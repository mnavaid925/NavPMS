/*
 * auction.js — NavPMS Module 8 E-Auction realtime engine (vanilla JS, NO deps).
 * Shared by the BUYER live console (templates/auctions/console.html) and the
 * VENDOR bidding page (templates/auctions/bidding.html, a later phase).
 *
 * ====================== DATA-* / ELEMENT-ID CONTRACT ======================
 * Root element:
 *   id="auctionRoot"
 *     data-state-url       (REQUIRED) GET endpoint returning the live_payload JSON.
 *     data-poll-ms         (optional, default "3000") poll interval in ms.
 *     data-results-url     (optional) revealed as a link when the auction ends.
 *     data-place-bid-url   (optional) present only on the VENDOR bidding page.
 *     data-csrf            (optional) CSRF token used for the bid POST.
 *
 * live_payload JSON (always present):
 *   auction_id, auction_number, status, is_live(bool), is_finished(bool),
 *   currency, server_now(ISO), end_at(ISO|null), start_at(ISO|null),
 *   seconds_remaining(int), extension_count(int), max_extensions(int),
 *   starting_price(str), leading_price(str|null), participant_count(int),
 *   bidder_count(int), view('full'|'self'|null).
 *
 * view==='full' (BUYER) also: leaderboard=[{participant_id, vendor_id,
 *   vendor_name, rank, current_bid(str|null), bid_count, last_bid_at(ISO|null),
 *   status}]. May optionally include recent_bids=[{vendor_name, amount,
 *   placed_at(ISO), triggered_extension(bool)}] (guarded).
 * view==='self' (VENDOR) also: my_rank(int|null), my_bid(str|null), my_status,
 *   next_valid_max(str|null), and (if rank_visibility==='full') an anonymised
 *   leaderboard=[{rank, current_bid, is_me}] (NO names).
 *
 * Element IDs touched (all OPTIONAL — render() is defensive, only fills what exists):
 *   BUYER console:
 *     #countdown #leadingPrice #participantCount #bidderCount (or #activeCount)
 *     #bidCount #extensionCount #statusBadge
 *     #leaderboardBody (tbody, rebuilt) ; #recentBids (rebuilt if payload has it)
 *     #endedNotice (revealed on end) ; #resultsLink (href set from data-results-url)
 *   VENDOR bidding:
 *     #countdown #yourRank #yourBid #leadingPrice #nextMax
 *     #placeBidForm #bidAmount #bidError #bidSubmit
 *     #endedNotice #resultsLink
 *
 * All server-provided strings are written with textContent (never innerHTML) → XSS-safe.
 * Countdown ticks client-side every 1s, re-synced from server seconds_remaining each poll.
 * ==========================================================================
 */
(function () {
  'use strict';

  var root = document.getElementById('auctionRoot');
  if (!root) { return; }

  var stateUrl    = root.getAttribute('data-state-url');
  if (!stateUrl) { return; }
  var pollMs      = parseInt(root.getAttribute('data-poll-ms') || '3000', 10);
  if (isNaN(pollMs) || pollMs < 500) { pollMs = 3000; }
  var resultsUrl  = root.getAttribute('data-results-url') || '';
  var placeBidUrl = root.getAttribute('data-place-bid-url') || '';
  var csrf        = root.getAttribute('data-csrf') || '';

  var pollTimer = null;
  var tickTimer = null;
  var remaining = 0;          // client-side countdown seconds
  var lastView  = null;       // 'full' | 'self' | null
  var ended     = false;
  var currency  = '';

  // ---------- helpers ----------
  function $(id) { return document.getElementById(id); }

  function setText(id, value) {
    var el = $(id);
    if (el) { el.textContent = (value === null || value === undefined) ? '' : String(value); }
  }

  function fmtMoney(value) {
    if (value === null || value === undefined || value === '') { return '—'; }
    return (currency ? currency + ' ' : '') + value;
  }

  function fmtSeconds(total) {
    if (total === null || total === undefined || total < 0) { total = 0; }
    var s = Math.floor(total);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    if (h > 0) { return h + ':' + pad(m) + ':' + pad(sec); }
    return pad(m) + ':' + pad(sec);
  }

  function fmtTime(iso) {
    if (!iso) { return '—'; }
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return '—'; }
    return d.toLocaleTimeString();
  }

  function statusBadgeClass(status) {
    switch (status) {
      case 'draft':     return 'badge bg-secondary-subtle text-secondary-emphasis';
      case 'scheduled': return 'badge bg-info-subtle text-info-emphasis';
      case 'live':      return 'badge bg-success-subtle text-success-emphasis';
      case 'closed':    return 'badge bg-primary-subtle text-primary-emphasis';
      case 'awarded':   return 'badge bg-success-subtle text-success-emphasis';
      case 'cancelled': return 'badge bg-danger-subtle text-danger-emphasis';
      default:          return 'badge bg-light text-dark';
    }
  }

  // ---------- countdown ----------
  function renderCountdown() {
    setText('countdown', fmtSeconds(remaining));
  }

  function startTick() {
    if (tickTimer) { return; }
    tickTimer = setInterval(function () {
      if (remaining > 0) {
        remaining -= 1;
        renderCountdown();
      } else {
        stopTick();
      }
    }, 1000);
  }

  function stopTick() {
    if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
  }

  // ---------- end handling ----------
  function showEnded() {
    if (ended) { return; }
    ended = true;
    stopPoll();
    stopTick();
    remaining = 0;
    renderCountdown();
    var notice = $('endedNotice');
    if (notice) { notice.classList.remove('d-none'); }
    var link = $('resultsLink');
    if (link && resultsUrl) {
      link.setAttribute('href', resultsUrl);
      link.classList.remove('d-none');
    }
    disableBidding();
  }

  // ---------- BUYER console render ----------
  function renderBuyer(data) {
    setText('leadingPrice', fmtMoney(data.leading_price));
    setText('participantCount', data.participant_count);
    setText('bidderCount', data.bidder_count);
    setText('activeCount', data.bidder_count);
    setText('extensionCount', data.extension_count);

    var statusEl = $('statusBadge');
    if (statusEl) {
      statusEl.textContent = data.status;
      statusEl.className = statusBadgeClass(data.status);
    }

    // leaderboard rebuild
    var tbody = $('leaderboardBody');
    if (tbody) {
      var lb = data.leaderboard || [];
      var totalBids = 0;
      while (tbody.firstChild) { tbody.removeChild(tbody.firstChild); }
      if (lb.length === 0) {
        var er = document.createElement('tr');
        var ec = document.createElement('td');
        ec.setAttribute('colspan', '5');
        ec.className = 'text-center text-muted py-4';
        ec.textContent = 'No participants yet.';
        er.appendChild(ec);
        tbody.appendChild(er);
      } else {
        for (var i = 0; i < lb.length; i++) {
          var row = lb[i];
          totalBids += (row.bid_count || 0);
          var tr = document.createElement('tr');
          if (row.rank === 1) { tr.className = 'table-success'; }

          var tdRank = document.createElement('td');
          tdRank.className = 'fw-semibold';
          tdRank.textContent = (row.rank === null || row.rank === undefined) ? '—' : row.rank;
          tr.appendChild(tdRank);

          var tdName = document.createElement('td');
          tdName.textContent = row.vendor_name || '—';
          tr.appendChild(tdName);

          var tdBid = document.createElement('td');
          tdBid.className = 'text-end';
          tdBid.textContent = fmtMoney(row.current_bid);
          tr.appendChild(tdBid);

          var tdCount = document.createElement('td');
          tdCount.className = 'text-end';
          tdCount.textContent = row.bid_count || 0;
          tr.appendChild(tdCount);

          var tdLast = document.createElement('td');
          tdLast.className = 'text-end small text-muted';
          tdLast.textContent = fmtTime(row.last_bid_at);
          tr.appendChild(tdLast);

          tbody.appendChild(tr);
        }
      }
      setText('bidCount', totalBids);
    }

    // recent bids feed (only if payload includes it)
    var recentEl = $('recentBids');
    if (recentEl && data.recent_bids) {
      while (recentEl.firstChild) { recentEl.removeChild(recentEl.firstChild); }
      var rb = data.recent_bids || [];
      if (rb.length === 0) {
        var li0 = document.createElement('li');
        li0.className = 'list-group-item text-center text-muted small';
        li0.textContent = 'No bids yet.';
        recentEl.appendChild(li0);
      } else {
        for (var j = 0; j < rb.length; j++) {
          var b = rb[j];
          var li = document.createElement('li');
          li.className = 'list-group-item d-flex justify-content-between align-items-center';
          var left = document.createElement('span');
          left.textContent = (b.vendor_name || '—') + '  ' + fmtMoney(b.amount);
          li.appendChild(left);
          var right = document.createElement('span');
          right.className = 'small text-muted';
          right.textContent = fmtTime(b.placed_at) + (b.triggered_extension ? '  (+ext)' : '');
          li.appendChild(right);
          recentEl.appendChild(li);
        }
      }
    }
  }

  // ---------- VENDOR bidding render ----------
  function renderVendor(data) {
    setText('yourRank', (data.my_rank === null || data.my_rank === undefined) ? '—' : data.my_rank);
    setText('yourBid', fmtMoney(data.my_bid));
    setText('leadingPrice', fmtMoney(data.leading_price));
    setText('nextMax', fmtMoney(data.next_valid_max));

    var statusEl = $('statusBadge');
    if (statusEl) {
      statusEl.textContent = data.status;
      statusEl.className = statusBadgeClass(data.status);
    }

    // optional anonymised leaderboard (rank_visibility==='full')
    var tbody = $('leaderboardBody');
    if (tbody && data.leaderboard) {
      while (tbody.firstChild) { tbody.removeChild(tbody.firstChild); }
      var lb = data.leaderboard || [];
      for (var i = 0; i < lb.length; i++) {
        var row = lb[i];
        var tr = document.createElement('tr');
        if (row.is_me) { tr.className = 'table-primary'; }
        else if (row.rank === 1) { tr.className = 'table-success'; }

        var tdRank = document.createElement('td');
        tdRank.className = 'fw-semibold';
        tdRank.textContent = row.rank;
        tr.appendChild(tdRank);

        var tdBid = document.createElement('td');
        tdBid.className = 'text-end';
        tdBid.textContent = fmtMoney(row.current_bid);
        tr.appendChild(tdBid);

        var tdMe = document.createElement('td');
        tdMe.className = 'text-end';
        tdMe.textContent = row.is_me ? 'You' : '';
        tr.appendChild(tdMe);

        tbody.appendChild(tr);
      }
    }
  }

  function disableBidding() {
    var form = $('placeBidForm');
    if (!form) { return; }
    var input = $('bidAmount');
    var btn = $('bidSubmit');
    if (input) { input.setAttribute('disabled', 'disabled'); }
    if (btn) { btn.setAttribute('disabled', 'disabled'); }
  }

  function enableBidding() {
    var form = $('placeBidForm');
    if (!form) { return; }
    var input = $('bidAmount');
    var btn = $('bidSubmit');
    if (input) { input.removeAttribute('disabled'); }
    if (btn) { btn.removeAttribute('disabled'); }
  }

  // ---------- master render ----------
  function render(data) {
    currency = data.currency || currency;
    lastView = data.view;

    // re-sync countdown from authoritative server value
    remaining = (typeof data.seconds_remaining === 'number') ? data.seconds_remaining : 0;
    renderCountdown();

    if (data.view === 'full') {
      renderBuyer(data);
    } else if (data.view === 'self') {
      renderVendor(data);
      if (data.is_live && data.seconds_remaining > 0) { enableBidding(); }
      else { disableBidding(); }
    }

    if (data.is_live === false || data.seconds_remaining <= 0) {
      showEnded();
    } else {
      startTick();
    }
  }

  // ---------- polling ----------
  function poll() {
    fetch(stateUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
      .then(function (resp) {
        if (!resp.ok) { throw new Error('state ' + resp.status); }
        return resp.json();
      })
      .then(function (data) { render(data); })
      .catch(function () { /* transient network error — keep polling */ });
  }

  function startPoll() {
    if (pollTimer) { return; }
    pollTimer = setInterval(poll, pollMs);
  }

  function stopPoll() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  // ---------- vendor bid submit ----------
  function wireBidForm() {
    var form = $('placeBidForm');
    if (!form || !placeBidUrl) { return; }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var input = $('bidAmount');
      var btn = $('bidSubmit');
      var errEl = $('bidError');
      if (errEl) { errEl.textContent = ''; }

      var val = input ? input.value.trim() : '';
      if (!val) {
        if (errEl) { errEl.textContent = 'Enter a bid amount.'; }
        return;
      }
      if (btn) { btn.setAttribute('disabled', 'disabled'); }

      fetch(placeBidUrl, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrf,
          'Content-Type': 'application/x-www-form-urlencoded'
        },
        credentials: 'same-origin',
        body: 'amount=' + encodeURIComponent(val)
      })
        .then(function (resp) { return resp.json(); })
        .then(function (res) {
          if (res && res.ok === false) {
            if (errEl) { errEl.textContent = res.error || 'Bid rejected.'; }
            if (btn) { btn.removeAttribute('disabled'); }
          } else {
            if (errEl) { errEl.textContent = ''; }
            if (input) { input.value = ''; }
            if (btn) { btn.removeAttribute('disabled'); }
            poll();
          }
        })
        .catch(function () {
          if (errEl) { errEl.textContent = 'Network error placing bid. Try again.'; }
          if (btn) { btn.removeAttribute('disabled'); }
        });
    });
  }

  // ---------- boot ----------
  wireBidForm();
  poll();        // immediate first fetch
  startPoll();   // then interval
})();
