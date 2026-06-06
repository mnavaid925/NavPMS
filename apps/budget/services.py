"""Module 16 service layer: Budget & Cost Management.

Two halves:

* **Compute-on-read consumption** — :func:`allocation_consumption` derives ``actual`` (approved/paid
  invoice lines), ``committed`` (open PO lines) and ``reserved`` (open requisition lines) for an
  allocation directly from the transactional tables, scoped by ``account_code`` + the budget
  period's date window. Nothing is stored, so a status change on a source document is reflected on
  the next read (no ledger, no reversal hooks). Everything else (budget rollups, the dashboard
  metrics, the variance report, the forecast, the exports) builds on this one function.
* **The availability gate** — :func:`check_requisition_budget` is called from
  ``requisitions.submit_requisition``; it groups the requisition's lines by cost centre, compares
  the requested amount against the available balance of the governing active budget, and either
  warns (default) or blocks (``BUDGET_ENFORCEMENT='block'``), recording a :class:`BudgetCheck` row.

Conventions mirrored from Modules 11/15: ``MANAGE_ROLES``/``VIEW_ROLES`` + ``_has_role`` permission
helpers, ``record_audit`` from :mod:`apps.tenants.services`, gap-free ``BUD-<SLUG>-NNNNN`` numbering
and ``@transaction.atomic`` write paths.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant
from apps.tenants.services import record_audit

from .models import (
    ACTUAL_INVOICE_STATUSES,
    COMMITTED_PO_STATUSES,
    RESERVED_REQUISITION_STATUSES,
    Budget,
    BudgetAllocation,
    BudgetCheck,
    BudgetStatusEvent,
)

ZERO = Decimal('0.00')

# Roles allowed to manage budgets (create/edit/activate/close, allocate, run alerts). Mirrors the
# other procurement modules — there is no dedicated finance role in the project yet.
MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
# Viewing (dashboards / variance / forecast / exports) additionally allows approvers.
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
    role_slug = role if isinstance(role, str) else (
        getattr(role, 'slug', None) or getattr(role, 'name', None))
    return role_slug in roles


def can_manage_budget(user):
    """May create/edit/activate/close budgets, allocate, and trigger alerts."""
    return _has_role(user, MANAGE_ROLES)


def can_view_budget(user):
    """May view dashboards / budgets / variance / forecast / exports (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Numbering + lifecycle
# ---------------------------------------------------------------------------
def next_budget_number(tenant) -> str:
    """Generate the next gap-free ``BUD-<SLUG>-NNNNN`` number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = Budget.all_objects.filter(tenant=tenant).count() + 1
    number = f'BUD-{slug}-{count:05d}'
    while Budget.all_objects.filter(tenant=tenant, budget_number=number).exists():
        count += 1
        number = f'BUD-{slug}-{count:05d}'
    return number


def record_status_event(budget, from_status, to_status, user, note=''):
    """Append an immutable entry to a budget's lifecycle timeline."""
    return BudgetStatusEvent.all_objects.create(
        tenant=budget.tenant, budget=budget,
        from_status=from_status, to_status=to_status, actor=user, note=note,
    )


def recompute_total(budget):
    """Refresh ``Budget.total_allocated`` from its allocation lines."""
    total = budget.allocations.aggregate(s=Sum('allocated_amount'))['s'] or ZERO
    budget.total_allocated = total
    budget.save(update_fields=['total_allocated', 'updated_at'])
    return total


@transaction.atomic
def activate_budget(budget, user, *, request=None):
    """Draft → active. Requires at least one allocation line."""
    if budget.status != 'draft':
        raise ValidationError('Only a draft budget can be activated.')
    if not budget.allocations.exists():
        raise ValidationError('Add at least one allocation before activating the budget.')
    recompute_total(budget)
    from_status = budget.status
    budget.status = 'active'
    budget.activated_at = timezone.now()
    budget.over_budget_alerted_at = None
    budget.save(update_fields=['status', 'activated_at', 'over_budget_alerted_at', 'updated_at'])
    record_status_event(budget, from_status, 'active', user, note='Activated')
    record_audit(
        budget.tenant, user, 'budget.activated', target_type='Budget', target_id=budget.id,
        message=f'Budget {budget.budget_number} activated', request=request,
    )
    return budget


@transaction.atomic
def close_budget(budget, user, *, note='', request=None):
    """Active → closed."""
    if budget.status == 'closed':
        raise ValidationError('Budget is already closed.')
    from_status = budget.status
    budget.status = 'closed'
    budget.closed_at = timezone.now()
    budget.save(update_fields=['status', 'closed_at', 'updated_at'])
    record_status_event(budget, from_status, 'closed', user, note=note or 'Closed')
    record_audit(
        budget.tenant, user, 'budget.closed', target_type='Budget', target_id=budget.id,
        message=f'Budget {budget.budget_number} closed', request=request,
    )
    return budget


def set_period_status(period, status, user, *, request=None):
    """Move a period through draft → active → locked → closed (audited)."""
    valid = {s for s, _ in period.STATUS_CHOICES}
    if status not in valid:
        raise ValidationError('Invalid period status.')
    period.status = status
    period.save(update_fields=['status', 'updated_at'])
    record_audit(
        period.tenant, user, 'budget.period_status', target_type='BudgetPeriod',
        target_id=period.id, message=f'Period {period.name} → {status}', request=request,
    )
    return period


# ---------------------------------------------------------------------------
# Compute-on-read consumption (the core)
# ---------------------------------------------------------------------------
def _in_period(qs, field, start, end):
    """Filter ``qs`` to rows whose ``field`` date is inside [start, end].

    A null date is *kept* (treated as in-period) so consumption is never silently understated by a
    source document that happens to have no date set — conservative for an availability gate.
    """
    if not start and not end:
        return qs
    cond = Q(**{f'{field}__isnull': True})
    rng = Q()
    if start:
        rng &= Q(**{f'{field}__gte': start})
    if end:
        rng &= Q(**{f'{field}__lte': end})
    return qs.filter(cond | rng)


def _actual_for(tenant, account_code_id, start, end, vendor_category_id=None):
    """Σ approved/paid supplier-invoice line totals for a cost centre in-period."""
    from apps.invoicing.models import SupplierInvoiceLine
    qs = SupplierInvoiceLine.all_objects.filter(
        tenant=tenant, account_code_id=account_code_id,
        supplier_invoice__status__in=ACTUAL_INVOICE_STATUSES,
    )
    qs = _in_period(qs, 'supplier_invoice__invoice_date', start, end)
    if vendor_category_id:
        qs = qs.filter(supplier_invoice__vendor__category_id=vendor_category_id)
    return qs.aggregate(s=Sum('line_total'))['s'] or ZERO


def _committed_for(tenant, account_code_id, start, end, vendor_category_id=None):
    """Σ open-PO (issued/acknowledged/partially_received) line totals for a cost centre in-period."""
    from apps.purchase_orders.models import PurchaseOrderLine
    qs = PurchaseOrderLine.all_objects.filter(
        tenant=tenant, account_code_id=account_code_id,
        purchase_order__status__in=COMMITTED_PO_STATUSES,
    )
    qs = _in_period(qs, 'purchase_order__order_date', start, end)
    if vendor_category_id:
        qs = qs.filter(purchase_order__vendor__category_id=vendor_category_id)
    return qs.aggregate(s=Sum('line_total'))['s'] or ZERO


def _reserved_for(tenant, account_code_id, start, end, *, exclude_requisition_id=None):
    """Σ open-requisition (submitted/approved) line totals for a cost centre in-period.

    The soft pre-commitment — a requisition that has not yet become a PO. Requisitions are not
    vendor-bound, so the optional vendor-category narrowing does not apply here.
    """
    from apps.requisitions.models import RequisitionLine
    qs = RequisitionLine.all_objects.filter(
        tenant=tenant, account_code_id=account_code_id,
        requisition__status__in=RESERVED_REQUISITION_STATUSES,
    )
    if exclude_requisition_id:
        qs = qs.exclude(requisition_id=exclude_requisition_id)
    qs = _in_period(qs, 'requisition__required_date', start, end)
    return qs.aggregate(s=Sum('line_total'))['s'] or ZERO


def _f(value):
    """Decimal/None -> float rounded to 2dp (for json_script chart series)."""
    return round(float(value or 0), 2)


def allocation_consumption(allocation, *, exclude_requisition_id=None):
    """Compute the live financials for one allocation.

    Returns ``{allocated, actual, committed, reserved, consumed, available, variance, variance_pct,
    utilization_pct, over_budget}``. ``consumed = actual + committed`` (the encumbered total);
    ``available = allocated − actual − committed − reserved``.
    """
    budget = allocation.budget
    period = budget.period
    tenant_id = allocation.tenant_id
    start = period.start_date if period else None
    end = period.end_date if period else None
    acc_id = allocation.account_code_id
    vc_id = allocation.vendor_category_id

    allocated = allocation.allocated_amount or ZERO
    actual = _actual_for(tenant_id, acc_id, start, end, vc_id)
    committed = _committed_for(tenant_id, acc_id, start, end, vc_id)
    reserved = _reserved_for(
        tenant_id, acc_id, start, end, exclude_requisition_id=exclude_requisition_id)

    consumed = actual + committed
    available = allocated - actual - committed - reserved
    utilization_pct = round(float(consumed / allocated * 100), 1) if allocated > 0 else 0.0
    variance = allocated - actual
    variance_pct = round(float(variance / allocated * 100), 1) if allocated > 0 else 0.0

    return {
        'allocation': allocation,
        'allocated': allocated.quantize(ZERO),
        'actual': actual.quantize(ZERO),
        'committed': committed.quantize(ZERO),
        'reserved': reserved.quantize(ZERO),
        'consumed': consumed.quantize(ZERO),
        'available': available.quantize(ZERO),
        'variance': variance.quantize(ZERO),
        'variance_pct': variance_pct,
        'utilization_pct': utilization_pct,
        'over_budget': available < 0,
    }


def budget_consumption(budget):
    """Roll allocation_consumption across a budget. Returns totals + per-allocation rows."""
    rows = [
        allocation_consumption(a)
        for a in budget.allocations.select_related('account_code', 'vendor_category')
    ]
    totals = {k: ZERO for k in ('allocated', 'actual', 'committed', 'reserved', 'consumed',
                                'available')}
    for r in rows:
        for k in totals:
            totals[k] += r[k]
    allocated = totals['allocated']
    totals['utilization_pct'] = (
        round(float(totals['consumed'] / allocated * 100), 1) if allocated > 0 else 0.0)
    totals['over_count'] = sum(1 for r in rows if r['over_budget'])
    return {'rows': rows, 'totals': totals}


# ---------------------------------------------------------------------------
# Dashboard metrics / variance / forecast
# ---------------------------------------------------------------------------
def _active_budgets(tenant, period=None):
    qs = Budget.all_objects.filter(tenant=tenant, status='active').select_related('period')
    if period is not None:
        qs = qs.filter(period=period)
    return qs


def tenant_budget_metrics(tenant, *, period=None):
    """KPI cards + by-cost-centre series for the dashboard (allocated / actual / committed)."""
    allocs = (
        BudgetAllocation.all_objects
        .filter(tenant=tenant, budget__in=_active_budgets(tenant, period))
        .select_related('account_code', 'budget', 'budget__period')
    )
    rows = [allocation_consumption(a) for a in allocs]

    totals = {k: ZERO for k in ('allocated', 'actual', 'committed', 'reserved', 'available')}
    for r in rows:
        for k in totals:
            totals[k] += r[k]

    # Aggregate by cost centre (an account code may appear in more than one active budget).
    by_cc = defaultdict(lambda: {'allocated': ZERO, 'actual': ZERO, 'committed': ZERO})
    for a, r in zip(allocs, rows):
        code = a.account_code.code if a.account_code else 'Unassigned'
        by_cc[code]['allocated'] += r['allocated']
        by_cc[code]['actual'] += r['actual']
        by_cc[code]['committed'] += r['committed']
    cc_items = sorted(by_cc.items(), key=lambda kv: kv[1]['allocated'], reverse=True)[:12]

    allocated = totals['allocated']
    consumed = totals['actual'] + totals['committed']
    return {
        'budget_count': _active_budgets(tenant, period).count(),
        'allocated': allocated.quantize(ZERO),
        'actual': totals['actual'].quantize(ZERO),
        'committed': totals['committed'].quantize(ZERO),
        'reserved': totals['reserved'].quantize(ZERO),
        'available': totals['available'].quantize(ZERO),
        'utilization_pct': round(float(consumed / allocated * 100), 1) if allocated > 0 else 0.0,
        'over_count': sum(1 for r in rows if r['over_budget']),
        'cc_labels': [c for c, _ in cc_items],
        'cc_allocated': [_f(v['allocated']) for _, v in cc_items],
        'cc_actual': [_f(v['actual']) for _, v in cc_items],
        'cc_committed': [_f(v['committed']) for _, v in cc_items],
    }


def variance_report(tenant, *, period=None):
    """Per-allocation variance rows (allocated vs actual vs committed) with tolerance flags."""
    tol = float(getattr(settings, 'BUDGET_VARIANCE_TOLERANCE_PCT', 10))
    allocs = (
        BudgetAllocation.all_objects
        .filter(tenant=tenant, budget__in=_active_budgets(tenant, period))
        .select_related('account_code', 'budget', 'budget__period')
    )
    warn_at = 100 - tol  # e.g. tolerance 10% -> warn once utilization hits 90%
    rows = []
    for a in allocs:
        c = allocation_consumption(a)
        over_pct = (
            round(float((c['consumed'] - c['allocated']) / c['allocated'] * 100), 1)
            if c['allocated'] > 0 else 0.0)
        if c['available'] < 0:
            flag = 'over'
        elif c['utilization_pct'] >= warn_at:
            flag = 'warning'
        else:
            flag = 'ok'
        rows.append({
            'budget': a.budget, 'account_code': a.account_code, 'cost_center':
                a.account_code.code if a.account_code else 'Unassigned',
            **c, 'over_pct': over_pct, 'flag': flag,
        })
    rows.sort(key=lambda r: r['available'])
    return {'rows': rows, 'tolerance_pct': tol}


def forecast(budget, *, as_of=None):
    """Linear run-rate projection to period end for each allocation in a budget.

    ``projected_actual = actual / fraction_of_period_elapsed`` (clamped); the projected period-end
    position adds the open commitments (they convert to actuals). Honest "history + open POs" — no
    statistical model on this stack.
    """
    today = as_of or timezone.now().date()
    period = budget.period
    start, end = period.start_date, period.end_date
    total_days = max((end - start).days, 1)
    elapsed_days = min(max((today - start).days, 0), total_days)
    fraction = elapsed_days / total_days if total_days else 1.0

    rows = []
    t_alloc = t_proj = ZERO
    for a in budget.allocations.select_related('account_code'):
        c = allocation_consumption(a)
        if fraction > 0:
            run_rate_actual = (c['actual'] / Decimal(str(fraction))).quantize(ZERO)
        else:
            run_rate_actual = c['actual']
        # Projected period-end spend = greater of (run-rated actual, actual + open commitments).
        projected = max(run_rate_actual, c['actual'] + c['committed'])
        proj_variance = c['allocated'] - projected
        rows.append({
            'account_code': a.account_code,
            'cost_center': a.account_code.code if a.account_code else 'Unassigned',
            'allocated': c['allocated'], 'actual': c['actual'], 'committed': c['committed'],
            'projected': projected.quantize(ZERO),
            'projected_variance': proj_variance.quantize(ZERO),
            'will_overrun': projected > c['allocated'],
        })
        t_alloc += c['allocated']
        t_proj += projected
    return {
        'rows': rows,
        'as_of': today,
        'elapsed_pct': round(fraction * 100, 1),
        'total_allocated': t_alloc.quantize(ZERO),
        'total_projected': t_proj.quantize(ZERO),
        'total_projected_variance': (t_alloc - t_proj).quantize(ZERO),
    }


# ---------------------------------------------------------------------------
# 2. Budget Availability Check (the requisitions integration)
# ---------------------------------------------------------------------------
def _governing_allocation(tenant_id, account_code_id, ref_date):
    """The active-budget allocation governing a cost centre on ``ref_date`` (or None = unbudgeted)."""
    qs = (
        BudgetAllocation.all_objects
        .filter(
            tenant_id=tenant_id, account_code_id=account_code_id,
            budget__status='active', budget__period__status='active',
        )
        .select_related('budget', 'budget__period', 'account_code')
    )
    if ref_date:
        qs = qs.filter(
            budget__period__start_date__lte=ref_date, budget__period__end_date__gte=ref_date)
    # Prefer an allocation without a vendor-category narrowing (the general envelope).
    return qs.order_by('vendor_category_id', 'id').first()


def check_requisition_budget(requisition, user=None, *, request=None):
    """Real-time availability check fired when a requisition is submitted.

    Groups the requisition's lines by cost centre, and for each governing active budget compares the
    requested amount against the available balance (excluding this requisition's own reservation).
    Writes a :class:`BudgetCheck` per cost centre. In ``warn`` mode (default) an over-budget line is
    flagged + the budget owner is notified but the submission proceeds; in ``block`` mode a
    ``ValidationError`` is raised so the caller aborts the submit.

    Returns ``{'result', 'blocked', 'lines'}``. Never raises in ``warn`` mode.
    """
    tenant = requisition.tenant
    mode = getattr(settings, 'BUDGET_ENFORCEMENT', 'warn')
    block = mode == 'block'
    ref_date = requisition.required_date or timezone.now().date()

    grouped = defaultdict(lambda: ZERO)
    for ln in requisition.lines.all():
        if ln.account_code_id:
            grouped[ln.account_code_id] += (ln.line_total or ZERO)

    lines = []
    insufficient = []
    for acc_id, requested in grouped.items():
        alloc = _governing_allocation(tenant.id, acc_id, ref_date)
        if alloc is None:
            available = None
            result = 'pass'
            message = 'No active budget governs this cost centre.'
        else:
            cons = allocation_consumption(alloc, exclude_requisition_id=requisition.id)
            available = cons['available']
            if requested > available:
                result = 'block' if block else 'warn'
                message = (f'Requested {requested} exceeds available {available} on budget '
                           f'{alloc.budget.budget_number}.')
                insufficient.append((alloc, requested, available))
            else:
                result = 'pass'
                message = f'Within budget {alloc.budget.budget_number}.'

        BudgetCheck.all_objects.create(
            tenant=tenant, requisition=requisition,
            budget=alloc.budget if alloc else None, allocation=alloc, account_code_id=acc_id,
            requested_amount=requested, available_amount=(available or ZERO),
            result=result, enforcement_mode=mode, message=message[:255], checked_by=user,
        )
        lines.append({'account_code_id': acc_id, 'requested': requested,
                      'available': available, 'result': result, 'message': message})

    overall = 'pass'
    if insufficient:
        overall = 'block' if block else 'warn'
        record_audit(
            tenant, user, 'budget.check_exceeded',
            level='warning',
            target_type='Requisition', target_id=requisition.id,
            message=(f'Requisition {requisition.number} exceeds budget on '
                     f'{len(insufficient)} cost centre(s) [{mode}]'),
            request=request,
        )
        _notify_owners_over_budget(requisition, insufficient, user, blocked=block)
        if block:
            raise ValidationError(
                'Requisition exceeds the available budget on '
                f'{len(insufficient)} cost centre(s). Submission blocked.')

    return {'result': overall, 'blocked': block and bool(insufficient), 'lines': lines}


def _notify_owners_over_budget(requisition, insufficient, actor, *, blocked):
    """In-app portal Notification to each distinct budget owner of an over-budget submission."""
    from apps.portal.models import Notification
    seen = set()
    for alloc, requested, available in insufficient:
        owner = alloc.budget.owner
        if not owner or owner.id in seen:
            continue
        seen.add(owner.id)
        verb = 'blocked' if blocked else 'flagged'
        Notification.all_objects.create(
            tenant=requisition.tenant, user=owner, category='approval',
            priority='high',
            title=f'Budget {verb}: {requisition.number}',
            message=(f'Requisition {requisition.number} ({requisition.title}) {verb} against '
                     f'budget {alloc.budget.budget_number} — requested {requested}, '
                     f'available {available}.'),
        )


def latest_check_status(requisition):
    """The most recent over-budget BudgetCheck for a requisition (for the detail banner), or None."""
    return (
        BudgetCheck.all_objects
        .filter(tenant=requisition.tenant, requisition=requisition)
        .exclude(result='pass')
        .select_related('budget', 'account_code')
        .order_by('-created_at')
        .first()
    )


# ---------------------------------------------------------------------------
# Alerts (cron-friendly over-budget sweep)
# ---------------------------------------------------------------------------
def scan_budget_alerts(tenant=None, *, now=None):
    """Raise a one-time alert for each active budget that is over budget or past the warn
    utilization threshold. Idempotent via ``Budget.over_budget_alerted_at``.

    Returns the number of budgets newly alerted.
    """
    now = now or timezone.now()
    warn_pct = float(getattr(settings, 'BUDGET_WARN_UTILIZATION_PCT', 90))
    tenants = [tenant] if tenant is not None else list(Tenant.objects.all())
    alerted = 0
    for t in tenants:
        for budget in Budget.all_objects.filter(
                tenant=t, status='active', over_budget_alerted_at__isnull=True):
            data = budget_consumption(budget)
            totals = data['totals']
            if totals['over_count'] == 0 and totals['utilization_pct'] < warn_pct:
                continue
            budget.over_budget_alerted_at = now
            budget.save(update_fields=['over_budget_alerted_at', 'updated_at'])
            alerted += 1
            level = 'warning' if totals['over_count'] else 'info'
            record_audit(
                t, None, 'budget.alert', level=level,
                target_type='Budget', target_id=budget.id,
                message=(f'Budget {budget.budget_number}: {totals["over_count"]} cost centre(s) '
                         f'over budget, utilization {totals["utilization_pct"]}%'),
            )
            if budget.owner:
                from apps.portal.models import Notification
                Notification.all_objects.create(
                    tenant=t, user=budget.owner, category='deadline',
                    priority='high' if totals['over_count'] else 'normal',
                    title=f'Budget alert: {budget.budget_number}',
                    message=(f'{budget.name} is at {totals["utilization_pct"]}% utilization '
                             f'with {totals["over_count"]} cost centre(s) over budget.'),
                )
    return alerted


def scan_all_tenants():
    """Cron entry point — sweep every tenant. Returns total budgets alerted."""
    total = 0
    for t in Tenant.objects.all():
        set_current_tenant(t)
        total += scan_budget_alerts(t)
    set_current_tenant(None)
    return total


# ---------------------------------------------------------------------------
# Export rows (consumed by spend_analytics.exports.csv_response / xlsx_response)
# ---------------------------------------------------------------------------
VARIANCE_EXPORT_HEADER = [
    'Budget', 'Cost center', 'Allocated', 'Actual', 'Committed', 'Reserved', 'Available',
    'Variance', 'Utilization %', 'Status',
]


def variance_rows_for_export(tenant, *, period=None):
    """``(header, rows)`` for the variance report (CSV/XLSX)."""
    report = variance_report(tenant, period=period)
    rows = [
        [
            r['budget'].budget_number, r['cost_center'], str(r['allocated']), str(r['actual']),
            str(r['committed']), str(r['reserved']), str(r['available']), str(r['variance']),
            r['utilization_pct'], r['flag'],
        ]
        for r in report['rows']
    ]
    return VARIANCE_EXPORT_HEADER, rows


BUDGET_EXPORT_HEADER = [
    'Cost center', 'Account name', 'Allocated', 'Actual', 'Committed', 'Reserved', 'Available',
    'Utilization %',
]


def budget_rows_for_export(budget):
    """``(header, rows)`` for one budget's allocation consumption (CSV/XLSX)."""
    data = budget_consumption(budget)
    rows = []
    for r in data['rows']:
        a = r['allocation']
        rows.append([
            a.account_code.code if a.account_code else '',
            a.account_code.name if a.account_code else '',
            str(r['allocated']), str(r['actual']), str(r['committed']), str(r['reserved']),
            str(r['available']), r['utilization_pct'],
        ])
    return BUDGET_EXPORT_HEADER, rows
