"""Security tests for Module 7 — OWASP-aligned.

A01 Broken Access Control: cross-tenant IDOR, cross-vendor response access.
A03 Injection / XSS: prompt + answer body must be HTML-escaped in templates.
A04 Insecure design: status-transition guards (cannot edit non-draft, etc).
A05 Misconfig: anonymous redirect to login.
A08 Data integrity / file upload: answer file size cap.
CSRF: POST endpoints reject missing csrf token.
"""
from io import BytesIO
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.rfx.forms import RfxDocumentForm, MAX_DOCUMENT_BYTES, MAX_ANSWER_FILE_BYTES
from apps.rfx.models import RfxEvent, RfxResponse, RfxAnswer, RfxQuestion, RfxSection
from apps.rfx.services import response_visible_to, record_evaluation, close_event

pytestmark = pytest.mark.django_db


# ---------- A01 — IDOR / cross-tenant access ----------

def test_cross_tenant_event_detail_returns_404(
    client, tenant_admin, draft_event, intruder,
):
    """An admin from another tenant cannot fetch this tenant's event."""
    client.force_login(intruder)
    resp = client.get(reverse('rfx:event_detail', args=[draft_event.pk]))
    assert resp.status_code == 404


def test_cross_tenant_event_edit_returns_404(
    client, draft_event, intruder,
):
    client.force_login(intruder)
    resp = client.get(reverse('rfx:event_edit', args=[draft_event.pk]))
    assert resp.status_code == 404


def test_cross_tenant_event_delete_returns_404(
    client, draft_event, intruder,
):
    client.force_login(intruder)
    resp = client.post(reverse('rfx:event_delete', args=[draft_event.pk]))
    assert resp.status_code == 404
    # event still exists
    assert RfxEvent.all_objects.filter(pk=draft_event.pk).exists()


def test_cross_tenant_question_delete_returns_404(
    client, draft_event, question, intruder,
):
    client.force_login(intruder)
    resp = client.post(reverse(
        'rfx:question_delete', args=[draft_event.pk, question.pk],
    ))
    assert resp.status_code == 404


def test_cross_vendor_response_blocked(
    tenant, submitted_response, vendor_b,
):
    """A different vendor's portal user cannot see this vendor's response."""
    from apps.accounts.models import User
    other = User.objects.create_user(
        username='other_v', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_b,
    )
    assert response_visible_to(other, submitted_response) is False


def test_vendor_cannot_start_response_for_event_they_were_not_invited(
    open_event, vendor_c, tenant_admin,
):
    """vendor_c is active but not on the invitee list."""
    from apps.rfx.services import start_response
    with pytest.raises(ValidationError):
        start_response(open_event, vendor_c, tenant_admin)


# ---------- A03 — XSS escape on user-supplied content ----------

def test_event_title_is_escaped_in_list(client, tenant, tenant_admin):
    """User-supplied title with HTML must be escaped, not rendered as markup."""
    RfxEvent.all_objects.create(
        tenant=tenant, event_number='RFX-ACME-XSS',
        title='<script>alert("xss")</script>', rfx_type='rfi',
    )
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:event_list'))
    assert resp.status_code == 200
    assert b'<script>alert("xss")</script>' not in resp.content
    assert b'&lt;script&gt;' in resp.content


def test_question_prompt_is_escaped_in_event_detail(
    client, tenant, tenant_admin, draft_event, section,
):
    RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=1,
        prompt='<img src=x onerror=alert(1)>',
        question_type='text',
    )
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:event_detail', args=[draft_event.pk]))
    assert resp.status_code == 200
    assert b'<img src=x onerror=alert(1)>' not in resp.content
    assert b'&lt;img src=x' in resp.content


# ---------- A04 — Status transition guards ----------

def test_cannot_edit_non_draft_event(
    client, tenant_admin, open_event,
):
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:event_edit', args=[open_event.pk]))
    # Redirected back to detail with an error message
    assert resp.status_code == 302
    assert reverse('rfx:event_detail', args=[open_event.pk]) in resp.url


def test_cannot_evaluate_unscored_question(
    tenant, tenant_admin, vendor_a,
):
    """Trying to score a non-scored question is rejected at the service layer."""
    from apps.rfx.services import (
        create_event, invite_vendors, publish_event,
        start_response, submit_response, close_event,
    )
    event = create_event(
        tenant=tenant, user=tenant_admin,
        title='Unscored', rfx_type='rfi',
        close_at=timezone.now() + timedelta(days=1),
    )
    sec = RfxSection.all_objects.create(
        tenant=tenant, event=event, title='S', position=1,
    )
    q = RfxQuestion.all_objects.create(
        tenant=tenant, section=sec, position=1,
        prompt='Tell us about your company',
        question_type='text', is_required=False, is_scored=False,
        weight=Decimal('0'),
    )
    invite_vendors(event, [vendor_a.pk], tenant_admin)
    event.publish_at = timezone.now() - timedelta(minutes=1)
    event.save()
    publish_event(event, tenant_admin)
    resp = start_response(event, vendor_a, tenant_admin)
    submit_response(resp, tenant_admin)
    close_event(event, tenant_admin)

    with pytest.raises(ValidationError):
        record_evaluation(response=resp, question=q,
                          evaluator=tenant_admin, score=5)


# ---------- A05 — anonymous redirect to login ----------

@pytest.mark.parametrize('url_name', [
    'rfx:event_list', 'rfx:event_create', 'rfx:template_list',
    'rfx:analytics_dashboard',
])
def test_anonymous_redirected_to_login(client, url_name):
    resp = client.get(reverse(url_name))
    assert resp.status_code == 302
    assert '/accounts/login/' in resp.url


# ---------- A08 — file upload size caps ----------

def test_document_form_rejects_oversize_file(tenant_admin):
    big_bytes = b'A' * (MAX_DOCUMENT_BYTES + 1)
    upload = SimpleUploadedFile('big.pdf', big_bytes, content_type='application/pdf')
    form = RfxDocumentForm(data={'title': 'big'}, files={'file': upload})
    assert not form.is_valid()
    assert 'file' in form.errors


def test_document_form_accepts_small_file():
    upload = SimpleUploadedFile('ok.pdf', b'small content', content_type='application/pdf')
    form = RfxDocumentForm(data={'title': 'ok'}, files={'file': upload})
    assert form.is_valid()


@pytest.mark.parametrize('filename,content_type', [
    ('logo.svg', 'image/svg+xml'),     # SVG can carry <script>
    ('brief.html', 'text/html'),       # stored HTML -> XSS if served inline
    ('macro.docm', 'application/vnd.ms-word.document.macroEnabled.12'),
    ('payload.exe', 'application/octet-stream'),
])
def test_document_form_rejects_active_content(filename, content_type):
    """D-04: uploads outside the extension allow-list are rejected, so a buyer
    cannot stash active content under MEDIA (which Apache may serve inline)."""
    upload = SimpleUploadedFile(filename, b'<svg onload=alert(1)>', content_type=content_type)
    form = RfxDocumentForm(data={'title': 'x'}, files={'file': upload})
    assert not form.is_valid()
    assert 'file' in form.errors


def test_document_form_rejects_uppercase_extension():
    """D-04: the whitelist check lowercases the name, so EVIL.SVG is still rejected
    (a naive splitext check would let an uppercase extension slip)."""
    upload = SimpleUploadedFile('EVIL.SVG', b'<svg/>', content_type='image/svg+xml')
    form = RfxDocumentForm(data={'title': 'x'}, files={'file': upload})
    assert not form.is_valid()
    assert 'file' in form.errors


def test_document_form_accepts_uppercase_allowed_extension():
    """And a legitimately uppercase allowed extension (SPEC.PDF) is accepted —
    pins the .lower() normalization so dropping it would fail this test."""
    upload = SimpleUploadedFile('SPEC.PDF', b'content', content_type='application/pdf')
    form = RfxDocumentForm(data={'title': 'ok'}, files={'file': upload})
    assert form.is_valid()


def test_answer_file_upload_size_cap_is_5mb():
    """Vendor-side per-answer uploads are capped at 5 MB."""
    assert MAX_ANSWER_FILE_BYTES == 5 * 1024 * 1024


# ---------- CSRF ----------

def test_post_without_csrf_token_is_rejected(tenant_admin, draft_event):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(tenant_admin)
    resp = csrf_client.post(reverse('rfx:event_delete', args=[draft_event.pk]))
    assert resp.status_code == 403


def test_vendor_portal_internal_url_block(client, vendor_portal_user):
    """A vendor-portal user cannot reach buyer-side RFx routes (sandbox middleware)."""
    client.force_login(vendor_portal_user)
    resp = client.get(reverse('rfx:event_create'))
    assert resp.status_code == 302
    assert '/vendor-portal/' in resp.url
