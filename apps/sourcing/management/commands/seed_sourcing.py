"""Seed Module 6 demo data: 3 events per tenant in varied statuses
(draft, open with draft+submitted bids, awarded with full evaluation matrix)."""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.sourcing.models import (
    Bid, BidDocument, BidEvaluation, BidLine, SourcingAward,
    SourcingCriterion, SourcingEvent, SourcingEventInvitee, SourcingEventItem,
)
from apps.sourcing.services import (
    finalize_award, invite_vendors, next_bid_number, next_event_number,
    publish_event, recommend_award, record_evaluation, recompute_bid_scores,
    start_bid, submit_bid,
)
from apps.vendors.models import Vendor, VendorCategory


CRITERIA = [
    ('Price',      'price',      Decimal('40.00'), Decimal('100.00')),
    ('Quality',    'quality',    Decimal('25.00'), Decimal('100.00')),
    ('Delivery',   'delivery',   Decimal('20.00'), Decimal('100.00')),
    ('Compliance', 'compliance', Decimal('15.00'), Decimal('100.00')),
]


class Command(BaseCommand):
    help = 'Seed Module 6 demo data (sourcing events, invitees, bids, evaluations, awards).'

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true')

    def handle(self, *args, **options):
        tenants = list(Tenant.objects.all())
        if not tenants:
            self.stdout.write(self.style.ERROR(
                'No tenants found. Run `seed_tenants` first.'
            ))
            return

        for tenant in tenants:
            set_current_tenant(tenant)
            if options['flush']:
                SourcingAward.all_objects.filter(tenant=tenant).delete()
                BidEvaluation.all_objects.filter(tenant=tenant).delete()
                BidDocument.all_objects.filter(tenant=tenant).delete()
                BidLine.all_objects.filter(tenant=tenant).delete()
                Bid.all_objects.filter(tenant=tenant).delete()
                SourcingCriterion.all_objects.filter(tenant=tenant).delete()
                SourcingEventInvitee.all_objects.filter(tenant=tenant).delete()
                SourcingEventItem.all_objects.filter(tenant=tenant).delete()
                SourcingEvent.all_objects.filter(tenant=tenant).delete()

            if SourcingEvent.all_objects.filter(tenant=tenant).exists() and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: sourcing data already exists — skipped '
                    '(use --flush to re-seed).'
                )
                continue

            users = list(User.objects.filter(tenant=tenant, is_active=True))
            admin = next(
                (u for u in users if u.is_tenant_admin),
                users[0] if users else None,
            )
            if not admin:
                self.stdout.write(f'    {tenant.name}: no admin user — skipped.')
                continue

            active_vendors = list(
                Vendor.all_objects.filter(
                    tenant=tenant, status='active',
                ).order_by('legal_name')[:5]
            )
            if len(active_vendors) < 2:
                self.stdout.write(
                    f'    {tenant.name}: needs >= 2 active vendors — skipped. '
                    'Run seed_vendors first.'
                )
                continue

            self.stdout.write(f'  Seeding sourcing data for {tenant.name}…')

            office_cat = VendorCategory.all_objects.filter(
                tenant=tenant, code='OFFICE',
            ).first()
            it_cat = VendorCategory.all_objects.filter(
                tenant=tenant, code='IT',
            ).first()
            maint_cat = VendorCategory.all_objects.filter(
                tenant=tenant, code='MAINT',
            ).first()

            # ---------- Event 1: Draft ----------
            draft = self._create_event(
                tenant, admin,
                title='Office stationery Q2 sourcing',
                event_type='rfq',
                category=office_cat,
                estimated_value=Decimal('5000.00'),
                items=[
                    ('A4 photocopier paper (cases)', 'CS', Decimal('40'),  Decimal('45.00')),
                    ('Ballpoint pens (boxes of 50)', 'BX', Decimal('20'),  Decimal('25.00')),
                    ('Stapler heavy-duty',           'EA', Decimal('15'),  Decimal('60.00')),
                ],
                publish_at=None, close_at=None,
            )
            # criteria but no invitees -> stays draft
            self._add_criteria(tenant, draft)

            # ---------- Event 2: Open ----------
            open_event = self._create_event(
                tenant, admin,
                title='Server hardware refresh',
                event_type='rfp',
                category=it_cat,
                estimated_value=Decimal('45000.00'),
                items=[
                    ('Rack-mount server (1U, 64GB RAM)', 'EA', Decimal('4'),  Decimal('5500.00')),
                    ('Network switch 48-port',           'EA', Decimal('2'),  Decimal('3200.00')),
                    ('UPS 3000VA',                       'EA', Decimal('2'),  Decimal('1800.00')),
                    ('Cabinet 42U',                      'EA', Decimal('1'),  Decimal('2500.00')),
                ],
                publish_at=timezone.now() - timedelta(days=3),
                close_at=timezone.now() + timedelta(days=10),
            )
            self._add_criteria(tenant, open_event)
            picked = active_vendors[:3]
            invite_vendors(open_event, [v.pk for v in picked], admin)
            publish_event(open_event, admin)
            # First vendor: draft bid with some prices
            b1 = start_bid(open_event, picked[0], admin)
            self._price_lines(b1, multiplier=Decimal('0.95'))
            # Second vendor: submitted bid
            b2 = start_bid(open_event, picked[1], admin)
            self._price_lines(b2, multiplier=Decimal('0.92'))
            b2.delivery_lead_time_days = 21
            b2.validity_days = 60
            b2.payment_terms = 'Net 30'
            b2.save()
            submit_bid(b2, admin)

            # ---------- Event 3: Awarded ----------
            awarded = self._create_event(
                tenant, admin,
                title='Janitorial services Q1 contract',
                event_type='tender',
                category=maint_cat,
                estimated_value=Decimal('12000.00'),
                items=[
                    ('Daily office cleaning (per month)', 'MO', Decimal('3'), Decimal('2800.00')),
                    ('Window cleaning quarterly',         'JOB', Decimal('1'), Decimal('1200.00')),
                ],
                publish_at=timezone.now() - timedelta(days=45),
                close_at=timezone.now() - timedelta(days=20),
            )
            self._add_criteria(tenant, awarded)
            picked_a = active_vendors[:3]
            invite_vendors(awarded, [v.pk for v in picked_a], admin)
            publish_event(awarded, admin)

            # Three submitted bids with varying prices.
            multipliers = [Decimal('0.95'), Decimal('0.85'), Decimal('1.05')]
            submitted_bids = []
            for vendor, mult in zip(picked_a, multipliers):
                b = start_bid(awarded, vendor, admin)
                self._price_lines(b, multiplier=mult)
                b.delivery_lead_time_days = 14
                b.validity_days = 90
                b.payment_terms = 'Net 30'
                b.save()
                submit_bid(b, admin)
                submitted_bids.append(b)

            # Close the event so bids are visible, then score them.
            awarded.status = 'closed'
            awarded.save(update_fields=['status', 'updated_at'])

            crit_objs = list(awarded.criteria.all())
            # Bid 0: best quality but expensive. Bid 1: best price. Bid 2: weakest.
            score_matrix = {
                0: {'price': 70, 'quality': 90, 'delivery': 80, 'compliance': 85},
                1: {'price': 95, 'quality': 75, 'delivery': 70, 'compliance': 80},
                2: {'price': 60, 'quality': 65, 'delivery': 60, 'compliance': 70},
            }
            for idx, bid in enumerate(submitted_bids):
                for crit in crit_objs:
                    score = Decimal(str(score_matrix[idx].get(crit.criterion_type, 70)))
                    record_evaluation(
                        bid=bid, criterion=crit, evaluator=admin,
                        score=score,
                        comment=f'Demo seed evaluation by {admin.username}',
                    )

            # Best score wins (likely bid 0 — price 70 * 0.4 + quality 90 * 0.25 + delivery 80*0.2 + compliance 85*0.15 = ~80)
            recompute_bid_scores(awarded)
            best_bid = sorted(submitted_bids, key=lambda b: b.overall_score, reverse=True)[0]
            recommend_award(
                awarded, best_bid.vendor,
                amount=best_bid.total_amount, user=admin,
                justification=(
                    f'Best overall weighted score ({best_bid.overall_score}) '
                    'with strong quality and acceptable price.'
                ),
            )
            finalize_award(awarded, admin)

            self.stdout.write(self.style.SUCCESS(
                f'    {tenant.name}: 3 events seeded (draft / open / awarded).'
            ))

        self.stdout.write(self.style.SUCCESS('Seeded sourcing data for all tenants.'))
        self.stdout.write(
            '\nLogin as a tenant admin (e.g. admin_acme / Welcome@123) to see the data.\n'
            'WARNING: Django superuser "admin" has no tenant — data will not appear there.\n'
        )

    # ----- helpers -----

    def _create_event(self, tenant, admin, *, title, event_type, category,
                      estimated_value, items, publish_at, close_at):
        ev = SourcingEvent.all_objects.create(
            tenant=tenant,
            event_number=next_event_number(tenant),
            title=title,
            description=f'Demo seed event for {title}.',
            event_type=event_type,
            category=category,
            currency='USD',
            estimated_value=estimated_value,
            status='draft',
            publish_at=publish_at,
            close_at=close_at,
            terms_and_conditions='Standard terms apply. Demo seed data.',
            created_by=admin,
        )
        for idx, (desc, uom, qty, price) in enumerate(items, start=1):
            SourcingEventItem.all_objects.create(
                tenant=tenant, event=ev, line_no=idx,
                item_description=desc, uom=uom,
                quantity=qty, est_unit_price=price,
            )
        return ev

    def _add_criteria(self, tenant, event):
        for idx, (name, ctype, weight, max_score) in enumerate(CRITERIA, start=1):
            SourcingCriterion.all_objects.create(
                tenant=tenant, event=event,
                name=name, criterion_type=ctype,
                weight=weight, max_score=max_score, order=idx,
            )

    def _price_lines(self, bid, multiplier=Decimal('1.0')):
        for line in bid.lines.all():
            line.unit_price = (
                (line.event_item.est_unit_price or Decimal('0')) * multiplier
            ).quantize(Decimal('0.01'))
            line.quantity_offered = line.event_item.quantity
            line.save(update_fields=[
                'unit_price', 'quantity_offered', 'updated_at',
            ])
        bid.recompute_total()
        bid.save(update_fields=['total_amount', 'updated_at'])
