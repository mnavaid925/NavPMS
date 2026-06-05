"""Module 14 views: Invoice & Voucher Management (buyer / internal side).

Function-based views mirroring the goods_receipt / purchase_orders modules:
``@login_required`` + a ``_require_manage`` / ``_require_view`` permission gate, helpers scoped
to ``request.tenant``, a list with search + filters + ``Paginator(qs, 20)``, and lifecycle
actions that delegate to :mod:`apps.invoicing.services` and surface ``ValidationError.messages``.
"""
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.purchase_orders.models import PurchaseOrder
from apps.vendors.models import Vendor

from . import services
from .forms import (
    CreateVoucherForm,
    DisputeForm,
    DisputeNoteForm,
    InvoiceCaptureForm,
    PayVoucherForm,
    PaymentTermForm,
    ReasonForm,
    SupplierInvoiceForm,
    SupplierInvoiceLineForm,
)
from .models import (
    INVOICE_MATCH_STATUS_CHOICES,
    INVOICE_STATUS_CHOICES,
    PAYMENT_METHOD_CHOICES,
    VOUCHER_STATUS_CHOICES,
    PaymentTerm,
    PaymentVoucher,
    SupplierInvoice,
    SupplierInvoiceLine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class Echo:
    """A write-only file-like object that returns what it is given (CSV streaming buffer)."""

    def write(self, value):
        return value


def _has_named_url(name):
    try:
        reverse(name)
        return True
    except Exception:
        return False


def _require_manage(request):
    if not services.can_manage_invoicing(request.user):
        messages.error(request, 'You do not have permission to manage invoices.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_view(request):
    if not services.can_view_invoicing(request.user):
        messages.error(request, 'You do not have permission to view invoices.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _get_invoice(request, pk):
    return get_object_or_404(SupplierInvoice, pk=pk, tenant=request.tenant)


def _get_voucher(request, pk):
    return get_object_or_404(PaymentVoucher, pk=pk, tenant=request.tenant)


def _get_term(request, pk):
    return get_object_or_404(PaymentTerm, pk=pk, tenant=request.tenant)


# ---------------------------------------------------------------------------
# Invoice list + CRUD
# ---------------------------------------------------------------------------
@login_required
def invoice_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = SupplierInvoice.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'purchase_order', 'payment_term')

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    match_status = request.GET.get('match_status', '')
    vendor = request.GET.get('vendor', '')
    po = request.GET.get('po', '')

    if q:
        qs = qs.filter(
            Q(invoice_number__icontains=q)
            | Q(supplier_invoice_ref__icontains=q)
            | Q(purchase_order__po_number__icontains=q)
            | Q(vendor__legal_name__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if match_status:
        qs = qs.filter(match_status=match_status)
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
        'invoices': page_obj.object_list,
        'q': q,
        'status_choices': INVOICE_STATUS_CHOICES,
        'match_status_choices': INVOICE_MATCH_STATUS_CHOICES,
        'vendors': Vendor.objects.filter(tenant=request.tenant).order_by('legal_name'),
        'querystring': querystring.urlencode(),
        'can_manage': services.can_manage_invoicing(request.user),
    }
    return render(request, 'invoicing/list.html', context)


@login_required
def invoice_capture(request):
    denied = _require_manage(request)
    if denied:
        return denied

    initial = {}
    from_po = request.GET.get('from_po')
    if from_po:
        po = get_object_or_404(PurchaseOrder, pk=from_po, tenant=request.tenant)
        initial['purchase_order'] = po

    if request.method == 'POST':
        form = InvoiceCaptureForm(request.POST, request.FILES, tenant=request.tenant)
        if form.is_valid():
            try:
                invoice = services.capture_invoice_from_file(
                    tenant=request.tenant, user=request.user,
                    source_file=form.cleaned_data['source_file'],
                    purchase_order=form.cleaned_data.get('purchase_order'),
                    vendor=form.cleaned_data.get('vendor'),
                    supplier_invoice_ref=form.cleaned_data.get('supplier_invoice_ref', ''),
                )
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
                return render(request, 'invoicing/capture.html', {'form': form})
            messages.success(
                request,
                f'Invoice {invoice.invoice_number} captured. Review the lines, then submit '
                'for three-way matching.')
            return redirect('invoicing:invoice_detail', pk=invoice.pk)
    else:
        form = InvoiceCaptureForm(initial=initial, tenant=request.tenant)

    return render(request, 'invoicing/capture.html', {'form': form})


@login_required
def invoice_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    if request.method == 'POST':
        form = SupplierInvoiceForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            po = form.cleaned_data.get('purchase_order')
            vendor = form.cleaned_data.get('vendor')
            fields = {
                k: v for k, v in form.cleaned_data.items()
                if k not in ('purchase_order', 'vendor')
            }
            try:
                invoice = services.create_invoice(
                    tenant=request.tenant, user=request.user,
                    vendor=vendor, purchase_order=po, **fields)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
                return render(request, 'invoicing/form.html', {
                    'form': form, 'is_edit': False})
            messages.success(
                request,
                f'Invoice {invoice.invoice_number} created. Add the billed lines, then '
                'submit for matching.')
            return redirect('invoicing:invoice_detail', pk=invoice.pk)
    else:
        form = SupplierInvoiceForm(tenant=request.tenant)

    return render(request, 'invoicing/form.html', {'form': form, 'is_edit': False})


@login_required
def invoice_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    invoice = _get_invoice(request, pk)
    lines = invoice.lines.select_related(
        'purchase_order_line', 'goods_receipt_line', 'account_code').all()
    context = {
        'invoice': invoice,
        'po': invoice.purchase_order,
        'lines': lines,
        'dispute_notes': invoice.dispute_notes.select_related('author').all(),
        'vouchers': invoice.vouchers.all(),
        'status_events': invoice.status_events.select_related('actor').all()[:30],
        'dispute_form': DisputeForm(),
        'dispute_note_form': DisputeNoteForm(),
        'reject_form': ReasonForm(),
        'cancel_form': ReasonForm(),
        'voucher_form': CreateVoucherForm(),
        'can_manage': services.can_manage_invoicing(request.user),
    }
    return render(request, 'invoicing/detail.html', context)


@login_required
def invoice_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    invoice = _get_invoice(request, pk)
    if not invoice.is_editable:
        messages.error(request, 'Only a draft invoice can be edited.')
        return redirect('invoicing:invoice_detail', pk=invoice.pk)

    if request.method == 'POST':
        form = SupplierInvoiceForm(request.POST, instance=invoice, tenant=request.tenant)
        if form.is_valid():
            form.save()
            services.recompute_invoice_totals(invoice)
            services.record_audit(
                request.tenant, request.user, 'supplier_invoice.updated',
                target_type='SupplierInvoice', target_id=str(invoice.pk),
                message=f'{invoice.invoice_number} updated.', request=request)
            messages.success(request, 'Invoice updated.')
            return redirect('invoicing:invoice_detail', pk=invoice.pk)
    else:
        form = SupplierInvoiceForm(instance=invoice, tenant=request.tenant)

    return render(request, 'invoicing/form.html', {
        'form': form, 'invoice': invoice, 'is_edit': True})


@login_required
@require_POST
def invoice_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    invoice = _get_invoice(request, pk)
    if not invoice.is_editable:
        messages.error(request, 'Only a draft invoice can be deleted.')
        return redirect('invoicing:invoice_detail', pk=invoice.pk)

    number = invoice.invoice_number
    services.record_audit(
        request.tenant, request.user, 'supplier_invoice.deleted', level='warning',
        target_type='SupplierInvoice', target_id=str(invoice.pk),
        message=f'{number} deleted.', request=request)
    invoice.delete()
    messages.success(request, f'Invoice {number} deleted.')
    return redirect('invoicing:invoice_list')


# ---------------------------------------------------------------------------
# Invoice lifecycle (POST)
# ---------------------------------------------------------------------------
@login_required
@require_POST
def invoice_submit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    invoice = _get_invoice(request, pk)
    try:
        services.submit_invoice(invoice, request.user)
        messages.success(request, f'{invoice.invoice_number} submitted for matching.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:invoice_detail', pk=invoice.pk)


@login_required
@require_POST
def invoice_match(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    invoice = _get_invoice(request, pk)
    try:
        services.run_three_way_match(invoice)
        messages.success(
            request,
            f'Three-way match re-run: {invoice.get_match_status_display()}.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:invoice_detail', pk=invoice.pk)


@login_required
@require_POST
def invoice_approve(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    invoice = _get_invoice(request, pk)
    override = request.POST.get('override') in ('1', 'true', 'on', 'yes')
    try:
        services.approve_invoice(invoice, request.user, override=override)
        messages.success(request, f'{invoice.invoice_number} approved for payment.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:invoice_detail', pk=invoice.pk)


@login_required
@require_POST
def invoice_dispute(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    invoice = _get_invoice(request, pk)
    form = DisputeForm(request.POST)
    if not form.is_valid():
        for errs in form.errors.values():
            for err in errs:
                messages.error(request, err)
        return redirect('invoicing:invoice_detail', pk=invoice.pk)
    try:
        services.raise_dispute(invoice, request.user, form.cleaned_data['reason'])
        messages.success(request, f'{invoice.invoice_number} marked disputed.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:invoice_detail', pk=invoice.pk)


@login_required
@require_POST
def invoice_dispute_note(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    invoice = _get_invoice(request, pk)
    form = DisputeNoteForm(request.POST)
    if not form.is_valid():
        for errs in form.errors.values():
            for err in errs:
                messages.error(request, err)
        return redirect('invoicing:invoice_detail', pk=invoice.pk)
    try:
        services.add_dispute_note(invoice, request.user, form.cleaned_data['body'])
        messages.success(request, 'Message added.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:invoice_detail', pk=invoice.pk)


@login_required
@require_POST
def invoice_resolve(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    invoice = _get_invoice(request, pk)
    try:
        services.resolve_dispute(invoice, request.user, request.POST.get('note', ''))
        messages.success(request, f'{invoice.invoice_number} dispute resolved.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:invoice_detail', pk=invoice.pk)


@login_required
@require_POST
def invoice_reject(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    invoice = _get_invoice(request, pk)
    form = ReasonForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Please give a reason for rejecting the invoice.')
        return redirect('invoicing:invoice_detail', pk=invoice.pk)
    try:
        services.reject_invoice(invoice, request.user, form.cleaned_data['reason'])
        messages.success(request, f'{invoice.invoice_number} rejected.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:invoice_detail', pk=invoice.pk)


@login_required
@require_POST
def invoice_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    invoice = _get_invoice(request, pk)
    reason = request.POST.get('reason', '')
    try:
        services.cancel_invoice(invoice, request.user, reason)
        messages.success(request, f'{invoice.invoice_number} cancelled.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:invoice_detail', pk=invoice.pk)


# ---------------------------------------------------------------------------
# Invoice line items (draft only)
# ---------------------------------------------------------------------------
@login_required
def line_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    invoice = _get_invoice(request, pk)
    if not invoice.is_editable:
        messages.error(request, 'Lines can only be changed while the invoice is a draft.')
        return redirect('invoicing:invoice_detail', pk=invoice.pk)

    if request.method == 'POST':
        form = SupplierInvoiceLineForm(
            request.POST, tenant=request.tenant, supplier_invoice=invoice)
        if form.is_valid():
            try:
                services.add_invoice_line(
                    invoice,
                    description=form.cleaned_data.get('description', ''),
                    quantity=form.cleaned_data['quantity'],
                    unit_price=form.cleaned_data['unit_price'],
                    uom=form.cleaned_data.get('uom', ''),
                    purchase_order_line=form.cleaned_data.get('purchase_order_line'),
                    goods_receipt_line=form.cleaned_data.get('goods_receipt_line'),
                    account_code=form.cleaned_data.get('account_code'),
                    tax_amount=form.cleaned_data.get('tax_amount') or 0,
                    notes=form.cleaned_data.get('notes', ''),
                )
                services.recompute_invoice_totals(invoice)
                messages.success(request, 'Line added.')
                return redirect('invoicing:invoice_detail', pk=invoice.pk)
            except ValidationError as exc:
                for msg in exc.messages:
                    messages.error(request, msg)
    else:
        form = SupplierInvoiceLineForm(tenant=request.tenant, supplier_invoice=invoice)

    return render(request, 'invoicing/line_form.html', {
        'form': form, 'invoice': invoice, 'is_edit': False})


@login_required
def line_edit(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    invoice = _get_invoice(request, pk)
    line = get_object_or_404(
        SupplierInvoiceLine, pk=line_pk, supplier_invoice=invoice, tenant=request.tenant)
    if not invoice.is_editable:
        messages.error(request, 'Lines can only be changed while the invoice is a draft.')
        return redirect('invoicing:invoice_detail', pk=invoice.pk)

    if request.method == 'POST':
        form = SupplierInvoiceLineForm(
            request.POST, instance=line, tenant=request.tenant, supplier_invoice=invoice)
        if form.is_valid():
            obj = form.save(commit=False)
            pol = obj.purchase_order_line
            if not obj.description and pol is not None:
                obj.description = pol.description
            if (not obj.uom or obj.uom == 'unit') and pol is not None:
                obj.uom = pol.uom
            obj.save()
            services.recompute_invoice_totals(invoice)
            messages.success(request, 'Line updated.')
            return redirect('invoicing:invoice_detail', pk=invoice.pk)
    else:
        form = SupplierInvoiceLineForm(
            instance=line, tenant=request.tenant, supplier_invoice=invoice)

    return render(request, 'invoicing/line_form.html', {
        'form': form, 'invoice': invoice, 'line': line, 'is_edit': True})


@login_required
@require_POST
def line_delete(request, pk, line_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    invoice = _get_invoice(request, pk)
    line = get_object_or_404(
        SupplierInvoiceLine, pk=line_pk, supplier_invoice=invoice, tenant=request.tenant)
    if not invoice.is_editable:
        messages.error(request, 'Lines can only be changed while the invoice is a draft.')
        return redirect('invoicing:invoice_detail', pk=invoice.pk)
    line.delete()
    services.recompute_invoice_totals(invoice)
    messages.success(request, 'Line removed.')
    return redirect('invoicing:invoice_detail', pk=invoice.pk)


# ---------------------------------------------------------------------------
# Payment vouchers
# ---------------------------------------------------------------------------
@login_required
@require_POST
def voucher_create(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    invoice = _get_invoice(request, pk)

    # Quick action from the analytics dashboard: one click to voucher an approved invoice and
    # take its early-payment discount (no full form).
    if request.POST.get('quick_action') == '1':
        try:
            voucher = services.create_voucher(invoice, request.user, take_discount=True)
            messages.success(
                request,
                f'Voucher {voucher.voucher_number} created with the early-payment discount.')
            return redirect('invoicing:voucher_detail', pk=voucher.pk)
        except ValidationError as exc:
            for msg in exc.messages:
                messages.error(request, msg)
        return redirect('invoicing:analytics_dashboard')

    form = CreateVoucherForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Invalid voucher details.')
        return redirect('invoicing:invoice_detail', pk=invoice.pk)
    try:
        voucher = services.create_voucher(
            invoice, request.user,
            take_discount=form.cleaned_data.get('take_discount'),
            payment_method=form.cleaned_data.get('payment_method', 'bank_transfer'),
            scheduled_date=form.cleaned_data.get('scheduled_date'))
        messages.success(request, f'Payment voucher {voucher.voucher_number} created.')
        return redirect('invoicing:voucher_detail', pk=voucher.pk)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:invoice_detail', pk=invoice.pk)


@login_required
def voucher_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = PaymentVoucher.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'supplier_invoice')

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    vendor = request.GET.get('vendor', '')
    if q:
        qs = qs.filter(
            Q(voucher_number__icontains=q)
            | Q(supplier_invoice__invoice_number__icontains=q)
            | Q(vendor__legal_name__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if vendor:
        qs = qs.filter(vendor_id=vendor)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    querystring = request.GET.copy()
    querystring.pop('page', None)

    return render(request, 'invoicing/voucher_list.html', {
        'page_obj': page_obj,
        'vouchers': page_obj.object_list,
        'q': q,
        'status_choices': VOUCHER_STATUS_CHOICES,
        'vendors': Vendor.objects.filter(tenant=request.tenant).order_by('legal_name'),
        'querystring': querystring.urlencode(),
        'can_manage': services.can_manage_invoicing(request.user),
    })


@login_required
def voucher_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    voucher = _get_voucher(request, pk)
    return render(request, 'invoicing/voucher_detail.html', {
        'voucher': voucher,
        'invoice': voucher.supplier_invoice,
        'status_events': voucher.status_events.select_related('actor').all()[:30],
        'pay_form': PayVoucherForm(initial={'payment_method': voucher.payment_method}),
        'cancel_form': ReasonForm(),
        'payment_method_choices': PAYMENT_METHOD_CHOICES,
        'can_manage': services.can_manage_invoicing(request.user),
    })


@login_required
@require_POST
def voucher_approve(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    voucher = _get_voucher(request, pk)
    try:
        services.approve_voucher(voucher, request.user)
        messages.success(request, f'{voucher.voucher_number} approved.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:voucher_detail', pk=voucher.pk)


@login_required
@require_POST
def voucher_schedule(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    voucher = _get_voucher(request, pk)
    scheduled_date = request.POST.get('scheduled_date') or None
    try:
        services.schedule_voucher(voucher, request.user, scheduled_date=scheduled_date)
        messages.success(request, f'{voucher.voucher_number} scheduled.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:voucher_detail', pk=voucher.pk)


@login_required
@require_POST
def voucher_pay(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    voucher = _get_voucher(request, pk)
    form = PayVoucherForm(request.POST)
    method = form.cleaned_data.get('payment_method') if form.is_valid() else None
    reference = form.cleaned_data.get('reference', '') if form.is_valid() else ''
    try:
        services.pay_voucher(
            voucher, request.user, payment_method=method, reference=reference)
        messages.success(
            request,
            f'{voucher.voucher_number} paid via the gateway. Invoice marked paid.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:voucher_detail', pk=voucher.pk)


@login_required
@require_POST
def voucher_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    voucher = _get_voucher(request, pk)
    reason = request.POST.get('reason', '')
    try:
        services.cancel_voucher(voucher, request.user, reason)
        messages.success(request, f'{voucher.voucher_number} cancelled.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('invoicing:voucher_detail', pk=voucher.pk)


def _run_voucher_batch(request, action_fn, *, verb, **kwargs):
    """Apply a per-voucher service action to the selected vouchers, reporting partial success.

    Each voucher is processed through the existing TOCTOU-safe service function, so a failure on
    one (wrong status, gateway decline) never rolls back the others — it is reported per voucher.
    """
    ids = request.POST.getlist('voucher_ids')
    if not ids:
        messages.warning(request, 'Select at least one voucher first.')
        return redirect('invoicing:voucher_list')
    vouchers = PaymentVoucher.objects.filter(tenant=request.tenant, pk__in=ids)
    ok = 0
    for voucher in vouchers:
        try:
            action_fn(voucher, request.user, **kwargs)
            ok += 1
        except ValidationError as exc:
            messages.error(request, f'{voucher.voucher_number}: {exc.messages[0]}')
    if ok:
        messages.success(request, f'{ok} voucher(s) {verb}.')
    return redirect('invoicing:voucher_list')


@login_required
@require_POST
def batch_schedule_vouchers(request):
    denied = _require_manage(request)
    if denied:
        return denied
    scheduled_date = request.POST.get('scheduled_date') or None
    return _run_voucher_batch(
        request, services.schedule_voucher, verb='scheduled', scheduled_date=scheduled_date)


@login_required
@require_POST
def batch_pay_vouchers(request):
    denied = _require_manage(request)
    if denied:
        return denied
    return _run_voucher_batch(request, services.pay_voucher, verb='paid')


@login_required
def export_unpaid_invoices_csv(request):
    """Stream the unpaid (submitted/approved) invoices as a CSV AP-aging report.

    Honours the same search / vendor / PO filters as ``invoice_list`` so the export matches
    what the user is looking at. Aging buckets mirror ``services.tenant_invoice_metrics``.
    """
    denied = _require_view(request)
    if denied:
        return denied

    qs = SupplierInvoice.objects.filter(
        tenant=request.tenant, status__in=('submitted', 'approved')
    ).select_related('vendor', 'purchase_order').order_by('due_date')

    q = request.GET.get('q', '').strip()
    vendor = request.GET.get('vendor', '')
    po = request.GET.get('po', '')
    if q:
        qs = qs.filter(
            Q(invoice_number__icontains=q)
            | Q(supplier_invoice_ref__icontains=q)
            | Q(purchase_order__po_number__icontains=q)
            | Q(vendor__legal_name__icontains=q))
    if vendor:
        qs = qs.filter(vendor_id=vendor)
    if po:
        qs = qs.filter(purchase_order_id=po)

    today = timezone.localdate()

    def rows():
        writer = csv.writer(Echo())
        yield writer.writerow([
            'Invoice #', 'Supplier ref', 'Vendor', 'PO', 'Status', 'Due date',
            'Days overdue', 'Aging bucket', 'Currency', 'Total', 'Net payable'])
        for inv in qs:
            overdue_days = (today - inv.due_date).days if inv.due_date else 0
            if overdue_days <= 0:
                bucket = 'Current'
            elif overdue_days <= 30:
                bucket = '1-30 days'
            elif overdue_days <= 60:
                bucket = '31-60 days'
            else:
                bucket = '60+ days'
            yield writer.writerow([
                inv.invoice_number, inv.supplier_invoice_ref or '',
                inv.vendor.legal_name if inv.vendor else '',
                inv.purchase_order.po_number if inv.purchase_order else '',
                inv.get_status_display(),
                inv.due_date.strftime('%Y-%m-%d') if inv.due_date else '',
                overdue_days if overdue_days > 0 else 0, bucket,
                inv.currency, f'{inv.total_amount:.2f}', f'{inv.net_payable:.2f}'])

    response = StreamingHttpResponse(rows(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="unpaid-invoices.csv"'
    return response


# ---------------------------------------------------------------------------
# Payment terms master (CRUD)
# ---------------------------------------------------------------------------
@login_required
def term_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    terms = PaymentTerm.objects.filter(tenant=request.tenant).order_by('code')
    return render(request, 'invoicing/terms_list.html', {
        'terms': terms,
        'can_manage': services.can_manage_invoicing(request.user),
    })


@login_required
def term_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    if request.method == 'POST':
        form = PaymentTermForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            term = form.save(commit=False)
            term.tenant = request.tenant
            term.save()
            messages.success(request, f'Payment term {term.code} created.')
            return redirect('invoicing:term_list')
    else:
        form = PaymentTermForm(tenant=request.tenant)

    return render(request, 'invoicing/terms_form.html', {'form': form, 'is_edit': False})


@login_required
def term_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    term = _get_term(request, pk)
    if request.method == 'POST':
        form = PaymentTermForm(request.POST, instance=term, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Payment term updated.')
            return redirect('invoicing:term_list')
    else:
        form = PaymentTermForm(instance=term, tenant=request.tenant)

    return render(request, 'invoicing/terms_form.html', {
        'form': form, 'term': term, 'is_edit': True})


@login_required
@require_POST
def term_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    term = _get_term(request, pk)
    if term.supplier_invoices.exists():
        messages.error(
            request, 'This payment term is in use by invoices and cannot be deleted. '
                     'Deactivate it instead.')
        return redirect('invoicing:term_list')
    code = term.code
    term.delete()
    messages.success(request, f'Payment term {code} deleted.')
    return redirect('invoicing:term_list')


# ---------------------------------------------------------------------------
# Analytics dashboard (+ lazy alert sweep + early-payment discounts + AP aging)
# ---------------------------------------------------------------------------
@login_required
def analytics_dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied

    if services.can_manage_invoicing(request.user):
        services.scan_invoice_alerts(tenant=request.tenant)

    metrics = services.tenant_invoice_metrics(request.tenant)
    recent = SupplierInvoice.objects.filter(tenant=request.tenant).select_related(
        'vendor', 'purchase_order')[:10]

    aging = metrics['aging']
    aging_chart = {
        'labels': ['Current', '1–30 days', '31–60 days', '60+ days'],
        'amounts': [
            float(aging['current']), float(aging['d1_30']),
            float(aging['d31_60']), float(aging['d60_plus']),
        ],
    }
    return render(request, 'invoicing/analytics.html', {
        'metrics': metrics,
        'recent_invoices': recent,
        'aging_chart': aging_chart,
        'can_manage': services.can_manage_invoicing(request.user),
    })
