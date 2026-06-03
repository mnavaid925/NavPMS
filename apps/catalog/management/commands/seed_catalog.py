"""Seed Module 10 demo data: catalog categories, items across every status
(draft / pending / approved-with-tiers / rejected / retired), a pending
price-change request, a cXML punch-out supplier configuration and a parsed
supplier upload — driven through the real catalog services so the approval
timeline, tiers and staged items are produced exactly as in production."""
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.catalog.models import (
    CatalogCategory,
    CatalogItem,
    CatalogPriceChangeRequest,
    CatalogPriceTier,
    PunchoutSession,
    SupplierCatalogUpload,
    SupplierPunchoutConfig,
)
from apps.catalog.services import (
    approve_item,
    create_item,
    next_price_change_number,
    process_catalog_upload,
    reject_item,
    retire_item,
    submit_item_for_approval,
    submit_price_change,
)
from apps.core.models import Tenant, set_current_tenant
from apps.vendors.models import Vendor

CATEGORIES = [
    ('OFFICE', 'Office Supplies'),
    ('IT', 'IT Equipment'),
    ('MRO', 'Maintenance, Repair & Operations'),
    ('RAW', 'Raw Materials'),
]

SEED_CSV = (
    'name,sku,base_price,uom,min_order_qty,category_code,lead_time_days\n'
    'Nitrile Gloves (box of 100),GLV-100,8.50,box,10,MRO,5\n'
    'Whiteboard Markers (pack of 4),WBM-4,3.20,pack,5,OFFICE,3\n'
    'USB-C Charging Cable 2m,USBC-2M,6.75,each,20,IT,7\n'
    ',BAD-ROW,not-a-price,each,1,OFFICE,2\n'  # one intentionally-bad row
)


class Command(BaseCommand):
    help = 'Seed Module 10 demo data (catalog categories, items, tiers, price-change, punch-out, upload).'

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
                CatalogItem.all_objects.filter(tenant=tenant).delete()
                PunchoutSession.all_objects.filter(tenant=tenant).delete()
                SupplierPunchoutConfig.all_objects.filter(tenant=tenant).delete()
                SupplierCatalogUpload.all_objects.filter(tenant=tenant).delete()
                CatalogCategory.all_objects.filter(tenant=tenant).delete()

            if CatalogItem.all_objects.filter(tenant=tenant).exists() and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: catalog data already exists — skipped '
                    '(use --flush to re-seed).')
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

            self.stdout.write(f'  Seeding catalog data for {tenant.name}…')
            cats = self._ensure_categories(tenant)
            v = (vendors * 3)

            # 1. Draft internal item with volume tiers.
            draft = create_item(
                tenant=tenant, user=admin, name='A4 Copier Paper (ream)',
                source='internal', category=cats['OFFICE'], uom='each',
                base_price=Decimal('4.5000'), min_order_qty=Decimal('5.00'),
                sku='PAP-A4', keywords='paper, a4, copier, ream')
            self._add_tiers(tenant, draft, [(Decimal('50'), Decimal('4.10')),
                                            (Decimal('200'), Decimal('3.80'))])

            # 2. Pending-approval supplier item.
            pending = create_item(
                tenant=tenant, user=admin, name='Industrial Safety Helmet',
                source='supplier', vendor=v[0], category=cats['MRO'], uom='each',
                base_price=Decimal('18.0000'), sku='HEL-IND')
            submit_item_for_approval(pending, admin)

            # 3. Approved supplier item with tiers (the orderable case).
            approved = create_item(
                tenant=tenant, user=admin, name='Heavy-Duty Cable Ties (1000)',
                source='supplier', vendor=v[1], category=cats['MRO'], uom='box',
                base_price=Decimal('12.5000'), min_order_qty=Decimal('1.00'),
                sku='CT-1000')
            self._add_tiers(tenant, approved, [(Decimal('10'), Decimal('11.00')),
                                               (Decimal('50'), Decimal('9.75'))])
            submit_item_for_approval(approved, admin)
            approve_item(approved, admin)

            # 4. Rejected item.
            rejected = create_item(
                tenant=tenant, user=admin, name='Unbranded Power Adapter',
                source='supplier', vendor=v[2], category=cats['IT'], uom='each',
                base_price=Decimal('5.0000'), sku='PWR-X')
            submit_item_for_approval(rejected, admin)
            reject_item(rejected, admin, 'Needs a safety-certification document.')

            # 5. Retired item.
            retired = create_item(
                tenant=tenant, user=admin, name='Legacy Toner Cartridge',
                source='internal', category=cats['IT'], uom='each',
                base_price=Decimal('45.0000'), sku='TON-OLD')
            submit_item_for_approval(retired, admin)
            approve_item(retired, admin)
            retire_item(retired, admin, 'Printer model discontinued.')

            # 6. Pending price-change on an approved item.
            pc = CatalogPriceChangeRequest.all_objects.create(
                tenant=tenant, item=approved,
                request_number=next_price_change_number(approved),
                change_type='base', new_base_price=Decimal('13.2500'),
                reason='Annual supplier price uplift.', status='draft',
                created_by=admin)
            submit_price_change(pc, admin)

            # 7. cXML punch-out supplier configuration.
            SupplierPunchoutConfig.all_objects.create(
                tenant=tenant, vendor=v[0], name=f'{v[0].legal_name} PunchOut',
                protocol='cxml', setup_url='https://punchout.example-supplier.com/cxml',
                from_identity=tenant.slug, to_identity='EXAMPLE-DUNS',
                sender_identity=tenant.slug, shared_secret='demo-shared-secret',
                is_active=True)

            # 8. Supplier upload — parsed and ingested (one bad row → partial import).
            upload = SupplierCatalogUpload.all_objects.create(
                tenant=tenant, vendor=v[1], uploaded_by=admin,
                file=ContentFile(SEED_CSV.encode('utf-8'), name='seed_catalog.csv'),
                original_filename='seed_catalog.csv', category=cats['MRO'])
            process_catalog_upload(upload, admin)

            self.stdout.write(self.style.SUCCESS(
                f'    {tenant.name}: 4 categories, items across every status, a '
                'price-change, a punch-out config and a parsed upload seeded.'))

        self.stdout.write(self.style.SUCCESS('\n=== Catalog seeding complete ==='))
        self.stdout.write(
            '\nLogin as a tenant admin (e.g. admin_acme / Welcome@123) to see the data.\n'
            'WARNING: Django superuser "admin" has no tenant — data will not appear there.\n')

    # ----- helpers -----

    def _ensure_categories(self, tenant):
        cats = {}
        for code, name in CATEGORIES:
            obj = CatalogCategory.all_objects.filter(tenant=tenant, code=code).first()
            if not obj:
                obj = CatalogCategory.all_objects.create(
                    tenant=tenant, code=code, name=name, is_active=True)
            cats[code] = obj
        return cats

    def _add_tiers(self, tenant, item, breaks):
        for min_qty, price in breaks:
            CatalogPriceTier.all_objects.create(
                tenant=tenant, item=item, tier_type='volume',
                min_quantity=min_qty, unit_price=price, is_active=True)
