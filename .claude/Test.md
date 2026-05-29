# RFx Management (Module 7) — Comprehensive SQA Test Report

> **Target:** `apps.rfx` — RFx Management (RFI / RFP / RFQ): Questionnaire Builder, Response Collection, Side-by-Side Comparison, Scoring & Weighting, Template Library, plus the Vendor Portal response surface.
> **Reviewer persona:** Senior SQA Engineer · **Standards:** OWASP Top 10 (2021), ISO/IEC 29119.
> **Codebase state at review:** branch `main`, 102 existing RFx tests passing (`apps/rfx/tests/`). Test infra already present: [pytest.ini](pytest.ini) → [config/settings_test.py](config/settings_test.py) (SQLite in-memory + MD5), [requirements-dev.txt](requirements-dev.txt) pins `pytest`, `pytest-django`, `pytest-cov`.
> **Verification:** every High/Critical finding below was reproduced against the live codebase with the Django test client (probes since removed). See §6.

---

## 1. Module Analysis

### 1.1 Surface

| Layer | File | LoC | Notes |
|---|---|---|---|
| Models | [apps/rfx/models.py](apps/rfx/models.py) | ~500 | 11 models, all `TenantAwareModel` + `TimeStampedModel` |
| Services | [apps/rfx/services.py](apps/rfx/services.py) | ~738 | Numbering, lifecycle, sealed gate, scoring, ranking, template clone, reorder, analytics |
| Buyer views | [apps/rfx/views.py](apps/rfx/views.py) | ~1112 | Event CRUD, lifecycle, inline section/question CRUD, invitees, documents, responses, evaluation, decisions, templates, analytics |
| Portal views | [apps/rfx/portal_views.py](apps/rfx/portal_views.py) | ~263 | Vendor inbox, event read-only, response start/edit/submit/withdraw/decline |
| Forms | [apps/rfx/forms.py](apps/rfx/forms.py) | ~293 | 10 forms incl. shared `_BaseQuestionForm`, file-size caps |
| Buyer URLs | [apps/rfx/urls.py](apps/rfx/urls.py) | 93 | `app_name = 'rfx'`, 40 routes |
| Portal URLs | [apps/vendors/portal_urls.py](apps/vendors/portal_urls.py) | — | `vendor_portal:rfx_*` |
| Admin | [apps/rfx/admin.py](apps/rfx/admin.py) | 157 | 11 registrations + inlines |
| Template tag | [apps/rfx/templatetags/rfx_tags.py](apps/rfx/templatetags/rfx_tags.py) | 23 | `get_item` dict lookup |
| Seed | [apps/rfx/management/commands/seed_rfx.py](apps/rfx/management/commands/seed_rfx.py) | — | 2 templates + 3 events/tenant |

### 1.2 Data model (11 entities)

| Model | Sub-module | Key invariants |
|---|---|---|
| `RfxEvent` | Builder | `unique_together(tenant, event_number)`; 7-state status machine; `is_editable`, `responses_are_visible`, `can_cancel` properties |
| `RfxSection` | Builder | ordered by `position`; CASCADE from event |
| `RfxQuestion` | Builder | 9 types; `weight` 0–100 validator; `max_score`; `choices` JSON; `is_scored` |
| `RfxInvitee` | Collection | `unique_together(event, vendor)`; status flow invited→viewed→responded/declined/withdrawn |
| `RfxResponse` | Collection | `unique_together(event, vendor)`; `overall_score`, `rank`; `is_editable` only in draft |
| `RfxAnswer` | Collection | `unique_together(response, question)`; typed `value` dispatch; `is_answered` |
| `RfxEvaluation` | Scoring | `unique_together(response, question, evaluator)` (panel); `score ≥ 0` |
| `RfxDocument` | Collection | buyer attachment; `FileField` |
| `RfxTemplate` | Library | `unique_together(tenant, title)`; `is_shared`, `archived` |
| `RfxTemplateSection` | Library | clone source |
| `RfxTemplateQuestion` | Library | clone source |

### 1.3 Business rules (each linked to source)

| # | Rule | Source |
|---|---|---|
| BR-1 | Event numbers are `RFX-<SLUG>-NNNNN`, auto-assigned, unique per tenant | [services.py:76](apps/rfx/services.py#L76) |
| BR-2 | Only `draft` events are editable / deletable (event, sections, questions) | [models.py:140](apps/rfx/models.py#L140), [views.py:220](apps/rfx/views.py#L220) |
| BR-3 | Publish requires ≥1 section, ≥1 question, ≥1 invitee, a `close_at`, and scored weights summing to exactly 100 | [services.py:119](apps/rfx/services.py#L119) |
| BR-4 | **Sealed-response:** buyers see response content only after the event reaches `closed`/`under_evaluation`/`completed`/`cancelled` | [models.py:148](apps/rfx/models.py#L148), [services.py:58](apps/rfx/services.py#L58) |
| BR-5 | A vendor may respond only if invited and the event is `open`; one response per (event, vendor) | [services.py:307](apps/rfx/services.py#L307) |
| BR-6 | Submit blocks if any `is_required` question is unanswered | [services.py:354](apps/rfx/services.py#L354) |
| BR-7 | Closing an open event auto-withdraws still-`draft` responses | [services.py:191](apps/rfx/services.py#L191) |
| BR-8 | Score = Σ(weight × avg_panel_score / max_score) over scored questions | [services.py:450](apps/rfx/services.py#L450) |
| BR-9 | First evaluation transitions `closed→under_evaluation` and `submitted→under_review` | [services.py:440](apps/rfx/services.py#L440) |
| BR-10 | Manage roles = tenant_admin / procurement_manager / buyer; evaluate adds approver | [services.py:34](apps/rfx/services.py#L34) |
| BR-11 | Template clone copies sections + questions into a fresh draft event | [services.py:584](apps/rfx/services.py#L584) |

### 1.4 Cross-cutting dependencies

- **Multi-tenancy:** every model inherits `TenantAwareModel` ([apps/core/models.py:70](apps/core/models.py#L70)). The default `objects` manager auto-scopes to the thread-local tenant set by [TenantMiddleware](apps/core/middleware.py#L9); services deliberately use `all_objects` (unscoped) and re-scope explicitly via `filter(tenant=...)`. Views use `get_object_or_404(Model, pk=pk, tenant=request.tenant)`.
- **Vendor sandbox:** [`@vendor_blocked`](apps/vendors/decorators.py#L37) on every buyer view + [VendorPortalSandboxMiddleware](apps/vendors/middleware.py) keep portal users out of `/rfx/*`; [`@vendor_required`](apps/vendors/decorators.py#L13) gates portal views.
- **Audit:** state transitions call `record_audit(...)` from `apps.tenants.services`.

### 1.5 Pre-test risk profile

| Area | Risk | Rationale |
|---|---|---|
| Sealed-response confidentiality | **High** | Competitor bid data; gate is status-based and applied inconsistently across views |
| Authorization (role vs login) | **High** | List/compare/analytics views check tenant but not manage/evaluate role |
| Scoring/ranking integrity | Medium | Float-free Decimal math; post-completion mutation path |
| File upload | Medium | Size-only validation; SVG/HTML not excluded |
| Numbering races | Medium | `count()+1` sequence without locking |
| Tenant isolation | Low | Consistent `tenant=` scoping + tested |

---

## 2. Test Plan

| Test type | In scope for RFx | Priority |
|---|---|---|
| **Unit** (models, services, forms) | `value` dispatch, `is_answered`, score math, weight validation, numbering, sealed gate, reorder, template clone | High |
| **Integration** (view+form+model+DB) | Event/section/question CRUD, lifecycle endpoints, invitee/document, response sealed list/detail/compare/evaluate, template CRUD, portal flow | High |
| **Functional** (E2E journey) | Buyer builds → publishes → vendor responds → buyer closes → panel scores → ranks → shortlists → completes; template round-trip | High |
| **Regression** | Guard the existing 102 tests + add a gate test for each fixed defect | High |
| **Boundary** | weight {0, 0.01, 100, 100.01}, max_score {0,1}, score {0, max, max+ε}, file {cap, cap+1}, choices {0,1,2}, `event_number` 40-char | Medium |
| **Edge** | empty/whitespace/unicode/emoji prompts & answers, no scored questions, zero invitees, datetime-local parsing, `value_choices` not in declared options | Medium |
| **Negative** | unauthenticated, wrong role, cross-tenant IDOR, cross-vendor response, edit non-draft, double submit, score unscored Q, score out of range | High |
| **Security** | OWASP A01–A10 (see §Security checklist) | High |
| **Performance** | N+1 in `response_compare` / `response_detail`; `recompute_response_scores` fan-out; list at scale | Medium |
| **Reliability** | numbering race, status-transition idempotency under retry | Medium |
| **Usability** | filter retention across pagination, sealed-state messaging | Low |

---

## 3. Test Scenarios

### Events & questionnaire (C = create/CRUD, X = negative/edge)

| # | Scenario | Type |
|---|---|---|
| C-01 | Tenant admin creates draft event → auto number `RFX-<SLUG>-00001` | Functional |
| C-02 | Edit draft event title/dates | Integration |
| C-03 | Add / edit / delete / reorder section (draft only) | Integration |
| C-04 | Add / edit / delete / reorder question (draft only) | Integration |
| C-05 | Delete draft event | Integration |
| X-01 | Edit/delete a non-draft event → bounced with error | Negative |
| X-02 | Add section/question to non-draft event → blocked | Negative |
| X-03 | Requester (no manage role) creates event → blocked, none created | Security/Negative |
| X-04 | Choice question with <2 options → form invalid | Boundary |
| X-05 | Scored question with weight 0 → form invalid | Boundary |
| X-06 | `<script>` in title/prompt → escaped in list/detail | Security |

### Lifecycle (L)

| # | Scenario | Type |
|---|---|---|
| L-01 | Publish with full setup → published or open (publish_at in past) | Functional |
| L-02 | Publish without sections/questions/invitees/close_at/weight=100 → each error surfaced | Negative |
| L-03 | Open → close → drafts auto-withdrawn | Functional |
| L-04 | Cancel with reason (and empty reason → "No reason given") | Integration |
| L-05 | Complete from under_evaluation → ranks finalised | Functional |
| L-06 | Publish a non-draft, close a non-open, complete a non-closed → ValidationError | Negative |
| L-07 | Close_at in the past still allows open | Edge |

### Response collection — vendor portal (R)

| # | Scenario | Type |
|---|---|---|
| R-01 | Invited vendor starts response → 1 blank answer/question | Functional |
| R-02 | Start is idempotent (returns existing) | Integration |
| R-03 | Uninvited / blacklisted vendor cannot start | Negative |
| R-04 | Fill answers per type (text/number/scale/date/choice/file/yes_no) | Integration |
| R-05 | `value_choices` value not in declared options is dropped | Edge/Security |
| R-06 | Submit blocked when required unanswered | Negative |
| R-07 | Withdraw only while open & draft/submitted | Negative |
| R-08 | Decline invitation | Integration |
| R-09 | Answer file > 5 MB rejected | Boundary |

### Sealed responses & comparison (S)

| # | Scenario | Type |
|---|---|---|
| S-01 | Before close: buyer list/detail/compare show **sealed**, no leak | Security |
| S-02 | After close: manage/evaluate role sees list/detail/compare | Functional |
| S-03 | Vendor sees only own response, never others' | Security |
| **S-04** | **Requester (non-manage/non-evaluate) hits list/compare after close → MUST be blocked** | **Security (D-01)** |
| S-05 | Cross-tenant response_detail → 404 | Security |
| S-06 | Side-by-side matrix renders one column per non-withdrawn response | Integration |

### Scoring, ranking, decisions (E)

| # | Scenario | Type |
|---|---|---|
| E-01 | Record evaluation → score = weight×avg/max | Unit |
| E-02 | Panel average across 2 evaluators | Unit |
| E-03 | Rank orders by overall_score desc | Unit |
| E-04 | Score unscored question / out of range / before close → rejected | Negative |
| **E-05** | **Evaluate a `completed`/`cancelled` event → score changes without re-rank** | **Negative (D-03)** |
| E-06 | Shortlist requires under_evaluation; reject requires ≥ closed | Negative |
| E-07 | Shortlisted response cannot be directly rejected | Negative |

### Templates (T) & Analytics (A)

| # | Scenario | Type |
|---|---|---|
| T-01 | Create template; add section/question | Integration |
| T-02 | Use template → spawns draft event with cloned structure | Functional |
| T-03 | Save event as template (snapshot) | Functional |
| T-04 | Duplicate template title (unique_together) → handled, no 500 | Negative |
| A-01 | Event metrics: response rate, top vendor, cycle days | Unit |
| A-02 | Tenant metrics: counts by status/type, response rate | Unit |
| **A-03** | **Requester hits analytics dashboard / event report → exposure check** | **Security (D-02)** |

### Multi-tenancy & numbering (M)

| # | Scenario | Type |
|---|---|---|
| M-01 | Cross-tenant event/section/question detail/edit/delete → 404 | Security |
| M-02 | Numbering uses tenant slug, zero-padded, increments | Unit |
| M-03 | Concurrent create → duplicate number race | Reliability (D-05) |

---

## 4. Detailed Test Cases

> Representative high-value cases. ID format `TC-<ENTITY>-NNN`. The full enumeration maps 1:1 to §3 scenarios; parametrised cases are noted.

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| **TC-SEC-001** | Requester cannot read sealed responses via `response_list` | Event closed, 1 submitted response; user role=`requester` | force_login(requester); GET `rfx:response_list` | event.pk | **403 or redirect to detail with "no permission"; vendor identity NOT in body** | none |
| **TC-SEC-002** | Requester cannot read `response_compare` matrix | as above | GET `rfx:response_compare` | event.pk | **Blocked; no answer/vendor leak** | none |
| **TC-SEC-003** | Requester cannot read analytics dashboard | tenant has events | GET `rfx:analytics_dashboard` | — | **Blocked or stripped of vendor-identifying rows** | none |
| TC-SEC-004 | Cross-tenant event detail IDOR | intruder in other tenant | GET `rfx:event_detail` | other tenant's event.pk | 404 | event intact |
| TC-SEC-005 | Cross-vendor response invisibility | portal user of vendor_b | call `response_visible_to` | submitted_response (vendor_a) | `False` | — |
| TC-SEC-006 | XSS escape in list/detail | — | create event/question with HTML; GET list/detail | `<script>alert(1)</script>` | Raw markup absent; `&lt;script&gt;` present | — |
| TC-SEC-007 | CSRF on POST | logged in | POST delete w/ `enforce_csrf_checks` | event.pk | 403 | not deleted |
| TC-SEC-008 | Malicious file upload rejected by type | manage role | POST document with `.svg`/`.html` | `evil.svg` (`<svg onload=...>`) | **Rejected by extension/content whitelist** | no file stored |
| **TC-EVT-001** | Auto numbering | tenant `acme` | `create_event` ×2 | — | `RFX-ACME-00001`, `…00002` | 2 events |
| TC-EVT-002 | Edit blocked on non-draft | open_event | GET `rfx:event_edit` | open_event.pk | 302 → detail + error | unchanged |
| TC-EVT-003 | Delete only when draft | open_event | POST `rfx:event_delete` | open_event.pk | still exists, status `open` | unchanged |
| TC-QST-001 | Choice question needs ≥2 options | draft | submit RfxQuestionForm | type=single_choice, 1 line | invalid, field error | not saved |
| TC-QST-002 | Scored question needs weight>0 | draft | submit form | is_scored=true, weight=0 | invalid | not saved |
| TC-PUB-001 | Publish gate enumerates all errors | empty draft | `validate_event_can_publish` | — | errors: section, question*, invitee, close, weight | status `draft` |
| TC-RSP-001 | Start creates 1 answer/question | open event, 3 Qs, invited vendor | `start_response` | vendor_a | `answers.count()==3` | draft response |
| TC-RSP-002 | Submit blocked w/ missing required | open, required text Q | `submit_response` | unanswered | ValidationError | status stays draft |
| TC-RSP-003 | Choice answer rejects undeclared option | choice Q with options [A,B] | POST answer | choices=['Z'] | stored `value_choices==[]` | — |
| TC-SCR-001 | Score formula | closed, scale Q max=10 wt=100 | `record_evaluation(score=8)` | — | `overall_score==80.0000` | event→under_evaluation |
| TC-SCR-002 | Panel average | two evaluators | scores 6 & 10 | — | `overall_score==80.0000` | — |
| **TC-SCR-003** | **No eval after complete** | completed event | `record_evaluation` again | score=10 | **ValidationError (must reject)** | score & rank unchanged |
| TC-RNK-001 | Rank by score desc | 2 responses scored 4 & 9 | `rank_responses` | — | higher score → rank 1 | ranks persisted |
| TC-TPL-001 | Use template clones structure | template w/ 1 sec, 2 Qs | POST `rfx:template_use` | title='X' | draft event, sections+questions cloned | new event |
| TC-TPL-002 | Duplicate template title | existing title | `save_event_as_template` w/ same title | dup title | graceful error message, no 500 | no partial template |
| TC-NUM-001 | Numbering race | — | 2 concurrent `create_event` | — | both succeed w/ distinct numbers (no IntegrityError 500) | 2 events |

---

## 5. Automation Strategy

### 5.1 State of the suite

A real suite **already exists** and is green (102 tests). The skill's "no test suite" note is stale.

| File | Coverage today |
|---|---|
| [conftest.py](apps/rfx/tests/conftest.py) | tenants, users (admin/buyer/evaluator/requester/intruder), vendors, portal user, draft/open events, submitted response, template |
| [test_models.py](apps/rfx/tests/test_models.py) | status defaults, uniqueness, `responses_are_visible`, `value` dispatch, `is_answered` |
| [test_services.py](apps/rfx/tests/test_services.py) | permissions, numbering, sealed gate, publish validation, lifecycle, scoring, ranking, reorder, template clone |
| [test_views.py](apps/rfx/tests/test_views.py) | permission gates, CRUD, sealed list/detail, filters, inline CRUD, lifecycle, templates, portal |
| [test_security.py](apps/rfx/tests/test_security.py) | A01 IDOR, A03 XSS, A04 guards, A05 anon redirect, A08 size cap, CSRF, sandbox |

### 5.2 Recommended stack additions

| Tool | Purpose | Status |
|---|---|---|
| pytest / pytest-django / pytest-cov | unit+integration+coverage | ✅ pinned ([requirements-dev.txt](requirements-dev.txt)) |
| `factory_boy` | reduce fixture boilerplate as suite grows | ➕ add |
| `pytest-randomly` | order-independence (catch the thread-local tenant leak) | ➕ add |
| Playwright | buyer↔vendor E2E smoke | ➕ optional |
| Locust | list/compare at scale | ➕ optional |
| `bandit`, `pip-audit` | SAST + dependency CVE scan (A06) | ➕ add to CI |

### 5.3 Gap tests to add (priority order)

The existing suite has **no test asserting that low-privilege roles are denied** on `response_list`, `response_compare`, or analytics — exactly the hole D-01/D-02 fall through. Add these as regression guards (they will **fail today**, documenting the defect, then pass once fixed):

```python
# apps/rfx/tests/test_access_control.py
"""A01 regression guards for sealed-response confidentiality (D-01, D-02)."""
import pytest
from django.urls import reverse

from apps.rfx.services import close_event

pytestmark = pytest.mark.django_db


def test_requester_cannot_list_sealed_responses(
    client, requester, open_event, submitted_response, tenant_admin,
):
    close_event(open_event, tenant_admin)
    client.force_login(requester)
    resp = client.get(reverse('rfx:response_list', args=[open_event.pk]))
    # After fix: blocked (redirect) OR rendered without vendor identity.
    assert resp.status_code in (302, 403)
    assert b'Acme IT Solutions' not in resp.content


def test_requester_cannot_compare_sealed_responses(
    client, requester, open_event, submitted_response, tenant_admin,
):
    close_event(open_event, tenant_admin)
    client.force_login(requester)
    resp = client.get(reverse('rfx:response_compare', args=[open_event.pk]))
    assert resp.status_code in (302, 403)
    assert b'Acme IT Solutions' not in resp.content


def test_requester_cannot_open_analytics(client, requester, draft_event):
    client.force_login(requester)
    resp = client.get(reverse('rfx:analytics_dashboard'))
    assert resp.status_code in (302, 403)


def test_evaluator_can_compare_after_close(
    client, evaluator, open_event, submitted_response, tenant_admin,
):
    close_event(open_event, tenant_admin)
    client.force_login(evaluator)
    resp = client.get(reverse('rfx:response_compare', args=[open_event.pk]))
    assert resp.status_code == 200  # legitimate access still works
```

```python
# apps/rfx/tests/test_evaluation_guards.py
"""A04 — scoring must be frozen once an event is completed/cancelled (D-03)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.rfx.models import RfxQuestion, RfxSection
from apps.rfx.services import (
    close_event, complete_event, create_event, invite_vendors, publish_event,
    record_evaluation, start_response, submit_response,
)

pytestmark = pytest.mark.django_db


def test_cannot_evaluate_completed_event(tenant, tenant_admin, vendor_a):
    event = create_event(tenant=tenant, user=tenant_admin, title='E',
                         rfx_type='rfp', close_at=timezone.now() + timedelta(days=1))
    sec = RfxSection.all_objects.create(tenant=tenant, event=event, title='S', position=1)
    q = RfxQuestion.all_objects.create(
        tenant=tenant, section=sec, position=1, prompt='Q', question_type='scale',
        is_required=True, is_scored=True, weight=Decimal('100'), max_score=10)
    invite_vendors(event, [vendor_a.pk], tenant_admin)
    event.publish_at = timezone.now() - timedelta(minutes=1); event.save()
    publish_event(event, tenant_admin)
    resp = start_response(event, vendor_a, tenant_admin)
    ans = resp.answers.first(); ans.value_number = Decimal('5'); ans.save()
    submit_response(resp, tenant_admin)
    close_event(event, tenant_admin)
    record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=2)
    complete_event(event, tenant_admin)
    # After fix: scoring a completed event must raise.
    with pytest.raises(ValidationError):
        record_evaluation(response=resp, question=q, evaluator=tenant_admin, score=10)
```

```python
# apps/rfx/tests/test_performance.py
"""N+1 guard for the comparison matrix (D-09)."""
import pytest
from django.urls import reverse

from apps.rfx.services import close_event

pytestmark = pytest.mark.django_db


def test_compare_matrix_query_budget(
    django_assert_max_num_queries, client, tenant_admin,
    open_event, submitted_response,
):
    close_event(open_event, tenant_admin)
    client.force_login(tenant_admin)
    # Today this scales O(questions × responses); pin a ceiling so regressions show.
    with django_assert_max_num_queries(40):
        client.get(reverse('rfx:response_compare', args=[open_event.pk]))
```

All snippets reuse the existing [conftest.py](apps/rfx/tests/conftest.py) fixtures verbatim and run under `config.settings_test` — verified compatible against the live module.

### 5.4 Run command (PowerShell)

```
python -m pytest apps/rfx/tests/ -q
python -m pytest apps/rfx/tests/ --cov=apps.rfx --cov-report=term-missing
```

---

## 6. Defects, Risks & Recommendations

Severity scale: Critical / High / Medium / Low / Info. **Verified** = reproduced against the live codebase this session.

| ID | Severity | OWASP | Location | Finding | Recommendation |
|---|---|---|---|---|---|
| **D-01** | **High** | A01 | [views.py:631](apps/rfx/views.py#L631) (`response_list`), [views.py:652](apps/rfx/views.py#L652) (`response_compare`) | **Verified.** Both views gate on `_require_tenant` only — no manage/evaluate role check. A `requester` (or any authenticated tenant user) gets **HTTP 200 and the full sealed bid set** (vendor identities, answers, scores, ranks) once the event closes. Inconsistent with `response_detail`, which *is* gated by `response_visible_to`. Probe: requester saw `Acme IT Solutions` in both list and compare bodies. | Add the same gate `response_detail` uses: `if not (can_manage_rfx(request.user) or can_evaluate(request.user)): messages.error(...); return redirect('rfx:event_detail', pk=event.pk)`. Add the §5.3 regression tests. |
| **D-02** | **Medium** | A01 | [views.py:1078](apps/rfx/views.py#L1078) (`analytics_dashboard`), [views.py:1100](apps/rfx/views.py#L1100) (`analytics_event_report`) | **Verified (200 for requester).** Tenant-wide RFx analytics and per-event reports — including top vendors by shortlist and per-vendor scores — are visible to any authenticated tenant user. | Gate with `can_manage_rfx` (and/or `can_evaluate`) like the other buyer surfaces. |
| **D-03** | **Medium** | A04 | [services.py:424](apps/rfx/services.py#L424) (`record_evaluation`), [views.py:735](apps/rfx/views.py#L735) (`response_evaluate`) | **Verified.** `EVENT_POST_CLOSE_STATUSES` includes `completed` and `cancelled`, so evaluations are accepted *after* completion. Probe: a completed event's `overall_score` changed 20 → 100 on a new evaluation, **without re-ranking** (rank only recomputed inside `complete_event`) and on an event whose ranks are advertised as "final". Scores and ranks silently desync; cancelled events remain scorable. | Restrict scoring to `('closed', 'under_evaluation')`. Either re-run `rank_responses` on any post-evaluation change, or freeze evaluation once `completed`/`cancelled`. |
| **D-04** | **Medium** | A08 / A03 | [forms.py:214](apps/rfx/forms.py#L214) (`RfxDocumentForm.clean_file`), [portal_views.py:138](apps/rfx/portal_views.py#L138) (answer file) | File uploads are validated by **size only**. No extension/content-type whitelist, no magic-byte check, SVG/HTML not excluded. A buyer (brief) or invited vendor (answer) can upload `evil.svg`/`.html`; if `MEDIA` is ever served inline this is stored XSS, and polyglot/oversized-name attacks are unguarded. | Add an extension+content-type whitelist (pdf/doc/xls/png/jpg), reject `.svg`/`.htm*`, validate magic bytes, and sanitise the stored filename. Mirror any existing branding-logo validator in `apps/tenants`. |
| **D-05** | **Medium** | A04 | [services.py:76](apps/rfx/services.py#L76) (`next_rfx_number`) | Numbering is `all_objects.filter(tenant).count() + 1` with a uniqueness while-loop but **no row lock**. Two concurrent `create_event` calls compute the same count → second insert violates `unique_together(tenant, event_number)` → uncaught `IntegrityError` (HTTP 500). Matches the known "auto-generated numbers — check for races" pattern. | Wrap create in `select_for_update` on a per-tenant counter row, or catch `IntegrityError` and retry with `count+1`. Same hardening should cover any other sequence (PR/PO/Invoice). |
| D-06 | Low | A04 | [services.py:492](apps/rfx/services.py#L492) vs [services.py:512](apps/rfx/services.py#L512) | Asymmetric decision guards: `reject_response` is allowed from `closed`, but `shortlist_response` requires `under_evaluation`. A buyer can reject a bid before any scoring yet cannot shortlist until evaluation begins. | Align the two state sets (decide whether decisions are allowed pre-evaluation, and apply consistently). |
| D-07 | Low | A04 | [views.py:594](apps/rfx/views.py#L594) (`document_add`), [views.py:614](apps/rfx/views.py#L614) (`document_delete`) | No status gate — documents can be added/removed on `completed`/`cancelled` events, altering the audit trail of a finalised event. | Restrict mutation to non-final statuses (or to manage role + log the change explicitly). |
| D-08 | Low | A04 | [services.py:292](apps/rfx/services.py#L292) (`decline_invitation`) | No event-status guard; a vendor can "decline" after close/cancel/complete. | Block decline unless the event is `published`/`open`. |
| D-09 | Info (Perf) | — | [views.py:666](apps/rfx/views.py#L666) (`response_compare`), [services.py:471](apps/rfx/services.py#L471) (`recompute_response_scores`) | `response_compare` runs a per-cell `answers.filter().first()` + per-scored-cell `Avg` aggregate → O(questions × responses) queries. `record_evaluation` calls `recompute_response_scores` (all responses) once **per question saved**, so one evaluator submit is O(scored_q × responses) writes. | Prefetch answers/evaluations into dicts keyed by `question_id`; recompute scores once per submit, not per question. Pin a query budget (§5.3 `test_performance.py`). |
| D-10 | Info | A09 | [views.py:631](apps/rfx/views.py#L631), [views.py:652](apps/rfx/views.py#L652) | Disclosure of sealed competitor bids (list/compare/detail reads) is **not** audited, though state mutations are. After D-01/D-02 are fixed, read-access to sealed data is still a sensitive event worth logging. | Emit `record_audit('rfx.responses_viewed', …)` on first reveal per user/event. |
| D-11 | Info | — | [services.py:714](apps/rfx/services.py#L714) (`tenant_rfx_metrics`) | `counts_by_status` uses `.annotate(c=Sum('id') * 0 + 1)` — a fragile substitute for `Count`. | Replace with `.annotate(c=Count('id'))`. |
| D-12 | Info | A04 | [forms.py:61](apps/rfx/forms.py#L61) (`RfxEventForm.clean`) | `clean` only enforces `close_at > publish_at`; a `close_at` in the past is accepted, so an event can open with an already-elapsed deadline (close is manual). | Validate `close_at > now()` on create/publish. |
| D-13 | Info | — | [models.py:101](apps/rfx/models.py#L101) | `currency` is a free 3-char field (default `USD`) with no ISO-4217 validation. | Constrain to a currency choice list. |

### Positives (no action)

- Consistent tenant scoping via `get_object_or_404(Model, pk=pk, tenant=request.tenant)`; cross-tenant IDOR returns 404 (tested A01).
- Sealed gate correctly implemented on `response_detail` / `response_evaluate` and proven on close (tested).
- Output auto-escaping verified for titles & prompts (A03 tested); CSRF enforced on POST (tested).
- Decimal-based scoring (no float drift); panel averaging unit-tested.
- Destructive actions are POST-only; edit/delete double-guarded (property + view).
- HTTPS hardening present in [config/settings.py:128](config/settings.py#L128) (A05), disabled only for the HTTP test client.

---

## 7. Test Coverage Estimation & Success Metrics

### 7.1 Coverage targets

| File | Current (est.) | Target line | Target branch |
|---|---|---|---|
| [services.py](apps/rfx/services.py) | ~85% | 95% | 90% |
| [views.py](apps/rfx/views.py) | ~70% | 90% | 80% |
| [portal_views.py](apps/rfx/portal_views.py) | ~45% | 85% | 75% |
| [forms.py](apps/rfx/forms.py) | ~75% | 95% | 90% |
| [models.py](apps/rfx/models.py) | ~90% | 95% | 90% |

> `portal_views._save_answer_from_post` (per-type answer parsing) is the largest under-tested surface — date/scale/choice/file branches have no direct test. Add a parametrised `test_portal_answers.py`.

### 7.2 KPI gate

| KPI | Green | Amber | Red |
|---|---|---|---|
| Functional pass rate | 100% | 98–99% | <98% |
| Open Critical/High defects | 0 | — | ≥1 |
| Open Medium defects | ≤2 | 3–4 | ≥5 |
| Suite runtime | <15s | 15–40s | >40s |
| `response_compare` query count (1 event) | ≤25 | 26–40 | >40 |
| Regression escape rate | 0 | — | >0 |
| Dependency CVEs (pip-audit) | 0 | low only | any High |

### 7.3 Release Exit Gate — remediation status (updated 2026-05-29)

> Fixes landed this session; full plan & per-file commits in [.claude/tasks/rfx_defects_todo.md](tasks/rfx_defects_todo.md). RFx suite **143 passing** (was 102); full project suite **396 passing**.

- [x] **D-01 fixed** — `_can_view_responses` gate on `response_list` + `response_compare`; guarded by `test_access_control.py`.
- [x] **D-02 fixed** — analytics views gated; `test_requester_cannot_open_analytics_dashboard`/`_event_report` green.
- [x] **D-14 fixed (found by adversarial review)** — `event_detail` template leaked the scored rank/score table + Outcome card to low-privilege users (gated on status, not on the computed `can_view_responses` flag); now gated. Guarded by `test_event_detail_hides_scores_from_requester` (verified fail-when-reverted) + `_shows_scores_to_manager`.
- [x] **D-03 fixed** — evaluation frozen to `EVENT_EVALUABLE_STATUSES`; `test_cannot_evaluate_completed_event`/`_cancelled_event` + view-gate tests green.
- [x] **D-04 fixed** — shared `upload_error` extension whitelist on buyer doc + vendor answer files; svg/html/exe + uppercase-extension reject tested.
- [x] **D-05 mitigated** — `select_for_update(Tenant)` serialization + retry-on-`IntegrityError`; retry-count and outer-atomic savepoint tests green. *Residual:* full race-proofing under MySQL REPEATABLE READ in a nested transaction needs a dedicated per-tenant sequence row (model + migration) — deferred.
- [x] **D-09 fixed** — compare matrix bulk-loaded with `select_related('question')`; N-independence perf guard green (caught a residual N+1 during this work).
- [x] Full RFx suite green (143) with 0 open Critical/High defects.
- [ ] `bandit` + `pip-audit` pinned in `requirements-dev.txt`; **not yet executed** (install `requirements-dev.txt` then `bandit -r apps/` / `pip-audit -r requirements.txt`).
- [~] Coverage: `services.py` ~83%, `models.py` ~91% (defect-relevant paths covered); view CRUD breadth still below the §7.1 target.

---

## 8. Summary

Module 7 (RFx Management) is a large, well-structured slice — 11 models, a clean service layer, a 7-state event machine, panel scoring with Decimal math, a template library, and a sandboxed vendor portal. Tenant isolation, the sealed-response concept, XSS escaping, and CSRF are all sound and already covered by **102 passing tests**.

The headline problem is **inconsistent authorization on the sealed-response surface**. The sealed gate was implemented correctly on `response_detail`/`response_evaluate` but **not** on `response_list`, `response_compare`, or the analytics views — all three authorize on tenant membership alone. I reproduced this: a low-privilege `requester` reads the full competitor bid set and vendor identities once an event closes (**D-01, High**; **D-02, Medium**). A second integrity gap lets evaluations mutate a `completed` event's score without re-ranking (**D-03, Medium**), and file uploads are size-validated only (**D-04, Medium**). Numbering carries the project-wide `count()+1` race (**D-05, Medium**).

None of these require structural rework — D-01/D-02 are a three-line gate copied from `response_detail`; D-03 is a status-set tightening; D-04 mirrors the branding-upload validator pattern. The §5.3 regression tests are written against the live fixtures and **fail today**, so they double as executable defect proof and as the exit-gate guards once fixed.

**Recommendation:** fix D-01–D-03 before this module is considered shippable; D-04/D-05 in the same iteration. The existing suite is a strong base — the gap is specifically the absence of *negative* role-authorization tests on the read surfaces, which is precisely where the High finding hid.

---

### Suggested follow-up

Reply with **"fix the defects"** to implement D-01–D-05 (with per-file PowerShell commit snippets and before/after verification), or **"build the tests"** to land the §5.3 gap tests (red → green) and wire `bandit`/`pip-audit` into the dev tooling.
