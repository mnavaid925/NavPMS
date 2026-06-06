"""Module 3 views: account codes, requisition templates, requisitions
(creation, tracking, duplicate check, amendment) and the tracking board."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.views.generic import ListView

from apps.core.mixins import TenantAdminRequiredMixin, TenantRequiredMixin
from apps.tenants.services import record_audit

from .forms import (
    AccountCodeForm, RequisitionForm, RequisitionLineForm,
    RequisitionTemplateForm, RequisitionTemplateLineForm,
)
from .models import (
    AccountCode, Requisition, RequisitionLine, RequisitionTemplate,
    RequisitionTemplateLine,
)
from .services import (
    amend_requisition, cancel_requisition, convert_requisition,
    create_requisition_from_template, decide_requisition,
    find_potential_duplicates, flag_duplicates, next_requisition_number,
    record_status_event, submit_requisition,
)


def can_modify_requisition(requisition, user):
    """The requester, a tenant admin, or a superuser may modify a requisition."""
    return (
        requisition.requested_by_id == user.id
        or getattr(user, 'is_tenant_admin', False)
        or user.is_superuser
    )


# ---------- Account codes ----------

class AccountCodeListView(TenantAdminRequiredMixin, ListView):
    model = AccountCode
    template_name = 'requisitions/account_codes/list.html'
    context_object_name = 'account_codes'
    paginate_by = 20

    def get_queryset(self):
        qs = AccountCode.objects.filter(tenant=self.request.tenant)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
        active = self.request.GET.get('active', '')
        if active == 'active':
            qs = qs.filter(is_active=True)
        elif active == 'inactive':
            qs = qs.filter(is_active=False)
        return qs.order_by('code')


class AccountCodeCreateView(TenantAdminRequiredMixin, View):
    def get(self, request):
        return render(request, 'requisitions/account_codes/form.html', {
            'form': AccountCodeForm(), 'title': 'New Account Code',
        })

    def post(self, request):
        form = AccountCodeForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            code = form.save(commit=False)
            code.tenant = request.tenant
            code.save()
            messages.success(request, f'Account code {code.code} created.')
            return redirect('requisitions:account_code_list')
        return render(request, 'requisitions/account_codes/form.html', {
            'form': form, 'title': 'New Account Code',
        })


class AccountCodeEditView(TenantAdminRequiredMixin, View):
    def _get(self, request, pk):
        return get_object_or_404(AccountCode, pk=pk, tenant=request.tenant)

    def get(self, request, pk):
        code = self._get(request, pk)
        return render(request, 'requisitions/account_codes/form.html', {
            'form': AccountCodeForm(instance=code),
            'title': f'Edit {code.code}', 'account_code': code,
        })

    def post(self, request, pk):
        code = self._get(request, pk)
        form = AccountCodeForm(request.POST, instance=code, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Account code updated.')
            return redirect('requisitions:account_code_list')
        return render(request, 'requisitions/account_codes/form.html', {
            'form': form, 'title': f'Edit {code.code}', 'account_code': code,
        })


class AccountCodeDeleteView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        code = get_object_or_404(AccountCode, pk=pk, tenant=request.tenant)
        if code.requisition_lines.exists() or code.template_lines.exists():
            messages.error(
                request, 'Cannot delete an account code that is in use.',
            )
        else:
            code.delete()
            messages.success(request, 'Account code deleted.')
        return redirect('requisitions:account_code_list')

    def get(self, request, pk):
        return redirect('requisitions:account_code_list')


# ---------- Requisition templates ----------

class TemplateListView(TenantRequiredMixin, ListView):
    model = RequisitionTemplate
    template_name = 'requisitions/req_templates/list.html'
    context_object_name = 'templates'
    paginate_by = 20

    def get_queryset(self):
        qs = RequisitionTemplate.objects.filter(
            tenant=self.request.tenant,
        ).filter(Q(owner=self.request.user) | Q(is_shared=True))
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        category = self.request.GET.get('category', '')
        if category:
            qs = qs.filter(category=category)
        return qs.select_related('owner').order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['category_choices'] = RequisitionTemplate._meta.get_field('category').choices
        return ctx


class TemplateCreateView(TenantRequiredMixin, View):
    def get(self, request):
        return render(request, 'requisitions/req_templates/form.html', {
            'form': RequisitionTemplateForm(), 'title': 'New Template',
        })

    def post(self, request):
        form = RequisitionTemplateForm(request.POST)
        if form.is_valid():
            tpl = form.save(commit=False)
            tpl.tenant = request.tenant
            tpl.owner = request.user
            tpl.save()
            messages.success(request, f'Template "{tpl.name}" created. Add lines below.')
            return redirect('requisitions:template_detail', pk=tpl.pk)
        return render(request, 'requisitions/req_templates/form.html', {
            'form': form, 'title': 'New Template',
        })


class TemplateDetailView(TenantRequiredMixin, View):
    def get(self, request, pk):
        tpl = get_object_or_404(
            RequisitionTemplate.objects.filter(
                Q(owner=request.user) | Q(is_shared=True),
            ),
            pk=pk, tenant=request.tenant,
        )
        can_edit = tpl.owner_id == request.user.id or request.user.is_tenant_admin
        return render(request, 'requisitions/req_templates/detail.html', {
            'template': tpl,
            'lines': tpl.lines.select_related('account_code'),
            'line_form': RequisitionTemplateLineForm(),
            'can_edit': can_edit,
        })


class TemplateEditView(TenantRequiredMixin, View):
    def _get(self, request, pk):
        tpl = get_object_or_404(RequisitionTemplate, pk=pk, tenant=request.tenant)
        if not (tpl.owner_id == request.user.id or request.user.is_tenant_admin):
            return None
        return tpl

    def get(self, request, pk):
        tpl = self._get(request, pk)
        if tpl is None:
            messages.error(request, 'You cannot edit this template.')
            return redirect('requisitions:template_list')
        return render(request, 'requisitions/req_templates/form.html', {
            'form': RequisitionTemplateForm(instance=tpl),
            'title': f'Edit {tpl.name}', 'template': tpl,
        })

    def post(self, request, pk):
        tpl = self._get(request, pk)
        if tpl is None:
            messages.error(request, 'You cannot edit this template.')
            return redirect('requisitions:template_list')
        form = RequisitionTemplateForm(request.POST, instance=tpl)
        if form.is_valid():
            form.save()
            messages.success(request, 'Template updated.')
            return redirect('requisitions:template_detail', pk=tpl.pk)
        return render(request, 'requisitions/req_templates/form.html', {
            'form': form, 'title': f'Edit {tpl.name}', 'template': tpl,
        })


class TemplateDeleteView(TenantRequiredMixin, View):
    def post(self, request, pk):
        tpl = get_object_or_404(RequisitionTemplate, pk=pk, tenant=request.tenant)
        if not (tpl.owner_id == request.user.id or request.user.is_tenant_admin):
            messages.error(request, 'You cannot delete this template.')
            return redirect('requisitions:template_list')
        tpl.delete()
        messages.success(request, 'Template deleted.')
        return redirect('requisitions:template_list')

    def get(self, request, pk):
        return redirect('requisitions:template_list')


class TemplateLineAddView(TenantRequiredMixin, View):
    def post(self, request, pk):
        tpl = get_object_or_404(RequisitionTemplate, pk=pk, tenant=request.tenant)
        if not (tpl.owner_id == request.user.id or request.user.is_tenant_admin):
            messages.error(request, 'You cannot modify this template.')
            return redirect('requisitions:template_detail', pk=tpl.pk)
        form = RequisitionTemplateLineForm(request.POST)
        if form.is_valid():
            line = form.save(commit=False)
            line.tenant = request.tenant
            line.template = tpl
            line.save()
            messages.success(request, 'Template line added.')
        else:
            messages.error(request, 'Could not add line — check the values.')
        return redirect('requisitions:template_detail', pk=tpl.pk)


class TemplateLineDeleteView(TenantRequiredMixin, View):
    def post(self, request, pk, line_pk):
        tpl = get_object_or_404(RequisitionTemplate, pk=pk, tenant=request.tenant)
        if not (tpl.owner_id == request.user.id or request.user.is_tenant_admin):
            messages.error(request, 'You cannot modify this template.')
            return redirect('requisitions:template_detail', pk=tpl.pk)
        line = get_object_or_404(
            RequisitionTemplateLine, pk=line_pk, template=tpl, tenant=request.tenant,
        )
        line.delete()
        messages.success(request, 'Template line removed.')
        return redirect('requisitions:template_detail', pk=tpl.pk)

    def get(self, request, pk, line_pk):
        return redirect('requisitions:template_detail', pk=pk)


class TemplateUseView(TenantRequiredMixin, View):
    """Create a fresh draft requisition from a template's pre-defined lines."""

    def post(self, request, pk):
        tpl = get_object_or_404(
            RequisitionTemplate.objects.filter(
                Q(owner=request.user) | Q(is_shared=True),
            ),
            pk=pk, tenant=request.tenant,
        )
        req = create_requisition_from_template(tpl, request.user, request.tenant)
        record_audit(
            request.tenant, request.user, 'requisition.created',
            target_type='Requisition', target_id=req.id,
            message=f'Requisition {req.number} created from template "{tpl.name}"',
            request=request,
        )
        messages.success(
            request, f'Requisition {req.number} created from "{tpl.name}".',
        )
        return redirect('requisitions:requisition_detail', pk=req.pk)

    def get(self, request, pk):
        return redirect('requisitions:template_detail', pk=pk)


# ---------- Requisitions ----------

class RequisitionListView(TenantRequiredMixin, ListView):
    model = Requisition
    template_name = 'requisitions/requisitions/list.html'
    context_object_name = 'requisitions'
    paginate_by = 20

    def get_queryset(self):
        qs = Requisition.objects.filter(
            tenant=self.request.tenant,
        ).select_related('requested_by')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(number__icontains=q) | Q(title__icontains=q)
                | Q(department__icontains=q)
            )
        status = self.request.GET.get('status', '')
        if status:
            qs = qs.filter(status=status)
        category = self.request.GET.get('category', '')
        if category:
            qs = qs.filter(category=category)
        scope = self.request.GET.get('scope', '')
        if scope == 'mine':
            qs = qs.filter(requested_by=self.request.user)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = Requisition.STATUS_CHOICES
        ctx['category_choices'] = Requisition._meta.get_field('category').choices
        return ctx


class RequisitionTrackingView(TenantRequiredMixin, View):
    """A status board showing every requisition grouped by its status."""

    template_name = 'requisitions/tracking.html'

    def get(self, request):
        qs = Requisition.objects.filter(
            tenant=request.tenant,
        ).select_related('requested_by')
        scope = request.GET.get('scope', '')
        if scope == 'mine':
            qs = qs.filter(requested_by=request.user)

        columns = []
        for value, label in Requisition.STATUS_CHOICES:
            columns.append({
                'value': value,
                'label': label,
                'requisitions': list(
                    qs.filter(status=value).order_by('-created_at')
                ),
            })
        totals = qs.aggregate(total=Sum('estimated_total'))
        return render(request, self.template_name, {
            'columns': columns,
            'total_count': qs.count(),
            'grand_total': totals['total'] or 0,
        })


class RequisitionCreateView(TenantRequiredMixin, View):
    def get(self, request):
        return render(request, 'requisitions/requisitions/form.html', {
            'form': RequisitionForm(), 'title': 'New Requisition',
        })

    def post(self, request):
        form = RequisitionForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.tenant = request.tenant
            req.requested_by = request.user
            req.number = next_requisition_number(request.tenant)
            req.status = 'draft'
            req.save()
            record_status_event(req, '', 'draft', request.user, note='Requisition created')
            flag_duplicates(req)
            record_audit(
                request.tenant, request.user, 'requisition.created',
                target_type='Requisition', target_id=req.id,
                message=f'Requisition {req.number} drafted',
                request=request,
            )
            messages.success(
                request, f'Requisition {req.number} created. Add line items below.',
            )
            return redirect('requisitions:requisition_detail', pk=req.pk)
        return render(request, 'requisitions/requisitions/form.html', {
            'form': form, 'title': 'New Requisition',
        })


class RequisitionDetailView(TenantRequiredMixin, View):
    def get(self, request, pk):
        req = get_object_or_404(
            Requisition.objects.select_related('requested_by', 'decided_by',
                                                'created_from_template', 'duplicate_of'),
            pk=pk, tenant=request.tenant,
        )
        duplicates = find_potential_duplicates(req) if req.possible_duplicate else []
        # Module 4: the most recent approval request driving this requisition.
        from apps.approvals.models import ApprovalRequest
        approval_request = (
            ApprovalRequest.objects.filter(requisition=req)
            .select_related('rule').order_by('-created_at').first()
        )
        # Module 16: the most recent over-budget availability check for this requisition (banner).
        try:
            from apps.budget.services import latest_check_status
            budget_check = latest_check_status(req)
        except Exception:
            budget_check = None
        return render(request, 'requisitions/requisitions/detail.html', {
            'req': req,
            'lines': req.lines.select_related('account_code'),
            'line_form': RequisitionLineForm(),
            'status_events': req.status_events.select_related('changed_by'),
            'duplicates': duplicates,
            'can_modify': can_modify_requisition(req, request.user),
            'approval_request': approval_request,
            'budget_check': budget_check,
        })


class RequisitionEditView(TenantRequiredMixin, View):
    def _get(self, request, pk):
        return get_object_or_404(Requisition, pk=pk, tenant=request.tenant)

    def get(self, request, pk):
        req = self._get(request, pk)
        if not req.is_editable or not can_modify_requisition(req, request.user):
            messages.error(request, 'Only your own draft requisitions can be edited.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        return render(request, 'requisitions/requisitions/form.html', {
            'form': RequisitionForm(instance=req),
            'title': f'Edit {req.number}', 'req': req,
        })

    def post(self, request, pk):
        req = self._get(request, pk)
        if not req.is_editable or not can_modify_requisition(req, request.user):
            messages.error(request, 'Only your own draft requisitions can be edited.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        form = RequisitionForm(request.POST, instance=req)
        if form.is_valid():
            form.save()
            flag_duplicates(req)
            messages.success(request, f'{req.number} updated.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        return render(request, 'requisitions/requisitions/form.html', {
            'form': form, 'title': f'Edit {req.number}', 'req': req,
        })


class RequisitionDeleteView(TenantRequiredMixin, View):
    def post(self, request, pk):
        req = get_object_or_404(Requisition, pk=pk, tenant=request.tenant)
        if not req.is_editable or not can_modify_requisition(req, request.user):
            messages.error(request, 'Only your own draft requisitions can be deleted.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        number = req.number
        req.delete()
        messages.success(request, f'Requisition {number} deleted.')
        return redirect('requisitions:requisition_list')

    def get(self, request, pk):
        return redirect('requisitions:requisition_list')


class RequisitionLineAddView(TenantRequiredMixin, View):
    def post(self, request, pk):
        req = get_object_or_404(Requisition, pk=pk, tenant=request.tenant)
        if not req.is_editable or not can_modify_requisition(req, request.user):
            messages.error(request, 'Lines can only be changed on your own draft.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        form = RequisitionLineForm(request.POST)
        if form.is_valid():
            line = form.save(commit=False)
            line.tenant = request.tenant
            line.requisition = req
            line.save()
            req.recalc_total()
            messages.success(request, 'Line item added.')
        else:
            messages.error(request, 'Could not add line — check the values.')
        return redirect('requisitions:requisition_detail', pk=req.pk)


class RequisitionLineDeleteView(TenantRequiredMixin, View):
    def post(self, request, pk, line_pk):
        req = get_object_or_404(Requisition, pk=pk, tenant=request.tenant)
        if not req.is_editable or not can_modify_requisition(req, request.user):
            messages.error(request, 'Lines can only be changed on your own draft.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        line = get_object_or_404(
            RequisitionLine, pk=line_pk, requisition=req, tenant=request.tenant,
        )
        line.delete()
        req.recalc_total()
        messages.success(request, 'Line item removed.')
        return redirect('requisitions:requisition_detail', pk=req.pk)

    def get(self, request, pk, line_pk):
        return redirect('requisitions:requisition_detail', pk=pk)


# ---------- Workflow actions ----------

class RequisitionSubmitView(TenantRequiredMixin, View):
    def post(self, request, pk):
        req = get_object_or_404(Requisition, pk=pk, tenant=request.tenant)
        if req.status != 'draft' or not can_modify_requisition(req, request.user):
            messages.error(request, 'This requisition cannot be submitted.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        if not req.lines.exists():
            messages.error(request, 'Add at least one line item before submitting.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        try:
            submit_requisition(req, request.user, request=request)
        except ValidationError as exc:
            # Module 16: budget enforcement is set to 'block' and funds are insufficient.
            messages.error(request, '; '.join(exc.messages))
            return redirect('requisitions:requisition_detail', pk=req.pk)
        messages.success(request, f'{req.number} submitted for approval.')
        return redirect('requisitions:requisition_detail', pk=req.pk)


class RequisitionDecideView(TenantAdminRequiredMixin, View):
    """Approve or reject a submitted requisition (tenant admin only)."""

    def post(self, request, pk):
        req = get_object_or_404(Requisition, pk=pk, tenant=request.tenant)
        if req.status != 'submitted':
            messages.error(request, 'Only submitted requisitions can be decided.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        approved = request.POST.get('decision') == 'approve'
        note = request.POST.get('note', '').strip()
        decide_requisition(req, request.user, approved=approved,
                           note=note, request=request)
        messages.success(
            request,
            f'{req.number} {"approved" if approved else "rejected"}.',
        )
        return redirect('requisitions:requisition_detail', pk=req.pk)


class RequisitionCancelView(TenantRequiredMixin, View):
    def post(self, request, pk):
        req = get_object_or_404(Requisition, pk=pk, tenant=request.tenant)
        if not req.can_cancel or not can_modify_requisition(req, request.user):
            messages.error(request, 'This requisition cannot be cancelled.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        cancel_requisition(req, request.user,
                           note=request.POST.get('note', '').strip(), request=request)
        messages.success(request, f'{req.number} cancelled.')
        return redirect('requisitions:requisition_detail', pk=req.pk)


class RequisitionAmendView(TenantRequiredMixin, View):
    def post(self, request, pk):
        req = get_object_or_404(Requisition, pk=pk, tenant=request.tenant)
        if not req.can_amend or not can_modify_requisition(req, request.user):
            messages.error(request, 'This requisition cannot be amended.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        amend_requisition(req, request.user,
                          note=request.POST.get('note', '').strip(), request=request)
        messages.success(
            request,
            f'{req.number} reopened as draft (revision {req.revision}) for amendment.',
        )
        return redirect('requisitions:requisition_detail', pk=req.pk)


class RequisitionConvertView(TenantAdminRequiredMixin, View):
    """Mark an approved requisition as converted to a purchase order."""

    def post(self, request, pk):
        req = get_object_or_404(Requisition, pk=pk, tenant=request.tenant)
        if req.status != 'approved':
            messages.error(request, 'Only approved requisitions can be converted.')
            return redirect('requisitions:requisition_detail', pk=req.pk)
        po_reference = request.POST.get('po_reference', '').strip()
        if not po_reference:
            po_reference = f'PO-{req.number.split("-", 1)[-1]}'
        convert_requisition(req, request.user, po_reference=po_reference, request=request)
        messages.success(request, f'{req.number} converted to {po_reference}.')
        return redirect('requisitions:requisition_detail', pk=req.pk)
