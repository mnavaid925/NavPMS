"""Shared fixtures for Module 14 (Invoice & Voucher Management) tests.

Mirrors ``apps/goods_receipt/tests/conftest.py``: tenants & users, vendors, a received PO to
bill against (received qty posted via the real ``record_line_receipt``, exactly as the GRN /
fulfilment paths do), then invoice fixtures.

IMPORTANT (per lessons.md): every invoice fixture CREATES its own PO + invoice — we never
build ``approved_invoice`` by mutating ``draft_invoice`` in place. Lifecycle fixtures call
``set_current_tenant`` first, then drive the real services, refreshing after each step.
"""
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from apps.purchase_orders import services as po_services
from apps.vendors.models import Vendor

from apps.invoicing import services as inv_services
from apps.invoicing.models import PaymentTerm


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
        username='buyer', password='x', tenant=tenant, role='buyer')


@pytest.fixture
def procurement_manager(db, tenant):
    return User.objects.create_user(
        username='pmgr', password='x', tenant=tenant, role='procurement_manager')


@pytest.fixture
def approver(db, tenant):
    return User.objects.create_user(
        username='approver_user', password='x', tenant=tenant, role='approver')


@pytest.fixture
def requester(db, tenant):
    return User.objects.create_user(
        username='requester', password='x', tenant=tenant, role='requester')


@pytest.fixture
def intruder(db, other_tenant):
    return User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant,
        role='tenant_admin', is_tenant_admin=True)


# ---------- Vendors ----------

@pytest.fixture
def vendor_a(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00001',
        legal_name='Acme IT Solutions', status='active', email='a@vend.test')


@pytest.fixture
def vendor_b(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00002',
        legal_name='Beacon Cleaners', status='active', email='b@vend.test')


@pytest.fixture
def blocked_vendor(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-09999',
        legal_name='Blocked Co', status='blacklisted')


@pytest.fixture
def vendor_portal_user(db, tenant, vendor_a):
    u = User.objects.create_user(
        username='portal_a', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_a)
    vendor_a.portal_user = u
    vendor_a.save(update_fields=['portal_user'])
    return u


@pytest.fixture
def vendor_b_portal_user(db, tenant, vendor_b):
    u = User.objects.create_user(
        username='portal_b', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_b)
    vendor_b.portal_user = u
    vendor_b.save(update_fields=['portal_user'])
    return u


# ---------- Payment terms ----------

@pytest.fixture
def payment_term(db, tenant):
    return PaymentTerm.all_objects.create(
        tenant=tenant, code='NET30', name='Net 30', net_days=30)


@pytest.fixture
def discount_term(db, tenant):
    return PaymentTerm.all_objects.create(
        tenant=tenant, code='2-10-NET30', name='2/10 Net 30', net_days=30,
        discount_percent=Decimal('2.00'), discount_days=10)


# ---------- Purchase orders (received, to bill against) ----------

def make_open_po(tenant, user, vendor, *, number, lines=None):
    """Create + issue + acknowledge a PO so it is in PO_CHANGE_ORDERABLE_STATUSES."""
    po = PurchaseOrder.all_objects.create(
        tenant=tenant, po_number=number, title='Billable PO',
        vendor=vendor, currency='USD', status='draft', created_by=user, owner=user)
    lines = lines or [('Server', 'unit', Decimal('10'), Decimal('100.00')),
                      ('Cable', 'unit', Decimal('8'), Decimal('5.00'))]
    for i, (desc, uom, qty, price) in enumerate(lines, start=1):
        PurchaseOrderLine.all_objects.create(
            tenant=tenant, purchase_order=po, line_no=i, description=desc,
            uom=uom, quantity=qty, unit_price=price)
    po_services.recompute_totals(po)
    po_services.issue_po(po, user, dispatch_method='portal')
    po.refresh_from_db()
    po_services.acknowledge_po(po, user)
    po.refresh_from_db()
    return po


def make_received_po(tenant, user, vendor, *, number, received=Decimal('6'), lines=None):
    """An acknowledged PO with ``received`` posted to every line (as a GRN/ASN would)."""
    po = make_open_po(tenant, user, vendor, number=number, lines=lines)
    for pol in po.lines.all():
        po_services.record_line_receipt(po, pol, received, user)
    po.refresh_from_db()
    return po


@pytest.fixture
def received_po(db, tenant, tenant_admin, vendor_a):
    set_current_tenant(tenant)
    return make_received_po(tenant, tenant_admin, vendor_a, number='PO-ACME-00001')


# ---------- Invoice fixtures (each builds its own received PO) ----------

def build_invoice(tenant, user, vendor, *, po_number, term=None,
                  price_factor=Decimal('1'), received=Decimal('6')):
    """Create a draft invoice billing the received qty of a freshly-received PO."""
    po = make_received_po(tenant, user, vendor, number=po_number, received=received)
    inv = inv_services.create_invoice(
        tenant=tenant, user=user, vendor=vendor, purchase_order=po, payment_term=term,
        currency='USD', invoice_date=timezone.localdate(), supplier_invoice_ref='SUP-1')
    for pol in po.lines.all():
        inv_services.add_invoice_line(
            inv, purchase_order_line=pol, quantity=pol.received_quantity,
            unit_price=(pol.unit_price * price_factor))
    inv_services.recompute_invoice_totals(inv)
    inv.refresh_from_db()
    return inv


@pytest.fixture
def draft_invoice(db, tenant, tenant_admin, vendor_a, payment_term):
    set_current_tenant(tenant)
    return build_invoice(tenant, tenant_admin, vendor_a,
                         po_number='PO-ACME-10001', term=payment_term)


@pytest.fixture
def submitted_invoice(db, tenant, tenant_admin, vendor_a, payment_term):
    set_current_tenant(tenant)
    inv = build_invoice(tenant, tenant_admin, vendor_a,
                        po_number='PO-ACME-10002', term=payment_term)
    inv_services.submit_invoice(inv, tenant_admin)
    inv.refresh_from_db()
    return inv


@pytest.fixture
def approved_invoice(db, tenant, tenant_admin, vendor_a, payment_term):
    set_current_tenant(tenant)
    inv = build_invoice(tenant, tenant_admin, vendor_a,
                        po_number='PO-ACME-10003', term=payment_term)
    inv_services.submit_invoice(inv, tenant_admin)
    inv.refresh_from_db()
    inv_services.approve_invoice(inv, tenant_admin)
    inv.refresh_from_db()
    return inv
