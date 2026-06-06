"""Security tests — the D-01/D-02 gate directly (lessons.md 2026-05-29): every read AND export
view is gated on ``can_view``; cross-tenant IDOR returns 404; private reports are owner-or-manager
only; mutations need ``can_manage``; the report name cannot inject script."""
import pytest
from django.urls import reverse

from apps.spend_analytics.models import SpendReport

pytestmark = pytest.mark.django_db

READ_VIEWS = [
    'spend_analytics:dashboard',
    'spend_analytics:category_analysis',
    'spend_analytics:maverick_tracking',
    'spend_analytics:report_list',
]
EXPORT_VIEWS = [
    ('spend_analytics:export_dashboard', ['csv']),
    ('spend_analytics:export_records', ['csv']),
]


@pytest.mark.parametrize('view_name', READ_VIEWS)
def test_requester_blocked_from_reads(client, spend_data, requester, view_name):
    client.force_login(requester)
    assert client.get(reverse(view_name)).status_code == 302  # bounced with an error


@pytest.mark.parametrize('view_name', READ_VIEWS)
def test_anonymous_blocked_from_reads(client, spend_data, view_name):
    assert client.get(reverse(view_name)).status_code == 302  # @login_required


@pytest.mark.parametrize('view_name', READ_VIEWS)
@pytest.mark.parametrize('role_fixture', ['buyer_user', 'approver'])
def test_view_roles_allowed(client, spend_data, request, view_name, role_fixture):
    client.force_login(request.getfixturevalue(role_fixture))
    assert client.get(reverse(view_name)).status_code == 200


@pytest.mark.parametrize('view_name,args', EXPORT_VIEWS)
def test_requester_blocked_from_exports(client, spend_data, requester, view_name, args):
    client.force_login(requester)
    assert client.get(reverse(view_name, args=args)).status_code == 302


def test_cross_tenant_report_404(client, spend_data, shared_report, intruder):
    client.force_login(intruder)
    assert client.get(reverse('spend_analytics:report_detail', args=[shared_report.pk])).status_code == 404
    assert client.get(reverse('spend_analytics:export_report', args=[shared_report.pk, 'csv'])).status_code == 404
    assert client.get(reverse('spend_analytics:report_edit', args=[shared_report.pk])).status_code == 404


def test_cross_tenant_category_404(client, spend_data, intruder):
    client.force_login(intruder)
    url = reverse('spend_analytics:category_detail', args=[spend_data.cat_a.pk])
    assert client.get(url).status_code == 404


def test_report_list_excludes_other_tenant(client, spend_data, shared_report, intruder):
    client.force_login(intruder)
    resp = client.get(reverse('spend_analytics:report_list'))
    assert resp.status_code == 200
    assert b'Shared category report' not in resp.content


def test_private_report_isolation(client, spend_data, private_report, approver, buyer_user):
    # Same-tenant viewer who is neither owner nor manager -> 404.
    client.force_login(approver)
    assert client.get(reverse('spend_analytics:report_detail', args=[private_report.pk])).status_code == 404
    # A manager can view it.
    client.force_login(buyer_user)
    assert client.get(reverse('spend_analytics:report_detail', args=[private_report.pk])).status_code == 200


def test_private_report_hidden_from_non_owner_list(client, spend_data, private_report, approver):
    client.force_login(approver)
    resp = client.get(reverse('spend_analytics:report_list'))
    assert b'Private vendor report' not in resp.content


def test_approver_can_view_shared_report(client, spend_data, shared_report, approver):
    client.force_login(approver)
    assert client.get(reverse('spend_analytics:report_detail', args=[shared_report.pk])).status_code == 200


def test_requester_cannot_sync(client, spend_data, requester):
    client.force_login(requester)
    assert client.post(reverse('spend_analytics:sync_now')).status_code == 302


def test_requester_cannot_create_report(client, spend_data, requester):
    client.force_login(requester)
    resp = client.post(reverse('spend_analytics:report_create'), {
        'name': 'Sneaky', 'dimension': 'vendor', 'measure': 'amount_sum',
        'chart_type': 'bar', 'basis': 'actual',
    })
    assert resp.status_code == 302
    assert not SpendReport.objects.filter(name='Sneaky').exists()


def test_report_name_xss_is_escaped(client, spend_data, tenant_admin):
    client.force_login(tenant_admin)
    rep = SpendReport.all_objects.create(
        tenant=spend_data.tenant, name='<script>alert(1)</script>', dimension='vendor',
        measure='amount_sum', basis='actual', owner=tenant_admin)
    resp = client.get(reverse('spend_analytics:report_detail', args=[rep.pk]))
    assert resp.status_code == 200
    assert b'<script>alert(1)</script>' not in resp.content
