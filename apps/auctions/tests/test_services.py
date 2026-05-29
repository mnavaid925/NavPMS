"""Unit tests for Module 8 (E-Auction) service layer.

Mirrors apps/rfx/tests/test_services.py: permission helpers, the visibility gate,
numbering, publish validation, lifecycle, participants, the bidding core
(decrement + ceiling enforcement, rank recompute, anti-snipe extension), the
blind vendor payload, finalize/award and analytics.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import set_current_tenant
from apps.auctions.models import Auction, AuctionLot, AuctionParticipant
from apps.auctions.services import (
    accept_invitation, auction_analytics, auction_state_for,
    can_manage_auction, can_monitor_auction, cancel_auction, close_auction,
    compute_auction_savings, current_best, decline_invitation,
    finalize_auction, invite_vendors, live_payload, next_auction_number,
    place_bid, publish_auction, recompute_ranks, refresh_auction_state,
    remove_participant, start_auction, tenant_auction_metrics,
    validate_auction_for_publish, withdraw_participant,
)

pytestmark = pytest.mark.django_db


# ---------- Permission helpers ----------

def test_can_manage_auction_for_tenant_admin(tenant_admin):
    assert can_manage_auction(tenant_admin)


def test_can_manage_auction_for_buyer(buyer_user):
    assert can_manage_auction(buyer_user)


def test_can_manage_auction_for_procurement_manager(procurement_manager):
    # No is_tenant_admin — exercises the MANAGE_ROLES membership branch.
    assert can_manage_auction(procurement_manager)


def test_can_manage_auction_rejects_approver(approver):
    # Approver is monitor-only, NOT a manager.
    assert not can_manage_auction(approver)


def test_can_manage_auction_rejects_requester(requester):
    assert not can_manage_auction(requester)


def test_can_monitor_auction_includes_approver(approver):
    assert can_monitor_auction(approver)


def test_can_monitor_auction_includes_buyer(buyer_user):
    assert can_monitor_auction(buyer_user)


def test_can_monitor_auction_rejects_requester(requester):
    assert not can_monitor_auction(requester)


def test_can_manage_auction_rejects_unauthenticated_user():
    from django.contrib.auth.models import AnonymousUser
    assert not can_manage_auction(AnonymousUser())


# ---------- Visibility gate ----------

def test_auction_state_for_buyer_is_full(tenant_admin, live_auction):
    assert auction_state_for(tenant_admin, live_auction) == 'full'


def test_auction_state_for_approver_is_full(approver, live_auction):
    assert auction_state_for(approver, live_auction) == 'full'


def test_auction_state_for_participant_vendor_is_self(vendor_portal_user, live_auction):
    # vendor_a is a participant of live_auction.
    assert auction_state_for(vendor_portal_user, live_auction) == 'self'


def test_auction_state_for_non_participant_vendor_is_none(
    vendor_b_portal_user, draft_auction,
):
    # vendor_b is NOT a participant of draft_auction (no participants at all).
    assert auction_state_for(vendor_b_portal_user, draft_auction) is None


def test_auction_state_for_requester_is_none(requester, live_auction):
    assert auction_state_for(requester, live_auction) is None


def test_auction_state_for_anonymous_is_none(live_auction):
    from django.contrib.auth.models import AnonymousUser
    assert auction_state_for(AnonymousUser(), live_auction) is None


# ---------- Numbering ----------

def test_next_auction_number_is_zero_padded(tenant):
    assert next_auction_number(tenant) == 'AUC-ACME-00001'


def test_next_auction_number_increments(tenant, draft_auction):
    # draft_auction already holds AUC-ACME-00001.
    assert next_auction_number(tenant) == 'AUC-ACME-00002'


def test_next_auction_number_uses_tenant_slug(other_tenant):
    # slug = ('globex')[:6].upper() = 'GLOBEX'
    assert next_auction_number(other_tenant) == 'AUC-GLOBEX-00001'


# ---------- Publish validation ----------

def test_validate_publish_blocked_without_lots(tenant, tenant_admin, vendor_a):
    now = timezone.now()
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-10001', title='No lots',
        created_by=tenant_admin, starting_price=Decimal('1000.00'),
        decrement_value=Decimal('50.00'),
        start_at=now + timedelta(hours=1), end_at=now + timedelta(hours=2),
    )
    invite_vendors(a, [vendor_a.pk], tenant_admin)
    with pytest.raises(ValidationError) as exc:
        validate_auction_for_publish(a)
    assert any('lot' in m.lower() for m in exc.value.messages)


def test_validate_publish_blocked_without_participants(tenant, tenant_admin):
    now = timezone.now()
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-10002', title='No vendors',
        created_by=tenant_admin, starting_price=Decimal('1000.00'),
        decrement_value=Decimal('50.00'),
        start_at=now + timedelta(hours=1), end_at=now + timedelta(hours=2),
    )
    AuctionLot.all_objects.create(
        tenant=tenant, auction=a, lot_no=1, item_description='Item',
    )
    with pytest.raises(ValidationError) as exc:
        validate_auction_for_publish(a)
    assert any('invite' in m.lower() or 'vendor' in m.lower() for m in exc.value.messages)


def test_validate_publish_blocked_without_window(tenant, tenant_admin, vendor_a):
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-10003', title='No window',
        created_by=tenant_admin, starting_price=Decimal('1000.00'),
        decrement_value=Decimal('50.00'),
    )
    AuctionLot.all_objects.create(
        tenant=tenant, auction=a, lot_no=1, item_description='Item',
    )
    invite_vendors(a, [vendor_a.pk], tenant_admin)
    with pytest.raises(ValidationError) as exc:
        validate_auction_for_publish(a)
    assert any('start' in m.lower() and 'end' in m.lower() for m in exc.value.messages)


def test_validate_publish_blocked_when_start_after_end(tenant, tenant_admin, vendor_a):
    now = timezone.now()
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-10004', title='Bad window',
        created_by=tenant_admin, starting_price=Decimal('1000.00'),
        decrement_value=Decimal('50.00'),
        start_at=now + timedelta(hours=2), end_at=now + timedelta(hours=1),
    )
    AuctionLot.all_objects.create(
        tenant=tenant, auction=a, lot_no=1, item_description='Item',
    )
    invite_vendors(a, [vendor_a.pk], tenant_admin)
    with pytest.raises(ValidationError) as exc:
        validate_auction_for_publish(a)
    assert any('after' in m.lower() for m in exc.value.messages)


def test_validate_publish_blocked_when_starting_price_zero(tenant, tenant_admin, vendor_a):
    now = timezone.now()
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-10005', title='Zero price',
        created_by=tenant_admin, starting_price=Decimal('0.00'),
        decrement_value=Decimal('50.00'),
        start_at=now + timedelta(hours=1), end_at=now + timedelta(hours=2),
    )
    AuctionLot.all_objects.create(
        tenant=tenant, auction=a, lot_no=1, item_description='Item',
    )
    invite_vendors(a, [vendor_a.pk], tenant_admin)
    with pytest.raises(ValidationError) as exc:
        validate_auction_for_publish(a)
    assert any('starting price' in m.lower() for m in exc.value.messages)


def test_validate_publish_blocked_when_decrement_zero(tenant, tenant_admin, vendor_a):
    now = timezone.now()
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-10006', title='Zero decrement',
        created_by=tenant_admin, starting_price=Decimal('1000.00'),
        decrement_value=Decimal('0.00'),
        start_at=now + timedelta(hours=1), end_at=now + timedelta(hours=2),
    )
    AuctionLot.all_objects.create(
        tenant=tenant, auction=a, lot_no=1, item_description='Item',
    )
    invite_vendors(a, [vendor_a.pk], tenant_admin)
    with pytest.raises(ValidationError) as exc:
        validate_auction_for_publish(a)
    assert any('decrement' in m.lower() for m in exc.value.messages)


def test_validate_publish_blocked_when_reserve_exceeds_starting(tenant, tenant_admin, vendor_a):
    now = timezone.now()
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-10007', title='Bad reserve',
        created_by=tenant_admin, starting_price=Decimal('1000.00'),
        reserve_price=Decimal('1200.00'), decrement_value=Decimal('50.00'),
        start_at=now + timedelta(hours=1), end_at=now + timedelta(hours=2),
    )
    AuctionLot.all_objects.create(
        tenant=tenant, auction=a, lot_no=1, item_description='Item',
    )
    invite_vendors(a, [vendor_a.pk], tenant_admin)
    with pytest.raises(ValidationError) as exc:
        validate_auction_for_publish(a)
    assert any('reserve' in m.lower() for m in exc.value.messages)


def test_validate_publish_succeeds_and_returns_warnings_list(draft_auction_ready):
    warnings = validate_auction_for_publish(draft_auction_ready)
    assert isinstance(warnings, list)


# ---------- Lifecycle ----------

def test_publish_transitions_draft_to_scheduled(draft_auction_ready, tenant_admin):
    publish_auction(draft_auction_ready, tenant_admin)
    draft_auction_ready.refresh_from_db()
    assert draft_auction_ready.status == 'scheduled'


def test_publish_does_not_auto_start(draft_auction_ready, tenant_admin):
    publish_auction(draft_auction_ready, tenant_admin)
    draft_auction_ready.refresh_from_db()
    assert draft_auction_ready.status != 'live'


def test_publish_only_from_draft(scheduled_auction, tenant_admin):
    with pytest.raises(ValidationError):
        publish_auction(scheduled_auction, tenant_admin)


def test_start_transitions_scheduled_to_live(scheduled_auction, tenant_admin):
    start_auction(scheduled_auction, tenant_admin)
    scheduled_auction.refresh_from_db()
    assert scheduled_auction.status == 'live'


def test_start_only_from_scheduled(draft_auction, tenant_admin):
    with pytest.raises(ValidationError):
        start_auction(draft_auction, tenant_admin)


def test_close_transitions_live_to_closed(live_auction, tenant_admin):
    close_auction(live_auction, tenant_admin)
    live_auction.refresh_from_db()
    assert live_auction.status == 'closed'


def test_close_only_from_live(scheduled_auction, tenant_admin):
    with pytest.raises(ValidationError):
        close_auction(scheduled_auction, tenant_admin)


def test_cancel_records_reason(draft_auction, tenant_admin):
    cancel_auction(draft_auction, tenant_admin, 'No longer needed')
    draft_auction.refresh_from_db()
    assert draft_auction.status == 'cancelled'
    assert draft_auction.cancelled_reason == 'No longer needed'
    assert draft_auction.cancelled_at is not None


def test_cancel_blocked_when_finished(awarded_auction, tenant_admin):
    with pytest.raises(ValidationError):
        cancel_auction(awarded_auction, tenant_admin, 'too late')


# ---------- Lazy clock ----------

def test_refresh_auction_state_scheduled_to_live(scheduled_auction, tenant_admin):
    # Force start_at into the past, then refresh.
    obj = Auction.all_objects.get(pk=scheduled_auction.pk)
    obj.start_at = timezone.now() - timedelta(minutes=1)
    obj.save(update_fields=['start_at'])
    refresh_auction_state(obj, tenant_admin)
    obj.refresh_from_db()
    assert obj.status == 'live'


def test_refresh_auction_state_live_to_closed(live_auction, tenant_admin):
    # Force end_at into the past, then refresh.
    obj = Auction.all_objects.get(pk=live_auction.pk)
    obj.end_at = timezone.now() - timedelta(minutes=1)
    obj.save(update_fields=['end_at'])
    refresh_auction_state(obj, tenant_admin)
    obj.refresh_from_db()
    assert obj.status == 'closed'


def test_refresh_auction_state_is_noop_when_no_clock_change(draft_auction, tenant_admin):
    refresh_auction_state(draft_auction, tenant_admin)
    draft_auction.refresh_from_db()
    assert draft_auction.status == 'draft'


# ---------- Participants ----------

def test_invite_vendors_returns_new_participants(draft_auction, vendor_a, vendor_b, tenant_admin):
    invited = invite_vendors(draft_auction, [vendor_a.pk, vendor_b.pk], tenant_admin)
    assert len(invited) == 2
    assert {p.vendor_id for p in invited} == {vendor_a.pk, vendor_b.pk}


def test_invite_vendors_excludes_blocked(draft_auction, vendor_a, blocked_vendor, tenant_admin):
    invited = invite_vendors(
        draft_auction, [vendor_a.pk, blocked_vendor.pk], tenant_admin)
    invited_vendor_ids = {p.vendor_id for p in invited}
    assert vendor_a.pk in invited_vendor_ids
    assert blocked_vendor.pk not in invited_vendor_ids
    assert not AuctionParticipant.all_objects.filter(
        auction=draft_auction, vendor=blocked_vendor).exists()


def test_invite_vendors_skips_duplicates(draft_auction, vendor_a, tenant_admin):
    first = invite_vendors(draft_auction, [vendor_a.pk], tenant_admin)
    assert len(first) == 1
    second = invite_vendors(draft_auction, [vendor_a.pk], tenant_admin)
    assert second == []  # already invited -> no new participant
    assert AuctionParticipant.all_objects.filter(
        auction=draft_auction, vendor=vendor_a).count() == 1


def test_remove_participant_succeeds_before_bidding(scheduled_auction, vendor_a, tenant_admin):
    participant = AuctionParticipant.all_objects.get(
        auction=scheduled_auction, vendor=vendor_a)
    remove_participant(participant, tenant_admin)
    assert not AuctionParticipant.all_objects.filter(pk=participant.pk).exists()


def test_remove_participant_blocked_after_bid(awarded_auction, vendor_a, tenant_admin):
    participant = AuctionParticipant.all_objects.get(
        auction=awarded_auction, vendor=vendor_a)
    # vendor_a placed a bid in awarded_auction.
    assert participant.bid_count > 0
    with pytest.raises(ValidationError):
        remove_participant(participant, tenant_admin)


def test_accept_invitation_sets_accepted(scheduled_auction, vendor_a, tenant_admin):
    participant = AuctionParticipant.all_objects.get(
        auction=scheduled_auction, vendor=vendor_a)
    accept_invitation(participant, tenant_admin)
    participant.refresh_from_db()
    assert participant.status == 'accepted'
    assert participant.responded_at is not None


def test_decline_invitation_sets_declined(scheduled_auction, vendor_a, tenant_admin):
    participant = AuctionParticipant.all_objects.get(
        auction=scheduled_auction, vendor=vendor_a)
    decline_invitation(participant, tenant_admin)
    participant.refresh_from_db()
    assert participant.status == 'declined'


def test_withdraw_participant_sets_withdrawn(live_auction, vendor_a, tenant_admin):
    participant = AuctionParticipant.all_objects.get(
        auction=live_auction, vendor=vendor_a)
    withdraw_participant(participant, tenant_admin)
    participant.refresh_from_db()
    assert participant.status == 'withdrawn'


def test_withdraw_participant_blocked_when_not_active(scheduled_auction, vendor_a, tenant_admin):
    participant = AuctionParticipant.all_objects.get(
        auction=scheduled_auction, vendor=vendor_a)
    decline_invitation(participant, tenant_admin)
    participant.refresh_from_db()
    with pytest.raises(ValidationError):
        withdraw_participant(participant, tenant_admin)


# ---------- Bidding core: happy path ----------

def test_place_bid_happy_path_rank_one(live_auction, vendor_a, tenant_admin):
    bid = place_bid(live_auction, vendor_a, Decimal('900.00'), tenant_admin)
    assert bid.amount == Decimal('900.00')
    assert bid.was_leading is True
    participant = AuctionParticipant.all_objects.get(
        auction=live_auction, vendor=vendor_a)
    assert participant.current_rank == 1
    assert participant.current_bid_amount == Decimal('900.00')
    assert participant.bid_count == 1


def test_place_bid_blocked_when_not_live(scheduled_auction, vendor_a, tenant_admin):
    with pytest.raises(ValidationError):
        place_bid(scheduled_auction, vendor_a, Decimal('900.00'), tenant_admin)


def test_place_bid_blocked_for_non_participant(live_auction, blocked_vendor, tenant_admin):
    # blocked_vendor was never invited to live_auction.
    with pytest.raises(ValidationError):
        place_bid(live_auction, blocked_vendor, Decimal('900.00'), tenant_admin)


def test_place_bid_rejects_zero_amount(live_auction, vendor_a, tenant_admin):
    with pytest.raises(ValidationError):
        place_bid(live_auction, vendor_a, Decimal('0.00'), tenant_admin)


# ---------- Bidding core: ceiling enforcement ----------

def test_place_bid_rejects_above_starting_price(live_auction, vendor_a, tenant_admin):
    # starting_price is 1000; 1001 exceeds the ceiling.
    with pytest.raises(ValidationError):
        place_bid(live_auction, vendor_a, Decimal('1001.00'), tenant_admin)


def test_place_bid_allows_exactly_starting_price(live_auction, vendor_a, tenant_admin):
    bid = place_bid(live_auction, vendor_a, Decimal('1000.00'), tenant_admin)
    assert bid.amount == Decimal('1000.00')


# ---------- Bidding core: decrement enforcement ----------

def test_place_bid_rejects_above_required_decrement(live_auction, vendor_a, vendor_b, tenant_admin):
    place_bid(live_auction, vendor_a, Decimal('900.00'), tenant_admin)
    # best is 900, decrement 50 -> next must be <= 850. 870 is rejected.
    with pytest.raises(ValidationError):
        place_bid(live_auction, vendor_b, Decimal('870.00'), tenant_admin)


def test_place_bid_accepts_exactly_required_decrement(live_auction, vendor_a, vendor_b, tenant_admin):
    place_bid(live_auction, vendor_a, Decimal('900.00'), tenant_admin)
    bid = place_bid(live_auction, vendor_b, Decimal('850.00'), tenant_admin)
    assert bid.amount == Decimal('850.00')
    assert bid.was_leading is True


# ---------- Bidding core: rank recompute across vendors ----------

def test_lowering_across_vendors_recomputes_ranks(live_auction, vendor_a, vendor_b, vendor_c, tenant_admin):
    place_bid(live_auction, vendor_a, Decimal('900.00'), tenant_admin)
    place_bid(live_auction, vendor_b, Decimal('840.00'), tenant_admin)
    place_bid(live_auction, vendor_c, Decimal('780.00'), tenant_admin)

    p_a = AuctionParticipant.all_objects.get(auction=live_auction, vendor=vendor_a)
    p_b = AuctionParticipant.all_objects.get(auction=live_auction, vendor=vendor_b)
    p_c = AuctionParticipant.all_objects.get(auction=live_auction, vendor=vendor_c)
    assert p_c.current_rank == 1
    assert p_b.current_rank == 2
    assert p_a.current_rank == 3
    assert current_best(live_auction) == Decimal('780.00')


def test_recompute_ranks_clears_rank_for_withdrawn(live_auction, vendor_a, vendor_b, tenant_admin):
    place_bid(live_auction, vendor_a, Decimal('900.00'), tenant_admin)
    place_bid(live_auction, vendor_b, Decimal('850.00'), tenant_admin)
    p_b = AuctionParticipant.all_objects.get(auction=live_auction, vendor=vendor_b)
    withdraw_participant(p_b, tenant_admin)  # also recomputes ranks
    p_a = AuctionParticipant.all_objects.get(auction=live_auction, vendor=vendor_a)
    p_b.refresh_from_db()
    assert p_a.current_rank == 1
    assert p_b.current_rank is None


# ---------- Bidding core: anti-snipe extension ----------

def test_anti_snipe_extends_end_at(tenant, tenant_admin, vendor_a):
    """A valid bid inside the anti-snipe window extends end_at and increments
    extension_count, and the bid is flagged triggered_extension."""
    set_current_tenant(tenant)
    now = timezone.now()
    a = Auction.all_objects.create(
        tenant=tenant, auction_number='AUC-ACME-20001', title='Snipe',
        created_by=tenant_admin, starting_price=Decimal('1000.00'),
        decrement_value=Decimal('50.00'), decrement_type='amount',
        start_at=now - timedelta(minutes=5),
        end_at=now + timedelta(seconds=30),  # inside the 120s window
        anti_snipe_seconds=120, anti_snipe_extension_seconds=120,
        status='live',
    )
    AuctionLot.all_objects.create(
        tenant=tenant, auction=a, lot_no=1, item_description='Item',
    )
    invite_vendors(a, [vendor_a.pk], tenant_admin)

    original_end = a.end_at
    bid = place_bid(a, vendor_a, Decimal('900.00'), tenant_admin)
    a.refresh_from_db()

    assert bid.triggered_extension is True
    assert a.extension_count == 1
    assert a.end_at > original_end


def test_no_anti_snipe_when_outside_window(live_auction, vendor_a, tenant_admin):
    # live_auction end_at is +1 day, far outside the 120s window.
    bid = place_bid(live_auction, vendor_a, Decimal('900.00'), tenant_admin)
    live_auction.refresh_from_db()
    assert bid.triggered_extension is False
    assert live_auction.extension_count == 0


# ---------- Live payload: buyer full vs vendor blind ----------

def test_live_payload_buyer_full_has_leaderboard_with_names(live_auction, tenant_admin, vendor_a):
    # Live auction with active participants — the full buyer leaderboard includes
    # every active vendor by name. (On an awarded auction participants are flipped
    # to won/lost and drop out of the active-only leaderboard, by design.)
    place_bid(live_auction, vendor_a, Decimal('900.00'), tenant_admin)
    payload = live_payload(live_auction, tenant_admin)
    assert payload['view'] == 'full'
    assert 'leaderboard' in payload
    names = {row['vendor_name'] for row in payload['leaderboard']}
    # The full buyer view DOES include competitor identities. The leaderboard
    # vendor_name is str(vendor) ("VND-... — <legal_name>"), so assert the
    # legal_name appears within one of those composite labels.
    assert any(vendor_a.legal_name in name for name in names)


def test_live_payload_vendor_self_is_blind(live_auction, vendor_portal_user,
                                           vendor_b_portal_user, vendor_a, vendor_b,
                                           tenant_admin):
    """vendor_a's self payload must NOT leak vendor_b's legal_name (blind)."""
    place_bid(live_auction, vendor_a, Decimal('900.00'), tenant_admin)
    place_bid(live_auction, vendor_b, Decimal('850.00'), tenant_admin)

    payload = live_payload(live_auction, vendor_portal_user)
    assert payload['view'] == 'self'
    assert 'my_rank' in payload
    assert 'my_bid' in payload
    assert 'next_valid_max' in payload
    assert 'leaderboard' not in payload  # default rank_and_leading

    # Canary: the competitor's legal_name appears nowhere in the self payload.
    import json
    blob = json.dumps(payload)
    assert vendor_b.legal_name not in blob
    # vendor_a sees their own bid (900) and the leading price (850 from vendor_b).
    assert payload['my_bid'] == '900.00'
    assert payload['leading_price'] == '850.00'


# ---------- Finalize / award ----------

def test_finalize_picks_lowest_bid_winner(awarded_auction, vendor_c):
    awarded_auction.refresh_from_db()
    assert awarded_auction.status == 'awarded'
    assert awarded_auction.awarded_vendor_id == vendor_c.pk
    assert awarded_auction.awarded_amount == Decimal('780.00')
    assert awarded_auction.awarded_at is not None
    winner = AuctionParticipant.all_objects.get(
        auction=awarded_auction, vendor=vendor_c)
    assert winner.status == 'won'
    assert winner.is_winner is True


def test_finalize_flips_losers_to_lost(awarded_auction, vendor_a, vendor_b):
    p_a = AuctionParticipant.all_objects.get(auction=awarded_auction, vendor=vendor_a)
    p_b = AuctionParticipant.all_objects.get(auction=awarded_auction, vendor=vendor_b)
    assert p_a.status == 'lost'
    assert p_b.status == 'lost'
    assert p_a.is_winner is False


def test_finalize_raises_when_no_valid_bids(live_auction, tenant_admin):
    # Close with no bids placed, then finalize -> no winner.
    close_auction(live_auction, tenant_admin)
    with pytest.raises(ValidationError) as exc:
        finalize_auction(live_auction, tenant_admin)
    assert 'No valid bids to award.' in str(exc.value)


def test_finalize_with_explicit_winner_override(live_auction, vendor_a, vendor_b, tenant_admin):
    place_bid(live_auction, vendor_a, Decimal('900.00'), tenant_admin)
    place_bid(live_auction, vendor_b, Decimal('850.00'), tenant_admin)
    close_auction(live_auction, tenant_admin)
    # Lowest is vendor_b (850), but override to vendor_a.
    finalize_auction(live_auction, tenant_admin, winner_vendor=vendor_a)
    live_auction.refresh_from_db()
    assert live_auction.awarded_vendor_id == vendor_a.pk
    assert live_auction.awarded_amount == Decimal('900.00')


# ---------- Analytics ----------

def test_compute_auction_savings_math(awarded_auction):
    figures = compute_auction_savings(awarded_auction)
    # baseline = total_budget (100 x 10 = 1000), awarded = 780, savings = 220.
    assert figures['baseline'] == Decimal('1000.00')
    assert figures['awarded'] == Decimal('780.00')
    assert figures['savings'] == Decimal('220.00')
    assert figures['savings_pct'] == Decimal('22.00')


def test_tenant_auction_metrics_shape(tenant, awarded_auction, draft_auction):
    metrics = tenant_auction_metrics(tenant)
    assert metrics['total_auctions'] >= 2
    assert metrics['awarded'] >= 1
    assert metrics['draft'] >= 1
    assert 'by_status' in metrics
    assert metrics['total_awarded'] == Decimal('780.00')
    assert metrics['total_baseline'] == Decimal('1000.00')


def test_auction_analytics_shape_and_price_drop_curve(awarded_auction):
    analytics = auction_analytics(awarded_auction)
    assert analytics['participant_count'] == 3
    assert analytics['bidder_count'] == 3
    assert analytics['bid_count'] == 3
    assert analytics['extension_count'] == 0
    assert analytics['duration_seconds'] is not None
    assert 'savings' in analytics
    # Price-drop curve: only the running-best decreasing bids (900 -> 840 -> 780).
    curve = analytics['price_drop_curve']
    prices = [row['price'] for row in curve]
    assert prices == ['900.00', '840.00', '780.00']
