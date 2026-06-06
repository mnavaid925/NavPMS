"""Pluggable text-extraction connector registry (Module 20, sub-module 5: Full-Text Search).

Mirrors the screening (``apps/compliance/screening.py``), OCR (``apps/invoicing/ocr.py``) and
freight-carrier (``apps/fulfillment/carriers.py``) patterns: a base provider + a
``_TEXT_EXTRACTION_REGISTRY`` + an env-selectable default (``settings.DMS_EXTRACTION_ENGINE``).

Two bundled providers:
  * ``mock``  (default) — reads the uploaded file's bytes locally and returns deterministic text
    (decoding UTF-8 for ``.txt`` / ``.md`` / ``.csv`` etc.; a binary degrades to a stable stub).
    NO extra dependency, so the index-and-search flow works out of the box and in CI.
  * ``local`` — real extraction: ``pypdf`` pulls text out of PDFs (with ``page_count``); text files
    decode as above. Enable with ``DMS_EXTRACTION_ENGINE=local`` after ``pip install pypdf``.

Register a hosted backend (Apache Tika / AWS Textract / a cloud OCR endpoint) with one line:
``_TEXT_EXTRACTION_REGISTRY['tika'] = TikaTextExtractionProvider``.

SECURITY (flagged per the project vulnerability rule):
    The bundled providers are LOCAL — they read already-stored bytes and make NO network call, so
    they have no SSRF surface and need no URL guard. A REAL *hosted* extractor would POST the file
    to a config-supplied endpoint server-side; that URL MUST be SSRF-validated first. Use
    :func:`validate_extraction_url` (fail-closed: HTTPS-only, reject raw internal IP literals,
    resolve hostnames and block any non-routable address, honouring
    ``settings.DMS_EXTRACTION_ALLOWLIST``) and never request an unvalidated URL.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Result value object
# ---------------------------------------------------------------------------
@dataclass
class ExtractionResult:
    ok: bool = True
    provider: str = 'mock'
    text: str = ''
    page_count: int = 0
    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SSRF guard (fail-closed) — for a future real HTTP extraction connector
# ---------------------------------------------------------------------------
def _allowlist():
    raw = getattr(settings, 'DMS_EXTRACTION_ALLOWLIST', '') or ''
    return {h.strip().lower() for h in raw.split(',') if h.strip()}


def _is_blocked_ip(ip_str):
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable — treat as unsafe
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def validate_extraction_url(url):
    """Raise ``ValidationError`` unless ``url`` is a safe outbound HTTPS target.

    WARNING (SSRF): a hosted extractor endpoint is config-supplied and requested server-side.
    Without this guard an attacker could point it at ``http://169.254.169.254/`` or an internal
    host. Secure pattern: HTTPS-only, reject raw internal IP literals, resolve hostnames — blocking
    any that map to a non-routable address. Fail closed. (Unused by the bundled local/mock
    providers, which make no network calls.)
    """
    parsed = urlparse((url or '').strip())
    if parsed.scheme != 'https':
        raise ValidationError('Extraction URL must use HTTPS.')
    host = parsed.hostname
    if not host:
        raise ValidationError('Extraction URL has no host.')
    if host.lower() in _allowlist():
        return url
    try:
        ipaddress.ip_address(host)
        if _is_blocked_ip(host):
            raise ValidationError('Extraction URL host is not a routable address.')
        return url
    except ValueError:
        pass  # hostname — resolve it
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValidationError('Extraction URL host could not be resolved.')
    for info in infos:
        if _is_blocked_ip(info[4][0]):
            raise ValidationError('Extraction URL resolves to a non-routable address.')
    return url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _max_chars():
    return int(getattr(settings, 'DMS_MAX_INDEX_CHARS', 200000) or 200000)


def _cap(text):
    """Trim indexed text so a huge PDF cannot bloat the row / search index."""
    limit = _max_chars()
    text = text or ''
    return text[:limit] if len(text) > limit else text


def _read_bytes(file_obj):
    """Read a Django FieldFile / uploaded file's bytes, restoring the pointer."""
    if file_obj is None:
        return b''
    try:
        if hasattr(file_obj, 'open'):
            file_obj.open('rb')
        data = file_obj.read()
        if hasattr(file_obj, 'seek'):
            try:
                file_obj.seek(0)
            except Exception:
                pass
        return data or b''
    except Exception:
        return b''


def _filename(file_obj):
    return (getattr(file_obj, 'name', '') or '').lower()


def _decode_text(data):
    try:
        return data.decode('utf-8', errors='ignore')
    except Exception:
        return ''


# ---------------------------------------------------------------------------
# Connector base
# ---------------------------------------------------------------------------
class TextExtractionProvider:
    name: str = 'base'

    def extract(self, file_obj, *, content_type=None) -> ExtractionResult:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Mock provider (deterministic, no deps, no network)
# ---------------------------------------------------------------------------
class MockTextExtractionProvider:
    """Decodes the uploaded bytes locally. Text files index verbatim; a binary degrades to a stable
    stub so the index-and-search flow still completes with no backend installed. Deterministic."""

    name = 'mock'

    def extract(self, file_obj, *, content_type=None):
        data = _read_bytes(file_obj)
        if not data:
            return ExtractionResult(ok=False, provider=self.name, raw={'error': 'unreadable'})
        text = _decode_text(data).strip()
        if not text:
            text = f'[extracted:{self.name}] {_filename(file_obj) or "document"}'
        page_count = max(1, text.count('\f') + 1)
        return ExtractionResult(
            ok=True, provider=self.name, text=_cap(text), page_count=page_count,
            raw={'bytes': len(data)})


# ---------------------------------------------------------------------------
# Local provider (real PDF text via pypdf; text files decode)
# ---------------------------------------------------------------------------
class LocalPdfTextExtractionProvider:
    """Real local extraction: ``pypdf`` for PDFs, UTF-8 decode for text-like files.

    No network — operates on the already-stored bytes. Falls back to ``ok=False`` (so the row is
    flagged ``failed``) if ``pypdf`` is missing or the PDF cannot be parsed, leaving the document
    re-indexable later via ``reindex_documents``.
    """

    name = 'local'

    def extract(self, file_obj, *, content_type=None):
        name = _filename(file_obj)
        if name.endswith('.pdf'):
            return self._extract_pdf(file_obj)
        data = _read_bytes(file_obj)
        if not data:
            return ExtractionResult(ok=False, provider=self.name, raw={'error': 'unreadable'})
        text = _decode_text(data).strip()
        if not text:
            return ExtractionResult(ok=False, provider=self.name,
                                    raw={'error': 'no decodable text'})
        return ExtractionResult(ok=True, provider=self.name, text=_cap(text),
                                page_count=max(1, text.count('\f') + 1), raw={'bytes': len(data)})

    def _extract_pdf(self, file_obj):
        try:
            from pypdf import PdfReader
        except ImportError:
            return ExtractionResult(
                ok=False, provider=self.name,
                raw={'error': 'pypdf not installed — pip install pypdf or set DMS_EXTRACTION_ENGINE=mock'})
        try:
            if hasattr(file_obj, 'open'):
                file_obj.open('rb')
            reader = PdfReader(file_obj)
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or '')
            if hasattr(file_obj, 'seek'):
                try:
                    file_obj.seek(0)
                except Exception:
                    pass
            text = '\n'.join(parts).strip()
            return ExtractionResult(
                ok=True, provider=self.name, text=_cap(text), page_count=len(reader.pages),
                raw={'pages': len(reader.pages)})
        except Exception as exc:  # pragma: no cover - depends on the uploaded file
            return ExtractionResult(ok=False, provider=self.name, raw={'error': str(exc)[:200]})


# ---------------------------------------------------------------------------
# Registry + env-selectable getter
# ---------------------------------------------------------------------------
_TEXT_EXTRACTION_REGISTRY = {
    'mock': MockTextExtractionProvider,
    'local': LocalPdfTextExtractionProvider,
}


def get_text_extraction_provider(name=None):
    """Return a provider instance for ``name`` (or the env default).

    Unknown names fall back to the mock provider, mirroring the screening / carrier / gateway
    registries — a typo in the env var degrades gracefully rather than 500-ing every upload.
    """
    key = (name or getattr(settings, 'DMS_EXTRACTION_ENGINE', 'mock') or 'mock')
    cls = _TEXT_EXTRACTION_REGISTRY.get(key, MockTextExtractionProvider)
    return cls()
