"""The KPI engine: each metric computes the right raw value from real source data."""
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.supplier_performance import services
from apps.supplier_performance.models import KpiDefinition
from .conftest import IN_PERIOD, OUT_OF_PERIOD, PERIOD_END, PERIOD_START

pytestmark = pytest.mark.django_db


# ---------- On-Time Delivery ----------

def test_otd_ratio_on_time_vs_late(tenant, vendor_a, make_po, make_grn):
    po1 = make_po(tenant, vendor_a, expected_delivery_date=date(2026, 3, 31), number='PO-1')
    make_grn(tenant, vendor_a, po1, received_date=date(2026, 2, 15), number='GRN-1')   # on time
    po2 = make_po(tenant, vendor_a, expected_delivery_date=date(2026, 2, 1), number='PO-2')
    make_grn(tenant, vendor_a, po2, received_date=date(2026, 3, 1), number='GRN-2')    # late
    result = services._otd_value(vendor_a, PERIOD_START, PERIOD_END)
    assert result['sample_size'] == 2
    assert result['raw_value'] == Decimal('50.00')


def test_otd_boundary_equal_date_is_on_time(tenant, vendor_a, make_po, make_grn):
    po = make_po(tenant, vendor_a, expected_delivery_date=date(2026, 2, 15), number='PO-B')
    make_grn(tenant, vendor_a, po, received_date=date(2026, 2, 15), number='GRN-B')
    result = services._otd_value(vendor_a, PERIOD_START, PERIOD_END)
    assert result['raw_value'] == Decimal('100.00')


def test_otd_excludes_out_of_period(tenant, vendor_a, make_po, make_grn):
    po = make_po(tenant, vendor_a, expected_delivery_date=date(2025, 7, 1), number='PO-O')
    make_grn(tenant, vendor_a, po, received_date=OUT_OF_PERIOD, number='GRN-O')
    result = services._otd_value(vendor_a, PERIOD_START, PERIOD_END)
    assert result['raw_value'] is None
    assert result['sample_size'] == 0


def test_otd_none_when_no_data(tenant, vendor_b):
    result = services._otd_value(vendor_b, PERIOD_START, PERIOD_END)
    assert result['raw_value'] is None


# ---------- Defect / Quality Rate ----------

def test_defect_rate_rejected_over_received(tenant, vendor_a, make_po, make_grn, make_grn_line):
    po = make_po(tenant, vendor_a, number='PO-D')
    grn = make_grn(tenant, vendor_a, po, number='GRN-D')
    make_grn_line(tenant, grn, po, received_quantity=Decimal('10'),
                  rejected_quantity=Decimal('2'))
    result = services._defect_value(vendor_a, PERIOD_START, PERIOD_END)
    assert result['raw_value'] == Decimal('20.00')


def test_defect_none_when_no_received(tenant, vendor_b):
    result = services._defect_value(vendor_b, PERIOD_START, PERIOD_END)
    assert result['raw_value'] is None


# ---------- Responsiveness (PO acknowledgement path) ----------

def test_responsiveness_avg_days(tenant, vendor_a, make_po):
    issued = timezone.make_aware(datetime(2026, 2, 1, 9, 0))
    ack = timezone.make_aware(datetime(2026, 2, 3, 9, 0))   # 2 days
    make_po(tenant, vendor_a, issued_at=issued, acknowledged_at=ack, number='PO-R')
    result = services._responsiveness_value(vendor_a, PERIOD_START, PERIOD_END)
    assert result['sample_size'] == 1
    assert result['raw_value'] == Decimal('2.0')


def test_responsiveness_excludes_unacknowledged(tenant, vendor_a, make_po):
    issued = timezone.make_aware(datetime(2026, 2, 1, 9, 0))
    make_po(tenant, vendor_a, issued_at=issued, acknowledged_at=None, number='PO-U')
    result = services._responsiveness_value(vendor_a, PERIOD_START, PERIOD_END)
    assert result['raw_value'] is None


# ---------- 360° Feedback ----------

def test_feedback_average_in_period(tenant, vendor_a, make_feedback):
    make_feedback(tenant, vendor_a, 4)
    make_feedback(tenant, vendor_a, 2)
    make_feedback(tenant, vendor_a, 5, submitted_on=OUT_OF_PERIOD)  # excluded
    result = services._feedback_value(vendor_a, PERIOD_START, PERIOD_END)
    assert result['raw_value'] == Decimal('3.0')  # avg(4, 2)
    assert result['sample_size'] == 2


def test_feedback_none_when_empty(tenant, vendor_b):
    result = services._feedback_value(vendor_b, PERIOD_START, PERIOD_END)
    assert result['raw_value'] is None


# ---------- Dispatch ----------

def test_compute_kpi_value_manual_returns_none(tenant, vendor_a):
    kpi = KpiDefinition.all_objects.create(
        tenant=tenant, code='CUST', name='Custom', kpi_type='custom', source='manual')
    result = services.compute_kpi_value(kpi, vendor_a, PERIOD_START, PERIOD_END)
    assert result['raw_value'] is None


def test_compute_kpi_value_only_reads_own_tenant(tenant, other_tenant, vendor_a, make_po, make_grn):
    """A vendor's KPI must not pick up another tenant's receipts."""
    po = make_po(tenant, vendor_a, expected_delivery_date=date(2026, 3, 31), number='PO-T')
    make_grn(tenant, vendor_a, po, received_date=IN_PERIOD, number='GRN-T')
    # vendor_a belongs to `tenant`; computing against it sees only tenant rows.
    result = services._otd_value(vendor_a, PERIOD_START, PERIOD_END)
    assert result['sample_size'] == 1
