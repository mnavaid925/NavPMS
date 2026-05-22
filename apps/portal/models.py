"""Module 2: User Dashboard & Portal.

Covers the five PMS sub-modules:
  1. Personalized Overview   -> DashboardWidget (per-user, customizable)
  2. Task & Alert Center     -> Notification
  3. Quick Requisition Entry -> QuickRequisition + QuickRequisitionItem
  4. Recent Activity Feed    -> reuses tenants.AuditLog (no model here)
  5. Self-Service Reporting  -> SavedReport
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------- 1. Personalized Overview ----------

class DashboardWidget(TenantAwareModel, TimeStampedModel):
    """A single, user-positioned widget on the personalized portal dashboard."""

    WIDGET_TYPES = [
        ('pending_tasks', 'Pending Tasks'),
        ('pending_approvals', 'Pending Approvals'),
        ('spend_summary', 'Spend Summary'),
        ('recent_activity', 'Recent Activity'),
        ('notifications', 'Notifications'),
        ('quick_requisition', 'Quick Requisition'),
        ('my_reports', 'My Reports'),
        ('quick_links', 'Quick Links'),
    ]
    SIZE_CHOICES = [
        ('small', 'Small (1/3 width)'),
        ('medium', 'Medium (1/2 width)'),
        ('large', 'Large (full width)'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='dashboard_widgets',
    )
    widget_type = models.CharField(max_length=30, choices=WIDGET_TYPES)
    title = models.CharField(max_length=120)
    position = models.PositiveIntegerField(default=0, help_text='Lower shows first')
    size = models.CharField(max_length=10, choices=SIZE_CHOICES, default='small')
    is_visible = models.BooleanField(default=True)

    class Meta:
        ordering = ['position', 'id']
        indexes = [models.Index(fields=['tenant', 'user', 'position'])]

    def __str__(self):
        return f'{self.title} ({self.get_widget_type_display()})'

    @property
    def col_class(self):
        """Bootstrap column class for this widget's size."""
        return {
            'small': 'col-lg-4',
            'medium': 'col-lg-6',
            'large': 'col-12',
        }.get(self.size, 'col-lg-4')


# ---------- 2. Task & Alert Center ----------

class Notification(TenantAwareModel, TimeStampedModel):
    """A centralized alert delivered to one user (deadline, approval, delivery...)."""

    CATEGORY_CHOICES = [
        ('deadline', 'Approaching Deadline'),
        ('approval', 'Approval Required'),
        ('delivery', 'Delivery Update'),
        ('system', 'System'),
        ('info', 'Information'),
    ]
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='notifications',
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='info')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True)
    link_url = models.CharField(
        max_length=300, blank=True, help_text='Optional URL the alert points to',
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'user', 'is_read']),
            models.Index(fields=['tenant', 'user', 'created_at']),
        ]

    def __str__(self):
        return f'{self.title} ({self.get_category_display()})'

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at', 'updated_at'])


# ---------- 3. Quick Requisition Entry ----------

class QuickRequisition(TenantAwareModel, TimeStampedModel):
    """A fast-track requisition for frequent, low-value or catalog purchases."""

    CATEGORY_CHOICES = [
        ('office_supplies', 'Office Supplies'),
        ('it_equipment', 'IT Equipment'),
        ('services', 'Services'),
        ('travel', 'Travel'),
        ('maintenance', 'Maintenance'),
        ('other', 'Other'),
    ]
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='quick_requisitions',
    )
    number = models.CharField(max_length=40)
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    description = models.TextField(blank=True)
    vendor_name = models.CharField(max_length=160, blank=True)
    needed_by = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='draft')
    justification = models.TextField(blank=True)
    estimated_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
    )
    currency = models.CharField(max_length=3, default='USD')
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='decided_requisitions',
    )
    decision_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        # number is unique per tenant (not globally) — see SQA defect D-08.
        unique_together = [('tenant', 'number')]
        indexes = [
            models.Index(fields=['tenant', 'user', 'status']),
        ]

    def __str__(self):
        return f'{self.number} - {self.title}'

    @property
    def is_editable(self):
        """Only drafts can be modified or deleted by the requester."""
        return self.status == 'draft'

    def recalc_total(self):
        total = sum(
            (item.line_total for item in self.items.all()), Decimal('0.00'),
        )
        self.estimated_total = total
        self.save(update_fields=['estimated_total', 'updated_at'])
        return total


class QuickRequisitionItem(TenantAwareModel, TimeStampedModel):
    """A single line on a quick requisition."""

    requisition = models.ForeignKey(
        QuickRequisition, on_delete=models.CASCADE, related_name='items',
    )
    name = models.CharField(max_length=200)
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('1.00'),
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    unit = models.CharField(max_length=30, default='unit')
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    line_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
    )

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.name} x{self.quantity}'

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))
        super().save(*args, **kwargs)


# ---------- 5. Self-Service Reporting ----------

class SavedReport(TenantAwareModel, TimeStampedModel):
    """A reusable personal report definition (spend / usage / activity)."""

    REPORT_TYPES = [
        ('spend_by_category', 'Spend by Category'),
        ('spend_by_month', 'Spend by Month'),
        ('requisition_status', 'Requisitions by Status'),
        ('my_activity', 'My Activity Summary'),
        ('notification_summary', 'Notifications Summary'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='saved_reports',
    )
    name = models.CharField(max_length=160)
    report_type = models.CharField(max_length=30, choices=REPORT_TYPES)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.get_report_type_display()})'
