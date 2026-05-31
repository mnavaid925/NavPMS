"""Shared fixtures for Module 9 (Contract Management) tests.

Mirrors the layout/style of ``apps/auctions/tests/conftest.py``: tenants & users,
vendors, then contract fixtures.

IMPORTANT (per lessons.md): every contract fixture CREATES its own row — we never
build ``active_contract`` by mutating ``draft_contract`` in place (that would
poison status-filter tests). Contract-creating fixtures call ``set_current_tenant``
first, then use the real services (``send_for_signature`` / ``sign_contract``) so
the seeded state is honest.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.contracts.models import (
    Contract,
    ContractClause,
    ContractClauseLine,
    ContractObligation,
    ContractSignatory,
    ContractTemplate,
    ContractTemplateClause,
)
from apps.contracts.services import sign_contract, send_for_signature
from apps.core.models import Tenant, set_current_tenant
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
    return User.objects.create_user(
        username='portal_a', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_a,
    )


@pytest.fixture
def vendor_b_portal_user(db, tenant, vendor_b):
    return User.objects.create_user(
        username='portal_b', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_b,
    )


# ---------- Clause library + templates ----------

@pytest.fixture
def clause(db, tenant):
    set_current_tenant(tenant)
    return ContractClause.all_objects.create(
        tenant=tenant, title='Payment Terms', category='payment',
        body='Net 30 days.', is_standard=True, is_active=True,
    )


@pytest.fixture
def template(db, tenant, tenant_admin, clause):
    set_current_tenant(tenant)
    tpl = ContractTemplate.all_objects.create(
        tenant=tenant, title='Standard Service Agreement',
        contract_type='service', is_shared=True, created_by=tenant_admin,
    )
    ContractTemplateClause.all_objects.create(
        tenant=tenant, template=tpl, clause=clause,
        heading=clause.title, body=clause.body, sort_order=1,
    )
    ContractTemplateClause.all_objects.create(
        tenant=tenant, template=tpl, heading='Confidentiality',
        body='Keep it secret.', sort_order=2,
    )
    return tpl


# ---------- Contracts ----------

def _make_contract(tenant, created_by, vendor, *, status='draft',
                   number='CON-ACME-00001', end_offset_days=365):
    today = timezone.localdate()
    return Contract.all_objects.create(
        tenant=tenant, contract_number=number,
        title='IT support services', contract_type='service',
        vendor=vendor, currency='USD', value=Decimal('120000.00'),
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=end_offset_days),
        status=status, created_by=created_by, owner=created_by,
    )


def _add_clause_line(tenant, contract, clause=None):
    return ContractClauseLine.all_objects.create(
        tenant=tenant, contract=contract, clause=clause,
        heading='Payment Terms', body='Net 30 days.', sort_order=1,
    )


def _add_signatories(tenant, contract, admin, vendor):
    ContractSignatory.all_objects.create(
        tenant=tenant, contract=contract, party='internal', user=admin,
        name='Ada Admin', email='ada@acme.test', order=1,
    )
    ContractSignatory.all_objects.create(
        tenant=tenant, contract=contract, party='vendor', vendor=vendor,
        name=vendor.legal_name, email=vendor.email or 'v@vend.test', order=2,
    )


@pytest.fixture
def draft_contract(db, tenant, tenant_admin, vendor_a, clause):
    """A bare draft contract with one clause line (not yet sendable: no signatory)."""
    set_current_tenant(tenant)
    contract = _make_contract(tenant, tenant_admin, vendor_a, number='CON-ACME-00001')
    _add_clause_line(tenant, contract, clause)
    return contract


@pytest.fixture
def ready_contract(db, tenant, tenant_admin, vendor_a, clause):
    """A draft with clause + 2 signatories + dates — ready to send for signature."""
    set_current_tenant(tenant)
    contract = _make_contract(tenant, tenant_admin, vendor_a, number='CON-ACME-00002')
    _add_clause_line(tenant, contract, clause)
    _add_signatories(tenant, contract, tenant_admin, vendor_a)
    return contract


@pytest.fixture
def pending_contract(db, tenant, tenant_admin, vendor_a, clause):
    """A contract that has been sent for signature (tokens issued)."""
    set_current_tenant(tenant)
    contract = _make_contract(tenant, tenant_admin, vendor_a, number='CON-ACME-00003')
    _add_clause_line(tenant, contract, clause)
    _add_signatories(tenant, contract, tenant_admin, vendor_a)
    send_for_signature(contract, tenant_admin)
    contract.refresh_from_db()
    return contract


@pytest.fixture
def active_contract(db, tenant, tenant_admin, vendor_a, clause):
    """A fully-signed, active contract with obligations."""
    set_current_tenant(tenant)
    contract = _make_contract(tenant, tenant_admin, vendor_a, number='CON-ACME-00004')
    _add_clause_line(tenant, contract, clause)
    _add_signatories(tenant, contract, tenant_admin, vendor_a)
    send_for_signature(contract, tenant_admin)
    for s in contract.signatories.all().order_by('order'):
        sign_contract(s, tenant_admin, s.name)
    contract.refresh_from_db()
    ContractObligation.all_objects.create(
        tenant=tenant, contract=contract, obligation_type='payment',
        title='Quarterly fee', amount=Decimal('30000.00'),
        due_date=timezone.localdate() + timedelta(days=30), status='pending',
    )
    return contract


@pytest.fixture
def expiring_contract(db, tenant, tenant_admin, vendor_a, clause):
    """An active contract expiring within the renewal-notice window (no alert yet)."""
    set_current_tenant(tenant)
    contract = _make_contract(
        tenant, tenant_admin, vendor_a, number='CON-ACME-00005', end_offset_days=10)
    _add_clause_line(tenant, contract, clause)
    _add_signatories(tenant, contract, tenant_admin, vendor_a)
    send_for_signature(contract, tenant_admin)
    for s in contract.signatories.all().order_by('order'):
        sign_contract(s, tenant_admin, s.name)
    contract.refresh_from_db()
    return contract
