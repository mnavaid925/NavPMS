"""File-upload validators for Module 10 (Catalog Management).

The wider codebase had no file-size validator before Module 10 — the contracts
``ContractDocumentForm`` enforced size/extension inline. Supplier catalog hosting
needs the same guard on a model ``FileField`` (so it fires on every save, not just
one form), so the size check is promoted to a reusable validator here and paired
with Django's built-in ``FileExtensionValidator``.
"""
from django.core.exceptions import ValidationError

# Supplier catalog files are spreadsheets — keep them small and well-typed.
CATALOG_UPLOAD_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
CATALOG_UPLOAD_EXTENSIONS = ('csv', 'xlsx')


def validate_upload_size(f):
    """Reject an uploaded file larger than :data:`CATALOG_UPLOAD_MAX_BYTES`."""
    if f and getattr(f, 'size', 0) > CATALOG_UPLOAD_MAX_BYTES:
        mb = CATALOG_UPLOAD_MAX_BYTES // (1024 * 1024)
        raise ValidationError(f'File size must be {mb} MB or less.')
