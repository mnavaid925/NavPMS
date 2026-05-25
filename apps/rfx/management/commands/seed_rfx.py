"""Seed Module 7 demo data: 2 templates + 3 events per tenant
(draft RFI, open RFP with responses, completed RFQ with evaluations + shortlist)."""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.rfx.models import (
    RfxAnswer, RfxEvaluation, RfxEvent, RfxInvitee, RfxQuestion,
    RfxResponse, RfxSection, RfxTemplate, RfxTemplateQuestion,
    RfxTemplateSection,
)
from apps.rfx.services import (
    close_event, complete_event, create_event, create_event_from_template,
    invite_vendors, publish_event, record_evaluation,
    shortlist_response, start_response, submit_response,
)
from apps.vendors.models import Vendor, VendorCategory


# ---------- Template specs ----------

RFI_TEMPLATE = {
    'title': 'Standard supplier RFI',
    'description': 'Capability survey for new strategic suppliers.',
    'rfx_type': 'rfi',
    'sections': [
        {
            'title': 'Company profile',
            'questions': [
                ('Legal name and trading address', 'longtext', True, False, 0, 0),
                ('Year founded', 'number', True, False, 0, 0),
                ('Number of full-time employees', 'number', True, False, 0, 0),
            ],
        },
        {
            'title': 'Capabilities',
            'questions': [
                ('List your top 3 service categories', 'longtext', True, False, 0, 0),
                ('Do you hold ISO 9001 certification?', 'yes_no', True, False, 0, 0),
                ('Geographic regions you serve',
                 'multi_choice', True, False, 0, 0,
                 ['North America', 'EMEA', 'APAC', 'LATAM']),
            ],
        },
        {
            'title': 'References',
            'questions': [
                ('Provide 2-3 reference customers (name, contact, scope)',
                 'longtext', True, False, 0, 0),
                ('Upload reference letter (PDF)', 'file', False, False, 0, 0),
            ],
        },
    ],
}

RFP_TEMPLATE = {
    'title': 'IT services RFP',
    'description': 'Detailed proposal request for IT services engagements.',
    'rfx_type': 'rfp',
    'sections': [
        {
            'title': 'Company overview',
            'questions': [
                ('Company description and core services', 'longtext', True, False, 0, 0),
                ('Years in IT services', 'number', True, True, 10, 10),
            ],
        },
        {
            'title': 'Technical capability',
            'questions': [
                ('Describe your delivery methodology', 'longtext', True, True, 25, 5),
                ('How do you handle 24/7 incidents?', 'longtext', True, True, 20, 5),
                ('Tools / platforms you support',
                 'multi_choice', True, True, 15, 5,
                 ['AWS', 'Azure', 'GCP', 'On-premise', 'Kubernetes', 'VMware']),
            ],
        },
        {
            'title': 'Commercials',
            'questions': [
                ('Indicative monthly rate (USD)', 'number', True, True, 20, 5),
                ('Payment terms you accept', 'text', True, False, 0, 0),
                ('Are you open to SLA-based pricing?', 'yes_no', True, True, 10, 5),
            ],
        },
        {
            'title': 'References',
            'questions': [
                ('Upload latest financial statement (PDF)', 'file', False, False, 0, 0),
            ],
        },
    ],
}


class Command(BaseCommand):
    help = 'Seed Module 7 demo data (RFx events, templates, responses, evaluations).'

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
                RfxEvaluation.all_objects.filter(tenant=tenant).delete()
                RfxAnswer.all_objects.filter(tenant=tenant).delete()
                RfxResponse.all_objects.filter(tenant=tenant).delete()
                RfxInvitee.all_objects.filter(tenant=tenant).delete()
                RfxQuestion.all_objects.filter(tenant=tenant).delete()
                RfxSection.all_objects.filter(tenant=tenant).delete()
                RfxEvent.all_objects.filter(tenant=tenant).delete()
                RfxTemplateQuestion.all_objects.filter(tenant=tenant).delete()
                RfxTemplateSection.all_objects.filter(tenant=tenant).delete()
                RfxTemplate.all_objects.filter(tenant=tenant).delete()

            if RfxEvent.all_objects.filter(tenant=tenant).exists() and not options['flush']:
                self.stdout.write(
                    f'  {tenant.name}: RFx data already exists — skipped '
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
            if len(active_vendors) < 3:
                self.stdout.write(
                    f'    {tenant.name}: needs >= 3 active vendors — skipped. '
                    'Run seed_vendors first.'
                )
                continue

            self.stdout.write(f'  Seeding RFx data for {tenant.name}…')

            # ---------- Templates ----------
            rfi_tpl = self._create_template(tenant, admin, RFI_TEMPLATE)
            rfp_tpl = self._create_template(tenant, admin, RFP_TEMPLATE)

            it_cat = VendorCategory.all_objects.filter(
                tenant=tenant, code='IT',
            ).first()
            maint_cat = VendorCategory.all_objects.filter(
                tenant=tenant, code='MAINT',
            ).first()

            # ---------- Event 1: Draft RFI from template (no invitees) ----------
            create_event_from_template(
                rfi_tpl, admin,
                title='Strategic supplier capability survey',
            )

            # ---------- Event 2: Open RFP from template ----------
            open_evt = create_event_from_template(
                rfp_tpl, admin,
                title='ERP system selection 2026',
                publish_at=timezone.now() - timedelta(days=2),
                close_at=timezone.now() + timedelta(days=14),
            )
            if it_cat:
                open_evt.category = it_cat
                open_evt.save(update_fields=['category', 'updated_at'])
            invitees_open = active_vendors[:3]
            invite_vendors(open_evt, [v.pk for v in invitees_open], admin)
            # publish_at is already in the past -> publish_event auto-advances to 'open'
            publish_event(open_evt, admin)

            # Vendor A submits, vendor B leaves draft.
            r_a = start_response(open_evt, invitees_open[0], admin)
            self._fill_answers(r_a, scenario='strong')
            submit_response(r_a, admin)

            r_b = start_response(open_evt, invitees_open[1], admin)
            self._fill_answers(r_b, scenario='draft')
            # left as draft

            # ---------- Event 3: Completed RFQ ----------
            done_evt = create_event(
                tenant=tenant, user=admin,
                title='Office cleaning services quote',
                description='Sealed-bid quotation for office cleaning services.',
                rfx_type='rfq',
                category=maint_cat,
                publish_at=timezone.now() - timedelta(days=30),
                close_at=timezone.now() - timedelta(days=10),
                terms_and_conditions='Net 30 payment. 90-day quote validity.',
            )
            # Build a small 1-section questionnaire (4 scored questions).
            section = RfxSection.all_objects.create(
                tenant=tenant, event=done_evt,
                title='Quote details', position=1,
            )
            q_price = RfxQuestion.all_objects.create(
                tenant=tenant, section=section, position=1,
                prompt='Monthly rate (USD)',
                question_type='number',
                is_required=True, is_scored=True,
                weight=Decimal('40.00'), max_score=10,
            )
            q_avail = RfxQuestion.all_objects.create(
                tenant=tenant, section=section, position=2,
                prompt='Service availability (1=weekdays only, 5=24/7)',
                question_type='scale',
                is_required=True, is_scored=True,
                weight=Decimal('25.00'), max_score=5,
            )
            q_insur = RfxQuestion.all_objects.create(
                tenant=tenant, section=section, position=3,
                prompt='Do you carry public-liability insurance?',
                question_type='yes_no',
                is_required=True, is_scored=True,
                weight=Decimal('20.00'), max_score=5,
            )
            q_lead = RfxQuestion.all_objects.create(
                tenant=tenant, section=section, position=4,
                prompt='Start lead time (days)',
                question_type='number',
                is_required=True, is_scored=True,
                weight=Decimal('15.00'), max_score=10,
            )
            invitees_done = active_vendors[:3]
            invite_vendors(done_evt, [v.pk for v in invitees_done], admin)
            # publish_at is already in the past -> publish_event auto-advances to 'open'
            publish_event(done_evt, admin)

            # 3 submitted responses
            answer_specs = [
                # (price, availability, insurance_yn, lead_days)
                (Decimal('2400.00'), 5, 'yes', Decimal('14')),
                (Decimal('2600.00'), 4, 'yes', Decimal('7')),
                (Decimal('2200.00'), 3, 'no',  Decimal('30')),
            ]
            scored_questions = [q_price, q_avail, q_insur, q_lead]
            # Pre-defined scores (out of question.max_score) for the panel
            score_grids = [
                # vendor 1 (balanced - best overall)
                {q_price.pk: 8, q_avail.pk: 5, q_insur.pk: 5, q_lead.pk: 8},
                # vendor 2 (premium pricing, fast)
                {q_price.pk: 6, q_avail.pk: 4, q_insur.pk: 5, q_lead.pk: 10},
                # vendor 3 (cheap but no insurance)
                {q_price.pk: 9, q_avail.pk: 3, q_insur.pk: 0, q_lead.pk: 4},
            ]
            submitted_responses = []
            for vendor, (price, avail, insur, lead) in zip(invitees_done, answer_specs):
                resp = start_response(done_evt, vendor, admin)
                for ans in resp.answers.all():
                    if ans.question_id == q_price.pk:
                        ans.value_number = price
                    elif ans.question_id == q_avail.pk:
                        ans.value_number = Decimal(avail)
                    elif ans.question_id == q_insur.pk:
                        ans.value_text = insur
                    elif ans.question_id == q_lead.pk:
                        ans.value_number = lead
                    ans.save()
                submit_response(resp, admin)
                submitted_responses.append(resp)

            # Close → evaluate all scored questions → complete → shortlist top
            close_event(done_evt, admin)
            for resp, grid in zip(submitted_responses, score_grids):
                for question in scored_questions:
                    record_evaluation(
                        response=resp,
                        question=question,
                        evaluator=admin,
                        score=grid[question.pk],
                        comment='',
                    )
            complete_event(done_evt, admin)

            # Shortlist the top-ranked response.
            top = done_evt.responses.order_by('rank').first()
            if top:
                shortlist_response(top, admin, reason='Best balanced score on price/availability/insurance.')

            self.stdout.write(self.style.SUCCESS(
                f'    {tenant.name}: 2 templates + 3 events seeded.'
            ))

        self.stdout.write(self.style.SUCCESS('\n=== RFx seeding complete ==='))

    # ---------- Helpers ----------

    def _create_template(self, tenant, admin, spec):
        template = RfxTemplate.all_objects.create(
            tenant=tenant,
            title=spec['title'],
            description=spec.get('description', ''),
            rfx_type=spec['rfx_type'],
            is_shared=True,
            created_by=admin,
        )
        for idx, sec_spec in enumerate(spec['sections'], start=1):
            section = RfxTemplateSection.all_objects.create(
                tenant=tenant,
                template=template,
                title=sec_spec['title'],
                description=sec_spec.get('description', ''),
                position=idx,
            )
            for qidx, q in enumerate(sec_spec['questions'], start=1):
                prompt, qtype, is_required, is_scored, weight, max_score, *extras = q
                choices = extras[0] if extras else []
                RfxTemplateQuestion.all_objects.create(
                    tenant=tenant,
                    section=section,
                    prompt=prompt,
                    question_type=qtype,
                    is_required=is_required,
                    is_scored=is_scored,
                    weight=Decimal(weight),
                    max_score=int(max_score) or 5,
                    choices=list(choices),
                    position=qidx,
                )
        return template

    def _fill_answers(self, response, *, scenario):
        """Populate a response's answers with believable placeholder values."""
        for ans in response.answers.all():
            q = ans.question
            if scenario == 'draft' and q.position > 2:
                # leave second-half questions blank to model a draft
                continue
            if q.question_type in ('text', 'longtext'):
                ans.value_text = f'Demo answer for "{q.prompt[:40]}" — {scenario}.'
            elif q.question_type == 'number':
                ans.value_number = Decimal('5')
            elif q.question_type == 'scale':
                ans.value_number = Decimal('4')
            elif q.question_type == 'yes_no':
                ans.value_text = 'yes' if scenario == 'strong' else 'no'
            elif q.question_type == 'single_choice' and q.choices:
                ans.value_choices = [q.choices[0]]
            elif q.question_type == 'multi_choice' and q.choices:
                ans.value_choices = q.choices[:2]
            elif q.question_type == 'date':
                ans.value_date = timezone.now().date()
            ans.save()
