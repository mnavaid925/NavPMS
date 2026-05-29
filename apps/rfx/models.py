"""Module 7: RFx Management (RFI / RFP / RFQ).

Covers the five PMS sub-modules:
  1. Questionnaire Builder      -> RfxEvent + RfxSection + RfxQuestion
  2. Response Collection        -> RfxInvitee + RfxResponse + RfxAnswer (+ RfxDocument)
  3. Side-by-Side Comparison    -> derived (compare view over RfxResponse / RfxAnswer)
  4. Scoring & Weighting        -> RfxEvaluation
  5. RFx Template Library       -> RfxTemplate + RfxTemplateSection + RfxTemplateQuestion
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------- Choice constants ----------

RFX_TYPE_CHOICES = [
    ('rfi', 'Request for Information (RFI)'),
    ('rfp', 'Request for Proposal (RFP)'),
    ('rfq', 'Request for Quotation (RFQ)'),
]

EVENT_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('published', 'Published (awaiting open date)'),
    ('open', 'Open for responses'),
    ('closed', 'Closed (responses ended)'),
    ('under_evaluation', 'Under evaluation'),
    ('completed', 'Completed (shortlisted)'),
    ('cancelled', 'Cancelled'),
]
EVENT_EDITABLE_STATUSES = ('draft',)
EVENT_OPEN_STATUSES = (
    'draft', 'published', 'open', 'closed', 'under_evaluation',
)
EVENT_POST_CLOSE_STATUSES = (
    'closed', 'under_evaluation', 'completed', 'cancelled',
)
# Statuses during which evaluators may score responses. Deliberately excludes
# `completed` and `cancelled`: once an event is finalised its ranks are frozen,
# so a late evaluation must not silently mutate overall_score (SQA defect D-03).
EVENT_EVALUABLE_STATUSES = ('closed', 'under_evaluation')

INVITEE_STATUS_CHOICES = [
    ('invited', 'Invited'),
    ('viewed', 'Viewed'),
    ('responded', 'Responded'),
    ('declined', 'Declined'),
    ('withdrawn', 'Withdrawn'),
]

RESPONSE_STATUS_CHOICES = [
    ('draft', 'Draft (vendor working)'),
    ('submitted', 'Submitted'),
    ('under_review', 'Under review'),
    ('shortlisted', 'Shortlisted'),
    ('rejected', 'Rejected'),
    ('withdrawn', 'Withdrawn'),
]
RESPONSE_OPEN_STATUSES = (
    'draft', 'submitted', 'under_review', 'shortlisted',
)

QUESTION_TYPE_CHOICES = [
    ('text', 'Short text'),
    ('longtext', 'Long text / paragraph'),
    ('number', 'Number'),
    ('single_choice', 'Single choice (radio)'),
    ('multi_choice', 'Multiple choice (checkboxes)'),
    ('yes_no', 'Yes / No'),
    ('scale', 'Rating scale (0–max)'),
    ('date', 'Date'),
    ('file', 'File upload'),
]
CHOICE_QUESTION_TYPES = ('single_choice', 'multi_choice')
DEFAULT_SCORED_TYPES = (
    'number', 'single_choice', 'multi_choice', 'yes_no', 'scale',
)


# ---------- 1. Questionnaire Builder ----------

class RfxEvent(TenantAwareModel, TimeStampedModel):
    """An RFx event (RFI / RFP / RFQ) issued by a buyer."""

    STATUS_CHOICES = EVENT_STATUS_CHOICES
    TYPE_CHOICES = RFX_TYPE_CHOICES

    event_number = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    rfx_type = models.CharField(
        max_length=10, choices=RFX_TYPE_CHOICES, default='rfi',
    )
    category = models.ForeignKey(
        'vendors.VendorCategory', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='rfx_events',
    )
    currency = models.CharField(max_length=3, default='USD')

    status = models.CharField(
        max_length=20, choices=EVENT_STATUS_CHOICES, default='draft',
    )
    publish_at = models.DateTimeField(null=True, blank=True)
    close_at = models.DateTimeField(null=True, blank=True)

    terms_and_conditions = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='rfx_events_created',
    )
    source_requisition = models.ForeignKey(
        'requisitions.Requisition', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='rfx_events',
        help_text='Source requisition this RFx was spawned from (if any).',
    )

    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='rfx_events_cancelled',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'event_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'rfx_type']),
        ]

    def __str__(self):
        return f'{self.event_number} — {self.title}'

    @property
    def is_editable(self):
        return self.status in EVENT_EDITABLE_STATUSES

    @property
    def is_open_for_responses(self):
        return self.status == 'open'

    @property
    def responses_are_visible(self):
        """Sealed-response: content visible only after the event closes."""
        return self.status in EVENT_POST_CLOSE_STATUSES

    @property
    def can_cancel(self):
        return self.status in EVENT_OPEN_STATUSES


class RfxSection(TenantAwareModel, TimeStampedModel):
    """A named section grouping questions inside an event."""

    event = models.ForeignKey(
        RfxEvent, on_delete=models.CASCADE, related_name='sections',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'{self.event.event_number} / {self.position}. {self.title}'


class RfxQuestion(TenantAwareModel, TimeStampedModel):
    """A single question inside a section."""

    TYPE_CHOICES = QUESTION_TYPE_CHOICES

    section = models.ForeignKey(
        RfxSection, on_delete=models.CASCADE, related_name='questions',
    )
    prompt = models.CharField(max_length=500)
    help_text = models.TextField(blank=True)
    question_type = models.CharField(
        max_length=20, choices=QUESTION_TYPE_CHOICES, default='text',
    )
    is_required = models.BooleanField(default=False)
    is_scored = models.BooleanField(
        default=False,
        help_text='If true, evaluators score this answer and the weight contributes to the response score.',
    )
    weight = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[
            MinValueValidator(Decimal('0')),
            MaxValueValidator(Decimal('100')),
        ],
        help_text='Weight in percent (0–100). All scored question weights on an event must sum to 100.',
    )
    max_score = models.PositiveIntegerField(
        default=5,
        help_text='Maximum evaluator score (default 5 for a 1–5 scale).',
    )
    choices = models.JSONField(
        default=list, blank=True,
        help_text='List of choice strings — required for single_choice / multi_choice; ignored otherwise.',
    )
    position = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'Q{self.position}. {self.prompt[:60]}'

    @property
    def is_choice_type(self):
        return self.question_type in CHOICE_QUESTION_TYPES


# ---------- 2. Response Collection ----------

class RfxInvitee(TenantAwareModel, TimeStampedModel):
    """A vendor invited to respond to an event."""

    STATUS_CHOICES = INVITEE_STATUS_CHOICES

    event = models.ForeignKey(
        RfxEvent, on_delete=models.CASCADE, related_name='invitees',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE,
        related_name='rfx_invitations',
    )
    status = models.CharField(
        max_length=12, choices=INVITEE_STATUS_CHOICES, default='invited',
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='rfx_invitations_sent',
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


class RfxResponse(TenantAwareModel, TimeStampedModel):
    """A vendor's response to an RFx event."""

    STATUS_CHOICES = RESPONSE_STATUS_CHOICES

    event = models.ForeignKey(
        RfxEvent, on_delete=models.CASCADE, related_name='responses',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='rfx_responses',
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='rfx_responses_submitted',
    )
    status = models.CharField(
        max_length=15, choices=RESPONSE_STATUS_CHOICES, default='draft',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    overall_score = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal('0.0000'),
    )
    rank = models.PositiveIntegerField(default=0, help_text='1 = highest; 0 = unranked')
    notes = models.TextField(blank=True)
    decision_reason = models.CharField(
        max_length=255, blank=True,
        help_text='Reason recorded when the response was shortlisted or rejected.',
    )

    class Meta:
        ordering = ['rank', '-submitted_at', '-created_at']
        unique_together = [('event', 'vendor')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['event', 'rank']),
        ]

    def __str__(self):
        return f'{self.event.event_number}: {self.vendor.legal_name} ({self.status})'

    @property
    def is_editable(self):
        return self.status == 'draft'


class RfxAnswer(TenantAwareModel, TimeStampedModel):
    """A vendor's answer to a single question on a response.

    Each question type lands in a different value field — `value()` returns the
    relevant one. Empty values across all fields means "unanswered".
    """

    response = models.ForeignKey(
        RfxResponse, on_delete=models.CASCADE, related_name='answers',
    )
    question = models.ForeignKey(
        RfxQuestion, on_delete=models.CASCADE, related_name='answers',
    )
    value_text = models.TextField(blank=True)
    value_number = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
    )
    value_choices = models.JSONField(
        default=list, blank=True,
        help_text='List of selected choice strings (one entry for single_choice).',
    )
    value_date = models.DateField(null=True, blank=True)
    value_file = models.FileField(
        upload_to='rfx_answers/', blank=True, null=True,
    )

    class Meta:
        ordering = ['question__section__position', 'question__position', 'id']
        unique_together = [('response', 'question')]

    def __str__(self):
        return f'{self.response} / Q{self.question.position}'

    @property
    def value(self):
        """Return the typed value for this answer (or None if unanswered)."""
        qtype = self.question.question_type
        if qtype in ('text', 'longtext'):
            return self.value_text or None
        if qtype == 'number':
            return self.value_number
        if qtype in CHOICE_QUESTION_TYPES:
            return self.value_choices or None
        if qtype == 'yes_no':
            # Stored in value_text as 'yes' / 'no' for simplicity
            return self.value_text or None
        if qtype == 'scale':
            return self.value_number
        if qtype == 'date':
            return self.value_date
        if qtype == 'file':
            return self.value_file or None
        return None

    @property
    def is_answered(self):
        v = self.value
        if isinstance(v, list):
            return bool(v)
        return v not in (None, '', [])


# ---------- 3. Scoring & Weighting ----------

class RfxEvaluation(TenantAwareModel, TimeStampedModel):
    """One evaluator's score for a (response, question) cell. Panel scoring."""

    response = models.ForeignKey(
        RfxResponse, on_delete=models.CASCADE, related_name='evaluations',
    )
    question = models.ForeignKey(
        RfxQuestion, on_delete=models.CASCADE, related_name='evaluations',
    )
    evaluator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='rfx_evaluations',
    )
    score = models.DecimalField(
        max_digits=7, decimal_places=4, default=Decimal('0.0000'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    comment = models.TextField(blank=True)
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-evaluated_at']
        unique_together = [('response', 'question', 'evaluator')]
        indexes = [
            models.Index(fields=['tenant', 'response']),
        ]

    def __str__(self):
        return f'{self.evaluator}: Q{self.question.position} = {self.score}'


# ---------- 4. Documents (buyer-side attachments) ----------

class RfxDocument(TenantAwareModel, TimeStampedModel):
    """A buyer-side attachment on an event (RFP brief, spec sheet, addendum)."""

    event = models.ForeignKey(
        RfxEvent, on_delete=models.CASCADE, related_name='documents',
    )
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='rfx_docs/', blank=True, null=True)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='rfx_documents_uploaded',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.title} ({self.event.event_number})'


# ---------- 5. RFx Template Library ----------

class RfxTemplate(TenantAwareModel, TimeStampedModel):
    """A reusable RFx questionnaire template."""

    TYPE_CHOICES = RFX_TYPE_CHOICES

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    rfx_type = models.CharField(
        max_length=10, choices=RFX_TYPE_CHOICES, default='rfi',
    )
    is_shared = models.BooleanField(
        default=True,
        help_text='Shared templates are visible to every user in the tenant.',
    )
    archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='rfx_templates_created',
    )

    class Meta:
        ordering = ['title']
        unique_together = [('tenant', 'title')]

    def __str__(self):
        return f'{self.title} ({self.get_rfx_type_display()})'


class RfxTemplateSection(TenantAwareModel, TimeStampedModel):
    """A section inside a template."""

    template = models.ForeignKey(
        RfxTemplate, on_delete=models.CASCADE, related_name='sections',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'{self.template.title} / {self.position}. {self.title}'


class RfxTemplateQuestion(TenantAwareModel, TimeStampedModel):
    """A question inside a template section."""

    TYPE_CHOICES = QUESTION_TYPE_CHOICES

    section = models.ForeignKey(
        RfxTemplateSection, on_delete=models.CASCADE, related_name='questions',
    )
    prompt = models.CharField(max_length=500)
    help_text = models.TextField(blank=True)
    question_type = models.CharField(
        max_length=20, choices=QUESTION_TYPE_CHOICES, default='text',
    )
    is_required = models.BooleanField(default=False)
    is_scored = models.BooleanField(default=False)
    weight = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[
            MinValueValidator(Decimal('0')),
            MaxValueValidator(Decimal('100')),
        ],
    )
    max_score = models.PositiveIntegerField(default=5)
    choices = models.JSONField(default=list, blank=True)
    position = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'Q{self.position}. {self.prompt[:60]}'
