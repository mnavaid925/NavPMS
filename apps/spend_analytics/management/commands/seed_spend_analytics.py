"""Seed Module 15 demo data: materialize the SpendRecord fact table from the already-seeded
supplier invoices (actual) + purchase orders (committed), and create a few demo saved reports.

Runs AFTER ``seed_invoicing`` (so approved/paid invoices exist to sync from). The fact table is
(re)built on every run via the idempotent ``sync_spend_facts``; the demo reports are created once
(idempotent ``get_or_create``). Pass ``--flush`` to wipe reports + facts first.
"""
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant

from apps.spend_analytics.models import SpendRecord, SpendReport
from apps.spend_analytics.services import sync_spend_facts

_REPORTS = [
    {
        'name': 'Spend by category (actual)', 'dimension': 'vendor_category',
        'measure': 'amount_sum', 'chart_type': 'doughnut', 'basis': 'actual',
        'is_shared': True,
        'description': 'Approved/paid spend grouped by commodity category.',
    },
    {
        'name': 'Monthly spend trend (actual)', 'dimension': 'month',
        'measure': 'amount_sum', 'chart_type': 'line', 'basis': 'actual',
        'is_shared': True, 'description': 'Actual spend by month.',
    },
    {
        'name': 'Maverick spend by supplier', 'dimension': 'vendor',
        'measure': 'amount_sum', 'chart_type': 'bar', 'basis': 'actual',
        'maverick_only': True,
        'description': 'Off-preferred / off-contract / non-PO spend by supplier.',
    },
]


class Command(BaseCommand):
    help = ('Seed Module 15 demo data (sync the spend fact table from invoices/POs + demo '
            'saved reports).')

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true')

    def handle(self, *args, **options):
        flush = options['flush']
        tenants = list(Tenant.objects.all())
        if not tenants:
            self.stdout.write(self.style.ERROR('No tenants found. Run `seed_tenants` first.'))
            return

        for tenant in tenants:
            set_current_tenant(tenant)
            if flush:
                SpendReport.all_objects.filter(tenant=tenant).delete()
                SpendRecord.all_objects.filter(tenant=tenant).delete()

            # Always (re)build the fact table — idempotent upsert + prune.
            counts = sync_spend_facts(tenant)
            self.stdout.write(
                f'  {tenant.name}: spend facts +{counts["created"]} ~{counts["updated"]} '
                f'-{counts["pruned"]} (={counts["total"]}).')
            if counts['total'] == 0:
                self.stdout.write(self.style.WARNING(
                    f'    {tenant.name}: no approved/paid invoices or open POs to analyse yet.'))

            if SpendReport.all_objects.filter(tenant=tenant).exists() and not flush:
                self.stdout.write(
                    f'    {tenant.name}: spend reports already exist — skipped '
                    '(use --flush to re-seed).')
                continue

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            owner = next((u for u in users if u.is_tenant_admin), users[0] if users else None)
            created = 0
            for spec in _REPORTS:
                _, was_created = SpendReport.all_objects.get_or_create(
                    tenant=tenant, name=spec['name'],
                    defaults={**spec, 'owner': owner},
                )
                if was_created:
                    created += 1
            self.stdout.write(f'    {tenant.name}: {created} demo report(s) created.')

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('Spend analytics seeded.'))
        self.stdout.write(
            'Log in as a tenant admin (e.g. admin_acme / Welcome@123) and open '
            '/spend-analytics/ — the superuser "admin" has no tenant and sees no data.')
