"""Module 3: Requisition Management.

Covers the five PMS sub-modules:
  1. Requisition Creation      -> Requisition + RequisitionLine
  2. Requisition Tracking      -> status + RequisitionStatusEvent timeline
  3. Duplicate Requisition Chk -> possible_duplicate / duplicate_of (services.py logic)
  4. Requisition Templates     -> RequisitionTemplate + RequisitionTemplateLine
  5. Cancellation/Amendment    -> status workflow + revision counter
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


PRIORITY_CHOICES = [
    ('low', 'Low'),
    ('normal', 'Normal'),
    ('high', 'High'),
    ('urgent', 'Urgent'),
]

CATEGORY_CHOICES = [
    ('office_supplies', 'Office Supplies'),
    ('it_equipment', 'IT Equipment'),
    ('services', 'Services'),
    ('travel', 'Travel'),
    ('maintenance', 'Maintenance'),
    ('raw_materials', 'Raw Materials'),
    ('other', 'Other'),
]


# ---------- Account codes (shared master data) ----------

class AccountCode(TenantAwareModel, TimeStampedModel):
    """A tenant chart-of-accounts code charged against requisition lines."""

    code = models.CharField(max_length=40)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']
        unique_together = [('tenant', 'code')]

    def __str__(self):
        return f'{self.code} — {self.name}'


# ---------- 4. Requisition Templates ----------

class RequisitionTemplate(TenantAwareModel, TimeStampedModel):
    """A reusable, pre-defined requisition form for recurring orders."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='requisition_templates',
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    default_account_code = models.ForeignKey(
        AccountCode, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='templates',
    )
    is_shared = models.BooleanField(
        default=False, help_text='Visible to the whole tenant, not just the owner',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def estimated_total(self):
        return sum(
            (line.estimated_total for line in self.lines.all()), Decimal('0.00'),
        )


class RequisitionTemplateLine(TenantAwareModel, TimeStampedModel):
    """A single pre-defined line on a requisition template."""

    template = models.ForeignKey(
        RequisitionTemplate, on_delete=models.CASCADE, related_name='lines',
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('1.00'),
    )
    unit = models.CharField(max_length=30, default='unit')
    estimated_unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
    )
    account_code = models.ForeignKey(
        AccountCode, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='template_lines',
    )

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.description} x{self.quantity}'

    @property
    def estimated_total(self):
        return (self.quantity or Decimal('0')) * (self.estimated_unit_price or Decimal('0'))


# ---------- 1. Requisition Creation / 2. Tracking / 5. Amendment ----------

class Requisition(TenantAwareModel, TimeStampedModel):
    """A formal purchase request moving from draft to approval to PO conversion."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('converted', 'Converted to PO'),
    ]
    OPEN_STATUSES = ('draft', 'submitted', 'approved')

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='requisitions',
    )
    number = models.CharField(max_length=40, unique=True)
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    department = models.CharField(max_length=120, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    required_date = models.DateField(null=True, blank=True)
    justification = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='draft')
    revision = models.PositiveIntegerField(default=1)
    estimated_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
    )
    currency = models.CharField(max_length=3, default='USD')

    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='requisitions_decided',
    )
    decision_note = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    converted_at = models.DateTimeField(null=True, blank=True)
    po_reference = models.CharField(
        max_length=60, blank=True, help_text='Purchase order reference once converted',
    )

    created_from_template = models.ForeignKey(
        RequisitionTemplate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='requisitions',
    )
    possible_duplicate = models.BooleanField(default=False)
    duplicate_of = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='duplicates',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'requested_by', 'status']),
        ]

    def __str__(self):
        return f'{self.number} — {self.title}'

    @property
    def is_editable(self):
        """Only drafts can have their header/lines modified or be deleted."""
        return self.status == 'draft'

    @property
    def can_amend(self):
        """Submitted or approved requisitions can be pulled back for revision."""
        return self.status in ('submitted', 'approved')

    @property
    def can_cancel(self):
        return self.status in ('draft', 'submitted', 'approved')

    def recalc_total(self):
        total = sum(
            (line.line_total for line in self.lines.all()), Decimal('0.00'),
        )
        self.estimated_total = total
        self.save(update_fields=['estimated_total', 'updated_at'])
        return total


class RequisitionLine(TenantAwareModel, TimeStampedModel):
    """A single requested item on a requisition."""

    requisition = models.ForeignKey(
        Requisition, on_delete=models.CASCADE, related_name='lines',
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('1.00'),
    )
    unit = models.CharField(max_length=30, default='unit')
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
    )
    line_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
    )
    account_code = models.ForeignKey(
        AccountCode, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='requisition_lines',
    )
    required_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.description} x{self.quantity}'

    def save(self, *args, **kwargs):
        self.line_total = (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))
        super().save(*args, **kwargs)


# ---------- 2. Requisition Tracking ----------

class RequisitionStatusEvent(TenantAwareModel, TimeStampedModel):
    """An immutable entry in a requisition's status timeline."""

    requisition = models.ForeignKey(
        Requisition, on_delete=models.CASCADE, related_name='status_events',
    )
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='requisition_status_events',
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.requisition_id}: {self.from_status or "—"} → {self.to_status}'
