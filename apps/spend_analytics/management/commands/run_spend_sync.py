"""Resync the SpendRecord fact table from invoices + POs across all tenants.

Safe to run repeatedly (e.g. via cron). The dashboard also resyncs lazily when stale, so this
command is a belt-and-braces option for environments without a background worker.
"""
from django.core.management.base import BaseCommand

from apps.core.models import Tenant, set_current_tenant
from apps.spend_analytics.services import sync_all_tenants, sync_spend_facts


class Command(BaseCommand):
    help = ('Resync the SpendRecord fact table from invoices + POs across all tenants '
            '(cron-friendly; the dashboard also resyncs lazily).')

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Sync only the tenant with this slug.')
        parser.add_argument('--full', action='store_true',
                            help='Force a full reconcile (the sync is always a full reconcile).')

    def handle(self, *args, **options):
        slug = options.get('tenant')
        full = options.get('full', False)

        if slug:
            tenant = Tenant.objects.filter(slug=slug).first()
            if not tenant:
                self.stdout.write(self.style.ERROR(f'No tenant with slug "{slug}".'))
                return
            set_current_tenant(tenant)
            counts = sync_spend_facts(tenant, full=full)
            set_current_tenant(None)
            self.stdout.write(self.style.SUCCESS(
                f"{tenant.name}: +{counts['created']} ~{counts['updated']} "
                f"-{counts['pruned']} (={counts['total']})."))
            return

        result = sync_all_tenants(full=full)
        for tenant, counts in result['results']:
            self.stdout.write(
                f"  {tenant.name}: +{counts['created']} ~{counts['updated']} "
                f"-{counts['pruned']} (={counts['total']}).")
        t = result['totals']
        self.stdout.write(self.style.SUCCESS(
            f"Spend sync: +{t['created']} new, ~{t['updated']} updated, -{t['pruned']} pruned "
            f"({t['total']} records across {len(result['results'])} tenant(s))."))
