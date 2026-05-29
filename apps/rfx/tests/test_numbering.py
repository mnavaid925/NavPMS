"""Reliability guard for RFx numbering (SQA defect D-05).

`next_rfx_number` is count-based, so two concurrent creates can compute the same
`event_number`. `create_event` now runs each attempt in its own atomic block and
retries on the `unique_together(tenant, event_number)` IntegrityError. We simulate
the collision by monkeypatching `next_rfx_number` to return an already-taken
number before yielding a fresh one.
"""
import pytest
from django.db import IntegrityError, transaction

from apps.rfx import services
from apps.rfx.models import RfxEvent
from apps.rfx.services import create_event

pytestmark = pytest.mark.django_db


def test_create_event_retries_on_number_collision(tenant, tenant_admin, monkeypatch):
    e1 = create_event(tenant=tenant, user=tenant_admin, title='A', rfx_type='rfi')
    taken = e1.event_number
    # Collide twice, then return a unique number on the third attempt.
    seq = iter([taken, taken, 'RFX-ACME-90001'])
    monkeypatch.setattr(services, 'next_rfx_number', lambda t: next(seq))

    e2 = create_event(tenant=tenant, user=tenant_admin, title='B', rfx_type='rfi')
    assert e2.event_number == 'RFX-ACME-90001'
    assert RfxEvent.all_objects.filter(tenant=tenant).count() == 2


def test_create_event_retries_exactly_five_times_then_raises(tenant, tenant_admin, monkeypatch):
    """Guards the retry *count* specifically: a single-attempt (pre-fix) version
    would call next_rfx_number once; the 5-attempt loop calls it exactly 5 times."""
    e1 = create_event(tenant=tenant, user=tenant_admin, title='A', rfx_type='rfi')
    calls = {'n': 0}

    def always_collide(_t):
        calls['n'] += 1
        return e1.event_number

    monkeypatch.setattr(services, 'next_rfx_number', always_collide)
    with pytest.raises(IntegrityError):
        create_event(tenant=tenant, user=tenant_admin, title='B', rfx_type='rfi')
    assert calls['n'] == 5
    assert RfxEvent.all_objects.filter(tenant=tenant, title='B').count() == 0


def test_create_event_retry_inside_outer_atomic(tenant, tenant_admin, monkeypatch):
    """The savepoint contract: a collision inside an enclosing atomic
    (create_event_from_template's pattern) rolls back only the inner savepoint and
    leaves the outer transaction usable — exercised by colliding once then succeeding."""
    e1 = create_event(tenant=tenant, user=tenant_admin, title='A', rfx_type='rfi')
    seq = iter([e1.event_number, 'RFX-ACME-91234'])
    monkeypatch.setattr(services, 'next_rfx_number', lambda t: next(seq))

    with transaction.atomic():
        e2 = create_event(tenant=tenant, user=tenant_admin, title='B', rfx_type='rfi')
        # Outer transaction still usable after the inner savepoint rollback:
        usable_count = RfxEvent.all_objects.filter(tenant=tenant).count()

    assert e2.event_number == 'RFX-ACME-91234'
    assert usable_count == 2
