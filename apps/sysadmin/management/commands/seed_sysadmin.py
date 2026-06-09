"""Seed Module 21 demo data: roles & permission matrix, system config (currency/tax/numbering),
an SSO provider, backup policy + runs, an API key and a webhook.

Runs LAST in the orchestrator. Idempotent: master data uses ``get_or_create`` and the demo
integrations are guarded by existence checks, so a re-run without ``--flush`` is a no-op. ``--flush``
wipes and re-seeds this tenant's sysadmin data.

Seeds, per tenant: the 8 built-in roles with the default permission grants (mirrors current
behaviour), a system-configuration singleton (USD base), 3 currencies, 3 tax codes, 2 number
sequences, one disabled SAML identity provider (mock connector) with a simulated login event, a daily
backup policy with one successful + one failed run, an API key, and an active webhook with a sample
delivery — all driven through the real services so the dashboards populate.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant

from apps.sysadmin import backups, services
from apps.sysadmin.models import (
    ApiKey, BackupPolicy, BackupRun, Currency, IdentityProvider, NumberSequence, RestoreRequest,
    RoleDefinition, RolePermission, SSOLoginEvent, SystemConfiguration, TaxCode, Webhook,
    WebhookDelivery,
)

CURRENCIES = [
    {'code': 'USD', 'name': 'US Dollar', 'symbol': '$', 'rate': 1, 'is_base': True},
    {'code': 'EUR', 'name': 'Euro', 'symbol': '€', 'rate': '1.08', 'is_base': False},
    {'code': 'GBP', 'name': 'Pound Sterling', 'symbol': '£', 'rate': '1.27', 'is_base': False},
]
TAXCODES = [
    {'code': 'VAT20', 'name': 'Standard VAT 20%', 'rate': '20', 'tax_type': 'vat',
     'jurisdiction': 'UK', 'is_default': True},
    {'code': 'GST10', 'name': 'GST 10%', 'rate': '10', 'tax_type': 'gst', 'jurisdiction': 'AU'},
    {'code': 'ZERO', 'name': 'Zero-rated / Exempt', 'rate': '0', 'tax_type': 'none'},
]
SEQUENCES = [
    {'doc_type': 'purchase_order', 'name': 'Purchase Order', 'prefix': 'PO', 'padding': 5,
     'next_number': 1001, 'include_year': True},
    {'doc_type': 'supplier_invoice', 'name': 'Supplier Invoice', 'prefix': 'SINV', 'padding': 6,
     'next_number': 500, 'include_year': False},
]


class Command(BaseCommand):
    help = 'Seed Module 21 demo data (roles, config, SSO, backups, API keys, webhooks) per tenant.'

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
                self._flush(tenant)

            owner = next(
                (u for u in User.objects.filter(tenant=tenant, is_active=True) if u.is_tenant_admin),
                User.objects.filter(tenant=tenant, is_active=True).first(),
            )

            # 1. Roles & permission matrix (idempotent).
            services.ensure_system_roles(tenant)
            services.sync_default_grants(tenant)

            # 2. System configuration + masters.
            config = services.get_system_configuration(tenant)
            if not config.company_legal_name:
                config.company_legal_name = f'{tenant.name} Ltd'
                config.save(update_fields=['company_legal_name', 'updated_at'])
            for spec in CURRENCIES:
                Currency.all_objects.get_or_create(
                    tenant=tenant, code=spec['code'],
                    defaults={'name': spec['name'], 'symbol': spec['symbol'],
                              'exchange_rate_to_base': spec['rate'], 'is_base': spec['is_base']})
            default_tax = None
            for spec in TAXCODES:
                tc, _ = TaxCode.all_objects.get_or_create(
                    tenant=tenant, code=spec['code'],
                    defaults={'name': spec['name'], 'rate': spec['rate'],
                              'tax_type': spec['tax_type'],
                              'jurisdiction': spec.get('jurisdiction', ''),
                              'is_default': spec.get('is_default', False)})
                if spec.get('is_default'):
                    default_tax = tc
            if default_tax and not config.default_tax_code_id:
                config.default_tax_code = default_tax
                config.save(update_fields=['default_tax_code', 'updated_at'])
            for spec in SEQUENCES:
                NumberSequence.all_objects.get_or_create(
                    tenant=tenant, doc_type=spec['doc_type'],
                    defaults={'name': spec['name'], 'prefix': spec['prefix'],
                              'padding': spec['padding'], 'next_number': spec['next_number'],
                              'include_year': spec['include_year']})

            # 3. SSO provider (+ a simulated login event).
            provider, created = IdentityProvider.all_objects.get_or_create(
                tenant=tenant, name='Corporate SSO (SAML)',
                defaults={'protocol': 'saml', 'connector': 'mock', 'is_active': False,
                          'is_default': True, 'entity_id': f'urn:{tenant.slug}:navpms',
                          'sso_url': 'https://idp.example.com/sso',
                          'jit_provisioning': True, 'default_role_code': 'requester'})
            if created:
                services.simulate_sso_login(provider, f'jane.doe@{tenant.slug}.example.com', user=owner)

            # 4. Backup policy + runs.
            if not BackupPolicy.all_objects.filter(tenant=tenant).exists():
                policy = BackupPolicy.all_objects.create(
                    tenant=tenant, name='Nightly full backup', frequency='daily', scope='full',
                    retention_days=30, storage_target='s3', encryption_enabled=True, run_hour=2)
                backups.run_backup(tenant, policy=policy, trigger='scheduled', user=owner)
                now = timezone.now()
                BackupRun.all_objects.create(
                    tenant=tenant, run_number=services.next_backup_run_number(tenant), policy=policy,
                    status='failed', trigger='scheduled', scope='full', started_at=now,
                    finished_at=now, connector='mock',
                    message='Demo: storage target unreachable.')

            # 5. API key.
            if not ApiKey.all_objects.filter(tenant=tenant).exists():
                services.issue_api_key(
                    tenant, name='ERP Integration', scopes=['po.view', 'invoice.view'], user=owner)

            # 6. Webhook + a sample delivery.
            if not Webhook.all_objects.filter(tenant=tenant).exists():
                webhook = Webhook.all_objects.create(
                    tenant=tenant, name='ERP order sync',
                    target_url='https://hooks.example.com/navpms',
                    events=['po.issued', 'invoice.paid'], secret=f'whsec_{tenant.slug}_demo',
                    is_active=True)
                WebhookDelivery.all_objects.create(
                    tenant=tenant, webhook=webhook, event='po.issued',
                    payload={'po_number': 'PO-DEMO-00001', 'amount': 1250.00}, status='success',
                    status_code=200, attempts=1, response_excerpt='OK',
                    delivered_at=timezone.now())

            self.stdout.write(
                f'  {tenant.name}: roles + config + SSO + backups + API key + webhook seeded.')

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('System administration & security seeded.'))
        self.stdout.write(
            'Log in as a tenant admin (e.g. admin_acme / Welcome@123) and open /sysadmin/ — '
            'the superuser "admin" has no tenant and sees no data.')

    def _flush(self, tenant):
        WebhookDelivery.all_objects.filter(tenant=tenant).delete()
        Webhook.all_objects.filter(tenant=tenant).delete()
        ApiKey.all_objects.filter(tenant=tenant).delete()
        RestoreRequest.all_objects.filter(tenant=tenant).delete()
        BackupRun.all_objects.filter(tenant=tenant).delete()
        BackupPolicy.all_objects.filter(tenant=tenant).delete()
        SSOLoginEvent.all_objects.filter(tenant=tenant).delete()
        IdentityProvider.all_objects.filter(tenant=tenant).delete()
        # Clear the config FK before deleting tax codes (SET_NULL would too, but be explicit).
        SystemConfiguration.objects.filter(tenant=tenant).update(default_tax_code=None)
        NumberSequence.all_objects.filter(tenant=tenant).delete()
        Currency.all_objects.filter(tenant=tenant).delete()
        TaxCode.all_objects.filter(tenant=tenant).delete()
        SystemConfiguration.objects.filter(tenant=tenant).delete()
        RolePermission.all_objects.filter(tenant=tenant).delete()
        RoleDefinition.all_objects.filter(tenant=tenant).delete()
