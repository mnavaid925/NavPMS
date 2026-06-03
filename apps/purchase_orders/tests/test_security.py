"""Security tests for Module 11 — Purchase Order Management (apps/purchase_orders).

OWASP-aligned, mirroring apps/contracts/tests/test_security.py:
  A01 Broken Access Control - cross-tenant IDOR, cross-vendor PO visibility/ack
  A03 Injection (XSS)       - PO title is escaped in the list
  A04 Insecure Design       - server-side state enforcement (no client trust)
  A05 Security Misconfig     - anonymous redirected to login; vendor sandbox
  File upload validation     - oversize / disallowed extension rejected
"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import set_current_tenant
from apps.purchase_orders.forms import PurchaseOrderDocumentForm
from apps.purchase_orders.models import PurchaseOrder

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# A01 - Cross-tenant IDOR
# ---------------------------------------------------------------------------
class TestCrossTenantIDOR:
    def test_intruder_cannot_view(self, client, intruder, draft_po):
        client.force_login(intruder)
        resp = client.get(reverse('purchase_orders:po_detail', kwargs={'pk': draft_po.pk}))
        assert resp.status_code == 404

    def test_intruder_cannot_edit(self, client, intruder, draft_po):
        client.force_login(intruder)
        resp = client.get(reverse('purchase_orders:po_edit', kwargs={'pk': draft_po.pk}))
        assert resp.status_code == 404

    def test_intruder_cannot_delete(self, client, intruder, draft_po):
        client.force_login(intruder)
        resp = client.post(reverse('purchase_orders:po_delete', kwargs={'pk': draft_po.pk}))
        assert resp.status_code == 404
        assert PurchaseOrder.all_objects.filter(pk=draft_po.pk).exists()

    def test_intruder_cannot_issue(self, client, intruder, draft_po):
        client.force_login(intruder)
        resp = client.post(reverse('purchase_orders:po_issue', kwargs={'pk': draft_po.pk}),
                           {'dispatch_method': 'portal'})
        assert resp.status_code == 404
        draft_po.refresh_from_db()
        assert draft_po.status == 'draft'


# ---------------------------------------------------------------------------
# A01 - Cross-vendor: another supplier must not see or acknowledge a PO
# ---------------------------------------------------------------------------
class TestCrossVendor:
    def test_vendor_cannot_view_other_vendor_po(self, client, vendor_b_portal_user, issued_po):
        client.force_login(vendor_b_portal_user)
        resp = client.get(reverse('vendor_portal:purchase_order_detail',
                                  kwargs={'pk': issued_po.pk}))
        assert resp.status_code == 404

    def test_vendor_cannot_acknowledge_other_vendor_po(self, client, vendor_b_portal_user,
                                                       issued_po):
        client.force_login(vendor_b_portal_user)
        resp = client.post(reverse('vendor_portal:purchase_order_acknowledge',
                                   kwargs={'pk': issued_po.pk}), {})
        assert resp.status_code == 404
        issued_po.refresh_from_db()
        assert issued_po.status == 'issued'  # NOT acknowledged

    def test_vendor_cannot_see_draft_po(self, client, vendor_portal_user, draft_po):
        # draft_po belongs to vendor_a but has not been dispatched
        client.force_login(vendor_portal_user)
        resp = client.get(reverse('vendor_portal:purchase_order_detail',
                                  kwargs={'pk': draft_po.pk}))
        assert resp.status_code == 302  # bounced — not visible yet


# ---------------------------------------------------------------------------
# A03 - XSS: PO title escaped in the list
# ---------------------------------------------------------------------------
class TestXSS:
    def test_title_escaped(self, client, buyer_user, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        PurchaseOrder.all_objects.create(
            tenant=tenant, po_number='PO-ACME-0XSS',
            title='<script>alert(1)</script>', vendor=vendor_a,
            created_by=tenant_admin,
        )
        client.force_login(buyer_user)
        resp = client.get(reverse('purchase_orders:po_list'))
        assert resp.status_code == 200
        assert b'<script>alert(1)</script>' not in resp.content
        assert b'&lt;script&gt;' in resp.content


# ---------------------------------------------------------------------------
# A04 - Insecure design: server rejects invalid state transitions
# ---------------------------------------------------------------------------
class TestInsecureDesign:
    def test_cannot_delete_issued_via_view(self, client, buyer_user, issued_po):
        client.force_login(buyer_user)
        client.post(reverse('purchase_orders:po_delete', kwargs={'pk': issued_po.pk}))
        assert PurchaseOrder.all_objects.filter(pk=issued_po.pk).exists()

    def test_cannot_double_acknowledge(self, client, buyer_user, acknowledged_po):
        client.force_login(buyer_user)
        # already acknowledged; a second acknowledge must not change state/stamp
        first_at = acknowledged_po.acknowledged_at
        client.post(reverse('purchase_orders:po_acknowledge',
                            kwargs={'pk': acknowledged_po.pk}), {})
        acknowledged_po.refresh_from_db()
        assert acknowledged_po.status == 'acknowledged'
        assert acknowledged_po.acknowledged_at == first_at

    def test_cannot_edit_lines_when_issued(self, client, buyer_user, issued_po):
        client.force_login(buyer_user)
        line = issued_po.lines.first()
        client.post(reverse('purchase_orders:line_delete',
                            kwargs={'pk': issued_po.pk, 'line_pk': line.pk}))
        assert issued_po.lines.filter(pk=line.pk).exists()


# ---------------------------------------------------------------------------
# A05 - Security misconfig: anonymous + vendor sandbox
# ---------------------------------------------------------------------------
class TestAccessControl:
    def test_anonymous_redirected(self, client, draft_po):
        resp = client.get(reverse('purchase_orders:po_list'))
        assert resp.status_code == 302
        assert '/accounts/login' in resp.url

    def test_vendor_user_bounced_from_buyer_surface(self, client, vendor_portal_user):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse('purchase_orders:po_list'))
        assert resp.status_code == 302  # sandbox middleware bounces to portal


# ---------------------------------------------------------------------------
# File upload validation
# ---------------------------------------------------------------------------
class TestFileUpload:
    def test_disallowed_extension_rejected(self):
        f = SimpleUploadedFile('evil.EXE', b'x', content_type='application/octet-stream')
        form = PurchaseOrderDocumentForm(data={'title': 'x'}, files={'file': f})
        assert not form.is_valid()
        assert 'file' in form.errors

    def test_oversize_rejected(self):
        big = SimpleUploadedFile('big.pdf', b'0' * (11 * 1024 * 1024),
                                 content_type='application/pdf')
        form = PurchaseOrderDocumentForm(data={'title': 'x'}, files={'file': big})
        assert not form.is_valid()
        assert 'file' in form.errors
