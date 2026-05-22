"""Unit tests for the Module 2 service layer (numbering, widgets, reporting)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.portal.models import DashboardWidget, Notification, QuickRequisition
from apps.portal.services import (
    build_dashboard_context, create_notification, ensure_default_widgets,
    generate_report, next_requisition_number,
)

pytestmark = pytest.mark.django_db


def _approved_req(tenant, user, category='office_supplies', total='100.00'):
    return QuickRequisition.all_objects.create(
        tenant=tenant, user=user, number=next_requisition_number(tenant),
        title='Seeded', category=category, status='approved',
        estimated_total=Decimal(total),
    )


# ---------- numbering ----------

def test_next_number_format_and_increment(tenant, user):
    n1 = next_requisition_number(tenant)
    assert n1 == 'QR-ACME-00001'
    QuickRequisition.all_objects.create(
        tenant=tenant, user=user, number=n1, title='x', status='draft')
    assert next_requisition_number(tenant) == 'QR-ACME-00002'


def test_numbering_is_per_tenant(tenant, other_tenant, user):
    """D-08: each tenant has its own QR sequence."""
    QuickRequisition.all_objects.create(
        tenant=tenant, user=user, number=next_requisition_number(tenant),
        title='x', status='draft')
    # other_tenant is untouched -> its first number is still 00001
    assert next_requisition_number(other_tenant) == 'QR-GLOBEX-00001'


# ---------- widgets ----------

def test_ensure_default_widgets_provisions_six(tenant, user):
    ensure_default_widgets(tenant, user)
    assert DashboardWidget.all_objects.filter(tenant=tenant, user=user).count() == 6


def test_ensure_default_widgets_idempotent(tenant, user):
    ensure_default_widgets(tenant, user)
    ensure_default_widgets(tenant, user)
    assert DashboardWidget.all_objects.filter(tenant=tenant, user=user).count() == 6


# ---------- notifications ----------

def test_create_notification(tenant, user):
    note = create_notification(tenant, user, 'Hi', category='approval')
    assert note.pk and note.category == 'approval' and not note.is_read


# ---------- reporting ----------

def test_generate_report_spend_by_category(tenant, user):
    _approved_req(tenant, user, 'office_supplies', '100.00')
    _approved_req(tenant, user, 'travel', '250.00')
    result = generate_report(_saved(tenant, user, 'spend_by_category'))
    assert result['kind'] == 'doughnut'
    assert sum(result['values']) == 350.0
    assert result['summary']['Total approved spend'] == 350.0


def test_generate_report_requisition_status(tenant, user):
    _approved_req(tenant, user)
    QuickRequisition.all_objects.create(
        tenant=tenant, user=user, number=next_requisition_number(tenant),
        title='d', status='draft')
    result = generate_report(_saved(tenant, user, 'requisition_status'))
    assert result['summary']['Total requisitions'] == 2


def test_generate_report_spend_by_month(tenant, user):
    _approved_req(tenant, user, total='40.00')
    result = generate_report(_saved(tenant, user, 'spend_by_month'))
    assert result['kind'] == 'bar'
    assert sum(result['values']) == 40.0


def test_generate_report_notification_summary(tenant, user):
    create_notification(tenant, user, 'a', category='approval')
    create_notification(tenant, user, 'b', category='deadline')
    result = generate_report(_saved(tenant, user, 'notification_summary'))
    assert result['summary']['Total notifications'] == 2


def test_generate_report_empty_data(tenant, user):
    result = generate_report(_saved(tenant, user, 'spend_by_category'))
    assert result['labels'] == [] and result['values'] == []


def test_generate_report_unknown_type_fallback(tenant, user):
    rep = _saved(tenant, user, 'spend_by_category')
    rep.report_type = 'does_not_exist'
    result = generate_report(rep)
    assert result == {'kind': 'bar', 'labels': [], 'values': [],
                      'rows': [], 'summary': {}}


# ---------- dashboard context ----------

def test_build_dashboard_context(tenant, user):
    _approved_req(tenant, user, total='100.00')
    QuickRequisition.all_objects.create(
        tenant=tenant, user=user, number=next_requisition_number(tenant),
        title='d', status='draft')
    create_notification(tenant, user, 'unread alert')
    ctx = build_dashboard_context(tenant, user)
    assert ctx['approved_count'] == 1
    assert ctx['draft_count'] == 1
    assert ctx['requisition_count'] == 2
    assert ctx['spend_total'] == Decimal('100.00')
    assert ctx['unread_count'] == 1


# ---------- helper ----------

def _saved(tenant, user, report_type):
    from apps.portal.models import SavedReport
    today = timezone.now().date()
    return SavedReport.all_objects.create(
        tenant=tenant, user=user, name=report_type, report_type=report_type,
        date_from=today - timedelta(days=90), date_to=today,
    )
