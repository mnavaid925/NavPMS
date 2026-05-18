"""Seed three demo tenants with subscriptions, invoices, branding, audit logs, health metrics."""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant
from apps.tenants.models import (
    AuditLog, BrandingSettings, HealthMetric, Invoice, Plan,
    SecuritySettings, Subscription, Transaction,
)


TENANT_FIXTURES = [
    {
        'slug': 'acme', 'name': 'Acme Corp',
        'email': 'hello@acme.local', 'phone': '+1 555 0100',
        'industry': 'Manufacturing', 'timezone': 'America/New_York',
        'plan_slug': 'professional', 'billing_cycle': 'yearly',
        'branding': {'primary_color': '#0d6efd', 'secondary_color': '#6610f2'},
    },
    {
        'slug': 'globex', 'name': 'Globex Industries',
        'email': 'contact@globex.local', 'phone': '+44 20 7946 0958',
        'industry': 'Retail', 'timezone': 'Europe/London',
        'plan_slug': 'starter', 'billing_cycle': 'monthly',
        'branding': {'primary_color': '#198754', 'secondary_color': '#20c997'},
    },
    {
        'slug': 'stark', 'name': 'Stark Industries',
        'email': 'pepper@stark.local', 'phone': '+1 555 0200',
        'industry': 'Defense', 'timezone': 'America/Los_Angeles',
        'plan_slug': 'enterprise', 'billing_cycle': 'yearly',
        'branding': {'primary_color': '#dc3545', 'secondary_color': '#ffc107'},
    },
]

AUDIT_ACTIONS = [
    ('user.login', 'info', 'User signed in'),
    ('user.created', 'info', 'New user added'),
    ('invoice.created', 'info', 'Invoice issued'),
    ('invoice.charged', 'info', 'Invoice paid via gateway'),
    ('branding.updated', 'info', 'Branding settings updated'),
    ('security.updated', 'warning', 'Password policy strengthened'),
    ('subscription.assigned', 'info', 'Plan changed'),
    ('api.rate_limited', 'warning', 'API rate limit triggered'),
    ('user.failed_login', 'warning', 'Failed login attempt'),
]


class Command(BaseCommand):
    help = 'Seed three demo tenants with subscriptions, invoices, branding, audit, metrics.'

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true')

    def handle(self, *args, **options):
        random.seed(42)
        if options['flush']:
            for slug in [t['slug'] for t in TENANT_FIXTURES]:
                Tenant.objects.filter(slug=slug).delete()
            self.stdout.write(self.style.WARNING(
                'Deleted existing demo tenants (cascade).'
            ))

        plans_by_slug = {p.slug: p for p in Plan.objects.all()}
        if not plans_by_slug:
            self.stdout.write(self.style.ERROR(
                'No plans found. Run `seed_plans` first.'
            ))
            return

        for data in TENANT_FIXTURES:
            tenant, created = Tenant.objects.get_or_create(
                slug=data['slug'],
                defaults={
                    'name': data['name'],
                    'email': data['email'],
                    'phone': data['phone'],
                    'industry': data['industry'],
                    'timezone': data['timezone'],
                },
            )
            set_current_tenant(tenant)
            verb = 'Created' if created else 'Updated'
            self.stdout.write(f'  {verb} tenant: {tenant.name}')

            branding, _ = BrandingSettings.objects.get_or_create(tenant=tenant)
            for k, v in data['branding'].items():
                setattr(branding, k, v)
            branding.email_from_name = tenant.name
            branding.email_from_address = f'no-reply@{tenant.slug}.local'
            branding.support_email = tenant.email
            branding.save()

            sec, _ = SecuritySettings.objects.get_or_create(tenant=tenant)
            if tenant.slug == 'stark':
                sec.mfa_required = True
                sec.password_min_length = 12
                sec.password_require_special = True
                sec.session_timeout_minutes = 60
                sec.save()

            plan = plans_by_slug[data['plan_slug']]
            sub, _ = Subscription.objects.get_or_create(
                tenant=tenant, plan=plan,
                defaults={
                    'status': 'active',
                    'billing_cycle': data['billing_cycle'],
                    'started_at': timezone.now() - timedelta(days=45),
                    'current_period_start': timezone.now() - timedelta(days=15),
                    'current_period_end': timezone.now() + timedelta(days=15),
                },
            )

            self._seed_invoices(tenant, sub)
            self._seed_audit(tenant)
            self._seed_metrics(tenant)

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('Demo tenants seeded.'))

    def _seed_invoices(self, tenant, sub):
        if Invoice.objects.filter(tenant=tenant).exists():
            return
        amount = sub.amount_for_cycle
        now = timezone.now()
        slug = tenant.slug.upper().replace('-', '')[:6]
        for i in range(3):
            issued = now - timedelta(days=30 * (3 - i))
            status = 'paid' if i < 2 else 'sent'
            inv = Invoice.objects.create(
                tenant=tenant, subscription=sub,
                number=f'INV-{slug}-{i + 1:05d}',
                status=status,
                subtotal=amount,
                tax=Decimal('0.00'),
                total=amount,
                currency=sub.plan.currency,
                line_items=[{
                    'description': f'{sub.plan.name} subscription',
                    'quantity': 1,
                    'unit_price': float(amount),
                    'amount': float(amount),
                }],
                issued_at=issued,
                due_at=issued + timedelta(days=14),
                paid_at=issued + timedelta(days=2) if status == 'paid' else None,
            )
            if status == 'paid':
                Transaction.objects.create(
                    tenant=tenant, invoice=inv,
                    gateway='mock',
                    gateway_ref=f'mock_seed_{tenant.slug}_{i}',
                    amount=amount, currency=sub.plan.currency,
                    status='succeeded',
                    method='card',
                    message='Seeded paid transaction',
                )

    def _seed_audit(self, tenant):
        if AuditLog.objects.filter(tenant=tenant).count() > 5:
            return
        now = timezone.now()
        for i in range(25):
            action, level, message = random.choice(AUDIT_ACTIONS)
            AuditLog.all_objects.create(
                tenant=tenant,
                user=None,
                action=action,
                level=level,
                message=message,
                ip_address=f'10.0.0.{random.randint(1, 254)}',
                created_at=now - timedelta(hours=i * 4),
            )

    def _seed_metrics(self, tenant):
        if HealthMetric.objects.filter(tenant=tenant).count() > 30:
            return
        now = timezone.now()
        base = {'acme': 22, 'globex': 6, 'stark': 87}.get(tenant.slug, 10)
        for d in range(30):
            ts = now - timedelta(days=29 - d)
            HealthMetric.all_objects.create(
                tenant=tenant, metric_type='user_count',
                value=Decimal(base + random.randint(-1, 2)),
                recorded_at=ts,
            )
            HealthMetric.all_objects.create(
                tenant=tenant, metric_type='api_calls',
                value=Decimal(random.randint(800, 5000)),
                recorded_at=ts,
            )
            HealthMetric.all_objects.create(
                tenant=tenant, metric_type='storage_mb',
                value=Decimal(d * 5 + random.randint(50, 100)),
                recorded_at=ts,
            )
            HealthMetric.all_objects.create(
                tenant=tenant, metric_type='active_sessions',
                value=Decimal(random.randint(2, base // 2 + 3)),
                recorded_at=ts,
            )
