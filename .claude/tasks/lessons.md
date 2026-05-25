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
