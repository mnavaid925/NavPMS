"""Invoice & Voucher Management domain services (Module 14 — Accounts Payable).

All state transitions live here, wrapped in ``@transaction.atomic`` with audit logging via
:func:`apps.tenants.services.record_audit`. Mirrors the Module 11/12/13 service style —
perms + numbering + lifecycle + alert sweep + analytics — and adds:

  * OCR capture of a supplier invoice from an uploaded file (``capture_invoice_from_file``),
  * a READ-ONLY three-way match (``run_three_way_match``) of each invoice line against its PO
    line (ordered qty/price) and the accepted qty from the Goods Receipt, with configurable
    tolerances and an over-billing guard computed *within this app* (no PO/GRN schema change),
  * a draft -> submitted -> approved -> paid invoice lifecycle plus a disputed branch and an
    append-only buyer<->supplier dispute thread, and
  * a Payment Voucher that authorises, schedules and PAYS an approved invoice through the
    existing pluggable payment gateway (:mod:`apps.tenants.gateways`), idempotently.

The invoice NEVER posts to the PO — Module 13's GRN already did. The match is purely
informational + a payment gate.
"""
import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Sum
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant
from apps.portal.models import Notification
from apps.tenants.services import record_audit
from apps.tenants.gateways import get_gateway

from .ocr import get_ocr_engine
from .models import (
    INVOICE_VENDOR_VISIBLE_STATUSES,
    INVOICE_VOUCHERABLE_STATUSES,
    LINE_EXCEPTION_STATUSES,
    InvoiceDisputeNote,
    PaymentTerm,
    PaymentVoucher,
    PaymentVoucherStatusEvent,
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierInvoiceStatusEvent,
)

# Roles allowed to capture/match/approve invoices and authorise payment (mirrors the rest of
# the P2P chain — there is no dedicated AP/accountant role in the project yet).
MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
VIEW_ROLES = MANAGE_ROLES + ('approver',)

# File-upload whitelist for invoice capture (OCR-safe formats). Whitelist, NOT blacklist —
# .svg/.html/.js become stored XSS when Apache serves MEDIA inline.
MAX_INVOICE_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_INVOICE_EXTENSIONS = frozenset({
    '.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.txt',
})

# Default three-way-match tolerances (percent). Overridable per call or via settings/.env.
_DEFAULT_QTY_TOL = Decimal('2')
_DEFAULT_PRICE_TOL = Decimal('2')
# Days before the early-payment discount lapses that the "closing soon" alert fires.
DISCOUNT_ALERT_WINDOW_DAYS = 3


# ---------------------------------------------------------------------------
# File-upload validation (shared by the form + the vendor-portal intake)
# ---------------------------------------------------------------------------
def upload_error(f, max_bytes=MAX_INVOICE_FILE_BYTES):
    """Return an error string for a bad upload, else ''. Whitelist-based."""
    if not f:
        return ''
    if f.size > max_bytes:
        return f'File size must be {max_bytes // (1024 * 1024)} MB or less.'
    ext = os.path.splitext((f.name or '').lower())[1]
    if ext not in ALLOWED_INVOICE_EXTENSIONS:
        return (
            f'File type "{ext or "unknown"}" is not allowed. '
            f'Permitted: {", ".join(sorted(ALLOWED_INVOICE_EXTENSIONS))}.'
        )
    return ''


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _has_role(user, roles):
    """True if the user holds any of ``roles`` (string slugs)."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'is_tenant_admin', False):
        return True
    role = getattr(user, 'role', None)
    if isinstance(role, str):
        role_slug = role
    else:
        role_slug = getattr(role, 'slug', None) or getattr(role, 'name', None)
    return role_slug in roles


def can_manage_invoicing(user):
    """May capture/match/approve invoices, manage payment terms and pay vouchers."""
    return _has_role(user, MANAGE_ROLES)


def can_view_invoicing(user):
    """May view invoices / analytics (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Visibility gate (vendor portal)
# ---------------------------------------------------------------------------
def invoice_visible_to(user, invoice):
    """True if ``user`` may view ``invoice``.

    Internal managers/approvers may view any invoice in their tenant; a vendor portal user
    may view only their own invoices, and only once submitted (an internally-entered draft is
    never exposed to the supplier).
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_vendor_user', False):
        return (
            getattr(user, 'vendor_id', None) == invoice.vendor_id
            and invoice.status in INVOICE_VENDOR_VISIBLE_STATUSES
        )
    return can_view_invoicing(user)


# ---------------------------------------------------------------------------
# Helpers — timeline + notifications
# ---------------------------------------------------------------------------
def record_invoice_event(invoice, status, user, note=''):
    """Append an immutable invoice lifecycle timeline row."""
    return SupplierInvoiceStatusEvent.all_objects.create(
        tenant=invoice.tenant, supplier_invoice=invoice, status=status,
        note=(note or '')[:255], actor=user,
    )


def record_voucher_event(voucher, status, user, note=''):
    """Append an immutable voucher lifecycle timeline row."""
    return PaymentVoucherStatusEvent.all_objects.create(
        tenant=voucher.tenant, payment_voucher=voucher, status=status,
        note=(note or '')[:255], actor=user,
    )


def _notify(user, *, tenant, link, category, priority, title, message):
    """Create a portal Notification (no-op if there is no recipient)."""
    if not user:
        return None
    return Notification.all_objects.create(
        tenant=tenant, user=user, category=category, priority=priority,
        title=title[:160], message=message, link_url=link,
    )


def _invoice_owner(invoice):
    """The internal recipient for an invoice alert (PO owner, else its creator)."""
    owner = getattr(invoice.purchase_order, 'owner', None) if invoice.purchase_order_id else None
    return owner or invoice.created_by


def _notify_owner(invoice, *, category, priority, title, message):
    """Notify the internal owner (buyer) of the invoice."""
    owner = _invoice_owner(invoice)
    if not owner:
        return None
    try:
        link = reverse('invoicing:invoice_detail', kwargs={'pk': invoice.pk})
    except Exception:
        link = ''
    return _notify(owner, tenant=invoice.tenant, link=link, category=category,
                   priority=priority, title=title, message=message)


def _notify_vendor(invoice, *, category, priority, title, message):
    """Notify the supplier's portal user about their invoice."""
    portal_user = getattr(invoice.vendor, 'portal_user', None) if invoice.vendor_id else None
    if not portal_user:
        return None
    try:
        link = reverse('vendor_portal:invoice_detail', kwargs={'pk': invoice.pk})
    except Exception:
        link = ''
    return _notify(portal_user, tenant=invoice.tenant, link=link, category=category,
                   priority=priority, title=title, message=message)


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def _next_number(tenant, model, field, prefix_kind):
    """Generate the next gap-free ``<KIND>-<SLUG>-NNNNN`` for ``tenant``."""
    slug = (tenant.slug or str(tenant.pk))[:6].upper()
    prefix = f'{prefix_kind}-{slug}-'
    last = (
        model.all_objects
        .filter(tenant=tenant, **{f'{field}__startswith': prefix})
        .order_by(f'-{field}')
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(getattr(last, field).rsplit('-', 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    number = f'{prefix}{seq:05d}'
    while model.all_objects.filter(tenant=tenant, **{field: number}).exists():
        seq += 1
        number = f'{prefix}{seq:05d}'
    return number


def next_invoice_number(tenant):
    """Generate the next gap-free ``SINV-<SLUG>-NNNNN`` for ``tenant``."""
    return _next_number(tenant, SupplierInvoice, 'invoice_number', 'SINV')


def next_voucher_number(tenant):
    """Generate the next gap-free ``VCH-<SLUG>-NNNNN`` for ``tenant``."""
    return _next_number(tenant, PaymentVoucher, 'voucher_number', 'VCH')


# ---------------------------------------------------------------------------
# Totals + payment terms
# ---------------------------------------------------------------------------
def recompute_invoice_totals(invoice):
    """Recompute ``subtotal``/``tax``/``total`` from the lines and persist."""
    lines = list(invoice.lines.all())
    subtotal = sum((ln.line_total or Decimal('0') for ln in lines), Decimal('0.00'))
    line_tax = sum((ln.tax_amount or Decimal('0') for ln in lines), Decimal('0.00'))
    invoice.subtotal = subtotal
    if line_tax > 0:
        invoice.tax_amount = line_tax
    invoice.total_amount = (
        subtotal + (invoice.tax_amount or Decimal('0')) + (invoice.shipping_amount or Decimal('0'))
    )
    invoice.save(update_fields=['subtotal', 'tax_amount', 'total_amount', 'updated_at'])
    return invoice.total_amount


def apply_payment_term(invoice):
    """Derive ``due_date`` / ``discount_due_date`` / ``discount_amount`` from the term."""
    term = invoice.payment_term
    base_date = invoice.invoice_date or invoice.received_date
    if term and base_date:
        invoice.due_date = term.due_date_for(base_date)
        invoice.discount_due_date = term.discount_date_for(base_date)
        if term.has_discount:
            invoice.discount_amount = (
                (invoice.total_amount or Decimal('0')) * term.discount_percent / Decimal('100')
            ).quantize(Decimal('0.01'))
        else:
            invoice.discount_amount = Decimal('0.00')
    invoice.save(update_fields=[
        'due_date', 'discount_due_date', 'discount_amount', 'updated_at',
    ])
    return invoice


# ---------------------------------------------------------------------------
# 1. Invoice creation + capture (OCR) + lines
# ---------------------------------------------------------------------------
def create_invoice(*, tenant, user, vendor, purchase_order=None, **fields):
    """Create a draft supplier invoice with a collision-safe number."""
    if purchase_order is not None and purchase_order.vendor_id:
        vendor = purchase_order.vendor
    if vendor is None:
        raise ValidationError('A supplier is required to create an invoice.')
    fields.pop('vendor', None)
    fields.pop('tenant', None)
    last_exc = None
    for _attempt in range(5):
        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=tenant.pk)
                invoice = SupplierInvoice.all_objects.create(
                    tenant=tenant,
                    invoice_number=next_invoice_number(tenant),
                    vendor=vendor,
                    purchase_order=purchase_order,
                    status='draft',
                    created_by=user,
                    **fields,
                )
                record_invoice_event(invoice, 'draft', user, 'Invoice created')
                record_audit(
                    tenant, user, 'supplier_invoice.created',
                    target_type='SupplierInvoice', target_id=str(invoice.id),
                    message=f'{invoice.invoice_number} for {vendor.legal_name}',
                )
            return invoice
        except IntegrityError as exc:
            last_exc = exc
    raise last_exc


def add_invoice_line(invoice, *, description='', quantity, unit_price,
                     purchase_order_line=None, goods_receipt_line=None, uom='',
                     account_code=None, tax_amount=Decimal('0.00'), **fields):
    """Add a billed line to a draft invoice (line_total computed in Model.save)."""
    if not invoice.is_editable:
        raise ValidationError('Lines can only be changed while the invoice is a draft.')
    quantity = Decimal(str(quantity or '0'))
    unit_price = Decimal(str(unit_price or '0'))
    if quantity <= 0:
        raise ValidationError('Quantity must be greater than zero.')
    if unit_price < 0:
        raise ValidationError('Unit price cannot be negative.')
    next_no = (invoice.lines.aggregate(m=Max('line_no'))['m'] or 0) + 1
    if not description and purchase_order_line is not None:
        description = purchase_order_line.description
    if not uom and purchase_order_line is not None:
        uom = purchase_order_line.uom
    if account_code is None and purchase_order_line is not None:
        account_code = purchase_order_line.account_code
    return SupplierInvoiceLine.all_objects.create(
        tenant=invoice.tenant, supplier_invoice=invoice,
        purchase_order_line=purchase_order_line,
        goods_receipt_line=goods_receipt_line,
        account_code=account_code,
        line_no=fields.pop('line_no', next_no),
        description=description, uom=uom or 'unit',
        quantity=quantity, unit_price=unit_price,
        tax_amount=Decimal(str(tax_amount or '0')),
        match_status='pending',
        **fields,
    )


def capture_invoice_from_file(*, tenant, user, source_file, purchase_order=None,
                              vendor=None, submitted_via_portal=False, **fields):
    """OCR-capture an uploaded invoice into a draft SupplierInvoice + lines.

    Validates the upload (whitelist), runs the configured OCR engine, then creates the
    invoice and one line per extracted line — mapping each to a PO line by description when a
    PO is supplied. The totals are recomputed server-side (OCR output is never trusted for
    payment).
    """
    err = upload_error(source_file)
    if err:
        raise ValidationError(err)
    if purchase_order is not None and purchase_order.vendor_id:
        vendor = purchase_order.vendor
    if vendor is None:
        raise ValidationError('A supplier (or a PO with a supplier) is required to capture an invoice.')

    engine = get_ocr_engine()
    result = engine.extract(source_file, purchase_order=purchase_order)

    invoice = create_invoice(
        tenant=tenant, user=user, vendor=vendor, purchase_order=purchase_order,
        source_file=source_file,
        supplier_invoice_ref=fields.pop('supplier_invoice_ref', '') or result.supplier_invoice_ref,
        currency=fields.pop('currency', '') or result.currency or 'USD',
        ocr_engine=result.engine,
        ocr_confidence=result.confidence,
        ocr_raw=result.raw or {},
        tax_amount=result.tax_amount or Decimal('0.00'),
        shipping_amount=result.shipping_amount or Decimal('0.00'),
        submitted_via_portal=submitted_via_portal,
        **fields,
    )

    po_lines_by_desc = {}
    if purchase_order is not None:
        for pol in purchase_order.lines.exclude(delivery_status='cancelled'):
            po_lines_by_desc.setdefault(pol.description, pol)

    for ocr_line in result.lines:
        pol = po_lines_by_desc.get(ocr_line.description)
        add_invoice_line(
            invoice, description=ocr_line.description, quantity=ocr_line.quantity,
            unit_price=ocr_line.unit_price, uom=ocr_line.uom, purchase_order_line=pol,
        )

    recompute_invoice_totals(invoice)
    record_audit(
        tenant, user, 'supplier_invoice.captured',
        target_type='SupplierInvoice', target_id=str(invoice.id),
        message=f'{invoice.invoice_number} captured via {result.engine} OCR',
    )
    return invoice


# ---------------------------------------------------------------------------
# 2. Three-way matching (invoice vs PO vs GRN) — READ-ONLY against PO/GRN
# ---------------------------------------------------------------------------
def _received_qty_for_po_line(po_line):
    """The qty received & accepted against a PO line — the authoritative 'received' leg.

    Reads ``PurchaseOrderLine.received_quantity``, which both Module 13's GRN posting and
    Module 12's fulfilment delivery confirmation feed through the guarded
    ``record_line_receipt`` (the GRN posts only the *accepted* qty), so it is correct
    regardless of which receiving path the goods came through.
    """
    return po_line.received_quantity or Decimal('0')


def _already_invoiced_for_po_line(po_line, exclude_invoice):
    """Qty already billed against a PO line on OTHER live invoices (over-billing guard).

    Only committed invoices count — drafts (not yet submitted), cancelled and rejected
    invoices are excluded, so an in-progress draft never inflates the over-billed check.
    """
    return (
        SupplierInvoiceLine.all_objects
        .filter(purchase_order_line=po_line)
        .exclude(supplier_invoice=exclude_invoice)
        .exclude(supplier_invoice__status__in=('draft', 'cancelled', 'rejected'))
        .aggregate(s=Sum('quantity'))['s'] or Decimal('0')
    )


def run_three_way_match(invoice, *, qty_tol=None, price_tol=None):
    """Match every invoice line against its PO line (ordered) + GRN (accepted received).

    Sets each line's ``match_status`` and the variance fields, and rolls the result up to the
    header ``match_status`` (``matched`` only if every line matched). Purely read-only against
    the PO and GRN — it computes a payment gate, it does not mutate them.
    """
    qty_tol = Decimal(str(
        qty_tol if qty_tol is not None
        else getattr(settings, 'INVOICE_QTY_TOLERANCE_PCT', _DEFAULT_QTY_TOL)))
    price_tol = Decimal(str(
        price_tol if price_tol is not None
        else getattr(settings, 'INVOICE_PRICE_TOLERANCE_PCT', _DEFAULT_PRICE_TOL)))

    has_line = False
    has_exception = False
    for line in invoice.lines.select_related('purchase_order_line'):
        has_line = True
        pol = line.purchase_order_line
        inv_qty = line.quantity or Decimal('0')
        inv_price = line.unit_price or Decimal('0')

        if pol is None:
            line.match_status = 'no_po'
            line.matched_po_qty = Decimal('0.00')
            line.matched_received_qty = Decimal('0.00')
            line.qty_variance = Decimal('0.00')
            line.price_variance = Decimal('0.00')
            line.match_note = 'No purchase-order line to match against.'
            has_exception = True
        else:
            ordered = pol.quantity or Decimal('0')
            po_price = pol.unit_price or Decimal('0')
            received = _received_qty_for_po_line(pol)
            already = _already_invoiced_for_po_line(pol, invoice)

            line.matched_po_qty = ordered
            line.matched_received_qty = received
            line.qty_variance = inv_qty - received
            line.price_variance = inv_price - po_price

            qty_tol_abs = (received * qty_tol / Decimal('100')) if received > 0 else Decimal('0')
            price_tol_abs = po_price * price_tol / Decimal('100')

            if received <= 0:
                line.match_status = 'no_receipt'
                line.match_note = 'No accepted goods receipt for this line yet.'
            elif (already + inv_qty) > received + qty_tol_abs:
                line.match_status = 'over_billed'
                line.match_note = (
                    f'Cumulative invoiced {already + inv_qty} exceeds received {received}.')
            elif abs(line.price_variance) > price_tol_abs:
                line.match_status = 'price_variance'
                line.match_note = f'Unit price {inv_price} vs PO {po_price}.'
            elif abs(line.qty_variance) > qty_tol_abs:
                line.match_status = 'qty_variance'
                line.match_note = f'Invoiced {inv_qty} vs received {received}.'
            else:
                line.match_status = 'matched'
                line.match_note = ''
            if line.match_status in LINE_EXCEPTION_STATUSES:
                has_exception = True

        line.save(update_fields=[
            'match_status', 'matched_po_qty', 'matched_received_qty', 'qty_variance',
            'price_variance', 'match_note', 'updated_at',
        ])

    if not has_line:
        invoice.match_status = 'unmatched'
    elif has_exception:
        invoice.match_status = 'exceptions'
    else:
        invoice.match_status = 'matched'
    invoice.save(update_fields=['match_status', 'updated_at'])
    return invoice


# ---------------------------------------------------------------------------
# Invoice lifecycle
# ---------------------------------------------------------------------------
def submit_invoice(invoice, user, *, qty_tol=None, price_tol=None):
    """Submit a draft invoice for matching + approval: draft -> submitted."""
    with transaction.atomic():
        if not invoice.can_submit:
            raise ValidationError('Only a draft invoice can be submitted.')
        if not invoice.lines.exists():
            raise ValidationError('Add at least one line before submitting.')
        invoice = SupplierInvoice.all_objects.select_for_update().get(pk=invoice.pk)
        recompute_invoice_totals(invoice)
        apply_payment_term(invoice)
        run_three_way_match(invoice, qty_tol=qty_tol, price_tol=price_tol)
        invoice.status = 'submitted'
        invoice.submitted_at = timezone.now()
        invoice.submitted_by = user
        invoice.overdue_alerted_at = None
        invoice.discount_alerted_at = None
        invoice.save(update_fields=[
            'status', 'submitted_at', 'submitted_by', 'overdue_alerted_at',
            'discount_alerted_at', 'updated_at',
        ])
        record_invoice_event(
            invoice, 'submitted', user,
            f'Submitted (match: {invoice.get_match_status_display()})')
        record_audit(
            invoice.tenant, user, 'supplier_invoice.submitted',
            target_type='SupplierInvoice', target_id=str(invoice.id),
            message=f'{invoice.invoice_number} submitted ({invoice.match_status})',
        )
        _notify_owner(
            invoice, category='approval', priority='normal',
            title=f'Invoice to approve: {invoice.invoice_number}',
            message=f'{invoice.invoice_number} from {invoice.vendor.legal_name} '
                    f'({invoice.match_status}) is awaiting approval.',
        )
    return invoice


def approve_invoice(invoice, user, *, override=False, note=''):
    """Approve a submitted invoice for payment: submitted -> approved.

    Blocked when the three-way match has exceptions, unless ``override=True`` (recorded).
    """
    with transaction.atomic():
        if not invoice.can_approve:
            raise ValidationError('Only a submitted invoice can be approved.')
        invoice = SupplierInvoice.all_objects.select_for_update().get(pk=invoice.pk)
        if invoice.match_status == 'exceptions' and not override:
            raise ValidationError(
                'This invoice has three-way-match exceptions. Resolve them, raise a dispute, '
                'or approve with override.')
        invoice.status = 'approved'
        invoice.approved_at = timezone.now()
        invoice.approved_by = user
        invoice.match_override = bool(override and invoice.match_status == 'exceptions')
        invoice.save(update_fields=[
            'status', 'approved_at', 'approved_by', 'match_override', 'updated_at'])
        msg = 'Approved with match override' if invoice.match_override else 'Approved'
        record_invoice_event(invoice, 'approved', user, (note or msg)[:255])
        record_audit(
            invoice.tenant, user, 'supplier_invoice.approved',
            target_type='SupplierInvoice', target_id=str(invoice.id),
            message=f'{invoice.invoice_number} approved'
                    f'{" (override)" if invoice.match_override else ""}',
        )
        _notify_vendor(
            invoice, category='info', priority='normal',
            title=f'Invoice approved: {invoice.invoice_number}',
            message=f'Your invoice {invoice.supplier_invoice_ref or invoice.invoice_number} '
                    'has been approved for payment.',
        )
    return invoice


def add_dispute_note(invoice, user, body, *, is_from_vendor=False):
    """Append a message to the invoice dispute thread and notify the other side."""
    body = (body or '').strip()
    if not body:
        raise ValidationError('A message is required.')
    if invoice.status in ('paid', 'cancelled'):
        raise ValidationError('This invoice is closed.')
    note = InvoiceDisputeNote.all_objects.create(
        tenant=invoice.tenant, supplier_invoice=invoice, author=user,
        is_from_vendor=is_from_vendor, body=body,
    )
    if is_from_vendor:
        _notify_owner(
            invoice, category='info', priority='normal',
            title=f'Dispute reply: {invoice.invoice_number}',
            message=f'{invoice.vendor.legal_name} replied on invoice {invoice.invoice_number}.')
    else:
        _notify_vendor(
            invoice, category='info', priority='normal',
            title=f'Message on invoice {invoice.invoice_number}',
            message='The buyer added a note to your invoice.')
    return note


def raise_dispute(invoice, user, reason='', *, is_from_vendor=False):
    """Open a dispute on a submitted invoice: submitted -> disputed."""
    with transaction.atomic():
        if not invoice.can_dispute:
            raise ValidationError('Only a submitted invoice can be disputed.')
        reason = (reason or '').strip()
        invoice = SupplierInvoice.all_objects.select_for_update().get(pk=invoice.pk)
        invoice.status = 'disputed'
        invoice.disputed_at = timezone.now()
        invoice.disputed_by = user
        invoice.dispute_reason = reason[:255]
        invoice.save(update_fields=[
            'status', 'disputed_at', 'disputed_by', 'dispute_reason', 'updated_at'])
        if reason:
            InvoiceDisputeNote.all_objects.create(
                tenant=invoice.tenant, supplier_invoice=invoice, author=user,
                is_from_vendor=is_from_vendor, body=reason,
            )
        record_invoice_event(invoice, 'disputed', user, reason[:255] or 'Disputed')
        record_audit(
            invoice.tenant, user, 'supplier_invoice.disputed', level='warning',
            target_type='SupplierInvoice', target_id=str(invoice.id),
            message=f'{invoice.invoice_number} disputed: {reason}'[:255],
        )
        if is_from_vendor:
            _notify_owner(
                invoice, category='deadline', priority='high',
                title=f'Invoice disputed: {invoice.invoice_number}',
                message=f'{invoice.vendor.legal_name} disputed {invoice.invoice_number}.')
        else:
            _notify_vendor(
                invoice, category='deadline', priority='high',
                title=f'Invoice query: {invoice.invoice_number}',
                message=f'There is a query on your invoice '
                        f'{invoice.supplier_invoice_ref or invoice.invoice_number}.')
    return invoice


def resolve_dispute(invoice, user, note=''):
    """Close out a dispute and return the invoice for re-review: disputed -> submitted."""
    with transaction.atomic():
        if not invoice.can_resolve:
            raise ValidationError('Only a disputed invoice can be resolved.')
        invoice = SupplierInvoice.all_objects.select_for_update().get(pk=invoice.pk)
        invoice.status = 'submitted'
        invoice.resolved_at = timezone.now()
        invoice.save(update_fields=['status', 'resolved_at', 'updated_at'])
        if (note or '').strip():
            InvoiceDisputeNote.all_objects.create(
                tenant=invoice.tenant, supplier_invoice=invoice, author=user,
                is_from_vendor=False, body=note.strip(),
            )
        record_invoice_event(invoice, 'submitted', user, (note or 'Dispute resolved')[:255])
        record_audit(
            invoice.tenant, user, 'supplier_invoice.dispute_resolved',
            target_type='SupplierInvoice', target_id=str(invoice.id),
            message=f'{invoice.invoice_number} dispute resolved',
        )
        _notify_vendor(
            invoice, category='info', priority='normal',
            title=f'Dispute resolved: {invoice.invoice_number}',
            message='The query on your invoice has been resolved.')
    return invoice


def reject_invoice(invoice, user, reason=''):
    """Reject an invoice (will not be paid): submitted/disputed -> rejected."""
    with transaction.atomic():
        if not invoice.can_reject:
            raise ValidationError('Only a submitted or disputed invoice can be rejected.')
        invoice = SupplierInvoice.all_objects.select_for_update().get(pk=invoice.pk)
        invoice.status = 'rejected'
        invoice.rejected_at = timezone.now()
        invoice.reject_reason = (reason or '').strip()[:255]
        invoice.save(update_fields=['status', 'rejected_at', 'reject_reason', 'updated_at'])
        record_invoice_event(invoice, 'rejected', user, invoice.reject_reason or 'Rejected')
        record_audit(
            invoice.tenant, user, 'supplier_invoice.rejected', level='warning',
            target_type='SupplierInvoice', target_id=str(invoice.id),
            message=f'{invoice.invoice_number} rejected: {invoice.reject_reason}'[:255],
        )
        _notify_vendor(
            invoice, category='info', priority='high',
            title=f'Invoice rejected: {invoice.invoice_number}',
            message=f'Your invoice {invoice.supplier_invoice_ref or invoice.invoice_number} '
                    'was rejected.')
    return invoice


def cancel_invoice(invoice, user, reason=''):
    """Cancel an invoice that has not been approved: draft/submitted/disputed -> cancelled."""
    with transaction.atomic():
        if not invoice.can_cancel:
            raise ValidationError(
                'An approved or paid invoice can no longer be cancelled.')
        invoice = SupplierInvoice.all_objects.select_for_update().get(pk=invoice.pk)
        invoice.status = 'cancelled'
        invoice.cancel_reason = (reason or '').strip()[:255]
        invoice.cancelled_at = timezone.now()
        invoice.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])
        record_invoice_event(invoice, 'cancelled', user, invoice.cancel_reason)
        record_audit(
            invoice.tenant, user, 'supplier_invoice.cancelled', level='warning',
            target_type='SupplierInvoice', target_id=str(invoice.id),
            message=f'{invoice.invoice_number} cancelled',
        )
    return invoice


# ---------------------------------------------------------------------------
# 4./5. Payment vouchers
# ---------------------------------------------------------------------------
def create_voucher(invoice, user, *, take_discount=None, payment_method='bank_transfer',
                   scheduled_date=None, notes=''):
    """Create a draft payment voucher for an approved invoice."""
    if invoice.status not in INVOICE_VOUCHERABLE_STATUSES:
        raise ValidationError('Only an approved invoice can be vouchered for payment.')
    if invoice.vouchers.exclude(status='cancelled').exists():
        raise ValidationError('A payment voucher already exists for this invoice.')

    if take_discount is None:
        take_discount = invoice.discount_is_available
    discount = (
        invoice.discount_amount
        if (take_discount and invoice.discount_amount and invoice.discount_amount > 0)
        else Decimal('0.00')
    )
    amount = (invoice.total_amount or Decimal('0')) - discount
    if amount < 0:
        amount = Decimal('0.00')

    last_exc = None
    for _attempt in range(5):
        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=invoice.tenant.pk)
                voucher = PaymentVoucher.all_objects.create(
                    tenant=invoice.tenant,
                    voucher_number=next_voucher_number(invoice.tenant),
                    supplier_invoice=invoice, vendor=invoice.vendor,
                    status='draft', currency=invoice.currency,
                    amount=amount, take_discount=bool(discount > 0),
                    discount_taken=discount, payment_method=payment_method,
                    scheduled_date=scheduled_date, notes=(notes or ''),
                    created_by=user,
                )
                record_voucher_event(voucher, 'draft', user, 'Voucher created')
                record_audit(
                    invoice.tenant, user, 'payment_voucher.created',
                    target_type='PaymentVoucher', target_id=str(voucher.id),
                    message=f'{voucher.voucher_number} for {invoice.invoice_number} '
                            f'({amount} {voucher.currency})',
                )
            return voucher
        except IntegrityError as exc:
            last_exc = exc
    raise last_exc


def approve_voucher(voucher, user, *, note=''):
    """Approve a draft voucher: draft -> approved."""
    with transaction.atomic():
        if not voucher.can_approve:
            raise ValidationError('Only a draft voucher can be approved.')
        voucher = PaymentVoucher.all_objects.select_for_update().get(pk=voucher.pk)
        voucher.status = 'approved'
        voucher.approved_at = timezone.now()
        voucher.approved_by = user
        voucher.save(update_fields=['status', 'approved_at', 'approved_by', 'updated_at'])
        record_voucher_event(voucher, 'approved', user, (note or 'Approved')[:255])
        record_audit(
            voucher.tenant, user, 'payment_voucher.approved',
            target_type='PaymentVoucher', target_id=str(voucher.id),
            message=f'{voucher.voucher_number} approved',
        )
    return voucher


def schedule_voucher(voucher, user, *, scheduled_date=None):
    """Schedule an approved voucher for a payment run: approved -> scheduled."""
    with transaction.atomic():
        if not voucher.can_schedule:
            raise ValidationError('Only an approved voucher can be scheduled.')
        voucher = PaymentVoucher.all_objects.select_for_update().get(pk=voucher.pk)
        voucher.status = 'scheduled'
        voucher.scheduled_date = scheduled_date or timezone.localdate()
        voucher.save(update_fields=['status', 'scheduled_date', 'updated_at'])
        record_voucher_event(
            voucher, 'scheduled', user, f'Scheduled for {voucher.scheduled_date}')
        record_audit(
            voucher.tenant, user, 'payment_voucher.scheduled',
            target_type='PaymentVoucher', target_id=str(voucher.id),
            message=f'{voucher.voucher_number} scheduled for {voucher.scheduled_date}',
        )
    return voucher


def pay_voucher(voucher, user, *, payment_method=None, reference=''):
    """Pay an approved/scheduled voucher through the gateway, exactly once.

    The voucher row is locked and its status re-checked INSIDE the transaction, and the
    gateway is only called after that check, so concurrent pay requests serialise: the first
    charges, the rest see ``status='paid'`` and return without charging again (mirrors
    :func:`apps.tenants.services.charge_invoice`).
    """
    gw = get_gateway()
    with transaction.atomic():
        # Lock the row FIRST, then check the precondition on the fresh status (TOCTOU-safe,
        # mirroring fulfilment's confirm_delivery / tenants.charge_invoice).
        voucher = PaymentVoucher.all_objects.select_for_update().get(pk=voucher.pk)
        if voucher.status == 'paid':
            return voucher
        if not voucher.can_pay:
            raise ValidationError('Only an approved or scheduled voucher can be paid.')
        result = gw.charge(
            amount=voucher.amount, currency=voucher.currency,
            description=f'AP payment {voucher.voucher_number} to {voucher.vendor.legal_name}',
            customer_ref=voucher.vendor.vendor_number or '',
            metadata={
                'voucher': voucher.voucher_number,
                'invoice': voucher.supplier_invoice.invoice_number,
            },
        )
        if not result.ok:
            raise ValidationError(f'Payment failed: {result.message}')
        now = timezone.now()
        voucher.status = 'paid'
        voucher.paid_at = now
        voucher.paid_by = user
        voucher.paid_date = timezone.localdate()
        voucher.gateway = gw.name
        voucher.gateway_ref = result.gateway_ref
        if payment_method:
            voucher.payment_method = payment_method
        voucher.reference = (reference or '').strip()[:120]
        voucher.save(update_fields=[
            'status', 'paid_at', 'paid_by', 'paid_date', 'gateway', 'gateway_ref',
            'payment_method', 'reference', 'updated_at',
        ])
        record_voucher_event(
            voucher, 'paid', user, f'Paid via {gw.name} ({result.gateway_ref})')

        # Flip the invoice to paid.
        inv = SupplierInvoice.all_objects.select_for_update().get(
            pk=voucher.supplier_invoice_id)
        if inv.status != 'paid':
            inv.status = 'paid'
            inv.paid_at = now
            inv.save(update_fields=['status', 'paid_at', 'updated_at'])
            record_invoice_event(
                inv, 'paid', user, f'Paid by voucher {voucher.voucher_number}')
        record_audit(
            voucher.tenant, user, 'payment_voucher.paid',
            target_type='PaymentVoucher', target_id=str(voucher.id),
            message=f'{voucher.voucher_number} paid {voucher.amount} {voucher.currency} '
                    f'to {voucher.vendor.legal_name} ({result.gateway_ref})',
        )
        _notify_vendor(
            inv, category='info', priority='normal',
            title=f'Payment sent: {inv.invoice_number}',
            message=f'A payment of {voucher.amount} {voucher.currency} has been issued for '
                    f'invoice {inv.supplier_invoice_ref or inv.invoice_number}.')
    return voucher


def cancel_voucher(voucher, user, reason=''):
    """Cancel an unpaid voucher: draft/approved/scheduled -> cancelled."""
    with transaction.atomic():
        if not voucher.can_cancel:
            raise ValidationError('A paid voucher can no longer be cancelled.')
        voucher = PaymentVoucher.all_objects.select_for_update().get(pk=voucher.pk)
        voucher.status = 'cancelled'
        voucher.cancel_reason = (reason or '').strip()[:255]
        voucher.cancelled_at = timezone.now()
        voucher.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])
        record_voucher_event(voucher, 'cancelled', user, voucher.cancel_reason)
        record_audit(
            voucher.tenant, user, 'payment_voucher.cancelled', level='warning',
            target_type='PaymentVoucher', target_id=str(voucher.id),
            message=f'{voucher.voucher_number} cancelled',
        )
    return voucher


# ---------------------------------------------------------------------------
# Alert sweep (overdue payable + closing discount window)
# ---------------------------------------------------------------------------
def scan_invoice_alerts(tenant=None, now=None):
    """Raise overdue-payment + closing-discount-window alerts. Idempotent.

    An approved/submitted invoice past its ``due_date`` and still unpaid raises a one-time
    alert (guarded by ``overdue_alerted_at``); an invoice whose early-payment discount lapses
    within ``DISCOUNT_ALERT_WINDOW_DAYS`` raises a one-time alert (guarded by
    ``discount_alerted_at``). Called by ``run_invoice_alerts`` (no ``tenant`` -> all tenants)
    and lazily by the analytics dashboard.
    """
    if tenant is None:
        totals = {'overdue': 0, 'discount': 0}
        for t in Tenant.objects.all():
            set_current_tenant(t)
            counts = scan_invoice_alerts(tenant=t, now=now)
            for k in totals:
                totals[k] += counts.get(k, 0)
        return totals

    now = now or timezone.now()
    today = timezone.localdate()
    counts = {'overdue': 0, 'discount': 0}

    overdue = SupplierInvoice.all_objects.filter(
        tenant=tenant, status__in=('submitted', 'approved'),
        due_date__lt=today, overdue_alerted_at__isnull=True,
    ).select_related('purchase_order', 'vendor')
    for inv in overdue:
        _notify_owner(
            inv, category='deadline', priority='high',
            title=f'Invoice overdue: {inv.invoice_number}',
            message=f'{inv.invoice_number} from {inv.vendor.legal_name} '
                    f'({inv.total_amount} {inv.currency}) was due on {inv.due_date}.')
        inv.overdue_alerted_at = now
        inv.save(update_fields=['overdue_alerted_at', 'updated_at'])
        record_audit(
            tenant, None, 'supplier_invoice.overdue', level='warning',
            target_type='SupplierInvoice', target_id=str(inv.id),
            message=f'{inv.invoice_number} overdue',
        )
        counts['overdue'] += 1

    cutoff = today + timedelta(days=DISCOUNT_ALERT_WINDOW_DAYS)
    closing = SupplierInvoice.all_objects.filter(
        tenant=tenant, status__in=('submitted', 'approved'),
        discount_due_date__isnull=False, discount_due_date__gte=today,
        discount_due_date__lte=cutoff, discount_amount__gt=0,
        discount_alerted_at__isnull=True,
    ).select_related('purchase_order', 'vendor')
    for inv in closing:
        _notify_owner(
            inv, category='deadline', priority='normal',
            title=f'Early-payment discount closing: {inv.invoice_number}',
            message=f'Pay {inv.invoice_number} by {inv.discount_due_date} to save '
                    f'{inv.discount_amount} {inv.currency}.')
        inv.discount_alerted_at = now
        inv.save(update_fields=['discount_alerted_at', 'updated_at'])
        counts['discount'] += 1

    return counts


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def tenant_invoice_metrics(tenant):
    """Aggregate AP KPIs for the analytics dashboard (status, aging, discounts, vouchers)."""
    qs = SupplierInvoice.objects.filter(tenant=tenant)
    by_status = dict(qs.values_list('status').annotate(n=Count('id')))
    total = qs.count()
    today = timezone.localdate()

    unpaid = qs.filter(status__in=('submitted', 'approved')).select_related('vendor')
    aging = {'current': Decimal('0.00'), 'd1_30': Decimal('0.00'),
             'd31_60': Decimal('0.00'), 'd60_plus': Decimal('0.00')}
    aging_counts = {'current': 0, 'd1_30': 0, 'd31_60': 0, 'd60_plus': 0}
    total_payable = Decimal('0.00')
    for inv in unpaid:
        amount = inv.total_amount or Decimal('0.00')
        total_payable += amount
        overdue_days = (today - inv.due_date).days if inv.due_date else 0
        if overdue_days <= 0:
            bucket = 'current'
        elif overdue_days <= 30:
            bucket = 'd1_30'
        elif overdue_days <= 60:
            bucket = 'd31_60'
        else:
            bucket = 'd60_plus'
        aging[bucket] += amount
        aging_counts[bucket] += 1

    discount_opps = list(
        unpaid.filter(discount_due_date__gte=today, discount_amount__gt=0)
        .order_by('discount_due_date')[:10]
    )
    discount_savings = sum(
        (inv.discount_amount or Decimal('0') for inv in discount_opps), Decimal('0.00'))

    voucher_qs = PaymentVoucher.objects.filter(tenant=tenant)
    paid_total = (
        voucher_qs.filter(status='paid').aggregate(s=Sum('amount'))['s'] or Decimal('0.00'))

    return {
        'total_invoices': total,
        'by_status': by_status,
        'draft': by_status.get('draft', 0),
        'submitted': by_status.get('submitted', 0),
        'approved': by_status.get('approved', 0),
        'disputed': by_status.get('disputed', 0),
        'paid': by_status.get('paid', 0),
        'rejected': by_status.get('rejected', 0),
        'cancelled': by_status.get('cancelled', 0),
        'awaiting_approval': by_status.get('submitted', 0),
        'open_disputes': by_status.get('disputed', 0),
        'match_exceptions': qs.filter(
            status='submitted', match_status='exceptions').count(),
        'total_payable': total_payable.quantize(Decimal('0.01')),
        'aging': {k: v.quantize(Decimal('0.01')) for k, v in aging.items()},
        'aging_counts': aging_counts,
        'discount_opportunities': discount_opps,
        'discount_savings': discount_savings.quantize(Decimal('0.01')),
        'discount_opportunity_count': len(discount_opps),
        'vouchers_paid': voucher_qs.filter(status='paid').count(),
        'vouchers_open': voucher_qs.filter(
            status__in=('draft', 'approved', 'scheduled')).count(),
        'total_paid': paid_total.quantize(Decimal('0.01')),
    }
