"""Module 6 vendor-portal views: invitations, event read-only, bid submission."""
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.vendors.decorators import vendor_required

from .forms import BidDocumentForm, BidForm, BidLineForm
from .models import Bid, BidDocument, BidLine, SourcingEvent, SourcingEventInvitee
from .services import (
    decline_invitation, start_bid, submit_bid, withdraw_bid,
)


@vendor_required
def portal_invitations(request):
    """List sourcing invitations for the current vendor portal user."""
    vendor = request.user.vendor
    invitations = SourcingEventInvitee.all_objects.filter(
        vendor=vendor,
    ).select_related('event').order_by('-invited_at')
    return render(request, 'vendor_portal/sourcing/invitations.html', {
        'invitations': invitations, 'vendor': vendor,
    })


@vendor_required
def portal_event_detail(request, event_pk):
    """Read-only RFQ view for an invited vendor."""
    vendor = request.user.vendor
    event = get_object_or_404(
        SourcingEvent, pk=event_pk, tenant=vendor.tenant,
    )
    invitee = event.invitees.filter(vendor=vendor).first()
    if not invitee:
        messages.error(request, 'You are not invited to this event.')
        return redirect('vendor_portal:sourcing_invitations')
    if invitee.status == 'invited':
        invitee.status = 'viewed'
        invitee.responded_at = timezone.now()
        invitee.save(update_fields=['status', 'responded_at', 'updated_at'])

    items = event.items.all().order_by('line_no')
    criteria = event.criteria.all()
    my_bid = event.bids.filter(vendor=vendor).first()
    return render(request, 'vendor_portal/sourcing/event_detail.html', {
        'event': event, 'invitee': invitee, 'items': items,
        'criteria': criteria, 'my_bid': my_bid,
    })


@vendor_required
def portal_bid_start(request, event_pk):
    """Create a draft Bid for the current vendor (idempotent)."""
    vendor = request.user.vendor
    event = get_object_or_404(
        SourcingEvent, pk=event_pk, tenant=vendor.tenant,
    )
    if request.method != 'POST':
        return redirect('vendor_portal:sourcing_event_detail', event_pk=event.pk)
    try:
        bid = start_bid(event, vendor, request.user)
        messages.success(request, 'Draft bid created. Fill in your prices to submit.')
        return redirect(
            'vendor_portal:sourcing_bid_edit', event_pk=event.pk, bpk=bid.pk,
        )
    except ValidationError as exc:
        for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
            messages.error(request, err)
        return redirect('vendor_portal:sourcing_event_detail', event_pk=event.pk)


@vendor_required
def portal_bid_edit(request, event_pk, bpk):
    """Fill in / edit prices on a draft Bid, upload documents."""
    vendor = request.user.vendor
    event = get_object_or_404(
        SourcingEvent, pk=event_pk, tenant=vendor.tenant,
    )
    bid = get_object_or_404(
        Bid, pk=bpk, event=event, vendor=vendor, tenant=vendor.tenant,
    )
    locked = bid.is_locked

    if request.method == 'POST' and not locked:
        # Update header
        header_form = BidForm(request.POST, instance=bid)
        if header_form.is_valid():
            header_form.save()
        # Update lines
        any_error = False
        for line in bid.lines.all():
            prefix = f'line_{line.pk}_'
            unit_price = request.POST.get(prefix + 'unit_price')
            quantity = request.POST.get(prefix + 'quantity_offered')
            lead_time = request.POST.get(prefix + 'lead_time_days') or None
            notes = request.POST.get(prefix + 'notes', '')
            try:
                line.unit_price = Decimal(unit_price or '0')
                line.quantity_offered = Decimal(quantity or '0')
                line.lead_time_days = int(lead_time) if lead_time else None
                line.notes = notes
                line.save(update_fields=[
                    'unit_price', 'quantity_offered', 'lead_time_days',
                    'notes', 'updated_at',
                ])
            except (ValueError, TypeError) as exc:
                any_error = True
                messages.error(request, f'Line {line.event_item.line_no}: {exc}')
        # Optional document upload
        doc_form = BidDocumentForm(request.POST, request.FILES)
        if request.FILES.get('file') and doc_form.is_valid():
            doc = doc_form.save(commit=False)
            doc.tenant = vendor.tenant
            doc.bid = bid
            doc.save()
            messages.success(request, f'Document "{doc.title}" uploaded.')
        if not any_error:
            bid.recompute_total()
            bid.save(update_fields=['total_amount', 'updated_at'])
            messages.success(request, 'Bid draft saved.')
        return redirect(
            'vendor_portal:sourcing_bid_edit', event_pk=event.pk, bpk=bid.pk,
        )

    header_form = BidForm(instance=bid)
    doc_form = BidDocumentForm()
    lines = bid.lines.select_related('event_item').order_by('event_item__line_no')
    return render(request, 'vendor_portal/sourcing/bid_form.html', {
        'event': event, 'bid': bid, 'lines': lines, 'locked': locked,
        'header_form': header_form, 'doc_form': doc_form,
        'documents': bid.documents.all(),
    })


@vendor_required
def portal_bid_submit(request, event_pk, bpk):
    vendor = request.user.vendor
    event = get_object_or_404(SourcingEvent, pk=event_pk, tenant=vendor.tenant)
    bid = get_object_or_404(
        Bid, pk=bpk, event=event, vendor=vendor, tenant=vendor.tenant,
    )
    if request.method == 'POST':
        try:
            submit_bid(bid, request.user)
            messages.success(request, 'Bid submitted. Good luck!')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('vendor_portal:sourcing_my_bids')


@vendor_required
def portal_bid_withdraw(request, event_pk, bpk):
    vendor = request.user.vendor
    event = get_object_or_404(SourcingEvent, pk=event_pk, tenant=vendor.tenant)
    bid = get_object_or_404(
        Bid, pk=bpk, event=event, vendor=vendor, tenant=vendor.tenant,
    )
    if request.method == 'POST':
        try:
            withdraw_bid(bid, request.user)
            messages.success(request, 'Bid withdrawn.')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('vendor_portal:sourcing_my_bids')


@vendor_required
def portal_my_bids(request):
    vendor = request.user.vendor
    bids = Bid.all_objects.filter(vendor=vendor).select_related(
        'event',
    ).order_by('-created_at')
    return render(request, 'vendor_portal/sourcing/my_bids.html', {
        'bids': bids, 'vendor': vendor,
    })


@vendor_required
def portal_bid_detail(request, event_pk, bpk):
    vendor = request.user.vendor
    event = get_object_or_404(SourcingEvent, pk=event_pk, tenant=vendor.tenant)
    bid = get_object_or_404(
        Bid, pk=bpk, event=event, vendor=vendor, tenant=vendor.tenant,
    )
    lines = bid.lines.select_related('event_item').order_by('event_item__line_no')
    documents = bid.documents.all()
    return render(request, 'vendor_portal/sourcing/bid_detail.html', {
        'event': event, 'bid': bid, 'lines': lines, 'documents': documents,
    })


@vendor_required
def portal_invitation_decline(request, ipk):
    vendor = request.user.vendor
    invitee = get_object_or_404(
        SourcingEventInvitee, pk=ipk, vendor=vendor, tenant=vendor.tenant,
    )
    if request.method == 'POST':
        try:
            decline_invitation(invitee, request.user)
            messages.success(request, 'Invitation declined.')
        except ValidationError as exc:
            for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
                messages.error(request, err)
    return redirect('vendor_portal:sourcing_invitations')
