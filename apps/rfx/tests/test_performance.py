"""Performance guard for the comparison matrix (SQA defect D-09).

`response_compare` used to issue a per-cell `.filter().first()` plus a per-scored-
cell `.aggregate()`, i.e. O(questions × responses) queries. Answers and average
scores are now bulk-loaded into dicts, making the matrix build O(1) queries.

A fixed-ceiling assertion is fragile (head-room can absorb the exact N+1 it means
to catch — the original budget of 25 let both the fixed path (19) and the N+1
path (25) pass). The robust guard is **N-independence**: build a small and a large
event and assert the compare query count is identical. With bulk-loading the count
is flat; an N+1 regression makes the large event issue more queries.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.rfx.models import RfxQuestion, RfxSection
from apps.rfx.services import (
    close_event, create_event, invite_vendors, publish_event,
    record_evaluation, start_response, submit_response,
)

pytestmark = pytest.mark.django_db


def _build_closed_event(tenant, admin, vendors):
    """A closed, evaluated event with one scored + two unscored questions and one
    submitted+scored response per vendor. Structure is identical across calls; only
    the vendor count varies, so query *structure* is constant and only an N+1 would
    make the count grow with len(vendors)."""
    event = create_event(
        tenant=tenant, user=admin, title='Compare perf', rfx_type='rfp',
        close_at=timezone.now() + timedelta(days=1),
    )
    sec = RfxSection.all_objects.create(tenant=tenant, event=event, title='S', position=1)
    scored = RfxQuestion.all_objects.create(
        tenant=tenant, section=sec, position=1, prompt='Rate', question_type='scale',
        is_required=False, is_scored=True, weight=Decimal('100'), max_score=10,
    )
    RfxQuestion.all_objects.create(
        tenant=tenant, section=sec, position=2, prompt='Tell us', question_type='text',
        is_required=False, is_scored=False,
    )
    RfxQuestion.all_objects.create(
        tenant=tenant, section=sec, position=3, prompt='How many', question_type='number',
        is_required=False, is_scored=False,
    )
    invite_vendors(event, [v.pk for v in vendors], admin)
    event.publish_at = timezone.now() - timedelta(minutes=1)
    event.save()
    publish_event(event, admin)
    for v in vendors:
        resp = start_response(event, v, admin)
        ans = resp.answers.filter(question=scored).first()
        ans.value_number = Decimal('5')
        ans.save()
        submit_response(resp, admin)
    close_event(event, admin)
    # Evaluate so the per-cell average bulk-load (avg_by_rq) is exercised.
    for resp in event.responses.all():
        record_evaluation(response=resp, question=scored, evaluator=admin, score=7)
    return event


def _count_compare_queries(client, event):
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(reverse('rfx:response_compare', args=[event.pk]))
    assert resp.status_code == 200
    return len(ctx)


def test_compare_query_count_is_independent_of_response_count(
    client, tenant, tenant_admin, vendor_a, vendor_b, vendor_c,
):
    small = _build_closed_event(tenant, tenant_admin, [vendor_a])
    large = _build_closed_event(tenant, tenant_admin, [vendor_a, vendor_b, vendor_c])
    client.force_login(tenant_admin)

    q_small = _count_compare_queries(client, small)
    q_large = _count_compare_queries(client, large)

    # Bulk-loaded matrix => flat query count. A per-cell N+1 (answers and/or the
    # scored-cell aggregate) would make q_large exceed q_small.
    assert q_large == q_small, (
        f'response_compare scales with response count ({q_small} -> {q_large}); '
        f'N+1 regression in the matrix build (D-09).'
    )
