"""Module 21 service layer: System Administration & Security.

Owns every state transition + side effect, mirroring the Module 18 (compliance) / Module 20 (dms)
conventions: role gates, gap-free numbering, ``record_audit`` from :mod:`apps.tenants.services`,
and ``@transaction.atomic`` write paths.

The headline governance API is :func:`user_has_perm` — the DB-backed roles x permission matrix that
new code can consult. It augments the existing hardcoded role checks; it does not replace them, so a
tenant_admin / superuser always passes (they administer the matrix).
"""
import hashlib
import hmac
import secrets

from django.db import transaction
from django.utils import timezone

from apps.tenants.services import record_audit

from . import permissions as perms
from .models import (
    ApiKey, BackupRun, Currency, IdentityProvider, NumberSequence, RoleDefinition, RolePermission,
    SSOLoginEvent, SystemConfiguration, TaxCode,
)

# This module administers the platform, so management is tenant-admin / super-admin only. Viewing is
# the same set (there is no read-only sysadmin role in the project). The fine-grained matrix is for
# the *rest* of the app, exposed via user_has_perm.
ADMIN_ROLES = ('tenant_admin', 'super_admin')


# ---------------------------------------------------------------------------
# Module access gates (who may open /sysadmin/)
# ---------------------------------------------------------------------------
def _is_admin(user):
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_tenant_admin', False):
        return True
    return getattr(user, 'role', '') in ADMIN_ROLES


def can_manage_sysadmin(user):
    return _is_admin(user)


def can_view_sysadmin(user):
    return _is_admin(user)


# ---------------------------------------------------------------------------
# Governance API — the roles x permission matrix
# ---------------------------------------------------------------------------
def user_has_perm(user, code):
    """True if ``user`` is granted permission ``code`` (the DB matrix; admins always pass)."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False) or getattr(user, 'is_tenant_admin', False):
        return True
    role = getattr(user, 'role', '') or ''
    if role in perms.SUPERUSER_ROLE_CODES:
        return True
    tenant = getattr(user, 'tenant', None)
    if tenant is None:
        return False
    return RolePermission.all_objects.filter(
        tenant=tenant, role__code=role, permission_code=code).exists()


def role_permission_codes(role):
    """The set of permission codes currently granted to a role."""
    return set(role.permissions.values_list('permission_code', flat=True))


@transaction.atomic
def ensure_system_roles(tenant):
    """Create the built-in :class:`RoleDefinition` rows for a tenant (idempotent)."""
    created = []
    for code, name in perms.BUILTIN_ROLES:
        role, was_created = RoleDefinition.all_objects.get_or_create(
            tenant=tenant, code=code,
            defaults={'name': name, 'is_system': True,
                      'description': f'Built-in {name} role.'})
        if was_created:
            created.append(role)
    return created


@transaction.atomic
def sync_default_grants(tenant, *, overwrite=False):
    """Apply :data:`permissions.DEFAULT_ROLE_GRANTS` to a tenant's roles (idempotent).

    With ``overwrite=False`` it only *adds* missing grants (never strips an admin's customisation);
    with ``overwrite=True`` it resets each role to exactly its default set.
    """
    ensure_system_roles(tenant)
    for role in RoleDefinition.all_objects.filter(tenant=tenant):
        defaults = set(perms.default_grants_for(role.code))
        current = role_permission_codes(role)
        if overwrite:
            _reconcile_role_permissions(role, defaults, current)
        else:
            for code in defaults - current:
                RolePermission.all_objects.get_or_create(
                    tenant=tenant, role=role, permission_code=code)


def _reconcile_role_permissions(role, target_codes, current_codes):
    target_codes = {c for c in target_codes if perms.is_valid_permission(c)}
    to_add = target_codes - current_codes
    to_remove = current_codes - target_codes
    for code in to_add:
        RolePermission.all_objects.get_or_create(
            tenant=role.tenant, role=role, permission_code=code)
    if to_remove:
        RolePermission.all_objects.filter(
            tenant=role.tenant, role=role, permission_code__in=to_remove).delete()
    return len(to_add), len(to_remove)


@transaction.atomic
def set_role_permissions(role, codes, *, user=None, request=None):
    """Reconcile a role's grants to exactly ``codes`` (the permission-matrix save). Audited."""
    target = {c for c in codes if perms.is_valid_permission(c)}
    current = role_permission_codes(role)
    added, removed = _reconcile_role_permissions(role, target, current)
    record_audit(
        role.tenant, user, 'sysadmin.role_permissions_set', target_type='RoleDefinition',
        target_id=str(role.pk),
        message=f'{role.name}: +{added} / -{removed} permissions.', request=request)
    return added, removed


def can_delete_role(role):
    return not role.is_system


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def _next_number(model, tenant, prefix, field_name):
    """Gap-free ``<PREFIX>-<SLUG>-NNNNN`` per tenant (clone of the dms idiom)."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = model.all_objects.filter(tenant=tenant).count() + 1
    number = f'{prefix}-{slug}-{count:05d}'
    while model.all_objects.filter(tenant=tenant, **{field_name: number}).exists():
        count += 1
        number = f'{prefix}-{slug}-{count:05d}'
    return number


def next_backup_run_number(tenant):
    return _next_number(BackupRun, tenant, 'BKR', 'run_number')


# ---------------------------------------------------------------------------
# System configuration + number sequences
# ---------------------------------------------------------------------------
def get_system_configuration(tenant):
    """Fetch (or lazily create) the per-tenant configuration singleton."""
    config, _ = SystemConfiguration.objects.get_or_create(tenant=tenant)
    return config


def format_sequence(seq, value, *, year=None):
    """Render a :class:`NumberSequence` value, e.g. ``PO-2026-00042``."""
    parts = []
    if seq.prefix:
        parts.append(seq.prefix)
    if seq.include_year:
        parts.append(str(year if year is not None else timezone.now().year))
    parts.append(str(value).zfill(seq.padding))
    return '-'.join(parts) + (seq.suffix or '')


def preview_number(seq):
    """The next value this sequence would produce, WITHOUT consuming it."""
    return format_sequence(seq, seq.next_number)


@transaction.atomic
def allocate_number(seq):
    """Atomically consume and return the next formatted number for a sequence.

    Locks the row with ``select_for_update`` so two concurrent allocations can never collide
    (the lessons.md row-lock rule).
    """
    locked = NumberSequence.all_objects.select_for_update().get(pk=seq.pk)
    value = locked.next_number
    locked.next_number = value + 1
    locked.save(update_fields=['next_number', 'updated_at'])
    return format_sequence(locked, value)


# ---------------------------------------------------------------------------
# LDAP / SSO orchestration
# ---------------------------------------------------------------------------
def _ip(request):
    return request.META.get('REMOTE_ADDR') if request is not None else None


def test_identity_provider(provider, *, user=None, request=None):
    """Run the connector's connection test, log an :class:`SSOLoginEvent`, audit it."""
    from .connectors import get_sso_connector
    result = get_sso_connector(provider.connector).test_connection(provider)
    SSOLoginEvent.all_objects.create(
        tenant=provider.tenant, provider=provider,
        outcome='success' if result.ok else 'failed', message=result.message[:255],
        ip_address=_ip(request))
    record_audit(
        provider.tenant, user, 'sysadmin.sso_test',
        level='info' if result.ok else 'warning', target_type='IdentityProvider',
        target_id=str(provider.pk), message=f'SSO test {provider.name}: {result.message}'[:255],
        request=request)
    return result


def simulate_sso_login(provider, email, *, user=None, request=None):
    """Deterministically simulate a login through the connector and log the outcome.

    The governance build does NOT auto-create real users here — it records the outcome (incl. a
    ``provisioned`` marker when JIT is on) so the flow is demoable and auditable.
    """
    from .connectors import get_sso_connector
    result = get_sso_connector(provider.connector).authenticate(provider, email)
    outcome = 'failed'
    if result.ok:
        outcome = 'provisioned' if provider.jit_provisioning else 'success'
    SSOLoginEvent.all_objects.create(
        tenant=provider.tenant, provider=provider, email=result.email or email or '',
        subject_id=result.subject_id, outcome=outcome, message=result.message[:255],
        ip_address=_ip(request))
    record_audit(
        provider.tenant, user, 'sysadmin.sso_login',
        level='info' if result.ok else 'warning', target_type='IdentityProvider',
        target_id=str(provider.pk),
        message=f'SSO login {provider.name} ({email}): {outcome}.'[:255], request=request)
    return result, outcome


# ---------------------------------------------------------------------------
# API keys (secret stored only as a SHA-256 hash)
# ---------------------------------------------------------------------------
def _hash_secret(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


@transaction.atomic
def issue_api_key(tenant, *, name, scopes=None, expires_at=None, user=None, request=None):
    """Create an API key and return ``(api_key, raw_secret)``.

    The raw secret is shown to the caller ONCE — only its SHA-256 hash is persisted. There is no way
    to recover the plaintext afterwards.
    """
    from django.conf import settings
    brand = (getattr(settings, 'API_KEY_PREFIX', 'pms') or 'pms')
    # Ensure a unique public prefix per tenant.
    key_prefix = f'{brand}_{secrets.token_hex(4)}'
    while ApiKey.all_objects.filter(tenant=tenant, key_prefix=key_prefix).exists():
        key_prefix = f'{brand}_{secrets.token_hex(4)}'
    raw = f'{key_prefix}.{secrets.token_urlsafe(32)}'
    api_key = ApiKey.all_objects.create(
        tenant=tenant, name=name, key_prefix=key_prefix, hashed_secret=_hash_secret(raw),
        scopes=list(scopes or []), expires_at=expires_at, created_by=user)
    record_audit(
        tenant, user, 'sysadmin.api_key_issued', target_type='ApiKey', target_id=str(api_key.pk),
        message=f'API key "{name}" issued ({key_prefix}…).', request=request)
    return api_key, raw


def verify_api_key(raw):
    """Return the active, unexpired :class:`ApiKey` matching ``raw`` (constant-time), else ``None``."""
    raw = (raw or '').strip()
    if '.' not in raw:
        return None
    prefix = raw.split('.', 1)[0]
    expected = _hash_secret(raw)
    for key in ApiKey.all_objects.filter(key_prefix=prefix, is_active=True):
        if hmac.compare_digest(key.hashed_secret, expected) and not key.is_expired:
            return key
    return None


@transaction.atomic
def revoke_api_key(api_key, *, user=None, request=None):
    api_key.is_active = False
    api_key.save(update_fields=['is_active', 'updated_at'])
    record_audit(
        api_key.tenant, user, 'sysadmin.api_key_revoked', target_type='ApiKey',
        target_id=str(api_key.pk), message=f'API key "{api_key.name}" revoked.', request=request)
    return api_key


# ---------------------------------------------------------------------------
# Dashboard metrics
# ---------------------------------------------------------------------------
def tenant_sysadmin_metrics(tenant):
    """KPI cards + chart series for the System Administration dashboard."""
    runs = BackupRun.all_objects.filter(tenant=tenant)
    last_backup = runs.order_by('-created_at').first()
    status_counts = {'success': 0, 'failed': 0, 'running': 0, 'pending': 0}
    for row in runs.values('status'):
        status_counts[row['status']] = status_counts.get(row['status'], 0) + 1

    from .models import BackupPolicy, Webhook, WebhookDelivery
    return {
        'role_count': RoleDefinition.all_objects.filter(tenant=tenant).count(),
        'permission_total': len(perms.ALL_PERMISSION_CODES),
        'provider_count': IdentityProvider.all_objects.filter(tenant=tenant).count(),
        'active_provider_count': IdentityProvider.all_objects.filter(
            tenant=tenant, is_active=True).count(),
        'currency_count': Currency.all_objects.filter(tenant=tenant, is_active=True).count(),
        'taxcode_count': TaxCode.all_objects.filter(tenant=tenant, is_active=True).count(),
        'sequence_count': NumberSequence.all_objects.filter(tenant=tenant).count(),
        'backup_policy_count': BackupPolicy.all_objects.filter(tenant=tenant, is_active=True).count(),
        'backup_run_count': runs.count(),
        'last_backup': last_backup,
        'api_key_count': ApiKey.all_objects.filter(tenant=tenant, is_active=True).count(),
        'webhook_count': Webhook.all_objects.filter(tenant=tenant, is_active=True).count(),
        'webhook_failed_count': WebhookDelivery.all_objects.filter(
            tenant=tenant, status='failed').count(),
        'backup_status_labels': ['Success', 'Failed', 'Running', 'Pending'],
        'backup_status_data': [status_counts['success'], status_counts['failed'],
                               status_counts['running'], status_counts['pending']],
        'recent_runs': list(runs.select_related('policy').order_by('-created_at')[:6]),
        'recent_sso': list(
            SSOLoginEvent.all_objects.filter(tenant=tenant)
            .select_related('provider').order_by('-created_at')[:6]),
    }
