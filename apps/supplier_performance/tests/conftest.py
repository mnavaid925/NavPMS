"""Shared fixtures for Module 17 (Supplier Performance & Evaluation) tests.

Source data is created at FIXED dates inside ``PERIOD`` so KPI-computation assertions are
deterministic (no reliance on "today").
"""
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant
from apps.goods_receipt.models import GoodsReceipt, GoodsReceiptLine
from apps.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from apps.supplier_performance import services
from apps.supplier_performance.models import KpiDefinition, PerformanceFeedback
from apps.vendors.models import Vendor

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 3, 31)
IN_PERIOD = date(2026, 2, 15)
OUT_OF_PERIOD = date(2025, 6, 1)


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
    )


@pytest.fixture
def buyer_user(db, tenant):
    return User.objects.create_user(
        username='buyer', password='x', tenant=tenant, role='buyer',
    )


@pytest.fixture
def procurement_manager(db, tenant):
    """Manage-role user WITHOUT is_tenant_admin (exercises the role-membership branch)."""
    return User.objects.create_user(
        username='pmgr', password='x', tenant=tenant, role='procurement_manager',
    )


@pytest.fixture
def evaluator(db, tenant):
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
        legal_name='Acme IT Solutions', status='active',
    )


@pytest.fixture
def vendor_b(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00002',
        legal_name='Beacon Cleaners', status='active',
    )


@pytest.fixture
def blocked_vendor(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-09999',
        legal_name='Blocked Co', status='blacklisted',
    )


@pytest.fixture
def vendor_portal_user(db, tenant, vendor_a):
    return User.objects.create_user(
        username='portal_a', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_a,
    )


# ---------- KPIs ----------

@pytest.fixture
def kpis(db, tenant):
    services.ensure_default_kpis(tenant)
    return list(KpiDefinition.all_objects.filter(tenant=tenant))


# ---------- Source-data factories ----------

@pytest.fixture
def make_po(db):
    def _make(tenant, vendor, *, expected_delivery_date=PERIOD_END, status='issued',
              issued_at=None, acknowledged_at=None, number='PO-T-0001'):
        return PurchaseOrder.all_objects.create(
            tenant=tenant, vendor=vendor, po_number=number, title='Test PO',
            status=status, expected_delivery_date=expected_delivery_date,
            issued_at=issued_at, acknowledged_at=acknowledged_at,
        )
    return _make


@pytest.fixture
def make_grn(db):
    def _make(tenant, vendor, po, *, received_date=IN_PERIOD, status='posted',
              number='GRN-T-0001'):
        return GoodsReceipt.all_objects.create(
            tenant=tenant, vendor=vendor, purchase_order=po, grn_number=number,
            status=status, received_date=received_date,
        )
    return _make


@pytest.fixture
def make_grn_line(db):
    def _make(tenant, grn, po, *, received_quantity=Decimal('10'),
              rejected_quantity=Decimal('0'), line_no=1):
        po_line = PurchaseOrderLine.all_objects.create(
            tenant=tenant, purchase_order=po, line_no=line_no, description='Widget')
        return GoodsReceiptLine.all_objects.create(
            tenant=tenant, goods_receipt=grn, purchase_order_line=po_line, line_no=line_no,
            received_quantity=received_quantity, rejected_quantity=rejected_quantity,
            accepted_quantity=received_quantity - rejected_quantity)
    return _make


@pytest.fixture
def make_feedback(db):
    def _make(tenant, vendor, rating, *, submitted_on=IN_PERIOD, status='submitted'):
        submitted_at = timezone.make_aware(datetime.combine(submitted_on, time(12, 0)))
        return PerformanceFeedback.all_objects.create(
            tenant=tenant, vendor=vendor, rating=rating, status=status,
            submitted_at=submitted_at if status == 'submitted' else None,
            quality_rating=rating, delivery_rating=rating, communication_rating=rating)
    return _make
