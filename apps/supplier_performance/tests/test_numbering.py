"""Auto-numbering: gap-free, tenant-slugged, delete-safe (SPC/PIP)."""
import pytest

from apps.supplier_performance import services
from apps.supplier_performance.models import Scorecard
from .conftest import PERIOD_END, PERIOD_START

pytestmark = pytest.mark.django_db


def test_scorecard_number_format_and_increment(tenant, other_tenant, vendor_a):
    assert services.next_scorecard_number(tenant) == 'SPC-ACME-00001'
    Scorecard.all_objects.create(
        tenant=tenant, vendor=vendor_a, scorecard_number='SPC-ACME-00001',
        period_label='P', period_start=PERIOD_START, period_end=PERIOD_END)
    assert services.next_scorecard_number(tenant) == 'SPC-ACME-00002'
    # Per-tenant slug.
    assert services.next_scorecard_number(other_tenant) == 'SPC-GLOBEX-00001'


def test_scorecard_number_delete_safe(tenant, vendor_a):
    c1 = Scorecard.all_objects.create(
        tenant=tenant, vendor=vendor_a, scorecard_number='SPC-ACME-00001',
        period_label='P', period_start=PERIOD_START, period_end=PERIOD_END)
    Scorecard.all_objects.create(
        tenant=tenant, vendor=vendor_a, scorecard_number='SPC-ACME-00002',
        period_label='P', period_start=PERIOD_START, period_end=PERIOD_END)
    c1.delete()
    # COUNT+1 would collide with the surviving 00002; the bump loop must skip it.
    assert services.next_scorecard_number(tenant) == 'SPC-ACME-00003'


def test_pip_number_format(tenant, vendor_a):
    assert services.next_pip_number(tenant) == 'PIP-ACME-00001'
