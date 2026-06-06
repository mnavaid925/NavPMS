"""Module 17 vendor-portal views: supplier-facing performance visibility.

Mirrors :mod:`apps.goods_receipt.portal_views`: every view is gated by ``@vendor_required`` and
scoped to ``request.user.vendor`` and its tenant. A supplier sees only their own FINAL scorecards
(drafts are never exposed), the aggregate feedback about them (reviewer names hidden for candour),
and their non-draft improvement plans — which they may acknowledge.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Avg
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.vendors.decorators import vendor_required

from . import services
from .models import ImprovementPlan, PerformanceFeedback, Scorecard


@vendor_required
def portal_scorecards(request):
    """The supplier's own finalised scorecards + trend."""
    vendor = request.user.vendor
    cards = (
        Scorecard.all_objects
        .filter(tenant=vendor.tenant, vendor=vendor, status__in=('final', 'archived'))
        .order_by('-period_end')
    )
    trend = services.vendor_trend(vendor)
    return render(request, 'vendor_portal/supplier_performance/scorecards.html', {
        'vendor': vendor, 'scorecards': cards, 'trend': trend,
    })


@vendor_required
def portal_scorecard_detail(request, pk):
    """One of the supplier's own finalised scorecards (draft cards 404)."""
    vendor = request.user.vendor
    card = get_object_or_404(
        Scorecard, pk=pk, tenant=vendor.tenant, vendor=vendor, status__in=('final', 'archived'))
    return render(request, 'vendor_portal/supplier_performance/scorecard_detail.html', {
        'vendor': vendor, 'card': card, 'lines': card.lines.all(),
    })


@vendor_required
def portal_feedback(request):
    """Aggregate feedback facets about the supplier (reviewer identities hidden for candour)."""
    vendor = request.user.vendor
    submitted = PerformanceFeedback.all_objects.filter(
        tenant=vendor.tenant, vendor=vendor, status='submitted')
    agg = submitted.aggregate(
        overall=Avg('rating'), quality=Avg('quality_rating'),
        delivery=Avg('delivery_rating'), communication=Avg('communication_rating'))
    return render(request, 'vendor_portal/supplier_performance/feedback.html', {
        'vendor': vendor, 'agg': agg, 'count': submitted.count(),
    })


@vendor_required
def portal_pips(request):
    """The supplier's own non-draft improvement plans."""
    vendor = request.user.vendor
    plans = (
        ImprovementPlan.all_objects
        .filter(tenant=vendor.tenant, vendor=vendor)
        .exclude(status='draft')
        .order_by('-created_at')
    )
    return render(request, 'vendor_portal/supplier_performance/pips.html', {
        'vendor': vendor, 'plans': plans,
    })


def _get_visible_pip(request, pk):
    vendor = request.user.vendor
    return get_object_or_404(
        ImprovementPlan.all_objects.exclude(status='draft'),
        pk=pk, tenant=vendor.tenant, vendor=vendor)


@vendor_required
def portal_pip_detail(request, pk):
    """Read view of one of the supplier's non-draft improvement plans + its actions."""
    plan = _get_visible_pip(request, pk)
    return render(request, 'vendor_portal/supplier_performance/pip_detail.html', {
        'vendor': request.user.vendor, 'plan': plan,
        'actions': plan.actions.all(),
        'status_events': plan.status_events.select_related('actor'),
    })


@vendor_required
@require_POST
def portal_pip_acknowledge(request, pk):
    """Supplier acknowledges an improvement plan."""
    plan = _get_visible_pip(request, pk)
    try:
        services.acknowledge_plan(plan, request.user, note=request.POST.get('note', ''),
                                  request=request)
        messages.success(request, f'Plan {plan.pip_number} acknowledged.')
    except ValidationError as exc:
        for msg in exc.messages:
            messages.error(request, msg)
    return redirect('vendor_portal:performance_pip_detail', pk=plan.pk)
