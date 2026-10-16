/* The Cave of Wonders' Terminal (2026-10-02, his word: the Workbench "seems old and not very useful ... we'll replace it
   with just simply a terminal ... choose which engine ... it will open to dev ... more than one terminal opened, kind of
   like VS Code ... it just doesn't have the steward skill running in it ... at the bottom of the Cave of Wonders so it
   doesn't open a new window").
   Tabs of plain engine terminals at the foot of the board: + Terminal starts one (POST /api/cave/terminal, the engine
   from the picker - the Terminal seat by default), each tab is an xterm on the session's own WebSocket (term_ws), sized
   to its box (term_resize); × ends it (term_kill). A reload re-attaches every terminal still running
   (GET /api/cave/terminals), so the page's own renewal never waits on one. */
(function () {
  'use strict';
  var $ = function (s) { return document.querySelector(s); };
  var dock = $('#termDock'), tabs = $('#termTabs'), body = $('#termBody'), btn = $('#termNew'), eng = $('#termEngine');
  if (!dock || !tabs || !body || !btn) return;
  var CTL = '\x00ANCHOR-CTL:';
  var NAMES = { claude: 'Claude', chatgpt: 'ChatGPT', grok: 'Grok', gemini: 'Gemini', shell: 'Shell' };
  var open = {}, order = [], current = null;

  function token() { try { return localStorage.getItem('anchor_token') || ''; } catch (e) { return ''; } }
  function headers() {
    var h = { 'Content-Type': 'application/json' }, t = token();
    if (t) { h['X-Anchor-Token'] = t; h['Authorization'] = 'Bearer ' + t; }
    return h;
  }
  function count() {
    var n = order.length, c = $('#termCount'), r = $('#railTerm');
    if (c) c.textContent = n ? (n + ' open') : 'none open';
    if (r) r.textContent = String(n);
    dock.hidden = !n;
  }
  function note(text, bad) {
    var c = $('#termCount'); if (!c) return;
    c.textContent = text; c.classList.toggle('bad', !!bad);
    setTimeout(function () { c.classList.remove('bad'); count(); }, bad ? 6000 : 2500);
  }
  // the cell size xterm actually renders, else a measure of the font; the box's own size gives cols x rows
  function fit(t) {
    if (!t || !t.host || t.host.offsetParent === null) return;
    var w = 0, h = 0;
    try { var d = t.term._core._renderService.dimensions; w = d.css.cell.width; h = d.css.cell.height; } catch (e) {}
    if (!w || !h) { w = 7.8; h = 17; }
    var cols = Math.max(20, Math.floor((t.host.clientWidth - 14) / w)), rows = Math.max(5, Math.floor((t.host.clientHeight - 6) / h));
    if (cols === t.term.cols && rows === t.term.rows) return;
    try { t.term.resize(cols, rows); } catch (e) {}
  }
  function post(path, data) {
    return fetch(path, { method: 'POST', headers: headers(), body: JSON.stringify(data) }).then(function (r) { return r.json().catch(function () { return {}; }); });
  }
  function show(sid) {
    current = sid;
    order.forEach(function (k) {
      var t = open[k]; t.tab.classList.toggle('on', k === sid); t.tab.setAttribute('aria-selected', k === sid ? 'true' : 'false');
      t.host.hidden = k !== sid;
    });
    var t = open[sid]; if (!t) return;
    setTimeout(function () { fit(t); try { t.term.focus(); } catch (e) {} }, 30);
  }
  function attach(s) {
    if (!window.Terminal) { note('the terminal component did not load', true); return; }
    if (open[s.session_id]) { show(s.session_id); return; }
    var host = document.createElement('div'); host.className = 'termhost'; body.appendChild(host);
    var tab = document.createElement('div'); tab.className = 'ttab'; tab.setAttribute('role', 'tab');
    tab.innerHTML = '<span class="tn"></span><button class="tx" title="end this terminal" aria-label="end this terminal">&times;</button>';
    tab.querySelector('.tn').textContent = (s.label || 'Terminal') + ' · ' + (NAMES[s.backend] || s.backend || '');
    tabs.appendChild(tab);
    var term = new window.Terminal({ convertEol: false, fontSize: 13, scrollback: 8000, cursorBlink: true,
      fontFamily: '"Cascadia Mono", Consolas, "Courier New", monospace', theme: { background: '#0a0c11' } });
    term.open(host);
    var t = { sid: s.session_id, term: term, host: host, tab: tab, ws: null };
    open[s.session_id] = t; order.push(s.session_id);
    term.onResize(function (sz) { post('/api/rnd/term_resize', { session: t.sid, cols: sz.cols, rows: sz.rows }); });
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:', tk = token();
    var ws = new WebSocket(proto + '//' + location.host + '/api/rnd/term_ws?session=' + encodeURIComponent(t.sid)
      + (tk ? '&token=' + encodeURIComponent(tk) : '') + '&since=0');
    t.ws = ws;
    ws.onmessage = function (ev) { var d = ev.data; if (typeof d === 'string' && d.indexOf(CTL) === 0) return; term.write(d); };
    ws.onclose = function () { if (open[t.sid]) term.write('\r\n\x1b[2m[the connection closed - reload the page to re-attach; × ends the terminal]\x1b[0m\r\n'); };
    term.onData(function (d) { try { ws.send(d); } catch (e) {} });
    tab.addEventListener('click', function (e) { if (e.target.closest('.tx')) return; show(t.sid); });
    tab.querySelector('.tx').addEventListener('click', function () { end(t.sid); });
    count(); show(t.sid);
  }
  function end(sid) {
    var t = open[sid]; if (!t) return;
    if (!window.confirm('End ' + t.tab.querySelector('.tn').textContent + '? The agent in it stops.')) return;
    post('/api/rnd/term_kill', { session: sid }).catch(function () {});
    try { t.ws && t.ws.close(); } catch (e) {}
    try { t.term.dispose(); } catch (e) {}
    t.host.remove(); t.tab.remove();
    delete open[sid]; order = order.filter(function (k) { return k !== sid; });
    count();
    if (order.length) show(order[order.length - 1]);
  }
  btn.addEventListener('click', function () {
    var backend = (eng && eng.value) || '';
    btn.disabled = true; note('starting ' + (NAMES[backend] || backend) + '…');
    post('/api/cave/terminal', { backend: backend }).then(function (j) {
      btn.disabled = false;
      if (!j || !j.ok || !j.session) { note('did not start: ' + ((j && j.error) || 'no answer'), true); return; }
      attach(j.session);
      try { dock.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (e) {}
    }).catch(function () { btn.disabled = false; note('did not start - the server did not answer', true); });
  });
  window.addEventListener('resize', function () { if (current) fit(open[current]); });
  // the box can be dragged taller; the terminal follows it
  if (window.ResizeObserver) new ResizeObserver(function () { if (current) fit(open[current]); }).observe(body);
  // a reload re-attaches every terminal still running
  fetch('/api/cave/terminals', { headers: headers() }).then(function (r) { return r.json(); })
    .then(function (j) { ((j && j.sessions) || []).forEach(attach); })
    .catch(function () {});
  count();
})();
