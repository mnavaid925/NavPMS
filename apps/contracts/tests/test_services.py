"""Service-layer tests for Module 9 — Contract Management."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.contracts import services
from apps.contracts.models import (
    Contract,
    ContractAmendment,
    ContractClauseLine,
)
from apps.core.models import set_current_tenant
from apps.portal.models import Notification

pytestmark = pytest.mark.django_db


# ---------- Permissions ----------
class TestPermissions:
    def test_manage_roles(self, tenant_admin, buyer_user, procurement_manager,
                          approver, requester):
        assert services.can_manage_contract(tenant_admin)
        assert services.can_manage_contract(buyer_user)
        assert services.can_manage_contract(procurement_manager)
        assert not services.can_manage_contract(approver)
        assert not services.can_manage_contract(requester)

    def test_view_roles(self, approver, requester):
        assert services.can_view_contract(approver)
        assert not services.can_view_contract(requester)


# ---------- Authoring / templates ----------
class TestTemplating:
    def test_create_from_template_clones_clauses(self, tenant, tenant_admin,
                                                 vendor_a, template):
        set_current_tenant(tenant)
        contract = services.create_contract_from_template(
            template, tenant_admin, vendor=vendor_a, title='Cloned')
        assert contract.status == 'draft'
        assert contract.clause_lines.count() == 2
        assert contract.body  # assembled
        assert contract.template_id == template.pk

    def test_save_as_template_snapshots_clauses(self, tenant, tenant_admin,
                                               draft_contract):
        set_current_tenant(tenant)
        tpl = services.save_contract_as_template(
            draft_contract, tenant_admin, title='From contract')
        assert tpl.clauses.count() == draft_contract.clause_lines.count()

    def test_add_clause_from_library(self, tenant, tenant_admin, draft_contract, clause):
        set_current_tenant(tenant)
        before = draft_contract.clause_lines.count()
        services.add_clause_from_library(draft_contract, clause, tenant_admin)
        assert draft_contract.clause_lines.count() == before + 1


# ---------- E-signature lifecycle ----------
class TestSignature:
    def test_send_requires_signatory(self, tenant, tenant_admin, draft_contract):
        set_current_tenant(tenant)
        with pytest.raises(ValidationError):
            services.send_for_signature(draft_contract, tenant_admin)

    def test_send_assigns_tokens_and_flips_status(self, tenant, tenant_admin,
                                                  ready_contract):
        set_current_tenant(tenant)
        services.send_for_signature(ready_contract, tenant_admin)
        ready_contract.refresh_from_db()
        assert ready_contract.status == 'pending_signature'
        assert all(s.sign_token for s in ready_contract.signatories.all())

    def test_sign_last_signatory_activates(self, tenant, tenant_admin, pending_contract):
        set_current_tenant(tenant)
        sigs = list(pending_contract.signatories.all().order_by('order'))
        services.sign_contract(sigs[0], tenant_admin, 'Ada Admin')
        pending_contract.refresh_from_db()
        assert pending_contract.status == 'pending_signature'  # one still pending
        services.sign_contract(sigs[1], tenant_admin, 'Vendor Rep')
        pending_contract.refresh_from_db()
        assert pending_contract.status == 'active'
        assert pending_contract.activated_at is not None

    def test_cannot_sign_twice(self, tenant, tenant_admin, pending_contract):
        set_current_tenant(tenant)
        s = pending_contract.signatories.order_by('order').first()
        services.sign_contract(s, tenant_admin, 'Ada')
        with pytest.raises(ValidationError):
            services.sign_contract(s, tenant_admin, 'Ada Again')

    def test_decline_reverts_to_draft(self, tenant, tenant_admin, pending_contract):
        set_current_tenant(tenant)
        s = pending_contract.signatories.order_by('order').first()
        services.decline_signature(s, tenant_admin, 'Terms unacceptable')
        pending_contract.refresh_from_db()
        assert pending_contract.status == 'draft'
        s.refresh_from_db()
        assert s.status == 'declined'

    def test_signatory_for_token(self, tenant, pending_contract):
        set_current_tenant(tenant)
        s = pending_contract.signatories.first()
        found = services.signatory_for_token(s.sign_token)
        assert found is not None and found.pk == s.pk
        assert services.signatory_for_token('nonsense') is None


# ---------- Terminate / cancel / renew ----------
class TestLifecycle:
    def test_terminate_active(self, tenant, tenant_admin, active_contract):
        set_current_tenant(tenant)
        services.terminate_contract(active_contract, tenant_admin, 'Breach')
        active_contract.refresh_from_db()
        assert active_contract.status == 'terminated'
        assert active_contract.terminated_reason == 'Breach'

    def test_cannot_terminate_draft(self, tenant, tenant_admin, draft_contract):
        set_current_tenant(tenant)
        with pytest.raises(ValidationError):
            services.terminate_contract(draft_contract, tenant_admin, 'x')

    def test_cancel_draft(self, tenant, tenant_admin, draft_contract):
        set_current_tenant(tenant)
        services.cancel_contract(draft_contract, tenant_admin, 'Not needed')
        draft_contract.refresh_from_db()
        assert draft_contract.status == 'cancelled'

    def test_renew_clones_and_marks_renewed(self, tenant, tenant_admin, active_contract):
        set_current_tenant(tenant)
        old_end = active_contract.end_date
        new_contract = services.renew_contract(active_contract, tenant_admin)
        active_contract.refresh_from_db()
        assert active_contract.status == 'renewed'
        assert new_contract.status == 'draft'
        assert new_contract.parent_contract_id == active_contract.pk
        assert new_contract.contract_number != active_contract.contract_number
        assert new_contract.start_date == old_end
        assert new_contract.clause_lines.count() == active_contract.clause_lines.count()


# ---------- Amendments ----------
class TestAmendments:
    def _draft_amendment(self, tenant, admin, contract, **kw):
        set_current_tenant(tenant)
        return ContractAmendment.all_objects.create(
            tenant=tenant, contract=contract,
            amendment_number=services.next_amendment_number(contract),
            change_type=kw.get('change_type', 'value'),
            title=kw.get('title', 'Adjust'),
            new_value=kw.get('new_value'),
            new_end_date=kw.get('new_end_date'),
            status='draft', created_by=admin,
        )

    def test_apply_bumps_revision_and_snapshots(self, tenant, tenant_admin, active_contract):
        old_value = active_contract.value
        new_end = active_contract.end_date + timedelta(days=180)
        amd = self._draft_amendment(
            tenant, tenant_admin, active_contract,
            new_value=Decimal('150000.00'), new_end_date=new_end)
        services.apply_amendment(amd, tenant_admin)
        active_contract.refresh_from_db()
        amd.refresh_from_db()
        assert active_contract.revision == 2
        assert active_contract.value == Decimal('150000.00')
        assert active_contract.end_date == new_end
        assert amd.status == 'applied'
        assert amd.prev_value == old_value

    def test_cannot_apply_twice(self, tenant, tenant_admin, active_contract):
        amd = self._draft_amendment(
            tenant, tenant_admin, active_contract, new_value=Decimal('1.00'))
        services.apply_amendment(amd, tenant_admin)
        with pytest.raises(ValidationError):
            services.apply_amendment(amd, tenant_admin)

    def test_amendment_number_sequential(self, tenant, tenant_admin, active_contract):
        set_current_tenant(tenant)
        n1 = services.next_amendment_number(active_contract)
        assert n1.endswith('-A01')


# ---------- Obligations ----------
class TestObligations:
    def test_complete(self, tenant, tenant_admin, active_contract):
        set_current_tenant(tenant)
        o = active_contract.obligations.first()
        services.complete_obligation(o, tenant_admin)
        o.refresh_from_db()
        assert o.status == 'completed'
        assert o.completed_at is not None

    def test_mark_overdue(self, tenant, tenant_admin, active_contract):
        set_current_tenant(tenant)
        o = active_contract.obligations.first()
        o.due_date = timezone.localdate() - timedelta(days=2)
        o.save(update_fields=['due_date'])
        flipped = services.mark_overdue_obligations(tenant)
        o.refresh_from_db()
        assert flipped >= 1
        assert o.status == 'overdue'


# ---------- Alert sweep ----------
class TestAlertSweep:
    def test_expiring_raises_notification_once(self, tenant, tenant_admin, expiring_contract):
        set_current_tenant(tenant)
        counts = services.scan_contract_alerts(tenant=tenant)
        assert counts['alerted'] == 1
        expiring_contract.refresh_from_db()
        assert expiring_contract.renewal_alerted_at is not None
        # Exactly one *deadline* alert is raised for this contract's owner.
        assert Notification.all_objects.filter(
            tenant=tenant, user=expiring_contract.owner,
            category='deadline').count() == 1
        # Idempotent second run — no new alert.
        counts2 = services.scan_contract_alerts(tenant=tenant)
        assert counts2['alerted'] == 0

    def test_past_due_expires_non_auto_renew(self, tenant, tenant_admin, active_contract):
        set_current_tenant(tenant)
        active_contract.end_date = timezone.localdate() - timedelta(days=1)
        active_contract.save(update_fields=['end_date'])
        counts = services.scan_contract_alerts(tenant=tenant)
        active_contract.refresh_from_db()
        assert active_contract.status == 'expired'
        assert counts['expired'] == 1

    def test_past_due_auto_renews(self, tenant, tenant_admin, active_contract):
        set_current_tenant(tenant)
        active_contract.auto_renew = True
        active_contract.end_date = timezone.localdate() - timedelta(days=1)
        active_contract.save(update_fields=['auto_renew', 'end_date'])
        old_end = active_contract.end_date
        counts = services.scan_contract_alerts(tenant=tenant)
        active_contract.refresh_from_db()
        assert active_contract.status == 'active'
        assert active_contract.end_date > old_end
        assert counts['auto_renewed'] == 1


# ---------- Analytics ----------
class TestAnalytics:
    def test_tenant_metrics(self, tenant, active_contract, draft_contract):
        set_current_tenant(tenant)
        m = services.tenant_contract_metrics(tenant)
        assert m['total_contracts'] >= 2
        assert m['active'] >= 1
        assert m['active_value'] >= Decimal('120000.00')

    def test_contract_analytics(self, tenant, active_contract):
        set_current_tenant(tenant)
        a = services.contract_analytics(active_contract)
        assert a['signature_progress'] == 100
        assert a['obligation_count'] >= 1
