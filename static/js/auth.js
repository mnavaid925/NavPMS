/* Auth-page helpers: password show/hide toggle. */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-password-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var selector = btn.getAttribute('data-password-toggle');
        var input = document.querySelector(selector);
        if (!input) return;
        var hide = input.type === 'password';
        input.type = hide ? 'text' : 'password';
        var icon = btn.querySelector('i');
        if (icon) {
          icon.className = hide ? 'ri-eye-off-line' : 'ri-eye-line';
        }
      });
    });
  });
})();
