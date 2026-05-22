"""Module 4 views: approval rules, delegations, requests, the approver
inbox, task review/decision, and the approval history log."""
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import ListView

from apps.core.mixins import TenantAdminRequiredMixin, TenantRequiredMixin

from .forms import ApprovalDelegationForm, ApprovalRuleForm, ApprovalStepForm
from .models import (
    ApprovalAction, ApprovalDelegation, ApprovalRequest, ApprovalRule,
    ApprovalStep, ApprovalTask,
)
from .services import act_on_task, escalate_overdue, record_action


def can_act_on_task(task, user):
    """The assigned approver, a tenant admin, or a superuser may act."""
    return (
        task.assigned_to_id == user.id
        or getattr(user, 'is_tenant_admin', False)
        or user.is_superuser
    )


# ---------- 1. Approval rules ----------

class RuleListView(TenantAdminRequiredMixin, ListView):
    model = ApprovalRule
    template_name = 'approvals/rules/list.html'
    context_object_name = 'rules'
    paginate_by = 20

    def get_queryset(self):
        qs = ApprovalRule.objects.filter(tenant=self.request.tenant)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(department__icontains=q))
        active = self.request.GET.get('active', '')
        if active == 'active':
            qs = qs.filter(is_active=True)
        elif active == 'inactive':
            qs = qs.filter(is_active=False)
        return qs.order_by('priority', 'name')


class RuleCreateView(TenantAdminRequiredMixin, View):
    def get(self, request):
        return render(request, 'approvals/rules/form.html', {
            'form': ApprovalRuleForm(), 'title': 'New Approval Rule',
        })

    def post(self, request):
        form = ApprovalRuleForm(request.POST)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.tenant = request.tenant
            rule.save()
            messages.success(request, f'Rule "{rule.name}" created. Add steps below.')
            return redirect('approvals:rule_detail', pk=rule.pk)
        return render(request, 'approvals/rules/form.html', {
            'form': form, 'title': 'New Approval Rule',
        })


class RuleDetailView(TenantAdminRequiredMixin, View):
    def get(self, request, pk):
        rule = get_object_or_404(ApprovalRule, pk=pk, tenant=request.tenant)
        return render(request, 'approvals/rules/detail.html', {
            'rule': rule,
            'steps': rule.steps.select_related('approver', 'escalate_to').order_by('order'),
            'step_form': ApprovalStepForm(tenant=request.tenant),
        })


class RuleEditView(TenantAdminRequiredMixin, View):
    def _get(self, request, pk):
        return get_object_or_404(ApprovalRule, pk=pk, tenant=request.tenant)

    def get(self, request, pk):
        rule = self._get(request, pk)
        return render(request, 'approvals/rules/form.html', {
            'form': ApprovalRuleForm(instance=rule),
            'title': f'Edit {rule.name}', 'rule': rule,
        })

    def post(self, request, pk):
        rule = self._get(request, pk)
        form = ApprovalRuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            messages.success(request, 'Rule updated.')
            return redirect('approvals:rule_detail', pk=rule.pk)
        return render(request, 'approvals/rules/form.html', {
            'form': form, 'title': f'Edit {rule.name}', 'rule': rule,
        })


class RuleDeleteView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        rule = get_object_or_404(ApprovalRule, pk=pk, tenant=request.tenant)
        if rule.requests.exists():
            messages.error(
                request, 'Cannot delete a rule that has routed approval requests.',
            )
            return redirect('approvals:rule_detail', pk=rule.pk)
        rule.delete()
        messages.success(request, 'Rule deleted.')
        return redirect('approvals:rule_list')

    def get(self, request, pk):
        return redirect('approvals:rule_list')


class StepAddView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        rule = get_object_or_404(ApprovalRule, pk=pk, tenant=request.tenant)
        form = ApprovalStepForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            step = form.save(commit=False)
            step.tenant = request.tenant
            step.rule = rule
            step.save()
            messages.success(request, f'Step "{step.name}" added.')
        else:
            messages.error(request, 'Could not add step — check the values.')
        return redirect('approvals:rule_detail', pk=rule.pk)


class StepDeleteView(TenantAdminRequiredMixin, View):
    def post(self, request, pk, step_pk):
        rule = get_object_or_404(ApprovalRule, pk=pk, tenant=request.tenant)
        step = get_object_or_404(
            ApprovalStep, pk=step_pk, rule=rule, tenant=request.tenant,
        )
        step.delete()
        messages.success(request, 'Step removed.')
        return redirect('approvals:rule_detail', pk=rule.pk)

    def get(self, request, pk, step_pk):
        return redirect('approvals:rule_detail', pk=pk)


# ---------- 2. Delegations ----------

class DelegationListView(TenantRequiredMixin, ListView):
    model = ApprovalDelegation
    template_name = 'approvals/delegations/list.html'
    context_object_name = 'delegations'
    paginate_by = 20

    def get_queryset(self):
        qs = ApprovalDelegation.objects.filter(tenant=self.request.tenant)
        if not (self.request.user.is_tenant_admin or self.request.user.is_superuser):
            qs = qs.filter(
                Q(delegator=self.request.user) | Q(delegate=self.request.user),
            )
        active = self.request.GET.get('active', '')
        if active == 'active':
            qs = qs.filter(is_active=True)
        elif active == 'inactive':
            qs = qs.filter(is_active=False)
        return qs.select_related('delegator', 'delegate').order_by('-start_date')


class DelegationCreateView(TenantRequiredMixin, View):
    def get(self, request):
        return render(request, 'approvals/delegations/form.html', {
            'form': ApprovalDelegationForm(
                tenant=request.tenant, exclude_user=request.user,
            ),
            'title': 'New Delegation',
        })

    def post(self, request):
        form = ApprovalDelegationForm(
            request.POST, tenant=request.tenant, exclude_user=request.user,
        )
        if form.is_valid():
            deleg = form.save(commit=False)
            deleg.tenant = request.tenant
            deleg.delegator = request.user
            deleg.save()
            messages.success(
                request, f'Approval authority delegated to {deleg.delegate}.',
            )
            return redirect('approvals:delegation_list')
        return render(request, 'approvals/delegations/form.html', {
            'form': form, 'title': 'New Delegation',
        })


class DelegationEditView(TenantRequiredMixin, View):
    def _get(self, request, pk):
        deleg = get_object_or_404(ApprovalDelegation, pk=pk, tenant=request.tenant)
        if not (deleg.delegator_id == request.user.id
                or request.user.is_tenant_admin or request.user.is_superuser):
            return None
        return deleg

    def get(self, request, pk):
        deleg = self._get(request, pk)
        if deleg is None:
            messages.error(request, 'You cannot edit this delegation.')
            return redirect('approvals:delegation_list')
        return render(request, 'approvals/delegations/form.html', {
            'form': ApprovalDelegationForm(
                instance=deleg, tenant=request.tenant, exclude_user=deleg.delegator,
            ),
            'title': 'Edit Delegation', 'delegation': deleg,
        })

    def post(self, request, pk):
        deleg = self._get(request, pk)
        if deleg is None:
            messages.error(request, 'You cannot edit this delegation.')
            return redirect('approvals:delegation_list')
        form = ApprovalDelegationForm(
            request.POST, instance=deleg, tenant=request.tenant,
            exclude_user=deleg.delegator,
        )
        if form.is_valid():
            form.save()
            messages.success(request, 'Delegation updated.')
            return redirect('approvals:delegation_list')
        return render(request, 'approvals/delegations/form.html', {
            'form': form, 'title': 'Edit Delegation', 'delegation': deleg,
        })


class DelegationDeleteView(TenantRequiredMixin, View):
    def post(self, request, pk):
        deleg = get_object_or_404(ApprovalDelegation, pk=pk, tenant=request.tenant)
        if not (deleg.delegator_id == request.user.id
                or request.user.is_tenant_admin or request.user.is_superuser):
            messages.error(request, 'You cannot delete this delegation.')
            return redirect('approvals:delegation_list')
        deleg.delete()
        messages.success(request, 'Delegation deleted.')
        return redirect('approvals:delegation_list')

    def get(self, request, pk):
        return redirect('approvals:delegation_list')


# ---------- Approval requests ----------

class RequestListView(TenantRequiredMixin, ListView):
    model = ApprovalRequest
    template_name = 'approvals/requests/list.html'
    context_object_name = 'requests'
    paginate_by = 20

    def get_queryset(self):
        qs = ApprovalRequest.objects.filter(
            tenant=self.request.tenant,
        ).select_related('requisition', 'rule', 'submitted_by')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(requisition__number__icontains=q)
                | Q(requisition__title__icontains=q)
            )
        status = self.request.GET.get('status', '')
        if status:
            qs = qs.filter(status=status)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = ApprovalRequest.STATUS_CHOICES
        return ctx


class RequestDetailView(TenantRequiredMixin, View):
    def get(self, request, pk):
        appr = get_object_or_404(
            ApprovalRequest.objects.select_related(
                'requisition', 'rule', 'submitted_by',
            ),
            pk=pk, tenant=request.tenant,
        )
        tasks = appr.tasks.select_related('assigned_to', 'original_approver', 'acted_by')
        active = appr.active_task
        return render(request, 'approvals/requests/detail.html', {
            'appr': appr,
            'tasks': tasks,
            'actions': appr.actions.select_related('actor', 'task'),
            'active_task': active,
            'can_act': active is not None and can_act_on_task(active, request.user),
        })


# ---------- 5. Approver inbox (mobile-friendly) ----------

class InboxView(TenantRequiredMixin, View):
    template_name = 'approvals/inbox.html'

    def get(self, request):
        # Lazy escalation sweep — keeps overdue tasks moving without a worker.
        escalated = escalate_overdue(request.tenant)
        if escalated:
            messages.info(
                request,
                f'{escalated} overdue task{"s" if escalated != 1 else ""} escalated.',
            )

        open_tasks = (
            ApprovalTask.objects.filter(
                tenant=request.tenant,
                assigned_to=request.user,
                status__in=['pending', 'escalated'],
                request__status='pending',
            )
            .select_related('request__requisition', 'request__rule', 'step')
            .order_by('due_at', 'created_at')
        )
        decided = (
            ApprovalTask.objects.filter(
                tenant=request.tenant,
                acted_by=request.user,
                status__in=['approved', 'rejected'],
            )
            .select_related('request__requisition')
            .order_by('-acted_at')[:10]
        )
        return render(request, self.template_name, {
            'open_tasks': open_tasks,
            'decided': decided,
        })


class TaskDetailView(TenantRequiredMixin, View):
    """Mobile-friendly review-and-decide page for a single approval task."""

    def get(self, request, pk):
        task = get_object_or_404(
            ApprovalTask.objects.select_related(
                'request__requisition', 'request__rule', 'assigned_to', 'step',
            ),
            pk=pk, tenant=request.tenant,
        )
        return render(request, 'approvals/task_detail.html', {
            'task': task,
            'req': task.request.requisition,
            'lines': task.request.requisition.lines.select_related('account_code'),
            'appr': task.request,
            'actions': task.request.actions.select_related('actor'),
            'can_act': task.is_open and can_act_on_task(task, request.user),
        })


class TaskActView(TenantRequiredMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(
            ApprovalTask.objects.select_related('request'),
            pk=pk, tenant=request.tenant,
        )
        if not task.is_open:
            messages.error(request, 'This task has already been actioned.')
            return redirect('approvals:task_detail', pk=task.pk)
        if not can_act_on_task(task, request.user):
            messages.error(request, 'This task is not assigned to you.')
            return redirect('approvals:task_detail', pk=task.pk)

        decision = request.POST.get('decision')
        comment = request.POST.get('comment', '').strip()
        if decision not in ('approve', 'reject'):
            messages.error(request, 'Choose approve or reject.')
            return redirect('approvals:task_detail', pk=task.pk)

        appr = act_on_task(
            task, request.user, approved=(decision == 'approve'),
            comment=comment, request=request,
        )
        if appr.status == 'approved':
            messages.success(
                request,
                f'Approved. {appr.requisition.number} is fully approved.',
            )
        elif appr.status == 'rejected':
            messages.warning(
                request, f'Rejected. {appr.requisition.number} was declined.',
            )
        else:
            messages.success(
                request, 'Step approved — routed to the next approver.',
            )
        return redirect('approvals:inbox')


class TaskCommentView(TenantRequiredMixin, View):
    def post(self, request, pk):
        task = get_object_or_404(
            ApprovalTask.objects.select_related('request'),
            pk=pk, tenant=request.tenant,
        )
        comment = request.POST.get('comment', '').strip()
        if comment:
            record_action(task.request, 'commented', request.user,
                          task=task, comment=comment)
            messages.success(request, 'Comment added.')
        return redirect('approvals:task_detail', pk=task.pk)


# ---------- 3. Approval history ----------

class HistoryView(TenantRequiredMixin, ListView):
    model = ApprovalAction
    template_name = 'approvals/history.html'
    context_object_name = 'actions'
    paginate_by = 40

    def get_queryset(self):
        qs = ApprovalAction.objects.filter(
            tenant=self.request.tenant,
        ).select_related('actor', 'request__requisition', 'task')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(request__requisition__number__icontains=q)
                | Q(comment__icontains=q)
            )
        action = self.request.GET.get('action', '')
        if action:
            qs = qs.filter(action=action)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action_choices'] = ApprovalAction.ACTION_CHOICES
        return ctx
