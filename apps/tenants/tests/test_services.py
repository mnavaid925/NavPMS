"""Unit tests for the Module 1 service layer + payment gateway."""
from decimal import Decimal

import pytest

from apps.tenants.gateways import MockGateway, get_gateway
from apps.tenants.models import (
    AuditLog, BrandingSettings, HealthMetric, Invoice, SecuritySettings,
    Subscription, Transaction,
)
from apps.tenants.services import (
    _next_invoice_number, cancel_subscription, charge_invoice,
    compute_tenant_usage, create_invoice_for_subscription, record_audit,
    record_health_metric, start_trial_for_new_tenant,
)

pytestmark = pytest.mark.django_db


# ---------- numbering ----------

def test_next_invoice_number(tenant):
    assert _next_invoice_number(tenant) == 'INV-ACME-00001'


# ---------- trial provisioning ----------

def test_start_trial_provisions_everything(tenant, plan):
    sub = start_trial_for_new_tenant(tenant)
    assert sub.status == 'trial' and sub.plan == plan
    assert BrandingSettings.objects.filter(tenant=tenant).exists()
    assert SecuritySettings.objects.filter(tenant=tenant).exists()
    assert AuditLog.all_objects.filter(
        tenant=tenant, action='tenant.trial_started').exists()


def test_start_trial_creates_free_plan_when_none(tenant):
    """With no Plan in the DB, a Free plan is auto-created."""
    sub = start_trial_for_new_tenant(tenant)
    assert sub.plan.slug == 'free'


# ---------- invoicing ----------

def test_create_invoice_for_subscription(subscription):
    invoice = create_invoice_for_subscription(subscription)
    assert invoice.status == 'sent'
    assert invoice.total == Decimal('20.00')
    assert invoice.subscription == subscription
    assert len(invoice.line_items) == 1


def test_create_invoice_applies_tax(subscription):
    invoice = create_invoice_for_subscription(
        subscription, tax_rate=Decimal('0.10'))
    assert invoice.tax == Decimal('2.00')
    assert invoice.total == Decimal('22.00')


# ---------- charging ----------

def test_charge_invoice_marks_paid(invoice):
    tx = charge_invoice(invoice)
    invoice.refresh_from_db()
    assert tx.status == 'succeeded'
    assert invoice.status == 'paid' and invoice.paid_at is not None


def test_charge_invoice_activates_subscription(invoice, subscription):
    subscription.status = 'trial'
    subscription.save(update_fields=['status'])
    charge_invoice(invoice)
    subscription.refresh_from_db()
    assert subscription.status == 'active'


# ---------- cancellation ----------

def test_cancel_subscription_immediate(subscription):
    cancel_subscription(subscription, immediate=True)
    subscription.refresh_from_db()
    assert subscription.status == 'cancelled'
    assert subscription.cancelled_at is not None and not subscription.auto_renew


def test_cancel_subscription_at_period_end(subscription):
    cancel_subscription(subscription, immediate=False)
    subscription.refresh_from_db()
    assert subscription.cancel_at_period_end and subscription.status == 'active'


# ---------- audit / health ----------

def test_record_audit(tenant, tenant_admin):
    log = record_audit(tenant, tenant_admin, 'thing.happened', level='warning')
    assert log.action == 'thing.happened' and log.level == 'warning'
    assert log.tenant == tenant


def test_record_health_metric(tenant):
    m = record_health_metric(tenant, 'user_count', 7)
    assert m.metric_type == 'user_count' and m.value == Decimal('7')


def test_compute_tenant_usage(tenant, tenant_admin, subscription, invoice):
    usage = compute_tenant_usage(tenant)
    assert usage['user_count'] == 1            # tenant_admin
    assert usage['active_subscriptions'] == 1
    assert usage['open_invoices'] == 1          # invoice status 'sent'


# ---------- gateway ----------

def test_mock_gateway_charge_ok():
    result = MockGateway().charge(
        amount=Decimal('10'), currency='USD', description='x')
    assert result.ok and result.gateway_ref.startswith('mock_')


def test_mock_gateway_refund():
    result = MockGateway().refund(gateway_ref='mock_abc', amount=Decimal('5'))
    assert result.ok


def test_get_gateway_returns_mock():
    assert get_gateway().name == 'mock'
