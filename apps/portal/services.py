"""Module 2 service layer: widgets, notifications, requisitions, reporting."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from .models import (
    DashboardWidget, Notification, QuickRequisition, SavedReport,
)


# ---------- Quick requisitions ----------

def next_requisition_number(tenant) -> str:
    """Generate the next QR-<SLUG>-NNNNN number for a tenant.

    The number is unique *per tenant* (SQA defect D-08); the caller is still
    expected to retry on IntegrityError to cover the concurrent-create race
    (SQA defect D-04), since this check is not transactionally locked.
    """
    slug = (getattr(tenant, 'slug', '') or 'x')[:6].upper().replace('-', '')
    count = QuickRequisition.all_objects.filter(tenant=tenant).count() + 1
    number = f'QR-{slug}-{count:05d}'
    # Guard against gaps left by deletes: bump until unique within the tenant.
    while QuickRequisition.all_objects.filter(tenant=tenant, number=number).exists():
        count += 1
        number = f'QR-{slug}-{count:05d}'
    return number


# ---------- Notifications ----------

def create_notification(tenant, user, title, *, category='info',
                         priority='normal', message='', link_url=''):
    """Create a single alert for a user. Used by views and the seeder."""
    return Notification.all_objects.create(
        tenant=tenant,
        user=user,
        category=category,
        priority=priority,
        title=title,
        message=message,
        link_url=link_url,
    )


# ---------- Personalized overview ----------

DEFAULT_WIDGETS = [
    {'widget_type': 'pending_tasks', 'title': 'Pending Tasks', 'size': 'small'},
    {'widget_type': 'pending_approvals', 'title': 'Pending Approvals', 'size': 'small'},
    {'widget_type': 'spend_summary', 'title': 'Spend Summary', 'size': 'small'},
    {'widget_type': 'notifications', 'title': 'Alerts', 'size': 'medium'},
    {'widget_type': 'recent_activity', 'title': 'Recent Activity', 'size': 'medium'},
    {'widget_type': 'quick_links', 'title': 'Quick Links', 'size': 'large'},
]


def ensure_default_widgets(tenant, user):
    """Provision the starter widget set the first time a user opens the portal."""
    if DashboardWidget.objects.filter(tenant=tenant, user=user).exists():
        return
    for position, spec in enumerate(DEFAULT_WIDGETS):
        DashboardWidget.objects.create(
            tenant=tenant, user=user, position=position, **spec,
        )


def build_dashboard_context(tenant, user):
    """Aggregate every figure the personalized dashboard widgets can render."""
    from apps.tenants.models import AuditLog

    reqs = QuickRequisition.objects.filter(tenant=tenant, user=user)
    draft = reqs.filter(status='draft')
    submitted = reqs.filter(status='submitted')
    approved = reqs.filter(status='approved')

    spend_total = approved.aggregate(t=Sum('estimated_total'))['t'] or Decimal('0.00')
    spend_by_category = [
        {
            'label': dict(QuickRequisition.CATEGORY_CHOICES).get(row['category'], row['category']),
            'value': float(row['total'] or 0),
        }
        for row in approved.values('category')
        .annotate(total=Sum('estimated_total')).order_by('-total')
    ]

    notifications = Notification.objects.filter(tenant=tenant, user=user)

    return {
        'draft_requisitions': draft.order_by('-created_at')[:5],
        'draft_count': draft.count(),
        'submitted_requisitions': submitted.order_by('-created_at')[:5],
        'submitted_count': submitted.count(),
        'approved_count': approved.count(),
        'requisition_count': reqs.count(),
        'spend_total': spend_total,
        'spend_by_category': spend_by_category,
        'unread_notifications': notifications.filter(is_read=False).order_by('-created_at')[:5],
        'unread_count': notifications.filter(is_read=False).count(),
        'recent_activity': (
            AuditLog.objects.filter(tenant=tenant, user=user)
            .order_by('-created_at')[:6]
        ),
        'saved_reports': SavedReport.objects.filter(tenant=tenant, user=user)[:5],
    }


# ---------- Self-service reporting ----------

def _report_window(report):
    """Resolve a report's date window, defaulting to the last 90 days."""
    end = report.date_to or timezone.now().date()
    start = report.date_from or (end - timedelta(days=90))
    return start, end


def generate_report(report):
    """Compute a SavedReport into a chart-ready payload.

    Returns a dict: {labels, values, rows, summary, kind}.
    `kind` is 'bar' or 'doughnut' so the template can pick a chart.
    """
    tenant, user = report.tenant, report.user
    start, end = _report_window(report)

    reqs = QuickRequisition.objects.filter(
        tenant=tenant, user=user,
        created_at__date__gte=start, created_at__date__lte=end,
    )

    if report.report_type == 'spend_by_category':
        rows = list(
            reqs.filter(status='approved').values('category')
            .annotate(total=Sum('estimated_total'), count=Count('id'))
            .order_by('-total')
        )
        labels, values, table = [], [], []
        cat_map = dict(QuickRequisition.CATEGORY_CHOICES)
        for r in rows:
            label = cat_map.get(r['category'], r['category'])
            labels.append(label)
            values.append(float(r['total'] or 0))
            table.append({'label': label, 'count': r['count'],
                          'amount': float(r['total'] or 0)})
        return {
            'kind': 'doughnut', 'labels': labels, 'values': values, 'rows': table,
            'summary': {'Total approved spend': sum(values),
                        'Categories': len(labels)},
        }

    if report.report_type == 'spend_by_month':
        buckets = {}
        for req in reqs.filter(status='approved'):
            key = req.created_at.strftime('%Y-%m')
            buckets[key] = buckets.get(key, 0.0) + float(req.estimated_total or 0)
        labels = sorted(buckets.keys())
        values = [buckets[k] for k in labels]
        return {
            'kind': 'bar', 'labels': labels, 'values': values,
            'rows': [{'label': k, 'amount': v} for k, v in zip(labels, values)],
            'summary': {'Total approved spend': sum(values),
                        'Months': len(labels)},
        }

    if report.report_type == 'requisition_status':
        rows = list(
            reqs.values('status').annotate(count=Count('id')).order_by('-count')
        )
        status_map = dict(QuickRequisition.STATUS_CHOICES)
        labels = [status_map.get(r['status'], r['status']) for r in rows]
        values = [r['count'] for r in rows]
        return {
            'kind': 'doughnut', 'labels': labels, 'values': values,
            'rows': [{'label': l, 'count': v} for l, v in zip(labels, values)],
            'summary': {'Total requisitions': sum(values)},
        }

    if report.report_type == 'my_activity':
        from apps.tenants.models import AuditLog
        logs = AuditLog.objects.filter(
            tenant=tenant, user=user,
            created_at__date__gte=start, created_at__date__lte=end,
        )
        rows = list(
            logs.values('action').annotate(count=Count('id')).order_by('-count')[:12]
        )
        labels = [r['action'] for r in rows]
        values = [r['count'] for r in rows]
        return {
            'kind': 'bar', 'labels': labels, 'values': values,
            'rows': [{'label': l, 'count': v} for l, v in zip(labels, values)],
            'summary': {'Total actions': logs.count()},
        }

    if report.report_type == 'notification_summary':
        notes = Notification.objects.filter(
            tenant=tenant, user=user,
            created_at__date__gte=start, created_at__date__lte=end,
        )
        rows = list(
            notes.values('category').annotate(count=Count('id')).order_by('-count')
        )
        cat_map = dict(Notification.CATEGORY_CHOICES)
        labels = [cat_map.get(r['category'], r['category']) for r in rows]
        values = [r['count'] for r in rows]
        return {
            'kind': 'doughnut', 'labels': labels, 'values': values,
            'rows': [{'label': l, 'count': v} for l, v in zip(labels, values)],
            'summary': {'Total notifications': notes.count(),
                        'Unread': notes.filter(is_read=False).count()},
        }

    return {'kind': 'bar', 'labels': [], 'values': [], 'rows': [], 'summary': {}}
