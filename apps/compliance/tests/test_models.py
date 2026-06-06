"""Model-level tests: numbering, properties, band mapping, constraints."""
import pytest
from decimal import Decimal

from django.db import IntegrityError

from apps.compliance import services
from apps.compliance.models import (
    FraudAlert, FraudRule, Policy, risk_band_from_score,
)

pytestmark = pytest.mark.django_db


def test_numbering_is_gap_free_and_prefixed(tenant):
    assert services.next_screening_number(tenant).startswith('SCR-ACME-')
    assert services.next_fraud_number(tenant).startswith('FRD-ACME-')
    assert services.next_policy_number(tenant).startswith('POL-ACME-')
    # creating one bumps the next
    Policy.all_objects.create(
        tenant=tenant, policy_number=services.next_policy_number(tenant), title='P')
    assert services.next_policy_number(tenant).endswith('00002')


@pytest.mark.parametrize('score,band', [
    (95, 'low'), (75, 'low'), (60, 'medium'), (50, 'medium'),
    (40, 'high'), (25, 'high'), (10, 'critical'), (0, 'critical')])
def test_risk_band_from_score(score, band):
    assert risk_band_from_score(score) == band


def test_badge_color_properties(tenant):
    rule = FraudRule.all_objects.create(
        tenant=tenant, code='round_amount', name='R', severity='critical')
    assert rule.severity_color == 'danger'
    alert = FraudAlert.all_objects.create(
        tenant=tenant, alert_number='FRD-1', severity='critical', status='open',
        summary='x', signature='sig-1')
    assert alert.severity_color == 'danger'
    assert alert.status_color == 'danger'
    assert alert.is_open is True


def test_fraud_alert_signature_unique_per_tenant(tenant):
    FraudAlert.all_objects.create(
        tenant=tenant, alert_number='FRD-1', summary='a', signature='dup')
    with pytest.raises(IntegrityError):
        FraudAlert.all_objects.create(
            tenant=tenant, alert_number='FRD-2', summary='b', signature='dup')


def test_fraud_rule_code_unique_per_tenant(tenant):
    FraudRule.all_objects.create(tenant=tenant, code='split_po', name='A')
    with pytest.raises(IntegrityError):
        FraudRule.all_objects.create(tenant=tenant, code='split_po', name='B')


def test_policy_str_and_status_helpers(tenant):
    p = Policy.all_objects.create(
        tenant=tenant, policy_number='POL-ACME-00001', title='Code', status='draft')
    assert 'POL-ACME-00001' in str(p)
    assert p.is_editable is True
    assert p.is_published is False
    assert p.status_color == 'secondary'
