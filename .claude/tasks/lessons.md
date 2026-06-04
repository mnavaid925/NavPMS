# Lessons learned

Captured corrections and validated approaches go here. Each entry: short, rule first,
then **Why** and **How to apply** lines (see `.claude/CLAUDE.md` self-improvement loop).

## Conventions
- One bullet per lesson, dated.
- Link related lessons inline (`[[other-lesson]]`).
- If a lesson becomes wrong, edit or delete it — don't accumulate stale rules.

---

- **2026-05-23 — Validate `DecimalField` quantities/prices server-side, not just with HTML `min`.**
  `QuickRequisitionItemForm` accepted negative `quantity`/`unit_price` because the
  `min=0` was only a widget attribute. **Why:** HTML constraints are advisory; a direct
  POST bypasses them. **How to apply:** put `MinValueValidator` on the *model* field so
  forms, admin, and any future API all inherit it.

- **2026-05-23 — Free-text URL fields rendered as `href` need a scheme allowlist.**
  `Notification.link_url` accepted `javascript:` URIs; Django auto-escaping does not
  neutralise script-scheme URIs. **Why:** `<a href="{{ value }}">` executes a
  `javascript:`/`data:` URI on click. **How to apply:** add a `clean_<field>()` that
  allows only `http(s)://` and site-relative (`/`, `#`, `?`) values.

- **2026-05-23 — Never `{{ value|safe }}` into a `<script>` block; use `json_script`.**
  `reports/detail.html` interpolated a Python list via `|safe` into inline JS — a label
  containing `</script>` breaks out. **How to apply:** `{{ data|json_script:"id" }}` +
  `JSON.parse(document.getElementById('id').textContent)`.

- **2026-05-23 — `redirect()` does not validate hosts; a `next` param is an open redirect.**
  Guard with `django.utils.http.url_has_allowed_host_and_scheme(nxt, {request.get_host()})`
  before redirecting, and fall back to a known-safe URL otherwise.

- **2026-05-23 — `settings_test.py` must disable the production HTTPS hardening.**
  With `SECURE_SSL_REDIRECT=True` the Django test client (plain HTTP) gets 301s on every
  request. **How to apply:** in test settings, set `SECURE_SSL_REDIRECT`,
  `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` all to `False`.

- **2026-05-23 — `unique_together` + a form-excluded field = silent 500.** When a
  `ModelForm` excludes a field that is part of a `unique_together` constraint (e.g.
  `tenant` is set in the view, not the form), Django's `validate_unique()` *skips*
  every uniqueness check involving that excluded field, so a duplicate passes
  `form.is_valid()` and dies on the DB `INSERT` with an `IntegrityError` (HTTP 500).
  **Why:** `BaseModelForm._get_validation_exclusions()` drops such constraints — it
  can't validate them without the missing field's value. **How to apply:** make the
  form accept the missing value as a kwarg (`__init__(self, *args, tenant=None,
  **kwargs)`) and re-validate uniqueness in `clean_<field>()`; pass it from the view
  on every POST. Verified fix: `AccountCodeForm` in `apps/requisitions/forms.py`.

- **2026-05-23 — Wide tables need `.table-responsive` AND a shrinkable layout
  container.** A multi-column table forces horizontal page overflow on mobile
  unless (a) it is wrapped in `.table-responsive` *and* (b) its layout ancestor
  can shrink below its content. A CSS-grid item (like `.app-main` in a `1fr`
  track) or a flex item defaults to `min-width: auto` and will NOT shrink below
  its intrinsic content width — set `min-width: 0` on it. **How to apply:** wrap
  every list/detail table in `.table-responsive`; ensure the main content
  region has `min-width: 0`. Also watch theme-attribute selectors
  (`html[data-...] .x`) out-specifying media-query rules — scope the responsive
  rule through the same attribute so it wins.

- **2026-05-23 — Driving Django's test `Client` from a plain script needs
  `setup_test_environment()`.** Outside `manage.py test`, `response.context` and
  `response.templates` are `None` unless `django.test.utils.setup_test_environment()`
  is called first (it connects the `template_rendered` signal). Call it once at the
  top of any ad-hoc harness that asserts on template context.

- **2026-05-26 — `ModelForm` fields for `PositiveIntegerField(default=N)` are
  required by default at the *form* layer — even when the view auto-fills them.**
  A `position` field with `default=1` on the model still raises "This field is
  required" if the user submits an empty value, because `ModelForm` derives
  `required=True` from `blank=False`. **Why:** the model default kicks in at
  `INSERT` time, but the form rejects the POST before the view ever gets to
  apply it. **How to apply:** in the form's `__init__`, set
  `self.fields['position'].required = False` whenever the view auto-populates a
  missing value. Verified fix: `RfxSectionForm`, `RfxTemplateSectionForm`, and
  the shared `_BaseQuestionForm` in [apps/rfx/forms.py](apps/rfx/forms.py).

- **2026-05-26 — Sealed-content leak tests need a canary that *isn't* a value
  already rendered elsewhere on the page.** A test that asserted `b'Acme' not
  in resp.content` failed not because of a leak but because the response
  vendor's `legal_name` was "Acme IT Solutions" and showed in the sidebar /
  breadcrumb of the sealed page. **Why:** sealed banners typically still
  render vendor identity (so the buyer knows *who* responded) — only the
  answer body is hidden. **How to apply:** pick a canary that lives *only*
  inside the per-question answer markup — e.g. `b'Q1.'`, or a hash unique to
  the answer content seeded for the test. Verified fix:
  `test_response_detail_sealed_before_close` in
  [apps/rfx/tests/test_views.py](apps/rfx/tests/test_views.py).

- **2026-05-26 — Fixture chains that mutate a shared object in place poison
  filter tests.** An `open_event` fixture built `from draft_event` by setting
  `draft_event.status = 'open'` and saving — so any test that asked for both
  fixtures got the *same* event in status `open`, breaking `?status=draft`
  filter assertions. **Why:** pytest evaluates each fixture once per scope;
  re-using `draft_event` inside `open_event` mutates the underlying row, not a
  fresh copy. **How to apply:** either (a) have the dependent fixture
  `create_event(...)` a brand-new event instead of mutating, or (b) drop the
  unrelated fixture from the test's parameters. The cleanest fix is to not
  share state — fixtures should create, not mutate.

- **2026-05-29 — An access gate is only as good as its least-guarded sibling
  view.** RFx `response_detail` correctly gated sealed bids via
  `response_visible_to` (role + post-close), but `response_list`,
  `response_compare`, and both analytics views shipped with only a
  `_require_tenant` check — so any tenant user (e.g. `role='requester'`) read
  the full competitor bid set after close (SQA D-01/D-02). **Why:** the gate
  was added per-view as each was written, not derived from "what data does this
  expose?". **How to apply:** when one view protects a class of data, grep every
  sibling view that touches the *same* models/queryset and apply the *same*
  predicate. Extract it (`_can_view_responses`) so the rule has one home.
  Verified fix: [apps/rfx/views.py](apps/rfx/views.py); guard tests in
  `apps/rfx/tests/test_access_control.py`.

- **2026-05-29 — To retry on a unique-constraint collision, catch
  `IntegrityError` *outside* a per-attempt `with transaction.atomic()` block —
  never inside one wrapped by `@transaction.atomic`.** Count-based numbering
  (`RFX-<SLUG>-NNNNN`) races: two concurrent creates compute the same number and
  the second INSERT 500s on `unique_together` (SQA D-05). The fix loops, each
  iteration in its own `atomic()` (a savepoint when nested inside
  `create_event_from_template`), and catches `IntegrityError` after the block so
  the savepoint has already rolled back cleanly and any enclosing transaction
  stays usable. Catching inside an atomic that's still marked-for-rollback raises
  `TransactionManagementError` on the next query. Verified fix:
  `create_event` in [apps/rfx/services.py](apps/rfx/services.py).

- **2026-05-29 — A view computing an authorization flag is worthless if the
  template gates on something else.** `event_detail` correctly computed
  `can_view_responses = responses_are_visible AND (manage OR evaluate)` and
  passed it to the template — but the Responses tab rendered the scored
  rank/score table whenever `responses_are_visible` (status only), ignoring the
  flag. So gating `response_list`/`compare`/analytics at the view layer (D-01)
  still left the same sealed scores readable on the event page. An adversarial
  review caught it; my own access-control tests had not. **How to apply:** when
  a view passes a permission flag to a template, grep the template for every
  render of the protected data and gate each on *that flag*, not on a status
  property that merely correlates. Add a paired test: privileged user SEES the
  value, low-privilege user does NOT (same fixture, different role). Verified
  fix: [templates/rfx/events/detail.html](templates/rfx/events/detail.html).

- **2026-05-29 — A fixed-ceiling query-count test can pass with the exact N+1 it
  was written to catch; assert N-independence instead.** `django_assert_max_num_queries(25)`
  passed both the bulk-loaded compare (19 queries) and a reverted per-cell N+1
  (25) — the head-room absorbed the regression. The robust guard builds a small
  and a large fixture and asserts the query count is *equal*. That hardened test
  then exposed a real residual N+1 I'd missed: bulk-loading `RfxAnswer` without
  `select_related('question')` let the template's `ans.is_answered`/`ans.value`
  lazy-load the question FK once per cell. **How to apply:** never trust an
  absolute query ceiling as an N+1 guard — assert count is independent of row
  count; and when bulk-loading objects, `select_related` every FK that a
  template or model property will dereference. Verified:
  [apps/rfx/tests/test_performance.py](apps/rfx/tests/test_performance.py),
  [apps/rfx/views.py](apps/rfx/views.py) `response_compare`.

- **2026-05-29 — File-upload validation belongs in a shared helper, applied at
  every intake — not just the ModelForm.** RFx accepted uploads via two paths:
  `RfxDocumentForm.clean_file` *and* a non-form vendor handler
  (`_save_answer_from_post`). Size was checked in both but type in neither (SQA
  D-04). Fix: one `upload_error(f, max_bytes)` helper with a **whitelist**
  (`ALLOWED_UPLOAD_EXTENSIONS`, not a blacklist) — rejecting `.svg`/`.html`/`.js`
  that become stored XSS when Apache serves MEDIA inline — called by both. **How
  to apply:** whenever a model has a `FileField`, find *all* request handlers
  that populate it (forms AND raw `request.FILES` parsers) and route every one
  through the same validator. Verified fix:
  [apps/rfx/forms.py](apps/rfx/forms.py) + [apps/rfx/portal_views.py](apps/rfx/portal_views.py).

- **2026-05-26 — `qs.first().attr = X; qs.first().save()` saves the wrong
  instance.** Each call to `qs.first()` returns a *different* Python object;
  the first assignment mutates an instance that's then discarded, and the
  second `.save()` writes a fresh-from-DB object with the original value.
  **Why:** Django querysets don't cache `first()` results — every call hits
  the DB or rebuilds the wrapper. **How to apply:** always bind to a local:
  `obj = qs.first(); obj.attr = X; obj.save()`. Bit me in a `rank_responses`
  test where two `r_a.answers.first()` calls saved an answer with
  `value_number=None`, then `submit_response` rightly failed the required-
  answer check.

- **2026-06-04 — Check a lifecycle precondition AFTER `select_for_update()`, on the
  locked row — never before it.** Module 12's `advise/confirm/cancel/close_shipment`
  evaluated `can_*` on the PASSED-IN (possibly stale) instance, then locked the row but
  never re-checked, so two concurrent POSTs could both pass a stale status (e.g. cancel a
  shipment a racing `confirm_delivery` just moved to `received` — freeing already-received
  qty for re-shipping). **How to apply:** in every transition service,
  `obj = Model.all_objects.select_for_update().get(pk=obj.pk)` FIRST, then
  `if not obj.can_X: raise`. (Module 11's PO services share this anti-pattern except
  `apply_change_order`, which does it right.) Verified fix: [apps/fulfillment/services.py](apps/fulfillment/services.py).

- **2026-06-04 — Gate status-ADVANCING side-effects to the states that should produce
  them.** `add_manual_tracking_event`/`sync_tracking` ran `_advance_status` with no
  precondition, so a *draft* shipment could be driven straight to `delivered` — skipping
  `advise_shipment` AND the only receipt-posting path (`confirm_delivery`), decoupling
  shipment state from PO received qty. **How to apply:** gate such mutators on the relevant
  in-flight predicate (`shipment.can_track`), and gate the matching template panel on the
  same predicate — not on a looser `not is_finished`. Verified fix:
  [apps/fulfillment/services.py](apps/fulfillment/services.py) + the detail template.

- **2026-06-04 — A gap-free sequence number must use `Max(field)+1`, not `count()+1`.**
  Shipment `line_no` derived from `lines.count()+1` collided (→ IntegrityError 500) after a
  mid-list line was deleted. **How to apply:**
  `(qs.aggregate(m=Max('line_no'))['m'] or 0) + 1`, or route through the service that
  already does so — don't let a view re-implement the numbering differently. Verified fix:
  [apps/fulfillment/views.py](apps/fulfillment/views.py) + portal_views.py.

- **2026-06-04 — Locking the PARENT row does not protect a stale CHILD read in a
  read-modify-write.** `record_line_receipt` locked the `PurchaseOrder` header but computed
  `new_received` from the caller's stale in-memory `line`, so two concurrent split-delivery
  confirmations on the same PO line lost an update (and could defeat the over-receipt
  guard). **How to apply:** re-fetch+lock the exact row you mutate —
  `line = PurchaseOrderLine.all_objects.select_for_update().get(pk=line.pk)` — inside the
  same transaction before reading its value. Verified fix:
  [apps/purchase_orders/services.py](apps/purchase_orders/services.py) `record_line_receipt`.
