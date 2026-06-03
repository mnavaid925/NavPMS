"""Model tests for Module 11 — Purchase Order Management."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import set_current_tenant
from apps.purchase_orders.models import (
    PurchaseOrder,
    PurchaseOrderChangeOrder,
    PurchaseOrderLine,
)

pytestmark = pytest.mark.django_db


class TestLineTotal:
    def test_line_total_computed_on_save(self, tenant, draft_po):
        set_current_tenant(tenant)
        line = PurchaseOrderLine.all_objects.create(
            tenant=tenant, purchase_order=draft_po, line_no=99,
            description='X', quantity=Decimal('3'), unit_price=Decimal('7.50'),
        )
        assert line.line_total == Decimal('22.50')

    def test_outstanding_quantity(self, tenant, draft_po):
        line = draft_po.lines.first()
        line.received_quantity = Decimal('1')
        assert line.outstanding_quantity == line.quantity - Decimal('1')


class TestStatusHelpers:
    def test_draft_is_editable_and_issuable(self, draft_po):
        assert draft_po.is_editable
        assert draft_po.can_issue
        assert draft_po.is_open
        assert not draft_po.is_finished

    def test_issued_can_acknowledge(self, issued_po):
        assert issued_po.status == 'issued'
        assert issued_po.can_acknowledge
        assert issued_po.can_receive
        assert issued_po.can_change_order
        assert not issued_po.is_editable

    def test_acknowledged_can_receive(self, acknowledged_po):
        assert acknowledged_po.status == 'acknowledged'
        assert acknowledged_po.can_receive
        assert acknowledged_po.can_cancel

    def test_received_is_closeable_and_finished_states(self, received_po):
        assert received_po.status == 'received'
        assert received_po.can_close
        assert not received_po.can_cancel  # received is not cancellable

    def test_dispatched_flag(self, draft_po, issued_po):
        assert not draft_po.is_dispatched
        assert issued_po.is_dispatched


class TestReceiving:
    def test_fully_received(self, received_po):
        assert received_po.is_fully_received
        assert received_po.received_progress == 100
        assert received_po.received_line_count == received_po.line_count

    def test_draft_not_fully_received(self, draft_po):
        assert not draft_po.is_fully_received
        assert draft_po.received_progress == 0


class TestDeliveryOverdue:
    def test_overdue_when_past_and_open(self, tenant, tenant_admin, vendor_a, issued_po):
        issued_po.expected_delivery_date = timezone.localdate() - timedelta(days=3)
        issued_po.save(update_fields=['expected_delivery_date'])
        assert issued_po.is_delivery_overdue

    def test_not_overdue_when_finished(self, received_po):
        received_po.expected_delivery_date = timezone.localdate() - timedelta(days=3)
        received_po.save(update_fields=['expected_delivery_date'])
        # received is not an open delivery status → not flagged overdue
        assert not received_po.is_delivery_overdue


class TestChangeOrder:
    def test_editable_and_applied_flags(self, tenant, draft_po):
        set_current_tenant(tenant)
        co = PurchaseOrderChangeOrder.all_objects.create(
            tenant=tenant, purchase_order=draft_po, change_number='PO-ACME-00001-CO01',
            change_type='quantity', status='draft',
        )
        assert co.is_editable
        assert not co.is_applied
        co.status = 'applied'
        assert co.is_applied
        assert not co.is_editable


class TestStr:
    def test_po_str(self, draft_po):
        assert draft_po.po_number in str(draft_po)
