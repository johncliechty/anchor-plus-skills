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
      if (key === 'calendar' || key === 'email') { $('#cal') && $('#cal').classList.add('open'); setCalTab(key === 'email' ? 'mail' : 'cal'); }
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
    var collabWasOpen = $('#caveCollabStrip') && $('#caveCollabStrip').classList.contains('open');
    ['shTriage', 'thisWeekBoard', 'cal', 'caveCollabStrip'].forEach(function (id) { var a = document.getElementById(id), b = doc.getElementById(id); if (a && b) morph(a, b); });
    ['nudgeSlot', 'seedCount', 'seedLbl', 'seedPanel', 'ptileCount', 'apGroups'].forEach(function (id) { var a = document.getElementById(id), b = doc.getElementById(id); if (a && b) morph(a, b); });
    if (openHzKey) {
      var nb = $('#shTriage .chz-card[data-hz-toggle="' + openHzKey + '"]'), nd = document.getElementById('hzDrawer-' + openHzKey);
      if (nb && nd) { nb.classList.add('open'); nb.setAttribute('aria-expanded', 'true'); nd.hidden = false; }
    }
    if (calWasOpen && $('#cal')) { $('#cal').classList.add('open'); if ($('#calTog')) $('#calTog').textContent = 'Collapse'; }
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

  // the Calendar / Email tile
  var cal = $('#cal'), calTog = $('#calTog');
  function setCalTab(which) { var a = $('#tabCal'), b = $('#tabMail'); if (a) a.classList.toggle('on', which === 'cal'); if (b) b.classList.toggle('on', which === 'mail'); }
  var calHead = $('#calHead'); if (calHead) calHead.addEventListener('click', function (e) {
    var tab = e.target.closest('.cal-tab');
    if (tab) { setCalTab(tab.id === 'tabMail' ? 'mail' : 'cal'); cal.classList.add('open'); }
    else cal.classList.toggle('open');
    if (calTog) calTog.textContent = cal.classList.contains('open') ? 'Close' : 'Open';
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
})();
