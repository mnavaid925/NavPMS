"""Module 16 views: Budget & Cost Management (internal side).

Function-based views mirroring spend_analytics: ``@login_required`` + a ``_require_view`` /
``_require_manage`` permission gate, tenant-scoped lookups, list search + filters +
``Paginator(qs, 20)``.

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
from django.views.decorators.http import require_POST

# Reuse the project's shared CSV/XLSX helpers (do not duplicate — Module 15 owns them).
from apps.spend_analytics.exports import csv_response, xlsx_response

from . import services
from .forms import BudgetAllocationForm, BudgetForm, BudgetPeriodForm
from .models import (
    BUDGET_STATUS_CHOICES, PERIOD_STATUS_CHOICES, Budget, BudgetAllocation, BudgetCheck,
    BudgetPeriod, CHECK_RESULT_CHOICES,
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
    if not services.can_view_budget(request.user):
        messages.error(request, 'You do not have permission to view budgets.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_manage(request):
    if not services.can_manage_budget(request.user):
        messages.error(request, 'You do not have permission to manage budgets.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _querystring(request, *drop):
    qs = request.GET.copy()
    for key in ('page',) + drop:
        qs.pop(key, None)
    return qs.urlencode()


def _selected_period(request):
    """Resolve the ``?period=`` filter to a tenant period (or None = all active budgets)."""
    pid = request.GET.get('period', '')
    if pid:
        return BudgetPeriod.objects.filter(pk=pid, tenant=request.tenant).first()
    return None


def _deliver(fmt, filename, header, rows, *, sheet_title='Budget'):
    if fmt == 'csv':
        return csv_response(filename, header, rows)
    return xlsx_response(filename, header, rows, sheet_title=sheet_title)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied

    period = _selected_period(request)
    metrics = services.tenant_budget_metrics(request.tenant, period=period)
    return render(request, 'budget/dashboard.html', {
        'metrics': metrics,
        'period': period,
        'periods': BudgetPeriod.objects.filter(tenant=request.tenant).order_by('-start_date'),
        'can_manage': services.can_manage_budget(request.user),
    })


# ---------------------------------------------------------------------------
# Budget Periods
# ---------------------------------------------------------------------------
@login_required
def period_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = BudgetPeriod.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(notes__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'budget/period_list.html', {
        'page_obj': page_obj, 'periods': page_obj.object_list, 'q': q,
        'status_choices': PERIOD_STATUS_CHOICES, 'querystring': _querystring(request),
        'can_manage': services.can_manage_budget(request.user),
    })


@login_required
def period_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    if request.method == 'POST':
        form = BudgetPeriodForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            period = form.save(commit=False)
            period.tenant = request.tenant
            period.save()
            services.record_audit(
                request.tenant, request.user, 'budget.period_created',
                target_type='BudgetPeriod', target_id=str(period.pk),
                message=f'Period "{period.name}" created.', request=request,
            )
            messages.success(request, f'Period "{period.name}" created.')
            return redirect('budget:period_detail', pk=period.pk)
    else:
        form = BudgetPeriodForm(tenant=request.tenant)
    return render(request, 'budget/period_form.html', {'form': form, 'is_edit': False})


@login_required
def period_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    period = get_object_or_404(BudgetPeriod, pk=pk, tenant=request.tenant)
    budgets = period.budgets.all().select_related('owner')
    return render(request, 'budget/period_detail.html', {
        'period': period, 'budgets': budgets,
        'can_manage': services.can_manage_budget(request.user),
        'status_choices': PERIOD_STATUS_CHOICES,
    })


@login_required
def period_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    period = get_object_or_404(BudgetPeriod, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = BudgetPeriodForm(request.POST, instance=period, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Period updated.')
            return redirect('budget:period_detail', pk=period.pk)
    else:
        form = BudgetPeriodForm(instance=period, tenant=request.tenant)
    return render(request, 'budget/period_form.html',
                  {'form': form, 'period': period, 'is_edit': True})


@login_required
@require_POST
def period_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    period = get_object_or_404(BudgetPeriod, pk=pk, tenant=request.tenant)
    if period.budgets.exists():
        messages.error(request, 'Cannot delete a period that still has budgets.')
        return redirect('budget:period_detail', pk=period.pk)
    name = period.name
    period.delete()
    messages.success(request, f'Period "{name}" deleted.')
    return redirect('budget:period_list')


@login_required
@require_POST
def period_set_status(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    period = get_object_or_404(BudgetPeriod, pk=pk, tenant=request.tenant)
    status = request.POST.get('status', '')
    try:
        services.set_period_status(period, status, request.user, request=request)
        messages.success(request, f'Period "{period.name}" is now {status}.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('budget:period_detail', pk=period.pk)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
@login_required
def budget_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = Budget.objects.filter(tenant=request.tenant).select_related('period', 'owner')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(budget_number__icontains=q) | Q(name__icontains=q)
                       | Q(description__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    period_id = request.GET.get('period', '')
    if period_id:
        qs = qs.filter(period_id=period_id)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'budget/budget_list.html', {
        'page_obj': page_obj, 'budgets': page_obj.object_list, 'q': q,
        'status_choices': BUDGET_STATUS_CHOICES,
        'periods': BudgetPeriod.objects.filter(tenant=request.tenant).order_by('-start_date'),
        'querystring': _querystring(request),
        'can_manage': services.can_manage_budget(request.user),
    })


@login_required
def budget_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    if request.method == 'POST':
        form = BudgetForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            budget = form.save(commit=False)
            budget.tenant = request.tenant
            budget.budget_number = services.next_budget_number(request.tenant)
            budget.created_by = request.user
            budget.save()
            services.record_status_event(budget, '', 'draft', request.user, note='Created')
            services.record_audit(
                request.tenant, request.user, 'budget.created',
                target_type='Budget', target_id=str(budget.pk),
                message=f'Budget {budget.budget_number} created.', request=request,
            )
            messages.success(request, f'Budget {budget.budget_number} created. Add allocations.')
            return redirect('budget:budget_detail', pk=budget.pk)
    else:
        form = BudgetForm(tenant=request.tenant)
    return render(request, 'budget/budget_form.html', {'form': form, 'is_edit': False})


@login_required
def budget_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    budget = get_object_or_404(
        Budget.objects.select_related('period', 'owner', 'created_by'),
        pk=pk, tenant=request.tenant)
    consumption = services.budget_consumption(budget)
    return render(request, 'budget/budget_detail.html', {
        'budget': budget,
        'consumption': consumption,
        'status_events': budget.status_events.select_related('actor'),
        'allocation_form': BudgetAllocationForm(tenant=request.tenant),
        'can_manage': services.can_manage_budget(request.user),
    })


@login_required
def budget_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    budget = get_object_or_404(Budget, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = BudgetForm(request.POST, instance=budget, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Budget updated.')
            return redirect('budget:budget_detail', pk=budget.pk)
    else:
        form = BudgetForm(instance=budget, tenant=request.tenant)
    return render(request, 'budget/budget_form.html',
                  {'form': form, 'budget': budget, 'is_edit': True})


@login_required
@require_POST
def budget_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    budget = get_object_or_404(Budget, pk=pk, tenant=request.tenant)
    number = budget.budget_number
    services.record_audit(
        request.tenant, request.user, 'budget.deleted', level='warning',
        target_type='Budget', target_id=str(budget.pk),
        message=f'Budget {number} deleted.', request=request,
    )
    budget.delete()
    messages.success(request, f'Budget {number} deleted.')
    return redirect('budget:budget_list')


@login_required
@require_POST
def budget_activate(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    budget = get_object_or_404(Budget, pk=pk, tenant=request.tenant)
    try:
        services.activate_budget(budget, request.user, request=request)
        messages.success(request, f'Budget {budget.budget_number} activated.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('budget:budget_detail', pk=budget.pk)


@login_required
@require_POST
def budget_close(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    budget = get_object_or_404(Budget, pk=pk, tenant=request.tenant)
    try:
        services.close_budget(budget, request.user, note=request.POST.get('note', ''),
                              request=request)
        messages.success(request, f'Budget {budget.budget_number} closed.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('budget:budget_detail', pk=budget.pk)


@login_required
def budget_forecast(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    budget = get_object_or_404(Budget.objects.select_related('period'), pk=pk,
                               tenant=request.tenant)
    data = services.forecast(budget)
    return render(request, 'budget/forecast.html', {'budget': budget, 'data': data})


# ---------------------------------------------------------------------------
# Allocation lines
# ---------------------------------------------------------------------------
def _editable_budget_or_redirect(request, pk):
    budget = get_object_or_404(Budget, pk=pk, tenant=request.tenant)
    if not budget.is_editable:
        messages.error(request, 'Allocations can only be changed while the budget is a draft.')
        return budget, redirect('budget:budget_detail', pk=budget.pk)
    return budget, None


@login_required
def allocation_create(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    budget, bail = _editable_budget_or_redirect(request, pk)
    if bail:
        return bail

    if request.method == 'POST':
        form = BudgetAllocationForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            alloc = form.save(commit=False)
            alloc.tenant = request.tenant
            alloc.budget = budget
            if not alloc.line_no:
                alloc.line_no = budget.allocations.count() + 1
            # Explicit duplicate guard: the (budget, account_code, vendor_category) unique constraint
            # does not catch two NULL-category rows (NULL != NULL in SQL), so check here.
            dup = BudgetAllocation.all_objects.filter(
                budget=budget, account_code=alloc.account_code,
                vendor_category=alloc.vendor_category).exists()
            if dup:
                messages.error(request, 'That cost centre is already allocated on this budget.')
                return redirect('budget:budget_detail', pk=budget.pk)
            alloc.save()
            services.recompute_total(budget)
            messages.success(request, 'Allocation added.')
            return redirect('budget:budget_detail', pk=budget.pk)
    else:
        form = BudgetAllocationForm(tenant=request.tenant)
    return render(request, 'budget/allocation_form.html',
                  {'form': form, 'budget': budget, 'is_edit': False})


@login_required
def allocation_edit(request, pk, apk):
    denied = _require_manage(request)
    if denied:
        return denied
    budget, bail = _editable_budget_or_redirect(request, pk)
    if bail:
        return bail

    alloc = get_object_or_404(BudgetAllocation, pk=apk, budget=budget, tenant=request.tenant)
    if request.method == 'POST':
        form = BudgetAllocationForm(request.POST, instance=alloc, tenant=request.tenant)
        if form.is_valid():
            form.save()
            services.recompute_total(budget)
            messages.success(request, 'Allocation updated.')
            return redirect('budget:budget_detail', pk=budget.pk)
    else:
        form = BudgetAllocationForm(instance=alloc, tenant=request.tenant)
    return render(request, 'budget/allocation_form.html',
                  {'form': form, 'budget': budget, 'allocation': alloc, 'is_edit': True})


@login_required
@require_POST
def allocation_delete(request, pk, apk):
    denied = _require_manage(request)
    if denied:
        return denied
    budget, bail = _editable_budget_or_redirect(request, pk)
    if bail:
        return bail

    alloc = get_object_or_404(BudgetAllocation, pk=apk, budget=budget, tenant=request.tenant)
    alloc.delete()
    services.recompute_total(budget)
    messages.success(request, 'Allocation removed.')
    return redirect('budget:budget_detail', pk=budget.pk)


# ---------------------------------------------------------------------------
# Variance Analysis
# ---------------------------------------------------------------------------
@login_required
def variance(request):
    denied = _require_view(request)
    if denied:
        return denied

    period = _selected_period(request)
    report = services.variance_report(request.tenant, period=period)
    return render(request, 'budget/variance_report.html', {
        'report': report, 'period': period,
        'periods': BudgetPeriod.objects.filter(tenant=request.tenant).order_by('-start_date'),
    })


# ---------------------------------------------------------------------------
# Availability-check audit log
# ---------------------------------------------------------------------------
@login_required
def check_log(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = BudgetCheck.objects.filter(tenant=request.tenant).select_related(
        'requisition', 'budget', 'account_code', 'checked_by')
    result = request.GET.get('result', '')
    if result:
        qs = qs.filter(result=result)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(requisition__number__icontains=q) | Q(message__icontains=q))

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'budget/check_log.html', {
        'page_obj': page_obj, 'checks': page_obj.object_list, 'q': q,
        'result': result, 'result_choices': CHECK_RESULT_CHOICES,
        'querystring': _querystring(request),
    })


# ---------------------------------------------------------------------------
# Exports (every endpoint _require_view gated — D-01/D-02)
# ---------------------------------------------------------------------------
@login_required
def export_variance(request, fmt):
    denied = _require_view(request)
    if denied:
        return denied
    if fmt not in VALID_FORMATS:
        raise Http404()
    period = _selected_period(request)
    header, rows = services.variance_rows_for_export(request.tenant, period=period)
    services.record_audit(
        request.tenant, request.user, 'budget.exported',
        target_type='Budget', message=f'Variance export ({fmt}).', request=request,
    )
    return _deliver(fmt, f'budget-variance.{fmt}', header, rows, sheet_title='Variance')


@login_required
def export_budget(request, pk, fmt):
    denied = _require_view(request)
    if denied:
        return denied
    if fmt not in VALID_FORMATS:
        raise Http404()
    budget = get_object_or_404(Budget, pk=pk, tenant=request.tenant)
    header, rows = services.budget_rows_for_export(budget)
    services.record_audit(
        request.tenant, request.user, 'budget.exported',
        target_type='Budget', target_id=str(budget.pk),
        message=f'Budget {budget.budget_number} export ({fmt}).', request=request,
    )
    return _deliver(fmt, f'budget-{budget.budget_number}.{fmt}', header, rows)
