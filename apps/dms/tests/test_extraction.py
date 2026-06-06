"""Pluggable text-extraction connector tests: mock determinism, registry fallback, SSRF guard."""
import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.dms import extraction

pytestmark = pytest.mark.django_db


def _f(body=b'Approval limit 1000. ISO 9001.'):
    return SimpleUploadedFile('a.txt', body, content_type='text/plain')


def test_mock_extracts_text():
    result = extraction.MockTextExtractionProvider().extract(_f())
    assert result.ok is True
    assert result.provider == 'mock'
    assert 'Approval limit' in result.text
    assert result.page_count >= 1


def test_mock_is_deterministic():
    a = extraction.MockTextExtractionProvider().extract(_f(b'same bytes'))
    b = extraction.MockTextExtractionProvider().extract(_f(b'same bytes'))
    assert a.text == b.text


def test_mock_binary_degrades_to_stub():
    result = extraction.MockTextExtractionProvider().extract(
        SimpleUploadedFile('x.bin', b'\x00\x01\x02', content_type='application/octet-stream'))
    assert result.ok is True
    assert result.text  # a stable stub, never empty


def test_registry_default_is_mock(settings):
    settings.DMS_EXTRACTION_ENGINE = 'mock'
    assert isinstance(extraction.get_text_extraction_provider(),
                      extraction.MockTextExtractionProvider)


def test_registry_unknown_falls_back_to_mock():
    provider = extraction.get_text_extraction_provider('nonexistent-engine')
    assert isinstance(provider, extraction.MockTextExtractionProvider)


def test_registry_local_resolves():
    assert isinstance(extraction.get_text_extraction_provider('local'),
                      extraction.LocalPdfTextExtractionProvider)


def test_local_extracts_text_file():
    result = extraction.LocalPdfTextExtractionProvider().extract(_f(b'plain text body'))
    assert result.ok is True
    assert 'plain text body' in result.text


def test_max_chars_caps_text(settings):
    settings.DMS_MAX_INDEX_CHARS = 10
    result = extraction.MockTextExtractionProvider().extract(_f(b'x' * 100))
    assert len(result.text) <= 10


# ---------- SSRF guard (for a future remote extractor) ----------
def test_validate_extraction_url_rejects_non_https():
    with pytest.raises(ValidationError):
        extraction.validate_extraction_url('http://example.com/extract')


def test_validate_extraction_url_rejects_internal_ip():
    with pytest.raises(ValidationError):
        extraction.validate_extraction_url('https://127.0.0.1/extract')
    with pytest.raises(ValidationError):
        extraction.validate_extraction_url('https://10.0.0.1/extract')


def test_validate_extraction_url_allowlist_short_circuits(settings):
    # allowlisted host returns without DNS resolution
    settings.DMS_EXTRACTION_ALLOWLIST = 'tika.internal'
    assert extraction.validate_extraction_url('https://tika.internal/extract') \
        == 'https://tika.internal/extract'
