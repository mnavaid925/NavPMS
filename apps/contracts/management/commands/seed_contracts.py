"""Seed Module 9 demo data: a clause library, contract templates and a set of
contracts in varied statuses (draft from a template, pending signature, active
with obligations, expiring-soon, auto-renewing, amended and terminated) driven
through the real contract services so signatures, amendments and the timeline
are produced exactly as in production."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.contracts.models import (
    Contract,
    ContractAmendment,
    ContractClause,
    ContractClauseLine,
    ContractObligation,
    ContractSignatory,
    ContractTemplate,
    ContractTemplateClause,
)
from apps.contracts.services import (
    apply_amendment,
    next_amendment_number,
    next_contract_number,
    send_for_signature,
    sign_contract,
    terminate_contract,
)
from apps.core.models import Tenant, set_current_tenant
from apps.vendors.models import Vendor

CLAUSES = [
    ('Payment Terms', 'payment',
     'The Buyer shall pay all undisputed invoices within thirty (30) days of receipt.'),
    ('Confidentiality', 'confidentiality',
     'Each party shall keep confidential all non-public information disclosed under this Agreement.'),
    ('Limitation of Liability', 'liability',
     "Neither party's aggregate liability shall exceed the total fees paid in the prior twelve (12) months."),
    ('Termination for Convenience', 'termination',
     'Either party may terminate this Agreement on sixty (60) days written notice.'),
    ('Intellectual Property', 'ip',
     'All deliverables created under this Agreement are the property of the Buyer upon full payment.'),
    ('Service Levels', 'sla',
     'The Supplier shall meet the service levels set out in the applicable Statement of Work.'),
]


class Command(BaseCommand):
    help = 'Seed Module 9 demo data (clause library + templates + contracts across statuses).'

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true')

    def handle(self, *args, **options):
        tenants = list(Tenant.objects.all())
        if not tenants:
            self.stdout.write(self.style.ERROR('No tenants found. Run `seed_tenants` first.'))
            return

        for tenant in tenants:
            set_current_tenant(tenant)
            if options['flush']:
                Contract.all_objects.filter(tenant=tenant).delete()
                ContractTemplate.all_objects.filter(tenant=tenant).delete()
                ContractClause.all_objects.filter(tenant=tenant).delete()

            if Contract.all_objects.filter(tenant=tenant).exists() and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: contract data already exists — skipped '
                    '(use --flush to re-seed).'
                )
                continue

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            admin = next((u for u in users if u.is_tenant_admin), users[0] if users else None)
            if not admin:
                self.stdout.write(f'    {tenant.name}: no admin user — skipped.')
                continue

            vendors = list(Vendor.all_objects.filter(
                tenant=tenant, status='active').order_by('legal_name')[:5])
            if not vendors:
                self.stdout.write(
                    f'    {tenant.name}: no active vendors — skipped. Run seed_vendors first.')
                continue

            self.stdout.write(f'  Seeding contract data for {tenant.name}…')

            clauses = self._ensure_clauses(tenant)
            msa = self._ensure_template(
                tenant, admin, 'Standard Service Agreement', 'service', clauses[:4])
            self._ensure_template(
                tenant, admin, 'Mutual NDA', 'nda', clauses[1:2])

            today = timezone.localdate()
            v = (vendors * 3)  # cycle so we always have enough

            # 1. Draft authored from the template
            self._draft_from_template(tenant, admin, msa, v[0],
                                      title='IT support services 2026')

            # 2. Pending signature
            pend = self._create_contract(
                tenant, admin, v[1], clauses[:4],
                title='Facilities management agreement', ctype='service',
                value=Decimal('120000.00'),
                start=today, end=today + timedelta(days=365))
            if pend:
                self._add_signatories(pend, admin, v[1])
                try:
                    send_for_signature(pend, admin)
                except ValidationError:
                    pass

            # 3. Active with obligations (fully signed)
            active = self._create_contract(
                tenant, admin, v[2], clauses[:4],
                title='Cloud hosting master agreement', ctype='msa',
                value=Decimal('240000.00'),
                start=today - timedelta(days=60), end=today + timedelta(days=305))
            if active:
                self._sign_and_activate(active, admin, v[2])
                self._add_obligations(tenant, active, today)

            # 4. Expiring soon (active, no alert sent yet)
            expiring = self._create_contract(
                tenant, admin, v[0], clauses[:3],
                title='Office cleaning contract', ctype='service',
                value=Decimal('36000.00'),
                start=today - timedelta(days=340), end=today + timedelta(days=20))
            if expiring:
                self._sign_and_activate(expiring, admin, v[0])

            # 5. Auto-renewing (active)
            auto = self._create_contract(
                tenant, admin, v[1], clauses[:3],
                title='Software subscription (auto-renew)', ctype='supply',
                value=Decimal('48000.00'), auto_renew=True,
                start=today - timedelta(days=350), end=today + timedelta(days=15))
            if auto:
                self._sign_and_activate(auto, admin, v[1])

            # 6. Amended (active → one applied amendment → revision 2)
            amended = self._create_contract(
                tenant, admin, v[2], clauses[:4],
                title='Logistics framework agreement', ctype='framework',
                value=Decimal('500000.00'),
                start=today - timedelta(days=120), end=today + timedelta(days=245))
            if amended:
                amended = self._sign_and_activate(amended, admin, v[2])
                amd = ContractAmendment.all_objects.create(
                    tenant=tenant, contract=amended,
                    amendment_number=next_amendment_number(amended),
                    change_type='term_extension', title='Extend term by 6 months',
                    description='Extend the framework term and uplift the value.',
                    new_value=Decimal('560000.00'),
                    new_end_date=amended.end_date + timedelta(days=180),
                    status='draft', created_by=admin,
                )
                apply_amendment(amd, admin)

            # 7. Terminated
            term = self._create_contract(
                tenant, admin, v[0], clauses[:4],
                title='Catering services agreement', ctype='service',
                value=Decimal('80000.00'),
                start=today - timedelta(days=200), end=today + timedelta(days=165))
            if term:
                term = self._sign_and_activate(term, admin, v[0])
                terminate_contract(term, admin, 'Supplier underperformed against SLAs.')

            self.stdout.write(self.style.SUCCESS(
                f'    {tenant.name}: clause library, 2 templates and 7 contracts seeded.'))

        self.stdout.write(self.style.SUCCESS('\n=== Contract seeding complete ==='))
        self.stdout.write(
            '\nLogin as a tenant admin (e.g. admin_acme / Welcome@123) to see the data.\n'
            'WARNING: Django superuser "admin" has no tenant — data will not appear there.\n'
        )

    # ----- helpers -----

    def _ensure_clauses(self, tenant):
        clauses = []
        for idx, (title, category, body) in enumerate(CLAUSES):
            obj = ContractClause.all_objects.filter(tenant=tenant, title=title).first()
            if not obj:
                obj = ContractClause.all_objects.create(
                    tenant=tenant, title=title, category=category, body=body,
                    is_standard=True, is_active=True, sort_order=idx,
                )
            clauses.append(obj)
        return clauses

    def _ensure_template(self, tenant, admin, title, ctype, clauses):
        template = ContractTemplate.all_objects.filter(tenant=tenant, title=title).first()
        if template:
            return template
        template = ContractTemplate.all_objects.create(
            tenant=tenant, title=title, contract_type=ctype,
            description=f'Standard {title.lower()} template.',
            is_shared=True, created_by=admin,
        )
        for order, clause in enumerate(clauses, start=1):
            ContractTemplateClause.all_objects.create(
                tenant=tenant, template=template, clause=clause,
                heading=clause.title, body=clause.body, sort_order=order,
            )
        return template

    def _draft_from_template(self, tenant, admin, template, vendor, *, title):
        if Contract.all_objects.filter(tenant=tenant, title=title).exists():
            return None
        contract = Contract.all_objects.create(
            tenant=tenant, contract_number=next_contract_number(tenant),
            title=title, contract_type=template.contract_type, vendor=vendor,
            template=template, status='draft', created_by=admin, owner=admin,
            value=Decimal('60000.00'),
        )
        for tc in template.clauses.all():
            ContractClauseLine.all_objects.create(
                tenant=tenant, contract=contract, clause=tc.clause,
                heading=tc.heading, body=tc.body, sort_order=tc.sort_order,
            )
        self._assemble(contract)
        return contract

    def _create_contract(self, tenant, admin, vendor, clauses, *, title, ctype,
                         value, start, end, auto_renew=False):
        if Contract.all_objects.filter(tenant=tenant, title=title).exists():
            return None
        contract = Contract.all_objects.create(
            tenant=tenant, contract_number=next_contract_number(tenant),
            title=title, contract_type=ctype, vendor=vendor, value=value,
            currency='USD', start_date=start, end_date=end, auto_renew=auto_renew,
            status='draft', created_by=admin, owner=admin,
            terms_and_conditions='Standard terms apply. Demo seed data.',
        )
        for order, clause in enumerate(clauses, start=1):
            ContractClauseLine.all_objects.create(
                tenant=tenant, contract=contract, clause=clause,
                heading=clause.title, body=clause.body, sort_order=order,
            )
        self._assemble(contract)
        return contract

    def _add_signatories(self, contract, admin, vendor):
        ContractSignatory.all_objects.create(
            tenant=contract.tenant, contract=contract, party='internal',
            user=admin, name=admin.get_full_name() or admin.username,
            email=admin.email, title='Contract Manager', order=1,
        )
        ContractSignatory.all_objects.create(
            tenant=contract.tenant, contract=contract, party='vendor',
            vendor=vendor, name=vendor.legal_name, email=vendor.email,
            title='Authorised Signatory', order=2,
        )

    def _sign_and_activate(self, contract, admin, vendor):
        self._add_signatories(contract, admin, vendor)
        try:
            send_for_signature(contract, admin)
        except ValidationError:
            return contract
        for signatory in contract.signatories.all().order_by('order'):
            try:
                sign_contract(signatory, admin, signatory.name)
            except ValidationError:
                pass
        # sign_contract activates via a freshly-fetched row, so refresh the local
        # instance before any caller acts on its (now stale) status.
        contract.refresh_from_db()
        return contract

    def _add_obligations(self, tenant, contract, today):
        ContractObligation.all_objects.create(
            tenant=tenant, contract=contract, obligation_type='payment',
            title='Quarterly hosting fee', amount=Decimal('60000.00'),
            due_date=today + timedelta(days=30), responsible_party='internal',
            status='pending',
        )
        ContractObligation.all_objects.create(
            tenant=tenant, contract=contract, obligation_type='deliverable',
            title='Onboarding & migration', amount=Decimal('0.00'),
            due_date=today - timedelta(days=10), responsible_party='vendor',
            status='completed', completed_at=timezone.now(),
        )
        ContractObligation.all_objects.create(
            tenant=tenant, contract=contract, obligation_type='milestone',
            title='Mid-term service review', amount=Decimal('0.00'),
            due_date=today + timedelta(days=180), responsible_party='internal',
            status='pending',
        )
        ContractObligation.all_objects.create(
            tenant=tenant, contract=contract, obligation_type='penalty',
            title='SLA breach credit (if applicable)',
            penalty_amount=Decimal('5000.00'),
            due_date=today + timedelta(days=90), responsible_party='vendor',
            status='pending',
        )

    def _assemble(self, contract):
        parts = [f'{l.heading}\n{l.body}' for l in contract.clause_lines.all()]
        contract.body = '\n\n'.join(parts)
        contract.save(update_fields=['body', 'updated_at'])
