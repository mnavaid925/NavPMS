"""Seed Module 8 demo data: 3 auctions per tenant in varied statuses
(draft with lots only, scheduled with invitees, awarded with a full live bid
ledger driven through the real bidding services)."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.auctions.models import (
    Auction, AuctionBid, AuctionDocument, AuctionLot, AuctionParticipant,
)
from apps.auctions.services import (
    close_auction, finalize_auction, invite_vendors, next_auction_number,
    place_bid, publish_auction, start_auction,
)
from apps.core.models import Tenant, set_current_tenant
from apps.vendors.models import Vendor


class Command(BaseCommand):
    help = 'Seed Module 8 demo data (auctions + lots + participants + live bid ledger + award).'

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true')

    def handle(self, *args, **options):
        tenants = list(Tenant.objects.all())
        if not tenants:
            self.stdout.write(self.style.ERROR(
                'No tenants found. Run `seed_tenants` first.'
            ))
            return

        for tenant in tenants:
            set_current_tenant(tenant)
            if options['flush']:
                AuctionBid.all_objects.filter(tenant=tenant).delete()
                AuctionDocument.all_objects.filter(tenant=tenant).delete()
                AuctionParticipant.all_objects.filter(tenant=tenant).delete()
                AuctionLot.all_objects.filter(tenant=tenant).delete()
                Auction.all_objects.filter(tenant=tenant).delete()

            if Auction.all_objects.filter(tenant=tenant).exists() and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: auction data already exists — skipped '
                    '(use --flush to re-seed).'
                )
                continue

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            admin = next(
                (u for u in users if u.is_tenant_admin),
                users[0] if users else None,
            )
            if not admin:
                self.stdout.write(f'    {tenant.name}: no admin user — skipped.')
                continue

            active_vendors = list(
                Vendor.all_objects.filter(
                    tenant=tenant, status='active',
                ).order_by('legal_name')[:5]
            )
            if len(active_vendors) < 3:
                self.stdout.write(
                    f'    {tenant.name}: needs >= 3 active vendors — skipped. '
                    'Run seed_vendors first.'
                )
                continue

            self.stdout.write(f'  Seeding auction data for {tenant.name}…')

            now = timezone.now()

            # ---------- Auction 1: Draft (3 lots, no participants) ----------
            self._create_auction(
                tenant, admin,
                title='Office laptops reverse auction Q3',
                description='Bulk procurement of business laptops via reverse auction.',
                starting_price=Decimal('45000.00'),
                reserve_price=Decimal('38000.00'),
                decrement_value=Decimal('500.00'),
                start_at=None, end_at=None,
                lots=[
                    ('14" business laptop (i7/16GB/512GB)', 'EA', Decimal('20'), Decimal('1200.00')),
                    ('15" business laptop (i5/16GB/256GB)', 'EA', Decimal('15'), Decimal('950.00')),
                    ('Docking station USB-C',               'EA', Decimal('35'), Decimal('180.00')),
                ],
            )
            # No participants, no publish -> stays draft.

            # ---------- Auction 2: Scheduled (2 lots, 3 invitees, +1 day) ----------
            scheduled = self._create_auction(
                tenant, admin,
                title='Bulk steel quarterly buy',
                description='Quarterly hot-rolled steel coil reverse auction.',
                starting_price=Decimal('120000.00'),
                reserve_price=Decimal('100000.00'),
                decrement_value=Decimal('1000.00'),
                start_at=now + timedelta(days=1),
                end_at=now + timedelta(days=1, hours=1),
                lots=[
                    ('Hot-rolled steel coil (tonnes)', 'TON', Decimal('150'), Decimal('600.00')),
                    ('Cold-rolled steel sheet (tonnes)', 'TON', Decimal('50'), Decimal('700.00')),
                ],
            )
            if scheduled:
                invite_vendors(scheduled, [v.pk for v in active_vendors[:3]], admin)
                try:
                    publish_auction(scheduled, admin)  # draft -> scheduled (start in future)
                except ValidationError as exc:
                    self.stdout.write(self.style.WARNING(
                        f'    {tenant.name}: could not publish scheduled auction: {exc}'
                    ))

            # ---------- Auction 3: Awarded (1 lot, 3 invitees, live round) ----------
            awarded = self._create_auction(
                tenant, admin,
                title='Inbound logistics reverse auction',
                description='12-month inbound freight contract awarded by reverse auction.',
                starting_price=Decimal('10000.00'),
                reserve_price=Decimal('8500.00'),
                decrement_value=Decimal('250.00'),
                start_at=now - timedelta(hours=2),
                # End is in the FUTURE so the auction stays live through the demo
                # bid round, but inside the default 120s anti-snipe window so the
                # FIRST bid deterministically fires one extension; the round then
                # closes the auction explicitly. (Bug fix: a past end_at made
                # refresh_auction_state close the auction on the first bid, so
                # every bid was rejected and finalize raised "No valid bids".)
                end_at=now + timedelta(seconds=90),
                lots=[
                    ('Annual inbound freight (lanes)', 'LOT', Decimal('1'), Decimal('10000.00')),
                ],
            )
            if awarded:
                picked = active_vendors[:3]
                invite_vendors(awarded, [v.pk for v in picked], admin)
                self._run_live_round(awarded, picked, admin)

            self.stdout.write(self.style.SUCCESS(
                f'    {tenant.name}: 3 auctions seeded (draft / scheduled / awarded).'
            ))

        self.stdout.write(self.style.SUCCESS('\n=== Auction seeding complete ==='))
        self.stdout.write(
            '\nLogin as a tenant admin (e.g. admin_acme / Welcome@123) to see the data.\n'
            'WARNING: Django superuser "admin" has no tenant — data will not appear there.\n'
        )

    # ----- helpers -----

    def _create_auction(self, tenant, admin, *, title, description, starting_price,
                        reserve_price, decrement_value, start_at, end_at, lots):
        """Create an auction (idempotent by title) plus its descriptive lots."""
        existing = Auction.all_objects.filter(tenant=tenant, title=title).first()
        if existing:
            return existing
        auction = Auction.all_objects.create(
            tenant=tenant,
            auction_number=next_auction_number(tenant),
            title=title,
            description=description,
            auction_type='reverse',
            currency='USD',
            starting_price=starting_price,
            reserve_price=reserve_price,
            decrement_type='amount',
            decrement_value=decrement_value,
            start_at=start_at,
            end_at=end_at,
            rank_visibility='rank_and_leading',
            terms_and_conditions='Standard terms apply. Demo seed data.',
            status='draft',
            created_by=admin,
        )
        for idx, (desc, uom, qty, price) in enumerate(lots, start=1):
            AuctionLot.all_objects.create(
                tenant=tenant, auction=auction, lot_no=idx,
                item_description=desc, uom=uom,
                quantity=qty, est_unit_price=price,
            )
        return auction

    def _run_live_round(self, auction, vendors, admin):
        """Drive a realistic decreasing bid round through the real services.

        starting_price=10000, amount decrement=250 -> each new global-best bid
        must be <= current_best - 250. Bids are placed via place_bid (which
        enforces the rules) so the ledger, ranks, denorm standing, savings and
        the award are all produced exactly as in production. Each placement is
        guarded so a rule-violating bid is skipped rather than aborting the seed.
        The auction's end_at is seeded inside the anti-snipe window, so the first
        bid records one anti-snipe extension in the demo ledger.
        """
        publish_auction(auction, admin)         # draft -> scheduled
        start_auction(auction, admin)           # scheduled -> live (start_at in past)

        v1, v2, v3 = vendors[0], vendors[1], vendors[2]
        # (vendor, amount) ladder — each beats the running best by >= 250.
        ladder = [
            (v1, Decimal('9800.00')),
            (v2, Decimal('9550.00')),
            (v1, Decimal('9300.00')),
            (v3, Decimal('9050.00')),
            (v2, Decimal('8800.00')),
        ]
        for vendor, amount in ladder:
            try:
                place_bid(auction, vendor, amount, admin, source='manual')
            except ValidationError as exc:
                self.stdout.write(self.style.WARNING(
                    f'    skipped bid {amount} by {vendor.legal_name}: {exc}'
                ))

        close_auction(auction, admin)           # live -> closed
        finalize_auction(auction, admin)        # lowest valid bid wins -> awarded
