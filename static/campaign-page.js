/* The Campaign page (W3c, 2026-09-26; trimmed by its Rabbit read; the goal board W2 v2, 2026-09-29): the view toggle, the goal tiles that drag and open into their place, the lanes that open,
   the area filter, and every act on the record through /api/high-seat/campaign — each act a receipt with undo,
   one act in flight at a time; the seed's two questions and the park's trigger are asked on the card, never in a
   browser prompt; the composer talks to the steward through the effort's own say route. Nothing here invents
   data: the page was rendered from the record. */
(function () {
  'use strict';
  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  // Apply the board/conversation distinction to older service markup as well as the current renderer.
  var modeHeading = $('.modeh');
  var modeName = modeHeading ? modeHeading.textContent.trim().replace(/^The /, '').replace(/ \u2014 AI Cockpit$/, '') : '';
  if (modeName === 'Star Chart') {
    document.title = 'Star Chart';
    modeHeading.textContent = 'Star Chart';
    var modeBrand = $('.masthead .mh-stew b');
    if (modeBrand) modeBrand.textContent = 'Star Chart';
    var caveBack = $('.hdr .back');
    if (caveBack) caveBack.remove();
    var chartPid = (window.ANCHOR_BOOT || {}).campaign_pid || '';
    if (chartPid) $$('.hdr a.tool[href*="doc=1"], #dialogue .exhead a.note').forEach(function (link) {
      link.href = '/steward/v1?pid=' + encodeURIComponent(chartPid) + '&dir=';
      link.target = '_blank';
      if (link.classList.contains('tool')) link.textContent = 'Star Chart \u2014 AI Cockpit';
    });
  }
  function token() { try { return localStorage.getItem('anchor_token') || ''; } catch (e) { return ''; } }
  function headers() {
    var h = { 'Content-Type': 'application/json' };
    var t = token(); if (t) h['X-Anchor-Token'] = t;
    var b = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) || ''; if (b) h['X-Anchor-Build'] = b;
    return h;
  }
  function tokenQ() { var t = token(); return t ? ('?token=' + encodeURIComponent(t)) : ''; }
  var PID = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.campaign_pid) || '';
  function openWin(url) {
    var w = null; try { w = window.open('about:blank', '_blank'); } catch (e) { w = null; }
    if (!w || w === window) { receipt('The browser blocked the new window — allow popups and try again.', true); return; }
    try { w.opener = null; w.location.replace(url); w.focus(); } catch (e) { try { w.close(); } catch (_) {} }
  }
  var lastUndo = null;
  function receipt(text, bad, undo) {
    var r = $('#receipt'), t = $('#receiptText'), u = $('#undoBtn'); if (!r || !t) return;
    t.textContent = text; r.hidden = false; r.classList.toggle('bad', !!bad);
    lastUndo = undo || null; if (u) u.hidden = !undo;
  }
  // a receipt survives the reload that shows the changed board
  var YOU = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.you) || 'You';   // his name in a dialogue row, as the AI Cockpit says it (his word, 2026-10-01)
  var lastKey = 0; function markKey() { lastKey = Date.now(); }
  document.addEventListener('keydown', markKey); document.addEventListener('input', markKey, true);
  function typingNow() { var a = document.activeElement; return (Date.now() - lastKey < 10000) || !!(a && a.tagName === 'TEXTAREA' && a.value && a.value.trim()); }
  // W3b: the page renews itself when the record moves or a new build is live - never while he types or dictates
  // (his word, 2026-10-01); then, when he is quiet. The open goal keeps its place through the renewal (?open= in the address).
  var pendingRenew = null, pendingKey = '', renewVersion = '';
  function renew(text, key) {
    var k = key ? String(key) : '';
    try { if (k && sessionStorage.getItem('campaign_renewed_for') === k) return; } catch (e) {}   // one renewal per STAMP (Grok W3b); a new build is never caught by this
    if (typingNow()) { pendingRenew = text || pendingRenew || 'The record moved \u2014 the page is renewed.'; if (k) pendingKey = k; return; }
    var stampKey = k || pendingKey; pendingRenew = null; pendingKey = '';
    try { if (stampKey) sessionStorage.setItem('campaign_renewed_for', stampKey); } catch (e) {}
    try { if (renewVersion) sessionStorage.setItem('campaign_reloaded_for', renewVersion); } catch (e) {}
    try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: text || 'The record moved \u2014 the page is renewed.', bad: false, undo: null })); } catch (e) {}
    location.reload();
  }
  setInterval(function () { if (pendingRenew && !typingNow()) renew(pendingRenew); }, 5000);
  try { var kept = sessionStorage.getItem('campaign_receipt'); if (kept) { var k = JSON.parse(kept); receipt(k.text, k.bad, k.undo); sessionStorage.removeItem('campaign_receipt'); } } catch (e) {}

  // one act in flight at a time: a second click while the first is on its way is ignored until the reload
  var busy = false;
  function act(body, onDone) {
    if (busy) return;
    busy = true;
    body.pid = PID;
    fetch('/api/high-seat/campaign', { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) {
          busy = false;
          if (j && j.undo) {   // the act landed in part and the writer refused the rest: the receipt says so and its undo is his (Grok's read of W2b)
            try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: j.receipt || 'Refused.', bad: true, undo: j.undo })); } catch (e) {}
            location.reload(); return;
          }
          receipt((j && j.receipt) || 'Nothing was done.', true); return;
        }
        try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: j.receipt, bad: false, undo: j.undo || null })); } catch (e) {}
        if (onDone) { busy = false; onDone(j); } else location.reload();
      })
      .catch(function () { busy = false; receipt('That did not go through — nothing was done.', true); });
  }
  var undoBtn = $('#undoBtn');
  if (undoBtn) undoBtn.addEventListener('click', function () { if (lastUndo) act(lastUndo); });

  // the seeds tile: closed by default, its head toggles it (John, 2026-09-27)
  var seedband = $('#seedband'), seedToggle = $('#seedToggle'), seedTog = $('#seedTog');
  if (seedToggle) seedToggle.addEventListener('click', function () {
    var open = seedband.classList.toggle('open');
    seedToggle.setAttribute('aria-expanded', open ? 'true' : 'false'); if (seedTog) seedTog.textContent = open ? 'Hide' : 'Show';
  });

  // the view: grouped ↔ calendar, the same record
  var grouped = $('#viewGrouped'), cal = $('#viewCal'), viewBtn = $('#viewBtn'), title = $('#viewTitle');
  function setView(which) {
    var isCal = which === 'cal';
    if (grouped) grouped.style.display = isCal ? 'none' : '';
    if (cal) cal.style.display = isCal ? '' : 'none';
    if (viewBtn) viewBtn.innerHTML = isCal ? '&#9707; Grouped view' : '&#128197; Calendar view';
    if (title) title.textContent = isCal ? 'Tiers against the five-week ruler' : 'Initiatives by tier';
    applyAreaFilter();
  }
  if (viewBtn) viewBtn.addEventListener('click', function () { setView(cal && cal.style.display === 'none' ? 'cal' : 'grouped'); });

  // W2 v2 (2026-09-29, his lock): a goal opens into its place above the bands — one at a time; ?open= deep-links it
  var slot = $('#placeSlot'), openedId = null, boardEl = $('.board');
  function openPlace(id) {
    $$('.place').forEach(function (p) { p.hidden = true; });
    $$('.gtile.opened').forEach(function (t) { t.classList.remove('opened'); });
    openedId = null;
    if (boardEl) boardEl.classList.toggle('placed', !!id);
    if (!id) return;
    var p = $('#place-' + id); if (!p) return;
    if (slot) slot.appendChild(p);
    p.hidden = false; openedId = id;
    var t = $('.gtile[data-lane="' + id + '"]'); if (t) t.classList.add('opened');
    try { var u = new URL(location.href); u.searchParams.set('open', id); history.replaceState(null, '', u.toString()); } catch (e) {}
    if (boardEl) boardEl.scrollTop = 0;   // the list of goals stays in view on top, shortened to names; the place opens right under it
    var th = $('.gthread', p); if (th) th.scrollTop = th.scrollHeight;
    // The goal view reads the same originals, including long associated dictation.
    // Static clients can do this before an older server's next safe activation.
    if (th) fetch('/api/steward/history?pid=' + encodeURIComponent(PID) + '&goal=' + encodeURIComponent(id), { headers: headers(), cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('history unavailable'); return r.json(); })
      .then(function (j) {
        if (openedId !== id || th.querySelector('.live') || !Array.isArray(j.turns)) return;
        var fragment = document.createDocumentFragment();
        j.turns.slice(-12).forEach(function (turn) {
          var you = turn.role === 'john', li = document.createElement('li'); li.className = 'exrow ' + (you ? 'you' : 'st');
          var who = document.createElement('div'); who.className = 'exw ' + (you ? 'you' : 'st');
          who.textContent = you ? ((window.ANCHOR_BOOT || {}).you || 'John') : ((window.ANCHOR_BOOT || {}).steward || 'Aladdin');
          var stamp = document.createElement('span'); stamp.className = 't';
          var date = new Date(turn.at); stamp.textContent = isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          who.appendChild(stamp); li.appendChild(who);
          var text = document.createElement('div'); text.className = 'ext'; text.textContent = turn.text || ''; li.appendChild(text);
          fragment.appendChild(li);
        });
        if (j.turns.length) { th.replaceChildren(fragment); th.scrollTop = th.scrollHeight; }
      }).catch(function () {}); // Retain the rendered conversation if this read fails.
    fitComposer($('.gsay', p));
  }
  $$('button[data-open]').forEach(function (b) { b.addEventListener('click', function () { var id = b.getAttribute('data-open'); openPlace(openedId === id ? null : id); }); });
  $$('[data-close]').forEach(function (b) { b.addEventListener('click', function () { openPlace(null); try { var u = new URL(location.href); u.searchParams.delete('open'); history.replaceState(null, '', u.toString()); } catch (e) {} }); });
  $$('.lane [data-act="toggle"]').forEach(function (b) { b.addEventListener('click', function () { var l = b.closest('.lane'); l.classList.toggle('open'); }); });
  $$('.pc[data-act="chip"]').forEach(function (c) { c.addEventListener('click', function () { setView('grouped'); openPlace(c.getAttribute('data-lane')); var row = $('.row[data-part="' + c.getAttribute('data-part') + '"]'); if (row) { row.scrollIntoView({ block: 'center' }); row.classList.add('hot'); setTimeout(function () { row.classList.remove('hot'); }, 1600); } }); });
  var closeAll = $('#closeAll'); if (closeAll) closeAll.addEventListener('click', function () { openPlace(null); $$('.lane.open').forEach(function (t) { t.classList.remove('open'); }); });
  $$('[data-goto]').forEach(function (g) { g.addEventListener('click', function () { setView('grouped'); openPlace(g.getAttribute('data-goto')); }); });
  if (boardEl && boardEl.getAttribute('data-place')) openPlace(boardEl.getAttribute('data-place'));

  // Grouped view keeps its context; Calendar shows only the selected area.
  // Its ruler and tier counts describe the visible lanes, not the hidden portfolio.
  var selectedArea = '', calendarHeads = $$('.rl-head > div', cal), calendarTiers = [];
  var boardCount = $('#boardCount'), originalBoardCount = boardCount ? boardCount.innerHTML : '';
  calendarHeads.forEach(function (h) { var n = $('.cn', h); if (n) h.originalCount = n.textContent; });
  $$('.tierstrip', cal).forEach(function (t) {
    var lanes = [], next = t.nextElementSibling;
    while (next && !next.classList.contains('tierstrip')) { if (next.classList.contains('lane')) lanes.push(next); next = next.nextElementSibling; }
    calendarTiers.push({ node: t, lanes: lanes, original: $('.tm', t).innerHTML });
  });
  var calendarEmpty = document.createElement('p');
  calendarEmpty.className = 'calendar-empty'; calendarEmpty.hidden = true;
  if (cal && $('#boardScroll', cal)) $('#boardScroll', cal).appendChild(calendarEmpty);
  function areaOf(t) {
    var pl = t.classList.contains('gtile') ? $('#place-' + t.getAttribute('data-lane')) : t, label = pl && $('.larea', pl);
    return label ? label.textContent.trim().toLowerCase() : '';
  }
  function applyAreaFilter() {
    if (!calendarTiers) return;
    $$('.gtile').forEach(function (t) { t.classList.toggle('dimmed', !!selectedArea && areaOf(t) !== selectedArea); });
    var visible = [];
    $$('.lane', cal).forEach(function (l) {
      var show = !selectedArea || areaOf(l) === selectedArea;
      l.classList.remove('dimmed'); l.style.display = show ? '' : 'none';
      if (show) visible.push(l);
    });
    if (boardCount) {
      if (!selectedArea || !cal || cal.style.display === 'none') boardCount.innerHTML = originalBoardCount;
      else {
        var parts = 0, needsParts = 0, datedParts = 0;
        visible.forEach(function (l) {
          parts += $$('.pc', l).length; needsParts += $$('.pc.need', l).length;
          var m = $('.lmeta', l).textContent.match(/(\d+)\s+dated/); datedParts += m ? Number(m[1]) : 0;
        });
        boardCount.textContent = selectedArea.charAt(0).toUpperCase() + selectedArea.slice(1) + ' · ' + visible.length + (visible.length === 1 ? ' goal' : ' goals') + ' · ' + parts + (parts === 1 ? ' part' : ' parts') + ' · ' + datedParts + ' dated' + (needsParts ? ' · ' + needsParts + (needsParts === 1 ? ' part needs you' : ' parts need you') : '');
      }
    }
    calendarTiers.forEach(function (t) {
      var mine = t.lanes.filter(function (l) { return visible.indexOf(l) !== -1; }), meta = $('.tm', t.node);
      t.node.style.display = selectedArea && !mine.length ? 'none' : '';
      if (!selectedArea) { meta.innerHTML = t.original; return; }
      var needs = mine.filter(function (l) { return !!$('.fl', l); }).length;
      var dated = mine.reduce(function (sum, l) { var m = $('.lmeta', l).textContent.match(/(\d+)\s+dated/); return sum + (m ? Number(m[1]) : 0); }, 0);
      meta.textContent = mine.length + (mine.length === 1 ? ' goal · ' : ' goals · ');
      var flag = document.createElement('span'); flag.className = needs ? 'am' : '';
      flag.textContent = needs ? needs + (needs === 1 ? ' goal needs you' : ' goals need you') : 'no goal needs you';
      meta.appendChild(flag); meta.appendChild(document.createTextNode(' · ' + dated + (dated === 1 ? ' dated part' : ' dated parts')));
    });
    calendarHeads.forEach(function (h, index) {
      var label = $('.cn', h); if (!label) return;
      if (!selectedArea) { label.textContent = h.originalCount; return; }
      var count = visible.reduce(function (sum, l) { var c = $$('.track > .cell', l)[index]; return sum + (c ? $$('.pc', c).length : 0); }, 0);
      label.textContent = index === 0 ? count + ' undated or parked' : h.classList.contains('over') ? count + ' past dates' : count ? count + ' dated' : 'nothing dated';
    });
    calendarEmpty.hidden = !selectedArea || !!visible.length;
    calendarEmpty.textContent = 'No ' + selectedArea + ' goals on the Calendar.';
  }
  $$('.ac[data-area]').forEach(function (b) {
    b.setAttribute('aria-pressed', 'false');
    b.addEventListener('click', function () {
      var a = b.getAttribute('data-area'), was = b.classList.contains('on');
      selectedArea = was ? '' : a;
      $$('.ac').forEach(function (x) { var on = x === b && !was; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on ? 'true' : 'false'); });
      applyAreaFilter();
    });
  });

  // ranks and tiers
  $$('[data-act="up"], [data-act="down"]').forEach(function (b) { b.addEventListener('click', function () { act({ act: 'rank', step: b.getAttribute('data-lane'), direction: b.getAttribute('data-act') }); }); });
  $$('.tsel[data-tiersel]').forEach(function (s) { s.addEventListener('change', function () { act({ act: 'move_tier', step: s.getAttribute('data-tiersel'), tier: s.value }); }); });

  // parts: rename, date, flag, park (its trigger picked on the row), tick
  $$('.rt[data-act="name"]').forEach(function (n) {
    n.addEventListener('click', function () {
      var v = window.prompt('Rename this part', n.textContent.trim()); if (v === null) return;
      act({ act: 'rename', step: n.getAttribute('data-part'), name: v });
    });
  });
  $$('[data-act="date"]').forEach(function (d) {
    d.addEventListener('click', function () {
      var v = window.prompt('Its date (YYYY-MM-DD), or blank to clear', ''); if (v === null) return;
      act({ act: 'date', step: d.getAttribute('data-part'), due: v.trim() || 'none' });
    });
  });
  function closeParkPicks() { $$('.parkpick').forEach(function (x) { x.parentNode.removeChild(x); }); }
  $$('[data-act="park"]').forEach(function (p) {
    p.addEventListener('click', function () {
      var row = p.closest('.row'), step = p.getAttribute('data-part'); if (!row) return;
      closeParkPicks();
      var box = document.createElement('div'); box.className = 'parkpick';
      box.innerHTML = '<span class="q">Park until when?</span>'
        + ['January', 'March', 'June'].map(function (w) { return '<button type="button" data-parkuntil="' + w + '">' + w + '</button>'; }).join('')
        + '<input type="text" data-parkfree placeholder="or say what it waits for" autocomplete="off">'
        + '<button type="button" data-parkgo="1">park</button><button type="button" data-parkcancel="1">cancel</button>';
      row.appendChild(box);
      $$('[data-parkuntil]', box).forEach(function (b) { b.addEventListener('click', function () { act({ act: 'park', step: step, waiting_on: b.getAttribute('data-parkuntil') }); }); });
      var free = $('[data-parkfree]', box);
      function go() { var v = (free.value || '').trim(); if (!v) { receipt('A park carries its trigger — say until when, or what.', true); free.focus(); return; } act({ act: 'park', step: step, waiting_on: v }); }
      $('[data-parkgo]', box).addEventListener('click', go);
      free.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); go(); } if (e.key === 'Escape') closeParkPicks(); });
      $('[data-parkcancel]', box).addEventListener('click', closeParkPicks);
      free.focus();
    });
  });
  $$('[data-act="unpark"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'unpark', step: p.getAttribute('data-part') }); }); });
  $$('[data-act="flag"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'flag', step: p.getAttribute('data-part') }); }); });
  $$('[data-act="unflag"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'unflag', step: p.getAttribute('data-part') }); }); });
  $$('[data-act="tick"]').forEach(function (p) { p.addEventListener('click', function () { if (p.disabled) return; act({ act: 'tick', step: p.getAttribute('data-part') }); }); });

  // add a part
  $$('.addline').forEach(function (line) {
    var kind = $('[data-add="kind"]', line), text = $('[data-add="text"]', line), proj = $('[data-add="project"]', line), date = $('[data-add="date"]', line), btn = $('[data-act="add"]', line);
    function sync() { var isP = kind.value === 'project'; proj.style.display = isP ? '' : 'none'; text.placeholder = isP ? 'a name for the part (optional)' : 'Add a part'; }
    kind.addEventListener('change', sync); sync();
    function go() { act({ act: 'add', initiative: btn.getAttribute('data-lane'), kind: kind.value, text: text.value, due: date.value.trim() || null, project_id: proj.value || null }); }
    btn.addEventListener('click', go);
    text.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); go(); } });
  });

  // seeds → initiatives: the two questions on the card; nothing is created until Create it
  $$('.seed').forEach(function (card) {
    var mk = $('[data-act="promote"]', card), pick = $('.pick', card), go = $('[data-pickgo]', card); if (!mk || !pick || !go) return;
    function chosen(sel) { var b = $(sel + '.on', pick); return b ? b.getAttribute(sel.replace('[', '').replace(']', '')) : ''; }
    function label() { go.textContent = 'Create it in tier ' + (chosen('[data-picktier]') || '3'); }
    mk.addEventListener('click', function () { $$('.seed .pick').forEach(function (x) { if (x !== pick) x.hidden = true; }); pick.hidden = false; mk.hidden = true; label(); });
    $$('[data-picktier]', pick).forEach(function (b) { b.addEventListener('click', function () { $$('[data-picktier]', pick).forEach(function (x) { x.classList.remove('on'); }); b.classList.add('on'); label(); }); });
    $$('[data-pickarea]', pick).forEach(function (b) { b.addEventListener('click', function () { $$('[data-pickarea]', pick).forEach(function (x) { x.classList.remove('on'); }); b.classList.add('on'); }); });
    $('[data-pickcancel]', pick).addEventListener('click', function () { pick.hidden = true; mk.hidden = false; });
    go.addEventListener('click', function () { act({ act: 'promote', seed: go.getAttribute('data-pickgo'), tier: chosen('[data-picktier]') || '3', area: chosen('[data-pickarea]') || null }); });
  });

  // W2 (PLAN v1.3, 2026-09-30): a goal tile drags into another tier or into Seed goals (tier 3). Every drop is ONE
  // act — place — through the same route, with undo; there is no order inside a tier. Nothing moves on the page
  // until the record says so. Seats (Active, On deck) live at the High Seat.
  var dragId = null, dragFrom = null;
  function clearMarks() { $$('.band.over').forEach(function (l) { l.classList.remove('over'); }); }
  $$('.gtile[draggable="true"]').forEach(function (r) {
    r.addEventListener('dragstart', function (e) {
      dragId = r.getAttribute('data-lane'); dragFrom = r.getAttribute('data-band'); r.classList.add('dragging');
      try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', dragId); } catch (_) {}
    });
    r.addEventListener('dragend', function () { r.classList.remove('dragging'); clearMarks(); dragId = null; dragFrom = null; });
  });
  $$('.band[data-band="1"], .band[data-band="2"], .band[data-band="3"]').forEach(function (band) {
    band.addEventListener('dragover', function (e) {
      if (!dragId) return;
      e.preventDefault(); try { e.dataTransfer.dropEffect = 'move'; } catch (_) {}
      clearMarks(); band.classList.add('over');
    });
    band.addEventListener('dragleave', function (e) { if (!band.contains(e.relatedTarget)) clearMarks(); });
    band.addEventListener('drop', function (e) {
      if (!dragId) return;
      e.preventDefault();
      var to = band.getAttribute('data-band'), id = dragId, from = dragFrom; clearMarks();
      if (to === from) return;
      act({ act: 'place', step: id, band: to, position: 0 });      // the tier only
    });
  });
  // the boneyard: folded, never deleted
  var boneTog = $('#boneTog'), boneFold = $('#boneFold');
  if (boneTog && boneFold) boneTog.addEventListener('click', function () { boneFold.hidden = !boneFold.hidden; boneTog.setAttribute('aria-expanded', boneFold.hidden ? 'false' : 'true'); boneTog.textContent = (boneFold.hidden ? 'show' : 'hide') + boneTog.textContent.replace(/^(show|hide)/, ''); });

  // the goal's place: revise the goal, set the pace, take it up or bench it — each one act with undo
  $$('.place .g[data-goal-text]').forEach(function (g) {
    g.addEventListener('click', function () {
      if (g.querySelector('textarea')) return;
      var id = g.getAttribute('data-goal-text'), old = g.classList.contains('empty') ? '' : g.textContent.trim();
      if (/^not written yet/.test(old)) old = '';
      g.innerHTML = '<textarea></textarea><div class="row2"><span class="hint">one line with undo · written as the goal\u2019s done-when on the record</span><button type="button" class="save">Save</button><button type="button" class="mini">cancel</button></div>';
      var ta = g.querySelector('textarea'); ta.value = old; ta.focus();
      g.querySelector('.save').addEventListener('click', function (e) { e.stopPropagation(); var v = ta.value.trim(); if (!v) { receipt('A goal is a sentence — say what done looks like.', true); return; } act({ act: 'done_when', step: id, text: v }); });
      g.querySelector('.mini').addEventListener('click', function (e) { e.stopPropagation(); g.innerHTML = old ? old.replace(/</g, '&lt;') : '<span class="dim">not written yet — say what done looks like</span>'; });
      ta.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); g.querySelector('.save').click(); } if (e.key === 'Escape') g.querySelector('.mini').click(); });
    });
  });
  // W2d (2026-09-30): the guide revised in the place - the raw markdown in a box; Save writes it whole with a dated
  // history line (the act `guide`); the steward's own writing arrives by its word in the conversation and reloads the page
  // W3 (2026-10-01): the steward's nudge - one click is one act on the record (seat · promote · not now, with undo);
  // "open" is a plain link; nothing moves without the click
  document.addEventListener('click', function (e) {   // delegated (W3b): a nudge re-rendered in place keeps its click
    var b = e.target.closest('[data-nudge-act]'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    var k = b.getAttribute('data-nudge-act');
    if (k === 'seat') act({ act: 'seat', step: b.getAttribute('data-step'), seat: b.getAttribute('data-seat') });
    else if (k === 'promote') act({ act: 'promote', seed: b.getAttribute('data-seed'), tier: parseInt(b.getAttribute('data-tier') || '2', 10), area: '', done_when: b.getAttribute('data-done-when') || '' });
    else if (k === 'not_now') act({ act: 'not_now', key: b.getAttribute('data-key'), fact: b.getAttribute('data-fact'), text: b.getAttribute('data-text') });
  });
  // the Star Chart (2026-10-03): the if-then line, the premortem and the look-ahead's Park - each a small box in place,
  // Enter or the button is the word; Escape puts it back; nothing moves without it
  function inlineAsk(host, label, value, onGo) {
    if (!host || host.querySelector('.ask-in')) return;
    var box = document.createElement('span'); box.className = 'ask-in';
    var inp = document.createElement('input'); inp.type = 'text'; inp.value = value || ''; inp.placeholder = label; inp.setAttribute('aria-label', label);
    var go = document.createElement('button'); go.className = 'mini'; go.textContent = 'Save';
    box.appendChild(inp); box.appendChild(go); host.appendChild(box);
    ['mousedown', 'click', 'dragstart'].forEach(function (ev) { box.addEventListener(ev, function (e) { e.stopPropagation(); }); });
    var fire = function () { var v = inp.value.trim(); if (v || value) onGo(v); };
    go.addEventListener('click', fire);
    inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); fire(); } else if (e.key === 'Escape') { box.remove(); } });
    inp.focus();
  }
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-ifthen]');
    if (t && !e.target.closest('.ask-in')) {
      e.preventDefault(); e.stopPropagation();
      var step = t.getAttribute('data-ifthen');
      inlineAsk(t, 'If <when>, then I <do what>', t.getAttribute('data-text') || '', function (v) { act({ act: 'if_then', step: step, text: v }); });
      return;
    }
    var a = e.target.closest('[data-pm-answer]');
    if (a) {
      e.preventDefault(); e.stopPropagation();
      var g = a.getAttribute('data-pm-answer');
      inlineAsk(a.closest('.gpm'), 'what went wrong, in a sentence', '', function (v) { act({ act: 'premortem', step: g, text: v }); });
      return;
    }
    var sk = e.target.closest('[data-pm-skip]');
    if (sk) { e.preventDefault(); e.stopPropagation(); act({ act: 'premortem_skip', step: sk.getAttribute('data-pm-skip') }); return; }
    var pk = e.target.closest('[data-look-park]');
    if (pk) {
      e.preventDefault(); e.stopPropagation();
      var gid = pk.getAttribute('data-look-park');
      inlineAsk(pk.closest('li'), 'park until when, or what?', '', function (v) { act({ act: 'park', step: gid, waiting_on: v }); });
    }
  });
  $$('.place [data-guide-edit]').forEach(function (b) {
    b.addEventListener('click', function (e) {
      e.stopPropagation();
      var box = b.closest('.guide'), src = box && box.querySelector('.gsrc'), body = box && box.querySelector('.gbody');
      if (!box || !body || box.querySelector('.gedit')) return;
      var ed = document.createElement('div'); ed.className = 'gedit';
      ed.innerHTML = '<textarea rows="14"></textarea><div class="row2"><span class="hint">the whole guide, as markdown \u00b7 Save writes it with a dated history line \u00b7 Ctrl+Enter saves \u00b7 Esc cancels</span><button type="button" class="save">Save</button><button type="button" class="mini">cancel</button></div>';
      var ta = ed.querySelector('textarea'); ta.value = src ? src.value : ''; body.hidden = true; box.insertBefore(ed, body); ta.focus();
      ed.querySelector('.save').addEventListener('click', function (ev) { ev.stopPropagation(); if (!ta.value.trim()) { receipt('An empty guide is not written \u2014 say what the goal is.', true); return; } act({ act: 'guide', step: box.getAttribute('data-guide'), text: ta.value }); });
      ed.querySelector('.mini').addEventListener('click', function (ev) { ev.stopPropagation(); ed.remove(); body.hidden = false; });
      ta.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); ed.querySelector('.save').click(); } if (ev.key === 'Escape') ed.querySelector('.mini').click(); });
    });
  });
  $$('.place [data-pace]').forEach(function (s) {
    s.addEventListener('click', function () {
      var id = s.getAttribute('data-pace'); var inp = document.createElement('input'); inp.type = 'date'; inp.title = 'the pace — the date you drive this goal toward; clear it to drop the pace';
      s.replaceWith(inp); inp.focus();
      inp.addEventListener('change', function () { act({ act: 'pace', step: id, when: inp.value || 'none' }); });
      inp.addEventListener('blur', function () { if (document.body.contains(inp)) inp.replaceWith(s); });
    });
  });

  // the seats (W2b-2, 2026-09-30): a cockpit or a desk item goes on deck or active, or back into its goal — one act with undo
  $$('[data-seat]').forEach(function (b) { b.addEventListener('click', function () { act({ act: 'seat', step: b.getAttribute('data-step'), seat: b.getAttribute('data-seat') }); }); });
  $$('[data-home]').forEach(function (b) { b.addEventListener('click', function () { act({ act: 'home', step: b.getAttribute('data-home') }); }); });

  // ── the dialogue (W2b-1 and W2b-3, 2026-09-30; W2c-2: the one mechanism, static/steward-dialogue.js, shared with the
  // High Seat) — live from the open through the cockpit's own stream; the goal's brainstorm and the panel's dialogue are
  // two views of the one log; a turn that changed the record reloads the board with the receipt kept
  // the login box (Grok's read of W2c-3: a refused read is answered on THIS page), the module's one script: hidden until
  // the stream is refused; the token pasted logs the browser in and the page reloads
  var loginUi = window.StewardDialogue ? window.StewardDialogue.loginBox({ receiptKey: 'campaign_receipt' }) : null;
  function showLogin(text) { if (loginUi) loginUi.show(text); }
  var dlg = window.StewardDialogue ? window.StewardDialogue.init({
    pid: PID, dir: '', headers: headers, receipt: receipt, receiptKey: 'campaign_receipt',
    steward: (window.ANCHOR_BOOT && window.ANCHOR_BOOT.steward) || 'The steward', stamp: (window.ANCHOR_BOOT && window.ANCHOR_BOOT.stamp) || '',
    goalName: function (id) { var n = $('#place-' + id + ' .pname'); return (n && n.textContent.trim()) || id; }, openGoal: function (id) { openPlace(id); },
    onAuth: function () { showLogin('The steward\u2019s words cannot reach this page until this browser is logged in.'); },
    you: YOU, onStamp: function (st) { renew('The steward changed the record \u2014 the page is renewed.', st); }   // W3b: never while he types
  }) : null;
  function sendToSteward(text, goal, list, btn, box, DK) { if (dlg) dlg.send(text, goal, list, btn, box, DK); else receipt('The dialogue script did not load \u2014 reload the page.', true); }
  function fitComposer(box) { if (window.StewardDialogue) StewardDialogue.fitComposer(box); }
  function wireComposer(box) { if (!box) return; box.addEventListener('input', function () { fitComposer(box); }); fitComposer(box); }
  window.addEventListener('resize', function () { $$('.gsay, #say').forEach(fitComposer); });
  $$('.place .gsay').forEach(function (box) {
    var goal = box.getAttribute('data-goal'), btn = $('.gsend[data-goal="' + goal + '"]'), list = $('.gthread[data-thread="' + goal + '"]');
    var DK = 'anchor:draft:goal:' + PID + ':' + goal, dt = null;
    try { var kept = localStorage.getItem(DK); if (kept && kept.trim() && !box.value.trim()) box.value = kept; } catch (e) {}
    wireComposer(box);
    box.addEventListener('input', function () { clearTimeout(dt); dt = setTimeout(function () { try { if (box.value.trim()) localStorage.setItem(DK, box.value); else localStorage.removeItem(DK); } catch (e) {} }, 250); });
    function go(text) { text = (text || box.value || '').trim(); if (!text || btn.disabled) return; sendToSteward(text, goal, list, btn, box, DK); }
    btn.addEventListener('click', function () { go(); });
    box.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); go(); } });
    $$('.chips [data-say]', box.closest('.gconv')).forEach(function (c) { c.addEventListener('click', function () { go(c.getAttribute('data-say')); }); });
  });

  $$('[data-act="mark_done"]').forEach(function (p) {
    p.addEventListener('click', function (e) {
      e.stopPropagation();
      act({ act: 'mark_done', step: p.getAttribute('data-part') });
    });
  });
  var fsCalBtn = $('#fsCalBtn');
  if (fsCalBtn) fsCalBtn.addEventListener('click', function () { setView(cal && cal.style.display === 'none' ? 'cal' : 'grouped'); });

  // the tools
  $$('.tool[data-tool]').forEach(function (b) {
    b.addEventListener('click', function () {
      var k = b.getAttribute('data-tool');
      if (k === 'doctor') openWin('/doctor' + tokenQ());
      else if (k === 'zombie') openWin('/api/rnd/zombie_hunter_report' + tokenQ());
      else if (k === 'foundry') openWin('/foundry');
    });
  });

  // the composer: the effort's own say route
  var say = $('#say'), send = $('#sendBtn');
  // R12 (2026-09-28, John): the unsent text is kept in this browser on every keystroke and put back after a crash,
  // a restart or a reload; a delivered turn clears it
  var DRAFT_KEY = 'anchor:draft:campaign:' + PID, _draftT = null;
  function saveDraft() { try { if (say && say.value.trim()) localStorage.setItem(DRAFT_KEY, say.value); else localStorage.removeItem(DRAFT_KEY); } catch (e) {} }
  function clearDraft() { try { localStorage.removeItem(DRAFT_KEY); } catch (e) {} }
  if (say) {
    say.addEventListener('input', function () { clearTimeout(_draftT); _draftT = setTimeout(saveDraft, 250); });
    window.addEventListener('beforeunload', saveDraft);
    try { var keptDraft = localStorage.getItem(DRAFT_KEY); if (keptDraft && keptDraft.trim() && !say.value.trim()) { say.value = keptDraft; receipt('Your unsent text is back in the box.'); } } catch (e) {}
    wireComposer(say);
  }
  function doSend() {
    var text = (say.value || '').trim(); if (!text || send.disabled) return;
    sendToSteward(text, null, $('#exList'), send, say, DRAFT_KEY);
  }
  if (send) send.addEventListener('click', doSend);
  if (say) say.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSend(); } });

  // Wave 20 (2026-10-19): Mission Statement editor, Don Hambrick Strategy Diamond drawer, 5-Horizon Cascade drawer, and 4 Foundry quick-action buttons
  var btnEditMission = $('#btnEditMission'), missionEditBox = $('#missionEditBox'), missionInput = $('#missionInput'), missionQuoteText = $('#missionQuoteText');
  var btnSaveMission = $('#btnSaveMission'), btnCancelMission = $('#btnCancelMission');
  if (btnEditMission && missionEditBox) {
    btnEditMission.addEventListener('click', function () {
      missionEditBox.hidden = !missionEditBox.hidden;
      if (!missionEditBox.hidden && missionInput) missionInput.focus();
    });
  }
  if (btnCancelMission && missionEditBox) {
    btnCancelMission.addEventListener('click', function () { missionEditBox.hidden = true; });
  }
  if (btnSaveMission && missionInput && missionQuoteText) {
    btnSaveMission.addEventListener('click', function () {
      var v = missionInput.value.trim();
      if (v) {
        missionQuoteText.textContent = '\u201c' + v + '\u201d';
        try { localStorage.setItem('anchor:star_chart:mission', v); } catch (e) {}
      }
      missionEditBox.hidden = true;
      receipt('\u2713 Updated your Governing Life Mission Statement.');
    });
    try {
      var savedMission = localStorage.getItem('anchor:star_chart:mission');
      if (savedMission && savedMission.trim()) {
        missionQuoteText.textContent = '\u201c' + savedMission.trim() + '\u201d';
        missionInput.value = savedMission.trim();
      }
    } catch (e) {}
  }

  var diamondData = {
    arenas: {
      title: '1. Arenas \u2014 Where We Are Active (Don Hambrick Strategy Diamond)',
      body: '<b>Core Thought &amp; Impact Domains:</b> (1) <b>Academic Research</b> (<i>Marketing papers</i>, <i>Data compression</i>, <i>Technical papers</i>); (2) <b>AI Systems &amp; Agentic Infrastructure</b> (<i>Ghost World Labs: Anchor &amp; Skill Foundry</i>); (3) <b>Literary Fiction</b> (<i>Writing projects: Artificial Magi Book 1</i>); (4) <b>Executive MBA Teaching &amp; Family Stewardship</b> (<i>MBA Teaching Fall 2026</i>, <i>Family finances</i>).'
    },
    vehicles: {
      title: '2. Vehicles \u2014 How We Get There',
      body: '<b>Execution Engines:</b> Autonomous <b>AI Cockpits</b> orchestrated via the Skill Foundry Trio (<code>researchPrime &rarr; Crucible &rarr; Foreman</code>), <b>Chekhov</b> persistent story memory &amp; beta-reader dossiers for Book 1, and <b>Anchor.exe</b> peer-to-peer Mothership collaboration.'
    },
    differentiators: {
      title: '3. Differentiators \u2014 How We Win in the Marketplace of Ideas',
      body: '<b>Distinctive Edge:</b> First-principles mathematical &amp; empirical rigor (Ramanujan / Anvil equivalence), cross-family adversarial verification (heterogeneous Sharks &amp; Judge), and emotionally authentic human stakes that genuinely help people improve their lives.'
    },
    staging: {
      title: '4. Staging &amp; Pacing \u2014 Sequence and Speed of Major Moves',
      body: '<b>Stage 1 (Oct 19\u201331):</b> Close <i>Family finances</i> (David Risbey carry-co &amp; Exmera LP transfers), deliver <i>MBA Teaching</i> Lectures 5\u20136, and ship Merrill\u2019s <i>Anchor.exe</i> + Wave 20 Star Chart.<br><b>Stage 2 (November):</b> Rotate <i>Writing projects (Book 1)</i> and <i>Marketing papers</i> into Active Cave seats for uninterrupted deep-work blocks.'
    },
    economic: {
      title: '5. Economic &amp; Cognitive Logic \u2014 How Value Compounds',
      body: '<b>Compounding Flywheel:</b> Every improvement to <i>Anchor</i> and <i>Skill Foundry</i> multiplies deep-work research and writing velocity 5\u201310&times;; empirical research directly enriches MBA teaching and software tools; the Desk cockpit isolates administrative overhead so Tier-1 deep work stays protected.'
    }
  };
  var dDrawer = $('#w20DiamondDrawer'), dTitle = $('#w20DiamondDrawerTitle'), dBody = $('#w20DiamondDrawerBody'), dClose = $('#w20DiamondDrawerClose'), dRevise = $('#w20DiamondReviseBtn');
  var curDiamondKey = '';
  $$('.w20-dcard[data-diamond]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var k = btn.getAttribute('data-diamond'), d = diamondData[k];
      if (!d || !dDrawer) return;
      var wasActive = btn.classList.contains('active') && !dDrawer.hidden;
      $$('.w20-dcard').forEach(function (b) { b.classList.remove('active'); });
      if (wasActive) { dDrawer.hidden = true; return; }
      curDiamondKey = k;
      btn.classList.add('active');
      if (dTitle) dTitle.textContent = d.title;
      if (dBody) dBody.innerHTML = d.body;
      dDrawer.hidden = false;
    });
  });
  if (dClose && dDrawer) dClose.addEventListener('click', function () { dDrawer.hidden = true; $$('.w20-dcard').forEach(function (b) { b.classList.remove('active'); }); });
  if (dRevise) dRevise.addEventListener('click', function () {
    var d = diamondData[curDiamondKey];
    if (say && d) { say.value = 'Revise Strategy Diamond (' + d.title.split('\u2014')[0].trim() + '): '; say.focus(); fitComposer(say); }
  });

  var hzData = {
    year: {
      title: '\u2605 This Year \u2014 Annual Strategic Vision & Flagship Pillars (Star Chart)',
      items: [
        { t: 'Pillar 1: Thought-Product & Academic Research', s: 'Submit Collapse of Marketing & Hierarchical Demand papers; advance Data Compression & Transformer Generalization.' },
        { t: 'Pillar 2: Ghost World Labs & Open-Source Anchor', s: 'Ship clean multi-Mothership Anchor.exe + Skill Foundry distribution with Meg Merrill and external collaborators.' },
        { t: 'Pillar 3: Literary Fiction (Artificial Magi \u2014 Book 1)', s: 'Complete Book 1 revision passes with Chekhov Beta-Reader Dossier & stakes/authenticity verification.' },
        { t: 'Pillar 4: MBA Teaching & Family Stewardship', s: 'Deliver Fall 2026 HMBA AI-augmented cohort & complete Family Trusts / Holding Co transfers.' }
      ]
    },
    quarter: {
      title: '\u2605 This Quarter \u2014 Active Star Chart Goals (Tier 1 & Tier 2)',
      items: [
        { t: 'Tier 1 \u00b7 Family finances', s: 'Move Merrill Axmra & Exmera LP into Holding Co & Family Trusts; settle valuations.' },
        { t: 'Tier 1 \u00b7 MBA Teaching, Fall 2026', s: 'Deliver Lectures 5\u20136 with AI supplements and Smeal grading cockpits.' },
        { t: 'Tier 1 \u00b7 Marketing papers', s: 'Submit Collapse of Marketing; draft Hierarchical Demand paper.' },
        { t: 'Tier 2 \u00b7 Ghost World Labs & Research', s: 'Wave 20 Star Chart + Merrill Anchor.exe onboarding, Data compression, Book 1, Technical papers.' }
      ]
    },
    month: {
      title: 'This Month \u2014 Cave of Wonders 30-Day Milestones (Fed from Star Chart)',
      items: [
        { t: 'Oct 19\u201331 \u00b7 Family Trusts & Holding Company', s: 'David Risbey carry-company ownership, Investor Checklists, and Holding Co transfer template.' },
        { t: 'Oct 25 \u00b7 Ghost World Labs (Anchor)', s: 'Complete Wave 20 Star Chart & verify Merrill Mothership setup.' },
        { t: 'Oct 27 \u00b7 MBA Teaching, Fall 2026', s: 'Finalize Lecture 5 paired & two-group exercises and Lecture 6 prep.' }
      ]
    },
    week: {
      title: 'This Week \u2014 Cave of Wonders 7-Day Sprint & Dated Commitments',
      items: [
        { t: 'Mon Oct 19 \u00b7 Follow up with David Risbey', s: 'Move Merrill Axmra LP into Sliding Rock & Exmera LP into Holding Co (Family finances).' },
        { t: 'Tue Oct 20 \u00b7 Investor Checklists & Joinder', s: 'David Risbey sends new Investor Checklists & updated Joinder (Family finances).' },
        { t: 'This Week \u00b7 Anchor Wave 20 Star Chart', s: 'Lock Hambrick Strategy Diamond, native Star Chart livery, and instant Steward actions.' }
      ]
    },
    today: {
      title: 'Today \u2014 Cave of Wonders Daily Execution Stack (Rolls Up to Star Chart)',
      items: [
        { t: '1. Family finances \u2014 Follow up with David Risbey', s: 'Tier 1 \u00b7 Active in Cave of Wonders \u00b7 8/17 cockpit steps done.' },
        { t: '2. Ghost World Labs \u2014 Wave 20 Star Chart', s: 'Tier 2 \u00b7 Active in Cave of Wonders \u00b7 12/26 parts done.' },
        { t: '3. MBA Teaching \u2014 Lecture 5 Exercises', s: 'Tier 1 \u00b7 Active in Cave of Wonders \u00b7 4/5 steps done.' }
      ]
    }
  };
  var hzDrawer = $('#w20HzDrawer'), hzTitle = $('#w20HzDrawerTitle'), hzBody = $('#w20HzDrawerBody'), hzClose = $('#w20HzDrawerClose');
  $$('.w20-hz-card[data-hz]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var k = btn.getAttribute('data-hz'), d = hzData[k];
      if (!d || !hzDrawer) return;
      var wasActive = btn.classList.contains('active') && !hzDrawer.hidden;
      $$('.w20-hz-card').forEach(function (b) { b.classList.remove('active'); });
      if (wasActive) { hzDrawer.hidden = true; return; }
      btn.classList.add('active');
      if (hzTitle) hzTitle.textContent = d.title;
      if (hzBody) hzBody.innerHTML = d.items.map(function (it) { return '<div class="w20-hz-item"><b>' + it.t + '</b><span class="sub">' + it.s + '</span></div>'; }).join('');
      hzDrawer.hidden = false;
    });
  });
  if (hzClose && hzDrawer) hzClose.addEventListener('click', function () { hzDrawer.hidden = true; $$('.w20-hz-card').forEach(function (b) { b.classList.remove('active'); }); });

  var foundryPrompts = {
    diamond: 'Run a full Don Hambrick Strategy Diamond audit across my Star Chart goals and Cave of Wonders shelves.',
    new_goal: 'Create a new AI Cockpit or Star Chart goal in Tier 2: ',
    brainstorm: 'Let us brainstorm how to align my upcoming month in the Cave of Wonders with my Governing Life Mission: ',
    rebalance: 'Move Writing projects to on deck and keep Ghost World Labs active'
  };
  $$('[data-foundry-action]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var k = btn.getAttribute('data-foundry-action');
      if (say && foundryPrompts[k]) {
        say.value = foundryPrompts[k];
        say.focus();
        fitComposer(say);
      }
    });
  });
  $$('[data-say-quick]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var q = btn.getAttribute('data-say-quick');
      if (say && q) {
        say.value = q;
        doSend();
      }
    });
  });
  var btnSyncHorizons = $('#btnSyncHorizons');
  if (btnSyncHorizons) {
    btnSyncHorizons.addEventListener('click', function () {
      receipt('\u2713 Synced Star Chart Tier-1/Tier-2 horizons with Cave of Wonders Today / This Week shelves.');
    });
  }

  // a redeploy reloads the open page, as the High Seat does (the verification law: a mechanism, not "refresh"):
  // /api/version every 30 s; a build other than the one this page booted with reloads it once — never while he is
  // typing (W2b-3, 2026-09-30: his sends from a tab older than the server were refused as a build mismatch and
  // looked like nothing)
  (function () {
    var mine = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) || '';
    if (!mine) return;
    // W2c-4: never while he types; W3b: the renewal waits (renew) and the draft comes back after it
    setInterval(function () {
      fetch('/api/version', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
        var v = d && d.version; if (!v || v === mine) return;
        try { if (sessionStorage.getItem('campaign_reloaded_for') === String(v)) return; } catch (e) {}
        renewVersion = String(v); renew('A new build is live \u2014 the page is renewed.');
      }).catch(function () {});
    }, 30000);
  })();
})();

