"""Module 12 views: Order Fulfillment & Tracking (buyer / internal side).

Function-based views mirroring the purchase_orders module: ``@login_required`` + a
``_require_manage`` / ``_require_view`` permission gate, ``_get_shipment`` scoped to
``request.tenant``, list search + filters + ``Paginator(qs, 20)``, and lifecycle
actions that delegate to :mod:`apps.fulfillment.services` and surface
``ValidationError.messages`` back to the user.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.purchase_orders.models import PO_DISPATCHED_STATUSES, PurchaseOrder
from apps.vendors.models import Vendor

from . import services
from .forms import (
    BackorderForm,
    CancelShipmentForm,
    ConfirmDeliveryForm,
    ShipmentDocumentForm,
    ShipmentForm,
    ShipmentLineForm,
    TrackingEventForm,
)
from .models import (
    SHIPMENT_STATUS_CHOICES,
    Backorder,
    Shipment,
    ShipmentDocument,
    ShipmentLine,
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
    if not services.can_manage_fulfillment(request.user):
        messages.error(request, 'You do not have permission to manage fulfillment.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_view(request):
    if not services.can_view_fulfillment(request.user):
        messages.error(request, 'You do not have permission to view fulfillment.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _get_shipment(request, pk):
    return get_object_or_404(Shipment, pk=pk, tenant=request.tenant)


# ---------------------------------------------------------------------------
# List + CRUD
# ---------------------------------------------------------------------------
@login_required
def shipment_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = Shipment.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'purchase_order',
    )

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    vendor = request.GET.get('vendor', '')
    carrier = request.GET.get('carrier', '')
    po = request.GET.get('po', '')

    if q:
        qs = qs.filter(
            Q(shipment_number__icontains=q)
            | Q(purchase_order__po_number__icontains=q)
            | Q(vendor__legal_name__icontains=q)
            | Q(tracking_number__icontains=q)
            | Q(carrier__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if vendor:
        qs = qs.filter(vendor_id=vendor)
    if carrier:
        qs = qs.filter(carrier=carrier)
    if po:
        qs = qs.filter(purchase_order_id=po)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    querystring = request.GET.copy()
    querystring.pop('page', None)

    carriers = list(
        Shipment.objects.filter(tenant=request.tenant)
        .exclude(carrier='').values_list('carrier', flat=True).distinct()
    )

    context = {
        'page_obj': page_obj,
        'shipments': page_obj.object_list,
        'q': q,
        'status_choices': SHIPMENT_STATUS_CHOICES,
        'vendors': Vendor.objects.filter(tenant=request.tenant).order_by('legal_name'),
        'carriers': carriers,
        'querystring': querystring.urlencode(),
        'can_manage': services.can_manage_fulfillment(request.user),
    }
    return render(request, 'fulfillment/shipment_list.html', context)


@login_required
def shipment_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    initial = {}
    from_po = request.GET.get('from_po')
    if from_po:
        po = get_object_or_404(
            PurchaseOrder, pk=from_po, tenant=request.tenant)
        if po.status not in PO_DISPATCHED_STATUSES:
            messages.error(
                request, 'A shipment can only be created against a dispatched PO.')
            return redirect('purchase_orders:po_detail', pk=po.pk)
        initial['purchase_order'] = po

    if request.method == 'POST':
        form = ShipmentForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            po = form.cleaned_data['purchase_order']
            fields = {
                k: v for k, v in form.cleaned_data.items() if k != 'purchase_order'
            }
            try:
                shipment = services.create_shipment(
                    tenant=request.tenant, user=request.user,
                    purchase_order=po, **fields)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
                return render(request, 'fulfillment/shipment_form.html', {
                    'form': form, 'is_edit': False,
                })
            messages.success(
                request,
                f'Shipment {shipment.shipment_number} created. Add the lines, then '
                'advise the ASN.')
            return redirect('fulfillment:shipment_detail', pk=shipment.pk)
    else:
        form = ShipmentForm(initial=initial, tenant=request.tenant)

    return render(request, 'fulfillment/shipment_form.html', {
        'form': form, 'is_edit': False,
    })


@login_required
def shipment_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    lines = shipment.lines.select_related('purchase_order_line').all()
    context = {
        'shipment': shipment,
        'po': shipment.purchase_order,
        'lines': lines,
        'tracking_events': shipment.tracking_events.all()[:50],
        'status_events': shipment.status_events.select_related('actor').all()[:30],
        'documents': shipment.documents.select_related('uploaded_by').all(),
        'tracking_form': TrackingEventForm(),
        'confirm_form': ConfirmDeliveryForm(),
        'cancel_form': CancelShipmentForm(),
        'document_form': ShipmentDocumentForm(),
        'remaining_to_ship': services.remaining_to_ship(shipment.purchase_order),
        'can_manage': services.can_manage_fulfillment(request.user),
    }
    return render(request, 'fulfillment/shipment_detail.html', context)


@login_required
def shipment_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    if not shipment.is_editable:
        messages.error(request, 'Only a draft shipment can be edited.')
        return redirect('fulfillment:shipment_detail', pk=shipment.pk)

    if request.method == 'POST':
        form = ShipmentForm(request.POST, instance=shipment, tenant=request.tenant)
        if form.is_valid():
            form.save()
            services.record_audit(
                request.tenant, request.user, 'fulfillment.shipment.updated',
                target_type='Shipment', target_id=str(shipment.pk),
                message=f'{shipment.shipment_number} updated.', request=request,
            )
            messages.success(request, 'Shipment updated.')
            return redirect('fulfillment:shipment_detail', pk=shipment.pk)
    else:
        form = ShipmentForm(instance=shipment, tenant=request.tenant)

    return render(request, 'fulfillment/shipment_form.html', {
        'form': form, 'shipment': shipment, 'is_edit': True,
    })


@login_required
@require_POST
def shipment_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    if not shipment.is_editable:
        messages.error(request, 'Only a draft shipment can be deleted.')
        return redirect('fulfillment:shipment_detail', pk=shipment.pk)

    number = shipment.shipment_number
    services.record_audit(
        request.tenant, request.user, 'fulfillment.shipment.deleted', level='warning',
        target_type='Shipment', target_id=str(shipment.pk),
        message=f'{number} deleted.', request=request,
    )
    shipment.delete()
    messages.success(request, f'Shipment {number} deleted.')
    return redirect('fulfillment:shipment_list')


# ---------------------------------------------------------------------------
# Lifecycle transitions (POST)
# ---------------------------------------------------------------------------
@login_required
@require_POST
def shipment_advise(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    try:
        services.advise_shipment(shipment, request.user)
        messages.success(request, f'{shipment.shipment_number} advised (ASN sent).')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('fulfillment:shipment_detail', pk=shipment.pk)


@login_required
@require_POST
def shipment_sync_tracking(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    try:
        services.sync_tracking(shipment, request.user)
        messages.success(request, 'Tracking synced from the carrier.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('fulfillment:shipment_detail', pk=shipment.pk)


@login_required
@require_POST
def tracking_event_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    form = TrackingEventForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('fulfillment:shipment_detail', pk=shipment.pk)
    cd = form.cleaned_data
    services.add_manual_tracking_event(
        shipment, request.user,
        status_code=cd['status_code'], description=cd.get('description', ''),
        location=cd.get('location', ''), occurred_at=cd.get('occurred_at'),
    )
    messages.success(request, 'Tracking event recorded.')
    return redirect('fulfillment:shipment_detail', pk=shipment.pk)


@login_required
@require_POST
def shipment_confirm_delivery(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    form = ConfirmDeliveryForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('fulfillment:shipment_detail', pk=shipment.pk)

    # Optional per-line received quantities (recv_<line_id>); default = full receipt.
    line_quantities = {}
    for ln in shipment.lines.all():
        raw = request.POST.get(f'recv_{ln.id}')
        if raw not in (None, ''):
            line_quantities[ln.id] = raw

    cd = form.cleaned_data
    try:
        services.confirm_delivery(
            shipment, request.user,
            delivered_at=cd.get('delivered_at'),
            condition=cd.get('received_condition', 'good'),
            post_receipt=cd.get('post_receipt', False),
            note=cd.get('note', ''),
            line_quantities=line_quantities or None,
        )
        messages.success(request, f'{shipment.shipment_number} confirmed delivered.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('fulfillment:shipment_detail', pk=shipment.pk)


@login_required
@require_POST
def shipment_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    form = CancelShipmentForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('fulfillment:shipment_detail', pk=shipment.pk)
    try:
        services.cancel_shipment(shipment, request.user, form.cleaned_data['reason'])
        messages.success(request, f'{shipment.shipment_number} cancelled.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('fulfillment:shipment_detail', pk=shipment.pk)


@login_required
@require_POST
def shipment_close(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    try:
        services.close_shipment(shipment, request.user, request.POST.get('note', ''))
        messages.success(request, f'{shipment.shipment_number} closed.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('fulfillment:shipment_detail', pk=shipment.pk)


# ---------------------------------------------------------------------------
# Line items (draft only)
# ---------------------------------------------------------------------------
@login_required
def line_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    if not shipment.is_editable:
        messages.error(request, 'Lines can only be changed while the shipment is a draft.')
        return redirect('fulfillment:shipment_detail', pk=shipment.pk)

    if request.method == 'POST':
        form = ShipmentLineForm(request.POST, tenant=request.tenant, shipment=shipment)
        if form.is_valid():
            line = form.save(commit=False)
            line.tenant = request.tenant
            line.shipment = shipment
            pol = line.purchase_order_line
            # Max+1 (not count+1) so a mid-list delete can't cause a line_no collision.
            line.line_no = (shipment.lines.aggregate(m=Max('line_no'))['m'] or 0) + 1
            if not line.description:
                line.description = pol.description
            if not line.uom or line.uom == 'unit':
                line.uom = pol.uom
            line.line_status = 'pending'
            line.save()
            messages.success(request, 'Shipment line added.')
            return redirect('fulfillment:shipment_detail', pk=shipment.pk)
    else:
        form = ShipmentLineForm(tenant=request.tenant, shipment=shipment)

    return render(request, 'fulfillment/shipment_line_form.html', {
        'form': form, 'shipment': shipment, 'is_edit': False,
    })


@login_required
def line_edit(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    line = get_object_or_404(
        ShipmentLine, pk=line_pk, shipment=shipment, tenant=request.tenant)
    if not shipment.is_editable:
        messages.error(request, 'Lines can only be changed while the shipment is a draft.')
        return redirect('fulfillment:shipment_detail', pk=shipment.pk)

    if request.method == 'POST':
        form = ShipmentLineForm(
            request.POST, instance=line, tenant=request.tenant, shipment=shipment)
        if form.is_valid():
            obj = form.save(commit=False)
            pol = obj.purchase_order_line
            if not obj.description:
                obj.description = pol.description
            if not obj.uom or obj.uom == 'unit':
                obj.uom = pol.uom
            obj.save()
            messages.success(request, 'Shipment line updated.')
            return redirect('fulfillment:shipment_detail', pk=shipment.pk)
    else:
        form = ShipmentLineForm(
            instance=line, tenant=request.tenant, shipment=shipment)

    return render(request, 'fulfillment/shipment_line_form.html', {
        'form': form, 'shipment': shipment, 'line': line, 'is_edit': True,
    })


@login_required
@require_POST
def line_delete(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    line = get_object_or_404(
        ShipmentLine, pk=line_pk, shipment=shipment, tenant=request.tenant)
    if not shipment.is_editable:
        messages.error(request, 'Lines can only be changed while the shipment is a draft.')
        return redirect('fulfillment:shipment_detail', pk=shipment.pk)
    line.delete()
    messages.success(request, 'Shipment line removed.')
    return redirect('fulfillment:shipment_detail', pk=shipment.pk)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@login_required
@require_POST
def document_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    form = ShipmentDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.tenant = request.tenant
        doc.shipment = shipment
        doc.uploaded_by = request.user
        doc.save()
        services.record_audit(
            request.tenant, request.user, 'fulfillment.document.added',
            target_type='Shipment', target_id=str(shipment.pk),
            message=f'Document "{doc.title}" added to {shipment.shipment_number}.',
            request=request,
        )
        messages.success(request, 'Document uploaded.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect('fulfillment:shipment_detail', pk=shipment.pk)


@login_required
@require_POST
def document_delete(request, pk, document_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    shipment = _get_shipment(request, pk)
    doc = get_object_or_404(
        ShipmentDocument, pk=document_pk, shipment=shipment, tenant=request.tenant)
    title = doc.title
    doc.delete()
    services.record_audit(
        request.tenant, request.user, 'fulfillment.document.deleted', level='warning',
        target_type='Shipment', target_id=str(shipment.pk),
        message=f'Document "{title}" removed from {shipment.shipment_number}.',
        request=request,
    )
    messages.success(request, 'Document removed.')
    return redirect('fulfillment:shipment_detail', pk=shipment.pk)


# ---------------------------------------------------------------------------
# 4. Backorders
# ---------------------------------------------------------------------------
@login_required
def backorder_board(request):
    denied = _require_view(request)
    if denied:
        return denied

    base = Backorder.objects.filter(tenant=request.tenant).select_related(
        'purchase_order', 'purchase_order_line', 'fulfilled_by_shipment')
    overdue = [b for b in base.filter(status__in=('open', 'promised')) if b.is_overdue]
    board = {
        'overdue': overdue,
        'open': list(base.filter(status='open')),
        'promised': list(base.filter(status='promised')),
        'fulfilled': list(base.filter(status='fulfilled')[:50]),
        'cancelled': list(base.filter(status='cancelled')[:50]),
    }
    return render(request, 'fulfillment/backorder_board.html', {
        'board': board,
        'can_manage': services.can_manage_fulfillment(request.user),
    })


@login_required
def backorder_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    purchase_order = None
    po_id = request.GET.get('po')
    if po_id:
        purchase_order = get_object_or_404(
            PurchaseOrder, pk=po_id, tenant=request.tenant)

    if request.method == 'POST':
        form = BackorderForm(
            request.POST, tenant=request.tenant, purchase_order=purchase_order)
        if form.is_valid():
            pol = form.cleaned_data['purchase_order_line']
            try:
                services.open_backorder(
                    tenant=request.tenant, user=request.user,
                    purchase_order_line=pol,
                    quantity=form.cleaned_data['quantity'],
                    expected_date=form.cleaned_data.get('expected_date'),
                    reason=form.cleaned_data.get('reason', ''),
                )
                messages.success(request, 'Backorder opened.')
                return redirect('fulfillment:backorder_board')
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
    else:
        form = BackorderForm(tenant=request.tenant, purchase_order=purchase_order)

    return render(request, 'fulfillment/backorder_form.html', {
        'form': form, 'purchase_order': purchase_order,
    })


@login_required
@require_POST
def backorder_fulfill(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    bo = get_object_or_404(Backorder, pk=pk, tenant=request.tenant)
    shipment = None
    shipment_id = request.POST.get('shipment')
    if shipment_id:
        shipment = Shipment.objects.filter(
            pk=shipment_id, tenant=request.tenant).first()
    try:
        services.fulfill_backorder(bo, request.user, shipment=shipment)
        messages.success(request, 'Backorder marked fulfilled.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('fulfillment:backorder_board')


@login_required
@require_POST
def backorder_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    bo = get_object_or_404(Backorder, pk=pk, tenant=request.tenant)
    try:
        services.cancel_backorder(bo, request.user, request.POST.get('reason', ''))
        messages.success(request, 'Backorder cancelled.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('fulfillment:backorder_board')


# ---------------------------------------------------------------------------
# Tracking board
# ---------------------------------------------------------------------------
@login_required
def tracking_board(request):
    denied = _require_view(request)
    if denied:
        return denied

    # Lazy sweep: raise overdue-delivery alerts before rendering.
    if services.can_manage_fulfillment(request.user):
        services.scan_fulfillment_alerts(tenant=request.tenant)

    base = Shipment.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'purchase_order')
    board = [
        ('draft', 'Draft', 'badge-soft-secondary',
         list(base.filter(status='draft').order_by('-created_at'))),
        ('advised', 'Advised', 'badge-soft-info',
         list(base.filter(status='advised').order_by('estimated_delivery_date'))),
        ('in_transit', 'In transit', 'badge-soft-primary',
         list(base.filter(status='in_transit').order_by('estimated_delivery_date'))),
        ('out_for_delivery', 'Out for delivery', 'badge-soft-warning',
         list(base.filter(status='out_for_delivery').order_by('estimated_delivery_date'))),
        ('delivered', 'Delivered', 'badge-soft-success',
         list(base.filter(status='delivered').order_by('-delivered_at'))),
        ('received', 'Received', 'badge-soft-success',
         list(base.filter(status='received').order_by('-updated_at')[:50])),
    ]
    return render(request, 'fulfillment/tracking_board.html', {
        'board': board,
        'can_manage': services.can_manage_fulfillment(request.user),
    })


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@login_required
def analytics_dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied

    metrics = services.tenant_fulfillment_metrics(request.tenant)
    recent = Shipment.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'purchase_order')[:10]
    return render(request, 'fulfillment/analytics.html', {
        'metrics': metrics,
        'recent_shipments': recent,
        'can_manage': services.can_manage_fulfillment(request.user),
    })
