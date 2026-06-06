"""Module 18 service layer: Risk & Compliance Management.

Five concerns, one module:

* **Screening** — :func:`run_screening` runs the pluggable provider (``screening.py``) against the
  tenant's restricted-party lists, persists a :class:`ComplianceScreening` + its
  :class:`ScreeningMatch` hits, and :func:`disposition_match` resolves each hit.
* **Financial monitoring** — :func:`refresh_financial_risk` pulls a credit score from the pluggable
  provider (``credit.py``), recomputes exposure from open POs + unpaid invoices, writes a
  :class:`FinancialRiskSnapshot`, and alerts on a score drop / band worsening.
* **Audit trail** — reuses ``apps.tenants`` ``record_audit`` / ``verify_audit_chain`` (this module
  only reads/verifies the chain; no new audit infra).
* **Fraud** — :func:`scan_fraud` dispatches the active :class:`FraudRule` detectors and raises
  deduplicated :class:`FraudAlert` findings.
* **Policy** — :func:`publish_policy` / :func:`acknowledge_policy` drive the repository + sign-offs.

Conventions mirrored from Module 16: ``MANAGE_ROLES``/``VIEW_ROLES`` + ``_has_role`` permission
helpers, ``record_audit`` from :mod:`apps.tenants.services`, ``create_notification`` from
:mod:`apps.portal.services`, gap-free ``PREFIX-<SLUG>-NNNNN`` numbering and ``@transaction.atomic``
write paths. The module is self-contained — it queries source models read-only and never mutates them.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant
from apps.portal.services import create_notification
from apps.tenants.services import record_audit

from .credit import get_credit_provider
from .models import (
    BAND_COLORS,
    ComplianceScreening,
    FinancialRiskProfile,
    FinancialRiskSnapshot,
    FraudAlert,
    FraudAlertEvent,
    FraudRule,
    Policy,
    PolicyAcknowledgment,
    PolicyVersion,
    ScreeningMatch,
)
from .screening import get_screening_provider

ZERO = Decimal('0.00')

# Source-document statuses this module treats as live financial exposure.
OPEN_PO_STATUSES = ('issued', 'acknowledged', 'partially_received')
UNPAID_INVOICE_STATUSES = ('submitted', 'approved')
_BAND_RANK = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
# Free-mail domains never treated as a conflict-of-interest signal (would be all false positives).
_COMMON_DOMAINS = {'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'icloud.com', 'aol.com'}

# Roles allowed to manage compliance (run screenings, manage rules/policies, resolve alerts). Mirrors
# the other procurement modules — there is no dedicated compliance role in the project yet.
MANAGE_ROLES = ('tenant_admin', 'procurement_manager', 'buyer')
# Viewing (dashboard / audit explorer / lists) additionally allows approvers.
VIEW_ROLES = MANAGE_ROLES + ('approver',)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _has_role(user, roles):
    """True if the user holds any of ``roles`` (string slugs)."""
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'is_tenant_admin', False):
        return True
    role = getattr(user, 'role', None)
    role_slug = role if isinstance(role, str) else (
        getattr(role, 'slug', None) or getattr(role, 'name', None))
    return role_slug in roles


def can_manage_compliance(user):
    """May run screenings, manage rules/policies, resolve fraud alerts, refresh financial risk."""
    return _has_role(user, MANAGE_ROLES)


def can_view_compliance(user):
    """May view dashboards / lists / audit explorer (managers + approvers)."""
    return _has_role(user, VIEW_ROLES)


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def _next_number(model, tenant, prefix, field_name) -> str:
    """Generate the next gap-free ``<PREFIX>-<SLUG>-NNNNN`` number for a tenant."""
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = model.all_objects.filter(tenant=tenant).count() + 1
    number = f'{prefix}-{slug}-{count:05d}'
    while model.all_objects.filter(tenant=tenant, **{field_name: number}).exists():
        count += 1
        number = f'{prefix}-{slug}-{count:05d}'
    return number


def next_screening_number(tenant):
    return _next_number(ComplianceScreening, tenant, 'SCR', 'screening_number')


def next_fraud_number(tenant):
    return _next_number(FraudAlert, tenant, 'FRD', 'alert_number')


def next_policy_number(tenant):
    return _next_number(Policy, tenant, 'POL', 'policy_number')


# ---------------------------------------------------------------------------
# 1. Restricted-party screening
# ---------------------------------------------------------------------------
@transaction.atomic
def run_screening(tenant, *, vendor=None, name=None, user=None, request=None,
                  provider=None, lists=None):
    """Screen a vendor (or an ad-hoc name) against the restricted-party lists; persist the result."""
    provider = provider or get_screening_provider()
    screened_name = (name or (vendor.legal_name if vendor else '') or '').strip()
    if not screened_name:
        raise ValidationError('Provide a vendor or a name to screen.')
    threshold = float(getattr(settings, 'SCREENING_MATCH_THRESHOLD', 85))
    result = provider.screen(screened_name, tenant=tenant, lists=lists, threshold=threshold)
    now = timezone.now()
    status = 'review' if result.matches else 'clear'
    screening = ComplianceScreening.all_objects.create(
        tenant=tenant, screening_number=next_screening_number(tenant), vendor=vendor,
        screened_name=screened_name, provider=result.provider, status=status,
        match_count=len(result.matches), lists_checked=result.lists_checked,
        screened_by=user, screened_at=now,
    )
    for m in result.matches:
        ScreeningMatch.all_objects.create(
            tenant=tenant, screening=screening, entry_id=m.entry_id, matched_name=m.matched_name,
            list_name=m.list_name, score=Decimal(str(m.score)), matched_field=m.matched_field,
        )
    record_audit(
        tenant, user, 'compliance.screening',
        level='warning' if result.matches else 'info',
        target_type='ComplianceScreening', target_id=screening.id,
        message=f'Screened "{screened_name}": {len(result.matches)} match(es).', request=request,
    )
    if result.matches:
        _notify_managers(
            tenant, f'Screening hit: {screening.screening_number}',
            f'"{screened_name}" matched {len(result.matches)} restricted-party record(s).',
            link_url=f'/compliance/screenings/{screening.id}/', priority='high',
        )
    return screening


@transaction.atomic
def disposition_match(match, decision, user, *, note='', request=None):
    """Resolve one screening hit (false_positive / confirmed) and recompute the screening status."""
    if decision not in {'pending', 'false_positive', 'confirmed'}:
        raise ValidationError('Invalid disposition.')
    match.decision = decision
    match.notes = note[:255]
    match.dispositioned_by = user
    match.dispositioned_at = timezone.now()
    match.save(update_fields=['decision', 'notes', 'dispositioned_by', 'dispositioned_at',
                              'updated_at'])
    screening = match.screening
    decisions = list(screening.matches.values_list('decision', flat=True))
    if any(d == 'confirmed' for d in decisions):
        screening.status = 'blocked'
    elif decisions and all(d == 'false_positive' for d in decisions):
        screening.status = 'clear'
    else:
        screening.status = 'review'
    screening.save(update_fields=['status', 'updated_at'])
    record_audit(
        screening.tenant, user, 'compliance.screening_disposition',
        target_type='ScreeningMatch', target_id=match.id,
        message=f'{match.matched_name} → {decision} ({screening.screening_number}).',
        request=request,
    )
    return match


# ---------------------------------------------------------------------------
# 2. Supplier financial-risk monitoring
# ---------------------------------------------------------------------------
def vendor_exposure(tenant, vendor):
    """Live exposure for a vendor: open-PO value + unpaid-invoice value (+ the overdue slice)."""
    from apps.purchase_orders.models import PurchaseOrder
    from apps.invoicing.models import SupplierInvoice

    open_po = PurchaseOrder.all_objects.filter(
        tenant=tenant, vendor=vendor, status__in=OPEN_PO_STATUSES)
    open_po_total = open_po.aggregate(s=Sum('total_amount'))['s'] or ZERO
    unpaid = SupplierInvoice.all_objects.filter(
        tenant=tenant, vendor=vendor, status__in=UNPAID_INVOICE_STATUSES)
    unpaid_total = unpaid.aggregate(s=Sum('total_amount'))['s'] or ZERO
    overdue_total = (
        unpaid.filter(due_date__lt=timezone.localdate()).aggregate(s=Sum('total_amount'))['s']
        or ZERO)
    return {
        'exposure': (open_po_total + unpaid_total).quantize(ZERO),
        'overdue': overdue_total.quantize(ZERO),
        'open_po_count': open_po.count(),
    }


@transaction.atomic
def refresh_financial_risk(tenant, vendor, *, user=None, request=None, provider=None, now=None):
    """Pull a fresh credit score, recompute exposure, snapshot it, and alert on deterioration."""
    now = now or timezone.now()
    provider = provider or get_credit_provider()
    result = provider.fetch(vendor)
    exp = vendor_exposure(tenant, vendor)

    profile, _ = FinancialRiskProfile.all_objects.get_or_create(
        tenant=tenant, vendor=vendor, defaults={'provider': result.provider})
    prev_score = float(profile.credit_score or 0)
    prev_band = profile.band

    profile.credit_score = Decimal(str(result.score))
    profile.band = result.band
    profile.outlook = result.outlook
    profile.exposure_amount = exp['exposure']
    profile.overdue_invoice_amount = exp['overdue']
    profile.provider = result.provider
    profile.last_checked_at = now
    profile.next_check_at = now + timedelta(days=30)
    profile.save()

    FinancialRiskSnapshot.all_objects.create(
        tenant=tenant, vendor=vendor, profile=profile, as_of_date=now.date(),
        credit_score=profile.credit_score, band=profile.band, outlook=profile.outlook,
        exposure_amount=exp['exposure'], overdue_amount=exp['overdue'],
        open_po_count=exp['open_po_count'], source=result.provider, raw=result.raw,
    )

    drop = prev_score - float(profile.credit_score)
    drop_threshold = float(getattr(settings, 'CREDIT_SCORE_DROP_ALERT', 10))
    worsened = _BAND_RANK.get(profile.band, 0) > _BAND_RANK.get(prev_band, 0)
    if (prev_score and drop >= drop_threshold) or worsened:
        profile.alerted_at = now
        profile.save(update_fields=['alerted_at', 'updated_at'])
        record_audit(
            tenant, user, 'compliance.financial_alert', level='warning',
            target_type='Vendor', target_id=vendor.id,
            message=(f'{vendor.legal_name} financial risk worsened to {profile.band} '
                     f'(score {profile.credit_score}).'), request=request,
        )
        _notify_managers(
            tenant, f'Financial risk: {vendor.legal_name}',
            f'Credit score is now {profile.credit_score} ({profile.get_band_display()}), '
            f'exposure {exp["exposure"]}.',
            link_url=f'/compliance/financial/{profile.id}/', priority='high',
        )
    else:
        record_audit(
            tenant, user, 'compliance.financial_refresh',
            target_type='Vendor', target_id=vendor.id,
            message=f'Credit score {profile.credit_score} ({profile.band}) for {vendor.legal_name}.',
            request=request,
        )
    return profile


# ---------------------------------------------------------------------------
# 4. Fraud detection
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    """One detector hit, normalized for :func:`_raise_alert`."""
    signature: str
    summary: str
    subject_type: str = ''
    subject_id: str = ''
    vendor_id: object = None
    evidence: dict = field(default_factory=dict)


def _approval_threshold(tenant):
    """The lowest active requisition-approval ceiling — the bar a split-PO scheme stays under."""
    from apps.approvals.models import ApprovalRule
    return (
        ApprovalRule.all_objects
        .filter(tenant=tenant, is_active=True, max_amount__isnull=False)
        .order_by('max_amount')
        .values_list('max_amount', flat=True)
        .first()
    )


def _detect_split_po(tenant, rule):
    from apps.purchase_orders.models import PurchaseOrder

    params = rule.params or {}
    window = int(params.get('window_days', getattr(settings, 'FRAUD_SPLIT_PO_WINDOW_DAYS', 14)))
    threshold = _approval_threshold(tenant)
    if not threshold or threshold <= 0:
        return []
    cutoff = timezone.localdate() - timedelta(days=window)
    pos = (
        PurchaseOrder.all_objects
        .filter(tenant=tenant, vendor__isnull=False, created_by__isnull=False,
                total_amount__gt=0, total_amount__lt=threshold)
        .exclude(status='cancelled')
        .values('id', 'vendor_id', 'created_by_id', 'total_amount', 'order_date', 'created_at',
                'po_number')
    )
    groups = defaultdict(list)
    for po in pos:
        d = po['order_date'] or (po['created_at'].date() if po['created_at'] else None)
        if d and d < cutoff:
            continue
        groups[(po['vendor_id'], po['created_by_id'])].append(po)

    findings = []
    for (vendor_id, _creator), items in groups.items():
        if len(items) < 2:
            continue
        total = sum((p['total_amount'] or ZERO) for p in items)
        if total <= threshold:
            continue
        ids = sorted(p['id'] for p in items)
        findings.append(Finding(
            signature='split_po:' + ','.join(map(str, ids)),
            summary=(f'{len(items)} POs to one vendor by one buyer total {total} '
                     f'exceed the approval threshold {threshold}.'),
            subject_type='Vendor', subject_id=str(vendor_id), vendor_id=vendor_id,
            evidence={'po_ids': ids, 'total': str(total), 'threshold': str(threshold),
                      'window_days': window},
        ))
    return findings


def _detect_duplicate_invoice(tenant, rule):
    from apps.invoicing.models import SupplierInvoice

    rows = (
        SupplierInvoice.all_objects
        .filter(tenant=tenant, total_amount__gt=0)
        .exclude(status='cancelled')
        .values('id', 'vendor_id', 'total_amount', 'supplier_invoice_ref', 'invoice_date')
    )
    by_ref = defaultdict(list)
    by_date = defaultdict(list)
    for r in rows:
        ref = (r['supplier_invoice_ref'] or '').strip().lower()
        if ref:
            by_ref[(r['vendor_id'], r['total_amount'], ref)].append(r['id'])
        if r['invoice_date']:
            by_date[(r['vendor_id'], r['total_amount'], r['invoice_date'])].append(r['id'])

    findings = []
    seen = set()
    for key, ids in list(by_ref.items()) + list(by_date.items()):
        if len(ids) < 2:
            continue
        ids = sorted(set(ids))
        sig = 'duplicate_invoice:' + ','.join(map(str, ids))
        if sig in seen:
            continue
        seen.add(sig)
        vendor_id, amount = key[0], key[1]
        findings.append(Finding(
            signature=sig,
            summary=f'{len(ids)} invoices from one vendor share the identical amount {amount}.',
            subject_type='Vendor', subject_id=str(vendor_id), vendor_id=vendor_id,
            evidence={'invoice_ids': ids, 'amount': str(amount)},
        ))
    return findings


def _detect_round_amount(tenant, rule):
    from apps.purchase_orders.models import PurchaseOrder
    from apps.invoicing.models import SupplierInvoice

    params = rule.params or {}
    floor = Decimal(str(params.get('amount_floor',
                                   getattr(settings, 'FRAUD_ROUND_AMOUNT_FLOOR', 5000))))
    modulus = Decimal(str(params.get('modulus', 1000)))
    if modulus <= 0:
        return []
    findings = []
    for po in (PurchaseOrder.all_objects
               .filter(tenant=tenant, total_amount__gte=floor).exclude(status='cancelled')
               .values('id', 'vendor_id', 'total_amount', 'po_number')):
        amt = po['total_amount'] or ZERO
        if amt % modulus == 0:
            findings.append(Finding(
                signature=f'round_amount:PurchaseOrder:{po["id"]}',
                summary=f'PO {po["po_number"]} is a suspiciously round {amt}.',
                subject_type='PurchaseOrder', subject_id=str(po['id']), vendor_id=po['vendor_id'],
                evidence={'amount': str(amt), 'modulus': str(modulus)},
            ))
    for inv in (SupplierInvoice.all_objects
                .filter(tenant=tenant, total_amount__gte=floor).exclude(status='cancelled')
                .values('id', 'vendor_id', 'total_amount', 'invoice_number')):
        amt = inv['total_amount'] or ZERO
        if amt % modulus == 0:
            findings.append(Finding(
                signature=f'round_amount:SupplierInvoice:{inv["id"]}',
                summary=f'Invoice {inv["invoice_number"]} is a suspiciously round {amt}.',
                subject_type='SupplierInvoice', subject_id=str(inv['id']),
                vendor_id=inv['vendor_id'],
                evidence={'amount': str(amt), 'modulus': str(modulus)},
            ))
    return findings


def _detect_vendor_bank_conflict(tenant, rule):
    from apps.vendors.models import VendorBankAccount

    rows = VendorBankAccount.all_objects.filter(tenant=tenant).values(
        'vendor_id', 'account_number', 'iban')
    by_key = defaultdict(set)
    for r in rows:
        acct = (r['account_number'] or '').strip()
        if acct:
            by_key[('account', acct)].add(r['vendor_id'])
        iban = (r['iban'] or '').strip()
        if iban:
            by_key[('iban', iban)].add(r['vendor_id'])

    findings = []
    for (kind, value), vendor_ids in by_key.items():
        if len(vendor_ids) < 2:
            continue
        vids = sorted(vendor_ids)
        findings.append(Finding(
            signature=f'vendor_bank_conflict:{kind}:' + ','.join(map(str, vids)),
            summary=f'{len(vids)} vendors share the same bank {kind} (…{value[-4:]}).',
            subject_type='Vendor', subject_id=str(vids[0]), vendor_id=vids[0],
            evidence={'vendor_ids': vids, 'kind': kind, 'value_tail': value[-4:]},
        ))
    return findings


def _detect_conflict_of_interest(tenant, rule):
    from apps.accounts.models import User
    from apps.vendors.models import Vendor, VendorContact

    user_domains = defaultdict(list)
    for u in (User.objects.filter(tenant=tenant, is_active=True)
              .exclude(email='').values('id', 'email')):
        dom = u['email'].split('@')[-1].lower().strip()
        if dom and dom not in _COMMON_DOMAINS:
            user_domains[dom].append(u['id'])
    if not user_domains:
        return []

    findings = []
    flagged = set()

    def add(vendor_id, legal_name, dom):
        if vendor_id in flagged or dom not in user_domains:
            return
        flagged.add(vendor_id)
        findings.append(Finding(
            signature=f'conflict_of_interest:{vendor_id}:{dom}',
            summary=f'Vendor {legal_name} shares email domain @{dom} with an internal user.',
            subject_type='Vendor', subject_id=str(vendor_id), vendor_id=vendor_id,
            evidence={'domain': dom, 'user_ids': user_domains[dom]},
        ))

    for v in (Vendor.all_objects.filter(tenant=tenant)
              .values('id', 'email', 'primary_contact_email', 'legal_name')):
        for email in (v['email'], v['primary_contact_email']):
            if email:
                add(v['id'], v['legal_name'], email.split('@')[-1].lower().strip())
    for c in (VendorContact.all_objects.filter(tenant=tenant)
              .exclude(email='').values('vendor_id', 'email', 'vendor__legal_name')):
        add(c['vendor_id'], c['vendor__legal_name'], c['email'].split('@')[-1].lower().strip())
    return findings


_DETECTORS = {
    'split_po': _detect_split_po,
    'duplicate_invoice': _detect_duplicate_invoice,
    'round_amount': _detect_round_amount,
    'vendor_bank_conflict': _detect_vendor_bank_conflict,
    'conflict_of_interest': _detect_conflict_of_interest,
}


def record_fraud_event(alert, from_status, to_status, actor, *, note=''):
    return FraudAlertEvent.all_objects.create(
        tenant=alert.tenant, alert=alert, from_status=from_status, to_status=to_status,
        actor=actor, note=note,
    )


def _raise_alert(tenant, rule, finding, *, actor=None):
    """Create a FraudAlert for ``finding`` unless one with the same signature already exists."""
    existing = FraudAlert.all_objects.filter(tenant=tenant, signature=finding.signature).first()
    if existing:
        return existing, False
    now = timezone.now()
    alert = FraudAlert.all_objects.create(
        tenant=tenant, alert_number=next_fraud_number(tenant), rule=rule, rule_code=rule.code,
        rule_name=rule.name, severity=rule.severity, status='open',
        subject_type=finding.subject_type, subject_id=finding.subject_id,
        vendor_id=finding.vendor_id, summary=finding.summary[:255], evidence=finding.evidence,
        signature=finding.signature[:120], detected_at=now,
    )
    record_fraud_event(alert, '', 'open', actor, note='Detected by scan')
    record_audit(
        tenant, actor, 'compliance.fraud_alert', level='warning',
        target_type='FraudAlert', target_id=alert.id,
        message=f'Fraud alert {alert.alert_number}: {alert.summary[:120]}',
    )
    _notify_managers(
        tenant, f'Fraud alert: {alert.alert_number}', alert.summary,
        link_url=f'/compliance/fraud/alerts/{alert.id}/',
        priority='urgent' if alert.severity == 'critical' else 'high',
    )
    return alert, True


def scan_fraud(tenant, *, actor=None):
    """Run every active fraud rule's detector and raise deduplicated alerts. Returns new-alert count."""
    created = 0
    for rule in FraudRule.all_objects.filter(tenant=tenant, is_active=True):
        detector = _DETECTORS.get(rule.code)
        if not detector:
            continue
        for finding in detector(tenant, rule):
            _, is_new = _raise_alert(tenant, rule, finding, actor=actor)
            created += int(is_new)
    return created


@transaction.atomic
def set_fraud_status(alert, status, user, *, note='', request=None):
    """Move a fraud alert through its investigation workflow (audited + timelined)."""
    valid = {s for s, _ in FraudAlert.STATUS_CHOICES}
    if status not in valid:
        raise ValidationError('Invalid fraud alert status.')
    from_status = alert.status
    alert.status = status
    if status in ('confirmed', 'dismissed'):
        alert.resolved_by = user
        alert.resolved_at = timezone.now()
        alert.resolution_note = note[:255]
    alert.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note',
                              'updated_at'])
    record_fraud_event(alert, from_status, status, user, note=note)
    record_audit(
        alert.tenant, user, 'compliance.fraud_status',
        target_type='FraudAlert', target_id=alert.id,
        message=f'{alert.alert_number}: {from_status} → {status}.', request=request,
    )
    return alert


def assign_fraud_alert(alert, assignee, user, *, request=None):
    alert.assigned_to = assignee
    alert.save(update_fields=['assigned_to', 'updated_at'])
    record_audit(
        alert.tenant, user, 'compliance.fraud_assigned',
        target_type='FraudAlert', target_id=alert.id,
        message=f'{alert.alert_number} assigned to {assignee}.', request=request,
    )
    return alert


# ---------------------------------------------------------------------------
# 5. Policy management & acknowledgment
# ---------------------------------------------------------------------------
@transaction.atomic
def create_policy_version(policy, body, user, *, change_note='', effective_date=None,
                         publish=False, request=None):
    """Append an immutable policy version; optionally publish it as the current version."""
    last = policy.versions.order_by('-version_no').first()
    version_no = (last.version_no + 1) if last else 1
    version = PolicyVersion.all_objects.create(
        tenant=policy.tenant, policy=policy, version_no=version_no, body=body,
        change_note=change_note, effective_date=effective_date,
    )
    if publish:
        publish_policy(policy, version, user, request=request)
    return version


@transaction.atomic
def publish_policy(policy, version, user, *, request=None):
    """Publish a version: set it current, flip the policy to published, ask users to acknowledge."""
    now = timezone.now()
    version.published_by = user
    version.published_at = now
    version.save(update_fields=['published_by', 'published_at', 'updated_at'])
    policy.current_version = version
    policy.status = 'published'
    policy.published_at = now
    policy.save(update_fields=['current_version', 'status', 'published_at', 'updated_at'])
    record_audit(
        policy.tenant, user, 'compliance.policy_published',
        target_type='Policy', target_id=policy.id,
        message=f'Policy {policy.policy_number} v{version.version_no} published.', request=request,
    )
    if policy.requires_acknowledgment:
        _request_acknowledgments(policy, version)
    return policy


def _request_acknowledgments(policy, version):
    """Notify every active tenant user who has not yet acknowledged this version."""
    from apps.accounts.models import User
    acked = set(PolicyAcknowledgment.all_objects.filter(
        tenant=policy.tenant, policy_version=version).values_list('user_id', flat=True))
    for u in User.objects.filter(tenant=policy.tenant, is_active=True):
        if u.id in acked:
            continue
        create_notification(
            policy.tenant, u, f'Action required: acknowledge {policy.title}',
            category='approval', priority='normal',
            message=f'Please read and acknowledge policy {policy.policy_number}.',
            link_url='/compliance/my-policies/',
        )


@transaction.atomic
def acknowledge_policy(policy_version, user, *, request=None):
    """Record a user's sign-off on a policy version (idempotent — once per user per version)."""
    now = timezone.now()
    ip = request.META.get('REMOTE_ADDR') if request is not None else None
    ack, created = PolicyAcknowledgment.all_objects.get_or_create(
        tenant=policy_version.tenant, policy_version=policy_version, user=user,
        defaults={'acknowledged_at': now, 'ip_address': ip},
    )
    if created:
        record_audit(
            policy_version.tenant, user, 'compliance.policy_acknowledged',
            target_type='PolicyVersion', target_id=policy_version.id,
            message=(f'Acknowledged {policy_version.policy.policy_number} '
                     f'v{policy_version.version_no}.'), request=request,
        )
    return ack, created


def set_policy_status(policy, status, user, *, request=None):
    """Archive / re-draft a policy (audited)."""
    valid = {s for s, _ in Policy.STATUS_CHOICES}
    if status not in valid:
        raise ValidationError('Invalid policy status.')
    policy.status = status
    policy.save(update_fields=['status', 'updated_at'])
    record_audit(
        policy.tenant, user, 'compliance.policy_status',
        target_type='Policy', target_id=policy.id,
        message=f'Policy {policy.policy_number} → {status}.', request=request,
    )
    return policy


def policy_ack_stats(policy):
    """Acknowledgment progress for a policy's current version."""
    from apps.accounts.models import User
    total = User.objects.filter(tenant=policy.tenant, is_active=True).count()
    acked = 0
    if policy.current_version_id:
        acked = (PolicyAcknowledgment.all_objects
                 .filter(tenant=policy.tenant, policy_version_id=policy.current_version_id)
                 .values('user').distinct().count())
    pct = round(acked / total * 100, 1) if total else 0.0
    return {'total': total, 'acked': acked, 'outstanding': max(total - acked, 0), 'pct': pct}


# ---------------------------------------------------------------------------
# Notifications helper
# ---------------------------------------------------------------------------
def _notify_managers(tenant, title, message, *, link_url='', priority='normal'):
    """In-app alert to every tenant admin (the compliance owners)."""
    from apps.accounts.models import User
    for u in User.objects.filter(tenant=tenant, is_active=True, is_tenant_admin=True):
        create_notification(
            tenant, u, title, category='system', priority=priority,
            message=message, link_url=link_url,
        )


# ---------------------------------------------------------------------------
# Dashboard metrics
# ---------------------------------------------------------------------------
def tenant_compliance_metrics(tenant):
    """KPI cards + chart series for the compliance dashboard."""
    open_fraud = FraudAlert.all_objects.filter(
        tenant=tenant, status__in=('open', 'investigating'))
    screenings_review = ComplianceScreening.all_objects.filter(tenant=tenant, status='review')
    profiles = FinancialRiskProfile.all_objects.filter(tenant=tenant)
    high_risk = profiles.filter(band__in=('high', 'critical'))
    published = Policy.all_objects.filter(
        tenant=tenant, status='published', requires_acknowledgment=True)

    ack_total = ack_done = 0
    for p in published.select_related('current_version'):
        s = policy_ack_stats(p)
        ack_total += s['total']
        ack_done += s['acked']
    ack_pct = round(ack_done / ack_total * 100, 1) if ack_total else 0.0

    # Fraud-by-severity chart (open alerts).
    sev_counts = {'info': 0, 'warning': 0, 'critical': 0}
    for row in open_fraud.values('severity').annotate(n=Count('id')):
        sev_counts[row['severity']] = row['n']

    # Financial band distribution.
    band_counts = {'low': 0, 'medium': 0, 'high': 0, 'critical': 0}
    for row in profiles.values('band').annotate(n=Count('id')):
        band_counts[row['band']] = row['n']

    return {
        'open_fraud_count': open_fraud.count(),
        'screening_review_count': screenings_review.count(),
        'high_risk_count': high_risk.count(),
        'monitored_count': profiles.filter(monitored=True).count(),
        'policy_ack_pct': ack_pct,
        'published_policy_count': published.count(),
        'sev_labels': ['Info', 'Warning', 'Critical'],
        'sev_data': [sev_counts['info'], sev_counts['warning'], sev_counts['critical']],
        'band_labels': ['Low', 'Medium', 'High', 'Critical'],
        'band_data': [band_counts['low'], band_counts['medium'], band_counts['high'],
                      band_counts['critical']],
        'band_colors': [BAND_COLORS['low'], BAND_COLORS['medium'], BAND_COLORS['high'],
                        BAND_COLORS['critical']],
        'recent_alerts': list(open_fraud.select_related('vendor').order_by('-detected_at')[:8]),
    }


# ---------------------------------------------------------------------------
# Cron sweep (financial refresh + fraud scan + policy reminders)
# ---------------------------------------------------------------------------
def scan_compliance_alerts(tenant, *, now=None):
    """Cron entry: refresh due financial profiles, scan fraud, remind on outstanding acks.

    Returns ``{'financial_refreshed', 'fraud_alerts', 'policy_reminders'}``.
    """
    now = now or timezone.now()

    # 1. Refresh monitored financial profiles that are due.
    refreshed = 0
    due = FinancialRiskProfile.all_objects.filter(tenant=tenant, monitored=True).filter(
        next_check_at__isnull=True) | FinancialRiskProfile.all_objects.filter(
        tenant=tenant, monitored=True, next_check_at__lte=now)
    for profile in due.select_related('vendor').distinct():
        refresh_financial_risk(tenant, profile.vendor, now=now)
        refreshed += 1

    # 2. Fraud scan.
    fraud_new = scan_fraud(tenant)

    # 3. Policy-acknowledgment reminders — digest to each policy owner with outstanding sign-offs.
    reminders = 0
    for policy in Policy.all_objects.filter(
            tenant=tenant, status='published', requires_acknowledgment=True
    ).select_related('owner', 'current_version'):
        stats = policy_ack_stats(policy)
        if stats['outstanding'] and policy.owner:
            create_notification(
                tenant, policy.owner, f'{stats["outstanding"]} outstanding ack(s): {policy.title}',
                category='deadline', priority='normal',
                message=(f'{stats["acked"]}/{stats["total"]} users have acknowledged '
                         f'{policy.policy_number}.'),
                link_url=f'/compliance/policies/{policy.id}/',
            )
            reminders += 1

    return {'financial_refreshed': refreshed, 'fraud_alerts': fraud_new,
            'policy_reminders': reminders}


def scan_all_tenants():
    """Sweep every tenant. Returns the per-tenant results keyed by slug."""
    results = {}
    for t in Tenant.objects.all():
        set_current_tenant(t)
        results[t.slug] = scan_compliance_alerts(t)
    set_current_tenant(None)
    return results
