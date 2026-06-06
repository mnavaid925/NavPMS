"""Module 20 service layer: Document & Knowledge Management.

Owns every state transition + side effect, mirroring the Module 18 (compliance) conventions:
``MANAGE_ROLES`` / ``VIEW_ROLES`` + ``_has_role`` permission helpers, gap-free
``PREFIX-<SLUG>-NNNNN`` numbering, ``record_audit`` from :mod:`apps.tenants.services`,
``create_notification`` from :mod:`apps.portal.services`, and ``@transaction.atomic`` write paths.

The pluggable text-extraction connector (``extraction.py``) is injected via ``provider=None`` so
tests can pass a stub. Full-text search is intentionally written with portable ``icontains`` so the
SQLite test database and the MySQL production database run the same code path — see
:func:`search_documents` for the documented MySQL ``FULLTEXT`` upgrade.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.text import slugify

from apps.core.models import Tenant, set_current_tenant
from apps.portal.services import create_notification
from apps.tenants.services import record_audit

from .extraction import get_text_extraction_provider
from .models import (
    DOC_CATEGORY_CHOICES, Document, DocumentEvent, DocumentVersion, PolicyTemplate,
)

# Roles allowed to manage the repository (upload, publish, edit, delete, manage templates). Mirrors
# the other procurement modules — there is no dedicated librarian role in the project yet.
MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
# Viewing (dashboard / lists / search / download) additionally allows approvers.
VIEW_ROLES = MANAGE_ROLES + ('approver',)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _has_role(user, roles):
    """True if the user holds any of ``roles`` (string slugs)."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'is_tenant_admin', False):
        return True
    role = getattr(user, 'role', None)
    role_slug = role if isinstance(role, str) else (
        getattr(role, 'slug', None) or getattr(role, 'name', None))
    return role_slug in roles


def can_manage_documents(user):
    """May upload, publish, edit, delete documents and manage templates."""
    return _has_role(user, MANAGE_ROLES)


def can_view_documents(user):
    """May view dashboards / lists / search / download (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def _next_number(model, tenant, prefix, field_name) -> str:
    """Generate the next gap-free ``<PREFIX>-<SLUG>-NNNNN`` number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = model.all_objects.filter(tenant=tenant).count() + 1
    number = f'{prefix}-{slug}-{count:05d}'
    while model.all_objects.filter(tenant=tenant, **{field_name: number}).exists():
        count += 1
        number = f'{prefix}-{slug}-{count:05d}'
    return number


def next_document_number(tenant):
    return _next_number(Document, tenant, 'DOC', 'document_number')


def next_template_number(tenant):
    return _next_number(PolicyTemplate, tenant, 'TPL', 'template_number')


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
def record_document_event(document, event, *, version=None, from_status='', to_status='',
                          actor=None, note=''):
    return DocumentEvent.all_objects.create(
        tenant=document.tenant, document=document, version=version, event=event,
        from_status=from_status, to_status=to_status, actor=actor, note=note[:255],
    )


# ---------------------------------------------------------------------------
# 1. Documents
# ---------------------------------------------------------------------------
@transaction.atomic
def create_document(tenant, *, title, category='other', confidentiality='internal', summary='',
                    tags='', owner=None, user=None, request=None):
    """Create a draft document (no file yet — versions are uploaded next) + audit it."""
    document = Document.all_objects.create(
        tenant=tenant, document_number=next_document_number(tenant), title=title,
        category=category, confidentiality=confidentiality, summary=summary, tags=tags,
        owner=owner or user, created_by=user, status='draft',
    )
    record_document_event(document, 'created', actor=user, note='Document created.')
    record_audit(
        tenant, user, 'dms.document_created', target_type='Document',
        target_id=str(document.pk), message=f'Document {document.document_number} created.',
        request=request,
    )
    return document


# ---------------------------------------------------------------------------
# 2. Versions + indexing (Version Control + Full-Text Search)
# ---------------------------------------------------------------------------
@transaction.atomic
def index_version(version, *, provider=None, user=None, request=None):
    """Extract text from the version's file and persist it to the searchable index field."""
    provider = provider or get_text_extraction_provider()
    result = provider.extract(version.file, content_type=version.content_type or None)
    version.extracted_text = result.text or ''
    version.page_count = result.page_count or 0
    version.extraction_engine = result.provider
    version.index_status = 'indexed' if result.ok and result.text else 'failed'
    version.extracted_at = timezone.now()
    version.save(update_fields=['extracted_text', 'page_count', 'extraction_engine',
                                'index_status', 'extracted_at', 'updated_at'])
    record_document_event(
        version.document, 'indexed', version=version, actor=user,
        note=f'Indexed via {result.provider} ({version.index_status}).')
    return version


@transaction.atomic
def create_document_version(document, uploaded_file, user, *, change_note='', publish=False,
                            request=None):
    """Attach a new immutable file version to a document, index it, optionally publish it."""
    last = document.versions.order_by('-version_no').first()
    version_no = (last.version_no + 1) if last else 1
    version = DocumentVersion.all_objects.create(
        tenant=document.tenant, document=document, version_no=version_no, file=uploaded_file,
        original_filename=(getattr(uploaded_file, 'name', '') or '')[:255],
        file_size=getattr(uploaded_file, 'size', 0) or 0,
        content_type=(getattr(uploaded_file, 'content_type', '') or '')[:100],
        change_note=change_note[:255], uploaded_by=user, status='draft',
    )
    record_document_event(
        document, 'version_uploaded', version=version, actor=user,
        note=f'Uploaded v{version_no}.')
    record_audit(
        document.tenant, user, 'dms.version_uploaded', target_type='DocumentVersion',
        target_id=str(version.pk),
        message=f'{document.document_number} v{version_no} uploaded.', request=request)
    index_version(version, user=user, request=request)
    if publish:
        publish_version(version, user, request=request)
    return version


@transaction.atomic
def publish_version(version, user, *, request=None):
    """Make ``version`` the current published one; supersede the rest; publish the document."""
    document = version.document
    now = timezone.now()
    # Supersede any previously-published versions of this document.
    (DocumentVersion.all_objects
     .filter(document=document, status='published')
     .exclude(pk=version.pk)
     .update(status='superseded', updated_at=now))
    version.status = 'published'
    version.published_by = user
    version.published_at = now
    version.save(update_fields=['status', 'published_by', 'published_at', 'updated_at'])
    document.current_version = version
    document.status = 'published'
    document.published_at = document.published_at or now
    document.save(update_fields=['current_version', 'status', 'published_at', 'updated_at'])
    record_document_event(
        document, 'version_published', version=version, to_status='published', actor=user,
        note=f'Published v{version.version_no}.')
    record_audit(
        document.tenant, user, 'dms.version_published', target_type='Document',
        target_id=str(document.pk),
        message=f'{document.document_number} v{version.version_no} published.', request=request)
    return version


@transaction.atomic
def set_document_status(document, status, user, *, request=None):
    """Archive / re-draft a document (audited + timelined)."""
    valid = {s for s, _ in Document.STATUS_CHOICES}
    if status not in valid:
        from django.core.exceptions import ValidationError
        raise ValidationError('Invalid document status.')
    from_status = document.status
    document.status = status
    document.save(update_fields=['status', 'updated_at'])
    record_document_event(
        document, 'status_changed', from_status=from_status, to_status=status, actor=user)
    record_audit(
        document.tenant, user, 'dms.document_status', target_type='Document',
        target_id=str(document.pk),
        message=f'{document.document_number}: {from_status} → {status}.', request=request)
    return document


def extract_pending(tenant):
    """Idempotent cron worker — (re)index every version still pending / failed extraction."""
    pending = DocumentVersion.all_objects.filter(
        tenant=tenant, index_status__in=('pending', 'failed'))
    n = 0
    for version in pending.select_related('document'):
        index_version(version)
        n += 1
    return {'indexed': n}


# ---------------------------------------------------------------------------
# 5. Full-text search
# ---------------------------------------------------------------------------
def _snippet(text, query, width=200):
    """A short context window around the first match of ``query`` in ``text``."""
    text = text or ''
    if not query:
        return text[:width]
    low = text.lower()
    i = low.find(query.lower())
    if i == -1:
        return text[:width]
    start = max(0, i - 70)
    end = min(len(text), i + len(query) + 110)
    return ('…' if start else '') + text[start:end].strip() + ('…' if end < len(text) else '')


def search_documents(tenant, query, *, category=None):
    """Full-text search across documents: title / number / tags / summary / extracted text.

    Returns a list of ``{'document', 'version', 'snippet'}`` hits.

    Implemented with portable ``icontains`` so the SQLite test DB and MySQL prod DB share one code
    path. TODO(MySQL FULLTEXT): for large corpora, add a ``FULLTEXT`` index on
    ``DocumentVersion.extracted_text`` via a MySQL-guarded ``RunSQL`` migration and branch here on
    ``connection.vendor == 'mysql'`` to ``MATCH(extracted_text) AGAINST(%s IN NATURAL LANGUAGE
    MODE)`` — keeping this ``icontains`` path as the SQLite/test fallback.
    """
    query = (query or '').strip()
    if not query:
        return []
    docs = (Document.all_objects.filter(tenant=tenant)
            .select_related('current_version', 'owner'))
    if category:
        docs = docs.filter(category=category)
    matched = docs.filter(
        Q(title__icontains=query) | Q(document_number__icontains=query)
        | Q(tags__icontains=query) | Q(summary__icontains=query)
        | Q(versions__extracted_text__icontains=query)
    ).distinct().order_by('title')
    results = []
    for d in matched:
        version = d.current_version or d.versions.order_by('-version_no').first()
        text = version.extracted_text if version else ''
        results.append({'document': d, 'version': version, 'snippet': _snippet(text, query)})
    return results


# ---------------------------------------------------------------------------
# 4. Templates
# ---------------------------------------------------------------------------
@transaction.atomic
def clone_template_to_document(template, user, *, request=None):
    """Stamp a :class:`PolicyTemplate` body into a new :class:`Document` (first published version)."""
    from django.core.files.base import ContentFile

    document = Document.all_objects.create(
        tenant=template.tenant, document_number=next_document_number(template.tenant),
        title=f'{template.title} (from template)', category='other', confidentiality='internal',
        summary=template.description, owner=user, created_by=user, status='draft',
    )
    record_document_event(
        document, 'created', actor=user,
        note=f'Cloned from template {template.template_number}.')
    content = ContentFile(
        (template.body or '').encode('utf-8'),
        name=f'{slugify(template.title) or "template"}.txt')
    create_document_version(
        document, content, user,
        change_note=f'From template {template.template_number}.', publish=True, request=request)
    record_audit(
        template.tenant, user, 'dms.template_cloned', target_type='PolicyTemplate',
        target_id=str(template.pk),
        message=f'Template {template.template_number} cloned to {document.document_number}.',
        request=request)
    return document


# ---------------------------------------------------------------------------
# Notifications helper
# ---------------------------------------------------------------------------
def _notify_managers(tenant, title, message, *, link_url='', priority='normal'):
    """In-app alert to every tenant admin (the document owners)."""
    from apps.accounts.models import User
    for u in User.objects.filter(tenant=tenant, is_active=True, is_tenant_admin=True):
        create_notification(
            tenant, u, title, category='system', priority=priority,
            message=message, link_url=link_url,
        )


# ---------------------------------------------------------------------------
# Dashboard metrics
# ---------------------------------------------------------------------------
def tenant_document_metrics(tenant):
    """KPI cards + chart series for the documents dashboard."""
    docs = Document.all_objects.filter(tenant=tenant)
    versions = DocumentVersion.all_objects.filter(tenant=tenant)
    templates = PolicyTemplate.all_objects.filter(tenant=tenant)

    total_versions = versions.count()
    indexed_versions = versions.filter(index_status='indexed').count()
    index_pct = round(indexed_versions / total_versions * 100, 1) if total_versions else 0.0

    cat_map = dict(DOC_CATEGORY_CHOICES)
    cat_counts = {key: 0 for key in cat_map}
    for row in docs.values('category').annotate(n=Count('id')):
        cat_counts[row['category']] = row['n']

    status_counts = {'draft': 0, 'published': 0, 'archived': 0}
    for row in docs.values('status').annotate(n=Count('id')):
        status_counts[row['status']] = row['n']

    return {
        'total_documents': docs.count(),
        'published_count': status_counts['published'],
        'draft_count': status_counts['draft'],
        'policy_count': docs.filter(category='policy').count(),
        'template_count': templates.count(),
        'index_pct': index_pct,
        'pending_index_count': versions.filter(index_status__in=('pending', 'failed')).count(),
        'cat_labels': [cat_map[k] for k in cat_map],
        'cat_data': [cat_counts[k] for k in cat_map],
        'status_labels': ['Draft', 'Published', 'Archived'],
        'status_data': [status_counts['draft'], status_counts['published'],
                        status_counts['archived']],
        'recent_documents': list(
            docs.select_related('owner').order_by('-created_at')[:8]),
    }


# ---------------------------------------------------------------------------
# Export rows
# ---------------------------------------------------------------------------
def document_export_rows(tenant):
    """Header + rows for the document CSV export."""
    header = ['Number', 'Title', 'Category', 'Status', 'Confidentiality', 'Owner', 'Versions',
              'Current version', 'Created']
    rows = []
    for d in (Document.all_objects.filter(tenant=tenant)
              .select_related('owner', 'current_version').order_by('-created_at')):
        rows.append([
            d.document_number, d.title, d.get_category_display(), d.get_status_display(),
            d.get_confidentiality_display(),
            (d.owner.get_full_name() or d.owner.username) if d.owner else '',
            d.versions.count(),
            f'v{d.current_version.version_no}' if d.current_version_id else '',
            d.created_at.isoformat(),
        ])
    return header, rows


# ---------------------------------------------------------------------------
# Cron sweep (re-index pending text)
# ---------------------------------------------------------------------------
def reindex_all_tenants():
    """Sweep every tenant, indexing pending/failed versions. Returns per-tenant results by slug."""
    results = {}
    for t in Tenant.objects.all():
        set_current_tenant(t)
        results[t.slug] = extract_pending(t)
    set_current_tenant(None)
    return results
