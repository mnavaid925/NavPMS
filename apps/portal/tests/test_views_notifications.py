"""Integration tests for the Task & Alert Center views."""
import pytest
from django.urls import reverse

from apps.portal.models import Notification

pytestmark = pytest.mark.django_db


def test_create_alert(client_logged_in, tenant, user):
    resp = client_logged_in.post(reverse('portal:notification_create'), {
        'category': 'info', 'priority': 'normal',
        'title': 'Heads up', 'message': 'Something happened', 'link_url': '',
    })
    assert resp.status_code == 302
    note = Notification.all_objects.get(tenant=tenant, title='Heads up')
    assert note.user == user and not note.is_read


def test_detail_marks_read(client_logged_in, notification):
    resp = client_logged_in.get(
        reverse('portal:notification_detail', args=[notification.pk]))
    assert resp.status_code == 200
    notification.refresh_from_db()
    assert notification.is_read and notification.read_at is not None


def test_toggle_read_unread(client_logged_in, notification):
    notification.mark_read()
    client_logged_in.post(
        reverse('portal:notification_mark_read', args=[notification.pk]))
    notification.refresh_from_db()
    assert not notification.is_read and notification.read_at is None


def test_mark_all_read(client_logged_in, tenant, user):
    for i in range(3):
        Notification.all_objects.create(tenant=tenant, user=user, title=f'N{i}')
    client_logged_in.post(reverse('portal:notification_mark_all_read'))
    assert Notification.all_objects.filter(
        tenant=tenant, user=user, is_read=False).count() == 0


def test_delete_notification(client_logged_in, notification):
    resp = client_logged_in.post(
        reverse('portal:notification_delete', args=[notification.pk]))
    assert resp.status_code == 302
    assert not Notification.all_objects.filter(pk=notification.pk).exists()


def test_filter_by_category_and_read(client_logged_in, tenant, user):
    Notification.all_objects.create(
        tenant=tenant, user=user, title='Appr', category='approval')
    Notification.all_objects.create(
        tenant=tenant, user=user, title='Sys', category='system')
    resp = client_logged_in.get(
        reverse('portal:notification_list'), {'category': 'approval'})
    titles = [n.title for n in resp.context['notifications']]
    assert titles == ['Appr']


def test_idor_other_user_notification_404(client_logged_in, tenant, other_user):
    note = Notification.all_objects.create(
        tenant=tenant, user=other_user, title='Private')
    resp = client_logged_in.get(
        reverse('portal:notification_detail', args=[note.pk]))
    assert resp.status_code == 404
