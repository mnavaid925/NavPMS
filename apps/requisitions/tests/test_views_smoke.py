"""Smoke tests for Module 3 — GET renders, edit/delete branches, invalid forms."""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.requisitions.models import (
    AccountCode, Requisition, RequisitionTemplate, RequisitionTemplateLine,
)

pytestmark = pytest.mark.django_db


def test_admin_get_pages_render(client, tenant_admin, account_code):
    client.force_login(tenant_admin)
    for url in (
        reverse('requisitions:account_code_list'),
        reverse('requisitions:account_code_create'),
        reverse('requisitions:account_code_edit', args=[account_code.pk]),
    ):
        assert client.get(url).status_code == 200


def test_member_get_pages_render(client, member, requisition, template):
    client.force_login(member)
    for url in (
        reverse('requisitions:requisition_list'),
        reverse('requisitions:requisition_create'),
        reverse('requisitions:requisition_detail', args=[requisition.pk]),
        reverse('requisitions:requisition_edit', args=[requisition.pk]),
        reverse('requisitions:template_list'),
        reverse('requisitions:template_create'),
        reverse('requisitions:template_detail', args=[template.pk]),
        reverse('requisitions:template_edit', args=[template.pk]),
    ):
        assert client.get(url).status_code == 200


def test_account_code_edit_and_delete(client, tenant_admin, account_code):
    client.force_login(tenant_admin)
    client.post(reverse('requisitions:account_code_edit', args=[account_code.pk]), {
        'code': account_code.code, 'name': 'Renamed', 'is_active': 'on'})
    account_code.refresh_from_db()
    assert account_code.name == 'Renamed'
    client.post(reverse('requisitions:account_code_delete', args=[account_code.pk]))
    assert not AccountCode.all_objects.filter(pk=account_code.pk).exists()


def test_account_code_delete_blocked_when_in_use(client, tenant_admin,
                                                 account_code, requisition, make_line):
    line = make_line(requisition)
    line.account_code = account_code
    line.save()
    client.force_login(tenant_admin)
    client.post(reverse('requisitions:account_code_delete', args=[account_code.pk]))
    assert AccountCode.all_objects.filter(pk=account_code.pk).exists()


def test_template_edit_and_delete(client, member, template):
    client.force_login(member)
    client.post(reverse('requisitions:template_edit', args=[template.pk]), {
        'name': 'Renamed template', 'category': 'office_supplies'})
    template.refresh_from_db()
    assert template.name == 'Renamed template'
    client.post(reverse('requisitions:template_delete', args=[template.pk]))
    assert not RequisitionTemplate.all_objects.filter(pk=template.pk).exists()


def test_template_line_delete(client, member, template):
    line = RequisitionTemplateLine.all_objects.create(
        tenant=template.tenant, template=template, description='X',
        quantity=Decimal('1'), estimated_unit_price=Decimal('1.00'))
    client.force_login(member)
    client.post(reverse('requisitions:template_line_delete',
                        args=[template.pk, line.pk]))
    assert not RequisitionTemplateLine.all_objects.filter(pk=line.pk).exists()


def test_requisition_delete_draft(client, member, requisition):
    client.force_login(member)
    client.post(reverse('requisitions:requisition_delete', args=[requisition.pk]))
    assert not Requisition.all_objects.filter(pk=requisition.pk).exists()


def test_requisition_edit_updates(client, member, requisition):
    client.force_login(member)
    client.post(reverse('requisitions:requisition_edit', args=[requisition.pk]), {
        'title': 'Updated title', 'category': 'it_equipment',
        'priority': 'high', 'currency': 'USD'})
    requisition.refresh_from_db()
    assert requisition.title == 'Updated title' and requisition.priority == 'high'


def test_invalid_requisition_create_rerenders(client, member):
    client.force_login(member)
    resp = client.post(reverse('requisitions:requisition_create'), {'title': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_invalid_account_code_create_rerenders(client, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('requisitions:account_code_create'), {'code': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_invalid_template_create_rerenders(client, member):
    client.force_login(member)
    resp = client.post(reverse('requisitions:template_create'), {'name': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_requisition_list_filters(client, member, requisition):
    client.force_login(member)
    resp = client.get(reverse('requisitions:requisition_list'), {
        'q': 'Laptop', 'status': 'draft', 'category': 'it_equipment',
        'scope': 'mine'})
    assert list(resp.context['requisitions']) == [requisition]


def test_account_code_list_filter(client, tenant_admin, account_code):
    client.force_login(tenant_admin)
    resp = client.get(reverse('requisitions:account_code_list'),
                      {'q': '4000', 'active': 'active'})
    assert list(resp.context['account_codes']) == [account_code]
