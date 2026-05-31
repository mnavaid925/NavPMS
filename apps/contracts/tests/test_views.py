"""View tests for Module 9 — Contract Management (buyer side + vendor portal)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.contracts.models import Contract, ContractObligation

pytestmark = pytest.mark.django_db


def _contract_post(vendor):
    today = timezone.localdate()
    return {
        'title': 'New supply contract',
        'description': 'desc',
        'contract_type': 'supply',
        'vendor': vendor.pk,
        'currency': 'USD',
        'value': '50000.00',
        'start_date': today.isoformat(),
        'end_date': (today + timedelta(days=200)).isoformat(),
        'renewal_term_months': 12,
        'renewal_notice_days': 30,
        'terms_and_conditions': '',
    }


# ---------- List + CRUD ----------
class TestList:
    def test_list_200(self, client, buyer_user, draft_contract):
        client.force_login(buyer_user)
        resp = client.get(reverse('contracts:contract_list'))
        assert resp.status_code == 200
        assert draft_contract.contract_number.encode() in resp.content

    def test_list_status_filter(self, client, buyer_user, draft_contract, active_contract):
        client.force_login(buyer_user)
        resp = client.get(reverse('contracts:contract_list'), {'status': 'draft'})
        assert resp.status_code == 200
        assert draft_contract.contract_number.encode() in resp.content
        assert active_contract.contract_number.encode() not in resp.content

    def test_list_search(self, client, buyer_user, draft_contract):
        client.force_login(buyer_user)
        resp = client.get(reverse('contracts:contract_list'),
                          {'q': draft_contract.title})
        assert resp.status_code == 200


class TestCreate:
    def test_get_200(self, client, buyer_user):
        client.force_login(buyer_user)
        assert client.get(reverse('contracts:contract_create')).status_code == 200

    def test_post_creates(self, client, buyer_user, tenant, vendor_a):
        client.force_login(buyer_user)
        before = Contract.all_objects.filter(tenant=tenant).count()
        resp = client.post(reverse('contracts:contract_create'), _contract_post(vendor_a))
        assert resp.status_code == 302
        assert Contract.all_objects.filter(tenant=tenant).count() == before + 1


class TestDetailEditDelete:
    def test_detail_200(self, client, buyer_user, draft_contract):
        client.force_login(buyer_user)
        assert client.get(reverse('contracts:contract_detail',
                                  kwargs={'pk': draft_contract.pk})).status_code == 200

    def test_edit_draft(self, client, buyer_user, draft_contract, vendor_a):
        client.force_login(buyer_user)
        data = _contract_post(vendor_a)
        data['title'] = 'Edited title'
        resp = client.post(reverse('contracts:contract_edit',
                                   kwargs={'pk': draft_contract.pk}), data)
        assert resp.status_code == 302
        draft_contract.refresh_from_db()
        assert draft_contract.title == 'Edited title'

    def test_cannot_edit_active(self, client, buyer_user, active_contract):
        client.force_login(buyer_user)
        resp = client.get(reverse('contracts:contract_edit',
                                  kwargs={'pk': active_contract.pk}))
        assert resp.status_code == 302  # redirected with error

    def test_delete_draft(self, client, buyer_user, draft_contract):
        client.force_login(buyer_user)
        resp = client.post(reverse('contracts:contract_delete',
                                   kwargs={'pk': draft_contract.pk}))
        assert resp.status_code == 302
        assert not Contract.all_objects.filter(pk=draft_contract.pk).exists()


# ---------- Authoring ----------
class TestAuthoring:
    def test_author_200(self, client, buyer_user, draft_contract):
        client.force_login(buyer_user)
        assert client.get(reverse('contracts:contract_author',
                                  kwargs={'pk': draft_contract.pk})).status_code == 200

    def test_add_clause_line(self, client, buyer_user, draft_contract):
        client.force_login(buyer_user)
        before = draft_contract.clause_lines.count()
        resp = client.post(
            reverse('contracts:clause_line_add', kwargs={'pk': draft_contract.pk}),
            {'heading': 'Liability', 'body': 'Capped.', 'sort_order': 2})
        assert resp.status_code == 302
        assert draft_contract.clause_lines.count() == before + 1


# ---------- Lifecycle ----------
class TestLifecycle:
    def test_send_for_signature(self, client, buyer_user, ready_contract):
        client.force_login(buyer_user)
        resp = client.post(reverse('contracts:contract_send_for_signature',
                                   kwargs={'pk': ready_contract.pk}))
        assert resp.status_code == 302
        ready_contract.refresh_from_db()
        assert ready_contract.status == 'pending_signature'

    def test_send_guard_without_signatory(self, client, buyer_user, draft_contract):
        client.force_login(buyer_user)
        resp = client.post(reverse('contracts:contract_send_for_signature',
                                   kwargs={'pk': draft_contract.pk}))
        assert resp.status_code == 302
        draft_contract.refresh_from_db()
        assert draft_contract.status == 'draft'  # blocked

    def test_internal_sign(self, client, tenant_admin, pending_contract):
        client.force_login(tenant_admin)
        s = pending_contract.signatories.filter(party='internal').first()
        resp = client.post(
            reverse('contracts:signatory_sign',
                    kwargs={'pk': pending_contract.pk, 'signatory_pk': s.pk}),
            {'signed_name': 'Ada Admin', 'agree': 'on'})
        assert resp.status_code == 302
        s.refresh_from_db()
        assert s.status == 'signed'

    def test_terminate(self, client, buyer_user, active_contract):
        client.force_login(buyer_user)
        resp = client.post(reverse('contracts:contract_terminate',
                                   kwargs={'pk': active_contract.pk}),
                           {'reason': 'Breach of SLA'})
        assert resp.status_code == 302
        active_contract.refresh_from_db()
        assert active_contract.status == 'terminated'

    def test_renew(self, client, buyer_user, active_contract, tenant):
        client.force_login(buyer_user)
        before = Contract.all_objects.filter(tenant=tenant).count()
        resp = client.post(reverse('contracts:contract_renew',
                                   kwargs={'pk': active_contract.pk}))
        assert resp.status_code == 302
        assert Contract.all_objects.filter(tenant=tenant).count() == before + 1


# ---------- Amendments + obligations ----------
class TestAmendmentsObligations:
    def test_amendment_create_and_apply(self, client, buyer_user, active_contract):
        client.force_login(buyer_user)
        new_end = (active_contract.end_date + timedelta(days=90)).isoformat()
        resp = client.post(
            reverse('contracts:amendment_create', kwargs={'pk': active_contract.pk}),
            {'title': 'Extend', 'change_type': 'term_extension',
             'description': 'extend', 'new_end_date': new_end})
        assert resp.status_code == 302
        amd = active_contract.amendments.first()
        assert amd is not None
        resp2 = client.post(reverse('contracts:amendment_apply',
                                    kwargs={'pk': active_contract.pk,
                                            'amendment_pk': amd.pk}))
        assert resp2.status_code == 302
        active_contract.refresh_from_db()
        assert active_contract.revision == 2

    def test_obligation_add_and_complete(self, client, buyer_user, active_contract):
        client.force_login(buyer_user)
        resp = client.post(
            reverse('contracts:obligation_add', kwargs={'pk': active_contract.pk}),
            {'obligation_type': 'deliverable', 'title': 'Deliver X',
             'amount': '0', 'penalty_amount': '0', 'responsible_party': 'vendor',
             'status': 'pending'})
        assert resp.status_code == 302
        o = ContractObligation.all_objects.filter(
            contract=active_contract, title='Deliver X').first()
        assert o is not None
        resp2 = client.post(reverse('contracts:obligation_complete',
                                    kwargs={'pk': active_contract.pk,
                                            'obligation_pk': o.pk}))
        assert resp2.status_code == 302
        o.refresh_from_db()
        assert o.status == 'completed'


# ---------- Boards + analytics + libraries ----------
class TestBoardsAndLibraries:
    def test_renewals_board(self, client, buyer_user, expiring_contract):
        client.force_login(buyer_user)
        resp = client.get(reverse('contracts:renewals_board'))
        assert resp.status_code == 200
        assert expiring_contract.contract_number.encode() in resp.content

    def test_obligation_board(self, client, buyer_user, active_contract):
        client.force_login(buyer_user)
        assert client.get(reverse('contracts:obligation_board')).status_code == 200

    def test_analytics(self, client, buyer_user, active_contract):
        client.force_login(buyer_user)
        assert client.get(reverse('contracts:analytics_dashboard')).status_code == 200
        assert client.get(reverse('contracts:contract_analytics',
                                  kwargs={'pk': active_contract.pk})).status_code == 200

    def test_clause_library_crud(self, client, buyer_user, tenant):
        client.force_login(buyer_user)
        assert client.get(reverse('contracts:clause_list')).status_code == 200
        resp = client.post(reverse('contracts:clause_create'),
                           {'title': 'New clause', 'category': 'general',
                            'body': 'text', 'sort_order': 0,
                            'is_standard': 'on', 'is_active': 'on'})
        assert resp.status_code == 302

    def test_template_use(self, client, buyer_user, template, vendor_a, tenant):
        client.force_login(buyer_user)
        before = Contract.all_objects.filter(tenant=tenant).count()
        resp = client.post(reverse('contracts:template_use', kwargs={'pk': template.pk}),
                           {'vendor': vendor_a.pk, 'title': 'From tpl'})
        assert resp.status_code == 302
        assert Contract.all_objects.filter(tenant=tenant).count() == before + 1


# ---------- Permission gate ----------
class TestPermissionGate:
    def test_requester_cannot_create(self, client, requester):
        client.force_login(requester)
        resp = client.get(reverse('contracts:contract_create'))
        assert resp.status_code == 302  # redirected away

    def test_requester_cannot_list(self, client, requester, draft_contract):
        client.force_login(requester)
        resp = client.get(reverse('contracts:contract_list'))
        assert resp.status_code == 302


# ---------- Vendor portal ----------
class TestVendorPortal:
    def test_vendor_sees_own_contracts(self, client, vendor_portal_user, active_contract):
        client.force_login(vendor_portal_user)
        resp = client.get(reverse('vendor_portal:contract_inbox'))
        assert resp.status_code == 200
        assert active_contract.contract_number.encode() in resp.content

    def test_vendor_sign_via_token(self, client, vendor_b_portal_user, tenant,
                                   tenant_admin, vendor_b):
        # Build a pending contract for vendor_b and sign through the portal token.
        from apps.contracts.models import Contract, ContractClauseLine, ContractSignatory
        from apps.contracts.services import send_for_signature
        from apps.core.models import set_current_tenant
        set_current_tenant(tenant)
        c = Contract.all_objects.create(
            tenant=tenant, contract_number='CON-ACME-07777', title='VB deal',
            vendor=vendor_b, created_by=tenant_admin, owner=tenant_admin,
            end_date=timezone.localdate() + timedelta(days=100),
        )
        ContractClauseLine.all_objects.create(
            tenant=tenant, contract=c, heading='Terms', body='x', sort_order=1)
        ContractSignatory.all_objects.create(
            tenant=tenant, contract=c, party='vendor', vendor=vendor_b,
            name='VB Rep', email='vb@x.test', order=1)
        send_for_signature(c, tenant_admin)
        token = c.signatories.first().sign_token

        client.force_login(vendor_b_portal_user)
        resp = client.post(reverse('vendor_portal:contract_sign', kwargs={'token': token}),
                           {'signed_name': 'VB Rep', 'agree': 'on'})
        assert resp.status_code == 302
        c.refresh_from_db()
        assert c.status == 'active'
