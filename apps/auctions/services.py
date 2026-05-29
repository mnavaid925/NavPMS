"""E-Auction Management domain services (Module 8).

Live, time-bound reverse auctions. All state transitions live here, wrapped in
``@transaction.atomic`` with audit logging via
:func:`apps.tenants.services.record_audit`. Mirrors the Sourcing module's service
style (perms + numbering + lifecycle + analytics) but adds the real-time bidding
core: an atomic :func:`place_bid` (``select_for_update`` on the auction row),
lazy clock transitions, anti-snipe extension, rank recompute and a blind
visibility gate for the vendor portal.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from apps.tenants.services import record_audit

from .models import (
    PARTICIPANT_ACTIVE_STATUSES, Auction, AuctionBid, AuctionParticipant,
)

# Roles allowed to create/configure/run auctions (mirrors Sourcing MANAGE_ROLES).
MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
# Monitoring (console / results) additionally allows approvers.
MONITOR_ROLES = MANAGE_ROLES + ('approver',)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _has_role(user, roles):
    """True if the user holds any of ``roles`` (string slugs).

    ``User.role`` is a CharField (a slug string like ``'buyer'``), mirroring
    Sourcing's ``getattr(user, 'role', '') in MANAGE_ROLES`` check. The
    ``getattr(role, 'slug'/'name')`` fallback keeps this working if ``role`` is
    ever promoted to a FK object.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'is_tenant_admin', False):
        return True
    role = getattr(user, 'role', None)
    if isinstance(role, str):
        role_slug = role
    else:
        role_slug = getattr(role, 'slug', None) or getattr(role, 'name', None)
    return role_slug in roles


def can_manage_auction(user):
    """May create/configure/run auctions and place manual bids."""
    return _has_role(user, MANAGE_ROLES)


def can_monitor_auction(user):
    """May view the live console / results (managers + approvers)."""
    return _has_role(user, MONITOR_ROLES)


# ---------------------------------------------------------------------------
# Visibility gate
# ---------------------------------------------------------------------------
def auction_state_for(user, auction):
    """Single source of truth for what a given user may see on an auction.

    Returns a string view-level flag:
      * ``'full'``           — buyer/manager: complete leaderboard + identities.
      * ``'self'``           — vendor participant: own rank/bid only (blind).
      * ``None``             — no access (non-participant vendor / outsider).

    Mirrors Sourcing's ``bid_visible_to`` two-path pattern.
    """
    if not user or not user.is_authenticated:
        return None
    # Vendor portal user — only if an actual participant of this auction.
    if getattr(user, 'is_vendor_user', False):
        vendor = getattr(user, 'vendor', None)
        if not vendor:
            return None
        is_participant = AuctionParticipant.all_objects.filter(
            auction=auction, vendor=vendor).exists()
        return 'self' if is_participant else None
    # Buyer side.
    if can_monitor_auction(user):
        return 'full'
    return None


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def next_auction_number(tenant):
    """Generate the next gap-free ``AUC-<SLUG>-NNNNN`` for ``tenant``."""
    slug = (tenant.slug or str(tenant.pk))[:6].upper()
    prefix = f'AUC-{slug}-'
    last = (
        Auction.all_objects
        .filter(tenant=tenant, auction_number__startswith=prefix)
        .order_by('-auction_number')
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.auction_number.rsplit('-', 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    number = f'{prefix}{seq:05d}'
    while Auction.all_objects.filter(
            tenant=tenant, auction_number=number).exists():
        seq += 1
        number = f'{prefix}{seq:05d}'
    return number


# ---------------------------------------------------------------------------
# Lazy clock
# ---------------------------------------------------------------------------
def refresh_auction_state(auction, user=None):
    """Apply lazy clock transitions to ``auction`` based on the wall clock.

    ``scheduled → live`` once ``now >= start_at``; ``live → closed`` once
    ``now >= end_at``. Idempotent — safe to call at the top of every console /
    poll / place_bid. Audited only when the status actually flips. Returns the
    auction (unsaved status change is persisted in-place).
    """
    now = timezone.now()
    flipped_to = None
    if auction.status == 'scheduled' and auction.start_at and now >= auction.start_at:
        auction.status = 'live'
        flipped_to = 'live'
    if auction.status == 'live' and auction.end_at and now >= auction.end_at:
        auction.status = 'closed'
        flipped_to = 'closed'
    if flipped_to:
        auction.save(update_fields=['status', 'updated_at'])
        record_audit(
            auction.tenant, user, f'auction.{flipped_to}',
            target_type='Auction', target_id=str(auction.id),
            message=f'{auction.auction_number} auto-{flipped_to} (clock)',
        )
    return auction


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def validate_auction_for_publish(auction):
    """Raise ``ValidationError`` unless the auction is ready to publish.

    Returns a list of non-blocking warnings on success.
    """
    errors = []
    warnings = []
    if not auction.lots.exists():
        errors.append('Add at least one lot before publishing.')
    if not auction.participants.exists():
        errors.append('Invite at least one vendor before publishing.')
    if not auction.start_at or not auction.end_at:
        errors.append('Set both a start and end time before publishing.')
    elif auction.start_at >= auction.end_at:
        errors.append('End time must be after the start time.')
    elif auction.start_at < timezone.now():
        warnings.append('Start time is in the past; the auction will go live immediately.')
    if auction.starting_price is None or auction.starting_price <= Decimal('0.00'):
        errors.append('Starting price (the ceiling) must be greater than zero.')
    if auction.decrement_value is None or auction.decrement_value <= Decimal('0.00'):
        errors.append('Decrement value must be greater than zero.')
    if (auction.reserve_price is not None
            and auction.starting_price is not None
            and auction.reserve_price > auction.starting_price):
        errors.append('Reserve price cannot exceed the starting price.')
    if errors:
        raise ValidationError(errors)
    return warnings


def publish_auction(auction, user):
    """Transition draft → scheduled (validated)."""
    if auction.status != 'draft':
        raise ValidationError('Only draft auctions can be published.')
    warnings = validate_auction_for_publish(auction)
    with transaction.atomic():
        auction.status = 'scheduled'
        auction.save(update_fields=['status', 'updated_at'])
        record_audit(
            auction.tenant, user, 'auction.published',
            target_type='Auction', target_id=str(auction.id),
            message=f'{auction.auction_number} → scheduled',
        )
    return warnings


def start_auction(auction, user):
    """Manual "Start now": scheduled → live (sets start_at if unset)."""
    with transaction.atomic():
        if auction.status != 'scheduled':
            raise ValidationError('Only scheduled auctions can be started.')
        now = timezone.now()
        if not auction.start_at or auction.start_at > now:
            auction.start_at = now
        auction.status = 'live'
        auction.save(update_fields=['status', 'start_at', 'updated_at'])
        record_audit(
            auction.tenant, user, 'auction.started',
            target_type='Auction', target_id=str(auction.id),
            message=f'{auction.auction_number} started manually',
        )
    return auction


def close_auction(auction, user):
    """Transition live → closed (manual close; sets end_at to now if later)."""
    with transaction.atomic():
        if auction.status != 'live':
            raise ValidationError('Only live auctions can be closed.')
        now = timezone.now()
        if not auction.end_at or auction.end_at > now:
            auction.end_at = now
        auction.status = 'closed'
        auction.save(update_fields=['status', 'end_at', 'updated_at'])
        record_audit(
            auction.tenant, user, 'auction.closed',
            target_type='Auction', target_id=str(auction.id),
            message=f'{auction.auction_number} closed',
        )
    return auction


def cancel_auction(auction, user, reason):
    """Cancel a draft/scheduled/live auction with a reason."""
    with transaction.atomic():
        if not auction.can_cancel:
            raise ValidationError('This auction can no longer be cancelled.')
        auction.status = 'cancelled'
        auction.cancelled_reason = (reason or '').strip()
        auction.cancelled_at = timezone.now()
        auction.cancelled_by = user
        auction.save(update_fields=[
            'status', 'cancelled_reason', 'cancelled_at', 'cancelled_by',
            'updated_at',
        ])
        record_audit(
            auction.tenant, user, 'auction.cancelled',
            level='warning',
            target_type='Auction', target_id=str(auction.id),
            message=f'{auction.auction_number} cancelled: {auction.cancelled_reason}'[:255],
        )
    return auction


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------
def invite_vendors(auction, vendor_ids, user):
    """Bulk-invite active vendors, skipping duplicates and blocked vendors."""
    with transaction.atomic():
        from apps.vendors.models import Vendor
        invited = []
        for vendor in Vendor.objects.filter(
                id__in=vendor_ids, tenant=auction.tenant).exclude(
                status__in=('suspended', 'blacklisted', 'inactive')):
            participant, created = AuctionParticipant.objects.get_or_create(
                auction=auction, vendor=vendor, tenant=auction.tenant,
                defaults={'invited_by': user},
            )
            if created:
                invited.append(participant)
        record_audit(
            auction.tenant, user, 'auction.vendors.invited',
            target_type='Auction', target_id=str(auction.id),
            message=f'{len(invited)} invited',
        )
    return invited


def remove_participant(participant, user):
    """Remove an invited participant (only before they have bid)."""
    auction = participant.auction
    if participant.bid_count:
        raise ValidationError('Cannot remove a vendor who has already bid.')
    with transaction.atomic():
        vendor_label = str(participant.vendor)
        pid = participant.id
        participant.delete()
        record_audit(
            auction.tenant, user, 'auction.participant.removed',
            target_type='AuctionParticipant', target_id=str(pid),
            message=f'{vendor_label} removed from {auction.auction_number}',
        )
    return auction


def accept_invitation(participant, user):
    """Vendor accepts an invitation: invited → accepted."""
    with transaction.atomic():
        if participant.status != 'invited':
            raise ValidationError('This invitation can no longer be accepted.')
        participant.status = 'accepted'
        participant.responded_at = timezone.now()
        participant.save(update_fields=['status', 'responded_at', 'updated_at'])
        record_audit(
            participant.tenant, user, 'auction.invitation.accepted',
            target_type='AuctionParticipant', target_id=str(participant.id),
            message=f'{participant.vendor} accepted {participant.auction.auction_number}',
        )
    return participant


def decline_invitation(participant, user):
    """Vendor declines an invitation: invited/accepted → declined."""
    with transaction.atomic():
        if participant.status not in ('invited', 'accepted'):
            raise ValidationError('This invitation can no longer be declined.')
        participant.status = 'declined'
        participant.responded_at = timezone.now()
        participant.save(update_fields=['status', 'responded_at', 'updated_at'])
        record_audit(
            participant.tenant, user, 'auction.invitation.declined',
            target_type='AuctionParticipant', target_id=str(participant.id),
            message=f'{participant.vendor} declined {participant.auction.auction_number}',
        )
    return participant


def withdraw_participant(participant, user):
    """Vendor withdraws from a live auction: active → withdrawn."""
    with transaction.atomic():
        if participant.status not in PARTICIPANT_ACTIVE_STATUSES:
            raise ValidationError('You are not an active participant in this auction.')
        participant.status = 'withdrawn'
        participant.responded_at = timezone.now()
        participant.save(update_fields=['status', 'responded_at', 'updated_at'])
        record_audit(
            participant.tenant, user, 'auction.participant.withdrawn',
            level='warning',
            target_type='AuctionParticipant', target_id=str(participant.id),
            message=f'{participant.vendor} withdrew from {participant.auction.auction_number}',
        )
        recompute_ranks(participant.auction)
    return participant


# ---------------------------------------------------------------------------
# Bidding core
# ---------------------------------------------------------------------------
def current_best(auction):
    """Lowest current bid among active participants, or ``None``."""
    best = (
        AuctionParticipant.all_objects
        .filter(
            auction=auction,
            status__in=PARTICIPANT_ACTIVE_STATUSES,
            current_bid_amount__isnull=False,
        )
        .order_by('current_bid_amount')
        .values_list('current_bid_amount', flat=True)
        .first()
    )
    return best


def recompute_ranks(auction):
    """Re-rank active participants by ``current_bid_amount`` ascending (1=best).

    Unbid / inactive participants are left unranked (``current_rank=None``).
    """
    ranked = list(
        AuctionParticipant.all_objects
        .filter(
            auction=auction,
            status__in=PARTICIPANT_ACTIVE_STATUSES,
            current_bid_amount__isnull=False,
        )
        .order_by('current_bid_amount', 'last_bid_at', 'id')
    )
    for index, participant in enumerate(ranked, start=1):
        if participant.current_rank != index:
            participant.current_rank = index
            participant.save(update_fields=['current_rank', 'updated_at'])
    # Clear ranks for anyone no longer in the ranked set.
    AuctionParticipant.all_objects.filter(auction=auction).exclude(
        id__in=[p.id for p in ranked]
    ).exclude(current_rank__isnull=True).update(current_rank=None)
    return ranked


def place_bid(auction, vendor, amount, user, source='portal'):
    """Place a bid on a live auction — the concurrency-safe core.

    Serialised via ``select_for_update`` on the auction row inside
    ``@transaction.atomic``. Validates (in order): auction is live, the vendor is
    an active participant, ``amount`` > 0, ``amount`` <= ``starting_price``
    (ceiling) and ``amount`` <= ``current_best - effective_decrement`` (must beat
    the global best by the configured decrement; the first bid only needs to meet
    the ceiling). On success creates an ``AuctionBid`` ledger row, updates the
    participant denorm, recomputes ranks, applies the anti-snipe extension and
    records an audit entry.

    Raises ``ValidationError`` with a clear message on any rule break so the JSON
    endpoint can surface it. Returns the created ``AuctionBid``.
    """
    if amount is None:
        raise ValidationError('Enter a bid amount.')
    amount = Decimal(amount).quantize(Decimal('0.01'))

    with transaction.atomic():
        # Lock the auction row so simultaneous bids are serialised.
        auction = Auction.all_objects.select_for_update().get(pk=auction.pk)
        refresh_auction_state(auction, user)

        if auction.status != 'live':
            raise ValidationError('This auction is not currently live.')

        participant = AuctionParticipant.all_objects.filter(
            auction=auction, vendor=vendor).first()
        if not participant or participant.status not in PARTICIPANT_ACTIVE_STATUSES:
            raise ValidationError('You are not an active participant in this auction.')

        if amount <= Decimal('0.00'):
            raise ValidationError('Bid amount must be greater than zero.')

        if amount > auction.starting_price:
            raise ValidationError(
                f'Bid must not exceed the starting price of {auction.starting_price}.')

        best = current_best(auction)
        if best is not None:
            max_allowed = auction.required_next_max(best)
            if amount > max_allowed:
                decrement = auction.effective_decrement(best)
                raise ValidationError(
                    f'Bid must be at most {max_allowed} (beat the current best of '
                    f'{best} by at least {decrement}).')

        now = timezone.now()

        # Anti-snipe: a valid bid inside the window extends the end time.
        triggered_extension = False
        if (auction.end_at
                and auction.anti_snipe_seconds
                and auction.anti_snipe_extension_seconds
                and auction.extension_count < auction.max_extensions):
            remaining = (auction.end_at - now).total_seconds()
            if 0 < remaining <= auction.anti_snipe_seconds:
                auction.end_at = auction.end_at + timezone.timedelta(
                    seconds=auction.anti_snipe_extension_seconds)
                auction.extension_count += 1
                triggered_extension = True
                auction.save(update_fields=[
                    'end_at', 'extension_count', 'updated_at'])

        was_leading = best is None or amount < best

        bid = AuctionBid.objects.create(
            tenant=auction.tenant,
            auction=auction,
            participant=participant,
            vendor=vendor,
            amount=amount,
            placed_by=user,
            source=source,
            was_leading=was_leading,
            triggered_extension=triggered_extension,
        )

        # Update participant denormalised standing.
        participant.current_bid_amount = amount
        participant.bid_count = (participant.bid_count or 0) + 1
        participant.last_bid_at = now
        if participant.status == 'invited':
            participant.status = 'accepted'
            if not participant.responded_at:
                participant.responded_at = now
        participant.save(update_fields=[
            'current_bid_amount', 'bid_count', 'last_bid_at', 'status',
            'responded_at', 'updated_at'])

        recompute_ranks(auction)

        # Persist rank-at-placement now that ranks are recomputed.
        participant.refresh_from_db(fields=['current_rank'])
        bid.rank_at_placement = participant.current_rank
        bid.save(update_fields=['rank_at_placement'])

        record_audit(
            auction.tenant, user, 'auction.bid.placed',
            target_type='Auction', target_id=str(auction.id),
            message=f'{vendor} bid {amount} on {auction.auction_number} '
                    f'(rank {participant.current_rank})',
            payload={
                'amount': str(amount),
                'rank': participant.current_rank,
                'was_leading': was_leading,
                'triggered_extension': triggered_extension,
                'source': source,
            },
        )
    return bid


# ---------------------------------------------------------------------------
# Live payload (JSON poll endpoints)
# ---------------------------------------------------------------------------
def live_payload(auction, user):
    """Serialisable dict for the live console / vendor bidding poll endpoints.

    Buyers (view='full') get the complete leaderboard with vendor identities.
    Vendor participants (view='self') get a blind view per ``rank_visibility``:
    their own rank/bid + the leading price, never competitor identities.

    Always re-runs the lazy clock first so the poll keeps the server
    authoritative. The ``end_at``/``server_now`` ISO timestamps drive the
    client-side countdown.
    """
    refresh_auction_state(auction, user)
    now = timezone.now()
    best = current_best(auction)

    participants = list(
        AuctionParticipant.all_objects
        .filter(auction=auction, status__in=PARTICIPANT_ACTIVE_STATUSES)
        .select_related('vendor')
    )
    bidder_count = sum(1 for p in participants if p.bid_count)

    payload = {
        'auction_id': auction.id,
        'auction_number': auction.auction_number,
        'status': auction.status,
        'is_live': auction.is_live,
        'is_finished': auction.is_finished,
        'currency': auction.currency,
        'server_now': now.isoformat(),
        'end_at': auction.end_at.isoformat() if auction.end_at else None,
        'start_at': auction.start_at.isoformat() if auction.start_at else None,
        'seconds_remaining': auction.seconds_remaining,
        'extension_count': auction.extension_count,
        'max_extensions': auction.max_extensions,
        'starting_price': str(auction.starting_price),
        'leading_price': str(best) if best is not None else None,
        'participant_count': len(participants),
        'bidder_count': bidder_count,
    }

    view = auction_state_for(user, auction)

    if view == 'full':
        payload['view'] = 'full'
        payload['leaderboard'] = [
            {
                'participant_id': p.id,
                'vendor_id': p.vendor_id,
                'vendor_name': str(p.vendor),
                'rank': p.current_rank,
                'current_bid': str(p.current_bid_amount) if p.current_bid_amount is not None else None,
                'bid_count': p.bid_count,
                'last_bid_at': p.last_bid_at.isoformat() if p.last_bid_at else None,
                'status': p.status,
            }
            for p in sorted(
                participants,
                key=lambda x: (x.current_rank is None, x.current_rank or 0),
            )
        ]
    elif view == 'self':
        vendor = getattr(user, 'vendor', None)
        me = next((p for p in participants if p.vendor_id == getattr(vendor, 'id', None)), None)
        payload['view'] = 'self'
        payload['my_rank'] = me.current_rank if me else None
        payload['my_bid'] = (
            str(me.current_bid_amount) if me and me.current_bid_amount is not None else None
        )
        payload['my_status'] = me.status if me else None
        payload['next_valid_max'] = str(auction.required_next_max(best))
        # rank_visibility controls how much of the standing the vendor sees.
        if auction.rank_visibility == 'rank_only':
            payload['leading_price'] = None
        elif auction.rank_visibility == 'full':
            payload['leaderboard'] = [
                {
                    'rank': p.current_rank,
                    'current_bid': str(p.current_bid_amount) if p.current_bid_amount is not None else None,
                    'is_me': p.vendor_id == getattr(vendor, 'id', None),
                }
                for p in sorted(
                    participants,
                    key=lambda x: (x.current_rank is None, x.current_rank or 0),
                )
            ]
        # default 'rank_and_leading' keeps my_rank + leading_price only.
    else:
        payload['view'] = None

    return payload


# ---------------------------------------------------------------------------
# Award / finalize
# ---------------------------------------------------------------------------
def finalize_auction(auction, user, winner_vendor=None):
    """Award a closed auction to the winning vendor.

    Winner defaults to the lowest valid bid (rank 1); ``winner_vendor`` overrides
    for compliance. Sets the denormalised award on the auction, flips the winning
    participant to ``won`` and the rest to ``lost``, transitions status to
    ``awarded`` and records an audit entry (with a reserve-price warning when the
    winning bid sits above the hidden reserve).
    """
    with transaction.atomic():
        auction = Auction.all_objects.select_for_update().get(pk=auction.pk)
        if auction.status not in ('closed', 'live'):
            raise ValidationError('Only closed auctions can be awarded.')
        if auction.status == 'live':
            # Allow finalize to implicitly close a still-live auction.
            close_auction(auction, user)
            auction.refresh_from_db()

        recompute_ranks(auction)

        if winner_vendor is not None:
            winner = AuctionParticipant.all_objects.filter(
                auction=auction, vendor=winner_vendor,
                status__in=PARTICIPANT_ACTIVE_STATUSES,
                current_bid_amount__isnull=False,
            ).first()
            if not winner:
                raise ValidationError(
                    'The selected vendor has no valid bid to award.')
        else:
            winner = (
                AuctionParticipant.all_objects
                .filter(
                    auction=auction,
                    status__in=PARTICIPANT_ACTIVE_STATUSES,
                    current_bid_amount__isnull=False,
                )
                .order_by('current_bid_amount', 'last_bid_at', 'id')
                .first()
            )
            if not winner:
                raise ValidationError('No valid bids to award.')

        # Flip participant outcomes.
        for participant in AuctionParticipant.all_objects.filter(auction=auction):
            if participant.id == winner.id:
                participant.status = 'won'
                participant.is_winner = True
            elif participant.status in PARTICIPANT_ACTIVE_STATUSES:
                participant.status = 'lost'
                participant.is_winner = False
            else:
                continue
            participant.save(update_fields=['status', 'is_winner', 'updated_at'])

        auction.awarded_vendor = winner.vendor
        auction.awarded_amount = winner.current_bid_amount
        auction.awarded_at = timezone.now()
        auction.status = 'awarded'
        auction.save(update_fields=[
            'awarded_vendor', 'awarded_amount', 'awarded_at', 'status',
            'updated_at'])

        level = 'info'
        reserve_note = ''
        if (auction.reserve_price is not None
                and winner.current_bid_amount > auction.reserve_price):
            level = 'warning'
            reserve_note = ' (above reserve price)'

        record_audit(
            auction.tenant, user, 'auction.awarded',
            level=level,
            target_type='Auction', target_id=str(auction.id),
            message=f'{auction.auction_number} awarded to {winner.vendor} '
                    f'at {winner.current_bid_amount}{reserve_note}',
            payload={
                'vendor_id': winner.vendor_id,
                'amount': str(winner.current_bid_amount),
                'above_reserve': bool(reserve_note),
            },
        )
    return auction


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def compute_auction_savings(auction):
    """Return baseline/awarded savings figures for ``auction``.

    Baseline = ``total_budget`` (Σ lot estimate) falling back to
    ``starting_price``; awarded = the winning amount.
    """
    baseline = auction.total_budget or auction.starting_price or Decimal('0.00')
    awarded = auction.awarded_amount or Decimal('0.00')
    savings = baseline - awarded
    if baseline > 0 and awarded > 0:
        savings_pct = (savings / baseline * Decimal('100')).quantize(Decimal('0.01'))
    else:
        savings_pct = Decimal('0.00')
    return {
        'baseline': baseline.quantize(Decimal('0.01')),
        'awarded': awarded.quantize(Decimal('0.01')),
        'savings': savings.quantize(Decimal('0.01')) if awarded > 0 else Decimal('0.00'),
        'savings_pct': savings_pct,
    }


def tenant_auction_metrics(tenant, period_start=None, period_end=None):
    """Aggregate e-auction KPIs for the tenant analytics dashboard."""
    qs = Auction.objects.filter(tenant=tenant)
    if period_start:
        qs = qs.filter(created_at__gte=period_start)
    if period_end:
        qs = qs.filter(created_at__lte=period_end)

    by_status = dict(qs.values_list('status').annotate(n=Count('id')))
    total = qs.count()
    awarded_qs = qs.filter(status='awarded')

    total_baseline = Decimal('0.00')
    total_awarded = Decimal('0.00')
    for auction in awarded_qs:
        figures = compute_auction_savings(auction)
        total_baseline += figures['baseline']
        total_awarded += figures['awarded']
    total_savings = total_baseline - total_awarded
    if total_baseline > 0 and total_awarded > 0:
        savings_pct = (total_savings / total_baseline * Decimal('100')).quantize(Decimal('0.01'))
    else:
        savings_pct = Decimal('0.00')

    agg = AuctionParticipant.objects.filter(auction__in=qs).aggregate(
        total_participants=Count('id'),
        total_bids=Sum('bid_count'),
    )
    avg_participants = (
        Decimal(agg['total_participants'] or 0) / Decimal(total)
    ).quantize(Decimal('0.01')) if total else Decimal('0.00')

    return {
        'total_auctions': total,
        'by_status': by_status,
        'live': by_status.get('live', 0),
        'scheduled': by_status.get('scheduled', 0),
        'draft': by_status.get('draft', 0),
        'awarded': by_status.get('awarded', 0),
        'cancelled': by_status.get('cancelled', 0),
        'total_baseline': total_baseline.quantize(Decimal('0.01')),
        'total_awarded': total_awarded.quantize(Decimal('0.01')),
        'total_savings': total_savings.quantize(Decimal('0.01')) if total_awarded > 0 else Decimal('0.00'),
        'savings_pct': savings_pct,
        'total_participants': agg['total_participants'] or 0,
        'total_bids': agg['total_bids'] or 0,
        'avg_participants': avg_participants,
    }


def auction_analytics(auction):
    """Per-auction analytics: savings, counts, extensions, duration + price-drop curve."""
    savings = compute_auction_savings(auction)

    participants = AuctionParticipant.all_objects.filter(auction=auction)
    participant_count = participants.count()
    bidder_count = participants.filter(bid_count__gt=0).count()
    bid_count = AuctionBid.all_objects.filter(auction=auction).count()

    # Price-drop curve: each leading bid over time (lowest running amount).
    bids = list(
        AuctionBid.all_objects
        .filter(auction=auction)
        .order_by('placed_at', 'id')
        .values('amount', 'placed_at', 'was_leading')
    )
    curve = []
    running_best = None
    for entry in bids:
        amt = entry['amount']
        if running_best is None or amt < running_best:
            running_best = amt
            curve.append({
                't': entry['placed_at'].isoformat() if entry['placed_at'] else None,
                'price': str(amt),
            })

    duration_seconds = None
    if auction.start_at and auction.end_at:
        duration_seconds = int((auction.end_at - auction.start_at).total_seconds())

    return {
        'savings': savings,
        'participant_count': participant_count,
        'bidder_count': bidder_count,
        'bid_count': bid_count,
        'extension_count': auction.extension_count,
        'duration_seconds': duration_seconds,
        'price_drop_curve': curve,
    }
