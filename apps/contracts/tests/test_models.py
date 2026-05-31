"""Model tests for Module 9 — Contract Management."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.contracts.models import (
    Contract,
    ContractClauseLine,
    ContractObligation,
)
from apps.contracts.services import next_contract_number
from apps.core.models import set_current_tenant

pytestmark = pytest.mark.django_db


class TestNumbering:
    def test_number_format(self, tenant):
        number = next_contract_number(tenant)
        assert number.startswith('CON-ACME-')
        assert number.endswith('00001')

    def test_number_increments(self, tenant, draft_contract):
        # draft_contract already used CON-ACME-00001
        assert next_contract_number(tenant) == 'CON-ACME-00002'


class TestContractProperties:
    def test_draft_is_editable_and_cancellable(self, draft_contract):
        assert draft_contract.is_editable
        assert draft_contract.can_cancel
        assert not draft_contract.can_terminate
        assert not draft_contract.is_finished

    def test_active_flags(self, active_contract):
        assert active_contract.is_active
        assert active_contract.can_terminate
        assert active_contract.can_renew
        assert not active_contract.is_editable

    def test_days_to_expiry_and_expiring_soon(self, expiring_contract):
        assert expiring_contract.days_to_expiry == 10
        assert expiring_contract.is_expiring_soon  # within default 30-day notice

    def test_not_expiring_when_far_out(self, active_contract):
        assert not active_contract.is_expiring_soon  # 365 days out

    def test_fully_signed(self, active_contract, draft_contract):
        assert active_contract.is_fully_signed
        assert active_contract.signature_progress == 100
        assert not draft_contract.is_fully_signed  # no signatories

    def test_revision_defaults_to_one(self, draft_contract):
        assert draft_contract.revision == 1


class TestObligation:
    def test_is_overdue(self, tenant, active_contract):
        set_current_tenant(tenant)
        o = ContractObligation.all_objects.create(
            tenant=tenant, contract=active_contract, obligation_type='deliverable',
            title='Late deliverable', status='pending',
            due_date=timezone.localdate() - timedelta(days=5),
        )
        assert o.is_overdue
        assert o.is_open

    def test_completed_not_overdue(self, tenant, active_contract):
        set_current_tenant(tenant)
        o = ContractObligation.all_objects.create(
            tenant=tenant, contract=active_contract, obligation_type='deliverable',
            title='Done', status='completed',
            due_date=timezone.localdate() - timedelta(days=5),
        )
        assert not o.is_overdue


class TestConstraints:
    def test_contract_number_unique_per_tenant(self, tenant, tenant_admin, vendor_a):
        set_current_tenant(tenant)
        Contract.all_objects.create(
            tenant=tenant, contract_number='CON-DUP-1', title='A',
            vendor=vendor_a, created_by=tenant_admin,
        )
        with pytest.raises(IntegrityError):
            Contract.all_objects.create(
                tenant=tenant, contract_number='CON-DUP-1', title='B',
                vendor=vendor_a, created_by=tenant_admin,
            )

    def test_clause_line_position_unique(self, tenant, draft_contract):
        set_current_tenant(tenant)
        # draft_contract already has a clause line at sort_order 1.
        with pytest.raises(IntegrityError):
            ContractClauseLine.all_objects.create(
                tenant=tenant, contract=draft_contract, heading='Dup',
                body='x', sort_order=1,
            )
