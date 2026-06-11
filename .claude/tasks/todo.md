# Task: Make the header Search work (global omni-search)

**Created:** 2026-06-12
**Plan:** `C:\Users\user\.claude\plans\wondrous-mapping-valiant.md`

## Problem
The header search box (`templates/partials/topbar.html`) is decorative — a bare
`<input type="search">` with no `<form>`, no `name`, no JS handler, and no global-search
view/URL to submit to. Typing + Enter does nothing.

## Plan / Checklist
- [x] `apps/core/search.py` — `SearchSpec` dataclass + `SEARCH_REGISTRY` (17 tenant-scoped entities)
- [x] `apps/core/views.py` — add `GlobalSearchView` (LoginRequiredMixin, tenant-scoped, defensive per-spec try/except)
- [x] `apps/core/urls.py` — `path('search/', GlobalSearchView.as_view(), name='search')`
- [x] `config/urls.py` — mount `apps.core.urls` at root (route `/search/`, name `core:search`)
- [x] `templates/core/search_results.html` — grouped results page (mirror dms/search_results.html)
- [x] `templates/partials/topbar.html` — wrap input in a real GET `<form>` → `core:search`
- [x] `README.md` — add `/search/` to Routes table + note global search
- [x] Verify: `manage.py check`, dev server, live search as tenant admin, run test suite

## Review

**Status: implemented & verified (2026-06-12).**

- **Root cause:** the topbar `<input type="search">` was decorative — no `<form>`, no `name`,
  no JS, and no global-search view/URL existed. Typing + Enter was a no-op.
- **Fix:** a declarative registry (`apps/core/search.py`, 17 specs) + one generic
  `GlobalSearchView` that runs a tenant-scoped `icontains` OR per spec and groups hits by type,
  each linking to its detail page. Topbar box is now a real `GET` form → `core:search`.
- **Design choices:** `LoginRequiredMixin` (not tenant mixin) so a no-tenant superuser gets an
  empty set, not a redirect; each spec's query + `reverse()` is wrapped in try/except so one bad
  spec can never 500 the page; nested/child detail routes (change orders, amendments, bids,
  price-change) deliberately excluded — they can't reverse from a single pk.
- **Verification:**
  - `manage.py check` clean.
  - Registry smoke test: all 17 models resolve, every search/number/title/order field exists,
    every model has a `tenant` FK, every detail URL reverses with a single pk. `core:search` → `/search/`.
  - Functional (test client, `admin_acme`): real PR number → 1 hit w/ correct `/requisitions/<pk>/`
    link; blank → prompt state; gibberish → empty state; no-tenant superuser → 200 + 0 results.
  - Live browser (port 8089, fresh server): logged in, header form posts to `/search/`; `?q=Acme`
    rendered 14 groups / "64 results", capped groups show "6+", input pre-filled; clicked result →
    real `REQ-ACME-00008` detail page; 0 console errors, 0 server errors.
  - Full pytest: **1467 passed in 163s, 0 failures** — no regressions.
