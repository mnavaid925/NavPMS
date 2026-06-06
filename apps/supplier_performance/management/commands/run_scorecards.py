"""Cron-friendly batch scorecard generation + overdue-PIP sweep.

Mirrors ``run_spend_sync`` / ``run_budget_alerts``: generate a final scorecard for every active
vendor over a period (defaults to the trailing calendar quarter), optionally sweeping overdue PIPs.

    python manage.py run_scorecards                       # trailing quarter, all tenants
    python manage.py run_scorecards --tenant acme         # one tenant
    python manage.py run_scorecards --period-start 2026-01-01 --period-end 2026-03-31 --label "Q1 2026"
    python manage.py run_scorecards --pip-sweep           # also alert on overdue improvement plans
"""
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import Tenant, set_current_tenant
from apps.supplier_performance import services


def _trailing_quarter(today):
    """Return (start, end, label) for the calendar quarter before ``today``."""
    current_q = (today.month - 1) // 3 + 1
    if current_q == 1:
        year, pq = today.year - 1, 4
    else:
        year, pq = today.year, current_q - 1
    start_month = (pq - 1) * 3 + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1) - timedelta(days=1)
    return start, end, f'Q{pq} {year}'


class Command(BaseCommand):
    help = 'Generate supplier scorecards for a period across tenants (+ optional overdue-PIP sweep).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Limit to one tenant slug.')
        parser.add_argument('--period-start', help='YYYY-MM-DD (defaults to trailing quarter).')
        parser.add_argument('--period-end', help='YYYY-MM-DD (defaults to trailing quarter).')
        parser.add_argument('--label', default='', help='Period label, e.g. "Q1 2026".')
        parser.add_argument('--pip-sweep', action='store_true',
                            help='Also raise alerts for overdue improvement plans.')

    def _parse(self, value, field):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            raise CommandError(f'--{field} must be YYYY-MM-DD.')

    def handle(self, *args, **options):
        today = timezone.now().date()
        if options['period_start'] or options['period_end']:
            if not (options['period_start'] and options['period_end']):
                raise CommandError('Provide both --period-start and --period-end, or neither.')
            start = self._parse(options['period_start'], 'period-start')
            end = self._parse(options['period_end'], 'period-end')
            label = options['label']
        else:
            start, end, label = _trailing_quarter(today)
        if end < start:
            raise CommandError('Period end must not be before the start.')
        label = label or f'{start} – {end}'

        if options['tenant']:
            tenants = list(Tenant.objects.filter(slug=options['tenant']))
            if not tenants:
                raise CommandError(f'No tenant with slug "{options["tenant"]}".')
        else:
            tenants = list(Tenant.objects.all())

        total = 0
        for tenant in tenants:
            result = services.generate_scorecards_for_period(
                tenant, start, end, period_label=label)
            total += result['generated']
            self.stdout.write(
                f'  {tenant.name}: {result["generated"]} scorecard(s) for {result["vendors"]} '
                f'active vendor(s) — {label}.')
        set_current_tenant(None)

        if options['pip_sweep']:
            if options['tenant']:
                alerted = services.scan_pip_alerts(tenants[0])
            else:
                alerted = services.scan_all_tenants()
            self.stdout.write(f'  Overdue-PIP sweep: {alerted} plan(s) alerted.')

        self.stdout.write(self.style.SUCCESS(
            f'Generated {total} scorecard(s) for {label} across {len(tenants)} tenant(s).'))
