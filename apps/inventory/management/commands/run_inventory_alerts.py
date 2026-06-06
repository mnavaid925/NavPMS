"""Cron-friendly inventory sweep (Module 19).

For each tenant: folds newly-posted goods receipts into stock, runs reorder-point automation
(raising a DRAFT requisition for every stocked item at/below its reorder point), and raises a
one-time near-expiry alert for stock lots inside the configured window. Idempotent — receipt sync is
watermarked, reorder skips items with an open reorder requisition, and expiry alerts stamp
``StockLevel.expiry_alerted_at``.
"""
from django.core.management.base import BaseCommand

from apps.core.models import Tenant, set_current_tenant

from apps.inventory.services import scan_inventory_alerts


class Command(BaseCommand):
    help = 'Sync stock from receipts, run reorder automation, and raise near-expiry alerts across ' \
           'all tenants (cron-friendly).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Limit the sweep to one tenant slug.')

    def _report(self, name, result):
        self.stdout.write(self.style.SUCCESS(
            f'{name}: {result["received"]} receipt(s) synced, '
            f'{result["reorders"]} reorder requisition(s), '
            f'{result["expiry_alerts"]} expiry alert(s).'))

    def handle(self, *args, **options):
        slug = options.get('tenant')
        if slug:
            tenant = Tenant.objects.filter(slug=slug).first()
            if not tenant:
                self.stdout.write(self.style.ERROR(f'No tenant with slug "{slug}".'))
                return
            set_current_tenant(tenant)
            result = scan_inventory_alerts(tenant)
            set_current_tenant(None)
            self._report(tenant.name, result)
            return

        for tenant in Tenant.objects.all():
            set_current_tenant(tenant)
            result = scan_inventory_alerts(tenant)
            self._report(tenant.name, result)
        set_current_tenant(None)
