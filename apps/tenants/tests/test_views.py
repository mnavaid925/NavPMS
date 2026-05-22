"""Integration tests for Module 1 views."""
import pytest
from django.urls import reverse

from apps.core.models import Tenant
from apps.tenants.models import (
    BrandingSettings, Invoice, Plan, SecuritySettings, Subscription,
)

pytestmark = pytest.mark.django_db


# ---------- Onboarding wizard ----------

def test_onboarding_start_is_public(client):
    assert client.get(reverse('tenants:onboarding_start')).status_code == 200


def test_onboarding_plan_redirects_without_company(client):
    resp = client.get(reverse('tenants:onboarding_plan'))
    assert resp.status_code == 302


def test_onboarding_wizard_end_to_end(client, plan):
    resp = client.post(reverse('tenants:onboarding_company'), {
        'name': 'New Co', 'slug': 'new-co', 'timezone': 'UTC',
    })
    assert resp.status_code == 302
    resp = client.post(reverse('tenants:onboarding_plan'), {
        'plan': plan.pk, 'billing_cycle': 'monthly',
    })
    assert resp.status_code == 302
    resp = client.get(reverse('tenants:onboarding_complete'))
    assert resp.status_code == 200
    tenant = Tenant.objects.get(name='New Co')
    assert Subscription.objects.filter(tenant=tenant).exists()


# ---------- Plans ----------

def test_plan_list_is_public(client, plan):
    resp = client.get(reverse('tenants:plan_list'))
    assert resp.status_code == 200


def test_plan_detail_is_public(client, plan):
    resp = client.get(reverse('tenants:plan_detail', args=[plan.pk]))
    assert resp.status_code == 200


def test_plan_create_as_super_admin(client, super_user):
    client.force_login(super_user)
    resp = client.post(reverse('tenants:plan_create'), {
        'name': 'Pro', 'slug': 'pro', 'description': '',
        'price_monthly': '50.00', 'price_yearly': '500.00', 'currency': 'USD',
        'trial_days': '14', 'max_users': '20', 'max_storage_gb': '10',
        'max_vendors': '200', 'max_purchase_orders_per_month': '500',
        'sort_order': '2', 'is_active': 'on', 'is_public': 'on',
    })
    assert resp.status_code == 302
    assert Plan.objects.filter(slug='pro').exists()


def test_plan_delete_blocked_with_subscriptions(client, super_user, plan, subscription):
    client.force_login(super_user)
    client.post(reverse('tenants:plan_delete', args=[plan.pk]))
    assert Plan.objects.filter(pk=plan.pk).exists()


# ---------- Subscriptions ----------

def test_subscription_list_for_member(client, member, subscription):
    client.force_login(member)
    resp = client.get(reverse('tenants:subscription_list'))
    assert resp.status_code == 200
    assert subscription in resp.context['subscriptions']


def test_subscription_assign_creates_invoice(client, tenant_admin, plan):
    client.force_login(tenant_admin)
    resp = client.post(reverse('tenants:subscription_assign'), {
        'plan': plan.pk, 'billing_cycle': 'monthly', 'auto_renew': 'on',
    })
    assert resp.status_code == 302
    sub = Subscription.objects.get(tenant=tenant_admin.tenant)
    assert Invoice.objects.filter(subscription=sub).exists()


def test_subscription_cancel(client, tenant_admin, subscription):
    client.force_login(tenant_admin)
    client.post(reverse('tenants:subscription_cancel', args=[subscription.pk]),
                {'immediate': '1'})
    subscription.refresh_from_db()
    assert subscription.status == 'cancelled'


# ---------- Invoices ----------

def test_invoice_list_for_member(client, member, invoice):
    client.force_login(member)
    resp = client.get(reverse('tenants:invoice_list'))
    assert resp.status_code == 200


def test_invoice_pay(client, tenant_admin, invoice):
    client.force_login(tenant_admin)
    client.post(reverse('tenants:invoice_pay', args=[invoice.pk]))
    invoice.refresh_from_db()
    assert invoice.status == 'paid'


def test_invoice_detail_cross_tenant_redirects(client, member, other_tenant):
    """A user cannot open another tenant's invoice."""
    foreign = Invoice.objects.create(
        tenant=other_tenant, number='INV-GLOBEX-00001', status='sent')
    client.force_login(member)
    resp = client.get(reverse('tenants:invoice_detail', args=[foreign.pk]))
    assert resp.status_code == 302  # bounced to invoice list


# ---------- Branding / Security / Monitoring ----------

def test_branding_edit_get_creates_settings(client, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.get(reverse('tenants:branding_edit'))
    assert resp.status_code == 200
    assert BrandingSettings.objects.filter(tenant=tenant_admin.tenant).exists()


def test_security_edit_post(client, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('tenants:security_edit'), {
        'password_min_length': '12', 'session_timeout_minutes': '60',
        'password_expiry_days': '0',
    })
    assert resp.status_code == 302
    sec = SecuritySettings.objects.get(tenant=tenant_admin.tenant)
    assert sec.password_min_length == 12


def test_monitoring_dashboard_renders(client, tenant_admin, subscription):
    client.force_login(tenant_admin)
    assert client.get(
        reverse('tenants:monitoring_dashboard')).status_code == 200


def test_audit_log_list_renders(client, tenant_admin):
    client.force_login(tenant_admin)
    assert client.get(reverse('tenants:audit_log_list')).status_code == 200
