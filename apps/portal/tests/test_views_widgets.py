"""Integration tests for the dashboard / widget views."""
import pytest
from django.urls import reverse

from apps.portal.models import DashboardWidget

pytestmark = pytest.mark.django_db


def test_first_visit_provisions_six_widgets(client_logged_in, tenant, user):
    resp = client_logged_in.get(reverse('portal:dashboard'))
    assert resp.status_code == 200
    assert DashboardWidget.all_objects.filter(tenant=tenant, user=user).count() == 6


def test_provisioning_not_duplicated(client_logged_in, tenant, user):
    client_logged_in.get(reverse('portal:dashboard'))
    client_logged_in.get(reverse('portal:dashboard'))
    assert DashboardWidget.all_objects.filter(tenant=tenant, user=user).count() == 6


def test_create_widget(client_logged_in, tenant, user):
    resp = client_logged_in.post(reverse('portal:widget_create'), {
        'widget_type': 'my_reports', 'title': 'My Reports',
        'size': 'medium', 'position': '3', 'is_visible': 'on',
    })
    assert resp.status_code == 302
    w = DashboardWidget.all_objects.get(tenant=tenant, title='My Reports')
    assert w.user == user and w.size == 'medium'


def test_edit_widget(client_logged_in, tenant, user):
    w = DashboardWidget.all_objects.create(
        tenant=tenant, user=user, widget_type='quick_links',
        title='Links', size='small')
    client_logged_in.post(reverse('portal:widget_edit', args=[w.pk]), {
        'widget_type': 'quick_links', 'title': 'Links',
        'size': 'large', 'position': '0', 'is_visible': 'on',
    })
    w.refresh_from_db()
    assert w.size == 'large'


def test_delete_widget_post(client_logged_in, tenant, user):
    w = DashboardWidget.all_objects.create(
        tenant=tenant, user=user, widget_type='quick_links', title='X')
    resp = client_logged_in.post(reverse('portal:widget_delete', args=[w.pk]))
    assert resp.status_code == 302
    assert not DashboardWidget.all_objects.filter(pk=w.pk).exists()


def test_get_on_delete_is_noop(client_logged_in, tenant, user):
    w = DashboardWidget.all_objects.create(
        tenant=tenant, user=user, widget_type='quick_links', title='X')
    resp = client_logged_in.get(reverse('portal:widget_delete', args=[w.pk]))
    assert resp.status_code == 302
    assert DashboardWidget.all_objects.filter(pk=w.pk).exists()


def test_idor_other_user_widget_404(client_logged_in, tenant, other_user):
    """A user cannot edit another user's widget even within the same tenant."""
    w = DashboardWidget.all_objects.create(
        tenant=tenant, user=other_user, widget_type='quick_links', title='Bob')
    resp = client_logged_in.get(reverse('portal:widget_edit', args=[w.pk]))
    assert resp.status_code == 404


def test_filter_by_type(client_logged_in, tenant, user):
    DashboardWidget.all_objects.create(
        tenant=tenant, user=user, widget_type='spend_summary', title='Spend')
    DashboardWidget.all_objects.create(
        tenant=tenant, user=user, widget_type='quick_links', title='Links')
    resp = client_logged_in.get(
        reverse('portal:widget_list'), {'widget_type': 'spend_summary'})
    titles = [w.title for w in resp.context['widgets']]
    assert titles == ['Spend']
