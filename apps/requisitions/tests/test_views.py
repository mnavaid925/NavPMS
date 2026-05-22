"""Integration tests for Module 3 views."""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.requisitions.models import (
    AccountCode, Requisition, RequisitionLine, RequisitionTemplate,
    RequisitionTemplateLine,
)
from apps.tenants.models import AuditLog

pytestmark = pytest.mark.django_db


# ---------- Account codes ----------

def test_account_code_create(client, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('requisitions:account_code_create'), {
        'code': '5000', 'name': 'Travel', 'description': '', 'is_active': 'on',
    })
    assert resp.status_code == 302
    assert AccountCode.all_objects.filter(
        tenant=tenant_admin.tenant, code='5000').exists()


def test_account_code_list(client, tenant_admin, account_code):
    client.force_login(tenant_admin)
    assert client.get(
        reverse('requisitions:account_code_list')).status_code == 200


def test_account_code_duplicate_rejected(client, tenant_admin, account_code):
    """clean_code surfaces the unique_together clash as a form error, not a 500."""
    client.force_login(tenant_admin)
    resp = client.post(reverse('requisitions:account_code_create'), {
        'code': account_code.code, 'name': 'Dup', 'is_active': 'on',
    })
    assert resp.status_code == 200
    assert resp.context['form'].errors.get('code')


# ---------- Templates ----------

def test_template_create_and_use(client, member, account_code):
    client.force_login(member)
    resp = client.post(reverse('requisitions:template_create'), {
        'name': 'Recurring', 'category': 'office_supplies',
    })
    assert resp.status_code == 302
    tpl = RequisitionTemplate.all_objects.get(name='Recurring')
    RequisitionTemplateLine.all_objects.create(
        tenant=tpl.tenant, template=tpl, description='Pens',
        quantity=Decimal('3'), estimated_unit_price=Decimal('2.00'))
    resp = client.post(reverse('requisitions:template_use', args=[tpl.pk]))
    assert resp.status_code == 302
    req = Requisition.all_objects.get(created_from_template=tpl)
    assert req.lines.count() == 1


def test_template_line_add(client, member, template):
    client.force_login(member)
    client.post(reverse('requisitions:template_line_add', args=[template.pk]), {
        'description': 'Folders', 'quantity': '10', 'unit': 'box',
        'estimated_unit_price': '3.00',
    })
    assert template.lines.count() == 1


# ---------- Requisitions ----------

def test_requisition_create_writes_event_and_audit(client, member):
    client.force_login(member)
    resp = client.post(reverse('requisitions:requisition_create'), {
        'title': 'New chairs', 'category': 'office_supplies',
        'priority': 'normal', 'currency': 'USD',
    })
    assert resp.status_code == 302
    req = Requisition.all_objects.get(title='New chairs')
    assert req.status == 'draft'
    assert req.status_events.filter(to_status='draft').exists()
    assert AuditLog.all_objects.filter(
        tenant=member.tenant, action='requisition.created').exists()


def test_requisition_list_and_tracking(client, member, requisition):
    client.force_login(member)
    assert client.get(reverse('requisitions:requisition_list')).status_code == 200
    resp = client.get(reverse('requisitions:tracking'))
    assert resp.status_code == 200
    assert resp.context['total_count'] == 1


def test_line_add_recomputes_total(client, member, requisition):
    client.force_login(member)
    client.post(reverse('requisitions:requisition_line_add', args=[requisition.pk]), {
        'description': 'Desk', 'quantity': '2', 'unit': 'unit',
        'unit_price': '150.00',
    })
    requisition.refresh_from_db()
    assert requisition.estimated_total == Decimal('300.00')


def test_submit_requisition_flow(client, member, requisition, make_line):
    make_line(requisition)
    client.force_login(member)
    resp = client.post(
        reverse('requisitions:requisition_submit', args=[requisition.pk]))
    assert resp.status_code == 302
    requisition.refresh_from_db()
    assert requisition.status == 'submitted'


def test_submit_requires_lines(client, member, requisition):
    client.force_login(member)
    client.post(reverse('requisitions:requisition_submit', args=[requisition.pk]))
    requisition.refresh_from_db()
    assert requisition.status == 'draft'


def test_decide_approve(client, tenant_admin, requisition, make_line):
    make_line(requisition)
    requisition.status = 'submitted'
    requisition.save(update_fields=['status'])
    client.force_login(tenant_admin)
    client.post(reverse('requisitions:requisition_decide', args=[requisition.pk]),
                {'decision': 'approve', 'note': 'fine'})
    requisition.refresh_from_db()
    assert requisition.status == 'approved'


def test_cancel_requisition(client, member, requisition):
    client.force_login(member)
    client.post(reverse('requisitions:requisition_cancel', args=[requisition.pk]))
    requisition.refresh_from_db()
    assert requisition.status == 'cancelled'


def test_amend_requisition(client, member, requisition):
    requisition.status = 'approved'
    requisition.save(update_fields=['status'])
    client.force_login(member)
    client.post(reverse('requisitions:requisition_amend', args=[requisition.pk]))
    requisition.refresh_from_db()
    assert requisition.status == 'draft' and requisition.revision == 2


def test_convert_requisition(client, tenant_admin, requisition):
    requisition.status = 'approved'
    requisition.save(update_fields=['status'])
    client.force_login(tenant_admin)
    client.post(reverse('requisitions:requisition_convert', args=[requisition.pk]),
                {'po_reference': 'PO-555'})
    requisition.refresh_from_db()
    assert requisition.status == 'converted' and requisition.po_reference == 'PO-555'
