"""Core dashboard view — aggregates KPIs from tenants/accounts."""
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.utils import timezone
from django.views import View


class DashboardView(LoginRequiredMixin, View):
    template_name = 'dashboard/index.html'

    def get(self, request):
        from apps.accounts.models import User, UserInvite
        from apps.tenants.models import (
            Subscription, Invoice, AuditLog, HealthMetric,
        )

        tenant = request.tenant
        if tenant is None:
            return render(request, self.template_name, {'no_tenant': True})

        today = timezone.now()
        thirty_days_ago = today - timedelta(days=30)

        subscription = (
            Subscription.objects.filter(tenant=tenant)
            .select_related('plan').order_by('-started_at').first()
        )
        active_users = User.objects.filter(tenant=tenant, is_active=True).count()
        pending_invites = UserInvite.objects.filter(
            tenant=tenant, status='pending',
        ).count()

        open_invoices_qs = Invoice.objects.filter(
            tenant=tenant, status__in=['sent', 'overdue', 'draft'],
        )
        open_invoices_count = open_invoices_qs.count()
        outstanding_balance = sum(
            (inv.total for inv in open_invoices_qs), Decimal('0.00'),
        )

        last_payment = (
            Invoice.objects.filter(tenant=tenant, status='paid')
            .order_by('-paid_at').first()
        )

        metrics = list(
            HealthMetric.objects.filter(
                tenant=tenant, recorded_at__gte=thirty_days_ago,
            ).order_by('recorded_at')
        )
        metric_dates = [m.recorded_at.strftime('%Y-%m-%d') for m in metrics]
        user_count_series = [m.value for m in metrics if m.metric_type == 'user_count']
        api_call_series = [m.value for m in metrics if m.metric_type == 'api_calls']

        recent_activity = (
            AuditLog.objects.filter(tenant=tenant)
            .select_related('user').order_by('-created_at')[:10]
        )

        context = {
            'subscription': subscription,
            'active_users': active_users,
            'pending_invites': pending_invites,
            'open_invoices_count': open_invoices_count,
            'outstanding_balance': outstanding_balance,
            'last_payment': last_payment,
            'metric_dates': metric_dates,
            'user_count_series': user_count_series,
            'api_call_series': api_call_series,
            'recent_activity': recent_activity,
        }
        return render(request, self.template_name, context)
