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
      var rawStr = String(raw);
      if (rawStr.indexOf('[SPEED_RACER_OPEN') !== -1) {
        var mOpen = rawStr.match(/\[SPEED_RACER_OPEN:?([^\]]*)\]/);
        var openDid = (mOpen && mOpen[1]) ? mOpen[1].trim() : '';
        rawStr = rawStr.replace(/\[SPEED_RACER_OPEN:?[^\]]*\]/g, '').trim();
        li._raw = rawStr;
        try {
          var hw = (window.parent && window.parent !== window) ? window.parent : window;
          if (typeof hw.openCaveSpeedRacer === 'function' && !li.dataset.srTriggered) {
            li.dataset.srTriggered = '1';
            if (live && live.sent) hw.openCaveSpeedRacer(openDid);
          }
        } catch (e) {}
      }
      try { x.textContent = ''; window.mdRender(x, rawStr); } catch (e) { x.textContent = rawStr; }
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
            var rawTxt = li._raw || li.querySelector('.ext').textContent.trim();
            if (rawTxt) {
              md(li);
              try { speakConciseSummary(rawTxt); } catch (e) {}
              return;
            }
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
      if (box && typeof box._stopDictation === 'function') { try { box._stopDictation(); } catch (e) {} }
      if (box) box._composing = false;
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
          if (j.campaign_act) {   // a Campaign verb or fast Steward answer: shown immediately in the dialogue
            live.target = list; live.goal = goal || null; live.skipJohn = text;
            appendLine('you', text); var stPair = appendLine('st', j.say || j.receipt || 'Done.'); each(stPair, md);
            live.target = null; live.goal = null;
            box.value = ''; try { box.dispatchEvent(new Event('input')); } catch (e) {}
            if (j.spoken_summary || j.say) {
              try { speakConciseSummary(j.spoken_summary || j.say); } catch (e) {}
            }
            if (j.act === 'open_deliverable' && j.open_deliverable_url) {
              receipt(j.receipt || j.say || 'Opened deliverable.', false);
              openCaveDeliverableDrawer(j.open_deliverable_title || 'Deliverable', j.open_deliverable_url);
              return;
            }
            if (j.act === 'open_speed_racer' || j.open_speed_racer) {
              receipt(j.receipt || 'Opened Speed Racer Tile in Email Hub.', false);
              try {
                var hostWin = (window.parent && window.parent !== window) ? window.parent : window;
                if (typeof hostWin.openCaveSpeedRacer === 'function') {
                  hostWin.openCaveSpeedRacer(j.speed_racer_draft_id || '');
                }
              } catch (e) {}
              return;
            }
            if (j.working_list_act) {
              receipt(j.receipt || j.say || 'Updated Working List Spine.', false);
              try {
                var hostWinWl = (window.parent && window.parent !== window) ? window.parent : window;
                if (typeof hostWinWl.refreshCaveWorkingList === 'function') {
                  hostWinWl.refreshCaveWorkingList(j.working_list || null);
                }
              } catch (e) {}
              return;
            }
            if (j.read_only) { receipt(j.receipt || j.say || 'Answered.', false); return; }
            if (j.open_url && j.act === 'open_cockpit') { receipt(j.say, false); window.location.href = j.open_url; return; }
            if (o.onRecord) { o.onRecord(j.receipt || j.say, j.undo || null, false); return; }
            keep(j.receipt || j.say, false, j.undo || null);
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
    if (!box._spellWired) {
      box._spellWired = true;
      wireSpellcheckOnTextarea(box);
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

  /* ---------- Split-Screen Deliverable / Video Drawer for Cave of Wonders & Star Chart ---------- */
  function ensureCaveEnhanceStyles() {
    if (document.getElementById('cave-steward-enhance-css')) return;
    var st = document.createElement('style');
    st.id = 'cave-steward-enhance-css';
    st.textContent = [
      '.anchor-spell-popup { position:fixed; z-index:99999; min-width:210px; max-width:300px; background:#0f172a; border:1px solid rgba(56,189,248,0.45); border-radius:10px; box-shadow:0 12px 32px rgba(0,0,0,0.75); padding:6px; color:#f1f5f9; font-family:system-ui,-apple-system,sans-serif; font-size:12.5px; }',
      '.anchor-spell-popup .asp-head { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:4px 8px 6px; border-bottom:1px solid rgba(148,163,184,0.16); margin-bottom:4px; font-size:11px; color:#94a3b8; }',
      '.anchor-spell-popup .asp-word { color:#f87171; font-weight:700; text-decoration:underline wavy #ef4444; }',
      '.anchor-spell-popup .asp-close { background:none; border:none; color:#94a3b8; cursor:pointer; font-size:13px; padding:0 4px; }',
      '.anchor-spell-popup .asp-list { display:flex; flex-direction:column; gap:2px; }',
      '.anchor-spell-popup .asp-item { display:flex; align-items:center; justify-content:space-between; width:100%; text-align:left; padding:6px 10px; border-radius:6px; border:1px solid transparent; background:rgba(30,41,59,0.65); color:#e2e8f0; font-size:13px; font-weight:600; cursor:pointer; }',
      '.anchor-spell-popup .asp-item:hover { background:rgba(56,189,248,0.18); border-color:rgba(56,189,248,0.45); color:#38bdf8; }',
      '.anchor-spell-popup .asp-badge { font-size:10px; font-weight:600; color:#38bdf8; background:rgba(56,189,248,0.12); padding:1px 6px; border-radius:4px; }',
      '.anchor-spell-popup .asp-empty { padding:8px 10px; color:#94a3b8; font-style:italic; font-size:12px; }',
      '.anchor-spell-popup .asp-foot { margin-top:4px; padding-top:4px; border-top:1px solid rgba(148,163,184,0.16); display:flex; justify-content:space-between; gap:4px; }',
      '.anchor-spell-popup .asp-action-btn { flex:1; background:transparent; border:1px solid rgba(148,163,184,0.25); color:#94a3b8; border-radius:5px; padding:4px 6px; font-size:11px; cursor:pointer; }',
      '.anchor-spell-popup .asp-action-btn:hover { color:#e2e8f0; border-color:rgba(148,163,184,0.5); background:rgba(255,255,255,0.05); }',
      '.cave-voice-btn { display:inline-flex; align-items:center; gap:5px; padding:6px 11px; border-radius:7px; border:1px solid rgba(148,163,184,0.28); background:rgba(15,23,42,0.75); color:#cbd5e1; font-size:12px; font-weight:600; cursor:pointer; white-space:nowrap; }',
      '.cave-voice-btn:hover { border-color:rgba(56,189,248,0.5); color:#f8fafc; }',
      '.cave-voice-btn.recording { border-color:rgba(239,68,68,0.75); background:rgba(239,68,68,0.18); color:#fca5a5; }',
      '.cave-voice-btn.talk-active { border-color:rgba(52,211,153,0.65); background:rgba(16,185,129,0.16); color:#6ee7b7; }',
      '#caveSplitDrawer { position:fixed; top:0; right:0; width:min(52vw, 820px); height:100vh; z-index:99990; background:#090d16; border-left:2px solid rgba(56,189,248,0.45); box-shadow:-12px 0 40px rgba(0,0,0,0.8); display:flex; flex-direction:column; }',
      '#caveSplitDrawer .csd-bar { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:10px 14px; background:#0f172a; border-bottom:1px solid rgba(56,189,248,0.25); color:#f8fafc; font-family:system-ui,-apple-system,sans-serif; }',
      '#caveSplitDrawer .csd-title { font-size:13px; font-weight:700; color:#38bdf8; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }',
      '#caveSplitDrawer .csd-close { padding:5px 12px; border-radius:6px; border:1px solid rgba(248,113,113,0.55); background:rgba(239,68,68,0.18); color:#fca5a5; font-size:12px; font-weight:700; cursor:pointer; }',
      '#caveSplitDrawer .csd-close:hover { background:rgba(239,68,68,0.32); color:#fff; }',
      '#caveSplitDrawer iframe { flex:1; width:100%; height:100%; border:0; background:#0b111e; }'
    ].join('\n');
    document.head.appendChild(st);
  }

  function closeCaveDeliverableDrawer() {
    var d = document.getElementById('caveSplitDrawer');
    if (d) d.remove();
  }
  window.closeCaveDeliverableDrawer = closeCaveDeliverableDrawer;

  function openCaveDeliverableDrawer(title, url) {
    if (!url) return;
    try {
      if (window.top && window.top.ANCHOR_APP && typeof window.top.ANCHOR_APP.openSecondWindow === 'function') {
        window.top.ANCHOR_APP.openSecondWindow(url, title || 'Deliverable', window, true);
        return;
      }
    } catch (e) {}
    ensureCaveEnhanceStyles();
    closeCaveDeliverableDrawer();
    var drawer = document.createElement('div');
    drawer.id = 'caveSplitDrawer';
    var bar = document.createElement('div');
    bar.className = 'csd-bar';
    var tSpan = document.createElement('span');
    tSpan.className = 'csd-title';
    tSpan.textContent = '📄 ' + (title || 'Deliverable Preview');
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'csd-close';
    closeBtn.textContent = '✕ Close Split Window';
    closeBtn.onclick = closeCaveDeliverableDrawer;
    bar.appendChild(tSpan);
    bar.appendChild(closeBtn);
    var ifr = document.createElement('iframe');
    var tok = '';
    try { tok = localStorage.getItem('anchor_token') || ''; } catch (e) {}
    var fullUrl = url;
    if (tok && fullUrl.indexOf('token=') < 0 && fullUrl.indexOf('/api/') === 0) {
      fullUrl += (fullUrl.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(tok);
    }
    ifr.src = fullUrl;
    drawer.appendChild(bar);
    drawer.appendChild(ifr);
    document.body.appendChild(drawer);
  }
  window.openCaveDeliverableDrawer = openCaveDeliverableDrawer;

  /* ---------- Talk-Back Mode (concise 1-2 sentence verbal summary) ---------- */
  var TALK_MODE_KEY = 'anchor:steward:talk_mode';
  var _caveTalkAudio = null;
  function stopCaveTalkAudio() {
    if (_caveTalkAudio) {
      try { _caveTalkAudio.pause(); _caveTalkAudio.currentTime = 0; } catch (e) {}
      _caveTalkAudio = null;
    }
    if (window.speechSynthesis) {
      try { window.speechSynthesis.cancel(); } catch (e) {}
    }
  }
  function isTalkModeOn() {
    try { return localStorage.getItem(TALK_MODE_KEY) === '1'; } catch (e) { return false; }
  }
  function setTalkModeOn(on) {
    try { localStorage.setItem(TALK_MODE_KEY, on ? '1' : '0'); } catch (e) {}
    Array.prototype.forEach.call(document.querySelectorAll('[data-cave-talk-btn]'), function (btn) {
      btn.classList.toggle('talk-active', !!on);
      btn.textContent = on ? '🔊 Talk: ON' : '🔈 Talk Mode';
    });
    if (!on) {
      stopCaveTalkAudio();
    }
  }
  function playCaveSummaryAudio(picked) {
    stopCaveTalkAudio();
    function fallbackSpeech() {
      if (window.speechSynthesis && typeof window.SpeechSynthesisUtterance === 'function') {
        try {
          window.speechSynthesis.cancel();
          setTimeout(function () {
            try {
              var u = new SpeechSynthesisUtterance(picked);
              u.rate = 1.06;
              window.speechSynthesis.speak(u);
            } catch (e) {}
          }, 60);
        } catch (e) {}
      }
    }
    var tok = '';
    try { tok = localStorage.getItem('anchor_token') || ''; } catch (e) {}
    var hdrs = { 'Content-Type': 'application/json' };
    if (tok) { hdrs.Authorization = 'Bearer ' + tok; hdrs['X-Anchor-Token'] = tok; }
    fetch('/api/steward/dictate', {
      method: 'POST',
      headers: hdrs,
      body: JSON.stringify({ action: 'tts', text: picked, rate: 1 })
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.ok && j.audio_b64) {
          var aud = new Audio('data:audio/wav;base64,' + j.audio_b64);
          _caveTalkAudio = aud;
          aud.play().catch(function () { fallbackSpeech(); });
        } else {
          fallbackSpeech();
        }
      })
      .catch(function () { fallbackSpeech(); });
  }
  function speakConciseSummary(rawText, forceSpeak) {
    if (!forceSpeak && !isTalkModeOn()) return;
    var clean = String(rawText || '')
      .replace(/```[\s\S]*?```/g, '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/[*_`#>~]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    if (!clean) return;
    var sents = clean.split(/(?<=[.!?])\s+/).filter(Boolean);
    var picked = sents.slice(0, 2).join(' ');
    if (picked.length > 210) picked = picked.slice(0, 207).replace(/\s+\S*$/, '') + '...';
    try {
      ensureCaveEnhanceStyles();
      var hostEl = document.getElementById('exList') || (document.getElementById('exSay') && document.getElementById('exSay').parentElement);
      if (hostEl) {
        var oldB = document.getElementById('caveSpokenSummaryBanner');
        if (oldB) oldB.remove();
        var ban = document.createElement(hostEl.tagName === 'UL' || hostEl.tagName === 'OL' ? 'li' : 'div');
        ban.id = 'caveSpokenSummaryBanner';
        ban.className = 'cave-spoken-summary-banner';
        ban.style.cssText = 'display:flex;align-items:center;gap:8px;padding:7px 11px;margin:6px 0;border-radius:8px;border:1px solid rgba(52,211,153,0.45);background:rgba(16,185,129,0.12);color:#d1fae5;font-size:12.5px;';
        var txtSpan = document.createElement('span');
        txtSpan.style.cssText = 'flex:1;line-height:1.35;';
        txtSpan.innerHTML = '<strong>🔊 Spoken Summary:</strong> ';
        txtSpan.appendChild(document.createTextNode(picked));
        var repB = document.createElement('button');
        repB.type = 'button';
        repB.className = 'cave-voice-btn';
        repB.style.cssText = 'padding:3px 8px;font-size:11px;';
        repB.textContent = '🔊 Replay';
        repB.onclick = function (ev) { ev.preventDefault(); ev.stopPropagation(); playCaveSummaryAudio(picked); };
        var mutB = document.createElement('button');
        mutB.type = 'button';
        mutB.className = 'cave-voice-btn';
        mutB.style.cssText = 'padding:3px 8px;font-size:11px;';
        mutB.textContent = '⏹ Silence';
        mutB.onclick = function (ev) { ev.preventDefault(); ev.stopPropagation(); stopCaveTalkAudio(); };
        ban.appendChild(txtSpan);
        ban.appendChild(repB);
        ban.appendChild(mutB);
        hostEl.appendChild(ban);
        try { hostEl.scrollTop = hostEl.scrollHeight; } catch (e) {}
      }
    } catch (e) {}
    playCaveSummaryAudio(picked);
  }

  /* ---------- Native Windows 11 Spellcheck Suggestion Popup (left-click / right-click) ---------- */
  var _spellPop = null;
  function closeSpellPop() {
    if (_spellPop) { _spellPop.remove(); _spellPop = null; }
  }
  document.addEventListener('mousedown', function (ev) {
    if (_spellPop && !_spellPop.contains(ev.target)) closeSpellPop();
  });
  function extractWordAt(text, idx) {
    var str = String(text || '');
    if (!str) return null;
    var pos = Math.max(0, Math.min(idx, str.length));
    if (pos === str.length || !/[A-Za-z'\u2019]/.test(str.charAt(pos))) {
      if (pos > 0 && /[A-Za-z'\u2019]/.test(str.charAt(pos - 1))) pos = pos - 1;
      else return null;
    }
    var start = pos;
    while (start > 0 && /[A-Za-z'\u2019]/.test(str.charAt(start - 1))) start--;
    var end = pos + 1;
    while (end < str.length && /[A-Za-z'\u2019]/.test(str.charAt(end))) end++;
    var word = str.slice(start, end).replace(/^['\u2019]+|['\u2019]+$/g, '');
    var lead = str.slice(start, end).match(/^['\u2019]+/);
    var rStart = start + (lead ? lead[0].length : 0);
    var rEnd = rStart + word.length;
    if (word.length < 2) return null;
    return { word: word, start: rStart, end: rEnd };
  }
  function wireSpellcheckOnTextarea(ta) {
    if (!ta || ta._caveSpellWired) return;
    ta._caveSpellWired = true;
    ta.setAttribute('spellcheck', 'true');
    ta.setAttribute('lang', 'en-US');
    ensureCaveEnhanceStyles();
    function checkAtCursor(ev, isRightClick) {
      var val = ta.value || '';
      if (!val.trim()) return;
      setTimeout(function () {
        if (ta.selectionStart !== ta.selectionEnd && !isRightClick) return;
        var caret = typeof ta.selectionStart === 'number' ? ta.selectionStart : 0;
        var hit = extractWordAt(val, caret);
        if (!hit || !hit.word) return;
        var tok = '';
        try { tok = localStorage.getItem('anchor_token') || ''; } catch (e) {}
        var hdrs = tok ? { 'Authorization': 'Bearer ' + tok, 'X-Anchor-Token': tok } : {};
        fetch('/api/steward/spellcheck?word=' + encodeURIComponent(hit.word), { headers: hdrs })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            if (!res || !res.ok || res.correct) {
              if (!isRightClick) closeSpellPop();
              return;
            }
            closeSpellPop();
            var pop = document.createElement('div');
            pop.className = 'anchor-spell-popup';
            pop.dataset.misspelledWord = hit.word;
            var head = document.createElement('div');
            head.className = 'asp-head';
            var wSpan = document.createElement('span');
            wSpan.className = 'asp-word';
            wSpan.textContent = 'Spelling: "' + hit.word + '"';
            var cBtn = document.createElement('button');
            cBtn.className = 'asp-close';
            cBtn.type = 'button';
            cBtn.textContent = '×';
            cBtn.onclick = function (e) { e.stopPropagation(); closeSpellPop(); };
            head.appendChild(wSpan);
            head.appendChild(cBtn);
            pop.appendChild(head);

            var list = document.createElement('div');
            list.className = 'asp-list';
            var sugs = Array.isArray(res.suggestions) ? res.suggestions : [];
            if (sugs.length) {
              sugs.slice(0, 6).forEach(function (sug, idx) {
                var b = document.createElement('button');
                b.type = 'button';
                b.className = 'asp-item';
                var sTxt = document.createElement('span');
                sTxt.textContent = sug;
                b.appendChild(sTxt);
                if (idx === 0) {
                  var bdg = document.createElement('span');
                  bdg.className = 'asp-badge';
                  bdg.textContent = 'Recommended';
                  b.appendChild(bdg);
                }
                b.onclick = function (e) {
                  e.preventDefault();
                  e.stopPropagation();
                  var cur = ta.value || '';
                  ta.value = cur.slice(0, hit.start) + sug + cur.slice(hit.end);
                  var nc = hit.start + sug.length;
                  closeSpellPop();
                  ta.focus();
                  try { ta.setSelectionRange(nc, nc); } catch (err) {}
                  ta.dispatchEvent(new Event('input', { bubbles: true }));
                };
                list.appendChild(b);
              });
            } else {
              var emp = document.createElement('div');
              emp.className = 'asp-empty';
              emp.textContent = 'No replacement suggestions found';
              list.appendChild(emp);
            }
            pop.appendChild(list);

            var foot = document.createElement('div');
            foot.className = 'asp-foot';
            var addB = document.createElement('button');
            addB.type = 'button';
            addB.className = 'asp-action-btn';
            addB.textContent = '+ Add "' + hit.word + '" to dictionary';
            addB.onclick = function (e) {
              e.preventDefault();
              e.stopPropagation();
              closeSpellPop();
              fetch('/api/steward/spellcheck', {
                method: 'POST',
                headers: Object.assign({ 'Content-Type': 'application/json' }, hdrs),
                body: JSON.stringify({ action: 'add', word: hit.word })
              }).catch(function () {});
              ta.focus();
            };
            var ignB = document.createElement('button');
            ignB.type = 'button';
            ignB.className = 'asp-action-btn';
            ignB.textContent = 'Ignore';
            ignB.onclick = function (e) { e.preventDefault(); e.stopPropagation(); closeSpellPop(); ta.focus(); };
            foot.appendChild(addB);
            foot.appendChild(ignB);
            pop.appendChild(foot);

            document.body.appendChild(pop);
            _spellPop = pop;
            var rect = ta.getBoundingClientRect();
            var cx = (ev && typeof ev.clientX === 'number' && ev.clientX > 0) ? ev.clientX : (rect.left + 80);
            var cy = (ev && typeof ev.clientY === 'number' && ev.clientY > 0) ? ev.clientY : rect.top;
            var pr = pop.getBoundingClientRect();
            var left = Math.min(window.innerWidth - pr.width - 12, Math.max(12, cx - 20));
            var top = cy - pr.height - 12;
            if (top < 12) top = Math.min(window.innerHeight - pr.height - 12, cy + 20);
            pop.style.left = left + 'px';
            pop.style.top = top + 'px';
          })
          .catch(function () {});
      }, 15);
    }
    ta.addEventListener('click', function (ev) { checkAtCursor(ev, false); });
    ta.addEventListener('contextmenu', function (ev) {
      var val = ta.value || '';
      var caret = typeof ta.selectionStart === 'number' ? ta.selectionStart : 0;
      var hit = extractWordAt(val, caret);
      if (hit && hit.word) {
        ev.preventDefault();
        checkAtCursor(ev, true);
      }
    });
  }

  function wireCaveComposerButtons() {
    ensureCaveEnhanceStyles();
    var exSay = document.getElementById('exSay') || document.getElementById('say');
    var exSend = document.getElementById('exSend') || document.getElementById('sendBtn');
    if (!exSay) return;
    wireSpellcheckOnTextarea(exSay);
    var host = exSend ? exSend.parentElement : exSay.parentElement;
    if (!host || !exSend || host.querySelector('[data-cave-dictate-btn]')) return;

    var dictBtn = document.createElement('button');
    dictBtn.type = 'button';
    dictBtn.className = 'cave-voice-btn';
    dictBtn.dataset.caveDictateBtn = '1';
    dictBtn.textContent = '🎤 Dictate';
    dictBtn.title = 'Start/stop continuous voice dictation (with auto-punctuation) · Win+H also supported';
    var recog = null, active = false, pollT = null, restartT = null, dictSeq = 0, recent = [];
    var audioStream = null, audioCtx = null, audioSource = null, audioProcessor = null;
    var pcmFrames = [], preRollFrames = [], speechDetected = false, speechStartTs = 0, lastVoiceTs = 0;
    function encodeCaveWav16kBase64(float32Chunks, inputSampleRate) {
      var totalLen = 0;
      for (var i = 0; i < float32Chunks.length; i++) totalLen += float32Chunks[i].length;
      if (!totalLen) return '';
      var merged = new Float32Array(totalLen);
      var offset = 0;
      for (var j = 0; j < float32Chunks.length; j++) { merged.set(float32Chunks[j], offset); offset += float32Chunks[j].length; }
      var targetRate = 16000;
      var ratio = (inputSampleRate && inputSampleRate > 0) ? (inputSampleRate / targetRate) : 1;
      var outLen = Math.max(1, Math.round(merged.length / ratio));
      var pcm16 = new Int16Array(outLen);
      for (var k = 0; k < outLen; k++) {
        var srcIdx = Math.min(merged.length - 1, Math.floor(k * ratio));
        var s = Math.max(-1, Math.min(1, merged[srcIdx]));
        pcm16[k] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      var wavBuf = new ArrayBuffer(44 + pcm16.length * 2);
      var view = new DataView(wavBuf);
      function writeStr(pos, str) { for (var m = 0; m < str.length; m++) view.setUint8(pos + m, str.charCodeAt(m)); }
      writeStr(0, 'RIFF'); view.setUint32(4, 36 + pcm16.length * 2, true); writeStr(8, 'WAVE');
      writeStr(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
      view.setUint32(24, targetRate, true); view.setUint32(28, targetRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
      writeStr(36, 'data'); view.setUint32(40, pcm16.length * 2, true);
      var bytes = new Uint8Array(wavBuf);
      bytes.set(new Uint8Array(pcm16.buffer), 44);
      var binary = '';
      var chunkSz = 0x8000;
      for (var n = 0; n < bytes.length; n += chunkSz) {
        binary += String.fromCharCode.apply(null, bytes.subarray(n, n + chunkSz));
      }
      return btoa(binary);
    }
    function appendChunk(txt) {
      var norm = String(txt || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, ' ');
      if (!norm) return;
      var now = Date.now();
      recent = recent.filter(function (c) { return now - c.ts < 3800; });
      if (recent.some(function (c) { return c.norm === norm; })) return;
      recent.push({ norm: norm, ts: now });
      var cur = exSay.value || '';
      var sep = (cur && !/\s$/.test(cur)) ? ' ' : '';
      exSay.value = cur + sep + String(txt || '').trim();
      exSay.dispatchEvent(new Event('input', { bubbles: true }));
    }
    function flushCaveAudio() {
      if (!speechDetected || !pcmFrames.length) {
        pcmFrames = []; speechDetected = false; speechStartTs = 0;
        return Promise.resolve();
      }
      var frames = pcmFrames.slice();
      var rate = (audioCtx && audioCtx.sampleRate) ? audioCtx.sampleRate : 48000;
      pcmFrames = []; speechDetected = false; speechStartTs = 0;
      var b64 = encodeCaveWav16kBase64(frames, rate);
      if (!b64) return Promise.resolve();
      if (active) dictBtn.textContent = '⏳ Transcribing…';
      return fetch('/api/steward/dictate', {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
        body: JSON.stringify({ action: 'transcribe', audio_b64: b64 })
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j && j.text) appendChunk(j.text);
      }).catch(function () {}).finally(function () {
        if (active) dictBtn.textContent = '⏹ Listening…';
      });
    }
    function teardownCaveAudio() {
      if (audioProcessor) { try { audioProcessor.onaudioprocess = null; audioProcessor.disconnect(); } catch (e) {} audioProcessor = null; }
      if (audioSource) { try { audioSource.disconnect(); } catch (e) {} audioSource = null; }
      if (audioStream) { try { audioStream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {} audioStream = null; }
      if (audioCtx) { try { audioCtx.close(); } catch (e) {} audioCtx = null; }
    }
    function stopRec() {
      active = false;
      if (restartT) { clearTimeout(restartT); restartT = null; }
      if (pollT) { clearInterval(pollT); pollT = null; }
      flushCaveAudio();
      teardownCaveAudio();
      dictBtn.classList.remove('recording');
      dictBtn.textContent = '🎤 Dictate';
      if (recog) { try { recog.onend = null; recog.onerror = null; recog.onresult = null; recog.stop(); } catch (e) {} recog = null; }
      exSay._composing = false;
      fetch('/api/steward/dictate', {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
        body: JSON.stringify({ action: 'stop' })
      }).catch(function () {});
    }
    exSay._stopDictation = stopRec;
    exSay.addEventListener('keydown', function (ev) {
      if ((ev.key === 'Enter' || ev.keyCode === 13) && !ev.shiftKey && !ev.isComposing && ev.keyCode !== 229) {
        if (active) stopRec();
        exSay._composing = false;
      }
    }, true);
    function startCaveMic() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return Promise.resolve(false);
      return navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
        .then(function (stream) {
          if (!active) { stream.getTracks().forEach(function (t) { t.stop(); }); return false; }
          audioStream = stream;
          var Ctx = window.AudioContext || window.webkitAudioContext;
          audioCtx = new Ctx();
          audioSource = audioCtx.createMediaStreamSource(stream);
          audioProcessor = audioCtx.createScriptProcessor(4096, 1, 1);
          var silent = audioCtx.createGain();
          silent.gain.value = 0;
          audioSource.connect(audioProcessor);
          audioProcessor.connect(silent);
          silent.connect(audioCtx.destination);
          pcmFrames = []; preRollFrames = []; speechDetected = false; speechStartTs = 0; lastVoiceTs = 0;
          audioProcessor.onaudioprocess = function (ev) {
            if (!active) return;
            var input = ev.inputBuffer.getChannelData(0);
            var copy = new Float32Array(input.length);
            copy.set(input);
            var sumSq = 0;
            for (var i = 0; i < copy.length; i++) sumSq += copy[i] * copy[i];
            var rms = Math.sqrt(sumSq / Math.max(1, copy.length));
            var now = Date.now();
            if (rms > 0.0042) {
              if (!speechDetected) {
                speechDetected = true;
                speechStartTs = now;
                preRollFrames.forEach(function (pr) { pcmFrames.push(pr); });
                preRollFrames = [];
              }
              lastVoiceTs = now;
              pcmFrames.push(copy);
              dictBtn.textContent = '🔴 Speaking…';
              if (now - speechStartTs >= 6500) flushCaveAudio();
            } else {
              if (speechDetected) {
                pcmFrames.push(copy);
                if (now - lastVoiceTs >= 900) flushCaveAudio();
              } else {
                preRollFrames.push(copy);
                if (preRollFrames.length > 4) preRollFrames.shift();
              }
            }
          };
          return true;
        })
        .catch(function () { return false; });
    }
    dictBtn.onclick = function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      if (active) { stopRec(); return; }
      active = true;
      dictBtn.classList.add('recording');
      dictBtn.textContent = '⏹ Listening…';
      exSay.focus();
      startCaveMic().then(function (micOk) {
        if (micOk || !active) return;
        fetch('/api/steward/dictate', {
          method: 'POST',
          headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
          body: JSON.stringify({ action: 'start' })
        }).then(function (r) { return r.json(); }).then(function (j) {
          if (j && typeof j.last_seq === 'number') dictSeq = j.last_seq;
        }).catch(function () {});
        if (pollT) clearInterval(pollT);
        pollT = setInterval(function () {
          if (!active) return;
          fetch('/api/steward/dictate', {
            method: 'POST',
            headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
            body: JSON.stringify({ action: 'poll', since: dictSeq })
          }).then(function (r) { return r.json(); }).then(function (j) {
            if (!active || !j) return;
            if (Array.isArray(j.chunks)) {
              j.chunks.forEach(function (c) {
                if (c && typeof c.seq === 'number' && c.seq > dictSeq) dictSeq = c.seq;
                if (c && c.text) appendChunk(c.text);
              });
            }
          }).catch(function () {});
        }, 500);
      });
    };
    host.insertBefore(dictBtn, exSend);

    var talkBtn = document.createElement('button');
    talkBtn.type = 'button';
    talkBtn.className = 'cave-voice-btn' + (isTalkModeOn() ? ' talk-active' : '');
    talkBtn.dataset.caveTalkBtn = '1';
    talkBtn.textContent = isTalkModeOn() ? '🔊 Talk: ON' : '🔈 Talk Mode';
    talkBtn.title = 'Toggle Talk-Back Mode — Anchor speaks a concise 1–2 sentence verbal summary of what is going on';
    talkBtn.onclick = function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      var next = !isTalkModeOn();
      setTalkModeOn(next);
      if (next) {
        var tok = '';
        try { tok = localStorage.getItem('anchor_token') || ''; } catch (e) {}
        var hdrs = tok ? { 'Authorization': 'Bearer ' + tok, 'X-Anchor-Token': tok } : {};
        fetch('/api/steward/fleet-brief', { headers: hdrs })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            speakConciseSummary((j && j.spoken_summary) || 'Talk mode enabled. Ask me what is ready for your input or tell me which deliverable to open.', true);
          })
          .catch(function () {
            speakConciseSummary('Talk mode enabled. Ask me what is ready for your input.', true);
          });
      }
    };
    host.insertBefore(talkBtn, exSend);
  }

  window.StewardDialogue = { init: init, authHeaders: authHeaders, loginBox: loginBox, fitComposer: fitComposer, wireSpellcheckOnTextarea: wireSpellcheckOnTextarea, openCaveDeliverableDrawer: openCaveDeliverableDrawer, speakConciseSummary: speakConciseSummary };
  function bootCaveDialogueExtras() {
    deliverablesBar();
    wireCaveComposerButtons();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bootCaveDialogueExtras); else bootCaveDialogueExtras();
})();
