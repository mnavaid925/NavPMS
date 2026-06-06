"""Module 1 service layer: billing, branding, audit, health."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import Tenant
from .gateways import get_gateway
from .models import (
    AuditLog, BrandingSettings, HealthMetric, Invoice, Plan,
    SecuritySettings, Subscription, Transaction,
)


def _invoice_prefix(tenant: Tenant) -> str:
    """Canonical invoice-number prefix for a tenant.

    Strip hyphens first, then truncate to 6 chars, so the seed command and the
    service layer always mint the same prefix for a given tenant.
    """
    slug = (tenant.slug or 'x').upper().replace('-', '')[:6]
    return f'INV-{slug}-'


def _next_invoice_number(tenant: Tenant) -> str:
    """Next invoice number from MAX(suffix)+1 (not COUNT()+1).

    COUNT()+1 reuses an already-issued number after any invoice is deleted, which
    violates the unique constraint on Invoice.number. Deriving from the highest
    existing suffix is delete-safe; create_invoice_for_subscription wraps the
    insert in a retry loop to absorb the residual race between concurrent issuers.
    """
    prefix = _invoice_prefix(tenant)
    highest = 0
    for number in (
        Invoice.objects.filter(tenant=tenant, number__startswith=prefix)
        .values_list('number', flat=True)
    ):
        suffix = number.rsplit('-', 1)[-1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f'{prefix}{highest + 1:05d}'


def start_trial_for_new_tenant(tenant: Tenant) -> Subscription:
    """Provision a trial subscription, branding, and security defaults."""
    plan = (
        Plan.objects.filter(is_active=True)
        .order_by('sort_order', 'price_monthly').first()
    )
    if plan is None:
        plan = Plan.objects.create(
            name='Free', slug='free',
            description='Default plan for new tenants',
            price_monthly=Decimal('0.00'), price_yearly=Decimal('0.00'),
            trial_days=14, max_users=3, max_storage_gb=1,
            features=['Dashboard', 'User management', 'Up to 3 users'],
            sort_order=1,
        )

    now = timezone.now()
    trial_end = now + timedelta(days=plan.trial_days or 14)
    sub = Subscription.objects.create(
        tenant=tenant,
        plan=plan,
        status='trial',
        billing_cycle='monthly',
        started_at=now,
        trial_ends_at=trial_end,
        current_period_start=now,
        current_period_end=trial_end,
    )
    BrandingSettings.objects.get_or_create(tenant=tenant)
    SecuritySettings.objects.get_or_create(tenant=tenant)
    record_audit(tenant, None, 'tenant.trial_started',
                 message=f'Trial started on {plan.name}',
                 payload={'plan_id': plan.id, 'trial_ends_at': trial_end.isoformat()})
    return sub


def create_invoice_for_subscription(
    sub: Subscription, period_start=None, period_end=None,
    tax_rate: Decimal = Decimal('0.00'),
) -> Invoice:
    period_start = period_start or sub.current_period_start
    period_end = period_end or sub.current_period_end or (
        period_start + (timedelta(days=365) if sub.billing_cycle == 'yearly' else timedelta(days=30))
    )
    amount = sub.amount_for_cycle
    tax = (amount * tax_rate).quantize(Decimal('0.01'))
    total = amount + tax
    money = str(amount.quantize(Decimal('0.01')))
    line_items = [{
        'description': f'{sub.plan.name} subscription',
        'period_start': period_start.strftime('%Y-%m-%d'),
        'period_end': period_end.strftime('%Y-%m-%d'),
        'quantity': 1,
        'unit_price': money,
        'amount': money,
    }]
    invoice = None
    for attempt in range(5):
        try:
            with transaction.atomic():
                invoice = Invoice.objects.create(
                    tenant=sub.tenant,
                    subscription=sub,
                    number=_next_invoice_number(sub.tenant),
                    status='sent',
                    subtotal=amount,
                    tax=tax,
                    total=total,
                    currency=sub.plan.currency,
                    line_items=line_items,
                    issued_at=timezone.now(),
                    due_at=timezone.now() + timedelta(days=14),
                )
            break
        except IntegrityError:
            # A concurrent issuer grabbed the same number; recompute and retry.
            if attempt == 4:
                raise
    record_audit(sub.tenant, None, 'invoice.created',
                 target_type='Invoice', target_id=str(invoice.id),
                 message=f'Invoice {invoice.number} for {total} {invoice.currency}')
    return invoice


def charge_invoice(invoice: Invoice, *, user=None) -> Transaction | None:
    """Charge an invoice through the configured gateway, exactly once.

    The invoice row is locked with select_for_update and its status re-checked
    INSIDE the transaction, and the gateway is only called after that check, so
    concurrent pay requests (double-click, retries, two tabs) serialize: the
    first charges, the rest see status='paid' and return the existing transaction
    without charging again. Returns None only in the degenerate case where the
    invoice is already paid but has no recorded transaction.
    """
    gw = get_gateway()
    with transaction.atomic():
        inv = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if inv.status == 'paid':
            invoice.status = inv.status
            invoice.paid_at = inv.paid_at
            return (
                inv.transactions.filter(status='succeeded')
                .order_by('-created_at').first()
            )
        result = gw.charge(
            amount=inv.total, currency=inv.currency,
            description=f'NavPMS invoice {inv.number}',
            customer_ref=inv.tenant.slug,
            metadata={'tenant_id': inv.tenant_id, 'invoice_id': inv.id},
        )
        tx = Transaction.objects.create(
            tenant=inv.tenant,
            invoice=inv,
            gateway=gw.name,
            gateway_ref=result.gateway_ref,
            amount=inv.total,
            currency=inv.currency,
            status='succeeded' if result.ok else 'failed',
            method='card',
            message=result.message,
        )
        if result.ok:
            inv.status = 'paid'
            inv.paid_at = timezone.now()
            inv.save(update_fields=['status', 'paid_at', 'updated_at'])
            if inv.subscription:
                inv.subscription.status = 'active'
                inv.subscription.save(update_fields=['status', 'updated_at'])
    record_audit(
        inv.tenant, user, 'invoice.charged',
        level='info' if result.ok else 'warning',
        target_type='Invoice', target_id=str(inv.id),
        message=f'Charge {result.gateway_ref} -> {"OK" if result.ok else "FAIL"}',
    )
    # Keep the caller's in-memory instance consistent with the locked copy.
    invoice.status = inv.status
    invoice.paid_at = inv.paid_at
    return tx


def cancel_subscription(sub: Subscription, *, immediate=False, user=None):
    if immediate:
        sub.status = 'cancelled'
        sub.cancelled_at = timezone.now()
    else:
        sub.cancel_at_period_end = True
    sub.auto_renew = False
    sub.save()
    record_audit(
        sub.tenant, user, 'subscription.cancelled',
        target_type='Subscription', target_id=str(sub.id),
        message='Immediate' if immediate else 'At period end',
    )
    return sub


def _audit_canonical(entry):
    """Stable serialization of an AuditLog row's content (excludes the hash fields themselves).

    Used as the hash input so any later edit to a logged field is detectable. ``created_at`` is part
    of the input (total order is ``created_at, id``), so it must already be set — compute the hash
    after the row is inserted.
    """
    return json.dumps(
        [
            entry.tenant_id, entry.user_id, entry.action, entry.level,
            entry.target_type, entry.target_id, entry.message, entry.payload,
            entry.created_at.isoformat() if entry.created_at else '',
        ],
        sort_keys=True, separators=(',', ':'), default=str,
    )


def _audit_row_hash(prev_hash, entry):
    """sha256(prev_hash + '|' + canonical(entry)) — one link in the tamper-evident chain."""
    digest = hashlib.sha256()
    digest.update((prev_hash or '').encode('utf-8'))
    digest.update(b'|')
    digest.update(_audit_canonical(entry).encode('utf-8'))
    return digest.hexdigest()


def record_audit(tenant, user, action, *, level='info', target_type='',
                 target_id='', message='', payload=None, request=None):
    """Append a tamper-evident audit entry.

    Within a transaction the previous (chain-tip) row for the tenant is locked, the new row is
    inserted, then its ``prev_hash``/``row_hash`` are computed and saved. The ``select_for_update``
    serializes concurrent writers for one tenant so the chain never forks (Module 18, sub-module 3).
    The public signature is unchanged — callers still get the saved instance back.
    """
    ip = ua = None
    if request is not None:
        ip = request.META.get('REMOTE_ADDR')
        ua = request.META.get('HTTP_USER_AGENT', '')[:255]
    with transaction.atomic():
        prev = (
            AuditLog.all_objects.select_for_update()
            .filter(tenant=tenant)
            .order_by('-created_at', '-id')
            .first()
        )
        prev_hash = prev.row_hash if prev else ''
        entry = AuditLog.all_objects.create(
            tenant=tenant,
            user=user,
            action=action,
            level=level,
            target_type=target_type,
            target_id=str(target_id) if target_id else '',
            message=message,
            payload=payload or {},
            ip_address=ip,
            user_agent=ua or '',
            prev_hash=prev_hash,
        )
        entry.row_hash = _audit_row_hash(prev_hash, entry)
        entry.save(update_fields=['row_hash'])
    return entry


def verify_audit_chain(tenant):
    """Recompute the hash chain for ``tenant`` and report the first broken (tampered) row.

    Returns ``{'ok', 'checked', 'first_broken_id', 'first_broken_at'}``. Rows are walked in
    ``(created_at, id)`` order — the same order ``record_audit`` chains in. Pre-chain rows (blank
    ``row_hash``) are skipped until the first hashed row, which anchors the chain.
    """
    qs = AuditLog.all_objects.filter(tenant=tenant).order_by('created_at', 'id')
    prev_hash = None
    checked = 0
    for entry in qs.iterator():
        if not entry.row_hash:
            continue  # not yet chained (pre-backfill) — skip
        anchor = prev_hash if prev_hash is not None else entry.prev_hash
        expected = _audit_row_hash(anchor, entry)
        if expected != entry.row_hash or (prev_hash is not None
                                          and entry.prev_hash != prev_hash):
            return {
                'ok': False, 'checked': checked,
                'first_broken_id': entry.id, 'first_broken_at': entry.created_at,
            }
        prev_hash = entry.row_hash
        checked += 1
    return {'ok': True, 'checked': checked, 'first_broken_id': None, 'first_broken_at': None}


def record_health_metric(tenant, metric_type, value, notes=''):
    return HealthMetric.all_objects.create(
        tenant=tenant,
        metric_type=metric_type,
        value=Decimal(str(value)),
        notes=notes,
    )


def compute_tenant_usage(tenant):
    """Compute the latest snapshot of each metric for a tenant."""
    from apps.accounts.models import User

    user_count = User.objects.filter(tenant=tenant, is_active=True).count()
    storage_mb = 0  # placeholder until file-storage tracking lands
    active_subs = Subscription.objects.filter(
        tenant=tenant, status__in=['trial', 'active'],
    ).count()
    open_invoices = Invoice.objects.filter(
        tenant=tenant, status__in=['sent', 'overdue', 'draft'],
    ).count()
    return {
        'user_count': user_count,
        'storage_mb': storage_mb,
        'active_subscriptions': active_subs,
        'open_invoices': open_invoices,
    }
