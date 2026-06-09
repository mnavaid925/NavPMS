"""Module 21 model tests — constants, ``__str__``, colour maps and computed properties."""
import pytest
from django.utils import timezone

from apps.sysadmin.models import ApiKey, BackupRun, IdentityProvider, SECRET_MASK
from apps.sysadmin.validators import mask_secret

pytestmark = pytest.mark.django_db


def test_role_str_and_properties(data):
    role = data.buyer_role
    assert role.code in str(role)
    assert role.status_color == 'success'
    assert role.permission_count > 0


def test_role_inactive_color(data):
    role = data.buyer_role
    role.is_active = False
    role.save()
    assert role.status_color == 'secondary'


def test_currency_taxcode_sequence_str(data):
    assert 'USD' in str(data.currency)
    assert 'VAT20' in str(data.taxcode)
    assert data.sequence.prefix in str(data.sequence)
    assert data.currency.status_color == 'success'


def test_identity_provider_properties(data):
    p = data.provider
    assert p.protocol_color == 'primary'      # saml
    assert p.status_color == 'secondary'       # is_active defaults False
    assert p.has_secret is False
    p.client_secret = 'shh'
    assert p.has_secret is True


def test_identity_provider_protocol_colors():
    assert IdentityProvider(protocol='oidc').protocol_color == 'info'
    assert IdentityProvider(protocol='ldap').protocol_color == 'warning'


def test_backup_run_size_mb_and_color(data):
    run = data.run
    assert run.status == 'success'
    assert run.status_color == 'success'
    assert run.size_mb > 0
    assert run.run_number.startswith('BKR-')


def test_backup_run_zero_size():
    assert BackupRun(size_bytes=0).size_mb == 0.0
    assert BackupRun(status='failed').status_color == 'danger'


def test_api_key_properties(data):
    k = data.api_key
    assert k.key_prefix in str(k)
    assert k.status_color == 'success'
    assert k.is_expired is False


def test_api_key_expired():
    k = ApiKey(expires_at=timezone.now() - timezone.timedelta(days=1))
    assert k.is_expired is True


def test_webhook_event_count(data):
    assert data.webhook.event_count == 2
    assert data.webhook.status_color == 'success'
    assert data.webhook.target_url in str(data.webhook)


def test_mask_secret_helper():
    assert mask_secret('anything') == SECRET_MASK
    assert mask_secret('') == ''
