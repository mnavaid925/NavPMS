"""Advance e-auction status by the wall clock. Safe to run repeatedly (e.g. via cron).

For every auction currently in `scheduled` or `live`, call
`refresh_auction_state`, which lazily flips:

    scheduled -> live   when now >= start_at
    live      -> closed when now >= end_at

The live auction console also performs this sweep lazily on open, so this
command is a belt-and-braces option for environments without a background
worker. Crosses all tenant scopes via `Auction.all_objects`.
"""
from django.core.management.base import BaseCommand

from apps.auctions.models import Auction
from apps.auctions.services import refresh_auction_state


class Command(BaseCommand):
    help = 'Advance scheduled/live auctions by the wall clock across all tenants.'

    def handle(self, *args, **options):
        started = 0
        closed = 0
        auctions = Auction.all_objects.filter(status__in=('scheduled', 'live'))
        for auction in auctions:
            before = auction.status
            refresh_auction_state(auction)
            after = auction.status
            if before == 'scheduled' and after == 'live':
                started += 1
            if after == 'closed':
                closed += 1

        if started or closed:
            self.stdout.write(self.style.SUCCESS(
                f'Auction clock: started {started}, closed {closed}.'
            ))
        else:
            self.stdout.write('Auction clock: no auctions changed state.')
