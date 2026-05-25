"""Unit tests for Module 7 model logic."""
from decimal import Decimal

import pytest

from apps.rfx.models import (
    RfxAnswer, RfxEvent, RfxQuestion, RfxResponse, RfxSection,
)

pytestmark = pytest.mark.django_db


# ---------- RfxEvent ----------

def test_event_status_default_is_draft(tenant, tenant_admin):
    e = RfxEvent.all_objects.create(
        tenant=tenant, event_number='RFX-ACME-00099',
        title='Draft', rfx_type='rfi',
    )
    assert e.status == 'draft'
    assert e.is_editable is True


def test_event_str_includes_number_and_title(draft_event):
    assert draft_event.event_number in str(draft_event)
    assert draft_event.title in str(draft_event)


def test_event_unique_number_per_tenant(tenant, tenant_admin):
    RfxEvent.all_objects.create(
        tenant=tenant, event_number='RFX-DUP-1',
        title='A', rfx_type='rfi',
    )
    with pytest.raises(Exception):
        RfxEvent.all_objects.create(
            tenant=tenant, event_number='RFX-DUP-1',
            title='B', rfx_type='rfi',
        )


def test_event_responses_are_visible_only_post_close(draft_event):
    assert draft_event.responses_are_visible is False
    draft_event.status = 'open'
    assert draft_event.responses_are_visible is False
    draft_event.status = 'closed'
    assert draft_event.responses_are_visible is True
    draft_event.status = 'under_evaluation'
    assert draft_event.responses_are_visible is True
    draft_event.status = 'completed'
    assert draft_event.responses_are_visible is True
    draft_event.status = 'cancelled'
    assert draft_event.responses_are_visible is True


def test_event_can_cancel(draft_event):
    for s in ('draft', 'published', 'open', 'closed', 'under_evaluation'):
        draft_event.status = s
        assert draft_event.can_cancel
    for s in ('completed', 'cancelled'):
        draft_event.status = s
        assert not draft_event.can_cancel


# ---------- RfxSection / RfxQuestion ----------

def test_section_ordered_by_position(tenant, draft_event):
    s2 = RfxSection.all_objects.create(tenant=tenant, event=draft_event, title='B', position=2)
    s1 = RfxSection.all_objects.create(tenant=tenant, event=draft_event, title='A', position=1)
    titles = list(draft_event.sections.values_list('title', flat=True))
    assert titles == ['A', 'B']


def test_question_choices_stored_as_list(tenant, section):
    q = RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=1,
        prompt='Pick one', question_type='single_choice',
        choices=['x', 'y', 'z'],
    )
    q.refresh_from_db()
    assert q.choices == ['x', 'y', 'z']
    assert q.is_choice_type is True


def test_question_is_choice_type_for_multi_choice_only(tenant, section):
    q = RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=1,
        prompt='Text question', question_type='text',
    )
    assert q.is_choice_type is False


# ---------- RfxAnswer.value dispatch ----------

def test_answer_value_returns_text_for_text_question(tenant, section, submitted_response):
    # submitted_response was built with one text question already; refresh it.
    response = submitted_response
    answer = response.answers.first()
    assert answer.is_answered
    assert answer.value == 'Acme'


def test_answer_value_returns_number_for_number_question(tenant, section):
    q = RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=5,
        prompt='N', question_type='number',
    )
    ans = RfxAnswer(question=q, value_number=Decimal('42'))
    assert ans.value == Decimal('42')


def test_answer_value_returns_none_when_unanswered(tenant, section, question,
                                                    open_event, vendor_c, tenant_admin):
    """An unanswered text answer should report is_answered=False."""
    response = RfxResponse.all_objects.create(
        tenant=tenant, event=open_event, vendor=vendor_c, status='draft',
    )
    ans = RfxAnswer.all_objects.create(
        tenant=tenant, response=response, question=question,
    )
    assert ans.is_answered is False
    assert ans.value is None


def test_answer_unique_per_response_question(tenant, submitted_response, question):
    """Cannot have two answers for the same (response, question) pair."""
    with pytest.raises(Exception):
        RfxAnswer.all_objects.create(
            tenant=tenant, response=submitted_response, question=question,
        )


# ---------- RfxResponse ----------

def test_response_is_editable_only_in_draft(submitted_response):
    submitted_response.status = 'draft'
    assert submitted_response.is_editable
    for s in ('submitted', 'under_review', 'shortlisted', 'rejected', 'withdrawn'):
        submitted_response.status = s
        assert not submitted_response.is_editable


def test_response_unique_per_event_vendor(tenant, open_event, vendor_a, tenant_admin):
    RfxResponse.all_objects.create(
        tenant=tenant, event=open_event, vendor=vendor_a, status='draft',
    )
    with pytest.raises(Exception):
        RfxResponse.all_objects.create(
            tenant=tenant, event=open_event, vendor=vendor_a, status='draft',
        )
