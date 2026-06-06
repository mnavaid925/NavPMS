"""Seed Module 17 demo data: default KPIs + multi-period scorecards + 360° feedback + a PIP.

Runs AFTER ``seed_vendors`` / ``seed_goods_receipt`` / ``seed_invoicing`` (so vendors + the
transactional data the KPI engine reads exist). Idempotent: skips a tenant that already has
scorecards unless ``--flush`` is passed. Generates final scorecards for three consecutive quarters
so the trending page renders a line, seeds submitted feedback so the feedback KPI has data, and
opens an improvement plan for the weakest vendor.
"""
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.vendors.models import Vendor

from apps.supplier_performance import services
from apps.supplier_performance.models import (
    ImprovementPlan, KpiDefinition, PerformanceFeedback, PIPAction, PIPStatusEvent,
    Scorecard, ScorecardLine,
)

# Per-vendor baseline feedback rating (by vendor index) and per-period delta (oldest→newest),
# so each vendor trends differently and the latest period is the current scorecard.
VENDOR_BASE_RATING = [5, 4, 2]   # strong / mid / weak supplier
PERIOD_DELTA = [-1, 0, 1]        # older period weaker, improving toward the latest


def _rolling_periods(today, *, count=3, length_days=90):
    """``count`` consecutive [start, end] windows ending at ``today`` (oldest first) + a label."""
    periods = []
    end = today
    for _ in range(count):
        start = end - timedelta(days=length_days - 1)
        periods.append((start, end, f'{start:%b %Y} – {end:%b %Y}'))
        end = start - timedelta(days=1)
    periods.reverse()
    return periods


class Command(BaseCommand):
    help = 'Seed Module 17 demo data (KPIs + scorecards + feedback + a PIP per tenant).'

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true')

    def handle(self, *args, **options):
        flush = options['flush']
        tenants = list(Tenant.objects.all())
        if not tenants:
            self.stdout.write(self.style.ERROR('No tenants found. Run `seed_tenants` first.'))
            return

        for tenant in tenants:
            set_current_tenant(tenant)
            if flush:
                PIPStatusEvent.all_objects.filter(tenant=tenant).delete()
                PIPAction.all_objects.filter(tenant=tenant).delete()
                ImprovementPlan.all_objects.filter(tenant=tenant).delete()
                ScorecardLine.all_objects.filter(tenant=tenant).delete()
                Scorecard.all_objects.filter(tenant=tenant).delete()
                PerformanceFeedback.all_objects.filter(tenant=tenant).delete()
                KpiDefinition.all_objects.filter(tenant=tenant).delete()

            if Scorecard.all_objects.filter(tenant=tenant).exists() and not flush:
                self.stdout.write(
                    f'  {tenant.name}: scorecards already exist — skipped (use --flush to re-seed).')
                continue

            services.ensure_default_kpis(tenant)

            actor = next(
                (u for u in User.objects.filter(tenant=tenant, is_active=True)
                 if u.is_tenant_admin),
                User.objects.filter(tenant=tenant, is_active=True, vendor__isnull=True).first(),
            )
            reviewers = list(
                User.objects.filter(tenant=tenant, is_active=True, vendor__isnull=True)[:3])
            vendors = list(Vendor.all_objects.filter(tenant=tenant, status='active')[:3])
            if not vendors:
                self.stdout.write(self.style.WARNING(
                    f'  {tenant.name}: no active vendors (run seed_vendors first) — skipped.'))
                continue

            today = timezone.localdate()
            periods = _rolling_periods(today)

            # Seed submitted feedback dated INSIDE each window so the feedback KPI scores every
            # period and the trend line varies. The latest window also captures the real
            # (today-dated) goods-receipt / invoice data the auto KPIs read.
            for vi, vendor in enumerate(vendors):
                base = VENDOR_BASE_RATING[vi % len(VENDOR_BASE_RATING)]
                for pi, (start, end, _label) in enumerate(periods):
                    rating = max(1, min(5, base + PERIOD_DELTA[pi % len(PERIOD_DELTA)]))
                    mid = start + (end - start) // 2
                    submitted = timezone.make_aware(datetime.combine(mid, time(12, 0)))
                    for r in range(2):
                        reviewer = reviewers[r % len(reviewers)] if reviewers else actor
                        PerformanceFeedback.all_objects.create(
                            tenant=tenant, vendor=vendor, reviewer=reviewer, requested_by=actor,
                            period_label=_label, status='submitted', rating=rating,
                            quality_rating=rating, delivery_rating=rating,
                            communication_rating=rating, would_recommend=rating >= 4,
                            comments='Seeded review.', requested_at=submitted,
                            submitted_at=submitted)
                # One outstanding request (dated now) so the feedback inbox has a demo item.
                if reviewers:
                    services.request_feedback(vendor, reviewers[0], actor,
                                              period_label=periods[-1][2])

            # Generate a final scorecard per vendor per period (latest becomes current).
            cards_by_vendor = {}
            for vendor in vendors:
                for start, end, label in periods:
                    card = services.generate_scorecard(
                        vendor, start, end, actor, period_label=label, status='final')
                    cards_by_vendor[vendor.pk] = card

            # Open a PIP for the weakest current vendor.
            weakest = min(
                vendors, key=lambda v: cards_by_vendor[v.pk].overall_score)
            trigger = cards_by_vendor[weakest.pk]
            plan = services.create_plan(
                weakest, actor,
                title=f'Performance recovery — {weakest.legal_name}',
                summary='Auto-opened from seed: address delivery and quality shortfalls.',
                severity='high', owner=actor, target_date=today + timedelta(days=90),
                scorecard=trigger)
            PIPAction.all_objects.create(
                tenant=tenant, improvement_plan=plan, line_no=1,
                description='Submit a root-cause analysis of late deliveries.',
                due_date=today + timedelta(days=30), assigned_to=actor)
            PIPAction.all_objects.create(
                tenant=tenant, improvement_plan=plan, line_no=2,
                description='Implement incoming-quality checks before dispatch.',
                due_date=today + timedelta(days=60), assigned_to=actor)
            services.set_plan_status(plan, 'open', actor, note='Seeded')
            services.set_plan_status(plan, 'in_progress', actor, note='Work started')

            avg = services.tenant_performance_metrics(tenant)['average_score']
            self.stdout.write(
                f'  {tenant.name}: {len(vendors)} vendor(s) scored across {len(periods)} period(s), '
                f'avg {avg}; PIP {plan.pip_number} opened for {weakest.legal_name}.')

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('Supplier performance & evaluation seeded.'))
        self.stdout.write(
            'Log in as a tenant admin (e.g. admin_acme / Welcome@123) and open '
            '/supplier-performance/ — the superuser "admin" has no tenant and sees no data.')
