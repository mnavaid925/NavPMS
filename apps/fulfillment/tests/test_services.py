"""Service-level tests: permissions, ASN advice, carrier tracking sync, the
idempotent / guarded delivery-receipt posting, split delivery, backorders and alerts."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import set_current_tenant
from apps.fulfillment import services as fs
from apps.fulfillment.models import Backorder, Shipment, ShipmentTrackingEvent
from apps.portal.models import Notification

pytestmark = pytest.mark.django_db


class TestPermissions:
    def test_manage_roles(self, tenant_admin, buyer_user, procurement_manager,
                          approver, requester):
        assert fs.can_manage_fulfillment(tenant_admin)
        assert fs.can_manage_fulfillment(buyer_user)
        assert fs.can_manage_fulfillment(procurement_manager)
        assert not fs.can_manage_fulfillment(approver)
        assert not fs.can_manage_fulfillment(requester)

    def test_view_roles(self, approver, requester):
        assert fs.can_view_fulfillment(approver)
        assert not fs.can_view_fulfillment(requester)

    def test_visibility_gate(self, tenant, tenant_admin, requester,
                             vendor_portal_user, vendor_b_portal_user, draft_shipment):
        set_current_tenant(tenant)
        # internal viewer
        assert fs.shipment_visible_to(tenant_admin, draft_shipment)
        assert not fs.shipment_visible_to(requester, draft_shipment)
        # the owning vendor sees it; another vendor does not
        assert fs.shipment_visible_to(vendor_portal_user, draft_shipment)
        assert not fs.shipment_visible_to(vendor_b_portal_user, draft_shipment)


class TestAdvise:
    def test_advise_requires_lines(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        s = fs.create_shipment(tenant=tenant, user=tenant_admin, purchase_order=issued_po)
        with pytest.raises(ValidationError):
            fs.advise_shipment(s, tenant_admin)

    def test_advise_transitions_and_notifies(self, tenant, tenant_admin, draft_shipment):
        set_current_tenant(tenant)
        fs.advise_shipment(draft_shipment, tenant_admin)
        draft_shipment.refresh_from_db()
        assert draft_shipment.status == 'advised'
        assert draft_shipment.advised_at is not None
        # the PO owner (tenant_admin) gets a delivery notification
        assert Notification.all_objects.filter(
            tenant=tenant, user=tenant_admin, category='delivery').exists()

    def test_cannot_advise_twice(self, tenant, tenant_admin, advised_shipment):
        set_current_tenant(tenant)
        with pytest.raises(ValidationError):
            fs.advise_shipment(advised_shipment, tenant_admin)


class TestSyncTracking:
    def test_requires_tracking_number(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        s = fs.create_shipment(tenant=tenant, user=tenant_admin, purchase_order=issued_po)
        with pytest.raises(ValidationError):
            fs.sync_tracking(s, tenant_admin)

    def test_mock_carrier_advances_and_dedupes(self, tenant, tenant_admin, advised_shipment):
        set_current_tenant(tenant)
        # ship_date is 2 days ago → mock reaches out_for_delivery
        fs.sync_tracking(advised_shipment, tenant_admin)
        advised_shipment.refresh_from_db()
        assert advised_shipment.status in ('in_transit', 'out_for_delivery')
        assert advised_shipment.freight_status
        assert advised_shipment.tracking_last_synced_at is not None
        n1 = ShipmentTrackingEvent.all_objects.filter(shipment=advised_shipment).count()
        assert n1 >= 1
        # syncing again must not duplicate the same events
        fs.sync_tracking(advised_shipment, tenant_admin)
        n2 = ShipmentTrackingEvent.all_objects.filter(shipment=advised_shipment).count()
        assert n2 == n1

    def test_delivered_sets_actual_date(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        s = fs.create_shipment(
            tenant=tenant, user=tenant_admin, purchase_order=issued_po,
            carrier_code='mock', tracking_number='TRKD',
            ship_date=timezone.localdate() - timedelta(days=5))
        fs.add_shipment_line(
            s, purchase_order_line=issued_po.lines.first(), shipped_quantity=Decimal('1'))
        fs.advise_shipment(s, tenant_admin)
        fs.sync_tracking(s, tenant_admin)
        s.refresh_from_db()
        assert s.status == 'delivered'
        assert s.actual_delivery_date is not None


class TestTrackingGuards:
    """Tracking (sync + manual events) is gated to in-flight states, so a draft
    can't jump straight to 'delivered' and a finished shipment can't be re-scanned."""

    def test_cannot_sync_draft(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        s = fs.create_shipment(
            tenant=tenant, user=tenant_admin, purchase_order=issued_po,
            carrier_code='mock', tracking_number='T')
        with pytest.raises(ValidationError):
            fs.sync_tracking(s, tenant_admin)

    def test_cannot_add_manual_event_to_draft(self, tenant, tenant_admin, draft_shipment):
        set_current_tenant(tenant)
        with pytest.raises(ValidationError):
            fs.add_manual_tracking_event(
                draft_shipment, tenant_admin, status_code='in_transit')

    def test_cannot_add_manual_event_to_received(self, tenant, tenant_admin,
                                                 advised_shipment):
        set_current_tenant(tenant)
        fs.confirm_delivery(advised_shipment, tenant_admin, post_receipt=True)
        advised_shipment.refresh_from_db()
        with pytest.raises(ValidationError):
            fs.add_manual_tracking_event(
                advised_shipment, tenant_admin, status_code='in_transit')

    def test_manual_event_advances_advised(self, tenant, tenant_admin, advised_shipment):
        set_current_tenant(tenant)
        fs.add_manual_tracking_event(
            advised_shipment, tenant_admin, status_code='in_transit')
        advised_shipment.refresh_from_db()
        assert advised_shipment.status == 'in_transit'


class TestSplitDelivery:
    def test_remaining_to_ship_decreases(self, tenant, tenant_admin, issued_po,
                                         draft_shipment):
        set_current_tenant(tenant)
        line = issued_po.lines.order_by('line_no').first()  # ordered qty 10
        # draft_shipment already ships 4 of it
        assert fs.remaining_to_ship_line(line) == Decimal('6.00')

    def test_over_ship_blocked(self, tenant, tenant_admin, issued_po, draft_shipment):
        set_current_tenant(tenant)
        line = issued_po.lines.order_by('line_no').first()
        s2 = fs.create_shipment(tenant=tenant, user=tenant_admin, purchase_order=issued_po)
        with pytest.raises(ValidationError):
            fs.add_shipment_line(s2, purchase_order_line=line, shipped_quantity=Decimal('7'))

    def test_two_shipments_roll_po_up(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        line = issued_po.lines.order_by('line_no').first()  # qty 10
        # shipment 1: 4 → confirm → PO partially_received
        s1 = fs.create_shipment(
            tenant=tenant, user=tenant_admin, purchase_order=issued_po,
            carrier_code='mock', tracking_number='S1')
        fs.add_shipment_line(s1, purchase_order_line=line, shipped_quantity=Decimal('4'))
        fs.advise_shipment(s1, tenant_admin)
        s1.refresh_from_db()
        fs.confirm_delivery(s1, tenant_admin, post_receipt=True)
        # the OTHER PO line (Gadget, qty 4) is untouched, so PO is partially_received
        issued_po.refresh_from_db()
        assert issued_po.status == 'partially_received'

        # shipment 2: remaining 6 of line 1 + all 4 of line 2 → confirm → PO received
        s2 = fs.create_shipment(
            tenant=tenant, user=tenant_admin, purchase_order=issued_po,
            carrier_code='mock', tracking_number='S2')
        fs.add_shipment_line(s2, purchase_order_line=line, shipped_quantity=Decimal('6'))
        fs.add_shipment_line(
            s2, purchase_order_line=issued_po.lines.order_by('line_no')[1],
            shipped_quantity=Decimal('4'))
        fs.advise_shipment(s2, tenant_admin)
        s2.refresh_from_db()
        fs.confirm_delivery(s2, tenant_admin, post_receipt=True)
        issued_po.refresh_from_db()
        assert issued_po.status == 'received'
        line.refresh_from_db()
        assert line.received_quantity == Decimal('10.00')


class TestConfirmDelivery:
    def test_posts_receipt_to_po(self, tenant, tenant_admin, advised_shipment, issued_po):
        set_current_tenant(tenant)
        po_line = issued_po.lines.order_by('line_no').first()
        fs.confirm_delivery(advised_shipment, tenant_admin, post_receipt=True)
        advised_shipment.refresh_from_db()
        po_line.refresh_from_db()
        assert advised_shipment.status == 'received'
        assert po_line.received_quantity == Decimal('4.00')
        sl = advised_shipment.lines.first()
        assert sl.posted_quantity == Decimal('4.00')   # watermark set

    def test_idempotent_no_double_post(self, tenant, tenant_admin, advised_shipment,
                                       issued_po):
        set_current_tenant(tenant)
        po_line = issued_po.lines.order_by('line_no').first()
        fs.confirm_delivery(advised_shipment, tenant_admin, post_receipt=True)
        advised_shipment.refresh_from_db()
        # second confirm must NOT re-post (shipment is already 'received')
        with pytest.raises(ValidationError):
            fs.confirm_delivery(advised_shipment, tenant_admin, post_receipt=True)
        po_line.refresh_from_db()
        assert po_line.received_quantity == Decimal('4.00')   # not 8

    def test_post_receipt_false_leaves_po_untouched(self, tenant, tenant_admin,
                                                    advised_shipment, issued_po):
        set_current_tenant(tenant)
        po_line = issued_po.lines.order_by('line_no').first()
        fs.confirm_delivery(advised_shipment, tenant_admin, post_receipt=False)
        advised_shipment.refresh_from_db()
        po_line.refresh_from_db()
        assert advised_shipment.status == 'delivered'
        assert po_line.received_quantity == Decimal('0.00')
        assert advised_shipment.lines.first().posted_quantity == Decimal('0.00')

    def test_received_cannot_exceed_shipped(self, tenant, tenant_admin, advised_shipment):
        set_current_tenant(tenant)
        sl = advised_shipment.lines.first()
        with pytest.raises(ValidationError):
            fs.confirm_delivery(
                advised_shipment, tenant_admin, post_receipt=True,
                line_quantities={sl.id: Decimal('999')})

    def test_cannot_post_when_po_not_receivable(self, tenant, tenant_admin, issued_po):
        """A delivered shipment whose PO is already fully received cannot post again."""
        set_current_tenant(tenant)
        line = issued_po.lines.order_by('line_no').first()
        gadget = issued_po.lines.order_by('line_no')[1]
        # Fully receive the PO via one shipment.
        s = fs.create_shipment(
            tenant=tenant, user=tenant_admin, purchase_order=issued_po,
            carrier_code='mock', tracking_number='FULL')
        fs.add_shipment_line(s, purchase_order_line=line, shipped_quantity=Decimal('10'))
        fs.add_shipment_line(s, purchase_order_line=gadget, shipped_quantity=Decimal('4'))
        fs.advise_shipment(s, tenant_admin)
        s.refresh_from_db()
        fs.confirm_delivery(s, tenant_admin, post_receipt=True)
        issued_po.refresh_from_db()
        assert issued_po.status == 'received'
        # A second shipment can't be created (nothing remains), proving no over-receipt path.
        s2 = fs.create_shipment(
            tenant=tenant, user=tenant_admin, purchase_order=issued_po)
        with pytest.raises(ValidationError):
            fs.add_shipment_line(
                s2, purchase_order_line=line, shipped_quantity=Decimal('1'))


class TestBackorders:
    def test_open_fulfill_cancel(self, tenant, tenant_admin, issued_po, draft_shipment):
        set_current_tenant(tenant)
        line = issued_po.lines.first()
        bo = fs.open_backorder(
            tenant=tenant, user=tenant_admin, purchase_order_line=line,
            quantity=Decimal('3'), expected_date=timezone.localdate() + timedelta(days=5))
        assert bo.status == 'open'
        fs.fulfill_backorder(bo, tenant_admin, shipment=draft_shipment)
        bo.refresh_from_db()
        assert bo.status == 'fulfilled'
        assert bo.fulfilled_by_shipment_id == draft_shipment.id

    def test_open_requires_positive_qty(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        with pytest.raises(ValidationError):
            fs.open_backorder(
                tenant=tenant, user=tenant_admin,
                purchase_order_line=issued_po.lines.first(), quantity=Decimal('0'))

    def test_scan_backorder_alerts_idempotent(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        fs.open_backorder(
            tenant=tenant, user=tenant_admin,
            purchase_order_line=issued_po.lines.first(), quantity=Decimal('2'),
            expected_date=timezone.localdate() - timedelta(days=3))
        c1 = fs.scan_backorder_alerts(tenant=tenant)
        assert c1['overdue'] == 1
        c2 = fs.scan_backorder_alerts(tenant=tenant)
        assert c2['overdue'] == 0   # guarded by alerted_at

    def test_orphan_backorder_auto_cancel(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        bo = fs.open_backorder(
            tenant=tenant, user=tenant_admin,
            purchase_order_line=issued_po.lines.first(), quantity=Decimal('2'))
        issued_po.status = 'cancelled'
        issued_po.save(update_fields=['status'])
        counts = fs.scan_backorder_alerts(tenant=tenant)
        bo.refresh_from_db()
        assert counts['orphans_cancelled'] == 1
        assert bo.status == 'cancelled'


class TestFulfillmentAlerts:
    def test_overdue_shipment_alert_idempotent(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        s = fs.create_shipment(
            tenant=tenant, user=tenant_admin, purchase_order=issued_po,
            carrier_code='mock', tracking_number='OD',
            estimated_delivery_date=timezone.localdate() - timedelta(days=4))
        fs.add_shipment_line(
            s, purchase_order_line=issued_po.lines.first(), shipped_quantity=Decimal('1'))
        fs.advise_shipment(s, tenant_admin)
        c1 = fs.scan_fulfillment_alerts(tenant=tenant)
        assert c1['overdue_delivery'] == 1
        c2 = fs.scan_fulfillment_alerts(tenant=tenant)
        assert c2['overdue_delivery'] == 0


class TestCancelClose:
    def test_cancel_advised(self, tenant, tenant_admin, advised_shipment):
        set_current_tenant(tenant)
        fs.cancel_shipment(advised_shipment, tenant_admin, 'No longer needed')
        advised_shipment.refresh_from_db()
        assert advised_shipment.status == 'cancelled'

    def test_cannot_cancel_received(self, tenant, tenant_admin, advised_shipment):
        set_current_tenant(tenant)
        fs.confirm_delivery(advised_shipment, tenant_admin, post_receipt=True)
        advised_shipment.refresh_from_db()
        with pytest.raises(ValidationError):
            fs.cancel_shipment(advised_shipment, tenant_admin, 'too late')

    def test_close_delivered(self, tenant, tenant_admin, advised_shipment):
        set_current_tenant(tenant)
        fs.confirm_delivery(advised_shipment, tenant_admin, post_receipt=False)
        advised_shipment.refresh_from_db()
        assert advised_shipment.status == 'delivered'
        fs.close_shipment(advised_shipment, tenant_admin, 'done')
        advised_shipment.refresh_from_db()
        assert advised_shipment.status == 'closed'
