"""Module 19 views: Inventory & Warehouse Integration.

Function-based views mirroring compliance/budget: ``@login_required`` + a ``_require_view`` /
``_require_manage`` permission gate, tenant-scoped lookups, list search + filters + ``Paginator``.

SECURITY (lessons.md D-01/D-02): EVERY read view calls ``_require_view`` first; every mutation calls
``_require_manage``; every object lookup is scoped to ``request.tenant`` (cross-tenant IDOR -> 404).
The dashboard lazily syncs newly-posted goods receipts into stock (the spend_analytics precedent).
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import F, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    CycleCountForm, GoodsIssueForm, GoodsIssueLineForm, StockAdjustForm, StockItemCreateForm,
    StockItemForm, WarehouseForm, WarehouseLocationForm,
)
from .models import (
    CYCLE_STATUS_CHOICES, CycleCount, GoodsIssue, ISSUE_STATUS_CHOICES, ISSUE_TYPE_CHOICES,
    MOVEMENT_TYPE_CHOICES, StockItem, StockMovement, Warehouse, WarehouseLocation,
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


def _require_view(request):
    if not services.can_view_inventory(request.user):
        messages.error(request, 'You do not have permission to view inventory.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_manage(request):
    if not services.can_manage_inventory(request.user):
        messages.error(request, 'You do not have permission to manage inventory.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _querystring(request, *drop):
    qs = request.GET.copy()
    for key in ('page',) + drop:
        qs.pop(key, None)
    return qs.urlencode()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied
    # Lazy sync: fold any newly-posted goods receipts into stock before rendering.
    if services.can_manage_inventory(request.user) and services._unsynced_receipt_count(
            request.tenant):
        services.sync_stock_from_receipts(request.tenant, actor=request.user)
    metrics = services.tenant_inventory_metrics(request.tenant)
    return render(request, 'inventory/dashboard.html', {
        'metrics': metrics,
        'can_manage': services.can_manage_inventory(request.user),
    })


# ---------------------------------------------------------------------------
# 1. Stock levels
# ---------------------------------------------------------------------------
@login_required
def stock_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = StockItem.objects.filter(tenant=request.tenant).select_related('catalog_item')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(sku__icontains=q) | Q(catalog_item__name__icontains=q)
                       | Q(catalog_item__item_number__icontains=q))
    warehouse = request.GET.get('warehouse', '')
    if warehouse:
        qs = qs.filter(levels__warehouse_id=warehouse).distinct()
    show = request.GET.get('show', '')
    if show == 'below':
        qs = qs.filter(is_stocked=True, reorder_point__gt=0,
                       quantity_on_hand__lte=F('reorder_point') + F('quantity_reserved'))
    elif show == 'out':
        qs = qs.filter(quantity_on_hand__lte=0)
    elif show == 'in':
        qs = qs.filter(quantity_on_hand__gt=0)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'inventory/stock/list.html', {
        'page_obj': page_obj, 'items': page_obj.object_list, 'q': q, 'warehouse': warehouse,
        'show': show, 'warehouses': Warehouse.objects.filter(tenant=request.tenant, is_active=True),
        'querystring': _querystring(request),
        'can_manage': services.can_manage_inventory(request.user),
    })


@login_required
def stock_item_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = StockItemCreateForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            item = form.save(commit=False)
            item.tenant = request.tenant
            item.catalog_item = form.cleaned_data['catalog_item']
            item.sku = item.catalog_item.sku
            item.save()
            messages.success(request, f'Stock item for {item.catalog_item.name} created.')
            return redirect('inventory:stock_item_detail', pk=item.pk)
    else:
        form = StockItemCreateForm(tenant=request.tenant)
    return render(request, 'inventory/stock/form.html', {'form': form, 'is_edit': False})


@login_required
def stock_item_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    item = get_object_or_404(
        StockItem.objects.select_related('catalog_item', 'default_warehouse', 'reorder_requisition'),
        pk=pk, tenant=request.tenant)
    levels = item.levels.select_related('warehouse', 'location').filter(quantity__gt=0)
    movements = (StockMovement.objects.filter(tenant=request.tenant, stock_item=item)
                 .select_related('warehouse', 'location')[:30])
    return render(request, 'inventory/stock/detail.html', {
        'item': item, 'levels': levels, 'movements': movements,
        'adjust_form': StockAdjustForm(tenant=request.tenant),
        'can_manage': services.can_manage_inventory(request.user),
    })


@login_required
def stock_item_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = get_object_or_404(StockItem, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = StockItemForm(request.POST, instance=item, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Stock item updated.')
            return redirect('inventory:stock_item_detail', pk=item.pk)
    else:
        form = StockItemForm(instance=item, tenant=request.tenant)
    return render(request, 'inventory/stock/form.html',
                  {'form': form, 'item': item, 'is_edit': True})


@login_required
@require_POST
def stock_item_adjust(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = get_object_or_404(StockItem, pk=pk, tenant=request.tenant)
    form = StockAdjustForm(request.POST, tenant=request.tenant)
    if form.is_valid():
        cd = form.cleaned_data
        try:
            services.adjust_stock(
                item, warehouse=cd['warehouse'], location=cd.get('location'),
                quantity=cd['quantity'], lot_number=cd.get('lot_number', ''),
                serial_number=cd.get('serial_number', ''), expiry_date=cd.get('expiry_date'),
                reason=cd.get('reason', ''), note=cd.get('note', ''), actor=request.user,
                request=request)
            messages.success(request, 'Stock adjusted.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
    else:
        messages.error(request, 'Could not adjust stock — check the form.')
    return redirect('inventory:stock_item_detail', pk=item.pk)


@login_required
@require_POST
def stock_item_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    item = get_object_or_404(StockItem, pk=pk, tenant=request.tenant)
    try:
        item.delete()
        messages.success(request, 'Stock item deleted.')
    except ProtectedError:
        messages.error(request, 'Cannot delete — this item has stock movements on the ledger.')
        return redirect('inventory:stock_item_detail', pk=item.pk)
    return redirect('inventory:stock_list')


# ---------------------------------------------------------------------------
# Movement ledger (read-only)
# ---------------------------------------------------------------------------
@login_required
def movement_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = (StockMovement.objects.filter(tenant=request.tenant)
          .select_related('stock_item__catalog_item', 'warehouse', 'location', 'actor'))
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(stock_item__sku__icontains=q)
                       | Q(stock_item__catalog_item__name__icontains=q))
    mtype = request.GET.get('type', '')
    if mtype:
        qs = qs.filter(movement_type=mtype)
    warehouse = request.GET.get('warehouse', '')
    if warehouse:
        qs = qs.filter(warehouse_id=warehouse)
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'inventory/movements/list.html', {
        'page_obj': page_obj, 'movements': page_obj.object_list, 'q': q, 'type': mtype,
        'warehouse': warehouse, 'type_choices': MOVEMENT_TYPE_CHOICES,
        'warehouses': Warehouse.objects.filter(tenant=request.tenant),
        'querystring': _querystring(request),
    })


@login_required
def movement_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    movement = get_object_or_404(
        StockMovement.objects.select_related('stock_item__catalog_item', 'warehouse', 'location',
                                             'to_location', 'actor'),
        pk=pk, tenant=request.tenant)
    return render(request, 'inventory/movements/detail.html', {'movement': movement})


# ---------------------------------------------------------------------------
# 4. Warehouses & locations
# ---------------------------------------------------------------------------
@login_required
def warehouse_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = Warehouse.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'inventory/warehouses/list.html', {
        'page_obj': page_obj, 'warehouses': page_obj.object_list, 'q': q,
        'querystring': _querystring(request),
        'can_manage': services.can_manage_inventory(request.user),
    })


@login_required
def warehouse_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = WarehouseForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            wh = form.save(commit=False)
            wh.tenant = request.tenant
            try:
                wh.save()
            except Exception:
                messages.error(request, 'That warehouse code already exists.')
            else:
                messages.success(request, 'Warehouse created.')
                return redirect('inventory:warehouse_detail', pk=wh.pk)
    else:
        form = WarehouseForm(tenant=request.tenant)
    return render(request, 'inventory/warehouses/form.html', {'form': form, 'is_edit': False})


@login_required
def warehouse_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    warehouse = get_object_or_404(Warehouse, pk=pk, tenant=request.tenant)
    return render(request, 'inventory/warehouses/detail.html', {
        'warehouse': warehouse,
        'locations': warehouse.locations.all(),
        'can_manage': services.can_manage_inventory(request.user),
    })


@login_required
def warehouse_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    warehouse = get_object_or_404(Warehouse, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = WarehouseForm(request.POST, instance=warehouse, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Warehouse updated.')
            return redirect('inventory:warehouse_detail', pk=warehouse.pk)
    else:
        form = WarehouseForm(instance=warehouse, tenant=request.tenant)
    return render(request, 'inventory/warehouses/form.html',
                  {'form': form, 'warehouse': warehouse, 'is_edit': True})


@login_required
@require_POST
def warehouse_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    warehouse = get_object_or_404(Warehouse, pk=pk, tenant=request.tenant)
    try:
        warehouse.delete()
        messages.success(request, 'Warehouse deleted.')
    except ProtectedError:
        messages.error(request, 'Cannot delete — this warehouse holds stock.')
        return redirect('inventory:warehouse_detail', pk=warehouse.pk)
    return redirect('inventory:warehouse_list')


@login_required
def location_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    warehouse = None
    wh_id = request.GET.get('warehouse') or request.POST.get('warehouse')
    if wh_id:
        warehouse = Warehouse.objects.filter(pk=wh_id, tenant=request.tenant).first()
    if request.method == 'POST':
        form = WarehouseLocationForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            loc = form.save(commit=False)
            loc.tenant = request.tenant
            try:
                loc.save()
            except Exception:
                messages.error(request, 'That bin code already exists in this warehouse.')
            else:
                messages.success(request, 'Location added.')
                return redirect('inventory:warehouse_detail', pk=loc.warehouse_id)
    else:
        form = WarehouseLocationForm(tenant=request.tenant,
                                     initial={'warehouse': warehouse} if warehouse else None)
    return render(request, 'inventory/locations/form.html',
                  {'form': form, 'warehouse': warehouse, 'is_edit': False})


@login_required
def location_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    location = get_object_or_404(WarehouseLocation, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = WarehouseLocationForm(request.POST, instance=location, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Location updated.')
            return redirect('inventory:warehouse_detail', pk=location.warehouse_id)
    else:
        form = WarehouseLocationForm(instance=location, tenant=request.tenant)
    return render(request, 'inventory/locations/form.html',
                  {'form': form, 'location': location, 'warehouse': location.warehouse,
                   'is_edit': True})


@login_required
@require_POST
def location_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    location = get_object_or_404(WarehouseLocation, pk=pk, tenant=request.tenant)
    wh_id = location.warehouse_id
    try:
        location.delete()
        messages.success(request, 'Location deleted.')
    except ProtectedError:
        messages.error(request, 'Cannot delete — this location holds stock.')
    return redirect('inventory:warehouse_detail', pk=wh_id)


# ---------------------------------------------------------------------------
# 3. Goods issues / returns
# ---------------------------------------------------------------------------
@login_required
def goods_issue_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = GoodsIssue.objects.filter(tenant=request.tenant).select_related('warehouse')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(purpose__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    issue_type = request.GET.get('issue_type', '')
    if issue_type:
        qs = qs.filter(issue_type=issue_type)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'inventory/issues/list.html', {
        'page_obj': page_obj, 'issues': page_obj.object_list, 'q': q, 'status': status,
        'issue_type': issue_type, 'status_choices': ISSUE_STATUS_CHOICES,
        'issue_type_choices': ISSUE_TYPE_CHOICES, 'querystring': _querystring(request),
        'can_manage': services.can_manage_inventory(request.user),
    })


@login_required
def goods_issue_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = GoodsIssueForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            cd = form.cleaned_data
            gi = services.create_goods_issue(
                request.tenant, warehouse=cd['warehouse'], issue_type=cd['issue_type'],
                user=request.user, purpose=cd.get('purpose', ''),
                department=cd.get('department', ''), cost_center=cd.get('cost_center', ''),
                note=cd.get('note', ''))
            messages.success(request, f'Goods issue {gi.number} created. Add lines, then post.')
            return redirect('inventory:goods_issue_detail', pk=gi.pk)
    else:
        form = GoodsIssueForm(tenant=request.tenant)
    return render(request, 'inventory/issues/form.html', {'form': form, 'is_edit': False})


@login_required
def goods_issue_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    gi = get_object_or_404(
        GoodsIssue.objects.select_related('warehouse', 'requested_by', 'issued_by'),
        pk=pk, tenant=request.tenant)
    return render(request, 'inventory/issues/detail.html', {
        'gi': gi,
        'lines': gi.lines.select_related('stock_item__catalog_item', 'location'),
        'events': gi.events.select_related('actor'),
        'line_form': GoodsIssueLineForm(tenant=request.tenant),
        'can_manage': services.can_manage_inventory(request.user),
    })


@login_required
def goods_issue_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    gi = get_object_or_404(GoodsIssue, pk=pk, tenant=request.tenant)
    if not gi.is_editable:
        messages.error(request, 'Only a draft goods issue can be edited.')
        return redirect('inventory:goods_issue_detail', pk=gi.pk)
    if request.method == 'POST':
        form = GoodsIssueForm(request.POST, instance=gi, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Goods issue updated.')
            return redirect('inventory:goods_issue_detail', pk=gi.pk)
    else:
        form = GoodsIssueForm(instance=gi, tenant=request.tenant)
    return render(request, 'inventory/issues/form.html', {'form': form, 'gi': gi, 'is_edit': True})


@login_required
@require_POST
def goods_issue_line_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    gi = get_object_or_404(GoodsIssue, pk=pk, tenant=request.tenant)
    form = GoodsIssueLineForm(request.POST, tenant=request.tenant)
    if form.is_valid():
        cd = form.cleaned_data
        try:
            services.add_goods_issue_line(
                gi, stock_item=cd['stock_item'], quantity=cd['quantity'],
                location=cd.get('location'), lot_number=cd.get('lot_number', ''),
                serial_number=cd.get('serial_number', ''), expiry_date=cd.get('expiry_date'),
                note=cd.get('note', ''))
            messages.success(request, 'Line added.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
    else:
        messages.error(request, 'Could not add line — check the form.')
    return redirect('inventory:goods_issue_detail', pk=gi.pk)


@login_required
@require_POST
def goods_issue_line_delete(request, pk, lpk):
    denied = _require_manage(request)
    if denied:
        return denied
    gi = get_object_or_404(GoodsIssue, pk=pk, tenant=request.tenant)
    if not gi.is_editable:
        messages.error(request, 'Only a draft goods issue can be edited.')
        return redirect('inventory:goods_issue_detail', pk=gi.pk)
    line = get_object_or_404(gi.lines, pk=lpk)
    line.delete()
    messages.success(request, 'Line removed.')
    return redirect('inventory:goods_issue_detail', pk=gi.pk)


@login_required
@require_POST
def goods_issue_post(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    gi = get_object_or_404(GoodsIssue, pk=pk, tenant=request.tenant)
    try:
        services.post_goods_issue(gi, request.user, request=request)
        messages.success(request, f'{gi.number} posted to the stock ledger.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('inventory:goods_issue_detail', pk=gi.pk)


@login_required
@require_POST
def goods_issue_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    gi = get_object_or_404(GoodsIssue, pk=pk, tenant=request.tenant)
    try:
        services.cancel_goods_issue(gi, request.user, note=request.POST.get('note', ''),
                                    request=request)
        messages.success(request, f'{gi.number} cancelled.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('inventory:goods_issue_detail', pk=gi.pk)


@login_required
@require_POST
def goods_issue_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    gi = get_object_or_404(GoodsIssue, pk=pk, tenant=request.tenant)
    if gi.status != 'draft':
        messages.error(request, 'Only a draft goods issue can be deleted.')
        return redirect('inventory:goods_issue_detail', pk=gi.pk)
    number = gi.number
    gi.delete()
    messages.success(request, f'{number} deleted.')
    return redirect('inventory:goods_issue_list')


# ---------------------------------------------------------------------------
# 5. Cycle counts
# ---------------------------------------------------------------------------
@login_required
def cycle_count_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = CycleCount.objects.filter(tenant=request.tenant).select_related('warehouse')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(number__icontains=q)
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    warehouse = request.GET.get('warehouse', '')
    if warehouse:
        qs = qs.filter(warehouse_id=warehouse)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'inventory/cycle_counts/list.html', {
        'page_obj': page_obj, 'counts': page_obj.object_list, 'q': q, 'status': status,
        'warehouse': warehouse, 'status_choices': CYCLE_STATUS_CHOICES,
        'warehouses': Warehouse.objects.filter(tenant=request.tenant),
        'querystring': _querystring(request),
        'can_manage': services.can_manage_inventory(request.user),
    })


@login_required
def cycle_count_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = CycleCountForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            cd = form.cleaned_data
            cc = services.create_cycle_count(
                request.tenant, warehouse=cd['warehouse'], scope=cd['scope'],
                scheduled_date=cd.get('scheduled_date'), user=request.user,
                note=cd.get('note', ''))
            messages.success(
                request, f'Cycle count {cc.number} created with {cc.line_count} line(s) to count.')
            return redirect('inventory:cycle_count_detail', pk=cc.pk)
    else:
        form = CycleCountForm(tenant=request.tenant)
    return render(request, 'inventory/cycle_counts/form.html', {'form': form, 'is_edit': False})


@login_required
def cycle_count_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    cc = get_object_or_404(
        CycleCount.objects.select_related('warehouse', 'counted_by', 'posted_by'),
        pk=pk, tenant=request.tenant)
    return render(request, 'inventory/cycle_counts/detail.html', {
        'cc': cc,
        'lines': cc.lines.select_related('stock_item__catalog_item', 'location'),
        'events': cc.events.select_related('actor'),
        'can_manage': services.can_manage_inventory(request.user),
    })


@login_required
def cycle_count_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    cc = get_object_or_404(CycleCount, pk=pk, tenant=request.tenant)
    if not cc.is_editable:
        messages.error(request, 'This cycle count can no longer be edited.')
        return redirect('inventory:cycle_count_detail', pk=cc.pk)
    if request.method == 'POST':
        form = CycleCountForm(request.POST, instance=cc, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cycle count updated.')
            return redirect('inventory:cycle_count_detail', pk=cc.pk)
    else:
        form = CycleCountForm(instance=cc, tenant=request.tenant)
    return render(request, 'inventory/cycle_counts/form.html', {'form': form, 'cc': cc,
                                                                'is_edit': True})


@login_required
@require_POST
def cycle_count_count(request, pk):
    """Save the entered counted quantities (one ``count_<line_id>`` field per line)."""
    denied = _require_manage(request)
    if denied:
        return denied
    cc = get_object_or_404(CycleCount, pk=pk, tenant=request.tenant)
    if not cc.is_editable:
        messages.error(request, 'This cycle count can no longer be edited.')
        return redirect('inventory:cycle_count_detail', pk=cc.pk)
    saved = 0
    for line in cc.lines.all():
        raw = request.POST.get(f'count_{line.pk}', '').strip()
        if raw == '':
            continue
        try:
            services.set_cycle_count_line(line, Decimal(raw))
            saved += 1
        except (InvalidOperation, ValidationError):
            messages.error(request, f'Invalid count for line {line.pk}.')
    messages.success(request, f'{saved} count(s) saved.')
    return redirect('inventory:cycle_count_detail', pk=cc.pk)


@login_required
@require_POST
def cycle_count_post(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    cc = get_object_or_404(CycleCount, pk=pk, tenant=request.tenant)
    try:
        services.post_cycle_count(cc, request.user, request=request)
        messages.success(request, f'{cc.number} posted — stock reconciled.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('inventory:cycle_count_detail', pk=cc.pk)


@login_required
@require_POST
def cycle_count_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    cc = get_object_or_404(CycleCount, pk=pk, tenant=request.tenant)
    try:
        services.cancel_cycle_count(cc, request.user, note=request.POST.get('note', ''),
                                    request=request)
        messages.success(request, f'{cc.number} cancelled.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('inventory:cycle_count_detail', pk=cc.pk)


@login_required
@require_POST
def cycle_count_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    cc = get_object_or_404(CycleCount, pk=pk, tenant=request.tenant)
    if not cc.is_editable:
        messages.error(request, 'Only a draft/counting cycle count can be deleted.')
        return redirect('inventory:cycle_count_detail', pk=cc.pk)
    number = cc.number
    cc.delete()
    messages.success(request, f'{number} deleted.')
    return redirect('inventory:cycle_count_list')


# ---------------------------------------------------------------------------
# 2. Reorder automation
# ---------------------------------------------------------------------------
@login_required
def reorder_board(request):
    denied = _require_view(request)
    if denied:
        return denied
    below = [si for si in StockItem.objects.filter(tenant=request.tenant, is_stocked=True)
             .select_related('catalog_item', 'reorder_requisition') if si.is_below_reorder]
    recent = (StockItem.objects.filter(tenant=request.tenant, reorder_requisition__isnull=False)
              .select_related('catalog_item', 'reorder_requisition')
              .order_by('-last_reordered_at')[:20])
    return render(request, 'inventory/reorder/board.html', {
        'below': below, 'recent': recent,
        'can_manage': services.can_manage_inventory(request.user),
    })


@login_required
@require_POST
def reorder_run(request):
    denied = _require_manage(request)
    if denied:
        return denied
    created = services.run_reorder_automation(request.tenant, actor=request.user, request=request)
    if created:
        messages.success(request, f'{created} reorder requisition(s) created.')
    else:
        messages.info(request, 'No reorder needed — nothing at/below its reorder point.')
    return redirect('inventory:reorder_board')
