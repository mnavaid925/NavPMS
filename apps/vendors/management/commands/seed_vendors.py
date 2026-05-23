"""Seed Module 5 demo data: categories, segments, vendors across every status,
contacts/docs/banks, risk assessments, onboarding applications, blacklist events."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.vendors.models import (
    Vendor, VendorBankAccount, VendorBlacklistEvent, VendorCategory,
    VendorContact, VendorDocument, VendorOnboardingApplication,
    VendorRiskAssessment, VendorSegment,
)
from apps.vendors.services import (
    apply_risk_assessment, blacklist_vendor, convert_application_to_vendor,
    next_vendor_number, suspend_vendor,
)


CATEGORIES = [
    ('RAW', 'Raw Materials'),
    ('IT',  'IT Services'),
    ('MAINT', 'Maintenance'),
    ('OFFICE', 'Office Supplies'),
    ('LOG', 'Logistics & Freight'),
]

SEGMENTS = [
    ('STRAT', 'Strategic', 'danger'),
    ('TACT', 'Tactical', 'warning'),
    ('PREF', 'Preferred', 'success'),
    ('APPR', 'Approved', 'primary'),
]

VENDORS = [
    # legal_name, trade, vendor_type, category_code, segment_code, status, country, email, tax_id
    ('Global Steel Corp', 'GSC', 'manufacturer', 'RAW', 'STRAT', 'active', 'USA', 'sales@globalsteel.example', 'GS-12345'),
    ('Acme IT Solutions', 'AcmeIT', 'service_provider', 'IT', 'STRAT', 'active', 'USA', 'hello@acmeit.example', 'AIT-789'),
    ('FastTrack Logistics', 'FTL', 'service_provider', 'LOG', 'PREF', 'active', 'India', 'orders@fasttrack.example', 'FT-456'),
    ('Riverside Office Supplies', '', 'distributor', 'OFFICE', 'APPR', 'pending_verification', 'Canada', 'info@riverside.example', ''),
    ('Mountain Maintenance Co', '', 'contractor', 'MAINT', 'TACT', 'suspended', 'USA', 'support@mountainmaint.example', 'MM-321'),
    ('Sunset Distributors', '', 'distributor', 'OFFICE', '', 'blacklisted', 'Mexico', 'sales@sunset.example', 'SD-654'),
    ('Pioneer Materials Inc', '', 'manufacturer', 'RAW', '', 'draft', 'UK', '', ''),
    ('Beta Tech Consulting', '', 'consultant', 'IT', '', 'draft', 'Germany', '', ''),
]


class Command(BaseCommand):
    help = 'Seed Module 5 demo data (vendors, categories, segments, risk, blacklist).'

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
                VendorBlacklistEvent.all_objects.filter(tenant=tenant).delete()
                VendorRiskAssessment.all_objects.filter(tenant=tenant).delete()
                VendorOnboardingApplication.all_objects.filter(tenant=tenant).delete()
                VendorBankAccount.all_objects.filter(tenant=tenant).delete()
                VendorDocument.all_objects.filter(tenant=tenant).delete()
                VendorContact.all_objects.filter(tenant=tenant).delete()
                # Disconnect portal users before deleting vendors
                portal_users = User.objects.filter(vendor__tenant=tenant)
                portal_users.update(vendor=None)
                portal_users.filter(role='vendor_portal').delete()
                Vendor.all_objects.filter(tenant=tenant).delete()
                VendorCategory.all_objects.filter(tenant=tenant).delete()
                VendorSegment.all_objects.filter(tenant=tenant).delete()

            if Vendor.all_objects.filter(tenant=tenant).exists() and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: vendor data already exists — skipped '
                    '(use --flush to re-seed).'
                )
                continue

            self.stdout.write(f'  Seeding vendors for {tenant.name}…')

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            admin = next((u for u in users if u.is_tenant_admin), users[0] if users else None)
            if not admin:
                self.stdout.write(f'    {tenant.name}: no admin user — skipped.')
                continue

            cats = {}
            for code, name in CATEGORIES:
                cats[code] = VendorCategory.all_objects.create(
                    tenant=tenant, code=code, name=name, is_active=True,
                )

            segs = {}
            for code, name, color in SEGMENTS:
                segs[code] = VendorSegment.all_objects.create(
                    tenant=tenant, code=code, name=name, color=color, is_active=True,
                )

            created_vendors = {}
            for (legal, trade, vtype, ccode, scode, status, country, email, tax) in VENDORS:
                v = Vendor.all_objects.create(
                    tenant=tenant,
                    vendor_number=next_vendor_number(tenant),
                    legal_name=legal, trade_name=trade,
                    vendor_type=vtype,
                    tax_id=tax,
                    email=email,
                    phone='+1-555-0100',
                    country=country,
                    address_line1='100 Demo Street',
                    city='Springfield', state='ST', postal_code='00000',
                    primary_contact_name=f'Contact for {legal}',
                    primary_contact_email=email or f'contact@{legal.lower().split()[0]}.example',
                    primary_contact_phone='+1-555-0101',
                    category=cats.get(ccode),
                    segment=segs.get(scode) if scode else None,
                    status=status,
                    is_verified=(status == 'active'),
                    verified_at=timezone.now() if status == 'active' else None,
                    verified_by=admin if status == 'active' else None,
                )
                created_vendors[legal] = v

                # 1-2 contacts
                VendorContact.all_objects.create(
                    tenant=tenant, vendor=v, name='Jane Doe',
                    role='Account Manager', email=f'jane@{legal.lower().split()[0]}.example',
                    phone='+1-555-0200', is_primary=True,
                )
                if status in ('active', 'pending_verification'):
                    VendorContact.all_objects.create(
                        tenant=tenant, vendor=v, name='Bob Smith',
                        role='Operations', email=f'bob@{legal.lower().split()[0]}.example',
                        phone='+1-555-0201',
                    )

                # 1 document
                VendorDocument.all_objects.create(
                    tenant=tenant, vendor=v, doc_type='registration',
                    title=f'{legal} business registration',
                    description='Demo seed — no file attached.',
                    expires_at=date.today() + timedelta(days=365),
                    is_verified=(status == 'active'),
                    verified_at=timezone.now() if status == 'active' else None,
                    verified_by=admin if status == 'active' else None,
                )
                if status == 'active':
                    VendorDocument.all_objects.create(
                        tenant=tenant, vendor=v, doc_type='tax',
                        title=f'{legal} tax certificate',
                        description='Demo seed.',
                        expires_at=date.today() + timedelta(days=180),
                        is_verified=True, verified_at=timezone.now(), verified_by=admin,
                    )

                # 1 bank account on active vendors
                if status in ('active', 'pending_verification'):
                    VendorBankAccount.all_objects.create(
                        tenant=tenant, vendor=v,
                        bank_name='First National Bank',
                        account_holder=legal,
                        account_number=f'1234{v.pk:06d}',
                        branch='Main', iban='', swift_code='FNBAUS33',
                        currency='USD', country='USA', is_primary=True,
                    )

            # Risk assessments on the active vendors
            risk_specs = [
                ('Global Steel Corp',          15, 20, 10, 25),  # low
                ('Acme IT Solutions',          30, 35, 40, 30),  # medium
                ('FastTrack Logistics',        20, 45, 30, 25),  # low/medium
                ('Riverside Office Supplies',  55, 60, 45, 50),  # high
                ('Mountain Maintenance Co',    70, 75, 80, 60),  # critical
            ]
            for (name, fin, op, comp, qual) in risk_specs:
                v = created_vendors.get(name)
                if not v:
                    continue
                ra = VendorRiskAssessment.all_objects.create(
                    tenant=tenant, vendor=v,
                    assessment_date=date.today() - timedelta(days=7),
                    valid_until=date.today() + timedelta(days=180),
                    financial_score=Decimal(fin),
                    operational_score=Decimal(op),
                    compliance_score=Decimal(comp),
                    quality_score=Decimal(qual),
                    notes='Demo seed assessment.',
                    assessed_by=admin,
                )
                apply_risk_assessment(ra, user=admin)

            # Blacklist events to set up suspended / blacklisted statuses
            mm = created_vendors.get('Mountain Maintenance Co')
            if mm:
                suspend_vendor(
                    mm, user=admin, reason='Repeated late deliveries',
                    effective_date=date.today() - timedelta(days=30),
                    end_date=date.today() + timedelta(days=60),
                    notes='Suspension pending review of Q3 delivery metrics.',
                )
            sd = created_vendors.get('Sunset Distributors')
            if sd:
                blacklist_vendor(
                    sd, user=admin,
                    reason='Compliance violation — counterfeit goods',
                    effective_date=date.today() - timedelta(days=90),
                    notes='Permanently blocked after audit findings.',
                )

            # Onboarding applications
            VendorOnboardingApplication.all_objects.create(
                tenant=tenant,
                company_name='New Horizons Trading',
                contact_name='Alice Lee',
                contact_email='alice@newhorizons.example',
                contact_phone='+1-555-9000',
                country='Singapore',
                vendor_type='distributor',
                tax_id='NH-1001', registration_number='SG-NH-001',
                website='https://newhorizons.example',
                service_description='Wholesale distribution of office equipment.',
                status='submitted',
            )
            VendorOnboardingApplication.all_objects.create(
                tenant=tenant,
                company_name='QuickFix Engineering',
                contact_name='Mark Patel',
                contact_email='mark@quickfix.example',
                contact_phone='+1-555-9100',
                country='India',
                vendor_type='contractor',
                tax_id='QF-2002',
                service_description='HVAC and electrical maintenance services.',
                status='under_review',
                reviewed_by=admin,
                reviewed_at=timezone.now(),
            )
            approved_app = VendorOnboardingApplication.all_objects.create(
                tenant=tenant,
                company_name='Heritage Crafts Ltd',
                contact_name='Priya Sharma',
                contact_email='priya@heritage.example',
                country='UK',
                vendor_type='manufacturer',
                tax_id='HC-3003',
                service_description='Custom packaging materials.',
                status='submitted',
            )
            convert_application_to_vendor(approved_app, admin)

        self.stdout.write(self.style.SUCCESS('Seeded vendor data for all tenants.'))
