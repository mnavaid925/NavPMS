"""Shared fixtures for Module 11 (Purchase Order Management) tests.

Mirrors the layout/style of ``apps/contracts/tests/conftest.py``: tenants & users,
vendors, then PO fixtures.

IMPORTANT (per lessons.md): every PO fixture CREATES its own row — we never build
``acknowledged_po`` by mutating ``draft_po`` in place (that would poison status-filter
tests). Lifecycle fixtures call ``set_current_tenant`` first, then drive the real
services (``issue_po`` / ``acknowledge_po`` / ``record_line_receipt``) so the seeded
state is honest, refreshing the instance after each step.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from apps.purchase_orders.services import (
    acknowledge_po,
    issue_po,
    recompute_totals,
    record_line_receipt,
)
from apps.requisitions.models import Requisition, RequisitionLine
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
        role='tenant_admin', is_tenant_admin=True,
        first_name='Ada', last_name='Admin', email='ada@acme.test',
    )


@pytest.fixture
def buyer_user(db, tenant):
    return User.objects.create_user(
        username='buyer', password='x', tenant=tenant, role='buyer',
    )


@pytest.fixture
def procurement_manager(db, tenant):
    """Manage-role user WITHOUT is_tenant_admin, exercising the MANAGE_ROLES branch."""
    return User.objects.create_user(
        username='pmgr', password='x', tenant=tenant, role='procurement_manager',
    )


@pytest.fixture
def approver(db, tenant):
    """View-only role: may view analytics but not manage."""
    return User.objects.create_user(
        username='approver_user', password='x', tenant=tenant, role='approver',
    )


@pytest.fixture
def requester(db, tenant):
    """Neither manage nor view."""
    return User.objects.create_user(
        username='requester', password='x', tenant=tenant, role='requester',
    )


@pytest.fixture
def intruder(db, other_tenant):
    """Tenant admin of a DIFFERENT tenant — used for cross-tenant isolation."""
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
def blocked_vendor(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-09999',
        legal_name='Blocked Co', status='blacklisted',
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


# ---------- Account code ----------

@pytest.fixture
def account_code(db, tenant):
    from apps.requisitions.models import AccountCode
    return AccountCode.all_objects.create(
        tenant=tenant, code='5000', name='Procurement', is_active=True,
    )


# ---------- Purchase orders ----------

def _make_po(tenant, user, vendor, *, number, lines=None, delivery_in=20,
             tax=Decimal('0.00'), shipping=Decimal('0.00')):
    today = timezone.localdate()
    po = PurchaseOrder.all_objects.create(
        tenant=tenant, po_number=number, title='Test purchase order',
        vendor=vendor, currency='USD', status='draft', created_by=user, owner=user,
        order_date=today, expected_delivery_date=today + timedelta(days=delivery_in),
        tax_amount=tax, shipping_amount=shipping,
    )
    lines = lines or [('Widget', 'unit', Decimal('10'), Decimal('25.00'))]
    for i, (desc, uom, qty, price) in enumerate(lines, start=1):
        PurchaseOrderLine.all_objects.create(
            tenant=tenant, purchase_order=po, line_no=i, description=desc,
            uom=uom, quantity=qty, unit_price=price,
        )
    recompute_totals(po)
    po.refresh_from_db()
    return po


@pytest.fixture
def draft_po(db, tenant, tenant_admin, vendor_a):
    """A draft PO with two line items, supplier assigned."""
    set_current_tenant(tenant)
    return _make_po(
        tenant, tenant_admin, vendor_a, number='PO-ACME-00001',
        lines=[('Server', 'unit', Decimal('2'), Decimal('4000.00')),
               ('Rails', 'set', Decimal('2'), Decimal('150.00'))],
    )


@pytest.fixture
def draft_po_no_vendor(db, tenant, tenant_admin):
    """A draft PO with lines but no supplier yet (cannot be issued)."""
    set_current_tenant(tenant)
    po = PurchaseOrder.all_objects.create(
        tenant=tenant, po_number='PO-ACME-09001', title='No-vendor PO',
        status='draft', created_by=tenant_admin, owner=tenant_admin, currency='USD',
    )
    PurchaseOrderLine.all_objects.create(
        tenant=tenant, purchase_order=po, line_no=1, description='X',
        quantity=Decimal('1'), unit_price=Decimal('5.00'),
    )
    recompute_totals(po)
    po.refresh_from_db()
    return po


@pytest.fixture
def issued_po(db, tenant, tenant_admin, vendor_a):
    set_current_tenant(tenant)
    po = _make_po(tenant, tenant_admin, vendor_a, number='PO-ACME-00002')
    issue_po(po, tenant_admin, dispatch_method='portal')
    po.refresh_from_db()
    return po


@pytest.fixture
def acknowledged_po(db, tenant, tenant_admin, vendor_a):
    set_current_tenant(tenant)
    po = _make_po(tenant, tenant_admin, vendor_a, number='PO-ACME-00003')
    issue_po(po, tenant_admin, dispatch_method='portal')
    po.refresh_from_db()
    acknowledge_po(po, tenant_admin)
    po.refresh_from_db()
    return po


@pytest.fixture
def received_po(db, tenant, tenant_admin, vendor_a):
    """A single-line PO issued, acknowledged and fully received (closeable)."""
    set_current_tenant(tenant)
    po = _make_po(
        tenant, tenant_admin, vendor_a, number='PO-ACME-00004',
        lines=[('Laptop', 'unit', Decimal('4'), Decimal('1000.00'))],
    )
    issue_po(po, tenant_admin, dispatch_method='portal')
    po.refresh_from_db()
    acknowledge_po(po, tenant_admin)
    po.refresh_from_db()
    line = po.lines.first()
    record_line_receipt(po, line, line.quantity, tenant_admin)
    po.refresh_from_db()
    return po


@pytest.fixture
def approved_requisition(db, tenant, tenant_admin, account_code):
    """An approved requisition with two lines, ready to convert to a PO."""
    set_current_tenant(tenant)
    req = Requisition.all_objects.create(
        tenant=tenant, requested_by=tenant_admin, number='REQ-ACME-00001',
        title='Office chairs', status='approved', currency='USD',
    )
    RequisitionLine.all_objects.create(
        tenant=tenant, requisition=req, description='Ergonomic chair',
        quantity=Decimal('5'), unit='unit', unit_price=Decimal('200.00'),
        account_code=account_code,
    )
    RequisitionLine.all_objects.create(
        tenant=tenant, requisition=req, description='Footrest',
        quantity=Decimal('5'), unit='unit', unit_price=Decimal('25.00'),
    )
    return req
