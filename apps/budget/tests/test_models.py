"""Model-level tests: constraints, properties, __str__."""
from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.budget.models import Budget, BudgetAllocation, BudgetPeriod

pytestmark = pytest.mark.django_db


def test_period_unique_per_tenant(budget_data):
    with pytest.raises(IntegrityError):
        BudgetPeriod.all_objects.create(
            tenant=budget_data.tenant, name='FY2026',
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))


def test_budget_number_unique_per_tenant(budget_data):
    with pytest.raises(IntegrityError):
        Budget.all_objects.create(
            tenant=budget_data.tenant, budget_number='BUD-ACME-00001', name='dup',
            period=budget_data.period)


def test_allocation_unique_per_account_code_and_category(budget_data):
    """The DB constraint is (budget, account_code, vendor_category). It enforces uniqueness for a
    concrete category (NULL categories are handled by the view's explicit duplicate guard)."""
    BudgetAllocation.all_objects.create(
        tenant=budget_data.tenant, budget=budget_data.budget,
        account_code=budget_data.account_code, vendor_category=budget_data.category,
        allocated_amount=Decimal('5'))
    with pytest.raises(IntegrityError):
        BudgetAllocation.all_objects.create(
            tenant=budget_data.tenant, budget=budget_data.budget,
            account_code=budget_data.account_code, vendor_category=budget_data.category,
            allocated_amount=Decimal('7'))


def test_budget_editable_and_active_flags(budget_data):
    assert budget_data.budget.is_active is True
    assert budget_data.budget.is_editable is False
    budget_data.budget.status = 'draft'
    assert budget_data.budget.is_editable is True


def test_period_is_open(budget_data):
    assert budget_data.period.is_open is True
    budget_data.period.status = 'closed'
    assert budget_data.period.is_open is False


def test_str(budget_data):
    assert 'BUD-ACME-00001' in str(budget_data.budget)
    assert budget_data.period.name in str(budget_data.period)
