"""Access-control regression tests for Module 1 (OWASP A01)."""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_plan_create_forbidden_for_member(client, member):
    """Plan CRUD is super-admin only — an authenticated member gets 403."""
    client.force_login(member)
    assert client.get(reverse('tenants:plan_create')).status_code == 403


def test_plan_create_redirects_anonymous(client):
    resp = client.get(reverse('tenants:plan_create'))
    assert resp.status_code == 302 and 'login' in resp['Location'].lower()


def test_branding_edit_blocked_for_member(client, member):
    """Branding is tenant-admin only — a plain member is bounced."""
    client.force_login(member)
    resp = client.get(reverse('tenants:branding_edit'))
    assert resp.status_code == 302
    assert reverse('tenants:branding_edit') not in resp['Location']


def test_security_edit_blocked_for_member(client, member):
    client.force_login(member)
    assert client.get(reverse('tenants:security_edit')).status_code == 302


def test_subscription_list_redirects_anonymous(client):
    resp = client.get(reverse('tenants:subscription_list'))
    assert resp.status_code == 302 and 'login' in resp['Location'].lower()


def test_subscription_cancel_cross_tenant_404(client, tenant_admin, other_tenant, plan):
    """Cancelling another tenant's subscription is a 404 (scoped lookup)."""
    from apps.tenants.models import Subscription
    foreign = Subscription.objects.create(
        tenant=other_tenant, plan=plan, status='active')
    client.force_login(tenant_admin)
    resp = client.post(
        reverse('tenants:subscription_cancel', args=[foreign.pk]),
        {'immediate': '1'})
    assert resp.status_code == 404
    foreign.refresh_from_db()
    assert foreign.status == 'active'
