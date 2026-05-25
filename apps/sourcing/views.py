"""Module 6 views (buyer side): events, items, criteria, invitees, bids,
evaluation, awards, analytics."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Q, Sum
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.vendors.decorators import vendor_blocked
from apps.vendors.models import Vendor, VendorCategory

from .forms import (
    AwardRecommendForm, BidEvaluationForm, CancelEventForm,
    InviteVendorsForm, SourcingCriterionForm, SourcingEventForm,
    SourcingEventItemForm,
)
from .models import (
    Bid, BidEvaluation, BidLine, SourcingAward, SourcingCriterion,
    SourcingEvent, SourcingEventInvitee, SourcingEventItem,
    EVENT_STATUS_CHOICES, EVENT_TYPE_CHOICES, BID_STATUS_CHOICES,
)
from .services import (
    bid_visible_to, can_evaluate, can_manage_sourcing,
    cancel_event, close_event, finalize_award, invite_vendors,
    next_event_number, open_event, publish_event, recommend_award,
    record_evaluation, recompute_bid_scores, reject_bid, shortlist_bid,
    compute_event_savings, tenant_sourcing_metrics,
    validate_event_can_publish,
)


# ---------- Permission helpers ----------

def _require_tenant(request):
    if not request.tenant:
        return redirect('tenants:onboarding_start')
    return None


def _require_manage(request):
    if not can_manage_sourcing(request.user):
        messages.error(request, 'You do not have permission to manage sourcing events.')
        return redirect('sourcing:event_list')
    return None


# ---------- Event list / CRUD ----------

@login_required
@vendor_blocked
def event_list(request):
    if (r := _require_tenant(request)):
        return r

    qs = SourcingEvent.objects.filter(tenant=request.tenant).select_related(
        'category', 'awarded_vendor', 'created_by',
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
    event_type = request.GET.get('event_type', '')
    if event_type:
        qs = qs.filter(event_type=event_type)
    category_id = request.GET.get('category', '')
    if category_id:
        qs = qs.filter(category_id=category_id)

    stats = {
        'total': SourcingEvent.objects.filter(tenant=request.tenant).count(),
        'open': SourcingEvent.objects.filter(
            tenant=request.tenant, status='open',
        ).count(),
        'draft': SourcingEvent.objects.filter(
            tenant=request.tenant, status='draft',
        ).count(),
        'awarded': SourcingEvent.objects.filter(
            tenant=request.tenant, status='awarded',
        ).count(),
    }
    return render(request, 'sourcing/events/list.html', {
        'events': qs.order_by('-created_at'),
        'status_choices': EVENT_STATUS_CHOICES,
        'type_choices': EVENT_TYPE_CHOICES,
        'categories': VendorCategory.objects.filter(
            tenant=request.tenant, is_active=True,
        ),
        'stats': stats,
        'can_manage': can_manage_sourcing(request.user),
    })


@login_required
@vendor_blocked
def event_create(request):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r

    from_req_pk = request.GET.get('from_requisition')
    initial = {}
    if from_req_pk:
        from apps.requisitions.models import Requisition
        from .services import create_event_from_requisition
        req = get_object_or_404(
            Requisition, pk=from_req_pk, tenant=request.tenant,
        )
        if req.status != 'approved':
            messages.error(request, 'Only approved requisitions can spawn a sourcing event.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        event = create_event_from_requisition(req, request.user)
        messages.success(
            request,
            f'Event {event.event_number} created from {req.number}. '
            'Add invitees and criteria, then publish.'
        )
        return redirect('sourcing:event_detail', pk=event.pk)

    if request.method == 'POST':
        form = SourcingEventForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            event = form.save(commit=False)
            event.tenant = request.tenant
            event.event_number = next_event_number(request.tenant)
            event.status = 'draft'
            event.created_by = request.user
            event.save()
            messages.success(request, f'Event {event.event_number} created as draft.')
            return redirect('sourcing:event_detail', pk=event.pk)
    else:
        form = SourcingEventForm(tenant=request.tenant, initial=initial)
    return render(request, 'sourcing/events/form.html', {
        'form': form, 'title': 'New Sourcing Event',
    })


@login_required
@vendor_blocked
def event_detail(request, pk):
    if (r := _require_tenant(request)):
        return r
    event = get_object_or_404(
        SourcingEvent, pk=pk, tenant=request.tenant,
    )
    items = event.items.select_related('account_code').all()
    invitees = event.invitees.select_related('vendor').all()
    criteria = event.criteria.all()
    bids = event.bids.select_related('vendor').all()
    awards = event.awards.select_related('vendor', 'bid').all()
    criteria_total = sum((c.weight or Decimal('0')) for c in criteria)

    can_view_bids = event.bids_are_visible and (
        can_manage_sourcing(request.user) or can_evaluate(request.user)
    )

    publish_errors = (
        validate_event_can_publish(event) if event.status == 'draft' else []
    )

    item_form = SourcingEventItemForm(tenant=request.tenant, event=event)
    criterion_form = SourcingCriterionForm(event=event)
    invitee_form = InviteVendorsForm(tenant=request.tenant, event=event)
    cancel_form = CancelEventForm()
    savings = compute_event_savings(event) if event.status == 'awarded' else None

    return render(request, 'sourcing/events/detail.html', {
        'event': event,
        'items': items,
        'invitees': invitees,
        'criteria': criteria,
        'criteria_total': criteria_total,
        'bids': bids,
        'awards': awards,
        'item_form': item_form,
        'criterion_form': criterion_form,
        'invitee_form': invitee_form,
        'cancel_form': cancel_form,
        'can_manage': can_manage_sourcing(request.user),
        'can_evaluate': can_evaluate(request.user),
        'can_view_bids': can_view_bids,
        'publish_errors': publish_errors,
        'savings': savings,
    })


@login_required
@vendor_blocked
def event_edit(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if not event.is_editable:
        messages.error(request, 'Only draft events can be edited.')
        return redirect('sourcing:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = SourcingEventForm(request.POST, instance=event, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, f'Event {event.event_number} updated.')
            return redirect('sourcing:event_detail', pk=event.pk)
    else:
        form = SourcingEventForm(instance=event, tenant=request.tenant)
    return render(request, 'sourcing/events/form.html', {
        'form': form, 'title': f'Edit {event.event_number}', 'event': event,
    })


@login_required
@vendor_blocked
def event_delete(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if not event.is_editable:
        messages.error(request, 'Only draft events can be deleted.')
        return redirect('sourcing:event_detail', pk=event.pk)
    if request.method == 'POST':
        number = event.event_number
        event.delete()
        messages.success(request, f'Event {number} deleted.')
    return redirect('sourcing:event_list')


# ---------- Event lifecycle actions ----------

@login_required
@vendor_blocked
def event_publish(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            publish_event(event, request.user)
            messages.success(request, f'Event {event.event_number} published ({event.status}).')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('sourcing:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def event_open(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            open_event(event, request.user)
            messages.success(request, f'Event {event.event_number} is now open for bids.')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('sourcing:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def event_close(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            close_event(event, request.user)
            messages.success(request, f'Event {event.event_number} closed. Bids are now visible.')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('sourcing:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def event_cancel(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = CancelEventForm(request.POST)
        if form.is_valid():
            try:
                cancel_event(event, request.user, form.cleaned_data['reason'])
                messages.success(request, f'Event {event.event_number} cancelled.')
            except ValidationError as exc:
                for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                    messages.error(request, err)
        else:
            messages.error(request, 'Please provide a reason for cancellation.')
    return redirect('sourcing:event_detail', pk=event.pk)


# ---------- Items inline CRUD ----------

@login_required
@vendor_blocked
def item_create(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if not event.is_editable:
        messages.error(request, 'Items can only be added to draft events.')
        return redirect('sourcing:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = SourcingEventItemForm(
            request.POST, tenant=request.tenant, event=event,
        )
        if form.is_valid():
            item = form.save(commit=False)
            item.tenant = request.tenant
            item.event = event
            item.save()
            messages.success(request, f'Line #{item.line_no} added.')
        else:
            messages.error(request, 'Could not add line: ' + str(form.errors))
    return redirect('sourcing:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def item_edit(request, pk, lpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    item = get_object_or_404(
        SourcingEventItem, pk=lpk, event=event, tenant=request.tenant,
    )
    if not event.is_editable:
        messages.error(request, 'Items can only be edited on draft events.')
        return redirect('sourcing:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = SourcingEventItemForm(
            request.POST, instance=item, tenant=request.tenant, event=event,
        )
        if form.is_valid():
            form.save()
            messages.success(request, f'Line #{item.line_no} updated.')
            return redirect('sourcing:event_detail', pk=event.pk)
    else:
        form = SourcingEventItemForm(
            instance=item, tenant=request.tenant, event=event,
        )
    return render(request, 'sourcing/items/form.html', {
        'form': form, 'event': event, 'item': item,
    })


@login_required
@vendor_blocked
def item_delete(request, pk, lpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    item = get_object_or_404(
        SourcingEventItem, pk=lpk, event=event, tenant=request.tenant,
    )
    if not event.is_editable:
        messages.error(request, 'Items can only be deleted from draft events.')
        return redirect('sourcing:event_detail', pk=event.pk)
    if request.method == 'POST':
        item.delete()
        messages.success(request, 'Line deleted.')
    return redirect('sourcing:event_detail', pk=event.pk)


# ---------- Invitees ----------

@login_required
@vendor_blocked
def invitee_add(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if event.status in ('awarded', 'cancelled'):
        messages.error(request, 'Cannot invite vendors to a finalised event.')
        return redirect('sourcing:event_detail', pk=event.pk)
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
    return redirect('sourcing:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def invitee_remove(request, pk, ipk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    invitee = get_object_or_404(
        SourcingEventInvitee, pk=ipk, event=event, tenant=request.tenant,
    )
    if invitee.status in ('submitted',):
        messages.error(request, 'Cannot remove a vendor who has already submitted a bid.')
        return redirect('sourcing:event_detail', pk=event.pk)
    if request.method == 'POST':
        invitee.delete()
        messages.success(request, 'Invitation removed.')
    return redirect('sourcing:event_detail', pk=event.pk)


# ---------- Criteria ----------

@login_required
@vendor_blocked
def criterion_create(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if event.status not in ('draft', 'scheduled'):
        messages.error(request, 'Criteria can only be edited before the event opens.')
        return redirect('sourcing:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = SourcingCriterionForm(request.POST, event=event)
        if form.is_valid():
            criterion = form.save(commit=False)
            criterion.tenant = request.tenant
            criterion.event = event
            criterion.save()
            messages.success(request, f'Criterion "{criterion.name}" added.')
        else:
            messages.error(request, 'Could not add criterion: ' + str(form.errors))
    return redirect('sourcing:event_detail', pk=event.pk)


@login_required
@vendor_blocked
def criterion_edit(request, pk, cpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    criterion = get_object_or_404(
        SourcingCriterion, pk=cpk, event=event, tenant=request.tenant,
    )
    if event.status not in ('draft', 'scheduled'):
        messages.error(request, 'Criteria can only be edited before the event opens.')
        return redirect('sourcing:event_detail', pk=event.pk)
    if request.method == 'POST':
        form = SourcingCriterionForm(request.POST, instance=criterion, event=event)
        if form.is_valid():
            form.save()
            messages.success(request, f'Criterion "{criterion.name}" updated.')
            return redirect('sourcing:event_detail', pk=event.pk)
    else:
        form = SourcingCriterionForm(instance=criterion, event=event)
    return render(request, 'sourcing/criteria/form.html', {
        'form': form, 'event': event, 'criterion': criterion,
    })


@login_required
@vendor_blocked
def criterion_delete(request, pk, cpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    criterion = get_object_or_404(
        SourcingCriterion, pk=cpk, event=event, tenant=request.tenant,
    )
    if event.status not in ('draft', 'scheduled'):
        messages.error(request, 'Criteria can only be deleted before the event opens.')
        return redirect('sourcing:event_detail', pk=event.pk)
    if request.method == 'POST':
        criterion.delete()
        messages.success(request, 'Criterion deleted.')
    return redirect('sourcing:event_detail', pk=event.pk)


# ---------- Bids (buyer side — sealed) ----------

@login_required
@vendor_blocked
def bid_list(request, pk):
    if (r := _require_tenant(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if not event.bids_are_visible:
        return render(request, 'sourcing/bids/list.html', {
            'event': event, 'sealed': True, 'bids': [],
        })
    bids = event.bids.select_related('vendor').order_by(
        'rank', '-overall_score', 'total_amount',
    )
    return render(request, 'sourcing/bids/list.html', {
        'event': event, 'sealed': False,
        'bids': bids,
        'can_manage': can_manage_sourcing(request.user),
        'can_evaluate': can_evaluate(request.user),
        'status_choices': BID_STATUS_CHOICES,
    })


@login_required
@vendor_blocked
def bid_compare(request, pk):
    if (r := _require_tenant(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if not event.bids_are_visible:
        messages.warning(request, 'Bids are sealed until the event closes.')
        return redirect('sourcing:event_detail', pk=event.pk)

    bids = list(event.bids.exclude(status='withdrawn').select_related('vendor')
                          .order_by('rank', '-overall_score'))
    items = list(event.items.all().order_by('line_no'))
    criteria = list(event.criteria.all())

    # Build line-by-line matrix: rows are event items, columns are bids.
    matrix_lines = []
    for item in items:
        row = {'item': item, 'cells': []}
        for bid in bids:
            line = bid.lines.filter(event_item=item).first()
            row['cells'].append(line)
        matrix_lines.append(row)

    # Criterion averages per bid (panel scoring).
    matrix_criteria = []
    for crit in criteria:
        row = {'criterion': crit, 'cells': []}
        for bid in bids:
            avg = bid.evaluations.filter(criterion=crit).aggregate(
                a=Avg('score'),
            )['a']
            row['cells'].append(avg)
        matrix_criteria.append(row)

    return render(request, 'sourcing/bids/compare.html', {
        'event': event, 'bids': bids, 'items': items, 'criteria': criteria,
        'matrix_lines': matrix_lines, 'matrix_criteria': matrix_criteria,
        'can_manage': can_manage_sourcing(request.user),
    })


@login_required
@vendor_blocked
def bid_detail(request, pk, bpk):
    if (r := _require_tenant(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    bid = get_object_or_404(Bid, pk=bpk, event=event, tenant=request.tenant)
    if not bid_visible_to(request.user, bid):
        return render(request, 'sourcing/bids/detail.html', {
            'event': event, 'bid': bid, 'sealed': True,
        })

    lines = bid.lines.select_related('event_item').order_by('event_item__line_no')
    documents = bid.documents.all()
    criteria = event.criteria.all()
    my_evaluations = {
        e.criterion_id: e
        for e in bid.evaluations.filter(evaluator=request.user)
    }
    panel_averages = {
        row['criterion_id']: row['avg']
        for row in bid.evaluations.values('criterion_id').annotate(avg=Avg('score'))
    }

    return render(request, 'sourcing/bids/detail.html', {
        'event': event, 'bid': bid, 'sealed': False,
        'lines': lines, 'documents': documents, 'criteria': criteria,
        'my_evaluations': my_evaluations,
        'panel_averages': panel_averages,
        'can_manage': can_manage_sourcing(request.user),
        'can_evaluate': can_evaluate(request.user),
    })


@login_required
@vendor_blocked
def bid_evaluate(request, pk, bpk):
    if (r := _require_tenant(request)):
        return r
    if not can_evaluate(request.user):
        messages.error(request, 'You do not have permission to evaluate bids.')
        return redirect('sourcing:event_detail', pk=pk)
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    bid = get_object_or_404(Bid, pk=bpk, event=event, tenant=request.tenant)
    if not event.bids_are_visible:
        messages.error(request, 'Bids are sealed until the event closes.')
        return redirect('sourcing:event_detail', pk=event.pk)

    criteria = list(event.criteria.all())
    existing = {
        e.criterion_id: e
        for e in bid.evaluations.filter(evaluator=request.user)
    }

    if request.method == 'POST':
        errors = []
        for crit in criteria:
            raw = (request.POST.get(f'score_{crit.pk}') or '').strip()
            comment = (request.POST.get(f'comment_{crit.pk}') or '').strip()
            if not raw:
                continue
            try:
                record_evaluation(
                    bid=bid, criterion=crit, evaluator=request.user,
                    score=raw, comment=comment,
                )
            except ValidationError as exc:
                for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                    errors.append(f'{crit.name}: {err}')
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            messages.success(request, 'Evaluation saved.')
            return redirect('sourcing:bid_detail', pk=event.pk, bpk=bid.pk)

    return render(request, 'sourcing/bids/evaluate.html', {
        'event': event, 'bid': bid, 'criteria': criteria, 'existing': existing,
    })


@login_required
@vendor_blocked
def bid_shortlist(request, pk, bpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    bid = get_object_or_404(Bid, pk=bpk, event=event, tenant=request.tenant)
    if request.method == 'POST':
        try:
            shortlist_bid(bid, request.user)
            messages.success(request, f'Bid {bid.bid_number} shortlisted.')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('sourcing:bid_detail', pk=event.pk, bpk=bid.pk)


@login_required
@vendor_blocked
def bid_reject(request, pk, bpk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    bid = get_object_or_404(Bid, pk=bpk, event=event, tenant=request.tenant)
    if request.method == 'POST':
        try:
            reject_bid(bid, request.user)
            messages.success(request, f'Bid {bid.bid_number} rejected.')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('sourcing:bid_detail', pk=event.pk, bpk=bid.pk)


# ---------- Awards ----------

@login_required
@vendor_blocked
def award_recommend(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = AwardRecommendForm(request.POST, event=event)
        if form.is_valid():
            try:
                award = recommend_award(
                    event=event,
                    vendor=form.cleaned_data['vendor'],
                    amount=form.cleaned_data['award_amount'],
                    user=request.user,
                    justification=form.cleaned_data.get('justification') or '',
                )
                messages.success(
                    request,
                    f'Award recommended: {award.vendor.legal_name} '
                    f'for {award.award_amount}.'
                )
            except ValidationError as exc:
                for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                    messages.error(request, err)
            return redirect('sourcing:event_detail', pk=event.pk)
    else:
        form = AwardRecommendForm(event=event)
    return render(request, 'sourcing/awards/recommend.html', {
        'form': form, 'event': event,
    })


@login_required
@vendor_blocked
def award_finalize(request, pk):
    if (r := _require_tenant(request)) or (r := _require_manage(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            finalize_award(event, request.user)
            messages.success(
                request,
                f'Event {event.event_number} awarded to '
                f'{event.awarded_vendor.legal_name}.'
            )
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('sourcing:event_detail', pk=event.pk)


# ---------- Analytics ----------

@login_required
@vendor_blocked
def analytics_dashboard(request):
    if (r := _require_tenant(request)):
        return r
    metrics = tenant_sourcing_metrics(request.tenant)
    recent = SourcingEvent.objects.filter(
        tenant=request.tenant, status='awarded',
    ).select_related('awarded_vendor').order_by('-awarded_at')[:10]
    # Top vendors by win count
    top_vendors = (
        SourcingAward.objects.filter(tenant=request.tenant, status='approved')
        .values('vendor__legal_name')
        .annotate(wins=Count('id'), value=Sum('award_amount'))
        .order_by('-wins', '-value')[:5]
    )
    return render(request, 'sourcing/analytics/dashboard.html', {
        'metrics': metrics,
        'recent': recent,
        'top_vendors': top_vendors,
    })


@login_required
@vendor_blocked
def analytics_event_report(request, pk):
    if (r := _require_tenant(request)):
        return r
    event = get_object_or_404(SourcingEvent, pk=pk, tenant=request.tenant)
    savings = compute_event_savings(event)
    invitee_count = event.invitees.count()
    submitted_count = event.invitees.filter(status='submitted').count()
    response_rate = (
        (Decimal(submitted_count) / Decimal(invitee_count) * Decimal('100'))
        if invitee_count else Decimal('0')
    )
    return render(request, 'sourcing/analytics/event_report.html', {
        'event': event, 'savings': savings,
        'invitee_count': invitee_count,
        'submitted_count': submitted_count,
        'response_rate': response_rate.quantize(Decimal('0.01')),
    })
