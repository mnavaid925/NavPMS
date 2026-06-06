"""Internal views: CRUD, generation, exports render for a manager."""
import pytest
from django.urls import reverse

from apps.supplier_performance import services
from apps.supplier_performance.models import ImprovementPlan, KpiDefinition, Scorecard
from .conftest import PERIOD_END, PERIOD_START

pytestmark = pytest.mark.django_db


def test_dashboard_ok_for_manager(client, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.get(reverse('supplier_performance:dashboard'))
    assert resp.status_code == 200


def test_kpi_create(client, tenant, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('supplier_performance:kpi_create'), {
        'code': 'NEW', 'name': 'New KPI', 'kpi_type': 'custom', 'source': 'manual',
        'direction': 'higher_better', 'weight': '10', 'green_threshold': '80',
        'amber_threshold': '60', 'display_order': '9', 'is_active': 'on',
    })
    assert resp.status_code == 302
    assert KpiDefinition.all_objects.filter(tenant=tenant, code='NEW').exists()


def test_scorecard_generate_creates_card(client, tenant, vendor_a, tenant_admin, kpis,
                                         make_feedback):
    make_feedback(tenant, vendor_a, 4)
    client.force_login(tenant_admin)
    resp = client.post(reverse('supplier_performance:scorecard_generate'), {
        'vendor': vendor_a.pk, 'period_label': 'Q1 2026',
        'period_start': PERIOD_START.isoformat(), 'period_end': PERIOD_END.isoformat(),
        'finalize': 'on',
    })
    assert resp.status_code == 302
    card = Scorecard.all_objects.get(tenant=tenant, vendor=vendor_a)
    assert card.status == 'final'
    assert card.overall_score == 80


def test_scorecard_detail_and_export(client, tenant, vendor_a, tenant_admin, kpis, make_feedback):
    make_feedback(tenant, vendor_a, 4)
    card = services.generate_scorecard(vendor_a, PERIOD_START, PERIOD_END, tenant_admin)
    client.force_login(tenant_admin)
    assert client.get(
        reverse('supplier_performance:scorecard_detail', args=[card.pk])).status_code == 200
    csv = client.get(reverse('supplier_performance:export_scorecard', args=[card.pk, 'csv']))
    assert csv.status_code == 200
    assert csv['Content-Type'] == 'text/csv'
    xlsx = client.get(reverse('supplier_performance:export_scorecard', args=[card.pk, 'xlsx']))
    assert xlsx.status_code == 200


def test_pip_create_and_status(client, tenant, vendor_a, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('supplier_performance:pip_create'), {
        'vendor': vendor_a.pk, 'title': 'Recovery', 'severity': 'high',
    })
    assert resp.status_code == 302
    plan = ImprovementPlan.all_objects.get(tenant=tenant, vendor=vendor_a)
    resp = client.post(reverse('supplier_performance:pip_set_status', args=[plan.pk]),
                       {'status': 'open'})
    plan.refresh_from_db()
    assert plan.status == 'open'


def test_trending_and_benchmarking_ok(client, tenant_admin):
    client.force_login(tenant_admin)
    assert client.get(reverse('supplier_performance:trending')).status_code == 200
    assert client.get(reverse('supplier_performance:benchmarking')).status_code == 200
    assert client.get(reverse('supplier_performance:kpi_list')).status_code == 200
    assert client.get(reverse('supplier_performance:scorecard_list')).status_code == 200
    assert client.get(reverse('supplier_performance:feedback_list')).status_code == 200
    assert client.get(reverse('supplier_performance:pip_list')).status_code == 200
