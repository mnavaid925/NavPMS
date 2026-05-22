"""Shared fixtures for Module 2 (Portal) tests.

Uses the real NavPMS model shapes: `core.Tenant`, `accounts.User`
(tenant-bound), and the `all_objects` (unscoped) manager for direct
object creation outside a request cycle.
"""
from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.models import Tenant
from apps.portal.models import (
    Notification, QuickRequisition, QuickRequisitionItem,
)
from apps.portal.services import next_requisition_number


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name='Acme Co', slug='acme')


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name='Globex', slug='globex')


@pytest.fixture
def user(db, tenant):
    return User.objects.create_user(
        username='alice', password='Welcome@123',
        tenant=tenant, role='tenant_admin', is_tenant_admin=True,
    )


@pytest.fixture
def other_user(db, tenant):
    """A second user inside the *same* tenant (for per-user IDOR tests)."""
    return User.objects.create_user(
        username='bob', password='Welcome@123', tenant=tenant,
    )


@pytest.fixture
def intruder(db, other_tenant):
    """A user in a different tenant (for cross-tenant IDOR tests)."""
    return User.objects.create_user(
        username='mallory', password='Welcome@123', tenant=other_tenant,
    )


@pytest.fixture
def client_logged_in(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def csrf_client(user):
    """Client that enforces CSRF — for the CSRF regression test."""
    c = Client(enforce_csrf_checks=True)
    c.force_login(user)
    return c


@pytest.fixture
def draft_req(tenant, user):
    return QuickRequisition.all_objects.create(
        tenant=tenant, user=user, number=next_requisition_number(tenant),
        title='Stationery', category='office_supplies', status='draft',
    )


@pytest.fixture
def make_item():
    """Factory: add a line item to a requisition."""
    def _make(req, name='Widget', quantity='2', unit_price='10.00'):
        return QuickRequisitionItem.all_objects.create(
            tenant=req.tenant, requisition=req, name=name,
            quantity=Decimal(quantity), unit_price=Decimal(unit_price),
        )
    return _make


@pytest.fixture
def notification(tenant, user):
    return Notification.all_objects.create(
        tenant=tenant, user=user, title='Welcome', category='info',
    )
