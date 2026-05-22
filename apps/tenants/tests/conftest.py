"""Shared fixtures for Module 1 (Tenant & Subscription Management) tests."""
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.core.models import Tenant
from apps.tenants.models import Invoice, Plan, Subscription


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name='Acme Co', slug='acme')


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name='Globex', slug='globex')


@pytest.fixture
def plan(db):
    return Plan.objects.create(
        name='Starter', slug='starter',
        price_monthly=Decimal('20.00'), price_yearly=Decimal('200.00'),
        trial_days=14, sort_order=1,
    )


@pytest.fixture
def super_user(db):
    return User.objects.create_user(
        username='root', password='x', email='root@navpms.local',
        is_superuser=True, is_staff=True, role='super_admin',
    )


@pytest.fixture
def tenant_admin(db, tenant):
    return User.objects.create_user(
        username='admin_acme', password='x', tenant=tenant,
        role='tenant_admin', is_tenant_admin=True,
    )


@pytest.fixture
def member(db, tenant):
    return User.objects.create_user(
        username='bob', password='x', tenant=tenant,
    )


@pytest.fixture
def subscription(db, tenant, plan):
    return Subscription.objects.create(
        tenant=tenant, plan=plan, status='active', billing_cycle='monthly',
    )


@pytest.fixture
def invoice(db, tenant, subscription):
    return Invoice.objects.create(
        tenant=tenant, subscription=subscription, number='INV-ACME-00001',
        status='sent', subtotal=Decimal('20.00'), total=Decimal('20.00'),
    )
