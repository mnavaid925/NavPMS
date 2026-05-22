"""Unit tests for Module 1 model properties."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.tenants.models import Subscription

pytestmark = pytest.mark.django_db


def test_is_trialing_true_when_trial_and_future_end(tenant, plan):
    sub = Subscription.objects.create(
        tenant=tenant, plan=plan, status='trial',
        trial_ends_at=timezone.now() + timedelta(days=5))
    assert sub.is_trialing


def test_is_trialing_false_when_expired(tenant, plan):
    sub = Subscription.objects.create(
        tenant=tenant, plan=plan, status='trial',
        trial_ends_at=timezone.now() - timedelta(days=1))
    assert not sub.is_trialing


def test_is_trialing_false_when_active(subscription):
    assert not subscription.is_trialing


def test_amount_for_cycle_monthly(subscription):
    assert subscription.amount_for_cycle == Decimal('20.00')


def test_amount_for_cycle_yearly(tenant, plan):
    sub = Subscription.objects.create(
        tenant=tenant, plan=plan, status='active', billing_cycle='yearly')
    assert sub.amount_for_cycle == Decimal('200.00')


def test_str_methods(plan, subscription, invoice):
    assert str(plan) == 'Starter'
    assert 'active' in str(subscription)
    assert 'INV-ACME-00001' in str(invoice)
