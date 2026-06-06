"""Shared fixtures for Module 16 (Budget & Cost Management) tests.

Consumption is computed on read, so the fixtures build *source* data with explicit account codes:
an active FY2026 budget allocating $1,000 to cost centre ``100-IT``, an open PO committing $300, an
approved invoice actualising $200, and a submitted requisition reserving $100 against the same
cost centre. Expected consumption: actual 200, committed 300, reserved 100, available 400.

Each fixture CREATES its own data (never mutates another) per lessons.md.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.invoicing.models import SupplierInvoice, SupplierInvoiceLine
from apps.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from apps.requisitions.models import AccountCode, Requisition, RequisitionLine
from apps.vendors.models import Vendor, VendorCategory

from apps.budget.models import Budget, BudgetAllocation, BudgetPeriod


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
def procurement_manager(db, tenant):
    return User.objects.create_user(
        username='pmgr', password='x', tenant=tenant, role='procurement_manager')


@pytest.fixture
def approver(db, tenant):
    """View-only role: may view budgets but not manage."""
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
        role='tenant_admin', is_tenant_admin=True)


# ---------- Source-data builder ----------
def build_budget(tenant, user, *, allocated=Decimal('1000.00'), budget_status='active'):
    set_current_tenant(tenant)
    cat = VendorCategory.all_objects.create(tenant=tenant, name='IT Equipment', code='IT')
    acct = AccountCode.all_objects.create(tenant=tenant, code='100-IT', name='IT Capex')
    acct2 = AccountCode.all_objects.create(tenant=tenant, code='200-OFF', name='Office Supplies')
    vendor = Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-1', legal_name='Supplier', status='active',
        category=cat)

    period = BudgetPeriod.all_objects.create(
        tenant=tenant, name='FY2026', period_type='annual',
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), status='active')
    budget = Budget.all_objects.create(
        tenant=tenant, budget_number='BUD-ACME-00001', name='Operating budget',
        period=period, status=budget_status, owner=user, created_by=user,
        total_allocated=allocated)
    alloc = BudgetAllocation.all_objects.create(
        tenant=tenant, budget=budget, line_no=1, account_code=acct, allocated_amount=allocated)

    # committed $300 — an open (issued) PO line on 100-IT, in-period.
    po = PurchaseOrder.all_objects.create(
        tenant=tenant, po_number='PO-1', title='Servers', vendor=vendor, currency='USD',
        status='issued', order_date=date(2026, 2, 1), created_by=user, owner=user)
    PurchaseOrderLine.all_objects.create(
        tenant=tenant, purchase_order=po, line_no=1, description='Server',
        quantity=Decimal('3'), unit_price=Decimal('100.00'), account_code=acct)

    # actual $200 — an approved invoice line on 100-IT, in-period.
    inv = SupplierInvoice.all_objects.create(
        tenant=tenant, invoice_number='SINV-1', vendor=vendor, purchase_order=po,
        status='approved', invoice_date=date(2026, 3, 1), currency='USD',
        subtotal=Decimal('200.00'), total_amount=Decimal('200.00'))
    SupplierInvoiceLine.all_objects.create(
        tenant=tenant, supplier_invoice=inv, account_code=acct, line_no=1, description='Server',
        quantity=Decimal('2'), unit_price=Decimal('100.00'))

    # reserved $100 — a submitted requisition line on 100-IT, in-period.
    req = Requisition.all_objects.create(
        tenant=tenant, requested_by=user, number='REQ-1', title='Need servers',
        status='submitted', required_date=date(2026, 4, 1))
    RequisitionLine.all_objects.create(
        tenant=tenant, requisition=req, description='Server', quantity=Decimal('1'),
        unit_price=Decimal('100.00'), account_code=acct)

    return SimpleNamespace(
        tenant=tenant, category=cat, account_code=acct, account_code2=acct2, vendor=vendor,
        period=period, budget=budget, allocation=alloc, po=po, inv=inv, req=req)


def make_requisition(tenant, user, amount, account_code, *, status='draft', number='REQ-9'):
    """A helper requisition with one line of ``amount`` on ``account_code``."""
    set_current_tenant(tenant)
    req = Requisition.all_objects.create(
        tenant=tenant, requested_by=user, number=number, title='Request',
        status=status, required_date=date(2026, 6, 1))
    RequisitionLine.all_objects.create(
        tenant=tenant, requisition=req, description='Thing', quantity=Decimal('1'),
        unit_price=Decimal(str(amount)), account_code=account_code)
    return req


@pytest.fixture
def budget_data(db, tenant, tenant_admin):
    return build_budget(tenant, tenant_admin)
