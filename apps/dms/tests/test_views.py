"""View-level tests: pages load, CRUD, upload/index/publish/download, search, export."""
import pytest
from django.urls import reverse

from apps.dms.models import Document, DocumentVersion, PolicyTemplate
from apps.dms.tests.conftest import upload

pytestmark = pytest.mark.django_db


def test_read_pages_load(client, data, tenant_admin):
    client.force_login(tenant_admin)
    for name in ['dms:dashboard', 'dms:document_list', 'dms:policy_library', 'dms:search',
                 'dms:policy_template_list']:
        assert client.get(reverse(name)).status_code == 200
    assert client.get(reverse('dms:document_detail', args=[data.pub.pk])).status_code == 200
    assert client.get(
        reverse('dms:policy_template_detail', args=[data.tmpl.pk])).status_code == 200


def test_document_crud(client, tenant, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('dms:document_create'), {
        'title': 'New Spec', 'category': 'spec', 'confidentiality': 'internal'})
    assert resp.status_code == 302
    doc = Document.objects.get(tenant=tenant, title='New Spec')
    resp = client.post(reverse('dms:document_edit', args=[doc.pk]), {
        'title': 'New Spec v2', 'category': 'spec', 'confidentiality': 'public'})
    assert resp.status_code == 302
    doc.refresh_from_db()
    assert doc.title == 'New Spec v2'
    assert client.post(reverse('dms:document_delete', args=[doc.pk])).status_code == 302
    assert not Document.objects.filter(pk=doc.pk).exists()


def test_version_upload_indexes_and_publishes(client, tenant, tenant_admin):
    client.force_login(tenant_admin)
    doc = Document.all_objects.create(
        tenant=tenant, document_number='DOC-ACME-90001', title='Doc')
    resp = client.post(reverse('dms:version_create', args=[doc.pk]), {
        'file': upload('u.txt', b'Net 30 payment terms apply.'), 'publish': 'on'})
    assert resp.status_code == 302
    version = DocumentVersion.objects.get(document=doc, version_no=1)
    assert version.index_status == 'indexed'
    assert 'Net 30' in version.extracted_text
    doc.refresh_from_db()
    assert doc.current_version_id == version.pk
    assert doc.status == 'published'


def test_version_publish_and_reindex_actions(client, data, tenant_admin):
    client.force_login(tenant_admin)
    version = data.draft.versions.first()  # the unpublished draft version
    resp = client.post(
        reverse('dms:version_publish', args=[data.draft.pk, version.pk]))
    assert resp.status_code == 302
    data.draft.refresh_from_db()
    assert data.draft.current_version_id == version.pk
    assert client.post(
        reverse('dms:version_reindex', args=[data.draft.pk, version.pk])).status_code == 302


def test_version_download(client, data, tenant_admin):
    client.force_login(tenant_admin)
    version = data.pub.current_version
    resp = client.get(reverse('dms:version_download', args=[data.pub.pk, version.pk]))
    assert resp.status_code == 200
    assert 'attachment' in resp['Content-Disposition']


def test_search_view(client, data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.get(reverse('dms:search'), {'q': 'ISO 9001'})
    assert resp.status_code == 200
    assert resp.context['result_count'] >= 1


def test_document_set_status(client, data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('dms:document_set_status', args=[data.pub.pk]),
                       {'status': 'archived'})
    assert resp.status_code == 302
    data.pub.refresh_from_db()
    assert data.pub.status == 'archived'


def test_template_crud_and_clone(client, tenant, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('dms:policy_template_create'), {
        'title': 'Negotiation Guide', 'category': 'negotiation', 'body': 'Anchor high.'})
    assert resp.status_code == 302
    tmpl = PolicyTemplate.objects.get(tenant=tenant, title='Negotiation Guide')
    # clone produces a document and redirects to it
    resp = client.post(reverse('dms:policy_template_clone', args=[tmpl.pk]))
    assert resp.status_code == 302
    assert Document.objects.filter(tenant=tenant, title__icontains='Negotiation Guide').exists()
    assert client.post(reverse('dms:policy_template_delete', args=[tmpl.pk])).status_code == 302


def test_document_export_csv(client, data, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.get(reverse('dms:document_export'))
    assert resp.status_code == 200
    assert resp['Content-Type'].startswith('text/csv')


def test_login_required(client):
    resp = client.get(reverse('dms:dashboard'))
    assert resp.status_code == 302
    assert '/accounts/login' in resp['Location']
