"""Shared fixtures for Module 19 (Inventory & Warehouse) tests.

``build_inventory`` creates the upstream masters an inventory test needs — a vendor, two approved
catalog items, a warehouse + bin, and a *posted* goods receipt line whose PO-line SKU matches a
catalog item (so ``sync_stock_from_receipts`` has something to fold in). ``make_stock`` is a helper
that gives a catalog item an on-hand opening balance via the real service.

Each fixture CREATES its own data (never mutates another) per lessons.md, using ``.all_objects`` to
bypass tenant scoping and an autouse reset of the thread-local tenant.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.core.models import Tenant, set_current_tenant
from apps.goods_receipt.models import GoodsReceipt, GoodsReceiptLine
from apps.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from apps.vendors.models import Vendor, VendorCategory

from apps.inventory import services
from apps.inventory.models import Warehouse, WarehouseLocation


@pytest.fixture(autouse=True)
def _reset_tenant():
    yield
    set_current_tenant(None)


# ---------- Tenants & users ----------
@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name='Acme Co', slug='acme')


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name='Globex', slug='globex')


@pytest.fixture
def tenant_admin(db, tenant):
    return User.objects.create_user(
        username='admin_acme', password='x', tenant=tenant,
        role='tenant_admin', is_tenant_admin=True, email='ada@acme.test')


@pytest.fixture
def buyer_user(db, tenant):
    return User.objects.create_user(username='buyer', password='x', tenant=tenant, role='buyer')


@pytest.fixture
def approver(db, tenant):
    """View-only role: may view inventory but not manage."""
    return User.objects.create_user(
        username='approver_user', password='x', tenant=tenant, role='approver')


@pytest.fixture
def requester(db, tenant):
    """Neither manage nor view — must be bounced from every page (the D-01 lesson)."""
    return User.objects.create_user(
        username='requester', password='x', tenant=tenant, role='requester')


@pytest.fixture
def intruder(db, other_tenant):
    """Tenant admin of a DIFFERENT tenant — used for cross-tenant isolation."""
    return User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant,
        role='tenant_admin', is_tenant_admin=True, email='m@globex.test')


# ---------- Source-data builder ----------
def build_inventory(tenant, user):
    set_current_tenant(tenant)
    cat = VendorCategory.all_objects.create(tenant=tenant, name='Parts', code='PARTS')
    vendor = Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-1', legal_name='Acme Supplies', status='active',
        category=cat)
    ci = CatalogItem.all_objects.create(
        tenant=tenant, item_number='CAT-1', name='Widget', sku='WIDGET-1', uom='each',
        base_price=Decimal('10.0000'), status='approved', is_active=True)
    ci2 = CatalogItem.all_objects.create(
        tenant=tenant, item_number='CAT-2', name='Gadget', sku='GADGET-1', uom='each',
        base_price=Decimal('4.0000'), status='approved', is_active=True)
    wh = Warehouse.all_objects.create(
        tenant=tenant, code='WH-MAIN', name='Main', is_default=True, is_active=True)
    loc = WarehouseLocation.all_objects.create(tenant=tenant, warehouse=wh, code='A-01-01')

    # A posted goods-receipt line (PO-line SKU matches WIDGET-1) ready for sync.
    po = PurchaseOrder.all_objects.create(
        tenant=tenant, po_number='PO-1', title='Buy widgets', vendor=vendor, currency='USD',
        status='issued', order_date=date(2026, 6, 1), total_amount=Decimal('50.00'),
        created_by=user, owner=user)
    poline = PurchaseOrderLine.all_objects.create(
        tenant=tenant, purchase_order=po, line_no=1, description='Widget', sku='WIDGET-1',
        uom='each', quantity=Decimal('5.00'), unit_price=Decimal('10.00'))
    grn = GoodsReceipt.all_objects.create(
        tenant=tenant, grn_number='GRN-1', purchase_order=po, vendor=vendor, status='posted')
    grn_line = GoodsReceiptLine.all_objects.create(
        tenant=tenant, goods_receipt=grn, purchase_order_line=poline, line_no=1,
        received_quantity=Decimal('5.00'), accepted_quantity=Decimal('5.00'),
        posted_quantity=Decimal('5.00'), lot_number='L1')

    return SimpleNamespace(tenant=tenant, vendor=vendor, ci=ci, ci2=ci2, wh=wh, loc=loc,
                           po=po, poline=poline, grn=grn, grn_line=grn_line)


def make_stock(tenant, catalog_item, warehouse, location, qty, user, *, unit_cost=None,
               reorder_point=None, reorder_quantity=None, lot_number=''):
    """Create/return a StockItem for ``catalog_item`` and give it an opening on-hand balance."""
    si = services.get_or_create_stock_item(tenant, catalog_item)
    if reorder_point is not None:
        si.reorder_point = Decimal(reorder_point)
    if reorder_quantity is not None:
        si.reorder_quantity = Decimal(reorder_quantity)
    si.save()
    if qty:
        services.apply_movement(
            tenant=tenant, stock_item=si, warehouse=warehouse, location=location,
            movement_type='adjustment', quantity=Decimal(qty),
            unit_cost=(unit_cost if unit_cost is not None else catalog_item.base_price),
            lot_number=lot_number, actor=user, reason='Opening balance')
    return services.get_or_create_stock_item(tenant, catalog_item)


@pytest.fixture
def data(db, tenant, tenant_admin):
    return build_inventory(tenant, tenant_admin)
