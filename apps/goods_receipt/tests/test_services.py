"""Service tests for Module 13 — Goods Receipt & Inspection.

Covers the receive -> inspect -> post lifecycle, the idempotent + guarded posting that
feeds the PO (and its co-existence with the fulfilment module), and the RTV flow.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models import set_current_tenant
from apps.purchase_orders.models import PurchaseOrder
from apps.fulfillment import services as ful_services

from apps.goods_receipt import services
from apps.goods_receipt.models import GoodsReceipt, ReceiptTag, ReturnToVendor
from .conftest import make_open_po

pytestmark = pytest.mark.django_db


# ---------- Permissions ----------
class TestPermissions:
    def test_manage_roles(self, tenant_admin, procurement_manager, buyer_user):
        assert services.can_manage_goods_receipt(tenant_admin)
        assert services.can_manage_goods_receipt(procurement_manager)
        assert services.can_manage_goods_receipt(buyer_user)

    def test_view_only_approver(self, approver):
        assert services.can_view_goods_receipt(approver)
        assert not services.can_manage_goods_receipt(approver)

    def test_requester_denied(self, requester):
        assert not services.can_view_goods_receipt(requester)

    def test_rtv_visible_to_vendor_only_when_authorised(self, grn_with_rtv,
                                                        vendor_portal_user):
        _grn, rtv = grn_with_rtv
        assert services.rtv_visible_to(vendor_portal_user, rtv)  # authorised
        rtv.status = 'draft'
        assert not services.rtv_visible_to(vendor_portal_user, rtv)


# ---------- Numbering ----------
class TestNumbering:
    def test_gap_free(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        po1 = make_open_po(tenant, tenant_admin, vendor_a, number='PO-ACME-20001')
        po2 = make_open_po(tenant, tenant_admin, vendor_a, number='PO-ACME-20002')
        g1 = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po1)
        g2 = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po2)
        assert g1.grn_number == 'GRN-ACME-00001'
        assert g2.grn_number == 'GRN-ACME-00002'


# ---------- Create + lines ----------
class TestCreate:
    def test_requires_open_po(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        po = PurchaseOrder.all_objects.create(
            tenant=tenant, po_number='PO-ACME-30001', title='draft', vendor=vendor_a,
            status='draft', created_by=tenant_admin, owner=tenant_admin)
        with pytest.raises(ValidationError):
            services.create_goods_receipt(
                tenant=tenant, user=tenant_admin, purchase_order=po)

    def test_add_line_requires_positive_qty(self, draft_grn):
        pol = draft_grn.purchase_order.lines.first()
        with pytest.raises(ValidationError):
            services.add_receipt_line(
                draft_grn, purchase_order_line=pol, received_quantity=Decimal('0'))

    def test_add_line_blocked_after_received(self, received_grn):
        pol = received_grn.purchase_order.lines.first()
        with pytest.raises(ValidationError):
            services.add_receipt_line(
                received_grn, purchase_order_line=pol, received_quantity=Decimal('1'))


# ---------- Receive ----------
class TestReceive:
    def test_mark_received(self, draft_grn, tenant_admin):
        grn = services.mark_received(draft_grn, tenant_admin)
        assert grn.status == 'received'
        assert grn.received_by_id == tenant_admin.id
        assert grn.lines.filter(line_status='received').count() == grn.lines.count()

    def test_received_requires_lines(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        po = make_open_po(tenant, tenant_admin, vendor_a, number='PO-ACME-40001')
        grn = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po)
        with pytest.raises(ValidationError):
            services.mark_received(grn, tenant_admin)


# ---------- Inspection ----------
class TestInspection:
    def test_accept_reject_split(self, received_grn, tenant_admin):
        line = received_grn.lines.first()
        services.record_inspection(
            received_grn, tenant_admin,
            checks=[{'criterion': 'no_damage', 'result': 'pass'}],
            line_results={line.id: {'accepted': Decimal('4'),
                                    'rejected': Decimal('2'),
                                    'discrepancy': 'damaged'}})
        received_grn.refresh_from_db()
        line.refresh_from_db()
        assert received_grn.status == 'inspected'
        assert received_grn.inspection_result == 'partial'
        assert line.accepted_quantity == Decimal('4.00')
        assert line.line_status == 'partial'

    def test_over_decide_rejected(self, received_grn, tenant_admin):
        line = received_grn.lines.first()
        with pytest.raises(ValidationError):
            services.record_inspection(
                received_grn, tenant_admin,
                line_results={line.id: {'accepted': Decimal('5'),
                                        'rejected': Decimal('5')}})  # 10 > 6 received

    def test_qa_fail_sets_result_fail(self, received_grn, tenant_admin):
        line = received_grn.lines.first()
        services.record_inspection(
            received_grn, tenant_admin,
            checks=[{'criterion': 'packaging_intact', 'result': 'fail'}],
            line_results={line.id: {'accepted': Decimal('6'), 'rejected': Decimal('0')}})
        received_grn.refresh_from_db()
        assert received_grn.inspection_result == 'fail'
        assert not received_grn.qa_passed


# ---------- Posting (the core) ----------
class TestPosting:
    def test_post_feeds_po_and_watermarks(self, posted_grn):
        po = posted_grn.purchase_order
        for grn_line in posted_grn.lines.all():
            pol = grn_line.purchase_order_line
            pol.refresh_from_db()
            assert pol.received_quantity == grn_line.accepted_quantity
            assert grn_line.posted_quantity == grn_line.accepted_quantity
        assert posted_grn.status == 'posted'

    def test_post_generates_tags(self, posted_grn):
        assert ReceiptTag.objects.filter(goods_receipt=posted_grn).count() == \
            posted_grn.lines.count()

    def test_repost_blocked_no_double_count(self, posted_grn, tenant_admin):
        po = posted_grn.purchase_order
        before = {l.id: l.received_quantity for l in po.lines.all()}
        with pytest.raises(ValidationError):
            services.post_goods_receipt(posted_grn, tenant_admin)
        for pol in po.lines.all():
            assert pol.received_quantity == before[pol.id]  # unchanged

    def test_post_requires_inspected(self, received_grn, tenant_admin):
        with pytest.raises(ValidationError):
            services.post_goods_receipt(received_grn, tenant_admin)

    def test_post_blocked_when_po_finished(self, inspected_grn, tenant_admin):
        po = inspected_grn.purchase_order
        po.status = 'cancelled'
        po.save(update_fields=['status'])
        with pytest.raises(ValidationError):
            services.post_goods_receipt(inspected_grn, tenant_admin)

    def test_over_receipt_pre_validation(self, tenant, tenant_admin, vendor_a):
        """Two GRNs against the same PO share its outstanding budget; the second over-posts."""
        set_current_tenant(tenant)
        po = make_open_po(
            tenant, tenant_admin, vendor_a, number='PO-ACME-50001',
            lines=[('Widget', 'unit', Decimal('10'), Decimal('1.00'))])
        pol = po.lines.first()

        # GRN #1: receive + accept 6, post.
        g1 = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po)
        services.add_receipt_line(
            g1, purchase_order_line=pol, received_quantity=Decimal('6'))
        services.mark_received(g1, tenant_admin)
        g1.refresh_from_db()
        services.record_inspection(
            g1, tenant_admin,
            line_results={g1.lines.first().id: {'accepted': Decimal('6'),
                                                'rejected': Decimal('0')}})
        g1.refresh_from_db()
        services.post_goods_receipt(g1, tenant_admin)
        pol.refresh_from_db()
        assert pol.received_quantity == Decimal('6.00')  # outstanding now 4

        # GRN #2: accept 6 again -> exceeds the remaining 4 -> raises, nothing posted.
        po.refresh_from_db()
        g2 = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po)
        services.add_receipt_line(
            g2, purchase_order_line=pol, received_quantity=Decimal('6'))
        services.mark_received(g2, tenant_admin)
        g2.refresh_from_db()
        services.record_inspection(
            g2, tenant_admin,
            line_results={g2.lines.first().id: {'accepted': Decimal('6'),
                                                'rejected': Decimal('0')}})
        g2.refresh_from_db()
        with pytest.raises(ValidationError, match='exceeds the PO outstanding'):
            services.post_goods_receipt(g2, tenant_admin)
        pol.refresh_from_db()
        assert pol.received_quantity == Decimal('6.00')  # unchanged

    def test_coexists_with_fulfillment_budget(self, tenant, tenant_admin, vendor_a):
        """A fulfilment confirm_delivery + a GRN post share one PO outstanding budget."""
        set_current_tenant(tenant)
        po = make_open_po(
            tenant, tenant_admin, vendor_a, number='PO-ACME-60001',
            lines=[('Widget', 'unit', Decimal('10'), Decimal('1.00'))])
        pol = po.lines.first()

        # Fulfilment receives 6 of 10 (PO -> partially_received, outstanding 4).
        shipment = ful_services.create_shipment(
            tenant=tenant, user=tenant_admin, purchase_order=po)
        ful_services.add_shipment_line(
            shipment, purchase_order_line=pol, shipped_quantity=Decimal('6'))
        ful_services.advise_shipment(shipment, tenant_admin)
        shipment.refresh_from_db()
        ful_services.confirm_delivery(shipment, tenant_admin, post_receipt=True)
        pol.refresh_from_db()
        assert pol.received_quantity == Decimal('6.00')

        # A GRN now accepting 6 more exceeds the remaining 4 -> raises.
        po.refresh_from_db()
        grn = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po)
        services.add_receipt_line(
            grn, purchase_order_line=pol, received_quantity=Decimal('6'))
        services.mark_received(grn, tenant_admin)
        grn.refresh_from_db()
        services.record_inspection(
            grn, tenant_admin,
            line_results={grn.lines.first().id: {'accepted': Decimal('6'),
                                                 'rejected': Decimal('0')}})
        grn.refresh_from_db()
        with pytest.raises(ValidationError, match='exceeds the PO outstanding'):
            services.post_goods_receipt(grn, tenant_admin)


# ---------- Receipt tolerance (auto over-receipt flag) ----------
class TestReceiptTolerance:
    def test_over_receipt_auto_flagged(self, tenant, tenant_admin, vendor_a):
        """Receiving beyond the PO outstanding (tolerance 0) flags discrepancy='over'."""
        set_current_tenant(tenant)
        po = make_open_po(
            tenant, tenant_admin, vendor_a, number='PO-ACME-70001',
            lines=[('Widget', 'unit', Decimal('10'), Decimal('1.00'))])
        pol = po.lines.first()
        grn = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po)
        line = services.add_receipt_line(
            grn, purchase_order_line=pol, received_quantity=Decimal('12'))
        assert line.discrepancy_type == 'over'

    def test_within_tolerance_not_flagged(self, tenant, tenant_admin, vendor_a):
        """A PO tolerance override widens the ceiling so an over-receipt is not flagged."""
        set_current_tenant(tenant)
        po = make_open_po(
            tenant, tenant_admin, vendor_a, number='PO-ACME-70002',
            lines=[('Widget', 'unit', Decimal('10'), Decimal('1.00'))])
        po.qty_tolerance_pct = Decimal('25')  # ceiling = 12.5
        po.save(update_fields=['qty_tolerance_pct'])
        pol = po.lines.first()
        grn = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po)
        line = services.add_receipt_line(
            grn, purchase_order_line=pol, received_quantity=Decimal('12'))
        assert line.discrepancy_type == 'none'

    def test_manual_discrepancy_not_overridden(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        po = make_open_po(
            tenant, tenant_admin, vendor_a, number='PO-ACME-70003',
            lines=[('Widget', 'unit', Decimal('10'), Decimal('1.00'))])
        pol = po.lines.first()
        grn = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po)
        line = services.add_receipt_line(
            grn, purchase_order_line=pol, received_quantity=Decimal('12'),
            discrepancy_type='damaged')
        assert line.discrepancy_type == 'damaged'  # manual choice preserved


# ---------- Tag propagation (bin / lot / expiry) ----------
class TestTagPropagation:
    def test_tags_inherit_bin_and_lot(self, tenant, tenant_admin, vendor_a):
        import datetime
        set_current_tenant(tenant)
        po = make_open_po(
            tenant, tenant_admin, vendor_a, number='PO-ACME-71001',
            lines=[('Widget', 'unit', Decimal('10'), Decimal('1.00'))])
        pol = po.lines.first()
        grn = services.create_goods_receipt(
            tenant=tenant, user=tenant_admin, purchase_order=po)
        line = services.add_receipt_line(
            grn, purchase_order_line=pol, received_quantity=Decimal('6'),
            bin_location='A-12-3', lot_number='LOT-9',
            expiry_date=datetime.date(2030, 1, 1))
        grn.refresh_from_db()
        services.mark_received(grn, tenant_admin)
        grn.refresh_from_db()
        services.record_inspection(
            grn, tenant_admin,
            line_results={line.id: {'accepted': Decimal('6'), 'rejected': Decimal('0')}})
        grn.refresh_from_db()
        services.post_goods_receipt(grn, tenant_admin)
        tag = ReceiptTag.objects.filter(goods_receipt=grn).first()
        assert tag.bin_location == 'A-12-3'
        assert tag.lot_number == 'LOT-9'
        assert tag.expiry_date == datetime.date(2030, 1, 1)


# ---------- Close / cancel ----------
class TestCloseCancel:
    def test_close_posted(self, posted_grn, tenant_admin):
        grn = services.close_goods_receipt(posted_grn, tenant_admin)
        assert grn.status == 'closed'

    def test_cancel_draft(self, draft_grn, tenant_admin):
        grn = services.cancel_goods_receipt(draft_grn, tenant_admin, 'oops')
        assert grn.status == 'cancelled'

    def test_cannot_cancel_posted(self, posted_grn, tenant_admin):
        with pytest.raises(ValidationError):
            services.cancel_goods_receipt(posted_grn, tenant_admin, 'no')


# ---------- RTV ----------
class TestRTV:
    def test_create_requires_rejections(self, posted_grn, tenant_admin):
        with pytest.raises(ValidationError):
            services.create_rtv_from_rejections(posted_grn, tenant_admin)

    def test_full_rtv_flow(self, inspected_grn, tenant_admin):
        rtv = services.create_rtv_from_rejections(inspected_grn, tenant_admin, reason='bad')
        assert rtv.rtv_number.startswith('RTV-ACME-')
        assert rtv.lines.count() == inspected_grn.lines.filter(
            rejected_quantity__gt=0).count()
        services.authorize_rtv(rtv, tenant_admin)
        rtv.refresh_from_db()
        assert rtv.status == 'authorized'
        services.ship_rtv(rtv, tenant_admin, carrier='UPS', tracking_number='1Z')
        rtv.refresh_from_db()
        assert rtv.status == 'shipped' and rtv.tracking_number == '1Z'
        services.close_rtv(rtv, tenant_admin)
        rtv.refresh_from_db()
        assert rtv.status == 'closed'

    def test_authorize_requires_lines(self, inspected_grn, tenant_admin):
        rtv = ReturnToVendor.all_objects.create(
            tenant=inspected_grn.tenant, rtv_number='RTV-ACME-09999',
            goods_receipt=inspected_grn, purchase_order=inspected_grn.purchase_order,
            vendor=inspected_grn.vendor, status='draft')
        with pytest.raises(ValidationError):
            services.authorize_rtv(rtv, tenant_admin)

    def test_acknowledge(self, grn_with_rtv, vendor_portal_user):
        _grn, rtv = grn_with_rtv
        services.acknowledge_rtv(rtv, vendor_portal_user, 'got it')
        rtv.refresh_from_db()
        assert rtv.acknowledged_at is not None


# ---------- Alerts + metrics ----------
class TestAlertsMetrics:
    def test_alerts_idempotent(self, received_grn, tenant):
        set_current_tenant(tenant)
        # back-date the receipt so it is overdue for inspection
        GoodsReceipt.all_objects.filter(pk=received_grn.pk).update(
            received_at=received_grn.received_at - __import__('datetime').timedelta(days=5))
        first = services.scan_goods_receipt_alerts(tenant=tenant)
        second = services.scan_goods_receipt_alerts(tenant=tenant)
        assert first['overdue_inspection'] == 1
        assert second['overdue_inspection'] == 0  # guarded, not re-raised

    def test_metrics_shape(self, posted_grn, inspected_grn, tenant):
        m = services.tenant_goods_receipt_metrics(tenant)
        assert m['total_grns'] >= 2
        assert m['posted'] >= 1
        assert m['acceptance_rate_pct'] >= 0
        assert 'top_discrepancies' in m
        assert m['tags_generated'] >= 1
