"""Module 6 service layer: numbering, event/bid workflow, sealed-bid visibility,
panel scoring, ranking, award flow, and analytics."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Sum
from django.utils import timezone

from apps.tenants.services import record_audit

from .models import (
    Bid, BidEvaluation, BidLine, SourcingAward, SourcingCriterion,
    SourcingEvent, SourcingEventInvitee, SourcingEventItem,
    EVENT_POST_CLOSE_STATUSES,
)


# ---------- Permission helpers ----------

MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
EVALUATE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer', 'approver')


def can_manage_sourcing(user) -> bool:
    """Tenant admin / procurement manager / buyer can manage events."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_tenant_admin', False):
        return True
    return getattr(user, 'role', '') in MANAGE_ROLES


def can_evaluate(user) -> bool:
    """Anyone who can manage, plus approvers, can score bids."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'is_tenant_admin', False):
        return True
    return getattr(user, 'role', '') in EVALUATE_ROLES


# ---------- Sealed-bid visibility ----------

def bid_visible_to(user, bid: Bid) -> bool:
    """Sealed-bid gate.

    A vendor portal user can always read their own bid.
    Buyers can only read bids after the event closes (`closed`, `under_evaluation`,
    `awarded`, `cancelled`).
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_vendor_user', False):
        return bid.vendor_id == getattr(user, 'vendor_id', None)
    # Buyer side
    if not can_manage_sourcing(user) and not can_evaluate(user):
        return False
    return bid.event.status in EVENT_POST_CLOSE_STATUSES


# ---------- Numbering ----------

def next_event_number(tenant) -> str:
    """Generate the next SRC-<SLUG>-NNNNN number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = SourcingEvent.all_objects.filter(tenant=tenant).count() + 1
    number = f'SRC-{slug}-{count:05d}'
    while SourcingEvent.all_objects.filter(
        tenant=tenant, event_number=number,
    ).exists():
        count += 1
        number = f'SRC-{slug}-{count:05d}'
    return number


def next_bid_number(tenant) -> str:
    """Generate the next BID-<SLUG>-NNNNN number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = Bid.all_objects.filter(tenant=tenant).count() + 1
    number = f'BID-{slug}-{count:05d}'
    while Bid.all_objects.filter(tenant=tenant, bid_number=number).exists():
        count += 1
        number = f'BID-{slug}-{count:05d}'
    return number


# ---------- REQ -> RFQ ----------

@transaction.atomic
def create_event_from_requisition(req, user) -> SourcingEvent:
    """Spawn a draft SourcingEvent pre-filled from an approved requisition."""
    event = SourcingEvent.all_objects.create(
        tenant=req.tenant,
        event_number=next_event_number(req.tenant),
        title=f'RFQ for {req.title}',
        description=req.justification or '',
        event_type='rfq',
        currency=req.currency,
        estimated_value=req.estimated_total or Decimal('0.00'),
        status='draft',
        created_by=user,
        requisition=req,
    )
    for idx, line in enumerate(req.lines.all(), start=1):
        SourcingEventItem.all_objects.create(
            tenant=req.tenant,
            event=event,
            line_no=idx,
            item_description=line.description,
            uom=line.unit or 'EA',
            quantity=line.quantity or Decimal('1'),
            est_unit_price=line.unit_price or Decimal('0'),
            account_code=line.account_code,
            required_date=line.required_date,
        )
    record_audit(
        tenant=req.tenant, user=user,
        action='sourcing.event_created_from_requisition',
        target_type='SourcingEvent', target_id=event.pk,
        message=f'From {req.number}',
    )
    return event


# ---------- Event workflow ----------

def validate_event_can_publish(event: SourcingEvent) -> list[str]:
    """Return a list of validation errors blocking publish; empty means OK."""
    errors = []
    if not event.items.exists():
        errors.append('Add at least one item to the event.')
    if not event.invitees.exists():
        errors.append('Invite at least one vendor.')
    if not event.criteria.exists():
        errors.append('Add at least one evaluation criterion.')
    else:
        total_weight = sum(
            (c.weight or Decimal('0')) for c in event.criteria.all()
        )
        if total_weight != Decimal('100'):
            errors.append(
                f'Criteria weights must sum to 100 (currently {total_weight}).'
            )
    if not event.close_at:
        errors.append('Set a close date/time for the event.')
    return errors


@transaction.atomic
def publish_event(event: SourcingEvent, user) -> SourcingEvent:
    """draft -> scheduled, or draft -> open if publish_at <= now."""
    if event.status != 'draft':
        raise ValidationError('Only draft events can be published.')
    errors = validate_event_can_publish(event)
    if errors:
        raise ValidationError(errors)
    now = timezone.now()
    if event.publish_at and event.publish_at <= now:
        event.status = 'open'
    else:
        event.status = 'scheduled'
    event.save(update_fields=['status', 'updated_at'])
    record_audit(
        tenant=event.tenant, user=user,
        action='sourcing.event_published',
        target_type='SourcingEvent', target_id=event.pk,
        message=event.status,
    )
    return event


@transaction.atomic
def open_event(event: SourcingEvent, user) -> SourcingEvent:
    if event.status not in ('scheduled', 'draft'):
        raise ValidationError('Only scheduled or draft events can be opened.')
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
        action='sourcing.event_opened',
        target_type='SourcingEvent', target_id=event.pk,
    )
    return event


@transaction.atomic
def close_event(event: SourcingEvent, user) -> SourcingEvent:
    if event.status != 'open':
        raise ValidationError('Only open events can be closed.')
    event.status = 'closed'
    event.close_at = event.close_at or timezone.now()
    event.save(update_fields=['status', 'close_at', 'updated_at'])
    # Any drafts still open at close are rejected; submitted bids stay locked.
    event.bids.filter(status='draft').update(
        status='rejected', updated_at=timezone.now(),
    )
    record_audit(
        tenant=event.tenant, user=user,
        action='sourcing.event_closed',
        target_type='SourcingEvent', target_id=event.pk,
    )
    return event


@transaction.atomic
def cancel_event(event: SourcingEvent, user, reason: str) -> SourcingEvent:
    if event.status not in (
        'draft', 'scheduled', 'open', 'closed', 'under_evaluation',
    ):
        raise ValidationError('This event cannot be cancelled.')
    event.status = 'cancelled'
    event.cancelled_reason = (reason or '').strip() or 'No reason given'
    event.cancelled_at = timezone.now()
    event.cancelled_by = user
    event.save(update_fields=[
        'status', 'cancelled_reason', 'cancelled_at', 'cancelled_by', 'updated_at',
    ])
    # Withdraw any in-flight bids.
    event.bids.filter(status__in=('draft', 'submitted', 'under_review')).update(
        status='withdrawn', withdrawn_at=timezone.now(), updated_at=timezone.now(),
    )
    record_audit(
        tenant=event.tenant, user=user,
        action='sourcing.event_cancelled',
        target_type='SourcingEvent', target_id=event.pk,
        message=event.cancelled_reason,
    )
    return event


# ---------- Invitations ----------

@transaction.atomic
def invite_vendors(event: SourcingEvent, vendor_ids, user) -> list[SourcingEventInvitee]:
    """Bulk-invite vendors; ignores duplicates and already-blocked vendors."""
    from apps.vendors.models import Vendor

    created = []
    eligible_vendors = Vendor.all_objects.filter(
        tenant=event.tenant, pk__in=vendor_ids,
    ).exclude(status__in=('suspended', 'blacklisted', 'inactive'))
    existing_ids = set(
        event.invitees.values_list('vendor_id', flat=True),
    )
    for vendor in eligible_vendors:
        if vendor.pk in existing_ids:
            continue
        invitee = SourcingEventInvitee.all_objects.create(
            tenant=event.tenant,
            event=event,
            vendor=vendor,
            invited_by=user,
            status='invited',
        )
        created.append(invitee)
    if created:
        record_audit(
            tenant=event.tenant, user=user,
            action='sourcing.vendors_invited',
            target_type='SourcingEvent', target_id=event.pk,
            message=f'{len(created)} vendor(s)',
        )
    return created


def decline_invitation(invitee: SourcingEventInvitee, user) -> SourcingEventInvitee:
    invitee.status = 'declined'
    invitee.responded_at = timezone.now()
    invitee.save(update_fields=['status', 'responded_at', 'updated_at'])
    record_audit(
        tenant=invitee.tenant, user=user,
        action='sourcing.invitation_declined',
        target_type='SourcingEventInvitee', target_id=invitee.pk,
    )
    return invitee


# ---------- Bid workflow ----------

@transaction.atomic
def start_bid(event: SourcingEvent, vendor, user) -> Bid:
    """Vendor portal: create a draft Bid with one BidLine per event item."""
    if event.status != 'open':
        raise ValidationError('This event is not accepting bids.')
    if vendor.status in ('suspended', 'blacklisted', 'inactive'):
        raise ValidationError('Your vendor account is blocked.')
    # Ensure invitee exists; vendors not invited cannot bid.
    invitee = event.invitees.filter(vendor=vendor).first()
    if not invitee:
        raise ValidationError('You are not invited to this event.')

    existing = event.bids.filter(vendor=vendor).first()
    if existing:
        return existing

    bid = Bid.all_objects.create(
        tenant=event.tenant,
        event=event,
        vendor=vendor,
        bid_number=next_bid_number(event.tenant),
        status='draft',
        currency=event.currency,
    )
    for item in event.items.all():
        BidLine.all_objects.create(
            tenant=event.tenant,
            bid=bid,
            event_item=item,
            quantity_offered=item.quantity,
            unit_price=Decimal('0.00'),
        )
    record_audit(
        tenant=event.tenant, user=user,
        action='sourcing.bid_started',
        target_type='Bid', target_id=bid.pk,
        message=f'{vendor.legal_name} on {event.event_number}',
    )
    return bid


@transaction.atomic
def submit_bid(bid: Bid, user) -> Bid:
    """Validate and finalise a draft bid; mark invitee as submitted."""
    if bid.status != 'draft':
        raise ValidationError('Only draft bids can be submitted.')
    if bid.event.status != 'open':
        raise ValidationError('Bidding has closed for this event.')

    # Compliance: every line must have a positive price + quantity.
    compliant = True
    for line in bid.lines.all():
        if (line.unit_price or Decimal('0')) <= 0:
            compliant = False
            break
        if (line.quantity_offered or Decimal('0')) <= 0:
            compliant = False
            break
    bid.is_compliant = compliant
    bid.recompute_total()
    bid.status = 'submitted'
    bid.submitted_by = user
    bid.submitted_at = timezone.now()
    bid.save(update_fields=[
        'total_amount', 'is_compliant', 'status', 'submitted_by', 'submitted_at',
        'updated_at',
    ])
    invitee = bid.event.invitees.filter(vendor=bid.vendor).first()
    if invitee:
        invitee.status = 'submitted'
        invitee.responded_at = timezone.now()
        invitee.save(update_fields=['status', 'responded_at', 'updated_at'])
    record_audit(
        tenant=bid.tenant, user=user,
        action='sourcing.bid_submitted',
        target_type='Bid', target_id=bid.pk,
        message=f'{bid.bid_number} total {bid.total_amount}',
    )
    return bid


@transaction.atomic
def withdraw_bid(bid: Bid, user) -> Bid:
    if bid.event.status != 'open':
        raise ValidationError('Bids can only be withdrawn while the event is open.')
    if bid.status not in ('draft', 'submitted'):
        raise ValidationError('This bid cannot be withdrawn.')
    bid.status = 'withdrawn'
    bid.withdrawn_at = timezone.now()
    bid.save(update_fields=['status', 'withdrawn_at', 'updated_at'])
    invitee = bid.event.invitees.filter(vendor=bid.vendor).first()
    if invitee:
        invitee.status = 'withdrawn'
        invitee.responded_at = timezone.now()
        invitee.save(update_fields=['status', 'responded_at', 'updated_at'])
    record_audit(
        tenant=bid.tenant, user=user,
        action='sourcing.bid_withdrawn',
        target_type='Bid', target_id=bid.pk,
    )
    return bid


# ---------- Evaluation & ranking ----------

@transaction.atomic
def record_evaluation(bid: Bid, criterion: SourcingCriterion, evaluator,
                      score, comment: str = '') -> BidEvaluation:
    """Upsert a (bid, criterion, evaluator) score; recompute rank/score."""
    if bid.event_id != criterion.event_id:
        raise ValidationError('Criterion does not belong to this event.')
    if bid.event.status not in EVENT_POST_CLOSE_STATUSES:
        raise ValidationError('Bids cannot be evaluated until the event closes.')
    score_d = Decimal(str(score))
    if score_d < Decimal('0') or score_d > (criterion.max_score or Decimal('100')):
        raise ValidationError(
            f'Score must be between 0 and {criterion.max_score}.'
        )

    evaluation, _ = BidEvaluation.all_objects.update_or_create(
        tenant=bid.tenant, bid=bid, criterion=criterion, evaluator=evaluator,
        defaults={'score': score_d, 'comment': comment or ''},
    )
    if bid.status == 'submitted':
        bid.status = 'under_review'
        bid.save(update_fields=['status', 'updated_at'])
    if bid.event.status == 'closed':
        bid.event.status = 'under_evaluation'
        bid.event.save(update_fields=['status', 'updated_at'])
    recompute_bid_scores(bid.event)
    return evaluation


def recompute_bid_scores(event: SourcingEvent) -> None:
    """Re-derive overall_score + rank across all bids on the event."""
    criteria = list(event.criteria.all())
    total_weight = sum((c.weight or Decimal('0')) for c in criteria) or Decimal('0')

    bids = list(event.bids.exclude(status='withdrawn'))
    for bid in bids:
        if not criteria or total_weight == 0:
            bid.overall_score = Decimal('0')
        else:
            weighted = Decimal('0')
            for crit in criteria:
                rows = bid.evaluations.filter(criterion=crit)
                if not rows.exists():
                    continue
                avg = rows.aggregate(a=Avg('score'))['a'] or Decimal('0')
                # Convert AVG to Decimal — Django may return float for Avg.
                avg_d = Decimal(str(avg))
                norm = (avg_d / (crit.max_score or Decimal('100')))
                weighted += norm * (crit.weight or Decimal('0'))
            bid.overall_score = weighted.quantize(Decimal('0.01'))
        bid.save(update_fields=['overall_score', 'updated_at'])

    # Rank: highest score first, lowest total amount breaks ties.
    bids = list(event.bids.exclude(status='withdrawn').order_by(
        '-overall_score', 'total_amount',
    ))
    for idx, bid in enumerate(bids, start=1):
        bid.rank = idx
        bid.save(update_fields=['rank', 'updated_at'])


def shortlist_bid(bid: Bid, user) -> Bid:
    if bid.status not in ('submitted', 'under_review'):
        raise ValidationError('Bid is not in a shortlistable state.')
    bid.status = 'shortlisted'
    bid.save(update_fields=['status', 'updated_at'])
    record_audit(
        tenant=bid.tenant, user=user,
        action='sourcing.bid_shortlisted',
        target_type='Bid', target_id=bid.pk,
    )
    return bid


def reject_bid(bid: Bid, user) -> Bid:
    if bid.status == 'awarded':
        raise ValidationError('Cannot reject an awarded bid.')
    bid.status = 'rejected'
    bid.save(update_fields=['status', 'updated_at'])
    record_audit(
        tenant=bid.tenant, user=user,
        action='sourcing.bid_rejected',
        target_type='Bid', target_id=bid.pk,
    )
    return bid


# ---------- Award ----------

@transaction.atomic
def recommend_award(event: SourcingEvent, vendor, amount, user,
                    justification: str = '') -> SourcingAward:
    """Append a SourcingAward (status='recommended') for a vendor."""
    if event.status not in ('closed', 'under_evaluation'):
        raise ValidationError(
            'Awards can only be recommended once the event has closed.'
        )
    bid = event.bids.filter(vendor=vendor).exclude(status='withdrawn').first()
    if not bid:
        raise ValidationError('This vendor has no eligible bid.')
    if not event.allow_partial_award and event.awards.exists():
        raise ValidationError(
            'This event already has a recommendation. Enable partial award to add more.'
        )
    award = SourcingAward.all_objects.create(
        tenant=event.tenant,
        event=event,
        vendor=vendor,
        bid=bid,
        award_amount=Decimal(str(amount or bid.total_amount)),
        currency=bid.currency,
        status='recommended',
        justification=justification or '',
        awarded_by=user,
    )
    record_audit(
        tenant=event.tenant, user=user,
        action='sourcing.award_recommended',
        target_type='SourcingAward', target_id=award.pk,
        message=f'{vendor.legal_name} @ {award.award_amount}',
    )
    return award


@transaction.atomic
def finalize_award(event: SourcingEvent, user) -> SourcingEvent:
    """Promote recommended awards to approved/contracted, flip statuses across bids."""
    recs = list(event.awards.filter(status='recommended'))
    if not recs:
        raise ValidationError('No recommendations to finalise.')
    winning_vendor_ids = set()
    total_amount = Decimal('0.00')
    for award in recs:
        award.status = 'approved'
        award.save(update_fields=['status', 'updated_at'])
        award.bid.status = 'awarded'
        award.bid.save(update_fields=['status', 'updated_at'])
        winning_vendor_ids.add(award.vendor_id)
        total_amount += award.award_amount

    # Mark losing bids as rejected (only those not awarded).
    event.bids.exclude(vendor_id__in=winning_vendor_ids).exclude(
        status__in=('withdrawn', 'rejected', 'draft'),
    ).update(status='rejected', updated_at=timezone.now())

    # Denormalise winner on the event (first winner if multi-award).
    primary_award = recs[0]
    event.status = 'awarded'
    event.awarded_vendor = primary_award.vendor
    event.awarded_amount = total_amount
    event.awarded_at = timezone.now()
    event.save(update_fields=[
        'status', 'awarded_vendor', 'awarded_amount', 'awarded_at', 'updated_at',
    ])
    record_audit(
        tenant=event.tenant, user=user,
        action='sourcing.event_awarded',
        target_type='SourcingEvent', target_id=event.pk,
        message=f'Awarded to {primary_award.vendor.legal_name} for {total_amount}',
    )
    return event


# ---------- Analytics ----------

def compute_event_savings(event: SourcingEvent) -> dict:
    """Per-event savings dict: estimated, awarded, savings, savings_pct."""
    estimated = event.estimated_value or event.total_estimated or Decimal('0')
    awarded = event.awarded_amount or Decimal('0')
    savings = estimated - awarded if awarded > 0 else Decimal('0')
    pct = (savings / estimated * Decimal('100')) if estimated > 0 and savings > 0 else Decimal('0')
    return {
        'estimated': estimated.quantize(Decimal('0.01')),
        'awarded': awarded.quantize(Decimal('0.01')),
        'savings': savings.quantize(Decimal('0.01')),
        'savings_pct': pct.quantize(Decimal('0.01')),
    }


def tenant_sourcing_metrics(tenant, period_start=None, period_end=None) -> dict:
    """Tenant-wide analytics for the dashboard."""
    qs = SourcingEvent.all_objects.filter(tenant=tenant)
    if period_start:
        qs = qs.filter(created_at__gte=period_start)
    if period_end:
        qs = qs.filter(created_at__lte=period_end)

    awarded = qs.filter(status='awarded')
    total_estimated = awarded.aggregate(s=Sum('estimated_value'))['s'] or Decimal('0')
    total_awarded = awarded.aggregate(s=Sum('awarded_amount'))['s'] or Decimal('0')
    savings = (total_estimated - total_awarded) if total_awarded else Decimal('0')
    savings_pct = (
        (savings / total_estimated * Decimal('100'))
        if total_estimated and savings > 0
        else Decimal('0')
    )
    counts_by_status = defaultdict(int)
    for ev in qs.values('status').annotate(c=Sum('id') * 0 + 1):
        counts_by_status[ev['status']] = ev['c']
    invited = SourcingEventInvitee.all_objects.filter(event__in=qs).count()
    submitted = SourcingEventInvitee.all_objects.filter(
        event__in=qs, status='submitted',
    ).count()
    response_rate = (
        (Decimal(submitted) / Decimal(invited) * Decimal('100'))
        if invited else Decimal('0')
    )
    return {
        'total_events': qs.count(),
        'open_events': qs.filter(status='open').count(),
        'awarded_events': awarded.count(),
        'total_estimated': total_estimated.quantize(Decimal('0.01')),
        'total_awarded': total_awarded.quantize(Decimal('0.01')),
        'savings': savings.quantize(Decimal('0.01')),
        'savings_pct': savings_pct.quantize(Decimal('0.01')),
        'response_rate': response_rate.quantize(Decimal('0.01')),
        'invited_count': invited,
        'submitted_count': submitted,
    }
