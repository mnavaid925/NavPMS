"""Permission gating (incl. D-01/D-02: reads + exports gate on view) and tenant isolation."""
import pytest
from django.urls import reverse

from apps.supplier_performance import services
from .conftest import PERIOD_END, PERIOD_START

pytestmark = pytest.mark.django_db


def test_requester_denied_on_read_views(client, requester):
    """A requester (no view permission) is bounced off every read view."""
    client.force_login(requester)
    for name in ('dashboard', 'scorecard_list', 'kpi_list', 'feedback_list', 'pip_list',
                 'trending', 'benchmarking'):
        resp = client.get(reverse(f'supplier_performance:{name}'))
        assert resp.status_code == 302   # redirected away, not 200


def test_requester_denied_on_export(client, tenant, vendor_a, tenant_admin, kpis, make_feedback,
                                    requester):
    make_feedback(tenant, vendor_a, 4)
    card = services.generate_scorecard(vendor_a, PERIOD_START, PERIOD_END, tenant_admin)
    client.force_login(requester)
    # D-01/D-02: exports must gate on view permission, not tenant alone.
    resp = client.get(reverse('supplier_performance:export_scorecard', args=[card.pk, 'csv']))
    assert resp.status_code == 302
    resp = client.get(reverse('supplier_performance:export_benchmark', args=['csv']))
    assert resp.status_code == 302


def test_approver_can_view_but_not_manage(client, evaluator):
    client.force_login(evaluator)
    assert client.get(reverse('supplier_performance:scorecard_list')).status_code == 200
    # Manage-only route: generating a scorecard.
    assert client.get(reverse('supplier_performance:scorecard_generate')).status_code == 302
    assert client.get(reverse('supplier_performance:kpi_create')).status_code == 302


def test_cross_tenant_scorecard_is_404(client, tenant, vendor_a, tenant_admin, kpis,
                                       make_feedback, intruder):
    make_feedback(tenant, vendor_a, 4)
    card = services.generate_scorecard(vendor_a, PERIOD_START, PERIOD_END, tenant_admin)
    client.force_login(intruder)   # other tenant, but is_tenant_admin (passes _require_view)
    resp = client.get(reverse('supplier_performance:scorecard_detail', args=[card.pk]))
    assert resp.status_code == 404


def test_vendor_portal_user_blocked_from_internal(client, vendor_portal_user):
    client.force_login(vendor_portal_user)
    resp = client.get(reverse('supplier_performance:dashboard'))
    assert resp.status_code == 302   # @vendor_blocked bounces to the portal
