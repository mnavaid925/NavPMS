"""Module 21 view tests — CRUD, filters, the permission matrix, and per-sub-module actions."""
import pytest

from apps.sysadmin import webhooks
from apps.sysadmin.models import (
    ApiKey, BackupRun, Currency, IdentityProvider, NumberSequence, RestoreRequest, RoleDefinition,
    SSOLoginEvent, TaxCode, Webhook, WebhookDelivery,
)

pytestmark = pytest.mark.django_db


# --- Dashboard + lists render ---
@pytest.mark.parametrize('name', [
    'dashboard', 'role_list', 'provider_list', 'config_overview', 'currency_list',
    'taxcode_list', 'sequence_list', 'backup_policy_list', 'backup_run_list', 'restore_list',
    'apikey_list', 'webhook_list',
])
def test_list_pages_render(admin_client, data, name):
    from django.urls import reverse
    assert admin_client.get(reverse(f'sysadmin:{name}')).status_code == 200


# --- Roles ---
def test_role_create(admin_client, tenant):
    resp = admin_client.post('/sysadmin/roles/new/', {
        'code': 'auditor', 'name': 'Auditor', 'description': 'Read-only auditor', 'is_active': 'on'})
    assert resp.status_code == 302
    role = RoleDefinition.all_objects.get(tenant=tenant, code='auditor')
    assert role.is_system is False


def test_role_permission_matrix_save(admin_client, data):
    url = f'/sysadmin/roles/{data.buyer_role.pk}/permissions/'
    resp = admin_client.post(url, {'permissions': ['po.view', 'invoice.pay']})
    assert resp.status_code == 302
    codes = set(data.buyer_role.permissions.values_list('permission_code', flat=True))
    assert codes == {'po.view', 'invoice.pay'}


def test_system_role_cannot_be_deleted(admin_client, data):
    resp = admin_client.post(f'/sysadmin/roles/{data.buyer_role.pk}/delete/')
    assert resp.status_code == 302
    assert RoleDefinition.all_objects.filter(pk=data.buyer_role.pk).exists()


def test_custom_role_delete(admin_client, data):
    role = RoleDefinition.all_objects.create(
        tenant=data.tenant, code='temp', name='Temp', is_system=False)
    resp = admin_client.post(f'/sysadmin/roles/{role.pk}/delete/')
    assert resp.status_code == 302
    assert not RoleDefinition.all_objects.filter(pk=role.pk).exists()


# --- System configuration ---
def test_config_overview_save(admin_client, tenant):
    resp = admin_client.post('/sysadmin/config/', {
        'company_legal_name': 'Acme Ltd', 'base_currency_code': 'EUR',
        'fiscal_year_start_month': '4', 'date_format': 'd/m/Y', 'time_format': 'H:i',
        'decimal_places': '2', 'default_payment_terms_days': '45', 'weekend_days': '6,0',
        'locale': 'en-gb'})
    assert resp.status_code == 302
    from apps.sysadmin.models import SystemConfiguration
    cfg = SystemConfiguration.objects.get(tenant=tenant)
    assert cfg.base_currency_code == 'EUR' and cfg.default_payment_terms_days == 45


def test_currency_crud(admin_client, tenant):
    admin_client.post('/sysadmin/config/currencies/new/', {
        'code': 'jpy', 'name': 'Yen', 'decimal_places': '0', 'exchange_rate_to_base': '0.0067'})
    cur = Currency.all_objects.get(tenant=tenant, code='JPY')  # upper-cased by the form
    admin_client.post(f'/sysadmin/config/currencies/{cur.pk}/delete/')
    assert not Currency.all_objects.filter(pk=cur.pk).exists()


def test_taxcode_create(admin_client, tenant):
    admin_client.post('/sysadmin/config/tax-codes/new/', {
        'code': 'GST5', 'name': 'GST 5%', 'rate': '5', 'tax_type': 'gst'})
    assert TaxCode.all_objects.filter(tenant=tenant, code='GST5').exists()


def test_sequence_create_and_filter(admin_client, tenant):
    admin_client.post('/sysadmin/config/sequences/new/', {
        'doc_type': 'grn', 'name': 'GRN', 'prefix': 'GRN', 'padding': '5', 'next_number': '1',
        'reset_frequency': 'never'})
    assert NumberSequence.all_objects.filter(tenant=tenant, doc_type='grn').exists()
    assert admin_client.get('/sysadmin/config/sequences/?q=grn').status_code == 200


# --- SSO ---
def test_provider_create_and_test(admin_client, data):
    resp = admin_client.post('/sysadmin/sso/new/', {
        'name': 'Okta', 'protocol': 'oidc', 'entity_id': 'urn:okta',
        'sso_url': 'https://okta.example.com/auth', 'default_role_code': 'requester'})
    assert resp.status_code == 302
    provider = IdentityProvider.all_objects.get(tenant=data.tenant, name='Okta')
    admin_client.post(f'/sysadmin/sso/{provider.pk}/test/')
    assert SSOLoginEvent.all_objects.filter(provider=provider).exists()


def test_provider_simulate(admin_client, data):
    admin_client.post(f'/sysadmin/sso/{data.provider.pk}/simulate/', {'email': 'jo@acme.test'})
    assert SSOLoginEvent.all_objects.filter(provider=data.provider, email='jo@acme.test').exists()


# --- Backups ---
def test_backup_policy_create_and_run(admin_client, tenant):
    admin_client.post('/sysadmin/backups/new/', {
        'name': 'Weekly', 'frequency': 'weekly', 'scope': 'db_only', 'retention_days': '60',
        'storage_target': 'local', 'run_hour': '3'})
    from apps.sysadmin.models import BackupPolicy
    policy = BackupPolicy.all_objects.get(tenant=tenant, name='Weekly')
    resp = admin_client.post(f'/sysadmin/backups/{policy.pk}/run/')
    assert resp.status_code == 302
    assert BackupRun.all_objects.filter(tenant=tenant, policy=policy).count() == 1


def test_restore_request_and_decide(admin_client, data):
    resp = admin_client.post(f'/sysadmin/backups/runs/{data.run.pk}/restore/',
                             {'reason': 'DR drill'})
    assert resp.status_code == 302
    rr = RestoreRequest.all_objects.get(backup_run=data.run)
    assert rr.status == 'requested'
    admin_client.post(f'/sysadmin/backups/restores/{rr.pk}/decide/', {'decision': 'approve'})
    rr.refresh_from_db()
    assert rr.status == 'approved'


def test_backup_run_export_csv(admin_client, data):
    resp = admin_client.get('/sysadmin/backups/runs/export.csv')
    assert resp.status_code == 200
    assert resp['Content-Type'].startswith('text/csv')


# --- API keys ---
def test_apikey_create_reveals_secret_once(admin_client, tenant):
    resp = admin_client.post('/sysadmin/api/keys/new/', {'name': 'CRM', 'scopes': ['po.view']})
    assert resp.status_code == 200  # the one-time reveal page
    key = ApiKey.all_objects.get(tenant=tenant, name='CRM')
    body = resp.content.decode()
    assert key.key_prefix in body
    # The full raw secret (prefix.secret) is shown once; the stored hash is never rendered.
    assert key.hashed_secret not in body


def test_apikey_revoke(admin_client, data):
    resp = admin_client.post(f'/sysadmin/api/keys/{data.api_key.pk}/revoke/')
    assert resp.status_code == 302
    data.api_key.refresh_from_db()
    assert data.api_key.is_active is False


# --- Webhooks ---
def test_webhook_create(admin_client, tenant):
    resp = admin_client.post('/sysadmin/api/webhooks/new/', {
        'name': 'CRM hook', 'target_url': 'https://hooks.test/crm', 'events': ['po.issued'],
        'secret': 'whsec_x', 'is_active': 'on'})
    assert resp.status_code == 302
    wh = Webhook.all_objects.get(tenant=tenant, name='CRM hook')
    assert wh.events == ['po.issued']


def test_webhook_test_action(admin_client, data, monkeypatch):
    monkeypatch.setattr(webhooks, '_default_poster',
                        lambda url, body, headers, timeout: (200, 'OK'))
    resp = admin_client.post(f'/sysadmin/api/webhooks/{data.webhook.pk}/test/')
    assert resp.status_code == 302
    assert WebhookDelivery.all_objects.filter(
        webhook=data.webhook, event='sysadmin.ping').exists()
