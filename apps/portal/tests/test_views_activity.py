"""Integration tests for the Recent Activity Feed (read-only over AuditLog)."""
import pytest
from django.urls import reverse

from apps.tenants.models import AuditLog

pytestmark = pytest.mark.django_db


def test_feed_shows_only_own_rows(client_logged_in, tenant, user, other_user):
    AuditLog.all_objects.create(
        tenant=tenant, user=user, action='requisition.created', message='mine')
    AuditLog.all_objects.create(
        tenant=tenant, user=other_user, action='requisition.created',
        message='bob')
    resp = client_logged_in.get(reverse('portal:activity_feed'))
    messages = [log.message for log in resp.context['logs']]
    assert 'mine' in messages and 'bob' not in messages


def test_feed_filter_by_level(client_logged_in, tenant, user):
    AuditLog.all_objects.create(
        tenant=tenant, user=user, action='a', level='info', message='i')
    AuditLog.all_objects.create(
        tenant=tenant, user=user, action='b', level='warning', message='w')
    resp = client_logged_in.get(
        reverse('portal:activity_feed'), {'level': 'warning'})
    messages = [log.message for log in resp.context['logs']]
    assert messages == ['w']


def test_feed_is_read_only():
    """No mutating routes exist for the activity feed."""
    from apps.portal import urls
    activity_names = [
        p.name for p in urls.urlpatterns if 'activity' in (p.name or '')
    ]
    assert activity_names == ['activity_feed']
