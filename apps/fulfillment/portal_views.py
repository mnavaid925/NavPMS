"""Module 12 vendor-portal views: supplier-driven Advance Shipping Notices (ASN).

Mirrors :mod:`apps.purchase_orders.portal_views`: every view is gated by
``@vendor_required`` and scoped to ``request.user.vendor`` and its tenant. A supplier
raises an ASN against one of their own dispatched purchase orders, adds the packing
lines, sets the carrier / tracking number, then advises it — which notifies the buyer.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.vendors.decorators import vendor_required

from . import services
from .forms import ShipmentForm, ShipmentLineForm
from .models import Shipment, ShipmentLine


def _get_shipment(request, pk):
    """Fetch a shipment owned by the current vendor (raises 404 otherwise)."""
    vendor = request.user.vendor
    return get_object_or_404(Shipment, pk=pk, tenant=vendor.tenant, vendor=vendor)


@vendor_required
def portal_shipment_list(request):
    """List this vendor's shipments / ASNs."""
    vendor = request.user.vendor
    shipments = (
        Shipment.objects
        .filter(vendor=vendor, tenant=vendor.tenant)
        .select_related('purchase_order')
        .order_by('-created_at')
    )
    return render(request, 'vendor_portal/fulfillment/list.html', {
        'shipments': shipments, 'vendor': vendor,
    })


@vendor_required
def portal_shipment_detail(request, pk):
    """Read view of an ASN with line/advise actions while it is a draft."""
    shipment = _get_shipment(request, pk)
    if not services.shipment_visible_to(request.user, shipment):
        messages.error(request, 'This shipment is not available.')
        return redirect('vendor_portal:shipments')
    return render(request, 'vendor_portal/fulfillment/detail.html', {
        'shipment': shipment,
        'po': shipment.purchase_order,
        'lines': shipment.lines.select_related('purchase_order_line').all(),
        'tracking_events': shipment.tracking_events.all()[:50],
    })


@vendor_required
def portal_asn_create(request):
    """Create a draft ASN against one of the vendor's dispatched POs."""
    vendor = request.user.vendor
    if request.method == 'POST':
        form = ShipmentForm(request.POST, tenant=vendor.tenant, vendor=vendor)
        if form.is_valid():
            po = form.cleaned_data['purchase_order']
            if po.vendor_id != vendor.id:
                messages.error(request, 'You can only ship your own purchase orders.')
                return redirect('vendor_portal:shipments')
            fields = {
                k: v for k, v in form.cleaned_data.items() if k != 'purchase_order'
            }
            try:
                shipment = services.create_shipment(
                    tenant=vendor.tenant, user=request.user,
                    purchase_order=po, **fields)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
                return render(request, 'vendor_portal/fulfillment/asn_form.html', {
                    'form': form, 'is_edit': False,
                })
            messages.success(
                request,
                f'Draft ASN {shipment.shipment_number} created. Add the packing lines, '
                'then send the notice.')
            return redirect('vendor_portal:shipment_detail', pk=shipment.pk)
    else:
        form = ShipmentForm(tenant=vendor.tenant, vendor=vendor)
    return render(request, 'vendor_portal/fulfillment/asn_form.html', {
        'form': form, 'is_edit': False,
    })


@vendor_required
def portal_asn_edit(request, pk):
    """Edit a draft ASN header (carrier / tracking / dates / packing)."""
    shipment = _get_shipment(request, pk)
    if not shipment.is_editable:
        messages.error(request, 'Only a draft ASN can be edited.')
        return redirect('vendor_portal:shipment_detail', pk=shipment.pk)
    if request.method == 'POST':
        form = ShipmentForm(
            request.POST, instance=shipment, tenant=shipment.tenant,
            vendor=request.user.vendor)
        if form.is_valid():
            form.save()
            messages.success(request, 'ASN updated.')
            return redirect('vendor_portal:shipment_detail', pk=shipment.pk)
    else:
        form = ShipmentForm(
            instance=shipment, tenant=shipment.tenant, vendor=request.user.vendor)
    return render(request, 'vendor_portal/fulfillment/asn_form.html', {
        'form': form, 'shipment': shipment, 'is_edit': True,
    })


@vendor_required
def portal_asn_line_add(request, pk):
    shipment = _get_shipment(request, pk)
    if not shipment.is_editable:
        messages.error(request, 'Lines can only be changed while the ASN is a draft.')
        return redirect('vendor_portal:shipment_detail', pk=shipment.pk)
    if request.method == 'POST':
        form = ShipmentLineForm(
            request.POST, tenant=shipment.tenant, shipment=shipment)
        if form.is_valid():
            line = form.save(commit=False)
            line.tenant = shipment.tenant
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
            messages.success(request, 'Packing line added.')
            return redirect('vendor_portal:shipment_detail', pk=shipment.pk)
    else:
        form = ShipmentLineForm(tenant=shipment.tenant, shipment=shipment)
    return render(request, 'vendor_portal/fulfillment/asn_line_form.html', {
        'form': form, 'shipment': shipment, 'is_edit': False,
    })


@vendor_required
def portal_asn_line_edit(request, pk, line_pk):
    shipment = _get_shipment(request, pk)
    line = get_object_or_404(
        ShipmentLine, pk=line_pk, shipment=shipment, tenant=shipment.tenant)
    if not shipment.is_editable:
        messages.error(request, 'Lines can only be changed while the ASN is a draft.')
        return redirect('vendor_portal:shipment_detail', pk=shipment.pk)
    if request.method == 'POST':
        form = ShipmentLineForm(
            request.POST, instance=line, tenant=shipment.tenant, shipment=shipment)
        if form.is_valid():
            obj = form.save(commit=False)
            pol = obj.purchase_order_line
            if not obj.description:
                obj.description = pol.description
            if not obj.uom or obj.uom == 'unit':
                obj.uom = pol.uom
            obj.save()
            messages.success(request, 'Packing line updated.')
            return redirect('vendor_portal:shipment_detail', pk=shipment.pk)
    else:
        form = ShipmentLineForm(
            instance=line, tenant=shipment.tenant, shipment=shipment)
    return render(request, 'vendor_portal/fulfillment/asn_line_form.html', {
        'form': form, 'shipment': shipment, 'line': line, 'is_edit': True,
    })


@vendor_required
@require_POST
def portal_asn_line_delete(request, pk, line_pk):
    shipment = _get_shipment(request, pk)
    line = get_object_or_404(
        ShipmentLine, pk=line_pk, shipment=shipment, tenant=shipment.tenant)
    if not shipment.is_editable:
        messages.error(request, 'Lines can only be changed while the ASN is a draft.')
        return redirect('vendor_portal:shipment_detail', pk=shipment.pk)
    line.delete()
    messages.success(request, 'Packing line removed.')
    return redirect('vendor_portal:shipment_detail', pk=shipment.pk)


@vendor_required
@require_POST
def portal_asn_advise(request, pk):
    """Send the ASN to the buyer (draft -> advised)."""
    shipment = _get_shipment(request, pk)
    try:
        services.advise_shipment(shipment, request.user)
        messages.success(
            request, f'Shipment notice {shipment.shipment_number} sent to the buyer.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('vendor_portal:shipment_detail', pk=shipment.pk)
