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
Templates, Cancellation/Amendment), and **Module 4 — Approval Workflow Engine** (all five
sub-modules: Dynamic Routing Rules, Delegation of Authority, Approval History & Audit Trail,
Escalation Management, Mobile Approval Interface).

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
13. [Routes / UI Tour](#routes--ui-tour)
14. [Multi-tenancy Model](#multi-tenancy-model)
15. [Payment Gateway](#payment-gateway)
16. [Browser Compatibility](#browser-compatibility)
17. [Roadmap](#roadmap)

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
│   └── approvals/            # Module 4: ApprovalRule(+Step), ApprovalDelegation,
│                             # ApprovalRequest, ApprovalTask, ApprovalAction
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
│   └── approvals/{rules,delegations,requests}/ + inbox, task_detail, history
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
| `python manage.py seed_data` | Orchestrator: runs `seed_plans` → `seed_tenants` → `seed_users` → `seed_portal` → `seed_requisitions` → `seed_approvals`. |
| `python manage.py seed_plans` | Creates 4 canonical plans (Free / Starter / Professional / Enterprise). |
| `python manage.py seed_tenants` | Creates 3 demo tenants with subscriptions, invoices, branding, audit, metrics. |
| `python manage.py seed_users` | Creates a tenant_admin + 4 staff users per tenant. |
| `python manage.py seed_portal` | Creates dashboard widgets, notifications, quick requisitions and saved reports for every tenant user. |
| `python manage.py seed_requisitions` | Creates account codes, requisition templates and requisitions across every status for each tenant. |
| `python manage.py seed_approvals` | Creates approval rules, steps and a delegation, and routes submitted requisitions through the engine. |
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
| Coverage | [apps/portal/tests/](apps/portal/tests/) — Module 2 suite, 94 tests, ~91% line coverage |

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

Modules 1–4 ship. Modules 5–21 from the PMS spec are not yet implemented:

| # | Module | Status |
|---|--------|--------|
| 1 | Tenant & Subscription Management | Shipped |
| 2 | User Dashboard & Portal | Shipped |
| 3 | Requisition Management | Shipped |
| 4 | Approval Workflow Engine | Shipped |
| 5 | Vendor Management | Planned |
| 6 | Sourcing & Tendering | Planned |
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
