# List-Table Page Revamp — App-Wide (77 templates)

**Created:** 2026-06-10 · **Completed:** 2026-06-11
**Plan:** `C:\Users\user\.claude\plans\squishy-mixing-eagle.md`

Frontend-only revamp of every list page: canonical markup (header / filter card / table card /
actions / empty state / pagination), new CSS section (design tokens, logical properties, sticky
thead, sort indicators, empty states, pagination polish), new JS (click-to-sort current page,
filter auto-submit + debounced search + clear link). **No backend/view changes.**

## Phase 0 — Foundation
- [x] `static/css/style.css` — appended `/* ===== List pages ===== */` section (+ defined the previously-missing `.badge-soft-dark`, `.filter-card`; dark-theme badge text colors)
- [x] `static/js/app.js` — appended self-contained IIFE: `initListTable` (sort) + `initFilterForm` (autosubmit/clear)
- [x] `templates/partials/_empty_state.html` — new param-only include
- [x] `templates/partials/_pagination.html` — rewritten: `page_obj.has_other_pages` guard, request.GET links, results count, window current±2 + first/last + ellipses

## Phase 1 — Reference template
- [x] `templates/requisitions/requisitions/list.html` — browser-verified (numeric sort, aria-sort, sticky thead, autosubmit, clear link, filter round-trip, empty state, dark theme, 0 console errors)

## Phase 2 — Fan out (76 templates, workflow agents + adversarial verify)
- [x] Batch A — CBV family (14)
- [x] Batch B — no-pagination family (10) — views confirmed unpaginated, no dead include added
- [x] Batch C — querystring P2P (14) — inline pagination swapped to shared include
- [x] Batch D — querystring analytics/ops (20)
- [x] Batch E — sysadmin (10) + deleted `templates/sysadmin/_pagination.html` (zero refs left)
- [x] Batch F — vendor_portal markup/CSS only (8) — NO data-sortable / data-filter-autosubmit (its base.html doesn't load app.js)

## Phase 3 — Docs
- [x] `README.md` — list-page pattern paragraph in Dashboard Features; partials in Project Structure
- [x] Review below

## Review

**Status: complete & verified (2026-06-11).**

- **Coverage:** 77/77 list templates migrated; 2 shared partials (pagination rewritten in place, empty state new); `sysadmin/_pagination.html` deleted.
- **Deterministic invariant sweep** (`temp/check_invariants.py`, HEAD vs working tree, all 77 files): no lost `{% url %}` names, identical form-control `name=` sets, identical `request.GET.*` reference sets, `|stringformat:"d"` counts unchanged, csrf counts not reduced, balanced if/for/block/with, JS hooks present (and absent on vendor_portal), zero `sysadmin/_pagination` references. **3 accepted deviations**, all "empty-state secondary action folded into message" (component supports one CTA): rfx events (template link — header button retained), vendors (onboarding-queue link — header path retained), compliance fraud alerts (duplicate Run-scan POST form — identical header form retained, message points to it).
- **Compile sweep:** all 360 project templates compile.
- **Pagination partial unit-tested** with a real Paginator + RequestFactory: GET-param preservation (q/status survive paging, no `page` leak), results label, ±2 windowing/ellipses, silent when absent/single-page.
- **Full pytest:** 1467 passed (twice: after Phase 0 and after full fan-out).
- **Live browser (admin_acme):** requisitions (sort proven numeric, sticky thead, autosubmit, clear-link reveal, filter round-trip `status=approved`, empty state, dark theme badge contrast, 0 console errors); inventory movements (date sort, pagination correctly silent <20 rows); supplier-performance feedback ("Showing 1–20 of 21", page-2 link); portal notifications page 6/6 ("Showing 101–113 of 113", `1 … 4 5 6` window clipping). Spot-rendered via test client: inventory stock, vendors, contracts, plans (card grid intact), sysadmin currencies, invoicing, approvals, rfx — all 200 + canonical markers.
- **Note:** first fan-out run hit the session token limit mid-flight (35/76 done); resumed with `resumeFromRunId` — cached prefix + re-run of the rest. 3 agents had written files but died before reporting (po/voucher/terms); po_list needed only its pagination-include swap finished by hand.

## Follow-ups (out of scope, recorded)
- Add `Paginator` to the ~20 unpaginated list views (vendors ×4, sourcing ×2, rfx ×3, catalog punchout/upload ×3, invoicing terms, compliance fraud rules, sysadmin sequences, vendor_portal ×8 as needed)
- vendor_portal theming decision (app.js not loaded there — sort/autosubmit deliberately absent)
- Batch G later: list-like non-`list` templates (compliance/audit_log, budget/check_log, dms/policy_library, spend_analytics category drilldowns, approvals history)
