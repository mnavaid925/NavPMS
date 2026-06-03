"""Module 11: Purchase Order (PO) Management.

Covers the five PMS sub-modules:
  1. PO Generation               -> PurchaseOrder + PurchaseOrderLine (created from an
                                    approved Requisition or entered manually)
  2. PO Dispatch & Acknowledgment -> issue/dispatch stamps + vendor-portal acknowledge /
                                    decline (a portal Notification alerts the supplier)
  3. PO Change Order Management   -> PurchaseOrderChangeOrder (quantity / price / delivery-
                                    date changes on an active PO; immutable once applied,
                                    bumps PurchaseOrder.revision)
  4. PO Cancellation & Close-out  -> status workflow (cancel an unfulfilled PO / close a
                                    fully or partially received PO)
  5. PO Line Item Tracking        -> PurchaseOrderLine.delivery_status + received_quantity
                                    (a lightweight precursor to Module 13 Goods Receipt)

A purchase order is generated from an approved requisition (lines pre-filled) or entered
manually, dispatched to a supplier who acknowledges or declines it, received line-by-line,
then closed — or cancelled while unfulfilled. Changes to an issued PO are tracked as change
orders. Mirrors the Module 9 (Contracts) conventions: TenantAwareModel + TimeStampedModel
bases, module-level status constants + EDITABLE/OPEN/FINISHED tuples, gap-free
PO-<SLUG>-NNNNN numbering (in services.py), and an append-only PurchaseOrderStatusEvent
timeline.

Decimal convention: line unit prices, line totals and the PO money fields use 2 dp (the
project money pattern, matching requisitions — the generation source).
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Choice constants (module-level, mirroring the contracts module)
# ---------------------------------------------------------------------------
PO_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('issued', 'Issued'),
    ('acknowledged', 'Acknowledged'),
    ('declined', 'Declined'),
    ('partially_received', 'Partially Received'),
    ('received', 'Received'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]
PO_EDITABLE_STATUSES = ('draft',)
PO_ISSUABLE_STATUSES = ('draft',)
PO_ACKNOWLEDGEABLE_STATUSES = ('issued',)
PO_RECEIVABLE_STATUSES = ('issued', 'acknowledged', 'partially_received')
PO_CHANGE_ORDERABLE_STATUSES = ('issued', 'acknowledged', 'partially_received')
PO_CANCELLABLE_STATUSES = (
    'draft', 'issued', 'acknowledged', 'partially_received', 'declined',
)
PO_CLOSEABLE_STATUSES = ('partially_received', 'received')
PO_OPEN_STATUSES = ('draft', 'issued', 'acknowledged', 'partially_received')
PO_FINISHED_STATUSES = ('closed', 'cancelled')
# Statuses where the supplier has the PO in hand (used by the vendor portal gate).
PO_DISPATCHED_STATUSES = (
    'issued', 'acknowledged', 'declined', 'partially_received', 'received', 'closed',
)

DISPATCH_METHOD_CHOICES = [
    ('portal', 'Vendor portal'),
    ('email', 'Email'),
    ('manual', 'Manual / offline'),
]

LINE_DELIVERY_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('partial', 'Partially received'),
    ('received', 'Received'),
    ('cancelled', 'Cancelled'),
]
LINE_OPEN_DELIVERY_STATUSES = ('pending', 'partial')

CHANGE_ORDER_TYPE_CHOICES = [
    ('quantity', 'Quantity change'),
    ('price', 'Price change'),
    ('delivery_date', 'Delivery date change'),
    ('lines', 'Line items'),
    ('mixed', 'Multiple changes'),
]
CHANGE_ORDER_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('pending_approval', 'Pending approval'),
    ('applied', 'Applied'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled'),
]
CHANGE_ORDER_EDITABLE_STATUSES = ('draft', 'pending_approval')


# ---------- 1./2./4. The central PurchaseOrder record ----------

class PurchaseOrder(TenantAwareModel, TimeStampedModel):
    """A purchase order issued to a supplier — generated, dispatched, received, closed."""

    STATUS_CHOICES = PO_STATUS_CHOICES
    DISPATCH_METHOD_CHOICES = DISPATCH_METHOD_CHOICES

    po_number = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # PROTECT: a PO is a financial commitment — you must not silently delete the
    # supplier behind it. Nullable so a PO can be generated from a requisition
    # (which has no vendor) and have its supplier assigned before dispatch.
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.PROTECT, null=True, blank=True,
        related_name='purchase_orders', help_text='The supplier this PO is issued to.',
    )
    category = models.ForeignKey(
        'vendors.VendorCategory', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_orders',
    )
    requisition = models.ForeignKey(
        'requisitions.Requisition', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_orders',
        help_text='Source requisition, if this PO was generated from one.',
    )

    currency = models.CharField(max_length=3, default='USD')
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    tax_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    shipping_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    total_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )

    order_date = models.DateField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)

    payment_terms = models.CharField(max_length=160, blank=True)
    shipping_address = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=20, choices=PO_STATUS_CHOICES, default='draft',
    )
    revision = models.PositiveIntegerField(default=1)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_orders_owned',
        help_text='Internal buyer / PO owner.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_orders_created',
    )

    # 2. Dispatch
    dispatch_method = models.CharField(
        max_length=10, choices=DISPATCH_METHOD_CHOICES, default='portal',
    )
    dispatched_to = models.EmailField(
        blank=True, help_text='Email the PO was dispatched to (snapshot).',
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_orders_issued',
    )

    # 2. Acknowledgment
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_orders_acknowledged',
        help_text='Supplier portal user (or buyer recording on their behalf).',
    )
    acknowledgement_note = models.CharField(max_length=255, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.CharField(max_length=255, blank=True)

    # 4. Close-out / cancellation
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_orders_closed',
    )
    close_note = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_orders_cancelled',
    )
    cancel_reason = models.CharField(max_length=255, blank=True)

    # Alert idempotency guards (used by scan_po_alerts)
    ack_alerted_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the awaiting-acknowledgment reminder was raised.',
    )
    delivery_alerted_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the overdue-delivery alert was raised.',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'po_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'vendor']),
            models.Index(fields=['tenant', 'expected_delivery_date']),
        ]

    def __str__(self):
        return f'{self.po_number} — {self.title}'

    # --- status helpers ---
    @property
    def is_editable(self):
        return self.status in PO_EDITABLE_STATUSES

    @property
    def can_issue(self):
        return self.status in PO_ISSUABLE_STATUSES

    @property
    def is_issued(self):
        return self.status == 'issued'

    @property
    def can_acknowledge(self):
        return self.status in PO_ACKNOWLEDGEABLE_STATUSES

    @property
    def can_receive(self):
        return self.status in PO_RECEIVABLE_STATUSES

    @property
    def can_change_order(self):
        return self.status in PO_CHANGE_ORDERABLE_STATUSES

    @property
    def can_cancel(self):
        return self.status in PO_CANCELLABLE_STATUSES

    @property
    def can_close(self):
        return self.status in PO_CLOSEABLE_STATUSES

    @property
    def is_open(self):
        return self.status in PO_OPEN_STATUSES

    @property
    def is_finished(self):
        return self.status in PO_FINISHED_STATUSES

    @property
    def is_dispatched(self):
        """True once the supplier has the PO (drives the vendor-portal gate)."""
        return self.status in PO_DISPATCHED_STATUSES

    # --- receiving helpers ---
    @property
    def line_count(self):
        return self.lines.count()

    @property
    def received_line_count(self):
        return self.lines.filter(delivery_status='received').count()

    @property
    def is_fully_received(self):
        """True if there is at least one line and every active line is received."""
        active = self.lines.exclude(delivery_status='cancelled')
        total = active.count()
        if not total:
            return False
        return active.filter(delivery_status='received').count() == total

    @property
    def received_progress(self):
        """Percent of active lines fully received (0-100)."""
        active = self.lines.exclude(delivery_status='cancelled')
        total = active.count()
        if not total:
            return 0
        received = active.filter(delivery_status='received').count()
        return int(round(received / total * 100))

    # --- expiry / delivery helpers ---
    @property
    def days_to_delivery(self):
        if not self.expected_delivery_date:
            return None
        from django.utils import timezone
        return (self.expected_delivery_date - timezone.localdate()).days

    @property
    def is_delivery_overdue(self):
        days = self.days_to_delivery
        return (
            days is not None and days < 0
            and self.status in ('issued', 'acknowledged', 'partially_received')
        )


# ---------- 1./5. Line items ----------

class PurchaseOrderLine(TenantAwareModel, TimeStampedModel):
    """A single ordered item on a purchase order, with delivery tracking."""

    DELIVERY_STATUS_CHOICES = LINE_DELIVERY_STATUS_CHOICES

    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='lines',
    )
    line_no = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=255)
    sku = models.CharField(max_length=60, blank=True)
    uom = models.CharField(max_length=30, default='unit')
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('1.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    line_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
    )
    account_code = models.ForeignKey(
        'requisitions.AccountCode', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_order_lines',
    )
    requisition_line = models.ForeignKey(
        'requisitions.RequisitionLine', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_order_lines',
        help_text='Source requisition line (provenance), if generated from one.',
    )
    required_date = models.DateField(null=True, blank=True)

    # 5. Line item tracking
    delivery_status = models.CharField(
        max_length=12, choices=LINE_DELIVERY_STATUS_CHOICES, default='pending',
    )
    received_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['line_no', 'id']
        unique_together = [('purchase_order', 'line_no')]

    def __str__(self):
        return f'{self.description} x{self.quantity}'

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))
        super().save(*args, **kwargs)

    @property
    def outstanding_quantity(self):
        return (self.quantity or Decimal('0')) - (self.received_quantity or Decimal('0'))

    @property
    def is_received(self):
        return self.delivery_status == 'received'

    @property
    def is_open(self):
        return self.delivery_status in LINE_OPEN_DELIVERY_STATUSES


# ---------- 3. Change Order Management ----------

class PurchaseOrderChangeOrder(TenantAwareModel, TimeStampedModel):
    """A tracked change to an issued PO (quantity / price / delivery date).

    Applying the change order snapshots the previous values, writes the proposed
    values onto the PO / its lines and bumps ``PurchaseOrder.revision`` — mirroring
    how an applied contract amendment is frozen into the version history.
    """

    CHANGE_TYPE_CHOICES = CHANGE_ORDER_TYPE_CHOICES
    STATUS_CHOICES = CHANGE_ORDER_STATUS_CHOICES

    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='change_orders',
    )
    change_number = models.CharField(max_length=48)
    change_type = models.CharField(
        max_length=16, choices=CHANGE_ORDER_TYPE_CHOICES, default='mixed',
    )
    reason = models.TextField(blank=True)

    # Proposed changes — NULL/empty means "no change to this".
    new_expected_delivery_date = models.DateField(null=True, blank=True)
    proposed_lines = models.JSONField(
        default=list, blank=True,
        help_text='List of {line_id, quantity, unit_price} applied atomically on approval.',
    )

    # Snapshot captured at apply time (audit trail).
    prev_expected_delivery_date = models.DateField(null=True, blank=True)
    prev_lines = models.JSONField(default=list, blank=True)
    prev_total = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
    )
    new_total = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
    )

    status = models.CharField(
        max_length=20, choices=CHANGE_ORDER_STATUS_CHOICES, default='draft',
    )
    effective_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='po_change_orders_created',
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='po_change_orders_applied',
    )
    decision_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('purchase_order', 'change_number')]

    def __str__(self):
        return f'{self.change_number} on {self.purchase_order.po_number}'

    @property
    def is_applied(self):
        return self.status == 'applied'

    @property
    def is_editable(self):
        return self.status in CHANGE_ORDER_EDITABLE_STATUSES


# ---------- Attachments ----------

class PurchaseOrderDocument(TenantAwareModel, TimeStampedModel):
    """A document attached to a purchase order (signed PO PDF, supplier docs, etc.)."""

    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='documents',
    )
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='purchase_order_docs/', blank=True, null=True)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_order_documents_uploaded',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.title} ({self.purchase_order.po_number})'


# ---------- Append-only lifecycle timeline ----------

class PurchaseOrderStatusEvent(TenantAwareModel, TimeStampedModel):
    """An append-only record of every PO / change-order status transition."""

    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='status_events',
    )
    change_order = models.ForeignKey(
        PurchaseOrderChangeOrder, on_delete=models.CASCADE, null=True, blank=True,
        related_name='status_events',
    )
    status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='po_status_events',
    )

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.purchase_order.po_number} → {self.status}'
