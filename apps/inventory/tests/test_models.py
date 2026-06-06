"""Module 19 model tests: numbering, properties, badge colours, constraints."""
from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.core.models import set_current_tenant

from apps.inventory import services
from apps.inventory.models import GoodsIssue, StockItem, StockLevel, Warehouse, WarehouseLocation

from .conftest import build_inventory

pytestmark = pytest.mark.django_db


def test_number_formats(tenant):
    set_current_tenant(tenant)
    assert services.next_movement_number(tenant).startswith('MOV-ACME-')
    assert services.next_goods_issue_number(tenant).startswith('GI-ACME-')
    assert services.next_cycle_count_number(tenant).startswith('CC-ACME-')
    assert services.next_movement_number(tenant).endswith('00001')


def test_stock_item_available_and_status(data):
    si = services.get_or_create_stock_item(data.tenant, data.ci)
    si.quantity_on_hand = Decimal('30')
    si.quantity_reserved = Decimal('5')
    si.reorder_point = Decimal('10')
    si.save()
    assert si.available_quantity == Decimal('25')
    assert si.is_below_reorder is False
    assert si.stock_status == 'ok'
    assert si.stock_status_color == 'success'


def test_stock_item_below_reorder_and_out(data):
    si = services.get_or_create_stock_item(data.tenant, data.ci)
    si.quantity_on_hand = Decimal('8')
    si.reorder_point = Decimal('10')
    si.save()
    assert si.is_below_reorder is True
    assert si.stock_status == 'low'
    assert si.stock_status_color == 'warning'

    si.quantity_on_hand = Decimal('0')
    si.save()
    assert si.stock_status == 'out'
    assert si.stock_status_color == 'danger'


def test_on_hand_value(data):
    si = services.get_or_create_stock_item(data.tenant, data.ci)
    si.quantity_on_hand = Decimal('10')
    si.moving_avg_cost = Decimal('2.5000')
    si.save()
    assert si.on_hand_value == Decimal('25.00')


def test_stock_level_available(data):
    si = services.get_or_create_stock_item(data.tenant, data.ci)
    lvl = StockLevel.all_objects.create(
        tenant=data.tenant, stock_item=si, warehouse=data.wh, location=data.loc,
        quantity=Decimal('12'), reserved_quantity=Decimal('2'))
    assert lvl.available == Decimal('10')


def test_goods_issue_direction(tenant):
    set_current_tenant(tenant)
    wh = Warehouse.all_objects.create(tenant=tenant, code='W1', name='W1')
    out = GoodsIssue.all_objects.create(
        tenant=tenant, number='GI-1', warehouse=wh, issue_type='consumption')
    ret = GoodsIssue.all_objects.create(
        tenant=tenant, number='GI-2', warehouse=wh, issue_type='return_to_stock')
    assert out.direction == -1 and out.is_return is False
    assert ret.direction == 1 and ret.is_return is True
    assert out.status_color == 'secondary'


def test_warehouse_code_unique_per_tenant(tenant):
    set_current_tenant(tenant)
    Warehouse.all_objects.create(tenant=tenant, code='DUP', name='One')
    with pytest.raises(IntegrityError):
        Warehouse.all_objects.create(tenant=tenant, code='DUP', name='Two')


def test_warehouse_location_label(tenant):
    set_current_tenant(tenant)
    wh = Warehouse.all_objects.create(tenant=tenant, code='W1', name='W1')
    loc = WarehouseLocation.all_objects.create(
        tenant=tenant, warehouse=wh, code='A-1', aisle='A', rack='1', shelf='2')
    assert 'A' in loc.label and '1' in loc.label


def test_same_code_allowed_across_tenants(tenant, other_tenant):
    set_current_tenant(tenant)
    Warehouse.all_objects.create(tenant=tenant, code='WH', name='A')
    # Same code in a different tenant must be allowed (tenant-scoped uniqueness).
    Warehouse.all_objects.create(tenant=other_tenant, code='WH', name='B')
    assert Warehouse.all_objects.filter(code='WH').count() == 2
