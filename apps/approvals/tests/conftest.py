"""Shared fixtures for Module 4 (Approval Workflow Engine) tests."""
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.approvals.models import ApprovalRule, ApprovalStep
from apps.approvals.services import start_approval
from apps.core.models import Tenant
from apps.requisitions.models import Requisition
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
def approver(db, tenant):
    return User.objects.create_user(
        username='approver', password='x', tenant=tenant, role='approver')


@pytest.fixture
def requester(db, tenant):
    return User.objects.create_user(
        username='requester', password='x', tenant=tenant, role='requester')


@pytest.fixture
def intruder(db, other_tenant):
    return User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant)


@pytest.fixture
def requisition(db, tenant, requester):
    return Requisition.all_objects.create(
        tenant=tenant, requested_by=requester,
        number=next_requisition_number(tenant),
        title='Server upgrade', category='it_equipment',
        status='submitted', estimated_total=Decimal('500.00'),
    )


@pytest.fixture
def rule(db, tenant):
    """An always-matching active rule (no amount/department/category bounds)."""
    return ApprovalRule.all_objects.create(
        tenant=tenant, name='Standard routing', document_type='requisition')


@pytest.fixture
def step(db, tenant, rule, approver):
    return ApprovalStep.all_objects.create(
        tenant=tenant, rule=rule, order=1, name='Manager review',
        approver=approver, sla_hours=48)


@pytest.fixture
def approval_request(db, requisition, requester, rule, step):
    """A live, single-step approval request routed from `requisition`."""
    return start_approval(requisition, requester)
