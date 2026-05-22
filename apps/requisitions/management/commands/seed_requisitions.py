"""Seed Module 3 demo data: account codes, requisition templates, and
requisitions spanning every status, for each tenant."""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.requisitions.models import (
    AccountCode, Requisition, RequisitionLine, RequisitionStatusEvent,
    RequisitionTemplate, RequisitionTemplateLine,
)
from apps.requisitions.services import next_requisition_number


ACCOUNT_CODES = [
    ('6100-OFF', 'Office Supplies & Stationery'),
    ('6200-IT', 'IT Hardware & Software'),
    ('6300-SVC', 'Professional Services'),
    ('6400-TRV', 'Travel & Accommodation'),
    ('6500-MNT', 'Repairs & Maintenance'),
]

TEMPLATES = [
    ('Monthly office restock', 'office_supplies', '6100-OFF', True, [
        ('A4 paper ream', 12, 'ream', '4.50'),
        ('Ballpoint pens (box)', 6, 'box', '6.00'),
        ('Sticky notes pack', 8, 'pack', '3.25'),
    ]),
    ('New-hire IT kit', 'it_equipment', '6200-IT', True, [
        ('Business laptop', 1, 'unit', '1150.00'),
        ('USB-C docking station', 1, 'unit', '120.00'),
        ('Wireless keyboard + mouse', 1, 'set', '45.00'),
    ]),
]

# (title, category, acct, status, [(desc, qty, unit, price)])
REQUISITIONS = [
    ('Reception area supplies', 'office_supplies', '6100-OFF', 'draft',
     [('Printer toner', 2, 'unit', '78.00'), ('Notebooks', 20, 'unit', '2.50')]),
    ('Developer workstations', 'it_equipment', '6200-IT', 'submitted',
     [('Curved monitor 27"', 4, 'unit', '240.00'), ('Laptop stand', 4, 'unit', '32.00')]),
    ('Annual audit engagement', 'services', '6300-SVC', 'approved',
     [('External audit retainer', 1, 'service', '4200.00')]),
    ('Sales team travel - Q3', 'travel', '6400-TRV', 'converted',
     [('Return flights', 6, 'ticket', '210.00'), ('Hotel nights', 12, 'night', '95.00')]),
    ('HVAC servicing', 'maintenance', '6500-MNT', 'rejected',
     [('HVAC inspection & service', 1, 'service', '650.00')]),
    ('Duplicate office supplies', 'office_supplies', '6100-OFF', 'cancelled',
     [('Printer toner', 2, 'unit', '78.00')]),
]


class Command(BaseCommand):
    help = 'Seed Module 3 data (account codes, templates, requisitions).'

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true')

    def handle(self, *args, **options):
        random.seed(42)
        tenants = list(Tenant.objects.all())
        if not tenants:
            self.stdout.write(self.style.ERROR(
                'No tenants found. Run `seed_tenants` first.'
            ))
            return

        for tenant in tenants:
            set_current_tenant(tenant)

            if options['flush']:
                AccountCode.all_objects.filter(tenant=tenant).delete()
                RequisitionTemplate.all_objects.filter(tenant=tenant).delete()
                Requisition.all_objects.filter(tenant=tenant).delete()

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            if not users:
                self.stdout.write(f'  {tenant.name}: no users — skipped.')
                continue

            if Requisition.all_objects.filter(tenant=tenant).exists() \
                    and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: requisition data already exists — skipped '
                    '(use --flush to re-seed).'
                )
                continue

            self.stdout.write(f'  Seeding requisitions for {tenant.name}…')
            codes = self._seed_account_codes(tenant)
            self._seed_templates(tenant, users[0], codes)
            self._seed_requisitions(tenant, users, codes)

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('\nRequisition demo data seeded.'))
        self.stdout.write(
            'Log in as a tenant admin (e.g. admin_acme / Welcome@123) and open '
            '/requisitions/ to review.\n'
            'WARNING: the Django superuser "admin" has no tenant — requisition '
            'data will not appear for that account.'
        )

    def _seed_account_codes(self, tenant):
        codes = {}
        for code, name in ACCOUNT_CODES:
            obj, _ = AccountCode.all_objects.get_or_create(
                tenant=tenant, code=code, defaults={'name': name},
            )
            codes[code] = obj
        return codes

    def _seed_templates(self, tenant, owner, codes):
        for name, category, acct, shared, lines in TEMPLATES:
            tpl = RequisitionTemplate.all_objects.create(
                tenant=tenant, owner=owner, name=name, category=category,
                description=f'Recurring {category} order.',
                default_account_code=codes.get(acct),
                is_shared=shared,
            )
            for desc, qty, unit, price in lines:
                RequisitionTemplateLine.all_objects.create(
                    tenant=tenant, template=tpl, description=desc,
                    quantity=Decimal(str(qty)), unit=unit,
                    estimated_unit_price=Decimal(price),
                    account_code=codes.get(acct),
                )

    def _seed_requisitions(self, tenant, users, codes):
        now = timezone.now()
        for idx, (title, category, acct, status, lines) in enumerate(REQUISITIONS):
            user = users[idx % len(users)]
            admin = next((u for u in users if u.is_tenant_admin), users[0])
            req = Requisition.all_objects.create(
                tenant=tenant, requested_by=user,
                number=next_requisition_number(tenant),
                title=title, category=category,
                department=random.choice(['Operations', 'Finance', 'IT', 'Sales']),
                priority=random.choice(['low', 'normal', 'high']),
                required_date=(now + timedelta(days=14 + idx)).date(),
                justification='Operational requirement for the current period.',
                status=status,
                submitted_at=now - timedelta(days=6 - idx) if status != 'draft' else None,
                decided_at=(now - timedelta(days=3))
                if status in ('approved', 'rejected', 'converted') else None,
                decided_by=admin
                if status in ('approved', 'rejected', 'converted') else None,
                decision_note='Approved within budget.' if status in ('approved', 'converted')
                else ('Out of budget this quarter.' if status == 'rejected' else ''),
                cancelled_at=now - timedelta(days=1) if status == 'cancelled' else None,
                converted_at=now - timedelta(days=2) if status == 'converted' else None,
                po_reference=f'PO-{tenant.slug[:4].upper()}-{idx + 1:04d}'
                if status == 'converted' else '',
            )
            for desc, qty, unit, price in lines:
                RequisitionLine.all_objects.create(
                    tenant=tenant, requisition=req, description=desc,
                    quantity=Decimal(str(qty)), unit=unit,
                    unit_price=Decimal(price), account_code=codes.get(acct),
                )
            total = sum(
                (ln.line_total for ln in req.lines.all()), Decimal('0.00'),
            )
            req.estimated_total = total
            req.save(update_fields=['estimated_total'])
            self._seed_status_events(req, user, admin, status, now, idx)

    def _seed_status_events(self, req, user, admin, status, now, idx):
        events = [('', 'draft', user, 'Requisition created')]
        if status != 'draft':
            events.append(('draft', 'submitted', user, 'Submitted for approval'))
        if status in ('approved', 'converted'):
            events.append(('submitted', 'approved', admin, 'Approved within budget'))
        if status == 'rejected':
            events.append(('submitted', 'rejected', admin, 'Out of budget this quarter'))
        if status == 'cancelled':
            events.append(('submitted', 'cancelled', user, 'No longer required'))
        if status == 'converted':
            events.append(('approved', 'converted', admin,
                           f'Converted to PO {req.po_reference}'))
        for n, (frm, to, who, note) in enumerate(events):
            RequisitionStatusEvent.all_objects.create(
                tenant=req.tenant, requisition=req,
                from_status=frm, to_status=to, changed_by=who, note=note,
                created_at=now - timedelta(days=6 - idx, hours=-n),
            )
