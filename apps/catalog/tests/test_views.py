"""View tests for Module 10: list/filter/search, CRUD, lifecycle POSTs, tiers,
price-change apply, categories, punch-out, uploads, analytics and role gates."""
import pytest
from django.test import override_settings
from django.urls import reverse

from apps.catalog.models import (
    CatalogCategory,
    CatalogItem,
    CatalogPriceTier,
    SupplierPunchoutConfig,
)

pytestmark = pytest.mark.django_db


def _item_post(**over):
    data = {
        'name': 'New Item', 'source': 'internal', 'uom': 'each',
        'currency': 'USD', 'base_price': '10.00', 'min_order_qty': '1',
        'lead_time_days': '0',
    }
    data.update(over)
    return data


class TestList:
    def test_list_200(self, client, buyer_user, draft_item):
        client.force_login(buyer_user)
        resp = client.get(reverse('catalog:item_list'))
        assert resp.status_code == 200
        assert draft_item.item_number.encode() in resp.content

    def test_status_filter(self, client, buyer_user, draft_item, approved_item):
        client.force_login(buyer_user)
        resp = client.get(reverse('catalog:item_list'), {'status': 'approved'})
        assert approved_item.item_number.encode() in resp.content
        assert draft_item.item_number.encode() not in resp.content

    def test_search(self, client, buyer_user, approved_item):
        client.force_login(buyer_user)
        resp = client.get(reverse('catalog:item_list'), {'q': 'Cable'})
        assert approved_item.item_number.encode() in resp.content


class TestCreateEditDelete:
    def test_create_get(self, client, buyer_user):
        client.force_login(buyer_user)
        assert client.get(reverse('catalog:item_create')).status_code == 200

    def test_create_post(self, client, buyer_user, tenant):
        client.force_login(buyer_user)
        before = CatalogItem.all_objects.filter(tenant=tenant).count()
        resp = client.post(reverse('catalog:item_create'), _item_post())
        assert resp.status_code == 302
        assert CatalogItem.all_objects.filter(tenant=tenant).count() == before + 1

    def test_edit_draft(self, client, buyer_user, draft_item):
        client.force_login(buyer_user)
        resp = client.post(reverse('catalog:item_edit', kwargs={'pk': draft_item.pk}),
                           _item_post(name='Renamed'))
        assert resp.status_code == 302
        draft_item.refresh_from_db()
        assert draft_item.name == 'Renamed'

    def test_cannot_edit_approved(self, client, buyer_user, approved_item):
        client.force_login(buyer_user)
        resp = client.get(reverse('catalog:item_edit', kwargs={'pk': approved_item.pk}))
        assert resp.status_code == 302

    def test_delete_draft(self, client, buyer_user, draft_item):
        client.force_login(buyer_user)
        resp = client.post(reverse('catalog:item_delete', kwargs={'pk': draft_item.pk}))
        assert resp.status_code == 302
        assert not CatalogItem.all_objects.filter(pk=draft_item.pk).exists()


class TestLifecycle:
    def test_submit_and_approve(self, client, buyer_user, draft_item):
        client.force_login(buyer_user)
        client.post(reverse('catalog:item_submit', kwargs={'pk': draft_item.pk}))
        draft_item.refresh_from_db()
        assert draft_item.status == 'pending_approval'
        client.post(reverse('catalog:item_approve', kwargs={'pk': draft_item.pk}))
        draft_item.refresh_from_db()
        assert draft_item.status == 'approved'

    def test_reject(self, client, buyer_user, pending_item):
        client.force_login(buyer_user)
        resp = client.post(reverse('catalog:item_reject', kwargs={'pk': pending_item.pk}),
                           {'reason': 'missing cert'})
        assert resp.status_code == 302
        pending_item.refresh_from_db()
        assert pending_item.status == 'rejected'


class TestTiers:
    def test_add_tier_draft(self, client, buyer_user, draft_item):
        client.force_login(buyer_user)
        resp = client.post(reverse('catalog:tier_add', kwargs={'pk': draft_item.pk}), {
            'tier_type': 'volume', 'min_quantity': '10', 'unit_price': '5.00',
            'is_active': 'on'})
        assert resp.status_code == 302
        assert CatalogPriceTier.all_objects.filter(item=draft_item).count() == 1

    def test_cannot_add_tier_to_approved(self, client, buyer_user, approved_item):
        client.force_login(buyer_user)
        resp = client.get(reverse('catalog:tier_add', kwargs={'pk': approved_item.pk}))
        assert resp.status_code == 302


class TestPriceChange:
    def test_apply_via_view(self, client, buyer_user, pending_price_change):
        client.force_login(buyer_user)
        item = pending_price_change.item
        resp = client.post(reverse('catalog:price_change_apply',
                                   kwargs={'pk': item.pk, 'pc_pk': pending_price_change.pk}))
        assert resp.status_code == 302
        item.refresh_from_db()
        assert item.base_price == pending_price_change.new_base_price


class TestCategories:
    def test_list_and_create(self, client, buyer_user, tenant):
        client.force_login(buyer_user)
        assert client.get(reverse('catalog:category_list')).status_code == 200
        resp = client.post(reverse('catalog:category_create'),
                           {'code': 'NEW', 'name': 'New Cat', 'is_active': 'on'})
        assert resp.status_code == 302
        assert CatalogCategory.all_objects.filter(tenant=tenant, code='NEW').exists()


class TestPunchout:
    @override_settings(PUNCHOUT_SSRF_ALLOWLIST='supplier.example.com')
    def test_config_create(self, client, buyer_user, tenant, vendor_a):
        client.force_login(buyer_user)
        resp = client.post(reverse('catalog:punchout_config_create'), {
            'vendor': vendor_a.pk, 'name': 'PO', 'protocol': 'cxml',
            'setup_url': 'https://supplier.example.com/po', 'shared_secret': 's',
            'extra_params': '{}', 'is_active': 'on'})
        assert resp.status_code == 302
        assert SupplierPunchoutConfig.all_objects.filter(tenant=tenant).count() == 1

    def test_session_detail_200(self, client, buyer_user, returned_session):
        client.force_login(buyer_user)
        resp = client.get(reverse('catalog:punchout_session_detail',
                                  kwargs={'pk': returned_session.pk}))
        assert resp.status_code == 200

    def test_return_loopback_success(self, client, open_session):
        resp = client.post(
            reverse('catalog:punchout_return', kwargs={'token': open_session.return_token}),
            {'shared_secret': 's3cr3t', 'item_name': 'Widget', 'item_qty': '3',
             'item_price': '2.50'})
        assert resp.status_code == 200
        open_session.refresh_from_db()
        assert open_session.status == 'returned'


class TestUploads:
    def test_list_and_process(self, client, buyer_user, catalog_upload):
        client.force_login(buyer_user)
        assert client.get(reverse('catalog:upload_list')).status_code == 200
        resp = client.post(reverse('catalog:upload_process', kwargs={'pk': catalog_upload.pk}))
        assert resp.status_code == 302
        catalog_upload.refresh_from_db()
        assert catalog_upload.status == 'imported'


class TestBoardsAnalytics:
    def test_approval_board(self, client, buyer_user, pending_item):
        client.force_login(buyer_user)
        assert client.get(reverse('catalog:approval_board')).status_code == 200

    def test_analytics(self, client, buyer_user, approved_item):
        client.force_login(buyer_user)
        assert client.get(reverse('catalog:analytics_dashboard')).status_code == 200
        assert client.get(reverse('catalog:item_analytics',
                                  kwargs={'pk': approved_item.pk})).status_code == 200


class TestRenders:
    """Render the pages not exercised elsewhere (catches template runtime errors)."""

    def test_item_detail(self, client, buyer_user, approved_item):
        client.force_login(buyer_user)
        assert client.get(reverse('catalog:item_detail',
                                  kwargs={'pk': approved_item.pk})).status_code == 200

    def test_price_change_detail(self, client, buyer_user, pending_price_change):
        client.force_login(buyer_user)
        url = reverse('catalog:price_change_detail',
                      kwargs={'pk': pending_price_change.item.pk,
                              'pc_pk': pending_price_change.pk})
        assert client.get(url).status_code == 200

    def test_upload_detail(self, client, buyer_user, catalog_upload):
        client.force_login(buyer_user)
        assert client.get(reverse('catalog:upload_detail',
                                  kwargs={'pk': catalog_upload.pk})).status_code == 200

    def test_punchout_config_create_get(self, client, buyer_user):
        client.force_login(buyer_user)
        assert client.get(reverse('catalog:punchout_config_create')).status_code == 200

    def test_price_change_create_get(self, client, buyer_user, approved_item):
        client.force_login(buyer_user)
        assert client.get(reverse('catalog:price_change_create',
                                  kwargs={'pk': approved_item.pk})).status_code == 200


class TestVendorPortal:
    def test_portal_catalog_list(self, client, vendor_portal_user, approved_item):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse('vendor_portal:catalog_items'))
        assert resp.status_code == 200
        assert approved_item.item_number.encode() in resp.content

    def test_portal_upload_pages(self, client, vendor_portal_user, catalog_upload):
        client.force_login(vendor_portal_user)
        assert client.get(reverse('vendor_portal:catalog_uploads')).status_code == 200
        assert client.get(reverse('vendor_portal:catalog_upload_create')).status_code == 200
        assert client.get(reverse('vendor_portal:catalog_upload_detail',
                                  kwargs={'pk': catalog_upload.pk})).status_code == 200

    def test_portal_upload_post(self, client, vendor_portal_user, tenant):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.catalog.models import SupplierCatalogUpload
        client.force_login(vendor_portal_user)
        f = SimpleUploadedFile('v.csv', b'name,base_price\nWidget,1.00\n')
        resp = client.post(reverse('vendor_portal:catalog_upload_create'), {'file': f})
        assert resp.status_code == 302
        assert SupplierCatalogUpload.all_objects.filter(tenant=tenant).count() == 1


class TestPermissionGate:
    def test_requester_cannot_create(self, client, requester):
        client.force_login(requester)
        assert client.get(reverse('catalog:item_create')).status_code == 302

    def test_requester_cannot_list(self, client, requester):
        client.force_login(requester)
        assert client.get(reverse('catalog:item_list')).status_code == 302
