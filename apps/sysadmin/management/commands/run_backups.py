"""Run scheduled backups across tenants and prune runs beyond each policy's retention window.

Cron-friendly: for every active, non-manual :class:`BackupPolicy` it executes a backup through the
pluggable connector (mock by default) and then deletes successful runs older than the policy's
``retention_days``. ``--tenant <slug>`` limits it to one tenant.
"""
from django.core.management.base import BaseCommand

from apps.core.models import Tenant, set_current_tenant

from apps.sysadmin import backups
from apps.sysadmin.models import BackupPolicy


class Command(BaseCommand):
    help = 'Execute scheduled backups and prune expired runs across all tenants (cron-friendly).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Limit to a single tenant slug.')

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        if options.get('tenant'):
            tenants = tenants.filter(slug=options['tenant'])

        total_runs = total_pruned = 0
        for tenant in tenants:
            set_current_tenant(tenant)
            policies = BackupPolicy.all_objects.filter(
                tenant=tenant, is_active=True).exclude(frequency='manual')
            for policy in policies:
                run = backups.run_backup(tenant, policy=policy, trigger='scheduled')
                total_runs += 1
                pruned = backups.prune_expired_runs(tenant, policy=policy)
                total_pruned += pruned
                self.stdout.write(
                    f'  {tenant.name}/{policy.name}: {run.run_number} {run.status}'
                    f'{f" (pruned {pruned})" if pruned else ""}.')

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS(
            f'Backups complete: {total_runs} run(s), {total_pruned} pruned.'))
