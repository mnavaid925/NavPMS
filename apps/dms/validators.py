"""File-upload validators for Module 20 (Document & Knowledge Management).

Mirrors ``apps/catalog/validators.py``: a reusable size guard paired with Django's built-in
``FileExtensionValidator`` on the model ``FileField`` so the check rides along with every
``ModelForm`` validation. The size cap is env-driven (``DMS_UPLOAD_MAX_MB``) so an operator can
loosen it without a code change.

NOTE (extension + size only): like the rest of the codebase there is no MIME sniffing here — the
extension allowlist plus the size cap are the guard. The pluggable text-extraction connector
(``extraction.py``) reads the stored bytes locally, never executing them.
"""
from django.conf import settings
from django.core.exceptions import ValidationError

# Procurement documents are office files — keep them reasonably small and well-typed.
DOCUMENT_UPLOAD_EXTENSIONS = ('pdf', 'doc', 'docx', 'txt', 'md', 'rtf', 'csv', 'xlsx')


def _max_bytes():
    mb = getattr(settings, 'DMS_UPLOAD_MAX_MB', 10) or 10
    return int(mb) * 1024 * 1024


def validate_upload_size(f):
    """Reject an uploaded file larger than ``DMS_UPLOAD_MAX_MB`` megabytes."""
    limit = _max_bytes()
    if f and getattr(f, 'size', 0) > limit:
        raise ValidationError(f'File size must be {limit // (1024 * 1024)} MB or less.')
