"""Access-control + tenant-isolation regression tests for Module 4."""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_rule_create_blocked_for_requester(client, requester):
    """Approval rules are tenant-admin only."""
    client.force_login(requester)
    resp = client.get(reverse('approvals:rule_create'))
    assert resp.status_code == 302
    assert reverse('approvals:rule_create') not in resp['Location']


def test_rule_list_blocked_for_requester(client, requester):
    client.force_login(requester)
    assert client.get(reverse('approvals:rule_list')).status_code == 302


def test_inbox_redirects_anonymous(client):
    resp = client.get(reverse('approvals:inbox'))
    assert resp.status_code == 302 and 'login' in resp['Location'].lower()


def test_task_act_blocked_for_unassigned_user(client, requester, approval_request):
    """A user the task is not assigned to cannot decide it."""
    task = approval_request.active_task
    client.force_login(requester)        # requester is not the approver
    resp = client.post(reverse('approvals:task_act', args=[task.pk]),
                        {'decision': 'approve'})
    assert resp.status_code == 302
    approval_request.refresh_from_db()
    assert approval_request.status == 'pending'


def test_cross_tenant_request_detail_404(client, intruder, approval_request):
    client.force_login(intruder)
    resp = client.get(
        reverse('approvals:request_detail', args=[approval_request.pk]))
    assert resp.status_code == 404


def test_cross_tenant_task_404(client, intruder, approval_request):
    client.force_login(intruder)
    task = approval_request.active_task
    resp = client.get(reverse('approvals:task_detail', args=[task.pk]))
    assert resp.status_code == 404
