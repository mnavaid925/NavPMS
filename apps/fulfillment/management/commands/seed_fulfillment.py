"""Seed Module 12 demo data: shipments (ASNs) across every status, a live carrier
tracking ledger, a delivered shipment that posts receipts back into the PO, a
split-delivery PO with two shipments + a backorder for the remainder, and an overdue
shipment to light up the alert sweep. Driven through the real fulfillment services so
the timelines, tracking events and PO roll-ups are produced exactly as in production.

Runs AFTER ``seed_purchase_orders`` — it ships against the dispatched POs created there.
Idempotent: skips a tenant that already has shipments unless ``--flush`` is passed.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.fulfillment.models import Backorder, Shipment
from apps.fulfillment.services import (
    add_shipment_line,
    advise_shipment,
    confirm_delivery,
    create_shipment,
    open_backorder,
    remaining_to_ship_line,
    sync_tracking,
)
from apps.purchase_orders.models import PurchaseOrder


class Command(BaseCommand):
    help = ('Seed Module 12 demo data (shipments across every status + split '
            'delivery + backorder).')

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
                Shipment.all_objects.filter(tenant=tenant).delete()
                Backorder.all_objects.filter(tenant=tenant).delete()

            if Shipment.all_objects.filter(tenant=tenant).exists() and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: fulfillment data already exists — skipped '
                    '(use --flush to re-seed).'
                )
                continue

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            admin = next((u for u in users if u.is_tenant_admin), users[0] if users else None)
            if not admin:
                self.stdout.write(f'    {tenant.name}: no admin user — skipped.')
                continue

            pos = list(
                PurchaseOrder.all_objects.filter(
                    tenant=tenant,
                    status__in=('issued', 'acknowledged', 'partially_received'),
                ).order_by('po_number')
            )
            if not pos:
                self.stdout.write(
                    f'    {tenant.name}: no dispatched purchase orders — skipped. '
                    'Run seed_purchase_orders first.')
                continue

            self.stdout.write(f'  Seeding fulfillment data for {tenant.name}…')
            cyc = pos * 5  # cycle so indices never run out
            today = timezone.localdate()
            count = 0

            # A. Draft ASN (not advised) — half of each line.
            self._make_shipment(
                tenant, admin, cyc[0], carrier='', tracking='',
                ship_in=-1, eta_in=6, fraction=Decimal('0.5'))
            count += 1

            # B. Advised + carrier-synced (in transit / out for delivery).
            s = self._make_shipment(
                tenant, admin, cyc[1], carrier='Swift Freight', tracking='SWFT100',
                ship_in=-2, eta_in=2, fraction=Decimal('0.5'))
            self._safe(s, lambda: advise_shipment(s, admin))
            self._safe(s, lambda: sync_tracking(s, admin))
            count += 1

            # C. Delivered + received (posts receipts back into the PO).
            s = self._make_shipment(
                tenant, admin, cyc[2], carrier='Swift Freight', tracking='SWFT200',
                ship_in=-4, eta_in=-1, fraction=Decimal('1'))
            self._safe(s, lambda: advise_shipment(s, admin))
            self._safe(s, lambda: sync_tracking(s, admin))
            self._safe(s, lambda: confirm_delivery(
                s, admin, condition='good', post_receipt=True,
                note='Delivered in full; signed for at the dock.'))
            count += 1

            # D. Split delivery: one PO fulfilled across two shipments + a backorder.
            po_split = cyc[3]
            s1 = self._make_shipment(
                tenant, admin, po_split, carrier='Swift Freight', tracking='SWFT300',
                ship_in=-3, eta_in=-1, fraction=Decimal('0.4'))
            self._safe(s1, lambda: advise_shipment(s1, admin))
            self._safe(s1, lambda: sync_tracking(s1, admin))
            self._safe(s1, lambda: confirm_delivery(
                s1, admin, condition='good', post_receipt=True,
                note='First split delivery received.'))
            s2 = self._make_shipment(
                tenant, admin, po_split, carrier='Swift Freight', tracking='SWFT301',
                ship_in=-1, eta_in=4, fraction=Decimal('0.3'))
            self._safe(s2, lambda: advise_shipment(s2, admin))
            self._safe(s2, lambda: sync_tracking(s2, admin))
            self._open_backorder_remaining(tenant, admin, po_split, today)
            count += 2

            # E. Overdue advised shipment (past ETA, not delivered) → alert sweep.
            s = self._make_shipment(
                tenant, admin, cyc[4], carrier='Slow Freight', tracking='SLOW400',
                ship_in=-8, eta_in=-3, fraction=Decimal('0.25'))
            self._safe(s, lambda: advise_shipment(s, admin))
            count += 1

            self.stdout.write(self.style.SUCCESS(
                f'    {tenant.name}: {count} shipments seeded (draft ASN, in-transit, '
                'delivered+received, split delivery + backorder, overdue).'))

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('\n=== Fulfillment seeding complete ==='))
        self.stdout.write(
            '\nLogin as a tenant admin (e.g. admin_acme / Welcome@123) to see the data.\n'
            'WARNING: Django superuser "admin" has no tenant — data will not appear there.\n'
        )

    # ----- helpers -----

    def _make_shipment(self, tenant, admin, po, *, carrier, tracking, ship_in, eta_in,
                       fraction):
        """Create a shipment against ``po`` and add lines shipping ``fraction`` of each
        PO line's still-shippable, still-outstanding quantity (never over-shipping)."""
        today = timezone.localdate()
        shipment = create_shipment(
            tenant=tenant, user=admin, purchase_order=po,
            carrier=carrier, carrier_code=('mock' if tracking else ''),
            service_level='Ground', tracking_number=tracking,
            ship_date=today + timedelta(days=ship_in),
            estimated_delivery_date=today + timedelta(days=eta_in),
            package_count=2, total_weight=Decimal('12.50'), weight_uom='kg',
            packing_slip_number=f'PS-{po.po_number}',
            freight_cost=Decimal('45.00'),
        )
        for pol in po.lines.exclude(delivery_status='cancelled').order_by('line_no'):
            cap = min(remaining_to_ship_line(pol), pol.outstanding_quantity)
            if cap <= 0:
                continue
            if fraction >= 1:
                qty = cap
            else:
                qty = (cap * fraction).quantize(Decimal('0.01'))
            if qty <= 0:
                continue
            qty = min(qty, cap)
            self._safe(shipment, lambda p=pol, q=qty: add_shipment_line(
                shipment, purchase_order_line=p, shipped_quantity=q))
        shipment.refresh_from_db()
        return shipment

    def _open_backorder_remaining(self, tenant, admin, po, today):
        """Open a single backorder for the first PO line still short of fulfilment."""
        po.refresh_from_db()
        for pol in po.lines.exclude(delivery_status='cancelled').order_by('line_no'):
            rem = remaining_to_ship_line(pol)
            if rem > 0:
                self._safe(None, lambda p=pol, r=rem: open_backorder(
                    tenant=tenant, user=admin, purchase_order_line=p, quantity=r,
                    expected_date=today + timedelta(days=12),
                    reason='Awaiting supplier restock.'))
                break

    def _safe(self, obj, fn):
        """Run a step, swallow ValidationError so seeding never aborts, and refresh
        ``obj`` so the next chained step sees the new state (services re-fetch
        internally and don't mutate the passed instance)."""
        try:
            fn()
        except ValidationError:
            pass
        if obj is not None:
            try:
                obj.refresh_from_db()
            except obj.__class__.DoesNotExist:
                pass
