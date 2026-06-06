"""Module 17: Supplier Performance & Evaluation.

Turns the transactional data the system already captures (purchase orders, goods receipts, RFx
responses, supplier invoices) into vendor performance scores. The missing feedback loop that closes
procure-to-pay: we know *what* a vendor delivered — this module grades *how well*.

Covers the five PMS sub-modules:
  1. KPI Definition & Setup        -> KpiDefinition (configurable metric per tenant)
  2. Scorecard Generation          -> Scorecard (+ ScorecardLine) — a period-bound snapshot
  3. 360-Degree Feedback Collection -> PerformanceFeedback (internal stakeholder reviews)
  4. Performance Improvement Plans  -> ImprovementPlan (+ PIPAction + PIPStatusEvent timeline)
  5. Benchmarking & Trending        -> services (over time / against the tenant average)

DESIGN — scorecards are a **snapshot, not compute-on-read** (the deliberate inverse of Module 16
Budget). A scorecard is a point-in-time evaluation that feeds trending, PIP triggers and the
denormalised ``Vendor.performance_score``. If we recomputed on read, last quarter's score would
drift whenever a GRN/invoice was edited, breaking the trend line and the PIP audit trail. So
``services.generate_scorecard`` reads the source tables once and **persists** every ``ScorecardLine``
(raw value, normalised score, weight). Each line snapshots the KPI's code/name/type/direction/target
too, so a later KPI rename or delete never rewrites history. (Live "current-quarter-so-far" dashboard
tiles may still compute provisionally.)

Mirrors the recent-module conventions: TenantAwareModel + TimeStampedModel bases, module-level status
constants, gap-free ``SPC-<SLUG>-NNNNN`` / ``PIP-<SLUG>-NNNNN`` numbering (services.py), and an
append-only status-event timeline (``PIPStatusEvent``, like ``BudgetStatusEvent``).
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Module-level choice constants + helpers
# ---------------------------------------------------------------------------
KPI_TYPE_CHOICES = [
    ('on_time_delivery', 'On-Time Delivery'),
    ('defect_rate', 'Defect / Quality Rate'),
    ('responsiveness', 'Responsiveness'),
    ('price_variance', 'Price / Cost Variance'),
    ('feedback', '360° Feedback'),
    ('custom', 'Custom / Manual'),
]
# Which KPI types the engine can compute automatically from transactional data.
AUTO_KPI_TYPES = ('on_time_delivery', 'defect_rate', 'responsiveness', 'price_variance')

KPI_SOURCE_CHOICES = [
    ('auto', 'Auto-computed'),
    ('manual', 'Manual entry'),
    ('feedback', 'Feedback aggregate'),
]

KPI_DIRECTION_CHOICES = [
    ('higher_better', 'Higher is better'),
    ('lower_better', 'Lower is better'),
]

SCORECARD_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('final', 'Final'),
    ('archived', 'Archived'),
]
SCORECARD_EDITABLE_STATUSES = ('draft',)

RATING_BAND_CHOICES = [
    ('excellent', 'Excellent'),
    ('good', 'Good'),
    ('acceptable', 'Acceptable'),
    ('poor', 'Poor'),
    ('critical', 'Critical'),
]
# Bands that flag a vendor as a PIP candidate.
UNDERPERFORMING_BANDS = ('poor', 'critical')
# Bootstrap badge colour per band (templates render {{ band }} -> colour).
BAND_COLORS = {
    'excellent': 'success', 'good': 'primary', 'acceptable': 'info',
    'poor': 'warning', 'critical': 'danger',
}

FEEDBACK_STATUS_CHOICES = [
    ('requested', 'Requested'),
    ('submitted', 'Submitted'),
    ('declined', 'Declined'),
    ('cancelled', 'Cancelled'),
]

PIP_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('open', 'Open'),
    ('in_progress', 'In Progress'),
    ('completed', 'Completed'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]
PIP_OPEN_STATUSES = ('draft', 'open', 'in_progress')

PIP_SEVERITY_CHOICES = [
    ('low', 'Low'),
    ('medium', 'Medium'),
    ('high', 'High'),
]

PIP_ACTION_STATUS_CHOICES = [
    ('open', 'Open'),
    ('done', 'Done'),
    ('cancelled', 'Cancelled'),
]


def rating_band_from_score(score) -> str:
    """Map an overall 0-100 score to a rating band (mirrors ``vendors.risk_level_from_score``)."""
    s = float(score or 0)
    if s >= 90:
        return 'excellent'
    if s >= 75:
        return 'good'
    if s >= 60:
        return 'acceptable'
    if s >= 40:
        return 'poor'
    return 'critical'


def _score_field(**kwargs):
    """A 0-100 normalised-score field (5,2) — the project's scoring convention."""
    kwargs.setdefault('default', Decimal('0.00'))
    kwargs.setdefault('validators', [MinValueValidator(0), MaxValueValidator(100)])
    return models.DecimalField(max_digits=5, decimal_places=2, **kwargs)


def _weight_field(**kwargs):
    """A 0-100 weight field (5,2)."""
    kwargs.setdefault('default', Decimal('0.00'))
    kwargs.setdefault('validators', [MinValueValidator(0)])
    return models.DecimalField(max_digits=5, decimal_places=2, **kwargs)


# ---------------------------------------------------------------------------
# 1. KPI Definition & Setup
# ---------------------------------------------------------------------------
class KpiDefinition(TenantAwareModel, TimeStampedModel):
    """A configurable performance metric for a tenant.

    ``kpi_type`` is the dispatch key the engine uses to compute the raw value (see
    ``services.compute_kpi_value``). ``direction`` + ``target_value`` drive normalisation to a 0-100
    ``score`` (``services.normalize_score``). ``weight`` is the metric's share of the overall
    scorecard (weights of the active KPIs are re-normalised over the metrics that actually scored).
    """

    KPI_TYPE_CHOICES = KPI_TYPE_CHOICES
    SOURCE_CHOICES = KPI_SOURCE_CHOICES
    DIRECTION_CHOICES = KPI_DIRECTION_CHOICES

    code = models.CharField(max_length=40, help_text='Stable key, e.g. OTD / DEF / RESP.')
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    kpi_type = models.CharField(max_length=20, choices=KPI_TYPE_CHOICES, default='custom')
    source = models.CharField(max_length=10, choices=KPI_SOURCE_CHOICES, default='auto')
    direction = models.CharField(
        max_length=13, choices=KPI_DIRECTION_CHOICES, default='higher_better',
    )
    weight = _weight_field(help_text='Percent weight in the overall scorecard.')
    target_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Goal raw value, e.g. 95 (% on-time) or 2 (% defects).',
    )
    unit = models.CharField(max_length=20, blank=True, help_text='%, days, count…')
    green_threshold = _score_field(
        default=Decimal('80.00'), help_text='Normalised score at/above which the line is green.',
    )
    amber_threshold = _score_field(
        default=Decimal('60.00'), help_text='Normalised score at/above which the line is amber.',
    )
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'name']
        unique_together = [('tenant', 'code')]
        indexes = [
            models.Index(fields=['tenant', 'is_active']),
        ]

    def __str__(self):
        return f'{self.code} — {self.name}'

    @property
    def is_auto(self):
        return self.source == 'auto' and self.kpi_type in AUTO_KPI_TYPES


# ---------------------------------------------------------------------------
# 2. Scorecard Generation (period-bound snapshot)
# ---------------------------------------------------------------------------
class Scorecard(TenantAwareModel, TimeStampedModel):
    """A point-in-time performance evaluation of one vendor over a period.

    ``overall_score`` is the weighted mean of its lines' normalised scores (over the lines that
    actually scored) and is frozen at generation. ``is_current`` marks the latest *final* card per
    vendor — it drives the denormalised ``Vendor.performance_*`` fields and the benchmarking page.
    """

    STATUS_CHOICES = SCORECARD_STATUS_CHOICES
    RATING_BAND_CHOICES = RATING_BAND_CHOICES

    scorecard_number = models.CharField(max_length=40, help_text='Auto SPC-<SLUG>-NNNNN.')
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.PROTECT, related_name='scorecards',
    )
    period_label = models.CharField(max_length=40, help_text='e.g. "Q1 2026".')
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=10, choices=SCORECARD_STATUS_CHOICES, default='draft')
    overall_score = _score_field()
    rating_band = models.CharField(
        max_length=12, choices=RATING_BAND_CHOICES, default='acceptable',
    )
    is_current = models.BooleanField(
        default=False, help_text='The latest final scorecard for the vendor.',
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='scorecards_generated',
    )
    generated_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-period_end', '-created_at']
        unique_together = [('tenant', 'scorecard_number')]
        indexes = [
            models.Index(fields=['tenant', 'vendor', 'is_current']),
            models.Index(fields=['tenant', 'vendor', 'period_end']),
            models.Index(fields=['tenant', 'status']),
        ]

    def __str__(self):
        return f'{self.scorecard_number} — {self.vendor_id} ({self.period_label})'

    @property
    def is_editable(self):
        return self.status in SCORECARD_EDITABLE_STATUSES

    @property
    def is_final(self):
        return self.status == 'final'

    @property
    def band_color(self):
        return BAND_COLORS.get(self.rating_band, 'secondary')

    @property
    def is_underperforming(self):
        return self.rating_band in UNDERPERFORMING_BANDS


class ScorecardLine(TenantAwareModel, TimeStampedModel):
    """One KPI's contribution to a scorecard — fully snapshotted at generation time."""

    scorecard = models.ForeignKey(
        Scorecard, on_delete=models.CASCADE, related_name='lines',
    )
    kpi = models.ForeignKey(
        KpiDefinition, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='scorecard_lines',
    )
    # Snapshots — survive a later KPI rename/delete so historic cards stay readable.
    kpi_code = models.CharField(max_length=40, blank=True)
    kpi_name = models.CharField(max_length=120, blank=True)
    kpi_type = models.CharField(max_length=20, blank=True)
    direction = models.CharField(max_length=13, blank=True)
    target_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)

    raw_value = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        help_text='The measured metric (None = no source data in-period).',
    )
    score = _score_field(null=True, blank=True, help_text='Normalised 0-100 (None = not scored).')
    weight = _weight_field(help_text='Weight snapshot at generation.')
    weighted_score = _score_field(help_text='score * weight / 100 (display only).')
    data_points = models.CharField(
        max_length=255, blank=True, help_text='Evidence, e.g. "138/150 receipts on time".',
    )
    is_manual = models.BooleanField(default=False)

    class Meta:
        ordering = ['id']
        unique_together = [('scorecard', 'kpi')]

    def __str__(self):
        return f'{self.kpi_code or self.kpi_id}: {self.score}'

    @property
    def band_color(self):
        """Green/amber/red for the line, using the KPI's thresholds (snapshot-safe via score)."""
        if self.score is None:
            return 'secondary'
        s = float(self.score)
        if self.kpi_id and self.kpi:
            if s >= float(self.kpi.green_threshold):
                return 'success'
            if s >= float(self.kpi.amber_threshold):
                return 'warning'
            return 'danger'
        if s >= 80:
            return 'success'
        if s >= 60:
            return 'warning'
        return 'danger'


# ---------------------------------------------------------------------------
# 3. 360-Degree Feedback Collection
# ---------------------------------------------------------------------------
class PerformanceFeedback(TenantAwareModel, TimeStampedModel):
    """An internal stakeholder's review of a vendor. Aggregated into the ``feedback``-type KPI.

    A manager *requests* feedback from a reviewer (creating a ``requested`` row + a notification);
    the reviewer *submits* a 1-5 rating with optional facet ratings and comments.
    """

    STATUS_CHOICES = FEEDBACK_STATUS_CHOICES

    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='performance_feedback',
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vendor_feedback_given', help_text='The internal stakeholder reviewing.',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vendor_feedback_requested',
    )
    period_label = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=12, choices=FEEDBACK_STATUS_CHOICES, default='requested')
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text='Overall 1 (poor) to 5 (excellent).',
    )
    quality_rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    delivery_rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    communication_rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    would_recommend = models.BooleanField(null=True, blank=True)
    comments = models.TextField(blank=True)
    requested_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'vendor', 'status']),
            models.Index(fields=['tenant', 'reviewer']),
        ]

    def __str__(self):
        return f'Feedback {self.vendor_id} by {self.reviewer_id} ({self.status})'

    @property
    def is_submitted(self):
        return self.status == 'submitted'


# ---------------------------------------------------------------------------
# 4. Performance Improvement Plans (PIP)
# ---------------------------------------------------------------------------
class ImprovementPlan(TenantAwareModel, TimeStampedModel):
    """A corrective-action plan opened against an underperforming vendor."""

    STATUS_CHOICES = PIP_STATUS_CHOICES
    SEVERITY_CHOICES = PIP_SEVERITY_CHOICES

    pip_number = models.CharField(max_length=40, help_text='Auto PIP-<SLUG>-NNNNN.')
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.PROTECT, related_name='improvement_plans',
    )
    scorecard = models.ForeignKey(
        Scorecard, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='improvement_plans', help_text='The scorecard that triggered the plan.',
    )
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True, help_text='Root cause / context.')
    status = models.CharField(max_length=12, choices=PIP_STATUS_CHOICES, default='draft')
    severity = models.CharField(max_length=8, choices=PIP_SEVERITY_CHOICES, default='medium')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='improvement_plans_owned', help_text='Internal owner driving the plan.',
    )
    target_date = models.DateField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='improvement_plans_created',
    )
    # Idempotency stamp for the cron overdue-PIP sweep (scan_pip_alerts).
    alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'pip_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'vendor']),
        ]

    def __str__(self):
        return f'{self.pip_number} — {self.title}'

    @property
    def is_open(self):
        return self.status in PIP_OPEN_STATUSES

    @property
    def is_editable(self):
        return self.status in ('draft', 'open', 'in_progress')


class PIPAction(TenantAwareModel, TimeStampedModel):
    """A corrective action item on a PIP."""

    STATUS_CHOICES = PIP_ACTION_STATUS_CHOICES

    improvement_plan = models.ForeignKey(
        ImprovementPlan, on_delete=models.CASCADE, related_name='actions',
    )
    line_no = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=PIP_ACTION_STATUS_CHOICES, default='open')
    due_date = models.DateField(null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pip_actions_assigned',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['line_no', 'id']
        unique_together = [('improvement_plan', 'line_no')]

    def __str__(self):
        return f'{self.improvement_plan_id} #{self.line_no}: {self.description[:40]}'


class PIPStatusEvent(TenantAwareModel, TimeStampedModel):
    """An immutable entry in a PIP's lifecycle timeline (mirrors ``BudgetStatusEvent``)."""

    improvement_plan = models.ForeignKey(
        ImprovementPlan, on_delete=models.CASCADE, related_name='status_events',
    )
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pip_status_events',
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.improvement_plan_id}: {self.from_status or "—"} → {self.to_status}'
