"""Module 20 views: Document & Knowledge Management.

Function-based views mirroring compliance / budget: ``@login_required`` + a ``_require_view`` /
``_require_manage`` permission gate, tenant-scoped lookups, list search + filters + ``Paginator``.

SECURITY (lessons.md D-01/D-02): EVERY read view AND the CSV export call ``_require_view`` first;
mutations call ``_require_manage``. File uploads instantiate the form with ``request.FILES``; the
download view serves the stored file only after the same tenant + view gate.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.spend_analytics.exports import csv_response

from . import services
from .forms import DocumentForm, DocumentVersionForm, PolicyTemplateForm
from .models import (
    CONFIDENTIALITY_CHOICES, DOC_CATEGORY_CHOICES, DOC_STATUS_CHOICES,
    TEMPLATE_CATEGORY_CHOICES, Document, DocumentVersion, PolicyTemplate,
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
    if not services.can_view_documents(request.user):
        messages.error(request, 'You do not have permission to view documents.')
        return redirect('dashboard') if _has_named_url('dashboard') else redirect('/')
    return None


def _require_manage(request):
    if not services.can_manage_documents(request.user):
        messages.error(request, 'You do not have permission to manage documents.')
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
    metrics = services.tenant_document_metrics(request.tenant)
    return render(request, 'dms/dashboard.html', {
        'metrics': metrics,
        'can_manage': services.can_manage_documents(request.user),
    })


# ---------------------------------------------------------------------------
# 1. Document repository
# ---------------------------------------------------------------------------
def _document_queryset(request):
    qs = (Document.objects.filter(tenant=request.tenant)
          .select_related('owner', 'current_version'))
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(document_number__icontains=q) | Q(title__icontains=q) | Q(tags__icontains=q)
            | Q(summary__icontains=q) | Q(versions__extracted_text__icontains=q)).distinct()
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    category = request.GET.get('category', '')
    if category:
        qs = qs.filter(category=category)
    confidentiality = request.GET.get('confidentiality', '')
    if confidentiality:
        qs = qs.filter(confidentiality=confidentiality)
    return qs


@login_required
def document_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = _document_queryset(request)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'dms/document_list.html', {
        'page_obj': page_obj, 'documents': page_obj.object_list,
        'q': request.GET.get('q', ''), 'status': request.GET.get('status', ''),
        'category': request.GET.get('category', ''),
        'confidentiality': request.GET.get('confidentiality', ''),
        'status_choices': DOC_STATUS_CHOICES, 'category_choices': DOC_CATEGORY_CHOICES,
        'confidentiality_choices': CONFIDENTIALITY_CHOICES,
        'querystring': _querystring(request),
        'can_manage': services.can_manage_documents(request.user),
    })


@login_required
def document_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = DocumentForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            cd = form.cleaned_data
            document = services.create_document(
                request.tenant, title=cd['title'], category=cd['category'],
                confidentiality=cd['confidentiality'], summary=cd.get('summary', ''),
                tags=cd.get('tags', ''), owner=cd.get('owner'), user=request.user,
                request=request)
            messages.success(
                request, f'Document {document.document_number} created. Upload a version.')
            return redirect('dms:document_detail', pk=document.pk)
    else:
        form = DocumentForm(tenant=request.tenant)
    return render(request, 'dms/document_form.html', {'form': form, 'is_edit': False})


@login_required
def document_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    document = get_object_or_404(Document, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = DocumentForm(request.POST, instance=document, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Document updated.')
            return redirect('dms:document_detail', pk=document.pk)
    else:
        form = DocumentForm(instance=document, tenant=request.tenant)
    return render(request, 'dms/document_form.html',
                  {'form': form, 'document': document, 'is_edit': True})


@login_required
@require_POST
def document_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    document = get_object_or_404(Document, pk=pk, tenant=request.tenant)
    number = document.document_number
    document.delete()
    messages.success(request, f'Document {number} deleted.')
    return redirect('dms:document_list')


@login_required
def document_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    document = get_object_or_404(
        Document.objects.select_related('owner', 'current_version'), pk=pk, tenant=request.tenant)
    return render(request, 'dms/document_detail.html', {
        'document': document,
        'versions': document.versions.select_related('uploaded_by', 'published_by'),
        'events': document.events.select_related('actor')[:30],
        'version_form': DocumentVersionForm(tenant=request.tenant),
        'status_choices': DOC_STATUS_CHOICES,
        'can_manage': services.can_manage_documents(request.user),
    })


@login_required
@require_POST
def document_set_status(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    document = get_object_or_404(Document, pk=pk, tenant=request.tenant)
    try:
        services.set_document_status(document, request.POST.get('status', ''), request.user,
                                     request=request)
        messages.success(request, f'Document {document.document_number} updated.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('dms:document_detail', pk=document.pk)


# ---------------------------------------------------------------------------
# 2. Versions
# ---------------------------------------------------------------------------
@login_required
def version_create(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    document = get_object_or_404(Document, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = DocumentVersionForm(request.POST, request.FILES, tenant=request.tenant)
        if form.is_valid():
            version = services.create_document_version(
                document, form.cleaned_data['file'], request.user,
                change_note=form.cleaned_data.get('change_note', ''),
                publish=form.cleaned_data.get('publish', False), request=request)
            messages.success(
                request, f'Version {version.version_no} uploaded and indexed '
                         f'({version.index_status}).')
            return redirect('dms:document_detail', pk=document.pk)
    else:
        form = DocumentVersionForm(tenant=request.tenant)
    return render(request, 'dms/version_form.html', {'form': form, 'document': document})


@login_required
@require_POST
def version_publish(request, pk, vpk):
    denied = _require_manage(request)
    if denied:
        return denied
    document = get_object_or_404(Document, pk=pk, tenant=request.tenant)
    version = get_object_or_404(document.versions, pk=vpk)
    services.publish_version(version, request.user, request=request)
    messages.success(request, f'Published v{version.version_no}.')
    return redirect('dms:document_detail', pk=document.pk)


@login_required
@require_POST
def version_reindex(request, pk, vpk):
    denied = _require_manage(request)
    if denied:
        return denied
    document = get_object_or_404(Document, pk=pk, tenant=request.tenant)
    version = get_object_or_404(document.versions, pk=vpk)
    services.index_version(version, user=request.user, request=request)
    messages.success(request, f'Re-indexed v{version.version_no} ({version.index_status}).')
    return redirect('dms:document_detail', pk=document.pk)


@login_required
def version_download(request, pk, vpk):
    denied = _require_view(request)
    if denied:
        return denied
    document = get_object_or_404(Document, pk=pk, tenant=request.tenant)
    version = get_object_or_404(document.versions, pk=vpk)
    if not version.file:
        raise Http404('No file on this version.')
    try:
        handle = version.file.open('rb')
    except (FileNotFoundError, ValueError):
        raise Http404('File is missing from storage.')
    filename = version.original_filename or version.file.name.rsplit('/', 1)[-1]
    return FileResponse(handle, as_attachment=True, filename=filename)


# ---------------------------------------------------------------------------
# 3. Procurement policy library
# ---------------------------------------------------------------------------
@login_required
def policy_library(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = (Document.objects.filter(tenant=request.tenant, category='policy')
          .select_related('owner', 'current_version'))
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(document_number__icontains=q) | Q(title__icontains=q) | Q(tags__icontains=q)
            | Q(versions__extracted_text__icontains=q)).distinct()
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'dms/policy_library.html', {
        'page_obj': page_obj, 'documents': page_obj.object_list, 'q': q, 'status': status,
        'status_choices': DOC_STATUS_CHOICES, 'querystring': _querystring(request),
        'can_manage': services.can_manage_documents(request.user),
    })


# ---------------------------------------------------------------------------
# 5. Full-text search
# ---------------------------------------------------------------------------
@login_required
def search(request):
    denied = _require_view(request)
    if denied:
        return denied
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    results = services.search_documents(request.tenant, q, category=category or None)
    return render(request, 'dms/search_results.html', {
        'q': q, 'category': category, 'results': results, 'result_count': len(results),
        'category_choices': DOC_CATEGORY_CHOICES,
        'can_manage': services.can_manage_documents(request.user),
    })


# ---------------------------------------------------------------------------
# 4. Best-practice template library
# ---------------------------------------------------------------------------
@login_required
def policy_template_list(request):
    denied = _require_view(request)
    if denied:
        return denied
    qs = PolicyTemplate.objects.filter(tenant=request.tenant).select_related('owner')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(template_number__icontains=q) | Q(title__icontains=q))
    status = request.GET.get('status', '')
    if status:
        qs = qs.filter(status=status)
    category = request.GET.get('category', '')
    if category:
        qs = qs.filter(category=category)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'dms/policy_template_list.html', {
        'page_obj': page_obj, 'templates': page_obj.object_list, 'q': q, 'status': status,
        'category': category, 'status_choices': DOC_STATUS_CHOICES,
        'category_choices': TEMPLATE_CATEGORY_CHOICES, 'querystring': _querystring(request),
        'can_manage': services.can_manage_documents(request.user),
    })


@login_required
def policy_template_create(request):
    denied = _require_manage(request)
    if denied:
        return denied
    if request.method == 'POST':
        form = PolicyTemplateForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            template = form.save(commit=False)
            template.tenant = request.tenant
            template.template_number = services.next_template_number(request.tenant)
            template.save()
            services.record_audit(
                request.tenant, request.user, 'dms.template_created',
                target_type='PolicyTemplate', target_id=str(template.pk),
                message=f'Template {template.template_number} created.', request=request)
            messages.success(request, f'Template {template.template_number} created.')
            return redirect('dms:policy_template_detail', pk=template.pk)
    else:
        form = PolicyTemplateForm(tenant=request.tenant)
    return render(request, 'dms/policy_template_form.html', {'form': form, 'is_edit': False})


@login_required
def policy_template_edit(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    template = get_object_or_404(PolicyTemplate, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = PolicyTemplateForm(request.POST, instance=template, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, 'Template updated.')
            return redirect('dms:policy_template_detail', pk=template.pk)
    else:
        form = PolicyTemplateForm(instance=template, tenant=request.tenant)
    return render(request, 'dms/policy_template_form.html',
                  {'form': form, 'template': template, 'is_edit': True})


@login_required
def policy_template_detail(request, pk):
    denied = _require_view(request)
    if denied:
        return denied
    template = get_object_or_404(
        PolicyTemplate.objects.select_related('owner'), pk=pk, tenant=request.tenant)
    return render(request, 'dms/policy_template_detail.html', {
        'template': template,
        'can_manage': services.can_manage_documents(request.user),
    })


@login_required
@require_POST
def policy_template_delete(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    template = get_object_or_404(PolicyTemplate, pk=pk, tenant=request.tenant)
    number = template.template_number
    template.delete()
    messages.success(request, f'Template {number} deleted.')
    return redirect('dms:policy_template_list')


@login_required
@require_POST
def policy_template_clone(request, pk):
    denied = _require_manage(request)
    if denied:
        return denied
    template = get_object_or_404(PolicyTemplate, pk=pk, tenant=request.tenant)
    document = services.clone_template_to_document(template, request.user, request=request)
    messages.success(
        request, f'Created {document.document_number} from {template.template_number}.')
    return redirect('dms:document_detail', pk=document.pk)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
@login_required
def document_export(request):
    denied = _require_view(request)
    if denied:
        return denied
    header, rows = services.document_export_rows(request.tenant)
    return csv_response('documents.csv', header, rows)
