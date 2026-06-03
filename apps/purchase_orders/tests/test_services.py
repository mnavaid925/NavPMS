"""Service-layer tests for Module 11 — Purchase Order Management."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import set_current_tenant
from apps.portal.models import Notification
from apps.purchase_orders import services
from apps.purchase_orders.models import (
    PurchaseOrder,
    PurchaseOrderChangeOrder,
    PurchaseOrderLine,
)

pytestmark = pytest.mark.django_db


class TestNumbering:
    def test_sequential_gap_free(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        n1 = services.next_po_number(tenant)
        assert n1 == 'PO-ACME-00001'
        PurchaseOrder.all_objects.create(
            tenant=tenant, po_number=n1, title='a', vendor=vendor_a,
            created_by=tenant_admin)
        assert services.next_po_number(tenant) == 'PO-ACME-00002'


class TestPermissions:
    def test_manage_roles(self, tenant_admin, buyer_user, procurement_manager):
        assert services.can_manage_po(tenant_admin)
        assert services.can_manage_po(buyer_user)
        assert services.can_manage_po(procurement_manager)

    def test_view_only_role(self, approver):
        assert services.can_view_po(approver)
        assert not services.can_manage_po(approver)

    def test_requester_denied(self, requester):
        assert not services.can_manage_po(requester)
        assert not services.can_view_po(requester)


class TestVisibilityGate:
    def test_vendor_sees_own_dispatched(self, vendor_portal_user, issued_po):
        assert services.po_visible_to(vendor_portal_user, issued_po)

    def test_vendor_cannot_see_draft(self, vendor_portal_user, draft_po):
        assert not services.po_visible_to(vendor_portal_user, draft_po)

    def test_vendor_cannot_see_other_vendor(self, vendor_b_portal_user, issued_po):
        assert not services.po_visible_to(vendor_b_portal_user, issued_po)

    def test_manager_sees_any(self, buyer_user, draft_po):
        assert services.po_visible_to(buyer_user, draft_po)


class TestCreateFromRequisition:
    def test_copies_lines_and_links(self, tenant, tenant_admin, approved_requisition):
        set_current_tenant(tenant)
        po = services.create_po_from_requisition(approved_requisition, tenant_admin)
        assert po.requisition_id == approved_requisition.pk
        assert po.lines.count() == 2
        # totals: 5*200 + 5*25 = 1125
        assert po.subtotal == Decimal('1125.00')
        first = po.lines.order_by('line_no').first()
        assert first.requisition_line_id is not None
        assert first.account_code_id is not None

    def test_marks_requisition_converted(self, tenant, tenant_admin, approved_requisition):
        set_current_tenant(tenant)
        po = services.create_po_from_requisition(approved_requisition, tenant_admin)
        approved_requisition.refresh_from_db()
        assert approved_requisition.status == 'converted'
        assert approved_requisition.po_reference == po.po_number


class TestIssue:
    def test_issue_requires_vendor(self, tenant, tenant_admin, draft_po_no_vendor):
        set_current_tenant(tenant)
        with pytest.raises(ValidationError):
            services.issue_po(draft_po_no_vendor, tenant_admin)

    def test_issue_requires_lines(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        po = PurchaseOrder.all_objects.create(
            tenant=tenant, po_number='PO-ACME-07777', title='empty',
            vendor=vendor_a, created_by=tenant_admin)
        with pytest.raises(ValidationError):
            services.issue_po(po, tenant_admin)

    def test_issue_transitions_and_notifies(self, tenant, tenant_admin, draft_po,
                                            vendor_portal_user):
        set_current_tenant(tenant)
        services.issue_po(draft_po, tenant_admin, dispatch_method='email',
                          recipient_email='buyer@x.test')
        draft_po.refresh_from_db()
        assert draft_po.status == 'issued'
        assert draft_po.issued_at is not None
        assert draft_po.dispatched_to == 'buyer@x.test'
        # the supplier's portal user was notified
        assert Notification.all_objects.filter(user=vendor_portal_user).exists()


class TestAcknowledgeDecline:
    def test_acknowledge(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        services.acknowledge_po(issued_po, tenant_admin, note='ok')
        issued_po.refresh_from_db()
        assert issued_po.status == 'acknowledged'
        assert issued_po.acknowledged_at is not None

    def test_cannot_acknowledge_draft(self, tenant, tenant_admin, draft_po):
        set_current_tenant(tenant)
        with pytest.raises(ValidationError):
            services.acknowledge_po(draft_po, tenant_admin)

    def test_decline_then_reopen(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        services.decline_po(issued_po, tenant_admin, 'cannot fulfil')
        issued_po.refresh_from_db()
        assert issued_po.status == 'declined'
        services.reopen_po(issued_po, tenant_admin)
        issued_po.refresh_from_db()
        assert issued_po.status == 'draft'


class TestReceiving:
    def test_partial_then_full(self, tenant, tenant_admin, acknowledged_po):
        set_current_tenant(tenant)
        line = acknowledged_po.lines.order_by('line_no').first()
        services.record_line_receipt(acknowledged_po, line, Decimal('1'), tenant_admin)
        line.refresh_from_db()
        acknowledged_po.refresh_from_db()
        assert line.delivery_status == 'partial'
        assert acknowledged_po.status == 'partially_received'

    def test_over_receipt_rejected(self, tenant, tenant_admin, acknowledged_po):
        set_current_tenant(tenant)
        line = acknowledged_po.lines.order_by('line_no').first()
        with pytest.raises(ValidationError):
            services.record_line_receipt(
                acknowledged_po, line, line.quantity + Decimal('1'), tenant_admin)

    def test_full_receipt_marks_received(self, tenant, tenant_admin, received_po):
        # received_po fixture already drove a full receipt
        assert received_po.status == 'received'
        assert received_po.lines.first().delivery_status == 'received'


class TestCancelClose:
    def test_cancel(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        services.cancel_po(issued_po, tenant_admin, 'no longer needed')
        issued_po.refresh_from_db()
        assert issued_po.status == 'cancelled'

    def test_cannot_cancel_received(self, tenant, tenant_admin, received_po):
        set_current_tenant(tenant)
        with pytest.raises(ValidationError):
            services.cancel_po(received_po, tenant_admin, 'x')

    def test_close_received(self, tenant, tenant_admin, received_po):
        set_current_tenant(tenant)
        services.close_po(received_po, tenant_admin, note='done')
        received_po.refresh_from_db()
        assert received_po.status == 'closed'

    def test_cannot_close_draft(self, tenant, tenant_admin, draft_po):
        set_current_tenant(tenant)
        with pytest.raises(ValidationError):
            services.close_po(draft_po, tenant_admin)


class TestChangeOrder:
    def _make_co(self, tenant, po, line, *, qty=None, price=None):
        item = {'line_id': line.id}
        if qty is not None:
            item['quantity'] = str(qty)
        if price is not None:
            item['unit_price'] = str(price)
        return PurchaseOrderChangeOrder.all_objects.create(
            tenant=tenant, purchase_order=po,
            change_number=services.next_change_number(po),
            change_type='quantity', proposed_lines=[item], status='draft',
        )

    def test_apply_changes_qty_and_bumps_revision(self, tenant, tenant_admin,
                                                  acknowledged_po):
        set_current_tenant(tenant)
        line = acknowledged_po.lines.order_by('line_no').first()
        before_total = acknowledged_po.total_amount
        co = self._make_co(tenant, acknowledged_po, line,
                           qty=line.quantity + Decimal('5'))
        services.apply_change_order(co, tenant_admin)
        acknowledged_po.refresh_from_db()
        co.refresh_from_db()
        assert co.status == 'applied'
        assert acknowledged_po.revision == 2
        assert acknowledged_po.total_amount > before_total
        assert co.prev_total == before_total

    def test_cannot_reapply(self, tenant, tenant_admin, acknowledged_po):
        set_current_tenant(tenant)
        line = acknowledged_po.lines.order_by('line_no').first()
        co = self._make_co(tenant, acknowledged_po, line, qty=Decimal('99'))
        services.apply_change_order(co, tenant_admin)
        with pytest.raises(ValidationError):
            services.apply_change_order(co, tenant_admin)

    def test_cannot_apply_to_draft(self, tenant, tenant_admin, draft_po):
        set_current_tenant(tenant)
        line = draft_po.lines.first()
        co = self._make_co(tenant, draft_po, line, qty=Decimal('5'))
        with pytest.raises(ValidationError):
            services.apply_change_order(co, tenant_admin)


class TestTotals:
    def test_recompute_with_tax_and_shipping(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        po = PurchaseOrder.all_objects.create(
            tenant=tenant, po_number='PO-ACME-06000', title='t', vendor=vendor_a,
            created_by=tenant_admin, tax_amount=Decimal('10.00'),
            shipping_amount=Decimal('5.00'))
        PurchaseOrderLine.all_objects.create(
            tenant=tenant, purchase_order=po, line_no=1, description='x',
            quantity=Decimal('2'), unit_price=Decimal('100.00'))
        services.recompute_totals(po)
        po.refresh_from_db()
        assert po.subtotal == Decimal('200.00')
        assert po.total_amount == Decimal('215.00')


class TestAlerts:
    def test_overdue_delivery_alert_idempotent(self, tenant, issued_po):
        set_current_tenant(tenant)
        issued_po.expected_delivery_date = timezone.localdate() - timedelta(days=2)
        issued_po.save(update_fields=['expected_delivery_date'])
        counts = services.scan_po_alerts(tenant=tenant)
        assert counts['overdue_delivery'] == 1
        issued_po.refresh_from_db()
        assert issued_po.delivery_alerted_at is not None
        # second sweep is a no-op (guarded)
        counts2 = services.scan_po_alerts(tenant=tenant)
        assert counts2['overdue_delivery'] == 0

    def test_awaiting_ack_alert(self, tenant, issued_po):
        set_current_tenant(tenant)
        issued_po.issued_at = timezone.now() - timedelta(days=5)
        issued_po.save(update_fields=['issued_at'])
        counts = services.scan_po_alerts(tenant=tenant)
        assert counts['ack_alerted'] == 1


class TestMetrics:
    def test_metrics_counts(self, tenant, draft_po, issued_po, received_po):
        set_current_tenant(tenant)
        m = services.tenant_po_metrics(tenant)
        assert m['total_pos'] == 3
        assert m['draft'] == 1
        assert m['issued'] == 1
        assert m['received'] == 1
        assert m['committed_value'] > 0
