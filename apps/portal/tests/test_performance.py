"""Query-budget guards for Module 2 (catch N+1 regressions)."""
import pytest
from django.urls import reverse

from apps.portal.models import Notification

pytestmark = pytest.mark.django_db


def test_dashboard_query_budget(client_logged_in, django_assert_max_num_queries):
    # Warm-up call provisions the 6 default widgets; measure the steady state.
    client_logged_in.get(reverse('portal:dashboard'))
    with django_assert_max_num_queries(20):
        client_logged_in.get(reverse('portal:dashboard'))


def test_notification_list_no_n_plus_one(
        client_logged_in, tenant, user, django_assert_max_num_queries):
    Notification.all_objects.bulk_create([
        Notification(tenant=tenant, user=user, title=f'N{i}') for i in range(60)
    ])
    with django_assert_max_num_queries(10):
        client_logged_in.get(reverse('portal:notification_list'))
