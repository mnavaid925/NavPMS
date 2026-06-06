"""Shared fixtures for Module 15 (Spend Analytics & Reporting) tests.

The spend fact table is derived, so the fixtures build *source* data (an approved invoice with a
PO-linked line for a preferred, on-contract vendor; an approved invoice with an off-PO line for a
non-preferred, off-contract vendor; a non-cancelled PO for committed spend) and then run
``sync_spend_facts``. Each fixture CREATES its own data (never mutates another) per lessons.md.

Expected after sync (actual basis): 2 records, 1 maverick (the non-preferred / off-contract /
off-PO invoice line). Committed basis: 1 record, 0 maverick.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.contracts.models import Contract
from apps.core.models import Tenant, set_current_tenant
from apps.invoicing.models import SupplierInvoice, SupplierInvoiceLine
from apps.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from apps.requisitions.models import AccountCode
from apps.vendors.models import Vendor, VendorCategory, VendorSegment

from apps.spend_analytics import services
from apps.spend_analytics.models import SpendReport

SPEND_DATE = date(2026, 1, 15)


@pytest.fixture(autouse=True)
def _reset_tenant():
    """Clear the thread-local tenant after each test so it can't leak across tests."""
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
        role='tenant_admin', is_tenant_admin=True, email='ada@acme.test',
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
    """View-only role: may view analytics/reports but not manage."""
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

def build_spend_data(tenant, user):
    """Create source invoices/POs/contract for ``tenant`` and sync the fact table.

    Returns a SimpleNamespace with the key objects + the sync counts.
    """
    set_current_tenant(tenant)
    cat_a = VendorCategory.all_objects.create(tenant=tenant, name='IT Equipment', code='IT')
    cat_b = VendorCategory.all_objects.create(tenant=tenant, name='Office Supplies', code='OFF')
    seg_pref = VendorSegment.all_objects.create(tenant=tenant, name='Preferred', code='preferred')
    seg_tac = VendorSegment.all_objects.create(tenant=tenant, name='Tactical', code='tactical')
    acct = AccountCode.all_objects.create(tenant=tenant, code='100-IT', name='IT Capex')

    vendor_pref = Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-1', legal_name='Preferred Supplier',
        status='active', category=cat_a, segment=seg_pref)
    vendor_nonpref = Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-2', legal_name='Maverick Supplier',
        status='active', category=cat_b, segment=seg_tac)

    # Active contract covering SPEND_DATE for the preferred vendor only.
    Contract.all_objects.create(
        tenant=tenant, contract_number='CON-1', title='MSA', vendor=vendor_pref,
        status='active', start_date=date(2025, 1, 1), end_date=date(2027, 1, 1),
        currency='USD', value=Decimal('10000'))

    # Committed spend — a non-cancelled PO for the preferred vendor.
    po = PurchaseOrder.all_objects.create(
        tenant=tenant, po_number='PO-1', title='Servers', vendor=vendor_pref,
        category=cat_a, currency='USD', status='issued', order_date=SPEND_DATE,
        created_by=user, owner=user)
    po_line = PurchaseOrderLine.all_objects.create(
        tenant=tenant, purchase_order=po, line_no=1, description='Server',
        quantity=Decimal('5'), unit_price=Decimal('20.00'), account_code=acct)  # line_total 100

    # Actual spend #1 — approved invoice, PO-linked line, preferred + on-contract -> NOT maverick.
    inv1 = SupplierInvoice.all_objects.create(
        tenant=tenant, invoice_number='SINV-1', vendor=vendor_pref, purchase_order=po,
        status='approved', invoice_date=SPEND_DATE, currency='USD',
        subtotal=Decimal('100.00'), total_amount=Decimal('100.00'))
    SupplierInvoiceLine.all_objects.create(
        tenant=tenant, supplier_invoice=inv1, purchase_order_line=po_line, account_code=acct,
        line_no=1, description='Server', quantity=Decimal('5'), unit_price=Decimal('20.00'))

    # Actual spend #2 — approved invoice, NO PO line, non-preferred + off-contract -> maverick.
    inv2 = SupplierInvoice.all_objects.create(
        tenant=tenant, invoice_number='SINV-2', vendor=vendor_nonpref,
        status='paid', invoice_date=SPEND_DATE, currency='USD',
        subtotal=Decimal('250.00'), total_amount=Decimal('250.00'))
    SupplierInvoiceLine.all_objects.create(
        tenant=tenant, supplier_invoice=inv2, account_code=acct,
        line_no=1, description='Pens', quantity=Decimal('100'), unit_price=Decimal('2.50'))

    counts = services.sync_spend_facts(tenant)
    return SimpleNamespace(
        tenant=tenant, cat_a=cat_a, cat_b=cat_b, seg_pref=seg_pref, seg_tac=seg_tac,
        account_code=acct, vendor_pref=vendor_pref, vendor_nonpref=vendor_nonpref,
        po=po, po_line=po_line, inv1=inv1, inv2=inv2, counts=counts)


@pytest.fixture
def spend_data(db, tenant, tenant_admin):
    return build_spend_data(tenant, tenant_admin)


@pytest.fixture
def shared_report(db, tenant, tenant_admin):
    set_current_tenant(tenant)
    return SpendReport.all_objects.create(
        tenant=tenant, name='Shared category report', dimension='vendor_category',
        measure='amount_sum', chart_type='bar', basis='actual', is_shared=True,
        owner=tenant_admin)


@pytest.fixture
def private_report(db, tenant, tenant_admin):
    set_current_tenant(tenant)
    return SpendReport.all_objects.create(
        tenant=tenant, name='Private vendor report', dimension='vendor',
        measure='amount_sum', chart_type='bar', basis='actual', is_shared=False,
        owner=tenant_admin)
