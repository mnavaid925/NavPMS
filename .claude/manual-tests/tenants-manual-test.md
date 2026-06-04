# Module 1: Tenant & Subscription Management — Manual Test Plan

> Verified against source on 2026-06-04. URL line numbers, toast strings, status
> values, permission behaviour, and seed data below were read directly from
> [`apps/tenants/`](apps/tenants/) and [`apps/accounts/management/commands/seed_users.py`](apps/accounts/management/commands/seed_users.py).

## 1. Scope & Objectives
This plan covers the **Tenant & Subscription Management** module ([`apps/tenants`](apps/tenants/)). It verifies the multi-tenant provisioning lifecycle: the public onboarding wizard, subscription plans (super-admin CRUD), subscription assignment/cancellation, invoice payment via the mock gateway, tenant-scoped branding & security policy, and the monitoring/audit dashboards.

The goal is to let a non-developer tester validate permissions, status transitions, multi-tenant boundaries (IDOR prevention), filters, and the full billing/admin UI — with exact expected toast text and badge colours so "pass/fail" is unambiguous.

## 2. Pre-Test Setup (Windows PowerShell)

> **IMPORTANT — do not run `seed_tenants` alone.** It seeds tenants/invoices/branding/audit **but creates no user accounts**. The `admin_acme` login is created by `seed_users`. The single orchestrator below runs plans → tenants → **users** → (all other modules) in the correct order.

1. **Flush and re-seed everything (recommended):**
   ```powershell
   python manage.py seed_data --flush
   ```
   *(If you only want Module 1 data: `python manage.py seed_plans --flush; python manage.py seed_tenants --flush; python manage.py seed_users --flush` — in that exact order.)*

2. **Ensure a super-admin exists.** Seeding does **not** create one. Use your existing Django superuser, or create it:
   ```powershell
   python manage.py createsuperuser
   ```

3. **Start the server:**
   ```powershell
   python manage.py runserver
   ```
4. **Open:** `http://127.0.0.1:8000/`

### Test Accounts (all non-superusers use password `Welcome@123`)

| Role | Username | Notes |
|---|---|---|
| **Super-admin** | `admin` (your superuser) | `tenant = None`. Can manage **Plans**. Will be **redirected to onboarding** on tenant-scoped pages (invoices, subscriptions, branding, etc.) — by design. |
| **Tenant admin (Acme)** | `admin_acme` | `role=tenant_admin`, `is_tenant_admin=True`. Primary account for branding/security/billing/monitoring tests. |
| **Tenant admin (Globex)** | `admin_globex` | Used as the "other tenant" for cross-tenant IDOR tests. |
| **Tenant admin (Stark)** | `admin_stark` | Stark is seeded with stricter security (MFA on, min length 12). |
| **Tenant member** | a seeded staff user, e.g. `firstname.lastname.acme` | `role` is buyer/approver/requester/procurement_manager (`is_tenant_admin=False`). Used to test member-blocked pages. Find the exact username in the `seed_users` console output or Django admin. |

Login page: `/accounts/login/`.

### Seeded data cheat-sheet (so expected counts are concrete)

| Tenant | Plan / cycle | Invoices | Audit logs | Health metrics |
|---|---|---|---|---|
| Acme Corp (`acme`) | Professional / yearly | 3 → `INV-ACME-00001`,`-00002` **paid**, `-00003` **sent** | 25 | 120 (30 days × 4 types) |
| Globex Industries (`globex`) | Starter / monthly | 3 → `INV-GLOBEX-00001`,`-00002` paid, `-00003` sent | 25 | 120 |
| Stark Industries (`stark`) | Enterprise / yearly | 3 → `INV-STARK-00001`,`-00002` paid, `-00003` sent | 25 | 120 |

## 3. Test Surface Inventory

- **Onboarding wizard (public, no login):**
  - Start: [`onboarding/`](apps/tenants/urls.py#L8)
  - Company: [`onboarding/company/`](apps/tenants/urls.py#L9)
  - Plan: [`onboarding/plan/`](apps/tenants/urls.py#L10)
  - Complete: [`onboarding/complete/`](apps/tenants/urls.py#L11)
- **Plans** — list/detail unguarded; create/edit/delete = **super-admin only**:
  - List: [`plans/`](apps/tenants/urls.py#L14) · Create: [`plans/create/`](apps/tenants/urls.py#L15) · Detail: [`plans/<pk>/`](apps/tenants/urls.py#L16) · Edit: [`plans/<pk>/edit/`](apps/tenants/urls.py#L17) · Delete: [`plans/<pk>/delete/`](apps/tenants/urls.py#L18)
- **Subscriptions** (tenant members may view; admin may change/cancel):
  - List: [`subscriptions/`](apps/tenants/urls.py#L21) · Detail: [`subscriptions/<pk>/`](apps/tenants/urls.py#L22) · Change plan: [`subscriptions/change-plan/`](apps/tenants/urls.py#L23) · Cancel: [`subscriptions/<pk>/cancel/`](apps/tenants/urls.py#L24)
- **Invoices & Billing** (members may view; admin may pay):
  - List: [`invoices/`](apps/tenants/urls.py#L27) · Detail: [`invoices/<pk>/`](apps/tenants/urls.py#L28) · Pay: [`invoices/<pk>/pay/`](apps/tenants/urls.py#L29)
- **Tenant isolation settings (tenant admin only):**
  - Branding: [`branding/`](apps/tenants/urls.py#L32) · Security: [`security/`](apps/tenants/urls.py#L35)
- **Monitoring (tenant admin only):**
  - Dashboard: [`monitoring/`](apps/tenants/urls.py#L38) · Audit Logs: [`monitoring/audit-logs/`](apps/tenants/urls.py#L39)

### Permission matrix (from [`apps/core/mixins.py`](apps/core/mixins.py))

| Page group | Mixin | Anonymous | Member (tenant, not admin) | Tenant admin | Super-admin (`admin`, no tenant) |
|---|---|---|---|---|---|
| Onboarding | none | ✅ loads | ✅ | ✅ | ✅ |
| Plans list/detail | none | ✅ loads | ✅ | ✅ | ✅ |
| Plans create/edit/delete | `SuperAdminRequiredMixin` | → login | **403** | **403** | ✅ |
| Subscriptions list/detail, Invoices list/detail | `TenantRequiredMixin` | → login | ✅ (own tenant) | ✅ | → **onboarding** (no tenant) |
| Branding, Security, Monitoring, Audit logs, Pay, Cancel, Change-plan | `TenantAdminRequiredMixin` | → login | → **portal dashboard** + error toast | ✅ | → **onboarding** (no tenant) |

---

## 4. Test Cases

### 4.1 Authentication & Access

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-AUTH-01 | Public onboarding | Logged out | Visit `/tenants/onboarding/` | — | Onboarding start page renders. **No** redirect to `/accounts/login/`. | | |
| TC-AUTH-02 | Authenticated, no tenant → onboarding | Logged in as super-admin `admin` (tenant=None) | Visit `/tenants/invoices/` | — | Redirected to `/tenants/onboarding/` (the wizard), **not** to the login page. `TenantRequiredMixin.handle_no_permission`. | | |
| TC-AUTH-03 | Member blocked from Security | Logged in as a tenant **member** | Navigate to `/tenants/security/` | — | Redirected to **portal dashboard** with red error toast: **"Tenant admin permission required to access that page."** (Not a 403.) | | |
| TC-AUTH-04 | Member blocked from Branding | Logged in as a tenant **member** | Navigate to `/tenants/branding/` | — | Same as TC-AUTH-03 — redirect to portal dashboard + the tenant-admin error toast. | | |
| TC-AUTH-05 | Member blocked from Plan CRUD (403) | Logged in as a tenant member | Navigate to `/tenants/plans/create/` | — | **403 Forbidden** (PermissionDenied) — `SuperAdminRequiredMixin` raises for any authenticated non-superuser. | | |
| TC-AUTH-06 | Anonymous → login on guarded page | Logged out | Navigate to `/tenants/invoices/` | — | Redirected to `/accounts/login/?next=/tenants/invoices/`. | | |

### 4.2 Multi-Tenancy Isolation (IDOR)

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-TENANT-01 | Super-admin on tenant pages vs Plans | Logged in as `admin` (tenant=None) | 1. Visit `/tenants/invoices/`<br>2. Visit `/tenants/plans/` | — | (1) Redirected to **onboarding** (no tenant). (2) Plans list **loads** and shows all 4 seeded plans (Free/Starter/Professional/Enterprise). | | Plans list has no tenant guard; invoice list does. |
| TC-TENANT-02 | Cross-tenant invoice **detail** | Logged in as `admin_acme` | 1. As `admin_globex`, open a Globex invoice and note its `<pk>` (URL).<br>2. Back as `admin_acme`, visit `/tenants/invoices/<globex-pk>/` | Globex invoice pk | Redirected to `/tenants/invoices/` with red toast **"Not authorized."** (object exists but tenant check redirects — it is *not* a 404). | | |
| TC-TENANT-03 | Cross-tenant invoice **pay** (404) | Logged in as `admin_acme` | POST to `/tenants/invoices/<globex-pk>/pay/` (e.g. craft via devtools, with CSRF) | Globex invoice pk | **404 Not Found** — the pay view scopes the query by `tenant=request.tenant`, so a foreign pk simply doesn't exist. | | |
| TC-TENANT-04 | Cross-tenant subscription detail | Logged in as `admin_acme` | Visit `/tenants/subscriptions/<globex-sub-pk>/` | Globex sub pk | Redirected to `/tenants/subscriptions/` with **"Not authorized."** toast. | | |
| TC-TENANT-05 | Audit log isolation | Logged in as `admin_acme` | Navigate to Monitoring → Audit Logs | — | Only Acme audit rows appear (~25). No Globex/Stark events. | | |

### 4.3 CREATE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-CREATE-01 | Onboarding — full flow | Logged out | 1. `/tenants/onboarding/` → click through to Company step<br>2. Fill company form, submit<br>3. Pick a plan + billing cycle, submit<br>4. Land on **Review & confirm** page<br>5. Click **Create my workspace** | `Name: Delta Test, Email: d@delta.test` | Step 4 shows a read-only review (company + plan) and creates **nothing** yet (GET is side-effect-free). Step 5 POSTs and renders the "Tenant created!" screen. DB now has a `Tenant`, a **trial** `Subscription` on the **chosen** plan whose `current_period_end == trial_ends_at` (trial window, not a full paid cycle), plus default `BrandingSettings` + `SecuritySettings` and a `tenant.trial_started` audit row. | | Creation is POST-only now. **No user account** is created — you cannot log into the new tenant. |
| TC-CREATE-02 | Onboarding — validation error | Logged out | 1. Visit `/tenants/onboarding/company/`<br>2. Clear **Name**, submit | Name blank | Form re-renders on the Company step with a "This field is required." error under Name. No tenant created. | | `name` is the only hard-required field. |
| TC-CREATE-03 | Onboarding — skip-ahead guard | Logged out (fresh session) | Visit `/tenants/onboarding/plan/` directly without doing the Company step | — | Redirected back to `/tenants/onboarding/company/` (session has no `onboarding_company`). | | |
| TC-CREATE-04 | Super-admin create Plan | Logged in as `admin` | 1. `/tenants/plans/` → **+ New plan**<br>2. Fill form, Save | `Name: Custom, Slug: custom, Monthly: 5, Yearly: 50` | Redirect to Plans list, green toast **"Plan \"Custom\" created."**, new row visible. | | |
| TC-CREATE-05 | Duplicate Plan slug | Logged in as `admin` | **+ New plan** → use slug `starter`, Save | `Slug: starter` | Form validation error ("Plan with this Slug already exists."), **not** a 500. Stays on form. | | `slug` is unique. |

### 4.4 READ — List Pages

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-LIST-01 | Invoices list | Logged in as `admin_acme` | Navigate to `/tenants/invoices/` | — | 3 Acme invoices shown (`INV-ACME-00001..3`). Columns: Number, Tenant, Plan, Status, Issued, Due, Total, Actions. No literal `None` text. | | |
| TC-LIST-02 | Subscriptions list | Logged in as `admin_acme` | Navigate to `/tenants/subscriptions/` | — | Acme's subscription(s) listed; Status badge **green** ("Active"). | | |
| TC-LIST-03 | Plans list | Logged in as `admin` | Navigate to `/tenants/plans/` | — | 4 plans, ordered by `sort_order` (Free, Starter, Professional, Enterprise). | | |

### 4.5 READ — Detail Pages

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DETAIL-01 | Invoice detail (line items + payments) | Logged in as `admin_acme` | Open `INV-ACME-00001` | — | Shows Billed-to (Acme), Plan, line-items table, Subtotal/Tax/Total, and a **Payment history** sidebar with a `succeeded` transaction (green badge, `mock_seed_…` ref). Status badge **green PAID**. | | |
| TC-DETAIL-02 | Plan limits sidebar | Logged in as `admin_acme` | `/tenants/subscriptions/` → open the active sub | — | "Plan limits" card shows max users / GB storage / vendors / POs-per-month from the plan (Professional: 50 / 50 / 1000 / 5000). | | |
| TC-DETAIL-03 | Unpaid invoice shows Pay button | Logged in as `admin_acme` | Open `INV-ACME-00003` (status **sent**) | — | Yellow **SENT** badge; **"Pay now"** button visible in the header (only renders when status ∉ {paid, void} **and** `is_tenant_admin`). | | |

### 4.6 UPDATE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-EDIT-01 | Update branding colour | Logged in as `admin_acme` | 1. `/tenants/branding/`<br>2. Change Primary colour<br>3. **Save branding** | Primary `#ff0000` | Redirect back with green **"Branding updated."** toast. The "Current preview" swatch now shows the new colour (page re-renders the saved value). A `branding.updated` audit row is added. | | Colour input is a native `<input type=color>`. |
| TC-EDIT-02 | Update security policy | Logged in as `admin_acme` | 1. `/tenants/security/`<br>2. Set password min length = 14<br>3. Save | Min length `14` | Green **"Security policy updated."** toast. A **warning**-level `security.updated` audit row appears in Audit Logs. | | |
| TC-EDIT-03 | Edit Plan (super-admin) | Logged in as `admin` | 1. `/tenants/plans/` → Edit "Starter"<br>2. Change monthly price, Save | Monthly `39.00` | Green **"Plan updated."** toast, list shows new price. | | |

### 4.7 DELETE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DELETE-01 | Delete plan blocked by FK | Logged in as `admin` | `/tenants/plans/` → Delete a plan in use (e.g. Professional — Acme subscribes) → confirm | — | Red toast **"Cannot delete a plan with active subscriptions."** Plan **not** deleted. | | Guarded by `plan.subscriptions.exists()`. |
| TC-DELETE-02 | Delete plan success | Logged in as `admin` | 1. Create a throwaway plan (TC-CREATE-04 "Custom")<br>2. Delete it → confirm | — | Green **"Plan deleted."** toast; row removed. | | |
| TC-DELETE-03 | Delete via GET is a no-op | Logged in as `admin` | Visit `/tenants/plans/<pk>/delete/` directly (GET) | — | Redirects to Plans list, **nothing deleted** (delete is POST-only). | | |

### 4.8 SEARCH

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-SEARCH-01 | Invoice search by number | Logged in as `admin_acme` | `/tenants/invoices/` → search box → Filter | `INV-ACME-00001` | Only the matching row. Search box retains the typed value. | | Matches `number` **or** `tenant.name` (icontains). |
| TC-SEARCH-02 | Audit log search — match | Logged in as `admin_acme` | Audit Logs → search → Filter | `login` | Only rows whose action/message/target contains "login" (e.g. `user.login`, `user.failed_login`). | | |
| TC-SEARCH-03 | Audit log search — no match | Logged in as `admin_acme` | Audit Logs → search → Filter | `XXX_NOTFOUND` | Empty-state row ("No audit events…" / empty table). No error. | | |

### 4.9 PAGINATION

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-PAGE-01 | Audit logs paginate at 30 | Logged in as `admin_acme` | 1. Confirm only **25** logs seeded → **no** pager initially.<br>2. Generate 6+ more events (Save Security/Branding repeatedly — each adds an audit row) → reload Audit Logs | — | Once total > 30, pagination controls appear at the bottom; `paginate_by=30`. | | **Default seed (25) shows no second page** — you must create extra events first. |
| TC-PAGE-02 | List pages below threshold | Logged in as `admin_acme` | Open Invoices / Subscriptions lists | — | No pager (≤ 3 rows; `paginate_by=20`). Confirms pagination only renders when needed. | | |

### 4.10 FILTERS

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-FILTER-01 | Invoice status filter | Logged in as `admin_acme` | `/tenants/invoices/` → Status = **Paid** → Filter | `status=paid` | Only the 2 paid Acme invoices. The dropdown **retains "Paid"** after reload (`request.GET.status == v`). | | Choices: Draft/Sent/Paid/Overdue/Void/Refunded. |
| TC-FILTER-02 | Audit log level filter | Logged in as `admin_acme` | Audit Logs → Level = **Warning** → Filter | `level=warning` | Only warning rows (e.g. `security.updated`, `api.rate_limited`, `user.failed_login`). URL shows `?level=warning`; dropdown retains "Warning". | | Levels: Info/Warning/Error/Critical. |
| TC-FILTER-03 | Subscription status filter | Logged in as `admin_acme` | `/tenants/subscriptions/` → Status = **Active** → Filter | `status=active` | Only active subscriptions; dropdown retains selection. | | Choices: Trial/Active/Past Due/Cancelled/Expired. |

### 4.11 Status Transitions / Custom Actions

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-ACTION-01 | Change plan (assign) | Logged in as `admin_acme` | 1. `/tenants/subscriptions/change-plan/`<br>2. Pick "Starter", Monthly, Save | — | Redirect to the subscription detail. Green toast **"Plan set to Starter. Invoice INV-ACME-000NN issued."** A new **sent** invoice is created and a `subscription.assigned` audit row recorded. | | New invoice status = `sent` (payable). |
| TC-ACTION-02 | Pay invoice (mock gateway) | Logged in as `admin_acme` | 1. Open a **sent** invoice (e.g. `INV-ACME-00003`)<br>2. Click **Pay now**, confirm the JS dialog | — | Status → **PAID** (green). Green toast **"Payment succeeded. Ref: mock_…"**. Payment-history shows a new **Succeeded** transaction. The linked subscription is set to **active**. | | MockGateway always succeeds (`ok=True`). |
| TC-ACTION-03 | Cancel subscription | Logged in as `admin_acme` | 1. Open the active subscription<br>2. Click **Cancel**, confirm "Cancel at period end?" | — | Green toast **"Will cancel at period end."** Detail shows the **"Cancels at period end"** badge; `auto_renew` → No. Status stays Active until period end. | | The UI button cancels at period-end; immediate cancel requires POST `immediate=1` (no button for it). |

### 4.12 Frontend UI / UX

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-UI-01 | Monitoring dashboard charts | Logged in as `admin_acme` | Navigate to `/tenants/monitoring/` | — | Four time-series charts render (Active users, API calls, Storage, Sessions) from 30 days of seeded `HealthMetric` data. No JS console errors. Usage cards + latest audit logs show. | | |
| TC-UI-02 | Invoice badge colours | Logged in as `admin_acme` | View Invoices list | — | **Paid** = green (`badge-soft-success`), **Sent** = yellow (`warning`), **Overdue** = red (`danger`), **Void/Refunded** = grey (`secondary`), **Draft** = blue (`info`). | | Matches [`invoices/list.html`](templates/tenants/invoices/list.html#L50). |
| TC-UI-03 | Pay button hidden when paid | Logged in as `admin_acme` | Open a **paid** invoice (`INV-ACME-00001`) | — | **No "Pay now" button** in header (template hides it for paid/void). Only **Print** shows. | | |

### 4.13 Negative & Edge Cases

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-NEG-01 | Pay an already-paid invoice | Logged in as `admin_acme` | 1. Open a paid invoice (Pay button is hidden).<br>2. Manually POST to `/tenants/invoices/<pk>/pay/` (with CSRF) | — | Redirects to the invoice detail with a blue info toast **"Invoice already paid."** **No** new transaction is created. | | Idempotency guard in `InvoicePayView`. |
| TC-NEG-02 | Invalid security input | Logged in as `admin_acme` | 1. `/tenants/security/`<br>2. Set password min length = `abc` (or `-5`), Save | `abc` | Form rejects with a field error ("Enter a whole number." / "Ensure this value is greater than or equal to…"). **No** save, **no** `security.updated` audit row. | | `password_min_length` is an integer field. |
| TC-NEG-03 | Onboarding complete without session | Logged out (fresh session) | Visit `/tenants/onboarding/complete/` directly | — | Redirected to `/tenants/onboarding/company/` (no `onboarding_company`/`onboarding_plan` in session). No tenant created. | | Prevents half-formed tenants. |

---

## 5. Bug Log

| Bug ID | Test Case ID | Severity | Page URL | Steps to Reproduce | Expected | Actual | Status | Browser |
|---|---|---|---|---|---|---|---|---|
| BUG-01 | TC-UI-01 | High | `/tenants/monitoring/` | Open the monitoring dashboard; the four Chart.js series were injected with `{{ series_*\|safe }}` straight into the `<script>` block. | Chart data passed as JSON via `json_script` + `JSON.parse` (project standard; no XSS surface, no JS console error). | Raw Python `repr` of a list-of-dicts (single-quoted) was emitted into JS — valid-by-accident for seeded floats, but an injection vector and a violation of the repo's own `json_script` rule. | **Fixed** — `templates/tenants/monitoring/dashboard.html` now uses `json_script` for all four series + a `readSeries()` `JSON.parse` helper. | n/a (source) |
| BUG-02 | TC-UI-02 | Low | `/tenants/invoices/<pk>/` | Open a **Draft**/**Void**/**Refunded** invoice detail page and compare the status badge colour to the list page. | Draft = blue (`info`), Void/Refunded = grey (`secondary`) — same map as the list. | Detail badge collapsed Draft/Void/Refunded all to grey (no `info` branch). | **Fixed** — `templates/tenants/invoices/detail.html` badge now mirrors the list's full status→colour map. | n/a (source) |

---

## 6. Sign-off & Release Recommendation

| Section | Total | Pass | Fail | Blocked | Notes |
|---|---|---|---|---|---|
| 4.1 Auth & Access | 6 | | | | |
| 4.2 Multi-Tenancy | 5 | | | | |
| 4.3 CREATE | 5 | | | | |
| 4.4 READ (List) | 3 | | | | |
| 4.5 READ (Detail) | 3 | | | | |
| 4.6 UPDATE | 3 | | | | |
| 4.7 DELETE | 3 | | | | |
| 4.8 SEARCH | 3 | | | | |
| 4.9 PAGINATION | 2 | | | | |
| 4.10 FILTERS | 3 | | | | |
| 4.11 Actions | 3 | | | | |
| 4.12 Frontend UI | 3 | | | | |
| 4.13 Negative/Edge | 3 | | | | |
| **Total** | **45** | | | | |

**Release Recommendation:** `GO-with-fixes` (fixes applied 2026-06-05)
**Rationale:** Source-level audit of all 45 cases found 2 defects — both now fixed and
verified: BUG-01 (High, chart `\|safe` → `json_script`) and BUG-02 (Low, invoice detail
badge colour map). Automated tenants suite: **54 passed**. Permissions, multi-tenant IDOR
redirects/404s, filters, seed counts (3 invoices / 25 audit logs / 120 health metrics per
tenant) all confirmed correct. Remaining Pass/Fail columns need a human click-through for
visual/JS-console items (TC-UI-01 chart render, TC-PAGE-01 timing).
