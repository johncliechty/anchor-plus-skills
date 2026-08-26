/* The steward chamber page (2026-08-15, John).
 *
 * Deliberately small. The cockpit's project-window.js is 8,000+ lines and this
 * page loads none of it: dead code that shares a document with live code is
 * what deleted the M1 chamber on every open for twelve waves.
 *
 * Every DOM write here is textContent / createTextNode — never innerHTML with
 * agent-influenced text (the F5 law). The server render is already escaped.
 */
(function () {
  'use strict';

  var PID = window.ANCHOR_PROJECT_ID || '';
  var EFFORT = window.ANCHOR_EFFORT || 'campaign';   // the open seal
  var RUN_LIVE = false;                              // set by pollPulse
  var SAYING = false;                                // a turn is in flight
  var STEWARD = window.ANCHOR_STEWARD_NAME || 'Ecgberht';
  var doc = document;

  // ── plumbing ──────────────────────────────────────────────────────────────
  function token() {
    try { return localStorage.getItem('anchor_token') || ''; } catch (e) { return ''; }
  }
  function tq() { var t = token(); return t ? '&token=' + encodeURIComponent(t) : ''; }
  function tq1() { var t = token(); return t ? '?token=' + encodeURIComponent(t) : ''; }

  function post(route, body) {
    var h = { 'Content-Type': 'application/json' };
    var t = token();
    if (t) h['X-Anchor-Token'] = t;
    return fetch(route, { method: 'POST', headers: h, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json(); });
  }
  function get(route) {
    return fetch(route).then(function (r) { return r.json(); });
  }
  function el(tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function $(sel) { return doc.querySelector(sel); }

  // ── the transcript ────────────────────────────────────────────────────────
  var msgs = $('.msgs');

  function atBottom() {
    if (!msgs) return true;
    return (msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight) < 120;
  }
  /* Pin to newest — but never yank the page out from under him if he has
     scrolled up to read something. */
  function pin(force) {
    if (!msgs) return;
    if (force || atBottom()) msgs.scrollTop = msgs.scrollHeight;
  }
  function append(node, wasAtBottom) {
    if (!msgs) return node;
    msgs.appendChild(node);
    if (wasAtBottom !== false) pin(true);
    return node;
  }

  function msg(cls, who, text) {
    var was = atBottom();
    var m = el('div', cls);
    m.appendChild(el('div', 'who', who));
    m.appendChild(doc.createTextNode(text == null ? '' : String(text)));
    return append(m, was);
  }

  function card(cls, who) {
    var was = atBottom();
    var c = el('div', cls);
    c.appendChild(el('div', 'who', who));
    return append(c, was);
  }

  function line(parent, text, cls) {
    var d = el('div', cls, text);
    parent.appendChild(d);
    return d;
  }

  function button(label, cls, fn) {
    var b = el('button', 'btn' + (cls ? ' ' + cls : ''), label);
    b.addEventListener('click', fn);
    return b;
  }

  /* Long replies stay digestible — clamp, with a way to see it all. */
  function clampLongMessages(scope) {
    (scope || doc).querySelectorAll('.msgs .msg').forEach(function (m) {
      if (m.dataset.clamped || m.classList.contains('clamped')) return;
      if (m.scrollHeight < 380) return;
      m.dataset.clamped = '1';
      /* Wrap the content in .body so the CSS clamp has something to clamp —
         the bare class clamped nothing (inert since birth). */
      var bodyWrap = el('div', 'body');
      while (m.firstChild) bodyWrap.appendChild(m.firstChild);
      m.appendChild(bodyWrap);
      m.classList.add('clamped');
      var b = el('button', 'showall', 'show all');
      b.addEventListener('click', function () {
        m.classList.remove('clamped');
        b.remove();
      });
      m.appendChild(b);
    });
  }

  // ── the turn ──────────────────────────────────────────────────────────────
  function renderTurn(j) {
    if (j && j.turn_blocked && j.blocked) {
      var b = j.blocked;
      var bm = card('msg steward blocked', '⛔ ' + STEWARD + ' — turn blocked');
      /* The seat call already ran and was billed. Withholding its text turned a
         bookkeeping refusal into "the steward ignored me". */
      if (b.held_say) line(bm, String(b.held_say), 'bheld');
      line(bm, (b.finding || 'E1-TURN-CLOSE-BLOCKED')
        + ' · a direct question lacks a typed answer-reference', 'bfind');
      (b.unanswered || []).forEach(function (q) {
        var r = line(bm, '“' + (q.text || '') + '” ', 'bq');
        r.appendChild(el('span', 'bqid', q.question_id || ''));
      });
      return;
    }

    var say = j && (j.say || j.message || j.user_text);
    var code = j && (j.code || j.status_code || j.error);

    if (code === 'CONVERSE_NO_ENVELOPE' || code === 'CONVERSE_BUDGET_REACHED') {
      var dc = card('decision', STEWARD + ' — needs your go-ahead');
      line(dc, say || 'Talking to the steward costs a model call.');
      var acts = el('div', 'act');
      var spend = function (label, route) {
        return button(label, 'gold', function () {
          var busy = line(dc, 'confirming…');
          post(route, { project_id: PID, who: 'john' }).then(function (k) {
            busy.textContent = (k && k.ok)
              ? 'confirmed — say it again and it will run.'
              : ((k && k.message) || 'that did not take — try again.');
          }).catch(function () { busy.textContent = 'that did not take — try again.'; });
        });
      };
      acts.appendChild(spend('Yes — spend on this session', '/api/ecgberht/envelope_confirm'));
      if (code === 'CONVERSE_BUDGET_REACHED') {
        acts.appendChild(spend('Raise it and carry on', '/api/ecgberht/envelope_raise'));
      }
      dc.appendChild(acts);
      return;
    }

    if (say) { msg('msg steward', STEWARD, say); clampLongMessages(); }

    var asks = (j && Array.isArray(j.asks)) ? j.asks.filter(Boolean) : [];
    if (asks.length) {
      var ac = card('decision', 'needs your answer');
      asks.forEach(function (a) { line(ac, String(a)); });
    }

    /* A proposed scaffolding. Nothing is written until he confirms, and the
       confirm binds the proposal hash — what lands is what he read. */
    var p = j && j.proposal;
    var stages = p && (p.stages || p.steps);
    if (Array.isArray(stages)) {
      var pc = card('decision', 'proposed scaffolding — nothing written yet');
      if (p.goal) line(pc, String(p.goal), 'pgoal');
      stages.forEach(function (s, i) {
        var row = line(pc, (i + 1) + '. ' + String(s.name || s.id || 'a stage'), 'pstage');
        if (s.done_when) line(row, 'done when: ' + String(s.done_when), 'pdone');
        if (Array.isArray(s.oranges) && s.oranges.length) {
          line(row, 'watch: ' + s.oranges.join(' · '), 'porange');
        }
      });
      var fs = (j.foresight || p.foresight);
      if (Array.isArray(fs) && fs.length) line(pc, 'later: ' + fs.join(' · '), 'porange');
      var pacts = el('div', 'act');
      pacts.appendChild(button('Confirm — make this the roadmap', 'gold', function () {
        var busy = line(pc, 'writing…');
        post('/api/ecgberht/scaffold_confirm', {
          project_id: PID, who: 'john',
          proposal_hash: j.proposal_hash || '', stages: stages
        }).then(function (k) {
          if (k && k.ok) {
            busy.textContent = 'written — the flow on the left is the campaign now.';
            reloadRail();
          } else {
            busy.textContent = (k && k.message) || 'not written — nothing changed.';
          }
        }).catch(function () { busy.textContent = 'not written — nothing changed.'; });
      }));
      pacts.appendChild(button('Keep talking', '', function () {
        line(pc, 'left as a draft — say what should change.');
      }));
      pc.appendChild(pacts);
    }

    if (j && j.wants_commission) {
      var cc = card('decision', 'wants to run ' + String(j.commission_skill || 'a skill'));
      if (j.commission_directive) line(cc, String(j.commission_directive));
      var cacts = el('div', 'act');
      cacts.appendChild(button('Go', 'pri', function () {
        /* (2026-08-15) THE CLASH WARNING. Seals share ONE flow rail and ONE
           run queue. Commissioning from a second seal while a run is live is
           the known collision — the engine will refuse or queue it, but the
           honest moment to say so is BEFORE the click spends anything. */
        if (RUN_LIVE && EFFORT !== 'campaign') {
          if (!window.confirm('A run is already live in this project, and '
              + 'seals share one flow rail and one run queue. Starting '
              + 'another run now can collide (the engine may refuse it). '
              + 'Talking is always safe. Start this run anyway?')) return;
        }
        var busy = line(cc, 'proposing…');
        post('/api/ecgberht/commission_propose', {
          project_id: PID, skill: j.commission_skill || null
        }).then(function (k) {
          if (!k || !k.ok || !k.proposal) {
            busy.textContent = (k && k.message) || 'could not propose that run.';
            return;
          }
          busy.textContent = 'launching…';
          return post('/api/ecgberht/commission_go', { project_id: PID, proposal: k.proposal })
            .then(function (g) {
              busy.textContent = (g && g.ok)
                ? 'running — watch the ⏱ line below.'
                : ((g && g.message) || 'could not start it.');
              if (g && g.ok) { pollPulse(); reloadRail(); }
            });
        }).catch(function () { busy.textContent = 'could not start it.'; });
      }));
      cc.appendChild(cacts);
    }

    if (!say && !Array.isArray(stages) && !(j && j.wants_commission)) {
      var why = (j && (j.message || j.error))
        ? String(j.message || j.error)
        : (STEWARD + " didn't answer — nothing was saved.");
      if (why === 'unauthorized') {
        why = 'This browser has no Anchor token, so the steward refused the '
          + 'call. Open the ⋯ menu → "Set the Anchor token…", then say it again.';
      }
      msg('msg steward', STEWARD, why);
    }
  }

  // ── saying something ──────────────────────────────────────────────────────
  var TURNS = [];

  function say() {
    var input = $('[data-say-input]');
    if (!input || SAYING) return;      // one turn at a time - Enter twice in a
    var text = (input.value || '').trim();   // 60-162s window = two debits
    if (!text) return;
    input.value = '';
    SAYING = true;
    input.disabled = true;
    var sayBtn = $('[data-say-send]');
    if (sayBtn) sayBtn.disabled = true;
    msg('msg john', 'You', text);
    TURNS.push({ role: 'john', text: text });

    /* A turn is measured at 60-162s and the bridge bound is 240s. A frozen
       "Thinking…" for four minutes is indistinguishable from a hang. */
    var think = msg('msg steward', STEWARD, 'Thinking… 0s');
    var t0 = Date.now();
    var clock = setInterval(function () {
      var n = think.lastChild;
      if (n && n.nodeType === 3) {
        n.nodeValue = 'Thinking… ' + Math.round((Date.now() - t0) / 1000) + 's';
      }
    }, 1000);

    post('/api/ecgberht/converse', { project_id: PID, text: text,
                                     effort_id: EFFORT, turns: TURNS.slice(0, -1) })
      .then(function (j) {
        clearInterval(clock); think.remove(); _sayDone(input);
        if (j && j.say) TURNS.push({ role: 'steward', text: String(j.say) });
        renderTurn(j);
      })
      .catch(function () {
        clearInterval(clock); think.remove(); _sayDone(input);
        msg('msg steward', STEWARD, STEWARD + " didn't answer — nothing was saved.");
      });
  }

  function _sayDone(input) {
    SAYING = false;
    if (input) { input.disabled = false; input.focus(); }
    var sayBtn = $('[data-say-send]');
    if (sayBtn) sayBtn.disabled = false;
  }

  // ── the rail ──────────────────────────────────────────────────────────────
  function closeDrawers() {
    doc.querySelectorAll('.stepdrawer').forEach(function (d) { d.remove(); });
  }

  function openStep(stepEl, stepId, stepName) {
    var existing = stepEl.nextElementSibling;
    if (existing && existing.classList.contains('stepdrawer')) { existing.remove(); return; }
    closeDrawers();
    var d = el('div', 'stepdrawer');
    line(d, 'reading the step…', 'v');   // never opens empty
    stepEl.parentNode.insertBefore(d, stepEl.nextSibling);

    get('/api/ecgberht/step_detail?project_id=' + encodeURIComponent(PID)
        + '&step_id=' + encodeURIComponent(stepId) + tq())
      .then(function (j) {
        d.textContent = '';
        var s = (j && (j.detail || j.step)) || j || {};
        var rows = [
          ['intent', s.intent || s.done_when || s.goal],
          ['status', s.status || s.state],
          ['skill', s.skill || s.step_type],
          ['what ran', s.ran || s.run_summary],
          ['findings', Array.isArray(s.findings) ? s.findings.join(' · ') : s.findings],
          ['yield', s.yield || s.outcome]
        ];
        var any = false;
        rows.forEach(function (r) {
          if (!r[1]) return;
          any = true;
          line(d, r[0], 'k');
          line(d, String(r[1]), 'v');
        });
        if (!any) {
          line(d, (j && j.ok === false && (j.message || j.error))
            ? String(j.message || j.error)
            : 'Nothing has been recorded against this step yet.', 'v');
        }
        line(d, 'add a note — it lands on the step', 'k');
        var ta = doc.createElement('textarea');
        ta.placeholder = 'what this step should account for…';
        d.appendChild(ta);
        var acts = el('div', 'acts');
        var save = button('Save note', 'gold', function () {
          var txt = (ta.value || '').trim();
          if (!txt) return;
          save.disabled = true; save.textContent = 'saving…';
          post('/api/ecgberht/step_note', { project_id: PID, step_id: stepId, note: txt })
            .then(function (k) {
              save.disabled = false;
              save.textContent = (k && k.ok) ? 'saved ✓' : 'not saved — try again';
              if (k && k.ok) ta.value = '';
            })
            .catch(function () { save.disabled = false; save.textContent = 'not saved — try again'; });
        });
        acts.appendChild(save);
        acts.appendChild(button('Talk about this step', '', function () {
          var input = $('[data-say-input]');
          if (input) {
            input.value = 'About "' + (stepName || stepId) + '": ';
            input.focus();
          }
        }));
        d.appendChild(acts);
      })
      .catch(function () {
        d.textContent = '';
        line(d, 'Could not read that step just now — the rest of the chamber is fine.', 'v');
      });
  }

  function reloadRail() {
    setTimeout(function () { location.reload(); }, 400);  // server re-renders
  }

  // ── the ⏱ strip: the 10-minute status ─────────────────────────────────────
  var strip = $('.cstrip');

  function setStrip(cls, text, more) {
    if (!strip) return;
    strip.className = 'cstrip ' + cls;
    strip.textContent = '';
    strip.appendChild(el('span', 'livedot', cls === 'live' ? '⏱'
      : (cls === 'needs' ? '⚑' : '—')));
    strip.appendChild(el('span', 'stxt', text));
    if (more) {
      strip.appendChild(el('span', 'sp'));
      strip.appendChild(el('span', 'more', more));
    }
  }

  /* run_pulse needs a session_id, so the runs list comes first — it is also
     what tells us a run WANTS him, which is the state that matters most. */
  function pollPulse() {
    get('/api/ecgberht/commission_runs?project_id=' + encodeURIComponent(PID) + tq())
      .then(function (j) {
        if (!j || !j.ok) return;
        var runs = j.runs || [];
        /* commission_runs sends `outcome`, never `status` — reading .status
           made liveness collapse to the watcher list, so after a restart a
           stranded running record read as "idle" while the rail said live
           (correctness audit P0-2). outcome running + a live watcher = LIVE;
           outcome running with NO watcher = stranded = wants him. */
        var wants = null, live = null;
        runs.forEach(function (r) {
          var o = String(r.outcome || '').toLowerCase();
          var watched = (j.watching || []).indexOf(r.session_id) >= 0;
          if (o === 'running' && watched) { if (!live) live = r; return; }
          if (!wants && (r.raised || o === 'asked' || o === 'died'
                         || o === 'quiet' || o === 'timeout'
                         || (o === 'running' && !watched))) wants = r;
        });
        RUN_LIVE = !!live;
        if (wants) {
          var o2 = String(wants.outcome || '').toLowerCase();
          setStrip('needs', 'needs you · ' + (wants.skill || 'a run') + ' · '
            + (o2 === 'asked' ? 'it asked you something'
               : (o2 === 'running' ? 'left running with no watcher — needs a look'
                  : (o2 || 'it stopped and wants a decision'))), 'ask about it ›');
          return;
        }
        if (!live) { setStrip('idle', 'idle · no step running'); return; }
        setStrip('live', (live.skill || 'a run') + ' running · reading its status…',
                 'status ›');
        return get('/api/ecgberht/run_pulse?project_id=' + encodeURIComponent(PID)
                   + '&session_id=' + encodeURIComponent(live.session_id || '') + tq())
          .then(function (p) {
            if (!p || !p.ok) return;
            var slot = p.step_slot || p.slot || p;
            var latest = String(slot.latest_status || slot.status_block
                                || p.latest_status || '').trim();
            var head = latest ? latest.split('\n')[0].slice(0, 150) : '';
            setStrip('live', head
              ? ((live.skill || 'a run') + ' · ' + head)
              : ((live.skill || 'a run') + ' running · started '
                 + (live.at || slot.started_at || 'recently')
                 + ' · first ⏱ within 10m'), 'status ›');
          })
          .catch(function () { /* keep the honest "running" line */ });
      })
      .catch(function () { /* the strip keeps its last honest value */ });
  }

  // ── the ⋯ menu ────────────────────────────────────────────────────────────
  function toggleMenu(btn) {
    var open = $('.pmenu');
    if (open) { open.remove(); return; }
    var m = el('div', 'pmenu');
    var link = function (href, label) {
      var a = el('a', null, label);
      a.href = href;
      a.target = href.indexOf('http') === 0 ? '_blank' : '_self';
      return a;
    };
    /* (2026-08-15, John) The classic-cockpit link is gone from the menu —
       "that's just not necessary anymore". The ?classic=1 URL itself stays
       (the dashboard iframe and the classic tests ride it). */
    m.appendChild(link('/mockup' + tq1(), 'The signed M1 drawing'));
    m.appendChild(el('div', 'sep'));
    m.appendChild(link('/', 'Back to the High Seat'));
    var tokBtn = el('button', null, 'Set the Anchor token…');
    tokBtn.addEventListener('click', function () {
      var t = prompt('Anchor access token for this origin:', token());
      if (t === null) return;
      try {
        if (t.trim()) localStorage.setItem('anchor_token', t.trim());
        else localStorage.removeItem('anchor_token');
      } catch (e) { /* private mode */ }
      location.reload();
    });
    m.appendChild(tokBtn);
    m.appendChild(el('div', 'note', PID));
    doc.body.appendChild(m);
    setTimeout(function () {
      doc.addEventListener('click', function once(ev) {
        if (m.contains(ev.target) || ev.target === btn) return;
        m.remove();
        doc.removeEventListener('click', once);
      });
    }, 0);
  }

  // ── the STATUS overlay — the drawn one, rendered by the server ────────────
  /* John: "I thought the M1 dashboard had a status option — something that
     could pop up and show you the status, so I could get that 10-minute status
     update." It was built (chamber_status_overlay.py) and had no caller on
     this page. This is the caller. */
  function openStatusOverlay() {
    var old = $('.ovl');
    if (old) old.remove();
    var ovl = el('div', 'ovl');
    ovl.appendChild(el('div', 'wempty', 'reading the status…'));
    ovl.addEventListener('click', function (ev) {
      if (ev.target === ovl || (ev.target.getAttribute
          && ev.target.getAttribute('data-overlay-close') !== null)) ovl.remove();
    });
    doc.body.appendChild(ovl);
    get('/api/ecgberht/status_overlay?project_id=' + encodeURIComponent(PID) + tq())
      .then(function (j) {
        ovl.textContent = '';
        if (j && j.ok && j.html) {
          /* Server-rendered and server-escaped (F5): the ONE innerHTML on this
             page, carrying markup this page did not author. */
          ovl.innerHTML = j.html;
        } else {
          var b = el('div', 'wempty', (j && (j.message || j.error))
            ? String(j.message || j.error)
            : 'No status to show yet — nothing has run on this campaign.');
          ovl.appendChild(b);
        }
      })
      .catch(function () {
        ovl.textContent = '';
        ovl.appendChild(el('div', 'wempty', 'Could not read the status.'));
      });
  }

  // ── refresh: recompute what the page draws from the ledger on disk ────────
  function refreshCampaign(btn) {
    var label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'refreshing…';
    post('/api/ecgberht/refresh', { project_id: PID })
      .then(function (j) {
        if (j && j.ok) { location.reload(); return; }
        btn.disabled = false;
        btn.textContent = (j && j.message) ? 'refresh failed' : label;
      })
      .catch(function () { btn.disabled = false; btn.textContent = 'refresh failed'; });
  }

  // ── the workbench ─────────────────────────────────────────────────────────
  var wb = $('#workbench'), wbody = $('#wbody'), wterm = null;

  function wempty(text) {
    wbody.textContent = '';
    wbody.appendChild(el('div', 'wempty', text));
  }

  /* Timestamps arrive as ISO strings from some endpoints and as Unix floats
     from others (gandalf.py writes `ts` as a float). Calling .slice on a
     number threw inside the render and the whole panel fell into its catch,
     reporting "could not read" about an index that had answered perfectly. */
  function when(v) {
    if (v == null || v === '') return '';
    /* LOCAL time, never toISOString — a session he started at 6:30 PM was
       labelling its tile "00:30 tomorrow", which reads as someone else's run. */
    var d = typeof v === 'number' ? new Date(v * 1000) : new Date(String(v));
    if (isNaN(d.getTime())) return String(v).slice(0, 16).replace('T', ' ');
    var z = function (n) { return (n < 10 ? '0' : '') + n; };
    return d.getFullYear() + '-' + z(d.getMonth() + 1) + '-' + z(d.getDate())
      + ' ' + z(d.getHours()) + ':' + z(d.getMinutes());
  }

  function wrow(kind, text, whenText, href, hrefLabel) {
    var r = el('div', 'wrow');
    if (kind) r.appendChild(el('span', 'k', kind));
    r.appendChild(el('span', 't', text));
    if (whenText) r.appendChild(el('span', 'when', whenText));
    if (href) {
      var a = el('a', null, hrefLabel || 'open');
      a.href = href + (href.indexOf('?') >= 0 ? '' : tq1());
      a.target = '_blank';
      r.appendChild(a);
    }
    return r;
  }

  /* A markdown artifact, RENDERED — the server's Reader page (?render=1).
     Raw text is never shown to a human. */
  function _mdUrl(rel) {
    return '/artifact/' + encodeURIComponent(PID)
      + '?path=' + encodeURIComponent(rel) + '&render=1'
      + (tq() ? '&' + tq().slice(1) : '');
  }

  /* Open a rendered document IN the bottom panel (an iframe onto the server's
     Reader page — no client-side markdown, no innerHTML of agent text). */
  function showDoc(rel, title) {
    if (GPOLL) { clearInterval(GPOLL); GPOLL = null; }  // never yank the doc
    wbody.className = 'wbody';
    wbody.textContent = '';
    var head = el('div', 'whead');
    head.appendChild(button('← back', '', function () { loadGandalf(); }));
    head.appendChild(el('span', 'wtitle', title || 'document'));
    head.appendChild(el('span', 'sp'));
    var a = el('a', null, 'open in its own window ▸');
    a.href = _mdUrl(rel);
    a.target = '_blank';
    head.appendChild(a);
    wbody.appendChild(head);
    var fr = doc.createElement('iframe');
    fr.className = 'docframe';
    fr.src = _mdUrl(rel);
    wbody.appendChild(fr);
  }

  var GPOLL = null;

  function openTab(key, btn) {
    doc.querySelectorAll('.wtab').forEach(function (b) { b.classList.remove('on'); });
    if (btn) btn.classList.add('on');
    wb.classList.add('open');
    wbody.className = 'wbody' + (key === 'terminal' ? ' term' : '');
    if (key !== 'terminal' && wterm) { closeTerm(); }
    if (key !== 'gandalf' && GPOLL) { clearInterval(GPOLL); GPOLL = null; }
    if (key === 'terminal') return loadTerminal();
    if (key === 'gandalf') return loadGandalf();
    if (key === 'files') return loadFiles();
    if (key === 'boneyard') return loadBoneyard();
  }

  function closeWorkbench() {
    wb.classList.remove('open');
    wbody.className = 'wbody';   // a lingering .term class kept the panel open
    doc.querySelectorAll('.wtab').forEach(function (b) { b.classList.remove('on'); });
    closeTerm();
    if (GPOLL) { clearInterval(GPOLL); GPOLL = null; }
    wbody.textContent = '';
  }

  /* ── Gandalf: the read is a PARAGRAPH, not a chip ─────────────────────────
     (2026-08-15, John) "It should not just give a one line — a proper summary
     you can scroll, then the option for the report… and a re-run button."
     The verdict IS the human-facing English summary of the whole project;
     truncating it to a table row threw away the one thing worth reading. */
  function loadGandalf() {
    wempty('reading Gandalf…');
    get('/api/rnd/gandalf?project_id=' + encodeURIComponent(PID) + tq())
      .then(function (j) {
        var runs = (j && (j.runs || j.reads)) || [];
        wbody.textContent = '';
        var head = el('div', 'whead');
        head.appendChild(el('span', 'wtitle', 'Gandalf — deep reads of this project'));
        head.appendChild(el('span', 'sp'));
        var runBtn = button('Run Gandalf again', 'gold', function () {
          runBtn.disabled = true;
          runBtn.textContent = 'starting…';
          post('/api/rnd/gandalf_run', { project_id: PID })
            .then(function (k) {
              runBtn.textContent = (k && k.ok)
                ? 'running — a read takes minutes; this list updates itself'
                : ((k && k.message) || 'could not start the read');
              if (k && k.ok && !GPOLL) {
                GPOLL = setInterval(function () {
                  if (wbody.className.indexOf('term') < 0
                      && wb.classList.contains('open')) loadGandalf();
                }, 20000);
              }
            })
            .catch(function () {
              runBtn.disabled = false;
              runBtn.textContent = 'could not start the read';
            });
        });
        head.appendChild(runBtn);
        wbody.appendChild(head);
        if (!runs.length) {
          wbody.appendChild(el('div', 'wempty',
            'No Gandalf read on this project yet — run one above.'));
          return;
        }
        runs.slice(0, 20).forEach(function (r) {
          var c = el('div', 'gcard');
          var top = el('div', 'gtop');
          top.appendChild(el('span', 'k',
            r.in_progress ? 'running' :
            (r.ok === false ? 'error' : (r.cross_model ? 'cross-model' : 'read'))));
          if (r.degraded) top.appendChild(el('span', 'k', 'degraded'));
          top.appendChild(el('span', 'when', when(r.ts)));
          top.appendChild(el('span', 'sp'));
          /* (2026-08-15, John) Everything human-presentable: both are MD, both
             render as Reader pages (?render=1), never raw text. The executive
             summary opens HERE in the bottom panel; the full report in its own
             window. The third artifact (the agent-facing advisor packet) is
             dropped — "it didn't seem very useful" — it is machine food. */
          if (r.exec_rel) {
            top.appendChild(button('summary', 'bare blue', (function (rel) {
              return function () { showDoc(rel, 'Executive summary'); };
            })(r.exec_rel)));
          }
          if (r.report_rel) {
            var a = el('a', null, 'report ▸');
            a.href = _mdUrl(r.report_rel);
            a.target = '_blank';
            top.appendChild(a);
          }
          c.appendChild(top);
          c.appendChild(el('div', 'gverdict',
            r.in_progress ? 'The read is running — the verdict lands here when it grades.'
            : (r.verdict || r.reason || '(no verdict recorded)')));
          wbody.appendChild(c);
        });
      })
      .catch(function () { wempty('Could not read the Gandalf index.'); });
  }

  /* ── Files: an explorer, not a dump ───────────────────────────────────────
     (2026-08-15, John) "Like Windows Explorer — name, type, size, date, sort
     by any of those, a search bar, and if there's folders you open the folder
     and go into it." The API already navigates (?path=) — this is the view. */
  var FILES = { path: '', sort: 'name', asc: true, q: '' };

  function fsize(n) {
    if (n == null) return '';
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  function ftype(name) {
    var i = name.lastIndexOf('.');
    return i > 0 ? name.slice(i + 1).toLowerCase() : '';
  }

  function loadFiles() {
    wempty('reading files…');
    get('/api/rnd/project_files?project_id=' + encodeURIComponent(PID)
        + '&path=' + encodeURIComponent(FILES.path) + tq())
      .then(function (j) {
        if (!j || !j.ok) { wempty((j && j.error) || 'Could not list the files.'); return; }
        wbody.textContent = '';
        var head = el('div', 'whead');
        var up = button('↑ up', '', function () {
          var parts = FILES.path.split('/').filter(Boolean);
          parts.pop();
          FILES.path = parts.join('/');
          loadFiles();
        });
        up.disabled = !FILES.path;
        head.appendChild(up);
        head.appendChild(el('span', 'fcrumb', '/' + (FILES.path || '')));
        var box = doc.createElement('input');
        box.placeholder = 'filter this folder…';
        box.value = FILES.q;
        box.addEventListener('input', function () {
          FILES.q = box.value;
          renderRows();
        });
        head.appendChild(box);
        wbody.appendChild(head);

        var table = el('div', 'ftable');
        wbody.appendChild(table);

        var dirs = (j.dirs || []).map(function (d) {
          var nm = d.split('/').pop();
          return { name: nm, path: d, dir: true, size: null, mtime: null, type: 'folder' };
        });
        var files = (j.files || []).map(function (f) {
          return { name: f.name, path: f.path, dir: false, size: f.size,
                   mtime: f.mtime, type: ftype(f.name) };
        });

        function renderRows() {
          table.textContent = '';
          var hdr = el('div', 'frow fhdr');
          [['name', 'Name'], ['type', 'Type'], ['size', 'Size'],
           ['mtime', 'Modified']].forEach(function (col) {
            var h = el('span', 'fc fc-' + col[0],
              col[1] + (FILES.sort === col[0] ? (FILES.asc ? ' ▲' : ' ▼') : ''));
            h.addEventListener('click', function () {
              if (FILES.sort === col[0]) FILES.asc = !FILES.asc;
              else { FILES.sort = col[0]; FILES.asc = col[0] === 'name'; }
              renderRows();
            });
            hdr.appendChild(h);
          });
          table.appendChild(hdr);

          var q = FILES.q.trim().toLowerCase();
          var rows = dirs.concat(files).filter(function (r) {
            return !q || r.name.toLowerCase().indexOf(q) >= 0;
          });
          rows.sort(function (a, b) {
            if (a.dir !== b.dir) return a.dir ? -1 : 1;   // folders first, always
            var k = FILES.sort, va = a[k], vb = b[k];
            if (va == null) va = k === 'name' || k === 'type' ? '' : -1;
            if (vb == null) vb = k === 'name' || k === 'type' ? '' : -1;
            if (typeof va === 'string') { va = va.toLowerCase(); vb = String(vb).toLowerCase(); }
            var c = va < vb ? -1 : (va > vb ? 1 : 0);
            return FILES.asc ? c : -c;
          });
          if (!rows.length) {
            table.appendChild(el('div', 'wempty', q ? 'Nothing here matches that.'
                                                    : 'This folder is empty.'));
            return;
          }
          rows.slice(0, 400).forEach(function (r) {
            var row = el('div', 'frow' + (r.dir ? ' fdir' : ''));
            row.appendChild(el('span', 'fc fc-name', (r.dir ? '🗀 ' : '') + r.name));
            row.appendChild(el('span', 'fc fc-type', r.dir ? 'folder' : r.type));
            row.appendChild(el('span', 'fc fc-size', r.dir ? '' : fsize(r.size)));
            row.appendChild(el('span', 'fc fc-mtime', r.dir ? '' : when(r.mtime)));
            if (r.dir) {
              row.addEventListener('click', function () {
                FILES.path = r.path;
                FILES.q = '';
                loadFiles();
              });
            } else {
              row.addEventListener('click', function () {
                window.open('/artifact/' + encodeURIComponent(PID)
                  + '?path=' + encodeURIComponent(r.path)
                  + (tq() ? '&' + tq().slice(1) : ''), '_blank');
              });
            }
            table.appendChild(row);
          });
        }
        renderRows();
        setTimeout(function () { box.focus(); }, 0);
      })
      .catch(function () { wempty('Could not list the files.'); });
  }

  function loadBoneyard(q) {
    wbody.textContent = '';
    var head = el('div', 'whead');
    var box = doc.createElement('input');
    box.placeholder = 'search the boneyard…';
    box.value = q || '';
    box.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); loadBoneyard(box.value); }
    });
    head.appendChild(box);
    wbody.appendChild(head);
    var list = el('div');
    wbody.appendChild(list);
    list.appendChild(el('div', 'wempty', 'reading…'));
    get('/api/rnd/boneyard?project_id=' + encodeURIComponent(PID)
        + (q ? '&q=' + encodeURIComponent(q) : '') + tq())
      .then(function (j) {
        var rows = (j && (j.entries || j.items)) || [];
        list.textContent = '';
        if (!rows.length) {
          list.appendChild(el('div', 'wempty', q
            ? 'Nothing in the boneyard matches that.'
            : 'Nothing discarded on this project yet.'));
          return;
        }
        rows.slice(0, 60).forEach(function (e) {
          list.appendChild(wrow(e.source || 'discarded',
            e.title || e.idea || e.session_id || 'an entry',
            when(e.at || e.ts),
            (e.docs && e.docs[0])
              ? ('/artifact/' + encodeURIComponent(PID) + '?path='
                 + encodeURIComponent(e.docs[0])) : null, 'open'));
        });
      })
      .catch(function () {
        list.textContent = '';
        list.appendChild(el('div', 'wempty', 'Could not read the boneyard.'));
      });
    setTimeout(function () { box.focus(); }, 0);
  }

  /* A bare general session, in this project, that he drives himself — his
     words: "open terminal and just sit in that project, use the terminal
     instead of using the steward." */
  var WS_CTL = '\x00ANCHOR-CTL:';

  function closeTerm() {
    if (!wterm) return;
    try { if (wterm.ws) wterm.ws.close(); } catch (e) {}
    try { if (wterm.term) wterm.term.dispose(); } catch (e) {}
    wterm = null;
  }

  /* (2026-08-15, John) "Little tiles that say previous terminal runs — it
     automatically saves, and you can restart it, archive it, or boneyard it."
     The registry already saves every session; this surfaces them. The old
     behavior started a NEW session (a fresh git worktree) on every tab open,
     which was both slow and exactly the opposite of "it saves". */

  function loadTerminal() {
    wbody.textContent = '';
    var bar = el('div', 'termbar');
    var strip = el('div', 'tstrip');
    var host = el('div', 'termhost');
    wbody.appendChild(bar);
    wbody.appendChild(strip);
    wbody.appendChild(host);
    refreshTermBar(bar, host, true, strip);
  }

  /* Search across previous runs: filters the tiles by their label AND the
     summary text fetched for each — type, and only matching runs remain. */
  function _tstripFilter(strip, q) {
    q = (q || '').trim().toLowerCase();
    var any = false;
    strip.querySelectorAll('.ttile').forEach(function (tile) {
      var hay = (tile.dataset.hay || '').toLowerCase();
      var hit = !q || hay.indexOf(q) >= 0;
      tile.style.display = hit ? '' : 'none';
      if (hit) any = true;
    });
    var miss = strip.querySelector('.tmiss');
    if (!any) {
      if (!miss) strip.appendChild(el('span', 'tmiss',
        'no previous run matches that'));
    } else if (miss) { miss.remove(); }
  }

  function termNote(host, text) {
    host.textContent = '';
    host.appendChild(el('div', 'wempty', text));
  }

  function termCounting(host, what) {
    termNote(host, what + ' — it cuts a git worktree first, ~10s… 0s');
    var t0 = Date.now();
    var tick = setInterval(function () {
      var n = host.querySelector('.wempty');
      if (!n) { clearInterval(tick); return; }
      n.textContent = what + ' — it cuts a git worktree first, ~10s… '
        + Math.round((Date.now() - t0) / 1000) + 's';
    }, 1000);
    return function () { clearInterval(tick); };
  }

  function refreshTermBar(bar, host, autoAttach, strip) {
    strip = strip || wbody.querySelector('.tstrip');
    bar.textContent = '';
    if (strip) strip.textContent = '';

    bar.appendChild(el('span', 'wtitle', 'previous runs'));
    var search = doc.createElement('input');
    search.className = 'tsearch';
    search.placeholder = 'search previous runs…';
    search.addEventListener('input', function () {
      if (strip) _tstripFilter(strip, search.value);
    });
    bar.appendChild(search);
    bar.appendChild(el('span', 'sp'));
    bar.appendChild(button('＋ New terminal', 'gold', function () {
      termStartNew(host, bar);
    }));

    get('/api/rnd/term_sessions?project_id=' + encodeURIComponent(PID) + tq())
      .then(function (j) {
        var rows = ((j && (j.sessions || j.records)) || [])
          .filter(function (r) { return r.lane === 'general'; })
          .sort(function (a, b) { return (b.created_at || 0) - (a.created_at || 0); });
        var running = rows.filter(function (r) { return r.status === 'running'; });

        /* The strip scrolls SIDEWAYS — a long history slides off to the right
           and the scrollbar brings the older ones back, instead of the tiles
           wrapping and eating the terminal. */
        rows.slice(0, 60).forEach(function (r) {
          var isRun = r.status === 'running';
          var t = el('div', 'ttile ' + (isRun ? 'run' : (r.status || 'idle')));
          t.dataset.hay = (r.label || '') + ' ' + when(r.created_at);

          var l1 = el('div', 'tl1');
          l1.appendChild(el('span', 'lt'));
          l1.appendChild(el('span', 'twhen', when(r.created_at)));
          l1.appendChild(el('span', 'sp'));
          if (isRun) {
            l1.appendChild(button('⏸', 'bare', function (ev) {
              ev.stopPropagation();
              post('/api/rnd/term_close', { project_id: PID, session: r.session_id })
                .then(function () {
                  if (wterm && wterm.sid === r.session_id) closeTerm();
                  refreshTermBar(bar, host, false, strip);
                  termNote(host, 'parked — it stays on a tile, reopenable warm.');
                })
                .catch(function () { /* the tile keeps its state */ });
            })).title = 'Archive — park it; docs persist, reopenable warm';
          }
          l1.appendChild(button('🪦', 'bare', function (ev) {
            ev.stopPropagation();
            if (!window.confirm('Boneyard this run? What it produced is kept '
                                + 'and searchable in the Boneyard; the session '
                                + 'itself is done.')) return;
            post('/api/rnd/term_kill',
                 { project_id: PID, session: r.session_id, confirm: true })
              .then(function () {
                if (wterm && wterm.sid === r.session_id) closeTerm();
                refreshTermBar(bar, host, false, strip);
              })
              .catch(function () { /* the tile keeps its state */ });
          })).title = 'Boneyard — done with it; its ideas stay searchable';
          t.appendChild(l1);

          var blurb = el('div', 'tblurb',
            isRun ? 'running now' : (r.label || 'summary loading…'));
          t.appendChild(blurb);

          t.title = isRun ? 'Attach to this live session'
            : 'Resume — a new session opens warm from this one';
          t.addEventListener('click', function () {
            if (isRun) { termConnect(r.session_id, host); }
            else { termResume(r.session_id, host, bar); }
          });
          if (strip) strip.appendChild(t);

          /* What was this run ABOUT? The cached session summary fills the
             tile's second line; the hover tooltip carries the fuller text.
             Cache-only read — never a model call from a tile. */
          get('/api/rnd/session_summary?pid=' + encodeURIComponent(PID)
              + '&lane=general&session=' + encodeURIComponent(r.session_id)
              + '&cache_only=1' + tq())
            .then(function (s) {
              if (!s || s.status !== 'ready' || !s.summary) {
                if (!isRun && !r.label) blurb.textContent = 'no summary yet';
                return;
              }
              var sm = s.summary;
              var short = sm.what_was_asked || sm.title
                || (Array.isArray(sm.claims) && sm.claims[0]) || '';
              if (short) blurb.textContent = String(short);
              var longer = [sm.what_was_asked, sm.title]
                .concat(Array.isArray(sm.actions) ? sm.actions.slice(0, 4) : [])
                .filter(Boolean).join('\n');
              if (longer) t.title = longer + '\n\n' + t.title;
              t.dataset.hay += ' ' + short + ' ' + longer;
              if (search.value) _tstripFilter(strip, search.value);
            })
            .catch(function () { /* the date-only tile is still honest */ });
        });

        if (!rows.length && strip) {
          strip.appendChild(el('span', 'tmiss',
            'no terminal runs yet in this project'));
        }

        if (autoAttach && running.length) {
          termConnect(running[0].session_id, host);
        } else if (autoAttach) {
          termNote(host, rows.length
            ? 'No session running — click a tile to resume it warm, or start new.'
            : 'No terminal runs yet in this project — start one.');
        }
      })
      .catch(function () {
        if (strip) strip.appendChild(el('span', 'tmiss',
          'could not list previous runs'));
      });
  }

  function termConnect(sid, host) {
    if (!window.Terminal) { termNote(host, 'the terminal component did not load'); return; }
    if (wterm && wterm.sid === sid) return;      // already attached
    closeTerm();
    host.textContent = '';
    var term = new window.Terminal({ convertEol: true, fontSize: 12,
                                     theme: { background: '#0c0e14' },
                                     scrollback: 5000 });
    term.open(host);
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var ws = new WebSocket(proto + '//' + location.host
      + '/api/rnd/term_ws?session=' + encodeURIComponent(sid) + tq() + '&since=0');
    wterm = { ws: ws, term: term, sid: sid };
    ws.onmessage = function (ev) {
      var d = ev.data;
      if (typeof d === 'string' && d.indexOf(WS_CTL) === 0) return;  // control
      term.write(d);
    };
    ws.onclose = function () { term.write('\r\n[session closed]\r\n'); };
    term.onData(function (d) {
      try { ws.send(d); } catch (e) { /* transport gone */ }
    });
    setTimeout(function () { term.focus(); }, 50);
  }

  function termStartNew(host, bar) {
    var stop = termCounting(host, 'starting a session');
    post('/api/rnd/term_start', { project_id: PID, lane: 'general' })
      .then(function (j) {
        stop();
        var sid = j && ((j.session && j.session.session_id) || j.session_id
                        || (j.record && j.record.session_id));
        if (!j || !j.ok || !sid) {
          termNote(host, (j && (j.message || j.error)) || 'could not start a session');
          return;
        }
        termConnect(sid, host);
        refreshTermBar(bar, host, false);
      })
      .catch(function () { stop(); termNote(host, 'could not start a session'); });
  }

  function termResume(sid, host, bar) {
    var stop = termCounting(host, 'resuming warm from that session');
    post('/api/rnd/continue_session',
         { project_id: PID, session: sid, lane: 'general' })
      .then(function (j) {
        stop();
        var nid = j && j.session && j.session.session_id;
        if (!j || !j.ok || !nid) {
          termNote(host, (j && (j.message || j.error)) || 'could not resume it');
          return;
        }
        termConnect(nid, host);
        refreshTermBar(bar, host, false);
      })
      .catch(function () { stop(); termNote(host, 'could not resume it'); });
  }

  // ── one delegation for the whole page ─────────────────────────────────────
  doc.addEventListener('click', function (ev) {
    var t = ev.target;
    if (!t || !t.closest) return;

    if (t.closest('[data-say-send]')) { ev.preventDefault(); say(); return; }
    if (t.closest('[data-page-menu]')) { ev.preventDefault(); toggleMenu(t); return; }

    var fold = t.closest('[data-unfold]');
    if (fold) {
      ev.preventDefault();
      var hidden = $('.folded');
      if (hidden) {
        var top0 = msgs ? msgs.scrollHeight - msgs.scrollTop : 0;
        hidden.hidden = false;
        fold.parentNode.remove();
        if (msgs) msgs.scrollTop = msgs.scrollHeight - top0;   // hold his place
        clampLongMessages();
      }
      return;
    }

    /* The North Star buttons are real: they put the ask in the say line rather
       than pretending to open an editor that does not exist yet. */
    if (t.closest('[data-refine-overlay]')) {
      ev.preventDefault();
      var input = $('[data-say-input]');
      if (input) {
        /* (2026-08-16, John) "It says goal instead of plan — that's a flaw
           in that button." One data-attribute serves two drawn buttons:
           [Refine it] on the North Star line and [Refine the plan] on the
           rail. The prefill now matches which one was pressed. */
        var isPlan = !!t.closest('aside.flow');
        input.value = input.value
          || (isPlan ? 'The plan should change: ' : 'The goal should be: ');
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
      return;
    }

    if (t.closest('.cstrip') || t.closest('[data-status-overlay]')) {
      ev.preventDefault(); openStatusOverlay(); return;
    }

    /* The drawn [Still the goal]: an affirmation is a turn like any other —
       it goes in the say line for HIM to send, never auto-spent. */
    if (t.closest('[data-still-plan]')) {
      ev.preventDefault();
      var sp = $('[data-say-input]');
      if (sp) {
        sp.value = 'Still the plan — carry on.';
        sp.focus();
        sp.setSelectionRange(sp.value.length, sp.value.length);
      }
      return;
    }
    if (t.closest('[data-still-goal]')) {
      ev.preventDefault();
      var sg = $('[data-say-input]');
      if (sg) {
        sg.value = 'Still the goal — carry on.';
        sg.focus();
        sg.setSelectionRange(sg.value.length, sg.value.length);
      }
      return;
    }

    var rb = t.closest('[data-refresh]');
    if (rb) { ev.preventDefault(); refreshCampaign(rb); return; }

    /* (2026-08-16, John) "A button to know what's going on and update it —
       scan the steward files, and if the effort went outside the steward's
       purview, update the record based on what it's doing." One REAL steward
       turn through the normal paid path: the reply and any proposed roadmap
       updates render as the usual cards, and Confirm writes them through the
       spine. If the seat cannot see the files, it says so and the terminal
       catch-up is the honest next step. */
    if (t.closest('[data-catch-up]')) {
      ev.preventDefault();
      if (SAYING) return;
      var ci = $('[data-say-input]');
      if (!ci) return;
      ci.value = 'Catch up — the record is behind reality. Work has been '
        + 'happening outside this chamber (files and sessions in the project '
        + 'folder; the roadmap has not moved in days). From what you can see: '
        + 'which roadmap steps are actually done or underway, what new work '
        + 'exists that the plan never covered, and propose the roadmap '
        + 'updates that make the record match reality. If you cannot see the '
        + 'project files from this seat, say so plainly and I will run the '
        + 'catch-up in a terminal session instead.';
      say();
      return;
    }

    /* The degraded rail's Rebuild — the guaranteed first screen on a fresh
       project, and until now a drawn button with NO handler. Same recompute
       as the bar's refresh. */
    var rbd = t.closest('[data-rebuild-command]');
    if (rbd) { ev.preventDefault(); refreshCampaign(rbd); return; }

    var wt = t.closest('[data-wtab]');
    if (wt) {
      ev.preventDefault();
      if (wt.classList.contains('on')) { closeWorkbench(); }
      else { openTab(wt.getAttribute('data-wtab'), wt); }
      return;
    }
    if (t.closest('[data-wclose]')) { ev.preventDefault(); closeWorkbench(); return; }

    /* ── the seal strip ──────────────────────────────────────────────────── */
    var effNew = t.closest('[data-effort-new]');
    if (effNew) {
      ev.preventDefault();
      var nm = window.prompt('What is this effort about? (one line — it names '
                             + 'the tile)');
      if (nm === null) return;
      if (RUN_LIVE) {
        window.alert('Heads up: a run is live in this project. A new seal is '
          + 'its own conversation — safe — but seals share one flow rail and '
          + 'one run queue, so hold off commissioning from it until the '
          + 'current run lands.');
      }
      post('/api/ecgberht/effort_act', { project_id: PID, act: 'create',
                                         name: nm || '' })
        .then(function (k) {
          if (k && k.ok) location.reload();     // server renders the new seal
          else window.alert((k && (k.message || k.error)) || 'could not create it');
        })
        .catch(function () { window.alert('could not create it'); });
      return;
    }
    var effTile = t.closest('[data-effort]');
    if (effTile) {
      ev.preventDefault();
      var eid = effTile.getAttribute('data-effort');
      if (eid === EFFORT) return;               // already open
      if (SAYING) {
        window.alert('A turn is in flight — switching seals now reloads the '
          + 'page and its reply would vanish from view. Wait for the answer.');
        return;
      }
      post('/api/ecgberht/effort_act', { project_id: PID, act: 'focus',
                                         effort_id: eid })
        .then(function (k) {
          if (k && k.ok) location.reload();     // thread + strip re-render
        })
        .catch(function () { /* the strip keeps its state */ });
      return;
    }

    var step = t.closest('[data-step]');
    if (step) {
      ev.preventDefault();
      var nm = step.querySelector('.nm');
      openStep(step, step.getAttribute('data-step'),
               nm ? nm.textContent.trim() : '');
    }
  });

  doc.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && ev.target && ev.target.matches
        && ev.target.matches('[data-say-input]')) {
      ev.preventDefault();
      say();
    }
  });

  // ── the page notices a redeploy and reloads itself ────────────────────────
  /* (2026-08-15, John: "you have promised me so many times that updated code is
     available once I restart and it is not there".) The cockpit had this and
     the chamber page did not, so an open chamber never learned the server had
     restarted. Paired with the build-id fix (it now fingerprints the code on
     disk instead of the last commit), a restart makes every open page reload
     itself — the promise becomes a mechanism instead of an instruction. */
  function watchForRedeploy() {
    var mine = window.ANCHOR_BUILD || null;
    if (!mine) return;
    var reloadKey = 'anchor_chamber_reloaded_for';
    setInterval(function () {
      get('/api/version').then(function (d) {
        var v = d && d.version;
        if (!v || v === mine) return;
        /* Never reload out from under him: a turn in flight, a half-typed
           message, or an attached terminal defers to the next quiet tick. */
        var typing = $('[data-say-input]');
        if (SAYING || wterm || (typing && typing.value.trim())) return;
        try {                      // never reload twice for one server build
          if (sessionStorage.getItem(reloadKey) === String(v)) return;
          sessionStorage.setItem(reloadKey, String(v));
        } catch (e) { /* private mode — one extra reload is survivable */ }
        location.reload();
      }).catch(function () { /* server down mid-restart; try again next tick */ });
    }, 10000);
  }

  // ── boot ──────────────────────────────────────────────────────────────────
  watchForRedeploy();
  pin(true);                 // open on the newest turn, always
  clampLongMessages();
  pollPulse();
  setInterval(pollPulse, 15000);
  var input0 = $('[data-say-input]');
  if (input0) input0.focus();
})();
