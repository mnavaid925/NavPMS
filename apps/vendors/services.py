"""Module 5 service layer: numbering, status workflow, risk recompute,
application conversion, portal invites."""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.tenants.services import record_audit

from .models import (
    Vendor, VendorBlacklistEvent, VendorOnboardingApplication,
    VendorRiskAssessment, risk_level_from_score,
)


User = get_user_model()


# ---------- Numbering ----------

def next_vendor_number(tenant) -> str:
    """Generate the next VND-<SLUG>-NNNNN number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = Vendor.all_objects.filter(tenant=tenant).count() + 1
    number = f'VND-{slug}-{count:05d}'
    while Vendor.all_objects.filter(tenant=tenant, vendor_number=number).exists():
        count += 1
        number = f'VND-{slug}-{count:05d}'
    return number


# ---------- 4. Risk recompute ----------

def apply_risk_assessment(assessment: VendorRiskAssessment, user=None):
    """Mark the assessment current, mark older ones stale, denormalise level/score
    onto the vendor row."""
    with transaction.atomic():
        VendorRiskAssessment.all_objects.filter(
            tenant=assessment.tenant, vendor=assessment.vendor,
        ).exclude(pk=assessment.pk).update(is_current=False)
        assessment.is_current = True
        assessment.save()
        vendor = assessment.vendor
        vendor.risk_score = assessment.overall_score
        vendor.risk_level = assessment.level
        vendor.save(update_fields=['risk_score', 'risk_level', 'updated_at'])
    record_audit(
        tenant=assessment.tenant,
        user=user,
        action='vendor.risk_assessed',
        target_type='Vendor',
        target_id=vendor.pk,
        message=f'Score {assessment.overall_score} ({assessment.level})',
    )
    return assessment


# ---------- 1. Vendor onboarding -> Vendor ----------

@transaction.atomic
def convert_application_to_vendor(application: VendorOnboardingApplication, user):
    """Approve an application and create a draft Vendor record from it."""
    if application.converted_to_vendor_id:
        return application.converted_to_vendor

    vendor = Vendor.all_objects.create(
        tenant=application.tenant,
        vendor_number=next_vendor_number(application.tenant),
        legal_name=application.company_name,
        trade_name=application.trade_name,
        vendor_type=application.vendor_type,
        tax_id=application.tax_id,
        registration_number=application.registration_number,
        email=application.contact_email,
        phone=application.contact_phone,
        website=application.website,
        country=application.country,
        primary_contact_name=application.contact_name,
        primary_contact_email=application.contact_email,
        primary_contact_phone=application.contact_phone,
        status='pending_verification',
        notes=(
            f'Created from onboarding application #{application.pk} on '
            f'{timezone.localdate()}'
        ),
    )
    application.status = 'approved'
    application.reviewed_by = user
    application.reviewed_at = timezone.now()
    application.converted_to_vendor = vendor
    application.save()

    record_audit(
        tenant=application.tenant,
        user=user,
        action='vendor.onboarded',
        target_type='Vendor',
        target_id=vendor.pk,
        message=f'From application {application.pk}',
    )
    return vendor


def reject_application(application: VendorOnboardingApplication, user, reason: str):
    application.status = 'rejected'
    application.reviewed_by = user
    application.reviewed_at = timezone.now()
    application.rejection_reason = reason or 'Not specified'
    application.save()
    record_audit(
        tenant=application.tenant,
        user=user,
        action='vendor.application_rejected',
        target_type='VendorOnboardingApplication',
        target_id=application.pk,
        message=reason or '',
    )


# ---------- 5. Suspension / Blacklist / Reinstate ----------

def _record_blacklist(vendor, action, *, user, reason, effective_date=None,
                      end_date=None, notes=''):
    """Internal: append an event + update vendor.status."""
    effective_date = effective_date or timezone.localdate()
    event = VendorBlacklistEvent.all_objects.create(
        tenant=vendor.tenant,
        vendor=vendor,
        action=action,
        effective_date=effective_date,
        end_date=end_date,
        reason=reason,
        notes=notes or '',
        actioned_by=user,
    )
    status_map = {
        'suspend': 'suspended',
        'blacklist': 'blacklisted',
    }
    if action in status_map:
        vendor.status = status_map[action]
    else:  # reinstate
        vendor.status = 'active'
    vendor.save(update_fields=['status', 'updated_at'])
    record_audit(
        tenant=vendor.tenant,
        user=user,
        action=f'vendor.{action}',
        target_type='Vendor',
        target_id=vendor.pk,
        message=reason,
    )
    return event


def suspend_vendor(vendor, *, user, reason, effective_date=None, end_date=None,
                   notes=''):
    return _record_blacklist(
        vendor, 'suspend', user=user, reason=reason,
        effective_date=effective_date, end_date=end_date, notes=notes,
    )


def blacklist_vendor(vendor, *, user, reason, effective_date=None, notes=''):
    return _record_blacklist(
        vendor, 'blacklist', user=user, reason=reason,
        effective_date=effective_date, notes=notes,
    )


def reinstate_vendor(vendor, *, user, reason, effective_date=None, notes=''):
    return _record_blacklist(
        vendor, 'reinstate', user=user, reason=reason,
        effective_date=effective_date, notes=notes,
    )


# ---------- Verification ----------

def verify_vendor(vendor, *, user):
    """Mark a vendor as verified and move it from pending_verification -> active."""
    vendor.is_verified = True
    vendor.verified_at = timezone.now()
    vendor.verified_by = user
    if vendor.status in ('draft', 'pending_verification'):
        vendor.status = 'active'
    vendor.save(update_fields=[
        'is_verified', 'verified_at', 'verified_by', 'status', 'updated_at',
    ])
    record_audit(
        tenant=vendor.tenant, user=user,
        action='vendor.verified',
        target_type='Vendor', target_id=vendor.pk,
    )
    return vendor


# ---------- 2. Portal invite ----------

def make_portal_username(vendor) -> str:
    base = f'vp_{vendor.tenant.slug}_{vendor.pk}'
    candidate = base
    i = 1
    while User.objects.filter(username=candidate).exists():
        i += 1
        candidate = f'{base}_{i}'
    return candidate


@transaction.atomic
def invite_to_portal(vendor, *, user, email=None):
    """Create (or refresh) a vendor portal User and a one-time password token.

    Returns the (user, raw_password) pair so the caller can email it. For this
    demo build, the raw password is shown back to the inviter — wire to an email
    backend in production.
    """
    target_email = email or vendor.primary_contact_email or vendor.email
    if not target_email:
        raise ValueError('Vendor has no contact email to invite.')

    existing = vendor.portal_user
    if existing:
        # rotate password
        raw = secrets.token_urlsafe(10)
        existing.set_password(raw)
        existing.email = target_email
        existing.is_active = True
        existing.save()
        record_audit(
            tenant=vendor.tenant, user=user,
            action='vendor.portal_reset',
            target_type='Vendor', target_id=vendor.pk,
            message=target_email,
        )
        return existing, raw

    raw = secrets.token_urlsafe(10)
    portal = User.objects.create_user(
        username=make_portal_username(vendor),
        email=target_email,
        password=raw,
        tenant=vendor.tenant,
        role='vendor_portal',
        first_name=vendor.primary_contact_name.split(' ')[0] if vendor.primary_contact_name else vendor.legal_name[:30],
        last_name='',
        is_tenant_admin=False,
    )
    portal.vendor = vendor
    portal.save(update_fields=['vendor'])
    vendor.portal_user = portal
    vendor.save(update_fields=['portal_user', 'updated_at'])
    record_audit(
        tenant=vendor.tenant, user=user,
        action='vendor.portal_invited',
        target_type='Vendor', target_id=vendor.pk,
        message=target_email,
    )
    return portal, raw


def revoke_portal_access(vendor, *, user):
    """Disable the vendor's portal user (kept for audit, not deleted)."""
    portal = vendor.portal_user
    if not portal:
        return None
    portal.is_active = False
    portal.save(update_fields=['is_active'])
    record_audit(
        tenant=vendor.tenant, user=user,
        action='vendor.portal_revoked',
        target_type='Vendor', target_id=vendor.pk,
    )
    return portal
