"""Module 19 view tests: page loads, CRUD flows, lifecycle actions, permission gating."""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventory.models import CycleCount, GoodsIssue, StockItem, Warehouse

from .conftest import make_stock

pytestmark = pytest.mark.django_db


def test_login_required(client):
    resp = client.get(reverse('inventory:dashboard'))
    assert resp.status_code == 302
    assert '/accounts/login/' in resp.url


def test_dashboard_loads(client, data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.get(reverse('inventory:dashboard'))
    assert resp.status_code == 200


def test_stock_list_and_detail(client, data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '30', tenant_admin)
    client.force_login(tenant_admin)
    assert client.get(reverse('inventory:stock_list')).status_code == 200
    assert client.get(reverse('inventory:stock_item_detail', args=[si.pk])).status_code == 200


def test_stock_list_below_filter(client, data, tenant_admin):
    make_stock(data.tenant, data.ci, data.wh, data.loc, '5', tenant_admin,
               reorder_point='10', reorder_quantity='20')
    client.force_login(tenant_admin)
    resp = client.get(reverse('inventory:stock_list') + '?show=below')
    assert resp.status_code == 200
    assert len(resp.context['items']) == 1


def test_warehouse_create(client, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('inventory:warehouse_create'),
                       {'code': 'WH-X', 'name': 'Extra', 'is_active': 'on'})
    assert resp.status_code == 302
    assert Warehouse.objects.filter(tenant=tenant_admin.tenant, code='WH-X').exists()


def test_stock_adjust_action(client, data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '10', tenant_admin)
    client.force_login(tenant_admin)
    resp = client.post(reverse('inventory:stock_item_adjust', args=[si.pk]),
                       {'warehouse': data.wh.pk, 'location': data.loc.pk,
                        'quantity': '5', 'reason': 'found'})
    assert resp.status_code == 302
    si.refresh_from_db()
    assert si.quantity_on_hand == Decimal('15.00')


def test_goods_issue_full_flow(client, data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '20', tenant_admin)
    client.force_login(tenant_admin)
    # create
    resp = client.post(reverse('inventory:goods_issue_create'),
                       {'warehouse': data.wh.pk, 'issue_type': 'consumption'})
    assert resp.status_code == 302
    gi = GoodsIssue.objects.filter(tenant=data.tenant).latest('id')
    # add line
    client.post(reverse('inventory:goods_issue_line_add', args=[gi.pk]),
                {'stock_item': si.pk, 'quantity': '6', 'location': data.loc.pk})
    assert gi.lines.count() == 1
    # post
    client.post(reverse('inventory:goods_issue_post', args=[gi.pk]))
    gi.refresh_from_db()
    si.refresh_from_db()
    assert gi.status == 'issued'
    assert si.quantity_on_hand == Decimal('14.00')


def test_cycle_count_flow(client, data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '40', tenant_admin)
    client.force_login(tenant_admin)
    resp = client.post(reverse('inventory:cycle_count_create'),
                       {'warehouse': data.wh.pk, 'scope': 'full'})
    assert resp.status_code == 302
    cc = CycleCount.objects.filter(tenant=data.tenant).latest('id')
    line = cc.lines.first()
    client.post(reverse('inventory:cycle_count_count', args=[cc.pk]),
                {f'count_{line.pk}': '38'})
    client.post(reverse('inventory:cycle_count_post', args=[cc.pk]))
    cc.refresh_from_db()
    si.refresh_from_db()
    assert cc.status == 'posted'
    assert si.quantity_on_hand == Decimal('38.00')


def test_reorder_run(client, data, tenant_admin):
    make_stock(data.tenant, data.ci, data.wh, data.loc, '5', tenant_admin,
               reorder_point='10', reorder_quantity='25')
    client.force_login(tenant_admin)
    assert client.get(reverse('inventory:reorder_board')).status_code == 200
    resp = client.post(reverse('inventory:reorder_run'))
    assert resp.status_code == 302
    si = StockItem.objects.get(tenant=data.tenant, catalog_item=data.ci)
    assert si.reorder_requisition is not None


def test_movement_list_loads(client, data, tenant_admin):
    make_stock(data.tenant, data.ci, data.wh, data.loc, '10', tenant_admin)
    client.force_login(tenant_admin)
    assert client.get(reverse('inventory:movement_list')).status_code == 200


def test_requester_bounced(client, data, requester):
    client.force_login(requester)
    assert client.get(reverse('inventory:dashboard')).status_code == 302
    assert client.get(reverse('inventory:stock_list')).status_code == 302


# ---------- Stock item CRUD ----------
def test_stock_item_create(client, data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('inventory:stock_item_create'), {
        'catalog_item': data.ci2.pk, 'is_stocked': 'on', 'reorder_point': '0',
        'reorder_quantity': '0', 'safety_stock': '0', 'lead_time_days': '0'})
    assert resp.status_code == 302
    si = StockItem.objects.get(tenant=data.tenant, catalog_item=data.ci2)
    assert si.sku == data.ci2.sku


def test_stock_item_edit(client, data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '5', tenant_admin)
    client.force_login(tenant_admin)
    resp = client.post(reverse('inventory:stock_item_edit', args=[si.pk]), {
        'is_stocked': 'on', 'reorder_point': '15', 'reorder_quantity': '30',
        'safety_stock': '5', 'lead_time_days': '3'})
    assert resp.status_code == 302
    si.refresh_from_db()
    assert si.reorder_point == Decimal('15.00')


def test_stock_item_delete_without_movements(client, data, tenant_admin):
    from apps.inventory import services
    si = services.get_or_create_stock_item(data.tenant, data.ci2)  # no movements
    client.force_login(tenant_admin)
    resp = client.post(reverse('inventory:stock_item_delete', args=[si.pk]))
    assert resp.status_code == 302
    assert not StockItem.objects.filter(pk=si.pk).exists()


# ---------- Warehouse & location CRUD ----------
def test_warehouse_edit_and_detail(client, data, tenant_admin):
    client.force_login(tenant_admin)
    assert client.get(reverse('inventory:warehouse_detail', args=[data.wh.pk])).status_code == 200
    resp = client.post(reverse('inventory:warehouse_edit', args=[data.wh.pk]),
                       {'code': data.wh.code, 'name': 'Renamed', 'is_active': 'on'})
    assert resp.status_code == 302
    data.wh.refresh_from_db()
    assert data.wh.name == 'Renamed'


def test_warehouse_delete_empty(client, tenant_admin):
    client.force_login(tenant_admin)
    client.post(reverse('inventory:warehouse_create'), {'code': 'TMP', 'name': 'Tmp', 'is_active': 'on'})
    wh = Warehouse.objects.get(tenant=tenant_admin.tenant, code='TMP')
    resp = client.post(reverse('inventory:warehouse_delete', args=[wh.pk]))
    assert resp.status_code == 302
    assert not Warehouse.objects.filter(pk=wh.pk).exists()


def test_location_crud(client, data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('inventory:location_create'),
                       {'warehouse': data.wh.pk, 'code': 'C-9-9', 'is_active': 'on'})
    assert resp.status_code == 302
    from apps.inventory.models import WarehouseLocation
    loc = WarehouseLocation.objects.get(tenant=data.tenant, code='C-9-9')
    client.post(reverse('inventory:location_edit', args=[loc.pk]),
                {'warehouse': data.wh.pk, 'code': 'C-9-9', 'aisle': 'C', 'is_active': 'on'})
    loc.refresh_from_db()
    assert loc.aisle == 'C'
    resp = client.post(reverse('inventory:location_delete', args=[loc.pk]))
    assert resp.status_code == 302
    assert not WarehouseLocation.objects.filter(pk=loc.pk).exists()


# ---------- Goods issue lifecycle branches ----------
def test_goods_issue_detail_edit_cancel(client, data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '10', tenant_admin)
    gi = GoodsIssue.objects.create(
        tenant=data.tenant, number='GI-T1', warehouse=data.wh, issue_type='consumption',
        status='draft')
    client.force_login(tenant_admin)
    assert client.get(reverse('inventory:goods_issue_detail', args=[gi.pk])).status_code == 200
    # add then delete a line
    client.post(reverse('inventory:goods_issue_line_add', args=[gi.pk]),
                {'stock_item': si.pk, 'quantity': '2', 'location': data.loc.pk})
    line = gi.lines.first()
    client.post(reverse('inventory:goods_issue_line_delete', args=[gi.pk, line.pk]))
    assert gi.lines.count() == 0
    # edit header
    client.post(reverse('inventory:goods_issue_edit', args=[gi.pk]),
                {'warehouse': data.wh.pk, 'issue_type': 'write_off', 'purpose': 'scrap'})
    gi.refresh_from_db()
    assert gi.issue_type == 'write_off'
    # cancel
    client.post(reverse('inventory:goods_issue_cancel', args=[gi.pk]))
    gi.refresh_from_db()
    assert gi.status == 'cancelled'


def test_goods_issue_delete_draft(client, data, tenant_admin):
    gi = GoodsIssue.objects.create(
        tenant=data.tenant, number='GI-T2', warehouse=data.wh, issue_type='consumption',
        status='draft')
    client.force_login(tenant_admin)
    resp = client.post(reverse('inventory:goods_issue_delete', args=[gi.pk]))
    assert resp.status_code == 302
    assert not GoodsIssue.objects.filter(pk=gi.pk).exists()


# ---------- Cycle count lifecycle branches ----------
def test_cycle_count_detail_edit_cancel_delete(client, data, tenant_admin):
    make_stock(data.tenant, data.ci, data.wh, data.loc, '12', tenant_admin)
    client.force_login(tenant_admin)
    client.post(reverse('inventory:cycle_count_create'), {'warehouse': data.wh.pk, 'scope': 'full'})
    cc = CycleCount.objects.filter(tenant=data.tenant).latest('id')
    assert client.get(reverse('inventory:cycle_count_detail', args=[cc.pk])).status_code == 200
    client.post(reverse('inventory:cycle_count_edit', args=[cc.pk]),
                {'warehouse': data.wh.pk, 'scope': 'location', 'note': 'spot'})
    cc.refresh_from_db()
    assert cc.scope == 'location'
    client.post(reverse('inventory:cycle_count_cancel', args=[cc.pk]))
    cc.refresh_from_db()
    assert cc.status == 'cancelled'


def test_movement_detail_loads(client, data, tenant_admin):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '5', tenant_admin)
    from apps.inventory.models import StockMovement
    mv = StockMovement.objects.filter(tenant=data.tenant, stock_item=si).first()
    client.force_login(tenant_admin)
    assert client.get(reverse('inventory:movement_detail', args=[mv.pk])).status_code == 200


def test_form_pages_render(client, data, tenant_admin):
    """GET every create/edit page so the crispy form templates are exercised."""
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '5', tenant_admin)
    from apps.inventory import services
    gi = services.create_goods_issue(
        data.tenant, warehouse=data.wh, issue_type='consumption', user=tenant_admin)
    cc = services.create_cycle_count(data.tenant, warehouse=data.wh, scope='full', user=tenant_admin)
    client.force_login(tenant_admin)
    pages = [
        reverse('inventory:stock_item_create'),
        reverse('inventory:stock_item_edit', args=[si.pk]),
        reverse('inventory:warehouse_create'),
        reverse('inventory:warehouse_edit', args=[data.wh.pk]),
        reverse('inventory:location_create') + f'?warehouse={data.wh.pk}',
        reverse('inventory:location_edit', args=[data.loc.pk]),
        reverse('inventory:goods_issue_create'),
        reverse('inventory:goods_issue_edit', args=[gi.pk]),
        reverse('inventory:cycle_count_create'),
        reverse('inventory:cycle_count_edit', args=[cc.pk]),
    ]
    for url in pages:
        assert client.get(url).status_code == 200, url


def test_list_pages_render(client, data, tenant_admin):
    """GET every list page so the remaining list templates are exercised."""
    client.force_login(tenant_admin)
    for name in ('warehouse_list', 'goods_issue_list', 'cycle_count_list', 'movement_list',
                 'stock_list', 'reorder_board'):
        assert client.get(reverse(f'inventory:{name}')).status_code == 200, name
