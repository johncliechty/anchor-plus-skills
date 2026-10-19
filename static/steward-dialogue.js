/* The steward's dialogue (W2b-1/W2b-3 on the Campaign page, 2026-09-30; W2c-2 the same day for the High Seat too, his
   word: both dialogues "need to engage the steward and then show the dialogue between the user and the steward").
   ONE mechanism for both pages: the page long-polls the cockpit's own event stream (/api/steward/events — the one the
   AI Cockpit uses) from the moment it opens (the cockpit's own soft start: a parked steward with work kept for it
   resumes; a brand-new one is never woken by a mere view); what the steward writes lands as it writes — in the page's
   dialogue and, when the turn was sent from a goal's brainstorm, there too (one log, two views); the steward's state
   (parked · waking · listening · working) stands at the dialogue's head; a turn that changed the record reloads the
   page with the receipt kept; a send from a tab older than the server renews the page with the draft kept. */
(function () {
  'use strict';
  function init(o) {
    var $ = function (s, r) { return (r || document).querySelector(s); };
    var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
    var PID = o.pid || '', DIR = o.dir || '', headers = o.headers, receipt = o.receipt || function () {};
    var STEWARD = o.steward || 'The steward', BOOT_STAMP = o.stamp || '', KEY = o.receiptKey || 'steward_receipt', YOU = o.you || 'You';
    var goalName = o.goalName || function (id) { return id; }, openGoal = o.openGoal || null;
    var live = { seq: 0, polling: false, target: null, goal: null, line: null, epoch: null, skipJohn: '', stopped: false, sent: false };
    function keep(text, bad, undo) { try { sessionStorage.setItem(KEY, JSON.stringify({ text: text, bad: !!bad, undo: undo || null })); } catch (e) {} }
    function mainList() { return $(o.list || '#exList'); }
    function exLi(who, text, cls, goal) {
      var li = document.createElement('li');
      li.className = 'exrow ' + (who === 'you' ? 'you' : (who === 'st' ? 'st' : 'sysl')) + (cls ? ' ' + cls : '');
      li.innerHTML = '<div class="exw ' + (who === 'you' ? 'you' : 'st') + '"><span class="w"></span><span class="t"></span></div><div class="ext"></div>';
      li.querySelector('.w').textContent = who === 'you' ? YOU : (who === 'st' ? STEWARD : '');
      if (goal) {
        var c = document.createElement('button'); c.className = 'gchip'; c.title = 'this goal'; c.textContent = 'about ' + goalName(goal);
        li.querySelector('.exw').insertBefore(c, li.querySelector('.t'));
        c.addEventListener('click', function () { if (openGoal) openGoal(goal); });
      }
      li.querySelector('.ext').textContent = text;
      li._raw = text;
      return li;
    }
    // the steward's words in the cockpit's own markdown (bold, lists, links, paragraphs) once a block is whole (2026-10-02,
    // his word: "I liked the formatting in the actual cockpit because it does it in blocks")
    function md(li) {
      var x = li && li.querySelector('.ext'); if (!x || !window.mdRender || !li.classList.contains('st')) return;
      var raw = li._raw !== undefined ? li._raw : x.textContent; if (!String(raw).trim()) return;
      try { x.textContent = ''; window.mdRender(x, raw); } catch (e) { x.textContent = raw; }
    }
    // 2026-10-07: the dialogue opens at the newest line and follows what arrives (rendering, late layout) until John
    // scrolls up - then it stays where he put it. Only a real scroll changes `_follow`; content growth fires none.
    function follow(el) {
      if (!el || el._followWired) return el;
      el._followWired = true; el._follow = true;
      // any upward move of his stops following; only the very bottom resumes it (a near-bottom band re-armed it)
      var lastTop = el.scrollTop;
      var stick = function () { if (el._follow) { el.scrollTop = el.scrollHeight; lastTop = el.scrollTop; } };
      // only his scrolling changes follow (a layout clamp never re-arms it; a wheel with nothing to scroll never disarms it)
      var userAt = 0, mark = function () { userAt = Date.now(); };
      ['wheel', 'touchstart', 'keydown', 'pointerdown'].forEach(function (k) { el.addEventListener(k, mark, { passive: true }); });
      // content shrinking never re-arms following; reaching the bottom otherwise does; only his upward scroll disarms
      var lastRange = el.scrollHeight - el.clientHeight;   // content minus viewport: shrink or a taller window reduce it
      el.addEventListener('scroll', function () {
        var gap = el.scrollHeight - el.scrollTop - el.clientHeight, his = Date.now() - userAt < 1500,
            range = el.scrollHeight - el.clientHeight, shrank = range < lastRange - 1;
        if (gap < 4 && !shrank) el._follow = true; else if (his && !shrank && el.scrollTop < lastTop - 1) el._follow = false;
        lastTop = el.scrollTop; lastRange = range;
      }, { passive: true });
      el.addEventListener('wheel', function (e) { if (e.deltaY < 0 && el.scrollHeight > el.clientHeight + 1) el._follow = false; }, { passive: true });
      if (window.ResizeObserver) {
        var ro = new ResizeObserver(stick); ro.observe(el);
        Array.prototype.forEach.call(el.children, function (c) { ro.observe(c); });
        if (window.MutationObserver) new MutationObserver(function (muts) {
          muts.forEach(function (m) { Array.prototype.forEach.call(m.addedNodes, function (n) { if (n.nodeType === 1 && n.parentElement === el) ro.observe(n); }); });
          stick();
        }).observe(el, { childList: true, subtree: true, characterData: true });
      }
      return el;
    }
    function settle(list) {
      follow(list); if (list._follow) list.scrollTop = list.scrollHeight;
      var sc = list.closest('.scroll'); if (sc) { follow(sc); if (sc._follow) sc.scrollTop = sc.scrollHeight; }
    }
    function put(list, li) { if (!list) return null; var fade = list.querySelector('.exfade'); if (fade) fade.remove(); list.appendChild(li); settle(list); return li; }
    // one log, two views: a line lands in the list that sent the turn and, when that is a goal's thread, in the
    // page's dialogue as well, with the goal's chip
    function appendLine(who, text, cls) {
      var main = mainList(), tgt = live.target || main;
      var pair = { li: put(tgt, exLi(who, text, cls, tgt === main ? live.goal : null)), mi: null };
      if (tgt !== main) pair.mi = put(main, exLi(who, text, cls, live.goal));
      return pair;
    }
    function each(pair, f) { if (!pair) return; if (pair.li) f(pair.li); if (pair.mi) f(pair.mi); }
    function stateText(s) {
      if (!s) return '';
      if (s.busy) { var q = +(s.quiet_seconds || 0); return 'working' + (q > 300 ? ', quiet for ' + Math.floor(q / 60) + ' min' : '') + '…'; }
      if (!s.alive) return s.queued ? 'parked — ' + s.queued + ' of yours waits for it to wake' : 'parked — it wakes on your word';
      return s.queued ? 'listening · ' + s.queued + ' queued' : 'listening';
    }
    function showState(s) { if (s && o.onState) { try { o.onState(s); } catch (err) {} } var el = $(o.state || '#exState'); if (!el || !s) return; el.textContent = stateText(s); el.setAttribute('data-state', s.busy ? 'busy' : (s.alive ? 'idle' : 'parked')); }
    // a GET on these pages carries the token in the standard Authorization header (the gate reads it; the X-Anchor-Token
    // header it does not) — his polls were refused with the page's header alone and asked again three times a second
    // (W2c-3); the token never rides the request line of a poll (Grok's read of W2c-3)
    function q() { return '?pid=' + encodeURIComponent(PID) + '&dir=' + encodeURIComponent(DIR); }
    function getHeaders() { return authHeaders(headers()); }
    var refused = false;
    function refusedOnce() {   // a refused poll: said once, the loop stopped; the page's own login (when it has one) is offered
      if (refused) return; refused = true; live.polling = false;
      var el = $(o.state || '#exState'); if (el) { el.textContent = 'not logged in — the steward’s words cannot reach this page'; el.setAttribute('data-state', 'auth'); }
      live.target = null; live.goal = null;
      appendLine('sys', 'This browser is not logged in to Anchor, so the steward’s words cannot reach this page \u2014 log in below.', 'dim');
      if (o.onAuth) o.onAuth();
    }
    function asJson(r) { if (r.status === 401 || r.status === 403) { var e = new Error('auth'); e.auth = true; throw e; } return r.json(); }
    // a turn that ended before this page saw its words (it was mid-turn when the page opened): the log has it
    var SILENT = 'Done — no reply (it answered with nothing to say, or acted quietly on the record).';
    function catchUp(mine) {
      fetch('/api/steward/history' + q(), { headers: getHeaders() })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          var ts = (j && j.turns) || [], last = null;
          for (var i = ts.length - 1; i >= 0; i--) { var role = String(ts[i].role || '').toLowerCase(); if (ts[i].text && role !== 'john' && role !== 'you' && role !== 'user' && role !== 'human') { last = ts[i]; break; } }
          var main = mainList(), rows = main ? $$('.exrow.st', main) : [], txt = last ? String(last.text).trim() : '';
          if (!last || (rows.length && String(rows[rows.length - 1]._raw !== undefined ? rows[rows.length - 1]._raw : rows[rows.length - 1].querySelector('.ext').textContent).trim() === txt)) { if (mine) appendLine('st', SILENT, 'dim'); return; }
          live.goal = last.goal || null; live.target = null; var cu = appendLine('st', txt, ''); each(cu, md); live.goal = null;
        })
        .catch(function () {});
    }
    function handleEvent(ev) {
      if (!ev || ev.tick) return;
      if (ev.t === 'delta') {
        if (live.act) { each(live.act, function (li) { li.remove(); }); live.act = null; }
        if (!live.line) live.line = appendLine('st', '', 'live');
        each(live.line, function (li) { li._raw = (li._raw || '') + (ev.text || ''); li.querySelector('.ext').textContent = li._raw; settle(li.parentNode); });
        return;
      }
      if (ev.t === 'turn_end') {
        // a turn that ends without words is said, never left blank (his word, 2026-10-02: he asked for no reply and
        // the page showed nothing - he could not tell the dialogue worked); a row left at "working…" is closed the same way
        var mine = live.sent; live.sent = false;
        if (live.act) { each(live.act, function (li) { li.remove(); }); live.act = null; }
        live.steps = 0;
        if (live.line) {
          each(live.line, function (li) {
            li.classList.remove('live');
            if (li.querySelector('.ext').textContent.trim()) { md(li); return; }
            if (mine) { li.querySelector('.ext').textContent = SILENT; li.classList.add('dim'); var w = li.querySelector('.exw .t'); if (w) w.textContent = ''; }
            else li.remove();      // a wordless turn this page did not send leaves no row (Grok, 2026-10-02)
          });
          live.line = null;
        } else catchUp(mine);
        live.target = null; live.goal = null; return;
      }
      if (ev.t === 'john') { var t = String(ev.text || ''); if (live.skipJohn && t === live.skipJohn) { live.skipJohn = ''; return; } live.target = null; live.goal = null; appendLine('you', t, ''); return; }
      if (ev.t === 'sys' && ev.text) { appendLine('sys', ev.text, 'dim'); return; }
      if (ev.t === 'receipt' && ev.text) { each(appendLine('st', ev.text, ''), md); return; }   // the delivery receipt, its links live
      if (ev.t === 'tool') {
        // the cockpit's rule: a tool step ends the block the words were in; the next words open a new one
        if (live.line) { each(live.line, function (li) { li.classList.remove('live'); if (li.querySelector('.ext').textContent.trim()) md(li); else li.remove(); }); live.line = null; }
        if (!live.act) live.act = appendLine('sys', 'working …', 'dim act');
        live.steps = (live.steps || 0) + 1;
        each(live.act, function (li) { li.querySelector('.ext').textContent = 'working … ' + live.steps + ' step' + (live.steps === 1 ? '' : 's') + (ev.name ? ' · ' + ev.name : ''); });
        return;
      }
    }
    function primeSeq() {   // the ring's current top, so the poll never replays lines the log below already shows
      return fetch('/api/steward/events' + q() + '&since=0', { headers: getHeaders() })
        .then(asJson)
        .then(function (j) {
          var evs = j.events || [];
          evs.forEach(function (ev) { live.seq = Math.max(live.seq, ev.seq || 0); });
          if (j.state && j.state.epoch !== undefined) live.epoch = j.state.epoch;
          showState(j.state);
          // 2026-10-11: opened mid-turn, the page shows what the steward has said so far in this turn (the log holds
          // it only at the turn's end); his own words are already in the log below, so they are not replayed
          if (j.state && j.state.busy) {
            var from = 0;
            evs.forEach(function (ev, i) { if (ev.t === 'turn_end') from = i + 1; });
            evs.slice(from).forEach(function (ev) { if (ev.t !== 'john') handleEvent(ev); });
          }
        })
        .catch(function (e) { if (e && e.auth) refusedOnce(); });
    }
    function pollLoop() {
      if (live.polling) return; live.polling = true;
      (function step() {
        if (live.stopped) { live.polling = false; return; }   // W2e: a card's dialogue stops when the card closes
        fetch('/api/steward/events' + q() + '&since=' + live.seq, { headers: getHeaders() })
          .then(asJson)
          .then(function (j) {
            if (!j || !j.events) { setTimeout(step, 3000); return; }   // an answer with no stream in it: wait, never hammer
            var ep = j.state && j.state.epoch;
            if (ep !== undefined && live.epoch !== null && ep !== live.epoch) { live.seq = 0; live.epoch = ep; appendLine('sys', '— the steward reconnected —', 'dim'); }
            else if (ep !== undefined) live.epoch = ep;
            showState(j.state);
            (j.events || []).forEach(function (ev) { live.seq = Math.max(live.seq, ev.seq || 0); handleEvent(ev); });
            // W2e-8: a dialogue inside a tile learns the record's stamp from the stream and, when it moves, tells the
            // tile to re-read itself in place (o.onStamp); the pages' own dialogues keep the reload with the receipt
            if (j.stamp && !BOOT_STAMP) BOOT_STAMP = j.stamp;   // learned on any page with no boot stamp (Grok's read of W2e-8)
            if (j.stamp && BOOT_STAMP && j.stamp !== BOOT_STAMP && !live.line) {
              if (o.onStamp) { BOOT_STAMP = j.stamp; try { o.onStamp(j.stamp); } catch (err) {} }
              else { keep('The steward changed the record — the page is reloaded.', false, null); location.reload(); return; }
            }
            if (!live.stopped) setTimeout(step, 250);
          })
          .catch(function (e) { if (e && e.auth) { refusedOnce(); return; } if (!live.stopped) setTimeout(step, 3000); });
      })();
    }
    function send(text, goal, list, btn, box, DK) {
      btn.disabled = true; btn.textContent = 'Thinking…';
      (live.polling ? Promise.resolve() : primeSeq()).then(function () {
        return fetch('/api/steward/say', { method: 'POST', headers: headers(), body: JSON.stringify({ pid: PID, dir: DIR, text: text, goal: goal || undefined }) });
      })
        .then(asJson)
        .then(function (j) {
          btn.disabled = false; btn.textContent = 'Send';
          // W4 (2026-10-08): a page that places the record in itself (o.onRecord) and waits to reload for a new build
          // (o.onBuild) - the Cave - is never reloaded from here; a page without them keeps the reload with its receipt
          if (j && j.error === 'build-mismatch') {   // a stale tab: the draft is kept in this browser; the renewed page puts it back
            var stale = 'This page was older than the server — it is renewed; your unsent text is back in the box, send it again.';
            if (o.onBuild) { receipt(stale, true); o.onBuild(stale); return; }
            keep(stale, true, null);
            location.reload(); return;
          }
          if (!j || j.ok === false) {
            var why = (j && (j.say || j.receipt || j.error || j.message)) || 'No answer came back — nothing was done.';
            if (j && j.undo) {   // a verb that landed in part: the refusal and its undo are his
              if (o.onRecord) { o.onRecord(why, j.undo, true); return; }
              keep(why, true, j.undo); location.reload(); return;
            }
            receipt(why, true); live.target = list; live.goal = goal || null; appendLine('sys', 'Not sent — ' + why, 'dim'); live.target = null; live.goal = null; return;
          }
          try { if (DK) localStorage.removeItem(DK); } catch (e) {}
          if (j.campaign_act && !j.read_only) {   // a Campaign verb: the record changed; the receipt and its undo are his
            live.target = list; live.goal = goal || null; appendLine('you', text); appendLine('st', j.say || j.receipt || 'Done.'); live.target = null; live.goal = null;
            if (j.open_url && j.act === 'open_cockpit') { box.value = ''; try { box.dispatchEvent(new Event('input')); } catch (e) {} receipt(j.say, false); window.location.href = j.open_url; return; }
            if (o.onRecord) { box.value = ''; try { box.dispatchEvent(new Event('input')); } catch (e) {} o.onRecord(j.say, j.undo || null, false); return; }
            keep(j.say, false, j.undo || null);
            location.reload(); return;
          }
          box.value = ''; try { box.dispatchEvent(new Event('input')); } catch (e) {}
          live.target = list; live.goal = goal || null; live.line = null; live.skipJohn = text; live.sent = true;
          appendLine('you', text);
          if (j.kept) appendLine('sys', 'the steward could not wake just now — your text is kept and goes when it wakes', 'dim');
          else if (j.queued) appendLine('sys', 'queued — the steward is mid-turn; yours goes next', 'dim');
          receipt(goal ? 'Said to the steward about this goal — it answers as it writes.' : 'Said — the steward answers above as it writes.');
          if (!refused) pollLoop();
        })
        .catch(function (e) { btn.disabled = false; btn.textContent = 'Send'; if (e && e.auth) { refusedOnce(); receipt('Not sent — this browser is not logged in to Anchor.', true); return; } receipt('That did not go through — nothing was done.', true); });
    }
    // live from the open: the ring's top first (so the log shown below is not replayed), then the stream
    if (PID && mainList()) primeSeq().then(function () { if (!refused) pollLoop(); });
    // the dialogue opens at its latest turn, never its first (his word, 2026-10-01: "you should be at the bottom of that, not the top")
    (function () { var ml = mainList(); if (!ml) return; $$('.exrow.st', ml).forEach(md); settle(ml); setTimeout(function () { settle(ml); }, 300); })();
    function stop() { live.stopped = true; }
    // W4 (ChatGPT r2): a login taken in place resumes the stream it refused - the same dialogue, the same cursor
    function resume() {
      if (!refused) return; refused = false;
      var el = $(o.state || '#exState'); if (el) { el.textContent = '…'; el.setAttribute('data-state', ''); }
      if (!live.polling && !live.stopped) pollLoop();
    }
    return { send: send, appendLine: appendLine, mainList: mainList, stop: stop, md: md, resume: resume };
  }
  function authHeaders(base) {   // the page's headers plus the standard Authorization header the GET gate reads
    var h = {}; Object.keys(base || {}).forEach(function (k) { h[k] = base[k]; });
    var t = ''; try { t = localStorage.getItem('anchor_token') || ''; } catch (e) {}
    if (t && !h.Authorization) h.Authorization = 'Bearer ' + t;
    return h;
  }
  // R14 (2026-09-29), one script for both pages (Grok's read of W2e-3): the login box each page mounts (#loginBox,
  // #loginTok, #loginGo, #loginMsg) — the token pasted is held, the browser logged in (POST /api/auth/login mints the
  // cookie) and the page reloaded with a receipt; a refused token is said and forgotten
  function loginBox(o) {
    o = o || {};
    var box = document.getElementById('loginBox'), tok = document.getElementById('loginTok'), go = document.getElementById('loginGo'), msg = document.getElementById('loginMsg');
    function say(t) { if (msg) msg.textContent = t || ''; }
    function show(text) {
      if (!box) return;
      box.hidden = false; say(text);
      try { box.scrollIntoView({ block: 'center' }); } catch (e) {}
      setTimeout(function () { try { tok.focus(); } catch (e) {} }, 50);
    }
    function login(t) {
      try { localStorage.setItem('anchor_token', t); } catch (e) {}
      return fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Anchor-Token': t }, body: JSON.stringify({ token: t }) }).catch(function () { return null; });
    }
    function doLogin() {
      var t = ((tok && tok.value) || '').trim();
      if (!t) { say('Paste the token first.'); return; }
      if (go) go.disabled = true; say('Logging in\u2026');
      login(t).then(function (r) {
        if (go) go.disabled = false;
        if (r && r.ok && o.onLogin) { say('Logged in.'); o.onLogin(); return; }   // a page that takes the login in place (the Cave, W4)
        if (r && r.ok) { say('Logged in.'); if (o.receiptKey) { try { sessionStorage.setItem(o.receiptKey, JSON.stringify({ text: 'Logged in. This browser holds the token now.', undo: null })); } catch (e) {} } location.reload(); return; }
        try { localStorage.removeItem('anchor_token'); } catch (e) {}
        say((r && r.status === 401) ? 'That token was refused \u2014 it is not the current one.' : 'That did not go through; try again.');
      });
    }
    if (go) go.addEventListener('click', doLogin);
    if (tok) tok.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); doLogin(); } });
    return { show: show, login: login };
  }
  // the Deliverables bar under the conversation (his word, 2026-10-02): the Campaign's register, newest first, each one
  // a click away - a text document through the report viewer, anything else through the cockpit's own file route
  function deliverablesBar() {
    var $ = function (s) { return document.querySelector(s); };
    function barToken() { try { return localStorage.getItem('anchor_token') || ''; } catch (e) { return ''; } }
    function barHeaders() { var h = { 'Content-Type': 'application/json' }, t = barToken(); if (t) { h['X-Anchor-Token'] = t; } return h; }
    var bar = $('#delivBar'), btn = $('#delivToggle'), ul = $('#delivList'), cnt = $('#delivCount');
    if (!bar || !btn || !ul) return;
    var pid = bar.getAttribute('data-pid') || '';
    function href(it) {
      var t = barToken(), tq = t ? '&token=' + encodeURIComponent(t) : '';
      var dir = encodeURIComponent(it.dir || bar.getAttribute('data-dir') || ''), path = encodeURIComponent(it.path || '');
      if (/\.(md|txt|csv|json|log)$/i.test(it.path || '')) return '/steward/report?dir=' + dir + '&path=' + path + '&pid=' + encodeURIComponent(pid) + tq;
      return '/api/steward/deliverable-file?pid=' + encodeURIComponent(pid) + '&dir=' + dir + '&path=' + path
        + (it.hash ? '&hash=' + encodeURIComponent(it.hash) : '') + (/\.(docx|pptx|xlsx)$/i.test(it.path || '') ? '&view=1' : '') + tq;
    }
    function load() {
      return fetch('/api/steward/deliverables?pid=' + encodeURIComponent(pid) + '&dir=' + encodeURIComponent(bar.getAttribute('data-dir') || ''), { headers: authHeaders(barHeaders()) })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          var items = ((j && j.items) || []).filter(function (it) { return it && it.path; });
          if (cnt) cnt.textContent = items.length ? (items.length + (items.length === 1 ? ' made' : ' made') + ' · newest ' + (items[0].date || '')) : 'none yet';
          ul.innerHTML = '';
          if (!items.length) { var e = document.createElement('li'); e.textContent = 'Nothing made in this conversation yet.'; ul.appendChild(e); return; }
          items.forEach(function (it) {
            var li = document.createElement('li'), a = document.createElement('a'), m = document.createElement('span');
            a.href = href(it); a.target = '_blank'; a.rel = 'noopener'; a.textContent = it.what || it.path;
            if (it.is_current) a.className = 'db-cur';
            m.className = 'db-m'; m.textContent = (it.date || '') + ' · ' + it.path + (it.step ? ' · ' + it.step : '');
            li.appendChild(a); li.appendChild(m); ul.appendChild(li);
          });
        })
        .catch(function () { if (cnt) cnt.textContent = 'could not be read'; });
    }
    btn.addEventListener('click', function () {
      var open = ul.hidden; ul.hidden = !open; btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) load();
    });
    load();
    setInterval(function () { if (!document.hidden) load(); }, 60000);   // a new deliverable shows within a minute
  }
  // Match the AI cockpit: show the growing draft, leaving room for the conversation.
  // A hidden goal composer is measured again when its place opens.
  function fitComposer(box) {
    if (!box || !box.getClientRects().length) return;
    if (!box._winHGuard) {
      box._winHGuard = true;
      box.addEventListener('compositionstart', function () { box._composing = true; });
      box.addEventListener('compositionend', function () { box._composing = false; fitComposer(box); });
      box.addEventListener('blur', function () { box._composing = false; });
    }
    var minimum = parseFloat(getComputedStyle(box).minHeight) || 0;
    var prevScroll = box.scrollTop;
    if (!box._composing) {
      box.style.height = 'auto';
      var target = Math.max(minimum, Math.min(box.scrollHeight + 2, window.innerHeight * 0.4));
      box.style.height = target + 'px';
      if (prevScroll) box.scrollTop = prevScroll;
    } else if (box.scrollHeight > box.clientHeight) {
      var targetC = Math.max(minimum, Math.min(box.scrollHeight + 2, window.innerHeight * 0.4));
      if (targetC > (parseFloat(box.style.height) || 0)) box.style.height = targetC + 'px';
    }
    box.style.overflowY = box.scrollHeight > box.clientHeight ? 'auto' : 'hidden';
  }
  window.StewardDialogue = { init: init, authHeaders: authHeaders, loginBox: loginBox }; window.StewardDialogue.fitComposer = fitComposer;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', deliverablesBar); else deliverablesBar();   // authHeaders: the one way a GET on these pages carries the token; loginBox: the one login script
})();
