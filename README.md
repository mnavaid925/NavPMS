# NavPMS — Procurement Management System

A multi-tenant, Bootstrap 5 + Django Procurement Management System with a unique blue/white
dashboard, light/dark mode, multiple layout variants, and a pluggable payment gateway.

This release ships the **Foundation** (project scaffolding, multi-tenancy, authentication,
user management, themed dashboard), **Module 1 — Tenant & Subscription Management** (all
five sub-modules: Onboarding, Subscription & Billing, Isolation & Security, Custom Branding,
Health Monitoring), **Module 2 — User Dashboard & Portal** (all five sub-modules:
Personalized Overview, Task & Alert Center, Quick Requisition Entry, Recent Activity Feed,
Self-Service Reporting), **Module 3 — Requisition Management** (all five sub-modules:
Requisition Creation, Requisition Tracking, Duplicate Requisition Check, Requisition
Templates, Cancellation/Amendment), **Module 4 — Approval Workflow Engine** (all five
sub-modules: Dynamic Routing Rules, Delegation of Authority, Approval History & Audit Trail,
Escalation Management, Mobile Approval Interface), **Module 5 — Vendor Management**
(all five sub-modules: Vendor Onboarding, Vendor Portal, Vendor Classification &
Segmentation, Vendor Risk Profiling, Vendor Blacklisting/Suspension), and
**Module 6 — Sourcing & Tendering** (all five sub-modules: Event Creation & Scheduling,
Bid Submission Portal, Bid Evaluation Matrix, Award Recommendation, Sourcing Analytics),
and **Module 7 — RFx Management** (all five sub-modules: Questionnaire Builder,
Response Collection, Side-by-Side Comparison, Scoring & Weighting, RFx Template Library),
and **Module 8 — E-Auction Management** (all five sub-modules: Auction Setup &
Configuration, Live Bidding Interface, Bid Extension & Rule Enforcement, Auction Monitoring
Console, Post-Auction Results), and **Module 9 — Contract Management** (all five sub-modules:
Contract Authoring & Templating, E-Signature Integration, Renewal & Expiration Alerts,
Contract Amendment Tracking, Obligation & Milestone Management), and
**Module 10 — Catalog Management** (all five sub-modules: Catalog Item Creation,
Pricing & Tier Management, Catalog Approval Workflow, Punch-out Catalog Integration,
Supplier Catalog Hosting), and **Module 11 — Purchase Order Management** (all five
sub-modules: PO Generation, PO Dispatch & Acknowledgment, PO Change Order Management,
PO Cancellation & Close-out, PO Line Item Tracking), and
**Module 12 — Order Fulfillment & Tracking** (all five sub-modules: Advanced Shipping
Notice (ASN), Real-time Freight Tracking, Delivery Confirmation, Backorder Management,
Split Delivery Management), and **Module 13 — Goods Receipt & Inspection** (all five
sub-modules: GRN Creation, Quality Inspection Checklists, Discrepancy Reporting, Return to
Vendor, Item Tagging & Barcoding), and **Module 14 — Invoice & Voucher Management** (all
five sub-modules: Invoice Capture (OCR), Three-Way Matching, Dispute Resolution Workflow,
Payment Schedule/Terms Management, Early Payment Discount Tracking), and
**Module 15 — Spend Analytics & Reporting** (all five sub-modules: Spend Dashboards, Custom
Report Builder, Category Spend Analysis, Maverick Spend Tracking, Data Export & Visualization),
and **Module 16 — Budget & Cost Management** (all five sub-modules: Budget Allocation & Mapping,
Budget Availability Check, Commitment Accounting, Variance Analysis, Forecasting & Projection),
and **Module 17 — Supplier Performance & Evaluation** (all five sub-modules: KPI Definition & Setup,
Scorecard Generation, 360-Degree Feedback Collection, Performance Improvement Plans, Benchmarking &
Trending), and **Module 18 — Risk & Compliance Management** (all five sub-modules: Regulatory
Compliance Checks, Supplier Financial Risk Monitoring, Audit Trail & Logging (tamper-evident
hash-chain), Fraud Detection Rules, Policy Management & Acknowledgment), and
**Module 19 — Inventory & Warehouse Integration** (all five sub-modules: Stock Level Visibility,
Reorder Point Automation, Goods Issue/Return to Stock, Warehouse Location Mapping, Cycle Count
Integration), and **Module 20 — Document & Knowledge Management** (all five sub-modules: Central
Document Repository, Version Control, Procurement Policy Library, Best Practices & Templates,
Full-Text Search & Indexing).

---

## Table of Contents
1. [Tech Stack](#tech-stack)
2. [Project Structure](#project-structure)
3. [Quick Start (Windows + XAMPP)](#quick-start-windows--xampp)
4. [Environment Variables](#environment-variables)
5. [Management Commands](#management-commands)
6. [Testing](#testing)
7. [Seeded Demo Data](#seeded-demo-data)
8. [Dashboard Features](#dashboard-features)
9. [Module 1 — Tenant & Subscription Management](#module-1--tenant--subscription-management)
10. [Module 2 — User Dashboard & Portal](#module-2--user-dashboard--portal)
11. [Module 3 — Requisition Management](#module-3--requisition-management)
12. [Module 4 — Approval Workflow Engine](#module-4--approval-workflow-engine)
13. [Module 5 — Vendor Management](#module-5--vendor-management)
14. [Module 6 — Sourcing & Tendering](#module-6--sourcing--tendering)
15. [Module 7 — RFx Management](#module-7--rfx-management)
16. [Module 8 — E-Auction Management](#module-8--e-auction-management)
17. [Module 9 — Contract Management](#module-9--contract-management)
18. [Module 10 — Catalog Management](#module-10--catalog-management)
19. [Module 11 — Purchase Order Management](#module-11--purchase-order-management)
20. [Module 12 — Order Fulfillment & Tracking](#module-12--order-fulfillment--tracking)
21. [Module 13 — Goods Receipt & Inspection](#module-13--goods-receipt--inspection)
22. [Module 14 — Invoice & Voucher Management](#module-14--invoice--voucher-management)
23. [Module 15 — Spend Analytics & Reporting](#module-15--spend-analytics--reporting)
24. [Module 16 — Budget & Cost Management](#module-16--budget--cost-management)
25. [Module 17 — Supplier Performance & Evaluation](#module-17--supplier-performance--evaluation)
26. [Module 18 — Risk & Compliance Management](#module-18--risk--compliance-management)
27. [Module 19 — Inventory & Warehouse Integration](#module-19--inventory--warehouse-integration)
28. [Module 20 — Document & Knowledge Management](#module-20--document--knowledge-management)
29. [Routes / UI Tour](#routes--ui-tour)
30. [Multi-tenancy Model](#multi-tenancy-model)
31. [Payment Gateway](#payment-gateway)
32. [Browser Compatibility](#browser-compatibility)
33. [Roadmap](#roadmap)

---

## Tech Stack

| Layer | Choice |
|------|--------|
| Backend | Django 4.2 |
| Database | MySQL 8 (via XAMPP) |
| Auth | Custom `User` (`accounts.User`) extending `AbstractUser` |
| Frontend | Bootstrap 5.3, RemixIcon, vanilla JS (no jQuery) |
| Charts | Chart.js 4 (CDN) |
| Forms | django-crispy-forms + crispy-bootstrap5 |
| Config | python-decouple (`.env` file) |
| Seeding | Faker |
| Payment | Mock (pluggable: swap [`apps/tenants/gateways.py`](apps/tenants/gateways.py) for Stripe / Razorpay) |
| Punch-out | Real cXML/OCI (pluggable [`apps/catalog/punchout.py`](apps/catalog/punchout.py)); `requests` + `defusedxml` (XXE-safe); supplier XLSX uploads via `openpyxl` |

---

## Project Structure

```
NavPMS/
├── apps/
│   ├── core/                 # Tenant model, middleware, mixins, dashboard view
│   ├── accounts/             # Custom User, UserProfile, UserInvite, auth flow
│   ├── tenants/              # Module 1: Plans, Subscriptions, Invoices, Branding,
│   │                         # Security, Audit, Health Monitoring + onboarding wizard
│   ├── portal/               # Module 2: DashboardWidget, Notification,
│   │                         # QuickRequisition(+Item), SavedReport, activity feed
│   ├── requisitions/         # Module 3: AccountCode, RequisitionTemplate(+Line),
│   │                         # Requisition(+Line), RequisitionStatusEvent
│   ├── approvals/            # Module 4: ApprovalRule(+Step), ApprovalDelegation,
│   │                         # ApprovalRequest, ApprovalTask, ApprovalAction
│   ├── vendors/              # Module 5: VendorCategory, VendorSegment, Vendor,
│   │                         # VendorContact, VendorDocument, VendorBankAccount,
│   │                         # VendorOnboardingApplication, VendorRiskAssessment,
│   │                         # VendorBlacklistEvent (+ vendor portal sandbox)
│   ├── sourcing/             # Module 6: SourcingEvent(+Item), SourcingEventInvitee,
│   │                         # SourcingCriterion, Bid(+Line +Document), BidEvaluation,
│   │                         # SourcingAward (append-only)
│   ├── rfx/                  # Module 7: RfxEvent (+Section +Question), RfxInvitee,
│   │                         # RfxResponse (+Answer), RfxEvaluation, RfxDocument,
│   │                         # RfxTemplate (+Section +Question)
│   ├── auctions/             # Module 8: Auction (+Lot), AuctionParticipant,
│   │                         # AuctionBid (append-only ledger), AuctionDocument
│   ├── contracts/            # Module 9: ContractClause (library), ContractTemplate
│   │                         # (+Clause), Contract (+ClauseLine), ContractSignatory,
│   │                         # ContractAmendment, ContractObligation, ContractDocument,
│   │                         # ContractStatusEvent (append-only)
│   ├── catalog/              # Module 10: CatalogCategory, CatalogItem, CatalogPriceTier,
│   │                         # CatalogPriceChangeRequest, CatalogItemStatusEvent
│   │                         # (append-only), SupplierPunchoutConfig, PunchoutSession,
│   │                         # SupplierCatalogUpload + punchout.py connector registry
│   ├── purchase_orders/      # Module 11: PurchaseOrder (+Line), PurchaseOrderChangeOrder,
│   │                         # PurchaseOrderStatusEvent (append-only), PurchaseOrderDocument
│   ├── fulfillment/          # Module 12: Shipment (+Line), ShipmentTrackingEvent
│   │                         # (append-only), Backorder, ShipmentStatusEvent (append-only),
│   │                         # ShipmentDocument + carriers.py connector registry
│   ├── goods_receipt/        # Module 13: GoodsReceipt (+Line w/ lot/batch/serial/expiry/bin),
│   │                         # GoodsReceiptCheck (QA checklist), GoodsReceiptStatusEvent
│   │                         # (append-only), GoodsReceiptAttachment (evidence),
│   │                         # ReturnToVendor (+Line), ReceiptTag (barcode/QR)
│   ├── invoicing/            # Module 14: PaymentTerm, SupplierInvoice (+Line),
│   │                         # SupplierInvoiceStatusEvent (append-only), InvoiceDisputeNote
│   │                         # (append-only thread), PaymentVoucher (+StatusEvent) +
│   │                         # ocr.py pluggable OCR-capture connector registry
│   ├── spend_analytics/      # Module 15: SpendRecord (synced spend fact table), SpendReport
│   │                         # (saved report builder) + services (sync/metrics/run/export) +
│   │                         # exports.py (CSV/XLSX helper)
│   ├── budget/               # Module 16: BudgetPeriod, Budget (+Allocation lines),
│   │                         # BudgetStatusEvent (append-only), BudgetCheck (append-only
│   │                         # availability-check log) + services (compute-on-read consumption,
│   │                         # availability check, variance, forecast, alerts)
│   ├── supplier_performance/ # Module 17: KpiDefinition, Scorecard (+ScorecardLine snapshot),
│   │                         # PerformanceFeedback, ImprovementPlan (+PIPAction +PIPStatusEvent
│   │                         # append-only) + services (KPI engine, scorecard generation,
│   │                         # trending/benchmarking, feedback, PIP lifecycle, cron)
│   ├── compliance/           # Module 18: RestrictedPartyEntry, ComplianceScreening (+ScreeningMatch),
│   │                         # FinancialRiskProfile (+Snapshot history), FraudRule + FraudAlert
│   │                         # (+event log), Policy (+Version +Acknowledgment) + screening.py /
│   │                         # credit.py pluggable connectors (reuses tenants.AuditLog hash-chain)
│   ├── inventory/            # Module 19: Warehouse (+WarehouseLocation bins), StockItem (on-hand
│   │                         # roll-up + reorder params + moving-avg cost), StockLevel (per-bucket),
│   │                         # StockMovement (append-only ledger), GoodsIssue (+Line), CycleCount
│   │                         # (+Line) + services (GRN->stock sync, reorder automation, cron)
│   └── dms/                  # Module 20: Document (+current_version pointer), DocumentVersion
│                             # (file + extracted_text index), PolicyTemplate, DocumentEvent
│                             # (append-only) + extraction.py pluggable text-extraction connector
│                             # (mock / local pypdf) + services (index, publish/supersede, search)
├── config/                   # settings.py, urls.py, wsgi.py, asgi.py
├── static/
│   ├── css/  style.css, auth.css
│   ├── js/   app.js (theme manager), auth.js, auction.js (live-bidding poll engine)
│   └── images/ logo.svg, logo-dark.svg, favicon.svg
├── templates/
│   ├── base.html             # App shell (sidebar/topbar/footer + theme settings)
│   ├── base_auth.html        # Auth shell (centered card)
│   ├── partials/             # sidebar, topbar, footer, preloader, theme_settings, ...
│   ├── auth/                 # login, register, forgot, reset, accept invite
│   ├── dashboard/index.html
│   ├── accounts/{users,invites,profile}/
│   ├── tenants/{onboarding,plans,subscriptions,invoices,branding,security,monitoring}/
│   ├── portal/{widgets,notifications,requisitions,reports,activity}/ + dashboard.html
│   ├── requisitions/{account_codes,req_templates,requisitions}/ + tracking.html
│   ├── approvals/{rules,delegations,requests}/ + inbox, task_detail, history
│   ├── vendors/{vendors,categories,segments,risk,onboarding,blacklist}/
│   ├── sourcing/{events,items,criteria,bids,awards,analytics}/
│   ├── rfx/{events,sections,questions,responses,templates,analytics}/
│   ├── auctions/             # list, form, detail, lot_form, console, results, analytics
│   ├── contracts/            # list, form, detail, author, clause/template libraries,
│   │                         # signatory/amendment/obligation forms, renewals + obligation
│   │                         # boards, analytics
│   ├── catalog/              # item list/form/detail, tier + price-change forms, approval
│   │                         # board, category + punch-out + upload pages, analytics
│   ├── purchase_orders/      # po list/form/detail, change-order + line forms, tracking board,
│   │                         # analytics
│   ├── invoicing/            # invoice list/capture(OCR)/form/detail (lines + 3-way match +
│   │                         # dispute thread + vouchers + timeline), payment-term + voucher
│   │                         # pages, analytics (AP aging + discount opportunities)
│   ├── spend_analytics/      # dashboard (KPIs + charts + basis toggle), category analysis
│   │                         # (+ drill), maverick tracking, report list/form/detail
│   ├── budget/               # dashboard (allocated/actual/committed), budget + period
│   │                         # list/form/detail, allocation form, variance, forecast, check log
│   └── vendor_portal/        # Separate shell for supplier self-service
│       ├── sourcing/         # Vendor-side bid submission + invitations
│       ├── rfx/              # Vendor-side RFx invitations + response form
│       ├── auctions/         # Vendor-side auction invitations + live bidding
│       ├── contracts/        # Vendor-side contracts + tokenized e-signature
│       ├── catalog/          # Vendor-side catalog list + self-service file uploads
│       ├── purchase_orders/  # Vendor-side PO inbox + acknowledge / decline
│       └── invoicing/        # Vendor-side invoice submission + dispute thread
├── .env                      # Local environment (gitignored)
├── .env.example              # Template
├── manage.py
├── requirements.txt
└── README.md
```

---

## Quick Start (Windows + XAMPP)

> Prereqs: Python 3.10+, MySQL via XAMPP running on port 3306.

```powershell
# 1. Create the database in phpMyAdmin (or via CLI)
#    -> http://localhost/phpmyadmin -> New -> name: navpms  -> Collation: utf8mb4_unicode_ci

# 2. Create and activate a virtualenv
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the env template (or keep the supplied .env)
copy .env.example .env

# 5. Run migrations
python manage.py makemigrations
python manage.py migrate

# 6. Create a Django superuser (cross-tenant admin)
python manage.py createsuperuser

# 7. Seed demo data (plans + 3 tenants + invoices + users + audit log)
python manage.py seed_data

# 8. Run the dev server
python manage.py runserver
```

Open `http://127.0.0.1:8000/` and sign in with one of the demo accounts below.

> **Warning** — the Django superuser created by `createsuperuser` has `tenant=None`. Module 1
> pages will appear empty for that account. Use the seeded tenant-admin accounts
> (e.g. `admin_acme`) to see populated data.

---

## Environment Variables

All values are read via `python-decouple` from `.env`.

| Variable | Default | Notes |
|----------|---------|-------|
| `SECRET_KEY` | dev placeholder | Replace before deploy. |
| `DEBUG` | `True` | |
| `ALLOWED_HOSTS` | `*` | Comma-separated. |
| `DB_ENGINE` | `django.db.backends.mysql` | |
| `DB_NAME` | `navpms` | Create in phpMyAdmin first. |
| `DB_USER` | `root` | |
| `DB_PASSWORD` | `` | Default XAMPP MySQL has no password. |
| `DB_HOST` | `127.0.0.1` | |
| `DB_PORT` | `3306` | |
| `APP_NAME` | `NavPMS` | Shown in `<title>` and topbar. |
| `LOGIN_URL` | `/accounts/login/` | |
| `LOGIN_REDIRECT_URL` | `/` | |
| `LOGOUT_REDIRECT_URL` | `/accounts/login/` | |
| `EMAIL_BACKEND` | console | Dev only. |
| `DEFAULT_FROM_EMAIL` | `no-reply@navpms.local` | |
| `PAYMENT_GATEWAY` | `mock` | Switch to `stripe` / `razorpay` after registering a handler. |
| `PUNCHOUT_CONNECTOR` | `cxml` | Default punch-out connector (`cxml` / `oci` / `loopback`). |
| `PUNCHOUT_SSRF_ALLOWLIST` | `` | Comma-separated extra hosts a punch-out setup URL may target (else HTTPS + public-host only). |
| `FREIGHT_CARRIER` | `mock` | Default freight-tracking carrier connector (real carriers added in `apps/fulfillment/carriers.py`). |
| `FREIGHT_TRACKING_ALLOWLIST` | `` | Comma-separated extra hosts a real carrier tracking endpoint may target (SSRF allowlist). |
| `OCR_ENGINE` | `mock` | Default invoice OCR-capture connector (real engines added in `apps/invoicing/ocr.py`). |
| `INVOICE_QTY_TOLERANCE_PCT` | `2` | Quantity tolerance (%) before a three-way-match line is flagged a variance (per-PO override available). |
| `INVOICE_PRICE_TOLERANCE_PCT` | `2` | Unit-price tolerance (%) before a three-way-match line is flagged a variance (per-PO override available). |
| `OCR_MIN_CONFIDENCE` | `70` | OCR captures below this confidence (%) are flagged "needs manual review" in the UI. |
| `INVOICE_DISPUTE_SLA_DAYS` | `5` | Days a dispute may stay open before `scan_invoice_alerts` raises a one-time escalation alert. |
| `INVOICE_EMAIL_ALERTS` | `False` | Opt-in: also email the invoice owner on overdue / closing-discount / dispute-SLA alerts (needs a real `EMAIL_BACKEND`). |
| `BUDGET_ENFORCEMENT` | `warn` | Budget-availability check on requisition submit: `warn` (flag + alert the owner, but allow) or `block` (raise a validation error and stop the submission). |
| `BUDGET_VARIANCE_TOLERANCE_PCT` | `10` | Utilization (%) below 100 at which the variance report flags a cost centre "near limit". |
| `BUDGET_WARN_UTILIZATION_PCT` | `90` | Utilization (%) at which `scan_budget_alerts` raises a one-time over-budget / high-burn alert. |
| `SCREENING_PROVIDER` | `mock` | Default restricted-party screening connector (real OFAC/SAM providers wire in via `apps/compliance/screening.py`). |
| `SCREENING_ALLOWLIST` | `` | Comma-separated extra hosts a real screening endpoint may target (SSRF allowlist; else HTTPS + public-host only). |
| `SCREENING_MATCH_THRESHOLD` | `85` | Fuzzy-match percent at/above which a screening records a hit. |
| `CREDIT_PROVIDER` | `mock` | Default supplier credit-score connector (real providers wire in via `apps/compliance/credit.py`). |
| `CREDIT_ALLOWLIST` | `` | Comma-separated extra hosts a real credit endpoint may target (SSRF allowlist). |
| `CREDIT_SCORE_DROP_ALERT` | `10` | Credit-score drop (points) that raises a financial-risk alert on refresh. |
| `FRAUD_SPLIT_PO_WINDOW_DAYS` | `14` | Window (days) the split-PO fraud detector groups a vendor+buyer's POs over. |
| `FRAUD_ROUND_AMOUNT_FLOOR` | `5000` | Minimum PO/invoice total the round-amount fraud detector considers. |
| `POLICY_ACK_REMINDER_DAYS` | `14` | Paces the cron policy-acknowledgment reminder digest. |
| `INVENTORY_AUTO_REORDER` | `True` | Whether `run_inventory_alerts` auto-generates draft requisitions for items at/below their reorder point. |
| `INVENTORY_EXPIRY_ALERT_DAYS` | `30` | Look-ahead window (days) within which a stock lot's expiry raises a one-time near-expiry alert. |
| `INVENTORY_DEFAULT_WAREHOUSE_CODE` | `WH-MAIN` | Warehouse auto-created to land received stock when a goods receipt has no mapped bin. |
| `DMS_EXTRACTION_ENGINE` | `mock` | Pluggable text-extraction engine for full-text search (`mock` = no deps; `local` parses PDFs via pypdf; hosted engines wire in via `apps/dms/extraction.py`). |
| `DMS_EXTRACTION_ALLOWLIST` | `` | Comma-separated SSRF allowlist of extra hosts a real (remote) extraction backend may target. |
| `DMS_MAX_INDEX_CHARS` | `200000` | Cap on stored extracted text (chars) so a large PDF cannot bloat the row / search index. |
| `DMS_UPLOAD_MAX_MB` | `10` | Maximum uploaded document file size (MB). |
| `TIME_ZONE` | `UTC` | |
| `LANGUAGE_CODE` | `en-us` | |

---

## Management Commands

| Command | What it does |
|---------|--------------|
| `python manage.py seed_data` | Orchestrator: runs `seed_plans` → `seed_tenants` → `seed_users` → `seed_portal` → `seed_requisitions` → `seed_approvals` → `seed_vendors` → `seed_sourcing` → `seed_rfx` → `seed_auctions` → `seed_contracts` → `seed_catalog` → `seed_purchase_orders` → `seed_fulfillment` → `seed_goods_receipt` → `seed_invoicing` → `seed_spend_analytics` → `seed_budget` → `seed_supplier_performance` → `seed_compliance` → `seed_inventory` → `seed_documents`. |
| `python manage.py seed_plans` | Creates 4 canonical plans (Free / Starter / Professional / Enterprise). |
| `python manage.py seed_tenants` | Creates 3 demo tenants with subscriptions, invoices, branding, audit, metrics. |
| `python manage.py seed_users` | Creates a tenant_admin + 4 staff users per tenant. |
| `python manage.py seed_portal` | Creates dashboard widgets, notifications, quick requisitions and saved reports for every tenant user. |
| `python manage.py seed_requisitions` | Creates account codes, requisition templates and requisitions across every status for each tenant. |
| `python manage.py seed_approvals` | Creates approval rules, steps and a delegation, and routes submitted requisitions through the engine. |
| `python manage.py seed_vendors` | Creates vendor categories, segments, 8 vendors across every status, contacts/docs/banks, risk assessments, 3 onboarding applications and blacklist history. |
| `python manage.py seed_sourcing` | Creates 3 sourcing events per tenant (draft / open with 2 bids / awarded with full evaluation matrix + finalised award + savings). |
| `python manage.py seed_rfx` | Creates 2 RFx templates and 3 events per tenant (draft RFI / open RFP with responses / completed RFQ with full panel evaluation + shortlist). |
| `python manage.py seed_auctions` | Creates 3 e-auctions per tenant (draft / scheduled with invitees / awarded with a full live bid ledger, anti-snipe extension + recorded savings). |
| `python manage.py seed_contracts` | Creates a clause library, 2 contract templates and 7 contracts per tenant across every status (draft-from-template / pending signature / active with obligations / expiring-soon / auto-renewing / amended / terminated). |
| `python manage.py seed_catalog` | Creates 4 catalog categories, items across every status (draft with tiers / pending / approved-with-tiers / rejected / retired), a pending price-change request, a cXML punch-out supplier config and a parsed supplier upload per tenant. |
| `python manage.py seed_purchase_orders` | Creates 8 purchase orders per tenant across every status (draft / issued / acknowledged / partially received / received / closed / cancelled / with an applied change order) plus a 9th generated from the approved requisition. |
| `python manage.py seed_fulfillment` | Creates 6 shipments per tenant against the dispatched POs (draft ASN / advised + carrier-synced in-transit / delivered + received with receipts posted to the PO / a split-delivery PO with 2 shipments + a backorder / an overdue shipment) — driven through the real services. |
| `python manage.py seed_goods_receipt` | Creates 5 goods receipts per tenant from the open POs (draft / awaiting inspection / posted-with-tags / mixed accept-reject + Return-to-Vendor / QA-fail) — driven through the real receive→inspect→post services. |
| `python manage.py seed_invoicing` | Creates 3 payment terms + 7 supplier (AP) invoices per tenant across every status (draft / paid-via-gateway / approved+scheduled-voucher with a live early-payment discount / submitted-with-match-exceptions+overdue / disputed-with-thread / rejected / cancelled) — driven through the real capture→match→approve→pay services. |
| `python manage.py seed_spend_analytics` | Materializes the `SpendRecord` fact table per tenant from the seeded approved/paid invoices (actual) + non-cancelled POs (committed) via the real `sync_spend_facts`, and creates 3 demo saved reports (category doughnut / monthly-trend line / maverick-by-supplier bar). |
| `python manage.py seed_budget` | Creates an `FY2026` period + an active operating budget per tenant with allocations across the seeded cost centres, then runs a couple of real availability checks against the seeded requisitions (idempotent; `--flush` to re-seed). |
| `python manage.py seed_supplier_performance` | Provisions the default KPI set + final scorecards for 3 vendors across 3 rolling quarters (so trending renders a line), seeds submitted 360° feedback inside each window, and opens an in-progress improvement plan for the weakest vendor — driven through the real services (idempotent; `--flush` to re-seed). |
| `python manage.py seed_compliance` | Seeds restricted-party lists (incl. a deliberate match on a real vendor name), runs screenings, builds financial-risk profiles + snapshots, creates the 5 default fraud rules + a deliberate shared-bank-account conflict, runs one fraud scan, and publishes 2 acknowledged policies per tenant — driven through the real services (idempotent; `--flush` to re-seed). |
| `python manage.py seed_inventory` | Creates a default warehouse + bins, stock items for the live catalog items (with reorder params), folds posted goods receipts into on-hand stock + opening balances, posts a consumption + a return goods issue, runs a posted (with variance) + an in-progress cycle count, and forces one item below reorder so an auto-requisition is raised — driven through the real services (idempotent; `--flush` to re-seed). |
| `python manage.py seed_documents` | Seeds 5 documents (a published policy / spec / warranty / SOP + a draft) and 2 best-practice templates per tenant, each from a small text fixture so the mock extractor indexes real searchable text out of the box — driven through the real create → index → publish services (idempotent; `--flush` to re-seed). |
| `python manage.py reindex_documents` | Re-extracts text from every document version still pending/failed across all tenants (`--tenant <slug>` for one) — cron-friendly; idempotent (already-indexed versions are skipped). Useful after switching `DMS_EXTRACTION_ENGINE` to `local`. |
| `python manage.py run_escalations` | Escalates overdue approval tasks (cron-friendly; the inbox also sweeps lazily). |
| `python manage.py run_auction_clock` | Advances scheduled→live and live→closed auctions by the wall clock across all tenants (cron-friendly; the live console also sweeps lazily). |
| `python manage.py run_contract_alerts` | Raises renewal/expiration alerts, auto-renews or expires past-due contracts and flags overdue obligations across all tenants (cron-friendly; the renewals board also sweeps lazily). |
| `python manage.py run_po_alerts` | Raises a one-time reminder for issued POs left unacknowledged and a one-time alert for overdue PO deliveries across all tenants (cron-friendly; the tracking board also sweeps lazily). |
| `python manage.py run_fulfillment_alerts` | Raises a one-time alert for in-flight shipments past their estimated delivery date and for overdue backorders, and auto-cancels backorders whose PO has finished, across all tenants (cron-friendly; the tracking board also sweeps lazily). |
| `python manage.py run_goods_receipt_alerts` | Raises a one-time alert for goods receipts left awaiting inspection and for open returns-to-vendor across all tenants (cron-friendly; the analytics dashboard also sweeps lazily). |
| `python manage.py run_invoice_alerts` | Raises a one-time alert for approved/submitted invoices past their due date and unpaid, and for invoices whose early-payment discount window is closing, across all tenants (cron-friendly; the analytics dashboard also sweeps lazily). |
| `python manage.py run_spend_sync` | Resyncs the `SpendRecord` fact table from invoices + POs across all tenants (`--tenant <slug>` for one) — cron-friendly; the dashboard also resyncs lazily when stale. |
| `python manage.py run_budget_alerts` | Raises a one-time over-budget / high-utilization alert (audit + owner notification) for each active budget across all tenants (`--tenant <slug>` for one) — cron-friendly; idempotent via `Budget.over_budget_alerted_at`. |
| `python manage.py run_scorecards` | Generates a final scorecard for every active vendor over a period (defaults to the trailing calendar quarter; `--period-start/-end`, `--label`, `--tenant <slug>`) and, with `--pip-sweep`, raises a one-time alert per overdue improvement plan across all tenants — cron-friendly; idempotent via `ImprovementPlan.alerted_at`. |
| `python manage.py scan_compliance_alerts` | Refreshes due financial-risk profiles (alerting on a score drop / band worsening), runs the fraud-rule scan (deduplicated by alert signature), and sends a policy-acknowledgment reminder digest to each policy owner with outstanding sign-offs, across all tenants (`--tenant <slug>` for one) — cron-friendly. |
| `python manage.py run_inventory_alerts` | Folds newly-posted goods receipts into stock, runs reorder-point automation (raising a draft requisition per item at/below its reorder point) and raises a one-time near-expiry alert for stock lots inside the window, across all tenants (`--tenant <slug>` for one) — cron-friendly; the dashboard also syncs lazily. |

All seed commands accept `--flush` to wipe-and-replace. Without `--flush` they are idempotent.

---

## Testing

Automated tests use **pytest + pytest-django** against an in-memory SQLite database
(see [`config/settings_test.py`](config/settings_test.py)).

```bash
pip install -r requirements-dev.txt
pytest                                   # run the whole suite
pytest apps/portal --cov=apps/portal      # one module, with coverage
```

| Item | Detail |
|------|--------|
| Config | [`pytest.ini`](pytest.ini) (`DJANGO_SETTINGS_MODULE = config.settings_test`) |
| Dev deps | [`requirements-dev.txt`](requirements-dev.txt) — `pytest`, `pytest-django`, `pytest-cov` |
| Suites | [tenants](apps/tenants/tests/), [portal](apps/portal/tests/), [requisitions](apps/requisitions/tests/), [approvals](apps/approvals/tests/), [rfx](apps/rfx/tests/), [auctions](apps/auctions/tests/), [contracts](apps/contracts/tests/), [catalog](apps/catalog/tests/), [purchase_orders](apps/purchase_orders/tests/), [goods_receipt](apps/goods_receipt/tests/), [invoicing](apps/invoicing/tests/), [spend_analytics](apps/spend_analytics/tests/), [budget](apps/budget/tests/), [supplier_performance](apps/supplier_performance/tests/), [compliance](apps/compliance/tests/), [inventory](apps/inventory/tests/), [dms](apps/dms/tests/) — **1378 tests** |
| Layout | each `tests/` package has `conftest.py` + `test_models` / `test_services` / `test_views` / `test_security` (high-80s–90s % line coverage per module) |

QA artefacts (SQA reports, manual test plans) live under [.claude/](.claude/) and are not part of the runtime.

---

## Seeded Demo Data

### Plans
- **Free** ($0/mo, no trial)
- **Starter** ($29/mo or $290/yr, 14-day trial)
- **Professional** ($99/mo or $990/yr, 14-day trial) — featured
- **Enterprise** ($299/mo or $2,990/yr, 30-day trial)

### Tenants & login credentials

All seeded users share the password **`Welcome@123`**.

| Tenant | Industry | Plan | Tenant-admin username |
|--------|----------|------|-----------------------|
| Acme Corp | Manufacturing | Professional (yearly) | `admin_acme` |
| Globex Industries | Retail | Starter (monthly) | `admin_globex` |
| Stark Industries | Defense | Enterprise (yearly, MFA on) | `admin_stark` |

Each tenant additionally has 4 staff users (Procurement Manager, Buyer, Approver, Requester)
with Faker-generated names, e.g. `john.doe.acme`.

### Audit + Health
Each tenant gets 25 audit-log entries and ~120 health metrics (active users, API calls,
storage MB, active sessions) spread across the last 30 days — enough to populate the
monitoring dashboard chart.

### Portal data
Every tenant user receives the 6-widget starter dashboard, 5 notifications (mixed
categories/priorities, 2 unread), 5 quick requisitions (draft / submitted / approved with
line items), and 3 saved reports — enough to populate every Module 2 page on first login.

### Requisition data
Each tenant gets 5 account codes, 2 shared requisition templates (with pre-defined lines),
and 6 requisitions — one in every status (draft, submitted, approved, rejected, cancelled,
converted) — each with line items and a status-event timeline.

### Approval data
Each tenant gets 2 approval rules (a single-step "Standard approval" and a two-step
"High-value approval (over $1,000)"), one active delegation, and an `ApprovalRequest` with
step tasks for every already-submitted requisition.

### Vendor data
Each tenant gets 5 vendor categories (Raw Materials, IT Services, Maintenance, Office
Supplies, Logistics), 4 segments (Strategic, Tactical, Preferred, Approved), 8 vendors
covering every status (3 active, 1 pending verification, 1 suspended, 1 blacklisted, 2
drafts plus an approved onboarding conversion = 9 total), contacts/documents/bank accounts
on each vendor, risk assessments on the active ones, and 3 onboarding applications
(submitted / under review / approved-and-converted).

### RFx data
Each tenant gets:
- **2 templates** — "Standard supplier RFI" (3 sections, 8 questions) and "IT services RFP" (4 sections, 11 questions, scored weights summing to 100).
- **3 events**:
  - **Draft RFI** — "Strategic supplier capability survey" (built from the RFI template, no invitees).
  - **Open RFP** — "ERP system selection 2026" (built from the RFP template, 3 invitees, 1 submitted response + 1 draft response).
  - **Completed RFQ** — "Office cleaning services quote" (4 scored questions, 3 submitted responses, full panel evaluation, ranked, top response shortlisted).

### Sourcing data
Each tenant gets 3 sourcing events:
- **Draft** — "Office stationery Q2" (RFQ, 3 items, 4 criteria, no invitees yet)
- **Open** — "Server hardware refresh" (RFP, 4 items, 4 criteria, 3 invitees, 1 draft bid + 1 submitted bid)
- **Awarded** — "Janitorial services Q1" (Tender, 2 items, 4 criteria, 3 submitted bids, full panel evaluation, lowest weighted-cost compliant winner, recorded savings)

Criteria template: Price 40 / Quality 25 / Delivery 20 / Compliance 15 (sums to 100).

### E-Auction data
Each tenant gets 3 reverse auctions:
- **Draft** — "Office laptops reverse auction Q3" (3 lots, no participants yet)
- **Scheduled** — "Bulk steel quarterly buy" (2 lots, 3 invitees, starts in +1 day)
- **Awarded** — "Inbound logistics reverse auction" (1 lot, 3 invitees, a full live bid
  ledger of declining bids driven through the real `place_bid` service — one anti-snipe
  extension fired, ranks computed, lowest valid bid awarded, savings recorded)

Auction defaults: `amount` decrement, 120 s anti-snipe window, blind `rank_and_leading`
visibility (vendors see their own rank + the leading price, never competitor identities).

### Contract data
Each tenant gets a **clause library** (6 standard clauses across payment / confidentiality /
liability / termination / IP / SLA), **2 contract templates** (Standard Service Agreement, Mutual
NDA) and **7 contracts** covering every status:
- **Draft** — "IT support services 2026" authored from the Service Agreement template.
- **Pending signature** — "Facilities management agreement" (1 internal + 1 supplier signatory, tokens issued).
- **Active** — "Cloud hosting master agreement" (fully signed, 4 obligations incl. a payment milestone + penalty).
- **Expiring-soon** — "Office cleaning contract" (ends in +20 days, inside the renewal-notice window).
- **Auto-renewing** — "Software subscription" (active, `auto_renew=True`, ends in +15 days).
- **Amended** — "Logistics framework agreement" (active, one applied amendment → revision 2).
- **Terminated** — "Catering services agreement".

### Catalog data
Each tenant gets **4 catalog categories** (Office Supplies, IT Equipment, MRO, Raw Materials)
and catalog items covering every status:
- **Draft** — "A4 Copier Paper" (internal, with two volume-break tiers).
- **Pending approval** — "Industrial Safety Helmet" (supplier-sourced).
- **Approved** — "Heavy-Duty Cable Ties" (supplier, two volume tiers, orderable) — plus a
  **pending price-change request** (annual uplift) awaiting approval.
- **Rejected** — "Unbranded Power Adapter" (rejected for a missing safety certificate).
- **Retired** — "Legacy Toner Cartridge".

Plus a **cXML punch-out supplier configuration** and a **parsed supplier upload** (a small CSV
with one intentionally-bad row → a *partially imported* upload demonstrating the row-level
error log).

### Purchase Order data
Each tenant gets **8 purchase orders** covering every status, driven through the real PO services:
- **Draft** — "Office supplies restock" (supplier assigned, 2 lines, not yet issued).
- **Issued** — "Server rack hardware" (dispatched, awaiting acknowledgment).
- **Acknowledged** — "Marketing print run" (supplier accepted).
- **Partially received** — "Quarterly stationery" (one of two lines partly received).
- **Received** — "Laptop batch Q2" (fully received, with tax — closeable).
- **Closed** — "Annual maintenance kit" (received then closed out).
- **Cancelled** — "Trial sample order" (issued then cancelled).
- **With an applied change order** — "Bulk steel order" (acknowledged, then a quantity change
  order applied → revision 2).

Plus a **9th PO generated from the approved requisition** (`REQ-*-00003`) via the
`Create Purchase Order` flow, which marks that requisition `converted`. (A full
`seed_data --flush` reseeds requisitions first, so the approved requisition is always available.)

### Fulfillment data
Each tenant gets **6 shipments** built from the dispatched POs, driven through the real fulfillment
services:
- **Draft ASN** — created with lines, not yet advised.
- **Advised + in transit** — ASN sent and carrier-synced via the mock carrier (tracking ledger populated).
- **Delivered + received** — synced to delivered, then confirmed — posting the received quantities back into the PO.
- **Split delivery** — one PO fulfilled across two shipments (one received, one in transit) **plus a backorder** for the remainder.
- **Overdue** — advised with a past estimated-delivery date, so the overdue-delivery alert fires.

### Goods Receipt data
Each tenant gets **5 goods receipts** built from the open POs, driven through the real
receive → inspect → post services:
- **Draft** — received lines entered, not yet marked received.
- **Awaiting inspection** — marked received (back-dated, so the overdue-inspection alert fires).
- **Posted** — fully accepted, posted to the PO line `received_quantity`, with barcode/QR
  **ReceiptTags** generated for the accepted inventory.
- **Mixed accept/reject + RTV** — half accepted (posted) and half rejected with a `damaged`
  discrepancy, spawning a **Return-to-Vendor** that is authorised and shipped back (visible in
  the supplier's vendor portal under *Returns to Vendor*).
- **QA-fail** — inspected with a failed QA checklist criterion, left un-posted pending a decision.

### Invoice & Voucher data
Each tenant gets **3 payment terms** (Net 30, Net 60, 2/10 Net 30) and **7 supplier (AP)
invoices** built from the dispatched / received POs, driven through the real
capture → three-way match → approve → pay services:
- **Draft** — billed against a received PO, not yet submitted.
- **Paid** — matched, approved, vouchered and **paid through the mock payment gateway**.
- **Approved + scheduled voucher** — matched, approved, with a scheduled `PaymentVoucher` and a
  **live early-payment discount opportunity** (2/10 Net 30, discount captured).
- **Submitted with match exceptions + overdue** — billed above the PO price and back-dated, so it
  shows a price variance *and* fires the overdue-payment alert.
- **Disputed** — submitted, queried, with a buyer↔supplier dispute thread (incl. a supplier reply).
- **Rejected** — submitted then rejected.
- **Cancelled** — entered then cancelled.

### Spend Analytics data
Each tenant's **`SpendRecord` fact table** is materialized from the seeded source documents via the
real `sync_spend_facts`: one row per approved/paid supplier-invoice line (**actual** spend) and one
per non-cancelled PO line (**committed** spend), with the maverick flags computed at sync
(off-preferred-supplier / off-contract / non-PO). Each tenant also gets **3 demo saved reports** —
"Spend by category (actual)" (doughnut), "Monthly spend trend (actual)" (line), and "Maverick spend
by supplier" (bar). Actual and committed are reported separately and never summed.

### Budget & Cost data
Each tenant gets an active **`FY2026`** budget period and an active **"Operating budget FY2026"**
(`BUD-<SLUG>-NNNNN`) with allocations across the seeded cost centres (`6100-OFF`, `6200-IT`,
`6300-SVC`, `6400-TRV`, `6500-MNT`). Consumption is computed on read from the seeded POs (committed),
invoices (actual) and open requisitions (reserved), and a couple of real **availability checks** are
run against the seeded requisitions so the check log + requisition banner are populated.

### Supplier Performance data
Each tenant gets the **default KPI set** (On-Time Delivery, Defect Rate, Responsiveness, Price
Variance, 360° Feedback — weights summing to 100) and **final scorecards** (`SPC-<SLUG>-NNNNN`) for
its top three active vendors across **three rolling quarters**, so the trending line has multiple
points and the latest card becomes each vendor's current score (denormalised onto the Vendor row).
Submitted **360° feedback** is dated inside each window (with one outstanding request for the inbox),
and an in-progress **improvement plan** (`PIP-<SLUG>-NNNNN`) with two corrective actions is opened for
the weakest vendor — all driven through the real services.

### Risk & Compliance data
Each tenant with vendors gets a small **restricted-party list** (OFAC/SAM/EU entries) including one
entry that deliberately matches a real vendor's name, so a seeded **screening** returns a confirmed
hit (a second vendor screens clear). The **5 default fraud rules** are installed and a deliberate
**shared bank account** is placed on two vendors, then one **fraud scan** runs — producing live
`FraudAlert`s (bank conflict plus any round-amount / duplicate-invoice / split-PO patterns in the
seeded POs and invoices). **Financial-risk profiles** (credit score + exposure) are built for the
active vendors with a history snapshot, and **two published policies** (Code of Conduct, Sanctions
& Screening) are created with one acknowledgment each. The reused `tenants.AuditLog` is hash-chained,
so `/compliance/audit/` → *Verify integrity* reports the chain intact.

### Inventory data
Each tenant with catalog items gets a default **`WH-MAIN` warehouse** with four bin locations
(`A-01-01` … `B-02-02`) and a **`StockItem`** profile per live catalog item (reorder parameters set on
the first few). The seeder folds any posted goods receipts into on-hand stock via the real
`sync_stock_from_receipts`, then lays down **opening balances** (one lot near expiry, to populate the
near-expiry alert) so every demo always has stock to work with. It posts a **consumption goods issue**
and a **return-to-stock**, leaves a **draft goods issue**, runs a **posted cycle count with a −3
variance** (writing an adjustment movement) plus an **in-progress count**, and forces one item below
its reorder point then runs the automation so a **draft auto-reorder requisition** exists — all driven
through the real services and visible on the `StockMovement` ledger.

### Documents & Knowledge data
Each tenant gets **5 documents** covering every status — a published **Procurement Policy Manual**,
**Laptop Specification**, **Warranty Terms** and **Supplier Onboarding SOP**, plus a **draft Vendor
Code of Conduct** awaiting publication — and **2 best-practice templates** (an IT-services RFP
skeleton and a bid-evaluation guide). Every document is seeded from a small text fixture, so the
default mock extraction engine fills each version's `extracted_text` and the full-text search at
`/dms/search/` works immediately (e.g. searching “ISO 9001” or “warranty” returns hits). Each
document is driven through the real create → upload → index → publish services, so the version
history, `current_version` pointer and append-only timeline are all populated.

---

## Dashboard Features

The layout is controlled by `data-*` attributes on `<html>`, set by the context processor from
`UserProfile` and overridden client-side via `localStorage` (key: `navpms.ui`).

Open the **theme customizer** via the cog icon in the topbar to toggle:

| Setting | Values |
|---------|--------|
| **Color Scheme** | Light / Dark |
| **Layout** | Vertical / Horizontal / Detached |
| **Layout Width** | Fluid / Boxed |
| **Layout Position** | Fixed / Scrollable |
| **Topbar Color** | Light / Dark |
| **Sidebar Color** | Light / Dark / Brand (blue) |
| **Sidebar Size** | Default / Compact / Small Icon / Icon Hover |
| **Direction** | LTR / RTL |

Other UI touches: site **preloader**, sidebar overlay on mobile, soft badges, sticky topbar.

---

## Module 1 — Tenant & Subscription Management

All five sub-modules from the PMS spec:

| Sub-module | Implementation |
|-----------|----------------|
| **Tenant Onboarding** | 3-step wizard at `/tenants/onboarding/` (welcome → company → plan → complete). Provisions Tenant + trial Subscription + default Branding + default Security policy. |
| **Subscription & Billing** | `Plan` (CRUD), `Subscription` (assign/cancel), `Invoice` (auto-numbered, line items JSON), `Transaction` (gateway-backed). Mock gateway by default. |
| **Tenant Isolation & Security** | `SecuritySettings`: password policy (min length, uppercase/number/special), MFA toggle, session timeout, IP allowlist (CIDR), allowed login domains, encryption key reference. Multi-tenancy enforced at ORM level via [`apps/core/models.py`](apps/core/models.py) (`TenantAwareModel` + `TenantManager` thread-local). |
| **Custom Branding** | `BrandingSettings` (logo, logo_dark, favicon, primary/secondary color pickers, login background, email from-name + signature, support URL/email). |
| **Tenant Health Monitoring** | `HealthMetric` (user_count, storage_mb, api_calls, active_sessions, error_rate) + dedicated dashboard with 4 Chart.js line charts and a recent-activity feed pulled from `AuditLog`. |

The `AuditLog` model is append-only (admin has add/delete disabled) and indexed by
`(tenant, created_at)` and `(tenant, action)` for fast filtering.

---

## Module 2 — User Dashboard & Portal

A per-user workspace ([`apps/portal/`](apps/portal/)) — every authenticated tenant member
gets their own portal, scoped by both `tenant` and `user`. All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Personalized Overview** | `DashboardWidget` — per-user, customizable widget rows (type, title, size, position, visibility). The portal dashboard at `/portal/` renders enabled widgets; first visit auto-provisions a 6-widget starter set. Widgets are managed with full CRUD at `/portal/widgets/`. |
| **Task & Alert Center** | `Notification` — categorized (deadline / approval / delivery / system / info), prioritized (low → urgent), read/unread with mark-read, mark-all-read, and full CRUD. |
| **Quick Requisition Entry** | `QuickRequisition` + `QuickRequisitionItem` — auto-numbered `QR-<SLUG>-NNNNN`, fast-track form for low-value/catalog purchases, inline line-item CRUD, `draft → submitted → approved/rejected` workflow. Submitting raises an audit entry and an approval notification. |
| **Recent Activity Feed** | Reuses [`apps/tenants/`](apps/tenants/) `AuditLog`, filtered to `user=request.user`. Portal actions are written via `record_audit()` — no duplicate audit infrastructure. |
| **Self-Service Reporting** | `SavedReport` — reusable report definitions (spend by category / by month, requisitions by status, my activity, notifications summary). The run view computes a Chart.js doughnut/bar chart plus a breakdown table over a date window. |

Drafts are the only editable/deletable requisition state; submitted+ requisitions are locked.
Every list page has search + filters; every model has full CRUD per the project conventions.

---

## Module 3 — Requisition Management

A tenant-shared procurement workflow ([`apps/requisitions/`](apps/requisitions/)) — formal
purchase requests moving from draft through approval to PO conversion. All five PMS
sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Requisition Creation** | `Requisition` + `RequisitionLine` — auto-numbered `REQ-<SLUG>-NNNNN`, item descriptions, quantities, required dates, per-line `AccountCode`. Inline line-item CRUD on the detail page. |
| **Requisition Tracking** | A `status` field (`draft → submitted → approved/rejected → converted`, plus `cancelled`) with an immutable `RequisitionStatusEvent` timeline, and a dedicated tracking board at `/requisitions/tracking/` that groups every requisition into status columns with counts and totals. |
| **Duplicate Requisition Check** | `find_potential_duplicates()` scans the last 30 days for same-requester requests with an equal title or a shared line description. Create / edit / submit set `possible_duplicate` + `duplicate_of`; the detail page shows a warning banner with links. |
| **Requisition Templates** | `RequisitionTemplate` + `RequisitionTemplateLine` — reusable pre-defined forms (private or shared), with a one-click "Create requisition from template" that copies the lines into a fresh draft. |
| **Cancellation/Amendment** | Cancel from any open status; Amend pulls a submitted/approved requisition back to `draft`, bumps the `revision` counter, and records a status event. |

A dedicated **`AccountCode`** master (tenant-scoped, full CRUD, unique `code` per tenant) is
charged against requisition and template lines. Approve / reject / convert-to-PO are tenant
-admin actions; the requester (or an admin) owns draft editing, submit, amend and cancel.
Every workflow transition also writes an `AuditLog` entry, so Module 2's Activity Feed shows
requisition activity.

> Once Module 4 approval rules exist, submitting a requisition routes it through the
> workflow engine instead of the simple admin approve/reject — see below.

---

## Module 4 — Approval Workflow Engine

A pluggable, multi-step approval engine ([`apps/approvals/`](apps/approvals/)) that drives
requisition sign-off. All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Dynamic Routing Rules** | `ApprovalRule` matches a requisition on amount range / department / category (lowest `priority` wins); `ApprovalStep` defines the ordered approver chain. |
| **Delegation of Authority** | `ApprovalDelegation` — date-bounded reassignment of one user's approval authority to a delegate; the engine resolves delegations when routing each task. |
| **Approval History & Audit Trail** | `ApprovalAction` — an append-only log of every submit / approve / reject / delegate / escalate / comment, shown on the request detail and a global history page. |
| **Escalation Management** | Each step has an SLA (`sla_hours`) and an `escalate_to` user. Overdue tasks escalate via the `run_escalations` command **and** a lazy sweep when the approver inbox is opened. |
| **Mobile Approval Interface** | A responsive, card-based "My Approvals" inbox and a mobile-friendly task review/decide page with one-tap approve/reject. |

**How it integrates with Module 3:** submitting a requisition calls the engine, which finds
the first matching `ApprovalRule` and creates an `ApprovalRequest` with one `ApprovalTask`
per step (resolving delegations). Approving a task advances the chain; the final approval
calls Module 3's `decide_requisition()` to mark the requisition approved (a rejection ends
it immediately). **If no rule matches, the requisition falls back** to the simple admin
approve/reject. Amending or cancelling a requisition withdraws any in-flight approval.

---

## Module 5 — Vendor Management

The supplier master and supplier self-service portal ([`apps/vendors/`](apps/vendors/)) — a
full vendor lifecycle from public onboarding application to active vendor, risk-rated and
classified, with a separate portal shell for the suppliers themselves. All five PMS
sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Vendor Onboarding** | Public per-tenant URL `/vendors/onboarding/apply/<tenant-slug>/` (no login). A `VendorOnboardingApplication` is created; tenant admin reviews from `/vendors/onboarding/`, then **approves → converts to a draft `Vendor`** or rejects with a reason. |
| **Vendor Portal** | Separate shell mounted at `/vendor-portal/`. A `User.vendor` OneToOne FK turns a user into a supplier-portal user; login redirects them to the portal, and **`VendorPortalSandboxMiddleware`** prevents access to any other namespace. Self-service: dashboard, profile edit, contact CRUD, document upload, with PO/invoice placeholders for Modules 11/14. |
| **Vendor Classification & Segmentation** | `VendorCategory` (tree-capable, parent self-FK) and `VendorSegment` (Strategic / Tactical / Preferred / Approved with badge color). Full CRUD; both surface as filters on the vendor list. |
| **Vendor Risk Profiling** | `VendorRiskAssessment` — four 0–100 pillars (financial / operational / compliance / quality), unweighted average → 0–25 Low, 26–50 Medium, 51–75 High, 76–100 Critical. Latest assessment is marked `is_current=True` and its level/score are **denormalised onto `Vendor`** for fast filtering. |
| **Vendor Blacklisting/Suspension** | `VendorBlacklistEvent` (append-only) records suspend / blacklist / reinstate with reason, effective date and optional end date. `Vendor.status` flips accordingly. The blacklist history page at `/vendors/blacklist/history/` is the audit trail. |

The vendor record carries [`apps/vendors/models.py`](apps/vendors/models.py) — `Vendor`,
`VendorContact`, `VendorDocument` (with `expires_at`), `VendorBankAccount`,
`VendorOnboardingApplication`, `VendorRiskAssessment`, `VendorBlacklistEvent`,
`VendorCategory`, `VendorSegment`. Auto-numbered as `VND-<SLUG>-NNNNN`. Document uploads
go to `MEDIA_ROOT/vendor_docs/`. The "Verify & activate" action stamps the vendor as
verified and moves draft/pending records to `active`.

**Vendor portal invite flow:** tenant admin clicks **Invite to portal** on a vendor's
detail page → [`apps/vendors/services.py`](apps/vendors/services.py) creates a `User` with
the `vendor_portal` role and `vendor` FK set, returns a one-time password (shown back to
the inviter — wire to an email backend in production). The new portal user logs in via
the regular `/accounts/login/` and is auto-redirected to `/vendor-portal/`. The middleware
keeps them sandboxed; `Revoke portal access` disables the user.

---

## Module 6 — Sourcing & Tendering

The tendering and bid-management surface ([`apps/sourcing/`](apps/sourcing/)) — buyers
issue RFQ / RFP / RFT / Tender events, invite vendors, receive sealed bids, score them
against weighted criteria, and award the contract. Vendors bid through the existing
vendor portal — no second shell. All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Event Creation & Scheduling** | `SourcingEvent` (`SRC-<SLUG>-NNNNN`, type RFQ/RFP/RFT/Tender) + `SourcingEventItem` lines (qty, UoM, est. unit price, optional `AccountCode`). Status workflow `draft → scheduled → open → closed → under_evaluation → awarded` plus `cancelled`. Optional FK to source `Requisition` so an approved REQ can spawn an event with pre-filled lines — the "Create Sourcing Event" button on the requisition detail page does exactly this. |
| **Bid Submission Portal** | `SourcingEventInvitee` (one row per invited vendor, status `invited → viewed → submitted / declined / withdrawn`). Vendors bid from `/vendor-portal/sourcing/` — a draft `Bid` is created with one `BidLine` per `SourcingEventItem`, pre-filled with the buyer's quantities, plus optional `BidDocument` uploads. **Sealed bids**: bid totals/lines/documents are hidden from buyers (and other vendors) until the event closes. Vendors can `withdraw` while the event is open. |
| **Bid Evaluation Matrix** | `SourcingCriterion` (weighted criteria per event, weights sum to 100 — validated at publish time). `BidEvaluation` is one score per `(bid, criterion, evaluator)` — supports panel scoring (multi-evaluator average per criterion). The service computes `overall_score = Σ(weight × avg_score / max_score)` and persists it on `Bid.overall_score` + rank. A side-by-side bid comparison matrix lives at `/sourcing/events/<pk>/bids/compare/`. |
| **Award Recommendation** | `recommend_award(event, vendor, amount, user, justification)` creates a `SourcingAward` (status `recommended`). `finalize_award(event, user)` promotes the recommendation to `approved`, flips the winning `Bid.status` → `awarded` and others → `rejected`, denormalises the winning vendor and amount onto the event, and computes savings. Direct admin action — Module 4 routing is not gated in this build. Set `allow_partial_award=True` to award by line. |
| **Sourcing Analytics** | Per-event report (estimated vs awarded, savings $/%, invitees / submitted, response rate, cycle time) plus a tenant-wide dashboard at `/sourcing/analytics/` (counts by status, total estimated/awarded/savings, response rate, top vendors by wins). |

**Permission gate:** event create / edit / publish / close / award is restricted to roles
`tenant_admin`, `procurement_manager`, `buyer` (plus Django superuser). Evaluators include
those plus `approver` — any of them can score a bid. Helpers
[`can_manage_sourcing`](apps/sourcing/services.py) and [`can_evaluate`](apps/sourcing/services.py)
encapsulate the check.

**Sealed-bid enforcement:** the [`bid_visible_to(user, bid)`](apps/sourcing/services.py)
gate returns True only when (a) the user is the vendor portal user who owns the bid,
or (b) the event status is in `{closed, under_evaluation, awarded, cancelled}`. The
[`bid_detail`](apps/sourcing/views.py) and [`bid_list`](apps/sourcing/views.py) views
render a sealed-bid placeholder when this check fails, instead of leaking the bid content.

**Integration with Module 5 (Vendors):** only `active` vendors can be invited (the form
queryset excludes `suspended`, `blacklisted`, `inactive`). Vendors with a portal user
see invitations directly; vendors without a portal user are still recorded as invitees
(the tenant admin can `Invite to portal` from the vendor detail to grant access).

---

## Module 7 — RFx Management

A questionnaire-driven RFI / RFP / RFQ surface ([apps/rfx/](apps/rfx/)) — buyers build
structured questionnaires, invite vendors to respond, score responses against weighted
criteria, and shortlist top performers. Distinct from Module 6 (which is **price-driven**),
Module 7 is **information-driven**: no priced line items, no award workflow, no savings
calculation — the lifecycle ends at "shortlist". All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Questionnaire Builder** | `RfxEvent` (`RFX-<SLUG>-NNNNN`, type RFI/RFP/RFQ) + `RfxSection` (named blocks) + `RfxQuestion` (9 types: `text`, `longtext`, `number`, `single_choice`, `multi_choice`, `yes_no`, `scale`, `date`, `file`). Per-question `weight` (0-100, scored weights must sum to 100 at publish), `max_score` for `scale`, `is_required`, `is_scored`, `choices` (JSON list). Up/down arrows reorder sections + questions in-place. |
| **Response Collection** | `RfxInvitee` (vendor → event, status `invited → viewed → responded / declined / withdrawn`). Vendor portal route `/vendor-portal/rfx/` lists invitations; vendors "start response" which creates a draft `RfxResponse` with one blank `RfxAnswer` per question. Per-answer file upload (`value_file`, 5 MB cap) supported on `file` questions. **Sealed responses**: buyer cannot see contents until the event closes. |
| **Side-by-Side Comparison** | `/rfx/events/<pk>/responses/compare/` — table with vendors as columns, questions as rows. Sealed gate enforced before render. Scored cells show per-evaluator-averaged scores; free-text cells render the raw answer. |
| **Scoring & Weighting** | `RfxEvaluation` is one score per `(response, question, evaluator)` — supports panel scoring (multi-evaluator average per question). Service `compute_overall_score(response) = Σ(question.weight × avg_evaluator_score / question.max_score)` for scored questions only. Overall scores persisted on `RfxResponse.overall_score`; `rank` (1 = highest) computed at `complete_event` time. |
| **RFx Template Library** | `RfxTemplate` (tenant, title, rfx_type, `is_shared`, `archived`) with `RfxTemplateSection` + `RfxTemplateQuestion` mirroring the event schema. `create_event_from_template(template, user)` clones the structure into a fresh draft event. `save_event_as_template(event, user)` snapshots an event's questionnaire into a new template. Library at `/rfx/templates/`. |

**Status workflow:** `draft → published → open → closed → under_evaluation → completed`
plus `cancelled`. Publish validation requires ≥1 section, ≥1 question, ≥1 invitee, a
`close_at` date, and scored question weights summing to 100. Recording the first evaluation
auto-advances `closed → under_evaluation`. `complete_event` finalises ranks.

**Sealed-response gate:** [`response_visible_to(user, response)`](apps/rfx/services.py)
returns True iff (a) the user is the vendor portal user who owns the response, or (b)
the user has manage/evaluate role AND `event.status ∈ {closed, under_evaluation, completed, cancelled}`.
The [`response_detail`](apps/rfx/views.py) and [`response_list`](apps/rfx/views.py) views
render a sealed banner instead of leaking content when this check fails.

**Permission gate:** event create / edit / publish / close / complete / shortlist /
reject is restricted to roles `tenant_admin`, `procurement_manager`, `buyer` (plus
Django superuser). Evaluators include those plus `approver` — any of them can score a
response. Helpers [`can_manage_rfx`](apps/rfx/services.py) and
[`can_evaluate`](apps/rfx/services.py) encapsulate the check.

**Integration with Module 5 (Vendors):** only `active` vendors can be invited; the form
queryset excludes `suspended`, `blacklisted`, `inactive`. Vendors with a portal user see
invitations in their `/vendor-portal/rfx/` inbox.

**Why not Module 6?** Module 6 (Sourcing) handles priced bids on line items — win on
lowest weighted cost. Module 7 (RFx) handles questionnaire responses — win on highest
weighted score. They share the same actors (buyer/vendor) and portal shells but the
data model differs fundamentally. The natural hand-off (RFx → Sourcing using shortlisted
vendors as invitees) is a planned follow-up; for now they're parallel surfaces.

---

## Module 8 — E-Auction Management

A live, time-bound **reverse-auction** surface ([apps/auctions/](apps/auctions/)) — buyers
configure a reverse auction, invite vendors, and watch a real-time leaderboard while
suppliers submit successively lower bids from the vendor portal. Distinct from Module 6
(sealed, one bid per vendor) and Module 7 (questionnaire scoring), Module 8 is **price-and-time
driven**: many bids per vendor, won on the lowest valid price, with a live console instead of
a back-office evaluation. All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Auction Setup & Configuration** | `Auction` (`AUC-<SLUG>-NNNNN`, type reverse/forward) holds the reverse-auction parameters: `starting_price` (ceiling), hidden `reserve_price` (floor), `decrement_type` (amount/percent) + `decrement_value`, `start_at`/`end_at`, `rank_visibility`, and the anti-snipe knobs. `AuctionLot` rows describe the basket. Full CRUD + a publish validation (≥1 lot, ≥1 participant, start<end, price>0, decrement>0, reserve≤starting). |
| **Live Bidding Interface** | Vendors bid from `/vendor-portal/auctions/<id>/bidding/` — a live screen with a client-side countdown, the current leading price, their own rank, and the next valid maximum. Bids POST to a JSON endpoint; the screen **AJAX-polls** a state endpoint every ~3 s (vanilla [`static/js/auction.js`](static/js/auction.js), no websockets). `place_bid()` validates the lowering + decrement + ceiling rules atomically under `select_for_update`. |
| **Bid Extension & Rule Enforcement** | Anti-snipe is enforced **server-side** in `place_bid()`: a valid bid landing within `anti_snipe_seconds` of `end_at` (while `extension_count < max_extensions`) pushes `end_at` out by `anti_snipe_extension_seconds`. The decrement rule (beat the current best by ≥ the configured amount/percent) and ceiling rule (≤ `starting_price`) are enforced in the same transaction, each with a clear error message. |
| **Auction Monitoring Console** | Buyers watch `/auctions/events/<id>/console/` — a live leaderboard (vendor, current bid, rank, last-bid time), participation counters, time remaining and extension count, all refreshed by polling a buyer JSON endpoint. The buyer sees full identities; vendors get a blind view (own rank + leading price) per `rank_visibility`. |
| **Post-Auction Results** | `/auctions/events/<id>/results/` shows the final ranking, savings (baseline vs winning bid, $ and %), the full append-only `AuctionBid` timeline, and the **award decision** (`finalize_auction`, lowest valid bid by default, buyer-overridable). Per-auction (price-drop curve) and tenant-wide analytics dashboards round it out. |

**Status workflow:** `draft → scheduled → live → closed → awarded` plus `cancelled`. Publish
moves draft → scheduled; the clock then flips scheduled → live (at `start_at`) and live →
closed (at `end_at`) **lazily** on console/poll/bid access — no celery — backed by the
cron-friendly `run_auction_clock` command. `finalize_auction` awards the lowest valid bid and
denormalises the winner onto the auction.

**Append-only bid ledger:** `AuctionBid` records one row per placement (amount, rank-at-placement,
`was_leading`, `triggered_extension`); the live standing (`current_bid_amount`, `current_rank`,
`bid_count`) is denormalised onto `AuctionParticipant` for fast leaderboard rendering. Admin
add/change/delete is disabled on the ledger (mirrors `AuditLog` / `SourcingAward`).

**Blind-bidding gate:** [`auction_state_for(user, auction)`](apps/auctions/services.py) returns
`'full'` for a buyer/monitor, `'self'` for a vendor participant, or `None` for an outsider;
[`live_payload(user, auction)`](apps/auctions/services.py) builds the JSON each poll returns —
a full leaderboard for buyers, but for vendors only their own rank/bid + the leading price,
never a competitor's identity.

**Permission gate:** create / configure / run / award is restricted to roles `tenant_admin`,
`procurement_manager`, `buyer` (plus Django superuser); the monitoring console additionally
allows `approver`. Helpers [`can_manage_auction`](apps/auctions/services.py) and
[`can_monitor_auction`](apps/auctions/services.py) encapsulate the check.

**Integration with Module 5 (Vendors):** only `active` vendors can be invited (the form
excludes `suspended` / `blacklisted` / `inactive`); invited vendors with a portal user see the
auction in their `/vendor-portal/auctions/` inbox. A nullable `Auction.sourcing_event` FK is in
place as a cheap hook for a future Sourcing → E-Auction hand-off.

**Concurrency:** `place_bid()` and `finalize_auction()` take a `select_for_update()` lock on the
auction row inside `@transaction.atomic`, so simultaneous bids are serialised and two vendors
cannot both "beat" the same best price.

---

## Module 9 — Contract Management

The post-award contract lifecycle ([apps/contracts/](apps/contracts/)) — author a contract from a
library of pre-approved clauses, route it for signature, run it through its term while tracking
deliverables and milestones, and renew, amend or terminate it. Suppliers review and sign from the
existing vendor portal. All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Contract Authoring & Templating** | A reusable `ContractClause` library (categorised, pre-approved legal text) + `ContractTemplate` (+ `ContractTemplateClause`). `create_contract_from_template()` clones a template's clauses into a fresh draft `Contract`; `save_contract_as_template()` snapshots a contract back into a template. The authoring screen assembles ordered `ContractClauseLine` rows (snapshotted, so later library edits never mutate executed text) into `Contract.body`. Auto-numbered `CON-<SLUG>-NNNNN`. |
| **E-Signature Integration** | `ContractSignatory` (ordered, internal stakeholders **and** suppliers). `send_for_signature()` issues each pending signatory an unguessable `sign_token` (`secrets.token_urlsafe`) and moves the contract `draft → pending_signature`. Internal signers sign in-app; suppliers sign from `/vendor-portal/sign/<token>/` by typing their name. When the last signatory signs, the contract auto-activates. A *mock, pluggable* flow (no external provider) consistent with the mock payment gateway. |
| **Renewal & Expiration Alerts** | `Contract.end_date` / `auto_renew` / `renewal_term_months` / `renewal_notice_days`. `scan_contract_alerts()` raises a one-time `portal.Notification` to the owner for contracts inside their notice window (idempotent via `renewal_alerted_at`), auto-renews or expires past-due contracts and flags overdue obligations. Driven by the cron-friendly `run_contract_alerts` command **and** a lazy sweep when the renewals board is opened. |
| **Contract Amendment Tracking** | `ContractAmendment` records a proposed change (value / end-date / body). `apply_amendment()` snapshots the previous values, applies the non-null changes, bumps `Contract.revision`, and is wrapped in `@transaction.atomic`. Applied amendments become an immutable part of the version history (admin change/delete disabled once applied). |
| **Obligation & Milestone Management** | `ContractObligation` (deliverable / milestone / payment / penalty / SLA / report) with due date, amount, penalty amount, optional `AccountCode` and responsible party. A tenant-wide obligations board groups them by Overdue / Open / Completed / Waived; `mark_overdue_obligations()` flips past-due open obligations to `overdue`. |

**Status workflow:** `draft → pending_signature → active → (expired | terminated | renewed)` plus
`cancelled`. Sending for signature validates ≥1 clause/body, ≥1 signatory, a vendor and an end date.
A declined signature drops the contract back to `draft`. `renew_contract()` clones an active/expired
contract into a fresh draft (linked via `parent_contract`, dates rolled forward, clauses/signatories/
obligations copied) and marks the predecessor `renewed`. `ContractStatusEvent` is an append-only
lifecycle timeline (admin add/change/delete disabled, mirroring `AuditLog` / `AuctionBid`).

**Permission gate:** create / author / configure / sign / amend / terminate is restricted to roles
`tenant_admin`, `procurement_manager`, `buyer` (plus Django superuser); analytics additionally allows
`approver`. Helpers [`can_manage_contract`](apps/contracts/services.py) and
[`can_view_contract`](apps/contracts/services.py) encapsulate the check.

**Vendor-side gate:** [`contract_visible_to(user, contract)`](apps/contracts/services.py) lets a vendor
portal user see only contracts where they are the counterparty; the tokenized signing link is resolved
by [`signatory_for_token`](apps/contracts/services.py) and re-checked against the signed-in vendor, so
one supplier can never view or sign another's contract.

**Integration with Module 5 (Vendors):** only `active` vendors can be the counterparty (the form excludes
`suspended` / `blacklisted` / `inactive`). Nullable `Contract.sourcing_event` / `requisition` FKs are in
place as cheap provenance hooks for a future Sourcing/Requisition → Contract hand-off.

---

## Module 10 — Catalog Management

The catalogued-buying surface ([apps/catalog/](apps/catalog/)) — a curated list of internal
stock items and supplier products with volume/contract pricing, reviewed through a self-contained
approval workflow, fed by both **real cXML/OCI punch-out** round-trips and **supplier-hosted file
uploads**. Mirrors the Module 9 conventions (tenant-aware models, `CAT-<SLUG>-NNNNN` numbering,
append-only timeline). All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Catalog Item Creation** | `CatalogItem` (`CAT-<SLUG>-NNNNN`, `source` internal/supplier) + a dedicated product taxonomy `CatalogCategory` (self-FK tree, distinct from `vendors.VendorCategory` which classifies *suppliers*). Items carry SKU/MPN, UoM, currency, a 4-dp `base_price`, optional supplier `Vendor` and `AccountCode` (GL coding). Full CRUD; only `draft`/`rejected` items are editable. |
| **Pricing & Tier Management** | `CatalogPriceTier` — volume breaks (`min_quantity` → `unit_price`) and **contract prices** (FK to `contracts.Contract`) with `effective_from`/`effective_to` windows. `resolve_price(item, qty, on_date, contract)` picks the best current, in-window, quantity-satisfying tier (contract-preferred), else the base price. Tiers are edited directly while an item is a draft. |
| **Catalog Approval Workflow** | Self-contained `draft → pending_approval → approved/rejected → retired/archived` lifecycle on `CatalogItem` (a rejected item returns to editable). Price changes to an **approved** item are themselves reviewed via `CatalogPriceChangeRequest` — approving one snapshots the previous price and applies the new base/tier schedule atomically. An append-only `CatalogItemStatusEvent` timeline records every transition. A Kanban approval board groups items by status. |
| **Punch-out Catalog Integration** | **Real cXML & OCI** behind a pluggable connector registry ([`apps/catalog/punchout.py`](apps/catalog/punchout.py)) modelled on the payment gateway: `SupplierPunchoutConfig` (per supplier) + `PunchoutSession`. cXML sends a server-side `PunchOutSetupRequest`, parses the `StartPage`, then receives a `PunchOutOrderMessage`; OCI renders a browser `HOOK_URL` auto-form. The returned cart becomes requisition lines or staged draft items. A `loopback` connector exercises the whole flow in tests. **Security**: setup/return URLs are SSRF-validated (HTTPS-only, non-routable hosts blocked); the inbound cart endpoint is CSRF-exempt but authenticated by an unguessable `return_token` + shared-secret; cXML is parsed with `defusedxml` (XXE-safe); the shared secret is write-only and never rendered. |
| **Supplier Catalog Hosting** | Suppliers upload a CSV/XLSX from the vendor portal (`@vendor_required`, scoped to their own vendor); `SupplierCatalogUpload` validates each row (`openpyxl` for XLSX) and stages valid rows as draft supplier items with a per-row `error_log` (a buyer then reviews and approves). File uploads are extension- and size-validated (10 MB cap). |

**Status workflow:** `draft → pending_approval → approved → (retired | archived)` plus `rejected`
(returns to editable). Submitting validates name, non-negative price and a supplier for
supplier-sourced items.

**Permission gate:** create / edit / approve / configure punch-out is restricted to roles
`tenant_admin`, `procurement_manager`, `buyer` (plus Django superuser); analytics/boards
additionally allow `approver`. Helpers [`can_manage_catalog`](apps/catalog/services.py) and
[`can_view_catalog`](apps/catalog/services.py) encapsulate the check.

**Integration with other modules:** only `active` vendors can be a supplier or punch-out
counterparty; `CatalogItem.account_code` reuses Module 3's `AccountCode`; punch-out carts and
approved items flow into Module 3 requisition lines; contract-price tiers link to Module 9
contracts.

---

## Module 11 — Purchase Order (PO) Management

The downstream purchasing surface ([apps/purchase_orders/](apps/purchase_orders/)) — turn an
approved requisition (or a manual entry) into a purchase order, dispatch it to a supplier who
acknowledges or declines it from the vendor portal, track delivery line-by-line, and close it out —
or revise it with a change order. Mirrors the Module 9 conventions (tenant-aware models,
`PO-<SLUG>-NNNNN` numbering, append-only timeline). All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **PO Generation** | `PurchaseOrder` (`PO-<SLUG>-NNNNN`) + `PurchaseOrderLine` (qty, UoM, 2-dp unit price, optional `AccountCode`, per-line delivery tracking). `create_po_from_requisition()` clones an approved requisition's lines into a fresh draft PO and marks the requisition `converted` — the **Create Purchase Order** button on the approved-requisition detail does exactly this (`?from_requisition=<id>`). POs can also be entered manually. |
| **PO Dispatch & Acknowledgment** | `issue_po()` validates (supplier + ≥1 line + total > 0), stamps the dispatch method/recipient and moves `draft → issued`, raising a `portal.Notification` to the supplier's portal user. The supplier **acknowledges** or **declines** from `/vendor-portal/purchase-orders/<id>/`; a buyer can also record the acknowledgment on a portal-less supplier's behalf. A declined PO can be reopened to draft. |
| **PO Change Order Management** | `PurchaseOrderChangeOrder` captures a proposed delivery date and per-line `(quantity, unit_price)` change as a `proposed_lines` JSON. `apply_change_order()` snapshots the previous values, writes the new ones, recomputes totals and bumps `PurchaseOrder.revision` — atomically. Applied change orders are frozen into the version history (admin change/delete disabled once applied). |
| **PO Cancellation & Close-out** | `cancel_po()` cancels an unfulfilled PO (draft / issued / acknowledged / partially-received / declined) with a reason; `close_po()` closes a fully or partially received PO. Both write the append-only `PurchaseOrderStatusEvent` timeline and an audit entry. |
| **PO Line Item Tracking** | Each `PurchaseOrderLine` carries a `delivery_status` (pending / partial / received / cancelled) and a `received_quantity`. `record_line_receipt()` posts a receipt (rejecting over-receipt), rolls the PO status up to `partially_received` / `received`, and feeds a status-grouped tracking board. A lightweight precursor to Module 13 (Goods Receipt & Inspection). |

**Status workflow:** `draft → issued → acknowledged → (partially_received → received) → closed`
plus `declined` (issued → declined → draft / cancelled) and `cancelled`. Only drafts are
editable/deletable; receipts and change orders apply only to an issued PO.

**Permission gate:** create / edit / issue / acknowledge / change / cancel / close is restricted to
roles `tenant_admin`, `procurement_manager`, `buyer` (plus Django superuser); analytics/tracking
additionally allow `approver`. Helpers [`can_manage_po`](apps/purchase_orders/services.py) and
[`can_view_po`](apps/purchase_orders/services.py) encapsulate the check.

**Vendor-side gate:** [`po_visible_to(user, po)`](apps/purchase_orders/services.py) lets a vendor
portal user see only POs issued to their own vendor, and only once dispatched (a still-draft PO is
never exposed) — so one supplier can never view or acknowledge another's order.

**Alerts:** `scan_po_alerts()` raises a one-time reminder for an issued PO left unacknowledged past
its window and a one-time alert for an overdue delivery (idempotent via `ack_alerted_at` /
`delivery_alerted_at`). Driven by the cron-friendly `run_po_alerts` command **and** a lazy sweep when
the tracking board is opened.

**Integration with Modules 3 & 5:** a nullable `PurchaseOrder.requisition` FK (and per-line
`requisition_line`) records provenance; only `active` vendors can be the supplier (the form excludes
`suspended` / `blacklisted` / `inactive`), and a vendor cannot be deleted while a PO references it
(`on_delete=PROTECT`).

---

## Module 12 — Order Fulfillment & Tracking

The logistics layer ([apps/fulfillment/](apps/fulfillment/)) — it sits in the P2P cycle *after* a
PO is issued (Module 11) and *before* the future Goods Receipt & Inspection (Module 13), answering
"where is my order, and did it arrive?". A supplier raises an ASN against a dispatched PO, the
shipment is tracked through a carrier, and confirming delivery posts the received quantities back
into the PO. Mirrors the Module 11 conventions: `TenantAwareModel` + `TimeStampedModel`, gap-free
`SHP-<SLUG>-NNNNN` numbering, and append-only timeline/ledger models. All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Advanced Shipping Notice (ASN)** | `Shipment` (`SHP-<SLUG>-NNNNN`) + `ShipmentLine` (each line ships a quantity of a `PurchaseOrderLine`, with packing details — carton/package refs, weight, package count). A supplier raises and **advises** the ASN from the vendor portal (`/vendor-portal/shipments/`); `advise_shipment()` moves `draft -> advised` and notifies the buyer. Buyers can also create shipments internally. |
| **Real-time Freight Tracking** | A pluggable carrier-connector registry ([`apps/fulfillment/carriers.py`](apps/fulfillment/carriers.py)) modelled on the punch-out/payment patterns: `CarrierConnector` Protocol + `MockCarrier` default (deterministic, derived from the ship date) selected via `FREIGHT_CARRIER`. `sync_tracking()` appends an append-only `ShipmentTrackingEvent` ledger (deduped) and advances the shipment status monotonically (`in_transit -> out_for_delivery -> delivered`); manual events are also supported. A real HTTP carrier must SSRF-validate its endpoint (`validate_carrier_url`, fail-closed). |
| **Delivery Confirmation** | `confirm_delivery()` captures the arrival date/time + `received_condition`, and (when `post_receipt`) posts each line's received quantity into the PO via Module 11's `record_line_receipt()`. Posting is **idempotent** — a per-line `posted_quantity` watermark means re-confirming never double-counts — and **guarded** so it can never exceed the PO outstanding (over-receipt requires a PO change order). |
| **Backorder Management** | `Backorder` tracks an undelivered remainder of a PO line with an `expected_date` and `open -> promised -> fulfilled / cancelled` lifecycle, surfaced on a board grouped by Overdue / Open / Promised / Fulfilled / Cancelled. `scan_backorder_alerts()` raises a one-time overdue alert and auto-cancels backorders whose PO has finished. |
| **Split Delivery Management** | One PO is fulfilled across many `Shipment`s; `remaining_to_ship_line()` (ordered − already-shipped across non-cancelled shipment lines) guards every line against over-shipping, and each confirmed shipment rolls the PO up to `partially_received` / `received`. |

**Status workflow:** `draft -> advised -> in_transit -> out_for_delivery -> delivered -> received -> closed`
plus `cancelled` and `exception`. A delivered/received shipment can no longer be cancelled (its
receipt has posted to the PO — reversals/RTV are Module 13's job).

**Permission gate:** create / advise / track / confirm / cancel is restricted to roles
`tenant_admin`, `procurement_manager`, `buyer` (plus Django superuser); tracking/analytics
additionally allow `approver`. Helpers [`can_manage_fulfillment`](apps/fulfillment/services.py) and
[`can_view_fulfillment`](apps/fulfillment/services.py) encapsulate the check.

**Vendor-side gate:** [`shipment_visible_to(user, shipment)`](apps/fulfillment/services.py) lets a
vendor portal user see only their own vendor's shipments; a supplier can only raise/advise an ASN
against their own dispatched PO.

**Alerts:** `scan_fulfillment_alerts()` raises a one-time alert for an in-flight shipment past its
estimated delivery date (idempotent via `delivery_alerted_at`). Driven by the cron-friendly
`run_fulfillment_alerts` command **and** a lazy sweep when the tracking board is opened.

---

## Module 13 — Goods Receipt & Inspection

The receiving surface ([apps/goods_receipt/](apps/goods_receipt/)) — when ordered goods arrive, log a
Goods Receipt Note (GRN) against the PO, capture lot/batch/serial + expiry for traceability, inspect
items against a QA checklist, attach photo/document evidence, post the accepted quantity back to the
PO, return rejected items to the supplier, and tag accepted inventory with internal barcodes
(stamped with the putaway bin). Mirrors the Module 11/12 conventions (tenant-aware models,
`GRN-<SLUG>-NNNNN` numbering, append-only timeline). All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Goods Receipt Note (GRN) Creation** | `GoodsReceipt` (`GRN-<SLUG>-NNNNN`) + `GoodsReceiptLine` (received / accepted / rejected / posted quantities, plus `lot_number` / `batch_number` / `serial_number` / `expiry_date` for recall traceability and a `bin_location` putaway destination). `create_goods_receipt()` raises a draft GRN against a dispatched, still-open PO (optionally provenance-linked to a fulfilment `Shipment`); `mark_received()` moves `draft → received`. |
| **Quality Inspection Checklists** | A fixed pass/fail QA checklist (`GoodsReceiptCheck`: packaging intact / quantity matches / no damage / labelling correct / documentation present) plus a per-line accepted/rejected split. `record_inspection()` derives the overall `pass` / `partial` / `fail` result and moves `received → inspected`. |
| **Discrepancy Reporting** | Each line carries a `discrepancy_type` (short / over / damaged / wrong item / quality failure) and a rejection reason. `apply_receipt_tolerance()` auto-flags an **over-receipt** when the received quantity exceeds the PO outstanding beyond the tolerance (the PO's `qty_tolerance_pct`, falling back to `INVOICE_QTY_TOLERANCE_PCT`) — never overriding a manual choice. Damage photos / packing slips / COAs attach via `GoodsReceiptAttachment`. All surfaced on the GRN and rolled into the analytics "top discrepancies". |
| **Return to Vendor (RTV) Processing** | `create_rtv_from_rejections()` opens a `ReturnToVendor` (`RTV-<SLUG>-NNNNN`) for the rejected lines; `authorise → ship → close`. The authorised return is surfaced to the supplier in the vendor portal (*Returns to Vendor*), where they can acknowledge it. |
| **Item Tagging & Barcoding** | `post_goods_receipt()` posts the accepted quantity to the PO line via Module 11's `record_line_receipt()` — *idempotently* (a `posted_quantity` watermark) and *guarded* (never over-receipts, so it can't double-count with Module 12) — and generates a `ReceiptTag` (internal Code128/QR code, stamped with the line's `bin_location` / `lot_number` / `expiry_date`) per accepted line, rendered on a print-friendly label sheet. |

**Status workflow:** `draft → received → under_inspection → inspected → posted → closed`, plus
`cancelled`. A posted GRN can no longer be cancelled — rejected goods flow through the RTV channel
instead.

**Integration with Modules 11 & 12:** the accepted quantity is the single thing posted to the PO,
through the same guarded `record_line_receipt()` that the fulfilment module's delivery confirmation
uses; the shared PO outstanding budget means the two receiving paths can never double-count. An
optional `Shipment` FK records which ASN a receipt was booked from **without modifying Module 12**.

---

## Module 14 — Invoice & Voucher Management

The accounts-payable surface ([apps/invoicing/](apps/invoicing/)) — the financial close of the
procure-to-pay loop: when a supplier's invoice arrives, capture it (OCR), match it against the PO
and the Goods Receipt, route mismatches through a dispute thread, then approve and pay it via a
payment voucher under the agreed net terms — capturing early-payment discounts. Mirrors the Module
11/12/13 conventions (tenant-aware models, append-only timelines).

> **Naming:** `apps.tenants.Invoice` already exists — that is the *SaaS subscription* invoice (the
> tenant pays the NavPMS platform). This module's invoice is the opposite direction (the tenant pays
> its *suppliers*), so the model is **`SupplierInvoice`** (`SINV-<SLUG>-NNNNN`) and the payment
> document is **`PaymentVoucher`** (`VCH-<SLUG>-NNNNN`) — there is no collision.

All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Invoice Capture (OCR)** | `SupplierInvoice` (`SINV-<SLUG>-NNNNN`) + `SupplierInvoiceLine`, with a `source_file` upload and a **pluggable OCR connector registry** ([`apps/invoicing/ocr.py`](apps/invoicing/ocr.py)) modelled on the payment gateway: an `OcrEngine` Protocol + `MockOcrEngine` default selected via `OCR_ENGINE` (real engines — Tesseract/Textract/Vision — drop in with no schema change). `capture_invoice_from_file()` validates the upload (extension **whitelist** + size), runs the engine and drafts the header + lines. Buyers capture from `/invoicing/capture/`; suppliers submit from the vendor portal. |
| **Three-Way Matching** | `run_three_way_match()` matches every invoice line against its `PurchaseOrderLine` (ordered qty + unit price) and the qty **received & accepted** against the PO (read from `PurchaseOrderLine.received_quantity`, which both the GRN posting and the fulfilment delivery confirmation feed). Per-line `match_status` ∈ {matched / qty_variance / price_variance / over_billed / no_receipt / no_po} with configurable tolerances (`INVOICE_QTY_TOLERANCE_PCT` / `INVOICE_PRICE_TOLERANCE_PCT`); an **over-billing guard** sums already-invoiced qty within this app. The invoice is **read-only** against the PO/GRN — it never re-posts (the GRN already did), so the two can't double-count. |
| **Dispute Resolution Workflow** | `InvoiceDisputeNote` — an append-only buyer↔supplier message thread — plus the `disputed` status. `raise_dispute()` / `add_dispute_note()` / `resolve_dispute()`. The supplier sees and replies to the thread from the vendor portal (`/vendor-portal/invoices/<id>/`). |
| **Payment Schedule / Terms Management** | `PaymentTerm` master (net days + early-payment discount %/days, e.g. *2/10 Net 30*). Submitting an invoice derives its `due_date`, `discount_due_date` and `discount_amount` from the term. A `PaymentVoucher` authorises, schedules and pays an approved invoice through the existing **mock payment gateway** ([`apps/tenants/gateways.py`](apps/tenants/gateways.py)) — idempotently (re-paying never double-charges), flipping the invoice to `paid`. |
| **Early Payment Discount Tracking** | The analytics dashboard (`/invoicing/analytics/`) surfaces every invoice still inside its discount window with the capturable savings, alongside an **AP aging** bar chart (current / 1–30 / 31–60 / 60+) and status breakdown. `scan_invoice_alerts()` raises one-time overdue-payment and closing-discount alerts (cron `run_invoice_alerts` + a lazy sweep on the dashboard). |

**Status workflow:** `draft → submitted → approved → paid`, plus `disputed` (from submitted, back to
submitted on resolve), `rejected` and `cancelled`. A separate `match_status` (`unmatched / matched /
exceptions`) is computed on submit; approving an invoice with exceptions requires an explicit
**override** (recorded). The voucher runs `draft → approved → scheduled → paid` (+ `cancelled`).

**Financial-integrity & AP hardening:**

- **Currency consistency** — a PO-backed invoice whose currency differs from its PO is flagged
  (`currency_mismatch`) as a three-way-match exception and **cannot** be vouchered until resolved.
- **Discount re-validation at payment** — `pay_voucher` re-checks the early-payment discount window
  inside the locked transaction, so a voucher created with a discount that has since lapsed is not
  silently paid at the stale amount.
- **Duplicate-invoice guard** — `check_duplicate_invoice_ref` hard-blocks a second live invoice with
  the same `(vendor, supplier_invoice_ref)` (case-insensitive; cancelled/rejected and blank refs are
  exempt); the capture/create forms also surface it as an early soft warning.
- **Per-PO tolerance overrides** — a `PurchaseOrder` may set `qty_tolerance_pct` / `price_tolerance_pct`
  that take precedence over the tenant-wide `INVOICE_*_TOLERANCE_PCT` defaults.
- **Dispute SLA escalation** — `scan_invoice_alerts` raises a one-time alert for disputes open longer
  than `INVOICE_DISPUTE_SLA_DAYS`.
- **OCR low-confidence routing** — captures below `OCR_MIN_CONFIDENCE` are flagged
  (`needs_manual_ocr_review`) with a badge + draft banner, and an audit event.
- **Opt-in email alerts** — overdue / closing-discount / dispute-SLA alerts can also email the invoice
  owner when `INVOICE_EMAIL_ALERTS` is on (in addition to the in-app notification).
- **Operational tools** — one-click "take discount" on the analytics dashboard, a streaming **CSV
  export** of the unpaid AP-aging list (`/invoicing/export/unpaid/`), and **batch** schedule/pay of
  selected vouchers from the voucher list (each through the existing TOCTOU-safe service).

**Permission gate:** capture / match / approve / dispute / pay is restricted to roles `tenant_admin`,
`procurement_manager`, `buyer` (plus Django superuser); analytics additionally allows `approver`.
Helpers [`can_manage_invoicing`](apps/invoicing/services.py) and
[`can_view_invoicing`](apps/invoicing/services.py) encapsulate the check.

**Vendor-side gate:** [`invoice_visible_to(user, invoice)`](apps/invoicing/services.py) lets a vendor
portal user see only their own vendor's invoices, and only once submitted (an internally-entered draft
is never exposed). Replaces the former Module-14 vendor-portal placeholder.

**Integration with Modules 11 & 13:** the invoice reads the PO line (ordered qty/price) and the
PO line's `received_quantity` (fed by Module 13's GRN posting and Module 12's delivery confirmation)
for the three-way match; only `active`/non-blocked vendors can be billed; a nullable `PurchaseOrder`
FK (and per-line `PurchaseOrderLine` / `GoodsReceiptLine` FKs) record provenance. Concurrency:
`pay_voucher()` locks the voucher row inside `@transaction.atomic` and re-checks `paid` before calling
the gateway, so concurrent pay requests serialise (one charges, the rest no-op).

---

## Module 15 — Spend Analytics & Reporting

The reporting layer ([apps/spend_analytics/](apps/spend_analytics/)) — the first **read-mostly**
module. It does not own transactional data; it aggregates spend that already lives in Invoicing
(Module 14), Purchase Orders (Module 11), Vendors (Module 5) and Contracts (Module 9) into one
denormalized fact table, `SpendRecord`, and drives dashboards, a report builder and exports off it.
All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Spend Dashboards** | A KPI dashboard (`/spend-analytics/`) — total spend, records, suppliers, maverick spend/% — with Chart.js views of spend by category (doughnut), top suppliers (bar), cost-center (bar) and a monthly trend (line), plus an **actual ↔ committed** toggle and a date window. |
| **Custom Report Builder** | `SpendReport` — saved, re-runnable report definitions: pick a **dimension** (vendor / category / cost-center / segment / month / source), a **measure** (total / net / count / average), a chart type and saved filters. Full CRUD + a run page. *Form-driven, not literal drag-and-drop on this stack.* Reports are private to their owner or `is_shared` to the tenant. |
| **Category Spend Analysis** | A category table (total / % of spend / count / avg) at `/spend-analytics/categories/` that drills into the suppliers and underlying records within a category (using `vendors.VendorCategory`, the commodity dimension). |
| **Maverick Spend Tracking** | Spend made **outside** preferred suppliers / active contracts / a PO. Three proxies are computed at sync and persisted as flags: `off_preferred_supplier` (segment not Preferred/Strategic), `off_contract` (no active `contracts.Contract` covering the spend date), `off_po` (an invoice line with no PO line). The tracking page breaks maverick spend down by reason / supplier / category with a filterable, paginated list. |
| **Data Export & Visualization** | One-click **CSV + XLSX** download of the dashboard dataset, a saved report's result, or the raw filtered spend records (a small reusable [`exports.py`](apps/spend_analytics/exports.py) using `csv` + `openpyxl`). These downloads are the BI feed for Excel / PowerBI. |

**The `SpendRecord` fact table:** one row per source line — an approved/paid `SupplierInvoiceLine`
(**actual** basis) or a non-cancelled `PurchaseOrderLine` (**committed** basis) — carrying
denormalized dimensions (date, vendor, category, segment, cost-center) and the maverick flags.
[`sync_spend_facts`](apps/spend_analytics/services.py) is an idempotent **upsert + prune**: it
re-derives every qualifying row and deletes any whose source no longer qualifies (e.g. an invoice
moved to `cancelled`), so the table self-heals. It runs from the cron-friendly `run_spend_sync`
command and **lazily** on the dashboard (a cheap `MAX(updated_at)` watermark check, not a full
resync per hit).

**Actual vs committed are never summed.** A PO that is later invoiced legitimately produces both a
`committed` and an `actual` row; every chart, report and KPI filters on exactly one `basis` (default
`actual`). The "department" dimension is the existing `requisitions.AccountCode` (cost center) — no
new model. The `off_contract` proxy is a date+vendor heuristic (there is no Contract↔PO/Invoice FK)
and is documented as such; v1 sums amounts without FX and warns when >1 currency appears.

**Permission gate:** every read view **and all three export endpoints** are gated on
[`can_view_spend_analytics`](apps/spend_analytics/services.py) (`tenant_admin` / `procurement_manager`
/ `buyer` / `approver` + superuser); building/running/deleting reports and triggering a manual sync
require [`can_manage_spend_analytics`](apps/spend_analytics/services.py). Private reports are visible
only to their owner or a manager, and all lookups are tenant-scoped (cross-tenant access 404s).

---

## Module 16 — Budget & Cost Management

The financial-control layer ([apps/budget/](apps/budget/)) that sits across the procure-to-pay loop
— it caps requisition spend before it starts, encumbers it once a PO is issued, and reconciles it
against actually-invoiced spend. All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Budget Allocation & Mapping** | `Budget` (`BUD-<SLUG>-NNNNN`) + `BudgetAllocation` lines mapping an `allocated_amount` to a cost centre / GL code (`requisitions.AccountCode`, optionally narrowed by `vendors.VendorCategory`) inside a `BudgetPeriod` (fiscal year / quarter / month). Full CRUD; allocations editable while the budget is a draft, then `activate` → `close`. |
| **Budget Availability Check** | [`check_requisition_budget`](apps/budget/services.py) fires when a requisition is submitted (hooked into [`requisitions.submit_requisition`](apps/requisitions/services.py)): it groups lines by cost centre and compares the request against `available = allocated − actual − committed − reserved`. `BUDGET_ENFORCEMENT='warn'` (default) flags the requisition (banner + owner notification) but lets it through; `'block'` raises a validation error and stops the submit. Every check is logged as an append-only `BudgetCheck`. |
| **Commitment Accounting** | `committed` spend = the value of open PO lines (`issued` / `acknowledged` / `partially_received`) for the cost centre in-period — a firm encumbrance not yet invoiced. Computed on read, so closing / cancelling the PO releases it automatically. |
| **Variance Analysis** | [`variance_report`](apps/budget/services.py) — per-allocation allocated vs actual vs committed with variance $/%, flags gated by `BUDGET_VARIANCE_TOLERANCE_PCT` (on track / near limit / over budget), plus CSV + XLSX export. |
| **Forecasting & Projection** | [`forecast`](apps/budget/services.py) — a linear run-rate projection (actual ÷ fraction-of-period-elapsed, floored at actual + open commitments) to period end vs allocated, flagging cost centres that will overrun. An honest "history + open POs" model, not a statistical forecast. |

**Compute-on-read, no ledger.** `actual` (approved/paid invoice lines), `committed` (open PO lines)
and `reserved` (open requisition lines) are all derived live from the authoritative transactional
tables, scoped by `account_code` + the budget period's dates — there is no stored ledger and no
reversal hooks, so any status change on a source document is reflected on the next read. The
dimension is the existing `requisitions.AccountCode`, the same cost-centre dimension used by Module
15. The CSV/XLSX helpers are reused from [`apps/spend_analytics/exports.py`](apps/spend_analytics/exports.py).

**Permission gate:** every read view **and both export endpoints** are gated on
[`can_view_budget`](apps/budget/services.py) (`tenant_admin` / `procurement_manager` / `buyer` /
`approver` + superuser); creating/editing/activating/closing budgets and editing allocations require
[`can_manage_budget`](apps/budget/services.py). All lookups are tenant-scoped (cross-tenant access
404s). A cron-friendly `run_budget_alerts` raises a one-time over-budget / high-burn alert per active
budget (idempotent via `Budget.over_budget_alerted_at`).

---

## Module 17 — Supplier Performance & Evaluation

The feedback loop that closes procure-to-pay ([apps/supplier_performance/](apps/supplier_performance/)):
it turns the transactional data the system already captures (goods receipts, PO acknowledgements,
RFx responses, supplier invoices) plus internal reviews into **vendor performance scores**. All five
PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **KPI Definition & Setup** | `KpiDefinition` — a configurable metric (`kpi_type`, `source` auto/manual/feedback, `direction` higher/lower-better, `weight`, `target_value`, thresholds). `ensure_default_kpis` provisions a starter set summing to 100% weight (On-Time Delivery, Defect Rate, Responsiveness, Price Variance, 360° Feedback). Full CRUD + "restore defaults". |
| **Scorecard Generation** | `Scorecard` (`SPC-<SLUG>-NNNNN`) + per-KPI `ScorecardLine`. [`generate_scorecard`](apps/supplier_performance/services.py) runs the engine once per active KPI, normalises each raw value to 0–100, and **persists a snapshot** — overall = weighted mean over the KPIs that actually scored (a missing-data metric is excluded, never counted as 0). |
| **360-Degree Feedback Collection** | `PerformanceFeedback` — a manager requests a review from an internal stakeholder (notification raised); the reviewer submits a 1–5 rating (+ facet ratings + comments). Submitted ratings aggregate into the feedback KPI. |
| **Performance Improvement Plans (PIP)** | `ImprovementPlan` (`PIP-<SLUG>-NNNNN`) + `PIPAction` items + an append-only `PIPStatusEvent` timeline. Lifecycle `draft → open → in_progress → completed → closed` (+ `cancelled`), validated transitions. Auto-flagged as a candidate (manager notification) when a finalised scorecard lands in the *poor*/*critical* band. |
| **Benchmarking & Trending** | [`vendor_trend`](apps/supplier_performance/services.py) (overall + per-KPI series over successive periods) and [`tenant_benchmark`](apps/supplier_performance/services.py) (every vendor's current score vs the tenant average), each with a Chart.js view + CSV/XLSX export. |

**Snapshot, not compute-on-read.** Unlike Module 16 (Budget), a scorecard is a *point-in-time*
evaluation: `generate_scorecard` reads the source tables once and freezes every line, so trending,
PIP triggers and the vendor rating stay stable even when the underlying receipts/invoices are later
edited. Each line also snapshots the KPI's code/name/type/target, so a later KPI rename or delete
never rewrites history.

**KPI data sources** (read live at generation): On-Time Delivery — `goods_receipt.GoodsReceipt.received_date`
vs `purchase_orders.PurchaseOrder.expected_delivery_date`; Defect Rate — `GoodsReceiptLine` rejected ÷
received; Responsiveness — RFx/sourcing `invited_at → responded_at` + PO `issued_at → acknowledged_at`;
Price Variance — `invoicing.SupplierInvoiceLine.price_variance`; Feedback — submitted
`PerformanceFeedback` ratings.

**Vendor denormalisation.** The latest *final* scorecard's score is written onto
`vendors.Vendor.performance_score` / `performance_band` / `performance_scored_at` (the same precedent
as `risk_score` from `VendorRiskAssessment`), so vendor lists and the portal can show a current grade
without recomputing.

**Permission gate:** every read view **and both export endpoints** are gated on
[`can_view_supplier_performance`](apps/supplier_performance/services.py) (`tenant_admin` /
`procurement_manager` / `buyer` / `approver` + superuser); defining KPIs, generating/finalising
scorecards, requesting feedback and running PIPs require
[`can_manage_supplier_performance`](apps/supplier_performance/services.py). All lookups are
tenant-scoped (cross-tenant access 404s). The CSV/XLSX helpers are reused from
[`apps/spend_analytics/exports.py`](apps/spend_analytics/exports.py).

**Vendor-side:** suppliers see their own *final* scorecards, an anonymised feedback summary, and
their non-draft improvement plans (which they can acknowledge) at `/vendor-portal/performance/`.

**Cron:** `run_scorecards` generates a final scorecard for every active vendor over a period
(defaults to the trailing calendar quarter); `--pip-sweep` additionally raises a one-time alert for
each overdue improvement plan (idempotent via `ImprovementPlan.alerted_at`).

---

## Module 18 — Risk & Compliance Management

The governance layer over the whole procure-to-pay loop ([apps/compliance/](apps/compliance/)) —
where the other modules *transact*, this one *polices*. Self-contained: it references existing models
(`Vendor`, POs, invoices) by FK/query only and makes **zero source-app migrations except one** — the
tamper-evident hash-chain added to Module 1's `AuditLog`. All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Regulatory Compliance Checks** | `RestrictedPartyEntry` (OFAC/SAM/EU denied-party records) + `ComplianceScreening` (`SCR-<SLUG>-NNNNN`) + `ScreeningMatch`. A pluggable [`screening.py`](apps/compliance/screening.py) connector registry (env `SCREENING_PROVIDER`, SSRF-guarded `validate_screening_url`) fuzzy-matches a vendor/name against the lists; the bundled `MockScreeningProvider` is deterministic. Each hit is dispositioned (false-positive / confirmed) and a confirmed match flips the screening to `blocked`. |
| **Supplier Financial Risk Monitoring** | `FinancialRiskProfile` (one per vendor: credit score, risk band, outlook, exposure) + append-only `FinancialRiskSnapshot` history driving a trend chart. A pluggable [`credit.py`](apps/compliance/credit.py) connector (env `CREDIT_PROVIDER`, SSRF-guarded) supplies the score; `refresh_financial_risk` recomputes exposure from open POs + unpaid invoices and alerts on a score drop ≥ `CREDIT_SCORE_DROP_ALERT` or a worsening band. |
| **Audit Trail & Logging** | Reuses the append-only `tenants.AuditLog` (no duplicate audit infra) and adds a **tamper-evident SHA-256 hash chain** (`prev_hash`/`row_hash`, backfilled by migration). `record_audit` chains each new row under `select_for_update`; `verify_audit_chain` recomputes the chain and reports the first broken row. A tenant-facing explorer at `/compliance/audit/` (search/filter/CSV export) plus a **Verify integrity** action surface it. |
| **Fraud Detection Rules** | `FraudRule` (5 configurable detectors) + `FraudAlert` (`FRD-<SLUG>-NNNNN`, CharField `subject_type`/`subject_id` snapshots — no source FK) + append-only `FraudAlertEvent` timeline. `scan_fraud` runs: **split-PO** (same vendor+buyer under the approval ceiling, summing over), **duplicate-invoice** (same vendor+amount sharing a `supplier_invoice_ref`/date), **round-amount**, **shared-bank-account**, and **conflict-of-interest** (vendor email domain matches an internal user). Findings dedupe on a stable `signature`. |
| **Policy Management & Acknowledgment** | `Policy` (`POL-<SLUG>-NNNNN`, draft → published → archived) + immutable `PolicyVersion` repository + `PolicyAcknowledgment` (one per user per version). Publishing asks every active user to acknowledge; a **My Policies** page (`/compliance/my-policies/`) captures sign-offs with IP + timestamp, and the policy detail shows an acknowledgment-rate bar. |

**Permission gate:** manage actions (run screening, manage rules/policies, resolve alerts, refresh
risk) are restricted to roles `tenant_admin`, `procurement_manager`, `buyer` (plus superuser); view
(dashboard / lists / audit explorer) additionally allows `approver`. Helpers
[`can_manage_compliance`](apps/compliance/services.py) / [`can_view_compliance`](apps/compliance/services.py)
encapsulate the check; a `requester` is bounced entirely.

**Cron:** `scan_compliance_alerts` refreshes due financial profiles, runs the fraud scan, and sends
acknowledgment-reminder digests across all tenants — idempotent (fraud alerts dedupe on signature;
financial alerts stamp `FinancialRiskProfile.alerted_at`).

---

## Module 19 — Inventory & Warehouse Integration

The stock layer under the procure-to-pay loop ([apps/inventory/](apps/inventory/)) — where Module 13
records that goods *arrived* (and only bumps `PurchaseOrderLine.received_quantity`), this module records
where that stock now *lives*, how much is on hand, when it expires, what it is worth, and reconciles it.
**Self-contained, like Module 18:** it references existing models (`CatalogItem`, `GoodsReceiptLine`,
`Requisition`) by FK/query only and makes **zero source-app migrations** — stock is fed from posted
goods receipts by a sync service, never by editing Module 13. All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Stock Level Visibility** | `StockItem` (the on-hand roll-up per catalog item: `quantity_on_hand` / `quantity_reserved` + a `moving_avg_cost`) over `StockLevel` buckets (one per warehouse/location/lot/serial/expiry/condition). `sync_stock_from_receipts` folds every newly-posted, accepted `GoodsReceiptLine` into an inbound movement — matching the PO line's **SKU** to an approved `CatalogItem` — *idempotently* via the unique `StockMovement.source_goods_receipt_line` watermark (the dashboard syncs lazily; lines with no/unmatched SKU are skipped). |
| **Reorder Point Automation** | Each `StockItem` carries `reorder_point` / `reorder_quantity` / `safety_stock` / `lead_time_days`. `run_reorder_automation` raises a **draft `requisitions.Requisition`** (+ line) for every stocked item whose *available* stock is at/below its reorder point and notifies procurement — *idempotent* (it never re-raises while an open reorder requisition exists, tracked on `StockItem.reorder_requisition`). A human reviews and submits it into the normal Module 4 approval flow. |
| **Goods Issue / Return to Stock** | `GoodsIssue` (`GI-<SLUG>-NNNNN`) + `GoodsIssueLine` with an `issue_type` of consumption / write-off (out) or return-to-stock (in). `post_goods_issue` applies the signed movements through the shared `apply_movement` primitive (negative-stock guarded), `draft → issued` (+ `cancelled`), with an append-only status timeline. |
| **Warehouse Location Mapping** | `Warehouse` (`code` / default flag) + `WarehouseLocation` (bin `code` + aisle / rack / shelf) formalise the free-text `bin_location` a GRN already writes; received stock is placed against the mapped bin (or the auto-created default warehouse). |
| **Cycle Count Integration** | `CycleCount` (`CC-<SLUG>-NNNNN`) + `CycleCountLine` snapshot the system quantity per bucket; entering a counted quantity moves `draft → in_progress`. `post_cycle_count` recomputes the variance against the **current** system quantity (not the stale snapshot) and **immediately** writes a `count_adjustment` movement for each non-zero variance — the manager's post is the control gate. |

**The ledger:** every stock change — receipt, issue, return, manual adjustment, cycle-count
adjustment — flows through one atomic `apply_movement` that upserts the `StockLevel` bucket, keeps the
`StockItem` on-hand roll-up + moving-average cost in sync, guards against negative stock, and appends
an immutable `StockMovement` (signed quantity + running `balance_after`) with an audit entry. The
`StockMovement` ledger is the single source of truth (append-only — the documented exception to the
CRUD-completeness rule).

**Permission gate:** manage actions (adjust stock, issue/return goods, post counts, run reorder,
manage warehouses) are restricted to roles `tenant_admin`, `procurement_manager`, `buyer` (plus
superuser); view (dashboard / lists / ledger) additionally allows `approver`. Helpers
[`can_manage_inventory`](apps/inventory/services.py) / [`can_view_inventory`](apps/inventory/services.py)
encapsulate the check; a `requester` is bounced entirely.

**Cron:** `run_inventory_alerts` syncs newly-posted receipts into stock, runs the reorder automation,
and raises one-time near-expiry alerts across all tenants — idempotent (receipt sync is watermarked,
reorder skips items with an open requisition, expiry alerts stamp `StockLevel.expiry_alerted_at`).

---

## Module 20 — Document & Knowledge Management

The knowledge layer over the procure-to-pay loop ([apps/dms/](apps/dms/)) — the central, versioned,
searchable home for every procurement document. Where the other modules *transact*, this one
*remembers*. All five PMS sub-modules:

| Sub-module | Implementation |
|-----------|----------------|
| **Central Document Repository** | [`Document`](apps/dms/models.py) (`DOC-<SLUG>-NNNNN`, `category`, a `confidentiality` band public/internal/restricted, owner) + [`DocumentVersion`](apps/dms/models.py) holding the uploaded `FileField` (extension + size validated). Full CRUD with search + filters. |
| **Version Control** | Each upload is an immutable numbered `DocumentVersion`. Publishing one **supersedes** the previous and re-points `Document.current_version`, so only the latest published version is downloadable. An append-only [`DocumentEvent`](apps/dms/models.py) timeline records every create / upload / publish / status change; cross-module audit reuses `tenants.record_audit`. |
| **Procurement Policy Library** | `/dms/policies/` — the policy-category documents as browsable reference files. **Cross-links** to the Module 18 [compliance](apps/compliance/) `Policy` stack (which owns read-and-acknowledge sign-off) rather than duplicating it: this module owns *files + search*, compliance owns *attestation*. |
| **Best Practices & Templates** | [`PolicyTemplate`](apps/dms/models.py) (`TPL-<SLUG>-NNNNN`) — reusable authored bodies (RFP skeletons, bid-evaluation guides, negotiation playbooks). **Clone to Document** stamps a template into a real published document via `clone_template_to_document`. |
| **Full-Text Search & Indexing** | A pluggable [`apps/dms/extraction.py`](apps/dms/extraction.py) connector fills `DocumentVersion.extracted_text`; `/dms/search/` queries it (plus titles / tags / summaries) and returns ranked hits with context snippets. |

**Pluggable text extraction.** `extraction.py` mirrors the screening / OCR connector pattern: a
registry selected by `DMS_EXTRACTION_ENGINE`. The default `mock` engine decodes file bytes locally
(no dependency — text/markdown index verbatim, binaries degrade to a stable stub) so search works out
of the box; the `local` engine parses **real PDFs** via `pypdf` (with page counts). Both are local
(no network, no SSRF surface); a `validate_extraction_url` SSRF guard (HTTPS-only, blocks non-routable
hosts, honours `DMS_EXTRACTION_ALLOWLIST`) is provided for a future hosted backend. `DMS_MAX_INDEX_CHARS`
caps stored text. Search uses portable `extracted_text__icontains` so the SQLite test DB and MySQL
prod DB share one path, with a documented MySQL `FULLTEXT` upgrade for scale.

**RBAC + tenancy.** `procurement_manager` / `buyer` / `tenant_admin` manage; `approver` may also view;
a `requester` is bounced (the D-01 lesson). Every view is tenant-scoped (cross-tenant detail/download
404s). **Cron:** `reindex_documents` re-extracts pending/failed versions across all tenants
(idempotent), useful after switching the engine to `local`.

---

## Routes / UI Tour

| URL | Purpose |
|-----|---------|
| `/` | Dashboard (stat widgets + usage chart + recent activity) |
| `/accounts/login/` | Sign in (username **or** email) |
| `/accounts/register/` | Self-service tenant + admin creation |
| `/accounts/forgot-password/` | Email a reset token |
| `/accounts/users/` | Tenant-admin user CRUD + role/status filters |
| `/accounts/invites/` | Pending invite list + send / cancel / resend |
| `/accounts/profile/` | View profile, edit, change password |
| `/tenants/onboarding/` | 3-step onboarding wizard |
| `/tenants/plans/` | Plan cards (super-admin can CRUD) |
| `/tenants/subscriptions/` | Subscription list, detail, change-plan |
| `/tenants/invoices/` | Invoice list, detail, **Pay now** (mock charge) |
| `/tenants/branding/` | Logo, colors, email branding |
| `/tenants/security/` | Password policy, MFA, IP allowlist |
| `/tenants/monitoring/` | 4-chart health dashboard |
| `/tenants/monitoring/audit-logs/` | Searchable audit log |
| `/portal/` | Personalized dashboard (customizable widgets) |
| `/portal/widgets/` | Widget CRUD — customize the dashboard |
| `/portal/notifications/` | Task & Alert Center — list, detail, CRUD, mark-read |
| `/portal/requisitions/` | Quick requisition list + fast-track entry + inline items |
| `/portal/activity/` | Recent activity feed (the user's own actions) |
| `/portal/reports/` | Self-service reports — save, run, chart |
| `/requisitions/` | Requisition list — search + status/category/scope filters |
| `/requisitions/create/` | New requisition (header → detail for line items) |
| `/requisitions/tracking/` | Status board grouping requisitions by workflow state |
| `/requisitions/templates/` | Requisition templates — pre-defined recurring forms |
| `/requisitions/account-codes/` | Account-code master CRUD (tenant admin) |
| `/approvals/` | My Approvals — mobile-friendly approver inbox |
| `/approvals/requests/` | All approval requests with progress |
| `/approvals/rules/` | Approval rule + step CRUD (tenant admin) |
| `/approvals/delegations/` | Delegation of authority CRUD |
| `/approvals/history/` | Append-only approval audit trail |
| `/vendors/` | Vendor master — search + status/category/segment/risk filters |
| `/vendors/create/` | New vendor form |
| `/vendors/<id>/` | Vendor detail (tabs: contacts, documents, banks, risk, blacklist history) |
| `/vendors/categories/` | Vendor classification CRUD (tenant admin) |
| `/vendors/segments/` | Vendor segmentation CRUD (tenant admin) |
| `/vendors/onboarding/` | Supplier onboarding queue (admin review) |
| `/vendors/onboarding/apply/<tenant-slug>/` | **Public** supplier application form |
| `/vendors/blacklist/history/` | Append-only suspend/blacklist/reinstate log |
| `/sourcing/events/` | Sourcing events — search + status/type/category filters |
| `/sourcing/events/new/` | New sourcing event (or `?from_requisition=<id>` to pre-fill from a REQ) |
| `/sourcing/events/<id>/` | Event detail (tabs: items, invitees, criteria, bids, awards) + lifecycle actions |
| `/sourcing/events/<id>/bids/` | Bid list (sealed until close) |
| `/sourcing/events/<id>/bids/compare/` | Side-by-side bid comparison matrix |
| `/sourcing/events/<id>/bids/<bid>/evaluate/` | Score a bid against the weighted criteria |
| `/sourcing/events/<id>/awards/recommend/` | Recommend an award; `finalize` from the event page |
| `/sourcing/analytics/` | Tenant-wide sourcing analytics dashboard |
| `/sourcing/events/<id>/analytics/` | Per-event savings + response-rate report |
| `/rfx/events/` | RFx events — search + status/type/category filters |
| `/rfx/events/new/` | New RFx event (or from `/rfx/templates/<id>/use/`) |
| `/rfx/events/<id>/` | Event detail (tabs: questionnaire, invitees, documents, responses) + lifecycle actions |
| `/rfx/events/<id>/responses/` | Response list (sealed until close) |
| `/rfx/events/<id>/responses/compare/` | Side-by-side response comparison matrix |
| `/rfx/events/<id>/responses/<r>/evaluate/` | Score a response against the scored questions |
| `/rfx/templates/` | RFx template library — list, create, edit, use |
| `/rfx/analytics/` | Tenant-wide RFx analytics dashboard |
| `/rfx/events/<id>/analytics/` | Per-event response-rate + final ranking report |
| `/auctions/events/` | E-Auctions — search + status/type/category filters |
| `/auctions/events/<id>/` | Auction detail (lots, participants, documents, bids) + lifecycle actions |
| `/auctions/events/<id>/console/` | Live bidding console (auto-polling leaderboard + countdown) |
| `/auctions/events/<id>/results/` | Post-auction ranking, savings + finalize award |
| `/auctions/analytics/` | Tenant-wide e-auction analytics dashboard |
| `/auctions/events/<id>/analytics/` | Per-auction savings + price-drop curve |
| `/contracts/list/` | Contracts — search + status/type/category filters |
| `/contracts/new/` | New contract (then author from clauses) |
| `/contracts/<id>/` | Contract detail (clauses, signatories, obligations, amendments, documents, timeline) + lifecycle actions |
| `/contracts/<id>/author/` | Authoring screen — assemble clauses (free-form or from the library) |
| `/contracts/<id>/amendments/new/` | Draft an amendment; apply it from the amendment detail page |
| `/contracts/renewals/` | Renewals board (active / expiring-soon / expired / renewed) |
| `/contracts/obligations/` | Obligations board (overdue / open / completed / waived) |
| `/contracts/clauses/` | Clause library CRUD (tenant admin) |
| `/contracts/templates/` | Contract template library — list, create, edit, use |
| `/contracts/analytics/` | Tenant-wide contract analytics dashboard |
| `/catalog/items/` | Catalog items — search + status/source/category filters |
| `/catalog/items/new/` | New catalog item (then add tiers, submit for approval) |
| `/catalog/items/<id>/` | Item detail (tiers, price changes, timeline) + lifecycle actions |
| `/catalog/items/<id>/price-change/new/` | Request a reviewed price change on an approved item |
| `/catalog/approvals/` | Catalog approval board (draft / pending / approved / rejected) |
| `/catalog/categories/` | Catalog category CRUD (tenant admin) |
| `/catalog/punchout/` | Punch-out supplier config + sessions; **Punch out** initiates a round-trip |
| `/catalog/punchout/return/<token>/` | **Inbound** cXML/OCI cart POST (CSRF-exempt, token-authenticated) |
| `/catalog/uploads/` | Supplier upload review + parse-and-ingest |
| `/catalog/analytics/` | Tenant-wide catalog analytics dashboard |
| `/purchase-orders/list/` | Purchase orders — search + status/vendor/category filters |
| `/purchase-orders/new/` | New PO (or `?from_requisition=<id>` to generate from an approved REQ) |
| `/purchase-orders/<id>/` | PO detail (lines, receipts, change orders, documents, timeline) + lifecycle actions |
| `/purchase-orders/<id>/change-orders/new/` | Draft a change order (qty / price / delivery date); apply from its detail page |
| `/purchase-orders/tracking/` | Tracking board (draft / issued / acknowledged / partially received / received / closed) |
| `/purchase-orders/analytics/` | Tenant-wide purchase-order analytics dashboard |
| `/fulfillment/list/` | Shipments — search + status/vendor/carrier filters |
| `/fulfillment/new/` | New shipment (or `?from_po=<id>` to ship a dispatched PO) |
| `/fulfillment/<id>/` | Shipment detail (lines, tracking timeline, documents) + lifecycle (advise / sync / confirm delivery / cancel / close) |
| `/fulfillment/tracking/` | Tracking board (draft / advised / in transit / out for delivery / delivered / received) |
| `/fulfillment/backorders/` | Backorder board (overdue / open / promised / fulfilled / cancelled) |
| `/fulfillment/analytics/` | Tenant-wide fulfillment analytics dashboard |
| `/goods-receipt/list/` | Goods receipts — search + status/vendor/PO filters |
| `/goods-receipt/new/` | New goods receipt (select an open PO, or `?from_po=<id>` from the PO page) |
| `/goods-receipt/<id>/` | GRN detail — receive → inspect (QA checklist + accept/reject) → post, tags, returns, timeline |
| `/goods-receipt/<id>/tags/` | Printable barcode/QR labels for the accepted inventory |
| `/goods-receipt/rtv/<id>/` | Return-to-Vendor detail (authorise → ship → close) |
| `/goods-receipt/analytics/` | Tenant-wide goods-receipt analytics dashboard |
| `/inventory/` | Inventory dashboard — on-hand value, below-reorder / out-of-stock / expiring KPIs + charts (lazy-syncs posted receipts) |
| `/inventory/stock/` | Stock levels — search + warehouse / in-stock / below-reorder / out filters; add / edit / adjust / delete a stock item |
| `/inventory/stock/<id>/` | Stock item detail — on-hand by location/lot, movement history, adjust action, reorder settings |
| `/inventory/movements/` | Append-only stock movement ledger — search + type / warehouse filters |
| `/inventory/warehouses/` | Warehouses + bin locations (aisle / rack / shelf) — full CRUD (tenant admin) |
| `/inventory/issues/` | Goods issues / returns — create, add lines, post (consumption / write-off / return-to-stock) |
| `/inventory/cycle-counts/` | Cycle counts — create (snapshots buckets), enter counts, post (immediate variance adjustment) |
| `/inventory/reorder/` | Reorder board — items below reorder point + auto-requisitions; **Run reorder now** raises drafts |
| `/dms/` | Documents dashboard — totals, category/status charts, index-coverage KPI, recently added |
| `/dms/documents/` | Document repository — search (incl. text inside files) + status/category/confidentiality filters; full CRUD |
| `/dms/documents/<id>/` | Document detail — version history, inline upload, publish/supersede, download, extracted-text preview, timeline |
| `/dms/search/` | Full-text search across titles, tags and the text extracted from uploaded files |
| `/dms/policies/` | Procurement policy library (policy-category documents); cross-links to compliance acknowledgment |
| `/dms/templates/` | Best-practice template library — author, edit, and **clone to a document** |
| `/invoicing/list/` | Supplier invoices — search + status/match/vendor/PO filters |
| `/invoicing/capture/` | Capture an invoice from a PDF/image (OCR) — optionally `?from_po=<id>` |
| `/invoicing/new/` | Enter an invoice manually |
| `/invoicing/<id>/` | Invoice detail — lines + three-way match, dispute thread, vouchers, timeline + lifecycle (submit / approve / dispute / resolve / reject / cancel) |
| `/invoicing/<id>/voucher/new/` | Create a payment voucher from an approved invoice |
| `/invoicing/vouchers/` | Payment vouchers — approve / schedule / **Pay now** (mock gateway) |
| `/invoicing/terms/` | Payment-term master CRUD (net terms + early-payment discounts) |
| `/invoicing/analytics/` | AP aging + early-payment discount opportunities dashboard |
| `/spend-analytics/` | Spend dashboard — KPIs + category/supplier/cost-center/month charts + actual↔committed toggle |
| `/spend-analytics/categories/` | Category spend analysis (total / % / count / avg) — drill into a category at `/categories/<id>/` |
| `/spend-analytics/maverick/` | Maverick spend tracking — off-preferred / off-contract / non-PO, filterable |
| `/spend-analytics/reports/` | Custom report builder — list / new / `<id>` (run) / edit / delete |
| `/spend-analytics/export/{dashboard,records}.{csv,xlsx}` · `/reports/<id>/export.{csv,xlsx}` | CSV / XLSX exports (the BI feed) |
| `/budget/` | Budget dashboard — allocated vs actual vs committed by cost centre + KPIs |
| `/budget/budgets/` | Budgets — list / new / `<id>` (allocations + consumption + timeline) / edit / delete |
| `/budget/budgets/<id>/forecast/` | Run-rate projection to period end |
| `/budget/periods/` | Budget periods (fiscal year / quarter) — full CRUD + status |
| `/budget/variance/` · `/variance/export.{csv,xlsx}` | Variance report + CSV / XLSX export |
| `/budget/checks/` | Availability-check audit log (every requisition budget check) |
| `/supplier-performance/` | Performance dashboard — band distribution + recent scorecards + open plans |
| `/supplier-performance/kpis/` | KPI definitions — full CRUD + restore-defaults |
| `/supplier-performance/scorecards/` · `/generate/` · `/<id>/` | Scorecards — list / generate / detail (lines + chart + finalize/regenerate) + CSV/XLSX export |
| `/supplier-performance/feedback/` | 360° feedback — request / submit / list |
| `/supplier-performance/pips/` | Improvement plans — CRUD + lifecycle + corrective actions |
| `/supplier-performance/trending/` · `/benchmarking/` | Per-vendor trend line + cross-vendor benchmark (CSV/XLSX export) |
| `/vendor-portal/performance/` | Supplier's own scorecards + anonymised feedback + acknowledgeable improvement plans |
| `/vendor-portal/` | Supplier portal dashboard (vendor users only) |
| `/vendor-portal/profile/` · `/documents/` · `/contacts/` | Vendor self-service |
| `/vendor-portal/sourcing/` | Vendor's sourcing invitations |
| `/vendor-portal/sourcing/<event>/` | RFQ read-only view (items, criteria, terms) |
| `/vendor-portal/sourcing/<event>/bid/<bid>/` | Bid form (prices per line, lead time, documents) |
| `/vendor-portal/sourcing/bids/` | All bids the vendor has started or submitted |
| `/vendor-portal/rfx/` | Vendor's RFx invitations inbox |
| `/vendor-portal/rfx/<event>/` | RFx event read-only view |
| `/vendor-portal/rfx/<event>/response/<r>/` | Answer form (one field per question) — draft + submit |
| `/vendor-portal/rfx/responses/` | All RFx responses the vendor has started or submitted |
| `/vendor-portal/auctions/` | Vendor's auction invitations |
| `/vendor-portal/auctions/<id>/` | Auction read-only view + accept/decline |
| `/vendor-portal/auctions/<id>/bidding/` | Live bidding screen (countdown, own rank, place bid) |
| `/vendor-portal/contracts/` | Supplier's contracts inbox |
| `/vendor-portal/contracts/<id>/` | Contract read-only view + sign entry point |
| `/vendor-portal/sign/<token>/` | Tokenized e-signature page (type name to sign / decline) |
| `/vendor-portal/catalog/` | Supplier's own catalog items (read-only) |
| `/vendor-portal/catalog/uploads/` | Supplier self-service catalog file uploads (CSV/XLSX) |
| `/vendor-portal/purchase-orders/` | Supplier's purchase orders inbox |
| `/vendor-portal/purchase-orders/<id>/` | PO read-only view + acknowledge / decline |
| `/vendor-portal/shipments/` | Supplier's shipments / ASNs |
| `/vendor-portal/shipments/new/` | Raise an ASN against a dispatched PO |
| `/vendor-portal/shipments/<id>/` | ASN detail + send / edit / line CRUD (while draft) |
| `/vendor-portal/returns/` | Supplier's Returns-to-Vendor inbox (read-only + acknowledge) |
| `/vendor-portal/invoices/` | Supplier's invoices inbox |
| `/vendor-portal/invoices/new/` | Submit an invoice against a dispatched PO (OCR-captured) |
| `/vendor-portal/invoices/<id>/` | Invoice read-only view + dispute thread reply |
| `/admin/` | Django admin |

---

## Multi-tenancy Model

- Every domain model extends [`TenantAwareModel`](apps/core/models.py) which adds a non-null
  `tenant` FK and uses `TenantManager` as its default `.objects` manager.
- A request middleware ([`apps/core/middleware.py`](apps/core/middleware.py)) sets
  `request.tenant` from `request.user.tenant` and binds the same value to a thread-local.
- `TenantManager.get_queryset()` reads the thread-local and automatically filters every query
  by the current tenant, so a forgotten `.filter(tenant=...)` in a view does not leak data.
- An `all_objects` escape-hatch manager exists for management commands and audit-chain reads.

---

## Payment Gateway

Defined as a `Protocol` in [`apps/tenants/gateways.py`](apps/tenants/gateways.py). The default
implementation is `MockGateway` (always succeeds, sleeps 200ms, returns a fake gateway ref).

To wire a real gateway:
1. Implement `charge` + `refund` on a new class.
2. Register it in `_GATEWAY_REGISTRY`.
3. Set `PAYMENT_GATEWAY=<name>` in `.env`.
4. **Important**: verify webhook signatures and re-derive `amount` from the `Invoice` on the
   server (see the module docstring for the standard pitfalls).

---

## Browser Compatibility

Tested against Chrome, Firefox, Safari, Edge (latest two majors). No IE support.

---

## Roadmap

Modules 1–19 ship. The remaining PMS modules are not yet implemented:

| # | Module | Status |
|---|--------|--------|
| 1 | Tenant & Subscription Management | Shipped |
| 2 | User Dashboard & Portal | Shipped |
| 3 | Requisition Management | Shipped |
| 4 | Approval Workflow Engine | Shipped |
| 5 | Vendor Management | Shipped |
| 6 | Sourcing & Tendering | Shipped |
| 7 | RFx Management | Shipped |
| 8 | E-Auction Management | Shipped |
| 9 | Contract Management | Shipped |
| 10 | Catalog Management | Shipped |
| 11 | Purchase Order Management | Shipped |
| 12 | Order Fulfillment & Tracking | Shipped |
| 13 | Goods Receipt & Inspection | Shipped |
| 14 | Invoice & Voucher Management | Shipped |
| 15 | Spend Analytics & Reporting | Shipped |
| 16 | Budget & Cost Management | Shipped |
| 17 | Supplier Performance & Evaluation | Shipped |
| 18 | Risk & Compliance Management | Shipped |
| 19 | Inventory & Warehouse Integration | Shipped |
| 20 | Document & Knowledge Management | Shipped |
| 21 | System Administration & Security | Planned |

See [PMS.md](PMS.md) for the full 20-module spec.

---

## License

See [LICENSE](LICENSE).
