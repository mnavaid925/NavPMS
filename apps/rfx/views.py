"""Module 7 views (buyer side): events, sections, questions, invitees,
documents, responses, evaluation, decisions, templates, analytics."""
from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from apps.vendors.decorators import vendor_blocked
from apps.vendors.models import VendorCategory

from .forms import (
    CancelEventForm,
    InviteVendorsForm,
    ResponseDecisionForm,
    RfxDocumentForm,
    RfxEventForm,
    RfxQuestionForm,
    RfxSectionForm,
    RfxTemplateForm,
    RfxTemplateQuestionForm,
    RfxTemplateSectionForm,
    SaveAsTemplateForm,
    UseTemplateForm,
)
from .models import (
    EVENT_STATUS_CHOICES,
    RFX_TYPE_CHOICES,
    RfxAnswer,
    RfxDocument,
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
from .services import (
    can_evaluate,
    can_manage_rfx,
    cancel_event,
    close_event,
    complete_event,
    create_event,
    create_event_from_template,
    event_metrics,
    invite_vendors,
    move_question,
    move_section,
    open_event,
    publish_event,
    rank_responses,
    record_evaluation,
    recompute_response_scores,
    reject_response,
    response_visible_to,
    save_event_as_template,
    shortlist_response,
    tenant_rfx_metrics,
    validate_event_can_publish,
)


# ---------- Permission helpers ----------

def _require_tenant(request):
    if not request.tenant:
        return redirect('tenants:onboarding_start')
    return None


def _require_manage(request):
    if not can_manage_rfx(request.user):
        messages.error(request, 'You do not have permission to manage RFx events.')
        return redirect('rfx:event_list')
    return None


# ---------- Event CRUD ----------

@login_required
@vendor_blocked
def event_list(request):
    if (r := _require_tenant(request)):
        return r

    qs = RfxEvent.objects.filter(tenant=request.tenant).select_related(
        'category', 'created_by',
    )
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(event_number__icontains=q) | Q(title__icontains=q)
            | Q(description__icontains=q)
        )
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    rfx_type = request.GET.get('rfx_type', '')
    if rfx_type:
        qs = qs.filter(rfx_type=rfx_type)
    category_id = request.GET.get('category', '')
    if category_id:
        qs = qs.filter(category_id=category_id)

    stats = {
        'total': RfxEvent.objects.filter(tenant=request.tenant).count(),
        'open': RfxEvent.objects.filter(
            tenant=request.tenant, status='open',
        ).count(),
        'draft': RfxEvent.objects.filter(
            tenant=request.tenant, status='draft',
        ).count(),
        'completed': RfxEvent.objects.filter(
            tenant=request.tenant, status='completed',
        ).count(),
    }
    return render(request, 'rfx/events/list.html', {
        'events': qs.order_by('-created_at'),
        'status_choices': EVENT_STATUS_CHOICES,
        'type_choices': RFX_TYPE_CHOICES,
        'categories': VendorCategory.objects.filter(
            tenant=request.tenant, is_active=True,
        ),
        'stats': stats,
        'can_manage': can_manage_rfx(request.user),
    })


@login_required
@vendor_blocked
def event_create(request):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r

    if request.method == 'POST':
        form = RfxEventForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            event = create_event(
                tenant=request.tenant,
                user=request.user,
                **form.cleaned_data,
            )
            messages.success(request, f'Event {event.event_number} created as draft.')
            return redirect('rfx:event_detail', pk=event.pk)
    else:
        form = RfxEventForm(tenant=request.tenant)
    return render(request, 'rfx/events/form.html', {
        'form': form, 'title': 'New RFx Event',
    })


@login_required
@vendor_blocked
def event_detail(request, pk):
    if (r := _require_tenant(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)

    sections = event.sections.prefetch_related('questions').all()
    invitees = event.invitees.select_related('vendor').all()
    documents = event.documents.all()
    responses = event.responses.select_related('vendor').all()

    scored_q = RfxQuestion.objects.filter(
        section__event=event, is_scored=True,
    )
    scored_weight_total = sum((q.weight or Decimal('0')) for q in scored_q)

    can_view_responses = event.responses_are_visible and (
        can_manage_rfx(request.user) or can_evaluate(request.user)
    )
    publish_errors = (
        validate_event_can_publish(event) if event.status == 'draft' else []
    )

    section_form = RfxSectionForm()
    question_form = RfxQuestionForm()
    invitee_form = InviteVendorsForm(tenant=request.tenant, event=event)
    document_form = RfxDocumentForm()
    cancel_form = CancelEventForm()
    save_template_form = SaveAsTemplateForm(initial={
        'title': f'{event.title} (template)',
    })
    metrics = event_metrics(event)

    return render(request, 'rfx/events/detail.html', {
        'event': event,
        'sections': sections,
        'invitees': invitees,
        'documents': documents,
        'responses': responses,
        'scored_weight_total': scored_weight_total,
        'section_form': section_form,
        'question_form': question_form,
        'invitee_form': invitee_form,
        'document_form': document_form,
        'cancel_form': cancel_form,
        'save_template_form': save_template_form,
        'metrics': metrics,
        'can_manage': can_manage_rfx(request.user),
        'can_evaluate': can_evaluate(request.user),
        'can_view_responses': can_view_responses,
        'publish_errors': publish_errors,
    })


@login_required
@vendor_blocked
def event_edit(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if not event.is_editable:
        messages.error(request, 'Only draft events can be edited.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = RfxEventForm(request.POST, instance=event, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, f'Event {event.event_number} updated.')
            return redirect('rfx:event_detail', pk=event.pk)
    else:
        form = RfxEventForm(instance=event, tenant=request.tenant)
    return render(request, 'rfx/events/form.html', {
        'form': form, 'title': f'Edit {event.event_number}', 'event': event,
    })


@login_required
@vendor_blocked
def event_delete(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if not event.is_editable:
        messages.error(request, 'Only draft events can be deleted.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        number = event.event_number
        event.delete()
        messages.success(request, f'Event {number} deleted.')
    return redirect('rfx:event_list')


# ---------- Event lifecycle actions ----------

def _flash_errors(request, exc):
    for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
        messages.error(request, err)


@login_required
@vendor_blocked
def event_publish(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            publish_event(event, request.user)
            messages.success(request, f'Event {event.event_number} published ({event.status}).')
        except ValidationError as exc:
            _flash_errors(request, exc)
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def event_open(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            open_event(event, request.user)
            messages.success(request, f'Event {event.event_number} is now open for responses.')
        except ValidationError as exc:
            _flash_errors(request, exc)
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def event_close(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            close_event(event, request.user)
            messages.success(request, f'Event {event.event_number} closed. Responses are now visible.')
        except ValidationError as exc:
            _flash_errors(request, exc)
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def event_cancel(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = CancelEventForm(request.POST)
        if form.is_valid():
            try:
                cancel_event(event, request.user, form.cleaned_data['reason'])
                messages.success(request, f'Event {event.event_number} cancelled.')
            except ValidationError as exc:
                _flash_errors(request, exc)
        else:
            messages.error(request, 'Please provide a reason for cancellation.')
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def event_complete(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            complete_event(event, request.user)
            messages.success(request, f'Event {event.event_number} completed. Ranks are final.')
        except ValidationError as exc:
            _flash_errors(request, exc)
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def event_save_as_template(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = SaveAsTemplateForm(request.POST)
        if form.is_valid():
            try:
                template = save_event_as_template(
                    event,
                    request.user,
                    title=form.cleaned_data['title'],
                    description=form.cleaned_data.get('description') or '',
                    is_shared=form.cleaned_data.get('is_shared') or False,
                )
                messages.success(request, f'Template "{template.title}" saved.')
                return redirect('rfx:template_detail', pk=template.pk)
            except Exception as exc:  # unique-title collision, etc.
                messages.error(request, str(exc))
        else:
            messages.error(request, 'Please give the template a title.')
    return redirect('rfx:event_detail', pk=event.pk)


# ---------- Sections (inline CRUD) ----------

@login_required
@vendor_blocked
def section_create(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if not event.is_editable:
        messages.error(request, 'Sections can only be edited on draft events.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = RfxSectionForm(request.POST)
        if form.is_valid():
            section = form.save(commit=False)
            section.tenant = request.tenant
            section.event = event
            if not section.position:
                section.position = (event.sections.count() or 0) + 1
            section.save()
            messages.success(request, f'Section "{section.title}" added.')
        else:
            messages.error(request, 'Could not add section: ' + str(form.errors))
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def section_edit(request, pk, spk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    section = get_object_or_404(
        RfxSection, pk=spk, event=event, tenant=request.tenant,
    )
    if not event.is_editable:
        messages.error(request, 'Sections can only be edited on draft events.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = RfxSectionForm(request.POST, instance=section)
        if form.is_valid():
            form.save()
            messages.success(request, f'Section "{section.title}" updated.')
            return redirect('rfx:event_detail', pk=event.pk)
    else:
        form = RfxSectionForm(instance=section)
    return render(request, 'rfx/sections/form.html', {
        'form': form, 'event': event, 'section': section,
    })


@login_required
@vendor_blocked
def section_delete(request, pk, spk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    section = get_object_or_404(
        RfxSection, pk=spk, event=event, tenant=request.tenant,
    )
    if not event.is_editable:
        messages.error(request, 'Sections can only be deleted on draft events.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        section.delete()
        messages.success(request, 'Section deleted.')
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def section_move(request, pk, spk, direction):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    section = get_object_or_404(
        RfxSection, pk=spk, event=event, tenant=request.tenant,
    )
    if not event.is_editable:
        messages.error(request, 'Sections can only be reordered on draft events.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        try:
            move_section(section, direction)
        except ValidationError as exc:
            _flash_errors(request, exc)
    return redirect('rfx:event_detail', pk=event.pk)


# ---------- Questions (inline CRUD) ----------

@login_required
@vendor_blocked
def question_create(request, pk, spk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    section = get_object_or_404(
        RfxSection, pk=spk, event=event, tenant=request.tenant,
    )
    if not event.is_editable:
        messages.error(request, 'Questions can only be edited on draft events.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = RfxQuestionForm(request.POST)
        if form.is_valid():
            question = form.save(commit=False)
            question.tenant = request.tenant
            question.section = section
            if not question.position:
                question.position = (section.questions.count() or 0) + 1
            question.save()
            messages.success(request, f'Question Q{question.position} added.')
        else:
            messages.error(request, 'Could not add question: ' + str(form.errors))
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def question_edit(request, pk, qpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    question = get_object_or_404(
        RfxQuestion, pk=qpk, section__event=event, tenant=request.tenant,
    )
    if not event.is_editable:
        messages.error(request, 'Questions can only be edited on draft events.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = RfxQuestionForm(request.POST, instance=question)
        if form.is_valid():
            form.save()
            messages.success(request, f'Question Q{question.position} updated.')
            return redirect('rfx:event_detail', pk=event.pk)
    else:
        form = RfxQuestionForm(instance=question)
    return render(request, 'rfx/questions/form.html', {
        'form': form, 'event': event, 'section': question.section, 'question': question,
    })


@login_required
@vendor_blocked
def question_delete(request, pk, qpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    question = get_object_or_404(
        RfxQuestion, pk=qpk, section__event=event, tenant=request.tenant,
    )
    if not event.is_editable:
        messages.error(request, 'Questions can only be deleted on draft events.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        question.delete()
        messages.success(request, 'Question deleted.')
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def question_move(request, pk, qpk, direction):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    question = get_object_or_404(
        RfxQuestion, pk=qpk, section__event=event, tenant=request.tenant,
    )
    if not event.is_editable:
        messages.error(request, 'Questions can only be reordered on draft events.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        try:
            move_question(question, direction)
        except ValidationError as exc:
            _flash_errors(request, exc)
    return redirect('rfx:event_detail', pk=event.pk)


# ---------- Invitees ----------

@login_required
@vendor_blocked
def invitee_add(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if event.status in ('completed', 'cancelled'):
        messages.error(request, 'Cannot invite vendors to a finalised event.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = InviteVendorsForm(
            request.POST, tenant=request.tenant, event=event,
        )
        if form.is_valid():
            vendor_ids = [v.pk for v in form.cleaned_data['vendors']]
            created = invite_vendors(event, vendor_ids, request.user)
            if created:
                messages.success(request, f'{len(created)} vendor(s) invited.')
            else:
                messages.info(request, 'No new vendors invited.')
        else:
            messages.error(request, 'Please select at least one vendor.')
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def invitee_remove(request, pk, ipk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    invitee = get_object_or_404(
        RfxInvitee, pk=ipk, event=event, tenant=request.tenant,
    )
    if invitee.status == 'responded':
        messages.error(request, 'Cannot remove a vendor who has already responded.')
        return redirect('rfx:event_detail', pk=event.pk)
    if request.method == 'POST':
        invitee.delete()
        messages.success(request, 'Invitation removed.')
    return redirect('rfx:event_detail', pk=event.pk)


# ---------- Documents (buyer-side) ----------

@login_required
@vendor_blocked
def document_add(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = RfxDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.tenant = request.tenant
            doc.event = event
            doc.uploaded_by = request.user
            doc.save()
            messages.success(request, f'Document "{doc.title}" uploaded.')
        else:
            messages.error(request, 'Could not upload document: ' + str(form.errors))
    return redirect('rfx:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def document_delete(request, pk, dpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    doc = get_object_or_404(
        RfxDocument, pk=dpk, event=event, tenant=request.tenant,
    )
    if request.method == 'POST':
        doc.delete()
        messages.success(request, 'Document deleted.')
    return redirect('rfx:event_detail', pk=event.pk)


# ---------- Responses (buyer-side, sealed) ----------

@login_required
@vendor_blocked
def response_list(request, pk):
    if (r := _require_tenant(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if not event.responses_are_visible:
        return render(request, 'rfx/responses/list.html', {
            'event': event, 'sealed': True, 'responses': [],
        })
    responses = event.responses.select_related('vendor').order_by(
        'rank', '-overall_score', '-submitted_at',
    )
    return render(request, 'rfx/responses/list.html', {
        'event': event, 'sealed': False,
        'responses': responses,
        'can_manage': can_manage_rfx(request.user),
        'can_evaluate': can_evaluate(request.user),
    })


@login_required
@vendor_blocked
def response_compare(request, pk):
    if (r := _require_tenant(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    if not event.responses_are_visible:
        messages.warning(request, 'Responses are sealed until the event closes.')
        return redirect('rfx:event_detail', pk=event.pk)

    responses = list(
        event.responses.exclude(status='withdrawn').select_related('vendor')
        .order_by('rank', '-overall_score')
    )
    sections = list(event.sections.prefetch_related('questions').all())

    # Build the matrix: rows are questions; columns are responses; cell = answer.
    matrix = []
    for section in sections:
        for question in section.questions.all():
            row = {'section': section, 'question': question, 'cells': []}
            for response in responses:
                answer = response.answers.filter(question=question).first()
                avg = None
                if question.is_scored:
                    avg = response.evaluations.filter(question=question).aggregate(
                        a=Avg('score'),
                    )['a']
                row['cells'].append({'answer': answer, 'avg_score': avg})
            matrix.append(row)

    return render(request, 'rfx/responses/compare.html', {
        'event': event, 'responses': responses, 'matrix': matrix,
        'can_manage': can_manage_rfx(request.user),
    })


@login_required
@vendor_blocked
def response_detail(request, pk, rpk):
    if (r := _require_tenant(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    response = get_object_or_404(
        RfxResponse, pk=rpk, event=event, tenant=request.tenant,
    )
    if not response_visible_to(request.user, response):
        return render(request, 'rfx/responses/detail.html', {
            'event': event, 'response': response, 'sealed': True,
        })

    sections = list(event.sections.prefetch_related('questions').all())
    answers = {a.question_id: a for a in response.answers.all()}
    panel_avg = {
        row['question_id']: row['avg']
        for row in response.evaluations.values('question_id').annotate(avg=Avg('score'))
    }
    my_scores = {
        e.question_id: e
        for e in response.evaluations.filter(evaluator=request.user)
    }
    decision_form = ResponseDecisionForm()

    return render(request, 'rfx/responses/detail.html', {
        'event': event, 'response': response, 'sealed': False,
        'sections': sections, 'answers': answers,
        'panel_avg': panel_avg, 'my_scores': my_scores,
        'decision_form': decision_form,
        'can_manage': can_manage_rfx(request.user),
        'can_evaluate': can_evaluate(request.user),
    })


@login_required
@vendor_blocked
def response_evaluate(request, pk, rpk):
    if (r := _require_tenant(request)):
        return r
    if not can_evaluate(request.user):
        messages.error(request, 'You do not have permission to evaluate responses.')
        return redirect('rfx:event_detail', pk=pk)
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    response = get_object_or_404(
        RfxResponse, pk=rpk, event=event, tenant=request.tenant,
    )
    if not event.responses_are_visible:
        messages.error(request, 'Responses are sealed until the event closes.')
        return redirect('rfx:event_detail', pk=event.pk)

    scored_questions = list(
        RfxQuestion.objects.filter(section__event=event, is_scored=True)
        .select_related('section').order_by('section__position', 'position', 'id')
    )
    existing = {
        e.question_id: e
        for e in response.evaluations.filter(evaluator=request.user)
    }
    answers = {a.question_id: a for a in response.answers.all()}

    if request.method == 'POST':
        errors = []
        any_saved = False
        for question in scored_questions:
            raw = (request.POST.get(f'score_{question.pk}') or '').strip()
            comment = (request.POST.get(f'comment_{question.pk}') or '').strip()
            if not raw:
                continue
            try:
                record_evaluation(
                    response=response,
                    question=question,
                    evaluator=request.user,
                    score=raw,
                    comment=comment,
                )
                any_saved = True
            except ValidationError as exc:
                for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                    errors.append(f'Q{question.position}: {err}')
        if errors:
            for e in errors:
                messages.error(request, e)
        elif any_saved:
            messages.success(request, 'Evaluation saved.')
            return redirect('rfx:response_detail', pk=event.pk, rpk=response.pk)

    return render(request, 'rfx/responses/evaluate.html', {
        'event': event, 'response': response,
        'scored_questions': scored_questions,
        'existing': existing, 'answers': answers,
    })


@login_required
@vendor_blocked
def response_shortlist(request, pk, rpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    response = get_object_or_404(
        RfxResponse, pk=rpk, event=event, tenant=request.tenant,
    )
    if request.method == 'POST':
        form = ResponseDecisionForm(request.POST)
        reason = form.cleaned_data.get('reason') if form.is_valid() else ''
        try:
            shortlist_response(response, request.user, reason=reason)
            messages.success(request, f'Response from {response.vendor.legal_name} shortlisted.')
        except ValidationError as exc:
            _flash_errors(request, exc)
    return redirect('rfx:response_detail', pk=event.pk, rpk=response.pk)


@login_required
@vendor_blocked
def response_reject(request, pk, rpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    response = get_object_or_404(
        RfxResponse, pk=rpk, event=event, tenant=request.tenant,
    )
    if request.method == 'POST':
        form = ResponseDecisionForm(request.POST)
        reason = form.cleaned_data.get('reason') if form.is_valid() else ''
        try:
            reject_response(response, request.user, reason=reason)
            messages.success(request, f'Response from {response.vendor.legal_name} rejected.')
        except ValidationError as exc:
            _flash_errors(request, exc)
    return redirect('rfx:response_detail', pk=event.pk, rpk=response.pk)


# ---------- Templates ----------

@login_required
@vendor_blocked
def template_list(request):
    if (r := _require_tenant(request)):
        return r

    qs = RfxTemplate.objects.filter(tenant=request.tenant).select_related('created_by')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    rfx_type = request.GET.get('rfx_type', '')
    if rfx_type:
        qs = qs.filter(rfx_type=rfx_type)
    archived = request.GET.get('archived', '')
    if archived == 'yes':
        qs = qs.filter(archived=True)
    elif archived == 'no':
        qs = qs.filter(archived=False)

    return render(request, 'rfx/templates/list.html', {
        'templates': qs.order_by('title'),
        'type_choices': RFX_TYPE_CHOICES,
        'can_manage': can_manage_rfx(request.user),
    })


@login_required
@vendor_blocked
def template_create(request):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    if request.method == 'POST':
        form = RfxTemplateForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            template.tenant = request.tenant
            template.created_by = request.user
            template.save()
            messages.success(request, f'Template "{template.title}" created.')
            return redirect('rfx:template_detail', pk=template.pk)
    else:
        form = RfxTemplateForm()
    return render(request, 'rfx/templates/form.html', {
        'form': form, 'title': 'New RFx Template',
    })


@login_required
@vendor_blocked
def template_detail(request, pk):
    if (r := _require_tenant(request)):
        return r
    template = get_object_or_404(RfxTemplate, pk=pk, tenant=request.tenant)
    sections = template.sections.prefetch_related('questions').all()
    scored_q = RfxTemplateQuestion.objects.filter(
        section__template=template, is_scored=True,
    )
    scored_weight_total = sum((q.weight or Decimal('0')) for q in scored_q)
    section_form = RfxTemplateSectionForm()
    question_form = RfxTemplateQuestionForm()
    use_form = UseTemplateForm(initial={'title': template.title})
    return render(request, 'rfx/templates/detail.html', {
        'template': template, 'sections': sections,
        'scored_weight_total': scored_weight_total,
        'section_form': section_form,
        'question_form': question_form,
        'use_form': use_form,
        'can_manage': can_manage_rfx(request.user),
    })


@login_required
@vendor_blocked
def template_edit(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    template = get_object_or_404(RfxTemplate, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = RfxTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            messages.success(request, f'Template "{template.title}" updated.')
            return redirect('rfx:template_detail', pk=template.pk)
    else:
        form = RfxTemplateForm(instance=template)
    return render(request, 'rfx/templates/form.html', {
        'form': form, 'title': f'Edit {template.title}', 'template': template,
    })


@login_required
@vendor_blocked
def template_delete(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    template = get_object_or_404(RfxTemplate, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        title = template.title
        template.delete()
        messages.success(request, f'Template "{title}" deleted.')
    return redirect('rfx:template_list')


@login_required
@vendor_blocked
def template_use(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    template = get_object_or_404(RfxTemplate, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = UseTemplateForm(request.POST)
        if form.is_valid():
            event = create_event_from_template(
                template,
                request.user,
                title=form.cleaned_data['title'],
                publish_at=form.cleaned_data.get('publish_at'),
                close_at=form.cleaned_data.get('close_at'),
            )
            messages.success(
                request,
                f'Event {event.event_number} created from template "{template.title}". '
                'Add invitees and publish.',
            )
            return redirect('rfx:event_detail', pk=event.pk)
        else:
            messages.error(request, 'Please give the new event a title.')
    return redirect('rfx:template_detail', pk=template.pk)


@login_required
@vendor_blocked
def template_section_create(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    template = get_object_or_404(RfxTemplate, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = RfxTemplateSectionForm(request.POST)
        if form.is_valid():
            section = form.save(commit=False)
            section.tenant = request.tenant
            section.template = template
            if not section.position:
                section.position = (template.sections.count() or 0) + 1
            section.save()
            messages.success(request, f'Section "{section.title}" added.')
        else:
            messages.error(request, 'Could not add section: ' + str(form.errors))
    return redirect('rfx:template_detail', pk=template.pk)


@login_required
@vendor_blocked
def template_section_edit(request, pk, spk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    template = get_object_or_404(RfxTemplate, pk=pk, tenant=request.tenant)
    section = get_object_or_404(
        RfxTemplateSection, pk=spk, template=template, tenant=request.tenant,
    )
    if request.method == 'POST':
        form = RfxTemplateSectionForm(request.POST, instance=section)
        if form.is_valid():
            form.save()
            messages.success(request, f'Section "{section.title}" updated.')
            return redirect('rfx:template_detail', pk=template.pk)
    else:
        form = RfxTemplateSectionForm(instance=section)
    return render(request, 'rfx/templates/section_form.html', {
        'form': form, 'template': template, 'section': section,
    })


@login_required
@vendor_blocked
def template_section_delete(request, pk, spk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    template = get_object_or_404(RfxTemplate, pk=pk, tenant=request.tenant)
    section = get_object_or_404(
        RfxTemplateSection, pk=spk, template=template, tenant=request.tenant,
    )
    if request.method == 'POST':
        section.delete()
        messages.success(request, 'Section deleted.')
    return redirect('rfx:template_detail', pk=template.pk)


@login_required
@vendor_blocked
def template_question_create(request, pk, spk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    template = get_object_or_404(RfxTemplate, pk=pk, tenant=request.tenant)
    section = get_object_or_404(
        RfxTemplateSection, pk=spk, template=template, tenant=request.tenant,
    )
    if request.method == 'POST':
        form = RfxTemplateQuestionForm(request.POST)
        if form.is_valid():
            question = form.save(commit=False)
            question.tenant = request.tenant
            question.section = section
            if not question.position:
                question.position = (section.questions.count() or 0) + 1
            question.save()
            messages.success(request, f'Question Q{question.position} added.')
        else:
            messages.error(request, 'Could not add question: ' + str(form.errors))
    return redirect('rfx:template_detail', pk=template.pk)


@login_required
@vendor_blocked
def template_question_edit(request, pk, qpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    template = get_object_or_404(RfxTemplate, pk=pk, tenant=request.tenant)
    question = get_object_or_404(
        RfxTemplateQuestion, pk=qpk, section__template=template, tenant=request.tenant,
    )
    if request.method == 'POST':
        form = RfxTemplateQuestionForm(request.POST, instance=question)
        if form.is_valid():
            form.save()
            messages.success(request, f'Question Q{question.position} updated.')
            return redirect('rfx:template_detail', pk=template.pk)
    else:
        form = RfxTemplateQuestionForm(instance=question)
    return render(request, 'rfx/templates/question_form.html', {
        'form': form, 'template': template, 'section': question.section, 'question': question,
    })


@login_required
@vendor_blocked
def template_question_delete(request, pk, qpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    template = get_object_or_404(RfxTemplate, pk=pk, tenant=request.tenant)
    question = get_object_or_404(
        RfxTemplateQuestion, pk=qpk, section__template=template, tenant=request.tenant,
    )
    if request.method == 'POST':
        question.delete()
        messages.success(request, 'Question deleted.')
    return redirect('rfx:template_detail', pk=template.pk)


# ---------- Analytics ----------

@login_required
@vendor_blocked
def analytics_dashboard(request):
    if (r := _require_tenant(request)):
        return r
    metrics = tenant_rfx_metrics(request.tenant)
    recent = RfxEvent.objects.filter(
        tenant=request.tenant, status='completed',
    ).order_by('-completed_at')[:10]
    top_vendors = (
        RfxResponse.objects.filter(
            tenant=request.tenant, status='shortlisted',
        )
        .values('vendor__legal_name')
        .annotate(shortlists=Count('id'), avg_score=Avg('overall_score'))
        .order_by('-shortlists', '-avg_score')[:5]
    )
    return render(request, 'rfx/analytics/dashboard.html', {
        'metrics': metrics, 'recent': recent, 'top_vendors': top_vendors,
    })


@login_required
@vendor_blocked
def analytics_event_report(request, pk):
    if (r := _require_tenant(request)):
        return r
    event = get_object_or_404(RfxEvent, pk=pk, tenant=request.tenant)
    metrics = event_metrics(event)
    ranked = (
        event.responses.exclude(status='withdrawn').select_related('vendor')
        .order_by('rank', '-overall_score')
    )
    return render(request, 'rfx/analytics/event_report.html', {
        'event': event, 'metrics': metrics, 'ranked': ranked,
    })
