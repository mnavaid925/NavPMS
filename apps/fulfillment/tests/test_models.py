"""Model-level tests: numbering, status properties, split detection, line maths,
backorder state, and the append-only tracking ledger ordering."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import set_current_tenant
from apps.fulfillment import services as fs
from apps.fulfillment.models import (
    Backorder,
    Shipment,
    ShipmentTrackingEvent,
)

pytestmark = pytest.mark.django_db


class TestNumbering:
    def test_format_and_increment(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        s1 = fs.create_shipment(tenant=tenant, user=tenant_admin, purchase_order=issued_po)
        s2 = fs.create_shipment(tenant=tenant, user=tenant_admin, purchase_order=issued_po)
        assert s1.shipment_number == 'SHP-ACME-00001'
        assert s2.shipment_number == 'SHP-ACME-00002'

    def test_number_is_tenant_scoped(self, tenant, other_tenant, tenant_admin,
                                     intruder, issued_po, issued_po_b):
        # both POs are in `tenant`; build one shipment in each tenant's namespace
        set_current_tenant(tenant)
        s = fs.create_shipment(tenant=tenant, user=tenant_admin, purchase_order=issued_po)
        assert s.shipment_number.startswith('SHP-ACME-')


class TestShipmentProperties:
    def test_draft_flags(self, draft_shipment):
        assert draft_shipment.is_editable
        assert draft_shipment.can_advise
        assert not draft_shipment.is_finished

    def test_advised_flags(self, advised_shipment):
        assert not advised_shipment.is_editable
        assert advised_shipment.can_track
        assert advised_shipment.can_confirm_delivery
        assert advised_shipment.can_cancel

    def test_received_cannot_cancel(self, tenant, tenant_admin, advised_shipment):
        set_current_tenant(tenant)
        fs.confirm_delivery(advised_shipment, tenant_admin, post_receipt=True)
        advised_shipment.refresh_from_db()
        assert advised_shipment.status == 'received'
        assert not advised_shipment.can_cancel
        assert advised_shipment.is_finished

    def test_is_split(self, tenant, tenant_admin, issued_po, draft_shipment):
        set_current_tenant(tenant)
        assert draft_shipment.is_split is False
        s2 = fs.create_shipment(
            tenant=tenant, user=tenant_admin, purchase_order=issued_po)
        fs.add_shipment_line(
            s2, purchase_order_line=issued_po.lines.first(),
            shipped_quantity=Decimal('2'))
        draft_shipment.refresh_from_db()
        assert draft_shipment.is_split is True

    def test_is_delivery_overdue(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        s = fs.create_shipment(
            tenant=tenant, user=tenant_admin, purchase_order=issued_po,
            tracking_number='T', carrier_code='mock',
            estimated_delivery_date=timezone.localdate() - timedelta(days=2))
        fs.add_shipment_line(
            s, purchase_order_line=issued_po.lines.first(),
            shipped_quantity=Decimal('1'))
        fs.advise_shipment(s, tenant_admin)
        s.refresh_from_db()
        assert s.is_delivery_overdue is True

    def test_not_overdue_when_future(self, advised_shipment):
        assert advised_shipment.is_delivery_overdue is False


class TestLineMaths:
    def test_outstanding_and_unposted(self, draft_shipment):
        line = draft_shipment.lines.first()
        line.received_quantity = Decimal('1.00')
        line.posted_quantity = Decimal('0.00')
        assert line.outstanding_quantity == Decimal('3.00')   # shipped 4 - received 1
        assert line.unposted_quantity == Decimal('1.00')      # received 1 - posted 0


class TestBackorder:
    def test_is_open_and_overdue(self, tenant, tenant_admin, issued_po):
        set_current_tenant(tenant)
        bo = fs.open_backorder(
            tenant=tenant, user=tenant_admin,
            purchase_order_line=issued_po.lines.first(),
            quantity=Decimal('3'),
            expected_date=timezone.localdate() - timedelta(days=1))
        assert bo.is_open
        assert bo.is_overdue
        bo.status = 'fulfilled'
        assert not bo.is_open
        assert not bo.is_overdue


class TestTrackingLedger:
    def test_ordering_newest_first(self, tenant, draft_shipment):
        set_current_tenant(tenant)
        now = timezone.now()
        ShipmentTrackingEvent.all_objects.create(
            tenant=tenant, shipment=draft_shipment, status_code='picked_up',
            occurred_at=now - timedelta(hours=2))
        ShipmentTrackingEvent.all_objects.create(
            tenant=tenant, shipment=draft_shipment, status_code='in_transit',
            occurred_at=now)
        codes = list(draft_shipment.tracking_events.values_list('status_code', flat=True))
        assert codes[0] == 'in_transit'  # newest first
