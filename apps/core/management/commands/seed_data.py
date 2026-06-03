"""Master seed orchestrator. Runs plans, tenants, users in order."""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Seed demo data (plans + tenants + users + invoices + audit logs).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush',
            action='store_true',
            help='Wipe existing demo data before reseeding.',
        )

    def handle(self, *args, **options):
        flush = options['flush']
        self.stdout.write(self.style.NOTICE('=== Seeding NavPMS demo data ==='))

        steps = [
            ('seed_plans', 'Subscription plans'),
            ('seed_tenants', 'Tenants + subscriptions + invoices + branding + audit'),
            ('seed_users', 'Tenant admin + staff users'),
            ('seed_portal', 'Portal widgets + notifications + requisitions + reports'),
            ('seed_requisitions', 'Account codes + requisition templates + requisitions'),
            ('seed_approvals', 'Approval rules + steps + delegations + routed requests'),
            ('seed_vendors', 'Vendors + categories + segments + risk + onboarding'),
            ('seed_sourcing', 'Sourcing events + invitees + bids + evaluations + awards'),
            ('seed_rfx', 'RFx templates + events + responses + evaluations + shortlist'),
            ('seed_auctions', 'Auctions + lots + participants + live bid ledger + award'),
            ('seed_contracts', 'Clause library + templates + contracts + signatories + obligations + amendments'),
            ('seed_catalog', 'Catalog categories + items + tiers + price-change + punch-out config + supplier upload'),
        ]

        for cmd, label in steps:
            self.stdout.write(self.style.MIGRATE_HEADING(f'-> {label}'))
            kwargs = {'flush': flush} if flush else {}
            try:
                call_command(cmd, **kwargs)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'   FAILED: {exc}'))
                raise

        self.stdout.write(self.style.SUCCESS('\n=== Seeding complete ==='))
        self.stdout.write(
            '\nLogin with one of:\n'
            '  - admin_acme   / Welcome@123  (Acme Corp tenant admin)\n'
            '  - admin_globex / Welcome@123  (Globex tenant admin)\n'
            '  - admin_stark  / Welcome@123  (Stark Industries tenant admin)\n'
            '\nWARNING: Django superuser "admin" has no tenant assigned.\n'
            '         Module data will NOT appear when logged in as "admin".\n'
        )
