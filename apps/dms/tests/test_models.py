"""Model-level tests: numbering uniqueness, choice props, version control invariants."""
import pytest
from django.db import IntegrityError

from apps.dms.models import Document, DocumentVersion, PolicyTemplate

pytestmark = pytest.mark.django_db


def test_document_number_unique_per_tenant(tenant):
    Document.all_objects.create(tenant=tenant, document_number='DOC-1', title='A')
    with pytest.raises(IntegrityError):
        Document.all_objects.create(tenant=tenant, document_number='DOC-1', title='B')


def test_same_document_number_ok_across_tenants(tenant, other_tenant):
    Document.all_objects.create(tenant=tenant, document_number='DOC-1', title='A')
    # different tenant, same number — allowed
    assert Document.all_objects.create(
        tenant=other_tenant, document_number='DOC-1', title='B').pk


def test_version_unique_per_document(tenant):
    doc = Document.all_objects.create(tenant=tenant, document_number='DOC-1', title='A')
    DocumentVersion.all_objects.create(tenant=tenant, document=doc, version_no=1)
    with pytest.raises(IntegrityError):
        DocumentVersion.all_objects.create(tenant=tenant, document=doc, version_no=1)


def test_status_color_and_editable(tenant):
    doc = Document.all_objects.create(
        tenant=tenant, document_number='DOC-1', title='A', status='published')
    assert doc.status_color == 'success'
    assert doc.is_editable is True
    assert doc.is_published is True
    doc.status = 'archived'
    assert doc.is_editable is False


def test_confidentiality_color(tenant):
    doc = Document.all_objects.create(
        tenant=tenant, document_number='DOC-1', title='A', confidentiality='restricted')
    assert doc.confidentiality_color == 'danger'


def test_is_current_property(data):
    version = data.pub.current_version
    assert version is not None
    assert version.is_current is True


def test_template_unique_number(tenant):
    PolicyTemplate.all_objects.create(tenant=tenant, template_number='TPL-1', title='A', body='x')
    with pytest.raises(IntegrityError):
        PolicyTemplate.all_objects.create(tenant=tenant, template_number='TPL-1', title='B', body='y')


def test_version_index_color(tenant):
    doc = Document.all_objects.create(tenant=tenant, document_number='DOC-1', title='A')
    v = DocumentVersion.all_objects.create(
        tenant=tenant, document=doc, version_no=1, index_status='indexed')
    assert v.index_color == 'success'
