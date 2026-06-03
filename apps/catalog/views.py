"""Module 10 views: Catalog Management (buyer side).

Function-based views mirroring the contracts module: ``@login_required`` + a
``_require_manage`` / ``_require_view`` permission gate, ``_get_item`` scoped to
``request.tenant``, list search + filters + ``Paginator(qs, 20)``, and lifecycle
actions that delegate to :mod:`apps.catalog.services` and surface
``ValidationError.messages`` back to the user.

The inbound punch-out endpoint (``punchout_return``) is intentionally
``@csrf_exempt`` (a cross-site supplier POST) and is authenticated by the
unguessable session ``return_token`` plus the connector's credential check.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.models import set_current_tenant

from . import services
from .forms import (
    CatalogCategoryForm,
    CatalogItemForm,
    CatalogPriceChangeForm,
    CatalogPriceTierForm,
    RejectForm,
    RetireForm,
    SupplierPunchoutConfigForm,
)
from .models import (
    CATALOG_ITEM_STATUS_CHOICES,
    ITEM_SOURCE_CHOICES,
    CatalogCategory,
    CatalogItem,
    CatalogPriceChangeRequest,
    CatalogPriceTier,
    PunchoutSession,
    SupplierCatalogUpload,
    SupplierPunchoutConfig,
)
from .punchout import get_connector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _has_named_url(name):
    try:
        reverse(name)
        return True
    except Exception:
        return False


def _require_manage(request):
    if not services.can_manage_catalog(request.user):
        messages.error(request, 'You do not have permission to manage the catalog.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_view(request):
    if not services.can_view_catalog(request.user):
        messages.error(request, 'You do not have permission to view the catalog.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _get_item(request, pk):
    return get_object_or_404(CatalogItem, pk=pk, tenant=request.tenant)


# ---------------------------------------------------------------------------
# Catalog item list + CRUD
# ---------------------------------------------------------------------------
@login_required
def item_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = CatalogItem.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'category')

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    source = request.GET.get('source', '')
    category = request.GET.get('category', '')

    if q:
        qs = qs.filter(
            Q(item_number__icontains=q)
            | Q(name__icontains=q)
            | Q(sku__icontains=q)
            | Q(keywords__icontains=q)
            | Q(vendor__legal_name__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if source:
        qs = qs.filter(source=source)
    if category:
        qs = qs.filter(category_id=category)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    querystring = request.GET.copy()
    querystring.pop('page', None)

    return render(request, 'catalog/item_list.html', {
        'page_obj': page_obj,
        'items': page_obj.object_list,
        'q': q,
        'status_choices': CATALOG_ITEM_STATUS_CHOICES,
        'source_choices': ITEM_SOURCE_CHOICES,
        'categories': CatalogCategory.objects.filter(tenant=request.tenant, is_active=True),
        'querystring': querystring.urlencode(),
        'can_manage': services.can_manage_catalog(request.user),
    })


@login_required
def item_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    if request.method == 'POST':
        form = CatalogItemForm(request.POST, request.FILES, tenant=request.tenant)
        if form.is_valid():
            item = services.create_item(
                tenant=request.tenant, user=request.user, **form.cleaned_data)
            messages.success(request, f'Catalog item {item.item_number} created.')
            return redirect('catalog:item_detail', pk=item.pk)
    else:
        form = CatalogItemForm(tenant=request.tenant)

    return render(request, 'catalog/item_form.html', {'form': form, 'is_edit': False})


@login_required
def item_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    item = _get_item(request, pk)
    return render(request, 'catalog/item_detail.html', {
        'item': item,
        'tiers': item.price_tiers.select_related('contract').all(),
        'price_changes': item.price_change_requests.all(),
        'status_events': item.status_events.select_related('actor').all()[:30],
        'effective_price': services.resolve_price(item, qty=item.min_order_qty),
        'reject_form': RejectForm(),
        'retire_form': RetireForm(),
        'can_manage': services.can_manage_catalog(request.user),
    })


@login_required
def item_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    item = _get_item(request, pk)
    if not item.is_editable:
        messages.error(request, 'Only draft or rejected items can be edited.')
        return redirect('catalog:item_detail', pk=item.pk)

    if request.method == 'POST':
        form = CatalogItemForm(request.POST, request.FILES, instance=item,
                               tenant=request.tenant)
        if form.is_valid():
            form.save()
            services.record_audit(
                request.tenant, request.user, 'catalog.item.updated',
                target_type='CatalogItem', target_id=str(item.pk),
                message=f'{item.item_number} updated.', request=request)
            messages.success(request, 'Catalog item updated.')
            return redirect('catalog:item_detail', pk=item.pk)
    else:
        form = CatalogItemForm(instance=item, tenant=request.tenant)

    return render(request, 'catalog/item_form.html', {
        'form': form, 'item': item, 'is_edit': True,
    })


@login_required
@require_POST
def item_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    item = _get_item(request, pk)
    if not item.is_editable:
        messages.error(request, 'Only draft or rejected items can be deleted.')
        return redirect('catalog:item_detail', pk=item.pk)

    number = item.item_number
    services.record_audit(
        request.tenant, request.user, 'catalog.item.deleted', level='warning',
        target_type='CatalogItem', target_id=str(item.pk),
        message=f'{number} deleted.', request=request)
    item.delete()
    messages.success(request, f'Catalog item {number} deleted.')
    return redirect('catalog:item_list')


# ---------------------------------------------------------------------------
# Item lifecycle (POST)
# ---------------------------------------------------------------------------
@login_required
@require_POST
def item_submit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    try:
        services.submit_item_for_approval(item, request.user)
        messages.success(request, f'{item.item_number} submitted for approval.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('catalog:item_detail', pk=item.pk)


@login_required
@require_POST
def item_approve(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    try:
        services.approve_item(item, request.user)
        messages.success(request, f'{item.item_number} approved.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('catalog:item_detail', pk=item.pk)


@login_required
@require_POST
def item_reject(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    form = RejectForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Please give a reason for rejection.')
        return redirect('catalog:item_detail', pk=item.pk)
    try:
        services.reject_item(item, request.user, form.cleaned_data['reason'])
        messages.success(request, f'{item.item_number} rejected.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('catalog:item_detail', pk=item.pk)


@login_required
@require_POST
def item_retire(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    form = RetireForm(request.POST)
    reason = form.cleaned_data['reason'] if form.is_valid() else ''
    try:
        services.retire_item(item, request.user, reason)
        messages.success(request, f'{item.item_number} retired.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('catalog:item_detail', pk=item.pk)


@login_required
@require_POST
def item_archive(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    try:
        services.archive_item(item, request.user)
        messages.success(request, f'{item.item_number} archived.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('catalog:item_detail', pk=item.pk)


# ---------------------------------------------------------------------------
# Price tiers (direct edit while the item is a draft/rejected)
# ---------------------------------------------------------------------------
def _require_editable_item(request, item):
    if not item.is_editable:
        messages.error(
            request,
            'Tiers can be edited directly only while the item is a draft. '
            'Use a price-change request for an approved item.')
        return redirect('catalog:item_detail', pk=item.pk)
    return None


@login_required
def tier_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    blocked = _require_editable_item(request, item)
    if blocked:
        return blocked

    if request.method == 'POST':
        form = CatalogPriceTierForm(request.POST, tenant=request.tenant, item=item)
        if form.is_valid():
            tier = form.save(commit=False)
            tier.tenant = request.tenant
            tier.item = item
            tier.save()
            messages.success(request, 'Price tier added.')
            return redirect('catalog:item_detail', pk=item.pk)
    else:
        form = CatalogPriceTierForm(tenant=request.tenant, item=item)
    return render(request, 'catalog/tier_form.html', {
        'form': form, 'item': item, 'is_edit': False,
    })


@login_required
def tier_edit(request, pk, tier_pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    tier = get_object_or_404(CatalogPriceTier, pk=tier_pk, item=item, tenant=request.tenant)
    blocked = _require_editable_item(request, item)
    if blocked:
        return blocked

    if request.method == 'POST':
        form = CatalogPriceTierForm(request.POST, instance=tier,
                                    tenant=request.tenant, item=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'Price tier updated.')
            return redirect('catalog:item_detail', pk=item.pk)
    else:
        form = CatalogPriceTierForm(instance=tier, tenant=request.tenant, item=item)
    return render(request, 'catalog/tier_form.html', {
        'form': form, 'item': item, 'tier': tier, 'is_edit': True,
    })


@login_required
@require_POST
def tier_delete(request, pk, tier_pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    tier = get_object_or_404(CatalogPriceTier, pk=tier_pk, item=item, tenant=request.tenant)
    blocked = _require_editable_item(request, item)
    if blocked:
        return blocked
    tier.delete()
    messages.success(request, 'Price tier removed.')
    return redirect('catalog:item_detail', pk=item.pk)


# ---------------------------------------------------------------------------
# Price-change requests (review price edits to an approved item)
# ---------------------------------------------------------------------------
@login_required
def price_change_create(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    if item.status != 'approved':
        messages.error(request, 'Price changes apply to approved items only.')
        return redirect('catalog:item_detail', pk=item.pk)

    if request.method == 'POST':
        form = CatalogPriceChangeForm(request.POST)
        if form.is_valid():
            pc = form.save(commit=False)
            pc.tenant = request.tenant
            pc.item = item
            pc.created_by = request.user
            pc.request_number = services.next_price_change_number(item)
            pc.save()
            messages.success(request, f'Price-change request {pc.request_number} drafted.')
            return redirect('catalog:price_change_detail', pk=item.pk, pc_pk=pc.pk)
    else:
        form = CatalogPriceChangeForm(initial={'new_base_price': item.base_price})

    return render(request, 'catalog/price_change_form.html', {
        'form': form, 'item': item,
    })


@login_required
def price_change_detail(request, pk, pc_pk):
    denied = _require_view(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    pc = get_object_or_404(CatalogPriceChangeRequest, pk=pc_pk, item=item,
                           tenant=request.tenant)
    return render(request, 'catalog/price_change_detail.html', {
        'item': item, 'pc': pc, 'reject_form': RejectForm(),
        'can_manage': services.can_manage_catalog(request.user),
    })


@login_required
@require_POST
def price_change_submit(request, pk, pc_pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    pc = get_object_or_404(CatalogPriceChangeRequest, pk=pc_pk, item=item,
                           tenant=request.tenant)
    try:
        services.submit_price_change(pc, request.user)
        messages.success(request, f'{pc.request_number} submitted for approval.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('catalog:price_change_detail', pk=item.pk, pc_pk=pc.pk)


@login_required
@require_POST
def price_change_apply(request, pk, pc_pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    pc = get_object_or_404(CatalogPriceChangeRequest, pk=pc_pk, item=item,
                           tenant=request.tenant)
    try:
        services.apply_price_change(pc, request.user)
        messages.success(request, f'{pc.request_number} approved and applied.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('catalog:price_change_detail', pk=item.pk, pc_pk=pc.pk)
    return redirect('catalog:item_detail', pk=item.pk)


@login_required
@require_POST
def price_change_reject(request, pk, pc_pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    pc = get_object_or_404(CatalogPriceChangeRequest, pk=pc_pk, item=item,
                           tenant=request.tenant)
    form = RejectForm(request.POST)
    reason = form.cleaned_data['reason'] if form.is_valid() else ''
    try:
        services.reject_price_change(pc, request.user, reason)
        messages.success(request, f'{pc.request_number} rejected.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('catalog:price_change_detail', pk=item.pk, pc_pk=pc.pk)


@login_required
@require_POST
def price_change_cancel(request, pk, pc_pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    pc = get_object_or_404(CatalogPriceChangeRequest, pk=pc_pk, item=item,
                           tenant=request.tenant)
    try:
        services.cancel_price_change(pc, request.user)
        messages.success(request, f'{pc.request_number} cancelled.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('catalog:item_detail', pk=item.pk)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
@login_required
def category_list(request):
    denied = _require_manage(request)
    if denied:
        return denied
    qs = CatalogCategory.objects.filter(tenant=request.tenant).select_related('parent')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    querystring = request.GET.copy()
    querystring.pop('page', None)
    return render(request, 'catalog/category_list.html', {
        'page_obj': page_obj, 'categories': page_obj.object_list, 'q': q,
        'querystring': querystring.urlencode(),
    })


@login_required
def category_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = CatalogCategoryForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            category = form.save(commit=False)
            category.tenant = request.tenant
            category.save()
            messages.success(request, 'Category created.')
            return redirect('catalog:category_list')
    else:
        form = CatalogCategoryForm(tenant=request.tenant)
    return render(request, 'catalog/category_form.html', {'form': form, 'is_edit': False})


@login_required
def category_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    category = get_object_or_404(CatalogCategory, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = CatalogCategoryForm(request.POST, instance=category, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category updated.')
            return redirect('catalog:category_list')
    else:
        form = CatalogCategoryForm(instance=category, tenant=request.tenant)
    return render(request, 'catalog/category_form.html', {
        'form': form, 'category': category, 'is_edit': True,
    })


@login_required
@require_POST
def category_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    category = get_object_or_404(CatalogCategory, pk=pk, tenant=request.tenant)
    category.delete()
    messages.success(request, 'Category removed.')
    return redirect('catalog:category_list')


# ---------------------------------------------------------------------------
# Approval board
# ---------------------------------------------------------------------------
@login_required
def approval_board(request):
    denied = _require_view(request)
    if denied:
        return denied
    base = CatalogItem.objects.filter(tenant=request.tenant).select_related('vendor', 'category')
    board = [
        ('draft', 'Draft', 'badge-soft-secondary',
         list(base.filter(status='draft').order_by('-created_at')[:50])),
        ('pending_approval', 'Pending approval', 'badge-soft-info',
         list(base.filter(status='pending_approval').order_by('submitted_at'))),
        ('approved', 'Approved', 'badge-soft-success',
         list(base.filter(status='approved').order_by('-approved_at')[:50])),
        ('rejected', 'Rejected', 'badge-soft-danger',
         list(base.filter(status='rejected').order_by('-rejected_at')[:50])),
    ]
    return render(request, 'catalog/approval_board.html', {
        'board': board, 'can_manage': services.can_manage_catalog(request.user),
    })


# ---------------------------------------------------------------------------
# Punch-out configuration + sessions
# ---------------------------------------------------------------------------
@login_required
def punchout_config_list(request):
    denied = _require_manage(request)
    if denied:
        return denied
    configs = SupplierPunchoutConfig.objects.filter(
        tenant=request.tenant).select_related('vendor')
    return render(request, 'catalog/punchout_config_list.html', {
        'configs': configs,
        'sessions': PunchoutSession.objects.filter(
            tenant=request.tenant).select_related('vendor')[:10],
    })


@login_required
def punchout_config_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = SupplierPunchoutConfigForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            config = form.save(commit=False)
            config.tenant = request.tenant
            config.save()
            messages.success(request, 'Punch-out supplier configured.')
            return redirect('catalog:punchout_config_list')
    else:
        form = SupplierPunchoutConfigForm(tenant=request.tenant)
    return render(request, 'catalog/punchout_config_form.html', {
        'form': form, 'is_edit': False,
    })


@login_required
def punchout_config_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    config = get_object_or_404(SupplierPunchoutConfig, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = SupplierPunchoutConfigForm(request.POST, instance=config, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Punch-out supplier updated.')
            return redirect('catalog:punchout_config_list')
    else:
        form = SupplierPunchoutConfigForm(instance=config, tenant=request.tenant)
    return render(request, 'catalog/punchout_config_form.html', {
        'form': form, 'config': config, 'is_edit': True,
    })


@login_required
@require_POST
def punchout_config_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    config = get_object_or_404(SupplierPunchoutConfig, pk=pk, tenant=request.tenant)
    config.delete()
    messages.success(request, 'Punch-out supplier removed.')
    return redirect('catalog:punchout_config_list')


@login_required
@require_POST
def punchout_start(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    config = get_object_or_404(
        SupplierPunchoutConfig, pk=pk, tenant=request.tenant, is_active=True)

    def _build_return_url(token):
        return request.build_absolute_uri(
            reverse('catalog:punchout_return', kwargs={'token': token}))

    try:
        session = services.start_punchout(
            config, request.user, build_return_url=_build_return_url)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('catalog:punchout_config_list')
    return redirect('catalog:punchout_redirect', pk=session.pk)


@login_required
def punchout_redirect(request, pk):
    """Bridge the buyer's browser to the supplier (302 for cXML, auto-form for OCI)."""
    denied = _require_manage(request)
    if denied:
        return denied
    session = get_object_or_404(PunchoutSession, pk=pk, tenant=request.tenant)
    connector = get_connector(session.config)
    return_url = request.build_absolute_uri(
        reverse('catalog:punchout_return', kwargs={'token': session.return_token}))
    descriptor = connector.build_setup(
        config=session.config, session=session, return_url=return_url)

    if descriptor.server_post:
        # cXML: the StartPage was fetched at setup; redirect straight there.
        if session.start_page_url:
            return redirect(session.start_page_url)
        messages.error(request, 'Punch-out did not return a start page.')
        return redirect('catalog:punchout_config_list')

    if session.status == 'initiated':
        session.status = 'redirected'
        session.save(update_fields=['status', 'updated_at'])
    return render(request, 'catalog/punchout_redirect.html', {
        'session': session,
        'action': descriptor.url,
        'method': descriptor.method,
        'fields': descriptor.fields,
    })


@csrf_exempt
def punchout_return(request, token):
    """Inbound PunchOutOrderMessage / OCI return — authenticated by ``token``.

    WARNING: ``@csrf_exempt`` is required for the cross-site supplier POST. The
    only authenticators are the unguessable ``return_token`` resolved here and the
    connector's inbound credential check inside ``receive_punchout_order``.
    """
    if request.method != 'POST':
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')

    session = (
        PunchoutSession.all_objects
        .select_related('config', 'vendor')
        .filter(return_token=token)
        .first()
    )
    if not session:
        # Opaque 404 — never reveal whether a token exists.
        return render(request, 'catalog/punchout_return_error.html',
                      {'ok': False, 'message': 'Invalid or expired punch-out link.'},
                      status=404)

    set_current_tenant(session.tenant)
    try:
        services.receive_punchout_order(request, session)
    except ValidationError as exc:
        return render(request, 'catalog/punchout_return_error.html', {
            'ok': False, 'session': session, 'message': '; '.join(exc.messages),
        }, status=400)
    return render(request, 'catalog/punchout_return_error.html', {
        'ok': True, 'session': session,
        'message': f'{session.line_count} item(s) received.',
    })


@login_required
def punchout_session_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    sessions = PunchoutSession.objects.filter(
        tenant=request.tenant).select_related('vendor', 'config')
    return render(request, 'catalog/punchout_session_list.html', {'sessions': sessions})


@login_required
def punchout_session_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    session = get_object_or_404(PunchoutSession, pk=pk, tenant=request.tenant)
    from apps.requisitions.models import Requisition
    requisitions = Requisition.objects.filter(
        tenant=request.tenant, status='draft').order_by('-created_at')[:50]
    return render(request, 'catalog/punchout_session_detail.html', {
        'session': session, 'requisitions': requisitions,
        'can_manage': services.can_manage_catalog(request.user),
    })


@login_required
@require_POST
def punchout_to_requisition(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    session = get_object_or_404(PunchoutSession, pk=pk, tenant=request.tenant)
    if session.status != 'returned' or not session.cart_data:
        messages.error(request, 'This session has no cart to convert.')
        return redirect('catalog:punchout_session_detail', pk=session.pk)
    from apps.requisitions.models import Requisition
    requisition = get_object_or_404(
        Requisition, pk=request.POST.get('requisition'), tenant=request.tenant)
    count = services.cart_to_requisition_lines(session, requisition, request.user)
    messages.success(request, f'{count} line(s) added to {requisition.number}.')
    return redirect('catalog:punchout_session_detail', pk=session.pk)


@login_required
@require_POST
def punchout_to_items(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    session = get_object_or_404(PunchoutSession, pk=pk, tenant=request.tenant)
    if session.status != 'returned' or not session.cart_data:
        messages.error(request, 'This session has no cart to convert.')
        return redirect('catalog:punchout_session_detail', pk=session.pk)
    items = services.cart_to_staged_items(session, request.user)
    messages.success(request, f'{len(items)} draft catalog item(s) staged for approval.')
    return redirect('catalog:punchout_session_detail', pk=session.pk)


# ---------------------------------------------------------------------------
# Supplier uploads (buyer review side)
# ---------------------------------------------------------------------------
@login_required
def upload_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    uploads = SupplierCatalogUpload.objects.filter(
        tenant=request.tenant).select_related('vendor', 'uploaded_by')
    return render(request, 'catalog/upload_list.html', {
        'uploads': uploads, 'can_manage': services.can_manage_catalog(request.user),
    })


@login_required
def upload_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    upload = get_object_or_404(SupplierCatalogUpload, pk=pk, tenant=request.tenant)
    return render(request, 'catalog/upload_detail.html', {
        'upload': upload,
        'staged_items': upload.staged_items.all(),
        'can_manage': services.can_manage_catalog(request.user),
    })


@login_required
@require_POST
def upload_process(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    upload = get_object_or_404(SupplierCatalogUpload, pk=pk, tenant=request.tenant)
    if not upload.is_open:
        messages.error(request, 'This upload has already been processed.')
        return redirect('catalog:upload_detail', pk=upload.pk)
    services.process_catalog_upload(upload, request.user)
    messages.success(
        request,
        f'Processed: {upload.imported_count} staged, {upload.error_count} error(s).')
    return redirect('catalog:upload_detail', pk=upload.pk)


@login_required
@require_POST
def upload_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    upload = get_object_or_404(SupplierCatalogUpload, pk=pk, tenant=request.tenant)
    upload.delete()
    messages.success(request, 'Upload removed.')
    return redirect('catalog:upload_list')


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@login_required
def analytics_dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied
    metrics = services.tenant_catalog_metrics(request.tenant)
    recent = CatalogItem.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'category')[:10]
    return render(request, 'catalog/analytics_dashboard.html', {
        'metrics': metrics, 'recent_items': recent,
        'can_manage': services.can_manage_catalog(request.user),
    })


@login_required
def item_analytics(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    item = _get_item(request, pk)
    return render(request, 'catalog/item_analytics.html', {
        'item': item, 'analytics': services.catalog_item_analytics(item),
        'can_manage': services.can_manage_catalog(request.user),
    })
