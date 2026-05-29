from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.requisitions.models import AccountCode
from apps.vendors.models import Vendor, VendorCategory

from . import services
from .forms import (
    AuctionDocumentForm,
    AuctionForm,
    AuctionLotForm,
    CancelAuctionForm,
    FinalizeAwardForm,
    InviteVendorsForm,
    PlaceBidForm,
)
from .models import (
    AUCTION_TYPE_CHOICES,
    Auction,
    AuctionDocument,
    AuctionLot,
    AuctionParticipant,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _require_manage(request):
    """Return None if allowed, else an HttpResponse redirect for a denied buyer."""
    if not services.can_manage_auction(request.user):
        messages.error(request, 'You do not have permission to manage auctions.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_monitor(request):
    if not services.can_monitor_auction(request.user):
        messages.error(request, 'You do not have permission to view auction monitoring.')
        return redirect('auctions:auction_list')
    return None


def _has_named_url(name):
    try:
        reverse(name)
        return True
    except Exception:
        return False


def _get_auction(request, pk):
    return get_object_or_404(Auction, pk=pk, tenant=request.tenant)


# ---------------------------------------------------------------------------
# Auction list + CRUD
# ---------------------------------------------------------------------------
@login_required
def auction_list(request):
    denied = _require_manage(request)
    if denied:
        return denied

    qs = Auction.objects.filter(tenant=request.tenant).select_related(
        'category', 'created_by', 'awarded_vendor'
    )

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    auction_type = request.GET.get('type', '')
    category = request.GET.get('category', '')

    if q:
        qs = qs.filter(
            Q(auction_number__icontains=q)
            | Q(title__icontains=q)
            | Q(description__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if auction_type:
        qs = qs.filter(auction_type=auction_type)
    if category:
        qs = qs.filter(category_id=category)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    querystring = request.GET.copy()
    querystring.pop('page', None)

    context = {
        'page_obj': page_obj,
        'auctions': page_obj.object_list,
        'q': q,
        'status_choices': Auction.STATUS_CHOICES,
        'type_choices': AUCTION_TYPE_CHOICES,
        'categories': VendorCategory.objects.filter(tenant=request.tenant, is_active=True),
        'querystring': querystring.urlencode(),
        'can_manage': True,
    }
    return render(request, 'auctions/auction_list.html', context)


@login_required
def auction_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    if request.method == 'POST':
        form = AuctionForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            auction = form.save(commit=False)
            auction.tenant = request.tenant
            auction.created_by = request.user
            auction.auction_number = services.next_auction_number(request.tenant)
            auction.save()
            services.record_audit(
                request.tenant,
                request.user,
                'auction.created',
                target_type='auction',
                target_id=str(auction.pk),
                message=f'Auction {auction.auction_number} created.',
                request=request,
            )
            messages.success(request, f'Auction {auction.auction_number} created.')
            return redirect('auctions:auction_detail', pk=auction.pk)
    else:
        form = AuctionForm(tenant=request.tenant)

    context = {
        'form': form,
        'is_edit': False,
    }
    return render(request, 'auctions/auction_form.html', context)


@login_required
def auction_detail(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    services.refresh_auction_state(auction, user=request.user)

    lots = auction.lots.all()
    participants = auction.participants.select_related('vendor').all()
    documents = auction.documents.select_related('uploaded_by').all()
    recent_bids = auction.bids.select_related('vendor', 'participant').all()[:25]

    best = services.current_best(auction)

    context = {
        'auction': auction,
        'lots': lots,
        'participants': participants,
        'documents': documents,
        'recent_bids': recent_bids,
        'current_best': best,
        'document_form': AuctionDocumentForm(),
        'invite_form': InviteVendorsForm(tenant=request.tenant, auction=auction),
        'lot_form': AuctionLotForm(tenant=request.tenant, auction=auction),
        'cancel_form': CancelAuctionForm(),
        'can_manage': True,
    }
    return render(request, 'auctions/auction_detail.html', context)


@login_required
def auction_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    if not auction.is_editable:
        messages.error(request, 'Only draft auctions can be edited.')
        return redirect('auctions:auction_detail', pk=auction.pk)

    if request.method == 'POST':
        form = AuctionForm(request.POST, instance=auction, tenant=request.tenant)
        if form.is_valid():
            form.save()
            services.record_audit(
                request.tenant,
                request.user,
                'auction.updated',
                target_type='auction',
                target_id=str(auction.pk),
                message=f'Auction {auction.auction_number} updated.',
                request=request,
            )
            messages.success(request, 'Auction updated.')
            return redirect('auctions:auction_detail', pk=auction.pk)
    else:
        form = AuctionForm(instance=auction, tenant=request.tenant)

    context = {
        'form': form,
        'auction': auction,
        'is_edit': True,
    }
    return render(request, 'auctions/auction_form.html', context)


@login_required
@require_POST
def auction_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    if not auction.is_editable:
        messages.error(request, 'Only draft auctions can be deleted.')
        return redirect('auctions:auction_detail', pk=auction.pk)

    number = auction.auction_number
    services.record_audit(
        request.tenant,
        request.user,
        'auction.deleted',
        level='warning',
        target_type='auction',
        target_id=str(auction.pk),
        message=f'Auction {number} deleted.',
        request=request,
    )
    auction.delete()
    messages.success(request, f'Auction {number} deleted.')
    return redirect('auctions:auction_list')


# ---------------------------------------------------------------------------
# Lifecycle transitions (POST)
# ---------------------------------------------------------------------------
@login_required
@require_POST
def auction_publish(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    try:
        warnings = services.publish_auction(auction, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('auctions:auction_detail', pk=auction.pk)

    # Lazily flip to live if the start time has already arrived.
    services.refresh_auction_state(auction, user=request.user)

    for w in warnings:
        messages.warning(request, w)
    messages.success(request, f'Auction {auction.auction_number} published.')
    return redirect('auctions:auction_detail', pk=auction.pk)


@login_required
@require_POST
def auction_start(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    try:
        services.start_auction(auction, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('auctions:auction_detail', pk=auction.pk)

    messages.success(request, 'Auction is now live.')
    return redirect('auctions:console', pk=auction.pk)


@login_required
@require_POST
def auction_close(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    try:
        services.close_auction(auction, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('auctions:console', pk=auction.pk)

    messages.success(request, 'Auction closed.')
    return redirect('auctions:results', pk=auction.pk)


@login_required
@require_POST
def auction_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    form = CancelAuctionForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('auctions:auction_detail', pk=auction.pk)

    try:
        services.cancel_auction(auction, request.user, form.cleaned_data['reason'])
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('auctions:auction_detail', pk=auction.pk)

    messages.success(request, 'Auction cancelled.')
    return redirect('auctions:auction_detail', pk=auction.pk)


# ---------------------------------------------------------------------------
# Lots (draft only)
# ---------------------------------------------------------------------------
@login_required
def lot_create(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    if not auction.is_editable:
        messages.error(request, 'Lots can only be changed while the auction is a draft.')
        return redirect('auctions:auction_detail', pk=auction.pk)

    if request.method == 'POST':
        form = AuctionLotForm(request.POST, tenant=request.tenant, auction=auction)
        if form.is_valid():
            lot = form.save(commit=False)
            lot.tenant = request.tenant
            lot.auction = auction
            lot.save()
            messages.success(request, 'Lot added.')
            return redirect('auctions:auction_detail', pk=auction.pk)
    else:
        form = AuctionLotForm(tenant=request.tenant, auction=auction)

    context = {
        'form': form,
        'auction': auction,
        'is_edit': False,
    }
    return render(request, 'auctions/lot_form.html', context)


@login_required
def lot_edit(request, pk, lot_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    lot = get_object_or_404(AuctionLot, pk=lot_pk, auction=auction, tenant=request.tenant)
    if not auction.is_editable:
        messages.error(request, 'Lots can only be changed while the auction is a draft.')
        return redirect('auctions:auction_detail', pk=auction.pk)

    if request.method == 'POST':
        form = AuctionLotForm(request.POST, instance=lot, tenant=request.tenant, auction=auction)
        if form.is_valid():
            form.save()
            messages.success(request, 'Lot updated.')
            return redirect('auctions:auction_detail', pk=auction.pk)
    else:
        form = AuctionLotForm(instance=lot, tenant=request.tenant, auction=auction)

    context = {
        'form': form,
        'auction': auction,
        'lot': lot,
        'is_edit': True,
    }
    return render(request, 'auctions/lot_form.html', context)


@login_required
@require_POST
def lot_delete(request, pk, lot_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    lot = get_object_or_404(AuctionLot, pk=lot_pk, auction=auction, tenant=request.tenant)
    if not auction.is_editable:
        messages.error(request, 'Lots can only be changed while the auction is a draft.')
        return redirect('auctions:auction_detail', pk=auction.pk)

    lot.delete()
    messages.success(request, 'Lot removed.')
    return redirect('auctions:auction_detail', pk=auction.pk)


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------
@login_required
@require_POST
def participant_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    form = InviteVendorsForm(request.POST, tenant=request.tenant, auction=auction)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('auctions:auction_detail', pk=auction.pk)

    vendor_ids = [v.pk for v in form.cleaned_data['vendors']]
    try:
        created = services.invite_vendors(auction, vendor_ids, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('auctions:auction_detail', pk=auction.pk)

    if created:
        messages.success(request, f'Invited {len(created)} vendor(s).')
    else:
        messages.info(request, 'No new vendors invited.')
    return redirect('auctions:auction_detail', pk=auction.pk)


@login_required
@require_POST
def participant_remove(request, pk, participant_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    participant = get_object_or_404(
        AuctionParticipant, pk=participant_pk, auction=auction, tenant=request.tenant
    )
    try:
        services.remove_participant(participant, request.user)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('auctions:auction_detail', pk=auction.pk)

    messages.success(request, 'Participant removed.')
    return redirect('auctions:auction_detail', pk=auction.pk)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@login_required
@require_POST
def document_add(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    form = AuctionDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        doc = form.save(commit=False)
        doc.tenant = request.tenant
        doc.auction = auction
        doc.uploaded_by = request.user
        doc.save()
        services.record_audit(
            request.tenant,
            request.user,
            'auction.document.added',
            target_type='auction',
            target_id=str(auction.pk),
            message=f'Document "{doc.title}" added to {auction.auction_number}.',
            request=request,
        )
        messages.success(request, 'Document uploaded.')
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect('auctions:auction_detail', pk=auction.pk)


@login_required
@require_POST
def document_delete(request, pk, document_pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    doc = get_object_or_404(
        AuctionDocument, pk=document_pk, auction=auction, tenant=request.tenant
    )
    title = doc.title
    doc.delete()
    services.record_audit(
        request.tenant,
        request.user,
        'auction.document.deleted',
        level='warning',
        target_type='auction',
        target_id=str(auction.pk),
        message=f'Document "{title}" removed from {auction.auction_number}.',
        request=request,
    )
    messages.success(request, 'Document removed.')
    return redirect('auctions:auction_detail', pk=auction.pk)


# ---------------------------------------------------------------------------
# Live console (buyer monitor)
# ---------------------------------------------------------------------------
@login_required
def console(request, pk):
    denied = _require_monitor(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    services.refresh_auction_state(auction, user=request.user)

    context = {
        'auction': auction,
        'state_url': reverse('auctions:console_state', kwargs={'pk': auction.pk}),
        'cancel_form': CancelAuctionForm(),
        'can_manage': services.can_manage_auction(request.user),
    }
    return render(request, 'auctions/console.html', context)


@login_required
def console_state(request, pk):
    if not services.can_monitor_auction(request.user):
        return JsonResponse({'error': 'forbidden'}, status=403)

    auction = _get_auction(request, pk)
    payload = services.live_payload(auction, request.user)
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# Results + award
# ---------------------------------------------------------------------------
@login_required
def results(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    services.refresh_auction_state(auction, user=request.user)
    services.recompute_ranks(auction)

    participants = auction.participants.select_related('vendor').all()
    savings = services.compute_auction_savings(auction)

    context = {
        'auction': auction,
        'participants': participants,
        'savings': savings,
        'finalize_form': FinalizeAwardForm(auction=auction),
        'can_manage': True,
    }
    return render(request, 'auctions/results.html', context)


@login_required
@require_POST
def award_finalize(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    form = FinalizeAwardForm(request.POST, auction=auction)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('auctions:results', pk=auction.pk)

    winner = form.cleaned_data.get('winner_vendor')
    notes = form.cleaned_data.get('notes', '')
    if notes:
        auction.award_notes = notes
    try:
        services.finalize_auction(auction, request.user, winner_vendor=winner)
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
        return redirect('auctions:results', pk=auction.pk)

    if notes:
        auction.award_notes = notes
        auction.save(update_fields=['award_notes', 'updated_at'])

    messages.success(request, f'Auction awarded to {auction.awarded_vendor}.')
    return redirect('auctions:results', pk=auction.pk)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@login_required
def analytics_dashboard(request):
    denied = _require_monitor(request)
    if denied:
        return denied

    metrics = services.tenant_auction_metrics(request.tenant)
    recent = Auction.objects.filter(tenant=request.tenant).select_related(
        'awarded_vendor'
    )[:10]

    context = {
        'metrics': metrics,
        'recent_auctions': recent,
        'can_manage': services.can_manage_auction(request.user),
    }
    return render(request, 'auctions/analytics_dashboard.html', context)


@login_required
def auction_analytics(request, pk):
    denied = _require_monitor(request)
    if denied:
        return denied

    auction = _get_auction(request, pk)
    analytics = services.auction_analytics(auction)

    context = {
        'auction': auction,
        'analytics': analytics,
        'savings': analytics.get('savings'),
        'can_manage': services.can_manage_auction(request.user),
    }
    return render(request, 'auctions/auction_analytics.html', context)
