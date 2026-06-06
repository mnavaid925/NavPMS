"""Model-level behaviour: rating bands, default KPIs, status properties."""
import pytest

from apps.supplier_performance.models import (
    KpiDefinition, Scorecard, rating_band_from_score,
)
from apps.supplier_performance import services
from .conftest import PERIOD_END, PERIOD_START

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('score,band', [
    (100, 'excellent'), (90, 'excellent'), (89.99, 'good'), (75, 'good'),
    (74, 'acceptable'), (60, 'acceptable'), (59, 'poor'), (40, 'poor'),
    (39, 'critical'), (0, 'critical'),
])
def test_rating_band_boundaries(score, band):
    assert rating_band_from_score(score) == band


def test_ensure_default_kpis_idempotent(tenant):
    n1 = services.ensure_default_kpis(tenant)
    assert n1 == 5
    n2 = services.ensure_default_kpis(tenant)
    assert n2 == 0  # second run adds nothing
    assert KpiDefinition.all_objects.filter(tenant=tenant).count() == 5
    # Default weights sum to 100.
    total = sum(k.weight for k in KpiDefinition.all_objects.filter(tenant=tenant))
    assert total == 100


def test_scorecard_status_properties(tenant, vendor_a):
    draft = Scorecard.all_objects.create(
        tenant=tenant, vendor=vendor_a, scorecard_number='SPC-ACME-00001',
        period_label='P', period_start=PERIOD_START, period_end=PERIOD_END,
        status='draft', overall_score=45, rating_band='poor')
    assert draft.is_editable is True
    assert draft.is_final is False
    assert draft.is_underperforming is True
    draft.status = 'final'
    assert draft.is_editable is False
    assert draft.is_final is True


def test_kpi_is_auto_flag(tenant):
    services.ensure_default_kpis(tenant)
    otd = KpiDefinition.all_objects.get(tenant=tenant, code='OTD')
    fb = KpiDefinition.all_objects.get(tenant=tenant, code='FB')
    assert otd.is_auto is True
    assert fb.is_auto is False  # feedback source, not an auto transactional KPI
