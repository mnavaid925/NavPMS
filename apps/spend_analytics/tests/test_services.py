"""Service-level tests: sync idempotency + prune, maverick flags, aggregation (with basis
isolation / no double-count), and the report runner."""
from decimal import Decimal

import pytest

from apps.spend_analytics import services
from apps.spend_analytics.models import SpendRecord, SpendReport

pytestmark = pytest.mark.django_db


def test_sync_creates_three_records(spend_data):
    # 2 invoice lines (actual) + 1 PO line (committed).
    assert spend_data.counts['created'] == 3
    assert spend_data.counts['total'] == 3


def test_sync_is_idempotent(spend_data):
    second = services.sync_spend_facts(spend_data.tenant)
    assert second['created'] == 0
    assert second['pruned'] == 0
    assert second['updated'] == 3
    assert second['total'] == 3


def test_maverick_flags(spend_data):
    t = spend_data.tenant
    pref = SpendRecord.all_objects.get(
        tenant=t, source_type='invoice_line', vendor=spend_data.vendor_pref)
    assert pref.is_maverick is False
    assert (pref.off_preferred_supplier, pref.off_contract, pref.off_po) == (False, False, False)

    mav = SpendRecord.all_objects.get(
        tenant=t, source_type='invoice_line', vendor=spend_data.vendor_nonpref)
    assert mav.is_maverick is True
    assert (mav.off_preferred_supplier, mav.off_contract, mav.off_po) == (True, True, True)


def test_prune_on_invoice_cancellation(spend_data):
    t = spend_data.tenant
    spend_data.inv2.status = 'cancelled'
    spend_data.inv2.save(update_fields=['status'])
    counts = services.sync_spend_facts(t)
    assert counts['pruned'] == 1
    assert not SpendRecord.all_objects.filter(
        tenant=t, source_type='invoice_line', vendor=spend_data.vendor_nonpref).exists()


def test_metrics_basis_isolation_no_double_count(spend_data):
    t = spend_data.tenant
    actual = services.tenant_spend_metrics(t, basis='actual')
    committed = services.tenant_spend_metrics(t, basis='committed')
    assert actual['total_spend'] == Decimal('350.00')
    assert actual['record_count'] == 2
    # The PO is also invoiced, but committed (100) is reported separately, never summed with actual.
    assert committed['total_spend'] == Decimal('100.00')
    assert committed['record_count'] == 1


def test_maverick_metrics(spend_data):
    m = services.maverick_metrics(spend_data.tenant, basis='actual')
    assert m['maverick_spend'] == Decimal('250.00')
    assert m['maverick_count'] == 1
    reasons = {r['reason']: r['count'] for r in m['by_reason']}
    assert reasons == {'off_preferred_supplier': 1, 'off_contract': 1, 'off_po': 1}


def test_category_spend_totals(spend_data):
    data = services.category_spend(spend_data.tenant, basis='actual')
    assert sum(r['total'] for r in data['rows']) == Decimal('350.00')
    labels = {r['label'] for r in data['rows']}
    assert {'IT Equipment', 'Office Supplies'} <= labels


def test_run_spend_report_by_category(spend_data):
    rep = SpendReport.all_objects.create(
        tenant=spend_data.tenant, name='Cat', dimension='vendor_category',
        measure='amount_sum', basis='actual')
    result = services.run_spend_report(rep)
    assert {'IT Equipment', 'Office Supplies'} <= set(result['labels'])
    assert round(sum(result['values']), 2) == 350.0
    assert result['kind'] == 'bar'


def test_run_spend_report_record_count_measure(spend_data):
    rep = SpendReport.all_objects.create(
        tenant=spend_data.tenant, name='Count', dimension='vendor',
        measure='record_count', basis='actual')
    result = services.run_spend_report(rep)
    assert round(sum(result['values'])) == 2  # two actual invoice-line records
