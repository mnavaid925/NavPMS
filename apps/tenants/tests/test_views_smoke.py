"""Smoke tests for Module 1 — GET renders, edit branches, invalid forms."""
import pytest
from django.urls import reverse

from apps.tenants.models import Plan

pytestmark = pytest.mark.django_db


def test_public_get_pages_render(client, plan):
    for url in (
        reverse('tenants:onboarding_company'),
        reverse('tenants:plan_list'),
        reverse('tenants:plan_detail', args=[plan.pk]),
    ):
        assert client.get(url).status_code == 200


def test_super_admin_get_pages_render(client, super_user, plan):
    client.force_login(super_user)
    for url in (
        reverse('tenants:plan_create'),
        reverse('tenants:plan_edit', args=[plan.pk]),
    ):
        assert client.get(url).status_code == 200


def test_tenant_admin_get_pages_render(client, tenant_admin, subscription, invoice):
    client.force_login(tenant_admin)
    for url in (
        reverse('tenants:subscription_assign'),
        reverse('tenants:subscription_detail', args=[subscription.pk]),
        reverse('tenants:invoice_detail', args=[invoice.pk]),
        reverse('tenants:security_edit'),
    ):
        assert client.get(url).status_code == 200


def test_plan_edit_updates(client, super_user, plan):
    client.force_login(super_user)
    client.post(reverse('tenants:plan_edit', args=[plan.pk]), {
        'name': 'Renamed', 'slug': plan.slug, 'description': '',
        'price_monthly': '30.00', 'price_yearly': '300.00', 'currency': 'USD',
        'trial_days': '7', 'max_users': '10', 'max_storage_gb': '5',
        'max_vendors': '100', 'max_purchase_orders_per_month': '200',
        'sort_order': '1', 'is_active': 'on', 'is_public': 'on'})
    plan.refresh_from_db()
    assert plan.name == 'Renamed'


def test_plan_delete_without_subscriptions(client, super_user, plan):
    client.force_login(super_user)
    client.post(reverse('tenants:plan_delete', args=[plan.pk]))
    assert not Plan.objects.filter(pk=plan.pk).exists()


def test_plan_list_filters(client, plan):
    resp = client.get(reverse('tenants:plan_list'),
                      {'q': 'Starter', 'active': 'active'})
    assert list(resp.context['plans']) == [plan]


def test_invalid_plan_create_rerenders(client, super_user):
    client.force_login(super_user)
    resp = client.post(reverse('tenants:plan_create'), {'name': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_invalid_onboarding_company_rerenders(client):
    resp = client.post(reverse('tenants:onboarding_company'), {'name': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_branding_edit_post(client, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('tenants:branding_edit'), {
        'primary_color': '#123456', 'secondary_color': '#654321'})
    assert resp.status_code == 302


def test_invoice_list_status_filter(client, member, invoice):
    client.force_login(member)
    resp = client.get(reverse('tenants:invoice_list'),
                      {'status': 'sent', 'q': 'INV'})
    assert invoice in resp.context['invoices']
