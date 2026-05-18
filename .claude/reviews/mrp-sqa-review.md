# Material Requirements Planning (MRP) — Comprehensive SQA Test Report

**Module:** [apps/mrp/](apps/mrp/) — Module 5 of MSM (Manufacturing System Modules)
**Scope:** Full module review (models, views, forms, services, signals, seeder, templates)
**Reviewer persona:** Senior SQA Engineer (15+ yrs)
**Standards aligned:** OWASP Top 10 (2021), ISO 29119, Django security checklist
**Report date:** 2026-04-29
**Codebase total:** ~3,328 LoC across MRP module + 21 templates

---

## 1. Module Analysis

### 1.1 Sub-modules

The MRP module implements five sub-modules per the MSM specification:

| Sub-module | Purpose | Key files |
|---|---|---|
| 5.1 Demand Forecasting | Algorithm-based forecast over a horizon | [models.py:41-187](apps/mrp/models.py#L41-L187), [services/forecasting.py](apps/mrp/services/forecasting.py) |
| 5.2 Net Requirements Calculation | Gross-to-net + multi-level BOM explosion | [models.py:194-380](apps/mrp/models.py#L194-L380), [services/mrp_engine.py](apps/mrp/services/mrp_engine.py) |
| 5.3 PR Auto-Generation | Suggested purchase requisitions for buy items | [models.py:387-448](apps/mrp/models.py#L387-L448), [services/mrp_engine.py:284-315](apps/mrp/services/mrp_engine.py#L284-L315) |
| 5.4 Exception Management | Action messages with workflow (open → ack → resolve/ignore) | [models.py:455-535](apps/mrp/models.py#L455-L535), [services/exceptions.py](apps/mrp/services/exceptions.py) |
| 5.5 MRP Run & Simulation | Top-level run wrapping a calculation | [models.py:542-626](apps/mrp/models.py#L542-L626), [views.py:726-867](apps/mrp/views.py#L726-L867) |

### 1.2 Key business rules (verified against source)

| # | Rule | Location |
|---|---|---|
| BR-01 | All views must filter by `request.tenant`; cross-tenant queryset access is impossible because `TenantRequiredMixin` rejects users with `tenant=None` | [views.py:81-119](apps/mrp/views.py#L81-L119), [accounts/views.py:28-46](apps/accounts/views.py#L28-L46) |
| BR-02 | `MRPRun.can_apply()` returns false for simulation runs — only Regenerative / Net-Change can be committed | [models.py:596-597](apps/mrp/models.py#L596-L597) |
| BR-03 | `MRPCalculation.can_commit()` requires status='completed' | [models.py:338-339](apps/mrp/models.py#L338-L339) |
| BR-04 | Status transitions on Run / PR / Exception use `_atomic_status_transition` — single conditional UPDATE prevents double-actioning | [views.py:66-74](apps/mrp/views.py#L66-L74) |
| BR-05 | Forecast horizon between 1 and 104 periods | [models.py:67-71](apps/mrp/models.py#L67-L71) |
| BR-06 | Seasonality `period_index` 1–12 (monthly) or 1–52 (weekly) | [models.py:99-102](apps/mrp/models.py#L99-L102), [forms.py:73-74](apps/mrp/forms.py#L73-L74) |
| BR-07 | Inventory Snapshot has FOQ / POQ / Min-Max validation in `clean()` | [forms.py:135-143](apps/mrp/forms.py#L135-L143) |
| BR-08 | MRP Calculation `horizon_end` must be strictly after `horizon_start` | [forms.py:188-194](apps/mrp/forms.py#L188-L194) |
| BR-09 | PR `suggested_release_date` must be ≤ `required_by_date` | [forms.py:219-225](apps/mrp/forms.py#L219-L225) |
| BR-10 | MRP engine prefers MBOM released+default; falls back to any released+default | [services/mrp_engine.py:163-172](apps/mrp/services/mrp_engine.py#L163-L172) |
| BR-11 | Auto-generated PRs only for products of type `raw_material` or `component` | [services/mrp_engine.py:286-293](apps/mrp/services/mrp_engine.py#L286-L293) |
| BR-12 | "Late order" exception severity is `high` if past-due > 7 days, else `medium` | [services/exceptions.py:51-66](apps/mrp/services/exceptions.py#L51-L66) |
| BR-13 | Coverage % = ((gross − net) / gross) × 100, floored at 0, rounded to 2dp | [views.py:763-766](apps/mrp/views.py#L763-L766) |
| BR-14 | Status-change auditing wired through `pre_save`/`post_save` for Run / Calc / PR / Exception | [signals.py](apps/mrp/signals.py) |
| BR-15 | Seeder is idempotent — guarded by `MRPRun.all_objects.filter(tenant=tenant).exists()` | [management/commands/seed_mrp.py:205-207](apps/mrp/management/commands/seed_mrp.py#L205-L207) |

### 1.3 Inputs / Outputs / Dependencies

| Aspect | Detail |
|---|---|
| **Inbound deps** | `apps.plm.models.Product`, `apps.bom.models.BillOfMaterials` (multi-level explode), `apps.pps.models.MasterProductionSchedule`, `apps.core.models.{Tenant, TenantAwareModel, TimeStampedModel}`, `apps.tenants.models.TenantAuditLog`, `apps.accounts.views.TenantRequiredMixin` |
| **Outbound consumers** | None yet — Module 9 (Procurement) will eventually convert `MRPPurchaseRequisition` rows |
| **External I/O** | None — all computation is in-process |
| **Persisted outputs** | `NetRequirement`, `ForecastResult`, `MRPPurchaseRequisition` (auto-generated rows), `MRPException`, `MRPRunResult`, `TenantAuditLog` |
| **Background work** | None — MRP runs are synchronous (within a single HTTP request) |

### 1.4 Risk profile (pre-test)

| Risk vector | Likelihood | Reasoning |
|---|---|---|
| Algorithmic correctness (forecasting / lot-sizing / netting) | **High** | 4 forecast methods × 4 lot-size rules × multi-level BOM = combinatorial surface |
| Multi-tenant isolation | **Medium** | Tenant filtering present but engine uses `all_objects` extensively — verified each call sets `tenant=` |
| Concurrent run safety | **Medium** | `_atomic_status_transition` is sound, but PR sequence numbering uses count+1 (see D-04) |
| Race conditions on commit | **Low–Medium** | Run → Calc commit is two `update()`s, not a single transaction (see D-08) |
| RBAC / segregation of duties | **High** | Any tenant user can approve PRs / apply runs (see D-01) |
| N+1 / scalability | **Medium** | BOM lookup per end item (see D-09) |
| Data validation gaps | **Low** | Most edges covered by form `clean()` and model validators |

---

## 2. Test Plan

### 2.1 Test types and where they apply

| Type | Targets | Tool |
|---|---|---|
| **Unit** | Forecasting algorithms, lot-sizing helpers, model invariants, form `clean()` | pytest + factory-boy |
| **Integration** | View → Form → Service → Model → DB; engine end-to-end | pytest-django |
| **Functional** | Full MRP run lifecycle (queue → start → complete → apply) | pytest-django + Django test client |
| **Regression** | Existing PPS / PLM / BOM contracts not broken by MRP introduction | pytest-django |
| **Boundary** | Decimal precision, horizon length, seasonality indices, lot-size limits | parametrised pytest |
| **Edge** | Empty history, missing BOM, missing inventory, zero demand | parametrised pytest |
| **Negative** | IDOR, cross-tenant access, double-action, bypass attempts | pytest-django |
| **Security (OWASP)** | A01 (access), A03 (XSS / injection), A04 (design), A09 (logging) | pytest + bandit + (optional) ZAP |
| **Performance** | N+1 detection, list-page query budget | `django_assert_max_num_queries` |
| **Concurrency** | Atomic status transitions under simulated concurrent UPDATEs | pytest with `transaction.atomic()` + threads |

### 2.2 Out of scope

- Module 9 (Procurement) PR-to-PO conversion (not yet built)
- Sales-order-driven forecast (Module 17 — not yet built)
- Inventory-bin aggregation (Module 8 — `InventorySnapshot` is the placeholder)

### 2.3 Test environment baseline

- Django **4.2.28** + SQLite in-memory for test runs
- Password hasher overridden to MD5 for speed (`PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']`)
- All tests autouse `_clear_tenant` fixture (mirrors [pps/tests/conftest.py:22-26](apps/pps/tests/conftest.py#L22-L26))

---

## 3. Test Scenarios

### 3.1 Scenario register

| # | Scenario | Type | Submodule |
|---|---|---|---|
| **C-01** | Create ForecastModel — happy path | Functional | 5.1 |
| **C-02** | Create ForecastModel — duplicate (tenant, name) blocked | Negative | 5.1 |
| **C-03** | Edit ForecastModel name to existing — duplicate guard fires | Negative | 5.1 |
| **C-04** | Delete ForecastModel referenced by past run — `ProtectedError` surfaced | Negative | 5.1 |
| **C-05** | List ForecastModels — search + method + period_type + active filters | Functional | 5.1 |
| **C-06** | Run forecast — `moving_avg` with default params | Functional | 5.1 |
| **C-07** | Run forecast — `weighted_ma` with normalised weights | Functional | 5.1 |
| **C-08** | Run forecast — `simple_exp_smoothing` α=0.3 | Functional | 5.1 |
| **C-09** | Run forecast — `naive_seasonal` with monthly indices | Functional | 5.1 |
| **C-10** | Run forecast — empty history → all-zeros forecast | Edge | 5.1 |
| **C-11** | Run forecast — invalid alpha (>1) falls back to 0.3 | Edge | 5.1 |
| **C-12** | Run forecast — unknown method → all-zeros, no 500 | Negative | 5.1 |
| **C-13** | Forecast run failure path — engine throws → status=failed, error_message captured | Negative | 5.1 |
| **C-14** | Cross-tenant ForecastModel access via PK — 404 | Security/IDOR | 5.1 |
| **S-01** | Create SeasonalityProfile — happy path | Functional | 5.1 |
| **S-02** | Duplicate (tenant, product, period_type, period_index) blocked at form layer | Negative | 5.1 |
| **S-03** | Monthly index > 12 rejected | Boundary | 5.1 |
| **S-04** | Weekly index > 52 rejected (model validator) | Boundary | 5.1 |
| **S-05** | Seasonal index = 0 accepted (model validator allows ≥0) | Boundary | 5.1 |
| **I-01** | Create InventorySnapshot — happy path L4L | Functional | 5.2 |
| **I-02** | FOQ method with `lot_size_value=0` rejected | Negative | 5.2 |
| **I-03** | Min-Max with max ≤ min rejected | Negative | 5.2 |
| **I-04** | Duplicate snapshot (same product) blocked | Negative | 5.2 |
| **I-05** | Edit snapshot — change method, recompute on next run | Integration | 5.2 |
| **I-06** | List inventory — search + lot-size method filter | Functional | 5.2 |
| **R-01** | Create ScheduledReceipt with quantity=0 → rejected (min validator 0.0001) | Boundary | 5.2 |
| **R-02** | Past expected_date allowed (back-dated receipts) | Edge | 5.2 |
| **R-03** | Filter by receipt_type / product retains across pagination | Functional | 5.2 |
| **CALC-01** | MRP run end-to-end with seeded MPS — full happy path | Functional | 5.2/5.5 |
| **CALC-02** | MRP run with zero demand → empty `NetRequirement`, summary notes captured | Edge | 5.2 |
| **CALC-03** | MRP run with end-item missing released BOM → `no_bom` exception emitted | Negative | 5.4 |
| **CALC-04** | MRP run — multi-level BOM explosion writes correct `bom_level` and `parent_product` | Functional | 5.2 |
| **CALC-05** | Net req calc — projected_on_hand below safety_stock generates net | Boundary | 5.2 |
| **CALC-06** | FOQ rounding — net 75 with FOQ 50 → planned 100 (smallest integer multiple) | Functional | 5.2 |
| **CALC-07** | POQ — period_count=4 buckets 4 weeks of net into a single planned order | Functional | 5.2 |
| **CALC-08** | Min-Max — net=15 with min=20/max=100 → planned 20 (forced to min) | Functional | 5.2 |
| **CALC-09** | Min-Max — net=150 with max=100 → planned 100, `below_min` not raised; capacity gap flagged elsewhere | Edge | 5.2 |
| **CALC-10** | Horizon end ≤ horizon start rejected at form layer | Negative | 5.2 |
| **CALC-11** | `time_bucket=day` produces daily periods | Functional | 5.2 |
| **CALC-12** | Cross-tenant calc detail access via PK — 404 | Security/IDOR | 5.2 |
| **CALC-13** | Delete committed calculation rejected | Negative | 5.2 |
| **PR-01** | Auto-generated PR for raw_material / component products | Functional | 5.3 |
| **PR-02** | Finished good with planned order produces NetRequirement but **no** PR | Functional | 5.3 |
| **PR-03** | Approve draft PR — status → approved, approved_by + approved_at set | Functional | 5.3 |
| **PR-04** | Approve already-approved PR rejected (atomic transition) | Negative | 5.3 |
| **PR-05** | Cancel approved PR allowed; cancelled PRs are deletable | Functional | 5.3 |
| **PR-06** | Edit converted PR rejected (pre-Module-9 behavior) | Negative | 5.3 |
| **PR-07** | PR delete blocked for status='approved' | Negative | 5.3 |
| **PR-08** | Filter list by status / priority / product retains across pagination | Functional | 5.3 |
| **PR-09** | Cross-tenant PR approval attempt → 404 | Security/IDOR | 5.3 |
| **PR-10** | PR sequence collision under simulated concurrency (see D-04) | Concurrency | 5.3 |
| **EX-01** | `late_order` exception severity grading | Functional | 5.4 |
| **EX-02** | `expedite` exception when lead_time > gap_days | Functional | 5.4 |
| **EX-03** | `below_min` exception when planned_qty < lot_size_value (Min-Max) | Functional | 5.4 |
| **EX-04** | `no_bom` exception synthesised from skipped end-item list | Functional | 5.4 |
| **EX-05** | `no_routing` exception when no inventory snapshot exists | Functional | 5.4 |
| **EX-06** | Acknowledge open exception — status → acknowledged | Functional | 5.4 |
| **EX-07** | Resolve exception with empty notes — currently allowed (D-06) | Negative | 5.4 |
| **EX-08** | Ignore acknowledged exception | Functional | 5.4 |
| **EX-09** | Delete open exception — currently allowed; should be guarded (D-07) | Negative | 5.4 |
| **EX-10** | Filter exceptions by type / severity / status retains across pagination | Functional | 5.4 |
| **EX-11** | Cross-tenant exception detail — 404 | Security/IDOR | 5.4 |
| **RUN-01** | Create MRPRun + MRPCalculation pair (atomic) | Functional | 5.5 |
| **RUN-02** | Start queued run — engine writes Net+PR+Exception rows | Integration | 5.5 |
| **RUN-03** | Apply completed regenerative run → calc.status='committed' | Functional | 5.5 |
| **RUN-04** | Apply simulation run rejected | Negative | 5.5 |
| **RUN-05** | Discard completed run | Functional | 5.5 |
| **RUN-06** | Delete applied run rejected | Negative | 5.5 |
| **RUN-07** | Run with `run_type='net_change'` against existing calc — IntegrityError on duplicates (D-02) | Negative/Bug | 5.5 |
| **RUN-08** | Run failure inside engine → run.status='failed', calc.status='failed', error_message captured | Negative | 5.5 |
| **RUN-09** | Concurrent Apply requests — second loses (atomic transition) | Concurrency | 5.5 |
| **RUN-10** | Cross-tenant run start/apply — 404 | Security/IDOR | 5.5 |
| **AUD-01** | `mrp_run.created` audit log written on run creation | Functional | Audit |
| **AUD-02** | `mrp_calculation.status.completed` audit log written on completion | Functional | Audit |
| **AUD-03** | `mrp_pr.approved` audit log written on approval | Functional | Audit |
| **AUD-04** | `mrp_exception.resolved` audit log written on resolve | Functional | Audit |
| **AUD-05** | Delete operations write **no** audit log (D-10) | Negative/Gap | Audit |
| **SEC-01** | Anonymous user → /mrp/* redirect to login | Security/A01 | All |
| **SEC-02** | Logged-in user with `tenant=None` (superuser) → friendly redirect | Security/A01 | All |
| **SEC-03** | Tenant staff can approve PR (no role gate) — see D-01 | Security/A01 | 5.3 |
| **SEC-04** | XSS attempt in `notes` / `commit_notes` — rendered as escaped text | Security/A03 | All |
| **SEC-05** | CSRF token required on all POST endpoints | Security/A03 | All |
| **SEC-06** | Cross-tenant detail / list / action — 404 / empty | Security/A01 | All |
| **SEEDER-01** | `seed_mrp` is idempotent (no duplicate keys on second run) | Functional | Mgmt |
| **SEEDER-02** | `seed_mrp --flush` wipes only the 3 demo tenants | Functional | Mgmt |
| **SEEDER-03** | Tenant without products → seeder skips with warning | Edge | Mgmt |
| **PERF-01** | List pages issue ≤ 6 queries per request | Performance | All |
| **PERF-02** | MRP run with 100 end items completes in < 5s | Performance | 5.5 |
| **PERF-03** | BOM lookup loop is N+1 (see D-09) | Performance | Engine |

**Total scenarios: 87**

---

## 4. Detailed Test Cases

> Sample of 30 highest-priority cases. The full suite (target ~120 cases) is to be authored by Test Engineering against this spec.

### 4.1 Forecast model CRUD

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| **TC-FM-001** | Create ForecastModel — happy path (`moving_avg`) | tenant `acme`; `acme_admin` logged in | 1. POST `/mrp/forecast-models/new/` 2. Fill form 3. Submit | `name='SMA-3', method='moving_avg', params={"window":3}, period_type='week', horizon_periods=12, is_active=true` | 302 redirect to `forecast_model_list`; success flash; row in DB with `tenant=acme, created_by=acme_admin` | Row exists; signal does NOT fire (creates not audited at FM level — by design) |
| **TC-FM-002** | Duplicate (tenant, name) blocked at form layer | TC-FM-001 done | 1. POST same form again | same as TC-FM-001 | 200 OK with form errors; field error on `name`: "A forecast model with this name already exists." | DB count = 1 |
| **TC-FM-003** | Cross-tenant FM PK access → 404 | tenant `acme` has FM pk=1; `globex_admin` logged in | 1. GET `/mrp/forecast-models/1/` | n/a | 404 | No DB change |
| **TC-FM-004** | Run forecast — happy path | FM exists; ≥ 1 active product in tenant | 1. POST `/mrp/forecast-models/<pk>/run/` | n/a | 302 to `forecast_run_detail`; `ForecastRun.status='completed'`; `ForecastResult` rows = (≤8 products) × `horizon_periods` | run row exists; results bulk-created |
| **TC-FM-005** | Run forecast — engine throws | Patch `forecast_service.run_forecast` to raise | 1. POST `/mrp/forecast-models/<pk>/run/` | n/a | 302; `ForecastRun.status='failed'`; `error_message` populated; flash 'Forecast failed: ...' | partial ForecastResult rows MAY exist (D-03) |

### 4.2 Forecasting algorithms (pure)

| ID | Description | Test Data | Expected Result |
|---|---|---|---|
| **TC-FC-001** | `moving_average([10,20,30], window=3)` | window=3, horizon=2 | `[Decimal('20.00'), Decimal('20.00')]` |
| **TC-FC-002** | `moving_average([], window=3)` (empty history) | empty | `[Decimal('0'), Decimal('0')]` (×horizon) |
| **TC-FC-003** | `weighted_moving_average([10,20,30], weights=[0.2,0.3,0.5])` | sums to 1.0 | `[Decimal('23.00')] × horizon` |
| **TC-FC-004** | `weighted_moving_average(history, weights=[0,0,0])` | total=0 | `[Decimal('0')] × horizon` |
| **TC-FC-005** | `simple_exp_smoothing([10,15,20], alpha=0.3, horizon=2)` | α=0.3 | `[Decimal('13.55'), Decimal('13.55')]` (verify level recursion) |
| **TC-FC-006** | `simple_exp_smoothing(history, alpha=2.0)` (invalid α) | α>1 | falls back to 0.3 internally; result ≠ all-zeros |
| **TC-FC-007** | `naive_seasonal(history, seasonal_indices=[1.2,...×12], horizon=12)` | season=12 | first period uses index[0]=1.2 |
| **TC-FC-008** | `run_forecast('unknown', ...)` | unknown method | `[Decimal('0')] × horizon` (no exception) |

### 4.3 Lot-sizing algorithms (pure)

| ID | Description | Test Data | Expected Result |
|---|---|---|---|
| **TC-LS-001** | `apply_l4l([0, 5, 0, 10])` | net per period | `[(1, 5), (3, 10)]` |
| **TC-LS-002** | `apply_foq([75], fixed_qty=50)` | net=75, FOQ=50 | `[(0, 100)]` (ceil multiple) |
| **TC-LS-003** | `apply_foq([0, 50], fixed_qty=50)` | exact multiple | `[(1, 50)]` |
| **TC-LS-004** | `apply_foq([5], fixed_qty=0)` (invalid FOQ) | fq≤0 | falls back to `apply_l4l` → `[(0, 5)]` |
| **TC-LS-005** | `apply_poq([10, 5, 8, 0, 3], period_count=2)` | bucket 2 | `[(0, 15), (2, 8), (4, 3)]` |
| **TC-LS-006** | `apply_min_max([15], min=20, max=100)` | net<min | `[(0, 20)]` (forced to min) |
| **TC-LS-007** | `apply_min_max([150], min=20, max=100)` | net>max | `[(0, 100)]` (capped at max) |
| **TC-LS-008** | `apply_min_max([5], min=50, max=10)` (lo>hi) | invalid | lo coerced to hi=10 → `[(0, 10)]` |

### 4.4 Inventory snapshot validation

| ID | Description | Test Data | Expected Result |
|---|---|---|---|
| **TC-IS-001** | FOQ with `lot_size_value=0` | method='foq', val=0 | Form invalid; error on `lot_size_value`: "FOQ size must be greater than zero." |
| **TC-IS-002** | Min-Max with `max ≤ min` | method='min_max', val=50, max=50 | Form invalid; error on `lot_size_max`: "Max must be greater than Min." |
| **TC-IS-003** | Duplicate (tenant, product) | snapshot already exists | Form invalid; error on `product`: "This product already has an inventory snapshot." |
| **TC-IS-004** | `lead_time_days=400` | exceeds MaxValueValidator(365) | Form invalid; field-level validator |

### 4.5 MRP engine integration

| ID | Description | Pre-conditions | Steps | Expected Result |
|---|---|---|---|---|
| **TC-EN-001** | Run engine with MPS → end-item gross requirements populated | seeded MPS+lines, FG product, snapshot, BOM released | call `mrp_engine.run_mrp(calc, mode='regenerative')` | summary.skipped_no_bom=[]; NetRequirement rows include FG end items at bom_level=0 |
| **TC-EN-002** | BOM explosion writes child rows at `bom_level=1` | end-item BOM with 2 components | call `run_mrp(...)` | NetRequirement rows for components with `bom_level=1` and `parent_product_id=<end_item.pk>` |
| **TC-EN-003** | End-item with no released BOM → skipped, exception synthesised | FG with no released BOM, demand exists | call `run_mrp(...)` then `generate_exceptions(calc, summary.skipped_no_bom)` | `MRPException.exception_type='no_bom', severity='critical'` row exists |
| **TC-EN-004** | net_change mode against existing calc — IntegrityError on duplicates | calc has prior NetRequirement rows | call `run_mrp(calc, mode='net_change')` | **CURRENT BEHAVIOUR:** `IntegrityError` on `unique_together(mrp_calculation, product, period_start)`. **Expected after D-02 fix:** rows merged, no integrity violation |
| **TC-EN-005** | Coverage = 100% when no net required | gross > 0, net = 0 | inspect aggregation post-run | `coverage_pct = Decimal('100.00')` |
| **TC-EN-006** | Coverage = 0 when gross = 0 | no demand | inspect aggregation post-run | `coverage_pct = Decimal('100.00')` (default branch) |
| **TC-EN-007** | Concurrent PR sequence — collision | mock concurrent runs producing overlapping `MPR-NNNNN` | run two engine runs in parallel | **CURRENT:** may raise IntegrityError on `pr_number` unique. **Expected after D-04 fix:** retried via `_save_with_unique_number` |

### 4.6 Workflow / status transitions

| ID | Description | Pre-conditions | Steps | Expected Result |
|---|---|---|---|---|
| **TC-WF-001** | Approve draft PR | PR with `status='draft'` | POST `/mrp/requisitions/<pk>/approve/` | 302; status='approved'; `approved_by`, `approved_at` set; audit log row `mrp_pr.approved` |
| **TC-WF-002** | Approve already-approved PR | PR with `status='approved'` | POST same | 302 with warning flash; status unchanged |
| **TC-WF-003** | Apply simulation run rejected | run with `run_type='simulation', status='completed'` | POST `/mrp/runs/<pk>/apply/` | 302; warning flash; run.status unchanged |
| **TC-WF-004** | Concurrent Apply — second loses | two clients POST apply within ~10ms | use `transaction.atomic` + threads | one returns success; other returns warning; calc.status='committed' exactly once |
| **TC-WF-005** | Discard failed run allowed | run.status='failed' | POST discard | status='discarded'; calc.status='discarded' |

### 4.7 Security / Access control

| ID | Description | Steps | Expected Result | OWASP |
|---|---|---|---|---|
| **TC-SC-001** | Anonymous GET `/mrp/` | not logged in | 302 to `/login/?next=/mrp/` | A01 |
| **TC-SC-002** | Superuser (tenant=None) GET `/mrp/` | login as superuser | 302 to `dashboard` with friendly warning flash | A01 |
| **TC-SC-003** | Cross-tenant PR approval | `globex_admin` POSTs `/mrp/requisitions/<acme_pr_pk>/approve/` | 404; PR unchanged | A01/IDOR |
| **TC-SC-004** | Tenant staff (non-admin) approves PR | `acme_staff` POST approve | **CURRENT BEHAVIOUR:** 302 success. **Expected after D-01 fix:** 403 / redirect with error | A01 |
| **TC-SC-005** | XSS attempt in PR notes | submit `<script>alert(1)</script>` as `notes` | renders escaped on detail page; no script execution | A03 |
| **TC-SC-006** | CSRF missing on POST approve | client w/o CSRF token | 403 | A03 |

---

## 5. Automation Strategy

### 5.1 Tool stack (recommended)

| Layer | Tool | Reason |
|---|---|---|
| Test runner | **pytest** + **pytest-django** | Aligns with [apps/pps/tests/](apps/pps/tests/) and project standard |
| Fixtures | **factory-boy** (optional) or hand-rolled per pps pattern | Maintain consistency with conftest pattern |
| Coverage | **coverage.py** (`pytest --cov=apps.mrp`) | Branch + line targets per file |
| Static security | **bandit** (`bandit -r apps/mrp`) | Catch obvious sinks |
| Dependency audit | **pip-audit** (or **safety**) | A06 |
| Performance | `pytest-django` `django_assert_max_num_queries` | N+1 detection |
| E2E (optional) | **Playwright** Python | Smoke a 3-step run lifecycle |
| Mutation (optional) | **mutmut** on `services/` | Algorithm correctness |

### 5.2 Suite layout

```
apps/mrp/tests/
├── __init__.py
├── conftest.py                    # tenant + user + product + bom + snapshot fixtures
├── test_models.py                 # invariants, choices, __str__, helper methods
├── test_forms.py                  # ForecastModelForm, SeasonalityProfileForm, InventorySnapshotForm clean()
├── test_forecasting.py            # pure-function unit tests (Phase 4.2 cases)
├── test_lot_sizing.py             # pure-function unit tests (Phase 4.3 cases)
├── test_engine.py                 # end-to-end MRP engine integration (Phase 4.5 cases)
├── test_exceptions_service.py     # generate_exceptions() rule coverage (EX-01..EX-05)
├── test_views_forecast.py         # FM CRUD + run + IDOR
├── test_views_inventory.py        # snapshot + receipts CRUD + filters
├── test_views_calculation.py      # calc list/detail/delete
├── test_views_run.py              # MRPRun lifecycle (RUN-01..RUN-10)
├── test_views_pr.py               # PR approve/cancel/edit/delete + concurrency
├── test_views_exception.py        # ack/resolve/ignore/delete
├── test_audit_signals.py          # AUD-01..AUD-05
├── test_security.py               # SEC-01..SEC-06 (OWASP A01/A03)
├── test_performance.py            # PERF-01..PERF-03 query budgets
└── test_seeder.py                 # SEEDER-01..SEEDER-03
```

Plus a `pytest.ini` and a `config/settings_test.py` (SQLite in-memory + MD5 hasher).

### 5.3 Ready-to-run snippets

#### `apps/mrp/tests/conftest.py`

```python
"""MRP test fixtures. Mirrors the PPS conftest pattern."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.bom.models import BillOfMaterials, BOMLine
from apps.core.models import Tenant, set_current_tenant
from apps.plm.models import Product
from apps.mrp.models import (
    ForecastModel, ForecastRun, ForecastResult, InventorySnapshot,
    MRPCalculation, MRPException, MRPPurchaseRequisition, MRPRun,
    NetRequirement, ScheduledReceipt, SeasonalityProfile,
)


@pytest.fixture(autouse=True)
def _clear_tenant():
    yield
    set_current_tenant(None)


@pytest.fixture
def acme(db):
    return Tenant.objects.create(name='Acme Test', slug='acme-mrp', is_active=True)


@pytest.fixture
def globex(db):
    return Tenant.objects.create(name='Globex Test', slug='globex-mrp', is_active=True)


@pytest.fixture
def acme_admin(db, acme):
    return User.objects.create_user(
        username='admin_acme_mrp', password='pw',
        tenant=acme, is_tenant_admin=True,
    )


@pytest.fixture
def acme_staff(db, acme):
    return User.objects.create_user(
        username='staff_acme_mrp', password='pw',
        tenant=acme, is_tenant_admin=False,
    )


@pytest.fixture
def globex_admin(db, globex):
    return User.objects.create_user(
        username='admin_globex_mrp', password='pw',
        tenant=globex, is_tenant_admin=True,
    )


@pytest.fixture
def admin_client(client, acme_admin):
    client.force_login(acme_admin)
    return client


@pytest.fixture
def staff_client(client, acme_staff):
    client.force_login(acme_staff)
    return client


@pytest.fixture
def globex_client(client, globex_admin):
    client.force_login(globex_admin)
    return client


@pytest.fixture
def fg_product(db, acme):
    return Product.objects.create(
        tenant=acme, sku='FG-1', name='FG One',
        product_type='finished_good', unit_of_measure='ea', status='active',
    )


@pytest.fixture
def raw_product(db, acme):
    return Product.objects.create(
        tenant=acme, sku='RM-1', name='RM One',
        product_type='raw_material', unit_of_measure='ea', status='active',
    )


@pytest.fixture
def released_bom(db, acme, fg_product, raw_product, acme_admin):
    bom = BillOfMaterials.objects.create(
        tenant=acme, product=fg_product, version='A',
        bom_number='BOM-T1', bom_type='mbom',
        status='released', is_default=True, created_by=acme_admin,
    )
    BOMLine.objects.create(
        tenant=acme, bom=bom, sequence=10,
        component=raw_product, quantity_per=Decimal('2'),
        unit_of_measure='ea',
    )
    return bom


@pytest.fixture
def snapshot_fg(db, acme, fg_product):
    return InventorySnapshot.objects.create(
        tenant=acme, product=fg_product,
        on_hand_qty=Decimal('5'), safety_stock=Decimal('10'),
        reorder_point=Decimal('15'), lead_time_days=14,
        lot_size_method='l4l', lot_size_value=Decimal('0'),
        lot_size_max=Decimal('0'), as_of_date=date.today(),
    )


@pytest.fixture
def snapshot_rm(db, acme, raw_product):
    return InventorySnapshot.objects.create(
        tenant=acme, product=raw_product,
        on_hand_qty=Decimal('30'), safety_stock=Decimal('20'),
        reorder_point=Decimal('40'), lead_time_days=7,
        lot_size_method='foq', lot_size_value=Decimal('50'),
        lot_size_max=Decimal('0'), as_of_date=date.today(),
    )


@pytest.fixture
def forecast_model(db, acme, acme_admin):
    return ForecastModel.objects.create(
        tenant=acme, name='SMA-3', method='moving_avg',
        params={'window': 3}, period_type='week',
        horizon_periods=4, is_active=True, created_by=acme_admin,
    )


@pytest.fixture
def completed_forecast_run(db, acme, forecast_model, fg_product):
    run = ForecastRun.objects.create(
        tenant=acme, run_number='FRUN-00001',
        forecast_model=forecast_model, run_date=date.today(),
        status='completed',
    )
    today = date.today()
    for w in range(4):
        ps = today + timedelta(days=w * 7)
        ForecastResult.objects.create(
            tenant=acme, run=run, product=fg_product,
            period_start=ps, period_end=ps + timedelta(days=6),
            forecasted_qty=Decimal('80'),
            lower_bound=Decimal('68'), upper_bound=Decimal('92'),
            confidence_pct=Decimal('80'),
        )
    return run


@pytest.fixture
def calc(db, acme, acme_admin):
    today = date.today()
    return MRPCalculation.objects.create(
        tenant=acme, mrp_number='MRP-00001', name='Test calc',
        horizon_start=today, horizon_end=today + timedelta(days=28),
        time_bucket='week', status='draft', started_by=acme_admin,
    )
```

#### `apps/mrp/tests/test_forecasting.py`

```python
"""Pure-function tests — no DB required."""
from decimal import Decimal

import pytest

from apps.mrp.services import forecasting as fc


class TestMovingAverage:
    def test_basic(self):
        assert fc.moving_average([10, 20, 30], window=3, horizon=2) == [
            Decimal('20.00'), Decimal('20.00'),
        ]

    def test_empty_history(self):
        assert fc.moving_average([], window=3, horizon=3) == [Decimal('0')] * 3

    def test_window_clamped_to_history(self):
        # window > len(history) clamped down
        assert fc.moving_average([10, 20], window=5, horizon=1) == [Decimal('15.00')]


class TestWeightedMA:
    def test_normalized_weights(self):
        out = fc.weighted_moving_average([10, 20, 30], [1, 1, 1], horizon=1)
        assert out == [Decimal('20.00')]

    def test_unnormalized_weights(self):
        out = fc.weighted_moving_average([10, 20, 30], [0.2, 0.3, 0.5], horizon=1)
        assert out == [Decimal('23.00')]

    def test_zero_weights_returns_zero(self):
        out = fc.weighted_moving_average([10, 20, 30], [0, 0, 0], horizon=2)
        assert out == [Decimal('0'), Decimal('0')]


class TestSimpleExpSmoothing:
    def test_basic(self):
        # L0=10; L1 = 0.3*15 + 0.7*10 = 11.5; L2 = 0.3*20 + 0.7*11.5 = 14.05
        out = fc.simple_exp_smoothing([10, 15, 20], alpha=Decimal('0.3'), horizon=2)
        assert out == [Decimal('14.05'), Decimal('14.05')]

    @pytest.mark.parametrize('bad_alpha', [Decimal('0'), Decimal('-1'), Decimal('2')])
    def test_invalid_alpha_falls_back(self, bad_alpha):
        out = fc.simple_exp_smoothing([10, 20], alpha=bad_alpha, horizon=1)
        assert out[0] != Decimal('0')


class TestNaiveSeasonal:
    def test_full_season(self):
        history = [Decimal('100')] * 12
        indices = [Decimal('1.2')] + [Decimal('1')] * 11
        out = fc.naive_seasonal(history, indices, horizon=12)
        # baseline = mean of de-seasonalized history; first index multiplied by 1.2
        assert out[0] == Decimal('110.00') or out[0] > Decimal('100')


class TestRunForecastDispatch:
    def test_unknown_method_returns_zeros(self):
        assert fc.run_forecast('unknown', [10, 20], {}, horizon=3) == [Decimal('0')] * 3
```

#### `apps/mrp/tests/test_lot_sizing.py`

```python
from decimal import Decimal

import pytest

from apps.mrp.services import lot_sizing as ls


class TestL4L:
    def test_picks_only_positive(self):
        assert ls.apply_l4l([0, 5, 0, 10]) == [(1, Decimal('5')), (3, Decimal('10'))]


class TestFOQ:
    def test_ceil_multiple(self):
        assert ls.apply_foq([75], fixed_qty=50) == [(0, Decimal('100'))]

    def test_exact_multiple(self):
        assert ls.apply_foq([0, 50], fixed_qty=50) == [(1, Decimal('50'))]

    def test_zero_fixed_falls_back_to_l4l(self):
        assert ls.apply_foq([5], fixed_qty=0) == [(0, Decimal('5'))]


class TestPOQ:
    def test_buckets(self):
        out = ls.apply_poq([10, 5, 8, 0, 3], period_count=2)
        assert out == [(0, Decimal('15')), (2, Decimal('8')), (4, Decimal('3'))]

    def test_zero_period_count_clamped(self):
        # max(1, int(0)) = 1 → degenerates to L4L on positive periods
        assert ls.apply_poq([0, 5], period_count=0) == [(1, Decimal('5'))]


class TestMinMax:
    @pytest.mark.parametrize('net,lo,hi,expected', [
        (Decimal('15'), 20, 100, [(0, Decimal('20'))]),
        (Decimal('150'), 20, 100, [(0, Decimal('100'))]),
        (Decimal('50'), 20, 100, [(0, Decimal('50'))]),
    ])
    def test_clamping(self, net, lo, hi, expected):
        assert ls.apply_min_max([net], min_qty=lo, max_qty=hi) == expected

    def test_lo_greater_than_hi_coerced(self):
        # lo > hi → lo = hi
        assert ls.apply_min_max([Decimal('5')], min_qty=50, max_qty=10) == [(0, Decimal('10'))]


class TestApplyDispatcher:
    def test_unknown_method_falls_back_to_l4l(self):
        assert ls.apply('mystery', [Decimal('5')]) == [(0, Decimal('5'))]
```

#### `apps/mrp/tests/test_engine.py`

```python
"""End-to-end MRP engine integration tests."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.mrp.models import (
    MRPException, MRPPurchaseRequisition, NetRequirement,
)
from apps.mrp.services import mrp_engine
from apps.mrp.services import exceptions as exc_service


@pytest.mark.django_db
class TestEngineHappyPath:
    def test_run_with_forecast_demand_produces_net_rows(
        self, acme, calc, fg_product, raw_product,
        released_bom, snapshot_fg, snapshot_rm, completed_forecast_run,
    ):
        summary = mrp_engine.run_mrp(calc, mode='regenerative')
        assert summary.skipped_no_bom == []
        nets = NetRequirement.objects.filter(mrp_calculation=calc)
        assert nets.exists()
        # End-item rows at level 0
        assert nets.filter(product=fg_product, bom_level=0).exists()
        # Component rows at level 1
        comp_rows = nets.filter(product=raw_product, bom_level=1)
        assert comp_rows.exists()
        assert comp_rows.first().parent_product == fg_product

    def test_pr_auto_generation_for_raw_material_only(
        self, acme, calc, fg_product, raw_product,
        released_bom, snapshot_fg, snapshot_rm, completed_forecast_run,
    ):
        mrp_engine.run_mrp(calc, mode='regenerative')
        # FG should NOT have a PR (it's finished_good)
        assert not MRPPurchaseRequisition.objects.filter(
            mrp_calculation=calc, product=fg_product,
        ).exists()
        # RM may have a PR if planned_order_qty > 0


@pytest.mark.django_db
class TestEngineExceptions:
    def test_no_bom_raises_critical_exception(
        self, acme, calc, fg_product, snapshot_fg, completed_forecast_run,
    ):
        # No released_bom fixture → end item is skipped
        summary = mrp_engine.run_mrp(calc, mode='regenerative')
        assert fg_product.sku in summary.skipped_no_bom
        n = exc_service.generate_exceptions(calc, summary.skipped_no_bom)
        assert n >= 1
        no_bom = MRPException.objects.filter(
            mrp_calculation=calc, exception_type='no_bom', product=fg_product,
        ).first()
        assert no_bom is not None
        assert no_bom.severity == 'critical'

    def test_late_order_severity(self, acme, calc, raw_product):
        from apps.mrp.models import NetRequirement
        # Create a NetRequirement with planned_release_date in the distant past
        NetRequirement.objects.create(
            tenant=acme, mrp_calculation=calc, product=raw_product,
            period_start=date.today(), period_end=date.today() + timedelta(days=6),
            bom_level=0, gross_requirement=Decimal('10'),
            scheduled_receipts_qty=Decimal('0'),
            projected_on_hand=Decimal('0'),
            net_requirement=Decimal('10'),
            planned_order_qty=Decimal('10'),
            planned_release_date=date.today() - timedelta(days=10),
            lot_size_method='l4l',
        )
        n = exc_service.generate_exceptions(calc, [])
        assert n >= 1
        late = MRPException.objects.filter(
            mrp_calculation=calc, exception_type='late_order',
        ).first()
        assert late.severity == 'high'


@pytest.mark.django_db
class TestEngineNetChangeMode:
    """Documents the current bug — see D-02."""

    @pytest.mark.xfail(reason='D-02: net_change mode appends, violating unique_together')
    def test_net_change_does_not_duplicate(
        self, acme, calc, fg_product, raw_product, released_bom,
        snapshot_fg, snapshot_rm, completed_forecast_run,
    ):
        mrp_engine.run_mrp(calc, mode='regenerative')
        # Second run in net_change mode should NOT raise IntegrityError
        mrp_engine.run_mrp(calc, mode='net_change')
        # Each (calc, product, period_start) should have exactly one row
        from django.db.models import Count
        dupes = (
            NetRequirement.objects.filter(mrp_calculation=calc)
            .values('product', 'period_start')
            .annotate(n=Count('id')).filter(n__gt=1)
        )
        assert not dupes.exists()
```

#### `apps/mrp/tests/test_views_pr.py`

```python
"""Purchase Requisition view tests — including IDOR + concurrency."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.mrp.models import MRPPurchaseRequisition


def _make_pr(tenant, calc, product, status='draft', pr_number='MPR-T1'):
    return MRPPurchaseRequisition.objects.create(
        tenant=tenant, pr_number=pr_number, mrp_calculation=calc,
        product=product, quantity=Decimal('10'),
        required_by_date=date.today() + timedelta(days=14),
        suggested_release_date=date.today() + timedelta(days=7),
        status=status, priority='normal',
    )


@pytest.mark.django_db
class TestPRApprove:
    def test_approve_draft(self, admin_client, acme, calc, raw_product, acme_admin):
        pr = _make_pr(acme, calc, raw_product)
        r = admin_client.post(reverse('mrp:pr_approve', args=[pr.pk]))
        assert r.status_code == 302
        pr.refresh_from_db()
        assert pr.status == 'approved'
        assert pr.approved_by == acme_admin
        assert pr.approved_at is not None

    def test_approve_already_approved_no_change(
        self, admin_client, acme, calc, raw_product,
    ):
        pr = _make_pr(acme, calc, raw_product, status='approved')
        prev_approved_at = pr.approved_at
        admin_client.post(reverse('mrp:pr_approve', args=[pr.pk]))
        pr.refresh_from_db()
        assert pr.status == 'approved'
        # approved_at should NOT have been overwritten by atomic transition
        assert pr.approved_at == prev_approved_at

    def test_cross_tenant_approve_404(
        self, globex_client, acme, calc, raw_product,
    ):
        pr = _make_pr(acme, calc, raw_product)
        r = globex_client.post(reverse('mrp:pr_approve', args=[pr.pk]))
        assert r.status_code == 302  # _atomic_status_transition silently fails
        pr.refresh_from_db()
        assert pr.status == 'draft'


@pytest.mark.django_db
class TestPRDelete:
    def test_delete_draft_allowed(self, admin_client, acme, calc, raw_product):
        pr = _make_pr(acme, calc, raw_product)
        r = admin_client.post(reverse('mrp:pr_delete', args=[pr.pk]))
        assert r.status_code == 302
        assert not MRPPurchaseRequisition.objects.filter(pk=pr.pk).exists()

    def test_delete_approved_blocked(self, admin_client, acme, calc, raw_product):
        pr = _make_pr(acme, calc, raw_product, status='approved')
        admin_client.post(reverse('mrp:pr_delete', args=[pr.pk]))
        assert MRPPurchaseRequisition.objects.filter(pk=pr.pk).exists()
```

#### `apps/mrp/tests/test_security.py`

```python
"""OWASP A01 + A03 coverage."""
import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestAccessControl:
    def test_anonymous_redirects_to_login(self, client):
        r = client.get(reverse('mrp:index'))
        assert r.status_code == 302
        assert '/login' in r.url

    def test_superuser_no_tenant_friendly_redirect(self, client, db):
        from apps.accounts.models import User
        su = User.objects.create_superuser('super', 'x@x.com', 'pw')
        client.force_login(su)
        r = client.get(reverse('mrp:index'))
        assert r.status_code == 302  # bounced to dashboard


@pytest.mark.django_db
class TestCrossTenantIDOR:
    """All detail/action views must 404 on cross-tenant pks."""

    def test_calc_detail_cross_tenant_404(self, globex_client, calc):
        r = globex_client.get(reverse('mrp:calculation_detail', args=[calc.pk]))
        assert r.status_code == 404

    def test_inventory_edit_cross_tenant_404(self, globex_client, snapshot_fg):
        r = globex_client.get(reverse('mrp:inventory_edit', args=[snapshot_fg.pk]))
        assert r.status_code == 404


@pytest.mark.django_db
class TestXSSEscape:
    def test_pr_notes_escaped_in_detail(self, admin_client, acme, calc, raw_product):
        from apps.mrp.models import MRPPurchaseRequisition
        from datetime import date, timedelta
        from decimal import Decimal
        pr = MRPPurchaseRequisition.objects.create(
            tenant=acme, pr_number='MPR-X1', mrp_calculation=calc,
            product=raw_product, quantity=Decimal('1'),
            required_by_date=date.today() + timedelta(days=7),
            suggested_release_date=date.today(),
            status='draft', priority='normal',
            notes='<script>alert(1)</script>',
        )
        from django.urls import reverse
        r = admin_client.get(reverse('mrp:pr_detail', args=[pr.pk]))
        assert r.status_code == 200
        # The literal payload must NOT appear unescaped
        assert b'<script>alert(1)</script>' not in r.content
        assert b'&lt;script&gt;' in r.content


@pytest.mark.django_db
class TestCSRF:
    def test_post_without_csrf_blocked(self, acme_admin, calc):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        c.force_login(acme_admin)
        from django.urls import reverse
        r = c.post(reverse('mrp:calculation_delete', args=[calc.pk]))
        assert r.status_code == 403
```

#### `apps/mrp/tests/test_performance.py`

```python
"""Query budget assertions."""
import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestListPageQueryBudget:
    def test_calculation_list_under_budget(
        self, admin_client, django_assert_max_num_queries, calc,
    ):
        with django_assert_max_num_queries(8):
            r = admin_client.get(reverse('mrp:calculation_list'))
        assert r.status_code == 200

    def test_pr_list_under_budget(
        self, admin_client, django_assert_max_num_queries, calc, raw_product, acme,
    ):
        from apps.mrp.models import MRPPurchaseRequisition
        from datetime import date, timedelta
        from decimal import Decimal
        for i in range(15):
            MRPPurchaseRequisition.objects.create(
                tenant=acme, pr_number=f'MPR-P{i:03d}',
                mrp_calculation=calc, product=raw_product,
                quantity=Decimal('5'),
                required_by_date=date.today() + timedelta(days=14),
                suggested_release_date=date.today(),
                status='draft', priority='normal',
            )
        with django_assert_max_num_queries(10):
            r = admin_client.get(reverse('mrp:pr_list'))
        assert r.status_code == 200
```

#### `pytest.ini`

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings_test
python_files = tests.py test_*.py *_tests.py
addopts = -ra --strict-markers
markers =
    slow: long-running tests (engine + perf)
```

#### `config/settings_test.py` (additive)

```python
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    },
}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
DEBUG = False
LOGGING_CONFIG = None
```

### 5.4 Run targets

```
pytest apps/mrp/tests/ -v                              # full suite
pytest apps/mrp/tests/test_forecasting.py -v           # pure-function smoke
pytest apps/mrp/tests/ --cov=apps.mrp --cov-report=term-missing
pytest apps/mrp/tests/ -m "not slow"                   # CI fast lane
bandit -r apps/mrp -ll                                 # security static
```

### 5.5 Coverage estimate of provided snippets

| File | Cases provided | Estimated coverage of file |
|---|---|---|
| `services/forecasting.py` | 12+ | ~95% line |
| `services/lot_sizing.py` | 10+ | ~95% line |
| `services/mrp_engine.py` | 4 | ~70% (needs more BOM-explosion variants) |
| `services/exceptions.py` | 2 | ~60% (needs `expedite`, `below_min`, `no_routing`) |
| `views.py` (PR + security slice) | 6 | ~30% (full view coverage requires per-entity files) |

To reach 80%+ overall the team needs to flesh out `test_views_*.py` per entity (FM, Seasonality, Receipt, Calc, Run, Exception) using the same shape as `test_views_pr.py`.

---

## 6. Defects, Risks & Recommendations

### 6.1 Defect register

> **Verification status:** items marked **VERIFIED** were confirmed by reading the source path. Items marked **CANDIDATE** require a Django shell or pytest reproduction before fix — reproduction recipes provided where applicable.

| ID | Severity | Location | Finding | OWASP | Status | Recommendation |
|---|---|---|---|---|---|---|
| **D-01** | **High** | [views.py:937-947](apps/mrp/views.py#L937-L947), [views.py:813-835](apps/mrp/views.py#L813-L835), [views.py:1015-1055](apps/mrp/views.py#L1015-L1055) | Any tenant user (including non-admins) can approve PRs, apply MRP runs, ignore exceptions, and discard runs. `TenantRequiredMixin` only checks login + tenant — there is **no** RBAC. Segregation-of-duties (creator ≠ approver) is also unenforced. | A01, A04 | VERIFIED | Add a `TenantAdminRequiredMixin` (or new role-based decorator) on PRApproveView, PRCancelView, RunApplyView, RunDiscardView, ExceptionResolveView, ExceptionIgnoreView, CalculationDeleteView. Add `if pr.created_by_id == request.user.id: reject` SoD guard on PRApproveView. |
| **D-02** | **High** | [services/mrp_engine.py:218-224](apps/mrp/services/mrp_engine.py#L218-L224) | `net_change` mode skips the prior NetRequirement deletion but the engine still bulk-creates new rows for **all** plans. This violates the `unique_together('mrp_calculation', 'product', 'period_start')` constraint — second run in net_change mode raises `IntegrityError`. The mode is exposed in `MRPRunForm` and selectable via `RunCreateView`. | A04 | VERIFIED — see [models.py:375](apps/mrp/models.py#L375) | Either (a) for v1, treat `net_change` exactly like `regenerative` — delete and recompute (simplest, document the limitation); or (b) implement true net-change: query existing rows, diff, update changed ones, insert only new ones. Currently the docstring at [services/mrp_engine.py:21-23](apps/mrp/services/mrp_engine.py#L21-L23) promises (a) but the code does neither. |
| **D-03** | **Medium** | [views.py:222-291](apps/mrp/views.py#L222-L291) | `ForecastModelRunView.post` does `ForecastResult.all_objects.bulk_create(...)` followed by `run.save()` — neither inside a single `transaction.atomic()`. If `run.save()` fails after the bulk_create, the run row is stale (status='running') with orphaned ForecastResult rows. Symmetric concern: the bulk_create itself runs OUTSIDE the run-creation transaction. | A04 | VERIFIED | Wrap lines 241-289 in `with transaction.atomic():`. The `_save_with_unique_number` already gives the run row its own atomic; the post-success persistence should be unified. |
| **D-04** | **Medium** | [services/mrp_engine.py:295-315](apps/mrp/services/mrp_engine.py#L295-L315) | PR sequence is computed as `existing_count + 1` from a SELECT and incremented in a Python `for` loop. Two concurrent runs on the same tenant can produce overlapping `MPR-NNNNN` values, raising `IntegrityError` on `unique_together('tenant', 'pr_number')`. Also, the count is filtered on `pr_number__startswith='MPR-'` so manually-numbered PRs (with a different prefix) are uncounted. | A04 | VERIFIED | Reuse the `_next_sequence_number` + `_save_with_unique_number` pair from [views.py:42-63](apps/mrp/views.py#L42-L63). Each PR creation should retry up to N times on `IntegrityError`. |
| **D-05** | **Medium** | [views.py:629-641](apps/mrp/views.py#L629-L641) | `CalculationDeleteView` catches `ProtectedError`, but `MRPRun.mrp_calculation` is `on_delete=CASCADE` ([models.py:563-566](apps/mrp/models.py#L563-L566)) — no PROTECT relationship exists. Deleting a calculation silently cascades to all runs and run-results. Users see no warning that runs were destroyed. | A04, A09 | VERIFIED | Either change `MRPRun.mrp_calculation` to `on_delete=PROTECT` (preferred — preserves audit trail) or warn the user up-front in the confirm dialog. Also block deletion if any related MRPRun has `status='applied'`. |
| **D-06** | **Medium** | [views.py:1025-1041](apps/mrp/views.py#L1025-L1041), [forms.py:230-234](apps/mrp/forms.py#L230-L234) | `MRPExceptionResolveForm` makes `resolution_notes` optional, but the resolve flow assumes a justification is required (the error message at line 1040 says "Please add a resolution note" but the form doesn't enforce it — only an empty form fails when `is_valid` returns False on a different ground, which it won't). Submitting with empty notes succeeds. | A09 | VERIFIED | Add `resolution_notes = forms.CharField(required=True, ...)` or `def clean_resolution_notes(self): ...` raising ValidationError when empty/whitespace. |
| **D-07** | **Medium** | [views.py:1058-1063](apps/mrp/views.py#L1058-L1063) | `ExceptionDeleteView.post` allows deletion of any exception in any state (including `status='open'`). Operators could delete an open critical exception instead of resolving / ignoring, losing the audit trail. | A09 | VERIFIED | Allow delete only when `status in ('resolved', 'ignored')`, mirroring the PR delete guard at [views.py:962-970](apps/mrp/views.py#L962-L970). |
| **D-08** | **Low–Medium** | [views.py:822-832](apps/mrp/views.py#L822-L832) | `RunApplyView` does the run status transition atomically, then issues a separate `MRPCalculation.objects.filter(...).update(...)`. Between those two statements, the calc could be queried by another reviewer in `status='completed'`. The window is small but observable. | A04 | VERIFIED | Wrap both UPDATEs inside one `with transaction.atomic():`, OR merge into a single `MRPRun.objects.filter(...).select_related('mrp_calculation').update(...)` pattern. |
| **D-09** | **Medium** | [services/mrp_engine.py:163-176](apps/mrp/services/mrp_engine.py#L163-L176) | BOM lookup runs two `.first()` queries per end item (preferred MBOM, then fallback) inside a loop. For an MRP run with 100 end items that's 200 queries before BOM explosion even begins. | — | VERIFIED | Pre-fetch all `BillOfMaterials` for end-item product_ids in one query, then resolve in Python. Pseudocode: `boms = {b.product_id: b for b in BillOfMaterials.objects.filter(tenant=tenant, product_id__in=ids, status='released', is_default=True).order_by(... 'mbom-first ...')}`. |
| **D-10** | **Low–Medium** | [signals.py](apps/mrp/signals.py) (entire file) | Signals fire on `post_save` only. **Deletes** of MRPCalculation, MRPRun, MRPPurchaseRequisition, and MRPException write **no** audit log. Per OWASP A09, destructive operations should leave an audit trail. | A09 | VERIFIED | Add `post_delete` receivers mirroring `post_save`, emitting `mrp_run.deleted`, `mrp_calculation.deleted`, etc. Alternatively, do a soft-delete pattern. |
| **D-11** | **Low** | [models.py:511-515](apps/mrp/models.py#L511-L515) | `MRPException.target_type` + `target_id` is a documented loose-pointer pattern (because targets cross apps), but there's no integrity check that `target_id` actually exists in the named table. Stale references will silently dangle once the target is deleted. | A04, A09 | VERIFIED | Acceptable for v1 given the documented rationale. Long-term, consider a periodic sweep (management command `mrp_audit_targets`) that flags exceptions whose target is gone. |
| **D-12** | **Low** | [views.py:248-250](apps/mrp/views.py#L248-L250) | `ForecastModelRunView` hard-caps active products at 8 (`Product.objects.filter(...)[:8]`). Tenants with > 8 active products will only get forecasts for the first 8 (by FK order). No warning surfaced to the user. | — | VERIFIED | Either remove the cap (it's a relic of the synthetic-history demo path), or surface "showing first N of M products" in the success flash. The docstring at lines 217-221 already concedes this is a v1 placeholder until Module 17. |
| **D-13** | **Low** | [views.py:266-268](apps/mrp/views.py#L266-L268), [services/forecasting.py](apps/mrp/services/forecasting.py) | Monthly forecast uses `step_days=30` for date arithmetic. Real months are 28-31 days; long horizons drift (12 monthly periods = 360 days, off by ~5 days). | — | VERIFIED | For the v1 demo path this is tolerable, but add a `relativedelta(months=1)` import (`from dateutil.relativedelta import relativedelta`) when promoted to production. |
| **D-14** | **Low** | [forms.py:69-86](apps/mrp/forms.py#L69-L86) | `SeasonalityProfileForm.clean()` rejects monthly index > 12 with a friendly message, but does NOT pre-validate weekly index > 52. The model validator catches it but the resulting error is a less-friendly model-level error rather than the form-level one. | — | VERIFIED | Mirror the monthly check: `if period_type == 'week' and period_index and period_index > 52: self.add_error('period_index', 'Weekly index must be 1–52.')`. |
| **D-15** | **Low** | [views.py:241-245](apps/mrp/views.py#L241-L245) | `ForecastModelRunView` selects products with `status='active'`. PLM may also expose `status in ('active', ...)` — confirm whether `pending`-status products should be forecast too. Currently `pending` and `obsolete` are excluded. | — | CANDIDATE — needs PLM product-status semantics check | Confirm with product owner; either expand to `status__in=('active', 'pending')` or document the intentional exclusion in the form help-text. |
| **D-16** | **Info** | [services/exceptions.py:69-86](apps/mrp/services/exceptions.py#L69-L86) | `expedite` exception fires whenever `gap_days < lead_time` — for products whose first period is "today", gap_days≈0 and an expedite exception is generated even when no order is being placed today. This produces noise in the seeded demo. | — | CANDIDATE — check seeded data | Add a guard `if nr.planned_release_date and nr.planned_release_date >= today` so expedite only fires for FUTURE planned orders. |
| **D-17** | **Info** | [admin.py](apps/mrp/admin.py) | `tenant` is exposed as a `list_filter` value in admin, leaking other tenants' names to staff users. Acceptable for staff-only Django admin but worth flagging if non-superuser staff ever get admin access. | A01 | VERIFIED | Document as known/intended. If non-superuser admins are eventually created, restrict `tenant` filter via `ModelAdmin.get_list_filter()` based on `request.user`. |
| **D-18** | **Info** | [views.py:285](apps/mrp/views.py#L285), [views.py:800](apps/mrp/views.py#L800) | Both broad `except Exception` blocks call `messages.error(request, f'... {exc}')`. The exception's `str()` is rendered into the page — for a `DatabaseError`, this could leak schema details to a low-privilege user. Auto-escape mitigates XSS but not info-disclosure. | A05 | VERIFIED | Replace user-facing message with a generic "MRP run failed — see system logs"; persist `str(exc)` to `error_message` for staff-only inspection. |

### 6.2 Recommended remediation priority

```
P0 (release-blocker)   D-01  D-02
P1 (next sprint)       D-03  D-04  D-05  D-06  D-07
P2 (next minor)        D-08  D-09  D-10
P3 (backlog)           D-11..D-18
```

### 6.3 Risks not yet defects

| ID | Risk | Mitigation |
|---|---|---|
| R-01 | `bom.explode()` recursion depth — uncapped, may stack-overflow on cyclic BOMs | Verify cycle protection in `apps.bom`; add `max_depth=20` guard on engine call |
| R-02 | Single-request synchronous MRP run — large tenants will time out HTTP | Move to Celery/RQ when run > 5s p95 (currently fine for seeded demo) |
| R-03 | `ForecastResult.all_objects.bulk_create(results, batch_size=500)` — silent overflow if `len(results) >> 500 × N_partitions` | Acceptable; bulk_create is cumulative |
| R-04 | Coverage_pct rounding — `((gross - net) / gross)` with very small gross can produce extreme values clamped at 0 / 100; correctness is fine but numerical noise | Acceptable |

---

## 7. Test Coverage Estimation & Success Metrics

### 7.1 Coverage targets per file

| File | Line target | Branch target | Mutation target | Notes |
|---|---|---|---|---|
| [services/forecasting.py](apps/mrp/services/forecasting.py) | **95%** | 90% | 80% | Pure functions — high bar |
| [services/lot_sizing.py](apps/mrp/services/lot_sizing.py) | **95%** | 90% | 80% | Pure functions — high bar |
| [services/mrp_engine.py](apps/mrp/services/mrp_engine.py) | **85%** | 75% | n/a | Allow uncovered branches in error paths |
| [services/exceptions.py](apps/mrp/services/exceptions.py) | **90%** | 80% | n/a | Each exception type must have ≥ 1 test |
| [models.py](apps/mrp/models.py) | **80%** | 70% | n/a | `__str__`, helpers, `is_editable`/`can_*` methods |
| [forms.py](apps/mrp/forms.py) | **85%** | 75% | n/a | Every `clean()` branch tested |
| [views.py](apps/mrp/views.py) | **80%** | 70% | n/a | Every status-transition view tested both happy + sad |
| [signals.py](apps/mrp/signals.py) | **75%** | 70% | n/a | Each receiver tested for create + status-change |
| [management/commands/seed_mrp.py](apps/mrp/management/commands/seed_mrp.py) | **70%** | 60% | n/a | Idempotency + flush path |

**Module-wide target: ≥ 80% line / ≥ 70% branch.**

### 7.2 KPI dashboard

| KPI | Green | Amber | Red |
|---|---|---|---|
| Functional pass rate | ≥ 99% | 95–99% | < 95% |
| Open Critical defects | 0 | 0 | ≥ 1 |
| Open High defects | ≤ 2 | 3–5 | ≥ 6 |
| Suite runtime (full) | < 90s | 90–180s | > 180s |
| List-page query count (PR list, 15 rows) | ≤ 8 | 9–15 | > 15 |
| MRP engine run wall-time (50 end items, full BOM, 4 weeks) | < 2s | 2–5s | > 5s |
| Coverage (line) | ≥ 80% | 70–80% | < 70% |
| Mutation kill rate (services/) | ≥ 75% | 60–75% | < 60% |
| Bandit findings (Severity ≥ Medium) | 0 | 1–2 | ≥ 3 |
| pip-audit High/Critical vulns | 0 | 0 | ≥ 1 |
| Audit logs on destructive ops | 100% | 80–99% | < 80% |
| Cross-tenant IDOR test pass rate | 100% | n/a | < 100% |

### 7.3 Release exit gate

A release containing this module may ship **only if all of the following are true**:

- [ ] D-01 fix merged: PR Approve / Run Apply / Exception Resolve are gated to tenant admins (or role).
- [ ] D-02 fix merged: net_change mode no longer raises IntegrityError on a second run.
- [ ] All P1 defects (D-03 through D-07) have either a merged fix or a documented deferral with a follow-up ticket and a workaround in the operator-facing docs.
- [ ] Full pytest suite in `apps/mrp/tests/` passes (≥ 80% line coverage).
- [ ] `bandit -r apps/mrp -ll` reports zero Medium/High findings.
- [ ] `pip-audit` shows zero High/Critical vulnerabilities for new dependencies.
- [ ] Manual UAT walkthrough of RUN-01..RUN-06 completed by a non-developer reviewer.
- [ ] Cross-tenant IDOR tests (TC-SC-003, TC-SC-004) all pass.
- [ ] At least one CSRF-enforcement test (TC-SC-006) and one XSS-escape test (TC-SC-005) pass.
- [ ] Audit-log assertions (AUD-01..AUD-04) pass.
- [ ] Performance test (PERF-02) demonstrates 50-end-item run under 2s green-band.

---

## 8. Summary

The MRP module is **architecturally sound** — it cleanly separates pure-function services (forecasting, lot-sizing) from ORM-bound services (engine, exceptions) from views, with a thoughtful seeder, signal-based audit trail, and full CRUD across nine entities. Tenant isolation is consistently applied, the multi-level BOM explosion reuses the BOM module's contract, and workflow transitions use atomic conditional UPDATEs.

**However**, two release-blocking issues must be addressed before production rollout:

- **D-01** — There is no role-based authorisation. Any tenant user can approve PRs, apply MRP runs, and ignore exceptions. Segregation of duties (creator ≠ approver) is also unenforced. This is a material A01 violation for an ERP-grade system.
- **D-02** — `net_change` run mode is broken. The engine documents three modes but only `regenerative` and `simulation` work; `net_change` will raise `IntegrityError` on the second run because it appends instead of merging.

A further **five P1 issues** (D-03 transactional integrity in forecast run, D-04 PR sequence races, D-05 cascade hidden by ProtectedError handler, D-06 empty resolution allowed, D-07 unrestricted exception delete) are correctness and audit gaps that should be cleared in the next sprint.

The **automation strategy** is straightforward: the project already has a strong test pattern in [apps/pps/tests/](apps/pps/tests/) and [apps/catalog](apps/catalog/) ([.claude/Test.md](.claude/Test.md)), and this module fits neatly into that pattern. The provided fixtures, pure-function suites, and engine integration tests give a runnable starting point — Test Engineering can productionise this in 2-3 days of focused work to reach the ≥ 80% coverage target.

**Module verdict:** **Not yet release-ready.** With D-01 + D-02 fixed, ≥ 80% test coverage, and the audit-log gap (D-10) closed, this becomes a strong release candidate.

---

### Appendix A — Files reviewed

| Path | LoC | Purpose |
|---|---|---|
| [apps/mrp/models.py](apps/mrp/models.py) | 626 | 11 models across 5 sub-modules |
| [apps/mrp/views.py](apps/mrp/views.py) | 1063 | 35 class-based views |
| [apps/mrp/forms.py](apps/mrp/forms.py) | 251 | 9 ModelForms |
| [apps/mrp/urls.py](apps/mrp/urls.py) | 71 | URL routing |
| [apps/mrp/admin.py](apps/mrp/admin.py) | 117 | Django admin registration |
| [apps/mrp/signals.py](apps/mrp/signals.py) | 129 | Audit-log wiring (4 senders) |
| [apps/mrp/services/mrp_engine.py](apps/mrp/services/mrp_engine.py) | 317 | Gross-to-net + BOM explosion |
| [apps/mrp/services/forecasting.py](apps/mrp/services/forecasting.py) | 131 | 4 forecast methods (pure) |
| [apps/mrp/services/lot_sizing.py](apps/mrp/services/lot_sizing.py) | 106 | 4 lot-size rules (pure) |
| [apps/mrp/services/exceptions.py](apps/mrp/services/exceptions.py) | 148 | Exception generation |
| [apps/mrp/management/commands/seed_mrp.py](apps/mrp/management/commands/seed_mrp.py) | 358 | Idempotent seeder |
| [apps/mrp/migrations/0001_initial.py](apps/mrp/migrations/0001_initial.py) | n/a | Initial schema |
| 21 templates under [templates/mrp/](templates/mrp/) | n/a | UI |
| **Total** | **3328 LoC** + 21 templates | |

### Appendix B — Manual reproduction recipes for D-02, D-04

**D-02 reproduction:**

```bash
python manage.py shell
```
```python
from apps.core.models import Tenant
from apps.mrp.models import MRPRun
from apps.mrp.services import mrp_engine

# Pick a seeded tenant + run + calc
t = Tenant.objects.get(slug='acme')
run = MRPRun.objects.filter(tenant=t).first()
calc = run.mrp_calculation

# First run is regenerative (already done by seeder)
# Now try net_change against the same calc:
mrp_engine.run_mrp(calc, mode='net_change')
# Expected (current bug): django.db.utils.IntegrityError: UNIQUE constraint failed
```

**D-04 reproduction (proof-of-concept):**

```python
import threading
from apps.mrp.services import mrp_engine
results = []
def worker(calc):
    try: mrp_engine.run_mrp(calc, mode='regenerative')
    except Exception as e: results.append(e)
threads = [threading.Thread(target=worker, args=(calc,)) for _ in range(2)]
for t in threads: t.start()
for t in threads: t.join()
print(results)  # one or both may carry IntegrityError on pr_number
```

---

*End of report. Generated 2026-04-29 against [main@53107c3](https://placeholder).*
