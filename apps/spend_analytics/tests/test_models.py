"""Model-level tests: unique_together, maverick flags, SpendReport defaults."""
from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.spend_analytics.models import SpendRecord, SpendReport

pytestmark = pytest.mark.django_db


def test_spendrecord_unique_per_source(tenant):
    SpendRecord.all_objects.create(
        tenant=tenant, source_type='invoice_line', source_id=1, basis='actual',
        amount=Decimal('10.00'))
    with pytest.raises(IntegrityError):
        SpendRecord.all_objects.create(
            tenant=tenant, source_type='invoice_line', source_id=1, basis='actual',
            amount=Decimal('20.00'))


def test_maverick_reasons_property(tenant):
    r = SpendRecord(
        tenant=tenant, source_type='invoice_line', source_id=2, basis='actual',
        off_preferred_supplier=True, off_contract=True, off_po=False)
    reasons = r.maverick_reasons
    assert 'Off preferred supplier' in reasons
    assert 'No active contract' in reasons
    assert 'Non-PO purchase' not in reasons


def test_spendrecord_str(tenant):
    r = SpendRecord(
        tenant=tenant, source_type='po_line', source_id=3, basis='committed',
        amount=Decimal('42.00'), currency='USD', source_ref='PO-1#L1')
    assert 'PO-1#L1' in str(r)


def test_spendreport_defaults_and_str(tenant):
    rep = SpendReport.all_objects.create(tenant=tenant, name='My report')
    assert rep.dimension == 'vendor_category'
    assert rep.measure == 'amount_sum'
    assert rep.chart_type == 'bar'
    assert rep.basis == 'actual'
    assert rep.is_shared is False
    assert str(rep) == 'My report'
