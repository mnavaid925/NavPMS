"""Service-layer tests for Module 14: OCR capture, three-way match, lifecycle,
voucher payment (gateway) idempotency, alerts, permissions and the over-billing guard."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.models import set_current_tenant
from apps.invoicing import services
from apps.invoicing.models import SupplierInvoice
from .conftest import build_invoice, make_open_po, make_received_po

pytestmark = pytest.mark.django_db


class TestCapture:
    def test_capture_from_file_creates_lines(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        po = make_received_po(tenant, tenant_admin, vendor_a, number='PO-CAP-1')
        f = SimpleUploadedFile('invoice.txt', b'mock invoice', content_type='text/plain')
        inv = services.capture_invoice_from_file(
            tenant=tenant, user=tenant_admin, source_file=f, purchase_order=po)
        assert inv.ocr_engine == 'mock'
        assert inv.lines.count() == po.lines.count()
        assert inv.total_amount > 0

    def test_capture_rejects_bad_extension(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        po = make_received_po(tenant, tenant_admin, vendor_a, number='PO-CAP-2')
        f = SimpleUploadedFile('evil.svg', b'<svg/>', content_type='image/svg+xml')
        with pytest.raises(ValidationError):
            services.capture_invoice_from_file(
                tenant=tenant, user=tenant_admin, source_file=f, purchase_order=po)


class TestThreeWayMatch:
    def test_clean_match(self, submitted_invoice):
        assert submitted_invoice.match_status == 'matched'
        for ln in submitted_invoice.lines.all():
            assert ln.match_status == 'matched'

    def test_price_variance(self, tenant, tenant_admin, vendor_a, payment_term):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-PV-1',
                            term=payment_term, price_factor=Decimal('1.20'))
        services.submit_invoice(inv, tenant_admin)
        inv.refresh_from_db()
        assert inv.match_status == 'exceptions'
        assert any(ln.match_status == 'price_variance' for ln in inv.lines.all())

    def test_over_billed(self, tenant, tenant_admin, vendor_a, payment_term):
        set_current_tenant(tenant)
        po = make_received_po(tenant, tenant_admin, vendor_a, number='PO-OB-1')
        inv = services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_a, purchase_order=po,
            payment_term=payment_term)
        pol = po.lines.first()
        services.add_invoice_line(
            inv, purchase_order_line=pol, quantity=pol.received_quantity * 2,
            unit_price=pol.unit_price)
        services.submit_invoice(inv, tenant_admin)
        inv.refresh_from_db()
        assert inv.lines.first().match_status == 'over_billed'

    def test_no_receipt(self, tenant, tenant_admin, vendor_a, payment_term):
        set_current_tenant(tenant)
        po = make_open_po(tenant, tenant_admin, vendor_a, number='PO-NR-1')  # not received
        inv = services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_a, purchase_order=po,
            payment_term=payment_term)
        pol = po.lines.first()
        services.add_invoice_line(
            inv, purchase_order_line=pol, quantity=Decimal('1'),
            unit_price=pol.unit_price)
        services.submit_invoice(inv, tenant_admin)
        inv.refresh_from_db()
        assert inv.lines.first().match_status == 'no_receipt'

    def test_no_po_line(self, tenant, tenant_admin, vendor_a, payment_term):
        set_current_tenant(tenant)
        inv = services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_a, payment_term=payment_term)
        services.add_invoice_line(
            inv, description='Off-PO charge', quantity=Decimal('1'),
            unit_price=Decimal('50'))
        services.submit_invoice(inv, tenant_admin)
        inv.refresh_from_db()
        assert inv.lines.first().match_status == 'no_po'
        assert inv.match_status == 'exceptions'


class TestLifecycle:
    def test_submit_sets_due_date(self, draft_invoice, tenant_admin):
        services.submit_invoice(draft_invoice, tenant_admin)
        draft_invoice.refresh_from_db()
        assert draft_invoice.status == 'submitted'
        assert draft_invoice.due_date is not None

    def test_approve_blocked_on_exceptions_without_override(
            self, tenant, tenant_admin, vendor_a, payment_term):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-EX-1',
                            term=payment_term, price_factor=Decimal('1.5'))
        services.submit_invoice(inv, tenant_admin)
        inv.refresh_from_db()
        with pytest.raises(ValidationError):
            services.approve_invoice(inv, tenant_admin)
        services.approve_invoice(inv, tenant_admin, override=True)
        inv.refresh_from_db()
        assert inv.status == 'approved' and inv.match_override

    def test_dispute_and_resolve(self, submitted_invoice, tenant_admin):
        services.raise_dispute(submitted_invoice, tenant_admin, 'Wrong price')
        submitted_invoice.refresh_from_db()
        assert submitted_invoice.status == 'disputed'
        assert submitted_invoice.dispute_notes.count() == 1
        services.add_dispute_note(
            submitted_invoice, tenant_admin, 'Will reissue', is_from_vendor=True)
        services.resolve_dispute(submitted_invoice, tenant_admin)
        submitted_invoice.refresh_from_db()
        assert submitted_invoice.status == 'submitted'

    def test_reject(self, submitted_invoice, tenant_admin):
        services.reject_invoice(submitted_invoice, tenant_admin, 'Duplicate')
        submitted_invoice.refresh_from_db()
        assert submitted_invoice.status == 'rejected'


class TestVoucherPayment:
    def test_pay_flips_invoice_paid(self, approved_invoice, tenant_admin):
        v = services.create_voucher(approved_invoice, tenant_admin)
        services.approve_voucher(v, tenant_admin)
        services.pay_voucher(v, tenant_admin)
        v.refresh_from_db()
        approved_invoice.refresh_from_db()
        assert v.status == 'paid'
        assert v.gateway_ref
        assert approved_invoice.status == 'paid'

    def test_pay_is_idempotent(self, approved_invoice, tenant_admin):
        v = services.create_voucher(approved_invoice, tenant_admin)
        services.approve_voucher(v, tenant_admin)
        services.pay_voucher(v, tenant_admin)
        v.refresh_from_db()
        ref = v.gateway_ref
        services.pay_voucher(v, tenant_admin)  # second call, no double-charge
        v.refresh_from_db()
        assert v.gateway_ref == ref and v.status == 'paid'

    def test_discount_taken(self, tenant, tenant_admin, vendor_a, discount_term):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-DISC-1',
                            term=discount_term)
        services.submit_invoice(inv, tenant_admin)
        inv.refresh_from_db()
        services.approve_invoice(inv, tenant_admin)
        inv.refresh_from_db()
        v = services.create_voucher(inv, tenant_admin, take_discount=True)
        assert v.discount_taken > 0
        assert v.amount == inv.total_amount - v.discount_taken


class TestAlerts:
    def test_overdue_alert_idempotent(self, approved_invoice, tenant):
        set_current_tenant(tenant)
        SupplierInvoice.all_objects.filter(pk=approved_invoice.pk).update(
            due_date=timezone.localdate() - timedelta(days=5))
        c1 = services.scan_invoice_alerts(tenant=tenant)
        c2 = services.scan_invoice_alerts(tenant=tenant)
        assert c1['overdue'] == 1
        assert c2['overdue'] == 0


class TestPermissions:
    def test_manage_roles(self, buyer_user, procurement_manager, approver, requester):
        assert services.can_manage_invoicing(buyer_user)
        assert services.can_manage_invoicing(procurement_manager)
        assert not services.can_manage_invoicing(approver)
        assert not services.can_manage_invoicing(requester)

    def test_view_roles(self, approver, requester):
        assert services.can_view_invoicing(approver)
        assert not services.can_view_invoicing(requester)

    def test_invoice_visible_to_vendor(self, submitted_invoice, vendor_portal_user,
                                       vendor_b_portal_user):
        assert services.invoice_visible_to(vendor_portal_user, submitted_invoice)
        # other vendor cannot see it
        assert not services.invoice_visible_to(vendor_b_portal_user, submitted_invoice)

    def test_draft_hidden_from_vendor(self, draft_invoice, vendor_portal_user):
        assert not services.invoice_visible_to(vendor_portal_user, draft_invoice)
