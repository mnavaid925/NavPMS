"""A01 regression guards for the sealed-response surface (SQA defects D-01, D-02).

These lock in the fix that gives `response_list`, `response_compare` and the two
analytics views the same manage/evaluate role gate that `response_detail`
already enforces. Before the fix a low-privilege `requester` could read the full
competitor bid set once an event closed.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.rfx.models import RfxQuestion, RfxSection
from apps.rfx.services import (
    close_event, create_event, invite_vendors, publish_event,
    record_evaluation, start_response, submit_response,
)

pytestmark = pytest.mark.django_db


def _closed_scored_event(tenant, admin, vendor, score):
    """Closed (under_evaluation) event with one scored response carrying a known
    overall_score, for asserting score leakage on read surfaces."""
    event = create_event(
        tenant=tenant, user=admin, title='Sealed scoring', rfx_type='rfp',
        close_at=timezone.now() + timedelta(days=1),
    )
    sec = RfxSection.all_objects.create(tenant=tenant, event=event, title='S', position=1)
    q = RfxQuestion.all_objects.create(
        tenant=tenant, section=sec, position=1, prompt='Rate', question_type='scale',
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
    record_evaluation(response=resp, question=q, evaluator=admin, score=score)
    return event


# ---------- D-01: response list / compare ----------

def test_requester_cannot_list_sealed_responses(
    client, requester, open_event, submitted_response, tenant_admin,
):
    close_event(open_event, tenant_admin)  # responses_are_visible == True
    client.force_login(requester)           # role='requester' — no manage/evaluate
    resp = client.get(reverse('rfx:response_list', args=[open_event.pk]))
    assert resp.status_code == 302
    assert reverse('rfx:event_detail', args=[open_event.pk]) in resp.url


def test_requester_cannot_compare_sealed_responses(
    client, requester, open_event, submitted_response, tenant_admin,
):
    close_event(open_event, tenant_admin)
    client.force_login(requester)
    resp = client.get(reverse('rfx:response_compare', args=[open_event.pk]))
    # 302 body is empty, so a content canary here would be vacuous — assert the
    # denial via status + redirect target instead (see the bounced test below
    # for the followed-body content check).
    assert resp.status_code == 302
    assert reverse('rfx:event_detail', args=[open_event.pk]) in resp.url


def test_requester_bounced_from_responses_to_event_detail(
    client, requester, open_event, submitted_response, tenant_admin,
):
    """The requester is bounced to event_detail and never reaches the responses
    table. We assert on the redirect chain rather than a body canary: event_detail
    legitimately shows the *invitee* vendor name, so the vendor's legal_name is a
    false-positive canary there (see lessons.md, 2026-05-26)."""
    close_event(open_event, tenant_admin)
    client.force_login(requester)
    resp = client.get(
        reverse('rfx:response_list', args=[open_event.pk]), follow=True,
    )
    assert resp.redirect_chain  # was redirected, not served
    assert resp.redirect_chain[-1][0].endswith(
        reverse('rfx:event_detail', args=[open_event.pk]),
    )
    # The responses table (its "Decision" column header) never rendered.
    assert b'>Decision<' not in resp.content


# ---------- D-02: analytics ----------

def test_requester_cannot_open_analytics_dashboard(client, requester, draft_event):
    client.force_login(requester)
    resp = client.get(reverse('rfx:analytics_dashboard'))
    assert resp.status_code == 302
    assert reverse('rfx:event_list') in resp.url


def test_requester_cannot_open_event_report(client, requester, draft_event):
    client.force_login(requester)
    resp = client.get(reverse('rfx:analytics_event_report', args=[draft_event.pk]))
    assert resp.status_code == 302
    assert reverse('rfx:event_detail', args=[draft_event.pk]) in resp.url


# ---------- Positive: legitimate roles still work ----------

def test_evaluator_can_compare_after_close(
    client, evaluator, open_event, submitted_response, tenant_admin,
):
    close_event(open_event, tenant_admin)
    client.force_login(evaluator)  # role='approver' -> can_evaluate
    resp = client.get(reverse('rfx:response_compare', args=[open_event.pk]))
    assert resp.status_code == 200
    assert b'Acme IT Solutions' in resp.content  # matrix renders vendor column


def test_manager_can_list_after_close(
    client, tenant_admin, open_event, submitted_response,
):
    close_event(open_event, tenant_admin)
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:response_list', args=[open_event.pk]))
    assert resp.status_code == 200
    assert b'Acme IT Solutions' in resp.content


def test_manager_can_open_analytics(client, tenant_admin, draft_event):
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:analytics_dashboard'))
    assert resp.status_code == 200


@pytest.mark.parametrize('role_fixture', ['buyer_user', 'procurement_manager'])
def test_manage_role_membership_can_list_after_close(
    role_fixture, request, client, open_event, submitted_response, tenant_admin,
):
    """Exercise the MANAGE_ROLES membership branch of can_manage_rfx through the
    view gate — tenant_admin alone only covers the is_tenant_admin short-circuit."""
    close_event(open_event, tenant_admin)
    user = request.getfixturevalue(role_fixture)
    client.force_login(user)
    resp = client.get(reverse('rfx:response_list', args=[open_event.pk]))
    assert resp.status_code == 200
    assert b'Acme IT Solutions' in resp.content


# ---------- event_detail must not leak sealed scores/ranks (D-01 follow-up) ----------

def test_event_detail_hides_scores_from_requester(client, tenant, requester, tenant_admin, vendor_a):
    """A requester may open event_detail (it is not role-gated) but the Responses
    tab must NOT render the sealed score/rank table for them."""
    event = _closed_scored_event(tenant, tenant_admin, vendor_a, score=Decimal('8.75'))
    client.force_login(requester)
    resp = client.get(reverse('rfx:event_detail', args=[event.pk]))
    assert resp.status_code == 200
    assert b'87.50' not in resp.content            # overall_score 8.75/10*100
    assert b'>Score</th>' not in resp.content       # results-table header
    assert b'Responses are restricted' in resp.content


def test_event_detail_shows_scores_to_manager(client, tenant, tenant_admin, vendor_a):
    event = _closed_scored_event(tenant, tenant_admin, vendor_a, score=Decimal('8.75'))
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:event_detail', args=[event.pk]))
    assert resp.status_code == 200
    assert b'87.50' in resp.content                 # manager sees the scored table
    assert b'>Score</th>' in resp.content
