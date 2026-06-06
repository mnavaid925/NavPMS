"""Module 3 service layer: numbering, status workflow, duplicate detection,
and template instantiation."""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.tenants.services import record_audit

from .models import (
    Requisition, RequisitionLine, RequisitionStatusEvent, RequisitionTemplate,
)

DUPLICATE_WINDOW_DAYS = 30


# ---------- Numbering ----------

def next_requisition_number(tenant) -> str:
    """Generate the next REQ-<SLUG>-NNNNN number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = Requisition.all_objects.filter(tenant=tenant).count() + 1
    number = f'REQ-{slug}-{count:05d}'
    while Requisition.all_objects.filter(number=number).exists():
        count += 1
        number = f'REQ-{slug}-{count:05d}'
    return number


# ---------- 2. Tracking ----------

def record_status_event(requisition, from_status, to_status, user, note=''):
    """Append an immutable entry to a requisition's status timeline."""
    return RequisitionStatusEvent.all_objects.create(
        tenant=requisition.tenant,
        requisition=requisition,
        from_status=from_status,
        to_status=to_status,
        changed_by=user,
        note=note,
    )


# ---------- 3. Duplicate detection ----------

def find_potential_duplicates(requisition, days=DUPLICATE_WINDOW_DAYS):
    """Return requisitions by the same user that look like duplicates of this one.

    A match is another recent requisition with an equal (case-insensitive) title
    or at least one shared line description.
    """
    window_start = timezone.now() - timedelta(days=days)
    candidates = (
        Requisition.objects.filter(
            tenant=requisition.tenant,
            requested_by=requisition.requested_by,
            created_at__gte=window_start,
        )
        .exclude(pk=requisition.pk)
        .exclude(status__in=['cancelled', 'rejected'])
        .prefetch_related('lines')
    )

    title = (requisition.title or '').strip().lower()
    my_lines = {
        (ln.description or '').strip().lower()
        for ln in requisition.lines.all()
        if (ln.description or '').strip()
    }

    matches = []
    for cand in candidates:
        if title and (cand.title or '').strip().lower() == title:
            matches.append(cand)
            continue
        if my_lines:
            cand_lines = {
                (ln.description or '').strip().lower()
                for ln in cand.lines.all()
            }
            if my_lines & cand_lines:
                matches.append(cand)
    return matches


def flag_duplicates(requisition):
    """Set the possible_duplicate / duplicate_of fields from a fresh scan."""
    matches = find_potential_duplicates(requisition)
    requisition.possible_duplicate = bool(matches)
    requisition.duplicate_of = matches[0] if matches else None
    requisition.save(update_fields=['possible_duplicate', 'duplicate_of', 'updated_at'])
    return matches


# ---------- 4. Templates ----------

def create_requisition_from_template(template: RequisitionTemplate, user, tenant):
    """Instantiate a new draft requisition from a template's pre-defined lines."""
    with transaction.atomic():
        req = Requisition.objects.create(
            tenant=tenant,
            requested_by=user,
            number=next_requisition_number(tenant),
            title=template.name,
            category=template.category,
            justification=template.description,
            created_from_template=template,
            status='draft',
        )
        for tline in template.lines.all():
            RequisitionLine.objects.create(
                tenant=tenant,
                requisition=req,
                description=tline.description,
                quantity=tline.quantity,
                unit=tline.unit,
                unit_price=tline.estimated_unit_price,
                account_code=tline.account_code or template.default_account_code,
            )
        req.recalc_total()
        record_status_event(req, '', 'draft', user,
                             note=f'Created from template "{template.name}"')
    return req


# ---------- 1./5. Status workflow ----------

def submit_requisition(requisition, user, *, request=None):
    """Move a draft requisition to submitted, scan for duplicates, and route it
    through the Module 4 approval workflow engine.

    If a matching approval rule exists the requisition is driven by the engine;
    otherwise it falls back to the simple admin approve/reject path.
    """
    # Module 16: real-time budget-availability check FIRST, before any status mutation. In 'warn'
    # mode it only flags + alerts the budget owner and returns; in 'block' mode it raises
    # ValidationError so the requisition is left untouched (the BudgetCheck evidence still persists,
    # as it is written outside this flow). Lazy import avoids an app-load cycle.
    from apps.budget.services import check_requisition_budget
    check_requisition_budget(requisition, user, request=request)

    from_status = requisition.status
    requisition.status = 'submitted'
    requisition.submitted_at = timezone.now()
    requisition.save(update_fields=['status', 'submitted_at', 'updated_at'])
    record_status_event(requisition, from_status, 'submitted', user,
                         note='Submitted for approval')
    flag_duplicates(requisition)
    record_audit(
        requisition.tenant, user, 'requisition.submitted',
        target_type='Requisition', target_id=requisition.id,
        message=f'Requisition {requisition.number} submitted for approval',
        request=request,
    )
    # Lazy import avoids a circular dependency with apps.approvals.services.
    from apps.approvals.services import start_approval
    start_approval(requisition, user, request=request)
    return requisition


def decide_requisition(requisition, user, *, approved, note='', request=None):
    """Approve or reject a submitted requisition."""
    from_status = requisition.status
    requisition.status = 'approved' if approved else 'rejected'
    requisition.decided_at = timezone.now()
    requisition.decided_by = user
    requisition.decision_note = note
    requisition.save(update_fields=[
        'status', 'decided_at', 'decided_by', 'decision_note', 'updated_at',
    ])
    record_status_event(requisition, from_status, requisition.status, user, note=note)
    record_audit(
        requisition.tenant, user,
        'requisition.approved' if approved else 'requisition.rejected',
        level='info' if approved else 'warning',
        target_type='Requisition', target_id=requisition.id,
        message=f'Requisition {requisition.number} '
                f'{"approved" if approved else "rejected"}',
        request=request,
    )
    return requisition


def cancel_requisition(requisition, user, *, note='', request=None):
    """Cancel a draft, submitted, or approved requisition."""
    from_status = requisition.status
    requisition.status = 'cancelled'
    requisition.cancelled_at = timezone.now()
    requisition.save(update_fields=['status', 'cancelled_at', 'updated_at'])
    record_status_event(requisition, from_status, 'cancelled', user,
                         note=note or 'Cancelled')
    record_audit(
        requisition.tenant, user, 'requisition.cancelled',
        target_type='Requisition', target_id=requisition.id,
        message=f'Requisition {requisition.number} cancelled',
        request=request,
    )
    # Withdraw any in-flight approval workflow.
    from apps.approvals.services import cancel_approval
    cancel_approval(requisition, user, request=request)
    return requisition


def amend_requisition(requisition, user, *, note='', request=None):
    """Pull a submitted/approved requisition back to draft for revision."""
    from_status = requisition.status
    requisition.status = 'draft'
    requisition.revision += 1
    requisition.submitted_at = None
    requisition.decided_at = None
    requisition.decided_by = None
    requisition.decision_note = ''
    requisition.save(update_fields=[
        'status', 'revision', 'submitted_at', 'decided_at', 'decided_by',
        'decision_note', 'updated_at',
    ])
    record_status_event(
        requisition, from_status, 'draft', user,
        note=note or f'Amended — reopened as revision {requisition.revision}',
    )
    record_audit(
        requisition.tenant, user, 'requisition.amended',
        target_type='Requisition', target_id=requisition.id,
        message=f'Requisition {requisition.number} amended '
                f'(revision {requisition.revision})',
        request=request,
    )
    # Withdraw the in-flight approval workflow; re-submitting starts a fresh one.
    from apps.approvals.services import cancel_approval
    cancel_approval(requisition, user, request=request)
    return requisition


def convert_requisition(requisition, user, *, po_reference, request=None):
    """Mark an approved requisition as converted to a purchase order."""
    from_status = requisition.status
    requisition.status = 'converted'
    requisition.converted_at = timezone.now()
    requisition.po_reference = po_reference
    requisition.save(update_fields=[
        'status', 'converted_at', 'po_reference', 'updated_at',
    ])
    record_status_event(requisition, from_status, 'converted', user,
                         note=f'Converted to PO {po_reference}')
    record_audit(
        requisition.tenant, user, 'requisition.converted',
        target_type='Requisition', target_id=requisition.id,
        message=f'Requisition {requisition.number} converted to PO {po_reference}',
        request=request,
    )
    return requisition
