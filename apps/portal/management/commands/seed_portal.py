"""Seed Module 2 demo data: dashboard widgets, notifications, quick
requisitions, and saved reports for each tenant's users."""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.portal.models import (
    DashboardWidget, Notification, QuickRequisition, QuickRequisitionItem,
    SavedReport,
)
from apps.portal.services import ensure_default_widgets, next_requisition_number


NOTIFICATIONS = [
    ('deadline', 'high', 'Requisition due in 2 days',
     'Your office-supplies requisition needs items before the cut-off.'),
    ('approval', 'urgent', 'Approval required: IT Equipment',
     'A submitted requisition is waiting for a manager decision.'),
    ('delivery', 'normal', 'Delivery scheduled for tomorrow',
     'Vendor confirmed dispatch of your last approved order.'),
    ('system', 'low', 'Welcome to the User Portal',
     'Customize your dashboard widgets from the Widgets page.'),
    ('info', 'normal', 'Monthly spend report ready',
     'Your saved spend-by-category report has fresh data.'),
]

REQUISITIONS = [
    ('Office stationery restock', 'office_supplies', 'normal', 'approved',
     [('A4 paper ream', 10, 'ream', '4.50'), ('Ballpoint pens (box)', 5, 'box', '6.00')]),
    ('Laptop docking stations', 'it_equipment', 'high', 'submitted',
     [('USB-C dock', 3, 'unit', '120.00')]),
    ('Quarterly cleaning service', 'services', 'normal', 'approved',
     [('Deep clean - floor', 1, 'service', '480.00')]),
    ('Team offsite travel', 'travel', 'high', 'draft',
     [('Return flight', 4, 'ticket', '210.00'), ('Hotel night', 8, 'night', '95.00')]),
    ('Printer maintenance kit', 'maintenance', 'low', 'draft',
     []),
]

REPORTS = [
    ('My spend by category', 'spend_by_category'),
    ('Monthly spend trend', 'spend_by_month'),
    ('Requisitions by status', 'requisition_status'),
]


class Command(BaseCommand):
    help = 'Seed Module 2 portal data (widgets, notifications, requisitions, reports).'

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
                DashboardWidget.all_objects.filter(tenant=tenant).delete()
                Notification.all_objects.filter(tenant=tenant).delete()
                QuickRequisition.all_objects.filter(tenant=tenant).delete()
                SavedReport.all_objects.filter(tenant=tenant).delete()

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            if not users:
                self.stdout.write(f'  {tenant.name}: no users — skipped.')
                continue

            if QuickRequisition.all_objects.filter(tenant=tenant).exists() \
                    and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: portal data already exists — skipped '
                    '(use --flush to re-seed).'
                )
                continue

            self.stdout.write(f'  Seeding portal for {tenant.name}…')
            for user in users:
                ensure_default_widgets(tenant, user)
                self._seed_notifications(tenant, user)
                self._seed_requisitions(tenant, user)
                self._seed_reports(tenant, user)

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('\nPortal demo data seeded.'))
        self.stdout.write(
            'Log in as a tenant admin (e.g. admin_acme / Welcome@123) and open '
            '/portal/ to see the personalized dashboard.\n'
            'WARNING: the Django superuser "admin" has no tenant — portal data '
            'will not appear for that account.'
        )

    def _seed_notifications(self, tenant, user):
        now = timezone.now()
        for i, (category, priority, title, message) in enumerate(NOTIFICATIONS):
            Notification.all_objects.create(
                tenant=tenant, user=user,
                category=category, priority=priority,
                title=title, message=message,
                is_read=(i >= 3),
                read_at=now - timedelta(hours=i) if i >= 3 else None,
                created_at=now - timedelta(hours=i * 6),
            )

    def _seed_requisitions(self, tenant, user):
        now = timezone.now()
        for idx, (title, category, priority, status, items) in enumerate(REQUISITIONS):
            req = QuickRequisition.all_objects.create(
                tenant=tenant, user=user,
                number=next_requisition_number(tenant),
                title=title, category=category, priority=priority,
                status=status,
                description=f'Auto-seeded {category} requisition.',
                vendor_name=random.choice(['Acme Supplies', 'TechMart', 'Globex Ltd', '']),
                needed_by=(now + timedelta(days=7 + idx)).date(),
                justification='Routine operational need.',
                submitted_at=now - timedelta(days=idx) if status != 'draft' else None,
                decided_at=now - timedelta(hours=idx) if status == 'approved' else None,
                decided_by=user if status == 'approved' else None,
                decision_note='Approved within budget.' if status == 'approved' else '',
            )
            for name, qty, unit, price in items:
                QuickRequisitionItem.all_objects.create(
                    tenant=tenant, requisition=req,
                    name=name, quantity=Decimal(str(qty)),
                    unit=unit, unit_price=Decimal(price),
                )
            total = sum(
                (it.line_total for it in req.items.all()), Decimal('0.00'),
            )
            req.estimated_total = total
            req.save(update_fields=['estimated_total'])

    def _seed_reports(self, tenant, user):
        today = timezone.now().date()
        for name, rtype in REPORTS:
            SavedReport.all_objects.create(
                tenant=tenant, user=user,
                name=name, report_type=rtype,
                date_from=today - timedelta(days=90),
                date_to=today,
            )
