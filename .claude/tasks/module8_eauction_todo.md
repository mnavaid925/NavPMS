# Module 8 — E-Auction Management

**Created:** 2026-05-29
**Status:** COMPLETE & VERIFIED (2026-05-29). See Review section at the bottom.
**Scope:** New Django app `apps/auctions/` implementing the 5 PMS sub-modules of Module 8
(PMS.md `### 7. E-Auction Management`). Buyer-side surface at `/auctions/`; vendor-side live
bidding integrated into the existing `/vendor-portal/` namespace (consistent with Modules 6 & 7).

## Sub-module → implementation

| Sub-module (PMS spec) | Implementation |
|------------------------|----------------|
| **Auction Setup & Configuration** | `Auction` model holds reverse-auction parameters: `starting_price` (ceiling), `reserve_price` (hidden floor), `decrement_type` (amount/percent) + `decrement_value`, `start_at`/`end_at` window, `anti_snipe_seconds` + `anti_snipe_extension_seconds` + `max_extensions`, `rank_visibility`. `AuctionLot` rows describe the basket (descriptive line items). Full CRUD + publish validation. |
| **Live Bidding Interface** | Vendor portal route `/vendor-portal/auctions/<id>/bidding/` — a live screen with a client-side countdown, the current leading price, the vendor's own rank, and a place-bid form. Bids POST to a JSON endpoint; the screen **AJAX-polls** a JSON state endpoint every ~3s (vanilla `fetch()`, no websockets). `place_bid()` service validates the lowering + decrement + ceiling rules atomically. |
| **Bid Extension & Rule Enforcement** | Anti-snipe is enforced **server-side** inside `place_bid()`: if a valid bid lands within `anti_snipe_seconds` of `end_at` (and `extension_count < max_extensions`), `end_at` is pushed out by `anti_snipe_extension_seconds`. The decrement rule (each new global-best bid must beat the current best by the configured amount/percent) and the ceiling rule (≤ `starting_price`) are enforced in the same atomic transaction. |
| **Auction Monitoring Console** | Buyer-side `/auctions/<id>/console/` — a live leaderboard (vendor, current bid, rank, last-bid time), participation counters, time remaining, and a price-drop curve. Polls a buyer JSON endpoint every ~3s. Buyer sees everything; vendors see a blind view (own rank + leading price only) per `rank_visibility`. |
| **Post-Auction Results** | `/auctions/<id>/results/` — final ranking table, savings (starting/estimated vs winning bid, $ and %), full bid timeline (from the append-only `AuctionBid` ledger), and the **award decision** action (`finalize_auction`). Per-auction + tenant-wide analytics dashboards. |

## Why a new app (not folded into Sourcing)

Module 6 (Sourcing) is a **sealed, one-bid-per-vendor** tender scored against weighted criteria.
Module 8 (E-Auction) is a **live, time-bound, many-bids-per-vendor reverse auction** won on the
lowest valid price with real-time rank feedback. The data model differs fundamentally (an
append-only bid *ledger* + denormalised live standing, vs one Bid row). Same actors and portal
shell, separate surface — exactly the Sourcing/RFx split precedent.

## Key architectural decisions (CONFIRM THESE)

1. **Realtime = AJAX polling, no new dependencies.** The repo has no celery/channels/websockets
   and a firm no-new-deps posture. The live console + bidding screen use vanilla `fetch()` polling
   a `JsonResponse` endpoint every ~3s, with a client-side countdown driven by a server-supplied
   `end_at` ISO timestamp (re-synced each poll so the server stays authoritative). This is the
   **first** client-side realtime code in the app (no existing precedent) → new file `static/js/auction.js`.
2. **Total-price reverse auction** (recommended). A vendor's bid is a single declining **total**;
   `AuctionLot` rows are descriptive (what's being bought), not separately bid. Multi-lot
   per-line live bidding is a documented **stretch** (much more UI/logic). 
3. **Append-only `AuctionBid` ledger** + denormalised standing on `AuctionParticipant`
   (`current_bid_amount`, `current_rank`, `bid_count`, `last_bid_at`). This ledger *is* the
   activity feed and the audit trail — no separate event-feed model.
4. **Blind auction by default** (`rank_visibility='rank_and_leading'`): vendors see their own rank
   + the current leading price, never competitor identities. Buyer console sees all. Configurable.
5. **Lazy clock transitions (no celery).** `scheduled → live` and `live → closed` happen on access
   (console load / poll / place_bid) once the clock passes `start_at`/`end_at` — mirrors the Module 4
   approval-inbox lazy sweep. Plus a cron-friendly `run_auction_clock` command (counterpart to
   `run_escalations`) to close auctions even when nobody is looking.
6. **Concurrency-safe bidding:** `place_bid()` uses `select_for_update()` on the auction row inside
   `@transaction.atomic` to serialise simultaneous bids (prevents two vendors both "beating" the
   same best price).
7. **No separate award model** — the winner (lowest valid bid, buyer-overridable for compliance) is
   denormalised onto `Auction` (`awarded_vendor/amount/at`). Simpler than Sourcing's recommend→finalize.
8. **Proxy / auto-bidding deferred** (vendor sets a floor; system auto-bids the min decrement to hold
   the lead) — classic e-auction feature, marked **stretch**.

## Models (`apps/auctions/models.py`) — all inherit `(TenantAwareModel, TimeStampedModel)`

### Constants
- `AUCTION_TYPE_CHOICES`: `reverse` (default), `forward` (rare in procurement; field present for extension)
- `AUCTION_STATUS_CHOICES`: `draft → scheduled → live → closed → awarded`, plus `cancelled`
  - `AUCTION_EDITABLE_STATUSES = ('draft',)`
  - `AUCTION_CANCELLABLE_STATUSES = ('draft','scheduled','live')`
- `DECREMENT_TYPE_CHOICES`: `amount`, `percent`
- `RANK_VISIBILITY_CHOICES`: `rank_and_leading` (default, blind), `rank_only`, `full`
- `PARTICIPANT_STATUS_CHOICES`: `invited → accepted / declined`, then `won / lost / withdrawn`
- `BID_SOURCE_CHOICES`: `portal` (vendor), `manual` (buyer-entered on behalf), `proxy` (stretch)

### 1. Auction
`auction_number` (`AUC-<SLUG>-NNNNN`, unique per tenant), `title`, `description`,
`auction_type` (default `reverse`), `category` FK→`vendors.VendorCategory` (null),
`currency` (CHAR3 `USD`), `starting_price` (Decimal 14,2, ceiling), `reserve_price`
(Decimal 14,2, null — hidden floor), `decrement_type` (default `amount`),
`decrement_value` (Decimal 14,2, `MinValueValidator(0)`), `start_at`/`end_at` (DateTime, null
until scheduled), `anti_snipe_seconds` (PositiveInt default 120), `anti_snipe_extension_seconds`
(PositiveInt default 120), `max_extensions` (PositiveInt default 10), `extension_count`
(PositiveInt default 0), `rank_visibility` (default `rank_and_leading`),
`terms_and_conditions` (Text), `requisition` FK (null, `SET_NULL`),
`sourcing_event` FK→`sourcing.SourcingEvent` (null — optional hand-off provenance, **stretch**),
`status` (default `draft`), `created_by` FK→User, denormalised award
(`awarded_vendor` FK null, `awarded_amount` Decimal, `awarded_at`, `award_notes`),
`cancelled_reason/at/by`.
- `unique_together=[('tenant','auction_number')]`, `ordering=['-created_at']`,
  indexes `(tenant,status)`, `(tenant,auction_type)`.
- Properties: `is_editable`, `is_live` (status=='live'), `can_cancel`, `is_finished`
  (status in closed/awarded/cancelled), `seconds_remaining` (end_at − now, ≥0),
  `effective_decrement(current_best)` (resolve amount vs percent → absolute), `required_next_max`
  (the highest amount a new bid may be = current_best − decrement, or starting_price if no bids),
  `total_budget` (Σ lot est. value, fallback starting_price).

### 2. AuctionLot  *(descriptive basket line)*
`auction` FK (`related_name='lots'`), `lot_no` (PositiveInt), `title`/`item_description`
(Char 255), `uom` (default `EA`), `quantity` (Decimal 14,3, default 1, MinValue 0),
`est_unit_price` (Decimal 14,2, MinValue 0), `account_code` FK→`requisitions.AccountCode` (null),
`notes`.
- `unique_together=[('auction','lot_no')]`, `ordering=['lot_no','id']`.
- Property `estimated_line_total = quantity * est_unit_price`.

### 3. AuctionParticipant  *(invited vendor + denormalised live standing)*
`auction` FK (`related_name='participants'`), `vendor` FK→`vendors.Vendor`
(`related_name='auction_participations'`), `status` (default `invited`),
`invited_at`, `invited_by` FK→User, `responded_at` (null),
`current_bid_amount` (Decimal 14,2, null — latest/best bid), `current_rank` (PositiveInt null,
1 = lowest/leading), `bid_count` (PositiveInt default 0), `last_bid_at` (null),
`is_winner` (bool default False), `notes`.
- `unique_together=[('auction','vendor')]`, `ordering=['current_rank','-current_bid_amount']`,
  index `(tenant,vendor,status)`.

### 4. AuctionBid  *(append-only ledger — one row per placement)*
`auction` FK (`related_name='bids'`), `participant` FK (`related_name='bids'`),
`vendor` FK→`vendors.Vendor` (denorm for fast filter), `amount` (Decimal 14,2, MinValue 0),
`placed_at` (auto_now_add), `placed_by` FK→User (vendor portal user), `source` (default `portal`),
`rank_at_placement` (PositiveInt null), `was_leading` (bool — did this bid take the lead),
`triggered_extension` (bool — did it fire an anti-snipe extension).
- `ordering=['-placed_at']`, index `(auction,placed_at)`, `(auction,amount)`.
- **Append-only**: admin add/change/delete disabled (mirrors `AuditLog`/`SourcingAward`).

### 5. AuctionDocument  *(buyer attachments — spec sheet, terms PDF)*
`auction` FK (`related_name='documents'`), `title`, `file` (`upload_to='auction_docs/'`),
`notes`, `uploaded_by` FK, `uploaded_at`. `ordering=['-uploaded_at']`.

*(Stretch model — `AuctionAutoBid`: participant floor + active flag, for proxy bidding. Deferred.)*

## Services (`apps/auctions/services.py`)

- **Perms:** `MANAGE_ROLES`/`MONITOR_ROLES` tuples; `can_manage_auction(user)`,
  `can_monitor_auction(user)` (manage + `approver`). Mirror Sourcing's helper pattern (superuser +
  role + `is_tenant_admin`).
- **Visibility gate:** `auction_state_for(user, auction)` is the single source of truth for what a
  given user may see (buyer = full leaderboard; vendor = blind own-rank+leading per `rank_visibility`;
  non-participant vendor = denied). Mirrors `bid_visible_to`.
- **Numbering:** `next_auction_number(tenant)` → `AUC-<SLUG>-NNNNN` (select_for_update, gap-free).
- **Clock:** `refresh_auction_state(auction)` — lazy transitions `scheduled→live` (now≥start_at) and
  `live→closed` (now≥end_at); called at the top of console/poll/place_bid. Idempotent, audited on flip.
- **Lifecycle (atomic, audited, validate source status):** `validate_auction_for_publish(auction)`
  (raises `ValidationError` unless ≥1 lot, ≥1 participant, start_at<end_at, start_at future-ish,
  starting_price>0, decrement_value>0, reserve≤starting; returns warnings), `publish_auction`
  (draft→scheduled), `start_auction` (scheduled→live, manual "Start now"), `close_auction`
  (live→closed), `cancel_auction(reason)`.
- **Participants:** `invite_vendors(auction, vendors, user)` (bulk, skip existing),
  `remove_participant`, `accept_invitation(participant, user)`, `decline_invitation`,
  `withdraw_participant`.
- **Bidding (core):** `place_bid(auction, vendor, amount, user, source='portal')` —
  `select_for_update` on auction; `refresh_auction_state`; validate: live, vendor is an
  accepted/invited participant, amount>0, amount ≤ `starting_price`, amount ≤
  `current_best − effective_decrement` (must beat global best by decrement; first bid only needs
  ≤ starting_price), optional reserve note. On success: create `AuctionBid`, update participant
  denorm, `recompute_ranks`, anti-snipe extension, audit. Raises `ValidationError` with a clear
  message on any rule break (so the JSON endpoint can surface it).
- `recompute_ranks(auction)` — order active participants by `current_bid_amount` asc (lowest=1),
  persist `current_rank`; unbid participants unranked.
- `current_best(auction)` → lowest current participant bid (Decimal or None).
- `live_payload(auction, user)` — the dict the poll endpoints serialise (status, `server_now`,
  `end_at` ISO, `seconds_remaining`, counts; buyer → full leaderboard; vendor → own rank, own bid,
  next valid max, leading price). Respects visibility gate.
- **Award:** `finalize_auction(auction, user, winner_vendor=None)` — winner = lowest valid bid (or
  override); set denormalised award, participant `won/lost`, status→awarded, reserve check warning;
  audit. `compute_auction_savings(auction)` → {baseline, awarded, savings, savings_pct} (baseline =
  starting_price or Σ lot est).
- **Analytics:** `tenant_auction_metrics(tenant)` (counts by status, total savings, avg participants,
  avg bids), `auction_analytics(auction)` (savings, participants, bids, extensions, duration,
  price-drop curve points for the chart).

## Forms (`apps/auctions/forms.py`)
- `AuctionForm` (tenant kwarg; all setup fields; `clean()`: end_at>start_at, decrement_value>0,
  reserve≤starting; category queryset scoped to tenant; `datetime-local` widgets).
- `AuctionLotForm` (tenant kwarg for `account_code` scoping).
- `InviteVendorsForm` (ModelMultipleChoiceField of active tenant vendors, exclude already-invited —
  reuse Sourcing pattern).
- `AuctionDocumentForm` (`clean_file`: ≤10 MB, ext allowlist).
- `PlaceBidForm` (single `amount` Decimal, MinValue>0 — for the no-JS fallback POST; the AJAX path
  reads `amount` directly and calls the service).
- `CancelAuctionForm` (reason).
- `FinalizeAwardForm` (optional `winner_vendor` override + notes).

## Buyer views (`apps/auctions/views.py`) — `@login_required` + `can_manage_auction` gate
CRUD per CRUD-Completeness Rules + lifecycle + console/results/analytics:
- `auction_list` (search `?q=` + status/type/category filters, pagination retaining filters)
- `auction_create`, `auction_detail` (tabs: Overview / Lots / Participants / Documents / Console / Results),
  `auction_edit` (draft only), `auction_delete` (POST, draft only)
- `auction_publish`, `auction_start`, `auction_close`, `auction_cancel` (POST lifecycle)
- `lot_create`, `lot_edit`, `lot_delete` (draft only)
- `participant_add` (invite form), `participant_remove`
- `document_add`, `document_delete`
- `console` (live monitoring page) + `console_state` (**JsonResponse** poll endpoint, buyer full view)
- `results` (post-auction results) + `award_finalize` (POST)
- `analytics_dashboard` (`/auctions/analytics/`), `auction_analytics` (`/auctions/<id>/analytics/`)
- *(stretch)* `bid_place_manual` (buyer bids on behalf of a phone-in vendor)

## Vendor portal views (`apps/auctions/portal_views.py`) — `@vendor_required` + manual ownership
- `portal_auction_list` (this vendor's invitations)
- `portal_auction_detail` (read-only info + accept/decline) 
- `portal_accept` (POST), `portal_decline` (POST), `portal_withdraw` (POST)
- `portal_bidding` (live bid screen — countdown, leading price, own rank, place-bid form)
- `portal_state` (**JsonResponse** poll endpoint — blind vendor view)
- `portal_place_bid` (**POST/JSON** — calls `place_bid`, returns updated `live_payload` or
  `{error: msg}`; ownership: vendor must be an accepted participant)

**IDOR defence (per map):** portal views `get_object_or_404` by pk (no tenant kwarg — vendor crosses
into buyer-tenant data via invitation), then explicitly verify `participant = AuctionParticipant.
objects.filter(auction=auction, vendor=request.user.vendor).first()` / `bid.vendor_id ==
request.user.vendor_id`. The blind JSON payload never includes competitor identities.

## URLs
- `apps/auctions/urls.py` (`app_name='auctions'`) — mirror Sourcing route shape + `console/`,
  `console/state/`, `results/`, `award/finalize/`, `analytics/`.
- Append to `apps/vendors/portal_urls.py` (vendor_portal namespace), importing
  `from apps.auctions import portal_views as auctions_portal_views`:
  `auctions/`, `auctions/<pk>/`, `auctions/<pk>/accept/`, `.../decline/`, `.../withdraw/`,
  `auctions/<pk>/bidding/`, `auctions/<pk>/state/` (json), `auctions/<pk>/place-bid/` (json).

## Templates (`templates/auctions/` + `templates/vendor_portal/auctions/`)
```
templates/auctions/
├── list.html              (filters + actions column)
├── form.html              (create/edit)
├── detail.html            (tabs: Overview/Lots/Participants/Documents/Console/Results + action sidebar)
├── lots/form.html
├── participants/form.html (invite multi-select)
├── documents/form.html
├── console.html           (live leaderboard, polls auctions:console_state)
├── results.html           (final ranks, savings, award action)
└── analytics/
    ├── dashboard.html      (tenant-wide, Chart.js)
    └── auction_report.html (per-auction, price-drop curve)
templates/vendor_portal/auctions/
├── list.html              (invitations)
├── detail.html            (read-only + accept/decline)
└── bidding.html           (live bid screen + countdown + poll, vendor_portal:auctions_state)
static/js/auction.js       (NEW — fetch() polling + countdown engine; data-* attrs for URLs/end_at)
```
All list pages follow Filter Implementation Rules (`status_choices`, FK querysets, `|stringformat:"d"`,
hidden pagination params). All detail pages have the Actions sidebar (status-gated). Charts via
`json_script` only (never `|safe`).

## Admin (`apps/auctions/admin.py`)
Register `Auction` (with `AuctionLot` + `AuctionParticipant` inlines), `AuctionBid`
(read-only/append-only — add/change/delete disabled), `AuctionDocument`. list_display/list_filter/
search mirroring Sourcing admin.

## Seed (`apps/auctions/management/commands/seed_auctions.py`) — idempotent, `--flush`
Per tenant, 3 auctions (uses real `timezone.now()` + `timedelta`):
- **Draft** — "Office laptops reverse auction Q3" (3 lots, no participants).
- **Scheduled** — "Bulk steel quarterly buy" (2 lots, 3 participants invited, starts in +1 day).
- **Awarded** — "Inbound logistics reverse auction" (1 lot, 3 participants, a realistic **bid
  history** of multiple lowering bids per vendor incl. one anti-snipe extension, ranks computed,
  lowest valid bid awarded, savings recorded).
Idempotent: skip if `Auction.objects.filter(tenant=tenant).exists()`; numbered-record existence check.
Chain into `seed_data` after `seed_rfx`. Print tenant-admin login hint + superuser-has-no-tenant warning.

## Cron command (`apps/auctions/management/commands/run_auction_clock.py`)
Sweeps all tenants (via `all_objects`): `scheduled→live` where `now≥start_at`, `live→closed` where
`now≥end_at`. Cron-friendly counterpart to `run_escalations`; the console/poll also sweep lazily.

## Tests (`apps/auctions/tests/`) — copy `apps/rfx/tests/` layout, target ~100+
- `conftest.py` — `tenant` (with `set_current_tenant`/`clear`), `other_tenant`, `tenant_admin_user`,
  `buyer_user`, `requester_user`, `vendor`/`vendor2`/`vendor3`, `vendor_user`(s),
  `client_tenant_admin`, `client_vendor`, `auction_factory`, `live_auction_factory`
  (create-not-mutate per the fixture-poisoning lesson).
- `test_models.py` — numbering, unique_together, choices, denorm defaults, append-only ledger,
  properties (`is_live`, `seconds_remaining`, `effective_decrement`, `required_next_max`).
- `test_services.py` — publish validation, lazy clock transitions, `place_bid` happy path,
  **decrement enforcement**, **lowering/ceiling enforcement** (reject bids above current best or
  above starting_price), **anti-snipe extension**, rank recompute, finalize/award + reserve,
  savings math, visibility payload (buyer-full vs vendor-blind).
- `test_views.py` — CRUD + permission gates + filter retention + console/results access + JSON
  endpoint shapes.
- `test_security.py` — A01 IDOR (cross-tenant 404; cross-vendor: non-participant can't reach
  bidding/state/place-bid; vendor A can't see B's identity in the blind payload — **canary lives
  only in competitor-name markup**), A03 XSS escape (title), A04 mass-assignment (vendor can't place
  a bid above ceiling / violating decrement via direct POST — the auction-specific test), A07
  anonymous→login redirect, CSRF on POST endpoints, file-upload size/ext caps.

## Wiring (modify — 6 files)
1. `config/settings.py` — append `'apps.auctions'` to `INSTALLED_APPS` (after `apps.rfx`).
2. `config/urls.py` — `path('auctions/', include('apps.auctions.urls'))` (after rfx).
3. `apps/core/management/commands/seed_data.py` — append `'seed_auctions'` to the chain.
4. `templates/partials/sidebar.html` — new "E-Auctions" group (same role gate), icon
   `ri-hammer-line` (`ri-auction-line` is taken by Sourcing): links Auctions + Auction Analytics.
5. `apps/vendors/portal_urls.py` — import auctions portal_views; append vendor auction routes.
6. `templates/vendor_portal/base.html` — add "Live Auctions" vp-nav link (`ri-hammer-line`).
   *(No middleware change — `/vendor-portal/` is already an allowed sandbox prefix.)*

## README (mandatory — same session)
ToC (+Module 8), intro paragraph (+Module 8 line), Project Structure tree (+`apps/auctions/`,
`templates/auctions/`, `templates/vendor_portal/auctions/`, `static/js/auction.js`), new **Module 8 —
E-Auction Management** section, Routes table (+auction + vendor-portal auction routes), Management
Commands (+`seed_auctions`, +`run_auction_clock`), Seeded Demo Data (+auction data), Roadmap
(Module 8 → Shipped).

## Implementation order (checklist)
### Phase 1 — Skeleton & models
- [ ] `apps/auctions/` package (`__init__.py`, `apps.py` → `name='apps.auctions'`)
- [ ] `apps.auctions` in `INSTALLED_APPS`
- [ ] `models.py` (5 models + constants + properties)
- [ ] `makemigrations auctions` → `0001_initial`; `migrate`; `manage.py check` clean
### Phase 2 — Services
- [ ] perms + visibility gate + numbering
- [ ] clock (`refresh_auction_state`) + lifecycle
- [ ] participants
- [ ] `place_bid` (decrement/ceiling/lowering + anti-snipe + select_for_update) + `recompute_ranks`
- [ ] `live_payload`, finalize/award, savings, analytics
### Phase 3 — Forms, buyer URLs/views, templates
- [ ] forms; `urls.py`; buyer views (incl. JSON `console_state`); buyer templates; sidebar group
### Phase 4 — Vendor portal + live JS
- [ ] `portal_views.py`; portal URL registration; portal templates; `static/js/auction.js`;
      vendor sidebar link; sandbox compatibility check
### Phase 5 — Admin, seed, cron
- [ ] `admin.py`; `seed_auctions.py` (idempotent) + chain; `run_auction_clock.py`
### Phase 6 — Tests
- [ ] conftest + test_models + test_services + test_views + test_security; `pytest` all green, no regressions
### Phase 7 — Docs & verification
- [ ] README (all locations); `manage.py check`; seed + `--flush`; smoke-test buyer routes 200,
      vendor portal routes 200, multi-tenant 404, blind-payload no leak, full live-bid round
      (place several lowering bids → ranks update → anti-snipe extends → close → finalize → savings)
- [ ] Per-file PowerShell commit snippets (one file per commit)

## Stretch goals (defer, document if cut)
- Multi-lot per-line live bidding (bid per lot, per-lot rankings/award).
- Proxy / auto-bidding (`AuctionAutoBid`: vendor floor; system holds the lead by min decrement).
- Hand-off provenance: "Run an E-Auction" button on a completed RFx / closed Sourcing event
  (the `sourcing_event` FK is included now as a cheap nullable hook).
- Email notifications on invite/start/outbid (project-wide gap — console-only for now).

## Open scope notes
- **No celery/websockets** — realtime is poll-based (decision #1). Clock is lazy + a cron command.
- **Forward (English ascending) auctions** — field present, not implemented in v1 (procurement is reverse).
- **Currency** — single per auction (copied to bids); cross-currency vendors decline.

---

## Review / Verification

**Completed:** 2026-05-29

### What shipped
- **New app `apps/auctions/`** at `/auctions/`; vendor-side under `/vendor-portal/auctions/`. Both sidebars updated.
- **5 models**: `Auction`, `AuctionLot`, `AuctionParticipant`, `AuctionBid` (append-only ledger), `AuctionDocument` + choice constants + Auction props (`is_editable`/`is_live`/`can_cancel`/`is_finished`/`seconds_remaining`/`total_budget`/`effective_decrement`/`required_next_max`).
- **Services**: perms (`can_manage_auction`/`can_monitor_auction`), blind gate (`auction_state_for`), numbering, lazy clock (`refresh_auction_state`), lifecycle (publish/start/close/cancel), participants (invite/accept/decline/withdraw/remove), concurrency-safe `place_bid` (select_for_update + ceiling/decrement/lowering + anti-snipe), `recompute_ranks`, `current_best`, `live_payload` (buyer-full vs vendor-blind), `finalize_auction`, savings + analytics.
- **Realtime via AJAX polling** — `static/js/auction.js` (vanilla, no deps): ~3s JSON poll, server-authoritative countdown, drives buyer console + vendor bidding; bids POST via fetch. No websockets/celery.
- **8 buyer templates + 3 vendor-portal templates** + sidebar/base nav.
- **30 buyer views + 8 vendor-portal views** (incl. 2 JSON poll endpoints + AJAX place-bid).
- **Seed** `seed_auctions` (idempotent, `--flush`): 3 auctions/tenant (draft / scheduled / awarded-with-live-ledger), chained into `seed_data` after `seed_rfx`.
- **Cron** `run_auction_clock`: sweeps scheduled→live, live→closed across all tenants.
- **Tests**: 157 (31 models + 68 services + 38 views + 20 security). Full project suite **553 passed, 0 regressions**.

### Bugs found & fixed during the build
1. **`_has_role` denied all non-admin buyers** — `User.role` is a CharField, but the helper only read `role.slug`/`role.name`. Fixed to handle the string slug. Caught + proven by the services e2e test.
2. **Seed `finalize` crashed "No valid bids to award"** — the awarded auction had `end_at` in the past, so the first `place_bid`→`refresh_auction_state` auto-closed it. Fixed: seed `end_at` now sits inside the anti-snipe window (future), so the live round runs (firing one anti-snipe extension) before `close_auction`/`finalize`.
3. Two **test-only** fixes (a `.number`→`.auction_number` typo; a too-strict leaderboard-name assertion). No further app bugs.

### Deviations from plan
- **Sidebar** rendered as a collapsible group (All Auctions / New Auction / Analytics) to match Sourcing/RFx.
- **`requisition`/`sourcing_event` FKs** present as cheap nullable hooks; cross-module hand-off deferred (stretch).
- **Multi-lot per-line bidding** and **proxy/auto-bidding** deferred (stretch).
- Analytics dashboard also exposed at `/auctions/` (root) in addition to `/auctions/analytics/`.

### Verified
- `manage.py check` clean; `makemigrations`→`0001_initial`; `migrate` OK on MySQL.
- `seed_auctions` + `--flush` → 9 auctions / 15 bids / 3 awards / 3 anti-snipe extensions across 3 tenants; idempotent rerun skips.
- `pytest apps/auctions/` → 157 passed; `pytest` (full) → 553 passed; all 11 templates compile.

### Files: 34 new + 7 modified (config/settings.py, config/urls.py, seed_data.py, vendors/portal_urls.py, partials/sidebar.html, vendor_portal/base.html, README.md).
