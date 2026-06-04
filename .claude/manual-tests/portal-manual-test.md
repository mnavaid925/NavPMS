# Portal & Dashboard — Manual Test Plan

> Verified against the live code on 2026-06-04. Where this plan asserts an exact
> string, redirect path, or seeded-data fact, it has been cross-checked against
> `apps/portal/` and the seed commands. See the **Verification Notes** call-outs.

## 1. Scope & Objectives
This manual test plan covers the **User Dashboard & Portal** module (`apps/portal/`). It verifies the functionality of the personalized dashboard widgets, task & alert center (notifications), quick requisition entry, recent activity feed, and self-service reporting.

The primary goals are to validate complete CRUD capabilities across these features, ensure correct status transitions for Quick Requisitions (Draft → Submitted), confirm accurate metric aggregations on the dashboard/reports, and rigorously test user/tenant isolation boundaries (users can only see their own widgets/reports/reqs — enforced at both the **tenant** and the **user** level).

## 2. Pre-Test Setup

Open Windows PowerShell and run the following commands. **Order matters** — tenants must exist before users, and users before portal data.

> **Verification Note — seeding:** `seed_tenants` does **NOT** create any user accounts (it only seeds tenants/subscriptions/invoices/branding). The `admin_acme` login is created by `seed_users`. Running only `seed_tenants` + `seed_portal` leaves you with no one to log in as. Use the three-step sequence below (or the all-in-one `seed_data --flush`).

1. **Re-seed data (three steps, in order):**
   ```powershell
   python manage.py seed_tenants --flush
   python manage.py seed_users
   python manage.py seed_portal --flush
   ```
   *All-in-one alternative (seeds every module, slower):* `python manage.py seed_data --flush`

2. **Start the local server:**
   ```powershell
   python manage.py runserver
   ```
3. **Open browser** to `http://127.0.0.1:8000/`
4. **Login Requirements:**
   - Go to `http://127.0.0.1:8000/accounts/login/`
   - Log in as **Acme Corp Admin**: Username `admin_acme` / Password `Welcome@123`
   - *Note on Superusers:* The seeded `admin` (superuser) has `tenant=None`. Hitting the portal as a superuser redirects to onboarding and shows no module data. This is **by design**. Use `admin_acme` for these tests.

> **Verification Note — what `seed_portal` creates (per user, for ALL three tenants — acme, globex, stark):**
> - **6 dashboard widgets** (Pending Tasks, Pending Approvals, Spend Summary, Alerts, Recent Activity, Quick Links)
> - **5 notifications** — 3 unread (deadline/approval/delivery) + 2 read (system/info). *Only 5 — see TC-PAGE-01.*
> - **5 quick requisitions** — 2 `approved`, 1 `submitted`, 2 `draft`
> - **3 saved reports** — "My spend by category", "Monthly spend trend", "Requisitions by status"
> - Every account (admins + 4 staff per tenant) uses password **`Welcome@123`**. Staff usernames are Faker-generated as `first.last.<slug>` (e.g. `*.acme`). Find the exact names in the `seed_users` console output or at `/admin/`.

## 3. Test Surface Inventory

> **Verification Note — line numbers below are the REAL `apps/portal/urls.py` lines** (the earlier draft was off by +1 on every route).

- **Dashboard:**
  - View: `[portal/](apps/portal/urls.py#L8)`
- **Widgets:**
  - List/Filter: `[portal/widgets/](apps/portal/urls.py#L11)`
  - Create: `[portal/widgets/create/](apps/portal/urls.py#L12)`
  - Edit: `[portal/widgets/<pk>/edit/](apps/portal/urls.py#L13)` · Delete: `[portal/widgets/<pk>/delete/](apps/portal/urls.py#L14)`
- **Notifications:**
  - List/Filter: `[portal/notifications/](apps/portal/urls.py#L17)`
  - Create: `[portal/notifications/create/](apps/portal/urls.py#L18)`
  - Mark All Read: `[portal/notifications/mark-all-read/](apps/portal/urls.py#L19)`
  - Detail: `[portal/notifications/<pk>/](apps/portal/urls.py#L20)` · Edit: `[.../edit/](apps/portal/urls.py#L21)` · Delete: `[.../delete/](apps/portal/urls.py#L22)`
  - Mark Read/Unread (toggle): `[portal/notifications/<pk>/toggle-read/](apps/portal/urls.py#L23)`
- **Quick Requisitions:**
  - List/Filter: `[portal/requisitions/](apps/portal/urls.py#L26)`
  - Create: `[portal/requisitions/create/](apps/portal/urls.py#L27)`
  - Detail: `[portal/requisitions/<pk>/](apps/portal/urls.py#L28)`
  - Edit: `[.../edit/](apps/portal/urls.py#L29)` · Delete: `[.../delete/](apps/portal/urls.py#L30)`
  - Submit: `[.../submit/](apps/portal/urls.py#L31)`
  - Item Add: `[.../items/add/](apps/portal/urls.py#L32)` · Item Delete: `[.../items/<item_pk>/delete/](apps/portal/urls.py#L33)`
- **Activity Feed:**
  - List/Filter: `[portal/activity/](apps/portal/urls.py#L36)`
- **Reports:**
  - List: `[portal/reports/](apps/portal/urls.py#L39)`
  - Create: `[portal/reports/create/](apps/portal/urls.py#L40)`
  - Run/View: `[portal/reports/<pk>/](apps/portal/urls.py#L41)`
  - Edit: `[.../edit/](apps/portal/urls.py#L42)` · Delete: `[.../delete/](apps/portal/urls.py#L43)`

---

## 4. Test Cases

### 4.1 Authentication & Access

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-AUTH-01 | Anonymous redirect | Logged out | 1. Visit `http://127.0.0.1:8000/portal/` | None | Redirects to `/accounts/login/?next=/portal/` | | |
| TC-AUTH-02 | Tenantless redirect | Logged in as `admin` (superuser, no tenant) | 1. Visit `/portal/` | None | Redirects to `/tenants/onboarding/` (there is **no** `/start/` segment) | | |

### 4.2 Multi-Tenancy & Multi-User Isolation

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-TENANT-01 | Cross-tenant Requisition Access | — | 1. Log in as `admin_globex` / `Welcome@123`.<br>2. Open any requisition, note its `pk` from the URL.<br>3. Log out, log in as `admin_acme`.<br>4. Visit `/portal/requisitions/<globex_pk>/` | Globex `pk` | Page returns **404**. (The detail view filters by `tenant` **and** `user`, so cross-tenant access is impossible.) | | |
| TC-TENANT-02 | Cross-user Widget Isolation | Logged in as `admin_acme` | 1. Create a Widget titled "My Links".<br>2. Log out, log in as a seeded `*.acme` **staff** user (`Welcome@123`; get the exact username from `/admin/`).<br>3. Visit `/portal/` | None | The staff user sees only **their own** 6 seeded widgets — `admin_acme`'s "My Links" widget is **absent**. Confirms per-user widget isolation. | | |

### 4.3 CREATE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-CREATE-01 | Add Dashboard Widget | Logged in as `admin_acme` | 1. Navigate to `/portal/widgets/`<br>2. Click **Add widget**<br>3. Select Type "Quick Links", set Title "My Links", select Size **"Small (1/3 width)"**<br>4. Save | Title: `My Links` | Redirects to widget list, success toast `Widget "My Links" added.` Dashboard now includes a "My Links" tile. | | |
| TC-CREATE-02 | Quick Requisition Draft | Logged in as `admin_acme` | 1. Navigate to `/portal/requisitions/`<br>2. Click **New requisition**<br>3. Fill Title, Category, Priority<br>4. Save | Title: `New Laptops`<br>Category: `IT Equipment` | Redirects to Requisition Detail. Number is generated as `QR-ACME-NNNNN`. Status is `Draft`. Toast: `Requisition QR-ACME-NNNNN created. Add items below.` | | |
| TC-CREATE-03 | Add Requisition Item | On Requisition Detail (Draft status) | 1. In the "Line items" form at the bottom, fill Item name, Quantity, Unit, Unit price.<br>2. Click **Add** | Name: `Mouse`<br>Qty: `2`<br>Price: `25.50` | Item appears in table, line total `$51.00`. Header total recalculates to `$51.00` (server-side, on reload). Toast `Item "Mouse" added.` | | |
| TC-CREATE-04 | Save Report Definition | Logged in as `admin_acme` | 1. Navigate to `/portal/reports/`<br>2. Click **New report**<br>3. Fill Name, pick Type "Spend by Category", leave dates empty.<br>4. Save | Name: `Q1 Spend` | Redirects to the Report Detail/Run page. A doughnut chart generates from the last 90 days of seeded data. Toast `Report "Q1 Spend" saved.` | | |

### 4.4 READ — List Page

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-LIST-01 | Default-widget Provisioning | A user with **no** existing widgets (seeded users already have 6; to observe auto-provisioning create a fresh user in `/admin/` assigned to the Acme tenant) | 1. Log in as that user.<br>2. Visit `/portal/` | None | 6 default widgets auto-provision: **Pending Tasks, Pending Approvals, Spend Summary, Alerts, Recent Activity, Quick Links**. | | |
| TC-LIST-02 | Notifications Empty State | User with 0 alerts | 1. Visit `/portal/notifications/` | None | Empty-state row shows exactly `No alerts found.` | | |
| TC-LIST-03 | Activity Feed Logs | Logged in as `admin_acme` | 1. Navigate to `/portal/activity/` | None | Chronological list of the user's actions. Level badges colorize: Info = blue (`badge-soft-info`), Warning = amber/yellow (`badge-soft-warning`). | | |

### 4.5 READ — Detail Page

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DETAIL-01 | Requisition View (locked) | Logged in as `admin_acme` | 1. Open a `Submitted` requisition from `/portal/requisitions/` | None | Detail shows all fields. Actions sidebar shows a lock message — for a submitted req: "This requisition is submitted and can no longer be edited." (text reflects the live status). Edit / Delete / Submit / Add-item form are all hidden. | | |
| TC-DETAIL-02 | Report Chart Rendering | Logged in as `admin_acme` | 1. Open the seeded "My spend by category" report from `/portal/reports/` | None | A `doughnut` chart renders via Chart.js (CDN). The breakdown table lists categories and amounts matching the chart data (both built from the same source rows). | | |

### 4.6 UPDATE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-EDIT-01 | Update Requisition | Logged in as `admin_acme` | 1. Open a `Draft` requisition.<br>2. Click **Edit requisition**.<br>3. Change Title, Save | Title: `Updated Request` | Redirects to detail. Title updated, toast `QR-ACME-NNNNN updated.` | | |
| TC-EDIT-02 | Edit Dashboard Widget | Logged in as `admin_acme` | 1. Navigate to `/portal/widgets/`<br>2. Edit a widget<br>3. Change Size to **"Large (full width)"**, Save<br>4. Visit Dashboard | Size: `Large (full width)` | Redirects to widget list. Toast `Widget updated.` Dashboard renders that widget full width (`col-12`). | | |

### 4.7 DELETE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DELETE-01 | Delete Line Item | On Requisition Detail (Draft) | 1. Click the red **"✕" / remove** button next to a line item.<br>2. Confirm the JS dialog ("Remove this item?") | None | Item is removed. Header total recalculates. Toast `Item removed.` | | |
| TC-DELETE-02 | Delete Draft Requisition | On Requisition Detail (Draft) | 1. Click **Delete** in the Actions sidebar.<br>2. Confirm the JS dialog | None | Redirects to `/portal/requisitions/`. Toast `Requisition QR-ACME-NNNNN deleted.` | | |
| TC-DELETE-03 | Delete Blocked on Non-Draft | Submitted Requisition Detail | 1. Inspect Actions sidebar | None | No **Delete** button is present (only the lock message). (Server also blocks it: a direct POST redirects with `Only draft requisitions can be deleted.`) | | |

### 4.8 SEARCH

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-SEARCH-01 | Requisition Search | Logged in as `admin_acme` | 1. Navigate to `/portal/requisitions/`<br>2. Enter an exact Requisition Number in Search<br>3. Submit | Seeded `QR-ACME-NNNNN` | List filters to exactly 1 matching requisition. (Search spans number / title / vendor name.) | | |
| TC-SEARCH-02 | Activity Feed Search | Logged in as `admin_acme` | 1. Navigate to `/portal/activity/`<br>2. Enter `requisition.created`<br>3. Submit | `requisition.created` | Returns only audit logs whose action/message matches. | | |

### 4.9 PAGINATION

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-PAGE-01 | Notification Pagination | **21+ notifications must exist.** The seeder creates only **5** per user — first create 16+ more via the **New alert** form (page size is 20). | 1. Visit `/portal/notifications/`<br>2. Scroll to bottom, click **Page 2** | None | Page 2 loads the older notifications. `Showing X to Y of Z` updates correctly. | | |

### 4.10 FILTERS

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-FILTER-01 | Requisition Status Filter | Logged in as `admin_acme` | 1. Navigate to `/portal/requisitions/`<br>2. Select "Approved" in the Status filter.<br>3. Click **Filter** | Status: `Approved` | Table shows only Approved requisitions (2 are seeded). The "Approved" choice stays selected after reload. | | |
| TC-FILTER-02 | Notification Filter Retention | Logged in as `admin_acme` | 1. Navigate to `/portal/notifications/`<br>2. Filter by Category = "System"<br>3. Click **Page 2** (if available) | Category: `System` | URL retains `?category=system&page=2`. List stays filtered. (Pagination links re-emit all GET params except `page`.) | | |

### 4.11 Status Transitions / Custom Actions

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-ACTION-01 | Submit Quick Requisition | Draft requisition with ≥1 line item | 1. View Requisition Detail<br>2. Click **Submit for approval** in the sidebar | None | Status → "Submitted". `submitted_at` recorded. An audit log `requisition.submitted` and an `approval` notification are created. Requisition becomes locked. Toast `QR-ACME-NNNNN submitted for approval.` | | |
| TC-ACTION-02 | Toggle Notification Read | Logged in as `admin_acme` | 1. Open an unread Notification Detail (opening it auto-marks read).<br>2. Click **Mark unread**.<br>3. Click **Mark read** | None | Toggles between "Read [time]" and "Unread"; `read_at` clears when unread. Toasts `Alert marked unread.` / `Alert marked read.` | | |
| TC-ACTION-03 | Mark All Read | Unread alerts exist | 1. Navigate to `/portal/notifications/`<br>2. Click **Mark all read** in the header | None | All notifications update to Read. The `{unread} unread` count in the breadcrumb clears and the button disappears. Toast `All alerts marked read.` | | |

### 4.12 Frontend UI / UX

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-UI-01 | Dashboard Unread Counter | Logged in as `admin_acme` | 1. Look at the Dashboard page | None | The hero banner "Unread alerts" number matches the "Alerts" tile's `N unread` (both read the same `unread_count`). *Note: it's plain text, not a styled pill.* | | |
| TC-UI-02 | Form Validation UI (Report) | Creating a Report | 1. Click **New report**<br>2. Leave Name blank and submit | Name: `<blank>` | The form re-renders with an inline "This field is required." under Name; other field values are preserved. | | |

### 4.13 Negative & Edge Cases

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-NEG-01 | Submit Empty Requisition | Draft requisition with 0 items | 1. Click **Submit for approval** | None | Status stays Draft. Red toast: `Add at least one item before submitting.` | | |
| TC-NEG-02 | Item Invalid Quantity | Add item to Draft Req | 1. Enter Name "Pen", Quantity "-5", Unit Price "10".<br>2. Click **Add** | Qty: `-5` | Item is **not** added. Red toast: `Could not add item — check the values.` *(The item-add view redirects with a generic toast — it does NOT render an inline "≥ 0.01" field error. The underlying rule is `MinValueValidator(0.01)` on quantity.)* | | |
| TC-NEG-03 | XSS Prevention (link URL) | Creating a Notification | 1. Navigate to `/portal/notifications/create/`<br>2. Enter `javascript:alert(1)` in the "Link URL" field.<br>3. Save | Link: `javascript:alert(1)` | Save blocked. Inline field error: `Enter a relative path (starting with /) or an http(s):// URL.` | | |
| TC-NEG-04 | Edit via URL Hack | Logged in as `admin_acme` | 1. Get the PK of an `Approved` (or any non-draft) requisition.<br>2. Manually navigate to `/portal/requisitions/<pk>/edit/` | None | Redirects to the detail page with red toast: `Only draft requisitions can be edited.` | | |

---

## 5. Bug Log

| Bug ID | Test Case ID | Severity | Page URL | Steps to Reproduce | Expected | Actual | Screenshot | Browser |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
| | | | | | | | | |

---

## 6. Sign-off & Release Recommendation

| Section | Total | Pass | Fail | Blocked | Notes |
|---|---|---|---|---|---|
| 4.1 Auth & Access | 2 | | | | |
| 4.2 Multi-Tenancy & Multi-User | 2 | | | | |
| 4.3 CREATE | 4 | | | | |
| 4.4 READ (List) | 3 | | | | |
| 4.5 READ (Detail) | 2 | | | | |
| 4.6 UPDATE | 2 | | | | |
| 4.7 DELETE | 3 | | | | |
| 4.8 SEARCH | 2 | | | | |
| 4.9 PAGINATION | 1 | | | | |
| 4.10 FILTERS | 2 | | | | |
| 4.11 Actions | 3 | | | | |
| 4.12 Frontend UI | 2 | | | | |
| 4.13 Negative/Edge | 4 | | | | |

**Release Recommendation:** `[ GO / NO-GO / GO-with-fixes ]`
**Rationale:** __________________________________________________________________
