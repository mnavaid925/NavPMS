"""Raise purchase-order alerts across all tenants.

Safe to run repeatedly (e.g. via cron). For every tenant it calls
``scan_po_alerts`` which:

    * raises a one-time portal Notification for each issued PO that has not been
      acknowledged within the reminder window (guarded by ``ack_alerted_at``), and
    * raises a one-time alert for each PO past its expected delivery date that is
      not yet fully received (guarded by ``delivery_alerted_at``).

The tracking board performs the same sweep lazily on open, so this command is a
belt-and-braces option for environments without a background worker.
"""
from django.core.management.base import BaseCommand

from apps.purchase_orders.services import scan_po_alerts


class Command(BaseCommand):
    help = 'Raise purchase-order acknowledgment/delivery alerts across all tenants.'

    def handle(self, *args, **options):
        counts = scan_po_alerts()
        if any(counts.values()):
            self.stdout.write(self.style.SUCCESS(
                f"PO alerts: {counts['ack_alerted']} awaiting acknowledgment, "
                f"{counts['overdue_delivery']} delivery overdue."
            ))
        else:
            self.stdout.write('PO alerts: nothing to do.')
