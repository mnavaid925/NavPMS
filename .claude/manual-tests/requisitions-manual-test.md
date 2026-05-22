# Requisition Management (Module 3) — Manual Test Plan

> Senior Manual QA click-through script. Every step names the exact URL, button, field, and expected on-screen text. A non-developer tester can run this start-to-finish in a browser. Fill the **Pass/Fail** and **Notes** columns as you go; log defects in §5.

---

## 1. Scope & Objectives

| Item | Detail |
|---|---|
| **Module under test** | `apps/requisitions/` — Account Codes, Requisition Templates, Requisitions, Tracking Board, Workflow actions |
| **Scope mode** | Module test (full CRUD + workflow across every page in the app) |
| **URL prefix** | `/requisitions/` — see [apps/requisitions/urls.py](apps/requisitions/urls.py) |
| **Objective** | Verify CRUD, search, pagination, filters, status workflow, multi-tenant isolation, permission boundaries, and UI/UX for Module 3 |
| **Primary browser** | Chrome desktop 1920×1080. Secondary: Edge, and mobile viewport 375×667 |
| **Out of scope** | Module 4 Approval Workflow Engine internals (`apps/approvals/`) — only its touch-point on the requisition detail page is checked |

**Pages covered:** Account Code list/create/edit/delete · Template list/create/detail/edit/delete/use + line add/delete · Requisition list/create/detail/edit/delete + line add/delete · Tracking board · Submit/Decide/Cancel/Amend/Convert workflow actions.

### 1.1 Execution Summary (auto-run 2026-05-23)

**60 of 145 test cases were executed automatically** against the real view code using Django's test client (auth, multi-tenancy, CRUD, search, pagination, filters, workflow, negative paths). The remaining 85 require a human in a browser (UI/UX rendering, responsive layouts, console errors, confirm dialogs, visual badges) and are left for the manual tester.

| Result | Count |
|---|---|
| ✅ Auto-executed & **PASS** | 60 |
| ❌ Auto-executed & FAIL | 0 *(1 found, fixed, re-verified — see BUG-01)* |
| ⏳ Manual execution required | 85 |

**1 defect found and fixed during this run** — `BUG-01` (duplicate account code → 500). Fix applied to [apps/requisitions/forms.py](apps/requisitions/forms.py) + [apps/requisitions/views.py](apps/requisitions/views.py); TC-CREATE-08 re-run → PASS. See §5.

**Auto-executed & PASS (60):** TC-AUTH-01·02·03·04·05 · TC-TENANT-01·02·03·04 · TC-CREATE-01·02·03·04·05·06·07·08·09·10·11·12 · TC-LIST-01·09·10 · TC-DETAIL-01 · TC-EDIT-01·02·04 · TC-DELETE-03·05·07·11 · TC-SEARCH-01·02·05·06·08·09 · TC-PAGE-01·05·06 · TC-FILTER-02·03·05·06·07 · TC-ACTION-01·02·03·05·06·07·08·09·10 · TC-UI-08 · TC-NEG-01·04·10·12.

The auto-run used a throwaway harness driving Django's test client; it re-seeded with `seed_requisitions --flush` for a deterministic baseline and was removed afterwards. Re-run any case manually in a browser to confirm the on-screen UX.

---

## 2. Pre-Test Setup

Run these once before testing. **Windows PowerShell** — commands use `;`, never `&&`.

### 2.1 Start the server
```powershell
cd c:\xampp\htdocs\NavPMS
python manage.py runserver
```
Leave this window running. The app is at `http://127.0.0.1:8000/`.

### 2.2 Seed demo data (only if the module is empty)
```powershell
python manage.py seed_requisitions
```
To wipe and re-seed between full test runs (per CLAUDE.md Seed Command Rules):
```powershell
python manage.py seed_requisitions --flush
```
> The full orchestrator is `python manage.py seed_data` (runs `seed_plans → seed_tenants → seed_users → seed_portal → seed_requisitions`). Use `seed_requisitions` alone for this module.

### 2.3 Log in as a TENANT ADMIN (not the superuser)
1. Open `http://127.0.0.1:8000/accounts/login/`
2. Log in with one of these seeded tenant admins (password **`Welcome@123`**):

| Username | Tenant |
|---|---|
| `admin_acme` | Acme Corp |
| `admin_globex` | Globex |
| `admin_stark` | Stark Industries |

> ⚠️ **Do NOT log in as `admin`.** The Django superuser has `tenant=None` and will see no requisition data — this is BY DESIGN ([apps/core/mixins.py](apps/core/mixins.py)). Use a tenant admin.

### 2.4 Verify seed data exists
Log in as `admin_acme`, open `http://127.0.0.1:8000/requisitions/` and confirm — per [seed_requisitions.py](apps/requisitions/management/commands/seed_requisitions.py) — **per tenant**:

| Entity | Expected count | Notes |
|---|---|---|
| Account codes | 5 | `6100-OFF`, `6200-IT`, `6300-SVC`, `6400-TRV`, `6500-MNT` |
| Templates | 2 | "Monthly office restock", "New-hire IT kit" (both shared) |
| Requisitions | 6 | One per status: draft, submitted, approved, converted, rejected, cancelled |

### 2.5 Reset between runs
Re-run `seed_requisitions --flush` to restore the baseline. Manually delete any draft requisitions / account codes you created during testing if not doing a full flush.

---

## 3. Test Surface Inventory

### 3.1 Routes — [apps/requisitions/urls.py](apps/requisitions/urls.py)

| Page | URL | View | Access |
|---|---|---|---|
| Account code list | `/requisitions/account-codes/` | `AccountCodeListView` | **Tenant admin only** |
| Account code create | `/requisitions/account-codes/create/` | `AccountCodeCreateView` | Tenant admin only |
| Account code edit | `/requisitions/account-codes/<pk>/edit/` | `AccountCodeEditView` | Tenant admin only |
| Account code delete | `/requisitions/account-codes/<pk>/delete/` | `AccountCodeDeleteView` (POST) | Tenant admin only |
| Template list | `/requisitions/templates/` | `TemplateListView` | Any tenant user |
| Template create | `/requisitions/templates/create/` | `TemplateCreateView` | Any tenant user |
| Template detail | `/requisitions/templates/<pk>/` | `TemplateDetailView` | Any tenant user (owner or shared) |
| Template edit | `/requisitions/templates/<pk>/edit/` | `TemplateEditView` | Owner or tenant admin |
| Template delete | `/requisitions/templates/<pk>/delete/` | `TemplateDeleteView` (POST) | Owner or tenant admin |
| Template use | `/requisitions/templates/<pk>/use/` | `TemplateUseView` (POST) | Any tenant user |
| Template line add | `/requisitions/templates/<pk>/lines/add/` | `TemplateLineAddView` (POST) | Owner or tenant admin |
| Template line delete | `/requisitions/templates/<pk>/lines/<line_pk>/delete/` | `TemplateLineDeleteView` (POST) | Owner or tenant admin |
| Tracking board | `/requisitions/tracking/` | `RequisitionTrackingView` | Any tenant user |
| Requisition list | `/requisitions/` | `RequisitionListView` | Any tenant user |
| Requisition create | `/requisitions/create/` | `RequisitionCreateView` | Any tenant user |
| Requisition detail | `/requisitions/<pk>/` | `RequisitionDetailView` | Any tenant user |
| Requisition edit | `/requisitions/<pk>/edit/` | `RequisitionEditView` | Requester / admin, draft only |
| Requisition delete | `/requisitions/<pk>/delete/` | `RequisitionDeleteView` (POST) | Requester / admin, draft only |
| Requisition line add | `/requisitions/<pk>/lines/add/` | `RequisitionLineAddView` (POST) | Requester / admin, draft only |
| Requisition line delete | `/requisitions/<pk>/lines/<line_pk>/delete/` | `RequisitionLineDeleteView` (POST) | Requester / admin, draft only |
| Submit | `/requisitions/<pk>/submit/` | `RequisitionSubmitView` (POST) | Requester / admin, draft + ≥1 line |
| Decide (approve/reject) | `/requisitions/<pk>/decide/` | `RequisitionDecideView` (POST) | **Tenant admin only**, submitted |
| Cancel | `/requisitions/<pk>/cancel/` | `RequisitionCancelView` (POST) | Requester / admin, draft/submitted/approved |
| Amend | `/requisitions/<pk>/amend/` | `RequisitionAmendView` (POST) | Requester / admin, submitted/approved |
| Convert to PO | `/requisitions/<pk>/convert/` | `RequisitionConvertView` (POST) | **Tenant admin only**, approved |

> **Note:** Account codes have **no detail page** — the list links straight to Edit. Templates list has **no Edit/Delete in the Actions column** — those live on the template detail page.

### 3.2 Filters, search, pagination

| List page | Search `q` covers | Filters | Page size |
|---|---|---|---|
| Requisitions | `number`, `title`, `department` | `status`, `category`, `scope` (`mine`) | 20 ([views.py:292](apps/requisitions/views.py#L292)) |
| Account codes | `code`, `name` | `active` (`active`/`inactive`) | 20 ([views.py:43](apps/requisitions/views.py#L43)) |
| Templates | `name`, `description` | `category` | 20 ([views.py:122](apps/requisitions/views.py#L122)) |

### 3.3 Status model — [apps/requisitions/models.py:122-198](apps/requisitions/models.py#L122-L198)

`draft → submitted → approved → rejected → cancelled → converted`

| Property | True when status is | Gates |
|---|---|---|
| `is_editable` | `draft` | Edit, Delete, line add/delete, Submit |
| `can_amend` | `submitted`, `approved` | Amend button |
| `can_cancel` | `draft`, `submitted`, `approved` | Cancel button |

---

## 4. Test Cases

> Steps are numbered inside each cell. Tester fills **Pass/Fail** and **Notes**.

### 4.1 Authentication & Access

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-AUTH-01 | Anonymous user blocked from requisition list | Logged out | 1. Open `http://127.0.0.1:8000/requisitions/` | — | Redirected to `/accounts/login/?next=/requisitions/`; login form shown | | |
| TC-AUTH-02 | Anonymous user blocked from a detail page | Logged out | 1. Open `http://127.0.0.1:8000/requisitions/1/` | — | Redirected to `/accounts/login/` | | |
| TC-AUTH-03 | Valid tenant-admin login | Logged out | 1. Open `/accounts/login/`<br>2. Username `admin_acme`, password `Welcome@123`<br>3. Click **Login** | `admin_acme` / `Welcome@123` | Logged in; dashboard loads; sidebar shows **Requisitions** group | | |
| TC-AUTH-04 | Superuser sees no module data | — | 1. Log in as `admin` (superuser)<br>2. Open `/requisitions/` | superuser `admin` | No requisitions shown / redirected to onboarding — superuser has `tenant=None` (BY DESIGN). Note actual behaviour | | |
| TC-AUTH-05 | Account codes page is tenant-admin only | Logged in as a **non-admin** tenant user | 1. Open `/requisitions/account-codes/` | non-admin tenant user | Access denied / redirect — `AccountCodeListView` uses `TenantAdminRequiredMixin` | | |
| TC-AUTH-06 | Logout ends session | Logged in | 1. Click avatar/menu → **Logout**<br>2. Open `/requisitions/` | — | Back to login page | | |

### 4.2 Multi-Tenancy Isolation

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-TENANT-01 | Acme admin sees only Acme requisitions | Logged in as `admin_acme` | 1. Open `/requisitions/`<br>2. Note the requisition numbers | — | All numbers start `REQ-ACME-…`; ~6 rows; no Globex/Stark data | | |
| TC-TENANT-02 | IDOR — cross-tenant requisition by URL | Logged in as `admin_acme`. Know a Globex requisition pk (log in as `admin_globex` first, open a detail page, note the pk in the URL) | 1. As `admin_acme`, open `/requisitions/<globex-pk>/` | Globex requisition pk | **404 Not Found** — `get_object_or_404(..., tenant=request.tenant)` blocks it | | |
| TC-TENANT-03 | IDOR — cross-tenant account code edit | Logged in as `admin_acme`; know a Globex account-code pk | 1. Open `/requisitions/account-codes/<globex-pk>/edit/` | Globex account code pk | 404 Not Found | | |
| TC-TENANT-04 | IDOR — cross-tenant template detail | Logged in as `admin_acme`; know a Globex template pk | 1. Open `/requisitions/templates/<globex-pk>/` | Globex template pk | 404 Not Found | | |
| TC-TENANT-05 | New requisition is scoped to current tenant | Logged in as `admin_globex` | 1. Create a requisition (see TC-CREATE-01)<br>2. Note its number | — | Number starts `REQ-GLOBEX-…` (or the tenant slug); appears only for Globex users | | |

### 4.3 CREATE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-CREATE-01 | Create requisition — all fields | Logged in as `admin_acme` | 1. Open `/requisitions/`<br>2. Click **New requisition** (top-right)<br>3. Title `Reception area supplies`<br>4. Category `Office Supplies`<br>5. Department `Operations`<br>6. Priority `High`<br>7. Required date = 2 weeks out<br>8. Justification `Stock running low`<br>9. Notes `Deliver to front desk`<br>10. Currency `USD`<br>11. Click **Save** | See steps | Green toast `Requisition REQ-ACME-NNNNN created. Add line items below.`; redirected to the new detail page; status badge **Draft** | | |
| TC-CREATE-02 | Create requisition — required fields only | Logged in | 1. **New requisition**<br>2. Title `Minimal req`<br>3. Leave department/justification/notes blank<br>4. **Save** | Title only | Created successfully — only `title` is required; detail page opens | | |
| TC-CREATE-03 | Create requisition — missing title | Logged in | 1. **New requisition**<br>2. Leave Title blank<br>3. **Save** | empty Title | Stays on form; red error under Title (`This field is required.`); no record created | | |
| TC-CREATE-04 | Auto-generated number is unique & increments | After TC-CREATE-01 & 02 | 1. Compare the two requisition numbers | — | Both `REQ-<SLUG>-NNNNN`; second is higher; tester never typed a number | | |
| TC-CREATE-05 | Add line items to a draft | A draft requisition open on its detail page | 1. Scroll to **Line items** card<br>2. In the footer row: Description `Printer toner`, Qty `2`, Unit `unit`, Unit price `78.00`, Account code `6100-OFF`<br>3. Click the **+** button | See steps | Toast `Line item added.`; row appears; **Total** updates to `$156.00` | | |
| TC-CREATE-06 | Line total auto-computes | Line added in TC-CREATE-05 | 1. Read the **Line total** cell | Qty 2 × $78.00 | Line total `$156.00`; estimated_total recalculated ([models.py:238](apps/requisitions/models.py#L238) `RequisitionLine.save`) | | |
| TC-CREATE-07 | Create account code — all fields | Logged in as `admin_acme` | 1. Open `/requisitions/account-codes/`<br>2. Click **New account code**<br>3. Code `7100-MKT`, Name `Marketing & Advertising`, Description `Campaign spend`, Active ✔<br>4. **Save** | See steps | Toast `Account code 7100-MKT created.`; redirected to list; new row visible | | |
| TC-CREATE-08 | Duplicate account-code `code` within tenant | `6100-OFF` already exists for Acme | 1. **New account code**<br>2. Code `6100-OFF`, Name `Dupe test`<br>3. **Save** | code `6100-OFF` | **Clean form-level error** under the Code field: *"An account code with this code already exists."* — no 500 | ✅ Pass (auto, after fix) | Was BUG-01 (500); fixed in [forms.py](apps/requisitions/forms.py#L10) — re-verified PASS |
| TC-CREATE-09 | Create template — all fields | Logged in | 1. Open `/requisitions/templates/`<br>2. Click **New template**<br>3. Name `Quarterly cleaning kit`, Description `Recurring`, Category `Maintenance`, Default account code `6500-MNT`, Shared ✔<br>4. **Save** | See steps | Toast `Template "Quarterly cleaning kit" created. Add lines below.`; redirected to template detail page | | |
| TC-CREATE-10 | Add a template line | Template detail page open (owner) | 1. In **Pre-defined lines** footer: Description `Mop & bucket`, Quantity `2`, Unit `set`, Est. price `15.00`, Account code `6500-MNT`<br>2. Click **Add line** | See steps | Toast `Template line added.`; row appears; Est. total updates | | |
| TC-CREATE-11 | Create requisition from a template | Logged in; template "Monthly office restock" exists | 1. Open `/requisitions/templates/`<br>2. Click the **file-copy** icon in the Actions column of "Monthly office restock" | — | Toast `Requisition REQ-… created from "Monthly office restock".`; new draft requisition opens **with 3 line items pre-filled** | | |
| TC-CREATE-12 | XSS / special chars in title | Logged in | 1. **New requisition**<br>2. Title `<script>alert(1)</script> & "quote" 🚀`<br>3. **Save** | XSS payload | Saved; on the detail page the title renders as **escaped text** — no alert popup, no broken layout | | |
| TC-CREATE-13 | Max-length title (200 chars) | Logged in | 1. **New requisition**<br>2. Paste a 200-char title<br>3. **Save** | 200-char string | Saved without truncation; a >200-char paste is blocked by the input `maxlength` or rejected gracefully | | |

### 4.4 READ — List Page

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-LIST-01 | Requisition list loads | Logged in as `admin_acme` | 1. Open `/requisitions/` | — | Table with columns Number, Title, Requester, Category, Priority, Status, Estimated, Actions; 6 seeded rows; no `None` literals | | |
| TC-LIST-02 | Status badge colors | Requisition list open | 1. Inspect the Status column | — | approved=green, rejected/cancelled=red, submitted=amber, converted=blue, draft=grey ([list.html:87](templates/requisitions/requisitions/list.html#L87)) | | |
| TC-LIST-03 | Priority badge colors | Requisition list open | 1. Inspect the Priority column | — | high/urgent=red, normal=blue, low=grey | | |
| TC-LIST-04 | Revision badge appears on amended req | A requisition with `revision > 1` exists (amend one first — TC-ACTION-07) | 1. Find that row | — | `r2` badge shown next to the number | | |
| TC-LIST-05 | Possible-duplicate icon | A flagged requisition exists | 1. Look for a warning triangle next to a number | — | Amber warning icon with tooltip "Possible duplicate" | | |
| TC-LIST-06 | Actions column — draft row | A draft requisition in the list | 1. Inspect its Actions cell | — | View (eye) + Edit (pencil) + Delete (bin) all shown | | |
| TC-LIST-07 | Actions column — non-draft row | An approved/converted requisition | 1. Inspect its Actions cell | — | **Only View (eye)** shown; Edit & Delete hidden (`is_editable` false) | | |
| TC-LIST-08 | Empty list state | Filter to a status with zero records | 1. Apply Status filter = a value with no rows | — | Single centered row `No requisitions found.` | | |
| TC-LIST-09 | Account code list loads | Logged in as admin | 1. Open `/requisitions/account-codes/` | — | 5 seeded codes; columns Code, Name, Description, Status, Actions | | |
| TC-LIST-10 | Template list loads | Logged in | 1. Open `/requisitions/templates/` | — | 2 seeded templates; columns Name, Category, Owner, Lines, Visibility, Est. total, Actions | | |
| TC-LIST-11 | Templates list shows only owned + shared | Logged in as a non-owner user | 1. Open `/requisitions/templates/` | — | Only templates owned by the user OR `is_shared=True` are listed ([views.py:124](apps/requisitions/views.py#L124)) | | |

### 4.5 READ — Detail Page

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DETAIL-01 | Requisition detail loads | Logged in | 1. Click a requisition number from the list | — | Header shows number + status badge; **Requisition details** card lists every field; **Line items** card; **Status timeline** card | | |
| TC-DETAIL-02 | Status timeline populated | Open a seeded approved/converted requisition | 1. Scroll to **Status timeline** | — | Multiple entries (`Created`, `Submitted`, `Approved`, …) with timestamp + user; dots colored by status | | |
| TC-DETAIL-03 | Line items total matches | Open a requisition with lines | 1. Read **Total** in the Line items header vs the **Summary** card estimated total | — | Both equal; equals sum of line totals | | |
| TC-DETAIL-04 | Decision block shown for decided req | Open a seeded approved requisition | 1. Find the **Decision** row | — | Shows `Approved by <user> (date)` and the decision note | | |
| TC-DETAIL-05 | PO reference shown for converted req | Open the seeded converted requisition | 1. Find **PO reference** row | — | Shows a `PO-…` code in monospace | | |
| TC-DETAIL-06 | Possible-duplicate alert banner | Open a flagged requisition | 1. Look at the top of the detail page | — | Amber alert "Possible duplicate" listing the resembling requisition(s) as links | | |
| TC-DETAIL-07 | Account code has no detail page | — | 1. Open `/requisitions/account-codes/`<br>2. Note Actions column | — | Account codes have **only Edit + Delete**, no View/detail page — confirm this is intentional (no detail route exists) | | |
| TC-DETAIL-08 | Template detail loads | Logged in | 1. Open a template from the list | — | Template details card + Pre-defined lines table + (if owner/admin) the add-line footer | | |
| TC-DETAIL-09 | Approval workflow panel (Module 4) | Open a requisition routed through an approval rule | 1. Look at the right sidebar | — | If an `ApprovalRequest` exists: "Approval workflow" card with progress bar and "View approval chain" link. If none: panel absent | | |

### 4.6 UPDATE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-EDIT-01 | Edit form pre-fills | A draft requisition exists | 1. Open the draft's detail page<br>2. Click **Edit requisition** | — | Form opens titled `Edit REQ-…`; every field pre-filled with current values | | |
| TC-EDIT-02 | Edit saves changes | On the edit form | 1. Change Title to `Reception supplies — updated`<br>2. Change Priority to `Urgent`<br>3. **Save** | See steps | Toast `REQ-… updated.`; redirected to detail; new title & priority shown | | |
| TC-EDIT-03 | Edit invalid data keeps input | On the edit form | 1. Clear Title<br>2. **Save** | empty Title | Form re-renders with red error; other field values **not lost** | | |
| TC-EDIT-04 | Cannot edit a submitted requisition | A submitted requisition exists | 1. Open `/requisitions/<submitted-pk>/edit/` directly | — | Redirected to detail with error toast `Only your own draft requisitions can be edited.` | | |
| TC-EDIT-05 | Edit button hidden on non-draft | Open an approved requisition detail | 1. Inspect the Actions sidebar | — | No "Edit requisition" button (only Amend/Cancel) | | |
| TC-EDIT-06 | Edit account code | An account code exists | 1. `/requisitions/account-codes/`<br>2. Click the pencil icon<br>3. Change Name to `Office Supplies (rev)`<br>4. **Save** | new name | Toast `Account code updated.`; list shows new name | | |
| TC-EDIT-07 | Toggle account code inactive | On the account-code edit form | 1. Uncheck **Active**<br>2. **Save** | Active = off | List shows grey **Inactive** badge; code disappears from active-only dropdowns (line forms) | | |
| TC-EDIT-08 | Edit template | A template you own | 1. Open template detail → **Edit**<br>2. Change Name<br>3. **Save** | new name | Toast `Template updated.`; redirected to template detail with new name | | |
| TC-EDIT-09 | Non-owner non-admin cannot edit template | Logged in as a user who is neither owner nor admin; a private template's pk | 1. Open `/requisitions/templates/<pk>/edit/` | — | Redirected to template list with error `You cannot edit this template.` | | |

### 4.7 DELETE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DELETE-01 | Delete confirm dialog appears | A draft requisition in the list | 1. Click the bin icon in its Actions cell | — | Browser confirm `Delete requisition REQ-…?` | | |
| TC-DELETE-02 | Cancel delete does nothing | Confirm dialog from TC-DELETE-01 open | 1. Click **Cancel** in the dialog | — | Dialog closes; record still in list | | |
| TC-DELETE-03 | Confirm delete removes record | A draft requisition | 1. Click bin → **OK** | — | Toast `Requisition REQ-… deleted.`; redirected to list; row gone | | |
| TC-DELETE-04 | Delete from detail sidebar | A draft requisition detail page | 1. Click **Delete** in the Actions sidebar → **OK** | — | Same as TC-DELETE-03 | | |
| TC-DELETE-05 | Cannot delete a non-draft requisition | A submitted requisition | 1. POST to `/requisitions/<submitted-pk>/delete/` (or there should be no Delete button) | — | No Delete button shown; direct POST → error toast `Only your own draft requisitions can be deleted.` | | |
| TC-DELETE-06 | Delete account code | An unused account code (e.g. the `7100-MKT` you created) | 1. `/requisitions/account-codes/`<br>2. Click bin → **OK** | — | Toast `Account code deleted.`; row gone | | |
| TC-DELETE-07 | Cannot delete an in-use account code | `6100-OFF` is used by seeded requisition lines | 1. Try to delete `6100-OFF` | — | Error toast `Cannot delete an account code that is in use.`; code remains | | |
| TC-DELETE-08 | Delete template | A template you own | 1. Template detail → **Delete** → **OK** | — | Toast `Template deleted.`; redirected to template list | | |
| TC-DELETE-09 | Delete a template line | A template you own with ≥1 line | 1. Template detail → click the **×** on a line → **OK** | — | Toast `Template line removed.`; row gone; Est. total recalculated | | |
| TC-DELETE-10 | Delete a requisition line | A draft requisition with ≥1 line | 1. Detail page → click **×** on a line → **OK** | — | Toast `Line item removed.`; row gone; Total recalculated | | |
| TC-DELETE-11 | GET on a delete URL is harmless | — | 1. Open `/requisitions/1/delete/` in the address bar (GET) | — | Redirected to the list — nothing deleted (delete views accept POST only) | | |

### 4.8 SEARCH

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-SEARCH-01 | Empty search returns all | Requisition list | 1. Leave Search blank<br>2. Click the filter button | — | All 6 requisitions shown | | |
| TC-SEARCH-02 | Search by title | Requisition list | 1. Type `Reception` → filter | `Reception` | Only the "Reception area supplies" row(s) | | |
| TC-SEARCH-03 | Search by number | Requisition list | 1. Type a full/partial `REQ-ACME-00003` → filter | requisition number | Matching requisition shown | | |
| TC-SEARCH-04 | Search by department | Requisition list | 1. Type `Finance` → filter | `Finance` | Only requisitions whose department is Finance | | |
| TC-SEARCH-05 | Case-insensitive | Requisition list | 1. Type `RECEPTION` → filter | uppercase | Same result as TC-SEARCH-02 (`icontains`) | | |
| TC-SEARCH-06 | Whitespace trimmed | Requisition list | 1. Type `  Reception  ` (leading/trailing spaces) → filter | padded string | Same as TC-SEARCH-02 — view does `.strip()` | | |
| TC-SEARCH-07 | Single character search | Requisition list | 1. Type `a` → filter | `a` | All titles/numbers/departments containing "a" shown; no error | | |
| TC-SEARCH-08 | No-match search | Requisition list | 1. Type `zzzznomatch` → filter | gibberish | Empty state `No requisitions found.` | | |
| TC-SEARCH-09 | Special chars don't 500 | Requisition list | 1. Type `%`, then `_`, then `'` (each) → filter | `%` `_` `'` | Page loads gracefully each time — no 500 error | | |
| TC-SEARCH-10 | Search retained across pagination | >20 requisitions with a common term | 1. Search a term → filter<br>2. Click page 2 | — | Page 2 URL keeps `?q=…`; results still filtered | | |
| TC-SEARCH-11 | Account code search | Account codes list | 1. Search `IT` → filter | `IT` | Only codes whose code/name contains "IT" (`6200-IT`) | | |
| TC-SEARCH-12 | Template search | Template list | 1. Search `office` → filter | `office` | "Monthly office restock" shown (matches name) | | |

### 4.9 PAGINATION

> All three list views use `paginate_by = 20`. The 6 seeded requisitions won't paginate — create extras or test the URL behaviour directly.

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-PAGE-01 | No pager under 21 records | Default seed (6 requisitions) | 1. Open `/requisitions/` | — | No pagination control rendered (`is_paginated` false) | | |
| TC-PAGE-02 | Pager appears past 20 records | Create requisitions until ≥21 exist | 1. Open `/requisitions/` | — | Pagination bar appears bottom-right; page 1 active, page 2 link present | | |
| TC-PAGE-03 | Page 2 shows next set | ≥21 requisitions | 1. Click page **2** | — | Requisitions 21+ shown; page 2 highlighted | | |
| TC-PAGE-04 | Default page size = 20 | ≥21 requisitions | 1. Count rows on page 1 | — | Exactly 20 rows | | |
| TC-PAGE-05 | Page beyond last → graceful | ≥21 requisitions | 1. Visit `/requisitions/?page=999` | `page=999` | No 500 — Django raises 404 for an out-of-range page; note actual behaviour | | |
| TC-PAGE-06 | Invalid page param → graceful | — | 1. Visit `/requisitions/?page=abc` | `page=abc` | No 500 — page 1 shown or 404; no crash | | |
| TC-PAGE-07 | Filters retained across page clicks | ≥21 requisitions, mixed status | 1. Apply Status = Draft<br>2. Click page 2 | — | Page 2 URL keeps `?status=draft&page=2`; still filtered | | |
| TC-PAGE-08 | Search + page combined | ≥21 matching a term | 1. Search a term<br>2. Click page 2 | — | URL keeps `?q=…&page=2`; results still filtered | | |

### 4.10 FILTERS

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-FILTER-01 | Status dropdown populated | Requisition list | 1. Open the **Status** dropdown | — | Options: All, Draft, Submitted, Approved, Rejected, Cancelled, Converted to PO | | |
| TC-FILTER-02 | Filter by status = Draft | Requisition list | 1. Status = Draft → filter | — | Only draft requisitions; URL has `?status=draft` | | |
| TC-FILTER-03 | Filter by status = Approved | Requisition list | 1. Status = Approved → filter | — | Only approved requisitions shown | | |
| TC-FILTER-04 | Category dropdown populated | Requisition list | 1. Open the **Category** dropdown | — | All 7 categories (Office Supplies … Other) | | |
| TC-FILTER-05 | Filter by category | Requisition list | 1. Category = IT Equipment → filter | — | Only IT Equipment requisitions | | |
| TC-FILTER-06 | Scope = Only mine | Requisition list, logged in as a user who owns some | 1. Scope = Only mine → filter | — | Only requisitions where requester = current user | | |
| TC-FILTER-07 | Combined filters AND correctly | Requisition list | 1. Status = Approved + Category = Services → filter | — | Only requisitions matching **both**; "Annual audit engagement" should appear | | |
| TC-FILTER-08 | Filter selection retained after Apply | After TC-FILTER-02 | 1. Look at the Status dropdown | — | Still shows "Draft" selected (not reset to All) | | |
| TC-FILTER-09 | Filter for zero-record value | Requisition list | 1. Pick a status/category combo with no rows | — | Empty state `No requisitions found.` | | |
| TC-FILTER-10 | Filter + search combined | Requisition list | 1. Status = Draft + Search a draft's title → filter | — | Only that draft; URL has both `?q=…&status=draft` | | |
| TC-FILTER-11 | Clear filters returns full list | After any filter | 1. Set all dropdowns to All, clear Search → filter | — | All 6 requisitions return | | |
| TC-FILTER-12 | Account code active/inactive filter | Account codes list; one inactive code exists | 1. Status = Inactive → filter | — | Only inactive codes shown | | |
| TC-FILTER-13 | Template category filter | Template list | 1. Category = IT Equipment → filter | — | Only "New-hire IT kit" shown | | |

### 4.11 Status Transitions / Custom Actions

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-ACTION-01 | Submit a draft with line items | A draft requisition with ≥1 line | 1. Open its detail page<br>2. Click **Submit for approval** | — | Toast `REQ-… submitted for approval.`; status badge → **Submitted**; timeline gains a "Submitted" entry | | |
| TC-ACTION-02 | Cannot submit a draft with no lines | A draft requisition with **0** lines | 1. Delete all lines<br>2. Click **Submit for approval** | — | Error toast `Add at least one line item before submitting.`; status stays Draft | | |
| TC-ACTION-03 | Approve a submitted requisition | Logged in as tenant admin; a submitted requisition with **no** approval rule routing it | 1. Open its detail page<br>2. In the Actions sidebar enter a decision note<br>3. Click **Approve** | note text | Toast `REQ-… approved.`; status → **Approved**; Decision row shows note | | |
| TC-ACTION-04 | Reject a submitted requisition | Same as TC-ACTION-03 | 1. Click **Reject** with a note | note text | Toast `REQ-… rejected.`; status → **Rejected** (red badge) | | |
| TC-ACTION-05 | Decide buttons hidden for non-admin | Logged in as non-admin tenant user; a submitted requisition | 1. Open its detail page | — | No Approve/Reject form in the sidebar (`request.user.is_tenant_admin` gate) | | |
| TC-ACTION-06 | Convert an approved requisition to PO | Logged in as tenant admin; an approved requisition | 1. Open detail<br>2. Leave PO reference blank<br>3. Click **Convert to PO** | blank PO ref | Toast `REQ-… converted to PO-….`; status → **Converted**; PO reference auto-generated and shown | | |
| TC-ACTION-07 | Amend a submitted/approved requisition | An approved or submitted requisition | 1. Open detail<br>2. Click **Amend (reopen as draft)** → confirm | — | Toast `REQ-… reopened as draft (revision N) …`; status → **Draft**; revision incremented; `r2` badge in list | | |
| TC-ACTION-08 | Cancel a requisition | A draft/submitted/approved requisition | 1. Open detail<br>2. Click **Cancel requisition** → confirm | — | Toast `REQ-… cancelled.`; status → **Cancelled** | | |
| TC-ACTION-09 | Out-of-order — convert a draft | A draft requisition | 1. POST to `/requisitions/<draft-pk>/convert/` (Convert button should not be visible) | — | Error toast `Only approved requisitions can be converted.`; status unchanged — no corruption | | |
| TC-ACTION-10 | Out-of-order — decide a draft | A draft requisition | 1. POST to `/requisitions/<draft-pk>/decide/` | — | Error toast `Only submitted requisitions can be decided.` | | |
| TC-ACTION-11 | Out-of-order — submit a converted req | A converted requisition | 1. POST to `/requisitions/<converted-pk>/submit/` | — | Error toast `This requisition cannot be submitted.` | | |
| TC-ACTION-12 | Terminal state shows no actions | A rejected/cancelled/converted requisition | 1. Open its detail page | — | Sidebar shows lock message `This requisition is <status> — no further actions.` | | |
| TC-ACTION-13 | Amend resets decision fields | An approved requisition | 1. Amend it<br>2. Re-open detail | — | Decision row gone; `submitted_at`/`decided_at` cleared; status Draft, editable again | | |
| TC-ACTION-14 | Submit routes via approval engine | Tenant has a matching approval rule (Module 4) | 1. Submit a draft | — | If a rule matches, an `ApprovalRequest` is created and the "Approval workflow" sidebar card appears; the inline Approve/Reject form is **suppressed** ([detail.html:212](templates/requisitions/requisitions/detail.html#L212) — `not approval_request`) | | |

### 4.12 Frontend UI / UX

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-UI-01 | Browser tab titles | — | 1. Visit list, detail, tracking, account codes, templates | — | Tabs read "Requisitions", "REQ-…", "Requisition Tracking", "Account Codes", "Requisition Templates" | | |
| TC-UI-02 | Sidebar active state | — | 1. Navigate each requisitions page | — | The Requisitions nav group/link is highlighted | | |
| TC-UI-03 | Breadcrumb trail | — | 1. Open a requisition detail page | — | Breadcrumb `Requisitions › <title>`; the "Requisitions" part links back to the list | | |
| TC-UI-04 | Toasts auto-dismiss | — | 1. Trigger any success toast | — | Green toast appears then auto-dismisses after a few seconds | | |
| TC-UI-05 | Confirm dialog names the entity | A draft requisition | 1. Click Delete | — | Confirm text includes the requisition number, e.g. `Delete requisition REQ-ACME-00007?` | | |
| TC-UI-06 | Form errors render under fields | Create form | 1. Submit with Title blank | — | Red error text directly under the Title field | | |
| TC-UI-07 | Empty states have a message | — | 1. View a requisition with no lines | — | `No line items yet.` centered in the table | | |
| TC-UI-08 | Tracking board columns | Tracking board | 1. Open `/requisitions/tracking/` | — | 6 columns (one per status) with count badges; cards link to detail; header shows total count + grand total | | |
| TC-UI-09 | Tracking scope selector | Tracking board | 1. Change the scope dropdown to "Only mine" | — | Board auto-submits (`onchange`) and re-filters to the current user's requisitions | | |
| TC-UI-10 | Long text wraps cleanly | A requisition with a 200-char title | 1. View it in the list and detail | — | Text wraps; no horizontal scrollbar / overflow | | |
| TC-UI-11 | Mobile viewport 375×667 | — | 1. DevTools → iPhone SE size<br>2. Browse list + detail | — | Layout usable; no offscreen content or overlap; tables scroll horizontally | | |
| TC-UI-12 | Tablet viewport 768×1024 | — | 1. DevTools → iPad size | — | Tables readable / horizontally scrollable; sidebar collapses appropriately | | |
| TC-UI-13 | Keyboard tab order | Create form | 1. Tab through the fields | — | Logical top-to-bottom order; focus ring visible | | |
| TC-UI-14 | No console errors | — | 1. Open DevTools Console<br>2. Visit every requisitions page | — | No red JS errors | | |
| TC-UI-15 | CSRF token on every form | — | 1. View source of create / line-add / delete forms | — | A `csrfmiddlewaretoken` hidden input is present | | |
| TC-UI-16 | Money formatting | A requisition with lines | 1. Inspect totals | — | Values show `$` + 2 decimals + thousands separators (e.g. `$4,200.00`) | | |

### 4.13 Negative & Edge Cases

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-NEG-01 | Letters in a line quantity | Draft requisition detail | 1. In the add-line row type `abc` in Qty<br>2. Click **+** | `abc` | Error toast `Could not add line — check the values.`; no line added | | |
| TC-NEG-02 | Negative unit price | Draft requisition detail | 1. Add a line with Unit price `-50`<br>2. Click **+** | `-50` | Graceful — either rejected by the `min=0` input or saved; note actual behaviour (negative line total would be a bug) | | |
| TC-NEG-03 | Invalid date in Required date | Create form | 1. Type an invalid date | `2026-13-99` | Browser date input rejects it / graceful form error — no 500 | | |
| TC-NEG-04 | Add line to a non-draft requisition | A submitted requisition | 1. POST to `/requisitions/<submitted-pk>/lines/add/` | — | Error toast `Lines can only be changed on your own draft.` | | |
| TC-NEG-05 | Double-click Submit | A draft with lines | 1. Rapidly double-click **Submit for approval** | — | Status moves to Submitted once; second POST → `This requisition cannot be submitted.` — no double processing | | |
| TC-NEG-06 | Browser back after create | Just created a requisition | 1. Press browser **Back**<br>2. Press Forward / refresh | — | No silent duplicate creation; browser may warn about resubmission | | |
| TC-NEG-07 | Refresh after POST | After submitting any form | 1. Press F5 on the result page | — | No duplicate record (views redirect after POST — PRG pattern) | | |
| TC-NEG-08 | All required fields blank | Create form | 1. Submit completely empty | — | Title error shown; no record created; no 500 | | |
| TC-NEG-09 | Decimal precision overflow | Add-line row | 1. Quantity `999999999999.999` (exceeds `max_digits=12`, `decimal_places=2`) | huge number | Graceful form error, not a 500 | | |
| TC-NEG-10 | Empty line description | Add-line row | 1. Leave Description blank, fill Qty/price<br>2. Click **+** | blank desc | Error toast `Could not add line…`; no line added (`description` required) | | |
| TC-NEG-11 | Delete a line via GET | — | 1. Open `/requisitions/<pk>/lines/<line_pk>/delete/` (GET) | — | Redirected to detail; line **not** deleted | | |
| TC-NEG-12 | Use a template you don't own & isn't shared | A private template owned by another user | 1. POST to `/requisitions/templates/<pk>/use/` | — | 404 — `TemplateUseView` filters `Q(owner=user) | Q(is_shared=True)` | | |
| TC-NEG-13 | Account code 500 trap | `6100-OFF` exists | 1. Re-test TC-CREATE-08 carefully | duplicate code | Watch for an IntegrityError 500 page — if it appears, log `BUG` (see §NavPMS notes: `tenant` excluded from `AccountCodeForm`) | | |

### 4.14 Cross-Module Integration

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-INT-01 | Submit triggers Module 4 approval | A tenant with an approval rule that matches | 1. Submit a draft requisition<br>2. Open its detail page | — | "Approval workflow" card in the sidebar with a progress bar; "View approval chain" links into `/approvals/` | | |
| TC-INT-02 | Cancel withdraws in-flight approval | A submitted requisition routed through an approval rule | 1. Cancel it | — | The linked `ApprovalRequest` is cancelled too ([services.py:194](apps/requisitions/services.py#L194) `cancel_approval`) | | |
| TC-INT-03 | Amend withdraws approval workflow | An approved requisition routed through a rule | 1. Amend it | — | Approval workflow withdrawn; re-submitting starts a fresh one | | |
| TC-INT-04 | Audit log records requisition events | Tenant admin | 1. Create, submit, approve a requisition<br>2. Open the tenant audit log (portal/tenants audit page) | — | Entries `requisition.created`, `requisition.submitted`, `requisition.approved` present (`record_audit`) | | |
| TC-INT-05 | Template "use" copies lines into a requisition | Template "New-hire IT kit" (3 lines) | 1. Use the template | — | New requisition has all 3 lines with matching descriptions/qty/price; `created_from_template` link shown on detail | | |

---

## 5. Bug Log

| Bug ID | Test Case ID | Severity | Page URL | Steps to Reproduce | Expected | Actual | Status | Browser |
|---|---|---|---|---|---|---|---|---|
| BUG-01 | TC-CREATE-08 / TC-NEG-13 | **High** | `/requisitions/account-codes/create/` | 1. Log in as `admin_acme`<br>2. New account code<br>3. Code `6100-OFF` (already exists for the tenant)<br>4. Save | Clean form-level error under the **Code** field | **Server error 500** — `MySQLdb.IntegrityError (1062) Duplicate entry '1-6100-OFF'`. `AccountCodeForm` excluded `tenant`, so `validate_unique()` skipped the `unique_together('tenant','code')` check and the duplicate hit the DB | ✅ **FIXED & re-verified** — see below | Django test client (auto-run) |

**Fix for BUG-01:** `AccountCodeForm` now accepts a `tenant` kwarg and validates tenant-scoped code uniqueness in `clean_code()`, surfacing a duplicate as the form error *"An account code with this code already exists."* The create/edit views pass `tenant=request.tenant`. Files: [apps/requisitions/forms.py](apps/requisitions/forms.py#L10), [apps/requisitions/views.py:65](apps/requisitions/views.py#L65), [apps/requisitions/views.py:90](apps/requisitions/views.py#L90). TC-CREATE-08 re-run after the fix → **PASS** (clean form error, no 500).

| Bug ID | Test Case ID | Severity | Page URL | Steps to Reproduce | Expected | Actual | Status | Browser |
|---|---|---|---|---|---|---|---|---|
| BUG-02 | | | | | | | open | |
| BUG-03 | | | | | | | open | |

**Severity guide:** Critical (data loss / security / blocks core flow) · High (major feature broken) · Medium (feature works with a workaround) · Low (minor) · Cosmetic (visual only).

> No other defects surfaced in the 60 auto-executed cases. The remaining 85 manual cases (UI/UX, responsive, console) have not yet been run — add `BUG-NN` rows here as you find issues.

---

## 6. Sign-off & Release Recommendation

"Pass" column shows **auto-executed passes**; "Pending" = cases still needing a human in a browser.

| Section | Total | Pass (auto) | Fail | Pending (manual) | Notes |
|---|---|---|---|---|---|
| 4.1 Authentication & Access | 6 | 5 | 0 | 1 | TC-AUTH-06 (logout) pending |
| 4.2 Multi-Tenancy Isolation | 5 | 4 | 0 | 1 | TC-TENANT-05 pending |
| 4.3 CREATE | 13 | 12 | 0 | 1 | TC-CREATE-13 (max-length) pending |
| 4.4 READ — List Page | 11 | 3 | 0 | 8 | Visual columns/badges need browser |
| 4.5 READ — Detail Page | 9 | 1 | 0 | 8 | Timeline/banners need browser |
| 4.6 UPDATE | 9 | 3 | 0 | 6 | |
| 4.7 DELETE | 11 | 4 | 0 | 7 | Confirm dialogs need browser |
| 4.8 SEARCH | 12 | 6 | 0 | 6 | |
| 4.9 PAGINATION | 8 | 3 | 0 | 5 | Needs >20 records seeded |
| 4.10 FILTERS | 13 | 5 | 0 | 8 | Dropdown rendering needs browser |
| 4.11 Status Transitions / Actions | 14 | 9 | 0 | 5 | |
| 4.12 Frontend UI / UX | 16 | 1 | 0 | 15 | Almost all need a browser |
| 4.13 Negative & Edge Cases | 13 | 4 | 0 | 9 | |
| 4.14 Cross-Module Integration | 5 | 0 | 0 | 5 | Audit log / approvals UI |
| **TOTAL** | **145** | **60** | **0** | **85** | 1 bug found & fixed (BUG-01) |

**Tested by:** Automated harness (60 cases) + ____________ (manual)  **Date:** 2026-05-23  **Build / commit:** main @ pre-commit

**Release Recommendation:** ☑ **GO-with-fixes** *(provisional)*

**Rationale:** All 60 auto-executed back-end cases pass; the one defect found (BUG-01, duplicate account code 500) has been fixed and re-verified. Final GO is contingent on completing the 85 pending manual UI/UX cases in a browser.
