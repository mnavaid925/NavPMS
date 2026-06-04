"""View tests for Module 13 — Goods Receipt & Inspection (buyer side + vendor portal)."""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.models import set_current_tenant
from apps.goods_receipt.models import GoodsReceipt, ReturnToVendor

pytestmark = pytest.mark.django_db


# ---------- List ----------
class TestList:
    def test_list_200(self, client, buyer_user, draft_grn):
        client.force_login(buyer_user)
        resp = client.get(reverse('goods_receipt:grn_list'))
        assert resp.status_code == 200
        assert draft_grn.grn_number.encode() in resp.content

    def test_status_filter(self, client, buyer_user, draft_grn, posted_grn):
        client.force_login(buyer_user)
        resp = client.get(reverse('goods_receipt:grn_list'), {'status': 'draft'})
        assert draft_grn.grn_number.encode() in resp.content
        assert posted_grn.grn_number.encode() not in resp.content

    def test_search(self, client, buyer_user, draft_grn):
        client.force_login(buyer_user)
        resp = client.get(reverse('goods_receipt:grn_list'), {'q': draft_grn.grn_number})
        assert draft_grn.grn_number.encode() in resp.content

    def test_vendor_filter(self, client, buyer_user, draft_grn):
        client.force_login(buyer_user)
        resp = client.get(reverse('goods_receipt:grn_list'),
                          {'vendor': draft_grn.vendor_id})
        assert resp.status_code == 200


# ---------- Create ----------
class TestCreate:
    def test_get_200(self, client, buyer_user):
        client.force_login(buyer_user)
        assert client.get(reverse('goods_receipt:grn_create')).status_code == 200

    def test_get_from_po(self, client, buyer_user, open_po):
        client.force_login(buyer_user)
        resp = client.get(reverse('goods_receipt:grn_create'), {'from_po': open_po.pk})
        assert resp.status_code == 200

    def test_post_creates(self, client, buyer_user, open_po, tenant):
        client.force_login(buyer_user)
        resp = client.post(reverse('goods_receipt:grn_create'),
                           {'purchase_order': open_po.pk})
        assert resp.status_code == 302
        set_current_tenant(tenant)
        assert GoodsReceipt.all_objects.filter(purchase_order=open_po).exists()


# ---------- Detail / edit / delete ----------
class TestDetailEditDelete:
    def test_detail_200(self, client, buyer_user, inspected_grn):
        client.force_login(buyer_user)
        resp = client.get(reverse('goods_receipt:grn_detail', args=[inspected_grn.pk]))
        assert resp.status_code == 200
        assert inspected_grn.grn_number.encode() in resp.content

    def test_edit_draft_200(self, client, buyer_user, draft_grn):
        client.force_login(buyer_user)
        assert client.get(
            reverse('goods_receipt:grn_edit', args=[draft_grn.pk])).status_code == 200

    def test_edit_blocked_after_received(self, client, buyer_user, received_grn):
        client.force_login(buyer_user)
        resp = client.get(reverse('goods_receipt:grn_edit', args=[received_grn.pk]))
        assert resp.status_code == 302  # redirected to detail

    def test_delete_draft(self, client, buyer_user, draft_grn, tenant):
        client.force_login(buyer_user)
        resp = client.post(reverse('goods_receipt:grn_delete', args=[draft_grn.pk]))
        assert resp.status_code == 302
        set_current_tenant(tenant)
        assert not GoodsReceipt.all_objects.filter(pk=draft_grn.pk).exists()

    def test_delete_blocked_after_received(self, client, buyer_user, received_grn, tenant):
        client.force_login(buyer_user)
        client.post(reverse('goods_receipt:grn_delete', args=[received_grn.pk]))
        set_current_tenant(tenant)
        assert GoodsReceipt.all_objects.filter(pk=received_grn.pk).exists()


# ---------- Lifecycle ----------
class TestLifecycle:
    def test_receive(self, client, buyer_user, draft_grn):
        client.force_login(buyer_user)
        resp = client.post(reverse('goods_receipt:grn_receive', args=[draft_grn.pk]))
        assert resp.status_code == 302
        draft_grn.refresh_from_db()
        assert draft_grn.status == 'received'

    def test_inspect(self, client, buyer_user, received_grn):
        client.force_login(buyer_user)
        data = {'check_no_damage': 'pass', 'inspection_note': 'ok'}
        for ln in received_grn.lines.all():
            data[f'accepted_{ln.id}'] = '6'
            data[f'rejected_{ln.id}'] = '0'
            data[f'discrepancy_{ln.id}'] = 'none'
        resp = client.post(
            reverse('goods_receipt:grn_inspect', args=[received_grn.pk]), data)
        assert resp.status_code == 302
        received_grn.refresh_from_db()
        assert received_grn.status == 'inspected'

    def test_post(self, client, buyer_user, inspected_grn):
        client.force_login(buyer_user)
        resp = client.post(reverse('goods_receipt:grn_post', args=[inspected_grn.pk]))
        assert resp.status_code == 302
        inspected_grn.refresh_from_db()
        assert inspected_grn.status == 'posted'

    def test_post_invalid_when_received(self, client, buyer_user, received_grn):
        client.force_login(buyer_user)
        client.post(reverse('goods_receipt:grn_post', args=[received_grn.pk]))
        received_grn.refresh_from_db()
        assert received_grn.status == 'received'  # unchanged

    def test_close(self, client, buyer_user, posted_grn):
        client.force_login(buyer_user)
        resp = client.post(reverse('goods_receipt:grn_close', args=[posted_grn.pk]))
        assert resp.status_code == 302
        posted_grn.refresh_from_db()
        assert posted_grn.status == 'closed'

    def test_cancel(self, client, buyer_user, draft_grn):
        client.force_login(buyer_user)
        resp = client.post(reverse('goods_receipt:grn_cancel', args=[draft_grn.pk]),
                           {'reason': 'mistake'})
        assert resp.status_code == 302
        draft_grn.refresh_from_db()
        assert draft_grn.status == 'cancelled'


# ---------- Lines ----------
class TestLines:
    def test_line_add(self, client, buyer_user, tenant, tenant_admin, vendor_a):
        from .conftest import make_open_po
        from apps.goods_receipt import services
        set_current_tenant(tenant)
        po = make_open_po(tenant, tenant_admin, vendor_a, number='PO-ACME-70001')
        grn = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po)
        client.force_login(buyer_user)
        pol = po.lines.first()
        resp = client.post(reverse('goods_receipt:line_add', args=[grn.pk]),
                           {'purchase_order_line': pol.pk, 'received_quantity': '3',
                            'discrepancy_type': 'none'})
        assert resp.status_code == 302
        assert grn.lines.count() == 1

    def test_line_delete(self, client, buyer_user, draft_grn):
        client.force_login(buyer_user)
        line = draft_grn.lines.first()
        resp = client.post(
            reverse('goods_receipt:line_delete', args=[draft_grn.pk, line.id]))
        assert resp.status_code == 302
        assert not draft_grn.lines.filter(pk=line.id).exists()


# ---------- Tags ----------
class TestTags:
    def test_tags_print_200(self, client, buyer_user, posted_grn):
        client.force_login(buyer_user)
        resp = client.get(reverse('goods_receipt:tags_print', args=[posted_grn.pk]))
        assert resp.status_code == 200
        assert b'JsBarcode' in resp.content


# ---------- RTV ----------
class TestRTVViews:
    def test_rtv_create(self, client, buyer_user, inspected_grn, tenant):
        client.force_login(buyer_user)
        resp = client.post(reverse('goods_receipt:rtv_create', args=[inspected_grn.pk]),
                           {'reason': 'damaged'})
        assert resp.status_code == 302
        set_current_tenant(tenant)
        assert ReturnToVendor.all_objects.filter(goods_receipt=inspected_grn).exists()

    def test_rtv_authorize_ship(self, client, buyer_user, grn_with_rtv):
        _grn, rtv = grn_with_rtv  # already authorised
        client.force_login(buyer_user)
        resp = client.post(reverse('goods_receipt:rtv_ship', args=[rtv.pk]),
                           {'carrier': 'UPS', 'tracking_number': '1Z'})
        assert resp.status_code == 302
        rtv.refresh_from_db()
        assert rtv.status == 'shipped'

    def test_rtv_detail_200(self, client, buyer_user, grn_with_rtv):
        _grn, rtv = grn_with_rtv
        client.force_login(buyer_user)
        resp = client.get(reverse('goods_receipt:rtv_detail', args=[rtv.pk]))
        assert resp.status_code == 200
        assert rtv.rtv_number.encode() in resp.content


# ---------- Analytics ----------
class TestAnalytics:
    def test_analytics_200(self, client, buyer_user, posted_grn):
        client.force_login(buyer_user)
        resp = client.get(reverse('goods_receipt:analytics_dashboard'))
        assert resp.status_code == 200


# ---------- Permissions ----------
class TestPermissions:
    def test_requester_denied_list(self, client, requester):
        client.force_login(requester)
        resp = client.get(reverse('goods_receipt:grn_list'))
        assert resp.status_code == 302  # redirected away

    def test_approver_can_view_not_manage(self, client, approver, draft_grn):
        client.force_login(approver)
        assert client.get(reverse('goods_receipt:grn_list')).status_code == 200
        # cannot reach create (manage-gated)
        assert client.get(reverse('goods_receipt:grn_create')).status_code == 302

    def test_approver_cannot_post(self, client, approver, inspected_grn):
        client.force_login(approver)
        client.post(reverse('goods_receipt:grn_post', args=[inspected_grn.pk]))
        inspected_grn.refresh_from_db()
        assert inspected_grn.status == 'inspected'  # not posted


# ---------- Vendor portal ----------
class TestVendorPortal:
    def test_portal_list_200(self, client, vendor_portal_user, grn_with_rtv):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse('vendor_portal:returns'))
        assert resp.status_code == 200

    def test_portal_acknowledge(self, client, vendor_portal_user, grn_with_rtv):
        _grn, rtv = grn_with_rtv
        client.force_login(vendor_portal_user)
        resp = client.post(reverse('vendor_portal:rtv_acknowledge', args=[rtv.pk]),
                           {'note': 'ok'})
        assert resp.status_code == 302
        rtv.refresh_from_db()
        assert rtv.acknowledged_at is not None
