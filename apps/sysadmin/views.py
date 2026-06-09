"""Module 21 views: System Administration & Security.

Function-based, mirroring dms/compliance: ``@login_required`` + a single ``_require_admin`` gate
(this whole module is tenant-admin / super-admin only), tenant-scoped lookups, list search + filters
+ ``Paginator``. Every mutation is audited inside the service layer.

SECURITY: secrets are never rendered back — the API-key plaintext is shown exactly once (the create
response), and SSO/webhook secrets use write-only form widgets. The webhook target + SSO metadata URL
pass a fail-closed SSRF guard before any outbound call.
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

from apps.spend_analytics.exports import csv_response

from . import backups, services, webhooks
from .forms import (
    ApiKeyIssueForm, BackupPolicyForm, CurrencyForm, IdentityProviderForm, NumberSequenceForm,
    RestoreRequestForm, RoleDefinitionForm, SystemConfigurationForm, TaxCodeForm, WebhookForm,
)
from .models import (
    BACKUP_SCOPE_CHOICES, BACKUP_STATUS_CHOICES, RESTORE_STATUS_CHOICES,
    SSO_PROTOCOL_CHOICES, TAX_TYPE_CHOICES, ApiKey, BackupPolicy, BackupRun, Currency,
    IdentityProvider, NumberSequence, RestoreRequest, RoleDefinition, TaxCode, Webhook,
)
from .permissions import PERMISSION_CATALOG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _has_named_url(name):
    try:
        reverse(name)
        return True
    except Exception:
        return False


def _require_admin(request):
    if not services.can_manage_sysadmin(request.user):
        messages.error(request, 'System administration is restricted to tenant administrators.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _querystring(request, *drop):
    qs = request.GET.copy()
    for key in ('page',) + drop:
        qs.pop(key, None)
    return qs.urlencode()


def _paginate(request, qs, per_page=20):
    return Paginator(qs, per_page).get_page(request.GET.get('page'))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    denied = _require_admin(request)
    if denied:
        return denied
    return render(request, 'sysadmin/dashboard.html', {
        'metrics': services.tenant_sysadmin_metrics(request.tenant),
    })


# ---------------------------------------------------------------------------
# 1. Roles & Permissions
# ---------------------------------------------------------------------------
@login_required
def role_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    services.ensure_system_roles(request.tenant)  # lazily backfill built-ins
    qs = RoleDefinition.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    status = request.GET.get('status', '')
    if status in ('active', 'inactive'):
        qs = qs.filter(is_active=(status == 'active'))
    return render(request, 'sysadmin/roles/list.html', {
        'page_obj': _paginate(request, qs), 'q': q, 'status': status,
        'querystring': _querystring(request),
    })


@login_required
def role_create(request):
    denied = _require_admin(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = RoleDefinitionForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            role = form.save(commit=False)
            role.tenant = request.tenant
            role.is_system = False
            role.save()
            services.record_audit(
                request.tenant, request.user, 'sysadmin.role_created', target_type='RoleDefinition',
                target_id=str(role.pk), message=f'Role {role.name} created.', request=request)
            messages.success(request, f'Role “{role.name}” created.')
            return redirect('sysadmin:role_permissions', pk=role.pk)
    else:
        form = RoleDefinitionForm(tenant=request.tenant)
    return render(request, 'sysadmin/roles/form.html', {'form': form, 'is_edit': False})


@login_required
def role_edit(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    role = get_object_or_404(RoleDefinition, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = RoleDefinitionForm(request.POST, instance=role, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Role updated.')
            return redirect('sysadmin:role_detail', pk=role.pk)
    else:
        form = RoleDefinitionForm(instance=role, tenant=request.tenant)
    return render(request, 'sysadmin/roles/form.html',
                  {'form': form, 'role': role, 'is_edit': True})


@login_required
def role_detail(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    role = get_object_or_404(RoleDefinition, pk=pk, tenant=request.tenant)
    granted = services.role_permission_codes(role)
    groups = [
        {'name': name,
         'perms': [{'code': code, 'label': label, 'granted': code in granted}
                   for code, label in prs]}
        for name, prs in PERMISSION_CATALOG
    ]
    return render(request, 'sysadmin/roles/detail.html', {
        'role': role, 'groups': groups, 'granted_count': len(granted),
        'can_delete': services.can_delete_role(role),
    })


@login_required
def role_permissions(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    role = get_object_or_404(RoleDefinition, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        codes = request.POST.getlist('permissions')
        added, removed = services.set_role_permissions(
            role, codes, user=request.user, request=request)
        messages.success(request, f'Permissions saved (+{added} / -{removed}).')
        return redirect('sysadmin:role_detail', pk=role.pk)
    granted = services.role_permission_codes(role)
    groups = [
        {'name': name,
         'perms': [{'code': code, 'label': label, 'granted': code in granted}
                   for code, label in prs]}
        for name, prs in PERMISSION_CATALOG
    ]
    return render(request, 'sysadmin/roles/permission_matrix.html', {'role': role, 'groups': groups})


@login_required
@require_POST
def role_delete(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    role = get_object_or_404(RoleDefinition, pk=pk, tenant=request.tenant)
    if not services.can_delete_role(role):
        messages.error(request, 'Built-in roles cannot be deleted.')
        return redirect('sysadmin:role_detail', pk=role.pk)
    name = role.name
    role.delete()
    services.record_audit(
        request.tenant, request.user, 'sysadmin.role_deleted', target_type='RoleDefinition',
        target_id=str(pk), message=f'Role {name} deleted.', request=request)
    messages.success(request, f'Role “{name}” deleted.')
    return redirect('sysadmin:role_list')


# ---------------------------------------------------------------------------
# 2. LDAP / SSO
# ---------------------------------------------------------------------------
@login_required
def provider_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    qs = IdentityProvider.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(entity_id__icontains=q))
    protocol = request.GET.get('protocol', '')
    if protocol:
        qs = qs.filter(protocol=protocol)
    status = request.GET.get('status', '')
    if status in ('active', 'inactive'):
        qs = qs.filter(is_active=(status == 'active'))
    return render(request, 'sysadmin/sso/list.html', {
        'page_obj': _paginate(request, qs), 'q': q, 'protocol': protocol, 'status': status,
        'protocol_choices': SSO_PROTOCOL_CHOICES, 'querystring': _querystring(request),
    })


@login_required
def provider_create(request):
    denied = _require_admin(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = IdentityProviderForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            provider = form.save(commit=False)
            provider.tenant = request.tenant
            provider.save()
            services.record_audit(
                request.tenant, request.user, 'sysadmin.sso_created',
                target_type='IdentityProvider', target_id=str(provider.pk),
                message=f'SSO provider {provider.name} created.', request=request)
            messages.success(request, f'Identity provider “{provider.name}” created.')
            return redirect('sysadmin:provider_detail', pk=provider.pk)
    else:
        form = IdentityProviderForm(tenant=request.tenant)
    return render(request, 'sysadmin/sso/form.html', {'form': form, 'is_edit': False})


@login_required
def provider_edit(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    provider = get_object_or_404(IdentityProvider, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = IdentityProviderForm(request.POST, instance=provider, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Identity provider updated.')
            return redirect('sysadmin:provider_detail', pk=provider.pk)
    else:
        form = IdentityProviderForm(instance=provider, tenant=request.tenant)
    return render(request, 'sysadmin/sso/form.html',
                  {'form': form, 'provider': provider, 'is_edit': True})


@login_required
def provider_detail(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    provider = get_object_or_404(IdentityProvider, pk=pk, tenant=request.tenant)
    return render(request, 'sysadmin/sso/detail.html', {
        'provider': provider,
        'events': provider.login_events.select_related('user')[:20],
    })


@login_required
@require_POST
def provider_test(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    provider = get_object_or_404(IdentityProvider, pk=pk, tenant=request.tenant)
    result = services.test_identity_provider(provider, user=request.user, request=request)
    (messages.success if result.ok else messages.error)(request, result.message)
    return redirect('sysadmin:provider_detail', pk=provider.pk)


@login_required
@require_POST
def provider_simulate(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    provider = get_object_or_404(IdentityProvider, pk=pk, tenant=request.tenant)
    email = (request.POST.get('email') or '').strip()
    result, outcome = services.simulate_sso_login(provider, email, user=request.user, request=request)
    (messages.success if result.ok else messages.error)(
        request, f'{result.message} (outcome: {outcome})')
    return redirect('sysadmin:provider_detail', pk=provider.pk)


@login_required
@require_POST
def provider_delete(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    provider = get_object_or_404(IdentityProvider, pk=pk, tenant=request.tenant)
    name = provider.name
    provider.delete()
    services.record_audit(
        request.tenant, request.user, 'sysadmin.sso_deleted', target_type='IdentityProvider',
        target_id=str(pk), message=f'SSO provider {name} deleted.', request=request)
    messages.success(request, f'Identity provider “{name}” deleted.')
    return redirect('sysadmin:provider_list')


# ---------------------------------------------------------------------------
# 3. System Configuration & Setup
# ---------------------------------------------------------------------------
@login_required
def config_overview(request):
    denied = _require_admin(request)
    if denied:
        return denied
    config = services.get_system_configuration(request.tenant)
    if request.method == 'POST':
        form = SystemConfigurationForm(request.POST, instance=config, tenant=request.tenant)
        if form.is_valid():
            form.save()
            services.record_audit(
                request.tenant, request.user, 'sysadmin.config_updated',
                target_type='SystemConfiguration', target_id=str(config.pk),
                message='System configuration updated.', request=request)
            messages.success(request, 'System configuration saved.')
            return redirect('sysadmin:config_overview')
    else:
        form = SystemConfigurationForm(instance=config, tenant=request.tenant)
    return render(request, 'sysadmin/config/overview.html', {
        'form': form, 'config': config,
        'currency_count': Currency.objects.filter(tenant=request.tenant).count(),
        'taxcode_count': TaxCode.objects.filter(tenant=request.tenant).count(),
        'sequence_count': NumberSequence.objects.filter(tenant=request.tenant).count(),
    })


# --- Currencies ---
@login_required
def currency_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    qs = Currency.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    status = request.GET.get('status', '')
    if status in ('active', 'inactive'):
        qs = qs.filter(is_active=(status == 'active'))
    return render(request, 'sysadmin/config/currency_list.html', {
        'page_obj': _paginate(request, qs), 'q': q, 'status': status,
        'querystring': _querystring(request),
    })


@login_required
def currency_create(request):
    denied = _require_admin(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = CurrencyForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.tenant = request.tenant
            obj.save()
            messages.success(request, f'Currency {obj.code} added.')
            return redirect('sysadmin:currency_list')
    else:
        form = CurrencyForm(tenant=request.tenant)
    return render(request, 'sysadmin/config/currency_form.html', {'form': form, 'is_edit': False})


@login_required
def currency_edit(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    obj = get_object_or_404(Currency, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = CurrencyForm(request.POST, instance=obj, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Currency updated.')
            return redirect('sysadmin:currency_list')
    else:
        form = CurrencyForm(instance=obj, tenant=request.tenant)
    return render(request, 'sysadmin/config/currency_form.html',
                  {'form': form, 'currency': obj, 'is_edit': True})


@login_required
@require_POST
def currency_delete(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    obj = get_object_or_404(Currency, pk=pk, tenant=request.tenant)
    code = obj.code
    obj.delete()
    messages.success(request, f'Currency {code} deleted.')
    return redirect('sysadmin:currency_list')


# --- Tax codes ---
@login_required
def taxcode_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    qs = TaxCode.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    tax_type = request.GET.get('tax_type', '')
    if tax_type:
        qs = qs.filter(tax_type=tax_type)
    return render(request, 'sysadmin/config/taxcode_list.html', {
        'page_obj': _paginate(request, qs), 'q': q, 'tax_type': tax_type,
        'tax_type_choices': TAX_TYPE_CHOICES, 'querystring': _querystring(request),
    })


@login_required
def taxcode_create(request):
    denied = _require_admin(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = TaxCodeForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.tenant = request.tenant
            obj.save()
            messages.success(request, f'Tax code {obj.code} added.')
            return redirect('sysadmin:taxcode_list')
    else:
        form = TaxCodeForm(tenant=request.tenant)
    return render(request, 'sysadmin/config/taxcode_form.html', {'form': form, 'is_edit': False})


@login_required
def taxcode_edit(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    obj = get_object_or_404(TaxCode, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = TaxCodeForm(request.POST, instance=obj, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Tax code updated.')
            return redirect('sysadmin:taxcode_list')
    else:
        form = TaxCodeForm(instance=obj, tenant=request.tenant)
    return render(request, 'sysadmin/config/taxcode_form.html',
                  {'form': form, 'taxcode': obj, 'is_edit': True})


@login_required
@require_POST
def taxcode_delete(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    obj = get_object_or_404(TaxCode, pk=pk, tenant=request.tenant)
    code = obj.code
    obj.delete()
    messages.success(request, f'Tax code {code} deleted.')
    return redirect('sysadmin:taxcode_list')


# --- Number sequences ---
@login_required
def sequence_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    qs = NumberSequence.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(doc_type__icontains=q) | Q(name__icontains=q) | Q(prefix__icontains=q))
    status = request.GET.get('status', '')
    if status in ('active', 'inactive'):
        qs = qs.filter(is_active=(status == 'active'))
    sequences = list(qs)
    for seq in sequences:
        seq.preview = services.preview_number(seq)
    return render(request, 'sysadmin/config/sequence_list.html', {
        'sequences': sequences, 'q': q, 'status': status, 'querystring': _querystring(request),
    })


@login_required
def sequence_create(request):
    denied = _require_admin(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = NumberSequenceForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.tenant = request.tenant
            obj.save()
            messages.success(request, f'Number sequence “{obj.name}” added.')
            return redirect('sysadmin:sequence_list')
    else:
        form = NumberSequenceForm(tenant=request.tenant)
    return render(request, 'sysadmin/config/sequence_form.html', {'form': form, 'is_edit': False})


@login_required
def sequence_edit(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    obj = get_object_or_404(NumberSequence, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = NumberSequenceForm(request.POST, instance=obj, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Number sequence updated.')
            return redirect('sysadmin:sequence_list')
    else:
        form = NumberSequenceForm(instance=obj, tenant=request.tenant)
    return render(request, 'sysadmin/config/sequence_form.html',
                  {'form': form, 'sequence': obj, 'is_edit': True})


@login_required
@require_POST
def sequence_delete(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    obj = get_object_or_404(NumberSequence, pk=pk, tenant=request.tenant)
    name = obj.name
    obj.delete()
    messages.success(request, f'Number sequence “{name}” deleted.')
    return redirect('sysadmin:sequence_list')


# ---------------------------------------------------------------------------
# 4. Data Backup & Recovery
# ---------------------------------------------------------------------------
@login_required
def backup_policy_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    qs = BackupPolicy.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q))
    status = request.GET.get('status', '')
    if status in ('active', 'inactive'):
        qs = qs.filter(is_active=(status == 'active'))
    return render(request, 'sysadmin/backup/policy_list.html', {
        'page_obj': _paginate(request, qs), 'q': q, 'status': status,
        'recent_runs': BackupRun.objects.filter(tenant=request.tenant)
                       .select_related('policy')[:8],
        'querystring': _querystring(request),
    })


@login_required
def backup_policy_create(request):
    denied = _require_admin(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = BackupPolicyForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.tenant = request.tenant
            obj.save()
            services.record_audit(
                request.tenant, request.user, 'sysadmin.backup_policy_created',
                target_type='BackupPolicy', target_id=str(obj.pk),
                message=f'Backup policy {obj.name} created.', request=request)
            messages.success(request, f'Backup policy “{obj.name}” created.')
            return redirect('sysadmin:backup_policy_detail', pk=obj.pk)
    else:
        form = BackupPolicyForm(tenant=request.tenant)
    return render(request, 'sysadmin/backup/policy_form.html', {'form': form, 'is_edit': False})


@login_required
def backup_policy_edit(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    obj = get_object_or_404(BackupPolicy, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = BackupPolicyForm(request.POST, instance=obj, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Backup policy updated.')
            return redirect('sysadmin:backup_policy_detail', pk=obj.pk)
    else:
        form = BackupPolicyForm(instance=obj, tenant=request.tenant)
    return render(request, 'sysadmin/backup/policy_form.html',
                  {'form': form, 'policy': obj, 'is_edit': True})


@login_required
def backup_policy_detail(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    policy = get_object_or_404(BackupPolicy, pk=pk, tenant=request.tenant)
    return render(request, 'sysadmin/backup/policy_detail.html', {
        'policy': policy,
        'runs': policy.runs.select_related('triggered_by')[:25],
    })


@login_required
@require_POST
def backup_policy_delete(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    obj = get_object_or_404(BackupPolicy, pk=pk, tenant=request.tenant)
    name = obj.name
    obj.delete()
    messages.success(request, f'Backup policy “{name}” deleted.')
    return redirect('sysadmin:backup_policy_list')


@login_required
@require_POST
def backup_run_now(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    policy = get_object_or_404(BackupPolicy, pk=pk, tenant=request.tenant)
    run = backups.run_backup(
        request.tenant, policy=policy, trigger='manual', user=request.user, request=request)
    (messages.success if run.status == 'success' else messages.error)(
        request, f'Backup {run.run_number}: {run.get_status_display()} ({run.size_mb} MB).')
    return redirect('sysadmin:backup_policy_detail', pk=policy.pk)


@login_required
def backup_run_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    qs = BackupRun.objects.filter(tenant=request.tenant).select_related('policy', 'triggered_by')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(run_number__icontains=q) | Q(location__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    scope = request.GET.get('scope', '')
    if scope:
        qs = qs.filter(scope=scope)
    return render(request, 'sysadmin/backup/run_list.html', {
        'page_obj': _paginate(request, qs), 'q': q, 'status': status, 'scope': scope,
        'status_choices': BACKUP_STATUS_CHOICES, 'scope_choices': BACKUP_SCOPE_CHOICES,
        'querystring': _querystring(request),
    })


@login_required
def backup_run_detail(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    run = get_object_or_404(
        BackupRun.objects.select_related('policy', 'triggered_by'), pk=pk, tenant=request.tenant)
    return render(request, 'sysadmin/backup/run_detail.html', {
        'run': run, 'restore_form': RestoreRequestForm(tenant=request.tenant),
        'restores': run.restore_requests.select_related('requested_by', 'decided_by'),
    })


@login_required
def backup_run_export(request):
    denied = _require_admin(request)
    if denied:
        return denied
    header = ['Run', 'Policy', 'Status', 'Trigger', 'Scope', 'Size (MB)', 'Location', 'Created']
    rows = []
    for r in (BackupRun.objects.filter(tenant=request.tenant)
              .select_related('policy').order_by('-created_at')):
        rows.append([r.run_number, r.policy.name if r.policy else '', r.get_status_display(),
                     r.get_trigger_display(), r.get_scope_display(), r.size_mb, r.location,
                     r.created_at.isoformat()])
    return csv_response('backup_runs.csv', header, rows)


@login_required
@require_POST
def restore_request(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    run = get_object_or_404(BackupRun, pk=pk, tenant=request.tenant)
    if run.status != 'success':
        messages.error(request, 'Only a successful backup can be restored.')
        return redirect('sysadmin:backup_run_detail', pk=run.pk)
    form = RestoreRequestForm(request.POST, tenant=request.tenant)
    if form.is_valid():
        rr = form.save(commit=False)
        rr.tenant = request.tenant
        rr.backup_run = run
        rr.requested_by = request.user
        rr.save()
        services.record_audit(
            request.tenant, request.user, 'sysadmin.restore_requested', level='warning',
            target_type='RestoreRequest', target_id=str(rr.pk),
            message=f'Restore requested for {run.run_number}.', request=request)
        messages.success(request, 'Restore request logged for approval.')
    return redirect('sysadmin:restore_list')


@login_required
def restore_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    qs = (RestoreRequest.objects.filter(tenant=request.tenant)
          .select_related('backup_run', 'requested_by', 'decided_by'))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    return render(request, 'sysadmin/backup/restore_list.html', {
        'page_obj': _paginate(request, qs), 'status': status,
        'status_choices': RESTORE_STATUS_CHOICES, 'querystring': _querystring(request),
    })


@login_required
@require_POST
def restore_decide(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    rr = get_object_or_404(RestoreRequest, pk=pk, tenant=request.tenant)
    decision = request.POST.get('decision', '')
    mapping = {'approve': 'approved', 'reject': 'rejected', 'restored': 'restored'}
    if decision not in mapping:
        messages.error(request, 'Unknown decision.')
        return redirect('sysadmin:restore_list')
    rr.status = mapping[decision]
    rr.decided_by = request.user
    rr.decided_at = timezone.now()
    rr.message = (request.POST.get('message') or '')[:255]
    rr.save(update_fields=['status', 'decided_by', 'decided_at', 'message', 'updated_at'])
    services.record_audit(
        request.tenant, request.user, 'sysadmin.restore_decided', level='warning',
        target_type='RestoreRequest', target_id=str(rr.pk),
        message=f'Restore {rr.backup_run.run_number}: {rr.status}.', request=request)
    messages.success(request, f'Restore request marked {rr.get_status_display()}.')
    return redirect('sysadmin:restore_list')


# ---------------------------------------------------------------------------
# 5. API & Webhook Management
# ---------------------------------------------------------------------------
@login_required
def apikey_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    qs = ApiKey.objects.filter(tenant=request.tenant).select_related('created_by')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(key_prefix__icontains=q))
    status = request.GET.get('status', '')
    if status in ('active', 'inactive'):
        qs = qs.filter(is_active=(status == 'active'))
    return render(request, 'sysadmin/api/key_list.html', {
        'page_obj': _paginate(request, qs), 'q': q, 'status': status,
        'querystring': _querystring(request),
    })


@login_required
def apikey_create(request):
    denied = _require_admin(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = ApiKeyIssueForm(request.POST)
        if form.is_valid():
            api_key, raw = services.issue_api_key(
                request.tenant, name=form.cleaned_data['name'],
                scopes=form.cleaned_data.get('scopes'),
                expires_at=form.cleaned_data.get('expires_at'),
                user=request.user, request=request)
            # The plaintext is shown ONCE, here, and never stored or shown again.
            return render(request, 'sysadmin/api/key_reveal.html',
                          {'api_key': api_key, 'raw_secret': raw})
    else:
        form = ApiKeyIssueForm()
    return render(request, 'sysadmin/api/key_form.html', {'form': form})


@login_required
@require_POST
def apikey_revoke(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    api_key = get_object_or_404(ApiKey, pk=pk, tenant=request.tenant)
    services.revoke_api_key(api_key, user=request.user, request=request)
    messages.success(request, f'API key “{api_key.name}” revoked.')
    return redirect('sysadmin:apikey_list')


@login_required
@require_POST
def apikey_delete(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    api_key = get_object_or_404(ApiKey, pk=pk, tenant=request.tenant)
    name = api_key.name
    api_key.delete()
    services.record_audit(
        request.tenant, request.user, 'sysadmin.api_key_deleted', target_type='ApiKey',
        target_id=str(pk), message=f'API key {name} deleted.', request=request)
    messages.success(request, f'API key “{name}” deleted.')
    return redirect('sysadmin:apikey_list')


@login_required
def webhook_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    qs = Webhook.objects.filter(tenant=request.tenant)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(target_url__icontains=q))
    status = request.GET.get('status', '')
    if status in ('active', 'inactive'):
        qs = qs.filter(is_active=(status == 'active'))
    return render(request, 'sysadmin/api/webhook_list.html', {
        'page_obj': _paginate(request, qs), 'q': q, 'status': status,
        'querystring': _querystring(request),
    })


@login_required
def webhook_create(request):
    denied = _require_admin(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = WebhookForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.tenant = request.tenant
            obj.save()
            services.record_audit(
                request.tenant, request.user, 'sysadmin.webhook_created', target_type='Webhook',
                target_id=str(obj.pk), message=f'Webhook {obj.name} created.', request=request)
            messages.success(request, f'Webhook “{obj.name}” created.')
            return redirect('sysadmin:webhook_detail', pk=obj.pk)
    else:
        form = WebhookForm(tenant=request.tenant)
    return render(request, 'sysadmin/api/webhook_form.html', {'form': form, 'is_edit': False})


@login_required
def webhook_edit(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    obj = get_object_or_404(Webhook, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = WebhookForm(request.POST, instance=obj, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Webhook updated.')
            return redirect('sysadmin:webhook_detail', pk=obj.pk)
    else:
        form = WebhookForm(instance=obj, tenant=request.tenant)
    return render(request, 'sysadmin/api/webhook_form.html',
                  {'form': form, 'webhook': obj, 'is_edit': True})


@login_required
def webhook_detail(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    webhook = get_object_or_404(Webhook, pk=pk, tenant=request.tenant)
    return render(request, 'sysadmin/api/webhook_detail.html', {
        'webhook': webhook,
        'event_labels': webhooks.WEBHOOK_EVENT_LABELS,
        'deliveries': webhook.deliveries.all()[:25],
    })


@login_required
@require_POST
def webhook_test(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    webhook = get_object_or_404(Webhook, pk=pk, tenant=request.tenant)
    delivery = webhooks.test_webhook(webhook)
    (messages.success if delivery.status == 'success' else messages.warning)(
        request, f'Test delivery: {delivery.get_status_display()} '
                 f'({delivery.status_code or "no response"}). {delivery.response_excerpt}')
    return redirect('sysadmin:webhook_detail', pk=webhook.pk)


@login_required
@require_POST
def webhook_delete(request, pk):
    denied = _require_admin(request)
    if denied:
        return denied
    obj = get_object_or_404(Webhook, pk=pk, tenant=request.tenant)
    name = obj.name
    obj.delete()
    messages.success(request, f'Webhook “{name}” deleted.')
    return redirect('sysadmin:webhook_list')
