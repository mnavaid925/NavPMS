"""Module 14 vendor-portal views: supplier-facing invoice submission + dispute thread.

Mirrors :mod:`apps.goods_receipt.portal_views`: every view is gated by ``@vendor_required``
and scoped to ``request.user.vendor`` and its tenant. A supplier submits an invoice against
one of their dispatched POs (the file is OCR-captured and auto-submitted for matching), tracks
its status, and can exchange messages on a disputed invoice. Replaces the Module-14 placeholder.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.purchase_orders.models import PO_DISPATCHED_STATUSES, PurchaseOrder
from apps.vendors.decorators import vendor_required

from . import services
from .models import INVOICE_VENDOR_VISIBLE_STATUSES, SupplierInvoice


def _get_invoice(request, pk):
    """Fetch an invoice owned by the current vendor (raises 404 otherwise)."""
    vendor = request.user.vendor
    return get_object_or_404(
        SupplierInvoice, pk=pk, tenant=vendor.tenant, vendor=vendor)


@vendor_required
def portal_invoice_list(request):
    """List the invoices this supplier has submitted (drafts entered internally hidden)."""
    vendor = request.user.vendor
    invoices = (
        SupplierInvoice.objects
        .filter(vendor=vendor, tenant=vendor.tenant,
                status__in=INVOICE_VENDOR_VISIBLE_STATUSES)
        .select_related('purchase_order')
        .order_by('-created_at')
    )
    return render(request, 'vendor_portal/invoicing/list.html', {
        'invoices': invoices, 'vendor': vendor,
    })


@vendor_required
def portal_invoice_create(request):
    """Submit a new invoice against a dispatched PO (file OCR-captured + auto-submitted)."""
    vendor = request.user.vendor
    pos = (
        PurchaseOrder.objects
        .filter(tenant=vendor.tenant, vendor=vendor, status__in=PO_DISPATCHED_STATUSES)
        .order_by('-issued_at', '-created_at')
    )

    if request.method == 'POST':
        po = get_object_or_404(
            PurchaseOrder, pk=request.POST.get('purchase_order'),
            tenant=vendor.tenant, vendor=vendor)
        source_file = request.FILES.get('source_file')
        err = services.upload_error(source_file)
        if err:
            messages.error(request, err)
            return redirect('vendor_portal:invoice_create')
        try:
            invoice = services.capture_invoice_from_file(
                tenant=vendor.tenant, user=request.user,
                source_file=source_file, purchase_order=po,
                supplier_invoice_ref=request.POST.get('supplier_invoice_ref', ''),
                submitted_via_portal=True)
            services.submit_invoice(invoice, request.user)
            messages.success(
                request,
                f'Invoice {invoice.invoice_number} submitted. We will review it shortly.')
            return redirect('vendor_portal:invoice_detail', pk=invoice.pk)
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)

    return render(request, 'vendor_portal/invoicing/form.html', {
        'purchase_orders': pos, 'vendor': vendor,
    })


@vendor_required
def portal_invoice_detail(request, pk):
    """Read view of the supplier's invoice with the match result + dispute thread."""
    invoice = _get_invoice(request, pk)
    if not services.invoice_visible_to(request.user, invoice):
        messages.error(request, 'This invoice is not available.')
        return redirect('vendor_portal:invoices')
    return render(request, 'vendor_portal/invoicing/detail.html', {
        'invoice': invoice,
        'po': invoice.purchase_order,
        'lines': invoice.lines.select_related('purchase_order_line').all(),
        'dispute_notes': invoice.dispute_notes.select_related('author').all(),
        'vouchers': invoice.vouchers.all(),
    })


@vendor_required
@require_POST
def portal_dispute_reply(request, pk):
    """Supplier adds a message to the invoice's dispute thread."""
    invoice = _get_invoice(request, pk)
    if not services.invoice_visible_to(request.user, invoice):
        messages.error(request, 'This invoice is not available.')
        return redirect('vendor_portal:invoices')
    body = (request.POST.get('body') or '').strip()
    if not body:
        messages.error(request, 'A message is required.')
        return redirect('vendor_portal:invoice_detail', pk=invoice.pk)
    try:
        services.add_dispute_note(invoice, request.user, body, is_from_vendor=True)
        messages.success(request, 'Message sent.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('vendor_portal:invoice_detail', pk=invoice.pk)
