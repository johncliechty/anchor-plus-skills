/* The High Seat page (W1b, 2026-09-26): the page's own behaviour — the rail's destinations, the tiles that open
   and close, the cards that open a cockpit, the tools, the Add box, and the composer that talks to the steward
   through the existing say route. Nothing here invents data: every figure on the page was rendered from a record. */
(function () {
  'use strict';
  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  // John, 2026-10-04: scan small cards, hover for details, click expands here; the cockpit link opens the full view.
  function positionPeek(card) {
    var peek = $('.t-peek', card); if (!peek || !card.classList.contains('peeking')) return;
    var r = card.getBoundingClientRect(), below = Math.max(0, innerHeight - r.bottom - 8), above = Math.max(0, r.top - 8);
    peek.style.width = Math.min(r.width, innerWidth - 16) + 'px';
    peek.style.left = Math.max(8, Math.min(r.left, innerWidth - r.width - 8)) + 'px';
    peek.style.maxHeight = Math.max(1, Math.min(500, Math.max(below, above), innerHeight - 16)) + 'px';
    var up = below < Math.min(peek.scrollHeight, 200) && above > below;
    peek.style.top = up ? 'auto' : Math.max(0, r.bottom - 1) + 'px';
    peek.style.bottom = up ? Math.max(0, innerHeight - r.top - 1) + 'px' : 'auto';
  }
  function hidePeek(card) {
    card.classList.remove('peeking', 'peek-pinned');
    var trigger = $('.t-peek-open', card); if (trigger) trigger.setAttribute('aria-expanded', 'false');
    card.removeAttribute('data-open'); card.removeAttribute('data-open-dir');
    var detail = $('.t-peek-detail', card); if (detail) { detail.hidden = true; detail.innerHTML = ''; }
    $$('.t-acts button.on, .t-eff-open.on', card).forEach(function (b) { b.classList.remove('on'); });
  }
  function showPeek(card) {
    if (drag || card.classList.contains('open') || card.classList.contains('peek-dismissed')) return;
    $$('.tile.peeking').forEach(function (other) { if (other !== card && !other.contains(document.activeElement)) hidePeek(other); });
    card.classList.add('peeking'); positionPeek(card);
    var trigger = $('.t-peek-open', card); if (trigger) trigger.setAttribute('aria-expanded', 'true');
  }
  function toggleInlineTile(card) {
    if (card.classList.contains('open')) closeTile(card);
    else openTile(card, card.getAttribute('data-tile'), card.getAttribute('data-dir') || '');
  }
  function compactTiles(root) {
    $$('.tile[data-tile]', root).forEach(function (card) {
      if (card._compact || !$('.t-body', card)) return;
      card._compact = true;
      var peek = document.createElement('div'); peek.className = 't-peek';
      peek.innerHTML = '<div class="t-peek-head"><span>Details</span><button type="button" class="t-peek-close" aria-label="Close details">\u00d7</button></div>';
      ['.t-face', '.t-acts'].forEach(function (s) { var el = $(s, card); if (el) peek.appendChild(el); });
      var dialogue = document.createElement('button'); dialogue.type = 'button'; dialogue.className = 't-inline-talk'; dialogue.textContent = 'Dialogue';
      $('.t-acts', peek).appendChild(dialogue);
      dialogue.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); openTile(card, card.getAttribute('data-tile'), card.getAttribute('data-dir') || ''); });
      var detail = document.createElement('div'); detail.className = 't-peek-detail'; detail.hidden = true; peek.appendChild(detail);
      card.insertBefore(peek, $('.t-body', card));
      var trigger = document.createElement('button'); trigger.type = 'button'; trigger.className = 't-peek-open'; trigger.textContent = '\u22ef'; trigger.setAttribute('aria-label', 'Show initiative details'); trigger.setAttribute('aria-expanded', 'false');
      $('.t-top', card).insertBefore(trigger, $('.t-go', card));
      trigger.addEventListener('click', function () { if (card.classList.contains('peek-pinned')) { hidePeek(card); card.classList.add('peek-dismissed'); } else { card.classList.remove('peek-dismissed'); showPeek(card); card.classList.add('peek-pinned'); } });
      card.tabIndex = 0;
      card.setAttribute('aria-label', ($('.t-name', card).textContent || '').trim() + ': hover for details, Enter expands the dialogue here');
      card.setAttribute('aria-expanded', 'false');
      card.addEventListener('pointerenter', function (e) { if (e.pointerType === 'touch') return; card.classList.remove('peek-dismissed'); showPeek(card); });
      card.addEventListener('pointerleave', function () { card.classList.remove('peek-dismissed'); if (!card.classList.contains('peek-pinned') && !card.contains(document.activeElement)) hidePeek(card); });
      card.addEventListener('focusin', function () { showPeek(card); });
      card.addEventListener('focusout', function () { setTimeout(function () { if (!card.contains(document.activeElement) && !card.matches(':hover') && !card.classList.contains('peek-pinned')) hidePeek(card); }, 0); });
      card.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && card.classList.contains('peeking')) {
          e.preventDefault(); e.stopPropagation(); hidePeek(card); card.classList.add('peek-dismissed'); card.focus();
        } else if (e.key === 'Enter' && e.target === card) { e.preventDefault(); toggleInlineTile(card); }
      });
      $('.t-peek-close', card).addEventListener('click', function () { hidePeek(card); card.classList.add('peek-dismissed'); card.focus(); });
      card.addEventListener('dragstart', function () { hidePeek(card); card.classList.add('peek-dismissed'); });
      card.addEventListener('click', function (e) {
        if (e.target.closest('a, button, .t-body, .t-peek') || drag || card.classList.contains('dragging') || String(window.getSelection() || '').trim()) return;
        e.preventDefault(); toggleInlineTile(card);
      });
    });
  }
  // W4 (ChatGPT r2): each card remembers the record's markup it was made from, before the page decorates it - the one
  // definition of what a placement compares
  $$('.shelf.zone .grid > .tile').forEach(function (c) { c._record = c.outerHTML; });
  compactTiles(document);
  window.addEventListener('resize', function () { $$('.tile.peeking').forEach(positionPeek); });
  document.addEventListener('scroll', function () { $$('.tile.peeking').forEach(positionPeek); }, true);
  // Initiative dialogue and full cockpit bind the same project and effort. Older
  // services still emit a project-index link; keep the loaded page's door direct.
  function initiativeCockpitLinks(root) {
    $$('.tile[data-tile] a.t-go', root).forEach(function (a) {
      var card = a.closest('.tile[data-tile]');
      a.href = '/steward/v1?pid=' + encodeURIComponent(card.getAttribute('data-tile'))
        + '&dir=' + encodeURIComponent(card.getAttribute('data-dir') || '');
    });
  }
  initiativeCockpitLinks(document);
  // An older service can stay alive while its conversations finish. Read the
  // component names from the same Campaign map until its next safe activation.
  (function initiativeNames() {
    var pid = (window.ANCHOR_BOOT || {}).campaign_pid;
    if (!pid) return;
    fetch('/api/steward/map?pid=' + encodeURIComponent(pid), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('map unavailable'); return r.json(); })
      .then(function (map) {
        var names = {}; (map.steps || []).forEach(function (s) { if (s.name) names[s.id] = s.name; });
        $$('.tile[data-step][data-tile]').forEach(function (card) {
          var name = names[card.getAttribute('data-step')], label = $('.t-nm', card);
          if (!name || !label) return;
          label.textContent = name; label.title = name;
          card.setAttribute('data-name', name);
          card.setAttribute('aria-label', name + ': hover for details, Enter opens the full cockpit');
          var head = $('.t-peek-head span', card); if (head) head.textContent = name;
        });
      }).catch(function () {}); // Retain the server's last recorded labels on a failed read.
  })();
  // Keep loaded-page names and links correct while an older service finishes its active turns.
  var seatBrand = $('.masthead .mh-stew b');
  if (seatBrand && seatBrand.textContent.trim().replace(/^The /, '') === 'Cave of Wonders') {
    document.title = 'Cave of Wonders';
    seatBrand.textContent = 'Cave of Wonders';
    var cavePid = (window.ANCHOR_BOOT || {}).campaign_pid || '';
    var caveLink = $('#dialogue .exhead a.note');
    if (cavePid && caveLink) caveLink.href = '/steward/v1?pid=' + encodeURIComponent(cavePid) + '&dir=' + encodeURIComponent('Cave of Wonders');
  }
  function token() { try { return localStorage.getItem('anchor_token') || ''; } catch (e) { return ''; } }
  // the hand-off the old dashboard did: /?token=<t> stores the token for this origin and drops it from the address
  try {
    var _qs = new URLSearchParams(location.search), _t = (_qs.get('token') || '').trim();
    if (_t) {
      _qs.delete('token'); var _rest = _qs.toString(); history.replaceState(null, '', location.pathname + (_rest ? '?' + _rest : '') + location.hash);
      login(_t);   // stored, and the browser logged in (the HttpOnly cookie the page routes and the card route accept), as the old home did — the one login()
    }
  } catch (e) {}
  function headers() {
    var h = { 'Content-Type': 'application/json' };
    var t = token(); if (t) { h['X-Anchor-Token'] = t; h['Authorization'] = 'Bearer ' + t; }   // the GET card route reads Authorization or the cookie
    var b = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) || ''; if (b) h['X-Anchor-Build'] = b;
    return h;
  }
  function tokenQ() { var t = token(); return t ? ('?token=' + encodeURIComponent(t)) : ''; }
  function openWin(url) {
    try {
      if (window.top && window.top.ANCHOR_APP && typeof window.top.ANCHOR_APP.open === 'function') {
        var aw = window.top.ANCHOR_APP.open(url, '_blank', window);
        if (aw) return;
      }
    } catch (e) {}
    var w = null;
    try { w = window.open('about:blank', '_blank'); } catch (e) { w = null; }
    if (!w || w === window) { receipt('The browser blocked the new window — allow popups and try again.', true); return; }
    try { w.opener = null; w.location.replace(url); w.focus(); } catch (e) { try { w.close(); } catch (_) {} }
  }
  var YOU = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.you) || 'You';   // his name in a dialogue row, as the AI Cockpit says it (his word, 2026-10-01)
  // what he is doing now: a key or dictated text in the last ten seconds, or a box he is in with words in it
  var lastKey = 0, lastCardKey = 0; function markKey(e) { lastKey = Date.now(); if (e && e.target && e.target.closest && e.target.closest('.tile')) lastCardKey = lastKey; }
  document.addEventListener('keydown', markKey); document.addEventListener('input', markKey, true);
  function typingNow() { var a = document.activeElement; return (Date.now() - lastKey < 10000) || !!(a && a.tagName === 'TEXTAREA' && a.value && a.value.trim()) || $$('.tile.open').some(function (c) { return !!c._typing; }); }   // his words in an open tile's cockpit view count (2026-10-02)
  function tileOpen() { return !!$('.tile.open'); }   // an open terminal does not hold it: its tabs re-attach after the reload (Grok, 2026-10-02); typingNow covers his keys in it
  // W3b (his word, 2026-10-01: dictating into an open tile, "the tile collapses down and whatever I was dictating gets
  // lost"); W4 (his word, 2026-10-08: "Anchor is rebuilding AI Cockpits, I thought that was not supposed to happen for
  // the open ones"): a change to the RECORD never reloads the page - it is placed in the page as it stands (renewInPlace,
  // below). A NEW BUILD is the one thing that reloads it, and never under an open tile or his typing: it waits, says so
  // once in the open card, and finishes when the card closes and he is quiet.
  var pendingBuild = null, renewVersion = '';
  function heldLine(card) {   // said once per open card: the reload waits for it (a card he switches to hears it too - Grok W3b)
    if (!card || card._heldSaid || !card._talk || !card._talk.appendLine) return;
    card._heldSaid = true; card._talk.appendLine('sys', 'a new build is live \u2014 this page renews itself when you close the card', 'dim');
  }
  function renewBuild(text) {
    if (tileOpen() || typingNow()) { pendingBuild = text || pendingBuild || 'A new build is live \u2014 the page is renewed.'; $$('.tile.open').forEach(heldLine); return; }
    var said = text || pendingBuild || 'A new build is live \u2014 the page is renewed.'; pendingBuild = null;
    try { if (renewVersion) sessionStorage.setItem('highseat_reloaded_for', renewVersion); } catch (e) {}
    try { sessionStorage.setItem('highseat_receipt', JSON.stringify({ text: said, undo: null })); } catch (e) {}
    location.reload();
  }
  setInterval(function () { if (pendingBuild && !tileOpen() && !typingNow()) renewBuild(pendingBuild); }, 5000);
  var lastUndo = null;
  function receipt(text, bad, undo) {
    var r = $('#receipt'), t = $('#receiptText'); if (!r || !t) return;
    lastUndo = undo || null; var u = $('#undoBtn'); if (u) u.hidden = !undo;
    t.textContent = text; r.hidden = false; r.classList.toggle('bad', !!bad);
  }
  try { var keptLine = sessionStorage.getItem('highseat_receipt'); if (keptLine) { var kl = JSON.parse(keptLine); receipt(kl.text, !!kl.bad, kl.undo); sessionStorage.removeItem('highseat_receipt'); } } catch (e) {}
  var undoBtn = $('#undoBtn');
  if (undoBtn) undoBtn.addEventListener('click', function () {
    if (!lastUndo) return;
    var body = JSON.parse(JSON.stringify(lastUndo)); body.pid = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.campaign_pid) || '';
    undoBtn.disabled = true;
    fetch('/api/high-seat/campaign', { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (j) { undoBtn.disabled = false; if (!j || !j.ok) { receipt((j && j.receipt) || 'Nothing was undone.', true); return; }
        renewInPlace(j.receipt, j.undo || null); })
      .catch(function () { undoBtn.disabled = false; receipt('That did not go through — nothing was undone.', true); });
  });

  // the rail: each destination scrolls to its section and opens it
  var DEST = { seat: '#nudgeSlot', campaign: '#camp', active: '#shActive', week: '#shDated', desk: '#deskline',
               deck: '#shDeck', calendar: '#cal', email: '#cal', term: '#shTerm' };
  $$('#railNav button').forEach(function (b) {
    b.addEventListener('click', function () {
      var key = b.getAttribute('data-rail'), sel = DEST[key], el = sel && $(sel);
      // the Star Chart (his word, 2026-10-03): the rail opens its page - one tile in the app, reused when open
      var camp = (window.ANCHOR_BOOT || {}).campaign_pid;
      if (key === 'campaign' && camp) { window.open('/project/' + camp, '_blank'); return; }
      $$('#railNav button').forEach(function (x) { x.classList.toggle('on', x === b); });
      if (!el) return;
      if (key === 'campaign') $('#camp') && $('#camp').classList.add('open');
      if (key === 'calendar' || key === 'email') {
        $('#cal') && $('#cal').classList.add('open');
        setCalTab(key === 'email' ? 'mail' : 'cal');
        var calEl = $('#cal'), cmEl = $('#caveCommsConnectModal');
        if (calEl && cmEl && calEl.getAttribute('data-connected-count') === '0') { cmEl.hidden = false; }
      }
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  // W2c (2026-09-30, his three levels): the goals as a thin tile that expands (each goal a row that opens to its
  // components); Active and On deck as shelves of initiative cards; a drag out of a goal, between the shelves, up and
  // down inside one, or back onto the goals tile; the × sends one home; a registry project dropped on a goal becomes
  // its component. Every move is ONE act on the Campaign record with one line and undo; the page reloads to the
  // record as it stands, the receipt kept.
  // the heads are delegated (W4): a section placed again in the page keeps its toggle
  var camp = $('#camp');
  function setCamp(open) { if (!camp) return; camp.classList.toggle('open', open); var t = $('#campTog'); if (t) t.textContent = open ? 'Collapse' : 'Expand'; }
  // the Desk's one line (2026-10-06): the same pattern - the head toggles the rows in the page, the link opens the Desk
  function setDesk(open) { var desk = $('#deskline'), t = $('#deskTog'); if (!desk || !t) return; desk.classList.toggle('open', open); t.textContent = open ? 'Collapse' : 'Expand'; }
  document.addEventListener('click', function (e) {
    var drillBtn = e.target.closest && e.target.closest('[data-cos-drill]');
    if (drillBtn) {
      e.preventDefault();
      var col = drillBtn.getAttribute('data-cos-drill') || 'today';
      var bodyEl = document.getElementById('cosExpandableBody');
      var isAlreadyOpen = bodyEl && !bodyEl.hidden;
      var wasActive = drillBtn.classList.contains('active-drill');
      if (isAlreadyOpen && wasActive) {
        _setCosBodyExpanded(false, '');
      } else {
        _setCosBodyExpanded(true, col);
      }
      return;
    }

    var toggleBodyBtn = e.target.closest && e.target.closest('[data-cos-toggle-body]');
    if (toggleBodyBtn && !e.target.closest('a')) {
      e.preventDefault();
      var bEl = document.getElementById('cosExpandableBody');
      var nowOpen = bEl ? bEl.hidden : true;
      _setCosBodyExpanded(nowOpen, nowOpen ? 'today' : '');
      return;
    }

    if (e.target.closest('#campHead') && !e.target.closest('a')) { setCamp(!camp.classList.contains('open')); return; }
    if (e.target.closest('#deskHead') && !e.target.closest('a, button')) { setDesk(!$('#deskline').classList.contains('open')); return; }
    var h = e.target.closest('.grow .gh'); if (h && !e.target.closest('a, button')) h.parentNode.classList.toggle('open');
  });
  var CAMPAIGN = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.campaign_pid) || '';
  var acting = false;
  function act(body) {   // one act in flight; the receipt and its undo stay on the page, the change is placed in it (W4)
    if (acting || !CAMPAIGN) return; acting = true; body.pid = CAMPAIGN;
    fetch('/api/high-seat/campaign', { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { if (r.status === 401 || r.status === 403) { return { ok: false, receipt: NOT_LOGGED_IN }; } return r.json(); })
      .then(function (j) {
        acting = false;
        if (!j || !j.ok) {
          // the act landed in part and the writer refused the rest: the receipt says so and its undo is his
          if (j && j.undo) { renewInPlace(j.receipt || 'Refused.', j.undo, true); return; }
          receipt((j && j.receipt) || 'Nothing was done.', true); return;
        }
        renewInPlace(j.receipt, j.undo || null);
      })
      .catch(function () { acting = false; receipt('That did not go through — nothing was done.', true); });
  }
  document.addEventListener('click', function (e) {
    var s = e.target.closest('[data-seat][data-step]');
    if (s) { e.preventDefault(); e.stopPropagation(); act({ act: 'seat', step: s.getAttribute('data-step'), seat: s.getAttribute('data-seat') }); return; }
    var h = e.target.closest('[data-home]');
    if (h) { e.preventDefault(); e.stopPropagation(); act({ act: 'home', step: h.getAttribute('data-home') }); return; }
    // a candidate not yet on the Campaign: on the map and in the seat in one act (2026-10-02)
    var c = e.target.closest('[data-cand-seat]');
    if (c) { e.preventDefault(); e.stopPropagation(); act({ act: 'seat_new', ref: c.getAttribute('data-ref'), name: c.getAttribute('data-name'), seat: c.getAttribute('data-cand-seat') }); }
  });
  // the Candidates: a search and a sort (his word, 2026-10-02: by date created, last date worked on, the steward's relevance)
  var candApply = function () {};

  function measureNaturalTextWidth(el) {
    if (!el) return 0;
    var prevDisplay = el.style.display;
    var prevWidth = el.style.width;
    el.style.display = 'inline-block';
    el.style.width = 'auto';
    var w = el.scrollWidth || el.offsetWidth || 0;
    el.style.display = prevDisplay;
    el.style.width = prevWidth;
    return w;
  }

  function syncCompactActs() {
    // Switch to compact dots SOONER rather than later: keep at least 96px of breathing room
    // after the cockpit name (and collapse whenever the tile is under 520px wide) so names
    // never get cramped or close to truncating before the blue/green dots + arrow appear.
    var SAFETY_BUFFER_PX = 96;
    var MIN_FULL_BTN_TILE_WIDTH = 520;
    $$('.tile').forEach(function (tile) {
      var nmWrap = tile.querySelector('.t-name');
      var nm = tile.querySelector('.t-name .t-nm') || nmWrap;
      var eff = tile.querySelector('.t-name .t-eff');
      if (!nm || !nmWrap) return;
      tile.classList.remove('compact-acts');
      var availW = nmWrap.clientWidth || 0;
      var nmW = measureNaturalTextWidth(nm);
      var effW = measureNaturalTextWidth(eff);
      var earlyCrowd = (nmW + SAFETY_BUFFER_PX > availW) || (effW > 0 && (effW + SAFETY_BUFFER_PX > availW));
      var nmTrunc = (nm.scrollWidth > nm.clientWidth + 1);
      var effTrunc = eff ? (eff.scrollWidth > eff.clientWidth + 1) : false;
      if (earlyCrowd || nmTrunc || effTrunc || tile.clientWidth < MIN_FULL_BTN_TILE_WIDTH) {
        tile.classList.add('compact-acts');
      }
    });
  }
  window.addEventListener('resize', syncCompactActs);
  setTimeout(syncCompactActs, 0);
  setTimeout(syncCompactActs, 150);

  function bindCands() {   // at load, and when the tile is placed in the page for the first time (W4)
    syncCompactActs();
    var q = document.getElementById('candSearch'), srt = document.getElementById('candSort'), note = document.getElementById('candNote'), fltWrap = document.getElementById('candFilter');
    if (!q || !srt || q._bound) return; q._bound = true;
    var kflt = 'all';
    try { var ks = sessionStorage.getItem('hs_cands_sort'); if (ks) srt.value = ks; q.value = sessionStorage.getItem('hs_cands_q') || ''; kflt = sessionStorage.getItem('hs_cands_kflt') || 'all'; } catch (e) {}
    function syncFltBtns() {
      if (!fltWrap) return;
      $$('.cand-flt', fltWrap).forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-cand-filter') === kflt); });
    }
    syncFltBtns();
    function apply() {
      var term = q.value.trim().toLowerCase(), key = srt.value, shown = 0, all = 0;
      $$('#shCands .cand-group').forEach(function (grp) {
        var ul = grp.querySelector('ul'); if (!ul) return;
        var rows = $$('li.cand', ul), grpShown = 0;
        rows.sort(function (a, b) {
          if (key === 'name') return a.querySelector('.cn').textContent.localeCompare(b.querySelector('.cn').textContent);
          var va = key === 'score' ? +a.getAttribute('data-score') : (a.getAttribute('data-' + key) || ''), vb = key === 'score' ? +b.getAttribute('data-score') : (b.getAttribute('data-' + key) || '');
          return va < vb ? 1 : va > vb ? -1 : 0;   // newest, or most relevant, first
        });
        rows.forEach(function (r) {
          ul.appendChild(r); all++;
          var kindOk = (kflt === 'all') || ((r.getAttribute('data-cand-kind') || 'cockpit') === kflt);
          var hit = (!term || r.textContent.toLowerCase().indexOf(term) >= 0) && kindOk;
          r.hidden = !hit; if (hit) { shown++; grpShown++; }
        });
        grp.hidden = (grpShown === 0) && (!!term || kflt !== 'all');
      });
      if (note) note.textContent = (term || kflt !== 'all') ? (shown + ' of ' + all) : '';
      try { sessionStorage.setItem('hs_cands_sort', key); sessionStorage.setItem('hs_cands_q', q.value); sessionStorage.setItem('hs_cands_kflt', kflt); } catch (e) {}
    }
    q.addEventListener('input', apply); srt.addEventListener('change', apply);
    if (fltWrap) {
      fltWrap.addEventListener('click', function (ev) {
        var b = ev.target.closest('.cand-flt'); if (!b) return;
        kflt = b.getAttribute('data-cand-filter') || 'all';
        syncFltBtns(); apply();
      });
    }
    candApply = apply;
    syncCompactActs();
    if (q.value || srt.value !== 'score' || kflt !== 'all') apply();
    // the Candidates tile stays open across a reload (2026-10-02)
    var t = document.getElementById('candsTile'); if (!t) return;
    try { if (sessionStorage.getItem('hs_cands_open') === '1') t.open = true; } catch (e) {}
    t.addEventListener('toggle', function () { try { sessionStorage.setItem('hs_cands_open', t.open ? '1' : '0'); } catch (e) {} });
  }
  bindCands();
  // the drags: a card or a goal's initiative (data-step) onto a shelf — its place among the cards — or onto the goals
  // tile (home); a registry project (data-proj) onto a goal's row (a component of that goal)
  var drag = null;
  function bindDrags(root) {   // at load, and on what W4 places in the page (once per element)
    var sel = '[draggable="true"][data-step], [draggable="true"][data-proj]', els = $$(sel, root);
    if (root.matches && root.matches(sel)) els.unshift(root);
    els.forEach(function (el) {
      if (el._dragBound) return; el._dragBound = true;
      el.addEventListener('dragstart', function (e) {
        drag = { step: el.getAttribute('data-step') || '', proj: el.getAttribute('data-proj') || '', name: (el.getAttribute('data-name') || el.textContent || '').trim() };
        el.classList.add('dragging'); try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', drag.step || drag.proj); } catch (_) {}
      });
      el.addEventListener('dragend', function () { el.classList.remove('dragging'); $$('.over').forEach(function (z) { z.classList.remove('over'); }); drag = null; });
    });
  }
  bindDrags(document);
  $$('.zone[data-seat]').forEach(function (z) {
    z.addEventListener('dragover', function (e) { if (!drag || !drag.step) return; e.preventDefault(); try { e.dataTransfer.dropEffect = 'move'; } catch (_) {} z.classList.add('over'); });
    z.addEventListener('dragleave', function (e) { if (!z.contains(e.relatedTarget)) z.classList.remove('over'); });
    z.addEventListener('drop', function (e) {
      e.preventDefault(); z.classList.remove('over'); if (!drag || !drag.step) return;
      // the card dropped before, found on screen; the position sent is that card's place in the RECORD's order of this
      // shelf (W4, ChatGPT r1-r2: an open card the record moved is still drawn where it was, never counted)
      var cards = $$('.grid > .tile', z).filter(function (c) { return c.getAttribute('data-step') !== drag.step && !c._leaving; }), before = null;
      for (var j = 0; j < cards.length; j++) { var b = cards[j].getBoundingClientRect(); if (e.clientY < b.top || (e.clientY <= b.bottom && e.clientX < b.left + b.width / 2)) { before = cards[j]; break; } }
      var order = (z._order || cards.map(function (c) { return c.id; })).filter(function (id) { var c = document.getElementById(id); return !c || c.getAttribute('data-step') !== drag.step; });
      var k = before ? order.indexOf(before.id) : order.length; if (k < 0) k = order.length;
      act({ act: 'seat', step: drag.step, seat: z.getAttribute('data-seat'), position: k });
    });
  });
  if (camp) {
    function seatedSource() { return !!(drag && drag.step && $('.tile[data-step="' + drag.step + '"], .irow.seated[data-step="' + drag.step + '"]')); }
    camp.addEventListener('dragover', function (e) {
      if (!drag) return; var g = e.target.closest('.grow');
      if (drag.proj ? false : !seatedSource()) return;   // an orphan may be dropped anywhere on the tile: a row adds it; the head answers with a line
      e.preventDefault(); try { e.dataTransfer.dropEffect = 'move'; } catch (_) {} (g || camp).classList.add('over');
    });
    camp.addEventListener('dragleave', function (e) { var g = e.target.closest('.grow'); if (g && !g.contains(e.relatedTarget)) g.classList.remove('over'); if (!camp.contains(e.relatedTarget)) camp.classList.remove('over'); });
    camp.addEventListener('drop', function (e) {
      e.preventDefault(); $$('.over').forEach(function (z) { z.classList.remove('over'); }); if (!drag) return;
      var g = e.target.closest('.grow');
      if (drag.proj) { if (g) act({ act: 'add', initiative: g.getAttribute('data-g'), kind: 'project', text: drag.name, project_id: drag.proj }); else receipt('Open the goals (Expand), then drop it on one goal.', true); return; }
      if (seatedSource()) act({ act: 'home', step: drag.step });
    });
  }

  // W3 (2026-10-01): the steward's nudge - one click is one act on the record (seat · promote · not now, with undo);
  // "open" is a plain link; nothing moves without the click
  document.addEventListener('click', function (e) {   // delegated (W3b): a nudge re-rendered in place keeps its click
    var b = e.target.closest('[data-nudge-act]'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    var k = b.getAttribute('data-nudge-act');
    if (k === 'seat') act({ act: 'seat', step: b.getAttribute('data-step'), seat: b.getAttribute('data-seat') });
    else if (k === 'promote') act({ act: 'promote', seed: b.getAttribute('data-seed'), tier: parseInt(b.getAttribute('data-tier') || '2', 10), area: '', done_when: b.getAttribute('data-done-when') || '' });
    else if (k === 'not_now') act({ act: 'not_now', key: b.getAttribute('data-key'), fact: b.getAttribute('data-fact'), text: b.getAttribute('data-text') });
    else if (k === 'resume_done') act({ act: 'resume_done' });
  });
  // the interrupt lane's open (2026-10-03): keep the ready-to-resume note of what he is on, then follow the link
  document.addEventListener('click', function (e) {
    var a = e.target.closest('[data-lane-open]'); if (!a || !CAMPAIGN) return;
    var lane = a.closest('#lane'), note = lane ? lane.getAttribute('data-note') : '';
    if (!note) return;
    try {
      fetch('/api/high-seat/campaign', { method: 'POST', headers: headers(), keepalive: true,
        body: JSON.stringify({ pid: CAMPAIGN, act: 'resume', note: note, switched_to: a.getAttribute('data-switched') || '' }) }).catch(function () {});
    } catch (err) {}
  });
  // the Projects tile and its folders
  var ptile = $('#ptile'), ptileTog = $('#ptileTog');
  var ptileLoaded = false;
  function setPtile(open) {
    if (!ptile) return; ptile.classList.toggle('open', open); if (ptileTog) ptileTog.textContent = open ? 'Hide' : 'Show all';
    // the list is built on the server when he first opens it (2026-10-02: it cost every load its 25 tiles' reads)
    if (open && !ptileLoaded && $('#ptileLoading')) { $('#ptileLoading').textContent = 'reading the projects…'; loadFolders(); }
  }
  function loadFolders() {   // the first Show all, and again when a change to the record lands while the list is loaded (W4)
    ptileLoaded = true;
    fetch('/api/high-seat/projects', { headers: window.StewardDialogue ? window.StewardDialogue.authHeaders(headers()) : headers() })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var f = $('#folders'); if (!(f && j && j.html)) return;
        if (f.contains(document.activeElement) || $('.tile.open', f)) { placeSkipped = true; return; }   // placed when he leaves it
        // the folders he opened stay open (ChatGPT W4 r4), known by their head's words
        var opened = $$('.rnd-folder:not(.rnd-collapsed)', f).map(function (d) { return d.getAttribute('data-group'); });
        f.innerHTML = j.html; initiativeCockpitLinks(f); compactTiles(f);
        $$('.rnd-folder', f).forEach(function (d) {
          if (opened.indexOf(d.getAttribute('data-group')) < 0) return;   // known by its folder, never its rendered words
          d.classList.remove('rnd-collapsed'); var tw = $('.rnd-tw', d); if (tw) tw.textContent = '\u25BE';
        });
      })
      .catch(function () { ptileLoaded = false; var l = $('#ptileLoading'); if (l) l.textContent = 'the list could not be read - press Show all again'; });
  }
  var ptileToggle = $('#ptileToggle'); if (ptileToggle) ptileToggle.addEventListener('click', function () { setPtile(!ptile.classList.contains('open')); });
  // the old dashboard's list inside the tile: its folder heads and rows call these two by name (every folder starts closed)
  window.rndToggleFolder = function (head) {
    var f = head && head.closest('.rnd-folder'); if (!f) return;
    var closed = f.classList.toggle('rnd-collapsed');
    var tw = head.querySelector('.rnd-tw'); if (tw) tw.textContent = closed ? '\u25B8' : '\u25BE';   // the arrow turns, as the old page's does; nothing remembered
  };
  window.openProjectWindow = function (pid) { if (pid) openWin('/project/' + pid); };

  // the cards open in place (W2; the compact card, 2026-09-27): Status · Next steps · Deliverables · Plan in the acts
  // row — each part is composed on the server from the cockpit's own readers, so the card says what the cockpit says.
  // The GET card route reads the auth cookie or an Authorization header; a browser that never took the /?token=
  // hand-off has neither, the route answers 401, and the card SAYS so in words and asks for the token once, as the
  // old home did: store it, log the browser in (POST /api/auth/login mints the cookie), read the part again.
  var NOT_LOGGED_IN = 'This browser is not logged in to Anchor, so the record cannot be read.';
  var askedOnce = false;
  // R14 (2026-09-29): the token is pasted INTO the page (no window.prompt \u2014 a browser that suppresses dialogs showed
  // nothing); the box's script is the dialogue module's, one for both pages (Grok's read of W2e-3). askToken() shows the
  // box and answers false at once; a successful login reloads the page, which then reads every card with the cookie.
  // W4 (ChatGPT r1): a login here is taken in place too - an open card is never reloaded by it
  var loginUi = window.StewardDialogue ? window.StewardDialogue.loginBox({ receiptKey: 'highseat_receipt', onLogin: function () {
    if (window.ANCHOR_BOOT) window.ANCHOR_BOOT.logged_in = true;
    var lb = $('#loginBox'); if (lb) lb.hidden = true;
    renewInPlace('Logged in. This browser holds the token now.'); refreshFeedback();
    if (dlg && dlg.resume) dlg.resume();   // the Cave's dialogue hears the steward again (ChatGPT W4 r2)
    $$('.tile[data-tile]').forEach(function (c) {   // and the cards' views and briefs refused before it (ChatGPT W4 r4)
      [c._talk, c._warmTalk].forEach(function (tk) { if (tk && tk.retry) tk.retry(); });
      if (c.classList.contains('open')) refreshTile(c, c.getAttribute('data-tile'), openDir(c));
    });
  } }) : null;
  function login(t) { return loginUi ? loginUi.login(t) : Promise.resolve(null); }
  function showLogin(text) { if (loginUi) loginUi.show(text); }
  // W2c-4 (his word, 2026-09-30): a browser the server already knows by its login cookie is logged in — no box, even with no token held here
  if (window.ANCHOR_BOOT && window.ANCHOR_BOOT.auth_required && !token() && !window.ANCHOR_BOOT.logged_in) showLogin('No login found in this browser at load: no cookie came with the page and no token is saved here.');   // the box says which check raised it (2026-10-01)
  // a held token may be the OLD one (after a rotation): check it once on load; a refusal opens the box at once
  if (window.ANCHOR_BOOT && window.ANCHOR_BOOT.auth_required && token()) {
    login(token()).then(function (r) {
      if (r && r.status === 401) { try { localStorage.removeItem('anchor_token'); } catch (e) {} if (!(window.ANCHOR_BOOT && window.ANCHOR_BOOT.logged_in)) showLogin('Your saved token is out of date — paste the current one.'); }   // a page already logged in by its cookie drops the stale token and says nothing (Grok's review)
    });
  }
  function askToken() {
    showLogin('A read of the record was refused: this browser is not logged in.');
    return Promise.resolve(false);
  }
  function notLoggedIn() { return '<div class="cp-quiet cp-auth">' + NOT_LOGGED_IN + ' <button class="mini" data-login>paste the token</button></div>'; }
  function fetchPart(pid, part, dir, retried, open) {
    // W0 (2026-09-28): `open=1` only when a card's BODY opens — the presence writer's signal; a balloon's glance sends none
    return fetch('/api/high-seat/card?pid=' + encodeURIComponent(pid) + '&part=' + encodeURIComponent(part) + '&dir=' + encodeURIComponent(dir || '') + (open ? '&open=1' : ''), { headers: window.StewardDialogue ? window.StewardDialogue.authHeaders(headers()) : headers() })
      .then(function (r) {
        if (r.status === 401 || r.status === 403) {
          if (retried || askedOnce) return notLoggedIn();
          askedOnce = true;
          return askToken().then(function (ok) { return ok ? fetchPart(pid, part, dir, true) : notLoggedIn(); });
        }
        return r.json().then(function (jr) { return (jr && jr.html) || ('<div class="cp-quiet">' + ((jr && jr.error) || 'Nothing came back.') + '</div>'); });
      });
  }
  // Refinement 3 (John, 2026-10-04): looking is not answering or accepting. The unresolved
  // request/review, rather than a browser's seen marker, owns the flashing amber edge.
  function seen(card) {}
  function paintReady(card, ready, why) {
    card.classList.toggle('ready', !!ready);
    if (ready) { card.setAttribute('data-ready', 'pending'); card.setAttribute('data-attention', why || 'needs your attention'); }
    else { card.removeAttribute('data-ready'); card.removeAttribute('data-attention'); }
    var l = $('.tlight', card);
    if (l) { l.setAttribute('role', 'img'); l.setAttribute('aria-label', (l.title || 'idle') + (ready ? '; ' + (why || 'needs your attention') : '')); }
  }
  $$('.tile[data-ready]').forEach(function (c) { paintReady(c, true, 'needs your attention'); });
  // W2e-2 (2026-09-30, his word on the W2e preview): the tile OPENS to its decision brief — what waits on him, the
  // decision with the recommendation and one Accept, the material to review, the next step — and its dialogue, a
  // small window always there that grows to take the tile when a dialogue starts; the acts add a detail under the
  // brief. The dialogue is the same module the pages use, on THAT cockpit's stream; it stops when the tile closes.
  // W2e-4 (his word, 16:0x): the dialogue is a THIN strip under the card and the rectangle \u2014 the steward's state and the
  // last turn's gist (the context first) \u2014 that expands on a click, his send, "talk about it", Accept, or the steward at work
  // the persona driving it, by name (his word 2026-10-02: "Aladdin or Jarvis depending on which one is driving it")
  var STEWARD_NAME = String((window.ANCHOR_BOOT && window.ANCHOR_BOOT.steward) || 'The steward').replace(/[<>&"']/g, '');
  // 2026-10-02 (his word: "if I had both open I'd be able to see exactly the same information flowing into the dialog
  // ... and the status bar should be doing the same thing in both"; ChatGPT's diagnosis in review/CODEX-TILE-PARITY):
  // the open tile's conversation IS the cockpit's own view of this effort - /steward/v1?view=tile, the same renderer,
  // the same engine stream, with Plan and Status in the full cockpit (John, 2026-10-04), not a second copy that drifted (it cleared its list under a live
  // reply, skipped a reply in flight, cut turns at 1600 characters, merged the blocks and never showed the status).
  // The tile hears the view through a bridge scoped to this instance and this origin: state (the light and the chip),
  // the last turn (the bar's one line), the record's stamp (the brief re-read), typing (the page never renews under his
  // words), files dropped on the view, ready (a held "talk about it" goes in).
  var TILE_SEQ = 0;
  function talkHtml(id) {
    return '<div class="cdlg big" id="' + id + '"><button class="dlg-bar" type="button" aria-expanded="true" title="fold or open the conversation"><span class="dlg-h">' + STEWARD_NAME + ' — this cockpit</span><span class="exstate" data-state="">…</span><span class="dlg-gist">reading the conversation…</span><span class="dlg-caret">&#9662;</span></button>'
      + '<div class="cframe-wrap"><iframe class="cframe" title="' + STEWARD_NAME + ' — this cockpit’s conversation"></iframe></div></div>';
  }
  function grow(card) {
    var d = $('.cdlg', card); if (!d) return;
    d.classList.remove('thin'); d.classList.add('big'); var bar = $('.dlg-bar', d); if (bar) bar.setAttribute('aria-expanded', 'true'); card.classList.add('talking');
    rememberTile(card, true);
    setTimeout(function () { try { d.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (e) {} }, 120);
  }
  function shrink(card) { var d = $('.cdlg', card); if (d) { d.classList.add('thin'); d.classList.remove('big'); var bar = $('.dlg-bar', d); if (bar) bar.setAttribute('aria-expanded', 'false'); } card.classList.remove('talking'); rememberTile(card, false); }
  function startTalk(card, pid, dir) {
    var id = 'talk-' + card.id, d = $('#' + id), bar = $('#' + id + ' .dlg-bar'), chip = $('#' + id + ' .exstate'), gist = $('#' + id + ' .dlg-gist'), frame = $('#' + id + ' .cframe');
    if (!d || !frame) return;
    var inst = 't' + (++TILE_SEQ) + '-' + Date.now().toString(36), ready = false, held = [], heard = false;
    var warm = !!card._prewarm, shown = !warm;   // a preloaded Active card's view waits parked until he opens the card
    // the words he dictated into the old tile box come back in the cockpit's own box once (its draft key is the cockpit's)
    try {
      var oldKey = 'anchor:draft:tile:' + pid + ':' + (dir || ''), newKey = 'anchor:draft:say:' + pid + ':' + (dir || '') + ':tile', kept = localStorage.getItem(oldKey), there = localStorage.getItem(newKey) || '';
      if (kept && kept.trim()) localStorage.setItem(newKey, there.trim() && there.trim() !== kept.trim() ? there.replace(/\s+$/, '') + '\n\n' + kept : kept);   // both kept when they differ (ChatGPT)
      localStorage.removeItem(oldKey);
    } catch (e) {}
    function post(kind, data) {
      var m = { proto: 'anchor-tile', inst: inst, kind: kind }; for (var k in (data || {})) m[k] = data[k];
      if (!ready) { held.push(m); return; }
      try { frame.contentWindow.postMessage(m, location.origin); } catch (e) {}
    }
    function onMsg(ev) {
      var m = ev.data;
      if (ev.origin !== location.origin || ev.source !== frame.contentWindow || !m || m.proto !== 'anchor-tile' || m.inst !== inst) return;
      if (m.kind === 'ready') { ready = true; var q = held; held = []; q.forEach(function (x) { try { frame.contentWindow.postMessage(x, location.origin); } catch (e) {} }); if (warm) post(shown ? 'show' : 'park'); return; }   // a reloaded preloaded view hears where it stands
      if (m.kind === 'state') {
        card._feedbackEpoch = (card._feedbackEpoch || 0) + 1;
        if (typeof m.ready === 'boolean') paintReady(card, m.ready, m.reason || (m.ready ? 'needs your attention' : ''));
        paintDot(card, m.light);
        if (chip) { chip.textContent = m.word || (m.busy ? 'working…' : (m.alive ? 'listening' : 'parked')); chip.setAttribute('data-state', m.busy ? 'busy' : (m.alive ? 'idle' : 'parked')); }   // the cockpit's own word (ChatGPT 2026-10-02)
        heard = true;
        return;
      }
      if (m.kind === 'trouble' && gist) { gist.textContent = String(m.text || 'the cockpit view could not read its record'); return; }
      if (m.kind === 'turn' && gist) { gist.textContent = (m.who === 'you' ? YOU : STEWARD_NAME) + ': ' + String(m.text || '').replace(/\s+/g, ' ').trim().slice(-200); return; }
      if (m.kind === 'stamp') { refreshTile(card, pid, dir); return; }
      if (m.kind === 'typing') { card._typing = !!m.active; return; }
      if (m.kind === 'drop' && m.files && m.files.length) { dropFiles(card, pid, m.files); return; }
    }
    window.addEventListener('message', onMsg);
    // a frame that loads a new document must say ready again before a prefill goes in (ChatGPT 2026-10-02); a view
    // that never reports its state within 20 s is said, not left at "reading"
    frame.addEventListener('load', function () { ready = false; });
    function watch() { setTimeout(function () { if (!heard && card._talk && gist) gist.textContent = 'the cockpit view has not answered - open the cockpit, or log in on this page'; }, 20000); }
    if (bar) bar.addEventListener('click', function (e) { e.stopPropagation(); if (d.classList.contains('thin')) grow(card); else shrink(card); });
    frame.src = '/steward/v1?embed=1&view=tile&inst=' + encodeURIComponent(inst) + '&pid=' + encodeURIComponent(pid) + '&dir=' + encodeURIComponent(dir || '') + (warm ? '&parked=1' : '');
    var talk = {
      dir: dir || '',
      prefill: function (text, focus) { grow(card); post('prefill', { text: text, focus: !!focus }); },
      show: function () { shown = true; post('show'); watch(); },
      park: function () { shown = false; card._typing = false; post('park'); },
      stop: function () { window.removeEventListener('message', onMsg); ready = false; held = []; card._typing = false; if (card._warmTalk === talk) card._warmTalk = null; try { frame.src = 'about:blank'; } catch (e) {} },
      // a view that never answered (it was refused before a login) loads again; one that answered is never touched
      retry: function () { if (heard) return; ready = false; try { frame.src = frame.src; } catch (e) {} }
    };
    if (warm) card._warmTalk = talk; else { card._talk = talk; watch(); }
  }
  // 2026-10-06 (his word: "if the tile is up on the top row, can't we keep the memory open/available so that it loads
  // instantly when I click on the tile"): an Active card's cockpit view loads in the background shortly after the page
  // is idle, one card every 1.5 s, into the card's CLOSED body - hidden by the body's own hidden attribute (no display
  // rule reaches a closed card's .t-body; the CSS pins [hidden] to none) and parked, so it holds no long-poll. Opening
  // the card reveals that view; closing hides it again. On deck and every other card load on the click, as before.
  var WARM_MAX = 8;   // a bound on the frames held, not a refusal: the rest of a wide Active row loads on the click
  function warmTile(card) {
    var body = $('.t-body', card), boot = window.ANCHOR_BOOT || {};
    if (!body || card._warmTalk || card.classList.contains('open') || !card.closest('#shActive')) return;
    if (boot.auth_required && !boot.logged_in && !token()) return;   // a browser that cannot read the record preloads nothing
    if ($$('#shActive .tile[data-tile]').filter(function (c) { return !!c._warmTalk; }).length >= WARM_MAX) return;
    body.innerHTML = talkHtml('talk-' + card.id); body.hidden = true;
    card._prewarm = true;
    try { startTalk(card, card.getAttribute('data-tile'), card.getAttribute('data-dir') || ''); } finally { card._prewarm = false; }
  }
  function warmActive() {
    var cards = $$('#shActive .tile[data-tile]').filter(function (c) { return !!$('.t-body', c); }).slice(0, WARM_MAX), i = 0;
    (function next() { if (i >= cards.length) return; warmTile(cards[i++]); setTimeout(next, 1500); })();
  }
  function warmWhenIdle() { setTimeout(function () { if (window.requestIdleCallback) window.requestIdleCallback(warmActive, { timeout: 3000 }); else warmActive(); }, 1500); }
  if (document.readyState === 'complete') warmWhenIdle(); else window.addEventListener('load', warmWhenIdle);
  function stopTalk(card) { if (card._talk && card._talk.stop) card._talk.stop(); card._talk = null; }
  // W2e-6 (his ask, 19:0x): a file dropped on the OPEN tile lands in the folder of the cockpit the tile was opened on
  // (the project's root, or the effort's directory), through the cockpit's own upload verb - never overwriting; the
  // result is one line in the tile and in its dialogue. A file dropped anywhere else never navigates the page away.
  function dropHtml() {
    return '<div class="cdrop"><span class="k">Files</span><span class="cd-text">drop a file anywhere on this open card \u2014 it lands in this cockpit\u2019s folder, never overwriting</span><span class="cd-note"></span></div>';
  }
  function isFileDrag(e) { var t = e.dataTransfer && e.dataTransfer.types; if (!t) return false; for (var i = 0; i < t.length; i++) { if (t[i] === 'Files') return true; } return false; }
  function openDir(card) { return card.getAttribute('data-open-dir') !== null ? card.getAttribute('data-open-dir') : (card.getAttribute('data-dir') || ''); }
  function dropNote(card, text, bad) {
    var n = $('.cd-note', card); if (n) { n.textContent = text; n.classList.toggle('bad', !!bad); }
  }
  function dropFiles(card, pid, files) {
    var dir = openDir(card), name = (card.getAttribute('data-name') || $('.t-nm', card).textContent || 'this cockpit').trim();
    var list = Array.prototype.slice.call(files || []); if (!list.length) return;
    (function next(i) {
      if (i >= list.length) return;
      var f = list[i];
      if (f.size > 250000000) { dropNote(card, f.name + ' is over 250 MB \u2014 not loaded', true); next(i + 1); return; }
      var r = new FileReader();
      r.onerror = function () { dropNote(card, f.name + ' could not be read', true); next(i + 1); };
      r.onload = function () {
        var b64 = String(r.result).split(',')[1] || '';
        fetch('/api/steward/upload', { method: 'POST', headers: headers(), body: JSON.stringify({ pid: pid, dir: dir, name: f.name, data_b64: b64, mode: 'new', sub: '' }) })
          .then(function (res) { return res.json().catch(function () { return {}; }); })
          .then(function (j) {
            if (j && j.ok) dropNote(card, 'loaded ' + f.name + ' into ' + name + (dir ? ' \u00b7 ' + dir : '') + ' \u2014 the cockpit\u2019s folder', false);
            else if (j && j.exists) dropNote(card, f.name + ' is already there \u2014 nothing overwritten', true);
            else dropNote(card, ((j && j.error) || 'not loaded') + ' (' + f.name + ')', true);
          })
          .catch(function () { dropNote(card, f.name + ' did not go through \u2014 not loaded', true); })
          .then(function () { next(i + 1); });
      };
      r.readAsDataURL(f);
    })(0);
  }
  document.addEventListener('dragover', function (e) { if (isFileDrag(e) && !drag) e.preventDefault(); });
  document.addEventListener('drop', function (e) {
    if (!isFileDrag(e) || drag) return;
    e.preventDefault();
    if (!e.target.closest('.tile.open')) receipt('Open a card first, then drop the file on it \u2014 it lands in that cockpit\u2019s folder.', true);
  });
  // W2e-8 (his word, 19:2x: "status for the expanded tile is not keeping up"): when the cockpit's record moves (the stamp
  // the stream carries - the same signal the cockpit page repaints on), the open tile re-reads itself in place: the brief
  // (the ask, the To review line), the open act's detail, and every card's own lines and light from ONE fresh render of
  // the page. Never a page reload: the conversation and the open tile stay as they are.
  // 2026-10-07 (John, evidence E5: the open card's box moved while he dictated): while he is typing or dictating -
  // a key in this page, words in a box, a card whose cockpit view reports typing, or focus inside a card's frame
  // (Win+H types into the frame, whose keys never reach this page) - nothing in the card is replaced. The repaint
  // waits until input has been idle, then runs once.
  function typingInCard() {
    var a = document.activeElement;
    return typingNow() || !!(a && a.tagName === 'IFRAME' && a.closest && a.closest('.tile'));
  }
  var deferred = {};
  function whenIdle(key, fn) {
    if (!typingInCard()) return false;
    if (!deferred[key]) deferred[key] = setTimeout(function () { deferred[key] = 0; fn(); }, 3000);
    return true;
  }
  function refreshTile(card, pid, dir) {
    if (!card.classList.contains('open')) return;
    if (whenIdle('tile:' + card.id, function () { refreshTile(card, pid, dir); })) return;
    var body0 = $('.cb-body', card), wasOpen = !!(body0 && !body0.hidden);
    fetchPart(pid, 'brief', dir, false, false).then(function (html) {
      if (!card.classList.contains('open')) return;
      if (whenIdle('tile:' + card.id, function () { refreshTile(card, pid, dir); })) return;   // he started typing mid-fetch
      var b = $('.cbrief', card), m = $('.cmat', card); if (m) m.remove();
      if (b) { if (/^\s*<div class="cbrief/.test(html)) b.outerHTML = html; else b.innerHTML = html; }
      if (wasOpen) { var a = $('.cb-ask', card), bd = $('.cb-body', card); if (a && bd) { bd.hidden = false; a.setAttribute('aria-expanded', 'true'); a.classList.add('open'); } }
    }).catch(function () { if (card._talk && card._talk.appendLine) card._talk.appendLine('sys', 'the record moved, but the brief could not be re-read \u2014 close and open the card', 'dim'); });   // a failed re-read is said (Grok W2e-8)
    var key = card.getAttribute('data-open');
    if (key) {
      var part = key.split('|')[0], pdir = key.split('|').slice(1).join('|');
      fetchPart(pid, part, pdir, false, false).then(function (html) { var det = $('.cdetail', card); if (det && card.getAttribute('data-open') === key) det.innerHTML = html; })
        .catch(function () { if (card._talk && card._talk.appendLine) card._talk.appendLine('sys', 'the record moved, but the ' + part + ' detail could not be re-read', 'dim'); });
    }
    refreshFaces();
  }
  // the open tile's OWN dot, from the poll's state on every answer (Grok's read of W2e-8): a steward that turns busy is
  // green at once, with no record change; the cockpit's words for its light
  var DOT_WORDS = { green: 'working', orange: 'needs you', red: 'a problem', quiet: 'idle', gray: 'idle' };
  function paintDot(card, light) {
    var l = $('.tlight', card); if (!l || !light) return;
    var cls = window.AnchorCockpitFeedback ? window.AnchorCockpitFeedback.color(light,card.classList.contains('ready')) : (light === 'quiet' ? 'gray' : light); if (!DOT_WORDS[cls]) return;
    var why = (l.title || '').indexOf(': ') > 0 && cls === (l.className.replace('tlight ', '')) ? l.title.split(': ').slice(1).join(': ') : '';
    l.className = 'tlight ' + cls; l.title = DOT_WORDS[cls] + (why ? ': ' + why : '');
    l.setAttribute('aria-label', l.title + (card.getAttribute('data-attention') ? '; ' + card.getAttribute('data-attention') : ''));
  }
  function refreshFaces() { renewInPlace(); }   // one way the page takes the record (W4)
  // W4 (his word, 2026-10-08: "Anchor is rebuilding AI Cockpits, I thought that was not supposed to happen for the open
  // ones"): EVERY change to the record - an act, an undo, a verb said in the composer or the Cave's dialogue, a project
  // made, the steward's own change, a card's stamp - is taken IN PLACE from one fresh render of the page. Each section
  // is placed where it stands; the shelves are reconciled card by card. An open card is never replaced, moved or
  // reloaded (its frame, draft, focus and stream stay); a change that would move or remove it waits until it closes
  // (closeTile). Nothing is placed while he types or dictates in a card, and no section he is in is replaced.
  var placeBusy = false, placeAgain = false, placeHeld = false, placeSkipped = false;
  var healthSig = String((window.ANCHOR_BOOT && window.ANCHOR_BOOT.health) || ''), healthPending = '';   // the page's own (Fable)   // the banner's fingerprint the page shows, and one it is placing (W3)
  // a section he was IN when the record moved (a search box, a button row) is placed once he leaves it (ChatGPT W4 r3)
  document.addEventListener('focusout', function () {
    if (!placeSkipped) return;
    setTimeout(function () { if (placeSkipped) { placeSkipped = false; renewInPlace(); } }, 300);
  }, true);
  function renewInPlace(text, undo, bad) {
    if (text) receipt(text, !!bad, undo || null);
    if (placeBusy) { placeAgain = true; return; }   // a change that lands mid-fetch runs one more fetch after (Grok W2e-8)
    if (placeWait()) { if (!deferred.place) deferred.place = setTimeout(function () { deferred.place = 0; renewInPlace(); }, 3000); return; }
    placeBusy = true;
    var sig = healthPending;   // the fingerprint THIS request will place (ChatGPT W3 r3: never a newer one it did not render)
    fetch('/high-seat', { cache: 'no-store', headers: window.StewardDialogue ? window.StewardDialogue.authHeaders(headers()) : headers() })
      .then(function (r) { return r.ok ? r.text() : ''; })
      .then(function (html) {
        if (!html) return;
        if (placeWait()) { placeAgain = true; return; }   // he started typing mid-fetch: placed once he is idle
        var doc = new DOMParser().parseFromString(html, 'text/html');
        if (doc.querySelector('.board')) {   // a locked or failed answer is never placed
          placeBoard(doc);
          if (sig) { healthSig = sig; if (healthPending === sig) healthPending = ''; }
        }
      })
      .catch(function () {})
      .then(function () { placeBusy = false; if (placeAgain) { placeAgain = false; renewInPlace(); } });   // a failed health repaint retries on the next 30 s poll
  }
  function busyIn(el) {   // he is IN this element: a box he types in (or a frame's) has the focus inside it - a button he just clicked does not count
    var a = document.activeElement;
    return !!(el && a && el.contains(a) && (a.tagName === 'IFRAME' || a.tagName === 'TEXTAREA' || a.tagName === 'INPUT' || a.tagName === 'SELECT' || a.isContentEditable));
  }
  // he is typing or dictating in an open card (its view reports it, or his keys went into it in the last ten seconds):
  // nothing on the page moves under his words until he is idle (E5, 2026-10-07)
  function placeWait() { return $$('.tile.open').some(function (c) { return !!c._typing || (busyIn(c) && Date.now() - lastCardKey < 10000); }); }   // keys IN a card, not the composer
  function held(card) { return card.classList.contains('open') || busyIn(card); }
  function morph(a, b) {   // the same element, carrying the fresh attributes and content; an open section stays open
    if (busyIn(a)) { placeSkipped = true; return false; }   // retried when he leaves it (below)
    var open = a.classList.contains('open');
    Array.prototype.slice.call(a.attributes).forEach(function (x) { if (!b.hasAttribute(x.name)) a.removeAttribute(x.name); });
    Array.prototype.slice.call(b.attributes).forEach(function (x) { if (a.getAttribute(x.name) !== x.value) a.setAttribute(x.name, x.value); });
    if (open) a.classList.add('open');
    if (a.innerHTML !== b.innerHTML) a.innerHTML = b.innerHTML;
    return true;
  }
  function placeBoard(doc) {
    placeHeld = false; placeSkipped = false;
    // the open card stays where it is ON SCREEN (ChatGPT W4 r1): whatever is placed above it, the page scrolls by the
    // same amount, so the box he dictates into never moves under him
    var anchor = $('.tile.open'), top0 = anchor ? anchor.getBoundingClientRect().top : 0;
    try { placeSections(doc); } finally {
      if (anchor && anchor.isConnected) { var dy = anchor.getBoundingClientRect().top - top0; if (Math.abs(dy) >= 1) window.scrollBy(0, dy); }
    }
  }
  function placeSections(doc) {
    // the health banner (W3: its words change in place, never a reload)
    var h0 = $('.healthbar'), h1 = doc.querySelector('.healthbar'), mh = $('.masthead');
    if (h0 && !h1) h0.remove(); else if (h1 && !h0 && mh) mh.insertAdjacentElement('afterend', document.importNode(h1, true)); else if (h0 && h1) morph(h0, h1);
    // the interrupt lane arrives at a natural break, never while he types (2026-10-03)
    var ae = document.activeElement, typing = ae && (ae.tagName === 'TEXTAREA' || ae.tagName === 'INPUT' || ae.isContentEditable);
    if (!typing) {
      var l0 = $('#lane'), l1 = doc.getElementById('lane'), bd = $('.board');
      if (l0 && !l1) l0.remove(); else if (l1 && !l0 && bd) bd.insertAdjacentElement('afterbegin', document.importNode(l1, true)); else if (l0 && l1) morph(l0, l1);
    }
    // the steward's nudge (W3b), proactive triage strip, this-week board, comms pulse, collab strip, and the seeds
    var openHzBtn = $('#shTriage .chz-card.open'), openHzKey = openHzBtn ? openHzBtn.getAttribute('data-hz-toggle') : '';
    var calWasOpen = $('#cal') && $('#cal').classList.contains('open');
    var calWasLayout = ($('#commsGrid') && $('#commsGrid').getAttribute('data-layout')) || 'split';
    var mailWasFolder = ($('#caveMailBucketsGrid') && $('#caveMailBucketsGrid').getAttribute('data-mail-folder-mode')) || 'all';
    var calBusyUi = !!(
      ($('#caveSpeedRacerBody') && !$('#caveSpeedRacerBody').hidden) ||
      ($('#caveCommsDialogueTile') && !$('#caveCommsDialogueTile').hidden) ||
      ($('#caveCommsSetupDrawer') && $('#caveCommsSetupDrawer').open) ||
      ($('#caveCommsConnectModal') && !$('#caveCommsConnectModal').hidden) ||
      ($('#caveCommsDeviceFlowBox') && !$('#caveCommsDeviceFlowBox').hidden)
    );
    var collabWasOpen = $('#caveCollabStrip') && $('#caveCollabStrip').classList.contains('open');
    ['shTriage', 'thisWeekBoard', 'cal', 'caveCollabStrip'].forEach(function (id) {
      if (id === 'cal' && calBusyUi) return;
      var a = document.getElementById(id), b = doc.getElementById(id);
      if (a && b) morph(a, b);
    });
    ['nudgeSlot', 'seedCount', 'seedLbl', 'seedPanel', 'ptileCount', 'apGroups'].forEach(function (id) { var a = document.getElementById(id), b = doc.getElementById(id); if (a && b) morph(a, b); });
    if (openHzKey) {
      var nb = $('#shTriage .chz-card[data-hz-toggle="' + openHzKey + '"]'), nd = document.getElementById('hzDrawer-' + openHzKey);
      if (nb && nd) { nb.classList.add('open'); nb.setAttribute('aria-expanded', 'true'); nd.hidden = false; }
    }
    if (calWasOpen && $('#cal')) { $('#cal').classList.add('open'); if ($('#calTog')) $('#calTog').textContent = 'Collapse'; }
    if (typeof window._applyCaveCommsLayout === 'function') window._applyCaveCommsLayout(calWasLayout);
    if (typeof window._applyCaveMailFolderMode === 'function') window._applyCaveMailFolderMode(mailWasFolder);
    if (typeof window._ensureCaveCommsDataLoaded === 'function') window._ensureCaveCommsDataLoaded(true);
    if (typeof window._applySourceFilterToDOM === 'function') window._applySourceFilterToDOM();
    if (typeof _renderCaveSpeedRacerTile === 'function') _renderCaveSpeedRacerTile();
    if (typeof _renderWorkingListSpine === 'function') _renderWorkingListSpine();
    if (collabWasOpen && $('#caveCollabStrip')) {
      $('#caveCollabStrip').classList.add('open');
      if ($('#caveCollabBody')) $('#caveCollabBody').hidden = false;
      var ct = $('#caveCollabStrip .cal-tog'); if (ct) ct.textContent = 'Collapse';
    }
    // the goals: the line and the rows, the rows he opened kept open
    var cb0 = $('#campBody'), cb1 = doc.getElementById('campBody'), cl0 = $('#campLine'), cl1 = doc.getElementById('campLine');
    if (cl0 && cl1) morph(cl0, cl1);
    if (cb0 && cb1) {
      var openG = $$('.grow.open', cb0).map(function (g) { return g.getAttribute('data-g'); });
      if (morph(cb0, cb1)) { openG.forEach(function (g) { var r = $('.grow[data-g="' + g + '"]', cb0); if (r) r.classList.add('open'); }); bindDrags(cb0); }
    }
    placeShelves(doc);
    // the Candidates: the groups and the count; the search, the sort and the open tile stay as he left them
    var c0 = $('#shCands'), c1 = doc.getElementById('shCands');
    if (c0 && !c1) { if (busyIn(c0)) placeSkipped = true; else c0.remove(); }
    else if (c1 && !c0) { var deck = $('#shDeck'); if (deck) { deck.insertAdjacentElement('afterend', document.importNode(c1, true)); bindCands(); } }
    else if (c0 && c1 && $$('.cand-group', c0).some(busyIn)) placeSkipped = true;
    else if (c0 && c1 && $('#candsTile', c0)) {
      var t0 = $('#candsTile', c0), n0 = $('summary .c', c0), n1 = $('summary .c', c1);
      if (n0 && n1) n0.textContent = n1.textContent;
      $$('.cand-group', c0).forEach(function (g) { g.remove(); });
      $$('.cand-group', c1).forEach(function (g) { t0.appendChild(document.importNode(g, true)); });
      candApply();
    }
    // the Desk's line (its rows open as he left them)
    var d0 = $('#deskline'), d1 = doc.getElementById('deskline');
    if (d0 && d1 && morph(d0, d1)) setDesk(d0.classList.contains('open'));
    // the dated deliveries: the ruler and its counts (a balloon over a marker that moved is closed)
    var r0 = $('#ruler'), r1 = doc.getElementById('ruler');
    if (r0 && r1 && busyIn(r0)) placeSkipped = true;
    else if (r0 && r1) {   // compared without the open balloon and the marker it hangs from (ChatGPT W4 r1)
      var bare = r0.cloneNode(true);
      $$('.balloon', bare).forEach(function (b) { b.remove(); }); $$('.mkcard.on', bare).forEach(function (m) { m.classList.remove('on'); });
      if (bare.innerHTML !== r1.innerHTML) { if (balloon) closeBalloon(); morph(r0, r1); bindMarkers(r0); }
    }
    var s0 = $('#shDated > .shelf-h .c'), s1 = doc.querySelector('#shDated > .shelf-h .c'); if (s0 && s1) s0.textContent = s1.textContent;
    var o0 = $('#shDated > .shelf-foot.late'), o1 = doc.querySelector('#shDated > .shelf-foot.late'), rl = $('#ruler');   // the overdue line too
    if (o0 && !o1) o0.remove(); else if (o1 && !o0 && rl) rl.insertAdjacentElement('afterend', document.importNode(o1, true)); else if (o0 && o1) morph(o0, o1);
    // the registry projects in no goal (draggable onto a goal): added, placed or taken out (ChatGPT W4 r2)
    $$('#railNav button[data-rail]').forEach(function (b) {   // the rail's counts follow the record (ChatGPT W4 r4)
      var f = doc.querySelector('#railNav button[data-rail="' + b.getAttribute('data-rail') + '"]'); if (!f) return;
      ['.n', '.c'].forEach(function (s) { var a = $(s, b), c = $(s, f); if (a && c && a.textContent !== c.textContent) a.textContent = c.textContent; });
    });
    var g0 = $('#ptile .orphans'), g1 = doc.querySelector('#ptile .orphans'), pl = $('#ptile .ptile-line');
    if (g0 && !g1) g0.remove();
    else if (g1 && !g0 && pl) { pl.insertAdjacentElement('afterend', document.importNode(g1, true)); bindDrags($('#ptile .orphans')); }
    else if (g0 && g1 && g0.innerHTML !== g1.innerHTML && morph(g0, g1)) bindDrags(g0);
    if (ptileLoaded) loadFolders();
  }
  // the shelves, card by card: a card that stays keeps its element (only its face is placed again); a new one is made
  // and wired as the page does at load; one that left is taken out; the order is the record's. The open card is never
  // touched: the others are placed around it, and its own move waits until it closes.
  function placeShelves(doc) {
    var where = {};
    ['shActive', 'shDeck'].forEach(function (z) { var f = doc.getElementById(z); if (f) $$('.grid > .tile', f).forEach(function (c) { where[c.id] = z; }); });
    ['shActive', 'shDeck'].forEach(function (z) {
      var live = document.getElementById(z); if (!live) return;
      $$('.grid > .tile', live).forEach(function (c) {
        c._leaving = false;
        if (where[c.id] && where[c.id] === z) return;
        if (held(c)) { placeHeld = true; c._leaving = true; return; }   // leaving this shelf once it closes: never counted for a drop
        if (!where[c.id]) dropCard(c);
      });
    });
    ['shActive', 'shDeck'].forEach(function (z) {
      var live = document.getElementById(z), fresh = doc.getElementById(z); if (!live || !fresh) return;
      var grid = $('.grid', live), want = [];
      $$('.grid > .tile', fresh).forEach(function (f) {
        var c = document.getElementById(f.id);
        if (c && c.parentNode !== grid && held(c)) { placeHeld = true; return; }   // a held card keeps its shelf until it closes
        var how = c ? recordChange(c, f) : 'new';
        if (how === 'remake' && held(c)) placeHeld = true;                          // made again once it closes
        else if (how === 'remake') { dropCard(c); c = null; how = 'new'; }
        else if (how === 'face') placeFace(c, f);
        if (how === 'new') { c = document.importNode(f, true); c._record = f.outerHTML; c._fresh = true; }
        want.push(c);
      });
      // the record's order around the held card(s): each wanted card goes before the next free one
      function nextFree(n) { while (n && (!n.classList || !n.classList.contains('tile') || held(n))) n = n.nextElementSibling; return n; }
      var at = nextFree(grid.firstElementChild);
      want.forEach(function (c) {
        if (held(c)) return;
        if (c === at) { at = nextFree(c.nextElementSibling); return; }
        var arriving = c.parentNode !== grid && !c._fresh;
        if (at) grid.insertBefore(c, at); else grid.appendChild(c);
        if (arriving && z === 'shActive') setTimeout(function () { warmTile(c); }, 1500);   // moved into Active: preloaded (ChatGPT W4 r4)
      });
      want.forEach(function (c) { if (c._fresh) { c._fresh = false; wireCard(c); } });
      live._order = $$('.grid > .tile', fresh).map(function (f) { return f.id; });   // the record's order, for a drop
      // a held card out of the record's order (moved within its shelf, or lifted to the top while open): placed on close
      var now = $$('.grid > .tile', live).filter(function (c) { return !c._leaving; });
      if (now.some(held) && now.map(function (c) { return c.id; }).join('|') !== want.map(function (c) { return c.id; }).join('|')) placeHeld = true;
      var empty = $('.grid > .empty', live), n = $$('.grid > .tile', live).length;
      if (n && empty) empty.remove();
      else if (!n && !empty) { var fe = $('.grid > .empty', fresh); if (fe) grid.appendChild(document.importNode(fe, true)); }
      var k0 = $('.shelf-h .c', live), k1 = $('.shelf-h .c', fresh); if (k0 && k1) k0.textContent = k1.textContent;
    });
  }
  // what changed in a card's record (ChatGPT W4 r1-r2): compared with the markup the card was made from, the whole of
  // it - '' nothing; 'face' only its lines (placed in the card, its preloaded view kept); 'remake' anything else (its
  // name, kind, record, acts, resume...: the card is made again from the record, an open one once it closes)
  function withoutFace(html) {
    var t = document.createElement('template'); t.innerHTML = html;
    var f = t.content.querySelector('.t-face'); if (f) f.innerHTML = '';
    return t.innerHTML;
  }
  function recordChange(card, fresh) {
    var was = card._record || '', now = fresh.outerHTML;
    if (was === now) return '';
    return withoutFace(was) === withoutFace(now) ? 'face' : 'remake';
  }
  function placeFace(card, fresh) {   // the record's lines; activity and attention keep their own continuing read (below)
    var a = $('.t-face', card), b = $('.t-face', fresh);
    if (a && b && !busyIn(a)) { a.innerHTML = b.innerHTML; card._record = fresh.outerHTML; }
  }
  function dropCard(card) {
    if (card._warmTalk) card._warmTalk.stop();
    stopTalk(card); card.remove();
  }
  function wireCard(card) {   // a card the record added: the same wiring the page gives its cards at load
    compactTiles(card.parentNode); initiativeCockpitLinks(card.parentNode); bindDrags(card);
    if (card.getAttribute('data-tile')) bindCard(card);
    if (card.hasAttribute('data-ready')) paintReady(card, true, 'needs your attention');
    if (card.closest('#shActive')) setTimeout(function () { warmTile(card); }, 1500);
    refreshFeedback();
  }
  // Closed tiles have no dialogue stream. Read the same exact-effort cockpit state every
  // five seconds, with no wake/send/model call, and refresh review metadata on change or
  // within fifteen seconds (managed lifecycle changes need not move the map's stamp).
  // Use only current, explicitly designated reviews; an ordinary work pin is not a request.
  var feedbackBusy = false, feedbackAgain = false, feedbackLoading = false;
  function feedbackModule() {
    if (window.AnchorCockpitFeedback) return window.AnchorCockpitFeedback;
    if (!feedbackLoading) {
      feedbackLoading = true;
      var script = document.createElement('script'); script.src = '/static/cockpit-feedback.js';
      script.onload = function () { feedbackLoading = false; refreshFeedback(); };
      script.onerror = function () { feedbackLoading = false; script.remove(); };
      document.head.appendChild(script);
    }
    return null;
  }
  function refreshFeedback() {
    var boot = window.ANCHOR_BOOT || {};
    if (document.hidden || (boot.auth_required && !boot.logged_in && !token())) return;
    var feedback = feedbackModule(); if (!feedback) return;
    if (feedbackBusy) { feedbackAgain = true; return; }
    feedbackBusy = true;
    var cards = $$('.tile[data-tile]').filter(function (c) { return c.getClientRects().length > 0; }), moved = false, next = 0;
    function worker() {
      var card = cards[next++]; if (!card) return Promise.resolve();
      var epoch = card._feedbackEpoch || 0, target = {pid:card.getAttribute('data-tile'),dir:openDir(card)}, key = feedback.identity(target);
      function current() { return card.isConnected && key === feedback.identity({pid:card.getAttribute('data-tile'),dir:openDir(card)}) && epoch === (card._feedbackEpoch || 0); }
      var old = card._feedbackRecord;
      var h = window.StewardDialogue ? window.StewardDialogue.authHeaders(headers()) : headers();
      return feedback.read(target,old,h,function (st,question) {
        if (!current()) return;
        if (question) paintReady(card,true,'needs your answer');
        paintDot(card,st.light);
      }).then(function (value) {
        if (!current()) return;
        if (value.ready !== null) paintReady(card,value.ready,value.reason);
        paintDot(card,value.state.light);
        if (value.record) {
          if (old && old.stamp !== value.record.stamp) moved = true;
          card._feedbackRecord = value.record;
        }
      }).catch(function () {}).then(worker);
    }
    Promise.all([worker(),worker(),worker(),worker()]).finally(function () {
      feedbackBusy = false;
      var nowMs = Date.now();
      if (moved && (!window._lastFaceRefreshAt || (nowMs - window._lastFaceRefreshAt) > 15000)) {
        window._lastFaceRefreshAt = nowMs;
        refreshFaces();
      }
      if (feedbackAgain) { feedbackAgain = false; refreshFeedback(); }
    });
  }
  setInterval(refreshFeedback, 5000);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) refreshFeedback(); });
  window.addEventListener('focus', refreshFeedback);
  setTimeout(refreshFeedback, 0);
  function openTile(card, pid, dir) {
    var body = $('.t-body', card);
    if (!body || card.classList.contains('open')) return;   // a card without a record has no body to open
    hidePeek(card);
    $$('.tile.open').forEach(function (c) { if (c !== card) closeTile(c, true); });   // one tile open, one dialogue polling (Grok's read of W2e)
    // the preloaded view (an Active card) is revealed when the card opens on ITS effort; opened on another effort, it goes
    var warm = card._warmTalk && card._warmTalk.dir === (dir || '') && $('.cdlg', body) ? card._warmTalk : null;
    if (card._warmTalk && !warm) card._warmTalk.stop();
    card.classList.add('open'); card.classList.remove('talking'); card.setAttribute('aria-expanded', 'true'); card.setAttribute('data-open-dir', dir || ''); body.hidden = false; seen(card);
    rememberTile(card, false);
    // the opened tile goes to the TOP of its shelf (his word, 2026-10-01) and comes back to its place on close
    var grid = card.parentNode;
    if (grid && grid.classList && grid.classList.contains('grid') && grid.firstElementChild !== card) {
      if (warm) { card.style.order = '-1'; card._lifted = true; }   // moving the node would reload its preloaded frame: the grid draws it first instead
      else { card._homeNext = card.nextElementSibling; card._moved = true; grid.insertBefore(card, grid.firstElementChild); }
    }
    try { card.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (err) {}
    if (warm) {
      // the brief and the detail go in above the kept dialogue, the drop line under it; the frame itself is never touched
      Array.prototype.slice.call(body.children).forEach(function (n) { if (!n.classList.contains('cdlg')) n.remove(); });
      body.insertAdjacentHTML('afterbegin', '<div class="cbrief"><div class="cp-quiet">Reading the record\u2026</div></div><div class="cdetail" hidden></div>');
      body.insertAdjacentHTML('beforeend', dropHtml());
      var dl = $('.cdlg', body), dbar = $('.dlg-bar', dl); dl.classList.remove('thin'); dl.classList.add('big'); if (dbar) dbar.setAttribute('aria-expanded', 'true');
    } else body.innerHTML = '<div class="cbrief"><div class="cp-quiet">Reading the record\u2026</div></div><div class="cdetail" hidden></div>' + talkHtml('talk-' + card.id) + dropHtml();
    fetchPart(pid, 'brief', dir, false, true)
      .then(function (html) { var b = $('.cbrief', card); if (b && card.classList.contains('open')) { if (/^\s*<div class="cbrief/.test(html)) b.outerHTML = html; else b.innerHTML = html; } })   // the served brief IS the rectangle (never one cbrief inside another)
      .catch(function () { var b = $('.cbrief', card); if (b) b.innerHTML = '<div class="cp-quiet">That did not go through.</div>'; });
    if (warm) { card._talk = warm; warm.show(); }
    else startTalk(card, pid, dir);
  }
  function rememberTile(card, big) { try { if (!card.classList.contains('open')) return; sessionStorage.setItem('highseat_open_tile', JSON.stringify({ id: card.id, dir: openDir(card), big: !!big })); } catch (e) {} }
  function forgetTile() { try { sessionStorage.removeItem('highseat_open_tile'); } catch (e) {} }
  function closeTile(card, another) {
    // a preloaded view is hidden and parked, never destroyed: the next open is instant too (2026-10-06)
    var warm = !!(card._warmTalk && card._talk === card._warmTalk);
    if (warm) { card._warmTalk.park(); card._talk = null; } else stopTalk(card);
    card.classList.remove('open', 'talking'); card.setAttribute('aria-expanded', 'false'); card.removeAttribute('data-open'); card.removeAttribute('data-open-dir'); forgetTile(); card._heldSaid = false;
    if (card._moved) { var g = card.parentNode; if (g) { if (card._homeNext && card._homeNext.parentNode === g) g.insertBefore(card, card._homeNext); else g.appendChild(card); } card._moved = false; card._homeNext = null; }
    if (card._lifted) { card.style.order = ''; card._lifted = false; }
    var body = $('.t-body', card);
    if (body) { body.hidden = true; if (warm) Array.prototype.slice.call(body.children).forEach(function (n) { if (!n.classList.contains('cdlg')) n.remove(); }); else body.innerHTML = ''; }
    $$('.t-acts button.on, .t-eff-open.on', card).forEach(function (b) { b.classList.remove('on'); });
    if (!warm) setTimeout(function () { warmTile(card); }, 1500);   // an Active card opened the ordinary way is preloaded from here on (warmTile skips the rest)
    if (!another) {   // what the open tile held back: a new build's reload, or the record's move of this card (W4)
      if (pendingBuild) renewBuild(pendingBuild);
      else if (placeHeld) renewInPlace();
    }
  }
  function openPart(card, pid, part, btn) {
    // W1/W2 (2026-09-28): a button may name ITS effort (another effort's wait; the head's pick) — its data-dir wins,
    // and the open state is keyed by part AND effort so the same part on another effort opens rather than closes
    var dir = (btn && btn.getAttribute && btn.getAttribute('data-dir') !== null) ? btn.getAttribute('data-dir') : (card.getAttribute('data-dir') || '');
    var key = part + '|' + dir;
    if (card._compact && !card.classList.contains('open')) {
      var detail = $('.t-peek-detail', card), same = card.getAttribute('data-open') === key;
      if (same) { hidePeek(card); card.classList.add('peek-dismissed'); return; }
      card.classList.remove('peek-dismissed'); showPeek(card); card.classList.add('peek-pinned'); seen(card);
      card.setAttribute('data-open', key); card.setAttribute('data-open-dir', dir);
      $$('.t-acts button, .t-eff-open', card).forEach(function (b) { b.classList.toggle('on', b === btn); });
      detail.hidden = false; detail.innerHTML = '<div class="cp-quiet">Reading the record\u2026</div>'; positionPeek(card);
      fetchPart(pid, part, dir, false, false).then(function (html) { if (card.getAttribute('data-open') === key) { detail.innerHTML = html; positionPeek(card); } })
        .catch(function () { if (card.getAttribute('data-open') === key) detail.innerHTML = '<div class="cp-quiet">That did not go through.</div>'; });
      return;
    }
    // the tile opens on the act's OWN effort (a button naming another effort's wait): its brief and dialogue are that
    // cockpit's, never a different cockpit from the detail beside it (Grok's read of W2e-3)
    if (!card.classList.contains('open')) openTile(card, pid, dir);
    else if ((card.getAttribute('data-open-dir') || '') !== dir) { closeTile(card); openTile(card, pid, dir); }
    var det = $('.cdetail', card);
    var same = card.getAttribute('data-open') === key;
    $$('.t-acts button, .t-eff-open', card).forEach(function (b) { b.classList.toggle('on', !same && b === btn); });
    if (same) { det.hidden = true; det.innerHTML = ''; card.removeAttribute('data-open'); return; }
    card.setAttribute('data-open', key); det.hidden = false; det.innerHTML = '<div class="cp-quiet">Reading the record\u2026</div>';
    fetchPart(pid, part, dir, false, false)
      .then(function (html) { if (card.getAttribute('data-open') === key) det.innerHTML = html; })
      .catch(function () { det.innerHTML = '<div class="cp-quiet">That did not go through.</div>'; });
  }
  $$('.tile[data-tile]').forEach(bindCard);
  function bindCard(card) {   // at load, and on a card the record adds (W4)
    if (card._cardBound) return; card._cardBound = true;
    var pid = card.getAttribute('data-tile');
    card.addEventListener('click', function (e) {
      if (card._compact) return;   // the compact card's own handler toggles its inline dialogue
      if (e.target.closest('a, button, .t-body')) return;
      if (card.classList.contains('open')) closeTile(card); else openTile(card, pid, card.getAttribute('data-dir') || '');   // the tile itself opens to its brief and its dialogue
    });
    // W2e-6: the OPEN tile takes a file drop (a card drag in progress is never a file)
    card.addEventListener('dragover', function (e) { if (drag || !isFileDrag(e) || !card.classList.contains('open')) return; e.preventDefault(); e.stopPropagation(); try { e.dataTransfer.dropEffect = 'copy'; } catch (_) {} card.classList.add('dropping'); });
    card.addEventListener('dragleave', function (e) { if (!card.contains(e.relatedTarget)) card.classList.remove('dropping'); });
    card.addEventListener('drop', function (e) { if (drag || !isFileDrag(e) || !card.classList.contains('open')) return; e.preventDefault(); e.stopPropagation(); card.classList.remove('dropping'); dropFiles(card, pid, e.dataTransfer.files); });
  }
  // a card's act buttons and its wait line's open/see are delegated (W3b, Grok's read): a face re-rendered in place keeps them
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.tile[data-tile] [data-part]'); if (!b || b.classList.contains('h-open')) return;
    var card = b.closest('.tile[data-tile]'); if (!card) return;
    e.stopPropagation(); openPart(card, card.getAttribute('data-tile'), b.getAttribute('data-part'), b);
  });
  // W3b: the open tile survives a renewal of the page - opened again where it was, its conversation grown as it was,
  // his unsent words back in the box
  (function () {
    var kept = null; try { kept = JSON.parse(sessionStorage.getItem('highseat_open_tile') || 'null'); } catch (e) { kept = null; }
    if (!kept || !kept.id) return;
    var card = document.getElementById(kept.id);
    if (!card || !card.getAttribute('data-tile')) { forgetTile(); return; }
    if (card._compact) { forgetTile(); return; }   // the new overview starts small; conversation drafts remain saved
    openTile(card, card.getAttribute('data-tile'), kept.dir || '');
    if (kept.big) grow(card);
  })();
  // W2e-3 (his word): the ask is a banner; a click opens the description and the recommendation; "talk about it" puts
  // the ask into the tile's dialogue and grows it
  document.addEventListener('click', function (e) {
    var a = e.target.closest('.cb-ask');
    if (a) { e.preventDefault(); e.stopPropagation(); var bd = a.parentNode.querySelector('.cb-body'); if (!bd) return; var open = bd.hidden; bd.hidden = !open; a.setAttribute('aria-expanded', open ? 'true' : 'false'); a.classList.toggle('open', open); return; }
    var t = e.target.closest('.cb-talk');
    if (t) { e.preventDefault(); e.stopPropagation(); var card = t.closest('.tile'); if (!card) return; if (card._compact && !card._talk) openTile(card, card.getAttribute('data-tile'), card.getAttribute('data-open-dir') || card.getAttribute('data-dir') || ''); if (!card._talk || !card._talk.prefill) return; card._talk.prefill('About: ' + (t.getAttribute('data-ask') || '') + ' \u2014 ', true); }   // an explicit talk action retains the dialogue-only embedded conversation
  });
  // Accept in the brief: one click, the answer said to the steward as the cockpit says it, the dialogue takes the tile
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.cb-accept'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    // the acceptance goes to the cockpit the tile was OPENED on (an act may have opened it on another effort), never the card's own dir by default (Grok's read of W2e-4)
    var card = b.closest('.tile'), pid = card && card.getAttribute('data-tile'), dir = card ? (card.getAttribute('data-open-dir') !== null ? card.getAttribute('data-open-dir') : (card.getAttribute('data-dir') || '')) : '';
    if (!card || !pid) return;
    b.disabled = true; grow(card);
    fetch('/api/steward/say', { method: 'POST', headers: headers(), body: JSON.stringify({ pid: pid, dir: dir, text: 'Accept recommendation: ' + (b.getAttribute('data-rec') || ''), question_id: b.getAttribute('data-qid') || null }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || j.ok === false) { b.disabled = false; receipt((j && (j.error || j.say)) || 'That did not go through.', true); return; }
        if (j.kept) { b.disabled = false; receipt('Kept \u2014 the steward could not wake; say the acceptance again when it is up (the question stays open).'); return; }   // Grok W2e-3: a kept send is not an acceptance
        b.textContent = 'Accepted'; receipt('Accepted \u2014 the steward answers in the tile as it writes.');
      })
      .catch(function () { b.disabled = false; receipt('That did not go through.', true); });
  });
  // W2 (2026-09-28): the head's one act — "open" on the brief's lead opens THAT project's card on THAT effort
  document.addEventListener('click', function (e) {
    var h = e.target.closest('.h-open'); if (!h) return;
    e.preventDefault(); e.stopPropagation();
    var pid = h.getAttribute('data-pid') || '', card = document.getElementById('card-' + pid);
    if (!card) { window.open('/project/' + encodeURIComponent(pid), '_blank', 'noopener'); return; }
    card.scrollIntoView({ block: 'center', behavior: 'smooth' });
    card.removeAttribute('data-open');
    openPart(card, pid, h.getAttribute('data-part') || 'status', h);
  });
  // W4 (2026-09-28): his word on a proposed correction set — accept applies it, dismiss closes it; the part is read
  // again and the card's "proposed" line goes when no set is left open
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.t-repair'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    var card = b.closest('.tile'), pid = b.getAttribute('data-pid') || '', dir = b.getAttribute('data-dir') || '';
    var body = { pid: pid, dir: dir, proposal_id: b.getAttribute('data-proposal') || '', disposition: b.getAttribute('data-disposition') || '' };
    $$('.t-repair', card || document).forEach(function (x) { x.disabled = true; });
    fetch('/api/high-seat/repair', { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { if (r.status === 401 || r.status === 403) { return { ok: false, receipt: NOT_LOGGED_IN }; } return r.json(); })
      .then(function (j) {
        receipt((j && j.receipt) || 'That did not go through.', !(j && j.ok));
        if (!(j && j.ok)) { $$('.t-repair', card || document).forEach(function (x) { x.disabled = false; }); return; }
        if (card) {
          if (j.open === 0) { var pl = $('.t-line.prop', card); if (pl) pl.remove(); }   // exactly none open; an omitted count keeps the chip (Grok W4)
          var tb = $('.cdetail', card) || $('.t-body', card);   // W2e-2: the detail, never the whole tile (its dialogue stays)
          if (tb) fetchPart(pid, 'status', dir).then(function (html) { tb.hidden = false; tb.innerHTML = html; })
            .catch(function () { tb.innerHTML = '<div class="cp-quiet">The record changed, but this card did not refresh &mdash; reload the page.</div>'; });
        }
      })
      .catch(function () { receipt('That did not go through.', true); $$('.t-repair', card || document).forEach(function (x) { x.disabled = false; }); });
  });
  // "paste the token" on a card or a balloon that answered 401: ask again, then read that part again
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-login]'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    askToken().then(function (ok) {
      if (!ok) return;
      var bl = b.closest('.balloon');
      if (bl) {   // the balloon re-reads its own part into its body (Grok R7)
        var bb = $('.bl-body', bl); bb.innerHTML = '<div class="cp-quiet">Reading the record…</div>';
        fetchPart(bl.getAttribute('data-pid') || '', 'next', bl.getAttribute('data-dir') || '')
          .then(function (html) { if (bl.isConnected) bb.innerHTML = html; })
          .catch(function () { bb.innerHTML = '<div class="cp-quiet">That did not go through.</div>'; });
        return;
      }
      var card = b.closest('.tile'), key = card && card.getAttribute('data-open');
      if (!card || !key) return;
      var part = key.split('|')[0], odir = key.indexOf('|') >= 0 ? key.slice(key.indexOf('|') + 1) : null;
      card.removeAttribute('data-open');
      var again = odir !== null ? $('[data-part="' + part + '"][data-dir="' + odir.replace(/"/g, '') + '"]', card) : null;
      openPart(card, card.getAttribute('data-tile'), part, again || $('.t-acts [data-part="' + part + '"]', card));
    });
  });

  // the ruler's markers balloon open (W2): the step, its project and date, the project's open decision and
  // what it depends on — the same Next steps fragment a card shows — and the links into the cockpit
  var balloon = null;
  function closeBalloon() { if (balloon) { balloon.remove(); balloon = null; } $$('.mkcard.on').forEach(function (m) { m.classList.remove('on'); }); }
  document.addEventListener('click', function (e) { if (balloon && !e.target.closest('.balloon, .mkcard')) closeBalloon(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeBalloon(); });
  function bindMarkers(root) { $$('.mkcard', root).forEach(bindMarker); }   // at load, and on a ruler placed again (W4)
  bindMarkers(document);
  function bindMarker(mk) {
    mk.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();
      if (mk.classList.contains('on')) { closeBalloon(); return; }
      closeBalloon(); mk.classList.add('on');
      var pid = (mk.getAttribute('href') || '').replace('/project/', '');
      var ruler = $('#ruler');
      balloon = document.createElement('div'); balloon.className = 'balloon';
      balloon.setAttribute('data-pid', pid);
      var r = mk.getBoundingClientRect(), rr = ruler.getBoundingClientRect();
      var left = Math.max(8, Math.min(r.left - rr.left, rr.width - 440));
      balloon.style.left = left + 'px'; balloon.style.top = (r.bottom - rr.top + 8) + 'px';
      balloon.style.setProperty('--arrow', Math.max(12, r.left - rr.left - left + 20) + 'px');
      balloon.innerHTML = '<div class="bl-head"><b>' + mk.querySelector('.mk-what').textContent + '</b> · ' + mk.querySelector('.mk-date').textContent
        + ' · ' + mk.querySelector('.mk-proj').textContent + '</div><div class="bl-body"><div class="cp-quiet">Reading the record…</div></div>'
        + '<div class="bl-foot"><a href="#card-' + pid + '" data-bl-card="' + pid + '">its card</a> <span class="bl-close" data-bl-close>close</span></div>';
      ruler.appendChild(balloon);
      $('[data-bl-close]', balloon).addEventListener('click', closeBalloon);
      var cardLink = $('[data-bl-card]', balloon);
      cardLink.addEventListener('click', function (ev) { ev.preventDefault(); var c = $('#card-' + pid); closeBalloon(); if (c) { c.scrollIntoView({ behavior: 'smooth', block: 'center' }); c.classList.add('flash'); setTimeout(function () { c.classList.remove('flash'); }, 1600); } });
      var body = $('.bl-body', balloon);
      var ownCard = $('#card-' + pid), ownDir = ownCard ? (ownCard.getAttribute('data-dir') || '') : '';
      balloon.setAttribute('data-dir', ownDir);
      fetchPart(pid, 'next', ownDir)
        .then(function (html) { if (balloon) body.innerHTML = html; })
        .catch(function () { if (balloon) body.innerHTML = '<div class="cp-quiet">That did not go through.</div>'; });
    });
  }

  // the Calendar / Email tile (Option 1 Split 50/50 + Click to Make Either Full = Mockup 3)
  var cal = $('#cal'), calTog = $('#calTog');
  function applyCommsLayout(mode) {
    var m = (mode === 'cal' || mode === 'mail') ? mode : 'split';
    var grid = document.getElementById('commsGrid');
    if (grid) grid.setAttribute('data-layout', m);
    var a = document.getElementById('tabCal'), b = document.getElementById('tabMail');
    if (a) a.classList.toggle('on', m === 'cal' || m === 'split');
    if (b) b.classList.toggle('on', m === 'mail');
    $$('[data-comms-layout]').forEach(function (btn) {
      if (btn.classList && (btn.classList.contains('mini') || btn.classList.contains('cal-tab'))) {
        btn.classList.toggle('on', btn.getAttribute('data-comms-layout') === m);
      }
    });
    var calTBtn = document.querySelector('[data-comms-layout-toggle="cal"]');
    if (calTBtn) {
      calTBtn.textContent = (m === 'cal') ? '\u2921 Back to 50/50 Split' : '\u2922 Full Calendar';
      calTBtn.classList.toggle('on', m === 'cal');
    }
    var mailTBtn = document.querySelector('[data-comms-layout-toggle="mail"]');
    if (mailTBtn) {
      mailTBtn.textContent = (m === 'mail') ? '\u2921 Back to 50/50 Split' : '\u2922 Full Email';
      mailTBtn.classList.toggle('on', m === 'mail');
    }
  }
  window._applyCaveCommsLayout = applyCommsLayout;
  function setCalTab(which) {
    applyCommsLayout(which === 'mail' ? 'mail' : (which === 'cal' ? 'cal' : 'split'));
  }
  document.addEventListener('click', function (e) {
    var headEl = e.target.closest && e.target.closest('#calHead');
    if (!headEl) return;
    var calSec = document.getElementById('cal');
    var togBtn = document.getElementById('calTog');
    if (!calSec) return;
    var openSentPill = e.target.closest('[data-cave-open-sent]');
    if (openSentPill) {
      e.preventDefault(); e.stopPropagation();
      calSec.classList.add('open');
      applyCommsLayout('mail');
      if (typeof window._applyCaveMailFolderMode === 'function') window._applyCaveMailFolderMode('sent');
      if (typeof window._ensureCaveCommsDataLoaded === 'function') window._ensureCaveCommsDataLoaded();
      if (togBtn) togBtn.textContent = 'Collapse';
      var sentColEl = document.getElementById('caveMailSentCol');
      if (sentColEl) setTimeout(function () { try { sentColEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (_) {} }, 80);
      return;
    }
    var layoutTarget = e.target.closest('[data-comms-layout]');
    if (layoutTarget) {
      e.preventDefault(); e.stopPropagation();
      var wantMode = layoutTarget.getAttribute('data-comms-layout') || 'split';
      var curGrid = document.getElementById('commsGrid');
      var curMode = (curGrid && curGrid.getAttribute('data-layout')) || 'split';
      if (calSec.classList.contains('open') && curMode === wantMode && e.target.closest('.cal-sline')) {
        calSec.classList.remove('open');
      } else {
        calSec.classList.add('open');
        applyCommsLayout(wantMode);
        if (typeof window._ensureCaveCommsDataLoaded === 'function') window._ensureCaveCommsDataLoaded();
      }
    } else {
      calSec.classList.toggle('open');
      if (calSec.classList.contains('open') && typeof window._ensureCaveCommsDataLoaded === 'function') {
        window._ensureCaveCommsDataLoaded();
      }
    }
    if (togBtn) togBtn.textContent = calSec.classList.contains('open') ? 'Collapse' : 'Expand';
  });
  // the Desk's chips and the tools are delegated (W4): a Desk line or a health banner placed again keeps them
  document.addEventListener('click', function (e) {
    var c = e.target.closest('.dchip[data-desk]');
    if (c) {
      var k = c.getAttribute('data-desk');
      if (k === 'tasks') { openWin('/dashboard#tile-tasks'); }
      else { cal && cal.classList.add('open'); setCalTab(k === 'mail' ? 'mail' : 'cal'); cal && cal.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
      return;
    }
    var b = e.target.closest('.tool[data-tool]'); if (!b) return;
    var t = b.getAttribute('data-tool');
    if (t === 'doctor') openWin('/doctor' + tokenQ());
    else if (t === 'zombie') openWin('/api/rnd/zombie_hunter_report' + tokenQ());
    else if (t === 'foundry') openWin('/foundry');
  });

  // R11 (2026-09-28): New project — the old dashboard's folder-creation dialog ALONE, in a small window; it reports
  // back here when the project is made and this page reloads to show it in its folder
  var apNew = $('#apNew');
  if (apNew) apNew.addEventListener('click', function (e) {
    e.preventDefault(); e.stopPropagation();
    var w = null;
    try { w = window.open('/dashboard?new=1&only=1', 'anchor-new-project', 'width=640,height=800,resizable=yes,scrollbars=yes'); } catch (err) { w = null; }
    if (!w) receipt('The browser blocked the small window — allow popups and try again.', true);
  });
  window.addEventListener('message', function (ev) {
    if (ev.origin !== location.origin || !ev.data || ev.data.anchor !== 'project-created') return;
    var en = ev.data.entry || {};
    var text = ev.data.message || ('Project \u201c' + (en.name || '?') + '\u201d created' + (en.group ? ' in the folder ' + en.group : '') + '.');
    renewInPlace(text, null, !!ev.data.group_error);   // W4: the new project is placed in the page, never a reload
  });
  // R11: the steward's "start a new project" comes back as a project_create act — a confirm card under the
  // composer with the folder to put it in; nothing is created until Create it
  function projectCard(pc) {
    var old = $('#pcCard'); if (old) old.remove();
    var folder = String(pc.folder || ''), name = pc.name || folder.replace(/[\\\/]+$/, '').split(/[\\\/]/).pop();
    var groups = $('#apGroups'); var opts = groups ? groups.innerHTML : '<option value="">Ungrouped</option>';
    var card = document.createElement('div'); card.className = 'pc-card'; card.id = 'pcCard';
    card.innerHTML = '<div class="pc-q">Create <b></b> at <code></code>?</div>'
      + '<div class="pc-row"><label>Folder <select class="pc-group">' + opts + '</select></label>'
      + '<button class="mini pc-go">Create it</button><button class="mini pc-no">not now</button></div>';
    card.querySelector('b').textContent = name; card.querySelector('code').textContent = folder;
    var sel = card.querySelector('.pc-group');   // Ungrouped stays selected unless the act names a folder that exists
    if (pc.group && Array.prototype.some.call(sel.options, function (o) { return o.value === pc.group; })) sel.value = pc.group;
    var row = $('.comp-row'); if (row && row.parentNode) row.parentNode.insertBefore(card, row.nextSibling); else document.body.appendChild(card);
    card.querySelector('.pc-no').addEventListener('click', function () { card.remove(); });
    card.querySelector('.pc-go').addEventListener('click', function () {
      var go = card.querySelector('.pc-go'); go.disabled = true; go.textContent = 'Creating\u2026';
      fetch('/api/rnd/new_project', { method: 'POST', headers: headers(), body: JSON.stringify({ mode: 'auto', name: name, folder_path: folder, group: sel.value || '' }) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d || !d.ok) { receipt('Not created: ' + ((d && (d.error || d.message)) || 'unknown'), true); go.disabled = false; go.textContent = 'Create it'; return; }
          var text = d.message || ('Project \u201c' + name + '\u201d created' + (sel.value ? ' in the folder ' + sel.value : '') + '.');
          card.remove(); renewInPlace(text, null, !!d.group_error);   // W4: placed in the page, never a reload
        })
        .catch(function () { receipt('That did not go through \u2014 nothing was created.', true); go.disabled = false; go.textContent = 'Create it'; });
    });
  }

  // the composer: the steward's say route (the same one the old home used)
  var say = $('#say'), send = $('#sendBtn');
  // R12 (2026-09-28, John): the unsent text is kept in this browser on every keystroke and put back after a crash,
  // a restart or a reload; a delivered turn clears it
  var DRAFT_KEY = 'anchor:draft:highseat', _draftT = null;
  function saveDraft() { try { if (say && say.value.trim()) localStorage.setItem(DRAFT_KEY, say.value); else localStorage.removeItem(DRAFT_KEY); } catch (e) {} }
  function clearDraft() { try { localStorage.removeItem(DRAFT_KEY); } catch (e) {} }
  if (say) {
    say.addEventListener('input', function () { clearTimeout(_draftT); _draftT = setTimeout(saveDraft, 250); });
    window.addEventListener('beforeunload', saveDraft);
    try { var keptDraft = localStorage.getItem(DRAFT_KEY); if (keptDraft && keptDraft.trim() && !say.value.trim()) { say.value = keptDraft; receipt('Your unsent text is back in the box.'); } } catch (e) {}
  }
  // the Seeds button opens the seed panel; a seed's button puts the steward's verb in the composer — Send is the word
  var seedBtn = $('#seedBtn'), seedPanel = $('#seedPanel');
  if (seedBtn && seedPanel) seedBtn.addEventListener('click', function () {
    var open = seedPanel.classList.toggle('open'); seedBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  document.addEventListener('click', function (e) {   // delegated (W4): a seed panel placed again keeps its buttons
    var g = e.target.closest('#seedPanel .go[data-seed-text]'); if (!g || !say) return;
    say.value = 'make ' + g.getAttribute('data-seed-text') + ' an initiative in tier 3';
    say.dispatchEvent(new Event('input'));
    say.focus(); say.scrollIntoView({ behavior: 'smooth', block: 'center' });
    receipt('The verb is in the composer — add the tier or the life area if you want, then Send.');
  });
  // W2c-2 (2026-09-30, his word: the dialogue must "engage the steward and then show the dialogue"): the composer is
  // ONE box. A Campaign verb and the new-project ask are answered by the High Seat's own route as before (a receipt,
  // the confirm card); anything else is said to the Campaign's steward — the Desk — and the exchange shows below, live
  var CAVE_DIR = (document.getElementById('dialogue') && document.getElementById('dialogue').getAttribute('data-dir')) || '';   // the Cave's own conversation (2026-10-02)
  var dlg = (window.StewardDialogue && CAMPAIGN) ? window.StewardDialogue.init({
    pid: CAMPAIGN, dir: CAVE_DIR, headers: headers, receipt: receipt, receiptKey: 'highseat_receipt',
    steward: (window.ANCHOR_BOOT && window.ANCHOR_BOOT.steward) || 'The steward', stamp: (window.ANCHOR_BOOT && window.ANCHOR_BOOT.stamp) || '',
    goalName: function (id) { var g = $('.grow[data-g="' + id + '"] .gn'); return (g && g.textContent.trim()) || id; },
    openGoal: function (id) { window.open('/project/' + encodeURIComponent(CAMPAIGN) + '?open=' + encodeURIComponent(id), '_blank', 'noopener'); },   // the goal's place, as the rendered chip opens it (Grok W2c-2)
    onAuth: function () { showLogin('The steward’s words cannot reach this page until this browser is logged in.'); },
    // W4: the steward's change, a verb said here, and a stale page each have their own way in - the record is placed in
    // the page (no line: the dialogue already shows the turn), a stale build waits for the open card to close
    you: YOU, onStamp: function () { renewInPlace(); },
    onRecord: function (text, undo, bad) { renewInPlace(text, undo, bad); },
    onBuild: function (text) { renewBuild(text); }
  }) : null;
  // the box he types into is always in view (his word, 2026-10-02): the column ends at the window's foot wherever the
  // page is scrolled (sticky alone left the composer ~150 px below the fold until he scrolled), and the box grows with
  // his dictation like the AI cockpit - the conversation above gives way, shifted up, never the box
  (function () {
    var panel = document.querySelector('.panel');
    function fit() {
      if (!panel) return;
      if (getComputedStyle(panel).position !== 'sticky') { panel.style.height = ''; return; }   // narrow screens: one column, no pin
      var top = Math.max(12, panel.getBoundingClientRect().top);
      panel.style.height = Math.max(320, window.innerHeight - top - 12) + 'px';
    }
    function grow() {
      if (!say) return;
      if (window.StewardDialogue) StewardDialogue.fitComposer(say);
      var ex = document.getElementById('exScroll'); if (ex) ex.scrollTop = ex.scrollHeight;
    }
    fit(); grow();
    window.addEventListener('scroll', fit, { passive: true });
    window.addEventListener('resize', function () { fit(); grow(); });
    if (say) { say.addEventListener('input', grow); say.addEventListener('focus', fit); }
    setTimeout(fit, 400);
  })();
  function doSend() {
    var text = (say.value || '').trim(); if (!text || send.disabled) return;
    send.disabled = true; send.textContent = 'Thinking…';
    fetch('/api/ecgberht/high_seat_say', { method: 'POST', headers: headers(), body: JSON.stringify({ text: text, verbs_only: !!dlg }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        send.disabled = false; send.textContent = 'Send';
        if (j && j.ok && j.talk && dlg) { dlg.send(text, null, dlg.mainList(), send, say, DRAFT_KEY); return; }   // not a verb: the steward, in the dialogue
        if (!j || !j.ok) { receipt((j && (j.say || j.message || j.error)) || 'No answer came back — nothing was done.', true); return; }
        say.value = ''; say.dispatchEvent(new Event('input')); clearDraft(); receipt(j.say || '…', false, j.undo || null);
        if (window.StewardDialogue && typeof window.StewardDialogue.speakConciseSummary === 'function' && (j.spoken_summary || j.say)) {
          try { window.StewardDialogue.speakConciseSummary(j.spoken_summary || j.say); } catch (e) {}
        }
        if (j.act === 'open_deliverable' && j.open_deliverable_url && window.StewardDialogue && typeof window.StewardDialogue.openCaveDeliverableDrawer === 'function') {
          window.StewardDialogue.openCaveDeliverableDrawer(j.open_deliverable_title || 'Deliverable', j.open_deliverable_url);
          return;
        }
        if (j.campaign_act && !j.read_only) { renewInPlace(); return; }   // W4: the change is placed in the page; the line and its undo stay
        if (j.project_create && j.project_create.folder) projectCard(j.project_create);   // R11: the card is here, not on the old dashboard
      })
      .catch(function () { send.disabled = false; send.textContent = 'Send'; receipt('That did not go through — nothing was done.', true); });
  }
  if (send) send.addEventListener('click', doSend);
  if (say) say.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); doSend(); } });

  // a redeploy reloads the open page, as the old home did (the verification law: a mechanism, not "refresh"): /api/version
  // every 30 s; a build other than the one this page booted with reloads it once — never while he is typing
  (function () {
    var mine = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) || '';
    if (!mine) return;
    // W2c-4: never while he types; W3b: never under an open tile either - the reload waits (renewBuild), the draft and the open tile come back after it
    setInterval(function () {
      fetch('/api/version', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
        // W3 (2026-10-08): the banner's facts moved (a report, a verified candidate) - placed in the page, never a reload
        var h = d && d.health;
        if (h && h !== healthSig) { healthPending = h; renewInPlace(); }   // acknowledged only once placed (ChatGPT W3 r2)
        var v = d && d.version; if (!v || v === mine) return;
        try { if (sessionStorage.getItem('highseat_reloaded_for') === String(v)) return; } catch (e) {}
        renewVersion = String(v); renewBuild('A new build is live \u2014 the page is renewed.');
      }).catch(function () {});
    }, 30000);
  })();

  // (2026-10-08) Cave health banner reader: polls /api/doctor/status when .main > .masthead is present
  (function () {
    if (!$('.main > .masthead')) return;
    function startHealth() {
      if (!window.AnchorCaveHealth) return;
      window.AnchorCaveHealth.start({
        headers: function () { return window.StewardDialogue ? window.StewardDialogue.authHeaders(headers()) : headers(); },
        openTool: function (t) {
          if (t === 'doctor') openWin('/doctor' + tokenQ());
          else if (t === 'zombie') openWin('/api/rnd/zombie_hunter_report' + tokenQ());
        }
      });
    }
    if (window.AnchorCaveHealth) startHealth();
    else {
      var hs = document.createElement('script');
      hs.src = '/static/cave-health.js';
      hs.onload = startHealth;
      hs.onerror = function () { hs.remove(); };
      document.head.appendChild(hs);
    }
  })();

  // Wave 6b (2026-10-15): 1-click Mark Done, Schedule Push +3d, Horizon tabs, Desk Ad-Hoc Cockpit launch, and Calendar/Email prefills
  document.addEventListener('click', function (e) {
    var openBtn = e.target.closest('[data-open-href]');
    if (openBtn) {
      e.preventDefault(); e.stopPropagation();
      window.open(openBtn.getAttribute('data-open-href'), '_blank', 'noopener');
      return;
    }
    var jumpBtn = e.target.closest('[data-jump]');
    if (jumpBtn) {
      e.preventDefault();
      var target = document.querySelector(jumpBtn.getAttribute('data-jump'));
      if (target) {
        if (target.id === 'cal') target.classList.add('open');
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      return;
    }
    var hzBtn = e.target.closest('.hz-tab[data-hz]');
    if (hzBtn) {
      e.preventDefault();
      var mode = hzBtn.getAttribute('data-hz') || 'both';
      $$('.hz-tab').forEach(function (b) { b.classList.toggle('on', b === hzBtn); });
      var tw = document.getElementById('thisWeekBoard'), rl = document.getElementById('ruler');
      if (tw) tw.hidden = (mode === 'ruler');
      if (rl) rl.hidden = (mode === 'week');
      return;
    }
    var preBtn = e.target.closest('.cal-prefill[data-say-prefill]');
    if (preBtn && say) {
      e.preventDefault(); e.stopPropagation();
      say.value = preBtn.getAttribute('data-say-prefill') || '';
      say.dispatchEvent(new Event('input'));
      say.focus(); say.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    var doneBtn = e.target.closest('[data-mark-done]');
    if (doneBtn) {
      e.preventDefault(); e.stopPropagation();
      act({
        act: 'mark_done',
        step: doneBtn.getAttribute('data-step') || '',
        target_dir: doneBtn.getAttribute('data-target-dir') || '',
        target_step: doneBtn.getAttribute('data-target-step') || ''
      });
      return;
    }
    var pushBtn = e.target.closest('[data-schedule-date]');
    if (pushBtn) {
      e.preventDefault(); e.stopPropagation();
      act({
        act: 'schedule_date',
        step: pushBtn.getAttribute('data-step') || '',
        due: pushBtn.getAttribute('data-schedule-date') || '',
        target_dir: pushBtn.getAttribute('data-target-dir') || '',
        target_step: pushBtn.getAttribute('data-target-step') || ''
      });
      return;
    }
    var syncBtn = e.target.closest('[data-comms-sync]');
    if (syncBtn) {
      e.preventDefault(); e.stopPropagation();
      syncBtn.disabled = true; syncBtn.textContent = 'Syncing\u2026';
      fetch('/api/steward/comms', { method: 'POST', headers: headers(), body: JSON.stringify({ action: 'sync_now' }) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          syncBtn.disabled = false; syncBtn.textContent = '\u21bb Sync Now';
          if (d && d.ok) renewInPlace(d.sync_receipt || 'Calendar & Email Pulse synced.');
          else receipt((d && d.error) || 'Sync did not complete.', true);
        })
        .catch(function () {
          syncBtn.disabled = false; syncBtn.textContent = '\u21bb Sync Now';
          receipt('Calendar & Email sync did not reach Anchor.', true);
        });
      return;
    }
    var openCommsBtn = e.target.closest('[data-open-comms-connect]');
    if (openCommsBtn) {
      e.preventDefault(); e.stopPropagation();
      var calSec = document.getElementById('cal');
      if (calSec) calSec.classList.add('open');
      var connModal = document.getElementById('caveCommsConnectModal');
      if (connModal) {
        connModal.hidden = false;
        connModal.scrollIntoView({ behavior: 'smooth', block: 'center' });
        var emIn = document.getElementById('caveCommsEmail');
        if (emIn) emIn.focus();
      }
      return;
    }
    if (e.target.closest('#btnCaveCommsConnectClose')) {
      e.preventDefault();
      var cModalClose = document.getElementById('caveCommsConnectModal');
      if (cModalClose) cModalClose.hidden = true;
      return;
    }
    var presetBtn = e.target.closest('[data-cave-comms-preset]');
    if (presetBtn) {
      e.preventDefault(); e.stopPropagation();
      var pType = presetBtn.getAttribute('data-cave-comms-preset') || 'gmail';
      var famSel = document.getElementById('caveCommsFamily');
      var lblIn = document.getElementById('caveCommsLabel');
      var modeSel = document.getElementById('caveCommsAuthMode');
      var emField = document.getElementById('caveCommsEmail');
      var icsField = document.getElementById('caveCommsIcsUrl');
      if (pType === 'gmail') {
        if (famSel) famSel.value = 'gmail';
        if (lblIn) lblIn.value = 'Gmail & Google Calendar';
        if (modeSel) modeSel.value = 'app_password';
        if (emField) emField.placeholder = 'your.name@example.com';
        if (icsField) icsField.placeholder = 'Optional: Google Calendar Secret Address in iCal format (.ics)';
      } else if (pType === 'outlook') {
        if (famSel) famSel.value = 'outlook';
        if (lblIn) lblIn.value = 'Microsoft Outlook & Calendar';
        if (modeSel) modeSel.value = 'app_password';
        if (emField) emField.placeholder = 'you@example.org or you@example.com';
        if (icsField) icsField.placeholder = 'Optional: Published Outlook Calendar ICS URL (.ics)';
      } else if (pType === 'ics_only') {
        if (famSel) famSel.value = 'gmail';
        if (lblIn) lblIn.value = 'Google / Outlook Calendar ICS Feed';
        if (modeSel) modeSel.value = 'ics_only';
        if (icsField) { icsField.placeholder = 'Paste Private ICS Calendar URL here (https://.../basic.ics)'; icsField.focus(); }
      }
      return;
    }
    var saveCaveCommsBtn = e.target.closest('#btnCaveCommsSaveAccount');
    if (saveCaveCommsBtn) {
      e.preventDefault(); e.stopPropagation();
      var cFam = ((document.getElementById('caveCommsFamily') || {}).value || 'gmail').trim();
      var cLbl = ((document.getElementById('caveCommsLabel') || {}).value || '').trim();
      var cEm = ((document.getElementById('caveCommsEmail') || {}).value || '').trim();
      var cMode = ((document.getElementById('caveCommsAuthMode') || {}).value || 'app_password').trim();
      var cSec = ((document.getElementById('caveCommsSecret') || {}).value || '').trim();
      var cIcs = ((document.getElementById('caveCommsIcsUrl') || {}).value || '').trim();
      var cStat = document.getElementById('caveCommsConnectStatus');
      if (!cEm && !cIcs) {
        if (cStat) cStat.textContent = 'Please enter your Email Address (for Gmail/Outlook) or a Calendar ICS URL.';
        return;
      }
      saveCaveCommsBtn.disabled = true;
      var isM365Client = (cFam === 'outlook' || cEm.toLowerCase().indexOf('psu.edu') >= 0 || cEm.toLowerCase().indexOf('axmra.com') >= 0);
      var isRawPwForM365 = isM365Client && cMode === 'app_password' && !cIcs && !(cSec.indexOf('{') === 0 && cSec.slice(-1) === '}');
      if (isRawPwForM365) {
        if (cStat) cStat.textContent = 'Starting safe Microsoft 365 + Duo 2FA browser sign-in for ' + cEm + '\u2026';
        var matchedExistingId = '';
        if (_caveCommsData && Array.isArray(_caveCommsData.accounts)) {
          var exAcc = _caveCommsData.accounts.find(function (a) { return String(a.email || '').toLowerCase() === cEm.toLowerCase(); });
          if (exAcc && exAcc.id) matchedExistingId = exAcc.id;
        }
        fetch('/api/steward/comms', {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({
            action: 'oauth_device_start',
            account_id: matchedExistingId,
            email: cEm,
            label: cLbl || 'Microsoft Outlook & Calendar'
          })
        })
          .then(function (r) { return r.json(); })
          .then(function (df) {
            return { saved: { ok: true, account_id: (df && df.account_id) || matchedExistingId, device_flow: df }, synced: {} };
          })
          .then(function (pair) {
            saveCaveCommsBtn.disabled = false;
            var d1 = pair.saved || {};
            var secEl = document.getElementById('caveCommsSecret');
            if (secEl) secEl.value = '';
            if (d1.device_flow && d1.device_flow.user_code) {
              var df = d1.device_flow;
              if (cStat) {
                cStat.innerHTML = '<b style="color:#fde68a">\ud83d\udd11 Penn State / Microsoft 365 requires Duo 2FA browser sign-in (raw password IMAP is blocked for account safety). Enter code <u>' + _escH(df.user_code) + '</u> in the Microsoft tab &amp; sign in with your new password!</b>';
              }
              var devBox0 = document.getElementById('caveCommsDeviceFlowBox');
              if (devBox0) {
                devBox0.hidden = false;
                var uCode0 = df.user_code || '';
                var vUri0 = df.verification_uri || 'https://login.microsoft.com/device';
                var stTok0 = df.state || '';
                try { if (navigator.clipboard && uCode0) navigator.clipboard.writeText(uCode0); } catch (err) {}
                devBox0.innerHTML =
                  '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">' +
                  '<div><div style="font-size:13px;font-weight:700;color:#c4b5fd">\ud83d\udd11 Microsoft 365 + Duo 2FA Sign-In (' + _escH(df.email || cEm || 'Outlook / Penn State') + ')</div>' +
                  '<div style="font-size:12px;color:#cbd5e1;margin-top:4px">1. Click <b>Open Microsoft Login</b> below (code <b>' + _escH(uCode0) + '</b> is copied to your clipboard).<br>' +
                  '2. Sign in with your <b>new PSU password + Duo 2FA</b> in the browser tab. Anchor will detect completion automatically!</div></div>' +
                  '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
                  '<code style="font-size:18px;font-weight:800;letter-spacing:2px;padding:6px 12px;border-radius:8px;background:#0d1117;border:1px solid #a78bfa;color:#fde68a">' + _escH(uCode0) + '</code>' +
                  '<a href="' + _escH(vUri0) + '" target="_blank" rel="noopener" class="mini" style="border-color:#10b981;color:#6ee7b7;font-weight:700;padding:6px 12px;text-decoration:none">\ud83d\udd17 Open ' + _escH(vUri0) + ' \u2197</a>' +
                  '</div></div>' +
                  '<div id="caveCommsDevicePollStatus" style="margin-top:8px;font-size:11.5px;color:#94a3b8">\u23f3 Waiting for you to approve 2FA in your browser (auto-checking every 4s)\u2026</div>';
                try { window.open(vUri0, '_blank', 'noopener'); } catch (err) {}
                if (window._msDevicePollTimer) clearInterval(window._msDevicePollTimer);
                var pollTicks0 = 0;
                window._msDevicePollTimer = setInterval(function () {
                  pollTicks0++;
                  if (pollTicks0 > 180) { clearInterval(window._msDevicePollTimer); return; }
                  fetch('/api/steward/comms', {
                    method: 'POST',
                    headers: headers(),
                    body: JSON.stringify({ action: 'oauth_device_poll', state: stTok0, account_id: df.account_id || matchedExistingId || '' })
                  })
                    .then(function (r2) { return r2.json(); })
                    .then(function (p) {
                      var pEl = document.getElementById('caveCommsDevicePollStatus');
                      if (p && p.status === 'connected') {
                        clearInterval(window._msDevicePollTimer);
                        if (pEl) pEl.innerHTML = '<b style="color:#6ee7b7">\u2713 ' + _escH(p.message || 'Connected via Microsoft 365 + Duo 2FA!') + '</b>';
                        if (devBox0) devBox0.hidden = true;
                        var cmHide = document.getElementById('caveCommsConnectModal');
                        if (cmHide) cmHide.hidden = true;
                        _caveCommsData = null;
                        renewInPlace(p.message || 'Connected Outlook account via Microsoft 365 + Duo 2FA.');
                      } else if (p && p.status === 'error') {
                        clearInterval(window._msDevicePollTimer);
                        if (pEl) pEl.textContent = '\u26a0 Sign-in stopped: ' + (p.error_description || p.error || 'expired');
                      }
                    })
                    .catch(function () {});
                }, 4000);
              }
            }
          })
          .catch(function () { saveCaveCommsBtn.disabled = false; });
        return;
      }
      if (cStat) cStat.textContent = 'Saving to Windows OS Credential Vault & verifying live connection\u2026';
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'save_account',
          family: cFam,
          label: cLbl || (cFam === 'outlook' ? 'Outlook & Calendar' : 'Gmail & Google Calendar'),
          email: cEm,
          auth_mode: cMode,
          secret: cSec,
          ics_url: cIcs
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d1) {
          if (d1 && d1.device_flow && d1.device_flow.user_code) {
            return { saved: d1, synced: d1 };
          }
          return fetch('/api/steward/comms', {
            method: 'POST',
            headers: headers(),
            body: JSON.stringify({ action: 'sync_now' })
          }).then(function (r2) { return r2.json(); }).then(function (d2) {
            return { saved: d1, synced: d2 };
          });
        })
        .then(function (pair) {
          saveCaveCommsBtn.disabled = false;
          var d1 = pair.saved || {};
          var d2 = pair.synced || d1;
          var secEl = document.getElementById('caveCommsSecret');
          if (secEl) secEl.value = '';
          if (d1 && d1.device_flow && d1.device_flow.user_code) {
            var df = d1.device_flow;
            if (cStat) {
              cStat.innerHTML = '<b style="color:#fde68a">\ud83d\udd11 Penn State / Microsoft 365 requires Duo 2FA browser sign-in (raw password IMAP is blocked for account safety). Enter code <u>' + _escH(df.user_code) + '</u> in the Microsoft tab!</b>';
            }
            var fakeBtn = document.querySelector('[data-comms-ms-device-auth="' + (d1.account_id || '') + '"]') || document.querySelector('[data-comms-ms-device-auth]');
            var devBox0 = document.getElementById('caveCommsDeviceFlowBox');
            if (devBox0) {
              devBox0.hidden = false;
              var uCode0 = df.user_code || '';
              var vUri0 = df.verification_uri || 'https://login.microsoft.com/device';
              var stTok0 = df.state || '';
              try { if (navigator.clipboard && uCode0) navigator.clipboard.writeText(uCode0); } catch (err) {}
              devBox0.innerHTML =
                '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">' +
                '<div><div style="font-size:13px;font-weight:700;color:#c4b5fd">\ud83d\udd11 Microsoft 365 + Duo 2FA Sign-In (' + _escH(df.email || cEm || 'Outlook / Penn State') + ')</div>' +
                '<div style="font-size:12px;color:#cbd5e1;margin-top:4px">1. Click <b>Open Microsoft Login</b> below (code <b>' + _escH(uCode0) + '</b> is copied to your clipboard).<br>' +
                '2. Sign in with your new PSU password + Duo 2FA in the browser tab. Anchor will detect completion automatically!</div></div>' +
                '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
                '<code style="font-size:18px;font-weight:800;letter-spacing:2px;padding:6px 12px;border-radius:8px;background:#0d1117;border:1px solid #a78bfa;color:#fde68a">' + _escH(uCode0) + '</code>' +
                '<a href="' + _escH(vUri0) + '" target="_blank" rel="noopener" class="mini" style="border-color:#10b981;color:#6ee7b7;font-weight:700;padding:6px 12px;text-decoration:none">\ud83d\udd17 Open ' + _escH(vUri0) + ' \u2197</a>' +
                '</div></div>' +
                '<div id="caveCommsDevicePollStatus" style="margin-top:8px;font-size:11.5px;color:#94a3b8">\u23f3 Waiting for you to approve 2FA in your browser (auto-checking every 4s)\u2026</div>';
              try { window.open(vUri0, '_blank', 'noopener'); } catch (err) {}
              if (window._msDevicePollTimer) clearInterval(window._msDevicePollTimer);
              var pollTicks0 = 0;
              window._msDevicePollTimer = setInterval(function () {
                pollTicks0++;
                if (pollTicks0 > 180) { clearInterval(window._msDevicePollTimer); return; }
                fetch('/api/steward/comms', {
                  method: 'POST',
                  headers: headers(),
                  body: JSON.stringify({ action: 'oauth_device_poll', state: stTok0, account_id: df.account_id || d1.account_id || '' })
                })
                  .then(function (r2) { return r2.json(); })
                  .then(function (p) {
                    var pEl = document.getElementById('caveCommsDevicePollStatus');
                    if (p && p.status === 'connected') {
                      clearInterval(window._msDevicePollTimer);
                      if (pEl) pEl.innerHTML = '<b style="color:#6ee7b7">\u2713 ' + _escH(p.message || 'Connected via Microsoft 365 + Duo 2FA!') + '</b>';
                      _caveCommsData = null;
                      renewInPlace(p.message || 'Connected Outlook account via Microsoft 365 + Duo 2FA.');
                    } else if (p && p.status === 'error') {
                      clearInterval(window._msDevicePollTimer);
                      if (pEl) pEl.textContent = '\u26a0 Sign-in stopped: ' + (p.error_description || p.error || 'expired');
                    }
                  })
                  .catch(function () {});
              }, 4000);
            } else if (fakeBtn) {
              fakeBtn.click();
            }
            return;
          }
          var accs = (d2 && d2.accounts) || (d1 && d1.accounts) || [];
          var matchedAcc = accs.find(function (a) { return a.id === d1.account_id || a.email === cEm; }) || {};
          var imapNote = matchedAcc.last_imap_note || d1.last_imap_note || '';
          var icsNote = matchedAcc.last_ics_note || d1.last_ics_note || '';
          if (matchedAcc.status === 'auth_error' || (imapNote && imapNote.indexOf('IMAP connection note:') === 0)) {
            if (cStat) cStat.textContent = '\u26a0 Saved in OS Vault, but live sign-in reported: ' + imapNote;
            receipt('Saved account, but provider sign-in needs attention: ' + imapNote, true);
          } else if (d2 && d2.ok) {
            var summaryMsg = [imapNote, icsNote].filter(Boolean).join(' \u00b7 ') || 'Connected to Windows OS Vault & synced Calendar/Email.';
            if (cStat) cStat.textContent = '\u2713 ' + summaryMsg;
            _caveCommsData = null;
            renewInPlace('Connected ' + (cEm || cLbl || cFam) + ' (' + summaryMsg + ').');
          } else {
            if (cStat) cStat.textContent = (d2 && d2.error) || 'Saved account, but initial sync reported an issue.';
          }
        })
        .catch(function () {
          saveCaveCommsBtn.disabled = false;
          if (cStat) cStat.textContent = 'Could not reach Anchor comms service.';
        });
      return;
    }
    var autoOutlookBtn = e.target.closest('[data-comms-auto-outlook]');
    if (autoOutlookBtn) {
      e.preventDefault(); e.stopPropagation();
      autoOutlookBtn.disabled = true;
      var cStatOut = document.getElementById('caveCommsConnectStatus');
      if (cStatOut) cStatOut.textContent = 'Checking running Windows Outlook desktop app\u2026';
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'auto_connect_local_outlook' })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          autoOutlookBtn.disabled = false;
          if (d && d.outlook_running) {
            renewInPlace(d.message || 'Connected to local Windows Outlook desktop app.');
          } else {
            var msg = (d && d.message) || 'Outlook desktop app is not currently running; use the Quick-Connect form to connect via App Password or ICS URL.';
            if (cStatOut) cStatOut.textContent = msg;
            var cm2 = document.getElementById('caveCommsConnectModal');
            if (cm2) cm2.hidden = false;
            receipt(msg);
          }
        })
        .catch(function () {
          autoOutlookBtn.disabled = false;
          receipt('Local Outlook check did not reach Anchor.', true);
        });
      return;
    }
    var gm2faBtn = e.target.closest('[data-comms-gmail-2fa]');
    if (gm2faBtn) {
      e.preventDefault(); e.stopPropagation();
      var gmAccId = gm2faBtn.getAttribute('data-comms-gmail-2fa') || '';
      var gmEmail = gm2faBtn.getAttribute('data-comms-edit-email') || 'account';
      var gmBox = document.getElementById('caveCommsDeviceFlowBox');
      var calEl = document.getElementById('cal');
      if (calEl && !calEl.classList.contains('open')) {
        calEl.classList.add('open');
        var togEl = document.getElementById('calTog');
        if (togEl) togEl.textContent = 'Collapse';
      }
      if (gmBox) {
        gmBox.hidden = false;
        gmBox.innerHTML = '\u23f3 Launching Google 2FA Phone-Prompt window for <b>' + gmEmail + '</b> using your stored OS Vault password (no password entry needed)\u2026';
      }
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'gmail_2fa_start', account_id: gmAccId, email: gmEmail })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d || !d.ok) {
            if (gmBox) gmBox.innerHTML = '\u26a0 Could not start Gmail 2FA helper: ' + ((d && d.error) || 'Unknown error');
            return;
          }
          if (window._startCaveGmail2faPoll) window._startCaveGmail2faPoll(gmAccId, gmEmail, d);
        });
      return;
    }
    var editAccBtn = e.target.closest('[data-comms-edit-account]');
    if (editAccBtn) {
      e.preventDefault(); e.stopPropagation();
      var calSecE = document.getElementById('cal');
      if (calSecE && !calSecE.classList.contains('open')) {
        calSecE.classList.add('open');
        var togE = document.getElementById('calTog');
        if (togE) togE.textContent = 'Collapse';
      }
      var cmEdit = document.getElementById('caveCommsConnectModal');
      if (cmEdit) {
        cmEdit.hidden = false;
        try { cmEdit.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (err) {}
      }
      var eFam = editAccBtn.getAttribute('data-comms-edit-family') || 'gmail';
      var eEm = editAccBtn.getAttribute('data-comms-edit-email') || '';
      var eLbl = editAccBtn.getAttribute('data-comms-edit-label') || '';
      var famEl = document.getElementById('caveCommsFamily');
      var lblEl = document.getElementById('caveCommsLabel');
      var emEl = document.getElementById('caveCommsEmail');
      var modeEl = document.getElementById('caveCommsAuthMode');
      var secEl = document.getElementById('caveCommsSecret');
      var stEl = document.getElementById('caveCommsConnectStatus');
      if (famEl) famEl.value = eFam;
      if (lblEl && eLbl) lblEl.value = eLbl;
      if (emEl && eEm) emEl.value = eEm;
      if (modeEl) modeEl.value = 'app_password';
      if (secEl) {
        secEl.placeholder = eFam === 'outlook'
          ? ('Enter new password for ' + (eEm || 'Outlook / PSU') + ' (or click Sign In with Microsoft 365 + 2FA below)')
          : ('Enter password or 16-char App Password for ' + (eEm || 'Gmail'));
        secEl.focus();
      }
      if (stEl) {
        if (eFam === 'outlook') {
          stEl.innerHTML = '\ud83d\udd11 Updating <b>' + _escH(eEm || 'Outlook / Penn State') + '</b>: enter your new password above and click <b>Save to OS Vault, Test &amp; Sync</b> (or click <b>\ud83d\udd11 Sign In with Microsoft 365 + 2FA</b>) to complete Penn State Duo 2FA in your browser.';
        } else {
          stEl.innerHTML = '\ud83d\udd11 Updating <b>' + _escH(eEm || 'Gmail') + '</b>: paste your password or 16-character App Password above and click <b>Save to OS Vault, Test &amp; Sync</b>.';
        }
      }
      return;
    }
    var msDevBtn = e.target.closest('[data-comms-ms-device-auth]');
    if (msDevBtn) {
      e.preventDefault(); e.stopPropagation();
      var devAccId = msDevBtn.getAttribute('data-comms-ms-device-auth') || '';
      var devEmail = msDevBtn.getAttribute('data-comms-ms-email') || ((document.getElementById('caveCommsEmail') || {}).value || '').trim();
      var devLabel = msDevBtn.getAttribute('data-comms-ms-label') || ((document.getElementById('caveCommsLabel') || {}).value || '').trim();
      var devBox = document.getElementById('caveCommsDeviceFlowBox');
      if (devBox) {
        devBox.hidden = false;
        devBox.innerHTML = '\u23f3 Requesting Microsoft 365 + 2FA Device Sign-In code for <b>' + (devEmail || 'Outlook / Penn State M365') + '</b>\u2026';
      }
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'oauth_device_start',
          account_id: devAccId,
          email: devEmail,
          label: devLabel
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d || !d.ok) {
            if (devBox) devBox.innerHTML = '\u26a0 Could not start Microsoft 365 Device Sign-In: ' + ((d && d.error) || 'Unknown error');
            return;
          }
          var uCode = d.user_code || '';
          var vUri = d.verification_uri || 'https://login.microsoft.com/device';
          var stTok = d.state || '';
          try { if (navigator.clipboard && uCode) navigator.clipboard.writeText(uCode); } catch (err) {}
          if (devBox) {
            devBox.innerHTML =
              '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">' +
              '<div><div style="font-size:13px;font-weight:700;color:#c4b5fd">\ud83d\udd11 Microsoft 365 + 2FA Sign-In (' + (d.email || 'Outlook / Penn State') + ')</div>' +
              '<div style="font-size:12px;color:#cbd5e1;margin-top:4px">1. Click <b>Open Microsoft Login</b> below (code <b>' + uCode + '</b> is copied to your clipboard).<br>' +
              '2. Complete your normal Penn State (Duo) or Axmra login + 2FA in the browser tab. Anchor will detect completion automatically!</div></div>' +
              '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
              '<code style="font-size:18px;font-weight:800;letter-spacing:2px;padding:6px 12px;border-radius:8px;background:#0d1117;border:1px solid #a78bfa;color:#fde68a">' + uCode + '</code>' +
              '<a href="' + vUri + '" target="_blank" rel="noopener" class="mini" style="border-color:#10b981;color:#6ee7b7;font-weight:700;padding:6px 12px;text-decoration:none">\ud83d\udd17 Open ' + vUri + ' \u2197</a>' +
              '</div></div>' +
              '<div id="caveCommsDevicePollStatus" style="margin-top:8px;font-size:11.5px;color:#94a3b8">\u23f3 Waiting for you to approve 2FA in your browser (auto-checking every 4s)\u2026</div>';
          }
          try { window.open(vUri, '_blank', 'noopener'); } catch (err) {}
          if (window._msDevicePollTimer) clearInterval(window._msDevicePollTimer);
          var pollTicks = 0;
          window._msDevicePollTimer = setInterval(function () {
            pollTicks++;
            if (pollTicks > 180) {
              clearInterval(window._msDevicePollTimer);
              return;
            }
            fetch('/api/steward/comms', {
              method: 'POST',
              headers: headers(),
              body: JSON.stringify({ action: 'oauth_device_poll', state: stTok, account_id: d.account_id || devAccId })
            })
              .then(function (r2) { return r2.json(); })
              .then(function (p) {
                var pEl = document.getElementById('caveCommsDevicePollStatus');
                if (p && p.status === 'connected') {
                  clearInterval(window._msDevicePollTimer);
                  if (pEl) pEl.innerHTML = '<b style="color:#6ee7b7">\u2713 ' + (p.message || 'Connected via Microsoft 365 + 2FA!') + '</b>';
                  renewInPlace(p.message || 'Connected Outlook account via Microsoft 365 + 2FA.');
                } else if (p && p.status === 'error') {
                  clearInterval(window._msDevicePollTimer);
                  if (pEl) pEl.textContent = '\u26a0 Sign-in stopped: ' + (p.error_description || p.error || 'expired');
                }
              })
              .catch(function () {});
          }, 4000);
        });
      return;
    }
    var caveOauthBtn = e.target.closest('[data-cave-comms-oauth]');
    if (caveOauthBtn) {
      e.preventDefault(); e.stopPropagation();
      var oFam = ((document.getElementById('caveCommsFamily') || {}).value || 'gmail').trim();
      var oEm = ((document.getElementById('caveCommsEmail') || {}).value || '').trim();
      var oStat = document.getElementById('caveCommsConnectStatus');
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'oauth_pkce_start', family: oFam, email: oEm })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var authUrl = (d && d.authorize_url) || (d && d.pkce && d.pkce.authorize_url) || '';
          var modeEl = document.getElementById('caveCommsAuthMode');
          if (modeEl) modeEl.value = 'oauth_token';
          if (oStat && authUrl) {
            oStat.innerHTML = '\u2713 OAuth2 PKCE challenge ready. <a href="' + authUrl + '" target="_blank" rel="noopener" style="color:#58a6ff">Open Provider Sign-In \u2197</a> or use the 1-click App Password / ICS links above.';
          }
        });
      return;
    }
    var rmCommsBtn = e.target.closest('[data-comms-remove-id]');
    if (rmCommsBtn) {
      e.preventDefault(); e.stopPropagation();
      var rmId = rmCommsBtn.getAttribute('data-comms-remove-id') || '';
      if (!rmId) return;
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'remove_account', id: rmId })
      })
        .then(function (r) { return r.json(); })
        .then(function () {
          renewInPlace('Removed account ' + rmId + ' from Calendar & Email Pulse.');
        });
      return;
    }
    var merrillPresetBtn = e.target.closest('[data-collab-preset-merrill]');
    if (merrillPresetBtn) {
      e.preventDefault(); e.stopPropagation();
      var pIdIn = document.getElementById('collabPeerId');
      var pLblIn = document.getElementById('collabPeerLabel');
      var pTrIn = document.getElementById('collabPeerTransport');
      var pEpIn = document.getElementById('collabPeerEndpoint');
      if (pIdIn) pIdIn.value = 'merrill-mothership';
      if (pLblIn) pLblIn.value = 'Merrill Liechty (Collaborator Mothership)';
      if (pTrIn) pTrIn.value = 'tailscale_http';
      if (pEpIn && !pEpIn.value) pEpIn.focus();
      var stC = document.getElementById('collabModalStatus');
      if (stC) stC.textContent = 'Pre-filled Merrill Liechty peer details. Paste his Tailscale/Git endpoint (or leave blank to register for packet handoff) and click Save Peer.';
      return;
    }
    var synthBtn = e.target.closest('[data-triage-synthesize]');
    if (synthBtn) {
      e.preventDefault(); e.stopPropagation();
      synthBtn.disabled = true; synthBtn.textContent = 'Synthesizing\u2026';
      fetch('/api/steward/comms', { method: 'POST', headers: headers(), body: JSON.stringify({ action: 'synthesize_brief' }) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          synthBtn.disabled = false; synthBtn.textContent = '\u2726 Synthesize Brief';
          var box = document.getElementById('triageExecBrief');
          if (d && d.ok && d.brief) {
            if (box) {
              box.hidden = false;
              box.innerHTML = '<b>\u2726 Chief-of-Staff Executive Brief (' + (d.brief.generated_at || '') + '):</b> ' +
                (d.brief.summary || '') +
                (d.brief.priorities && d.brief.priorities.length ? '<div style="margin-top:4px;color:#8b949e">\u2022 ' + d.brief.priorities.join(' &nbsp;\u00b7&nbsp; \u2022 ') + '</div>' : '');
            }
            receipt('Executive Brief synthesized across active roadmaps & correspondence.');
          } else {
            receipt((d && d.error) || 'Could not synthesize Executive Brief.', true);
          }
        })
        .catch(function () {
          synthBtn.disabled = false; synthBtn.textContent = '\u2726 Synthesize Brief';
          receipt('Executive Brief request did not reach Anchor.', true);
        });
      return;
    }
    var draftBtn = e.target.closest('[data-comms-draft-reply]');
    if (draftBtn) {
      e.preventDefault(); e.stopPropagation();
      var modal = document.getElementById('caveCommsDraftModal');
      if (modal) {
        modal.hidden = false;
        var toIn = document.getElementById('commsDraftTo');
        var subIn = document.getElementById('commsDraftSubject');
        var bodyIn = document.getElementById('commsDraftBody');
        var stSpan = document.getElementById('commsDraftStatus');
        var sub = draftBtn.getAttribute('data-comms-draft-subject') || '';
        var to = draftBtn.getAttribute('data-comms-draft-to') || '';
        var proj = draftBtn.getAttribute('data-comms-draft-project') || '';
        var step = draftBtn.getAttribute('data-comms-draft-step') || '';
        modal.setAttribute('data-project-name', proj);
        modal.setAttribute('data-step-id', step);
        if (toIn) toIn.value = to;
        if (subIn) subIn.value = sub && !/^re:/i.test(sub) ? ('Re: ' + sub) : sub;
        if (bodyIn && !bodyIn.value) {
          bodyIn.value = 'Hi' + (to ? ' ' + to : '') + ',\n\nFollowing up on ' + (sub || proj || 'our next milestone') + ':\n- \n\nBest,\nJohn';
        }
        if (stSpan) stSpan.textContent = '';
        if (bodyIn) bodyIn.focus();
      }
      return;
    }
    if (e.target.closest('#btnCommsDraftClose')) {
      e.preventDefault();
      var m0 = document.getElementById('caveCommsDraftModal');
      if (m0) m0.hidden = true;
      return;
    }
    var saveDraftBtn = e.target.closest('#btnCommsDraftSave');
    if (saveDraftBtn) {
      e.preventDefault(); e.stopPropagation();
      var m1 = document.getElementById('caveCommsDraftModal');
      var toVal = (document.getElementById('commsDraftTo') || {}).value || '';
      var subVal = (document.getElementById('commsDraftSubject') || {}).value || '';
      var bodyVal = (document.getElementById('commsDraftBody') || {}).value || '';
      var stEl = document.getElementById('commsDraftStatus');
      var mailtoA = document.getElementById('btnCommsDraftMailto');
      saveDraftBtn.disabled = true;
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'create_draft',
          to_addr: toVal,
          subject: subVal,
          body: bodyVal,
          project_name: m1 ? (m1.getAttribute('data-project-name') || '') : '',
          step_id: m1 ? (m1.getAttribute('data-step-id') || '') : ''
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          saveDraftBtn.disabled = false;
          if (d && d.ok) {
            if (stEl) stEl.textContent = '\u2713 Saved ' + (d.eml_file || 'draft.eml');
            if (mailtoA && d.mailto_url) { mailtoA.href = d.mailto_url; mailtoA.hidden = false; }
            receipt(d.receipt || 'Reply draft saved to .anchor/drafts/.');
          } else {
            if (stEl) stEl.textContent = (d && d.error) || 'Failed to save draft.';
          }
        })
        .catch(function () {
          saveDraftBtn.disabled = false;
          if (stEl) stEl.textContent = 'Draft request did not reach Anchor.';
        });
      return;
    }
    var collabSyncBtn = e.target.closest('[data-collab-sync],[data-collab-sync-peer]');
    if (collabSyncBtn) {
      e.preventDefault(); e.stopPropagation();
      var peerId = collabSyncBtn.getAttribute('data-collab-sync-peer') || '';
      collabSyncBtn.disabled = true;
      fetch('/api/steward/collab', { method: 'POST', headers: headers(), body: JSON.stringify({ action: 'sync_now', peer_id: peerId }) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          collabSyncBtn.disabled = false;
          if (d && d.ok) {
            var note = (d.peer_sync && d.peer_sync.sync_note) ? (' (' + d.peer_sync.sync_note + ')') : '';
            renewInPlace('Shared Cockpits & Step Leases synced across Motherships' + note + '.');
          } else receipt((d && d.error) || 'Mothership sync did not complete.', true);
        })
        .catch(function () {
          collabSyncBtn.disabled = false;
          receipt('Mothership sync did not reach Anchor.', true);
        });
      return;
    }
    var collabOpenModal = e.target.closest('[data-collab-add-peer],[data-collab-open-import]');
    if (collabOpenModal) {
      e.preventDefault(); e.stopPropagation();
      var cm = document.getElementById('caveCollabModal');
      if (cm) {
        cm.hidden = !cm.hidden;
        if (!cm.hidden) {
          var focusEl = collabOpenModal.hasAttribute('data-collab-open-import')
            ? document.getElementById('collabImportJson')
            : document.getElementById('collabPeerId');
          if (focusEl) focusEl.focus();
        }
      }
      return;
    }
    if (e.target.closest('#btnCollabModalClose')) {
      e.preventDefault();
      var cmClose = document.getElementById('caveCollabModal');
      if (cmClose) cmClose.hidden = true;
      return;
    }
    var collabPeerSaveBtn = e.target.closest('#btnCollabPeerSave');
    if (collabPeerSaveBtn) {
      e.preventDefault(); e.stopPropagation();
      var pidVal = ((document.getElementById('collabPeerId') || {}).value || '').trim() || ('peer-' + Date.now().toString(36));
      var plblVal = ((document.getElementById('collabPeerLabel') || {}).value || '').trim() || pidVal;
      var ptrVal = ((document.getElementById('collabPeerTransport') || {}).value || 'tailscale_http').trim();
      var pepVal = ((document.getElementById('collabPeerEndpoint') || {}).value || '').trim();
      var stCollab = document.getElementById('collabModalStatus');
      collabPeerSaveBtn.disabled = true;
      fetch('/api/steward/collab', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'register_peer',
          peer: { id: pidVal, label: plblVal, transport: ptrVal, endpoint: pepVal, role: 'collaborator' }
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          collabPeerSaveBtn.disabled = false;
          if (d && d.ok) {
            if (stCollab) stCollab.textContent = '\u2713 Linked ' + plblVal;
            renewInPlace('Linked Collaborator Mothership (' + plblVal + ').');
          } else {
            if (stCollab) stCollab.textContent = (d && d.error) || 'Could not register peer.';
          }
        })
        .catch(function () {
          collabPeerSaveBtn.disabled = false;
          if (stCollab) stCollab.textContent = 'Could not reach /api/steward/collab.';
        });
      return;
    }
    var collabImportBtn = e.target.closest('#btnCollabPacketImport');
    if (collabImportBtn) {
      e.preventDefault(); e.stopPropagation();
      var tdir = ((document.getElementById('collabImportTargetDir') || {}).value || '').trim();
      var rawPkt = ((document.getElementById('collabImportJson') || {}).value || '').trim();
      var stImp = document.getElementById('collabModalStatus');
      var parsedPkt = null;
      try { parsedPkt = JSON.parse(rawPkt); } catch (err) {
        if (stImp) stImp.textContent = 'Invalid JSON in packet box.';
        return;
      }
      collabImportBtn.disabled = true;
      fetch('/api/steward/collab', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'import_packet', cdir: tdir, packet: parsedPkt })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          collabImportBtn.disabled = false;
          if (d && d.ok) {
            if (stImp) stImp.textContent = '\u2713 Imported (' + (d.merged_steps || 0) + ' steps merged).';
            renewInPlace('Imported portable Cockpit Packet (' + (d.merged_steps || 0) + ' steps, ' + (d.merged_leases || 0) + ' leases).');
          } else {
            if (stImp) stImp.textContent = (d && d.error) || 'Import failed.';
          }
        })
        .catch(function () {
          collabImportBtn.disabled = false;
          if (stImp) stImp.textContent = 'Import request failed.';
        });
      return;
    }
    var claimBtn = e.target.closest('[data-collab-claim-cdir]');
    if (claimBtn) {
      e.preventDefault(); e.stopPropagation();
      var claimDir = claimBtn.getAttribute('data-collab-claim-cdir') || '';
      var claimStep = claimBtn.getAttribute('data-collab-claim-step') || '';
      claimBtn.disabled = true;
      fetch('/api/steward/collab', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'claim_lease', cdir: claimDir, step_id: claimStep })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          claimBtn.disabled = false;
          if (d && d.ok) renewInPlace('Claimed step lease on ' + claimStep + '.');
          else receipt((d && d.error) || 'Could not claim step lease.', true);
        })
        .catch(function () { claimBtn.disabled = false; receipt('Lease claim request failed.', true); });
      return;
    }
    var relBtn = e.target.closest('[data-collab-release-cdir]');
    if (relBtn) {
      e.preventDefault(); e.stopPropagation();
      var relDir = relBtn.getAttribute('data-collab-release-cdir') || '';
      var relStep = relBtn.getAttribute('data-collab-release-step') || '';
      relBtn.disabled = true;
      fetch('/api/steward/collab', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'release_lease', cdir: relDir, step_id: relStep })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          relBtn.disabled = false;
          if (d && d.ok) renewInPlace('Released step lease on ' + relStep + '.');
          else receipt((d && d.error) || 'Could not release step lease.', true);
        })
        .catch(function () { relBtn.disabled = false; receipt('Lease release request failed.', true); });
      return;
    }
    var collabExportBtn = e.target.closest('[data-collab-export]');
    if (collabExportBtn) {
      e.preventDefault(); e.stopPropagation();
      var cdir = collabExportBtn.getAttribute('data-collab-export') || '';
      var cname = collabExportBtn.getAttribute('data-collab-name') || 'Project';
      collabExportBtn.disabled = true;
      fetch('/api/steward/collab', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'export_packet', cdir: cdir })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          collabExportBtn.disabled = false;
          if (d && d.ok && d.packet) {
            var pre = document.getElementById('collabPacketPreview');
            if (pre) {
              pre.hidden = false;
              pre.textContent = JSON.stringify(d.packet, null, 2).slice(0, 1800);
            }
            receipt('Exported portable Cockpit Packet for ' + cname + ' (digest ' + String(d.packet.packet_digest || '').slice(0, 10) + '\u2026).');
          } else {
            receipt((d && d.error) || 'Could not export cockpit packet.', true);
          }
        })
        .catch(function () {
          collabExportBtn.disabled = false;
          receipt('Export packet request failed.', true);
        });
      return;
    }
  });

  // Wave 15: HTML5 Drag-and-Drop rescheduling across the 4-column Today & This Week board (#thisWeekBoard)
  var twDragPayload = null;
  document.addEventListener('dragstart', function (e) {
    var card = e.target.closest && e.target.closest('.tw-card[data-tw-card]');
    if (!card) return;
    twDragPayload = {
      target_dir: card.getAttribute('data-target-dir') || '',
      target_step: card.getAttribute('data-target-step') || ''
    };
    card.classList.add('dragging');
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', JSON.stringify(twDragPayload)); } catch (err) {}
    }
  });
  document.addEventListener('dragend', function (e) {
    var card = e.target.closest && e.target.closest('.tw-card[data-tw-card]');
    if (card) card.classList.remove('dragging');
    $$('.tw-col.drop-over').forEach(function (c) { c.classList.remove('drop-over'); });
  });
  document.addEventListener('dragover', function (e) {
    if (!twDragPayload) return;
    var col = e.target.closest && e.target.closest('.tw-col[data-tw-drop-col]');
    if (!col) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    col.classList.add('drop-over');
  });
  document.addEventListener('dragleave', function (e) {
    var col = e.target.closest && e.target.closest('.tw-col[data-tw-drop-col]');
    if (col && (!e.relatedTarget || !col.contains(e.relatedTarget))) col.classList.remove('drop-over');
  });
  document.addEventListener('drop', function (e) {
    var col = e.target.closest && e.target.closest('.tw-col[data-tw-drop-col]');
    if (!col || !twDragPayload) return;
    e.preventDefault();
    col.classList.remove('drop-over');
    var newDate = col.getAttribute('data-tw-target-date') || '';
    var payload = twDragPayload;
    twDragPayload = null;
    if (newDate && payload.target_dir && payload.target_step) {
      act({
        act: 'schedule_date',
        due: newDate,
        target_dir: payload.target_dir,
        target_step: payload.target_step
      });
    }
  });

  // Wave 19 (2026-10-19): 5-Horizon Chief-of-Staff drawer toggles, Level-3 item detail expansion,
  // Dated Schedule Ruler toggle, Multi-Mothership Collab strip toggle, and 4 Foundry-Icon Steward action buttons
  document.addEventListener('click', function (e) {
    var hzCard = e.target.closest && e.target.closest('[data-hz-toggle]');
    if (hzCard) {
      e.preventDefault();
      var key = hzCard.getAttribute('data-hz-toggle') || '';
      var drawer = document.getElementById('hzDrawer-' + key);
      var wasOpen = hzCard.classList.contains('open');
      $$('#shTriage .chz-card').forEach(function (c) {
        c.classList.remove('open');
        c.setAttribute('aria-expanded', 'false');
      });
      $$('#shTriage .chz-drawer').forEach(function (d) { d.hidden = true; });
      if (!wasOpen && drawer) {
        hzCard.classList.add('open');
        hzCard.setAttribute('aria-expanded', 'true');
        drawer.hidden = false;
      }
      return;
    }
    var hzClose = e.target.closest && e.target.closest('[data-hz-close]');
    if (hzClose) {
      e.preventDefault();
      $$('#shTriage .chz-card').forEach(function (c) {
        c.classList.remove('open');
        c.setAttribute('aria-expanded', 'false');
      });
      $$('#shTriage .chz-drawer').forEach(function (d) { d.hidden = true; });
      return;
    }
    var hzItem = e.target.closest && e.target.closest('.hz-item');
    if (hzItem && !e.target.closest('a, button')) {
      hzItem.classList.toggle('expanded');
      return;
    }
    var toggleDated = e.target.closest && e.target.closest('[data-toggle-dated]');
    if (toggleDated) {
      e.preventDefault();
      var wrap = document.getElementById('datedScheduleWrap');
      if (wrap) {
        wrap.hidden = !wrap.hidden;
        if (!wrap.hidden) wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      return;
    }
    var collabHead = e.target.closest && e.target.closest('#caveCollabStrip > .cal-h');
    if (collabHead && !e.target.closest('button, a, input')) {
      var strip = document.getElementById('caveCollabStrip');
      var body = document.getElementById('caveCollabBody');
      if (strip && body) {
        var open = !strip.classList.contains('open');
        strip.classList.toggle('open', open);
        body.hidden = !open;
        var tog = strip.querySelector('.cal-tog');
        if (tog) tog.textContent = open ? 'Collapse' : 'Expand';
      }
      return;
    }
    var fBtn = e.target.closest && e.target.closest('[data-foundry-action]');
    if (fBtn && say) {
      e.preventDefault();
      var actKey = fBtn.getAttribute('data-foundry-action') || '';
      var prompts = {
        new_cockpit: 'Create a new AI Cockpit for project "',
        brainstorm: 'Let\u2019s brainstorm on ',
        modify_today: 'Update Today\u2019s priorities / move cockpit status: ',
        desk_calendar: 'Add to Desk / schedule deadline: '
      };
      say.value = prompts[actKey] || '';
      say.dispatchEvent(new Event('input'));
      say.focus();
      return;
    }
  });
  function ensureHeaderDownloadButtons() {
    var hdrRight = document.querySelector('.hdr-right') || document.querySelector('.top-actions') || document.querySelector('header');
    if (!hdrRight) return;
    if (!document.getElementById('hs-onboard-wizard-btn')) {
      var wBtn = document.createElement('a');
      wBtn.id = 'hs-onboard-wizard-btn';
      wBtn.className = 'btn';
      wBtn.href = '/onboard-wizard';
      wBtn.title = 'Open the 7-Step Onboarding & Setup Wizard (or Sandbox Test Walkthrough)';
      wBtn.style.cssText = 'text-decoration:none;border-color:rgba(124,92,255,0.55);color:#c4b5fd;font-weight:600';
      wBtn.textContent = '🧭 Setup & Onboard';
      hdrRight.insertBefore(wBtn, hdrRight.firstChild);
    }
    if (!document.getElementById('hs-download-test-exe-btn')) {
      var tBtn = document.createElement('a');
      tBtn.id = 'hs-download-test-exe-btn';
      tBtn.className = 'btn';
      tBtn.href = '/static/downloads/Anchor-Test-Onboard.zip?download=1';
      tBtn.setAttribute('download', 'Anchor-Test-Onboard.zip');
      tBtn.title = 'Download isolated Desktop Onboard-Test Anchor.exe package (runs on port 8787 + isolated AppData so your live Anchor.exe & Tailscale stay untouched)';
      tBtn.style.cssText = 'text-decoration:none;border-color:rgba(245,158,11,0.55);color:#fcd34d;font-weight:600';
      tBtn.textContent = '🧪 Desktop Onboard-Test.exe';
      var ref = document.getElementById('hs-onboard-wizard-btn');
      if (ref && ref.nextSibling) hdrRight.insertBefore(tBtn, ref.nextSibling);
      else hdrRight.appendChild(tBtn);
    }
    if (!document.getElementById('hs-download-prod-exe-btn')) {
      var pBtn = document.createElement('a');
      pBtn.id = 'hs-download-prod-exe-btn';
      pBtn.className = 'btn';
      pBtn.href = '/static/downloads/Anchor.zip?download=1';
      pBtn.setAttribute('download', 'Anchor.zip');
      pBtn.title = 'Download production Anchor.exe package (shareable with collaborators)';
      pBtn.style.cssText = 'text-decoration:none;border-color:rgba(16,185,129,0.55);color:#6ee7b7;font-weight:600';
      pBtn.textContent = '📦 Anchor.exe';
      var ref2 = document.getElementById('hs-onboard-wizard-btn');
      if (ref2 && ref2.nextSibling) hdrRight.insertBefore(pBtn, ref2.nextSibling);
      else hdrRight.appendChild(pBtn);
    }
  }
  ensureHeaderDownloadButtons();

  // Option 1 + Click-to-Full (Mockup 3): Interactive 4-View Calendar (iPhone Rolling Stream, Day, Week, Month)
  // & Steward 2-Bucket Email Triage (Seen, Downgrade, Upgrade, Open Body, Save Attachment)
  var _caveCommsData = null;
  var _caveCalView = (window.innerWidth > 680 ? 'week' : 'iphone');
  try {
    var savedView = localStorage.getItem('anchor_cave_cal_view_v2');
    if (savedView && (savedView === 'week' || savedView === 'day' || savedView === 'month' || savedView === 'iphone')) {
      _caveCalView = savedView;
    }
  } catch (e) {}
  var _caveCalDay = '';

  function _escH(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function _shiftIsoDate(iso, days) {
    var p = String(iso || '2026-11-02').split('-');
    var dt = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
    dt.setDate(dt.getDate() + days);
    return dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0') + '-' + String(dt.getDate()).padStart(2, '0');
  }

  function _fmtFriendlyDate(iso) {
    var p = String(iso || '').split('-');
    if (p.length < 3) return iso;
    var dt = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
    var dows = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    var mos = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return dows[dt.getDay()] + ', ' + mos[dt.getMonth()] + ' ' + dt.getDate();
  }

  var _caveSources = { psu: true, axmra: true, gmail: true };
  try {
    var savedSrc = localStorage.getItem('anchor_cave_comms_sources_v1');
    if (savedSrc) {
      var parsedSrc = JSON.parse(savedSrc);
      if (parsedSrc && typeof parsedSrc === 'object') {
        _caveSources = {
          psu: parsedSrc.psu !== false,
          axmra: parsedSrc.axmra !== false,
          gmail: parsedSrc.gmail !== false
        };
      }
    }
  } catch (e) {}

  function _matchesSourceKey(badgeOrSourceStr) {
    var s = String(badgeOrSourceStr || '').toLowerCase();
    if (!s) return true;
    var hasPsu = s.indexOf('psu') >= 0 || s.indexOf('penn state') >= 0 || (s.indexOf('outlook') >= 0 && s.indexOf('axmra') < 0);
    var hasAxmra = s.indexOf('axmra') >= 0;
    var hasGmail = s.indexOf('gmail') >= 0 || s.indexOf('google') >= 0;
    if (!hasPsu && !hasAxmra && !hasGmail) return true;
    return (hasPsu && _caveSources.psu) || (hasAxmra && _caveSources.axmra) || (hasGmail && _caveSources.gmail);
  }

  function _eventMatchesSources(ev) {
    if (!ev) return false;
    var cals = ev.calendars && ev.calendars.length ? ev.calendars.join(' + ') : (ev.calendar_badge || ev.project_name || '');
    return _matchesSourceKey(cals);
  }

  function _applyCaveMailFolderMode(mode) {
    var m = (mode === 'inbox' || mode === 'sent' || mode === 'all') ? mode : 'all';
    var grid = document.getElementById('caveMailBucketsGrid');
    if (grid) grid.setAttribute('data-mail-folder-mode', m);
    $$('[data-cave-mail-folder]').forEach(function (btn) {
      btn.classList.toggle('on', btn.getAttribute('data-cave-mail-folder') === m);
    });
    var impCol = document.getElementById('caveMailImportantCol');
    var sentCol = document.getElementById('caveMailSentCol');
    var othCol = document.getElementById('caveMailOtherCol');
    if (impCol) impCol.hidden = (m === 'sent');
    if (othCol) othCol.hidden = (m === 'sent');
    if (sentCol) {
      sentCol.hidden = (m === 'inbox');
      sentCol.style.marginTop = (m === 'sent') ? '0px' : '8px';
      sentCol.style.paddingTop = (m === 'sent') ? '0px' : '8px';
      sentCol.style.borderTop = (m === 'sent') ? 'none' : '1px solid rgba(16,185,129,0.35)';
    }
  }
  window._applyCaveMailFolderMode = _applyCaveMailFolderMode;

  function _applySourceFilterToDOM() {
    if (_caveCommsData && typeof _hydrateMailCardsFromCommsData === 'function') {
      _hydrateMailCardsFromCommsData(_caveCommsData);
    }
    $$('[data-comms-source-filter]').forEach(function (cb) {
      var k = cb.getAttribute('data-comms-source-filter') || '';
      if (k in _caveSources) cb.checked = !!_caveSources[k];
    });
    var visImp = 0, visOth = 0, visSent = 0;
    $$('#caveMailImportantList .cave-mail-card').forEach(function (card) {
      var src = card.getAttribute('data-mail-source') || '';
      var show = _matchesSourceKey(src);
      card.hidden = !show;
      if (show) visImp++;
    });
    $$('#caveMailSentList .cave-mail-card').forEach(function (card) {
      var src = card.getAttribute('data-mail-source') || '';
      var show = _matchesSourceKey(src);
      card.hidden = !show;
      if (show) visSent++;
    });
    $$('#caveMailOtherList .cave-mail-card').forEach(function (card) {
      var src = card.getAttribute('data-mail-source') || '';
      var show = _matchesSourceKey(src);
      card.hidden = !show;
      if (show) visOth++;
    });
    var impB = document.getElementById('caveImpCountBadge');
    if (impB && document.querySelectorAll('#caveMailImportantList .cave-mail-card').length) {
      impB.innerHTML = '\u26a1 ' + visImp + ' to Address';
    }
    var sentB = document.getElementById('caveSentCountBadge');
    if (sentB && document.querySelectorAll('#caveMailSentList .cave-mail-card').length) {
      sentB.textContent = String(visSent);
    }
    var othB = document.getElementById('caveOthCountBadge');
    if (othB && document.querySelectorAll('#caveMailOtherList .cave-mail-card').length) {
      othB.innerHTML = '\ud83d\udce5 ' + visOth + ' Not Important';
    }
    var visPrep = 0;
    $$('#caveUpcomingPrepStrip .cave-prep-card').forEach(function (card) {
      var src = card.getAttribute('data-cal-source') || '';
      var show = _matchesSourceKey(src);
      card.hidden = !show;
      if (show) visPrep++;
    });
    var prepStrip = document.getElementById('caveUpcomingPrepStrip');
    if (prepStrip && document.querySelectorAll('#caveUpcomingPrepStrip .cave-prep-card').length) {
      prepStrip.hidden = (visPrep === 0);
    }
    $$('#caveCalViewport .cave-cal-card').forEach(function (card) {
      var src = card.getAttribute('data-cal-source') || '';
      card.hidden = !_matchesSourceKey(src);
    });
    $$('[data-cave-cal-view]').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-cave-cal-view') === _caveCalView);
    });
    if (_caveCommsData) {
      _renderCaveCalendarViewport();
    }
  }
  window._applySourceFilterToDOM = _applySourceFilterToDOM;

  function _renderGmail2faStateBox(gmEmail, p) {
    var gmBox = document.getElementById('caveCommsDeviceFlowBox');
    if (!gmBox || !p) return;
    gmBox.hidden = false;
    if (p.status === 'connected') {
      gmBox.innerHTML =
        '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding:6px 4px">' +
          '<div style="font-size:13px;font-weight:750;color:#6ee7b7">\u2713 ' + _escH(p.message || ('Gmail 2FA verified & permanent credential stored in OS Vault for ' + (gmEmail || p.email || 'Gmail') + '!')) + '</div>' +
          '<span class="comms-badge emerald">Connected &amp; Synced</span>' +
        '</div>';
      setTimeout(function () {
        if (gmBox) gmBox.hidden = true;
      }, 4000);
      return;
    }
    var existingSmsInp = document.getElementById('caveGmailSmsCodeInput');
    if (existingSmsInp && document.activeElement === existingSmsInp) {
      var msgEl = document.getElementById('caveGmail2faPollMsg');
      if (msgEl) msgEl.textContent = p.message || 'Check your phone to tap Yes or enter the 6-digit SMS code!';
      return;
    }
    var prevSmsVal = existingSmsInp ? existingSmsInp.value : '';
    var chNum = String(p.challenge_number || '').trim();
    var numBanner = chNum
      ? '<div style="display:flex;align-items:center;gap:14px;margin-top:8px;padding:10px 14px;border-radius:10px;background:rgba(16,185,129,0.18);border:2px solid #10b981">' +
          '<div style="font-size:32px;font-weight:900;color:#6ee7b7;background:#064e3b;padding:6px 18px;border-radius:10px;border:2px solid #34d399;letter-spacing:0.06em">' + _escH(chNum) + '</div>' +
          '<div>' +
            '<div style="font-size:14px;font-weight:800;color:#f8fafc">\ud83d\udcf1 On your phone: Tap <b>YES</b>, then select number <span style="color:#6ee7b7;font-size:17px;text-decoration:underline">' + _escH(chNum) + '</span>!</div>' +
            '<div style="font-size:11.5px;color:#cbd5e1;margin-top:2px">Once you tap ' + _escH(chNum) + ' on your phone, Anchor automatically stores the permanent credential in your Windows OS Vault.</div>' +
          '</div>' +
        '</div>'
      : '';
    var smsRow =
      '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:8px;padding:8px 10px;border-radius:8px;background:rgba(15,23,42,0.75);border:1px solid #334155">' +
        '<span style="font-size:11.5px;color:#cbd5e1;font-weight:650">\ud83d\udcac Or if Google texted a 6-digit SMS code to (\u2022\u2022\u2022) \u2022\u2022\u2022-\u2022\u202289:</span>' +
        '<input type="text" id="caveGmailSmsCodeInput" value="' + _escH(prevSmsVal) + '" placeholder="6-digit code (e.g. 482910)" style="width:170px;background:#0b1120;border:1px solid #38bdf8;color:#f8fafc;border-radius:6px;padding:5px 9px;font-size:12.5px;font-weight:700;letter-spacing:0.06em">' +
        '<button type="button" class="tw-btn done" id="btnCaveGmailSubmitSms" data-gmail-acc="' + _escH(p.account_id || 'comms-3a9bfa74') + '">\u2713 Submit SMS Code</button>' +
      '</div>';
    gmBox.innerHTML =
      '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">' +
        '<div style="font-size:13px;font-weight:700;color:#7dd3fc">\ud83d\udcf1 Gmail 2FA Phone Prompt (' + _escH(gmEmail || p.email || 'Gmail') + ')</div>' +
        '<span class="comms-badge sky">Auto-submitted stored OS Vault password</span>' +
      '</div>' +
      '<div id="caveGmail2faPollMsg" style="font-size:12px;color:#e2e8f0;margin-top:4px">' + _escH(p.message || 'Check your phone to tap Yes!') + '</div>' +
      numBanner +
      smsRow;
  }

  window._startCaveGmail2faPoll = function (gmAccId, gmEmail, initialData) {
    if (initialData) _renderGmail2faStateBox(gmEmail, initialData);
    if (window._gm2faPollTimer) clearInterval(window._gm2faPollTimer);
    var gTicks = 0;
    var lastShownNum = '';
    window._gm2faPollTimer = setInterval(function () {
      gTicks++;
      if (gTicks > 150) { clearInterval(window._gm2faPollTimer); return; }
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'gmail_2fa_poll', account_id: gmAccId || 'comms-3a9bfa74' })
      })
        .then(function (r2) { return r2.json(); })
        .then(function (p) {
          if (!p) return;
          _renderGmail2faStateBox(gmEmail, p);
          if (p.challenge_number && p.challenge_number !== lastShownNum) {
            lastShownNum = p.challenge_number;
            receipt('\ud83d\udcf1 Google 2FA: Tap YES on your phone and select number ' + p.challenge_number + '!');
          }
          if (p.status === 'connected') {
            clearInterval(window._gm2faPollTimer);
            var gmBoxDone = document.getElementById('caveCommsDeviceFlowBox');
            if (gmBoxDone) gmBoxDone.hidden = true;
            var cmDone = document.getElementById('caveCommsConnectModal');
            if (cmDone) cmDone.hidden = true;
            _caveCommsData = null;
            renewInPlace(p.message || 'Connected Gmail via 2FA Phone Prompt!');
          } else if (p.status === 'error' || p.status === 'expired') {
            clearInterval(window._gm2faPollTimer);
          }
        })
        .catch(function () {});
    }, 2000);
  };

  function _parseHmMins(hm, fallback) {
    var m = String(hm || '').match(/(\d{1,2}):(\d{2})/);
    if (!m) return fallback;
    return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
  }

  function _eventSpanInfo(ev) {
    var st = String(ev.start_time || '').trim();
    var et = String(ev.end_time || '').trim();
    var tLbl = String(ev.time_label || '').trim();
    if ((!st || st === 'All day') && tLbl.indexOf(':') >= 0) {
      var matches = tLbl.match(/(\d{1,2}:\d{2})/g);
      if (matches && matches.length >= 1) st = matches[0];
      if (matches && matches.length >= 2 && !et) et = matches[1];
    }
    var isAllDay = (!st || st.toLowerCase().indexOf('all') >= 0 || st.toLowerCase().indexOf('due') >= 0);
    if (isAllDay) {
      return { isAllDay: true, startMins: 480, endMins: 540, durMins: 60, rangeLabel: tLbl || 'All day' };
    }
    var sM = _parseHmMins(st, 540);
    var eM = _parseHmMins(et, sM + (parseInt(ev.duration_mins, 10) || 60));
    if (eM <= sM) eM = sM + Math.max(30, parseInt(ev.duration_mins, 10) || 60);
    var dur = Math.max(30, eM - sM);
    var sH = String(Math.floor(sM / 60)).padStart(2, '0') + ':' + String(sM % 60).padStart(2, '0');
    var eH = String(Math.floor(eM / 60)).padStart(2, '0') + ':' + String(eM % 60).padStart(2, '0');
    var durStr = dur >= 60 ? ((Math.round((dur / 60) * 10) / 10) + 'h') : (dur + 'm');
    return {
      isAllDay: false,
      startMins: sM,
      endMins: eM,
      durMins: dur,
      startHm: sH,
      endHm: eH,
      durLabel: durStr,
      rangeLabel: sH + '\u2013' + eH + ' (' + durStr + ')'
    };
  }

  function _renderCaveCalEventRow(ev) {
    var sp = _eventSpanInfo(ev);
    var tone = ev.tone || (String(ev.calendar_badge || '').toLowerCase().indexOf('axmra') >= 0 ? 'emerald' : 'sky');
    var mergedHtml = ev.merged_badge
      ? '<span class="comms-badge amber" title="Smart-merged across multiple calendars">' + _escH(ev.merged_badge) + '</span>'
      : '';
    var doneHtml = (ev.folder && ev.step_id)
      ? '<button type="button" class="tw-btn done" data-mark-done="1" data-target-dir="' + _escH(ev.folder) + '" data-target-step="' + _escH(ev.step_id) + '">\u2713 Done</button>'
      : '';
    var projHtml = ev.project_id
      ? '<a class="tw-proj" href="/project/' + _escH(ev.project_id) + '" target="_blank" rel="noopener">' + _escH(ev.project_name || 'Project') + '</a>'
      : '<span class="tw-proj">' + _escH(ev.calendar_badge || ev.project_name || 'Calendar') + '</span>';
    var locHtml = ev.location ? '<div class="comms-item-sub">\ud83d\udccd ' + _escH(String(ev.location).slice(0, 90)) + '</div>' : '';
    var calsJoined = (ev.calendars && ev.calendars.length) ? ev.calendars.join(' + ') : (ev.calendar_badge || ev.project_name || 'Calendar');
    return (
      '<div class="comms-item ' + _escH(tone) + ' cave-cal-card" data-cave-cal-open="' + _escH(ev.id || ev.uid || '') + '" data-cal-title="' + _escH(ev.title || '') + '" data-cal-date="' + _escH(ev.date || '') + '" data-cal-start="' + _escH(sp.startHm || ev.start_time || '') + '" data-cal-end="' + _escH(sp.endHm || ev.end_time || '') + '" data-cal-loc="' + _escH(ev.location || '') + '" data-cal-source="' + _escH(calsJoined) + '" style="cursor:pointer" title="Click to blow up Calendar Event Dialogue Tile">' +
      '<div class="comms-item-top">' +
      '<span class="comms-badge ' + _escH(tone) + '">' + _escH(_fmtFriendlyDate(ev.date)) + ' \u00b7 ' + _escH(sp.rangeLabel) + '</span>' +
      projHtml + mergedHtml + doneHtml +
      '</div>' +
      '<div class="comms-item-title">' + _escH(ev.title || '') + '</div>' +
      locHtml +
      '</div>'
    );
  }

  function _renderCaveCalendarViewport() {
    var vp = document.getElementById('caveCalViewport');
    var lbl = document.getElementById('caveCalDateLabel');
    if (!vp || !_caveCommsData) return;
    var rawEvs = _caveCommsData.calendar_events_all || _caveCommsData.calendar_events || [];
    var allEvs = rawEvs.filter(_eventMatchesSources);
    var visCntEl = document.getElementById('caveCalVisibleCount');
    if (visCntEl) visCntEl.textContent = String(allEvs.length);
    var nowIso = new Date().toISOString().slice(0, 10);
    if (!_caveCalDay) {
      var firstUp = allEvs.find(function (e) { return e.date >= nowIso; });
      _caveCalDay = (firstUp && firstUp.date) || nowIso;
    }

    $$('[data-cave-cal-view]').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-cave-cal-view') === _caveCalView);
    });

    if (_caveCalView === 'iphone') {
      if (lbl) lbl.textContent = '\ud83d\udcf1 Apple iPhone Rolling Stream (\u2191 Past \u00b7 \ud83d\udd34 NOW \u00b7 \u2193 Upcoming)';
      var pastEvs = allEvs.filter(function (e) { return e.date < nowIso; }).slice(-8);
      var futEvs = allEvs.filter(function (e) { return e.date >= nowIso; }).slice(0, 28);
      var html = [];
      if (pastEvs.length) {
        html.push('<div style="font-size:10px;font-weight:750;color:var(--text-dim);text-transform:uppercase;padding:2px 4px">\u2191 Earlier Events (Scroll Up \u00b7 Click any event to open Dialogue Tile)</div>');
        pastEvs.forEach(function (ev) {
          html.push('<div style="opacity:0.65">' + _renderCaveCalEventRow(ev) + '</div>');
        });
      }
      html.push(
        '<div class="cave-now-anchor" id="caveIphoneNowAnchor">' +
        '<span class="cave-now-dot"></span>' +
        '<span>\ud83d\udd34 NOW \u2014 ' + _escH(_fmtFriendlyDate(nowIso)) + ' \u00b7 Click any event below to open Dialogue Tile \u2193</span>' +
        '</div>'
      );
      if (futEvs.length) {
        futEvs.forEach(function (ev) { html.push(_renderCaveCalEventRow(ev)); });
      } else {
        html.push('<div class="tw-empty">No upcoming calendar events for the checked source(s).</div>');
      }
      vp.innerHTML = html.join('');
      setTimeout(function () {
        var anch = document.getElementById('caveIphoneNowAnchor');
        if (anch && vp) vp.scrollTop = Math.max(0, anch.offsetTop - vp.offsetTop - 60);
      }, 30);
      return;
    }

    if (_caveCalView === 'day') {
      if (lbl) lbl.textContent = '\ud83d\udcc5 Day Time-Block Schedule \u2014 ' + _fmtFriendlyDate(_caveCalDay) + ' (' + _caveCalDay + ')';
      var dayEvs = allEvs.filter(function (e) { return e.date === _caveCalDay; });
      var allDayEvs = [];
      var timedEvs = [];
      dayEvs.forEach(function (ev) {
        var sp = _eventSpanInfo(ev);
        if (sp.isAllDay) allDayEvs.push({ ev: ev, sp: sp });
        else timedEvs.push({ ev: ev, sp: sp });
      });
      timedEvs.sort(function (a, b) { return a.sp.startMins - b.sp.startMins || b.sp.durMins - a.sp.durMins; });

      // Assign side-by-side columns when events overlap in time
      var clusters = [];
      timedEvs.forEach(function (item) {
        var lastCluster = clusters[clusters.length - 1];
        if (!lastCluster || item.sp.startMins >= lastCluster.maxEnd) {
          clusters.push({ items: [item], maxEnd: item.sp.endMins });
        } else {
          lastCluster.items.push(item);
          if (item.sp.endMins > lastCluster.maxEnd) lastCluster.maxEnd = item.sp.endMins;
        }
      });
      clusters.forEach(function (cl) {
        var colEnds = [];
        cl.items.forEach(function (it) {
          var assigned = -1;
          for (var c = 0; c < colEnds.length; c++) {
            if (it.sp.startMins >= colEnds[c]) { assigned = c; colEnds[c] = it.sp.endMins; break; }
          }
          if (assigned < 0) { assigned = colEnds.length; colEnds.push(it.sp.endMins); }
          it.colIdx = assigned;
        });
        cl.items.forEach(function (it) { it.colCount = colEnds.length; });
      });

      var startHour = 7, endHour = 20, pxPerHour = 52;
      var totalHeight = (endHour - startHour + 1) * pxPerHour;
      var out = [];
      if (!dayEvs.length) {
        out.push('<div class="tw-empty" style="margin-bottom:8px">No events scheduled on ' + _escH(_fmtFriendlyDate(_caveCalDay)) + '. Click <b>+ Add Calendar Event</b> or <b>Next \u25b6</b>.</div>');
      }
      if (allDayEvs.length) {
        out.push('<div style="margin-bottom:8px">' + allDayEvs.map(function (x) { return _renderCaveCalEventRow(x.ev); }).join('') + '</div>');
      }
      out.push('<div class="cave-day-timegrid" style="position:relative;height:' + totalHeight + 'px;border:1px solid #1e293b;border-radius:10px;background:#090d16;overflow:hidden">');
      for (var hr = startHour; hr <= endHour; hr++) {
        var topPx = (hr - startHour) * pxPerHour;
        var hDisp = (hr > 12 ? (hr - 12) : hr) + ':00 ' + (hr >= 12 ? 'PM' : 'AM');
        out.push(
          '<div style="position:absolute;left:0;right:0;top:' + topPx + 'px;height:' + pxPerHour + 'px;border-top:1px dashed rgba(51,65,85,0.55);display:flex;align-items:flex-start;pointer-events:none">' +
            '<span style="width:66px;padding:3px 6px;font-size:10px;font-weight:700;color:#64748b;text-align:right;flex-shrink:0">' + hDisp + '</span>' +
          '</div>'
        );
      }
      timedEvs.forEach(function (it) {
        var ev = it.ev, sp = it.sp;
        var clampedStart = Math.max(startHour * 60, Math.min(endHour * 60, sp.startMins));
        var clampedEnd = Math.max(clampedStart + 30, Math.min((endHour + 1) * 60, sp.endMins));
        var topPx = Math.round(((clampedStart - startHour * 60) / 60) * pxPerHour);
        var heightPx = Math.max(36, Math.round(((clampedEnd - clampedStart) / 60) * pxPerHour) - 2);
        var colW = 100 / (it.colCount || 1);
        var leftPct = (it.colIdx || 0) * colW;
        var calsJoined = (ev.calendars && ev.calendars.length) ? ev.calendars.join(' + ') : (ev.calendar_badge || ev.project_name || 'Calendar');
        var isMerged = !!ev.merged_badge;
        var isAxmra = calsJoined.toLowerCase().indexOf('axmra') >= 0 && !isMerged;
        var isGoogleOnly = calsJoined.toLowerCase().indexOf('google') >= 0 && calsJoined.toLowerCase().indexOf('psu') < 0 && !isMerged;
        var borderCol = isMerged ? '#f59e0b' : (isAxmra ? '#10b981' : (isGoogleOnly ? '#eab308' : '#38bdf8'));
        var bgCol = isMerged ? 'rgba(245,158,11,0.22)' : (isAxmra ? 'rgba(16,185,129,0.20)' : (isGoogleOnly ? 'rgba(234,179,8,0.18)' : 'rgba(56,189,248,0.20)'));
        out.push(
          '<div class="cave-cal-card" data-cave-cal-open="' + _escH(ev.id || ev.uid || '') + '" data-cal-title="' + _escH(ev.title || '') + '" data-cal-date="' + _escH(ev.date || '') + '" data-cal-start="' + _escH(sp.startHm) + '" data-cal-end="' + _escH(sp.endHm) + '" data-cal-loc="' + _escH(ev.location || '') + '" data-cal-source="' + _escH(calsJoined) + '" ' +
          'title="' + _escH(sp.rangeLabel + ' \u00b7 ' + (ev.title || '') + ' (' + calsJoined + ')') + '" ' +
          'style="position:absolute;top:' + topPx + 'px;height:' + heightPx + 'px;left:calc(70px + (100% - 76px) * ' + (leftPct / 100).toFixed(4) + ');width:calc((100% - 76px) * ' + (colW / 100).toFixed(4) + ' - 4px);' +
          'background:' + bgCol + ';border:1px solid ' + borderCol + ';border-left:4px solid ' + borderCol + ';border-radius:7px;padding:4px 8px;box-sizing:border-box;overflow:hidden;cursor:pointer;z-index:2;box-shadow:0 2px 8px rgba(0,0,0,0.35)">' +
            '<div style="display:flex;align-items:center;justify-content:space-between;gap:4px;flex-wrap:wrap;font-size:10.5px;line-height:1.2">' +
              '<b style="color:#7dd3fc">' + _escH(sp.rangeLabel) + '</b>' +
              '<span style="font-size:9.5px;color:#fde68a;font-weight:700">' + _escH(ev.merged_badge || calsJoined) + '</span>' +
            '</div>' +
            '<div style="font-weight:750;font-size:12px;color:#f8fafc;margin-top:2px;line-height:1.25">' + _escH(ev.title || '') + '</div>' +
            (ev.location && heightPx >= 52 ? '<div style="font-size:10px;color:#cbd5e1;margin-top:2px">\ud83d\udccd ' + _escH(String(ev.location).slice(0, 70)) + '</div>' : '') +
          '</div>'
        );
      });
      out.push('</div>');
      vp.innerHTML = out.join('');
      return;
    }

    if (_caveCalView === 'week') {
      var p = _caveCalDay.split('-');
      var baseD = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
      var dow = baseD.getDay();
      var diffMon = (dow === 0 ? -6 : 1 - dow);
      baseD.setDate(baseD.getDate() + diffMon);
      var monIso = baseD.getFullYear() + '-' + String(baseD.getMonth() + 1).padStart(2, '0') + '-' + String(baseD.getDate()).padStart(2, '0');
      var sunIso = _shiftIsoDate(monIso, 6);
      if (lbl) lbl.textContent = '\ud83d\udcc6 Week View (Full Event Duration Blocks) \u2014 ' + _fmtFriendlyDate(monIso) + ' \u2013 ' + _fmtFriendlyDate(sunIso);
      var cols = ['<div class="cave-week-grid">'];
      for (var i = 0; i < 7; i++) {
        var dIso = _shiftIsoDate(monIso, i);
        var cEvs = allEvs.filter(function (e) { return e.date === dIso; });
        var isT = (dIso === nowIso || dIso === _caveCalDay);
        cols.push(
          '<div class="cave-week-col' + (isT ? ' today' : '') + '" data-cave-pick-day="' + dIso + '" style="cursor:pointer" title="Click day header to open proportional Day Time-Block Schedule">' +
          '<div class="cave-week-hdr">' + _escH(_fmtFriendlyDate(dIso)) + '</div>' +
          (cEvs.length
            ? cEvs.map(function (ev) {
                var sp = _eventSpanInfo(ev);
                var t = ev.merged_badge ? 'amber' : (ev.tone || 'sky');
                var calsJoined = (ev.calendars && ev.calendars.length) ? ev.calendars.join(' + ') : (ev.calendar_badge || 'Calendar');
                var minH = Math.max(48, Math.min(180, Math.round(sp.durMins * 0.56)));
                return (
                  '<div class="cave-week-chip ' + _escH(t) + '" data-cave-cal-open="' + _escH(ev.id || ev.uid || '') + '" data-cal-title="' + _escH(ev.title || '') + '" data-cal-date="' + _escH(ev.date || '') + '" data-cal-start="' + _escH(sp.startHm || ev.start_time || '') + '" data-cal-end="' + _escH(sp.endHm || ev.end_time || '') + '" data-cal-loc="' + _escH(ev.location || '') + '" data-cal-source="' + _escH(calsJoined) + '" style="min-height:' + minH + 'px;display:flex;flex-direction:column;justify-content:space-between;border-left-width:3px" title="Click to open Event Dialogue Tile (' + _escH(sp.rangeLabel) + ')">' +
                  '<div>' +
                    '<div style="font-weight:800;color:#7dd3fc;font-size:10px">' + _escH(sp.rangeLabel) + '</div>' +
                    '<div style="font-weight:700;color:#f8fafc;margin-top:2px;line-height:1.25">' + _escH(ev.title || '') + '</div>' +
                  '</div>' +
                  '<div style="font-size:9px;color:' + (ev.merged_badge ? '#fde68a' : 'var(--text-dim)') + ';margin-top:3px;font-weight:' + (ev.merged_badge ? '700' : '500') + '">' +
                    (ev.merged_badge ? ('\ud83d\udd17 ' + _escH(calsJoined)) : _escH(calsJoined)) +
                  '</div>' +
                  '</div>'
                );
              }).join('')
            : '<div style="font-size:10px;color:var(--text-dim2);text-align:center;margin-top:16px">\u2014</div>') +
          '</div>'
        );
      }
      cols.push('</div>');
      vp.innerHTML = cols.join('');
      return;
    }

    if (_caveCalView === 'month') {
      var ym = _caveCalDay.slice(0, 7);
      var yp = ym.split('-');
      var yr = parseInt(yp[0], 10), mo = parseInt(yp[1], 10);
      var mosFull = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
      if (lbl) lbl.textContent = '\ud83d\uddd3 Month View \u2014 ' + mosFull[mo - 1] + ' ' + yr + ' (Click event for Dialogue Tile, or day for Day View)';
      var firstDow = new Date(yr, mo - 1, 1).getDay();
      var daysInMo = new Date(yr, mo, 0).getDate();
      var mCells = ['<div class="cave-month-grid">'];
      ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].forEach(function (d) {
        mCells.push('<div class="cave-month-dow">' + d + '</div>');
      });
      for (var b = 0; b < firstDow; b++) {
        mCells.push('<div class="cave-month-cell" style="opacity:0.25"></div>');
      }
      for (var dNum = 1; dNum <= daysInMo; dNum++) {
        var cellIso = yr + '-' + String(mo).padStart(2, '0') + '-' + String(dNum).padStart(2, '0');
        var cellEvs = allEvs.filter(function (e) { return e.date === cellIso; });
        var isCur = (cellIso === _caveCalDay || cellIso === nowIso);
        mCells.push(
          '<div class="cave-month-cell' + (isCur ? ' today' : '') + '" data-cave-pick-day="' + cellIso + '">' +
          '<div class="cave-month-num">' + dNum + (cellEvs.length ? ' <span style="color:#7dd3fc">(' + cellEvs.length + ')</span>' : '') + '</div>' +
          cellEvs.slice(0, 3).map(function (ev) {
            var cTone = ev.merged_badge ? 'amber' : (ev.tone || 'sky');
            var calsJoined = (ev.calendars && ev.calendars.length) ? ev.calendars.join(' + ') : (ev.calendar_badge || 'Calendar');
            return '<div class="cave-month-dot ' + _escH(cTone) + '" data-cave-cal-open="' + _escH(ev.id || ev.uid || '') + '" data-cal-title="' + _escH(ev.title || '') + '" data-cal-date="' + _escH(ev.date || '') + '" data-cal-start="' + _escH(ev.start_time || '') + '" data-cal-end="' + _escH(ev.end_time || '') + '" data-cal-loc="' + _escH(ev.location || '') + '" data-cal-source="' + _escH(calsJoined) + '" title="Click to open Event Dialogue Tile: ' + _escH((ev.time_label || '') + ' ' + (ev.title || '')) + '">' + _escH((ev.start_time || '').slice(0, 5) + ' ' + (ev.title || '')) + '</div>';
          }).join('') +
          (cellEvs.length > 3 ? '<div style="font-size:9px;color:var(--text-dim)">+' + (cellEvs.length - 3) + ' more</div>' : '') +
          '</div>'
        );
      }
      mCells.push('</div>');
      vp.innerHTML = mCells.join('');
    }
  }

  var _activeEmailDialogue = null;

  function _openEmailDialogueTile(uid, fallbackSubj, fallbackSender, fallbackSource) {
    var dlg = document.getElementById('caveCommsDialogueTile');
    var mailPane = document.getElementById('caveEmailDialoguePane');
    var calPane = document.getElementById('caveCalDialoguePane');
    if (!dlg || !mailPane) return;
    dlg.hidden = false;
    mailPane.hidden = false;
    if (calPane) calPane.hidden = true;

    var subjEl = document.getElementById('caveDlgMailSubject');
    var badgeEl = document.getElementById('caveDlgMailBadge');
    var metaEl = document.getElementById('caveDlgMailMeta');
    var thList = document.getElementById('caveDialogueThreadList');
    var noteEl = document.getElementById('caveDlgStewardNote');
    var stMsg = document.getElementById('caveReplyStatusMsg');
    if (subjEl) subjEl.textContent = fallbackSubj || 'Loading email conversation...';
    if (badgeEl) badgeEl.textContent = fallbackSource || 'Inbox';
    if (metaEl) metaEl.textContent = 'From: ' + (fallbackSender || 'Loading...');
    if (thList) thList.innerHTML = '<div style="color:#94a3b8;padding:10px">\u23f3 Loading full message body, thread history &amp; Steward suggested reply\u2026</div>';
    if (stMsg) stMsg.textContent = '';
    try { dlg.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (err) {}

    fetch('/api/steward/comms', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({
        action: 'email_dialogue',
        uid: uid,
        subject: fallbackSubj || '',
        sender_email: fallbackSender || ''
      })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) {
          if (thList) thList.innerHTML = '<div style="color:#fda4af;padding:10px">\u26a0 Could not load email detail: ' + _escH((d && d.error) || 'Unknown error') + '</div>';
          return;
        }
        _activeEmailDialogue = d;
        if (subjEl) subjEl.textContent = _sanitizeEmailSandboxText(d.subject || fallbackSubj || '(No Subject)');
        if (badgeEl) badgeEl.textContent = (d.account_badge || fallbackSource || 'Inbox') + ' \u00b7 \ud83d\udd12 Sandboxed (Read-Only / No Execution)';
        if (metaEl) metaEl.textContent = 'From: ' + (d.from || d.sender_email || '') + (d.date ? (' \u00b7 ' + d.date) : '');
        var attBtn = document.getElementById('btnCaveDlgDownloadAtt');
        if (attBtn) {
          attBtn.hidden = !d.has_attachments;
          attBtn.setAttribute('data-comms-download-att', d.uid || uid);
          attBtn.setAttribute('data-comms-att-subject', d.subject || '');
        }
        var msgs = d.thread_messages || [];
        if (thList) {
          thList.innerHTML = msgs.map(function (m) {
            var isSent = m.direction === 'sent';
            var borderCol = isSent ? '#10b981' : (m.is_current ? '#38bdf8' : '#334155');
            return (
              '<div style="padding:9px 11px;border-radius:8px;background:' + (isSent ? 'rgba(16,185,129,0.08)' : '#111827') + ';border:1px solid #1e293b;border-left:4px solid ' + borderCol + '">' +
                '<div style="display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap;font-size:11px;color:#94a3b8;margin-bottom:4px">' +
                  '<b style="color:' + (isSent ? '#6ee7b7' : '#f8fafc') + '">' + _escH(m.from || 'Message') + '</b>' +
                  '<span>' + _escH(m.account_badge || '') + (m.date ? (' \u00b7 ' + _escH(m.date)) : '') + '</span>' +
                '</div>' +
                '<div style="font-size:12px;color:#e2e8f0;white-space:pre-wrap;line-height:1.45">' + _escH(_sanitizeEmailSandboxText(m.body || '')) + '</div>' +
              '</div>'
            );
          }).join('');
        }
        var sd = d.steward_draft || {};
        var toIn = document.getElementById('caveReplyTo');
        var subIn = document.getElementById('caveReplySubject');
        var bodyIn = document.getElementById('caveReplyBody');
        if (toIn) toIn.value = sd.to || d.sender_email || fallbackSender || '';
        if (subIn) subIn.value = sd.subject || ('Re: ' + (d.subject || fallbackSubj || ''));
        if (bodyIn) bodyIn.value = sd.draft_body || '';
        if (noteEl) noteEl.textContent = (sd.steward_note || '\u2728 Steward suggested draft ready to edit & send') + ' (\ud83d\udd12 Email Sandbox: strictly information-only, zero command execution)';
      })
      .catch(function () {
        if (thList) thList.innerHTML = '<div style="color:#fda4af;padding:10px">Could not reach Anchor comms service.</div>';
      });
  }

  function _openCalDialogueTile(opts) {
    var dlg = document.getElementById('caveCommsDialogueTile');
    var mailPane = document.getElementById('caveEmailDialoguePane');
    var calPane = document.getElementById('caveCalDialoguePane');
    if (!dlg || !calPane) return;
    dlg.hidden = false;
    calPane.hidden = false;
    if (mailPane) mailPane.hidden = true;

    var isNew = !!(opts && opts.isNew);
    var modeB = document.getElementById('caveDlgCalModeBadge');
    var hdrT = document.getElementById('caveDlgCalHeaderTitle');
    if (modeB) modeB.textContent = isNew ? '\u2795 New Calendar Event' : '\ud83d\udcc5 Calendar Event Dialogue';
    if (hdrT) hdrT.textContent = isNew ? 'Add Event & Sync Back to Selected Calendar(s)' : (opts.title || 'Calendar Event');

    var tIn = document.getElementById('caveCalEvTitle');
    var dIn = document.getElementById('caveCalEvDate');
    var sIn = document.getElementById('caveCalEvStart');
    var eIn = document.getElementById('caveCalEvEnd');
    var lIn = document.getElementById('caveCalEvLocation');
    var nIn = document.getElementById('caveCalEvNotes');
    var stEl = document.getElementById('caveCalSaveStatus');
    var relBox = document.getElementById('caveCalDialogueEmails');

    var nowIso = new Date().toISOString().slice(0, 10);
    if (tIn) tIn.value = (opts && opts.title) || '';
    if (dIn) dIn.value = (opts && opts.date) || _caveCalDay || nowIso;
    if (sIn) sIn.value = ((opts && opts.start) || '10:00').slice(0, 5);
    if (eIn) eIn.value = ((opts && opts.end) || '10:30').slice(0, 5);
    if (lIn) lIn.value = (opts && opts.location) || '';
    if (nIn) nIn.value = (opts && opts.notes) || '';
    if (stEl) stEl.textContent = '';

    var srcStr = String((opts && opts.source) || 'PSU 365').toLowerCase();
    $$('[data-cave-cal-target]').forEach(function (cb) {
      var k = cb.getAttribute('data-cave-cal-target') || '';
      if (isNew) {
        cb.checked = (k === 'psu' || k === 'axmra');
      } else {
        cb.checked = srcStr.indexOf(k) >= 0 || (k === 'psu' && srcStr.indexOf('axmra') < 0 && srcStr.indexOf('gmail') < 0);
      }
    });
    calPane.setAttribute('data-cal-ev-uid', (opts && opts.uid) || '');
    try { dlg.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (err) {}

    if (isNew) {
      if (relBox) relBox.innerHTML = '<div style="color:#94a3b8;font-size:11.5px">Fill in the event details on the left and check which calendars (<b>PSU 365</b>, <b>Axmra 365</b>, <b>Gmail</b>) should receive this event.</div>';
      if (tIn) tIn.focus();
      return;
    }

    if (relBox) relBox.innerHTML = '<div style="color:#94a3b8;font-size:11.5px">\u23f3 Searching related emails &amp; correspondence\u2026</div>';
    fetch('/api/steward/comms', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({
        action: 'calendar_dialogue',
        id: (opts && opts.uid) || '',
        title: (opts && opts.title) || '',
        date: (opts && opts.date) || ''
      })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!relBox) return;
        var rels = (d && d.related_emails) || [];
        if (!rels.length) {
          relBox.innerHTML = '<div style="color:#94a3b8;font-size:11.5px">No matching inbox threads for this event title. You can edit the event or check additional calendars on the left to copy/sync it.</div>';
          return;
        }
        relBox.innerHTML = rels.map(function (em) {
          return (
            '<div style="padding:8px 10px;border-radius:8px;background:#111827;border:1px solid #283548;cursor:pointer" data-cave-mail-open="' + _escH(em.uid || '') + '" title="Click to switch to this Email Dialogue Tile">' +
              '<div style="display:flex;justify-content:space-between;font-size:10.5px;color:#94a3b8">' +
                '<span class="comms-badge sky">' + _escH(em.account_badge || 'Inbox') + '</span>' +
                '<span>' + _escH(em.date || '') + '</span>' +
              '</div>' +
              '<div style="font-weight:700;color:#f8fafc;margin-top:3px">' + _escH(em.subject || '') + '</div>' +
              '<div style="font-size:11px;color:#cbd5e1">' + _escH(em.from || '') + '</div>' +
            '</div>'
          );
        }).join('');
      })
      .catch(function () {});
  }

  function _interleaveEmailsByBadge(items) {
    if (!items || items.length <= 1) return items || [];
    var buckets = {};
    var order = [];
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      if (!it) continue;
      // Push automated Google Security Alert notices slightly below human correspondence
      var sEm = String(it.sender_email || it.from || '').toLowerCase();
      var subjL = String(it.subject || '').toLowerCase();
      it._adjScore = (it.steward_score || 70) - (sEm.indexOf('accounts.google.com') >= 0 && subjL.indexOf('security alert') >= 0 ? 14 : 0);
      var b = String(it.account_badge || it.account_id || 'Inbox');
      if (!buckets[b]) {
        buckets[b] = [];
        order.push(b);
      }
      buckets[b].push(it);
    }
    if (order.length <= 1) return items;
    order.forEach(function (b) {
      buckets[b].sort(function (a, c) { return (c._adjScore || 0) - (a._adjScore || 0); });
    });
    var out = [];
    var maxLen = 0;
    order.forEach(function (b) { if (buckets[b].length > maxLen) maxLen = buckets[b].length; });
    for (var idx = 0; idx < maxLen; idx++) {
      for (var j = 0; j < order.length; j++) {
        var bList = buckets[order[j]];
        if (idx < bList.length) out.push(bList[idx]);
      }
    }
    return out;
  }

  function _renderImportantMailCardHtml(em) {
    var uid = _escH(em.uid || '');
    var frmRaw = String(em.from || 'Inbox');
    var frmClean = _escH(frmRaw.split('<')[0].replace(/^["'\s]+|["'\s]+$/g, '') || frmRaw);
    var sEmail = _escH(em.sender_email || frmRaw);
    var subj = _escH(em.subject || '(No Subject)');
    var acctB = _escH(em.account_badge || 'Inbox');
    var score = parseInt(em.steward_score || 75, 10);
    var attBadge = em.has_attachments ? '<span class="comms-badge amber">&#128206; Attachment</span>' : '';
    var tCnt = parseInt(em.thread_count || 1, 10);
    var cntBadge = tCnt > 1 ? ('<span class="comms-badge sky">' + tCnt + ' msgs</span>') : '';
    var linkedEv = String(em.linked_calendar_event || '').trim();
    var prepBadge = linkedEv
      ? ('<span class="comms-badge emerald" title="Steward linked this email to upcoming calendar event: ' + _escH(linkedEv) + '">&#128197; Prep: ' + _escH(linkedEv.slice(0, 38)) + '</span>')
      : '';
    var dtShort = _escH(String(em.date || '').slice(0, 16));
    var snip = _escH(em.snippet || 'Click to read full message body from account inbox.');
    var rsn = _escH(em.steward_reason || 'Steward Priority');
    var openedFlag = em.was_opened ? '1' : '0';
    return (
      '<div class="comms-item amber cave-mail-card" data-mail-uid="' + uid + '" data-mail-sender="' + sEmail + '" data-mail-source="' + acctB + '" data-mail-opened="' + openedFlag + '" data-cave-mail-open="' + uid + '" style="cursor:pointer" title="Click to blow up Email Interaction &amp; Steward Reply Dialogue Tile">' +
        '<div class="comms-item-top">' +
          '<span class="comms-badge sky">' + acctB + '</span>' +
          '<b class="cave-mail-from" data-cave-mail-open="' + uid + '" style="cursor:pointer;color:#f8fafc">' + frmClean + '</b>' +
          '<span class="comms-badge emerald" title="' + rsn + '">&#9733; ' + score + '</span>' +
          prepBadge + attBadge + cntBadge +
          '<span class="comms-meta" style="text-align:right">' + dtShort + '</span>' +
          '<span class="comms-acts">' +
            '<button type="button" class="tw-btn" data-speed-racer-queue="1" data-mail-uid="' + uid + '" data-mail-sender="' + sEmail + '" data-mail-from="' + frmClean + '" data-mail-subject="' + subj + '" data-mail-account="' + acctB + '" data-mail-snippet="' + snip + '" style="border-color:rgba(245,158,11,0.55);background:rgba(245,158,11,0.16);color:#fef08a;font-weight:700" title="Have Steward draft a response and put this email into the Speed Racer review &amp; approval queue">&#127950;&#65039; &rarr; Speed Racer</button>' +
            '<button type="button" class="tw-btn" data-cave-mail-open="' + uid + '" title="Open Email Dialogue Tile (Thread History + Steward Suggested Reply)">&#128172; Open &amp; Reply</button>' +
            '<button type="button" class="tw-btn" data-cave-mail-triage="seen" data-mail-uid="' + uid + '" data-mail-sender="' + sEmail + '" title="Tap Seen: if you have not opened this email, Steward learns it is Not Interesting and downgrades it">&#128065; Seen</button>' +
            '<button type="button" class="tw-btn" data-cave-mail-triage="downgrade" data-mail-uid="' + uid + '" data-mail-sender="' + sEmail + '" title="Downgrade to Not Important &amp; teach Steward">&#11015; Not Interested</button>' +
          '</span>' +
        '</div>' +
        '<div class="comms-item-title" data-cave-mail-open="' + uid + '" style="cursor:pointer">' + subj + '</div>' +
        '<div class="cave-mail-body" id="caveMailBody-' + uid + '" hidden style="margin-top:6px;padding-top:6px;border-top:1px dashed #283548">' +
          '<div class="comms-item-sub" style="white-space:pre-wrap;color:#cbd5e1">' + snip + '</div>' +
          '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">' +
            '<button type="button" class="tw-btn" data-comms-draft-reply="1" data-comms-draft-subject="' + subj + '" data-comms-draft-to="' + sEmail + '" data-comms-draft-project="' + acctB + '" data-comms-draft-step="">&#9998; Draft Reply</button>' +
            '<button type="button" class="tw-btn" data-comms-download-att="' + uid + '" data-comms-att-subject="' + subj + '">&#11015; Save Attachment Locally</button>' +
            '<button type="button" class="tw-btn" data-cave-mail-triage="downgrade" data-mail-uid="' + uid + '" data-mail-sender="' + sEmail + '">&#11015; Downgrade / Not Interested</button>' +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function _renderSentMailCardHtml(em) {
    var uid = _escH(em.uid || '');
    var toRaw = String(em.to || em.counterparty || 'Recipient');
    var toClean = _escH(toRaw.split('<')[0].replace(/^["'\s]+|["'\s]+$/g, '') || toRaw);
    var toEmail = _escH(em.to || em.sender_email || toRaw);
    var subj = _escH(em.subject || '(No Subject)');
    var acctB = _escH(em.account_badge || 'Sent');
    var attBadge = em.has_attachments ? '<span class="comms-badge amber">&#128206; Attachment</span>' : '';
    var dtShort = _escH(String(em.date || '').slice(0, 16));
    var snip = _escH(em.snippet || em.body || 'Click to view full sent email and thread history.');
    return (
      '<div class="comms-item emerald cave-mail-card cave-sent-card" data-mail-uid="' + uid + '" data-mail-sender="' + toEmail + '" data-mail-source="' + acctB + '" data-mail-direction="sent" data-cave-mail-open="' + uid + '" style="cursor:pointer;border-left:3px solid #10b981" title="Click to open Sent Email &amp; Thread History">' +
        '<div class="comms-item-top">' +
          '<span class="comms-badge emerald">&#128228; ' + acctB + '</span>' +
          '<b class="cave-mail-from" data-cave-mail-open="' + uid + '" style="cursor:pointer;color:#6ee7b7">To: ' + toClean + '</b>' +
          attBadge +
          '<span class="comms-meta" style="text-align:right">' + dtShort + '</span>' +
          '<span class="comms-acts">' +
            '<button type="button" class="tw-btn" data-cave-mail-open="' + uid + '" title="Open Sent Email &amp; Thread History">&#128172; View / Follow Up</button>' +
            '<button type="button" class="tw-btn" data-comms-draft-reply="1" data-comms-draft-subject="' + subj + '" data-comms-draft-to="' + toEmail + '" data-comms-draft-project="' + acctB + '" data-comms-draft-step="">&#9998; Follow-Up Draft</button>' +
          '</span>' +
        '</div>' +
        '<div class="comms-item-title" data-cave-mail-open="' + uid + '" style="cursor:pointer">' + subj + '</div>' +
        '<div class="comms-item-sub" style="color:#cbd5e1">' + snip + '</div>' +
      '</div>'
    );
  }

  function _sanitizeEmailSandboxText(rawText) {
    var s = String(rawText || '');
    if (!s) return '';
    return s
      .replace(/(?:ignore|disregard|override)\s+(?:all\s+)?(?:previous|prior|system)\s+instructions?/gi, '[SANDBOXED-EMAIL-TEXT: non-executable content]')
      .replace(/(?:system\s+prompt|developer\s+instruction|execute\s+command|run\s+shell|powershell\s+-|cmd\.exe\s+\/c|bash\s+-c)/gi, '[SANDBOXED-EMAIL-TEXT: non-executable content]');
  }

  function _hydrateMailCardsFromCommsData(d) {
    if (!d || !d.ok) return;
    var impBox = document.getElementById('caveMailImportantList');
    if (impBox && Array.isArray(d.important_emails) && d.important_emails.length) {
      var interleaved = _interleaveEmailsByBadge(d.important_emails.slice());
      impBox.innerHTML = interleaved.slice(0, 30).map(_renderImportantMailCardHtml).join('');
    }
    if (d.speed_racer && typeof _syncSpeedRacerFromServer === 'function') {
      _syncSpeedRacerFromServer(d.speed_racer);
    }
    var sentBox = document.getElementById('caveMailSentList');
    if (sentBox && Array.isArray(d.sent_emails)) {
      if (d.sent_emails.length) {
        sentBox.innerHTML = d.sent_emails.slice(0, 25).map(_renderSentMailCardHtml).join('');
      }
      var sentCntB = document.getElementById('caveSentCountBadge');
      if (sentCntB) sentCntB.textContent = String(d.sent_emails.length);
    }
    var accBar = document.getElementById('caveConnectedAccountsBar');
    var syncBtnToolbar = document.getElementById('btnCaveCommsSync');
    if (syncBtnToolbar && syncBtnToolbar.parentElement && !document.getElementById('btnCaveToolbarChangePw')) {
      syncBtnToolbar.insertAdjacentHTML(
        'beforebegin',
        '<button type="button" class="mini comms-sync-btn" id="btnCaveToolbarChangePw" data-open-comms-connect="1" style="border-color:#fbbf24;color:#fde68a;font-weight:700" title="Open box to change password or connect an account">\u270f\ufe0f Change Password / Account</button>'
      );
    }
    if (accBar && Array.isArray(d.accounts)) {
      var allConnected = true;
      var pillsHtml = [];
      d.accounts.forEach(function (a) {
        if (!a || !a.id) return;
        var aid = _escH(a.id);
        var albl = _escH(a.label || a.family || 'Account');
        var aem = _escH(a.email || 'Calendar ICS');
        var astat = String(a.status || 'configured').toLowerCase();
        var famL = String(a.family || 'gmail').toLowerCase();
        var noteTip = _escH(String(a.last_imap_note || a.last_ics_note || '').slice(0, 180));
        var editBtnHtml =
          '<button type="button" class="mini" data-comms-edit-account="' + aid + '" data-comms-edit-email="' + aem + '" data-comms-edit-label="' + albl + '" data-comms-edit-family="' + _escH(famL) + '" ' +
          'title="Open box to change/update password for ' + aem + '" ' +
          'style="border-color:#94a3b8;color:#e2e8f0;background:rgba(148,163,184,0.14);padding:1px 7px;font-size:11px;font-weight:650">' +
          '\u270f\ufe0f Change Password</button> ';
        if (astat === 'paused_safety' || astat === 'auth_error') {
          allConnected = false;
          var fixBtn = '';
          if (famL === 'outlook') {
            fixBtn =
              '<button type="button" class="mini" data-comms-ms-device-auth="' + aid + '" data-comms-ms-email="' + aem + '" data-comms-ms-label="' + albl + '" ' +
              'title="Sign in safely with your Microsoft 365 password + 2FA in browser" ' +
              'style="border-color:#fbbf24;color:#fde68a;background:rgba(245,158,11,0.18);padding:1px 8px;font-size:11px;font-weight:700">' +
              '\ud83d\udd11 Sign In with Microsoft 365 (2FA)</button> ';
          } else {
            fixBtn =
              '<button type="button" class="mini" data-comms-gmail-2fa="' + aid + '" data-comms-edit-account="' + aid + '" data-comms-edit-email="' + aem + '" data-comms-edit-label="' + albl + '" data-comms-edit-family="' + _escH(famL) + '" ' +
              'title="Trigger Google 2FA prompt on your phone" ' +
              'style="border-color:#38bdf8;color:#7dd3fc;background:rgba(56,189,248,0.15);padding:1px 7px;font-size:11px;font-weight:700">' +
              '\ud83d\udd11 Authenticate 2FA</button> ';
          }
          pillsHtml.push(
            '<span class="comms-pill amber" title="' + noteTip + '" style="display:inline-flex;align-items:center;gap:6px;border:1px solid rgba(245,158,11,0.5);background:rgba(245,158,11,0.1);color:#fde68a">' +
            '\u26a0 ' + albl + ' (' + aem + ') \u00b7 <span style="font-size:10.5px;opacity:0.9">Needs Sign-In / 2FA</span> ' +
            fixBtn + editBtnHtml +
            '<button type="button" class="mini" data-comms-remove-id="' + aid + '" title="Remove this account" style="padding:0 5px;font-size:11px;line-height:1.2">&times;</button>' +
            '</span>'
          );
        } else {
          pillsHtml.push(
            '<span class="comms-pill emerald" title="' + noteTip + '" style="display:inline-flex;align-items:center;gap:6px">' +
            '\u2713 ' + albl + ' (' + aem + ') ' +
            editBtnHtml +
            '<button type="button" class="mini" data-comms-remove-id="' + aid + '" title="Disconnect this account" style="padding:0 5px;font-size:11px;line-height:1.2">&times;</button>' +
            '</span>'
          );
        }
      });
      if (pillsHtml.length) {
        accBar.innerHTML = pillsHtml.join('');
      }
      if (allConnected) {
        var devBox = document.getElementById('caveCommsDeviceFlowBox');
        if (devBox) devBox.hidden = true;
      }
    }
  }

  function _ensureCaveCommsDataLoaded(force) {
    if (_caveCommsData && !force) return Promise.resolve(_caveCommsData);
    return fetch('/api/steward/comms', { headers: headers(), cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.ok) {
          _caveCommsData = d;
          _hydrateMailCardsFromCommsData(d);
          _applySourceFilterToDOM();
          if (d.gmail_2fa && d.gmail_2fa.status === 'pending' && (Date.now() / 1000 - (d.gmail_2fa.updated_at || 0)) < 120) {
            var gmAccObj = (d.accounts || []).find(function (x) { return x && x.id === d.gmail_2fa.account_id; });
            if (!gmAccObj || gmAccObj.status !== 'connected') {
              window._startCaveGmail2faPoll(d.gmail_2fa.account_id, d.gmail_2fa.email, d.gmail_2fa);
            }
          }
        }
        return d;
      })
      .catch(function () { return null; });
  }
  window._ensureCaveCommsDataLoaded = _ensureCaveCommsDataLoaded;

  document.addEventListener('change', function (e) {
    var srcCb = e.target.closest && e.target.closest('[data-comms-source-filter]');
    if (srcCb) {
      var key = srcCb.getAttribute('data-comms-source-filter') || '';
      if (key in _caveSources) {
        _caveSources[key] = !!srcCb.checked;
        try { localStorage.setItem('anchor_cave_comms_sources_v1', JSON.stringify(_caveSources)); } catch (err) {}
        _ensureCaveCommsDataLoaded(false).then(function () {
          _applySourceFilterToDOM();
        });
      }
    }
  });

  document.addEventListener('click', function (e) {
    var allSrcBtn = e.target.closest && e.target.closest('[data-comms-source-all]');
    if (allSrcBtn) {
      e.preventDefault(); e.stopPropagation();
      _caveSources = { psu: true, axmra: true, gmail: true };
      try { localStorage.setItem('anchor_cave_comms_sources_v1', JSON.stringify(_caveSources)); } catch (err) {}
      _ensureCaveCommsDataLoaded(false).then(function () { _applySourceFilterToDOM(); });
      return;
    }
    var submitSmsBtn = e.target.closest && e.target.closest('#btnCaveGmailSubmitSms');
    if (submitSmsBtn) {
      e.preventDefault(); e.stopPropagation();
      var smsInp = document.getElementById('caveGmailSmsCodeInput');
      var smsCode = (smsInp && smsInp.value || '').trim();
      var gmAcc = submitSmsBtn.getAttribute('data-gmail-acc') || 'comms-3a9bfa74';
      if (!smsCode) {
        receipt('Please enter the 6-digit SMS verification code first.', true);
        return;
      }
      submitSmsBtn.disabled = true;
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'gmail_2fa_submit_code', account_id: gmAcc, code: smsCode })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          submitSmsBtn.disabled = false;
          if (d && d.ok) {
            receipt('\u2713 Submitted 6-digit SMS code ' + d.code + ' to Google 2FA!');
            if (smsInp) smsInp.value = '';
          } else {
            receipt((d && d.error) || 'Could not submit SMS code.', true);
          }
        })
        .catch(function () {
          submitSmsBtn.disabled = false;
        });
      return;
    }
    var closeDlgBtn = e.target.closest && e.target.closest('[data-cave-dlg-close]');
    if (closeDlgBtn) {
      e.preventDefault(); e.stopPropagation();
      var dlg = document.getElementById('caveCommsDialogueTile');
      if (dlg) dlg.hidden = true;
      return;
    }
    var addEvBtn = e.target.closest && e.target.closest('[data-cave-add-event]');
    if (addEvBtn) {
      e.preventDefault(); e.stopPropagation();
      var calSec = document.getElementById('cal');
      if (calSec && !calSec.classList.contains('open')) {
        calSec.classList.add('open');
        var tog = document.getElementById('calTog');
        if (tog) tog.textContent = 'Collapse';
      }
      _openCalDialogueTile({ isNew: true, date: _caveCalDay || new Date().toISOString().slice(0, 10) });
      return;
    }
    var openCalEl = e.target.closest && e.target.closest('[data-cave-cal-open]');
    if (openCalEl && !e.target.closest('[data-mark-done], a')) {
      e.preventDefault(); e.stopPropagation();
      _openCalDialogueTile({
        isNew: false,
        uid: openCalEl.getAttribute('data-cave-cal-open') || '',
        title: openCalEl.getAttribute('data-cal-title') || '',
        date: openCalEl.getAttribute('data-cal-date') || '',
        start: openCalEl.getAttribute('data-cal-start') || '10:00',
        end: openCalEl.getAttribute('data-cal-end') || '10:30',
        location: openCalEl.getAttribute('data-cal-loc') || '',
        source: openCalEl.getAttribute('data-cal-source') || 'PSU 365'
      });
      return;
    }
    var saveCalBtn = e.target.closest && e.target.closest('#btnCaveSaveCalEvent');
    if (saveCalBtn) {
      e.preventDefault(); e.stopPropagation();
      var titleVal = ((document.getElementById('caveCalEvTitle') || {}).value || '').trim();
      var dateVal = ((document.getElementById('caveCalEvDate') || {}).value || '').trim();
      var startVal = ((document.getElementById('caveCalEvStart') || {}).value || '10:00').trim();
      var endVal = ((document.getElementById('caveCalEvEnd') || {}).value || '10:30').trim();
      var locVal = ((document.getElementById('caveCalEvLocation') || {}).value || '').trim();
      var notesVal = ((document.getElementById('caveCalEvNotes') || {}).value || '').trim();
      var calPaneEl = document.getElementById('caveCalDialoguePane');
      var evUid = calPaneEl ? (calPaneEl.getAttribute('data-cal-ev-uid') || '') : '';
      var stCal = document.getElementById('caveCalSaveStatus');
      var pickedSources = [];
      $$('[data-cave-cal-target]').forEach(function (cb) {
        if (cb.checked) pickedSources.push(cb.getAttribute('data-cave-cal-target'));
      });
      if (!titleVal) {
        if (stCal) stCal.textContent = '\u26a0 Please enter an Event Title.';
        return;
      }
      saveCalBtn.disabled = true;
      if (stCal) stCal.textContent = '\u23f3 Saving & syncing to checked calendar(s)\u2026';
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'create_event',
          uid: evUid,
          title: titleVal,
          date: dateVal,
          start_time: startVal,
          end_time: endVal,
          location: locVal,
          description: notesVal,
          sources: pickedSources
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          saveCalBtn.disabled = false;
          if (d && d.ok) {
            if (stCal) stCal.innerHTML = '<b style="color:#6ee7b7">\u2713 ' + _escH(d.remote_note || 'Saved to calendar!') + '</b>';
            _caveCommsData = null;
            _caveCalDay = dateVal || _caveCalDay;
            renewInPlace('\u2713 Calendar event "' + titleVal + '" synced (' + (d.remote_note || 'saved') + ').');
          } else {
            if (stCal) stCal.textContent = '\u26a0 ' + ((d && d.error) || 'Could not save event.');
          }
        })
        .catch(function () {
          saveCalBtn.disabled = false;
          if (stCal) stCal.textContent = 'Calendar save request did not reach Anchor.';
        });
      return;
    }
    var stIntentBtn = e.target.closest && e.target.closest('[data-steward-draft-intent], #btnCaveStewardCustomDraft');
    if (stIntentBtn) {
      e.preventDefault(); e.stopPropagation();
      var intent = stIntentBtn.getAttribute('data-steward-draft-intent') || 'default';
      var custIn = document.getElementById('caveStewardCustomPrompt');
      var customPrompt = (stIntentBtn.id === 'btnCaveStewardCustomDraft' && custIn) ? custIn.value.trim() : '';
      var curD = _activeEmailDialogue || {};
      var noteEl = document.getElementById('caveDlgStewardNote');
      if (noteEl) noteEl.textContent = '\u23f3 Steward is drafting response\u2026';
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'steward_draft_reply',
          uid: curD.uid || '',
          account_id: curD.account_id || '',
          subject: curD.subject || ((document.getElementById('caveReplySubject') || {}).value || ''),
          from: curD.from || '',
          sender_email: curD.sender_email || ((document.getElementById('caveReplyTo') || {}).value || ''),
          body: curD.body || '',
          intent: intent,
          custom_prompt: customPrompt
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.ok) {
            var bIn = document.getElementById('caveReplyBody');
            if (bIn) bIn.value = d.draft_body || '';
            if (noteEl) noteEl.textContent = '\u2728 ' + (d.steward_note || 'Draft updated');
          }
        });
      return;
    }
    var sendReplyBtn = e.target.closest && e.target.closest('#btnCaveSendReplyNow');
    if (sendReplyBtn) {
      e.preventDefault(); e.stopPropagation();
      var curM = _activeEmailDialogue || {};
      var toVal = ((document.getElementById('caveReplyTo') || {}).value || '').trim();
      var ccVal = ((document.getElementById('caveReplyCc') || {}).value || '').trim();
      var subVal = ((document.getElementById('caveReplySubject') || {}).value || '').trim();
      var bodyVal = ((document.getElementById('caveReplyBody') || {}).value || '').trim();
      var stMsg = document.getElementById('caveReplyStatusMsg');
      if (!toVal || !bodyVal) {
        if (stMsg) stMsg.textContent = '\u26a0 Recipient (To) and message body are required.';
        return;
      }
      sendReplyBtn.disabled = true;
      if (stMsg) stMsg.textContent = '\u23f3 Sending reply\u2026';
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'send_email',
          account_id: curM.account_id || '',
          to: toVal,
          cc: ccVal,
          subject: subVal,
          body: bodyVal
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          sendReplyBtn.disabled = false;
          if (d && d.ok) {
            if (stMsg) stMsg.innerHTML = '<b style="color:#6ee7b7">\u2713 Sent via ' + _escH(d.transport || d.from || 'Account') + '!</b>';
            var thList = document.getElementById('caveDialogueThreadList');
            if (thList) {
              var sentCard = document.createElement('div');
              sentCard.style.cssText = 'padding:9px 11px;border-radius:8px;background:rgba(16,185,129,0.12);border:1px solid #10b981;border-left:4px solid #10b981';
              sentCard.innerHTML =
                '<div style="display:flex;justify-content:space-between;font-size:11px;color:#6ee7b7;margin-bottom:4px"><b>You \u2192 ' + _escH(toVal) + '</b><span>Just Sent</span></div>' +
                '<div style="font-size:12px;color:#f8fafc;white-space:pre-wrap">' + _escH(bodyVal) + '</div>';
              thList.appendChild(sentCard);
              thList.scrollTop = thList.scrollHeight;
            }
            if (Array.isArray(d.sent_emails)) {
              if (!_caveCommsData) _caveCommsData = { ok: true };
              _caveCommsData.sent_emails = d.sent_emails;
              _hydrateMailCardsFromCommsData(_caveCommsData);
            }
            receipt('\u2713 Reply sent to ' + toVal + ' (' + subVal + ').');
          } else {
            if (stMsg) stMsg.textContent = '\u26a0 ' + ((d && d.error) || 'Send failed.');
          }
        })
        .catch(function () {
          sendReplyBtn.disabled = false;
          if (stMsg) stMsg.textContent = 'Send request did not reach Anchor.';
        });
      return;
    }
    var saveReplyDraftBtn = e.target.closest && e.target.closest('#btnCaveSaveReplyDraft');
    if (saveReplyDraftBtn) {
      e.preventDefault(); e.stopPropagation();
      var toValD = ((document.getElementById('caveReplyTo') || {}).value || '').trim();
      var subValD = ((document.getElementById('caveReplySubject') || {}).value || '').trim();
      var bodyValD = ((document.getElementById('caveReplyBody') || {}).value || '').trim();
      var stMsgD = document.getElementById('caveReplyStatusMsg');
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'create_draft', to: toValD, subject: subValD, body: bodyValD })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.ok) {
            if (stMsgD) stMsgD.innerHTML = '<b style="color:#7dd3fc">\u2713 Draft saved to .anchor/drafts/</b>';
            receipt('Saved reply draft to .anchor/drafts/.');
          }
        });
      return;
    }
    var dlgTriageBtn = e.target.closest && e.target.closest('#btnCaveDlgSeen, #btnCaveDlgDowngrade, #btnCaveDlgUpgrade');
    if (dlgTriageBtn && _activeEmailDialogue) {
      e.preventDefault(); e.stopPropagation();
      var actMap = { btnCaveDlgSeen: 'seen', btnCaveDlgDowngrade: 'downgrade', btnCaveDlgUpgrade: 'upgrade' };
      var fb = actMap[dlgTriageBtn.id] || 'seen';
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'email_triage_feedback',
          uid: _activeEmailDialogue.uid || '',
          sender_email: _activeEmailDialogue.sender_email || '',
          feedback: fb,
          was_opened: true
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.ok) {
            var dlg = document.getElementById('caveCommsDialogueTile');
            if (dlg) dlg.hidden = true;
            _caveCommsData = null;
            renewInPlace(d.note || 'Updated Steward email preference.');
          }
        });
      return;
    }
    var mailFolderBtn = e.target.closest && e.target.closest('[data-cave-mail-folder]');
    if (mailFolderBtn) {
      e.preventDefault(); e.stopPropagation();
      var fMode = mailFolderBtn.getAttribute('data-cave-mail-folder') || 'all';
      _applyCaveMailFolderMode(fMode);
      return;
    }
    var layoutBtn = e.target.closest && e.target.closest('#calBody [data-comms-layout]');
    if (layoutBtn) {
      e.preventDefault(); e.stopPropagation();
      applyCommsLayout(layoutBtn.getAttribute('data-comms-layout') || 'split');
      return;
    }
    var toggleFullBtn = e.target.closest && e.target.closest('[data-comms-layout-toggle]');
    if (toggleFullBtn) {
      e.preventDefault(); e.stopPropagation();
      var targetCol = toggleFullBtn.getAttribute('data-comms-layout-toggle') || 'cal';
      var curG = document.getElementById('commsGrid');
      var curL = (curG && curG.getAttribute('data-layout')) || 'split';
      applyCommsLayout(curL === targetCol ? 'split' : targetCol);
      return;
    }
    var calViewBtn = e.target.closest && e.target.closest('[data-cave-cal-view]');
    if (calViewBtn) {
      e.preventDefault(); e.stopPropagation();
      _caveCalView = calViewBtn.getAttribute('data-cave-cal-view') || 'week';
      try { localStorage.setItem('anchor_cave_cal_view_v2', _caveCalView); } catch (err) {}
      _ensureCaveCommsDataLoaded(false).then(function () { _renderCaveCalendarViewport(); });
      return;
    }
    var calNavBtn = e.target.closest && e.target.closest('[data-cave-cal-nav]');
    if (calNavBtn) {
      e.preventDefault(); e.stopPropagation();
      var dir = parseInt(calNavBtn.getAttribute('data-cave-cal-nav') || '0', 10);
      _ensureCaveCommsDataLoaded(false).then(function () {
        var nowIso = new Date().toISOString().slice(0, 10);
        if (dir === 0) {
          _caveCalDay = nowIso;
        } else if (_caveCalView === 'week') {
          _caveCalDay = _shiftIsoDate(_caveCalDay || nowIso, dir * 7);
        } else if (_caveCalView === 'month') {
          _caveCalDay = _shiftIsoDate(_caveCalDay || nowIso, dir * 30);
        } else {
          if (_caveCalView === 'iphone') _caveCalView = 'day';
          _caveCalDay = _shiftIsoDate(_caveCalDay || nowIso, dir);
        }
        try { localStorage.setItem('anchor_cave_cal_view_v2', _caveCalView); } catch (err) {}
        _renderCaveCalendarViewport();
      });
      return;
    }
    var pickDayEl = e.target.closest && e.target.closest('[data-cave-pick-day]');
    if (pickDayEl && !e.target.closest('button, a, [data-cave-cal-open]')) {
      e.preventDefault();
      _caveCalDay = pickDayEl.getAttribute('data-cave-pick-day') || '';
      _caveCalView = 'day';
      try { localStorage.setItem('anchor_cave_cal_view_v2', _caveCalView); } catch (err) {}
      _ensureCaveCommsDataLoaded(false).then(function () { _renderCaveCalendarViewport(); });
      return;
    }
    var openMailEl = e.target.closest && e.target.closest('[data-cave-mail-open]');
    if (openMailEl && !e.target.closest('[data-cave-mail-triage], [data-comms-download-att], [data-comms-draft-reply], [data-speed-racer-queue]')) {
      e.preventDefault(); e.stopPropagation();
      var uid = openMailEl.getAttribute('data-cave-mail-open') || '';
      if (!uid) return;
      var card = openMailEl.closest('.cave-mail-card');
      var fSubj = '';
      var fSender = '';
      var fSrc = '';
      if (card) {
        card.setAttribute('data-mail-opened', '1');
        fSender = card.getAttribute('data-mail-sender') || '';
        fSrc = card.getAttribute('data-mail-source') || '';
        var tEl = card.querySelector('.comms-item-title, .comms-item-sub');
        if (tEl) fSubj = tEl.textContent || '';
      }
      _openEmailDialogueTile(uid, fSubj, fSender, fSrc);
      return;
    }
    var triageBtn = e.target.closest && e.target.closest('[data-cave-mail-triage]');
    if (triageBtn) {
      e.preventDefault(); e.stopPropagation();
      var tUid = triageBtn.getAttribute('data-mail-uid') || '';
      var tSender = triageBtn.getAttribute('data-mail-sender') || '';
      var tAct = triageBtn.getAttribute('data-cave-mail-triage') || '';
      var mCard = triageBtn.closest('.cave-mail-card');
      var wasOpened = mCard ? (mCard.getAttribute('data-mail-opened') === '1') : false;
      triageBtn.disabled = true;
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'email_triage_feedback',
          uid: tUid,
          sender_email: tSender,
          feedback: tAct,
          was_opened: wasOpened
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          triageBtn.disabled = false;
          if (d && d.ok) {
            _caveCommsData = null;
            renewInPlace(d.note || 'Updated Steward email triage preference.');
          } else {
            receipt((d && d.error) || 'Could not update email triage.', true);
          }
        })
        .catch(function () {
          triageBtn.disabled = false;
          receipt('Email triage request did not reach Anchor.', true);
        });
      return;
    }
    var dlAttBtn = e.target.closest && e.target.closest('[data-comms-download-att]');
    if (dlAttBtn) {
      e.preventDefault(); e.stopPropagation();
      var attUid = dlAttBtn.getAttribute('data-comms-download-att') || '';
      var attSubj = dlAttBtn.getAttribute('data-comms-att-subject') || '';
      dlAttBtn.disabled = true;
      var origTxt = dlAttBtn.textContent;
      dlAttBtn.textContent = 'Saving\u2026';
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'download_attachments', uid: attUid, subject: attSubj })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          dlAttBtn.disabled = false;
          dlAttBtn.textContent = origTxt;
          if (d && d.ok) {
            receipt('\u2713 Saved ' + (d.count || 0) + ' attachment(s) locally to ' + (d.save_dir || '.anchor/attachments'));
          } else {
            receipt((d && d.error) || 'Could not save attachments.', true);
          }
        })
        .catch(function () {
          dlAttBtn.disabled = false;
          dlAttBtn.textContent = origTxt;
          receipt('Attachment download request did not reach Anchor.', true);
        });
      return;
    }
  });

  // Wave 21 (2026-11-02): Option 1 (Mockup 4) Chief-of-Staff Asymmetric Horizon Strip, Break-Between-Cockpits Filter,
  // Q1 -> Q2 Deep-Work Unlock Meter, Parable-of-the-Oranges Skill Pre-Stage, and 1-Click Rotate
  var _cosClearedCount = 0;
  function _setCosBodyExpanded(open, focusCol) {
    var body = document.getElementById('cosExpandableBody');
    var strip = document.getElementById('shTriage');
    var btn = document.getElementById('btnCosToggleExpand');
    if (!body) return;
    body.hidden = !open;
    if (strip) strip.classList.toggle('is-collapsed', !open);
    if (btn) {
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      var cntMatch = (btn.textContent || '').match(/\(\d+\)/);
      var cntStr = cntMatch ? (' ' + cntMatch[0]) : '';
      btn.innerHTML = (open ? '&#9652; Collapse Recommendations' : '&#9662; Expand Recommendations') + cntStr;
    }
    $$('#cosCompactSummaryRow .cos-cs-pill').forEach(function (p) {
      p.classList.toggle('active-drill', !!(open && focusCol && p.getAttribute('data-cos-drill') === focusCol));
    });
    if (open && focusCol) {
      _expandCosColumn(focusCol);
    }
  }

  function _expandCosColumn(colKey) {
    var strip = document.getElementById('cosHorizonStrip');
    if (!strip) return;
    strip.classList.remove('expanded-week', 'expanded-month', 'expanded-quarter');
    ['today', 'week', 'month', 'quarter'].forEach(function (k) {
      var el = document.getElementById('cosCol-' + k);
      if (el) el.classList.remove('hz-focused', 'is-wide');
    });
    if (colKey === 'week') {
      strip.classList.add('expanded-week');
      var t1 = document.getElementById('cosCol-today'); if (t1) t1.classList.add('is-wide');
      var w1 = document.getElementById('cosCol-week'); if (w1) { w1.classList.add('is-wide', 'hz-focused'); }
    } else if (colKey === 'month') {
      strip.classList.add('expanded-month');
      var t2 = document.getElementById('cosCol-today'); if (t2) t2.classList.add('is-wide');
      var m1 = document.getElementById('cosCol-month'); if (m1) { m1.classList.add('is-wide', 'hz-focused'); }
    } else if (colKey === 'quarter') {
      strip.classList.add('expanded-quarter');
      var t3 = document.getElementById('cosCol-today'); if (t3) t3.classList.add('is-wide');
      var q1 = document.getElementById('cosCol-quarter'); if (q1) { q1.classList.add('is-wide', 'hz-focused'); }
    } else {
      var t0 = document.getElementById('cosCol-today'); if (t0) { t0.classList.add('is-wide', 'hz-focused'); }
      var w0 = document.getElementById('cosCol-week'); if (w0) w0.classList.add('is-wide');
    }
  }

  document.addEventListener('click', function (e) {
    var breakBtn = e.target.closest && e.target.closest('[data-cos-break]');
    if (breakBtn) {
      e.preventDefault();
      var mode = breakBtn.getAttribute('data-cos-break') || 'all';
      var bar = breakBtn.closest('.cos-break-selector');
      if (bar) {
        bar.querySelectorAll('.cos-break-btn').forEach(function (b) { b.classList.remove('active'); });
      }
      breakBtn.classList.add('active');
      $$('#shTriage [data-cos-card]').forEach(function (card) {
        var tags = (card.getAttribute('data-break') || '').split(/\s+/);
        card.style.display = (mode === 'all' || tags.indexOf(mode) >= 0) ? '' : 'none';
      });
      if (mode === 'family') _expandCosColumn('month');
      else if (mode === 'deep') _expandCosColumn('quarter');
      else _expandCosColumn('today');
      return;
    }

    var expEl = e.target.closest && e.target.closest('[data-cos-expand-col]');
    if (expEl && !e.target.closest('a, [data-cos-prestage-prompt], [data-mark-done], [data-cos-rotate], [data-cos-modal-open]')) {
      e.preventDefault();
      _expandCosColumn(expEl.getAttribute('data-cos-expand-col') || 'today');
      return;
    }

    var preBtn = e.target.closest && e.target.closest('[data-cos-prestage-prompt]');
    if (preBtn) {
      e.preventDefault(); e.stopPropagation();
      var pr = preBtn.getAttribute('data-cos-prestage-prompt') || '';
      var sk = preBtn.getAttribute('data-cos-skill') || 'Foundry Skill';
      if (say && pr) {
        say.value = pr;
        say.dispatchEvent(new Event('input'));
        say.focus();
      }
      receipt('\ud83c\udf4a Parable of the Oranges: Pre-staged ' + sk + ' brief in Steward composer!');
      return;
    }

    var dispBtn = e.target.closest && e.target.closest('[data-cos-dispatch-skill]');
    if (dispBtn) {
      e.preventDefault(); e.stopPropagation();
      var dSkill = dispBtn.getAttribute('data-cos-dispatch-skill') || 'researchPrime';
      var mTitle = (document.getElementById('cosModalTitle') || {}).textContent || 'this effort';
      if (say) {
        say.value = 'Pre-stage and run /' + dSkill + ' for "' + mTitle + '" so the AI Cockpit is ready when I open it.';
        say.dispatchEvent(new Event('input'));
        say.focus();
      }
      var mClose0 = document.getElementById('cosOrangesModal');
      if (mClose0) mClose0.hidden = true;
      receipt('\ud83c\udf4a Dispatched ' + dSkill + ' pre-stage request for ' + mTitle + '!');
      return;
    }

    var modalOpen = e.target.closest && e.target.closest('[data-cos-modal-open]');
    if (modalOpen) {
      e.preventDefault(); e.stopPropagation();
      var m = document.getElementById('cosOrangesModal');
      if (m) {
        var tEl = document.getElementById('cosModalTitle');
        var trEl = document.getElementById('cosModalTier');
        var drEl = document.getElementById('cosModalDriver');
        var orEl = document.getElementById('cosModalOranges');
        var opBtn = document.getElementById('cosModalOpenBtn');
        if (tEl) tEl.textContent = modalOpen.getAttribute('data-cos-title') || 'Effort';
        if (trEl) trEl.textContent = modalOpen.getAttribute('data-cos-tier') || 'Next-Best Effort';
        if (drEl) drEl.innerHTML = '<strong>Signal / Driver Provenance:</strong> ' + _escH(modalOpen.getAttribute('data-cos-driver') || '');
        if (orEl) orEl.innerHTML = '\ud83c\udf4a <strong>Parable of the Oranges Pre-Staging:</strong> ' + _escH(modalOpen.getAttribute('data-cos-oranges') || '');
        if (opBtn) opBtn.href = modalOpen.getAttribute('data-cos-href') || '/steward/v1';
        m.hidden = false;
      }
      return;
    }

    if (e.target.closest && (e.target.closest('#btnCosModalClose') || e.target.id === 'cosOrangesModal')) {
      var mHide = document.getElementById('cosOrangesModal');
      if (mHide) mHide.hidden = true;
      return;
    }

    var rotBtn = e.target.closest && e.target.closest('[data-cos-rotate]');
    if (rotBtn) {
      e.preventDefault(); e.stopPropagation();
      var rId = rotBtn.getAttribute('data-cos-rotate') || '';
      var rCard = document.getElementById(rId) || rotBtn.closest('.cos-effort-card');
      if (rCard) {
        var nmEl = rCard.querySelector('.cos-ef-name');
        if (rId === 'cos-today-q2-moe' && nmEl) {
          nmEl.textContent = '3. [2:15 PM Protected Q2 Deep Work] Spring 2027 AI Class Proposal (w/ Min) & GWL Harnesses';
          receipt('\u23ed Rotated Q2 Deep-Work slot to next Star Chart priority: Spring 2027 AI Class Proposal (Superjump + Gandalf pre-staged).');
        } else {
          var parentCol = rCard.parentElement;
          if (parentCol) parentCol.appendChild(rCard);
          receipt('\u23ed Rotated effort — promoted next candidate in Steward queue!');
        }
      }
      return;
    }

    var clrBtn = e.target.closest && e.target.closest('[data-cos-clear-id]');
    if (clrBtn) {
      var cId = clrBtn.getAttribute('data-cos-clear-id') || '';
      var cCard = document.getElementById(cId);
      if (cCard) cCard.style.opacity = '0.4';
      _cosClearedCount++;
      var lbl = document.getElementById('cosQ2UnlockLabel');
      var segU = document.getElementById('cosSegUrg');
      var segD = document.getElementById('cosSegDeep');
      if (_cosClearedCount === 1) {
        if (lbl) lbl.innerHTML = '1 Urgent effort cleared! <strong>1 left</strong> &rarr; <strong>3.25 hrs</strong> Q2 Deep Work unlocked today';
        if (segU) segU.style.width = '14%';
        if (segD) segD.style.width = '59%';
      } else {
        if (lbl) lbl.innerHTML = '\ud83c\udf89 All Urgent Q1 items cleared! <strong>Full 3.75 hrs Quadrant II Deep Work</strong> unlocked!';
        if (segU) segU.style.width = '0%';
        if (segD) segD.style.width = '73%';
      }
    }
  });

  // =========================================================================
  // Wave 22 (2026-11-06):
  //   1) Expandable Speed Racer Tile inside Email Hub + Steward Auto-Open
  //   2) Variation A Persistent Working List Spine with Per-Step AI Cockpit & Initiative Connections
  // =========================================================================
  var _srState = window.ANCHOR_SPEED_RACER_INIT || { queue: [], sent_log: [], auto_open_ts: 0 };
  var _srIdx = 0;
  var _srLastAutoOpenTs = Number(_srState.auto_open_ts || 0);
  var _srLastSentDraft = null;

  function _updateSrBadges() {
    var q = (_srState && Array.isArray(_srState.queue)) ? _srState.queue : [];
    var n = q.length;
    var b1 = document.getElementById('caveHdrSrCount');
    var b2 = document.getElementById('caveSrBtnCount');
    var b3 = document.getElementById('caveSrTileBadge');
    if (b1) b1.textContent = String(n);
    if (b2) b2.textContent = String(n);
    if (b3) b3.textContent = n + (n === 1 ? ' Draft Awaiting Approval' : ' Drafts Awaiting Approval');
  }

  function _renderCaveSpeedRacerTile() {
    _updateSrBadges();
    var host = document.getElementById('caveSpeedRacerDeckHost');
    if (!host) return;
    var q = (_srState && Array.isArray(_srState.queue)) ? _srState.queue : [];
    if (!q.length) {
      host.innerHTML =
        '<div style="padding:12px;border-radius:8px;border:1px dashed rgba(16,185,129,0.5);background:rgba(16,185,129,0.08);color:#6ee7b7;font-size:12px;text-align:center">' +
        '&#127881; <b>Speed Racer Queue Clear!</b> Zero pending Steward email drafts. Click <code>[&#127950;&#65039; &rarr; Speed Racer]</code> on any Inbox email below or ask the Steward to draft a reply.' +
        '</div>';
      return;
    }
    if (_srIdx >= q.length) _srIdx = 0;
    if (_srIdx < 0) _srIdx = q.length - 1;
    var item = q[_srIdx];
    var navPills = q.map(function (it, idx) {
      var on = idx === _srIdx;
      var shortTo = String(it.to || 'Draft').split('<')[0].replace(/^["'\\s]+|["'\\s]+$/g, '').slice(0, 18) || ('#' + (idx + 1));
      return (
        '<button type="button" class="tw-btn' + (on ? ' on' : '') + '" data-sr-pick-idx="' + idx + '" ' +
        'style="font-size:10.5px;padding:2px 7px;' + (on ? 'border-color:#f59e0b;background:rgba(245,158,11,0.22);color:#fef08a;font-weight:700' : '') + '">' +
        (idx + 1) + '. ' + _escH(shortTo) + '</button>'
      );
    }).join('');

    host.innerHTML =
      '<div class="sr-card" data-sr-active-id="' + _escH(item.id || '') + '">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;padding-bottom:7px;border-bottom:1px solid #1e293b">' +
          '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">' +
            '<span class="comms-badge amber" style="font-weight:800">Draft ' + (_srIdx + 1) + ' of ' + q.length + '</span>' +
            '<span class="comms-badge sky">' + _escH(item.account || 'PSU 365') + '</span>' +
            '<span class="comms-badge emerald">' + _escH(item.urgency || 'Steward Staged') + '</span>' +
            (item.queued_by ? '<span style="font-size:10.5px;color:#c4b5fd">Queued via ' + _escH(item.queued_by) + '</span>' : '') +
          '</div>' +
          '<div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap">' +
            '<button type="button" class="tw-btn" data-sr-nav="-1" title="Previous Draft">&larr; Prev</button>' +
            navPills +
            '<button type="button" class="tw-btn" data-sr-nav="1" title="Next Draft">Next &rarr;</button>' +
          '</div>' +
        '</div>' +
        '<div class="sr-diff-grid">' +
          '<div style="background:#070b12;border:1px solid #1e293b;border-radius:7px;padding:8px 10px;display:flex;flex-direction:column;justify-content:space-between;gap:8px">' +
            '<div>' +
              '<div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:#94a3b8;margin-bottom:4px">&#128233; Incoming Context / Prompt</div>' +
              '<div style="font-size:11.5px;font-weight:700;color:#f8fafc;margin-bottom:4px">' + _escH(item.subject || '(No Subject)') + '</div>' +
              '<div style="font-size:11.5px;color:#cbd5e1;white-space:pre-wrap;line-height:1.45">' + _escH(_sanitizeEmailSandboxText(item.incoming_snippet || '')) + '</div>' +
            '</div>' +
            '<div style="padding:6px 8px;border-radius:6px;background:rgba(56,189,248,0.1);border:1px solid rgba(56,189,248,0.3);font-size:10.5px;color:#7dd3fc">' +
              '&#10024; <b>Steward Reasoning:</b> ' + _escH(item.context_reason || 'Drafted for rapid approval in Speed Racer.') +
            '</div>' +
          '</div>' +
          '<div style="background:#0d1524;border:1px solid #283548;border-radius:7px;padding:8px 10px;display:flex;flex-direction:column;gap:6px">' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">' +
              '<div><label style="font-size:10px;color:#94a3b8;display:block">To</label>' +
              '<input type="text" id="caveSrToInput" value="' + _escH(item.to || '') + '" style="width:100%;box-sizing:border-box;padding:4px 7px;border-radius:5px;border:1px solid #334155;background:#070b12;color:#f8fafc;font-size:11.5px"></div>' +
              '<div><label style="font-size:10px;color:#94a3b8;display:block">Subject</label>' +
              '<input type="text" id="caveSrSubjInput" value="' + _escH(item.subject || '') + '" style="width:100%;box-sizing:border-box;padding:4px 7px;border-radius:5px;border:1px solid #334155;background:#070b12;color:#f8fafc;font-size:11.5px"></div>' +
            '</div>' +
            '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:4px">' +
              '<label style="font-size:10px;font-weight:700;color:#6ee7b7">&#9998; Steward Draft (Edit Freely Before Approving)</label>' +
              '<div style="display:inline-flex;gap:4px;flex-wrap:wrap">' +
                '<button type="button" class="tw-btn" data-sr-tone="shorter" style="font-size:10px;padding:1px 6px">&#10024; Shorter</button>' +
                '<button type="button" class="tw-btn" data-sr-tone="calendar" style="font-size:10px;padding:1px 6px">&#128197; + Calendar Slot</button>' +
                '<button type="button" class="tw-btn" data-sr-tone="warm" style="font-size:10px;padding:1px 6px">&#129309; Warmer</button>' +
              '</div>' +
            '</div>' +
            '<textarea id="caveSrBodyInput" rows="5" style="width:100%;box-sizing:border-box;padding:7px 9px;border-radius:6px;border:1px solid #3b4f6b;background:#070b12;color:#f8fafc;font-size:12px;line-height:1.45">' + _escH(item.draft_body || '') + '</textarea>' +
            '<div style="display:flex;gap:5px;align-items:center">' +
              '<input type="text" id="caveSrFeedbackInput" placeholder="Or give Steward quick feedback (e.g. Mention we will review the K-1 on Thursday)..." style="flex:1;padding:4px 7px;border-radius:5px;border:1px solid #283548;background:#070b12;color:#e2e8f0;font-size:11px">' +
              '<button type="button" class="tw-btn" id="btnCaveSrApplyFeedback" style="border-color:#a78bfa;color:#c4b5fd;font-weight:700">&#10024; Refine</button>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-top:8px;padding-top:8px;border-top:1px solid #1e293b">' +
          '<span style="font-size:11px;color:#fde68a;font-weight:650">&#128274; Permission Gate: Steward holds this draft until you click <b>Approve &amp; Send</b></span>' +
          '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">' +
            '<button type="button" class="tw-btn" id="btnCaveSrSkip" title="Keep in queue and move to next draft">&#9197; Skip / Later</button>' +
            '<button type="button" class="tw-btn" id="btnCaveSrDiscard" style="border-color:rgba(244,63,94,0.45);color:#fda4af" title="Remove draft from Speed Racer without sending">&#128465; Discard</button>' +
            '<button type="button" class="tw-btn done" id="btnCaveSrApproveSend" style="border-color:#10b981;background:rgba(16,185,129,0.24);color:#ecfdf5;font-weight:800;padding:4px 12px">&#10003; Approve &amp; Send</button>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  function _setSpeedRacerExpanded(open) {
    var tile = document.getElementById('caveSpeedRacerTile');
    var body = document.getElementById('caveSpeedRacerBody');
    var hint = document.getElementById('caveSrToggleHint');
    if (!tile || !body) return;
    tile.classList.toggle('open', !!open);
    body.hidden = !open;
    if (hint) {
      hint.innerHTML = open ? 'Click Header to Collapse &#9652;' : 'Click Header to Expand &#9662;';
    }
  }

  function _syncSpeedRacerFromServer(srObj) {
    if (!srObj || typeof srObj !== 'object') return;
    _srState = srObj;
    _renderCaveSpeedRacerTile();
    var ts = Number(srObj.auto_open_ts || 0);
    if (ts > _srLastAutoOpenTs) {
      _srLastAutoOpenTs = ts;
      window.openCaveSpeedRacer();
    }
  }

  window.openCaveSpeedRacer = function (draftId) {
    var calSec = document.getElementById('cal');
    if (calSec && !calSec.classList.contains('open')) {
      calSec.classList.add('open');
      var calTog = document.getElementById('calTog');
      if (calTog) calTog.textContent = 'Collapse';
    }
    var curGrid = document.getElementById('commsGrid');
    if (curGrid && curGrid.getAttribute('data-layout') === 'cal') {
      applyCommsLayout('split');
    }
    _setSpeedRacerExpanded(true);
    fetch('/api/steward/comms', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ action: 'speed_racer_act', sr_action: 'list' })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.speed_racer) {
          _srState = d.speed_racer;
          _srLastAutoOpenTs = Number(_srState.auto_open_ts || _srLastAutoOpenTs);
        }
        var q = (_srState && Array.isArray(_srState.queue)) ? _srState.queue : [];
        if (draftId) {
          for (var i = 0; i < q.length; i++) {
            if (q[i].id === draftId) {
              _srIdx = i;
              break;
            }
          }
        } else {
          _srIdx = 0;
        }
        _renderCaveSpeedRacerTile();
        var tile = document.getElementById('caveSpeedRacerTile');
        if (tile) {
          try { tile.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (err) {}
        }
      })
      .catch(function () {
        _renderCaveSpeedRacerTile();
      });
  };

  document.addEventListener('click', function (e) {
    var srHead = e.target.closest && e.target.closest('#caveSpeedRacerHead');
    if (srHead) {
      e.preventDefault();
      var body = document.getElementById('caveSpeedRacerBody');
      _setSpeedRacerExpanded(body ? body.hidden : true);
      return;
    }
    var openSrBtn = e.target.closest && e.target.closest('[data-cave-open-speed-racer]');
    if (openSrBtn) {
      e.preventDefault(); e.stopPropagation();
      window.openCaveSpeedRacer();
      return;
    }
    var queueMailBtn = e.target.closest && e.target.closest('[data-speed-racer-queue]');
    if (queueMailBtn) {
      e.preventDefault(); e.stopPropagation();
      var mUid = queueMailBtn.getAttribute('data-mail-uid') || '';
      var mTo = queueMailBtn.getAttribute('data-mail-sender') || queueMailBtn.getAttribute('data-mail-from') || '';
      var mFrom = queueMailBtn.getAttribute('data-mail-from') || mTo;
      var mSubj = queueMailBtn.getAttribute('data-mail-subject') || '(No Subject)';
      var mAcct = queueMailBtn.getAttribute('data-mail-account') || 'PSU 365';
      var mSnip = queueMailBtn.getAttribute('data-mail-snippet') || '';
      queueMailBtn.disabled = true;
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'speed_racer_queue',
          uid: mUid,
          to: mFrom + (mTo && mTo.indexOf('@') >= 0 && mFrom.indexOf('@') < 0 ? (' <' + mTo + '>') : ''),
          subject: mSubj.indexOf('Re:') === 0 ? mSubj : ('Re: ' + mSubj),
          account: mAcct,
          incoming_snippet: mSnip,
          queued_by: 'Inbox [-> Speed Racer] button'
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          queueMailBtn.disabled = false;
          if (d && d.ok && d.speed_racer) {
            _srState = d.speed_racer;
            _srIdx = 0;
            _setSpeedRacerExpanded(true);
            _renderCaveSpeedRacerTile();
            var srTile = document.getElementById('caveSpeedRacerTile');
            if (srTile) {
              try { srTile.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (err) {}
            }
            receipt('\ud83c\udfce\ufe0f Queued "' + mSubj + '" into Speed Racer for your review & approval.');
          }
        })
        .catch(function () { queueMailBtn.disabled = false; });
      return;
    }
    var srStewardBtn = e.target.closest && e.target.closest('#btnCaveSrStewardDraft');
    if (srStewardBtn) {
      e.preventDefault(); e.stopPropagation();
      var pIn = document.getElementById('caveSrStewardPromptInput');
      var promptTxt = pIn ? pIn.value.trim() : '';
      if (!promptTxt) return;
      srStewardBtn.disabled = true;
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'speed_racer_queue',
          to: 'Recipient <contact@example.com>',
          subject: promptTxt.slice(0, 72),
          incoming_snippet: 'Steward instruction: ' + promptTxt,
          context_reason: 'Drafted by Cave of Wonders Steward from your Speed Racer instruction.',
          draft_body: 'Hi,\n\nFollowing up regarding: ' + promptTxt + '\n\nPlease let me know if you need any additional materials from my side.\n\nBest,\nJohn',
          queued_by: 'Steward Prompt'
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          srStewardBtn.disabled = false;
          if (pIn) pIn.value = '';
          if (d && d.ok && d.speed_racer) {
            _srState = d.speed_racer;
            _srIdx = 0;
            _renderCaveSpeedRacerTile();
            receipt('\ud83c\udfce\ufe0f Steward drafted & queued email in Speed Racer.');
          }
        })
        .catch(function () { srStewardBtn.disabled = false; });
      return;
    }
    var srNavBtn = e.target.closest && e.target.closest('[data-sr-nav]');
    if (srNavBtn) {
      e.preventDefault();
      var delta = parseInt(srNavBtn.getAttribute('data-sr-nav') || '1', 10);
      _srIdx += delta;
      _renderCaveSpeedRacerTile();
      return;
    }
    var srPickBtn = e.target.closest && e.target.closest('[data-sr-pick-idx]');
    if (srPickBtn) {
      e.preventDefault();
      _srIdx = parseInt(srPickBtn.getAttribute('data-sr-pick-idx') || '0', 10);
      _renderCaveSpeedRacerTile();
      return;
    }
    var srToneBtn = e.target.closest && e.target.closest('[data-sr-tone]');
    if (srToneBtn) {
      e.preventDefault();
      var tone = srToneBtn.getAttribute('data-sr-tone') || '';
      var bEl = document.getElementById('caveSrBodyInput');
      if (!bEl) return;
      var cur = bEl.value || '';
      if (tone === 'shorter') {
        var lines = cur.split('\n').filter(function (ln) { return ln.trim().length > 0; });
        if (lines.length > 3) {
          bEl.value = lines[0] + '\n\n' + lines[1] + '\n\nBest,\nJohn';
        }
      } else if (tone === 'calendar') {
        bEl.value = cur.replace(/\n*Best,\nJohn/i, '') + '\n\nI have open slots on Thursday 2:00-3:30 PM ET or Friday 10:30 AM-12:00 PM ET if either works.\n\nBest,\nJohn';
      } else if (tone === 'warm') {
        bEl.value = cur.replace(/^Hi([^,\n]*),/i, 'Hi$1,\n\nHope your week is going well!');
      }
      return;
    }
    var srRefineBtn = e.target.closest && e.target.closest('#btnCaveSrApplyFeedback');
    if (srRefineBtn) {
      e.preventDefault();
      var fbIn = document.getElementById('caveSrFeedbackInput');
      var bIn = document.getElementById('caveSrBodyInput');
      if (fbIn && bIn && fbIn.value.trim()) {
        var note = fbIn.value.trim();
        bIn.value = bIn.value.replace(/\n*Best,\nJohn/i, '') + '\n\n' + note + '\n\nBest,\nJohn';
        fbIn.value = '';
        receipt('\u2728 Steward incorporated your feedback into the Speed Racer draft.');
      }
      return;
    }
    var srSkipBtn = e.target.closest && e.target.closest('#btnCaveSrSkip');
    if (srSkipBtn) {
      e.preventDefault();
      var qSkip = (_srState && Array.isArray(_srState.queue)) ? _srState.queue : [];
      var curSkip = qSkip[_srIdx];
      if (!curSkip) return;
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'speed_racer_act', sr_action: 'skip', id: curSkip.id })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.speed_racer) {
            _srState = d.speed_racer;
            _renderCaveSpeedRacerTile();
          }
        });
      return;
    }
    var srDiscardBtn = e.target.closest && e.target.closest('#btnCaveSrDiscard');
    if (srDiscardBtn) {
      e.preventDefault();
      var qDisc = (_srState && Array.isArray(_srState.queue)) ? _srState.queue : [];
      var curDisc = qDisc[_srIdx];
      if (!curDisc) return;
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ action: 'speed_racer_act', sr_action: 'discard', id: curDisc.id })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.speed_racer) {
            _srState = d.speed_racer;
            _renderCaveSpeedRacerTile();
            receipt('Removed draft from Speed Racer queue.');
          }
        });
      return;
    }
    var srApproveBtn = e.target.closest && e.target.closest('#btnCaveSrApproveSend');
    if (srApproveBtn) {
      e.preventDefault();
      var qApp = (_srState && Array.isArray(_srState.queue)) ? _srState.queue : [];
      var curApp = qApp[_srIdx];
      if (!curApp) return;
      var toV = ((document.getElementById('caveSrToInput') || {}).value || curApp.to || '').trim();
      var subV = ((document.getElementById('caveSrSubjInput') || {}).value || curApp.subject || '').trim();
      var bodyV = ((document.getElementById('caveSrBodyInput') || {}).value || curApp.draft_body || '').trim();
      srApproveBtn.disabled = true;
      _srLastSentDraft = {
        id: curApp.id,
        to: toV,
        subject: subV,
        account: curApp.account || 'PSU 365',
        incoming_snippet: curApp.incoming_snippet || '',
        context_reason: curApp.context_reason || '',
        draft_body: bodyV
      };
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'speed_racer_act',
          sr_action: 'approve_send',
          id: curApp.id,
          to: toV,
          subject: subV,
          draft_body: bodyV
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          srApproveBtn.disabled = false;
          if (d && d.ok) {
            if (d.speed_racer) _srState = d.speed_racer;
            _renderCaveSpeedRacerTile();
            if (Array.isArray(d.sent_emails)) {
              if (!_caveCommsData) _caveCommsData = { ok: true };
              _caveCommsData.sent_emails = d.sent_emails;
              _hydrateMailCardsFromCommsData(_caveCommsData);
            }
            var undoBar = document.getElementById('caveSpeedRacerUndoBar');
            var undoTxt = document.getElementById('caveSpeedRacerUndoText');
            if (undoBar && undoTxt) {
              undoTxt.innerHTML = '&#10003; Approved &amp; Sent to <b>' + _escH(toV) + '</b> (' + _escH(subV) + ') &mdash; logged in Sent Emails.';
              undoBar.hidden = false;
              setTimeout(function () { undoBar.hidden = true; }, 6000);
            }
            receipt('\u2713 Speed Racer: Approved & sent email to ' + toV + '!');
          }
        })
        .catch(function () { srApproveBtn.disabled = false; });
      return;
    }
    var srUndoBtn = e.target.closest && e.target.closest('#btnCaveSrUndoSend');
    if (srUndoBtn && _srLastSentDraft) {
      e.preventDefault();
      var restoreItem = _srLastSentDraft;
      _srLastSentDraft = null;
      var undoBar2 = document.getElementById('caveSpeedRacerUndoBar');
      if (undoBar2) undoBar2.hidden = true;
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'speed_racer_queue',
          to: restoreItem.to,
          subject: restoreItem.subject,
          account: restoreItem.account,
          incoming_snippet: restoreItem.incoming_snippet,
          context_reason: restoreItem.context_reason,
          draft_body: restoreItem.draft_body,
          queued_by: 'Undo Send'
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.speed_racer) {
            _srState = d.speed_racer;
            _srIdx = 0;
            _renderCaveSpeedRacerTile();
            receipt('\u21a9 Undid send — draft restored to Speed Racer queue.');
          }
        });
      return;
    }
  });

  // -------------------------------------------------------------------------
  // Variation A: Persistent Working List Spine with Per-Step Connections
  // -------------------------------------------------------------------------
  var _wlState = window.ANCHOR_WORKING_LIST_INIT || { tiles: [], cockpit_items_catalog: [], initiative_items_catalog: [] };
  var _wlCatFilter = 'all';
  var _wlOpenConnDrawer = {}; // key: tileId + '::' + stepIdx

  function _wlMutate(op, payload) {
    var bodyObj = Object.assign({ action: 'working_list_mutate', wl_op: op }, payload || {});
    return fetch('/api/steward/comms', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify(bodyObj)
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.working_list) {
          _wlState = d.working_list;
          _renderWorkingListSpine();
        }
        return d;
      })
      .catch(function () {});
  }

  function _buildCockpitOptionsHtml(selectedKey) {
    var cat = (_wlState && Array.isArray(_wlState.cockpit_items_catalog)) ? _wlState.cockpit_items_catalog : [];
    var out = ['<option value="">— None (Not linked to an AI Cockpit item) —</option>'];
    cat.forEach(function (c) {
      var val = (c.cockpitName || '') + '||' + (c.itemLabel || '') + '||' + (c.kind || 'Wave / Deliverable') + '||' + (c.href || '/steward/v1');
      var sel = (selectedKey && selectedKey === (c.cockpitName + '||' + c.itemLabel)) ? ' selected' : '';
      out.push('<option value="' + _escH(val) + '"' + sel + '>\ud83d\udef8 ' + _escH(c.cockpitName + ' \u00b7 ' + c.itemLabel + ' (' + (c.kind || 'Item') + ')') + '</option>');
    });
    return out.join('');
  }

  function _buildInitiativeOptionsHtml(selectedKey) {
    var cat = (_wlState && Array.isArray(_wlState.initiative_items_catalog)) ? _wlState.initiative_items_catalog : [];
    var out = ['<option value="">— None (Not linked to an Initiative) —</option>'];
    cat.forEach(function (it) {
      var val = (it.initiativeName || '') + '||' + (it.role || 'Initiative') + '||' + (it.href || '/campaign');
      var sel = (selectedKey && selectedKey === it.initiativeName) ? ' selected' : '';
      out.push('<option value="' + _escH(val) + '"' + sel + '>\ud83c\udf1f ' + _escH(it.initiativeName + ' (' + (it.role || 'Initiative') + ')') + '</option>');
    });
    return out.join('');
  }

  function _renderWorkingListSpine() {
    var container = document.getElementById('wlTilesContainer');
    if (!container) return;
    var tiles = (_wlState && Array.isArray(_wlState.tiles)) ? _wlState.tiles : [];
    var activeTiles = tiles.filter(function (t) { return !t.archived; });
    var archTiles = tiles.filter(function (t) { return !!t.archived; });

    var cAll = document.getElementById('wlCntAll');
    var cBus = document.getElementById('wlCntBusiness');
    var cTch = document.getElementById('wlCntTeaching');
    var cRes = document.getElementById('wlCntResearch');
    var cPer = document.getElementById('wlCntPersonal');
    var cArc = document.getElementById('wlCntArchived');
    var hdrCnt = document.getElementById('wlHeaderCounts');
    if (cAll) cAll.textContent = String(activeTiles.length);
    if (cBus) cBus.textContent = String(activeTiles.filter(function (t) { return t.category === 'Business'; }).length);
    if (cTch) cTch.textContent = String(activeTiles.filter(function (t) { return t.category === 'Teaching'; }).length);
    if (cRes) cRes.textContent = String(activeTiles.filter(function (t) { return t.category === 'Research'; }).length);
    if (cPer) cPer.textContent = String(activeTiles.filter(function (t) { return t.category === 'Personal'; }).length);
    if (cArc) cArc.textContent = String(archTiles.length);
    if (hdrCnt) hdrCnt.textContent = activeTiles.length + ' Active Tiles \u00b7 ' + archTiles.length + ' Archived';

    $$('#wlCatTabs [data-wl-cat]').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-wl-cat') === _wlCatFilter);
    });

    var visible = tiles.filter(function (t) {
      if (_wlCatFilter === 'archived') return !!t.archived;
      if (t.archived) return false;
      if (_wlCatFilter === 'all') return true;
      return t.category === _wlCatFilter;
    });

    if (!visible.length) {
      container.innerHTML = '<div class="tw-empty">No effort tiles in this category view. Use the input bar above to add a multi-step effort tile to your persistent list.</div>';
      return;
    }

    container.innerHTML = visible.map(function (t) {
      var tid = _escH(t.id || '');
      var prio = String(t.prio || 'B1');
      var pCls = prio.charAt(0) === 'A' ? 'prio-a' : (prio.charAt(0) === 'B' ? 'prio-b' : 'prio-c');
      var steps = Array.isArray(t.steps) ? t.steps : [];
      var doneCount = steps.filter(function (s) { return !!s.done; }).length;
      var totalCount = steps.length;
      var connCount = steps.filter(function (s) { return !!(s.cockpitItem || s.initiativeItem); }).length;
      var nextStep = steps.find(function (s) { return !s.done; });
      var nextTxt = nextStep
        ? ('<b>Next step:</b> ' + _escH(nextStep.text || ''))
        : ('&#10003; All ' + totalCount + ' steps completed &mdash; ready to archive!');

      var stepsHtml = steps.map(function (s, sIdx) {
        var rawCk = s.cockpitItem || null;
        var ckItem = (typeof rawCk === 'string' && rawCk)
          ? { cockpitName: rawCk.split('·')[0].trim(), itemLabel: (rawCk.split('·').slice(1).join('·') || rawCk).trim(), kind: s.cockpitStatus || 'Wave / Deliverable', href: s.cockpitUrl || '/steward/v1' }
          : rawCk;
        var rawIn = s.initiativeItem || null;
        var inItem = (typeof rawIn === 'string' && rawIn)
          ? { initiativeName: rawIn, role: 'Initiative', href: s.initiativeUrl || '/?view=cave' }
          : rawIn;
        var drawerKey = (t.id || '') + '::' + sIdx;
        var isDrawerOpen = !!_wlOpenConnDrawer[drawerKey];
        var selCkKey = (ckItem && ckItem.cockpitName) ? ((ckItem.cockpitName || '') + '||' + (ckItem.itemLabel || '')) : '';
        var selInKey = (inItem && inItem.initiativeName) ? (inItem.initiativeName || '') : '';

        var chips = [];
        if (ckItem && ckItem.cockpitName) {
          chips.push(
            '<span class="wl-conn-chip cockpit" title="Connected AI Cockpit Item (' + _escH(ckItem.kind || 'Wave / Deliverable') + ')">' +
              '&#128760; <b>' + _escH(ckItem.cockpitName) + ':</b> ' + _escH(ckItem.itemLabel || '') +
              ' <a href="' + _escH(ckItem.href || s.cockpitUrl || '/steward/v1') + '" target="_blank" rel="noopener">Open &#8599;</a>' +
              ' <button type="button" class="mini" data-wl-unlink-ck="' + tid + '" data-wl-step-idx="' + sIdx + '" title="Unlink AI Cockpit item" style="padding:0 4px;font-size:10px">&times;</button>' +
            '</span>'
          );
        }
        if (inItem && inItem.initiativeName) {
          chips.push(
            '<span class="wl-conn-chip initiative" title="Connected Cave / Star Chart Initiative">' +
              '&#127775; <b>' + _escH(inItem.initiativeName) + '</b> (' + _escH(inItem.role || 'Initiative') + ')' +
              ' <a href="' + _escH(inItem.href || s.initiativeUrl || '/?view=cave') + '" target="_blank" rel="noopener">View &#8599;</a>' +
              ' <button type="button" class="mini" data-wl-unlink-init="' + tid + '" data-wl-step-idx="' + sIdx + '" title="Unlink Initiative" style="padding:0 4px;font-size:10px">&times;</button>' +
            '</span>'
          );
        }
        if (!chips.length) {
          chips.push('<span style="font-size:10.5px;color:#64748b;font-style:italic">No Cockpit or Initiative linked yet</span>');
        }

        return (
          '<div class="wl-substep-card' + (s.done ? ' done' : '') + '" data-wl-step-idx="' + sIdx + '">' +
            '<div class="wl-substep-top">' +
              '<label style="display:flex;align-items:center;gap:7px;cursor:pointer;flex:1;font-size:12px;color:' + (s.done ? '#94a3b8;text-decoration:line-through' : '#f1f5f9') + '">' +
                '<input type="checkbox" data-wl-step-check="' + tid + '" data-wl-step-idx="' + sIdx + '"' + (s.done ? ' checked' : '') + ' style="accent-color:#10b981;cursor:pointer">' +
                '<span>' + _escH(s.text || '') + '</span>' +
              '</label>' +
              '<div style="display:inline-flex;align-items:center;gap:4px">' +
                '<button type="button" class="tw-btn" data-wl-step-conn-toggle="' + tid + '" data-wl-step-idx="' + sIdx + '" style="font-size:10px;padding:1px 7px;border-color:rgba(56,189,248,0.45);color:#7dd3fc" title="Connect this step to an AI Cockpit item and/or an Initiative">&#128279; Connect Cockpit / Initiative &#9662;</button>' +
                '<button type="button" class="mini" data-wl-step-del="' + tid + '" data-wl-step-idx="' + sIdx + '" title="Remove step" style="padding:0 5px;font-size:11px">&times;</button>' +
              '</div>' +
            '</div>' +
            '<div class="wl-substep-conn-row">' + chips.join('') + '</div>' +
            '<div class="wl-connector-drawer"' + (isDrawerOpen ? '' : ' hidden') + ' id="wlConnDrawer-' + tid + '-' + sIdx + '">' +
              '<div style="font-size:10.5px;font-weight:750;color:#7dd3fc;margin-bottom:5px">&#128279; Connect Step #' + (sIdx + 1) + ' to an AI Cockpit Item AND/OR an Initiative (or both):</div>' +
              '<div style="display:grid;grid-template-columns:1fr 1fr auto;gap:6px;align-items:end">' +
                '<div>' +
                  '<label style="font-size:10px;color:#94a3b8;display:block;margin-bottom:2px">&#128760; AI Cockpit Item (Wave / Deliverable)</label>' +
                  '<select id="wlSelCk-' + tid + '-' + sIdx + '" style="width:100%;padding:4px 6px;border-radius:5px;border:1px solid #334155;background:#070b12;color:#f1f5f9;font-size:11px">' +
                    _buildCockpitOptionsHtml(selCkKey) +
                  '</select>' +
                '</div>' +
                '<div>' +
                  '<label style="font-size:10px;color:#94a3b8;display:block;margin-bottom:2px">&#127775; Cave / Star Chart Initiative</label>' +
                  '<select id="wlSelInit-' + tid + '-' + sIdx + '" style="width:100%;padding:4px 6px;border-radius:5px;border:1px solid #334155;background:#070b12;color:#f1f5f9;font-size:11px">' +
                    _buildInitiativeOptionsHtml(selInKey) +
                  '</select>' +
                '</div>' +
                '<button type="button" class="tw-btn done" data-wl-step-conn-save="' + tid + '" data-wl-step-idx="' + sIdx + '" style="font-weight:700;padding:4px 10px">&#128190; Save Links</button>' +
              '</div>' +
            '</div>' +
          '</div>'
        );
      }).join('');

      var detailsHtml = '';
      if (t.expanded) {
        detailsHtml =
          '<div class="wl-details" id="wlDetails-' + tid + '">' +
            '<div class="wl-details-grid">' +
              '<div class="wl-substeps-box">' +
                '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:7px;flex-wrap:wrap">' +
                  '<span style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:#7dd3fc">&#9745; Multi-Step Checklist &amp; Per-Step Connections (' + doneCount + '/' + totalCount + ')</span>' +
                  '<span style="font-size:10.5px;color:#94a3b8">Each step can link to an &#128760; AI Cockpit item, a &#127775; Initiative, or both</span>' +
                '</div>' +
                stepsHtml +
                '<div style="margin-top:8px;padding-top:8px;border-top:1px dashed #1e293b;display:flex;flex-direction:column;gap:6px">' +
                  '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
                    '<input type="text" id="wlAddStepText-' + tid + '" placeholder="Add a concrete step to this tile..." style="flex:1;min-width:180px;padding:5px 8px;border-radius:6px;border:1px solid #283548;background:#070b12;color:#f1f5f9;font-size:11.5px">' +
                    '<button type="button" class="tw-btn done" data-wl-add-step="' + tid + '" style="font-weight:700">+ Add Step</button>' +
                  '</div>' +
                  '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">' +
                    '<select id="wlAddStepCk-' + tid + '" style="padding:4px 6px;border-radius:5px;border:1px solid #283548;background:#070b12;color:#cbd5e1;font-size:10.5px">' +
                      _buildCockpitOptionsHtml('') +
                    '</select>' +
                    '<select id="wlAddStepInit-' + tid + '" style="padding:4px 6px;border-radius:5px;border:1px solid #283548;background:#070b12;color:#cbd5e1;font-size:10.5px">' +
                      _buildInitiativeOptionsHtml('') +
                    '</select>' +
                  '</div>' +
                '</div>' +
              '</div>' +
              '<div class="wl-brainstorm-box">' +
                '<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;margin-bottom:6px;flex-wrap:wrap">' +
                  '<span style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:#c4b5fd">&#129504; Brainstorming &amp; Details Scratchpad</span>' +
                  '<span style="font-size:10px;color:#94a3b8">Auto-saved to your persistent list</span>' +
                '</div>' +
                '<textarea class="wl-scratch-ta" data-wl-notes="' + tid + '" placeholder="Brainstorm what needs to get done, key dependencies, or instructions for the AI Cockpit...">' + _escH(t.brainstormNotes || '') + '</textarea>' +
                '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:8px">' +
                  '<button type="button" class="tw-btn" data-wl-brainstorm="' + tid + '" style="border-color:rgba(167,139,250,0.55);color:#c4b5fd;font-weight:700">&#10024; Brainstorm Connected Steps</button>' +
                  '<button type="button" class="tw-btn" data-wl-draft-sr="' + tid + '" style="border-color:rgba(245,158,11,0.55);color:#fde68a;font-weight:700">&#127950;&#65039; Draft Related Email in Speed Racer</button>' +
                  (t.cockpitHref ? ('<a class="tw-btn" href="' + _escH(t.cockpitHref) + '" target="_blank" rel="noopener" style="border-color:rgba(56,189,248,0.55);color:#7dd3fc;text-decoration:none;font-weight:700">&#128760; Open ' + _escH(t.cockpitName || 'AI Cockpit') + ' &#8599;</a>') : '') +
                '</div>' +
              '</div>' +
            '</div>' +
          '</div>';
      }

      return (
        '<article class="wl-tile ' + pCls + (t.expanded ? ' is-expanded' : '') + (t.done ? ' is-done' : '') + '" data-wl-tile-id="' + tid + '">' +
          '<div class="wl-summary" data-wl-toggle-expand="' + tid + '">' +
            '<div class="wl-move-col">' +
              '<button type="button" class="wl-move-btn" data-wl-move="up" data-wl-id="' + tid + '" title="Move tile up">&#9650;</button>' +
              '<button type="button" class="wl-move-btn" data-wl-move="down" data-wl-id="' + tid + '" title="Move tile down">&#9660;</button>' +
            '</div>' +
            '<input type="checkbox" data-wl-check-tile="' + tid + '"' + (t.done ? ' checked' : '') + ' title="Check off entire multi-step tile" style="width:15px;height:15px;accent-color:#10b981;cursor:pointer;flex-shrink:0">' +
            '<span class="wl-prio" data-wl-cycle-prio="' + tid + '" title="Click to cycle Covey Priority (A1 -> A2 -> B1 -> C1)">' + _escH(prio) + '</span>' +
            '<div class="wl-main">' +
              '<div class="wl-title-line">' +
                '<b class="wl-title">' + _escH(t.title || 'Effort Tile') + '</b>' +
                '<span class="wl-pill">' + _escH(t.category || 'Business') + '</span>' +
                '<span class="wl-pill sky">&#10003; ' + doneCount + '/' + totalCount + ' steps</span>' +
                '<span class="wl-pill purple">&#128279; ' + connCount + '/' + totalCount + ' connected to Cockpit / Initiative</span>' +
              '</div>' +
              '<div class="wl-sub">' + nextTxt + '</div>' +
            '</div>' +
            '<div class="wl-acts">' +
              (t.cockpitHref ? ('<a class="mini" href="' + _escH(t.cockpitHref) + '" target="_blank" rel="noopener" style="border-color:#38bdf8;color:#7dd3fc;text-decoration:none" title="Open primary AI Cockpit">&#128760; Cockpit &#8599;</a>') : '') +
              '<button type="button" class="mini" data-wl-archive="' + tid + '" title="' + (t.archived ? 'Restore to Active Spine' : 'Archive completed tile') + '">' + (t.archived ? '&#8617; Restore' : '&#128230; Archive') + '</button>' +
              '<button type="button" class="mini" data-wl-toggle-expand="' + tid + '" style="border-color:#38bdf8;color:#7dd3fc;font-weight:700">' + (t.expanded ? '&#9652; Collapse' : '&#9662; Open Steps &amp; Connections') + '</button>' +
            '</div>' +
          '</div>' +
          detailsHtml +
        '</article>'
      );
    }).join('');
  }

  document.addEventListener('click', function (e) {
    var catBtn = e.target.closest && e.target.closest('#wlCatTabs [data-wl-cat]');
    if (catBtn) {
      e.preventDefault();
      _wlCatFilter = catBtn.getAttribute('data-wl-cat') || 'all';
      _renderWorkingListSpine();
      return;
    }
    var colBtn = e.target.closest && e.target.closest('#wlSpineCollapseBtn');
    if (colBtn) {
      e.preventDefault();
      var body = document.getElementById('wlSpineBody');
      if (body) {
        body.hidden = !body.hidden;
        colBtn.textContent = body.hidden ? 'Expand' : 'Collapse';
      }
      return;
    }
    var addBtn = e.target.closest && e.target.closest('#btnWlAddTile, #btnWlAddTopA1');
    if (addBtn) {
      e.preventDefault();
      var tIn = document.getElementById('wlNewTileTitle');
      var cIn = document.getElementById('wlNewTileCat');
      var pIn = document.getElementById('wlNewTilePrio');
      var title = tIn ? tIn.value.trim() : '';
      if (!title) return;
      var isTop = addBtn.id === 'btnWlAddTopA1';
      if (tIn) tIn.value = '';
      _wlMutate('add_tile', {
        title: title,
        category: cIn ? cIn.value : 'Business',
        prio: isTop ? 'A1' : (pIn ? pIn.value : 'B1'),
        insert_top: isTop
      }).then(function () {
        receipt('\ud83d\udccb Added "' + title + '" to your Persistent Working List Spine.');
      });
      return;
    }
    var moveBtn = e.target.closest && e.target.closest('[data-wl-move]');
    if (moveBtn) {
      e.preventDefault(); e.stopPropagation();
      _wlMutate('move_tile', {
        tile_id: moveBtn.getAttribute('data-wl-id') || '',
        dir: moveBtn.getAttribute('data-wl-move') || 'up'
      });
      return;
    }
    var prioBtn = e.target.closest && e.target.closest('[data-wl-cycle-prio]');
    if (prioBtn) {
      e.preventDefault(); e.stopPropagation();
      _wlMutate('cycle_prio', { tile_id: prioBtn.getAttribute('data-wl-cycle-prio') || '' });
      return;
    }
    var archBtn = e.target.closest && e.target.closest('[data-wl-archive]');
    if (archBtn) {
      e.preventDefault(); e.stopPropagation();
      _wlMutate('archive_tile', { tile_id: archBtn.getAttribute('data-wl-archive') || '' }).then(function () {
        receipt('Updated tile archive status.');
      });
      return;
    }
    var chkTile = e.target.closest && e.target.closest('[data-wl-check-tile]');
    if (chkTile) {
      e.stopPropagation();
      _wlMutate('toggle_tile_done', { tile_id: chkTile.getAttribute('data-wl-check-tile') || '' });
      return;
    }
    var expToggle = e.target.closest && e.target.closest('[data-wl-toggle-expand]');
    if (expToggle && !e.target.closest('a, input, [data-wl-move], [data-wl-cycle-prio], [data-wl-archive]')) {
      e.preventDefault(); e.stopPropagation();
      _wlMutate('toggle_expand', { tile_id: expToggle.getAttribute('data-wl-toggle-expand') || '' });
      return;
    }
    var stepChk = e.target.closest && e.target.closest('[data-wl-step-check]');
    if (stepChk) {
      e.stopPropagation();
      _wlMutate('toggle_step', {
        tile_id: stepChk.getAttribute('data-wl-step-check') || '',
        step_idx: parseInt(stepChk.getAttribute('data-wl-step-idx') || '0', 10)
      });
      return;
    }
    var stepDel = e.target.closest && e.target.closest('[data-wl-step-del]');
    if (stepDel) {
      e.preventDefault(); e.stopPropagation();
      _wlMutate('delete_step', {
        tile_id: stepDel.getAttribute('data-wl-step-del') || '',
        step_idx: parseInt(stepDel.getAttribute('data-wl-step-idx') || '0', 10)
      });
      return;
    }
    var connToggle = e.target.closest && e.target.closest('[data-wl-step-conn-toggle]');
    if (connToggle) {
      e.preventDefault(); e.stopPropagation();
      var tidC = connToggle.getAttribute('data-wl-step-conn-toggle') || '';
      var sIdxC = parseInt(connToggle.getAttribute('data-wl-step-idx') || '0', 10);
      var k = tidC + '::' + sIdxC;
      _wlOpenConnDrawer[k] = !_wlOpenConnDrawer[k];
      _renderWorkingListSpine();
      return;
    }
    var connSave = e.target.closest && e.target.closest('[data-wl-step-conn-save]');
    if (connSave) {
      e.preventDefault(); e.stopPropagation();
      var tidS = connSave.getAttribute('data-wl-step-conn-save') || '';
      var sIdxS = parseInt(connSave.getAttribute('data-wl-step-idx') || '0', 10);
      var ckSel = document.getElementById('wlSelCk-' + tidS + '-' + sIdxS);
      var inSel = document.getElementById('wlSelInit-' + tidS + '-' + sIdxS);
      var ckVal = ckSel ? ckSel.value : '';
      var inVal = inSel ? inSel.value : '';
      var ckObj = null;
      if (ckVal) {
        var p1 = ckVal.split('||');
        ckObj = { cockpitName: p1[0] || '', itemLabel: p1[1] || '', kind: p1[2] || 'Wave / Deliverable', href: p1[3] || '/steward/v1' };
      }
      var inObj = null;
      if (inVal) {
        var p2 = inVal.split('||');
        inObj = { initiativeName: p2[0] || '', role: p2[1] || 'Initiative', href: p2[2] || '/campaign' };
      }
      _wlOpenConnDrawer[tidS + '::' + sIdxS] = false;
      _wlMutate('connect_step', {
        tile_id: tidS,
        step_idx: sIdxS,
        cockpitItem: ckObj,
        initiativeItem: inObj
      }).then(function () {
        receipt('\ud83d\udd17 Saved AI Cockpit & Initiative connections for Step #' + (sIdxS + 1) + '.');
      });
      return;
    }
    var unlinkCk = e.target.closest && e.target.closest('[data-wl-unlink-ck]');
    if (unlinkCk) {
      e.preventDefault(); e.stopPropagation();
      var tidU1 = unlinkCk.getAttribute('data-wl-unlink-ck') || '';
      var sIdxU1 = parseInt(unlinkCk.getAttribute('data-wl-step-idx') || '0', 10);
      var tilesU1 = (_wlState && _wlState.tiles) || [];
      var tObj1 = tilesU1.find(function (x) { return x.id === tidU1; });
      var existingInit = (tObj1 && tObj1.steps && tObj1.steps[sIdxU1]) ? tObj1.steps[sIdxU1].initiativeItem : null;
      _wlMutate('connect_step', { tile_id: tidU1, step_idx: sIdxU1, cockpitItem: null, initiativeItem: existingInit });
      return;
    }
    var unlinkInit = e.target.closest && e.target.closest('[data-wl-unlink-init]');
    if (unlinkInit) {
      e.preventDefault(); e.stopPropagation();
      var tidU2 = unlinkInit.getAttribute('data-wl-unlink-init') || '';
      var sIdxU2 = parseInt(unlinkInit.getAttribute('data-wl-step-idx') || '0', 10);
      var tilesU2 = (_wlState && _wlState.tiles) || [];
      var tObj2 = tilesU2.find(function (x) { return x.id === tidU2; });
      var existingCk = (tObj2 && tObj2.steps && tObj2.steps[sIdxU2]) ? tObj2.steps[sIdxU2].cockpitItem : null;
      _wlMutate('connect_step', { tile_id: tidU2, step_idx: sIdxU2, cockpitItem: existingCk, initiativeItem: null });
      return;
    }
    var addStepBtn = e.target.closest && e.target.closest('[data-wl-add-step]');
    if (addStepBtn) {
      e.preventDefault(); e.stopPropagation();
      var tidA = addStepBtn.getAttribute('data-wl-add-step') || '';
      var stIn = document.getElementById('wlAddStepText-' + tidA);
      var ckIn = document.getElementById('wlAddStepCk-' + tidA);
      var inIn = document.getElementById('wlAddStepInit-' + tidA);
      var stTxt = stIn ? stIn.value.trim() : '';
      if (!stTxt) return;
      var ckObjA = null;
      if (ckIn && ckIn.value) {
        var pa = ckIn.value.split('||');
        ckObjA = { cockpitName: pa[0] || '', itemLabel: pa[1] || '', kind: pa[2] || 'Wave / Deliverable', href: pa[3] || '/steward/v1' };
      }
      var inObjA = null;
      if (inIn && inIn.value) {
        var pb = inIn.value.split('||');
        inObjA = { initiativeName: pb[0] || '', role: pb[1] || 'Initiative', href: pb[2] || '/campaign' };
      }
      _wlMutate('add_step', {
        tile_id: tidA,
        text: stTxt,
        cockpitItem: ckObjA,
        initiativeItem: inObjA
      });
      return;
    }
    var bsBtn = e.target.closest && e.target.closest('[data-wl-brainstorm]');
    if (bsBtn) {
      e.preventDefault(); e.stopPropagation();
      var tidB = bsBtn.getAttribute('data-wl-brainstorm') || '';
      var tilesB = (_wlState && _wlState.tiles) || [];
      var tObjB = tilesB.find(function (x) { return x.id === tidB; });
      if (!tObjB) return;
      _wlMutate('add_step', {
        tile_id: tidB,
        text: 'Verify final deliverable sign-off and sync with connected AI Cockpit',
        cockpitItem: tObjB.cockpitName ? { cockpitName: tObjB.cockpitName, itemLabel: 'Steward Checkpoint Deliverable', kind: 'Deliverable', href: tObjB.cockpitHref || '/steward/v1' } : null,
        initiativeItem: { initiativeName: tObjB.title || 'Active Initiative', role: 'Milestone', href: '/campaign' }
      }).then(function () {
        receipt('\u2728 Added brainstormed connected step to "' + (tObjB.title || 'Tile') + '".');
      });
      return;
    }
    var srFromTileBtn = e.target.closest && e.target.closest('[data-wl-draft-sr]');
    if (srFromTileBtn) {
      e.preventDefault(); e.stopPropagation();
      var tidSr = srFromTileBtn.getAttribute('data-wl-draft-sr') || '';
      var tilesSr = (_wlState && _wlState.tiles) || [];
      var tObjSr = tilesSr.find(function (x) { return x.id === tidSr; });
      if (!tObjSr) return;
      var nxtS = (tObjSr.steps || []).find(function (s) { return !s.done; });
      var stepDesc = nxtS ? nxtS.text : tObjSr.title;
      fetch('/api/steward/comms', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({
          action: 'speed_racer_queue',
          to: 'Counterparty <contact@example.com>',
          subject: 'Action & Next Steps: ' + (tObjSr.title || 'Working List Effort'),
          account: tObjSr.category === 'Business' ? 'Axmra 365' : 'PSU 365',
          incoming_snippet: 'Working List Tile (' + (tObjSr.prio || 'A1') + '): ' + (tObjSr.title || '') + ' — Next Step: ' + stepDesc,
          context_reason: 'Queued directly from your Persistent Working List Tile ("' + (tObjSr.title || '') + '") for rapid review & approval.',
          draft_body: 'Hi,\n\nI am writing to follow up on "' + (tObjSr.title || '') + '", specifically regarding our next step:\n- ' + stepDesc + '\n\nPlease let me know once this is ready so we can finalize.\n\nBest,\nJohn',
          queued_by: 'Working List Tile'
        })
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.ok && d.draft) {
            window.openCaveSpeedRacer(d.draft.id);
            receipt('\ud83c\udfce\ufe0f Queued email for "' + tObjSr.title + '" into Speed Racer & opened Speed Racer tile!');
          }
        });
      return;
    }
  });

  document.addEventListener('change', function (e) {
    var notesTa = e.target.closest && e.target.closest('[data-wl-notes]');
    if (notesTa) {
      var tidN = notesTa.getAttribute('data-wl-notes') || '';
      _wlMutate('update_notes', { tile_id: tidN, notes: notesTa.value || '' });
    }
  });

  window.refreshCaveWorkingList = function (wlData) {
    if (wlData && wlData.tiles) {
      _wlState = wlData;
      _renderWorkingListSpine();
    } else {
      _wlMutate('list', {});
    }
  };
  _renderCaveSpeedRacerTile();
  _renderWorkingListSpine();

  // Initialize source filters & check for active Gmail 2FA prompt on startup
  _applySourceFilterToDOM();
  setTimeout(function () { _ensureCaveCommsDataLoaded(false); }, 400);

  // Auto-refresh Comms every 5 minutes in background when idle
  setInterval(function () {
    if (document.hidden || tileOpen() || typingNow()) return;
    fetch('/api/steward/comms', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ action: 'sync_now' })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.ok) {
          _caveCommsData = d;
          renewInPlace();
        }
      })
      .catch(function () {});
  }, 300000);
})();
