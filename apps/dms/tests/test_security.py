"""Security tests: RBAC + cross-tenant isolation."""
import pytest
from django.urls import reverse

from apps.dms.models import Document, PolicyTemplate

pytestmark = pytest.mark.django_db


def test_requester_is_bounced_from_view_and_manage(client, data, requester):
    """A requester holds neither view nor manage rights (the D-01 lesson)."""
    client.force_login(requester)
    assert client.get(reverse('dms:dashboard')).status_code == 302
    # manage action refused (and nothing created)
    before = Document.objects.count()
    resp = client.post(reverse('dms:document_create'), {
        'title': 'Sneaky', 'category': 'other', 'confidentiality': 'internal'})
    assert resp.status_code == 302
    assert Document.objects.count() == before


def test_approver_can_view_but_not_manage(client, data, approver):
    client.force_login(approver)
    assert client.get(reverse('dms:document_list')).status_code == 200
    assert client.get(reverse('dms:search')).status_code == 200
    before = PolicyTemplate.objects.count()
    resp = client.post(reverse('dms:policy_template_create'), {
        'title': 'X', 'category': 'other', 'body': 'y'})
    assert resp.status_code == 302
    assert PolicyTemplate.objects.count() == before


def test_cross_tenant_document_is_isolated(client, data, intruder):
    client.force_login(intruder)  # admin of a different tenant
    assert client.get(
        reverse('dms:document_detail', args=[data.pub.pk])).status_code == 404
    # and cannot download another tenant's file
    version = data.pub.current_version
    assert client.get(
        reverse('dms:version_download', args=[data.pub.pk, version.pk])).status_code == 404


def test_cross_tenant_template_is_isolated(client, data, intruder):
    client.force_login(intruder)
    assert client.get(
        reverse('dms:policy_template_detail', args=[data.tmpl.pk])).status_code == 404


def test_cross_tenant_document_not_listed(client, data, intruder):
    """Intruder's own (empty) list must not leak the other tenant's documents."""
    client.force_login(intruder)
    resp = client.get(reverse('dms:document_list'))
    assert resp.status_code == 200
    assert data.pub not in list(resp.context['documents'])
