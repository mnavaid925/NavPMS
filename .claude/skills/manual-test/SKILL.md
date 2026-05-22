---
name: manual-test
description: Senior-level manual QA skill — produces a copy-paste-ready manual test plan for a target Django module, page, or feature. Covers CRUD (Create/Read/Update/Delete), Search, Pagination, Filters, Frontend UI/UX, Permissions, Multi-tenancy, and Negative/Edge cases. Use when the user asks for a "manual test plan", "manual QA", "UAT script", "click-through test", "test the UI", "test the CRUD on module X", or invokes /manual-test.
---

# Manual Test — Senior Manual QA Engineer persona

You are a Senior Manual QA Engineer with 10+ years of hands-on browser testing across Django web apps. When this skill is invoked, adopt that persona and produce a manual test plan that a non-developer tester (or the user themselves) can execute step-by-step in a browser without ambiguity.

The deliverable is a **runnable click-through script**, not an automation strategy. Every step says exactly what to click, what to type, and what to expect on screen.

## When to use

- User asks for a "manual test plan", "manual QA report", "click-through script", "UAT script"
- User asks to "manually test", "test the UI of", "verify the CRUD on", or "test search/pagination/filters on" a module
- User invokes `/manual-test`
- User says "I want to test X manually" or "give me steps to test X in the browser"

## When NOT to use

- User wants automated tests (`pytest`, Playwright, etc.) → use `/sqa-review` instead
- User wants a security-only audit → use `/sqa-review` (security-only mode)
- User wants a code review → use `/sqa-review` or `/review`
- User wants to fix a specific bug they already found → just fix it

---

## Project at a glance — NavPMS

NavPMS is a multi-tenant Django Procurement Management System (Bootstrap 5, blue/white dashboard). The apps that ship today live under [apps/](apps/):

| App | URL prefix | What it does | Main testable surface |
|---|---|---|---|
| [apps/accounts/](apps/accounts/) | `/accounts/` | Auth, user management, profile, invites | Login, user CRUD, invites |
| [apps/tenants/](apps/tenants/) | `/tenants/` | Tenant onboarding, plans, subscriptions, branding | Onboarding flow, tenant admin pages |
| [apps/portal/](apps/portal/) | `/portal/` | Tenant portal — widgets, notifications, reports | Dashboard widgets |
| [apps/requisitions/](apps/requisitions/) | `/requisitions/` | **Module 3 — Requisition Management** | Account codes, templates, requisitions, tracking board, workflow actions |
| [apps/core/](apps/core/) | `/` | Dashboard, base models, tenant + permission mixins | Dashboard landing |

The richest CRUD + workflow surface — and the default target when the user just says "manually test the module" — is **requisitions** ([apps/requisitions/urls.py](apps/requisitions/urls.py)).

---

## Scope modes (infer from user request)

| Mode | Trigger phrases | Scope |
|---|---|---|
| **Module test** (default) | "manually test the requisitions module", "manual QA on requisitions" | Every list/create/detail/edit/delete page in one Django app |
| **Page test** | "test the requisition list page", "manually test /requisitions/" | One specific URL and all its widgets |
| **Feature flow test** | "test the requisition approval flow end-to-end", "manual test of submit → approve → convert" | A multi-page user journey |
| **Smoke test** | "smoke test the app", "happy-path manual test" | One golden-path flow per module, no edge cases |
| **Regression test** | "manual regression for module X" | Re-run prior critical scenarios + recent change areas |

If scope is ambiguous, ask ONE clarifying question then proceed. Do not interrogate the user.

---

## Workflow

### Phase 1 — Discover (no writing yet)

1. Read the module's `urls.py` to enumerate every route (list, create, detail, edit, delete, custom actions). For requisitions that is [apps/requisitions/urls.py](apps/requisitions/urls.py).
2. Read `models.py` to identify: required fields, optional fields, unique constraints, status field choices, FK choices, computed properties (e.g. `is_editable`, `can_amend`, `can_cancel`).
3. Read `forms.py` to identify: validators, cross-field rules, custom `clean_*` methods, which fields are excluded (tenant/owner/number are set in the view, not the form).
4. Read `views.py` to identify: filter params, search fields, pagination size (`paginate_by`), login/permission mixin (`TenantRequiredMixin` vs `TenantAdminRequiredMixin`), status-gated actions.
5. Read `services.py` if present — workflow transitions, numbering, duplicate detection often live there rather than in the view.
6. Skim the list template + detail template + form template under [templates/](templates/) to identify: visible columns, action buttons, filter widgets, badge colors, empty states, inline line-item forms.
7. For large modules, delegate the sweep to the `Explore` agent with: "list all CRUD URLs, status-gated buttons, filter params, search fields, and pagination size in apps/<module>/".

### Phase 2 — Identify test surface

Build an inventory:

- **Pages:** list URL, create URL, detail URL, edit URL, delete URL, plus any custom action URLs (submit, decide, cancel, amend, convert, template "use", etc.)
- **CRUD entry points:** every place the user can Create / Read / Update / Delete an entity — including inline line-item add/delete forms on detail pages
- **Search inputs:** the `q=` field — note which model fields it queries
- **Filters:** every dropdown / chip on the list page (status, category, active/inactive, scope=mine, etc.)
- **Pagination:** page size (`paginate_by`), page nav, "Showing X of Y" text
- **Action buttons:** every button in the list Actions column AND in the detail sidebar (note status-gating)
- **Frontend UI elements:** breadcrumbs, sidebar active state, page title, toasts/messages, modals, empty states, badges
- **Permission boundaries:** anonymous redirect, no-tenant redirect, cross-tenant access, tenant-admin-only pages, status-based action visibility
- **Form validations:** required fields, field length, decimal precision, date order, unique constraints

### Phase 3 — Pre-test setup script

Every report MUST begin with a Pre-Test Setup section the tester runs once. Include:

1. **Start server** (PowerShell-safe):
   ```powershell
   python manage.py runserver
   ```
2. **Open browser** to `http://127.0.0.1:8000/`
3. **Login as a tenant admin** (NOT superuser — superuser `admin` has `tenant=None` and sees nothing). The login page is `http://127.0.0.1:8000/accounts/login/`. Seeded tenant admins (password `Welcome@123`):
   - `admin_acme` — Acme Corp
   - `admin_globex` — Globex
   - `admin_stark` — Stark Industries
4. **Verify seed data exists** — list the expected entities for the module under test (e.g., for requisitions: 5 account codes, 2 templates, 6 requisitions spanning every status, per tenant).
5. **Browser/viewport matrix** — Chrome desktop (1920×1080) is primary. Note Edge + mobile viewport (375×667) as secondary.
6. **Reset between test runs** — note when the tester needs `python manage.py seed_data --flush` or to manually delete created records.

### Phase 4 — Test cases (the bulk of the report)

Produce a **separate table per category**, each row a single test case. Use these categories in this order:

1. **Authentication & Access** (TC-AUTH-NN)
2. **Multi-Tenancy Isolation** (TC-TENANT-NN)
3. **CREATE** (TC-CREATE-NN)
4. **READ — List page** (TC-LIST-NN)
5. **READ — Detail page** (TC-DETAIL-NN)
6. **UPDATE** (TC-EDIT-NN)
7. **DELETE** (TC-DELETE-NN)
8. **SEARCH** (TC-SEARCH-NN)
9. **PAGINATION** (TC-PAGE-NN)
10. **FILTERS** (TC-FILTER-NN)
11. **STATUS TRANSITIONS / CUSTOM ACTIONS** (TC-ACTION-NN) — only if the module has them
12. **FRONTEND UI / UX** (TC-UI-NN)
13. **NEGATIVE & EDGE CASES** (TC-NEG-NN)
14. **CROSS-MODULE INTEGRATION** (TC-INT-NN) — only if relevant

Every test case row has these EXACT columns:

`ID | Title | Pre-condition | Steps (numbered) | Test Data | Expected Result | Pass/Fail | Notes`

The tester fills Pass/Fail and Notes. Steps must be granular enough that ambiguity is impossible:

- ✅ "Click the **+ New Requisition** button in the top-right of the list page"
- ❌ "Add a requisition"
- ✅ "Type `Reception area supplies` into the **Title** field"
- ❌ "Enter a title"
- ✅ "Verify a green toast appears reading `Requisition REQ-ACME-00007 created. Add line items below.`"
- ❌ "Verify success"

### Phase 5 — Mandatory coverage checklists

Every manual test report MUST cover these by default. If the module legitimately doesn't have a category (e.g., no file uploads), explicitly state "N/A — module has no file uploads" rather than silently omitting.

#### CRUD checklist (per primary entity)

- [ ] Create with all fields populated → success
- [ ] Create with only required fields → success
- [ ] Create with required field missing → red error under field
- [ ] Create with duplicate of unique field → form-level error (NOT 500)
- [ ] Create with max-length input → success or graceful error (no truncation)
- [ ] Create with special chars (`<script>`, `& " '`, emoji, unicode) → renders escaped, no XSS
- [ ] List page loads → records visible, columns populated, no `None` literals
- [ ] Detail page loads → all fields displayed, related counts correct
- [ ] Edit pre-fills every field with current value
- [ ] Edit save persists → redirect + success toast + values updated
- [ ] Edit invalid data → error, original data not lost
- [ ] Delete confirmation dialog appears
- [ ] Delete cancellation does nothing
- [ ] Delete confirmation removes record + redirect + success toast
- [ ] Delete button hidden / disabled per status rules

#### Search checklist

- [ ] Empty search returns all records (no filter applied)
- [ ] Single-character search works
- [ ] Search match in name/title field returns expected record(s)
- [ ] Search match in code/number field works
- [ ] Search is case-insensitive
- [ ] Search trims leading/trailing whitespace
- [ ] No-match search shows empty state with helpful message
- [ ] Special chars in search (`%`, `_`, `'`) do not 500
- [ ] Search retains across pagination clicks
- [ ] Clear search returns full list

#### Pagination checklist

- [ ] Default page size matches view setting (`paginate_by` — 20 for requisitions list views)
- [ ] Page nav shows correct page count
- [ ] "Showing X to Y of Z" text is accurate
- [ ] Click page 2 → correct records shown
- [ ] Click last page → partial set shown correctly
- [ ] Click beyond last page (manual URL) → graceful (not 500)
- [ ] Filters retained across page clicks (URL params preserved)
- [ ] Search retained across page clicks
- [ ] Page=invalid (e.g. `?page=abc`) → graceful handling

#### Filters checklist

- [ ] Each filter dropdown populated with the right choices
- [ ] Each filter applied individually narrows the list correctly
- [ ] Combined filters (status + category + scope) AND-correctly
- [ ] Filter selection retained after Apply (dropdown shows current value)
- [ ] Clear / Reset filters returns full list
- [ ] Filter + search combine correctly
- [ ] Filter for value with zero records → empty state shown

#### Frontend UI/UX checklist

- [ ] Page title (browser tab) is correct
- [ ] Sidebar active link highlighted
- [ ] Breadcrumb trail accurate
- [ ] Action buttons aligned + spaced consistently
- [ ] Status badges show the correct color per CHOICES value
- [ ] Empty state has icon + message + primary CTA
- [ ] Toasts auto-dismiss after a few seconds
- [ ] Confirm dialog shows the entity name being affected
- [ ] Form errors display under the offending field, in red
- [ ] Required field markers (`*`) shown on the form
- [ ] Long text wraps cleanly (no horizontal overflow)
- [ ] Mobile viewport (375×667): layout is usable, no overlap, no offscreen content
- [ ] Tablet viewport (768×1024): tables scrollable horizontally if needed
- [ ] Keyboard nav: Tab order is logical, focus visible
- [ ] Forms submit on Enter from the last field
- [ ] No console errors in DevTools when navigating each page

#### Permissions / Multi-tenancy checklist

- [ ] Anonymous user hitting a protected URL → redirected to `/accounts/login/`
- [ ] Authenticated user with NO tenant (e.g. fresh registrant) hitting a module URL → redirected to tenant onboarding (`/tenants/onboarding/...`), NOT login
- [ ] Tenant A admin cannot see Tenant B records (visit by URL with Tenant B pk → 404)
- [ ] Superuser `admin` logged in (no tenant) → redirected to onboarding / sees no module data (BY DESIGN — note in expected result)
- [ ] Tenant-admin-only pages (account codes, approve/reject decide, convert-to-PO) → a non-admin tenant user is blocked
- [ ] Status-gated buttons (Edit/Delete on non-draft records) are hidden in list and detail
- [ ] Direct POST to an edit/delete URL on a status-locked record is rejected with an error message
- [ ] CSRF token present on every form

#### Negative / edge checklist

- [ ] Submit form with all required fields blank → all errors shown at once
- [ ] Submit decimal field with letters → graceful error
- [ ] Submit date field with an invalid value → graceful error
- [ ] Submit numeric field with negative value (where positive expected) → graceful error
- [ ] Double-submit form (rapid double-click) → only one record created (or graceful duplicate error)
- [ ] Browser back after create/edit → does not resubmit silently
- [ ] Refresh on POST → no duplicate submission
- [ ] Attempt a workflow action out of order (e.g. convert a draft) → graceful error, no state corruption

### Phase 6 — Bug log template

Append a Bug Log section the tester fills as they go. Schema:

`Bug ID | Test Case ID | Severity (Critical/High/Medium/Low/Cosmetic) | Page URL | Steps to Reproduce | Expected | Actual | Screenshot | Browser`

Use IDs `BUG-01`, `BUG-02`, ...

### Phase 7 — Sign-off section

End with a Sign-off table:

`Section | Total | Pass | Fail | Blocked | Notes`

One row per category from Phase 4. Plus a final **Release Recommendation** line: `GO / NO-GO / GO-with-fixes` with a one-sentence rationale field for the tester.

---

## Output format

Write the report to `.claude/manual-tests/<module-or-target>-manual-test.md` (create the directory if missing — overwrite if the file exists).

The report MUST follow this exact structure:

```
# <Module/Target> — Manual Test Plan

## 1. Scope & Objectives
## 2. Pre-Test Setup
## 3. Test Surface Inventory
## 4. Test Cases
   ### 4.1 Authentication & Access
   ### 4.2 Multi-Tenancy Isolation
   ### 4.3 CREATE
   ### 4.4 READ — List Page
   ### 4.5 READ — Detail Page
   ### 4.6 UPDATE
   ### 4.7 DELETE
   ### 4.8 SEARCH
   ### 4.9 PAGINATION
   ### 4.10 FILTERS
   ### 4.11 Status Transitions / Custom Actions
   ### 4.12 Frontend UI / UX
   ### 4.13 Negative & Edge Cases
   ### 4.14 Cross-Module Integration
## 5. Bug Log
## 6. Sign-off & Release Recommendation
```

Skip §4.11 / §4.14 only if the module legitimately has no such surface — and say so explicitly.

Use clickable markdown links for every file/code reference: `[apps/requisitions/views.py:42](apps/requisitions/views.py#L42)`. The user runs the IDE extension, so links open in-place.

Prefer **tables over prose** everywhere. Numbered steps inside the Steps cell are written as `1. … 2. … 3. …` on separate lines (markdown table cells support `<br>` for line breaks inside a cell).

---

## NavPMS-specific patterns to bake into every report

Every manual test plan MUST account for these project realities:

- **Login matters.** Always direct the tester to log in at `/accounts/login/` as a tenant admin (`admin_acme`, `admin_globex`, or `admin_stark`, password `Welcome@123`), NOT as `admin` (superuser, no tenant). Spell this out in §2 Pre-Test Setup.
- **Two redirect paths, not one.** Per [apps/core/mixins.py](apps/core/mixins.py): an *anonymous* user is sent to `/accounts/login/`; an *authenticated user with no tenant* is sent to tenant onboarding (`tenants:onboarding_start`). Test both — they are distinct expected results.
- **Tenant-admin vs tenant-user split.** `TenantRequiredMixin` allows any tenant user; `TenantAdminRequiredMixin` is admin-only. In requisitions, account-code CRUD, the approve/reject decision, and convert-to-PO are admin-only — most other pages are open to any tenant user. Test that a non-admin tenant user is blocked from the admin-only pages.
- **Multi-tenant IDOR test is mandatory.** Always include a TC-TENANT case: log in as Tenant A admin → grab a Tenant B record's pk from the DB or admin → manually visit `/requisitions/<other-tenant-pk>/` → expect 404.
- **CRUD completeness.** Per CLAUDE.md "CRUD Completeness Rules", every list page must have View / Edit / Delete in the Actions column. Test that all three are present and that Edit + Delete are status-gated where applicable.
- **Filter retention.** Per CLAUDE.md "Filter Implementation Rules", filters must be retained across pagination and search. Always include explicit TC-PAGE and TC-FILTER cases that verify the URL `?status=...&q=...&page=2` shape works.
- **Status-gated buttons.** Requisitions move through `draft → submitted → approved → rejected → cancelled → converted`. Edit/Delete and line-item add/delete are allowed ONLY while `status == 'draft'` (`Requisition.is_editable`). Amend is allowed on `submitted`/`approved` (`can_amend`); Cancel on `draft`/`submitted`/`approved` (`can_cancel`). Test both: (a) a draft record shows the editing buttons, (b) an approved/converted record hides them.
- **Workflow actions are POST-only and gated.** Submit, decide (approve/reject), cancel, amend, convert each live at their own URL ([apps/requisitions/urls.py](apps/requisitions/urls.py)) and call into [apps/requisitions/services.py](apps/requisitions/services.py). Submit also requires at least one line item. Test the happy path AND the out-of-order rejection (e.g. POST convert on a draft → error toast).
- **Inline line items.** Requisition and template line items are added/removed via inline forms on the *detail* page, not separate list pages. Cover line add/delete as part of the detail-page test cases.
- **Auto-generated numbers.** `Requisition.number` is generated as `REQ-<SLUG>-NNNNN` by [apps/requisitions/services.py](apps/requisitions/services.py) `next_requisition_number()` and is globally `unique=True`. The tester never types it — verify it appears, is unique, and increments.
- **Unique-together + tenant trap.** `AccountCode` has `unique_together = ('tenant', 'code')` but `tenant` is excluded from `AccountCodeForm` (it is set in the view). Django's `validate_unique()` may skip the cross-tenant-scoped check, so a duplicate `code` within the same tenant can surface as a 500 instead of a clean form error. Test creating a duplicate account-code `code` within one tenant and expect a clean form-level error, NOT a 500. Log it as a bug if it 500s.
- **Seed assumptions.** The orchestrator `python manage.py seed_data` runs `seed_plans → seed_tenants → seed_users → seed_portal → seed_requisitions`. The requisitions slice alone is `python manage.py seed_requisitions`. Mention the relevant command in §2 and warn that re-seeding may need `--flush` per CLAUDE.md "Seed Command Rules".

---

## Verification protocol (before publishing the report)

Do not invent fields, URLs, or buttons that don't exist. Before listing a test case:

1. **Verify the URL exists** in `urls.py` — link to it in the report.
2. **Verify the field exists** on the model — link to the model line.
3. **Verify the button exists** in the template — link to the template line.
4. **Verify the filter param name** matches what the view reads from `request.GET` — link both.

If you cannot verify a step against the codebase, omit the test case (or mark it `CANDIDATE — verify before testing`). Do not pad the report with hypothetical UI that doesn't ship.

---

## Shell compatibility

The user runs **Windows PowerShell 5.x**. Every shell command in §2 Pre-Test Setup MUST be PowerShell-safe:

- Use `;` as separator — NEVER `&&`
- Quote paths with spaces using `'single'` or `"double"` quotes
- For multi-step setup that should stop on failure, put commands on separate lines, not chained

When emitting the per-file commit snippets at the end (per CLAUDE.md GIT Commit Rule):

```
git add '.claude/manual-tests/<module>-manual-test.md'; git commit -m 'qa(<module>): add manual test plan'
```

One line per file. Always.

---

## Follow-up modes (only if user asks)

After the report is delivered:

- **"Walk me through it"** → execute the test cases yourself against `runserver`, fill in Pass/Fail + Notes, log any bugs found in §5. Use `WebFetch` or browser automation tools where available; otherwise narrate what would happen and ask the user to confirm.
- **"Fix the bugs you found"** → triage by severity, plan in `.claude/tasks/<module>_manual_fixes_todo.md`, implement, re-run the relevant test cases, emit per-file commits.
- **"Convert to automated tests"** → invoke the `/sqa-review` skill in automation-only mode, using this manual plan as the scenario source.

---

## Quality bar

The delivered manual test plan should be:

- **Executable by a non-developer.** A junior tester (or the user) can follow every step without asking questions.
- **Concrete.** Every step names a specific button, field, URL, or expected text — no hand-waving.
- **Project-aware.** Uses real NavPMS URLs (`/requisitions/...`, `/accounts/login/`), real seeded usernames (`admin_acme`), real model field names, real status values (`draft`, `submitted`, `approved`, `rejected`, `cancelled`, `converted`) — not generic placeholders.
- **Comprehensive within scope.** Covers every mandatory checklist from §Phase 5; explicitly marks any category as N/A with a reason rather than silently omitting.
- **Verifiable.** Every claim about a UI element points at the template/model/view file:line where it lives.
- **Tester-friendly.** Pass/Fail/Notes columns are empty for the tester to fill. Bug log template ready to use.

If the user's previous turn produced a manual test plan and they now ask to "execute it" / "walk me through it" / "fix the bugs" — continue from that report, don't regenerate.

---

## Reference

The companion automation-focused skill is [.claude/skills/sqa-review/SKILL.md](.claude/skills/sqa-review/SKILL.md). When the user wants both manual + automated coverage, run this skill first (so they can start clicking immediately) then `/sqa-review` for the automation suite.
