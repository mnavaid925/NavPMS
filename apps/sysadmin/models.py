"""Module 21: System Administration & Security.

The platform-governance layer over the whole procure-to-pay suite. Where the other modules
*transact*, this one *administers*: who may do what (roles & permissions), how people sign in
(LDAP/SSO), the company-wide defaults every module reads (currency, tax codes, numbering), how the
data is protected (backup & recovery), and how the system talks to the outside world (API keys &
webhooks for ERP / accounting / CRM integration).

Covers the five PMS sub-modules:
  1. User Role & Permission Management -> RoleDefinition + RolePermission (a roles x permission
     matrix; presence of a row = granted). The permission *catalog* lives in ``permissions.py``.
  2. LDAP/SSO Integration              -> IdentityProvider (SAML / OIDC / LDAP config) + append-only
     SSOLoginEvent. Live handshakes are pluggable connectors (``connectors.py``, mock by default).
  3. System Configuration & Setup      -> SystemConfiguration (1:1 per-tenant singleton) + Currency +
     TaxCode + NumberSequence master tables.
  4. Data Backup & Recovery            -> BackupPolicy + append-only BackupRun history + RestoreRequest
     (a logged recovery protocol). Execution is a pluggable connector (``backups.py``, mock default).
  5. API & Webhook Management          -> ApiKey (secret stored only as a SHA-256 hash) + Webhook
     (SSRF-guarded target) + append-only WebhookDelivery log. Dispatch lives in ``webhooks.py``.

DESIGN — self-contained, mirroring the Module 18 (compliance) / Module 20 (dms) conventions:
TenantAwareModel + TimeStampedModel bases, module-level choice constants re-exposed on the model,
``*_COLORS`` badge maps, and append-only log models. It *augments* the existing foundations
(``tenants.SecuritySettings`` password/MFA/session policy, ``tenants.AuditLog`` hash-chain reused via
``record_audit``, ``accounts.User.role``) — it does not replace them.

SECURITY: every secret (API key secret, SSO client_secret / bind_password, webhook signing secret)
is write-only at the form/UI layer and is hashed (API key) or masked (the rest) — never re-rendered.
"""
from django.conf import settings
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Sub-module 1 — Roles & Permissions
# ---------------------------------------------------------------------------
class RoleDefinition(TenantAwareModel, TimeStampedModel):
    """A tenant's definition of a job role — the *subject* side of access control.

    Built-in roles (``is_system=True``) mirror ``accounts.User.ROLE_CHOICES`` and cannot be deleted;
    tenants may add custom roles. Permission grants hang off :class:`RolePermission`.
    """

    code = models.SlugField(max_length=40, help_text='Stable identifier, e.g. "buyer".')
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    is_system = models.BooleanField(
        default=False, help_text='Built-in role (mirrors User.role) — cannot be deleted.')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        unique_together = [('tenant', 'code')]
        indexes = [models.Index(fields=['tenant', 'is_active'])]

    def __str__(self):
        return f'{self.name} ({self.code})'

    @property
    def status_color(self):
        return 'success' if self.is_active else 'secondary'

    @property
    def permission_count(self):
        return self.permissions.count()


class RolePermission(TenantAwareModel, TimeStampedModel):
    """A single granted permission for a role. **Presence of the row = granted.**

    ``permission_code`` is validated against ``permissions.PERMISSION_LABELS`` at the service layer.
    """

    role = models.ForeignKey(RoleDefinition, on_delete=models.CASCADE, related_name='permissions')
    permission_code = models.CharField(max_length=60)

    class Meta:
        ordering = ['permission_code']
        unique_together = [('tenant', 'role', 'permission_code')]
        indexes = [models.Index(fields=['tenant', 'permission_code'])]

    def __str__(self):
        return f'{self.role_id}:{self.permission_code}'


# ---------------------------------------------------------------------------
# Sub-module 2 — LDAP/SSO Integration
# ---------------------------------------------------------------------------
SSO_PROTOCOL_CHOICES = [
    ('saml', 'SAML 2.0'),
    ('oidc', 'OpenID Connect'),
    ('ldap', 'LDAP / Active Directory'),
]
SSO_PROTOCOL_COLORS = {'saml': 'primary', 'oidc': 'info', 'ldap': 'warning'}

SSO_OUTCOME_CHOICES = [
    ('success', 'Success'),
    ('failed', 'Failed'),
    ('provisioned', 'Provisioned (JIT)'),
]
SSO_OUTCOME_COLORS = {'success': 'success', 'failed': 'danger', 'provisioned': 'info'}

# Sentinel shown in the UI in place of a stored secret (never the real value).
SECRET_MASK = '••••••••'


class IdentityProvider(TenantAwareModel, TimeStampedModel):
    """A corporate-directory / SSO connection a tenant signs in through.

    Configuration only — the live protocol handshake is a pluggable connector (``connectors.py``,
    mock by default). Secrets (``client_secret`` / ``bind_password``) are write-only and masked.
    """

    PROTOCOL_CHOICES = SSO_PROTOCOL_CHOICES

    name = models.CharField(max_length=120)
    protocol = models.CharField(max_length=8, choices=SSO_PROTOCOL_CHOICES, default='saml')
    connector = models.CharField(
        max_length=20, default='mock',
        help_text='Backend that performs the handshake (mock by default).')
    is_active = models.BooleanField(default=False)
    is_default = models.BooleanField(
        default=False, help_text='Primary provider offered on the login page.')

    # SAML / OIDC
    entity_id = models.CharField('Entity ID / Issuer', max_length=255, blank=True)
    sso_url = models.URLField('Sign-in URL', max_length=500, blank=True)
    slo_url = models.URLField('Sign-out URL', max_length=500, blank=True)
    metadata_url = models.URLField(max_length=500, blank=True)
    x509_cert = models.TextField('Signing certificate (PEM)', blank=True)
    client_id = models.CharField(max_length=255, blank=True)
    client_secret = models.CharField(max_length=255, blank=True)  # write-only/masked

    # LDAP / AD
    server_uri = models.CharField(max_length=255, blank=True, help_text='ldaps://host:636')
    bind_dn = models.CharField(max_length=255, blank=True)
    bind_password = models.CharField(max_length=255, blank=True)  # write-only/masked
    user_search_base = models.CharField(max_length=255, blank=True)
    user_filter = models.CharField(max_length=255, blank=True, default='(sAMAccountName=%(user)s)')

    # Provisioning
    attribute_mapping = models.JSONField(
        default=dict, blank=True,
        help_text='IdP attribute -> user field, e.g. {"email": "mail", "first_name": "givenName"}.')
    jit_provisioning = models.BooleanField(
        default=True, help_text='Auto-create a user on first successful login.')
    default_role_code = models.CharField(
        max_length=40, default='requester', help_text='Role assigned to JIT-provisioned users.')
    allowed_domains = models.CharField(
        max_length=255, blank=True, help_text='Comma-separated email domains permitted to use this IdP.')

    class Meta:
        ordering = ['name']
        unique_together = [('tenant', 'name')]
        indexes = [models.Index(fields=['tenant', 'is_active'])]

    def __str__(self):
        return f'{self.name} [{self.protocol}]'

    @property
    def protocol_color(self):
        return SSO_PROTOCOL_COLORS.get(self.protocol, 'secondary')

    @property
    def status_color(self):
        return 'success' if self.is_active else 'secondary'

    @property
    def has_secret(self):
        return bool(self.client_secret or self.bind_password)


class SSOLoginEvent(TenantAwareModel, TimeStampedModel):
    """Append-only record of an SSO sign-in attempt (or a connection test)."""

    OUTCOME_CHOICES = SSO_OUTCOME_CHOICES

    provider = models.ForeignKey(
        IdentityProvider, on_delete=models.CASCADE, related_name='login_events')
    email = models.EmailField(blank=True)
    subject_id = models.CharField(max_length=255, blank=True, help_text='IdP subject / nameID.')
    outcome = models.CharField(max_length=12, choices=SSO_OUTCOME_CHOICES, default='success')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sso_login_events')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    message = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['tenant', 'provider', 'outcome'])]

    def __str__(self):
        return f'{self.email or "—"} {self.outcome}'

    @property
    def outcome_color(self):
        return SSO_OUTCOME_COLORS.get(self.outcome, 'secondary')


# ---------------------------------------------------------------------------
# Sub-module 3 — System Configuration & Setup
# ---------------------------------------------------------------------------
DATE_FORMAT_CHOICES = [
    ('Y-m-d', '2026-12-31 (ISO)'),
    ('d/m/Y', '31/12/2026 (DMY)'),
    ('m/d/Y', '12/31/2026 (MDY)'),
    ('d M Y', '31 Dec 2026'),
]
TIME_FORMAT_CHOICES = [('H:i', '24-hour (14:30)'), ('h:i A', '12-hour (02:30 PM)')]
MONTH_CHOICES = [
    (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'), (5, 'May'), (6, 'June'),
    (7, 'July'), (8, 'August'), (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
]
TAX_TYPE_CHOICES = [
    ('vat', 'VAT'),
    ('gst', 'GST'),
    ('sales', 'Sales Tax'),
    ('wht', 'Withholding Tax'),
    ('none', 'No Tax / Exempt'),
]
RESET_FREQUENCY_CHOICES = [
    ('never', 'Never (continuous)'),
    ('yearly', 'Yearly'),
    ('monthly', 'Monthly'),
]


class SystemConfiguration(TimeStampedModel):
    """Per-tenant company-wide defaults — a 1:1 singleton (like ``tenants.SecuritySettings``)."""

    tenant = models.OneToOneField(
        'core.Tenant', on_delete=models.CASCADE, related_name='system_configuration')
    company_legal_name = models.CharField(max_length=200, blank=True)
    base_currency_code = models.CharField(max_length=3, default='USD')
    fiscal_year_start_month = models.PositiveSmallIntegerField(choices=MONTH_CHOICES, default=1)
    date_format = models.CharField(max_length=20, choices=DATE_FORMAT_CHOICES, default='Y-m-d')
    time_format = models.CharField(max_length=20, choices=TIME_FORMAT_CHOICES, default='H:i')
    decimal_places = models.PositiveSmallIntegerField(default=2)
    prices_include_tax = models.BooleanField(default=False)
    default_payment_terms_days = models.PositiveIntegerField(default=30)
    default_tax_code = models.ForeignKey(
        'sysadmin.TaxCode', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='default_for_configs')
    weekend_days = models.CharField(
        max_length=20, default='6,0', help_text='Comma-separated weekday numbers (Mon=0 … Sun=6).')
    locale = models.CharField(max_length=10, default='en-us')

    class Meta:
        ordering = ['tenant_id']

    def __str__(self):
        return f'Config for {self.tenant_id}'


class Currency(TenantAwareModel, TimeStampedModel):
    """A currency a tenant transacts in, with its exchange rate to the base currency."""

    code = models.CharField(max_length=3, help_text='ISO 4217, e.g. USD.')
    name = models.CharField(max_length=60)
    symbol = models.CharField(max_length=6, blank=True)
    decimal_places = models.PositiveSmallIntegerField(default=2)
    exchange_rate_to_base = models.DecimalField(
        max_digits=18, decimal_places=6, default=1,
        help_text='How many base-currency units one unit of this currency is worth.')
    is_base = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-is_base', 'code']
        unique_together = [('tenant', 'code')]

    def __str__(self):
        return f'{self.code} — {self.name}'

    @property
    def status_color(self):
        return 'success' if self.is_active else 'secondary'


class TaxCode(TenantAwareModel, TimeStampedModel):
    """A reusable tax rate (VAT/GST/Sales) applied across modules."""

    TAX_TYPE_CHOICES = TAX_TYPE_CHOICES

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=80)
    rate = models.DecimalField(max_digits=6, decimal_places=3, default=0, help_text='Percent.')
    tax_type = models.CharField(max_length=8, choices=TAX_TYPE_CHOICES, default='vat')
    jurisdiction = models.CharField(max_length=80, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']
        unique_together = [('tenant', 'code')]

    def __str__(self):
        return f'{self.code} ({self.rate}%)'

    @property
    def status_color(self):
        return 'success' if self.is_active else 'secondary'


class NumberSequence(TenantAwareModel, TimeStampedModel):
    """A configurable document-numbering rule (prefix + zero-padded counter + optional year).

    ``services.allocate_number`` increments ``next_number`` atomically; ``services.preview_number``
    renders the *next* value without consuming it. New code can opt in to this registry; existing
    per-module numbering is left untouched (governance-layer scope).
    """

    RESET_FREQUENCY_CHOICES = RESET_FREQUENCY_CHOICES

    doc_type = models.SlugField(max_length=40, help_text='What it numbers, e.g. "purchase_order".')
    name = models.CharField(max_length=80)
    prefix = models.CharField(max_length=12, blank=True)
    suffix = models.CharField(max_length=12, blank=True)
    padding = models.PositiveSmallIntegerField(default=5)
    next_number = models.PositiveIntegerField(default=1)
    include_year = models.BooleanField(default=False)
    reset_frequency = models.CharField(
        max_length=10, choices=RESET_FREQUENCY_CHOICES, default='never')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['doc_type']
        unique_together = [('tenant', 'doc_type')]

    def __str__(self):
        return f'{self.name} ({self.prefix})'

    @property
    def status_color(self):
        return 'success' if self.is_active else 'secondary'


# ---------------------------------------------------------------------------
# Sub-module 4 — Data Backup & Recovery
# ---------------------------------------------------------------------------
BACKUP_FREQUENCY_CHOICES = [
    ('manual', 'Manual only'),
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('monthly', 'Monthly'),
]
BACKUP_SCOPE_CHOICES = [
    ('full', 'Full (database + media)'),
    ('db_only', 'Database only'),
    ('media_only', 'Media / files only'),
]
BACKUP_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('running', 'Running'),
    ('success', 'Success'),
    ('failed', 'Failed'),
]
BACKUP_STATUS_COLORS = {
    'pending': 'secondary', 'running': 'info', 'success': 'success', 'failed': 'danger',
}
BACKUP_TRIGGER_CHOICES = [('scheduled', 'Scheduled'), ('manual', 'Manual')]

RESTORE_STATUS_CHOICES = [
    ('requested', 'Requested'),
    ('approved', 'Approved'),
    ('restored', 'Restored'),
    ('rejected', 'Rejected'),
]
RESTORE_STATUS_COLORS = {
    'requested': 'warning', 'approved': 'info', 'restored': 'success', 'rejected': 'danger',
}


class BackupPolicy(TenantAwareModel, TimeStampedModel):
    """A schedule + retention rule describing how a tenant's data is backed up."""

    FREQUENCY_CHOICES = BACKUP_FREQUENCY_CHOICES
    SCOPE_CHOICES = BACKUP_SCOPE_CHOICES

    name = models.CharField(max_length=120)
    frequency = models.CharField(max_length=10, choices=BACKUP_FREQUENCY_CHOICES, default='daily')
    scope = models.CharField(max_length=12, choices=BACKUP_SCOPE_CHOICES, default='full')
    retention_days = models.PositiveIntegerField(default=30)
    storage_target = models.CharField(
        max_length=20, default='local', help_text='local / s3 / gcs / azure.')
    storage_location = models.CharField(max_length=255, blank=True)
    encryption_enabled = models.BooleanField(default=True)
    run_hour = models.PositiveSmallIntegerField(default=2, help_text='Hour of day (0–23) to run.')
    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']
        unique_together = [('tenant', 'name')]
        indexes = [models.Index(fields=['tenant', 'is_active'])]

    def __str__(self):
        return f'{self.name} ({self.frequency})'

    @property
    def status_color(self):
        return 'success' if self.is_active else 'secondary'


class BackupRun(TenantAwareModel, TimeStampedModel):
    """Append-only history of one backup execution (scheduled or manual)."""

    STATUS_CHOICES = BACKUP_STATUS_CHOICES
    TRIGGER_CHOICES = BACKUP_TRIGGER_CHOICES

    run_number = models.CharField(max_length=40, help_text='Auto BKR-<SLUG>-NNNNN.')
    policy = models.ForeignKey(
        BackupPolicy, on_delete=models.SET_NULL, null=True, blank=True, related_name='runs')
    status = models.CharField(max_length=10, choices=BACKUP_STATUS_CHOICES, default='pending')
    trigger = models.CharField(max_length=10, choices=BACKUP_TRIGGER_CHOICES, default='manual')
    scope = models.CharField(max_length=12, choices=BACKUP_SCOPE_CHOICES, default='full')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    location = models.CharField(max_length=255, blank=True)
    checksum = models.CharField(max_length=64, blank=True)
    connector = models.CharField(max_length=20, blank=True)
    message = models.CharField(max_length=255, blank=True)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='backup_runs_triggered')

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'run_number')]
        indexes = [models.Index(fields=['tenant', 'status'])]

    def __str__(self):
        return f'{self.run_number} [{self.status}]'

    @property
    def status_color(self):
        return BACKUP_STATUS_COLORS.get(self.status, 'secondary')

    @property
    def size_mb(self):
        return round(self.size_bytes / (1024 * 1024), 2) if self.size_bytes else 0.0


class RestoreRequest(TenantAwareModel, TimeStampedModel):
    """A logged disaster-recovery request against a successful :class:`BackupRun`.

    Restore is a deliberate, audited protocol (an admin requests → another approves), not a one-click
    live DB overwrite — this model is the paper trail, never the executor.
    """

    STATUS_CHOICES = RESTORE_STATUS_CHOICES

    backup_run = models.ForeignKey(
        BackupRun, on_delete=models.CASCADE, related_name='restore_requests')
    status = models.CharField(max_length=10, choices=RESTORE_STATUS_CHOICES, default='requested')
    reason = models.TextField(blank=True)
    message = models.CharField(max_length=255, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='restore_requests_made')
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='restore_requests_decided')
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['tenant', 'status'])]

    def __str__(self):
        return f'Restore of {self.backup_run_id} [{self.status}]'

    @property
    def status_color(self):
        return RESTORE_STATUS_COLORS.get(self.status, 'secondary')


# ---------------------------------------------------------------------------
# Sub-module 5 — API & Webhook Management
# ---------------------------------------------------------------------------
WEBHOOK_DELIVERY_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('success', 'Delivered'),
    ('failed', 'Failed'),
]
WEBHOOK_DELIVERY_STATUS_COLORS = {
    'pending': 'secondary', 'success': 'success', 'failed': 'danger',
}


class ApiKey(TenantAwareModel, TimeStampedModel):
    """A credential an external system (ERP / accounting / CRM) uses to call the API.

    SECURITY: only a SHA-256 hash of the secret is stored. The plaintext is shown **once**, at
    creation, and never again — there is no field that can re-reveal it.
    """

    name = models.CharField(max_length=120)
    key_prefix = models.CharField(
        max_length=24, help_text='Public, non-secret prefix shown in lists (e.g. pms_AB12CD).')
    hashed_secret = models.CharField(max_length=64, help_text='SHA-256 of the secret. Never plaintext.')
    scopes = models.JSONField(default=list, blank=True, help_text='List of permission codes.')
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='api_keys_created')

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'key_prefix')]
        indexes = [models.Index(fields=['tenant', 'is_active'])]

    def __str__(self):
        return f'{self.name} ({self.key_prefix}…)'

    @property
    def status_color(self):
        return 'success' if self.is_active else 'secondary'

    @property
    def is_expired(self):
        from django.utils import timezone
        return bool(self.expires_at and self.expires_at < timezone.now())


class Webhook(TenantAwareModel, TimeStampedModel):
    """An outbound HTTP subscription — the app POSTs signed event payloads to ``target_url``.

    ``target_url`` is validated by a fail-closed SSRF guard (``webhooks.validate_webhook_url``);
    ``secret`` is the HMAC-SHA256 signing key (write-only/masked).
    """

    name = models.CharField(max_length=120)
    target_url = models.URLField(max_length=500)
    events = models.JSONField(default=list, blank=True, help_text='Subscribed event codes.')
    secret = models.CharField(max_length=255, blank=True, help_text='HMAC signing secret (masked).')
    custom_headers = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    last_status = models.CharField(max_length=10, blank=True)
    last_delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']
        unique_together = [('tenant', 'name')]
        indexes = [models.Index(fields=['tenant', 'is_active'])]

    def __str__(self):
        return f'{self.name} → {self.target_url[:40]}'

    @property
    def status_color(self):
        return 'success' if self.is_active else 'secondary'

    @property
    def event_count(self):
        return len(self.events or [])


class WebhookDelivery(TenantAwareModel, TimeStampedModel):
    """Append-only delivery attempt log for a :class:`Webhook` (one row per event fan-out)."""

    STATUS_CHOICES = WEBHOOK_DELIVERY_STATUS_CHOICES

    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE, related_name='deliveries')
    event = models.CharField(max_length=60)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=WEBHOOK_DELIVERY_STATUS_CHOICES, default='pending')
    status_code = models.PositiveIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField(default=0)
    response_excerpt = models.CharField(max_length=255, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'webhook', 'status']),
            models.Index(fields=['tenant', 'status']),
        ]

    def __str__(self):
        return f'{self.event} → {self.webhook_id} [{self.status}]'

    @property
    def status_color(self):
        return WEBHOOK_DELIVERY_STATUS_COLORS.get(self.status, 'secondary')
