"""Module 15 views: Spend Analytics & Reporting (internal side).

Function-based views mirroring the goods_receipt module: ``@login_required`` + a
``_require_view`` / ``_require_manage`` permission gate, tenant-scoped lookups, list search +
filters + ``Paginator(qs, 20)``.

SECURITY (lessons.md 2026-05-29 D-01/D-02): EVERY read view — dashboard, category, maverick,
report list/detail — AND all three export endpoints call ``_require_view`` first. A prior module
leaked competitor data by shipping analytics gated only on the tenant. ``_get_report`` additionally
enforces private-report isolation (owner-or-manager) and returns 404 across tenants.
"""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.vendors.models import Vendor, VendorCategory

from . import services
from .exports import csv_response, xlsx_response
from .forms import SpendReportForm
from .models import BASIS_CHOICES, MAVERICK_REASON_CHOICES, SpendRecord, SpendReport

VALID_BASES = {b for b, _ in BASIS_CHOICES}
VALID_REASONS = {r for r, _ in MAVERICK_REASON_CHOICES}
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
    if not services.can_view_spend_analytics(request.user):
        messages.error(request, 'You do not have permission to view spend analytics.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_manage(request):
    if not services.can_manage_spend_analytics(request.user):
        messages.error(request, 'You do not have permission to manage spend analytics.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _get_basis(request):
    basis = request.GET.get('basis', 'actual')
    return basis if basis in VALID_BASES else 'actual'


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _date_window(request):
    return _parse_date(request.GET.get('start')), _parse_date(request.GET.get('end'))


def _get_report(request, pk):
    """Fetch a tenant-scoped report; 404 a private report unless owner or manager."""
    report = get_object_or_404(SpendReport, pk=pk, tenant=request.tenant)
    if (not report.is_shared and report.owner_id != request.user.id
            and not services.can_manage_spend_analytics(request.user)):
        raise Http404('Report not found.')
    return report


def _base_querystring(request, *drop):
    qs = request.GET.copy()
    for key in ('page',) + drop:
        qs.pop(key, None)
    return qs.urlencode()


# ---------------------------------------------------------------------------
# 1. Spend Dashboards
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied

    # Lazy resync (managers only) so the dashboard reflects recent invoices / POs.
    if services.can_manage_spend_analytics(request.user):
        services.lazy_sync(request.tenant)

    basis = _get_basis(request)
    start, end = _date_window(request)
    metrics = services.tenant_spend_metrics(request.tenant, basis=basis, start=start, end=end)
    return render(request, 'spend_analytics/dashboard.html', {
        'metrics': metrics,
        'basis': basis,
        'basis_choices': BASIS_CHOICES,
        'start': request.GET.get('start', ''),
        'end': request.GET.get('end', ''),
        'base_querystring': _base_querystring(request, 'basis'),
        'can_manage': services.can_manage_spend_analytics(request.user),
    })


# ---------------------------------------------------------------------------
# 3. Category Spend Analysis
# ---------------------------------------------------------------------------
@login_required
def category_analysis(request):
    denied = _require_view(request)
    if denied:
        return denied

    basis = _get_basis(request)
    start, end = _date_window(request)
    data = services.category_spend(request.tenant, basis=basis, start=start, end=end)
    return render(request, 'spend_analytics/category_analysis.html', {
        'data': data,
        'basis': basis,
        'basis_choices': BASIS_CHOICES,
        'start': request.GET.get('start', ''),
        'end': request.GET.get('end', ''),
        'base_querystring': _base_querystring(request, 'basis'),
    })


@login_required
def category_detail(request, category_id):
    denied = _require_view(request)
    if denied:
        return denied

    basis = _get_basis(request)
    start, end = _date_window(request)
    category = None
    if category_id:  # 0 == the "Uncategorized" bucket
        category = get_object_or_404(VendorCategory, pk=category_id, tenant=request.tenant)
    data = services.category_detail(
        request.tenant, category_id, basis=basis, start=start, end=end)

    paginator = Paginator(data['records'], 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'spend_analytics/category_detail.html', {
        'category': category,
        'data': data,
        'basis': basis,
        'page_obj': page_obj,
        'records': page_obj.object_list,
        'querystring': _base_querystring(request),
        'start': request.GET.get('start', ''),
        'end': request.GET.get('end', ''),
    })


# ---------------------------------------------------------------------------
# 4. Maverick Spend Tracking
# ---------------------------------------------------------------------------
@login_required
def maverick_tracking(request):
    denied = _require_view(request)
    if denied:
        return denied

    basis = _get_basis(request)
    start, end = _date_window(request)
    metrics = services.maverick_metrics(request.tenant, basis=basis, start=start, end=end)

    records = SpendRecord.objects.filter(
        tenant=request.tenant, basis=basis, is_maverick=True,
    ).select_related('vendor', 'vendor_category', 'account_code')
    if start:
        records = records.filter(spend_date__gte=start)
    if end:
        records = records.filter(spend_date__lte=end)

    reason = request.GET.get('reason', '')
    if reason in VALID_REASONS:
        records = records.filter(**{reason: True})
    vendor = request.GET.get('vendor', '')
    if vendor:
        records = records.filter(vendor_id=vendor)
    category = request.GET.get('category', '')
    if category:
        records = records.filter(vendor_category_id=category)
    q = request.GET.get('q', '').strip()
    if q:
        records = records.filter(
            Q(source_ref__icontains=q) | Q(vendor_name__icontains=q)
            | Q(description__icontains=q)
        )

    paginator = Paginator(records, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'spend_analytics/maverick_tracking.html', {
        'metrics': metrics,
        'basis': basis,
        'basis_choices': BASIS_CHOICES,
        'reason_choices': MAVERICK_REASON_CHOICES,
        'vendors': Vendor.objects.filter(tenant=request.tenant).order_by('legal_name'),
        'categories': VendorCategory.objects.filter(tenant=request.tenant).order_by('name'),
        'page_obj': page_obj,
        'records': page_obj.object_list,
        'q': q,
        'querystring': _base_querystring(request),
        'start': request.GET.get('start', ''),
        'end': request.GET.get('end', ''),
    })


# ---------------------------------------------------------------------------
# 2. Custom Report Builder (full CRUD + run)
# ---------------------------------------------------------------------------
@login_required
def report_list(request):
    denied = _require_view(request)
    if denied:
        return denied

    qs = SpendReport.objects.filter(tenant=request.tenant).select_related('owner')
    if not services.can_manage_spend_analytics(request.user):
        qs = qs.filter(Q(is_shared=True) | Q(owner=request.user))
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'spend_analytics/report_list.html', {
        'page_obj': page_obj,
        'reports': page_obj.object_list,
        'q': q,
        'querystring': _base_querystring(request),
        'can_manage': services.can_manage_spend_analytics(request.user),
    })


@login_required
def report_create(request):
    denied = _require_manage(request)
    if denied:
        return denied

    if request.method == 'POST':
        form = SpendReportForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            report = form.save(commit=False)
            report.tenant = request.tenant
            report.owner = request.user
            report.save()
            services.record_audit(
                request.tenant, request.user, 'spend_analytics.report_created',
                target_type='SpendReport', target_id=str(report.pk),
                message=f'Report "{report.name}" created.', request=request,
            )
            messages.success(request, f'Report "{report.name}" created.')
            return redirect('spend_analytics:report_detail', pk=report.pk)
    else:
        form = SpendReportForm(tenant=request.tenant)

    return render(request, 'spend_analytics/report_form.html', {
        'form': form, 'is_edit': False,
    })


@login_required
def report_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied

    report = _get_report(request, pk)
    result = services.run_spend_report(report)
    report.last_run_at = timezone.now()
    report.save(update_fields=['last_run_at', 'updated_at'])
    services.record_audit(
        request.tenant, request.user, 'spend_analytics.report_run',
        target_type='SpendReport', target_id=str(report.pk),
        message=f'Report "{report.name}" run.', request=request,
    )
    return render(request, 'spend_analytics/report_detail.html', {
        'report': report,
        'result': result,
        'can_manage': services.can_manage_spend_analytics(request.user),
    })


@login_required
def report_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    report = _get_report(request, pk)
    if request.method == 'POST':
        form = SpendReportForm(request.POST, instance=report, tenant=request.tenant)
        if form.is_valid():
            form.save()
            services.record_audit(
                request.tenant, request.user, 'spend_analytics.report_updated',
                target_type='SpendReport', target_id=str(report.pk),
                message=f'Report "{report.name}" updated.', request=request,
            )
            messages.success(request, 'Report updated.')
            return redirect('spend_analytics:report_detail', pk=report.pk)
    else:
        form = SpendReportForm(instance=report, tenant=request.tenant)

    return render(request, 'spend_analytics/report_form.html', {
        'form': form, 'report': report, 'is_edit': True,
    })


@login_required
@require_POST
def report_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied

    report = _get_report(request, pk)
    name = report.name
    services.record_audit(
        request.tenant, request.user, 'spend_analytics.report_deleted', level='warning',
        target_type='SpendReport', target_id=str(report.pk),
        message=f'Report "{name}" deleted.', request=request,
    )
    report.delete()
    messages.success(request, f'Report "{name}" deleted.')
    return redirect('spend_analytics:report_list')


# ---------------------------------------------------------------------------
# Manual fact-table refresh
# ---------------------------------------------------------------------------
@login_required
@require_POST
def sync_now(request):
    denied = _require_manage(request)
    if denied:
        return denied

    counts = services.sync_spend_facts(request.tenant)  # records its own audit entry
    messages.success(
        request,
        f"Spend data refreshed: +{counts['created']} new, ~{counts['updated']} updated, "
        f"-{counts['pruned']} removed ({counts['total']} records).")
    return redirect('spend_analytics:dashboard')


# ---------------------------------------------------------------------------
# 5. Data Export (CSV / XLSX — the BI feed). Every endpoint is _require_view gated.
# ---------------------------------------------------------------------------
def _deliver(fmt, filename, header, rows, *, sheet_title='Spend'):
    if fmt == 'csv':
        return csv_response(filename, header, rows)
    return xlsx_response(filename, header, rows, sheet_title=sheet_title)


@login_required
def export_dashboard(request, fmt):
    denied = _require_view(request)
    if denied:
        return denied
    if fmt not in VALID_FORMATS:
        raise Http404()

    basis = _get_basis(request)
    start, end = _date_window(request)
    header, rows = services.spend_rows_for_export(
        request.tenant, basis=basis, start=start, end=end)
    services.record_audit(
        request.tenant, request.user, 'spend_analytics.exported',
        target_type='SpendRecord', message=f'Dashboard export ({basis}, {fmt}).',
        request=request,
    )
    return _deliver(fmt, f'spend-dashboard-{basis}.{fmt}', header, rows)


@login_required
def export_records(request, fmt):
    denied = _require_view(request)
    if denied:
        return denied
    if fmt not in VALID_FORMATS:
        raise Http404()

    basis = _get_basis(request)
    start, end = _date_window(request)
    maverick_only = request.GET.get('maverick') in ('1', 'true', 'on', 'yes')
    dim = {}
    if request.GET.get('vendor'):
        dim['vendor_id'] = request.GET['vendor']
    if request.GET.get('category'):
        dim['vendor_category_id'] = request.GET['category']
    reason = request.GET.get('reason', '')
    if reason in VALID_REASONS:
        dim[reason] = True
        maverick_only = True
    header, rows = services.spend_rows_for_export(
        request.tenant, basis=basis, start=start, end=end,
        maverick_only=maverick_only, **dim)
    services.record_audit(
        request.tenant, request.user, 'spend_analytics.exported',
        target_type='SpendRecord', message=f'Records export ({basis}, {fmt}).',
        request=request,
    )
    return _deliver(fmt, f'spend-records-{basis}.{fmt}', header, rows)


@login_required
def export_report(request, pk, fmt):
    denied = _require_view(request)
    if denied:
        return denied
    if fmt not in VALID_FORMATS:
        raise Http404()

    report = _get_report(request, pk)
    result = services.run_spend_report(report)
    header = [result['dimension_label'], result['measure_label']]
    rows = [[r['label'], r['value']] for r in result['rows']]
    services.record_audit(
        request.tenant, request.user, 'spend_analytics.exported',
        target_type='SpendReport', target_id=str(report.pk),
        message=f'Report "{report.name}" export ({fmt}).', request=request,
    )
    return _deliver(fmt, f'report-{report.pk}.{fmt}', header, rows, sheet_title='Report')
