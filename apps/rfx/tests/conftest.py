"""Shared fixtures for Module 7 (RFx Management) tests."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant
from apps.rfx.models import (
    RfxEvent, RfxInvitee, RfxQuestion, RfxResponse, RfxSection,
    RfxTemplate, RfxTemplateQuestion, RfxTemplateSection,
)
from apps.rfx.services import (
    invite_vendors, publish_event, start_response, submit_response,
)
from apps.vendors.models import Vendor


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
        role='tenant_admin', is_tenant_admin=True,
    )


@pytest.fixture
def buyer_user(db, tenant):
    return User.objects.create_user(
        username='buyer', password='x', tenant=tenant, role='buyer',
    )


@pytest.fixture
def procurement_manager(db, tenant):
    """Manage-role user WITHOUT is_tenant_admin, so the MANAGE_ROLES membership
    branch of can_manage_rfx is exercised (not the is_tenant_admin short-circuit)."""
    return User.objects.create_user(
        username='pmgr', password='x', tenant=tenant, role='procurement_manager',
    )


@pytest.fixture
def evaluator(db, tenant):
    return User.objects.create_user(
        username='approver_user', password='x', tenant=tenant, role='approver',
    )


@pytest.fixture
def requester(db, tenant):
    return User.objects.create_user(
        username='requester', password='x', tenant=tenant, role='requester',
    )


@pytest.fixture
def intruder(db, other_tenant):
    return User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant,
        role='tenant_admin', is_tenant_admin=True,
    )


# ---------- Vendors ----------

@pytest.fixture
def vendor_a(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00001',
        legal_name='Acme IT Solutions', status='active',
    )


@pytest.fixture
def vendor_b(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00002',
        legal_name='Beacon Cleaners', status='active',
    )


@pytest.fixture
def vendor_c(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00003',
        legal_name='Cosmic Stationery', status='active',
    )


@pytest.fixture
def blocked_vendor(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-09999',
        legal_name='Blocked Co', status='blacklisted',
    )


@pytest.fixture
def vendor_portal_user(db, tenant, vendor_a):
    return User.objects.create_user(
        username='portal_a', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_a,
    )


# ---------- Events ----------

@pytest.fixture
def draft_event(db, tenant, tenant_admin):
    return RfxEvent.all_objects.create(
        tenant=tenant, event_number='RFX-ACME-00001',
        title='Draft event', rfx_type='rfi',
        status='draft', created_by=tenant_admin,
        close_at=timezone.now() + timedelta(days=7),
    )


@pytest.fixture
def section(db, tenant, draft_event):
    return RfxSection.all_objects.create(
        tenant=tenant, event=draft_event, title='Profile', position=1,
    )


@pytest.fixture
def question(db, tenant, section):
    """A short-text, non-scored question."""
    return RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=1,
        prompt='Company name?', question_type='text',
        is_required=True, is_scored=False, weight=Decimal('0.00'),
    )


@pytest.fixture
def scored_question(db, tenant, section):
    """A scored number question worth 100% of the score (max 10)."""
    return RfxQuestion.all_objects.create(
        tenant=tenant, section=section, position=2,
        prompt='Rate your readiness (0–10)', question_type='scale',
        is_required=True, is_scored=True,
        weight=Decimal('100.00'), max_score=10,
    )


@pytest.fixture
def open_event(db, draft_event, question, vendor_a, vendor_b, tenant_admin):
    """A fully-built event opened for responses (no scored questions)."""
    invite_vendors(draft_event, [vendor_a.pk, vendor_b.pk], tenant_admin)
    # Force a past publish_at so publish_event auto-advances to 'open'.
    draft_event.publish_at = timezone.now() - timedelta(minutes=5)
    draft_event.save(update_fields=['publish_at', 'updated_at'])
    publish_event(draft_event, tenant_admin)
    draft_event.refresh_from_db()
    return draft_event


@pytest.fixture
def submitted_response(db, open_event, vendor_a, tenant_admin):
    response = start_response(open_event, vendor_a, tenant_admin)
    # Answer the required question
    answer = response.answers.first()
    answer.value_text = 'Acme'
    answer.save()
    submit_response(response, tenant_admin)
    return response


# ---------- Template ----------

@pytest.fixture
def template_with_questions(db, tenant, tenant_admin):
    template = RfxTemplate.all_objects.create(
        tenant=tenant, title='Standard RFI', rfx_type='rfi',
        is_shared=True, created_by=tenant_admin,
    )
    sec = RfxTemplateSection.all_objects.create(
        tenant=tenant, template=template, title='Overview', position=1,
    )
    RfxTemplateQuestion.all_objects.create(
        tenant=tenant, section=sec, position=1,
        prompt='Company name?', question_type='text',
        is_required=True, is_scored=False, weight=Decimal('0'),
    )
    RfxTemplateQuestion.all_objects.create(
        tenant=tenant, section=sec, position=2,
        prompt='Years in business', question_type='number',
        is_required=True, is_scored=True,
        weight=Decimal('100.00'), max_score=5,
    )
    return template
