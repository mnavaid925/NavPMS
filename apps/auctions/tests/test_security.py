"""Security tests for Module 8 - E-Auction Management (apps/auctions).

OWASP-aligned, mirroring apps/rfx/tests/test_security.py:
  A01 Broken Access Control  - cross-tenant IDOR, cross-vendor state, blind leak
  A03 Injection (XSS)        - auction title is escaped in the list
  A04 Insecure Design        - server-side bid rule enforcement (no client trust)
  A05 Security Misconfig     - anonymous redirected to login; CSRF enforced; sandbox
  File upload validation     - oversize / disallowed extension rejected
"""
import json
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.auctions.models import Auction, AuctionBid

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# A01 - Broken Access Control: cross-tenant IDOR
# ---------------------------------------------------------------------------
class TestCrossTenantIDOR:
    def test_intruder_cannot_view_detail(self, client, intruder, draft_auction):
        client.force_login(intruder)
        resp = client.get(reverse("auctions:auction_detail", kwargs={"pk": draft_auction.pk}))
        assert resp.status_code == 404

    def test_intruder_cannot_edit(self, client, intruder, draft_auction):
        client.force_login(intruder)
        resp = client.get(reverse("auctions:auction_edit", kwargs={"pk": draft_auction.pk}))
        assert resp.status_code == 404

    def test_intruder_cannot_delete(self, client, intruder, draft_auction):
        client.force_login(intruder)
        resp = client.post(reverse("auctions:auction_delete", kwargs={"pk": draft_auction.pk}))
        assert resp.status_code == 404
        assert Auction.all_objects.filter(pk=draft_auction.pk).exists()


# ---------------------------------------------------------------------------
# A01 - Cross-vendor: non-participant cannot read another auction's state
# ---------------------------------------------------------------------------
class TestCrossVendorState:
    def test_non_participant_portal_state_403(self, client, vendor_b_portal_user, draft_auction):
        # draft_auction has NO participants -> vendor_b is not invited.
        # The vendor-portal state endpoint denies a non-participant with a JSON 403.
        client.force_login(vendor_b_portal_user)
        resp = client.get(reverse("vendor_portal:auction_state", kwargs={"pk": draft_auction.pk}))
        assert resp.status_code == 403
        data = json.loads(resp.content)
        assert data.get("ok") is False

    def test_buyer_console_state_forbidden_for_requester(self, client, requester, live_auction):
        # The buyer console_state JSON endpoint denies a non-monitor with {"error": "forbidden"}.
        client.force_login(requester)
        resp = client.get(reverse("auctions:console_state", kwargs={"pk": live_auction.pk}))
        assert resp.status_code == 403
        data = json.loads(resp.content)
        assert data.get("error") == "forbidden"


# ---------------------------------------------------------------------------
# A01 - Blind/sealed leak: vendor self view must NOT expose competitor names
# ---------------------------------------------------------------------------
class TestBlindLeak:
    def test_vendor_state_hides_competitor_legal_names(
        self, client, vendor_portal_user, vendor_b, vendor_c, live_auction
    ):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse("vendor_portal:auction_state", kwargs={"pk": live_auction.pk}))
        assert resp.status_code == 200
        body = resp.content
        # competitor legal_names are the canaries - they appear ONLY in buyer markup
        assert vendor_b.legal_name.encode() not in body
        assert vendor_c.legal_name.encode() not in body

    def test_vendor_bidding_page_hides_competitor_names(
        self, client, vendor_portal_user, vendor_b, vendor_c, live_auction
    ):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse("vendor_portal:auction_bidding", kwargs={"pk": live_auction.pk}))
        assert resp.status_code == 200
        assert vendor_b.legal_name.encode() not in resp.content
        assert vendor_c.legal_name.encode() not in resp.content


# ---------------------------------------------------------------------------
# A03 - XSS: auction title is escaped in the list
# ---------------------------------------------------------------------------
class TestXSSEscaping:
    def test_title_is_escaped_in_list(self, client, buyer_user, tenant, tenant_admin):
        from apps.core.models import set_current_tenant
        from apps.auctions.services import next_auction_number

        set_current_tenant(tenant)
        payload = "<script>alert('xss')</script>"
        Auction.all_objects.create(
            tenant=tenant,
            auction_number=next_auction_number(tenant),
            title=payload,
            auction_type="reverse",
            currency="USD",
            starting_price="1000",
            decrement_type="amount",
            decrement_value="50",
            reserve_price="800",
            created_by=tenant_admin,
        )
        client.force_login(buyer_user)
        resp = client.get(reverse("auctions:auction_list"))
        assert resp.status_code == 200
        # raw script tag must NOT be present; escaped form may be
        assert b"<script>alert('xss')</script>" not in resp.content
        assert b"&lt;script&gt;" in resp.content


# ---------------------------------------------------------------------------
# A04 - Insecure Design: server enforces bid rules regardless of client input
# ---------------------------------------------------------------------------
class TestBidRuleBypass:
    def test_bid_above_starting_price_rejected(self, client, vendor_portal_user, live_auction):
        client.force_login(vendor_portal_user)
        before = AuctionBid.all_objects.filter(auction=live_auction).count()
        resp = client.post(
            reverse("vendor_portal:auction_place_bid", kwargs={"pk": live_auction.pk}),
            {"amount": "2000"},  # above starting_price 1000
        )
        assert resp.status_code == 400
        data = json.loads(resp.content)
        assert data["ok"] is False
        assert AuctionBid.all_objects.filter(auction=live_auction).count() == before

    def test_bid_violating_decrement_rejected(self, client, vendor_portal_user, vendor_b,
                                              live_auction, tenant_admin):
        from apps.auctions.services import place_bid

        # Seed a leading bid of 900 by a competitor; decrement is 50, so the next
        # bid must be <= 850. A 870 bid does not beat the best by the decrement.
        place_bid(live_auction, vendor_b, Decimal("900"), tenant_admin, source="manual")

        client.force_login(vendor_portal_user)
        before = AuctionBid.all_objects.filter(auction=live_auction).count()
        resp = client.post(
            reverse("vendor_portal:auction_place_bid", kwargs={"pk": live_auction.pk}),
            {"amount": "870"},
        )
        assert resp.status_code == 400
        data = json.loads(resp.content)
        assert data["ok"] is False
        assert AuctionBid.all_objects.filter(auction=live_auction).count() == before


# ---------------------------------------------------------------------------
# A05 - Anonymous access redirected to login
# ---------------------------------------------------------------------------
class TestAnonymousRedirect:
    @pytest.mark.parametrize(
        "url_name,kwargs",
        [
            ("auctions:auction_list", {}),
            ("auctions:auction_create", {}),
            ("auctions:analytics_dashboard", {}),
        ],
    )
    def test_anonymous_redirected(self, client, url_name, kwargs):
        resp = client.get(reverse(url_name, kwargs=kwargs))
        assert resp.status_code == 302
        assert "/accounts/login/" in resp["Location"]

    def test_anonymous_console_redirected(self, client, live_auction):
        resp = client.get(reverse("auctions:console", kwargs={"pk": live_auction.pk}))
        assert resp.status_code == 302
        assert "/accounts/login/" in resp["Location"]


# ---------------------------------------------------------------------------
# A05 - CSRF enforced on state-changing POST
# ---------------------------------------------------------------------------
class TestCSRF:
    def test_delete_without_csrf_403(self, buyer_user, draft_auction):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(buyer_user)
        resp = csrf_client.post(reverse("auctions:auction_delete", kwargs={"pk": draft_auction.pk}))
        assert resp.status_code == 403
        assert Auction.all_objects.filter(pk=draft_auction.pk).exists()


# ---------------------------------------------------------------------------
# Sandbox - vendor_portal user cannot reach buyer /auctions/ surface
# ---------------------------------------------------------------------------
class TestSandbox:
    def test_vendor_portal_user_bounced_from_buyer_create(self, client, vendor_portal_user):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse("auctions:auction_create"))
        assert resp.status_code == 302
        assert "/vendor-portal/" in resp["Location"]


# ---------------------------------------------------------------------------
# File upload validation (AuctionDocumentForm)
# ---------------------------------------------------------------------------
class TestFileUploadValidation:
    def _form(self, file):
        from apps.auctions.forms import AuctionDocumentForm

        return AuctionDocumentForm(data={"title": "Doc"}, files={"file": file})

    def test_accepts_small_allowed_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        good = SimpleUploadedFile("terms.pdf", b"%PDF-1.4 ok", content_type="application/pdf")
        form = self._form(good)
        assert form.is_valid(), form.errors

    def test_rejects_disallowed_extension(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        evil = SimpleUploadedFile("evil.svg", b"<svg/onload=alert(1)>", content_type="image/svg+xml")
        form = self._form(evil)
        assert not form.is_valid()
        assert "file" in form.errors

    def test_rejects_uppercase_disallowed_extension(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        evil = SimpleUploadedFile("EVIL.SVG", b"<svg/onload=alert(1)>", content_type="image/svg+xml")
        form = self._form(evil)
        assert not form.is_valid()
        assert "file" in form.errors

    def test_rejects_oversize_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        big = SimpleUploadedFile(
            "huge.pdf", b"x" * (60 * 1024 * 1024), content_type="application/pdf"
        )
        form = self._form(big)
        assert not form.is_valid()
        assert "file" in form.errors
