"""Module 11 vendor-portal views: a supplier's purchase orders + acknowledgment.

Mirrors :mod:`apps.contracts.portal_views`: every view is gated by
``@vendor_required`` and scoped to ``request.user.vendor`` and its tenant. The
supplier acknowledges or declines an issued PO; the action delegates to
``services.acknowledge_po`` / ``services.decline_po``.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.vendors.decorators import vendor_required

from . import services
from .forms import AcknowledgePOForm, DeclinePOForm
from .models import PO_DISPATCHED_STATUSES, PurchaseOrder


def _get_po(request, pk):
    """Fetch a PO owned by the current vendor (raises 404 otherwise)."""
    vendor = request.user.vendor
    return get_object_or_404(
        PurchaseOrder, pk=pk, tenant=vendor.tenant, vendor=vendor)


@vendor_required
def portal_po_list(request):
    """List this vendor's purchase orders (everything that has been dispatched)."""
    vendor = request.user.vendor
    pos = (
        PurchaseOrder.objects
        .filter(vendor=vendor, tenant=vendor.tenant,
                status__in=PO_DISPATCHED_STATUSES)
        .order_by('-issued_at', '-created_at')
    )
    return render(request, 'vendor_portal/purchase_orders/list.html', {
        'purchase_orders': pos, 'vendor': vendor,
    })


@vendor_required
def portal_po_detail(request, pk):
    """Read-only PO view for the supplier, with acknowledge / decline actions."""
    po = _get_po(request, pk)
    # Never expose a still-draft PO to the supplier.
    if not services.po_visible_to(request.user, po):
        messages.error(request, 'This purchase order is not available.')
        return redirect('vendor_portal:purchase_orders')
    return render(request, 'vendor_portal/purchase_orders/detail.html', {
        'po': po,
        'lines': po.lines.all(),
        'ack_form': AcknowledgePOForm(),
        'decline_form': DeclinePOForm(),
    })


@vendor_required
@require_POST
def portal_po_acknowledge(request, pk):
    po = _get_po(request, pk)
    form = AcknowledgePOForm(request.POST)
    note = form.cleaned_data.get('note', '') if form.is_valid() else ''
    try:
        services.acknowledge_po(po, request.user, note=note)
        messages.success(request, 'Thank you — you have acknowledged this purchase order.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('vendor_portal:purchase_order_detail', pk=po.pk)


@vendor_required
@require_POST
def portal_po_decline(request, pk):
    po = _get_po(request, pk)
    form = DeclinePOForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Please give a reason for declining.')
        return redirect('vendor_portal:purchase_order_detail', pk=po.pk)
    try:
        services.decline_po(po, request.user, form.cleaned_data['reason'])
        messages.success(request, 'You have declined this purchase order.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('vendor_portal:purchase_order_detail', pk=po.pk)
