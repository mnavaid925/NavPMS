"""Security tests: role gates, cross-tenant isolation, export gating, anon redirect.

Mirrors the spend_analytics D-01/D-02 posture — read pages AND exports must never be gated on
tenant alone. ``requester`` (no role) is bounced from every page; ``approver`` may view but not
manage; a cross-tenant admin gets a 404 on another tenant's budget.
"""
import pytest
from django.urls import reverse

from apps.budget.models import Budget

pytestmark = pytest.mark.django_db


def test_anonymous_redirected_to_login(client, budget_data):
    resp = client.get(reverse('budget:dashboard'))
    assert resp.status_code == 302
    assert '/accounts/login/' in resp.url


def test_requester_bounced_from_view_pages(client, budget_data, requester):
    client.force_login(requester)
    resp = client.get(reverse('budget:dashboard'))
    assert resp.status_code == 302  # redirected away, not rendered


def test_requester_cannot_create_budget(client, budget_data, requester):
    client.force_login(requester)
    resp = client.post(reverse('budget:budget_create'), {
        'name': 'Sneaky', 'period': budget_data.period.pk, 'currency': 'USD',
    })
    assert resp.status_code == 302
    assert not Budget.objects.filter(name='Sneaky').exists()


def test_approver_can_view_not_manage(client, budget_data, approver):
    client.force_login(approver)
    # view OK
    assert client.get(reverse('budget:dashboard')).status_code == 200
    assert client.get(reverse('budget:budget_detail', args=[budget_data.budget.pk])).status_code == 200
    # manage blocked (no new budget created)
    resp = client.post(reverse('budget:budget_create'), {
        'name': 'ByApprover', 'period': budget_data.period.pk, 'currency': 'USD',
    })
    assert resp.status_code == 302
    assert not Budget.objects.filter(name='ByApprover').exists()


def test_buyer_can_manage(client, budget_data, buyer_user):
    client.force_login(buyer_user)
    resp = client.post(reverse('budget:budget_create'), {
        'name': 'ByBuyer', 'period': budget_data.period.pk, 'currency': 'USD',
    })
    assert resp.status_code == 302
    assert Budget.objects.filter(tenant=budget_data.tenant, name='ByBuyer').exists()


def test_cross_tenant_budget_404(client, budget_data, intruder):
    """A different tenant's admin cannot read this tenant's budget (IDOR)."""
    client.force_login(intruder)
    resp = client.get(reverse('budget:budget_detail', args=[budget_data.budget.pk]))
    assert resp.status_code == 404


def test_cross_tenant_export_404(client, budget_data, intruder):
    client.force_login(intruder)
    resp = client.get(reverse('budget:export_budget', args=[budget_data.budget.pk, 'csv']))
    assert resp.status_code == 404


def test_requester_cannot_export(client, budget_data, requester):
    client.force_login(requester)
    resp = client.get(reverse('budget:export_variance', args=['csv']))
    # bounced by _require_view before any data is produced
    assert resp.status_code == 302
