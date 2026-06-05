"""Security tests for Module 14: anonymous redirect, role gating, multi-tenant isolation,
vendor-portal IDOR + visibility, and the file-upload whitelist."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import set_current_tenant
from .conftest import build_invoice

pytestmark = pytest.mark.django_db


class TestAnonymous:
    def test_list_requires_login(self, client):
        resp = client.get(reverse('invoicing:invoice_list'))
        assert resp.status_code == 302
        assert '/accounts/login' in resp.url


class TestRoleGating:
    def test_requester_denied_list(self, client, requester):
        client.force_login(requester)
        resp = client.get(reverse('invoicing:invoice_list'))
        assert resp.status_code == 302  # bounced by _require_view

    def test_approver_can_view_not_manage(self, client, approver, submitted_invoice):
        client.force_login(approver)
        assert client.get(reverse('invoicing:invoice_list')).status_code == 200
        # cannot create
        assert client.get(reverse('invoicing:invoice_create')).status_code == 302

    def test_approver_cannot_approve(self, client, approver, submitted_invoice):
        client.force_login(approver)
        client.post(reverse('invoicing:invoice_approve', args=[submitted_invoice.pk]))
        submitted_invoice.refresh_from_db()
        assert submitted_invoice.status == 'submitted'  # unchanged


class TestTenantIsolation:
    def test_intruder_cannot_see_other_tenant_invoice(
            self, client, intruder, submitted_invoice):
        client.force_login(intruder)
        resp = client.get(
            reverse('invoicing:invoice_detail', args=[submitted_invoice.pk]))
        assert resp.status_code == 404

    def test_intruder_cannot_delete_other_tenant_invoice(
            self, client, intruder, draft_invoice):
        client.force_login(intruder)
        resp = client.post(reverse('invoicing:invoice_delete', args=[draft_invoice.pk]))
        assert resp.status_code == 404


class TestVendorPortal:
    def test_vendor_sees_own_submitted(self, client, vendor_portal_user, submitted_invoice):
        client.force_login(vendor_portal_user)
        resp = client.get(
            reverse('vendor_portal:invoice_detail', args=[submitted_invoice.pk]))
        assert resp.status_code == 200

    def test_vendor_cannot_see_other_vendor_invoice(
            self, client, tenant, tenant_admin, vendor_a, vendor_b,
            vendor_b_portal_user, payment_term):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-SEC-1',
                            term=payment_term)
        from apps.invoicing import services
        services.submit_invoice(inv, tenant_admin)
        client.force_login(vendor_b_portal_user)  # belongs to vendor_b
        resp = client.get(reverse('vendor_portal:invoice_detail', args=[inv.pk]))
        assert resp.status_code == 404  # _get_invoice scopes to own vendor

    def test_vendor_portal_list_200(self, client, vendor_portal_user, submitted_invoice):
        client.force_login(vendor_portal_user)
        assert client.get(reverse('vendor_portal:invoices')).status_code == 200

    def test_non_vendor_bounced_from_portal(self, client, buyer_user):
        client.force_login(buyer_user)
        resp = client.get(reverse('vendor_portal:invoices'))
        assert resp.status_code == 302  # vendor_required bounces non-vendor


class TestFileUploadWhitelist:
    def test_portal_rejects_dangerous_extension(
            self, client, tenant, tenant_admin, vendor_a, vendor_portal_user):
        from .conftest import make_received_po
        set_current_tenant(tenant)
        make_received_po(tenant, tenant_admin, vendor_a, number='PO-UP-1')
        client.force_login(vendor_portal_user)
        # need a dispatched PO for this vendor — the received PO above qualifies
        from apps.purchase_orders.models import PurchaseOrder
        po = PurchaseOrder.all_objects.filter(tenant=tenant, vendor=vendor_a).first()
        f = SimpleUploadedFile('x.html', b'<script>', content_type='text/html')
        resp = client.post(reverse('vendor_portal:invoice_create'),
                           {'purchase_order': po.pk, 'source_file': f})
        # rejected -> redirect back, no invoice created
        from apps.invoicing.models import SupplierInvoice
        set_current_tenant(tenant)
        assert not SupplierInvoice.all_objects.filter(
            tenant=tenant, vendor=vendor_a).exists()
