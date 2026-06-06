"""Regression tests for the Module 1 bug-hunt fixes.

Each test pins a specific defect found during the tenant-module review so it
cannot silently come back.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.tenants.models import Invoice, Plan, Subscription, Transaction
from apps.tenants.services import (
    _next_invoice_number, charge_invoice, create_invoice_for_subscription,
)

pytestmark = pytest.mark.django_db


# ---------- double-pay TOCTOU ----------

def test_charge_invoice_is_idempotent(invoice):
    """A second charge of a paid invoice must not charge again or duplicate the tx."""
    tx1 = charge_invoice(invoice)
    invoice.refresh_from_db()
    assert invoice.status == 'paid'

    tx2 = charge_invoice(invoice)            # simulates a double-click / retry
    assert tx2 is not None and tx2.pk == tx1.pk
    assert Transaction.objects.filter(invoice=invoice).count() == 1


def test_invoice_pay_endpoint_twice_charges_once(client, tenant_admin, invoice):
    client.force_login(tenant_admin)
    client.post(reverse('tenants:invoice_pay', args=[invoice.pk]))
    client.post(reverse('tenants:invoice_pay', args=[invoice.pk]))
    assert Transaction.objects.filter(invoice=invoice, status='succeeded').count() == 1


# ---------- invoice numbering ----------

def test_next_invoice_number_is_delete_safe(tenant, subscription):
    """After deleting an invoice, the next number must not reuse an existing one."""
    nums = ['INV-ACME-00001', 'INV-ACME-00002', 'INV-ACME-00003']
    for n in nums:
        Invoice.objects.create(tenant=tenant, subscription=subscription, number=n,
                               status='sent', subtotal=Decimal('1'), total=Decimal('1'))
    Invoice.objects.filter(number='INV-ACME-00002').delete()
    # COUNT()+1 would yield ...00003 (a collision); MAX()+1 yields ...00004.
    assert _next_invoice_number(tenant) == 'INV-ACME-00004'


def test_invoice_line_items_money_is_string(subscription):
    invoice = create_invoice_for_subscription(subscription)
    li = invoice.line_items[0]
    assert li['unit_price'] == '20.00' and li['amount'] == '20.00'
    assert isinstance(li['amount'], str)


# ---------- plan visibility ----------

@pytest.fixture
def hidden_plan(db):
    return Plan.objects.create(name='Internal', slug='internal', is_public=False,
                               is_active=True, price_monthly=Decimal('5.00'), sort_order=9)


def test_plan_list_hides_non_public_from_anonymous(client, plan, hidden_plan):
    resp = client.get(reverse('tenants:plan_list'))
    plans = list(resp.context['plans'])
    assert plan in plans and hidden_plan not in plans


def test_plan_list_shows_non_public_to_super_admin(client, super_user, plan, hidden_plan):
    client.force_login(super_user)
    plans = list(client.get(reverse('tenants:plan_list')).context['plans'])
    assert hidden_plan in plans


def test_plan_detail_non_public_404_for_anonymous(client, hidden_plan):
    assert client.get(reverse('tenants:plan_detail', args=[hidden_plan.pk])).status_code == 404


# ---------- subscription-assign plan restriction ----------

def test_subscription_assign_rejects_non_public_plan(client, tenant_admin, hidden_plan):
    client.force_login(tenant_admin)
    resp = client.post(reverse('tenants:subscription_assign'), {
        'plan': hidden_plan.pk, 'billing_cycle': 'monthly', 'auto_renew': 'on',
    })
    assert resp.status_code == 200                      # form re-rendered with errors
    assert not Subscription.objects.filter(
        tenant=tenant_admin.tenant, plan=hidden_plan).exists()


# ---------- onboarding: no write on GET, trial aligned to chosen plan ----------

def test_onboarding_complete_get_does_not_create(client, plan):
    client.post(reverse('tenants:onboarding_company'),
                {'name': 'Review Co', 'slug': 'review-co', 'timezone': 'UTC'})
    client.post(reverse('tenants:onboarding_plan'),
                {'plan': plan.pk, 'billing_cycle': 'monthly'})
    client.get(reverse('tenants:onboarding_complete'))
    from apps.core.models import Tenant
    assert not Tenant.objects.filter(name='Review Co').exists()


def test_onboarding_post_aligns_trial_to_chosen_plan(client, plan):
    client.post(reverse('tenants:onboarding_company'),
                {'name': 'Trial Co', 'slug': 'trial-co', 'timezone': 'UTC'})
    client.post(reverse('tenants:onboarding_plan'),
                {'plan': plan.pk, 'billing_cycle': 'yearly'})
    client.post(reverse('tenants:onboarding_complete'))
    sub = Subscription.objects.get(tenant__name='Trial Co')
    assert sub.plan == plan and sub.status == 'trial'
    assert sub.trial_ends_at is not None
    # period_end matches the trial window (not stretched to a full paid cycle)
    assert sub.current_period_end == sub.trial_ends_at
    expected = sub.started_at + timedelta(days=plan.trial_days)
    assert abs((sub.trial_ends_at - expected).total_seconds()) < 5
