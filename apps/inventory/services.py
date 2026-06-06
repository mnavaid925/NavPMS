"""Module 19 service layer: Inventory & Warehouse Integration.

Five concerns, one module:

* **Stock visibility** — :func:`sync_stock_from_receipts` reads posted Module 13 goods-receipt lines
  and turns each accepted quantity into an inbound :class:`StockMovement` (idempotent via the unique
  ``StockMovement.source_goods_receipt_line`` watermark). :func:`apply_movement` is the single atomic
  primitive every stock change flows through — it upserts the :class:`StockLevel` bucket, keeps the
  :class:`StockItem` on-hand roll-up + moving-average cost in sync, and guards against negative stock.
* **Reorder automation** — :func:`run_reorder_automation` mints a DRAFT ``requisitions.Requisition``
  for every stocked item at/below its reorder point and notifies procurement (idempotent — it never
  re-raises while an open reorder requisition exists).
* **Goods issue / return** — :func:`post_goods_issue` applies the issue (consumption / write-off, out)
  or return-to-stock (in) movements.
* **Cycle count** — :func:`post_cycle_count` reconciles counted vs *current* system quantity and
  writes the adjustment movements immediately (the manager's post is the control gate).
* **Audit + notifications** — reuses ``apps.tenants.record_audit`` and ``apps.portal.create_notification``.

DESIGN — a downstream observer (the Module 18 precedent): it reads ``catalog`` / ``goods_receipt`` /
``requisitions`` by FK/query and never mutates them, so no source app is migrated.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant
from apps.portal.services import create_notification
from apps.tenants.services import record_audit

from .models import (
    CycleCount, CycleCountLine, CycleCountStatusEvent, GoodsIssue, GoodsIssueLine,
    GoodsIssueStatusEvent, StockItem, StockLevel, StockMovement, Warehouse, WarehouseLocation,
)

ZERO = Decimal('0.00')
QTY_Q = Decimal('0.01')
COST_Q = Decimal('0.0001')

# Roles allowed to manage inventory (adjust stock, issue goods, post counts, run reorder). Mirrors the
# other procurement modules — there is no dedicated warehouse role in the project yet.
MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
# Viewing (dashboards / lists / ledger) additionally allows approvers.
VIEW_ROLES = MANAGE_ROLES + ('approver',)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _has_role(user, roles):
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'is_tenant_admin', False):
        return True
    role = getattr(user, 'role', None)
    role_slug = role if isinstance(role, str) else (
        getattr(role, 'slug', None) or getattr(role, 'name', None))
    return role_slug in roles


def can_manage_inventory(user):
    """May adjust stock, issue/return goods, post cycle counts, run reorder, manage warehouses."""
    return _has_role(user, MANAGE_ROLES)


def can_view_inventory(user):
    """May view dashboards / stock lists / movement ledger (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def _next_number(model, tenant, prefix) -> str:
    """Generate the next gap-free ``<PREFIX>-<SLUG>-NNNNN`` number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = model.all_objects.filter(tenant=tenant).count() + 1
    number = f'{prefix}-{slug}-{count:05d}'
    while model.all_objects.filter(tenant=tenant, number=number).exists():
        count += 1
        number = f'{prefix}-{slug}-{count:05d}'
    return number


def next_movement_number(tenant):
    return _next_number(StockMovement, tenant, 'MOV')


def next_goods_issue_number(tenant):
    return _next_number(GoodsIssue, tenant, 'GI')


def next_cycle_count_number(tenant):
    return _next_number(CycleCount, tenant, 'CC')


# ---------------------------------------------------------------------------
# Masters
# ---------------------------------------------------------------------------
def ensure_default_warehouse(tenant):
    """Return the tenant's default warehouse, creating WH-MAIN on first use if none exists."""
    wh = (Warehouse.all_objects.filter(tenant=tenant, is_default=True, is_active=True).first()
          or Warehouse.all_objects.filter(tenant=tenant, is_active=True).first())
    if wh:
        return wh
    code = getattr(settings, 'INVENTORY_DEFAULT_WAREHOUSE_CODE', 'WH-MAIN')
    return Warehouse.all_objects.create(
        tenant=tenant, code=code, name='Main Warehouse', is_active=True, is_default=True)


def get_or_create_stock_item(tenant, catalog_item):
    """Ensure a :class:`StockItem` profile exists for an (approved) catalog item."""
    si, _ = StockItem.all_objects.get_or_create(
        tenant=tenant, catalog_item=catalog_item,
        defaults={'sku': catalog_item.sku, 'is_stocked': True})
    if not si.sku and catalog_item.sku:
        si.sku = catalog_item.sku
        si.save(update_fields=['sku', 'updated_at'])
    return si


def _resolve_location(tenant, bin_code, default_warehouse):
    """Map a free-text bin code to a (warehouse, location); fall back to the default warehouse."""
    bin_code = (bin_code or '').strip()
    if bin_code:
        loc = WarehouseLocation.all_objects.filter(
            tenant=tenant, code__iexact=bin_code).select_related('warehouse').first()
        if loc:
            return loc.warehouse, loc
    return default_warehouse, None


# ---------------------------------------------------------------------------
# The atomic stock primitive
# ---------------------------------------------------------------------------
@transaction.atomic
def apply_movement(*, tenant, stock_item, warehouse, movement_type, quantity, location=None,
                   to_location=None, unit_cost=None, lot_number='', batch_number='',
                   serial_number='', expiry_date=None, condition='available', actor=None,
                   reason='', note='', source_goods_receipt_line=None, goods_issue_line=None,
                   cycle_count_line=None, request=None):
    """Apply one signed stock change atomically and record it on the append-only ledger.

    ``quantity`` is signed (+ in / - out). Upserts the StockLevel bucket, keeps the StockItem on-hand
    roll-up + moving-average cost current, guards against negative stock, and writes a StockMovement.
    """
    quantity = Decimal(quantity).quantize(QTY_Q)
    if quantity == ZERO:
        raise ValidationError('A stock movement must change a non-zero quantity.')

    si = StockItem.all_objects.select_for_update().get(pk=stock_item.pk)

    bucket = (StockLevel.all_objects.select_for_update().filter(
        tenant=tenant, stock_item=si, location=location, lot_number=lot_number,
        batch_number=batch_number, serial_number=serial_number, expiry_date=expiry_date,
        condition=condition).first())
    if bucket is None:
        bucket = StockLevel.all_objects.create(
            tenant=tenant, stock_item=si, warehouse=warehouse, location=location,
            lot_number=lot_number, batch_number=batch_number, serial_number=serial_number,
            expiry_date=expiry_date, condition=condition, quantity=ZERO)

    new_bucket_qty = (bucket.quantity or ZERO) + quantity
    if new_bucket_qty < ZERO:
        raise ValidationError(
            f'Insufficient stock: {si.sku or si.catalog_item_id} has {bucket.quantity} on hand '
            f'at this location, cannot move {quantity}.')
    new_on_hand = (si.quantity_on_hand or ZERO) + quantity
    if new_on_hand < ZERO:
        raise ValidationError('Movement would drive total on-hand below zero.')

    # Moving-average cost recompute (receipts only — issues/adjustments keep the running average).
    cost = Decimal(unit_cost).quantize(COST_Q) if unit_cost is not None else (
        si.moving_avg_cost or ZERO)
    if movement_type == 'receipt' and quantity > ZERO:
        old_on_hand = si.quantity_on_hand or ZERO
        denom = old_on_hand + quantity
        if denom > ZERO:
            si.moving_avg_cost = (
                (old_on_hand * (si.moving_avg_cost or ZERO) + quantity * cost) / denom
            ).quantize(COST_Q)

    bucket.warehouse = warehouse
    bucket.quantity = new_bucket_qty
    bucket.save(update_fields=['warehouse', 'quantity', 'updated_at'])

    si.quantity_on_hand = new_on_hand
    si.save(update_fields=['quantity_on_hand', 'moving_avg_cost', 'updated_at'])

    mv = StockMovement.all_objects.create(
        tenant=tenant, number=next_movement_number(tenant), movement_type=movement_type,
        stock_item=si, warehouse=warehouse, location=location, to_location=to_location,
        lot_number=lot_number, batch_number=batch_number, serial_number=serial_number,
        expiry_date=expiry_date, quantity=quantity, unit_cost=cost, balance_after=new_on_hand,
        reason=reason[:120], note=note[:255], source_goods_receipt_line=source_goods_receipt_line,
        goods_issue_line=goods_issue_line, cycle_count_line=cycle_count_line, actor=actor)
    record_audit(
        tenant, actor, f'inventory.movement.{movement_type}',
        target_type='StockMovement', target_id=str(mv.id),
        message=f'{mv.number}: {quantity} of {si.sku or si.catalog_item_id} ({movement_type}).',
        request=request)
    return mv


def adjust_stock(stock_item, *, warehouse, quantity, location=None, lot_number='', batch_number='',
                 serial_number='', expiry_date=None, reason='', note='', actor=None, request=None):
    """Record a manual stock adjustment (signed) — the stock-take / correction path."""
    return apply_movement(
        tenant=stock_item.tenant, stock_item=stock_item, warehouse=warehouse,
        movement_type='adjustment', quantity=quantity, location=location, lot_number=lot_number,
        batch_number=batch_number, serial_number=serial_number, expiry_date=expiry_date,
        reason=reason or 'Manual adjustment', note=note, actor=actor, request=request)


def recompute_stock_item(stock_item):
    """Repair the denormalised on-hand / reserved totals from the StockLevel buckets."""
    from django.db.models import Sum
    agg = StockLevel.all_objects.filter(tenant=stock_item.tenant, stock_item=stock_item).aggregate(
        q=Sum('quantity'), r=Sum('reserved_quantity'))
    stock_item.quantity_on_hand = (agg['q'] or ZERO)
    stock_item.quantity_reserved = (agg['r'] or ZERO)
    stock_item.save(update_fields=['quantity_on_hand', 'quantity_reserved', 'updated_at'])
    return stock_item


# ---------------------------------------------------------------------------
# 1. Stock sync from goods receipts (the GRN -> stock seam)
# ---------------------------------------------------------------------------
def _unsynced_receipt_lines(tenant):
    """Posted GRN lines with accepted stock not yet turned into a stock movement."""
    from apps.goods_receipt.models import GoodsReceiptLine
    return (GoodsReceiptLine.all_objects
            .filter(tenant=tenant, goods_receipt__status='posted', accepted_quantity__gt=0)
            .filter(stock_movement__isnull=True)
            .select_related('purchase_order_line', 'goods_receipt'))


def _unsynced_receipt_count(tenant):
    return _unsynced_receipt_lines(tenant).count()


def sync_stock_from_receipts(tenant, *, actor=None):
    """Turn every newly-posted, accepted GRN line into an inbound stock movement.

    Maps a line's PO-line SKU -> approved CatalogItem -> StockItem, resolves the putaway bin from the
    line ``bin_location`` (falling back to the GRN header / default warehouse), and applies a receipt.
    Idempotent via the unique ``StockMovement.source_goods_receipt_line`` watermark. Lines with no SKU
    or no matching approved catalog item are skipped (and counted). Returns ``{received, skipped}``.
    """
    from apps.catalog.models import CatalogItem

    received = skipped = 0
    default_wh = None
    for line in _unsynced_receipt_lines(tenant):
        sku = (getattr(line.purchase_order_line, 'sku', '') or '').strip()
        if not sku:
            skipped += 1
            continue
        catalog_item = (CatalogItem.all_objects
                        .filter(tenant=tenant, sku__iexact=sku, status='approved')
                        .order_by('pk').first())
        if not catalog_item:
            skipped += 1
            continue
        si = get_or_create_stock_item(tenant, catalog_item)
        if default_wh is None:
            default_wh = ensure_default_warehouse(tenant)
        bin_code = line.bin_location or line.goods_receipt.warehouse_location
        warehouse, location = _resolve_location(tenant, bin_code, default_wh)
        apply_movement(
            tenant=tenant, stock_item=si, warehouse=warehouse, location=location,
            movement_type='receipt', quantity=line.accepted_quantity,
            unit_cost=getattr(line.purchase_order_line, 'unit_price', None),
            lot_number=line.lot_number, batch_number=line.batch_number,
            serial_number=line.serial_number, expiry_date=line.expiry_date, actor=actor,
            reason=f'GRN {line.goods_receipt.grn_number}', source_goods_receipt_line=line)
        received += 1
    return {'received': received, 'skipped': skipped}


# ---------------------------------------------------------------------------
# 3. Goods issue / return to stock
# ---------------------------------------------------------------------------
def record_issue_event(goods_issue, from_status, to_status, actor, *, note=''):
    return GoodsIssueStatusEvent.all_objects.create(
        tenant=goods_issue.tenant, goods_issue=goods_issue, from_status=from_status,
        to_status=to_status, actor=actor, note=note)


def create_goods_issue(tenant, *, warehouse, issue_type, user=None, purpose='', department='',
                       cost_center='', note=''):
    """Open a draft goods-issue / return document."""
    gi = GoodsIssue.all_objects.create(
        tenant=tenant, number=next_goods_issue_number(tenant), warehouse=warehouse,
        issue_type=issue_type, purpose=purpose, department=department, cost_center=cost_center,
        note=note, requested_by=user, created_by=user, status='draft')
    record_issue_event(gi, '', 'draft', user, note='Created')
    return gi


def add_goods_issue_line(goods_issue, *, stock_item, quantity, location=None, lot_number='',
                         batch_number='', serial_number='', expiry_date=None, unit_cost=None,
                         note=''):
    """Add a line to a draft goods issue (unit cost defaults to the item's moving average)."""
    if not goods_issue.is_editable:
        raise ValidationError('Only a draft goods issue can be edited.')
    return GoodsIssueLine.all_objects.create(
        tenant=goods_issue.tenant, goods_issue=goods_issue, stock_item=stock_item,
        location=location, lot_number=lot_number, batch_number=batch_number,
        serial_number=serial_number, expiry_date=expiry_date,
        quantity=Decimal(quantity).quantize(QTY_Q),
        unit_cost=(stock_item.moving_avg_cost if unit_cost is None else unit_cost), note=note)


@transaction.atomic
def post_goods_issue(goods_issue, user, *, request=None):
    """Apply a draft goods issue: out for consumption/write-off, in for return-to-stock."""
    gi = GoodsIssue.all_objects.select_for_update().get(pk=goods_issue.pk)
    if not gi.can_post:
        raise ValidationError('Only a draft goods issue with at least one line can be posted.')
    direction = gi.direction
    movement_type = 'return' if gi.is_return else 'issue'
    for line in gi.lines.select_related('stock_item'):
        if not line.unit_cost:
            line.unit_cost = line.stock_item.moving_avg_cost or ZERO
            line.save(update_fields=['unit_cost', 'updated_at'])
        apply_movement(
            tenant=gi.tenant, stock_item=line.stock_item, warehouse=gi.warehouse,
            location=line.location, movement_type=movement_type,
            quantity=(line.quantity or ZERO) * direction, unit_cost=line.unit_cost,
            lot_number=line.lot_number, batch_number=line.batch_number,
            serial_number=line.serial_number, expiry_date=line.expiry_date, actor=user,
            reason=gi.get_issue_type_display(), goods_issue_line=line, request=request)
    gi.status = 'issued'
    gi.issued_by = user
    gi.issued_at = timezone.now()
    gi.save(update_fields=['status', 'issued_by', 'issued_at', 'updated_at'])
    record_issue_event(gi, 'draft', 'issued', user, note='Posted to stock ledger')
    record_audit(
        gi.tenant, user, 'inventory.goods_issue.posted', target_type='GoodsIssue',
        target_id=str(gi.id), message=f'{gi.number} posted ({gi.get_issue_type_display()}).',
        request=request)
    return gi


def cancel_goods_issue(goods_issue, user, *, note='', request=None):
    if not goods_issue.can_cancel:
        raise ValidationError('Only a draft goods issue can be cancelled.')
    from_status = goods_issue.status
    goods_issue.status = 'cancelled'
    goods_issue.save(update_fields=['status', 'updated_at'])
    record_issue_event(goods_issue, from_status, 'cancelled', user, note=note or 'Cancelled')
    record_audit(
        goods_issue.tenant, user, 'inventory.goods_issue.cancelled', target_type='GoodsIssue',
        target_id=str(goods_issue.id), message=f'{goods_issue.number} cancelled.', request=request)
    return goods_issue


# ---------------------------------------------------------------------------
# 5. Cycle counts
# ---------------------------------------------------------------------------
def record_cycle_event(cycle_count, from_status, to_status, actor, *, note=''):
    return CycleCountStatusEvent.all_objects.create(
        tenant=cycle_count.tenant, cycle_count=cycle_count, from_status=from_status,
        to_status=to_status, actor=actor, note=note)


def create_cycle_count(tenant, *, warehouse, scope='full', scheduled_date=None, user=None,
                       note='', abc_class=''):
    """Open a cycle count and snapshot the current on-hand buckets in scope as count lines."""
    cc = CycleCount.all_objects.create(
        tenant=tenant, number=next_cycle_count_number(tenant), warehouse=warehouse, scope=scope,
        scheduled_date=scheduled_date, created_by=user, note=note, status='draft')
    levels = (StockLevel.all_objects
              .filter(tenant=tenant, warehouse=warehouse, quantity__gt=0)
              .select_related('stock_item'))
    if scope == 'abc' and abc_class:
        levels = levels.filter(stock_item__abc_class=abc_class)
    for lvl in levels:
        CycleCountLine.all_objects.create(
            tenant=tenant, cycle_count=cc, stock_item=lvl.stock_item, location=lvl.location,
            lot_number=lvl.lot_number, batch_number=lvl.batch_number,
            serial_number=lvl.serial_number, expiry_date=lvl.expiry_date,
            system_quantity=lvl.quantity, unit_cost=lvl.stock_item.moving_avg_cost or ZERO)
    record_cycle_event(cc, '', 'draft', user, note=f'Snapshot {cc.lines.count()} bucket(s)')
    return cc


def set_cycle_count_line(line, counted_quantity):
    """Record a physically-counted quantity on a count line (moves the count to in-progress)."""
    if not line.cycle_count.is_editable:
        raise ValidationError('This cycle count can no longer be edited.')
    line.counted_quantity = Decimal(counted_quantity).quantize(QTY_Q)
    line.counted = True
    line.save(update_fields=['counted_quantity', 'counted', 'updated_at'])
    cc = line.cycle_count
    if cc.status == 'draft':
        cc.status = 'in_progress'
        cc.save(update_fields=['status', 'updated_at'])
    return line


@transaction.atomic
def post_cycle_count(cycle_count, user, *, request=None):
    """Reconcile counted vs current system quantity and write adjustment movements immediately."""
    cc = CycleCount.all_objects.select_for_update().get(pk=cycle_count.pk)
    if not cc.can_post:
        raise ValidationError('Only a draft/counting cycle count with lines can be posted.')
    from_status = cc.status
    adjustments = 0
    for line in cc.lines.select_related('stock_item'):
        if not line.counted or line.counted_quantity is None:
            continue
        bucket = StockLevel.all_objects.filter(
            tenant=cc.tenant, stock_item=line.stock_item, location=line.location,
            lot_number=line.lot_number, batch_number=line.batch_number,
            serial_number=line.serial_number, expiry_date=line.expiry_date,
            condition='available').first()
        current = bucket.quantity if bucket else ZERO
        variance = (line.counted_quantity - current).quantize(QTY_Q)
        line.variance = variance
        line.save(update_fields=['variance', 'updated_at'])
        if variance != ZERO:
            apply_movement(
                tenant=cc.tenant, stock_item=line.stock_item, warehouse=cc.warehouse,
                location=line.location, movement_type='count_adjustment', quantity=variance,
                unit_cost=line.unit_cost, lot_number=line.lot_number, batch_number=line.batch_number,
                serial_number=line.serial_number, expiry_date=line.expiry_date, actor=user,
                reason=f'Cycle count {cc.number}', cycle_count_line=line, request=request)
            adjustments += 1
    cc.status = 'posted'
    cc.posted_by = user
    cc.posted_at = timezone.now()
    cc.counted_by = cc.counted_by or user
    cc.save(update_fields=['status', 'posted_by', 'posted_at', 'counted_by', 'updated_at'])
    record_cycle_event(cc, from_status, 'posted', user, note=f'{adjustments} adjustment(s)')
    record_audit(
        cc.tenant, user, 'inventory.cycle_count.posted', target_type='CycleCount',
        target_id=str(cc.id),
        message=f'{cc.number} posted — {adjustments} stock adjustment(s).', request=request)
    return cc


def cancel_cycle_count(cycle_count, user, *, note='', request=None):
    if not cycle_count.can_cancel:
        raise ValidationError('Only a draft/counting cycle count can be cancelled.')
    from_status = cycle_count.status
    cycle_count.status = 'cancelled'
    cycle_count.save(update_fields=['status', 'updated_at'])
    record_cycle_event(cycle_count, from_status, 'cancelled', user, note=note or 'Cancelled')
    record_audit(
        cycle_count.tenant, user, 'inventory.cycle_count.cancelled', target_type='CycleCount',
        target_id=str(cycle_count.id), message=f'{cycle_count.number} cancelled.', request=request)
    return cycle_count


# ---------------------------------------------------------------------------
# 2. Reorder-point automation
# ---------------------------------------------------------------------------
def _reorder_user(tenant, actor=None):
    """The user a system-generated requisition is attributed to (requested_by is required)."""
    from apps.accounts.models import User
    if actor and getattr(actor, 'is_authenticated', False):
        return actor
    return (User.objects.filter(tenant=tenant, is_active=True, is_tenant_admin=True).first()
            or User.objects.filter(tenant=tenant, is_active=True).first())


def run_reorder_automation(tenant, *, actor=None, request=None):
    """Raise a DRAFT requisition for every stocked item at/below its reorder point. Idempotent.

    Skips an item that already has an *open* reorder requisition (draft/submitted/approved) so the
    cron can run repeatedly without duplicating. Returns the number of new requisitions created.
    """
    from apps.requisitions.models import Requisition, RequisitionLine
    from apps.requisitions.services import next_requisition_number, record_status_event

    user = _reorder_user(tenant, actor)
    if user is None:
        return 0

    created = 0
    now = timezone.now()
    items = (StockItem.all_objects.filter(tenant=tenant, is_stocked=True)
             .select_related('catalog_item', 'reorder_requisition'))
    for si in items:
        if not si.is_below_reorder or (si.reorder_quantity or ZERO) <= ZERO:
            continue
        existing = si.reorder_requisition
        if existing and existing.status in Requisition.OPEN_STATUSES:
            continue

        with transaction.atomic():
            ci = si.catalog_item
            req = Requisition.all_objects.create(
                tenant=tenant, requested_by=user, number=next_requisition_number(tenant),
                title=f'Auto-reorder: {ci.name}', category='other', priority='high',
                justification=(f'Inventory reorder for {si.sku or ci.item_number}: available '
                               f'{si.available_quantity} at/below reorder point '
                               f'{si.reorder_point}.'),
                status='draft')
            RequisitionLine.all_objects.create(
                tenant=tenant, requisition=req, description=ci.name,
                quantity=si.reorder_quantity, unit=ci.uom,
                unit_price=(si.moving_avg_cost or ci.base_price or ZERO),
                account_code=ci.account_code)
            if hasattr(req, 'recalc_total'):
                req.recalc_total()
            record_status_event(req, '', 'draft', user, note='Auto-generated by inventory reorder')
            si.reorder_requisition = req
            si.last_reordered_at = now
            si.save(update_fields=['reorder_requisition', 'last_reordered_at', 'updated_at'])
            record_audit(
                tenant, user, 'inventory.reorder.created', target_type='Requisition',
                target_id=str(req.id),
                message=(f'Auto-reorder {req.number} for {si.sku or ci.item_number} '
                         f'({si.reorder_quantity} {ci.uom}).'), request=request)
        _notify_managers(
            tenant, f'Reorder raised: {ci.name}',
            f'Stock for {si.sku or ci.item_number} is at/below its reorder point. Draft '
            f'requisition {req.number} created for {si.reorder_quantity} {ci.uom}.',
            link_url='/inventory/reorder/', priority='high', category='deadline')
        created += 1
    return created


# ---------------------------------------------------------------------------
# Notifications helper
# ---------------------------------------------------------------------------
def _notify_managers(tenant, title, message, *, link_url='', priority='normal', category='system'):
    """In-app alert to every active inventory manager in the tenant."""
    from apps.accounts.models import User
    for u in User.objects.filter(tenant=tenant, is_active=True):
        if _has_role(u, MANAGE_ROLES):
            create_notification(
                tenant, u, title, category=category, priority=priority,
                message=message, link_url=link_url)


# ---------------------------------------------------------------------------
# Dashboard metrics
# ---------------------------------------------------------------------------
def tenant_inventory_metrics(tenant):
    """KPI cards + chart series for the inventory dashboard."""
    items = list(StockItem.all_objects.filter(tenant=tenant).select_related('catalog_item'))
    total_value = sum((si.on_hand_value for si in items), ZERO)
    below = [si for si in items if si.is_below_reorder]
    out = [si for si in items if (si.quantity_on_hand or ZERO) <= ZERO and si.is_stocked]

    cutoff = timezone.localdate() + timedelta(
        days=getattr(settings, 'INVENTORY_EXPIRY_ALERT_DAYS', 30))
    near_expiry = StockLevel.all_objects.filter(
        tenant=tenant, quantity__gt=0, expiry_date__isnull=False, expiry_date__lte=cutoff).count()

    # Stock value by warehouse.
    wh_value = {}
    levels = (StockLevel.all_objects.filter(tenant=tenant, quantity__gt=0)
              .select_related('warehouse', 'stock_item'))
    for lvl in levels:
        val = (lvl.quantity or ZERO) * (lvl.stock_item.moving_avg_cost or ZERO)
        key = lvl.warehouse.code if lvl.warehouse_id else '—'
        wh_value[key] = (wh_value.get(key, ZERO) + val)

    # Movement volume by type (last 90 days).
    since = timezone.now() - timedelta(days=90)
    type_counts = {k: 0 for k, _ in StockMovement.TYPE_CHOICES}
    for row in (StockMovement.all_objects.filter(tenant=tenant, created_at__gte=since)
                .values('movement_type').annotate(n=Count('id'))):
        type_counts[row['movement_type']] = row['n']

    top_items = sorted(items, key=lambda s: s.on_hand_value, reverse=True)[:8]

    return {
        'item_count': len(items),
        'total_value': total_value.quantize(QTY_Q),
        'below_reorder_count': len(below),
        'out_of_stock_count': len(out),
        'near_expiry_count': near_expiry,
        'warehouse_count': Warehouse.all_objects.filter(tenant=tenant, is_active=True).count(),
        'unsynced_count': _unsynced_receipt_count(tenant),
        'wh_labels': list(wh_value.keys()),
        'wh_data': [float(v.quantize(QTY_Q)) for v in wh_value.values()],
        'type_labels': [label for _, label in StockMovement.TYPE_CHOICES],
        'type_data': [type_counts[k] for k, _ in StockMovement.TYPE_CHOICES],
        'low_stock_items': sorted(below, key=lambda s: s.available_quantity)[:8],
        'recent_movements': list(
            StockMovement.all_objects.filter(tenant=tenant)
            .select_related('stock_item__catalog_item', 'warehouse')[:8]),
    }


# ---------------------------------------------------------------------------
# Cron sweep (sync receipts + reorder + near-expiry alerts)
# ---------------------------------------------------------------------------
def scan_inventory_alerts(tenant, *, now=None):
    """Cron entry: sync stock from receipts, run reorder automation, raise near-expiry alerts.

    Returns ``{'received', 'reorders', 'expiry_alerts'}``. Idempotent — the receipt sync is
    watermarked, reorder skips open requisitions, and expiry alerts stamp ``expiry_alerted_at``.
    """
    now = now or timezone.now()
    synced = sync_stock_from_receipts(tenant)
    reorders = 0
    if getattr(settings, 'INVENTORY_AUTO_REORDER', True):
        reorders = run_reorder_automation(tenant)

    cutoff = now.date() + timedelta(days=getattr(settings, 'INVENTORY_EXPIRY_ALERT_DAYS', 30))
    expiry_alerts = 0
    expiring = (StockLevel.all_objects.filter(
        tenant=tenant, quantity__gt=0, expiry_date__isnull=False, expiry_date__lte=cutoff,
        expiry_alerted_at__isnull=True).select_related('stock_item__catalog_item'))
    for lvl in expiring:
        si = lvl.stock_item
        _notify_managers(
            tenant, f'Stock expiring soon: {si.name}',
            f'{lvl.quantity} unit(s) of {si.sku or si.catalog_item_id} expire on {lvl.expiry_date}.',
            link_url='/inventory/stock/', priority='high', category='deadline')
        lvl.expiry_alerted_at = now
        lvl.save(update_fields=['expiry_alerted_at', 'updated_at'])
        expiry_alerts += 1

    return {'received': synced['received'], 'reorders': reorders, 'expiry_alerts': expiry_alerts}


def scan_all_tenants():
    """Sweep every tenant. Returns the per-tenant results keyed by slug."""
    results = {}
    for t in Tenant.objects.all():
        set_current_tenant(t)
        results[t.slug] = scan_inventory_alerts(t)
    set_current_tenant(None)
    return results
