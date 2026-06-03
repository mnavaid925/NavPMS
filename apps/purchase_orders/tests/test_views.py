"""View tests for Module 11 — Purchase Order Management (buyer side + vendor portal)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import set_current_tenant
from apps.purchase_orders.models import PurchaseOrder, PurchaseOrderChangeOrder

pytestmark = pytest.mark.django_db


def _po_post(vendor=None):
    today = timezone.localdate()
    data = {
        'title': 'Manual purchase order',
        'description': 'desc',
        'currency': 'USD',
        'tax_amount': '0',
        'shipping_amount': '0',
        'order_date': today.isoformat(),
        'expected_delivery_date': (today + timedelta(days=10)).isoformat(),
        'payment_terms': 'Net 30',
    }
    if vendor is not None:
        data['vendor'] = vendor.pk
    return data


def _line_post(n=1):
    return {'line_no': n, 'description': 'New line', 'uom': 'unit',
            'quantity': '3', 'unit_price': '10.00'}


# ---------- List ----------
class TestList:
    def test_list_200(self, client, buyer_user, draft_po):
        client.force_login(buyer_user)
        resp = client.get(reverse('purchase_orders:po_list'))
        assert resp.status_code == 200
        assert draft_po.po_number.encode() in resp.content

    def test_status_filter(self, client, buyer_user, draft_po, issued_po):
        client.force_login(buyer_user)
        resp = client.get(reverse('purchase_orders:po_list'), {'status': 'draft'})
        assert draft_po.po_number.encode() in resp.content
        assert issued_po.po_number.encode() not in resp.content

    def test_vendor_filter(self, client, buyer_user, draft_po, vendor_b, tenant,
                           tenant_admin):
        set_current_tenant(tenant)
        other = PurchaseOrder.all_objects.create(
            tenant=tenant, po_number='PO-ACME-05555', title='vb', vendor=vendor_b,
            created_by=tenant_admin)
        client.force_login(buyer_user)
        resp = client.get(reverse('purchase_orders:po_list'),
                          {'vendor': draft_po.vendor_id})
        assert draft_po.po_number.encode() in resp.content
        assert other.po_number.encode() not in resp.content

    def test_search(self, client, buyer_user, draft_po):
        client.force_login(buyer_user)
        resp = client.get(reverse('purchase_orders:po_list'), {'q': draft_po.po_number})
        assert resp.status_code == 200
        assert draft_po.po_number.encode() in resp.content


# ---------- Create ----------
class TestCreate:
    def test_get_200(self, client, buyer_user):
        client.force_login(buyer_user)
        assert client.get(reverse('purchase_orders:po_create')).status_code == 200

    def test_post_creates(self, client, buyer_user, tenant, vendor_a):
        client.force_login(buyer_user)
        before = PurchaseOrder.all_objects.filter(tenant=tenant).count()
        resp = client.post(reverse('purchase_orders:po_create'), _po_post(vendor_a))
        assert resp.status_code == 302
        assert PurchaseOrder.all_objects.filter(tenant=tenant).count() == before + 1

    def test_post_without_vendor_allowed(self, client, buyer_user, tenant):
        client.force_login(buyer_user)
        resp = client.post(reverse('purchase_orders:po_create'), _po_post())
        assert resp.status_code == 302
        assert PurchaseOrder.all_objects.filter(tenant=tenant, vendor__isnull=True).exists()


class TestCreateFromRequisition:
    def test_from_requisition_creates_and_converts(self, client, buyer_user, tenant,
                                                   approved_requisition):
        client.force_login(buyer_user)
        url = reverse('purchase_orders:po_create')
        resp = client.get(url, {'from_requisition': approved_requisition.pk})
        assert resp.status_code == 302
        po = PurchaseOrder.all_objects.filter(
            tenant=tenant, requisition=approved_requisition).first()
        assert po is not None
        assert po.lines.count() == 2
        approved_requisition.refresh_from_db()
        assert approved_requisition.status == 'converted'

    def test_from_non_approved_requisition_blocked(self, client, buyer_user, tenant,
                                                   tenant_admin, approved_requisition):
        approved_requisition.status = 'draft'
        approved_requisition.save(update_fields=['status'])
        client.force_login(buyer_user)
        resp = client.get(reverse('purchase_orders:po_create'),
                          {'from_requisition': approved_requisition.pk})
        assert resp.status_code == 302
        assert not PurchaseOrder.all_objects.filter(
            requisition=approved_requisition).exists()


# ---------- Detail / edit / delete ----------
class TestDetailEditDelete:
    def test_detail_200(self, client, buyer_user, draft_po):
        client.force_login(buyer_user)
        assert client.get(reverse('purchase_orders:po_detail',
                                  kwargs={'pk': draft_po.pk})).status_code == 200

    def test_edit_draft(self, client, buyer_user, draft_po, vendor_a):
        client.force_login(buyer_user)
        data = _po_post(vendor_a)
        data['title'] = 'Renamed PO'
        resp = client.post(reverse('purchase_orders:po_edit',
                                   kwargs={'pk': draft_po.pk}), data)
        assert resp.status_code == 302
        draft_po.refresh_from_db()
        assert draft_po.title == 'Renamed PO'

    def test_edit_issued_blocked(self, client, buyer_user, issued_po):
        client.force_login(buyer_user)
        resp = client.get(reverse('purchase_orders:po_edit', kwargs={'pk': issued_po.pk}))
        assert resp.status_code == 302  # redirected to detail

    def test_delete_draft(self, client, buyer_user, draft_po):
        client.force_login(buyer_user)
        resp = client.post(reverse('purchase_orders:po_delete', kwargs={'pk': draft_po.pk}))
        assert resp.status_code == 302
        assert not PurchaseOrder.all_objects.filter(pk=draft_po.pk).exists()

    def test_delete_issued_blocked(self, client, buyer_user, issued_po):
        client.force_login(buyer_user)
        client.post(reverse('purchase_orders:po_delete', kwargs={'pk': issued_po.pk}))
        assert PurchaseOrder.all_objects.filter(pk=issued_po.pk).exists()


# ---------- Lines ----------
class TestLines:
    def test_add_line_draft(self, client, buyer_user, draft_po):
        client.force_login(buyer_user)
        before = draft_po.lines.count()
        resp = client.post(reverse('purchase_orders:line_add', kwargs={'pk': draft_po.pk}),
                           _line_post(n=draft_po.lines.count() + 1))
        assert resp.status_code == 302
        assert draft_po.lines.count() == before + 1

    def test_add_line_issued_blocked(self, client, buyer_user, issued_po):
        client.force_login(buyer_user)
        resp = client.post(reverse('purchase_orders:line_add', kwargs={'pk': issued_po.pk}),
                           _line_post(n=9))
        assert resp.status_code == 302  # blocked → redirect to detail

    def test_delete_line_draft(self, client, buyer_user, draft_po):
        client.force_login(buyer_user)
        line = draft_po.lines.first()
        client.post(reverse('purchase_orders:line_delete',
                            kwargs={'pk': draft_po.pk, 'line_pk': line.pk}))
        assert not draft_po.lines.filter(pk=line.pk).exists()

    def test_receive_line(self, client, buyer_user, acknowledged_po):
        client.force_login(buyer_user)
        line = acknowledged_po.lines.order_by('line_no').first()
        client.post(reverse('purchase_orders:line_receive',
                            kwargs={'pk': acknowledged_po.pk, 'line_pk': line.pk}),
                   {'received_quantity': '1'})
        line.refresh_from_db()
        assert line.received_quantity == Decimal('1')


# ---------- Lifecycle ----------
class TestLifecycle:
    def test_issue(self, client, buyer_user, draft_po):
        client.force_login(buyer_user)
        resp = client.post(reverse('purchase_orders:po_issue', kwargs={'pk': draft_po.pk}),
                           {'dispatch_method': 'portal'})
        assert resp.status_code == 302
        draft_po.refresh_from_db()
        assert draft_po.status == 'issued'

    def test_acknowledge(self, client, buyer_user, issued_po):
        client.force_login(buyer_user)
        client.post(reverse('purchase_orders:po_acknowledge', kwargs={'pk': issued_po.pk}), {})
        issued_po.refresh_from_db()
        assert issued_po.status == 'acknowledged'

    def test_decline_and_reopen(self, client, buyer_user, issued_po):
        client.force_login(buyer_user)
        client.post(reverse('purchase_orders:po_decline', kwargs={'pk': issued_po.pk}),
                   {'reason': 'cannot fulfil'})
        issued_po.refresh_from_db()
        assert issued_po.status == 'declined'
        client.post(reverse('purchase_orders:po_reopen', kwargs={'pk': issued_po.pk}))
        issued_po.refresh_from_db()
        assert issued_po.status == 'draft'

    def test_cancel(self, client, buyer_user, issued_po):
        client.force_login(buyer_user)
        client.post(reverse('purchase_orders:po_cancel', kwargs={'pk': issued_po.pk}),
                   {'reason': 'no longer needed'})
        issued_po.refresh_from_db()
        assert issued_po.status == 'cancelled'

    def test_close(self, client, buyer_user, received_po):
        client.force_login(buyer_user)
        client.post(reverse('purchase_orders:po_close', kwargs={'pk': received_po.pk}), {})
        received_po.refresh_from_db()
        assert received_po.status == 'closed'


# ---------- Change orders ----------
class TestChangeOrderViews:
    def test_create_and_apply(self, client, buyer_user, tenant, acknowledged_po):
        client.force_login(buyer_user)
        resp = client.post(
            reverse('purchase_orders:change_order_create', kwargs={'pk': acknowledged_po.pk}),
            {'change_type': 'quantity', 'reason': 'more needed'})
        assert resp.status_code == 302
        co = PurchaseOrderChangeOrder.all_objects.filter(
            purchase_order=acknowledged_po).first()
        assert co is not None
        # save proposed line change via the detail POST
        line = acknowledged_po.lines.order_by('line_no').first()
        client.post(reverse('purchase_orders:change_order_detail',
                            kwargs={'pk': acknowledged_po.pk, 'co_pk': co.pk}),
                   {f'line_{line.id}_quantity': str(line.quantity + Decimal('5'))})
        # apply
        client.post(reverse('purchase_orders:change_order_apply',
                            kwargs={'pk': acknowledged_po.pk, 'co_pk': co.pk}))
        acknowledged_po.refresh_from_db()
        co.refresh_from_db()
        assert co.status == 'applied'
        assert acknowledged_po.revision == 2

    def test_cancel_change_order(self, client, buyer_user, tenant, acknowledged_po):
        client.force_login(buyer_user)
        client.post(
            reverse('purchase_orders:change_order_create', kwargs={'pk': acknowledged_po.pk}),
            {'change_type': 'quantity', 'reason': 'maybe'})
        co = PurchaseOrderChangeOrder.all_objects.filter(
            purchase_order=acknowledged_po).first()
        client.post(reverse('purchase_orders:change_order_cancel',
                            kwargs={'pk': acknowledged_po.pk, 'co_pk': co.pk}))
        co.refresh_from_db()
        assert co.status == 'cancelled'


# ---------- Documents ----------
class TestDocuments:
    def test_add_and_delete_document(self, client, buyer_user, draft_po):
        from django.core.files.uploadedfile import SimpleUploadedFile
        client.force_login(buyer_user)
        f = SimpleUploadedFile('po.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        client.post(reverse('purchase_orders:document_add', kwargs={'pk': draft_po.pk}),
                   {'title': 'Signed PO', 'file': f})
        doc = draft_po.documents.first()
        assert doc is not None
        client.post(reverse('purchase_orders:document_delete',
                            kwargs={'pk': draft_po.pk, 'document_pk': doc.pk}))
        assert not draft_po.documents.filter(pk=doc.pk).exists()


# ---------- Boards ----------
class TestBoards:
    def test_tracking_200(self, client, buyer_user, draft_po, issued_po):
        client.force_login(buyer_user)
        assert client.get(reverse('purchase_orders:po_tracking')).status_code == 200

    def test_analytics_200(self, client, buyer_user, draft_po):
        client.force_login(buyer_user)
        assert client.get(reverse('purchase_orders:analytics_dashboard')).status_code == 200


# ---------- Vendor portal ----------
class TestVendorPortal:
    def test_portal_list_200(self, client, vendor_portal_user, issued_po):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse('vendor_portal:purchase_orders'))
        assert resp.status_code == 200
        assert issued_po.po_number.encode() in resp.content

    def test_portal_detail_200(self, client, vendor_portal_user, issued_po):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse('vendor_portal:purchase_order_detail',
                                  kwargs={'pk': issued_po.pk}))
        assert resp.status_code == 200

    def test_portal_acknowledge(self, client, vendor_portal_user, issued_po):
        client.force_login(vendor_portal_user)
        client.post(reverse('vendor_portal:purchase_order_acknowledge',
                            kwargs={'pk': issued_po.pk}), {})
        issued_po.refresh_from_db()
        assert issued_po.status == 'acknowledged'
        assert issued_po.acknowledged_by_id == vendor_portal_user.pk

    def test_portal_decline(self, client, vendor_portal_user, issued_po):
        client.force_login(vendor_portal_user)
        client.post(reverse('vendor_portal:purchase_order_decline',
                            kwargs={'pk': issued_po.pk}), {'reason': 'out of stock'})
        issued_po.refresh_from_db()
        assert issued_po.status == 'declined'


# ---------- Permissions ----------
class TestPermissions:
    def test_requester_cannot_create(self, client, requester):
        client.force_login(requester)
        resp = client.get(reverse('purchase_orders:po_create'))
        assert resp.status_code == 302  # redirected away (no manage permission)

    def test_approver_can_view_list(self, client, approver, draft_po):
        client.force_login(approver)
        assert client.get(reverse('purchase_orders:po_list')).status_code == 200
