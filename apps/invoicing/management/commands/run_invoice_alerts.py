"""Raise accounts-payable invoice alerts across all tenants.

Safe to run repeatedly (e.g. via cron). For every tenant it calls ``scan_invoice_alerts`` —
a one-time portal Notification for each approved/submitted invoice that is past its due date
and still unpaid (guarded by ``overdue_alerted_at``) and each invoice whose early-payment
discount window is closing (guarded by ``discount_alerted_at``).

The analytics dashboard performs the sweep lazily on open, so this command is a
belt-and-braces option for environments without a background worker.
"""
from django.core.management.base import BaseCommand

from apps.invoicing.services import scan_invoice_alerts


class Command(BaseCommand):
    help = 'Raise overdue-payment + closing-discount alerts across all tenants.'

    def handle(self, *args, **options):
        counts = scan_invoice_alerts()
        if any(counts.values()):
            self.stdout.write(self.style.SUCCESS(
                f"Invoice alerts: {counts['overdue']} overdue, "
                f"{counts['discount']} closing discount window(s)."))
        else:
            self.stdout.write('Invoice alerts: nothing to do.')
