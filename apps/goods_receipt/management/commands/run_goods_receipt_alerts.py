"""Raise goods-receipt alerts across all tenants.

Safe to run repeatedly (e.g. via cron). For every tenant it calls
``scan_goods_receipt_alerts`` — a one-time portal Notification for each goods receipt that
has been awaiting inspection for too long (guarded by ``inspection_alerted_at``) and each
open Return-to-Vendor (guarded by ``alerted_at``).

The analytics dashboard performs the sweep lazily on open, so this command is a
belt-and-braces option for environments without a background worker.
"""
from django.core.management.base import BaseCommand

from apps.goods_receipt.services import scan_goods_receipt_alerts


class Command(BaseCommand):
    help = 'Raise overdue-inspection + open-RTV alerts across all tenants.'

    def handle(self, *args, **options):
        counts = scan_goods_receipt_alerts()
        if any(counts.values()):
            self.stdout.write(self.style.SUCCESS(
                f"Goods-receipt alerts: {counts['overdue_inspection']} awaiting "
                f"inspection, {counts['open_rtv']} open return(s)."))
        else:
            self.stdout.write('Goods-receipt alerts: nothing to do.')
