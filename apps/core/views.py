"""Core views — dashboard KPIs + the global header search."""
import operator
from datetime import timedelta
from decimal import Decimal
from functools import reduce
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views import View

from apps.core.search import SEARCH_REGISTRY


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


class GlobalSearchView(LoginRequiredMixin, View):
    """Tenant-scoped omni-search behind the topbar box.

    Walks :data:`apps.core.search.SEARCH_REGISTRY`, runs an ``icontains`` OR per spec
    and groups the hits by entity type. Uses ``LoginRequiredMixin`` (not the tenant
    mixin) so a no-tenant superuser simply sees an empty result set instead of being
    bounced to onboarding — empty-for-no-tenant is the multi-tenancy contract.
    """
    template_name = 'core/search_results.html'
    per_type_limit = 6

    def get(self, request):
        q = request.GET.get('q', '').strip()
        tenant = getattr(request, 'tenant', None)
        groups = []
        total = 0

        if q and tenant is not None:
            for spec in SEARCH_REGISTRY:
                # Each spec is isolated: a single misconfigured field/route can never
                # 500 the whole page — it just drops that one group.
                try:
                    model = spec.get_model()
                    predicate = reduce(
                        operator.or_,
                        (Q(**{f'{name}__icontains': q}) for name in spec.fields),
                    )
                    rows = list(
                        model.objects.filter(tenant=tenant)
                        .filter(predicate)
                        .order_by(spec.order)[:self.per_type_limit + 1]
                    )
                except Exception:
                    continue
                if not rows:
                    continue

                items = []
                for obj in rows[:self.per_type_limit]:
                    try:
                        url = reverse(spec.url_name, kwargs={'pk': obj.pk})
                    except NoReverseMatch:
                        url = ''
                    title = getattr(obj, spec.title_field, '') if spec.title_field else ''
                    items.append({
                        'number': getattr(obj, spec.number_field, '') or '',
                        'title': title or '',
                        'url': url,
                    })
                groups.append({
                    'label': spec.label,
                    'icon': spec.icon,
                    'items': items,
                    'more': len(rows) > self.per_type_limit,
                })
                total += len(items)

        return render(request, self.template_name, {
            'q': q,
            'groups': groups,
            'total': total,
        })
