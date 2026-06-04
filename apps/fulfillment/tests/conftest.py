"""Shared fixtures for Module 12 (Order Fulfillment & Tracking) tests.

Mirrors ``apps/purchase_orders/tests/conftest.py``: tenants & users, vendors (+ portal
users), an acknowledged PO to ship against, then shipment fixtures.

Per lessons.md, every fixture CREATES its own row through the real services
(``create_shipment`` / ``add_shipment_line`` / ``advise_shipment``) — ``advised_shipment``
builds a fresh shipment rather than mutating ``draft_shipment`` in place, so status-filter
tests are never poisoned.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.fulfillment import services as fs
from apps.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from apps.purchase_orders.services import acknowledge_po, issue_po, recompute_totals
from apps.vendors.models import Vendor


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
        role='tenant_admin', is_tenant_admin=True, email='ada@acme.test',
    )


@pytest.fixture
def buyer_user(db, tenant):
    return User.objects.create_user(
        username='buyer', password='x', tenant=tenant, role='buyer',
    )


@pytest.fixture
def procurement_manager(db, tenant):
    return User.objects.create_user(
        username='pmgr', password='x', tenant=tenant, role='procurement_manager',
    )


@pytest.fixture
def approver(db, tenant):
    return User.objects.create_user(
        username='approver_user', password='x', tenant=tenant, role='approver',
    )


@pytest.fixture
def requester(db, tenant):
    return User.objects.create_user(
        username='requester', password='x', tenant=tenant, role='requester',
    )


@pytest.fixture
def intruder(db, other_tenant):
    return User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant,
        role='tenant_admin', is_tenant_admin=True,
    )


# ---------- Vendors ----------

@pytest.fixture
def vendor_a(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00001',
        legal_name='Acme IT Solutions', status='active', email='a@vend.test',
    )


@pytest.fixture
def vendor_b(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00002',
        legal_name='Beacon Cleaners', status='active', email='b@vend.test',
    )


@pytest.fixture
def vendor_portal_user(db, tenant, vendor_a):
    u = User.objects.create_user(
        username='portal_a', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_a,
    )
    vendor_a.portal_user = u
    vendor_a.save(update_fields=['portal_user'])
    return u


@pytest.fixture
def vendor_b_portal_user(db, tenant, vendor_b):
    u = User.objects.create_user(
        username='portal_b', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_b,
    )
    vendor_b.portal_user = u
    vendor_b.save(update_fields=['portal_user'])
    return u


# ---------- Purchase orders (acknowledged → receivable) ----------

def _make_acknowledged_po(tenant, user, vendor, *, number, lines):
    today = timezone.localdate()
    po = PurchaseOrder.all_objects.create(
        tenant=tenant, po_number=number, title='Test PO', vendor=vendor,
        currency='USD', status='draft', created_by=user, owner=user,
        order_date=today, expected_delivery_date=today + timedelta(days=20),
    )
    for i, (desc, uom, qty, price) in enumerate(lines, start=1):
        PurchaseOrderLine.all_objects.create(
            tenant=tenant, purchase_order=po, line_no=i, description=desc,
            uom=uom, quantity=qty, unit_price=price,
        )
    recompute_totals(po)
    po.refresh_from_db()
    issue_po(po, user, dispatch_method='portal')
    po.refresh_from_db()
    acknowledge_po(po, user)
    po.refresh_from_db()
    return po


@pytest.fixture
def issued_po(db, tenant, tenant_admin, vendor_a):
    """Acknowledged PO for vendor_a with two lines (qty 10 and 4)."""
    set_current_tenant(tenant)
    return _make_acknowledged_po(
        tenant, tenant_admin, vendor_a, number='PO-ACME-00010',
        lines=[('Widget', 'unit', Decimal('10'), Decimal('25.00')),
               ('Gadget', 'unit', Decimal('4'), Decimal('50.00'))],
    )


@pytest.fixture
def issued_po_b(db, tenant, tenant_admin, vendor_b):
    """Acknowledged PO for vendor_b (single line) — for cross-vendor isolation."""
    set_current_tenant(tenant)
    return _make_acknowledged_po(
        tenant, tenant_admin, vendor_b, number='PO-ACME-00011',
        lines=[('Bolt', 'unit', Decimal('100'), Decimal('1.00'))],
    )


# ---------- Shipments ----------

def _build_shipment(tenant, user, po, *, qty, tracking='TRK1', ship_in=-2, eta_in=2,
                    line_index=0):
    s = fs.create_shipment(
        tenant=tenant, user=user, purchase_order=po,
        carrier='Swift Freight', carrier_code='mock', tracking_number=tracking,
        ship_date=timezone.localdate() + timedelta(days=ship_in),
        estimated_delivery_date=timezone.localdate() + timedelta(days=eta_in),
    )
    pol = po.lines.order_by('line_no')[line_index]
    fs.add_shipment_line(s, purchase_order_line=pol, shipped_quantity=Decimal(qty))
    s.refresh_from_db()
    return s


@pytest.fixture
def draft_shipment(db, tenant, tenant_admin, issued_po):
    set_current_tenant(tenant)
    return _build_shipment(tenant, tenant_admin, issued_po, qty='4')


@pytest.fixture
def advised_shipment(db, tenant, tenant_admin, issued_po):
    """A freshly-built shipment driven to 'advised' (its own row, not draft_shipment)."""
    set_current_tenant(tenant)
    s = _build_shipment(tenant, tenant_admin, issued_po, qty='4', tracking='TRK2')
    fs.advise_shipment(s, tenant_admin)
    s.refresh_from_db()
    return s


@pytest.fixture
def shipment_b(db, tenant, tenant_admin, issued_po_b):
    set_current_tenant(tenant)
    return _build_shipment(tenant, tenant_admin, issued_po_b, qty='20', tracking='TRKB')
