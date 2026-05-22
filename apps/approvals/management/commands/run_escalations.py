"""Escalate overdue approval tasks. Safe to run repeatedly (e.g. via cron).

The approver inbox also performs this sweep lazily on open, so this command
is a belt-and-braces option for environments without a background worker.
"""
from django.core.management.base import BaseCommand

from apps.approvals.services import escalate_overdue


class Command(BaseCommand):
    help = 'Escalate every overdue approval task across all tenants.'

    def handle(self, *args, **options):
        count = escalate_overdue()
        if count:
            self.stdout.write(self.style.SUCCESS(
                f'Escalated {count} overdue approval task(s).'
            ))
        else:
            self.stdout.write('No overdue approval tasks found.')
