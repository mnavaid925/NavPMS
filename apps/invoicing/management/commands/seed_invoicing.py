"""Seed Module 14 demo data: payment terms + supplier (AP) invoices across every status,
three-way matching, a buyer<->supplier dispute thread, and payment vouchers driven through
the real mock payment gateway. Built against the dispatched / received purchase orders, so the
matched invoices match cleanly and the no-receipt invoices surface match exceptions exactly as
in production.

Runs AFTER ``seed_goods_receipt`` (which posts accepted quantities back to the PO lines).
Idempotent: skips a tenant that already has invoices unless ``--flush`` is passed.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.purchase_orders.models import PO_DISPATCHED_STATUSES, PurchaseOrder

from apps.invoicing.models import PaymentTerm, PaymentVoucher, SupplierInvoice
from apps.invoicing.services import (
    add_invoice_line,
    approve_invoice,
    approve_voucher,
    create_invoice,
    create_voucher,
    pay_voucher,
    raise_dispute,
    add_dispute_note,
    recompute_invoice_totals,
    reject_invoice,
    cancel_invoice,
    schedule_voucher,
    submit_invoice,
)

_TERMS = [
    {'code': 'NET30', 'name': 'Net 30', 'net_days': 30,
     'discount_percent': Decimal('0'), 'discount_days': 0},
    {'code': 'NET60', 'name': 'Net 60', 'net_days': 60,
     'discount_percent': Decimal('0'), 'discount_days': 0},
    {'code': '2-10-NET30', 'name': '2/10 Net 30', 'net_days': 30,
     'discount_percent': Decimal('2.00'), 'discount_days': 10},
]


class Command(BaseCommand):
    help = ('Seed Module 14 demo data (payment terms + supplier invoices across every '
            'status + three-way match + disputes + vouchers paid via the gateway).')

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
                PaymentVoucher.all_objects.filter(tenant=tenant).delete()
                SupplierInvoice.all_objects.filter(tenant=tenant).delete()
                PaymentTerm.all_objects.filter(tenant=tenant).delete()

            # Payment terms are a master — always ensure they exist (idempotent).
            terms = {}
            for spec in _TERMS:
                term, _ = PaymentTerm.all_objects.get_or_create(
                    tenant=tenant, code=spec['code'], defaults={**spec})
                terms[spec['code']] = term

            if SupplierInvoice.all_objects.filter(tenant=tenant).exists() and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: invoice data already exists — skipped '
                    '(use --flush to re-seed).')
                continue

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            admin = next((u for u in users if u.is_tenant_admin), users[0] if users else None)
            if not admin:
                self.stdout.write(f'    {tenant.name}: no admin user — skipped.')
                continue

            dispatched = list(
                PurchaseOrder.all_objects.filter(
                    tenant=tenant, status__in=PO_DISPATCHED_STATUSES)
                .exclude(vendor__isnull=True).order_by('po_number'))
            received = [
                po for po in dispatched
                if any((l.received_quantity or 0) > 0
                       for l in po.lines.exclude(delivery_status='cancelled'))
            ]
            other = [po for po in dispatched if po not in received]
            if not dispatched:
                self.stdout.write(
                    f'    {tenant.name}: no dispatched purchase orders — skipped. '
                    'Run seed_purchase_orders first.')
                continue

            # Pools: matched invoices need a received PO; the rest can use any dispatched PO.
            recv = (received * 4) if received else (dispatched * 4)
            pool = (other * 4) if other else (dispatched * 4)
            today = timezone.localdate()
            self.stdout.write(f'  Seeding invoice data for {tenant.name}…')
            count = 0
            net30, net60, disc = terms['NET30'], terms['NET60'], terms['2-10-NET30']

            # 1. Draft — captured/entered, not yet submitted.
            inv = self._bill(tenant, admin, recv[0], net30, ref='SUP-DRAFT-001',
                             invoice_date=today)
            if inv:
                count += 1

            # 2. Paid — matched, approved, vouchered and PAID through the gateway.
            inv = self._bill(tenant, admin, recv[1], net30, ref='SUP-PAID-002',
                             invoice_date=today - timedelta(days=5))
            if inv:
                self._safe(inv, lambda i=inv: submit_invoice(i, admin))
                self._safe(inv, lambda i=inv: approve_invoice(i, admin, override=True))
                voucher = self._safe_ret(lambda i=inv: create_voucher(i, admin))
                if voucher:
                    self._safe(voucher, lambda v=voucher: approve_voucher(v, admin))
                    self._safe(voucher, lambda v=voucher: pay_voucher(v, admin))
                count += 1

            # 3. Approved + scheduled voucher + early-payment discount opportunity.
            inv = self._bill(tenant, admin, recv[2], disc, ref='SUP-APPR-003',
                             invoice_date=today)
            if inv:
                self._safe(inv, lambda i=inv: submit_invoice(i, admin))
                self._safe(inv, lambda i=inv: approve_invoice(i, admin, override=True))
                voucher = self._safe_ret(lambda i=inv: create_voucher(i, admin))
                if voucher:
                    self._safe(voucher, lambda v=voucher: approve_voucher(v, admin))
                    self._safe(voucher, lambda v=voucher: schedule_voucher(v, admin))
                count += 1

            # 4. Submitted with match exceptions + OVERDUE (billed before receipt, back-dated).
            inv = self._bill(tenant, admin, pool[0], net30, ref='SUP-EXC-004',
                             invoice_date=today - timedelta(days=45), price_factor=Decimal('1.15'))
            if inv:
                self._safe(inv, lambda i=inv: submit_invoice(i, admin))
                count += 1

            # 5. Disputed — submitted, then queried, with a supplier reply.
            inv = self._bill(tenant, admin, pool[1], net60, ref='SUP-DISP-005',
                             invoice_date=today - timedelta(days=3))
            if inv:
                self._safe(inv, lambda i=inv: submit_invoice(i, admin))
                self._safe(inv, lambda i=inv: raise_dispute(
                    i, admin, 'Unit price does not match the agreed PO price.'))
                self._safe(inv, lambda i=inv: add_dispute_note(
                    i, admin, 'Apologies — we will reissue at the agreed price.',
                    is_from_vendor=True))
                count += 1

            # 6. Rejected.
            inv = self._bill(tenant, admin, pool[2], net30, ref='SUP-REJ-006',
                             invoice_date=today - timedelta(days=2))
            if inv:
                self._safe(inv, lambda i=inv: submit_invoice(i, admin))
                self._safe(inv, lambda i=inv: reject_invoice(
                    i, admin, 'Duplicate of an already-paid invoice.'))
                count += 1

            # 7. Cancelled (from draft).
            inv = self._bill(tenant, admin, pool[3], net30, ref='SUP-CAN-007',
                             invoice_date=today)
            if inv:
                self._safe(inv, lambda i=inv: cancel_invoice(i, admin, 'Entered in error.'))
                count += 1

            self.stdout.write(self.style.SUCCESS(
                f'    {tenant.name}: {len(terms)} payment terms + {count} invoices seeded '
                '(draft, paid, approved+voucher, exceptions/overdue, disputed, rejected, '
                'cancelled).'))

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('\n=== Invoice seeding complete ==='))
        self.stdout.write(
            '\nLogin as a tenant admin (e.g. admin_acme / Welcome@123) to see the data.\n'
            'WARNING: Django superuser "admin" has no tenant — data will not appear there.\n')

    # ----- helpers -----

    def _bill(self, tenant, admin, po, term, *, ref, invoice_date,
              fraction=Decimal('1'), price_factor=Decimal('1')):
        """Create an invoice against ``po``, one line per line with received/ordered qty."""
        inv = self._safe_ret(lambda: create_invoice(
            tenant=tenant, user=admin, vendor=po.vendor, purchase_order=po,
            payment_term=term, currency=po.currency, supplier_invoice_ref=ref,
            invoice_date=invoice_date, received_date=invoice_date))
        if not inv:
            return None
        for pol in po.lines.exclude(delivery_status='cancelled').order_by('line_no'):
            base_qty = pol.received_quantity if (pol.received_quantity or 0) > 0 else pol.quantity
            qty = (Decimal(str(base_qty or '0')) * fraction).quantize(Decimal('0.01'))
            if qty <= 0:
                continue
            price = (Decimal(str(pol.unit_price or '0')) * price_factor).quantize(Decimal('0.01'))
            self._safe(inv, lambda p=pol, q=qty, pr=price: add_invoice_line(
                inv, purchase_order_line=p, quantity=q, unit_price=pr))
        self._safe(inv, lambda i=inv: recompute_invoice_totals(i))
        inv.refresh_from_db()
        return inv

    def _safe(self, obj, fn):
        """Run a step, swallow ValidationError, and refresh ``obj`` for the next step."""
        try:
            fn()
        except ValidationError:
            pass
        if obj is not None:
            try:
                obj.refresh_from_db()
            except obj.__class__.DoesNotExist:
                pass

    def _safe_ret(self, fn):
        try:
            return fn()
        except ValidationError:
            return None
