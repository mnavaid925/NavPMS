"""Spend Analytics & Reporting domain models (Module 15).

This is a read-mostly *analytics* module. It does not own transactional data — instead it
materializes spend that already exists in Invoicing (Module 14), Purchase Orders (Module 11),
Vendors (Module 5) and Contracts (Module 9) into one denormalized fact table, :class:`SpendRecord`,
and stores re-runnable report definitions in :class:`SpendReport`.

Two spend *bases* are tracked and are **NEVER summed together**:

* ``actual``    — money actually billed, sourced from ``invoicing.SupplierInvoiceLine`` whose parent
  invoice is ``approved`` or ``paid``.
* ``committed`` — money committed on a purchase order, sourced from
  ``purchase_orders.PurchaseOrderLine`` whose parent PO is not ``cancelled``.

A PO that is later invoiced legitimately produces BOTH a ``committed`` row and (once approved/paid)
an ``actual`` row, so every aggregation filters on exactly one ``basis`` (default ``actual``).

The fact table is kept in sync by :func:`apps.spend_analytics.services.sync_spend_facts` (an
idempotent upsert + prune), driven by the ``run_spend_sync`` management command and a lazy sweep on
the dashboard. See the design spec for the full rationale.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel


# ---------------------------------------------------------------------------
# Module-level choice constants + sync policy
# ---------------------------------------------------------------------------
SOURCE_TYPE_CHOICES = [
    ('invoice_line', 'Invoice line'),
    ('po_line', 'PO line'),
]

BASIS_CHOICES = [
    ('actual', 'Actual (invoiced)'),
    ('committed', 'Committed (PO)'),
]

MAVERICK_REASON_CHOICES = [
    ('off_preferred_supplier', 'Off preferred supplier'),
    ('off_contract', 'No active contract'),
    ('off_po', 'Non-PO purchase'),
]

# A VendorSegment whose code OR name (lower-cased) is in this set is treated as "preferred".
PREFERRED_SEGMENT_TOKENS = {'preferred', 'strategic'}

# Invoice statuses that count as ACTUAL spend.
ACTUAL_INVOICE_STATUSES = ('approved', 'paid')
# PO statuses that do NOT count as COMMITTED spend (everything else does).
COMMITTED_PO_EXCLUDE_STATUSES = ('cancelled',)

# Report builder choices.
DIMENSION_CHOICES = [
    ('vendor', 'Vendor'),
    ('vendor_category', 'Category'),
    ('account_code', 'Cost Center / Account Code'),
    ('vendor_segment', 'Vendor Segment'),
    ('month', 'Month'),
    ('source_type', 'Source Type'),
]

MEASURE_CHOICES = [
    ('amount_sum', 'Total spend'),
    ('net_sum', 'Net spend'),
    ('record_count', 'Record count'),
    ('amount_avg', 'Average spend'),
]

CHART_TYPE_CHOICES = [
    ('bar', 'Bar'),
    ('doughnut', 'Doughnut'),
    ('line', 'Line'),
]


def _money(**kwargs):
    """A 14,2 money field (matches the PO / invoice money convention)."""
    kwargs.setdefault('default', Decimal('0.00'))
    return models.DecimalField(max_digits=14, decimal_places=2, **kwargs)


# ---------------------------------------------------------------------------
# The spend fact table
# ---------------------------------------------------------------------------
class SpendRecord(TenantAwareModel, TimeStampedModel):
    """One denormalized spend fact per source line (an invoice line or a PO line).

    System-synced — there is no human-facing number and no manual CRUD. Dimensions are
    denormalized so every chart/report queries this one table without joins, and the maverick
    flags are computed once at sync time so the tracking pages filter cheaply.
    """

    SOURCE_TYPE_CHOICES = SOURCE_TYPE_CHOICES
    BASIS_CHOICES = BASIS_CHOICES

    # Provenance key — (tenant, source_type, source_id) is unique so sync is an idempotent upsert.
    # source_id is a plain integer (NOT a FK) so a deleted source line is prunable without a
    # PROTECT/cascade coupling back onto the transactional models.
    source_type = models.CharField(max_length=12, choices=SOURCE_TYPE_CHOICES)
    source_id = models.PositiveBigIntegerField()
    basis = models.CharField(max_length=10, choices=BASIS_CHOICES)

    # Denormalized dimensions (all nullable so a sparse source line still syncs). FKs are SET_NULL
    # so this derived projection never blocks a delete on the transactional side.
    spend_date = models.DateField(null=True, blank=True)
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='spend_records',
    )
    vendor_category = models.ForeignKey(
        'vendors.VendorCategory', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='spend_records',
    )
    vendor_segment = models.ForeignKey(
        'vendors.VendorSegment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='spend_records',
    )
    account_code = models.ForeignKey(
        'requisitions.AccountCode', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='spend_records',
        help_text='Cost centre / GL account (the "department" dimension).',
    )

    # Money (single reporting currency assumed for v1; currency is stored per row regardless).
    currency = models.CharField(max_length=3, default='USD')
    amount = _money(help_text='Line total (pre-tax).')
    tax_amount = _money(help_text='Line tax (PO lines carry none).')
    net_amount = _money(help_text='Net (pre-tax) spend; an explicit column for the "net" measure.')

    # Maverick flags — computed at sync, persisted so the tracking pages filter cheaply.
    off_preferred_supplier = models.BooleanField(default=False)
    off_contract = models.BooleanField(default=False)
    off_po = models.BooleanField(default=False)
    is_maverick = models.BooleanField(default=False)

    # Provenance / denormalized human refs (so exports + drill tables need no extra joins).
    source_ref = models.CharField(max_length=64, blank=True)
    vendor_name = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=255, blank=True)
    source_status = models.CharField(max_length=20, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-spend_date', '-id']
        unique_together = [('tenant', 'source_type', 'source_id')]
        indexes = [
            models.Index(fields=['tenant', 'spend_date']),
            models.Index(fields=['tenant', 'vendor']),
            models.Index(fields=['tenant', 'source_type']),
            models.Index(fields=['tenant', 'is_maverick']),
            models.Index(fields=['tenant', 'basis']),
            models.Index(fields=['tenant', 'vendor_category']),
        ]

    def __str__(self):
        return f'{self.source_ref or self.source_type} {self.amount} {self.currency}'

    @property
    def maverick_reasons(self):
        """List of human reason labels for this record's set maverick flags."""
        labels = dict(MAVERICK_REASON_CHOICES)
        out = []
        if self.off_preferred_supplier:
            out.append(labels['off_preferred_supplier'])
        if self.off_contract:
            out.append(labels['off_contract'])
        if self.off_po:
            out.append(labels['off_po'])
        return out


# ---------------------------------------------------------------------------
# Saved, re-runnable report definitions (the Custom Report Builder)
# ---------------------------------------------------------------------------
class SpendReport(TenantAwareModel, TimeStampedModel):
    """A saved spend report: a dimension + measure + chart type + saved filters.

    Form-driven (not drag-and-drop on this stack). Low-volume and user-named like
    ``portal.SavedReport`` — no human number, and ``name`` is not unique, so there is no
    tenant-scoped ``unique_together`` (which would otherwise need re-validation in the form).
    """

    DIMENSION_CHOICES = DIMENSION_CHOICES
    MEASURE_CHOICES = MEASURE_CHOICES
    CHART_TYPE_CHOICES = CHART_TYPE_CHOICES
    BASIS_CHOICES = BASIS_CHOICES
    SOURCE_TYPE_CHOICES = SOURCE_TYPE_CHOICES

    name = models.CharField(max_length=160)
    description = models.CharField(max_length=255, blank=True)

    dimension = models.CharField(
        max_length=20, choices=DIMENSION_CHOICES, default='vendor_category',
    )
    measure = models.CharField(max_length=20, choices=MEASURE_CHOICES, default='amount_sum')
    chart_type = models.CharField(max_length=10, choices=CHART_TYPE_CHOICES, default='bar')
    # Actual & committed are never summed together, so basis is a required single choice.
    basis = models.CharField(max_length=10, choices=BASIS_CHOICES, default='actual')

    # Saved filters (all optional; scoped to the tenant in the form).
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='spend_reports',
    )
    vendor_category = models.ForeignKey(
        'vendors.VendorCategory', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='spend_reports',
    )
    vendor_segment = models.ForeignKey(
        'vendors.VendorSegment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='spend_reports',
    )
    account_code = models.ForeignKey(
        'requisitions.AccountCode', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='spend_reports',
    )
    source_type = models.CharField(
        max_length=12, choices=SOURCE_TYPE_CHOICES, blank=True,
        help_text='Blank = both invoice and PO lines (within the chosen basis).',
    )
    maverick_only = models.BooleanField(default=False)

    is_shared = models.BooleanField(
        default=False, help_text='Shared reports are visible to every viewer in the tenant.',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='spend_reports',
    )
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'owner']),
        ]

    def __str__(self):
        return self.name
