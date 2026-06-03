"""Module 10: Catalog Management.

Covers the five PMS sub-modules:
  1. Catalog Item Creation       -> CatalogCategory + CatalogItem (internal stock
                                    items and supplier products, descriptions, pricing)
  2. Pricing & Tier Management   -> CatalogItem.base_price + CatalogPriceTier
                                    (volume breaks, contract pricing, effective dates)
  3. Catalog Approval Workflow   -> CatalogItem.status lifecycle + CatalogPriceChangeRequest
                                    (a self-contained review of new items / price changes)
                                    + CatalogItemStatusEvent (append-only timeline)
  4. Punch-out Integration       -> SupplierPunchoutConfig + PunchoutSession
                                    (real cXML/OCI round-trip; connectors live in punchout.py)
  5. Supplier Catalog Hosting    -> SupplierCatalogUpload (a supplier uploads a CSV/XLSX
                                    which is parsed and ingested as staged draft items)

A catalog item is authored (internally or ingested from a supplier upload / punch-out
cart), reviewed through its approval workflow, and — once approved — becomes orderable
on a requisition line. Price changes to an approved item are themselves reviewed.
Mirrors the Module 9 (Contracts) conventions: TenantAwareModel + TimeStampedModel bases,
module-level status constants + EDITABLE/OPEN/FINISHED tuples, gap-free PREFIX-<SLUG>-NNNNN
numbering (in services.py), and an append-only status-event timeline.

Decimal convention: extended/total figures use 2 dp (the project money pattern); per-unit
catalog prices use 4 dp because bulk-goods unit prices are frequently sub-cent.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import TenantAwareModel, TimeStampedModel

from .validators import CATALOG_UPLOAD_EXTENSIONS, validate_upload_size


# ---------------------------------------------------------------------------
# Choice constants (module-level, mirroring the contracts module)
# ---------------------------------------------------------------------------
ITEM_SOURCE_CHOICES = [
    ('internal', 'Internal stock item'),
    ('supplier', 'Supplier product'),
]

UOM_CHOICES = [
    ('each', 'Each'),
    ('box', 'Box'),
    ('case', 'Case'),
    ('pack', 'Pack'),
    ('kg', 'Kilogram'),
    ('g', 'Gram'),
    ('l', 'Litre'),
    ('m', 'Metre'),
    ('hour', 'Hour'),
    ('day', 'Day'),
    ('unit', 'Unit'),
    ('set', 'Set'),
    ('roll', 'Roll'),
]

CATALOG_ITEM_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('pending_approval', 'Pending Approval'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('retired', 'Retired'),
    ('archived', 'Archived'),
]
ITEM_EDITABLE_STATUSES = ('draft', 'rejected')
ITEM_SUBMITTABLE_STATUSES = ('draft', 'rejected')
ITEM_OPEN_STATUSES = ('draft', 'pending_approval', 'approved')
ITEM_ORDERABLE_STATUSES = ('approved',)
ITEM_FINISHED_STATUSES = ('retired', 'archived')

TIER_TYPE_CHOICES = [
    ('volume', 'Volume break'),
    ('contract', 'Contract price'),
]

PRICE_CHANGE_TYPE_CHOICES = [
    ('base', 'Base price'),
    ('tiers', 'Tier schedule'),
    ('both', 'Base price & tiers'),
]
PRICE_CHANGE_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('pending_approval', 'Pending Approval'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled'),
]
PRICE_CHANGE_EDITABLE_STATUSES = ('draft',)

PUNCHOUT_PROTOCOL_CHOICES = [
    ('cxml', 'cXML'),
    ('oci', 'OCI (Open Catalog Interface)'),
]
PUNCHOUT_SESSION_STATUS_CHOICES = [
    ('initiated', 'Initiated'),
    ('redirected', 'Redirected'),
    ('returned', 'Returned'),
    ('expired', 'Expired'),
    ('failed', 'Failed'),
]
PUNCHOUT_SESSION_OPEN_STATUSES = ('initiated', 'redirected')

UPLOAD_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('processing', 'Processing'),
    ('imported', 'Imported'),
    ('partially_imported', 'Partially imported'),
    ('failed', 'Failed'),
]
UPLOAD_OPEN_STATUSES = ('pending', 'processing')


# ---------- 1. Catalog Item Creation — product taxonomy ----------

class CatalogCategory(TenantAwareModel, TimeStampedModel):
    """A product/commodity category for the catalog (a UNSPSC-style taxonomy).

    Distinct from ``vendors.VendorCategory`` (which classifies *suppliers*): a
    catalog item is classified by what it *is*, not by who sells it.
    """

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
        verbose_name_plural = 'Catalog categories'
        indexes = [models.Index(fields=['tenant', 'is_active'])]

    def __str__(self):
        return f'{self.code} — {self.name}'


# ---------- The central CatalogItem record ----------

class CatalogItem(TenantAwareModel, TimeStampedModel):
    """A single catalog product or service — internal stock or supplier-sourced."""

    SOURCE_CHOICES = ITEM_SOURCE_CHOICES
    STATUS_CHOICES = CATALOG_ITEM_STATUS_CHOICES
    UOM_CHOICES = UOM_CHOICES

    item_number = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    sku = models.CharField(max_length=60, blank=True)
    manufacturer_part_number = models.CharField(max_length=80, blank=True)
    keywords = models.CharField(
        max_length=255, blank=True, help_text='Comma-separated search terms.',
    )

    source = models.CharField(
        max_length=10, choices=ITEM_SOURCE_CHOICES, default='internal',
    )
    category = models.ForeignKey(
        CatalogCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='items',
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_items',
        help_text='Supplier counterparty (required when the source is a supplier).',
    )
    account_code = models.ForeignKey(
        'requisitions.AccountCode', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_items', help_text='Default GL coding for this item.',
    )

    uom = models.CharField(max_length=12, choices=UOM_CHOICES, default='each')
    currency = models.CharField(max_length=3, default='USD')
    # Per-unit list price (4 dp — bulk-goods prices are frequently sub-cent).
    base_price = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal('0.0000'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='List unit price. The effective price is resolved from the tiers.',
    )
    min_order_qty = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('1.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    lead_time_days = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to='catalog_items/', blank=True, null=True)
    is_active = models.BooleanField(default=True)

    status = models.CharField(
        max_length=20, choices=CATALOG_ITEM_STATUS_CHOICES, default='draft',
    )

    # Provenance — where an ingested / captured item came from.
    source_upload = models.ForeignKey(
        'SupplierCatalogUpload', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='staged_items',
    )
    source_session = models.ForeignKey(
        'PunchoutSession', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='captured_items',
    )

    # Lifecycle stamps
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_items_approved',
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_items_created',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'item_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'source']),
            models.Index(fields=['tenant', 'category']),
            models.Index(fields=['tenant', 'vendor']),
        ]

    def __str__(self):
        return f'{self.item_number} — {self.name}'

    # --- status helpers ---
    @property
    def is_editable(self):
        return self.status in ITEM_EDITABLE_STATUSES

    @property
    def can_submit(self):
        return self.status in ITEM_SUBMITTABLE_STATUSES

    @property
    def is_pending(self):
        return self.status == 'pending_approval'

    @property
    def is_approved(self):
        return self.status == 'approved'

    @property
    def is_orderable(self):
        return self.status in ITEM_ORDERABLE_STATUSES

    @property
    def can_retire(self):
        return self.status == 'approved'

    @property
    def is_finished(self):
        return self.status in ITEM_FINISHED_STATUSES

    @property
    def effective_price(self):
        """Best current unit price for the item's minimum order quantity."""
        from . import services
        return services.resolve_price(self, qty=self.min_order_qty)


# ---------- 2. Pricing & Tier Management ----------

class CatalogPriceTier(TenantAwareModel, TimeStampedModel):
    """A volume break or contract price for a catalog item, with effective dates."""

    TIER_TYPE_CHOICES = TIER_TYPE_CHOICES

    item = models.ForeignKey(
        CatalogItem, on_delete=models.CASCADE, related_name='price_tiers',
    )
    tier_type = models.CharField(
        max_length=12, choices=TIER_TYPE_CHOICES, default='volume',
    )
    min_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('1.00'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    unit_price = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal('0.0000'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    contract = models.ForeignKey(
        'contracts.Contract', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_price_tiers',
        help_text='Contract this negotiated price comes from (contract tiers only).',
    )
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['item', '-tier_type', 'min_quantity']
        indexes = [models.Index(fields=['tenant', 'item', 'effective_from'])]

    def __str__(self):
        return f'{self.item.item_number} @ {self.min_quantity}+ = {self.unit_price}'

    @property
    def is_current(self):
        """True if active and today falls inside the (open-ended) effective window."""
        if not self.is_active:
            return False
        today = timezone.localdate()
        if self.effective_from and today < self.effective_from:
            return False
        if self.effective_to and today > self.effective_to:
            return False
        return True


# ---------- 3. Catalog Approval Workflow — price-change requests ----------

class CatalogPriceChangeRequest(TenantAwareModel, TimeStampedModel):
    """A reviewed change to an approved item's price / tier schedule.

    Approving the request applies the proposed base price and/or replaces the
    item's tier schedule atomically (mirrors how an applied contract amendment is
    snapshotted and frozen).
    """

    CHANGE_TYPE_CHOICES = PRICE_CHANGE_TYPE_CHOICES
    STATUS_CHOICES = PRICE_CHANGE_STATUS_CHOICES

    item = models.ForeignKey(
        CatalogItem, on_delete=models.CASCADE, related_name='price_change_requests',
    )
    request_number = models.CharField(max_length=48)
    change_type = models.CharField(
        max_length=16, choices=PRICE_CHANGE_TYPE_CHOICES, default='base',
    )
    reason = models.TextField(blank=True)

    # Proposed changes — NULL/empty means "no change to this".
    new_base_price = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
    )
    proposed_tiers = models.JSONField(
        default=list, blank=True,
        help_text='List of {min_quantity, unit_price, tier_type, effective_from, '
                  'effective_to} applied atomically on approval.',
    )

    # Snapshot captured at apply time (audit trail).
    prev_base_price = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True,
    )
    prev_tiers = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=20, choices=PRICE_CHANGE_STATUS_CHOICES, default='draft',
    )
    effective_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_price_changes_created',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_price_changes_decided',
    )
    decision_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('item', 'request_number')]

    def __str__(self):
        return f'{self.request_number} on {self.item.item_number}'

    @property
    def is_editable(self):
        return self.status in PRICE_CHANGE_EDITABLE_STATUSES

    @property
    def is_applied(self):
        return self.status == 'approved'


# ---------- Append-only lifecycle timeline ----------

class CatalogItemStatusEvent(TenantAwareModel, TimeStampedModel):
    """An append-only record of every catalog-item / price-change transition."""

    item = models.ForeignKey(
        CatalogItem, on_delete=models.CASCADE, related_name='status_events',
    )
    price_change = models.ForeignKey(
        CatalogPriceChangeRequest, on_delete=models.CASCADE, null=True, blank=True,
        related_name='status_events',
    )
    status = models.CharField(max_length=20)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_status_events',
    )

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.item.item_number} → {self.status}'


# ---------- 4. Punch-out Catalog Integration (real cXML / OCI) ----------

class SupplierPunchoutConfig(TenantAwareModel, TimeStampedModel):
    """Per-supplier punch-out connection settings (cXML or OCI).

    WARNING: ``shared_secret`` is a credential. It is write-only in the forms
    (never rendered back), excluded from any template/admin display and never
    written to an audit payload. In production source it from a secret manager.
    The ``setup_url`` is SSRF-validated (HTTPS-only, public host) in ``clean()``
    and again in the service before any outbound request.
    """

    PROTOCOL_CHOICES = PUNCHOUT_PROTOCOL_CHOICES

    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='punchout_configs',
    )
    name = models.CharField(max_length=120)
    protocol = models.CharField(
        max_length=8, choices=PUNCHOUT_PROTOCOL_CHOICES, default='cxml',
    )
    setup_url = models.URLField(
        max_length=500,
        help_text='The supplier endpoint the PunchOutSetupRequest / OCI hook is sent to.',
    )
    # cXML identity (Header/Sender credentials).
    from_identity = models.CharField(max_length=120, blank=True)
    to_identity = models.CharField(max_length=120, blank=True)
    sender_identity = models.CharField(max_length=120, blank=True)
    # WARNING: credential — write-only in forms, never rendered, never audited.
    shared_secret = models.CharField(max_length=255, blank=True)
    # OCI extras.
    username = models.CharField(max_length=120, blank=True)
    extra_params = models.JSONField(
        default=dict, blank=True,
        help_text='Static OCI form fields (HOOK_URL is added at runtime).',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['vendor', 'name']
        unique_together = [('tenant', 'vendor', 'name')]
        indexes = [models.Index(fields=['tenant', 'is_active'])]

    def __str__(self):
        return f'{self.name} ({self.get_protocol_display()})'

    def clean(self):
        # SSRF guard at the model layer so admin saves are protected too.
        from . import services
        if self.setup_url:
            try:
                services.validate_punchout_url(self.setup_url)
            except ValidationError:
                raise
            except Exception as exc:  # defensive — surface as a field error
                raise ValidationError({'setup_url': str(exc)})


class PunchoutSession(TenantAwareModel, TimeStampedModel):
    """One punch-out round-trip: setup → redirect → returned cart."""

    STATUS_CHOICES = PUNCHOUT_SESSION_STATUS_CHOICES

    config = models.ForeignKey(
        SupplierPunchoutConfig, on_delete=models.CASCADE, related_name='sessions',
    )
    # Denormalised for the vendor-portal visibility gate / fast filtering.
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='punchout_sessions',
    )
    # Opaque correlation token echoed in the cXML <BuyerCookie> / OCI ~OCI_SESSION.
    buyer_cookie = models.CharField(max_length=64, unique=True)
    # WARNING: unguessable; the only credential authenticating the inbound cart POST.
    return_token = models.CharField(max_length=64, unique=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='punchout_sessions',
    )
    requisition = models.ForeignKey(
        'requisitions.Requisition', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='punchout_sessions', help_text='Optional cart destination.',
    )
    status = models.CharField(
        max_length=12, choices=PUNCHOUT_SESSION_STATUS_CHOICES, default='initiated',
    )
    start_page_url = models.URLField(max_length=1000, blank=True)
    cart_data = models.JSONField(default=list, blank=True)
    error_message = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    redirected_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'vendor']),
        ]

    def __str__(self):
        return f'PunchOut {self.buyer_cookie[:8]} ({self.status})'

    @property
    def is_open(self):
        return self.status in PUNCHOUT_SESSION_OPEN_STATUSES

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at < timezone.now())

    @property
    def line_count(self):
        return len(self.cart_data or [])


# ---------- 5. Supplier Catalog Hosting — uploads (parse-and-ingest) ----------

class SupplierCatalogUpload(TenantAwareModel, TimeStampedModel):
    """A catalog file a supplier uploads from the vendor portal, parsed and ingested.

    Valid rows are staged as draft ``CatalogItem`` rows (source='supplier') that then
    flow through the approval workflow. Mirrors the ``VendorDocument`` FileField plus
    an extension + size validator.
    """

    STATUS_CHOICES = UPLOAD_STATUS_CHOICES

    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='catalog_uploads',
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='catalog_uploads',
    )
    file = models.FileField(
        upload_to='catalog_uploads/',
        validators=[
            FileExtensionValidator(allowed_extensions=list(CATALOG_UPLOAD_EXTENSIONS)),
            validate_upload_size,
        ],
    )
    original_filename = models.CharField(max_length=255, blank=True)
    category = models.ForeignKey(
        CatalogCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploads',
    )
    status = models.CharField(
        max_length=20, choices=UPLOAD_STATUS_CHOICES, default='pending',
    )
    row_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    error_log = models.JSONField(
        default=list, blank=True, help_text='List of {row, field, message}.',
    )
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'vendor']),
        ]

    def __str__(self):
        return f'{self.vendor.legal_name} — {self.original_filename or self.file.name}'

    @property
    def is_open(self):
        return self.status in UPLOAD_OPEN_STATUSES
