"""Cron-friendly over-budget sweep (Module 16).

Raises a one-time alert (audit + portal Notification to the budget owner) for each active budget
that is over budget or past the ``BUDGET_WARN_UTILIZATION_PCT`` threshold. Idempotent via
``Budget.over_budget_alerted_at`` — re-running does not re-alert. The dashboard does NOT sweep
lazily (consumption is computed on read), so schedule this to surface alerts proactively.
"""
from django.core.management.base import BaseCommand

from apps.core.models import Tenant, set_current_tenant

from apps.budget.services import scan_budget_alerts


class Command(BaseCommand):
    help = 'Raise one-time over-budget / high-utilization alerts across all tenants (cron-friendly).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Limit the sweep to one tenant slug.')

    def handle(self, *args, **options):
        slug = options.get('tenant')
        if slug:
            tenant = Tenant.objects.filter(slug=slug).first()
            if not tenant:
                self.stdout.write(self.style.ERROR(f'No tenant with slug "{slug}".'))
                return
            set_current_tenant(tenant)
            alerted = scan_budget_alerts(tenant)
            set_current_tenant(None)
            self.stdout.write(self.style.SUCCESS(
                f'{tenant.name}: {alerted} budget(s) newly alerted.'))
            return

        total = 0
        for tenant in Tenant.objects.all():
            set_current_tenant(tenant)
            total += scan_budget_alerts(tenant)
        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS(f'{total} budget(s) newly alerted across all tenants.'))
