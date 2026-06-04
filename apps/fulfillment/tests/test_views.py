"""View-level tests: auth, permission gates, list filters/search/pagination, CRUD,
lifecycle POSTs, draft-only guards and the backorder board."""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.models import set_current_tenant
from apps.fulfillment import services as fs
from apps.fulfillment.models import Backorder, Shipment

pytestmark = pytest.mark.django_db


class TestAuthAndGates:
    def test_login_required(self, client):
        resp = client.get(reverse('fulfillment:shipment_list'))
        assert resp.status_code == 302
        assert '/accounts/login' in resp.url

    def test_requester_denied(self, client, requester):
        client.force_login(requester)
        resp = client.get(reverse('fulfillment:shipment_list'))
        assert resp.status_code == 302  # bounced by _require_view

    def test_approver_can_view(self, client, approver, draft_shipment):
        client.force_login(approver)
        resp = client.get(reverse('fulfillment:shipment_list'))
        assert resp.status_code == 200
        assert resp.context['can_manage'] is False

    def test_buyer_can_manage(self, client, buyer_user):
        client.force_login(buyer_user)
        resp = client.get(reverse('fulfillment:shipment_list'))
        assert resp.status_code == 200
        assert resp.context['can_manage'] is True


class TestList:
    def test_status_filter(self, client, tenant, tenant_admin, draft_shipment,
                           advised_shipment):
        client.force_login(tenant_admin)
        resp = client.get(reverse('fulfillment:shipment_list'), {'status': 'advised'})
        assert resp.status_code == 200
        nums = {s.shipment_number for s in resp.context['shipments']}
        assert advised_shipment.shipment_number in nums
        assert draft_shipment.shipment_number not in nums

    def test_search(self, client, tenant_admin, draft_shipment):
        client.force_login(tenant_admin)
        resp = client.get(reverse('fulfillment:shipment_list'),
                          {'q': draft_shipment.shipment_number})
        assert resp.status_code == 200
        assert len(resp.context['shipments']) == 1

    def test_pagination_context(self, client, tenant_admin, draft_shipment):
        client.force_login(tenant_admin)
        resp = client.get(reverse('fulfillment:shipment_list'))
        assert 'page_obj' in resp.context


class TestCrud:
    def test_create(self, client, tenant, tenant_admin, issued_po):
        client.force_login(tenant_admin)
        resp = client.post(reverse('fulfillment:shipment_create'), {
            'purchase_order': issued_po.pk, 'package_count': 1,
            'total_weight': '5.00', 'weight_uom': 'kg', 'freight_cost': '10.00',
        })
        assert resp.status_code == 302
        assert Shipment.all_objects.filter(tenant=tenant, purchase_order=issued_po).exists()

    def test_edit_draft(self, client, tenant_admin, draft_shipment):
        client.force_login(tenant_admin)
        resp = client.post(
            reverse('fulfillment:shipment_edit', args=[draft_shipment.pk]), {
                'package_count': 3, 'total_weight': '7.00', 'weight_uom': 'kg',
                'freight_cost': '12.00', 'carrier': 'New Carrier',
            })
        assert resp.status_code == 302
        draft_shipment.refresh_from_db()
        assert draft_shipment.carrier == 'New Carrier'

    def test_cannot_edit_advised(self, client, tenant_admin, advised_shipment):
        client.force_login(tenant_admin)
        resp = client.get(reverse('fulfillment:shipment_edit', args=[advised_shipment.pk]))
        assert resp.status_code == 302  # redirected with error

    def test_delete_draft(self, client, tenant_admin, draft_shipment):
        client.force_login(tenant_admin)
        resp = client.post(reverse('fulfillment:shipment_delete', args=[draft_shipment.pk]))
        assert resp.status_code == 302
        assert not Shipment.all_objects.filter(pk=draft_shipment.pk).exists()

    def test_cannot_delete_advised(self, client, tenant_admin, advised_shipment):
        client.force_login(tenant_admin)
        resp = client.post(reverse('fulfillment:shipment_delete', args=[advised_shipment.pk]))
        assert resp.status_code == 302
        assert Shipment.all_objects.filter(pk=advised_shipment.pk).exists()

    def test_line_add(self, client, tenant_admin, draft_shipment, issued_po):
        client.force_login(tenant_admin)
        gadget = issued_po.lines.order_by('line_no')[1]
        resp = client.post(
            reverse('fulfillment:line_add', args=[draft_shipment.pk]), {
                'purchase_order_line': gadget.pk, 'shipped_quantity': '2',
            })
        assert resp.status_code == 302
        assert draft_shipment.lines.count() == 2


class TestLifecycle:
    def test_advise(self, client, tenant_admin, draft_shipment):
        client.force_login(tenant_admin)
        resp = client.post(reverse('fulfillment:shipment_advise', args=[draft_shipment.pk]))
        assert resp.status_code == 302
        draft_shipment.refresh_from_db()
        assert draft_shipment.status == 'advised'

    def test_sync_tracking(self, client, tenant_admin, advised_shipment):
        client.force_login(tenant_admin)
        resp = client.post(
            reverse('fulfillment:shipment_sync_tracking', args=[advised_shipment.pk]))
        assert resp.status_code == 302
        advised_shipment.refresh_from_db()
        assert advised_shipment.status in ('in_transit', 'out_for_delivery', 'delivered')

    def test_confirm_delivery_posts(self, client, tenant, tenant_admin,
                                    advised_shipment, issued_po):
        client.force_login(tenant_admin)
        resp = client.post(
            reverse('fulfillment:shipment_confirm_delivery', args=[advised_shipment.pk]),
            {'received_condition': 'good', 'post_receipt': 'on'})
        assert resp.status_code == 302
        advised_shipment.refresh_from_db()
        assert advised_shipment.status == 'received'
        po_line = issued_po.lines.order_by('line_no').first()
        po_line.refresh_from_db()
        assert po_line.received_quantity == Decimal('4.00')

    def test_cancel(self, client, tenant_admin, advised_shipment):
        client.force_login(tenant_admin)
        resp = client.post(
            reverse('fulfillment:shipment_cancel', args=[advised_shipment.pk]),
            {'reason': 'cancel it'})
        assert resp.status_code == 302
        advised_shipment.refresh_from_db()
        assert advised_shipment.status == 'cancelled'


class TestBackorderViews:
    def test_board(self, client, approver, draft_shipment):
        client.force_login(approver)
        resp = client.get(reverse('fulfillment:backorder_board'))
        assert resp.status_code == 200
        assert 'board' in resp.context

    def test_create_and_fulfill(self, client, tenant, tenant_admin, issued_po,
                                draft_shipment):
        client.force_login(tenant_admin)
        line = issued_po.lines.first()
        resp = client.post(reverse('fulfillment:backorder_create'), {
            'purchase_order_line': line.pk, 'quantity': '3',
        })
        assert resp.status_code == 302
        bo = Backorder.all_objects.filter(tenant=tenant).first()
        assert bo is not None and bo.status == 'open'
        resp = client.post(reverse('fulfillment:backorder_fulfill', args=[bo.pk]))
        assert resp.status_code == 302
        bo.refresh_from_db()
        assert bo.status == 'fulfilled'

    def test_tracking_board_and_analytics(self, client, tenant_admin, draft_shipment):
        client.force_login(tenant_admin)
        assert client.get(reverse('fulfillment:tracking_board')).status_code == 200
        assert client.get(reverse('fulfillment:analytics_dashboard')).status_code == 200


class TestLineNumbering:
    def test_no_line_no_collision_after_delete(self, client, tenant_admin, issued_po,
                                               draft_shipment):
        """Add a 2nd line, delete the 1st, re-add — line_no must come from Max+1
        (not count+1) so the re-add does not collide and 500 (fix #4)."""
        client.force_login(tenant_admin)
        widget_sl = draft_shipment.lines.get(line_no=1)             # widget, qty 4
        gadget = issued_po.lines.order_by('line_no')[1]
        client.post(reverse('fulfillment:line_add', args=[draft_shipment.pk]),
                    {'purchase_order_line': gadget.pk, 'shipped_quantity': '2'})
        assert draft_shipment.lines.count() == 2                    # line_no 1 + 2
        client.post(reverse('fulfillment:line_delete',
                            args=[draft_shipment.pk, widget_sl.pk]))
        assert draft_shipment.lines.count() == 1                    # only line_no 2 left
        widget = issued_po.lines.order_by('line_no')[0]
        resp = client.post(reverse('fulfillment:line_add', args=[draft_shipment.pk]),
                           {'purchase_order_line': widget.pk, 'shipped_quantity': '1'})
        assert resp.status_code == 302                              # no IntegrityError 500
        nums = list(draft_shipment.lines.values_list('line_no', flat=True))
        assert len(nums) == len(set(nums)) == 2                     # unique line numbers

    def test_duplicate_po_line_rejected(self, client, tenant_admin, issued_po,
                                        draft_shipment):
        """A 2nd shipment line for a PO line already on the shipment is rejected by
        the form (re-render), never an IntegrityError 500 (fix #5)."""
        client.force_login(tenant_admin)
        widget = issued_po.lines.order_by('line_no')[0]            # already on the shipment
        resp = client.post(reverse('fulfillment:line_add', args=[draft_shipment.pk]),
                           {'purchase_order_line': widget.pk, 'shipped_quantity': '1'})
        assert resp.status_code == 200                              # form invalid, re-rendered
        assert draft_shipment.lines.count() == 1                    # no duplicate created
