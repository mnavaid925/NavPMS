"""Security tests: multi-tenant isolation, vendor-portal scoping, ASN ownership and
access-gate parity across every sibling view that exposes shipment data."""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.models import set_current_tenant
from apps.fulfillment import services as fs
from apps.fulfillment.models import Shipment

pytestmark = pytest.mark.django_db


class TestMultiTenantIsolation:
    def test_intruder_cannot_open_detail(self, client, intruder, draft_shipment):
        """A different tenant's admin gets a 404 on this tenant's shipment."""
        client.force_login(intruder)
        resp = client.get(reverse('fulfillment:shipment_detail', args=[draft_shipment.pk]))
        assert resp.status_code == 404

    def test_intruder_list_is_empty(self, client, intruder, draft_shipment):
        client.force_login(intruder)
        resp = client.get(reverse('fulfillment:shipment_list'))
        # 200 (intruder is a tenant_admin, may view) but sees none of acme's shipments
        assert resp.status_code == 200
        assert draft_shipment.shipment_number not in {
            s.shipment_number for s in resp.context['shipments']}


class TestVendorPortalScoping:
    def test_vendor_sees_own_shipment(self, client, vendor_portal_user, draft_shipment):
        client.force_login(vendor_portal_user)
        resp = client.get(
            reverse('vendor_portal:shipment_detail', args=[draft_shipment.pk]))
        assert resp.status_code == 200

    def test_vendor_cannot_see_other_vendor_shipment(self, client, vendor_b_portal_user,
                                                     draft_shipment):
        client.force_login(vendor_b_portal_user)
        resp = client.get(
            reverse('vendor_portal:shipment_detail', args=[draft_shipment.pk]))
        assert resp.status_code == 404   # _get_shipment scopes to request.user.vendor

    def test_vendor_list_scoped(self, client, vendor_b_portal_user, draft_shipment,
                                shipment_b):
        client.force_login(vendor_b_portal_user)
        resp = client.get(reverse('vendor_portal:shipments'))
        assert resp.status_code == 200
        nums = {s.shipment_number for s in resp.context['shipments']}
        assert shipment_b.shipment_number in nums          # own vendor
        assert draft_shipment.shipment_number not in nums   # vendor_a's shipment

    def test_vendor_cannot_asn_other_vendors_po(self, client, tenant, vendor_portal_user,
                                                issued_po_b):
        """vendor_a's portal user cannot raise an ASN against vendor_b's PO."""
        client.force_login(vendor_portal_user)
        resp = client.post(reverse('vendor_portal:asn_create'), {
            'purchase_order': issued_po_b.pk, 'package_count': 1,
            'total_weight': '1.00', 'weight_uom': 'kg', 'freight_cost': '0.00',
        })
        # the PO is not in vendor_a's queryset → form invalid (re-render) or rejected;
        # in all cases no shipment is created for vendor_b's PO by vendor_a.
        assert not Shipment.all_objects.filter(
            purchase_order=issued_po_b, created_by=vendor_portal_user).exists()


class TestAccessGateParity:
    """A low-privilege (requester) user must be bounced from EVERY sibling view that
    reads shipment/fulfillment data — not just the list (lessons.md: least-guarded
    sibling)."""

    @pytest.mark.parametrize('urlname', [
        'shipment_list', 'tracking_board', 'backorder_board', 'analytics_dashboard',
        'shipment_create', 'backorder_create',
    ])
    def test_requester_bounced(self, client, requester, urlname):
        client.force_login(requester)
        resp = client.get(reverse(f'fulfillment:{urlname}'))
        assert resp.status_code == 302   # _require_view / _require_manage redirect

    def test_requester_bounced_from_detail(self, client, requester, draft_shipment):
        client.force_login(requester)
        resp = client.get(reverse('fulfillment:shipment_detail', args=[draft_shipment.pk]))
        assert resp.status_code == 302
