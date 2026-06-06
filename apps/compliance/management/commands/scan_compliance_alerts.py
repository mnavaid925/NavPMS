"""Cron-friendly compliance sweep (Module 18).

For each tenant: refreshes due financial-risk profiles (raising a one-time alert on a score drop /
band worsening), runs the fraud-rule scan (deduplicated by alert signature), and sends an
acknowledgment-reminder digest to each policy owner with outstanding sign-offs. Idempotent — fraud
alerts dedupe on signature and financial alerts stamp ``FinancialRiskProfile.alerted_at``.
"""
from django.core.management.base import BaseCommand

from apps.core.models import Tenant, set_current_tenant

from apps.compliance.services import scan_compliance_alerts


class Command(BaseCommand):
    help = 'Refresh financial risk, scan fraud, and remind on policy acks across all tenants ' \
           '(cron-friendly).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Limit the sweep to one tenant slug.')

    def _report(self, name, result):
        self.stdout.write(self.style.SUCCESS(
            f'{name}: {result["financial_refreshed"]} financial refresh(es), '
            f'{result["fraud_alerts"]} new fraud alert(s), '
            f'{result["policy_reminders"]} policy reminder(s).'))

    def handle(self, *args, **options):
        slug = options.get('tenant')
        if slug:
            tenant = Tenant.objects.filter(slug=slug).first()
            if not tenant:
                self.stdout.write(self.style.ERROR(f'No tenant with slug "{slug}".'))
                return
            set_current_tenant(tenant)
            result = scan_compliance_alerts(tenant)
            set_current_tenant(None)
            self._report(tenant.name, result)
            return

        for tenant in Tenant.objects.all():
            set_current_tenant(tenant)
            result = scan_compliance_alerts(tenant)
            self._report(tenant.name, result)
        set_current_tenant(None)
