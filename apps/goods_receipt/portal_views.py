"""Module 13 vendor-portal views: supplier-facing Return-to-Vendor (RTV) notices.

Mirrors :mod:`apps.fulfillment.portal_views`: every view is gated by ``@vendor_required``
and scoped to ``request.user.vendor`` and its tenant. A supplier sees the returns that
have been authorised against them, and may acknowledge receipt of the return notice.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.vendors.decorators import vendor_required

from . import services
from .models import RTV_VENDOR_VISIBLE_STATUSES, ReturnToVendor


def _get_rtv(request, pk):
    """Fetch an RTV owned by the current vendor (raises 404 otherwise)."""
    vendor = request.user.vendor
    return get_object_or_404(ReturnToVendor, pk=pk, tenant=vendor.tenant, vendor=vendor)


@vendor_required
def portal_rtv_list(request):
    """List the returns authorised against this vendor."""
    vendor = request.user.vendor
    returns = (
        ReturnToVendor.objects
        .filter(vendor=vendor, tenant=vendor.tenant,
                status__in=RTV_VENDOR_VISIBLE_STATUSES)
        .select_related('purchase_order', 'goods_receipt')
        .order_by('-created_at')
    )
    return render(request, 'vendor_portal/goods_receipt/rtv_list.html', {
        'returns': returns, 'vendor': vendor,
    })


@vendor_required
def portal_rtv_detail(request, pk):
    """Read view of an authorised return with an acknowledge action."""
    rtv = _get_rtv(request, pk)
    if not services.rtv_visible_to(request.user, rtv):
        messages.error(request, 'This return is not available.')
        return redirect('vendor_portal:returns')
    return render(request, 'vendor_portal/goods_receipt/rtv_detail.html', {
        'rtv': rtv,
        'po': rtv.purchase_order,
        'lines': rtv.lines.select_related('goods_receipt_line').all(),
    })


@vendor_required
@require_POST
def portal_rtv_acknowledge(request, pk):
    """Supplier acknowledges the return notice."""
    rtv = _get_rtv(request, pk)
    if not services.rtv_visible_to(request.user, rtv):
        messages.error(request, 'This return is not available.')
        return redirect('vendor_portal:returns')
    try:
        services.acknowledge_rtv(rtv, request.user, request.POST.get('note', ''))
        messages.success(request, f'Return {rtv.rtv_number} acknowledged.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('vendor_portal:rtv_detail', pk=rtv.pk)
