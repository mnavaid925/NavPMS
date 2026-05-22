"""Module 4: Approval Workflow Engine.

Covers the five PMS sub-modules:
  1. Dynamic Routing Rules        -> ApprovalRule + ApprovalStep
  2. Delegation of Authority      -> ApprovalDelegation
  3. Approval History/Audit Trail -> ApprovalAction (append-only)
  4. Escalation Management        -> ApprovalStep.sla_hours / escalate_to + ApprovalTask.due_at
  5. Mobile Approval Interface    -> responsive inbox / task views (templates)
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------- 1. Dynamic Routing Rules ----------

class ApprovalRule(TenantAwareModel, TimeStampedModel):
    """A condition set that routes a document through an ordered approval chain."""

    DOCUMENT_TYPES = [('requisition', 'Requisition')]

    name = models.CharField(max_length=160)
    document_type = models.CharField(
        max_length=20, choices=DOCUMENT_TYPES, default='requisition',
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(
        default=100, help_text='Lower numbers are evaluated first',
    )
    # Conditions — blank/null means "any"
    min_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text='Match documents whose total is at least this amount',
    )
    max_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text='Match documents whose total is at most this amount',
    )
    department = models.CharField(
        max_length=120, blank=True, help_text='Blank = any department',
    )
    category = models.CharField(
        max_length=20, blank=True, help_text='Blank = any category',
    )

    class Meta:
        ordering = ['priority', 'name']

    def __str__(self):
        return self.name

    def matches(self, requisition):
        """Return True if this active rule applies to the given requisition."""
        if not self.is_active:
            return False
        total = requisition.estimated_total or Decimal('0.00')
        if self.min_amount is not None and total < self.min_amount:
            return False
        if self.max_amount is not None and total > self.max_amount:
            return False
        if self.department and self.department.strip().lower() != \
                (requisition.department or '').strip().lower():
            return False
        if self.category and self.category != requisition.category:
            return False
        return True


class ApprovalStep(TenantAwareModel, TimeStampedModel):
    """One ordered stage of a rule's approval chain, assigned to a named approver."""

    rule = models.ForeignKey(
        ApprovalRule, on_delete=models.CASCADE, related_name='steps',
    )
    order = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=120)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='approval_steps',
    )
    sla_hours = models.PositiveIntegerField(
        default=48, help_text='Hours before the task escalates (0 = never)',
    )
    escalate_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='escalation_steps',
        help_text='User the task escalates to when overdue',
    )

    class Meta:
        ordering = ['rule', 'order']

    def __str__(self):
        return f'{self.rule.name} · step {self.order}: {self.name}'


# ---------- 2. Delegation of Authority ----------

class ApprovalDelegation(TenantAwareModel, TimeStampedModel):
    """A temporary reassignment of one user's approval authority to another."""

    delegator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='delegations_given',
    )
    delegate = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='delegations_received',
    )
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f'{self.delegator} → {self.delegate} ({self.start_date}–{self.end_date})'

    @property
    def is_current(self):
        today = timezone.now().date()
        return self.is_active and self.start_date <= today <= self.end_date


# ---------- Approval instances ----------

class ApprovalRequest(TenantAwareModel, TimeStampedModel):
    """A live approval process for one requisition, spawned on submission."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    requisition = models.ForeignKey(
        'requisitions.Requisition', on_delete=models.CASCADE,
        related_name='approval_requests',
    )
    rule = models.ForeignKey(
        ApprovalRule, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='requests',
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')
    current_step = models.PositiveIntegerField(default=1)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approval_requests_submitted',
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['tenant', 'status'])]

    def __str__(self):
        return f'Approval for {self.requisition.number} ({self.status})'

    @property
    def active_task(self):
        return self.tasks.filter(status__in=['pending', 'escalated']).order_by('order').first()

    @property
    def progress(self):
        total = self.tasks.count()
        done = self.tasks.filter(status='approved').count()
        return {'done': done, 'total': total,
                'percent': int(done / total * 100) if total else 0}


class ApprovalTask(TenantAwareModel, TimeStampedModel):
    """A single approver's pending decision within an ApprovalRequest."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('escalated', 'Escalated'),
        ('skipped', 'Skipped'),
    ]

    request = models.ForeignKey(
        ApprovalRequest, on_delete=models.CASCADE, related_name='tasks',
    )
    step = models.ForeignKey(
        ApprovalStep, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tasks',
    )
    order = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=120)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='approval_tasks',
    )
    original_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approval_tasks_original',
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='pending')
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approval_tasks_acted',
    )
    acted_at = models.DateTimeField(null=True, blank=True)
    comment = models.CharField(max_length=255, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['request', 'order']
        indexes = [models.Index(fields=['tenant', 'assigned_to', 'status'])]

    def __str__(self):
        return f'{self.name} → {self.assigned_to} ({self.status})'

    @property
    def is_open(self):
        return self.status in ('pending', 'escalated')

    @property
    def is_overdue(self):
        return (
            self.status == 'pending'
            and self.due_at is not None
            and self.due_at < timezone.now()
        )


# ---------- 3. Approval History & Audit Trail ----------

class ApprovalAction(TenantAwareModel, TimeStampedModel):
    """An append-only entry in an approval request's history."""

    ACTION_CHOICES = [
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('delegated', 'Delegated'),
        ('escalated', 'Escalated'),
        ('commented', 'Commented'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    ]

    request = models.ForeignKey(
        ApprovalRequest, on_delete=models.CASCADE, related_name='actions',
    )
    task = models.ForeignKey(
        ApprovalTask, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='actions',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approval_actions',
    )
    action = models.CharField(max_length=12, choices=ACTION_CHOICES)
    comment = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['tenant', 'request', 'created_at'])]

    def __str__(self):
        return f'{self.get_action_display()} by {self.actor_id or "system"}'
