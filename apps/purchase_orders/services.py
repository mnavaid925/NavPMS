"""Purchase Order Management domain services (Module 11).

All state transitions live here, wrapped in ``@transaction.atomic`` with audit
logging via :func:`apps.tenants.services.record_audit`. Mirrors the contracts /
sourcing service style (perms + numbering + lifecycle + analytics) and adds:

  * generation of a draft PO from an approved requisition (lines pre-filled),
  * a dispatch/acknowledge flow that raises a portal Notification to the supplier's
    portal user (no external provider — consistent with the mock payment gateway),
  * change-order versioning that snapshots the previous values and bumps
    ``PurchaseOrder.revision``, and
  * a clock-free alert sweep (awaiting-acknowledgment + overdue-delivery), called by
    the ``run_po_alerts`` command and lazily by the tracking board.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant
from apps.portal.models import Notification
from apps.tenants.services import record_audit

from .models import (
    PO_CHANGE_ORDERABLE_STATUSES,
    PurchaseOrder,
    PurchaseOrderChangeOrder,
    PurchaseOrderLine,
    PurchaseOrderStatusEvent,
)

# Roles allowed to create/configure/manage purchase orders (mirrors contracts).
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


def can_manage_po(user):
    """May create/configure/issue/cancel/close purchase orders."""
    return _has_role(user, MANAGE_ROLES)


def can_view_po(user):
    """May view purchase orders / analytics (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Visibility gate (vendor portal)
# ---------------------------------------------------------------------------
def po_visible_to(user, po):
    """True if ``user`` may view ``po``.

    Internal managers/approvers may view any PO in their tenant; a vendor portal
    user may view only POs issued to their own vendor, and only once dispatched
    (a still-draft PO is never exposed to the supplier).
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_vendor_user', False):
        return (
            getattr(user, 'vendor_id', None) == po.vendor_id
            and po.is_dispatched
        )
    return can_view_po(user)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def record_status_event(po, status, user, note='', change_order=None):
    """Append an immutable lifecycle timeline row."""
    return PurchaseOrderStatusEvent.all_objects.create(
        tenant=po.tenant, purchase_order=po, change_order=change_order,
        status=status, note=(note or '')[:255], actor=user,
    )


def _notify(user, po, *, category, priority, title, message):
    """Create a portal Notification linking to a purchase order."""
    if not user:
        return None
    try:
        link = reverse('purchase_orders:po_detail', kwargs={'pk': po.pk})
    except Exception:
        link = ''
    return Notification.all_objects.create(
        tenant=po.tenant, user=user, category=category, priority=priority,
        title=title[:160], message=message, link_url=link,
    )


def _notify_vendor(po, *, category, priority, title, message):
    """Notify the supplier's portal user (if any)."""
    portal_user = getattr(po.vendor, 'portal_user', None) if po.vendor_id else None
    return _notify(portal_user, po, category=category, priority=priority,
                   title=title, message=message)


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def next_po_number(tenant):
    """Generate the next gap-free ``PO-<SLUG>-NNNNN`` for ``tenant``."""
    slug = (tenant.slug or str(tenant.pk))[:6].upper()
    prefix = f'PO-{slug}-'
    last = (
        PurchaseOrder.all_objects
        .filter(tenant=tenant, po_number__startswith=prefix)
        .order_by('-po_number')
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.po_number.rsplit('-', 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    number = f'{prefix}{seq:05d}'
    while PurchaseOrder.all_objects.filter(
            tenant=tenant, po_number=number).exists():
        seq += 1
        number = f'{prefix}{seq:05d}'
    return number


def next_change_number(po):
    """Return the next ``<po_number>-CO0N`` change-order label."""
    n = PurchaseOrderChangeOrder.all_objects.filter(purchase_order=po).count() + 1
    return f'{po.po_number}-CO{n:02d}'


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------
def recompute_totals(po):
    """Recompute ``subtotal`` and ``total_amount`` from the (non-cancelled) lines."""
    subtotal = sum(
        (line.line_total for line in po.lines.exclude(delivery_status='cancelled')),
        Decimal('0.00'),
    )
    po.subtotal = subtotal
    po.total_amount = (
        subtotal + (po.tax_amount or Decimal('0')) + (po.shipping_amount or Decimal('0'))
    )
    po.save(update_fields=['subtotal', 'total_amount', 'updated_at'])
    return po.total_amount


# ---------------------------------------------------------------------------
# 1. PO Generation
# ---------------------------------------------------------------------------
def create_purchase_order(*, tenant, user, **fields):
    """Create a draft PO with an auto-assigned, collision-safe number.

    Serialises numbering with a ``select_for_update`` row lock on the tenant and
    retries on a unique-constraint collision (mirrors ``contracts.create_contract``).
    """
    last_exc = None
    for _attempt in range(5):
        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=tenant.pk)
                po = PurchaseOrder.all_objects.create(
                    tenant=tenant,
                    po_number=next_po_number(tenant),
                    status='draft',
                    created_by=user,
                    **fields,
                )
                record_status_event(po, 'draft', user, 'Purchase order created')
                record_audit(
                    tenant, user, 'purchase_order.created',
                    target_type='PurchaseOrder', target_id=str(po.id),
                    message=f'{po.po_number}: {po.title}',
                )
            return po
        except IntegrityError as exc:
            last_exc = exc
    raise last_exc


def create_po_from_requisition(req, user, *, mark_converted=True):
    """Generate a draft PO pre-filled from an approved requisition's lines.

    The requisition carries no supplier, so the buyer assigns the vendor before
    issuing. When ``mark_converted`` and the requisition is approved, the
    requisition is flipped to ``converted`` (linking the new PO number).
    """
    with transaction.atomic():
        po = create_purchase_order(
            tenant=req.tenant, user=user,
            title=f'PO for {req.title}'[:200],
            description=req.justification or '',
            currency=req.currency,
            owner=user,
            requisition=req,
            order_date=timezone.localdate(),
            expected_delivery_date=req.required_date,
        )
        for idx, line in enumerate(req.lines.all(), start=1):
            PurchaseOrderLine.all_objects.create(
                tenant=req.tenant, purchase_order=po, line_no=idx,
                description=line.description,
                uom=line.unit or 'unit',
                quantity=line.quantity or Decimal('1'),
                unit_price=line.unit_price or Decimal('0'),
                account_code=line.account_code,
                requisition_line=line,
                required_date=line.required_date,
            )
        recompute_totals(po)
        record_audit(
            req.tenant, user, 'purchase_order.created_from_requisition',
            target_type='PurchaseOrder', target_id=str(po.id),
            message=f'{po.po_number} from {req.number}',
        )
        if mark_converted and req.status == 'approved':
            from apps.requisitions.services import convert_requisition
            convert_requisition(req, user, po_reference=po.po_number)
    return po


# ---------------------------------------------------------------------------
# 2. Dispatch & Acknowledgment
# ---------------------------------------------------------------------------
def validate_po_for_issue(po):
    """Raise ``ValidationError`` unless the PO is ready to dispatch."""
    errors = []
    if not po.vendor_id:
        errors.append('Assign a supplier before issuing the PO.')
    if not po.lines.exclude(delivery_status='cancelled').exists():
        errors.append('Add at least one line item before issuing the PO.')
    if (po.total_amount or Decimal('0')) <= 0:
        errors.append('The PO total must be greater than zero.')
    if errors:
        raise ValidationError(errors)
    return []


def issue_po(po, user, *, dispatch_method='', recipient_email=''):
    """Transition draft → issued (dispatch the PO to the supplier)."""
    with transaction.atomic():
        if po.status != 'draft':
            raise ValidationError('Only draft purchase orders can be issued.')
        recompute_totals(po)
        po.refresh_from_db()
        validate_po_for_issue(po)
        po = PurchaseOrder.all_objects.select_for_update().get(pk=po.pk)

        po.status = 'issued'
        po.issued_at = timezone.now()
        po.issued_by = user
        if dispatch_method:
            po.dispatch_method = dispatch_method
        po.dispatched_to = (
            recipient_email or (po.vendor.email if po.vendor_id else '') or ''
        )[:254]
        if not po.order_date:
            po.order_date = timezone.localdate()
        po.ack_alerted_at = None
        po.save(update_fields=[
            'status', 'issued_at', 'issued_by', 'dispatch_method', 'dispatched_to',
            'order_date', 'ack_alerted_at', 'updated_at',
        ])
        record_status_event(
            po, 'issued', user,
            f'Dispatched via {po.get_dispatch_method_display()}',
        )
        record_audit(
            po.tenant, user, 'purchase_order.issued',
            target_type='PurchaseOrder', target_id=str(po.id),
            message=f'{po.po_number} issued to {po.vendor.legal_name}',
        )
        _notify_vendor(
            po, category='delivery', priority='high',
            title=f'New purchase order: {po.po_number}',
            message=f'You have received purchase order {po.po_number} — '
                    f'{po.title}. Please acknowledge it.',
        )
    return po


def acknowledge_po(po, user, note=''):
    """Supplier (or buyer on their behalf) accepts an issued PO: issued → acknowledged."""
    with transaction.atomic():
        if po.status != 'issued':
            raise ValidationError('Only issued purchase orders can be acknowledged.')
        po = PurchaseOrder.all_objects.select_for_update().get(pk=po.pk)
        po.status = 'acknowledged'
        po.acknowledged_at = timezone.now()
        po.acknowledged_by = user
        po.acknowledgement_note = (note or '').strip()[:255]
        po.save(update_fields=[
            'status', 'acknowledged_at', 'acknowledged_by', 'acknowledgement_note',
            'updated_at',
        ])
        record_status_event(po, 'acknowledged', user, po.acknowledgement_note)
        record_audit(
            po.tenant, user, 'purchase_order.acknowledged',
            target_type='PurchaseOrder', target_id=str(po.id),
            message=f'{po.po_number} acknowledged',
        )
        if po.owner_id:
            _notify(
                po.owner, po, category='info', priority='normal',
                title=f'PO acknowledged: {po.po_number}',
                message=f'{po.vendor.legal_name} acknowledged {po.po_number}.',
            )
    return po


def decline_po(po, user, reason):
    """Supplier declines an issued PO: issued → declined (buyer can revise / cancel)."""
    with transaction.atomic():
        if po.status != 'issued':
            raise ValidationError('Only issued purchase orders can be declined.')
        po = PurchaseOrder.all_objects.select_for_update().get(pk=po.pk)
        po.status = 'declined'
        po.declined_at = timezone.now()
        po.decline_reason = (reason or '').strip()[:255]
        po.save(update_fields=[
            'status', 'declined_at', 'decline_reason', 'updated_at',
        ])
        record_status_event(po, 'declined', user, po.decline_reason)
        record_audit(
            po.tenant, user, 'purchase_order.declined', level='warning',
            target_type='PurchaseOrder', target_id=str(po.id),
            message=f'{po.po_number} declined: {po.decline_reason}'[:255],
        )
        if po.owner_id:
            _notify(
                po.owner, po, category='approval', priority='high',
                title=f'PO declined: {po.po_number}',
                message=f'{po.vendor.legal_name} declined {po.po_number}: '
                        f'{po.decline_reason}',
            )
    return po


def reopen_po(po, user):
    """Pull a declined PO back to draft for re-work."""
    with transaction.atomic():
        if po.status != 'declined':
            raise ValidationError('Only declined purchase orders can be reopened.')
        po = PurchaseOrder.all_objects.select_for_update().get(pk=po.pk)
        po.status = 'draft'
        po.issued_at = None
        po.issued_by = None
        po.declined_at = None
        po.save(update_fields=[
            'status', 'issued_at', 'issued_by', 'declined_at', 'updated_at',
        ])
        record_status_event(po, 'draft', user, 'Reopened after decline')
        record_audit(
            po.tenant, user, 'purchase_order.reopened',
            target_type='PurchaseOrder', target_id=str(po.id),
            message=f'{po.po_number} reopened to draft',
        )
    return po


# ---------------------------------------------------------------------------
# 5. Line item tracking — goods receipt (lightweight precursor to Module 13)
# ---------------------------------------------------------------------------
def record_line_receipt(po, line, received_qty, user):
    """Record a receipt against a PO line and roll the PO receiving status up."""
    with transaction.atomic():
        if po.status not in PO_CHANGE_ORDERABLE_STATUSES:
            raise ValidationError('Receipts can only be recorded against an issued PO.')
        if line.delivery_status == 'cancelled':
            raise ValidationError('This line has been cancelled.')
        received_qty = Decimal(received_qty or 0)
        if received_qty <= 0:
            raise ValidationError('Received quantity must be greater than zero.')

        po = PurchaseOrder.all_objects.select_for_update().get(pk=po.pk)
        # Re-fetch + lock the line in this transaction so two concurrent receipts on the
        # same line (e.g. two split-delivery shipments confirmed at once) can't lose an
        # update by both reading a stale received_quantity.
        line = PurchaseOrderLine.all_objects.select_for_update().get(pk=line.pk)
        new_received = (line.received_quantity or Decimal('0')) + received_qty
        if new_received > (line.quantity or Decimal('0')):
            raise ValidationError(
                'Received quantity exceeds the ordered quantity '
                f'({line.outstanding_quantity} outstanding).'
            )
        line.received_quantity = new_received
        line.delivery_status = (
            'received' if new_received >= (line.quantity or Decimal('0')) else 'partial'
        )
        line.save(update_fields=['received_quantity', 'delivery_status', 'updated_at'])

        # Roll the PO status up from its lines.
        _recompute_receiving_status(po, user)
        record_audit(
            po.tenant, user, 'purchase_order.line_received',
            target_type='PurchaseOrder', target_id=str(po.id),
            message=f'{po.po_number} line {line.line_no}: received {received_qty} '
                    f'{line.uom}',
        )
    return line


def _recompute_receiving_status(po, user):
    """Set the PO status to received / partially_received based on its lines."""
    active = po.lines.exclude(delivery_status='cancelled')
    total = active.count()
    if not total:
        return po
    received = active.filter(delivery_status='received').count()
    any_progress = active.exclude(delivery_status='pending').exists()

    new_status = po.status
    if received == total:
        new_status = 'received'
    elif any_progress:
        new_status = 'partially_received'

    if new_status != po.status:
        po.status = new_status
        po.save(update_fields=['status', 'updated_at'])
        record_status_event(po, new_status, user, 'Receiving updated from line items')
    return po


# ---------------------------------------------------------------------------
# 4. Cancellation & close-out
# ---------------------------------------------------------------------------
def cancel_po(po, user, reason):
    """Cancel an unfulfilled PO."""
    with transaction.atomic():
        if not po.can_cancel:
            raise ValidationError('This purchase order can no longer be cancelled.')
        po = PurchaseOrder.all_objects.select_for_update().get(pk=po.pk)
        po.status = 'cancelled'
        po.cancel_reason = (reason or '').strip()[:255]
        po.cancelled_at = timezone.now()
        po.cancelled_by = user
        po.save(update_fields=[
            'status', 'cancel_reason', 'cancelled_at', 'cancelled_by', 'updated_at',
        ])
        record_status_event(po, 'cancelled', user, po.cancel_reason)
        record_audit(
            po.tenant, user, 'purchase_order.cancelled', level='warning',
            target_type='PurchaseOrder', target_id=str(po.id),
            message=f'{po.po_number} cancelled: {po.cancel_reason}'[:255],
        )
        _notify_vendor(
            po, category='info', priority='normal',
            title=f'Purchase order cancelled: {po.po_number}',
            message=f'{po.po_number} has been cancelled.',
        )
    return po


def close_po(po, user, note=''):
    """Close a received (or partially received) PO."""
    with transaction.atomic():
        if not po.can_close:
            raise ValidationError('Only received purchase orders can be closed.')
        po = PurchaseOrder.all_objects.select_for_update().get(pk=po.pk)
        po.status = 'closed'
        po.closed_at = timezone.now()
        po.closed_by = user
        po.close_note = (note or '').strip()[:255]
        po.save(update_fields=[
            'status', 'closed_at', 'closed_by', 'close_note', 'updated_at',
        ])
        record_status_event(po, 'closed', user, po.close_note or 'Closed out')
        record_audit(
            po.tenant, user, 'purchase_order.closed',
            target_type='PurchaseOrder', target_id=str(po.id),
            message=f'{po.po_number} closed',
        )
    return po


# ---------------------------------------------------------------------------
# 3. Change Order Management
# ---------------------------------------------------------------------------
def apply_change_order(co, user):
    """Apply a draft/pending change order to its PO, bumping the revision.

    Snapshots the previous delivery date + line (qty, price) values, writes the
    proposed values, recomputes totals and bumps ``PurchaseOrder.revision`` — all
    atomically. Applied change orders are frozen into the version history.
    """
    with transaction.atomic():
        po = PurchaseOrder.all_objects.select_for_update().get(pk=co.purchase_order_id)
        if not co.is_editable:
            raise ValidationError('This change order has already been resolved.')
        if po.status not in PO_CHANGE_ORDERABLE_STATUSES:
            raise ValidationError(
                'Change orders can only be applied to an issued purchase order.'
            )

        co.prev_expected_delivery_date = po.expected_delivery_date
        co.prev_total = po.total_amount

        # Snapshot the affected lines, then apply proposed (qty, price) changes.
        proposed = {
            int(item['line_id']): item
            for item in (co.proposed_lines or [])
            if item.get('line_id') is not None
        }
        lines = {line.id: line for line in po.lines.all()}
        prev_lines = []
        for line_id, item in proposed.items():
            line = lines.get(line_id)
            if line is None:
                continue
            prev_lines.append({
                'line_id': line_id,
                'quantity': str(line.quantity),
                'unit_price': str(line.unit_price),
            })
            if item.get('quantity') is not None:
                line.quantity = Decimal(str(item['quantity']))
            if item.get('unit_price') is not None:
                line.unit_price = Decimal(str(item['unit_price']))
            line.save(update_fields=['quantity', 'unit_price', 'line_total', 'updated_at'])
        co.prev_lines = prev_lines

        if co.new_expected_delivery_date:
            po.expected_delivery_date = co.new_expected_delivery_date

        recompute_totals(po)
        po.refresh_from_db()
        po.revision = (po.revision or 1) + 1
        po.save(update_fields=['revision', 'updated_at'])

        co.new_total = po.total_amount
        co.status = 'applied'
        co.applied_at = timezone.now()
        co.applied_by = user
        co.save(update_fields=[
            'status', 'applied_at', 'applied_by', 'prev_expected_delivery_date',
            'prev_lines', 'prev_total', 'new_total', 'updated_at',
        ])
        record_status_event(
            po, po.status, user,
            f'Change order {co.change_number} applied (rev {po.revision})',
            change_order=co,
        )
        record_audit(
            po.tenant, user, 'purchase_order.change_order.applied',
            target_type='PurchaseOrder', target_id=str(po.id),
            message=f'{co.change_number} applied to {po.po_number}',
            payload={
                'change_order_id': co.id,
                'revision': po.revision,
                'prev_total': str(co.prev_total) if co.prev_total is not None else None,
                'new_total': str(co.new_total) if co.new_total is not None else None,
            },
        )
        _notify_vendor(
            po, category='delivery', priority='normal',
            title=f'Purchase order updated: {po.po_number}',
            message=f'{po.po_number} has been revised (change order {co.change_number}).',
        )
    return co


def cancel_change_order(co, user, reason=''):
    """Cancel a draft/pending change order without touching the PO."""
    with transaction.atomic():
        if not co.is_editable:
            raise ValidationError('This change order has already been resolved.')
        co.status = 'cancelled'
        co.decision_note = (reason or '').strip()[:255]
        co.save(update_fields=['status', 'decision_note', 'updated_at'])
        record_audit(
            co.tenant, user, 'purchase_order.change_order.cancelled', level='warning',
            target_type='PurchaseOrderChangeOrder', target_id=str(co.id),
            message=f'{co.change_number} cancelled',
        )
    return co


# ---------------------------------------------------------------------------
# Alert sweep (awaiting-acknowledgment + overdue-delivery)
# ---------------------------------------------------------------------------
def scan_po_alerts(tenant=None, now=None, ack_after_days=3):
    """Raise awaiting-ack + overdue-delivery alerts. Idempotent; returns counts.

    * An issued PO not acknowledged within ``ack_after_days`` raises a one-time
      reminder to the owner (guarded by ``ack_alerted_at``).
    * An issued/acknowledged/partially-received PO past its expected delivery date
      raises a one-time alert to the owner (guarded by ``delivery_alerted_at``).

    Called by the ``run_po_alerts`` command (no ``tenant`` → all tenants) and
    lazily by the tracking board (single tenant).
    """
    if tenant is None:
        totals = {'ack_alerted': 0, 'overdue_delivery': 0}
        for t in Tenant.objects.all():
            set_current_tenant(t)
            counts = scan_po_alerts(tenant=t, now=now, ack_after_days=ack_after_days)
            for k in totals:
                totals[k] += counts.get(k, 0)
        return totals

    now = now or timezone.now()
    today = timezone.localdate()
    counts = {'ack_alerted': 0, 'overdue_delivery': 0}

    # Awaiting acknowledgment.
    issued = PurchaseOrder.all_objects.filter(
        tenant=tenant, status='issued', issued_at__isnull=False,
        ack_alerted_at__isnull=True,
    )
    for po in issued:
        age_days = (now - po.issued_at).days
        if age_days >= ack_after_days:
            if po.owner_id:
                _notify(
                    po.owner, po, category='deadline', priority='high',
                    title=f'PO awaiting acknowledgment: {po.po_number}',
                    message=f'{po.po_number} was issued {age_days} day(s) ago and is '
                            f'not yet acknowledged.',
                )
            po.ack_alerted_at = now
            po.save(update_fields=['ack_alerted_at', 'updated_at'])
            record_audit(
                tenant, None, 'purchase_order.ack_alert',
                target_type='PurchaseOrder', target_id=str(po.id),
                message=f'{po.po_number} awaiting acknowledgment ({age_days}d)',
            )
            counts['ack_alerted'] += 1

    # Overdue delivery.
    overdue = PurchaseOrder.all_objects.filter(
        tenant=tenant,
        status__in=('issued', 'acknowledged', 'partially_received'),
        expected_delivery_date__lt=today, delivery_alerted_at__isnull=True,
    )
    for po in overdue:
        days = (today - po.expected_delivery_date).days
        if po.owner_id:
            _notify(
                po.owner, po, category='deadline', priority='urgent',
                title=f'PO delivery overdue: {po.po_number}',
                message=f'{po.po_number} is {days} day(s) past its expected delivery '
                        f'date ({po.expected_delivery_date}).',
            )
        po.delivery_alerted_at = now
        po.save(update_fields=['delivery_alerted_at', 'updated_at'])
        record_audit(
            tenant, None, 'purchase_order.delivery_overdue', level='warning',
            target_type='PurchaseOrder', target_id=str(po.id),
            message=f'{po.po_number} delivery overdue ({days}d)',
        )
        counts['overdue_delivery'] += 1

    return counts


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def tenant_po_metrics(tenant):
    """Aggregate PO KPIs for the tenant analytics dashboard."""
    qs = PurchaseOrder.objects.filter(tenant=tenant)
    by_status = dict(qs.values_list('status').annotate(n=Count('id')))
    total = qs.count()

    committed_value = qs.exclude(status='cancelled').aggregate(
        s=Sum('total_amount'))['s'] or Decimal('0.00')
    open_qs = qs.filter(status__in=('issued', 'acknowledged', 'partially_received'))
    open_value = open_qs.aggregate(s=Sum('total_amount'))['s'] or Decimal('0.00')

    overdue = sum(1 for po in open_qs if po.is_delivery_overdue)
    awaiting_ack = by_status.get('issued', 0)

    top_vendors = list(
        qs.exclude(status='cancelled').filter(vendor__isnull=False)
        .values('vendor__legal_name')
        .annotate(n=Count('id'), v=Sum('total_amount'))
        .order_by('-v', '-n')[:5]
    )

    return {
        'total_pos': total,
        'by_status': by_status,
        'draft': by_status.get('draft', 0),
        'issued': by_status.get('issued', 0),
        'acknowledged': by_status.get('acknowledged', 0),
        'declined': by_status.get('declined', 0),
        'partially_received': by_status.get('partially_received', 0),
        'received': by_status.get('received', 0),
        'closed': by_status.get('closed', 0),
        'cancelled': by_status.get('cancelled', 0),
        'committed_value': committed_value.quantize(Decimal('0.01')),
        'open_value': open_value.quantize(Decimal('0.01')),
        'awaiting_ack': awaiting_ack,
        'overdue_delivery': overdue,
        'top_vendors': top_vendors,
    }
