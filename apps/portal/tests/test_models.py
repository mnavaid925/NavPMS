"""Unit tests for Module 2 model invariants (BR-4, BR-5, properties)."""
from decimal import Decimal

import pytest

from apps.portal.models import DashboardWidget, Notification, QuickRequisitionItem


@pytest.mark.parametrize('size,expected', [
    ('small', 'col-lg-4'),
    ('medium', 'col-lg-6'),
    ('large', 'col-12'),
    ('bogus', 'col-lg-4'),
])
def test_widget_col_class(size, expected):
    assert DashboardWidget(size=size).col_class == expected


@pytest.mark.django_db
def test_item_save_computes_line_total(draft_req):
    """BR-4: line_total = quantity * unit_price on save."""
    item = QuickRequisitionItem(
        tenant=draft_req.tenant, requisition=draft_req,
        name='Pen', quantity=Decimal('3'), unit_price=Decimal('4.50'),
    )
    item.save()
    assert item.line_total == Decimal('13.50')


@pytest.mark.django_db
def test_recalc_total_sums_items(draft_req, make_item):
    """BR-5: recalc_total aggregates every line item."""
    make_item(draft_req, quantity='1', unit_price='10.00')
    make_item(draft_req, quantity='1', unit_price='5.50')
    assert draft_req.recalc_total() == Decimal('15.50')
    draft_req.refresh_from_db()
    assert draft_req.estimated_total == Decimal('15.50')


@pytest.mark.django_db
def test_mark_read_sets_timestamp(notification):
    assert not notification.is_read
    notification.mark_read()
    notification.refresh_from_db()
    assert notification.is_read and notification.read_at is not None


@pytest.mark.django_db
def test_mark_read_is_idempotent(notification):
    notification.mark_read()
    first = notification.read_at
    notification.mark_read()
    notification.refresh_from_db()
    assert notification.read_at == first


@pytest.mark.django_db
def test_is_editable_only_draft(draft_req):
    """BR-2: only drafts are editable."""
    assert draft_req.is_editable
    for status in ('submitted', 'approved', 'rejected', 'cancelled'):
        draft_req.status = status
        assert not draft_req.is_editable
