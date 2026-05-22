# Module 3 — Requisition Management

**Created:** 2026-05-22
**Scope:** New Django app `apps/requisitions/` implementing the 5 PMS sub-modules of Module 3.

| Sub-module | Implementation |
|-----------|----------------|
| Requisition Creation | `Requisition` + `RequisitionLine` — item descriptions, quantities, required dates, account codes |
| Requisition Tracking | `status` field + `RequisitionStatusEvent` timeline + dedicated `/requisitions/tracking/` board grouped by status |
| Duplicate Requisition Check | `find_potential_duplicates()` service — flags `possible_duplicate` + `duplicate_of` on create/submit within a 30-day window |
| Requisition Templates | `RequisitionTemplate` + `RequisitionTemplateLine` — pre-defined recurring forms + "create requisition from template" |
| Cancellation/Amendment | Cancel action + Amend action (revert approved/submitted to draft, bump `revision`, log status event) |

## Architecture decisions
- Dedicated `AccountCode` master model (tenant-scoped, full CRUD, FK from requisition lines).
- Amendment = revert-to-draft + `revision` counter (single record, full timeline history).
- Fully separate from `apps/portal/` QuickRequisition — no Module 2 changes.
- Reuse `TenantAwareModel`/`TimeStampedModel`; views use `TenantRequiredMixin`, scope by tenant.
- Reuse `apps.tenants.services.record_audit` so portal Activity Feed shows requisition actions.
- Mounted at `/requisitions/`.

## Models (`apps/requisitions/models.py`)
1. **AccountCode** — code, name, description, is_active.
2. **RequisitionTemplate** — owner (user), name, description, category, default_account_code FK, is_shared.
3. **RequisitionTemplateLine** — template FK, description, quantity, unit, estimated_unit_price, account_code FK.
4. **Requisition** — requested_by (user), number (REQ-SLUG-00001), title, department, priority, required_date, justification, notes, status (draft/submitted/approved/rejected/cancelled/converted), revision, estimated_total, currency, submitted_at, approved_by/approved_at/decision_note, cancelled_at, converted_at, po_reference, created_from_template FK, possible_duplicate, duplicate_of FK.
5. **RequisitionLine** — requisition FK, description, quantity, unit, unit_price, line_total, account_code FK, required_date.
6. **RequisitionStatusEvent** — requisition FK, from_status, to_status, changed_by, note (tracking timeline).

## Tasks

### Backend — `apps/requisitions/`
- [ ] `__init__.py`, `apps.py`
- [ ] `models.py` — 6 models above
- [ ] `admin.py` — register all models (template + requisition with line inlines)
- [ ] `forms.py` — AccountCode, RequisitionTemplate, RequisitionTemplateLine, Requisition, RequisitionLine forms
- [ ] `services.py` — `next_requisition_number`, `recalc_total`, `record_status_event`, `find_potential_duplicates`, `create_requisition_from_template`, transition helpers (submit/approve/reject/cancel/amend/convert)
- [ ] `views.py` — full CRUD per model + workflow actions + tracking board
- [ ] `urls.py` — `app_name = 'requisitions'`
- [ ] `migrations/__init__.py`
- [ ] `management/__init__.py`, `management/commands/__init__.py`
- [ ] `management/commands/seed_requisitions.py` — idempotent: account codes, templates, requisitions across all statuses

### Views (full CRUD + workflow)
- Account codes: list / create / edit / delete
- Templates: list / create / detail / edit / delete + line add/delete + create-requisition-from-template
- Requisitions: list / create / detail / edit (draft) / delete (draft) + line add/delete
- Workflow: submit, approve, reject, cancel, amend, convert-to-PO
- Tracking: `RequisitionTrackingView` — status board with counts

### Templates — `templates/requisitions/`
- [ ] `account_codes/list.html`, `account_codes/form.html`
- [ ] `req_templates/list.html`, `req_templates/form.html`, `req_templates/detail.html`
- [ ] `requisitions/list.html`, `requisitions/form.html`, `requisitions/detail.html`
- [ ] `tracking.html`

### Wiring (modified files)
- [ ] `config/settings.py` — add `'apps.requisitions'`
- [ ] `config/urls.py` — `path('requisitions/', include('apps.requisitions.urls'))`
- [ ] `templates/partials/sidebar.html` — new "Procurement" nav section
- [ ] `apps/core/management/commands/seed_data.py` — add `seed_requisitions` step
- [ ] `README.md` — structure, ToC, commands, seeded data, Module 3 section, routes, roadmap

### Verification
- [ ] `makemigrations requisitions` + `migrate` + `seed_requisitions` + `check`
- [ ] Smoke test: all GET routes 200; create → add line → submit → approve → convert; amend; cancel; duplicate flag; create-from-template

## Review

**Status: complete & verified (2026-05-22).**

- New app `apps/requisitions/` — 6 models, services (numbering, status workflow,
  duplicate detection, template instantiation), full-CRUD views + workflow actions,
  urls, admin, idempotent `seed_requisitions` command (wired into `seed_data`).
- 9 templates under `templates/requisitions/` (account_codes, req_templates,
  requisitions, tracking board).
- Wiring: `INSTALLED_APPS`, `config/urls.py` (`/requisitions/`), sidebar "Procurement"
  section, `seed_data` orchestrator.
- `README.md` updated: intro, ToC, structure, commands, seeded data, Module 3 section,
  routes table, roadmap (Module 3 → Shipped).

**Verification performed:**
- `manage.py check` — 0 issues (fixed an early `related_name` clash: portal and
  requisitions both used `decided_requisitions` → renamed Module 3's to
  `requisitions_decided`).
- `makemigrations requisitions` → `0001_initial` (6 models + 2 indexes + unique_together);
  `migrate` OK.
- `seed_requisitions` — account codes, templates, requisitions across all 6 statuses
  for all 3 tenants.
- Smoke test 1: all 13 GET routes returned HTTP 200.
- Smoke test 2 (workflow): create → add line (total 100) → submit → approve →
  amend (revision 2) → re-submit → convert; duplicate auto-flagged; cancel;
  create-from-template copied 3 lines; account-code create — all passed.

**Design notes:**
- Dedicated `AccountCode` master (unique code per tenant), FK'd from requisition + template lines.
- Amendment = revert-to-draft + `revision` counter; every transition logs a
  `RequisitionStatusEvent` and an `AuditLog` entry (feeds Module 2 Activity Feed).
- Duplicate check: same requester, 30-day window, equal title or shared line description.
- Kept fully separate from Module 2's portal QuickRequisition — no Module 2 changes.
