"""Security tests for Module 10 (OWASP-aligned): cross-tenant IDOR, XSS escaping,
state-machine integrity, access control, file-upload validation and the punch-out
attack surface (SSRF, token auth, shared-secret leakage, XXE, cross-vendor isolation)."""
import secrets
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.catalog import services
from apps.catalog.forms import SupplierCatalogUploadForm
from apps.catalog.models import CatalogItem, PunchoutSession, SupplierPunchoutConfig
from apps.core.models import set_current_tenant

pytestmark = pytest.mark.django_db


class TestCrossTenantIDOR:
    def test_intruder_cannot_view(self, client, intruder, draft_item):
        client.force_login(intruder)
        resp = client.get(reverse('catalog:item_detail', kwargs={'pk': draft_item.pk}))
        assert resp.status_code == 404

    def test_intruder_cannot_edit(self, client, intruder, draft_item):
        client.force_login(intruder)
        resp = client.get(reverse('catalog:item_edit', kwargs={'pk': draft_item.pk}))
        assert resp.status_code == 404

    def test_intruder_cannot_delete(self, client, intruder, draft_item):
        client.force_login(intruder)
        resp = client.post(reverse('catalog:item_delete', kwargs={'pk': draft_item.pk}))
        assert resp.status_code == 404
        assert CatalogItem.all_objects.filter(pk=draft_item.pk).exists()


class TestXSS:
    def test_name_escaped(self, client, buyer_user, tenant, tenant_admin):
        set_current_tenant(tenant)
        CatalogItem.all_objects.create(
            tenant=tenant, item_number='CAT-ACME-0XSS', name='<script>alert(1)</script>',
            base_price=Decimal('1'), created_by=tenant_admin)
        client.force_login(buyer_user)
        resp = client.get(reverse('catalog:item_list'))
        assert resp.status_code == 200
        assert b'<script>alert(1)</script>' not in resp.content
        assert b'&lt;script&gt;' in resp.content


class TestInsecureDesign:
    def test_cannot_apply_price_change_twice(self, client, buyer_user, pending_price_change):
        client.force_login(buyer_user)
        item = pending_price_change.item
        url = reverse('catalog:price_change_apply',
                      kwargs={'pk': item.pk, 'pc_pk': pending_price_change.pk})
        client.post(url)
        item.refresh_from_db()
        first = item.base_price
        client.post(url)  # second apply must be a no-op
        item.refresh_from_db()
        assert item.base_price == first

    def test_cannot_delete_approved_via_view(self, client, buyer_user, approved_item):
        client.force_login(buyer_user)
        client.post(reverse('catalog:item_delete', kwargs={'pk': approved_item.pk}))
        assert CatalogItem.all_objects.filter(pk=approved_item.pk).exists()


class TestAccessControl:
    def test_anonymous_redirected(self, client, draft_item):
        resp = client.get(reverse('catalog:item_list'))
        assert resp.status_code == 302
        assert '/accounts/login' in resp.url

    def test_vendor_bounced_from_buyer_surface(self, client, vendor_portal_user):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse('catalog:item_list'))
        assert resp.status_code == 302  # VendorPortalSandboxMiddleware


class TestFileUpload:
    def test_disallowed_extension_rejected(self, tenant):
        form = SupplierCatalogUploadForm(
            data={}, files={'file': SimpleUploadedFile('evil.exe', b'x')}, tenant=tenant)
        assert not form.is_valid() and 'file' in form.errors

    def test_oversize_rejected(self, tenant):
        big = SimpleUploadedFile('big.csv', b'0' * (11 * 1024 * 1024))
        form = SupplierCatalogUploadForm(data={}, files={'file': big}, tenant=tenant)
        assert not form.is_valid() and 'file' in form.errors


class TestPunchoutSSRF:
    @pytest.mark.parametrize('url', [
        'http://supplier.example.com/po',     # not HTTPS
        'https://127.0.0.1/po',               # loopback
        'https://localhost/po',               # resolves to loopback
        'https://169.254.169.254/latest/',    # cloud metadata
        'https://10.0.0.5/po',                # private
    ])
    def test_blocked(self, url):
        with pytest.raises(ValidationError):
            services.validate_punchout_url(url)

    @override_settings(PUNCHOUT_SSRF_ALLOWLIST='supplier.example.com')
    def test_allowlisted_ok(self):
        assert services.validate_punchout_url('https://supplier.example.com/po')


class TestPunchoutInbound:
    def test_bad_token_404(self, client):
        resp = client.post(reverse('catalog:punchout_return',
                                   kwargs={'token': 'does-not-exist'}),
                           {'item_name': 'X'})
        assert resp.status_code == 404

    def test_wrong_secret_rejected(self, client, open_session):
        resp = client.post(
            reverse('catalog:punchout_return', kwargs={'token': open_session.return_token}),
            {'shared_secret': 'WRONG', 'item_name': 'X', 'item_qty': '1', 'item_price': '1'})
        assert resp.status_code == 400
        open_session.refresh_from_db()
        assert open_session.status != 'returned'

    def test_secret_never_rendered(self, client, buyer_user, tenant, vendor_a):
        set_current_tenant(tenant)
        config = SupplierPunchoutConfig.all_objects.create(
            tenant=tenant, vendor=vendor_a, name='PO', protocol='cxml',
            setup_url='https://supplier.example.com/po',
            shared_secret='topsecret-do-not-leak', is_active=True)
        client.force_login(buyer_user)
        resp = client.get(reverse('catalog:punchout_config_edit', kwargs={'pk': config.pk}))
        assert resp.status_code == 200
        assert b'topsecret-do-not-leak' not in resp.content

    def test_xxe_blocked(self, client, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        config = SupplierPunchoutConfig.all_objects.create(
            tenant=tenant, vendor=vendor_a, name='PO', protocol='cxml',
            setup_url='https://supplier.example.com/po', shared_secret='', is_active=True)
        session = PunchoutSession.all_objects.create(
            tenant=tenant, config=config, vendor=vendor_a,
            buyer_cookie=secrets.token_urlsafe(8), return_token=secrets.token_urlsafe(16),
            started_by=tenant_admin, status='redirected',
            expires_at=timezone.now() + timedelta(hours=1))
        xxe = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE cXML [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            '<cXML><Message><PunchOutOrderMessage><ItemIn quantity="1">'
            '<ItemDetail><Description>&xxe;</Description></ItemDetail>'
            '</ItemIn></PunchOutOrderMessage></Message></cXML>'
        )
        resp = client.post(
            reverse('catalog:punchout_return', kwargs={'token': session.return_token}),
            data=xxe, content_type='text/xml')
        assert resp.status_code == 400
        session.refresh_from_db()
        assert session.status != 'returned'
        assert b'root:' not in resp.content


class TestCrossVendorIsolation:
    def test_vendor_cannot_see_other_upload(self, client, vendor_b_portal_user,
                                            catalog_upload):
        # catalog_upload belongs to vendor_a; vendor_b must not see it.
        client.force_login(vendor_b_portal_user)
        resp = client.get(reverse('vendor_portal:catalog_upload_detail',
                                  kwargs={'pk': catalog_upload.pk}))
        assert resp.status_code == 404
