"""Service-level tests: consumption math, availability check (warn/block), forecast, variance,
alerts, numbering."""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.budget import services
from apps.budget.models import Budget, BudgetCheck
from apps.core.models import set_current_tenant

from .conftest import build_budget, make_requisition

pytestmark = pytest.mark.django_db


# ---------- Consumption math ----------
def test_allocation_consumption_breakdown(budget_data):
    c = services.allocation_consumption(budget_data.allocation)
    assert c['allocated'] == Decimal('1000.00')
    assert c['actual'] == Decimal('200.00')
    assert c['committed'] == Decimal('300.00')
    assert c['reserved'] == Decimal('100.00')
    assert c['available'] == Decimal('400.00')
    assert c['consumed'] == Decimal('500.00')
    assert c['over_budget'] is False


def test_committed_drops_when_po_closed(budget_data):
    """Closing the PO removes it from committed — proving no permanent double count."""
    budget_data.po.status = 'closed'
    budget_data.po.save(update_fields=['status'])
    c = services.allocation_consumption(budget_data.allocation)
    assert c['committed'] == Decimal('0.00')
    # actual (the approved invoice) is unaffected.
    assert c['actual'] == Decimal('200.00')


def test_over_budget_when_allocation_small(db, tenant, tenant_admin):
    data = build_budget(tenant, tenant_admin, allocated=Decimal('400.00'))
    c = services.allocation_consumption(data.allocation)
    assert c['available'] == Decimal('-200.00')
    assert c['over_budget'] is True


def test_next_budget_number_is_gap_free(budget_data):
    n = services.next_budget_number(budget_data.tenant)
    assert n == 'BUD-ACME-00002'


def test_budget_consumption_rollup(budget_data):
    data = services.budget_consumption(budget_data.budget)
    assert data['totals']['allocated'] == Decimal('1000.00')
    assert data['totals']['available'] == Decimal('400.00')
    assert data['totals']['over_count'] == 0


# ---------- Availability check ----------
def test_check_passes_within_budget(budget_data, tenant_admin):
    req = make_requisition(budget_data.tenant, tenant_admin, 50,
                           budget_data.account_code, status='draft')
    result = services.check_requisition_budget(req, tenant_admin)
    assert result['result'] == 'pass'
    assert result['blocked'] is False
    chk = BudgetCheck.all_objects.get(requisition=req)
    assert chk.result == 'pass'


@override_settings(BUDGET_ENFORCEMENT='warn')
def test_check_warns_but_does_not_raise(budget_data, tenant_admin):
    # available is 400 (excluding the request's own reservation); request 5000 -> over.
    req = make_requisition(budget_data.tenant, tenant_admin, 5000,
                           budget_data.account_code, status='draft')
    result = services.check_requisition_budget(req, tenant_admin)
    assert result['result'] == 'warn'
    assert result['blocked'] is False
    assert BudgetCheck.all_objects.get(requisition=req).result == 'warn'
    assert services.latest_check_status(req) is not None


@override_settings(BUDGET_ENFORCEMENT='block')
def test_check_blocks_and_raises(budget_data, tenant_admin):
    req = make_requisition(budget_data.tenant, tenant_admin, 5000,
                           budget_data.account_code, status='draft')
    with pytest.raises(ValidationError):
        services.check_requisition_budget(req, tenant_admin)
    # The evidence row persists even though the submit aborts.
    assert BudgetCheck.all_objects.get(requisition=req).result == 'block'


def test_check_excludes_own_reservation(budget_data, tenant_admin):
    """A submitted requisition must not be counted against itself when re-checked."""
    # budget_data.req already reserves 100; re-checking it should see available 500 (not 400).
    result = services.check_requisition_budget(budget_data.req, tenant_admin)
    line = result['lines'][0]
    assert line['available'] == Decimal('500.00')


def test_check_unbudgeted_cost_centre_passes(budget_data, tenant_admin):
    req = make_requisition(budget_data.tenant, tenant_admin, 9999,
                           budget_data.account_code2, status='draft')
    result = services.check_requisition_budget(req, tenant_admin)
    assert result['result'] == 'pass'


# ---------- Forecast / variance ----------
def test_forecast_returns_rows(budget_data):
    from datetime import date
    data = services.forecast(budget_data.budget, as_of=date(2026, 7, 1))
    assert len(data['rows']) == 1
    assert data['total_allocated'] == Decimal('1000.00')
    assert data['rows'][0]['projected'] > 0


def test_variance_report_flags_over(db, tenant, tenant_admin):
    data = build_budget(tenant, tenant_admin, allocated=Decimal('400.00'))
    report = services.variance_report(tenant)
    assert report['rows'][0]['flag'] == 'over'


# ---------- Lifecycle ----------
def test_activate_requires_allocations(db, tenant, tenant_admin):
    from apps.budget.models import Budget as B
    set_current_tenant(tenant)
    from apps.budget.models import BudgetPeriod
    period = BudgetPeriod.all_objects.create(
        tenant=tenant, name='FY27', start_date=__import__('datetime').date(2027, 1, 1),
        end_date=__import__('datetime').date(2027, 12, 31), status='active')
    budget = B.all_objects.create(
        tenant=tenant, budget_number='BUD-ACME-00009', name='Empty', period=period,
        status='draft')
    with pytest.raises(ValidationError):
        services.activate_budget(budget, tenant_admin)


def test_close_budget(budget_data, tenant_admin):
    services.close_budget(budget_data.budget, tenant_admin)
    budget_data.budget.refresh_from_db()
    assert budget_data.budget.status == 'closed'


# ---------- Alerts ----------
def test_scan_alerts_idempotent(db, tenant, tenant_admin):
    data = build_budget(tenant, tenant_admin, allocated=Decimal('400.00'))  # over budget
    first = services.scan_budget_alerts(tenant)
    assert first == 1
    second = services.scan_budget_alerts(tenant)
    assert second == 0  # already alerted -> idempotent
    data.budget.refresh_from_db()
    assert data.budget.over_budget_alerted_at is not None


def test_scan_alerts_skips_healthy(budget_data):
    # available 400 of 1000 -> 50% utilization, under the 90% warn threshold.
    assert services.scan_budget_alerts(budget_data.tenant) == 0
