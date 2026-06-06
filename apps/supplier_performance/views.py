"""Module 17 views: Supplier Performance & Evaluation (internal side).

Function-based views mirroring budget/spend_analytics: ``@login_required`` + a ``_require_view`` /
``_require_manage`` permission gate, tenant-scoped lookups, list search + filters + ``Paginator``.

SECURITY (lessons.md D-01/D-02): EVERY read view AND both export endpoints call ``_require_view``
first — analytics/exports must never be gated on tenant alone. Mutations call ``_require_manage``.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

# Reuse the project's shared CSV/XLSX helpers (Module 15 owns them).
from apps.spend_analytics.exports import csv_response, xlsx_response
from apps.vendors.decorators import vendor_blocked
from apps.vendors.models import Vendor

from . import services
from .forms import (
    FeedbackRequestForm, FeedbackSubmitForm, ImprovementPlanForm, KpiDefinitionForm,
    PIPActionForm, ScorecardGenerateForm,
)
from .models import (
    FEEDBACK_STATUS_CHOICES, KPI_TYPE_CHOICES, PIP_STATUS_CHOICES, RATING_BAND_CHOICES,
    SCORECARD_STATUS_CHOICES, ImprovementPlan, KpiDefinition, PerformanceFeedback, PIPAction,
    Scorecard,
)

VALID_FORMATS = ('csv', 'xlsx')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _has_named_url(name):
    try:
        reverse(name)
        return True
    except Exception:
        return False


def _require_view(request):
    if not services.can_view_supplier_performance(request.user):
        messages.error(request, 'You do not have permission to view supplier performance.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_manage(request):
    if not services.can_manage_supplier_performance(request.user):
        messages.error(request, 'You do not have permission to manage supplier performance.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _querystring(request, *drop):
    qs = request.GET.copy()
    for key in ('page',) + drop:
        qs.pop(key, None)
    return qs.urlencode()


def _deliver(fmt, filename, header, rows, *, sheet_title='Performance'):
    if fmt == 'csv':
        return csv_response(filename, header, rows)
    return xlsx_response(filename, header, rows, sheet_title=sheet_title)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
@vendor_blocked
def dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied
    metrics = services.tenant_performance_metrics(request.tenant)
    recent = (
        Scorecard.objects.filter(tenant=request.tenant, status='final')
        .select_related('vendor').order_by('-generated_at')[:8]
    )
    open_pips = (
        ImprovementPlan.objects.filter(tenant=request.tenant, status__in=('open', 'in_progress'))
        .select_related('vendor').order_by('target_date')[:8]
    )
    return render(request, 'supplier_performance/dashboard.html', {
        'metrics': metrics, 'recent': recent, 'open_pips': open_pips,
        'can_manage': services.can_manage_supplier_performance(request.user),
    })


# ---------------------------------------------------------------------------
# KPI Definitions
# ---------------------------------------------------------------------------
@login_required
@vendor_blocked
def kpi_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = KpiDefinition.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q) | Q(description__icontains=q))
    kpi_type = request.GET.get('kpi_type', '')
    if kpi_type:
        qs = qs.filter(kpi_type=kpi_type)
    status = request.GET.get('status', '')
    if status == 'active':
        qs = qs.filter(is_active=True)
    elif status == 'inactive':
        qs = qs.filter(is_active=False)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    total_weight = sum(k.weight for k in KpiDefinition.objects.filter(
        tenant=request.tenant, is_active=True))
    return render(request, 'supplier_performance/kpi_list.html', {
        'page_obj': page_obj, 'kpis': page_obj.object_list, 'q': q,
        'kpi_type': kpi_type, 'status': status,
        'kpi_type_choices': KPI_TYPE_CHOICES, 'total_weight': total_weight,
        'querystring': _querystring(request),
        'can_manage': services.can_manage_supplier_performance(request.user),
    })


@login_required
@vendor_blocked
def kpi_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = KpiDefinitionForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            kpi = form.save(commit=False)
            kpi.tenant = request.tenant
            kpi.save()
            services.record_audit(
                request.tenant, request.user, 'supplier_performance.kpi_created',
                target_type='KpiDefinition', target_id=str(kpi.pk),
                message=f'KPI {kpi.code} created.', request=request)
            messages.success(request, f'KPI {kpi.code} created.')
            return redirect('supplier_performance:kpi_list')
    else:
        form = KpiDefinitionForm(tenant=request.tenant)
    return render(request, 'supplier_performance/kpi_form.html', {'form': form, 'is_edit': False})


@login_required
@vendor_blocked
def kpi_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    kpi = get_object_or_404(KpiDefinition, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = KpiDefinitionForm(request.POST, instance=kpi, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'KPI updated.')
            return redirect('supplier_performance:kpi_list')
    else:
        form = KpiDefinitionForm(instance=kpi, tenant=request.tenant)
    return render(request, 'supplier_performance/kpi_form.html',
                  {'form': form, 'kpi': kpi, 'is_edit': True})


@login_required
@vendor_blocked
@require_POST
def kpi_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    kpi = get_object_or_404(KpiDefinition, pk=pk, tenant=request.tenant)
    code = kpi.code
    kpi.delete()
    messages.success(request, f'KPI {code} deleted.')
    return redirect('supplier_performance:kpi_list')


@login_required
@vendor_blocked
@require_POST
def kpi_restore_defaults(request):
    denied = _require_manage(request)
    if denied:
        return denied
    created = services.ensure_default_kpis(request.tenant)
    messages.success(request, f'Restored default KPIs ({created} added).')
    return redirect('supplier_performance:kpi_list')


# ---------------------------------------------------------------------------
# Scorecards
# ---------------------------------------------------------------------------
@login_required
@vendor_blocked
def scorecard_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = Scorecard.objects.filter(tenant=request.tenant).select_related('vendor')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(scorecard_number__icontains=q) | Q(vendor__legal_name__icontains=q)
                       | Q(period_label__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    band = request.GET.get('band', '')
    if band:
        qs = qs.filter(rating_band=band)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'supplier_performance/scorecard_list.html', {
        'page_obj': page_obj, 'scorecards': page_obj.object_list, 'q': q,
        'status': status, 'band': band,
        'status_choices': SCORECARD_STATUS_CHOICES, 'band_choices': RATING_BAND_CHOICES,
        'querystring': _querystring(request),
        'can_manage': services.can_manage_supplier_performance(request.user),
    })


@login_required
@vendor_blocked
def scorecard_generate(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = ScorecardGenerateForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                card = services.generate_scorecard(
                    cd['vendor'], cd['period_start'], cd['period_end'], request.user,
                    period_label=cd['period_label'],
                    status='final' if cd['finalize'] else 'draft', request=request)
                messages.success(
                    request, f'Scorecard {card.scorecard_number} generated '
                             f'({card.overall_score}, {card.get_rating_band_display()}).')
                return redirect('supplier_performance:scorecard_detail', pk=card.pk)
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
    else:
        form = ScorecardGenerateForm(tenant=request.tenant)
    return render(request, 'supplier_performance/scorecard_form.html', {'form': form})


@login_required
@vendor_blocked
def scorecard_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    card = get_object_or_404(
        Scorecard.objects.select_related('vendor', 'generated_by'), pk=pk, tenant=request.tenant)
    return render(request, 'supplier_performance/scorecard_detail.html', {
        'card': card,
        'lines': card.lines.select_related('kpi').all(),
        'pips': card.improvement_plans.all(),
        'can_manage': services.can_manage_supplier_performance(request.user),
    })


@login_required
@vendor_blocked
@require_POST
def scorecard_finalize(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    card = get_object_or_404(Scorecard, pk=pk, tenant=request.tenant)
    try:
        services.finalize_scorecard(card, request.user, request=request)
        messages.success(request, f'Scorecard {card.scorecard_number} finalized.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('supplier_performance:scorecard_detail', pk=card.pk)


@login_required
@vendor_blocked
@require_POST
def scorecard_regenerate(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    card = get_object_or_404(Scorecard, pk=pk, tenant=request.tenant)
    try:
        services.regenerate_scorecard(card, request.user, request=request)
        messages.success(request, 'Scorecard recomputed from current data.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('supplier_performance:scorecard_detail', pk=card.pk)


@login_required
@vendor_blocked
@require_POST
def scorecard_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    card = get_object_or_404(Scorecard, pk=pk, tenant=request.tenant)
    number = card.scorecard_number
    services.record_audit(
        request.tenant, request.user, 'supplier_performance.scorecard_deleted', level='warning',
        target_type='Scorecard', target_id=str(card.pk),
        message=f'Scorecard {number} deleted.', request=request)
    card.delete()
    messages.success(request, f'Scorecard {number} deleted.')
    return redirect('supplier_performance:scorecard_list')


@login_required
@vendor_blocked
def export_scorecard(request, pk, fmt):
    denied = _require_view(request)
    if denied:
        return denied
    if fmt not in VALID_FORMATS:
        raise Http404()
    card = get_object_or_404(Scorecard, pk=pk, tenant=request.tenant)
    header, rows = services.scorecard_rows_for_export(card)
    services.record_audit(
        request.tenant, request.user, 'supplier_performance.exported',
        target_type='Scorecard', target_id=str(card.pk),
        message=f'Scorecard {card.scorecard_number} export ({fmt}).', request=request)
    return _deliver(fmt, f'scorecard-{card.scorecard_number}.{fmt}', header, rows,
                    sheet_title='Scorecard')


# ---------------------------------------------------------------------------
# 360° Feedback
# ---------------------------------------------------------------------------
@login_required
@vendor_blocked
def feedback_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = (
        PerformanceFeedback.objects.filter(tenant=request.tenant)
        .select_related('vendor', 'reviewer')
    )
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(vendor__legal_name__icontains=q) | Q(comments__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'supplier_performance/feedback_list.html', {
        'page_obj': page_obj, 'feedback': page_obj.object_list, 'q': q, 'status': status,
        'status_choices': FEEDBACK_STATUS_CHOICES, 'querystring': _querystring(request),
        'can_manage': services.can_manage_supplier_performance(request.user),
        'my_pending': PerformanceFeedback.objects.filter(
            tenant=request.tenant, reviewer=request.user, status='requested').count(),
    })


@login_required
@vendor_blocked
def feedback_request(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = FeedbackRequestForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            cd = form.cleaned_data
            services.request_feedback(
                cd['vendor'], cd['reviewer'], request.user,
                period_label=cd['period_label'], request=request)
            messages.success(request, f'Feedback requested from {cd["reviewer"]}.')
            return redirect('supplier_performance:feedback_list')
    else:
        form = FeedbackRequestForm(tenant=request.tenant)
    return render(request, 'supplier_performance/feedback_request_form.html', {'form': form})


@login_required
@vendor_blocked
def feedback_submit(request, pk):
    # Any logged-in internal user who is the assigned reviewer (or a manager) may submit.
    if not (services.can_view_supplier_performance(request.user)
            or PerformanceFeedback.objects.filter(
                pk=pk, tenant=request.tenant, reviewer=request.user).exists()):
        messages.error(request, 'You do not have permission to submit this feedback.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    fb = get_object_or_404(PerformanceFeedback, pk=pk, tenant=request.tenant)
    is_reviewer = fb.reviewer_id == request.user.id
    if not (is_reviewer or services.can_manage_supplier_performance(request.user)):
        messages.error(request, 'Only the assigned reviewer can submit this feedback.')
        return redirect('supplier_performance:feedback_list')
    if request.method == 'POST':
        form = FeedbackSubmitForm(request.POST, instance=fb)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                services.submit_feedback(
                    fb, request.user, rating=cd['rating'],
                    quality_rating=cd['quality_rating'], delivery_rating=cd['delivery_rating'],
                    communication_rating=cd['communication_rating'],
                    would_recommend=cd['would_recommend'], comments=cd['comments'],
                    request=request)
                messages.success(request, 'Feedback submitted. Thank you.')
                return redirect('supplier_performance:feedback_list')
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
    else:
        form = FeedbackSubmitForm(instance=fb)
    return render(request, 'supplier_performance/feedback_submit_form.html',
                  {'form': form, 'feedback': fb})


@login_required
@vendor_blocked
@require_POST
def feedback_cancel(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    fb = get_object_or_404(PerformanceFeedback, pk=pk, tenant=request.tenant)
    try:
        services.cancel_feedback(fb, request.user, request=request)
        messages.success(request, 'Feedback request cancelled.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('supplier_performance:feedback_list')


# ---------------------------------------------------------------------------
# Performance Improvement Plans
# ---------------------------------------------------------------------------
@login_required
@vendor_blocked
def pip_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = ImprovementPlan.objects.filter(tenant=request.tenant).select_related('vendor', 'owner')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(pip_number__icontains=q) | Q(title__icontains=q)
                       | Q(vendor__legal_name__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'supplier_performance/pip_list.html', {
        'page_obj': page_obj, 'pips': page_obj.object_list, 'q': q, 'status': status,
        'status_choices': PIP_STATUS_CHOICES, 'querystring': _querystring(request),
        'can_manage': services.can_manage_supplier_performance(request.user),
    })


@login_required
@vendor_blocked
def pip_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    initial = {}
    scorecard_id = request.GET.get('scorecard')
    if scorecard_id:
        card = Scorecard.objects.filter(pk=scorecard_id, tenant=request.tenant).first()
        if card:
            initial = {'vendor': card.vendor_id, 'scorecard': card.pk,
                       'title': f'Improvement plan — {card.vendor.legal_name}'}
    if request.method == 'POST':
        form = ImprovementPlanForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            plan = services.create_plan(
                form.cleaned_data['vendor'], request.user,
                title=form.cleaned_data['title'], summary=form.cleaned_data['summary'],
                severity=form.cleaned_data['severity'], owner=form.cleaned_data['owner'],
                target_date=form.cleaned_data['target_date'],
                scorecard=form.cleaned_data['scorecard'], request=request)
            messages.success(request, f'Improvement plan {plan.pip_number} created.')
            return redirect('supplier_performance:pip_detail', pk=plan.pk)
    else:
        form = ImprovementPlanForm(tenant=request.tenant, initial=initial)
    return render(request, 'supplier_performance/pip_form.html', {'form': form, 'is_edit': False})


@login_required
@vendor_blocked
def pip_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    plan = get_object_or_404(
        ImprovementPlan.objects.select_related('vendor', 'owner', 'scorecard'),
        pk=pk, tenant=request.tenant)
    labels = dict(PIP_STATUS_CHOICES)
    next_statuses = [(s, labels.get(s, s)) for s in services.PIP_TRANSITIONS.get(plan.status, ())]
    return render(request, 'supplier_performance/pip_detail.html', {
        'plan': plan,
        'actions': plan.actions.select_related('assigned_to').all(),
        'status_events': plan.status_events.select_related('actor'),
        'next_statuses': next_statuses,
        'action_form': PIPActionForm(tenant=request.tenant),
        'can_manage': services.can_manage_supplier_performance(request.user),
    })


@login_required
@vendor_blocked
def pip_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    plan = get_object_or_404(ImprovementPlan, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = ImprovementPlanForm(request.POST, instance=plan, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Improvement plan updated.')
            return redirect('supplier_performance:pip_detail', pk=plan.pk)
    else:
        form = ImprovementPlanForm(instance=plan, tenant=request.tenant)
    return render(request, 'supplier_performance/pip_form.html',
                  {'form': form, 'plan': plan, 'is_edit': True})


@login_required
@vendor_blocked
@require_POST
def pip_set_status(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    plan = get_object_or_404(ImprovementPlan, pk=pk, tenant=request.tenant)
    try:
        services.set_plan_status(plan, request.POST.get('status', ''), request.user,
                                 note=request.POST.get('note', ''), request=request)
        messages.success(request, f'Plan {plan.pip_number} is now {plan.get_status_display()}.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('supplier_performance:pip_detail', pk=plan.pk)


@login_required
@vendor_blocked
@require_POST
def pip_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    plan = get_object_or_404(ImprovementPlan, pk=pk, tenant=request.tenant)
    number = plan.pip_number
    services.record_audit(
        request.tenant, request.user, 'supplier_performance.pip_deleted', level='warning',
        target_type='ImprovementPlan', target_id=str(plan.pk),
        message=f'PIP {number} deleted.', request=request)
    plan.delete()
    messages.success(request, f'Improvement plan {number} deleted.')
    return redirect('supplier_performance:pip_list')


@login_required
@vendor_blocked
def pip_action_create(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    plan = get_object_or_404(ImprovementPlan, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = PIPActionForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            action = form.save(commit=False)
            action.tenant = request.tenant
            action.improvement_plan = plan
            if not action.line_no:
                action.line_no = plan.actions.count() + 1
            action.save()
            messages.success(request, 'Action added.')
            return redirect('supplier_performance:pip_detail', pk=plan.pk)
    else:
        form = PIPActionForm(tenant=request.tenant)
    return render(request, 'supplier_performance/pip_action_form.html',
                  {'form': form, 'plan': plan, 'is_edit': False})


@login_required
@vendor_blocked
def pip_action_edit(request, pk, apk):
    denied = _require_manage(request)
    if denied:
        return denied
    plan = get_object_or_404(ImprovementPlan, pk=pk, tenant=request.tenant)
    action = get_object_or_404(PIPAction, pk=apk, improvement_plan=plan, tenant=request.tenant)
    if request.method == 'POST':
        form = PIPActionForm(request.POST, instance=action, tenant=request.tenant)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.status == 'done' and not obj.completed_at:
                obj.completed_at = timezone.now()
            obj.save()
            messages.success(request, 'Action updated.')
            return redirect('supplier_performance:pip_detail', pk=plan.pk)
    else:
        form = PIPActionForm(instance=action, tenant=request.tenant)
    return render(request, 'supplier_performance/pip_action_form.html',
                  {'form': form, 'plan': plan, 'action': action, 'is_edit': True})


@login_required
@vendor_blocked
@require_POST
def pip_action_delete(request, pk, apk):
    denied = _require_manage(request)
    if denied:
        return denied
    plan = get_object_or_404(ImprovementPlan, pk=pk, tenant=request.tenant)
    action = get_object_or_404(PIPAction, pk=apk, improvement_plan=plan, tenant=request.tenant)
    action.delete()
    messages.success(request, 'Action removed.')
    return redirect('supplier_performance:pip_detail', pk=plan.pk)


# ---------------------------------------------------------------------------
# Trending & Benchmarking
# ---------------------------------------------------------------------------
@login_required
@vendor_blocked
def trending(request):
    denied = _require_view(request)
    if denied:
        return denied
    vendors = Vendor.objects.filter(
        tenant=request.tenant, scorecards__status='final').distinct().order_by('legal_name')
    vendor_id = request.GET.get('vendor', '')
    vendor = None
    trend = None
    if vendor_id:
        vendor = Vendor.objects.filter(pk=vendor_id, tenant=request.tenant).first()
    if vendor is None:
        vendor = vendors.first()
    if vendor is not None:
        trend = services.vendor_trend(vendor)
    return render(request, 'supplier_performance/trending.html', {
        'vendors': vendors, 'vendor': vendor, 'trend': trend,
    })


@login_required
@vendor_blocked
def benchmarking(request):
    denied = _require_view(request)
    if denied:
        return denied
    kpi_code = request.GET.get('kpi', '')
    data = services.tenant_benchmark(request.tenant, kpi_code=kpi_code or None)
    return render(request, 'supplier_performance/benchmarking.html', {
        'data': data, 'kpi_code': kpi_code,
        'kpis': KpiDefinition.objects.filter(tenant=request.tenant, is_active=True),
    })


@login_required
@vendor_blocked
def export_benchmark(request, fmt):
    denied = _require_view(request)
    if denied:
        return denied
    if fmt not in VALID_FORMATS:
        raise Http404()
    kpi_code = request.GET.get('kpi', '') or None
    header, rows = services.benchmark_rows_for_export(request.tenant, kpi_code=kpi_code)
    services.record_audit(
        request.tenant, request.user, 'supplier_performance.exported',
        target_type='Scorecard', message=f'Benchmark export ({fmt}).', request=request)
    return _deliver(fmt, f'supplier-benchmark.{fmt}', header, rows, sheet_title='Benchmark')


@login_required
@vendor_blocked
def vendor_scorecards(request, vendor_pk):
    denied = _require_view(request)
    if denied:
        return denied
    vendor = get_object_or_404(Vendor, pk=vendor_pk, tenant=request.tenant)
    trend = services.vendor_trend(vendor)
    return render(request, 'supplier_performance/vendor_scorecards.html', {
        'vendor': vendor, 'trend': trend,
        'scorecards': Scorecard.objects.filter(tenant=request.tenant, vendor=vendor)
        .order_by('-period_end'),
        'can_manage': services.can_manage_supplier_performance(request.user),
    })
