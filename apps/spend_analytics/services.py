"""Spend Analytics & Reporting services (Module 15).

The heart is :func:`sync_spend_facts` — an idempotent *upsert + prune* that materializes the
:class:`~apps.spend_analytics.models.SpendRecord` fact table from approved/paid supplier invoice
lines (``actual`` basis) and non-cancelled PO lines (``committed`` basis), denormalizing the
dimensions and computing the maverick flags once. Everything else (dashboard metrics, category
analysis, maverick tracking, the report runner, export rows) reads the fact table.

Conventions mirrored from Module 13 (goods_receipt): ``MANAGE_ROLES``/``VIEW_ROLES`` + ``_has_role``
permission helpers, ``record_audit`` from :mod:`apps.tenants.services`, ``@transaction.atomic`` for
the write path, and a cron-friendly all-tenants sweep + lazy dashboard sweep.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Avg, Count, Max, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant
from apps.tenants.services import record_audit
from apps.contracts.models import Contract
from apps.invoicing.models import SupplierInvoice, SupplierInvoiceLine
from apps.purchase_orders.models import PurchaseOrder, PurchaseOrderLine

from .models import (
    ACTUAL_INVOICE_STATUSES,
    BASIS_CHOICES,
    COMMITTED_PO_EXCLUDE_STATUSES,
    DIMENSION_CHOICES,
    MAVERICK_REASON_CHOICES,
    MEASURE_CHOICES,
    PREFERRED_SEGMENT_TOKENS,
    SOURCE_TYPE_CHOICES,
    SpendRecord,
)

# Roles allowed to manage (build/run/delete reports, trigger a manual sync). Mirrors the other
# procurement modules — there is no dedicated analyst role in the project yet.
MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
# Viewing (dashboards / reports / exports) additionally allows approvers.
VIEW_ROLES = MANAGE_ROLES + ('approver',)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _has_role(user, roles):
    """True if the user holds any of ``roles`` (string slugs)."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'is_tenant_admin', False):
        return True
    role = getattr(user, 'role', None)
    if isinstance(role, str):
        role_slug = role
    else:
        role_slug = getattr(role, 'slug', None) or getattr(role, 'name', None)
    return role_slug in roles


def can_manage_spend_analytics(user):
    """May build/run/delete reports and trigger a manual fact-table sync."""
    return _has_role(user, MANAGE_ROLES)


def can_view_spend_analytics(user):
    """May view dashboards / reports / analytics / exports (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Maverick helpers
# ---------------------------------------------------------------------------
def _preferred_segment(segment):
    """True if a VendorSegment is "preferred" (code OR name in PREFERRED_SEGMENT_TOKENS)."""
    if not segment:
        return False
    code = (segment.code or '').strip().lower()
    name = (segment.name or '').strip().lower()
    return code in PREFERRED_SEGMENT_TOKENS or name in PREFERRED_SEGMENT_TOKENS


def _build_contract_map(tenant):
    """Preload active contracts once: ``{vendor_id: [(start_date, end_date), ...]}``.

    Lets :func:`_is_off_contract` be a pure dict + date check during sync (no per-row query).
    """
    cmap = {}
    rows = (
        Contract.all_objects
        .filter(tenant=tenant, status='active')
        .values_list('vendor_id', 'start_date', 'end_date')
    )
    for vendor_id, start, end in rows:
        if vendor_id is None:
            continue
        cmap.setdefault(vendor_id, []).append((start, end))
    return cmap


def _is_off_contract(vendor_id, spend_date, contract_map):
    """True if the vendor has NO active contract covering ``spend_date``.

    A null contract start/end is treated as an open bound. With no vendor or no spend date we
    cannot match a contract, so it counts as off-contract. This is a date+vendor heuristic — there
    is no Contract↔PO/Invoice FK, so it cannot prove THIS purchase was made under the contract.
    """
    if not vendor_id or spend_date is None:
        return True
    for start, end in contract_map.get(vendor_id, ()):
        if (start is None or start <= spend_date) and (end is None or spend_date <= end):
            return False
    return True


# ---------------------------------------------------------------------------
# The sync engine (idempotent upsert + prune)
# ---------------------------------------------------------------------------
def sync_spend_facts(tenant, *, full=False):
    """Materialize/refresh SpendRecords for one tenant from invoices + POs. Idempotent.

    Returns ``{'created', 'updated', 'pruned', 'total'}``. ``full`` is accepted for CLI symmetry;
    the sync is *always* a full reconcile (every qualifying row is re-written and orphans pruned).
    """
    now = timezone.now()
    contract_map = _build_contract_map(tenant)
    created = updated = 0
    seen = {'invoice_line': set(), 'po_line': set()}

    with transaction.atomic():
        # 1. ACTUAL spend — approved/paid supplier invoice lines.
        inv_lines = (
            SupplierInvoiceLine.all_objects
            .filter(tenant=tenant, supplier_invoice__status__in=ACTUAL_INVOICE_STATUSES)
            .select_related(
                'supplier_invoice', 'supplier_invoice__vendor',
                'supplier_invoice__vendor__category', 'supplier_invoice__vendor__segment',
                'account_code',
            )
        )
        for line in inv_lines:
            inv = line.supplier_invoice
            vendor = inv.vendor
            spend_date = (
                inv.invoice_date or inv.received_date
                or (inv.created_at.date() if inv.created_at else None)
            )
            amount = line.line_total or Decimal('0.00')
            off_pref = not _preferred_segment(getattr(vendor, 'segment', None))
            off_con = _is_off_contract(getattr(vendor, 'id', None), spend_date, contract_map)
            off_po = line.purchase_order_line_id is None
            _, was_created = SpendRecord.all_objects.update_or_create(
                tenant=tenant, source_type='invoice_line', source_id=line.id,
                defaults={
                    'basis': 'actual',
                    'spend_date': spend_date,
                    'vendor': vendor,
                    'vendor_category': getattr(vendor, 'category', None),
                    'vendor_segment': getattr(vendor, 'segment', None),
                    'account_code': line.account_code,
                    'currency': inv.currency or 'USD',
                    'amount': amount,
                    'tax_amount': line.tax_amount or Decimal('0.00'),
                    'net_amount': amount,
                    'off_preferred_supplier': off_pref,
                    'off_contract': off_con,
                    'off_po': off_po,
                    'is_maverick': bool(off_pref or off_con or off_po),
                    'source_ref': f'{inv.invoice_number}#L{line.line_no}',
                    'vendor_name': getattr(vendor, 'legal_name', '') or '',
                    'description': (line.description or '')[:255],
                    'source_status': inv.status,
                    'synced_at': now,
                },
            )
            seen['invoice_line'].add(line.id)
            if was_created:
                created += 1
            else:
                updated += 1

        # 2. COMMITTED spend — non-cancelled PO lines.
        po_lines = (
            PurchaseOrderLine.all_objects
            .filter(tenant=tenant)
            .exclude(purchase_order__status__in=COMMITTED_PO_EXCLUDE_STATUSES)
            .select_related(
                'purchase_order', 'purchase_order__vendor',
                'purchase_order__vendor__category', 'purchase_order__vendor__segment',
                'purchase_order__category', 'account_code',
            )
        )
        for line in po_lines:
            po = line.purchase_order
            vendor = po.vendor
            spend_date = po.order_date or (po.created_at.date() if po.created_at else None)
            amount = line.line_total or Decimal('0.00')
            off_pref = not _preferred_segment(getattr(vendor, 'segment', None))
            off_con = _is_off_contract(getattr(vendor, 'id', None), spend_date, contract_map)
            category = po.category or getattr(vendor, 'category', None)
            _, was_created = SpendRecord.all_objects.update_or_create(
                tenant=tenant, source_type='po_line', source_id=line.id,
                defaults={
                    'basis': 'committed',
                    'spend_date': spend_date,
                    'vendor': vendor,
                    'vendor_category': category,
                    'vendor_segment': getattr(vendor, 'segment', None),
                    'account_code': line.account_code,
                    'currency': po.currency or 'USD',
                    'amount': amount,
                    'tax_amount': Decimal('0.00'),
                    'net_amount': amount,
                    'off_preferred_supplier': off_pref,
                    'off_contract': off_con,
                    'off_po': False,  # a PO line is, by definition, on a PO
                    'is_maverick': bool(off_pref or off_con),
                    'source_ref': f'{po.po_number}#L{line.line_no}',
                    'vendor_name': getattr(vendor, 'legal_name', '') or '',
                    'description': (line.description or '')[:255],
                    'source_status': po.status,
                    'synced_at': now,
                },
            )
            seen['po_line'].add(line.id)
            if was_created:
                created += 1
            else:
                updated += 1

        # 3. Prune rows whose source no longer qualifies (status change / deletion).
        pruned = (
            SpendRecord.all_objects
            .filter(tenant=tenant, source_type='invoice_line')
            .exclude(source_id__in=seen['invoice_line']).delete()[0]
        )
        pruned += (
            SpendRecord.all_objects
            .filter(tenant=tenant, source_type='po_line')
            .exclude(source_id__in=seen['po_line']).delete()[0]
        )

    total = SpendRecord.all_objects.filter(tenant=tenant).count()
    record_audit(
        tenant, None, 'spend_analytics.synced',
        target_type='SpendRecord',
        message=f'sync +{created} ~{updated} -{pruned} (={total})',
    )
    return {'created': created, 'updated': updated, 'pruned': pruned, 'total': total}


def sync_all_tenants(*, full=False):
    """Resync every tenant (cron entry point). Returns ``{'totals', 'results'}``."""
    results = []
    totals = {'created': 0, 'updated': 0, 'pruned': 0, 'total': 0}
    for t in Tenant.objects.all():
        set_current_tenant(t)
        counts = sync_spend_facts(t, full=full)
        results.append((t, counts))
        for k in totals:
            totals[k] += counts.get(k, 0)
    set_current_tenant(None)
    return {'totals': totals, 'results': results}


# ---------------------------------------------------------------------------
# Lazy sweep (cheap watermark compare — not a full resync per dashboard hit)
# ---------------------------------------------------------------------------
def _spend_is_stale(tenant):
    """True if a qualifying source doc changed since the last sync."""
    last = SpendRecord.all_objects.filter(tenant=tenant).aggregate(m=Max('synced_at'))['m']
    if last is None:
        return True  # never synced
    inv_max = (
        SupplierInvoice.all_objects
        .filter(tenant=tenant, status__in=ACTUAL_INVOICE_STATUSES)
        .aggregate(m=Max('updated_at'))['m']
    )
    po_max = (
        PurchaseOrder.all_objects
        .filter(tenant=tenant).exclude(status__in=COMMITTED_PO_EXCLUDE_STATUSES)
        .aggregate(m=Max('updated_at'))['m']
    )
    candidates = [d for d in (inv_max, po_max) if d]
    return bool(candidates and max(candidates) > last)


def lazy_sync(tenant):
    """Dashboard sweep — resyncs only when stale. Returns the sync counts or None."""
    if _spend_is_stale(tenant):
        return sync_spend_facts(tenant)
    return None


# ---------------------------------------------------------------------------
# Aggregation / metrics
# ---------------------------------------------------------------------------
def _base_qs(tenant, *, basis=None, start=None, end=None, maverick_only=False, **dim_filters):
    """SpendRecord queryset for ``tenant`` filtered by basis + date window + dimension filters."""
    qs = SpendRecord.objects.filter(tenant=tenant)
    if basis:
        qs = qs.filter(basis=basis)
    if start:
        qs = qs.filter(spend_date__gte=start)
    if end:
        qs = qs.filter(spend_date__lte=end)
    if maverick_only:
        qs = qs.filter(is_maverick=True)
    clean = {k: v for k, v in dim_filters.items() if v}
    if clean:
        qs = qs.filter(**clean)
    return qs


def _num(value):
    """Decimal/None -> float rounded to 2dp (for json_script chart series)."""
    return round(float(value or 0), 2)


def _group_top(qs, field, none_label, *, limit=12):
    """Top-N group-by-Sum(amount): returns {'labels', 'values', 'items'}."""
    rows = (
        qs.values(field)
        .annotate(total=Sum('amount'), n=Count('id'))
        .order_by('-total')[:limit]
    )
    labels, values, items = [], [], []
    for r in rows:
        label = r[field] or none_label
        amt = _num(r['total'])
        labels.append(label)
        values.append(amt)
        items.append({'label': label, 'total': amt, 'count': r['n']})
    return {'labels': labels, 'values': values, 'items': items}


def _group_month(qs):
    """Monthly Sum(amount) time-series ordered ascending."""
    rows = (
        qs.exclude(spend_date__isnull=True)
        .annotate(m=TruncMonth('spend_date')).values('m')
        .annotate(total=Sum('amount')).order_by('m')
    )
    labels, values, items = [], [], []
    for r in rows:
        m = r['m']
        label = m.strftime('%Y-%m') if m else ''
        amt = _num(r['total'])
        labels.append(label)
        values.append(amt)
        items.append({'label': label, 'total': amt})
    return {'labels': labels, 'values': values, 'items': items}


def tenant_spend_metrics(tenant, *, basis='actual', start=None, end=None):
    """KPI cards + by_category/by_vendor/by_cost_center/by_month series for the dashboard."""
    qs = _base_qs(tenant, basis=basis, start=start, end=end)
    total_spend = qs.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    record_count = qs.count()
    vendor_count = qs.exclude(vendor__isnull=True).values('vendor').distinct().count()
    avg_record = (total_spend / record_count) if record_count else Decimal('0.00')
    maverick_spend = qs.filter(is_maverick=True).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    maverick_pct = int(round(maverick_spend / total_spend * 100)) if total_spend > 0 else 0
    currencies = sorted(c for c in qs.values_list('currency', flat=True).distinct() if c)

    return {
        'basis': basis,
        'total_spend': total_spend.quantize(Decimal('0.01')),
        'record_count': record_count,
        'vendor_count': vendor_count,
        'avg_record': avg_record.quantize(Decimal('0.01')),
        'maverick_spend': maverick_spend.quantize(Decimal('0.01')),
        'maverick_pct': maverick_pct,
        'currencies': currencies,
        'by_category': _group_top(qs, 'vendor_category__name', 'Uncategorized'),
        'by_vendor': _group_top(qs, 'vendor_name', 'Unknown'),
        'by_cost_center': _group_top(qs, 'account_code__code', 'Unassigned'),
        'by_month': _group_month(qs),
    }


def category_spend(tenant, *, basis='actual', start=None, end=None):
    """Category table: total, % of total, count, avg. Plus chart labels/values."""
    qs = _base_qs(tenant, basis=basis, start=start, end=end)
    total = qs.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    grouped = (
        qs.values('vendor_category', 'vendor_category__name')
        .annotate(spend=Sum('amount'), n=Count('id'))
        .order_by('-spend')
    )
    rows, labels, values = [], [], []
    for r in grouped:
        amt = r['spend'] or Decimal('0.00')
        pct = float(amt / total * 100) if total > 0 else 0.0
        avg = (amt / r['n']) if r['n'] else Decimal('0.00')
        label = r['vendor_category__name'] or 'Uncategorized'
        rows.append({
            'category_id': r['vendor_category'] or 0,
            'label': label,
            'total': amt.quantize(Decimal('0.01')),
            'pct': round(pct, 1),
            'count': r['n'],
            'avg': avg.quantize(Decimal('0.01')),
        })
        labels.append(label)
        values.append(_num(amt))
    return {'rows': rows, 'total': total.quantize(Decimal('0.01')),
            'labels': labels, 'values': values, 'basis': basis}


def category_detail(tenant, category_id, *, basis='actual', start=None, end=None):
    """Drill-down for one category (``category_id == 0`` = the Uncategorized bucket).

    Returns vendors-within-category totals + the underlying records queryset (the view paginates).
    """
    qs = _base_qs(tenant, basis=basis, start=start, end=end)
    if not category_id:
        qs = qs.filter(vendor_category__isnull=True)
    else:
        qs = qs.filter(vendor_category_id=category_id)
    total = qs.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    by_vendor = [
        {'vendor_id': r['vendor'] or 0, 'label': r['vendor_name'] or 'Unknown',
         'total': (r['total'] or Decimal('0.00')).quantize(Decimal('0.01')), 'count': r['n']}
        for r in (
            qs.values('vendor', 'vendor_name')
            .annotate(total=Sum('amount'), n=Count('id')).order_by('-total')
        )
    ]
    records = qs.select_related('vendor', 'account_code')
    return {'total': total.quantize(Decimal('0.01')), 'by_vendor': by_vendor, 'records': records}


def maverick_metrics(tenant, *, basis='actual', start=None, end=None):
    """Maverick KPIs + breakdown by reason / vendor / category.

    ``by_reason`` uses three independent filtered aggregates (the flags overlap), so its counts can
    exceed the maverick record count — the template labels this.
    """
    base = _base_qs(tenant, basis=basis, start=start, end=end)
    total_spend = base.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    mav = base.filter(is_maverick=True)
    maverick_spend = mav.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    maverick_count = mav.count()
    maverick_pct = int(round(maverick_spend / total_spend * 100)) if total_spend > 0 else 0

    by_reason, labels, values = [], [], []
    for flag, label in MAVERICK_REASON_CHOICES:
        agg = base.filter(**{flag: True}).aggregate(s=Sum('amount'), n=Count('id'))
        amt = agg['s'] or Decimal('0.00')
        by_reason.append({'reason': flag, 'label': label,
                          'total': amt.quantize(Decimal('0.01')), 'count': agg['n'] or 0})
        labels.append(label)
        values.append(_num(amt))

    return {
        'basis': basis,
        'total_spend': total_spend.quantize(Decimal('0.01')),
        'maverick_spend': maverick_spend.quantize(Decimal('0.01')),
        'maverick_pct': maverick_pct,
        'maverick_count': maverick_count,
        'by_reason': by_reason,
        'labels': labels,
        'values': values,
        'by_vendor': _group_top(mav, 'vendor_name', 'Unknown')['items'],
        'by_category': _group_top(mav, 'vendor_category__name', 'Uncategorized')['items'],
    }


# ---------------------------------------------------------------------------
# Report runner (mirror portal.generate_report shape)
# ---------------------------------------------------------------------------
_DIMENSION_FIELDS = {
    'vendor': 'vendor_name',
    'vendor_category': 'vendor_category__name',
    'account_code': 'account_code__code',
    'vendor_segment': 'vendor_segment__name',
    'source_type': 'source_type',
}
_NONE_LABELS = {'account_code__code': 'Unassigned', 'vendor_category__name': 'Uncategorized'}


def _measure_agg(measure):
    if measure == 'record_count':
        return Count('id')
    if measure == 'net_sum':
        return Sum('net_amount')
    if measure == 'amount_avg':
        return Avg('amount')
    return Sum('amount')  # amount_sum (default)


def run_spend_report(report):
    """Compute a SpendReport into a chart-ready payload.

    Returns ``{'kind', 'labels', 'values', 'rows', 'summary', 'measure', 'measure_label',
    'dimension_label'}``. ``last_run_at`` is stamped by the view (mirrors portal.ReportRunView).
    """
    qs = _base_qs(
        report.tenant, basis=report.basis, start=report.date_from, end=report.date_to,
        maverick_only=report.maverick_only,
        vendor_id=report.vendor_id, vendor_category_id=report.vendor_category_id,
        vendor_segment_id=report.vendor_segment_id, account_code_id=report.account_code_id,
        source_type=report.source_type,
    )
    agg = _measure_agg(report.measure)
    labels, values, rows = [], [], []

    if report.dimension == 'month':
        grouped = (
            qs.exclude(spend_date__isnull=True)
            .annotate(m=TruncMonth('spend_date')).values('m')
            .annotate(value=agg).order_by('m')
        )
        for r in grouped:
            m = r['m']
            label = m.strftime('%Y-%m') if m else ''
            val = _num(r['value'])
            labels.append(label)
            values.append(val)
            rows.append({'label': label, 'value': val})
    else:
        field = _DIMENSION_FIELDS.get(report.dimension, 'vendor_name')
        none_label = _NONE_LABELS.get(field, 'Unknown')
        src_map = dict(SOURCE_TYPE_CHOICES)
        grouped = qs.values(field).annotate(value=agg).order_by('-value')
        for r in grouped:
            raw = r[field]
            if report.dimension == 'source_type':
                label = src_map.get(raw, raw or 'Unknown')
            else:
                label = raw or none_label
            val = _num(r['value'])
            labels.append(label)
            values.append(val)
            rows.append({'label': label, 'value': val})

    dim_label = dict(DIMENSION_CHOICES).get(report.dimension, report.dimension)
    meas_label = dict(MEASURE_CHOICES).get(report.measure, report.measure)
    summary = {meas_label: round(sum(values), 2), dim_label: len(labels)}
    return {
        'kind': report.chart_type,
        'labels': labels,
        'values': values,
        'rows': rows,
        'summary': summary,
        'measure': report.measure,
        'measure_label': meas_label,
        'dimension_label': dim_label,
    }


# ---------------------------------------------------------------------------
# Export rows (consumed by exports.csv_response / xlsx_response)
# ---------------------------------------------------------------------------
EXPORT_HEADER = [
    'Source ref', 'Source type', 'Basis', 'Spend date', 'Vendor', 'Category', 'Cost center',
    'Segment', 'Currency', 'Amount', 'Tax', 'Net', 'Maverick', 'Off preferred', 'Off contract',
    'Non-PO', 'Description',
]


def spend_rows_for_export(tenant, *, basis=None, start=None, end=None, maverick_only=False,
                          **dim_filters):
    """Return ``(header, rows)`` for raw, filtered SpendRecords (CSV/XLSX export)."""
    qs = _base_qs(tenant, basis=basis, start=start, end=end, maverick_only=maverick_only,
                  **dim_filters).select_related('vendor_category', 'account_code', 'vendor_segment')
    src_map = dict(SOURCE_TYPE_CHOICES)
    basis_map = dict(BASIS_CHOICES)
    rows = []
    for r in qs.iterator():
        rows.append([
            r.source_ref,
            src_map.get(r.source_type, r.source_type),
            basis_map.get(r.basis, r.basis),
            r.spend_date.isoformat() if r.spend_date else '',
            r.vendor_name,
            r.vendor_category.name if r.vendor_category else '',
            r.account_code.code if r.account_code else '',
            r.vendor_segment.name if r.vendor_segment else '',
            r.currency,
            str(r.amount),
            str(r.tax_amount),
            str(r.net_amount),
            'Yes' if r.is_maverick else 'No',
            'Yes' if r.off_preferred_supplier else 'No',
            'Yes' if r.off_contract else 'No',
            'Yes' if r.off_po else 'No',
            r.description,
        ])
    return EXPORT_HEADER, rows
