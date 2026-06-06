"""View-level tests: pages load, CRUD flows, lifecycle, export content-types."""
import pytest
from django.urls import reverse

from apps.budget.models import Budget, BudgetAllocation, BudgetPeriod

pytestmark = pytest.mark.django_db


def test_dashboard_and_read_pages_load(client, budget_data, tenant_admin):
    client.force_login(tenant_admin)
    for name, args in [
        ('budget:dashboard', []),
        ('budget:budget_list', []),
        ('budget:budget_detail', [budget_data.budget.pk]),
        ('budget:budget_forecast', [budget_data.budget.pk]),
        ('budget:period_list', []),
        ('budget:period_detail', [budget_data.period.pk]),
        ('budget:variance', []),
        ('budget:check_log', []),
    ]:
        assert client.get(reverse(name, args=args)).status_code == 200


def test_period_crud(client, tenant, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('budget:period_create'), {
        'name': 'FY2027', 'period_type': 'annual', 'status': 'active',
        'start_date': '2027-01-01', 'end_date': '2027-12-31',
    })
    assert resp.status_code == 302
    period = BudgetPeriod.objects.get(tenant=tenant, name='FY2027')
    resp = client.post(reverse('budget:period_edit', args=[period.pk]), {
        'name': 'FY2027 (rev)', 'period_type': 'annual', 'status': 'active',
        'start_date': '2027-01-01', 'end_date': '2027-12-31',
    })
    assert resp.status_code == 302
    period.refresh_from_db()
    assert period.name == 'FY2027 (rev)'
    assert client.post(reverse('budget:period_delete', args=[period.pk])).status_code == 302
    assert not BudgetPeriod.objects.filter(pk=period.pk).exists()


def test_budget_create_allocate_activate(client, budget_data, tenant, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('budget:budget_create'), {
        'name': 'Capex budget', 'period': budget_data.period.pk, 'currency': 'USD',
    })
    assert resp.status_code == 302
    budget = Budget.objects.get(tenant=tenant, name='Capex budget')
    assert budget.budget_number.startswith('BUD-')
    assert budget.status == 'draft'

    # add an allocation on the new (draft) budget
    resp = client.post(reverse('budget:allocation_create', args=[budget.pk]), {
        'account_code': budget_data.account_code2.pk, 'allocated_amount': '5000',
    })
    assert resp.status_code == 302
    alloc = BudgetAllocation.objects.get(budget=budget)
    budget.refresh_from_db()
    assert budget.total_allocated == alloc.allocated_amount

    # edit it
    resp = client.post(reverse('budget:allocation_edit', args=[budget.pk, alloc.pk]), {
        'account_code': budget_data.account_code2.pk, 'allocated_amount': '6000',
    })
    assert resp.status_code == 302
    budget.refresh_from_db()
    assert budget.total_allocated == 6000

    # activate
    assert client.post(reverse('budget:budget_activate', args=[budget.pk])).status_code == 302
    budget.refresh_from_db()
    assert budget.status == 'active'
    # close
    assert client.post(reverse('budget:budget_close', args=[budget.pk])).status_code == 302
    budget.refresh_from_db()
    assert budget.status == 'closed'


def test_allocation_blocked_on_active_budget(client, budget_data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('budget:allocation_create', args=[budget_data.budget.pk]), {
        'account_code': budget_data.account_code2.pk, 'allocated_amount': '100',
    })
    # active budget is not editable -> redirect, no new allocation
    assert resp.status_code == 302
    assert BudgetAllocation.objects.filter(budget=budget_data.budget).count() == 1


def test_budget_edit_and_delete(client, tenant, tenant_admin, budget_data):
    client.force_login(tenant_admin)
    # make a fresh draft budget to delete
    resp = client.post(reverse('budget:budget_create'), {
        'name': 'Throwaway', 'period': budget_data.period.pk, 'currency': 'USD',
    })
    budget = Budget.objects.get(tenant=tenant, name='Throwaway')
    assert client.post(reverse('budget:budget_delete', args=[budget.pk])).status_code == 302
    assert not Budget.objects.filter(pk=budget.pk).exists()


@pytest.mark.parametrize('fmt,ctype', [
    ('csv', 'text/csv'),
    ('xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
])
def test_exports_content_types(client, budget_data, tenant_admin, fmt, ctype):
    client.force_login(tenant_admin)
    r1 = client.get(reverse('budget:export_variance', args=[fmt]))
    assert r1.status_code == 200 and r1['Content-Type'] == ctype
    r2 = client.get(reverse('budget:export_budget', args=[budget_data.budget.pk, fmt]))
    assert r2.status_code == 200 and r2['Content-Type'] == ctype


def test_export_bad_format_404(client, budget_data, tenant_admin):
    client.force_login(tenant_admin)
    assert client.get(reverse('budget:export_variance', args=['pdf'])).status_code == 404
