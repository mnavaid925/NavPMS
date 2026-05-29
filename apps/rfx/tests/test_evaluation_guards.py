"""A04 regression guards: scoring is frozen once an event is finalised
(SQA defect D-03). Evaluations are only accepted while the event is `closed`
or `under_evaluation` — never on `completed` or `cancelled`, whose ranks are
final and would otherwise desync from a silently-mutated overall_score.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.rfx.models import RfxQuestion, RfxSection
from apps.rfx.services import (
    cancel_event, close_event, complete_event, create_event, invite_vendors,
    publish_event, record_evaluation, start_response, submit_response,
)

pytestmark = pytest.mark.django_db


def _build_closed_scored_event(tenant, admin, vendor):
    """A closed event with one scored scale question and a submitted response."""
    event = create_event(
        tenant=tenant, user=admin, title='Scoring', rfx_type='rfp',
        close_at=timezone.now() + timedelta(days=1),
    )
    sec = RfxSection.all_objects.create(tenant=tenant, event=event, title='S', position=1)
    q = RfxQuestion.all_objects.create(
        tenant=tenant, section=sec, position=1, prompt='Q', question_type='scale',
        is_required=True, is_scored=True, weight=Decimal('100'), max_score=10,
    )
    invite_vendors(event, [vendor.pk], admin)
    event.publish_at = timezone.now() - timedelta(minutes=1)
    event.save()
    publish_event(event, admin)
    resp = start_response(event, vendor, admin)
    ans = resp.answers.first(); ans.value_number = Decimal('5'); ans.save()
    submit_response(resp, admin)
    close_event(event, admin)
    return event, q, resp


# ---------- Service layer ----------

def test_cannot_evaluate_completed_event(tenant, tenant_admin, vendor_a):
    event, q, resp = _build_closed_scored_event(tenant, tenant_admin, vendor_a)
    record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=2)
    complete_event(event, tenant_admin)
    resp.refresh_from_db()
    frozen_score, frozen_rank = resp.overall_score, resp.rank
    with pytest.raises(ValidationError):
        record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=10)
    resp.refresh_from_db()
    assert resp.overall_score == frozen_score  # unchanged
    assert resp.rank == frozen_rank


def test_cannot_evaluate_cancelled_event(tenant, tenant_admin, vendor_a):
    event, q, resp = _build_closed_scored_event(tenant, tenant_admin, vendor_a)
    cancel_event(event, tenant_admin, 'scope changed')
    resp.refresh_from_db()
    with pytest.raises(ValidationError):
        record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=8)


def test_can_still_evaluate_while_under_evaluation(tenant, tenant_admin, vendor_a):
    """Positive control: the legitimate window still works."""
    event, q, resp = _build_closed_scored_event(tenant, tenant_admin, vendor_a)
    record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=4)
    event.refresh_from_db()
    assert event.status == 'under_evaluation'
    # A second evaluation while under_evaluation is accepted and recomputes.
    record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=8)
    resp.refresh_from_db()
    assert resp.overall_score == Decimal('80.0000')


# ---------- View layer ----------

def test_evaluate_view_blocks_completed_event(
    client, tenant, tenant_admin, vendor_a,
):
    event, q, resp = _build_closed_scored_event(tenant, tenant_admin, vendor_a)
    record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=3)
    complete_event(event, tenant_admin)
    client.force_login(tenant_admin)
    url = reverse('rfx:response_evaluate', args=[event.pk, resp.pk])
    resp_http = client.get(url)
    assert resp_http.status_code == 302
    assert reverse('rfx:event_detail', args=[event.pk]) in resp_http.url


def test_evaluate_view_blocks_cancelled_event(
    client, tenant, tenant_admin, vendor_a,
):
    """Cancelled is the higher-value stale-bookmark case: cancel_event withdraws
    in-flight responses, yet the evaluate page must still bounce."""
    event, q, resp = _build_closed_scored_event(tenant, tenant_admin, vendor_a)
    cancel_event(event, tenant_admin, 'scope changed')
    client.force_login(tenant_admin)
    url = reverse('rfx:response_evaluate', args=[event.pk, resp.pk])
    resp_http = client.get(url)
    assert resp_http.status_code == 302
    assert reverse('rfx:event_detail', args=[event.pk]) in resp_http.url
