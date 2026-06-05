"""View-level tests for Module 14: list/filters, capture, CRUD, lifecycle, vouchers,
payment-term CRUD and analytics."""
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import set_current_tenant
from apps.invoicing import services
from apps.invoicing.models import PaymentTerm, SupplierInvoice
from .conftest import make_received_po

pytestmark = pytest.mark.django_db


class TestList:
    def test_list_200(self, client, buyer_user, submitted_invoice):
        client.force_login(buyer_user)
        resp = client.get(reverse('invoicing:invoice_list'))
        assert resp.status_code == 200
        assert submitted_invoice.invoice_number.encode() in resp.content

    def test_status_filter(self, client, buyer_user, submitted_invoice):
        client.force_login(buyer_user)
        resp = client.get(reverse('invoicing:invoice_list'), {'status': 'submitted'})
        assert resp.status_code == 200
        assert submitted_invoice.invoice_number.encode() in resp.content

    def test_search(self, client, buyer_user, submitted_invoice):
        client.force_login(buyer_user)
        resp = client.get(reverse('invoicing:invoice_list'),
                          {'q': submitted_invoice.invoice_number})
        assert resp.status_code == 200


class TestCapture:
    def test_capture_get(self, client, buyer_user):
        client.force_login(buyer_user)
        assert client.get(reverse('invoicing:invoice_capture')).status_code == 200

    def test_capture_post_creates_invoice(self, client, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        po = make_received_po(tenant, tenant_admin, vendor_a, number='PO-V-CAP')
        client.force_login(tenant_admin)
        f = SimpleUploadedFile('inv.pdf', b'%PDF-1.4 mock', content_type='application/pdf')
        resp = client.post(reverse('invoicing:invoice_capture'),
                           {'purchase_order': po.pk, 'source_file': f})
        assert resp.status_code == 302
        set_current_tenant(tenant)
        assert SupplierInvoice.all_objects.filter(tenant=tenant).exists()


class TestDetailEditDelete:
    def test_detail_200(self, client, buyer_user, draft_invoice):
        client.force_login(buyer_user)
        assert client.get(
            reverse('invoicing:invoice_detail', args=[draft_invoice.pk])).status_code == 200

    def test_edit_draft(self, client, buyer_user, draft_invoice):
        client.force_login(buyer_user)
        assert client.get(
            reverse('invoicing:invoice_edit', args=[draft_invoice.pk])).status_code == 200

    def test_edit_blocked_after_submit(self, client, buyer_user, submitted_invoice):
        client.force_login(buyer_user)
        resp = client.get(reverse('invoicing:invoice_edit', args=[submitted_invoice.pk]))
        assert resp.status_code == 302  # redirected — not editable

    def test_delete_draft(self, client, buyer_user, draft_invoice):
        client.force_login(buyer_user)
        resp = client.post(reverse('invoicing:invoice_delete', args=[draft_invoice.pk]))
        assert resp.status_code == 302
        set_current_tenant(draft_invoice.tenant)
        assert not SupplierInvoice.all_objects.filter(pk=draft_invoice.pk).exists()


class TestLifecycle:
    def test_submit(self, client, buyer_user, draft_invoice):
        client.force_login(buyer_user)
        client.post(reverse('invoicing:invoice_submit', args=[draft_invoice.pk]))
        draft_invoice.refresh_from_db()
        assert draft_invoice.status == 'submitted'

    def test_approve(self, client, buyer_user, submitted_invoice):
        client.force_login(buyer_user)
        client.post(reverse('invoicing:invoice_approve', args=[submitted_invoice.pk]))
        submitted_invoice.refresh_from_db()
        assert submitted_invoice.status == 'approved'

    def test_dispute(self, client, buyer_user, submitted_invoice):
        client.force_login(buyer_user)
        client.post(reverse('invoicing:invoice_dispute', args=[submitted_invoice.pk]),
                    {'reason': 'price wrong'})
        submitted_invoice.refresh_from_db()
        assert submitted_invoice.status == 'disputed'

    def test_match_rerun(self, client, buyer_user, submitted_invoice):
        client.force_login(buyer_user)
        resp = client.post(reverse('invoicing:invoice_match', args=[submitted_invoice.pk]))
        assert resp.status_code == 302


class TestLines:
    def test_add_line(self, client, buyer_user, draft_invoice):
        client.force_login(buyer_user)
        po = draft_invoice.purchase_order
        pol = po.lines.first()
        resp = client.post(
            reverse('invoicing:line_add', args=[draft_invoice.pk]),
            {'purchase_order_line': pol.pk, 'quantity': '1', 'unit_price': '5', 'uom': 'unit'})
        assert resp.status_code == 302
        assert draft_invoice.lines.count() == 3


class TestVouchers:
    def test_create_and_pay(self, client, buyer_user, approved_invoice):
        client.force_login(buyer_user)
        client.post(reverse('invoicing:voucher_create', args=[approved_invoice.pk]),
                    {'payment_method': 'bank_transfer'})
        approved_invoice.refresh_from_db()
        v = approved_invoice.vouchers.first()
        assert v is not None
        client.post(reverse('invoicing:voucher_approve', args=[v.pk]))
        client.post(reverse('invoicing:voucher_pay', args=[v.pk]),
                    {'payment_method': 'bank_transfer'})
        v.refresh_from_db()
        approved_invoice.refresh_from_db()
        assert v.status == 'paid'
        assert approved_invoice.status == 'paid'

    def test_voucher_list_200(self, client, buyer_user, approved_invoice):
        client.force_login(buyer_user)
        assert client.get(reverse('invoicing:voucher_list')).status_code == 200


class TestPaymentTerms:
    def test_term_crud(self, client, tenant, buyer_user):
        client.force_login(buyer_user)
        assert client.get(reverse('invoicing:term_list')).status_code == 200
        resp = client.post(reverse('invoicing:term_create'),
                           {'code': 'NET15', 'name': 'Net 15', 'net_days': '15',
                            'discount_percent': '0', 'discount_days': '0', 'is_active': 'on'})
        assert resp.status_code == 302
        set_current_tenant(tenant)
        assert PaymentTerm.all_objects.filter(tenant=tenant, code='NET15').exists()


class TestAnalytics:
    def test_dashboard_200(self, client, buyer_user, submitted_invoice):
        client.force_login(buyer_user)
        assert client.get(reverse('invoicing:analytics_dashboard')).status_code == 200
