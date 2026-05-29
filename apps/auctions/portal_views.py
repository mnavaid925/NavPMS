"""Module 8 vendor-portal views: auction invitations, accept/decline, live bidding.

Mirrors :mod:`apps.sourcing.portal_views`: every view is gated by
``@vendor_required``, scoped to ``request.user.vendor`` and its tenant, and the
lifecycle actions delegate to :mod:`apps.auctions.services`. The live bidding
page reuses ``static/js/auction.js`` against the JSON state / place-bid endpoints
defined here; ``services.live_payload`` returns the vendor-blind ``view='self'``
payload automatically because the requester is a participant.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.vendors.decorators import vendor_required

from . import services
from .forms import PlaceBidForm
from .models import Auction, AuctionParticipant


def _get_participant(request, pk):
    """Return ``(auction, participant)`` for the current vendor or ``(None, None)``.

    The auction is scoped to the vendor's tenant; a vendor that was never invited
    has no participant row and is bounced back to the invitations list.
    """
    vendor = request.user.vendor
    auction = get_object_or_404(Auction, pk=pk, tenant=vendor.tenant)
    participant = AuctionParticipant.objects.filter(
        auction=auction, vendor=vendor,
    ).first()
    return auction, participant


@vendor_required
def portal_auction_list(request):
    """List this vendor's auction participations (invitations + standings)."""
    vendor = request.user.vendor
    participations = (
        AuctionParticipant.objects
        .filter(vendor=vendor, tenant=vendor.tenant)
        .select_related('auction', 'auction__category')
        .order_by('-invited_at')
    )
    return render(request, 'vendor_portal/auctions/list.html', {
        'participations': participations, 'vendor': vendor,
    })


@vendor_required
def portal_auction_detail(request, pk):
    """Read-only auction terms + accept/decline + enter-live entry point."""
    auction, participant = _get_participant(request, pk)
    if not participant:
        messages.error(request, 'You are not invited to this auction.')
        return redirect('vendor_portal:auction_invitations')
    lots = auction.lots.all().order_by('lot_no', 'id')
    return render(request, 'vendor_portal/auctions/detail.html', {
        'auction': auction, 'participant': participant, 'lots': lots,
    })


@vendor_required
@require_POST
def portal_accept(request, pk):
    """Vendor accepts an invitation: invited -> accepted."""
    auction, participant = _get_participant(request, pk)
    if not participant:
        messages.error(request, 'You are not invited to this auction.')
        return redirect('vendor_portal:auction_invitations')
    try:
        services.accept_invitation(participant, request.user)
        messages.success(request, 'Invitation accepted. You can now bid once live.')
    except ValidationError as exc:
        for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
            messages.error(request, err)
    return redirect('vendor_portal:auction_event_detail', pk=auction.pk)


@vendor_required
@require_POST
def portal_decline(request, pk):
    """Vendor declines an invitation: invited/accepted -> declined."""
    auction, participant = _get_participant(request, pk)
    if not participant:
        messages.error(request, 'You are not invited to this auction.')
        return redirect('vendor_portal:auction_invitations')
    try:
        services.decline_invitation(participant, request.user)
        messages.success(request, 'Invitation declined.')
    except ValidationError as exc:
        for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
            messages.error(request, err)
    return redirect('vendor_portal:auction_invitations')


@vendor_required
@require_POST
def portal_withdraw(request, pk):
    """Vendor withdraws from an auction: active -> withdrawn."""
    auction, participant = _get_participant(request, pk)
    if not participant:
        messages.error(request, 'You are not invited to this auction.')
        return redirect('vendor_portal:auction_invitations')
    try:
        services.withdraw_participant(participant, request.user)
        messages.success(request, 'You have withdrawn from this auction.')
    except ValidationError as exc:
        for err in (exc.messages if hasattr(exc, 'messages') else [str(exc)]):
            messages.error(request, err)
    return redirect('vendor_portal:auction_invitations')


@vendor_required
def portal_bidding(request, pk):
    """Live bidding page — JS polls the state endpoint and POSTs bids via AJAX."""
    auction, participant = _get_participant(request, pk)
    if not participant:
        messages.error(request, 'You are not invited to this auction.')
        return redirect('vendor_portal:auction_invitations')
    if participant.status in ('declined', 'withdrawn'):
        messages.error(
            request, 'You are no longer a participant in this auction.',
        )
        return redirect('vendor_portal:auction_event_detail', pk=auction.pk)
    return render(request, 'vendor_portal/auctions/bidding.html', {
        'auction': auction,
        'participant': participant,
        'state_url': reverse('vendor_portal:auction_state', kwargs={'pk': auction.pk}),
        'place_bid_url': reverse(
            'vendor_portal:auction_place_bid', kwargs={'pk': auction.pk},
        ),
    })


@vendor_required
def portal_state(request, pk):
    """JSON poll endpoint — vendor-blind ``view='self'`` payload."""
    auction, participant = _get_participant(request, pk)
    if not participant:
        return JsonResponse(
            {'ok': False, 'error': 'Not a participant.'}, status=403,
        )
    return JsonResponse(services.live_payload(auction, request.user))


@vendor_required
@require_POST
def portal_place_bid(request, pk):
    """AJAX bid submission. Returns ``{ok: True, **payload}`` or ``{ok: False, error}``."""
    vendor = request.user.vendor
    auction, participant = _get_participant(request, pk)
    if not participant:
        return JsonResponse(
            {'ok': False, 'error': 'Not a participant.'}, status=403,
        )
    form = PlaceBidForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {'ok': False, 'error': 'Enter a valid amount.'}, status=400,
        )
    try:
        services.place_bid(
            auction, vendor, form.cleaned_data['amount'], request.user,
            source='portal',
        )
    except ValidationError as exc:
        return JsonResponse(
            {'ok': False, 'error': ' '.join(exc.messages)}, status=400,
        )
    payload = services.live_payload(auction, request.user)
    return JsonResponse({'ok': True, **payload})
