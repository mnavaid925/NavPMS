# RFx Management (Module 7) — Defect Fixes + Test Build

Source: [.claude/Test.md](../Test.md) SQA report. Scope: implement High/Medium defects D-01–D-05 (the approved follow-up), plus directly-related quality wins D-09 (compare N+1, has a perf test) and D-11 (Count). Build the §5.3 gap tests and extras. Wire bandit/pip-audit.

## Defects in scope

- [ ] **D-01 (High, A01)** — `response_list` + `response_compare` lack a manage/evaluate role gate → any tenant user reads sealed bids after close. Fix: mirror `response_detail`'s `can_manage_rfx OR can_evaluate` gate.
- [ ] **D-02 (Medium, A01)** — `analytics_dashboard` + `analytics_event_report` ungated. Fix: same role gate.
- [ ] **D-03 (Medium, A04)** — evaluations accepted on `completed`/`cancelled` events → score/rank desync. Fix: introduce `EVENT_EVALUABLE_STATUSES = ('closed','under_evaluation')`; enforce in `record_evaluation` (service) and `response_evaluate` (view).
- [ ] **D-04 (Medium, A08)** — uploads validated by size only. Fix: extension whitelist (`upload_error` helper) on `RfxDocumentForm.clean_file` + vendor answer file branch in `portal_views`.
- [ ] **D-05 (Medium, A04)** — `create_event` has no retry on numbering collision → IntegrityError 500. Fix: per-attempt `transaction.atomic()` + retry on `IntegrityError`.
- [ ] **D-09 (Info/Perf)** — `response_compare` O(Q×R) queries. Fix: bulk-load answers + per-cell avg into dicts.
- [ ] **D-11 (Info)** — `tenant_rfx_metrics` uses `Sum('id')*0+1`. Fix: `Count('id')`.

Out of scope (documented as follow-ups): D-06 (decision-guard asymmetry — needs product call), D-07 (document status gate), D-08 (decline guard), D-10 (read-audit), D-12 (past close_at), D-13 (currency choices).

## Tests to build

- [ ] `apps/rfx/tests/test_access_control.py` — D-01/D-02 negative (requester blocked) + positive (manager/evaluator allowed; matrix renders).
- [ ] `apps/rfx/tests/test_evaluation_guards.py` — D-03 service + view guards (completed & cancelled).
- [ ] `apps/rfx/tests/test_performance.py` — D-09 query budget on compare.
- [ ] `apps/rfx/tests/test_numbering.py` — D-05 retry-on-collision (monkeypatched `next_rfx_number`).
- [ ] `apps/rfx/tests/test_portal_answers.py` — `_save_answer_from_post` per-type parsing + D-04 upload reject.
- [ ] Extend `apps/rfx/tests/test_security.py` A08 — reject `.svg`/`.html`; accept `.pdf`.

## Tooling

- [ ] Add `bandit`, `pip-audit` to [requirements-dev.txt](../../requirements-dev.txt).

## Verification protocol

1. Each defect fix proven by a test that **fails before / passes after** (the §5.3 tests were authored to fail today).
2. Full RFx suite must stay green (≥102 existing + new).
3. Adversarial multi-agent review of the final diff (Workflow) for regressions/completeness.

## Review

**Outcome:** all in-scope defects fixed; suite grew 102 → **143 RFx tests**; full project suite **396 passing**. Zero cross-module regressions.

### Fixes landed
| Defect | Fix | Files |
|---|---|---|
| D-01 (High) | `_can_view_responses` gate on `response_list` + `response_compare` | views.py |
| D-02 (Med) | same gate on `analytics_dashboard` + `analytics_event_report` | views.py |
| **D-14 (High, review-found)** | `event_detail` template rendered the scored rank/score table + Outcome card on the status-only `responses_are_visible`, ignoring the `can_view_responses` flag the view already computed — same sealed data D-01 protects. Gated both on `can_view_responses`. | templates/rfx/events/detail.html |
| D-03 (Med) | `EVENT_EVALUABLE_STATUSES=('closed','under_evaluation')` enforced in `record_evaluation` (service) and `response_evaluate` (view) | models.py, services.py, views.py |
| D-04 (Med) | `upload_error` extension **whitelist** shared by `RfxDocumentForm.clean_file` + vendor answer handler | forms.py, portal_views.py |
| D-05 (Med) | `create_event`: `select_for_update(Tenant)` per-tenant serialization + retry-on-`IntegrityError` (no-op lock on SQLite; honest docstring on residual REPEATABLE-READ nested-atomic risk) | services.py |
| D-09 (Info→real) | compare matrix bulk-loaded; review's hardened perf test exposed a **residual N+1** (missing `select_related('question')`) — fixed | views.py |
| D-11 (Info) | `Count('id')` replaces `Sum('id')*0+1` | services.py |
| cleanup | removed dead imports `rank_responses`/`recompute_response_scores` from views.py | views.py |

### Adversarial review (Workflow, 6 dimensions × verify, 32 agents)
- Caught **D-14** (the event_detail leak) and a **loose perf guard** that passed with the exact N+1 it targeted — both since fixed. The hardened (N-independence) perf test then found a *second* residual N+1 (the `select_related` miss).
- Note: some review agents edited the working tree to run mutation experiments; I re-verified on-disk state (D-03 gate present, D-05 retry present, no stray markers) and ran the suite authoritatively before continuing. One "refuted" verdict was an agent reading a stale snapshot — disregarded.
- Spot-verified the headline guard is real: reverting the `event_detail` gate makes `test_event_detail_hides_scores_from_requester` go red (requester sees `87.50`), restored after.

### Test additions (8 new + strengthened)
event_detail leak guard (×2), manage-role membership via `buyer`/`procurement_manager` (parametrized), cancelled-event view gate, uppercase-extension reject + accept, retry-count guard, outer-atomic savepoint collision; fixed weak assertions (vacuous 302 canary, `value_file is not None`).

### Deferred (documented, not in approved scope)
D-06 (decision-guard asymmetry — needs product call), D-07/D-08 (document/decline status gates), D-10 (read-audit of sealed views), D-12 (past `close_at`), D-13 (currency choices), and the **fully** race-proof per-tenant sequence row (model + migration) for D-05.

### Untouched (not mine)
`config/settings.py` (`apps.auctions` line), `apps/auctions/`, and root `_behave_*`/`_smoke_out`/`_cfg_pytest_ini` scratch files — Module 8 WIP, excluded from commits.
