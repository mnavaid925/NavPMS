# Module 7 — RFx Management (RFI / RFP / RFQ)

**Created:** 2026-05-25
**Scope:** New Django app `apps/rfx/` implementing the 5 PMS sub-modules of Module 7.
Buyer-side surface at `/rfx/`; vendor-side response submission integrated into the existing
`/vendor-portal/` namespace (consistent with Module 6).

## Scope decisions (confirmed)

1. **New app `apps/rfx/`** — clean separation from `apps/sourcing/`. RFx is questionnaire-driven; Sourcing stays price-driven. Optional cross-link via `sourcing.SourcingEvent.rfx_event` FK in a follow-up commit.
2. **No award workflow** — RFx scores responses and shortlists top vendors only. Add a "Create Sourcing Event from RFx" action on the event detail to hand off to Module 6.
3. **Form-based builder with up/down reorder** — no drag-and-drop in v1. Position field + arrow-button reorder.

## Sub-module → implementation

| Sub-module | Implementation |
|------------|----------------|
| **Questionnaire Builder** | `RfxEvent` (`RFX-<SLUG>-NNNNN`, type RFI/RFP/RFQ) holds top-level event metadata. `RfxSection` groups questions into named blocks. `RfxQuestion` is one question with `question_type` (`text` / `longtext` / `number` / `single_choice` / `multi_choice` / `yes_no` / `scale` / `date` / `file`), `weight` (0-100, summed across event = 100 at publish), `max_score` (for `scale`, default 5), `choices` (JSONField list for choice types), `is_required`, `position`. Up/down reorder via dedicated POST endpoints. |
| **Response Collection** | `RfxInvitee` (vendor → event, status `invited → viewed → responded / declined / withdrawn`). Vendor portal route `/vendor-portal/rfx/` lists invitations; vendor "starts response" which creates a draft `RfxResponse` with one blank `RfxAnswer` per question. Per-answer file upload supported (`value_file` field on `RfxAnswer` for `file` question type). Sealed responses: buyer can't see contents until `event.status ∈ {closed, under_evaluation, completed, cancelled}`. |
| **Side-by-Side Comparison** | `/rfx/events/<pk>/responses/compare/` — table with vendors as columns and questions as rows. Renders raw answers for non-scored questions and aggregated `BidEvaluation`-style scores for scored ones. Sealed gate enforced before rendering. |
| **Scoring & Weighting** | `RfxEvaluation` is one score per `(response, question, evaluator)` — same panel-scoring shape as Module 6's `BidEvaluation`. Service `compute_overall_score(response) = Σ(question.weight × avg_evaluator_score / question.max_score)` for scored question types. Text/file answers can be marked "scored" via a per-question `is_scored` flag (default True for `scale` / `number` / `single_choice` / `multi_choice` / `yes_no`; False for `text` / `longtext` / `date` / `file`). Overall scores persisted on `RfxResponse.overall_score` + `rank`. |
| **RFx Template Library** | `RfxTemplate` (tenant, title, description, rfx_type, is_shared, archived). `RfxTemplateSection` + `RfxTemplateQuestion` mirror the event structure. Service `create_event_from_template(template, user)` clones template content into a fresh draft `RfxEvent`. Templates have their own CRUD UI at `/rfx/templates/`. |

## Architecture decisions

- **App mount:** `apps/rfx/` mounted at `/rfx/` in `config/urls.py`. Vendor-facing RFx routes mounted in the existing vendor portal urls (next to sourcing). No second portal shell.
- **Inheritance:** all tenant-scoped models extend `apps.core.models.TenantAwareModel` + `TimeStampedModel`. Auto-managed `tenant` FK + thread-local filtering (same as every other module).
- **Numbering:** `RFX-<SLUG>-NNNNN` per tenant, generated via `next_rfx_number(tenant)` — same pattern as `next_event_number` in sourcing services.
- **Status workflow (events):**
  - `draft` → `published` (validates: ≥1 section with ≥1 question, weights sum to 100 across all scored questions, ≥1 invitee, `publish_at` + `close_at` set)
  - `published` → `open` (manual "Open now"; v1 has no celery)
  - `open` → `closed` (manual or via `close_at` reached — manual only in v1)
  - `closed` → `under_evaluation` (auto on first `RfxEvaluation` save)
  - `under_evaluation` → `completed` (manual "Complete & shortlist" action by buyer; locks responses, persists final ranks)
  - any open status → `cancelled`
- **Status workflow (responses):**
  - `draft` (vendor working) → `submitted` (validates required answers; locks the response, sets `submitted_at`, updates invitee → `responded`)
  - `submitted` → `under_review` (auto on first evaluator save)
  - `under_review` → `shortlisted` / `rejected` (manual buyer action; only in `under_evaluation` or `completed` event state)
  - `draft` / `submitted` → `withdrawn` (vendor self-withdraw, only while event is `open`)
- **Sealed-response gate:** `response_visible_to(user, response)` returns True iff (a) the user is the vendor portal user who owns the response, or (b) the user can manage / evaluate AND `event.status ∈ {closed, under_evaluation, completed, cancelled}`. Mirror of `bid_visible_to` in sourcing.
- **Permission gate:**
  - Manage (create/edit/publish/close/shortlist): roles `tenant_admin`, `procurement_manager`, `buyer` + Django superuser + `is_tenant_admin`.
  - Evaluate (score responses): manage roles + `approver`.
  - Vendor portal: `User.vendor` users only see their own invitations/responses (enforced by existing `VendorPortalSandboxMiddleware`).
- **Integration with Module 3 (Requisitions):** optional FK `RfxEvent.source_requisition` (nullable) + service `create_rfx_from_requisition(req, user)` for traceability. Add a "Run an RFx" button on the requisition detail page when `status='approved'`. **Stretch goal — defer to follow-up PR if time-constrained.**
- **Integration with Module 6 (Sourcing):** the RFx event detail offers "Create Sourcing Event from RFx" when `status='completed'`. Pre-fills `SourcingEvent.title` and copies shortlisted vendor invitees. **Stretch goal — defer to follow-up PR if time-constrained.**
- **Audit:** every workflow transition writes to `tenants.AuditLog` via `record_audit()` — same pattern as Module 6.
- **No new dependencies.** No celery, no SortableJS. Bootstrap forms only.

## Models (`apps/rfx/models.py`)

1. **RfxEvent**
   - `event_number` (auto `RFX-<SLUG>-NNNNN`, unique per tenant)
   - `title`, `description`, `rfx_type` (`rfi`/`rfp`/`rfq`)
   - `category` FK to `vendors.VendorCategory` (nullable)
   - `currency` CHAR(3) default `USD`
   - `status` default `draft` — see workflow above
   - `publish_at`, `close_at` (DateTimeField, nullable until published)
   - `terms_and_conditions` (TextField)
   - `source_requisition` FK nullable
   - `created_by` FK to `accounts.User`
   - `unique_together = [('tenant', 'event_number')]`
   - `STATUS_CHOICES` exposed as class attribute (filter rule compliance)

2. **RfxSection**
   - `event` FK (`related_name='sections'`)
   - `title`, `description`, `position` int
   - `ordering = ['position', 'pk']`

3. **RfxQuestion**
   - `section` FK (`related_name='questions'`)
   - `prompt` (CharField 500), `help_text` (TextField blank)
   - `question_type` (CHOICES above), `is_required` bool, `is_scored` bool
   - `weight` Decimal(5,2) default 0 (0-100, validators)
   - `max_score` int default 5 (for `scale`)
   - `choices` JSONField (list of strings, blank=True for non-choice types)
   - `position` int
   - `ordering = ['position', 'pk']`

4. **RfxInvitee**
   - `event` FK (`related_name='invitees'`), `vendor` FK to `vendors.Vendor`
   - `status` (`invited`/`viewed`/`responded`/`declined`/`withdrawn`)
   - `invited_at`, `responded_at`, `invited_by` FK to `accounts.User`
   - `unique_together = [('event', 'vendor')]`

5. **RfxResponse**
   - `event` FK (`related_name='responses'`), `vendor` FK to `vendors.Vendor`
   - `submitted_by` FK to `accounts.User` (vendor portal user)
   - `status` (`draft`/`submitted`/`under_review`/`shortlisted`/`rejected`/`withdrawn`)
   - `submitted_at` (nullable), `withdrawn_at` (nullable)
   - `overall_score` Decimal(7,4) default 0
   - `rank` int default 0 (1-based, 0 = unranked)
   - `unique_together = [('event', 'vendor')]`

6. **RfxAnswer**
   - `response` FK (`related_name='answers'`), `question` FK
   - `value_text` (TextField blank)
   - `value_number` Decimal(14,4) nullable
   - `value_choices` JSONField (list of selected choice strings; blank=True)
   - `value_date` DateField nullable
   - `value_file` FileField (`upload_to='rfx_answers/'`, blank=True)
   - `unique_together = [('response', 'question')]`
   - `value(self)` property returns the appropriate field based on `question.question_type`.

7. **RfxEvaluation**
   - `response` FK, `question` FK, `evaluator` FK to `accounts.User`
   - `score` Decimal(7,4), validators 0-`question.max_score`
   - `comment` TextField blank
   - `unique_together = [('response', 'question', 'evaluator')]`

8. **RfxDocument** (buyer-side attachments — RFP brief PDF, spec sheet, etc.)
   - `event` FK (`related_name='documents'`), `title`, `file`, `uploaded_by`
   - `upload_to='rfx_docs/'`

9. **RfxTemplate**
   - `tenant`, `title`, `description`, `rfx_type`, `is_shared`, `archived`, `created_by`
   - `unique_together = [('tenant', 'title')]`

10. **RfxTemplateSection** — mirrors `RfxSection` (template FK + title + position).

11. **RfxTemplateQuestion** — mirrors `RfxQuestion` minus event coupling (template_section FK + prompt + type + weight + choices + position).

## Services (`apps/rfx/services.py`)

- Permission helpers: `can_manage_rfx(user)`, `can_evaluate(user)` (mirror sourcing).
- `response_visible_to(user, response)` — sealed gate.
- `next_rfx_number(tenant)` — `RFX-<SLUG>-NNNNN`.
- **Event lifecycle:** `publish_event`, `open_event`, `close_event`, `cancel_event`, `mark_under_evaluation`, `complete_event` (all transactional, all audit-logged, all validate the source status).
- **Template:** `create_event_from_template(template, user, target_title=None)` — clones sections + questions into a fresh draft RfxEvent.
- **Responses:** `start_response(event, vendor, user)` (creates draft + blank answers), `submit_response(response, user)` (validates required, locks), `withdraw_response(response, user)`.
- **Scoring:** `record_evaluation(response, question, evaluator, score, comment='')` (upsert; triggers `compute_overall_score` + `mark_under_evaluation`), `compute_overall_score(response)` (Σ weighted), `rank_responses(event)` (orders desc by `overall_score`, persists `rank`).
- **Shortlist:** `shortlist_response(response, user)`, `reject_response(response, user, reason='')`.
- **Reorder:** `move_section(section, direction)`, `move_question(question, direction)` — swap `position` with neighbour, atomic.
- **Stretch hand-off:** `create_sourcing_event_from_rfx(rfx_event, user)` — copies shortlisted vendors into a draft `SourcingEvent`. *Defer to a follow-up if scope creeps.*

## Forms (`apps/rfx/forms.py`)

- `RfxEventForm` — title, description, rfx_type, category, currency, publish_at, close_at, terms_and_conditions.
- `RfxSectionForm` — title, description.
- `RfxQuestionForm` — prompt, help_text, question_type, is_required, is_scored, weight, max_score, choices (CharField textarea, parsed into list).
- `RfxInviteeForm` — `vendor` ModelChoiceField filtered to active vendors of the tenant, excluding already-invited.
- `RfxDocumentForm` — title, file (size + type validation).
- `RfxAnswerForm` — dynamic field choice based on `question.question_type` (single-field form per question; templates iterate `for question, form in zip(...)`).
- `RfxEvaluationForm` — score + comment, score validators per question.
- `RfxTemplateForm`, `RfxTemplateSectionForm`, `RfxTemplateQuestionForm`.
- **Filter rule compliance:** form widgets pre-render `select` choices using Bootstrap classes; list-view filter dropdowns in templates use `|stringformat:"d"` for FK pks.

## Buyer views (`apps/rfx/views.py`)

Standard CRUD pattern (per CRUD Completeness Rules):

- Events: `event_list`, `event_create`, `event_detail`, `event_edit`, `event_delete`, plus lifecycle actions `event_publish`, `event_open`, `event_close`, `event_cancel`, `event_complete`.
- Sections inline on event detail: `section_create`, `section_edit`, `section_delete`, `section_move`.
- Questions inline: `question_create`, `question_edit`, `question_delete`, `question_move`.
- Invitees inline: `invitee_add`, `invitee_remove`.
- Documents inline: `document_add`, `document_delete`.
- Responses (sealed list / detail / compare / evaluate / shortlist / reject):
  - `response_list` (sealed until close)
  - `response_detail` (sealed gate)
  - `response_compare` (`events/<pk>/responses/compare/`)
  - `response_evaluate` (form per question)
  - `response_shortlist`, `response_reject`
- Templates: `template_list`, `template_create`, `template_detail`, `template_edit`, `template_delete`, plus `template_section_*` and `template_question_*` analogues.
- Use template: `event_use_template` (`/rfx/events/new/?from_template=<id>` — pre-fills from template via service call).
- Analytics: `analytics_dashboard` (`/rfx/analytics/`), `analytics_event_report` (`/rfx/events/<pk>/analytics/`).

Every list view: search (`?q=`) + filters (status, type, category) with hidden inputs in filter form so pagination retains state. Tenant filter enforced via `Model.objects.filter(tenant=request.tenant)` (defence-in-depth — thread-local manager also filters).

## Vendor portal views (`apps/rfx/portal_views.py`)

Mounted under the existing vendor portal namespace (`/vendor-portal/rfx/`):

- `rfx_inbox` — list of invitations for `request.user.vendor`.
- `event_view` — read-only RFx event (sections + questions; cannot see other vendors' responses).
- `response_form` — single-page form with one field per question, grouped by section. Saves draft on each submit.
- `response_submit` — POST endpoint that submits a draft (validates required).
- `response_withdraw` — POST endpoint.
- `my_responses` — list of vendor's own RFx responses (across all events).

## Templates (`templates/rfx/` + `templates/vendor_portal/rfx/`)

```
templates/rfx/
├── events/
│   ├── list.html
│   ├── form.html
│   ├── detail.html  (tabs: Sections, Invitees, Documents, Responses, Evaluation, Analytics)
│   └── delete_confirm.html  (POST-only delete, no separate page — see CRUD rule 4)
├── sections/
│   ├── form.html
│   └── _inline.html  (partial used inside event detail)
├── questions/
│   ├── form.html
│   └── _inline.html
├── invitees/
│   └── _inline.html
├── responses/
│   ├── list.html        (sealed-aware)
│   ├── detail.html      (sealed-aware)
│   ├── compare.html     (matrix table)
│   └── evaluate.html    (score form)
├── templates/
│   ├── list.html
│   ├── form.html
│   ├── detail.html
│   └── question_form.html
└── analytics/
    ├── dashboard.html
    └── event_report.html

templates/vendor_portal/rfx/
├── inbox.html
├── event.html       (read-only)
├── response.html    (vendor answer form)
└── my_responses.html
```

Every list page wired to Filter Implementation Rules (status_choices in context, FK querysets in context, hidden filter inputs in pagination links). Every detail page has Edit/Delete in the actions sidebar (conditional on status).

## Admin (`apps/rfx/admin.py`)

Register `RfxEvent`, `RfxTemplate`, `RfxResponse`, `RfxEvaluation`. Inlines: `RfxSection`/`RfxQuestion` under event, `RfxAnswer` under response.

## URLs

- Add `apps/rfx/urls.py` and mount in `config/urls.py` at `/rfx/` with `app_name='rfx'`.
- Add `apps/rfx/portal_urls.py` (or fold into existing vendor portal urls — match the Module 6 pattern) at `/vendor-portal/rfx/`.

## Sidebar / navigation

- Add an "RFx" sidebar group under the existing "Sourcing" group in `templates/partials/sidebar.html` (one nav item per: Events, Templates, Analytics). Visible only to users who pass `can_manage_rfx`.
- Add "RFx Invitations" + "My Responses" to the vendor portal sidebar.

## Migrations

- `apps/rfx/migrations/0001_initial.py` — generated via `python manage.py makemigrations rfx`.
- No data migrations in v1.

## Seed data (`apps/rfx/management/commands/seed_rfx.py`)

Per tenant:
- 2 templates: "Standard supplier RFI" (3 sections, 8 questions) and "IT services RFP" (4 sections, 12 questions, weights summing to 100).
- 3 events:
  - Draft RFI ("Strategic supplier capability survey") — built from "Standard supplier RFI" template, no invitees yet.
  - Open RFP ("ERP system selection 2026") — built from "IT services RFP" template, 3 invitees, 1 submitted response + 1 draft response.
  - Completed RFQ ("Office cleaning services quote") — 4 questions, 3 submitted responses, full evaluations, ranked, top vendor shortlisted.

Idempotent: skip if `RfxEvent.objects.filter(tenant=tenant).exists()`. Use `get_or_create` where unique constraints exist; for `RFX-...` numbered events, check existence by number first.

Chain into `seed_data` orchestrator: `seed_plans → seed_tenants → seed_users → seed_portal → seed_requisitions → seed_approvals → seed_vendors → seed_sourcing → seed_rfx`.

## Tests (`apps/rfx/tests/`)

Mirroring Modules 1-6 layout:

- `conftest.py` — fixtures: `tenant`, `tenant_admin_user`, `client_tenant_admin`, `vendor`, `vendor_user`, `client_vendor`, `rfx_event_factory`.
- `test_models.py` — auto-numbering, unique constraints, choice values, `RfxAnswer.value` dispatch, score validators, ranking.
- `test_services.py` — publish validation (weights must sum to 100), lifecycle transitions, sealed gate, `start_response` blank-answer creation, `submit_response` required-validation, `compute_overall_score` math, `rank_responses`, template cloning.
- `test_views.py` — full CRUD + permission gates + sealed responses + filter retention.
- `test_security.py` — OWASP-aligned: A01 IDOR (cross-tenant + cross-vendor response access), A03 XSS escape in prompts/answers, A04 mass-assignment on score field, A07 anonymous-user 302 to login, CSRF on POST endpoints, file-upload size + content-type cap on `RfxAnswer.value_file` and `RfxDocument.file`.

Target line coverage ≥ 90% per file (matching Modules 1-4).

## Files to create

```
apps/rfx/
├── __init__.py                                (empty)
├── apps.py                                    (AppConfig name='apps.rfx')
├── admin.py
├── forms.py
├── models.py
├── services.py
├── urls.py
├── portal_urls.py                             (or extend apps/vendors/portal_urls.py — TBD during impl)
├── views.py
├── portal_views.py
├── management/__init__.py                     (empty)
├── management/commands/__init__.py            (empty)
├── management/commands/seed_rfx.py
├── migrations/__init__.py                     (empty)
└── migrations/0001_initial.py                 (generated)

apps/rfx/tests/
├── __init__.py                                (empty)
├── conftest.py
├── test_models.py
├── test_services.py
├── test_views.py
└── test_security.py

templates/rfx/                                 (~22 templates per layout above)
templates/vendor_portal/rfx/                   (~4 templates)
```

## Files to modify

- `config/settings.py` — append `'apps.rfx'` to `INSTALLED_APPS`.
- `config/urls.py` — add `path('rfx/', include('apps.rfx.urls'))` and the vendor portal RFx routes.
- `apps/core/management/commands/seed_data.py` — chain `seed_rfx`.
- `templates/partials/sidebar.html` — add RFx nav group (buyer side + vendor portal additions).
- `README.md` — add Module 7 section, update Project Structure tree, update Roadmap (mark complete), update Management Commands table, update Routes table, update Seeded Demo Data, update Module 6 references with the new RFx → Sourcing hand-off link.

## Implementation order (checklist)

### Phase 1 — Skeleton & models
- [ ] Create `apps/rfx/` package (apps.py, empty __init__.py)
- [ ] Add `apps.rfx` to `INSTALLED_APPS`
- [ ] Write `apps/rfx/models.py` with all 11 models + constants
- [ ] Generate `0001_initial` migration
- [ ] Migrate, verify no errors

### Phase 2 — Services
- [ ] Permission helpers + sealed gate
- [ ] Numbering helper
- [ ] Lifecycle transitions for events
- [ ] Lifecycle transitions for responses
- [ ] Scoring + ranking
- [ ] Template cloning
- [ ] Reorder helpers

### Phase 3 — Forms & buyer URLs/views
- [ ] All forms in `forms.py`
- [ ] `urls.py` with full route set
- [ ] All buyer views + tenant filter + role gate
- [ ] All buyer templates (events/sections/questions/invitees/docs/responses/templates/analytics)
- [ ] Sidebar nav

### Phase 4 — Vendor portal
- [ ] `portal_views.py`
- [ ] Vendor portal URL registration
- [ ] Vendor portal templates
- [ ] Vendor sidebar additions
- [ ] Sandbox middleware compatibility check

### Phase 5 — Admin & seed
- [ ] `admin.py`
- [ ] `seed_rfx.py` (idempotent)
- [ ] Wire into `seed_data` orchestrator

### Phase 6 — Tests
- [ ] conftest fixtures
- [ ] test_models
- [ ] test_services (incl. sealed gate, weight validation, scoring math)
- [ ] test_views (incl. permission gates, filter retention)
- [ ] test_security (IDOR, XSS, CSRF, file upload, mass-assignment)
- [ ] Run pytest — all green

### Phase 7 — Docs & polish
- [ ] README update (all six locations listed above)
- [ ] Manual smoke test: superuser login → tenant admin login → RFx event lifecycle end-to-end including vendor portal submission
- [ ] Final per-file commit snippet block (PowerShell-compatible)

## Open scope notes

- **Stretch goal 1 — Module 3 hand-off** (`create_rfx_from_requisition`). Defer if Phases 1-7 take a full session.
- **Stretch goal 2 — Module 6 hand-off** (`create_sourcing_event_from_rfx`). Defer same.
- **No drag-and-drop reorder in v1** — confirmed.
- **No award workflow** — confirmed; responses are scored, shortlisted, and that's the end of the RFx lifecycle.
- **No email notifications** — vendor sees invitations in their portal only. Email backend wiring is a project-wide gap (placeholder console email backend); pick that up cross-module later.

## Review / Verification

**Completed:** 2026-05-26

### What shipped
- **App layout:** new `apps/rfx/` mounted at `/rfx/`; vendor portal routes mounted under existing `/vendor-portal/rfx/`. Sidebar updated on both shells.
- **11 models** as planned (incl. `RfxEvent`, `RfxSection`, `RfxQuestion`, `RfxInvitee`, `RfxResponse`, `RfxAnswer`, `RfxEvaluation`, `RfxDocument`, `RfxTemplate`, `RfxTemplateSection`, `RfxTemplateQuestion`).
- **Service layer** with permission helpers, sealed-response gate, numbering, full event + response lifecycle, panel scoring, ranking, shortlist/reject, section/question reorder, template clone (both directions), and analytics helpers.
- **30 buyer views + 7 vendor portal views** + dynamic per-question answer form handling.
- **20 templates** (16 buyer + 4 vendor portal), all using project conventions (Bootstrap 5, RemixIcon, crispy forms, soft badges, action sidebars).
- **Seed command** `seed_rfx` producing 2 templates + 3 events per tenant (draft RFI, open RFP with responses, completed RFQ with shortlist) — idempotent + `--flush` supported. Chained into `seed_data` orchestrator.
- **Test suite** at [apps/rfx/tests/](apps/rfx/tests/): 102 tests across `test_models` (14), `test_services` (45), `test_views` (24), `test_security` (19). Full project suite: 355 passing, 0 regressions.

### Deviations from plan
- **`unique_together` on `(event|section, position)` dropped** for `RfxSection` / `RfxQuestion` / `RfxTemplateSection` / `RfxTemplateQuestion` so single-transaction position swaps in `move_section` / `move_question` don't violate the constraint. Position is a sort hint, not a natural key — matches Module 6's `SourcingCriterion.order` pattern.
- **`source_requisition` FK on `RfxEvent`** included as planned (cheap nullable FK), but the `create_rfx_from_requisition` service and "Run an RFx" button on requisition detail are deferred — confirmed stretch goal.
- **`create_sourcing_event_from_rfx` (Module 6 hand-off)** deferred — confirmed stretch goal.
- **Custom templatetag** `apps/rfx/templatetags/rfx_tags.py` added with a `get_item` filter so the response detail / evaluate / compare templates can look up per-question answers and scores by pk. Not in original plan but cleaner than restructuring every view's context.

### Verified
- `python manage.py check` clean post each phase.
- `python manage.py seed_rfx` + `seed_rfx --flush` produce 3 events × 3 tenants × correct status distribution + 12 evaluations + 2 templates per tenant.
- `pytest apps/rfx/tests/` → 102 passed.
- `pytest` (full project) → 355 passed.
- Sealed-gate logic verified by `test_sealed_gate_*` tests covering vendor-self / buyer-pre-close / buyer-post-close / other-vendor / requester scenarios.
- Cross-tenant IDOR verified by `test_cross_tenant_*` tests on event / edit / delete / question routes.
- XSS escape verified by `test_*_is_escaped_*` tests (event title, question prompt).

### Files touched
- **New:** 11 backend modules (forms, urls, views, portal_views, admin, services, models, apps, templatetags/rfx_tags.py, 5 test files, seed command) + 20 templates + 1 plan doc.
- **Modified:** `config/settings.py` (Phase 1 — INSTALLED_APPS), `config/urls.py` (mount /rfx/), `apps/vendors/portal_urls.py` (vendor portal routes), `apps/core/management/commands/seed_data.py` (chain seed_rfx), `templates/partials/sidebar.html` (RFx nav), `templates/vendor_portal/base.html` (RFx links), `README.md` (Module 7 section + roadmap + routes + seed + structure + tests + commands).
