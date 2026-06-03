"""Seed Module 11 demo data: purchase orders in varied statuses (draft, issued,
acknowledged, partially received, received, closed, cancelled, one with an applied
change order, and one generated from an approved requisition) driven through the
real PO services so the timeline, totals and change orders are produced exactly as
in production."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.purchase_orders.models import (
    PurchaseOrder,
    PurchaseOrderChangeOrder,
    PurchaseOrderLine,
)
from apps.purchase_orders.services import (
    acknowledge_po,
    apply_change_order,
    cancel_po,
    close_po,
    create_po_from_requisition,
    create_purchase_order,
    issue_po,
    next_change_number,
    recompute_totals,
    record_line_receipt,
)
from apps.vendors.models import Vendor


class Command(BaseCommand):
    help = 'Seed Module 11 demo data (purchase orders across every status).'

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
                PurchaseOrder.all_objects.filter(tenant=tenant).delete()

            if PurchaseOrder.all_objects.filter(tenant=tenant).exists() and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: purchase order data already exists — skipped '
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

            self.stdout.write(f'  Seeding purchase order data for {tenant.name}…')
            v = vendors * 3  # cycle so we always have enough
            today = timezone.localdate()
            count = 0

            # 1. Draft (supplier assigned, lines added, not issued)
            self._make_po(
                tenant, admin, v[0], 'Office supplies restock',
                [('A4 paper (box of 5 reams)', 'box', '20', '32.50'),
                 ('Ballpoint pens (pack of 50)', 'pack', '15', '8.75')],
                delivery_in=14)
            count += 1

            # 2. Issued — awaiting acknowledgment
            po = self._make_po(
                tenant, admin, v[1], 'Server rack hardware',
                [('1U rack server', 'unit', '4', '4200.00'),
                 ('Rack-mount rails', 'set', '4', '180.00')],
                delivery_in=30)
            self._safe(po, lambda: issue_po(po, admin, dispatch_method='portal'))
            count += 1

            # 3. Acknowledged
            po = self._make_po(
                tenant, admin, v[2], 'Marketing print run',
                [('Brochures (1000 ct)', 'unit', '5', '450.00'),
                 ('Roll-up banners', 'unit', '3', '120.00')],
                delivery_in=21)
            self._safe(po, lambda: issue_po(po, admin, dispatch_method='email'))
            self._safe(po, lambda: acknowledge_po(po, admin, note='Confirmed — production scheduled.'))
            count += 1

            # 4. Partially received
            po = self._make_po(
                tenant, admin, v[0], 'Quarterly stationery',
                [('Notebooks (pack of 12)', 'pack', '40', '14.00'),
                 ('Sticky notes (carton)', 'unit', '10', '22.00')],
                delivery_in=10)
            self._safe(po, lambda: issue_po(po, admin, dispatch_method='portal'))
            self._safe(po, lambda: acknowledge_po(po, admin))
            first_line = po.lines.order_by('line_no').first()
            if first_line:
                # receive part of the first line only → partially_received
                self._safe(po, lambda: record_line_receipt(
                    po, first_line, Decimal('20'), admin))
            count += 1

            # 5. Received in full (closeable)
            po = self._make_po(
                tenant, admin, v[1], 'Laptop batch Q2',
                [('14" business laptop', 'unit', '8', '1150.00')],
                delivery_in=-2, tax='920.00')
            self._safe(po, lambda: issue_po(po, admin, dispatch_method='portal'))
            self._safe(po, lambda: acknowledge_po(po, admin))
            self._receive_all(po, admin)
            count += 1

            # 6. Closed out (received then closed)
            po = self._make_po(
                tenant, admin, v[2], 'Annual maintenance kit',
                [('Filters & spares kit', 'set', '6', '310.00')],
                delivery_in=-20)
            self._safe(po, lambda: issue_po(po, admin, dispatch_method='manual'))
            self._safe(po, lambda: acknowledge_po(po, admin))
            self._receive_all(po, admin)
            self._safe(po, lambda: close_po(po, admin, note='Delivered & invoiced.'))
            count += 1

            # 7. Cancelled (issued, then cancelled)
            po = self._make_po(
                tenant, admin, v[0], 'Trial sample order',
                [('Sample widget', 'unit', '2', '95.00')],
                delivery_in=7)
            self._safe(po, lambda: issue_po(po, admin, dispatch_method='portal'))
            self._safe(po, lambda: cancel_po(po, admin, 'Requirement withdrawn by department.'))
            count += 1

            # 8. With an applied change order (issued → acknowledged → revised)
            po = self._make_po(
                tenant, admin, v[1], 'Bulk steel order',
                [('Steel sheet 2mm', 'unit', '100', '45.00'),
                 ('Steel rod 10mm', 'unit', '200', '12.50')],
                delivery_in=45)
            self._safe(po, lambda: issue_po(po, admin, dispatch_method='portal'))
            self._safe(po, lambda: acknowledge_po(po, admin))
            self._apply_change_order(tenant, po, admin, today)
            count += 1

            # 9. Generated from an approved requisition (if one is available)
            self._from_requisition(tenant, admin)

            self.stdout.write(self.style.SUCCESS(
                f'    {tenant.name}: {count} purchase orders seeded across every status.'))

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('\n=== Purchase order seeding complete ==='))
        self.stdout.write(
            '\nLogin as a tenant admin (e.g. admin_acme / Welcome@123) to see the data.\n'
            'WARNING: Django superuser "admin" has no tenant — data will not appear there.\n'
        )

    # ----- helpers -----

    def _make_po(self, tenant, admin, vendor, title, lines, *, delivery_in=14,
                 tax='0.00', shipping='0.00'):
        po = create_purchase_order(
            tenant=tenant, user=admin, title=title, vendor=vendor, owner=admin,
            currency='USD', order_date=timezone.localdate(),
            expected_delivery_date=timezone.localdate() + timedelta(days=delivery_in),
            tax_amount=Decimal(tax), shipping_amount=Decimal(shipping),
            payment_terms='Net 30',
        )
        for idx, (desc, uom, qty, price) in enumerate(lines, start=1):
            PurchaseOrderLine.all_objects.create(
                tenant=tenant, purchase_order=po, line_no=idx, description=desc,
                uom=uom, quantity=Decimal(qty), unit_price=Decimal(price),
            )
        recompute_totals(po)
        po.refresh_from_db()
        return po

    def _receive_all(self, po, admin):
        for line in po.lines.order_by('line_no'):
            if line.outstanding_quantity > 0:
                self._safe(po, lambda l=line: record_line_receipt(
                    po, l, l.outstanding_quantity, admin))

    def _apply_change_order(self, tenant, po, admin, today):
        lines = list(po.lines.order_by('line_no'))
        if not lines:
            return
        proposed = [{
            'line_id': lines[0].id,
            'quantity': str(lines[0].quantity + Decimal('20')),
            'unit_price': str(lines[0].unit_price),
        }]
        co = PurchaseOrderChangeOrder.all_objects.create(
            tenant=tenant, purchase_order=po,
            change_number=next_change_number(po), change_type='quantity',
            reason='Increase sheet quantity to cover an extra production run.',
            new_expected_delivery_date=today + timedelta(days=50),
            proposed_lines=proposed, status='draft', created_by=admin,
        )
        self._safe(po, lambda: apply_change_order(co, admin))

    def _from_requisition(self, tenant, admin):
        from apps.requisitions.models import Requisition
        req = (
            Requisition.all_objects
            .filter(tenant=tenant, status='approved')
            .order_by('id')
            .first()
        )
        if not req:
            return
        try:
            po = create_po_from_requisition(req, admin)
            self.stdout.write(
                f'      generated {po.po_number} from approved requisition {req.number}.')
        except (ValidationError, Exception) as exc:  # defensive — never abort the seed
            self.stdout.write(self.style.WARNING(
                f'      could not generate PO from requisition: {exc}'))

    def _safe(self, po, fn):
        """Run a lifecycle step on ``po``, then refresh it so the next chained step
        sees the new status (the services re-fetch internally and don't mutate the
        passed instance). Swallows ValidationError so seeding never aborts."""
        try:
            fn()
        except ValidationError:
            pass
        po.refresh_from_db()
