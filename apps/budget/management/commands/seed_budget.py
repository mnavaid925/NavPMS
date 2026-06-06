"""Seed Module 16 demo data: a fiscal period + an active budget per tenant with allocations sized
so the dashboard/variance pages show a healthy, a near-limit and an over-budget cost centre.

Runs AFTER ``seed_requisitions`` / ``seed_purchase_orders`` / ``seed_invoicing`` (so account codes
plus committed POs and actual invoices exist to consume against). Idempotent: skips a tenant that
already has a budget unless ``--flush`` is passed. After creating the budget it runs a couple of
availability checks against the seeded requisitions so the check log + banner are populated.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.requisitions.models import AccountCode, Requisition

from apps.budget.models import (
    Budget, BudgetAllocation, BudgetCheck, BudgetPeriod,
)
from apps.budget import services

# Allocation amounts keyed by account code. Sized against the seeded spend so each cost centre lands
# in a different band (healthy / near-limit / over budget) once POs + invoices are consumed.
ALLOCATIONS = [
    ('6100-OFF', Decimal('20000.00')),   # office supplies — comfortably under
    ('6200-IT', Decimal('15000.00')),    # IT — near the limit
    ('6300-SVC', Decimal('8000.00')),    # services — small, likely over once committed
    ('6400-TRV', Decimal('10000.00')),
    ('6500-MNT', Decimal('6000.00')),
]


class Command(BaseCommand):
    help = 'Seed Module 16 demo data (a fiscal period + active budget + allocations per tenant).'

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
                BudgetCheck.all_objects.filter(tenant=tenant).delete()
                Budget.all_objects.filter(tenant=tenant).delete()
                BudgetPeriod.all_objects.filter(tenant=tenant).delete()

            if Budget.all_objects.filter(tenant=tenant).exists() and not flush:
                self.stdout.write(
                    f'  {tenant.name}: budgets already exist — skipped (use --flush to re-seed).')
                continue

            owner = next(
                (u for u in User.objects.filter(tenant=tenant, is_active=True)
                 if u.is_tenant_admin),
                User.objects.filter(tenant=tenant, is_active=True).first(),
            )

            period, _ = BudgetPeriod.all_objects.get_or_create(
                tenant=tenant, name='FY2026',
                defaults={
                    'period_type': 'annual', 'start_date': date(2026, 1, 1),
                    'end_date': date(2026, 12, 31), 'status': 'active', 'is_default': True,
                },
            )

            budget = Budget.all_objects.create(
                tenant=tenant, budget_number=services.next_budget_number(tenant),
                name='Operating budget FY2026', period=period, status='draft',
                owner=owner, created_by=owner,
                description='Annual operating budget across the core cost centres.',
            )
            services.record_status_event(budget, '', 'draft', owner, note='Seeded')

            line_no = 0
            for code, amount in ALLOCATIONS:
                acc = AccountCode.all_objects.filter(tenant=tenant, code=code).first()
                if not acc:
                    continue
                line_no += 1
                BudgetAllocation.all_objects.create(
                    tenant=tenant, budget=budget, line_no=line_no,
                    account_code=acc, allocated_amount=amount,
                )

            if line_no == 0:
                self.stdout.write(self.style.WARNING(
                    f'  {tenant.name}: no account codes found (run seed_requisitions first) — '
                    'budget left as draft.'))
                continue
            services.activate_budget(budget, owner)

            # Run a couple of availability checks so the check log + banner have data.
            checks = 0
            for req in Requisition.all_objects.filter(
                    tenant=tenant, status__in=('submitted', 'approved'))[:2]:
                services.check_requisition_budget(req, owner)
                checks += 1

            data = services.budget_consumption(budget)
            t = data['totals']
            self.stdout.write(
                f'  {tenant.name}: {budget.budget_number} ${t["allocated"]} allocated, '
                f'${t["actual"]} actual, ${t["committed"]} committed, '
                f'{t["over_count"]} over-budget centre(s); {checks} check(s) run.')

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('Budget & cost management seeded.'))
        self.stdout.write(
            'Log in as a tenant admin (e.g. admin_acme / Welcome@123) and open /budget/ — '
            'the superuser "admin" has no tenant and sees no data.')
