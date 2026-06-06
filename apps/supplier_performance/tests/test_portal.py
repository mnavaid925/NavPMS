"""Vendor portal: own-data-only, final cards only, blocked vendors bounced."""
import pytest
from django.urls import reverse

from apps.supplier_performance import services
from .conftest import PERIOD_END, PERIOD_START

pytestmark = pytest.mark.django_db


def test_portal_lists_own_final_scorecards(client, tenant, vendor_a, tenant_admin, kpis,
                                           make_feedback, vendor_portal_user):
    make_feedback(tenant, vendor_a, 4)
    services.generate_scorecard(vendor_a, PERIOD_START, PERIOD_END, tenant_admin, status='final')
    client.force_login(vendor_portal_user)
    resp = client.get(reverse('vendor_portal:performance_scorecards'))
    assert resp.status_code == 200


def test_portal_draft_scorecard_404(client, tenant, vendor_a, tenant_admin, kpis, make_feedback,
                                    vendor_portal_user):
    make_feedback(tenant, vendor_a, 4)
    draft = services.generate_scorecard(vendor_a, PERIOD_START, PERIOD_END, tenant_admin,
                                        status='draft')
    client.force_login(vendor_portal_user)
    resp = client.get(reverse('vendor_portal:performance_scorecard_detail', args=[draft.pk]))
    assert resp.status_code == 404   # drafts are never exposed to the supplier


def test_portal_cannot_see_other_vendor_card(client, tenant, vendor_a, vendor_b, tenant_admin,
                                             kpis, make_feedback, vendor_portal_user):
    make_feedback(tenant, vendor_b, 4)
    other = services.generate_scorecard(vendor_b, PERIOD_START, PERIOD_END, tenant_admin,
                                        status='final')
    client.force_login(vendor_portal_user)   # bound to vendor_a
    resp = client.get(reverse('vendor_portal:performance_scorecard_detail', args=[other.pk]))
    assert resp.status_code == 404


def test_portal_blocked_vendor_bounced(client, tenant, blocked_vendor):
    from apps.accounts.models import User
    user = User.objects.create_user(
        username='portal_blocked', password='x', tenant=tenant,
        role='vendor_portal', vendor=blocked_vendor)
    client.force_login(user)
    resp = client.get(reverse('vendor_portal:performance_scorecards'))
    assert resp.status_code == 302   # vendor_required bounces blocked/inactive vendors


def test_portal_pip_acknowledge(client, tenant, vendor_a, tenant_admin, vendor_portal_user):
    plan = services.create_plan(vendor_a, tenant_admin, title='Recover')
    services.set_plan_status(plan, 'open', tenant_admin)
    client.force_login(vendor_portal_user)
    resp = client.post(reverse('vendor_portal:performance_pip_acknowledge', args=[plan.pk]),
                       {'note': 'understood'})
    assert resp.status_code == 302
