"""Smoke tests — GET renders of every page + invalid-form re-render branches.

These exercise the form-display and validation-failure paths that the
happy-path integration tests skip.
"""
import pytest
from django.urls import reverse

from apps.portal.models import (
    DashboardWidget, Notification, QuickRequisition, SavedReport,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('name', [
    'portal:widget_list', 'portal:widget_create',
    'portal:notification_list', 'portal:notification_create',
    'portal:requisition_list', 'portal:requisition_create',
    'portal:activity_feed', 'portal:report_list', 'portal:report_create',
])
def test_get_pages_render(client_logged_in, name):
    assert client_logged_in.get(reverse(name)).status_code == 200


def test_get_edit_pages_render(client_logged_in, tenant, user, draft_req):
    widget = DashboardWidget.all_objects.create(
        tenant=tenant, user=user, widget_type='quick_links', title='W')
    note = Notification.all_objects.create(tenant=tenant, user=user, title='N')
    report = SavedReport.all_objects.create(
        tenant=tenant, user=user, name='R', report_type='my_activity')
    for url in (
        reverse('portal:widget_edit', args=[widget.pk]),
        reverse('portal:notification_edit', args=[note.pk]),
        reverse('portal:requisition_edit', args=[draft_req.pk]),
        reverse('portal:requisition_detail', args=[draft_req.pk]),
        reverse('portal:report_edit', args=[report.pk]),
    ):
        assert client_logged_in.get(url).status_code == 200


def test_invalid_widget_create_rerenders(client_logged_in):
    resp = client_logged_in.post(reverse('portal:widget_create'), {'title': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_invalid_notification_create_rerenders(client_logged_in):
    resp = client_logged_in.post(
        reverse('portal:notification_create'), {'title': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_invalid_requisition_create_rerenders(client_logged_in):
    resp = client_logged_in.post(
        reverse('portal:requisition_create'), {'title': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_invalid_report_create_rerenders(client_logged_in):
    resp = client_logged_in.post(reverse('portal:report_create'), {'name': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_invalid_item_add_shows_error(client_logged_in, draft_req):
    """A bad line item posts back to the detail page with an error message."""
    resp = client_logged_in.post(
        reverse('portal:requisition_item_add', args=[draft_req.pk]),
        {'name': '', 'quantity': '-1', 'unit': 'u', 'unit_price': '1'},
        follow=True)
    assert resp.status_code == 200
    assert not draft_req.items.exists()


def test_widget_invalid_edit_rerenders(client_logged_in, tenant, user):
    widget = DashboardWidget.all_objects.create(
        tenant=tenant, user=user, widget_type='quick_links', title='W')
    resp = client_logged_in.post(
        reverse('portal:widget_edit', args=[widget.pk]), {'title': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_notification_invalid_edit_rerenders(client_logged_in, notification):
    resp = client_logged_in.post(
        reverse('portal:notification_edit', args=[notification.pk]),
        {'title': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_requisition_invalid_edit_rerenders(client_logged_in, draft_req):
    resp = client_logged_in.post(
        reverse('portal:requisition_edit', args=[draft_req.pk]), {'title': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_report_invalid_edit_rerenders(client_logged_in, tenant, user):
    report = SavedReport.all_objects.create(
        tenant=tenant, user=user, name='R', report_type='my_activity')
    resp = client_logged_in.post(
        reverse('portal:report_edit', args=[report.pk]), {'name': ''})
    assert resp.status_code == 200 and resp.context['form'].errors


def test_list_filters_apply(client_logged_in, tenant, user):
    DashboardWidget.all_objects.create(
        tenant=tenant, user=user, widget_type='quick_links', title='Hidden',
        is_visible=False)
    QuickRequisition.all_objects.create(
        tenant=tenant, user=user, number='QR-ACME-09001', title='Travel',
        category='travel', status='submitted')
    assert client_logged_in.get(
        reverse('portal:widget_list'), {'visible': 'hidden'}).status_code == 200
    resp = client_logged_in.get(
        reverse('portal:requisition_list'),
        {'q': 'Travel', 'status': 'submitted', 'category': 'travel'})
    assert [r.title for r in resp.context['requisitions']] == ['Travel']


def test_notification_list_filters_apply(client_logged_in, tenant, user):
    Notification.all_objects.create(
        tenant=tenant, user=user, title='Urgent', priority='urgent',
        message='check this')
    resp = client_logged_in.get(reverse('portal:notification_list'), {
        'q': 'check', 'priority': 'urgent', 'read': 'unread'})
    assert [n.title for n in resp.context['notifications']] == ['Urgent']


def test_report_list_filter_applies(client_logged_in, tenant, user):
    SavedReport.all_objects.create(
        tenant=tenant, user=user, name='Spend', report_type='spend_by_month')
    resp = client_logged_in.get(reverse('portal:report_list'), {
        'q': 'Spend', 'report_type': 'spend_by_month'})
    assert [r.name for r in resp.context['reports']] == ['Spend']
