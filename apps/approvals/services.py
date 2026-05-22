"""Module 4 service layer — the approval workflow engine.

Routing, delegation resolution, task progression, completion and escalation.
Imports from `apps.requisitions` are done lazily to avoid a circular import
(requisitions.services.submit_requisition calls start_approval here).
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.tenants.services import record_audit

from .models import (
    ApprovalAction, ApprovalDelegation, ApprovalRequest, ApprovalRule,
    ApprovalTask,
)


# ---------- History ----------

def record_action(request, action, actor, *, task=None, comment=''):
    """Append an immutable entry to an approval request's history."""
    return ApprovalAction.all_objects.create(
        tenant=request.tenant,
        request=request,
        task=task,
        actor=actor,
        action=action,
        comment=comment,
    )


# ---------- 1. Routing ----------

def match_rule(requisition):
    """Return the first active rule (lowest priority number) that applies."""
    rules = (
        ApprovalRule.objects.filter(
            tenant=requisition.tenant,
            document_type='requisition',
            is_active=True,
        )
        .prefetch_related('steps')
        .order_by('priority', 'name')
    )
    for rule in rules:
        if rule.matches(requisition) and rule.steps.exists():
            return rule
    return None


# ---------- 2. Delegation ----------

def resolve_approver(user, tenant):
    """Resolve an approver through any currently-active delegation (one hop)."""
    today = timezone.now().date()
    delegation = (
        ApprovalDelegation.objects.filter(
            tenant=tenant, delegator=user, is_active=True,
            start_date__lte=today, end_date__gte=today,
        )
        .order_by('-start_date')
        .first()
    )
    if delegation is not None:
        return delegation.delegate, delegation
    return user, None


# ---------- Task activation / escalation ----------

def _activate_task(task):
    """Stamp a task's escalation deadline as it becomes the active step."""
    if task.step and task.step.sla_hours:
        task.due_at = timezone.now() + timedelta(hours=task.step.sla_hours)
        task.save(update_fields=['due_at', 'updated_at'])


# ---------- Engine entry point ----------

def start_approval(requisition, submitted_by, *, request=None):
    """Route a submitted requisition through its matching approval rule.

    Returns the new ApprovalRequest, or None when no rule matches (the caller
    then falls back to the simple admin approve/reject path).
    """
    rule = match_rule(requisition)
    if rule is None:
        return None

    with transaction.atomic():
        appr = ApprovalRequest.objects.create(
            tenant=requisition.tenant,
            requisition=requisition,
            rule=rule,
            status='pending',
            current_step=1,
            submitted_by=submitted_by,
        )
        steps = list(rule.steps.order_by('order'))
        first_task = None
        for index, step in enumerate(steps, start=1):
            assigned, delegation = resolve_approver(step.approver, requisition.tenant)
            task = ApprovalTask.objects.create(
                tenant=requisition.tenant,
                request=appr,
                step=step,
                order=index,
                name=step.name,
                assigned_to=assigned,
                original_approver=step.approver,
            )
            if index == 1:
                first_task = task
            if delegation is not None:
                record_action(appr, 'delegated', step.approver, task=task,
                              comment=f'Routed to delegate {assigned}')
        appr.current_step = 1
        appr.save(update_fields=['current_step', 'updated_at'])
        record_action(appr, 'submitted', submitted_by,
                      comment=f'Routed via rule "{rule.name}"')
        if first_task is not None:
            _activate_task(first_task)

    record_audit(
        requisition.tenant, submitted_by, 'approval.started',
        target_type='Requisition', target_id=requisition.id,
        message=f'Requisition {requisition.number} routed via "{rule.name}" '
                f'({len(steps)} step{"s" if len(steps) != 1 else ""})',
        request=request,
    )
    return appr


# ---------- Acting on tasks ----------

def act_on_task(task, user, *, approved, comment='', request=None):
    """Approve or reject a single approval task and advance the workflow."""
    appr = task.request
    now = timezone.now()
    task.status = 'approved' if approved else 'rejected'
    task.acted_by = user
    task.acted_at = now
    task.comment = comment
    task.save(update_fields=['status', 'acted_by', 'acted_at', 'comment', 'updated_at'])
    record_action(appr, task.status, user, task=task, comment=comment)

    if not approved:
        appr.tasks.filter(status__in=['pending', 'escalated']).update(status='skipped')
        _complete_request(appr, approved=False, user=user, request=request)
        return appr

    next_task = (
        appr.tasks.filter(status__in=['pending', 'escalated'])
        .order_by('order').first()
    )
    if next_task is None:
        _complete_request(appr, approved=True, user=user, request=request)
    else:
        appr.current_step = next_task.order
        appr.save(update_fields=['current_step', 'updated_at'])
        _activate_task(next_task)
    return appr


def _complete_request(appr, *, approved, user, request=None):
    """Finalize an approval request and push the decision back to the requisition."""
    from apps.requisitions.services import decide_requisition

    appr.status = 'approved' if approved else 'rejected'
    appr.completed_at = timezone.now()
    appr.save(update_fields=['status', 'completed_at', 'updated_at'])
    record_action(appr, 'completed', user,
                  comment=f'Approval {appr.status}')

    requisition = appr.requisition
    if requisition.status == 'submitted':
        decide_requisition(
            requisition, user, approved=approved,
            note=f'{"Approved" if approved else "Rejected"} via approval workflow',
            request=request,
        )


# ---------- Cancellation ----------

def cancel_approval(requisition, user, *, request=None):
    """Cancel any in-flight approval request for a requisition."""
    for appr in ApprovalRequest.objects.filter(
        tenant=requisition.tenant, requisition=requisition, status='pending',
    ):
        appr.tasks.filter(status__in=['pending', 'escalated']).update(status='skipped')
        appr.status = 'cancelled'
        appr.completed_at = timezone.now()
        appr.save(update_fields=['status', 'completed_at', 'updated_at'])
        record_action(appr, 'cancelled', user, comment='Requisition withdrawn')


# ---------- 4. Escalation ----------

def escalate_overdue(tenant=None):
    """Escalate every overdue active task. Returns the number escalated.

    Used by both the `run_escalations` command and the lazy inbox sweep.
    """
    now = timezone.now()
    qs = ApprovalTask.objects.filter(
        status='pending', due_at__isnull=False, due_at__lt=now,
    ).select_related('step', 'request', 'assigned_to')
    if tenant is not None:
        qs = qs.filter(tenant=tenant)

    escalated = 0
    for task in qs:
        if task.request.status != 'pending':
            continue
        target = task.step.escalate_to if task.step else None
        task.status = 'escalated'
        task.escalated_at = now
        if target is not None:
            task.assigned_to = target
        # Give the (possibly new) approver a fresh SLA window.
        if task.step and task.step.sla_hours:
            task.due_at = now + timedelta(hours=task.step.sla_hours)
        task.save(update_fields=['status', 'escalated_at', 'assigned_to',
                                 'due_at', 'updated_at'])
        record_action(
            task.request, 'escalated', None, task=task,
            comment=(f'Overdue — escalated to {target}' if target
                     else 'Overdue — flagged for attention'),
        )
        escalated += 1
    return escalated
