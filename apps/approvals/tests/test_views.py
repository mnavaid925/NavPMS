"""Integration tests for Module 4 views."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.approvals.models import (
    ApprovalDelegation, ApprovalRule, ApprovalStep,
)

pytestmark = pytest.mark.django_db


# ---------- Rules ----------

def test_rule_create(client, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('approvals:rule_create'), {
        'name': 'High value', 'document_type': 'requisition',
        'priority': '50', 'is_active': 'on', 'category': '',
    })
    assert resp.status_code == 302
    assert ApprovalRule.all_objects.filter(name='High value').exists()


def test_rule_list_and_detail(client, tenant_admin, rule):
    client.force_login(tenant_admin)
    assert client.get(reverse('approvals:rule_list')).status_code == 200
    assert client.get(
        reverse('approvals:rule_detail', args=[rule.pk])).status_code == 200


def test_step_add(client, tenant_admin, rule, approver):
    client.force_login(tenant_admin)
    client.post(reverse('approvals:step_add', args=[rule.pk]), {
        'order': '1', 'name': 'Manager', 'approver': approver.pk,
        'sla_hours': '24',
    })
    assert rule.steps.count() == 1


def test_rule_delete_blocked_with_requests(client, tenant_admin, approval_request):
    rule = approval_request.rule
    client.force_login(tenant_admin)
    client.post(reverse('approvals:rule_delete', args=[rule.pk]))
    assert ApprovalRule.all_objects.filter(pk=rule.pk).exists()


# ---------- Delegations ----------

def test_delegation_create(client, approver, requester):
    client.force_login(approver)
    today = timezone.now().date()
    resp = client.post(reverse('approvals:delegation_create'), {
        'delegate': requester.pk,
        'start_date': today.isoformat(),
        'end_date': (today + timedelta(days=7)).isoformat(),
        'reason': 'Vacation', 'is_active': 'on',
    })
    assert resp.status_code == 302
    assert ApprovalDelegation.all_objects.filter(
        delegator=approver, delegate=requester).exists()


def test_delegation_rejects_end_before_start(client, approver, requester):
    client.force_login(approver)
    today = timezone.now().date()
    resp = client.post(reverse('approvals:delegation_create'), {
        'delegate': requester.pk,
        'start_date': today.isoformat(),
        'end_date': (today - timedelta(days=3)).isoformat(),
        'is_active': 'on',
    })
    assert resp.status_code == 200
    assert resp.context['form'].errors.get('end_date')


# ---------- Requests ----------

def test_request_list_and_detail(client, tenant_admin, approval_request):
    client.force_login(tenant_admin)
    assert client.get(reverse('approvals:request_list')).status_code == 200
    assert client.get(
        reverse('approvals:request_detail', args=[approval_request.pk])
    ).status_code == 200


# ---------- Inbox / tasks ----------

def test_inbox_lists_assigned_tasks(client, approver, approval_request):
    client.force_login(approver)
    resp = client.get(reverse('approvals:inbox'))
    assert resp.status_code == 200
    assert approval_request.active_task in list(resp.context['open_tasks'])


def test_task_act_approve(client, approver, approval_request):
    task = approval_request.active_task
    client.force_login(approver)
    resp = client.post(reverse('approvals:task_act', args=[task.pk]),
                        {'decision': 'approve', 'comment': 'ok'})
    assert resp.status_code == 302
    approval_request.refresh_from_db()
    assert approval_request.status == 'approved'


def test_task_act_reject(client, approver, approval_request):
    task = approval_request.active_task
    client.force_login(approver)
    client.post(reverse('approvals:task_act', args=[task.pk]),
                {'decision': 'reject', 'comment': 'no'})
    approval_request.refresh_from_db()
    assert approval_request.status == 'rejected'


def test_task_detail_renders(client, approver, approval_request):
    client.force_login(approver)
    task = approval_request.active_task
    assert client.get(
        reverse('approvals:task_detail', args=[task.pk])).status_code == 200


def test_task_comment(client, approver, approval_request):
    task = approval_request.active_task
    client.force_login(approver)
    client.post(reverse('approvals:task_comment', args=[task.pk]),
                {'comment': 'Looks fine'})
    assert approval_request.actions.filter(action='commented').exists()


def test_history_renders(client, tenant_admin, approval_request):
    client.force_login(tenant_admin)
    assert client.get(reverse('approvals:history')).status_code == 200
