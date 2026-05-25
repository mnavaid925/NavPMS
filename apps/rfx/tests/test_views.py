"""Integration tests for Module 7 views: CRUD, permission gates, filter retention."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.rfx.models import RfxEvent, RfxResponse, RfxSection, RfxTemplate

pytestmark = pytest.mark.django_db


# ---------- Permission gates ----------

def test_event_list_requires_login(client):
    resp = client.get(reverse('rfx:event_list'))
    assert resp.status_code == 302
    assert '/accounts/login/' in resp.url


def test_event_list_kicks_vendor_user_to_portal(client, vendor_portal_user):
    client.force_login(vendor_portal_user)
    resp = client.get(reverse('rfx:event_list'))
    assert resp.status_code == 302
    assert '/vendor-portal/' in resp.url


def test_event_create_requires_manage_role(client, requester):
    client.force_login(requester)
    resp = client.post(reverse('rfx:event_create'), {
        'title': 'sneaky', 'rfx_type': 'rfi', 'currency': 'USD',
    })
    assert resp.status_code == 302
    assert RfxEvent.all_objects.filter(title='sneaky').count() == 0


def test_event_create_allowed_for_tenant_admin(client, tenant, tenant_admin):
    client.force_login(tenant_admin)
    resp = client.post(reverse('rfx:event_create'), {
        'title': 'New RFx', 'rfx_type': 'rfp', 'currency': 'USD',
    })
    assert resp.status_code == 302
    assert RfxEvent.all_objects.filter(tenant=tenant, title='New RFx').exists()


# ---------- CRUD ----------

def test_event_list_renders(client, tenant_admin, draft_event):
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:event_list'))
    assert resp.status_code == 200
    assert draft_event.event_number.encode() in resp.content


def test_event_detail_renders(client, tenant_admin, draft_event):
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:event_detail', args=[draft_event.pk]))
    assert resp.status_code == 200
    assert draft_event.title.encode() in resp.content


def test_event_edit_only_when_draft(client, tenant_admin, open_event):
    client.force_login(tenant_admin)
    url = reverse('rfx:event_edit', args=[open_event.pk])
    resp = client.get(url)
    # Non-draft -> bounced
    assert resp.status_code == 302


def test_event_delete_only_when_draft(client, tenant_admin, open_event):
    client.force_login(tenant_admin)
    url = reverse('rfx:event_delete', args=[open_event.pk])
    client.post(url)
    open_event.refresh_from_db()
    assert open_event.status == 'open'   # not deleted


def test_event_delete_when_draft(client, tenant_admin, draft_event):
    client.force_login(tenant_admin)
    url = reverse('rfx:event_delete', args=[draft_event.pk])
    resp = client.post(url)
    assert resp.status_code == 302
    assert not RfxEvent.all_objects.filter(pk=draft_event.pk).exists()


# ---------- Sealed responses ----------

def test_response_list_sealed_before_close(client, tenant_admin, open_event, submitted_response):
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:response_list', args=[open_event.pk]))
    assert resp.status_code == 200
    # The sealed banner is shown; submitted_response's vendor name is not.
    assert b'sealed' in resp.content.lower()


def test_response_detail_sealed_before_close(
    client, tenant_admin, open_event, submitted_response,
):
    client.force_login(tenant_admin)
    resp = client.get(reverse(
        'rfx:response_detail', args=[open_event.pk, submitted_response.pk],
    ))
    assert resp.status_code == 200
    # Sealed banner shown; specific answer body not rendered.
    assert b'sealed' in resp.content.lower()
    # The answer text "Acme" is also the vendor's legal name, so we can't use it
    # as a sealed-leak canary. Instead, check that the answer-rendering markup
    # (the per-question "Q1." prefix from sections) is absent.
    assert b'Q1.' not in resp.content


def test_response_detail_visible_after_close(
    client, tenant_admin, open_event, submitted_response,
):
    from apps.rfx.services import close_event
    close_event(open_event, tenant_admin)
    client.force_login(tenant_admin)
    resp = client.get(reverse(
        'rfx:response_detail', args=[open_event.pk, submitted_response.pk],
    ))
    assert resp.status_code == 200
    assert b'Acme' in resp.content


# ---------- Filters ----------

def test_event_list_status_filter(client, tenant, tenant_admin, draft_event):
    """Filter narrows by status — when filtering 'completed', the draft event is
    excluded; when filtering 'draft', it's included."""
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:event_list') + '?status=draft')
    assert resp.status_code == 200
    assert draft_event.event_number.encode() in resp.content
    resp2 = client.get(reverse('rfx:event_list') + '?status=completed')
    assert resp2.status_code == 200
    assert draft_event.event_number.encode() not in resp2.content


def test_event_list_search(client, tenant_admin, draft_event):
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:event_list') + '?q=Draft')
    assert resp.status_code == 200
    assert draft_event.event_number.encode() in resp.content


# ---------- Inline section / question CRUD ----------

def test_section_create_appends_position(
    client, tenant_admin, draft_event, section,
):
    """Adding a section auto-increments position to the next free slot."""
    client.force_login(tenant_admin)
    resp = client.post(
        reverse('rfx:section_create', args=[draft_event.pk]),
        {'title': 'New section', 'description': '', 'position': ''},
    )
    assert resp.status_code == 302
    s = draft_event.sections.filter(title='New section').first()
    assert s is not None
    assert s.position >= 2  # at least past the existing section


def test_question_create_appends_position(
    client, tenant_admin, draft_event, section, question,
):
    client.force_login(tenant_admin)
    resp = client.post(
        reverse('rfx:question_create', args=[draft_event.pk, section.pk]),
        {
            'prompt': 'New Q', 'help_text': '',
            'question_type': 'text', 'is_required': '',
            'is_scored': '', 'weight': '0',
            'max_score': '5', 'position': '',
            'choices_text': '',
        },
    )
    assert resp.status_code == 302
    q = section.questions.filter(prompt='New Q').first()
    assert q is not None
    assert q.position >= 2


# ---------- Lifecycle ----------

def test_publish_event_with_full_setup(
    client, tenant, tenant_admin, draft_event, section, question, vendor_a,
):
    """Adding invitees + question + close_at lets publish succeed."""
    from apps.rfx.services import invite_vendors
    invite_vendors(draft_event, [vendor_a.pk], tenant_admin)
    client.force_login(tenant_admin)
    resp = client.post(reverse('rfx:event_publish', args=[draft_event.pk]))
    assert resp.status_code == 302
    draft_event.refresh_from_db()
    assert draft_event.status in ('published', 'open')


def test_cancel_event_requires_reason(client, tenant_admin, open_event):
    client.force_login(tenant_admin)
    resp = client.post(
        reverse('rfx:event_cancel', args=[open_event.pk]),
        {'reason': ''},
    )
    open_event.refresh_from_db()
    assert open_event.status != 'cancelled'


def test_cancel_event_with_reason(client, tenant_admin, open_event):
    client.force_login(tenant_admin)
    client.post(
        reverse('rfx:event_cancel', args=[open_event.pk]),
        {'reason': 'Scope changed'},
    )
    open_event.refresh_from_db()
    assert open_event.status == 'cancelled'
    assert 'Scope changed' in open_event.cancelled_reason


# ---------- Template CRUD ----------

def test_template_list_renders(client, tenant_admin, template_with_questions):
    client.force_login(tenant_admin)
    resp = client.get(reverse('rfx:template_list'))
    assert resp.status_code == 200
    assert template_with_questions.title.encode() in resp.content


def test_template_use_creates_event(client, tenant, tenant_admin, template_with_questions):
    client.force_login(tenant_admin)
    resp = client.post(
        reverse('rfx:template_use', args=[template_with_questions.pk]),
        {'title': 'Spawned from tpl', 'publish_at': '', 'close_at': ''},
    )
    assert resp.status_code == 302
    assert RfxEvent.all_objects.filter(
        tenant=tenant, title='Spawned from tpl',
    ).exists()


# ---------- Vendor portal ----------

def test_vendor_portal_inbox_renders(client, vendor_portal_user, open_event, vendor_a):
    """Vendor portal user sees their invitations."""
    client.force_login(vendor_portal_user)
    resp = client.get(reverse('vendor_portal:rfx_inbox'))
    assert resp.status_code == 200
    assert open_event.event_number.encode() in resp.content


def test_vendor_portal_response_start_creates_draft(
    client, vendor_portal_user, open_event,
):
    client.force_login(vendor_portal_user)
    resp = client.post(reverse('vendor_portal:rfx_response_start', args=[open_event.pk]))
    assert resp.status_code == 302
    assert RfxResponse.all_objects.filter(event=open_event).exists()


def test_internal_route_blocks_vendor_portal_user(client, vendor_portal_user):
    """A vendor-portal user hitting an internal RFx route gets bounced."""
    client.force_login(vendor_portal_user)
    resp = client.get(reverse('rfx:event_list'))
    assert resp.status_code == 302
    assert '/vendor-portal/' in resp.url
