"""Order Fulfillment & Tracking domain services (Module 12).

All state transitions live here, wrapped in ``@transaction.atomic`` with audit logging
via :func:`apps.tenants.services.record_audit`. Mirrors the Module 11 (purchase_orders)
service style — perms + numbering + lifecycle + alert sweep + analytics — and adds:

  * ASN advice from the supplier (draft -> advised),
  * a pluggable carrier tracking sync (``apps/fulfillment/carriers.py``) that appends an
    append-only ShipmentTrackingEvent ledger and advances the shipment status, and
  * delivery confirmation that posts the received quantities back into the PO lines via
    :func:`apps.purchase_orders.services.record_line_receipt` — *idempotently* (a
    ``posted_quantity`` watermark per shipment line) and *guarded* (never over-receipts).

Split delivery is enforced by :func:`remaining_to_ship_line`; backorders track the
out-of-stock remainder.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Sum
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant
from apps.portal.models import Notification
from apps.tenants.services import record_audit
from apps.purchase_orders import services as po_services
from apps.purchase_orders.models import (
    PO_CHANGE_ORDERABLE_STATUSES,
    PurchaseOrder,
)

from . import carriers
from .models import (
    SHIPMENT_FINISHED_STATUSES,
    Backorder,
    Shipment,
    ShipmentLine,
    ShipmentStatusEvent,
    ShipmentTrackingEvent,
)

# Roles allowed to create/configure/manage shipments (mirrors purchase_orders).
MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
# Viewing (analytics / read-only) additionally allows approvers.
VIEW_ROLES = MANAGE_ROLES + ('approver',)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _has_role(user, roles):
    """True if the user holds any of ``roles`` (string slugs)."""
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


def can_manage_fulfillment(user):
    """May create/advise/track/confirm/cancel shipments and manage backorders."""
    return _has_role(user, MANAGE_ROLES)


def can_view_fulfillment(user):
    """May view shipments / tracking / analytics (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Visibility gate (vendor portal)
# ---------------------------------------------------------------------------
def shipment_visible_to(user, shipment):
    """True if ``user`` may view ``shipment``.

    Internal managers/approvers may view any shipment in their tenant; a vendor
    portal user may view only shipments for their own vendor (they create and advise
    these ASNs themselves).
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_vendor_user', False):
        return getattr(user, 'vendor_id', None) == shipment.vendor_id
    return can_view_fulfillment(user)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def record_status_event(shipment, status, user, note=''):
    """Append an immutable lifecycle timeline row."""
    return ShipmentStatusEvent.all_objects.create(
        tenant=shipment.tenant, shipment=shipment, status=status,
        note=(note or '')[:255], actor=user,
    )


def _notify(user, shipment, *, category, priority, title, message):
    """Create a portal Notification linking to a shipment."""
    if not user:
        return None
    try:
        link = reverse('fulfillment:shipment_detail', kwargs={'pk': shipment.pk})
    except Exception:
        link = ''
    return Notification.all_objects.create(
        tenant=shipment.tenant, user=user, category=category, priority=priority,
        title=title[:160], message=message, link_url=link,
    )


def _notify_vendor(shipment, *, category, priority, title, message):
    """Notify the supplier's portal user (if any)."""
    portal_user = getattr(shipment.vendor, 'portal_user', None) if shipment.vendor_id else None
    return _notify(portal_user, shipment, category=category, priority=priority,
                   title=title, message=message)


def _notify_buyer(shipment, *, category, priority, title, message):
    """Notify the internal PO owner (the buyer who placed the order)."""
    owner = getattr(shipment.purchase_order, 'owner', None)
    return _notify(owner, shipment, category=category, priority=priority,
                   title=title, message=message)


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def next_shipment_number(tenant):
    """Generate the next gap-free ``SHP-<SLUG>-NNNNN`` for ``tenant``."""
    slug = (tenant.slug or str(tenant.pk))[:6].upper()
    prefix = f'SHP-{slug}-'
    last = (
        Shipment.all_objects
        .filter(tenant=tenant, shipment_number__startswith=prefix)
        .order_by('-shipment_number')
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.shipment_number.rsplit('-', 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    number = f'{prefix}{seq:05d}'
    while Shipment.all_objects.filter(
            tenant=tenant, shipment_number=number).exists():
        seq += 1
        number = f'{prefix}{seq:05d}'
    return number


# ---------------------------------------------------------------------------
# Split-delivery helpers
# ---------------------------------------------------------------------------
def remaining_to_ship_line(po_line, exclude_shipment_line=None):
    """Quantity of ``po_line`` not yet covered by (non-cancelled) shipment lines.

    Used to guard against over-shipping a PO line across split deliveries:
    ``ordered − Σ shipped on other live shipment lines``.
    """
    qs = ShipmentLine.all_objects.filter(
        purchase_order_line=po_line,
    ).exclude(shipment__status='cancelled')
    if exclude_shipment_line is not None and exclude_shipment_line.pk:
        qs = qs.exclude(pk=exclude_shipment_line.pk)
    shipped = qs.aggregate(s=Sum('shipped_quantity'))['s'] or Decimal('0')
    return (po_line.quantity or Decimal('0')) - shipped


def remaining_to_ship(po):
    """Return ``[(po_line, remaining_qty), ...]`` for the PO's open lines."""
    out = []
    for line in po.lines.exclude(delivery_status='cancelled'):
        out.append((line, remaining_to_ship_line(line)))
    return out


# ---------------------------------------------------------------------------
# 1. Shipment / ASN creation
# ---------------------------------------------------------------------------
def create_shipment(*, tenant, user, purchase_order, **fields):
    """Create a draft shipment against a PO with a collision-safe number.

    Serialises numbering with a ``select_for_update`` lock on the tenant and retries
    on a unique-constraint collision (mirrors ``purchase_orders.create_purchase_order``).
    """
    if not purchase_order.vendor_id:
        raise ValidationError('The purchase order has no supplier to ship from.')
    fields.pop('vendor', None)  # always derived from the PO
    last_exc = None
    for _attempt in range(5):
        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=tenant.pk)
                shipment = Shipment.all_objects.create(
                    tenant=tenant,
                    shipment_number=next_shipment_number(tenant),
                    purchase_order=purchase_order,
                    vendor=purchase_order.vendor,
                    status='draft',
                    created_by=user,
                    **fields,
                )
                record_status_event(shipment, 'draft', user, 'Shipment created')
                record_audit(
                    tenant, user, 'fulfillment.shipment.created',
                    target_type='Shipment', target_id=str(shipment.id),
                    message=f'{shipment.shipment_number} for {purchase_order.po_number}',
                )
            return shipment
        except IntegrityError as exc:
            last_exc = exc
    raise last_exc


def add_shipment_line(shipment, *, purchase_order_line, shipped_quantity, **fields):
    """Add a line to a draft shipment, guarding against over-shipping the PO line."""
    shipped_quantity = Decimal(str(shipped_quantity or '0'))
    if shipped_quantity <= 0:
        raise ValidationError('Shipped quantity must be greater than zero.')
    remaining = remaining_to_ship_line(purchase_order_line)
    if shipped_quantity > remaining:
        raise ValidationError(
            f'Cannot ship {shipped_quantity}: only {remaining} of PO line '
            f'{purchase_order_line.line_no} remains to ship.'
        )
    next_no = (shipment.lines.aggregate(m=Max('line_no'))['m'] or 0) + 1
    return ShipmentLine.all_objects.create(
        tenant=shipment.tenant, shipment=shipment,
        purchase_order_line=purchase_order_line,
        line_no=fields.pop('line_no', next_no),
        description=fields.pop('description', '') or purchase_order_line.description,
        uom=fields.pop('uom', '') or purchase_order_line.uom,
        shipped_quantity=shipped_quantity,
        line_status='pending',
        **fields,
    )


# ---------------------------------------------------------------------------
# 1. ASN advice (draft -> advised)
# ---------------------------------------------------------------------------
def validate_shipment_for_advice(shipment):
    """Raise ``ValidationError`` unless the shipment is ready to advise."""
    errors = []
    lines = list(shipment.lines.all())
    if not lines:
        errors.append('Add at least one line before sending the ASN.')
    if sum((ln.shipped_quantity or Decimal('0') for ln in lines), Decimal('0')) <= 0:
        errors.append('The shipment must declare a quantity to ship.')
    if errors:
        raise ValidationError(errors)
    return []


def advise_shipment(shipment, user):
    """Supplier notifies the buyer of a pending shipment: draft -> advised (ASN)."""
    with transaction.atomic():
        # Lock first, THEN check the precondition on the fresh row — otherwise a
        # concurrent transition could slip past a stale in-memory status (TOCTOU).
        shipment = Shipment.all_objects.select_for_update().get(pk=shipment.pk)
        if not shipment.can_advise:
            raise ValidationError('Only a draft shipment can be advised.')
        validate_shipment_for_advice(shipment)
        shipment.status = 'advised'
        shipment.advised_at = timezone.now()
        shipment.advised_by = user
        shipment.delivery_alerted_at = None
        shipment.save(update_fields=[
            'status', 'advised_at', 'advised_by', 'delivery_alerted_at', 'updated_at',
        ])
        shipment.lines.filter(line_status='pending').update(line_status='shipped')
        record_status_event(shipment, 'advised', user, 'ASN sent')
        record_audit(
            shipment.tenant, user, 'fulfillment.shipment.advised',
            target_type='Shipment', target_id=str(shipment.id),
            message=f'{shipment.shipment_number} advised for {shipment.purchase_order.po_number}',
        )
        _notify_buyer(
            shipment, category='delivery', priority='normal',
            title=f'Shipment advised: {shipment.shipment_number}',
            message=f'{shipment.vendor.legal_name} advised shipment '
                    f'{shipment.shipment_number} for {shipment.purchase_order.po_number}.',
        )
    return shipment


# ---------------------------------------------------------------------------
# 2. Real-time freight tracking
# ---------------------------------------------------------------------------
_STATUS_ORDER = [
    'draft', 'advised', 'in_transit', 'out_for_delivery', 'delivered',
    'received', 'closed',
]
_CARRIER_TO_SHIPMENT = {
    'label_created': 'advised',
    'picked_up': 'in_transit',
    'in_transit': 'in_transit',
    'out_for_delivery': 'out_for_delivery',
    'delivered': 'delivered',
}


def _advance_status(carrier_status, current):
    """Map a carrier status to a shipment status, advancing only forward."""
    target = _CARRIER_TO_SHIPMENT.get(carrier_status)
    if not target:
        return current
    if current in SHIPMENT_FINISHED_STATUSES:
        return current
    try:
        if _STATUS_ORDER.index(target) > _STATUS_ORDER.index(current):
            return target
    except ValueError:
        return current
    return current


def sync_tracking(shipment, user=None):
    """Pull carrier tracking, append new events, and advance the shipment status."""
    with transaction.atomic():
        shipment = Shipment.all_objects.select_for_update().get(pk=shipment.pk)
        if not shipment.can_track:
            raise ValidationError(
                'Tracking can only be synced while the shipment is in transit.')
        if not shipment.tracking_number:
            raise ValidationError('Add a tracking number before syncing tracking.')
        carrier = carriers.get_carrier(shipment.carrier_code)
        result = carrier.fetch_tracking(
            shipment.tracking_number, service_level=shipment.service_level,
            ship_date=shipment.ship_date,
        )
        added = 0
        for upd in result.updates:
            occurred = upd.occurred_at or timezone.now()
            if ShipmentTrackingEvent.all_objects.filter(
                    shipment=shipment, status_code=upd.status_code,
                    occurred_at=occurred).exists():
                continue
            ShipmentTrackingEvent.all_objects.create(
                tenant=shipment.tenant, shipment=shipment,
                status_code=upd.status_code, description=upd.description,
                location=upd.location, occurred_at=occurred, source='carrier',
                raw=upd.raw or {}, recorded_by=user,
            )
            added += 1

        old_status = shipment.status
        if result.current_status:
            shipment.freight_status = result.current_status[:60]
        if result.estimated_delivery and not shipment.estimated_delivery_date:
            shipment.estimated_delivery_date = result.estimated_delivery
        shipment.tracking_last_synced_at = timezone.now()
        new_status = _advance_status(result.current_status, shipment.status)
        fields = [
            'freight_status', 'estimated_delivery_date', 'tracking_last_synced_at',
            'updated_at',
        ]
        if new_status != old_status:
            shipment.status = new_status
            fields.append('status')
            if new_status == 'delivered':
                shipment.actual_delivery_date = timezone.localdate()
                fields.append('actual_delivery_date')
        shipment.save(update_fields=fields)
        if new_status != old_status:
            record_status_event(
                shipment, new_status, user,
                f'Carrier update: {result.current_status}',
            )
        record_audit(
            shipment.tenant, user, 'fulfillment.shipment.tracking_synced',
            target_type='Shipment', target_id=str(shipment.id),
            message=f'{shipment.shipment_number}: {added} new event(s), '
                    f'status {result.current_status}',
        )
    return shipment


def add_manual_tracking_event(shipment, user, *, status_code, description='',
                              location='', occurred_at=None, advance=True):
    """Record a manually-entered tracking event (and optionally advance status)."""
    with transaction.atomic():
        shipment = Shipment.all_objects.select_for_update().get(pk=shipment.pk)
        if not shipment.can_track:
            raise ValidationError(
                'Tracking events can only be added while the shipment is in transit.')
        occurred = occurred_at or timezone.now()
        event = ShipmentTrackingEvent.all_objects.create(
            tenant=shipment.tenant, shipment=shipment,
            status_code=status_code, description=description[:255],
            location=location[:160], occurred_at=occurred, source='manual',
            recorded_by=user,
        )
        if advance:
            old_status = shipment.status
            new_status = _advance_status(status_code, shipment.status)
            if new_status != old_status:
                shipment.status = new_status
                fields = ['status', 'updated_at']
                if new_status == 'delivered':
                    shipment.actual_delivery_date = timezone.localdate()
                    fields.append('actual_delivery_date')
                shipment.freight_status = status_code[:60]
                fields.append('freight_status')
                shipment.save(update_fields=fields)
                record_status_event(shipment, new_status, user,
                                    f'Manual update: {status_code}')
        record_audit(
            shipment.tenant, user, 'fulfillment.shipment.tracking_added',
            target_type='Shipment', target_id=str(shipment.id),
            message=f'{shipment.shipment_number}: {status_code}',
        )
    return event


# ---------------------------------------------------------------------------
# 3. Delivery confirmation (posts receipts into the PO — idempotent + guarded)
# ---------------------------------------------------------------------------
def confirm_delivery(shipment, user, *, delivered_at=None, condition='good',
                     post_receipt=True, note='', line_quantities=None):
    """Confirm a shipment delivered, capturing arrival and posting receipts to the PO.

    ``line_quantities`` optionally overrides the received quantity per shipment-line id
    (default = the shipped quantity = a full receipt). When ``post_receipt`` is set, the
    per-line delta ``received − posted`` (skipping <= 0) is posted to the PO line via
    :func:`apps.purchase_orders.services.record_line_receipt`, pre-validated against the
    PO outstanding so the PO's own over-receipt guard is never tripped. Re-running posts
    nothing (the ``posted_quantity`` watermark makes it idempotent).
    """
    with transaction.atomic():
        shipment = Shipment.all_objects.select_for_update().get(pk=shipment.pk)
        if not shipment.can_confirm_delivery:
            raise ValidationError('This shipment cannot be confirmed delivered.')
        po = shipment.purchase_order
        delivered_at = delivered_at or timezone.now()
        lines = list(shipment.lines.select_related('purchase_order_line'))

        # 1. Resolve received quantity per line (default = shipped).
        for ln in lines:
            qty = None
            if line_quantities and ln.id in line_quantities:
                qty = Decimal(str(line_quantities[ln.id]))
            if qty is None:
                qty = ln.shipped_quantity or Decimal('0')
            if qty < 0:
                raise ValidationError('Received quantity cannot be negative.')
            if qty > (ln.shipped_quantity or Decimal('0')):
                raise ValidationError(
                    f'Line {ln.line_no}: received cannot exceed the shipped quantity.'
                )
            ln.received_quantity = qty

        # 2. Pre-validate the receipt postings against the PO (no over-receipt).
        if post_receipt:
            if po.status not in PO_CHANGE_ORDERABLE_STATUSES:
                raise ValidationError(
                    f'Cannot post receipts: purchase order {po.po_number} is '
                    f'{po.get_status_display()}.'
                )
            for ln in lines:
                delta = (ln.received_quantity or Decimal('0')) - (ln.posted_quantity or Decimal('0'))
                if delta <= 0:
                    continue
                outstanding = ln.purchase_order_line.outstanding_quantity
                if delta > outstanding:
                    raise ValidationError(
                        f'Line {ln.line_no}: receiving {delta} exceeds the PO outstanding '
                        f'({outstanding}). Raise a PO change order first.'
                    )

        # 3. Apply: post each line's delta to the PO, then persist the shipment line.
        for ln in lines:
            if post_receipt:
                delta = (ln.received_quantity or Decimal('0')) - (ln.posted_quantity or Decimal('0'))
                if delta > 0:
                    po_services.record_line_receipt(
                        po, ln.purchase_order_line, delta, user)
                    ln.posted_quantity = ln.received_quantity
            shipped = ln.shipped_quantity or Decimal('0')
            recv = ln.received_quantity or Decimal('0')
            if shipped > 0 and recv >= shipped:
                ln.line_status = 'received'
            elif recv < shipped:
                ln.line_status = 'short'
            ln.save(update_fields=[
                'received_quantity', 'posted_quantity', 'line_status', 'updated_at',
            ])

        # 4. Stamp the shipment.
        shipment.status = 'received' if post_receipt else 'delivered'
        shipment.delivered_at = delivered_at
        if not shipment.actual_delivery_date:
            shipment.actual_delivery_date = delivered_at.date()
        shipment.confirmed_by = user
        shipment.received_condition = condition or 'good'
        shipment.delivery_note = (note or '').strip()[:255]
        shipment.save(update_fields=[
            'status', 'delivered_at', 'actual_delivery_date', 'confirmed_by',
            'received_condition', 'delivery_note', 'updated_at',
        ])
        record_status_event(
            shipment, shipment.status, user,
            f'Delivery confirmed ({shipment.get_received_condition_display()})',
        )
        record_audit(
            shipment.tenant, user, 'fulfillment.shipment.delivered',
            target_type='Shipment', target_id=str(shipment.id),
            message=f'{shipment.shipment_number} delivered '
                    f'({shipment.received_condition}); posted={post_receipt}',
        )
        _notify_buyer(
            shipment, category='delivery', priority='normal',
            title=f'Shipment delivered: {shipment.shipment_number}',
            message=f'{shipment.shipment_number} for {po.po_number} was confirmed '
                    f'delivered ({shipment.get_received_condition_display()}).',
        )
    return shipment


# ---------------------------------------------------------------------------
# Cancellation & close-out
# ---------------------------------------------------------------------------
def cancel_shipment(shipment, user, reason=''):
    """Cancel a shipment that has not yet been delivered/received."""
    with transaction.atomic():
        shipment = Shipment.all_objects.select_for_update().get(pk=shipment.pk)
        if not shipment.can_cancel:
            raise ValidationError(
                'A delivered or received shipment can no longer be cancelled.'
            )
        shipment.status = 'cancelled'
        shipment.cancel_reason = (reason or '').strip()[:255]
        shipment.cancelled_at = timezone.now()
        shipment.save(update_fields=[
            'status', 'cancel_reason', 'cancelled_at', 'updated_at',
        ])
        record_status_event(shipment, 'cancelled', user, shipment.cancel_reason)
        record_audit(
            shipment.tenant, user, 'fulfillment.shipment.cancelled', level='warning',
            target_type='Shipment', target_id=str(shipment.id),
            message=f'{shipment.shipment_number} cancelled: {shipment.cancel_reason}'[:255],
        )
        _notify_buyer(
            shipment, category='info', priority='normal',
            title=f'Shipment cancelled: {shipment.shipment_number}',
            message=f'{shipment.shipment_number} has been cancelled.',
        )
    return shipment


def close_shipment(shipment, user, note=''):
    """Close a delivered/received shipment (terminal book-keeping)."""
    with transaction.atomic():
        shipment = Shipment.all_objects.select_for_update().get(pk=shipment.pk)
        if not shipment.can_close:
            raise ValidationError('Only a delivered shipment can be closed.')
        shipment.status = 'closed'
        shipment.closed_at = timezone.now()
        shipment.save(update_fields=['status', 'closed_at', 'updated_at'])
        record_status_event(shipment, 'closed', user, (note or 'Closed out')[:255])
        record_audit(
            shipment.tenant, user, 'fulfillment.shipment.closed',
            target_type='Shipment', target_id=str(shipment.id),
            message=f'{shipment.shipment_number} closed',
        )
    return shipment


# ---------------------------------------------------------------------------
# 4. Backorder management
# ---------------------------------------------------------------------------
def open_backorder(*, tenant, user, purchase_order_line, quantity, expected_date=None,
                   reason=''):
    """Open a backorder for an undelivered remainder of a PO line."""
    quantity = Decimal(str(quantity or '0'))
    if quantity <= 0:
        raise ValidationError('Backorder quantity must be greater than zero.')
    po = purchase_order_line.purchase_order
    with transaction.atomic():
        bo = Backorder.all_objects.create(
            tenant=tenant, purchase_order=po, purchase_order_line=purchase_order_line,
            quantity=quantity, expected_date=expected_date, status='open',
            reason=(reason or '').strip()[:255], created_by=user,
        )
        record_audit(
            tenant, user, 'fulfillment.backorder.opened',
            target_type='Backorder', target_id=str(bo.id),
            message=f'Backorder {quantity} on {po.po_number} line '
                    f'{purchase_order_line.line_no}',
        )
        owner = getattr(po, 'owner', None)
        if owner:
            try:
                link = reverse('fulfillment:backorder_board')
            except Exception:
                link = ''
            Notification.all_objects.create(
                tenant=tenant, user=owner, category='delivery', priority='normal',
                title=f'Backorder opened: {po.po_number}'[:160],
                message=f'{quantity} of "{purchase_order_line.description}" is '
                        f'backordered on {po.po_number}.',
                link_url=link,
            )
    return bo


def fulfill_backorder(bo, user, shipment=None):
    """Mark a backorder fulfilled (optionally linking the fulfilling shipment)."""
    with transaction.atomic():
        if not bo.is_open:
            raise ValidationError('Only an open backorder can be fulfilled.')
        bo.status = 'fulfilled'
        bo.fulfilled_at = timezone.now()
        bo.fulfilled_by_shipment = shipment
        bo.save(update_fields=[
            'status', 'fulfilled_at', 'fulfilled_by_shipment', 'updated_at',
        ])
        record_audit(
            bo.tenant, user, 'fulfillment.backorder.fulfilled',
            target_type='Backorder', target_id=str(bo.id),
            message=f'Backorder on {bo.purchase_order.po_number} fulfilled',
        )
    return bo


def cancel_backorder(bo, user, reason=''):
    """Cancel an open backorder."""
    with transaction.atomic():
        if not bo.is_open:
            raise ValidationError('Only an open backorder can be cancelled.')
        bo.status = 'cancelled'
        bo.reason = (reason or bo.reason or '').strip()[:255]
        bo.save(update_fields=['status', 'reason', 'updated_at'])
        record_audit(
            bo.tenant, user, 'fulfillment.backorder.cancelled', level='warning',
            target_type='Backorder', target_id=str(bo.id),
            message=f'Backorder on {bo.purchase_order.po_number} cancelled',
        )
    return bo


def scan_backorder_alerts(tenant=None, now=None):
    """Alert overdue backorders + auto-cancel orphans whose PO is finished.

    Idempotent (guarded by ``alerted_at``). Returns counts. Called by the
    ``run_fulfillment_alerts`` command (no ``tenant`` -> all tenants).
    """
    if tenant is None:
        totals = {'overdue': 0, 'orphans_cancelled': 0}
        for t in Tenant.objects.all():
            set_current_tenant(t)
            counts = scan_backorder_alerts(tenant=t, now=now)
            for k in totals:
                totals[k] += counts.get(k, 0)
        return totals

    now = now or timezone.now()
    today = timezone.localdate()
    counts = {'overdue': 0, 'orphans_cancelled': 0}

    # Auto-cancel backorders whose PO has finished (keeps the PO dependency one-way).
    orphans = Backorder.all_objects.filter(
        tenant=tenant, status__in=('open', 'promised'),
        purchase_order__status__in=('closed', 'cancelled'),
    )
    for bo in orphans:
        bo.status = 'cancelled'
        bo.reason = (bo.reason or 'PO closed/cancelled')[:255]
        bo.save(update_fields=['status', 'reason', 'updated_at'])
        record_audit(
            tenant, None, 'fulfillment.backorder.auto_cancelled',
            target_type='Backorder', target_id=str(bo.id),
            message=f'Backorder auto-cancelled ({bo.purchase_order.po_number} finished)',
        )
        counts['orphans_cancelled'] += 1

    overdue = Backorder.all_objects.filter(
        tenant=tenant, status__in=('open', 'promised'),
        expected_date__lt=today, alerted_at__isnull=True,
    ).select_related('purchase_order')
    for bo in overdue:
        owner = getattr(bo.purchase_order, 'owner', None)
        if owner:
            try:
                link = reverse('fulfillment:backorder_board')
            except Exception:
                link = ''
            Notification.all_objects.create(
                tenant=tenant, user=owner, category='deadline', priority='high',
                title=f'Backorder overdue: {bo.purchase_order.po_number}'[:160],
                message=f'A backorder on {bo.purchase_order.po_number} was due '
                        f'{bo.expected_date} and is still open.',
                link_url=link,
            )
        bo.alerted_at = now
        bo.save(update_fields=['alerted_at', 'updated_at'])
        record_audit(
            tenant, None, 'fulfillment.backorder.overdue', level='warning',
            target_type='Backorder', target_id=str(bo.id),
            message=f'Backorder overdue on {bo.purchase_order.po_number}',
        )
        counts['overdue'] += 1

    return counts


# ---------------------------------------------------------------------------
# Alert sweep (overdue delivery)
# ---------------------------------------------------------------------------
def scan_fulfillment_alerts(tenant=None, now=None):
    """Raise overdue-delivery alerts for in-flight shipments. Idempotent.

    A shipment past its estimated delivery date (still in transit / not delivered)
    raises a one-time alert to the PO owner (guarded by ``delivery_alerted_at``).
    Called by the ``run_fulfillment_alerts`` command (no ``tenant`` -> all tenants)
    and lazily by the tracking board.
    """
    if tenant is None:
        totals = {'overdue_delivery': 0}
        for t in Tenant.objects.all():
            set_current_tenant(t)
            counts = scan_fulfillment_alerts(tenant=t, now=now)
            for k in totals:
                totals[k] += counts.get(k, 0)
        return totals

    now = now or timezone.now()
    today = timezone.localdate()
    counts = {'overdue_delivery': 0}

    overdue = Shipment.all_objects.filter(
        tenant=tenant,
        status__in=('advised', 'in_transit', 'out_for_delivery'),
        estimated_delivery_date__lt=today, delivery_alerted_at__isnull=True,
    ).select_related('purchase_order', 'vendor')
    for shipment in overdue:
        days = (today - shipment.estimated_delivery_date).days
        owner = getattr(shipment.purchase_order, 'owner', None)
        if owner:
            _notify(
                owner, shipment, category='deadline', priority='urgent',
                title=f'Shipment delivery overdue: {shipment.shipment_number}',
                message=f'{shipment.shipment_number} for '
                        f'{shipment.purchase_order.po_number} is {days} day(s) past its '
                        f'estimated delivery date ({shipment.estimated_delivery_date}).',
            )
        shipment.delivery_alerted_at = now
        shipment.save(update_fields=['delivery_alerted_at', 'updated_at'])
        record_audit(
            tenant, None, 'fulfillment.shipment.delivery_overdue', level='warning',
            target_type='Shipment', target_id=str(shipment.id),
            message=f'{shipment.shipment_number} delivery overdue ({days}d)',
        )
        counts['overdue_delivery'] += 1

    return counts


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def tenant_fulfillment_metrics(tenant):
    """Aggregate fulfilment KPIs for the tenant analytics dashboard."""
    qs = Shipment.objects.filter(tenant=tenant)
    by_status = dict(qs.values_list('status').annotate(n=Count('id')))
    total = qs.count()

    in_flight = qs.filter(status__in=('advised', 'in_transit', 'out_for_delivery'))
    overdue = sum(1 for s in in_flight if s.is_delivery_overdue)

    delivered_qs = qs.filter(status__in=('delivered', 'received', 'closed'))
    delivered = delivered_qs.count()
    on_time = sum(
        1 for s in delivered_qs
        if s.actual_delivery_date and s.estimated_delivery_date
        and s.actual_delivery_date <= s.estimated_delivery_date
    )
    on_time_pct = int(round(on_time / delivered * 100)) if delivered else 0

    split_pos = (
        qs.exclude(status='cancelled')
        .values('purchase_order')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
        .count()
    )
    open_backorders = Backorder.objects.filter(
        tenant=tenant, status__in=('open', 'promised')).count()
    freight_spend = qs.exclude(status='cancelled').aggregate(
        s=Sum('freight_cost'))['s'] or Decimal('0.00')

    top_carriers = list(
        qs.exclude(status='cancelled').exclude(carrier='')
        .values('carrier')
        .annotate(n=Count('id'))
        .order_by('-n')[:5]
    )

    return {
        'total_shipments': total,
        'by_status': by_status,
        'draft': by_status.get('draft', 0),
        'advised': by_status.get('advised', 0),
        'in_transit': by_status.get('in_transit', 0),
        'out_for_delivery': by_status.get('out_for_delivery', 0),
        'delivered': by_status.get('delivered', 0),
        'received': by_status.get('received', 0),
        'closed': by_status.get('closed', 0),
        'cancelled': by_status.get('cancelled', 0),
        'exception': by_status.get('exception', 0),
        'in_flight': in_flight.count(),
        'overdue_delivery': overdue,
        'on_time_pct': on_time_pct,
        'split_pos': split_pos,
        'open_backorders': open_backorders,
        'freight_spend': freight_spend.quantize(Decimal('0.01')),
        'top_carriers': top_carriers,
    }
