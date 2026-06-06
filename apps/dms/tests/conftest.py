"""Shared fixtures for Module 20 (Document & Knowledge Management) tests.

``build_documents`` creates a published document (with an indexed, published version), a draft
document (unpublished version), and a best-practice template — enough to exercise listing, version
control, search and cloning. Each fixture CREATES its own data (never mutates another) per
lessons.md, using ``.all_objects`` / the service layer and an autouse reset of the thread-local
tenant. ``_tmp_media`` points MEDIA_ROOT at a per-test temp dir so uploads never touch the repo.
"""
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant

from apps.dms import services
from apps.dms.models import PolicyTemplate


@pytest.fixture(autouse=True)
def _reset_tenant():
    yield
    set_current_tenant(None)


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    """Isolate uploaded files to a temp dir per test (no media/ pollution)."""
    settings.MEDIA_ROOT = str(tmp_path)


# ---------- Tenants & users ----------
@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name='Acme Co', slug='acme')


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name='Globex', slug='globex')


@pytest.fixture
def tenant_admin(db, tenant):
    return User.objects.create_user(
        username='admin_acme', password='x', tenant=tenant,
        role='tenant_admin', is_tenant_admin=True, email='ada@acme.test')


@pytest.fixture
def buyer_user(db, tenant):
    return User.objects.create_user(username='buyer', password='x', tenant=tenant, role='buyer')


@pytest.fixture
def approver(db, tenant):
    """View-only role: may view documents but not manage."""
    return User.objects.create_user(
        username='approver_user', password='x', tenant=tenant, role='approver')


@pytest.fixture
def requester(db, tenant):
    """Neither manage nor view — bounced from every page (the D-01 lesson)."""
    return User.objects.create_user(
        username='requester', password='x', tenant=tenant, role='requester')


@pytest.fixture
def intruder(db, other_tenant):
    """Tenant admin of a DIFFERENT tenant — used for cross-tenant isolation."""
    return User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant,
        role='tenant_admin', is_tenant_admin=True, email='m@globex.test')


# ---------- Helpers ----------
def upload(name='policy.txt', body=b'Procurement policy: approval limit 1000. Warranty 36 months.'):
    return SimpleUploadedFile(name, body, content_type='text/plain')


# ---------- Source-data builder ----------
def build_documents(tenant, user):
    set_current_tenant(tenant)
    pub = services.create_document(
        tenant, title='Procurement Policy Manual', category='policy', confidentiality='internal',
        summary='Approval limits and competitive-bid thresholds.', tags='policy, limits',
        owner=user, user=user)
    services.create_document_version(
        pub, upload('policy.txt', b'Approval limit is 1000. Three quotes above 5000. ISO 9001.'),
        user, change_note='Initial', publish=True)

    draft = services.create_document(
        tenant, title='Laptop Specification', category='spec', confidentiality='public',
        tags='laptop, hardware', owner=user, user=user)
    services.create_document_version(
        draft, upload('spec.txt', b'Laptop 16 GB RAM, 512 GB SSD, 3 year warranty.'),
        user, publish=False)

    tmpl = PolicyTemplate.all_objects.create(
        tenant=tenant, template_number=services.next_template_number(tenant),
        title='RFP Template — IT Services', category='rfp',
        description='Reusable RFP skeleton.', body='1. Scope\n2. Criteria\n3. Terms',
        status='published', owner=user)

    return SimpleNamespace(tenant=tenant, pub=pub, draft=draft, tmpl=tmpl)


@pytest.fixture
def data(db, tenant, tenant_admin):
    return build_documents(tenant, tenant_admin)
