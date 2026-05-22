"""Unit tests for Module 4 model logic (rule matching, task state)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.approvals.models import ApprovalDelegation, ApprovalRule, ApprovalTask

pytestmark = pytest.mark.django_db


# ---------- ApprovalRule.matches ----------

def test_rule_matches_when_unbounded(rule, requisition):
    assert rule.matches(requisition)


def test_rule_no_match_below_min_amount(tenant, requisition):
    rule = ApprovalRule.all_objects.create(
        tenant=tenant, name='Big spend', min_amount=Decimal('1000.00'))
    assert not rule.matches(requisition)        # requisition total is 500


def test_rule_no_match_above_max_amount(tenant, requisition):
    rule = ApprovalRule.all_objects.create(
        tenant=tenant, name='Small spend', max_amount=Decimal('100.00'))
    assert not rule.matches(requisition)


def test_rule_matches_category(tenant, requisition):
    rule = ApprovalRule.all_objects.create(
        tenant=tenant, name='IT only', category='it_equipment')
    assert rule.matches(requisition)


def test_rule_no_match_wrong_category(tenant, requisition):
    rule = ApprovalRule.all_objects.create(
        tenant=tenant, name='Travel only', category='travel')
    assert not rule.matches(requisition)


def test_inactive_rule_never_matches(tenant, requisition):
    rule = ApprovalRule.all_objects.create(
        tenant=tenant, name='Off', is_active=False)
    assert not rule.matches(requisition)


# ---------- ApprovalDelegation.is_current ----------

def test_delegation_is_current(tenant, tenant_admin, approver):
    today = timezone.now().date()
    deleg = ApprovalDelegation.all_objects.create(
        tenant=tenant, delegator=tenant_admin, delegate=approver,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=1))
    assert deleg.is_current


def test_delegation_not_current_when_expired(tenant, tenant_admin, approver):
    today = timezone.now().date()
    deleg = ApprovalDelegation.all_objects.create(
        tenant=tenant, delegator=tenant_admin, delegate=approver,
        start_date=today - timedelta(days=10), end_date=today - timedelta(days=5))
    assert not deleg.is_current


# ---------- ApprovalRequest / ApprovalTask ----------

def test_request_active_task_and_progress(approval_request):
    assert approval_request.active_task is not None
    progress = approval_request.progress
    assert progress['total'] == 1 and progress['done'] == 0


def test_task_is_open(approval_request):
    task = approval_request.active_task
    assert task.is_open
    task.status = 'approved'
    assert not task.is_open


def test_task_is_overdue(approval_request):
    task = approval_request.active_task
    task.due_at = timezone.now() - timedelta(hours=1)
    assert task.is_overdue
    task.due_at = timezone.now() + timedelta(hours=1)
    assert not task.is_overdue
