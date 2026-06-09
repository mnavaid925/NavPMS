"""Retry due pending/failed webhook deliveries across all tenants (cron-friendly).

For each tenant it re-attempts every :class:`WebhookDelivery` still under the attempt cap
(``settings.WEBHOOK_MAX_ATTEMPTS``) whose ``next_retry_at`` has elapsed, through the real signed
HTTP delivery path. ``--tenant <slug>`` limits it to one tenant.
"""
from django.core.management.base import BaseCommand

from apps.core.models import Tenant, set_current_tenant

from apps.sysadmin import webhooks


class Command(BaseCommand):
    help = 'Retry pending/failed webhook deliveries across all tenants (cron-friendly).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Limit to a single tenant slug.')

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        if options.get('tenant'):
            tenants = tenants.filter(slug=options['tenant'])

        total_retried = total_succeeded = 0
        for tenant in tenants:
            set_current_tenant(tenant)
            result = webhooks.retry_pending(tenant)
            total_retried += result['retried']
            total_succeeded += result['succeeded']
            if result['retried']:
                self.stdout.write(
                    f'  {tenant.name}: retried {result["retried"]}, '
                    f'succeeded {result["succeeded"]}.')

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS(
            f'Webhook retries complete: {total_retried} attempted, {total_succeeded} delivered.'))
