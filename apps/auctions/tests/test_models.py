"""Unit tests for Module 8 (E-Auction) model logic.

Mirrors apps/rfx/tests/test_models.py: numbering/uniqueness, choice defaults,
the append-only bid ledger basics, lifecycle properties and the bid-math
helpers (effective_decrement / required_next_max) on the Auction model.
"""
from decimal import Decimal

import pytest

from apps.auctions.models import (
    Auction, AuctionBid, AuctionLot, AuctionParticipant,
)

pytestmark = pytest.mark.django_db


# ---------- Auction: numbering / uniqueness / defaults ----------

def test_auction_status_default_is_draft(tenant, tenant_admin):
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-00099',
        title='Draft', created_by=tenant_admin,
    )
    assert a.status == 'draft'
    assert a.auction_type == 'reverse'
    assert a.decrement_type == 'amount'
    assert a.rank_visibility == 'rank_and_leading'
    assert a.currency == 'USD'
    assert a.is_editable is True


def test_auction_str_includes_number_and_title(draft_auction):
    assert draft_auction.auction_number in str(draft_auction)
    assert draft_auction.title in str(draft_auction)


def test_auction_number_format_is_zero_padded(draft_auction):
    # AUC-ACME-00001 — slug uppercased, 5-digit zero pad.
    assert draft_auction.auction_number == 'AUC-ACME-00001'
    assert draft_auction.auction_number.startswith('AUC-ACME-')
    assert draft_auction.auction_number.rsplit('-', 1)[1] == '00001'


def test_auction_unique_number_per_tenant(tenant, tenant_admin):
    Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-DUP-1',
        title='A', created_by=tenant_admin,
    )
    with pytest.raises(Exception):
        Auction.all_objects.create(
            tenant=tenant, auction_number='AUC-DUP-1',
            title='B', created_by=tenant_admin,
        )


def test_auction_same_number_allowed_across_tenants(tenant, other_tenant, tenant_admin):
    """unique_together is (tenant, auction_number) — same number, different tenant is fine."""
    Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-SHARED-1',
        title='Acme one', created_by=tenant_admin,
    )
    other = Auction.all_objects.create(
        tenant=other_tenant, auction_number='AUC-SHARED-1',
        title='Globex one',
    )
    assert other.pk is not None


# ---------- Auction: lifecycle properties ----------

def test_auction_is_editable_only_in_draft(draft_auction):
    draft_auction.status = 'draft'
    assert draft_auction.is_editable is True
    for s in ('scheduled', 'live', 'closed', 'awarded', 'cancelled'):
        draft_auction.status = s
        assert draft_auction.is_editable is False


def test_auction_is_live_only_when_live(draft_auction):
    for s in ('draft', 'scheduled', 'closed', 'awarded', 'cancelled'):
        draft_auction.status = s
        assert draft_auction.is_live is False
    draft_auction.status = 'live'
    assert draft_auction.is_live is True


def test_auction_can_cancel(draft_auction):
    for s in ('draft', 'scheduled', 'live'):
        draft_auction.status = s
        assert draft_auction.can_cancel is True
    for s in ('closed', 'awarded', 'cancelled'):
        draft_auction.status = s
        assert draft_auction.can_cancel is False


def test_auction_is_finished(draft_auction):
    for s in ('draft', 'scheduled', 'live'):
        draft_auction.status = s
        assert draft_auction.is_finished is False
    for s in ('closed', 'awarded', 'cancelled'):
        draft_auction.status = s
        assert draft_auction.is_finished is True


# ---------- Auction: seconds_remaining ----------

def test_seconds_remaining_zero_without_end_at(draft_auction):
    draft_auction.end_at = None
    assert draft_auction.seconds_remaining == 0


def test_seconds_remaining_positive_for_future_end(live_auction):
    # live_auction end_at is +1 day in the future.
    assert live_auction.seconds_remaining > 0


def test_seconds_remaining_zero_for_past_end(awarded_auction):
    # awarded_auction was closed, so end_at is now/past.
    assert awarded_auction.seconds_remaining == 0


# ---------- Auction: effective_decrement ----------

def test_effective_decrement_amount(draft_auction):
    # decrement_type='amount', decrement_value=50 -> always 50.00 regardless of best.
    assert draft_auction.decrement_type == 'amount'
    assert draft_auction.effective_decrement(None) == Decimal('50.00')
    assert draft_auction.effective_decrement(Decimal('900.00')) == Decimal('50.00')


def test_effective_decrement_percent_uses_best(tenant, tenant_admin):
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-00200',
        title='Percent', created_by=tenant_admin,
        starting_price=Decimal('1000.00'),
        decrement_type='percent', decrement_value=Decimal('10.00'),
    )
    # 10% of the current best (800) = 80.00
    assert a.effective_decrement(Decimal('800.00')) == Decimal('80.00')


def test_effective_decrement_percent_falls_back_to_starting_price(tenant, tenant_admin):
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-00201',
        title='Percent2', created_by=tenant_admin,
        starting_price=Decimal('1000.00'),
        decrement_type='percent', decrement_value=Decimal('10.00'),
    )
    # No best yet -> base is starting_price (1000) -> 10% = 100.00
    assert a.effective_decrement(None) == Decimal('100.00')


# ---------- Auction: required_next_max ----------

def test_required_next_max_is_starting_price_when_no_best(draft_auction):
    assert draft_auction.required_next_max(None) == draft_auction.starting_price
    assert draft_auction.required_next_max(None) == Decimal('1000.00')


def test_required_next_max_subtracts_decrement(draft_auction):
    # best 900, amount decrement 50 -> ceiling is 850.00
    assert draft_auction.required_next_max(Decimal('900.00')) == Decimal('850.00')


def test_required_next_max_floored_at_zero(tenant, tenant_admin):
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-00202',
        title='Tiny', created_by=tenant_admin,
        starting_price=Decimal('100.00'),
        decrement_type='amount', decrement_value=Decimal('50.00'),
    )
    # best 30 - 50 = -20 -> floored to 0.00
    assert a.required_next_max(Decimal('30.00')) == Decimal('0.00')


# ---------- Auction: total_budget ----------

def test_total_budget_sums_lot_estimates(draft_auction_ready):
    # one lot: 100 box x 10.00 = 1000.00
    assert draft_auction_ready.total_budget == Decimal('1000.00')


def test_total_budget_falls_back_to_starting_price_without_lots(draft_auction):
    # no lots -> fall back to starting_price
    assert draft_auction.total_budget == draft_auction.starting_price
    assert draft_auction.total_budget == Decimal('1000.00')


# ---------- AuctionLot ----------

def test_lot_estimated_line_total(draft_auction_ready):
    lot = draft_auction_ready.lots.first()
    assert lot.estimated_line_total == Decimal('1000.00')


def test_lot_str_includes_number_and_description(draft_auction_ready):
    lot = draft_auction_ready.lots.first()
    assert f'#{lot.lot_no}' in str(lot)
    assert lot.item_description in str(lot)


def test_lot_unique_per_auction_and_lot_no(tenant, draft_auction):
    AuctionLot.all_objects.create(
        tenant=tenant, auction=draft_auction, lot_no=1,
        item_description='First',
    )
    with pytest.raises(Exception):
        AuctionLot.all_objects.create(
            tenant=tenant, auction=draft_auction, lot_no=1,
            item_description='Dup lot_no',
        )


def test_lot_ordered_by_lot_no(tenant, draft_auction):
    AuctionLot.all_objects.create(
        tenant=tenant, auction=draft_auction, lot_no=2, item_description='B',
    )
    AuctionLot.all_objects.create(
        tenant=tenant, auction=draft_auction, lot_no=1, item_description='A',
    )
    descriptions = list(draft_auction.lots.values_list('item_description', flat=True))
    assert descriptions == ['A', 'B']


# ---------- AuctionParticipant ----------

def test_participant_status_default_is_invited(tenant, draft_auction, vendor_a):
    p = AuctionParticipant.all_objects.create(
        tenant=tenant, auction=draft_auction, vendor=vendor_a,
    )
    assert p.status == 'invited'
    assert p.bid_count == 0
    assert p.current_bid_amount is None
    assert p.current_rank is None
    assert p.is_winner is False


def test_participant_unique_per_auction_vendor(tenant, draft_auction, vendor_a):
    AuctionParticipant.all_objects.create(
        tenant=tenant, auction=draft_auction, vendor=vendor_a,
    )
    with pytest.raises(Exception):
        AuctionParticipant.all_objects.create(
            tenant=tenant, auction=draft_auction, vendor=vendor_a,
        )


def test_participant_str_includes_vendor_and_auction(tenant, draft_auction, vendor_a):
    p = AuctionParticipant.all_objects.create(
        tenant=tenant, auction=draft_auction, vendor=vendor_a,
    )
    assert vendor_a.legal_name in str(p)
    assert draft_auction.auction_number in str(p)


# ---------- AuctionBid: append-only ledger basics ----------

def test_bid_ledger_is_append_only(awarded_auction):
    """awarded_auction placed 3 bids — each is its own ledger row."""
    bids = list(AuctionBid.all_objects.filter(auction=awarded_auction))
    assert len(bids) == 3
    amounts = {b.amount for b in bids}
    assert amounts == {Decimal('900.00'), Decimal('840.00'), Decimal('780.00')}


def test_bid_default_source_is_portal(tenant, draft_auction, vendor_a):
    participant = AuctionParticipant.all_objects.create(
        tenant=tenant, auction=draft_auction, vendor=vendor_a,
    )
    bid = AuctionBid.all_objects.create(
        tenant=tenant, auction=draft_auction, participant=participant,
        vendor=vendor_a, amount=Decimal('500.00'),
    )
    assert bid.source == 'portal'
    assert bid.was_leading is False
    assert bid.triggered_extension is False


def test_bid_ordered_newest_first(awarded_auction):
    bids = list(AuctionBid.all_objects.filter(auction=awarded_auction))
    placed = [b.placed_at for b in bids]
    assert placed == sorted(placed, reverse=True)


def test_bid_str_includes_vendor_amount_and_auction(tenant, draft_auction, vendor_a):
    participant = AuctionParticipant.all_objects.create(
        tenant=tenant, auction=draft_auction, vendor=vendor_a,
    )
    bid = AuctionBid.all_objects.create(
        tenant=tenant, auction=draft_auction, participant=participant,
        vendor=vendor_a, amount=Decimal('500.00'),
    )
    label = str(bid)
    assert vendor_a.legal_name in label
    assert '500.00' in label
    assert draft_auction.auction_number in label
