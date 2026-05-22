"""Integration tests for the Quick Requisition Entry flow."""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.portal.models import Notification, QuickRequisition, QuickRequisitionItem
from apps.tenants.models import AuditLog

pytestmark = pytest.mark.django_db


def test_create_requisition_writes_audit(client_logged_in, tenant):
    resp = client_logged_in.post(reverse('portal:requisition_create'), {
        'title': 'Pens', 'category': 'office_supplies',
        'priority': 'normal', 'currency': 'USD',
    })
    assert resp.status_code == 302
    req = QuickRequisition.all_objects.get(tenant=tenant, title='Pens')
    assert req.status == 'draft' and req.number.startswith('QR-')
    assert AuditLog.all_objects.filter(
        tenant=tenant, action='requisition.created', target_id=str(req.id),
    ).exists()


def test_add_item_recomputes_total(client_logged_in, draft_req):
    client_logged_in.post(
        reverse('portal:requisition_item_add', args=[draft_req.pk]),
        {'name': 'Pen', 'quantity': '10', 'unit': 'box', 'unit_price': '6.00'})
    draft_req.refresh_from_db()
    item = draft_req.items.get()
    assert item.line_total == Decimal('60.00')
    assert draft_req.estimated_total == Decimal('60.00')


def test_delete_item_recomputes_total(client_logged_in, draft_req, make_item):
    a = make_item(draft_req, quantity='1', unit_price='10.00')
    make_item(draft_req, quantity='1', unit_price='5.00')
    draft_req.recalc_total()
    client_logged_in.post(reverse(
        'portal:requisition_item_delete', args=[draft_req.pk, a.pk]))
    draft_req.refresh_from_db()
    assert draft_req.estimated_total == Decimal('5.00')


def test_submit_flow(client_logged_in, draft_req, make_item, tenant, user):
    make_item(draft_req)
    resp = client_logged_in.post(
        reverse('portal:requisition_submit', args=[draft_req.pk]))
    assert resp.status_code == 302
    draft_req.refresh_from_db()
    assert draft_req.status == 'submitted' and draft_req.submitted_at is not None
    assert AuditLog.all_objects.filter(
        tenant=tenant, action='requisition.submitted').exists()
    assert Notification.all_objects.filter(
        tenant=tenant, user=user, category='approval').exists()


def test_submit_requires_items(client_logged_in, draft_req):
    resp = client_logged_in.post(
        reverse('portal:requisition_submit', args=[draft_req.pk]), follow=True)
    draft_req.refresh_from_db()
    assert draft_req.status == 'draft'
    assert b'at least one item' in resp.content.lower()


def test_resubmit_is_noop(client_logged_in, draft_req, make_item):
    make_item(draft_req)
    draft_req.status = 'submitted'
    draft_req.save(update_fields=['status'])
    client_logged_in.post(
        reverse('portal:requisition_submit', args=[draft_req.pk]))
    draft_req.refresh_from_db()
    assert draft_req.status == 'submitted'


def test_edit_blocked_on_non_draft(client_logged_in, draft_req):
    draft_req.status = 'submitted'
    draft_req.save(update_fields=['status'])
    resp = client_logged_in.get(
        reverse('portal:requisition_edit', args=[draft_req.pk]))
    assert resp.status_code == 302  # bounced to detail


def test_delete_blocked_on_non_draft(client_logged_in, draft_req):
    draft_req.status = 'approved'
    draft_req.save(update_fields=['status'])
    client_logged_in.post(reverse('portal:requisition_delete', args=[draft_req.pk]))
    assert QuickRequisition.all_objects.filter(pk=draft_req.pk).exists()


def test_item_add_blocked_on_non_draft(client_logged_in, draft_req):
    draft_req.status = 'submitted'
    draft_req.save(update_fields=['status'])
    client_logged_in.post(
        reverse('portal:requisition_item_add', args=[draft_req.pk]),
        {'name': 'Late', 'quantity': '1', 'unit': 'u', 'unit_price': '1.00'})
    assert not QuickRequisitionItem.all_objects.filter(requisition=draft_req).exists()


def test_idor_cross_tenant_404(client, intruder, draft_req):
    client.force_login(intruder)
    resp = client.get(reverse('portal:requisition_detail', args=[draft_req.pk]))
    assert resp.status_code == 404
