"""Service-layer tests: numbering, indexing, version control, search, cloning."""
import pytest

from apps.dms import services
from apps.dms.models import Document, DocumentVersion, PolicyTemplate
from apps.dms.tests.conftest import upload

pytestmark = pytest.mark.django_db


def test_next_number_gap_free(tenant):
    n1 = services.next_document_number(tenant)
    Document.all_objects.create(tenant=tenant, document_number=n1, title='A')
    n2 = services.next_document_number(tenant)
    assert n1 != n2
    assert n1.startswith('DOC-ACME-')
    assert services.next_template_number(tenant).startswith('TPL-ACME-')


def test_create_document_version_indexes_text(tenant, tenant_admin):
    doc = services.create_document(tenant, title='Spec', category='spec', user=tenant_admin)
    version = services.create_document_version(
        doc, upload('s.txt', b'Warranty is 36 months. ISO 9001 certified.'), tenant_admin)
    version.refresh_from_db()
    assert version.index_status == 'indexed'
    assert 'Warranty' in version.extracted_text
    assert version.extraction_engine == 'mock'
    assert version.page_count >= 1


def test_publish_version_supersedes_prior(tenant, tenant_admin):
    doc = services.create_document(tenant, title='Doc', category='other', user=tenant_admin)
    v1 = services.create_document_version(doc, upload('v1.txt', b'first'), tenant_admin, publish=True)
    v2 = services.create_document_version(doc, upload('v2.txt', b'second'), tenant_admin, publish=True)
    v1.refresh_from_db()
    v2.refresh_from_db()
    doc.refresh_from_db()
    assert v1.status == 'superseded'
    assert v2.status == 'published'
    assert doc.current_version_id == v2.pk
    assert doc.status == 'published'


def test_search_documents_finds_text(data, tenant):
    # 'ISO 9001' appears only inside the published policy file's extracted text
    hits = services.search_documents(tenant, 'ISO 9001')
    assert any(h['document'].pk == data.pub.pk for h in hits)
    # snippet carries the matched context
    hit = next(h for h in hits if h['document'].pk == data.pub.pk)
    assert 'ISO' in hit['snippet']


def test_search_empty_query_returns_nothing(data, tenant):
    assert services.search_documents(tenant, '') == []


def test_search_respects_category_filter(data, tenant):
    assert services.search_documents(tenant, 'warranty', category='policy') == []
    assert services.search_documents(tenant, 'warranty', category='spec')


def test_set_document_status_archives(data, tenant, tenant_admin):
    services.set_document_status(data.pub, 'archived', tenant_admin)
    data.pub.refresh_from_db()
    assert data.pub.status == 'archived'
    assert data.pub.events.filter(event='status_changed', to_status='archived').exists()


def test_clone_template_to_document(data, tenant, tenant_admin):
    before = Document.all_objects.filter(tenant=tenant).count()
    doc = services.clone_template_to_document(data.tmpl, tenant_admin)
    assert Document.all_objects.filter(tenant=tenant).count() == before + 1
    assert doc.current_version is not None  # cloned + published
    assert doc.status == 'published'
    assert '1. Scope' in doc.current_version.extracted_text


def test_extract_pending_reindexes(tenant, tenant_admin):
    doc = services.create_document(tenant, title='Doc', category='other', user=tenant_admin)
    v = services.create_document_version(doc, upload('a.txt', b'hello'), tenant_admin)
    DocumentVersion.all_objects.filter(pk=v.pk).update(index_status='pending', extracted_text='')
    result = services.extract_pending(tenant)
    assert result['indexed'] >= 1
    v.refresh_from_db()
    assert v.index_status == 'indexed'


def test_permission_helpers(tenant_admin, approver, requester):
    assert services.can_manage_documents(tenant_admin) is True
    assert services.can_view_documents(approver) is True
    assert services.can_manage_documents(approver) is False
    assert services.can_view_documents(requester) is False


def test_create_document_records_event_and_number(tenant, tenant_admin):
    doc = services.create_document(tenant, title='X', category='other', user=tenant_admin)
    assert doc.document_number.startswith('DOC-ACME-')
    assert doc.events.filter(event='created').exists()
