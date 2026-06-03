"""Module 11 views: Purchase Order Management (buyer side).

Function-based views mirroring the contracts module: ``@login_required`` + a
``_require_manage`` / ``_require_view`` permission gate, ``_get_po`` scoped to
``request.tenant``, list search + filters + ``Paginator(qs, 20)``, and lifecycle
actions that delegate to :mod:`apps.purchase_orders.services` and surface
``ValidationError.messages`` back to the user.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.vendors.models import Vendor, VendorCategory

from . import services
from .forms import (
    AcknowledgePOForm,
    CancelPOForm,
    ChangeOrderForm,
    CloseoutForm,
    DeclinePOForm,
    IssuePOForm,
    PurchaseOrderDocumentForm,
    PurchaseOrderForm,
    PurchaseOrderLineForm,
    ReceiveLineForm,
)
from .models import (
    PO_STATUS_CHOICES,
    PurchaseOrder,
    PurchaseOrderChangeOrder,
    PurchaseOrderDocument,
    PurchaseOrderLine,
)


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
    if not services.can_manage_po(request.user):
        messages.error(request, 'You do not have permission to manage purchase orders.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_view(request):
    if not services.can_view_po(request.user):
        messages.error(request, 'You do not have permission to view purchase orders.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _get_po(request, pk):
    return get_object_or_404(PurchaseOrder, pk=pk, tenant=request.tenant)


# ---------------------------------------------------------------------------
# List + CRUD
# ---------------------------------------------------------------------------
@login_required
def po_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = PurchaseOrder.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'category', 'owner',
    )

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    vendor = request.GET.get('vendor', '')
    category = request.GET.get('category', '')

    if q:
        qs = qs.filter(
            Q(po_number__icontains=q)
            | Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(vendor__legal_name__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if vendor:
        qs = qs.filter(vendor_id=vendor)
    if category:
        qs = qs.filter(category_id=category)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    querystring = request.GET.copy()
    querystring.pop('page', None)

    context = {
        'page_obj': page_obj,
        'purchase_orders': page_obj.object_list,
        'q': q,
        'status_choices': PO_STATUS_CHOICES,
        'vendors': Vendor.objects.filter(tenant=request.tenant).order_by('legal_name'),
        'categories': VendorCategory.objects.filter(tenant=request.tenant, is_active=True),
        'querystring': querystring.urlencode(),
        'can_manage': services.can_manage_po(request.user),
    }
    return render(request, 'purchase_orders/po_list.html', context)


@login_required
def po_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    # 1. PO Generation — pre-fill from an approved requisition.
    from_req_pk = request.GET.get('from_requisition')
    if from_req_pk:
        from apps.requisitions.models import Requisition
        req = get_object_or_404(Requisition, pk=from_req_pk, tenant=request.tenant)
        if req.status == 'converted':
            messages.warning(
                request,
                f'{req.number} has already been converted to PO {req.po_reference}.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        if req.status != 'approved':
            messages.error(
                request, 'Only approved requisitions can be converted to a PO.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        po = services.create_po_from_requisition(req, request.user)
        messages.success(
            request,
            f'Purchase order {po.po_number} created from {req.number}. '
            'Assign the supplier and review the lines, then issue it.')
        return redirect('purchase_orders:po_detail', pk=po.pk)

    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            po = form.save(commit=False)
            po.tenant = request.tenant
            po.created_by = request.user
            if not po.owner_id:
                po.owner = request.user
            po.po_number = services.next_po_number(request.tenant)
            po.save()
            services.recompute_totals(po)
            services.record_status_event(po, 'draft', request.user, 'Purchase order created')
            services.record_audit(
                request.tenant, request.user, 'purchase_order.created',
                target_type='PurchaseOrder', target_id=str(po.pk),
                message=f'{po.po_number}: {po.title}', request=request,
            )
            messages.success(request, f'Purchase order {po.po_number} created.')
            return redirect('purchase_orders:po_detail', pk=po.pk)
    else:
        form = PurchaseOrderForm(tenant=request.tenant)

    return render(request, 'purchase_orders/po_form.html', {
        'form': form, 'is_edit': False,
    })


@login_required
def po_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    context = {
        'po': po,
        'lines': po.lines.select_related('account_code').all(),
        'change_orders': po.change_orders.all(),
        'documents': po.documents.select_related('uploaded_by').all(),
        'status_events': po.status_events.select_related('actor', 'change_order').all()[:30],
        'issue_form': IssuePOForm(),
        'ack_form': AcknowledgePOForm(),
        'decline_form': DeclinePOForm(),
        'cancel_form': CancelPOForm(),
        'closeout_form': CloseoutForm(),
        'document_form': PurchaseOrderDocumentForm(),
        'can_manage': services.can_manage_po(request.user),
    }
    return render(request, 'purchase_orders/po_detail.html', context)


@login_required
def po_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    if not po.is_editable:
        messages.error(request, 'Only draft purchase orders can be edited.')
        return redirect('purchase_orders:po_detail', pk=po.pk)

    if request.method == 'POST':
        form = PurchaseOrderForm(request.POST, instance=po, tenant=request.tenant)
        if form.is_valid():
            form.save()
            services.recompute_totals(po)
            services.record_audit(
                request.tenant, request.user, 'purchase_order.updated',
                target_type='PurchaseOrder', target_id=str(po.pk),
                message=f'{po.po_number} updated.', request=request,
            )
            messages.success(request, 'Purchase order updated.')
            return redirect('purchase_orders:po_detail', pk=po.pk)
    else:
        form = PurchaseOrderForm(instance=po, tenant=request.tenant)

    return render(request, 'purchase_orders/po_form.html', {
        'form': form, 'po': po, 'is_edit': True,
    })


@login_required
@require_POST
def po_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    if not po.is_editable:
        messages.error(request, 'Only draft purchase orders can be deleted.')
        return redirect('purchase_orders:po_detail', pk=po.pk)

    number = po.po_number
    services.record_audit(
        request.tenant, request.user, 'purchase_order.deleted', level='warning',
        target_type='PurchaseOrder', target_id=str(po.pk),
        message=f'{number} deleted.', request=request,
    )
    po.delete()
    messages.success(request, f'Purchase order {number} deleted.')
    return redirect('purchase_orders:po_list')


# ---------------------------------------------------------------------------
# Lifecycle transitions (POST)
# ---------------------------------------------------------------------------
@login_required
@require_POST
def po_issue(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    form = IssuePOForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Choose a dispatch method.')
        return redirect('purchase_orders:po_detail', pk=po.pk)
    try:
        services.issue_po(
            po, request.user,
            dispatch_method=form.cleaned_data['dispatch_method'],
            recipient_email=form.cleaned_data.get('recipient_email', ''),
        )
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('purchase_orders:po_detail', pk=po.pk)
    messages.success(request, f'{po.po_number} issued to the supplier.')
    return redirect('purchase_orders:po_detail', pk=po.pk)


@login_required
@require_POST
def po_acknowledge(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    form = AcknowledgePOForm(request.POST)
    note = form.cleaned_data.get('note', '') if form.is_valid() else ''
    try:
        services.acknowledge_po(po, request.user, note=note)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('purchase_orders:po_detail', pk=po.pk)
    messages.success(request, f'{po.po_number} acknowledged.')
    return redirect('purchase_orders:po_detail', pk=po.pk)


@login_required
@require_POST
def po_decline(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    form = DeclinePOForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('purchase_orders:po_detail', pk=po.pk)
    try:
        services.decline_po(po, request.user, form.cleaned_data['reason'])
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('purchase_orders:po_detail', pk=po.pk)
    messages.success(request, f'{po.po_number} marked declined.')
    return redirect('purchase_orders:po_detail', pk=po.pk)


@login_required
@require_POST
def po_reopen(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    try:
        services.reopen_po(po, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('purchase_orders:po_detail', pk=po.pk)
    messages.success(request, f'{po.po_number} reopened to draft.')
    return redirect('purchase_orders:po_detail', pk=po.pk)


@login_required
@require_POST
def po_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    form = CancelPOForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('purchase_orders:po_detail', pk=po.pk)
    try:
        services.cancel_po(po, request.user, form.cleaned_data['reason'])
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('purchase_orders:po_detail', pk=po.pk)
    messages.success(request, f'{po.po_number} cancelled.')
    return redirect('purchase_orders:po_detail', pk=po.pk)


@login_required
@require_POST
def po_close(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    form = CloseoutForm(request.POST)
    note = form.cleaned_data.get('note', '') if form.is_valid() else ''
    try:
        services.close_po(po, request.user, note=note)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('purchase_orders:po_detail', pk=po.pk)
    messages.success(request, f'{po.po_number} closed out.')
    return redirect('purchase_orders:po_detail', pk=po.pk)


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------
@login_required
def line_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    if not po.is_editable:
        messages.error(request, 'Line items can only be changed while the PO is a draft.')
        return redirect('purchase_orders:po_detail', pk=po.pk)

    if request.method == 'POST':
        form = PurchaseOrderLineForm(
            request.POST, tenant=request.tenant, purchase_order=po)
        if form.is_valid():
            line = form.save(commit=False)
            line.tenant = request.tenant
            line.purchase_order = po
            line.save()
            services.recompute_totals(po)
            messages.success(request, 'Line item added.')
            return redirect('purchase_orders:po_detail', pk=po.pk)
    else:
        next_no = (po.lines.count() or 0) + 1
        form = PurchaseOrderLineForm(
            tenant=request.tenant, purchase_order=po, initial={'line_no': next_no})

    return render(request, 'purchase_orders/po_line_form.html', {
        'form': form, 'po': po, 'is_edit': False,
    })


@login_required
def line_edit(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    line = get_object_or_404(
        PurchaseOrderLine, pk=line_pk, purchase_order=po, tenant=request.tenant)
    if not po.is_editable:
        messages.error(request, 'Line items can only be changed while the PO is a draft.')
        return redirect('purchase_orders:po_detail', pk=po.pk)

    if request.method == 'POST':
        form = PurchaseOrderLineForm(
            request.POST, instance=line, tenant=request.tenant, purchase_order=po)
        if form.is_valid():
            form.save()
            services.recompute_totals(po)
            messages.success(request, 'Line item updated.')
            return redirect('purchase_orders:po_detail', pk=po.pk)
    else:
        form = PurchaseOrderLineForm(
            instance=line, tenant=request.tenant, purchase_order=po)

    return render(request, 'purchase_orders/po_line_form.html', {
        'form': form, 'po': po, 'line': line, 'is_edit': True,
    })


@login_required
@require_POST
def line_delete(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    line = get_object_or_404(
        PurchaseOrderLine, pk=line_pk, purchase_order=po, tenant=request.tenant)
    if not po.is_editable:
        messages.error(request, 'Line items can only be changed while the PO is a draft.')
        return redirect('purchase_orders:po_detail', pk=po.pk)
    line.delete()
    services.recompute_totals(po)
    messages.success(request, 'Line item removed.')
    return redirect('purchase_orders:po_detail', pk=po.pk)


@login_required
@require_POST
def line_receive(request, pk, line_pk):
    """Record a goods receipt against a single line (5. Line item tracking)."""
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    line = get_object_or_404(
        PurchaseOrderLine, pk=line_pk, purchase_order=po, tenant=request.tenant)
    form = ReceiveLineForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Enter a valid received quantity.')
        return redirect('purchase_orders:po_detail', pk=po.pk)
    try:
        services.record_line_receipt(
            po, line, form.cleaned_data['received_quantity'], request.user)
        messages.success(request, f'Receipt recorded for line {line.line_no}.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('purchase_orders:po_detail', pk=po.pk)


# ---------------------------------------------------------------------------
# 3. Change orders
# ---------------------------------------------------------------------------
@login_required
def change_order_create(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    if not po.can_change_order:
        messages.error(request, 'Change orders apply only to an issued purchase order.')
        return redirect('purchase_orders:po_detail', pk=po.pk)

    if request.method == 'POST':
        form = ChangeOrderForm(request.POST)
        if form.is_valid():
            co = form.save(commit=False)
            co.tenant = request.tenant
            co.purchase_order = po
            co.created_by = request.user
            co.change_number = services.next_change_number(po)
            co.save()
            messages.success(
                request,
                f'Change order {co.change_number} drafted. Adjust the lines below, '
                'then apply it.')
            return redirect(
                'purchase_orders:change_order_detail', pk=po.pk, co_pk=co.pk)
    else:
        form = ChangeOrderForm(initial={
            'new_expected_delivery_date': po.expected_delivery_date,
        })

    return render(request, 'purchase_orders/po_change_order_form.html', {
        'form': form, 'po': po, 'is_edit': False,
    })


@login_required
def change_order_detail(request, pk, co_pk):
    denied = _require_view(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    co = get_object_or_404(
        PurchaseOrderChangeOrder, pk=co_pk, purchase_order=po, tenant=request.tenant)

    # While editable, the manager adjusts proposed line (qty, price) values.
    if request.method == 'POST' and co.is_editable and services.can_manage_po(request.user):
        proposed = []
        for line in po.lines.all():
            q = request.POST.get(f'line_{line.id}_quantity')
            p = request.POST.get(f'line_{line.id}_unit_price')
            item = {'line_id': line.id}
            changed = False
            if q not in (None, ''):
                item['quantity'] = q
                changed = True
            if p not in (None, ''):
                item['unit_price'] = p
                changed = True
            if changed:
                proposed.append(item)
        co.proposed_lines = proposed
        new_date = request.POST.get('new_expected_delivery_date')
        if new_date:
            co.new_expected_delivery_date = new_date
        reason = request.POST.get('reason')
        if reason is not None:
            co.reason = reason.strip()[:2000]
        co.save(update_fields=[
            'proposed_lines', 'new_expected_delivery_date', 'reason', 'updated_at'])
        messages.success(request, 'Proposed changes saved.')
        return redirect('purchase_orders:change_order_detail', pk=po.pk, co_pk=co.pk)

    # Attach any proposed (qty, price) values onto each line for the edit grid.
    proposed_map = {
        int(item['line_id']): item for item in (co.proposed_lines or [])
        if item.get('line_id') is not None
    }
    lines = list(po.lines.all())
    for line in lines:
        item = proposed_map.get(line.id) or {}
        line.proposed_quantity = item.get('quantity')
        line.proposed_unit_price = item.get('unit_price')
    return render(request, 'purchase_orders/po_change_order_detail.html', {
        'po': po, 'co': co,
        'lines': lines,
        'can_manage': services.can_manage_po(request.user),
    })


@login_required
@require_POST
def change_order_apply(request, pk, co_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    co = get_object_or_404(
        PurchaseOrderChangeOrder, pk=co_pk, purchase_order=po, tenant=request.tenant)
    try:
        services.apply_change_order(co, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('purchase_orders:change_order_detail', pk=po.pk, co_pk=co.pk)
    messages.success(request, f'Change order {co.change_number} applied.')
    return redirect('purchase_orders:po_detail', pk=po.pk)


@login_required
@require_POST
def change_order_cancel(request, pk, co_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    co = get_object_or_404(
        PurchaseOrderChangeOrder, pk=co_pk, purchase_order=po, tenant=request.tenant)
    try:
        services.cancel_change_order(co, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('purchase_orders:change_order_detail', pk=po.pk, co_pk=co.pk)
    messages.success(request, 'Change order cancelled.')
    return redirect('purchase_orders:po_detail', pk=po.pk)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@login_required
@require_POST
def document_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    form = PurchaseOrderDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.tenant = request.tenant
        doc.purchase_order = po
        doc.uploaded_by = request.user
        doc.save()
        services.record_audit(
            request.tenant, request.user, 'purchase_order.document.added',
            target_type='PurchaseOrder', target_id=str(po.pk),
            message=f'Document "{doc.title}" added to {po.po_number}.', request=request,
        )
        messages.success(request, 'Document uploaded.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect('purchase_orders:po_detail', pk=po.pk)


@login_required
@require_POST
def document_delete(request, pk, document_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    po = _get_po(request, pk)
    doc = get_object_or_404(
        PurchaseOrderDocument, pk=document_pk, purchase_order=po, tenant=request.tenant)
    title = doc.title
    doc.delete()
    services.record_audit(
        request.tenant, request.user, 'purchase_order.document.deleted', level='warning',
        target_type='PurchaseOrder', target_id=str(po.pk),
        message=f'Document "{title}" removed from {po.po_number}.', request=request,
    )
    messages.success(request, 'Document removed.')
    return redirect('purchase_orders:po_detail', pk=po.pk)


# ---------------------------------------------------------------------------
# Tracking board
# ---------------------------------------------------------------------------
@login_required
def po_tracking(request):
    denied = _require_view(request)
    if denied:
        return denied

    # Lazy sweep: raise awaiting-ack / overdue-delivery alerts before rendering.
    if services.can_manage_po(request.user):
        services.scan_po_alerts(tenant=request.tenant)

    base = PurchaseOrder.objects.filter(tenant=request.tenant).select_related('vendor')
    board = [
        ('draft', 'Draft', 'badge-soft-secondary',
         list(base.filter(status='draft').order_by('-created_at'))),
        ('issued', 'Issued', 'badge-soft-info',
         list(base.filter(status='issued').order_by('expected_delivery_date'))),
        ('acknowledged', 'Acknowledged', 'badge-soft-primary',
         list(base.filter(status='acknowledged').order_by('expected_delivery_date'))),
        ('partially_received', 'Partially received', 'badge-soft-warning',
         list(base.filter(status='partially_received').order_by('expected_delivery_date'))),
        ('received', 'Received', 'badge-soft-success',
         list(base.filter(status='received').order_by('-updated_at'))),
        ('closed', 'Closed', 'badge-soft-dark',
         list(base.filter(status='closed').order_by('-closed_at')[:50])),
    ]
    return render(request, 'purchase_orders/tracking.html', {
        'board': board,
        'can_manage': services.can_manage_po(request.user),
    })


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@login_required
def analytics_dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied

    metrics = services.tenant_po_metrics(request.tenant)
    recent = PurchaseOrder.objects.filter(tenant=request.tenant).select_related('vendor')[:10]
    return render(request, 'purchase_orders/analytics.html', {
        'metrics': metrics,
        'recent_pos': recent,
        'can_manage': services.can_manage_po(request.user),
    })
