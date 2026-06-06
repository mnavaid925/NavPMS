"""Module 19: Inventory & Warehouse Integration.

The stock layer under the procure-to-pay loop. Where Module 13 (Goods Receipt) records that goods
*arrived* (and only bumps ``PurchaseOrderLine.received_quantity``), this module records where that
stock now *lives*, how much is on hand, when it expires, what it is worth, and reconciles it.

Covers the five PMS sub-modules:
  1. Stock Level Visibility          -> StockItem (on-hand roll-up) + StockLevel (per location/lot
                                        bucket), fed from posted GRNs by services.sync_stock_from_receipts
  2. Reorder Point Automation        -> StockItem.reorder_point + services.run_reorder_automation,
                                        which mints a DRAFT requisitions.Requisition (Module 3)
  3. Goods Issue / Return to Stock   -> GoodsIssue (+ GoodsIssueLine) consumption / return / write-off
  4. Warehouse Location Mapping      -> Warehouse + WarehouseLocation (bin / aisle / rack)
  5. Cycle Count Integration         -> CycleCount (+ CycleCountLine), posting adjusts stock immediately

DESIGN — downstream observer (the Module 18 precedent). Every cross-module reference is an *outbound*
FK declared here (to ``catalog.CatalogItem`` / ``goods_receipt.GoodsReceiptLine`` /
``requisitions.Requisition`` / the user model) so no source app is migrated. Stock is fed from posted
goods receipts via ``services.sync_stock_from_receipts`` (the spend_analytics/budget sync precedent),
made idempotent by the ``unique`` ``StockMovement.source_goods_receipt_line`` watermark — goods_receipt
is never imported by, and never imports, this app.

Conventions mirrored from the recent modules: TenantAwareModel + TimeStampedModel bases, module-level
status / colour constants, gap-free ``<PREFIX>-<SLUG>-NNNNN`` numbering (services.py), an append-only
``StockMovement`` ledger + per-document status-event timelines, and 2dp quantities / 4dp unit costs.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Module-level choice + colour constants and field helpers
# ---------------------------------------------------------------------------
STOCK_CONDITION_CHOICES = [
    ('available', 'Available'),
    ('quarantine', 'Quarantine'),
    ('damaged', 'Damaged'),
]

# Stock-health vocabulary used by StockItem.stock_status (badge colours in templates).
STOCK_STATUS_COLORS = {'out': 'danger', 'low': 'warning', 'ok': 'success'}

MOVEMENT_TYPE_CHOICES = [
    ('receipt', 'Receipt (from GRN)'),
    ('issue', 'Goods issue'),
    ('return', 'Return to stock'),
    ('adjustment', 'Manual adjustment'),
    ('transfer_out', 'Transfer out'),
    ('transfer_in', 'Transfer in'),
    ('count_adjustment', 'Cycle-count adjustment'),
]
MOVEMENT_TYPE_COLORS = {
    'receipt': 'success', 'issue': 'danger', 'return': 'info', 'adjustment': 'warning',
    'transfer_out': 'secondary', 'transfer_in': 'secondary', 'count_adjustment': 'primary',
}

ISSUE_TYPE_CHOICES = [
    ('consumption', 'Internal consumption'),
    ('return_to_stock', 'Return to stock'),
    ('write_off', 'Write-off / scrap'),
]
ISSUE_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('issued', 'Issued'),
    ('cancelled', 'Cancelled'),
]
ISSUE_EDITABLE_STATUSES = ('draft',)
ISSUE_STATUS_COLORS = {'draft': 'secondary', 'issued': 'success', 'cancelled': 'dark'}

CYCLE_SCOPE_CHOICES = [
    ('full', 'Full warehouse'),
    ('location', 'By location'),
    ('abc', 'By ABC class'),
]
CYCLE_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('in_progress', 'Counting'),
    ('posted', 'Posted'),
    ('cancelled', 'Cancelled'),
]
CYCLE_EDITABLE_STATUSES = ('draft', 'in_progress')
CYCLE_STATUS_COLORS = {
    'draft': 'secondary', 'in_progress': 'info', 'posted': 'success', 'cancelled': 'dark',
}

ABC_CHOICES = [('A', 'A — high value'), ('B', 'B — medium'), ('C', 'C — low value')]


def _qty(**kwargs):
    """A 12,2 quantity field — the project's non-negative quantity convention."""
    kwargs.setdefault('default', Decimal('0.00'))
    kwargs.setdefault('validators', [MinValueValidator(Decimal('0'))])
    return models.DecimalField(max_digits=12, decimal_places=2, **kwargs)


def _signed_qty(**kwargs):
    """A 12,2 quantity field that may be negative (used by the signed StockMovement ledger)."""
    kwargs.setdefault('default', Decimal('0.00'))
    return models.DecimalField(max_digits=12, decimal_places=2, **kwargs)


def _cost(**kwargs):
    """A 14,4 unit-cost field (matches the 4dp ``CatalogItem.base_price`` convention)."""
    kwargs.setdefault('default', Decimal('0.0000'))
    kwargs.setdefault('validators', [MinValueValidator(Decimal('0'))])
    return models.DecimalField(max_digits=14, decimal_places=4, **kwargs)


# ---------------------------------------------------------------------------
# 4. Warehouse Location Mapping
# ---------------------------------------------------------------------------
class Warehouse(TenantAwareModel, TimeStampedModel):
    """A physical stocking location (a site / DC / store-room)."""

    code = models.CharField(max_length=40, help_text='Short code, e.g. WH-MAIN.')
    name = models.CharField(max_length=120)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=False, help_text='The fallback warehouse when a receipt has no mapped bin.',
    )

    class Meta:
        ordering = ['code']
        unique_together = [('tenant', 'code')]
        indexes = [models.Index(fields=['tenant', 'is_active'])]

    def __str__(self):
        return f'{self.code} — {self.name}'


class WarehouseLocation(TenantAwareModel, TimeStampedModel):
    """A bin / aisle / rack inside a warehouse — the exact putaway destination."""

    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name='locations',
    )
    code = models.CharField(max_length=40, help_text='Bin code, e.g. A-01-03.')
    aisle = models.CharField(max_length=20, blank=True)
    rack = models.CharField(max_length=20, blank=True)
    shelf = models.CharField(max_length=20, blank=True)
    description = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['warehouse_id', 'code']
        unique_together = [('tenant', 'warehouse', 'code')]
        indexes = [models.Index(fields=['tenant', 'warehouse'])]

    def __str__(self):
        return f'{self.warehouse.code} / {self.code}'

    @property
    def label(self):
        bits = [b for b in (self.aisle, self.rack, self.shelf) if b]
        return ' · '.join(bits) or self.description or self.code


# ---------------------------------------------------------------------------
# 1. Stock Level Visibility
# ---------------------------------------------------------------------------
class StockItem(TenantAwareModel, TimeStampedModel):
    """The inventory profile of one catalog item — the on-hand roll-up + reorder parameters.

    Links to the approved ``catalog.CatalogItem`` master (matched from a received line's SKU during
    :func:`services.sync_stock_from_receipts`). ``quantity_on_hand`` / ``quantity_reserved`` are
    denormalised running totals kept in sync atomically by :func:`services.apply_movement`;
    ``moving_avg_cost`` is recomputed on each receipt.
    """

    ABC_CHOICES = ABC_CHOICES

    catalog_item = models.ForeignKey(
        'catalog.CatalogItem', on_delete=models.PROTECT, related_name='stock_item',
        help_text='The catalog master this stock tracks.',
    )
    sku = models.CharField(
        max_length=60, blank=True, help_text='Denormalised from the catalog item (GRN join key).',
    )
    is_stocked = models.BooleanField(
        default=True, help_text='Whether this item is tracked + eligible for reorder automation.',
    )
    default_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='default_for_items',
    )
    default_location = models.ForeignKey(
        WarehouseLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='default_for_items',
    )

    reorder_point = _qty(help_text='Reorder when available stock falls to/below this level.')
    reorder_quantity = _qty(help_text='Quantity the auto-requisition orders.')
    safety_stock = _qty(help_text='Buffer kept above zero (informational).')
    lead_time_days = models.PositiveIntegerField(default=0)
    abc_class = models.CharField(max_length=1, choices=ABC_CHOICES, blank=True)

    moving_avg_cost = _cost(help_text='Weighted-average unit cost, recomputed on each receipt.')
    quantity_on_hand = _qty(help_text='Denormalised sum of all stock-level buckets.')
    quantity_reserved = _qty(help_text='Soft-allocated quantity (not available to issue).')

    # Reorder idempotency: the open draft requisition this item last triggered (if any).
    reorder_requisition = models.ForeignKey(
        'requisitions.Requisition', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    last_reordered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['sku', 'id']
        unique_together = [('tenant', 'catalog_item')]
        indexes = [
            models.Index(fields=['tenant', 'sku']),
            models.Index(fields=['tenant', 'is_stocked']),
        ]

    def __str__(self):
        return f'{self.sku or self.catalog_item_id}: {self.quantity_on_hand}'

    @property
    def available_quantity(self):
        return (self.quantity_on_hand or Decimal('0')) - (self.quantity_reserved or Decimal('0'))

    @property
    def is_below_reorder(self):
        return bool(
            self.is_stocked
            and (self.reorder_point or Decimal('0')) > 0
            and self.available_quantity <= (self.reorder_point or Decimal('0'))
        )

    @property
    def stock_status(self):
        if (self.quantity_on_hand or Decimal('0')) <= 0:
            return 'out'
        if self.is_below_reorder:
            return 'low'
        return 'ok'

    @property
    def stock_status_color(self):
        return STOCK_STATUS_COLORS.get(self.stock_status, 'secondary')

    @property
    def on_hand_value(self):
        return ((self.quantity_on_hand or Decimal('0'))
                * (self.moving_avg_cost or Decimal('0'))).quantize(Decimal('0.01'))

    @property
    def name(self):
        return self.catalog_item.name if self.catalog_item_id else (self.sku or '')


class StockLevel(TenantAwareModel, TimeStampedModel):
    """An on-hand bucket: quantity of one item at one location, for one lot/serial/expiry/condition."""

    CONDITION_CHOICES = STOCK_CONDITION_CHOICES

    stock_item = models.ForeignKey(
        StockItem, on_delete=models.CASCADE, related_name='levels',
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='stock_levels',
    )
    location = models.ForeignKey(
        WarehouseLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_levels',
    )
    lot_number = models.CharField(max_length=80, blank=True)
    batch_number = models.CharField(max_length=80, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    condition = models.CharField(
        max_length=12, choices=STOCK_CONDITION_CHOICES, default='available',
    )
    quantity = _qty()
    reserved_quantity = _qty()
    # Alert idempotency for the near-expiry cron sweep.
    expiry_alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['stock_item_id', 'location_id']
        unique_together = [(
            'tenant', 'stock_item', 'location', 'lot_number', 'batch_number',
            'serial_number', 'expiry_date', 'condition',
        )]
        indexes = [
            models.Index(fields=['tenant', 'stock_item']),
            models.Index(fields=['tenant', 'warehouse']),
            models.Index(fields=['tenant', 'expiry_date']),
        ]

    def __str__(self):
        return f'{self.stock_item_id} @ {self.location_id or self.warehouse_id}: {self.quantity}'

    @property
    def available(self):
        return (self.quantity or Decimal('0')) - (self.reserved_quantity or Decimal('0'))


class StockMovement(TenantAwareModel, TimeStampedModel):
    """An append-only ledger entry — the single source of truth for every stock change.

    ``quantity`` is signed (positive = in, negative = out). Source documents are referenced by
    nullable FKs; ``source_goods_receipt_line`` is ``unique`` so re-syncing posted GRNs never
    double-counts (the idempotency watermark).
    """

    TYPE_CHOICES = MOVEMENT_TYPE_CHOICES

    number = models.CharField(max_length=40, help_text='Auto MOV-<SLUG>-NNNNN.')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPE_CHOICES)
    stock_item = models.ForeignKey(
        StockItem, on_delete=models.PROTECT, related_name='movements',
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='movements',
    )
    location = models.ForeignKey(
        WarehouseLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movements',
    )
    to_location = models.ForeignKey(
        WarehouseLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inbound_movements', help_text='Destination bin for a transfer.',
    )
    lot_number = models.CharField(max_length=80, blank=True)
    batch_number = models.CharField(max_length=80, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    quantity = _signed_qty(help_text='Signed change (+ in / - out).')
    unit_cost = _cost()
    balance_after = _qty(help_text='Item on-hand after this movement (audit nicety).')
    reason = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=255, blank=True)

    # Decoupled source references (no inbound FK is ever added to the source apps).
    source_goods_receipt_line = models.OneToOneField(
        'goods_receipt.GoodsReceiptLine', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_movement',
        help_text='The GRN line this receipt was synced from (idempotency watermark).',
    )
    goods_issue_line = models.ForeignKey(
        'inventory.GoodsIssueLine', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_movements',
    )
    cycle_count_line = models.ForeignKey(
        'inventory.CycleCountLine', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stock_movements',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='inventory_movements',
    )

    class Meta:
        ordering = ['-created_at', '-id']
        unique_together = [('tenant', 'number')]
        indexes = [
            models.Index(fields=['tenant', 'stock_item', 'created_at']),
            models.Index(fields=['tenant', 'movement_type']),
        ]

    def __str__(self):
        return f'{self.number} {self.movement_type} {self.quantity}'

    @property
    def type_color(self):
        return MOVEMENT_TYPE_COLORS.get(self.movement_type, 'secondary')

    @property
    def is_inbound(self):
        return (self.quantity or Decimal('0')) > 0


# ---------------------------------------------------------------------------
# 3. Goods Issue / Return to Stock
# ---------------------------------------------------------------------------
class GoodsIssue(TenantAwareModel, TimeStampedModel):
    """An internal stock movement document: consumption, return-to-stock, or write-off."""

    TYPE_CHOICES = ISSUE_TYPE_CHOICES
    STATUS_CHOICES = ISSUE_STATUS_CHOICES

    number = models.CharField(max_length=40, help_text='Auto GI-<SLUG>-NNNNN.')
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='goods_issues',
    )
    issue_type = models.CharField(
        max_length=20, choices=ISSUE_TYPE_CHOICES, default='consumption',
    )
    purpose = models.CharField(max_length=200, blank=True)
    department = models.CharField(max_length=120, blank=True)
    cost_center = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=12, choices=ISSUE_STATUS_CHOICES, default='draft')

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_issues_requested',
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_issues_issued',
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_issues_created',
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'warehouse']),
        ]

    def __str__(self):
        return f'{self.number} ({self.get_issue_type_display()})'

    @property
    def status_color(self):
        return ISSUE_STATUS_COLORS.get(self.status, 'secondary')

    @property
    def is_editable(self):
        return self.status in ISSUE_EDITABLE_STATUSES

    @property
    def is_return(self):
        return self.issue_type == 'return_to_stock'

    @property
    def direction(self):
        """+1 returns stock TO the warehouse; -1 takes it OUT (consumption / write-off)."""
        return 1 if self.is_return else -1

    @property
    def line_count(self):
        return self.lines.count()

    @property
    def can_post(self):
        return self.status == 'draft' and self.lines.exists()

    @property
    def can_cancel(self):
        return self.status == 'draft'

    @property
    def total_quantity(self):
        return sum((ln.quantity or Decimal('0') for ln in self.lines.all()), Decimal('0.00'))


class GoodsIssueLine(TenantAwareModel, TimeStampedModel):
    """A single item line on a goods issue/return (quantity is always positive)."""

    goods_issue = models.ForeignKey(
        GoodsIssue, on_delete=models.CASCADE, related_name='lines',
    )
    stock_item = models.ForeignKey(
        StockItem, on_delete=models.PROTECT, related_name='goods_issue_lines',
    )
    location = models.ForeignKey(
        WarehouseLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_issue_lines',
    )
    lot_number = models.CharField(max_length=80, blank=True)
    batch_number = models.CharField(max_length=80, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = _qty(default=Decimal('1.00'))
    unit_cost = _cost()
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.stock_item_id} x{self.quantity}'

    @property
    def line_value(self):
        return ((self.quantity or Decimal('0')) * (self.unit_cost or Decimal('0'))).quantize(
            Decimal('0.01'))


class GoodsIssueStatusEvent(TenantAwareModel, TimeStampedModel):
    """An immutable entry in a goods-issue status timeline."""

    goods_issue = models.ForeignKey(
        GoodsIssue, on_delete=models.CASCADE, related_name='events',
    )
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goods_issue_events',
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.goods_issue_id}: {self.from_status or "—"} → {self.to_status}'


# ---------------------------------------------------------------------------
# 5. Cycle Count Integration
# ---------------------------------------------------------------------------
class CycleCount(TenantAwareModel, TimeStampedModel):
    """A scheduled physical count that reconciles system stock against a counted quantity."""

    SCOPE_CHOICES = CYCLE_SCOPE_CHOICES
    STATUS_CHOICES = CYCLE_STATUS_CHOICES

    number = models.CharField(max_length=40, help_text='Auto CC-<SLUG>-NNNNN.')
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='cycle_counts',
    )
    scope = models.CharField(max_length=12, choices=CYCLE_SCOPE_CHOICES, default='full')
    scheduled_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=CYCLE_STATUS_CHOICES, default='draft')

    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cycle_counts_counted',
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cycle_counts_posted',
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cycle_counts_created',
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'warehouse']),
        ]

    def __str__(self):
        return f'{self.number} ({self.get_status_display()})'

    @property
    def status_color(self):
        return CYCLE_STATUS_COLORS.get(self.status, 'secondary')

    @property
    def is_editable(self):
        return self.status in CYCLE_EDITABLE_STATUSES

    @property
    def can_post(self):
        return self.status in CYCLE_EDITABLE_STATUSES and self.lines.exists()

    @property
    def can_cancel(self):
        return self.status in CYCLE_EDITABLE_STATUSES

    @property
    def line_count(self):
        return self.lines.count()

    @property
    def variance_line_count(self):
        return self.lines.exclude(variance=Decimal('0')).filter(counted=True).count()


class CycleCountLine(TenantAwareModel, TimeStampedModel):
    """One counted bucket: the system quantity snapshot vs the physically counted quantity."""

    cycle_count = models.ForeignKey(
        CycleCount, on_delete=models.CASCADE, related_name='lines',
    )
    stock_item = models.ForeignKey(
        StockItem, on_delete=models.PROTECT, related_name='cycle_count_lines',
    )
    location = models.ForeignKey(
        WarehouseLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cycle_count_lines',
    )
    lot_number = models.CharField(max_length=80, blank=True)
    batch_number = models.CharField(max_length=80, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    system_quantity = _qty(help_text='On-hand snapshot when the count was created.')
    counted_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Physically counted quantity (blank = not yet counted).',
    )
    variance = _signed_qty(help_text='counted − system at post time (signed).')
    unit_cost = _cost()
    counted = models.BooleanField(default=False)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.stock_item_id}: sys {self.system_quantity} / cnt {self.counted_quantity}'

    @property
    def variance_value(self):
        return ((self.variance or Decimal('0')) * (self.unit_cost or Decimal('0'))).quantize(
            Decimal('0.01'))


class CycleCountStatusEvent(TenantAwareModel, TimeStampedModel):
    """An immutable entry in a cycle-count status timeline."""

    cycle_count = models.ForeignKey(
        CycleCount, on_delete=models.CASCADE, related_name='events',
    )
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cycle_count_events',
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.cycle_count_id}: {self.from_status or "—"} → {self.to_status}'
