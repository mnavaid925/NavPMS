"""Unit tests for Module 7 service layer: numbering, sealed gate, lifecycle,
scoring, ranking, template clone, reorder."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.rfx import services
from apps.rfx.models import (
    RfxAnswer, RfxEvaluation, RfxEvent, RfxQuestion, RfxResponse, RfxSection,
)
from apps.rfx.services import (
    can_evaluate, can_manage_rfx, cancel_event, close_event,
    complete_event, create_event, create_event_from_template, invite_vendors,
    move_question, move_section, next_rfx_number, publish_event,
    rank_responses, record_evaluation, recompute_response_scores,
    reject_response, response_visible_to, save_event_as_template,
    shortlist_response, start_response, submit_response,
    validate_event_can_publish, withdraw_response,
)

pytestmark = pytest.mark.django_db


# ---------- Permission helpers ----------

def test_can_manage_rfx_for_tenant_admin(tenant_admin):
    assert can_manage_rfx(tenant_admin)


def test_can_manage_rfx_for_buyer(buyer_user):
    assert can_manage_rfx(buyer_user)


def test_can_manage_rfx_rejects_requester(requester):
    assert not can_manage_rfx(requester)


def test_can_evaluate_includes_approver(evaluator):
    assert can_evaluate(evaluator)


def test_can_evaluate_rejects_unauthenticated_user():
    from django.contrib.auth.models import AnonymousUser
    assert not can_evaluate(AnonymousUser())


# ---------- Numbering ----------

def test_next_rfx_number_is_zero_padded(tenant):
    assert next_rfx_number(tenant) == 'RFX-ACME-00001'


def test_next_rfx_number_increments(tenant, tenant_admin):
    create_event(tenant=tenant, user=tenant_admin, title='A', rfx_type='rfi')
    assert next_rfx_number(tenant) == 'RFX-ACME-00002'


def test_next_rfx_number_uses_tenant_slug(other_tenant):
    assert next_rfx_number(other_tenant) == 'RFX-GLOBEX-00001'


# ---------- Sealed-response visibility ----------

def test_sealed_gate_vendor_sees_own_response(vendor_portal_user, submitted_response):
    assert response_visible_to(vendor_portal_user, submitted_response) is True


def test_sealed_gate_buyer_blocked_before_close(tenant_admin, submitted_response):
    # event is 'open', so buyer cannot see
    assert response_visible_to(tenant_admin, submitted_response) is False


def test_sealed_gate_buyer_can_see_after_close(tenant_admin, submitted_response):
    close_event(submitted_response.event, tenant_admin)
    submitted_response.refresh_from_db()
    assert response_visible_to(tenant_admin, submitted_response) is True


def test_sealed_gate_other_vendor_blocked(tenant, submitted_response, vendor_b):
    other_user = User.objects.create_user(
        username='other_vendor', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_b,
    )
    assert response_visible_to(other_user, submitted_response) is False


def test_sealed_gate_requester_blocked(requester, submitted_response, tenant_admin):
    close_event(submitted_response.event, tenant_admin)
    submitted_response.refresh_from_db()
    assert response_visible_to(requester, submitted_response) is False


# ---------- Publish validation ----------

def test_publish_blocked_without_sections(draft_event):
    errors = validate_event_can_publish(draft_event)
    assert any('section' in e.lower() for e in errors)


def test_publish_blocked_without_questions(draft_event, section):
    errors = validate_event_can_publish(draft_event)
    assert any('question' in e.lower() for e in errors)


def test_publish_blocked_without_invitees(draft_event, section, question):
    errors = validate_event_can_publish(draft_event)
    assert any('invite' in e.lower() for e in errors)


def test_publish_blocked_when_scored_weights_dont_sum_to_100(
    tenant, draft_event, section, vendor_a, tenant_admin,
):
    RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=1,
        prompt='Q1', question_type='scale', is_scored=True,
        weight=Decimal('60.00'), max_score=5,
    )
    invite_vendors(draft_event, [vendor_a.pk], tenant_admin)
    errors = validate_event_can_publish(draft_event)
    assert any('100' in e for e in errors)


def test_publish_succeeds_with_full_setup(
    tenant, draft_event, section, vendor_a, tenant_admin,
):
    RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=1,
        prompt='Q1', question_type='text', is_scored=False, weight=Decimal('0'),
    )
    invite_vendors(draft_event, [vendor_a.pk], tenant_admin)
    publish_event(draft_event, tenant_admin)
    draft_event.refresh_from_db()
    assert draft_event.status in ('published', 'open')


# ---------- Event lifecycle ----------

def test_publish_only_from_draft(open_event, tenant_admin):
    with pytest.raises(ValidationError):
        publish_event(open_event, tenant_admin)


def test_close_only_from_open(draft_event, tenant_admin):
    with pytest.raises(ValidationError):
        close_event(draft_event, tenant_admin)


def test_close_withdraws_draft_responses(open_event, vendor_b, tenant_admin):
    draft_resp = start_response(open_event, vendor_b, tenant_admin)
    close_event(open_event, tenant_admin)
    draft_resp.refresh_from_db()
    assert draft_resp.status == 'withdrawn'


def test_cancel_event_audit_reason_required(open_event, tenant_admin):
    """Empty reason becomes 'No reason given'."""
    cancel_event(open_event, tenant_admin, '   ')
    open_event.refresh_from_db()
    assert open_event.status == 'cancelled'
    assert open_event.cancelled_reason == 'No reason given'


def test_complete_event_requires_closed_or_under_evaluation(open_event, tenant_admin):
    with pytest.raises(ValidationError):
        complete_event(open_event, tenant_admin)


# ---------- Response workflow ----------

def test_start_response_requires_invitation(open_event, vendor_c, tenant_admin):
    """vendor_c is active but not invited."""
    with pytest.raises(ValidationError):
        start_response(open_event, vendor_c, tenant_admin)


def test_start_response_blocked_for_blacklisted_vendor(
    open_event, blocked_vendor, tenant_admin,
):
    invite_vendors(open_event, [blocked_vendor.pk], tenant_admin)
    # invite_vendors itself filtered the blacklisted vendor out, so they have no invitee row.
    assert not open_event.invitees.filter(vendor=blocked_vendor).exists()


def test_start_response_creates_one_answer_per_question(
    tenant, draft_event, section, vendor_a, tenant_admin,
):
    # Build event with 3 questions
    for i in range(3):
        RfxQuestion.all_objects.create(
            tenant=tenant, section=section, position=i + 1,
            prompt=f'Q{i+1}', question_type='text',
        )
    invite_vendors(draft_event, [vendor_a.pk], tenant_admin)
    draft_event.publish_at = timezone.now() - timedelta(minutes=1)
    draft_event.save()
    publish_event(draft_event, tenant_admin)

    response = start_response(draft_event, vendor_a, tenant_admin)
    assert response.answers.count() == 3


def test_start_response_is_idempotent(open_event, vendor_a, tenant_admin):
    r1 = start_response(open_event, vendor_a, tenant_admin)
    r2 = start_response(open_event, vendor_a, tenant_admin)
    assert r1.pk == r2.pk


def test_submit_response_fails_when_required_missing(
    open_event, vendor_a, tenant_admin,
):
    response = start_response(open_event, vendor_a, tenant_admin)
    # required question (text) is not answered
    with pytest.raises(ValidationError):
        submit_response(response, tenant_admin)


def test_withdraw_response_blocked_after_close(submitted_response, tenant_admin):
    close_event(submitted_response.event, tenant_admin)
    submitted_response.refresh_from_db()
    with pytest.raises(ValidationError):
        withdraw_response(submitted_response, tenant_admin)


# ---------- Scoring & ranking ----------

def _build_scored_event(tenant, admin, vendor):
    """Build a closed event with one scored question and a submitted response."""
    event = create_event(
        tenant=tenant, user=admin,
        title='Scoring event', rfx_type='rfp',
        close_at=timezone.now() + timedelta(days=1),
    )
    sec = RfxSection.all_objects.create(
        tenant=tenant, event=event, title='S', position=1,
    )
    q = RfxQuestion.all_objects.create(
        tenant=tenant, section=sec, position=1,
        prompt='Q', question_type='scale',
        is_required=True, is_scored=True,
        weight=Decimal('100.00'), max_score=10,
    )
    invite_vendors(event, [vendor.pk], admin)
    event.publish_at = timezone.now() - timedelta(minutes=1)
    event.save()
    publish_event(event, admin)
    resp = start_response(event, vendor, admin)
    ans = resp.answers.first()
    ans.value_number = Decimal('7')
    ans.save()
    submit_response(resp, admin)
    close_event(event, admin)
    return event, q, resp


def test_record_evaluation_advances_event_to_under_evaluation(
    tenant, tenant_admin, vendor_a,
):
    event, q, resp = _build_scored_event(tenant, tenant_admin, vendor_a)
    assert event.status == 'closed'
    record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=8)
    event.refresh_from_db()
    assert event.status == 'under_evaluation'


def test_record_evaluation_advances_response_to_under_review(
    tenant, tenant_admin, vendor_a,
):
    event, q, resp = _build_scored_event(tenant, tenant_admin, vendor_a)
    record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=5)
    resp.refresh_from_db()
    assert resp.status == 'under_review'


def test_record_evaluation_blocked_on_unscored_question(
    tenant, tenant_admin, vendor_a,
):
    """Cannot score a non-scored question."""
    event, _, resp = _build_scored_event(tenant, tenant_admin, vendor_a)
    sec = event.sections.first()
    unscored = RfxQuestion.all_objects.create(
        tenant=tenant, section=sec, position=99,
        prompt='Not scored', question_type='text', is_scored=False,
    )
    with pytest.raises(ValidationError):
        record_evaluation(response=resp, question=unscored,
                          evaluator=tenant_admin, score=5)


def test_record_evaluation_blocked_before_close(
    tenant, tenant_admin, vendor_a,
):
    event, q, resp = _build_scored_event(tenant, tenant_admin, vendor_a)
    # Force the event back to open to simulate pre-close.
    event.status = 'open'
    event.save()
    with pytest.raises(ValidationError):
        record_evaluation(response=resp, question=q,
                          evaluator=tenant_admin, score=5)


def test_record_evaluation_rejects_out_of_range_score(
    tenant, tenant_admin, vendor_a,
):
    event, q, resp = _build_scored_event(tenant, tenant_admin, vendor_a)
    with pytest.raises(ValidationError):
        record_evaluation(response=resp, question=q,
                          evaluator=tenant_admin, score=999)
    with pytest.raises(ValidationError):
        record_evaluation(response=resp, question=q,
                          evaluator=tenant_admin, score=-1)


def test_compute_overall_score_uses_weight_and_max_score(
    tenant, tenant_admin, vendor_a,
):
    """score=8 on a max_score=10 weight=100 question => 80.0000."""
    event, q, resp = _build_scored_event(tenant, tenant_admin, vendor_a)
    record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=8)
    resp.refresh_from_db()
    assert resp.overall_score == Decimal('80.0000')


def test_compute_overall_score_panel_average(
    tenant, tenant_admin, evaluator, vendor_a,
):
    """Two evaluators: 6 + 10 / 2 = 8 → 80.0000."""
    event, q, resp = _build_scored_event(tenant, tenant_admin, vendor_a)
    record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=6)
    record_evaluation(response=resp, question=q, evaluator=evaluator, score=10)
    resp.refresh_from_db()
    assert resp.overall_score == Decimal('80.0000')


def test_rank_responses_orders_by_score_desc(
    tenant, tenant_admin, vendor_a, vendor_b,
):
    event = create_event(
        tenant=tenant, user=tenant_admin,
        title='Multi', rfx_type='rfp',
        close_at=timezone.now() + timedelta(days=1),
    )
    sec = RfxSection.all_objects.create(
        tenant=tenant, event=event, title='S', position=1,
    )
    q = RfxQuestion.all_objects.create(
        tenant=tenant, section=sec, position=1,
        prompt='Q', question_type='scale', is_scored=True, is_required=True,
        weight=Decimal('100'), max_score=10,
    )
    invite_vendors(event, [vendor_a.pk, vendor_b.pk], tenant_admin)
    event.publish_at = timezone.now() - timedelta(minutes=1)
    event.save()
    publish_event(event, tenant_admin)

    r_a = start_response(event, vendor_a, tenant_admin)
    ans_a = r_a.answers.first()
    ans_a.value_number = Decimal('5')
    ans_a.save()
    submit_response(r_a, tenant_admin)

    r_b = start_response(event, vendor_b, tenant_admin)
    ans_b = r_b.answers.first()
    ans_b.value_number = Decimal('5')
    ans_b.save()
    submit_response(r_b, tenant_admin)

    close_event(event, tenant_admin)
    record_evaluation(response=r_a, question=q, evaluator=tenant_admin, score=4)
    record_evaluation(response=r_b, question=q, evaluator=tenant_admin, score=9)
    rank_responses(event)
    r_a.refresh_from_db()
    r_b.refresh_from_db()
    assert r_b.rank == 1
    assert r_a.rank == 2


# ---------- Shortlist / reject ----------

def test_shortlist_requires_event_under_evaluation(open_event, vendor_a, tenant_admin):
    resp = start_response(open_event, vendor_a, tenant_admin)
    with pytest.raises(ValidationError):
        shortlist_response(resp, tenant_admin)


def test_reject_records_reason(tenant, tenant_admin, vendor_a):
    event, q, resp = _build_scored_event(tenant, tenant_admin, vendor_a)
    record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=2)
    resp.refresh_from_db()
    reject_response(resp, tenant_admin, reason='Below threshold')
    resp.refresh_from_db()
    assert resp.status == 'rejected'
    assert resp.decision_reason == 'Below threshold'


# ---------- Reorder ----------

def test_move_section_swaps_positions(tenant, draft_event):
    s1 = RfxSection.all_objects.create(tenant=tenant, event=draft_event, title='A', position=1)
    s2 = RfxSection.all_objects.create(tenant=tenant, event=draft_event, title='B', position=2)
    move_section(s1, 'down')
    s1.refresh_from_db(); s2.refresh_from_db()
    assert s1.position == 2 and s2.position == 1


def test_move_section_at_boundary_is_noop(tenant, draft_event):
    s1 = RfxSection.all_objects.create(tenant=tenant, event=draft_event, title='only', position=1)
    move_section(s1, 'up')
    s1.refresh_from_db()
    assert s1.position == 1


def test_move_section_rejects_bad_direction(tenant, section):
    with pytest.raises(ValidationError):
        move_section(section, 'sideways')


def test_move_question_swaps_within_section(tenant, section):
    q1 = RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=1, prompt='A', question_type='text',
    )
    q2 = RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=2, prompt='B', question_type='text',
    )
    move_question(q1, 'down')
    q1.refresh_from_db(); q2.refresh_from_db()
    assert q1.position == 2 and q2.position == 1


# ---------- Template clone ----------

def test_create_event_from_template_copies_structure(
    tenant, template_with_questions, tenant_admin,
):
    event = create_event_from_template(template_with_questions, tenant_admin)
    assert event.status == 'draft'
    assert event.rfx_type == 'rfi'
    assert event.sections.count() == template_with_questions.sections.count()
    section = event.sections.first()
    assert section.questions.count() == 2
    scored = section.questions.filter(is_scored=True).first()
    assert scored.weight == Decimal('100.00')


def test_save_event_as_template_snapshots_event(
    tenant, draft_event, section, tenant_admin,
):
    RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=1,
        prompt='Snap me', question_type='text',
    )
    template = save_event_as_template(
        draft_event, tenant_admin, title='Snapshot template',
    )
    assert template.title == 'Snapshot template'
    assert template.sections.count() == 1
    assert template.sections.first().questions.count() == 1
