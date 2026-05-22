"""Module 2 views: personalized dashboard, widgets, notifications,
quick requisitions, self-service reports, activity feed."""
from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView

from apps.core.mixins import TenantRequiredMixin
from apps.tenants.models import AuditLog
from apps.tenants.services import record_audit

from .forms import (
    DashboardWidgetForm, NotificationForm, QuickRequisitionForm,
    QuickRequisitionItemForm, SavedReportForm,
)
from .models import (
    DashboardWidget, Notification, QuickRequisition, QuickRequisitionItem,
    SavedReport,
)
from .services import (
    build_dashboard_context, create_notification, ensure_default_widgets,
    generate_report, next_requisition_number,
)


# ---------- 1. Personalized dashboard ----------

class PortalDashboardView(TenantRequiredMixin, View):
    template_name = 'portal/dashboard.html'

    def get(self, request):
        ensure_default_widgets(request.tenant, request.user)
        widgets = DashboardWidget.objects.filter(
            tenant=request.tenant, user=request.user, is_visible=True,
        )
        ctx = build_dashboard_context(request.tenant, request.user)
        ctx['widgets'] = widgets
        return render(request, self.template_name, ctx)


# ---------- Widgets (Personalized Overview customization) ----------

class WidgetListView(TenantRequiredMixin, ListView):
    model = DashboardWidget
    template_name = 'portal/widgets/list.html'
    context_object_name = 'widgets'
    paginate_by = 20

    def get_queryset(self):
        qs = DashboardWidget.objects.filter(
            tenant=self.request.tenant, user=self.request.user,
        )
        wtype = self.request.GET.get('widget_type', '')
        if wtype:
            qs = qs.filter(widget_type=wtype)
        visible = self.request.GET.get('visible', '')
        if visible == 'visible':
            qs = qs.filter(is_visible=True)
        elif visible == 'hidden':
            qs = qs.filter(is_visible=False)
        return qs.order_by('position', 'id')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['widget_type_choices'] = DashboardWidget.WIDGET_TYPES
        return ctx


class WidgetCreateView(TenantRequiredMixin, View):
    def get(self, request):
        return render(request, 'portal/widgets/form.html', {
            'form': DashboardWidgetForm(), 'title': 'Add Widget',
        })

    def post(self, request):
        form = DashboardWidgetForm(request.POST)
        if form.is_valid():
            widget = form.save(commit=False)
            widget.tenant = request.tenant
            widget.user = request.user
            widget.save()
            messages.success(request, f'Widget "{widget.title}" added.')
            return redirect('portal:widget_list')
        return render(request, 'portal/widgets/form.html', {
            'form': form, 'title': 'Add Widget',
        })


class WidgetEditView(TenantRequiredMixin, View):
    def _get(self, request, pk):
        return get_object_or_404(
            DashboardWidget, pk=pk, tenant=request.tenant, user=request.user,
        )

    def get(self, request, pk):
        widget = self._get(request, pk)
        return render(request, 'portal/widgets/form.html', {
            'form': DashboardWidgetForm(instance=widget),
            'title': 'Edit Widget', 'widget': widget,
        })

    def post(self, request, pk):
        widget = self._get(request, pk)
        form = DashboardWidgetForm(request.POST, instance=widget)
        if form.is_valid():
            form.save()
            messages.success(request, 'Widget updated.')
            return redirect('portal:widget_list')
        return render(request, 'portal/widgets/form.html', {
            'form': form, 'title': 'Edit Widget', 'widget': widget,
        })


class WidgetDeleteView(TenantRequiredMixin, View):
    def post(self, request, pk):
        widget = get_object_or_404(
            DashboardWidget, pk=pk, tenant=request.tenant, user=request.user,
        )
        widget.delete()
        messages.success(request, 'Widget removed.')
        return redirect('portal:widget_list')

    def get(self, request, pk):
        return redirect('portal:widget_list')


# ---------- 2. Task & Alert Center ----------

class NotificationListView(TenantRequiredMixin, ListView):
    model = Notification
    template_name = 'portal/notifications/list.html'
    context_object_name = 'notifications'
    paginate_by = 20

    def get_queryset(self):
        qs = Notification.objects.filter(
            tenant=self.request.tenant, user=self.request.user,
        )
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(message__icontains=q))
        category = self.request.GET.get('category', '')
        if category:
            qs = qs.filter(category=category)
        priority = self.request.GET.get('priority', '')
        if priority:
            qs = qs.filter(priority=priority)
        read = self.request.GET.get('read', '')
        if read == 'unread':
            qs = qs.filter(is_read=False)
        elif read == 'read':
            qs = qs.filter(is_read=True)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['category_choices'] = Notification.CATEGORY_CHOICES
        ctx['priority_choices'] = Notification.PRIORITY_CHOICES
        ctx['unread_count'] = Notification.objects.filter(
            tenant=self.request.tenant, user=self.request.user, is_read=False,
        ).count()
        return ctx


class NotificationDetailView(TenantRequiredMixin, View):
    def get(self, request, pk):
        note = get_object_or_404(
            Notification, pk=pk, tenant=request.tenant, user=request.user,
        )
        note.mark_read()
        return render(request, 'portal/notifications/detail.html', {'note': note})


class NotificationCreateView(TenantRequiredMixin, View):
    def get(self, request):
        return render(request, 'portal/notifications/form.html', {
            'form': NotificationForm(), 'title': 'New Alert',
        })

    def post(self, request):
        form = NotificationForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.tenant = request.tenant
            note.user = request.user
            note.save()
            messages.success(request, 'Alert created.')
            return redirect('portal:notification_list')
        return render(request, 'portal/notifications/form.html', {
            'form': form, 'title': 'New Alert',
        })


class NotificationEditView(TenantRequiredMixin, View):
    def _get(self, request, pk):
        return get_object_or_404(
            Notification, pk=pk, tenant=request.tenant, user=request.user,
        )

    def get(self, request, pk):
        note = self._get(request, pk)
        return render(request, 'portal/notifications/form.html', {
            'form': NotificationForm(instance=note),
            'title': 'Edit Alert', 'note': note,
        })

    def post(self, request, pk):
        note = self._get(request, pk)
        form = NotificationForm(request.POST, instance=note)
        if form.is_valid():
            form.save()
            messages.success(request, 'Alert updated.')
            return redirect('portal:notification_list')
        return render(request, 'portal/notifications/form.html', {
            'form': form, 'title': 'Edit Alert', 'note': note,
        })


class NotificationDeleteView(TenantRequiredMixin, View):
    def post(self, request, pk):
        note = get_object_or_404(
            Notification, pk=pk, tenant=request.tenant, user=request.user,
        )
        note.delete()
        messages.success(request, 'Alert deleted.')
        return redirect('portal:notification_list')

    def get(self, request, pk):
        return redirect('portal:notification_list')


class NotificationMarkReadView(TenantRequiredMixin, View):
    def post(self, request, pk):
        note = get_object_or_404(
            Notification, pk=pk, tenant=request.tenant, user=request.user,
        )
        if note.is_read:
            note.is_read = False
            note.read_at = None
            note.save(update_fields=['is_read', 'read_at', 'updated_at'])
            messages.info(request, 'Alert marked unread.')
        else:
            note.mark_read()
            messages.success(request, 'Alert marked read.')
        # SQA defect D-03: validate the `next` target against an open redirect.
        nxt = request.POST.get('next', '')
        if nxt and url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
        ):
            return redirect(nxt)
        return redirect('portal:notification_list')


class NotificationMarkAllReadView(TenantRequiredMixin, View):
    def post(self, request):
        Notification.objects.filter(
            tenant=request.tenant, user=request.user, is_read=False,
        ).update(is_read=True, read_at=timezone.now())
        messages.success(request, 'All alerts marked read.')
        return redirect('portal:notification_list')


# ---------- 3. Quick Requisition Entry ----------

class RequisitionListView(TenantRequiredMixin, ListView):
    model = QuickRequisition
    template_name = 'portal/requisitions/list.html'
    context_object_name = 'requisitions'
    paginate_by = 20

    def get_queryset(self):
        qs = QuickRequisition.objects.filter(
            tenant=self.request.tenant, user=self.request.user,
        )
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(number__icontains=q) | Q(title__icontains=q)
                | Q(vendor_name__icontains=q)
            )
        status = self.request.GET.get('status', '')
        if status:
            qs = qs.filter(status=status)
        category = self.request.GET.get('category', '')
        if category:
            qs = qs.filter(category=category)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = QuickRequisition.STATUS_CHOICES
        ctx['category_choices'] = QuickRequisition.CATEGORY_CHOICES
        return ctx


class RequisitionCreateView(TenantRequiredMixin, View):
    def get(self, request):
        return render(request, 'portal/requisitions/form.html', {
            'form': QuickRequisitionForm(), 'title': 'Quick Requisition',
        })

    def post(self, request):
        form = QuickRequisitionForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.tenant = request.tenant
            req.user = request.user
            req.status = 'draft'
            # SQA defect D-04: count-based numbering can race under concurrent
            # creates — retry with a fresh number on the duplicate-key error.
            for attempt in range(5):
                req.number = next_requisition_number(request.tenant)
                try:
                    req.save()
                    break
                except IntegrityError:
                    if attempt == 4:
                        raise
            record_audit(
                request.tenant, request.user, 'requisition.created',
                target_type='QuickRequisition', target_id=req.id,
                message=f'Quick requisition {req.number} drafted',
                request=request,
            )
            messages.success(
                request, f'Requisition {req.number} created. Add items below.',
            )
            return redirect('portal:requisition_detail', pk=req.pk)
        return render(request, 'portal/requisitions/form.html', {
            'form': form, 'title': 'Quick Requisition',
        })


class RequisitionDetailView(TenantRequiredMixin, View):
    def get(self, request, pk):
        req = get_object_or_404(
            QuickRequisition, pk=pk, tenant=request.tenant, user=request.user,
        )
        return render(request, 'portal/requisitions/detail.html', {
            'req': req,
            'items': req.items.all(),
            'item_form': QuickRequisitionItemForm(),
        })


class RequisitionEditView(TenantRequiredMixin, View):
    def _get(self, request, pk):
        return get_object_or_404(
            QuickRequisition, pk=pk, tenant=request.tenant, user=request.user,
        )

    def get(self, request, pk):
        req = self._get(request, pk)
        if not req.is_editable:
            messages.error(request, 'Only draft requisitions can be edited.')
            return redirect('portal:requisition_detail', pk=req.pk)
        return render(request, 'portal/requisitions/form.html', {
            'form': QuickRequisitionForm(instance=req),
            'title': f'Edit {req.number}', 'req': req,
        })

    def post(self, request, pk):
        req = self._get(request, pk)
        if not req.is_editable:
            messages.error(request, 'Only draft requisitions can be edited.')
            return redirect('portal:requisition_detail', pk=req.pk)
        form = QuickRequisitionForm(request.POST, instance=req)
        if form.is_valid():
            form.save()
            messages.success(request, f'{req.number} updated.')
            return redirect('portal:requisition_detail', pk=req.pk)
        return render(request, 'portal/requisitions/form.html', {
            'form': form, 'title': f'Edit {req.number}', 'req': req,
        })


class RequisitionDeleteView(TenantRequiredMixin, View):
    def post(self, request, pk):
        req = get_object_or_404(
            QuickRequisition, pk=pk, tenant=request.tenant, user=request.user,
        )
        if not req.is_editable:
            messages.error(request, 'Only draft requisitions can be deleted.')
            return redirect('portal:requisition_detail', pk=req.pk)
        number = req.number
        req.delete()
        messages.success(request, f'Requisition {number} deleted.')
        return redirect('portal:requisition_list')

    def get(self, request, pk):
        return redirect('portal:requisition_list')


class RequisitionSubmitView(TenantRequiredMixin, View):
    def post(self, request, pk):
        req = get_object_or_404(
            QuickRequisition, pk=pk, tenant=request.tenant, user=request.user,
        )
        if req.status != 'draft':
            messages.info(request, 'Requisition is already submitted.')
            return redirect('portal:requisition_detail', pk=req.pk)
        if not req.items.exists():
            messages.error(request, 'Add at least one item before submitting.')
            return redirect('portal:requisition_detail', pk=req.pk)
        req.status = 'submitted'
        req.submitted_at = timezone.now()
        req.save(update_fields=['status', 'submitted_at', 'updated_at'])
        record_audit(
            request.tenant, request.user, 'requisition.submitted',
            target_type='QuickRequisition', target_id=req.id,
            message=f'Quick requisition {req.number} submitted for approval',
            request=request,
        )
        create_notification(
            request.tenant, request.user,
            f'Requisition {req.number} submitted',
            category='approval', priority='normal',
            message=f'"{req.title}" is awaiting approval.',
            link_url=f'/portal/requisitions/{req.pk}/',
        )
        messages.success(request, f'{req.number} submitted for approval.')
        return redirect('portal:requisition_detail', pk=req.pk)


class RequisitionItemAddView(TenantRequiredMixin, View):
    def post(self, request, pk):
        req = get_object_or_404(
            QuickRequisition, pk=pk, tenant=request.tenant, user=request.user,
        )
        if not req.is_editable:
            messages.error(request, 'Items can only be changed on a draft.')
            return redirect('portal:requisition_detail', pk=req.pk)
        form = QuickRequisitionItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.tenant = request.tenant
            item.requisition = req
            item.save()
            req.recalc_total()
            messages.success(request, f'Item "{item.name}" added.')
        else:
            messages.error(request, 'Could not add item — check the values.')
        return redirect('portal:requisition_detail', pk=req.pk)


class RequisitionItemDeleteView(TenantRequiredMixin, View):
    def post(self, request, pk, item_pk):
        req = get_object_or_404(
            QuickRequisition, pk=pk, tenant=request.tenant, user=request.user,
        )
        if not req.is_editable:
            messages.error(request, 'Items can only be changed on a draft.')
            return redirect('portal:requisition_detail', pk=req.pk)
        item = get_object_or_404(
            QuickRequisitionItem, pk=item_pk, requisition=req, tenant=request.tenant,
        )
        item.delete()
        req.recalc_total()
        messages.success(request, 'Item removed.')
        return redirect('portal:requisition_detail', pk=req.pk)

    def get(self, request, pk, item_pk):
        return redirect('portal:requisition_detail', pk=pk)


# ---------- 4. Recent Activity Feed ----------

class ActivityFeedView(TenantRequiredMixin, ListView):
    template_name = 'portal/activity/feed.html'
    context_object_name = 'logs'
    paginate_by = 30

    def get_queryset(self):
        qs = AuditLog.objects.filter(
            tenant=self.request.tenant, user=self.request.user,
        )
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(action__icontains=q) | Q(message__icontains=q))
        level = self.request.GET.get('level', '')
        if level:
            qs = qs.filter(level=level)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['level_choices'] = AuditLog.LEVEL_CHOICES
        return ctx


# ---------- 5. Self-Service Reporting ----------

class ReportListView(TenantRequiredMixin, ListView):
    model = SavedReport
    template_name = 'portal/reports/list.html'
    context_object_name = 'reports'
    paginate_by = 20

    def get_queryset(self):
        qs = SavedReport.objects.filter(
            tenant=self.request.tenant, user=self.request.user,
        )
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        rtype = self.request.GET.get('report_type', '')
        if rtype:
            qs = qs.filter(report_type=rtype)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['report_type_choices'] = SavedReport.REPORT_TYPES
        return ctx


class ReportCreateView(TenantRequiredMixin, View):
    def get(self, request):
        return render(request, 'portal/reports/form.html', {
            'form': SavedReportForm(), 'title': 'New Report',
        })

    def post(self, request):
        form = SavedReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.tenant = request.tenant
            report.user = request.user
            report.save()
            messages.success(request, f'Report "{report.name}" saved.')
            return redirect('portal:report_run', pk=report.pk)
        return render(request, 'portal/reports/form.html', {
            'form': form, 'title': 'New Report',
        })


class ReportEditView(TenantRequiredMixin, View):
    def _get(self, request, pk):
        return get_object_or_404(
            SavedReport, pk=pk, tenant=request.tenant, user=request.user,
        )

    def get(self, request, pk):
        report = self._get(request, pk)
        return render(request, 'portal/reports/form.html', {
            'form': SavedReportForm(instance=report),
            'title': f'Edit {report.name}', 'report': report,
        })

    def post(self, request, pk):
        report = self._get(request, pk)
        form = SavedReportForm(request.POST, instance=report)
        if form.is_valid():
            form.save()
            messages.success(request, 'Report updated.')
            return redirect('portal:report_run', pk=report.pk)
        return render(request, 'portal/reports/form.html', {
            'form': form, 'title': f'Edit {report.name}', 'report': report,
        })


class ReportDeleteView(TenantRequiredMixin, View):
    def post(self, request, pk):
        report = get_object_or_404(
            SavedReport, pk=pk, tenant=request.tenant, user=request.user,
        )
        report.delete()
        messages.success(request, 'Report deleted.')
        return redirect('portal:report_list')

    def get(self, request, pk):
        return redirect('portal:report_list')


class ReportRunView(TenantRequiredMixin, View):
    """Detail page for a SavedReport — computes and renders the result."""

    def get(self, request, pk):
        report = get_object_or_404(
            SavedReport, pk=pk, tenant=request.tenant, user=request.user,
        )
        result = generate_report(report)
        report.last_run_at = timezone.now()
        report.save(update_fields=['last_run_at', 'updated_at'])
        return render(request, 'portal/reports/detail.html', {
            'report': report, 'result': result,
        })
