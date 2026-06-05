"""Model-level tests for Module 14: status gates, roll-ups, numbering, term math."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.core.models import set_current_tenant
from apps.invoicing.models import (
    PaymentTerm,
    PaymentVoucher,
    SupplierInvoice,
    SupplierInvoiceLine,
)

pytestmark = pytest.mark.django_db


class TestStatusGates:
    def test_draft_is_editable_and_submittable(self, draft_invoice):
        assert draft_invoice.is_editable
        assert draft_invoice.can_submit
        assert not draft_invoice.can_approve
        assert draft_invoice.can_cancel
        assert draft_invoice.is_open and not draft_invoice.is_finished

    def test_submitted_can_approve_dispute_not_edit(self, submitted_invoice):
        assert not submitted_invoice.is_editable
        assert submitted_invoice.can_approve
        assert submitted_invoice.can_dispute
        assert submitted_invoice.can_reject

    def test_approved_can_create_voucher(self, approved_invoice):
        assert approved_invoice.status == 'approved'
        assert approved_invoice.can_create_voucher
        assert not approved_invoice.can_cancel
        assert approved_invoice.is_open and not approved_invoice.is_finished

    def test_match_matched_on_clean_invoice(self, submitted_invoice):
        assert submitted_invoice.match_status == 'matched'
        assert submitted_invoice.is_matched


class TestRollUps:
    def test_total_amount_from_lines(self, draft_invoice):
        # 6 x 100 + 6 x 5 = 630
        assert draft_invoice.subtotal == Decimal('630.00')
        assert draft_invoice.total_amount == Decimal('630.00')
        assert draft_invoice.line_count == 2

    def test_line_total_computed_on_save(self, draft_invoice):
        line = draft_invoice.lines.first()
        assert line.line_total == (line.quantity * line.unit_price)


class TestVoucherGate:
    def test_voucher_blocks_second(self, approved_invoice, tenant_admin):
        from apps.invoicing.services import create_voucher
        create_voucher(approved_invoice, tenant_admin)
        approved_invoice.refresh_from_db()
        assert not approved_invoice.can_create_voucher


class TestPaymentTermMath:
    def test_due_and_discount_dates(self, tenant, discount_term):
        d = date(2026, 1, 1)
        assert discount_term.due_date_for(d) == d + timedelta(days=30)
        assert discount_term.discount_date_for(d) == d + timedelta(days=10)
        assert discount_term.has_discount

    def test_no_discount_date_when_zero(self, tenant):
        set_current_tenant(tenant)
        t = PaymentTerm.all_objects.create(
            tenant=tenant, code='NET45', name='Net 45', net_days=45)
        assert t.discount_date_for(date(2026, 1, 1)) is None
        assert not t.has_discount


class TestConstraints:
    def test_invoice_number_unique_per_tenant(self, tenant, vendor_a):
        set_current_tenant(tenant)
        SupplierInvoice.all_objects.create(
            tenant=tenant, invoice_number='SINV-X-1', vendor=vendor_a)
        with pytest.raises(IntegrityError):
            SupplierInvoice.all_objects.create(
                tenant=tenant, invoice_number='SINV-X-1', vendor=vendor_a)

    def test_line_no_unique_per_invoice(self, draft_invoice):
        set_current_tenant(draft_invoice.tenant)
        with pytest.raises(IntegrityError):
            SupplierInvoiceLine.all_objects.create(
                tenant=draft_invoice.tenant, supplier_invoice=draft_invoice,
                line_no=draft_invoice.lines.first().line_no,
                description='dup', quantity=Decimal('1'), unit_price=Decimal('1'))

    def test_term_code_unique_per_tenant(self, tenant):
        set_current_tenant(tenant)
        PaymentTerm.all_objects.create(tenant=tenant, code='DUP', name='a')
        with pytest.raises(IntegrityError):
            PaymentTerm.all_objects.create(tenant=tenant, code='DUP', name='b')

    def test_voucher_number_unique_per_tenant(self, tenant, vendor_a):
        set_current_tenant(tenant)
        inv = SupplierInvoice.all_objects.create(
            tenant=tenant, invoice_number='SINV-Y-1', vendor=vendor_a)
        PaymentVoucher.all_objects.create(
            tenant=tenant, voucher_number='VCH-Y-1', supplier_invoice=inv,
            vendor=vendor_a, amount=Decimal('10'))
        with pytest.raises(IntegrityError):
            PaymentVoucher.all_objects.create(
                tenant=tenant, voucher_number='VCH-Y-1', supplier_invoice=inv,
                vendor=vendor_a, amount=Decimal('10'))
