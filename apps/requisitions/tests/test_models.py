"""Unit tests for Module 3 model properties and invariants."""
from decimal import Decimal

import pytest

from apps.requisitions.models import RequisitionLine, RequisitionTemplateLine

pytestmark = pytest.mark.django_db


def test_is_editable_only_draft(requisition):
    assert requisition.is_editable
    requisition.status = 'submitted'
    assert not requisition.is_editable


def test_can_amend(requisition):
    assert not requisition.can_amend
    for status in ('submitted', 'approved'):
        requisition.status = status
        assert requisition.can_amend


def test_can_cancel(requisition):
    for status in ('draft', 'submitted', 'approved'):
        requisition.status = status
        assert requisition.can_cancel
    requisition.status = 'converted'
    assert not requisition.can_cancel


def test_line_save_computes_line_total(requisition):
    line = RequisitionLine(
        tenant=requisition.tenant, requisition=requisition,
        description='Mouse', quantity=Decimal('4'), unit_price=Decimal('12.50'))
    line.save()
    assert line.line_total == Decimal('50.00')


def test_recalc_total(requisition, make_line):
    make_line(requisition, quantity='2', unit_price='10.00')
    make_line(requisition, quantity='1', unit_price='5.00')
    assert requisition.recalc_total() == Decimal('25.00')


def test_template_estimated_total(template):
    RequisitionTemplateLine.all_objects.create(
        tenant=template.tenant, template=template, description='A',
        quantity=Decimal('3'), estimated_unit_price=Decimal('10.00'))
    assert template.estimated_total == Decimal('30.00')


def test_template_line_estimated_total(template):
    line = RequisitionTemplateLine(
        tenant=template.tenant, template=template, description='B',
        quantity=Decimal('2'), estimated_unit_price=Decimal('7.50'))
    assert line.estimated_total == Decimal('15.00')
