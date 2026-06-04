"""Model tests for Module 13 — Goods Receipt & Inspection."""
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.core.models import set_current_tenant
from apps.goods_receipt.models import GoodsReceipt, GoodsReceiptLine, ReceiptTag

pytestmark = pytest.mark.django_db


class TestStatusGates:
    def test_draft_is_editable_and_receivable(self, draft_grn):
        assert draft_grn.is_editable
        assert draft_grn.can_receive
        assert not draft_grn.can_inspect
        assert draft_grn.is_open and not draft_grn.is_finished

    def test_received_can_inspect(self, received_grn):
        assert received_grn.can_inspect
        assert not received_grn.can_receive
        assert not received_grn.is_editable

    def test_inspected_can_post(self, inspected_grn):
        assert inspected_grn.can_post
        assert inspected_grn.can_cancel  # still cancellable before posting

    def test_posted_can_close_not_cancel(self, posted_grn):
        assert posted_grn.can_close
        assert not posted_grn.can_cancel  # a posting cannot be silently reversed
        assert posted_grn.is_finished

    def test_str(self, draft_grn):
        assert draft_grn.grn_number in str(draft_grn)
        assert draft_grn.purchase_order.po_number in str(draft_grn)


class TestNumberingFormat:
    def test_grn_number_format(self, draft_grn):
        assert draft_grn.grn_number.startswith('GRN-ACME-')
        assert draft_grn.grn_number.split('-')[-1].isdigit()


class TestLineProperties:
    def test_outstanding_inspection(self, received_grn):
        line = received_grn.lines.first()
        # received 6, nothing decided yet
        assert line.outstanding_inspection == Decimal('6.00')

    def test_unposted_quantity(self, inspected_grn):
        line = inspected_grn.lines.first()
        # accepted 4, posted 0
        assert line.unposted_quantity == Decimal('4.00')

    def test_inspected_split(self, inspected_grn):
        line = inspected_grn.lines.first()
        assert line.accepted_quantity == Decimal('4.00')
        assert line.rejected_quantity == Decimal('2.00')
        assert line.discrepancy_type == 'damaged'
        assert line.line_status == 'partial'


class TestRollUps:
    def test_totals(self, inspected_grn):
        # two lines, each accepted 4 / rejected 2
        assert inspected_grn.total_received_qty == Decimal('12.00')
        assert inspected_grn.total_accepted_qty == Decimal('8.00')
        assert inspected_grn.total_rejected_qty == Decimal('4.00')
        assert inspected_grn.has_rejections

    def test_qa_passed(self, inspected_grn):
        assert inspected_grn.qa_passed  # only a 'no_damage: pass' check exists


class TestTags:
    def test_tag_generated_on_post(self, posted_grn):
        tags = posted_grn.tags.all()
        assert tags.count() == posted_grn.lines.count()
        for tag in tags:
            assert tag.code.startswith(posted_grn.grn_number + '-L')


class TestConstraints:
    def test_grn_number_unique_per_tenant(self, draft_grn, tenant):
        set_current_tenant(tenant)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                GoodsReceipt.all_objects.create(
                    tenant=tenant, grn_number=draft_grn.grn_number,
                    purchase_order=draft_grn.purchase_order, vendor=draft_grn.vendor,
                )

    def test_line_no_unique_per_grn(self, draft_grn, tenant):
        set_current_tenant(tenant)
        existing = draft_grn.lines.first()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                GoodsReceiptLine.all_objects.create(
                    tenant=tenant, goods_receipt=draft_grn,
                    purchase_order_line=existing.purchase_order_line,
                    line_no=existing.line_no, received_quantity=Decimal('1'),
                )

    def test_tag_code_unique_per_tenant(self, posted_grn, tenant):
        set_current_tenant(tenant)
        tag = posted_grn.tags.first()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ReceiptTag.all_objects.create(
                    tenant=tenant, goods_receipt=posted_grn,
                    goods_receipt_line=tag.goods_receipt_line, code=tag.code,
                    quantity=Decimal('1'),
                )
