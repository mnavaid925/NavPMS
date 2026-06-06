"""Seed Module 20 demo data: documents + versions (with indexed text) + best-practice templates.

Runs LAST in the orchestrator. Each document is seeded from a small in-memory text fixture so the
default mock text-extraction engine produces real, searchable ``extracted_text`` out of the box —
the full-text search at /dms/search/ works immediately with no extra dependency. Idempotent: skips a
tenant that already has document data unless ``--flush`` is passed.

Seeds, per tenant: 2 best-practice templates and 5 documents covering every status (a published
policy / spec / warranty / SOP plus a draft awaiting publication), each owned by the tenant admin.
"""
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant

from apps.dms import services
from apps.dms.models import Document, DocumentEvent, DocumentVersion, PolicyTemplate

TEMPLATES = [
    {
        'title': 'RFP Template — IT Services', 'category': 'rfp',
        'description': 'A reusable request-for-proposal skeleton for IT services engagements.',
        'body': ('1. Introduction & Background\n2. Scope of Work\n3. Mandatory Requirements\n'
                 '4. Evaluation Criteria (Price 40 / Quality 30 / Delivery 20 / Support 10)\n'
                 '5. Commercial Terms & Payment Schedule\n6. Submission Instructions & Deadline\n'
                 '7. Terms & Conditions'),
    },
    {
        'title': 'Bid Evaluation Scorecard Guide', 'category': 'evaluation',
        'description': 'How to score and weight competing bids consistently and defensibly.',
        'body': ('Score each criterion 0-100, multiply by its weight, and sum to a weighted total.\n'
                 'Document the rationale for every score. Two independent evaluators per bid.\n'
                 'Disqualify non-compliant bids before scoring. Record conflicts of interest.'),
    },
]

DOCUMENTS = [
    {
        'title': 'Procurement Policy Manual 2026', 'category': 'policy',
        'confidentiality': 'internal', 'tags': 'policy, limits, approval, purchasing',
        'summary': 'The master purchasing policy: approval limits, competitive-bid thresholds, ethics.',
        'filename': 'procurement-policy-2026.txt', 'publish': True,
        'body': ('PROCUREMENT POLICY MANUAL 2026\n\n'
                 'Approval limits: purchases up to 1,000 may be approved by a Buyer; up to 10,000 by '
                 'a Procurement Manager; above 10,000 require Director approval.\n'
                 'Competitive bids: three written quotes are required above 5,000.\n'
                 'Ethics: no employee may accept gifts that could influence a purchasing decision.\n'
                 'All suppliers must be screened against restricted-party lists before onboarding.'),
    },
    {
        'title': 'Standard Laptop Technical Specification', 'category': 'spec',
        'confidentiality': 'public', 'tags': 'laptop, hardware, specification, IT',
        'summary': 'Minimum technical specification for corporate laptop purchases.',
        'filename': 'laptop-specification.txt', 'publish': True,
        'body': ('CORPORATE LAPTOP SPECIFICATION\n\n'
                 'CPU: 8-core, 3.0 GHz minimum. RAM: 16 GB. Storage: 512 GB NVMe SSD.\n'
                 'Display: 14" 1920x1080. Battery: 10 hours. Warranty: 3 years on-site.\n'
                 'Compliance: ENERGY STAR, EPEAT Gold, ISO 9001 manufacturer.'),
    },
    {
        'title': 'Standard Equipment Warranty Terms', 'category': 'warranty',
        'confidentiality': 'internal', 'tags': 'warranty, guarantee, terms',
        'summary': 'The default warranty terms attached to capital-equipment purchase orders.',
        'filename': 'warranty-terms.txt', 'publish': True,
        'body': ('STANDARD WARRANTY TERMS\n\n'
                 'The supplier warrants all goods free from defects for 36 months from delivery.\n'
                 'Defective items are repaired or replaced within 10 business days at no cost.\n'
                 'The warranty period is suspended for the duration of any repair.'),
    },
    {
        'title': 'Supplier Onboarding SOP', 'category': 'sop',
        'confidentiality': 'restricted', 'tags': 'sop, onboarding, supplier, procedure',
        'summary': 'Step-by-step procedure for onboarding and approving a new supplier.',
        'filename': 'supplier-onboarding-sop.txt', 'publish': True,
        'body': ('SUPPLIER ONBOARDING SOP\n\n'
                 '1. Collect the supplier registration form and tax documents.\n'
                 '2. Run a restricted-party screening and a financial-risk check.\n'
                 '3. Verify bank details against an independent source.\n'
                 '4. Obtain category-manager approval before the first purchase order.'),
    },
    {
        'title': 'Draft Vendor Code of Conduct', 'category': 'policy',
        'confidentiality': 'internal', 'tags': 'draft, code of conduct, ethics',
        'summary': 'Awaiting legal review before publication.',
        'filename': 'vendor-code-of-conduct-draft.txt', 'publish': False,
        'body': ('VENDOR CODE OF CONDUCT (DRAFT)\n\n'
                 'Suppliers shall comply with all applicable labour, safety and anti-bribery laws.\n'
                 'This draft is pending legal review and is not yet in force.'),
    },
]


class Command(BaseCommand):
    help = 'Seed Module 20 demo data (documents + versions + indexed text + templates) per tenant.'

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
                self._flush(tenant)

            if Document.all_objects.filter(tenant=tenant).exists() and not flush:
                self.stdout.write(
                    f'  {tenant.name}: document data already exists — skipped (use --flush).')
                continue

            owner = next(
                (u for u in User.objects.filter(tenant=tenant, is_active=True) if u.is_tenant_admin),
                User.objects.filter(tenant=tenant, is_active=True).first(),
            )

            for spec in TEMPLATES:
                PolicyTemplate.all_objects.create(
                    tenant=tenant, template_number=services.next_template_number(tenant),
                    title=spec['title'], category=spec['category'],
                    description=spec['description'], body=spec['body'], status='published',
                    owner=owner)

            docs = 0
            for spec in DOCUMENTS:
                document = services.create_document(
                    tenant, title=spec['title'], category=spec['category'],
                    confidentiality=spec['confidentiality'], summary=spec['summary'],
                    tags=spec['tags'], owner=owner, user=owner)
                content = ContentFile(spec['body'].encode('utf-8'), name=spec['filename'])
                services.create_document_version(
                    document, content, owner, change_note='Initial version',
                    publish=spec['publish'])
                docs += 1

            self.stdout.write(
                f'  {tenant.name}: {docs} document(s), {len(TEMPLATES)} template(s).')

        set_current_tenant(None)
        self.stdout.write(self.style.SUCCESS('Documents & knowledge seeded.'))
        self.stdout.write(
            'Log in as a tenant admin (e.g. admin_acme / Welcome@123) and open /dms/ — '
            'the superuser "admin" has no tenant and sees no data.')

    def _flush(self, tenant):
        DocumentEvent.all_objects.filter(tenant=tenant).delete()
        # Break the Document <-> current_version cycle before deleting versions.
        Document.all_objects.filter(tenant=tenant).update(current_version=None)
        DocumentVersion.all_objects.filter(tenant=tenant).delete()
        Document.all_objects.filter(tenant=tenant).delete()
        PolicyTemplate.all_objects.filter(tenant=tenant).delete()
