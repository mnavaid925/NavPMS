"""Module 7 vendor-portal views: RFx invitations, event read-only, response form."""
from decimal import Decimal, InvalidOperation
from datetime import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.vendors.decorators import vendor_required

from .forms import MAX_ANSWER_FILE_BYTES
from .models import (
    CHOICE_QUESTION_TYPES,
    RfxAnswer,
    RfxEvent,
    RfxInvitee,
    RfxQuestion,
    RfxResponse,
)
from .services import (
    decline_invitation,
    start_response,
    submit_response,
    withdraw_response,
)


@vendor_required
def portal_invitations(request):
    """List RFx invitations for the current vendor portal user."""
    vendor = request.user.vendor
    invitations = RfxInvitee.all_objects.filter(
        vendor=vendor,
    ).select_related('event').order_by('-invited_at')
    return render(request, 'vendor_portal/rfx/inbox.html', {
        'invitations': invitations, 'vendor': vendor,
    })


@vendor_required
def portal_event_view(request, event_pk):
    """Read-only RFx event view for an invited vendor."""
    vendor = request.user.vendor
    event = get_object_or_404(
        RfxEvent, pk=event_pk, tenant=vendor.tenant,
    )
    invitee = event.invitees.filter(vendor=vendor).first()
    if not invitee:
        messages.error(request, 'You are not invited to this event.')
        return redirect('vendor_portal:rfx_inbox')
    if invitee.status == 'invited':
        invitee.status = 'viewed'
        invitee.responded_at = timezone.now()
        invitee.save(update_fields=['status', 'responded_at', 'updated_at'])

    sections = event.sections.prefetch_related('questions').all()
    documents = event.documents.all()
    my_response = event.responses.filter(vendor=vendor).first()
    return render(request, 'vendor_portal/rfx/event.html', {
        'event': event, 'invitee': invitee,
        'sections': sections, 'documents': documents,
        'my_response': my_response,
    })


@vendor_required
def portal_response_start(request, event_pk):
    """Create a draft RfxResponse for the current vendor (idempotent)."""
    vendor = request.user.vendor
    event = get_object_or_404(RfxEvent, pk=event_pk, tenant=vendor.tenant)
    if request.method != 'POST':
        return redirect('vendor_portal:rfx_event', event_pk=event.pk)
    try:
        response = start_response(event, vendor, request.user)
        messages.success(request, 'Draft response created. Fill in your answers to submit.')
        return redirect(
            'vendor_portal:rfx_response_edit', event_pk=event.pk, rpk=response.pk,
        )
    except ValidationError as exc:
        for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
            messages.error(request, err)
        return redirect('vendor_portal:rfx_event', event_pk=event.pk)


def _save_answer_from_post(answer: RfxAnswer, question: RfxQuestion,
                           post, files) -> str:
    """Mutate an RfxAnswer based on POST/FILES; return error message or ''."""
    qtype = question.question_type
    prefix = f'answer_{question.pk}_'

    if qtype in ('text', 'longtext'):
        answer.value_text = (post.get(prefix + 'text') or '').strip()
    elif qtype == 'yes_no':
        raw = (post.get(prefix + 'text') or '').strip().lower()
        if raw and raw not in ('yes', 'no'):
            return f'Q{question.position}: pick Yes or No.'
        answer.value_text = raw
    elif qtype == 'number':
        raw = (post.get(prefix + 'number') or '').strip()
        if raw == '':
            answer.value_number = None
        else:
            try:
                answer.value_number = Decimal(raw)
            except (InvalidOperation, ValueError):
                return f'Q{question.position}: "{raw}" is not a number.'
    elif qtype == 'scale':
        raw = (post.get(prefix + 'number') or '').strip()
        if raw == '':
            answer.value_number = None
        else:
            try:
                value = Decimal(raw)
            except (InvalidOperation, ValueError):
                return f'Q{question.position}: "{raw}" is not a number.'
            max_score = Decimal(question.max_score or 5)
            if value < 0 or value > max_score:
                return f'Q{question.position}: pick a value between 0 and {max_score}.'
            answer.value_number = value
    elif qtype == 'date':
        raw = (post.get(prefix + 'date') or '').strip()
        if raw == '':
            answer.value_date = None
        else:
            try:
                answer.value_date = datetime.strptime(raw, '%Y-%m-%d').date()
            except ValueError:
                return f'Q{question.position}: invalid date (expected YYYY-MM-DD).'
    elif qtype in CHOICE_QUESTION_TYPES:
        selected = post.getlist(prefix + 'choices')
        if qtype == 'single_choice':
            selected = selected[:1]
        valid_options = list(question.choices or [])
        # Drop anything that is not one of the declared options
        selected = [s for s in selected if s in valid_options]
        answer.value_choices = selected
    elif qtype == 'file':
        uploaded = files.get(prefix + 'file')
        if uploaded:
            if uploaded.size > MAX_ANSWER_FILE_BYTES:
                return f'Q{question.position}: file too large (5 MB max).'
            answer.value_file = uploaded
        if post.get(prefix + 'clear') == 'yes':
            answer.value_file = None

    return ''


@vendor_required
def portal_response_edit(request, event_pk, rpk):
    """Fill in / edit answers on a draft RfxResponse."""
    vendor = request.user.vendor
    event = get_object_or_404(RfxEvent, pk=event_pk, tenant=vendor.tenant)
    response = get_object_or_404(
        RfxResponse, pk=rpk, event=event, vendor=vendor, tenant=vendor.tenant,
    )
    locked = response.status != 'draft'

    questions = list(
        RfxQuestion.all_objects.filter(section__event=event)
        .select_related('section')
        .order_by('section__position', 'position', 'id')
    )
    answers_by_qid = {a.question_id: a for a in response.answers.all()}
    # Backfill any missing answer rows (e.g. if questions were added after start_response).
    for q in questions:
        if q.pk not in answers_by_qid:
            answer = RfxAnswer.all_objects.create(
                tenant=vendor.tenant, response=response, question=q,
            )
            answers_by_qid[q.pk] = answer

    if request.method == 'POST' and not locked:
        errors = []
        for question in questions:
            answer = answers_by_qid[question.pk]
            err = _save_answer_from_post(
                answer, question, request.POST, request.FILES,
            )
            if err:
                errors.append(err)
                continue
            answer.save()
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            messages.success(request, 'Draft answers saved.')
        return redirect(
            'vendor_portal:rfx_response_edit', event_pk=event.pk, rpk=response.pk,
        )

    sections = event.sections.prefetch_related('questions').all()
    return render(request, 'vendor_portal/rfx/response.html', {
        'event': event, 'response': response, 'sections': sections,
        'answers': answers_by_qid, 'locked': locked,
    })


@vendor_required
def portal_response_submit(request, event_pk, rpk):
    vendor = request.user.vendor
    event = get_object_or_404(RfxEvent, pk=event_pk, tenant=vendor.tenant)
    response = get_object_or_404(
        RfxResponse, pk=rpk, event=event, vendor=vendor, tenant=vendor.tenant,
    )
    if request.method == 'POST':
        try:
            submit_response(response, request.user)
            messages.success(request, 'Response submitted. Good luck!')
            return redirect('vendor_portal:rfx_my_responses')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect(
        'vendor_portal:rfx_response_edit', event_pk=event.pk, rpk=response.pk,
    )


@vendor_required
def portal_response_withdraw(request, event_pk, rpk):
    vendor = request.user.vendor
    event = get_object_or_404(RfxEvent, pk=event_pk, tenant=vendor.tenant)
    response = get_object_or_404(
        RfxResponse, pk=rpk, event=event, vendor=vendor, tenant=vendor.tenant,
    )
    if request.method == 'POST':
        try:
            withdraw_response(response, request.user)
            messages.success(request, 'Response withdrawn.')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('vendor_portal:rfx_my_responses')


@vendor_required
def portal_my_responses(request):
    vendor = request.user.vendor
    responses = RfxResponse.all_objects.filter(vendor=vendor).select_related(
        'event',
    ).order_by('-created_at')
    return render(request, 'vendor_portal/rfx/my_responses.html', {
        'responses': responses, 'vendor': vendor,
    })


@vendor_required
def portal_invitation_decline(request, ipk):
    vendor = request.user.vendor
    invitee = get_object_or_404(
        RfxInvitee, pk=ipk, vendor=vendor, tenant=vendor.tenant,
    )
    if request.method == 'POST':
        try:
            decline_invitation(invitee, request.user)
            messages.success(request, 'Invitation declined.')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('vendor_portal:rfx_inbox')
