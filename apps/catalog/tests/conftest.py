"""Shared fixtures for Module 10 (Catalog Management) tests.

Mirrors ``apps/contracts/tests/conftest.py``: tenants & users, vendors, then
catalog fixtures. Every catalog-creating fixture calls ``set_current_tenant``
first and creates its OWN row (we never build ``approved_item`` by mutating
``draft_item`` in place) and uses the real services so the seeded state is honest.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

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
    next_price_change_number,
    submit_item_for_approval,
    submit_price_change,
)
from apps.core.models import Tenant, set_current_tenant
from apps.vendors.models import Vendor


# ---------- Tenants & users ----------

@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name='Acme Co', slug='acme')


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name='Globex', slug='globex')


@pytest.fixture
def tenant_admin(db, tenant):
    return User.objects.create_user(
        username='admin_acme', password='x', tenant=tenant,
        role='tenant_admin', is_tenant_admin=True,
        first_name='Ada', last_name='Admin', email='ada@acme.test')


@pytest.fixture
def buyer_user(db, tenant):
    return User.objects.create_user(
        username='buyer', password='x', tenant=tenant, role='buyer')


@pytest.fixture
def procurement_manager(db, tenant):
    return User.objects.create_user(
        username='pmgr', password='x', tenant=tenant, role='procurement_manager')


@pytest.fixture
def approver(db, tenant):
    return User.objects.create_user(
        username='approver_user', password='x', tenant=tenant, role='approver')


@pytest.fixture
def requester(db, tenant):
    return User.objects.create_user(
        username='requester', password='x', tenant=tenant, role='requester')


@pytest.fixture
def intruder(db, other_tenant):
    return User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant,
        role='tenant_admin', is_tenant_admin=True)


# ---------- Vendors ----------

@pytest.fixture
def vendor_a(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00001',
        legal_name='Acme IT Solutions', status='active', email='a@vend.test')


@pytest.fixture
def vendor_b(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00002',
        legal_name='Beacon Supplies', status='active', email='b@vend.test')


@pytest.fixture
def blocked_vendor(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-09999',
        legal_name='Blocked Co', status='blacklisted')


@pytest.fixture
def vendor_portal_user(db, tenant, vendor_a):
    return User.objects.create_user(
        username='portal_a', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_a)


@pytest.fixture
def vendor_b_portal_user(db, tenant, vendor_b):
    return User.objects.create_user(
        username='portal_b', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_b)


# ---------- Categories ----------

@pytest.fixture
def category(db, tenant):
    set_current_tenant(tenant)
    return CatalogCategory.all_objects.create(
        tenant=tenant, code='OFFICE', name='Office Supplies', is_active=True)


# ---------- Items ----------

def _make_item(tenant, created_by, *, number, status='draft', source='internal',
               vendor=None, base_price=Decimal('10.0000'), name='A4 Copier Paper'):
    return CatalogItem.all_objects.create(
        tenant=tenant, item_number=number, name=name, source=source,
        vendor=vendor, base_price=base_price, currency='USD', uom='each',
        min_order_qty=Decimal('1.00'), status=status, created_by=created_by)


@pytest.fixture
def draft_item(db, tenant, tenant_admin, category):
    set_current_tenant(tenant)
    item = _make_item(tenant, tenant_admin, number='CAT-ACME-00001')
    item.category = category
    item.save(update_fields=['category'])
    return item


@pytest.fixture
def pending_item(db, tenant, tenant_admin, vendor_a):
    set_current_tenant(tenant)
    item = _make_item(tenant, tenant_admin, number='CAT-ACME-00002',
                      source='supplier', vendor=vendor_a, name='Safety Helmet')
    submit_item_for_approval(item, tenant_admin)
    item.refresh_from_db()
    return item


@pytest.fixture
def approved_item(db, tenant, tenant_admin, vendor_a):
    set_current_tenant(tenant)
    item = _make_item(tenant, tenant_admin, number='CAT-ACME-00003',
                      source='supplier', vendor=vendor_a, name='Cable Ties',
                      base_price=Decimal('12.5000'))
    CatalogPriceTier.all_objects.create(
        tenant=tenant, item=item, tier_type='volume',
        min_quantity=Decimal('10'), unit_price=Decimal('11.0000'))
    CatalogPriceTier.all_objects.create(
        tenant=tenant, item=item, tier_type='volume',
        min_quantity=Decimal('50'), unit_price=Decimal('9.7500'))
    submit_item_for_approval(item, tenant_admin)
    approve_item(item, tenant_admin)
    item.refresh_from_db()
    return item


@pytest.fixture
def rejected_item(db, tenant, tenant_admin, vendor_a):
    set_current_tenant(tenant)
    item = _make_item(tenant, tenant_admin, number='CAT-ACME-00004',
                      source='supplier', vendor=vendor_a, status='rejected',
                      name='Rejected Adapter')
    return item


@pytest.fixture
def pending_price_change(db, tenant, tenant_admin, approved_item):
    set_current_tenant(tenant)
    pc = CatalogPriceChangeRequest.all_objects.create(
        tenant=tenant, item=approved_item,
        request_number=next_price_change_number(approved_item),
        change_type='base', new_base_price=Decimal('13.2500'),
        reason='Annual uplift', status='draft', created_by=tenant_admin)
    submit_price_change(pc, tenant_admin)
    pc.refresh_from_db()
    return pc


# ---------- Punch-out ----------

@pytest.fixture
def punchout_config(db, tenant, vendor_a):
    set_current_tenant(tenant)
    return SupplierPunchoutConfig.all_objects.create(
        tenant=tenant, vendor=vendor_a, name='Acme PunchOut', protocol='loopback',
        setup_url='https://supplier.example.com/punchout',
        shared_secret='s3cr3t', is_active=True)


@pytest.fixture
def open_session(db, tenant, tenant_admin, punchout_config, vendor_a):
    set_current_tenant(tenant)
    import secrets
    return PunchoutSession.all_objects.create(
        tenant=tenant, config=punchout_config, vendor=vendor_a,
        buyer_cookie=secrets.token_urlsafe(16),
        return_token=secrets.token_urlsafe(24), started_by=tenant_admin,
        status='redirected', expires_at=timezone.now() + timedelta(hours=1))


@pytest.fixture
def returned_session(db, tenant, tenant_admin, punchout_config, vendor_a):
    set_current_tenant(tenant)
    import secrets
    return PunchoutSession.all_objects.create(
        tenant=tenant, config=punchout_config, vendor=vendor_a,
        buyer_cookie=secrets.token_urlsafe(16),
        return_token=secrets.token_urlsafe(24), started_by=tenant_admin,
        status='returned', returned_at=timezone.now(),
        cart_data=[{'name': 'Bulk Widget', 'sku': 'W-1', 'quantity': '5',
                    'unit_price': '3.5000', 'currency': 'USD', 'uom': 'each'}])


# ---------- Uploads ----------

@pytest.fixture
def catalog_upload(db, tenant, vendor_a, tenant_admin):
    set_current_tenant(tenant)
    from django.core.files.base import ContentFile
    return SupplierCatalogUpload.all_objects.create(
        tenant=tenant, vendor=vendor_a, uploaded_by=tenant_admin,
        file=ContentFile(
            b'name,base_price,uom\nWidget,2.50,each\nGadget,4.00,box\n',
            name='cat.csv'),
        original_filename='cat.csv')
