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

  function markActiveNav() {
    var path = window.location.pathname;
    document.querySelectorAll('.app-sidebar .nav-link[href]').forEach(function (a) {
      var href = a.getAttribute('href');
      if (href && href !== '/' && path.indexOf(href) === 0) {
        a.classList.add('active');
        var group = a.closest('.collapse');
        if (group) group.classList.add('show');
      } else if (href === path) {
        a.classList.add('active');
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initThemeSettings();
    initCustomizerTabs();
    initThemeToggle();
    initSidebarToggle();
    markActiveNav();
    fadePreloader();
  });
})();
