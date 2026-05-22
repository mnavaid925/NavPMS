"""Unit tests for the Module 3 service layer: numbering, workflow, duplicates."""
from decimal import Decimal

import pytest

from apps.requisitions.models import (
    Requisition, RequisitionStatusEvent, RequisitionTemplateLine,
)
from apps.requisitions.services import (
    amend_requisition, cancel_requisition, convert_requisition,
    create_requisition_from_template, decide_requisition,
    find_potential_duplicates, flag_duplicates, next_requisition_number,
    record_status_event, submit_requisition,
)
from apps.tenants.models import AuditLog

pytestmark = pytest.mark.django_db


# ---------- numbering ----------

def test_next_requisition_number(tenant, member):
    assert next_requisition_number(tenant) == 'REQ-ACME-00001'
    Requisition.all_objects.create(
        tenant=tenant, requested_by=member, number='REQ-ACME-00001', title='x')
    assert next_requisition_number(tenant) == 'REQ-ACME-00002'


# ---------- tracking ----------

def test_record_status_event(requisition, member):
    ev = record_status_event(requisition, 'draft', 'submitted', member, note='go')
    assert ev.from_status == 'draft' and ev.to_status == 'submitted'
    assert RequisitionStatusEvent.all_objects.filter(requisition=requisition).count() == 1


# ---------- duplicate detection ----------

def test_find_potential_duplicates_by_title(tenant, member, requisition):
    twin = Requisition.all_objects.create(
        tenant=tenant, requested_by=member,
        number=next_requisition_number(tenant),
        title=requisition.title, status='draft')
    matches = find_potential_duplicates(twin)
    assert requisition in matches


def test_flag_duplicates_sets_fields(tenant, member, requisition):
    twin = Requisition.all_objects.create(
        tenant=tenant, requested_by=member,
        number=next_requisition_number(tenant),
        title=requisition.title, status='draft')
    flag_duplicates(twin)
    twin.refresh_from_db()
    assert twin.possible_duplicate and twin.duplicate_of_id == requisition.id


# ---------- templates ----------

def test_create_requisition_from_template(tenant, member, template):
    RequisitionTemplateLine.all_objects.create(
        tenant=tenant, template=template, description='Paper',
        quantity=Decimal('5'), estimated_unit_price=Decimal('4.00'))
    req = create_requisition_from_template(template, member, tenant)
    assert req.status == 'draft' and req.created_from_template == template
    assert req.lines.count() == 1
    assert req.estimated_total == Decimal('20.00')


# ---------- status workflow ----------

def test_submit_requisition(requisition, member):
    submit_requisition(requisition, member)
    requisition.refresh_from_db()
    assert requisition.status == 'submitted' and requisition.submitted_at is not None
    assert AuditLog.all_objects.filter(
        tenant=requisition.tenant, action='requisition.submitted').exists()


def test_decide_requisition_approve(requisition, tenant_admin):
    requisition.status = 'submitted'
    requisition.save(update_fields=['status'])
    decide_requisition(requisition, tenant_admin, approved=True, note='ok')
    requisition.refresh_from_db()
    assert requisition.status == 'approved'
    assert requisition.decided_by == tenant_admin


def test_decide_requisition_reject(requisition, tenant_admin):
    requisition.status = 'submitted'
    requisition.save(update_fields=['status'])
    decide_requisition(requisition, tenant_admin, approved=False)
    requisition.refresh_from_db()
    assert requisition.status == 'rejected'


def test_cancel_requisition(requisition, member):
    cancel_requisition(requisition, member)
    requisition.refresh_from_db()
    assert requisition.status == 'cancelled' and requisition.cancelled_at is not None


def test_amend_requisition_bumps_revision(requisition, member):
    requisition.status = 'approved'
    requisition.save(update_fields=['status'])
    amend_requisition(requisition, member)
    requisition.refresh_from_db()
    assert requisition.status == 'draft' and requisition.revision == 2
    assert requisition.submitted_at is None and requisition.decided_at is None


def test_convert_requisition(requisition, tenant_admin):
    requisition.status = 'approved'
    requisition.save(update_fields=['status'])
    convert_requisition(requisition, tenant_admin, po_reference='PO-123')
    requisition.refresh_from_db()
    assert requisition.status == 'converted' and requisition.po_reference == 'PO-123'
