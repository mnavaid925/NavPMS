"""Module 17 service layer: Supplier Performance & Evaluation.

Three halves:

* **The KPI engine** — :func:`compute_kpi_value` reads the authoritative transactional tables
  (goods receipts, purchase orders, RFx/sourcing invitations, supplier invoices, internal feedback)
  for one vendor over a date window and returns the raw metric; :func:`normalize_score` maps the raw
  value to a 0-100 score using the KPI's ``direction`` + ``target_value``.
* **Scorecard generation** — :func:`generate_scorecard` runs the engine once per active KPI and
  **persists** a :class:`ScorecardLine` snapshot, freezes the weighted ``overall_score`` + rating
  band, and (when final) denormalises the latest score onto the ``Vendor`` row — the same precedent
  as :func:`apps.vendors.services.apply_risk_assessment`.
* **Workflow** — 360° feedback request/submit, PIP lifecycle transitions (append-only timeline),
  trending/benchmarking read models, a cron-friendly period generator and an overdue-PIP sweep.

Conventions mirrored from Modules 15/16: ``MANAGE_ROLES``/``VIEW_ROLES`` + ``_has_role`` permission
helpers, ``record_audit`` from :mod:`apps.tenants.services`, gap-free ``SPC-<SLUG>-NNNNN`` /
``PIP-<SLUG>-NNNNN`` numbering and ``@transaction.atomic`` write paths.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant
from apps.portal.services import create_notification
from apps.tenants.services import record_audit
from apps.vendors.models import Vendor

from .models import (
    AUTO_KPI_TYPES,
    PIP_OPEN_STATUSES,
    UNDERPERFORMING_BANDS,
    ImprovementPlan,
    KpiDefinition,
    PerformanceFeedback,
    PIPStatusEvent,
    Scorecard,
    ScorecardLine,
    rating_band_from_score,
)

ZERO = Decimal('0.00')
Q2 = Decimal('0.01')

# Roles allowed to manage performance (define KPIs, generate scorecards, request feedback, run PIPs).
MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
# Viewing (dashboards / scorecards / trending / benchmarking / exports) additionally allows approvers.
VIEW_ROLES = MANAGE_ROLES + ('approver',)

# Source-document statuses that count toward auto KPIs (kept here so this module owns its own policy).
RECEIVED_GRN_STATUSES = ('received', 'under_inspection', 'inspected', 'posted', 'closed')
ACTUAL_INVOICE_STATUSES = ('approved', 'paid')

# Valid PIP status transitions + the timestamp each lands on.
PIP_TRANSITIONS = {
    'draft': ('open', 'cancelled'),
    'open': ('in_progress', 'completed', 'closed', 'cancelled'),
    'in_progress': ('completed', 'closed', 'cancelled'),
    'completed': ('closed',),
    'closed': (),
    'cancelled': (),
}
PIP_STATUS_TIMESTAMP = {
    'open': 'opened_at', 'completed': 'completed_at', 'closed': 'closed_at',
    'cancelled': 'cancelled_at',
}


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


def can_manage_supplier_performance(user):
    """May define KPIs, generate/finalize scorecards, request feedback and run PIPs."""
    return _has_role(user, MANAGE_ROLES)


def can_view_supplier_performance(user):
    """May view dashboards / scorecards / trending / benchmarking / exports (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Default KPIs
# ---------------------------------------------------------------------------
# The starter metric set every tenant gets. Weights sum to 100 across the five default KPIs.
DEFAULT_KPIS = [
    {'code': 'OTD', 'name': 'On-Time Delivery', 'kpi_type': 'on_time_delivery',
     'source': 'auto', 'direction': 'higher_better', 'weight': Decimal('30.00'),
     'target_value': Decimal('95.00'), 'unit': '%', 'display_order': 1,
     'description': 'Percentage of goods receipts on or before the PO promised date.'},
    {'code': 'DEF', 'name': 'Defect / Quality Rate', 'kpi_type': 'defect_rate',
     'source': 'auto', 'direction': 'lower_better', 'weight': Decimal('25.00'),
     'target_value': Decimal('2.00'), 'unit': '%', 'display_order': 2,
     'description': 'Rejected quantity as a percentage of received quantity at inspection.'},
    {'code': 'RESP', 'name': 'Responsiveness', 'kpi_type': 'responsiveness',
     'source': 'auto', 'direction': 'lower_better', 'weight': Decimal('20.00'),
     'target_value': Decimal('3.00'), 'unit': 'days', 'display_order': 3,
     'description': 'Average time to respond to RFx/sourcing invitations and acknowledge POs.'},
    {'code': 'PRICE', 'name': 'Price / Cost Variance', 'kpi_type': 'price_variance',
     'source': 'auto', 'direction': 'lower_better', 'weight': Decimal('10.00'),
     'target_value': Decimal('2.00'), 'unit': '%', 'display_order': 4,
     'description': 'Average absolute invoiced-vs-PO unit-price variance.'},
    {'code': 'FB', 'name': '360° Feedback', 'kpi_type': 'feedback',
     'source': 'feedback', 'direction': 'higher_better', 'weight': Decimal('15.00'),
     'target_value': Decimal('5.00'), 'unit': '/5', 'display_order': 5,
     'description': 'Average internal-stakeholder rating (1-5).'},
]


def ensure_default_kpis(tenant):
    """Idempotently provision the default KPI set for a tenant. Returns the count created."""
    created = 0
    for spec in DEFAULT_KPIS:
        _, made = KpiDefinition.all_objects.get_or_create(
            tenant=tenant, code=spec['code'], defaults={**spec, 'is_active': True},
        )
        created += int(made)
    return created


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def next_scorecard_number(tenant) -> str:
    """Generate the next gap-free ``SPC-<SLUG>-NNNNN`` number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = Scorecard.all_objects.filter(tenant=tenant).count() + 1
    number = f'SPC-{slug}-{count:05d}'
    while Scorecard.all_objects.filter(tenant=tenant, scorecard_number=number).exists():
        count += 1
        number = f'SPC-{slug}-{count:05d}'
    return number


def next_pip_number(tenant) -> str:
    """Generate the next gap-free ``PIP-<SLUG>-NNNNN`` number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = ImprovementPlan.all_objects.filter(tenant=tenant).count() + 1
    number = f'PIP-{slug}-{count:05d}'
    while ImprovementPlan.all_objects.filter(tenant=tenant, pip_number=number).exists():
        count += 1
        number = f'PIP-{slug}-{count:05d}'
    return number


# ---------------------------------------------------------------------------
# The KPI computation engine
# ---------------------------------------------------------------------------
def _in_period(qs, field, start, end):
    """Filter ``qs`` to rows whose ``field`` date is inside [start, end].

    A null date is **excluded** (the inverse of the budget module's keep-null) — a source document
    with no date cannot be judged for performance (you can't grade on-time delivery on an undated
    receipt).
    """
    cond = Q(**{f'{field}__isnull': False})
    if start:
        cond &= Q(**{f'{field}__gte': start})
    if end:
        cond &= Q(**{f'{field}__lte': end})
    return qs.filter(cond)


def _mean(values):
    return (sum(values) / len(values)) if values else None


def _otd_value(vendor, start, end):
    """On-time delivery %: goods receipts received on/before the PO's promised date."""
    from apps.goods_receipt.models import GoodsReceipt

    grns = (
        GoodsReceipt.all_objects
        .filter(tenant=vendor.tenant, vendor=vendor, status__in=RECEIVED_GRN_STATUSES)
        .select_related('purchase_order')
    )
    grns = _in_period(grns, 'received_date', start, end)
    judged = on_time = 0
    for gr in grns:
        promised = gr.purchase_order.expected_delivery_date if gr.purchase_order_id else None
        if not promised:
            continue
        judged += 1
        if gr.received_date <= promised:
            on_time += 1
    if judged == 0:
        return {'raw_value': None, 'data_points': 'No dated receipts in period.', 'sample_size': 0}
    raw = Decimal(on_time) / Decimal(judged) * 100
    return {
        'raw_value': raw.quantize(Q2),
        'data_points': f'{on_time}/{judged} receipts on time',
        'sample_size': judged,
    }


def _defect_value(vendor, start, end):
    """Defect rate %: rejected qty / received qty across the vendor's receipt lines in period."""
    from apps.goods_receipt.models import GoodsReceiptLine

    lines = (
        GoodsReceiptLine.all_objects
        .filter(
            tenant=vendor.tenant, goods_receipt__vendor=vendor,
            goods_receipt__status__in=RECEIVED_GRN_STATUSES,
        )
    )
    lines = _in_period(lines, 'goods_receipt__received_date', start, end)
    agg = lines.aggregate(rec=Sum('received_quantity'), rej=Sum('rejected_quantity'))
    received = agg['rec'] or ZERO
    rejected = agg['rej'] or ZERO
    if received <= 0:
        return {'raw_value': None, 'data_points': 'No received units in period.', 'sample_size': 0}
    raw = rejected / received * 100
    return {
        'raw_value': raw.quantize(Q2),
        'data_points': f'{rejected:g}/{received:g} units rejected',
        'sample_size': int(received),
    }


def _responsiveness_value(vendor, start, end):
    """Average vendor response time in days across RFx + sourcing invitations + PO acknowledgements.

    Response timestamps are filtered to the period in Python (they are datetimes); a missing response
    is excluded (only actual responses contribute).
    """
    from apps.purchase_orders.models import PurchaseOrder
    from apps.rfx.models import RfxInvitee
    from apps.sourcing.models import SourcingEventInvitee

    def _in_window(dt):
        if dt is None:
            return False
        d = timezone.localtime(dt).date() if timezone.is_aware(dt) else dt.date()
        if start and d < start:
            return False
        if end and d > end:
            return False
        return True

    durations = []
    for inv in RfxInvitee.all_objects.filter(
            tenant=vendor.tenant, vendor=vendor, responded_at__isnull=False):
        if inv.invited_at and _in_window(inv.responded_at):
            durations.append((inv.responded_at - inv.invited_at).total_seconds() / 86400)
    for inv in SourcingEventInvitee.all_objects.filter(
            tenant=vendor.tenant, vendor=vendor, responded_at__isnull=False):
        if inv.invited_at and _in_window(inv.responded_at):
            durations.append((inv.responded_at - inv.invited_at).total_seconds() / 86400)
    for po in PurchaseOrder.all_objects.filter(
            tenant=vendor.tenant, vendor=vendor,
            issued_at__isnull=False, acknowledged_at__isnull=False):
        if _in_window(po.acknowledged_at):
            durations.append((po.acknowledged_at - po.issued_at).total_seconds() / 86400)

    if not durations:
        return {'raw_value': None, 'data_points': 'No responses in period.', 'sample_size': 0}
    avg = _mean(durations)
    return {
        'raw_value': Decimal(str(round(avg, 2))),
        'data_points': f'avg {avg:.1f} days over {len(durations)} response(s)',
        'sample_size': len(durations),
    }


def _price_variance_value(vendor, start, end):
    """Average absolute invoiced-vs-PO unit-price variance (% of invoiced unit price)."""
    from apps.invoicing.models import SupplierInvoiceLine

    lines = (
        SupplierInvoiceLine.all_objects
        .filter(
            tenant=vendor.tenant, supplier_invoice__vendor=vendor,
            supplier_invoice__status__in=ACTUAL_INVOICE_STATUSES,
        )
    )
    lines = _in_period(lines, 'supplier_invoice__invoice_date', start, end)
    pcts = []
    for ln in lines.only('unit_price', 'price_variance'):
        if ln.unit_price and ln.unit_price > 0 and ln.price_variance is not None:
            pcts.append(abs(float(ln.price_variance)) / float(ln.unit_price) * 100)
    if not pcts:
        return {'raw_value': None, 'data_points': 'No matched invoice lines in period.',
                'sample_size': 0}
    avg = _mean(pcts)
    return {
        'raw_value': Decimal(str(round(avg, 2))),
        'data_points': f'avg {avg:.1f}% over {len(pcts)} line(s)',
        'sample_size': len(pcts),
    }


def _feedback_value(vendor, start, end):
    """Average submitted 360° feedback rating (1-5) for the vendor in period."""
    qs = PerformanceFeedback.all_objects.filter(
        tenant=vendor.tenant, vendor=vendor, status='submitted',
        rating__isnull=False, submitted_at__isnull=False)
    # submitted_at is a DateTimeField — compare on its date to avoid a naive-datetime filter.
    if start:
        qs = qs.filter(submitted_at__date__gte=start)
    if end:
        qs = qs.filter(submitted_at__date__lte=end)
    ratings = list(qs.values_list('rating', flat=True))
    if not ratings:
        return {'raw_value': None, 'data_points': 'No feedback in period.', 'sample_size': 0}
    avg = _mean(ratings)
    return {
        'raw_value': Decimal(str(round(avg, 2))),
        'data_points': f'avg {avg:.1f}/5 over {len(ratings)} review(s)',
        'sample_size': len(ratings),
    }


_KPI_DISPATCH = {
    'on_time_delivery': _otd_value,
    'defect_rate': _defect_value,
    'responsiveness': _responsiveness_value,
    'price_variance': _price_variance_value,
    'feedback': _feedback_value,
}


def compute_kpi_value(kpi, vendor, start, end):
    """Compute one KPI's raw value for a vendor over [start, end].

    Returns ``{'raw_value': Decimal|None, 'data_points': str, 'sample_size': int}``. Manual/custom
    KPIs return ``None`` (the operator enters the value on the draft line by hand).
    """
    fn = _KPI_DISPATCH.get(kpi.kpi_type)
    if fn is None:
        return {'raw_value': None, 'data_points': 'Manual entry.', 'sample_size': 0}
    return fn(vendor, start, end)


def normalize_score(kpi, raw_value):
    """Map a raw KPI value to a 0-100 score using the KPI's direction + target. ``None`` -> ``None``.

    * higher-is-better: ``raw / target * 100`` (clamped 0-100); with no target, ``raw`` is assumed to
      already be a 0-100 percentage and is clamped.
    * lower-is-better: meeting or beating the target scores 100; worse than target degrades as
      ``target / raw * 100`` (clamped). With no target, ``100 - raw`` (raw assumed a percentage).
    """
    if raw_value is None:
        return None
    raw = float(raw_value)
    target = float(kpi.target_value) if kpi.target_value is not None else None

    if kpi.direction == 'lower_better':
        if raw <= 0:
            score = 100.0
        elif target and target > 0:
            score = min(100.0, target / raw * 100)
        else:
            score = 100.0 - raw
    else:  # higher_better
        if target and target > 0:
            score = raw / target * 100
        else:
            score = raw
    score = max(0.0, min(100.0, score))
    return Decimal(str(round(score, 2)))


# ---------------------------------------------------------------------------
# Scorecard generation (persists a snapshot)
# ---------------------------------------------------------------------------
def _build_lines(scorecard, vendor, start, end):
    """Compute + persist a ScorecardLine per active KPI; return them."""
    lines = []
    for kpi in KpiDefinition.all_objects.filter(
            tenant=vendor.tenant, is_active=True).order_by('display_order', 'name'):
        result = compute_kpi_value(kpi, vendor, start, end)
        raw = result['raw_value']
        score = normalize_score(kpi, raw)
        weighted = (score * kpi.weight / 100).quantize(Q2) if score is not None else ZERO
        lines.append(ScorecardLine.all_objects.create(
            tenant=vendor.tenant, scorecard=scorecard, kpi=kpi,
            kpi_code=kpi.code, kpi_name=kpi.name, kpi_type=kpi.kpi_type,
            direction=kpi.direction, target_value=kpi.target_value, unit=kpi.unit,
            raw_value=raw, score=score, weight=kpi.weight, weighted_score=weighted,
            data_points=result['data_points'][:255],
            is_manual=(kpi.source != 'auto' or kpi.kpi_type not in AUTO_KPI_TYPES) and (
                kpi.kpi_type != 'feedback'),
        ))
    return lines


def _overall_from_lines(lines):
    """Weighted mean of the lines that actually scored (re-normalised over present weights)."""
    num = ZERO
    den = ZERO
    for ln in lines:
        if ln.score is not None and ln.weight:
            num += ln.score * ln.weight
            den += ln.weight
    if den <= 0:
        return ZERO
    return (num / den).quantize(Q2)


@transaction.atomic
def generate_scorecard(vendor, start, end, user, *, period_label='', status='final', request=None):
    """Compute + persist a scorecard for a vendor over [start, end].

    Reads the source tables once and stores every line. When ``status='final'`` the card becomes the
    vendor's current card and its score is denormalised onto the Vendor row. Notifies managers when
    the resulting band is underperforming (a PIP candidate).
    """
    if end < start:
        raise ValidationError('Period end must not be before the start.')
    tenant = vendor.tenant
    card = Scorecard.all_objects.create(
        tenant=tenant, vendor=vendor,
        scorecard_number=next_scorecard_number(tenant),
        period_label=period_label or f'{start:%Y-%m-%d} – {end:%Y-%m-%d}',
        period_start=start, period_end=end, status='draft',
        generated_by=user, generated_at=timezone.now(),
    )
    lines = _build_lines(card, vendor, start, end)
    card.overall_score = _overall_from_lines(lines)
    card.rating_band = rating_band_from_score(card.overall_score)
    card.status = status
    card.save(update_fields=['overall_score', 'rating_band', 'status', 'updated_at'])

    if status == 'final':
        _mark_current(card)

    record_audit(
        tenant, user, 'supplier_performance.scorecard_generated',
        target_type='Scorecard', target_id=card.id,
        message=(f'Scorecard {card.scorecard_number} for {vendor.legal_name} '
                 f'= {card.overall_score} ({card.rating_band})'),
        request=request,
    )
    if status == 'final' and card.rating_band in UNDERPERFORMING_BANDS:
        _notify_underperformance(card, user)
    return card


def _mark_current(card):
    """Make ``card`` the vendor's current scorecard and denormalise its score onto the Vendor row."""
    Scorecard.all_objects.filter(
        tenant=card.tenant, vendor_id=card.vendor_id, is_current=True,
    ).exclude(pk=card.pk).update(is_current=False)
    if not card.is_current:
        card.is_current = True
        card.save(update_fields=['is_current', 'updated_at'])
    vendor = Vendor.all_objects.select_for_update().get(pk=card.vendor_id)
    vendor.performance_score = card.overall_score
    vendor.performance_band = card.rating_band
    vendor.performance_scored_at = card.generated_at or timezone.now()
    vendor.save(update_fields=[
        'performance_score', 'performance_band', 'performance_scored_at', 'updated_at'])


def _notify_underperformance(card, user):
    """Alert the tenant's procurement managers that a vendor is a PIP candidate."""
    from apps.accounts.models import User

    managers = User.objects.filter(
        tenant=card.tenant, is_active=True,
    ).filter(Q(is_tenant_admin=True) | Q(role__in=('procurement_manager', 'buyer')))
    for mgr in managers:
        create_notification(
            card.tenant, mgr,
            f'Underperforming supplier: {card.vendor.legal_name}',
            category='approval', priority='high',
            message=(f'{card.vendor.legal_name} scored {card.overall_score} '
                     f'({card.get_rating_band_display()}) on {card.scorecard_number} — '
                     'consider an improvement plan.'),
        )


@transaction.atomic
def regenerate_scorecard(card, user, *, request=None):
    """Recompute a DRAFT card's lines from current source data."""
    if not card.is_editable:
        raise ValidationError('Only a draft scorecard can be regenerated.')
    card.lines.all().delete()
    lines = _build_lines(card, card.vendor, card.period_start, card.period_end)
    card.overall_score = _overall_from_lines(lines)
    card.rating_band = rating_band_from_score(card.overall_score)
    card.generated_at = timezone.now()
    card.generated_by = user
    card.save(update_fields=['overall_score', 'rating_band', 'generated_at',
                             'generated_by', 'updated_at'])
    record_audit(
        card.tenant, user, 'supplier_performance.scorecard_regenerated',
        target_type='Scorecard', target_id=card.id,
        message=f'Scorecard {card.scorecard_number} regenerated', request=request,
    )
    return card


@transaction.atomic
def finalize_scorecard(card, user, *, request=None):
    """Draft -> final. Marks the card current + denormalises onto the Vendor row."""
    if card.status != 'draft':
        raise ValidationError('Only a draft scorecard can be finalized.')
    card.status = 'final'
    card.save(update_fields=['status', 'updated_at'])
    _mark_current(card)
    record_audit(
        card.tenant, user, 'supplier_performance.scorecard_finalized',
        target_type='Scorecard', target_id=card.id,
        message=f'Scorecard {card.scorecard_number} finalized ({card.rating_band})', request=request,
    )
    if card.rating_band in UNDERPERFORMING_BANDS:
        _notify_underperformance(card, user)
    return card


# ---------------------------------------------------------------------------
# 360° Feedback
# ---------------------------------------------------------------------------
def request_feedback(vendor, reviewer, requested_by, *, period_label='', request=None):
    """Create a pending feedback request for an internal reviewer + notify them."""
    fb = PerformanceFeedback.all_objects.create(
        tenant=vendor.tenant, vendor=vendor, reviewer=reviewer, requested_by=requested_by,
        period_label=period_label, status='requested', requested_at=timezone.now(),
    )
    if reviewer:
        create_notification(
            vendor.tenant, reviewer,
            f'Feedback requested: {vendor.legal_name}',
            category='approval', priority='normal',
            message=f'Please rate the performance of {vendor.legal_name}.',
        )
    record_audit(
        vendor.tenant, requested_by, 'supplier_performance.feedback_requested',
        target_type='PerformanceFeedback', target_id=fb.id,
        message=f'Feedback on {vendor.legal_name} requested from {reviewer}', request=request,
    )
    return fb


def submit_feedback(feedback, user, *, rating, quality_rating=None, delivery_rating=None,
                    communication_rating=None, would_recommend=None, comments='', request=None):
    """Record a reviewer's submitted rating."""
    if feedback.status not in ('requested', 'submitted'):
        raise ValidationError('This feedback request can no longer be submitted.')
    feedback.rating = rating
    feedback.quality_rating = quality_rating
    feedback.delivery_rating = delivery_rating
    feedback.communication_rating = communication_rating
    feedback.would_recommend = would_recommend
    feedback.comments = comments
    feedback.status = 'submitted'
    feedback.submitted_at = timezone.now()
    feedback.save()
    record_audit(
        feedback.tenant, user, 'supplier_performance.feedback_submitted',
        target_type='PerformanceFeedback', target_id=feedback.id,
        message=f'Feedback on {feedback.vendor.legal_name}: {rating}/5', request=request,
    )
    return feedback


def cancel_feedback(feedback, user, *, request=None):
    """Cancel an outstanding feedback request."""
    if feedback.status != 'requested':
        raise ValidationError('Only an outstanding request can be cancelled.')
    feedback.status = 'cancelled'
    feedback.save(update_fields=['status', 'updated_at'])
    record_audit(
        feedback.tenant, user, 'supplier_performance.feedback_cancelled',
        target_type='PerformanceFeedback', target_id=feedback.id,
        message='Feedback request cancelled', request=request,
    )
    return feedback


# ---------------------------------------------------------------------------
# Performance Improvement Plans (PIP)
# ---------------------------------------------------------------------------
def record_status_event(plan, from_status, to_status, user, note=''):
    """Append an immutable entry to a PIP's lifecycle timeline."""
    return PIPStatusEvent.all_objects.create(
        tenant=plan.tenant, improvement_plan=plan,
        from_status=from_status, to_status=to_status, actor=user, note=note,
    )


def create_plan(vendor, user, *, title, summary='', severity='medium', owner=None,
                target_date=None, scorecard=None, request=None):
    """Create a draft PIP for a vendor (optionally tied to the triggering scorecard)."""
    plan = ImprovementPlan.all_objects.create(
        tenant=vendor.tenant, vendor=vendor, scorecard=scorecard,
        pip_number=next_pip_number(vendor.tenant), title=title, summary=summary,
        severity=severity, owner=owner, target_date=target_date, status='draft',
        created_by=user,
    )
    record_status_event(plan, '', 'draft', user, note='Created')
    record_audit(
        vendor.tenant, user, 'supplier_performance.pip_created',
        target_type='ImprovementPlan', target_id=plan.id,
        message=f'PIP {plan.pip_number} for {vendor.legal_name} created', request=request,
    )
    return plan


@transaction.atomic
def set_plan_status(plan, to_status, user, *, note='', request=None):
    """Move a PIP through its lifecycle (validated + audited + timeline-stamped)."""
    from_status = plan.status
    allowed = PIP_TRANSITIONS.get(from_status, ())
    if to_status not in allowed:
        raise ValidationError(f'Cannot move a {from_status} plan to {to_status}.')
    plan.status = to_status
    stamp_field = PIP_STATUS_TIMESTAMP.get(to_status)
    update_fields = ['status', 'updated_at']
    if stamp_field and not getattr(plan, stamp_field):
        setattr(plan, stamp_field, timezone.now())
        update_fields.append(stamp_field)
    plan.save(update_fields=update_fields)
    record_status_event(plan, from_status, to_status, user, note=note)
    record_audit(
        plan.tenant, user, 'supplier_performance.pip_status',
        target_type='ImprovementPlan', target_id=plan.id,
        message=f'PIP {plan.pip_number}: {from_status} → {to_status}', request=request,
    )
    if plan.owner and to_status in ('open', 'in_progress', 'closed'):
        create_notification(
            plan.tenant, plan.owner, f'Improvement plan {plan.pip_number}: {to_status}',
            category='info', message=f'{plan.title} is now {plan.get_status_display()}.',
        )
    return plan


def acknowledge_plan(plan, user, *, note='', request=None):
    """Record that the vendor has acknowledged a PIP (timeline note + owner notification)."""
    record_status_event(plan, plan.status, plan.status, user,
                         note=f'Acknowledged by vendor{": " + note if note else ""}')
    record_audit(
        plan.tenant, user, 'supplier_performance.pip_acknowledged',
        target_type='ImprovementPlan', target_id=plan.id,
        message=f'PIP {plan.pip_number} acknowledged by vendor', request=request)
    if plan.owner:
        create_notification(
            plan.tenant, plan.owner, f'Vendor acknowledged {plan.pip_number}',
            category='info', message=f'{plan.vendor.legal_name} acknowledged the improvement plan.')
    return plan


def scan_pip_alerts(tenant=None, *, now=None):
    """Raise a one-time alert for each open PIP past its target date. Idempotent via ``alerted_at``.

    Returns the number of plans newly alerted.
    """
    now = now or timezone.now()
    today = now.date()
    tenants = [tenant] if tenant is not None else list(Tenant.objects.all())
    alerted = 0
    for t in tenants:
        plans = ImprovementPlan.all_objects.filter(
            tenant=t, status__in=('open', 'in_progress'),
            target_date__lt=today, alerted_at__isnull=True,
        ).exclude(target_date__isnull=True)
        for plan in plans:
            plan.alerted_at = now
            plan.save(update_fields=['alerted_at', 'updated_at'])
            alerted += 1
            record_audit(
                t, None, 'supplier_performance.pip_overdue', level='warning',
                target_type='ImprovementPlan', target_id=plan.id,
                message=f'PIP {plan.pip_number} overdue (target {plan.target_date})',
            )
            if plan.owner:
                create_notification(
                    t, plan.owner, f'Overdue improvement plan: {plan.pip_number}',
                    category='deadline', priority='high',
                    message=f'{plan.title} passed its target date of {plan.target_date}.',
                )
    return alerted


# ---------------------------------------------------------------------------
# Trending / benchmarking read models
# ---------------------------------------------------------------------------
def vendor_trend(vendor, *, limit=8):
    """Final scorecards oldest→newest for a vendor: labels + overall series + per-KPI series."""
    cards = list(
        Scorecard.all_objects
        .filter(tenant=vendor.tenant, vendor=vendor, status__in=('final', 'archived'))
        .order_by('-period_end')[:limit]
    )
    cards.reverse()
    labels = [c.period_label for c in cards]
    overall = [float(c.overall_score) for c in cards]
    kpi_series = defaultdict(lambda: [None] * len(cards))
    for idx, card in enumerate(cards):
        for ln in card.lines.all():
            if ln.score is not None:
                kpi_series[ln.kpi_code or ln.kpi_name][idx] = float(ln.score)
    return {
        'labels': labels,
        'overall': overall,
        'kpi_series': {k: v for k, v in kpi_series.items()},
        'cards': cards,
    }


def tenant_benchmark(tenant, *, kpi_code=None):
    """Per-vendor current overall score (or one KPI's score) + the tenant average, sorted desc."""
    cards = (
        Scorecard.all_objects
        .filter(tenant=tenant, is_current=True, status='final')
        .select_related('vendor')
    )
    rows = []
    for card in cards:
        if kpi_code:
            line = card.lines.filter(kpi_code=kpi_code).first()
            value = float(line.score) if line and line.score is not None else None
        else:
            value = float(card.overall_score)
        if value is None:
            continue
        rows.append({
            'vendor': card.vendor, 'scorecard': card, 'value': value,
            'band': card.rating_band, 'band_color': card.band_color,
        })
    rows.sort(key=lambda r: r['value'], reverse=True)
    avg = round(sum(r['value'] for r in rows) / len(rows), 2) if rows else 0.0
    return {'rows': rows, 'average': avg, 'kpi_code': kpi_code}


def tenant_performance_metrics(tenant):
    """Dashboard tiles: scored-vendor count, average score, band distribution, open PIPs, pending FB."""
    current = Scorecard.all_objects.filter(tenant=tenant, is_current=True, status='final')
    scores = list(current.values_list('overall_score', flat=True))
    band_counts = defaultdict(int)
    for band in current.values_list('rating_band', flat=True):
        band_counts[band] += 1
    avg = round(float(sum(scores) / len(scores)), 1) if scores else 0.0
    bands_order = ['excellent', 'good', 'acceptable', 'poor', 'critical']
    return {
        'scored_vendors': len(scores),
        'average_score': avg,
        'band_labels': [b.title() for b in bands_order],
        'band_values': [band_counts.get(b, 0) for b in bands_order],
        'underperforming': sum(band_counts.get(b, 0) for b in UNDERPERFORMING_BANDS),
        'open_pips': ImprovementPlan.all_objects.filter(
            tenant=tenant, status__in=('open', 'in_progress')).count(),
        'pending_feedback': PerformanceFeedback.all_objects.filter(
            tenant=tenant, status='requested').count(),
    }


# ---------------------------------------------------------------------------
# Cron-style batch generation
# ---------------------------------------------------------------------------
def generate_scorecards_for_period(tenant, start, end, *, period_label='', user=None):
    """Generate a final scorecard for every active vendor of a tenant. Returns counts."""
    set_current_tenant(tenant)
    vendors = Vendor.all_objects.filter(tenant=tenant, status='active')
    generated = 0
    for vendor in vendors:
        generate_scorecard(vendor, start, end, user, period_label=period_label, status='final')
        generated += 1
    return {'vendors': vendors.count(), 'generated': generated}


def generate_all_tenants(start, end, *, period_label='', user=None):
    """Cron entry point — generate scorecards for every tenant. Returns total generated."""
    total = 0
    for t in Tenant.objects.all():
        result = generate_scorecards_for_period(t, start, end, period_label=period_label, user=user)
        total += result['generated']
    set_current_tenant(None)
    return total


def scan_all_tenants():
    """Cron entry point — sweep every tenant for overdue PIPs. Returns total plans alerted."""
    total = 0
    for t in Tenant.objects.all():
        set_current_tenant(t)
        total += scan_pip_alerts(t)
    set_current_tenant(None)
    return total


# ---------------------------------------------------------------------------
# Export rows (consumed by spend_analytics.exports.csv_response / xlsx_response)
# ---------------------------------------------------------------------------
SCORECARD_EXPORT_HEADER = [
    'KPI', 'Type', 'Raw value', 'Unit', 'Target', 'Score', 'Weight %', 'Weighted', 'Evidence',
]


def scorecard_rows_for_export(card):
    """``(header, rows)`` for one scorecard's lines (CSV/XLSX)."""
    rows = []
    for ln in card.lines.all():
        rows.append([
            ln.kpi_name or ln.kpi_code, ln.kpi_type,
            '' if ln.raw_value is None else str(ln.raw_value), ln.unit,
            '' if ln.target_value is None else str(ln.target_value),
            '' if ln.score is None else str(ln.score), str(ln.weight),
            str(ln.weighted_score), ln.data_points,
        ])
    return SCORECARD_EXPORT_HEADER, rows


BENCHMARK_EXPORT_HEADER = ['Vendor', 'Vendor #', 'Score', 'Band', 'Scorecard']


def benchmark_rows_for_export(tenant, *, kpi_code=None):
    """``(header, rows)`` for the cross-vendor benchmark (CSV/XLSX)."""
    data = tenant_benchmark(tenant, kpi_code=kpi_code)
    rows = [
        [r['vendor'].legal_name, r['vendor'].vendor_number, r['value'],
         r['band'], r['scorecard'].scorecard_number]
        for r in data['rows']
    ]
    return BENCHMARK_EXPORT_HEADER, rows
