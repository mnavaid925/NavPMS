# User Dashboard & Portal — Manual Test Plan

> Target: **Module 2 — User Dashboard & Portal** ([apps/portal/](../../apps/portal/)) plus the platform **Dashboard** landing page ([apps/core/views.py](../../apps/core/views.py#L10)).
> Persona: Senior Manual QA Engineer. This is a runnable click-through script — a non-developer can execute every step.

---

## 1. Scope & Objectives

### In scope

| # | Surface | Entry URL | Code |
|---|---|---|---|
| A | Platform Dashboard (KPI landing) | `/` | [apps/core/views.py:10](../../apps/core/views.py#L10), [templates/dashboard/index.html](../../templates/dashboard/index.html) |
| B | Personalized Portal Dashboard (widget grid) | `/portal/` | [apps/portal/views.py:30](../../apps/portal/views.py#L30), [templates/portal/dashboard.html](../../templates/portal/dashboard.html) |
| C | Dashboard Widgets — CRUD | `/portal/widgets/` | [apps/portal/views.py:45](../../apps/portal/views.py#L45) |
| D | Notifications / Task & Alert Center — CRUD + read state | `/portal/notifications/` | [apps/portal/views.py:131](../../apps/portal/views.py#L131) |
| E | Quick Requisitions — CRUD + inline items + submit | `/portal/requisitions/` | [apps/portal/views.py:261](../../apps/portal/views.py#L261) |
| F | Recent Activity Feed — read-only | `/portal/activity/` | [apps/portal/views.py:456](../../apps/portal/views.py#L456) |
| G | Self-Service Reports — CRUD + run | `/portal/reports/` | [apps/portal/views.py:481](../../apps/portal/views.py#L481) |

### Objectives

- Verify CRUD completeness, search, pagination, filters on widgets / notifications / quick requisitions / reports.
- Verify the two dashboards render KPIs/widgets correctly and degrade gracefully with no tenant / no data.
- Verify per-user data isolation: portal records are scoped to **both** `tenant` **and** `user` — a user must not see another user's widgets, alerts, requisitions or reports even inside the same tenant.
- Verify status-gating on quick requisitions (`draft`-only edit/delete/items) and read-state transitions on notifications.

### Out of scope

- The full Requisition Management module (`/requisitions/`) — covered by its own plan.
- Tenant onboarding, billing, user management — separate modules.
- Automated tests — see [.claude/skills/sqa-review/SKILL.md](../skills/sqa-review/SKILL.md).

---

## 2. Pre-Test Setup

Run once before testing.

### 2.1 Start the server (PowerShell)

```powershell
python manage.py runserver
```

### 2.2 Seed demo data

If the portal has no data yet, run **either**:

```powershell
python manage.py seed_portal
```

…or the full orchestrator (also seeds plans, tenants, users, requisitions):

```powershell
python manage.py seed_data
```

To wipe and re-seed between runs:

```powershell
python manage.py seed_data --flush
```

### 2.3 Open the browser

Navigate to `http://127.0.0.1:8000/` → you should be redirected to `http://127.0.0.1:8000/accounts/login/`.

### 2.4 Log in as a tenant admin

> ⚠️ Do **NOT** log in as the Django superuser `admin` — it has `tenant=None` and the portal shows nothing.

Seeded tenant admins (password `Welcome@123` for all):

| Username | Tenant |
|---|---|
| `admin_acme` | Acme Corp |
| `admin_globex` | Globex |
| `admin_stark` | Stark Industries |

Use **`admin_acme`** as the primary test account. You will also need a **second user in the same tenant** for the cross-user isolation tests (TC-TENANT-03/04) — open the Django admin at `/admin/` (as superuser) → **Users** → pick any `*.acme` staff user, and note its username + its records' primary keys.

### 2.5 Verify seed data exists

[apps/portal/management/commands/seed_portal.py](../../apps/portal/management/commands/seed_portal.py) seeds, **per active user per tenant**:

| Entity | Expected count | Notes |
|---|---|---|
| Dashboard widgets | 6 | The default starter set ([apps/portal/services.py:47](../../apps/portal/services.py#L47)) |
| Notifications | 5 | First 3 **unread**, last 2 **read** |
| Quick requisitions | 5 | Statuses: approved, submitted, approved, draft, draft. The last draft ("Printer maintenance kit") has **no items** |
| Saved reports | 3 | spend_by_category, spend_by_month, requisition_status |

Log in as `admin_acme`, open `/portal/` and confirm a widget grid appears; open `/portal/notifications/` and confirm 5 alerts.

### 2.6 Browser / viewport matrix

| Browser | Viewport | Priority |
|---|---|---|
| Chrome | 1920×1080 desktop | Primary |
| Edge | 1920×1080 desktop | Secondary |
| Chrome | 375×667 mobile | Secondary |
| Chrome | 768×1024 tablet | Secondary |

### 2.7 Reset between runs

Created widgets/alerts/requisitions/reports persist. To return to a clean state run `python manage.py seed_data --flush`, or delete the records you created via the UI.

---

## 3. Test Surface Inventory

### 3.1 Pages & URLs

| Surface | List | Create | Detail / Run | Edit | Delete | Custom actions |
|---|---|---|---|---|---|---|
| Platform Dashboard | — | — | `/` | — | — | — |
| Portal Dashboard | — | — | `/portal/` | — | — | — |
| Widgets | `/portal/widgets/` | `/portal/widgets/create/` | *(none)* | `/portal/widgets/<pk>/edit/` | `/portal/widgets/<pk>/delete/` | — |
| Notifications | `/portal/notifications/` | `/portal/notifications/create/` | `/portal/notifications/<pk>/` | `/portal/notifications/<pk>/edit/` | `/portal/notifications/<pk>/delete/` | toggle-read `<pk>/toggle-read/`, mark-all-read `/mark-all-read/` |
| Quick Requisitions | `/portal/requisitions/` | `/portal/requisitions/create/` | `/portal/requisitions/<pk>/` | `/portal/requisitions/<pk>/edit/` | `/portal/requisitions/<pk>/delete/` | submit `<pk>/submit/`, item add/delete |
| Activity Feed | `/portal/activity/` | — | — | — | — | — (read-only) |
| Reports | `/portal/reports/` | `/portal/reports/create/` | `/portal/reports/<pk>/` (run) | `/portal/reports/<pk>/edit/` | `/portal/reports/<pk>/delete/` | run-on-view recompute |

URLs verified in [apps/portal/urls.py](../../apps/portal/urls.py) and [config/urls.py](../../config/urls.py).

### 3.2 Search / filter params per list page

| List page | Search `q=` matches | Filter params | Page size |
|---|---|---|---|
| Widgets | *(no search box)* | `widget_type`, `visible` (`visible`/`hidden`) | 20 |
| Notifications | `title`, `message` | `category`, `priority`, `read` (`unread`/`read`) | 20 |
| Quick Requisitions | `number`, `title`, `vendor_name` | `status`, `category` | 20 |
| Activity Feed | `action`, `message` | `level` (`info`/`warning`/`error`/`critical`) | 30 |
| Reports | `name` | `report_type` | 20 |

### 3.3 Choice values (for badge / dropdown verification)

| Field | Values |
|---|---|
| Widget type | `pending_tasks`, `pending_approvals`, `spend_summary`, `recent_activity`, `notifications`, `quick_requisition`, `my_reports`, `quick_links` |
| Widget size | `small` (col-lg-4), `medium` (col-lg-6), `large` (col-12) |
| Notification category | `deadline`, `approval`, `delivery`, `system`, `info` |
| Notification priority | `low`, `normal`, `high`, `urgent` |
| Quick requisition status | `draft`, `submitted`, `approved`, `rejected`, `cancelled` |
| Quick requisition category | `office_supplies`, `it_equipment`, `services`, `travel`, `maintenance`, `other` |
| Report type | `spend_by_category`, `spend_by_month`, `requisition_status`, `my_activity`, `notification_summary` |

### 3.4 Behaviour notes baked into the test cases

- **All portal views use `TenantRequiredMixin`** ([apps/portal/views.py:10](../../apps/portal/views.py#L10)) — no tenant-admin gating; any tenant user has full access to their own data.
- **Double scoping.** Every portal `get_object_or_404` filters `tenant=request.tenant, user=request.user` — so another user's record returns **404**, not just a different tenant's.
- **Auto-provision widgets.** First visit to `/portal/` calls `ensure_default_widgets` ([apps/portal/services.py:57](../../apps/portal/services.py#L57)) → a brand-new user gets 6 widgets automatically; they never see a truly empty dashboard on first load.
- **Notification detail auto-marks-read.** Opening `/portal/notifications/<pk>/` calls `note.mark_read()` ([apps/portal/views.py:172](../../apps/portal/views.py#L172)) — viewing an unread alert flips it to read.
- **Quick requisition `is_editable`** is `True` only while `status == 'draft'`. Edit / Delete / item add / item delete are all blocked otherwise.
- **Submit requires ≥1 item** ([apps/portal/views.py:390](../../apps/portal/views.py#L390)).
- **Auto numbers.** `QuickRequisition.number` = `QR-<SLUG>-NNNNN`, globally unique ([apps/portal/services.py:17](../../apps/portal/services.py#L17)).
- **Report create → run redirect.** Saving a new report redirects straight to its run page; viewing a run recomputes the result and updates `last_run_at`.
- **No file uploads anywhere in this module.**

---

## 4. Test Cases

> Tester fills the **Pass/Fail** and **Notes** columns. Steps are numbered inside the cell.

### 4.1 Authentication & Access

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-AUTH-01 | Anonymous → portal dashboard redirects to login | Logged out | 1. Open `/portal/` in a fresh/incognito window | — | Redirected to `/accounts/login/?next=/portal/` | | |
| TC-AUTH-02 | Anonymous → platform dashboard redirects to login | Logged out | 1. Open `/` in a fresh window | — | Redirected to `/accounts/login/?next=/` | | |
| TC-AUTH-03 | Anonymous → portal sub-page redirects to login | Logged out | 1. Open `/portal/notifications/` | — | Redirected to `/accounts/login/` | | |
| TC-AUTH-04 | Valid login lands on platform dashboard | Seed data present | 1. Go to `/accounts/login/`<br>2. Enter `admin_acme` / `Welcome@123`<br>3. Click **Sign in** | `admin_acme` / `Welcome@123` | Lands on `/` showing the Dashboard with KPI cards | | |
| TC-AUTH-05 | Authenticated user with NO tenant — portal redirects to onboarding | Log in as a user with no tenant (the superuser `admin`) | 1. Log in as `admin` at `/admin/` then visit `/portal/` | superuser `admin` | Redirected to tenant onboarding (`/tenants/onboarding/...`) — NOT login, NOT a 500 | | |
| TC-AUTH-06 | Authenticated user with NO tenant — platform dashboard shows the no-tenant screen | Logged in as superuser `admin` | 1. Visit `/` | superuser `admin` | Page renders the **"You're signed in without a tenant"** message ([templates/dashboard/index.html:8](../../templates/dashboard/index.html#L8)) — BY DESIGN, no crash | | |
| TC-AUTH-07 | Logout ends the session | Logged in as `admin_acme` | 1. Click the user menu → **Logout**<br>2. Re-open `/portal/` | — | After logout, `/portal/` redirects to `/accounts/login/` | | |

### 4.2 Multi-Tenancy & Multi-User Isolation

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-TENANT-01 | Cross-tenant requisition by URL → 404 | Logged in as `admin_acme`. Note a Globex quick-requisition pk from `/admin/` | 1. Manually visit `/portal/requisitions/<globex-pk>/` | Globex requisition pk | HTTP 404 page — Acme cannot open a Globex record | | |
| TC-TENANT-02 | Cross-tenant notification by URL → 404 | Logged in as `admin_acme`. Note a Globex notification pk | 1. Visit `/portal/notifications/<globex-pk>/` | Globex notification pk | HTTP 404 | | |
| TC-TENANT-03 | Same-tenant, other-user requisition → 404 | Logged in as `admin_acme`. Note a quick-requisition pk that belongs to a **different Acme user** | 1. Visit `/portal/requisitions/<other-acme-user-pk>/` | other Acme user's requisition pk | HTTP 404 — portal records are scoped to `user`, not just `tenant` | | |
| TC-TENANT-04 | Same-tenant, other-user widget edit → 404 | Logged in as `admin_acme`. Note a widget pk owned by another Acme user | 1. Visit `/portal/widgets/<other-user-widget-pk>/edit/` | other Acme user's widget pk | HTTP 404 | | |
| TC-TENANT-05 | List pages show only the logged-in user's data | Two Acme users each have seeded portal data | 1. As `admin_acme` open `/portal/requisitions/`<br>2. Note the visible numbers<br>3. Log in as the other Acme user, open `/portal/requisitions/` | — | The two users see disjoint sets of requisitions — no overlap | | |
| TC-TENANT-06 | Cross-tenant POST delete is rejected | Logged in as `admin_acme`. Note a Globex report pk | 1. Build a POST to `/portal/reports/<globex-pk>/delete/` (e.g. via the form on a Globex record you cannot reach — use browser devtools to fake the action) | Globex report pk | 404 — record not found for this tenant/user; the Globex record still exists | | |

### 4.3 CREATE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-CREATE-01 | Create a widget — all fields | On `/portal/widgets/` | 1. Click **+ Add Widget**<br>2. Select **Widget type** = `Spend Summary`<br>3. Type **Title** = `My Spend`<br>4. Select **Size** = `Medium (1/2 width)`<br>5. Set **Position** = `2`<br>6. Leave **Is visible** checked<br>7. Click **Save** | type=spend_summary, title=My Spend, size=medium, position=2 | Redirect to `/portal/widgets/`; green toast `Widget "My Spend" added.`; the widget appears in the list | | |
| TC-CREATE-02 | Create a notification — required only | On `/portal/notifications/` | 1. Click **+ New Alert**<br>2. Type **Title** = `Test alert`<br>3. Leave category/priority at defaults, message blank<br>4. Click **Save** | title=`Test alert` | Redirect to notification list; toast `Alert created.`; new alert appears, default category **Information**, priority **Normal** | | |
| TC-CREATE-03 | Create a notification — all fields | On `/portal/notifications/` | 1. Click **+ New Alert**<br>2. Title = `Budget review`<br>3. Category = `Approval Required`<br>4. Priority = `Urgent`<br>5. Message = `Please review the Q3 budget.`<br>6. Link URL = `/portal/requisitions/`<br>7. Click **Save** | — | Alert created; in the list it shows an **Approval** category badge and an **Urgent** priority badge | | |
| TC-CREATE-04 | Create a quick requisition | On `/portal/requisitions/` | 1. Click **+ Quick Requisition**<br>2. Title = `New monitors`<br>3. Category = `IT Equipment`<br>4. Priority = `High`<br>5. Vendor name = `TechMart`<br>6. Needed by = a date next week<br>7. Click **Save** | title=`New monitors` | Redirect to the new requisition's detail page; toast `Requisition QR-ACME-000NN created. Add items below.`; an auto number `QR-ACME-…` is shown; status badge = **Draft** | | |
| TC-CREATE-05 | Create a saved report | On `/portal/reports/` | 1. Click **+ New Report**<br>2. Name = `Q3 spend`<br>3. Report type = `Spend by Category`<br>4. Date from = 90 days ago, Date to = today<br>5. Click **Save** | name=`Q3 spend` | Toast `Report "Q3 spend" saved.`; redirect straight to the **run** page `/portal/reports/<pk>/` showing a computed chart | | |
| TC-CREATE-06 | Create a quick requisition — required field missing | On the create form | 1. Click **+ Quick Requisition**<br>2. Leave **Title** blank<br>3. Click **Save** | title empty | Form re-renders; red error under **Title** (`This field is required.`); no record created | | |
| TC-CREATE-07 | Create a widget — required field missing | On the widget create form | 1. Click **+ Add Widget**<br>2. Leave **Title** blank, leave **Widget type** unselected<br>3. Click **Save** | empty form | Form re-renders with red errors under **Widget type** and **Title**; no widget created | | |
| TC-CREATE-08 | Special chars render escaped (XSS check) | On the notification create form | 1. Create an alert with Title = `<script>alert(1)</script>` and Message = `& " ' 😀` | XSS payload | Alert saves; on the list/detail the title shows literally as text — no JS alert pops, no broken layout | | |
| TC-CREATE-09 | Max-length title accepted gracefully | On the notification create form | 1. Paste a 160-character string into **Title**<br>2. Save<br>3. Then try a 161-character string | 160 / 161 chars | 160 chars saves cleanly; 161 chars is either blocked by the field `maxlength` or returns a graceful form error — never a 500 or silent truncation | | |
| TC-CREATE-10 | Create report with invalid date range | On the report create form | 1. Name = `Bad range`<br>2. Report type = `Spend by Month`<br>3. Date from = today, Date to = a date last year<br>4. Save | from > to | Report saves (no cross-field validation in `SavedReportForm`); the run page renders with an empty/zero result — no 500. *Note as a candidate UX bug if from>to is silently accepted.* | | |

### 4.4 READ — List Pages

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-LIST-01 | Widgets list renders | Seeded | 1. Open `/portal/widgets/` | — | Table with columns **# / Title / Type / Size / Visibility / Actions**; 6 seeded widgets visible; no `None` literals | | |
| TC-LIST-02 | Notifications list renders | Seeded | 1. Open `/portal/notifications/` | — | Table columns **Alert / Category / Priority / Received / Status / Actions**; 5 alerts; an **unread count** chip shows `3` | | |
| TC-LIST-03 | Quick requisitions list renders | Seeded | 1. Open `/portal/requisitions/` | — | Columns **Number / Title / Category / Priority / Needed by / Status / Actions**; 5 requisitions; status badges colour-coded per status | | |
| TC-LIST-04 | Reports list renders | Seeded | 1. Open `/portal/reports/` | — | Columns **Name / Type / Date range / Last run / Actions**; 3 reports | | |
| TC-LIST-05 | Activity feed renders | Seeded; do some actions first | 1. Open `/portal/activity/` | — | A chronological list of audit entries for the current user; newest first; level shown per row | | |
| TC-LIST-06 | List Actions columns are complete | Seeded | 1. On `/portal/widgets/`, `/portal/notifications/`, `/portal/requisitions/`, `/portal/reports/` inspect the Actions column | — | Widgets: Edit + Delete. Notifications: View + Edit + Toggle-read + Delete. Requisitions: View always; Edit + Delete only on **draft** rows. Reports: Run + Edit + Delete | | |
| TC-LIST-07 | Empty list shows a helpful empty state | A list with zero matching rows | 1. Apply a filter that matches nothing (e.g. `/portal/notifications/?q=zzzzzz`) | — | Friendly empty-state message in the table body (not a blank page, not an error) | | |

### 4.5 READ — Dashboards & Detail Pages

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DETAIL-01 | Platform Dashboard KPIs render | Logged in as `admin_acme` (tenant with seeded subscription/invoices) | 1. Open `/`<br>2. Read the KPI cards | — | Cards show **Active users**, **Pending invites**, **Open invoices**, **Outstanding balance**, **Last payment**, current subscription/plan; numbers are non-`None` | | |
| TC-DETAIL-02 | Platform Dashboard charts render | On `/` | 1. Scroll to the health-metric charts | — | The user-count / API-calls trend charts render (or show an empty-state if no metrics); no console errors | | |
| TC-DETAIL-03 | Platform Dashboard recent activity | On `/` | 1. Scroll to **Recent activity** | — | Up to 10 latest audit entries for the tenant, newest first | | |
| TC-DETAIL-04 | Portal Dashboard auto-provisions widgets for a new user | A user who has **never** opened `/portal/` (create a fresh user or flush) | 1. Log in as that user<br>2. Open `/portal/` | brand-new user | 6 default widgets appear immediately (Pending Tasks, Pending Approvals, Spend Summary, Alerts, Recent Activity, Quick Links) — never a fully empty dashboard | | |
| TC-DETAIL-05 | Portal Dashboard widget content | `admin_acme` has seeded requisitions/alerts | 1. Open `/portal/`<br>2. Read each widget | — | Pending-tasks widget shows draft count; Spend Summary shows approved-spend total; Alerts widget lists unread alerts; counts match the underlying list pages | | |
| TC-DETAIL-06 | Portal Dashboard "Customize widgets" link | On `/portal/` | 1. Click **Customize widgets** (top-right) | — | Navigates to `/portal/widgets/` | | |
| TC-DETAIL-07 | Portal Dashboard empty state when all widgets hidden | On `/portal/widgets/`, set every widget **Is visible** = off | 1. Edit each widget → uncheck **Is visible** → Save<br>2. Open `/portal/` | all hidden | Dashboard shows the empty state **"No widgets on your dashboard yet."** with an **Add widgets** CTA | | |
| TC-DETAIL-08 | Notification detail page | Seeded; pick an **unread** alert | 1. On `/portal/notifications/` click an unread alert title | — | Detail page shows title, category, priority, message, received time | | |
| TC-DETAIL-09 | Viewing a notification auto-marks it read | Pick an **unread** alert; note the unread count | 1. Open that alert's detail page<br>2. Return to `/portal/notifications/` | — | The alert now shows **Read** status; the unread-count chip dropped by 1 | | |
| TC-DETAIL-10 | Quick requisition detail page | Seeded | 1. Open a seeded requisition's detail page | — | Header info, the items table, an **Add item** form (draft only), and a sidebar with Submit/Edit/Delete (draft only) | | |
| TC-DETAIL-11 | Report run page computes a result | Seeded reports exist | 1. Open `/portal/reports/` → click the **Run** (▶) icon on "My spend by category" | — | A doughnut/bar chart + a result table render; **Last run** timestamp updates to now | | |
| TC-DETAIL-12 | Each report type renders | Create one report of every type | 1. Create + run a report of each type: spend_by_category, spend_by_month, requisition_status, my_activity, notification_summary | — | Each run page renders a chart + summary without error; empty data → graceful empty result, not a 500 | | |

### 4.6 UPDATE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-EDIT-01 | Edit a widget — fields pre-filled | A widget exists | 1. On `/portal/widgets/` click the **Edit** (✏) icon | — | Form opens with every field pre-filled with the current values | | |
| TC-EDIT-02 | Edit a widget — save persists | On a widget edit form | 1. Change **Title** to `Renamed widget`<br>2. Change **Size** to `Large`<br>3. Save | — | Redirect to list; toast `Widget updated.`; the row shows the new title and size | | |
| TC-EDIT-03 | Edit a notification — save persists | A notification exists | 1. Open `/portal/notifications/<pk>/edit/`<br>2. Change Priority to `Low`, edit the message<br>3. Save | — | Toast `Alert updated.`; list reflects the new priority badge | | |
| TC-EDIT-04 | Edit a draft quick requisition | A **draft** requisition exists | 1. Open it → click **Edit**<br>2. Change Title and Vendor name<br>3. Save | — | Toast `QR-… updated.`; detail page shows new values | | |
| TC-EDIT-05 | Edit a non-draft quick requisition is blocked (UI) | A **submitted/approved** requisition exists | 1. Open its detail page | — | No **Edit** button is shown in the sidebar (gated by `is_editable`) | | |
| TC-EDIT-06 | Edit a non-draft quick requisition is blocked (direct URL) | A submitted requisition, pk known | 1. Manually visit `/portal/requisitions/<submitted-pk>/edit/` | — | Redirect to the detail page with error toast `Only draft requisitions can be edited.` | | |
| TC-EDIT-07 | Edit a report — save persists & re-runs | A report exists | 1. Open `/portal/reports/<pk>/edit/`<br>2. Rename it, change the date range<br>3. Save | — | Toast `Report updated.`; redirect to the run page; chart reflects the new date window | | |
| TC-EDIT-08 | Edit with invalid data keeps original | On a widget edit form | 1. Clear the **Title** field<br>2. Save | title empty | Form re-renders with a red error; the original title is NOT lost from the DB (cancel → list still shows the old title) | | |

### 4.7 DELETE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DELETE-01 | Delete a widget — confirm dialog | A widget exists | 1. On `/portal/widgets/` click the **Delete** (🗑) icon | — | A JS confirm dialog appears reading `Remove this widget?` | | |
| TC-DELETE-02 | Delete a widget — cancel does nothing | Confirm dialog from TC-DELETE-01 open | 1. Click **Cancel** in the dialog | — | Dialog closes; widget still present; nothing changed | | |
| TC-DELETE-03 | Delete a widget — confirm removes it | A widget exists | 1. Click **Delete** → **OK** | — | Redirect to list; toast `Widget removed.`; row gone | | |
| TC-DELETE-04 | Delete a notification | An alert exists | 1. Click the **Delete** icon → confirm `Delete this alert?` → **OK** | — | Toast `Alert deleted.`; row gone | | |
| TC-DELETE-05 | Delete a draft quick requisition | A **draft** requisition | 1. Open it → sidebar **Delete** → confirm `Delete requisition QR-…?` → **OK** | — | Toast `Requisition QR-… deleted.`; redirect to the requisition list; row gone | | |
| TC-DELETE-06 | Delete a non-draft quick requisition is blocked | A **submitted** requisition, pk known | 1. Manually POST to `/portal/requisitions/<submitted-pk>/delete/` (or confirm no Delete button is shown) | — | No Delete button on a non-draft; direct POST → error toast `Only draft requisitions can be deleted.`, record kept | | |
| TC-DELETE-07 | Delete a report | A report exists | 1. Click the **Delete** icon → confirm `Delete this report?` → **OK** | — | Toast `Report deleted.`; redirect to report list; row gone | | |
| TC-DELETE-08 | Delete via GET is a no-op | Any delete URL | 1. Paste a delete URL directly in the address bar, e.g. `/portal/widgets/<pk>/delete/` (a GET) | — | No deletion; redirected back to the relevant list page — record still present | | |

### 4.8 SEARCH

> Widgets list has **no search box** — N/A for widgets. Search applies to Notifications, Quick Requisitions, Activity Feed, Reports.

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-SEARCH-01 | Empty search returns all | On `/portal/notifications/` | 1. Clear the search box, submit | empty `q` | All alerts shown — no filter applied | | |
| TC-SEARCH-02 | Search notification by title | Seeded alerts | 1. Type `Welcome` into the notifications search → submit | `Welcome` | Only the "Welcome to the User Portal" alert is listed | | |
| TC-SEARCH-03 | Search notification by message text | Seeded alerts | 1. Search `manager decision` | `manager decision` | The "Approval required: IT Equipment" alert (its message) is returned | | |
| TC-SEARCH-04 | Search is case-insensitive | Seeded alerts | 1. Search `welcome` (lowercase) | `welcome` | Same result as TC-SEARCH-02 | | |
| TC-SEARCH-05 | Search trims whitespace | Seeded alerts | 1. Search `  Welcome  ` (leading/trailing spaces) | `  Welcome  ` | Same result as TC-SEARCH-02 | | |
| TC-SEARCH-06 | Search quick requisition by number | Seeded requisitions | 1. On `/portal/requisitions/` search a partial number e.g. `QR-ACME` | `QR-ACME` | All of the user's requisitions matching that number fragment listed | | |
| TC-SEARCH-07 | Search quick requisition by vendor | Seeded requisitions (vendors are randomized) | 1. Search a vendor name shown in the list, e.g. `TechMart` | `TechMart` | Only requisitions with that vendor listed | | |
| TC-SEARCH-08 | Search report by name | Seeded reports | 1. On `/portal/reports/` search `spend` | `spend` | "My spend by category" and "Monthly spend trend" listed | | |
| TC-SEARCH-09 | Search activity feed | Activity exists | 1. On `/portal/activity/` search `requisition` | `requisition` | Only audit entries whose action/message contains it listed | | |
| TC-SEARCH-10 | No-match search → empty state | Any searchable list | 1. Search `zzzzzzz` | `zzzzzzz` | Empty-state message; no rows; no error | | |
| TC-SEARCH-11 | Special chars in search do not 500 | Any searchable list | 1. Search `%`, then `_`, then `'` | `%` `_` `'` | Each returns gracefully (likely empty) — no 500 | | |
| TC-SEARCH-12 | Search persists across pagination | A search returning >20 rows (create extra alerts) | 1. Search a common term → go to page 2 | — | URL keeps `?q=…&page=2`; page 2 still filtered by the search term | | |

### 4.9 PAGINATION

> Page size: 20 for widgets/notifications/requisitions/reports; **30** for the activity feed. Seed data is below one page, so create extra records first.

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-PAGE-01 | Default page size = 20 | Create 25+ notifications | 1. Open `/portal/notifications/` | 25 alerts | Exactly 20 rows on page 1; a pager appears | | |
| TC-PAGE-02 | Navigate to page 2 | From TC-PAGE-01 | 1. Click **2** / **Next** in the pager | — | The remaining rows show on page 2; URL has `?page=2` | | |
| TC-PAGE-03 | Activity feed page size = 30 | Create 35+ audit entries (do many actions) | 1. Open `/portal/activity/` | 35 entries | 30 rows on page 1, rest on page 2 | | |
| TC-PAGE-04 | Page beyond last → graceful | Paginated list | 1. Manually visit `?page=9999` | `page=9999` | Django returns the last page or a clean 404 — never a 500 / stack trace | | |
| TC-PAGE-05 | Invalid page param → graceful | Paginated list | 1. Visit `?page=abc` | `page=abc` | Graceful handling (page 1 or clean 404), no 500 | | |
| TC-PAGE-06 | Filter retained across pages | >20 notifications, mixed categories | 1. Filter Category = `Approval Required`<br>2. Go to page 2 | — | URL keeps `?category=approval&page=2`; page 2 still category-filtered | | |
| TC-PAGE-07 | Search retained across pages | >20 matching rows | 1. Search a common term → page 2 | — | `?q=…&page=2` preserved; results still filtered | | |
| TC-PAGE-08 | "Showing X of Y" text accurate | Paginated list | 1. Read the count/summary text on page 1 and page 2 | — | The shown range matches the actual rows on that page (if the template renders such text) | | |

### 4.10 FILTERS

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-FILTER-01 | Widget — filter by type | Seeded widgets | 1. On `/portal/widgets/` set **Widget type** = `Spend Summary` → **Filter** | — | Only spend_summary widgets listed | | |
| TC-FILTER-02 | Widget — filter by visibility | Some widgets hidden | 1. Set **Visibility** = `Hidden` → Filter | — | Only `is_visible=False` widgets listed; switch to `Visible` → only visible ones | | |
| TC-FILTER-03 | Widget — filter selection retained | After TC-FILTER-01 | 1. Observe the **Widget type** dropdown after Filter | — | Dropdown still shows `Spend Summary` selected | | |
| TC-FILTER-04 | Notification — filter by category | Seeded alerts span categories | 1. Set Category = `Approval Required` → Filter | — | Only `approval` alerts listed | | |
| TC-FILTER-05 | Notification — filter by priority | Seeded alerts | 1. Set Priority = `Urgent` → Filter | — | Only `urgent` alerts listed | | |
| TC-FILTER-06 | Notification — filter by read state | 3 unread + 2 read seeded | 1. Set Read = `Unread` → Filter; then `Read` | — | `Unread` → 3 rows; `Read` → 2 rows | | |
| TC-FILTER-07 | Notification — combined filters AND-correctly | Seeded alerts | 1. Set Category = `Approval Required` **and** Priority = `Urgent` → Filter | — | Only alerts matching **both** are listed | | |
| TC-FILTER-08 | Notification — filter + search combine | Seeded alerts | 1. Search `requisition` + Category = `Deadline` → Filter | — | Result narrowed by both `q` and category | | |
| TC-FILTER-09 | Quick requisition — filter by status | Seeded requisitions span statuses | 1. On `/portal/requisitions/` set Status = `Draft` → Filter | — | Only draft requisitions listed | | |
| TC-FILTER-10 | Quick requisition — filter by category | Seeded requisitions | 1. Set Category = `IT Equipment` → Filter | — | Only `it_equipment` requisitions listed | | |
| TC-FILTER-11 | Quick requisition — combined filters | Seeded requisitions | 1. Status = `Approved` **and** Category = `Services` → Filter | — | Only requisitions matching both listed | | |
| TC-FILTER-12 | Activity feed — filter by level | Activity exists | 1. On `/portal/activity/` set Level = `Info` → Filter | — | Only `info`-level entries listed | | |
| TC-FILTER-13 | Report — filter by type | Seeded reports | 1. On `/portal/reports/` set Report type = `Spend by Category` → Filter | — | Only spend_by_category reports listed | | |
| TC-FILTER-14 | Clear filters returns full list | Any filtered list | 1. Reset all dropdowns to the blank option / remove query params → Filter | — | Full unfiltered list returns | | |
| TC-FILTER-15 | Filter for a value with zero rows → empty state | Any list | 1. Filter by a status/category with no records (e.g. requisition Status = `Cancelled`) | — | Empty-state message; no rows; no error | | |

### 4.11 Status Transitions / Custom Actions

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-ACTION-01 | Add an item to a draft requisition | A **draft** requisition open | 1. In the **Add item** form: Name = `A4 paper ream`, Quantity = `10`, Unit = `ream`, Unit price = `4.50`<br>2. Click **Add** | — | Toast `Item "A4 paper ream" added.`; item appears in the table; the requisition's **estimated total** recalculates to `45.00` | | |
| TC-ACTION-02 | Remove an item from a draft requisition | Draft requisition with ≥1 item | 1. Click the item's **remove** (✕) → confirm `Remove this item?` → OK | — | Toast `Item removed.`; row gone; total recalculated | | |
| TC-ACTION-03 | Submit a draft requisition with items | Draft requisition with ≥1 item | 1. Open it → sidebar **Submit for approval** → submit | — | Toast `QR-… submitted for approval.`; status badge changes to **Submitted**; Edit/Delete/Add-item controls disappear | | |
| TC-ACTION-04 | Submit a draft requisition with NO items is blocked | The seeded empty draft "Printer maintenance kit" | 1. Open it → click **Submit for approval** | — | Error toast `Add at least one item before submitting.`; status stays **Draft** | | |
| TC-ACTION-05 | Re-submitting an already-submitted requisition | A **submitted** requisition, submit URL known | 1. POST to `/portal/requisitions/<submitted-pk>/submit/` | — | Info toast `Requisition is already submitted.`; no state change, no 500 | | |
| TC-ACTION-06 | Submitting creates a notification | A draft with items | 1. Submit it (TC-ACTION-03)<br>2. Open `/portal/notifications/` | — | A new alert `Requisition QR-… submitted` (category **Approval**) appears for the user | | |
| TC-ACTION-07 | Toggle a notification read → unread | A **read** alert | 1. On the list click the **Toggle read** (✓) icon on a read alert | — | Info toast `Alert marked unread.`; status flips to **Unread**; unread count +1 | | |
| TC-ACTION-08 | Toggle a notification unread → read | An **unread** alert | 1. Click **Toggle read** on an unread alert | — | Toast `Alert marked read.`; status flips to **Read**; unread count −1 | | |
| TC-ACTION-09 | Mark all alerts read | ≥1 unread alert | 1. Click **Mark all read** (top of the notification list) → confirm if prompted | — | Toast `All alerts marked read.`; every row shows **Read**; unread count = `0` | | |
| TC-ACTION-10 | Running a report updates Last run | A report exists | 1. Note the report's **Last run** value<br>2. Click **Run** (▶)<br>3. Return to `/portal/reports/` | — | The **Last run** timestamp updates to the current time | | |

### 4.12 Frontend UI / UX

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-UI-01 | Browser tab titles | Logged in | 1. Open `/` then `/portal/` and read the tab | — | `/` tab = `Dashboard`; `/portal/` tab = `My Portal` | | |
| TC-UI-02 | Sidebar active link highlight | On each portal page | 1. Visit widgets / notifications / requisitions / reports / activity | — | The sidebar highlights the matching nav item on each page | | |
| TC-UI-03 | Breadcrumb trail | On any portal sub-page | 1. Read the breadcrumb on `/portal/widgets/`, `/portal/notifications/`, etc. | — | Breadcrumb starts at **My Portal** and names the current page | | |
| TC-UI-04 | Status / priority badges colour-coded | Seeded data | 1. Inspect badges on the notification & requisition lists | — | Each status/priority badge uses a distinct colour matching its choice value; no badge shows a raw code like `it_equipment` | | |
| TC-UI-05 | Widget size column correct | Widgets of each size exist | 1. On `/portal/widgets/` read the **Size** column<br>2. On `/portal/` confirm the grid widths | — | small = 1/3 width, medium = 1/2, large = full — grid matches `col_class` | | |
| TC-UI-06 | Toasts auto-dismiss | After any create/edit | 1. Trigger a success toast and wait | — | Toast disappears after a few seconds (or is dismissible) | | |
| TC-UI-07 | Confirm dialogs name the entity | On delete actions | 1. Trigger delete on a requisition | — | Confirm text includes the requisition number, e.g. `Delete requisition QR-ACME-00012?` | | |
| TC-UI-08 | Form errors show under the field | Submit an invalid form | 1. Submit the widget create form empty | — | Errors render in red directly under each offending field | | |
| TC-UI-09 | Long text wraps cleanly | Create an alert with a very long title/message | 1. View it in the list and detail | — | Text wraps; no horizontal scrollbar / overflow | | |
| TC-UI-10 | Mobile viewport 375×667 | Chrome devtools mobile | 1. Open `/portal/` and each list page at 375px wide | — | Layout is usable; widget grid stacks; no overlap / offscreen content | | |
| TC-UI-11 | Tablet viewport 768×1024 | Chrome devtools tablet | 1. Open the list pages at 768px | — | Tables remain readable / horizontally scrollable; no broken layout | | |
| TC-UI-12 | Keyboard navigation | On a create form | 1. Tab through every field | — | Tab order is logical top-to-bottom; focus ring visible on each field | | |
| TC-UI-13 | No console errors | DevTools Console open | 1. Navigate `/` → `/portal/` → each list/detail/form page | — | No red JS errors in the console on any page (charts included) | | |
| TC-UI-14 | Charts render on the dashboards & report run | Seeded data | 1. View the platform dashboard charts and a report run chart | — | Canvas charts draw without error; legends/labels readable | | |

### 4.13 Negative & Edge Cases

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-NEG-01 | All-blank form shows every error at once | On the quick requisition create form | 1. Leave everything blank → Save | empty | All required-field errors render together; no record created | | |
| TC-NEG-02 | Non-numeric quantity on an item | Draft requisition open | 1. In **Add item** type Quantity = `abc` → Add | qty=`abc` | Graceful error toast `Could not add item — check the values.`; no item created; no 500 | | |
| TC-NEG-03 | Negative unit price on an item | Draft requisition open | 1. Add an item with Unit price = `-5` | price=`-5` | Field `min=0` blocks it, or a graceful form error — no negative line total persisted | | |
| TC-NEG-04 | Negative widget position | Widget create form | 1. Set Position = `-1` → Save | position=`-1` | Field `min=0` blocks it / graceful error — no 500 (`position` is a PositiveIntegerField) | | |
| TC-NEG-05 | Invalid date in "Needed by" | Quick requisition form | 1. Type a non-date into **Needed by** (if not using the date picker) | `not-a-date` | Graceful form error; no 500 | | |
| TC-NEG-06 | Double-submit a create form | Create form filled | 1. Click **Save** twice rapidly | — | Only one record created (or a graceful unique-number guard) — no duplicate, no 500 | | |
| TC-NEG-07 | Refresh after POST | Just submitted a create form | 1. After landing on the result page, press F5 | — | No duplicate record created (POST→redirect→GET in effect) | | |
| TC-NEG-08 | Browser back after create | Just created a record | 1. Click browser **Back** to the form | — | Form does not silently resubmit; no extra record | | |
| TC-NEG-09 | Add item to a non-draft requisition (direct POST) | Submitted requisition, pk known | 1. POST to `/portal/requisitions/<submitted-pk>/items/add/` | — | Error toast `Items can only be changed on a draft.`; no item added | | |
| TC-NEG-10 | Open a non-existent record | Logged in | 1. Visit `/portal/notifications/999999/` | pk 999999 | Clean HTTP 404 — no 500 | | |
| TC-NEG-11 | CSRF token present on every form | Logged in | 1. View source of each create/edit/delete/action form | — | A `csrfmiddlewaretoken` hidden input is present in every form | | |
| TC-NEG-12 | Report with no data in the window | A report whose date range has no requisitions | 1. Run such a report | — | Run page renders an empty chart / "no data" state — not a 500 | | |

### 4.14 Cross-Module Integration

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-INT-01 | Creating a quick requisition logs an audit entry | Logged in as `admin_acme` | 1. Create a new quick requisition<br>2. Open `/portal/activity/` | — | A `requisition.created` entry for the new requisition appears in the activity feed | | |
| TC-INT-02 | Submitting a requisition logs an audit entry + notification | A draft with items | 1. Submit it<br>2. Open `/portal/activity/` and `/portal/notifications/` | — | Activity feed has a `requisition.submitted` entry; notifications has a new "submitted" alert (TC-ACTION-06) | | |
| TC-INT-03 | Portal dashboard counts match the list pages | Seeded data | 1. Read the Spend Summary / pending counts on `/portal/`<br>2. Cross-check against `/portal/requisitions/` filtered by status | — | Draft/submitted/approved counts and approved-spend total on the dashboard match the filtered list totals | | |
| TC-INT-04 | "Spend by Category" report matches requisition data | ≥1 approved requisition with items | 1. Run the `spend_by_category` report | — | Report totals equal the sum of `estimated_total` of the user's **approved** requisitions, grouped by category | | |
| TC-INT-05 | "Requisitions by Status" report matches the list | Seeded requisitions | 1. Run the `requisition_status` report<br>2. Compare counts to the requisition list filtered per status | — | Per-status counts in the report equal the list-page counts | | |
| TC-INT-06 | Platform dashboard reflects tenant-level data | `admin_acme` tenant has seeded users/invoices | 1. On `/` read **Active users** and **Open invoices** | — | Values match the Acme tenant's seeded users (`is_active=True`) and open invoices | | |

---

## 5. Bug Log

Fill as you test. Severity: Critical / High / Medium / Low / Cosmetic.

| Bug ID | Test Case ID | Severity | Page URL | Steps to Reproduce | Expected | Actual | Screenshot | Browser |
|---|---|---|---|---|---|---|---|---|
| BUG-01 | | | | | | | | |
| BUG-02 | | | | | | | | |
| BUG-03 | | | | | | | | |
| BUG-04 | | | | | | | | |
| BUG-05 | | | | | | | | |

### Watch-list (likely problem areas to scrutinise)

- **TC-CREATE-10 / TC-NEG-12** — `SavedReportForm` has no `date_from ≤ date_to` validation; a reversed range is silently accepted. Confirm the run page degrades gracefully and decide if reversed ranges should be a form error.
- **TC-DETAIL-09** — auto-mark-read on the notification *detail* view: confirm this is intended (a tester just *peeking* at an alert consumes its unread state).
- **TC-AUTH-05 vs TC-AUTH-06** — the platform Dashboard (`/`) uses `LoginRequiredMixin` only and renders a no-tenant screen, while `/portal/` uses `TenantRequiredMixin` and redirects to onboarding. Verify both behave as described and neither 500s.
- **TC-TENANT-03/04** — per-user scoping (`user=request.user`) is the key isolation guarantee here; a regression would leak one colleague's data to another within the same tenant.

---

## 6. Sign-off & Release Recommendation

| Section | Total | Pass | Fail | Blocked | Notes |
|---|---|---|---|---|---|
| 4.1 Authentication & Access | 7 | | | | |
| 4.2 Multi-Tenancy & Multi-User Isolation | 6 | | | | |
| 4.3 CREATE | 10 | | | | |
| 4.4 READ — List Pages | 7 | | | | |
| 4.5 READ — Dashboards & Detail Pages | 12 | | | | |
| 4.6 UPDATE | 8 | | | | |
| 4.7 DELETE | 8 | | | | |
| 4.8 SEARCH | 12 | | | | |
| 4.9 PAGINATION | 8 | | | | |
| 4.10 FILTERS | 15 | | | | |
| 4.11 Status Transitions / Custom Actions | 10 | | | | |
| 4.12 Frontend UI / UX | 14 | | | | |
| 4.13 Negative & Edge Cases | 12 | | | | |
| 4.14 Cross-Module Integration | 6 | | | | |
| **Total** | **135** | | | | |

**Release Recommendation:** `GO` / `NO-GO` / `GO-with-fixes` — ☐

**Rationale (tester to complete):** _______________________________________________

**Tested by:** ____________________  **Date:** ____________  **Build / commit:** ____________
