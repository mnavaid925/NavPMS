"""Module 1: Tenant & Subscription Management.

Covers the five PMS sub-modules:
  1. Tenant Onboarding         -> handled by Tenant + Subscription + views
  2. Subscription & Billing    -> Plan, Subscription, Invoice, Transaction
  3. Tenant Isolation/Security -> SecuritySettings
  4. Custom Branding           -> BrandingSettings
  5. Tenant Health Monitoring  -> AuditLog, HealthMetric
"""
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import Tenant, TenantAwareModel, TimeStampedModel


# ---------- 2. Subscription & Billing ----------

class Plan(TimeStampedModel):
    """A subscription plan (Free, Starter, Pro, Enterprise)."""

    BILLING_CYCLES = [('monthly', 'Monthly'), ('yearly', 'Yearly')]

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=3, default='USD')
    trial_days = models.PositiveIntegerField(default=14)
    max_users = models.PositiveIntegerField(default=5)
    max_storage_gb = models.PositiveIntegerField(default=1)
    max_vendors = models.PositiveIntegerField(default=50)
    max_purchase_orders_per_month = models.PositiveIntegerField(default=100)
    features = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True, help_text='Show on pricing page')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'price_monthly']

    def __str__(self):
        return self.name


class Subscription(TimeStampedModel):
    """A tenant's enrollment in a plan."""

    STATUS_CHOICES = [
        ('trial', 'Trial'),
        ('active', 'Active'),
        ('past_due', 'Past Due'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    ]
    BILLING_CYCLES = [('monthly', 'Monthly'), ('yearly', 'Yearly')]

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='subscriptions',
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='trial')
    billing_cycle = models.CharField(max_length=10, choices=BILLING_CYCLES, default='monthly')
    started_at = models.DateTimeField(default=timezone.now)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.tenant} -> {self.plan} ({self.status})'

    @property
    def is_trialing(self):
        return self.status == 'trial' and self.trial_ends_at and self.trial_ends_at > timezone.now()

    @property
    def amount_for_cycle(self):
        return self.plan.price_yearly if self.billing_cycle == 'yearly' else self.plan.price_monthly


class Invoice(TimeStampedModel):
    """An invoice issued to a tenant for a subscription period."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('void', 'Void'),
        ('refunded', 'Refunded'),
    ]

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='invoices',
    )
    subscription = models.ForeignKey(
        Subscription, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoices',
    )
    number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=3, default='USD')
    line_items = models.JSONField(default=list, blank=True)
    issued_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-issued_at']

    def __str__(self):
        return f'{self.number} ({self.status})'


class Transaction(TimeStampedModel):
    """A payment attempt against an invoice."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='transactions',
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='transactions',
    )
    gateway = models.CharField(max_length=40, default='mock')
    gateway_ref = models.CharField(max_length=120, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    method = models.CharField(max_length=40, blank=True, help_text='card / ach / wallet')
    message = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.gateway_ref or "?"} - {self.amount} ({self.status})'


# ---------- 4. Custom Branding ----------

class BrandingSettings(TimeStampedModel):
    """Per-tenant white-label settings (logo, colors, email branding)."""

    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name='branding',
    )
    logo = models.ImageField(upload_to='branding/logos/', blank=True, null=True)
    logo_dark = models.ImageField(upload_to='branding/logos/', blank=True, null=True)
    favicon = models.ImageField(upload_to='branding/favicons/', blank=True, null=True)
    primary_color = models.CharField(max_length=9, default='#3b5de7')
    secondary_color = models.CharField(max_length=9, default='#5fa8ff')
    login_background = models.ImageField(
        upload_to='branding/backgrounds/', blank=True, null=True,
    )
    email_from_name = models.CharField(max_length=120, blank=True)
    email_from_address = models.EmailField(blank=True)
    email_signature = models.TextField(blank=True)
    support_url = models.URLField(blank=True)
    support_email = models.EmailField(blank=True)

    def __str__(self):
        return f'Branding for {self.tenant}'


# ---------- 3. Tenant Isolation & Security ----------

class SecuritySettings(TimeStampedModel):
    """Per-tenant security policy (password, MFA, sessions, IP allowlist)."""

    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name='security',
    )
    password_min_length = models.PositiveIntegerField(default=8)
    password_require_uppercase = models.BooleanField(default=True)
    password_require_number = models.BooleanField(default=True)
    password_require_special = models.BooleanField(default=False)
    password_expiry_days = models.PositiveIntegerField(default=0, help_text='0 = never')
    mfa_required = models.BooleanField(default=False)
    session_timeout_minutes = models.PositiveIntegerField(default=60 * 8)
    ip_allowlist = models.TextField(
        blank=True, help_text='One CIDR per line. Empty = allow all.',
    )
    allowed_login_domains = models.TextField(
        blank=True, help_text='Comma-separated, e.g. acme.com,partner.com',
    )
    encryption_key_id = models.CharField(
        max_length=120, blank=True, help_text='KMS key reference (read-only display)',
    )

    def __str__(self):
        return f'Security for {self.tenant}'


# ---------- 5. Tenant Health Monitoring ----------

class AuditLog(TenantAwareModel, TimeStampedModel):
    """Tamper-evident audit trail (append-only)."""

    LEVEL_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs',
    )
    action = models.CharField(max_length=80)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='info')
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    message = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    # Tamper-evident hash chain (Module 18, sub-module 3). Each row's row_hash is sha256 of the
    # previous row's row_hash + this row's canonical content, so editing/deleting any historic row
    # breaks the chain from that point on. Set by services.record_audit; verified by
    # services.verify_audit_chain. Blank on pre-chain rows until backfilled.
    prev_hash = models.CharField(max_length=64, blank=True)
    row_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'created_at']),
            models.Index(fields=['tenant', 'action']),
        ]

    def __str__(self):
        return f'{self.action} ({self.level}) by {self.user_id or "system"}'


class HealthMetric(TenantAwareModel):
    """Periodic snapshot of a single tenant-level metric."""

    METRIC_TYPES = [
        ('user_count', 'Active users'),
        ('storage_mb', 'Storage (MB)'),
        ('api_calls', 'API calls (24h)'),
        ('active_sessions', 'Active sessions'),
        ('error_rate', 'Error rate (%)'),
    ]

    metric_type = models.CharField(max_length=30, choices=METRIC_TYPES)
    value = models.DecimalField(max_digits=14, decimal_places=2)
    recorded_at = models.DateTimeField(default=timezone.now)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['tenant', 'metric_type', 'recorded_at']),
        ]

    def __str__(self):
        return f'{self.metric_type}={self.value} @ {self.recorded_at:%Y-%m-%d}'
