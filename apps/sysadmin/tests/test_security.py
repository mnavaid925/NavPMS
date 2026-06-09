"""Module 21 security tests — admin gating, cross-tenant isolation, SSRF, secret confidentiality."""
import pytest
from django.core.exceptions import ValidationError

from apps.sysadmin.connectors import validate_metadata_url
from apps.sysadmin.webhooks import validate_webhook_url

pytestmark = pytest.mark.django_db


# --- Admin gating (non-admins bounced) ---
@pytest.mark.parametrize('path', [
    '/sysadmin/', '/sysadmin/roles/', '/sysadmin/sso/', '/sysadmin/config/',
    '/sysadmin/backups/', '/sysadmin/api/keys/', '/sysadmin/api/webhooks/',
])
def test_non_admin_is_bounced(client, requester, path):
    client.force_login(requester)
    resp = client.get(path)
    assert resp.status_code == 302
    assert '/sysadmin/' not in resp['Location']


def test_buyer_is_bounced(client, buyer_user):
    client.force_login(buyer_user)
    assert client.get('/sysadmin/').status_code == 302


def test_anonymous_redirected_to_login(client):
    resp = client.get('/sysadmin/')
    assert resp.status_code == 302
    assert '/accounts/login' in resp['Location']


# --- Cross-tenant isolation (IDOR) ---
def test_cross_tenant_role_404(client, data, intruder):
    client.force_login(intruder)
    assert client.get(f'/sysadmin/roles/{data.buyer_role.pk}/').status_code == 404


def test_cross_tenant_provider_404(client, data, intruder):
    client.force_login(intruder)
    assert client.get(f'/sysadmin/sso/{data.provider.pk}/').status_code == 404


def test_cross_tenant_backup_run_404(client, data, intruder):
    client.force_login(intruder)
    assert client.get(f'/sysadmin/backups/runs/{data.run.pk}/').status_code == 404


def test_cross_tenant_webhook_404(client, data, intruder):
    client.force_login(intruder)
    assert client.get(f'/sysadmin/api/webhooks/{data.webhook.pk}/').status_code == 404


def test_cross_tenant_apikey_revoke_404(client, data, intruder):
    client.force_login(intruder)
    assert client.post(f'/sysadmin/api/keys/{data.api_key.pk}/revoke/').status_code == 404
    data.api_key.refresh_from_db()
    assert data.api_key.is_active is True  # untouched


# --- SSRF guards (fail closed) ---
@pytest.mark.parametrize('url', [
    'http://hooks.example.com/x',        # not HTTPS
    'https://127.0.0.1/x',               # loopback
    'https://10.0.0.1/x',                # private
    'https://169.254.169.254/latest',    # cloud metadata
    'https://[::1]/x',                    # IPv6 loopback
])
def test_webhook_url_ssrf_rejected(settings, url):
    settings.WEBHOOK_SSRF_ALLOWLIST = ''
    with pytest.raises(ValidationError):
        validate_webhook_url(url)


def test_webhook_url_allowlist_passes(settings):
    settings.WEBHOOK_SSRF_ALLOWLIST = 'hooks.internal'
    assert validate_webhook_url('https://hooks.internal/x') == 'https://hooks.internal/x'


def test_metadata_url_ssrf_rejected(settings):
    settings.SSO_METADATA_ALLOWLIST = ''
    with pytest.raises(ValidationError):
        validate_metadata_url('https://192.168.1.1/metadata')


# --- Secret confidentiality ---
def test_api_key_secret_never_listed(admin_client, data):
    """No page may echo the stored hash; the raw secret exists only on the one-time reveal."""
    body = admin_client.get('/sysadmin/api/keys/').content.decode()
    assert data.api_key.hashed_secret not in body
    assert data.raw_secret not in body


def test_provider_secret_not_rendered(admin_client, data):
    data.provider.client_secret = 'super-secret-value'
    data.provider.save()
    body = admin_client.get(f'/sysadmin/sso/{data.provider.pk}/').content.decode()
    assert 'super-secret-value' not in body


def test_provider_edit_blank_secret_preserves(admin_client, data):
    """Submitting the edit form with a blank secret keeps (does not wipe) the stored one."""
    data.provider.client_secret = 'keep-me'
    data.provider.save()
    admin_client.post(f'/sysadmin/sso/{data.provider.pk}/edit/', {
        'name': data.provider.name, 'protocol': 'saml', 'entity_id': data.provider.entity_id,
        'sso_url': data.provider.sso_url, 'default_role_code': 'requester', 'client_secret': ''})
    data.provider.refresh_from_db()
    assert data.provider.client_secret == 'keep-me'


def test_webhook_secret_not_rendered(admin_client, data):
    data.webhook.secret = 'whsec_supersecret'
    data.webhook.save()
    body = admin_client.get(f'/sysadmin/api/webhooks/{data.webhook.pk}/').content.decode()
    assert 'whsec_supersecret' not in body
