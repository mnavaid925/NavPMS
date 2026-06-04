"""Shared fixtures for Module 13 (Goods Receipt & Inspection) tests.

Mirrors ``apps/purchase_orders/tests/conftest.py``: tenants & users, vendors, an open
(acknowledged) PO to receive against, then GRN/RTV fixtures.

IMPORTANT (per lessons.md): every GRN fixture CREATES its own PO + GRN — we never build
``posted_grn`` by mutating ``draft_grn`` in place (that would poison status-filter tests).
Lifecycle fixtures call ``set_current_tenant`` first, then drive the real services so the
seeded state is honest, refreshing the instance after each step.
"""
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from apps.purchase_orders.services import acknowledge_po, issue_po, recompute_totals
from apps.vendors.models import Vendor

from apps.goods_receipt import services as grn_services


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


# ---------- Open purchase order to receive against ----------

def make_open_po(tenant, user, vendor, *, number, lines=None):
    """Create + issue + acknowledge a PO so its status is in PO_CHANGE_ORDERABLE_STATUSES."""
    po = PurchaseOrder.all_objects.create(
        tenant=tenant, po_number=number, title='Receivable PO',
        vendor=vendor, currency='USD', status='draft', created_by=user, owner=user,
    )
    lines = lines or [('Server', 'unit', Decimal('10'), Decimal('100.00')),
                      ('Cable', 'unit', Decimal('8'), Decimal('5.00'))]
    for i, (desc, uom, qty, price) in enumerate(lines, start=1):
        PurchaseOrderLine.all_objects.create(
            tenant=tenant, purchase_order=po, line_no=i, description=desc,
            uom=uom, quantity=qty, unit_price=price,
        )
    recompute_totals(po)
    issue_po(po, user, dispatch_method='portal')
    po.refresh_from_db()
    acknowledge_po(po, user)
    po.refresh_from_db()
    return po


@pytest.fixture
def open_po(db, tenant, tenant_admin, vendor_a):
    set_current_tenant(tenant)
    return make_open_po(tenant, tenant_admin, vendor_a, number='PO-ACME-00001')


# ---------- GRN fixtures (each builds its own PO) ----------

def _build_grn(tenant, user, vendor, *, po_number, received_per_line=Decimal('6')):
    """Create a draft GRN with a received line per PO line."""
    po = make_open_po(tenant, user, vendor, number=po_number)
    grn = grn_services.create_goods_receipt(
        tenant=tenant, user=user, purchase_order=po,
        delivery_note_ref='DN-1', warehouse_location='Main')
    for pol in po.lines.all():
        grn_services.add_receipt_line(
            grn, purchase_order_line=pol, received_quantity=received_per_line)
    grn.refresh_from_db()
    return grn


@pytest.fixture
def draft_grn(db, tenant, tenant_admin, vendor_a):
    set_current_tenant(tenant)
    return _build_grn(tenant, tenant_admin, vendor_a, po_number='PO-ACME-10001')


@pytest.fixture
def received_grn(db, tenant, tenant_admin, vendor_a):
    set_current_tenant(tenant)
    grn = _build_grn(tenant, tenant_admin, vendor_a, po_number='PO-ACME-10002')
    grn_services.mark_received(grn, tenant_admin)
    grn.refresh_from_db()
    return grn


def _inspect_all(grn, user, *, accepted, rejected, discrepancy='none', reason=''):
    line_results = {
        ln.id: {'accepted': accepted, 'rejected': rejected,
                'discrepancy': discrepancy, 'reason': reason}
        for ln in grn.lines.all()
    }
    checks = [{'criterion': 'no_damage', 'result': 'pass'}]
    grn_services.record_inspection(grn, user, checks=checks, line_results=line_results)
    grn.refresh_from_db()
    return grn


@pytest.fixture
def inspected_grn(db, tenant, tenant_admin, vendor_a):
    """Received then inspected with a mixed accept (4) / reject (2) split per line."""
    set_current_tenant(tenant)
    grn = _build_grn(tenant, tenant_admin, vendor_a, po_number='PO-ACME-10003')
    grn_services.mark_received(grn, tenant_admin)
    grn.refresh_from_db()
    return _inspect_all(
        grn, tenant_admin, accepted=Decimal('4'), rejected=Decimal('2'),
        discrepancy='damaged', reason='Damaged')


@pytest.fixture
def posted_grn(db, tenant, tenant_admin, vendor_a):
    """Received, fully accepted, and posted to the PO (tags generated)."""
    set_current_tenant(tenant)
    grn = _build_grn(tenant, tenant_admin, vendor_a, po_number='PO-ACME-10004')
    grn_services.mark_received(grn, tenant_admin)
    grn.refresh_from_db()
    _inspect_all(grn, tenant_admin, accepted=Decimal('6'), rejected=Decimal('0'))
    grn_services.post_goods_receipt(grn, tenant_admin)
    grn.refresh_from_db()
    return grn


@pytest.fixture
def grn_with_rtv(db, tenant, tenant_admin, vendor_a):
    """An inspected GRN with rejections plus an authorised Return-to-Vendor."""
    set_current_tenant(tenant)
    grn = _build_grn(tenant, tenant_admin, vendor_a, po_number='PO-ACME-10005')
    grn_services.mark_received(grn, tenant_admin)
    grn.refresh_from_db()
    _inspect_all(
        grn, tenant_admin, accepted=Decimal('4'), rejected=Decimal('2'),
        discrepancy='damaged', reason='Damaged')
    rtv = grn_services.create_rtv_from_rejections(grn, tenant_admin, reason='Damaged')
    grn_services.authorize_rtv(rtv, tenant_admin)
    rtv.refresh_from_db()
    grn.refresh_from_db()
    return grn, rtv
