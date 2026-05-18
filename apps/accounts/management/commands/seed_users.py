"""Seed tenant-admin + staff users for the three demo tenants."""
from django.core.management.base import BaseCommand
from faker import Faker

from apps.core.models import Tenant, set_current_tenant
from apps.accounts.models import User

DEFAULT_PASSWORD = 'Welcome@123'
STAFF_PER_TENANT = 4
STAFF_ROLES = ['procurement_manager', 'buyer', 'approver', 'requester']


class Command(BaseCommand):
    help = 'Seed tenant_admin + 4 staff users per demo tenant.'

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true')

    def handle(self, *args, **options):
        if options['flush']:
            User.objects.filter(is_superuser=False).delete()
            self.stdout.write(self.style.WARNING('Flushed non-superuser accounts.'))

        fake = Faker()
        Faker.seed(42)

        tenants = list(Tenant.objects.all())
        if not tenants:
            self.stdout.write(self.style.ERROR(
                'No tenants found. Run `seed_tenants` first.'
            ))
            return

        for tenant in tenants:
            set_current_tenant(tenant)
            admin_username = f'admin_{tenant.slug.replace("-", "_")}'
            admin, created = User.objects.get_or_create(
                username=admin_username,
                defaults={
                    'email': f'admin@{tenant.slug}.local',
                    'first_name': 'Tenant',
                    'last_name': 'Admin',
                    'tenant': tenant,
                    'role': 'tenant_admin',
                    'is_tenant_admin': True,
                    'is_staff': False,
                },
            )
            admin.set_password(DEFAULT_PASSWORD)
            admin.tenant = tenant
            admin.role = 'tenant_admin'
            admin.is_tenant_admin = True
            admin.save()
            verb = 'created' if created else 'updated'
            self.stdout.write(f'  {verb}: {admin.username} ({tenant.name})')

            for i in range(STAFF_PER_TENANT):
                role = STAFF_ROLES[i % len(STAFF_ROLES)]
                first = fake.first_name()
                last = fake.last_name()
                base_username = f'{first.lower()}.{last.lower()}.{tenant.slug}'
                username = base_username[:150]
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        'email': f'{first.lower()}.{last.lower()}@{tenant.slug}.local',
                        'first_name': first,
                        'last_name': last,
                        'tenant': tenant,
                        'role': role,
                        'job_title': role.replace('_', ' ').title(),
                        'phone': fake.phone_number()[:30],
                    },
                )
                if created:
                    user.set_password(DEFAULT_PASSWORD)
                    user.tenant = tenant
                    user.role = role
                    user.save()
                    self.stdout.write(f'    + {user.username} [{role}]')

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS(
            f'\nAll users use password: {DEFAULT_PASSWORD}'
        ))
