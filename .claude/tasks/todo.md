# Module 4 — Approval Workflow Engine

**Created:** 2026-05-22
**Scope:** New Django app `apps/approvals/` implementing the 5 PMS sub-modules of Module 4,
integrated with Module 3 requisitions.

| Sub-module | Implementation |
|-----------|----------------|
| Dynamic Routing Rules | `ApprovalRule` + `ApprovalStep` — conditions on amount range / department / category, ordered multi-step chains |
| Delegation of Authority | `ApprovalDelegation` — temporary reassignment of approval rights (delegator → delegate, date-bounded) |
| Approval History & Audit Trail | `ApprovalAction` — append-only log of every submit/approve/reject/delegate/escalate/comment |
| Escalation Management | `sla_hours` + `escalate_to` per step; `run_escalations` command + lazy sweep on inbox open |
| Mobile Approval Interface | Responsive card-based "My Approvals" inbox + mobile-friendly task review/decide page |

## Architecture decisions
- Submitting a requisition routes through the matching `ApprovalRule`; **falls back** to the
  existing Module 3 admin approve/reject when no rule matches.
- Steps name a **specific user** approver (+ optional `escalate_to` user).
- Escalation: `run_escalations` management command **and** lazy on-view sweep of the inbox.
- `ApprovalRequest` links directly to `requisitions.Requisition` (one document type today).
- Engine completion calls `requisitions.services.decide_requisition()` to set the
  requisition status — reuses Module 3, avoids duplication. Circular import avoided with
  lazy imports both ways.
- Reuse `TenantAwareModel`/`TimeStampedModel`, `record_audit`. Mounted at `/approvals/`.

## Models (`apps/approvals/models.py`)
1. **ApprovalRule** — name, document_type, description, is_active, priority, min_amount, max_amount, department, category.
2. **ApprovalStep** — rule FK, order, name, approver (user), sla_hours, escalate_to (user).
3. **ApprovalRequest** — requisition FK, rule FK, status (pending/approved/rejected/cancelled), current_step, submitted_by, completed_at.
4. **ApprovalTask** — request FK, step FK, order, name, assigned_to (effective approver), original_approver, status (pending/approved/rejected/escalated/skipped), acted_by, acted_at, comment, due_at, escalated_at.
5. **ApprovalAction** — request FK, task FK, actor, action, comment (append-only timeline).
6. **ApprovalDelegation** — delegator (user), delegate (user), start_date, end_date, reason, is_active.

## Tasks

### Backend — `apps/approvals/`
- [ ] `__init__.py`, `apps.py`
- [ ] `models.py` — 6 models
- [ ] `admin.py` — register all (rule + request with inlines)
- [ ] `forms.py` — ApprovalRule, ApprovalStep, ApprovalDelegation, TaskAction forms
- [ ] `services.py` — `match_rule`, `resolve_approver`, `start_approval`, `act_on_task`, `escalate_overdue`, `cancel_approval`, `record_action`
- [ ] `views.py` — rule CRUD + steps, delegation CRUD, request list/detail, inbox, task review/act, history
- [ ] `urls.py` — `app_name = 'approvals'`
- [ ] `migrations/__init__.py`
- [ ] `management/__init__.py`, `management/commands/__init__.py`
- [ ] `management/commands/seed_approvals.py` — idempotent: rules, steps, delegations, route submitted requisitions
- [ ] `management/commands/run_escalations.py` — escalate overdue tasks

### Templates — `templates/approvals/`
- [ ] `rules/list.html`, `rules/form.html`, `rules/detail.html`
- [ ] `delegations/list.html`, `delegations/form.html`
- [ ] `requests/list.html`, `requests/detail.html`
- [ ] `inbox.html` (mobile-friendly), `task_detail.html` (review/decide), `history.html`

### Module 3 integration (modified files)
- [ ] `apps/requisitions/services.py` — `submit_requisition` calls `start_approval` (lazy)
- [ ] `apps/requisitions/views.py` — `RequisitionDetailView` passes the `ApprovalRequest`
- [ ] `templates/requisitions/requisitions/detail.html` — show approval progress; gate the
      admin approve/reject fallback to "no engine request"

### Wiring (modified files)
- [ ] `config/settings.py` — add `'apps.approvals'`
- [ ] `config/urls.py` — `path('approvals/', include('apps.approvals.urls'))`
- [ ] `templates/partials/sidebar.html` — add Approvals entries to the Procurement section
- [ ] `apps/core/management/commands/seed_data.py` — add `seed_approvals` step
- [ ] `README.md` — structure, ToC, commands, seeded data, Module 4 section, routes, roadmap

### Verification
- [ ] `makemigrations approvals` + `migrate` + `seed_approvals` + `check`
- [ ] Smoke test: rule match, multi-step routing, approve advances step, final approve sets
      requisition approved, reject, delegation reassigns, escalation command + lazy sweep,
      fallback path when no rule matches

## Review

**Status: complete & verified (2026-05-23).**

- New app `apps/approvals/` — 6 models, the workflow engine (`services.py`: routing,
  delegation resolution, task progression, completion, escalation), full-CRUD views +
  inbox/task/history, urls, admin, `seed_approvals` + `run_escalations` commands.
- 10 templates under `templates/approvals/`.
- Module 3 integration: `submit_requisition` routes through the engine;
  `cancel_requisition`/`amend_requisition` withdraw in-flight approvals;
  `RequisitionDetailView` + requisition `detail.html` show approval progress and gate
  the admin approve/reject fallback to "no engine request".
- Wiring: `INSTALLED_APPS`, `/approvals/`, sidebar "Approvals" group, `seed_data`.
- `README.md` updated end to end (Module 4 → Shipped).

**Verification performed:**
- `manage.py check` — 0 issues.
- `makemigrations approvals` → `0001_initial` (6 models + 3 indexes); `migrate` OK.
- `seed_approvals` — rules/steps/delegation + routed 1 submitted requisition per tenant.
- Smoke test 1: all 12 GET routes returned HTTP 200; engine routed 3 seeded requisitions.
- Smoke test 2 (engine): 2-step routing → approve step 1 (pending) → approve step 2
  (request approved → requisition approved); reject (request + requisition rejected,
  later step skipped); delegation re-assigned a task to the delegate; overdue task
  escalated; no-rule case returned None (admin fallback). All passed.
- `run_escalations` command runs clean.

**Design notes:**
- `ApprovalRequest` → direct FK to `requisitions.Requisition` (one document type today).
- Circular import (requisitions ⇄ approvals services) avoided with lazy imports both ways.
- Tasks created upfront; `due_at` is stamped only when a step becomes active, so
  not-yet-reached steps are never counted overdue.
- Engine completion reuses Module 3's `decide_requisition()` — no duplicate status logic.

**Note:** `.claude/manual-tests/` changes + a stray `.tmp` file are from the user's
manual-test skill run — not part of this module and left untouched.

---

## Manual Test — Requisition Management (Module 3) — 2026-05-23

**Scope:** `/manual-test "Requisition Management"` → produced
`.claude/manual-tests/requisitions-manual-test.md` (145 test cases), then executed
the back-end-verifiable subset and fixed the defect found.

**Work done:**
- Built a 145-case manual test plan (auth, multi-tenancy, CRUD, search, pagination,
  filters, workflow, UI/UX, negative, integration), verified against the codebase.
- Auto-executed 60 cases via Django's test `Client` (throwaway harness, since removed).
- **Bug found & fixed — BUG-01:** creating an `AccountCode` with a `code` that already
  exists for the tenant raised a 500 `IntegrityError` instead of a clean form error.
  Root cause: `tenant` is excluded from `AccountCodeForm`, so `validate_unique()`
  skipped the `unique_together('tenant','code')` check.

**Fix:**
- `apps/requisitions/forms.py` — `AccountCodeForm` now takes a `tenant` kwarg and
  validates tenant-scoped code uniqueness in `clean_code()`.
- `apps/requisitions/views.py` — create & edit views pass `tenant=request.tenant`.

**Verification:**
- All 60 auto-executed cases PASS after the fix (0 fail); TC-CREATE-08 re-run →
  clean form error "An account code with this code already exists.", no 500.
- `seed_requisitions --flush` re-run to leave a clean data baseline.
- Lesson captured in `lessons.md` (unique_together + excluded-field 500 trap).

**Browser pass (Playwright + system Chrome):**
- Drove 43 more UI/UX cases at 1920×1080, 768×1024 and 375×667 mobile — page
  titles, sidebar, breadcrumbs, badge colours, confirm dialogs, console errors,
  pagination, filters, responsive layout. All 43 PASS after the fix below.
- **Bug found & fixed — BUG-02:** horizontal page overflow on mobile (≤992px).
  Two causes: (a) wide tables not wrapped in `.table-responsive`; (b) the theme
  rule `html[data-layout-position="fixed"] .app-sidebar { position: sticky }`
  overrode the mobile `position: fixed`, jamming the 260px sidebar in-flow.
- **Fix:** `static/css/style.css` — `.app-main { min-width: 0 }` + the mobile
  sidebar rule re-scoped to `html[data-layout-position] .app-sidebar`; five
  requisition list/detail tables wrapped in `.table-responsive`. The sidebar
  half is an app-wide layout defect — the CSS fix corrects it globally.
- Verified: every module page now `scrollWidth = 375` at a 375px viewport;
  desktop 1920px layout unchanged.

**Totals:** 103 / 145 cases executed (60 back-end + 43 browser), 0 fail,
2 bugs found & fixed (BUG-01, BUG-02). 42 cases still need a human (visual
judgement, double-submit timing, browser back/forward). GO-with-fixes.

