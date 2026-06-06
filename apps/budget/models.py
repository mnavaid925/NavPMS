"""Module 16: Budget & Cost Management.

The financial-control layer across the procure-to-pay loop. It caps requisition spend before it
starts (availability check), encumbers it once a PO is issued (commitment accounting), and
reconciles it against actually-invoiced spend (variance + forecasting).

Covers the five PMS sub-modules:
  1. Budget Allocation & Mapping  -> Budget (+ BudgetAllocation lines) mapped to a cost-centre /
                                     GL code (``requisitions.AccountCode``) within a BudgetPeriod
  2. Budget Availability Check    -> services.check_requisition_budget (called from
                                     requisitions.submit_requisition) + BudgetCheck audit rows
  3. Commitment Accounting        -> "committed" = open-PO line value, computed on read
  4. Variance Analysis            -> services.variance_report (allocated vs actual vs committed)
  5. Forecasting & Projection     -> services.forecast (run-rate + open commitments)

DESIGN — consumption is **never stored**. ``committed`` (open PO lines), ``actual`` (approved/paid
invoice lines) and ``reserved`` (open requisition lines) are all computed on read from the
authoritative transactional tables, scoped by ``account_code`` + the budget's period dates. There
is therefore no ledger and no reversal hooks — a status change on a PO / invoice / requisition is
reflected on the next read. The dimension is the existing ``requisitions.AccountCode`` (the same
"cost centre / GL" dimension used by Module 15 Spend Analytics, PO lines and invoice lines).

Mirrors the recent-module conventions: TenantAwareModel + TimeStampedModel bases, module-level
status constants, gap-free ``BUD-<SLUG>-NNNNN`` numbering (services.py), and append-only event /
check timelines (``BudgetStatusEvent`` / ``BudgetCheck``).
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Module-level choice constants + consumption policy
# ---------------------------------------------------------------------------
PERIOD_TYPE_CHOICES = [
    ('annual', 'Annual / Fiscal year'),
    ('quarterly', 'Quarterly'),
    ('monthly', 'Monthly'),
    ('custom', 'Custom range'),
]

PERIOD_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('active', 'Active'),
    ('locked', 'Locked'),
    ('closed', 'Closed'),
]
PERIOD_OPEN_STATUSES = ('draft', 'active')

BUDGET_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('active', 'Active'),
    ('closed', 'Closed'),
]
BUDGET_EDITABLE_STATUSES = ('draft',)
BUDGET_ACTIVE_STATUSES = ('active',)

CHECK_RESULT_CHOICES = [
    ('pass', 'Within budget'),
    ('warn', 'Over budget (warned)'),
    ('block', 'Over budget (blocked)'),
]

# Source-document statuses that feed compute-on-read consumption. Kept here (not imported from the
# source apps) so this module owns its own financial policy and the values are visible in one place.
ACTUAL_INVOICE_STATUSES = ('approved', 'paid')           # money actually billed
COMMITTED_PO_STATUSES = ('issued', 'acknowledged', 'partially_received')  # firm, open encumbrance
RESERVED_REQUISITION_STATUSES = ('submitted', 'approved')  # soft pre-commitment, not yet a PO


def _money(**kwargs):
    """A 14,2 money field (matches the PO / invoice / requisition money convention)."""
    kwargs.setdefault('default', Decimal('0.00'))
    return models.DecimalField(max_digits=14, decimal_places=2, **kwargs)


# ---------------------------------------------------------------------------
# 1. Budget Allocation & Mapping
# ---------------------------------------------------------------------------
class BudgetPeriod(TenantAwareModel, TimeStampedModel):
    """A fiscal envelope (year / quarter / month) that budgets are scoped to.

    Consumption is matched against a period by its ``start_date``/``end_date`` window, so a budget's
    actual / committed / reserved figures only count source documents dated inside the period.
    """

    PERIOD_TYPE_CHOICES = PERIOD_TYPE_CHOICES
    STATUS_CHOICES = PERIOD_STATUS_CHOICES

    name = models.CharField(max_length=120, help_text='e.g. "FY2026" or "Q1 2026".')
    period_type = models.CharField(
        max_length=12, choices=PERIOD_TYPE_CHOICES, default='annual',
    )
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=10, choices=PERIOD_STATUS_CHOICES, default='draft')
    is_default = models.BooleanField(
        default=False, help_text='The period new budgets default to.',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-start_date', 'name']
        unique_together = [('tenant', 'name')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
        ]

    def __str__(self):
        return self.name

    @property
    def is_open(self):
        return self.status in PERIOD_OPEN_STATUSES


class Budget(TenantAwareModel, TimeStampedModel):
    """A named budget for one period — a container of per-cost-centre allocation lines."""

    STATUS_CHOICES = BUDGET_STATUS_CHOICES

    budget_number = models.CharField(max_length=40, help_text='Auto BUD-<SLUG>-NNNNN.')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    period = models.ForeignKey(
        BudgetPeriod, on_delete=models.PROTECT, related_name='budgets',
    )
    status = models.CharField(max_length=10, choices=BUDGET_STATUS_CHOICES, default='draft')
    currency = models.CharField(max_length=3, default='USD')
    total_allocated = _money(help_text='Denormalised sum of the allocation lines.')

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='budgets_owned', help_text='Budget holder alerted on over-budget activity.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='budgets_created',
    )

    activated_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Idempotency stamp for the cron over-budget sweep (scan_budget_alerts).
    over_budget_alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'budget_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'period']),
        ]

    def __str__(self):
        return f'{self.budget_number} — {self.name}'

    @property
    def is_editable(self):
        return self.status in BUDGET_EDITABLE_STATUSES

    @property
    def is_active(self):
        return self.status in BUDGET_ACTIVE_STATUSES


class BudgetAllocation(TenantAwareModel, TimeStampedModel):
    """One envelope: ``allocated_amount`` mapped to a cost-centre / GL code (and optionally a
    vendor category) inside a budget. Consumption is computed against this line on read."""

    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name='allocations',
    )
    line_no = models.PositiveIntegerField(default=1)
    account_code = models.ForeignKey(
        'requisitions.AccountCode', on_delete=models.PROTECT, related_name='budget_allocations',
        help_text='Cost centre / GL account this budget envelope governs.',
    )
    vendor_category = models.ForeignKey(
        'vendors.VendorCategory', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='budget_allocations',
        help_text='Optional: narrow the envelope to one commodity category.',
    )
    allocated_amount = _money(validators=[MinValueValidator(Decimal('0'))])
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['line_no', 'id']
        unique_together = [('budget', 'account_code', 'vendor_category')]

    def __str__(self):
        return f'{self.account_code} — {self.allocated_amount}'


# ---------------------------------------------------------------------------
# 2. Tracking — append-only timelines
# ---------------------------------------------------------------------------
class BudgetStatusEvent(TenantAwareModel, TimeStampedModel):
    """An immutable entry in a budget's lifecycle timeline."""

    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name='status_events',
    )
    from_status = models.CharField(max_length=10, blank=True)
    to_status = models.CharField(max_length=10)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='budget_status_events',
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.budget_id}: {self.from_status or "—"} → {self.to_status}'


class BudgetCheck(TenantAwareModel, TimeStampedModel):
    """Append-only evidence of one budget-availability check fired against a requisition line group.

    Written by ``services.check_requisition_budget`` at requisition submit. ``result`` records
    whether the requested amount was within the available balance (``pass``) or exceeded it — and
    if so whether the configured enforcement merely warned or blocked the submission.
    """

    RESULT_CHOICES = CHECK_RESULT_CHOICES

    requisition = models.ForeignKey(
        'requisitions.Requisition', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='budget_checks',
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.SET_NULL, null=True, blank=True, related_name='checks',
    )
    allocation = models.ForeignKey(
        BudgetAllocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='checks',
    )
    account_code = models.ForeignKey(
        'requisitions.AccountCode', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='budget_checks',
    )
    requested_amount = _money()
    available_amount = _money(help_text='Available balance at check time (0 when unbudgeted).')
    result = models.CharField(max_length=6, choices=CHECK_RESULT_CHOICES, default='pass')
    enforcement_mode = models.CharField(max_length=6, blank=True)
    message = models.CharField(max_length=255, blank=True)
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='budget_checks',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'result']),
            models.Index(fields=['tenant', 'requisition']),
        ]

    def __str__(self):
        return f'check {self.account_code_id} {self.result} ({self.requested_amount})'
