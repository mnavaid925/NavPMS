"""Module 1 views: onboarding wizard, plans, subscriptions, invoices,
branding, security, monitoring, audit logs."""
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from apps.core.mixins import (
    SuperAdminRequiredMixin, TenantAdminRequiredMixin, TenantRequiredMixin,
)
from apps.core.models import Tenant
from .forms import (
    BrandingForm, OnboardingCompanyForm, OnboardingPlanForm, PlanForm,
    SecurityForm, SubscriptionAssignForm,
)
from .models import (
    AuditLog, BrandingSettings, HealthMetric, Invoice, Plan,
    SecuritySettings, Subscription, Transaction,
)
from .services import (
    charge_invoice, create_invoice_for_subscription, cancel_subscription,
    compute_tenant_usage, record_audit, start_trial_for_new_tenant,
)


# ---------- Onboarding wizard ----------

class OnboardingStartView(View):
    template_name = 'tenants/onboarding/start.html'

    def get(self, request):
        return render(request, self.template_name)


class OnboardingCompanyView(View):
    template_name = 'tenants/onboarding/company.html'

    def get(self, request):
        return render(request, self.template_name, {
            'form': OnboardingCompanyForm(initial=request.session.get('onboarding_company', {})),
        })

    def post(self, request):
        form = OnboardingCompanyForm(request.POST)
        if form.is_valid():
            request.session['onboarding_company'] = {
                k: (v.isoformat() if hasattr(v, 'isoformat') else v)
                for k, v in form.cleaned_data.items()
            }
            return redirect('tenants:onboarding_plan')
        return render(request, self.template_name, {'form': form})


class OnboardingPlanView(View):
    template_name = 'tenants/onboarding/plan.html'

    def get(self, request):
        if 'onboarding_company' not in request.session:
            return redirect('tenants:onboarding_company')
        return render(request, self.template_name, {
            'form': OnboardingPlanForm(),
            'plans': Plan.objects.filter(is_active=True, is_public=True),
        })

    def post(self, request):
        if 'onboarding_company' not in request.session:
            return redirect('tenants:onboarding_company')
        form = OnboardingPlanForm(request.POST)
        if form.is_valid():
            request.session['onboarding_plan'] = {
                'plan_id': form.cleaned_data['plan'].id,
                'billing_cycle': form.cleaned_data['billing_cycle'],
            }
            return redirect('tenants:onboarding_complete')
        return render(request, self.template_name, {
            'form': form,
            'plans': Plan.objects.filter(is_active=True, is_public=True),
        })


class OnboardingCompleteView(View):
    """Review + provision the new tenant.

    GET renders a read-only confirmation page; the tenant/subscription is only
    created on POST (CSRF-protected) so a link prefetch, crawler, or accidental
    reload can never provision a tenant as a side effect of a safe GET request.
    """
    template_name = 'tenants/onboarding/complete.html'
    review_template = 'tenants/onboarding/review.html'

    def get(self, request):
        company_data = request.session.get('onboarding_company')
        plan_data = request.session.get('onboarding_plan')
        if not (company_data and plan_data):
            return redirect('tenants:onboarding_company')
        return render(request, self.review_template, {
            'company': company_data,
            'plan': Plan.objects.filter(pk=plan_data['plan_id']).first(),
            'billing_cycle': plan_data['billing_cycle'],
        })

    def post(self, request):
        company_data = request.session.get('onboarding_company')
        plan_data = request.session.get('onboarding_plan')
        if not (company_data and plan_data):
            return redirect('tenants:onboarding_company')

        with transaction.atomic():
            tenant = Tenant.objects.create(
                name=company_data['name'],
                slug=company_data.get('slug') or '',
                domain=company_data.get('domain', ''),
                email=company_data.get('email', ''),
                phone=company_data.get('phone', ''),
                address=company_data.get('address', ''),
                website=company_data.get('website', ''),
                industry=company_data.get('industry', ''),
                timezone=company_data.get('timezone', 'UTC'),
            )
            plan = Plan.objects.get(pk=plan_data['plan_id'])
            sub = start_trial_for_new_tenant(tenant)
            sub.plan = plan
            sub.billing_cycle = plan_data['billing_cycle']
            # Align the trial window to the CHOSEN plan rather than leaving the
            # default-plan trial_ends_at while stretching period_end to a full
            # paid cycle (which left status='trial' disagreeing with the dates).
            sub.trial_ends_at = sub.started_at + timedelta(days=plan.trial_days or 14)
            sub.current_period_start = sub.started_at
            sub.current_period_end = sub.trial_ends_at
            sub.save()

        request.session.pop('onboarding_company', None)
        request.session.pop('onboarding_plan', None)
        return render(request, self.template_name, {'tenant': tenant})


# ---------- Plans ----------

class PlanListView(ListView):
    model = Plan
    template_name = 'tenants/plans/list.html'
    context_object_name = 'plans'
    paginate_by = 20

    def get_queryset(self):
        qs = Plan.objects.all()
        u = self.request.user
        if not (u.is_authenticated and (u.is_superuser or getattr(u, 'role', '') == 'super_admin')):
            # Anonymous/non-admin pricing-page visitors only see published plans.
            qs = qs.filter(is_public=True, is_active=True)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q))
        active = self.request.GET.get('active', '')
        if active == 'active':
            qs = qs.filter(is_active=True)
        elif active == 'inactive':
            qs = qs.filter(is_active=False)
        return qs.order_by('sort_order', 'price_monthly')


class PlanCreateView(SuperAdminRequiredMixin, View):
    def get(self, request):
        return render(request, 'tenants/plans/form.html', {
            'form': PlanForm(), 'title': 'New Plan',
        })

    def post(self, request):
        form = PlanForm(request.POST)
        if form.is_valid():
            plan = form.save()
            messages.success(request, f'Plan "{plan.name}" created.')
            return redirect('tenants:plan_list')
        return render(request, 'tenants/plans/form.html', {
            'form': form, 'title': 'New Plan',
        })


class PlanDetailView(View):
    def get(self, request, pk):
        qs = Plan.objects.all()
        u = request.user
        if not (u.is_authenticated and (u.is_superuser or getattr(u, 'role', '') == 'super_admin')):
            # Non-public / inactive plans 404 for anonymous and non-admin users.
            qs = qs.filter(is_public=True, is_active=True)
        plan = get_object_or_404(qs, pk=pk)
        return render(request, 'tenants/plans/detail.html', {'plan': plan})


class PlanEditView(SuperAdminRequiredMixin, View):
    def get(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        return render(request, 'tenants/plans/form.html', {
            'form': PlanForm(instance=plan),
            'title': f'Edit Plan: {plan.name}',
            'plan': plan,
        })

    def post(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        form = PlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, 'Plan updated.')
            return redirect('tenants:plan_list')
        return render(request, 'tenants/plans/form.html', {
            'form': form, 'title': f'Edit Plan: {plan.name}', 'plan': plan,
        })


class PlanDeleteView(SuperAdminRequiredMixin, View):
    def post(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        if plan.subscriptions.exists():
            messages.error(request, 'Cannot delete a plan with active subscriptions.')
        else:
            plan.delete()
            messages.success(request, 'Plan deleted.')
        return redirect('tenants:plan_list')

    def get(self, request, pk):
        return redirect('tenants:plan_list')


# ---------- Subscriptions ----------

class SubscriptionListView(TenantRequiredMixin, ListView):
    model = Subscription
    template_name = 'tenants/subscriptions/list.html'
    context_object_name = 'subscriptions'
    paginate_by = 20

    def get_queryset(self):
        u = self.request.user
        qs = Subscription.objects.select_related('plan', 'tenant')
        if not (u.is_superuser or getattr(u, 'role', '') == 'super_admin'):
            qs = qs.filter(tenant=self.request.tenant)
        status = self.request.GET.get('status', '')
        if status:
            qs = qs.filter(status=status)
        return qs.order_by('-started_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = Subscription.STATUS_CHOICES
        return ctx


class SubscriptionDetailView(TenantRequiredMixin, View):
    def get(self, request, pk):
        sub = get_object_or_404(
            Subscription.objects.select_related('plan', 'tenant'),
            pk=pk,
        )
        if sub.tenant != request.tenant and not request.user.is_superuser:
            messages.error(request, 'Not authorized.')
            return redirect('tenants:subscription_list')
        invoices = Invoice.objects.filter(subscription=sub).order_by('-issued_at')[:10]
        return render(request, 'tenants/subscriptions/detail.html', {
            'subscription': sub, 'invoices': invoices,
        })


class SubscriptionAssignView(TenantAdminRequiredMixin, View):
    template_name = 'tenants/subscriptions/form.html'

    def _current(self, request):
        return (
            Subscription.objects.filter(tenant=request.tenant)
            .order_by('-started_at').first()
        )

    def get(self, request):
        sub = self._current(request)
        instance = sub or Subscription(tenant=request.tenant)
        return render(request, self.template_name, {
            'form': SubscriptionAssignForm(instance=instance),
            'current': sub,
        })

    def post(self, request):
        sub = self._current(request)
        instance = sub or Subscription(tenant=request.tenant)
        form = SubscriptionAssignForm(request.POST, instance=instance)
        if form.is_valid():
            new_sub = form.save(commit=False)
            new_sub.tenant = request.tenant
            if not new_sub.started_at:
                new_sub.started_at = timezone.now()
            if not new_sub.current_period_start:
                new_sub.current_period_start = new_sub.started_at
            if not new_sub.current_period_end:
                days = 365 if new_sub.billing_cycle == 'yearly' else 30
                new_sub.current_period_end = new_sub.started_at + timedelta(days=days)
            if new_sub.status not in ('trial', 'active'):
                new_sub.status = 'active'
            new_sub.save()
            invoice = create_invoice_for_subscription(new_sub)
            record_audit(
                request.tenant, request.user, 'subscription.assigned',
                target_type='Subscription', target_id=str(new_sub.id),
                message=f'Plan changed to {new_sub.plan.name}',
                request=request,
            )
            messages.success(
                request,
                f'Plan set to {new_sub.plan.name}. Invoice {invoice.number} issued.',
            )
            return redirect('tenants:subscription_detail', pk=new_sub.pk)
        return render(request, self.template_name, {'form': form, 'current': sub})


class SubscriptionCancelView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        sub = get_object_or_404(Subscription, pk=pk, tenant=request.tenant)
        immediate = request.POST.get('immediate') == '1'
        cancel_subscription(sub, immediate=immediate, user=request.user)
        messages.success(
            request,
            'Subscription cancelled.' if immediate else 'Will cancel at period end.',
        )
        return redirect('tenants:subscription_detail', pk=sub.pk)


# ---------- Invoices ----------

class InvoiceListView(TenantRequiredMixin, ListView):
    model = Invoice
    template_name = 'tenants/invoices/list.html'
    context_object_name = 'invoices'
    paginate_by = 20

    def get_queryset(self):
        u = self.request.user
        qs = Invoice.objects.select_related('tenant', 'subscription__plan')
        if not (u.is_superuser or getattr(u, 'role', '') == 'super_admin'):
            qs = qs.filter(tenant=self.request.tenant)
        status = self.request.GET.get('status', '')
        if status:
            qs = qs.filter(status=status)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(tenant__name__icontains=q))
        return qs.order_by('-issued_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = Invoice.STATUS_CHOICES
        return ctx


class InvoiceDetailView(TenantRequiredMixin, View):
    def get(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk)
        if invoice.tenant != request.tenant and not request.user.is_superuser:
            messages.error(request, 'Not authorized.')
            return redirect('tenants:invoice_list')
        return render(request, 'tenants/invoices/detail.html', {
            'invoice': invoice,
            'transactions': invoice.transactions.order_by('-created_at'),
        })


class InvoicePayView(TenantAdminRequiredMixin, View):
    def post(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk, tenant=request.tenant)
        if invoice.status == 'paid':
            messages.info(request, 'Invoice already paid.')
            return redirect('tenants:invoice_detail', pk=pk)
        tx = charge_invoice(invoice, user=request.user)
        if tx is None:
            messages.info(request, 'Invoice already paid.')
        elif tx.status == 'succeeded':
            messages.success(request, f'Payment succeeded. Ref: {tx.gateway_ref}')
        else:
            messages.error(request, f'Payment failed: {tx.message}')
        return redirect('tenants:invoice_detail', pk=pk)


# ---------- Branding ----------

class BrandingEditView(TenantAdminRequiredMixin, View):
    template_name = 'tenants/branding/edit.html'

    def get(self, request):
        branding, _ = BrandingSettings.objects.get_or_create(tenant=request.tenant)
        return render(request, self.template_name, {
            'form': BrandingForm(instance=branding), 'branding': branding,
        })

    def post(self, request):
        branding, _ = BrandingSettings.objects.get_or_create(tenant=request.tenant)
        form = BrandingForm(request.POST, request.FILES, instance=branding)
        if form.is_valid():
            form.save()
            record_audit(
                request.tenant, request.user, 'branding.updated',
                message='Branding settings updated', request=request,
            )
            messages.success(request, 'Branding updated.')
            return redirect('tenants:branding_edit')
        return render(request, self.template_name, {
            'form': form, 'branding': branding,
        })


# ---------- Security ----------

class SecurityEditView(TenantAdminRequiredMixin, View):
    template_name = 'tenants/security/edit.html'

    def get(self, request):
        security, _ = SecuritySettings.objects.get_or_create(tenant=request.tenant)
        return render(request, self.template_name, {
            'form': SecurityForm(instance=security), 'security': security,
        })

    def post(self, request):
        security, _ = SecuritySettings.objects.get_or_create(tenant=request.tenant)
        form = SecurityForm(request.POST, instance=security)
        if form.is_valid():
            form.save()
            record_audit(
                request.tenant, request.user, 'security.updated',
                level='warning', message='Security policy updated',
                request=request,
            )
            messages.success(request, 'Security policy updated.')
            return redirect('tenants:security_edit')
        return render(request, self.template_name, {
            'form': form, 'security': security,
        })


# ---------- Monitoring ----------

class MonitoringDashboardView(TenantAdminRequiredMixin, View):
    template_name = 'tenants/monitoring/dashboard.html'

    def get(self, request):
        tenant = request.tenant
        thirty_days_ago = timezone.now() - timedelta(days=30)
        usage = compute_tenant_usage(tenant)
        metrics_qs = HealthMetric.objects.filter(
            tenant=tenant, recorded_at__gte=thirty_days_ago,
        ).order_by('recorded_at')

        def series(metric_type):
            return [
                {
                    'date': m.recorded_at.strftime('%Y-%m-%d'),
                    'value': float(m.value),
                }
                for m in metrics_qs if m.metric_type == metric_type
            ]

        invoice_totals = (
            Invoice.objects.filter(tenant=tenant, status='paid')
            .aggregate(total=Sum('total'))
        )
        latest_logs = AuditLog.objects.filter(tenant=tenant).order_by('-created_at')[:10]

        return render(request, self.template_name, {
            'usage': usage,
            'series_users': series('user_count'),
            'series_storage': series('storage_mb'),
            'series_api_calls': series('api_calls'),
            'series_sessions': series('active_sessions'),
            'paid_total': invoice_totals.get('total') or Decimal('0.00'),
            'latest_logs': latest_logs,
        })


class AuditLogListView(TenantAdminRequiredMixin, ListView):
    model = AuditLog
    template_name = 'tenants/monitoring/audit_logs.html'
    context_object_name = 'logs'
    paginate_by = 30

    def get_queryset(self):
        qs = AuditLog.objects.filter(tenant=self.request.tenant).select_related('user')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(action__icontains=q)
                | Q(message__icontains=q)
                | Q(target_type__icontains=q)
            )
        level = self.request.GET.get('level', '')
        if level:
            qs = qs.filter(level=level)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['level_choices'] = AuditLog.LEVEL_CHOICES
        return ctx
