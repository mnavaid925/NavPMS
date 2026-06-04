"""Seed Module 13 demo data: goods receipts (GRNs) across every status, a QA inspection
checklist, accepted quantities posted back into the PO, a mixed accept/reject GRN that
spawns a Return-to-Vendor, barcode tags for accepted inventory, and a received-but-not-yet
-inspected GRN (back-dated) to light up the overdue-inspection alert sweep. Driven through
the real goods_receipt services so the timelines, postings and RTVs are produced exactly
as in production.

Runs AFTER ``seed_fulfillment`` — it receives against the dispatched, still-open POs.
Idempotent: skips a tenant that already has goods receipts unless ``--flush`` is passed.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.purchase_orders.models import PO_CHANGE_ORDERABLE_STATUSES, PurchaseOrder

from apps.goods_receipt.models import GoodsReceipt, ReturnToVendor
from apps.goods_receipt.services import (
    add_receipt_line,
    authorize_rtv,
    create_goods_receipt,
    create_rtv_from_rejections,
    mark_received,
    post_goods_receipt,
    record_inspection,
    ship_rtv,
)

_QA_PASS = [{'criterion': k, 'result': 'pass'} for k, _ in [
    ('packaging_intact', ''), ('quantity_matches', ''), ('no_damage', ''),
    ('labelling_correct', ''), ('documentation_present', ''),
]]
_QA_FAIL = [
    {'criterion': 'packaging_intact', 'result': 'fail', 'note': 'Crushed corner'},
    {'criterion': 'quantity_matches', 'result': 'pass'},
    {'criterion': 'no_damage', 'result': 'fail', 'note': 'Water damage'},
    {'criterion': 'labelling_correct', 'result': 'pass'},
    {'criterion': 'documentation_present', 'result': 'na'},
]


class Command(BaseCommand):
    help = ('Seed Module 13 demo data (goods receipts across every status + inspection + '
            'posting + returns to vendor + tags).')

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
                ReturnToVendor.all_objects.filter(tenant=tenant).delete()
                GoodsReceipt.all_objects.filter(tenant=tenant).delete()

            if GoodsReceipt.all_objects.filter(tenant=tenant).exists() and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: goods-receipt data already exists — skipped '
                    '(use --flush to re-seed).')
                continue

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            admin = next((u for u in users if u.is_tenant_admin), users[0] if users else None)
            if not admin:
                self.stdout.write(f'    {tenant.name}: no admin user — skipped.')
                continue

            pos = [
                po for po in PurchaseOrder.all_objects.filter(
                    tenant=tenant, status__in=PO_CHANGE_ORDERABLE_STATUSES,
                ).order_by('po_number')
                if any(l.outstanding_quantity > 0 for l in po.lines.exclude(
                    delivery_status='cancelled'))
            ]
            if not pos:
                self.stdout.write(
                    f'    {tenant.name}: no open purchase orders with outstanding lines — '
                    'skipped. Run seed_purchase_orders first.')
                continue

            self.stdout.write(f'  Seeding goods-receipt data for {tenant.name}…')
            cyc = pos * 5  # cycle so indices never run out
            today = timezone.localdate()
            count = 0

            # A. Draft GRN (lines added, not yet received).
            grn = self._make_grn(tenant, admin, cyc[0], 'DN-A', fraction=Decimal('0.5'))
            if grn:
                count += 1

            # B. Received but not inspected — back-dated to trigger the alert sweep.
            grn = self._make_grn(tenant, admin, cyc[1], 'DN-B', fraction=Decimal('0.5'))
            if grn:
                self._safe(grn, lambda g=grn: mark_received(g, admin))
                GoodsReceipt.all_objects.filter(pk=grn.pk).update(
                    received_at=timezone.now() - timedelta(days=5))
                count += 1

            # C. Received -> inspected (all accepted, QA pass) -> posted (+ tags).
            grn = self._make_grn(tenant, admin, cyc[2], 'DN-C', fraction=Decimal('0.5'))
            if grn:
                self._safe(grn, lambda g=grn: mark_received(g, admin))
                self._inspect(grn, admin, accept_frac=Decimal('1'), checks=_QA_PASS)
                self._safe(grn, lambda g=grn: post_goods_receipt(g, admin))
                count += 1

            # D. Mixed accept/reject -> posted -> Return to Vendor (authorised + shipped).
            grn = self._make_grn(tenant, admin, cyc[3], 'DN-D', fraction=Decimal('0.5'))
            if grn:
                self._safe(grn, lambda g=grn: mark_received(g, admin))
                self._inspect(grn, admin, accept_frac=Decimal('0.5'), checks=_QA_PASS,
                              discrepancy='damaged', reason='Damaged in transit')
                self._safe(grn, lambda g=grn: post_goods_receipt(g, admin))
                rtv = self._safe_ret(lambda g=grn: create_rtv_from_rejections(
                    g, admin, reason='Damaged on arrival — returning for replacement.'))
                if rtv:
                    self._safe(rtv, lambda r=rtv: authorize_rtv(r, admin))
                    self._safe(rtv, lambda r=rtv: ship_rtv(
                        r, admin, carrier='Return Logistics', tracking_number='RMA-100'))
                count += 1

            # E. Inspected with a QA failure, left un-posted (awaiting decision).
            grn = self._make_grn(tenant, admin, cyc[4], 'DN-E', fraction=Decimal('0.25'))
            if grn:
                self._safe(grn, lambda g=grn: mark_received(g, admin))
                self._inspect(grn, admin, accept_frac=Decimal('0'), checks=_QA_FAIL,
                              discrepancy='quality', reason='Failed QA inspection')
                count += 1

            self.stdout.write(self.style.SUCCESS(
                f'    {tenant.name}: {count} goods receipts seeded (draft, awaiting '
                'inspection, posted, mixed+RTV, QA-fail).'))

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('\n=== Goods-receipt seeding complete ==='))
        self.stdout.write(
            '\nLogin as a tenant admin (e.g. admin_acme / Welcome@123) to see the data.\n'
            'WARNING: Django superuser "admin" has no tenant — data will not appear there.\n')

    # ----- helpers -----

    def _make_grn(self, tenant, admin, po, dn_ref, *, fraction):
        """Create a GRN against ``po`` and add a line per still-outstanding PO line,
        receiving ``fraction`` of the outstanding quantity (never exceeding it)."""
        grn = self._safe_ret(lambda: create_goods_receipt(
            tenant=tenant, user=admin, purchase_order=po,
            received_date=timezone.localdate(), delivery_note_ref=dn_ref,
            warehouse_location='Main warehouse'))
        if not grn:
            return None
        for pol in po.lines.exclude(delivery_status='cancelled').order_by('line_no'):
            outstanding = pol.outstanding_quantity
            if outstanding <= 0:
                continue
            qty = (outstanding * fraction).quantize(Decimal('0.01'))
            if qty <= 0:
                qty = min(outstanding, Decimal('1.00'))
            qty = min(qty, outstanding)
            self._safe(grn, lambda p=pol, q=qty: add_receipt_line(
                grn, purchase_order_line=p, received_quantity=q))
        grn.refresh_from_db()
        return grn

    def _inspect(self, grn, admin, *, accept_frac, checks, discrepancy='none', reason=''):
        """Inspect every received line, accepting ``accept_frac`` and rejecting the rest."""
        grn.refresh_from_db()
        line_results = {}
        for line in grn.lines.all():
            received = line.received_quantity or Decimal('0')
            accepted = (received * accept_frac).quantize(Decimal('0.01'))
            accepted = min(accepted, received)
            rejected = received - accepted
            line_results[line.id] = {
                'accepted': accepted, 'rejected': rejected,
                'discrepancy': discrepancy if rejected > 0 else 'none',
                'reason': reason if rejected > 0 else '',
            }
        self._safe(grn, lambda: record_inspection(
            grn, admin, checks=checks, line_results=line_results,
            note='Seed inspection'))

    def _safe(self, obj, fn):
        """Run a step, swallow ValidationError so seeding never aborts, and refresh
        ``obj`` so the next chained step sees the new state."""
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
        """Run a step that returns an object; swallow ValidationError -> None."""
        try:
            return fn()
        except ValidationError:
            return None
