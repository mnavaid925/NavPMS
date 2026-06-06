"""Cron-friendly full-text re-index sweep (Module 20).

For each tenant, (re)extracts text from every document version still pending or failed extraction
via the configured ``DMS_EXTRACTION_ENGINE`` provider. Idempotent — already-indexed versions are
left untouched, so it is safe to run on a schedule (e.g. after switching the extraction engine to
``local`` to back-fill real PDF text).
"""
from django.core.management.base import BaseCommand

from apps.core.models import Tenant, set_current_tenant

from apps.dms.services import extract_pending


class Command(BaseCommand):
    help = 'Re-index pending/failed document versions across all tenants (cron-friendly).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Limit the sweep to one tenant slug.')

    def _report(self, name, result):
        self.stdout.write(self.style.SUCCESS(f'{name}: {result["indexed"]} version(s) indexed.'))

    def handle(self, *args, **options):
        slug = options.get('tenant')
        if slug:
            tenant = Tenant.objects.filter(slug=slug).first()
            if not tenant:
                self.stdout.write(self.style.ERROR(f'No tenant with slug "{slug}".'))
                return
            set_current_tenant(tenant)
            result = extract_pending(tenant)
            set_current_tenant(None)
            self._report(tenant.name, result)
            return

        for tenant in Tenant.objects.all():
            set_current_tenant(tenant)
            result = extract_pending(tenant)
            self._report(tenant.name, result)
        set_current_tenant(None)
