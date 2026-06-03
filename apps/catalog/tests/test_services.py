"""Service tests for Module 10: permissions, item lifecycle, price resolution,
price-change application, punch-out (loopback) and the supplier upload parser."""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import RequestFactory

from apps.catalog import services
from apps.catalog.models import (
    CatalogItem,
    CatalogPriceChangeRequest,
    CatalogPriceTier,
    SupplierCatalogUpload,
)
from apps.core.models import set_current_tenant

pytestmark = pytest.mark.django_db


class TestPermissions:
    def test_manage_roles(self, tenant_admin, buyer_user, procurement_manager,
                          approver, requester):
        assert services.can_manage_catalog(tenant_admin)
        assert services.can_manage_catalog(buyer_user)
        assert services.can_manage_catalog(procurement_manager)
        assert not services.can_manage_catalog(approver)
        assert not services.can_manage_catalog(requester)

    def test_view_roles(self, approver, requester):
        assert services.can_view_catalog(approver)
        assert not services.can_view_catalog(requester)

    def test_item_visible_to_vendor(self, approved_item, vendor_portal_user,
                                    vendor_b_portal_user):
        assert services.catalog_item_visible_to(vendor_portal_user, approved_item)
        assert not services.catalog_item_visible_to(vendor_b_portal_user, approved_item)


class TestItemLifecycle:
    def test_submit_requires_name(self, tenant, tenant_admin):
        set_current_tenant(tenant)
        item = services.create_item(tenant=tenant, user=tenant_admin, name='',
                                    base_price=Decimal('1'))
        with pytest.raises(ValidationError):
            services.submit_item_for_approval(item, tenant_admin)

    def test_submit_supplier_requires_vendor(self, tenant, tenant_admin):
        set_current_tenant(tenant)
        item = services.create_item(tenant=tenant, user=tenant_admin, name='X',
                                    source='supplier', base_price=Decimal('1'))
        with pytest.raises(ValidationError):
            services.submit_item_for_approval(item, tenant_admin)

    def test_approve_flow(self, pending_item, tenant_admin):
        services.approve_item(pending_item, tenant_admin)
        pending_item.refresh_from_db()
        assert pending_item.status == 'approved' and pending_item.approved_at

    def test_reject_returns_to_editable(self, pending_item, tenant_admin):
        services.reject_item(pending_item, tenant_admin, 'no cert')
        pending_item.refresh_from_db()
        assert pending_item.status == 'rejected' and pending_item.is_editable

    def test_retire_requires_approved(self, draft_item, tenant_admin):
        with pytest.raises(ValidationError):
            services.retire_item(draft_item, tenant_admin)

    def test_retire_approved(self, approved_item, tenant_admin):
        services.retire_item(approved_item, tenant_admin, 'EOL')
        approved_item.refresh_from_db()
        assert approved_item.status == 'retired'


class TestPriceChange:
    def test_apply_sets_new_base(self, pending_price_change, tenant_admin):
        item = pending_price_change.item
        services.apply_price_change(pending_price_change, tenant_admin)
        item.refresh_from_db()
        pending_price_change.refresh_from_db()
        assert item.base_price == Decimal('13.2500')
        assert pending_price_change.status == 'approved'
        assert pending_price_change.prev_base_price == Decimal('12.5000')

    def test_cannot_apply_twice(self, pending_price_change, tenant_admin):
        services.apply_price_change(pending_price_change, tenant_admin)
        with pytest.raises(ValidationError):
            services.apply_price_change(pending_price_change, tenant_admin)

    def test_reject(self, pending_price_change, tenant_admin):
        services.reject_price_change(pending_price_change, tenant_admin, 'no')
        pending_price_change.refresh_from_db()
        assert pending_price_change.status == 'rejected'


class TestPunchout:
    def _post(self, token, **data):
        rf = RequestFactory()
        return rf.post(f'/catalog/punchout/return/{token}/', data)

    def test_start_creates_session(self, tenant, tenant_admin, punchout_config):
        set_current_tenant(tenant)
        session = services.start_punchout(
            punchout_config, tenant_admin,
            build_return_url=lambda tok: f'https://buyer.test/return/{tok}/')
        assert session.return_token and session.buyer_cookie
        assert session.status in ('initiated', 'redirected')

    def test_receive_parses_cart(self, tenant, open_session):
        set_current_tenant(tenant)
        req = self._post(open_session.return_token, shared_secret='s3cr3t',
                         item_name='Bulk Widget', item_qty='5', item_price='3.50',
                         item_sku='W-1', item_uom='box')
        services.receive_punchout_order(req, open_session)
        open_session.refresh_from_db()
        assert open_session.status == 'returned'
        assert open_session.cart_data[0]['name'] == 'Bulk Widget'
        assert open_session.cart_data[0]['unit_price'] == '3.5000'

    def test_receive_rejects_wrong_secret(self, tenant, open_session):
        set_current_tenant(tenant)
        req = self._post(open_session.return_token, shared_secret='WRONG',
                         item_name='X', item_qty='1', item_price='1')
        with pytest.raises(ValidationError):
            services.receive_punchout_order(req, open_session)
        open_session.refresh_from_db()
        assert open_session.status != 'returned'

    def test_cart_to_staged_items(self, tenant, tenant_admin, returned_session):
        set_current_tenant(tenant)
        items = services.cart_to_staged_items(returned_session, tenant_admin)
        assert len(items) == 1
        assert items[0].source == 'supplier' and items[0].status == 'draft'
        assert items[0].vendor_id == returned_session.vendor_id

    def test_cart_to_requisition_lines(self, tenant, tenant_admin, returned_session):
        set_current_tenant(tenant)
        from apps.requisitions.models import Requisition
        req = Requisition.all_objects.create(
            tenant=tenant, requested_by=tenant_admin, number='REQ-ACME-90001',
            title='PunchOut cart', status='draft')
        count = services.cart_to_requisition_lines(returned_session, req, tenant_admin)
        assert count == 1 and req.lines.count() == 1


class TestUploadParser:
    def test_validate_row_rejects_bad_price(self, tenant, vendor_a):
        cleaned, errors = services.validate_catalog_row(
            {'name': 'X', 'base_price': 'abc'}, tenant, vendor_a)
        assert cleaned is None and any(e['field'] == 'base_price' for e in errors)

    def test_process_imports_valid_rows(self, tenant, tenant_admin, catalog_upload):
        set_current_tenant(tenant)
        services.process_catalog_upload(catalog_upload, tenant_admin)
        catalog_upload.refresh_from_db()
        assert catalog_upload.status == 'imported'
        assert catalog_upload.imported_count == 2
        assert CatalogItem.all_objects.filter(
            source_upload=catalog_upload, source='supplier').count() == 2

    def test_process_partial_with_bad_row(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        upload = SupplierCatalogUpload.all_objects.create(
            tenant=tenant, vendor=vendor_a, uploaded_by=tenant_admin,
            file=ContentFile(b'name,base_price\nGood,1.00\n,bad\n', name='c.csv'),
            original_filename='c.csv')
        services.process_catalog_upload(upload, tenant_admin)
        upload.refresh_from_db()
        assert upload.status == 'partially_imported'
        assert upload.imported_count == 1 and upload.error_count >= 1


class TestAnalytics:
    def test_tenant_metrics(self, approved_item, pending_item):
        m = services.tenant_catalog_metrics(approved_item.tenant)
        assert m['total_items'] >= 2
        assert m['approved'] >= 1 and m['pending_approval'] >= 1
        assert m['active_tiers'] >= 2

    def test_item_analytics(self, approved_item):
        a = services.catalog_item_analytics(approved_item)
        assert a['tier_count'] == 2 and a['is_orderable'] is True
