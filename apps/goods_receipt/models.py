"""Module 13: Goods Receipt & Inspection.

Closes the procure-to-pay receiving loop, sitting *after* a PO is issued (Module 11)
and the goods are shipped/advised (Module 12). Covers the five PMS sub-modules:

  1. Goods Receipt Note (GRN)        -> GoodsReceipt (+ GoodsReceiptLine): formal logging
                                        of received items against the original PO (optionally
                                        provenance-linked to a fulfilment Shipment).
  2. Quality Inspection Checklists   -> GoodsReceiptCheck (fixed pass/fail QA criteria) +
                                        per-line accepted / rejected quantities.
  3. Discrepancy Reporting           -> GoodsReceiptLine.discrepancy_type (short / over /
                                        damaged / wrong item / quality failure).
  4. Return to Vendor (RTV)          -> ReturnToVendor (+ ReturnToVendorLine): authorise and
                                        track the return of rejected items (surfaced to the
                                        supplier in the vendor portal).
  5. Item Tagging & Barcoding        -> ReceiptTag: an internal barcode/QR code generated for
                                        each accepted line, printed on a label sheet.

The accepted quantity is posted back to Module 11's ``record_line_receipt`` (see services),
which already guards against over-receipt — so a GRN can never double-count with the
fulfilment module's delivery confirmation. Mirrors the Module 11/12 conventions:
TenantAwareModel + TimeStampedModel bases, module-level status constants + EDITABLE/OPEN/
FINISHED tuples, gap-free GRN-<SLUG>-NNNNN numbering (in services.py), and append-only
timeline models.

Decimal convention: all quantities use 2 dp (the project money/quantity pattern,
matching purchase orders and fulfilment).
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Choice constants (module-level, mirroring purchase_orders / fulfillment)
# ---------------------------------------------------------------------------
GRN_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('received', 'Received'),
    ('under_inspection', 'Under inspection'),
    ('inspected', 'Inspected'),
    ('posted', 'Posted'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]
GRN_EDITABLE_STATUSES = ('draft',)
GRN_RECEIVABLE_STATUSES = ('draft',)
GRN_INSPECTABLE_STATUSES = ('received', 'under_inspection')
GRN_POSTABLE_STATUSES = ('inspected',)
GRN_CLOSEABLE_STATUSES = ('posted',)
# Cancellable up to (but NOT including) posted — a posting has already fed the PO and
# cannot be silently reversed (that is the RTV flow).
GRN_CANCELLABLE_STATUSES = ('draft', 'received', 'under_inspection', 'inspected')
GRN_OPEN_STATUSES = ('draft', 'received', 'under_inspection', 'inspected')
GRN_FINISHED_STATUSES = ('posted', 'closed', 'cancelled')

INSPECTION_RESULT_CHOICES = [
    ('pass', 'Pass'),
    ('fail', 'Fail'),
    ('partial', 'Partial'),
]

GRN_LINE_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('received', 'Received'),
    ('inspected', 'Inspected'),
    ('accepted', 'Accepted'),
    ('rejected', 'Rejected'),
    ('partial', 'Partially accepted'),
]

DISCREPANCY_CHOICES = [
    ('none', 'None'),
    ('short', 'Short / under-delivered'),
    ('over', 'Over-delivered'),
    ('damaged', 'Damaged'),
    ('wrong_item', 'Wrong item'),
    ('quality', 'Quality failure'),
]

CHECK_RESULT_CHOICES = [
    ('pass', 'Pass'),
    ('fail', 'Fail'),
    ('na', 'N/A'),
]
# The fixed QA inspection checklist applied to every GRN.
GRN_QA_CRITERIA = [
    ('packaging_intact', 'Packaging intact'),
    ('quantity_matches', 'Quantity matches documents'),
    ('no_damage', 'No visible damage'),
    ('labelling_correct', 'Labelling correct'),
    ('documentation_present', 'Documentation present'),
]

RTV_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('authorized', 'Authorized'),
    ('shipped', 'Shipped'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]
RTV_EDITABLE_STATUSES = ('draft',)
RTV_AUTHORIZABLE_STATUSES = ('draft',)
RTV_SHIPPABLE_STATUSES = ('authorized',)
RTV_CLOSEABLE_STATUSES = ('shipped',)
RTV_CANCELLABLE_STATUSES = ('draft', 'authorized')
RTV_OPEN_STATUSES = ('draft', 'authorized', 'shipped')
RTV_FINISHED_STATUSES = ('closed', 'cancelled')
# Statuses a supplier may see in their portal (a draft is never exposed).
RTV_VENDOR_VISIBLE_STATUSES = ('authorized', 'shipped', 'closed')


def _qty_field(**kwargs):
    return models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))], **kwargs,
    )


# ---------- 1. The Goods Receipt Note (GRN) header ----------

class GoodsReceipt(TenantAwareModel, TimeStampedModel):
    """A formal record of goods received against a purchase order (the GRN header)."""

    STATUS_CHOICES = GRN_STATUS_CHOICES
    INSPECTION_RESULT_CHOICES = INSPECTION_RESULT_CHOICES

    grn_number = models.CharField(max_length=40)

    # PROTECT: a GRN is evidence of receipt against a financial commitment — the PO
    # (and supplier) behind it must not be silently deleted.
    purchase_order = models.ForeignKey(
        'purchase_orders.PurchaseOrder', on_delete=models.PROTECT,
        related_name='goods_receipts',
        help_text='The purchase order these goods were received against.',
    )
    # Optional provenance link to the fulfilment shipment (reverse-only — no Module 12
    # change). SET_NULL so cancelling/removing a shipment never erases the receipt.
    shipment = models.ForeignKey(
        'fulfillment.Shipment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_receipts',
        help_text='The shipment/ASN this receipt was booked from (optional).',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.PROTECT, related_name='goods_receipts',
        help_text='The supplier (denormalised from the PO for filtering).',
    )

    status = models.CharField(
        max_length=20, choices=GRN_STATUS_CHOICES, default='draft',
    )

    # 1. Receiving details
    received_date = models.DateField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_receipts_received',
    )
    delivery_note_ref = models.CharField(max_length=80, blank=True)
    warehouse_location = models.CharField(max_length=120, blank=True)
    carrier_note = models.CharField(max_length=255, blank=True)

    # 2. Inspection outcome
    inspected_at = models.DateTimeField(null=True, blank=True)
    inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_receipts_inspected',
    )
    inspection_result = models.CharField(
        max_length=10, choices=INSPECTION_RESULT_CHOICES, blank=True,
    )
    inspection_note = models.CharField(max_length=255, blank=True)

    # 3. Posting (accepted qty fed to the PO lines)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_receipts_posted',
    )

    # Lifecycle bookkeeping
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_receipts_created',
    )
    cancel_reason = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Alert idempotency guard (used by scan_goods_receipt_alerts)
    inspection_alerted_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the overdue-inspection alert was raised.',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'grn_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'vendor']),
            models.Index(fields=['tenant', 'purchase_order']),
            models.Index(fields=['tenant', 'received_date']),
        ]

    def __str__(self):
        return f'{self.grn_number} — {self.purchase_order.po_number}'

    # --- status helpers ---
    @property
    def is_editable(self):
        return self.status in GRN_EDITABLE_STATUSES

    @property
    def can_receive(self):
        return self.status in GRN_RECEIVABLE_STATUSES

    @property
    def can_inspect(self):
        return self.status in GRN_INSPECTABLE_STATUSES

    @property
    def can_post(self):
        return self.status in GRN_POSTABLE_STATUSES

    @property
    def can_close(self):
        return self.status in GRN_CLOSEABLE_STATUSES

    @property
    def can_cancel(self):
        return self.status in GRN_CANCELLABLE_STATUSES

    @property
    def is_open(self):
        return self.status in GRN_OPEN_STATUSES

    @property
    def is_finished(self):
        return self.status in GRN_FINISHED_STATUSES

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
    def total_received_qty(self):
        return self._sum('received_quantity')

    @property
    def total_accepted_qty(self):
        return self._sum('accepted_quantity')

    @property
    def total_rejected_qty(self):
        return self._sum('rejected_quantity')

    @property
    def has_rejections(self):
        return any((ln.rejected_quantity or Decimal('0')) > 0 for ln in self.lines.all())

    @property
    def qa_passed(self):
        """True if no QA checklist criterion failed."""
        return not self.checks.filter(result='fail').exists()


# ---------- 1. GRN line items ----------

class GoodsReceiptLine(TenantAwareModel, TimeStampedModel):
    """A single received item on a GRN — received, then inspected into accepted/rejected."""

    LINE_STATUS_CHOICES = GRN_LINE_STATUS_CHOICES
    DISCREPANCY_CHOICES = DISCREPANCY_CHOICES

    goods_receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.CASCADE, related_name='lines',
    )
    purchase_order_line = models.ForeignKey(
        'purchase_orders.PurchaseOrderLine', on_delete=models.PROTECT,
        related_name='goods_receipt_lines',
    )
    shipment_line = models.ForeignKey(
        'fulfillment.ShipmentLine', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_receipt_lines',
    )
    line_no = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=255, blank=True)
    uom = models.CharField(max_length=30, default='unit')

    received_quantity = _qty_field(help_text='Quantity physically received on this GRN.')
    accepted_quantity = _qty_field(help_text='Quantity that passed inspection.')
    rejected_quantity = _qty_field(help_text='Quantity that failed inspection (-> RTV).')
    posted_quantity = _qty_field(
        help_text='Accepted qty already posted to the PO line — the idempotency '
                  'watermark so re-posting a GRN never double-counts.',
    )

    discrepancy_type = models.CharField(
        max_length=12, choices=DISCREPANCY_CHOICES, default='none',
    )
    rejection_reason = models.CharField(max_length=255, blank=True)
    line_status = models.CharField(
        max_length=12, choices=GRN_LINE_STATUS_CHOICES, default='pending',
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['line_no', 'id']
        unique_together = [('goods_receipt', 'line_no')]

    def __str__(self):
        return f'{self.description or self.purchase_order_line_id} x{self.received_quantity}'

    @property
    def outstanding_inspection(self):
        """Received but not yet decided (accepted or rejected)."""
        return (
            (self.received_quantity or Decimal('0'))
            - (self.accepted_quantity or Decimal('0'))
            - (self.rejected_quantity or Decimal('0'))
        )

    @property
    def unposted_quantity(self):
        """Accepted but not yet posted to the PO line."""
        return (self.accepted_quantity or Decimal('0')) - (self.posted_quantity or Decimal('0'))

    @property
    def is_fully_inspected(self):
        return self.outstanding_inspection <= 0


# ---------- 2. Quality inspection checklist ----------

class GoodsReceiptCheck(TenantAwareModel, TimeStampedModel):
    """A single pass/fail QA criterion result for a GRN (one row per criterion)."""

    RESULT_CHOICES = CHECK_RESULT_CHOICES
    CRITERIA = GRN_QA_CRITERIA

    goods_receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.CASCADE, related_name='checks',
    )
    criterion = models.CharField(max_length=40, choices=GRN_QA_CRITERIA)
    result = models.CharField(max_length=4, choices=CHECK_RESULT_CHOICES, default='pass')
    note = models.CharField(max_length=255, blank=True)
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grn_checks',
    )

    class Meta:
        ordering = ['id']
        unique_together = [('goods_receipt', 'criterion')]

    def __str__(self):
        return f'{self.get_criterion_display()}: {self.result}'


# ---------- Append-only lifecycle timeline ----------

class GoodsReceiptStatusEvent(TenantAwareModel, TimeStampedModel):
    """An append-only record of every GRN status transition."""

    goods_receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.CASCADE, related_name='status_events',
    )
    status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grn_status_events',
    )

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.goods_receipt.grn_number} → {self.status}'


# ---------- 4. Return to Vendor (RTV) ----------

class ReturnToVendor(TenantAwareModel, TimeStampedModel):
    """An authorised return of rejected goods to the supplier (the RTV header)."""

    STATUS_CHOICES = RTV_STATUS_CHOICES

    rtv_number = models.CharField(max_length=40)
    goods_receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.PROTECT, related_name='returns',
    )
    purchase_order = models.ForeignKey(
        'purchase_orders.PurchaseOrder', on_delete=models.PROTECT,
        related_name='returns_to_vendor',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.PROTECT, related_name='returns_to_vendor',
    )

    status = models.CharField(
        max_length=12, choices=RTV_STATUS_CHOICES, default='draft',
    )
    reason = models.TextField(blank=True)
    rma_number = models.CharField(
        max_length=80, blank=True, help_text='Supplier return-merchandise authorisation #.',
    )

    authorized_at = models.DateTimeField(null=True, blank=True)
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rtvs_authorized',
    )
    shipped_at = models.DateTimeField(null=True, blank=True)
    shipped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rtvs_shipped',
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    carrier = models.CharField(max_length=120, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)

    # Vendor-portal acknowledgement
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledgement_note = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rtvs_created',
    )
    alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'rtv_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'vendor']),
        ]

    def __str__(self):
        return f'{self.rtv_number} — {self.vendor.legal_name}'

    @property
    def is_editable(self):
        return self.status in RTV_EDITABLE_STATUSES

    @property
    def can_authorize(self):
        return self.status in RTV_AUTHORIZABLE_STATUSES

    @property
    def can_ship(self):
        return self.status in RTV_SHIPPABLE_STATUSES

    @property
    def can_close(self):
        return self.status in RTV_CLOSEABLE_STATUSES

    @property
    def can_cancel(self):
        return self.status in RTV_CANCELLABLE_STATUSES

    @property
    def is_open(self):
        return self.status in RTV_OPEN_STATUSES

    @property
    def is_finished(self):
        return self.status in RTV_FINISHED_STATUSES

    @property
    def line_count(self):
        return self.lines.count()

    @property
    def total_quantity(self):
        return sum(
            (ln.quantity or Decimal('0') for ln in self.lines.all()),
            Decimal('0.00'),
        )


class ReturnToVendorLine(TenantAwareModel, TimeStampedModel):
    """A single rejected line being returned to the supplier."""

    rtv = models.ForeignKey(
        ReturnToVendor, on_delete=models.CASCADE, related_name='lines',
    )
    goods_receipt_line = models.ForeignKey(
        GoodsReceiptLine, on_delete=models.PROTECT, related_name='rtv_lines',
    )
    line_no = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=255, blank=True)
    uom = models.CharField(max_length=30, default='unit')
    quantity = _qty_field()
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['line_no', 'id']
        unique_together = [('rtv', 'line_no')]

    def __str__(self):
        return f'{self.description or self.goods_receipt_line_id} x{self.quantity}'


# ---------- 5. Item tagging & barcoding ----------

class ReceiptTag(TenantAwareModel, TimeStampedModel):
    """An internal barcode/QR tag generated for an accepted GRN line."""

    goods_receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.CASCADE, related_name='tags',
    )
    goods_receipt_line = models.ForeignKey(
        GoodsReceiptLine, on_delete=models.CASCADE, related_name='tags',
    )
    code = models.CharField(max_length=80)
    quantity = _qty_field()
    uom = models.CharField(max_length=30, default='unit')
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='receipt_tags',
    )

    class Meta:
        ordering = ['code']
        unique_together = [('tenant', 'code')]
        indexes = [
            models.Index(fields=['tenant', 'goods_receipt']),
        ]

    def __str__(self):
        return self.code
