"""Module 5: Vendor Management.

Covers the five PMS sub-modules:
  1. Vendor Onboarding              -> VendorOnboardingApplication + Vendor (status workflow)
  2. Vendor Portal                  -> Vendor.portal_user OneToOne to User
  3. Vendor Classification/Segments -> VendorCategory + VendorSegment
  4. Vendor Risk Profiling          -> VendorRiskAssessment (4-pillar 0-100)
  5. Vendor Blacklisting/Suspension -> VendorBlacklistEvent (append-only) + Vendor.status
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


VENDOR_TYPE_CHOICES = [
    ('manufacturer', 'Manufacturer'),
    ('distributor', 'Distributor'),
    ('service_provider', 'Service Provider'),
    ('contractor', 'Contractor'),
    ('consultant', 'Consultant'),
    ('other', 'Other'),
]

VENDOR_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('pending_verification', 'Pending Verification'),
    ('active', 'Active'),
    ('suspended', 'Suspended'),
    ('blacklisted', 'Blacklisted'),
    ('inactive', 'Inactive'),
]
VENDOR_OPEN_STATUSES = ('draft', 'pending_verification', 'active')

RISK_LEVEL_CHOICES = [
    ('low', 'Low'),
    ('medium', 'Medium'),
    ('high', 'High'),
    ('critical', 'Critical'),
]

# Module 17 performance rating bands. Duplicated here (rather than imported from
# apps.supplier_performance) so vendors carries no dependency on a downstream module — the value is
# written onto the Vendor row by supplier_performance.services.generate_scorecard.
PERFORMANCE_BAND_CHOICES = [
    ('excellent', 'Excellent'),
    ('good', 'Good'),
    ('acceptable', 'Acceptable'),
    ('poor', 'Poor'),
    ('critical', 'Critical'),
]

DOC_TYPE_CHOICES = [
    ('registration', 'Business Registration'),
    ('tax', 'Tax Certificate'),
    ('nda', 'Non-Disclosure Agreement'),
    ('insurance', 'Insurance Certificate'),
    ('bank', 'Bank Details'),
    ('quality_cert', 'Quality Certification'),
    ('other', 'Other'),
]

APPLICATION_STATUS_CHOICES = [
    ('submitted', 'Submitted'),
    ('under_review', 'Under Review'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]

BLACKLIST_ACTION_CHOICES = [
    ('suspend', 'Suspended'),
    ('blacklist', 'Blacklisted'),
    ('reinstate', 'Reinstated'),
]


def risk_level_from_score(score) -> str:
    s = float(score or 0)
    if s >= 76:
        return 'critical'
    if s >= 51:
        return 'high'
    if s >= 26:
        return 'medium'
    return 'low'


# ---------- 3. Classification & Segmentation ----------

class VendorCategory(TenantAwareModel, TimeStampedModel):
    """A classification node (e.g. Raw Materials > Steel)."""

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=40)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='children',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        unique_together = [('tenant', 'code')]
        verbose_name_plural = 'Vendor categories'

    def __str__(self):
        return self.name


class VendorSegment(TenantAwareModel, TimeStampedModel):
    """A vendor segment (e.g. Strategic, Tactical, Preferred, Approved)."""

    name = models.CharField(max_length=80)
    code = models.CharField(max_length=40)
    description = models.TextField(blank=True)
    color = models.CharField(
        max_length=20, default='secondary',
        help_text='Bootstrap badge color: primary/success/warning/danger/info/secondary',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        unique_together = [('tenant', 'code')]

    def __str__(self):
        return self.name


# ---------- Core Vendor entity ----------

class Vendor(TenantAwareModel, TimeStampedModel):
    """Top-level supplier record. Status drives every workflow."""

    STATUS_CHOICES = VENDOR_STATUS_CHOICES

    vendor_number = models.CharField(max_length=40)
    legal_name = models.CharField(max_length=200)
    trade_name = models.CharField(max_length=200, blank=True)
    vendor_type = models.CharField(
        max_length=20, choices=VENDOR_TYPE_CHOICES, default='other',
    )

    tax_id = models.CharField(max_length=80, blank=True)
    registration_number = models.CharField(max_length=80, blank=True)

    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    website = models.URLField(blank=True)

    country = models.CharField(max_length=80, blank=True)
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    primary_contact_name = models.CharField(max_length=120, blank=True)
    primary_contact_email = models.EmailField(blank=True)
    primary_contact_phone = models.CharField(max_length=40, blank=True)

    category = models.ForeignKey(
        VendorCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vendors',
    )
    segment = models.ForeignKey(
        VendorSegment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vendors',
    )

    status = models.CharField(
        max_length=24, choices=VENDOR_STATUS_CHOICES, default='draft',
    )
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_vendors',
    )

    risk_level = models.CharField(
        max_length=10, choices=RISK_LEVEL_CHOICES, default='low',
        help_text='Denormalised from the latest current VendorRiskAssessment.',
    )
    risk_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
    )

    # Module 17: denormalised latest performance score, kept current from the most recent FINAL
    # Scorecard by supplier_performance.services.generate_scorecard (same precedent as risk_*).
    performance_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text='Denormalised from the latest current Scorecard (0-100).',
    )
    performance_band = models.CharField(
        max_length=12, choices=PERFORMANCE_BAND_CHOICES, default='acceptable',
    )
    performance_scored_at = models.DateTimeField(null=True, blank=True)

    portal_user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vendor_account',
        help_text='User account with self-service portal access for this vendor.',
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['legal_name']
        unique_together = [('tenant', 'vendor_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'risk_level']),
            models.Index(fields=['tenant', 'performance_band']),
        ]

    def __str__(self):
        return f'{self.vendor_number} — {self.legal_name}'

    @property
    def display_name(self):
        return self.trade_name or self.legal_name

    @property
    def is_blocked(self):
        return self.status in ('suspended', 'blacklisted', 'inactive')

    @property
    def can_be_active(self):
        return self.status in ('draft', 'pending_verification', 'suspended')


# ---------- Vendor sub-records ----------

class VendorContact(TenantAwareModel, TimeStampedModel):
    """Additional point-of-contact for a vendor."""

    vendor = models.ForeignKey(
        Vendor, on_delete=models.CASCADE, related_name='contacts',
    )
    name = models.CharField(max_length=120)
    role = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    is_primary = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-is_primary', 'name']

    def __str__(self):
        return f'{self.name} ({self.vendor.legal_name})'


class VendorDocument(TenantAwareModel, TimeStampedModel):
    """An uploaded compliance / KYC document for a vendor."""

    vendor = models.ForeignKey(
        Vendor, on_delete=models.CASCADE, related_name='documents',
    )
    doc_type = models.CharField(max_length=24, choices=DOC_TYPE_CHOICES)
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='vendor_docs/', blank=True, null=True)
    description = models.TextField(blank=True)
    expires_at = models.DateField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='verified_vendor_documents',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.get_doc_type_display()})'

    @property
    def is_expired(self):
        from django.utils import timezone
        return bool(self.expires_at and self.expires_at < timezone.localdate())


class VendorBankAccount(TenantAwareModel, TimeStampedModel):
    """A bank account for paying a vendor."""

    vendor = models.ForeignKey(
        Vendor, on_delete=models.CASCADE, related_name='bank_accounts',
    )
    bank_name = models.CharField(max_length=160)
    account_holder = models.CharField(max_length=160)
    account_number = models.CharField(max_length=80)
    branch = models.CharField(max_length=160, blank=True)
    iban = models.CharField(max_length=64, blank=True)
    swift_code = models.CharField(max_length=20, blank=True)
    currency = models.CharField(max_length=3, default='USD')
    country = models.CharField(max_length=80, blank=True)
    is_primary = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-is_primary', 'bank_name']

    def __str__(self):
        return f'{self.bank_name} ({self.account_number[-4:]})'


# ---------- 1. Vendor Onboarding (public) ----------

class VendorOnboardingApplication(TenantAwareModel, TimeStampedModel):
    """A supplier-submitted application reachable via a public per-tenant URL."""

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    company_name = models.CharField(max_length=200)
    trade_name = models.CharField(max_length=200, blank=True)
    contact_name = models.CharField(max_length=160)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=40, blank=True)
    country = models.CharField(max_length=80, blank=True)
    vendor_type = models.CharField(
        max_length=20, choices=VENDOR_TYPE_CHOICES, default='other',
    )
    tax_id = models.CharField(max_length=80, blank=True)
    registration_number = models.CharField(max_length=80, blank=True)
    website = models.URLField(blank=True)
    service_description = models.TextField(
        blank=True, help_text='What goods or services does the vendor offer?',
    )

    status = models.CharField(
        max_length=20, choices=APPLICATION_STATUS_CHOICES, default='submitted',
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_vendor_applications',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    review_notes = models.TextField(blank=True)

    converted_to_vendor = models.ForeignKey(
        Vendor, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='source_applications',
    )

    class Meta:
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['tenant', 'status']),
        ]

    def __str__(self):
        return f'{self.company_name} ({self.get_status_display()})'

    @property
    def is_open(self):
        return self.status in ('submitted', 'under_review')


# ---------- 4. Risk Profiling ----------

class VendorRiskAssessment(TenantAwareModel, TimeStampedModel):
    """Four-pillar 0-100 risk assessment for a vendor."""

    LEVEL_CHOICES = RISK_LEVEL_CHOICES

    vendor = models.ForeignKey(
        Vendor, on_delete=models.CASCADE, related_name='risk_assessments',
    )
    assessment_date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)

    financial_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='Financial risk 0 (low) to 100 (critical).',
    )
    operational_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    compliance_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    quality_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    overall_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
    )
    level = models.CharField(
        max_length=10, choices=RISK_LEVEL_CHOICES, default='low',
    )

    notes = models.TextField(blank=True)
    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vendor_risk_assessments',
    )
    is_current = models.BooleanField(default=True)

    class Meta:
        ordering = ['-assessment_date', '-created_at']
        indexes = [
            models.Index(fields=['tenant', 'vendor', 'is_current']),
        ]

    def __str__(self):
        return f'{self.vendor.legal_name} — {self.get_level_display()} ({self.assessment_date})'

    def recalc(self):
        scores = [
            self.financial_score or Decimal('0'),
            self.operational_score or Decimal('0'),
            self.compliance_score or Decimal('0'),
            self.quality_score or Decimal('0'),
        ]
        avg = sum(scores) / Decimal('4')
        self.overall_score = avg.quantize(Decimal('0.01'))
        self.level = risk_level_from_score(self.overall_score)

    def save(self, *args, **kwargs):
        self.recalc()
        super().save(*args, **kwargs)


# ---------- 5. Blacklist / Suspension ----------

class VendorBlacklistEvent(TenantAwareModel, TimeStampedModel):
    """An append-only suspend / blacklist / reinstate event for a vendor."""

    ACTION_CHOICES = BLACKLIST_ACTION_CHOICES

    vendor = models.ForeignKey(
        Vendor, on_delete=models.CASCADE, related_name='blacklist_events',
    )
    action = models.CharField(max_length=20, choices=BLACKLIST_ACTION_CHOICES)
    effective_date = models.DateField()
    end_date = models.DateField(
        null=True, blank=True,
        help_text='For suspensions only — leave blank for an indefinite block.',
    )
    reason = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    actioned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vendor_blacklist_events',
    )

    class Meta:
        ordering = ['-effective_date', '-created_at']
        indexes = [
            models.Index(fields=['tenant', 'vendor', 'action']),
        ]

    def __str__(self):
        return f'{self.vendor.legal_name}: {self.get_action_display()} on {self.effective_date}'
