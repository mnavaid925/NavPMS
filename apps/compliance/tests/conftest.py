"""Shared fixtures for Module 18 (Risk & Compliance) tests.

``build_compliance`` creates source data that deliberately trips each fraud detector:
  * two vendors sharing one bank account            -> vendor_bank_conflict
  * a restricted-party entry matching vendor 1's name -> a screening hit
  * an approval rule (ceiling 1000) + two 800 POs to one vendor by one buyer -> split_po
  * a 5000 PO                                          -> round_amount
  * two 250 invoices sharing a reference              -> duplicate_invoice

Each fixture CREATES its own data (never mutates another) per lessons.md, using ``.all_objects`` to
bypass tenant scoping and an autouse reset of the thread-local tenant.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.approvals.models import ApprovalRule
from apps.core.models import Tenant, set_current_tenant
from apps.invoicing.models import SupplierInvoice
from apps.purchase_orders.models import PurchaseOrder
from apps.vendors.models import Vendor, VendorBankAccount, VendorCategory

from apps.compliance.models import FraudRule, RestrictedPartyEntry

FRAUD_CODES = ('split_po', 'duplicate_invoice', 'round_amount', 'vendor_bank_conflict',
               'conflict_of_interest')


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
    """View-only role: may view compliance but not manage."""
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
def build_compliance(tenant, user):
    set_current_tenant(tenant)
    cat = VendorCategory.all_objects.create(tenant=tenant, name='Parts', code='PARTS')
    v1 = Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-1', legal_name='Acme Supplies', status='active',
        category=cat)
    v2 = Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-2', legal_name='Globex Parts', status='active',
        category=cat)

    # shared bank account -> vendor_bank_conflict
    VendorBankAccount.all_objects.create(
        tenant=tenant, vendor=v1, bank_name='Demo Bank', account_number='ACC-DUP-1')
    VendorBankAccount.all_objects.create(
        tenant=tenant, vendor=v2, bank_name='Demo Bank', account_number='ACC-DUP-1')

    # restricted-party entry matching v1 -> screening hit
    RestrictedPartyEntry.all_objects.create(
        tenant=tenant, list_name='OFAC-SDN', entity_name='Acme Supplies')

    # approval ceiling 1000 + two 800 POs to v1 by one buyer -> split_po
    ApprovalRule.all_objects.create(
        tenant=tenant, name='Standard', document_type='requisition', is_active=True,
        min_amount=Decimal('0'), max_amount=Decimal('1000'))
    for i in range(2):
        PurchaseOrder.all_objects.create(
            tenant=tenant, po_number=f'PO-S{i}', title='Split', vendor=v1, currency='USD',
            status='issued', order_date=date(2026, 6, 1), total_amount=Decimal('800.00'),
            created_by=user, owner=user)

    # 5000 PO -> round_amount
    PurchaseOrder.all_objects.create(
        tenant=tenant, po_number='PO-R', title='Round', vendor=v2, currency='USD',
        status='issued', order_date=date(2026, 6, 1), total_amount=Decimal('5000.00'),
        created_by=user, owner=user)

    # two 250 invoices sharing a reference -> duplicate_invoice
    for i in range(2):
        SupplierInvoice.all_objects.create(
            tenant=tenant, invoice_number=f'SINV-D{i}', vendor=v1, status='submitted',
            invoice_date=date(2026, 6, 1), currency='USD', subtotal=Decimal('250.00'),
            total_amount=Decimal('250.00'), supplier_invoice_ref='DUP-REF-1')

    for code in FRAUD_CODES:
        FraudRule.all_objects.create(
            tenant=tenant, code=code, name=code.replace('_', ' ').title(), is_active=True,
            severity='warning')

    return SimpleNamespace(tenant=tenant, category=cat, v1=v1, v2=v2)


@pytest.fixture
def data(db, tenant, tenant_admin):
    return build_compliance(tenant, tenant_admin)
