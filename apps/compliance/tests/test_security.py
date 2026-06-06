"""Security tests: cross-tenant isolation + role-based access control."""
import pytest
from django.urls import reverse

from apps.compliance import services
from apps.compliance.models import Policy

pytestmark = pytest.mark.django_db


def test_requester_is_bounced_from_view_and_manage(client, data, requester):
    """A requester holds neither view nor manage rights (the D-01 lesson)."""
    client.force_login(requester)
    # read page -> redirected away
    resp = client.get(reverse('compliance:dashboard'))
    assert resp.status_code == 302
    # manage action -> redirected away (and no scan happened)
    resp = client.post(reverse('compliance:fraud_scan'))
    assert resp.status_code == 302


def test_approver_can_view_but_not_manage(client, data, approver):
    client.force_login(approver)
    assert client.get(reverse('compliance:fraud_alert_list')).status_code == 200
    # manage-only: creating an RPE entry is refused (redirect, nothing created)
    from apps.compliance.models import RestrictedPartyEntry
    before = RestrictedPartyEntry.objects.count()
    resp = client.post(reverse('compliance:rpe_create'), {
        'list_name': 'X', 'entity_name': 'Y', 'entry_type': 'organization'})
    assert resp.status_code == 302
    assert RestrictedPartyEntry.objects.count() == before


def test_cross_tenant_screening_is_isolated(client, data, tenant, tenant_admin, intruder):
    screening = services.run_screening(tenant, vendor=data.v1, user=tenant_admin)
    client.force_login(intruder)  # admin of a different tenant
    resp = client.get(reverse('compliance:screening_detail', args=[screening.pk]))
    assert resp.status_code == 404


def test_cross_tenant_policy_is_isolated(client, tenant, tenant_admin, intruder):
    policy = Policy.all_objects.create(
        tenant=tenant, policy_number='POL-ACME-00001', title='Secret', owner=tenant_admin)
    client.force_login(intruder)
    assert client.get(reverse('compliance:policy_detail', args=[policy.pk])).status_code == 404
