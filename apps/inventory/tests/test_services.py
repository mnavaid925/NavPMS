"""Module 19 service tests: movements, moving-average, sync, goods issue, cycle count, reorder."""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models import set_current_tenant
from apps.requisitions.models import Requisition

from apps.inventory import services
from apps.inventory.models import StockMovement

from .conftest import make_stock

pytestmark = pytest.mark.django_db


# ---------- Permissions ----------
def test_permission_matrix(tenant_admin, buyer_user, approver, requester):
    assert services.can_manage_inventory(tenant_admin)
    assert services.can_manage_inventory(buyer_user)
    assert not services.can_manage_inventory(approver)
    assert services.can_view_inventory(approver)
    assert not services.can_view_inventory(requester)
    assert not services.can_manage_inventory(requester)


# ---------- apply_movement + moving average ----------
def test_apply_movement_updates_on_hand_and_ledger(data, tenant_admin):
    si = services.get_or_create_stock_item(data.tenant, data.ci)
    mv = services.apply_movement(
        tenant=data.tenant, stock_item=si, warehouse=data.wh, location=data.loc,
        movement_type='adjustment', quantity=Decimal('40'), unit_cost=Decimal('5'),
        actor=tenant_admin)
    si.refresh_from_db()
    assert si.quantity_on_hand == Decimal('40.00')
    assert mv.balance_after == Decimal('40.00')
    assert StockMovement.all_objects.filter(tenant=data.tenant, stock_item=si).count() == 1


def test_moving_average_recompute_on_receipt(data, tenant_admin):
    si = services.get_or_create_stock_item(data.tenant, data.ci)
    # 10 @ 2.00, then 10 @ 4.00 -> weighted average 3.00.
    services.apply_movement(
        tenant=data.tenant, stock_item=si, warehouse=data.wh, location=data.loc,
        movement_type='receipt', quantity=Decimal('10'), unit_cost=Decimal('2'), actor=tenant_admin)
    services.apply_movement(
        tenant=data.tenant, stock_item=si, warehouse=data.wh, location=data.loc,
        movement_type='receipt', quantity=Decimal('10'), unit_cost=Decimal('4'), actor=tenant_admin)
    si.refresh_from_db()
    assert si.quantity_on_hand == Decimal('20.00')
    assert si.moving_avg_cost == Decimal('3.0000')


def test_issue_does_not_change_moving_average(data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '10', tenant_admin,
                    unit_cost=Decimal('3'))
    # opening adjustment is not a receipt, so set avg manually then issue.
    si.moving_avg_cost = Decimal('3.0000')
    si.save()
    services.apply_movement(
        tenant=data.tenant, stock_item=si, warehouse=data.wh, location=data.loc,
        movement_type='issue', quantity=Decimal('-4'), actor=tenant_admin)
    si.refresh_from_db()
    assert si.quantity_on_hand == Decimal('6.00')
    assert si.moving_avg_cost == Decimal('3.0000')


def test_negative_stock_guard(data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '5', tenant_admin)
    with pytest.raises(ValidationError):
        services.apply_movement(
            tenant=data.tenant, stock_item=si, warehouse=data.wh, location=data.loc,
            movement_type='issue', quantity=Decimal('-9'), actor=tenant_admin)


def test_zero_quantity_movement_rejected(data, tenant_admin):
    si = services.get_or_create_stock_item(data.tenant, data.ci)
    with pytest.raises(ValidationError):
        services.apply_movement(
            tenant=data.tenant, stock_item=si, warehouse=data.wh, location=data.loc,
            movement_type='adjustment', quantity=Decimal('0'), actor=tenant_admin)


# ---------- GRN -> stock sync ----------
def test_sync_from_receipts_is_idempotent(data, tenant_admin):
    first = services.sync_stock_from_receipts(data.tenant, actor=tenant_admin)
    assert first['received'] == 1
    si = services.get_or_create_stock_item(data.tenant, data.ci)
    assert si.quantity_on_hand == Decimal('5.00')
    # Second run folds in nothing (the watermark blocks re-sync).
    second = services.sync_stock_from_receipts(data.tenant, actor=tenant_admin)
    assert second['received'] == 0
    si.refresh_from_db()
    assert si.quantity_on_hand == Decimal('5.00')


def test_sync_skips_unmatched_sku(data, tenant_admin):
    # Point the PO line at a SKU that has no approved catalog item.
    data.poline.sku = 'NO-SUCH-SKU'
    data.poline.save()
    result = services.sync_stock_from_receipts(data.tenant, actor=tenant_admin)
    assert result['received'] == 0
    assert result['skipped'] == 1


# ---------- Goods issue ----------
def test_post_goods_issue_consumption_reduces_stock(data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '20', tenant_admin)
    gi = services.create_goods_issue(
        data.tenant, warehouse=data.wh, issue_type='consumption', user=tenant_admin)
    services.add_goods_issue_line(gi, stock_item=si, quantity=Decimal('7'), location=data.loc)
    services.post_goods_issue(gi, tenant_admin)
    gi.refresh_from_db()
    si.refresh_from_db()
    assert gi.status == 'issued'
    assert si.quantity_on_hand == Decimal('13.00')


def test_post_goods_issue_return_adds_stock(data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '5', tenant_admin)
    gi = services.create_goods_issue(
        data.tenant, warehouse=data.wh, issue_type='return_to_stock', user=tenant_admin)
    services.add_goods_issue_line(gi, stock_item=si, quantity=Decimal('3'), location=data.loc)
    services.post_goods_issue(gi, tenant_admin)
    si.refresh_from_db()
    assert si.quantity_on_hand == Decimal('8.00')


def test_post_empty_goods_issue_rejected(data, tenant_admin):
    gi = services.create_goods_issue(
        data.tenant, warehouse=data.wh, issue_type='consumption', user=tenant_admin)
    with pytest.raises(ValidationError):
        services.post_goods_issue(gi, tenant_admin)


# ---------- Cycle count ----------
def test_cycle_count_posts_immediate_adjustment(data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '50', tenant_admin)
    cc = services.create_cycle_count(data.tenant, warehouse=data.wh, scope='full', user=tenant_admin)
    line = cc.lines.first()
    assert line is not None and line.system_quantity == Decimal('50.00')
    services.set_cycle_count_line(line, Decimal('47'))   # counted 3 short
    services.post_cycle_count(cc, tenant_admin)
    cc.refresh_from_db()
    si.refresh_from_db()
    line.refresh_from_db()
    assert cc.status == 'posted'
    assert line.variance == Decimal('-3.00')
    assert si.quantity_on_hand == Decimal('47.00')
    assert StockMovement.all_objects.filter(
        tenant=data.tenant, movement_type='count_adjustment').count() == 1


# ---------- Reorder automation ----------
def test_reorder_creates_draft_requisition_and_is_idempotent(data, tenant_admin):
    # On-hand 5, reorder point 10 -> below; reorder qty 40.
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '5', tenant_admin,
                    reorder_point='10', reorder_quantity='40')
    created = services.run_reorder_automation(data.tenant, actor=tenant_admin)
    assert created == 1
    si.refresh_from_db()
    req = si.reorder_requisition
    assert req is not None and req.status == 'draft'
    assert req.title.startswith('Auto-reorder')
    assert req.lines.count() == 1
    line = req.lines.first()
    assert line.quantity == Decimal('40.00')
    # Second run does nothing while the reorder requisition is still open.
    assert services.run_reorder_automation(data.tenant, actor=tenant_admin) == 0


def test_reorder_reraises_after_requisition_closed(data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '5', tenant_admin,
                    reorder_point='10', reorder_quantity='40')
    assert services.run_reorder_automation(data.tenant, actor=tenant_admin) == 1
    si.refresh_from_db()
    # Close the requisition (e.g. cancelled) -> a fresh reorder may be raised.
    req = si.reorder_requisition
    req.status = 'cancelled'
    req.save(update_fields=['status'])
    assert services.run_reorder_automation(data.tenant, actor=tenant_admin) == 1


def test_reorder_skips_items_in_stock(data, tenant_admin):
    make_stock(data.tenant, data.ci, data.wh, data.loc, '100', tenant_admin,
               reorder_point='10', reorder_quantity='40')
    assert services.run_reorder_automation(data.tenant, actor=tenant_admin) == 0
    assert not Requisition.all_objects.filter(
        tenant=data.tenant, title__startswith='Auto-reorder').exists()


# ---------- Dashboard metrics ----------
def test_metrics_smoke(data, tenant_admin):
    make_stock(data.tenant, data.ci, data.wh, data.loc, '30', tenant_admin)
    m = services.tenant_inventory_metrics(data.tenant)
    assert m['item_count'] >= 1
    assert m['warehouse_count'] >= 1
    assert 'wh_labels' in m and 'type_data' in m


# ---------- Cancels / repair / cron ----------
def test_cancel_goods_issue(data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '10', tenant_admin)
    gi = services.create_goods_issue(
        data.tenant, warehouse=data.wh, issue_type='consumption', user=tenant_admin)
    services.add_goods_issue_line(gi, stock_item=si, quantity=Decimal('2'), location=data.loc)
    services.cancel_goods_issue(gi, tenant_admin)
    gi.refresh_from_db()
    assert gi.status == 'cancelled'
    # A cancelled issue can't be posted.
    with pytest.raises(ValidationError):
        services.post_goods_issue(gi, tenant_admin)


def test_cancel_cycle_count(data, tenant_admin):
    make_stock(data.tenant, data.ci, data.wh, data.loc, '10', tenant_admin)
    cc = services.create_cycle_count(data.tenant, warehouse=data.wh, scope='full', user=tenant_admin)
    services.cancel_cycle_count(cc, tenant_admin)
    cc.refresh_from_db()
    assert cc.status == 'cancelled'
    with pytest.raises(ValidationError):
        services.post_cycle_count(cc, tenant_admin)


def test_recompute_stock_item(data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '10', tenant_admin)
    # Corrupt the denormalised total, then repair it from the buckets.
    si.quantity_on_hand = Decimal('999')
    si.save(update_fields=['quantity_on_hand'])
    services.recompute_stock_item(si)
    si.refresh_from_db()
    assert si.quantity_on_hand == Decimal('10.00')


def test_ensure_default_warehouse_creates_one(tenant):
    set_current_tenant(tenant)
    wh = services.ensure_default_warehouse(tenant)
    assert wh.is_default is True
    # Idempotent — returns the same warehouse.
    assert services.ensure_default_warehouse(tenant).pk == wh.pk


def test_scan_inventory_alerts(data, tenant_admin):
    # Below-reorder item (reorder), a posted GRN line (sync), and a near-expiry lot (alert).
    si = make_stock(data.tenant, data.ci2, data.wh, data.loc, '5', tenant_admin,
                    reorder_point='10', reorder_quantity='20')
    from datetime import timedelta
    from django.utils import timezone
    services.apply_movement(
        tenant=data.tenant, stock_item=si, warehouse=data.wh, location=data.loc,
        movement_type='adjustment', quantity=Decimal('5'), lot_number='EXP',
        expiry_date=timezone.localdate() + timedelta(days=5), actor=tenant_admin)
    result = services.scan_inventory_alerts(data.tenant)
    assert result['received'] == 1        # the seeded posted GRN line
    assert result['reorders'] == 1        # ci2 below reorder
    assert result['expiry_alerts'] == 1   # the near-expiry lot
    # Idempotent second pass: nothing new.
    again = services.scan_inventory_alerts(data.tenant)
    assert again['received'] == 0 and again['reorders'] == 0 and again['expiry_alerts'] == 0
