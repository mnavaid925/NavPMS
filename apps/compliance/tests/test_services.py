"""Service-layer tests: screening, financial monitoring, fraud detectors, policy, permissions."""
import pytest
from decimal import Decimal

from apps.compliance import services
from apps.compliance.models import (
    ComplianceScreening, FinancialRiskProfile, FinancialRiskSnapshot, FraudAlert, Policy,
    PolicyAcknowledgment,
)

pytestmark = pytest.mark.django_db


# ---------- Permissions ----------
def test_permission_matrix(tenant_admin, buyer_user, approver, requester):
    assert services.can_manage_compliance(tenant_admin)
    assert services.can_manage_compliance(buyer_user)
    assert not services.can_manage_compliance(approver)   # view-only
    assert services.can_view_compliance(approver)
    assert not services.can_view_compliance(requester)    # bounced entirely


# ---------- Screening ----------
def test_run_screening_hits_restricted_party(data, tenant, tenant_admin):
    screening = services.run_screening(tenant, vendor=data.v1, user=tenant_admin)
    assert screening.status == 'review'
    assert screening.match_count >= 1
    assert screening.matches.first().score >= 85


def test_run_screening_clear_when_no_match(data, tenant, tenant_admin):
    screening = services.run_screening(tenant, name='Totally Unlisted Co', user=tenant_admin)
    assert screening.status == 'clear'
    assert screening.match_count == 0


def test_disposition_confirmed_blocks_screening(data, tenant, tenant_admin):
    screening = services.run_screening(tenant, vendor=data.v1, user=tenant_admin)
    match = screening.matches.first()
    services.disposition_match(match, 'confirmed', tenant_admin)
    screening.refresh_from_db()
    assert screening.status == 'blocked'


def test_disposition_all_false_positive_clears(data, tenant, tenant_admin):
    screening = services.run_screening(tenant, vendor=data.v1, user=tenant_admin)
    for m in screening.matches.all():
        services.disposition_match(m, 'false_positive', tenant_admin)
    screening.refresh_from_db()
    assert screening.status == 'clear'


# ---------- Financial monitoring ----------
def test_refresh_financial_creates_profile_and_snapshot(data, tenant, tenant_admin):
    profile = services.refresh_financial_risk(tenant, data.v1, user=tenant_admin)
    assert isinstance(profile, FinancialRiskProfile)
    assert 0 <= profile.credit_score <= 100
    assert profile.band in ('low', 'medium', 'high', 'critical')
    assert FinancialRiskSnapshot.all_objects.filter(tenant=tenant, vendor=data.v1).count() == 1
    # deterministic — a second refresh keeps the same score
    again = services.refresh_financial_risk(tenant, data.v1, user=tenant_admin)
    assert again.credit_score == profile.credit_score


# ---------- Fraud detectors ----------
def test_scan_fraud_detects_all_seeded_patterns(data, tenant, tenant_admin):
    created = services.scan_fraud(tenant, actor=tenant_admin)
    assert created >= 4
    codes = set(FraudAlert.all_objects.filter(tenant=tenant).values_list('rule_code', flat=True))
    assert {'vendor_bank_conflict', 'duplicate_invoice', 'round_amount', 'split_po'} <= codes


def test_scan_fraud_is_idempotent(data, tenant, tenant_admin):
    first = services.scan_fraud(tenant, actor=tenant_admin)
    assert first >= 4
    second = services.scan_fraud(tenant, actor=tenant_admin)
    assert second == 0  # signatures dedupe — no duplicates


def test_conflict_of_interest_detector(data, tenant, tenant_admin):
    # tenant_admin email domain is acme.test; give v2 a matching contact email
    data.v2.primary_contact_email = 'sales@acme.test'
    data.v2.save(update_fields=['primary_contact_email'])
    services.scan_fraud(tenant, actor=tenant_admin)
    assert FraudAlert.all_objects.filter(
        tenant=tenant, rule_code='conflict_of_interest').exists()


def test_set_fraud_status_records_event(data, tenant, tenant_admin):
    services.scan_fraud(tenant, actor=tenant_admin)
    alert = FraudAlert.all_objects.filter(tenant=tenant).first()
    services.set_fraud_status(alert, 'confirmed', tenant_admin, note='Verified')
    alert.refresh_from_db()
    assert alert.status == 'confirmed'
    assert alert.resolved_by_id == tenant_admin.id
    assert alert.events.filter(to_status='confirmed').exists()


# ---------- Policy ----------
def test_policy_publish_and_acknowledge(tenant, tenant_admin, buyer_user):
    policy = Policy.all_objects.create(
        tenant=tenant, policy_number=services.next_policy_number(tenant), title='Conduct',
        owner=tenant_admin, requires_acknowledgment=True)
    version = services.create_policy_version(
        policy, 'Body text', tenant_admin, publish=True)
    policy.refresh_from_db()
    assert policy.status == 'published'
    assert policy.current_version_id == version.id

    ack, created = services.acknowledge_policy(version, buyer_user)
    assert created is True
    # idempotent
    ack2, created2 = services.acknowledge_policy(version, buyer_user)
    assert created2 is False
    assert PolicyAcknowledgment.all_objects.filter(
        tenant=tenant, policy_version=version).count() == 1

    stats = services.policy_ack_stats(policy)
    assert stats['acked'] == 1
    assert stats['total'] >= 2


# ---------- Cron sweep ----------
def test_scan_compliance_alerts_runs(data, tenant, tenant_admin):
    services.refresh_financial_risk(tenant, data.v1, user=tenant_admin)
    result = services.scan_compliance_alerts(tenant)
    assert set(result) == {'financial_refreshed', 'fraud_alerts', 'policy_reminders'}
    assert result['fraud_alerts'] >= 4
