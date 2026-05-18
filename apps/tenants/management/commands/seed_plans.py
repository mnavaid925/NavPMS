"""Seed the four canonical subscription plans (Free / Starter / Pro / Enterprise)."""
from decimal import Decimal
from django.core.management.base import BaseCommand

from apps.tenants.models import Plan


PLAN_FIXTURES = [
    {
        'slug': 'free',
        'name': 'Free',
        'description': 'For evaluation and small teams getting started.',
        'price_monthly': Decimal('0.00'),
        'price_yearly': Decimal('0.00'),
        'trial_days': 0,
        'max_users': 3,
        'max_storage_gb': 1,
        'max_vendors': 10,
        'max_purchase_orders_per_month': 25,
        'features': [
            'Dashboard',
            'Tenant onboarding',
            'Up to 3 users',
            'Up to 10 vendors',
            'Community support',
        ],
        'is_active': True, 'is_public': True, 'sort_order': 1,
    },
    {
        'slug': 'starter',
        'name': 'Starter',
        'description': 'For small purchasing teams ready to digitize requisitions.',
        'price_monthly': Decimal('29.00'),
        'price_yearly': Decimal('290.00'),
        'trial_days': 14,
        'max_users': 10,
        'max_storage_gb': 5,
        'max_vendors': 100,
        'max_purchase_orders_per_month': 250,
        'features': [
            'Everything in Free',
            '10 users included',
            '100 vendors',
            'Email support',
            'Audit log',
        ],
        'is_active': True, 'is_public': True, 'sort_order': 2,
    },
    {
        'slug': 'professional',
        'name': 'Professional',
        'description': 'For growing procurement organizations.',
        'price_monthly': Decimal('99.00'),
        'price_yearly': Decimal('990.00'),
        'trial_days': 14,
        'max_users': 50,
        'max_storage_gb': 50,
        'max_vendors': 1000,
        'max_purchase_orders_per_month': 5000,
        'features': [
            'Everything in Starter',
            '50 users included',
            '1,000 vendors',
            'Custom branding',
            'Advanced security policy',
            'Priority email support',
        ],
        'is_active': True, 'is_public': True, 'sort_order': 3,
    },
    {
        'slug': 'enterprise',
        'name': 'Enterprise',
        'description': 'For large organizations with custom requirements.',
        'price_monthly': Decimal('299.00'),
        'price_yearly': Decimal('2990.00'),
        'trial_days': 30,
        'max_users': 1000,
        'max_storage_gb': 1000,
        'max_vendors': 100000,
        'max_purchase_orders_per_month': 100000,
        'features': [
            'Everything in Professional',
            'Unlimited users (1,000+ included)',
            'SSO / SAML',
            'Dedicated CSM',
            '99.9% uptime SLA',
            'Custom contracts',
        ],
        'is_active': True, 'is_public': True, 'sort_order': 4,
    },
]


class Command(BaseCommand):
    help = 'Seed the four canonical subscription plans.'

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true')

    def handle(self, *args, **options):
        if options['flush']:
            Plan.objects.all().delete()
            self.stdout.write(self.style.WARNING('Deleted all plans.'))

        for data in PLAN_FIXTURES:
            obj, created = Plan.objects.update_or_create(
                slug=data['slug'], defaults=data,
            )
            verb = 'Created' if created else 'Updated'
            self.stdout.write(f'  {verb}: {obj.name}')
        self.stdout.write(self.style.SUCCESS('Plans seeded.'))
