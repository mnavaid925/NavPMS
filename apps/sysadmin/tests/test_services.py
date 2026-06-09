"""Module 21 service tests — the governance API, numbering, API keys, SSO, backups, webhooks."""
import hashlib
import hmac

import pytest

from apps.sysadmin import backups, permissions as perms, services, webhooks
from apps.sysadmin.models import NumberSequence, RoleDefinition, WebhookDelivery

pytestmark = pytest.mark.django_db


# --- Roles & permission matrix ---
def test_ensure_system_roles_idempotent(tenant):
    services.ensure_system_roles(tenant)
    services.ensure_system_roles(tenant)
    roles = RoleDefinition.all_objects.filter(tenant=tenant)
    assert roles.count() == len(perms.BUILTIN_ROLES)
    assert all(r.is_system for r in roles)


def test_sync_default_grants_mirrors_defaults(tenant):
    services.ensure_system_roles(tenant)
    services.sync_default_grants(tenant)
    buyer = RoleDefinition.all_objects.get(tenant=tenant, code='buyer')
    granted = services.role_permission_codes(buyer)
    assert granted == set(perms.default_grants_for('buyer'))


def test_user_has_perm_matrix(tenant, buyer_user):
    services.ensure_system_roles(tenant)
    services.sync_default_grants(tenant)
    assert services.user_has_perm(buyer_user, 'po.manage') is True
    assert services.user_has_perm(buyer_user, 'invoice.pay') is False


def test_user_has_perm_admin_always_true(tenant, tenant_admin):
    # No grants synced at all — admins still pass.
    assert services.user_has_perm(tenant_admin, 'invoice.pay') is True


def test_user_has_perm_is_tenant_scoped(tenant, other_tenant, buyer_user):
    """A buyer's perms come from THEIR tenant's matrix, never another tenant's."""
    services.ensure_system_roles(other_tenant)
    services.sync_default_grants(other_tenant)  # grants exist only for other_tenant
    # buyer_user belongs to `tenant`, which has no grants → denied.
    assert services.user_has_perm(buyer_user, 'po.manage') is False


def test_set_role_permissions_reconciles(data):
    role = data.buyer_role
    added, removed = services.set_role_permissions(role, ['po.view', 'invoice.pay'], user=data.user)
    codes = services.role_permission_codes(role)
    assert codes == {'po.view', 'invoice.pay'}
    assert added >= 1 and removed >= 1


def test_set_role_permissions_ignores_invalid_codes(data):
    role = data.buyer_role
    services.set_role_permissions(role, ['po.view', 'not.a.real.code'], user=data.user)
    assert services.role_permission_codes(role) == {'po.view'}


def test_can_delete_role(data):
    assert services.can_delete_role(data.buyer_role) is False  # built-in
    custom = RoleDefinition.all_objects.create(
        tenant=data.tenant, code='auditor', name='Auditor', is_system=False)
    assert services.can_delete_role(custom) is True


# --- Numbering ---
def test_allocate_number_consumes_and_formats(data):
    seq = data.sequence  # PO, padding 5, include_year, next 1
    first = services.allocate_number(seq)
    seq.refresh_from_db()
    second = services.allocate_number(seq)
    assert first.startswith('PO-') and first.endswith('-00001')
    assert second.endswith('-00002')
    assert first != second


def test_preview_number_does_not_consume(data):
    seq = data.sequence
    before = seq.next_number
    preview = services.preview_number(seq)
    seq.refresh_from_db()
    assert seq.next_number == before
    assert preview.endswith('-00001')


def test_allocate_number_unique_across_many(tenant):
    seq = NumberSequence.all_objects.create(
        tenant=tenant, doc_type='x', name='X', prefix='X', padding=4, next_number=1)
    nums = {services.allocate_number(seq) for _ in range(20)}
    assert len(nums) == 20


# --- API keys ---
def test_issue_api_key_stores_only_hash(data):
    api_key, raw = services.issue_api_key(data.tenant, name='New', user=data.user)
    assert raw.startswith(api_key.key_prefix + '.')
    assert api_key.hashed_secret == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in api_key.hashed_secret  # plaintext never stored


def test_verify_api_key_roundtrip(data):
    api_key, raw = services.issue_api_key(data.tenant, name='V', user=data.user)
    assert services.verify_api_key(raw).pk == api_key.pk
    assert services.verify_api_key(raw + 'tamper') is None
    assert services.verify_api_key('garbage') is None


def test_verify_api_key_revoked(data):
    api_key, raw = services.issue_api_key(data.tenant, name='R', user=data.user)
    services.revoke_api_key(api_key, user=data.user)
    assert services.verify_api_key(raw) is None


# --- SSO ---
def test_test_identity_provider_logs_event(data):
    result = services.test_identity_provider(data.provider, user=data.user)
    assert result.ok is True
    assert data.provider.login_events.count() == 1


def test_simulate_sso_login_provisioned(data):
    result, outcome = services.simulate_sso_login(
        data.provider, 'jane@acme.test', user=data.user)
    assert result.ok is True
    assert outcome == 'provisioned'  # jit_provisioning on


def test_simulate_sso_login_domain_blocked(data):
    data.provider.allowed_domains = 'corp.test'
    data.provider.save()
    result, outcome = services.simulate_sso_login(data.provider, 'jane@evil.test', user=data.user)
    assert result.ok is False
    assert outcome == 'failed'


# --- Backups ---
def test_run_backup_success(data):
    new_run = backups.run_backup(
        data.tenant, policy=data.policy, trigger='manual', user=data.user)
    assert new_run.status == 'success'
    assert new_run.size_bytes > 0
    assert new_run.checksum
    assert new_run.run_number.startswith('BKR-')


# --- Webhooks ---
def test_sign_payload_is_hmac():
    sig = webhooks.sign_payload('secret', b'body')
    assert sig == hmac.new(b'secret', b'body', hashlib.sha256).hexdigest()


def test_deliver_with_stub_poster(data):
    delivery = WebhookDelivery.all_objects.create(
        tenant=data.tenant, webhook=data.webhook, event='po.issued', payload={'x': 1})
    webhooks.deliver(delivery, poster=lambda url, body, headers, timeout: (200, 'OK'))
    delivery.refresh_from_db()
    assert delivery.status == 'success'
    assert delivery.attempts == 1


def test_deliver_blocks_private_host(data):
    data.webhook.target_url = 'https://10.0.0.5/internal'
    data.webhook.save()
    delivery = WebhookDelivery.all_objects.create(
        tenant=data.tenant, webhook=data.webhook, event='po.issued', payload={})
    # Poster must never be called — SSRF guard fails closed first.
    called = []
    webhooks.deliver(delivery, poster=lambda *a: called.append(1) or (200, 'x'))
    delivery.refresh_from_db()
    assert delivery.status == 'failed'
    assert not called


def test_emit_event_fans_out(data):
    deliveries = webhooks.emit_event(
        data.tenant, 'po.issued', {'po': 1},
        poster=lambda url, body, headers, timeout: (200, 'OK'))
    assert len(deliveries) == 1
    assert deliveries[0].status == 'success'


def test_emit_event_skips_unsubscribed(data):
    deliveries = webhooks.emit_event(
        data.tenant, 'vendor.created', {}, poster=lambda *a: (200, 'OK'))
    assert deliveries == []  # webhook only subscribes to po.issued / invoice.paid


# --- System configuration ---
def test_get_system_configuration_singleton(tenant):
    c1 = services.get_system_configuration(tenant)
    c2 = services.get_system_configuration(tenant)
    assert c1.pk == c2.pk
