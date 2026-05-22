"""Integration tests for Self-Service Reporting views."""
import pytest
from django.urls import reverse

from apps.portal.models import SavedReport

pytestmark = pytest.mark.django_db


def test_create_report_redirects_to_run(client_logged_in, tenant, user):
    resp = client_logged_in.post(reverse('portal:report_create'), {
        'name': 'My Spend', 'report_type': 'spend_by_category',
    })
    assert resp.status_code == 302
    report = SavedReport.all_objects.get(tenant=tenant, name='My Spend')
    assert resp.url == reverse('portal:report_run', args=[report.pk])


def test_run_renders_and_updates_last_run(client_logged_in, tenant, user):
    report = SavedReport.all_objects.create(
        tenant=tenant, user=user, name='R', report_type='requisition_status')
    assert report.last_run_at is None
    resp = client_logged_in.get(reverse('portal:report_run', args=[report.pk]))
    assert resp.status_code == 200
    report.refresh_from_db()
    assert report.last_run_at is not None


def test_run_empty_data_renders(client_logged_in, tenant, user):
    report = SavedReport.all_objects.create(
        tenant=tenant, user=user, name='Empty', report_type='spend_by_category')
    resp = client_logged_in.get(reverse('portal:report_run', args=[report.pk]))
    assert resp.status_code == 200
    assert resp.context['result']['values'] == []


def test_idor_cross_user_report_404(client_logged_in, tenant, other_user):
    report = SavedReport.all_objects.create(
        tenant=tenant, user=other_user, name='Bob', report_type='my_activity')
    resp = client_logged_in.get(reverse('portal:report_run', args=[report.pk]))
    assert resp.status_code == 404
