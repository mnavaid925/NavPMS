"""Shared fixtures for Module 3 (Requisition Management) tests."""
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.core.models import Tenant
from apps.requisitions.models import (
    AccountCode, Requisition, RequisitionLine, RequisitionTemplate,
)
from apps.requisitions.services import next_requisition_number


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name='Acme Co', slug='acme')


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name='Globex', slug='globex')


@pytest.fixture
def tenant_admin(db, tenant):
    return User.objects.create_user(
        username='admin_acme', password='x', tenant=tenant,
        role='tenant_admin', is_tenant_admin=True,
    )


@pytest.fixture
def member(db, tenant):
    return User.objects.create_user(
        username='alice', password='x', tenant=tenant, role='requester')


@pytest.fixture
def other_member(db, tenant):
    return User.objects.create_user(
        username='carol', password='x', tenant=tenant, role='requester')


@pytest.fixture
def intruder(db, other_tenant):
    return User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant)


@pytest.fixture
def account_code(db, tenant):
    return AccountCode.all_objects.create(
        tenant=tenant, code='4000', name='Office Expense')


@pytest.fixture
def requisition(db, tenant, member):
    return Requisition.all_objects.create(
        tenant=tenant, requested_by=member,
        number=next_requisition_number(tenant),
        title='Laptop refresh', category='it_equipment', status='draft',
    )


@pytest.fixture
def make_line():
    def _make(req, description='Item', quantity='2', unit_price='25.00'):
        return RequisitionLine.all_objects.create(
            tenant=req.tenant, requisition=req, description=description,
            quantity=Decimal(quantity), unit_price=Decimal(unit_price),
        )
    return _make


@pytest.fixture
def template(db, tenant, member):
    return RequisitionTemplate.all_objects.create(
        tenant=tenant, owner=member, name='Monthly stationery',
        category='office_supplies')
