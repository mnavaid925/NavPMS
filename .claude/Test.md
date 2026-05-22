# Module 2 — User Dashboard & Portal — Comprehensive SQA Test Report

**Target:** [apps/portal/](../apps/portal/) — NavPMS Module 2 (User Dashboard & Portal). Scope mode: **Module review** (full app, end-to-end).
**Reviewer:** Senior SQA Engineer.
**Codebase snapshot:** branch `main` @ `0f90d1e`.
**Stack:** Django 4.2.28, MySQL 8, Bootstrap 5.3, custom `accounts.User`, multi-tenant.

---

## 1. Module Analysis

### 1.1 Surface area & shipping state

Module 2 delivers the five PMS portal sub-modules across ~1,366 LoC:

| Sub-module | Purpose | Key models / code |
|---|---|---|
| 2.1 Personalized Overview | Per-user customizable dashboard widgets | [`DashboardWidget`](../apps/portal/models.py#L21), [`build_dashboard_context`](../apps/portal/services.py#L67), [`ensure_default_widgets`](../apps/portal/services.py#L57) |
| 2.2 Task & Alert Center | Per-user notifications with read state | [`Notification`](../apps/portal/models.py#L69), [`create_notification`](../apps/portal/services.py#L31) |
| 2.3 Quick Requisition Entry | Fast-track requisitions + line items | [`QuickRequisition`](../apps/portal/models.py#L119), [`QuickRequisitionItem`](../apps/portal/models.py#L192), [`next_requisition_number`](../apps/portal/services.py#L17) |
| 2.4 Recent Activity Feed | Read-only view over `tenants.AuditLog` | [`ActivityFeedView`](../apps/portal/views.py#L456) (no own model) |
| 2.5 Self-Service Reporting | Saved report definitions + chart render | [`SavedReport`](../apps/portal/models.py#L223), [`generate_report`](../apps/portal/services.py#L116) |

Code volume: [models.py](../apps/portal/models.py) (249), [views.py](../apps/portal/views.py) (575), [services.py](../apps/portal/services.py) (212), [forms.py](../apps/portal/forms.py) (73), [urls.py](../apps/portal/urls.py) (44), [admin.py](../apps/portal/admin.py) (52), [seed_portal.py](../apps/portal/management/commands/seed_portal.py) (154). 13 templates under [templates/portal/](../templates/portal/). Mounted at `/portal/` ([config/urls.py:12](../config/urls.py#L12)).

### 1.2 Architecture & dependencies

| Concern | Implementation | Reference |
|---|---|---|
| Auth + tenant gate | All 25 views inherit `TenantRequiredMixin` (`LoginRequiredMixin` + `UserPassesTestMixin`, `test_func` requires `request.tenant`) | [core/mixins.py:6](../apps/core/mixins.py#L6) |
| Tenant resolution | `TenantMiddleware` sets `request.tenant` + thread-local from `request.user.tenant` | [core/middleware.py](../apps/core/middleware.py) |
| Tenant auto-scoping | `TenantAwareModel.objects` (`TenantManager`) auto-filters by current tenant; `all_objects` is unscoped | [core/models.py:25](../apps/core/models.py#L25) |
| Audit trail | `record_audit()` writes `tenants.AuditLog` (append-only) on requisition create/submit | [tenants/services.py:151](../apps/tenants/services.py#L151) |
| Cross-module read | Activity feed + `my_activity` report read `tenants.AuditLog` | [views.py:462](../apps/portal/views.py#L462) |

### 1.3 Business rules (each linked)

| # | Rule | Source |
|---|---|---|
| BR-1 | Every portal queryset is scoped to **both** `tenant=request.tenant` **and** `user=request.user` — data is per-user, not just per-tenant | [views.py:35](../apps/portal/views.py#L35), passim |
| BR-2 | Only `status='draft'` requisitions are editable/deletable; enforced by `is_editable` property + view guards | [models.py:178](../apps/portal/models.py#L178), [views.py:342](../apps/portal/views.py#L342) |
| BR-3 | Submitting requires `status=='draft'` **and** at least one line item | [views.py:387-392](../apps/portal/views.py#L387-L392) |
| BR-4 | `QuickRequisitionItem.line_total` is auto-computed `quantity * unit_price` on save | [models.py:216](../apps/portal/models.py#L216) |
| BR-5 | `QuickRequisition.estimated_total` is recomputed from items via `recalc_total()` after each item add/delete | [models.py:183](../apps/portal/models.py#L183), [views.py:427](../apps/portal/views.py#L427) |
| BR-6 | Requisition numbers are `QR-<SLUG6>-NNNNN`, sequence per tenant, `number` globally `unique=True` | [services.py:17](../apps/portal/services.py#L17), [models.py:148](../apps/portal/models.py#L148) |
| BR-7 | First portal visit provisions 6 default widgets via `ensure_default_widgets` | [services.py:57](../apps/portal/services.py#L57) |
| BR-8 | Activity feed is **read-only** — no create/edit/delete (correct for an audit view) | [views.py:456](../apps/portal/views.py#L456) |
| BR-9 | Approval decisions (`approved`/`rejected`, `decided_by`) are **not** settable in this module — only the seeder populates them; live decision flow belongs to Module 4 (Approvals) | [seed_portal.py:130](../apps/portal/management/commands/seed_portal.py#L130) |

### 1.4 Pre-test risk profile

| Area | Risk | Rationale |
|---|---|---|
| Tenant/user isolation | **Low** | Consistent double-scoped `get_object_or_404` + `TenantManager`; no `Model.objects.all()` found |
| Input validation | **High** | Forms expose `DecimalField`s with **no `MinValueValidator`**; `link_url` is unvalidated free text |
| Injection / XSS | **Medium** | `{{ ...|safe }}` in report chart script; user-controlled `link_url` rendered as `href` |
| Concurrency | **Medium** | Count-based requisition numbering races under load |
| CRUD completeness | **Low** | All entities have list/create/detail/edit/delete (widgets have no detail by design) |
| Performance | **Low–Medium** | Dashboard ≈14 queries; `spend_by_month` aggregates in Python |

---

## 2. Test Plan

| Layer | Coverage | Priority |
|---|---|---|
| **Unit** | `is_editable`, `col_class`, `mark_read`, `recalc_total`, `QuickRequisitionItem.save` line-total, `next_requisition_number`, `generate_report` per report type, `_report_window` defaults | P1 |
| **Integration** | Each view: GET render + POST happy path + invalid form; `ensure_default_widgets` provisioning; submit flow → audit + notification side effects | P1 |
| **Functional** | End-to-end: create requisition → add items → submit → appears on dashboard → spawns notification → shows in activity feed → surfaces in saved report | P1 |
| **Regression** | Draft-only edit/delete guard; "already submitted" guard; "items required to submit" guard; widget default-provisioning idempotency | P1 |
| **Boundary** | `title`/`number` max lengths, `Decimal` max_digits (12,2 / 14,2), `link_url` 300 chars, `position` `PositiveIntegerField` | P2 |
| **Edge** | Empty/null `needed_by`, unicode/emoji titles, whitespace-only search `q`, zero-item requisition submit, report with no data, `report_type` not in any branch | P2 |
| **Negative** | Negative quantity/unit_price, cross-user IDOR, cross-tenant IDOR, edit/delete on non-draft, duplicate `number`, invalid `widget_type`, GET on POST-only views | P1 |
| **Security** | OWASP A01-A10 (see §6 mapping); CSRF on every POST; open-redirect `next`; `javascript:` `link_url`; `|safe` chart sink | P1 |
| **Performance** | Dashboard query count; notification/requisition list at 1k rows; `generate_report` at scale | P2 |
| **Usability** | Filter retention across pagination; status-conditional action buttons; empty-state messaging | P3 |

Out of scope (correctly): live approval decisioning (Module 4), payment, cross-tenant admin reporting.

---

## 3. Test Scenarios

| # | Scenario | Type |
|---|---|---|
| W-01 | First portal visit provisions exactly 6 default widgets | Functional |
| W-02 | Second visit does **not** duplicate widgets (`ensure_default_widgets` idempotent) | Regression |
| W-03 | Create widget → appears in list & on dashboard | Integration |
| W-04 | Edit widget type/size/position/visibility | Integration |
| W-05 | Delete widget (POST) | Integration |
| W-06 | GET on `widget_delete` redirects to list, deletes nothing | Negative |
| W-07 | Filter list by `widget_type` and `visible` | Functional |
| W-08 | `is_visible=False` widget hidden from dashboard but shown in list | Edge |
| W-09 | Edit/delete another user's widget → 404 | Negative (IDOR) |
| W-10 | `col_class` maps size→Bootstrap column correctly | Unit |
| N-01 | Create notification, list shows unread count | Integration |
| N-02 | Open detail → auto `mark_read`, `read_at` set | Functional |
| N-03 | Toggle read/unread via `notification_mark_read` | Integration |
| N-04 | Mark-all-read clears unread count | Functional |
| N-05 | Edit / delete notification | Integration |
| N-06 | Filter by `q` / `category` / `priority` / `read` | Functional |
| N-07 | `mark_read` on already-read row → toggles back to unread | Regression |
| N-08 | Cross-user notification detail → 404 | Negative (IDOR) |
| N-09 | `link_url='javascript:alert(1)'` accepted & rendered as live `href` | Security (A03) |
| N-10 | `next` POST param controls post-toggle redirect target | Security (A01) |
| R-01 | Create requisition → auto `number`, `status='draft'`, audit row written | Functional |
| R-02 | Add line item → `line_total` + `estimated_total` recompute | Functional |
| R-03 | Delete line item → `estimated_total` recompute | Integration |
| R-04 | Submit draft with items → `status='submitted'`, `submitted_at`, audit + notification | Functional |
| R-05 | Submit draft with **zero** items → blocked | Regression |
| R-06 | Submit already-submitted requisition → no-op info message | Regression |
| R-07 | Edit/delete non-draft requisition → blocked, redirect to detail | Regression |
| R-08 | Add/delete items on non-draft → blocked | Regression |
| R-09 | Cross-user / cross-tenant requisition detail → 404 | Negative (IDOR) |
| R-10 | Negative `quantity` / `unit_price` accepted by item form | Negative (A04) |
| R-11 | Concurrent create → duplicate `number` `IntegrityError` | Negative (concurrency) |
| R-12 | Filter list by `q` / `status` / `category` | Functional |
| R-13 | Item-delete `item_pk` belonging to another requisition → 404 | Negative (IDOR) |
| A-01 | Activity feed lists only current user's audit rows | Functional |
| A-02 | Filter feed by `q` / `level` | Functional |
| A-03 | Feed has no create/edit/delete routes | Regression |
| RP-01 | Create report → redirect to run page, computes result | Functional |
| RP-02 | `generate_report` per type: spend_by_category / _by_month / requisition_status / my_activity / notification_summary | Unit |
| RP-03 | Report with no data → empty labels/values, no crash | Edge |
| RP-04 | `report_type` unmatched → empty payload fallback | Edge |
| RP-05 | Run page updates `last_run_at` on each GET | Integration |
| RP-06 | `_report_window` defaults to last 90 days when dates blank | Unit |
| RP-07 | `{{ result.labels|safe }}` rendered raw into `<script>` | Security (A03) |
| RP-08 | Cross-user report run → 404 | Negative (IDOR) |
| D-01 | Dashboard aggregates (counts, spend, unread) match DB | Functional |
| D-02 | Dashboard query count within budget | Performance |
| S-01 | Anonymous user → all `/portal/*` redirect to login | Security (A01) |
| S-02 | Authenticated user with `tenant=None` → redirect to onboarding | Security (A01) |
| S-03 | POST without CSRF token → 403 on every mutating view | Security (A03) |
| P-01 | Notification/requisition list at 1,000 rows paginates without N+1 | Performance |

---

## 4. Detailed Test Cases

> ID format `TC-<ENTITY>-<NNN>`. Pre-conditions assume a seeded tenant `t`, tenant member `u`, and `client` logged in as `u` unless stated.

### 4.1 Personalized Overview / Widgets

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| TC-W-001 | Default widgets provisioned on first visit | `u` has 0 widgets | GET `/portal/` | — | 6 `DashboardWidget` rows created for `(t,u)` with positions 0-5 | Widgets persist |
| TC-W-002 | Provisioning idempotent | Run TC-W-001 | GET `/portal/` again | — | Still exactly 6 widgets (no duplicates) | — |
| TC-W-003 | Create widget | — | POST `/portal/widgets/create/` | `widget_type=my_reports, title=Reports, size=medium, position=9, is_visible=on` | 302→`widget_list`; widget owned by `(t,u)` | +1 widget |
| TC-W-004 | Edit widget | Widget `w` exists | POST `/portal/widgets/<w>/edit/` | `size=large` | `w.size='large'`, 302→list | — |
| TC-W-005 | Delete widget (POST) | Widget `w` exists | POST `/portal/widgets/<w>/delete/` | — | `w` deleted, 302→list | -1 widget |
| TC-W-006 | GET delete is a no-op | Widget `w` exists | GET `/portal/widgets/<w>/delete/` | — | 302→list, `w` still exists | — |
| TC-W-007 | IDOR — edit other user's widget | `w2` owned by `u2` | GET `/portal/widgets/<w2>/edit/` as `u` | — | HTTP 404 | — |
| TC-W-008 | Hidden widget excluded from dashboard | `w.is_visible=False` | GET `/portal/` | — | `w` absent from `widgets` context; still in `/portal/widgets/` | — |
| TC-W-009 | Filter by type retained across pages | >20 widgets | GET `/portal/widgets/?widget_type=spend_summary&page=2` | — | Page 2 shows only `spend_summary`; page links keep `widget_type` | — |
| TC-W-010 | `col_class` mapping | — | Unit: `DashboardWidget(size=s).col_class` | s∈{small,medium,large,bogus} | `col-lg-4 / col-lg-6 / col-12 / col-lg-4` | — |

### 4.2 Task & Alert Center / Notifications

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| TC-N-001 | Create alert | — | POST `/portal/notifications/create/` | `category=info, priority=normal, title=Hi, message=x` | 302→list; row owned by `(t,u)`, `is_read=False` | +1 unread |
| TC-N-002 | Detail auto-marks read | Unread note `n` | GET `/portal/notifications/<n>/` | — | `n.is_read=True`, `read_at` set | unread-1 |
| TC-N-003 | Toggle read→unread | Read note `n` | POST `/portal/notifications/<n>/toggle-read/` | — | `n.is_read=False`, `read_at=None` | — |
| TC-N-004 | Mark all read | 3 unread | POST `/portal/notifications/mark-all-read/` | — | All `(t,u)` unread→read; `unread_count=0` | — |
| TC-N-005 | Edit / delete alert | Note `n` | POST edit then delete | `title=Edited` | Edit persists; delete removes row | — |
| TC-N-006 | Filter combinations | Mixed notes | GET `?q=&category=approval&priority=urgent&read=unread` | — | Only matching rows; selects keep value | — |
| TC-N-007 | IDOR — other user's note | `n2` owned by `u2` | GET `/portal/notifications/<n2>/` as `u` | — | HTTP 404 | — |
| TC-N-008 | **`javascript:` link_url** | — | POST create with `link_url=javascript:alert(document.cookie)` | — | **DEFECT D-02**: form valid; detail renders `<a href="javascript:...">` — clickable script | — |
| TC-N-009 | **Open-redirect `next`** | Note `n` | POST `/portal/notifications/<n>/toggle-read/` with `next=https://evil.example` | — | **DEFECT D-03**: 302 to external host | — |
| TC-N-010 | CSRF enforced | — | POST create without token | — | HTTP 403 | — |

### 4.3 Quick Requisition Entry

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| TC-R-001 | Create requisition | — | POST `/portal/requisitions/create/` | `title=Pens, category=office_supplies, priority=normal, currency=USD` | 302→detail; `number=QR-<slug6>-NNNNN`, `status=draft`; `AuditLog action=requisition.created` written | +1 req, +1 audit |
| TC-R-002 | Add item recomputes totals | Draft `r` | POST `/portal/requisitions/<r>/items/add/` | `name=Pen, quantity=10, unit=box, unit_price=6.00` | `item.line_total=60.00`; `r.estimated_total=60.00` | +1 item |
| TC-R-003 | Delete item recomputes | `r` with 2 items | POST item delete | — | `estimated_total` drops by removed line | -1 item |
| TC-R-004 | Submit draft with items | Draft `r`, ≥1 item | POST `/portal/requisitions/<r>/submit/` | — | `status=submitted`, `submitted_at` set; `AuditLog requisition.submitted`; self-notification created | — |
| TC-R-005 | Submit with zero items blocked | Draft `r`, 0 items | POST submit | — | Error message; `status` stays `draft` | — |
| TC-R-006 | Re-submit blocked | `r.status=submitted` | POST submit | — | Info message "already submitted"; no change | — |
| TC-R-007 | Edit non-draft blocked | `r.status=submitted` | GET/POST edit | — | Error message, 302→detail; unchanged | — |
| TC-R-008 | Delete non-draft blocked | `r.status=approved` | POST delete | — | Error message, 302→detail; row kept | — |
| TC-R-009 | Item add on non-draft blocked | `r.status=submitted` | POST item add | — | Error message; no item created | — |
| TC-R-010 | IDOR cross-user/tenant | `r2` owned by `u2`/`t2` | GET `/portal/requisitions/<r2>/` as `u` | — | HTTP 404 | — |
| TC-R-011 | **Negative quantity/price** | Draft `r` | POST item add `quantity=-5, unit_price=-10` | — | **DEFECT D-01**: form valid (verified); `line_total=50.00` from two negatives → corrupt data | — |
| TC-R-012 | **Concurrent numbering race** | — | Two parallel POSTs to create | — | **DEFECT D-04**: both compute same `count` → second hits `IntegrityError` (unhandled 500) | — |
| TC-R-013 | Item-delete wrong parent | `item` of `r`, target `r_other` | POST `/portal/requisitions/<r_other>/items/<item>/delete/` | — | HTTP 404 (item not under `r_other`) | — |
| TC-R-014 | Filter list | Mixed reqs | GET `?q=QR&status=draft&category=travel` | — | Only matching rows; selects keep value | — |
| TC-R-015 | Boundary — `title` 160 / 161 chars | — | POST create | 160-char / 161-char title | 160 accepted; 161 → form error | — |

### 4.4 Recent Activity Feed

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| TC-A-001 | Feed shows only own audit rows | `u` and `u2` both have audit rows | GET `/portal/activity/` | — | Only `(t,u)` rows; `u2` rows absent | — |
| TC-A-002 | Filter by action text & level | Mixed logs | GET `?q=requisition&level=info` | — | Only matching rows | — |
| TC-A-003 | Feed is read-only | — | Inspect `urls.py` | — | No create/edit/delete routes for activity | — |

### 4.5 Self-Service Reporting

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| TC-RP-001 | Create report | — | POST `/portal/reports/create/` | `name=Spend, report_type=spend_by_category` | 302→`report_run`; result computed | +1 report |
| TC-RP-002 | Each report type computes | Seeded approved reqs + audit | Unit: `generate_report(r)` for all 5 types | — | Correct `kind`, `labels`, `values`, `summary`; no exception | — |
| TC-RP-003 | Empty-data report | New tenant, no data | Run `spend_by_category` | — | `labels=[], values=[]`, page renders | — |
| TC-RP-004 | Unknown report_type fallback | `report_type` patched to `bogus` | `generate_report` | — | `{kind:'bar', labels:[], values:[], rows:[], summary:{}}` | — |
| TC-RP-005 | Run updates `last_run_at` | Report `r` | GET `/portal/reports/<r>/` twice | — | `last_run_at` advances each GET (**D-06**: side-effecting GET) | — |
| TC-RP-006 | `_report_window` default | `date_from/date_to` blank | Unit | — | window = today-90d … today | — |
| TC-RP-007 | **`|safe` chart sink** | Report `my_activity`; an `AuditLog.action` contains `</script>` | Run report | — | **DEFECT D-05**: raw list interpolated into `<script>` breaks out → DOM XSS | — |
| TC-RP-008 | IDOR cross-user report | `r2` owned by `u2` | GET `/portal/reports/<r2>/` as `u` | — | HTTP 404 | — |

### 4.6 Access control & dashboard

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| TC-S-001 | Anonymous blocked | logged out | GET each `/portal/*` URL | all 25 routes | 302→`/accounts/login/?next=…` | — |
| TC-S-002 | Tenant-less user redirected | `u.tenant=None` | GET `/portal/` | — | 302→`tenants:onboarding_start` | — |
| TC-S-003 | CSRF on all POST views | logged in | POST without token to every mutating route | — | HTTP 403 each | — |
| TC-D-001 | Dashboard figures correct | seeded `(t,u)` | GET `/portal/` | — | `draft_count`, `submitted_count`, `approved_count`, `spend_total`, `unread_count` match DB | — |
| TC-D-002 | Dashboard query budget | seeded data | `django_assert_max_num_queries(20)` around GET `/portal/` | — | ≤20 queries; no per-widget query | — |
| TC-P-001 | List scale | 1,000 notifications | GET `/portal/notifications/?page=25` | — | Single page query + count; no N+1; <300 ms | — |

---

## 5. Automation Strategy

### 5.1 Tooling

NavPMS currently has **no test suite, no `pytest.ini`, no `conftest.py`**, and `requirements.txt` does **not** pin pytest. Recommended additions:

```
# requirements-dev.txt (new)
pytest==8.3.4
pytest-django==4.9.0
pytest-cov==6.0.0
factory-boy==3.3.1
bandit==1.8.0
```

E2E/load (optional, later): Playwright, Locust. Static security: `bandit -r apps/portal`.

### 5.2 Suite layout

```
config/
  settings_test.py          # SQLite in-memory + MD5 hasher
pytest.ini
apps/portal/tests/
  __init__.py
  conftest.py               # tenant / user / client fixtures
  test_models.py            # BR-4, BR-5, properties
  test_services.py          # numbering, report engine, widget provisioning
  test_views_widgets.py
  test_views_notifications.py
  test_views_requisitions.py
  test_views_reports.py
  test_views_activity.py
  test_security.py          # OWASP-mapped: IDOR, CSRF, open-redirect, XSS
  test_performance.py       # query budgets
```

### 5.3 `config/settings_test.py`

```python
"""Fast test settings — in-memory SQLite, weak hasher."""
from config.settings import *  # noqa

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
DEBUG = False
```

### 5.4 `pytest.ini`

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings_test
python_files = test_*.py
addopts = --reuse-db --tb=short
```

### 5.5 `apps/portal/tests/conftest.py`

```python
"""Shared fixtures for Module 2 portal tests."""
import pytest

from apps.core.models import Tenant
from apps.accounts.models import User
from apps.portal.models import QuickRequisition


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name='Acme Co', slug='acme')


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name='Globex', slug='globex')


@pytest.fixture
def user(db, tenant):
    return User.objects.create_user(
        username='alice', password='Welcome@123',
        tenant=tenant, is_tenant_admin=True, role='tenant_admin',
    )


@pytest.fixture
def other_user(db, tenant):
    return User.objects.create_user(
        username='bob', password='Welcome@123', tenant=tenant, role='member',
    )


@pytest.fixture
def client_logged_in(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def draft_req(db, tenant, user):
    from apps.portal.services import next_requisition_number
    return QuickRequisition.all_objects.create(
        tenant=tenant, user=user, number=next_requisition_number(tenant),
        title='Stationery', category='office_supplies', status='draft',
    )
```

### 5.6 `test_models.py` — model invariants

```python
"""Unit tests for Module 2 model logic (BR-4, BR-5, properties)."""
from decimal import Decimal
import pytest

from apps.portal.models import DashboardWidget, Notification, QuickRequisitionItem


@pytest.mark.parametrize('size,expected', [
    ('small', 'col-lg-4'), ('medium', 'col-lg-6'),
    ('large', 'col-12'), ('bogus', 'col-lg-4'),
])
def test_widget_col_class(size, expected):
    assert DashboardWidget(size=size).col_class == expected


@pytest.mark.django_db
def test_item_save_computes_line_total(draft_req, tenant):
    item = QuickRequisitionItem(
        tenant=tenant, requisition=draft_req,
        name='Pen', quantity=Decimal('3'), unit_price=Decimal('4.50'),
    )
    item.save()
    assert item.line_total == Decimal('13.50')


@pytest.mark.django_db
def test_recalc_total_sums_items(draft_req, tenant):
    for price in ('10.00', '5.50'):
        QuickRequisitionItem.all_objects.create(
            tenant=tenant, requisition=draft_req, name='x',
            quantity=Decimal('1'), unit_price=Decimal(price),
        )
    assert draft_req.recalc_total() == Decimal('15.50')


@pytest.mark.django_db
def test_mark_read_sets_timestamp(tenant, user):
    n = Notification.all_objects.create(tenant=tenant, user=user, title='Hi')
    n.mark_read()
    assert n.is_read and n.read_at is not None


@pytest.mark.django_db
def test_is_editable_only_draft(draft_req):
    assert draft_req.is_editable
    draft_req.status = 'submitted'
    assert not draft_req.is_editable
```

### 5.7 `test_views_requisitions.py` — integration + guards

```python
"""Integration tests for the Quick Requisition flow."""
import pytest
from django.urls import reverse

from apps.portal.models import QuickRequisition
from apps.tenants.models import AuditLog

pytestmark = pytest.mark.django_db


def test_create_writes_audit(client_logged_in, tenant):
    resp = client_logged_in.post(reverse('portal:requisition_create'), {
        'title': 'Pens', 'category': 'office_supplies',
        'priority': 'normal', 'currency': 'USD',
    })
    req = QuickRequisition.all_objects.get(tenant=tenant, title='Pens')
    assert req.status == 'draft' and req.number.startswith('QR-')
    assert resp.status_code == 302
    assert AuditLog.all_objects.filter(
        tenant=tenant, action='requisition.created', target_id=str(req.id),
    ).exists()


def test_submit_requires_items(client_logged_in, draft_req):
    resp = client_logged_in.post(
        reverse('portal:requisition_submit', args=[draft_req.pk]), follow=True)
    draft_req.refresh_from_db()
    assert draft_req.status == 'draft'
    assert b'at least one item' in resp.content.lower()


def test_edit_blocked_on_non_draft(client_logged_in, draft_req):
    draft_req.status = 'submitted'
    draft_req.save(update_fields=['status'])
    resp = client_logged_in.get(
        reverse('portal:requisition_edit', args=[draft_req.pk]))
    assert resp.status_code == 302  # bounced to detail


def test_idor_other_tenant_404(client, other_tenant, draft_req):
    from apps.accounts.models import User
    intruder = User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant)
    client.force_login(intruder)
    resp = client.get(reverse('portal:requisition_detail', args=[draft_req.pk]))
    assert resp.status_code == 404
```

### 5.8 `test_security.py` — OWASP-mapped (encodes the live defects)

```python
"""Security regression tests — D-01..D-03 FAIL today, pass once §6 is fixed."""
import pytest
from django.urls import reverse

from apps.portal.forms import QuickRequisitionItemForm, NotificationForm
from apps.portal.models import Notification

pytestmark = pytest.mark.django_db


def test_A04_item_form_rejects_negative_values():
    """D-01: quantity/unit_price must not accept negatives."""
    form = QuickRequisitionItemForm(
        {'name': 'X', 'quantity': '-5', 'unit': 'u', 'unit_price': '-10'})
    assert not form.is_valid()           # FAILS until MinValueValidator added
    assert 'quantity' in form.errors


def test_A03_notification_rejects_js_uri():
    """D-02: link_url must reject javascript:/data: schemes."""
    form = NotificationForm({
        'category': 'info', 'priority': 'normal', 'title': 'T',
        'message': 'm', 'link_url': 'javascript:alert(1)'})
    assert not form.is_valid()           # FAILS until clean_link_url added


def test_A01_toggle_read_rejects_external_redirect(client_logged_in, tenant, user):
    """D-03: open redirect via the `next` POST param."""
    n = Notification.all_objects.create(tenant=tenant, user=user, title='Hi')
    resp = client_logged_in.post(
        reverse('portal:notification_mark_read', args=[n.pk]),
        {'next': 'https://evil.example/'})
    assert 'evil.example' not in resp['Location']   # FAILS until host-checked


def test_A01_anonymous_redirected_to_login(client):
    resp = client.get(reverse('portal:dashboard'))
    assert resp.status_code == 302 and 'login' in resp['Location']
```

### 5.9 `test_performance.py`

```python
"""Query-budget guards for Module 2."""
import pytest
from django.urls import reverse

from apps.portal.models import Notification

pytestmark = pytest.mark.django_db


def test_dashboard_query_budget(client_logged_in, django_assert_max_num_queries):
    with django_assert_max_num_queries(20):
        client_logged_in.get(reverse('portal:dashboard'))


def test_notification_list_no_n_plus_one(
        client_logged_in, tenant, user, django_assert_max_num_queries):
    Notification.all_objects.bulk_create([
        Notification(tenant=tenant, user=user, title=f'N{i}') for i in range(60)
    ])
    with django_assert_max_num_queries(8):
        client_logged_in.get(reverse('portal:notification_list'))
```

Run: `pytest apps/portal -q --cov=apps/portal --cov-report=term-missing`.

---

## 6. Defects, Risks & Recommendations

### 6.1 Defect register

| ID | Severity | OWASP | Location | Finding | Recommendation |
|---|---|---|---|---|---|
| **D-01** | **High** | A04 | [forms.py:43-63](../apps/portal/forms.py#L43-L63), [models.py:199-208](../apps/portal/models.py#L199-L208) | **Negative `quantity`/`unit_price` accepted** — verified: `QuickRequisitionItemForm({'quantity':'-5','unit_price':'-10'})` is valid. HTML `min=0` is client-side only; no `MinValueValidator` on the model. Corrupts `line_total`/`estimated_total` and every downstream spend figure. | Add `validators=[MinValueValidator(Decimal('0'))]` to `quantity` and `unit_price` on the model (also covers admin + future APIs). Use a strict `>0` validator on `quantity` if zero-qty lines are invalid. |
| **D-02** | **Medium** | A03 | [forms.py:19-26](../apps/portal/forms.py#L19-L26), [notifications/detail.html:28](../templates/portal/notifications/detail.html#L28) | **`javascript:` URI stored in `link_url`** — verified form-valid; detail page renders `<a href="{{ note.link_url }}">`. Auto-escaping does not neutralise script-scheme URIs → click-to-execute (currently self-XSS, as notes are per-user). | Add `clean_link_url()` rejecting any scheme other than `http`/`https`/site-relative paths; or apply a scheme allowlist at render time. |
| **D-03** | **Medium** | A01 | [views.py:247](../apps/portal/views.py#L247) | **Open redirect** — `NotificationMarkReadView` does `redirect(request.POST.get('next') or 'portal:notification_list')`; `django.shortcuts.redirect` does no host validation, so `next=https://evil/` redirects off-site. CSRF limits cross-site abuse, but the pattern is unsafe. | Validate with `django.utils.http.url_has_allowed_host_and_scheme(nxt, {request.get_host()})` before redirecting; fall back to the list URL otherwise. |
| **D-04** | **Medium** | A04 | [services.py:17-26](../apps/portal/services.py#L17-L26) | **Race in `next_requisition_number`** — number = `count()+1` with a uniqueness `while` loop; two concurrent creates read the same `count` before either commits → second `save()` raises `IntegrityError` (`number` is globally `unique=True`) → unhandled 500. | Wrap create in a retry loop catching `IntegrityError`, or compute the number inside a `select_for_update()` transaction over a per-tenant counter, or use a DB sequence. |
| **D-05** | **Medium** | A03 | [reports/detail.html:99-100](../templates/portal/reports/detail.html#L99-L100) | **`{{ result.labels|safe }}` interpolated into a `<script>` block** — raw Python list repr, escaping disabled. For `my_activity` reports the labels are `AuditLog.action` strings (free-text `CharField`); a label containing `</script>` breaks out of the tag → DOM XSS. Not exploitable via portal-written actions today, but a latent injection sink. | Replace with `{{ result|json_script:"report-data" }}` and `JSON.parse(document.getElementById('report-data').textContent)` in JS. Never `|safe` a value into a script context. |
| **D-06** | Low | A04 | [views.py:566-572](../apps/portal/views.py#L566-L572) | **Side-effecting GET** — `ReportRunView.get` writes `last_run_at` on every load (similarly `NotificationDetailView` auto-marks read). Crawlers/prefetch mutate state; not idempotent. | Acceptable as a product choice — document it; for strict REST hygiene move `last_run_at` behind an explicit "Run" POST. |
| **D-07** | Low | A03 | [partials/_pagination.html:6](../templates/partials/_pagination.html#L6) | **GET params not URL-encoded** in pagination links (`&{{ k }}={{ v }}`). A search term containing `&`, `#`, or spaces corrupts next/prev URLs (affects every portal list). | Apply `|urlencode` to `v` (and `k`) in the shared partial. |
| **D-08** | Low | — | [services.py:19](../apps/portal/services.py#L19), [models.py:148](../apps/portal/models.py#L148) | **Cross-tenant numbering coupling** — `number` is globally `unique=True`; slug truncated to 6 chars (`slug[:6].upper().replace('-','')`), so two tenants whose slugs collapse to the same token share one global space. The `while` loop avoids a crash but tenant B's first requisition may become `QR-XXX-00002`. Confusing, not corrupting. | Make `number` unique per tenant: add `unique_together=[('tenant','number')]`, drop global `unique=True`; or embed the tenant pk in the prefix. |
| **D-09** | Info | A05 | [config/settings.py:7-9](../config/settings.py#L7-L9) | Project-level (not portal-specific): `SECRET_KEY` has an insecure default, `ALLOWED_HOSTS` defaults to `*`, and there is no `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` / `SECURE_SSL_REDIRECT` / HSTS. | Ensure `.env` sets `SECRET_KEY` + `ALLOWED_HOSTS` in every non-dev environment; add `SECURE_*` settings gated on `not DEBUG`. Track outside this module. |
| **D-10** | Info | A04 | [views.py:71-88](../apps/portal/views.py#L71-L88) | No cap on widgets per user; amounts have no upper bound beyond `max_digits`. Low abuse potential (per-user data). | Optional: soft-cap widget count. |

### 6.2 Risk register

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| RK-1 | Negative line items poison spend reports & dashboard `spend_total` | Medium | Medium | Fix D-01 — highest-value single fix |
| RK-2 | Requisition create fails under concurrent load | Low–Medium | Medium | Fix D-04 |
| RK-3 | Future caller passes user-influenced text to `AuditLog.action` → D-05 becomes live XSS | Low | High | Fix D-05 proactively |
| RK-4 | `link_url` script scheme abused if notifications become admin-pushable to other users | Low | Medium | Fix D-02 |
| RK-5 | No automated tests — regressions ship silently | High | Medium | Adopt §5 suite; wire into CI |

### 6.3 Strengths (no action needed)

- Tenant **and** user isolation is consistent: every `get_object_or_404` is double-scoped (`tenant=`, `user=`); no `Model.objects.all()`; `TenantManager` adds defence-in-depth.
- CRUD is complete per CLAUDE.md rules; status-gated edit/delete enforced in **both** template and view.
- POST-only mutations with GET fallbacks that redirect safely; CSRF via Django middleware (no `csrf_exempt`).
- Filters are retained across pagination by [_pagination.html](../templates/partials/_pagination.html) (modulo the D-07 encoding bug).
- Seeder is idempotent (`exists()` guard + `--flush`) and prints the tenant-admin login + superuser warning.

---

## 7. Test Coverage Estimation & Success Metrics

### 7.1 Coverage targets

| File | Line target | Branch target | Notes |
|---|---|---|---|
| [models.py](../apps/portal/models.py) | 95% | 90% | `save`/`recalc_total`/`mark_read`/properties |
| [services.py](../apps/portal/services.py) | 90% | 85% | All 5 `generate_report` branches + fallback |
| [views.py](../apps/portal/views.py) | 85% | 80% | All guards + IDOR 404 paths |
| [forms.py](../apps/portal/forms.py) | 100% | — | Post-D-01/D-02 `clean_*` methods |
| **Module** | **≥88%** | **≥82%** | Mutation (optional, `mutmut`): ≥70% killed |

### 7.2 KPI thresholds

| KPI | 🟢 Green | 🟡 Amber | 🔴 Red |
|---|---|---|---|
| Functional pass rate | ≥98% | 90–97% | <90% |
| Open Critical/High defects | 0 | 1 | ≥2 |
| Open Medium defects | ≤2 | 3–5 | >5 |
| Module line coverage | ≥88% | 75–87% | <75% |
| Suite runtime | <25 s | 25–60 s | >60 s |
| Dashboard query count | ≤16 | 17–25 | >25 |
| List p95 latency @1k rows | <300 ms | 300–800 ms | >800 ms |
| Regression escape rate | 0 | 1/release | >1/release |

### 7.3 Current scorecard

| Metric | Value | Status |
|---|---|---|
| Open High | 1 (D-01) | 🔴 |
| Open Medium | 4 (D-02…D-05) | 🟡 |
| Automated tests | 0 | 🔴 |
| Tenant-isolation defects | 0 | 🟢 |
| CRUD completeness | Full | 🟢 |

### 7.4 Release Exit Gate — ALL must be true

- [ ] D-01 fixed: negative `quantity`/`unit_price` rejected; regression test green.
- [ ] D-02 fixed: non-`http(s)` `link_url` schemes rejected.
- [ ] D-03 fixed: `next` redirect host-validated.
- [ ] D-04 fixed: concurrent requisition create cannot 500 on duplicate `number`.
- [ ] D-05 fixed: report chart data rendered via `json_script`, no `|safe`.
- [ ] §5 automation suite present and green; module line coverage ≥88%.
- [ ] Dashboard query count ≤16 verified by `test_performance.py`.
- [ ] `bandit -r apps/portal` reports no Medium+ issues.
- [ ] All P1 test cases in §4 executed and passing.

---

## 8. Summary

Module 2 (User Dashboard & Portal) is **functionally complete and architecturally sound**. All five sub-modules ship with full CRUD, and the standout strength is **isolation discipline** — every view double-scopes by tenant *and* user, every object lookup is a scoped `get_object_or_404`, and the `TenantManager` adds defence-in-depth. CRUD, status-gating, CSRF, and seeder idempotency all follow the CLAUDE.md rules.

The module is **not release-ready** until the input-validation gaps close. The single highest-value fix is **D-01** (High) — negative quantities/prices are accepted today (shell-verified) and silently corrupt every downstream spend figure on the dashboard and in reports. Four Medium defects share a theme of trusting un-sanitised input: a `javascript:` URI sink (**D-02**), an open redirect (**D-03**), a concurrency race on requisition numbering (**D-04**), and an unsafe `|safe` chart-data sink (**D-05**). None breach tenant isolation; all are local, well-bounded, and cheap to fix.

There is **zero automated test coverage** and no test scaffolding — the largest process risk. §5 provides a ready-to-run pytest suite (`config.settings_test`, real `Tenant`/`accounts.User` fixtures) whose `test_security.py` deliberately encodes D-01…D-03 as currently-failing tests, so the suite doubles as the verification gate for the fixes.

**Recommended next step:** `Fix the defects` — implement D-01 through D-05, then `Build the automation` to lock the fixes in. Estimated effort: ~0.5 day for fixes, ~1 day for the initial suite.

---
*Report generated by the `/sqa-review` skill. D-01 and D-02 were verified by Django-shell reproduction against the live codebase; D-03/D-05 are verified by code analysis of well-known unsafe patterns; D-04 is verified by concurrency analysis.*
