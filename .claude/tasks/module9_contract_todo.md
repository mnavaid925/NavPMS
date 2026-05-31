# Module 9 — Contract Management

## Plan (approved)
Add a full multi-tenant `apps/contracts/` app mirroring `apps/auctions/` (Module 8) + the RFx
template-library pattern, delivering all five sub-modules: Contract Authoring & Templating,
E-Signature Integration (mock/tokenized), Renewal & Expiration Alerts, Amendment Tracking,
Obligation & Milestone Management.

- [x] App skeleton (`__init__`, `apps.py`) + register in `config/settings.py`
- [x] `models.py` — ContractClause, ContractTemplate(+Clause), Contract, ContractClauseLine,
      ContractSignatory, ContractAmendment, ContractObligation, ContractDocument, ContractStatusEvent
- [x] `services.py` — perms, numbering, authoring/templating, e-signature lifecycle, terminate/cancel/
      renew/expire, amendments, obligations, `scan_contract_alerts`, analytics
- [x] `forms.py`, `admin.py` (append-only status-event + post-apply amendment lockdown)
- [x] `views.py` + `urls.py` (FBV CRUD + lifecycle + authoring + boards + libraries + analytics); mounted in `config/urls.py`
- [x] `portal_views.py` (vendor inbox + tokenized signing); wired into `apps/vendors/portal_urls.py`
- [x] Templates (21 buyer + 3 vendor) + `_status_badge.html`; sidebar `#sbContracts`; vendor-portal nav link
- [x] Management commands: `seed_contracts`, `run_contract_alerts` (+ chained `seed_contracts` into `seed_data`)
- [x] Migration `0001_initial` (removed Django's spurious self-FK `__first__` deps); migrated — 10 tables
- [x] `tests/` package (conftest + models/services/views/security) — 76 tests
- [x] README updated (intro, TOC, structure, commands, testing count, seed data, Module 9 section, routes, roadmap)

## Verification
- `manage.py check` — 0 issues.
- `seed_contracts` (+ `--flush`) idempotent across all tenants: clause library, 2 templates, 7 contracts
  (draft-from-template / pending-signature / active+obligations / expiring-soon / auto-renew / amended / terminated).
- `run_contract_alerts` raises one-time deadline alerts (idempotent on re-run).
- `pytest apps/contracts` → 76 passed; full suite → **629 passed** (was 553 + 76).
- All 24 contract templates compile cleanly.

## Review / lessons
- **Bug found & fixed (seed):** activate-then-terminate failed because `sign_contract` activates a
  freshly-fetched row, leaving the caller's object stale → added `refresh_from_db()` in `_sign_and_activate`.
- **Bug found & fixed (templates):** vendor-portal templates must use `{% block title %}`/`{% block content %}`
  (the `vendor_portal/base.html` block names), not `vp_*` — wrong names render an empty shell silently.
- **Migration quirk:** the self-referential `parent_contract` FK made Django emit bogus `('contracts','__first__')`
  self-dependencies in the initial migration; removed them.
- `Contract.vendor` uses CASCADE (not PROTECT) to stay consistent with the auctions vendor FK and keep
  `seed_vendors --flush` working (vendors are flushed before contracts in the orchestrator).
