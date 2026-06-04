"""Module 12: Order Fulfillment & Tracking.

Covers the five PMS sub-modules, sitting in the P2P cycle *after* a PO is issued
(Module 11) and *before* the future Goods Receipt & Inspection (Module 13):

  1. Advanced Shipping Notice (ASN) -> Shipment (+ ShipmentLine) advised by the
                                       supplier from the vendor portal with packing details
  2. Real-time Freight Tracking     -> ShipmentTrackingEvent (append-only carrier ledger);
                                       a pluggable carrier connector (see carriers.py)
  3. Delivery Confirmation          -> Shipment.delivered_at / actual_delivery_date +
                                       received_condition; confirming a delivery posts the
                                       received quantities into the PO lines
  4. Backorder Management           -> Backorder (out-of-stock / undelivered remainder with
                                       an expected fulfilment date)
  5. Split Delivery Management      -> many Shipments per PurchaseOrder; per-line shipped
                                       quantity is guarded against over-shipping

A shipment is created/advised against an issued PO (one PO may be split across several),
tracked through the carrier, then confirmed delivered — which feeds the received quantities
back into Module 11's ``record_line_receipt`` so the PO rolls up to partially_received /
received. Mirrors the Module 11 (Purchase Orders) conventions: TenantAwareModel +
TimeStampedModel bases, module-level status constants + EDITABLE/OPEN/FINISHED tuples,
gap-free SHP-<SLUG>-NNNNN numbering (in services.py), and append-only timeline models.

Decimal convention: quantities, weights and freight money use 2 dp (the project money
pattern, matching purchase orders — the fulfilment source).
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Choice constants (module-level, mirroring the purchase_orders module)
# ---------------------------------------------------------------------------
SHIPMENT_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('advised', 'Advised (ASN sent)'),
    ('in_transit', 'In transit'),
    ('out_for_delivery', 'Out for delivery'),
    ('delivered', 'Delivered'),
    ('received', 'Received'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
    ('exception', 'Exception'),
]
SHIPMENT_EDITABLE_STATUSES = ('draft',)
SHIPMENT_ADVISABLE_STATUSES = ('draft',)
# Statuses where the shipment is in motion (carrier tracking is meaningful).
SHIPMENT_TRACKABLE_STATUSES = ('advised', 'in_transit', 'out_for_delivery')
SHIPMENT_CONFIRMABLE_STATUSES = ('advised', 'in_transit', 'out_for_delivery', 'delivered')
# Cancellable up to (but NOT including) delivered/received — a confirmed receipt has
# already posted to the PO and cannot be reversed here (that is Module 13's RTV flow).
SHIPMENT_CANCELLABLE_STATUSES = (
    'draft', 'advised', 'in_transit', 'out_for_delivery', 'exception',
)
SHIPMENT_CLOSEABLE_STATUSES = ('delivered', 'received')
SHIPMENT_OPEN_STATUSES = (
    'draft', 'advised', 'in_transit', 'out_for_delivery', 'delivered', 'exception',
)
SHIPMENT_FINISHED_STATUSES = ('received', 'closed', 'cancelled')

WEIGHT_UOM_CHOICES = [('kg', 'kg'), ('lb', 'lb')]

RECEIVED_CONDITION_CHOICES = [
    ('good', 'Good'),
    ('damaged', 'Damaged'),
    ('partial', 'Partial / short'),
    ('rejected', 'Rejected'),
]

SHIPMENT_LINE_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('shipped', 'Shipped'),
    ('received', 'Received'),
    ('short', 'Short / backordered'),
]

TRACKING_SOURCE_CHOICES = [
    ('manual', 'Manual entry'),
    ('carrier', 'Carrier API'),
    ('webhook', 'Carrier webhook'),
]

BACKORDER_STATUS_CHOICES = [
    ('open', 'Open'),
    ('promised', 'Promised'),
    ('fulfilled', 'Fulfilled'),
    ('cancelled', 'Cancelled'),
]
BACKORDER_OPEN_STATUSES = ('open', 'promised')

DOCUMENT_TYPE_CHOICES = [
    ('packing_slip', 'Packing slip'),
    ('bol', 'Bill of lading'),
    ('pod', 'Proof of delivery'),
    ('other', 'Other'),
]


# ---------- 1./2./3./5. The central Shipment record (an ASN) ----------

class Shipment(TenantAwareModel, TimeStampedModel):
    """A single shipment fulfilling (part of) a purchase order — the ASN header."""

    STATUS_CHOICES = SHIPMENT_STATUS_CHOICES
    WEIGHT_UOM_CHOICES = WEIGHT_UOM_CHOICES
    RECEIVED_CONDITION_CHOICES = RECEIVED_CONDITION_CHOICES

    shipment_number = models.CharField(max_length=40)

    # PROTECT: a shipment is evidence of fulfilment against a financial commitment —
    # you must not silently delete the PO (or supplier) behind it.
    purchase_order = models.ForeignKey(
        'purchase_orders.PurchaseOrder', on_delete=models.PROTECT,
        related_name='shipments', help_text='The purchase order this shipment fulfils.',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.PROTECT, related_name='shipments',
        help_text='The shipping supplier (denormalised from the PO for filtering).',
    )

    status = models.CharField(
        max_length=20, choices=SHIPMENT_STATUS_CHOICES, default='draft',
    )

    # 1. ASN / packing details
    packing_slip_number = models.CharField(max_length=80, blank=True)
    package_count = models.PositiveIntegerField(default=1)
    total_weight = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    weight_uom = models.CharField(max_length=3, choices=WEIGHT_UOM_CHOICES, default='kg')
    packing_note = models.TextField(blank=True)
    advised_at = models.DateTimeField(null=True, blank=True)
    advised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='shipments_advised',
        help_text='Supplier portal user (or buyer recording on their behalf).',
    )

    # 2. Freight tracking
    carrier = models.CharField(max_length=120, blank=True)
    carrier_code = models.CharField(
        max_length=40, blank=True,
        help_text='Carrier connector key (e.g. "mock") used for live tracking sync.',
    )
    service_level = models.CharField(max_length=80, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)
    freight_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    freight_status = models.CharField(
        max_length=60, blank=True, help_text='Last carrier status label.',
    )
    tracking_last_synced_at = models.DateTimeField(null=True, blank=True)

    # Dates
    ship_date = models.DateField(null=True, blank=True)
    estimated_delivery_date = models.DateField(null=True, blank=True)
    actual_delivery_date = models.DateField(null=True, blank=True)

    # 3. Delivery confirmation
    delivered_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='shipments_confirmed',
    )
    received_condition = models.CharField(
        max_length=10, choices=RECEIVED_CONDITION_CHOICES, blank=True,
    )
    delivery_note = models.CharField(max_length=255, blank=True)
    proof_reference = models.CharField(
        max_length=120, blank=True,
        help_text='Proof-of-delivery reference (signature / photo id).',
    )

    # Lifecycle bookkeeping
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='shipments_created',
    )
    cancel_reason = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Alert idempotency guard (used by scan_fulfillment_alerts)
    delivery_alerted_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the overdue-delivery alert was raised.',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'shipment_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'vendor']),
            models.Index(fields=['tenant', 'purchase_order']),
            models.Index(fields=['tenant', 'estimated_delivery_date']),
        ]

    def __str__(self):
        return f'{self.shipment_number} — {self.purchase_order.po_number}'

    # --- status helpers ---
    @property
    def is_editable(self):
        return self.status in SHIPMENT_EDITABLE_STATUSES

    @property
    def can_advise(self):
        return self.status in SHIPMENT_ADVISABLE_STATUSES

    @property
    def can_track(self):
        return self.status in SHIPMENT_TRACKABLE_STATUSES

    @property
    def can_confirm_delivery(self):
        return self.status in SHIPMENT_CONFIRMABLE_STATUSES

    @property
    def can_cancel(self):
        return self.status in SHIPMENT_CANCELLABLE_STATUSES

    @property
    def can_close(self):
        return self.status in SHIPMENT_CLOSEABLE_STATUSES

    @property
    def is_open(self):
        return self.status in SHIPMENT_OPEN_STATUSES

    @property
    def is_finished(self):
        return self.status in SHIPMENT_FINISHED_STATUSES

    @property
    def is_advised(self):
        """True once the supplier has notified us (ASN sent)."""
        return self.status not in ('draft',)

    # --- line / split helpers ---
    @property
    def line_count(self):
        return self.lines.count()

    @property
    def total_shipped_qty(self):
        return sum(
            (ln.shipped_quantity or Decimal('0') for ln in self.lines.all()),
            Decimal('0.00'),
        )

    @property
    def is_split(self):
        """True if the parent PO is fulfilled across more than one (live) shipment."""
        return self.purchase_order.shipments.exclude(status='cancelled').count() > 1

    # --- delivery helpers ---
    @property
    def days_to_delivery(self):
        if not self.estimated_delivery_date:
            return None
        from django.utils import timezone
        return (self.estimated_delivery_date - timezone.localdate()).days

    @property
    def is_delivery_overdue(self):
        days = self.days_to_delivery
        return (
            days is not None and days < 0
            and self.status in SHIPMENT_TRACKABLE_STATUSES
        )


# ---------- 5. Shipment line items (which PO lines, how much) ----------

class ShipmentLine(TenantAwareModel, TimeStampedModel):
    """A line on a shipment — a quantity of a single PO line being delivered."""

    LINE_STATUS_CHOICES = SHIPMENT_LINE_STATUS_CHOICES

    shipment = models.ForeignKey(
        Shipment, on_delete=models.CASCADE, related_name='lines',
    )
    purchase_order_line = models.ForeignKey(
        'purchase_orders.PurchaseOrderLine', on_delete=models.PROTECT,
        related_name='shipment_lines',
    )
    line_no = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=255, blank=True)
    uom = models.CharField(max_length=30, default='unit')

    shipped_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    received_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Quantity confirmed received on this shipment.',
    )
    posted_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='How much has already been posted to the PO line — the idempotency '
                  'watermark so re-confirming a delivery never double-counts.',
    )
    backordered_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )

    carton_reference = models.CharField(max_length=80, blank=True)
    package_no = models.CharField(max_length=40, blank=True)
    line_status = models.CharField(
        max_length=12, choices=SHIPMENT_LINE_STATUS_CHOICES, default='pending',
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['line_no', 'id']
        # One line per (shipment, line_no) and at most one line per PO line on a
        # shipment — so confirm_delivery never posts two stale deltas for one PO line.
        unique_together = [
            ('shipment', 'line_no'),
            ('shipment', 'purchase_order_line'),
        ]

    def __str__(self):
        return f'{self.description or self.purchase_order_line_id} x{self.shipped_quantity}'

    @property
    def outstanding_quantity(self):
        """Shipped but not yet confirmed received on this shipment line."""
        return (self.shipped_quantity or Decimal('0')) - (self.received_quantity or Decimal('0'))

    @property
    def unposted_quantity(self):
        """Confirmed received but not yet posted to the PO line."""
        return (self.received_quantity or Decimal('0')) - (self.posted_quantity or Decimal('0'))


# ---------- 2. Real-time freight tracking (append-only ledger) ----------

class ShipmentTrackingEvent(TenantAwareModel, TimeStampedModel):
    """An append-only carrier tracking event for a shipment."""

    SOURCE_CHOICES = TRACKING_SOURCE_CHOICES

    shipment = models.ForeignKey(
        Shipment, on_delete=models.CASCADE, related_name='tracking_events',
    )
    status_code = models.CharField(max_length=40)
    description = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=160, blank=True)
    occurred_at = models.DateTimeField()
    source = models.CharField(
        max_length=10, choices=TRACKING_SOURCE_CHOICES, default='manual',
    )
    raw = models.JSONField(default=dict, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='shipment_tracking_events',
    )

    class Meta:
        ordering = ['-occurred_at', '-id']
        indexes = [
            models.Index(fields=['tenant', 'shipment']),
        ]

    def __str__(self):
        return f'{self.shipment.shipment_number}: {self.status_code}'


# ---------- 4. Backorder management ----------

class Backorder(TenantAwareModel, TimeStampedModel):
    """An out-of-stock / undelivered remainder of a PO line scheduled for later delivery."""

    STATUS_CHOICES = BACKORDER_STATUS_CHOICES

    purchase_order = models.ForeignKey(
        'purchase_orders.PurchaseOrder', on_delete=models.PROTECT,
        related_name='backorders',
    )
    purchase_order_line = models.ForeignKey(
        'purchase_orders.PurchaseOrderLine', on_delete=models.PROTECT,
        related_name='backorders',
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    expected_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=BACKORDER_STATUS_CHOICES, default='open',
    )
    reason = models.CharField(max_length=255, blank=True)

    fulfilled_by_shipment = models.ForeignKey(
        Shipment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fulfilled_backorders',
    )
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='backorders_created',
    )
    # Alert idempotency guard (used by scan_backorder_alerts)
    alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['expected_date', '-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'purchase_order']),
        ]

    def __str__(self):
        return f'Backorder {self.quantity} on {self.purchase_order.po_number}'

    @property
    def is_open(self):
        return self.status in BACKORDER_OPEN_STATUSES

    @property
    def is_overdue(self):
        if not self.expected_date or not self.is_open:
            return False
        from django.utils import timezone
        return self.expected_date < timezone.localdate()


# ---------- Append-only lifecycle timeline ----------

class ShipmentStatusEvent(TenantAwareModel, TimeStampedModel):
    """An append-only record of every shipment status transition."""

    shipment = models.ForeignKey(
        Shipment, on_delete=models.CASCADE, related_name='status_events',
    )
    status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='shipment_status_events',
    )

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.shipment.shipment_number} → {self.status}'


# ---------- Attachments ----------

class ShipmentDocument(TenantAwareModel, TimeStampedModel):
    """A document attached to a shipment (packing slip, BOL, proof of delivery)."""

    DOC_TYPE_CHOICES = DOCUMENT_TYPE_CHOICES

    shipment = models.ForeignKey(
        Shipment, on_delete=models.CASCADE, related_name='documents',
    )
    title = models.CharField(max_length=200)
    doc_type = models.CharField(
        max_length=16, choices=DOCUMENT_TYPE_CHOICES, default='other',
    )
    file = models.FileField(upload_to='shipment_docs/', blank=True, null=True)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='shipment_documents_uploaded',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.title} ({self.shipment.shipment_number})'
