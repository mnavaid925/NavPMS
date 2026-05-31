"""Contract Management domain services (Module 9).

All state transitions live here, wrapped in ``@transaction.atomic`` with audit
logging via :func:`apps.tenants.services.record_audit`. Mirrors the auctions /
RFx service style (perms + numbering + lifecycle + analytics) and adds:

  * a *mock* in-app e-signature flow (tokenized links + typed-name signature),
  * a clock-free renewal/expiration alert sweep that raises portal Notifications
    (idempotent via ``Contract.renewal_alerted_at``), called by the cron command
    and lazily by the renewals board, and
  * amendment versioning that bumps ``Contract.revision``.
"""
import calendar
import secrets
from datetime import date
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
    OBLIGATION_OPEN_STATUSES,
    SIGNATORY_OPEN_STATUSES,
    Contract,
    ContractAmendment,
    ContractClauseLine,
    ContractObligation,
    ContractSignatory,
    ContractStatusEvent,
    ContractTemplate,
    ContractTemplateClause,
)

# Roles allowed to create/configure/manage contracts (mirrors auctions MANAGE_ROLES).
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


def can_manage_contract(user):
    """May create/configure/sign/terminate contracts."""
    return _has_role(user, MANAGE_ROLES)


def can_view_contract(user):
    """May view contracts / analytics (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Visibility gate (portal)
# ---------------------------------------------------------------------------
def contract_visible_to(user, contract):
    """True if ``user`` may view ``contract``.

    Internal managers/approvers may view any contract in their tenant; a vendor
    portal user may view only contracts where they are the counterparty.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_vendor_user', False):
        return getattr(user, 'vendor_id', None) == contract.vendor_id
    return can_view_contract(user)


def signatory_for_token(token):
    """Resolve a (single-use) signing token to its signatory, or ``None``."""
    if not token:
        return None
    return (
        ContractSignatory.all_objects
        .select_related('contract', 'contract__vendor')
        .filter(sign_token=token)
        .first()
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _add_months(d, months):
    """Return ``d`` shifted forward by ``months`` calendar months (clamped day)."""
    month = d.month - 1 + (months or 0)
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def record_status_event(contract, status, user, note=''):
    """Append an immutable lifecycle timeline row."""
    return ContractStatusEvent.all_objects.create(
        tenant=contract.tenant, contract=contract, status=status,
        note=(note or '')[:255], actor=user,
    )


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def next_contract_number(tenant):
    """Generate the next gap-free ``CON-<SLUG>-NNNNN`` for ``tenant``."""
    slug = (tenant.slug or str(tenant.pk))[:6].upper()
    prefix = f'CON-{slug}-'
    last = (
        Contract.all_objects
        .filter(tenant=tenant, contract_number__startswith=prefix)
        .order_by('-contract_number')
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.contract_number.rsplit('-', 1)[1]) + 1
        except (IndexError, ValueError):
            seq = 1
    number = f'{prefix}{seq:05d}'
    while Contract.all_objects.filter(
            tenant=tenant, contract_number=number).exists():
        seq += 1
        number = f'{prefix}{seq:05d}'
    return number


def next_amendment_number(contract):
    """Return the next ``<contract_number>-A0N`` amendment label."""
    n = ContractAmendment.all_objects.filter(contract=contract).count() + 1
    return f'{contract.contract_number}-A{n:02d}'


# ---------------------------------------------------------------------------
# Authoring & templating
# ---------------------------------------------------------------------------
def create_contract(*, tenant, user, **fields):
    """Create a draft Contract with an auto-assigned, collision-safe number.

    Serialises numbering with a ``select_for_update`` row lock on the tenant and
    retries on a unique-constraint collision (mirrors ``rfx.services.create_event``).
    """
    last_exc = None
    for _attempt in range(5):
        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=tenant.pk)
                contract = Contract.all_objects.create(
                    tenant=tenant,
                    contract_number=next_contract_number(tenant),
                    status='draft',
                    created_by=user,
                    **fields,
                )
                record_status_event(contract, 'draft', user, 'Contract created')
                record_audit(
                    tenant, user, 'contract.created',
                    target_type='Contract', target_id=str(contract.id),
                    message=f'{contract.contract_number}: {contract.title}',
                )
            return contract
        except IntegrityError as exc:
            last_exc = exc
    raise last_exc


def assemble_body(contract):
    """Concatenate the contract's clause lines into ``contract.body`` (snapshot)."""
    parts = []
    for line in contract.clause_lines.all():
        parts.append(f'{line.heading}\n{line.body}')
    contract.body = '\n\n'.join(parts)
    contract.save(update_fields=['body', 'updated_at'])
    return contract.body


def add_clause_from_library(contract, clause, user):
    """Append a library clause to a draft contract as the next clause line."""
    if not contract.is_editable:
        raise ValidationError('Clauses can only be changed while the contract is a draft.')
    next_order = (
        ContractClauseLine.all_objects.filter(contract=contract).count() + 1
    )
    line = ContractClauseLine.all_objects.create(
        tenant=contract.tenant, contract=contract, clause=clause,
        heading=clause.title, body=clause.body, sort_order=next_order,
    )
    assemble_body(contract)
    return line


def create_contract_from_template(template, user, *, vendor, title='', **overrides):
    """Clone a contract template into a fresh draft contract."""
    with transaction.atomic():
        contract = create_contract(
            tenant=template.tenant, user=user,
            title=title or f'{template.title} — {vendor}',
            description=template.description,
            contract_type=template.contract_type,
            vendor=vendor,
            template=template,
            owner=user,
            **overrides,
        )
        for tc in template.clauses.all():
            ContractClauseLine.all_objects.create(
                tenant=contract.tenant, contract=contract, clause=tc.clause,
                heading=tc.heading, body=tc.body, sort_order=tc.sort_order,
            )
        assemble_body(contract)
        record_audit(
            contract.tenant, user, 'contract.created_from_template',
            target_type='Contract', target_id=str(contract.id),
            message=f'{contract.contract_number} from template "{template.title}"',
        )
    return contract


def save_contract_as_template(contract, user, *, title, description='', is_shared=True):
    """Snapshot a contract's clauses into a new reusable template."""
    with transaction.atomic():
        template = ContractTemplate.all_objects.create(
            tenant=contract.tenant, title=title,
            description=description or contract.description,
            contract_type=contract.contract_type,
            is_shared=is_shared, created_by=user,
        )
        for line in contract.clause_lines.all():
            ContractTemplateClause.all_objects.create(
                tenant=contract.tenant, template=template, clause=line.clause,
                heading=line.heading, body=line.body, sort_order=line.sort_order,
            )
        record_audit(
            contract.tenant, user, 'contract.saved_as_template',
            target_type='ContractTemplate', target_id=str(template.id),
            message=f'Template "{title}" from {contract.contract_number}',
        )
    return template


# ---------------------------------------------------------------------------
# E-signature lifecycle
# ---------------------------------------------------------------------------
def validate_contract_for_signature(contract):
    """Raise ``ValidationError`` unless the contract is ready to send for signing."""
    errors = []
    if not contract.vendor_id:
        errors.append('Assign a supplier before sending for signature.')
    if not contract.clause_lines.exists() and not (contract.body or '').strip():
        errors.append('Author the contract body (add at least one clause) first.')
    if not contract.signatories.exists():
        errors.append('Add at least one signatory before sending for signature.')
    if not contract.end_date:
        errors.append('Set an end date before sending for signature.')
    if (contract.start_date and contract.end_date
            and contract.start_date >= contract.end_date):
        errors.append('End date must be after the start date.')
    if errors:
        raise ValidationError(errors)
    return []


def send_for_signature(contract, user):
    """Transition draft → pending_signature, issuing signing tokens."""
    with transaction.atomic():
        if contract.status != 'draft':
            raise ValidationError('Only draft contracts can be sent for signature.')
        validate_contract_for_signature(contract)
        contract = Contract.all_objects.select_for_update().get(pk=contract.pk)

        for signatory in contract.signatories.all():
            if signatory.status == 'pending' and not signatory.sign_token:
                signatory.sign_token = secrets.token_urlsafe(32)
                signatory.save(update_fields=['sign_token', 'updated_at'])

        contract.status = 'pending_signature'
        contract.signature_sent_at = timezone.now()
        contract.save(update_fields=['status', 'signature_sent_at', 'updated_at'])

        record_status_event(contract, 'pending_signature', user, 'Sent for signature')
        record_audit(
            contract.tenant, user, 'contract.sent_for_signature',
            target_type='Contract', target_id=str(contract.id),
            message=f'{contract.contract_number} → pending signature',
        )
        # Notify internal signatories who are app users.
        for signatory in contract.signatories.filter(party='internal', user__isnull=False):
            _notify(
                signatory.user, contract, category='approval', priority='high',
                title=f'Signature requested: {contract.contract_number}',
                message=f'Please review and sign “{contract.title}”.',
            )
    return contract


def sign_contract(signatory, user, signed_name, ip=None):
    """Record a typed-name signature; activate the contract once all have signed."""
    with transaction.atomic():
        contract = Contract.all_objects.select_for_update().get(pk=signatory.contract_id)
        if contract.status != 'pending_signature':
            raise ValidationError('This contract is not awaiting signatures.')
        if signatory.status != 'pending':
            raise ValidationError('This signatory has already responded.')
        if not (signed_name or '').strip():
            raise ValidationError('Type your full name to sign.')

        signatory.status = 'signed'
        signatory.signed_name = signed_name.strip()[:160]
        signatory.signed_at = timezone.now()
        signatory.signature_ip = (ip or '')[:45]
        signatory.save(update_fields=[
            'status', 'signed_name', 'signed_at', 'signature_ip', 'updated_at',
        ])
        record_audit(
            contract.tenant, user, 'contract.signatory.signed',
            target_type='Contract', target_id=str(contract.id),
            message=f'{signatory.name} signed {contract.contract_number}',
        )
        # Re-fetch to reflect the just-saved signature in is_fully_signed.
        contract.refresh_from_db()
        if contract.is_fully_signed:
            activate_contract(contract, user)
    return signatory


def decline_signature(signatory, user, reason=''):
    """Decline a signature; the contract drops back to draft for re-authoring."""
    with transaction.atomic():
        contract = signatory.contract
        if signatory.status != 'pending':
            raise ValidationError('This signatory has already responded.')
        signatory.status = 'declined'
        signatory.decline_reason = (reason or '').strip()[:255]
        signatory.save(update_fields=['status', 'decline_reason', 'updated_at'])

        if contract.status == 'pending_signature':
            contract.status = 'draft'
            contract.signature_sent_at = None
            contract.save(update_fields=['status', 'signature_sent_at', 'updated_at'])
            record_status_event(
                contract, 'draft', user,
                f'{signatory.name} declined: {signatory.decline_reason}'[:255],
            )
        record_audit(
            contract.tenant, user, 'contract.signatory.declined', level='warning',
            target_type='Contract', target_id=str(contract.id),
            message=f'{signatory.name} declined {contract.contract_number}',
        )
        if contract.owner_id:
            _notify(
                contract.owner, contract, category='approval', priority='high',
                title=f'Signature declined: {contract.contract_number}',
                message=f'{signatory.name} declined to sign “{contract.title}”.',
            )
    return signatory


def activate_contract(contract, user):
    """Transition a fully-signed contract pending_signature → active."""
    with transaction.atomic():
        if contract.status != 'pending_signature':
            raise ValidationError('Only contracts awaiting signature can be activated.')
        if not contract.is_fully_signed:
            raise ValidationError('All signatories must sign before activation.')
        now = timezone.now()
        contract.status = 'active'
        if not contract.signed_at:
            contract.signed_at = now
        contract.activated_at = now
        contract.save(update_fields=['status', 'signed_at', 'activated_at', 'updated_at'])
        record_status_event(contract, 'active', user, 'All parties signed')
        record_audit(
            contract.tenant, user, 'contract.activated',
            target_type='Contract', target_id=str(contract.id),
            message=f'{contract.contract_number} is now active',
        )
        if contract.owner_id:
            _notify(
                contract.owner, contract, category='info', priority='normal',
                title=f'Contract active: {contract.contract_number}',
                message=f'“{contract.title}” is fully executed and active.',
            )
    return contract


def terminate_contract(contract, user, reason):
    """Terminate an active contract with a reason."""
    with transaction.atomic():
        if not contract.can_terminate:
            raise ValidationError('Only active contracts can be terminated.')
        contract.status = 'terminated'
        contract.terminated_reason = (reason or '').strip()[:255]
        contract.terminated_at = timezone.now()
        contract.terminated_by = user
        contract.save(update_fields=[
            'status', 'terminated_reason', 'terminated_at', 'terminated_by',
            'updated_at',
        ])
        record_status_event(contract, 'terminated', user, contract.terminated_reason)
        record_audit(
            contract.tenant, user, 'contract.terminated', level='warning',
            target_type='Contract', target_id=str(contract.id),
            message=f'{contract.contract_number} terminated: {contract.terminated_reason}'[:255],
        )
    return contract


def cancel_contract(contract, user, reason):
    """Cancel a draft / pending-signature contract."""
    with transaction.atomic():
        if not contract.can_cancel:
            raise ValidationError('This contract can no longer be cancelled.')
        contract.status = 'cancelled'
        contract.cancelled_reason = (reason or '').strip()[:255]
        contract.cancelled_at = timezone.now()
        contract.save(update_fields=[
            'status', 'cancelled_reason', 'cancelled_at', 'updated_at',
        ])
        record_status_event(contract, 'cancelled', user, contract.cancelled_reason)
        record_audit(
            contract.tenant, user, 'contract.cancelled', level='warning',
            target_type='Contract', target_id=str(contract.id),
            message=f'{contract.contract_number} cancelled: {contract.cancelled_reason}'[:255],
        )
    return contract


def renew_contract(contract, user):
    """Clone an active/expired contract into a fresh draft renewal.

    The new contract links back via ``parent_contract``, picks up where the old
    term ended, and copies the clause lines, signatories (reset to pending) and
    obligations (reset to pending). The predecessor moves to ``renewed``.
    """
    with transaction.atomic():
        if not contract.can_renew:
            raise ValidationError('Only active or expired contracts can be renewed.')

        start = contract.end_date or timezone.localdate()
        end = _add_months(start, contract.renewal_term_months or 12)

        new_contract = create_contract(
            tenant=contract.tenant, user=user,
            title=f'{contract.title} (renewal)',
            description=contract.description,
            contract_type=contract.contract_type,
            category=contract.category,
            vendor=contract.vendor,
            currency=contract.currency,
            value=contract.value,
            terms_and_conditions=contract.terms_and_conditions,
            start_date=start,
            end_date=end,
            auto_renew=contract.auto_renew,
            renewal_term_months=contract.renewal_term_months,
            renewal_notice_days=contract.renewal_notice_days,
            parent_contract=contract,
            template=contract.template,
            owner=contract.owner or user,
        )
        for line in contract.clause_lines.all():
            ContractClauseLine.all_objects.create(
                tenant=new_contract.tenant, contract=new_contract,
                clause=line.clause, heading=line.heading, body=line.body,
                sort_order=line.sort_order,
            )
        assemble_body(new_contract)
        for s in contract.signatories.all():
            ContractSignatory.all_objects.create(
                tenant=new_contract.tenant, contract=new_contract, party=s.party,
                user=s.user, vendor=s.vendor, name=s.name, email=s.email,
                title=s.title, order=s.order, status='pending',
            )
        for o in contract.obligations.all():
            ContractObligation.all_objects.create(
                tenant=new_contract.tenant, contract=new_contract,
                obligation_type=o.obligation_type, title=o.title,
                description=o.description, amount=o.amount,
                penalty_amount=o.penalty_amount, account_code=o.account_code,
                responsible_party=o.responsible_party, owner=o.owner,
                status='pending',
            )

        contract.status = 'renewed'
        contract.save(update_fields=['status', 'updated_at'])
        record_status_event(contract, 'renewed', user,
                            f'Renewed as {new_contract.contract_number}')
        record_audit(
            contract.tenant, user, 'contract.renewed',
            target_type='Contract', target_id=str(contract.id),
            message=f'{contract.contract_number} renewed as {new_contract.contract_number}',
        )
    return new_contract


def expire_contract(contract, user=None):
    """Lazily flip an active, past-due, non-auto-renew contract to ``expired``."""
    if contract.status != 'active':
        return contract
    if not contract.is_past_due:
        return contract
    if contract.auto_renew:
        return contract
    contract.status = 'expired'
    contract.save(update_fields=['status', 'updated_at'])
    record_status_event(contract, 'expired', user, 'Term ended')
    record_audit(
        contract.tenant, user, 'contract.expired',
        target_type='Contract', target_id=str(contract.id),
        message=f'{contract.contract_number} expired',
    )
    return contract


# ---------------------------------------------------------------------------
# Amendments
# ---------------------------------------------------------------------------
def apply_amendment(amendment, user):
    """Apply a draft/pending amendment to its contract, bumping the revision."""
    with transaction.atomic():
        contract = Contract.all_objects.select_for_update().get(pk=amendment.contract_id)
        if not amendment.is_editable:
            raise ValidationError('This amendment has already been resolved.')
        if contract.status in ('cancelled', 'terminated'):
            raise ValidationError('Cannot amend a closed contract.')

        amendment.prev_value = contract.value
        amendment.prev_end_date = contract.end_date

        if amendment.new_value is not None:
            contract.value = amendment.new_value
        if amendment.new_end_date:
            contract.end_date = amendment.new_end_date
            contract.renewal_alerted_at = None  # new term — re-arm the alert
        if (amendment.new_body or '').strip():
            contract.body = amendment.new_body

        contract.revision = (contract.revision or 1) + 1
        contract.save(update_fields=[
            'value', 'end_date', 'renewal_alerted_at', 'body', 'revision',
            'updated_at',
        ])

        amendment.status = 'applied'
        amendment.applied_at = timezone.now()
        amendment.applied_by = user
        amendment.save(update_fields=[
            'status', 'applied_at', 'applied_by', 'prev_value', 'prev_end_date',
            'updated_at',
        ])
        record_status_event(
            contract, contract.status, user,
            f'Amendment {amendment.amendment_number} applied (rev {contract.revision})',
        )
        record_audit(
            contract.tenant, user, 'contract.amendment.applied',
            target_type='Contract', target_id=str(contract.id),
            message=f'{amendment.amendment_number} applied to {contract.contract_number}',
            payload={
                'amendment_id': amendment.id,
                'revision': contract.revision,
                'new_value': str(amendment.new_value) if amendment.new_value is not None else None,
                'new_end_date': amendment.new_end_date.isoformat() if amendment.new_end_date else None,
            },
        )
    return amendment


def cancel_amendment(amendment, user, reason=''):
    """Cancel a draft/pending amendment without touching the contract."""
    with transaction.atomic():
        if not amendment.is_editable:
            raise ValidationError('This amendment has already been resolved.')
        amendment.status = 'cancelled'
        amendment.save(update_fields=['status', 'updated_at'])
        record_audit(
            amendment.tenant, user, 'contract.amendment.cancelled', level='warning',
            target_type='ContractAmendment', target_id=str(amendment.id),
            message=f'{amendment.amendment_number} cancelled',
        )
    return amendment


# ---------------------------------------------------------------------------
# Obligations
# ---------------------------------------------------------------------------
def complete_obligation(obligation, user):
    """Mark an open obligation completed."""
    with transaction.atomic():
        if obligation.status not in OBLIGATION_OPEN_STATUSES:
            raise ValidationError('Only open obligations can be completed.')
        obligation.status = 'completed'
        obligation.completed_at = timezone.now()
        obligation.completed_by = user
        obligation.save(update_fields=[
            'status', 'completed_at', 'completed_by', 'updated_at',
        ])
        record_audit(
            obligation.tenant, user, 'contract.obligation.completed',
            target_type='ContractObligation', target_id=str(obligation.id),
            message=f'Obligation "{obligation.title}" completed',
        )
    return obligation


def waive_obligation(obligation, user, reason=''):
    """Waive an open obligation."""
    with transaction.atomic():
        if obligation.status not in OBLIGATION_OPEN_STATUSES:
            raise ValidationError('Only open obligations can be waived.')
        obligation.status = 'waived'
        if reason:
            obligation.notes = (obligation.notes + f'\nWaived: {reason}').strip()
        obligation.save(update_fields=['status', 'notes', 'updated_at'])
        record_audit(
            obligation.tenant, user, 'contract.obligation.waived', level='warning',
            target_type='ContractObligation', target_id=str(obligation.id),
            message=f'Obligation "{obligation.title}" waived',
        )
    return obligation


def mark_overdue_obligations(tenant):
    """Flip pending/in-progress obligations past their due date to ``overdue``.

    Bulk, idempotent. Returns the number flipped.
    """
    today = timezone.localdate()
    return (
        ContractObligation.all_objects
        .filter(tenant=tenant, status__in=('pending', 'in_progress'),
                due_date__lt=today)
        .update(status='overdue')
    )


# ---------------------------------------------------------------------------
# Renewal & expiration alert sweep (sub-module 3)
# ---------------------------------------------------------------------------
def _notify(user, contract, *, category, priority, title, message):
    """Create a portal Notification linking to a contract."""
    if not user:
        return None
    try:
        link = reverse('contracts:contract_detail', kwargs={'pk': contract.pk})
    except Exception:
        link = ''
    return Notification.all_objects.create(
        tenant=contract.tenant, user=user, category=category, priority=priority,
        title=title[:160], message=message, link_url=link,
    )


def scan_contract_alerts(tenant=None, now=None):
    """Raise renewal/expiry alerts, auto-renew or expire past-due contracts.

    Idempotent: an expiring contract is alerted only once (guarded by
    ``renewal_alerted_at``). Called by the ``run_contract_alerts`` command (no
    ``tenant`` → all tenants) and lazily by the renewals board (single tenant).
    Returns a counts dict.
    """
    if tenant is None:
        totals = {'alerted': 0, 'auto_renewed': 0, 'expired': 0, 'overdue': 0}
        for t in Tenant.objects.all():
            set_current_tenant(t)
            counts = scan_contract_alerts(tenant=t, now=now)
            for k in totals:
                totals[k] += counts.get(k, 0)
        return totals

    counts = {'alerted': 0, 'auto_renewed': 0, 'expired': 0, 'overdue': 0}

    active = Contract.all_objects.filter(
        tenant=tenant, status='active', end_date__isnull=False,
    )
    for contract in active:
        # Expiring soon → one-time notification to the owner.
        if contract.is_expiring_soon and contract.renewal_alerted_at is None:
            days = contract.days_to_expiry
            priority = 'urgent' if days <= 7 else ('high' if days <= 14 else 'normal')
            verb = 'auto-renews' if contract.auto_renew else 'expires'
            if contract.owner_id:
                _notify(
                    contract.owner, contract, category='deadline', priority=priority,
                    title=f'Contract {verb} in {days} day(s): {contract.contract_number}',
                    message=f'“{contract.title}” {verb} on {contract.end_date}.',
                )
            contract.renewal_alerted_at = timezone.now()
            contract.save(update_fields=['renewal_alerted_at', 'updated_at'])
            record_audit(
                tenant, None, 'contract.renewal_alert',
                target_type='Contract', target_id=str(contract.id),
                message=f'{contract.contract_number} {verb} in {days} day(s)',
            )
            counts['alerted'] += 1

        # Past due → auto-renew (extend term) or expire.
        if contract.is_past_due:
            if contract.auto_renew:
                contract.end_date = _add_months(
                    contract.end_date, contract.renewal_term_months or 12)
                contract.renewal_alerted_at = None
                contract.save(update_fields=[
                    'end_date', 'renewal_alerted_at', 'updated_at'])
                record_status_event(contract, 'active', None,
                                    f'Auto-renewed to {contract.end_date}')
                record_audit(
                    tenant, None, 'contract.auto_renewed',
                    target_type='Contract', target_id=str(contract.id),
                    message=f'{contract.contract_number} auto-renewed to {contract.end_date}',
                )
                counts['auto_renewed'] += 1
            else:
                expire_contract(contract, None)
                counts['expired'] += 1

    counts['overdue'] = mark_overdue_obligations(tenant)
    return counts


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
def tenant_contract_metrics(tenant):
    """Aggregate contract KPIs for the tenant analytics dashboard."""
    qs = Contract.objects.filter(tenant=tenant)
    by_status = dict(qs.values_list('status').annotate(n=Count('id')))
    total = qs.count()

    total_value = qs.aggregate(s=Sum('value'))['s'] or Decimal('0.00')
    active_qs = qs.filter(status='active')
    active_value = active_qs.aggregate(s=Sum('value'))['s'] or Decimal('0.00')

    expiring_soon = sum(1 for c in active_qs if c.is_expiring_soon)

    obl = ContractObligation.objects.filter(contract__tenant=tenant)
    open_obligations = obl.filter(status__in=OBLIGATION_OPEN_STATUSES).count()
    overdue_obligations = obl.filter(status='overdue').count()
    obligation_value = obl.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

    top_vendors = list(
        active_qs.values('vendor__legal_name')
        .annotate(n=Count('id'), v=Sum('value'))
        .order_by('-n', '-v')[:5]
    )

    return {
        'total_contracts': total,
        'by_status': by_status,
        'draft': by_status.get('draft', 0),
        'pending_signature': by_status.get('pending_signature', 0),
        'active': by_status.get('active', 0),
        'expired': by_status.get('expired', 0),
        'terminated': by_status.get('terminated', 0),
        'renewed': by_status.get('renewed', 0),
        'cancelled': by_status.get('cancelled', 0),
        'total_value': total_value.quantize(Decimal('0.01')),
        'active_value': active_value.quantize(Decimal('0.01')),
        'expiring_soon': expiring_soon,
        'open_obligations': open_obligations,
        'overdue_obligations': overdue_obligations,
        'obligation_value': obligation_value.quantize(Decimal('0.01')),
        'top_vendors': top_vendors,
    }


def contract_analytics(contract):
    """Per-contract analytics: signing progress, obligations, amendments, expiry."""
    obligations = ContractObligation.all_objects.filter(contract=contract)
    total_obl = obligations.count()
    completed_obl = obligations.filter(status='completed').count()
    overdue_obl = obligations.filter(status='overdue').count()
    obl_completion = int(round(completed_obl / total_obl * 100)) if total_obl else 0

    return {
        'signatory_count': contract.signatory_count,
        'signed_count': contract.signed_count,
        'signature_progress': contract.signature_progress,
        'obligation_count': total_obl,
        'completed_obligations': completed_obl,
        'overdue_obligations': overdue_obl,
        'obligation_completion': obl_completion,
        'amendment_count': ContractAmendment.all_objects.filter(contract=contract).count(),
        'days_to_expiry': contract.days_to_expiry,
        'revision': contract.revision,
        'value': contract.value,
        'obligation_value': obligations.aggregate(s=Sum('amount'))['s'] or Decimal('0.00'),
    }
