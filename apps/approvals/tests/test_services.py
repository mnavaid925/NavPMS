"""Unit tests for the Module 4 approval workflow engine."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.approvals.models import (
    ApprovalAction, ApprovalDelegation, ApprovalRequest, ApprovalStep,
    ApprovalTask,
)
from apps.approvals.services import (
    act_on_task, cancel_approval, escalate_overdue, match_rule,
    record_action, resolve_approver, start_approval,
)

pytestmark = pytest.mark.django_db


# ---------- routing ----------

def test_match_rule_returns_rule_with_steps(requisition, rule, step):
    assert match_rule(requisition) == rule


def test_match_rule_skips_rule_without_steps(requisition, rule):
    """A rule with no steps cannot route anything."""
    assert match_rule(requisition) is None


# ---------- delegation ----------

def test_resolve_approver_without_delegation(tenant, approver):
    resolved, deleg = resolve_approver(approver, tenant)
    assert resolved == approver and deleg is None


def test_resolve_approver_follows_active_delegation(tenant, approver, requester):
    today = timezone.now().date()
    ApprovalDelegation.all_objects.create(
        tenant=tenant, delegator=approver, delegate=requester,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=1))
    resolved, deleg = resolve_approver(approver, tenant)
    assert resolved == requester and deleg is not None


# ---------- start_approval ----------

def test_start_approval_creates_request_and_task(requisition, requester, rule, step):
    appr = start_approval(requisition, requester)
    assert appr is not None and appr.status == 'pending'
    task = appr.tasks.get()
    assert task.assigned_to == step.approver
    assert task.due_at is not None        # SLA window stamped on activation


def test_start_approval_returns_none_without_rule(requisition, requester):
    assert start_approval(requisition, requester) is None


# ---------- act_on_task ----------

def test_approve_single_step_completes_request(approval_request, approver):
    task = approval_request.active_task
    act_on_task(task, approver, approved=True)
    approval_request.refresh_from_db()
    assert approval_request.status == 'approved'
    approval_request.requisition.refresh_from_db()
    assert approval_request.requisition.status == 'approved'


def test_reject_completes_request_as_rejected(approval_request, approver):
    task = approval_request.active_task
    act_on_task(task, approver, approved=False, comment='no budget')
    approval_request.refresh_from_db()
    assert approval_request.status == 'rejected'
    approval_request.requisition.refresh_from_db()
    assert approval_request.requisition.status == 'rejected'


def test_multi_step_advances_to_next_task(tenant, requisition, requester,
                                          rule, step, approver):
    second = ApprovalStep.all_objects.create(
        tenant=tenant, rule=rule, order=2, name='Director', approver=requester)
    appr = start_approval(requisition, requester)
    first = appr.tasks.order_by('order').first()
    act_on_task(first, approver, approved=True)
    appr.refresh_from_db()
    assert appr.status == 'pending' and appr.current_step == 2


# ---------- cancellation ----------

def test_cancel_approval(approval_request, requester):
    cancel_approval(approval_request.requisition, requester)
    approval_request.refresh_from_db()
    assert approval_request.status == 'cancelled'
    assert approval_request.tasks.filter(status='skipped').exists()


# ---------- escalation ----------

def test_escalate_overdue(approval_request, tenant):
    task = approval_request.active_task
    task.due_at = timezone.now() - timedelta(hours=1)
    task.save(update_fields=['due_at'])
    count = escalate_overdue(tenant)
    task.refresh_from_db()
    assert count == 1 and task.status == 'escalated'
    assert ApprovalAction.all_objects.filter(
        request=approval_request, action='escalated').exists()


def test_escalate_skips_non_overdue(approval_request, tenant):
    assert escalate_overdue(tenant) == 0


def test_run_escalations_command(approval_request):
    from django.core.management import call_command
    task = approval_request.active_task
    task.due_at = timezone.now() - timedelta(hours=1)
    task.save(update_fields=['due_at'])
    call_command('run_escalations')
    task.refresh_from_db()
    assert task.status == 'escalated'


# ---------- history ----------

def test_record_action(approval_request, requester):
    action = record_action(approval_request, 'commented', requester, comment='hi')
    assert action.action == 'commented' and action.comment == 'hi'
