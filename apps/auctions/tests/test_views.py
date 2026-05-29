"""View tests for Module 8 - E-Auction Management (apps/auctions).

Mirrors the layout/style of apps/rfx/tests/test_views.py: buyer-facing CRUD
happy paths, lifecycle transitions, monitor console + JSON state, results,
analytics, the permission gate, and the vendor-portal bidding surface.
"""
import json
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.auctions.models import Auction, AuctionLot, AuctionParticipant, AuctionBid

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Buyer CRUD - happy paths
# ---------------------------------------------------------------------------
class TestAuctionList:
    def test_list_200_for_buyer(self, client, buyer_user, draft_auction):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:auction_list"))
        assert resp.status_code == 200
        assert draft_auction.auction_number.encode() in resp.content

    def test_list_filter_retains_status(self, client, buyer_user, draft_auction, live_auction):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:auction_list"), {"status": "draft"})
        assert resp.status_code == 200
        # draft row present, live row filtered out
        assert draft_auction.auction_number.encode() in resp.content
        assert live_auction.auction_number.encode() not in resp.content
        # selected filter value is retained in the markup
        assert b"draft" in resp.content

    def test_list_filter_by_type_and_q_does_not_500(self, client, buyer_user, draft_auction):
        client.force_login(buyer_user)
        resp = client.get(
            reverse("auctions:auction_list"),
            {"type": draft_auction.auction_type, "q": draft_auction.title, "category": ""},
        )
        assert resp.status_code == 200


class TestAuctionCreate:
    def test_create_get_200(self, client, buyer_user):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:auction_create"))
        assert resp.status_code == 200

    def test_create_post_creates_auction(self, client, buyer_user, tenant):
        client.force_login(buyer_user)
        before = Auction.all_objects.filter(tenant=tenant).count()
        resp = client.post(
            reverse("auctions:auction_create"),
            {
                "title": "Stationery Reverse Auction",
                "auction_type": "reverse",
                "currency": "USD",
                "starting_price": "5000",
                "reserve_price": "4000",
                "decrement_type": "amount",
                "decrement_value": "100",
                "anti_snipe_seconds": "120",
                "anti_snipe_extension_seconds": "120",
                "max_extensions": "10",
                "rank_visibility": "rank_and_leading",
                "description": "Test auction",
            },
        )
        assert resp.status_code in (302, 303), getattr(resp, "context", None) and resp.context["form"].errors
        after = Auction.all_objects.filter(tenant=tenant).count()
        assert after == before + 1


class TestAuctionDetail:
    def test_detail_200(self, client, buyer_user, draft_auction):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:auction_detail", kwargs={"pk": draft_auction.pk}))
        assert resp.status_code == 200
        assert draft_auction.auction_number.encode() in resp.content


class TestAuctionEdit:
    def test_edit_get_200_for_draft(self, client, buyer_user, draft_auction):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:auction_edit", kwargs={"pk": draft_auction.pk}))
        assert resp.status_code == 200

    def test_edit_post_updates_draft(self, client, buyer_user, draft_auction):
        client.force_login(buyer_user)
        resp = client.post(
            reverse("auctions:auction_edit", kwargs={"pk": draft_auction.pk}),
            {
                "title": "Renamed Auction",
                "auction_type": draft_auction.auction_type,
                "currency": draft_auction.currency,
                "starting_price": "1000",
                "reserve_price": "800",
                "decrement_type": "amount",
                "decrement_value": "50",
                "anti_snipe_seconds": "120",
                "anti_snipe_extension_seconds": "120",
                "max_extensions": "10",
                "rank_visibility": "rank_and_leading",
                "description": "",
            },
        )
        assert resp.status_code in (302, 303), getattr(resp, "context", None) and resp.context["form"].errors
        refreshed = Auction.all_objects.get(pk=draft_auction.pk)
        assert refreshed.title == "Renamed Auction"

    def test_edit_non_draft_redirects(self, client, buyer_user, live_auction):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:auction_edit", kwargs={"pk": live_auction.pk}))
        # non-editable -> bounced back (no 200 edit form)
        assert resp.status_code in (302, 303)


class TestAuctionDelete:
    def test_delete_draft(self, client, buyer_user, draft_auction):
        client.force_login(buyer_user)
        pk = draft_auction.pk
        resp = client.post(reverse("auctions:auction_delete", kwargs={"pk": pk}))
        assert resp.status_code in (302, 303)
        assert not Auction.all_objects.filter(pk=pk).exists()

    def test_delete_non_draft_blocked(self, client, buyer_user, live_auction):
        client.force_login(buyer_user)
        pk = live_auction.pk
        resp = client.post(reverse("auctions:auction_delete", kwargs={"pk": pk}))
        assert resp.status_code in (302, 303)
        # live auction is NOT deleted
        assert Auction.all_objects.filter(pk=pk).exists()


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
class TestLifecycle:
    def test_publish_moves_to_scheduled(self, client, buyer_user, draft_auction_ready):
        client.force_login(buyer_user)
        resp = client.post(reverse("auctions:auction_publish", kwargs={"pk": draft_auction_ready.pk}))
        assert resp.status_code in (302, 303)
        refreshed = Auction.all_objects.get(pk=draft_auction_ready.pk)
        assert refreshed.status == "scheduled"

    def test_start_moves_to_live(self, client, buyer_user, scheduled_auction):
        client.force_login(buyer_user)
        resp = client.post(reverse("auctions:auction_start", kwargs={"pk": scheduled_auction.pk}))
        assert resp.status_code in (302, 303)
        refreshed = Auction.all_objects.get(pk=scheduled_auction.pk)
        assert refreshed.status == "live"

    def test_close_moves_to_closed(self, client, buyer_user, live_auction):
        client.force_login(buyer_user)
        resp = client.post(reverse("auctions:auction_close", kwargs={"pk": live_auction.pk}))
        assert resp.status_code in (302, 303)
        refreshed = Auction.all_objects.get(pk=live_auction.pk)
        assert refreshed.status == "closed"

    def test_cancel_moves_to_cancelled(self, client, buyer_user, scheduled_auction):
        client.force_login(buyer_user)
        resp = client.post(
            reverse("auctions:auction_cancel", kwargs={"pk": scheduled_auction.pk}),
            {"reason": "No longer required"},
        )
        assert resp.status_code in (302, 303)
        refreshed = Auction.all_objects.get(pk=scheduled_auction.pk)
        assert refreshed.status == "cancelled"


# ---------------------------------------------------------------------------
# Lots (draft only)
# ---------------------------------------------------------------------------
class TestLots:
    def test_lot_add(self, client, buyer_user, draft_auction):
        client.force_login(buyer_user)
        before = AuctionLot.all_objects.filter(auction=draft_auction).count()
        resp = client.post(
            reverse("auctions:lot_create", kwargs={"pk": draft_auction.pk}),
            {
                "lot_no": "1",
                "title": "Lot One",
                "item_description": "Office chairs",
                "uom": "EA",
                "quantity": "10",
                "est_unit_price": "100",
                "account_code": "",
                "notes": "",
            },
        )
        assert resp.status_code in (302, 303)
        after = AuctionLot.all_objects.filter(auction=draft_auction).count()
        assert after == before + 1

    def test_lot_edit(self, client, buyer_user, draft_auction_ready):
        client.force_login(buyer_user)
        lot = AuctionLot.all_objects.filter(auction=draft_auction_ready).first()
        assert lot is not None
        resp = client.post(
            reverse("auctions:lot_edit", kwargs={"pk": draft_auction_ready.pk, "lot_pk": lot.pk}),
            {
                "lot_no": str(lot.lot_no),
                "title": "Edited lot title",
                "item_description": lot.item_description,
                "uom": lot.uom,
                "quantity": str(lot.quantity),
                "est_unit_price": str(lot.est_unit_price or "0"),
                "account_code": lot.account_code or "",
                "notes": "",
            },
        )
        assert resp.status_code in (302, 303)
        refreshed = AuctionLot.all_objects.get(pk=lot.pk)
        assert refreshed.title == "Edited lot title"

    def test_lot_delete(self, client, buyer_user, draft_auction_ready):
        client.force_login(buyer_user)
        lot = AuctionLot.all_objects.filter(auction=draft_auction_ready).first()
        assert lot is not None
        lot_pk = lot.pk
        resp = client.post(
            reverse("auctions:lot_delete", kwargs={"pk": draft_auction_ready.pk, "lot_pk": lot_pk})
        )
        assert resp.status_code in (302, 303)
        assert not AuctionLot.all_objects.filter(pk=lot_pk).exists()


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------
class TestParticipants:
    def test_participant_add_invites(self, client, buyer_user, draft_auction, vendor_a, vendor_b):
        client.force_login(buyer_user)
        before = AuctionParticipant.all_objects.filter(auction=draft_auction).count()
        resp = client.post(
            reverse("auctions:participant_add", kwargs={"pk": draft_auction.pk}),
            {"vendors": [str(vendor_a.pk), str(vendor_b.pk)]},
        )
        assert resp.status_code in (302, 303)
        after = AuctionParticipant.all_objects.filter(auction=draft_auction).count()
        assert after > before

    def test_participant_remove(self, client, buyer_user, draft_auction_ready):
        client.force_login(buyer_user)
        part = AuctionParticipant.all_objects.filter(auction=draft_auction_ready).first()
        assert part is not None
        part_pk = part.pk
        resp = client.post(
            reverse(
                "auctions:participant_remove",
                kwargs={"pk": draft_auction_ready.pk, "participant_pk": part_pk},
            )
        )
        assert resp.status_code in (302, 303)
        assert not AuctionParticipant.all_objects.filter(pk=part_pk).exists()


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class TestDocuments:
    def test_document_add(self, client, buyer_user, draft_auction):
        from django.core.files.uploadedfile import SimpleUploadedFile

        client.force_login(buyer_user)
        upload = SimpleUploadedFile("terms.pdf", b"%PDF-1.4 small file", content_type="application/pdf")
        resp = client.post(
            reverse("auctions:document_add", kwargs={"pk": draft_auction.pk}),
            {"title": "Terms", "file": upload},
        )
        assert resp.status_code in (302, 303)


# ---------------------------------------------------------------------------
# Monitor console + JSON state
# ---------------------------------------------------------------------------
class TestConsole:
    def test_console_200_for_monitor(self, client, buyer_user, live_auction):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:console", kwargs={"pk": live_auction.pk}))
        assert resp.status_code == 200

    def test_console_200_for_approver_monitor(self, client, approver, live_auction):
        client.force_login(approver)
        resp = client.get(reverse("auctions:console", kwargs={"pk": live_auction.pk}))
        assert resp.status_code == 200

    def test_console_state_json_full_with_leaderboard(self, client, buyer_user, live_auction, vendor_a):
        from apps.auctions.services import place_bid

        # Place a bid so there is an active participant in the (active-only) leaderboard.
        place_bid(live_auction, vendor_a, Decimal("900"), buyer_user, source="manual")
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:console_state", kwargs={"pk": live_auction.pk}))
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("application/json")
        data = json.loads(resp.content)
        assert data["view"] == "full"
        assert "leaderboard" in data
        # buyer full view exposes vendor names
        assert any("vendor_name" in row for row in data["leaderboard"])


# ---------------------------------------------------------------------------
# Results + finalize
# ---------------------------------------------------------------------------
class TestResults:
    def test_results_200(self, client, buyer_user, awarded_auction):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:results", kwargs={"pk": awarded_auction.pk}))
        assert resp.status_code == 200

    def test_award_finalize_post_awards(self, client, buyer_user, live_auction, vendor_a):
        from apps.auctions.services import place_bid, close_auction

        client.force_login(buyer_user)
        # place a valid bid then close so there is something to award
        place_bid(live_auction, vendor_a, Decimal("900"), buyer_user, source="portal")
        close_auction(live_auction, buyer_user)
        resp = client.post(reverse("auctions:award_finalize", kwargs={"pk": live_auction.pk}))
        assert resp.status_code in (302, 303)
        refreshed = Auction.all_objects.get(pk=live_auction.pk)
        assert refreshed.status == "awarded"
        assert refreshed.awarded_vendor_id == vendor_a.pk


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
class TestAnalytics:
    def test_analytics_dashboard_200(self, client, buyer_user, awarded_auction):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:analytics_dashboard"))
        assert resp.status_code == 200

    def test_auction_analytics_200(self, client, buyer_user, awarded_auction):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:auction_analytics", kwargs={"pk": awarded_auction.pk}))
        assert resp.status_code == 200

    def test_dashboard_200(self, client, buyer_user, draft_auction):
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:dashboard"))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Permission gate (requester can neither manage nor monitor)
# ---------------------------------------------------------------------------
class TestPermissionGate:
    def test_requester_blocked_from_create(self, client, requester):
        client.force_login(requester)
        resp = client.get(reverse("auctions:auction_create"))
        assert resp.status_code in (302, 303, 403)
        if resp.status_code in (302, 303):
            assert "/auctions/create" not in resp["Location"]

    def test_requester_blocked_from_console(self, client, requester, live_auction):
        client.force_login(requester)
        resp = client.get(reverse("auctions:console", kwargs={"pk": live_auction.pk}))
        assert resp.status_code in (302, 303, 403, 404)


# ---------------------------------------------------------------------------
# Vendor portal surface
# ---------------------------------------------------------------------------
class TestVendorPortal:
    def test_invitations_list_200(self, client, vendor_portal_user, scheduled_auction):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse("vendor_portal:auction_invitations"))
        assert resp.status_code == 200

    def test_accept_post(self, client, vendor_portal_user, scheduled_auction):
        client.force_login(vendor_portal_user)
        resp = client.post(reverse("vendor_portal:auction_accept", kwargs={"pk": scheduled_auction.pk}))
        assert resp.status_code in (302, 303)
        part = AuctionParticipant.all_objects.get(
            auction=scheduled_auction, vendor=vendor_portal_user.vendor
        )
        assert part.status == "accepted"

    def test_decline_post(self, client, vendor_portal_user, scheduled_auction):
        client.force_login(vendor_portal_user)
        resp = client.post(reverse("vendor_portal:auction_decline", kwargs={"pk": scheduled_auction.pk}))
        assert resp.status_code in (302, 303)
        part = AuctionParticipant.all_objects.get(
            auction=scheduled_auction, vendor=vendor_portal_user.vendor
        )
        assert part.status == "declined"

    def test_bidding_page_200(self, client, vendor_portal_user, live_auction):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse("vendor_portal:auction_bidding", kwargs={"pk": live_auction.pk}))
        assert resp.status_code == 200

    def test_portal_state_json_self(self, client, vendor_portal_user, live_auction):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse("vendor_portal:auction_state", kwargs={"pk": live_auction.pk}))
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data["view"] == "self"
        # vendor self view never carries the buyer leaderboard
        assert "leaderboard" not in data

    def test_place_bid_happy_path(self, client, vendor_portal_user, live_auction):
        client.force_login(vendor_portal_user)
        before = AuctionBid.all_objects.filter(auction=live_auction).count()
        resp = client.post(
            reverse("vendor_portal:auction_place_bid", kwargs={"pk": live_auction.pk}),
            {"amount": "900"},
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data["ok"] is True
        after = AuctionBid.all_objects.filter(auction=live_auction).count()
        assert after == before + 1

    def test_place_bid_too_high_rejected(self, client, vendor_portal_user, live_auction):
        client.force_login(vendor_portal_user)
        before = AuctionBid.all_objects.filter(auction=live_auction).count()
        resp = client.post(
            reverse("vendor_portal:auction_place_bid", kwargs={"pk": live_auction.pk}),
            {"amount": "999999"},  # above starting_price 1000? no - above next valid max
        )
        assert resp.status_code == 400
        data = json.loads(resp.content)
        assert data["ok"] is False
        after = AuctionBid.all_objects.filter(auction=live_auction).count()
        assert after == before
