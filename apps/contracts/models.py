"""Module 9: Contract Management.

Covers the five PMS sub-modules:
  1. Contract Authoring & Templating   -> ContractClause (library) + ContractTemplate
                                          (+ ContractTemplateClause) + ContractClauseLine
                                          (assembled on a Contract) + Contract.body
  2. E-Signature Integration           -> ContractSignatory (internal + supplier, mock
                                          tokenized signing) + Contract signing stamps
  3. Renewal & Expiration Alerts       -> Contract.end_date / auto_renew /
                                          renewal_notice_days / renewal_alerted_at
  4. Contract Amendment Tracking       -> ContractAmendment + Contract.revision
  5. Obligation & Milestone Management -> ContractObligation (deliverables, milestones,
                                          payment, penalties)

A Contract is authored from a clause library / template, signed by an ordered set of
signatories (the *mock* in-app e-signature flow — typed name + tokenized link, pluggable
for a real provider later), then runs through its term with tracked obligations until it is
renewed, terminated or expires. ContractStatusEvent is an append-only lifecycle timeline.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Choice constants (module-level, mirroring the auctions module)
# ---------------------------------------------------------------------------
CONTRACT_TYPE_CHOICES = [
    ('msa', 'Master Service Agreement'),
    ('sow', 'Statement of Work'),
    ('nda', 'Non-Disclosure Agreement'),
    ('service', 'Service Agreement'),
    ('supply', 'Supply Agreement'),
    ('lease', 'Lease'),
    ('framework', 'Framework Agreement'),
    ('purchase', 'Purchase Agreement'),
    ('other', 'Other'),
]

CONTRACT_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('pending_signature', 'Pending Signature'),
    ('active', 'Active'),
    ('expired', 'Expired'),
    ('terminated', 'Terminated'),
    ('renewed', 'Renewed'),
    ('cancelled', 'Cancelled'),
]
CONTRACT_EDITABLE_STATUSES = ('draft',)
CONTRACT_SIGNING_STATUSES = ('pending_signature',)
CONTRACT_CANCELLABLE_STATUSES = ('draft', 'pending_signature')
CONTRACT_RENEWABLE_STATUSES = ('active', 'expired')
CONTRACT_FINISHED_STATUSES = ('expired', 'terminated', 'renewed', 'cancelled')

CLAUSE_CATEGORY_CHOICES = [
    ('payment', 'Payment Terms'),
    ('liability', 'Liability & Indemnity'),
    ('confidentiality', 'Confidentiality'),
    ('termination', 'Termination'),
    ('ip', 'Intellectual Property'),
    ('compliance', 'Compliance'),
    ('sla', 'Service Levels'),
    ('warranty', 'Warranty'),
    ('general', 'General'),
]

SIGNATORY_PARTY_CHOICES = [
    ('internal', 'Internal stakeholder'),
    ('vendor', 'Supplier'),
]
SIGNATORY_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('signed', 'Signed'),
    ('declined', 'Declined'),
]
SIGNATORY_OPEN_STATUSES = ('pending',)

AMENDMENT_CHANGE_TYPE_CHOICES = [
    ('value', 'Value change'),
    ('term_extension', 'Term extension'),
    ('scope', 'Scope change'),
    ('renewal', 'Renewal'),
    ('other', 'Other'),
]
AMENDMENT_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('pending_approval', 'Pending approval'),
    ('applied', 'Applied'),
    ('cancelled', 'Cancelled'),
]
AMENDMENT_EDITABLE_STATUSES = ('draft', 'pending_approval')

OBLIGATION_TYPE_CHOICES = [
    ('deliverable', 'Deliverable'),
    ('milestone', 'Milestone'),
    ('payment', 'Payment milestone'),
    ('penalty', 'Penalty / SLA credit'),
    ('sla', 'Service level'),
    ('report', 'Report / compliance'),
]
OBLIGATION_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('in_progress', 'In progress'),
    ('completed', 'Completed'),
    ('overdue', 'Overdue'),
    ('waived', 'Waived'),
]
OBLIGATION_OPEN_STATUSES = ('pending', 'in_progress', 'overdue')


# ---------- 1. Contract Authoring & Templating — clause library ----------

class ContractClause(TenantAwareModel, TimeStampedModel):
    """A pre-approved, reusable legal clause in the tenant's clause library."""

    CATEGORY_CHOICES = CLAUSE_CATEGORY_CHOICES

    title = models.CharField(max_length=200)
    category = models.CharField(
        max_length=20, choices=CLAUSE_CATEGORY_CHOICES, default='general',
    )
    body = models.TextField(help_text='Standard clause text. May contain {{vendor_name}} tokens.')
    is_standard = models.BooleanField(
        default=True, help_text='Standard, pre-approved by legal.',
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['category', 'sort_order', 'title']
        unique_together = [('tenant', 'title')]
        indexes = [models.Index(fields=['tenant', 'category'])]

    def __str__(self):
        return f'{self.title} ({self.get_category_display()})'


# ---------- 1. Contract Authoring & Templating — contract templates ----------

class ContractTemplate(TenantAwareModel, TimeStampedModel):
    """A reusable contract skeleton: an ordered set of clauses + metadata."""

    TYPE_CHOICES = CONTRACT_TYPE_CHOICES

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    contract_type = models.CharField(
        max_length=12, choices=CONTRACT_TYPE_CHOICES, default='other',
    )
    is_shared = models.BooleanField(
        default=True, help_text='Visible to every user in the tenant.',
    )
    archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contract_templates_created',
    )

    class Meta:
        ordering = ['title']
        unique_together = [('tenant', 'title')]

    def __str__(self):
        return self.title


class ContractTemplateClause(TenantAwareModel, TimeStampedModel):
    """An ordered clause slot inside a contract template (the cloneable structure)."""

    template = models.ForeignKey(
        ContractTemplate, on_delete=models.CASCADE, related_name='clauses',
    )
    clause = models.ForeignKey(
        ContractClause, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='template_uses',
        help_text='Library clause this slot was snapshotted from (provenance).',
    )
    heading = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.heading} ({self.template.title})'


# ---------- The central Contract record ----------

class Contract(TenantAwareModel, TimeStampedModel):
    """A contract with a supplier — authored, signed, run and renewed/terminated."""

    STATUS_CHOICES = CONTRACT_STATUS_CHOICES
    TYPE_CHOICES = CONTRACT_TYPE_CHOICES

    contract_number = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    contract_type = models.CharField(
        max_length=12, choices=CONTRACT_TYPE_CHOICES, default='other',
    )
    category = models.ForeignKey(
        'vendors.VendorCategory', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contracts',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='contracts',
        help_text='The supplier counterparty.',
    )
    currency = models.CharField(max_length=3, default='USD')
    value = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )

    body = models.TextField(
        blank=True, help_text='Authored contract text, assembled from clauses.',
    )
    terms_and_conditions = models.TextField(blank=True)

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # 3. Renewal & Expiration Alerts
    auto_renew = models.BooleanField(default=False)
    renewal_term_months = models.PositiveIntegerField(
        default=12, help_text='Length of an auto-renewal / renewal term.',
    )
    renewal_notice_days = models.PositiveIntegerField(
        default=30, help_text='Raise an alert this many days before end_date.',
    )
    renewal_alerted_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Set when the renewal alert was raised (idempotency guard).',
    )

    # 4. Amendment / version control
    revision = models.PositiveIntegerField(default=1)
    parent_contract = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='renewals',
        help_text='The predecessor contract this one was renewed from.',
    )

    # Provenance hooks
    template = models.ForeignKey(
        ContractTemplate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='contracts',
    )
    sourcing_event = models.ForeignKey(
        'sourcing.SourcingEvent', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contracts',
    )
    requisition = models.ForeignKey(
        'requisitions.Requisition', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contracts',
    )

    status = models.CharField(
        max_length=20, choices=CONTRACT_STATUS_CHOICES, default='draft',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contracts_owned',
        help_text='Internal contract manager / owner.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contracts_created',
    )

    # Lifecycle stamps
    signature_sent_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)
    terminated_reason = models.CharField(max_length=255, blank=True)
    terminated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contracts_terminated',
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'contract_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'contract_type']),
            models.Index(fields=['tenant', 'end_date']),
        ]

    def __str__(self):
        return f'{self.contract_number} — {self.title}'

    # --- status helpers ---
    @property
    def is_editable(self):
        return self.status in CONTRACT_EDITABLE_STATUSES

    @property
    def is_active(self):
        return self.status == 'active'

    @property
    def is_pending_signature(self):
        return self.status in CONTRACT_SIGNING_STATUSES

    @property
    def can_cancel(self):
        return self.status in CONTRACT_CANCELLABLE_STATUSES

    @property
    def can_terminate(self):
        return self.status == 'active'

    @property
    def can_renew(self):
        return self.status in CONTRACT_RENEWABLE_STATUSES

    @property
    def is_finished(self):
        return self.status in CONTRACT_FINISHED_STATUSES

    # --- signing helpers ---
    @property
    def signed_count(self):
        return self.signatories.filter(status='signed').count()

    @property
    def signatory_count(self):
        return self.signatories.count()

    @property
    def pending_count(self):
        return self.signatories.filter(status__in=SIGNATORY_OPEN_STATUSES).count()

    @property
    def is_fully_signed(self):
        """True if there is at least one signatory and none are still pending."""
        total = self.signatory_count
        return total > 0 and self.pending_count == 0 and not self.signatories.filter(
            status='declined').exists()

    @property
    def signature_progress(self):
        """Percent of signatories who have signed (0-100)."""
        total = self.signatory_count
        if not total:
            return 0
        return int(round(self.signed_count / total * 100))

    # --- expiry helpers ---
    @property
    def days_to_expiry(self):
        if not self.end_date:
            return None
        return (self.end_date - timezone.localdate()).days

    @property
    def is_expiring_soon(self):
        days = self.days_to_expiry
        if days is None:
            return False
        return 0 <= days <= self.renewal_notice_days

    @property
    def is_past_due(self):
        days = self.days_to_expiry
        return days is not None and days < 0


# ---------- 1. Authoring — clauses assembled onto a concrete contract ----------

class ContractClauseLine(TenantAwareModel, TimeStampedModel):
    """An authored clause on a specific contract (snapshotted from the library)."""

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name='clause_lines',
    )
    clause = models.ForeignKey(
        ContractClause, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='contract_uses',
    )
    heading = models.CharField(max_length=200)
    body = models.TextField()
    sort_order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['sort_order', 'id']
        unique_together = [('contract', 'sort_order')]

    def __str__(self):
        return f'{self.heading} ({self.contract.contract_number})'


# ---------- 2. E-Signature — ordered signatories (mock signing) ----------

class ContractSignatory(TenantAwareModel, TimeStampedModel):
    """An ordered signatory on a contract and their mock e-signature state.

    The signing flow is simulated in-app (no real crypto / external provider):
    ``send_for_signature`` assigns each pending signatory an unguessable
    ``sign_token`` (``secrets.token_urlsafe``); the holder of the link types
    their name to sign. Built pluggable so a real provider (DocuSign / Adobe Sign)
    can replace this later, mirroring the mock payment gateway.
    """

    PARTY_CHOICES = SIGNATORY_PARTY_CHOICES
    STATUS_CHOICES = SIGNATORY_STATUS_CHOICES

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name='signatories',
    )
    party = models.CharField(max_length=10, choices=SIGNATORY_PARTY_CHOICES)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contract_signatures',
        help_text='Internal signer (if any).',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='contract_signatures',
        help_text='Supplier signer (if any).',
    )
    name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    title = models.CharField(max_length=120, blank=True)
    order = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=10, choices=SIGNATORY_STATUS_CHOICES, default='pending',
    )
    # WARNING: must be an unguessable token (set via secrets.token_urlsafe in the
    # service). null when not yet sent so multiple unsent rows don't collide.
    sign_token = models.CharField(
        max_length=64, null=True, blank=True, unique=True, default=None,
    )
    signed_name = models.CharField(
        max_length=160, blank=True, help_text='Typed-name signature.',
    )
    signed_at = models.DateTimeField(null=True, blank=True)
    signature_ip = models.CharField(max_length=45, blank=True)
    decline_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['order', 'id']
        unique_together = [('contract', 'order')]
        indexes = [models.Index(fields=['tenant', 'status'])]

    def __str__(self):
        return f'{self.name} ({self.get_party_display()}) → {self.contract.contract_number}'

    @property
    def is_open(self):
        return self.status in SIGNATORY_OPEN_STATUSES


# ---------- 4. Amendment Tracking ----------

class ContractAmendment(TenantAwareModel, TimeStampedModel):
    """A tracked change to a contract — the version-control record."""

    CHANGE_TYPE_CHOICES = AMENDMENT_CHANGE_TYPE_CHOICES
    STATUS_CHOICES = AMENDMENT_STATUS_CHOICES

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name='amendments',
    )
    amendment_number = models.CharField(max_length=48)
    change_type = models.CharField(
        max_length=16, choices=AMENDMENT_CHANGE_TYPE_CHOICES, default='other',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Proposed changes — a NULL means "no change to this field".
    new_value = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
    )
    new_end_date = models.DateField(null=True, blank=True)
    new_body = models.TextField(blank=True)

    # Snapshot captured at apply time (audit trail).
    prev_value = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
    )
    prev_end_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=20, choices=AMENDMENT_STATUS_CHOICES, default='draft',
    )
    effective_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contract_amendments_created',
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contract_amendments_applied',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [('contract', 'amendment_number')]

    def __str__(self):
        return f'{self.amendment_number} on {self.contract.contract_number}'

    @property
    def is_applied(self):
        return self.status == 'applied'

    @property
    def is_editable(self):
        return self.status in AMENDMENT_EDITABLE_STATUSES


# ---------- 5. Obligation & Milestone Management ----------

class ContractObligation(TenantAwareModel, TimeStampedModel):
    """A deliverable, milestone, payment or penalty tied to a contract."""

    TYPE_CHOICES = OBLIGATION_TYPE_CHOICES
    STATUS_CHOICES = OBLIGATION_STATUS_CHOICES

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name='obligations',
    )
    obligation_type = models.CharField(
        max_length=16, choices=OBLIGATION_TYPE_CHOICES, default='deliverable',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Payment-milestone value (if applicable).',
    )
    penalty_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Penalty / SLA credit on breach (if applicable).',
    )
    account_code = models.ForeignKey(
        'requisitions.AccountCode', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contract_obligations',
    )
    responsible_party = models.CharField(
        max_length=10, choices=SIGNATORY_PARTY_CHOICES, default='vendor',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contract_obligations_owned',
    )
    status = models.CharField(
        max_length=12, choices=OBLIGATION_STATUS_CHOICES, default='pending',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contract_obligations_completed',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['due_date', 'id']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'due_date']),
        ]

    def __str__(self):
        return f'{self.title} ({self.get_obligation_type_display()})'

    @property
    def is_open(self):
        return self.status in OBLIGATION_OPEN_STATUSES

    @property
    def is_overdue(self):
        return (
            self.due_date is not None
            and self.due_date < timezone.localdate()
            and self.status in OBLIGATION_OPEN_STATUSES
        )


# ---------- Attachments ----------

class ContractDocument(TenantAwareModel, TimeStampedModel):
    """A document attached to a contract (signed PDF, supporting docs, etc.)."""

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name='documents',
    )
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='contract_docs/', blank=True, null=True)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contract_documents_uploaded',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.title} ({self.contract.contract_number})'


# ---------- Append-only lifecycle timeline ----------

class ContractStatusEvent(TenantAwareModel, TimeStampedModel):
    """An append-only record of every contract status transition."""

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name='status_events',
    )
    status = models.CharField(max_length=20, choices=CONTRACT_STATUS_CHOICES)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='contract_status_events',
    )

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.contract.contract_number} → {self.status}'
