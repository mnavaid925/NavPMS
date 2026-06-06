"""Seed Module 18 demo data: restricted-party lists + screenings + financial-risk profiles +
fraud rules/alerts + policies, per tenant.

Runs LAST in the orchestrator (after seed_vendors / seed_purchase_orders / seed_invoicing) so the
fraud scan and financial monitoring have vendors, bank accounts, POs and invoices to read against.
Idempotent: skips a tenant that already has compliance data unless ``--flush`` is passed.

Creates only its own rows plus a couple of demonstration ``VendorBankAccount`` child rows — a
deliberate shared account number so the bank-conflict fraud detector produces a real alert — and a
restricted-party entry matching a real vendor's name so a screening produces a real hit. It never
mutates seeded Vendor records.
"""
from datetime import date

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.vendors.models import Vendor, VendorBankAccount

from apps.compliance import services
from apps.compliance.models import (
    ComplianceScreening, FinancialRiskProfile, FinancialRiskSnapshot, FraudAlert,
    FraudAlertEvent, FraudRule, Policy, PolicyAcknowledgment, PolicyVersion,
    RestrictedPartyEntry, ScreeningMatch,
)

SEED_CONFLICT_ACCT = 'SEED-COI-000777'

GENERIC_LIST = [
    ('OFAC-SDN', 'Volkov Trading LLC', 'organization', 'RU', 'UKRAINE-EO13662'),
    ('OFAC-SDN', 'Han Heavy Industries', 'organization', 'KP', 'DPRK'),
    ('SAM-EPLS', 'Apex Defense Subcontractor', 'organization', 'US', 'Debarred'),
    ('EU-CFSP', 'Sergei Ivanov', 'person', 'RU', 'EU sanctions'),
]

DEFAULT_RULES = [
    ('split_po', 'Split purchase orders', 'warning',
     'Multiple POs to one vendor by one buyer that each stay just under the approval threshold '
     'but together exceed it.'),
    ('duplicate_invoice', 'Duplicate invoice', 'critical',
     'Invoices from the same vendor with an identical amount and a shared reference or date.'),
    ('round_amount', 'Suspicious round amount', 'info',
     'Large POs or invoices with suspiciously round totals.'),
    ('vendor_bank_conflict', 'Shared vendor bank account', 'critical',
     'A bank account number shared across two or more vendors.'),
    ('conflict_of_interest', 'Vendor / employee conflict of interest', 'warning',
     'A vendor email domain matching an internal user email domain.'),
]

POLICIES = [
    {
        'title': 'Procurement Code of Conduct', 'category': 'ethics',
        'summary': 'Standards of ethical behaviour for everyone involved in purchasing.',
        'body': ('1. Act with integrity and avoid conflicts of interest.\n'
                 '2. Treat all suppliers fairly and transparently.\n'
                 '3. Never solicit or accept gifts that could influence a decision.\n'
                 '4. Protect confidential supplier and pricing information.'),
        'publish': True,
    },
    {
        'title': 'Supplier Sanctions & Screening Policy', 'category': 'procurement',
        'summary': 'All new and existing suppliers must be screened against restricted-party lists.',
        'body': ('All suppliers are screened against OFAC, SAM and EU lists at onboarding and '
                 'periodically thereafter. A confirmed match blocks transactions until cleared by '
                 'Compliance.'),
        'publish': True,
    },
]


class Command(BaseCommand):
    help = 'Seed Module 18 demo data (restricted-party lists, screenings, financial risk, fraud, ' \
           'policies) per tenant.'

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

            if RestrictedPartyEntry.all_objects.filter(tenant=tenant).exists() and not flush:
                self.stdout.write(
                    f'  {tenant.name}: compliance data already exists — skipped (use --flush).')
                continue

            owner = next(
                (u for u in User.objects.filter(tenant=tenant, is_active=True)
                 if u.is_tenant_admin),
                User.objects.filter(tenant=tenant, is_active=True).first(),
            )
            vendors = list(Vendor.all_objects.filter(tenant=tenant).order_by('id'))

            # 1. Restricted-party list + a deliberate match against a real vendor.
            for list_name, name, etype, country, program in GENERIC_LIST:
                RestrictedPartyEntry.all_objects.create(
                    tenant=tenant, list_name=list_name, entity_name=name, entry_type=etype,
                    country=country, program=program)
            flagged_vendor = vendors[0] if vendors else None
            if flagged_vendor:
                RestrictedPartyEntry.all_objects.create(
                    tenant=tenant, list_name='OFAC-SDN', entity_name=flagged_vendor.legal_name,
                    entry_type='organization', program='Demo seeded match')

            # 2. Screenings — one hit (flagged vendor) + one clear.
            screenings = 0
            if flagged_vendor:
                services.run_screening(tenant, vendor=flagged_vendor, user=owner)
                screenings += 1
            if len(vendors) > 1:
                services.run_screening(tenant, vendor=vendors[1], user=owner)
                screenings += 1

            # 3. Fraud rules (all active).
            for code, name, severity, desc in DEFAULT_RULES:
                FraudRule.all_objects.get_or_create(
                    tenant=tenant, code=code,
                    defaults={'name': name, 'severity': severity, 'description': desc,
                              'is_active': True})

            # 4. Deliberate shared-bank-account conflict (child rows only — Vendor untouched).
            if len(vendors) > 1:
                for v in vendors[:2]:
                    VendorBankAccount.all_objects.get_or_create(
                        tenant=tenant, vendor=v, account_number=SEED_CONFLICT_ACCT,
                        defaults={'bank_name': 'Shared Demo Bank', 'account_holder': v.legal_name})

            # 5. Financial-risk profiles for the first few active vendors.
            profiles = 0
            active = [v for v in vendors if v.status == 'active'] or vendors
            for v in active[:5]:
                services.refresh_financial_risk(tenant, v, user=owner)
                profiles += 1

            # 6. Run the fraud scan once so demo alerts exist.
            alerts = services.scan_fraud(tenant, actor=owner)

            # 7. Policies (published) + a couple of acknowledgments.
            ack_users = list(User.objects.filter(tenant=tenant, is_active=True)[:2])
            for spec in POLICIES:
                policy = Policy.all_objects.create(
                    tenant=tenant, policy_number=services.next_policy_number(tenant),
                    title=spec['title'], category=spec['category'], summary=spec['summary'],
                    owner=owner, created_by=owner, requires_acknowledgment=True)
                services.create_policy_version(
                    policy, spec['body'], owner, change_note='Initial version',
                    effective_date=date(2026, 1, 1), publish=spec['publish'])
                if spec['publish'] and policy.current_version_id:
                    for u in ack_users[:1]:
                        services.acknowledge_policy(policy.current_version, u)

            self.stdout.write(
                f'  {tenant.name}: {screenings} screening(s), {profiles} financial profile(s), '
                f'{alerts} fraud alert(s), {len(POLICIES)} policy(ies).')

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('Risk & compliance seeded.'))
        self.stdout.write(
            'Log in as a tenant admin (e.g. admin_acme / Welcome@123) and open /compliance/ — '
            'the superuser "admin" has no tenant and sees no data.')

    def _flush(self, tenant):
        FraudAlertEvent.all_objects.filter(tenant=tenant).delete()
        FraudAlert.all_objects.filter(tenant=tenant).delete()
        FraudRule.all_objects.filter(tenant=tenant).delete()
        ScreeningMatch.all_objects.filter(tenant=tenant).delete()
        ComplianceScreening.all_objects.filter(tenant=tenant).delete()
        RestrictedPartyEntry.all_objects.filter(tenant=tenant).delete()
        FinancialRiskSnapshot.all_objects.filter(tenant=tenant).delete()
        FinancialRiskProfile.all_objects.filter(tenant=tenant).delete()
        PolicyAcknowledgment.all_objects.filter(tenant=tenant).delete()
        PolicyVersion.all_objects.filter(tenant=tenant).delete()
        Policy.all_objects.filter(tenant=tenant).delete()
        # Remove only the demonstration shared-bank rows this seeder created.
        VendorBankAccount.all_objects.filter(
            vendor__tenant=tenant, account_number=SEED_CONFLICT_ACCT).delete()
