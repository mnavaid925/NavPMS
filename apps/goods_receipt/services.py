"""Goods Receipt & Inspection domain services (Module 13).

All state transitions live here, wrapped in ``@transaction.atomic`` with audit logging
via :func:`apps.tenants.services.record_audit`. Mirrors the Module 11/12 service style —
perms + numbering + lifecycle + alert sweep + analytics — and adds:

  * a receive -> inspect -> post lifecycle for a Goods Receipt Note (GRN),
  * a fixed pass/fail QA inspection checklist + per-line accepted/rejected split,
  * posting of the ACCEPTED quantity back into the PO lines via
    :func:`apps.purchase_orders.services.record_line_receipt` — *idempotently* (a
    ``posted_quantity`` watermark per GRN line) and *guarded* (the PO's own over-receipt
    check is pre-validated so a GRN can never double-count with the fulfilment module),
  * a Return-to-Vendor (RTV) flow for rejected goods, surfaced to the supplier portal, and
  * internal barcode/QR tag generation for accepted inventory.
"""
from datetime import timedelta
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
from apps.purchase_orders.models import PO_CHANGE_ORDERABLE_STATUSES

from .models import (
    GRN_QA_CRITERIA,
    RTV_VENDOR_VISIBLE_STATUSES,
    GoodsReceipt,
    GoodsReceiptCheck,
    GoodsReceiptLine,
    GoodsReceiptStatusEvent,
    ReceiptTag,
    ReturnToVendor,
    ReturnToVendorLine,
)

# Roles allowed to create/receive/inspect/post goods receipts (mirrors purchase_orders /
# fulfillment — there is no dedicated warehouse/QA role in the project yet).
MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
# Viewing (analytics / read-only) additionally allows approvers.
VIEW_ROLES = MANAGE_ROLES + ('approver',)

_VALID_CRITERIA = {key for key, _ in GRN_QA_CRITERIA}


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


def can_manage_goods_receipt(user):
    """May create/receive/inspect/post goods receipts and manage RTVs."""
    return _has_role(user, MANAGE_ROLES)


def can_view_goods_receipt(user):
    """May view goods receipts / analytics (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Visibility gate (vendor portal — RTV)
# ---------------------------------------------------------------------------
def rtv_visible_to(user, rtv):
    """True if ``user`` may view ``rtv``.

    Internal managers/approvers may view any RTV in their tenant; a vendor portal user
    may view only their own returns, and only once authorised (a draft is never exposed).
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_vendor_user', False):
        return (
            getattr(user, 'vendor_id', None) == rtv.vendor_id
            and rtv.status in RTV_VENDOR_VISIBLE_STATUSES
        )
    return can_view_goods_receipt(user)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def record_status_event(grn, status, user, note=''):
    """Append an immutable lifecycle timeline row."""
    return GoodsReceiptStatusEvent.all_objects.create(
        tenant=grn.tenant, goods_receipt=grn, status=status,
        note=(note or '')[:255], actor=user,
    )


def _notify(user, *, tenant, link, category, priority, title, message):
    """Create a portal Notification (no-op if there is no recipient)."""
    if not user:
        return None
    return Notification.all_objects.create(
        tenant=tenant, user=user, category=category, priority=priority,
        title=title[:160], message=message, link_url=link,
    )


def _notify_owner(grn, *, category, priority, title, message):
    """Notify the internal PO owner (the buyer who placed the order)."""
    owner = getattr(grn.purchase_order, 'owner', None)
    if not owner:
        return None
    try:
        link = reverse('goods_receipt:grn_detail', kwargs={'pk': grn.pk})
    except Exception:
        link = ''
    return _notify(owner, tenant=grn.tenant, link=link, category=category,
                   priority=priority, title=title, message=message)


def _notify_vendor_rtv(rtv, *, category, priority, title, message):
    """Notify the supplier's portal user about a return."""
    portal_user = getattr(rtv.vendor, 'portal_user', None) if rtv.vendor_id else None
    if not portal_user:
        return None
    try:
        link = reverse('vendor_portal:rtv_detail', kwargs={'pk': rtv.pk})
    except Exception:
        link = ''
    return _notify(portal_user, tenant=rtv.tenant, link=link, category=category,
                   priority=priority, title=title, message=message)


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def _next_number(tenant, model, field, prefix_kind):
    """Generate the next gap-free ``<KIND>-<SLUG>-NNNNN`` for ``tenant``."""
    slug = (tenant.slug or str(tenant.pk))[:6].upper()
    prefix = f'{prefix_kind}-{slug}-'
    last = (
        model.all_objects
        .filter(tenant=tenant, **{f'{field}__startswith': prefix})
        .order_by(f'-{field}')
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(getattr(last, field).rsplit('-', 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    number = f'{prefix}{seq:05d}'
    while model.all_objects.filter(tenant=tenant, **{field: number}).exists():
        seq += 1
        number = f'{prefix}{seq:05d}'
    return number


def next_grn_number(tenant):
    """Generate the next gap-free ``GRN-<SLUG>-NNNNN`` for ``tenant``."""
    return _next_number(tenant, GoodsReceipt, 'grn_number', 'GRN')


def next_rtv_number(tenant):
    """Generate the next gap-free ``RTV-<SLUG>-NNNNN`` for ``tenant``."""
    return _next_number(tenant, ReturnToVendor, 'rtv_number', 'RTV')


def generate_tag_code(grn, line, seq):
    """Deterministic internal tag code, e.g. ``GRN-ACME-00007-L2-001``."""
    return f'{grn.grn_number}-L{line.line_no}-{seq:03d}'


# ---------------------------------------------------------------------------
# 1. GRN creation + lines
# ---------------------------------------------------------------------------
def create_goods_receipt(*, tenant, user, purchase_order, shipment=None, **fields):
    """Create a draft GRN against a PO with a collision-safe number.

    Serialises numbering with a ``select_for_update`` lock on the tenant and retries on a
    unique-constraint collision (mirrors ``purchase_orders.create_purchase_order``).
    """
    if not purchase_order.vendor_id:
        raise ValidationError('The purchase order has no supplier to receive from.')
    if purchase_order.status not in PO_CHANGE_ORDERABLE_STATUSES:
        raise ValidationError(
            'A goods receipt can only be raised against a dispatched, open purchase order.')
    fields.pop('vendor', None)  # always derived from the PO
    last_exc = None
    for _attempt in range(5):
        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=tenant.pk)
                grn = GoodsReceipt.all_objects.create(
                    tenant=tenant,
                    grn_number=next_grn_number(tenant),
                    purchase_order=purchase_order,
                    shipment=shipment,
                    vendor=purchase_order.vendor,
                    status='draft',
                    created_by=user,
                    **fields,
                )
                record_status_event(grn, 'draft', user, 'Goods receipt created')
                record_audit(
                    tenant, user, 'goods_receipt.created',
                    target_type='GoodsReceipt', target_id=str(grn.id),
                    message=f'{grn.grn_number} for {purchase_order.po_number}',
                )
            return grn
        except IntegrityError as exc:
            last_exc = exc
    raise last_exc


def add_receipt_line(grn, *, purchase_order_line, received_quantity, shipment_line=None,
                     **fields):
    """Add a received line to a draft GRN."""
    if not grn.is_editable:
        raise ValidationError('Lines can only be changed while the GRN is a draft.')
    received_quantity = Decimal(str(received_quantity or '0'))
    if received_quantity <= 0:
        raise ValidationError('Received quantity must be greater than zero.')
    next_no = (grn.lines.aggregate(m=Max('line_no'))['m'] or 0) + 1
    return GoodsReceiptLine.all_objects.create(
        tenant=grn.tenant, goods_receipt=grn,
        purchase_order_line=purchase_order_line,
        shipment_line=shipment_line,
        line_no=fields.pop('line_no', next_no),
        description=fields.pop('description', '') or purchase_order_line.description,
        uom=fields.pop('uom', '') or purchase_order_line.uom,
        received_quantity=received_quantity,
        line_status='pending',
        **fields,
    )


# ---------------------------------------------------------------------------
# 1. Mark received (draft -> received)
# ---------------------------------------------------------------------------
def mark_received(grn, user, *, received_date=None):
    """Confirm the goods are physically in: draft -> received."""
    with transaction.atomic():
        if not grn.can_receive:
            raise ValidationError('Only a draft GRN can be marked received.')
        lines = list(grn.lines.all())
        if not lines:
            raise ValidationError('Add at least one received line first.')
        total = sum((ln.received_quantity or Decimal('0') for ln in lines), Decimal('0'))
        if total <= 0:
            raise ValidationError('The GRN must record a received quantity.')
        grn = GoodsReceipt.all_objects.select_for_update().get(pk=grn.pk)
        now = timezone.now()
        grn.status = 'received'
        grn.received_at = now
        grn.received_date = received_date or timezone.localdate()
        grn.received_by = user
        grn.inspection_alerted_at = None
        grn.save(update_fields=[
            'status', 'received_at', 'received_date', 'received_by',
            'inspection_alerted_at', 'updated_at',
        ])
        grn.lines.filter(line_status='pending').update(line_status='received')
        record_status_event(grn, 'received', user, 'Goods received')
        record_audit(
            grn.tenant, user, 'goods_receipt.received',
            target_type='GoodsReceipt', target_id=str(grn.id),
            message=f'{grn.grn_number} received ({total} unit(s))',
        )
        _notify_owner(
            grn, category='delivery', priority='normal',
            title=f'Goods received: {grn.grn_number}',
            message=f'{grn.grn_number} for {grn.purchase_order.po_number} was received '
                    'and is awaiting inspection.',
        )
    return grn


# ---------------------------------------------------------------------------
# 2. Inspection (received -> inspected)
# ---------------------------------------------------------------------------
def record_inspection(grn, user, *, checks=None, line_results=None,
                      result_overall=None, note=''):
    """Record the QA checklist + per-line accept/reject: received -> inspected.

    ``checks`` is an iterable of ``{'criterion', 'result', 'note'}`` (one per QA criterion).
    ``line_results`` maps a GRN-line id to ``{'accepted', 'rejected', 'discrepancy',
    'reason'}``. ``accepted + rejected`` may not exceed the received quantity.
    """
    with transaction.atomic():
        if not grn.can_inspect:
            raise ValidationError('This GRN is not awaiting inspection.')
        grn = GoodsReceipt.all_objects.select_for_update().get(pk=grn.pk)

        # 1. QA checklist (one row per criterion; update on re-inspection).
        any_fail = False
        for chk in (checks or []):
            criterion = chk.get('criterion')
            if criterion not in _VALID_CRITERIA:
                continue
            result = chk.get('result') or 'pass'
            if result not in ('pass', 'fail', 'na'):
                result = 'pass'
            if result == 'fail':
                any_fail = True
            GoodsReceiptCheck.all_objects.update_or_create(
                tenant=grn.tenant, goods_receipt=grn, criterion=criterion,
                defaults={
                    'result': result, 'note': (chk.get('note') or '')[:255],
                    'checked_by': user,
                },
            )

        # 2. Per-line accept / reject.
        results = line_results or {}
        any_rejection = False
        total_accepted = Decimal('0')
        for line in grn.lines.all():
            if line.id not in results:
                continue
            data = results[line.id]
            accepted = Decimal(str(data.get('accepted') or '0'))
            rejected = Decimal(str(data.get('rejected') or '0'))
            if accepted < 0 or rejected < 0:
                raise ValidationError(
                    f'Line {line.line_no}: quantities cannot be negative.')
            received = line.received_quantity or Decimal('0')
            if accepted + rejected > received:
                raise ValidationError(
                    f'Line {line.line_no}: accepted + rejected ({accepted + rejected}) '
                    f'exceeds the received quantity ({received}).')
            line.accepted_quantity = accepted
            line.rejected_quantity = rejected
            discrepancy = data.get('discrepancy') or 'none'
            line.discrepancy_type = discrepancy
            line.rejection_reason = (data.get('reason') or '')[:255]
            if rejected > 0 and accepted > 0:
                line.line_status = 'partial'
            elif rejected > 0:
                line.line_status = 'rejected'
            elif accepted > 0:
                line.line_status = 'accepted'
            else:
                line.line_status = 'inspected'
            line.save(update_fields=[
                'accepted_quantity', 'rejected_quantity', 'discrepancy_type',
                'rejection_reason', 'line_status', 'updated_at',
            ])
            if rejected > 0:
                any_rejection = True
            total_accepted += accepted

        # 3. Derive the overall inspection result.
        if result_overall in ('pass', 'fail', 'partial'):
            overall = result_overall
        elif any_fail or (any_rejection and total_accepted <= 0):
            overall = 'fail'
        elif any_rejection:
            overall = 'partial'
        else:
            overall = 'pass'

        grn.status = 'inspected'
        grn.inspected_at = timezone.now()
        grn.inspected_by = user
        grn.inspection_result = overall
        grn.inspection_note = (note or '')[:255]
        grn.save(update_fields=[
            'status', 'inspected_at', 'inspected_by', 'inspection_result',
            'inspection_note', 'updated_at',
        ])
        record_status_event(
            grn, 'inspected', user, f'Inspection: {grn.get_inspection_result_display()}')
        record_audit(
            grn.tenant, user, 'goods_receipt.inspected',
            target_type='GoodsReceipt', target_id=str(grn.id),
            message=f'{grn.grn_number} inspected ({overall})',
        )
        if any_rejection:
            _notify_owner(
                grn, category='delivery', priority='high',
                title=f'Inspection rejections: {grn.grn_number}',
                message=f'{grn.grn_number} for {grn.purchase_order.po_number} has rejected '
                        'items. Raise a return to vendor (RTV) if required.',
            )
    return grn


# ---------------------------------------------------------------------------
# 3. Post accepted qty to the PO (idempotent + guarded) + generate tags
# ---------------------------------------------------------------------------
def generate_tags(grn, user):
    """Create one barcode/QR tag per accepted line that does not yet have one.

    Idempotent: re-running only tags newly-accepted lines.
    """
    created = []
    for line in grn.lines.all():
        accepted = line.accepted_quantity or Decimal('0')
        if accepted <= 0:
            continue
        if line.tags.exists():
            continue
        seq = line.tags.count() + 1
        tag = ReceiptTag.all_objects.create(
            tenant=grn.tenant, goods_receipt=grn, goods_receipt_line=line,
            code=generate_tag_code(grn, line, seq),
            quantity=accepted, uom=line.uom, generated_by=user,
        )
        created.append(tag)
    return created


def post_goods_receipt(grn, user):
    """Post the accepted quantities to the PO lines: inspected -> posted.

    Structured exactly like ``fulfillment.confirm_delivery``: the per-line delta
    ``accepted − posted`` is pre-validated against the PO outstanding (so the PO's own
    over-receipt guard is never tripped), then posted via
    :func:`apps.purchase_orders.services.record_line_receipt`. Re-running posts nothing
    (the ``posted_quantity`` watermark makes it idempotent).
    """
    with transaction.atomic():
        if not grn.can_post:
            raise ValidationError('Only an inspected GRN can be posted.')
        grn = GoodsReceipt.all_objects.select_for_update().get(pk=grn.pk)
        po = grn.purchase_order
        lines = list(grn.lines.select_related('purchase_order_line'))

        # 1. Guard the PO is still receivable.
        if po.status not in PO_CHANGE_ORDERABLE_STATUSES:
            raise ValidationError(
                f'Cannot post receipts: purchase order {po.po_number} is '
                f'{po.get_status_display()}.')

        # 2. Pre-validate every line's delta against the PO outstanding (no writes yet).
        for ln in lines:
            delta = (ln.accepted_quantity or Decimal('0')) - (ln.posted_quantity or Decimal('0'))
            if delta <= 0:
                continue
            outstanding = ln.purchase_order_line.outstanding_quantity
            if delta > outstanding:
                raise ValidationError(
                    f'Line {ln.line_no}: posting {delta} exceeds the PO outstanding '
                    f'({outstanding}). Raise a PO change order first.')

        # 3. Apply: post each line's delta to the PO, then watermark the GRN line.
        posted_total = Decimal('0')
        for ln in lines:
            delta = (ln.accepted_quantity or Decimal('0')) - (ln.posted_quantity or Decimal('0'))
            if delta > 0:
                po_services.record_line_receipt(po, ln.purchase_order_line, delta, user)
                ln.posted_quantity = ln.accepted_quantity
                ln.save(update_fields=['posted_quantity', 'updated_at'])
                posted_total += delta

        # 4. Generate barcode/QR tags for the accepted inventory.
        generate_tags(grn, user)

        # 5. Stamp the GRN.
        grn.status = 'posted'
        grn.posted_at = timezone.now()
        grn.posted_by = user
        grn.save(update_fields=['status', 'posted_at', 'posted_by', 'updated_at'])
        record_status_event(grn, 'posted', user, f'Posted {posted_total} to {po.po_number}')
        record_audit(
            grn.tenant, user, 'goods_receipt.posted',
            target_type='GoodsReceipt', target_id=str(grn.id),
            message=f'{grn.grn_number} posted {posted_total} accepted unit(s) to '
                    f'{po.po_number}',
        )
        _notify_owner(
            grn, category='delivery', priority='normal',
            title=f'Goods receipt posted: {grn.grn_number}',
            message=f'{grn.grn_number} posted {posted_total} accepted unit(s) to '
                    f'{po.po_number}.',
        )
    return grn


# ---------------------------------------------------------------------------
# Close / cancel
# ---------------------------------------------------------------------------
def close_goods_receipt(grn, user, note=''):
    """Close a posted GRN (terminal book-keeping)."""
    with transaction.atomic():
        if not grn.can_close:
            raise ValidationError('Only a posted GRN can be closed.')
        grn = GoodsReceipt.all_objects.select_for_update().get(pk=grn.pk)
        grn.status = 'closed'
        grn.closed_at = timezone.now()
        grn.save(update_fields=['status', 'closed_at', 'updated_at'])
        record_status_event(grn, 'closed', user, (note or 'Closed out')[:255])
        record_audit(
            grn.tenant, user, 'goods_receipt.closed',
            target_type='GoodsReceipt', target_id=str(grn.id),
            message=f'{grn.grn_number} closed',
        )
    return grn


def cancel_goods_receipt(grn, user, reason=''):
    """Cancel a GRN that has not yet posted to the PO."""
    with transaction.atomic():
        if not grn.can_cancel:
            raise ValidationError(
                'A posted GRN can no longer be cancelled (use a return to vendor instead).')
        grn = GoodsReceipt.all_objects.select_for_update().get(pk=grn.pk)
        grn.status = 'cancelled'
        grn.cancel_reason = (reason or '').strip()[:255]
        grn.cancelled_at = timezone.now()
        grn.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])
        record_status_event(grn, 'cancelled', user, grn.cancel_reason)
        record_audit(
            grn.tenant, user, 'goods_receipt.cancelled', level='warning',
            target_type='GoodsReceipt', target_id=str(grn.id),
            message=f'{grn.grn_number} cancelled: {grn.cancel_reason}'[:255],
        )
        _notify_owner(
            grn, category='info', priority='normal',
            title=f'Goods receipt cancelled: {grn.grn_number}',
            message=f'{grn.grn_number} has been cancelled.',
        )
    return grn


# ---------------------------------------------------------------------------
# 4. Return to Vendor (RTV)
# ---------------------------------------------------------------------------
def create_rtv_from_rejections(grn, user, *, reason='', line_quantities=None):
    """Open a draft RTV for the rejected lines of an inspected/posted GRN."""
    rejected_lines = [
        ln for ln in grn.lines.all() if (ln.rejected_quantity or Decimal('0')) > 0
    ]
    if not rejected_lines:
        raise ValidationError('This GRN has no rejected items to return.')
    last_exc = None
    for _attempt in range(5):
        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=grn.tenant.pk)
                rtv = ReturnToVendor.all_objects.create(
                    tenant=grn.tenant, rtv_number=next_rtv_number(grn.tenant),
                    goods_receipt=grn, purchase_order=grn.purchase_order,
                    vendor=grn.vendor, status='draft',
                    reason=(reason or '').strip(), created_by=user,
                )
                for i, ln in enumerate(rejected_lines, start=1):
                    qty = ln.rejected_quantity or Decimal('0')
                    if line_quantities and ln.id in line_quantities:
                        qty = Decimal(str(line_quantities[ln.id]))
                    if qty <= 0:
                        continue
                    ReturnToVendorLine.all_objects.create(
                        tenant=grn.tenant, rtv=rtv, goods_receipt_line=ln,
                        line_no=i, description=ln.description, uom=ln.uom,
                        quantity=qty, reason=ln.rejection_reason,
                    )
                record_audit(
                    grn.tenant, user, 'goods_receipt.rtv.created',
                    target_type='ReturnToVendor', target_id=str(rtv.id),
                    message=f'{rtv.rtv_number} from {grn.grn_number}',
                )
            return rtv
        except IntegrityError as exc:
            last_exc = exc
    raise last_exc


def authorize_rtv(rtv, user):
    """Authorise a draft RTV and notify the supplier: draft -> authorized."""
    with transaction.atomic():
        if not rtv.can_authorize:
            raise ValidationError('Only a draft RTV can be authorised.')
        if not rtv.lines.exists():
            raise ValidationError('Add at least one line before authorising the return.')
        rtv = ReturnToVendor.all_objects.select_for_update().get(pk=rtv.pk)
        rtv.status = 'authorized'
        rtv.authorized_at = timezone.now()
        rtv.authorized_by = user
        rtv.alerted_at = None
        rtv.save(update_fields=[
            'status', 'authorized_at', 'authorized_by', 'alerted_at', 'updated_at'])
        record_audit(
            rtv.tenant, user, 'goods_receipt.rtv.authorized',
            target_type='ReturnToVendor', target_id=str(rtv.id),
            message=f'{rtv.rtv_number} authorised',
        )
        _notify_vendor_rtv(
            rtv, category='delivery', priority='high',
            title=f'Return authorised: {rtv.rtv_number}',
            message=f'A return ({rtv.rtv_number}) against {rtv.purchase_order.po_number} '
                    'has been authorised. Please review the items being returned.',
        )
    return rtv


def ship_rtv(rtv, user, *, carrier='', tracking_number=''):
    """Mark an authorised RTV shipped back to the supplier: authorized -> shipped."""
    with transaction.atomic():
        if not rtv.can_ship:
            raise ValidationError('Only an authorised RTV can be shipped.')
        rtv = ReturnToVendor.all_objects.select_for_update().get(pk=rtv.pk)
        rtv.status = 'shipped'
        rtv.shipped_at = timezone.now()
        rtv.shipped_by = user
        rtv.carrier = (carrier or '').strip()[:120]
        rtv.tracking_number = (tracking_number or '').strip()[:120]
        rtv.save(update_fields=[
            'status', 'shipped_at', 'shipped_by', 'carrier', 'tracking_number',
            'updated_at'])
        record_audit(
            rtv.tenant, user, 'goods_receipt.rtv.shipped',
            target_type='ReturnToVendor', target_id=str(rtv.id),
            message=f'{rtv.rtv_number} shipped back to {rtv.vendor.legal_name}',
        )
        _notify_vendor_rtv(
            rtv, category='delivery', priority='normal',
            title=f'Return shipped: {rtv.rtv_number}',
            message=f'{rtv.rtv_number} has been shipped back to you.',
        )
    return rtv


def close_rtv(rtv, user, note=''):
    """Close a shipped RTV (credit received / complete): shipped -> closed."""
    with transaction.atomic():
        if not rtv.can_close:
            raise ValidationError('Only a shipped RTV can be closed.')
        rtv = ReturnToVendor.all_objects.select_for_update().get(pk=rtv.pk)
        rtv.status = 'closed'
        rtv.closed_at = timezone.now()
        rtv.save(update_fields=['status', 'closed_at', 'updated_at'])
        record_audit(
            rtv.tenant, user, 'goods_receipt.rtv.closed',
            target_type='ReturnToVendor', target_id=str(rtv.id),
            message=f'{rtv.rtv_number} closed',
        )
    return rtv


def cancel_rtv(rtv, user, reason=''):
    """Cancel a draft/authorised RTV."""
    with transaction.atomic():
        if not rtv.can_cancel:
            raise ValidationError('A shipped or closed RTV can no longer be cancelled.')
        rtv = ReturnToVendor.all_objects.select_for_update().get(pk=rtv.pk)
        rtv.status = 'cancelled'
        rtv.cancel_reason = (reason or '').strip()[:255]
        rtv.cancelled_at = timezone.now()
        rtv.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])
        record_audit(
            rtv.tenant, user, 'goods_receipt.rtv.cancelled', level='warning',
            target_type='ReturnToVendor', target_id=str(rtv.id),
            message=f'{rtv.rtv_number} cancelled',
        )
    return rtv


def acknowledge_rtv(rtv, user, note=''):
    """Supplier acknowledges an authorised/shipped return from the vendor portal."""
    with transaction.atomic():
        if rtv.status not in RTV_VENDOR_VISIBLE_STATUSES:
            raise ValidationError('This return cannot be acknowledged.')
        rtv = ReturnToVendor.all_objects.select_for_update().get(pk=rtv.pk)
        rtv.acknowledged_at = timezone.now()
        rtv.acknowledgement_note = (note or '').strip()[:255]
        rtv.save(update_fields=['acknowledged_at', 'acknowledgement_note', 'updated_at'])
        record_audit(
            rtv.tenant, user, 'goods_receipt.rtv.acknowledged',
            target_type='ReturnToVendor', target_id=str(rtv.id),
            message=f'{rtv.rtv_number} acknowledged by supplier',
        )
        owner = getattr(rtv.purchase_order, 'owner', None)
        if owner:
            try:
                link = reverse('goods_receipt:rtv_detail', kwargs={'pk': rtv.pk})
            except Exception:
                link = ''
            _notify(
                owner, tenant=rtv.tenant, link=link, category='delivery',
                priority='normal',
                title=f'Return acknowledged: {rtv.rtv_number}',
                message=f'{rtv.vendor.legal_name} acknowledged return {rtv.rtv_number}.',
            )
    return rtv


# ---------------------------------------------------------------------------
# Alert sweep (overdue inspection + open RTV)
# ---------------------------------------------------------------------------
def scan_goods_receipt_alerts(tenant=None, now=None, inspect_after_days=2):
    """Raise overdue-inspection + open-RTV alerts. Idempotent.

    A GRN received more than ``inspect_after_days`` ago and still not inspected raises a
    one-time alert (guarded by ``inspection_alerted_at``); an RTV left in draft/authorized
    raises a one-time alert (guarded by ``alerted_at``). Called by the
    ``run_goods_receipt_alerts`` command (no ``tenant`` -> all tenants) and lazily by the
    analytics dashboard.
    """
    if tenant is None:
        totals = {'overdue_inspection': 0, 'open_rtv': 0}
        for t in Tenant.objects.all():
            set_current_tenant(t)
            counts = scan_goods_receipt_alerts(
                tenant=t, now=now, inspect_after_days=inspect_after_days)
            for k in totals:
                totals[k] += counts.get(k, 0)
        return totals

    now = now or timezone.now()
    cutoff = now - timedelta(days=inspect_after_days)
    counts = {'overdue_inspection': 0, 'open_rtv': 0}

    overdue = GoodsReceipt.all_objects.filter(
        tenant=tenant, status__in=('received', 'under_inspection'),
        received_at__lt=cutoff, inspection_alerted_at__isnull=True,
    ).select_related('purchase_order')
    for grn in overdue:
        _notify_owner(
            grn, category='deadline', priority='high',
            title=f'Goods receipt awaiting inspection: {grn.grn_number}',
            message=f'{grn.grn_number} for {grn.purchase_order.po_number} has been '
                    'awaiting inspection for more than '
                    f'{inspect_after_days} day(s).',
        )
        grn.inspection_alerted_at = now
        grn.save(update_fields=['inspection_alerted_at', 'updated_at'])
        record_audit(
            tenant, None, 'goods_receipt.inspection_overdue', level='warning',
            target_type='GoodsReceipt', target_id=str(grn.id),
            message=f'{grn.grn_number} inspection overdue',
        )
        counts['overdue_inspection'] += 1

    open_rtvs = ReturnToVendor.all_objects.filter(
        tenant=tenant, status__in=('draft', 'authorized'), alerted_at__isnull=True,
    ).select_related('purchase_order')
    for rtv in open_rtvs:
        owner = getattr(rtv.purchase_order, 'owner', None)
        if owner:
            try:
                link = reverse('goods_receipt:rtv_detail', kwargs={'pk': rtv.pk})
            except Exception:
                link = ''
            _notify(
                owner, tenant=tenant, link=link, category='deadline', priority='normal',
                title=f'Return to vendor open: {rtv.rtv_number}',
                message=f'{rtv.rtv_number} against {rtv.purchase_order.po_number} is still '
                        f'{rtv.get_status_display()}.',
            )
        rtv.alerted_at = now
        rtv.save(update_fields=['alerted_at', 'updated_at'])
        counts['open_rtv'] += 1

    return counts


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def tenant_goods_receipt_metrics(tenant):
    """Aggregate goods-receipt KPIs for the tenant analytics dashboard."""
    qs = GoodsReceipt.objects.filter(tenant=tenant)
    by_status = dict(qs.values_list('status').annotate(n=Count('id')))
    total = qs.count()

    line_qs = GoodsReceiptLine.objects.filter(tenant=tenant).exclude(
        goods_receipt__status='cancelled')
    accepted = line_qs.aggregate(s=Sum('accepted_quantity'))['s'] or Decimal('0.00')
    rejected = line_qs.aggregate(s=Sum('rejected_quantity'))['s'] or Decimal('0.00')
    inspected = accepted + rejected
    acceptance_rate = int(round(accepted / inspected * 100)) if inspected > 0 else 0

    top_discrepancies = list(
        line_qs.exclude(discrepancy_type='none')
        .values('discrepancy_type')
        .annotate(n=Count('id'))
        .order_by('-n')[:5]
    )

    rtv_qs = ReturnToVendor.objects.filter(tenant=tenant)

    return {
        'total_grns': total,
        'by_status': by_status,
        'draft': by_status.get('draft', 0),
        'received': by_status.get('received', 0),
        'under_inspection': by_status.get('under_inspection', 0),
        'inspected': by_status.get('inspected', 0),
        'posted': by_status.get('posted', 0),
        'closed': by_status.get('closed', 0),
        'cancelled': by_status.get('cancelled', 0),
        'awaiting_inspection': qs.filter(
            status__in=('received', 'under_inspection')).count(),
        'total_accepted': accepted.quantize(Decimal('0.01')),
        'total_rejected': rejected.quantize(Decimal('0.01')),
        'acceptance_rate_pct': acceptance_rate,
        'open_rtvs': rtv_qs.filter(status__in=('draft', 'authorized', 'shipped')).count(),
        'tags_generated': ReceiptTag.objects.filter(tenant=tenant).count(),
        'top_discrepancies': top_discrepancies,
    }
