# Sourcing & Tendering (Module 6) — Manual Test Plan

> Senior Manual QA Engineer click-through script for **Module 6 — Sourcing & Tendering**. Two surfaces in scope: the buyer side at [apps/sourcing/](../../apps/sourcing/) (`/sourcing/`) and the vendor bid portal in [apps/vendors/portal_urls.py](../../apps/vendors/portal_urls.py) (`/vendor-portal/sourcing/`). Sealed-bid visibility is treated as a security boundary.

---

## 1. Scope & Objectives

| Item | Detail |
|---|---|
| **Module under test** | `apps.sourcing` + vendor-portal sourcing routes in `apps.vendors` |
| **URL prefixes** | `/sourcing/` (buyer) + `/vendor-portal/sourcing/` (vendor) |
| **Sub-modules covered** | (1) Event Creation & Scheduling, (2) Vendor Bid Submission Portal, (3) Bid Evaluation Matrix, (4) Award Recommendation, (5) Sourcing Analytics |
| **Primary entities** | `SourcingEvent`, `SourcingEventItem`, `SourcingEventInvitee`, `SourcingCriterion`, `Bid`, `BidLine`, `BidDocument`, `BidEvaluation`, `SourcingAward` ([apps/sourcing/models.py](../../apps/sourcing/models.py)) |
| **Workflows** | Event status `draft → scheduled → open → closed → under_evaluation → awarded` (+ `cancelled`); Bid status `draft → submitted → under_review → shortlisted/rejected/awarded/withdrawn`; Invitee status `invited → viewed → submitted/declined/withdrawn`; Award status `recommended → approved` |
| **Security boundary** | **Sealed-bid gate** in `bid_visible_to()` ([apps/sourcing/services.py:48-63](../../apps/sourcing/services.py#L48-L63)) — buyers cannot see bid prices, lines, docs, or scores until the event status reaches one of `closed/under_evaluation/awarded/cancelled`. Vendor authors always see their own bid. |
| **Integration boundary** | Requisitions (Module 3): the requisition detail page exposes a "Create Sourcing Event" button when the requisition is approved; that route calls `create_event_from_requisition()` to pre-fill items. |
| **Out of scope** | Automated email notifications (none in v1), background cron for auto open/close (manual only), file-system scanning of uploaded documents |

---

## 2. Pre-Test Setup

### 2.1 Start the dev server (PowerShell)

```powershell
python manage.py runserver
```

### 2.2 Seed demo data

```powershell
python manage.py seed_data
python manage.py seed_sourcing
```

`seed_sourcing` creates **3 events per tenant** ([apps/sourcing/management/commands/seed_sourcing.py](../../apps/sourcing/management/commands/seed_sourcing.py)):

| Event | Status | Items | Criteria | Invitees | Bids |
|---|---|---:|---:|---:|---|
| Office furniture refresh | `draft` | 3 | 4 | 0 | 0 |
| Quarterly IT hardware | `open` (closes +10d) | 4 | 4 | 3 | 1 draft + 1 submitted |
| Annual cleaning contract | `awarded` | 2 | 4 | 3 | 3 scored, winner awarded |

Re-seed requires `--flush`:

```powershell
python manage.py seed_sourcing --flush
```

### 2.3 Credentials (password `Welcome@123` for all)

| Username | Role | Tenant | Use for |
|---|---|---|---|
| `admin_acme` | tenant_admin | Acme | Primary buyer-side tester |
| `admin_globex` | tenant_admin | Globex | Cross-tenant isolation |
| `mgr_acme` *(procurement_manager)* | mgr | Acme | "buyer" persona — has manage role |
| `approver_acme` *(approver)* | approver | Acme | Can evaluate but NOT manage events |
| any seeded **vendor portal user** (see [apps/vendors/management/commands/seed_vendor_users.py](../../apps/vendors/management/commands/seed_vendor_users.py)) | vendor | n/a | Vendor-side bid testing |
| `admin` | superuser, no tenant | — | Negative test (BY DESIGN no data) |

> Find a vendor portal user with `python manage.py shell -c "from apps.vendors.models import VendorUser; print([(v.user.username, v.vendor.legal_name) for v in VendorUser.objects.select_related('user','vendor')[:5]])"`.

### 2.4 Baseline expectations per tenant

| Page | URL | Expected |
|---|---|---|
| Event list | [`/sourcing/`](http://127.0.0.1:8000/sourcing/) | 3 rows (Office furniture / IT hardware / Cleaning contract). Stats cards: total=3, draft=1, open=1, awarded=1. |
| Awarded event detail | `/sourcing/<awarded-pk>/` | Shows 2 items, 4 criteria, 3 invitees (all `submitted`), Bids tab UNSEALED (event closed), Awards table with 1 approved row. |
| Open event detail | `/sourcing/<open-pk>/` | Items/Invitees/Criteria visible; Bids tab **SEALED** (lock icon, "Bids hidden until event closes"). |
| Draft event detail | `/sourcing/<draft-pk>/` | No invitees, no bids; Publish button available once items + invitees + criteria added. |
| Analytics | [`/sourcing/analytics/`](http://127.0.0.1:8000/sourcing/analytics/) | Cards populated with non-zero estimated/awarded/savings values. |
| Vendor inbox | [`/vendor-portal/sourcing/`](http://127.0.0.1:8000/vendor-portal/sourcing/) (as vendor) | Invitations visible for invited events. |

### 2.5 Browser matrix

| Surface | Viewport | Browser |
|---|---|---|
| Primary buyer side | 1920×1080 | Chrome desktop |
| Vendor portal | 1366×768 | Chrome desktop |
| Mobile vendor portal | 375×667 | Chrome DevTools emulation |
| Secondary | 1366×768 | Edge desktop |

### 2.6 Reset between major test runs

```powershell
python manage.py seed_sourcing --flush
python manage.py seed_sourcing
```

---

## 3. Test Surface Inventory

### 3.1 Buyer-side URLs ([apps/sourcing/urls.py](../../apps/sourcing/urls.py))

| Sub-area | Method | URL pattern | View | Gate |
|---|---|---|---|---|
| Event list | GET | `/sourcing/` | `event_list` | login + non-vendor |
| Event create | GET/POST | `/sourcing/new/` | `event_create` | login + tenant + **manage role** |
| Event detail | GET | `/sourcing/<pk>/` | `event_detail` | login + tenant |
| Event edit | GET/POST | `/sourcing/<pk>/edit/` | `event_edit` | manage role + status=draft |
| Event delete | POST | `/sourcing/<pk>/delete/` | `event_delete` | manage role + status=draft |
| Publish | POST | `/sourcing/<pk>/publish/` | `event_publish` | manage role |
| Open now | POST | `/sourcing/<pk>/open/` | `event_open` | manage role |
| Close | POST | `/sourcing/<pk>/close/` | `event_close` | manage role |
| Cancel | POST | `/sourcing/<pk>/cancel/` | `event_cancel` | manage role |
| Item add | GET/POST | `/sourcing/<pk>/items/add/` | `item_create` | manage role + draft |
| Item edit | GET/POST | `/sourcing/<pk>/items/<lpk>/edit/` | `item_edit` | manage role + draft |
| Item delete | POST | `/sourcing/<pk>/items/<lpk>/delete/` | `item_delete` | manage role + draft |
| Invitee add | POST | `/sourcing/<pk>/invitees/add/` | `invitee_add` | manage role |
| Invitee remove | POST | `/sourcing/<pk>/invitees/<ipk>/remove/` | `invitee_remove` | manage role (blocked if invitee `submitted`) |
| Criterion add | GET/POST | `/sourcing/<pk>/criteria/add/` | `criterion_create` | manage role |
| Criterion edit | GET/POST | `/sourcing/<pk>/criteria/<cpk>/edit/` | `criterion_edit` | manage role |
| Criterion delete | POST | `/sourcing/<pk>/criteria/<cpk>/delete/` | `criterion_delete` | manage role |
| Bid list | GET | `/sourcing/<pk>/bids/` | `bid_list` | login + sealed gate |
| Bid compare | GET | `/sourcing/<pk>/bids/compare/` | `bid_compare` | sealed gate + closed |
| Bid detail | GET | `/sourcing/<pk>/bids/<bpk>/` | `bid_detail` | `bid_visible_to()` |
| Bid evaluate | GET/POST | `/sourcing/<pk>/bids/<bpk>/evaluate/` | `bid_evaluate` | evaluate role + post-close |
| Bid shortlist | POST | `/sourcing/<pk>/bids/<bpk>/shortlist/` | `bid_shortlist` | manage role |
| Bid reject | POST | `/sourcing/<pk>/bids/<bpk>/reject/` | `bid_reject` | manage role |
| Award recommend | GET/POST | `/sourcing/<pk>/awards/recommend/` | `award_recommend` | manage role + post-close |
| Award finalize | POST | `/sourcing/<pk>/awards/finalize/` | `award_finalize` | manage role |
| Analytics dashboard | GET | `/sourcing/analytics/` | `analytics_dashboard` | login + tenant |
| Event analytics | GET | `/sourcing/<pk>/analytics/` | `analytics_event_report` | login + tenant |

### 3.2 Vendor-side URLs ([apps/vendors/portal_urls.py](../../apps/vendors/portal_urls.py))

| Method | URL | View | Notes |
|---|---|---|---|
| GET | `/vendor-portal/sourcing/` | `portal_invitations` | Vendor's invitation inbox |
| GET | `/vendor-portal/sourcing/bids/` | `portal_my_bids` | All vendor's bids across events |
| GET | `/vendor-portal/sourcing/<event_pk>/` | `portal_event_detail` | Read-only event; auto-marks invitee `viewed` |
| POST | `/vendor-portal/sourcing/<event_pk>/bid/start/` | `portal_bid_start` | Creates draft Bid (idempotent); requires invited + event open |
| GET/POST | `/vendor-portal/sourcing/<event_pk>/bid/<bpk>/` | `portal_bid_edit` | Editable only while status=draft |
| POST | `/vendor-portal/sourcing/<event_pk>/bid/<bpk>/submit/` | `portal_bid_submit` | draft → submitted; validates all lines have `unit_price > 0` |
| POST | `/vendor-portal/sourcing/<event_pk>/bid/<bpk>/withdraw/` | `portal_bid_withdraw` | draft/submitted → withdrawn (event must be open) |
| GET | `/vendor-portal/sourcing/<event_pk>/bid/<bpk>/view/` | `portal_bid_detail` | Read-only own bid |
| POST | `/vendor-portal/sourcing/invitations/<ipk>/decline/` | `portal_invitation_decline` | invited/viewed → declined |

### 3.3 Filter / search params

| Page | Search (`q=`) | Filters |
|---|---|---|
| Event list | event_number, title, description | `status`, `event_type`, `category` |
| Bid list | — | sealed-aware; no params |
| Vendor invitations | — | no params |

### 3.4 Workflow state machines

> The full diagrams live in [.claude/tasks/todo.md](../tasks/todo.md). Quick summary:

**Event:** `draft → scheduled → open → closed → under_evaluation → awarded`. `cancelled` reachable from `draft/scheduled/open/closed/under_evaluation`.

**Bid:** `draft → submitted → under_review → shortlisted/rejected → awarded`. `withdrawn` reachable from `draft/submitted` (only while event open). `close_event` auto-rejects all `draft` bids.

**Invitee:** `invited → viewed → submitted/declined`; `submitted → withdrawn`.

**Award:** `recommended → approved` (append-only).

---

## 4. Test Cases

### 4.1 Authentication & Access

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-AUTH-01 | Anonymous redirected to login | Logged out | 1. Open incognito<br>2. Visit `/sourcing/` | — | Redirected to `/accounts/login/?next=/sourcing/`. | | |
| TC-AUTH-02 | Anonymous on vendor portal redirected | Logged out | 1. Visit `/vendor-portal/sourcing/` | — | Redirected to login. | | |
| TC-AUTH-03 | Authenticated, no tenant → onboarding | Login as `admin` (superuser, no tenant) | 1. Visit `/sourcing/` | — | Redirected to `/tenants/onboarding/...` (per [apps/core/mixins.py](../../apps/core/mixins.py) two-path redirect), NOT `/accounts/login/`. | | |
| TC-AUTH-04 | Tenant admin can open every buyer-side page | Login as `admin_acme` | 1. Visit each URL in §3.1 | — | All return 200. Sidebar **Sourcing** highlighted. | | |
| TC-AUTH-05 | Non-manage role BLOCKED from create | Login as `approver_acme` (role `approver`, not in MANAGE_ROLES) | 1. Visit `/sourcing/new/` | — | 403 / redirect with permission error toast. `approver` is in EVALUATE_ROLES only (per [apps/sourcing/services.py](../../apps/sourcing/services.py) MANAGE_ROLES = tenant_admin, procurement_manager, buyer). | | |
| TC-AUTH-06 | Approver CAN evaluate (post-close) | Closed event with bids exists; login as `approver_acme` | 1. Visit `/sourcing/<closed-pk>/bids/<bpk>/evaluate/` | — | Form loads 200. Score fields editable per criterion. | | |
| TC-AUTH-07 | Vendor user BLOCKED from buyer surface | Login as a vendor portal user | 1. Visit `/sourcing/` | — | Blocked / redirected (decorator `@vendor_blocked`). User cannot reach event_list. | | |
| TC-AUTH-08 | Buyer-side user BLOCKED from vendor portal | Login as `admin_acme` | 1. Visit `/vendor-portal/sourcing/` | — | Blocked / redirected (decorator `@vendor_required`). | | |
| TC-AUTH-09 | CSRF token present on every form | Login as `admin_acme` | 1. View source on event create + item create + criteria add + award recommend | — | Each contains `<input type="hidden" name="csrfmiddlewaretoken">`. | | |

### 4.2 Multi-Tenancy Isolation

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-TENANT-01 | Event list scoped to tenant | Both Acme + Globex seeded | 1. Login `admin_acme`<br>2. Visit `/sourcing/`<br>3. Count rows | — | Only Acme events visible (3). No Globex events. | | |
| TC-TENANT-02 | Cross-tenant IDOR (event detail) | Globex event exists | 1. Note a Globex event pk from `admin_globex` session<br>2. Logout, login `admin_acme`<br>3. Visit `/sourcing/<globex-pk>/` | Globex pk | 404 Not Found. | | |
| TC-TENANT-03 | Cross-tenant IDOR (bid detail) | Globex closed event has bids | 1. Get a Globex bid pk<br>2. Login `admin_acme`<br>3. Visit `/sourcing/<globex-event-pk>/bids/<globex-bid-pk>/` | Globex pks | 404. | | |
| TC-TENANT-04 | Cross-tenant POST on close | — | 1. As `admin_acme`, POST to `/sourcing/<globex-pk>/close/` with valid CSRF | — | 404. Globex event status unchanged when verified back as `admin_globex`. | | |
| TC-TENANT-05 | Vendor cannot see other vendor's invitations | Vendor A and Vendor B both have invitations | 1. Login as Vendor A portal user<br>2. Try `/vendor-portal/sourcing/<event-pk>/bid/<vendor-B-bid-pk>/` | Vendor B's bid pk | 404 / forbidden. Vendor A only sees own bids. | | |
| TC-TENANT-06 | Superuser sees no tenant data | `admin` (no tenant) | 1. Visit `/sourcing/` | — | Redirected to onboarding (per TC-AUTH-03). Never sees the buyer surface. | | |

### 4.3 CREATE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-CREATE-01 | Create event — happy path | Login as `admin_acme` | 1. Visit `/sourcing/`<br>2. Click **+ New event**<br>3. Fill Title `Test RFQ Q2`, Description `Test`, Type `rfq`, Category any, Currency `USD`, Estimated `5000`, Publish at = tomorrow 09:00, Close at = +14d 17:00, Award target = +21d, Terms `Standard`, Partial award unchecked<br>4. Save | as listed | Toast: `Event "Test RFQ Q2" created. Add items, invitees, and criteria below.` Redirect to `/sourcing/<new-pk>/`. event_number generated `SRC-ACME-NNNNN`. Detail page shows all six tabs empty. | | |
| TC-CREATE-02 | Create event — required field missing | Same | 1. Visit `/sourcing/new/`<br>2. Leave Title blank<br>3. Save | — | Form re-renders with red error under Title. No record created. | | |
| TC-CREATE-03 | Create event — close < publish | Same | 1. Set Publish at = +5d, Close at = today<br>2. Save | dates inverted | Form-level error: `Close date must be after publish date.` (Per `clean()` in [apps/sourcing/forms.py](../../apps/sourcing/forms.py).) | | |
| TC-CREATE-04 | Create event from approved requisition | An approved Acme requisition exists with ≥2 lines | 1. Visit `/requisitions/<approved-pk>/`<br>2. Click **Create Sourcing Event**<br>3. The link goes to `/sourcing/new/?from_requisition=<req-pk>`<br>4. Save default form | — | New event created with title prefilled from requisition + items pre-populated as `SourcingEventItem` rows (one per requisition line, qty + unit_price copied). `event.requisition` FK set. | | |
| TC-CREATE-05 | Add item — happy path | Draft event open | 1. On event detail, Items tab → **Add item**<br>2. Fill Line no `1`, Description `Office chair`, UoM `EA`, Qty `10`, Unit price `150`, Required date = +30d<br>3. Save | as listed | Toast `Item added.` Row appears in items table. Estimated line total = `1,500.00`. | | |
| TC-CREATE-06 | Add item — duplicate line_no on same event | Item with line_no=1 already exists | 1. Add another item with Line no `1`, Description `Desk` | Line no `1` | Form re-renders with red error under Line no — duplicate caught by `clean_line_no` (per [apps/sourcing/forms.py](../../apps/sourcing/forms.py) `clean_line_no`). | | |
| TC-CREATE-07 | Add item — negative qty rejected | Draft event | 1. Add item with Qty `-5` | qty `-5` | Form error (model `MinValueValidator(0)`). No record. | | |
| TC-CREATE-08 | Add item — XSS in description | Draft event | 1. Add item with description `<script>alert('xss')</script>` | XSS payload | Saves. Items table renders escaped (no popup). | | |
| TC-CREATE-09 | Add criterion — happy path | Draft event with no criteria | 1. Criteria tab → **Add criterion**<br>2. Fill Name `Price`, Type `price`, Weight `40`, Max score `100`, Order `1`<br>3. Save | as listed | Toast. Row appears. Total weight indicator shows 40/100. | | |
| TC-CREATE-10 | Add criterion — weight makes sum > 100 | Existing criteria totaling 95 | 1. Add new criterion Weight `10` (sum becomes 105) | weight 10 | Form error: `Total criteria weight would exceed 100% (existing: 95, new: 10).` (Per `clean_weight` checking sum.) | | |
| TC-CREATE-11 | Add criterion — weight > 100 individually | Empty event | 1. Add criterion Weight `150` | weight 150 | Form error: weight must be 0–100. | | |
| TC-CREATE-12 | Invite vendors — happy path | Active vendors exist; draft event with no invitees | 1. Invitees tab → click **Invite vendors**<br>2. Tick 3 active vendors<br>3. Save | 3 vendor pks | Toast: `3 vendors invited.` 3 rows appear in invitees table, all `Invited`. Vendors that are suspended/blacklisted/inactive must NOT appear in the dropdown ([apps/sourcing/forms.py](../../apps/sourcing/forms.py) `InviteVendorsForm`). | | |
| TC-CREATE-13 | Cannot re-invite the same vendor | Vendor already an invitee | 1. Open Invite vendors dialog again | — | Already-invited vendors NOT in the dropdown (form queryset excludes existing invitees). | | |
| TC-CREATE-14 | Cannot invite suspended vendor | Vendor with status `suspended` exists | 1. Open Invite vendors dialog | — | Suspended/blacklisted vendor not listed in choices. | | |
| TC-CREATE-15 | Vendor starts a bid (vendor side) | Vendor V is invited to open event E | 1. Login as V's portal user<br>2. Visit `/vendor-portal/sourcing/`<br>3. Click event E<br>4. Click **Start bid** | — | Draft Bid created with `BID-<SLUG>-NNNNN` number. One BidLine per event item auto-created (qty_offered = event_item.qty, unit_price = 0). Redirect to `/vendor-portal/sourcing/<event-pk>/bid/<bpk>/`. Invitee status flipped to `viewed`. | | |
| TC-CREATE-16 | Vendor start bid is idempotent | Vendor already started a draft bid | 1. Click **Start bid** again | — | Same draft bid opened (no new Bid row created). No 500. | | |
| TC-CREATE-17 | Vendor not invited cannot start bid | Open event E exists; Vendor V NOT invited | 1. As V, POST to `/vendor-portal/sourcing/<E-pk>/bid/start/` directly | — | Error toast / redirect. No bid created. | | |
| TC-CREATE-18 | Vendor cannot start bid on closed event | Event E status=closed | 1. Try start bid | — | Error: event not open for bids. | | |
| TC-CREATE-19 | Bid document upload | Vendor has draft bid | 1. On bid edit page, fill Document title `Spec.pdf`<br>2. Choose a small PDF<br>3. Upload | small PDF (<10 MB) | Document row appears. Download link works. | | |
| TC-CREATE-20 | Bid document — oversized file rejected | Vendor draft bid | 1. Try upload a file > 10 MB | 12 MB file | Form error: `File must be ≤ 10 MB.` (per `clean_file` in BidDocumentForm). | | |

### 4.4 READ — List Page

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-LIST-01 | Event list renders seeded events | Seeded | 1. Visit `/sourcing/` | — | 3 rows: Office furniture (draft), IT hardware (open), Cleaning contract (awarded). Stats cards show counts. | | |
| TC-LIST-02 | Event list — Edit/Delete only on draft | Mixed-status events | 1. Inspect Actions column | — | Edit + Delete buttons shown ONLY on the draft row. The open + awarded rows show only the View (eye) icon (per `event.is_editable`). | | |
| TC-LIST-03 | Bid list — sealed before close | Open event with at least 1 submitted bid | 1. Visit `/sourcing/<open-pk>/bids/` | — | Page renders a lock icon + message `Bids are hidden until the event closes.` No bid numbers, no totals, no vendor names visible. | | |
| TC-LIST-04 | Bid list — unsealed after close | Closed/awarded event | 1. Visit `/sourcing/<awarded-pk>/bids/` | — | Table visible: rank, bid_number, vendor, status, total, score, compliant indicator. Awarded row clearly shown. | | |
| TC-LIST-05 | Vendor invitations inbox | Vendor user with ≥1 invitation | 1. Login as vendor user<br>2. Visit `/vendor-portal/sourcing/` | — | Table of invitations: event, type, event status, close_at, invitee status. View + Decline buttons (Decline only if invited/viewed and event open). | | |
| TC-LIST-06 | My bids page | Vendor with bids | 1. Visit `/vendor-portal/sourcing/bids/` | — | All vendor's bids listed with status, event link, edit/view link. | | |
| TC-LIST-07 | Empty state — no events | New tenant | 1. Login as that tenant<br>2. Visit `/sourcing/` | — | Empty state message + CTA `Create your first sourcing event`. | | |

### 4.5 READ — Detail Page

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DETAIL-01 | Event detail tabs render | Awarded seeded event | 1. Visit detail | — | Six tabs visible: Items, Invitees, Criteria, Bids, Awards, Terms. All populated. Sidebar shows status, type, currency, estimated/awarded totals, dates. | | |
| TC-DETAIL-02 | Estimated total uses item sum when items exist | Event with items | 1. Open detail | — | Total = Σ(qty × est_unit_price) from items (NOT just `estimated_value` field) — per `total_estimated` property in [apps/sourcing/models.py](../../apps/sourcing/models.py). | | |
| TC-DETAIL-03 | Invitee status badges | Awarded event with mixed invitee outcomes | 1. Invitees tab | — | Each row shows correct status badge: invited/viewed/submitted/declined/withdrawn. | | |
| TC-DETAIL-04 | Bid detail — sealed for buyer pre-close | Open event with submitted bid | 1. Login as `admin_acme`<br>2. Visit `/sourcing/<open-pk>/bids/<bpk>/` | — | Sealed message; lines, total, docs, evaluations HIDDEN. (per `bid_visible_to()` returning False — security boundary.) | | |
| TC-DETAIL-05 | Bid detail — visible to vendor author at any time | Vendor V has draft bid on open event | 1. Login as V's portal user<br>2. Visit `/vendor-portal/sourcing/<event-pk>/bid/<bpk>/view/` | — | Vendor V sees their own bid lines, total, docs (per `bid_visible_to()` vendor branch). | | |
| TC-DETAIL-06 | Bid detail — visible to buyer post-close | Closed event with bid | 1. Login as `admin_acme`<br>2. Visit `/sourcing/<closed-pk>/bids/<bpk>/` | — | Full content: lines table, docs, scores, sidebar with vendor + total + rank. | | |
| TC-DETAIL-07 | Bid compare matrix | Closed event with ≥2 bids | 1. Visit `/sourcing/<closed-pk>/bids/compare/` | — | Matrix 1: items × bid prices. Matrix 2: criteria × per-bid avg scores. Bid columns ordered by rank. | | |
| TC-DETAIL-08 | Bid compare blocked pre-close | Open event with multiple bids | 1. Try `/sourcing/<open-pk>/bids/compare/` directly | — | Redirect / error toast. Page not rendered. | | |
| TC-DETAIL-09 | Vendor event detail auto-marks invitee viewed | Vendor V is invited (status=invited) | 1. Login as V<br>2. Visit `/vendor-portal/sourcing/<event-pk>/` | — | Page renders 200. Then back in invitations list, V's invitee status now `viewed`. | | |
| TC-DETAIL-10 | Analytics dashboard renders | Seeded | 1. Visit `/sourcing/analytics/` | — | Cards: total_events, open_events, awarded_events, total_estimated, total_awarded, savings, savings_pct, response_rate. Recent awarded events + Top vendors tables. | | |
| TC-DETAIL-11 | Event analytics report | Awarded event | 1. Visit `/sourcing/<pk>/analytics/` | — | Estimated vs awarded with savings$ and savings%. Response rate (submitted/invited %). | | |

### 4.6 UPDATE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-EDIT-01 | Edit draft event | Draft event | 1. Open detail<br>2. Click Edit<br>3. Change estimated value to `7500`<br>4. Save | — | Form prefilled. Saves. Detail shows new value. | | |
| TC-EDIT-02 | Cannot edit non-draft event | Open event | 1. Try to visit `/sourcing/<open-pk>/edit/` directly | — | Redirect with error: `Event can only be edited while in draft.` Even if the URL is reached, status guard kicks in. | | |
| TC-EDIT-03 | Edit item — happy path | Draft event with items | 1. Items tab → click pencil on a row<br>2. Change qty from 10 to 20<br>3. Save | qty 20 | Item row updated. Line total recalculated. | | |
| TC-EDIT-04 | Edit criterion — change weight (sum stays ≤100) | Event with 4 criteria totalling 100 | 1. Edit Price criterion: change weight from 40 to 35 (sum drops to 95) | — | Saves. Sum indicator shows 95/100. Cannot publish until sum back to 100. | | |
| TC-EDIT-05 | Vendor edits draft bid | Vendor V has draft bid | 1. Open bid edit page<br>2. Fill unit_price on every line, set lead_time `14`, payment_terms `Net 30`<br>3. Save draft | non-zero prices | Saves. Total recomputed. Bid status stays draft. | | |
| TC-EDIT-06 | Vendor cannot edit submitted bid | Vendor V has submitted bid | 1. Try to access bid edit page | — | Page shows "Locked" warning. Inputs disabled (per `is_locked`). Save button hidden. | | |

### 4.7 DELETE

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-DELETE-01 | Delete draft event — confirm dialog | Draft event with NO bids | 1. Click bin on the draft row → confirm | — | Toast: `Event deleted.` Redirect to list. Row gone. | | |
| TC-DELETE-02 | Cannot delete non-draft event | Open event | 1. Bin button not visible in list (per `is_editable`)<br>2. POST to `/sourcing/<open-pk>/delete/` directly | — | Redirect with error toast. Event remains. | | |
| TC-DELETE-03 | Delete item from draft event | Item exists | 1. Items tab → bin on row → confirm | — | Item removed. Total recalculates. | | |
| TC-DELETE-04 | Cannot delete item from open event | Open event has items | 1. Open event detail | — | Item delete buttons not rendered (per `event.is_editable`). | | |
| TC-DELETE-05 | Remove invitee — not yet submitted | Invitee status invited/viewed | 1. Invitees tab → click X → confirm | — | Invitee removed. Toast: `Invitee removed.` | | |
| TC-DELETE-06 | Cannot remove invitee who already submitted | Invitee status=submitted | 1. Try X | — | Error: `Cannot remove an invitee who has already submitted.` Invitee remains. | | |
| TC-DELETE-07 | Delete criterion | Draft event | 1. Criteria tab → bin → confirm | — | Criterion removed. Total weight recalculates. | | |
| TC-DELETE-08 | CSRF required on delete POST | Logged in | 1. From DevTools console: `fetch('/sourcing/<pk>/delete/', {method:'POST'})` no token | — | 403. Event remains. | | |

### 4.8 SEARCH

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-SEARCH-01 | Empty search returns all | Logged in | 1. `/sourcing/` with blank q → Filter | — | All 3 seeded events shown. | | |
| TC-SEARCH-02 | Search by event_number | Seeded | 1. Type `SRC-ACME-00001` | — | Single matching row. | | |
| TC-SEARCH-03 | Search by title fragment | Seeded | 1. Type `cleaning` | `cleaning` | Cleaning contract event shown. | | |
| TC-SEARCH-04 | Search case-insensitive | Seeded | 1. Type `CLEANING` | `CLEANING` | Same as TC-SEARCH-03. | | |
| TC-SEARCH-05 | Search trims whitespace | Seeded | 1. Type `   cleaning   ` | — | Same as TC-SEARCH-03. | | |
| TC-SEARCH-06 | No-match search shows empty state | Seeded | 1. Type `zzzz` | — | Empty state row. URL preserves q. | | |
| TC-SEARCH-07 | Special chars do not 500 | Seeded | 1. Type `%' OR 1=1 --` | SQL-injection-style | 200, zero matches, no DB error. | | |

### 4.9 PAGINATION

> Event list does not paginate by default in v1. Skip pagination tests unless ≥20 events are present.

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-PAGE-01 | Page param invalid graceful | Logged in | 1. Visit `/sourcing/?page=abc` | — | No 500 — either ignored or graceful 404. | | |
| TC-PAGE-02 | Filter retained across page | Need >page-size events | 1. `/sourcing/?status=open&page=2` | — | Status filter retained; URL preserves `status=open&page=2`. | | |

### 4.10 FILTERS

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-FILTER-01 | Status filter — Draft | Seeded | 1. Status = `draft` → Filter | — | Only the draft event shown. | | |
| TC-FILTER-02 | Status filter — Open | Seeded | 1. Status = `open` | — | Only the open event. | | |
| TC-FILTER-03 | Status filter — Awarded | Seeded | 1. Status = `awarded` | — | Only the awarded event. | | |
| TC-FILTER-04 | Event type filter — RFQ | Seeded events have type rfq | 1. Type = `rfq` | — | Only rfq events. | | |
| TC-FILTER-05 | Category filter populates with tenant categories | Categories exist | 1. Open category dropdown | — | Lists tenant VendorCategory rows only. No cross-tenant categories. | | |
| TC-FILTER-06 | Filter + search combined | Seeded | 1. `/sourcing/?q=hardware&status=open` | — | Rows are intersection. Both controls retain values. | | |
| TC-FILTER-07 | Zero-match filter shows empty state | Seeded | 1. Status = `under_evaluation` (none seeded) | — | Empty state row shown. | | |

### 4.11 Status Transitions / Custom Actions

> This is the heart of Module 6. Every transition exercises a service in [apps/sourcing/services.py](../../apps/sourcing/services.py) and must verify persisted side effects.

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-ACTION-01 | Publish blocked when items missing | Draft event with 0 items | 1. Click Publish | — | Error toast listing missing prerequisites (≥1 item, ≥1 invitee, ≥1 criterion, weights sum to 100, close_at set). Status stays `draft`. (Per `validate_event_can_publish()`.) | | |
| TC-ACTION-02 | Publish blocked when weights ≠ 100 | Items + invitees + 3 criteria summing to 80 | 1. Publish | — | Error: `Criteria weights must sum to 100% (currently 80%).` | | |
| TC-ACTION-03 | Publish — future publish_at → scheduled | All prereqs met; publish_at = +5d | 1. Publish | — | Status `scheduled`. Toast confirms. Detail page now shows "Open for bids now" button. | | |
| TC-ACTION-04 | Publish — past publish_at → directly open | publish_at = yesterday; all prereqs met | 1. Publish | — | Status jumps `draft → open`. Bid list now accessible to invited vendors. | | |
| TC-ACTION-05 | Open scheduled event manually | Scheduled event | 1. Click **Open for bids now** | — | Status `open`. publish_at set to now if blank. | | |
| TC-ACTION-06 | Close open event | Open event with 1 draft + 1 submitted bid | 1. Click **Close bidding** → confirm | — | Status `closed`. The draft bid is auto-set to `rejected` (per `close_event()` — auto-rejects unsubmitted). Submitted bid stays `submitted`. Sealed gate lifts — buyers now see bid contents. | | |
| TC-ACTION-07 | Cancel event with reason | Open event | 1. Click Cancel → enter reason `Budget cut`<br>2. Confirm | reason `Budget cut` | Status `cancelled`. In-flight bids (draft/submitted/under_review) flipped to `withdrawn` (per `cancel_event()`). `event.cancelled_reason/at/by` populated. | | |
| TC-ACTION-08 | Cannot cancel awarded event | Awarded event | 1. Cancel button hidden / disabled | — | Per `can_cancel` property — awarded events cannot be cancelled. | | |
| TC-ACTION-09 | Vendor submit bid — happy path | Vendor V has draft bid with all unit_price > 0 | 1. As V, click **Submit bid** → confirm | — | Status `submitted`. `submitted_at` stamped. `total_amount` recomputed from lines. Invitee status `submitted`. Bid is now locked (no edit). | | |
| TC-ACTION-10 | Vendor submit bid blocked when price = 0 | Draft bid with at least one line unit_price = 0 | 1. Submit | — | Error toast: `All line items must have a unit price > 0.` Status stays `draft`. | | |
| TC-ACTION-11 | Vendor withdraw submitted bid (event open) | Vendor V has submitted bid; event open | 1. Click Withdraw → confirm | — | Status `withdrawn`. Invitee status flipped to `withdrawn`. | | |
| TC-ACTION-12 | Vendor withdraw blocked when event closed | Vendor V has submitted bid; event closed | 1. Withdraw | — | Error: cannot withdraw after event closes. Status stays `submitted`. | | |
| TC-ACTION-13 | Vendor decline invitation | Invitee status invited | 1. Click Decline on the invitation row → confirm | — | Status `declined`. Cannot start a bid afterwards. | | |
| TC-ACTION-14 | Evaluate a bid (panel scoring) | Closed event with 1 submitted bid; login as `mgr_acme` (in EVALUATE_ROLES) | 1. Bids tab → click **Evaluate** on a bid<br>2. Fill score for each of 4 criteria (e.g. 80, 70, 90, 85)<br>3. Save | scores | Toast `Evaluation saved.` BidEvaluation rows created (1 per criterion for this evaluator). Bid status auto-promoted `submitted → under_review`. Event status auto-promoted `closed → under_evaluation`. `bid.overall_score` recomputed. | | |
| TC-ACTION-15 | Second evaluator scores same bid | TC-ACTION-14 done; login as `approver_acme` | 1. Open same bid evaluate page<br>2. Submit different scores (e.g. 100, 60, 100, 50) | scores | New evaluation rows for evaluator2. `bid.overall_score` reflects average per criterion across both evaluators (per `recompute_bid_scores()`). | | |
| TC-ACTION-16 | Evaluation blocked pre-close | Open event with submitted bid | 1. As `mgr_acme`, try `/sourcing/<open-pk>/bids/<bpk>/evaluate/` | — | Redirect / error: event must be closed before evaluation. | | |
| TC-ACTION-17 | Score validation (range) | Evaluating a bid | 1. Type score `150` (criterion.max_score=100) | — | Form error: `Score must be between 0 and 100.` | | |
| TC-ACTION-18 | Shortlist bid | Closed event with bid in submitted or under_review | 1. As manager, click **Shortlist** on bid detail | — | Bid status `shortlisted`. | | |
| TC-ACTION-19 | Reject bid | Closed event with bid not awarded | 1. Click **Reject** | — | Bid status `rejected`. | | |
| TC-ACTION-20 | Recommend award | Closed event with ≥1 non-withdrawn bid | 1. Click **Recommend award**<br>2. Pick vendor, amount = winning bid total, justification `Best score and price`<br>3. Save | — | SourcingAward created with status `recommended`. Awards table shows the row. | | |
| TC-ACTION-21 | Recommend blocked when allow_partial_award=False and award exists | Event has 1 recommended award, allow_partial_award=False | 1. Try Recommend again | — | Error: `This event does not allow partial awards.` No second award. | | |
| TC-ACTION-22 | Recommend allowed for partial-award event | allow_partial_award=True | 1. Recommend a second vendor | — | Second SourcingAward row created. | | |
| TC-ACTION-23 | Finalize award | Recommended award exists | 1. Click **Finalize award** | — | All recommended → `approved`. Winning Bid status → `awarded`. Non-winning non-withdrawn/non-rejected bids → `rejected`. `event.status` → `awarded`. `event.awarded_vendor/amount/at` denormalised. | | |
| TC-ACTION-24 | Cannot evaluate after awarded | Event awarded | 1. Try evaluate on a bid | — | Redirect / error — evaluation closed. | | |
| TC-ACTION-25 | Compliance flag — submit with 0 quantity | Draft bid with one line qty_offered=0 | 1. Submit | — | Bid submitted but `is_compliant=False`. Bid list shows ✗ (red X) for compliance. | | |
| TC-ACTION-26 | Audit log entries written | After any transition above | 1. Visit `/tenants/audit/` (or relevant audit page) | — | Audit entries for `sourcing.event.publish`, `sourcing.bid.submit`, etc. with actor + target + message. | | |

### 4.12 Frontend UI / UX

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-UI-01 | Browser tab title | Each page | 1. Open each major page | — | Titles match (Events, New Event, <event-number>, My Invitations, etc.). | | |
| TC-UI-02 | Sidebar active state | Logged in | 1. Visit `/sourcing/` | — | Sourcing group highlighted. | | |
| TC-UI-03 | Breadcrumb on event detail | Any event | 1. Open detail | — | Breadcrumb: `Sourcing › <event-number>`. | | |
| TC-UI-04 | Status badge colors | Mixed-status events | 1. Visit `/sourcing/` | — | draft=secondary, scheduled=info, open=success, closed=warning, under_evaluation=warning, awarded=primary/green, cancelled=danger. | | |
| TC-UI-05 | Sealed-bid lock icon | Open event | 1. Bids tab on open event | — | Large lock icon + clear message. | | |
| TC-UI-06 | Empty state — no events | New tenant | 1. Visit `/sourcing/` | — | Friendly empty state with CTA. | | |
| TC-UI-07 | Decision buttons large + clear (vendor side) | Vendor with draft bid | 1. Bid edit page | — | Save draft + Submit + Withdraw buttons clearly distinct, big, color-coded. | | |
| TC-UI-08 | Toast auto-dismiss | Any action | 1. Trigger success | — | Green toast dismisses after a few seconds. | | |
| TC-UI-09 | Confirm dialogs name the entity | Close / Cancel / Delete actions | 1. Click each | — | Dialog mentions event name + action. | | |
| TC-UI-10 | Mobile vendor portal 375×667 | DevTools mobile | 1. Visit `/vendor-portal/sourcing/` and `/vendor-portal/sourcing/<event-pk>/bid/<bpk>/` | — | Layout stacks. Buttons tap-friendly. Tables scroll horizontally if needed. | | |
| TC-UI-11 | Bid compare matrix readability | Closed event with ≥3 bids | 1. Visit compare page | — | Header row sticky / clearly labeled. Best price per row highlighted (if implemented). | | |
| TC-UI-12 | No console errors | All pages | 1. Open DevTools console | — | No red errors on any major page. | | |

### 4.13 Negative & Edge Cases — including security boundary

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-NEG-01 | All required fields blank on event form | Logged in | 1. `/sourcing/new/` → blank Save | — | Errors on Title (and any other required field). No 500. | | |
| TC-NEG-02 | Decimal fields with letters | Event form | 1. Estimated `abc` | — | Decimal validation error. No 500. | | |
| TC-NEG-03 | Negative estimated_value | Event form | 1. Estimated `-100` | — | Field validation error (`MinValueValidator(0)` on model). | | |
| TC-NEG-04 | Date in past for publish_at | Event form | 1. publish_at = yesterday | — | Saves (past publish_at is allowed — it means publish-now per TC-ACTION-04). NOT an error. | | |
| TC-NEG-05 | Double-click rapid submit on Publish | Draft event ready to publish | 1. Click Publish twice fast | — | At most one transition. No duplicate state. | | |
| TC-NEG-06 | Refresh after POST does not duplicate | After publishing | 1. F5 on redirected page | — | No POST replay (Post/Redirect/Get). | | |
| TC-NEG-07 | XSS in event description | Event form | 1. Description `<script>alert(1)</script>` | — | Escaped on render. No popup. | | |
| TC-NEG-08 | XSS in bid notes | Vendor bid form | 1. Notes `<img src=x onerror=alert(1)>` | — | Escaped on render of buyer's bid detail. No popup. | | |
| TC-NEG-09 | **SEALED BID — buyer reading bid lines pre-close** ⚠ SECURITY | Vendor V submitted bid on event E; E still open | 1. As `admin_acme`, visit `/sourcing/<E-pk>/bids/<bpk>/` directly<br>2. Inspect DOM for unit prices | — | **Page does NOT render line prices, totals, vendor name, or documents.** Only the sealed-message shell is in the DOM (per `bid_visible_to()` in [apps/sourcing/services.py:48-63](../../apps/sourcing/services.py#L48-L63)). If any bid detail leaks, log as **Critical security bug**. | | |
| TC-NEG-10 | **SEALED BID — buyer reading bid lines via compare URL** ⚠ SECURITY | Same setup | 1. Visit `/sourcing/<E-pk>/bids/compare/` | — | Redirect / error. Compare page must not render pre-close. If matrix renders, log Critical. | | |
| TC-NEG-11 | **SEALED BID — buyer scoring bid pre-close** ⚠ SECURITY | Same setup | 1. As `mgr_acme`, visit evaluate URL | — | Blocked with error. Per TC-ACTION-16. | | |
| TC-NEG-12 | **SEALED BID — cross-vendor read** ⚠ SECURITY | Vendor A has submitted bid; Vendor B is also invited | 1. As Vendor B's portal user, try `/vendor-portal/sourcing/<E>/bid/<A-bpk>/view/` | — | 404 / forbidden. Vendor B cannot see Vendor A's bid at any time. | | |
| TC-NEG-13 | Cannot submit bid after event closed | Vendor V has draft bid; event just closed | 1. Try Submit | — | Error: event not open. Draft was auto-rejected by `close_event()` anyway. | | |
| TC-NEG-14 | Cannot recommend award before close | Open event | 1. As manager, try `/sourcing/<open-pk>/awards/recommend/` | — | Error: event must be closed/under_evaluation. | | |
| TC-NEG-15 | Cannot recommend a withdrawn vendor | Vendor V withdrew their bid | 1. Recommend award form → V not in vendor dropdown | — | Only vendors with non-withdrawn bids listed. | | |
| TC-NEG-16 | Score boundary 0 | Evaluation | 1. Score `0` | — | Accepted (0 is valid). | | |
| TC-NEG-17 | Score boundary max | Evaluation | 1. Score = max_score (100) | — | Accepted. | | |
| TC-NEG-18 | Score above max | Evaluation | 1. Score `101` | — | Form error. | | |
| TC-NEG-19 | Bid document — wrong file type | Vendor bid | 1. Try upload `.exe` | — | Either accepted (no extension filter in form) — log as Low if security policy requires whitelisting. | | |
| TC-NEG-20 | Re-uploading same document creates duplicate | Vendor bid | 1. Upload same file twice | — | Two rows in documents table. Acceptable per current design (no de-dup). | | |
| TC-NEG-21 | Publish with publish_at far past | All prereqs met; publish_at = 1 year ago | 1. Publish | — | Goes straight to `open`. close_at and award_target unchanged. | | |

### 4.14 Cross-Module Integration

| ID | Title | Pre-condition | Steps | Test Data | Expected Result | Pass/Fail | Notes |
|---|---|---|---|---|---|---|---|
| TC-INT-01 | Approved requisition shows Create Sourcing Event button | Approved requisition exists | 1. Open `/requisitions/<approved-pk>/` | — | Button **Create Sourcing Event** visible in sidebar (per [templates/requisitions/requisitions/detail.html:239-243](../../templates/requisitions/requisitions/detail.html#L239-L243)). | | |
| TC-INT-02 | Draft/submitted requisition does NOT show the button | Draft requisition | 1. Open detail | — | Button hidden. Only `status='approved'` exposes it. | | |
| TC-INT-03 | Create event from requisition pre-fills items | Approved requisition with 3 lines | 1. Click Create Sourcing Event<br>2. Save | — | New event has 3 items copied from req.lines (description, qty, unit_price, account_code, required_date). `event.requisition` FK set. | | |
| TC-INT-04 | Event sidebar links back to requisition | Event created from requisition | 1. Open event detail | — | Sidebar shows "Source requisition: <REQ-NUMBER>" link to `/requisitions/<pk>/`. | | |
| TC-INT-05 | Invitee dropdown filters by tenant | Login as `admin_acme` | 1. Open invite dialog | — | Only Acme active non-suspended/non-blacklisted vendors listed. | | |
| TC-INT-06 | Vendor blacklist event impact (if any) | Active vendor V with portal user; blacklist V | 1. Blacklist V via vendor admin<br>2. Try inviting V to a new event | — | V no longer appears in invite dropdown. V's existing invitations remain (current behaviour — confirm with team). | | |
| TC-INT-07 | Audit log captures publish + finalize | Run TC-ACTION-04 and TC-ACTION-23 | 1. Visit `/tenants/audit/` | — | Two audit entries: `sourcing.event.publish` and `sourcing.award.finalize` with actor + target. | | |

---

## 5. Bug Log

| Bug ID | Test Case ID | Severity | Page URL | Steps to Reproduce | Expected | Actual | Screenshot | Browser |
|---|---|---|---|---|---|---|---|---|
| BUG-01 | | | | | | | | |
| BUG-02 | | | | | | | | |
| BUG-03 | | | | | | | | |
| BUG-04 | | | | | | | | |
| BUG-05 | | | | | | | | |

> **Sealed-bid violations (TC-NEG-09 / 10 / 12) → Critical.** All other security-boundary failures → High at minimum.

---

## 6. Sign-off & Release Recommendation

| Section | Total | Pass | Fail | Blocked | Notes |
|---|---:|---:|---:|---:|---|
| 4.1 Authentication & Access | 9 | | | | |
| 4.2 Multi-Tenancy Isolation | 6 | | | | |
| 4.3 CREATE | 20 | | | | |
| 4.4 READ — List Page | 7 | | | | |
| 4.5 READ — Detail Page | 11 | | | | |
| 4.6 UPDATE | 6 | | | | |
| 4.7 DELETE | 8 | | | | |
| 4.8 SEARCH | 7 | | | | |
| 4.9 PAGINATION | 2 | | | | |
| 4.10 FILTERS | 7 | | | | |
| 4.11 Status Transitions / Custom Actions | 26 | | | | |
| 4.12 Frontend UI / UX | 12 | | | | |
| 4.13 Negative & Edge Cases | 21 | | | | |
| 4.14 Cross-Module Integration | 7 | | | | |
| **Total** | **149** | | | | |

**Release recommendation:** ☐ GO ☐ NO-GO ☐ GO-with-fixes

**Tester:** _______________ **Date:** _______________

**Rationale (one sentence):**
______________________________________________________________________________

---

> Companion automation skill: [/sqa-review](../skills/sqa-review/SKILL.md). The sealed-bid gate ([apps/sourcing/services.py:48-63](../../apps/sourcing/services.py#L48-L63)) is the most important boundary to lock in automated regression tests after the manual pass.
