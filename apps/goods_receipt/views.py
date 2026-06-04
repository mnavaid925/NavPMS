"""Module 13 views: Goods Receipt & Inspection (buyer / internal side).

Function-based views mirroring the purchase_orders / fulfillment modules:
``@login_required`` + a ``_require_manage`` / ``_require_view`` permission gate,
``_get_grn`` scoped to ``request.tenant``, list search + filters + ``Paginator(qs, 20)``,
and lifecycle actions that delegate to :mod:`apps.goods_receipt.services` and surface
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

from apps.purchase_orders.models import PO_CHANGE_ORDERABLE_STATUSES, PurchaseOrder
from apps.fulfillment.models import Shipment
from apps.vendors.models import Vendor

from . import services
from .forms import (
    CancelRTVForm,
    GoodsReceiptForm,
    GoodsReceiptLineForm,
    ReturnToVendorForm,
    RTVLineForm,
    ShipRTVForm,
)
from .models import (
    CHECK_RESULT_CHOICES,
    DISCREPANCY_CHOICES,
    GRN_QA_CRITERIA,
    GRN_STATUS_CHOICES,
    GoodsReceipt,
    GoodsReceiptLine,
    ReturnToVendor,
    ReturnToVendorLine,
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
    if not services.can_manage_goods_receipt(request.user):
        messages.error(request, 'You do not have permission to manage goods receipts.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_view(request):
    if not services.can_view_goods_receipt(request.user):
        messages.error(request, 'You do not have permission to view goods receipts.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _get_grn(request, pk):
    return get_object_or_404(GoodsReceipt, pk=pk, tenant=request.tenant)


def _get_rtv(request, pk):
    return get_object_or_404(ReturnToVendor, pk=pk, tenant=request.tenant)


# ---------------------------------------------------------------------------
# List + CRUD
# ---------------------------------------------------------------------------
@login_required
def grn_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = GoodsReceipt.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'purchase_order', 'shipment',
    )

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    vendor = request.GET.get('vendor', '')
    po = request.GET.get('po', '')

    if q:
        qs = qs.filter(
            Q(grn_number__icontains=q)
            | Q(purchase_order__po_number__icontains=q)
            | Q(vendor__legal_name__icontains=q)
            | Q(delivery_note_ref__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if vendor:
        qs = qs.filter(vendor_id=vendor)
    if po:
        qs = qs.filter(purchase_order_id=po)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    querystring = request.GET.copy()
    querystring.pop('page', None)

    context = {
        'page_obj': page_obj,
        'goods_receipts': page_obj.object_list,
        'q': q,
        'status_choices': GRN_STATUS_CHOICES,
        'vendors': Vendor.objects.filter(tenant=request.tenant).order_by('legal_name'),
        'querystring': querystring.urlencode(),
        'can_manage': services.can_manage_goods_receipt(request.user),
    }
    return render(request, 'goods_receipt/list.html', context)


@login_required
def grn_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    initial = {}
    from_po = request.GET.get('from_po')
    if from_po:
        po = get_object_or_404(PurchaseOrder, pk=from_po, tenant=request.tenant)
        if po.status not in PO_CHANGE_ORDERABLE_STATUSES:
            messages.error(
                request, 'A goods receipt can only be raised against a dispatched, open PO.')
            return redirect('purchase_orders:po_detail', pk=po.pk)
        initial['purchase_order'] = po
        from_shipment = request.GET.get('from_shipment')
        if from_shipment:
            shipment = Shipment.objects.filter(
                pk=from_shipment, tenant=request.tenant, purchase_order=po).first()
            if shipment:
                initial['shipment'] = shipment

    if request.method == 'POST':
        form = GoodsReceiptForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            po = form.cleaned_data['purchase_order']
            shipment = form.cleaned_data.get('shipment')
            fields = {
                k: v for k, v in form.cleaned_data.items()
                if k not in ('purchase_order', 'shipment')
            }
            try:
                grn = services.create_goods_receipt(
                    tenant=request.tenant, user=request.user,
                    purchase_order=po, shipment=shipment, **fields)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
                return render(request, 'goods_receipt/form.html', {
                    'form': form, 'is_edit': False,
                })
            messages.success(
                request,
                f'Goods receipt {grn.grn_number} created. Add the received lines, then '
                'mark it received.')
            return redirect('goods_receipt:grn_detail', pk=grn.pk)
    else:
        form = GoodsReceiptForm(initial=initial, tenant=request.tenant)

    return render(request, 'goods_receipt/form.html', {
        'form': form, 'is_edit': False,
    })


@login_required
def grn_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    lines = grn.lines.select_related('purchase_order_line').all()
    existing_checks = {c.criterion: c for c in grn.checks.all()}
    qa_rows = [
        {
            'key': key, 'label': label,
            'result': existing_checks[key].result if key in existing_checks else '',
            'note': existing_checks[key].note if key in existing_checks else '',
        }
        for key, label in GRN_QA_CRITERIA
    ]
    context = {
        'grn': grn,
        'po': grn.purchase_order,
        'lines': lines,
        'qa_rows': qa_rows,
        'has_checks': bool(existing_checks),
        'check_result_choices': CHECK_RESULT_CHOICES,
        'discrepancy_choices': DISCREPANCY_CHOICES,
        'tags': grn.tags.select_related('goods_receipt_line').all(),
        'returns': grn.returns.all(),
        'status_events': grn.status_events.select_related('actor').all()[:30],
        'cancel_form': CancelRTVForm(),
        'can_manage': services.can_manage_goods_receipt(request.user),
    }
    return render(request, 'goods_receipt/detail.html', context)


@login_required
def grn_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    if not grn.is_editable:
        messages.error(request, 'Only a draft GRN can be edited.')
        return redirect('goods_receipt:grn_detail', pk=grn.pk)

    if request.method == 'POST':
        form = GoodsReceiptForm(request.POST, instance=grn, tenant=request.tenant)
        if form.is_valid():
            form.save()
            services.record_audit(
                request.tenant, request.user, 'goods_receipt.updated',
                target_type='GoodsReceipt', target_id=str(grn.pk),
                message=f'{grn.grn_number} updated.', request=request,
            )
            messages.success(request, 'Goods receipt updated.')
            return redirect('goods_receipt:grn_detail', pk=grn.pk)
    else:
        form = GoodsReceiptForm(instance=grn, tenant=request.tenant)

    return render(request, 'goods_receipt/form.html', {
        'form': form, 'grn': grn, 'is_edit': True,
    })


@login_required
@require_POST
def grn_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    if not grn.is_editable:
        messages.error(request, 'Only a draft GRN can be deleted.')
        return redirect('goods_receipt:grn_detail', pk=grn.pk)

    number = grn.grn_number
    services.record_audit(
        request.tenant, request.user, 'goods_receipt.deleted', level='warning',
        target_type='GoodsReceipt', target_id=str(grn.pk),
        message=f'{number} deleted.', request=request,
    )
    grn.delete()
    messages.success(request, f'Goods receipt {number} deleted.')
    return redirect('goods_receipt:grn_list')


# ---------------------------------------------------------------------------
# Lifecycle transitions (POST)
# ---------------------------------------------------------------------------
@login_required
@require_POST
def grn_receive(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    received_date = request.POST.get('received_date') or None
    try:
        services.mark_received(grn, request.user, received_date=received_date)
        messages.success(request, f'{grn.grn_number} marked received.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('goods_receipt:grn_detail', pk=grn.pk)


@login_required
@require_POST
def grn_inspect(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)

    # QA checklist: one POST key per criterion (check_<criterion>).
    checks = []
    for criterion, _label in GRN_QA_CRITERIA:
        result = request.POST.get(f'check_{criterion}')
        if result:
            checks.append({
                'criterion': criterion, 'result': result,
                'note': request.POST.get(f'checknote_{criterion}', ''),
            })

    # Per-line accept / reject.
    line_results = {}
    for ln in grn.lines.all():
        accepted = request.POST.get(f'accepted_{ln.id}')
        rejected = request.POST.get(f'rejected_{ln.id}')
        if accepted in (None, '') and rejected in (None, ''):
            continue
        line_results[ln.id] = {
            'accepted': accepted or '0',
            'rejected': rejected or '0',
            'discrepancy': request.POST.get(f'discrepancy_{ln.id}', 'none'),
            'reason': request.POST.get(f'reason_{ln.id}', ''),
        }

    try:
        services.record_inspection(
            grn, request.user, checks=checks, line_results=line_results,
            note=request.POST.get('inspection_note', ''))
        messages.success(request, f'{grn.grn_number} inspection recorded.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('goods_receipt:grn_detail', pk=grn.pk)


@login_required
@require_POST
def grn_post(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    try:
        services.post_goods_receipt(grn, request.user)
        messages.success(
            request, f'{grn.grn_number} posted to {grn.purchase_order.po_number}.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('goods_receipt:grn_detail', pk=grn.pk)


@login_required
@require_POST
def grn_close(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    try:
        services.close_goods_receipt(grn, request.user, request.POST.get('note', ''))
        messages.success(request, f'{grn.grn_number} closed.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('goods_receipt:grn_detail', pk=grn.pk)


@login_required
@require_POST
def grn_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    reason = request.POST.get('reason', '')
    try:
        services.cancel_goods_receipt(grn, request.user, reason)
        messages.success(request, f'{grn.grn_number} cancelled.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('goods_receipt:grn_detail', pk=grn.pk)


# ---------------------------------------------------------------------------
# GRN line items (draft only)
# ---------------------------------------------------------------------------
@login_required
def line_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    if not grn.is_editable:
        messages.error(request, 'Lines can only be changed while the GRN is a draft.')
        return redirect('goods_receipt:grn_detail', pk=grn.pk)

    if request.method == 'POST':
        form = GoodsReceiptLineForm(request.POST, tenant=request.tenant, goods_receipt=grn)
        if form.is_valid():
            try:
                services.add_receipt_line(
                    grn,
                    purchase_order_line=form.cleaned_data['purchase_order_line'],
                    received_quantity=form.cleaned_data['received_quantity'],
                    shipment_line=form.cleaned_data.get('shipment_line'),
                    discrepancy_type=form.cleaned_data.get('discrepancy_type', 'none'),
                    notes=form.cleaned_data.get('notes', ''),
                )
                messages.success(request, 'Received line added.')
                return redirect('goods_receipt:grn_detail', pk=grn.pk)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
    else:
        form = GoodsReceiptLineForm(tenant=request.tenant, goods_receipt=grn)

    return render(request, 'goods_receipt/line_form.html', {
        'form': form, 'grn': grn, 'is_edit': False,
    })


@login_required
def line_edit(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    line = get_object_or_404(
        GoodsReceiptLine, pk=line_pk, goods_receipt=grn, tenant=request.tenant)
    if not grn.is_editable:
        messages.error(request, 'Lines can only be changed while the GRN is a draft.')
        return redirect('goods_receipt:grn_detail', pk=grn.pk)

    if request.method == 'POST':
        form = GoodsReceiptLineForm(
            request.POST, instance=line, tenant=request.tenant, goods_receipt=grn)
        if form.is_valid():
            obj = form.save(commit=False)
            pol = obj.purchase_order_line
            if not obj.description:
                obj.description = pol.description
            if not obj.uom or obj.uom == 'unit':
                obj.uom = pol.uom
            obj.save()
            messages.success(request, 'Received line updated.')
            return redirect('goods_receipt:grn_detail', pk=grn.pk)
    else:
        form = GoodsReceiptLineForm(
            instance=line, tenant=request.tenant, goods_receipt=grn)

    return render(request, 'goods_receipt/line_form.html', {
        'form': form, 'grn': grn, 'line': line, 'is_edit': True,
    })


@login_required
@require_POST
def line_delete(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    line = get_object_or_404(
        GoodsReceiptLine, pk=line_pk, goods_receipt=grn, tenant=request.tenant)
    if not grn.is_editable:
        messages.error(request, 'Lines can only be changed while the GRN is a draft.')
        return redirect('goods_receipt:grn_detail', pk=grn.pk)
    line.delete()
    messages.success(request, 'Received line removed.')
    return redirect('goods_receipt:grn_detail', pk=grn.pk)


# ---------------------------------------------------------------------------
# 5. Tags (barcode / QR labels)
# ---------------------------------------------------------------------------
@login_required
def tags_print(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    return render(request, 'goods_receipt/tags_print.html', {
        'grn': grn,
        'tags': grn.tags.select_related('goods_receipt_line').all(),
    })


@login_required
@require_POST
def grn_generate_tags(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    if grn.status not in ('posted', 'closed'):
        messages.error(request, 'Tags can only be generated for a posted GRN.')
        return redirect('goods_receipt:grn_detail', pk=grn.pk)
    created = services.generate_tags(grn, request.user)
    messages.success(request, f'{len(created)} tag(s) generated.')
    return redirect('goods_receipt:grn_detail', pk=grn.pk)


# ---------------------------------------------------------------------------
# 4. Return to Vendor (RTV)
# ---------------------------------------------------------------------------
@login_required
def rtv_create(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    grn = _get_grn(request, pk)
    if not grn.has_rejections:
        messages.error(request, 'This GRN has no rejected items to return.')
        return redirect('goods_receipt:grn_detail', pk=grn.pk)

    if request.method == 'POST':
        form = ReturnToVendorForm(request.POST)
        if form.is_valid():
            try:
                rtv = services.create_rtv_from_rejections(
                    grn, request.user, reason=form.cleaned_data.get('reason', ''))
                if form.cleaned_data.get('rma_number'):
                    rtv.rma_number = form.cleaned_data['rma_number']
                    rtv.save(update_fields=['rma_number', 'updated_at'])
                messages.success(request, f'Return {rtv.rtv_number} created.')
                return redirect('goods_receipt:rtv_detail', pk=rtv.pk)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
    else:
        form = ReturnToVendorForm()

    return render(request, 'goods_receipt/rtv_form.html', {
        'form': form, 'grn': grn,
    })


@login_required
def rtv_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    rtv = _get_rtv(request, pk)
    context = {
        'rtv': rtv,
        'grn': rtv.goods_receipt,
        'lines': rtv.lines.select_related('goods_receipt_line').all(),
        'ship_form': ShipRTVForm(),
        'cancel_form': CancelRTVForm(),
        'line_form': RTVLineForm(goods_receipt=rtv.goods_receipt),
        'can_manage': services.can_manage_goods_receipt(request.user),
    }
    return render(request, 'goods_receipt/rtv_detail.html', context)


@login_required
@require_POST
def rtv_line_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    rtv = _get_rtv(request, pk)
    if not rtv.is_editable:
        messages.error(request, 'Lines can only be changed while the return is a draft.')
        return redirect('goods_receipt:rtv_detail', pk=rtv.pk)
    form = RTVLineForm(request.POST, goods_receipt=rtv.goods_receipt)
    if form.is_valid():
        line = form.save(commit=False)
        line.tenant = request.tenant
        line.rtv = rtv
        grl = line.goods_receipt_line
        line.line_no = (rtv.lines.count() or 0) + 1
        line.description = grl.description
        line.uom = grl.uom
        line.save()
        messages.success(request, 'Return line added.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect('goods_receipt:rtv_detail', pk=rtv.pk)


@login_required
@require_POST
def rtv_line_delete(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    rtv = _get_rtv(request, pk)
    line = get_object_or_404(
        ReturnToVendorLine, pk=line_pk, rtv=rtv, tenant=request.tenant)
    if not rtv.is_editable:
        messages.error(request, 'Lines can only be changed while the return is a draft.')
        return redirect('goods_receipt:rtv_detail', pk=rtv.pk)
    line.delete()
    messages.success(request, 'Return line removed.')
    return redirect('goods_receipt:rtv_detail', pk=rtv.pk)


@login_required
@require_POST
def rtv_authorize(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    rtv = _get_rtv(request, pk)
    try:
        services.authorize_rtv(rtv, request.user)
        messages.success(request, f'{rtv.rtv_number} authorised.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('goods_receipt:rtv_detail', pk=rtv.pk)


@login_required
@require_POST
def rtv_ship(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    rtv = _get_rtv(request, pk)
    form = ShipRTVForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Invalid shipping details.')
        return redirect('goods_receipt:rtv_detail', pk=rtv.pk)
    try:
        services.ship_rtv(
            rtv, request.user,
            carrier=form.cleaned_data.get('carrier', ''),
            tracking_number=form.cleaned_data.get('tracking_number', ''))
        messages.success(request, f'{rtv.rtv_number} shipped back to the supplier.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('goods_receipt:rtv_detail', pk=rtv.pk)


@login_required
@require_POST
def rtv_close(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    rtv = _get_rtv(request, pk)
    try:
        services.close_rtv(rtv, request.user, request.POST.get('note', ''))
        messages.success(request, f'{rtv.rtv_number} closed.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('goods_receipt:rtv_detail', pk=rtv.pk)


@login_required
@require_POST
def rtv_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    rtv = _get_rtv(request, pk)
    form = CancelRTVForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('goods_receipt:rtv_detail', pk=rtv.pk)
    try:
        services.cancel_rtv(rtv, request.user, form.cleaned_data['reason'])
        messages.success(request, f'{rtv.rtv_number} cancelled.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('goods_receipt:rtv_detail', pk=rtv.pk)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@login_required
def analytics_dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied

    # Lazy sweep: raise overdue-inspection / open-RTV alerts before rendering.
    if services.can_manage_goods_receipt(request.user):
        services.scan_goods_receipt_alerts(tenant=request.tenant)

    metrics = services.tenant_goods_receipt_metrics(request.tenant)
    recent = GoodsReceipt.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'purchase_order')[:10]
    return render(request, 'goods_receipt/analytics.html', {
        'metrics': metrics,
        'recent_grns': recent,
        'can_manage': services.can_manage_goods_receipt(request.user),
    })
