"""Shared fixtures for Module 21 (System Administration & Security) tests.

``build_sysadmin`` creates a representative slice of every sub-module (the built-in roles + default
grant matrix, a currency / tax code / number sequence, an SSO provider, a backup policy + run, a
webhook and an API key) driven through the real services. Each fixture CREATES its own data (never
mutates another) per lessons.md, using ``.all_objects`` / the service layer and an autouse reset of
the thread-local tenant. A webhook-friendly SSRF allowlist is set so the webhook host validates
without a DNS lookup (hermetic).
"""
from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant

from apps.sysadmin import backups, services
from apps.sysadmin.models import (
    BackupPolicy, Currency, IdentityProvider, NumberSequence, RoleDefinition, TaxCode, Webhook,
)


@pytest.fixture(autouse=True)
def _reset_tenant():
    yield
    set_current_tenant(None)


@pytest.fixture(autouse=True)
def _webhook_allowlist(settings):
    """Allow the test webhook host so the SSRF guard validates it without a DNS lookup."""
    settings.WEBHOOK_SSRF_ALLOWLIST = 'hooks.test'
    settings.SSO_METADATA_ALLOWLIST = 'idp.test'


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
def requester(db, tenant):
    """Non-admin — bounced from every /sysadmin/ page."""
    return User.objects.create_user(
        username='requester', password='x', tenant=tenant, role='requester')


@pytest.fixture
def intruder(db, other_tenant):
    """Tenant admin of a DIFFERENT tenant — used for cross-tenant isolation."""
    return User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant,
        role='tenant_admin', is_tenant_admin=True, email='m@globex.test')


@pytest.fixture
def admin_client(client, tenant_admin):
    client.force_login(tenant_admin)
    return client


# ---------- Source-data builder ----------
def build_sysadmin(tenant, user):
    set_current_tenant(tenant)
    services.ensure_system_roles(tenant)
    services.sync_default_grants(tenant)
    buyer_role = RoleDefinition.all_objects.get(tenant=tenant, code='buyer')

    currency = Currency.all_objects.create(
        tenant=tenant, code='USD', name='US Dollar', symbol='$', is_base=True)
    taxcode = TaxCode.all_objects.create(
        tenant=tenant, code='VAT20', name='Standard VAT', rate=20, tax_type='vat', is_default=True)
    sequence = NumberSequence.all_objects.create(
        tenant=tenant, doc_type='purchase_order', name='Purchase Order', prefix='PO',
        padding=5, next_number=1, include_year=True)
    provider = IdentityProvider.all_objects.create(
        tenant=tenant, name='Corporate SSO', protocol='saml', connector='mock',
        entity_id='urn:acme:navpms', sso_url='https://idp.example.com/sso',
        jit_provisioning=True, default_role_code='requester')
    policy = BackupPolicy.all_objects.create(
        tenant=tenant, name='Nightly full', frequency='daily', scope='full', retention_days=30)
    run = backups.run_backup(tenant, policy=policy, trigger='manual', user=user)
    webhook = Webhook.all_objects.create(
        tenant=tenant, name='ERP sync', target_url='https://hooks.test/navpms',
        events=['po.issued', 'invoice.paid'], secret='whsec_test', is_active=True)
    api_key, raw_secret = services.issue_api_key(
        tenant, name='ERP', scopes=['po.view'], user=user)

    return SimpleNamespace(
        tenant=tenant, user=user, buyer_role=buyer_role, currency=currency, taxcode=taxcode,
        sequence=sequence, provider=provider, policy=policy, run=run, webhook=webhook,
        api_key=api_key, raw_secret=raw_secret)


@pytest.fixture
def data(db, tenant, tenant_admin):
    return build_sysadmin(tenant, tenant_admin)
