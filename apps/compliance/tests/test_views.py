"""View-level tests: pages load, CRUD flows, actions, audit explorer/export."""
import pytest
from django.urls import reverse

from apps.compliance import services
from apps.compliance.models import (
    FraudAlert, FraudRule, Policy, RestrictedPartyEntry,
)

pytestmark = pytest.mark.django_db


def test_read_pages_load(client, data, tenant, tenant_admin):
    services.scan_fraud(tenant, actor=tenant_admin)
    services.refresh_financial_risk(tenant, data.v1, user=tenant_admin)
    client.force_login(tenant_admin)
    for name in ['compliance:dashboard', 'compliance:screening_list', 'compliance:rpe_list',
                 'compliance:financial_list', 'compliance:audit_log', 'compliance:audit_verify',
                 'compliance:fraud_rule_list', 'compliance:fraud_alert_list',
                 'compliance:policy_list', 'compliance:my_policies']:
        assert client.get(reverse(name)).status_code == 200


def test_run_screening_view(client, data, tenant, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('compliance:screening_run'), {'vendor': data.v1.pk})
    assert resp.status_code == 302
    assert client.get(reverse('compliance:screening_list')).status_code == 200


def test_rpe_crud(client, tenant, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('compliance:rpe_create'), {
        'list_name': 'OFAC-SDN', 'entity_name': 'Bad Actor Inc', 'entry_type': 'organization',
        'is_active': 'on'})
    assert resp.status_code == 302
    entry = RestrictedPartyEntry.objects.get(tenant=tenant, entity_name='Bad Actor Inc')
    resp = client.post(reverse('compliance:rpe_edit', args=[entry.pk]), {
        'list_name': 'OFAC-SDN', 'entity_name': 'Bad Actor LLC', 'entry_type': 'organization'})
    assert resp.status_code == 302
    entry.refresh_from_db()
    assert entry.entity_name == 'Bad Actor LLC'
    assert client.post(reverse('compliance:rpe_delete', args=[entry.pk])).status_code == 302
    assert not RestrictedPartyEntry.objects.filter(pk=entry.pk).exists()


def test_financial_monitor_and_refresh(client, data, tenant, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('compliance:financial_monitor'), {'vendor': data.v1.pk})
    assert resp.status_code == 302
    from apps.compliance.models import FinancialRiskProfile
    profile = FinancialRiskProfile.objects.get(tenant=tenant, vendor=data.v1)
    assert client.get(reverse('compliance:financial_detail', args=[profile.pk])).status_code == 200
    assert client.post(reverse('compliance:financial_refresh', args=[profile.pk])).status_code == 302


def test_fraud_rule_crud_and_scan(client, data, tenant, tenant_admin):
    client.force_login(tenant_admin)
    # scan creates alerts
    assert client.post(reverse('compliance:fraud_scan')).status_code == 302
    assert FraudAlert.objects.filter(tenant=tenant).exists()
    alert = FraudAlert.objects.filter(tenant=tenant).first()
    assert client.get(reverse('compliance:fraud_alert_detail', args=[alert.pk])).status_code == 200
    resp = client.post(reverse('compliance:fraud_alert_status', args=[alert.pk]),
                       {'status': 'dismissed', 'note': 'benign'})
    assert resp.status_code == 302
    alert.refresh_from_db()
    assert alert.status == 'dismissed'


def test_audit_export_csv(client, data, tenant, tenant_admin):
    services.scan_fraud(tenant, actor=tenant_admin)  # generate audit rows
    client.force_login(tenant_admin)
    resp = client.get(reverse('compliance:audit_export'))
    assert resp.status_code == 200
    assert resp['Content-Type'].startswith('text/csv')


def test_policy_lifecycle_views(client, tenant, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('compliance:policy_create'), {
        'title': 'Ethics Policy', 'category': 'ethics', 'requires_acknowledgment': 'on'})
    assert resp.status_code == 302
    policy = Policy.objects.get(tenant=tenant, title='Ethics Policy')
    # add + publish a version
    resp = client.post(reverse('compliance:policy_version_create', args=[policy.pk]), {
        'body': 'Be ethical.', 'publish': 'on'})
    assert resp.status_code == 302
    policy.refresh_from_db()
    assert policy.status == 'published'
    # acknowledge from My Policies
    resp = client.post(reverse('compliance:policy_acknowledge', args=[policy.pk]))
    assert resp.status_code == 302
    assert policy.current_version.acknowledgments.filter(user=tenant_admin).exists()


def test_login_required(client):
    resp = client.get(reverse('compliance:dashboard'))
    assert resp.status_code == 302
    assert '/accounts/login' in resp['Location']
