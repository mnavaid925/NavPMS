"""Seed Module 4 demo data: approval rules + steps, a delegation, and route
every already-submitted requisition through the engine."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.approvals.models import (
    ApprovalDelegation, ApprovalRequest, ApprovalRule, ApprovalStep,
)
from apps.approvals.services import start_approval
from apps.requisitions.models import Requisition


class Command(BaseCommand):
    help = 'Seed Module 4 data (approval rules, steps, delegation, routed requests).'

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true')

    def handle(self, *args, **options):
        tenants = list(Tenant.objects.all())
        if not tenants:
            self.stdout.write(self.style.ERROR(
                'No tenants found. Run `seed_tenants` first.'
            ))
            return

        for tenant in tenants:
            set_current_tenant(tenant)

            if options['flush']:
                ApprovalRequest.all_objects.filter(tenant=tenant).delete()
                ApprovalRule.all_objects.filter(tenant=tenant).delete()
                ApprovalDelegation.all_objects.filter(tenant=tenant).delete()

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            if len(users) < 2:
                self.stdout.write(f'  {tenant.name}: needs 2+ users — skipped.')
                continue

            if ApprovalRule.all_objects.filter(tenant=tenant).exists() \
                    and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: approval data already exists — skipped '
                    '(use --flush to re-seed).'
                )
                continue

            self.stdout.write(f'  Seeding approvals for {tenant.name}…')
            admin = next((u for u in users if u.is_tenant_admin), users[0])
            manager = next(
                (u for u in users if u.role == 'procurement_manager'),
                users[1 % len(users)],
            )
            approver = next(
                (u for u in users if u.role == 'approver'),
                users[-1],
            )

            self._seed_rules(tenant, manager, admin, approver)
            self._seed_delegation(tenant, approver, manager)
            self._route_requisitions(tenant, admin)

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('\nApproval workflow data seeded.'))
        self.stdout.write(
            'Log in as a tenant admin (e.g. admin_acme / Welcome@123) and open '
            '/approvals/ for the approver inbox.\n'
            'WARNING: the Django superuser "admin" has no tenant — approval data '
            'will not appear for that account.'
        )

    def _seed_rules(self, tenant, manager, admin, approver):
        # Standard rule — any requisition, single manager sign-off.
        standard = ApprovalRule.all_objects.create(
            tenant=tenant, name='Standard approval',
            description='Single-step manager sign-off for routine requisitions.',
            priority=100, max_amount=None,
        )
        ApprovalStep.all_objects.create(
            tenant=tenant, rule=standard, order=1, name='Manager review',
            approver=manager, sla_hours=48, escalate_to=admin,
        )
        # High-value rule — evaluated first; two-step chain.
        high = ApprovalRule.all_objects.create(
            tenant=tenant, name='High-value approval (over $1,000)',
            description='Two-step chain for higher-value requisitions.',
            priority=50, min_amount=1000,
        )
        ApprovalStep.all_objects.create(
            tenant=tenant, rule=high, order=1, name='Manager review',
            approver=manager, sla_hours=24, escalate_to=admin,
        )
        ApprovalStep.all_objects.create(
            tenant=tenant, rule=high, order=2, name='Finance / admin sign-off',
            approver=admin, sla_hours=48, escalate_to=admin,
        )

    def _seed_delegation(self, tenant, delegator, delegate):
        today = timezone.now().date()
        ApprovalDelegation.all_objects.create(
            tenant=tenant, delegator=delegator, delegate=delegate,
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=12),
            reason='Covering approvals during leave.',
            is_active=True,
        )

    def _route_requisitions(self, tenant, actor):
        submitted = Requisition.all_objects.filter(
            tenant=tenant, status='submitted',
        )
        routed = 0
        for req in submitted:
            if ApprovalRequest.all_objects.filter(requisition=req).exists():
                continue
            if start_approval(req, req.requested_by) is not None:
                routed += 1
        if routed:
            self.stdout.write(f'    routed {routed} submitted requisition(s)')
