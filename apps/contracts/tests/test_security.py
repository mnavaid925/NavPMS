"""Security tests for Module 9 — Contract Management (apps/contracts).

OWASP-aligned, mirroring apps/auctions/tests/test_security.py:
  A01 Broken Access Control - cross-tenant IDOR, cross-vendor signing
  A03 Injection (XSS)       - contract title is escaped in the list
  A04 Insecure Design       - server-side state enforcement (no client trust)
  A05 Security Misconfig     - anonymous redirected to login; vendor sandbox
  File upload validation     - oversize / disallowed extension rejected
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.contracts.forms import ContractDocumentForm
from apps.contracts.models import Contract, ContractClauseLine, ContractSignatory
from apps.contracts.services import send_for_signature
from apps.core.models import set_current_tenant

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# A01 - Cross-tenant IDOR
# ---------------------------------------------------------------------------
class TestCrossTenantIDOR:
    def test_intruder_cannot_view(self, client, intruder, draft_contract):
        client.force_login(intruder)
        resp = client.get(reverse('contracts:contract_detail',
                                  kwargs={'pk': draft_contract.pk}))
        assert resp.status_code == 404

    def test_intruder_cannot_edit(self, client, intruder, draft_contract):
        client.force_login(intruder)
        resp = client.get(reverse('contracts:contract_edit',
                                  kwargs={'pk': draft_contract.pk}))
        assert resp.status_code == 404

    def test_intruder_cannot_delete(self, client, intruder, draft_contract):
        client.force_login(intruder)
        resp = client.post(reverse('contracts:contract_delete',
                                   kwargs={'pk': draft_contract.pk}))
        assert resp.status_code == 404
        assert Contract.all_objects.filter(pk=draft_contract.pk).exists()


# ---------------------------------------------------------------------------
# A01 - Cross-vendor signing: another vendor's token must not work
# ---------------------------------------------------------------------------
class TestCrossVendorSigning:
    def test_other_vendor_cannot_use_token(self, client, vendor_b_portal_user,
                                           pending_contract):
        # pending_contract belongs to vendor_a; vendor_b tries its vendor token.
        token = pending_contract.signatories.filter(party='vendor').first().sign_token
        client.force_login(vendor_b_portal_user)
        resp = client.post(reverse('vendor_portal:contract_sign',
                                   kwargs={'token': token}),
                           {'signed_name': 'Mallory', 'agree': 'on'})
        assert resp.status_code == 302  # bounced to inbox
        pending_contract.refresh_from_db()
        assert pending_contract.status == 'pending_signature'  # NOT signed

    def test_vendor_cannot_view_other_vendor_contract(self, client,
                                                      vendor_b_portal_user,
                                                      active_contract):
        client.force_login(vendor_b_portal_user)
        resp = client.get(reverse('vendor_portal:contract_detail',
                                  kwargs={'pk': active_contract.pk}))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# A03 - XSS: contract title escaped in the list
# ---------------------------------------------------------------------------
class TestXSS:
    def test_title_escaped(self, client, buyer_user, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        Contract.all_objects.create(
            tenant=tenant, contract_number='CON-ACME-0XSS',
            title='<script>alert(1)</script>', vendor=vendor_a,
            created_by=tenant_admin,
        )
        client.force_login(buyer_user)
        resp = client.get(reverse('contracts:contract_list'))
        assert resp.status_code == 200
        assert b'<script>alert(1)</script>' not in resp.content
        assert b'&lt;script&gt;' in resp.content


# ---------------------------------------------------------------------------
# A04 - Insecure design: server rejects invalid state transitions
# ---------------------------------------------------------------------------
class TestInsecureDesign:
    def test_cannot_reapply_amendment(self, client, buyer_user, active_contract, tenant):
        from apps.contracts.models import ContractAmendment
        from apps.contracts.services import apply_amendment, next_amendment_number
        set_current_tenant(tenant)
        amd = ContractAmendment.all_objects.create(
            tenant=tenant, contract=active_contract,
            amendment_number=next_amendment_number(active_contract),
            change_type='value', title='Bump', new_value=Decimal('1.00'),
            status='draft', created_by=buyer_user,
        )
        apply_amendment(amd, buyer_user)
        active_contract.refresh_from_db()
        rev_after_first = active_contract.revision
        client.force_login(buyer_user)
        # Re-applying via the view must not bump the revision again.
        client.post(reverse('contracts:amendment_apply',
                            kwargs={'pk': active_contract.pk, 'amendment_pk': amd.pk}))
        active_contract.refresh_from_db()
        assert active_contract.revision == rev_after_first

    def test_cannot_delete_active_via_view(self, client, buyer_user, active_contract):
        client.force_login(buyer_user)
        client.post(reverse('contracts:contract_delete',
                            kwargs={'pk': active_contract.pk}))
        assert Contract.all_objects.filter(pk=active_contract.pk).exists()


# ---------------------------------------------------------------------------
# A05 - Security misconfig: anonymous + vendor sandbox
# ---------------------------------------------------------------------------
class TestAccessControl:
    def test_anonymous_redirected(self, client, draft_contract):
        resp = client.get(reverse('contracts:contract_list'))
        assert resp.status_code == 302
        assert '/accounts/login' in resp.url

    def test_vendor_user_bounced_from_buyer_surface(self, client, vendor_portal_user):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse('contracts:contract_list'))
        assert resp.status_code == 302  # sandbox middleware bounces to portal


# ---------------------------------------------------------------------------
# File upload validation
# ---------------------------------------------------------------------------
class TestFileUpload:
    def test_disallowed_extension_rejected(self):
        f = SimpleUploadedFile('evil.EXE', b'x', content_type='application/octet-stream')
        form = ContractDocumentForm(data={'title': 'x'}, files={'file': f})
        assert not form.is_valid()
        assert 'file' in form.errors

    def test_oversize_rejected(self):
        big = SimpleUploadedFile('big.pdf', b'0' * (11 * 1024 * 1024),
                                 content_type='application/pdf')
        form = ContractDocumentForm(data={'title': 'x'}, files={'file': big})
        assert not form.is_valid()
        assert 'file' in form.errors
