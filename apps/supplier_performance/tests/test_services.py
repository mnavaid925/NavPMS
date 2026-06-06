"""Service layer: normalisation, permissions, scorecard generation, PIP lifecycle, feedback."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.supplier_performance import services
from apps.supplier_performance.models import (
    ImprovementPlan, KpiDefinition, PerformanceFeedback, PIPStatusEvent, Scorecard,
)
from .conftest import PERIOD_END, PERIOD_START

pytestmark = pytest.mark.django_db


# ---------- normalize_score (pure) ----------

def _kpi(direction, target):
    return KpiDefinition(direction=direction,
                         target_value=Decimal(str(target)) if target is not None else None)


@pytest.mark.parametrize('direction,target,raw,expected', [
    ('higher_better', 95, 95, 100),
    ('higher_better', 95, 190, 100),     # clamped
    ('higher_better', 95, 0, 0),
    ('higher_better', 95, 47.5, 50),
    ('higher_better', None, 80, 80),     # no target -> raw is the %
    ('lower_better', 2, 0, 100),
    ('lower_better', 2, 2, 100),         # meeting target = full marks
    ('lower_better', 2, 4, 50),
    ('lower_better', 2, 8, 25),
    ('lower_better', None, 10, 90),      # no target -> 100 - raw
])
def test_normalize_score(direction, target, raw, expected):
    assert services.normalize_score(_kpi(direction, target), Decimal(str(raw))) == expected


def test_normalize_score_none_raw_is_none():
    assert services.normalize_score(_kpi('higher_better', 95), None) is None


# ---------- Permissions ----------

def test_can_manage_roles(tenant_admin, procurement_manager, buyer_user, evaluator, requester):
    assert services.can_manage_supplier_performance(tenant_admin)
    assert services.can_manage_supplier_performance(procurement_manager)
    assert services.can_manage_supplier_performance(buyer_user)
    assert not services.can_manage_supplier_performance(evaluator)   # approver: view only
    assert not services.can_manage_supplier_performance(requester)


def test_can_view_roles(evaluator, requester):
    assert services.can_view_supplier_performance(evaluator)
    assert not services.can_view_supplier_performance(requester)


# ---------- Scorecard generation ----------

def test_generate_scorecard_reweights_over_present_kpis(
        tenant, vendor_a, tenant_admin, kpis, make_feedback):
    """With only feedback data, a missing-data KPI must not drag the score to 0."""
    make_feedback(tenant, vendor_a, 4)  # rating 4 -> 4/5*100 = 80 on the feedback KPI
    card = services.generate_scorecard(
        vendor_a, PERIOD_START, PERIOD_END, tenant_admin, period_label='Q1 2026')
    assert card.overall_score == Decimal('80.00')
    assert card.rating_band == 'good'
    fb_line = card.lines.get(kpi_code='FB')
    assert fb_line.score == Decimal('80.00')
    # The auto KPIs with no source data are scored None (excluded), not 0.
    assert card.lines.get(kpi_code='OTD').score is None


def test_generate_scorecard_denormalises_onto_vendor(
        tenant, vendor_a, tenant_admin, kpis, make_feedback):
    make_feedback(tenant, vendor_a, 5)  # -> 100
    card = services.generate_scorecard(
        vendor_a, PERIOD_START, PERIOD_END, tenant_admin, status='final')
    vendor_a.refresh_from_db()
    assert card.is_current is True
    assert vendor_a.performance_score == Decimal('100.00')
    assert vendor_a.performance_band == 'excellent'
    assert vendor_a.performance_scored_at is not None


def test_finalize_flips_current_and_updates_vendor(
        tenant, vendor_a, tenant_admin, kpis, make_feedback):
    make_feedback(tenant, vendor_a, 3)  # -> 60
    draft = services.generate_scorecard(
        vendor_a, PERIOD_START, PERIOD_END, tenant_admin, status='draft')
    vendor_a.refresh_from_db()
    assert draft.is_current is False
    assert vendor_a.performance_score == Decimal('0.00')   # draft doesn't denormalise
    services.finalize_scorecard(draft, tenant_admin)
    draft.refresh_from_db()
    vendor_a.refresh_from_db()
    assert draft.is_current is True
    assert vendor_a.performance_score == Decimal('60.00')


def test_new_final_card_supersedes_prior_current(
        tenant, vendor_a, tenant_admin, kpis, make_feedback):
    make_feedback(tenant, vendor_a, 4)
    c1 = services.generate_scorecard(vendor_a, PERIOD_START, PERIOD_END, tenant_admin,
                                     status='final')
    c2 = services.generate_scorecard(vendor_a, PERIOD_START, PERIOD_END, tenant_admin,
                                     status='final')
    c1.refresh_from_db()
    assert c1.is_current is False
    assert c2.is_current is True


def test_scorecard_line_snapshots_survive_kpi_rename(
        tenant, vendor_a, tenant_admin, kpis, make_feedback):
    make_feedback(tenant, vendor_a, 4)
    card = services.generate_scorecard(vendor_a, PERIOD_START, PERIOD_END, tenant_admin)
    line = card.lines.get(kpi_code='FB')
    assert line.kpi_name == '360° Feedback'
    kpi = KpiDefinition.all_objects.get(tenant=tenant, code='FB')
    kpi.name = 'Renamed Feedback'
    kpi.save(update_fields=['name'])
    line.refresh_from_db()
    assert line.kpi_name == '360° Feedback'   # snapshot unchanged


def test_generate_rejects_inverted_period(tenant, vendor_a, tenant_admin, kpis):
    with pytest.raises(ValidationError):
        services.generate_scorecard(vendor_a, PERIOD_END, PERIOD_START, tenant_admin)


# ---------- PIP lifecycle ----------

def test_pip_valid_transition_appends_one_event(tenant, vendor_a, tenant_admin):
    plan = services.create_plan(vendor_a, tenant_admin, title='Recover')
    assert plan.status == 'draft'
    services.set_plan_status(plan, 'open', tenant_admin, note='go')
    plan.refresh_from_db()
    assert plan.status == 'open'
    assert plan.opened_at is not None
    # 'Created' (draft) + 'open' events.
    assert PIPStatusEvent.all_objects.filter(improvement_plan=plan).count() == 2


def test_pip_invalid_transition_raises(tenant, vendor_a, tenant_admin):
    plan = services.create_plan(vendor_a, tenant_admin, title='Recover')
    with pytest.raises(ValidationError):
        services.set_plan_status(plan, 'completed', tenant_admin)   # draft -> completed invalid


def test_pip_overdue_sweep_idempotent(tenant, vendor_a, tenant_admin):
    plan = services.create_plan(vendor_a, tenant_admin, title='Recover')
    services.set_plan_status(plan, 'open', tenant_admin)
    plan.target_date = timezone.now().date() - timedelta(days=2)
    plan.save(update_fields=['target_date'])
    assert services.scan_pip_alerts(tenant) == 1
    assert services.scan_pip_alerts(tenant) == 0   # alerted_at guard


# ---------- Feedback ----------

def test_request_then_submit_feedback(tenant, vendor_a, tenant_admin, evaluator):
    fb = services.request_feedback(vendor_a, evaluator, tenant_admin)
    assert fb.status == 'requested'
    assert fb.requested_at is not None
    services.submit_feedback(fb, evaluator, rating=4, comments='solid')
    fb.refresh_from_db()
    assert fb.status == 'submitted'
    assert fb.rating == 4
    assert fb.submitted_at is not None
