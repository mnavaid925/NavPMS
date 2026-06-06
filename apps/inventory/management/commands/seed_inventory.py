"""Seed Module 19 demo data: a warehouse + bins, stock items, on-hand balances, goods issues,
cycle counts and an auto-reorder, per tenant.

Runs after seed_catalog / seed_goods_receipt in the orchestrator so it can pull real on-hand stock
out of the already-posted goods receipts (``sync_stock_from_receipts``) and also seeds opening
balances so the demo always has stock to issue and count regardless of SKU matching. Idempotent:
skips a tenant that already has inventory data unless ``--flush`` is passed. All work flows through
the real services, so the seeded ledger / averages / variances are exactly what the app produces.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import CatalogItem
from apps.core.models import Tenant, set_current_tenant
from apps.requisitions.models import Requisition

from apps.inventory import services
from apps.inventory.models import (
    CycleCount, CycleCountLine, CycleCountStatusEvent, GoodsIssue, GoodsIssueLine,
    GoodsIssueStatusEvent, StockItem, StockLevel, StockMovement, Warehouse, WarehouseLocation,
)

LOCATIONS = [
    ('A-01-01', 'A', '01', '01'),
    ('A-01-02', 'A', '01', '02'),
    ('B-02-01', 'B', '02', '01'),
    ('B-02-02', 'B', '02', '02'),
]


class Command(BaseCommand):
    help = 'Seed Module 19 demo data (warehouse + bins, stock items, on-hand, goods issues, ' \
           'cycle counts, an auto-reorder) per tenant.'

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

            if StockItem.all_objects.filter(tenant=tenant).exists() and not flush:
                self.stdout.write(
                    f'  {tenant.name}: inventory data already exists — skipped (use --flush).')
                continue

            owner = next(
                (u for u in User.objects.filter(tenant=tenant, is_active=True) if u.is_tenant_admin),
                User.objects.filter(tenant=tenant, is_active=True).first())

            # 1. Warehouse + bins.
            wh = services.ensure_default_warehouse(tenant)
            locations = []
            for code, aisle, rack, shelf in LOCATIONS:
                loc, _ = WarehouseLocation.all_objects.get_or_create(
                    tenant=tenant, warehouse=wh, code=code,
                    defaults={'aisle': aisle, 'rack': rack, 'shelf': shelf})
                locations.append(loc)

            # 2. Stock items for the tenant's live (non-rejected/retired) catalog items.
            catalog_items = list(CatalogItem.all_objects.filter(tenant=tenant, is_active=True)
                                 .exclude(status__in=['rejected', 'retired', 'archived'])
                                 .order_by('id'))
            if not catalog_items:
                self.stdout.write(
                    f'  {tenant.name}: no catalog items — run seed_catalog first; skipped.')
                continue
            stock_items = [services.get_or_create_stock_item(tenant, ci) for ci in catalog_items]

            def at(i):
                return stock_items[i % len(stock_items)]

            # Reorder parameters on the first few items.
            for si in stock_items[:3]:
                si.reorder_point = Decimal('20.00')
                si.reorder_quantity = Decimal('50.00')
                si.safety_stock = Decimal('10.00')
                si.lead_time_days = 7
                si.abc_class = 'A'
                si.default_warehouse = wh
                si.default_location = locations[0]
                si.save()

            # 3. Pull whatever the posted GRNs can give us (best effort, SKU-matched).
            synced = services.sync_stock_from_receipts(tenant, actor=owner)

            # 4. Opening balances so the demo always has stock to work with. The first two items get
            # plain (no-lot) stock so simple goods issues match; the rest carry a lot + expiry to
            # show traceability (item index 2 expires soon, to populate the near-expiry alert).
            today = timezone.localdate()
            for idx, si in enumerate(stock_items[:5]):
                if idx < 2:
                    lot, expiry = '', None
                elif idx == 2:
                    lot, expiry = f'LOT-{idx + 1:03d}', today + timedelta(days=20)
                else:
                    lot, expiry = f'LOT-{idx + 1:03d}', today + timedelta(days=120 + idx * 30)
                services.apply_movement(
                    tenant=tenant, stock_item=si, warehouse=wh,
                    location=locations[idx % len(locations)], movement_type='adjustment',
                    quantity=Decimal('100.00'),
                    unit_cost=(si.catalog_item.base_price or Decimal('5.0000')),
                    lot_number=lot, expiry_date=expiry, actor=owner, reason='Opening balance')

            # 5. Goods issues — posted consumption + draft pick + posted return-to-stock.
            gi = services.create_goods_issue(
                tenant, warehouse=wh, issue_type='consumption', user=owner,
                purpose='Production line consumption', department='Operations')
            services.add_goods_issue_line(
                gi, stock_item=at(0), quantity=Decimal('10.00'), location=locations[0])
            services.post_goods_issue(gi, owner)

            gi_draft = services.create_goods_issue(
                tenant, warehouse=wh, issue_type='consumption', user=owner,
                purpose='Pending office-supplies pick')
            services.add_goods_issue_line(
                gi_draft, stock_item=at(1), quantity=Decimal('5.00'),
                location=locations[1 % len(locations)])

            gi_ret = services.create_goods_issue(
                tenant, warehouse=wh, issue_type='return_to_stock', user=owner,
                purpose='Unused materials returned')
            services.add_goods_issue_line(
                gi_ret, stock_item=at(2), quantity=Decimal('4.00'),
                location=locations[2 % len(locations)])
            services.post_goods_issue(gi_ret, owner)

            # 6. Cycle counts — one posted with a variance + one left in-progress.
            cc = services.create_cycle_count(
                tenant, warehouse=wh, scope='full', user=owner, note='Quarterly full count')
            first_line = cc.lines.first()
            if first_line:
                services.set_cycle_count_line(
                    first_line, (first_line.system_quantity or Decimal('0')) - Decimal('3.00'))
            services.post_cycle_count(cc, owner)

            cc2 = services.create_cycle_count(
                tenant, warehouse=wh, scope='full', user=owner, note='In-progress spot count')
            l2 = cc2.lines.first()
            if l2:
                services.set_cycle_count_line(l2, l2.system_quantity or Decimal('0'))

            # 7. Force one item below its reorder point and run the automation -> draft requisition.
            reorder_item = at(3)
            reorder_item.is_stocked = True
            reorder_item.reorder_point = reorder_item.available_quantity + Decimal('25.00')
            reorder_item.reorder_quantity = Decimal('40.00')
            reorder_item.default_warehouse = wh
            reorder_item.save()
            reorders = services.run_reorder_automation(tenant, actor=owner)

            self.stdout.write(
                f'  {tenant.name}: {len(stock_items)} stock item(s), {synced["received"]} '
                f'receipt(s) synced, 3 goods issue(s), 2 cycle count(s), {reorders} reorder(s).')

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('Inventory & warehouse seeded.'))
        self.stdout.write(
            'Log in as a tenant admin (e.g. admin_acme / Welcome@123) and open /inventory/ — '
            'the superuser "admin" has no tenant and sees no data.')

    def _flush(self, tenant):
        # Child -> parent so PROTECT FKs never block the wipe.
        StockMovement.all_objects.filter(tenant=tenant).delete()
        CycleCountStatusEvent.all_objects.filter(tenant=tenant).delete()
        CycleCountLine.all_objects.filter(tenant=tenant).delete()
        CycleCount.all_objects.filter(tenant=tenant).delete()
        GoodsIssueStatusEvent.all_objects.filter(tenant=tenant).delete()
        GoodsIssueLine.all_objects.filter(tenant=tenant).delete()
        GoodsIssue.all_objects.filter(tenant=tenant).delete()
        StockLevel.all_objects.filter(tenant=tenant).delete()
        StockItem.all_objects.filter(tenant=tenant).delete()
        WarehouseLocation.all_objects.filter(tenant=tenant).delete()
        Warehouse.all_objects.filter(tenant=tenant).delete()
        # Remove only the auto-reorder requisitions this seeder generated.
        Requisition.all_objects.filter(tenant=tenant, title__startswith='Auto-reorder:').delete()
