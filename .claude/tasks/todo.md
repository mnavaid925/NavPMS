# Module 5 — Vendor Management

**Created:** 2026-05-24
**Scope:** New Django app `apps/vendors/` implementing the 5 PMS sub-modules of Module 5, plus
a separate Vendor Portal shell at `/vendor-portal/` for suppliers.

| Sub-module | Implementation |
|-----------|----------------|
| **Vendor Onboarding** | Public per-tenant slug application form (`/vendors/onboarding/apply/<tenant-slug>/`), tenant-admin review queue, "Approve → convert to Vendor" workflow, document verification. |
| **Vendor Portal** | Separate shell at `/vendor-portal/`. Supplier auth via `User.vendor` OneToOne FK + invite link. Login redirects vendor users to portal; portal users sandboxed. Self-service: profile, contacts, documents. PO/invoice placeholders for Module 11/14. |
| **Vendor Classification & Segmentation** | `VendorCategory` (tree-capable, parent self-FK) + `VendorSegment` (Strategic/Tactical/Preferred/Approved with badge colors). Full CRUD. Assigned on vendor form + filterable on list. |
| **Vendor Risk Profiling** | `VendorRiskAssessment` with four-pillar 0–100 sliders (financial/operational/compliance/quality). Overall = average; level auto-derived (low/medium/high/critical). One `is_current` per vendor; denormalised onto `Vendor.risk_level` for fast filtering. |
| **Vendor Blacklisting/Suspension** | `VendorBlacklistEvent` append-only timeline (suspend/blacklist/reinstate) with effective + end dates and reason. `Vendor.status` flips accordingly. Blacklisted/suspended vendors are flagged in the queryset for future PO selection (Module 11). |

## Architecture decisions
- New app `apps/vendors/` mounted at `/vendors/`. Vendor portal mounted at `/vendor-portal/`.
- `User.vendor` (OneToOne, nullable) added to `apps.accounts.models.User`. A user with this set
  is a supplier portal user.
- `vendor_required` decorator: only users with `user.vendor` set may hit portal routes.
- `vendor_blocked` decorator: portal users are kicked out of internal `/vendors/`,
  `/requisitions/`, etc. routes.
- Login flow patched: after login, if `user.vendor` set → redirect to `/vendor-portal/`.
- Onboarding form is **public** (no `@login_required`) at `/vendors/onboarding/apply/<tenant-slug>/`.
  Submission creates a `VendorOnboardingApplication` for that tenant. CSRF protected; rate
  not enforced (deferred to Module 21).
- `Vendor.risk_level` + `Vendor.risk_score` are denormalised from the latest
  `is_current=True` `VendorRiskAssessment` for filter performance.
- `VendorBlacklistEvent` is append-only (admin add/delete disabled, mirroring `AuditLog`).
- Reuse `TenantAwareModel` / `TimeStampedModel` and `record_audit` for the audit trail.

## Models (`apps/vendors/models.py`)
1. **VendorCategory** — tenant, name, code, description, parent (self FK, nullable), is_active.
   `unique_together(tenant, code)`. Ordering: `name`.
2. **VendorSegment** — tenant, name, code, color (hex for badge), description, is_active.
   `unique_together(tenant, code)`. Ordering: `name`.
3. **Vendor** — tenant, vendor_number (auto `VND-<SLUG>-NNNNN`), legal_name, trade_name,
   vendor_type (manufacturer/distributor/service_provider/contractor/other), tax_id,
   registration_number, email, phone, website, country, address_line1, address_line2,
   city, state, postal_code, primary_contact_name, primary_contact_email,
   primary_contact_phone, category FK, segment FK, status (draft/pending_verification/
   active/suspended/blacklisted/inactive), is_verified, verified_at, verified_by,
   risk_level (low/medium/high/critical, default low), risk_score (decimal, default 0),
   portal_user OneToOne to User (nullable), notes.
   `unique_together(tenant, vendor_number)`.
4. **VendorContact** — vendor FK, name, email, phone, role, is_primary, notes.
5. **VendorDocument** — vendor FK, doc_type (registration/tax/nda/insurance/bank/
   quality_cert/other), title, file (`upload_to='vendor_docs/'`), description,
   expires_at, is_verified, verified_at, verified_by, uploaded_at.
6. **VendorBankAccount** — vendor FK, bank_name, account_holder, account_number, branch,
   iban, swift_code, currency, country, is_primary, notes.
7. **VendorOnboardingApplication** — tenant, token (uuid, unique, public), company_name,
   contact_name, contact_email, contact_phone, country, vendor_type, tax_id,
   registration_number, website, service_description, status (submitted/under_review/
   approved/rejected), submitted_at, reviewed_by FK, reviewed_at, rejection_reason,
   converted_to_vendor FK (nullable, set on approval).
8. **VendorRiskAssessment** — vendor FK, assessment_date, valid_until, financial_score
   (0–100), operational_score (0–100), compliance_score (0–100), quality_score (0–100),
   overall_score (computed in `save()`), level (computed), notes, assessed_by FK,
   is_current (boolean — only one current per vendor enforced in `save()`).
9. **VendorBlacklistEvent** — vendor FK, action (suspend/blacklist/reinstate),
   effective_date, end_date (suspension only), reason, notes, actioned_by FK,
   created_at. Append-only.

## Tasks

### Backend — `apps/vendors/`
- [ ] `__init__.py`, `apps.py`
- [ ] `models.py` — 9 models above
- [ ] `admin.py` — register all (vendor with contact/doc/bank inlines; application + risk + blacklist read-mostly)
- [ ] `forms.py` — VendorForm, ContactForm, DocumentForm, BankAccountForm, CategoryForm, SegmentForm, RiskAssessmentForm, OnboardingApplicationForm (public), BlacklistEventForm, VendorPortalInviteForm
- [ ] `services.py` — `generate_vendor_number`, `compute_risk_level`, `apply_risk_assessment`, `convert_application_to_vendor`, `suspend_vendor`, `blacklist_vendor`, `reinstate_vendor`, `invite_to_portal` (creates User + token), `accept_portal_invite`
- [ ] `decorators.py` — `vendor_required`, `vendor_blocked`
- [ ] `views.py` — vendor CRUD, contact/doc/bank inline CRUD, category CRUD, segment CRUD, risk CRUD (per-vendor list/create/detail), onboarding apply (public), onboarding review (admin), blacklist actions, portal invite send/accept, portal: dashboard/profile/profile_edit/documents/contacts/PO+invoice placeholders
- [ ] `urls.py` — `app_name = 'vendors'` with all internal routes
- [ ] `portal_urls.py` (or share `urls.py` with a separate namespace) — `app_name = 'vendor_portal'` for `/vendor-portal/`
- [ ] `migrations/__init__.py`
- [ ] `management/__init__.py`, `management/commands/__init__.py`
- [ ] `management/commands/seed_vendors.py` — idempotent

### Templates — `templates/vendors/`
- [ ] `vendors/list.html` — search + status/category/segment/risk filters + actions
- [ ] `vendors/form.html` — create/edit (also reused for verify)
- [ ] `vendors/detail.html` — tabs: Overview / Contacts / Documents / Bank Accounts / Risk / Blacklist History; Action sidebar (edit/suspend/blacklist/reinstate/invite-to-portal)
- [ ] `categories/list.html`, `categories/form.html`
- [ ] `segments/list.html`, `segments/form.html`
- [ ] `contacts/form.html`
- [ ] `documents/form.html`
- [ ] `bank_accounts/form.html`
- [ ] `risk/form.html`, `risk/detail.html`
- [ ] `onboarding/apply.html` (PUBLIC, anon-friendly card layout)
- [ ] `onboarding/applied.html` (PUBLIC thank-you)
- [ ] `onboarding/list.html` (admin review queue)
- [ ] `onboarding/detail.html` (admin review + approve/reject)
- [ ] `blacklist/form.html` (action dialog: suspend/blacklist/reinstate)

### Templates — `templates/vendor_portal/`
- [ ] `base.html` — separate shell (minimal sidebar: Dashboard / My Profile / Documents / Contacts / Purchase Orders / Invoices), logo+vendor name in topbar
- [ ] `dashboard.html` — welcome card, profile completeness, document expiry alerts, recent activity
- [ ] `profile.html`, `profile_edit.html`
- [ ] `documents.html` (list + upload)
- [ ] `contacts.html` (list + add)
- [ ] `purchase_orders.html` (placeholder — "Available in Module 11")
- [ ] `invoices.html` (placeholder — "Available in Module 14")
- [ ] `invite_accept.html` — token URL → set-password form

### Auth integration (modified files)
- [ ] `apps/accounts/models.py` — add `User.vendor` OneToOne FK + `is_vendor_user` property
- [ ] `apps/accounts/views.py` — login redirect: if `user.vendor`, go to `/vendor-portal/`
- [ ] `apps/accounts/middleware.py` (or new vendor middleware) — sandbox vendor users
      OR per-view `vendor_blocked` on every internal namespace's URLConf (simpler, do this)

### Wiring (modified files)
- [ ] `config/settings.py` — add `'apps.vendors'`
- [ ] `config/urls.py` — `path('vendors/', include('apps.vendors.urls'))` and
      `path('vendor-portal/', include(('apps.vendors.portal_urls', 'vendor_portal'), namespace='vendor_portal'))`
- [ ] `templates/partials/sidebar.html` — new "Vendors" group in the Procurement section
      (Vendors list, Categories, Segments, Onboarding Applications, Blacklist History)
- [ ] `apps/core/management/commands/seed_data.py` — add `seed_vendors` after `seed_approvals`
- [ ] `README.md` — Project Structure, ToC, Management Commands, Seeded Demo Data,
      **new Module 5 section**, Routes table, Roadmap (Module 5 → Shipped)

### Seed data per tenant
- 5 categories: Raw Materials, IT Services, Maintenance, Office Supplies, Logistics
- 4 segments: Strategic (red), Tactical (orange), Preferred (green), Approved (blue)
- 8 vendors: 3 active, 1 pending_verification, 1 suspended, 1 blacklisted, 2 draft
- 1–2 contacts, 1 document, 1 bank account per vendor (file stays None on doc rows — path-only or skipped)
- Risk assessment on each active vendor (varied scores → varied levels)
- 3 onboarding applications: 1 submitted, 1 under_review, 1 approved-and-converted
- 2–3 blacklist events on the suspended + blacklisted vendors

### Verification
- [ ] `python manage.py check` — 0 issues
- [ ] `makemigrations vendors` → `0001_initial`; `makemigrations accounts` → adds `vendor` FK
- [ ] `migrate` — both clean
- [ ] `seed_vendors` (and via `seed_data --flush`) — populated for each tenant
- [ ] Smoke test: every GET route returns 200 with `admin_acme`
- [ ] Multi-tenancy: admin_acme cannot see admin_globex vendor rows
- [ ] CRUD: create/edit/delete on vendor, category, segment, risk assessment
- [ ] Status workflow: draft → pending → verify → active; active → suspend → reinstate; active → blacklist
- [ ] Public onboarding application: submit anon → tenant admin sees in queue → approve → vendor created
- [ ] Portal: invite vendor → accept link → log in → land on `/vendor-portal/`; cannot reach `/vendors/`

## Review

**Status: complete & verified (2026-05-24).**

- New app `apps/vendors/` — 9 models (`VendorCategory`, `VendorSegment`, `Vendor`,
  `VendorContact`, `VendorDocument`, `VendorBankAccount`, `VendorOnboardingApplication`,
  `VendorRiskAssessment`, `VendorBlacklistEvent`), service layer
  (`next_vendor_number`, `apply_risk_assessment` with denorm onto Vendor,
  `convert_application_to_vendor`, `suspend/blacklist/reinstate_vendor`,
  `verify_vendor`, `invite_to_portal`, `revoke_portal_access`), full views,
  forms, admin, urls (`vendors:` and `vendor_portal:` namespaces), seed command.
- 15 internal templates (`templates/vendors/`) + 8 vendor portal templates
  (`templates/vendor_portal/`) with a separate shell.
- `User.vendor` OneToOne FK added (`apps/accounts/migrations/0002_user_vendor.py`),
  `User.is_vendor_user` helper, login flow auto-redirects vendor users to the portal.
- **`VendorPortalSandboxMiddleware`** — kicks vendor users back to `/vendor-portal/`
  when they attempt to access internal namespaces (`/vendors/`, `/requisitions/`,
  `/approvals/`, `/portal/`, `/`). Allowed prefixes: `/vendor-portal/`,
  `/accounts/`, `/admin/`, `/static/`, `/media/`. Chosen over per-app decorators
  because it provides blanket coverage that future modules inherit automatically.
- Wiring: `INSTALLED_APPS`, `/vendors/` + `/vendor-portal/` URL mounts, sidebar
  "Vendors" group with role-gated entries, `seed_data` orchestrator extended with
  `seed_vendors`, README updated end to end (Module 5 → Shipped).

**Verification performed:**
- `manage.py check` — 0 issues.
- `makemigrations vendors accounts` → `vendors.0001_initial` (9 models, 3 indexes,
  unique_together) + `accounts.0002_user_vendor`; `migrate` OK.
- `seed_vendors` — populated categories, segments, 9 vendors, contacts/docs/banks,
  risk assessments, 3 onboarding apps, blacklist events. Idempotent (skips with
  warning on second run, supports `--flush`).
- Smoke test 1: 13 GET routes returned HTTP 200 as `admin_acme` (list, create,
  detail, edit, categories, segments, risk, onboarding queue, public apply form
  anonymous, blacklist history).
- Smoke test 2 (vendor portal): 7 routes returned 200 as a portal user
  (dashboard, profile, profile_edit, documents, contacts, PO+invoice placeholders).
- Smoke test 3 (sandbox middleware): vendor user → 5 internal namespaces all
  returned 302 → `/vendor-portal/`. Tenant admin unaffected.
- Smoke test 4 (workflows): multi-tenancy (Globex admin gets 404 on Acme vendor);
  status transitions draft → verify → active → suspend → reinstate → blacklist;
  risk recompute (new critical assessment denormalises to Vendor.risk_level);
  onboarding approve creates a vendor via `convert_application_to_vendor`; public
  anonymous application submission creates an application for the right tenant.
- Login flow: POST `/accounts/login/` with vendor user credentials returns 302 →
  `/vendor-portal/`.

**Design notes:**
- `Vendor.risk_level` + `Vendor.risk_score` are denormalised from the current
  `VendorRiskAssessment` to keep list filters fast. `apply_risk_assessment`
  marks older assessments stale in the same transaction.
- Onboarding `convert_application_to_vendor` creates the vendor as
  `pending_verification`, not active — the verify step is a deliberate gate.
- Onboarding apply form is *fully public*: no `@login_required`; tenant resolved
  from URL slug; `set_current_tenant` is invoked manually because the auth
  middleware leaves `request.tenant` None for anonymous requests.
- Portal invite returns a one-time password back to the caller (no email
  backend yet). Production must wire SMTP and stop displaying the raw secret.
- Vendor portal uses its own base template (`vendor_portal/base.html`), not the
  internal `base.html`, so changes to the buyer sidebar/topbar don't leak into
  the supplier experience.

**Files changed:** 32 new + 8 modified = 40 files.

---

# Previous Modules

## Module 4 — Approval Workflow Engine — 2026-05-22 / 2026-05-23

**Status: complete & verified (2026-05-23).**

- New app `apps/approvals/` — 6 models, workflow engine (`services.py`: routing,
  delegation resolution, task progression, completion, escalation), full-CRUD views +
  inbox/task/history, urls, admin, `seed_approvals` + `run_escalations` commands.
- 10 templates under `templates/approvals/`.
- Module 3 integration: `submit_requisition` routes through the engine;
  `cancel_requisition`/`amend_requisition` withdraw in-flight approvals;
  `RequisitionDetailView` + requisition `detail.html` show approval progress and gate
  the admin approve/reject fallback to "no engine request".
- Wiring: `INSTALLED_APPS`, `/approvals/`, sidebar "Approvals" group, `seed_data`.
- `README.md` updated end to end (Module 4 → Shipped).
- Verified: `manage.py check` clean; migrations + seed + 12 routes 200 + engine smoke
  test (2-step approve, reject, delegate, escalate, no-rule fallback) all passed.

## Manual Test — Requisition Management (Module 3) — 2026-05-23

**Scope:** `/manual-test "Requisition Management"` → produced
`.claude/manual-tests/requisitions-manual-test.md` (145 test cases), executed the
back-end-verifiable subset, then a 43-case browser pass; fixed two bugs.

- **BUG-01:** `AccountCode` duplicate-code 500 (unique_together + excluded field).
  Fixed in `apps/requisitions/forms.py` (tenant kwarg + `clean_code`).
- **BUG-02:** mobile horizontal overflow. Fixed in `static/css/style.css`
  (`.app-main { min-width: 0 }` + sidebar selector re-scoped) and five
  requisition tables wrapped in `.table-responsive`.

**Totals:** 103 / 145 cases executed, 0 fail, 2 bugs fixed. 42 cases still need a
human (visual judgement, double-submit timing, browser back/forward). GO-with-fixes.
