"""Module 14: Invoice & Voucher Management (Accounts Payable).

Closes the procure-to-pay loop: it sits *after* Module 13 (Goods Receipt) — once goods
are received and accepted, the supplier's invoice is captured, matched against the PO and
the GRN, approved, and paid via a payment voucher. Covers the five PMS sub-modules:

  1. Invoice Capture (OCR)      -> SupplierInvoice.source_file + a pluggable OCR engine
                                   (see ocr.py) that extracts the header + lines into a draft.
  2. Three-Way Matching         -> run_three_way_match (services): each SupplierInvoiceLine is
                                   matched against its PurchaseOrderLine (ordered qty/price) and
                                   the accepted qty from the Goods Receipt — variances flagged.
  3. Dispute Resolution         -> InvoiceDisputeNote (append-only buyer<->supplier thread) +
                                   the ``disputed`` status, surfaced in the vendor portal.
  4. Payment Schedule / Terms   -> PaymentTerm (net-30/60 + early-payment discount) drives the
                                   due date / discount date; PaymentVoucher authorises + schedules.
  5. Early Payment Discount     -> the analytics dashboard surfaces invoices inside their discount
                                   window with the capturable savings (+ AP aging buckets).

IMPORTANT — naming: ``apps.tenants.Invoice`` already exists and is the *SaaS subscription*
invoice (the tenant pays the NavPMS platform). This module's invoice is the opposite
direction (the tenant pays its *suppliers*), so the model is ``SupplierInvoice`` with its own
``SINV-<SLUG>-NNNNN`` numbering — there is no collision.

Design: the invoice is READ-ONLY against the PO and GRN. The GRN already posted the accepted
quantity into ``PurchaseOrderLine.received_quantity`` (Module 13); the invoice never re-posts
to the PO (that would double-count). Over-billing is guarded by summing already-invoiced qty
*within this app* (see services.run_three_way_match). Mirrors the Module 11/12/13 conventions:
TenantAwareModel + TimeStampedModel bases, module-level status constants, gap-free numbering
(in services.py), and append-only timeline models.

Decimal convention: money fields use 14,2 (matching the PO header); quantities use 12,2.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Choice constants (module-level, mirroring purchase_orders / goods_receipt)
# ---------------------------------------------------------------------------
INVOICE_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('submitted', 'Submitted'),
    ('approved', 'Approved'),
    ('disputed', 'Disputed'),
    ('paid', 'Paid'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled'),
]
INVOICE_EDITABLE_STATUSES = ('draft',)
INVOICE_SUBMITTABLE_STATUSES = ('draft',)
INVOICE_APPROVABLE_STATUSES = ('submitted',)
INVOICE_DISPUTABLE_STATUSES = ('submitted',)
INVOICE_RESOLVABLE_STATUSES = ('disputed',)
INVOICE_REJECTABLE_STATUSES = ('submitted', 'disputed')
# Cancellable up to (but NOT including) approved — once approved a voucher may exist.
INVOICE_CANCELLABLE_STATUSES = ('draft', 'submitted', 'disputed')
INVOICE_VOUCHERABLE_STATUSES = ('approved',)
INVOICE_OPEN_STATUSES = ('draft', 'submitted', 'disputed', 'approved')
INVOICE_FINISHED_STATUSES = ('paid', 'rejected', 'cancelled')
# Statuses a supplier may see in their portal (a draft entered internally is never exposed).
INVOICE_VENDOR_VISIBLE_STATUSES = (
    'submitted', 'approved', 'disputed', 'paid', 'rejected',
)

INVOICE_MATCH_STATUS_CHOICES = [
    ('unmatched', 'Not matched'),
    ('matched', 'Matched'),
    ('exceptions', 'Exceptions'),
]

# Per-line three-way-match outcome.
LINE_MATCH_STATUS_CHOICES = [
    ('pending', 'Not matched'),
    ('matched', 'Matched'),
    ('qty_variance', 'Quantity variance'),
    ('price_variance', 'Price variance'),
    ('over_billed', 'Over-billed'),
    ('no_receipt', 'Not yet received'),
    ('no_po', 'No PO line'),
]
LINE_EXCEPTION_STATUSES = (
    'qty_variance', 'price_variance', 'over_billed', 'no_receipt', 'no_po',
)

VOUCHER_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('approved', 'Approved'),
    ('scheduled', 'Scheduled'),
    ('paid', 'Paid'),
    ('cancelled', 'Cancelled'),
]
VOUCHER_EDITABLE_STATUSES = ('draft',)
VOUCHER_APPROVABLE_STATUSES = ('draft',)
VOUCHER_SCHEDULABLE_STATUSES = ('approved',)
VOUCHER_PAYABLE_STATUSES = ('approved', 'scheduled')
VOUCHER_CANCELLABLE_STATUSES = ('draft', 'approved', 'scheduled')
VOUCHER_OPEN_STATUSES = ('draft', 'approved', 'scheduled')
VOUCHER_FINISHED_STATUSES = ('paid', 'cancelled')

PAYMENT_METHOD_CHOICES = [
    ('bank_transfer', 'Bank transfer'),
    ('card', 'Card'),
    ('cheque', 'Cheque'),
    ('cash', 'Cash'),
    ('other', 'Other'),
]


def _money_field(**kwargs):
    kwargs.setdefault('default', Decimal('0.00'))
    return models.DecimalField(
        max_digits=14, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))], **kwargs,
    )


def _qty_field(**kwargs):
    kwargs.setdefault('default', Decimal('0.00'))
    return models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))], **kwargs,
    )


def _signed_field(**kwargs):
    """A money/qty field that may legitimately be negative (a variance)."""
    kwargs.setdefault('default', Decimal('0.00'))
    return models.DecimalField(max_digits=14, decimal_places=2, **kwargs)


# ---------------------------------------------------------------------------
# 4. Payment terms master (net-30/60 + early-payment discount)
# ---------------------------------------------------------------------------
class PaymentTerm(TenantAwareModel, TimeStampedModel):
    """A reusable payment term, e.g. *Net 30* or *2/10 Net 30* (2% off if paid in 10 days)."""

    code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    net_days = models.PositiveIntegerField(
        default=30, help_text='Days from the invoice date until payment is due.',
    )
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Early-payment discount percentage (0 = none).',
    )
    discount_days = models.PositiveIntegerField(
        default=0, help_text='Pay within this many days to take the discount.',
    )
    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['code']
        unique_together = [('tenant', 'code')]

    def __str__(self):
        return f'{self.code} — {self.name}'

    @property
    def has_discount(self):
        return self.discount_percent and self.discount_percent > 0 and self.discount_days > 0

    def due_date_for(self, invoice_date):
        """The payment due date for an invoice issued on ``invoice_date``."""
        from datetime import timedelta
        if not invoice_date:
            return None
        return invoice_date + timedelta(days=self.net_days or 0)

    def discount_date_for(self, invoice_date):
        """The last date the early-payment discount may be taken (or None)."""
        from datetime import timedelta
        if not invoice_date or not self.has_discount:
            return None
        return invoice_date + timedelta(days=self.discount_days or 0)


# ---------------------------------------------------------------------------
# 1./2./3. The supplier (accounts-payable) invoice header
# ---------------------------------------------------------------------------
class SupplierInvoice(TenantAwareModel, TimeStampedModel):
    """A supplier's invoice captured for matching, approval and payment (the AP header)."""

    STATUS_CHOICES = INVOICE_STATUS_CHOICES
    MATCH_STATUS_CHOICES = INVOICE_MATCH_STATUS_CHOICES

    invoice_number = models.CharField(
        max_length=40, help_text='Internal control number (SINV-<SLUG>-NNNNN).',
    )
    supplier_invoice_ref = models.CharField(
        max_length=80, blank=True, help_text="The supplier's own invoice number.",
    )

    # PROTECT: an invoice is a financial obligation — the supplier behind it must not be
    # silently deleted.
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.PROTECT, related_name='supplier_invoices',
    )
    # Nullable: most invoices reference a PO (for three-way matching), but a non-PO invoice
    # (e.g. a utility bill) is allowed.
    purchase_order = models.ForeignKey(
        'purchase_orders.PurchaseOrder', on_delete=models.PROTECT,
        null=True, blank=True, related_name='supplier_invoices',
        help_text='The PO this invoice bills against (for three-way matching).',
    )
    # Optional provenance link to the goods receipt the invoice was matched from.
    goods_receipt = models.ForeignKey(
        'goods_receipt.GoodsReceipt', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_invoices',
    )
    payment_term = models.ForeignKey(
        PaymentTerm, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_invoices',
    )

    status = models.CharField(
        max_length=12, choices=INVOICE_STATUS_CHOICES, default='draft',
    )
    match_status = models.CharField(
        max_length=12, choices=INVOICE_MATCH_STATUS_CHOICES, default='unmatched',
    )

    # Dates
    invoice_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(
        null=True, blank=True, help_text='Date the invoice arrived / was captured.',
    )
    due_date = models.DateField(null=True, blank=True)
    discount_due_date = models.DateField(null=True, blank=True)

    # Money (mirrors the PO header)
    currency = models.CharField(max_length=3, default='USD')
    subtotal = _money_field()
    tax_amount = _money_field()
    shipping_amount = _money_field()
    total_amount = _money_field()
    discount_amount = _money_field(
        help_text='Early-payment discount available on this invoice (per the payment term).',
    )

    # 1. Invoice capture (OCR)
    source_file = models.FileField(upload_to='invoice_docs/', null=True, blank=True)
    ocr_engine = models.CharField(max_length=40, blank=True)
    ocr_confidence = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='OCR extraction confidence (0-100); blank for manual entry.',
    )
    ocr_raw = models.JSONField(default=dict, blank=True)

    notes = models.TextField(blank=True)
    submitted_via_portal = models.BooleanField(
        default=False, help_text='True if the supplier submitted this through the portal.',
    )

    # Lifecycle bookkeeping
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_invoices_created',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_invoices_submitted',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_invoices_approved',
    )
    match_override = models.BooleanField(
        default=False, help_text='True if approved despite three-way-match exceptions.',
    )

    # 3. Dispute
    disputed_at = models.DateTimeField(null=True, blank=True)
    disputed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_invoices_disputed',
    )
    dispute_reason = models.CharField(max_length=255, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    paid_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    # Alert idempotency guards (used by scan_invoice_alerts)
    overdue_alerted_at = models.DateTimeField(null=True, blank=True)
    discount_alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'invoice_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'match_status']),
            models.Index(fields=['tenant', 'vendor']),
            models.Index(fields=['tenant', 'purchase_order']),
            models.Index(fields=['tenant', 'due_date']),
        ]

    def __str__(self):
        return f'{self.invoice_number} — {self.vendor.legal_name}'

    # --- status helpers ---
    @property
    def is_editable(self):
        return self.status in INVOICE_EDITABLE_STATUSES

    @property
    def can_submit(self):
        return self.status in INVOICE_SUBMITTABLE_STATUSES

    @property
    def can_approve(self):
        return self.status in INVOICE_APPROVABLE_STATUSES

    @property
    def can_dispute(self):
        return self.status in INVOICE_DISPUTABLE_STATUSES

    @property
    def can_resolve(self):
        return self.status in INVOICE_RESOLVABLE_STATUSES

    @property
    def can_reject(self):
        return self.status in INVOICE_REJECTABLE_STATUSES

    @property
    def can_cancel(self):
        return self.status in INVOICE_CANCELLABLE_STATUSES

    @property
    def is_open(self):
        return self.status in INVOICE_OPEN_STATUSES

    @property
    def is_finished(self):
        return self.status in INVOICE_FINISHED_STATUSES

    @property
    def is_matched(self):
        return self.match_status == 'matched'

    @property
    def has_exceptions(self):
        return self.match_status == 'exceptions'

    @property
    def can_create_voucher(self):
        """Approved, no active voucher yet."""
        if self.status not in INVOICE_VOUCHERABLE_STATUSES:
            return False
        return not self.vouchers.exclude(status='cancelled').exists()

    # --- line roll-ups ---
    @property
    def line_count(self):
        return self.lines.count()

    def _sum(self, attr):
        return sum(
            (getattr(ln, attr) or Decimal('0') for ln in self.lines.all()),
            Decimal('0.00'),
        )

    @property
    def computed_subtotal(self):
        return self._sum('line_total')

    @property
    def computed_tax(self):
        return self._sum('tax_amount')

    @property
    def exception_line_count(self):
        return sum(1 for ln in self.lines.all() if ln.is_exception)

    # --- payment / discount helpers ---
    @property
    def net_payable(self):
        """Total minus any discount currently being taken is handled on the voucher;
        this is the gross amount owed."""
        return self.total_amount or Decimal('0.00')

    @property
    def days_until_due(self):
        if not self.due_date:
            return None
        from django.utils import timezone
        return (self.due_date - timezone.localdate()).days

    @property
    def is_overdue(self):
        days = self.days_until_due
        return days is not None and days < 0 and self.status in ('submitted', 'approved')

    @property
    def discount_is_available(self):
        """True if the early-payment discount window is still open today."""
        if not self.discount_due_date or not self.discount_amount or self.discount_amount <= 0:
            return False
        if self.status not in ('submitted', 'approved'):
            return False
        from django.utils import timezone
        return timezone.localdate() <= self.discount_due_date

    @property
    def days_until_discount(self):
        if not self.discount_due_date:
            return None
        from django.utils import timezone
        return (self.discount_due_date - timezone.localdate()).days


# ---------------------------------------------------------------------------
# 1./2. Invoice line items
# ---------------------------------------------------------------------------
class SupplierInvoiceLine(TenantAwareModel, TimeStampedModel):
    """A single billed line on a supplier invoice, matched against PO + GRN."""

    MATCH_STATUS_CHOICES = LINE_MATCH_STATUS_CHOICES

    supplier_invoice = models.ForeignKey(
        SupplierInvoice, on_delete=models.CASCADE, related_name='lines',
    )
    # Nullable: a line may not map to a PO line (off-PO charge) — then it is an exception.
    purchase_order_line = models.ForeignKey(
        'purchase_orders.PurchaseOrderLine', on_delete=models.PROTECT,
        null=True, blank=True, related_name='supplier_invoice_lines',
    )
    goods_receipt_line = models.ForeignKey(
        'goods_receipt.GoodsReceiptLine', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_invoice_lines',
    )
    account_code = models.ForeignKey(
        'requisitions.AccountCode', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_invoice_lines',
    )
    line_no = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=255, blank=True)
    uom = models.CharField(max_length=30, default='unit')

    quantity = _qty_field(default=Decimal('1.00'))
    unit_price = _money_field()
    line_total = _money_field()
    tax_amount = _money_field()

    # Three-way-match outputs (computed by services.run_three_way_match)
    match_status = models.CharField(
        max_length=14, choices=LINE_MATCH_STATUS_CHOICES, default='pending',
    )
    matched_po_qty = _qty_field(help_text='Ordered qty on the matched PO line.')
    matched_received_qty = _qty_field(
        help_text='Qty received & accepted against the PO line (via the GRN or the '
                  'fulfilment delivery confirmation — both post only accepted qty).')
    qty_variance = _signed_field(help_text='Invoiced qty − received (accepted) qty.')
    price_variance = _signed_field(help_text='Invoiced unit price − PO unit price.')
    match_note = models.CharField(max_length=255, blank=True)

    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['line_no', 'id']
        unique_together = [('supplier_invoice', 'line_no')]

    def __str__(self):
        return f'{self.description or self.purchase_order_line_id} x{self.quantity}'

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))
        super().save(*args, **kwargs)

    @property
    def is_exception(self):
        return self.match_status in LINE_EXCEPTION_STATUSES

    @property
    def gross_total(self):
        return (self.line_total or Decimal('0')) + (self.tax_amount or Decimal('0'))


# ---------------------------------------------------------------------------
# Append-only lifecycle timeline
# ---------------------------------------------------------------------------
class SupplierInvoiceStatusEvent(TenantAwareModel, TimeStampedModel):
    """An append-only record of every supplier-invoice status transition."""

    supplier_invoice = models.ForeignKey(
        SupplierInvoice, on_delete=models.CASCADE, related_name='status_events',
    )
    status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='supplier_invoice_status_events',
    )

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.supplier_invoice.invoice_number} → {self.status}'


# ---------------------------------------------------------------------------
# 3. Dispute resolution thread (append-only)
# ---------------------------------------------------------------------------
class InvoiceDisputeNote(TenantAwareModel, TimeStampedModel):
    """A single message in the buyer<->supplier dispute thread for an invoice."""

    supplier_invoice = models.ForeignKey(
        SupplierInvoice, on_delete=models.CASCADE, related_name='dispute_notes',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoice_dispute_notes',
    )
    is_from_vendor = models.BooleanField(default=False)
    body = models.TextField()

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        who = 'supplier' if self.is_from_vendor else 'buyer'
        return f'{self.supplier_invoice.invoice_number} note ({who})'


# ---------------------------------------------------------------------------
# 4./5. Payment voucher (authorises + schedules + pays an approved invoice)
# ---------------------------------------------------------------------------
class PaymentVoucher(TenantAwareModel, TimeStampedModel):
    """A payment authorisation for an approved supplier invoice (the voucher header)."""

    STATUS_CHOICES = VOUCHER_STATUS_CHOICES

    voucher_number = models.CharField(max_length=40)
    # PROTECT: a paid voucher is a financial record; the invoice it paid must not vanish.
    supplier_invoice = models.ForeignKey(
        SupplierInvoice, on_delete=models.PROTECT, related_name='vouchers',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.PROTECT, related_name='payment_vouchers',
        help_text='The supplier being paid (denormalised from the invoice).',
    )

    status = models.CharField(
        max_length=12, choices=VOUCHER_STATUS_CHOICES, default='draft',
    )
    currency = models.CharField(max_length=3, default='USD')
    amount = _money_field(help_text='The amount to disburse (net of any discount taken).')
    take_discount = models.BooleanField(default=False)
    discount_taken = _money_field()

    payment_method = models.CharField(
        max_length=16, choices=PAYMENT_METHOD_CHOICES, default='bank_transfer',
    )
    scheduled_date = models.DateField(null=True, blank=True)
    paid_date = models.DateField(null=True, blank=True)
    reference = models.CharField(
        max_length=120, blank=True, help_text='Cheque no. / remittance reference.',
    )
    gateway = models.CharField(max_length=40, blank=True)
    gateway_ref = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payment_vouchers_created',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payment_vouchers_approved',
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payment_vouchers_paid',
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'voucher_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'vendor']),
            models.Index(fields=['tenant', 'scheduled_date']),
        ]

    def __str__(self):
        return f'{self.voucher_number} — {self.vendor.legal_name}'

    @property
    def is_editable(self):
        return self.status in VOUCHER_EDITABLE_STATUSES

    @property
    def can_approve(self):
        return self.status in VOUCHER_APPROVABLE_STATUSES

    @property
    def can_schedule(self):
        return self.status in VOUCHER_SCHEDULABLE_STATUSES

    @property
    def can_pay(self):
        return self.status in VOUCHER_PAYABLE_STATUSES

    @property
    def can_cancel(self):
        return self.status in VOUCHER_CANCELLABLE_STATUSES

    @property
    def is_open(self):
        return self.status in VOUCHER_OPEN_STATUSES

    @property
    def is_finished(self):
        return self.status in VOUCHER_FINISHED_STATUSES


class PaymentVoucherStatusEvent(TenantAwareModel, TimeStampedModel):
    """An append-only record of every payment-voucher status transition."""

    payment_voucher = models.ForeignKey(
        PaymentVoucher, on_delete=models.CASCADE, related_name='status_events',
    )
    status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payment_voucher_status_events',
    )

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.payment_voucher.voucher_number} → {self.status}'
