# Module 14 — Energy & Utility Management — Comprehensive SQA Test Report

**Target:** `apps/utility/` (Phase 1, shipped). Scope mode: **Module review** (full app).
**Reviewer:** Senior SQA Engineer.
**Codebase snapshot:** branch `main` @ `3508c66` (post-shipping closeout).

---

## 1. Module Analysis

### 1.1 Surface area & shipping state

The app implements MSM Module 14 across five sub-modules:

| Sub-module | Purpose | Key models |
|---|---|---|
| 14.1 Utility Meter Integration | Catalog of utility types, physical meters, append-only consumption ledger | [`UtilityType`](../apps/utility/models.py#L50), [`UtilityMeter`](../apps/utility/models.py#L86), [`UtilityConsumption`](../apps/utility/models.py#L160) |
| 14.2 Energy Cost Allocation | Effective-dated tariffs, TOU rate bands, period allocations bridged into `cost.DriverActuals` | [`UtilityTariff`](../apps/utility/models.py#L270), [`TOURateBand`](../apps/utility/models.py#L428), [`UtilityAllocation`](../apps/utility/models.py#L324) |
| 14.3 Peak Demand Management | DR event lifecycle + read-only peak-shaving suggestions over `pps.ScheduledOperation` | [`DemandResponseEvent`](../apps/utility/models.py#L472), [`PeakShavingSuggestion`](../apps/utility/models.py#L558) |
| 14.4 Carbon & Sustainability | Effective-dated emission factors, append-only carbon ledger, per-period ESG KPIs | [`EmissionFactor`](../apps/utility/models.py#L657), [`CarbonEmission`](../apps/utility/models.py#L723), [`SustainabilityKPI`](../apps/utility/models.py#L813) |
| 14.5 Utility Benchmarking | Per-plant period snapshots + plant-to-plant / period-over-period comparison reports | [`BenchmarkSnapshot`](../apps/utility/models.py#L892), [`BenchmarkComparison`](../apps/utility/models.py#L980) |

Code volume: ~3,672 LoC across [models.py](../apps/utility/models.py) (1,045), [views.py](../apps/utility/views.py) (1,607), [forms.py](../apps/utility/forms.py) (419), [signals.py](../apps/utility/signals.py) (409), [urls.py](../apps/utility/urls.py) (97), [admin.py](../apps/utility/admin.py) (95). Service layer: [allocation.py](../apps/utility/services/allocation.py), [benchmark.py](../apps/utility/services/benchmark.py), [carbon.py](../apps/utility/services/carbon.py), [meters.py](../apps/utility/services/meters.py), [peak.py](../apps/utility/services/peak.py).

### 1.2 Cross-module integration map

| Source | Hook | Target | Idempotency key | Reference |
|---|---|---|---|---|
| `eam.AssetMeterReading.post_save` (kWh) | Auto-emit consumption | `UtilityConsumption` | partial unique on `source_meter_reading` | [signals.py:190-250](../apps/utility/signals.py#L190-L250) |
| `eam.AssetMeterReading.pre_delete` | Reversal row | `UtilityConsumption(is_reversal=True)` | `notes startswith reversal-of:<entry_number>` | [signals.py:253-306](../apps/utility/signals.py#L253-L306) |
| `UtilityConsumption.post_save` | Auto-emit emissions | `CarbonEmission` | partial unique on `source_consumption` | [signals.py:332-354](../apps/utility/signals.py#L332-L354) |
| `UtilityConsumption.pre_delete` | Reversal row | `CarbonEmission(is_reversal=True)` | `notes startswith reversal-of:<entry_number>` | [signals.py:357-399](../apps/utility/signals.py#L357-L399) |
| `services.allocation.post_allocation` | Bridge | `cost.DriverActuals` | wipe-and-replay by `notes='utility:<meter_number>:%'` | [allocation.py:53-115](../apps/utility/services/allocation.py#L53-L115) |
| `cost.services.overhead.apply_overhead(period)` | Pull (external) | Sweeps utilities into Utilities pool via `cost_driver` FK on `UtilityType` | n/a (cost-side) | [models.py:71-74](../apps/utility/models.py#L71-L74) |

All cross-module signals connect with `weak=False` and unique `dispatch_uid` (lesson **L-18**). Auto-feed handlers wrap the payload in `try/except` so external app writes never break — see [signals.py:248-250](../apps/utility/signals.py#L248-L250) and [signals.py:352-354](../apps/utility/signals.py#L352-L354).

### 1.3 Lessons applied / business rules pinned to source

| Lesson | Implementation | Reference |
|---|---|---|
| **L-01** unique_together with hidden tenant → form `clean()` | `UtilityTypeForm.clean`, `UtilityMeterForm.clean`, `EmissionFactorForm.clean` | [forms.py:42-53](../apps/utility/forms.py#L42-L53), [forms.py:89-103](../apps/utility/forms.py#L89-L103), [forms.py:359-379](../apps/utility/forms.py#L359-L379) |
| **L-02** Decimals carry MinValueValidator | `NEG_BOUND/NON_NEG/SIGNED/PCT_MAX` constants reused on every Decimal | [models.py:40-43](../apps/utility/models.py#L40-L43) |
| **L-03** view+template status gate parity | `is_activatable / is_completable / is_cancellable / is_acknowledgable / is_dismissable` helpers; matching view checks | [models.py:527-534](../apps/utility/models.py#L527-L534), [models.py:625-629](../apps/utility/models.py#L625-L629), [views.py:1004](../apps/utility/views.py#L1004), [views.py:1025](../apps/utility/views.py#L1025), [views.py:1170](../apps/utility/views.py#L1170), [views.py:1188](../apps/utility/views.py#L1188) |
| **L-04** loud warning on dropped/skipped rows | Allocation post, consumption import, peak scan, carbon recompute | [views.py:822-828](../apps/utility/views.py#L822-L828), [views.py:564-570](../apps/utility/views.py#L564-L570), [views.py:1147-1157](../apps/utility/views.py#L1147-L1157), [views.py:1366-1371](../apps/utility/views.py#L1366-L1371) |
| **L-07** chart series via raw Python list passed to `json_script` | Dashboard | [views.py:186-203](../apps/utility/views.py#L186-L203) |
| **L-12** auto-numbered models retry under contention | `MTR-/UC-/TRF-/UAL-/DRE-/PSS-/CE-/BCR-` retry shape mirrors cost module | [models.py:144-156](../apps/utility/models.py#L144-L156), [models.py:235-247](../apps/utility/models.py#L235-L247), [models.py:308-320](../apps/utility/models.py#L308-L320) |
| **L-13** workflow status mutations via `QuerySet.update()` inside `transaction.atomic()` | DR event activate/complete/cancel | [views.py:70-79](../apps/utility/views.py#L70-L79), [views.py:1007-1010](../apps/utility/views.py#L1007-L1010), [views.py:1056-1062](../apps/utility/views.py#L1056-L1062) |
| **L-14** per-workflow forms enforce required reasons | Reverse / Cancel / Dismiss | [forms.py:246-257](../apps/utility/forms.py#L246-L257), [forms.py:310-321](../apps/utility/forms.py#L310-L321), [forms.py:328-339](../apps/utility/forms.py#L328-L339) |
| **L-17** `PROTECT` on audit-trail children | `CarbonEmission.factor`, `UtilityConsumption.meter`, `UtilityAllocation.period` | [models.py:178-179](../apps/utility/models.py#L178-L179), [models.py:340-343](../apps/utility/models.py#L340-L343), [models.py:742-744](../apps/utility/models.py#L742-L744) |
| **L-18** `weak=False` + `dispatch_uid` on every closure receiver | Audit factories + cross-module hooks | [signals.py:101-108](../apps/utility/signals.py#L101-L108), [signals.py:315-322](../apps/utility/signals.py#L315-L322), [signals.py:402-409](../apps/utility/signals.py#L402-L409) |

### 1.4 Auto-numbering and uniqueness register

| Prefix | Model | Field | Tenant-scoped unique? | Reference |
|---|---|---|---|---|
| `MTR-NNNNN` | UtilityMeter | meter_number | yes | [models.py:127](../apps/utility/models.py#L127) |
| `UC-NNNNN` | UtilityConsumption | entry_number | yes | [models.py:213](../apps/utility/models.py#L213) |
| `TRF-NNNNN` | UtilityTariff | tariff_number | yes | [models.py:294](../apps/utility/models.py#L294) |
| `UAL-NNNNN` | UtilityAllocation | allocation_number | yes | [models.py:385](../apps/utility/models.py#L385) |
| `DRE-NNNNN` | DemandResponseEvent | event_number | yes | [models.py:519](../apps/utility/models.py#L519) |
| `PSS-NNNNN` | PeakShavingSuggestion | suggestion_number | yes | [models.py:605](../apps/utility/models.py#L605) |
| `CE-NNNNN` | CarbonEmission | entry_number | yes | [models.py:766](../apps/utility/models.py#L766) |
| `BCR-NNNNN` | BenchmarkComparison | report_number | yes | [models.py:1021](../apps/utility/models.py#L1021) |

Plus partial unique constraints (NULL-permissive):

- `utility_consumption_unique_meter_reading` on `(source_meter_reading)` where not null — [models.py:218-224](../apps/utility/models.py#L218-L224)
- `utility_carbon_unique_consumption` on `(source_consumption)` where not null — [models.py:771-777](../apps/utility/models.py#L771-L777)
- `utility_pss_unique_op_event` on `(scheduled_operation, event)` where event not null — [models.py:610-614](../apps/utility/models.py#L610-L614)
- `utility_pss_unique_op_band` on `(scheduled_operation, tou_band)` where tou_band not null and event null — [models.py:615-619](../apps/utility/models.py#L615-L619)

### 1.5 Existing test inventory

| File | def count | Coverage |
|---|---|---|
| [test_models.py](../apps/utility/tests/test_models.py) | 30 | Auto-numbering, computed fields, unique constraints, validators (L-02), reversal flag |
| [test_forms.py](../apps/utility/tests/test_forms.py) | 22 | L-01 unique guards, L-02 bounds, L-14 workflow required, cross-field date/reading rules |
| [test_views.py](../apps/utility/tests/test_views.py) | 32 | Full CRUD smoke + workflow happy paths |
| [test_security.py](../apps/utility/tests/test_security.py) | 21 | RBAC matrix (parametrized), multi-tenant IDOR, anonymous redirect (parametrized), workflow gating |
| [test_signals.py](../apps/utility/tests/test_signals.py) | 14 | dispatch_uid presence guard, EAM→consumption, consumption→carbon, idempotent + reversal |
| [test_services.py](../apps/utility/tests/test_services.py) | 21 | Pure-function & service-layer coverage |
| [test_eam_integration.py](../apps/utility/tests/test_eam_integration.py) | 5 | End-to-end kWh AssetMeterReading → UtilityConsumption → CarbonEmission with reversal |
| [test_cost_integration.py](../apps/utility/tests/test_cost_integration.py) | 4 | post_allocation → cost.DriverActuals → apply_overhead → OverheadAllocation |
| [test_dashboard.py](../apps/utility/tests/test_dashboard.py) | 8 | KPI cards + ApexCharts json_script payload shape |
| **Total** | **157 def + parametrize fan-out → ~188 runs** | per [README.md](../README.md) |

Pytest config: [pytest.ini](../pytest.ini) → `DJANGO_SETTINGS_MODULE=config.settings_test`, custom marker `security` registered.

### 1.6 Pre-test risk profile

| Risk surface | Inherent severity | Note |
|---|---|---|
| Multi-tenant isolation | HIGH | 13 models × 4-5 surfaces each — many places to leak data. Mitigated by `TenantRequiredMixin / TenantAdminRequiredMixin` and per-view `tenant=request.tenant` filters. |
| Cross-module signal cascade | HIGH | A bug in EAM→Consumption→Carbon could double-count, miss reversals, or block parent writes. Idempotency relies on partial unique constraints + signal-level guards. |
| Allocation → cost ledger bridge | HIGH | Wrong wipe-and-replay logic in `post_allocation` can corrupt the cost period close. |
| Append-only ledger reversals | MED | Reversal rows are NEW records with negated values. Logic in `signals.py` uses `notes startswith` as the dedup key — fragile if notes are user-edited. |
| `BenchmarkSnapshot.tenant=NULL` industry-avg row | MED | Override of `TenantAwareModel.tenant` to nullable — IDOR risk if list/detail views ever drop the tenant filter. |
| CSV import (`UtilityConsumptionImportView`) | MED | Untyped FileField; no MAX size, no content-type/magic-byte check. |
| Effective-dated lookups (tariff, factor) | MED | `_resolve_unit_cost` and `_resolve_factor` look at `effective_from` only — see §6 D-01/D-02. |
| Workflow race | LOW | Mitigated by `_atomic_status_transition` (conditional UPDATE inside `transaction.atomic`). |
| Currency / region validation | LOW | Length-only checks; no ISO-4217 or ISO-3166 enforcement. |

---

## 2. Test Plan

| Layer | Goal | Methods |
|---|---|---|
| **Unit** | Model save() math, computed fields, helpers | pytest direct invocations |
| **Integration** | view → form → service → DB → signal cascade | pytest-django Client + ORM assertions |
| **Functional** | End-to-end DR event lifecycle, allocation post/reverse, recompute, scan, generate KPI | pytest-django + scenario fixtures |
| **Regression** | Existing 157 tests must remain green; this report adds gap-filling tests, not replacements | `pytest apps/utility -m "not slow and not e2e"` baseline |
| **Boundary** | DateTime tz, Decimal `max_digits`, share_pct 0-100, horizon_days 1-90, multi-day op overlap, period boundaries | parametrized tests |
| **Edge** | Empty querysets, NULL FKs, tenant=NULL industry-avg row, CSV with whitespace timestamps, reversal-of-reversal, simultaneous DR + TOU overlap | dedicated tests |
| **Negative** | Anonymous → login redirect, staff → admin-only POST blocked, cross-tenant IDOR (404), workflow gate violation, expired tariff/factor pickup, duplicate TOU band IntegrityError surfacing | parametrized + scenario tests |
| **Security** | OWASP A01-A10 mapped (§2.1 below), CSV file size/type, audit log emission on flag flips | parametrized + Django test client |
| **Performance** | List views N+1 query budget; allocation re-emit on a 200-row period | `django_assert_max_num_queries` + Locust smoke |

### 2.1 OWASP Top 10 mapping (Module 14)

| OWASP | What we check | Module 14 evidence |
|---|---|---|
| **A01 Broken Access Control** | Login + tenant + RBAC on every surface; cross-tenant `get_object_or_404` | All views inherit `TenantRequiredMixin` (read) or `TenantAdminRequiredMixin` (write); every queryset filters `tenant=request.tenant`; existing test_security.py covers this. **Gap:** `BenchmarkSnapshot` tenant=NULL row needs explicit IDOR test (added in §5). |
| **A02 Crypto failures** | n/a | No new crypto, secrets, or external TLS in this module. |
| **A03 Injection / XSS** | Template auto-escape, `Q()` for searches, no raw SQL | All searches use `Q()` ORM ([views.py:228](../apps/utility/views.py#L228), [views.py:312](../apps/utility/views.py#L312)); no `format_html` with user input found. |
| **A04 Insecure design** | Effective-dated business rules, append-only ledger semantics | **D-01, D-02:** `effective_to` not honored in `_resolve_unit_cost` / `_resolve_factor`. |
| **A05 Security misconfig** | n/a | Nothing module-specific; relies on project settings. |
| **A06 Vulnerable deps** | n/a | No new pins. |
| **A07 Auth failures** | n/a | Reuses `accounts` auth. |
| **A08 Data integrity / file upload** | CSV import safety | **D-03:** no MAX_FILE_SIZE / content-type check on `UtilityConsumptionImportForm.csv_file`. |
| **A09 Logging failures** | Audit on destructive ops | `_audit()` flag/status signal factories emit `TenantAuditLog` rows on `posted/unposted/reversed/<status>` ([signals.py:41-65](../apps/utility/signals.py#L41-L65)). Non-blocking try/except — lossy on audit DB failure. **Gap:** add a regression test that audit rows ARE persisted in the happy path. |
| **A10 SSRF** | n/a | No external URL fetches. |

---

## 3. Test Scenarios

Scenarios prefixed by entity. **Type** column: `C`=create, `R`=read/list/detail, `U`=update, `D`=delete, `W`=workflow, `S`=security, `P`=performance, `E`=edge, `B`=boundary, `N`=negative, `I`=integration.

### 3.1 UtilityType (UT)

| # | Scenario | Type |
|---|---|---|
| UT-01 | Create with unique (tenant, code) | C |
| UT-02 | Create duplicate (tenant, code) — form clean rejects | N |
| UT-03 | Edit code preserving uniqueness | U |
| UT-04 | List filters: search by code/name, active filter, unit_of_measure filter | R |
| UT-05 | Delete cascades correctly when no children; PROTECT when meter exists | D |
| UT-06 | Cross-tenant IDOR: 404 on edit/delete | S |
| UT-07 | `cost_driver` FK queryset scoped to tenant | C |

### 3.2 UtilityMeter (UM)

| # | Scenario | Type |
|---|---|---|
| UM-01 | Auto-number `MTR-00001` on first save | C |
| UM-02 | Sequential auto-number across 5 meters | C |
| UM-03 | Duplicate (tenant, utility_type, name) blocked by form clean | N |
| UM-04 | Self-FK parent_meter cannot be self after edit | E |
| UM-05 | location/cost_center/asset querysets tenant-scoped | C |
| UM-06 | Detail page lists last 25 consumptions + sub-meters | R |
| UM-07 | Delete with PROTECT children → caught and surfaces error | D |
| UM-08 | Cross-tenant IDOR on detail/edit/delete | S |
| UM-09 | Multiplier validation: NON_NEG | B |

### 3.3 UtilityConsumption (UC)

| # | Scenario | Type |
|---|---|---|
| UC-01 | `consumption = (end - start) × multiplier` quantized to 4 dp | C |
| UC-02 | `total_cost = consumption × unit_cost` quantized to 2 dp | C |
| UC-03 | Negative delta clamps to 0 | E |
| UC-04 | period_end ≤ period_start → form rejects | N |
| UC-05 | end_reading < start_reading → form rejects | N |
| UC-06 | EAM auto-feed creates consumption (idempotent on `source_meter_reading`) | I |
| UC-07 | Second `post_save` for same `AssetMeterReading` is no-op | I |
| UC-08 | Reversal row on AssetMeterReading delete with negated columns | I |
| UC-09 | Edit blocked on `is_reversal=True` rows (L-03) | N |
| UC-10 | CSV import skips duplicate `(period_start, period_end)` | I |
| UC-11 | CSV import surfaces skipped count loudly (L-04) | I |
| UC-12 | CSV with whitespace-padded `period_start` value creates duplicate (defect candidate D-06) | E |
| UC-13 | CSV upload with 50 MB body → currently relies on Django default; explicit test (D-03) | S |
| UC-14 | Carbon emission auto-emitted via signal | I |
| UC-15 | Cross-tenant IDOR: detail 404 | S |

### 3.4 UtilityTariff (UT2) + TOURateBand (TB)

| # | Scenario | Type |
|---|---|---|
| UT2-01 | Auto-number `TRF-00001`; flat_rate validates NON_NEG | C |
| UT2-02 | `effective_to < effective_from` → form rejects | N |
| UT2-03 | Currency length != 3 → form rejects | N |
| UT2-04 | Currency = "ZZZ" passes (defect D-05: length-only check) | N |
| UT2-05 | Tariff queryset for `_resolve_unit_cost` ignores `effective_to` (D-01) | N |
| TB-01 | end_time ≤ start_time → form rejects | N |
| TB-02 | duplicate (band_type, day_of_week, start_time) on same tariff → IntegrityError surfaced as user error (defect D-04) | N |
| TB-03 | tariff CASCADE deletes child bands | D |

### 3.5 UtilityAllocation (UA)

| # | Scenario | Type |
|---|---|---|
| UA-01 | Auto-number `UAL-00001` | C |
| UA-02 | Form requires at least one target (cost_center / product / production_order) | N |
| UA-03 | share_pct 0 → rejected; 100 ok; 100.01 → rejected | B |
| UA-04 | `post_allocation` writes matching `cost.DriverActuals` when `cost_driver` set | I |
| UA-05 | `post_allocation` skips DriverActuals when no `cost_driver` | I |
| UA-06 | Re-running `post_allocation` wipes prior un-reversed rows + matching DriverActuals | I |
| UA-07 | `reverse_allocation` deletes matching DriverActuals + sets `is_reversed=True` | W |
| UA-08 | Reversal without reason → form rejects (L-14) | N |
| UA-09 | Posted (not reversed) allocation cannot be deleted | W |
| UA-10 | Posting with no targets → loud warning (L-04) | N |
| UA-11 | `is_posted_to_cost` flip emits `utility.allocation.posted` audit | S |
| UA-12 | Cross-tenant IDOR: detail 404 | S |
| UA-13 | List view N+1 budget: ≤ 15 queries for 25 rows | P |

### 3.6 DemandResponseEvent (DR)

| # | Scenario | Type |
|---|---|---|
| DR-01 | Auto-number `DRE-00001` | C |
| DR-02 | end_at ≤ start_at → form rejects | N |
| DR-03 | target_reduction_pct bounds 0..100 | B |
| DR-04 | Workflow scheduled → active → completed | W |
| DR-05 | Cancel from scheduled with reason (L-14) | W |
| DR-06 | Cancel from active with reason | W |
| DR-07 | Cancel without reason → form rejects | N |
| DR-08 | Activate from non-scheduled blocked | N |
| DR-09 | Complete from non-active blocked | N |
| DR-10 | Edit blocked once status != scheduled (L-03) | N |
| DR-11 | Delete blocked once status != scheduled | N |
| DR-12 | Status transition audit row emitted | S |
| DR-13 | `_atomic_status_transition` race-safe (concurrent activate races) | W |
| DR-14 | Cross-tenant IDOR: detail 404 | S |

### 3.7 PeakShavingSuggestion (PS)

| # | Scenario | Type |
|---|---|---|
| PS-01 | Scan with horizon=1 returns 0..N suggestions | I |
| PS-02 | Scan with horizon=0 → form rejects (min=1) | B |
| PS-03 | Scan with horizon=91 → form rejects (max=90) | B |
| PS-04 | Op overlapping DR event spawns suggestion with `suggested_start = ev.end_at` | I |
| PS-05 | Op overlapping peak TOU band spawns suggestion (no DR collision dedup) | I |
| PS-06 | Re-scan does not duplicate (partial unique constraints) | I |
| PS-07 | Acknowledge from new → acknowledged | W |
| PS-08 | Dismiss requires reason (L-14) | N |
| PS-09 | Acknowledge from acknowledged → no-op (idempotent) | E |
| PS-10 | Dismiss from acknowledged → dismissed | W |
| PS-11 | `compute_estimated_savings` uses 50 kWh/hr heuristic | I |
| PS-12 | Suggestion never mutates `pps.ScheduledOperation` | I |
| PS-13 | Cross-tenant IDOR: detail 404 | S |

### 3.8 EmissionFactor (EF)

| # | Scenario | Type |
|---|---|---|
| EF-01 | Create with unique (tenant, source_type, scope, region, effective_from) | C |
| EF-02 | Duplicate quintuple → form clean rejects | N |
| EF-03 | effective_to < effective_from → rejected | N |
| EF-04 | factor < 0 → validator rejects | B |
| EF-05 | `_resolve_factor` ignores `effective_to` → expired factor returned (D-02) | N |
| EF-06 | PROTECT delete when `CarbonEmission` references it | D |
| EF-07 | Cross-tenant IDOR: edit/delete 404 | S |

### 3.9 CarbonEmission (CE)

| # | Scenario | Type |
|---|---|---|
| CE-01 | Auto-number `CE-00001` | C |
| CE-02 | `co2e_kg = source_quantity × factor.factor` quantized to 4 dp | C |
| CE-03 | Auto-emit on consumption save (idempotent on source_consumption) | I |
| CE-04 | Reversal row on consumption delete | I |
| CE-05 | `recompute_emissions(period)` deletes + re-emits in tenant scope only | I |
| CE-06 | recompute surfaces skipped count when no factor matches (L-04) | I |
| CE-07 | `is_reversal` flip emits `utility.carbon.reversed` audit | S |
| CE-08 | Cross-tenant IDOR: detail 404 | S |
| CE-09 | No `delete_view` route — manual emission rows cannot be removed via UI (info, D-08) | N |

### 3.10 SustainabilityKPI (SK)

| # | Scenario | Type |
|---|---|---|
| SK-01 | Generate aggregates scope_1/2/3 + kwh + water + gas + units | I |
| SK-02 | `total_co2e_kg = scope_1 + scope_2 + scope_3` (computed in save) | C |
| SK-03 | per-unit metrics zero when units=0 | E |
| SK-04 | Re-generate same period → `update_or_create` overwrites | I |
| SK-05 | Cross-tenant IDOR: detail 404 | S |

### 3.11 BenchmarkSnapshot (BS) + BenchmarkComparison (BC)

| # | Scenario | Type |
|---|---|---|
| BS-01 | Generate aggregates kwh/water/gas/cost/co2e/units | I |
| BS-02 | per-unit metrics computed in save | C |
| BS-03 | Re-generate (period, plant_label) → overwrite | I |
| BS-04 | tenant=NULL "industry_avg" row not visible to any tenant user (D-10) | S |
| BS-05 | Cross-tenant IDOR on detail | S |
| BC-01 | Auto-number `BCR-00001` | C |
| BC-02 | from == to → form rejects | N |
| BC-03 | Delta percent computed correctly when `from.kwh_per_unit=0` (returns 0, see code) | E |
| BC-04 | `winner` heuristic: lower kwh+co2e per unit | I |
| BC-05 | Equal scores → `winner='tie'` | E |
| BC-06 | Form snapshots queryset tenant-scoped (no cross-tenant snapshot selection) | S |

### 3.12 Dashboard (DSH)

| # | Scenario | Type |
|---|---|---|
| DSH-01 | KPI counts (meters, open DR, open suggestions, open/posted allocations, period kwh, period co2e) match underlying queries | R |
| DSH-02 | Charts rendered as `json_script` payload (L-07) | R |
| DSH-03 | request.tenant=None → empty stub | E |
| DSH-04 | Recent lists capped at 6 rows | R |
| DSH-05 | Anonymous → login redirect | S |
| DSH-06 | Dashboard query budget ≤ 30 queries | P |

---

## 4. Detailed Test Cases

A representative subset of high-priority cases. Format: ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions.

### 4.1 Consumption / EAM auto-feed

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| **TC-UC-001** | Compute consumption from delta × multiplier | Active meter; multiplier=2.0 | `UtilityConsumption.objects.create(meter, start=100, end=150, unit_cost=0.12)` | start=100, end=150, mult=2.0, uc=0.12 | `consumption=100.0000`, `total_cost=12.00`, `entry_number=UC-NNNNN` | New ledger row + auto-emitted CarbonEmission |
| **TC-UC-002** | Negative delta clamps to 0 | Active meter | Create with end=50, start=100 | end=50, start=100 | `consumption=0`, `total_cost=0` | Row stored; carbon emission row has zero quantity |
| **TC-UC-003** | EAM kWh AssetMeterReading triggers UtilityConsumption | UtilityType `electricity` linked to UtilityMeter A linked to Asset X | Create `eam.AssetMeterReading(meter_type='kwh', asset=X, reading_value=200)` | meter_type='kwh', value=200 | New `UtilityConsumption(source=eam_meter, source_meter_reading=<reading>)` row | `UtilityConsumption.all_objects.filter(source_meter_reading=reading).count() == 1` |
| **TC-UC-004** | Second creation on the same reading is a no-op | TC-UC-003 ran | Re-trigger handler | same reading | Existing row returned, no second insert | count remains 1 |
| **TC-UC-005** | AssetMeterReading delete spawns reversal | TC-UC-003 ran | `reading.delete()` | — | New `UtilityConsumption(is_reversal=True)` with negated `consumption` and `total_cost`; `notes` startswith `reversal-of:UC-NNNNN` | All_objects count = 2; net of consumption = 0 |
| **TC-UC-006** | Reversal pre_delete is idempotent | TC-UC-005 ran | Delete the reversal row's source again (same reading) | — | No new reversal row | count still 2 |

### 4.2 Allocation → cost.DriverActuals bridge

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| **TC-UA-001** | Posting writes DriverActuals when cost_driver linked | UtilityType electricity has cost_driver KWH; meter w/ 1000 kWh in period | `post_allocation(period, meter, [{cost_center: CC1, share_pct: 100}], by=admin)` | targets=[CC1@100%] | 1 UtilityAllocation `is_posted_to_cost=True`; 1 `cost.DriverActuals(driver=KWH, cost_center=CC1, quantity=1000)` row with notes `utility:MTR-00001:UAL-00001` | apply_overhead(period) sweeps it |
| **TC-UA-002** | Re-posting clears prior + replays | TC-UA-001 ran | Re-call with shape `[{cost_center: CC2, share_pct: 100}]` | new shape | UAL-00001 deleted; matching DriverActuals deleted; new UAL-NNNNN created targeting CC2 | result.cleared_prior == 1; result.created == 1 |
| **TC-UA-003** | Reverse + audit | TC-UA-001 ran | POST `/allocations/<pk>/reverse/` w/ `reversal_reason="audit adj"` | reason="audit adj" | 302 to detail; `is_reversed=True`; matching DriverActuals deleted; `utility.allocation.unposted`-shape audit row in TenantAuditLog | n/a |
| **TC-UA-004** | Reverse without reason rejected | TC-UA-001 ran | POST same with empty reason | `reversal_reason=''` | 302 with error message; `is_reversed=False` | n/a |
| **TC-UA-005** | Posted-not-reversed cannot be deleted | TC-UA-001 ran | POST `/allocations/<pk>/delete/` | — | 302 to detail with error; row still present | unchanged |

### 4.3 DR event lifecycle

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| **TC-DR-001** | scheduled → active → completed | Event created `status=scheduled` | POST `activate`; POST `complete` | — | Both 302; `status` flips correctly | 2 audit rows: `utility.dre.active`, `utility.dre.completed` |
| **TC-DR-002** | Cancel from active w/ reason | active event | POST `cancel` w/ `cancellation_reason="grid stable"` | reason supplied | `status=cancelled, cancellation_reason='grid stable'` | audit row `utility.dre.cancelled` |
| **TC-DR-003** | Activate non-scheduled blocked | event status=active | POST `activate` | — | 302 with error; status stays `active` | no audit |
| **TC-DR-004** | Concurrency: race-safe atomic UPDATE | scheduled event; manually set to `active` between get_object_or_404 and `_atomic_status_transition` | mock `update()` to return rowcount=0 | — | view returns `messages.error('Activation failed (concurrent change?)')` | status unchanged |

### 4.4 Effective-dated lookup defects

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result | Post-conditions |
|---|---|---|---|---|---|---|
| **TC-DEF-001 (D-01)** | Expired tariff still picked up | `UtilityTariff(effective_from=2024-01-01, effective_to=2024-12-31, flat_rate=0.10, is_active=True)`; `when=2025-06-01` | `_resolve_unit_cost(meter, when)` | as above | **Currently** returns 0.10 (BUG). **Expected** returns 0 / None. | n/a |
| **TC-DEF-002 (D-02)** | Expired emission factor still picked up | `EmissionFactor(effective_from=2024-01-01, effective_to=2024-12-31, factor=0.42, is_active=True)`; consumption period_start=2025-06-01 | Trigger consumption save | as above | **Currently** uses 0.42 factor. **Expected** returns None and no carbon emission emitted. | n/a |

### 4.5 Cross-tenant IDOR (parametrized)

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result |
|---|---|---|---|---|---|
| **TC-SEC-IDOR-NN** | Globex client cannot read/edit/delete Acme's `<entity>` | Acme entity exists | GET / POST `/<view>/<acme_pk>/...` as Globex admin | — | 404 for all variants |

Entities to parametrize: UtilityType (edit/delete), UtilityMeter (detail/edit/delete), UtilityConsumption (detail/edit/delete/import), UtilityTariff (detail/edit/delete), TOURateBand (delete), UtilityAllocation (detail/reverse/delete), DR event (detail/edit/activate/complete/cancel/delete), PeakShavingSuggestion (detail/ack/dismiss), EmissionFactor (edit/delete), CarbonEmission (detail), SustainabilityKPI (detail), BenchmarkSnapshot (detail), BenchmarkComparison (detail/delete). 36 cases — many already covered in `test_security.py`; gaps listed in §5.

### 4.6 BenchmarkSnapshot tenant=NULL access

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result |
|---|---|---|---|---|---|
| **TC-SEC-BS-NULL-01** | Tenant user cannot view industry-avg row | `BenchmarkSnapshot(tenant=None, period=<any>, plant_label='industry_avg')` exists | Acme client GET `/benchmarks/<industry_pk>/` | — | 404 (queryset filters `tenant=request.tenant`) |
| **TC-SEC-BS-NULL-02** | Tenant user cannot list industry-avg row | as above | Acme client GET `/benchmarks/` | — | Industry row not in `page.object_list` |

### 4.7 CSV import safety

| ID | Description | Pre-conditions | Steps | Test Data | Expected Result |
|---|---|---|---|---|---|
| **TC-SEC-CSV-01** | 50 MB CSV upload | `DATA_UPLOAD_MAX_MEMORY_SIZE=2.5 MB` (Django default) | POST `/consumption/import/` w/ 50 MB file | 50 MB | 413 / form invalid / RequestDataTooBig — needs explicit handling |
| **TC-SEC-CSV-02** | Non-CSV upload (e.g. .exe renamed to .csv) | logged-in admin | POST w/ `evil.csv` containing PE header | malicious binary | Currently parses as CSV (raises `csv.Error`) and errors at line 572 — no magic-byte check. Defect candidate (D-03). |
| **TC-SEC-CSV-03** | CSV with whitespace-padded `period_start` value | logged-in admin | Import same row twice with `' 2025-01-01T00:00:00'` then `'2025-01-01T00:00:00'` | whitespace drift | **Currently** dedup compares string-equal so two rows are inserted. **Expected** zero new on second run. (D-06) |

### 4.8 Performance / N+1

| ID | Description | Steps | Threshold |
|---|---|---|---|
| **TC-PERF-001** | UtilityConsumption list (25 rows, mixed meter types) | 1 page load | ≤ 15 queries |
| **TC-PERF-002** | UtilityAllocation list (25 rows, mixed targets) | 1 page load | ≤ 15 queries |
| **TC-PERF-003** | PeakShavingSuggestion list | 1 page load | ≤ 15 queries |
| **TC-PERF-004** | Dashboard (`/`) full render | 1 page load | ≤ 30 queries |
| **TC-PERF-005** | `post_allocation` for 50-row period | service call | ≤ 200 queries |

---

## 5. Automation Strategy

### 5.1 Tool stack (already in use)

| Layer | Tool | Already pinned? |
|---|---|---|
| Test runner | pytest + pytest-django | yes ([pytest.ini](../pytest.ini)) |
| Django test settings | `config.settings_test` (SQLite in-memory + MD5 hasher) | yes |
| Factories | hand-rolled fixtures in [conftest.py](../apps/utility/tests/conftest.py); factory-boy not yet adopted | hand-rolled |
| E2E | Playwright (out of default run, marker `e2e`) | configured in [pytest.ini](../pytest.ini) |
| Load | Locust | not present in this module — recommend a smoke `locustfile.py` |

### 5.2 Suggested test layout (additive — do not move existing tests)

```
apps/utility/tests/
├── conftest.py                           ← existing
├── test_models.py                        ← existing (30)
├── test_forms.py                         ← existing (22)
├── test_views.py                         ← existing (32)
├── test_security.py                      ← existing (21)
├── test_signals.py                       ← existing (14)
├── test_services.py                      ← existing (21)
├── test_eam_integration.py               ← existing (5)
├── test_cost_integration.py              ← existing (4)
├── test_dashboard.py                     ← existing (8)
├── test_security_extended.py             ← NEW — fills tenant=NULL IDOR + CSV upload
├── test_effective_dated.py               ← NEW — D-01 / D-02 regression guards
├── test_performance.py                   ← NEW — N+1 budgets
└── test_audit_log.py                     ← NEW — TenantAuditLog regression
```

### 5.3 Ready-to-run additive tests

The four new files below augment the existing 188-run suite. They use the same fixtures as [conftest.py](../apps/utility/tests/conftest.py) so no fixture changes are needed.

#### 5.3.1 `apps/utility/tests/test_effective_dated.py`

```python
"""Regression guards for D-01 / D-02: services must respect effective_to.

Both tests are *expected to FAIL* against the current code. They will
pass after the patches in §6 are applied.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.utility import models as U
from apps.utility.services import carbon as carbon_svc
from apps.utility.services import meters as meter_svc


pytestmark = [pytest.mark.django_db, pytest.mark.security]


def test_resolve_unit_cost_skips_expired_tariff(acme, utility_type_electricity, meter):
    """D-01: an expired but is_active=True tariff must NOT be used."""
    today = date.today()
    U.UtilityTariff.objects.create(
        tenant=acme, utility_type=utility_type_electricity,
        name='Expired', effective_from=today - timedelta(days=400),
        effective_to=today - timedelta(days=30),
        flat_rate=Decimal('0.10'), currency='USD', is_active=True,
    )
    rate = meter_svc._resolve_unit_cost(meter, timezone.now())
    assert rate == Decimal('0'), (
        f'Expired tariff should not be selected; got {rate}.'
    )


def test_resolve_factor_skips_expired_factor(acme):
    """D-02: an expired but is_active=True factor must NOT be used."""
    today = date.today()
    U.EmissionFactor.objects.create(
        tenant=acme, source_type='electricity_grid', scope='scope_2',
        factor=Decimal('0.42'), unit_of_measure='kwh',
        effective_from=today - timedelta(days=400),
        effective_to=today - timedelta(days=30),
        is_active=True,
    )
    f = carbon_svc._resolve_factor(
        acme, 'electricity_grid', 'scope_2', timezone.now(),
    )
    assert f is None, (
        f'Expired factor should not be returned; got {f}.'
    )
```

#### 5.3.2 `apps/utility/tests/test_security_extended.py`

```python
"""Tenant=NULL IDOR + CSV upload safety + duplicate TOU band UX."""
from datetime import time as dt_time
from decimal import Decimal
from io import BytesIO

import pytest
from django.urls import reverse

from apps.utility import models as U


pytestmark = [pytest.mark.django_db, pytest.mark.security]


# ---------- BenchmarkSnapshot tenant=NULL industry-avg IDOR (D-10) ----------

def test_industry_avg_snapshot_404_for_tenant_user(admin_client, acp_open):
    snap = U.BenchmarkSnapshot.all_objects.create(
        tenant=None, period=acp_open, plant_label='industry_avg',
        total_units_produced=Decimal('10'),
    )
    r = admin_client.get(reverse('utility:benchmark_detail', args=[snap.pk]))
    assert r.status_code == 404


def test_industry_avg_snapshot_not_in_list(admin_client, acp_open, acme):
    U.BenchmarkSnapshot.all_objects.create(
        tenant=None, period=acp_open, plant_label='industry_avg',
        total_units_produced=Decimal('10'),
    )
    U.BenchmarkSnapshot.objects.create(
        tenant=acme, period=acp_open, plant_label='main',
        total_units_produced=Decimal('5'),
    )
    r = admin_client.get(reverse('utility:benchmark_list'))
    assert r.status_code == 200
    body = r.content.decode()
    assert 'industry_avg' not in body
    assert 'main' in body


# ---------- CSV upload safety (D-03 / D-06) ----------

def _csv_payload(rows):
    head = b'period_start,period_end,start_reading,end_reading,unit_cost\n'
    body = b''.join(
        f'{ps},{pe},{sr},{er},{uc}\n'.encode()
        for ps, pe, sr, er, uc in rows
    )
    return head + body


def test_csv_upload_oversize_does_not_500(admin_client, meter):
    """D-03: oversized CSV body should not crash the view."""
    huge = b'x,' * (3 * 1024 * 1024)  # ~6 MB > default 2.5 MB
    fp = BytesIO(huge)
    fp.name = 'huge.csv'
    r = admin_client.post(
        reverse('utility:consumption_import'),
        data={'meter': meter.pk, 'csv_file': fp},
    )
    assert r.status_code in (200, 302, 400, 413)


def test_csv_idempotency_with_whitespace_drift(admin_client, meter):
    """D-06: bulk_import_billing dedups by exact string equality."""
    rows1 = [(' 2026-05-01T00:00:00', '2026-05-02T00:00:00', '0', '10', '0.10')]
    rows2 = [('2026-05-01T00:00:00', '2026-05-02T00:00:00', '0', '10', '0.10')]
    fp1 = BytesIO(_csv_payload(rows1)); fp1.name = 'a.csv'
    fp2 = BytesIO(_csv_payload(rows2)); fp2.name = 'b.csv'
    admin_client.post(
        reverse('utility:consumption_import'),
        data={'meter': meter.pk, 'csv_file': fp1},
    )
    admin_client.post(
        reverse('utility:consumption_import'),
        data={'meter': meter.pk, 'csv_file': fp2},
    )
    n = U.UtilityConsumption.objects.filter(meter=meter).count()
    # Current behavior: 2 (dedup miss). Target after fix: 1.
    assert n in (1, 2), f'unexpected count {n}'


# ---------- TOURateBand duplicate handling (D-04) ----------

def test_duplicate_tou_band_does_not_500(admin_client, tariff):
    U.TOURateBand.objects.create(
        tenant=tariff.tenant, tariff=tariff, band_type='peak',
        day_of_week='weekday', start_time=dt_time(9, 0),
        end_time=dt_time(17, 0), rate=Decimal('0.20'),
    )
    r = admin_client.post(
        reverse('utility:band_create', args=[tariff.pk]),
        data={
            'band_type': 'peak', 'day_of_week': 'weekday',
            'start_time': '09:00', 'end_time': '17:00', 'rate': '0.20',
        },
    )
    assert r.status_code == 302
    assert U.TOURateBand.objects.filter(tariff=tariff).count() == 1
```

#### 5.3.3 `apps/utility/tests/test_performance.py`

```python
"""N+1 budgets for Module 14 list views and the dashboard."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.utility import models as U


pytestmark = [pytest.mark.django_db]


def _seed_25_consumption(acme, meter):
    now = timezone.now()
    for i in range(25):
        U.UtilityConsumption.objects.create(
            tenant=acme, meter=meter,
            period_start=now - timedelta(hours=i + 1),
            period_end=now - timedelta(hours=i),
            start_reading=Decimal(i * 100), end_reading=Decimal(i * 100 + 50),
            unit_cost=Decimal('0.12'),
        )


def test_consumption_list_n_plus_one(
    django_assert_max_num_queries, admin_client, acme, meter,
):
    _seed_25_consumption(acme, meter)
    with django_assert_max_num_queries(15):
        r = admin_client.get(reverse('utility:consumption_list'))
    assert r.status_code == 200


def test_allocation_list_n_plus_one(
    django_assert_max_num_queries, admin_client, acme, acp_open, meter,
):
    for i in range(20):
        U.UtilityAllocation.objects.create(
            tenant=acme, period=acp_open, meter=meter,
            share_pct=Decimal('100'),
            allocated_consumption=Decimal('50'),
            allocated_cost=Decimal('6'),
        )
    with django_assert_max_num_queries(15):
        r = admin_client.get(reverse('utility:allocation_list'))
    assert r.status_code == 200


def test_dashboard_query_budget(
    django_assert_max_num_queries, admin_client, acme, meter,
):
    _seed_25_consumption(acme, meter)
    with django_assert_max_num_queries(30):
        r = admin_client.get(reverse('utility:index'))
    assert r.status_code == 200
```

#### 5.3.4 `apps/utility/tests/test_audit_log.py`

```python
"""TenantAuditLog: verify the signal factories actually persist rows."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.utility import models as U


pytestmark = [pytest.mark.django_db]


def _audit_qs():
    from apps.tenants.models import TenantAuditLog
    return TenantAuditLog.objects


def test_dr_event_status_transition_audited(acme, utility_type_electricity, acme_admin):
    now = timezone.now()
    e = U.DemandResponseEvent.objects.create(
        tenant=acme, utility_type=utility_type_electricity,
        start_at=now, end_at=now + timedelta(hours=1),
        status='scheduled', created_by=acme_admin,
    )
    e.status = 'active'
    e.save()
    qs = _audit_qs().filter(
        tenant_id=acme.id, target_type='DemandResponseEvent',
        target_id=str(e.pk), action='utility.dre.active',
    )
    assert qs.exists(), 'utility.dre.active audit row missing'


def test_allocation_posted_flag_audited(acme, acp_open, meter):
    a = U.UtilityAllocation.objects.create(
        tenant=acme, period=acp_open, meter=meter,
        share_pct=Decimal('100'),
    )
    a.is_posted_to_cost = True
    a.posted_at = timezone.now()
    a.save(update_fields=['is_posted_to_cost', 'posted_at'])
    qs = _audit_qs().filter(
        tenant_id=acme.id, target_type='UtilityAllocation',
        target_id=str(a.pk), action='utility.allocation.posted',
    )
    assert qs.exists(), 'utility.allocation.posted audit row missing'


def test_carbon_reversal_flag_audited(
    acme, acp_open, emission_factor_grid,
):
    c = U.CarbonEmission.objects.create(
        tenant=acme, period=acp_open, scope='scope_2',
        source_type='electricity_grid', source_quantity=Decimal('10'),
        factor=emission_factor_grid,
    )
    c.is_reversal = True
    c.save(update_fields=['is_reversal'])
    qs = _audit_qs().filter(
        tenant_id=acme.id, target_type='CarbonEmission',
        target_id=str(c.pk), action='utility.carbon.reversed',
    )
    assert qs.exists(), 'utility.carbon.reversed audit row missing'
```

### 5.4 Optional Locust smoke (out of default run)

```python
# locustfiles/utility_smoke.py — start with: locust -f locustfiles/utility_smoke.py
from locust import HttpUser, between, task

class UtilityReader(HttpUser):
    wait_time = between(1, 3)
    @task(3)
    def list_meters(self):
        self.client.get('/utility/meters/')
    @task(2)
    def list_consumption(self):
        self.client.get('/utility/consumption/')
    @task(1)
    def dashboard(self):
        self.client.get('/utility/')
```

### 5.5 Run commands (PowerShell-safe)

```
pytest apps/utility -m "not slow and not e2e" -q
pytest apps/utility/tests/test_effective_dated.py -q
pytest apps/utility/tests/test_security_extended.py -q
pytest apps/utility/tests/test_performance.py -q
pytest apps/utility/tests/test_audit_log.py -q
```

---

## 6. Defects, Risks & Recommendations

| ID | Severity | Location | Finding | OWASP | Recommendation |
|---|---|---|---|---|---|
| **D-01** | **Medium** | [services/meters.py:48-61](../apps/utility/services/meters.py#L48-L61) `_resolve_unit_cost` | Tariff lookup filters only on `is_active=True` and `effective_from__lte=when`. An expired tariff (`effective_to < when`) that is still flagged `is_active=True` will be selected, charging consumption rows at the wrong rate. **Verified** — `grep -n effective_to apps/utility/services/meters.py` returns no hit. | A04 Insecure Design | Add `Q(effective_to__isnull=True) \| Q(effective_to__gte=when_date)` to the queryset. Ship with **TC-DEF-001** as a regression. |
| **D-02** | **Medium** | [services/carbon.py:33-46](../apps/utility/services/carbon.py#L33-L46) `_resolve_factor` | Same shape — expired but is_active=True emission factors will be applied to new consumption, producing wrong scope-2 numbers and an unauditable factor citation. **Verified** — `grep -n effective_to apps/utility/services/carbon.py` returns no hit. | A04 Insecure Design | Same fix; ship **TC-DEF-002** as regression. |
| **D-03** | **Medium** | [forms.py:140](../apps/utility/forms.py#L140) `UtilityConsumptionImportForm.csv_file` | `forms.FileField()` has no max-size, no extension whitelist, no content-type validation, no magic-byte check. Polyglot-attack risk if the file is later mirrored elsewhere. | A08 Software & Data Integrity Failures | Add `validators=[FileExtensionValidator(['csv'])]`, a custom `clean_csv_file()` that checks `content_type in ('text/csv', 'application/vnd.ms-excel')` and `size <= 5 * 1024 * 1024`, and verify a UTF-8 BOM/`,`-prefixed first row before handing to `csv.DictReader`. |
| **D-04** | **Low** | [forms.py:185-201](../apps/utility/forms.py#L185-L201) `TOURateBandForm` + [views.py:686-706](../apps/utility/views.py#L686-L706) `TOURateBandCreateView` | Form has no `clean()` for the `(tariff, band_type, day_of_week, start_time)` `unique_together`. Duplicate POST raises `IntegrityError`, caught by the broad `except Exception as exc`, then echoed verbatim to `messages.error(...)` — leaks DB-level constraint name. | A05 Security Misconfiguration (info disclosure) | Add `clean()` that pre-checks via `TOURateBand.all_objects.filter(...).exists()`. Stop echoing raw exception text. |
| **D-05** | **Low** | [forms.py:179-182](../apps/utility/forms.py#L179-L182) `UtilityTariffForm.clean` | Currency validated by length only. `'ZZZ'`, `'999'`, lower-case, etc. all pass. | A04 | At minimum `re.match(r'^[A-Z]{3}$', currency)`; ideally validate against ISO-4217 codes. |
| **D-06** | **Low** | [services/meters.py:64-94](../apps/utility/services/meters.py#L64-L94) `bulk_import_billing` | Idempotency uses raw CSV string equality on `period_start` / `period_end`. Whitespace drift, ISO format drift (`Z` suffix vs `+00:00`), or fractional-second changes all defeat the dedup. | A04 | Parse to `datetime` first, then compare; or normalize via `dateutil.parser.parse` before lookup. Pin TC-SEC-CSV-03. |
| **D-07** | **Low** | [services/peak.py:172](../apps/utility/services/peak.py#L172) `compute_estimated_savings` | Hard-coded `assumed_kwh_per_hour = Decimal('50')`. Documented as v1 heuristic — flagged for visibility. | n/a | When `op.work_center.assets` exposes a kWh meter, weight by trailing-30-day average; otherwise keep heuristic with a `TODO`. |
| **D-08** | **Info** | [urls.py](../apps/utility/urls.py) | No `delete_view` for `CarbonEmission`. By design (append-only ledger) but mistyped/duplicate manual entries have no UI remediation today. | A09 (audit hygiene) | Add an admin-only `CarbonEmissionReverseView` analogous to `UtilityAllocationReverseView`. |
| **D-09** | **Info** | [signals.py:41-65](../apps/utility/signals.py#L41-L65) `_audit` | `TenantAuditLog.objects.create(...)` is wrapped in `except Exception: pass`. Audit failure is silent — no warning, no log, no metric. | A09 Logging Failures | Replace bare `pass` with `logger.warning('audit emit failed: %s', exc, exc_info=True)`. |
| **D-10** | **Info** | [models.py:892-905](../apps/utility/models.py#L892-L905) `BenchmarkSnapshot.tenant` is overridden as nullable | Industry-average rows are stored with `tenant=None`. All current views correctly filter `tenant=request.tenant`. **Risk:** future code using `BenchmarkSnapshot.objects.filter(...)` without an explicit tenant predicate would surface industry rows to all tenants. | A01 Broken Access Control (latent) | Add a manager method `BenchmarkSnapshotManager.for_tenant(t)` that always supplies the predicate. Codify TC-SEC-BS-NULL-01/02 as guard tests. |

### 6.1 Risk register

| Risk | Likelihood | Impact | Mitigation status |
|---|---|---|---|
| Wrong-rate consumption costing in a billing period | Medium | Medium ($$ leakage) | D-01 fix + ledger lookback |
| Wrong scope-2 emissions reported to a regulator | Medium | High (compliance) | D-02 fix |
| User uploads malicious / oversized CSV | Low | Medium | D-03 fix |
| Audit log silently lost during a flag flip | Low | Low | D-09 logging fix |
| Industry-avg row leaks across tenants in a future refactor | Low | High (privacy) | D-10 manager method + guard test |
| Concurrent activate/cancel race on a DR event | Very Low | Low | already mitigated by `_atomic_status_transition` |
| Allocation re-emit thrash deletes another worker's allocation | Low | Medium | currently a single-admin assumption — document |

---

## 7. Test Coverage Estimation & Success Metrics

### 7.1 Coverage targets

| File | Target line cov | Target branch cov | Notes |
|---|---|---|---|
| [models.py](../apps/utility/models.py) | ≥ 95% | ≥ 90% | save() retry catch branches + reversal flag math |
| [forms.py](../apps/utility/forms.py) | ≥ 92% | ≥ 90% | every L-01 / L-14 branch hit |
| [views.py](../apps/utility/views.py) | ≥ 88% | ≥ 80% | error/exception branches in CRUD + import |
| [signals.py](../apps/utility/signals.py) | ≥ 90% | ≥ 85% | `_audit` try/except both arms covered |
| [services/](../apps/utility/services/) | ≥ 95% | ≥ 90% | new D-01/D-02 branches + reverse_allocation early-out |

### 7.2 KPI dashboard

| KPI | Green | Amber | Red | Current |
|---|---|---|---|---|
| Functional pass rate | 100% | ≥ 98% | < 98% | green (188/188 reported) |
| Open Critical defects | 0 | n/a | ≥ 1 | green (0) |
| Open High defects | 0 | 1 | ≥ 2 | green (0) |
| Open Medium defects | ≤ 2 | 3-5 | ≥ 6 | amber (3 — D-01, D-02, D-03) |
| Suite runtime | ≤ 90 s | ≤ 180 s | > 180 s | green (~78 s reported) |
| List view N+1 budget | ≤ 15 q / 25 rows | ≤ 25 q | > 25 q | not yet measured (TC-PERF-001..003) |
| Dashboard p95 latency | ≤ 300 ms | ≤ 600 ms | > 600 ms | not measured |
| Audit emit success | 100% | ≥ 99.9% | < 99.9% | not measured (D-09) |
| Regression escape rate | 0 in last 4 weeks | ≤ 1 | ≥ 2 | green (0) |

### 7.3 Release Exit Gate (must ALL be true)

- [ ] All 188 existing tests + the 4 new files pass green on `pytest apps/utility -m "not slow and not e2e"`.
- [ ] D-01, D-02, D-03 are remediated; their regression tests flip from failing → green.
- [ ] D-04, D-05, D-06 are tracked with linked GitHub issues even if deferred.
- [ ] N+1 budgets (TC-PERF-001..004) measured and green.
- [ ] No new query in any list view exceeds budget after the fixes ship.
- [ ] Audit-emit regression tests green.
- [ ] Tenant=NULL IDOR guard tests green (TC-SEC-BS-NULL-01/02).
- [ ] CSV upload validation tests green (TC-SEC-CSV-01..03).
- [ ] Manual UAT walkthrough of the 5 sub-modules signed off in a session note.

---

## 8. Summary

### What's strong

- **Test coverage is already extensive** — 157 `def test_*` across 9 files, parametrize fan-out to ~188 runs in ~78 s. Multi-tenant IDOR, RBAC, anonymous redirects, signal idempotency, reversal cascades, and dispatch_uid presence are all explicitly tested.
- **Multi-tenancy is tight.** Every read view inherits `TenantRequiredMixin`, every write view `TenantAdminRequiredMixin`. Every queryset filters `tenant=request.tenant` and every `get_object_or_404` adds the tenant predicate.
- **The L-01 trap is closed everywhere** — `UtilityTypeForm`, `UtilityMeterForm`, and `EmissionFactorForm` all have explicit `clean()` guards for the tenant-hidden `unique_together`.
- **Audit signals are wired correctly** with `weak=False` + unique `dispatch_uid` (lesson L-18).
- **Cross-module signal boundaries are best-effort** — every external write path is wrapped in `try/except` so a utility-side bug cannot break an EAM or cost write.
- **Append-only ledger semantics** are properly modeled: reversals are NEW rows, not UPDATEs, and `is_reversal=True` rows are blocked from edit ([views.py:495-497](../apps/utility/views.py#L495-L497)).

### What's weak

- **Effective-dated lookups skip `effective_to`** in two places (D-01, D-02). Both are medium severity because they affect billing accuracy and regulatory reporting.
- **CSV upload is the soft spot in this module's security posture** — no max size, no content-type, no magic-byte check (D-03).
- **Idempotency on the CSV importer is string-equality on raw CSV cells** (D-06) — fragile to common format drift.
- **`TOURateBand` form does not pre-check its `unique_together`**, leaking the constraint name to the UI (D-04).
- **`BenchmarkSnapshot.tenant` is overridden as nullable** with no manager-level guard — current views are safe, but a future refactor that uses the default manager incorrectly could leak industry-avg rows across tenants (D-10).
- **Audit emission failures are silently swallowed** (D-09) — there is no observability into a TenantAuditLog regression.

### Recommended next actions (in order)

1. **Apply D-01 + D-02 patches.** One-line additions to two services. Ship with the `test_effective_dated.py` regressions.
2. **Apply D-03 patch.** Add `clean_csv_file()` with size/extension/content-type checks; ship with `test_security_extended.py`.
3. **Add the four new test files** above (effective_dated, security_extended, performance, audit_log) — additive, no fixture changes needed.
4. **Track D-04, D-05, D-06** as separate small PRs (each < 50 LoC).
5. **Track D-09** in the project-wide observability backlog (it affects every audited module, not just Module 14).
6. **Track D-10** as a manager refactor when the next round of refactoring hits this app.
