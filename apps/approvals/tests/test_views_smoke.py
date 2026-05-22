"""Smoke tests for Module 4 — GET renders, edit/delete branches, invalid forms."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.approvals.models import ApprovalDelegation, ApprovalRule, ApprovalStep

pytestmark = pytest.mark.django_db


def test_admin_get_pages_render(client, tenant_admin, rule):
    client.force_login(tenant_admin)
    for url in (
        reverse('approvals:rule_list'),
        reverse('approvals:rule_create'),
        reverse('approvals:rule_detail', args=[rule.pk]),
        reverse('approvals:rule_edit', args=[rule.pk]),
        reverse('approvals:request_list'),
        reverse('approvals:history'),
    ):
        assert client.get(url).status_code == 200


def test_member_get_pages_render(client, approver):
    client.force_login(approver)
    for url in (
        reverse('approvals:inbox'),
        reverse('approvals:delegation_list'),
        reverse('approvals:delegation_create'),
    ):
        assert client.get(url).status_code == 200


def test_rule_edit_updates(client, tenant_admin, rule):
    client.force_login(tenant_admin)
    client.post(reverse('approvals:rule_edit', args=[rule.pk]), {
        'name': 'Renamed rule', 'document_type': 'requisition',
        'priority': '10', 'is_active': 'on', 'category': ''})
    rule.refresh_from_db()
    assert rule.name == 'Renamed rule' and rule.priority == 10


def test_rule_delete(client, tenant_admin, rule):
    client.force_login(tenant_admin)
    client.post(reverse('approvals:rule_delete', args=[rule.pk]))
    assert not ApprovalRule.all_objects.filter(pk=rule.pk).exists()


def test_step_delete(client, tenant_admin, rule, step):
    client.force_login(tenant_admin)
    client.post(reverse('approvals:step_delete', args=[rule.pk, step.pk]))
    assert not ApprovalStep.all_objects.filter(pk=step.pk).exists()


def test_delegation_edit_and_delete(client, approver, requester):
    today = timezone.now().date()
    deleg = ApprovalDelegation.all_objects.create(
        tenant=approver.tenant, delegator=approver, delegate=requester,
        start_date=today, end_date=today + timedelta(days=5))
    client.force_login(approver)
    client.post(reverse('approvals:delegation_edit', args=[deleg.pk]), {
        'delegate': requester.pk, 'start_date': today.isoformat(),
        'end_date': (today + timedelta(days=10)).isoformat(),
        'reason': 'Extended', 'is_active': 'on'})
    deleg.refresh_from_db()
    assert deleg.end_date == today + timedelta(days=10)
    client.post(reverse('approvals:delegation_delete', args=[deleg.pk]))
    assert not ApprovalDelegation.all_objects.filter(pk=deleg.pk).exists()


def test_invalid_rule_create_rerenders(client, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('approvals:rule_create'), {'name': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_request_list_filter(client, tenant_admin, approval_request):
    client.force_login(tenant_admin)
    resp = client.get(reverse('approvals:request_list'),
                      {'q': 'Server', 'status': 'pending'})
    assert approval_request in list(resp.context['requests'])


def test_history_filter(client, tenant_admin, approval_request):
    client.force_login(tenant_admin)
    resp = client.get(reverse('approvals:history'), {'action': 'submitted'})
    assert resp.status_code == 200
    assert all(a.action == 'submitted' for a in resp.context['actions'])


def test_delegation_list_filter(client, approver, requester):
    today = timezone.now().date()
    ApprovalDelegation.all_objects.create(
        tenant=approver.tenant, delegator=approver, delegate=requester,
        start_date=today, end_date=today + timedelta(days=5), is_active=True)
    client.force_login(approver)
    resp = client.get(reverse('approvals:delegation_list'), {'active': 'active'})
    assert resp.status_code == 200 and len(resp.context['delegations']) == 1
