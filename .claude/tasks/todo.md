# Module 16 — Budget & Cost Management (`apps/budget/`)

**Created:** 2026-06-06
**Plan:** `C:\Users\user\.claude\plans\partitioned-finding-sifakis.md`

New app `apps/budget/` at `/budget/` — the financial-control layer across the P2P loop. Five
sub-modules: Budget Allocation & Mapping, Budget Availability Check, Commitment Accounting,
Variance Analysis, Forecasting & Projection.

**Locked decisions (user-confirmed, all recommended):** dimension = reuse `requisitions.AccountCode`;
consumption = compute-on-read (no ledger, no reversal hooks); availability check = soft-warn by
default with `BUDGET_ENFORCEMENT='block'` toggle; full module in one session.

## Review

**Status: complete & verified (2026-06-06).**

- New app `apps/budget/` — 5 models (`BudgetPeriod`, `Budget` (+`BudgetAllocation`),
  `BudgetStatusEvent` append-only, `BudgetCheck` append-only availability-check log), full service
  layer (`next_budget_number`, `can_manage_budget`/`can_view_budget`, lifecycle
  `activate_budget`/`close_budget`/`set_period_status`, **compute-on-read** consumption
  (`allocation_consumption`/`budget_consumption` deriving actual/committed/reserved from invoice/PO/
  requisition lines), `tenant_budget_metrics`, `variance_report`, `forecast`,
  `check_requisition_budget` + `latest_check_status`, `scan_budget_alerts`, export-row builders),
  views + forms + admin + urls, `seed_budget` + `run_budget_alerts` commands.
- 12 templates under `templates/budget/` (dashboard, period + budget list/form/detail, allocation
  form, variance, forecast, check log, `_status_badge`, `_requisition_budget_banner`).
- **Integration:** `requisitions.submit_requisition` calls the availability check FIRST (before any
  status mutation, so a `block` leaves the requisition untouched while the `BudgetCheck` evidence
  persists); the submit view catches the block `ValidationError`; the requisition detail view +
  template surface a live over-budget banner. CSV/XLSX helpers reused from `spend_analytics.exports`.
- **Wiring:** `INSTALLED_APPS`, `/budget/` mount, sidebar "Budget & Costs" group (after Spend
  Analytics), `seed_data` orchestrator extended, 3 new env vars (`BUDGET_ENFORCEMENT`,
  `BUDGET_VARIANCE_TOLERANCE_PCT`, `BUDGET_WARN_UTILIZATION_PCT`). README updated end to end
  (Module 16 → Shipped, intro, TOC, structure, env, commands, seeded data, routes, roadmap, test count).

**Design call (consumption is data-honest):** committed/actual read the authoritative PO/invoice
line `account_code`. In the existing demo data those lines carry no cost centre, so seeded
committed/actual show low — this matches `spend_analytics` and is NOT faked; the deterministic
commitment / over-budget / block paths are proven by the test suite instead. No cross-module changes
were made to backfill account codes (Minimal Impact).

**Verification performed:**
- `manage.py check` — 0 issues; `makemigrations --check` — no missing migrations; `migrate` clean on MySQL.
- `seed_budget --flush` — period + active budget + allocations + a real availability check per
  tenant; idempotent re-run skips; degrades gracefully for tenants without account codes.
- **pytest: 38 budget tests pass; full project suite 1165 pass (0 failures)** — the requisitions
  submit hook broke nothing. Tests cover consumption math (incl. committed dropping when a PO closes
  — no double count), warn vs block enforcement, own-reservation exclusion, forecast, variance flags,
  alert idempotency, full CRUD + lifecycle, export content-types, role gates, cross-tenant IDOR 404s.

**Files:** ~30 new app/template/test files + 8 modified.

---

# Module 15 — Spend Analytics & Reporting (`apps/spend_analytics/`)

**Created:** 2026-06-06
**Scope:** New app `apps/spend_analytics/` at `/spend-analytics/` — the first read-mostly analytics
module. Aggregates spend from Invoicing (M14) + Purchase Orders (M11) + Vendors (M5) + Contracts
(M9) into a denormalized `SpendRecord` fact table. Full design spec:
`C:\Users\user\.claude\plans\snoopy-wishing-lightning.md`.

> **Decisions locked:** spend basis = actual invoiced (primary) + committed PO (toggle), never
> summed; "department" dimension = existing `requisitions.AccountCode` (cost center), no new model;
> architecture = `SpendRecord` fact table synced by service + cron + lazy sweep; `SpendReport` has
> no human number (matches `portal.SavedReport`).

| Sub-module (spec) | Implementation |
|---|---|
| **Spend Dashboards** | KPI cards + category/vendor/cost-center/month charts (`json_script`), actual↔committed toggle. |
| **Custom Report Builder** | `SpendReport` (dimension+measure+chart+filters), full CRUD + run. Form-driven (NOT drag-drop on this stack). |
| **Category Spend Analysis** | category table (total/%/count/avg) → drill to vendors + records (uses `VendorCategory`). |
| **Maverick Spend Tracking** | persisted proxies at sync: off-preferred-supplier / off-contract / non-PO; reason/vendor/category breakdown + KPIs. |
| **Data Export & Visualization** | CSV + XLSX of dashboard / a saved report / raw filtered records (net-new `exports.py`; the BI feed). |

## Tasks
- [ ] Scaffold `apps/spend_analytics/` (`__init__`, `apps.py`, migrations pkg, management pkgs)
- [ ] `models.py` — SpendRecord (fact) + SpendReport + module constants
- [ ] INSTALLED_APPS + `makemigrations spend_analytics` + `migrate`
- [ ] `services.py` — perms, maverick helpers, `sync_spend_facts` (upsert+prune), `sync_all_tenants`, lazy-sync watermark, metrics (`tenant_spend_metrics`/`category_spend`/`category_detail`/`maverick_metrics`), `run_spend_report`, `spend_rows_for_export`
- [ ] `exports.py` — `csv_response` / `xlsx_response`
- [ ] `forms.py` — `SpendReportForm`
- [ ] `views.py` + `urls.py` (every read + export view gated on `can_view_*` — D-01 lesson) + mount in `config/urls.py`
- [ ] `templates/spend_analytics/*` — dashboard, category_analysis, category_detail, maverick_tracking, report_list, report_form, report_detail
- [ ] `admin.py` (SpendRecord read-only; SpendReport CRUD) + `apps.py`
- [ ] `seed_spend_analytics` (sync + 2–3 demo reports) + `run_spend_sync` (cron) + seed_data step + sidebar group
- [ ] Tests (`conftest`, `test_models`, `test_services`, `test_views`, `test_security`)
- [ ] `manage.py check` + `seed_data --flush` + `pytest apps/spend_analytics` + smoke routes incl. export content-types
- [x] README (module section, routes, commands, seeded data, roadmap → Shipped, TOC, test count)
- [ ] Per-file PowerShell commit snippets

## Review

**Status: complete & verified (2026-06-06).**

- New app `apps/spend_analytics/` — 2 models (`SpendRecord` synced fact table + `SpendReport`
  saved report builder), full service layer (`sync_spend_facts` upsert+prune, `sync_all_tenants`,
  `lazy_sync` watermark, `tenant_spend_metrics`/`category_spend`/`category_detail`/
  `maverick_metrics`, `run_spend_report`, `spend_rows_for_export`, perms + maverick proxies),
  reusable `exports.py` (CSV/XLSX), `forms.py`, gated `views.py` + `urls.py`, `admin.py`,
  `seed_spend_analytics` + `run_spend_sync` commands, 7 templates, tests.
- **Decisions honoured:** actual (invoiced) + committed (PO) bases, never summed; AccountCode =
  cost-center/"department"; SpendRecord fact table synced via service + cron + lazy sweep;
  SpendReport has no human number.
- **Security (D-01/D-02 lesson):** every read view AND all 3 export endpoints gated on
  `can_view_spend_analytics`; mutations on `can_manage`; private-report isolation + cross-tenant 404.
- **Wiring:** INSTALLED_APPS, `/spend-analytics/` mount, sidebar "Spend Analytics" group,
  `seed_data` orchestrator step after `seed_invoicing`. README updated end to end (Module 15 →
  Shipped).

**Verification performed:**
- `manage.py check` — 0 issues; `makemigrations --check` — no missing migrations.
- `migrate` (brought the dev DB current — it was behind on invoicing/PO migrations from a parallel
  Module-14 session); `seed_spend_analytics` — 15 spend records + 3 reports per seeded tenant;
  `run_spend_sync` idempotent (`+0 ~45 -0`).
- **pytest: 50 spend_analytics tests pass; full suite 1127 pass (0 failures)** — shared-file edits
  (settings/urls/sidebar/seed_data) broke nothing.
- Live smoke as `admin_acme`: dashboard (both bases), category + drill, maverick, reports + run,
  and CSV/XLSX exports all 200 with correct content types.

**Note:** a save-hook/formatter twice blanked/deleted `apps/spend_analytics/urls.py` after writing;
restored with the full route list (an empty `urlpatterns` is a broken stub, not an intentional
state). Verify it is present before committing.

---

# Module 14 — Invoice & Voucher Management (`apps/invoicing/`)

**Created:** 2026-06-05
**Scope:** New app `apps/invoicing/` at `/invoicing/` — the accounts-payable layer closing the P2P
loop after Module 13 (Goods Receipt). Mirrors M13 conventions. Full design spec:
`C:\Users\user\.claude\plans\cheerful-rolling-walrus.md`.

> **Naming:** `apps.tenants.Invoice` already exists (SaaS billing). AP model = **`SupplierInvoice`**
> (`SINV-<SLUG>-NNNNN`); payment doc = **`PaymentVoucher`** (`VCH-<SLUG>-NNNNN`). The invoice is
> **read-only** against PO/GRN — never re-posts to the PO (GRN already did).
>
> **Decisions locked:** OCR = mock pluggable connector (`ocr.py`, mirrors `gateways.py`); voucher
> payment = reuse `tenants/gateways.py` mock gateway; scope = full module.

| Sub-module (spec) | Implementation |
|---|---|
| **Invoice Capture (OCR)** | `SupplierInvoice.source_file` + `ocr.py` (OcrEngine Protocol + MockOcrEngine, `OCR_ENGINE` env) → `capture_invoice_from_file()` extracts header+lines to a draft. File whitelist-validated (`upload_error`). |
| **Three-Way Matching** | `run_three_way_match()` — invoice line vs PO line (ordered qty/price) vs GRN accepted qty; tolerances; over-billing guard computed in-app. Sets per-line + header `match_status`. |
| **Dispute Resolution** | `InvoiceDisputeNote` append-only buyer↔supplier thread; `disputed` status; vendor portal reply. |
| **Payment Terms** | `PaymentTerm` master (net days, discount %/days) → due_date / discount_due_date / discount_amount; `PaymentVoucher` schedules + pays via gateway. |
| **Early Payment Discount** | Analytics dashboard: discount-window opportunities + AP aging buckets. |

## Status workflows
- Invoice `status`: `draft → submitted → approved → paid`, plus `disputed` (↔ submitted), `rejected`, `cancelled`.
- Invoice `match_status`: `unmatched / matched / exceptions`.
- Voucher `status`: `draft → approved → scheduled → paid`, plus `cancelled`.

## Tasks
- [ ] Scaffold `apps/invoicing/` (`__init__`, `apps.py`, migrations pkg, management pkgs)
- [ ] `models.py` — PaymentTerm, SupplierInvoice(+Line), SupplierInvoiceStatusEvent, InvoiceDisputeNote, PaymentVoucher(+StatusEvent)
- [ ] `ocr.py` — OcrEngine Protocol + MockOcrEngine + registry + `get_ocr_engine()`
- [ ] `services.py` — numbering, capture, 3-way match, lifecycle, vouchers (gateway), alerts, metrics, perms/visibility
- [ ] `forms.py`, `views.py`, `urls.py`, `admin.py`, `portal_views.py`
- [ ] Migration (`makemigrations invoicing`)
- [ ] `templates/invoicing/*` + `templates/vendor_portal/invoicing/*` (replace `vendor_portal/invoices.html`)
- [ ] Vendor-portal wiring (`vendors/portal_urls.py`, `vendors/views.py`) — replace placeholder
- [ ] Global wiring (settings INSTALLED_APPS + env, `config/urls.py`, `sidebar.html`, `seed_data.py`)
- [ ] `seed_invoicing` + `run_invoice_alerts` commands
- [ ] Tests (`conftest`, `test_models`, `test_services`, `test_views`, `test_security`)
- [ ] `makemigrations` + `migrate` + `pytest apps/invoicing` + `seed_invoicing --flush`
- [ ] README (module section, routes, commands, env, seeded data, roadmap, TOC)
- [x] Per-file PowerShell commit snippets

## Review

**Status: complete & verified (2026-06-06).**

- New app `apps/invoicing/` — 7 models (`PaymentTerm`, `SupplierInvoice` (+`SupplierInvoiceLine`),
  `SupplierInvoiceStatusEvent` append-only, `InvoiceDisputeNote` append-only thread, `PaymentVoucher`
  (+`PaymentVoucherStatusEvent` append-only)), a pluggable OCR connector (`ocr.py`: `OcrEngine`
  Protocol + `MockOcrEngine` + `get_ocr_engine()`), full service layer (`next_invoice_number`/
  `next_voucher_number`, `capture_invoice_from_file`, `run_three_way_match`, `submit`/`approve`/
  `raise_dispute`/`add_dispute_note`/`resolve_dispute`/`reject`/`cancel`, `create_voucher`/`approve`/
  `schedule`/`pay_voucher` via the mock gateway, `scan_invoice_alerts`, `tenant_invoice_metrics`,
  perms + `invoice_visible_to`), views + portal_views, forms, admin, urls, seed + alerts commands.
- 13 internal templates (`templates/invoicing/`) + 3 vendor-portal templates
  (`templates/vendor_portal/invoicing/`); replaced + removed the Module-14 placeholder.
- Wiring: `INSTALLED_APPS`, `/invoicing/` mount, sidebar "Invoices" group (after Goods Receipt),
  `seed_data` orchestrator extended, vendor-portal routes repointed (dead `portal_invoices` view +
  placeholder template removed), three new env vars (`OCR_ENGINE` + two tolerances). README updated
  end to end (Module 14 → Shipped, intro, TOC, structure, routes, commands, env, seeded data).

**Design decisions (locked with the user):** OCR = mock pluggable connector; voucher payment reuses
the existing `tenants/gateways.py` mock gateway; full module in one session.

**Key design call:** the invoice is **read-only** against the PO/GRN — it never re-posts to the PO
(the GRN already did), so the two receiving paths can't double-count. Over-billing is guarded by
summing already-invoiced qty *within the app*. `SupplierInvoice` (not `Invoice`) avoids the
`apps.tenants.Invoice` (SaaS billing) collision.

**Bug found & fixed during verification:** the three-way match originally matched only against
`GoodsReceiptLine.accepted_quantity`, but demo POs received their goods via **Module 12 fulfilment**
(no GRN) — so matched invoices falsely showed `no_receipt`. Fixed by sourcing the "received" leg from
the authoritative `PurchaseOrderLine.received_quantity` (fed by *both* GRN posting and fulfilment
confirmation, each posting only accepted qty); renamed the field `matched_grn_qty → matched_received_qty`.
Also hardened `pay_voucher` to lock-then-check (TOCTOU-safe, per the fulfilment lesson).

**Verification performed:**
- `manage.py check` — 0 issues; `makemigrations --check` — no missing migrations.
- `seed_invoicing --flush` — 3 payment terms + 7 invoices/tenant across every status; idempotent
  re-run skips; the paid invoice charges through the mock gateway (`gateway_ref` set), the discount is
  captured (2/10 Net 30), and the overdue alert fires once (idempotent on re-sweep).
- **pytest: 61 invoicing tests pass; full project suite 1042 pass (0 failures)** — shared-file edits
  broke nothing.

**Files:** 22 new app files + 16 new templates + 8 modified + 1 deleted = 47.

---

# Module 11 — Purchase Order (PO) Management

**Created:** 2026-06-03
**Scope:** New Django app `apps/purchase_orders/` mounted at `/purchase-orders/`, implementing the
5 PMS sub-modules of Module 11. Mirrors the Module 9 (Contracts) conventions. Vendor-facing
dispatch/acknowledgment integrated into the existing `/vendor-portal/` namespace (no second shell).

## Decisions (locked with the user, 2026-06-03)
- Build as **Module 11 now**; the half-built, uncommitted `apps/catalog/` (Module 10) is **left untouched**.
- PO **Generation** sources: **approved requisitions** (`?from_requisition=<pk>` pre-fill) **+ manual entry**.

## Design decisions (my defaults — flag on review if you disagree)
- **Acknowledgment** happens inside the authenticated **vendor portal** (vendor user accepts/declines).
  Buyer can also "record acknowledgment on behalf" for vendors without a portal account. No public
  token page (unlike contract e-sign) since dispatch targets an existing supplier record.
- **Receiving** is a lightweight precursor to Module 13 (Goods Receipt): per-line `received_quantity`
  + `delivery_status` + a `record receipt` action. Full inspection/GRN stays for Module 13.
- **No PO template library** (spec doesn't call for one, unlike Contracts/RFx) — keeps scope to the 5 sub-modules.
- **Change Orders** capture proposed `expected_delivery_date` + per-line `(quantity, unit_price)` changes as a
  `proposed_lines` JSON, snapshotting `prev_*` on apply (mirrors `catalog.CatalogPriceChangeRequest` + `ContractAmendment`).
- Money: line `unit_price`/`line_total` + PO `subtotal/tax/shipping/total` at **2 dp** (match requisitions, the source).

| Sub-module (spec) | Implementation |
|---|---|
| **PO Generation** | `PurchaseOrder` + `PurchaseOrderLine`; `create_po_from_requisition()` + manual form; "Create Purchase Order" button on approved requisition detail (`?from_requisition=<pk>`) |
| **PO Dispatch & Acknowledgment** | `issue_po()` (draft→issued, stamps dispatch), vendor-portal `acknowledge`/`decline`; portal `Notification` to the vendor's portal user |
| **PO Change Order Management** | `PurchaseOrderChangeOrder` (+`apply_change_order()`, `revision` bump, immutable once applied) — qty / price / delivery-date changes on an active PO |
| **PO Cancellation & Close-out** | `cancel_po()` (unfulfilled) / `close_po()` (fully or partially received) status workflow |
| **PO Line Item Tracking** | `PurchaseOrderLine.delivery_status` + `received_quantity`; `record_line_receipt()`; status-grouped tracking board |

## Status workflow
`draft → issued → acknowledged → (partially_received → received) → closed`, plus `declined` (issued→declined→draft/cancel) and `cancelled`.
- EDITABLE `('draft',)` · ISSUABLE `('draft',)` · ACKNOWLEDGEABLE `('issued',)`
- RECEIVABLE `('issued','acknowledged','partially_received')` · CHANGE_ORDERABLE `('issued','acknowledged','partially_received')`
- CANCELLABLE `('draft','issued','acknowledged','partially_received','declined')` · CLOSEABLE `('partially_received','received')`
- OPEN `('draft','issued','acknowledged','partially_received')` · FINISHED `('closed','cancelled')`

## Build checklist

### A. App scaffold + wiring
- [ ] `apps/purchase_orders/__init__.py`, `apps.py` (`PurchaseOrdersConfig`, label `purchase_orders`)
- [ ] Add `'apps.purchase_orders'` to `config/settings.py` INSTALLED_APPS (after `apps.contracts`)
- [ ] Mount `path('purchase-orders/', include('apps.purchase_orders.urls'))` in `config/urls.py`

### B. Models (`models.py`) + migration
- [ ] Module-level choice constants + status tuples (above)
- [ ] `PurchaseOrder` (po_number `PO-<SLUG>-NNNNN`, vendor FK, nullable `requisition` FK, currency, order/expected dates, subtotal/tax/shipping/total, dispatch + ack + close/cancel stamps, owner/created_by, payment_terms, ship_to, notes, revision)
- [ ] `PurchaseOrderLine` (line_no, description, uom, quantity, unit_price, line_total, account_code FK, nullable `requisition_line` FK, required_date, `delivery_status`, received_quantity)
- [ ] `PurchaseOrderChangeOrder` (change_number, change_type, reason, new_expected_delivery_date, proposed_lines JSON, prev_* snapshot, status, decided_*)
- [ ] `PurchaseOrderStatusEvent` (append-only: po FK, change_order FK nullable, status, note, actor)
- [ ] `PurchaseOrderDocument` (FileField upload, mirror ContractDocument)
- [ ] `makemigrations purchase_orders` → review `0001_initial`

### C. Services (`services.py`)
- [ ] `next_po_number(tenant)` (gap-free, `all_objects` + collision loop) · `next_change_number(po)`
- [ ] Role helpers: `MANAGE_ROLES`, `VIEW_ROLES`, `_has_role`, `can_manage_po`, `can_view_po`
- [ ] `record_status_event(po, status, user, note, change_order=None)` · `recompute_totals(po)`
- [ ] `create_po_from_requisition(req, user)` (@atomic; copy lines; link req; mark requisition converted; audit)
- [ ] `issue_po` / `acknowledge_po` / `decline_po` / `reopen_po` — @atomic, stamps, event, audit, vendor notify
- [ ] `record_line_receipt(po, line, qty, user)` (line + PO receiving status rollup)
- [ ] `cancel_po(po, user, reason)` · `close_po(po, user, note)`
- [ ] `create_change_order` / `apply_change_order(co, user)` (@atomic, snapshot prev, apply, bump revision, immutable after)
- [ ] `scan_po_alerts(tenant=None, now=None)` (awaiting-ack + overdue-delivery, idempotent via `*_alerted_at`)
- [ ] Vendor gate: `po_visible_to(user, po)`

### D. Forms (`forms.py`)
- [ ] `PurchaseOrderForm` (vendor qs excludes suspended/blacklisted/inactive; requisition optional; date widgets)
- [ ] `PurchaseOrderLineForm` (account_code tenant-filtered) · `ChangeOrderForm`
- [ ] Action forms: `AcknowledgePOForm`, `DeclinePOForm`, `CancelPOForm`, `CloseoutForm`, `ReceiveLineForm`

### E. Views + URLs
- [ ] `urls.py` (`app_name='purchase_orders'`): dashboard/analytics, list, new, detail, edit, delete, issue, acknowledge, decline, reopen, cancel, close, line add/edit/delete/receive, change-order create/detail/apply/cancel, documents add/delete, tracking
- [ ] `views.py`: permission gates, list (search+filters+paginate), create (incl. `?from_requisition=`), detail, edit, delete, all lifecycle + line + change-order + document actions, tracking board (lazy `scan_po_alerts`), analytics dashboard

### F. Admin (`admin.py`)
- [ ] Register PO (+line/change-order inlines), ChangeOrder (read-only once applied), StatusEvent (append-only: no add/change/delete), Document

### G. Templates (`templates/purchase_orders/`)
- [ ] `po_list.html`, `po_form.html`, `po_detail.html` (lines + change orders + timeline + actions), `po_change_order_form.html`, `po_line_form.html`, `tracking.html`, `analytics.html` — Actions column per CRUD Completeness rules

### H. Vendor portal
- [ ] Repoint `portal_purchase_orders` to a real list; add `portal_po_detail` + `portal_po_acknowledge`/`decline` (POST) in `apps/vendors/views.py`
- [ ] Routes in `apps/vendors/portal_urls.py`; templates `templates/vendor_portal/purchase_orders/{list,detail}.html` (replace placeholder)

### I. Requisition integration
- [ ] "Create Purchase Order" button on `templates/requisitions/requisitions/detail.html` when `status == 'approved'` and not already converted

### J. Seed + management command
- [ ] `management/__init__.py` + `management/commands/__init__.py`
- [ ] `seed_purchase_orders.py` (idempotent, per-tenant; POs across every status + one w/ applied change order + one from an approved requisition)
- [ ] Append `('seed_purchase_orders', ...)` to `seed_data.py` steps
- [ ] `run_po_alerts.py` (cron-friendly `scan_po_alerts` sweep)

### K. Tests (`tests/`)
- [ ] `conftest.py` fixtures + `test_models.py`, `test_services.py`, `test_views.py`, `test_security.py` (IDOR, cross-vendor PO/ack, XSS, permission gates, anon redirect) — target ~150–180 tests

### L. Docs + verification
- [ ] README: Module 11 section, intro list, Project Structure, routes table, Management Commands, Seeded Demo Data, Roadmap (→ Shipped), TOC, test count
- [ ] `pytest apps/purchase_orders`, `makemigrations --check`, smoke the pages
- [ ] Hand the user **one-file-per-commit** PowerShell snippets

## Review

**Status: complete & verified (2026-06-04).**

- New app `apps/purchase_orders/` — 5 models (`PurchaseOrder`, `PurchaseOrderLine`,
  `PurchaseOrderChangeOrder`, `PurchaseOrderStatusEvent` append-only, `PurchaseOrderDocument`),
  full service layer (`next_po_number`, `can_manage_po`/`can_view_po`, `po_visible_to`,
  `create_purchase_order`, `create_po_from_requisition`, `issue_po`/`acknowledge_po`/`decline_po`/
  `reopen_po`, `record_line_receipt`, `cancel_po`/`close_po`, `apply_change_order`/
  `cancel_change_order`, `scan_po_alerts`, `tenant_po_metrics`), views + portal_views, forms,
  admin, urls, seed command, `run_po_alerts` cron command.
- 9 internal templates under `templates/purchase_orders/` + 2 vendor-portal templates under
  `templates/vendor_portal/purchase_orders/` (replaced the Module-11 placeholder).
- All 3 locked design defaults implemented as planned: portal-based acknowledgment (no token page),
  lightweight per-line receiving, no PO template library.
- Wiring: `INSTALLED_APPS`, `/purchase-orders/` mount, sidebar "Purchase Orders" group (after
  Catalog), `seed_data` orchestrator extended, vendor-portal routes + repointed `purchase_orders`
  view (dead Module-5 placeholder view + flat template removed), "Create Purchase Order" button on
  the approved-requisition detail. README updated end to end (Module 11 → Shipped).

**Verification performed:**
- `manage.py check` — 0 issues; `makemigrations --check` — no missing migrations.
- `migrate` + `seed_purchase_orders` — 8 POs/tenant across every status + a 9th from the approved
  requisition; idempotent re-run skips; `--flush` re-seeds; `run_po_alerts` flags overdue deliveries.
- **pytest: 92 PO tests pass; full project suite 806 pass (0 failures)** — my edits to shared files
  broke nothing.

**Bug found & fixed during seeding:** the seed chained lifecycle calls on one in-memory PO; the
services re-fetch the row internally (so the caller's object goes stale), leaving every chained step
(`acknowledge`→`receive`→`close`) failing its status precondition silently. Fixed by refreshing the
PO after each step (this is the [[navpms-module-build-cadence]] gotcha #2 — applied). Production views
are unaffected (each request re-fetches).

**Note (parallel session):** Module 10 (Catalog) was committed by another session mid-build; my
`config/settings.py` + `config/urls.py` PO lines were swept into catalog-labelled commits. Those two
files are therefore already committed; the per-file snippets below cover only the rest.

**Files:** 22 new (`apps/purchase_orders/` package + 11 templates) + 6 modified + 1 deleted.

---

# Module 6 — Sourcing & Tendering

**Created:** 2026-05-25
**Scope:** New Django app `apps/sourcing/` implementing the 5 PMS sub-modules of Module 6.
Internal buyer-side surface at `/sourcing/`, vendor-side bid submission integrated into
the existing `/vendor-portal/` namespace (no second portal shell).

| Sub-module | Implementation |
|------------|----------------|
| **Event Creation & Scheduling** | `SourcingEvent` (`SRC-<SLUG>-NNNNN`, type RFQ/RFP/RFT/Tender, publish/close/award-target dates, status `draft → scheduled → open → closed → under_evaluation → awarded`, with `cancelled`). Optional FK to source `Requisition` so an approved REQ can spawn an event with pre-filled lines. Inline `SourcingEventItem` lines (item description, qty, uom, est. unit price, optional `AccountCode`, required date). |
| **Bid Submission Portal** | `SourcingEventInvitee` (one row per invited vendor: `invited → viewed → submitted / declined / withdrawn`). Bid surface in the existing vendor portal (`/vendor-portal/sourcing/`) — invited vendors see their invitations, open the event read-only, then submit a `Bid` with one `BidLine` per `SourcingEventItem` plus `BidDocument` uploads. **Sealed bids**: bid content is hidden from buyers (and from other vendors) until the event closes. |
| **Bid Evaluation Matrix** | `SourcingCriterion` (weighted criteria per event, weights sum to 100 — validated at publish time). `BidEvaluation` (one score per `(bid, criterion, evaluator)` — supports panel scoring; multi-evaluator average per criterion). Service computes `overall_score = Σ(weight × avg_score / max_score)`, persisted on `Bid.overall_score`, rank persisted on `Bid.rank`. Side-by-side bid comparison grid on event detail. |
| **Award Recommendation** | Service `recommend_award(event, vendor, amount, user, justification)` creates a `SourcingAward` (status `recommended`). `finalize_award(event, vendor, user)` flips `Bid.status` → `awarded` for the winner, `rejected` for the rest, sets `event.status='awarded'`, denormalises winning vendor/amount onto the event. Supports `allow_partial_award` (multiple awards per event by item). **No Module 4 routing** — direct admin action per scope decision. |
| **Sourcing Analytics** | Per-event analytics card (estimated vs awarded, % savings, # invitees / # bids / response rate, cycle time draft→award). Tenant-wide dashboard at `/sourcing/analytics/` with Chart.js: monthly events run, savings $ / %, top categories, top vendors by win rate. |

## Architecture decisions
- New app `apps/sourcing/` mounted at `/sourcing/`. Vendor-facing bid routes added under the
  existing `vendor_portal` namespace (`apps/vendors/portal_urls.py`) — no parallel shell.
- Integration with **Module 3 (Requisitions)**: `SourcingEvent.requisition` (FK nullable) and a
  service `create_event_from_requisition(req, user)` that copies REQ lines into event items.
  Requisition detail template gets a "Create Sourcing Event" button shown only for `status='approved'`.
- Integration with **Module 5 (Vendors)**: invitees are picked from active vendors (excluding
  `suspended`, `blacklisted`). Active vendors with a portal user receive an in-portal
  invitation; vendors without a portal user can still be invited (admin can email the bid
  details manually — out-of-scope automated email).
- **Sealed-bid enforcement**: a `BidVisibilityMixin` on the service layer (and a guard inside
  `get_bid_visible_to(user, bid)`) blocks buyers from reading bid lines/docs/total until
  `event.status in {'closed','under_evaluation','awarded','cancelled'}`. Vendor authors can
  always read their own bid. Tested.
- **Event status workflow** (with allowed transitions):
  - `draft` → `scheduled` (validates: ≥1 item, ≥1 invitee, criteria sum to 100, publish/close set)
  - `scheduled` → `open` (manual "Open now" or auto via `publish_at` reached — manual only in v1, no celery)
  - `open` → `closed` (manual or auto via `close_at` reached — manual only in v1)
  - `closed` → `under_evaluation` (when an evaluator submits the first score)
  - `under_evaluation` → `awarded` (via `finalize_award`)
  - any open status → `cancelled`
- **Bid status workflow**:
  - `draft` (vendor working) → `submitted` (locks the bid, sets `submitted_at`)
  - `submitted` → `under_review` (any evaluator opens it post-close)
  - `under_review` → `shortlisted` / `rejected` (manual decision)
  - `shortlisted` → `awarded` (via finalize)
  - `draft`/`submitted` → `withdrawn` (vendor self-withdraw, only while event is `open`)
- `SourcingAward` is append-only (admin add/delete disabled), mirroring `AuditLog` /
  `VendorBlacklistEvent`.
- Reuse `TenantAwareModel` / `TimeStampedModel`. All audit writes via `tenants.services.record_audit`.
- **Permission gate**: event create/edit/publish/close/award restricted to roles
  `tenant_admin`, `procurement_manager`, `buyer`. Evaluators are the same set plus `approver`
  (any user with that role can score). Implemented via a `_can_manage_sourcing(user)` helper
  + `_can_evaluate(user)` helper in `apps/sourcing/services.py`.

## Models (`apps/sourcing/models.py`)

1. **SourcingEvent**
   - `tenant` FK, `event_number` (auto `SRC-<SLUG>-NNNNN`, unique per tenant)
   - `title`, `description`, `event_type` (`rfq`/`rfp`/`rft`/`tender`), `category` FK to
     `vendors.VendorCategory` (nullable), `currency` (CHAR 3, default `USD`)
   - `estimated_value` (Decimal 14,2, default 0)
   - `status` (default `draft`) — choices listed above
   - `publish_at`, `close_at`, `award_target_at` (DateTimeFields, all nullable until scheduled)
   - `terms_and_conditions` (TextField)
   - `allow_partial_award` (bool, default False)
   - `created_by` FK to `accounts.User`
   - `requisition` FK to `requisitions.Requisition` (nullable, `on_delete=SET_NULL`)
   - `awarded_vendor` FK to `vendors.Vendor` (nullable), `awarded_amount` (Decimal), `awarded_at`,
     `award_notes`
   - `cancelled_reason` (text, blank), `cancelled_at`, `cancelled_by` FK (nullable)
   - `unique_together(tenant, event_number)`, ordering `['-created_at']`

2. **SourcingEventItem**
   - `event` FK (cascade), `line_no` (int), `item_description`, `uom` (default `EA`),
     `quantity` (Decimal 14,3, `MinValueValidator(0)`), `est_unit_price` (Decimal 14,2,
     `MinValueValidator(0)`), `account_code` FK to `requisitions.AccountCode` (nullable),
     `required_date` (Date, nullable), `notes`
   - `unique_together(event, line_no)`, ordering `['line_no']`

3. **SourcingEventInvitee**
   - `event` FK (cascade), `vendor` FK to `vendors.Vendor` (cascade)
   - `invited_at`, `invited_by` FK, `status` (`invited`/`viewed`/`submitted`/`declined`/`withdrawn`,
     default `invited`), `responded_at` (nullable), `notes`
   - `unique_together(event, vendor)`, ordering `['-invited_at']`

4. **SourcingCriterion**
   - `event` FK (cascade), `name`, `description`, `criterion_type` (`price`/`quality`/`delivery`/
     `compliance`/`experience`/`other`), `weight` (Decimal 5,2, `MinValueValidator(0)` /
     `MaxValueValidator(100)`), `max_score` (default 100), `order` (default 0)
   - ordering `['order','id']`
   - Service-level validator: `sum(event.criteria.weight) == 100` before transitioning to
     `scheduled` / `open`.

5. **Bid**
   - `event` FK (cascade), `vendor` FK to `vendors.Vendor` (cascade), `bid_number` (auto
     `BID-<SLUG>-NNNNN`, unique per tenant — denormalised tenant via event)
   - `status` (default `draft`) — choices listed above
   - `submitted_by` FK to `accounts.User` (nullable — vendor portal user), `submitted_at` (null
     until submit)
   - `total_amount` (Decimal 14,2, default 0 — computed at submit from lines)
   - `currency` (CHAR 3 — copied from event at create)
   - `delivery_lead_time_days` (positive int, nullable), `validity_days` (positive int,
     nullable), `payment_terms` (text, blank), `notes`
   - `is_compliant` (bool, default True — flips False if any required line is missing or `0`)
   - `overall_score` (Decimal 5,2, default 0), `rank` (int, nullable)
   - `withdrawn_at` (nullable)
   - `unique_together(event, vendor)`, ordering `['rank','-submitted_at']`

6. **BidLine**
   - `bid` FK (cascade), `event_item` FK to `SourcingEventItem` (cascade)
   - `unit_price` (Decimal 14,2, `MinValueValidator(0)`), `quantity_offered` (Decimal 14,3,
     default = event_item.quantity), `lead_time_days` (positive int, nullable), `notes`
   - `line_total` property = `unit_price * quantity_offered`
   - `unique_together(bid, event_item)`

7. **BidDocument**
   - `bid` FK (cascade), `title`, `file` (`upload_to='bid_docs/'`), `uploaded_at`
   - Append-only (admin delete disabled); buyer can only read after event close
   - ordering `['-uploaded_at']`

8. **BidEvaluation**
   - `bid` FK (cascade), `criterion` FK (cascade), `evaluator` FK to `accounts.User` (cascade)
   - `score` (Decimal 5,2, validators 0..criterion.max_score), `comment` (text)
   - `evaluated_at` (auto)
   - `unique_together(bid, criterion, evaluator)`, ordering `['-evaluated_at']`

9. **SourcingAward** (append-only)
   - `event` FK (cascade), `vendor` FK (cascade), `bid` FK (cascade)
   - `award_amount` (Decimal 14,2), `currency` (CHAR 3)
   - `status` (`recommended`/`approved`/`contracted`/`cancelled`, default `recommended`)
   - `justification` (text), `awarded_by` FK, `awarded_at` (auto), `notes`
   - ordering `['-awarded_at']`
   - Multiple rows allowed if `event.allow_partial_award`; otherwise service enforces one.

## Services (`apps/sourcing/services.py`)
- `next_event_number(tenant)` — `SRC-<SLUG>-NNNNN`, gap-free per tenant
- `next_bid_number(tenant)` — `BID-<SLUG>-NNNNN`
- `create_event_from_requisition(req, user)` — copies REQ lines → SourcingEventItem
- `validate_event_can_publish(event)` — raises `ValidationError` if items/invitees/criteria sums
  fail; returns warnings list (e.g. close_at in past)
- `publish_event(event, user)` — draft → scheduled (or scheduled → open if `publish_at <= now()`)
- `open_event(event, user)` — scheduled → open
- `close_event(event, user)` — open → closed (locks all submitted bids; rejects un-submitted drafts)
- `cancel_event(event, user, reason)` — any open status → cancelled; withdraws bids
- `invite_vendors(event, vendor_ids, user)` — bulk; records audit
- `decline_invitation(invitee, user)` — vendor portal action
- `start_bid(event, vendor, user)` — creates `Bid(draft)` with one `BidLine` per event item,
  pre-filled qty
- `submit_bid(bid, user)` — validates every line has a price; sets total, compliance, status
- `withdraw_bid(bid, user)` — only event.status='open', vendor self-action
- `record_evaluation(bid, criterion, evaluator, score, comment)` — upserts BidEvaluation,
  advances bid.status to `under_review` if first, recomputes overall_score
- `recompute_bid_scores(event)` — recomputes overall_score + rank across all bids in event
- `recommend_award(event, vendor, amount, user, justification)` — creates SourcingAward
- `finalize_award(event, vendor_ids, user)` — flips bid statuses, event.status='awarded',
  denormalises winner; supports list of vendor_ids when partial-award
- `compute_event_savings(event)` — returns dict {estimated, awarded, savings, savings_pct}
- `tenant_sourcing_metrics(tenant, period_start, period_end)` — for analytics dashboard
- `bid_visible_to(user, bid)` — returns True if user is vendor author OR (event.status in
  closed/eval/awarded/cancelled AND user.is_staff-equiv). Used in views.

## Views (`apps/sourcing/views.py`)
**Internal (buyer side, all `@login_required` + `_can_manage_sourcing` gate):**
- `event_list` — search + filter by status/type/category + pagination
- `event_create` (also accepts `?from_requisition=<id>`)
- `event_detail` — tabs: Overview / Items / Invitees / Criteria / Bids (sealed-aware) /
  Evaluation / Awards
- `event_edit` (draft only)
- `event_delete` (draft only)
- `event_publish` (POST), `event_open` (POST), `event_close` (POST), `event_cancel` (POST)
- `event_item_create`, `event_item_edit`, `event_item_delete` (draft only)
- `invitee_add` (form with vendor multi-select), `invitee_remove`
- `criterion_create`, `criterion_edit`, `criterion_delete` (draft/scheduled only)
- `bid_list_for_event` (only after close)
- `bid_detail` (only after close; sealed otherwise)
- `bid_compare` — side-by-side matrix
- `bid_evaluate` (per criterion, per evaluator)
- `bid_shortlist`, `bid_reject`
- `award_recommend`, `award_finalize`
- `analytics_dashboard` — tenant-wide
- `analytics_event_report` — per event

**Vendor portal (added to `apps/vendors/views.py` or new `apps/sourcing/portal_views.py`):**
- `portal_invitations_list` — vendor's invitations across all events
- `portal_event_detail` — RFQ read-only view (terms, items, criteria with weights, close_at)
- `portal_bid_start` (POST) — creates draft bid
- `portal_bid_edit` — fill prices per line, upload docs
- `portal_bid_submit` (POST)
- `portal_bid_withdraw` (POST)
- `portal_bid_list` — vendor's bids

## URLs

**`apps/sourcing/urls.py`** — `app_name = 'sourcing'`:
```
events/                          name='event_list'
events/new/                      name='event_create'
events/<pk>/                     name='event_detail'
events/<pk>/edit/                name='event_edit'
events/<pk>/delete/              name='event_delete'
events/<pk>/publish/             name='event_publish'
events/<pk>/open/                name='event_open'
events/<pk>/close/               name='event_close'
events/<pk>/cancel/              name='event_cancel'
events/<pk>/items/add/           name='item_create'
events/<pk>/items/<lpk>/edit/    name='item_edit'
events/<pk>/items/<lpk>/delete/  name='item_delete'
events/<pk>/invitees/add/        name='invitee_add'
events/<pk>/invitees/<ipk>/remove/  name='invitee_remove'
events/<pk>/criteria/add/        name='criterion_create'
events/<pk>/criteria/<cpk>/edit/ name='criterion_edit'
events/<pk>/criteria/<cpk>/delete/ name='criterion_delete'
events/<pk>/bids/                name='bid_list'
events/<pk>/bids/compare/        name='bid_compare'
events/<pk>/bids/<bpk>/          name='bid_detail'
events/<pk>/bids/<bpk>/evaluate/ name='bid_evaluate'
events/<pk>/bids/<bpk>/shortlist/ name='bid_shortlist'
events/<pk>/bids/<bpk>/reject/   name='bid_reject'
events/<pk>/awards/recommend/    name='award_recommend'
events/<pk>/awards/finalize/     name='award_finalize'
analytics/                       name='analytics_dashboard'
events/<pk>/analytics/           name='analytics_event_report'
```

**`apps/vendors/portal_urls.py`** — append to existing `vendor_portal` namespace:
```
sourcing/                          name='sourcing_invitations'
sourcing/<event_pk>/               name='sourcing_event_detail'
sourcing/<event_pk>/bid/start/     name='sourcing_bid_start'
sourcing/<event_pk>/bid/<bpk>/     name='sourcing_bid_edit'
sourcing/<event_pk>/bid/<bpk>/submit/   name='sourcing_bid_submit'
sourcing/<event_pk>/bid/<bpk>/withdraw/ name='sourcing_bid_withdraw'
sourcing/bids/                     name='sourcing_my_bids'
```

## Templates

**Internal `templates/sourcing/`:**
- `events/list.html`, `events/form.html`, `events/detail.html` (tabbed)
- `events/cancel.html` (reason form)
- `items/form.html`
- `invitees/form.html` (vendor multi-select)
- `criteria/form.html`
- `bids/list.html`, `bids/detail.html`, `bids/compare.html`
- `bids/evaluate.html` (per-criterion score sheet)
- `awards/recommend.html`, `awards/list.html`
- `analytics/dashboard.html`, `analytics/event_report.html`

**Vendor portal `templates/vendor_portal/sourcing/`:**
- `invitations.html`, `event_detail.html`, `bid_form.html`, `my_bids.html`, `bid_detail.html`

## Forms (`apps/sourcing/forms.py`)
- `SourcingEventForm` (tenant kwarg; `clean_event_number` uniqueness)
- `SourcingEventItemForm`
- `SourcingCriterionForm` (form-level weight validation against existing event total)
- `InviteVendorsForm` (queryset of active vendors, multi-select)
- `BidForm` (vendor-side header: lead time, validity, payment terms, notes)
- `BidLineForm` (one per event item; queryset gated)
- `BidDocumentForm` (file size + extension validator)
- `BidEvaluationForm` (score bounded by criterion.max_score)
- `AwardRecommendForm` (amount, justification)
- `CancelEventForm` (reason text)

## Backend file list (`apps/sourcing/`)
- [ ] `__init__.py`, `apps.py`
- [ ] `models.py` — 9 models above
- [ ] `admin.py` — register all (inlines for items/criteria on event; SourcingAward read-only)
- [ ] `forms.py` — 10 forms above
- [ ] `services.py` — service layer + permission helpers + visibility gate
- [ ] `views.py` — internal buyer views
- [ ] `portal_views.py` — vendor-portal sourcing views (avoids bloating vendors/views.py)
- [ ] `urls.py` — buyer namespace `sourcing`
- [ ] `migrations/__init__.py`
- [ ] `management/__init__.py`, `management/commands/__init__.py`
- [ ] `management/commands/seed_sourcing.py` — idempotent

## Modified files
- [ ] `config/settings.py` — add `'apps.sourcing'`
- [ ] `config/urls.py` — `path('sourcing/', include('apps.sourcing.urls'))`
- [ ] `apps/vendors/portal_urls.py` — append 7 sourcing routes
- [ ] `apps/vendors/views.py` (or new portal_views import) — wire sourcing portal views
      *(decision: import from `apps.sourcing.portal_views` into `apps.vendors.portal_urls.py`
      to keep separation clean)*
- [ ] `templates/partials/sidebar.html` — add "Sourcing" group between Approvals and Vendors
- [ ] `templates/vendor_portal/base.html` — add "RFx / Sourcing" sidebar link
- [ ] `templates/requisitions/requisitions/detail.html` — "Create Sourcing Event" button when
      `requisition.status == 'approved'`
- [ ] `apps/core/management/commands/seed_data.py` — add `seed_sourcing` after `seed_vendors`
- [ ] `README.md` — Project Structure, ToC, Module 6 section, Routes table, Management Commands,
      Seeded Demo Data, Roadmap (Module 6 → Shipped)

## Seed data per tenant
- 3 events:
  1. **Draft** — "Office stationery Q2" (RFQ, 3 items, 4 criteria, 2 invitees, no bids)
  2. **Open** — "Server hardware refresh" (RFP, 4 items, 4 criteria, 3 invitees, 2 draft bids,
     1 submitted bid)
  3. **Awarded** — "Janitorial services Q1" (Tender, 2 items, 4 criteria, 3 invitees, 3
     submitted bids, evaluations done, award finalised to lowest compliant bidder)
- Criteria template: Price 40 / Quality 25 / Delivery 20 / Compliance 15 (sums to 100)
- Invitees pulled from the 3 active vendors seeded in Module 5
- Per the **awarded** event: full evaluation matrix (each criterion scored by `admin_<slug>`),
  ranks computed, savings recorded (estimated 10k → awarded 8.5k = 15% saving)
- 1 `SourcingAward` row for the awarded event

## Verification
- [ ] `python manage.py check` — 0 issues
- [ ] `makemigrations sourcing` → `0001_initial` (9 models, indexes, unique_togethers); `migrate` clean
- [ ] `seed_sourcing` (and via `seed_data --flush`) — populated for each tenant; idempotent rerun warns
- [ ] Smoke test 1 — 18 buyer GET routes return 200 as `admin_acme`
- [ ] Smoke test 2 — vendor portal 5 routes return 200 as an invited vendor portal user
- [ ] Multi-tenancy: `admin_globex` 404s on Acme event detail
- [ ] CRUD: event create/edit/delete (draft only); item/criterion/invitee CRUD
- [ ] Status workflow: draft → publish → open → close → award; cancel from each
- [ ] Sealed-bid: while event is `open`, GET buyer bid_detail returns 403 (or banner-blocked
      page); after `close`, returns 200 with content
- [ ] Sealed-bid: vendor A cannot read vendor B's bid via direct URL
- [ ] Evaluation: scoring all criteria recomputes overall_score and rank
- [ ] Award: finalize sets winner.status=awarded, others=rejected, event.status=awarded,
      denormalises onto event; savings computed
- [ ] REQ→RFQ link: from approved REQ, "Create Sourcing Event" pre-fills items
- [ ] Permission gate: `requester` role cannot reach event_create (redirect / 403)
- [ ] Portal sandbox middleware still blocks vendor user from `/sourcing/` (internal)

## Open questions to confirm before coding
1. **Bid line currency** — single `currency` field on the bid (copied from event) is enough,
   right? Per-line currency would be unusual; if any vendor wants to bid in a different
   currency, they decline and we run a separate event. *(Assumption: single currency.)*
2. **Document size cap** — default to 10 MB per file, 5 files max per bid. *(Open to change.)*
3. **Email notifications on invite** — out of scope for v1 (same posture as Module 5 portal
   invite which returns a one-time password to the inviter). The invitee will see the new
   invitation when they next log into the vendor portal.

If the plan looks right, say "go" and I'll start with `apps/sourcing/__init__.py`,
`apps.py`, `models.py`, and the migrations — committing one file at a time per the CLAUDE.md
rule.

## Review

**Status: complete & verified (2026-05-25).**

- New app `apps/sourcing/` — 9 models (`SourcingEvent`, `SourcingEventItem`,
  `SourcingEventInvitee`, `SourcingCriterion`, `Bid`, `BidLine`, `BidDocument`,
  `BidEvaluation`, `SourcingAward`), full service layer
  (`next_event_number`, `next_bid_number`, `create_event_from_requisition`,
  `publish_event` / `open_event` / `close_event` / `cancel_event`, `invite_vendors`,
  `start_bid` / `submit_bid` / `withdraw_bid`, `record_evaluation` +
  `recompute_bid_scores`, `shortlist_bid` / `reject_bid`, `recommend_award` /
  `finalize_award`, `compute_event_savings`, `tenant_sourcing_metrics`,
  `bid_visible_to` sealed-bid gate, `can_manage_sourcing` / `can_evaluate` perms),
  full views + portal_views, forms, admin, urls, seed command.
- 12 internal templates under `templates/sourcing/` + 5 vendor portal templates under
  `templates/vendor_portal/sourcing/`.
- Sealed-bid enforcement: `bid_visible_to(user, bid)` blocks buyers from reading bid
  content while the event is `draft` / `scheduled` / `open`; vendors can only read
  their own bid via the portal — verified by smoke test (cross-vendor portal read
  returns 404).
- Direct admin award per scope decision (no Module 4 routing in this build).
- REQ → RFQ integration: `Create Sourcing Event` button on approved requisition
  detail spawns an event with items pre-filled from the requisition lines.
- Wiring: `INSTALLED_APPS`, `/sourcing/` URL mount, sidebar "Sourcing" group between
  Approvals and Vendors, vendor-portal sidebar gets "Sourcing > Invitations / My Bids"
  links, `seed_data` orchestrator extended with `seed_sourcing`. README updated end
  to end (Module 6 → Shipped, Routes table extended, Seeded Data extended).

**Verification performed:**
- `manage.py check` — 0 issues.
- `makemigrations sourcing` → `0001_initial` (9 models, indexes, unique_togethers);
  `migrate` OK on MySQL.
- `seed_sourcing` — populated for 3 demo tenants (Acme / Globex / Stark) — each
  gets a draft, an open event (3 invitees, 1 draft + 1 submitted bid), and a fully
  awarded event (3 submitted bids, 16 evaluations, 1 finalised award, recorded
  savings). Idempotent rerun warns + skips; `--flush` re-seeds cleanly.
- Smoke test 1 (buyer side, admin_acme): **15 GET routes returned 200** — event
  list / create / detail / edit / analytics dashboard / per-event analytics report /
  sealed bid list / unsealed bid list / bid compare / bid detail / bid evaluate.
- Smoke test 2 (vendor portal, invited vendor): **5 routes returned 200** —
  invitations list, event detail (read-only), my bids, bid edit, bid detail.
- Smoke test 3 (multi-tenancy): Globex admin GET on Acme event detail → 404. ✓
- Smoke test 4 (sealed bid): vendor user GET on another vendor's bid → 404. ✓
- Smoke test 5 (sandbox): vendor user GET on internal `/sourcing/events/` →
  302 redirect to `/vendor-portal/dashboard/`. ✓
- Workflow exercised end-to-end by seed: draft → publish (open) → close (auto on
  seed) → evaluate (16 panel scores) → recompute ranks → recommend award →
  finalize → winner.status='awarded', losers='rejected', event.status='awarded',
  savings denormalised.

**Design notes:**
- `bid_visible_to(user, bid)` is the single source of truth for sealed-bid policy.
  Buyer views render a placeholder card when the check fails (instead of 403)
  so the page still loads with helpful context — invitee count, close date.
- `recompute_bid_scores` re-derives all bid scores + ranks any time an evaluation
  is recorded. `Bid.overall_score` and `Bid.rank` are denormalised for fast list
  rendering (mirrors Vendor.risk_level denorm from Module 5).
- The `_can_manage_sourcing` helper checks `role in (tenant_admin,
  procurement_manager, buyer)` plus the `is_tenant_admin` flag. Requesters get a
  redirect with a flash message — verified by inspection of the role gate in
  every internal view.
- Vendor portal mounts the bid surface under the existing `vendor_portal`
  namespace so no second shell exists. The sidebar gets a "Sourcing" section
  inside the same `vp-sidebar`, keeping the supplier UX coherent.
- `create_event_from_requisition` creates the event AND its items in a single
  transaction; the view then redirects to event detail so the user immediately
  sees the pre-filled lines.
- `cancel_event` withdraws any in-flight bids (`draft / submitted / under_review`)
  in the same transaction — keeps the bid ledger consistent.
- `finalize_award` rejects only non-awarded bids that are not already withdrawn
  or rejected — so vendors who voluntarily withdrew don't get a "rejected" status.

**Files changed:** 31 new + 9 modified = 40 files.

---

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


## Module 12 — Order Fulfillment & Tracking (review)

**Status: COMPLETE & verified.** New `apps/fulfillment/` app (PMS.md `### 11` = real Module 12).

Built (mirrors Module 11): models (Shipment, ShipmentLine, ShipmentTrackingEvent, Backorder,
ShipmentStatusEvent, ShipmentDocument) + 2 migrations; `carriers.py` pluggable connector
(MockCarrier, `FREIGHT_CARRIER` env, SSRF-validated); services (gates, SHP-numbering,
advise/sync/confirm/cancel/close, idempotent receipt posting via `record_line_receipt`,
backorders, alerts, metrics); forms; admin (append-only ledgers); buyer views + vendor-portal
ASN; 12 templates (generated via a parallel workflow, reviewed); sidebar nav; `seed_fulfillment`
+ `run_fulfillment_alerts` (chained into `seed_data`); wiring (settings/urls/portal_urls/.env).

Verification:
- `pytest apps/fulfillment --create-db` -> **75 passed** (models/services/views/security + 6 fix tests).
- Live smoke render: all buyer + vendor-portal pages 200. `manage.py check` clean. seed + re-seed OK.

Adversarial multi-agent review (3 lenses -> verify): 8 findings, 7 confirmed, **all fixed**:
1. Manual tracking event / sync could jump a draft straight to `delivered` -> gated to `can_track`.
2. TOCTOU: lifecycle guards now run AFTER `select_for_update` (advise/confirm/cancel/close).
3. `record_line_receipt` lost-update -> re-fetch+lock the PO line (Module 11 file touched).
4. `line_no` collision after mid-list delete -> `Max(line_no)+1` in both add-line views.
5. Two shipment lines for one PO line -> `unique_together(shipment, purchase_order_line)` + form guard.
6. Manual events on finished shipments -> blocked by the `can_track` gate.
7. Received-condition/delivered-at now shown for the `received` state, not just `delivered`.

NOTE (parallel session): Module 13 (`apps/goods_receipt/`) was being built concurrently and
edited shared files (settings/urls/portal_urls/seed_data/sidebar/README) live. Diff those shared
files before committing; `record_line_receipt` lives in the PO module (Module 11) and was hardened
here — review that commit separately.
