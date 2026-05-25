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
Bid Submission Portal, Bid Evaluation Matrix, Award Recommendation, Sourcing Analytics).

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
15. [Routes / UI Tour](#routes--ui-tour)
16. [Multi-tenancy Model](#multi-tenancy-model)
17. [Payment Gateway](#payment-gateway)
18. [Browser Compatibility](#browser-compatibility)
19. [Roadmap](#roadmap)

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
│   └── sourcing/             # Module 6: SourcingEvent(+Item), SourcingEventInvitee,
│                             # SourcingCriterion, Bid(+Line +Document), BidEvaluation,
│                             # SourcingAward (append-only)
├── config/                   # settings.py, urls.py, wsgi.py, asgi.py
├── static/
│   ├── css/  style.css, auth.css
│   ├── js/   app.js (theme manager), auth.js
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
│   └── vendor_portal/        # Separate shell for supplier self-service
│       └── sourcing/         # Vendor-side bid submission + invitations
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
| `TIME_ZONE` | `UTC` | |
| `LANGUAGE_CODE` | `en-us` | |

---

## Management Commands

| Command | What it does |
|---------|--------------|
| `python manage.py seed_data` | Orchestrator: runs `seed_plans` → `seed_tenants` → `seed_users` → `seed_portal` → `seed_requisitions` → `seed_approvals` → `seed_vendors` → `seed_sourcing`. |
| `python manage.py seed_plans` | Creates 4 canonical plans (Free / Starter / Professional / Enterprise). |
| `python manage.py seed_tenants` | Creates 3 demo tenants with subscriptions, invoices, branding, audit, metrics. |
| `python manage.py seed_users` | Creates a tenant_admin + 4 staff users per tenant. |
| `python manage.py seed_portal` | Creates dashboard widgets, notifications, quick requisitions and saved reports for every tenant user. |
| `python manage.py seed_requisitions` | Creates account codes, requisition templates and requisitions across every status for each tenant. |
| `python manage.py seed_approvals` | Creates approval rules, steps and a delegation, and routes submitted requisitions through the engine. |
| `python manage.py seed_vendors` | Creates vendor categories, segments, 8 vendors across every status, contacts/docs/banks, risk assessments, 3 onboarding applications and blacklist history. |
| `python manage.py seed_sourcing` | Creates 3 sourcing events per tenant (draft / open with 2 bids / awarded with full evaluation matrix + finalised award + savings). |
| `python manage.py run_escalations` | Escalates overdue approval tasks (cron-friendly; the inbox also sweeps lazily). |

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
| Suites | [tenants](apps/tenants/tests/), [portal](apps/portal/tests/), [requisitions](apps/requisitions/tests/), [approvals](apps/approvals/tests/) — Modules 1–4, **253 tests** |
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

### Sourcing data
Each tenant gets 3 sourcing events:
- **Draft** — "Office stationery Q2" (RFQ, 3 items, 4 criteria, no invitees yet)
- **Open** — "Server hardware refresh" (RFP, 4 items, 4 criteria, 3 invitees, 1 draft bid + 1 submitted bid)
- **Awarded** — "Janitorial services Q1" (Tender, 2 items, 4 criteria, 3 submitted bids, full panel evaluation, lowest weighted-cost compliant winner, recorded savings)

Criteria template: Price 40 / Quality 25 / Delivery 20 / Compliance 15 (sums to 100).

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
| `/vendor-portal/` | Supplier portal dashboard (vendor users only) |
| `/vendor-portal/profile/` · `/documents/` · `/contacts/` | Vendor self-service |
| `/vendor-portal/sourcing/` | Vendor's sourcing invitations |
| `/vendor-portal/sourcing/<event>/` | RFQ read-only view (items, criteria, terms) |
| `/vendor-portal/sourcing/<event>/bid/<bid>/` | Bid form (prices per line, lead time, documents) |
| `/vendor-portal/sourcing/bids/` | All bids the vendor has started or submitted |
| `/vendor-portal/purchase-orders/` · `/invoices/` | Placeholders for Modules 11 / 14 |
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

Modules 1–6 ship. Modules 7–21 from the PMS spec are not yet implemented:

| # | Module | Status |
|---|--------|--------|
| 1 | Tenant & Subscription Management | Shipped |
| 2 | User Dashboard & Portal | Shipped |
| 3 | Requisition Management | Shipped |
| 4 | Approval Workflow Engine | Shipped |
| 5 | Vendor Management | Shipped |
| 6 | Sourcing & Tendering | Shipped |
| 7 | RFx Management | Planned |
| 8 | E-Auction Management | Planned |
| 9 | Contract Management | Planned |
| 10 | Catalog Management | Planned |
| 11 | Purchase Order Management | Planned |
| 12 | Order Fulfillment & Tracking | Planned |
| 13 | Goods Receipt & Inspection | Planned |
| 14 | Invoice & Voucher Management | Planned |
| 15 | Spend Analytics & Reporting | Planned |
| 16 | Budget & Cost Management | Planned |
| 17 | Supplier Performance & Evaluation | Planned |
| 18 | Risk & Compliance Management | Planned |
| 19 | Inventory & Warehouse Integration | Planned |
| 20 | Document & Knowledge Management | Planned |
| 21 | System Administration & Security | Planned |

See [PMS.md](PMS.md) for the full 20-module spec.

---

## License

See [LICENSE](LICENSE).
