"""Raise order-fulfillment alerts across all tenants.

Safe to run repeatedly (e.g. via cron). For every tenant it calls:

    * ``scan_fulfillment_alerts`` — a one-time portal Notification for each in-flight
      shipment past its estimated delivery date (guarded by ``delivery_alerted_at``), and
    * ``scan_backorder_alerts`` — a one-time alert for each overdue open backorder
      (guarded by ``alerted_at``) and auto-cancellation of backorders whose PO has finished.

The tracking board performs the shipment sweep lazily on open, so this command is a
belt-and-braces option for environments without a background worker.
"""
from django.core.management.base import BaseCommand

from apps.fulfillment.services import scan_backorder_alerts, scan_fulfillment_alerts


class Command(BaseCommand):
    help = 'Raise shipment delivery + backorder alerts across all tenants.'

    def handle(self, *args, **options):
        ship = scan_fulfillment_alerts()
        back = scan_backorder_alerts()
        if any(ship.values()) or any(back.values()):
            self.stdout.write(self.style.SUCCESS(
                f"Fulfillment alerts: {ship['overdue_delivery']} shipment(s) overdue, "
                f"{back['overdue']} backorder(s) overdue, "
                f"{back['orphans_cancelled']} backorder(s) auto-cancelled."
            ))
        else:
            self.stdout.write('Fulfillment alerts: nothing to do.')
