/* NavPMS theme manager + sidebar toggle + preloader fade + customizer tabs. */
(function () {
  'use strict';

  var STORAGE_KEY = 'navpms.ui';
  var ATTR_MAP = {
    layout: 'data-layout',
    theme: 'data-theme',
    topbar: 'data-topbar',
    sidebar: 'data-sidebar',
    sidebarSize: 'data-sidebar-size',
    layoutWidth: 'data-layout-width',
    layoutPosition: 'data-layout-position',
    direction: 'dir',
  };

  // Captured ONCE at script init, before any pref is applied to <html>.
  // Reset must reuse this, NOT re-read attrs (which would now reflect overrides).
  var SERVER_DEFAULTS = readServerDefaults();

  function loadPrefs() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) { return {}; }
  }

  function savePrefs(p) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(p)); } catch (e) {}
  }

  function applyPrefs(p) {
    var html = document.documentElement;
    Object.keys(ATTR_MAP).forEach(function (key) {
      if (p[key]) html.setAttribute(ATTR_MAP[key], p[key]);
    });
  }

  function readServerDefaults() {
    var html = document.documentElement;
    var defaults = {};
    Object.keys(ATTR_MAP).forEach(function (key) {
      var attr = ATTR_MAP[key];
      var val = html.getAttribute(attr);
      if (val) defaults[key] = val;
    });
    return defaults;
  }

  // Sync radio inputs AND keep visual .is-checked class on parent label.
  function syncRadios(p) {
    document.querySelectorAll('[data-theme-setting]').forEach(function (input) {
      var key = input.getAttribute('data-theme-setting');
      var match = (p[key] != null && input.value === p[key]);
      input.checked = match;
      var label = input.closest('.tc-swatch, .tc-icon-pick');
      if (label) label.classList.toggle('is-checked', match);
    });
    document.querySelectorAll('[data-theme-setting-toggle]').forEach(function (input) {
      var key = input.getAttribute('data-theme-setting-toggle');
      var on = input.getAttribute('data-on');
      input.checked = (p[key] === on);
    });
  }

  function initThemeSettings() {
    var merged = Object.assign({}, SERVER_DEFAULTS, loadPrefs());
    applyPrefs(merged);
    syncRadios(merged);

    document.querySelectorAll('[data-theme-setting]').forEach(function (input) {
      input.addEventListener('change', function () {
        var prefs = Object.assign({}, loadPrefs());
        prefs[input.getAttribute('data-theme-setting')] = input.value;
        savePrefs(prefs);
        applyPrefs(prefs);
        syncRadios(Object.assign({}, SERVER_DEFAULTS, prefs));
      });
    });

    document.querySelectorAll('[data-theme-setting-toggle]').forEach(function (input) {
      input.addEventListener('change', function () {
        var prefs = Object.assign({}, loadPrefs());
        var key = input.getAttribute('data-theme-setting-toggle');
        prefs[key] = input.checked
          ? input.getAttribute('data-on')
          : input.getAttribute('data-off');
        savePrefs(prefs);
        applyPrefs(prefs);
      });
    });

    var reset = document.querySelector('[data-theme-reset]');
    if (reset) {
      reset.addEventListener('click', function () {
        try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
        // Reapply defaults to <html> AND to every customizer control.
        applyPrefs(SERVER_DEFAULTS);
        syncRadios(SERVER_DEFAULTS);
      });
    }
  }

  function initCustomizerTabs() {
    var tabs = document.querySelectorAll('[data-tc-tab]');
    if (!tabs.length) return;
    tabs.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = btn.getAttribute('data-tc-tab');
        tabs.forEach(function (b) { b.classList.toggle('active', b === btn); });
        document.querySelectorAll('[data-tc-pane]').forEach(function (pane) {
          pane.classList.toggle('active', pane.getAttribute('data-tc-pane') === target);
        });
      });
    });
  }

  function initThemeToggle() {
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var html = document.documentElement;
        var current = html.getAttribute('data-theme') || 'light';
        var next = current === 'light' ? 'dark' : 'light';
        var prefs = Object.assign({}, loadPrefs());
        prefs.theme = next;
        savePrefs(prefs);
        applyPrefs(prefs);
        syncRadios(Object.assign({}, SERVER_DEFAULTS, prefs));
      });
    });
  }

  function initSidebarToggle() {
    document.querySelectorAll('[data-sidebar-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        document.body.classList.toggle('sidebar-open');
      });
    });
    document.addEventListener('click', function (e) {
      if (!document.body.classList.contains('sidebar-open')) return;
      var sidebar = document.querySelector('.app-sidebar');
      var trigger = e.target.closest('[data-sidebar-toggle]');
      if (sidebar && !sidebar.contains(e.target) && !trigger) {
        document.body.classList.remove('sidebar-open');
      }
    });
  }

  function fadePreloader() {
    var p = document.getElementById('preloader');
    if (!p) return;
    setTimeout(function () {
      p.classList.add('is-hidden');
      setTimeout(function () { p.remove(); }, 350);
    }, 100);
  }

  // The sidebar is its own scroll container (fixed layout) and resets to the top
  // on every full-page navigation, which can push the just-clicked item out of
  // view. Scroll ONLY the sidebar (never the window) the minimum needed to keep
  // the active item visible after the reload.
  function keepActiveNavInView(sidebar, active) {
    var pad = 12;
    var s = sidebar.getBoundingClientRect();
    var a = active.getBoundingClientRect();
    if (a.top < s.top + pad) {
      sidebar.scrollTop -= (s.top + pad) - a.top;
    } else if (a.bottom > s.bottom - pad) {
      sidebar.scrollTop += a.bottom - (s.bottom - pad);
    }
  }

  // Highlight the ONE sidebar link that best matches the current URL and open
  // only its group. We pick the longest matching href (exact match, or a prefix
  // ending on a path boundary) so e.g. /requisitions/create/ lights up "New
  // Requisition" alone — not also "All Requisitions" (/requisitions/).
  function markActiveNav() {
    // Normalize current path to a trailing slash so the prefix test respects
    // path segments (and stays correct even for a future non-slash route).
    var path = window.location.pathname.replace(/\/?$/, '/');
    var links = document.querySelectorAll('.app-sidebar .nav-link[href]');
    var best = null;
    var bestLen = -1;

    links.forEach(function (a) {
      var href = a.getAttribute('href');
      if (!href || href.charAt(0) !== '/') return; // skip "#sbXxx" toggles / external
      var boundary = href.replace(/\/?$/, '/');
      // Exact match, or a prefix ending on a "/" boundary. The boundary !== '/'
      // guard stops the root link from prefix-matching every page.
      var isMatch = (path === boundary) || (boundary !== '/' && path.indexOf(boundary) === 0);
      if (isMatch && href.length > bestLen) {
        best = a;
        bestLen = href.length;
      }
    });

    if (!best) return;

    best.classList.add('active');

    // Open the ancestor collapse group (if this leaf lives in a submenu) and
    // flag its toggle so the group reads as active even when collapsed.
    var group = best.closest('.collapse');
    if (group && group.id) {
      group.classList.add('show');
      var toggle = document.querySelector('.app-sidebar [href="#' + group.id + '"]');
      if (toggle) {
        toggle.setAttribute('aria-expanded', 'true');
        toggle.classList.remove('collapsed');
        toggle.classList.add('has-active-child');
      }
    }

    // Group is now expanded, so the active item's position is final — keep it
    // on screen across the full-page reload that navigation triggers.
    var sidebar = best.closest('.app-sidebar');
    if (sidebar) keepActiveNavInView(sidebar, best);
  }

  // Accordion: opening one sidebar group auto-collapses any other open group,
  // keeping the (long) nav compact. Uses Bootstrap's collapse events so it
  // cooperates with the manual open in markActiveNav (hide() reads the .show
  // class). Nested chains are left intact via the contains() guards.
  function initSidebarAccordion() {
    var sidebar = document.querySelector('.app-sidebar');
    if (!sidebar || !window.bootstrap) return;
    sidebar.addEventListener('show.bs.collapse', function (e) {
      var opening = e.target;
      sidebar.querySelectorAll('.collapse.show').forEach(function (openEl) {
        if (openEl === opening || openEl.contains(opening) || opening.contains(openEl)) return;
        window.bootstrap.Collapse.getOrCreateInstance(openEl, { toggle: false }).hide();
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initThemeSettings();
    initCustomizerTabs();
    initThemeToggle();
    initSidebarToggle();
    initSidebarAccordion();
    markActiveNav();
    fadePreloader();
  });
})();

/* =====================================================================
   List pages: client-side column sorting + filter form auto-submit.
   Pages opt in via data attributes (nothing runs otherwise):
     <table data-sortable>                  click-to-sort headers
                                            (sorts the CURRENT page's rows only)
     <th data-sort="none|number|date|text"> exclude a column / skip the type
                                            heuristic
     <td data-sort-value="...">             raw comparison value when the
                                            display text isn't sortable
     <form data-filter-autosubmit>          selects submit on change, text
                                            inputs submit debounced, and an
                                            optional .filter-clear.d-none link
                                            is revealed when a filter is active
   ===================================================================== */
(function () {
  'use strict';

  /* ---------- sorting ---------- */

  // "$1,234.50", "USD 1200", "85%" → 1234.5 / 1200 / 85; non-numeric → null.
  function parseNumber(v) {
    var s = v.replace(/^[A-Z]{3}\b/, '').replace(/[$€£¥,%\s]/g, '');
    if (s === '' || isNaN(s)) return null;
    return parseFloat(s);
  }

  function isEmptyValue(v) {
    return !v || v === '—' || v === '-';
  }

  function cellValue(row, idx) {
    var td = row.cells[idx];
    if (!td) return '';
    if (td.dataset.sortValue !== undefined) return td.dataset.sortValue;
    return td.textContent.trim();
  }

  // Column type when the th carries no data-sort hint: ≥80% numeric wins,
  // then ≥80% parseable-but-not-numeric dates, else text.
  function detectType(values) {
    var present = values.filter(function (v) { return !isEmptyValue(v); });
    if (!present.length) return 'text';
    var nums = 0, dates = 0;
    present.forEach(function (v) {
      if (parseNumber(v) !== null) nums++;
      else if (!isNaN(Date.parse(v))) dates++;
    });
    if (nums / present.length >= 0.8) return 'number';
    if (dates / present.length >= 0.8) return 'date';
    return 'text';
  }

  function compareValues(type, av, bv) {
    if (type === 'number') {
      var an = parseNumber(av), bn = parseNumber(bv);
      if (an === null && bn === null) return 0;
      if (an === null) return 1;
      if (bn === null) return -1;
      return an - bn;
    }
    if (type === 'date') {
      var ad = Date.parse(av), bd = Date.parse(bv);
      if (isNaN(ad) && isNaN(bd)) return 0;
      if (isNaN(ad)) return 1;
      if (isNaN(bd)) return -1;
      return ad - bd;
    }
    return av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' });
  }

  function sortBy(table, tbody, th, idx) {
    var dir = th.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (h) {
      h.removeAttribute('aria-sort');
    });
    th.setAttribute('aria-sort', dir);

    // Spanning rows (the empty-state row) are never sorted.
    var rows = Array.prototype.filter.call(tbody.rows, function (tr) {
      return !tr.querySelector('td[colspan]');
    });
    var values = rows.map(function (tr, i) { return cellValue(tr, idx); });
    var type = (th.dataset.sort && th.dataset.sort !== 'none') ? th.dataset.sort : detectType(values);
    var desc = dir === 'descending';

    // Decorate-sort-undecorate with the original index as tiebreaker so equal
    // rows keep a stable order; empties sort last regardless of direction.
    var decorated = rows.map(function (tr, i) { return { row: tr, value: values[i], index: i }; });
    decorated.sort(function (a, b) {
      var aEmpty = isEmptyValue(a.value), bEmpty = isEmptyValue(b.value);
      if (aEmpty && bEmpty) return a.index - b.index;
      if (aEmpty) return 1;
      if (bEmpty) return -1;
      var cmp = compareValues(type, a.value, b.value);
      if (cmp === 0) return a.index - b.index;
      return desc ? -cmp : cmp;
    });
    // appendChild MOVES rows (handlers + inline delete forms survive intact).
    decorated.forEach(function (d) { tbody.appendChild(d.row); });
  }

  function initListTable(table) {
    var tbody = table.tBodies[0];
    if (!tbody || !table.tHead || !table.tHead.rows.length) return;
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, idx) {
      if (th.dataset.sort === 'none' || !th.textContent.trim()) return;
      th.classList.add('sortable');
      th.setAttribute('tabindex', '0');
      th.addEventListener('click', function () { sortBy(table, tbody, th, idx); });
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          sortBy(table, tbody, th, idx);
        }
      });
    });
  }

  /* ---------- filter forms ---------- */

  function initFilterForm(form) {
    function submit() {
      if (typeof form.requestSubmit === 'function') form.requestSubmit();
      else form.submit();
    }

    Array.prototype.forEach.call(form.querySelectorAll('select'), function (sel) {
      sel.addEventListener('change', submit);
    });

    Array.prototype.forEach.call(
      form.querySelectorAll('input[type="search"][name], input[type="text"][name]'),
      function (input) {
        var initial = input.value.trim();
        var timer = null;
        input.addEventListener('input', function () {
          if (timer) clearTimeout(timer);
          var v = input.value.trim();
          if (v === initial) return;
          if (v.length === 1) return; // wait for ≥2 chars (or a full clear)
          timer = setTimeout(submit, 400);
        });
      }
    );

    // Reveal the "clear filters" link when any named control holds a value.
    var clear = form.querySelector('.filter-clear');
    if (clear) {
      var active = Array.prototype.some.call(form.elements, function (el) {
        return el.name && el.name !== 'page' && el.type !== 'submit' && el.value;
      });
      if (active) clear.classList.remove('d-none');
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('table[data-sortable]').forEach(function (table) {
      try { initListTable(table); } catch (e) { /* one bad table must not break the rest */ }
    });
    document.querySelectorAll('form[data-filter-autosubmit]').forEach(function (form) {
      try { initFilterForm(form); } catch (e) { /* ditto for filter forms */ }
    });
  });
})();
