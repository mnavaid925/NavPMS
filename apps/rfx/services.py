"""Module 7 service layer: numbering, event/response workflow, sealed-response
visibility, panel scoring, ranking, shortlisting, template cloning, and
section/question reorder."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Sum
from django.utils import timezone

from apps.tenants.services import record_audit

from .models import (
    DEFAULT_SCORED_TYPES,
    EVENT_POST_CLOSE_STATUSES,
    RfxAnswer,
    RfxEvaluation,
    RfxEvent,
    RfxInvitee,
    RfxQuestion,
    RfxResponse,
    RfxSection,
    RfxTemplate,
    RfxTemplateQuestion,
    RfxTemplateSection,
)


# ---------- Permission helpers ----------

MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
EVALUATE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer', 'approver')


def can_manage_rfx(user) -> bool:
    """Tenant admin / procurement manager / buyer can manage RFx events."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_tenant_admin', False):
        return True
    return getattr(user, 'role', '') in MANAGE_ROLES


def can_evaluate(user) -> bool:
    """Manage roles + approvers can score responses."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_tenant_admin', False):
        return True
    return getattr(user, 'role', '') in EVALUATE_ROLES


# ---------- Sealed-response visibility ----------

def response_visible_to(user, response: RfxResponse) -> bool:
    """Sealed-response gate.

    A vendor portal user can always read their own response.
    Buyers (manage or evaluate roles) can only read responses after the event
    closes (`closed`, `under_evaluation`, `completed`, `cancelled`).
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_vendor_user', False):
        return response.vendor_id == getattr(user, 'vendor_id', None)
    if not (can_manage_rfx(user) or can_evaluate(user)):
        return False
    return response.event.status in EVENT_POST_CLOSE_STATUSES


# ---------- Numbering ----------

def next_rfx_number(tenant) -> str:
    """Generate the next RFX-<SLUG>-NNNNN number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = RfxEvent.all_objects.filter(tenant=tenant).count() + 1
    number = f'RFX-{slug}-{count:05d}'
    while RfxEvent.all_objects.filter(
        tenant=tenant, event_number=number,
    ).exists():
        count += 1
        number = f'RFX-{slug}-{count:05d}'
    return number


# ---------- Event create ----------

@transaction.atomic
def create_event(*, tenant, user, **fields) -> RfxEvent:
    """Create a draft RfxEvent with an auto-assigned number."""
    event = RfxEvent.all_objects.create(
        tenant=tenant,
        event_number=next_rfx_number(tenant),
        status='draft',
        created_by=user,
        **fields,
    )
    record_audit(
        tenant=tenant, user=user,
        action='rfx.event_created',
        target_type='RfxEvent', target_id=event.pk,
        message=f'{event.event_number}: {event.title}',
    )
    return event


# ---------- Event publish validation ----------

def _scored_questions(event: RfxEvent):
    """Yield every scored question across all sections of the event."""
    return RfxQuestion.all_objects.filter(
        section__event=event, is_scored=True,
    )


def validate_event_can_publish(event: RfxEvent) -> list[str]:
    """Return a list of validation errors blocking publish; empty means OK."""
    errors = []
    if not event.sections.exists():
        errors.append('Add at least one section to the questionnaire.')
        return errors  # nothing else makes sense without sections
    if not RfxQuestion.all_objects.filter(section__event=event).exists():
        errors.append('Add at least one question.')
    if not event.invitees.exists():
        errors.append('Invite at least one vendor.')
    if not event.close_at:
        errors.append('Set a close date/time for the event.')

    scored = _scored_questions(event)
    if scored.exists():
        total_weight = sum(
            (q.weight or Decimal('0')) for q in scored
        )
        if total_weight != Decimal('100'):
            errors.append(
                f'Scored question weights must sum to 100 (currently {total_weight}).'
            )
    return errors


# ---------- Event workflow ----------

@transaction.atomic
def publish_event(event: RfxEvent, user) -> RfxEvent:
    """draft -> published, or draft -> open if publish_at <= now."""
    if event.status != 'draft':
        raise ValidationError('Only draft events can be published.')
    errors = validate_event_can_publish(event)
    if errors:
        raise ValidationError(errors)
    now = timezone.now()
    if event.publish_at and event.publish_at <= now:
        event.status = 'open'
    else:
        event.status = 'published'
    event.save(update_fields=['status', 'updated_at'])
    record_audit(
        tenant=event.tenant, user=user,
        action='rfx.event_published',
        target_type='RfxEvent', target_id=event.pk,
        message=event.status,
    )
    return event


@transaction.atomic
def open_event(event: RfxEvent, user) -> RfxEvent:
    """published|draft -> open. From draft, runs publish validation."""
    if event.status not in ('published', 'draft'):
        raise ValidationError('Only published or draft events can be opened.')
    if event.status == 'draft':
        errors = validate_event_can_publish(event)
        if errors:
            raise ValidationError(errors)
    event.status = 'open'
    if not event.publish_at:
        event.publish_at = timezone.now()
    event.save(update_fields=['status', 'publish_at', 'updated_at'])
    record_audit(
        tenant=event.tenant, user=user,
        action='rfx.event_opened',
        target_type='RfxEvent', target_id=event.pk,
    )
    return event


@transaction.atomic
def close_event(event: RfxEvent, user) -> RfxEvent:
    """open -> closed. Auto-rejects still-draft responses."""
    if event.status != 'open':
        raise ValidationError('Only open events can be closed.')
    event.status = 'closed'
    event.close_at = event.close_at or timezone.now()
    event.save(update_fields=['status', 'close_at', 'updated_at'])
    # Drafts that never made it to submitted by the deadline are abandoned.
    event.responses.filter(status='draft').update(
        status='withdrawn', withdrawn_at=timezone.now(), updated_at=timezone.now(),
    )
    record_audit(
        tenant=event.tenant, user=user,
        action='rfx.event_closed',
        target_type='RfxEvent', target_id=event.pk,
    )
    return event


@transaction.atomic
def cancel_event(event: RfxEvent, user, reason: str = '') -> RfxEvent:
    """Any non-final status -> cancelled."""
    if event.status not in (
        'draft', 'published', 'open', 'closed', 'under_evaluation',
    ):
        raise ValidationError('This event cannot be cancelled.')
    event.status = 'cancelled'
    event.cancelled_reason = (reason or '').strip() or 'No reason given'
    event.cancelled_at = timezone.now()
    event.cancelled_by = user
    event.save(update_fields=[
        'status', 'cancelled_reason', 'cancelled_at', 'cancelled_by', 'updated_at',
    ])
    # Withdraw any in-flight responses.
    event.responses.filter(status__in=('draft', 'submitted', 'under_review')).update(
        status='withdrawn', withdrawn_at=timezone.now(), updated_at=timezone.now(),
    )
    record_audit(
        tenant=event.tenant, user=user,
        action='rfx.event_cancelled',
        target_type='RfxEvent', target_id=event.pk,
        message=event.cancelled_reason,
    )
    return event


@transaction.atomic
def complete_event(event: RfxEvent, user) -> RfxEvent:
    """under_evaluation -> completed. Finalises ranks; locks shortlist decisions."""
    if event.status not in ('closed', 'under_evaluation'):
        raise ValidationError(
            'Event must be closed and under evaluation to be completed.'
        )
    rank_responses(event)
    event.status = 'completed'
    event.completed_at = timezone.now()
    event.save(update_fields=['status', 'completed_at', 'updated_at'])
    record_audit(
        tenant=event.tenant, user=user,
        action='rfx.event_completed',
        target_type='RfxEvent', target_id=event.pk,
    )
    return event


# ---------- Invitations ----------

@transaction.atomic
def invite_vendors(event: RfxEvent, vendor_ids, user) -> list[RfxInvitee]:
    """Bulk-invite vendors; ignores duplicates and blocked vendors."""
    from apps.vendors.models import Vendor

    created = []
    eligible = Vendor.all_objects.filter(
        tenant=event.tenant, pk__in=vendor_ids,
    ).exclude(status__in=('suspended', 'blacklisted', 'inactive'))
    existing_ids = set(
        event.invitees.values_list('vendor_id', flat=True),
    )
    for vendor in eligible:
        if vendor.pk in existing_ids:
            continue
        created.append(
            RfxInvitee.all_objects.create(
                tenant=event.tenant,
                event=event,
                vendor=vendor,
                invited_by=user,
                status='invited',
            )
        )
    if created:
        record_audit(
            tenant=event.tenant, user=user,
            action='rfx.vendors_invited',
            target_type='RfxEvent', target_id=event.pk,
            message=f'{len(created)} vendor(s)',
        )
    return created


def decline_invitation(invitee: RfxInvitee, user) -> RfxInvitee:
    invitee.status = 'declined'
    invitee.responded_at = timezone.now()
    invitee.save(update_fields=['status', 'responded_at', 'updated_at'])
    record_audit(
        tenant=invitee.tenant, user=user,
        action='rfx.invitation_declined',
        target_type='RfxInvitee', target_id=invitee.pk,
    )
    return invitee


# ---------- Response workflow ----------

@transaction.atomic
def start_response(event: RfxEvent, vendor, user) -> RfxResponse:
    """Vendor portal: create a draft RfxResponse with one blank RfxAnswer per question."""
    if event.status != 'open':
        raise ValidationError('This event is not accepting responses.')
    if vendor.status in ('suspended', 'blacklisted', 'inactive'):
        raise ValidationError('Your vendor account is blocked.')
    invitee = event.invitees.filter(vendor=vendor).first()
    if not invitee:
        raise ValidationError('You are not invited to this event.')

    existing = event.responses.filter(vendor=vendor).first()
    if existing:
        return existing

    response = RfxResponse.all_objects.create(
        tenant=event.tenant,
        event=event,
        vendor=vendor,
        submitted_by=user,
        status='draft',
    )
    for question in RfxQuestion.all_objects.filter(section__event=event):
        RfxAnswer.all_objects.create(
            tenant=event.tenant,
            response=response,
            question=question,
        )
    if invitee.status == 'invited':
        invitee.status = 'viewed'
        invitee.save(update_fields=['status', 'updated_at'])
    record_audit(
        tenant=event.tenant, user=user,
        action='rfx.response_started',
        target_type='RfxResponse', target_id=response.pk,
        message=f'{vendor.legal_name} on {event.event_number}',
    )
    return response


@transaction.atomic
def submit_response(response: RfxResponse, user) -> RfxResponse:
    """Validate and finalise a draft response; mark invitee as responded."""
    if response.status != 'draft':
        raise ValidationError('Only draft responses can be submitted.')
    if response.event.status != 'open':
        raise ValidationError('Responses are no longer being accepted.')

    # Required-question validation
    required_questions = RfxQuestion.all_objects.filter(
        section__event=response.event, is_required=True,
    )
    missing = []
    for question in required_questions:
        answer = response.answers.filter(question=question).first()
        if not answer or not answer.is_answered:
            missing.append(f'Q{question.position}: {question.prompt[:60]}')
    if missing:
        raise ValidationError(
            ['Required questions are missing answers:'] + missing
        )

    response.status = 'submitted'
    response.submitted_by = user
    response.submitted_at = timezone.now()
    response.save(update_fields=[
        'status', 'submitted_by', 'submitted_at', 'updated_at',
    ])
    invitee = response.event.invitees.filter(vendor=response.vendor).first()
    if invitee:
        invitee.status = 'responded'
        invitee.responded_at = timezone.now()
        invitee.save(update_fields=['status', 'responded_at', 'updated_at'])
    record_audit(
        tenant=response.tenant, user=user,
        action='rfx.response_submitted',
        target_type='RfxResponse', target_id=response.pk,
        message=f'{response.vendor.legal_name} on {response.event.event_number}',
    )
    return response


@transaction.atomic
def withdraw_response(response: RfxResponse, user) -> RfxResponse:
    """Vendor self-withdraw, only while event is open."""
    if response.event.status != 'open':
        raise ValidationError('Responses can only be withdrawn while the event is open.')
    if response.status not in ('draft', 'submitted'):
        raise ValidationError('This response cannot be withdrawn.')
    response.status = 'withdrawn'
    response.withdrawn_at = timezone.now()
    response.save(update_fields=['status', 'withdrawn_at', 'updated_at'])
    invitee = response.event.invitees.filter(vendor=response.vendor).first()
    if invitee:
        invitee.status = 'withdrawn'
        invitee.responded_at = timezone.now()
        invitee.save(update_fields=['status', 'responded_at', 'updated_at'])
    record_audit(
        tenant=response.tenant, user=user,
        action='rfx.response_withdrawn',
        target_type='RfxResponse', target_id=response.pk,
    )
    return response


# ---------- Evaluation & ranking ----------

@transaction.atomic
def record_evaluation(response: RfxResponse, question: RfxQuestion, evaluator,
                      score, comment: str = '') -> RfxEvaluation:
    """Upsert a (response, question, evaluator) score; recompute overall scores.

    Triggers the closed -> under_evaluation transition on first save.
    """
    if question.section.event_id != response.event_id:
        raise ValidationError('Question does not belong to this event.')
    if not question.is_scored:
        raise ValidationError('This question is not scored.')
    if response.event.status not in EVENT_POST_CLOSE_STATUSES:
        raise ValidationError('Responses cannot be evaluated until the event closes.')
    score_d = Decimal(str(score))
    max_score = Decimal(question.max_score or 5)
    if score_d < Decimal('0') or score_d > max_score:
        raise ValidationError(
            f'Score must be between 0 and {max_score}.'
        )

    evaluation, _ = RfxEvaluation.all_objects.update_or_create(
        tenant=response.tenant,
        response=response,
        question=question,
        evaluator=evaluator,
        defaults={'score': score_d, 'comment': comment or ''},
    )
    if response.status == 'submitted':
        response.status = 'under_review'
        response.save(update_fields=['status', 'updated_at'])
    if response.event.status == 'closed':
        response.event.status = 'under_evaluation'
        response.event.save(update_fields=['status', 'updated_at'])
    recompute_response_scores(response.event)
    return evaluation


def compute_overall_score(response: RfxResponse) -> Decimal:
    """Σ(question.weight × avg_evaluator_score / question.max_score) for scored questions."""
    scored = list(_scored_questions(response.event))
    if not scored:
        return Decimal('0.0000')

    weighted = Decimal('0')
    for question in scored:
        rows = response.evaluations.filter(question=question)
        if not rows.exists():
            continue
        avg = rows.aggregate(a=Avg('score'))['a'] or Decimal('0')
        avg_d = Decimal(str(avg))
        max_score = Decimal(question.max_score or 5)
        if max_score == 0:
            continue
        norm = avg_d / max_score
        weighted += norm * (question.weight or Decimal('0'))
    return weighted.quantize(Decimal('0.0001'))


def recompute_response_scores(event: RfxEvent) -> None:
    """Re-derive overall_score across all non-withdrawn responses on the event."""
    responses = list(event.responses.exclude(status='withdrawn'))
    for response in responses:
        response.overall_score = compute_overall_score(response)
        response.save(update_fields=['overall_score', 'updated_at'])


def rank_responses(event: RfxEvent) -> None:
    """Persist 1-based rank ordering by overall_score desc on every non-withdrawn response."""
    responses = list(
        event.responses.exclude(status='withdrawn').order_by(
            '-overall_score', 'submitted_at', 'id',
        )
    )
    for idx, response in enumerate(responses, start=1):
        if response.rank != idx:
            response.rank = idx
            response.save(update_fields=['rank', 'updated_at'])


@transaction.atomic
def shortlist_response(response: RfxResponse, user, reason: str = '') -> RfxResponse:
    """Mark a response as shortlisted (buyer decision after evaluation)."""
    if response.event.status not in ('under_evaluation', 'completed'):
        raise ValidationError(
            'Responses can only be shortlisted after evaluation begins.'
        )
    if response.status not in ('submitted', 'under_review'):
        raise ValidationError('Response is not in a shortlistable state.')
    response.status = 'shortlisted'
    response.decision_reason = (reason or '').strip()
    response.save(update_fields=['status', 'decision_reason', 'updated_at'])
    record_audit(
        tenant=response.tenant, user=user,
        action='rfx.response_shortlisted',
        target_type='RfxResponse', target_id=response.pk,
    )
    return response


@transaction.atomic
def reject_response(response: RfxResponse, user, reason: str = '') -> RfxResponse:
    """Mark a response as rejected."""
    if response.event.status not in ('under_evaluation', 'completed', 'closed'):
        raise ValidationError(
            'Responses can only be rejected after the event closes.'
        )
    if response.status in ('shortlisted',):
        raise ValidationError('Shortlisted responses cannot be directly rejected.')
    response.status = 'rejected'
    response.decision_reason = (reason or '').strip()
    response.save(update_fields=['status', 'decision_reason', 'updated_at'])
    record_audit(
        tenant=response.tenant, user=user,
        action='rfx.response_rejected',
        target_type='RfxResponse', target_id=response.pk,
        message=response.decision_reason,
    )
    return response


# ---------- Section / question reorder ----------

@transaction.atomic
def move_section(section: RfxSection, direction: str) -> RfxSection:
    """Swap a section's position with its neighbour ('up' or 'down')."""
    if direction not in ('up', 'down'):
        raise ValidationError('Direction must be "up" or "down".')
    siblings = list(section.event.sections.all())
    try:
        idx = next(i for i, s in enumerate(siblings) if s.pk == section.pk)
    except StopIteration:
        return section
    target = idx - 1 if direction == 'up' else idx + 1
    if target < 0 or target >= len(siblings):
        return section
    other = siblings[target]
    section.position, other.position = other.position, section.position
    section.save(update_fields=['position', 'updated_at'])
    other.save(update_fields=['position', 'updated_at'])
    return section


@transaction.atomic
def move_question(question: RfxQuestion, direction: str) -> RfxQuestion:
    """Swap a question's position with its neighbour within the same section."""
    if direction not in ('up', 'down'):
        raise ValidationError('Direction must be "up" or "down".')
    siblings = list(question.section.questions.all())
    try:
        idx = next(i for i, q in enumerate(siblings) if q.pk == question.pk)
    except StopIteration:
        return question
    target = idx - 1 if direction == 'up' else idx + 1
    if target < 0 or target >= len(siblings):
        return question
    other = siblings[target]
    question.position, other.position = other.position, question.position
    question.save(update_fields=['position', 'updated_at'])
    other.save(update_fields=['position', 'updated_at'])
    return question


# ---------- Defaults helper ----------

def default_is_scored(question_type: str) -> bool:
    """Return the default `is_scored` value for a question type."""
    return question_type in DEFAULT_SCORED_TYPES


# ---------- Template library ----------

@transaction.atomic
def create_event_from_template(template: RfxTemplate, user,
                               *, title: str = '', publish_at=None,
                               close_at=None) -> RfxEvent:
    """Clone a template's sections and questions into a fresh draft RfxEvent."""
    event = create_event(
        tenant=template.tenant,
        user=user,
        title=title or template.title,
        description=template.description,
        rfx_type=template.rfx_type,
        publish_at=publish_at,
        close_at=close_at,
    )
    for t_section in template.sections.all():
        section = RfxSection.all_objects.create(
            tenant=template.tenant,
            event=event,
            title=t_section.title,
            description=t_section.description,
            position=t_section.position,
        )
        for t_question in t_section.questions.all():
            RfxQuestion.all_objects.create(
                tenant=template.tenant,
                section=section,
                prompt=t_question.prompt,
                help_text=t_question.help_text,
                question_type=t_question.question_type,
                is_required=t_question.is_required,
                is_scored=t_question.is_scored,
                weight=t_question.weight,
                max_score=t_question.max_score,
                choices=list(t_question.choices or []),
                position=t_question.position,
            )
    record_audit(
        tenant=template.tenant, user=user,
        action='rfx.event_created_from_template',
        target_type='RfxEvent', target_id=event.pk,
        message=f'From template {template.title}',
    )
    return event


@transaction.atomic
def save_event_as_template(event: RfxEvent, user, *, title: str,
                           description: str = '',
                           is_shared: bool = True) -> RfxTemplate:
    """Snapshot an event's questionnaire structure into a new RfxTemplate."""
    template = RfxTemplate.all_objects.create(
        tenant=event.tenant,
        title=title,
        description=description or event.description,
        rfx_type=event.rfx_type,
        is_shared=is_shared,
        created_by=user,
    )
    for section in event.sections.all():
        t_section = RfxTemplateSection.all_objects.create(
            tenant=event.tenant,
            template=template,
            title=section.title,
            description=section.description,
            position=section.position,
        )
        for question in section.questions.all():
            RfxTemplateQuestion.all_objects.create(
                tenant=event.tenant,
                section=t_section,
                prompt=question.prompt,
                help_text=question.help_text,
                question_type=question.question_type,
                is_required=question.is_required,
                is_scored=question.is_scored,
                weight=question.weight,
                max_score=question.max_score,
                choices=list(question.choices or []),
                position=question.position,
            )
    record_audit(
        tenant=event.tenant, user=user,
        action='rfx.template_saved_from_event',
        target_type='RfxTemplate', target_id=template.pk,
        message=f'From {event.event_number}',
    )
    return template


# ---------- Analytics ----------

def event_metrics(event: RfxEvent) -> dict:
    """Per-event metrics for the analytics card."""
    invited = event.invitees.count()
    responded = event.invitees.filter(status='responded').count()
    submitted = event.responses.filter(
        status__in=('submitted', 'under_review', 'shortlisted', 'rejected'),
    ).count()
    shortlisted = event.responses.filter(status='shortlisted').count()
    response_rate = (
        (Decimal(submitted) / Decimal(invited) * Decimal('100'))
        if invited else Decimal('0')
    )
    top = event.responses.exclude(status='withdrawn').order_by(
        '-overall_score', 'submitted_at', 'id',
    ).first()
    cycle_days = None
    if event.completed_at and event.created_at:
        cycle_days = (event.completed_at - event.created_at).days
    return {
        'invited': invited,
        'responded': responded,
        'submitted': submitted,
        'shortlisted': shortlisted,
        'response_rate': response_rate.quantize(Decimal('0.01')),
        'top_vendor': top.vendor.legal_name if top else None,
        'top_score': top.overall_score if top else Decimal('0'),
        'cycle_days': cycle_days,
    }


def tenant_rfx_metrics(tenant, period_start=None, period_end=None) -> dict:
    """Tenant-wide RFx analytics for the dashboard."""
    qs = RfxEvent.all_objects.filter(tenant=tenant)
    if period_start:
        qs = qs.filter(created_at__gte=period_start)
    if period_end:
        qs = qs.filter(created_at__lte=period_end)

    counts_by_status = defaultdict(int)
    for row in qs.values('status').annotate(c=Sum('id') * 0 + 1):
        counts_by_status[row['status']] = row['c']
    counts_by_type = defaultdict(int)
    for row in qs.values('rfx_type').annotate(c=Sum('id') * 0 + 1):
        counts_by_type[row['rfx_type']] = row['c']

    invited = RfxInvitee.all_objects.filter(event__in=qs).count()
    responded = RfxInvitee.all_objects.filter(
        event__in=qs, status='responded',
    ).count()
    response_rate = (
        (Decimal(responded) / Decimal(invited) * Decimal('100'))
        if invited else Decimal('0')
    )
    return {
        'total_events': qs.count(),
        'open_events': qs.filter(status='open').count(),
        'completed_events': qs.filter(status='completed').count(),
        'counts_by_status': dict(counts_by_status),
        'counts_by_type': dict(counts_by_type),
        'invited_count': invited,
        'responded_count': responded,
        'response_rate': response_rate.quantize(Decimal('0.01')),
    }
