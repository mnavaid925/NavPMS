"""Module 18 views: Risk & Compliance Management.

Function-based views mirroring budget/spend_analytics: ``@login_required`` + a ``_require_view`` /
``_require_manage`` permission gate, tenant-scoped lookups, list search + filters + ``Paginator``.

SECURITY (lessons.md D-01/D-02): EVERY read view AND the audit export call ``_require_view`` first;
mutations call ``_require_manage``. The audit explorer additionally reads the tamper-evident
AuditLog and exposes a chain-integrity verify action.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.spend_analytics.exports import csv_response
from apps.tenants.models import AuditLog
from apps.tenants.services import verify_audit_chain
from apps.vendors.models import Vendor

from . import services
from .forms import (
    FinancialMonitorForm, FraudRuleForm, PolicyForm, PolicyVersionForm,
    RestrictedPartyEntryForm, ScreeningRunForm,
)
from .models import (
    ComplianceScreening, FRAUD_RULE_CHOICES, FRAUD_STATUS_CHOICES, FinancialRiskProfile,
    FraudAlert, FraudRule, POLICY_CATEGORY_CHOICES, POLICY_STATUS_CHOICES, Policy,
    RISK_BAND_CHOICES, RP_ENTRY_TYPE_CHOICES, RestrictedPartyEntry,
    SCREENING_STATUS_CHOICES, SEVERITY_CHOICES,
)


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
    if not services.can_view_compliance(request.user):
        messages.error(request, 'You do not have permission to view compliance.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_manage(request):
    if not services.can_manage_compliance(request.user):
        messages.error(request, 'You do not have permission to manage compliance.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _querystring(request, *drop):
    qs = request.GET.copy()
    for key in ('page',) + drop:
        qs.pop(key, None)
    return qs.urlencode()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    denied = _require_view(request)
    if denied:
        return denied
    metrics = services.tenant_compliance_metrics(request.tenant)
    return render(request, 'compliance/dashboard.html', {
        'metrics': metrics,
        'can_manage': services.can_manage_compliance(request.user),
    })


# ---------------------------------------------------------------------------
# 1. Restricted-party screening
# ---------------------------------------------------------------------------
@login_required
def screening_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = ComplianceScreening.objects.filter(tenant=request.tenant).select_related('vendor')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(screening_number__icontains=q) | Q(screened_name__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'compliance/screening_list.html', {
        'page_obj': page_obj, 'screenings': page_obj.object_list, 'q': q,
        'status': status, 'status_choices': SCREENING_STATUS_CHOICES,
        'querystring': _querystring(request),
        'can_manage': services.can_manage_compliance(request.user),
    })


@login_required
def screening_run(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = ScreeningRunForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            try:
                screening = services.run_screening(
                    request.tenant, vendor=form.cleaned_data.get('vendor'),
                    name=form.cleaned_data.get('screened_name'), user=request.user,
                    request=request)
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
            else:
                messages.success(
                    request, f'Screening {screening.screening_number} complete — '
                    f'{screening.match_count} match(es).')
                return redirect('compliance:screening_detail', pk=screening.pk)
    else:
        form = ScreeningRunForm(tenant=request.tenant)
    return render(request, 'compliance/screening_run.html', {'form': form})


@login_required
def screening_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    screening = get_object_or_404(
        ComplianceScreening.objects.select_related('vendor', 'screened_by'),
        pk=pk, tenant=request.tenant)
    return render(request, 'compliance/screening_detail.html', {
        'screening': screening,
        'matches': screening.matches.select_related('entry', 'dispositioned_by'),
        'can_manage': services.can_manage_compliance(request.user),
    })


@login_required
@require_POST
def screening_disposition(request, pk, mpk):
    denied = _require_manage(request)
    if denied:
        return denied
    screening = get_object_or_404(ComplianceScreening, pk=pk, tenant=request.tenant)
    match = get_object_or_404(screening.matches, pk=mpk)
    try:
        services.disposition_match(
            match, request.POST.get('decision', ''), request.user,
            note=request.POST.get('note', ''), request=request)
        messages.success(request, 'Match disposition saved.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('compliance:screening_detail', pk=screening.pk)


# ---------------------------------------------------------------------------
# Restricted-party list (reference data)
# ---------------------------------------------------------------------------
@login_required
def rpe_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = RestrictedPartyEntry.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(entity_name__icontains=q) | Q(list_name__icontains=q)
                       | Q(country__icontains=q))
    entry_type = request.GET.get('entry_type', '')
    if entry_type:
        qs = qs.filter(entry_type=entry_type)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'compliance/rpe_list.html', {
        'page_obj': page_obj, 'entries': page_obj.object_list, 'q': q,
        'entry_type': entry_type, 'entry_type_choices': RP_ENTRY_TYPE_CHOICES,
        'querystring': _querystring(request),
        'can_manage': services.can_manage_compliance(request.user),
    })


@login_required
def rpe_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = RestrictedPartyEntryForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.tenant = request.tenant
            entry.save()
            messages.success(request, 'Restricted-party entry added.')
            return redirect('compliance:rpe_list')
    else:
        form = RestrictedPartyEntryForm(tenant=request.tenant)
    return render(request, 'compliance/rpe_form.html', {'form': form, 'is_edit': False})


@login_required
def rpe_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    entry = get_object_or_404(RestrictedPartyEntry, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = RestrictedPartyEntryForm(request.POST, instance=entry, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Entry updated.')
            return redirect('compliance:rpe_list')
    else:
        form = RestrictedPartyEntryForm(instance=entry, tenant=request.tenant)
    return render(request, 'compliance/rpe_form.html',
                  {'form': form, 'entry': entry, 'is_edit': True})


@login_required
@require_POST
def rpe_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    entry = get_object_or_404(RestrictedPartyEntry, pk=pk, tenant=request.tenant)
    entry.delete()
    messages.success(request, 'Entry deleted.')
    return redirect('compliance:rpe_list')


# ---------------------------------------------------------------------------
# 2. Financial-risk monitoring
# ---------------------------------------------------------------------------
@login_required
def financial_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = FinancialRiskProfile.objects.filter(tenant=request.tenant).select_related('vendor')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(vendor__legal_name__icontains=q)
    band = request.GET.get('band', '')
    if band:
        qs = qs.filter(band=band)
    monitored = request.GET.get('monitored', '')
    if monitored == 'yes':
        qs = qs.filter(monitored=True)
    elif monitored == 'no':
        qs = qs.filter(monitored=False)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'compliance/financial_list.html', {
        'page_obj': page_obj, 'profiles': page_obj.object_list, 'q': q,
        'band': band, 'monitored': monitored, 'band_choices': RISK_BAND_CHOICES,
        'monitor_form': FinancialMonitorForm(tenant=request.tenant),
        'querystring': _querystring(request),
        'can_manage': services.can_manage_compliance(request.user),
    })


@login_required
def financial_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    profile = get_object_or_404(
        FinancialRiskProfile.objects.select_related('vendor'), pk=pk, tenant=request.tenant)
    snapshots = list(profile.snapshots.order_by('as_of_date')[:60])
    return render(request, 'compliance/financial_detail.html', {
        'profile': profile,
        'snapshots': list(reversed(snapshots)),
        'trend_labels': [s.as_of_date.isoformat() for s in snapshots],
        'trend_scores': [float(s.credit_score) for s in snapshots],
        'can_manage': services.can_manage_compliance(request.user),
    })


@login_required
@require_POST
def financial_monitor(request):
    denied = _require_manage(request)
    if denied:
        return denied
    form = FinancialMonitorForm(request.POST, tenant=request.tenant)
    if form.is_valid():
        profile = services.refresh_financial_risk(
            request.tenant, form.cleaned_data['vendor'], user=request.user, request=request)
        messages.success(request, f'{profile.vendor.legal_name} added to monitoring.')
        return redirect('compliance:financial_detail', pk=profile.pk)
    messages.error(request, 'Select a vendor to monitor.')
    return redirect('compliance:financial_list')


@login_required
@require_POST
def financial_refresh(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    profile = get_object_or_404(FinancialRiskProfile, pk=pk, tenant=request.tenant)
    services.refresh_financial_risk(request.tenant, profile.vendor, user=request.user,
                                    request=request)
    messages.success(request, 'Financial risk refreshed.')
    return redirect('compliance:financial_detail', pk=profile.pk)


@login_required
@require_POST
def financial_toggle(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    profile = get_object_or_404(FinancialRiskProfile, pk=pk, tenant=request.tenant)
    profile.monitored = not profile.monitored
    profile.save(update_fields=['monitored', 'updated_at'])
    messages.success(request, f'Monitoring {"enabled" if profile.monitored else "paused"}.')
    return redirect('compliance:financial_detail', pk=profile.pk)


# ---------------------------------------------------------------------------
# 3. Audit trail explorer (tamper-evident)
# ---------------------------------------------------------------------------
def _audit_queryset(request):
    qs = AuditLog.objects.filter(tenant=request.tenant).select_related('user')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(action__icontains=q) | Q(message__icontains=q)
                       | Q(target_id__icontains=q) | Q(user__username__icontains=q))
    level = request.GET.get('level', '')
    if level:
        qs = qs.filter(level=level)
    action = request.GET.get('action', '').strip()
    if action:
        qs = qs.filter(action__icontains=action)
    date_from = request.GET.get('date_from', '')
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    date_to = request.GET.get('date_to', '')
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs


@login_required
def audit_log(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = _audit_queryset(request)
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'compliance/audit_log.html', {
        'page_obj': page_obj, 'entries': page_obj.object_list,
        'q': request.GET.get('q', ''), 'level': request.GET.get('level', ''),
        'action': request.GET.get('action', ''),
        'date_from': request.GET.get('date_from', ''), 'date_to': request.GET.get('date_to', ''),
        'level_choices': AuditLog.LEVEL_CHOICES,
        'querystring': _querystring(request),
    })


@login_required
def audit_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    entry = get_object_or_404(
        AuditLog.objects.select_related('user'), pk=pk, tenant=request.tenant)
    return render(request, 'compliance/audit_detail.html', {'entry': entry})


@login_required
def audit_verify(request):
    denied = _require_view(request)
    if denied:
        return denied
    result = verify_audit_chain(request.tenant)
    broken_entry = None
    if not result['ok'] and result['first_broken_id']:
        broken_entry = AuditLog.objects.filter(
            pk=result['first_broken_id'], tenant=request.tenant).first()
    return render(request, 'compliance/audit_verify.html',
                  {'result': result, 'broken_entry': broken_entry})


@login_required
def audit_export(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = _audit_queryset(request).order_by('created_at', 'id')
    header = ['Timestamp', 'User', 'Action', 'Level', 'Target', 'Message', 'IP', 'Row hash']
    rows = [
        [e.created_at.isoformat(), e.user.username if e.user else 'system', e.action, e.level,
         f'{e.target_type}#{e.target_id}' if e.target_type else '', e.message,
         e.ip_address or '', e.row_hash]
        for e in qs[:5000]
    ]
    return csv_response('compliance-audit-trail.csv', header, rows)


# ---------------------------------------------------------------------------
# 4. Fraud rules
# ---------------------------------------------------------------------------
@login_required
def fraud_rule_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    rules = FraudRule.objects.filter(tenant=request.tenant)
    return render(request, 'compliance/fraud_rule_list.html', {
        'rules': rules,
        'can_manage': services.can_manage_compliance(request.user),
    })


@login_required
def fraud_rule_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = FraudRuleForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.tenant = request.tenant
            try:
                rule.save()
            except Exception:
                messages.error(request, 'That rule code already exists for this tenant.')
            else:
                messages.success(request, 'Fraud rule created.')
                return redirect('compliance:fraud_rule_list')
    else:
        form = FraudRuleForm(tenant=request.tenant)
    return render(request, 'compliance/fraud_rule_form.html', {'form': form, 'is_edit': False})


@login_required
def fraud_rule_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    rule = get_object_or_404(FraudRule, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = FraudRuleForm(request.POST, instance=rule, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fraud rule updated.')
            return redirect('compliance:fraud_rule_list')
    else:
        form = FraudRuleForm(instance=rule, tenant=request.tenant)
    return render(request, 'compliance/fraud_rule_form.html',
                  {'form': form, 'rule': rule, 'is_edit': True})


@login_required
@require_POST
def fraud_rule_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    rule = get_object_or_404(FraudRule, pk=pk, tenant=request.tenant)
    rule.delete()
    messages.success(request, 'Fraud rule deleted.')
    return redirect('compliance:fraud_rule_list')


@login_required
@require_POST
def fraud_scan(request):
    denied = _require_manage(request)
    if denied:
        return denied
    created = services.scan_fraud(request.tenant, actor=request.user)
    messages.success(request, f'Fraud scan complete — {created} new alert(s).')
    return redirect('compliance:fraud_alert_list')


# ---------------------------------------------------------------------------
# 4. Fraud alerts
# ---------------------------------------------------------------------------
@login_required
def fraud_alert_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = FraudAlert.objects.filter(tenant=request.tenant).select_related('vendor', 'rule')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(alert_number__icontains=q) | Q(summary__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    severity = request.GET.get('severity', '')
    if severity:
        qs = qs.filter(severity=severity)
    rule_code = request.GET.get('rule', '')
    if rule_code:
        qs = qs.filter(rule_code=rule_code)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'compliance/fraud_alert_list.html', {
        'page_obj': page_obj, 'alerts': page_obj.object_list, 'q': q,
        'status': status, 'severity': severity, 'rule_code': rule_code,
        'status_choices': FRAUD_STATUS_CHOICES, 'severity_choices': SEVERITY_CHOICES,
        'rule_choices': FRAUD_RULE_CHOICES, 'querystring': _querystring(request),
        'can_manage': services.can_manage_compliance(request.user),
    })


@login_required
def fraud_alert_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    alert = get_object_or_404(
        FraudAlert.objects.select_related('vendor', 'rule', 'assigned_to', 'resolved_by'),
        pk=pk, tenant=request.tenant)
    return render(request, 'compliance/fraud_alert_detail.html', {
        'alert': alert,
        'events': alert.events.select_related('actor'),
        'status_choices': FRAUD_STATUS_CHOICES,
        'assignees': User.objects.filter(tenant=request.tenant, is_active=True).order_by('username'),
        'can_manage': services.can_manage_compliance(request.user),
    })


@login_required
@require_POST
def fraud_alert_status(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    alert = get_object_or_404(FraudAlert, pk=pk, tenant=request.tenant)
    try:
        services.set_fraud_status(alert, request.POST.get('status', ''), request.user,
                                  note=request.POST.get('note', ''), request=request)
        messages.success(request, f'Alert {alert.alert_number} updated.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('compliance:fraud_alert_detail', pk=alert.pk)


@login_required
@require_POST
def fraud_alert_assign(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    alert = get_object_or_404(FraudAlert, pk=pk, tenant=request.tenant)
    assignee = User.objects.filter(
        pk=request.POST.get('assigned_to'), tenant=request.tenant).first()
    if assignee:
        services.assign_fraud_alert(alert, assignee, request.user, request=request)
        messages.success(request, f'Alert assigned to {assignee.username}.')
    else:
        messages.error(request, 'Select a valid assignee.')
    return redirect('compliance:fraud_alert_detail', pk=alert.pk)


# ---------------------------------------------------------------------------
# 5. Policies
# ---------------------------------------------------------------------------
@login_required
def policy_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = Policy.objects.filter(tenant=request.tenant).select_related('owner', 'current_version')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(policy_number__icontains=q) | Q(title__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    category = request.GET.get('category', '')
    if category:
        qs = qs.filter(category=category)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'compliance/policy_list.html', {
        'page_obj': page_obj, 'policies': page_obj.object_list, 'q': q,
        'status': status, 'category': category, 'status_choices': POLICY_STATUS_CHOICES,
        'category_choices': POLICY_CATEGORY_CHOICES, 'querystring': _querystring(request),
        'can_manage': services.can_manage_compliance(request.user),
    })


@login_required
def policy_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = PolicyForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            policy = form.save(commit=False)
            policy.tenant = request.tenant
            policy.policy_number = services.next_policy_number(request.tenant)
            policy.created_by = request.user
            policy.save()
            services.record_audit(
                request.tenant, request.user, 'compliance.policy_created',
                target_type='Policy', target_id=str(policy.pk),
                message=f'Policy {policy.policy_number} created.', request=request)
            messages.success(request, f'Policy {policy.policy_number} created. Add a version.')
            return redirect('compliance:policy_detail', pk=policy.pk)
    else:
        form = PolicyForm(tenant=request.tenant)
    return render(request, 'compliance/policy_form.html', {'form': form, 'is_edit': False})


@login_required
def policy_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    policy = get_object_or_404(Policy, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = PolicyForm(request.POST, instance=policy, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Policy updated.')
            return redirect('compliance:policy_detail', pk=policy.pk)
    else:
        form = PolicyForm(instance=policy, tenant=request.tenant)
    return render(request, 'compliance/policy_form.html',
                  {'form': form, 'policy': policy, 'is_edit': True})


@login_required
@require_POST
def policy_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    policy = get_object_or_404(Policy, pk=pk, tenant=request.tenant)
    number = policy.policy_number
    policy.delete()
    messages.success(request, f'Policy {number} deleted.')
    return redirect('compliance:policy_list')


@login_required
def policy_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    policy = get_object_or_404(
        Policy.objects.select_related('owner', 'current_version'), pk=pk, tenant=request.tenant)
    return render(request, 'compliance/policy_detail.html', {
        'policy': policy,
        'versions': policy.versions.select_related('published_by'),
        'ack_stats': services.policy_ack_stats(policy),
        'can_manage': services.can_manage_compliance(request.user),
    })


@login_required
def policy_version_create(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    policy = get_object_or_404(Policy, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = PolicyVersionForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            services.create_policy_version(
                policy, form.cleaned_data['body'], request.user,
                change_note=form.cleaned_data.get('change_note', ''),
                effective_date=form.cleaned_data.get('effective_date'),
                publish=form.cleaned_data.get('publish', False), request=request)
            messages.success(request, 'Policy version saved.')
            return redirect('compliance:policy_detail', pk=policy.pk)
    else:
        form = PolicyVersionForm(tenant=request.tenant)
    return render(request, 'compliance/policy_version_form.html',
                  {'form': form, 'policy': policy})


@login_required
@require_POST
def policy_publish(request, pk, vpk):
    denied = _require_manage(request)
    if denied:
        return denied
    policy = get_object_or_404(Policy, pk=pk, tenant=request.tenant)
    version = get_object_or_404(policy.versions, pk=vpk)
    services.publish_policy(policy, version, request.user, request=request)
    messages.success(request, f'Published v{version.version_no}.')
    return redirect('compliance:policy_detail', pk=policy.pk)


@login_required
@require_POST
def policy_set_status(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    policy = get_object_or_404(Policy, pk=pk, tenant=request.tenant)
    try:
        services.set_policy_status(policy, request.POST.get('status', ''), request.user,
                                   request=request)
        messages.success(request, f'Policy {policy.policy_number} updated.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('compliance:policy_detail', pk=policy.pk)


@login_required
def my_policies(request):
    """Every published policy requiring acknowledgment + this user's sign-off status."""
    published = (Policy.objects.filter(
        tenant=request.tenant, status='published', requires_acknowledgment=True)
        .select_related('current_version').order_by('title'))
    acked_ids = set()
    if published:
        from .models import PolicyAcknowledgment
        acked_ids = set(PolicyAcknowledgment.objects.filter(
            tenant=request.tenant, user=request.user,
            policy_version__in=[p.current_version_id for p in published if p.current_version_id]
        ).values_list('policy_version_id', flat=True))
    items = [{'policy': p, 'acked': p.current_version_id in acked_ids} for p in published]
    return render(request, 'compliance/my_policies.html', {'items': items})


@login_required
@require_POST
def policy_acknowledge(request, pk):
    policy = get_object_or_404(
        Policy.objects.select_related('current_version'), pk=pk, tenant=request.tenant)
    if not policy.current_version_id:
        messages.error(request, 'This policy has no published version.')
        return redirect('compliance:my_policies')
    _, created = services.acknowledge_policy(policy.current_version, request.user, request=request)
    messages.success(
        request, 'Thank you — acknowledged.' if created else 'Already acknowledged.')
    return redirect('compliance:my_policies')
