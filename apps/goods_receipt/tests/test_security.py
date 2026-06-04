"""Security tests for Module 13 — Goods Receipt & Inspection.

Aligned with OWASP Top 10: A01 broken access control (cross-tenant IDOR, cross-vendor),
A03 injection/XSS, A04 insecure design (lifecycle guards), A05 misconfiguration
(anonymous access).
"""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.models import set_current_tenant
from apps.goods_receipt.models import GoodsReceipt

pytestmark = pytest.mark.django_db


# ---------- A01: cross-tenant IDOR ----------
class TestCrossTenantIDOR:
    def test_detail_404_for_intruder(self, client, intruder, draft_grn):
        client.force_login(intruder)
        resp = client.get(reverse('goods_receipt:grn_detail', args=[draft_grn.pk]))
        assert resp.status_code == 404

    def test_edit_404_for_intruder(self, client, intruder, draft_grn):
        client.force_login(intruder)
        assert client.get(
            reverse('goods_receipt:grn_edit', args=[draft_grn.pk])).status_code == 404

    def test_delete_404_for_intruder(self, client, intruder, draft_grn, tenant):
        client.force_login(intruder)
        resp = client.post(reverse('goods_receipt:grn_delete', args=[draft_grn.pk]))
        assert resp.status_code == 404
        set_current_tenant(tenant)
        assert GoodsReceipt.all_objects.filter(pk=draft_grn.pk).exists()

    def test_post_404_for_intruder(self, client, intruder, inspected_grn):
        client.force_login(intruder)
        resp = client.post(reverse('goods_receipt:grn_post', args=[inspected_grn.pk]))
        assert resp.status_code == 404
        inspected_grn.refresh_from_db()
        assert inspected_grn.status == 'inspected'

    def test_inspect_404_for_intruder(self, client, intruder, received_grn):
        client.force_login(intruder)
        resp = client.post(reverse('goods_receipt:grn_inspect', args=[received_grn.pk]))
        assert resp.status_code == 404

    def test_rtv_detail_404_for_intruder(self, client, intruder, grn_with_rtv):
        _grn, rtv = grn_with_rtv
        client.force_login(intruder)
        assert client.get(
            reverse('goods_receipt:rtv_detail', args=[rtv.pk])).status_code == 404

    def test_list_excludes_other_tenant(self, client, intruder, draft_grn):
        client.force_login(intruder)
        resp = client.get(reverse('goods_receipt:grn_list'))
        assert draft_grn.grn_number.encode() not in resp.content


# ---------- A01: cross-vendor (portal) ----------
class TestCrossVendor:
    def test_vendor_b_cannot_see_vendor_a_rtv(self, client, vendor_b_portal_user,
                                             grn_with_rtv):
        _grn, rtv = grn_with_rtv  # belongs to vendor_a
        client.force_login(vendor_b_portal_user)
        assert client.get(
            reverse('vendor_portal:rtv_detail', args=[rtv.pk])).status_code == 404

    def test_vendor_b_cannot_acknowledge(self, client, vendor_b_portal_user, grn_with_rtv):
        _grn, rtv = grn_with_rtv
        client.force_login(vendor_b_portal_user)
        resp = client.post(reverse('vendor_portal:rtv_acknowledge', args=[rtv.pk]))
        assert resp.status_code == 404
        rtv.refresh_from_db()
        assert rtv.acknowledged_at is None

    def test_draft_rtv_not_visible_to_vendor(self, client, vendor_portal_user,
                                            inspected_grn, tenant_admin):
        from apps.goods_receipt import services
        rtv = services.create_rtv_from_rejections(inspected_grn, tenant_admin)  # draft
        client.force_login(vendor_portal_user)
        # draft is not in the portal list, and the detail view bounces it
        resp = client.get(reverse('vendor_portal:returns'))
        assert rtv.rtv_number.encode() not in resp.content


# ---------- A03: XSS / injection ----------
class TestXSS:
    def test_cancel_reason_escaped(self, client, buyer_user, draft_grn, tenant):
        client.force_login(buyer_user)
        client.post(reverse('goods_receipt:grn_cancel', args=[draft_grn.pk]),
                    {'reason': '<script>alert(1)</script>'})
        resp = client.get(reverse('goods_receipt:grn_detail', args=[draft_grn.pk]))
        assert b'<script>alert(1)</script>' not in resp.content


# ---------- A04: insecure design (lifecycle guards) ----------
class TestDesignGuards:
    def test_cannot_post_non_inspected(self, client, buyer_user, received_grn):
        client.force_login(buyer_user)
        client.post(reverse('goods_receipt:grn_post', args=[received_grn.pk]))
        received_grn.refresh_from_db()
        assert received_grn.status == 'received'

    def test_cannot_cancel_posted(self, client, buyer_user, posted_grn):
        client.force_login(buyer_user)
        client.post(reverse('goods_receipt:grn_cancel', args=[posted_grn.pk]),
                    {'reason': 'no'})
        posted_grn.refresh_from_db()
        assert posted_grn.status == 'posted'

    def test_double_post_keeps_po_quantity(self, client, buyer_user, posted_grn):
        po = posted_grn.purchase_order
        before = {l.id: l.received_quantity for l in po.lines.all()}
        client.force_login(buyer_user)
        client.post(reverse('goods_receipt:grn_post', args=[posted_grn.pk]))
        for pol in po.lines.all():
            assert pol.received_quantity == before[pol.id]


# ---------- A05: anonymous access ----------
class TestAnonymous:
    def test_anonymous_redirected_to_login(self, client, draft_grn):
        resp = client.get(reverse('goods_receipt:grn_list'))
        assert resp.status_code == 302
        assert '/accounts/login' in resp.url

    def test_vendor_user_bounced_from_buyer_surface(self, client, vendor_portal_user,
                                                   draft_grn):
        client.force_login(vendor_portal_user)
        # vendor users hold no manage/view role -> redirected away from the buyer list
        resp = client.get(reverse('goods_receipt:grn_list'))
        assert resp.status_code == 302
