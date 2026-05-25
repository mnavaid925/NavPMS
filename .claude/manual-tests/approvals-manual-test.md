# Approvals (Module 4) — Manual Test Plan

> Senior Manual QA Engineer click-through script for the **Approval Workflow Engine** at [apps/approvals/](../../apps/approvals/) mounted at `/approvals/`. Every step is browser-executable; no developer required.

---

## 1. Scope & Objectives

| Item | Detail |
|---|---|
| **Module under test** | `apps.approvals` — [apps/approvals/](../../apps/approvals/) |
| **URL prefix** | `/approvals/` ([apps/approvals/urls.py](../../apps/approvals/urls.py)) |
| **Sub-modules covered** | (1) Dynamic Routing Rules, (2) Delegation of Authority, (3) Approval History / Audit Trail, (4) Escalation Management, (5) Mobile Approver Inbox |
| **Primary entities** | `ApprovalRule`, `ApprovalStep`, `ApprovalDelegation`, `ApprovalRequest`, `ApprovalTask`, `ApprovalAction` ([apps/approvals/models.py](../../apps/approvals/models.py)) |
| **Integration boundary** | Requisitions (Module 3) — submitting an approved-routing-eligible requisition spawns an `ApprovalRequest`; completing the chain calls back into `requisitions.services.decide_requisition`. |
| **Objective** | Verify every CRUD page, the multi-step approval workflow engine, delegation hop-resolution, escalation sweep, and the mobile-friendly approver inbox under multi-tenant isolation. |
| **Out of scope** | Email notifications (none in v1), Celery / async escalations (manual `run_escalations` command + lazy inbox sweep only), the Requisition workflow itself (covered by [requisitions-manual-test.md](requisitions-manual-test.md)). |

---

## 2. Pre-Test Setup

> Run these once before starting. Stop on the first failure — do not proceed if seed data does not appear.

### 2.1 Start the dev server (PowerShell)

```powershell
python manage.py runserver
```

Leave this terminal open. Open a second PowerShell window for any extra commands.

### 2.2 Seed demo data (if not already done)

```powershell
python manage.py seed_data
python manage.py seed_approvals
```

The orchestrator `seed_data` creates tenants, users, plans, portal data, and requisitions. `seed_approvals` then:

- Creates two `ApprovalRule`s per tenant: `Standard approval` (priority 100, any amount, single manager step) and `High-value approval (over $1,000)` (priority 50, ≥$1,000, two-step chain).
- Creates one in-window `ApprovalDelegation` per tenant (approver → procurement_manager, ~14 days window).
- Routes every existing `submitted` requisition through the matching rule, creating `ApprovalRequest` + `ApprovalTask` rows.

**Re-seeding** requires `--flush` (per [.claude/CLAUDE.md](../CLAUDE.md) "Seed Command Rules"):

```powershell
python manage.py seed_approvals --flush
```

### 2.3 Login credentials (password `Welcome@123` for all seeded users)

| Username | Role | Tenant | Use for |
|---|---|---|---|
| `admin_acme` | tenant_admin | Acme Corp | Primary tester — full admin pages |
| `admin_globex` | tenant_admin | Globex | Cross-tenant isolation tests |
| `admin_stark` | tenant_admin | Stark Industries | Cross-tenant isolation tests |
| `mgr_acme` *(or any `procurement_manager` in Acme)* | procurement_manager | Acme Corp | Non-admin tenant user (blocked from rule CRUD) |
| `approver_acme` *(or any `approver` role)* | approver | Acme Corp | Owner of delegation + assignee of high-value step-2 |
| `admin` | superuser | **None** | Negative test — sees no tenant data (BY DESIGN) |

> ⚠ **Login URL:** [`http://127.0.0.1:8000/accounts/login/`](http://127.0.0.1:8000/accounts/login/) — do NOT log in as `admin` (superuser, no tenant). See §4.2 for the negative tenant test.
>
> If a user is missing in your DB, run `python manage.py shell` then `from apps.accounts.models import User; User.objects.filter(tenant__slug='acme').values('username','role')` to see what's available.

### 2.4 Expected baseline (per tenant after seed)

| Page | URL | Expected |
|---|---|---|
| Rule list | [`/approvals/rules/`](http://127.0.0.1:8000/approvals/rules/) | 2 rules: Standard (pri 100) + High-value (pri 50) |
| Delegation list | [`/approvals/delegations/`](http://127.0.0.1:8000/approvals/delegations/) | 1 active delegation |
| Request list | [`/approvals/requests/`](http://127.0.0.1:8000/approvals/requests/) | Several requests — one per `submitted` requisition |
| Inbox | [`/approvals/`](http://127.0.0.1:8000/approvals/) | For `mgr_acme`: one or more open tasks. For `admin_acme`: tasks for high-value step 2. |
| History | [`/approvals/history/`](http://127.0.0.1:8000/approvals/history/) | `submitted` + (possibly) `delegated` actions for each routed request |

### 2.5 Browser matrix

| Surface | Viewport | Browser |
|---|---|---|
| **Primary** | 1920×1080 | Chrome desktop |
| **Mobile inbox** (Module 4 sub-module 5) | 375×667 (iPhone SE) | Chrome DevTools device emulation |
| Secondary | 1366×768 | Edge desktop |
| Tablet | 768×1024 | Chrome DevTools |

### 2.6 Reset between major test runs

```powershell
python manage.py seed_approvals --flush
python manage.py seed_requisitions --flush
python manage.py seed_approvals
```

(Re-seeding requisitions first restores the `submitted` records the approval seed routes through.)

---

## 3. Test Surface Inventory

### 3.1 URLs ([apps/approvals/urls.py](../../apps/approvals/urls.py))

| Sub-area | Method | URL pattern | View | Mixin |
|---|---|---|---|---|
| Inbox | GET | `/approvals/` | `InboxView` | `TenantRequiredMixin` |
| Task detail | GET | `/approvals/tasks/<pk>/` | `TaskDetailView` | `TenantRequiredMixin` |
| Task act | POST | `/approvals/tasks/<pk>/act/` | `TaskActView` | `TenantRequiredMixin` |
| Task comment | POST | `/approvals/tasks/<pk>/comment/` | `TaskCommentView` | `TenantRequiredMixin` |
| Rule list | GET | `/approvals/rules/` | `RuleListView` | **`TenantAdminRequiredMixin`** |
| Rule create | GET/POST | `/approvals/rules/create/` | `RuleCreateView` | **`TenantAdminRequiredMixin`** |
| Rule detail | GET | `/approvals/rules/<pk>/` | `RuleDetailView` | **`TenantAdminRequiredMixin`** |
| Rule edit | GET/POST | `/approvals/rules/<pk>/edit/` | `RuleEditView` | **`TenantAdminRequiredMixin`** |
| Rule delete | POST | `/approvals/rules/<pk>/delete/` | `RuleDeleteView` | **`TenantAdminRequiredMixin`** |
| Step add | POST | `/approvals/rules/<pk>/steps/add/` | `StepAddView` | **`TenantAdminRequiredMixin`** |
| Step delete | POST | `/approvals/rules/<pk>/steps/<step_pk>/delete/` | `StepDeleteView` | **`TenantAdminRequiredMixin`** |
| Delegation list | GET | `/approvals/delegations/` | `DelegationListView` | `TenantRequiredMixin` |
| Delegation create | GET/POST | `/approvals/delegations/create/` | `DelegationCreateView` | `TenantRequiredMixin` |
| Delegation edit | GET/POST | `/approvals/delegations/<pk>/edit/` | `DelegationEditView` | `TenantRequiredMixin` *(owner OR admin)* |
| Delegation delete | POST | `/approvals/delegations/<pk>/delete/` | `DelegationDeleteView` | `TenantRequiredMixin` *(owner OR admin)* |
| Request list | GET | `/approvals/requests/` | `RequestListView` | `TenantRequiredMixin` |
| Request detail | GET | `/approvals/requests/<pk>/` | `RequestDetailView` | `TenantRequiredMixin` |
| History | GET | `/approvals/history/` | `HistoryView` | `TenantRequiredMixin` |

### 3.2 Filter / search params (verified from [apps/approvals/views.py](../../apps/approvals/views.py))

| Page | Search (`q=`) | Filters |
|---|---|---|
| Rule list | name, department | `?active=active\|inactive` |
| Request list | requisition number, requisition title | `?status=pending\|approved\|rejected\|cancelled` |
| Delegation list | — | `?active=active\|inactive` (own + admin sees all) |
| History | requisition number, comment text | `?action=submitted\|approved\|rejected\|delegated\|escalated\|commented\|cancelled\|completed` |

### 3.3 Pagination

| Page | `paginate_by` | View line |
|---|---|---|
| Rule list | 20 | [apps/approvals/views.py:34](../../apps/approvals/views.py#L34) |
| Delegation list | 20 | [apps/approvals/views.py:152](../../apps/approvals/views.py#L152) |
| Request list | 20 | [apps/approvals/views.py:254](../../apps/approvals/views.py#L254) |
| History | 40 | [apps/approvals/views.py:414](../../apps/approvals/views.py#L414) |

### 3.4 Action buttons (verified from templates)

| Page | Button | Method | Notes |
|---|---|---|---|
| Rule list ([templates/approvals/rules/list.html:67-74](../../templates/approvals/rules/list.html#L67-L74)) | View / Edit / Delete | GET / GET / **POST** | Delete has confirm dialog and CSRF token |
| Rule detail | Add step (inline form) / Delete step | POST / POST | Step CRUD is inline, not a separate list page |
| Inbox card ([templates/approvals/inbox.html:43-52](../../templates/approvals/inbox.html#L43-L52)) | Review / Approve (one-tap) | GET / POST | Quick-approve does NOT require a comment |
| Task detail ([templates/approvals/task_detail.html:91-104](../../templates/approvals/task_detail.html#L91-L104)) | Approve / Reject | POST | Both submit the same form with `decision=approve\|reject`; comment optional |
| Task detail | Post comment | POST | Records `commented` action without deciding |
| Request detail | View only | GET | No edit/delete on `ApprovalRequest` itself (workflow is engine-driven) |

### 3.5 Workflow state-machine

| Entity | States | Transition trigger |
|---|---|---|
| `ApprovalRequest.status` | `pending → approved` (all tasks approved) `→ rejected` (any task rejected) `→ cancelled` (requisition cancelled) | `act_on_task` and `cancel_approval` in [apps/approvals/services.py](../../apps/approvals/services.py) |
| `ApprovalTask.status` | `pending → approved\|rejected\|escalated\|skipped` | `act_on_task` (approve / reject); rejecting one task `skipped`s the remaining ones |
| Escalation | `pending → escalated` when `due_at < now` | `escalate_overdue()` — runs on inbox load AND via `python manage.py run_escalations` |
| Delegation hop | At `start_approval` time the original approver is swapped for any in-window delegate (one hop only) | `resolve_approver` in [apps/approvals/services.py:57](../../apps/approvals/services.py#L57) |

### 3.6 Permission split (verified)

| Action | Anyone with tenant | Tenant admin only |
|---|---|---|
| Inbox, task detail, task act/comment, request list/detail, history, delegation list | ✔ | — |
| Rule list / create / edit / delete / step add / step delete | — | ✔ |
| Delegation create | ✔ (creates on self) | — |
| Delegation edit / delete | own delegations only | ✔ (any) |
| Task act on someone else's task | — | ✔ (`can_act_on_task` allows tenant admin OR superuser) — message banner shown |

---

## 4. Test Cases

> Tester fills the **Pass/Fail** and **Notes** columns as they go. Step counts inside a cell are written `1. … 2. … 3. …` separated by `<br>` so they render on multiple lines inside the table cell.

### 4.1 Authentication & Access

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-AUTH-01 | Anonymous → login redirect (inbox) | Logged out | 1. Open a fresh incognito window<br>2. Navigate to `http://127.0.0.1:8000/approvals/` | — | Redirected to `/accounts/login/?next=/approvals/`. Login form shown. | | |
| TC-AUTH-02 | Anonymous → login redirect (rules) | Logged out | 1. Navigate to `http://127.0.0.1:8000/approvals/rules/` | — | Redirected to `/accounts/login/?next=/approvals/rules/`. | | |
| TC-AUTH-03 | Authenticated, no tenant → onboarding redirect | Logged in as Django superuser `admin` (no tenant) | 1. Login at `/accounts/login/` as `admin`<br>2. Navigate to `/approvals/` | username `admin` | Redirected to `/tenants/onboarding/` (NOT `/accounts/login/`). Per [apps/core/mixins.py](../../apps/core/mixins.py) two-path redirect. | | |
| TC-AUTH-04 | Tenant admin can open every approvals page | Logged in as `admin_acme` | 1. Visit each URL in §3.1 in turn | — | All pages return HTTP 200, no 403/500. Sidebar **Approvals** group shows active. | | |
| TC-AUTH-05 | Tenant non-admin BLOCKED from rule CRUD | Logged in as any non-admin tenant user (e.g. `andrea.calderon.acme` / `danielle.johnson.acme`) | 1. Navigate to `/approvals/rules/`<br>2. Navigate to `/approvals/rules/create/`<br>3. Navigate to `/approvals/rules/1/edit/` | — | Each request 302 → `/portal/` with a red error toast `Tenant admin permission required to access that page.` User must NOT see the rule list. (Per `TenantAdminRequiredMixin.handle_no_permission` in [apps/core/mixins.py](../../apps/core/mixins.py).) | | |
| TC-AUTH-06 | Tenant non-admin CAN open inbox + delegations | Logged in as `mgr_acme` | 1. Navigate to `/approvals/` (inbox)<br>2. Navigate to `/approvals/delegations/` (own delegations) | — | Both pages render 200. Inbox shows tasks assigned to this user; delegations page shows rows where this user is delegator OR delegate. | | |
| TC-AUTH-07 | CSRF token present on every form | Logged in as `admin_acme` | 1. View source on the rule create page (`/approvals/rules/create/`)<br>2. View source on the task detail decision form (`/approvals/tasks/1/`) | — | Both pages contain `<input type="hidden" name="csrfmiddlewaretoken" value="...">`. | | |

### 4.2 Multi-Tenancy Isolation

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-TENANT-01 | Tenant A cannot see Tenant B rules in list | Acme + Globex both have seed rules | 1. Login as `admin_acme`<br>2. Visit `/approvals/rules/`<br>3. Note the rule names and count | — | List shows ONLY Acme rules (2 rows: Standard + High-value). No Globex rules visible. | | |
| TC-TENANT-02 | Cross-tenant IDOR (rule detail by URL) | Two tenants present | 1. Login as `admin_globex`<br>2. In another tab or via shell, find a Globex rule pk (e.g. `pk=2`)<br>3. Login as `admin_acme`<br>4. Manually visit `/approvals/rules/2/` | Globex rule pk | **404 Not Found** (the `get_object_or_404(..., tenant=request.tenant)` guard kicks in). Must NOT show the Globex rule content. | | |
| TC-TENANT-03 | Cross-tenant IDOR (approval request) | Both tenants have seeded requests | 1. As `admin_globex`, open `/approvals/requests/` and copy a request pk from the URL<br>2. Logout, login as `admin_acme`<br>3. Visit `/approvals/requests/<that pk>/` | Globex request pk | **404 Not Found**. | | |
| TC-TENANT-04 | Cross-tenant IDOR (task act POST) | Both tenants have inbox tasks | 1. As `admin_globex`, find a task pk in their inbox<br>2. Logout, login as `admin_acme`<br>3. Open browser DevTools console and POST to `/approvals/tasks/<globex-pk>/act/` with `decision=approve` (or use Postman) | Globex task pk | **404 Not Found**. The Globex task status MUST remain unchanged when verified back as `admin_globex`. | | |
| TC-TENANT-05 | Superuser sees no tenant data | Superuser `admin` has `tenant=None` | 1. Login as `admin`<br>2. Visit `/approvals/` | — | Redirected to `/tenants/onboarding/` (per TC-AUTH-03) — never reaches the inbox. By design per [.claude/CLAUDE.md](../CLAUDE.md) Multi-Tenancy Rules. | | |
| TC-TENANT-06 | Delegation list filters to user when not admin | Acme has a seeded delegation (approver → mgr) | 1. Login as some tenant user NOT involved in any delegation (or create such user)<br>2. Visit `/approvals/delegations/` | — | List is empty (the seeded delegation does NOT include this user). | | |

### 4.3 CREATE

> Cover: `ApprovalRule`, `ApprovalStep` (inline on rule detail), `ApprovalDelegation`. `ApprovalRequest` and `ApprovalTask` are engine-created — covered in §4.11.

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-CREATE-01 | Create rule with all fields | Logged in as `admin_acme` | 1. Visit `/approvals/rules/`<br>2. Click **+ New rule**<br>3. Fill Name `IT requisitions`, Document type `Requisition`, Description `IT-only routing`, Active=checked, Priority `75`, Min amount `100`, Max amount `5000`, Department `IT`, Category `it`<br>4. Click **Save** | as listed | Green toast: `Rule "IT requisitions" created. Add steps below.` Redirect to `/approvals/rules/<new-pk>/`. Detail page shows 0 steps and the new field values. | | |
| TC-CREATE-02 | Create rule with only required fields | Same | 1. Visit `/approvals/rules/create/`<br>2. Fill Name only (`Catch-all`), leave amounts/department/category blank<br>3. Click **Save** | Name `Catch-all` | Success toast. Detail page shows `Any requisition` under Conditions (rendered via [templates/approvals/rules/list.html:56](../../templates/approvals/rules/list.html#L56)). | | |
| TC-CREATE-03 | Create rule with missing required Name | Same | 1. Visit `/approvals/rules/create/`<br>2. Leave Name blank<br>3. Click **Save** | — | Form re-renders with a red error under Name (`This field is required.`). No record created. | | |
| TC-CREATE-04 | Create rule with min > max amount | Same | 1. Visit `/approvals/rules/create/`<br>2. Fill Name `Bad range`, Min `1000`, Max `500`<br>3. Click **Save** | Min 1000, Max 500 | Form re-renders with red error under Max amount: `Maximum amount must be greater than or equal to the minimum.` No record created. (`ApprovalRuleForm.clean()` in [apps/approvals/forms.py](../../apps/approvals/forms.py).) | | |
| TC-CREATE-05 | Create rule with special chars in Name | Same | 1. Visit `/approvals/rules/create/`<br>2. Fill Name `<script>alert(1)</script> & "ümlaut" 🎉`<br>3. Click **Save** | Name contains XSS payload + unicode + emoji | Saves successfully. List page renders the name escaped (no popup, no console errors). Source shows `&lt;script&gt;`. | | |
| TC-CREATE-06 | Add a step (inline on rule detail) | Rule from TC-CREATE-01 exists | 1. Visit `/approvals/rules/<pk>/`<br>2. In the **Add step** form, fill Order `1`, Name `Manager review`, Approver `mgr_acme`, SLA hours `24`, Escalate to `admin_acme`<br>3. Click **Add step** | as listed | Green toast: `Step "Manager review" added.` Step appears in the steps list with order, approver name, and SLA badge. | | |
| TC-CREATE-07 | Add a second step (multi-step chain) | Step 1 exists on the rule | 1. Same page<br>2. Fill Order `2`, Name `Director sign-off`, Approver `admin_acme`, SLA `48`<br>3. Click **Add step** | as listed | Step 2 appears below step 1 in order. Rule list **Steps** column for this rule now shows `2`. | | |
| TC-CREATE-08 | Add step with non-tenant user blocked at form | Same | 1. Open the Approver dropdown on the Add step form | — | Dropdown contains ONLY active users from the current tenant (Acme). Globex/Stark users NOT listed. (Verified via `tenant=...` filter at [apps/approvals/forms.py:45](../../apps/approvals/forms.py#L45).) | | |
| TC-CREATE-09 | Create delegation — happy path | Logged in as `approver_acme` | 1. Visit `/approvals/delegations/`<br>2. Click **+ New delegation**<br>3. Fill Delegate = `mgr_acme`, Start = today, End = today+30, Reason = `On leave`, Active = checked<br>4. Click **Save** | dates today/+30 | Success toast: `Approval authority delegated to <name>.` Redirect to delegation list. Row visible with status `Active`. | | |
| TC-CREATE-10 | Cannot delegate to self | Logged in as `approver_acme` | 1. Visit `/approvals/delegations/create/`<br>2. Open Delegate dropdown | — | Current user (`approver_acme`) is NOT in the dropdown (excluded via `exclude_user` in [apps/approvals/forms.py:67](../../apps/approvals/forms.py#L67)). | | |
| TC-CREATE-11 | Delegation end before start → form error | Logged in as `approver_acme` | 1. Visit `/approvals/delegations/create/`<br>2. Set Start = today+10, End = today<br>3. Submit | end < start | Form re-renders with red error under End date: `End date cannot be before the start date.` (per `clean` in [apps/approvals/forms.py:71](../../apps/approvals/forms.py#L71)). | | |

### 4.4 READ — List Page

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-LIST-01 | Rule list renders all seeded rules | Logged in as `admin_acme`; seed data loaded | 1. Visit `/approvals/rules/` | — | Two seeded rows visible: `High-value approval (over $1,000)` (pri 50) and `Standard approval` (pri 100). Rows sorted by priority asc. Each row shows priority badge, conditions string, step count, Active badge, and 3 action buttons (View / Edit / Delete). | | |
| TC-LIST-02 | Request list renders routed requests | Logged in as `admin_acme` | 1. Visit `/approvals/requests/` | — | Rows visible — one per submitted Acme requisition. Each row shows requisition number + title, rule name, progress bar (`done/total steps`), status badge (Pending), and naturaltime `Submitted` value. | | |
| TC-LIST-03 | Delegation list shows seeded delegation | Logged in as `admin_acme` | 1. Visit `/approvals/delegations/` | — | 1 row visible (delegator approver_acme → delegate mgr_acme, dates spanning today). Admin sees all delegations in the tenant. | | |
| TC-LIST-04 | History list shows seeded actions | Logged in as `admin_acme` | 1. Visit `/approvals/history/` | — | Multiple rows visible, ordered newest-first. Each row shows timestamp, actor, action display name, requisition number link, and comment (if any). At minimum a `Submitted` row per routed request. | | |
| TC-LIST-05 | Empty state — no rules | Brand-new tenant with no rules | 1. Login as that tenant's admin<br>2. Visit `/approvals/rules/` | — | Table shows empty-state message: `No approval rules. Requisitions fall back to a single admin approve/reject until a rule is added.` New rule button still visible top-right. | | |
| TC-LIST-06 | Empty state — no requests | New tenant, no submitted requisitions | 1. Visit `/approvals/requests/` | — | Empty-state message: `No approval requests yet.` | | |
| TC-LIST-07 | No `None` literals or raw nulls | Any populated list | 1. Visit each list page<br>2. Scan every cell | — | No literal `None` text in any column. Empty values render as `—` or blank. | | |

### 4.5 READ — Detail Page

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DETAIL-01 | Rule detail shows steps + condition summary | Seeded rule with 2 steps | 1. Visit `/approvals/rules/<high-value-pk>/` | — | Header: rule name. Body: description, priority, min/max amount, department/category, Active badge, and the steps table (2 rows: Manager review SLA 24h escalate to admin; Finance/admin sign-off SLA 48h). Add-step form visible at bottom. | | |
| TC-DETAIL-02 | Request detail shows task chain | Routed request from seed | 1. Visit `/approvals/requests/`<br>2. Click any request | — | Page shows: header (req number + title), rule used, current step number, submitted_by, completed_at (or `—` if pending). Tasks table lists every step with assigned user, order, status badge, acted_by/acted_at. Approval history timeline at bottom. | | |
| TC-DETAIL-03 | Task detail shows full requisition snapshot | Any pending task in your inbox | 1. Login as `mgr_acme`<br>2. Visit `/approvals/`<br>3. Click **Review** on a pending card | — | Page shows: req number/title header, requester, category, department, priority, required date, justification, estimated total. Line items table populated. Approval history timeline. Decision form (Approve/Reject) visible in right sidebar IF you are the assignee. | | |
| TC-DETAIL-04 | Task detail — decision form HIDDEN for non-assignee | Approver task assigned to user A; you log in as user B (non-admin) | 1. Login as a tenant user NOT assigned to the task<br>2. Open the task URL directly | — | Decision card NOT shown. Replaced with the muted message `This task is assigned to <name>.` (per [templates/approvals/task_detail.html:108-111](../../templates/approvals/task_detail.html#L108-L111)). | | |
| TC-DETAIL-05 | Task detail — admin sees "acting on behalf of" banner | Logged in as `admin_acme`; task is assigned to someone else | 1. Open `/approvals/tasks/<pk>/` for a task NOT assigned to admin | — | Decision form IS visible (admin can act per `can_act_on_task`). Yellow banner above the form: `You are acting as an administrator on behalf of <user>.` | | |
| TC-DETAIL-06 | History timeline ordering | Request that has been acted on | 1. Open `/approvals/requests/<acted-pk>/` | — | History list shows events oldest-first within the request (per `ordering = ['created_at']` on `ApprovalAction.Meta`). First event is `submitted`. | | |

### 4.6 UPDATE

> The engine-driven entities (`ApprovalRequest`, `ApprovalTask`, `ApprovalAction`) are intentionally **not editable** through the UI — `ApprovalAction` is append-only. Only `ApprovalRule` and `ApprovalDelegation` have edit views.

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-EDIT-01 | Edit rule pre-fills every field | Existing rule | 1. Visit `/approvals/rules/`<br>2. Click the pencil icon on a row | — | Form loads with current values populated in EVERY field (Name, Document type, Description, Active checkbox, Priority, Min/Max amount, Department, Category). | | |
| TC-EDIT-02 | Edit rule save persists | Same form open | 1. Change Priority from `100` to `80`<br>2. Click **Save** | — | Toast: `Rule updated.` Redirect to rule detail. List page shows the rule now at priority `80` and re-sorted relative to others. | | |
| TC-EDIT-03 | Edit rule with blank Name → error preserved | Edit form open | 1. Clear the Name field<br>2. Click **Save** | empty name | Form re-renders with the red error under Name. Other unchanged values are retained in the form (no data loss). | | |
| TC-EDIT-04 | Toggle Active → off propagates to engine | Rule with `is_active=True` | 1. Edit rule<br>2. Uncheck Active<br>3. Save<br>4. Visit `/approvals/rules/`<br>5. Submit a NEW requisition that previously matched this rule | new req that would have matched | Rule list shows `Inactive` badge for this rule. New requisition does NOT spawn an `ApprovalRequest` via this rule (per `matches()` returning False for inactive rules — [apps/approvals/models.py:60](../../apps/approvals/models.py#L60)). | | |
| TC-EDIT-05 | Edit delegation pre-fills + saves | Own delegation as `approver_acme` | 1. Login as `approver_acme`<br>2. `/approvals/delegations/`<br>3. Click pencil on the row<br>4. Change Reason to `Updated reason`<br>5. Save | — | Pre-filled correctly. Saves with toast `Delegation updated.` Reason updated in the list. | | |
| TC-EDIT-06 | Cannot edit someone else's delegation | Logged in as non-admin user who is NOT the delegator | 1. Login as a non-admin user other than the delegator<br>2. Manually navigate to `/approvals/delegations/<other-pk>/edit/` | — | Red toast: `You cannot edit this delegation.` Redirect back to delegation list (per [apps/approvals/views.py:205-207](../../apps/approvals/views.py#L205-L207)). | | |
| TC-EDIT-07 | Admin CAN edit any delegation | Logged in as `admin_acme` | 1. Visit `/approvals/delegations/<any-pk>/edit/` | — | Edit form opens normally. Save works. | | |

### 4.7 DELETE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DELETE-01 | Delete rule confirm dialog | Logged in as `admin_acme` | 1. Visit `/approvals/rules/`<br>2. Click the bin icon on a rule that has NO routed requests (e.g. a freshly-created one from §4.3) | — | Browser confirm dialog: `Delete rule <name>?` Cancel = no-op. | | |
| TC-DELETE-02 | Delete rule confirm OK removes it | Same | 1. Repeat TC-DELETE-01, click **OK** in confirm | — | Toast: `Rule deleted.` Redirect to `/approvals/rules/`. The rule is gone from the list. | | |
| TC-DELETE-03 | Cannot delete rule with routed requests | Seeded rule that has at least one `ApprovalRequest` (e.g. `Standard approval` after seed) | 1. Visit `/approvals/rules/`<br>2. Click bin on the Standard rule, confirm | — | Red toast: `Cannot delete a rule that has routed approval requests.` Rule remains. Redirect to rule detail (per [apps/approvals/views.py:104-108](../../apps/approvals/views.py#L104-L108)). | | |
| TC-DELETE-04 | Delete step inline | Rule with 2+ steps | 1. Visit `/approvals/rules/<pk>/`<br>2. Click the bin icon next to step 2 in the steps list, confirm | — | Toast: `Step removed.` Steps list now shows only step 1. | | |
| TC-DELETE-05 | Delete delegation as owner | Logged in as the delegator | 1. Visit `/approvals/delegations/`<br>2. Click delete on your own row, confirm | — | Toast: `Delegation deleted.` Row gone. | | |
| TC-DELETE-06 | Non-owner non-admin cannot delete delegation | Same setup as TC-EDIT-06 | 1. POST manually to `/approvals/delegations/<other-pk>/delete/` (via Postman, since the bin button is hidden) | — | Red toast: `You cannot delete this delegation.` Row remains. | | |
| TC-DELETE-07 | GET on delete URL is safe | Logged in as admin | 1. Manually navigate (GET) to `/approvals/rules/1/delete/` | — | Redirects to rule list (no deletion — GET handler returns `redirect(rule_list)` per [apps/approvals/views.py:113-114](../../apps/approvals/views.py#L113-L114)). | | |
| TC-DELETE-08 | CSRF token required on delete POST | Logged in | 1. Open browser DevTools<br>2. Run `fetch('/approvals/rules/1/delete/', {method:'POST'})` from console (no CSRF) | — | Response 403 Forbidden. Rule remains. | | |

### 4.8 SEARCH

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-SEARCH-01 | Empty search returns all rules | Logged in as `admin_acme` | 1. Visit `/approvals/rules/`<br>2. Leave search blank<br>3. Click **Filter** | — | Both seeded rules visible. URL: `/approvals/rules/?q=&active=`. | | |
| TC-SEARCH-02 | Search by rule name | Same | 1. Type `high` in Search<br>2. Filter | `high` | Only `High-value approval (over $1,000)` row visible. | | |
| TC-SEARCH-03 | Search is case-insensitive | Same | 1. Type `HIGH` in Search<br>2. Filter | `HIGH` | Same result as TC-SEARCH-02. | | |
| TC-SEARCH-04 | Search by department | Rule created with `department=IT` (from TC-CREATE-01) | 1. Type `IT` in Search | `IT` | Row for `IT requisitions` visible. | | |
| TC-SEARCH-05 | Search trims whitespace | Same | 1. Type `   high   ` (with leading/trailing spaces)<br>2. Filter | `   high   ` | Same result as TC-SEARCH-02 (per `.strip()` at [apps/approvals/views.py:39](../../apps/approvals/views.py#L39)). | | |
| TC-SEARCH-06 | Search no-match shows empty state | Same | 1. Type `zzzzz`<br>2. Filter | `zzzzz` | Table shows the empty-state row (`No approval rules…`). URL query still present. | | |
| TC-SEARCH-07 | Search special chars do NOT 500 | Same | 1. Type `%' OR 1=1 --`<br>2. Filter | SQL-injection-style string | Page renders 200, no rows match, no 500 / no DB error. | | |
| TC-SEARCH-08 | Request search by req number | Logged in as `admin_acme` | 1. Visit `/approvals/requests/`<br>2. Type `REQ-ACME-00001`<br>3. Filter | `REQ-ACME-00001` | Single matching row. | | |
| TC-SEARCH-09 | Request search by req title | Same | 1. Type a word from a known requisition title | e.g. `supplies` | All requests whose req.title contains `supplies` returned. | | |
| TC-SEARCH-10 | History search by comment | History has rows with comments (after acting on tasks) | 1. Visit `/approvals/history/`<br>2. Type a substring of a known comment | known substring | Only rows where the comment OR requisition number matches. | | |

### 4.9 PAGINATION

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-PAGE-01 | Default page size — rule list | Need ≥21 rules — create extras manually if needed | 1. Visit `/approvals/rules/` | — | Exactly 20 rows shown. Pagination nav visible at bottom (page 1 / page 2). | | |
| TC-PAGE-02 | Click page 2 — rule list | Page 1 shows 20 rows | 1. Click page 2 link | — | Remaining rules shown. URL: `/approvals/rules/?page=2`. | | |
| TC-PAGE-03 | Page param invalid | Logged in | 1. Visit `/approvals/rules/?page=abc` | — | Graceful handling — Django's paginator returns last page or 404 cleanly (not a 500). | | |
| TC-PAGE-04 | Page beyond last → graceful | Rule list paginated | 1. Visit `/approvals/rules/?page=999` | — | Django paginator: HTTP 404 `Invalid page (999): That page contains no results` — not a 500. Acceptable. | | |
| TC-PAGE-05 | Filter retained across page click — request list | Need ≥21 pending requests | 1. Visit `/approvals/requests/?status=pending`<br>2. Click page 2 link | — | URL becomes `/approvals/requests/?status=pending&page=2` AND the Status filter dropdown still shows `Pending` selected. (Per [.claude/CLAUDE.md](../CLAUDE.md) Filter Implementation Rules.) | | |
| TC-PAGE-06 | Search retained across page click | Need search results spanning multiple pages | 1. Run a search that returns ≥21 results<br>2. Click page 2 | — | URL preserves `q=...&page=2`. Search box still shows the term. | | |
| TC-PAGE-07 | History page size 40 | Need ≥41 actions | 1. Visit `/approvals/history/` | — | 40 rows on page 1. Pagination shows page 2. | | |

### 4.10 FILTERS

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-FILTER-01 | Rule list — Active filter | Rules mixed active/inactive | 1. Visit `/approvals/rules/`<br>2. Select Status = `Active`<br>3. Filter | — | Only `is_active=True` rows. URL `?active=active`. | | |
| TC-FILTER-02 | Rule list — Inactive filter | Same | 1. Select Status = `Inactive`<br>2. Filter | — | Only `is_active=False` rows. URL `?active=inactive`. | | |
| TC-FILTER-03 | Rule list — All filter | Same | 1. Select Status = `All`<br>2. Filter | — | All rules listed. URL `?active=`. | | |
| TC-FILTER-04 | Request list — status filter populated correctly | Logged in as `admin_acme` | 1. Visit `/approvals/requests/`<br>2. Open the Status dropdown | — | Dropdown shows 4 options matching `ApprovalRequest.STATUS_CHOICES`: Pending, Approved, Rejected, Cancelled. (Per [apps/approvals/views.py:272-274](../../apps/approvals/views.py#L272-L274) the view passes `status_choices`.) | | |
| TC-FILTER-05 | Request list — apply Approved filter | Need at least one approved request (act on one first) | 1. Filter Status = `Approved`<br>2. Filter | — | Only approved requests shown. URL `?status=approved`. | | |
| TC-FILTER-06 | Filter + search combined | Logged in | 1. Visit `/approvals/requests/?q=REQ&status=pending`<br>2. Submit | — | Rows are intersection: pending requests whose req number/title contains `REQ`. Both controls retain their values. | | |
| TC-FILTER-07 | Delegation list — Active filter | Mixed delegations | 1. Visit `/approvals/delegations/`<br>2. Status = `Active`<br>3. Filter | — | Only `is_active=True` rows. | | |
| TC-FILTER-08 | History — action filter | History has multiple action types | 1. Visit `/approvals/history/`<br>2. Select Action = `Approved`<br>3. Filter | — | Only rows whose `action='approved'`. | | |
| TC-FILTER-09 | Filter for zero-result value | Logged in | 1. Visit `/approvals/requests/?status=cancelled` when no cancelled requests exist | — | Empty-state row shown (`No approval requests yet.`). Filter retained. | | |

### 4.11 Status Transitions / Custom Actions

> The heart of Module 4: the workflow engine in [apps/approvals/services.py](../../apps/approvals/services.py). Each test exercises one transition end-to-end and verifies the persisted side effects.

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-ACTION-01 | Submitting a draft requisition routes via matching rule | Logged in as a requisition owner; tenant has the Standard rule active | 1. Create a draft requisition with estimated total ~$200 (below high-value threshold)<br>2. Add a line item<br>3. Click **Submit**<br>4. After redirect, visit `/approvals/requests/` | total $200 → matches Standard | New `ApprovalRequest` row visible — status `Pending`, Rule `Standard approval`, Progress `0/1`. History page shows a `Submitted` action with comment `Routed via rule "Standard approval"`. | | |
| TC-ACTION-02 | High-value requisition routes via high-value rule (priority) | Same | 1. Create + submit a requisition with total ≥$1,000 | total $5,000 → matches BOTH but priority 50 wins | New `ApprovalRequest` uses `High-value approval (over $1,000)` rule. Progress `0/2`. Two `ApprovalTask` rows visible on request detail — step 1 Manager review, step 2 Finance/admin sign-off. | | |
| TC-ACTION-03 | Delegation hop swaps the assignee at routing time | Acme seed delegation: `approver_acme → mgr_acme` is currently in-window. Make the approver of step-1 in some rule = `approver_acme`. | 1. Edit (or create) a rule where step 1's approver = `approver_acme`<br>2. Submit a requisition that matches it<br>3. Open the new approval request detail | — | Step 1's `assigned_to` is `mgr_acme` (the delegate), NOT `approver_acme`. A `Delegated` history event with comment `Routed to delegate mgr_acme` is logged. (Per `resolve_approver` at [apps/approvals/services.py:57](../../apps/approvals/services.py#L57).) | | |
| TC-ACTION-04 | Approve step 1 of a 2-step chain → routes to step 2 | High-value request from TC-ACTION-02 exists; logged in as `mgr_acme` (step 1 approver) | 1. Visit `/approvals/`<br>2. Click **Review** on the card<br>3. Add comment `LGTM`<br>4. Click **Approve** | comment `LGTM` | Toast: `Step approved — routed to the next approver.` Redirect to inbox. Inbox no longer shows this task. Visit `/approvals/requests/<pk>/`: task 1 status `Approved` with comment; task 2 status `Pending` and is the new active step. `ApprovalRequest.current_step` = 2. | | |
| TC-ACTION-05 | Step 2 approval completes the request and approves the requisition | Continued from TC-ACTION-04; logged in as `admin_acme` (step 2 approver) | 1. Visit `/approvals/`<br>2. Open the step 2 task, **Approve**<br>3. Open the underlying requisition (`/requisitions/<pk>/`) | — | Toast: `Approved. <REQ-NUMBER> is fully approved.` Approval request status now `Approved`, `completed_at` set. Two new history events: step 2 `Approved` + `Completed`. The requisition itself has moved from `submitted` to `approved` (per `decide_requisition` callback). | | |
| TC-ACTION-06 | Reject at step 1 short-circuits the whole chain | Fresh high-value request (2 tasks pending); logged in as step 1 approver | 1. Open the task<br>2. Add comment `Out of budget`<br>3. Click **Reject** | comment `Out of budget` | Toast: `Rejected. <REQ-NUMBER> was declined.` Approval request status `Rejected`, `completed_at` set. Task 1 `Rejected`; task 2 transitioned to `Skipped` (per [apps/approvals/services.py:151-153](../../apps/approvals/services.py#L151-L153)). Requisition status now `rejected`. History shows `Rejected` + `Completed`. | | |
| TC-ACTION-07 | Comment-only does NOT decide | Pending task in inbox | 1. Open the task<br>2. In the "Add a comment" panel (right sidebar), type `Need more info`<br>3. Click **Post comment** | comment text | Green toast: `Comment added.` Task status remains `Pending`. New `Commented` event appears in history. Task is still in inbox. | | |
| TC-ACTION-08 | Acting twice on the same task is blocked | Task already approved | 1. Re-open `/approvals/tasks/<pk>/`<br>2. Form is hidden (right sidebar shows "This task was approved by ..." per TC-DETAIL-04 logic)<br>3. Attempt to POST manually: `curl -X POST /approvals/tasks/<pk>/act/ -d "decision=approve" -H "X-CSRFToken: ..."` | — | Red toast: `This task has already been actioned.` Redirect back. No new history event. | | |
| TC-ACTION-09 | Non-assignee, non-admin cannot act | Task assigned to user A; logged in as some user B (non-admin) | 1. POST manually to `/approvals/tasks/<pk>/act/` with `decision=approve` and a valid CSRF token | — | Red toast: `This task is not assigned to you.` Task unchanged. | | |
| TC-ACTION-10 | Empty decision value rejected | Pending task | 1. POST to `/approvals/tasks/<pk>/act/` with `decision=` (empty) or `decision=foo` | — | Red toast: `Choose approve or reject.` No change. | | |
| TC-ACTION-11 | Tenant admin can act on behalf of another user | Task assigned to `mgr_acme`; logged in as `admin_acme` | 1. Open `/approvals/tasks/<that-pk>/`<br>2. Verify the yellow "acting as administrator" banner<br>3. Click **Approve** | — | Action succeeds. Task `acted_by = admin_acme`. History shows `Approved` action by `admin_acme`. Workflow continues. | | |
| TC-ACTION-12 | Lazy escalation sweep escalates an overdue task | A task exists with `due_at` in the past. Easiest setup: in `python manage.py shell`, run `from django.utils import timezone; from datetime import timedelta; from apps.approvals.models import ApprovalTask; t = ApprovalTask.objects.filter(status='pending').first(); t.due_at = timezone.now() - timedelta(hours=1); t.save()` | 1. Login as `admin_acme`<br>2. Visit `/approvals/` (inbox) | — | Blue info toast: `1 overdue task escalated.` Inbox now shows the task with an `Escalated` (yellow) badge instead of `Step N`. Card has yellow border. History page shows an `Escalated` action; `escalate_to` user is the new assignee (if `escalate_to` was set on the step). (Per [apps/approvals/views.py:302-307](../../apps/approvals/views.py#L302-L307) + `escalate_overdue`.) | | |
| TC-ACTION-13 | `run_escalations` management command | Same overdue setup as TC-ACTION-12, in a fresh shell | 1. PowerShell: `python manage.py run_escalations` | — | Stdout shows "Escalated N task(s)" (exact text depends on the command). Verify via `/approvals/history/`. | | |
| TC-ACTION-14 | Cancelling a requisition cancels its in-flight approval | Logged in as `admin_acme`; an approval request exists with `status=pending` | 1. Open the underlying requisition (`/requisitions/<pk>/`)<br>2. POST cancel on the requisition (whatever the requisitions UI provides)<br>3. Open `/approvals/requests/<pk>/` | — | Approval request status now `Cancelled`. All pending tasks set to `Skipped`. History shows `Cancelled` event with comment `Requisition withdrawn`. (Per `cancel_approval` at [apps/approvals/services.py:190](../../apps/approvals/services.py#L190).) | | |
| TC-ACTION-15 | Quick-approve from inbox card | Pending task in your inbox | 1. Visit `/approvals/`<br>2. On a card, click the green **Approve** button (no review) | — | Card disappears. Toast confirms approval. History shows `Approved` action with empty comment (no comment captured by quick-approve form per [templates/approvals/inbox.html:47-51](../../templates/approvals/inbox.html#L47-L51)). | | |
| TC-ACTION-16 | Rule priority order — multiple matching rules | Create a third rule `Priority 10 catch-all` (priority `10`, no conditions) | 1. Submit a $500 requisition that matches both new rule AND Standard rule | — | New approval request uses `Priority 10 catch-all` (lower priority number = higher precedence per `order_by('priority','name')` at [apps/approvals/services.py:46](../../apps/approvals/services.py#L46)). | | |
| TC-ACTION-17 | No matching rule → no approval request | Disable all rules (uncheck Active on each) | 1. Submit a new requisition | — | NO `ApprovalRequest` is created. Requisition goes via the simple admin approve/reject path instead. `/approvals/requests/` does NOT show a new row. | | |
| TC-ACTION-18 | Rule with zero steps is skipped by matcher | Create a rule with conditions but NO steps added | 1. Submit a requisition that would otherwise match | — | The empty-step rule is skipped (per `if rule.matches(req) and rule.steps.exists()` at [apps/approvals/services.py:50](../../apps/approvals/services.py#L50)). Falls through to next priority rule or admin path. | | |

### 4.12 Frontend UI / UX

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-UI-01 | Browser tab title | Each page | 1. Open each list / detail page<br>2. Check the browser tab | — | Titles match: Approval Rules / Approval Requests / My Approvals / Review · <REQ#> / etc. | | |
| TC-UI-02 | Sidebar active state | Logged in | 1. Visit `/approvals/` | — | The **Approvals** group in the sidebar is highlighted/active. | | |
| TC-UI-03 | Breadcrumb on task detail | Pending task | 1. Visit `/approvals/tasks/<pk>/` | — | Breadcrumb reads `My Approvals › <task name> · <REQ#>` with `My Approvals` linking to `/approvals/`. | | |
| TC-UI-04 | Status badge colors | Mixed-status requests | 1. Visit `/approvals/requests/` | — | Approved = green, Pending = yellow/warning, Rejected/Cancelled = red. Per [templates/approvals/requests/list.html:65](../../templates/approvals/requests/list.html#L65). | | |
| TC-UI-05 | Inbox card border — overdue/escalated | Escalated or overdue task in inbox | 1. Visit `/approvals/` after triggering an escalation (TC-ACTION-12) | — | Card has yellow border (`border-warning`). | | |
| TC-UI-06 | Empty inbox state | User with no assigned tasks | 1. Login as a user who has no inbox tasks<br>2. Visit `/approvals/` | — | Friendly empty state: icon + `No approvals waiting on you. You're all caught up.` | | |
| TC-UI-07 | Decision form layout — task detail | Pending task assigned to you | 1. Open task detail | — | Left column: requisition snapshot, line items, history. Right column (or stacked on mobile): big green Approve + big red Reject buttons, comment textarea, "Add a comment" panel. | | |
| TC-UI-08 | Toast auto-dismiss | Any action with a success toast | 1. Trigger any successful action | — | Green toast appears top-right and auto-dismisses after a few seconds (Bootstrap default). | | |
| TC-UI-09 | Confirm dialog names the rule | Rule list delete button | 1. Click delete on a row | — | Dialog: `Delete rule <actual name>?` — uses the rule name, not a generic "this item". | | |
| TC-UI-10 | Required field markers on forms | Form pages | 1. Visit `/approvals/rules/create/`<br>2. Visit `/approvals/delegations/create/` | — | Required fields (`Name`, `Delegate`, `Start date`, `End date`) have visible `*` markers or are flagged. | | |
| TC-UI-11 | Long content wraps cleanly | Rule with very long description (create one) | 1. Visit list and detail | — | No horizontal scroll. Description wraps within the cell/column. | | |
| TC-UI-12 | Mobile inbox 375×667 | DevTools mobile mode | 1. Set viewport to 375×667 (iPhone SE)<br>2. Visit `/approvals/`<br>3. Visit a task detail | — | Inbox cards stack 1-per-row. Action buttons are large/tap-friendly. Task detail: left column stacks above right column (decision form below the snapshot). No content offscreen. | | |
| TC-UI-13 | Tablet view 768×1024 | DevTools tablet | 1. Visit `/approvals/requests/` | — | Table is readable; if too wide it scrolls horizontally inside its card (not the whole page). | | |
| TC-UI-14 | Keyboard navigation | Logged in | 1. On any list page, press Tab repeatedly | — | Focus indicator visible at every tab stop. Order: top nav → sidebar → search → status → Filter button → table action buttons. | | |
| TC-UI-15 | Enter submits search form | Logged in | 1. Visit `/approvals/rules/`<br>2. Type `high` in Search<br>3. Press Enter | — | Form submits — same result as clicking Filter. | | |
| TC-UI-16 | No console errors | Any page | 1. Open DevTools Console<br>2. Visit each major URL in §3.1 | — | Zero red errors. Warnings acceptable but note them. | | |
| TC-UI-17 | Activity timeline icons | Request with mixed actions | 1. Open task detail or request detail | — | Approved/Completed dots are green, Rejected/Cancelled red, Escalated yellow, others default. Per `at-dot is-success/is-danger/is-warning` in [templates/approvals/task_detail.html:66-69](../../templates/approvals/task_detail.html#L66-L69). | | |

### 4.13 Negative & Edge Cases

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-NEG-01 | All required fields blank on rule form | Logged in as admin | 1. Visit `/approvals/rules/create/`<br>2. Click Save without filling anything | — | Name field shows red error (the only required text field; others have defaults). No record created. | | |
| TC-NEG-02 | Decimal fields with letters | Rule create form | 1. Type `abc` in Min amount<br>2. Save | — | Form shows decimal validation error under Min amount. No 500. | | |
| TC-NEG-03 | Negative amounts | Rule create form | 1. Type `-100` in Min amount<br>2. Save | — | Form re-renders with red error under Min amount: `Minimum amount cannot be negative.` Same behaviour for Max amount. No record created. (`clean_min_amount` / `clean_max_amount` in [apps/approvals/forms.py](../../apps/approvals/forms.py).) | | |
| TC-NEG-04 | Date validation on delegation | Delegation form | 1. Type `2026-99-99` in Start date | — | Browser date picker rejects OR form-level validation error. No 500. | | |
| TC-NEG-05 | Double-click rapid submit on rule create | Rule create form | 1. Fill required Name<br>2. Double-click Save fast | — | At most one rule created (subsequent click hits a redirect). Verify in list. If duplicate is created, log as Medium bug. | | |
| TC-NEG-06 | Refresh after POST does not resubmit | After creating a rule | 1. On the redirected detail page, press F5 | — | Browser refreshes the detail GET — no duplicate creation prompt (POST/Redirect/GET pattern). | | |
| TC-NEG-07 | Browser back after create | After creating a rule | 1. Click browser Back arrow | — | Back to the create form (blank or with last input). No POST replay. | | |
| TC-NEG-08 | Approve out-of-order — step 2 before step 1 | High-value request, both tasks pending | 1. Login as `admin_acme` (step 2 approver, also admin-can-act-anywhere)<br>2. Manually navigate to `/approvals/tasks/<step-2-pk>/`<br>3. Click Approve | — | Acts on step 2 first. Workflow then looks for the next pending task — step 1 remains pending and becomes active. Request status stays `Pending`. (The engine processes tasks by `order_by('order')` after each action — verify carefully and log behavior.) **NOTE:** if this completes the request prematurely, log as High bug. | | |
| TC-NEG-09 | Submit a comment-only POST with empty comment | Pending task | 1. POST to `/approvals/tasks/<pk>/comment/` with `comment=`  | — | No-op — no toast, no history event (per `if comment:` guard at [apps/approvals/views.py:401](../../apps/approvals/views.py#L401)). Redirect back to task detail. | | |
| TC-NEG-10 | Delegation with end = start (same day) | Delegation form | 1. Set Start = today, End = today<br>2. Save | — | Saves successfully (per `end < start` check — `==` is allowed). One-day window is valid. | | |
| TC-NEG-11 | Inactive delegation does NOT swap approver | Edit an existing delegation, uncheck Active. Then submit a new requisition that would route through that approver | 1. Toggle delegation Active = off<br>2. Submit a matching requisition | — | Task is assigned to the original approver (not the delegate). `resolve_approver` filters `is_active=True` per [apps/approvals/services.py:62](../../apps/approvals/services.py#L62). | | |
| TC-NEG-12 | Out-of-window delegation does NOT swap | Edit delegation: set Start = today+30, End = today+45 | 1. Submit a matching requisition today | — | Task assigned to original approver (delegation window is future). | | |
| TC-NEG-13 | Acting on a task whose request was cancelled | Approval request that was cancelled (TC-ACTION-14) | 1. Manually open the task detail of one of the now-skipped tasks | — | Decision form NOT shown (task `is_open` is False since status is `skipped`). Page shows "This task was skipped." | | |
| TC-NEG-14 | XSS in step name | Logged in as admin | 1. Create rule, then add step with Name = `<script>alert('xss')</script>` | — | No popup. Step list renders the name escaped. View source: `&lt;script&gt;`. | | |
| TC-NEG-15 | XSS in delegation reason | Logged in | 1. Create delegation with Reason = `<img src=x onerror=alert(1)>` | — | No popup on list/edit pages. Reason rendered as text. | | |
| TC-NEG-16 | Comment length boundary | Pending task | 1. Open task<br>2. Try to type/paste a 1000-character comment into either textarea (decision or "Add a comment") | — | Browser stops typing at exactly 255 characters (per `maxlength="255"` on both `<textarea>` in [templates/approvals/task_detail.html](../../templates/approvals/task_detail.html)). Cannot exceed the `ApprovalTask.comment` / `ApprovalAction.comment` DB column length. | | |
| TC-NEG-17 | Direct POST to step delete on wrong-tenant rule | Logged in as Acme admin | 1. POST to `/approvals/rules/<acme-pk>/steps/<globex-step-pk>/delete/` | mixing tenants | 404 Not Found (per `get_object_or_404(..., rule=rule, tenant=request.tenant)` at [apps/approvals/views.py:135](../../apps/approvals/views.py#L135)). | | |

### 4.14 Cross-Module Integration

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-INT-01 | Submitting a requisition triggers `start_approval` | Logged in as Acme tenant user; Acme has Standard rule active | 1. `/requisitions/` → create draft<br>2. Add ≥1 line item<br>3. Submit<br>4. `/approvals/requests/` | — | New approval request row appears within seconds. (Verifies the requisitions → approvals seam.) | | |
| TC-INT-02 | Approval completion updates requisition status | Walk TC-ACTION-04 + TC-ACTION-05 to completion | 1. Open the requisition `/requisitions/<pk>/` | — | Requisition status badge shows `Approved`. The requisition's history/activity also shows the approval event. | | |
| TC-INT-03 | Approval rejection updates requisition status | Walk TC-ACTION-06 to completion | 1. Open the requisition | — | Requisition status = `Rejected`. | | |
| TC-INT-04 | Inbox card links to requisition detail | Inbox has tasks | 1. On a card, click the bold requisition number (top-left) | — | Navigates to `/requisitions/<pk>/`. | | |
| TC-INT-05 | Requisition cancel cascades into approval cancel | TC-ACTION-14 walked end-to-end | 1. As above | — | Both the requisition AND its approval request show `Cancelled`. | | |
| TC-INT-06 | Step approver dropdown excludes other-tenant users | Logged in as `admin_acme` on Add Step form | 1. Open the dropdown | — | Only Acme active users listed. Cross-checked against `apps.accounts.models.User.objects.filter(tenant=acme, is_active=True)`. | | |

---

## 5. Bug Log

> Add one row per bug found. Severity guide: **Critical** (data loss, security, blocked workflow), **High** (broken core feature), **Medium** (workaround exists), **Low** (form validation gaps, polish), **Cosmetic** (visual only).

| Bug ID | Test Case ID | Severity | Page URL | Steps to Reproduce | Expected | Actual | Screenshot | Browser |
|---|---|---|---|---|---|---|---|---|
| BUG-01 | | | | | | | | |
| BUG-02 | | | | | | | | |
| BUG-03 | | | | | | | | |
| BUG-04 | | | | | | | | |
| BUG-05 | | | | | | | | |

---

## 6. Sign-off & Release Recommendation

| Section | Total | Pass | Fail | Blocked | Notes |
|---|---:|---:|---:|---:|---|
| 4.1 Authentication & Access | 7 | | | | |
| 4.2 Multi-Tenancy Isolation | 6 | | | | |
| 4.3 CREATE | 11 | | | | |
| 4.4 READ — List Page | 7 | | | | |
| 4.5 READ — Detail Page | 6 | | | | |
| 4.6 UPDATE | 7 | | | | |
| 4.7 DELETE | 8 | | | | |
| 4.8 SEARCH | 10 | | | | |
| 4.9 PAGINATION | 7 | | | | |
| 4.10 FILTERS | 9 | | | | |
| 4.11 Status Transitions / Custom Actions | 18 | | | | |
| 4.12 Frontend UI / UX | 17 | | | | |
| 4.13 Negative & Edge Cases | 17 | | | | |
| 4.14 Cross-Module Integration | 6 | | | | |
| **Total** | **136** | | | | |

**Release recommendation:** ☐ GO ☐ NO-GO ☐ GO-with-fixes

**Tester:** _______________ **Date:** _______________

**Rationale (one sentence):**
______________________________________________________________________________

---

> Companion automation skill: [/sqa-review](../skills/sqa-review/SKILL.md). When manual passes are clean and you want a regression suite to lock the behavior in, run it next.
