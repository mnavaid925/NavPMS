"""Module 6: Sourcing & Tendering.

Covers the five PMS sub-modules:
  1. Event Creation & Scheduling -> SourcingEvent + SourcingEventItem
  2. Bid Submission Portal       -> SourcingEventInvitee + Bid + BidLine + BidDocument
  3. Bid Evaluation Matrix       -> SourcingCriterion + BidEvaluation
  4. Award Recommendation        -> SourcingAward (append-only)
  5. Sourcing Analytics          -> derived (per-event + tenant-wide)
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


EVENT_TYPE_CHOICES = [
    ('rfq', 'Request for Quotation (RFQ)'),
    ('rfp', 'Request for Proposal (RFP)'),
    ('rft', 'Request for Tender (RFT)'),
    ('tender', 'Open Tender'),
]

EVENT_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('scheduled', 'Scheduled'),
    ('open', 'Open for bids'),
    ('closed', 'Closed (bidding ended)'),
    ('under_evaluation', 'Under evaluation'),
    ('awarded', 'Awarded'),
    ('cancelled', 'Cancelled'),
]
EVENT_EDITABLE_STATUSES = ('draft',)
EVENT_OPEN_STATUSES = ('draft', 'scheduled', 'open', 'closed', 'under_evaluation')
EVENT_POST_CLOSE_STATUSES = ('closed', 'under_evaluation', 'awarded', 'cancelled')

INVITEE_STATUS_CHOICES = [
    ('invited', 'Invited'),
    ('viewed', 'Viewed'),
    ('submitted', 'Submitted bid'),
    ('declined', 'Declined'),
    ('withdrawn', 'Withdrawn'),
]

CRITERION_TYPE_CHOICES = [
    ('price', 'Price'),
    ('quality', 'Quality'),
    ('delivery', 'Delivery'),
    ('compliance', 'Compliance'),
    ('experience', 'Experience'),
    ('other', 'Other'),
]

BID_STATUS_CHOICES = [
    ('draft', 'Draft (vendor working)'),
    ('submitted', 'Submitted'),
    ('under_review', 'Under review'),
    ('shortlisted', 'Shortlisted'),
    ('rejected', 'Rejected'),
    ('awarded', 'Awarded'),
    ('withdrawn', 'Withdrawn'),
]
BID_OPEN_STATUSES = ('draft', 'submitted', 'under_review', 'shortlisted')

AWARD_STATUS_CHOICES = [
    ('recommended', 'Recommended'),
    ('approved', 'Approved'),
    ('contracted', 'Contracted'),
    ('cancelled', 'Cancelled'),
]


# ---------- 1. Event Creation & Scheduling ----------

class SourcingEvent(TenantAwareModel, TimeStampedModel):
    """A sourcing event (RFQ / RFP / RFT / Tender) issued by a buyer."""

    STATUS_CHOICES = EVENT_STATUS_CHOICES
    TYPE_CHOICES = EVENT_TYPE_CHOICES

    event_number = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    event_type = models.CharField(
        max_length=10, choices=EVENT_TYPE_CHOICES, default='rfq',
    )
    category = models.ForeignKey(
        'vendors.VendorCategory', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sourcing_events',
    )
    currency = models.CharField(max_length=3, default='USD')
    estimated_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )

    status = models.CharField(
        max_length=20, choices=EVENT_STATUS_CHOICES, default='draft',
    )
    publish_at = models.DateTimeField(null=True, blank=True)
    close_at = models.DateTimeField(null=True, blank=True)
    award_target_at = models.DateTimeField(null=True, blank=True)

    terms_and_conditions = models.TextField(blank=True)
    allow_partial_award = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sourcing_events_created',
    )
    requisition = models.ForeignKey(
        'requisitions.Requisition', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sourcing_events',
        help_text='Source requisition this event was spawned from (if any).',
    )

    awarded_vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='awarded_events',
    )
    awarded_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
    )
    awarded_at = models.DateTimeField(null=True, blank=True)
    award_notes = models.TextField(blank=True)

    cancelled_reason = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sourcing_events_cancelled',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'event_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'event_type']),
        ]

    def __str__(self):
        return f'{self.event_number} — {self.title}'

    @property
    def is_editable(self):
        return self.status in EVENT_EDITABLE_STATUSES

    @property
    def is_open_for_bids(self):
        return self.status == 'open'

    @property
    def bids_are_visible(self):
        """Sealed-bid: bid content visible only after the event closes."""
        return self.status in EVENT_POST_CLOSE_STATUSES

    @property
    def can_cancel(self):
        return self.status in EVENT_OPEN_STATUSES

    @property
    def total_estimated(self):
        total = sum(
            ((line.quantity or Decimal('0')) * (line.est_unit_price or Decimal('0'))
             for line in self.items.all()),
            Decimal('0.00'),
        )
        return total if total else self.estimated_value


class SourcingEventItem(TenantAwareModel, TimeStampedModel):
    """A single line item in a sourcing event."""

    event = models.ForeignKey(
        SourcingEvent, on_delete=models.CASCADE, related_name='items',
    )
    line_no = models.PositiveIntegerField(default=1)
    item_description = models.CharField(max_length=255)
    uom = models.CharField(max_length=20, default='EA', help_text='Unit of measure')
    quantity = models.DecimalField(
        max_digits=14, decimal_places=3, default=Decimal('1.000'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    est_unit_price = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    account_code = models.ForeignKey(
        'requisitions.AccountCode', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sourcing_items',
    )
    required_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['line_no', 'id']
        unique_together = [('event', 'line_no')]

    def __str__(self):
        return f'#{self.line_no} {self.item_description} x{self.quantity}'

    @property
    def estimated_line_total(self):
        return (self.quantity or Decimal('0')) * (self.est_unit_price or Decimal('0'))


# ---------- 2. Bid Submission Portal — invitations ----------

class SourcingEventInvitee(TenantAwareModel, TimeStampedModel):
    """A vendor invited to submit a bid for an event."""

    STATUS_CHOICES = INVITEE_STATUS_CHOICES

    event = models.ForeignKey(
        SourcingEvent, on_delete=models.CASCADE, related_name='invitees',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE,
        related_name='sourcing_invitations',
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sourcing_invitations_sent',
    )
    status = models.CharField(
        max_length=12, choices=INVITEE_STATUS_CHOICES, default='invited',
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-invited_at']
        unique_together = [('event', 'vendor')]
        indexes = [
            models.Index(fields=['tenant', 'vendor', 'status']),
        ]

    def __str__(self):
        return f'{self.vendor.legal_name} -> {self.event.event_number}'


# ---------- 3. Bid Evaluation Matrix — criteria ----------

class SourcingCriterion(TenantAwareModel, TimeStampedModel):
    """A weighted criterion used to score bids on an event."""

    TYPE_CHOICES = CRITERION_TYPE_CHOICES

    event = models.ForeignKey(
        SourcingEvent, on_delete=models.CASCADE, related_name='criteria',
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    criterion_type = models.CharField(
        max_length=15, choices=CRITERION_TYPE_CHOICES, default='other',
    )
    weight = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
        help_text='Weight in percent (0–100). All weights on an event should sum to 100.',
    )
    max_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('100.00'),
        validators=[MinValueValidator(Decimal('1'))],
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.name} ({self.weight}%)'


# ---------- 2. Bid Submission Portal — Bid + lines + docs ----------

class Bid(TenantAwareModel, TimeStampedModel):
    """A vendor's submitted bid for an event."""

    STATUS_CHOICES = BID_STATUS_CHOICES

    bid_number = models.CharField(max_length=40)
    event = models.ForeignKey(
        SourcingEvent, on_delete=models.CASCADE, related_name='bids',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='bids',
    )
    status = models.CharField(
        max_length=12, choices=BID_STATUS_CHOICES, default='draft',
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bids_submitted',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    total_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
    )
    currency = models.CharField(max_length=3, default='USD')

    delivery_lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    validity_days = models.PositiveIntegerField(null=True, blank=True)
    payment_terms = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    is_compliant = models.BooleanField(default=True)
    overall_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
    )
    rank = models.PositiveIntegerField(null=True, blank=True)

    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['rank', '-submitted_at', '-created_at']
        unique_together = [('event', 'vendor')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['event', 'rank']),
        ]

    def __str__(self):
        return f'{self.bid_number} ({self.vendor.legal_name})'

    @property
    def is_locked(self):
        """Once submitted, the vendor can no longer edit the bid."""
        return self.status not in ('draft',)

    @property
    def is_visible_to_buyer(self):
        return self.event.bids_are_visible

    def recompute_total(self):
        total = sum(
            (line.line_total for line in self.lines.all()),
            Decimal('0.00'),
        )
        self.total_amount = total.quantize(Decimal('0.01'))
        return self.total_amount


class BidLine(TenantAwareModel, TimeStampedModel):
    """A per-event-item priced line on a bid."""

    bid = models.ForeignKey(Bid, on_delete=models.CASCADE, related_name='lines')
    event_item = models.ForeignKey(
        SourcingEventItem, on_delete=models.CASCADE, related_name='bid_lines',
    )
    unit_price = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    quantity_offered = models.DecimalField(
        max_digits=14, decimal_places=3, default=Decimal('0.000'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['event_item__line_no', 'id']
        unique_together = [('bid', 'event_item')]

    def __str__(self):
        return f'{self.bid.bid_number} L{self.event_item.line_no}'

    @property
    def line_total(self):
        return (self.unit_price or Decimal('0')) * (self.quantity_offered or Decimal('0'))


class BidDocument(TenantAwareModel, TimeStampedModel):
    """An attachment uploaded by a vendor with their bid."""

    bid = models.ForeignKey(Bid, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='bid_docs/', blank=True, null=True)
    notes = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.title} ({self.bid.bid_number})'


# ---------- 3. Bid Evaluation Matrix — scores ----------

class BidEvaluation(TenantAwareModel, TimeStampedModel):
    """One evaluator's score for a (bid, criterion) cell. Supports panel scoring."""

    bid = models.ForeignKey(
        Bid, on_delete=models.CASCADE, related_name='evaluations',
    )
    criterion = models.ForeignKey(
        SourcingCriterion, on_delete=models.CASCADE, related_name='evaluations',
    )
    evaluator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='bid_evaluations',
    )
    score = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    comment = models.TextField(blank=True)
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-evaluated_at']
        unique_together = [('bid', 'criterion', 'evaluator')]
        indexes = [
            models.Index(fields=['tenant', 'bid']),
        ]

    def __str__(self):
        return f'{self.evaluator}: {self.criterion.name} = {self.score}'


# ---------- 4. Award Recommendation (append-only) ----------

class SourcingAward(TenantAwareModel, TimeStampedModel):
    """An award record for an event. Append-only audit trail."""

    STATUS_CHOICES = AWARD_STATUS_CHOICES

    event = models.ForeignKey(
        SourcingEvent, on_delete=models.CASCADE, related_name='awards',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='sourcing_awards',
    )
    bid = models.ForeignKey(
        Bid, on_delete=models.CASCADE, related_name='awards',
    )
    award_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
    )
    currency = models.CharField(max_length=3, default='USD')
    status = models.CharField(
        max_length=12, choices=AWARD_STATUS_CHOICES, default='recommended',
    )
    justification = models.TextField(blank=True)
    awarded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sourcing_awards_made',
    )
    awarded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-awarded_at']
        indexes = [
            models.Index(fields=['tenant', 'event', 'status']),
        ]

    def __str__(self):
        return f'{self.event.event_number} -> {self.vendor.legal_name} ({self.status})'
