"""Module 18: Risk & Compliance Management.

The governance layer over the whole procure-to-pay loop. Where the other modules *transact*, this
one *polices*: it screens vendors against restricted-party lists, monitors their financial health,
keeps a tamper-evident audit trail, flags suspicious purchasing patterns, and tracks sign-off on
procurement policies.

Covers the five PMS sub-modules:
  1. Regulatory Compliance Checks   -> RestrictedPartyEntry + ComplianceScreening (+ ScreeningMatch),
                                       driven by the pluggable apps/compliance/screening.py connector
  2. Supplier Financial Risk Monitoring -> FinancialRiskProfile (+ FinancialRiskSnapshot history),
                                       driven by the pluggable apps/compliance/credit.py connector
  3. Audit Trail & Logging          -> reuses apps.tenants.AuditLog (no duplicate audit infra); the
                                       tamper-evident hash-chain lives on that model, this app owns
                                       the read-only explorer + integrity-verify views
  4. Fraud Detection Rules          -> FraudRule (configurable detectors) + FraudAlert (+ event log),
                                       run by services.scan_fraud
  5. Policy Management & Acknowledgment -> Policy (+ PolicyVersion) repository + PolicyAcknowledgment

DESIGN — self-contained. Every cross-module reference is an *outbound* FK declared here (to
``vendors.Vendor`` / the user model) so no source app is migrated, and a ``FraudAlert`` points at any
offending document (PO / invoice / vendor) via CharField ``subject_type``/``subject_id`` snapshots —
the same precedent as ``AuditLog.target_type``/``target_id`` — never a hard FK to a source table.

Mirrors the recent-module conventions: TenantAwareModel + TimeStampedModel bases, module-level status
constants, gap-free ``SCR-`` / ``FRD-`` / ``POL-<SLUG>-NNNNN`` numbering (services.py), and append-only
event / snapshot timelines (``FraudAlertEvent`` / ``FinancialRiskSnapshot``).
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Module-level choice constants + helpers
# ---------------------------------------------------------------------------
# Shared risk band (reuses the vendor risk vocabulary so the two surfaces read the same).
RISK_BAND_CHOICES = [
    ('low', 'Low'),
    ('medium', 'Medium'),
    ('high', 'High'),
    ('critical', 'Critical'),
]
# Bootstrap badge colour per band (templates render {{ band }} -> colour).
BAND_COLORS = {'low': 'success', 'medium': 'info', 'high': 'warning', 'critical': 'danger'}

# 1. Screening ---------------------------------------------------------------
RP_ENTRY_TYPE_CHOICES = [
    ('person', 'Individual'),
    ('organization', 'Organization'),
    ('vessel', 'Vessel / Asset'),
]
SCREENING_STATUS_CHOICES = [
    ('clear', 'Clear — no match'),
    ('review', 'Potential match — needs review'),
    ('blocked', 'Confirmed match — blocked'),
]
SCREENING_OPEN_STATUSES = ('review',)
MATCH_DECISION_CHOICES = [
    ('pending', 'Pending review'),
    ('false_positive', 'False positive'),
    ('confirmed', 'Confirmed match'),
]

# 2. Financial risk ----------------------------------------------------------
OUTLOOK_CHOICES = [
    ('positive', 'Positive'),
    ('stable', 'Stable'),
    ('negative', 'Negative'),
]

# 4. Fraud -------------------------------------------------------------------
FRAUD_RULE_CHOICES = [
    ('split_po', 'Split purchase orders (threshold avoidance)'),
    ('duplicate_invoice', 'Duplicate invoice'),
    ('round_amount', 'Suspicious round-number amount'),
    ('vendor_bank_conflict', 'Shared vendor bank account'),
    ('conflict_of_interest', 'Vendor / employee conflict of interest'),
]
SEVERITY_CHOICES = [
    ('info', 'Info'),
    ('warning', 'Warning'),
    ('critical', 'Critical'),
]
FRAUD_STATUS_CHOICES = [
    ('open', 'Open'),
    ('investigating', 'Investigating'),
    ('confirmed', 'Confirmed'),
    ('dismissed', 'Dismissed'),
]
FRAUD_OPEN_STATUSES = ('open', 'investigating')
SEVERITY_COLORS = {'info': 'info', 'warning': 'warning', 'critical': 'danger'}
FRAUD_STATUS_COLORS = {
    'open': 'danger', 'investigating': 'warning', 'confirmed': 'dark', 'dismissed': 'secondary',
}

# 5. Policy ------------------------------------------------------------------
POLICY_CATEGORY_CHOICES = [
    ('procurement', 'Procurement'),
    ('ethics', 'Ethics & Conduct'),
    ('security', 'Security'),
    ('finance', 'Finance'),
    ('other', 'Other'),
]
POLICY_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('published', 'Published'),
    ('archived', 'Archived'),
]
POLICY_EDITABLE_STATUSES = ('draft',)


def risk_band_from_score(score) -> str:
    """Map a 0-100 financial-health score to a risk band (higher score = lower risk).

    Mirrors ``vendors.risk_level_from_score`` but inverted: a *high* credit score is *low* risk.
    """
    s = float(score or 0)
    if s >= 75:
        return 'low'
    if s >= 50:
        return 'medium'
    if s >= 25:
        return 'high'
    return 'critical'


def _score_field(**kwargs):
    """A 0-100 score field (5,2) — the project's scoring convention (matches Vendor.risk_score)."""
    kwargs.setdefault('default', Decimal('0.00'))
    kwargs.setdefault('validators', [MinValueValidator(0), MaxValueValidator(100)])
    return models.DecimalField(max_digits=5, decimal_places=2, **kwargs)


def _money(**kwargs):
    """A 14,2 money field (matches the PO / invoice money convention)."""
    kwargs.setdefault('default', Decimal('0.00'))
    return models.DecimalField(max_digits=14, decimal_places=2, **kwargs)


# ---------------------------------------------------------------------------
# 1. Regulatory Compliance Checks (restricted-party screening)
# ---------------------------------------------------------------------------
class RestrictedPartyEntry(TenantAwareModel, TimeStampedModel):
    """One record on a sanctions / denied-party / debarment list (OFAC SDN, SAM EPLS, …).

    The mock screening provider (``apps/compliance/screening.py``) fuzzy-matches a screened name
    against these rows; real providers query their own remote lists instead.
    """

    ENTRY_TYPE_CHOICES = RP_ENTRY_TYPE_CHOICES

    list_name = models.CharField(max_length=60, help_text='e.g. OFAC-SDN, SAM-EPLS, EU-CFSP.')
    entity_name = models.CharField(max_length=200)
    entry_type = models.CharField(
        max_length=12, choices=RP_ENTRY_TYPE_CHOICES, default='organization',
    )
    country = models.CharField(max_length=80, blank=True)
    program = models.CharField(max_length=120, blank=True, help_text='Sanctions program / reason.')
    aliases = models.JSONField(default=list, blank=True, help_text='Known aliases (a/k/a).')
    source_ref = models.CharField(max_length=120, blank=True, help_text='List entry id / URL.')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['entity_name']
        indexes = [
            models.Index(fields=['tenant', 'list_name']),
            models.Index(fields=['tenant', 'is_active']),
        ]

    def __str__(self):
        return f'{self.entity_name} [{self.list_name}]'


class ComplianceScreening(TenantAwareModel, TimeStampedModel):
    """One screening run of a name (usually a vendor) against the configured restricted-party lists."""

    STATUS_CHOICES = SCREENING_STATUS_CHOICES

    screening_number = models.CharField(max_length=40, help_text='Auto SCR-<SLUG>-NNNNN.')
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.PROTECT, null=True, blank=True,
        related_name='compliance_screenings',
        help_text='Screened vendor (blank = an ad-hoc name screen).',
    )
    screened_name = models.CharField(max_length=200, help_text='The name actually screened.')
    provider = models.CharField(max_length=40, default='mock')
    status = models.CharField(max_length=10, choices=SCREENING_STATUS_CHOICES, default='clear')
    match_count = models.PositiveIntegerField(default=0)
    lists_checked = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    screened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='compliance_screenings',
    )
    screened_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'screening_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'vendor']),
        ]

    def __str__(self):
        return f'{self.screening_number} — {self.screened_name} ({self.status})'

    @property
    def status_color(self):
        return {'clear': 'success', 'review': 'warning', 'blocked': 'danger'}.get(
            self.status, 'secondary')

    @property
    def is_hit(self):
        return self.status in ('review', 'blocked')


class ScreeningMatch(TenantAwareModel, TimeStampedModel):
    """A single hit produced by a screening run, with its disposition."""

    DECISION_CHOICES = MATCH_DECISION_CHOICES

    screening = models.ForeignKey(
        ComplianceScreening, on_delete=models.CASCADE, related_name='matches',
    )
    entry = models.ForeignKey(
        RestrictedPartyEntry, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='matches',
    )
    matched_name = models.CharField(max_length=200)
    list_name = models.CharField(max_length=60, blank=True)
    score = _score_field(help_text='Fuzzy match confidence (0-100).')
    matched_field = models.CharField(max_length=40, blank=True, help_text='name / alias.')
    decision = models.CharField(
        max_length=15, choices=MATCH_DECISION_CHOICES, default='pending',
    )
    notes = models.CharField(max_length=255, blank=True)
    dispositioned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='screening_dispositions',
    )
    dispositioned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-score', 'id']

    def __str__(self):
        return f'{self.matched_name} ({self.score}%)'


# ---------------------------------------------------------------------------
# 2. Supplier Financial Risk Monitoring
# ---------------------------------------------------------------------------
class FinancialRiskProfile(TenantAwareModel, TimeStampedModel):
    """The current financial-risk posture of one vendor (one row per vendor).

    ``credit_score`` comes from the pluggable credit provider; ``exposure_amount`` /
    ``overdue_invoice_amount`` are computed from the vendor's open POs + unpaid invoices at refresh.
    """

    BAND_CHOICES = RISK_BAND_CHOICES
    OUTLOOK_CHOICES = OUTLOOK_CHOICES

    vendor = models.OneToOneField(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='financial_risk_profile',
    )
    monitored = models.BooleanField(
        default=True, help_text='Whether the cron refresh keeps this vendor up to date.',
    )
    credit_score = _score_field(help_text='Latest 0-100 credit-health score (higher = healthier).')
    band = models.CharField(max_length=10, choices=RISK_BAND_CHOICES, default='low')
    outlook = models.CharField(max_length=10, choices=OUTLOOK_CHOICES, default='stable')
    exposure_amount = _money(help_text='Open commitments + unpaid invoices at last refresh.')
    overdue_invoice_amount = _money()
    provider = models.CharField(max_length=40, default='mock')
    last_checked_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)
    # Idempotency stamp for the cron score-drop sweep (scan_financial_alerts).
    alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-exposure_amount', 'vendor_id']
        indexes = [
            models.Index(fields=['tenant', 'band']),
            models.Index(fields=['tenant', 'monitored']),
        ]

    def __str__(self):
        return f'{self.vendor_id}: {self.band} ({self.credit_score})'

    @property
    def band_color(self):
        return BAND_COLORS.get(self.band, 'secondary')

    @property
    def is_high_risk(self):
        return self.band in ('high', 'critical')


class FinancialRiskSnapshot(TenantAwareModel, TimeStampedModel):
    """An append-only point-in-time reading — drives the trend chart and score-drop alerts."""

    BAND_CHOICES = RISK_BAND_CHOICES

    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='financial_risk_snapshots',
    )
    profile = models.ForeignKey(
        FinancialRiskProfile, on_delete=models.CASCADE, null=True, blank=True,
        related_name='snapshots',
    )
    as_of_date = models.DateField()
    credit_score = _score_field()
    band = models.CharField(max_length=10, choices=RISK_BAND_CHOICES, default='low')
    outlook = models.CharField(max_length=10, choices=OUTLOOK_CHOICES, default='stable')
    exposure_amount = _money()
    overdue_amount = _money()
    open_po_count = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=40, default='mock')
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-as_of_date', '-created_at']
        indexes = [
            models.Index(fields=['tenant', 'vendor', 'as_of_date']),
        ]

    def __str__(self):
        return f'{self.vendor_id} @ {self.as_of_date}: {self.credit_score}'

    @property
    def band_color(self):
        return BAND_COLORS.get(self.band, 'secondary')


# ---------------------------------------------------------------------------
# 4. Fraud Detection Rules
# ---------------------------------------------------------------------------
class FraudRule(TenantAwareModel, TimeStampedModel):
    """A configurable fraud detector. ``code`` is the dispatch key services.scan_fraud runs."""

    CODE_CHOICES = FRAUD_RULE_CHOICES
    SEVERITY_CHOICES = SEVERITY_CHOICES

    code = models.CharField(max_length=30, choices=FRAUD_RULE_CHOICES)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    severity = models.CharField(max_length=8, choices=SEVERITY_CHOICES, default='warning')
    params = models.JSONField(
        default=dict, blank=True,
        help_text='Tuning, e.g. {"window_days": 14, "amount_floor": 5000}.',
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'name']
        unique_together = [('tenant', 'code')]
        indexes = [
            models.Index(fields=['tenant', 'is_active']),
        ]

    def __str__(self):
        return f'{self.name} ({self.code})'

    @property
    def severity_color(self):
        return SEVERITY_COLORS.get(self.severity, 'secondary')


class FraudAlert(TenantAwareModel, TimeStampedModel):
    """A finding raised by a fraud rule against an offending document (PO / invoice / vendor).

    The offender is referenced by CharField ``subject_type``/``subject_id`` snapshots (the
    ``AuditLog.target_*`` precedent) so an alert can point at any source row with no hard FK and no
    source-app migration. ``signature`` is a stable dedupe key so re-scans never duplicate an alert.
    """

    SEVERITY_CHOICES = SEVERITY_CHOICES
    STATUS_CHOICES = FRAUD_STATUS_CHOICES

    alert_number = models.CharField(max_length=40, help_text='Auto FRD-<SLUG>-NNNNN.')
    rule = models.ForeignKey(
        FraudRule, on_delete=models.SET_NULL, null=True, blank=True, related_name='alerts',
    )
    rule_code = models.CharField(max_length=30, blank=True, help_text='Snapshot of the rule code.')
    rule_name = models.CharField(max_length=120, blank=True)
    severity = models.CharField(max_length=8, choices=SEVERITY_CHOICES, default='warning')
    status = models.CharField(max_length=15, choices=FRAUD_STATUS_CHOICES, default='open')
    subject_type = models.CharField(
        max_length=40, blank=True, help_text='e.g. PurchaseOrder / SupplierInvoice / Vendor.',
    )
    subject_id = models.CharField(max_length=80, blank=True)
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fraud_alerts',
    )
    summary = models.CharField(max_length=255)
    evidence = models.JSONField(default=dict, blank=True, help_text='Matched group / amounts / ids.')
    signature = models.CharField(
        max_length=120, help_text='Stable dedupe key (rule + offending entity set).',
    )
    detected_at = models.DateTimeField(null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fraud_alerts_assigned',
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fraud_alerts_resolved',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-detected_at', '-created_at']
        unique_together = [('tenant', 'signature')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'severity']),
            models.Index(fields=['tenant', 'vendor']),
        ]

    def __str__(self):
        return f'{self.alert_number} — {self.summary[:50]}'

    @property
    def severity_color(self):
        return SEVERITY_COLORS.get(self.severity, 'secondary')

    @property
    def status_color(self):
        return FRAUD_STATUS_COLORS.get(self.status, 'secondary')

    @property
    def is_open(self):
        return self.status in FRAUD_OPEN_STATUSES


class FraudAlertEvent(TenantAwareModel, TimeStampedModel):
    """An immutable entry in a fraud alert's investigation timeline."""

    alert = models.ForeignKey(
        FraudAlert, on_delete=models.CASCADE, related_name='events',
    )
    from_status = models.CharField(max_length=15, blank=True)
    to_status = models.CharField(max_length=15)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fraud_alert_events',
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.alert_id}: {self.from_status or "—"} → {self.to_status}'


# ---------------------------------------------------------------------------
# 5. Policy Management & Acknowledgment
# ---------------------------------------------------------------------------
class Policy(TenantAwareModel, TimeStampedModel):
    """A governance policy in the repository. Bodies live on immutable ``PolicyVersion`` rows."""

    CATEGORY_CHOICES = POLICY_CATEGORY_CHOICES
    STATUS_CHOICES = POLICY_STATUS_CHOICES

    policy_number = models.CharField(max_length=40, help_text='Auto POL-<SLUG>-NNNNN.')
    title = models.CharField(max_length=200)
    category = models.CharField(
        max_length=15, choices=POLICY_CATEGORY_CHOICES, default='procurement',
    )
    summary = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=POLICY_STATUS_CHOICES, default='draft')
    requires_acknowledgment = models.BooleanField(
        default=True, help_text='Whether users must sign off on the published version.',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='policies_owned',
    )
    current_version = models.ForeignKey(
        'compliance.PolicyVersion', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='current_for', help_text='The published version users acknowledge.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='policies_created',
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'policy_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'category']),
        ]

    def __str__(self):
        return f'{self.policy_number} — {self.title}'

    @property
    def status_color(self):
        return {'draft': 'secondary', 'published': 'success', 'archived': 'dark'}.get(
            self.status, 'secondary')

    @property
    def is_editable(self):
        return self.status in POLICY_EDITABLE_STATUSES

    @property
    def is_published(self):
        return self.status == 'published'


class PolicyVersion(TenantAwareModel, TimeStampedModel):
    """An immutable, numbered revision of a policy's text."""

    policy = models.ForeignKey(
        Policy, on_delete=models.CASCADE, related_name='versions',
    )
    version_no = models.PositiveIntegerField(default=1)
    body = models.TextField()
    change_note = models.CharField(max_length=255, blank=True)
    effective_date = models.DateField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='policy_versions_published',
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-version_no']
        unique_together = [('policy', 'version_no')]

    def __str__(self):
        return f'{self.policy_id} v{self.version_no}'


class PolicyAcknowledgment(TenantAwareModel, TimeStampedModel):
    """A user's sign-off on a specific policy version (one per user per version)."""

    policy_version = models.ForeignKey(
        PolicyVersion, on_delete=models.CASCADE, related_name='acknowledgments',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='policy_acknowledgments',
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-acknowledged_at']
        unique_together = [('tenant', 'policy_version', 'user')]
        indexes = [
            models.Index(fields=['tenant', 'user']),
        ]

    def __str__(self):
        return f'{self.user_id} ack {self.policy_version_id}'
