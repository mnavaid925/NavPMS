"""Access-control + tenant-isolation regression tests for Module 3."""
import pytest
from django.urls import reverse

from apps.requisitions.models import Requisition
from apps.requisitions.services import next_requisition_number

pytestmark = pytest.mark.django_db


def test_account_code_create_blocked_for_member(client, member):
    """Account-code master data is tenant-admin only."""
    client.force_login(member)
    resp = client.get(reverse('requisitions:account_code_create'))
    assert resp.status_code == 302
    assert reverse('requisitions:account_code_create') not in resp['Location']


def test_decide_blocked_for_member(client, member, requisition):
    """A plain member cannot approve/reject — decide is tenant-admin only."""
    requisition.status = 'submitted'
    requisition.save(update_fields=['status'])
    client.force_login(member)
    resp = client.post(
        reverse('requisitions:requisition_decide', args=[requisition.pk]),
        {'decision': 'approve'})
    assert resp.status_code == 302
    requisition.refresh_from_db()
    assert requisition.status == 'submitted'


def test_requisition_list_redirects_anonymous(client):
    resp = client.get(reverse('requisitions:requisition_list'))
    assert resp.status_code == 302 and 'login' in resp['Location'].lower()


def test_cross_tenant_requisition_404(client, intruder, requisition):
    client.force_login(intruder)
    resp = client.get(
        reverse('requisitions:requisition_detail', args=[requisition.pk]))
    assert resp.status_code == 404


def test_member_cannot_edit_another_users_draft(client, other_member, requisition):
    """can_modify_requisition blocks a non-requester member from editing."""
    client.force_login(other_member)
    resp = client.get(
        reverse('requisitions:requisition_edit', args=[requisition.pk]))
    assert resp.status_code == 302
    assert reverse('requisitions:requisition_detail',
                   args=[requisition.pk]) in resp['Location']


def test_cross_tenant_line_delete_404(client, member, requisition, other_tenant):
    """A line from another requisition cannot be deleted through this one."""
    from apps.accounts.models import User
    from apps.requisitions.models import RequisitionLine
    foreign_user = User.objects.create_user(
        username='ext', password='x', tenant=other_tenant)
    foreign_req = Requisition.all_objects.create(
        tenant=other_tenant, requested_by=foreign_user,
        number=next_requisition_number(other_tenant), title='Foreign')
    foreign_line = RequisitionLine.all_objects.create(
        tenant=other_tenant, requisition=foreign_req, description='x')
    client.force_login(member)
    resp = client.post(reverse(
        'requisitions:requisition_line_delete',
        args=[requisition.pk, foreign_line.pk]))
    assert resp.status_code == 404
