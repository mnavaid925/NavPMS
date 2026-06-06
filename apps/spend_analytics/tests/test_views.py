"""View-level tests: pages load, report CRUD + run, export content-types."""
import pytest
from django.urls import reverse

from apps.spend_analytics.models import SpendReport

pytestmark = pytest.mark.django_db


def test_dashboard_loads_both_bases(client, spend_data, tenant_admin):
    client.force_login(tenant_admin)
    assert client.get(reverse('spend_analytics:dashboard')).status_code == 200
    assert client.get(reverse('spend_analytics:dashboard'), {'basis': 'committed'}).status_code == 200


def test_category_pages(client, spend_data, tenant_admin):
    client.force_login(tenant_admin)
    assert client.get(reverse('spend_analytics:category_analysis')).status_code == 200
    url = reverse('spend_analytics:category_detail', args=[spend_data.cat_a.pk])
    assert client.get(url).status_code == 200


def test_maverick_page_shows_maverick_vendor(client, spend_data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.get(reverse('spend_analytics:maverick_tracking'))
    assert resp.status_code == 200
    assert b'Maverick Supplier' in resp.content


def test_report_crud_and_run(client, spend_data, tenant_admin):
    client.force_login(tenant_admin)
    assert client.get(reverse('spend_analytics:report_list')).status_code == 200

    resp = client.post(reverse('spend_analytics:report_create'), {
        'name': 'By vendor', 'dimension': 'vendor', 'measure': 'amount_sum',
        'chart_type': 'bar', 'basis': 'actual',
    })
    assert resp.status_code == 302
    rep = SpendReport.objects.get(tenant=spend_data.tenant, name='By vendor')
    assert rep.owner_id == tenant_admin.id

    detail = client.get(reverse('spend_analytics:report_detail', args=[rep.pk]))
    assert detail.status_code == 200
    rep.refresh_from_db()
    assert rep.last_run_at is not None

    resp = client.post(reverse('spend_analytics:report_edit', args=[rep.pk]), {
        'name': 'By vendor v2', 'dimension': 'vendor', 'measure': 'amount_sum',
        'chart_type': 'doughnut', 'basis': 'actual',
    })
    assert resp.status_code == 302
    rep.refresh_from_db()
    assert rep.name == 'By vendor v2'
    assert rep.chart_type == 'doughnut'

    resp = client.post(reverse('spend_analytics:report_delete', args=[rep.pk]))
    assert resp.status_code == 302
    assert not SpendReport.objects.filter(pk=rep.pk).exists()


def test_sync_now_refreshes(client, spend_data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('spend_analytics:sync_now'))
    assert resp.status_code == 302


@pytest.mark.parametrize('fmt,ctype', [
    ('csv', 'text/csv'),
    ('xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
])
def test_export_dashboard_content_types(client, spend_data, tenant_admin, fmt, ctype):
    client.force_login(tenant_admin)
    resp = client.get(reverse('spend_analytics:export_dashboard', args=[fmt]))
    assert resp.status_code == 200
    assert resp['Content-Type'] == ctype
    assert 'attachment' in resp['Content-Disposition']


def test_export_records_csv_has_header_and_rows(client, spend_data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.get(reverse('spend_analytics:export_records', args=['csv']), {'basis': 'actual'})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'Source ref' in body
    assert 'SINV-1#L1' in body


def test_export_report_csv(client, spend_data, tenant_admin):
    client.force_login(tenant_admin)
    rep = SpendReport.all_objects.create(
        tenant=spend_data.tenant, name='Cat', dimension='vendor_category',
        measure='amount_sum', basis='actual', owner=tenant_admin)
    resp = client.get(reverse('spend_analytics:export_report', args=[rep.pk, 'csv']))
    assert resp.status_code == 200
    assert resp['Content-Type'] == 'text/csv'


def test_bad_export_format_404(client, spend_data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.get(reverse('spend_analytics:export_dashboard', args=['pdf']))
    assert resp.status_code == 404
