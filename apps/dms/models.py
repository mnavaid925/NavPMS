"""Module 20: Document & Knowledge Management.

The knowledge layer over the procure-to-pay loop. Where the other modules *transact*, this one
*remembers*: it is the central, versioned, searchable home for every procurement document (quotes,
specs, warranties, SOPs), a curated policy library, a best-practice template library, and full-text
search over the text extracted from uploaded files.

Covers the five PMS sub-modules:
  1. Central Document Repository   -> Document (the logical record) + DocumentVersion (the file),
                                      organized by a ``category`` and a ``confidentiality`` band.
  2. Version Control               -> DocumentVersion (numbered, immutable file rows). Publishing a
                                      version supersedes the previous one and re-points
                                      ``Document.current_version`` so only the latest published
                                      version is the current/downloadable one (the compliance.Policy
                                      precedent), with an append-only DocumentEvent timeline.
  3. Procurement Policy Library    -> Documents filtered to ``category='policy'`` (a library view);
                                      cross-links to ``compliance.Policy`` (which owns sign-off /
                                      acknowledgment) rather than duplicating it.
  4. Best Practices & Templates    -> PolicyTemplate — authored reusable bodies (RFP skeletons, bid
                                      evaluation guides) that clone into a real Document on demand.
  5. Full-Text Search & Indexing   -> DocumentVersion.extracted_text, populated by the pluggable
                                      ``apps/dms/extraction.py`` connector and queried by
                                      ``services.search_documents``.

DESIGN — self-contained, mirroring the Module 18 (compliance) conventions: TenantAwareModel +
TimeStampedModel bases, module-level choice constants re-exposed on the model, gap-free
``DOC-`` / ``TPL-<SLUG>-NNNNN`` numbering (minted in services.py), a ``current_version`` pointer, and
an append-only event timeline. The uploaded file *and* its searchable extracted text live on the
version row — never on the parent — so making a version "current" is a cheap pointer swap.
"""
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

from apps.core.models import TenantAwareModel, TimeStampedModel

from .validators import DOCUMENT_UPLOAD_EXTENSIONS, validate_upload_size


# ---------------------------------------------------------------------------
# Module-level choice constants + colour maps
# ---------------------------------------------------------------------------
DOC_CATEGORY_CHOICES = [
    ('quote', 'Quote / Proposal'),
    ('spec', 'Specification'),
    ('warranty', 'Warranty / Guarantee'),
    ('contract', 'Contract / Legal'),
    ('policy', 'Procurement Policy'),
    ('sop', 'SOP / Procedure'),
    ('other', 'Other'),
]
DOC_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('published', 'Published'),
    ('archived', 'Archived'),
]
DOC_EDITABLE_STATUSES = ('draft', 'published')
CONFIDENTIALITY_CHOICES = [
    ('public', 'Public'),
    ('internal', 'Internal'),
    ('restricted', 'Restricted'),
]

VERSION_STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('published', 'Published'),
    ('superseded', 'Superseded'),
]
INDEX_STATUS_CHOICES = [
    ('pending', 'Pending extraction'),
    ('indexed', 'Indexed'),
    ('failed', 'Extraction failed'),
    ('unsupported', 'Unsupported type'),
]

TEMPLATE_CATEGORY_CHOICES = [
    ('rfp', 'RFP / RFQ'),
    ('rfi', 'RFI'),
    ('evaluation', 'Bid Evaluation'),
    ('negotiation', 'Negotiation'),
    ('sop', 'SOP / Procedure'),
    ('other', 'Other'),
]

DOC_STATUS_COLORS = {'draft': 'secondary', 'published': 'success', 'archived': 'dark'}
CONFIDENTIALITY_COLORS = {'public': 'success', 'internal': 'info', 'restricted': 'danger'}
INDEX_STATUS_COLORS = {
    'pending': 'secondary', 'indexed': 'success', 'failed': 'danger', 'unsupported': 'warning',
}
VERSION_STATUS_COLORS = {'draft': 'secondary', 'published': 'success', 'superseded': 'dark'}


# ---------------------------------------------------------------------------
# 1. Central Document Repository
# ---------------------------------------------------------------------------
class Document(TenantAwareModel, TimeStampedModel):
    """A logical procurement document — the container its versioned files hang off.

    The actual file bytes + searchable extracted text live on :class:`DocumentVersion` rows;
    ``current_version`` points at the latest *published* one (the only version end-users download).
    """

    CATEGORY_CHOICES = DOC_CATEGORY_CHOICES
    STATUS_CHOICES = DOC_STATUS_CHOICES
    CONFIDENTIALITY_CHOICES = CONFIDENTIALITY_CHOICES

    document_number = models.CharField(max_length=40, help_text='Auto DOC-<SLUG>-NNNNN.')
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=16, choices=DOC_CATEGORY_CHOICES, default='other')
    status = models.CharField(max_length=10, choices=DOC_STATUS_CHOICES, default='draft')
    confidentiality = models.CharField(
        max_length=12, choices=CONFIDENTIALITY_CHOICES, default='internal',
        help_text='Access sensitivity — restricted documents are owner/manager only.',
    )
    summary = models.TextField(blank=True)
    tags = models.CharField(
        max_length=255, blank=True, help_text='Comma-separated keywords for discovery / search.',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='documents_owned',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='documents_created',
    )
    current_version = models.ForeignKey(
        'dms.DocumentVersion', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='current_for', help_text='The published version end-users access.',
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'document_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'category']),
        ]

    def __str__(self):
        return f'{self.document_number} — {self.title[:50]}'

    @property
    def status_color(self):
        return DOC_STATUS_COLORS.get(self.status, 'secondary')

    @property
    def confidentiality_color(self):
        return CONFIDENTIALITY_COLORS.get(self.confidentiality, 'secondary')

    @property
    def is_editable(self):
        return self.status in DOC_EDITABLE_STATUSES

    @property
    def is_published(self):
        return self.status == 'published'

    @property
    def version_count(self):
        return self.versions.count()


class DocumentVersion(TenantAwareModel, TimeStampedModel):
    """One immutable uploaded file revision of a :class:`Document`.

    The uploaded ``file`` is parsed by the pluggable extraction connector into ``extracted_text`` —
    the field the full-text search queries. Publishing a version supersedes its predecessors.
    """

    STATUS_CHOICES = VERSION_STATUS_CHOICES
    INDEX_STATUS_CHOICES = INDEX_STATUS_CHOICES

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='versions')
    version_no = models.PositiveIntegerField(default=1)
    file = models.FileField(
        upload_to='dms_documents/%Y/%m/',
        validators=[FileExtensionValidator(allowed_extensions=list(DOCUMENT_UPLOAD_EXTENSIONS)),
                    validate_upload_size],
    )
    original_filename = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(default=0, help_text='Bytes.')
    content_type = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=12, choices=VERSION_STATUS_CHOICES, default='draft')
    change_note = models.CharField(max_length=255, blank=True)

    # Full-text index fields (populated by extraction.py via services.index_version).
    extracted_text = models.TextField(blank=True, help_text='The searchable extracted text.')
    index_status = models.CharField(
        max_length=12, choices=INDEX_STATUS_CHOICES, default='pending')
    page_count = models.PositiveIntegerField(default=0)
    extraction_engine = models.CharField(max_length=20, blank=True)
    extracted_at = models.DateTimeField(null=True, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='document_versions_uploaded',
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='document_versions_published',
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-version_no']
        unique_together = [('document', 'version_no')]
        indexes = [
            models.Index(fields=['tenant', 'index_status']),
            models.Index(fields=['tenant', 'status']),
        ]

    def __str__(self):
        return f'{self.document_id} v{self.version_no} [{self.index_status}]'

    @property
    def status_color(self):
        return VERSION_STATUS_COLORS.get(self.status, 'secondary')

    @property
    def index_color(self):
        return INDEX_STATUS_COLORS.get(self.index_status, 'secondary')

    @property
    def is_current(self):
        return self.document.current_version_id == self.pk


# ---------------------------------------------------------------------------
# 4. Best Practices & Templates
# ---------------------------------------------------------------------------
class PolicyTemplate(TenantAwareModel, TimeStampedModel):
    """A reusable best-practice template (RFP skeleton, bid-evaluation guide, negotiation playbook).

    Authored as text in-app; ``services.clone_template_to_document`` stamps a copy into a real
    :class:`Document` (as its first published version) so teams start from the house standard.
    """

    CATEGORY_CHOICES = TEMPLATE_CATEGORY_CHOICES
    STATUS_CHOICES = DOC_STATUS_CHOICES

    template_number = models.CharField(max_length=40, help_text='Auto TPL-<SLUG>-NNNNN.')
    title = models.CharField(max_length=200)
    category = models.CharField(
        max_length=16, choices=TEMPLATE_CATEGORY_CHOICES, default='other')
    description = models.TextField(blank=True)
    body = models.TextField(help_text='The reusable template content.')
    status = models.CharField(max_length=10, choices=DOC_STATUS_CHOICES, default='draft')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='document_templates_owned',
    )

    class Meta:
        ordering = ['-created_at']
        unique_together = [('tenant', 'template_number')]
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'category']),
        ]

    def __str__(self):
        return f'{self.template_number} — {self.title[:50]}'

    @property
    def status_color(self):
        return DOC_STATUS_COLORS.get(self.status, 'secondary')

    @property
    def is_editable(self):
        return self.status in DOC_EDITABLE_STATUSES


# ---------------------------------------------------------------------------
# Append-only document timeline (Version Control auditability)
# ---------------------------------------------------------------------------
class DocumentEvent(TenantAwareModel, TimeStampedModel):
    """An immutable entry in a document's lifecycle timeline (create / upload / publish / status)."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='events')
    version = models.ForeignKey(
        DocumentVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    event = models.CharField(max_length=30, help_text='created / version_uploaded / '
                                                       'version_published / status_changed / indexed.')
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12, blank=True)
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='document_events',
    )

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['tenant', 'document']),
        ]

    def __str__(self):
        return f'{self.document_id}: {self.event}'
