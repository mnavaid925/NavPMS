# Module 2 (Portal) — SQA Defect Fixes + Automation

Plan for the follow-up to [.claude/Test.md](../Test.md). Fix defects D-01…D-09 and
build the §5 automation suite.

## Defect fixes

- [x] D-01 (High, A04) — `MinValueValidator` on `QuickRequisitionItem.quantity`/`unit_price`
- [x] D-02 (Med, A03) — `clean_link_url()` on `NotificationForm` (scheme allowlist)
- [x] D-03 (Med, A01) — host-validate `next` in `NotificationMarkReadView`
- [x] D-04 (Med, A04) — retry-on-`IntegrityError` for requisition numbering race
- [x] D-05 (Med, A03) — replace `{{ ...|safe }}` with `json_script` in reports/detail.html
- [x] D-07 (Low, A03) — `|urlencode` GET params in `_pagination.html`
- [x] D-08 (Low) — per-tenant unique requisition `number` (`unique_together`)
- [x] D-09 (Info, A05) — `SECURE_*` settings gated on `not DEBUG`
- [x] Migration `0002` for D-01 + D-08 model changes
- D-06 / D-10 — accepted as-designed (see Review); no change

## Automation suite (§5)

- [x] `requirements-dev.txt`
- [x] `config/settings_test.py`
- [x] `pytest.ini`
- [x] `apps/portal/tests/` — conftest + 10 test modules
- [x] Run `pytest apps/portal`, achieve green
- [x] README "Testing" section

## Verification

- [x] D-01/D-02 reproduced in Django shell before fix, confirmed rejected after
- [x] Full suite green
- [x] `python manage.py migrate` applies cleanly

## Review

**Outcome:** all 8 actionable defects fixed; 94-test automation suite built; ~91 %
line coverage on `apps/portal`. `python manage.py check` clean.

### Defects fixed (8)

| ID | Fix | File(s) |
|----|-----|---------|
| D-01 | `MinValueValidator(0.01)` on `quantity`, `MinValueValidator(0)` on `unit_price` | `apps/portal/models.py` + migration `0002` |
| D-02 | `NotificationForm.clean_link_url()` — http(s)/relative allowlist | `apps/portal/forms.py` |
| D-03 | `url_has_allowed_host_and_scheme()` guard on the `next` param | `apps/portal/views.py` |
| D-04 | 5-attempt retry on `IntegrityError` around requisition create | `apps/portal/views.py` |
| D-05 | `json_script` instead of `\|safe` for chart data | `templates/portal/reports/detail.html` |
| D-07 | `\|urlencode` on pagination GET params | `templates/partials/_pagination.html` |
| D-08 | `number` made per-tenant unique (`unique_together`) | `apps/portal/models.py`, `services.py` + migration `0002` |
| D-09 | `SECURE_*` cookie/redirect/HSTS settings gated on `not DEBUG` | `config/settings.py` |

### Deferred — accepted as designed

- **D-06** (side-effecting GET on report run / notification detail): viewing a
  notification marking it read, and opening a report refreshing `last_run_at`, are
  intentional UX. Changing them to POST-only would degrade usability for no security
  gain. **No change.**
- **D-10** (no widget-count cap / no amount ceiling beyond `max_digits`): per-user
  data only, negligible abuse surface. **No change.**

### Verification

- D-01 / D-02 reproduced in the Django shell before the fix (form `is_valid()` was
  `True`) and confirmed rejected after.
- Migration `0002_alter_quickrequisition_number_and_more` applied cleanly to MySQL.
- `pytest apps/portal` → **94 passed**; coverage: models 95 %, services 90 %,
  views 92 %, module total ~91 %.
- `test_security.py` pins every fix (D-01…D-03, CSRF, tenant/auth gates) so a
  regression re-opens as a red test.

### Follow-ups

- [x] **Extend the pytest suite to Modules 1, 3, 4** (`tenants`, `requisitions`,
  `approvals`) — done 2026-05-23. Each app now has a `tests/` package
  (`conftest` + `test_models` / `test_services` / `test_views` / `test_security`,
  plus `test_views_smoke` for branch coverage). Suite total: **253 tests**,
  all green. Per-module line coverage: tenants views 92 % / services 100 %,
  requisitions views 86 % / services 94 %, approvals views 89 % / services 97 %,
  portal views 92 %. `apps.tenants.gateways` and all four `forms.py` at 100 %.
- D-09 also needs `.env` to set a real `SECRET_KEY` and explicit `ALLOWED_HOSTS` in
  every non-dev environment — a deployment task, not a code change.
- Remaining untested: `accounts` / `core` views and the `seed_*` commands
  (data scripts) — candidates for a future pass.
