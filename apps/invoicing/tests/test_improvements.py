"""Tests for the Module 14 hardening / feature pass:

  * currency-mismatch validation (three-way match + voucher block),
  * early-payment discount re-validation at payment time,
  * duplicate supplier-invoice-ref detection,
  * per-PO three-way-match tolerance overrides,
  * dispute SLA escalation alerts,
  * OCR low-confidence routing,
  * opt-in email alerts,
  * take-discount quick action, CSV export and batch voucher operations (views).

Reuses the shared conftest fixtures; every helper builds its own PO/invoice so fixtures are
never mutated in place (per lessons.md).
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import set_current_tenant
from apps.purchase_orders.models import PurchaseOrder

from apps.invoicing import services
from apps.invoicing.models import PaymentVoucher, SupplierInvoice
from .conftest import build_invoice, make_received_po

pytestmark = pytest.mark.django_db


def _refetch(inv):
    return SupplierInvoice.all_objects.select_related('purchase_order').get(pk=inv.pk)


# ---------------------------------------------------------------------------
# Currency mismatch
# ---------------------------------------------------------------------------
class TestCurrencyMismatch:
    def test_match_flags_currency_mismatch(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-CUR-1')
        PurchaseOrder.all_objects.filter(pk=inv.purchase_order_id).update(currency='EUR')
        services.run_three_way_match(_refetch(inv))
        inv = _refetch(inv)
        assert inv.currency_mismatch is True
        assert inv.match_status == 'exceptions'

    def test_match_no_mismatch_same_currency(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-CUR-2')
        services.run_three_way_match(_refetch(inv))
        inv = _refetch(inv)
        assert inv.currency_mismatch is False
        assert inv.match_status == 'matched'

    def test_create_voucher_blocked_on_mismatch(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-CUR-3')
        PurchaseOrder.all_objects.filter(pk=inv.purchase_order_id).update(currency='EUR')
        inv = _refetch(inv)
        services.submit_invoice(inv, tenant_admin)
        inv = _refetch(inv)
        services.approve_invoice(inv, tenant_admin, override=True)
        inv = _refetch(inv)
        with pytest.raises(ValidationError):
            services.create_voucher(inv, tenant_admin)


# ---------------------------------------------------------------------------
# Early-payment discount re-validation at payment time
# ---------------------------------------------------------------------------
class TestDiscountRevalidation:
    def _approved_with_discount(self, tenant, user, vendor, term, po_number):
        inv = build_invoice(tenant, user, vendor, po_number=po_number, term=term)
        services.submit_invoice(inv, user)
        inv = _refetch(inv)
        services.approve_invoice(inv, user)
        return _refetch(inv)

    def test_pay_after_window_closed_raises(
            self, tenant, tenant_admin, vendor_a, discount_term):
        set_current_tenant(tenant)
        inv = self._approved_with_discount(
            tenant, tenant_admin, vendor_a, discount_term, 'PO-DR-1')
        voucher = services.create_voucher(inv, tenant_admin, take_discount=True)
        services.approve_voucher(voucher, tenant_admin)
        assert voucher.discount_taken > 0
        # The window closes before payment.
        SupplierInvoice.all_objects.filter(pk=inv.pk).update(
            discount_due_date=timezone.localdate() - timedelta(days=1))
        with pytest.raises(ValidationError):
            services.pay_voucher(voucher, tenant_admin)
        voucher.refresh_from_db()
        assert voucher.status != 'paid'

    def test_pay_within_window_succeeds(
            self, tenant, tenant_admin, vendor_a, discount_term):
        set_current_tenant(tenant)
        inv = self._approved_with_discount(
            tenant, tenant_admin, vendor_a, discount_term, 'PO-DR-2')
        voucher = services.create_voucher(inv, tenant_admin, take_discount=True)
        services.approve_voucher(voucher, tenant_admin)
        services.pay_voucher(voucher, tenant_admin)
        voucher.refresh_from_db()
        assert voucher.status == 'paid'

    def test_pay_no_discount_unaffected_by_closed_window(
            self, tenant, tenant_admin, vendor_a, discount_term):
        set_current_tenant(tenant)
        inv = self._approved_with_discount(
            tenant, tenant_admin, vendor_a, discount_term, 'PO-DR-3')
        voucher = services.create_voucher(inv, tenant_admin, take_discount=False)
        services.approve_voucher(voucher, tenant_admin)
        SupplierInvoice.all_objects.filter(pk=inv.pk).update(
            discount_due_date=timezone.localdate() - timedelta(days=1))
        services.pay_voucher(voucher, tenant_admin)
        voucher.refresh_from_db()
        assert voucher.status == 'paid'


# ---------------------------------------------------------------------------
# Duplicate supplier-invoice-ref detection
# ---------------------------------------------------------------------------
class TestDuplicateRef:
    def test_duplicate_blocked(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_a,
            currency='USD', supplier_invoice_ref='INV-77')
        with pytest.raises(ValidationError):
            services.create_invoice(
                tenant=tenant, user=tenant_admin, vendor=vendor_a,
                currency='USD', supplier_invoice_ref='INV-77')

    def test_duplicate_case_insensitive(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_a,
            currency='USD', supplier_invoice_ref='abc-1')
        with pytest.raises(ValidationError):
            services.create_invoice(
                tenant=tenant, user=tenant_admin, vendor=vendor_a,
                currency='USD', supplier_invoice_ref='ABC-1')

    def test_blank_ref_allowed_twice(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_a,
            currency='USD', supplier_invoice_ref='')
        services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_a,
            currency='USD', supplier_invoice_ref='')

    def test_cancelled_ref_does_not_block(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_a,
            currency='USD', supplier_invoice_ref='INV-CX')
        services.cancel_invoice(inv, tenant_admin, 'mistake')
        # A new invoice may reuse the ref now the old one is cancelled.
        services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_a,
            currency='USD', supplier_invoice_ref='INV-CX')

    def test_different_vendor_allowed(self, tenant, tenant_admin, vendor_a, vendor_b):
        set_current_tenant(tenant)
        services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_a,
            currency='USD', supplier_invoice_ref='SHARED')
        services.create_invoice(
            tenant=tenant, user=tenant_admin, vendor=vendor_b,
            currency='USD', supplier_invoice_ref='SHARED')


# ---------------------------------------------------------------------------
# Per-PO tolerance overrides
# ---------------------------------------------------------------------------
class TestPoToleranceOverrides:
    def test_price_variance_without_override(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-TOL-1',
                            price_factor=Decimal('1.10'))
        services.run_three_way_match(_refetch(inv))
        assert _refetch(inv).match_status == 'exceptions'

    def test_po_override_absorbs_variance(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-TOL-2',
                            price_factor=Decimal('1.10'))
        PurchaseOrder.all_objects.filter(pk=inv.purchase_order_id).update(
            price_tolerance_pct=Decimal('20'))
        services.run_three_way_match(_refetch(inv))
        assert _refetch(inv).match_status == 'matched'


# ---------------------------------------------------------------------------
# Dispute SLA escalation
# ---------------------------------------------------------------------------
class TestDisputeSla:
    def _disputed(self, tenant, user, vendor, po_number):
        inv = build_invoice(tenant, user, vendor, po_number=po_number)
        services.submit_invoice(inv, user)
        inv = _refetch(inv)
        services.raise_dispute(inv, user, 'Wrong price')
        return _refetch(inv)

    def test_aging_dispute_fires_once(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = self._disputed(tenant, tenant_admin, vendor_a, 'PO-SLA-1')
        SupplierInvoice.all_objects.filter(pk=inv.pk).update(
            disputed_at=timezone.now() - timedelta(days=30))
        counts = services.scan_invoice_alerts(tenant=tenant)
        assert counts['dispute_sla'] == 1
        # Idempotent — guarded by dispute_sla_alerted_at.
        again = services.scan_invoice_alerts(tenant=tenant)
        assert again['dispute_sla'] == 0

    def test_fresh_dispute_not_alerted(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        self._disputed(tenant, tenant_admin, vendor_a, 'PO-SLA-2')
        counts = services.scan_invoice_alerts(tenant=tenant)
        assert counts['dispute_sla'] == 0


# ---------------------------------------------------------------------------
# OCR low-confidence routing
# ---------------------------------------------------------------------------
class TestOcrConfidence:
    def test_high_confidence_not_flagged(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-OCR-1')
        SupplierInvoice.all_objects.filter(pk=inv.pk).update(ocr_confidence=Decimal('92'))
        assert _refetch(inv).needs_manual_ocr_review is False

    @override_settings(OCR_MIN_CONFIDENCE=70)
    def test_low_confidence_flagged(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-OCR-2')
        SupplierInvoice.all_objects.filter(pk=inv.pk).update(ocr_confidence=Decimal('45'))
        assert _refetch(inv).needs_manual_ocr_review is True

    def test_manual_entry_never_flagged(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-OCR-3')
        assert inv.ocr_confidence is None
        assert _refetch(inv).needs_manual_ocr_review is False


# ---------------------------------------------------------------------------
# Email alerts (opt-in)
# ---------------------------------------------------------------------------
class TestEmailAlerts:
    def _overdue(self, tenant, user, vendor, po_number):
        inv = build_invoice(tenant, user, vendor, po_number=po_number)
        services.submit_invoice(inv, user)
        SupplierInvoice.all_objects.filter(pk=inv.pk).update(
            due_date=timezone.localdate() - timedelta(days=1),
            overdue_alerted_at=None)
        return inv

    def test_no_email_when_disabled(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        self._overdue(tenant, tenant_admin, vendor_a, 'PO-EM-1')
        mail.outbox.clear()
        counts = services.scan_invoice_alerts(tenant=tenant)
        assert counts['overdue'] == 1
        assert len(mail.outbox) == 0

    @override_settings(INVOICE_EMAIL_ALERTS=True)
    def test_email_sent_when_enabled(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        self._overdue(tenant, tenant_admin, vendor_a, 'PO-EM-2')
        mail.outbox.clear()
        counts = services.scan_invoice_alerts(tenant=tenant)
        assert counts['overdue'] == 1
        assert len(mail.outbox) == 1
        assert tenant_admin.email in mail.outbox[0].to


# ---------------------------------------------------------------------------
# Views — take-discount quick action, CSV export, batch vouchers
# ---------------------------------------------------------------------------
class TestQuickActionView:
    def test_take_discount_quick_action(
            self, client, buyer_user, tenant, tenant_admin, vendor_a, discount_term):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-QA-1',
                            term=discount_term)
        services.submit_invoice(inv, tenant_admin)
        inv = _refetch(inv)
        services.approve_invoice(inv, tenant_admin)
        client.force_login(buyer_user)
        resp = client.post(
            reverse('invoicing:voucher_create', args=[inv.pk]), {'quick_action': '1'})
        assert resp.status_code == 302
        voucher = PaymentVoucher.all_objects.filter(supplier_invoice=inv).first()
        assert voucher is not None
        assert voucher.discount_taken > 0


class TestCsvExport:
    def test_export_csv(self, client, buyer_user, submitted_invoice):
        client.force_login(buyer_user)
        resp = client.get(reverse('invoicing:export_unpaid_csv'))
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'text/csv'
        body = b''.join(resp.streaming_content)
        assert submitted_invoice.invoice_number.encode() in body

    def test_export_requires_view(self, client, requester):
        client.force_login(requester)
        resp = client.get(reverse('invoicing:export_unpaid_csv'))
        assert resp.status_code == 302  # bounced to dashboard


class TestBatchVouchers:
    def test_batch_pay(self, client, buyer_user, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        inv = build_invoice(tenant, tenant_admin, vendor_a, po_number='PO-BV-1')
        services.submit_invoice(inv, tenant_admin)
        inv = _refetch(inv)
        services.approve_invoice(inv, tenant_admin)
        inv = _refetch(inv)
        voucher = services.create_voucher(inv, tenant_admin)
        services.approve_voucher(voucher, tenant_admin)
        client.force_login(buyer_user)
        resp = client.post(
            reverse('invoicing:batch_pay_vouchers'), {'voucher_ids': [str(voucher.pk)]})
        assert resp.status_code == 302
        voucher.refresh_from_db()
        assert voucher.status == 'paid'

    def test_batch_empty_selection_warns(self, client, buyer_user):
        client.force_login(buyer_user)
        resp = client.post(reverse('invoicing:batch_pay_vouchers'), {})
        assert resp.status_code == 302
