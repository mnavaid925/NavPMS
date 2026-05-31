"""Raise contract renewal/expiration alerts across all tenants.

Safe to run repeatedly (e.g. via cron). For every tenant it calls
``scan_contract_alerts`` which:

    * raises a one-time portal Notification for each contract that is expiring
      within its renewal-notice window (guarded by ``renewal_alerted_at``),
    * auto-renews past-due contracts flagged ``auto_renew``,
    * expires past-due contracts that are not set to auto-renew, and
    * flags overdue obligations.

The renewals board performs the same sweep lazily on open, so this command is a
belt-and-braces option for environments without a background worker.
"""
from django.core.management.base import BaseCommand

from apps.contracts.services import scan_contract_alerts


class Command(BaseCommand):
    help = 'Raise contract renewal/expiration alerts across all tenants.'

    def handle(self, *args, **options):
        counts = scan_contract_alerts()
        if any(counts.values()):
            self.stdout.write(self.style.SUCCESS(
                f"Contract alerts: {counts['alerted']} alerted, "
                f"{counts['auto_renewed']} auto-renewed, "
                f"{counts['expired']} expired, "
                f"{counts['overdue']} obligations flagged overdue."
            ))
        else:
            self.stdout.write('Contract alerts: nothing to do.')
