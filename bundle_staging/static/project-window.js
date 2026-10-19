
// ════════════════════════════════════════════════════════════════════════════
// v4.1 "Project Cockpit" — Paradigm-2 (inline expanding panels). The ONLY
// terminal surface is the inline panel inside #panelStack (openPanel). There is
// NO console drawer, NO live-terminals bar, NO loose cost-rollup / deliverables
// section — those v3 leftovers were removed. Plain RAW string (single braces).
// ════════════════════════════════════════════════════════════════════════════

// ── Global 401 auto-reprompt (self-service token) ───────────────────────────
// A fresh origin (e.g. a laptop on the tailnet IP) has no token in this origin's
// localStorage, so every token-gated read-API GET returns 401 and the dynamic
// panels come up EMPTY. Wrap window.fetch so a 401 (when auth is on, and not
// already prompting) re-prompts for the token and reloads — every read then
// retries with the new token via the existing ?token=/X-Anchor-Token senders.
// Non-401 responses pass through UNCHANGED (the body/stream is never touched).
(function () {
  if (window.__anchorFetchWrapped) return;
  window.__anchorFetchWrapped = true;
  var _origFetch = window.fetch.bind(window);
  var prompting = false;
  window.fetch = function () {
    return _origFetch.apply(null, arguments).then(function (resp) {
      if (resp && resp.status === 401 && window.ANCHOR_AUTH_REQUIRED && !prompting) {
        prompting = true;
        try {
          if (setAnchorToken()) { location.reload(); }
        } finally {
          prompting = false;
        }
      }
      // W2 contract shim: a structured 409 build-mismatch means THIS tab was
      // loaded before a deploy — render the 'reload required' banner. The body
      // is read off a CLONE so the caller's own .json() still works.
      if (resp && resp.status === 409) {
        try {
          resp.clone().json().then(function (d) {
            if (d && d.error === 'build-mismatch') _showReloadBanner();
          }).catch(function () {});
        } catch (e) {}
      }
      return resp;
    });
  };
})();

// ── W2 contract shim: the 'reload required' banner ─────────────────────────
// Shown when any POST answers the structured 409 build-mismatch (this tab is
// from a pre-deploy build). Idempotent; fixed to the top of the viewport; one
// click reloads onto the new build.
function _showReloadBanner() {
  if (document.getElementById('anchorReloadBanner')) return;
  var d = document.createElement('div');
  d.id = 'anchorReloadBanner';
  d.setAttribute('role', 'alert');
  d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;' +
    'background:#b45309;color:#fff;padding:10px 16px;text-align:center;' +
    'font:600 14px/1.4 system-ui,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.4)';
  d.innerHTML = 'Anchor was updated — this page is out of date. ' +
    '<button onclick="location.reload()" style="margin-left:10px;padding:4px 12px;' +
    'border:1px solid #fff;border-radius:6px;background:transparent;color:#fff;' +
    'cursor:pointer;font:inherit">Reload</button>';
  (document.body || document.documentElement).appendChild(d);
}

function _esc(s) {
  // FULL HTML escaping (defense-in-depth). Escapes &, <, > AND BOTH quote chars
  // (" -> &quot;, ' -> &#39;) so output is safe inside double- OR single-quoted
  // attributes — not just text nodes. (Pre-v10-W7-fix this escaped only & < >,
  // which let a title/value containing a double-quote break out of a
  // data-title="..." attribute → stored DOM XSS in the Boneyard live search.)
  // Verified safe for every _esc(...) caller in _PROJECT_WINDOW_JS: each puts the
  // result into HTML text content or a quoted attribute, never a JS-string/URL
  // context where &quot;/&#39; would render literally wrong.
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ── v12 Wave 2: Layout-D collapsible shelf toggle ──────────────────────────
// Folds/unfolds a zone's "older sessions" shelf of little tiles. Toggles the
// .collapsed class (machine-checkable) on the shelf wrapper and updates the
// "▾ Hide N / ▸ Show all N" caption. Static-skeleton interaction only; the live
// effort-view wiring + the bottom dock arrive in W10.
function toggleShelf(id, btnId, n, label) {
  var el = document.getElementById(id);
  if (!el) return;
  var collapsed = el.classList.toggle('collapsed');
  var btn = btnId ? document.getElementById(btnId) : null;
  if (btn) {
    btn.textContent = collapsed
      ? ('▸ Show all ' + n + ' older ' + label + ' sessions')
      : ('▾ Hide ' + n + ' older ' + label + ' sessions');
  }
}

// Collapse / expand the right-column Grass Catcher idea list IN THE TILE (the open
// items fold away; +capture / Open-workbench stay reachable). Default expanded.
function toggleGrassMini(el) {
  var list = document.getElementById('grassMiniList');
  if (!list) return;
  var collapsed = list.classList.toggle('collapsed');
  if (el) el.innerHTML = collapsed ? '&#9656;' : '&#9662;';  // ▸ / ▾
}

// John tweak: collapse / expand the right-column Gandalf run list IN THE HEADER
// (mirrors toggleGrassMini). The list starts COLLAPSED on first load so the
// dashboard is minimal; clicking the header caret shows/hides the run history.
function toggleGandalfRuns(el) {
  var list = document.getElementById('gandalfRuns');
  if (!list) return;
  var collapsed = list.classList.toggle('collapsed');
  if (el) el.innerHTML = collapsed ? '&#9656;' : '&#9662;';  // ▸ / ▾
}

// ── Access token (D4) ──────────────────────────────────────────────────────
// The shared-secret token is kept ONLY in this browser's localStorage and sent
// as X-Anchor-Token on mutating POSTs. It is NEVER embedded in the served HTML
// (GET is unauthenticated, so embedding would leak it to anyone who can reach
// the page). When ANCHOR_TOKEN is unset on the server, auth is disabled and the
// header is simply ignored, so local use needs no token.
function _anchorToken() { try { return localStorage.getItem('anchor_token') || ''; } catch (e) { return ''; } }
function setAnchorToken() {
  var cur = _anchorToken();
  var t = window.prompt('Paste your Anchor access token:', cur);
  if (t === null) return false;            // user cancelled
  try { if (t) { localStorage.setItem('anchor_token', t.trim()); } else { localStorage.removeItem('anchor_token'); } } catch (e) {}
  return true;
}
// W9 cookie navigation: prime the HttpOnly auth cookie from this browser's
// localStorage token so page navigation (/project/, /report/, /summary/,
// /artifact/, /api/rnd/projects …) authenticates off the cookie under
// ANCHOR_AUTH_MODE=enforce — no shared-secret token ever rides in a page URL.
// The POST carries the token via the X-Anchor-Token header (_postJson); the
// server Set-Cookies it. Best-effort + idempotent (safe to call every load).
function primeAuthCookie() {
  try {
    var t = _anchorToken();
    if (!window.ANCHOR_AUTH_REQUIRED || !t) return;
    _postJson('/api/auth/login', {}).catch(function () {});
  } catch (e) {}
}
// On first load: ask for a token once if required, then sync MANAGED from the
// session registry so a tile for an already-running terminal can re-open its
// inline panel.
window.addEventListener('DOMContentLoaded', function () {
  if (window.ANCHOR_AUTH_REQUIRED && !_anchorToken()) { setAnchorToken(); }
  primeAuthCookie();   // W9: set the cookie so page navigation works under enforce
  repopulate();
  try { initGandalfPanelCollapse(); } catch(e){}
  // v8 Wave 3: render the GitHub link / auto-push header controls from the
  // current remote_status (read-only GET; never a model call / network).
  try { renderRemoteControls(); } catch (e) {}
  // v10 Wave 4 FIX 2/3: resolve the board-tile "from grass" chips (label +
  // dead-state) once the grass data is loaded (read-only GET). Best-effort.
  try {
    _loadGrassData().then(function () {
      try { _resolveGrassOriginChips(document); } catch (e) {}
    });
  } catch (e) {}
});
function _postJson(url, payload) {
  var headers = {'Content-Type': 'application/json'};
  var tok = _anchorToken();
  if (tok) headers['X-Anchor-Token'] = tok;
  // W2 contract shim: declare this page's build id on EVERY mutating POST so a
  // stale tab (loaded before a deploy) gets the structured 409 → the 'reload
  // required' banner — never an opaque failure. Absent on old cached HTML that
  // carries no ANCHOR_BOOT (the server never blocks a build-less request).
  var bid = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) || '';
  if (bid) headers['X-Anchor-Build'] = bid;
  return fetch(url, { method: 'POST', headers: headers, body: JSON.stringify(payload) });
}
function _isUnauthorized(r, data) { return r.status === 401 || (data && data.error === 'unauthorized'); }

// ── v8 Wave 3 — GitHub link + Option-A auto-push (header controls) ───────────
// renderRemoteControls(): fetch the project's current remote_status (read-only,
// token-gated GET) and paint the #ghRemote header span. Unlinked → a single
// "Link GitHub" button. Linked → the remote host/name + an auto-push opt-in
// checkbox (set_auto_push) + a "Push now" button (push_now). NO network here —
// this is a pure registry read. Never throws into the page (best-effort).
async function renderRemoteControls() {
  var host = document.getElementById('ghRemote');
  if (!host) return;
  var st = null;
  try {
    var url = '/api/rnd/remote_status?project_id=' +
      encodeURIComponent(PROJECT_ID) + _tokenQ();
    var r = await fetch(url, _jsonHdrs());
    st = await r.json();
  } catch (e) { st = null; }
  if (!st || !st.ok) {
    // Unknown state → still offer the link control (best-effort).
    host.innerHTML = "<button class='rnd-mini' id='ghLinkBtn' " +
      "onclick='linkGithub()'>&#128279; Link GitHub</button>";
    return;
  }
  if (!st.linked) {
    host.innerHTML = "<button class='rnd-mini' id='ghLinkBtn' " +
      "onclick='linkGithub()'>&#128279; Link GitHub</button>";
    return;
  }
  // Linked: show a short remote label + the auto-push toggle + Push now.
  var label = _ghShortRemote(st.remote_url);
  var checked = st.auto_push ? ' checked' : '';
  host.innerHTML =
    "<span class='gh-linked' id='ghLinkedLabel' title='" + _esc(st.remote_url) +
      "'>&#128279; " + _esc(label) + "</span>" +
    "<label class='gh-autopush' title='Auto-push this project when a session " +
      "finishes'><input type='checkbox' id='ghAutoPush'" + checked +
      " onchange='toggleAutoPush(this.checked)'> auto-push</label>" +
    "<button class='rnd-mini' id='ghPushNowBtn' onclick='pushNow()'>" +
      "&#8593; Push now</button>";
}

// Trim a remote URL to a compact "owner/name" (or host/name) for the header.
function _ghShortRemote(u) {
  u = String(u || '');
  if (!u) return 'linked';
  var s = u.replace(/^https?:\/\//, '').replace(/^git@/, '')
           .replace(/\.git$/, '').replace(/:/g, '/');
  var parts = s.split('/').filter(function (p) { return p; });
  if (parts.length >= 2) return parts.slice(-2).join('/');
  return s;
}

// linkGithub(): inline prompt to link a GitHub remote. If gh is available we
// offer "Create new private repo" (mode=create) vs "Paste an existing URL"
// (mode=existing); when gh is unavailable we offer paste-only (the server also
// degrades create → {reason:'gh-unavailable', suggest:'paste-url'}).
async function linkGithub() {
  // Probe current state so we can decide whether to offer "create".
  var ghAvailable = true;
  try {
    var sr = await fetch('/api/rnd/remote_status?project_id=' +
      encodeURIComponent(PROJECT_ID) + _tokenQ(), _jsonHdrs());
    var sd = await sr.json();
    if (sd && typeof sd.gh_available === 'boolean') ghAvailable = sd.gh_available;
  } catch (e) {}
  var mode, value;
  if (ghAvailable) {
    var pick = window.prompt(
      'Link GitHub — type:\n  C = Create a new PRIVATE repo\n' +
      '  (or paste an existing repo URL)\n  (Cancel = not now)', 'C');
    if (pick === null) return;            // not now
    pick = (pick || '').trim();
    if (pick.toUpperCase() === 'C' || pick === '') {
      mode = 'create';
      var nm = window.prompt('New private repo name (blank = folder name):', '');
      if (nm === null) return;
      value = (nm || '').trim();
    } else {
      mode = 'existing';
      value = pick;
    }
  } else {
    // gh unavailable → paste-only.
    var url = window.prompt(
      'gh is unavailable — paste an existing GitHub repo URL to link:', '');
    if (url === null) return;
    url = (url || '').trim();
    if (!url) return;
    mode = 'existing';
    value = url;
  }
  var payload = {project_id: PROJECT_ID, mode: mode, value: value};
  var r, data;
  try {
    r = await _postJson('/api/rnd/link_github', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/link_github', payload);
      data = await r.json();
    }
  } catch (e) { alert('[link GitHub error] ' + e.message); return; }
  if (!data.ok) {
    if (data.reason === 'gh-unavailable') {
      // Fall back to paste-only on the spot.
      var url2 = window.prompt(
        'gh is unavailable — paste an existing GitHub repo URL to link:', '');
      if (url2 === null) return;
      url2 = (url2 || '').trim();
      if (!url2) return;
      var p2 = {project_id: PROJECT_ID, mode: 'existing', value: url2};
      var r2 = await _postJson('/api/rnd/link_github', p2);
      var d2 = await r2.json();
      if (!d2.ok) { alert('[link GitHub refused] ' + (d2.error || d2.reason || 'unknown')); return; }
    } else {
      alert('[link GitHub refused] ' + (data.error || data.reason || 'unknown'));
      return;
    }
  }
  renderRemoteControls();
}

// toggleAutoPush(on): persist the per-project auto-push opt-in (set_auto_push).
async function toggleAutoPush(on) {
  var payload = {project_id: PROJECT_ID, enabled: !!on};
  var r, data;
  try {
    r = await _postJson('/api/rnd/set_auto_push', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/set_auto_push', payload);
      data = await r.json();
    }
  } catch (e) { alert('[auto-push error] ' + e.message); return; }
  if (!data.ok) {
    alert('[auto-push refused] ' + (data.error || 'unknown'));
    renderRemoteControls();             // re-sync the checkbox to truth
  }
}

// pushNow(): manual "Push now" — git push -u origin <branch>. In tests origin is
// a LOCAL BARE repo (file://) so there is NO network. Reports the outcome.
async function pushNow() {
  var btn = document.getElementById('ghPushNowBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Pushing…'; }
  var payload = {project_id: PROJECT_ID};
  var r, data;
  try {
    r = await _postJson('/api/rnd/push_now', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/push_now', payload);
      data = await r.json();
    }
  } catch (e) {
    alert('[push error] ' + e.message);
    if (btn) { btn.disabled = false; btn.innerHTML = '&#8593; Push now'; }
    return;
  }
  if (btn) { btn.disabled = false; btn.innerHTML = '&#8593; Push now'; }
  if (!data.ok || !data.pushed) {
    alert('[push refused] ' + (data.error || data.reason || 'unknown'));
    return;
  }
}

// ── Grass Catchers content feeds (Wave 5) ───────────────────────────────────
// After a grass idea is added/promoted, refresh WITHOUT a full page reload. The
// old code called location.reload(), which tore down the client-only #grassPanel
// workbench — so adding an idea from inside the workbench "closed" it on the user
// (reported glitch). Instead: re-render the board in place (refreshBoard updates
// the hidden #grassWorkbenchTpl, which now carries the new idea), then, if the
// workbench is open, swap ONLY its left idea list (.glist) from the fresh
// template — leaving the right work pane (.gwork, which may host a LIVE grass dev
// terminal) fully intact — and re-wire the rows + counts.
async function _refreshAfterGrassMutation() {
  var wbOpen = !!document.getElementById('grassPanel');
  try { await refreshBoard(); } catch (e) {}
  if (!wbOpen) return;
  try {
    var panel = document.getElementById('grassPanel');
    var tpl = document.getElementById('grassWorkbenchTpl');
    if (!panel || !tpl) return;
    var freshList = tpl.querySelector('.glist');
    var curList = panel.querySelector('.glist');
    if (freshList && curList) {
      curList.innerHTML = freshList.innerHTML;
      // Re-wire the (new) rows: click selects the idea.
      var rows = curList.querySelectorAll('.gli');
      for (var k = 0; k < rows.length; k++) {
        rows[k].onclick = (function (row) {
          return function () { selectGrassIdea(row.getAttribute('data-idea')); };
        })(rows[k]);
      }
      _refreshGrassCounts(panel);
      filterGrass();                     // honor the active filter tab
    }
  } catch (e) { /* never throw into the UI */ }
}

// Manual add: prompt for idea text, POST /api/rnd/add_idea, then refresh so the
// new grass card renders. Token-aware via _postJson (retries once on 401).
async function addIdea() {
  var text = window.prompt('New idea for Grass Catchers:', '');
  if (text === null) return;            // cancelled
  text = (text || '').trim();
  if (!text) return;
  var payload = {project_id: PROJECT_ID, text: text};
  var r, data;
  try {
    r = await _postJson('/api/rnd/add_idea', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/add_idea', payload);
      data = await r.json();
    }
  } catch (e) { alert('[add idea error] ' + e.message); return; }
  if (!data.ok) { alert('[add idea refused] ' + (data.error || 'unknown')); return; }
  await _refreshAfterGrassMutation();
}

// Promote from INBOX: prompt for the inbox item text, POST /api/rnd/promote_inbox
// (copy-by-default — the inbox item is not removed), then refresh.
async function promoteInbox() {
  var text = window.prompt('Promote which INBOX item into Grass Catchers? (type the item text)', '');
  if (text === null) return;
  text = (text || '').trim();
  if (!text) return;
  var payload = {project_id: PROJECT_ID, text: text};
  var r, data;
  try {
    r = await _postJson('/api/rnd/promote_inbox', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/promote_inbox', payload);
      data = await r.json();
    }
  } catch (e) { alert('[promote inbox error] ' + e.message); return; }
  if (!data.ok) { alert('[promote inbox refused] ' + (data.error || 'unknown')); return; }
  await _refreshAfterGrassMutation();
}

// Promote a Grass Catcher idea into a NEW seeded session in a lane (Wave 6).
// POST /api/rnd/promote_grass {project_id, idea_id, lane} → the backend starts a
// session SEEDED with the idea text (reusing the Wave-1 seed path); we then
// register it in MANAGED and open its inline panel (reusing openPanel/repopulate).
// The idea REMAINS in grass (copy, never destroy).
async function promoteGrass(ideaId, lane) {
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, lane: lane,
                 backend: 'claude'};
  var r, data;
  try {
    r = await _postJson('/api/rnd/promote_grass', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/promote_grass', payload);
      data = await r.json();
    }
  } catch (e) { alert('[promote grass error] ' + e.message); return; }
  if (!data.ok || !data.session) {
    alert('[promote refused] ' + (data.error || data.reason || 'unknown'));
    return;
  }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {
    session_id: sid, lane: rec.lane || lane, backend: rec.backend || 'claude',
    status: rec.status || 'running', label: rec.label || '',
    idx: (_laneCounters[rec.lane || lane] = (_laneCounters[rec.lane || lane] || 0) + 1)
  };
  renderSessionBar();
  openPanel(sid);
  // v7 Wave 6: re-fetch the server-rendered board so the just-started session's
  // lane-column tile appears INSTANTLY (no page reload). The board is the single
  // source of truth — re-fetch, don't JS-inject — so dedupe stays correct.
  refreshBoard();
  // Re-sync indices/labels from the registry shortly after.
  setTimeout(repopulate, 600);
}

// ── v10 Wave 7 — Boneyard (per-project searchable discard list) ─────────────
// The header "Boneyard" button opens a FULL-WIDTH panel in #panelStack (cloned
// from #boneyardTpl, the server-rendered search box + entry list). Live search
// re-fetches GET /api/rnd/boneyard?q=<term> (so it exercises boneyard.search) and
// re-renders the list; each entry expands to its summary + doc links (opened via
// the safe /artifact route). Read-only — no mutation, no model call.
function _boneyardTokenQ() {
  var t = _anchorToken();
  return t ? ('&token=' + encodeURIComponent(t)) : '';
}

function openBoneyard() {
  var stack = document.getElementById('panelStack');
  var tpl = document.getElementById('boneyardTpl');
  if (!stack || !tpl) return;
  var existing = document.getElementById('boneyardPanel');
  if (existing) {
    if (existing.classList.contains('minimized')) existing.classList.remove('minimized');
    existing.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    return;
  }
  var panel = document.createElement('div');
  panel.className = 'panel';
  panel.id = 'boneyardPanel';
  var bar = document.createElement('div');
  bar.className = 'pbar';
  var title = document.createElement('span');
  title.className = 'ti';
  title.textContent = '☠ Boneyard — discarded material';
  var sp = document.createElement('span');
  sp.className = 'sp';
  var minBtn = document.createElement('button');
  minBtn.className = 'panelbtn min';
  minBtn.title = 'Minimize';
  minBtn.textContent = '–';
  minBtn.onclick = function (e) { e.stopPropagation(); panel.classList.add('minimized'); };
  var closeBtn = document.createElement('button');
  closeBtn.className = 'panelbtn close';
  closeBtn.title = 'Close';
  closeBtn.textContent = '×';
  closeBtn.onclick = function (e) { e.stopPropagation(); panel.remove(); };
  bar.appendChild(title); bar.appendChild(sp);
  bar.appendChild(minBtn); bar.appendChild(closeBtn);
  var pin = document.createElement('div');
  pin.className = 'pin';
  pin.innerHTML = tpl.innerHTML;        // clone the rendered boneyard markup
  panel.appendChild(bar); panel.appendChild(pin);
  stack.appendChild(panel);
  panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

// Build ONE entry's DOM from a server entry view (the SAFE projection + doc_links).
function _boneyardEntryHtml(e) {
  var src = e.source || '';
  var srcLbl = e.source_label || src || '';
  var title = e.title || '(untitled)';
  var body = ((e.summary_excerpt || '').trim()) || ((e.idea_text || '').trim());
  var excerpt = body ? body.split('\n')[0] : '';
  // Use the server-computed, LOCAL-tz when_display verbatim (the SAME string the
  // server initial render emits) so the displayed time is byte-identical across
  // the initial paint and this live-search re-render. (Pre-fix this re-formatted
  // e.when in UTC via toISOString → a ~tz-offset jump the instant a user searched.)
  var whenTxt = e.when_display || '';

  var laneChip = e.lane ? ('<span class="bylanechip">' + _esc(e.lane) + '</span>') : '';
  var whenChip = whenTxt ? ('<span class="bywhen">' + _esc(whenTxt) + '</span>') : '';
  var excHtml = excerpt ? ('<div class="byexc">' + _esc(excerpt) + '</div>') : '';
  var sumHtml = body
    ? ('<div class="bysum">' + _esc(body) + '</div>')
    : ('<div class="bysum dim">No summary captured.</div>');
  var docsInner = '';
  var links = e.doc_links || [];
  if (links.length) {
    for (var i = 0; i < links.length; i++) {
      docsInner += '<a class="bydoc" href="' + _esc(links[i].href)
        + '" target="anchor_report_window" rel="noopener">'
        + _esc(links[i].name) + '</a>';
    }
  } else {
    docsInner = '<span class="none">No documents.</span>';
  }
  var docsHtml = '<div class="bydocs"><div class="h">Documents</div>' + docsInner + '</div>';
  return '<div class="byentry" data-byentry="' + _esc(e.entry_id || '')
    + '" data-source="' + _esc(src) + '" data-title="' + _esc(title)
    + '" onclick="toggleBoneyardEntry(this)">'
    + '<div class="byhd"><span class="bybadge ' + _esc(src) + '">' + _esc(srcLbl)
    + '</span><div class="bymeta"><div class="bytitle">' + _esc(title) + '</div>'
    + excHtml + '</div>' + laneChip + whenChip + '<span class="bycar">&#9656;</span></div>'
    + '<div class="bybody" onclick="event.stopPropagation()">' + sumHtml + docsHtml + '</div>'
    + '</div>';
}

// Toggle one entry's expanded (summary + doc links) state.
function toggleBoneyardEntry(el) {
  if (!el) return;
  el.classList.toggle('open');
}

// Live search: re-fetch GET /api/rnd/boneyard?q=<term> (exercises boneyard.search)
// and re-render the list newest-first. Debounced lightly. An empty result shows
// the honest empty state (no fabricated rows).
var _boneyardSearchTimer = null;
function searchBoneyard() {
  if (_boneyardSearchTimer) clearTimeout(_boneyardSearchTimer);
  _boneyardSearchTimer = setTimeout(_doBoneyardSearch, 120);
}
async function _doBoneyardSearch() {
  var panel = document.getElementById('boneyardPanel');
  if (!panel) return;
  var box = panel.querySelector('#boneyardSearch');
  var list = panel.querySelector('#boneyardList');
  if (!list) return;
  var q = box ? (box.value || '').trim() : '';
  try {
    var r = await fetch('/api/rnd/boneyard?project_id=' + encodeURIComponent(PROJECT_ID)
                        + '&q=' + encodeURIComponent(q) + _boneyardTokenQ());
    var data = await r.json();
    if (!data || !data.ok) return;
    var entries = data.entries || [];
    if (!entries.length) {
      list.innerHTML = '<div class="byempty" data-byempty="1">'
        + (q ? 'No discarded material matches &ldquo;' + _esc(q) + '&rdquo;.'
             : 'Nothing discarded yet.') + '</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < entries.length; i++) html += _boneyardEntryHtml(entries[i]);
    list.innerHTML = html;
  } catch (e) { /* read-only; leave the current list on a transient error */ }
}

// ── Gandalf v1 Wave 3 — the white-wizard read panel ─────────────────────────
// The right-column Gandalf panel (ABOVE Grass) shows the project's Gandalf run
// history newest-first (rendered server-side from gandalf.list_runs — the index,
// never a model call). Three interactions live here:
//   * gandalfToggleRun(el)  — expand/collapse a run row; on first expand fetch
//                             the exec-summary via the traversal-safe /artifact
//                             route (data-exec-rel) and show it inline. An error
//                             run carries no exec-rel → no fetch, no dead link.
//   * gandalfRun(pid)       — POST /api/rnd/gandalf_run {project_id}; schedules a
//                             fresh run (token-aware _postJson). On {scheduled}
//                             we poll the read endpoint until a NEW run lands,
//                             then re-render the rows in place (no page bounce).
// Read-only render; only the explicit Re-run mutates (and only schedules).
//
// v13 Wave 1 — a tiny self-contained markdown→HTML renderer exposed as
// `marked.parse`. NO external library, NO CDN, NO compiled asset (honors
// Anchor's stdlib-only / vendored-assets-only rule); it mirrors
// report_viewer.markdown_to_html's feature set (#headings, **bold**, *italic*,
// `code`, fenced ``` blocks, - lists, [links](url)) and is XSS-safe — every text
// segment is HTML-escaped BEFORE inline formatting is applied. Used to render the
// Gandalf inline exec-summary as clean structured HTML instead of plain text.
var marked = (function () {
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function inline(t) {
    // t arrives ALREADY HTML-escaped; layer inline markdown on top.
    t = t.replace(/`([^`]+)`/g, function (m, c) { return '<code>' + c + '</code>'; });
    t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, '$1<em>$2</em>');
    t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="anchor_report_window" rel="noopener noreferrer">$1</a>');
    return t;
  }
  function parse(md) {
    var lines = String(md == null ? '' : md).split('\n');
    var out = [], i = 0, inCode = false, codeBuf = [], listOpen = false;
    function closeList() { if (listOpen) { out.push('</ul>'); listOpen = false; } }
    while (i < lines.length) {
      var line = lines[i], s = line.trim();
      if (s.indexOf('```') === 0) {
        if (inCode) {
          out.push('<pre><code>' + codeBuf.join('\n') + '</code></pre>');
          codeBuf = []; inCode = false;
        } else { closeList(); inCode = true; }
        i++; continue;
      }
      if (inCode) { codeBuf.push(esc(line)); i++; continue; }
      if (!s) { closeList(); i++; continue; }
      var h = s.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        closeList();
        var lv = h[1].length;
        out.push('<h' + lv + '>' + inline(esc(h[2])) + '</h' + lv + '>');
        i++; continue;
      }
      if (/^[-*+]\s+/.test(s)) {
        if (!listOpen) { out.push('<ul>'); listOpen = true; }
        out.push('<li>' + inline(esc(s.replace(/^[-*+]\s+/, ''))) + '</li>');
        i++; continue;
      }
      closeList();
      out.push('<p>' + inline(esc(s)) + '</p>');
      i++;
    }
    if (inCode) out.push('<pre><code>' + codeBuf.join('\n') + '</code></pre>');
    closeList();
    return out.join('\n');
  }
  return { parse: parse };
})();

function gandalfToggleRun(el) {
  if (!el) return;
  var open = el.classList.toggle('open');
  if (!open) return;
  var rel = el.getAttribute('data-exec-rel') || '';
  var host = el.querySelector('.gexec');
  if (!rel || !host) return;
  if (host.getAttribute('data-loaded') === '1') return;
  host.setAttribute('data-loaded', '1');
  host.textContent = 'Loading executive summary…';
  var href = '/artifact/' + encodeURIComponent(PROJECT_ID)
    + '?path=' + encodeURIComponent(rel);
  fetch(href, _jsonHdrs()).then(function (r) {
    if (!r.ok) throw new Error('artifact ' + r.status);
    return r.text();
  }).then(function (txt) {
    // v13 W1 — render the markdown exec-summary as clean HTML (structured
    // lists / bold) instead of dumping plain text.
    if (txt) {
      try { host.innerHTML = marked.parse(txt); }
      catch (e) { host.textContent = txt; }
    } else {
      host.textContent = '(empty executive summary)';
    }
  }).catch(function () {
    host.textContent = '(executive summary unavailable)';
  });
}

var _gandalfPolling = false;
function gandalfRun(pid, tier) {
  pid = pid || PROJECT_ID;
  // tier: 'standard' (regular, Opus reasoner) | 'heavy' (Gandalf-Heavy, Fable-5).
  tier = (tier === 'heavy') ? 'heavy' : 'standard';
  var btns = document.querySelectorAll('#gandalfPanel .gandalf-run');
  var runningLabel = (tier === 'heavy') ? 'Running Heavy...' : 'Running...';
  for (var i = 0; i < btns.length; i++) {
    btns[i].disabled = true;
    btns[i].setAttribute('data-og', btns[i].textContent);
    btns[i].textContent = runningLabel;
  }
  var before = _gandalfRunCount();
  _postJson('/api/rnd/gandalf_run', {project_id: pid, tier: tier}).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (data) {
      if (_isUnauthorized(r, data)) {
        if (setAnchorToken()) return gandalfRun(pid, tier);
        return;
      }
      if (!data || !data.ok) {
        _gandalfReenable(btns);
        return;
      }
      // Scheduled — poll the read endpoint until a new run appears, then refresh.
      _gandalfPollForNew(pid, before, btns, 0);
    });
  }).catch(function () { _gandalfReenable(btns); });
}

function _gandalfRunCount() {
  return document.querySelectorAll('#gandalfPanel .grun').length;
}
function _gandalfReenable(btns) {
  for (var i = 0; i < btns.length; i++) { 
    btns[i].disabled = false;
    var og = btns[i].getAttribute('data-og');
    if (og) btns[i].textContent = og;
  }
}
function _gandalfPollForNew(pid, before, btns, tries) {
  if (tries > 240) { _gandalfReenable(btns); return; } // up to 2 mins
  _gandalfPolling = true;
  fetch('/api/rnd/gandalf_status?project_id=' + encodeURIComponent(pid) + _tokenQ(),
        _jsonHdrs()).then(function (r) {
    return r.json();
  }).then(function (data) {
    var status = data && data.status;
    if (!status) {
      // Run finished. Fetch runs to update UI.
      fetch('/api/rnd/gandalf?project_id=' + encodeURIComponent(pid) + _tokenQ(),
            _jsonHdrs()).then(r => r.json()).then(gdata => {
        var runs = (gdata && gdata.runs) || [];
        _gandalfRenderRuns(runs);
        _gandalfPolling = false;
      }).catch(() => { _gandalfPolling = false; _gandalfReenable(btns); });
      return;
    }
    var dots = ".".repeat((tries % 3) + 1);
    for (var i = 0; i < btns.length; i++) {
        if (!btns[i].getAttribute('data-og')) btns[i].setAttribute('data-og', btns[i].textContent);
        btns[i].textContent = status + dots;
    }
    setTimeout(function () {
      _gandalfPollForNew(pid, before, btns, tries + 1);
    }, 500);
  }).catch(function () {
    setTimeout(function () {
      _gandalfPollForNew(pid, before, btns, tries + 1);
    }, 500);
  });
}

// Re-render the run rows in place from a list_runs payload (client mirror of the
// server-side _render_layoutd_gandalf_panel row markup).
function _gandalfRenderRuns(runs) {
  var host = document.getElementById('gandalfRuns');
  var panel = document.getElementById('gandalfPanel');
  if (!panel) return;
  // refresh the count chip + re-enable the buttons.
  var cnt = panel.querySelector('.gandalf-head .cnt');
  if (cnt) cnt.textContent = runs.length + ' read' + (runs.length === 1 ? '' : 's');
  var btns = panel.querySelectorAll('.gandalf-run');
  for (var b = 0; b < btns.length; b++) { btns[b].disabled = false; }
  if (!host) return;
  var html = '';
  for (var i = 0; i < runs.length; i++) html += _gandalfRunHtml(runs[i]);
  host.innerHTML = html;
  // Drop the "Clear failed" control if no failed rows remain after the refresh.
  if (!host.querySelectorAll('.grun.err-row').length) {
    var cf = panel.querySelector('.gandalf-clear-failed');
    if (cf && cf.parentNode) cf.parentNode.removeChild(cf);
  }
  // A Re-run was an explicit user action → reveal the (now refreshed) run list
  // and sync the header caret to the expanded glyph.
  host.classList.remove('collapsed');
  var tog = document.getElementById('gandalfRunsTog');
  if (tog) tog.innerHTML = '&#9662;';  // ▾
}

function _gandalfTs(ts) {
  if (ts == null) return '';
  try {
    var d = new Date(ts * 1000);
    if (isNaN(d.getTime())) return '';
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
      + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  } catch (e) { return ''; }
}

function _gandalfRunHtml(r) {
  r = r || {};
  var ok = !!r.ok;
  var runId = String(r.run_id || '');
  var ts = _gandalfTs(r.ts);
  var chips = '';
  if (!ok) {
    chips = '<span class="chip deg">Error</span>';
  } else {
    if (r.cross_model) {
      chips = '<span class="chip prom">Promising</span>';
    } else {
      chips = '<span class="chip spec">Speculative</span>'
        + '<span class="chip sf">single-family</span>';
    }
    if (r.degraded) chips += '<span class="chip deg">degraded</span>';
  }
  var vtxt, vcls;
  if (ok) {
    vtxt = _esc(r.verdict || '(no verdict)');
    vcls = 'verdict';
  } else {
    vtxt = 'Run did not complete &mdash; ' + _esc(r.reason || 'unknown');
    vcls = 'verdict err';
  }
  var links = '';
  if (ok && (r.report_rel || r.advisor_rel)) {
    var parts = '';
    if (r.report_rel) {
      // v13 W1 — &render=1 opens the rendered Reader page in the unified window.
      parts += '<a href="/artifact/' + encodeURIComponent(PROJECT_ID)
        + '?path=' + encodeURIComponent(r.report_rel) + '&render=1'
        + '" target="anchor_report_window" rel="noopener">&#128196; Full report</a>';
    }
    if (r.advisor_rel) {
      parts += '<a href="/artifact/' + encodeURIComponent(PROJECT_ID)
        + '?path=' + encodeURIComponent(r.advisor_rel)
        + '" target="anchor_report_window" rel="noopener">{ } raw JSON</a>';
    }
    links = '<div class="glinks">' + parts + '</div>';
  }
  // The (x) retire/archive control — mirrors the server-rendered .gretire span.
  var retire = '<span class="gretire" title="Retire / archive this run"'
    + ' onclick="gandalfArchiveRun(event, \'' + _esc(runId) + '\')">&times;</span>';
  // John tweak: an ERROR run is NOT expandable (no caret, no onclick, no body
  // box) — its reason already shows in the row line. OK runs keep the expand.
  if (!ok) {
    return '<div class="grun err-row" data-run="' + _esc(runId) + '">'
      + '<div class="grtop"><span class="' + vcls + '">' + vtxt + '</span>'
      + retire + '</div>'
      + '<div class="gmeta"><span class="gts">' + _esc(ts) + '</span>' + chips
      + '</div></div>';
  }
  var relAttr = (r.exec_rel)
    ? ' data-exec-rel="' + _esc(r.exec_rel) + '"' : '';
  return '<div class="grun" data-run="' + _esc(runId) + '"' + relAttr
    + ' onclick="gandalfToggleRun(this)">'
    + '<div class="grtop"><span class="gcaret">&#9656;</span>'
    + '<span class="' + vcls + '">' + vtxt + '</span>' + retire + '</div>'
    + '<div class="gmeta"><span class="gts">' + _esc(ts) + '</span>' + chips
    + '</div>'
    + '<div class="gbody" onclick="event.stopPropagation()">'
    + '<div class="gexec"></div>' + links + '</div></div>';
}

// Retire/archive ONE run: POST /api/rnd/gandalf_archive {project_id, run_id};
// on success remove the tile from the view (no page bounce). stopPropagation so
// the click never toggles the row open.
function gandalfArchiveRun(ev, runId) {
  if (ev) { ev.stopPropagation(); if (ev.preventDefault) ev.preventDefault(); }
  if (!runId) return;
  _postJson('/api/rnd/gandalf_archive',
            {project_id: PROJECT_ID, run_id: runId}).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (data) {
      if (_isUnauthorized(r, data)) {
        if (setAnchorToken()) return gandalfArchiveRun(null, runId);
        return;
      }
      if (!data || !data.ok) return;
      var row = document.querySelector(
        '#gandalfPanel .grun[data-run="' + runId + '"]');
      if (row && row.parentNode) row.parentNode.removeChild(row);
      _gandalfRefreshCount();
    });
  }).catch(function () {});
}

// Clear ALL failed runs: POST /api/rnd/gandalf_clear_failed {project_id}; on
// success refetch + re-render the (now failed-free) run list.
function gandalfClearFailed(pid) {
  pid = pid || PROJECT_ID;
  _postJson('/api/rnd/gandalf_clear_failed', {project_id: pid}).then(function (r) {
    return r.json().catch(function () { return {}; }).then(function (data) {
      if (_isUnauthorized(r, data)) {
        if (setAnchorToken()) return gandalfClearFailed(pid);
        return;
      }
      if (!data || !data.ok) return;
      fetch('/api/rnd/gandalf?project_id=' + encodeURIComponent(pid) + _tokenQ(),
            _jsonHdrs()).then(function (r2) { return r2.json(); })
        .then(function (gdata) {
          _gandalfRenderRuns((gdata && gdata.runs) || []);
        }).catch(function () {});
    });
  }).catch(function () {});
}

// Sync the header count chip + drop the "Clear failed" button when no failed
// rows remain (after a single retire).
function _gandalfRefreshCount() {
  var panel = document.getElementById('gandalfPanel');
  if (!panel) return;
  var rows = panel.querySelectorAll('.grun');
  var cnt = panel.querySelector('.gandalf-head .cnt');
  if (cnt) cnt.textContent = rows.length + ' read' + (rows.length === 1 ? '' : 's');
  if (!panel.querySelectorAll('.grun.err-row').length) {
    var cf = panel.querySelector('.gandalf-clear-failed');
    if (cf && cf.parentNode) cf.parentNode.removeChild(cf);
  }
}

// ── Grass B+C hybrid idea workbench (v5 Wave 5) ─────────────────────────────
// The grass lane column tile (.grass-tile) opens a FULL-WIDTH two-pane workbench
// panel in #panelStack (the column is too narrow for the two-pane workbench). The
// workbench markup is rendered server-side into #grassWorkbenchTpl and cloned in.
// Tabs + search scope the left list; selecting a .gli loads the right workbench;
// Develop starts a SEEDED live session in the workbench terminal; a saved
// refinement appears in the history (grass-<id>/dev-N) and is pullable.
var _grassEngine = 'claude';   // workbench engine toggle (default Claude; flip to gemini)
var _grassData = {};            // idea_id -> idea record (from /api/rnd/grass)
var _grassDevSession = null;    // the active Develop session id (for Save refinement)
// v10 Wave 3 — per-(idea,lane) develop session id, so each of the TWO terminal
// hosts (research, plan) remembers its own LIVE session across collapse/expand.
// Key: ideaId + '::' + lane → session_id. A collapse never clears this (the
// session stays live); only switching ideas resets via selectGrassIdea.
var _grassLaneSession = {};

function openGrassWorkbench() {
  var stack = document.getElementById('panelStack');
  var tpl = document.getElementById('grassWorkbenchTpl');
  if (!stack || !tpl) return;
  var existing = document.getElementById('grassPanel');
  if (existing) {
    if (existing.classList.contains('minimized')) existing.classList.remove('minimized');
    existing.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    return;
  }
  var panel = document.createElement('div');
  panel.className = 'panel';
  panel.id = 'grassPanel';
  var bar = document.createElement('div');
  bar.className = 'pbar';
  var title = document.createElement('span');
  title.className = 'ti';
  title.textContent = '🌿 Grass Catcher — idea workbench';
  var sp = document.createElement('span');
  sp.className = 'sp';
  var minBtn = document.createElement('button');
  minBtn.className = 'panelbtn min';
  minBtn.title = 'Minimize';
  minBtn.textContent = '–';
  minBtn.onclick = function (e) { e.stopPropagation(); panel.classList.add('minimized'); };
  var closeBtn = document.createElement('button');
  closeBtn.className = 'panelbtn close';
  closeBtn.title = 'Close';
  closeBtn.textContent = '×';
  closeBtn.onclick = function (e) { e.stopPropagation(); panel.remove(); };
  bar.appendChild(title); bar.appendChild(sp);
  bar.appendChild(minBtn); bar.appendChild(closeBtn);
  var pin = document.createElement('div');
  pin.className = 'pin';
  pin.innerHTML = tpl.innerHTML;     // clone the rendered workbench markup
  panel.appendChild(bar); panel.appendChild(pin);
  stack.appendChild(panel);
  _wireGrassWorkbench(panel);
  panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  // Hydrate the idea data (status + refinements) for the right workbench.
  _loadGrassData();
}

function _wireGrassWorkbench(panel) {
  // Tabs: click sets the active filter and re-filters the list.
  var tabs = panel.querySelectorAll('.gtab');
  for (var i = 0; i < tabs.length; i++) {
    tabs[i].onclick = (function (tab) {
      return function () {
        var all = panel.querySelectorAll('.gtab');
        for (var j = 0; j < all.length; j++) all[j].classList.remove('on');
        tab.classList.add('on');
        filterGrass();
      };
    })(tabs[i]);
  }
  // Rows: click selects the idea.
  var rows = panel.querySelectorAll('.gli');
  for (var k = 0; k < rows.length; k++) {
    rows[k].onclick = (function (row) {
      return function () { selectGrassIdea(row.getAttribute('data-idea')); };
    })(rows[k]);
  }
}

async function _loadGrassData() {
  try {
    var r = await fetch('/api/rnd/grass?project_id=' + encodeURIComponent(PROJECT_ID)
                        + _grassTokenQ());
    var data = await r.json();
    if (data && data.ok && data.ideas) {
      _grassData = {};
      for (var i = 0; i < data.ideas.length; i++) _grassData[data.ideas[i].idea_id] = data.ideas[i];
    }
  } catch (e) { /* read-only; workbench still works from row data */ }
  // v10 Wave 4 FIX 2/3: now that grass data is current, resolve any pending
  // board-tile "from grass" chips (label/dead-state). Idempotent.
  try { _resolveGrassOriginChips(document); } catch (e) {}
}
function _grassTokenQ() {
  var t = _anchorToken();
  return t ? ('&token=' + encodeURIComponent(t)) : '';
}

// filterGrass(): scope the left .gli list by the active status tab + the search box.
function filterGrass() {
  var panel = document.getElementById('grassPanel');
  if (!panel) return;
  var active = panel.querySelector('.gtab.on');
  var filter = active ? (active.getAttribute('data-filter') || 'all') : 'all';
  var sbox = panel.querySelector('.gsearch');
  var q = sbox ? (sbox.value || '').trim().toLowerCase() : '';
  var rows = panel.querySelectorAll('.gli');
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    var st = row.getAttribute('data-status') || 'raw';
    var ttl = (row.getAttribute('data-title') || '').toLowerCase();
    var okStatus = (filter === 'all') || (st === filter);
    var okSearch = !q || ttl.indexOf(q) !== -1;
    row.style.display = (okStatus && okSearch) ? '' : 'none';
  }
}

// selectGrassIdea(ideaId): load the chosen idea's RIGHT workbench (v12 Wave 11 —
// the approved one-session-per-idea workbench, _mockups/grass_2_workbench.html).
// The right pane is: a header (auto-saved indicator + Archive snapshot + Migrate
// to project ↑), the idea text, an auto-gathered History panel (prior refinements
// + archived material + linked/exported deliverables), and ONE session terminal +
// engine toggle. There are NO Research/Plan develop buttons and NO Advance-to-Plan
// control — the single workbench session advances research→plan IN-SESSION
// (advance_stage); the grass second-advance is retired for effort_managed ideas.
// Marks the left-list row selected. (✕→Boneyard stays on the LEFT list row.)
function selectGrassIdea(ideaId) {
  var panel = document.getElementById('grassPanel');
  if (!panel) return;
  var rows = panel.querySelectorAll('.gli');
  var row = null;
  for (var i = 0; i < rows.length; i++) {
    rows[i].classList.remove('sel');
    if (rows[i].getAttribute('data-idea') === ideaId) { row = rows[i]; rows[i].classList.add('sel'); }
  }
  if (!row) return;
  var rec = _grassData[ideaId] || {};
  var title = (rec.title != null) ? rec.title : (row.getAttribute('data-title') || '');
  var status = rec.status || row.getAttribute('data-status') || 'raw';
  var short = rec.short_id || '';
  var notes = rec.notes || '';
  var work = panel.querySelector('.gwork');
  if (!work) return;
  work.removeAttribute('data-empty');
  work.setAttribute('data-idea', ideaId);
  var engLabel = (_grassEngine === 'claude') ? '◆ Claude' : '✦ Gemini';
  var html = ''
    // ── workbench header: title + status chip + auto-saved + Archive + Migrate ──
    + '<div class="ghead">'
    + '<div class="ghead-main">'
    + '<h3>' + _esc(title || '(untitled idea)')
    + ' <span class="idchip">' + _esc(short) + '</span>'
    + ' <span class="stchip ' + _esc(status) + '">' + _esc(status) + '</span></h3>'
    + '<div class="gsubmeta"><span class="gautosave" title="Finished work is '
    + 'auto-saved + auto-logged — there is no Save button">'
    + '<span class="ck">✓</span> auto-saved</span></div>'
    + '</div>'
    + '<div class="ghead-actions">'
    + '<button class="mini garchive-snap" title="Save a point-in-time snapshot of '
    + 'this idea\'s session work (docs + summary) into a per-idea bundle">'
    + '📸 Archive snapshot</button>'
    + '<button class="mini primary gmigrate" title="Migrate this idea\'s work up '
    + 'into the real project lanes; the idea stays here marked promoted">'
    + 'Migrate to project ↑</button>'
    + '</div></div>'
    // ── idea text ──
    + '<div class="gidea"><div class="lbl">Idea</div>'
    + _esc(title || '(untitled idea)')
    + (notes ? '<div class="gidea-notes">' + _esc(notes) + '</div>' : '')
    + '</div>'
    // ── auto-gathered History (prior refinements + archives + deliverables) ──
    + '<div class="ghist"><div class="h">History around this idea '
    + '<span class="auto">⟳ gathered automatically</span></div>'
    + '<div class="ghist-rows"></div></div>'
    // ── ONE workbench session: engine toggle + a single terminal ──
    + '<div class="gsession">'
    + '<div class="gsess-head"><span class="lbl">Workbench session</span>'
    + '<span class="sp"></span>'
    + '<div class="gengine"><button class="mini gengtog">' + _esc(engLabel)
    + '</button></div></div>'
    + '<div class="gterm collapsed" data-lane="research">'
    + '<div class="tbar"><span class="ic">💬</span>'
    + '<span class="lab"><b>Session</b> · not started — click Open to seed it '
    + 'with this idea\'s history</span>'
    + '<span class="sp"></span>'
    + '<button class="mini go gopen" title="Open the seeded workbench session for '
    + 'this idea">Open session</button>'
    + '<span class="car">▸</span></div>'
    + '<div class="term-host" data-grass-term="research"></div></div>'
    + '</div>';
  work.innerHTML = html;
  // Engine toggle (Claude/Gemini) — affects the next session opened for this idea.
  var eng = work.querySelector('.gengtog');
  if (eng) eng.onclick = function () {
    _grassEngine = (_grassEngine === 'claude') ? 'gemini' : 'claude';
    eng.textContent = (_grassEngine === 'claude') ? '◆ Claude' : '✦ Gemini';
  };
  // Migrate to project ↑ → export_grass_to_project (idea stays, grass_origin).
  var mig = work.querySelector('.gmigrate');
  if (mig) mig.onclick = function () { exportGrass(ideaId); };
  // Archive snapshot → archive the single workbench session's docs + summary.
  var arc = work.querySelector('.garchive-snap');
  if (arc) arc.onclick = function () { archiveGrassWorkbench(ideaId); };
  // Open session — start/focus the ONE seeded workbench session (no R/P split).
  var openBtn = work.querySelector('.gopen');
  if (openBtn) openBtn.onclick = function (ev) {
    if (ev) ev.stopPropagation();
    openGrassSession(ideaId);
  };
  // The terminal bar toggles the single session's collapse (never kills).
  var bar = work.querySelector('.gterm .tbar');
  if (bar) bar.onclick = function () { toggleGrassSession(ideaId); };
  // The single workbench session host starts COLLAPSED + unbound for a fresh idea.
  _grassDevSession = null;
  _grassLaneSession[ideaId + '::workbench'] = null;
  _renderGrassHistory(work, rec);
}

// openGrassSession(ideaId): start (or focus) the idea's SINGLE workbench session
// (v12 Wave 11) — one effort_managed grass-dev session per idea, seeded with the
// idea text + refinements, advancing research→plan IN-SESSION. POST
// /api/rnd/grass_workbench. Mounts its xterm in the single terminal host. The
// idea STAYS in grass. Token-aware. Contained: NOT added to the board/top strip.
async function openGrassSession(ideaId) {
  var work = _grassWork(ideaId);
  if (!work) return;
  var box = work.querySelector('.gterm[data-lane="research"]');
  if (box) { box.classList.remove('collapsed'); _setGrassSessionToggle(work, true); }
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, backend: _grassEngine};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_workbench', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_workbench', payload);
      data = await r.json();
    }
  } catch (e) { alert('[grass session error] ' + e.message); return; }
  if (!data.ok || !data.session) {
    alert('[grass session refused] ' + (data.error || 'unknown')); return;
  }
  var sid = data.session.session_id;
  var host = box ? box.querySelector('[data-grass-term]') : null;
  var lab = box ? box.querySelector('.tbar .lab') : null;
  if (lab) lab.innerHTML = '<b>Session</b> · ' + _esc(_grassEngine)
    + ' · seeded with this idea · ' + _esc(sid);
  if (host) {
    if (host.getAttribute('data-session') === sid && PANELS[sid]) {
      host.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    } else {
      host.setAttribute('data-session', sid);
      PANELS[sid] = {el: document.getElementById('grassPanel'), body: host, term: null, transport: null};
      _mountTerminal(sid, host);
    }
  }
  _grassLaneSession[ideaId + '::workbench'] = sid;
  _grassDevSession = sid;
  _setGrassSessionToggle(work, true);
  // Hide the Open button once the session is live (re-clicking the bar toggles).
  var openBtn = work.querySelector('.gopen');
  if (openBtn) openBtn.style.display = 'none';
}

// toggleGrassSession(ideaId): collapse/expand the single workbench terminal. If
// no session is bound yet, opening it starts the session; collapsing never kills.
function toggleGrassSession(ideaId) {
  var work = _grassWork(ideaId);
  if (!work) return;
  var box = work.querySelector('.gterm[data-lane="research"]');
  if (!box) return;
  if (box.classList.contains('collapsed')) {
    box.classList.remove('collapsed');
    _setGrassSessionToggle(work, true);
    if (!_grassLaneSession[ideaId + '::workbench']) {
      openGrassSession(ideaId);
    }
  } else {
    box.classList.add('collapsed');
    _setGrassSessionToggle(work, false);
  }
}

// _setGrassSessionToggle(work, open): reflect the single session's caret state.
function _setGrassSessionToggle(work, open) {
  if (!work) return;
  var box = work.querySelector('.gterm[data-lane="research"]');
  if (box) {
    var tc = box.querySelector('.tbar .car');
    if (tc) tc.textContent = open ? '▾' : '▸';
  }
}

// archiveGrassWorkbench(ideaId): Archive snapshot — persist the single workbench
// session's produced docs + summary into a per-idea bundle (survives kill). The
// idea stays in grass. POST /api/rnd/grass_archive on the workbench session's lane
// (it advances research→plan in-session, so we archive whichever stage's docs
// exist — try plan then research). Token-aware; honest when nothing was produced.
async function archiveGrassWorkbench(ideaId) {
  var sid = _grassLaneSession[ideaId + '::workbench'] || null;
  if (!sid) { alert('[archive] open this idea\'s session first'); return; }
  // The single workbench session's current stage maps to a store lane; the backend
  // resolves the dev session for the lane, so try both (plan first = most advanced).
  var done = false;
  for (var li = 0; li < 2 && !done; li++) {
    var lane = (li === 0) ? 'plan' : 'research';
    var payload = {project_id: PROJECT_ID, idea_id: ideaId, lane: lane};
    var r, data;
    try {
      r = await _postJson('/api/rnd/grass_archive', payload);
      data = await r.json();
      if (_isUnauthorized(r, data) && setAnchorToken()) {
        r = await _postJson('/api/rnd/grass_archive', payload);
        data = await r.json();
      }
    } catch (e) { continue; }
    if (data && data.ok) { done = true; }
  }
  await _loadGrassData();
  var work = _grassWork(ideaId);
  if (work) _renderGrassHistory(work, _grassData[ideaId] || {});
  if (!done) alert('[nothing to archive] no docs produced in this session yet');
}

// _renderGrassArchives(work, archives): render the per-idea Archived-material list
// (persisted docs + a summary link), newest-first. Each archive's docs link via
// /artifact/<pid>?path=<rel>; its summary via /summary/<pid>/<lane>/<sid>. Honest
// empty state when none. (v10 Wave 4.)
function _renderGrassArchives(work, archives) {
  var box = work.querySelector('.garch-rows');
  if (!box) return;
  if (!archives || !archives.length) {
    box.innerHTML = '<div class="garch-empty">No archived material yet — Archive '
      + 'a Research or Plan session to save its docs + summary here.</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < archives.length; i++) {
    var a = archives[i];
    var lane = a.lane || '';
    var sid = a.session_id || '';
    var docs = a.docs || [];
    var doclinks = '';
    for (var d = 0; d < docs.length; d++) {
      var rel = docs[d];
      var href = '/artifact/' + encodeURIComponent(PROJECT_ID)
        + '?path=' + encodeURIComponent(rel);
      var nm = rel.split('/').pop();
      doclinks += '<a class="alink" target="anchor_report_window" href="'
        + _esc(href) + '">'
        + _esc(nm) + '</a>';
    }
    if (!doclinks) doclinks = '<span class="garch-nodoc">(no docs)</span>';
    var sumhref = '/summary/' + encodeURIComponent(PROJECT_ID) + '/'
      + encodeURIComponent(lane) + '/' + encodeURIComponent(sid);
    var sumlink = (a.has_summary)
      ? '<a class="alink" target="anchor_report_window" href="' + _esc(sumhref)
        + '">summary</a>'
      : '<span class="garch-nosum">summary pending</span>';
    html += '<div class="ar"><span class="lnchip">' + _esc(lane) + '</span> '
      + doclinks + '<span class="sp"></span>' + sumlink + '</div>';
  }
  box.innerHTML = html;
}

// _renderGrassHistory(work, rec): v12 Wave 11 — the AUTO-GATHERED History panel
// for the one-session workbench. Gathers, newest-first, the idea's prior
// refinements (text snapshots, each pullable into the live session), its archived
// material (persisted docs + summary), and its exported/linked deliverables — all
// loaded as the context for the single workbench session. ``rec`` is the idea
// record from /api/rnd/grass; an absent record yields the honest empty state.
function _renderGrassHistory(work, rec) {
  var box = work.querySelector('.ghist-rows');
  if (!box) return;
  rec = rec || {};
  var refs = rec.refinements || [];
  var archives = rec.archives || [];
  var exported = rec.exported_to || [];
  var ideaId = work.getAttribute('data-idea');
  var html = '';
  // Exported / linked deliverables first (the most concrete outputs).
  for (var e = 0; e < exported.length; e++) {
    var ex = exported[e];
    var docs = ex.docs || [];
    var dl = '';
    for (var di = 0; di < docs.length; di++) {
      var rel = docs[di];
      var href = '/artifact/' + encodeURIComponent(PROJECT_ID)
        + '?path=' + encodeURIComponent(rel);
      dl += '<a class="open alink" target="anchor_report_window" href="'
        + _esc(href) + '">'
        + _esc(rel.split('/').pop()) + ' ↗</a>';
    }
    if (!dl) dl = '<span class="ghnodoc">(no docs)</span>';
    html += '<div class="hitem deliv"><div class="hbody">'
      + '<div class="htitle"><span class="kind">migrated → ' + _esc(ex.lane || '')
      + '</span> <span class="deliv-badge">deliverable</span></div>'
      + '<div class="hsub">' + dl + '</div></div></div>';
  }
  // Archived material (persisted docs + summary).
  for (var a = 0; a < archives.length; a++) {
    var ar = archives[a];
    var alane = ar.lane || '';
    var asid = ar.session_id || '';
    var adocs = ar.docs || [];
    var adl = '';
    for (var ai = 0; ai < adocs.length; ai++) {
      var arel = adocs[ai];
      var ahref = '/artifact/' + encodeURIComponent(PROJECT_ID)
        + '?path=' + encodeURIComponent(arel);
      adl += '<a class="open alink" target="anchor_report_window" href="'
        + _esc(ahref) + '">'
        + _esc(arel.split('/').pop()) + ' ↗</a>';
    }
    if (!adl) adl = '<span class="ghnodoc">(no docs)</span>';
    var sumhref = '/summary/' + encodeURIComponent(PROJECT_ID) + '/'
      + encodeURIComponent(alane) + '/' + encodeURIComponent(asid);
    var sumlink = (ar.has_summary)
      ? '<a class="open alink" target="anchor_report_window" href="' + _esc(sumhref)
        + '">summary ↗</a>'
      : '<span class="ghnosum">summary pending</span>';
    html += '<div class="hitem arch"><div class="hbody">'
      + '<div class="htitle"><span class="kind">archive · ' + _esc(alane)
      + '</span></div>'
      + '<div class="hsub">' + adl + ' ' + sumlink + '</div></div></div>';
  }
  // Prior refinements (text snapshots) — each pullable into the live session.
  for (var i = 0; i < refs.length; i++) {
    var r = refs[i];
    var rid = r.refinement_id || '';
    var lbl = r.label || (r.text ? r.text.slice(0, 60) : 'refinement');
    html += '<div class="hitem hr"><div class="hbody">'
      + '<div class="htitle"><span class="kind">refinement</span> '
      + '<span class="idchip">' + _esc(rid) + '</span> ' + _esc(lbl) + '</div>'
      + '</div>'
      + '<button class="open mini" data-pull="' + _esc(rid)
      + '">pull into session ↗</button></div>';
  }
  if (!html) {
    box.innerHTML = '<div class="ghist-empty">No prior work yet — open the session '
      + 'to develop this idea; refinements, archives, and migrated deliverables '
      + 'will gather here automatically.</div>';
    return;
  }
  box.innerHTML = html;
  // Pull a refinement into the LIVE single workbench session (research lane = the
  // session's starting stage; the in-session advance carries it to plan).
  var pbtns = box.querySelectorAll('button[data-pull]');
  for (var k = 0; k < pbtns.length; k++) {
    pbtns[k].onclick = (function (rid) {
      return function () { pullGrass(ideaId, rid, 'research'); };
    })(pbtns[k].getAttribute('data-pull'));
  }
}

// _grassWork(ideaId): the .gwork pane for THIS idea (fallback to the visible one).
function _grassWork(ideaId) {
  var panel = document.getElementById('grassPanel');
  if (!panel) return null;
  return panel.querySelector('.gwork[data-idea="' + _cssEsc(ideaId) + '"]')
      || panel.querySelector('.gwork');
}

// _grassTermBox(work, lane): the .gterm container for one lane (research|plan).
function _grassTermBox(work, lane) {
  return work ? work.querySelector('.gterm[data-lane="' + _cssEsc(lane) + '"]') : null;
}

// toggleGrassTerminal(ideaId, lane): v10 Wave 3. Research and Plan each own a
// SEPARATE, independently-collapsible terminal. Clicking a Develop button (or the
// terminal's own bar):
//   • if that lane's terminal is COLLAPSED → EXPAND it. If no session is bound
//     yet, start/focus the (idea, lane) develop session (developGrass) and mount
//     its xterm in THIS lane's host; if already mounted, just reveal it.
//   • if that lane's terminal is EXPANDED → COLLAPSE (minimize) it. The session
//     stays LIVE (the PTY + transport are untouched) — only the host is hidden.
// The two lanes are fully independent: toggling one never touches the other.
function toggleGrassTerminal(ideaId, lane) {
  var work = _grassWork(ideaId);
  if (!work) return;
  var box = _grassTermBox(work, lane);
  if (!box) return;
  if (box.classList.contains('collapsed')) {
    box.classList.remove('collapsed');
    _setGrassToggle(work, lane, true);
    // Bind a session the first time this lane is opened (or re-focus its terminal).
    if (!_grassLaneSession[ideaId + '::' + lane]) {
      developGrass(ideaId, lane);
    } else {
      var host = box.querySelector('[data-grass-term]');
      if (host) host.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      _grassDevSession = _grassLaneSession[ideaId + '::' + lane];
    }
  } else {
    // COLLAPSE only — session stays live (do NOT unmount/kill the PTY).
    box.classList.add('collapsed');
    _setGrassToggle(work, lane, false);
  }
}

// _setGrassToggle(work, lane, open): reflect the open/collapsed state on the
// Develop button (active cue + ▾/▸ caret) and the terminal bar's caret.
function _setGrassToggle(work, lane, open) {
  if (!work) return;
  var btn = work.querySelector('button[data-dev="' + _cssEsc(lane) + '"]');
  if (btn) {
    btn.classList.toggle('on', !!open);
    var bc = btn.querySelector('.car');
    if (bc) bc.textContent = open ? '▾' : '▸';
  }
  var box = _grassTermBox(work, lane);
  if (box) {
    var tc = box.querySelector('.tbar .car');
    if (tc) tc.textContent = open ? '▾' : '▸';
  }
}

// developGrass(ideaId, lane): start a SEEDED workbench session (the idea + its
// refinements) and mount its terminal in THIS lane's own .gterm host. Token-aware.
// Called by toggleGrassTerminal when a lane is first opened. The backend dedupes
// on the live (idea, lane) session — research and plan are two DIFFERENT lanes, so
// both can be live at once (two concurrent dev sessions per idea).
async function developGrass(ideaId, lane) {
  var work = _grassWork(ideaId);
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, lane: lane, backend: _grassEngine};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_develop', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_develop', payload);
      data = await r.json();
    }
  } catch (e) { alert('[develop error] ' + e.message); return; }
  if (!data.ok || !data.session) { alert('[develop refused] ' + (data.error || 'unknown')); return; }
  var sid = data.session.session_id;
  // v8 Wave 6: a develop session is CONTAINED. It is DELIBERATELY NOT added to
  // MANAGED / renderSessionBar (no top-strip chip) and NOT pushed to the board
  // (refreshBoard) — it lives ONLY in the workbench pane below, keyed by
  // (idea, lane). Re-clicking Develop focuses this same session (the backend
  // dedupes on the live (idea, lane) session and returns it). The board bridge
  // also excludes it server-side via the [grass-dev] label marker.
  var box = _grassTermBox(work, lane);
  var host = box ? box.querySelector('[data-grass-term]') : null;
  var lab = box ? box.querySelector('.tbar .lab') : null;
  var icon = (lane === 'plan') ? '📐' : '🔬';
  var name = (lane === 'plan') ? 'Plan terminal' : 'Research terminal';
  if (lab) lab.innerHTML = '<b>' + _esc(name) + '</b> · ' + _esc(_grassEngine)
    + ' · grass-dev · ' + _esc(sid);
  if (host) {
    // Re-focus: if THIS session's terminal is already mounted, just bring it up.
    if (host.getAttribute('data-session') === sid && PANELS[sid]) {
      host.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    } else {
      host.setAttribute('data-session', sid);
      PANELS[sid] = {el: document.getElementById('grassPanel'), body: host, term: null, transport: null};
      _mountTerminal(sid, host);
    }
  }
  // Bind this session to THIS (idea, lane) so a later expand re-focuses it AND so
  // Save-refinement targets the right host. Mark this lane's toggle OPEN.
  _grassLaneSession[ideaId + '::' + lane] = sid;
  _grassDevSession = sid;
  _setGrassToggle(work, lane, true);
  // Enable THIS lane's own Save-refinement button (the other lane's stays as-is).
  var sv = box ? box.querySelector('button[data-save-lane="' + _cssEsc(lane) + '"]') : null;
  if (sv) sv.disabled = false;
  // v10 Wave 4 — enable THIS lane's own Archive button too (the other stays as-is).
  var ar = box ? box.querySelector('button[data-archive-lane="' + _cssEsc(lane) + '"]') : null;
  if (ar) ar.disabled = false;
  // v10 Wave 5 — enable the research lane's own Advance-to-Plan control once its
  // dev session is live (only the research bar carries it).
  if (lane === 'research') {
    var adv = box ? box.querySelector('button[data-advance="research"]') : null;
    if (adv) adv.disabled = false;
  }
}

// archiveGrassSession(ideaId, lane): v10 Wave 4 (D7). Archive THIS LANE's live
// Develop session's PRODUCED docs + summary into a per-idea bundle that survives a
// kill — DISTINCT from Save (a text snapshot). POST /api/rnd/grass_archive →
// effort_history.archive_grass_session. The idea STAYS in grass. Re-renders the
// Archived-material list with the new bundle. Honest: if nothing was produced the
// server returns ok:false with a reason (surfaced, not faked). Token-aware.
async function archiveGrassSession(ideaId, lane) {
  var work = _grassWork(ideaId);
  if (!work) return;
  var sid = _grassLaneSession[ideaId + '::' + lane] || null;
  if (!sid) { alert('[archive] open this lane’s Develop session first'); return; }
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, lane: lane};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_archive', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_archive', payload);
      data = await r.json();
    }
  } catch (e) { alert('[archive error] ' + e.message); return; }
  if (!data.ok) {
    alert('[nothing to archive] ' + (data.reason || data.error || 'no docs produced yet'));
    return;
  }
  // Re-fetch the grass data so the idea record's archives ride the next render,
  // then re-render THIS idea's Archived-material list with the new bundle.
  await _loadGrassData();
  var rec = _grassData[ideaId] || {};
  _renderGrassArchives(work, rec.archives || []);
}

// advanceGrassToPlan(ideaId): v10 Wave 5 (Pillar 2 #2). From THIS idea's RESEARCH
// dev session, push research → plan using the SAME paste-NOT-submit seeded handoff
// as the project-level advance — staying INSIDE the grass workbench, linked. POST
// /api/rnd/grass_advance → effort_history.advance_grass_research_to_plan builds the
// Crucible prompt from the research dev session's persisted docs, starts (or
// focuses) the CONTAINED (idea, 'plan') dev session with the prompt delivered
// PASTED-but-UNSENT, links it to the research session (parent_session_id +
// grass_origin), and records the stage edge. On success we ENSURE the grass PLAN
// terminal is OPEN and mounts the returned plan dev session (reusing the Wave-3
// toggle/mount path), so the pasted-unsent prompt becomes visible in the plan
// terminal input for the user to review and press Enter. The research dev session
// must be live first (the control is disabled until then). v11.1 Wave 2: the
// advance NEVER refuses on "no written doc" — the keystone snapshots the research
// conversation transcript so the plan session ALWAYS opens with a transcript-backed
// (or honest-minimal "create the plan") prompt. The only ok:false left is
// no-research-session (no research dev session to advance from), surfaced honestly.
// Token-aware. No auto-submit (the prompt is the v10 pending paste).
async function advanceGrassToPlan(ideaId) {
  var work = _grassWork(ideaId);
  if (!work) return;
  var rsid = _grassLaneSession[ideaId + '::research'] || null;
  if (!rsid) { alert('[advance] open this idea’s Research session first'); return; }
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, backend: _grassEngine};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_advance', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_advance', payload);
      data = await r.json();
    }
  } catch (e) { alert('[advance error] ' + e.message); return; }
  if (!data || !data.ok || !data.session) {
    // v11.1 Wave 2: the advance NO LONGER refuses on "no written doc" — the
    // keystone snapshots the research conversation transcript and the plan session
    // ALWAYS opens (with a transcript-backed or honest-minimal "create the plan"
    // prompt). The only legitimate refusal left is no-research-session (there is no
    // research dev session at all to advance FROM); honest-surface it.
    alert('[nothing to advance] ' + ((data && (data.reason || data.error))
      || 'open this idea’s Research session first'));
    return;
  }
  var rec = data.session;
  var psid = rec.session_id;
  // Mount the returned grass PLAN dev session into the plan lane's OWN host, then
  // ensure the plan terminal toggles OPEN (reuse the Wave-3 mount/toggle path). We
  // bind the (idea, 'plan') session id BEFORE toggling so toggleGrassTerminal
  // re-focuses THIS session instead of starting a second develop session.
  var box = _grassTermBox(work, 'plan');
  var host = box ? box.querySelector('[data-grass-term]') : null;
  var lab = box ? box.querySelector('.tbar .lab') : null;
  if (lab) lab.innerHTML = '<b>Plan terminal</b> · ' + _esc(_grassEngine)
    + ' · grass-dev · ' + _esc(psid);
  if (host && host.getAttribute('data-session') !== psid) {
    host.setAttribute('data-session', psid);
    PANELS[psid] = {el: document.getElementById('grassPanel'), body: host, term: null, transport: null};
    _mountTerminal(psid, host);
  }
  _grassLaneSession[ideaId + '::plan'] = psid;
  _grassDevSession = psid;
  // Reveal the plan terminal (it may be collapsed) + reflect the open state.
  if (box) box.classList.remove('collapsed');
  _setGrassToggle(work, 'plan', true);
  // Enable the plan lane's own Save + Archive controls (its dev session is live).
  var sv = box ? box.querySelector('button[data-save-lane="plan"]') : null;
  if (sv) sv.disabled = false;
  var ar = box ? box.querySelector('button[data-archive-lane="plan"]') : null;
  if (ar) ar.disabled = false;
  // The Crucible prompt is delivered PASTED-but-UNSENT (pending paste, flushed by
  // the terminal transport after the skill greets). Hint the user it is sitting in
  // the input line for review — nothing was submitted.
  // v10 Wave 5 (DEFECT-1 fix): only flash the "prompt ready" hint when the server
  // actually delivered/queued a fresh paste on THIS advance (data.paste_delivered).
  // A focus of an ALREADY-handed-off plan session (re-advance, or one the user is
  // mid-typing in) delivers nothing → we must NOT flash a misleading hint over an
  // input we didn't write to. (On a fresh mint AND on the develop-plan-first focus
  // that just queued the handoff, paste_delivered is true.)
  if (data.paste_delivered) {
    _flashPendingPasteHint(psid);
  }
}

// saveGrassRefinement(ideaId, lane): persist THIS LANE's live Develop session's
// output as a NEW versioned refinement (grass-<id>/dev-N) and re-render the history
// so it appears with a pull control. Closes the develop→save→appears loop end to
// end. v10 Wave 3 — research and plan are INDEPENDENT lanes, each with its OWN Save
// control, so the save targets THAT lane's bound (idea, lane) session (NOT the
// last-focused global one). The session's visible terminal text is captured
// best-effort as the refinement text; the session_id links the refinement to the
// run. Saving requires that lane's terminal be open (its Develop session live).
// Token-aware.
async function saveGrassRefinement(ideaId, lane) {
  var work = _grassWork(ideaId);
  if (!work) return;
  // THIS lane's bound develop session (set in developGrass). No session ⇒ nothing
  // to save (the per-lane Save button is disabled until its lane is live anyway).
  var sid = _grassLaneSession[ideaId + '::' + lane] || null;
  if (!sid) { alert('[save] open this lane’s Develop session first'); return; }
  // Capture THIS lane's own terminal host text (its [data-grass-term="<lane>"]).
  var box = _grassTermBox(work, lane);
  var host = box ? box.querySelector('[data-grass-term][data-session="'
                                     + _cssEsc(sid) + '"]') : null;
  if (!host && box) host = box.querySelector('[data-grass-term]');
  var text = host ? ((host.innerText || '').trim().slice(-4000)) : '';
  var payload = {project_id: PROJECT_ID, idea_id: ideaId,
                 session_id: sid,
                 label: 'Refinement from ' + lane + ' workbench session', text: text};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_save_refinement', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_save_refinement', payload);
      data = await r.json();
    }
  } catch (e) { alert('[save error] ' + e.message); return; }
  if (!data.ok) { alert('[save refused] ' + (data.error || 'unknown')); return; }
  // Re-fetch the grass data and re-render THIS idea's history so the new
  // grass-<id>/dev-N row appears with its pull controls.
  await _loadGrassData();
  var rec = _grassData[ideaId] || {};
  _renderGrassHistory(work, rec.refinements || []);
  // The idea is now REFINED — reflect it on the workbench chip + the list row.
  var chip = work.querySelector('h3 .stchip');
  if (chip) { chip.className = 'stchip refined'; chip.textContent = 'refined'; }
  // The .gli list rows live under #grassPanel (the left list) — look the row up
  // there (the prior code read an undeclared `panel`, throwing a ReferenceError).
  var panel = document.getElementById('grassPanel');
  var lrow = panel ? panel.querySelector('.gli[data-idea="' + _cssEsc(ideaId) + '"]') : null;
  if (lrow) lrow.setAttribute('data-status', 'refined');
}

// exportGrass(ideaId): EXPORT the idea's research/plan develop work UP into REAL
// lane tiles (Option B). POST /api/rnd/grass_export → the backend copies the
// develop docs up as board-visible lane sessions AND marks the idea "promoted"
// (linked) — the idea STAYS in grass. We then refresh the board so the new lane
// tiles appear, and flip the workbench + list chip to "promoted". Token-aware.
async function exportGrass(ideaId) {
  var payload = {project_id: PROJECT_ID, idea_id: ideaId};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_export', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_export', payload);
      data = await r.json();
    }
  } catch (e) { alert('[export error] ' + e.message); return; }
  if (!data.ok) {
    alert('[export refused] ' + (data.error || data.reason || 'unknown'));
    return;
  }
  // The idea is now PROMOTED — reflect it on the workbench chip + the list row.
  var panel = document.getElementById('grassPanel');
  var work = panel ? panel.querySelector('.gwork[data-idea="' + _cssEsc(ideaId) + '"]') : null;
  if (!work) work = panel ? panel.querySelector('.gwork') : null;
  if (work) {
    var chip = work.querySelector('h3 .stchip');
    if (chip) { chip.className = 'stchip promoted'; chip.textContent = 'promoted'; }
  }
  var lrow = panel ? panel.querySelector('.gli[data-idea="' + _cssEsc(ideaId) + '"]') : null;
  if (lrow) { lrow.setAttribute('data-status', 'promoted'); lrow.classList.add('p'); }
  // Re-fetch the server-rendered board so the exported research/plan lane tiles
  // appear INSTANTLY (the board is the single source of truth — re-fetch, never
  // JS-inject — so dedupe stays correct).
  refreshBoard();
}

// pullGrass(ideaId, refinementId, lane): pull a refinement version into a NEW
// seeded session (research/plan) and open its inline panel. Token-aware.
async function pullGrass(ideaId, refinementId, lane) {
  var payload = {project_id: PROJECT_ID, idea_id: ideaId,
                 refinement_id: refinementId, lane: lane, backend: _grassEngine};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_pull', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_pull', payload);
      data = await r.json();
    }
  } catch (e) { alert('[pull error] ' + e.message); return; }
  if (!data.ok || !data.session) { alert('[pull refused] ' + (data.error || 'unknown')); return; }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {
    session_id: sid, lane: rec.lane || lane, backend: rec.backend || _grassEngine,
    status: rec.status || 'running', label: rec.label || '',
    idx: (_laneCounters[rec.lane || lane] = (_laneCounters[rec.lane || lane] || 0) + 1)
  };
  renderSessionBar();
  openPanel(sid);
  setTimeout(repopulate, 600);
}

// _refreshGrassCounts(root): recompute the .gtabs filter-count chips from the
// REMAINING .gli rows under `root` (a live #grassPanel OR the hidden source
// #grassWorkbenchTpl) and write them into the matching .gtab[data-filter] .n
// spans (all = total rows, raw/refined/promoted = rows by data-status). Deriving
// from the actual rows (not an arithmetic decrement) means the counts can never
// drift after a delete. Guarded for missing elements (no throw).
function _refreshGrassCounts(root) {
  if (!root) return;
  var rows = root.querySelectorAll('.gli[data-status]');
  var counts = {all: 0, raw: 0, refined: 0, promoted: 0};
  for (var i = 0; i < rows.length; i++) {
    counts.all++;
    var st = rows[i].getAttribute('data-status');
    if (counts.hasOwnProperty(st)) counts[st]++;
  }
  var keys = ['all', 'raw', 'refined', 'promoted'];
  for (var k = 0; k < keys.length; k++) {
    var tab = root.querySelector('.gtab[data-filter="' + keys[k] + '"] .n');
    if (tab) tab.textContent = String(counts[keys[k]]);
  }
}

// deleteGrassIdea(ideaId): permanently DELETE a grass idea (v9 Wave 2). confirm()-
// gated (an irreversible removal), then POST /api/rnd/grass_delete {confirm:true}.
// On success the idea row is removed from the workbench list AND — if it was the
// selected idea — the right workbench pane is cleared. The idea does not return
// (grass_workbench_data no longer lists it). Token-aware (retries once on 401).
async function deleteGrassIdea(ideaId) {
  if (!confirm('Delete this idea? This permanently removes it and its refinements.')) return;
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, confirm: true};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_delete', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_delete', payload);
      data = await r.json();
    }
  } catch (e) { alert('[delete error] ' + e.message); return; }
  if (!data.ok) { alert('[delete refused] ' + (data.error || data.reason || 'unknown')); return; }
  var panel = document.getElementById('grassPanel');
  if (panel) {
    var lrow = panel.querySelector('.gli[data-idea="' + _cssEsc(ideaId) + '"]');
    if (lrow) lrow.remove();
    // If the deleted idea was the selected one, clear the right workbench pane.
    var work = panel.querySelector('.gwork[data-idea="' + _cssEsc(ideaId) + '"]')
            || panel.querySelector('.gwork');
    if (work && work.getAttribute('data-idea') === ideaId) {
      work.removeAttribute('data-idea');
      work.setAttribute('data-empty', '1');
      work.innerHTML = '<div class="gwork-empty">Select an idea to develop it.</div>';
    }
  }
  // Drop it from the cached grass data too, so a later select can't resurrect it.
  if (_grassData && _grassData[ideaId]) { try { delete _grassData[ideaId]; } catch (e) {} }
  // v10.1 FIX 2 — the workbench is server-rendered ONCE into a hidden template
  // (#grassWorkbenchTpl); openGrassWorkbench clones it on EVERY fresh open and
  // closeBtn does panel.remove(). Removing only the LIVE row leaves the stale
  // idea in the template, so close→reopen re-clones it back. Prune the matching
  // row from the source template too, so later clones are clean. (DOM-only on a
  // display:none template; no re-wiring, no server change.)
  var stpl = document.getElementById('grassWorkbenchTpl');
  var trow = stpl && stpl.querySelector('.gli[data-idea="' + _cssEsc(ideaId) + '"]');
  if (trow) trow.remove();
  // v10.1 FIX 2 follow-up — the .gtabs filter-count chips were server-rendered
  // ONCE into the template and never updated, so after a delete they read stale
  // (e.g. "All 1" over an empty list, both live AND on a later re-clone). Recompute
  // the counts from the REMAINING rows on BOTH the live panel (immediate update)
  // and the source template (so a close→reopen re-clone shows correct counts).
  _refreshGrassCounts(panel);
  _refreshGrassCounts(stpl);
}

// ── Type-aware deliverable launch (v4 Wave 7) ───────────────────────────────
// Clicking launch ADAPTS to the deliverable type:
//   skill/tool → verify status (available/loaded/missing); NO process.
//   service    → start a preview (free port ≠8777, isolated data dir) or pull
//                up the running one; open the URL in a new tab + show Stop.
//   program    → run-to-result; report success/failure.
//   doc        → open the rendered view (the /artifact route) in a new tab.
// Token-aware via _postJson (retries once on 401).
async function launchDeliverable(btn) {
  var li = btn.closest('.deliv-pinned');
  var msg = li ? li.querySelector('.deliv-msg') : null;
  var did = li ? li.getAttribute('data-deliv-id') : '';
  var dtype = li ? li.getAttribute('data-deliv-type') : '';
  if (!did) { if (msg) msg.textContent = 'no deliverable id'; return; }
  if (msg) msg.textContent = 'launching…';
  btn.disabled = true;
  var payload = {project_id: PROJECT_ID, deliverable_id: did};
  try {
    var r = await _postJson('/api/rnd/launch_deliverable', payload);
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/launch_deliverable', payload);
      data = await r.json();
    }
    if (!data || !data.ok) {
      if (msg) msg.textContent = 'failed: ' + ((data && data.error) || 'unknown');
      btn.disabled = false;
      return;
    }
    if (dtype === 'service') {
      if (li) li.setAttribute('data-preview-id', data.preview_id || '');
      if (msg) msg.textContent = (data.pulled_up ? 'pulled up' : 'running')
        + ' on port ' + (data.port || '?');
      var stopBtn = li ? li.querySelector('.deliv-stop') : null;
      if (stopBtn) stopBtn.style.display = '';
      btn.style.display = 'none';
      if (data.url) window.open(data.url, '_blank');
    } else if (dtype === 'doc') {
      if (msg) msg.textContent = 'opened';
      btn.disabled = false;
      // v13 W1 — a launched DOC deliverable is a report-style document: open it
      // in the unified named window so it refreshes one tab, not many.
      if (data.href) window.open(data.href, 'anchor_report_window');
    } else if (dtype === 'skill' || dtype === 'tool') {
      if (msg) msg.textContent = dtype + ': ' + (data.status || '?');
      btn.disabled = false;
    } else {  // program / script
      if (msg) msg.textContent = 'result: ' + (data.status || (data.ok ? 'ok' : 'failed'));
      btn.disabled = false;
    }
  } catch (e) {
    if (msg) msg.textContent = 'error: ' + e.message;
    btn.disabled = false;
  }
}

async function stopDeliverable(btn) {
  var li = btn.closest('.deliv-pinned');
  var pid = li ? li.getAttribute('data-preview-id') : '';
  var msg = li ? li.querySelector('.deliv-msg') : null;
  if (!pid) { if (msg) msg.textContent = 'no running preview'; return; }
  btn.disabled = true;
  try {
    var r = await _postJson('/api/rnd/preview_stop', {preview_id: pid});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/preview_stop', {preview_id: pid});
      data = await r.json();
    }
    if (msg) msg.textContent = 'stopped';
    btn.style.display = 'none';
    if (li) li.removeAttribute('data-preview-id');
    var runBtn = li ? li.querySelector('.deliv-run') : null;
    if (runBtn) { runBtn.style.display = ''; runBtn.disabled = false; }
  } catch (e) {
    if (msg) msg.textContent = 'stop error: ' + e.message;
    btn.disabled = false;
  }
}

// v13 W1 — unified report-link target: a report/artifact link refreshes the
// ONE named window (anchor_report_window) instead of spawning an endless trail
// of throwaway tabs. Used by the done-effort report links + discovered-artifact
// links (onclick="openReport(...)").
function openReport(href) { window.open(href, 'anchor_report_window'); }

// ── Lifecycle header actions (token-aware via _postJson) ────────────────────
function _lifecycle(url, payload, reload) {
  return _postJson(url, payload).then(function (r) {
    return r.json().then(function (data) {
      if (_isUnauthorized(r, data) && setAnchorToken()) {
        return _postJson(url, payload).then(function (r2) { return r2.json(); });
      }
      return data;
    });
  }).then(function (data) {
    if (reload !== false) location.reload();
    return data;
  }).catch(function (e) { alert('Action failed: ' + e.message); });
}
function rndSetPriority(pid, pr) { _lifecycle('/api/rnd/set_priority', {id: pid, priority: pr}); }
function rndArchive(pid) { if (confirm('Archive this project?')) _lifecycle('/api/rnd/archive_project', {id: pid}); }
function rndRetire(pid) { if (confirm('Retire/cancel this project?')) _lifecycle('/api/rnd/retire_project', {id: pid}); }
function rndReactivate(pid) { _lifecycle('/api/rnd/reactivate_project', {id: pid}); }
function rndRescan(pid) { _lifecycle('/api/rnd/rescan', {id: pid}); }
function rndNotes(pid) {
  var d = document.querySelector('.dash');
  var cur = d ? (d.getAttribute('data-notes') || '') : '';
  var n = window.prompt('Notes for this project:', cur);
  if (n === null) return;
  _lifecycle('/api/rnd/set_notes', {id: pid, notes: n});
}
function rndBlurb(pid) {
  var d = document.querySelector('.dash');
  var cur = d ? (d.getAttribute('data-blurb') || '') : '';
  var n = window.prompt('What this project is (blurb):', cur);
  if (n === null) return;
  _lifecycle('/api/rnd/set_blurb', {id: pid, blurb: n});
}

// ── Header cost/tokens/time rollup: lifetime / 30-day toggle (v4 Wave 5) ─────
// The header renders the lifetime rollup server-side; this toggle re-fetches the
// read-only /api/rnd/project_rollup for the chosen window and swaps the text in
// place (no page reload). Lifetime is the default; the toggle is purely additive.
function rndRollupWindow(window_, btn) {
  var el = document.getElementById('hdrRollup');
  if (!el) return;
  var pid = el.getAttribute('data-pid') || PROJECT_ID;
  // Flip the on-state on the two toggle buttons.
  if (btn && btn.parentNode) {
    var bs = btn.parentNode.querySelectorAll('b');
    for (var i = 0; i < bs.length; i++) bs[i].classList.remove('on');
    btn.classList.add('on');
  }
  var url = '/api/rnd/project_rollup?pid=' + encodeURIComponent(pid)
    + '&window=' + encodeURIComponent(window_) + _tokenQ();
  fetch(url, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d && d.ok && d.text) {
        el.textContent = d.text;
        el.setAttribute('data-window', window_);
      }
    })
    .catch(function () {});
}

// ── Task linking (surfaces the existing link_task endpoint) ─────────────────
function rndLinkTask(el) {
  // Project id rides via the element's data-project attribute (the browser
  // entity-decodes it for us), avoiding the inline-string-literal trap.
  var pid = el.dataset.project || '';
  var t = window.prompt('Link a task to this project (type the task text):', '');
  if (t === null) return;
  t = t.trim();
  if (!t) return;
  _lifecycle('/api/rnd/link_task', {text: t, project_id: pid});
}
function rndUnlinkTask(el) {
  // Read the raw task text from the DOM dataset (entity-decoded by the
  // browser) so it matches the markdown task text verbatim — works even when
  // the text contains apostrophes, quotes, &, <, or >.
  var text = el.dataset.task || '';
  if (!confirm('Unlink this task from the project?')) return;
  // An empty project_id unlinks the matching task (backend contract).
  _lifecycle('/api/rnd/link_task', {text: text, project_id: ''});
}

// ════════════════════════════════════════════════════════════════════════════
// Paradigm-2 INLINE ACCORDION PANEL MANAGER — the ONLY terminal surface.
//
// Each lane's most-recent session is a TILE carrying a status light. Clicking a
// tile (laneTileClick → openPanel) EXPANDS a full-width inline panel appended to
// the #panelStack BELOW the board — panels stack down the page, they never float
// or overlap. A second click / the panel's "– min" button collapses it back to
// the tile (minimizePanel) WITHOUT killing the session. The panel's "×" button is
// CLOSE-to-tile (closePanel) — it tears down the panel DOM only and leaves the
// session record + lane tile intact (reopenable). A SEPARATE "🗑 Kill" button is
// the deliberate hard-kill, gated behind a confirm() (killPanel → POST
// /api/rnd/term_kill) that also removes the session's tile. repopulate() reads
// /api/rnd/term_sessions to keep the MANAGED map in sync (so a tile for an
// already-running terminal can re-open its panel).
//
// The terminal transport is UNCHANGED (WS term_ws first; SSE-out term_stream2 +
// POST-in term_input2 fallback; term_resize), mounted into the panel body host.
// A LIVE session mounts xterm; a DONE/historical session shows a read-only note.
// ════════════════════════════════════════════════════════════════════════════

// MANAGED: session_id -> {session_id, lane, backend, status, label, idx} for
// LIVE (non-terminal) managed sessions — these mount a live xterm terminal.
var MANAGED = {};
// telemetry-resume W3 — REUSE-NOT-SIBLING: source-effort id -> the LIVE session
// id a prior '▶ Resume live' minted from it. _resumeLive consults this so a
// second click on the same effort focuses the already-live window instead of
// spawning a sibling session/worktree.
var _RESUMED_FROM = {};
// FINISHED (v6 Wave 4): session_id -> {session_id, lane, backend, status, label,
// created_at, chain_id, parent_session_id, idx} for TERMINAL-status (done/failed)
// managed sessions. v5 dropped these from the row; v6 KEEPS them as greyed,
// reopenable tiles (per lane: newest prominent, older ones under "previously
// done"). Clicking a finished tile opens a HISTORICAL (read-only) panel showing
// the Wave-1 session summary — _synthSessionRecord reads the tile's data-* attrs,
// so a finished tile is NOT in MANAGED and openPanel treats it as non-live.
var FINISHED = {};
// PANELS: session_id -> {el, body, term, transport} for an OPEN inline panel.
var PANELS = {};
var _laneCounters = {};   // lane -> running index, for "plan 1", "plan 2" labels
// _KILLED (v6 Wave 4): session ids the user DELIBERATELY hard-killed this page
// load. term_kill marks the registry record 'done' (terminal) — indistinguishable
// by status from a naturally-finished session — so without this set a killed tile
// would re-enter the row as a greyed FINISHED tile on the next repopulate(). A
// hard-kill means GONE; we suppress these ids from both MANAGED and FINISHED.
var _KILLED = {};

// _DELETED (v9 Wave 1): session ids the user TRUE-DELETED this page load. Delete
// (term_delete) HARD-REMOVES the registry record + the session's effort pointer-
// records + cached summary — so unlike a kill (which leaves a 'done' record that
// would otherwise re-enter as a greyed tile), a deleted session never comes back
// from the registry. We still record the id here so any in-flight repopulate()
// that raced the delete cannot momentarily re-add the tile. (The produced
// documents are KEPT on disk — Option A — only the Anchor record/cache is gone.)
var _DELETED = {};

// Map a session status to the LOCKED color bucket (MASTER-PLAN §D / §E; this is
// the SAME mapping the server's _session_light_class applies to the lane tiles):
//   running              -> green  (working; ignore)
//   needs-attention/done -> amber  (come look)
//   failed               -> red
//   idle / unknown       -> grey
function _statusColor(status) {
  if (status === 'running') return 'green';
  if (status === 'needs-attention' || status === 'done') return 'amber';
  if (status === 'failed') return 'red';
  return 'grey';
}

// v8 Wave 4 — skill clarity. Mirror terminal_session.LANE_SKILL so the panel
// header can show WHICH trio skill a session loaded (the user's "loads Crucible"
// confusion): research→researchPrime, plan/planning→Crucible, build→Foreman.
// A lane with no mapped skill (grass/general/deliverables) returns '' (no chip).
function _skillForLane(lane) {
  switch (lane) {
    case 'research': return 'researchPrime';
    case 'plan':
    case 'planning': return 'Crucible';
    case 'build': return 'Foreman';
    default: return '';
  }
}

// _isTerminalStatus: mirror session_registry.TERMINAL_STATUSES ({done, failed}).
// The live-session bar is the reopen vector for LIVE (non-terminal) sessions
// ONLY; a terminal session (a hard-killed one is marked 'done', a crashed one
// 'failed') must never sit in it.
function _isTerminalStatus(status) {
  return status === 'done' || status === 'failed';
}

// v10 Wave 5 (DEFECT-2 fix): a CONTAINED grass-workbench develop session keeps
// its research/plan lane (so its trio skill seeds) but its registry label is
// stamped with the [grass-dev] prefix — it must NEVER appear on the top strip
// (#sessionBar) or in MANAGED/FINISHED. It lives ONLY in the workbench pane,
// where it is mounted by session id directly (developGrass → _mountTerminal),
// not via repopulate(). Mirrors effort_history.is_grass_dev_label; the prefix is
// injected from the Python constant (GRASS_DEV_LABEL_PREFIX) so they can't drift.
function _isGrassDevLabel(label) {
  var p = (typeof GRASS_DEV_LABEL_PREFIX !== 'undefined') ? GRASS_DEV_LABEL_PREFIX : '[grass-dev] ';
  return typeof label === 'string' && label.indexOf(p) === 0;
}

// repopulate(): fetch the project's live managed sessions from the registry and
// re-sync the MANAGED map (so a tile / re-open keys on a real, stable record).
// Kept under the historical name loadSessions too (callers use it).
async function repopulate() {
  var url = '/api/rnd/term_sessions?project_id=' + encodeURIComponent(PROJECT_ID);
  var data;
  try {
    var r = await fetch(url);
    data = await r.json();
  } catch (e) { return; }
  if (!data || !data.ok) return;
  var sessions = data.sessions || [];
  // Rebuild the MANAGED (live) + FINISHED (terminal) maps, preserving a stable
  // per-lane index per session.
  var seenLive = {};
  var seenDone = {};
  _laneCounters = {};
  sessions.sort(function (a, b) {
    return (a.created_at || 0) - (b.created_at || 0);
  });
  for (var i = 0; i < sessions.length; i++) {
    var s = sessions[i];
    if (!s.session_id) continue;
    // v10 Wave 5 (DEFECT-2 fix): a CONTAINED grass-workbench develop session
    // (research OR plan) is excluded from the top strip + MANAGED/FINISHED. It is
    // mounted by session id directly in the workbench pane (developGrass), never
    // via this path. Skip BEFORE it enters either map or renderSessionBar.
    if (_isGrassDevLabel(s.label)) continue;
    // v6 Wave 4: a DELIBERATELY hard-killed session is GONE — never re-add it
    // (its registry record persists as 'done', which would otherwise re-enter it
    // as a greyed FINISHED tile). This preserves the v5 "killed tile stays gone".
    if (_KILLED[s.session_id]) continue;
    // v9 Wave 1: a TRUE-DELETED session is GONE (registry record removed); never
    // re-add it even if an in-flight fetch raced the delete and still saw it.
    if (_DELETED[s.session_id]) continue;
    // Phantom-tile fix (belt-and-braces; server already filters these): a Gandalf
    // run (lane 'gandalf') and the Zombie-Hunter terminal (lane 'zombie'; legacy
    // records lane 'general' + label 'zombie-hunter') are NOT cockpit terminals —
    // never paint a tile, live OR greyed-finished. Real general-tab terminals
    // (lane 'general', no zombie-hunter label) are unaffected.
    if (s.lane === 'gandalf' || s.lane === 'zombie' || s.label === 'zombie-hunter') continue;
    var lane = s.lane || 'session';
    if (_isTerminalStatus(s.status)) {
      // v6 Wave 4: a TERMINAL session (a deliberate hard-kill marks the registry
      // record 'done'; a crash 'failed') is KEPT — but in FINISHED (a greyed,
      // reopenable tile), NOT in MANAGED (so openPanel won't try to mount a live
      // PTY for it; it synthesizes a read-only historical panel instead). If it
      // was previously live, drop it from MANAGED + close its now-stale live panel
      // (its PTY is gone) so the tile re-renders as finished.
      if (MANAGED[s.session_id]) { _closePanel(s.session_id); delete MANAGED[s.session_id]; }
      var pdone = FINISHED[s.session_id] || {};
      FINISHED[s.session_id] = {
        session_id: s.session_id, lane: lane, backend: s.backend || '',
        status: s.status || 'done', label: s.label || '',
        created_at: s.created_at || pdone.created_at || 0,
        chain_id: s.chain_id || '', parent_session_id: s.parent_session_id || '',
        effort_managed: !!s.effort_managed,  // v12 W7 (W7-R2-01)
        idx: pdone.idx || 0
      };
      seenDone[s.session_id] = true;
      continue;
    }
    // A LIVE (running/idle/needs-attention) session → colored tile in the row.
    // If it was previously finished (e.g. reconcile re-statused it back live —
    // rare), drop the stale FINISHED entry.
    if (FINISHED[s.session_id]) delete FINISHED[s.session_id];
    _laneCounters[lane] = (_laneCounters[lane] || 0) + 1;
    var prev = MANAGED[s.session_id] || {};
    MANAGED[s.session_id] = {
      session_id: s.session_id, lane: lane, backend: s.backend || '',
      status: s.status || 'idle', label: s.label || '',
      chain_id: s.chain_id || '', parent_session_id: s.parent_session_id || '',
      created_at: s.created_at || prev.created_at || 0,
      effort_managed: !!s.effort_managed,  // v12 W7: live the advance-bar retirement guard (W7-R2-01)
      idx: prev.idx || _laneCounters[lane]
    };
    seenLive[s.session_id] = true;
  }
  // Drop LIVE sessions the registry no longer reports at all (gone, not merely
  // terminal — a terminal one moved to FINISHED above) and close any stale panel.
  for (var sid in MANAGED) {
    if (!seenLive[sid]) { _closePanel(sid); delete MANAGED[sid]; }
  }
  // Drop FINISHED sessions the registry no longer reports (e.g. hard-kill removed
  // the record). A killed tile must not reappear.
  for (var dsid in FINISHED) {
    if (!seenDone[dsid]) delete FINISHED[dsid];
  }
  renderSessionBar();
  // v7 Wave 6: after re-syncing the live/finished maps from the registry, also
  // re-fetch the server-rendered board so the lane-column tiles reflect the
  // current set (a session that finished / advanced / reconciled-dead between
  // polls). The board is the single source of truth for the columns — re-fetch,
  // don't JS-inject — so a session shows EXACTLY ONE tile in its lane.
  refreshBoard();
}
// Back-compat alias: the historical name used by callers.
var loadSessions = repopulate;

// telemetry-resume W6 (diag-B2 S1 fix): the client MANAGED liveness cache used to
// self-heal ONLY on DOMContentLoaded + explicit user actions — a session that died
// SERVER-side (restart/reap/crash) while a tab sat open stayed cached 'running'
// forever, so a click routed to a live-terminal mount over a dead PTY. The PRIMARY
// fix is the Layer-2 attach-ack handshake in _mountTerminal (a dead session yields
// an explicit styled error state, never a blank pane). As defense-in-depth we ALSO
// re-reconcile the cache to server truth on tab refocus + on a bounded timer, so a
// stale-'running' record heals within seconds. Best-effort; _RESUME_REPOLL_MS is
// overridable for tests.
var _RESUME_REPOLL_MS = 15000;
try {
  window.addEventListener('focus', function () {
    try { repopulate(); } catch (e) {}
  });
  setInterval(function () { try { loadSessions(); } catch (e) {} }, _RESUME_REPOLL_MS);
} catch (e) {}

// renderSessionBar(): v5 Wave 1 — render one clickable TILE per LIVE managed
// session into #sessionBar. A live terminal session (started via "+ new <lane>")
// is NOT a server-rendered board tile, so this bar IS its reopenable tile: after
// close-to-tile its chip persists (click it → openPanel re-attaches the live
// terminal); a deliberate hard-kill removes the chip (via _removeSessionTile, the
// SAME selector — these chips carry .tile + data-session). Empty bar when there
// are no live managed sessions. Idempotent (rebuilds from MANAGED each call).
function renderSessionBar() {
  var bar = document.getElementById('sessionBar');
  if (!bar) return;
  // Don't clobber a chip the panel manager is mid-removing: rebuild from the maps.
  bar.innerHTML = '';
  // (1) LIVE managed sessions → colored, reopenable tiles (running/idle/attn).
  var live = Object.keys(MANAGED);
  for (var i = 0; i < live.length; i++) {
    var s = MANAGED[live[i]];
    if (!s) continue;
    bar.appendChild(_buildBarTile(s, false));
  }
  // (2) v6 Wave 4: FINISHED (done/failed) sessions → greyed, reopenable tiles.
  //     Per lane the MOST-RECENT finished session is shown PROMINENTLY in the
  //     row; older finished ones in that lane collapse under a small
  //     "previously done (N)" expander so the row stays tidy but nothing is lost.
  var doneIds = Object.keys(FINISHED);
  if (doneIds.length) {
    // Group by lane, newest-first within each lane (by created_at, then idx).
    var byLane = {};
    for (var j = 0; j < doneIds.length; j++) {
      var d = FINISHED[doneIds[j]];
      if (!d) continue;
      var lane = d.lane || 'session';
      (byLane[lane] = byLane[lane] || []).push(d);
    }
    var lanes = Object.keys(byLane).sort();
    for (var k = 0; k < lanes.length; k++) {
      var group = byLane[lanes[k]];
      group.sort(function (a, b) {
        return (b.created_at || 0) - (a.created_at || 0) || (b.idx || 0) - (a.idx || 0);
      });
      // The newest finished session in this lane is the prominent tile.
      bar.appendChild(_buildBarTile(group[0], true));
      // Older finished ones collapse under "previously done (N)".
      if (group.length > 1) {
        var det = document.createElement('details');
        det.className = 'prevdone';
        det.setAttribute('data-lane', lanes[k]);
        var sum = document.createElement('summary');
        sum.textContent = 'previously done (' + (group.length - 1) + ')';
        det.appendChild(sum);
        var wrap = document.createElement('span');
        wrap.className = 'prevdone-tiles';
        for (var m = 1; m < group.length; m++) {
          wrap.appendChild(_buildBarTile(group[m], true));
        }
        det.appendChild(wrap);
        bar.appendChild(det);
      }
    }
  }
}

// _buildBarTile(s, finished): build one tiles-row tile element for a session
// record. .tile + data-session so _synthSessionRecord / _removeSessionTile bind,
// and the click hook is the SAME laneTileClick → openPanel path. A FINISHED tile
// is greyed (.done) and carries data-light='grey' so openPanel synthesizes a
// read-only historical panel (it is NOT in MANAGED). A LIVE tile carries
// data-live='1' + its status color.
function _buildBarTile(s, finished) {
  var sid = s.session_id;
  var chip = document.createElement('span');
  var light = finished ? 'grey' : _statusColor(s.status);
  chip.className = 'tile lane-tile live-chip' + (finished ? ' done' : '');
  chip.setAttribute('data-session', sid);
  chip.setAttribute('data-lane', s.lane || '');
  chip.setAttribute('data-light', light);
  if (finished) { chip.setAttribute('data-finished', '1'); }
  else { chip.setAttribute('data-live', '1'); }
  chip.onclick = (function (theId) {
    return function (ev) { laneTileClick(ev, theId); };
  })(sid);
  var dot = document.createElement('span');
  dot.className = 'lt ' + light;
  var lbl = document.createElement('span');
  lbl.className = 'ttl';
  lbl.textContent = (s.label ? s.label : (s.lane + ' ' + (s.idx || '')));
  chip.appendChild(dot);
  chip.appendChild(lbl);
    if (!finished) {
      var kill = document.createElement('span');
      kill.innerHTML = '&times;';
      kill.style.marginLeft = '6px';
      kill.style.cursor = 'pointer';
      kill.style.fontWeight = 'bold';
      kill.title = 'Retire session';
      kill.onclick = function (ev) {
        ev.stopPropagation();
        killPanel(sid, true);
      };
      chip.appendChild(kill);
    }
    if (finished) {
    var ck = document.createElement('span');
    ck.className = 'ck';
    ck.textContent = '✓';
    chip.appendChild(ck);
  }
  return chip;
}

// laneTileClick: a Paradigm-2 lane tile was clicked → open its inline panel.
// The tile no longer contains report links / a summary accordion, so the click
// reliably reaches openPanel. We still ignore clicks that land on an explicit
// control (a <details>/<summary> disclosure, an engine toggle, or an explicit
// link/button) before reaching the tile, so those keep their own behavior.
function laneTileClick(ev, sessionId) {
  var t = ev && ev.target;
  var tile = null;
  while (t && t.classList && !t.classList.contains('tile')) {
    if (t.tagName === 'SUMMARY' || t.tagName === 'A' ||
        t.tagName === 'BUTTON' || t.classList.contains('engtog')) {
      return;   // explicit control handles its own click
    }
    t = t.parentNode;
  }
  tile = t;
  // v12 W10: a Layout-D EFFORT tile (headline / minitile, carries
  // data-effort-id) opens the SINGLE bottom dock bound to that effort. Any other
  // tile (legacy lane tile with no effort binding) keeps the inline-panel path.
  if (tile && tile.getAttribute && tile.getAttribute('data-effort-id') != null) {
    openEffortDock(sessionId, tile);
    return;
  }
  openPanel(sessionId);
}

// openLinkedPlanning(ev, planningSid): from a BUILD tile's "⛓ Planning: …" chip,
// open the matched planning session's panel WITHOUT also opening this build tile's
// panel (stopPropagation keeps the click off the tile's laneTileClick). The
// planning session's tile lives in the Planning column with data-session ==
// planningSid, so openPanel resolves it via _synthSessionRecord.
function openLinkedPlanning(ev, planningSid) {
  if (ev) ev.stopPropagation();
  if (planningSid) openPanel(planningSid);
}

// Start a brand-new managed terminal session for a lane (Wave-3 term_start),
// then refresh the bar and open its inline panel. backend defaults to claude.
async function newTermSession(lane, backend, opts) {
  backend = backend || 'claude';
  var payload = {project_id: PROJECT_ID, lane: lane, backend: backend};
  // Wave 6 seam: a seed hint (the source session id) rides into term_start so
  // Wave 7 can build the stage-handoff on top of it. term_start tolerates the
  // extra field today (start_session ignores it); Wave 7 wires it through.
  if (opts && opts.seed_session) payload.seed_session = opts.seed_session;
  // Wave 7 offer→confirm: for a BUILD lane, OFFER the most-recent plan set and
  // only prime on confirm. We fetch the read-only proposal, and if a plan set
  // exists, ask "Execute on this plan set?". YES → proceed (term_start primes).
  // NO → drop the seed and launch a bare build session (non-blocking).
  if (lane === 'build') {
    try {
      var qp = 'project_id=' + encodeURIComponent(PROJECT_ID) + '&lane=build';
      if (opts && opts.seed_session)
        qp += '&seed_session=' + encodeURIComponent(opts.seed_session);
      var pr = await fetch('/api/rnd/handoff_proposal?' + qp);
      var pd = await pr.json();
      if (pd && pd.ok && pd.has_plan_set) {
        var ps = pd.plan_set || {};
        var msg = 'Execute on this plan set? ' +
          (ps.title || ps.plan_dir || 'plan set') +
          ' — ' + (ps.impl_plan_rel || ps.master_plan_rel || '');
        if (!confirm(msg)) {
          // User declined the offer: launch without seeding a plan set.
          delete payload.seed_session;
        }
      }
    } catch (e) { /* proposal is advisory; never block the launch */ }
  }
  var r, data;
  try {
    r = await _postJson('/api/rnd/term_start', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_start', payload);
      data = await r.json();
    }
  } catch (e) { alert('[terminal start error] ' + e.message); return; }
  if (!data.ok || !data.session) {
    alert('[terminal refused] ' + (data.error || data.reason || 'unknown'));
    return;
  }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {
    session_id: sid, lane: rec.lane || lane, backend: rec.backend || backend,
    status: rec.status || 'running', label: rec.label || '',
    idx: (_laneCounters[rec.lane || lane] = (_laneCounters[rec.lane || lane] || 0) + 1)
  };
  renderSessionBar();
  openPanel(sid);
  // v7 Wave 6: re-fetch the server-rendered board so the just-started session's
  // lane-column tile appears INSTANTLY (no page reload). The board is the single
  // source of truth — re-fetch, don't JS-inject — so dedupe stays correct.
  refreshBoard();
  // Re-sync indices/labels from the registry shortly after.
  setTimeout(repopulate, 600);
}

// openPanel(sessionId): expand (or scroll to) the session's INLINE panel in the
// #panelStack below the board. A second openPanel on an OPEN, non-minimized panel
// toggles it back to minimized (collapse-to-tile); an already-minimized panel
// re-expands. The session keeps running throughout — this only shows/hides the
// panel body. The panel header carries "– min" (minimizePanel), "× close"
// (closePanel — close-to-tile, NON-destructive) + "🗑 Kill" (killPanel,
// confirm-gated reap that also removes the tile).
function openPanel(sessionId) {
  // F1 (W10 Reviewer): never stack a floating panel for a session that is ALREADY
  // open in the bottom dock — route the click to the dock so there is exactly ONE
  // live terminal surface per session (the chip + the board effort tile both point
  // at the same live session; the dock owns it).
  if (DOCK && DOCK.session_id === sessionId) { openEffortDock(sessionId); return; }
  // A LIVE managed terminal session → attach its PTY (as today). ANY other tile
  // (historical / discovered / imported) → SYNTHESIZE a panel record from its
  // DOM tile so the panel still opens with the split summary + a read-only body.
  var s = MANAGED[sessionId];
  var isLive = !!s;
  if (!s) {
    s = _synthSessionRecord(sessionId);
    if (!s) return;
  }
  var existing = PANELS[sessionId];
  if (existing && existing.el) {
    // Second click toggles minimize/expand (no kill, no re-mount).
    if (existing.el.classList.contains('minimized')) {
      existing.el.classList.remove('minimized');
      existing.el.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    } else {
      minimizePanel(sessionId);
    }
    renderSessionBar();
    return;
  }
  var stack = document.getElementById('panelStack');
  if (!stack) return;

  var panel = document.createElement('div');
  panel.className = 'panel';
  panel.setAttribute('data-session', sessionId);

  var bar = document.createElement('div');
  bar.className = 'pbar';
  var dot = document.createElement('span');
  dot.className = 'lt ' + _statusColor(s.status);
  var title = document.createElement('span');
  title.className = 'ti';
  title.textContent = (s.label ? s.label : (s.lane + ' ' + s.idx));
  // v8 Wave 4 — surface the LOADED trio skill (e.g. "build · Foreman" /
  // "planning · Crucible" / "research · researchPrime") so it is unambiguous
  // which skill this session is running. Omitted for skill-less lanes.
  var skillEl = document.createElement('span');
  skillEl.className = 'skl';
  var _skl = _skillForLane(s.lane || '');
  skillEl.textContent = _skl ? (s.lane + ' · ' + _skl) : (s.lane || '');
  skillEl.setAttribute('data-skill', _skl);
  var meta = document.createElement('span');
  meta.className = 'mt';
  meta.textContent = s.backend ? ('· ' + s.backend) : '';
  // v6 Wave 5: chain breadcrumb (R-1 → P-2 → …) — the lineage this session
  // belongs to. Filled async from /api/rnd/chain; each node is clickable →
  // openPanel(thatSession). Empty (hidden) for a session with no chain yet.
  var crumb = document.createElement('span');
  crumb.className = 'chaincrumb';
  crumb.setAttribute('data-session', sessionId);
  var sp = document.createElement('span');
  sp.className = 'sp';
  // Per-session engine toggle (◆ Claude / ✦ Gemini). Chosen once; flipping POSTs
  // term_set_engine to relaunch this LIVE session on the other engine in the same
  // worktree. Research can switch freely; plan/build allow Gemini (the server
  // also enforces this). Historical/non-live sessions have no process to switch,
  // so the toggle is omitted there.
  var engEl = null;
  if (isLive) engEl = _buildEngineToggle(sessionId, s);
  // crucible-improve W6 — UNIFIED panel-header controls. Alongside the window
  // controls (– minimize / ▢ maximize) the panel now exposes exactly TWO
  // lifecycle controls, collapsing the old redundant close/hardkill/delete trio:
  //   (a) '–'  minimize  — collapse to a header strip; session keeps running.
  //   (b) '×'  CLOSE     — GRACEFUL close (W6): stops the PTY but PRESERVES the
  //        worktree + KEEPS the registry record (parked STATUS_IDLE, resumable
  //        WARM via W3/W4). POST /api/rnd/term_close persists the produced docs to
  //        MAIN + schedules a background summary so a later resume opens WARM, not
  //        cold. NON-destructive — the tile stays (greyed/idle, reopenable).
  //   (c) Kill → Boneyard — the ONE destructive control (replaces the old 🗑
  //        hardkill + ✕ delete pair): confirm-gated → POST /api/rnd/term_kill
  //        (archive to the Boneyard + reap PTY + worktree), then drop the tile.
  var minBtn = document.createElement('button');
  minBtn.className = 'panelbtn min';
  minBtn.title = 'Minimize (keeps the session running)';
  minBtn.textContent = '–';
  minBtn.onclick = function (e) { e.stopPropagation(); minimizePanel(sessionId); };
  // v6 Wave 3: maximize (▢) — toggle the panel to fill the cockpit viewport
  // (.panel.maxd) and back to its prior size. Either way the xterm terminal is
  // re-fit so cols/rows track the new area (no freeze / clip).
  var maxBtn = document.createElement('button');
  maxBtn.className = 'panelbtn max';
  maxBtn.title = 'Maximize / restore (re-fits the terminal)';
  maxBtn.textContent = '▢';
  maxBtn.onclick = function (e) { e.stopPropagation(); maximizePanel(sessionId); };
  var closeBtn = document.createElement('button');
  closeBtn.className = 'panelbtn close';
  closeBtn.title = 'Close (stops the session but keeps it — reopens WARM from its tile)';
  closeBtn.textContent = '×';
  closeBtn.onclick = function (e) { e.stopPropagation(); closePanel(sessionId); };
  // The ONE destructive control: Kill → Boneyard. Confirm-gated → term_kill
  // (archive to the Boneyard + reap PTY + worktree), then the tile is dropped.
  var killBtn = document.createElement('button');
  killBtn.className = 'panelbtn killbone';
  killBtn.title = 'Kill → Boneyard (archive + reap this session)';
  killBtn.textContent = '🪦';
  killBtn.onclick = function (e) { e.stopPropagation(); killPanel(sessionId); };
  bar.appendChild(dot); bar.appendChild(title);
  bar.appendChild(skillEl); bar.appendChild(meta);
  bar.appendChild(crumb);
  bar.appendChild(sp);
  if (engEl) {
    var englbl = document.createElement('span');
    englbl.className = 'englbl';
    englbl.textContent = 'engine';
    bar.appendChild(englbl);
    bar.appendChild(engEl);
  }
  bar.appendChild(minBtn); bar.appendChild(maxBtn);
  bar.appendChild(closeBtn); bar.appendChild(killBtn);

  // Panel inner body STACKS (mockup Paradigm-2): a split summary block on TOP
  // (materials left + role-tagged doc links right, EQUAL height), then a
  // full-width, vertically-resizable terminal pane BELOW.
  var pin = document.createElement('div');
  pin.className = 'pin';
  // v6 Wave 3: the .pin body is the FREE-resize box (CSS resize:both). Restore
  // this session's persisted panel rect (width + height) if the user resized it
  // earlier this page load (_panelRects, keyed by session_id).
  var _rect = _panelRects[sessionId];
  if (_rect) {
    if (_rect.w) pin.style.width = _rect.w;
    if (_rect.h) pin.style.height = _rect.h;
  }

  // (1) Split summary block — filled async from /api/rnd/session_summary +
  //     /api/rnd/session_doc_roles. Absent → just a thin loading note.
  var summ = document.createElement('div');
  summ.className = 'summary split';
  summ.setAttribute('data-session', sessionId);
  summ.innerHTML = '<div class="summ-loading">loading session summary…</div>';
  pin.appendChild(summ);

  // (2) The terminal pane (resizable wrapper) with a bar + the xterm host.
  var tpane = document.createElement('div');
  tpane.className = 'tpane';
  // Persisted per-session height (in-memory): restore if the user resized it.
  if (_panelHeights[sessionId]) tpane.style.height = _panelHeights[sessionId];
  var tbar = document.createElement('div');
  tbar.className = 'tbar';
  var lab = document.createElement('span');
  lab.className = 'lab';
  lab.textContent = (isLive ? (s.backend || 'terminal') : 'log') + ' · ' + s.session_id;
  var rz = document.createElement('span');
  rz.className = 'rzhint';
  rz.textContent = '⤡ drag the panel corner to resize';
  tbar.appendChild(lab);
  tbar.appendChild(rz);
  var host = document.createElement('div');
  host.className = 'panel-body term-host';
  host.setAttribute('data-session', sessionId);
  tpane.appendChild(tbar);
  tpane.appendChild(host);
  pin.appendChild(tpane);

  // v6 Wave 5: a research session's panel gets an "Advance to Planning →" bar
  // (mockup Step 3). One click starts a NEW linked planning tile seeded from this
  // research (advanceSession → POST /api/rnd/advance_session). Shown ONLY for the
  // research lane this wave (the plan→build auto path is Wave 6).
  // v12 Wave 7 — RETIREMENT MAP (Shark C2): the legacy "Advance to Planning →"
  // bar (which MINTS a new linked planning session) is NOT reachable for a v12
  // effort. A v12 effort advances IN-SESSION (the new Advance → lands in W10);
  // the !s.effort_managed guard INSIDE the block suppresses it for an effort.
  // Legacy (non-effort) research sessions keep the bar exactly as before.
  if ((s.lane || '') === 'research') {
   if (!s.effort_managed) {
    var adv = document.createElement('div');
    adv.className = 'advbar';
    var advt = document.createElement('span');
    advt.className = 'advt';
    advt.innerHTML = 'When this research is done, advance it to a new linked '
      + '<b>planning</b> session, seeded from this work:';
    var advb = document.createElement('button');
    advb.className = 'advbtn';
    advb.type = 'button';
    advb.textContent = 'Advance to Planning →';
    advb.onclick = function (e) {
      e.stopPropagation();
      advanceSession(sessionId, 'planning');
    };
    adv.appendChild(advt);
    adv.appendChild(advb);
    pin.appendChild(adv);
   }
  }

  // v6 Wave 9 (polish 1): a PLANNING session's panel gets an explicit, friendly
  // "Finish → Build" bar (mirrors the research advance bar style). One click POSTs
  // /api/rnd/finish_to_build → captures the plan set, marks THIS planning session
  // done (non-destructive — its worktree is kept, the tile stays reopenable), and
  // auto-opens ONE linked build session. Honest when there is no plan set yet
  // (shows a small note, opens no build). Shown ONLY for the plan/planning lane.
  // v12 Wave 7 — RETIREMENT MAP (Shark C2): the legacy "Finish → Build →" bar
  // (which MINTS a new linked build session) is NOT reachable for a v12 effort.
  // A v12 effort advances IN-SESSION (the new Advance → lands in W10); for it
  // this bar is suppressed. Legacy (non-effort) planning sessions keep it.
  if (((s.lane || '') === 'plan' || (s.lane || '') === 'planning')
      && !s.effort_managed) {
    var fbb = document.createElement('div');
    fbb.className = 'fbbar';
    var fbt = document.createElement('span');
    fbt.className = 'fbt';
    fbt.innerHTML = 'When this plan is ready, finish it and advance to a new '
      + 'linked <b>build</b> session that executes on it:';
    var fbbtn = document.createElement('button');
    fbbtn.className = 'fbbtn';
    fbbtn.type = 'button';
    fbbtn.textContent = 'Finish → Build →';
    fbbtn.onclick = function (e) {
      e.stopPropagation();
      finishToBuild(sessionId);
    };
    fbb.appendChild(fbt);
    fbb.appendChild(fbbtn);
    pin.appendChild(fbb);
  }

  panel.appendChild(bar);
  panel.appendChild(pin);
  stack.appendChild(panel);

  PANELS[sessionId] = {el: panel, body: host, term: null, transport: null,
                       tpane: tpane, pin: pin, fit: null, ro: null, pinRo: null,
                       maxd: false};
  if (isLive) {
    // LIVE managed terminal: mount xterm over the v3 transport (UNCHANGED).
    _mountTerminal(sessionId, host);
  } else {
    // HISTORICAL/discovered session: NO live PTY. Show a read-only note (the
    // summary above carries the materials + doc links). We try to load a
    // transcript/log if one exists; otherwise a "session complete" note.
    _mountReadOnlyBody(sessionId, host, s);
  }
  _loadPanelSummary(sessionId, summ);
  _loadChainBreadcrumb(sessionId, crumb);
  _loadGrassOriginChip(sessionId, crumb);
  _wirePanelResize(sessionId, tpane);
  // crucible-improve #8 (W5): fit the terminal to its now-full-width column ON
  // OPEN so a freshly-opened terminal spans the full column immediately — not
  // only after a maximize→restore. The .pin CSS now carries width:100%, so by
  // the time the panel paints the host is full width; re-fit once now and once
  // after layout settles (guarded: _fitPanelTerminal no-ops without a live term).
  if (isLive) {
    _fitPanelTerminalDeferred(sessionId);
  }
  panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  renderSessionBar();
}

// _CHAIN_ABBR: lane → the breadcrumb node prefix (research→R, planning/plan→P,
// build→B). Mirrors the mockup's R-/P-/B- labels.
var _CHAIN_ABBR = {research: 'R', planning: 'P', plan: 'P', build: 'B'};

// _loadChainBreadcrumb(sessionId, host): fetch this session's lineage chain and
// render a clickable breadcrumb (R-1 → P-2 → …) into the panel header. Read-only
// (GET /api/rnd/chain, ?token=); each node opens that session's panel. A chain of
// one (no lineage) renders nothing. Best-effort — any error leaves the crumb empty.
//
// v8 Wave 7 — full chain navigation on the now-DURABLE artifacts (W2/W5):
//   - Renders for EVERY panel — live AND done/historical (openPanel calls this
//     unconditionally; a done/historical tile resolves via _synthSessionRecord),
//     so you can navigate the chain from a finished build the same as from a live
//     research session.
//   - Each node shows a status LIGHT (green/amber/red/grey) + the lane + a short
//     label, so a node's state is visible at a glance (not only on hover).
//   - Click a sibling node → openPanel(thatId): if it is LIVE it focuses/attaches
//     its terminal; if DONE/historical it opens that session's DETAIL view (the W5
//     read-only body — summary + produced docs + "Continue the dialog"). So you can
//     move research→plan→build AND back build→plan→research, landing on real content.
//   - HONEST partial chains: members.length < 2 → render nothing (a lone session
//     with no siblings shows no misleading breadcrumb; no fabricated nodes — the
//     server only emits the records that actually exist for this chain).
function _loadChainBreadcrumb(sessionId, host) {
  if (!host) return;
  var url = '/api/rnd/chain?project_id=' + encodeURIComponent(PROJECT_ID)
    + '&session=' + encodeURIComponent(sessionId) + _tokenQ();
  fetch(url, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var members = (d && d.ok && d.members) ? d.members : [];
      host.innerHTML = '';
      if (members.length < 2) {
        // No managed/registry chain (e.g. a DISCOVERED build session). Fall back
        // to the static Build→Planning tie carried on the tile (Option A): render
        // a 2-node breadcrumb (P <label> → B <label>) so the imported build still
        // shows — and can navigate to — the plan it executed on.
        _renderStaticTieCrumb(sessionId, host);
        return;
      }
      members.forEach(function (m, i) {
        if (i > 0) {
          var sep = document.createElement('span');
          sep.className = 'cc-sep';
          sep.textContent = '→';
          host.appendChild(sep);
        }
        var node = document.createElement('span');
        var lane = m.lane || '';
        var abbr = _CHAIN_ABBR[lane] || (lane ? lane.charAt(0).toUpperCase() : '?');
        node.className = 'cc-node' + (m.session_id === sessionId ? ' cur' : '');
        node.setAttribute('data-session', m.session_id);
        node.setAttribute('data-lane', lane);
        // A small status light (locked color map) makes each node's state visible
        // at a glance — a done sibling reads amber, a live one green, etc.
        var lt = document.createElement('span');
        lt.className = 'cc-light ' + _statusColor(m.status || '');
        node.appendChild(lt);
        var txt = document.createElement('span');
        txt.className = 'cc-txt';
        txt.textContent = m.label ? m.label : (abbr + ' ' + lane);
        node.appendChild(txt);
        node.title = lane + ' · ' + (m.status || '');
        node.onclick = (function (theId) {
          return function (ev) { ev.stopPropagation(); openPanel(theId); };
        })(m.session_id);
        host.appendChild(node);
      });
    })
    .catch(function () {});
}

// _loadGrassOriginChip(sessionId, host): v10 Wave 4 (D8). If this session's chain
// carries a grass_origin (it was exported/promoted from a grass idea, OR is a
// downstream plan/build that inherited the stamp), render a "from grass: <idea>"
// back-link chip into the panel header. Clicking it opens the Grass workbench
// focused on that idea (openGrassWorkbench → selectGrassIdea). HONEST: no
// grass_origin in the chain → no chip (no fabricated back-link). Read-only
// (GET /api/rnd/chain, ?token=); best-effort (any error leaves no chip).
function _loadGrassOriginChip(sessionId, host) {
  if (!host) return;
  var url = '/api/rnd/chain?project_id=' + encodeURIComponent(PROJECT_ID)
    + '&session=' + encodeURIComponent(sessionId) + _tokenQ();
  fetch(url, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var members = (d && d.ok && d.members) ? d.members : [];
      // Find a grass_origin anywhere in the chain (this session or a sibling).
      var origin = '';
      for (var i = 0; i < members.length; i++) {
        var go = (members[i] && members[i].grass_origin) || '';
        if (go) { origin = go; break; }
      }
      // HONEST: empty origin → no chip (no fabricated back-link).
      if (!origin) return;
      // Ensure the grass data is loaded so we can resolve the idea title AND
      // detect a DELETED origin (FIX 3 dead-chip). _loadGrassData is idempotent.
      var done = function () {
        var rec = (_grassData && _grassData[origin]) ? _grassData[origin] : null;
        var chip = document.createElement('span');
        chip.className = 'grassorigin';
        chip.setAttribute('data-grass-origin', origin);
        if (!rec) {
          // DEAD CHIP: the originating idea no longer exists — render greyed/
          // disabled, no live link (FIX 3). Keep the stamp; be honest in the UI.
          chip.classList.add('removed');
          chip.setAttribute('data-grass-removed', '1');
          chip.title = 'The originating grass idea was removed';
          chip.textContent = '🌱 from grass (idea removed)';
          host.appendChild(chip);
          return;
        }
        var label = (rec.title || rec.short_id || origin);
        chip.title = 'This work traces back to a grass idea — click to open it';
        chip.textContent = '🌱 from grass: ' + (label.length > 40
          ? label.slice(0, 40) + '…' : label);
        chip.onclick = function (ev) {
          ev.stopPropagation();
          if (typeof openGrassWorkbench === 'function') openGrassWorkbench();
          // Focus the originating idea once the workbench list has rendered.
          setTimeout(function () {
            try { selectGrassIdea(origin); } catch (e) {}
          }, 250);
        };
        host.appendChild(chip);
      };
      if (_grassData && Object.keys(_grassData).length) { done(); return; }
      try { _loadGrassData().then(done).catch(done); } catch (e) { done(); }
    })
    .catch(function () {});
}

// _resolveGrassOriginChips(root): resolve every server-rendered board-tile
// "from grass" chip placeholder (v10 Wave 4 FIX 2/3). The server emits a chip
// stub carrying ONLY data-grass-origin (the SAFE idea id) + data-grass-pending;
// here we resolve its label, dead-state, and click handler against the loaded
// _grassData — exactly like the panel chip (shared dead-chip path). Idempotent:
// a chip is processed once (its pending marker is cleared). Best-effort.
function _resolveGrassOriginChips(root) {
  root = root || document;
  var pend = root.querySelectorAll('.grassorigin[data-grass-pending]');
  for (var i = 0; i < pend.length; i++) {
    var el = pend[i];
    var origin = el.getAttribute('data-grass-origin') || '';
    el.removeAttribute('data-grass-pending');
    if (!origin) { el.style.display = 'none'; continue; }
    var rec = (_grassData && _grassData[origin]) ? _grassData[origin] : null;
    if (!rec) {
      // DEAD CHIP on the tile: greyed/disabled, no live link (FIX 3).
      el.classList.add('removed');
      el.setAttribute('data-grass-removed', '1');
      el.title = 'The originating grass idea was removed';
      el.textContent = '🌱 from grass (idea removed)';
      el.onclick = null;
      continue;
    }
    var label = (rec.title || rec.short_id || origin);
    el.title = 'This work traces back to a grass idea — click to open it';
    el.textContent = '🌱 from grass: ' + (label.length > 40
      ? label.slice(0, 40) + '…' : label);
    (function (oid) {
      el.onclick = function (ev) {
        ev.stopPropagation();
        if (typeof openGrassWorkbench === 'function') openGrassWorkbench();
        setTimeout(function () {
          try { selectGrassIdea(oid); } catch (e) {}
        }, 250);
      };
    })(origin);
  }
}

// _renderStaticTieCrumb(sessionId, host): the DISCOVERED build→planning fallback
// breadcrumb (Option A). When a session has no managed/registry chain, read the
// session's tile for data-linked-planning (+ label) and, if present, render a
// 2-node breadcrumb "P <label> → B <label>" into the panel header. The P node
// opens the matched planning session's panel; the B node is the current one.
// No tie on the tile → nothing rendered (honest; no fabricated chain).
function _renderStaticTieCrumb(sessionId, host) {
  if (!host) return;
  var tile = document.querySelector('.tile[data-session="' + _cssEsc(sessionId) + '"]');
  if (!tile) return;
  var planSid = tile.getAttribute('data-linked-planning');
  if (!planSid) return;
  var label = tile.getAttribute('data-linked-planning-label') || '';
  function _node(abbr, lab, isCur, openSid) {
    var node = document.createElement('span');
    node.className = 'cc-node' + (isCur ? ' cur' : '');
    var lt = document.createElement('span');
    lt.className = 'cc-light grey';
    node.appendChild(lt);
    var txt = document.createElement('span');
    txt.className = 'cc-txt';
    txt.textContent = lab ? (abbr + ' ' + lab) : abbr;
    node.appendChild(txt);
    if (openSid) {
      node.onclick = function (ev) { ev.stopPropagation(); openPanel(openSid); };
    }
    return node;
  }
  host.appendChild(_node('P', label, false, planSid));
  var sep = document.createElement('span');
  sep.className = 'cc-sep';
  sep.textContent = '→';
  host.appendChild(sep);
  host.appendChild(_node('B', label, true, null));
}

// _synthSessionRecord(sessionId): build a MANAGED-shaped record for a NON-live
// tile from its DOM, so openPanel can render a panel for a historical /
// discovered / imported session. Reads the tile's data-lane + data-light (the
// locked status color the server stamped) off the page. Returns null only if no
// such tile exists.
function _synthSessionRecord(sessionId) {
  var tile = document.querySelector('.tile[data-session="' + _cssEsc(sessionId) + '"]');
  if (!tile) return null;
  var lane = tile.getAttribute('data-lane') || '';
  var light = tile.getAttribute('data-light') || 'grey';
  // Map the light color back to a coarse status (only for the header dot/title).
  var status = (light === 'green') ? 'running'
             : (light === 'amber') ? 'done'
             : (light === 'red') ? 'failed' : 'idle';
  var ttlEl = tile.querySelector('.ttl');
  var label = ttlEl ? (ttlEl.textContent || '').trim() : '';
  // v12 W7: carry effort_managed so the advance-bar retirement guard is live on
  // the historical/synth panel path too (W7-R2-01).
  var em = tile.getAttribute('data-effort-managed') === '1';
  return {session_id: sessionId, lane: lane, backend: '', status: status,
          label: label, idx: '', historical: true, effort_managed: em};
}

// CSS.escape shim for the attribute selector (older engines lack CSS.escape).
function _cssEsc(s) {
  if (window.CSS && CSS.escape) return CSS.escape(s);
  return String(s).replace(/["\\\]]/g, '\\$&');
}

// _buildEngineToggle(sessionId, s): the ◆ Claude / ✦ Gemini toggle for the panel
// bar. The currently-selected engine (s.backend, default claude) is highlighted;
// clicking the OTHER engine POSTs term_set_engine (relaunch in the same worktree)
// and updates the record + toggle on success. Returns the .engtog element.
function _buildEngineToggle(sessionId, s) {
  var cur = (s && s.backend) || 'claude';
  var tog = document.createElement('span');
  tog.className = 'engtog';
  tog.title = 'Chosen once; flip to switch this session to the other engine.';
  [['claude', '◆ Claude'], ['gemini', '✦ Gemini']].forEach(function (pair) {
    var eng = pair[0];
    var b = document.createElement('b');
    b.textContent = pair[1];
    b.setAttribute('data-engine', eng);
    if (eng === cur) b.className = 'on';
    b.onclick = function (e) {
      e.stopPropagation();
      if (eng === ((MANAGED[sessionId] || {}).backend || cur)) return;  // already on it
      switchTerminalEngine(sessionId, eng, tog);
    };
    tog.appendChild(b);
  });
  return tog;
}

// setSessionEngine(sessionId, engine, tog): flip a LIVE session to the other
// engine via /api/rnd/term_set_engine (relaunch in the same worktree). On success
// update the MANAGED record + the toggle's on-state; on refusal (e.g. plan/build
// is invalid) alert and leave the toggle unchanged.
async function setSessionEngine(sessionId, engine, tog) {
  var r, data;
  try {
    r = await _postJson('/api/rnd/term_set_engine', {session: sessionId, engine: engine});
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_set_engine', {session: sessionId, engine: engine});
      data = await r.json();
    }
  } catch (e) { alert('[engine switch error] ' + e.message); return; }
  if (!data || !data.ok) {
    alert('[engine switch refused] ' + ((data && (data.error || data.reason)) || 'unknown'));
    return;
  }
  if (MANAGED[sessionId]) MANAGED[sessionId].backend = engine;
  if (tog) {
    var bs = tog.querySelectorAll('b');
    for (var i = 0; i < bs.length; i++) {
      bs[i].className = (bs[i].getAttribute('data-engine') === engine) ? 'on' : '';
    }
  }
  // Re-sync the registry shortly (the relaunch mints a fresh PTY in the worktree).
  setTimeout(repopulate, 600);
}

// switchTerminalEngine(sessionId, engine, tog): hot-swap the terminal session to the other
// engine with suspend & summarize. POSTs /api/rnd/switch_terminal_engine.
async function switchTerminalEngine(sessionId, engine, tog) {
  var r, data;
  try {
    r = await _postJson('/api/rnd/switch_terminal_engine', {session: sessionId, engine: engine});
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/switch_terminal_engine', {session: sessionId, engine: engine});
      data = await r.json();
    }
  } catch (e) { alert('[engine switch error] ' + e.message); return; }
  if (!data || !data.ok) {
    alert('[engine switch refused] ' + ((data && (data.error || data.reason)) || 'unknown'));
    return;
  }
  if (MANAGED[sessionId]) MANAGED[sessionId].backend = engine;
  if (tog) {
    var bs = tog.querySelectorAll('b');
    for (var i = 0; i < bs.length; i++) {
      bs[i].className = (bs[i].getAttribute('data-engine') === engine) ? 'on' : '';
    }
  }
  if (!data.context_loaded) {
    var p = PANELS[sessionId];
    var lab = p && p.tpane ? p.tpane.querySelector('.lab') : null;
    if (lab) {
      lab.innerHTML += ' <span style="color:var(--rnd-amber,#d97706);font-size:0.85em;margin-left:8px;">⚠️ Context summary not loaded</span>';
    }
  }
  // Re-sync the registry shortly (the relaunch mints a fresh PTY in the worktree).
  setTimeout(function() {
    if (typeof DOCK !== 'undefined' && DOCK && DOCK.session_id === sessionId) {
      openEffortDock(sessionId);
    } else {
      var w = PANELS[sessionId];
      if (w && w.body) {
        _closePanel(sessionId);
        setTimeout(function() { openPanel(sessionId); }, 100);
      }
    }
    repopulate();
  }, 600);
}

// _mountReadOnlyBody (v5 Wave 2): a NON-live (done/historical) session has no
// PTY. Instead of a dead-end "session complete" note, render a REAL past-session
// view in the terminal host: the SKILL invoked, the PROMPTS asked, and the
// ACTIONS/files produced (from the cached session summary), plus a "Continue in a
// live session" button that starts a NEW live session in the SAME lane seeded
// with this session's context. Honest placeholders when a field is absent.
function _mountReadOnlyBody(sessionId, host, s) {
  var runningNote = (s.status === 'running')
    ? '<div class="ro-note">Session is running in the background — no live '
      + 'terminal attached.</div>'
    : '';
  // Skeleton with a Continue button (always available for a historical session)
  // and a region we fill async from the cached session summary.
  host.innerHTML = runningNote
    + '<div class="ro-past" data-session="' + _esc(sessionId) + '">'
    + '<div class="ro-actions">'
    + '<button class="ro-continue" type="button">▶ Continue in a live session</button>'
    + '</div>'
    + '<div class="ro-detail"><div class="summ-loading">loading past-session '
    + 'summary…</div></div>'
    + '</div>';
  var btn = host.querySelector('.ro-continue');
  if (btn) btn.onclick = function (e) {
    e.stopPropagation();
    continueSession(sessionId, s.lane);
  };
  var detail = host.querySelector('.ro-detail');
  _fillPastSessionDetail(sessionId, (s && s.lane) || '', detail);
  // telemetry-resume W3 — the Layer-1 WARM narrated view. Prepend the
  // deterministic narration spine (done / produced / next) + the '▶ Resume live'
  // control INTO this same session-window terminal chrome, so the first click on
  // ANY tile class opens a warm terminal that narrates (the first-click sentence).
  // Pure render off the token-authed /api/rnd/session_narration data route — NO
  // PTY, NO synchronous model call, NO network beyond the one cached-data GET.
  _mountLayer1Narration(sessionId, host, s);
}

// _mountLayer1Narration (telemetry-resume W3): render the Layer-1 warm narrated
// view into the session-window terminal-chrome host. The narration SPINE (what
// was done / produced / comes next) is a PURE deterministic render served from
// the token-authed /api/rnd/session_narration route — total over every tile class
// (running, done, failed, parked-idle, EVICTED-parked, reaped-orphan, cancelled,
// general, discovered, finished one-shot job), so it is structurally never blank.
// A '▶ Resume live' control (the Layer-2 escalation, fully wired in W6) sits in
// the same window. Lazy enrichment: while the server reports enrichment
// 'generating' the spine shows a 'summary generating…' badge OVER the floor and
// polls a BOUNDED number of times for the enriched line to land, then STOPS (no
// loop; a failed/absent generation leaves the floor standing).
function _mountLayer1Narration(sessionId, host, s, _tries) {
  if (!host) return;
  _tries = _tries || 0;
  var block = host.querySelector('.layer1');
  if (!block) {
    block = document.createElement('div');
    block.className = 'layer1';
    block.setAttribute('data-session', sessionId);
    block.innerHTML = '<div class="l1-spine"><div class="summ-loading">'
      + 'loading warm view…</div></div>';
    var act = document.createElement('div');
    act.className = 'l1-actions';
    var rl = document.createElement('button');
    rl.className = 'resume-live';
    rl.type = 'button';
    rl.textContent = '▶ Resume live';
    rl.onclick = function (e) {
      e.stopPropagation();
      _resumeLive(sessionId, (s && s.lane) || '');
    };
    act.appendChild(rl);
    block.appendChild(act);
    host.insertBefore(block, host.firstChild);
  }
  var spine = block.querySelector('.l1-spine');
  var lane = (s && s.lane) || '';
  var url = '/api/rnd/session_narration?pid=' + encodeURIComponent(PROJECT_ID)
    + '&lane=' + encodeURIComponent(lane)
    + '&session=' + encodeURIComponent(sessionId) + _tokenQ();
  fetch(url, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var n = (d && d.ok && d.narration) ? d.narration : null;
      if (!n) {
        if (spine) spine.innerHTML = '<div class="ro-note">Warm view '
          + 'unavailable.</div>';
        return;
      }
      if (spine) spine.innerHTML = _renderLayer1(n);
      // Lazy enrichment: poll a BOUNDED number of times while generating, then
      // stop — never an infinite loop; the floor already stands underneath.
      if (n.enrichment === 'generating' && _tries < 20) {
        setTimeout(function () {
          _mountLayer1Narration(sessionId, host, s, _tries + 1);
        }, 600);
      }
    })
    .catch(function () {
      if (spine) spine.innerHTML = '<div class="ro-note">Warm view '
        + 'unavailable.</div>';
    });
}

// _renderLayer1(n): the narration SPINE HTML — badges (evicted / summary
// generating…), the what-was-done line, the produced doc links (/report ·
// /artifact), and the what-comes-next block. The 'next' is shown PASTE-NOT-SUBMIT
// (a quoted block carrying data-submit="false") — nothing is ever auto-run.
function _renderLayer1(n) {
  var out = [];
  var badges = n.badges || [];
  if (badges.length) {
    var b = ['<div class="l1-badges">'];
    for (var i = 0; i < badges.length; i++) {
      var cls = (badges[i] === 'evicted') ? 'l1-badge evicted' : 'l1-badge gen';
      b.push('<span class="' + cls + '">' + _esc(badges[i]) + '</span>');
    }
    b.push('</div>');
    out.push(b.join(''));
  }
  out.push('<div class="l1-sec"><span class="l1-k">What was done</span>'
    + '<span class="l1-v">' + _esc(n.done || '') + '</span></div>');
  out.push('<div class="l1-sec"><span class="l1-k">What was produced</span></div>');
  var produced = n.produced || [];
  if (produced.length) {
    var pl = ['<ul class="l1-list">'];
    for (var j = 0; j < produced.length; j++) {
      var p = produced[j];
      var tag = p.role ? (_esc(p.role) + ': ') : '';
      pl.push('<li><a href="' + _esc(p.href || '') + '" target="anchor_report_window" '
        + 'rel="noopener">' + tag + _esc(p.label || '') + '</a></li>');
    }
    pl.push('</ul>');
    out.push(pl.join(''));
  } else {
    out.push('<div class="ro-note"><i>'
      + _esc(n.produced_note || 'no recoverable documents') + '</i></div>');
  }
  var nx = n.next || {};
  out.push('<div class="l1-sec"><span class="l1-k">What comes next</span></div>');
  out.push('<div class="l1-next" data-submit="false">'
    + _esc(nx.text || '') + '</div>');
  return out.join('');
}

// _resumeLive(sessionId, lane): the Layer-2 escalation control. REUSE-NOT-SIBLING
// — if this effort already has a LIVE session open (either the session itself is
// live, or a prior Resume minted one that is still live), FOCUS that window
// instead of spawning a second sibling. Otherwise escalate via the existing
// continueSession path. The full attach-ack + replay-complete handshake and the
// read-only plan-mode orientation land in W6; here the control is rendered and
// wired to the reuse-aware escalation.
function _resumeLive(sessionId, lane) {
  var self = MANAGED[sessionId];
  if (self && self.status === 'running') {
    if (DOCK && DOCK.session_id === sessionId) { openEffortDock(sessionId); return; }
    openPanel(sessionId);
    return;
  }
  var prior = _RESUMED_FROM[sessionId];
  if (prior && MANAGED[prior] && MANAGED[prior].status === 'running') {
    if (DOCK && DOCK.session_id === prior) { openEffortDock(prior); return; }
    openPanel(prior);
    return;
  }
  // telemetry-resume W6 — the per-tile-class escalation is decided SERVER-side by
  // /api/rnd/resume_live: RUNNING→focus, parked-idle→warm reattach (same id,
  // retained worktree), evicted-parked→NEW seeded session on the same chain with
  // the 'resumed from persisted docs (worktree evicted)' line, done/failed/
  // discovered/one-shot→continue-seed. On escalation the read-only orientation
  // AUTO-EXECUTES as a plan-mode one-shot job (never a seeded PTY turn); any
  // ACTION prompt stays v10 paste-NOT-submit. One click, one further action,
  // same window — never a third action, never a second window.
  var fromDock = (DOCK && DOCK.session_id === sessionId);
  var payload = {project_id: PROJECT_ID, lane: lane || '',
                 source_session: sessionId, backend: 'claude'};
  _postJson('/api/rnd/resume_live', payload).then(function (d) {
    if (!d || !d.ok || !d.session || !d.session.session_id) {
      // Fall back to the plain continue path so the click is never a dead end.
      continueSession(sessionId, lane);
      return;
    }
    var sid = d.session.session_id;
    var mode = d.mode || 'continue';
    MANAGED[sid] = d.session;
    if (sid !== sessionId) _RESUMED_FROM[sessionId] = sid;
    try { renderSessionBar(); } catch (e) {}
    // Read-only orientation AUTO-EXECUTES (plan-mode one-shot job) on the resumed
    // session — best-effort, fire-and-forget; nothing is auto-submitted.
    _triggerOrientation(sid, d.session.lane || lane || '');
    // Open the escalated session IN THE SAME window (dock or panel).
    if (fromDock) {
      try { refreshBoard(); } catch (e) {}
      var tile = document.querySelector('[data-effort-id="' + sid + '"]')
        || document.querySelector('[data-effort-id="' + sessionId + '"]');
      openEffortDock(sid, tile || undefined);
    } else {
      openPanel(sid);
      if (sid !== sessionId) { try { _closePanel(sessionId); } catch (e) {} }
    }
    setTimeout(repopulate, 600);
  }).catch(function () { continueSession(sessionId, lane); });
}

// _triggerOrientation: fire the read-only plan-mode orientation one-shot job for
// a resumed session (telemetry-resume W6 orientation fork). Best-effort — the
// escalation never blocks on it, and NOTHING is auto-submitted to the live PTY
// (orientation is a separate read-only job; any ACTION prompt stays paste-NOT-
// submit).
function _triggerOrientation(sessionId, lane) {
  try {
    _postJson('/api/rnd/orient_session',
              {project_id: PROJECT_ID, lane: lane || '', session: sessionId})
      .catch(function () {});
  } catch (e) {}
}

// _fillPastSessionDetail: fetch the cached session summary and render the
// skill/prompts/produced-files (v5 Wave 2). Read-only; honest placeholders for
// absent fields. The summary GET returns the full cached structured dict, so the
// new skill/prompts/actions fields ride along.
function _fillPastSessionDetail(sessionId, lane, detail, _tries) {
  if (!detail) return;
  // v8 Wave 5 — a just-killed session's durable summary is generated in the
  // BACKGROUND (kill schedules it). The GET returns status:'generating' until it
  // lands, so we poll a bounded number of times before painting the honest
  // "being generated" placeholder — the detail then shows the REAL produced
  // docs/summary as soon as it caches (no-loss close-out), not a dead-end.
  _tries = _tries || 0;
  var sUrl = '/api/rnd/session_summary?pid=' + encodeURIComponent(PROJECT_ID)
    + '&lane=' + encodeURIComponent(lane)
    + '&session=' + encodeURIComponent(sessionId);
  fetch(sUrl, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var summ = (d && d.status === 'ready' && d.summary) ? d.summary : null;
      if (!summ && d && d.status === 'generating' && _tries < 20) {
        setTimeout(function () {
          _fillPastSessionDetail(sessionId, lane, detail, _tries + 1);
        }, 500);
        return;
      }
      detail.innerHTML = _renderPastSession(summ);
    })
    .catch(function () {
      detail.innerHTML = '<div class="ro-note">Summary unavailable.</div>';
    });
}

// _renderPastSession(summary): the skill/prompts/produced-files block for a
// historical session's read-only body. Every section is honest — absent data
// renders an explicit placeholder, never fabricated content.
function _renderPastSession(summary) {
  if (!summary) {
    return '<div class="ro-note">No cached summary yet for this session — '
      + 'it is being generated. Reopen shortly, or continue it live above.</div>';
  }
  var out = [];
  var skill = (summary.skill || '').trim ? (summary.skill || '').trim() : summary.skill;
  out.push('<div class="ro-sec"><span class="ro-k">Skill invoked</span><span>'
    + (skill ? _esc(skill) : '<i>not recorded</i>') + '</span></div>');
  var prompts = summary.prompts || [];
  out.push('<div class="ro-sec"><span class="ro-k">Prompts asked</span></div>');
  if (prompts.length) {
    var pl = ['<ul class="ro-list">'];
    for (var i = 0; i < prompts.length; i++)
      pl.push('<li>' + _esc(prompts[i]) + '</li>');
    pl.push('</ul>');
    out.push(pl.join(''));
  } else {
    out.push('<div class="ro-note"><i>No prompts recorded for this session.</i></div>');
  }
  var actions = summary.actions || [];
  out.push('<div class="ro-sec"><span class="ro-k">Files produced</span></div>');
  if (actions.length) {
    var al = ['<ul class="ro-list">'];
    for (var j = 0; j < actions.length; j++) {
      var a = actions[j];
      var lbl = (a && (a.label || a.rel || a.job_id)) || '';
      al.push('<li>' + _esc(lbl) + '</li>');
    }
    al.push('</ul>');
    out.push(al.join(''));
  } else {
    out.push('<div class="ro-note"><i>No files recorded for this session.</i></div>');
  }
  return out.join('');
}

// resumeDiscovered(ev, sessionId, lane): W4 (#6 UI) — resume a DISCOVERED/
// brownfield effort tile as a WARM live session. A discovered effort has no
// managed session, so we reuse the continueSession path: POST
// /api/rnd/continue_session with the discovered session id as the source. The
// server's _build_continue_seed SYNTHESIZES a warm seed from the on-disk docs
// (W3 #6 backend — detected phase + trio skill + doc list), so start_session
// opens with the skill loaded and the documents read, not a cold terminal.
// stopPropagation so the tile's read-only panel does not also open underneath.
function resumeDiscovered(ev, sessionId, lane) {
  if (ev && ev.stopPropagation) ev.stopPropagation();
  continueSession(sessionId, lane);
}

// continueSession(sessionId, lane): v5 Wave 2 — POST /api/rnd/continue_session
// (token-authed) to start a NEW live session in the SAME lane, seeded with the
// prior session's summary/context. The ORIGINAL session is never mutated. On
// success the new session is added to MANAGED and its panel opened/attached
// (reusing the live-session panel path).
async function continueSession(sessionId, lane) {
  var payload = {project_id: PROJECT_ID, lane: lane, source_session: sessionId,
                 backend: 'claude'};
  var r, data;
  try {
    r = await _postJson('/api/rnd/continue_session', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/continue_session', payload);
      data = await r.json();
    }
  } catch (e) { alert('[continue error] ' + e.message); return; }
  if (!data || !data.ok || !data.session) {
    alert('[continue refused] ' + ((data && (data.error || data.reason)) || 'unknown'));
    return;
  }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {
    session_id: sid, lane: rec.lane || lane, backend: rec.backend || 'claude',
    status: rec.status || 'running', label: rec.label || '',
    idx: (_laneCounters[rec.lane || lane] = (_laneCounters[rec.lane || lane] || 0) + 1)
  };
  // W3 reuse-not-sibling: remember which live session this effort resumed into,
  // so a later '▶ Resume live' focuses it instead of spawning a second sibling.
  if (sid !== sessionId) _RESUMED_FROM[sessionId] = sid;
  renderSessionBar();
  // v12 W10 — if the source was opened in the bottom DOCK (the effort surface),
  // continue IN the dock: re-bind it to the new live session (a NEW tile lands on
  // the board via refreshBoard, preserving the new-tile-per-session invariant).
  if (DOCK && DOCK.session_id === sessionId) {
    refreshBoard();
    setTimeout(function () {
      var tile = document.querySelector(
        '.tile[data-session="' + _cssEsc(sid) + '"]');
      openEffortDock(sid, tile);
    }, 300);
    setTimeout(repopulate, 600);
    return;
  }
  // v10.1 FIX 1 — Restart-in-place: the cockpit's only terminal surface is an
  // inline panel in #panelStack. continueSession mints a BRAND-NEW session id,
  // so openPanel(sid) would stack a SECOND panel below the still-open source.
  // Instead: carry the source panel's geometry onto the new id, open the new
  // panel, then _closePanel the SOURCE (tears down its DOM/transport ONLY —
  // never the MANAGED record or the lane/board tile, so the source session
  // stays reopenable). The new session keeps its own board tile (the v6
  // new-tile-per-session invariant is preserved). NEVER killPanel/term_kill
  // (those reap the worktree/record).
  if (_panelRects[sessionId] && !_panelRects[sid]) _panelRects[sid] = _panelRects[sessionId];
  if (_panelHeights[sessionId] && !_panelHeights[sid]) _panelHeights[sid] = _panelHeights[sessionId];
  openPanel(sid);
  if (sid !== sessionId) _closePanel(sessionId);
  setTimeout(repopulate, 600);
}

// advanceSession(sourceId, toLane): v6 Wave 5 — MANUAL advance research →
// planning. POST /api/rnd/advance_session (token-authed) to start a NEW LINKED
// session in toLane (defaults 'planning'), seeded with the SOURCE session's
// grounded summary/report; the SOURCE record is never mutated (server reuses the
// read-only continue-seed builder). On success the new session is added to
// MANAGED and its panel opened (reusing the continueSession success path); the
// new tile lands in the SAME chain as the source.
async function advanceSession(sourceId, toLane) {
  toLane = toLane || 'planning';
  var payload = {project_id: PROJECT_ID, source_session: sourceId, to_lane: toLane};
  var r, data;
  try {
    r = await _postJson('/api/rnd/advance_session', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/advance_session', payload);
      data = await r.json();
    }
  } catch (e) { alert('[advance error] ' + e.message); return; }
  if (!data || !data.ok || !data.session) {
    alert('[advance refused] ' + ((data && (data.error || data.reason)) || 'unknown'));
    return;
  }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {
    session_id: sid, lane: rec.lane || toLane, backend: rec.backend || 'claude',
    status: rec.status || 'running', label: rec.label || '',
    chain_id: rec.chain_id || '', parent_session_id: rec.parent_session_id || sourceId,
    idx: (_laneCounters[rec.lane || toLane] = (_laneCounters[rec.lane || toLane] || 0) + 1)
  };
  renderSessionBar();
  openPanel(sid);
  // v10 Wave 2: the next-stage prompt is delivered PASTED-but-UNSENT (pending
  // paste, flushed by the terminal transport after the skill greets). Hint the
  // user that it is sitting in the input line for review — nothing was submitted.
  _flashPendingPasteHint(sid);
  // v7 Wave 6: instant-in-column tile for the advanced (build) session.
  refreshBoard();
  setTimeout(repopulate, 600);
}

// finishToBuild(planningId): v6 Wave 9 (polish 1) — the explicit, NON-destructive
// plan→build advance. POSTs /api/rnd/finish_to_build (token-gated): the server
// captures the plan set, marks THIS planning session done WITHOUT reaping its
// worktree (it stays a reopenable finished tile — close-to-tile philosophy), then
// auto-advances to ONE linked build (idempotent server-side). On success we mint
// the build tile (_addAutoBuildTile + note, the SAME path the hard-kill auto-build
// uses) and move the planning session to a greyed FINISHED tile (reusing the
// Wave-4 finished-tile path). With NO plan set the server honestly returns
// auto_build:null + a reason → we show a small note and create no build.
async function finishToBuild(planningId) {
  var payload = {project_id: PROJECT_ID, session: planningId};
  var r, data;
  try {
    r = await _postJson('/api/rnd/finish_to_build', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/finish_to_build', payload);
      data = await r.json();
    }
  } catch (e) { alert('[finish→build error] ' + e.message); return; }
  if (!data || !data.ok) {
    alert('[finish→build refused] '
      + ((data && (data.error || data.reason)) || 'unknown'));
    return;
  }
  if (data.auto_build && data.auto_build.session_id) {
    // Move the planning session to a finished (greyed, reopenable) tile — it is
    // DONE but its worktree/record persist (non-destructive). Then mint the build.
    _finishPlanningTile(planningId);
    _addAutoBuildTile(data.auto_build);
  } else {
    // Honest: no plan set yet → nothing to build. Surface a small inline note on
    // the planning panel's finish bar (no tile is created, the session stays live).
    _flashNoPlanNote(planningId, (data.reason || 'no plan set yet'));
  }
  // v7 Wave 6: refresh the board so the planning→finished + new build tiles
  // (the lane-column tiles) update instantly without a page reload.
  refreshBoard();
  setTimeout(repopulate, 600);
}

// _finishPlanningTile(sessionId): move a now-DONE planning session from the LIVE
// (MANAGED) map to the FINISHED map (greyed, reopenable tile — Wave-4 path) and
// close its open panel. The registry record + worktree are KEPT server-side (the
// finish was non-destructive); repopulate() will re-confirm it as a terminal tile.
function _finishPlanningTile(sessionId) {
  var s = MANAGED[sessionId];
  if (s) {
    FINISHED[sessionId] = {
      session_id: sessionId, lane: s.lane || 'planning',
      backend: s.backend || '', status: 'done', label: s.label || '',
      created_at: s.created_at || 0, chain_id: s.chain_id || '',
      parent_session_id: s.parent_session_id || '', idx: s.idx || 0
    };
    delete MANAGED[sessionId];
  }
  _closePanel(sessionId);
  renderSessionBar();
}

// _flashNoPlanNote(sessionId, reason): when finish→build finds no plan set, show
// a brief honest note in the planning panel's finish bar (no build fabricated).
function _flashNoPlanNote(sessionId, reason) {
  try {
    var p = PANELS[sessionId];
    var bar = p && p.el ? p.el.querySelector('.fbbar') : null;
    if (!bar) return;
    var old = bar.querySelector('.fbnote');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var note = document.createElement('span');
    note.className = 'fbnote';
    note.textContent = 'No plan set yet — nothing to build (' + reason + ')';
    bar.appendChild(note);
    setTimeout(function () {
      if (note && note.parentNode) note.parentNode.removeChild(note);
    }, 6000);
  } catch (e) { /* advisory only */ }
}

// Per-session terminal-pane height (in-memory persistence across minimize /
// re-open within this page load). Keyed by session_id → CSS height string.
var _panelHeights = {};
// v6 Wave 3: per-session PANEL rect (the freely-resized .pin body's CSS width +
// height). Keyed by session_id → {w, h}. Restored on re-open; NOT applied while
// the panel is maximized (maxd) so restore returns to the pre-maximize size.
var _panelRects = {};

// _loadPanelSummary(sessionId, host): fill the split summary — materials LEFT
// (.smat: goal / North-Star / what-was-asked / effort) from the cached session
// summary, role-tagged doc links RIGHT (.slinks) from session_doc_roles. Both
// fetches are read-only; absent fields / roles are simply not rendered. The
// terminal mounts regardless (the summary is advisory chrome).
function _loadPanelSummary(sessionId, host) {
  if (!host) return;
  // The lane comes from the MANAGED record for a live session, else from the
  // page tile (historical/discovered) so the summary/doc-roles fetch keys on the
  // right (pid, lane, session).
  var s = MANAGED[sessionId] || _synthSessionRecord(sessionId);
  var lane = (s && s.lane) || '';
  // session_id here is the MANAGED (live-terminal) id; its lane is the trio lane
  // (research/plan/build). The summary/doc-roles endpoints key on (pid, lane,
  // session). A live terminal session may have no cached trio-session summary
  // yet — that's fine; we render whatever resolves and omit the rest.
  var sUrl = '/api/rnd/session_summary?pid=' + encodeURIComponent(PROJECT_ID)
    + '&lane=' + encodeURIComponent(lane)
    + '&session=' + encodeURIComponent(sessionId);
  var rUrl = '/api/rnd/session_doc_roles?pid=' + encodeURIComponent(PROJECT_ID)
    + '&lane=' + encodeURIComponent(lane)
    + '&session=' + encodeURIComponent(sessionId)
    + _tokenQ();
  var summary = null, roles = {}, buildDeliv = null;
  function _paint() {
    host.innerHTML = _renderSplitSummary(summary, roles, lane, buildDeliv);
  }
  fetch(sUrl, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d && d.status === 'ready' && d.summary) summary = d.summary;
    })
    .catch(function () {})
    .then(function () { return fetch(rUrl, _jsonHdrs()); })
    .then(function (r) { return r.json(); })
    .then(function (d) { if (d && d.ok && d.roles) roles = d.roles; })
    .catch(function () {})
    .then(function () {
      // v5 Wave 4 — a BUILD session's panel surfaces ITS resolved deliverable
      // (or an honest "none yet" placeholder). Read-only; never fabricated.
      if (lane !== 'build') return null;
      var dUrl = '/api/rnd/build_deliverable?pid=' + encodeURIComponent(PROJECT_ID)
        + '&lane=build&session=' + encodeURIComponent(sessionId) + _tokenQ();
      return fetch(dUrl, _jsonHdrs())
        .then(function (r) { return r.json(); })
        .then(function (d) { if (d && d.ok) buildDeliv = d; })
        .catch(function () {});
    })
    .catch(function () {})
    .then(_paint);
}

// _renderSplitSummary(summary, roles, lane): the EQUAL-HEIGHT two-column split.
// LEFT (.smat) = materials; the effort line uses margin-top:auto so it sinks to
// the bottom. RIGHT (.slinks) = role-tagged doc links; a second link group (when
// present) uses .slh.two (margin-top:auto) so it pins to the bottom — making both
// columns fill the same height per the mockup.
function _renderSplitSummary(summary, roles, lane, buildDeliv) {
  var L = [];   // left materials
  // v5 Wave 4 — a BUILD panel shows ITS deliverable (resolved → a link; absent →
  // an honest placeholder). Rendered FIRST so it is prominent in the materials.
  if (lane === 'build' && buildDeliv) {
    if (buildDeliv.resolved && buildDeliv.deliverable) {
      var bd = buildDeliv.deliverable;
      L.push('<div class="bdeliv resolved"><span class="k">Deliverable</span>'
        + '<a class="doc" href="' + _esc(bd.href || '#')
        + '" target="anchor_report_window" '
        + 'rel="noopener">' + _esc(bd.name || bd.path || 'deliverable')
        + '<span class="role">' + _esc(bd.type || '') + '</span></a></div>');
    } else {
      L.push('<div class="bdeliv none">' + _esc(buildDeliv.reason
        || 'no deliverable pinned yet') + ' — pin one</div>');
    }
  }
  if (summary) {
    if (summary.title) L.push('<div class="sgoal">' + _esc(summary.title) + '</div>');
    if (summary.north_star) L.push('<div class="row"><span class="k">North Star</span><span>' + _esc(summary.north_star) + '</span></div>');
    if (summary.what_was_asked) L.push('<div class="row"><span class="k">Asked</span><span>' + _esc(summary.what_was_asked) + '</span></div>');
    if (summary.when_run) L.push('<div class="row"><span class="k">When run</span><span>' + _esc(summary.when_run) + '</span></div>');
    var eff = '';
    if (summary.hasOwnProperty('effort')) {
      if (summary.effort === null) eff = 'imported — no run metrics';
      else if (summary.effort) {
        var secs = ((summary.effort.wall_clock_ms || 0) / 1000).toFixed(1);
        eff = _esc(summary.effort.tokens || 0) + ' tokens · ' + secs + 's wall-clock · '
          + _esc(summary.effort.runs || 0) + ' run(s)';
      }
    }
    if (eff) L.push('<div class="effbar">' + eff + '</div>');
  }
  if (!L.length) L.push('<div class="summ-loading">No cached summary for this session yet.</div>');

  // RIGHT: role-tagged links. Roles split into a primary group + a secondary
  // (.two) group so both columns fill equal height (locked CSS).
  var primary = [], secondary = [];
  var groups = _DOC_ROLE_GROUPS[lane] || {};
  for (var role in roles) {
    if (!roles.hasOwnProperty(role)) continue;
    var lk = roles[role];
    var html = '<a class="doc" href="' + _esc(lk.href)
      + '" target="anchor_report_window" '
      + 'rel="noopener">' + _esc(lk.label || role)
      + '<span class="role">' + _esc(role) + '</span></a>';
    if ((groups.two || []).indexOf(role) >= 0) secondary.push(html);
    else primary.push(html);
  }
  var R = [];
  if (primary.length) {
    R.push('<div class="slh">' + _esc(groups.primary_label || 'Documents') + '</div>');
    R = R.concat(primary);
  }
  if (secondary.length) {
    R.push('<div class="slh two">' + _esc(groups.two_label || 'More') + '</div>');
    R = R.concat(secondary);
  }
  var right = R.length ? ('<div class="slinks">' + R.join('') + '</div>') : '';
  return '<div class="smat">' + L.join('') + '</div>' + right;
}

// Per-lane role grouping for the split's two link groups (primary + .two). The
// secondary group pins to the bottom (.slh.two) so both columns share height.
var _DOC_ROLE_GROUPS = {
  research: {primary_label: 'Research outputs', two_label: 'Provenance',
            two: ['provenance']},
  planning: {primary_label: 'Plan documents', two_label: 'Objective',
            two: ['northstar']},
  plan: {primary_label: 'Plan documents', two_label: 'Objective',
        two: ['northstar']},
  build: {primary_label: 'Build outputs', two_label: 'Plan it executes',
         two: ['northstar', 'plan']}
};

// _wirePanelResize(sessionId, tpane): v6 Wave 3 — the WHOLE panel is freely
// resizable: the .pin body carries CSS `resize:both`, so the browser draws a
// corner drag handle and the user can resize the panel to any width+height
// (the inner .tpane also still has its own bottom-edge handle). We watch BOTH
// boxes with ResizeObservers: on a .pin change persist the panel rect (w+h) in
// _panelRects (skipping while maximized) and re-fit the terminal; on a .tpane
// change persist the terminal height and re-fit. Falls back to no-op if
// ResizeObserver is unavailable (the CSS resize still works visually).
function _wirePanelResize(sessionId, tpane) {
  var p = PANELS[sessionId];
  if (!p || !tpane || typeof ResizeObserver === 'undefined') return;
  var ro = new ResizeObserver(function () {
    _panelHeights[sessionId] = tpane.style.height || (tpane.offsetHeight + 'px');
    _fitPanelTerminal(sessionId);
  });
  ro.observe(tpane);
  p.ro = ro;
  // The .pin free-resize box → persist the panel rect + re-fit on every change.
  if (p.pin) {
    var pro = new ResizeObserver(function () {
      if (!p.maxd) {
        _panelRects[sessionId] = {
          w: p.pin.style.width || (p.pin.offsetWidth + 'px'),
          h: p.pin.style.height || (p.pin.offsetHeight + 'px')
        };
      }
      _fitPanelTerminal(sessionId);
    });
    pro.observe(p.pin);
    p.pinRo = pro;
  }
}

// maximizePanel(sessionId): v6 Wave 3 — toggle the panel to fill the cockpit
// viewport (.panel.maxd: a fixed full-screen overlay) and back to its prior
// freely-resized rect. On BOTH the maximize and the restore we re-fit the xterm
// terminal (twice — immediately + after the layout settles) so cols/rows track
// the new area and the terminal never freezes or clips. The session keeps
// running throughout — this only changes the panel's geometry.
function maximizePanel(sessionId) {
  var p = PANELS[sessionId];
  if (!p || !p.el) return;
  // A maximize on a minimized panel first re-expands it (so there's something
  // to fill the screen with).
  if (p.el.classList.contains('minimized')) p.el.classList.remove('minimized');
  if (!p.maxd) {
    // Remember the freely-resized rect so restore returns to it exactly, then
    // clear the inline size so .panel.maxd's fixed fill takes over.
    if (p.pin) {
      p._restoreRect = {w: p.pin.style.width, h: p.pin.style.height};
      p.pin.style.width = '';
      p.pin.style.height = '';
    }
    p.el.classList.add('maxd');
    p.maxd = true;
  } else {
    p.el.classList.remove('maxd');
    p.maxd = false;
    // Restore the pre-maximize rect (if any).
    if (p.pin && p._restoreRect) {
      if (p._restoreRect.w) p.pin.style.width = p._restoreRect.w;
      if (p._restoreRect.h) p.pin.style.height = p._restoreRect.h;
    }
  }
  // Re-fit now and again after the geometry change paints (xterm needs the new
  // host size to recompute cols/rows; the ResizeObserver also fires, but we call
  // explicitly so the fit happens even on browsers that batch RO callbacks).
  _fitPanelTerminal(sessionId);
  setTimeout(function () { _fitPanelTerminal(sessionId); }, 60);
}

// _fitPanelTerminal(sessionId): re-fit the xterm to its host then push the new
// cols/rows to the PTY via term_resize (the existing transport endpoint). Uses
// the xterm fit addon when present; otherwise relies on the onResize hook the
// mounted terminal already wires to term_resize.
function _fitPanelTerminal(sessionId, rec) {
  var p = rec || PANELS[sessionId];
  if (!p || !p.term) return;
  try {
    if (p.fit && p.fit.fit) {
      p.fit.fit();              // triggers term.onResize → term_resize
    } else if (p.term.resize) {
      // No fit addon: compute BOTH cols and rows from the host so the terminal
      // fills the FULL panel width (xterm defaults to 80 cols → only the left
      // ~third of a wide panel) and reflows on vertical resize. ~7.2px/char,
      // ~17px/row at 12px monospace.
      var host = p.body;
      // v10.1 FIX 4 — collapse/zero-size guard: a collapsed/hidden host (e.g.
      // `.gterm.collapsed .term-host{display:none}`) has no offsetParent / zero
      // box; bail so we don't compute a degenerate cols/rows + spam term_resize.
      if (!host || host.offsetParent === null
          || host.clientHeight === 0 || host.clientWidth === 0) return;
      var hw = (host && host.clientWidth) || 600;
      var hh = (host && host.clientHeight) || 90;
      var cols = Math.max(20, Math.floor((hw - 8) / 7.2));
      var rows = Math.max(4, Math.floor((hh - 4) / 17));
      p.term.resize(cols, rows);   // triggers onResize → term_resize
    }
  } catch (e) {}
}

// _fitPanelTerminalDeferred(): fit a freshly-opened terminal to its column
// AFTER the browser has committed layout. The bug this fixes: on open the host
// is frequently NOT yet laid out — offsetParent === null / clientWidth === 0 —
// so _fitPanelTerminal bails and xterm stays at its constructor default of 80
// cols (≈ the left third of a wide column); or the panel's ancestors haven't
// stretched yet so we measure the `.pin` min-width (~360px) instead of its
// settled width:100%. A synchronous fit + a fixed setTimeout(60/80ms) races
// both — which is why the terminal only filled ~1/3 on open and "fixed itself"
// on a later resize (when the ResizeObserver refired post-layout). This waits
// on requestAnimationFrame until the host reports a real (non-zero, visible)
// width, then fits across a few consecutive frames so a late min-width→100% /
// column reflow is also caught. xterm.resize no-ops when cols/rows are
// unchanged, so the extra frames are free. Bounded so it can never spin.
function _fitPanelTerminalDeferred(sessionId, rec) {
  if (typeof requestAnimationFrame === 'undefined') {
    // No rAF (shouldn't happen in a browser) — fall back to the old timing.
    _fitPanelTerminal(sessionId, rec);
    setTimeout(function () { _fitPanelTerminal(sessionId, rec); }, 80);
    return;
  }
  var tries = 0;         // frames spent waiting for the host to lay out (~0.7s cap)
  function attempt() {
    var p = rec || PANELS[sessionId];
    if (!p || !p.term) return;                       // panel torn down — stop
    var host = p.body;
    var ready = host && host.offsetParent !== null
                && host.clientHeight > 0 && host.clientWidth > 0;
    if (!ready) {
      if (++tries > 40) return;                      // give up quietly (~0.7s)
      requestAnimationFrame(attempt);
      return;
    }
    // Layout committed with a real width — fit ONCE. Any LATER reflow (a
    // min-width→100% settle, a splitter drag, a window resize) is caught by
    // the per-host ResizeObserver (w.fitRo) wired in _mountTerminal, so we do
    // NOT keep re-fitting on a timer here: repeated fits emit a term_resize
    // POST every frame, which races window-reuse/teardown (continueSession
    // swaps the session in the slot) and 404s on the swapped-out session.
    _fitPanelTerminal(sessionId, rec);
  }
  requestAnimationFrame(attempt);
}

// _tokenQ(): the ?token= suffix for read-only GET endpoints that gate via the
// query param (same semantics as the WS/SSE transport token).
function _tokenQ() {
  var tok = _anchorToken();
  return tok ? ('&token=' + encodeURIComponent(tok)) : '';
}

// Shared Accept-JSON headers object (one definition avoids a literal double
// close-brace in nested fetch-option object literals — the served-HTML
// brace-hygiene contract for this RAW single-brace string).
var _ACCEPT_JSON = {Accept: 'application/json'};
function _jsonHdrs() { return {headers: _ACCEPT_JSON}; }

// ── refreshBoard (v7 Wave 6) ────────────────────────────────────────────────
// Instant-in-column board refresh. After a session-lifecycle mutation (start /
// finish / advance / promote / develop) the SERVER-rendered 5-lane board is the
// single source of truth for the lane-column tiles, so we just re-fetch the
// board fragment (GET /api/rnd/board_html, ?token=) and swap #kanbanBoard's
// innerHTML in place — no full page reload. Because the tile comes from the
// server render (NOT JS-injected), dedupe stays correct: a started session
// shows EXACTLY ONE tile in its lane column. Guarded so it never throws into
// the UI (a failed refresh just leaves the prior board until the next refresh /
// reload). The top live strip (renderSessionBar) is unaffected — it stays the
// instant chip view for live managed sessions; this only refreshes the columns.
async function refreshBoard() {
  try {
    var url = '/api/rnd/board_html?project_id=' + encodeURIComponent(PROJECT_ID) + _tokenQ();
    var r = await fetch(url, Object.assign({cache: 'no-store'}, _jsonHdrs()));
    if (!r || !r.ok) return;
    var data = await r.json();
    if (!data || !data.ok || typeof data.html !== 'string') return;
      var filesOpen = false;
      var detailEl = document.getElementById('projectFilesDetails');
      if (detailEl) {
        filesOpen = detailEl.open;
      }
      var openStates = { details: {}, classes: {} };
      var detailsEls = document.querySelectorAll('#kanbanBoard details');
      for (var i = 0; i < detailsEls.length; i++) {
        var key = detailsEls[i].id || detailsEls[i].className;
        if (key) openStates.details[key] = detailsEls[i].open;
      }
      var openEls = document.querySelectorAll('#kanbanBoard .open');
      for (var i = 0; i < openEls.length; i++) {
        var idAttr = openEls[i].id || openEls[i].getAttribute('data-run') || openEls[i].getAttribute('data-window') || openEls[i].className;
        if (idAttr) openStates.classes[idAttr] = true;
      }
      
      var openGandalfRuns = {};
      var gruns = document.querySelectorAll('#gandalfPanel .grun.open');
      for (var i = 0; i < gruns.length; i++) {
        var runId = gruns[i].getAttribute('data-run');
        var gexec = gruns[i].querySelector('.gexec');
        if (runId && gexec && gexec.getAttribute('data-loaded') === '1') {
          openGandalfRuns[runId] = gexec.innerHTML;
        }
      }
      var board = document.getElementById('kanbanBoard');
      if (!board) return;                    // guard: container absent
      board.innerHTML = data.html;
      var newDetailEl = document.getElementById('projectFilesDetails');
      if (newDetailEl && filesOpen) {
        newDetailEl.open = true;
      }
      var newDetailsEls = document.querySelectorAll('#kanbanBoard details');
      for (var i = 0; i < newDetailsEls.length; i++) {
        var key = newDetailsEls[i].id || newDetailsEls[i].className;
        if (key && openStates.details[key] !== undefined) {
          newDetailsEls[i].open = openStates.details[key];
        }
      }
      var newOpenEls = document.querySelectorAll('#kanbanBoard *');
      for (var i = 0; i < newOpenEls.length; i++) {
        var idAttr = newOpenEls[i].id || newOpenEls[i].getAttribute('data-run') || newOpenEls[i].getAttribute('data-window') || newOpenEls[i].className;
        if (idAttr && openStates.classes[idAttr]) {
          newOpenEls[i].classList.add('open');
        }
      }

      for (var runId in openGandalfRuns) {
        var el = document.querySelector('#gandalfPanel .grun[data-run="' + runId + '"]');
        if (el) {
          el.classList.add('open');
          var gexec = el.querySelector('.gexec');
          if (gexec) {
            gexec.setAttribute('data-loaded', '1');
            gexec.innerHTML = openGandalfRuns[runId];
          }
        }
      }
    // v10 Wave 4 FIX 2/3: the swapped-in board re-emits "from grass" chip stubs;
    // resolve them (label/dead-state) against the loaded grass data. If grass
    // data isn't loaded yet, fetch it (which itself re-resolves on completion).
    try {
      if (_grassData && Object.keys(_grassData).length) {
        _resolveGrassOriginChips(board);
      } else {
        _loadGrassData();
      }
    } catch (e) {}
  } catch (e) { /* never throw into the UI */ }
}

// minimizePanel: collapse the panel back to a header-only strip. The session and
// its terminal transport keep RUNNING — this only hides the panel body.
function minimizePanel(sessionId) {
  var p = PANELS[sessionId];
  if (!p || !p.el) return;
  p.el.classList.add('minimized');
  renderSessionBar();
}

// _closePanel: tear down the panel DOM + transport WITHOUT killing the session
// (used by close-to-tile, and when the registry no longer reports a session, e.g.
// after a kill). It NEVER touches the MANAGED record or the lane tile — the
// session stays reopenable from its tile.
function _closePanel(sessionId) {
  var p = PANELS[sessionId];
  if (!p) return;
  try { if (p.ro && p.ro.disconnect) p.ro.disconnect(); } catch (e) {}
  try { if (p.pinRo && p.pinRo.disconnect) p.pinRo.disconnect(); } catch (e) {}
  try { if (p.fitRo && p.fitRo.disconnect) p.fitRo.disconnect(); } catch (e) {}  // v10.1 FIX 4
  try { if (p.transport && p.transport.close) p.transport.close(); } catch (e) {}
  try { if (p.term && p.term.dispose) p.term.dispose(); } catch (e) {}
  if (p.el && p.el.parentNode) p.el.parentNode.removeChild(p.el);
  delete PANELS[sessionId];
}

// closePanel: the panel "×" = GRACEFUL CLOSE (crucible-improve W6). Stops the
// live PTY but PRESERVES the worktree + KEEPS the registry record — the session
// is PARKED (STATUS_IDLE, grey, reopenable), NOT killed. POST /api/rnd/term_close
// persists the produced docs into MAIN (so the boot reaper can't lose them and
// the W3 resume seed reads them) + schedules a background session-summary, so a
// later resume (click the tile) opens WARM, not cold. The tile is NOT removed —
// the record persists. Best-effort: a 404 (no live PTY / historical panel) or any
// error still tears down the panel DOM. The board is refreshed so the now-parked
// tile reflects its idle (grey) status.
async function closePanel(sessionId) {
  try {
    var r = await _postJson('/api/rnd/term_close', {session: sessionId});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      await _postJson('/api/rnd/term_close', {session: sessionId});
    }
  } catch (e) { /* best-effort; still tear down the panel DOM */ }
  _closePanel(sessionId);
  renderSessionBar();
  // Reflect the parked (idle/grey) tile — the record persists, so the tile stays.
  refreshBoard();
}

// _removeSessionTile: drop the lane-board tile for a session from the DOM (used by
// the deliberate hard-kill only — close-to-tile NEVER removes a tile). Removes the
// most-recent visible tile AND any tile inside a "previous sessions" expander.
function _removeSessionTile(sessionId) {
  var sel = '.tile[data-session="' + _cssEsc(sessionId) + '"]';
  var tiles = document.querySelectorAll(sel);
  for (var i = 0; i < tiles.length; i++) {
    var el = tiles[i];
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }
}

// killPanel: the panel "🗑 Kill" = deliberate HARD-KILL, gated behind a confirm().
// Only on YES do we POST /api/rnd/term_kill (reap PTY + remove worktree + mark the
// registry record terminal), then tear down the panel, drop the MANAGED record AND
// remove the session's lane tile so it's gone. For a historical/non-live session
// the server returns 404 (unknown-session) — that's fine; we STILL remove the
// tile + record cleanly (no orphan). (Minimize/close, by contrast, never kill.)
async function killPanel(sessionId, skipConfirm) {
  var s = MANAGED[sessionId];
  var name = s ? (s.label || (s.lane + ' ' + s.idx)) : sessionId;
  if (!skipConfirm && !confirm('Are you sure? Kill the "' + name + '" session? This terminates its process and removes its tile.')) return;
  var autoBuild = null;
  try {
    var r = await _postJson('/api/rnd/term_kill', {session: sessionId});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_kill', {session: sessionId});
      data = await r.json();
    }
    // A 404 unknown-session (historical tile with no live PTY) is NOT an error
    // for kill — there is simply no process to reap; we still drop the tile.
    // v6 Wave 6: killing a PLANNING session that produced a real plan set
    // auto-opens a linked BUILD session (server-side). Surface its new tile.
    if (data && data.auto_build) autoBuild = data.auto_build;
  } catch (e) { alert('[kill error] ' + e.message); }
  _KILLED[sessionId] = 1;       // v6 Wave 4: suppress this id from future repopulate
  _closePanel(sessionId);
  delete MANAGED[sessionId];
  delete FINISHED[sessionId];   // v6 Wave 4: also evict a finished tile if killed
  _removeSessionTile(sessionId);
  renderSessionBar();
  // v6 Wave 6: mint the auto-opened build tile (new MANAGED entry + bar) and
  // open its panel, with a tiny "auto-opened from this plan" note.
  if (autoBuild && autoBuild.session_id) {
    _addAutoBuildTile(autoBuild);
  }
  // v7 Wave 6: re-fetch the server-rendered board so the killed session's tile
  // is dropped (and any auto-opened build tile appears) instantly, no reload.
  refreshBoard();
  setTimeout(repopulate, 400);
}

// deletePanel: the panel red "✕" = TRUE DELETE (v9 Wave 1), DISTINCT from kill.
// Confirm-gated. On YES we POST /api/rnd/term_delete {confirm:true} — the server
// hard-deletes the registry record + the session's effort pointer-records +
// cached summary (the produced DOCUMENTS are KEPT on disk — Option A). Then we
// tear down the panel, drop the MANAGED/FINISHED record, mark the id _DELETED
// (so an in-flight repopulate can't re-add it) and remove the lane tile. Because
// the registry record is GONE, term_sessions/the board no longer surface it — so
// it STAYS gone across a reload (the v6 key bug for kills is moot for delete).
async function deletePanel(sessionId) {
  var s = MANAGED[sessionId] || FINISHED[sessionId];
  var name = s ? (s.label || (s.lane + ' ' + s.idx)) : sessionId;
  if (!confirm('Are you sure? This permanently removes the "' + name +
               '" session from Anchor (its registry record, effort records and ' +
               'cached summary). The produced documents are KEPT on disk. This ' +
               'cannot be undone.')) return;
  try {
    var r = await _postJson('/api/rnd/term_delete', {session: sessionId, confirm: true});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_delete', {session: sessionId, confirm: true});
      data = await r.json();
    }
  } catch (e) { alert('[delete error] ' + e.message); }
  _DELETED[sessionId] = 1;       // suppress this id from any future repopulate
  delete _KILLED[sessionId];
  _closePanel(sessionId);
  delete MANAGED[sessionId];
  delete FINISHED[sessionId];
  _removeSessionTile(sessionId);
  renderSessionBar();
  // Re-fetch the server-rendered board so the deleted session's tile is dropped
  // instantly (the registry record is gone → the board no longer renders it).
  refreshBoard();
  setTimeout(repopulate, 400);
}

// cleanupGhostSessions: v9 Wave 1 small "clear empty sessions" action — sweep the
// project's empty ghost (terminal/idle, no-effort) registry records. Confirm +
// token gated; refreshes the board on success.
async function cleanupGhostSessions() {
  if (!confirm('Clear empty sessions? This removes session records that produced ' +
               'nothing (no documents are affected).')) return;
  try {
    var r = await _postJson('/api/rnd/cleanup_ghost_sessions',
                            {project_id: PROJECT_ID, confirm: true});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/cleanup_ghost_sessions',
                          {project_id: PROJECT_ID, confirm: true});
      data = await r.json();
    }
    if (data && data.removed) {
      for (var i = 0; i < data.removed.length; i++) {
        _DELETED[data.removed[i]] = 1;
        _closePanel(data.removed[i]);
        delete MANAGED[data.removed[i]];
        delete FINISHED[data.removed[i]];
        _removeSessionTile(data.removed[i]);
      }
    }
  } catch (e) { alert('[cleanup error] ' + e.message); }
  renderSessionBar();
  refreshBoard();
  setTimeout(repopulate, 400);
}

// _addAutoBuildTile(rec): v6 Wave 6 — register the server-started auto-advance
// build session as a LIVE managed tile (same shape advanceSession uses), render
// the bar, open its panel, and flash a tiny "→ auto-opened Build from this plan"
// note so the user sees the planning→build hand-off happen.
function _addAutoBuildTile(rec) {
  var sid = rec.session_id;
  var lane = rec.lane || 'build';
  MANAGED[sid] = {
    session_id: sid, lane: lane, backend: rec.backend || 'claude',
    status: rec.status || 'running', label: rec.label || 'auto · from plan',
    chain_id: rec.chain_id || '', parent_session_id: rec.parent_session_id || '',
    auto_from_plan: true,
    idx: (_laneCounters[lane] = (_laneCounters[lane] || 0) + 1)
  };
  renderSessionBar();
  openPanel(sid);
  _flashAutoBuildNote(rec);
  // v10 Wave 2: the build prompt is a PENDING PASTE (unsent) — hint the user.
  _flashPendingPasteHint(sid);
}

// _flashAutoBuildNote(rec): a small, transient banner above the panel stack.
function _flashAutoBuildNote(rec) {
  try {
    var host = document.getElementById('panelStack') || document.body;
    var note = document.createElement('div');
    note.className = 'autobuild-note';
    note.setAttribute('data-session', rec.session_id);
    var which = 'Build ' + (rec.session_id || '').slice(0, 6);
    note.textContent = '→ auto-opened ' + which + ' from this plan';
    if (host.firstChild) host.insertBefore(note, host.firstChild);
    else host.appendChild(note);
    setTimeout(function () {
      if (note && note.parentNode) note.parentNode.removeChild(note);
    }, 6000);
  } catch (e) { /* the tile already landed; the note is advisory */ }
}

// _flashPendingPasteHint(sessionId): v10 Wave 2 — a subtle, transient hint above
// the panel stack telling the user the next-stage prompt is PASTED but UNSENT in
// the terminal input ("review & press Enter to run"). Nothing auto-submits; the
// prompt is the v10 pending paste, flushed UNSENT by the terminal transport read.
function _flashPendingPasteHint(sessionId) {
  try {
    var host = document.getElementById('panelStack') || document.body;
    var note = document.createElement('div');
    note.className = 'pendpaste-hint';
    note.setAttribute('data-session', sessionId || '');
    note.textContent = 'prompt ready — review & press Enter to run (nothing was submitted)';
    if (host.firstChild) host.insertBefore(note, host.firstChild);
    else host.appendChild(note);
    setTimeout(function () {
      if (note && note.parentNode) note.parentNode.removeChild(note);
    }, 8000);
  } catch (e) { /* advisory only */ }
}

// Mount xterm.js in the panel body host over the Wave-3 transport (UNCHANGED).
// Prefer the hand-rolled WebSocket (term_ws); fall back to SSE-out (term_stream2)
// + POST-in (term_input2). Bytes from read_since are decoded str sent as UTF-8.
function _mountTerminal(sessionId, body, rec) {
  // rec (v12 W10): the panel record to mount onto. Defaults to PANELS[sessionId]
  // (the inline-panel path). The bottom dock passes its own DOCK record so the
  // SAME transport + fit + observer logic drives the dock terminal.
  var w = rec || PANELS[sessionId];
  if (!w) return;
  if (!window.Terminal) {
    body.textContent = 'terminal component failed to load';
    return;
  }
  var _termTheme = {background: '#0c0e14'};
  var term = new window.Terminal({convertEol: true, fontSize: 12,
                                  theme: _termTheme, scrollback: 5000});
  term.open(body);
  w.term = term;
  w.body = body;
  var tok = _anchorToken();
  var tq = tok ? ('&token=' + encodeURIComponent(tok)) : '';

  // Fit to the host once layout is committed (xterm starts at 80 cols). The
  // rAF-until-visible loop replaces the old sync + setTimeout(60ms), which
  // raced the layout and left the terminal at ~1/3 column width on open.
  _fitPanelTerminalDeferred(sessionId, w);

  // v10.1 FIX 4 — make _mountTerminal self-sufficient about reflow. The board
  // path wires a ResizeObserver in _wirePanelResize, but the grass mounts never
  // call it, so an ENLARGED grass terminal (.gterm host is CSS resize:vertical)
  // grew but xterm never reflowed (nothing observed it → _fitPanelTerminal never
  // ran). Attach our OWN observer on the INNER host (`body` = the .term-host the
  // fit measures), stored on a DISTINCT key (w.fitRo, NOT p.ro — never clobber
  // the board's _wirePanelResize observer). Disconnect any prior fitRo first
  // (grass never calls _closePanel, so a re-develop would otherwise leak
  // observers). Idempotent for the board (same cols/rows → xterm no-ops).
  if (typeof ResizeObserver !== 'undefined') {
    try { if (w.fitRo && w.fitRo.disconnect) w.fitRo.disconnect(); } catch (e) {}
    var fro = new ResizeObserver(function () { _fitPanelTerminal(sessionId, w); });
    fro.observe(body);
    w.fitRo = fro;
  }

  // Outbound user keystrokes. Ordering fix (2026-07-08): characters were sent
  // as independent fire-and-forget POSTs to term_input2 that RACED — the browser
  // issues them on parallel connections and the threaded server writes each on
  // its own thread — so fast typing arrived at the PTY muddled/out of order.
  // Prefer the already-connected WebSocket: it is a single FIFO stream whose
  // frames the one server pump-loop applies to the PTY strictly in order. When
  // the WS isn't OPEN (SSE fallback / not yet upgraded) fall back to a
  // PROMISE-CHAINED POST queue so at most ONE term_input2 POST is in flight per
  // session (POST N resolves before POST N+1 is issued) — never two concurrent
  // writes. All input paths (keystrokes, paste) route through _sendInput so they
  // share the one ordered channel.
  var _sendChain = Promise.resolve();
  function _sendInput(d) {
    if (d === '' || d == null) return;
    var t = w.transport;
    if (t && typeof WebSocket !== 'undefined' && t instanceof WebSocket &&
        t.readyState === 1 /* OPEN */) {
      try { t.send(d); return; } catch (e) { /* fall through to POST */ }
    }
    _sendChain = _sendChain.then(function () {
      return _postJson('/api/rnd/term_input2', {session: sessionId, data: d});
    }).catch(function () {});
  }
  term.onData(function (d) { _sendInput(d); });
  // Keyboard paste: xterm emits Ctrl+V as the control byte \x16, so paste never
  // happened (only right-click, which uses the browser's native paste event).
  // Intercept Ctrl/Cmd+V → read the clipboard → term.paste (honors bracketed
  // paste so multi-line prompts don't run line-by-line). Ctrl+Shift+C copies a
  // selection. Everything else passes through unchanged.
  term.attachCustomKeyEventHandler(function (e) {
    if (e.type !== 'keydown') return true;
    var mod = e.ctrlKey || e.metaKey;
    if (mod && !e.altKey && (e.key === 'v' || e.key === 'V')) {
      if (navigator.clipboard && navigator.clipboard.readText) {
        navigator.clipboard.readText().then(function (t) {
          if (t) { try { term.paste(t); } catch (err) { _sendInput(t); } }
        }).catch(function () {});
      }
      return false;  // suppress the \x16 control byte
    }
    if (mod && e.shiftKey && (e.key === 'c' || e.key === 'C')) {
      var sel = term.getSelection && term.getSelection();
      if (sel && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(sel).catch(function () {});
        return false;
      }
    }
    return true;
  });
  // Resize → term_resize (best-effort, token-aware).
  term.onResize(function (sz) {
    _postJson('/api/rnd/term_resize',
              {session: sessionId, cols: sz.cols, rows: sz.rows});
  });

  // telemetry-resume W6 — the ATTACH-ACK / replay-complete handshake (diag-B2 S1
  // fix; NORTH-STAR-AMENDMENT Layer 2). The pane swaps in ONLY after the server's
  // 'replay_complete' control frame; a dead/unknown session yields 'attach_ack
  // ok:false' → an explicit styled ERROR STATE with a Retry control (the Layer-1
  // narration stays visible underneath), never a silent blank pane. A missing ack
  // within 5s falls to the SAME error state. Control frames ride the SAME authed
  // socket as a TEXT frame prefixed with WS_CTL_PREFIX (opaque PTY bytes never
  // start with a NUL), so terminal bytes and control messages are unambiguous.
  var WS_CTL_PREFIX = '\x00ANCHOR-CTL:';
  var attached = false;
  var ackTimer = null;
  // A styled attach overlay over the terminal until replay-complete lands.
  var overlay = document.createElement('div');
  overlay.className = 'term-attach';
  overlay.innerHTML = '<div class="term-attach-msg">connecting to live '
    + 'session…</div>';
  try { body.appendChild(overlay); } catch (e) {}
  function _clearAckTimer() { if (ackTimer) { clearTimeout(ackTimer); ackTimer = null; } }
  function _attachOk() {
    attached = true; _clearAckTimer();
    try { if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay); } catch (e) {}
    try { _fitPanelTerminal(sessionId, w); } catch (e) {}
  }
  function _attachError(reason) {
    _clearAckTimer();
    if (attached) return;  // already live — a later close is not an attach error
    try { if (w.transport && w.transport.close) w.transport.close(); } catch (e) {}
    overlay.className = 'term-attach term-attach-err';
    overlay.innerHTML = '<div class="term-attach-msg">Could not attach a live '
      + 'terminal (' + _esc(reason || 'no response') + '). The warm view below '
      + 'is still available.</div>'
      + '<button class="term-attach-retry" type="button">Retry</button>';
    var rb = overlay.querySelector('.term-attach-retry');
    if (rb) rb.onclick = function (e) {
      e.stopPropagation();
      try { if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay); } catch (er) {}
      try { if (w.term && w.term.dispose) w.term.dispose(); } catch (er) {}
      _mountTerminal(sessionId, body, rec);  // one-click retry, same window
    };
  }
  ackTimer = setTimeout(function () {
    if (!attached) _attachError('timeout');
  }, 5000);

  // Transport: try WebSocket first; on error fall back to the SSE stream.
  var wsProto = (location.protocol === 'https:') ? 'wss:' : 'ws:';
  var wsUrl = wsProto + '//' + location.host +
              '/api/rnd/term_ws?session=' + encodeURIComponent(sessionId) + tq;
  var sseStarted = false;
  function startSSE() {
    if (sseStarted) return;
    sseStarted = true;
    var sseUrl = '/api/rnd/term_stream2?session=' + encodeURIComponent(sessionId) + tq;
    var es = new EventSource(sseUrl);
    w.transport = es;
    // Mirror the WS handshake over SSE control events.
    es.addEventListener('attach_ack', function (ev) {
      try { var p = JSON.parse(ev.data); if (p && p.ok === false) {
        _attachError(p.reason || 'unknown-session'); } } catch (e) {}
    });
    es.addEventListener('replay_complete', function () { _attachOk(); });
    es.addEventListener('output', function (ev) {
      try { var p = JSON.parse(ev.data); if (p.text) term.write(p.text); } catch (e) {}
    });
    es.addEventListener('done', function () { try { es.close(); } catch (e) {} });
    es.onerror = function () { /* bounded server stream; let it close */ };
  }
  try {
    var ws = new WebSocket(wsUrl);
    w.transport = ws;
    ws.onmessage = function (ev) {
      var data = ev.data;
      // A W6 control frame? (prefixed TEXT frame; PTY bytes never start with NUL.)
      if (typeof data === 'string' && data.indexOf(WS_CTL_PREFIX) === 0) {
        var msg = null;
        try { msg = JSON.parse(data.slice(WS_CTL_PREFIX.length)); } catch (e) { return; }
        if (!msg) return;
        if (msg.type === 'attach_ack' && msg.ok === false) {
          _attachError(msg.reason || 'unknown-session');
        } else if (msg.type === 'replay_complete') {
          _attachOk();
        }
        return;  // control frames are never written to the terminal
      }
      term.write(data);
    };
    ws.onclose = function () {
      // If the WS never carried data (e.g. upgrade unsupported), use SSE.
      if (!sseStarted) startSSE();
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} startSSE(); };
  } catch (e) { startSSE(); }
}

// ════════════════════════════════════════════════════════════════════════════
// v12 Wave 10 — the SINGLE bottom DOCK (Layout-D). Clicking any effort tile opens
// THIS dock bound to that effort: a title bar (status dot + title + a 3-node
// stage track lit by current_stage [EV-2] + min/max/close + a distinct
// Kill -> Boneyard + the context-full warn banner + Advance ->), summary ON TOP
// (full width, reusing _renderSplitSummary/_loadPanelSummary), a DRAGGABLE
// vertical splitter, and a FULL-WIDTH terminal whose HEIGHT the user drags. It
// reuses the WS->SSE transport + xterm mount/fit (the splitter-drag fit is
// DEBOUNCED so dragging doesn't thrash the terminal). The legacy #panelStack /
// openPanel surface stays for the live-session bar chips, grass, boneyard, and
// chain-nav clones — only effort tiles route here.
// ════════════════════════════════════════════════════════════════════════════

// DOCK: the one bound effort's transient state {session_id, effort_id, lane,
// current_stage, status, term, transport, fitRo, body, tpane}. Empty/unbound when
// the dock is closed (no data-effort-id on #effortDock → the negative DOM case).
var DOCK = null;

function _dockEl() { return document.getElementById('effortDock'); }

// _dockStageRank: map a stage to the count of reached track nodes (presence —
// research→1, plan→2, build→3). NOT iterating stage_history (EV-2).
function _dockStageReached(stage) {
  if (stage === 'build') return 3;
  if (stage === 'plan' || stage === 'planning') return 2;
  return 1;  // research / unknown → first node
}

// _renderDockTrack: build the 3-node Research→Plan→Build track DOM into #dockTrack
// from current_stage (presence-based). Mirrors the server _render_layoutd_track.
function _renderDockTrack(stage) {
  var host = document.getElementById('dockTrack');
  if (!host) return;
  host.innerHTML = '';
  var lanes = ['research', 'plan', 'build'];
  var curIdx = (stage === 'build') ? 2
             : (stage === 'plan' || stage === 'planning') ? 1 : 0;
  var reached = _dockStageReached(stage);
  for (var i = 0; i < lanes.length; i++) {
    var node = document.createElement('span');
    var cls = ['node', lanes[i]];
    if (i < reached) cls.push('reached');
    if (i === curIdx) cls.push('current');
    node.className = cls.join(' ');
    host.appendChild(node);
    if (i < lanes.length - 1) {
      var line = document.createElement('span');
      line.className = (i + 1 < reached) ? 'line done' : 'line';
      host.appendChild(line);
    }
  }
  var lbl = document.createElement('span');
  lbl.className = 'track-lbl';
  lbl.textContent = (stage === 'plan' || stage === 'planning') ? 'Plan'
                  : (stage === 'build') ? 'Build' : 'Research';
  host.appendChild(lbl);
}

// _fmtDockTime(ms): a short wall-clock label for the metrics line (s / m / h).
function _fmtDockTime(ms) {
  ms = ms || 0;
  var secs = ms / 1000;
  if (secs < 60) return secs.toFixed(secs < 10 ? 1 : 0) + 's';
  var mins = secs / 60;
  if (mins < 60) return mins.toFixed(1) + 'm';
  return (mins / 60).toFixed(1) + 'h';
}

// _loadDockMetrics(effortId): fill #dockMetrics with the SELECTED effort's
// rollup — "Σ <tok> tok · <time> · $<cost>" — from GET /api/rnd/effort_rollup
// (numbers only; imported/discovered contribute 0, never fabricated). Read-only;
// best-effort (any error leaves the placeholder, never throws).
function _loadDockMetrics(effortId) {
  var el = document.getElementById('dockMetrics');
  if (!el) return;
  el.textContent = 'Σ … tok · … · $…';
  if (!effortId) return;
  var url = '/api/rnd/effort_rollup?pid=' + encodeURIComponent(PROJECT_ID)
    + '&effort=' + encodeURIComponent(effortId) + _tokenQ();
  fetch(url, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (!d || !d.ok) return;
      var tok = d.tokens || 0;
      var cost = (d.cost_usd || 0).toFixed(2);
      el.textContent = 'Σ ' + tok + ' tok · '
        + _fmtDockTime(d.wall_clock_ms) + ' · $' + cost;
    })
    .catch(function () {});
}

// openEffortDock(sessionId, tile): show the bottom dock bound to the clicked
// effort. Resolves the effort_id + current_stage + lane from the tile's data-*
// attrs (server-stamped from the effort view), loads the summary ON TOP, and
// mounts the terminal (live xterm, or a read-only body for a historical effort).
function openEffortDock(sessionId, tile) {
  var dock = _dockEl();
  if (!dock) return;
  try {
    if (window.parent && window.parent.document.getElementById('dashboard-workbench-details')) {
      window.parent.document.getElementById('dashboard-workbench-details').open = true;
    }
  } catch(e) {}
  tile = tile || document.querySelector(
    '.tile[data-session="' + _cssEsc(sessionId) + '"]');
  var lane = (tile && tile.getAttribute('data-lane')) || '';
  var stage = (tile && tile.getAttribute('data-current-stage')) || '';
  var effortId = (tile && tile.getAttribute('data-effort-id')) || sessionId;
  var light = (tile && tile.getAttribute('data-light')) || 'grey';
  var em = (tile && tile.getAttribute('data-effort-managed')) === '1';
  // Tear down any previously-mounted dock terminal/transport first.
  _dockTeardownTerminal();
  var s = MANAGED[sessionId] || _synthSessionRecord(sessionId) ||
          {session_id: sessionId, lane: lane, status: 'idle', label: ''};
  var status = s.status || (light === 'green' ? 'running'
             : light === 'amber' ? 'done' : light === 'red' ? 'failed' : 'idle');
  // Is this a LIVE managed session? W10-R2-03: require RUNNING — a freshly-DONE
  // session whose MANAGED chip lingers client-side gets the read-only body, never
  // a transport mounted on a reaped PTY.
  var live = !!MANAGED[sessionId] && status === 'running';

  // Bind the dock state.
  DOCK = {session_id: sessionId, effort_id: effortId, lane: lane,
          current_stage: stage || lane, status: status, live: live,
          effort_managed: em, term: null, transport: null, fitRo: null,
          body: null, tpane: null};
  dock.setAttribute('data-effort-id', effortId);
  dock.setAttribute('data-session', sessionId);
  dock.classList.remove('mind', 'maxd');
  dock.style.display = 'flex';

  // Title bar.
  var dotEl = document.getElementById('dockDot');
  if (dotEl) dotEl.className = 'dot ' + _statusColor(status);
  var titleEl = document.getElementById('dockTitle');
  if (titleEl) {
    var skl = _skillForLane(lane);
    titleEl.textContent = (s.label && s.label.trim())
      ? s.label : ((lane || 'effort') + (skl ? ' · ' + skl : ''));
  }
  var engEl = document.getElementById('dockEngTog');
  if (engEl) {
    engEl.innerHTML = '';
    if (live) engEl.appendChild(_buildEngineToggle(sessionId, s));
  }
  var runEl = document.getElementById('dockRun');
  if (runEl) runEl.style.display = (status === 'running') ? '' : 'none';
  // v12 W11 (SC6): a bare GENERAL session opens in the dock too, but it is NOT a
  // trio effort — show NO stage track and NO Advance (it never advances). Trio
  // efforts (research/plan/build) render the 3-node track + Advance as before.
  var isGeneral = (lane === 'general') || (DOCK.current_stage === '' && lane === 'general');
  var trackEl = document.getElementById('dockTrack');
  if (isGeneral) {
    if (trackEl) trackEl.innerHTML = '';
  } else {
    _renderDockTrack(DOCK.current_stage);
  }
  // Advance → is shown for a trio effort whose current stage is not the last
  // (build); hidden for general (no stages) and at build.
  var advEl = document.getElementById('dockAdvance');
  if (advEl) {
    var atBuild = (DOCK.current_stage === 'build');
    advEl.style.display = (isGeneral || atBuild) ? 'none' : '';
  }
  // Warn banner hidden until the poll says over_threshold.
  var warnEl = document.getElementById('dockWarn');
  if (warnEl) warnEl.style.display = 'none';

  // Summary ON TOP (reuses the panel split-summary loader/renderer).
  var summHost = document.getElementById('dockSummary');
  if (summHost) {
    summHost.innerHTML = '<div class="summ-loading">loading effort summary…</div>';
    _loadPanelSummary(sessionId, summHost);
  }
  // v12 W10 (change #3): the per-effort metrics line (Σ tokens · time · $).
  _loadDockMetrics(effortId);

  // Terminal BELOW (full width). Live → xterm over the transport; historical →
  // a read-only body (summary already on top).
  var host = document.getElementById('dockTermHost');
  if (host) {
    host.innerHTML = '';
    DOCK.body = host;
    DOCK.tpane = document.getElementById('dockBottom');
    if (live) {
      _mountTerminal(sessionId, host, DOCK);   // reuses transport + fit + observer
    } else {
      _mountReadOnlyBody(sessionId, host, s);
    }
  }

  // Wire the draggable splitter (debounced fit) + start the context-status poll.
  _wireDockSplitter();
  _startDockContextPoll();
  // Fit once the dock's <details>/flex layout has actually committed — the dock
  // is un-hidden in this same tick, so a fixed setTimeout raced it (general
  // "Open terminal" sessions open into the dock and were the worst-hit).
  _fitPanelTerminalDeferred(sessionId, DOCK);
}

// _dockTeardownTerminal: dispose the dock's xterm + transport + observer (no
// effect on the session — the PTY keeps running server-side).
function _dockTeardownTerminal() {
  if (!DOCK) return;
  try { if (DOCK.fitRo && DOCK.fitRo.disconnect) DOCK.fitRo.disconnect(); } catch (e) {}
  try { if (DOCK.transport && DOCK.transport.close) DOCK.transport.close(); } catch (e) {}
  try { if (DOCK.term && DOCK.term.dispose) DOCK.term.dispose(); } catch (e) {}
  DOCK.term = null; DOCK.transport = null; DOCK.fitRo = null;
}

// _wireDockSplitter: drag the .dsplit bar to set the terminal (bottom) height.
// The fit is DEBOUNCED (requestAnimationFrame-coalesced) so a fast drag does NOT
// thrash xterm's resize (SK-9) — one fit per animation frame, plus a final fit on
// pointer-up.
var _dockSplitWired = false;
function _wireDockSplitter() {
  var split = document.getElementById('dockSplit');
  var dock = _dockEl();
  if (!split || !dock || _dockSplitWired) return;
  _dockSplitWired = true;
  var dragging = false;
  var raf = 0;
  function _debouncedFit() {
    if (raf) return;
    raf = (window.requestAnimationFrame || function (f) { return setTimeout(f, 16); })(
      function () { raf = 0; if (DOCK) _fitPanelTerminal(DOCK.session_id, DOCK); });
  }
  function _onMove(e) {
    if (!dragging) return;
    var y = (e.touches ? e.touches[0].clientY : e.clientY);
    // v12 W10 (change #1): the dock is EMBEDDED (top-anchored in the flow), so its
    // HEIGHT = (pointer Y - dock top). When maximized it is a fixed full-viewport
    // overlay (top-anchored at 0) and the same math holds. Clamp to a sane range.
    var top = dock.getBoundingClientRect().top;
    var h = Math.max(200, Math.min(window.innerHeight * 0.95, y - top));
    dock.style.height = h + 'px';
    _debouncedFit();
    if (e.cancelable) e.preventDefault();
  }
  function _onUp() {
    if (!dragging) return;
    dragging = false;
    document.removeEventListener('mousemove', _onMove);
    document.removeEventListener('mouseup', _onUp);
    document.removeEventListener('touchmove', _onMove);
    document.removeEventListener('touchend', _onUp);
    if (DOCK) _fitPanelTerminal(DOCK.session_id, DOCK);   // final crisp fit
  }
  function _onDown(e) {
    dragging = true;
    document.addEventListener('mousemove', _onMove);
    document.addEventListener('mouseup', _onUp);
    document.addEventListener('touchmove', _onMove, {passive: false});
    document.addEventListener('touchend', _onUp);
    if (e.cancelable) e.preventDefault();
  }
  split.addEventListener('mousedown', _onDown);
  split.addEventListener('touchstart', _onDown, {passive: false});
}

// dockMinimize / dockMaximize / dockClose: the dock window controls. Minimize/
// maximize keep the session running (re-fit on change); close hides + unbinds the
// dock (does NOT kill — the effort stays, reopen from its tile).
function dockMinimize() {
  var dock = _dockEl();
  if (!dock) return;
  dock.classList.remove('maxd');
  dock.classList.toggle('mind');
  if (!dock.classList.contains('mind') && DOCK)
    setTimeout(function () { _fitPanelTerminal(DOCK.session_id, DOCK); }, 40);
}
function dockMaximize() {
  var dock = _dockEl();
  if (!dock) return;
  dock.classList.remove('mind');
  dock.classList.toggle('maxd');
  if (DOCK) {
    _fitPanelTerminal(DOCK.session_id, DOCK);
    setTimeout(function () { _fitPanelTerminal(DOCK.session_id, DOCK); }, 60);
  }
}
function dockClose() {
  var dock = _dockEl();
  _dockTeardownTerminal();
  _stopDockContextPoll();
  if (dock) {
    dock.style.display = 'none';
    dock.removeAttribute('data-effort-id');
    dock.removeAttribute('data-session');
    dock.classList.remove('mind', 'maxd');
  }
  DOCK = null;
}

// dockAdvance: in-session stage advance for the bound effort. POST
// /api/rnd/advance_stage — KEEPS the same session (no new session minted, nothing
// injected into the PTY). On success: relabel the stage track + migrate the tile's
// zone via a board refresh; the session-id SET is unchanged.
async function dockAdvance() {
  if (!DOCK) return;
  var sid = DOCK.session_id;
  var payload = {project_id: PROJECT_ID, session: sid};
  var r, data;
  try {
    r = await _postJson('/api/rnd/advance_stage', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/advance_stage', payload);
      data = await r.json();
    }
  } catch (e) { alert('[advance error] ' + e.message); return; }
  if (!data || !data.ok) {
    alert('[advance refused] ' + ((data && (data.reason || data.error))
      || 'unknown'));
    return;
  }
  var rec = data.session || {};
  var newStage = rec.current_stage || data.to_stage || DOCK.current_stage;
  DOCK.current_stage = newStage;
  _renderDockTrack(newStage);
  var advEl = document.getElementById('dockAdvance');
  if (advEl) advEl.style.display = (newStage === 'build') ? 'none' : '';
  // Refresh the board so the tile migrates zones (its data-current-stage updates);
  // the SAME session stays bound to the dock.
  refreshBoard();
}

// dockKill: deliberate hard-kill of the bound effort → Boneyard. Confirm-gated;
// reuses the existing term_kill path (reap PTY + worktree, files a boneyard
// entry), then closes the dock + removes the tile.
async function dockKill() {
  if (!DOCK) return;
  if (!confirm('Kill this effort and send it to the Boneyard? '
    + 'This ends the session and reaps its worktree.')) return;
  var sid = DOCK.session_id;
  try {
    var r = await _postJson('/api/rnd/term_kill', {session: sid});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_kill', {session: sid});
    }
  } catch (e) { /* best-effort; still close the dock */ }
  if (MANAGED[sid]) delete MANAGED[sid];
  _KILLED[sid] = true;
  _removeSessionTile(sid);
  dockClose();
  renderSessionBar();
  refreshBoard();
}

// dockDelete: v9 TRUE-delete (keep documents) for the bound effort. Reuses the
// shared deletePanel() (confirm-gated; POST /api/rnd/term_delete → drops the
// registry record + effort/summary cache, KEEPS the produced docs), then closes
// the dock. Distinct from dockKill (which reaps the worktree → Boneyard).
async function dockDelete() {
  if (!DOCK) return;
  var sid = DOCK.session_id;
  await deletePanel(sid);     // confirm + term_delete + tile/board cleanup
  dockClose();
}

// ── context-full warn banner (poll → one-click handoff) ─────────────────────
var _dockPollTimer = null;
function _startDockContextPoll() {
  _stopDockContextPoll();
  // Only a LIVE session can fill its context; a historical effort never warns.
  if (!DOCK || !DOCK.live) return;
  var sid = DOCK.session_id;
  function _poll() {
    if (!DOCK || DOCK.session_id !== sid) return;
    var url = '/api/rnd/context_status?session=' + encodeURIComponent(sid)
      + _tokenQ();
    fetch(url, _jsonHdrs())
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!DOCK || DOCK.session_id !== sid) return;
        var warnEl = document.getElementById('dockWarn');
        if (!warnEl) return;
        warnEl.style.display = (d && d.ok && d.over_threshold) ? '' : 'none';
      })
      .catch(function () {});
  }
  _poll();
  _dockPollTimer = setInterval(_poll, 8000);
}
function _stopDockContextPoll() {
  if (_dockPollTimer) { clearInterval(_dockPollTimer); _dockPollTimer = null; }
}

// dockHandoffToFresh: the warn-banner one-click action. POST
// /api/rnd/handoff_to_fresh — continue the effort in a FRESH session that JOINS
// the same effort (same effort_id); the next prompt is held as a PENDING PASTE
// (UNSENT). On success, re-bind the dock to the new live session.
async function dockHandoffToFresh() {
  if (!DOCK) return;
  var sid = DOCK.session_id;
  var payload = {project_id: PROJECT_ID, session: sid};
  var r, data;
  try {
    r = await _postJson('/api/rnd/handoff_to_fresh', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/handoff_to_fresh', payload);
      data = await r.json();
    }
  } catch (e) { alert('[handoff error] ' + e.message); return; }
  if (!data || !data.ok) {
    alert('[handoff refused] ' + ((data && (data.reason || data.error))
      || 'unknown'));
    return;
  }
  var nr = data.new_session || {};
  var nsid = nr.session_id;
  if (nsid) {
    MANAGED[nsid] = {session_id: nsid, lane: nr.lane || DOCK.lane,
      backend: '', status: nr.status || 'running', label: nr.label || '',
      idx: (_laneCounters[nr.lane || DOCK.lane] =
            (_laneCounters[nr.lane || DOCK.lane] || 0) + 1)};
    renderSessionBar();
    refreshBoard();
    setTimeout(function () {
      var tile = document.querySelector(
        '.tile[data-session="' + _cssEsc(nsid) + '"]');
      openEffortDock(nsid, tile);
    }, 300);
  } else {
    dockClose();
  }
}

// newEffort(stage): the "+ New effort" control. Start a NEW effort_managed trio
// session at the given stage (default research) via the existing term_start path
// with effort_managed=true, then open the dock bound to it. (term_start tolerates
// the extra field; the server marks it effort_managed.)
async function newEffort(stage) {
  stage = stage || 'research';
  // v12 W10 (John change #2): start at research OR plan (W6 supports both). The
  // lane name mirrors the stage (term_start accepts both 'plan' and 'planning').
  var lane = (stage === 'plan') ? 'plan'
           : (stage === 'build') ? 'build' : 'research';
  var payload = {project_id: PROJECT_ID, lane: lane, backend: 'claude',
                 effort_managed: true};
  var r, data;
  try {
    r = await _postJson('/api/rnd/term_start', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_start', payload);
      data = await r.json();
    }
  } catch (e) { alert('[new effort error] ' + e.message); return; }
  if (!data || !data.ok || !data.session) {
    alert('[new effort refused] ' + ((data && (data.error || data.reason))
      || 'unknown'));
    return;
  }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {session_id: sid, lane: rec.lane || lane,
    backend: rec.backend || 'claude', status: rec.status || 'running',
    label: rec.label || '',
    idx: (_laneCounters[rec.lane || lane] =
          (_laneCounters[rec.lane || lane] || 0) + 1)};
  renderSessionBar();
  refreshBoard();
  setTimeout(function () {
    var tile = document.querySelector(
      '.tile[data-session="' + _cssEsc(sid) + '"]');
    openEffortDock(sid, tile);
  }, 400);
}

// newGeneral(backend): v12 Wave 11 (SC6). Start a BARE general session (lane
// 'general' — NOT in LANE_SKILL, so no trio skill seeds) and open it in the W10
// BOTTOM DOCK like any effort (summary-on-top + a live terminal). It is NOT a trio
// effort: the dock shows no stage track and no Advance, and it never auto-advances.
// It is registered (a top-strip chip) but is NOT a board lane column. Token-aware.
async function newGeneral(backend) {
  backend = backend || 'claude';
  var payload = {project_id: PROJECT_ID, lane: 'general', backend: backend};
  var r, data;
  try {
    r = await _postJson('/api/rnd/term_start', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_start', payload);
      data = await r.json();
    }
  } catch (e) { alert('[open terminal error] ' + e.message); return; }
  if (!data || !data.ok || !data.session) {
    alert('[open terminal refused] ' + ((data && (data.error || data.reason))
      || 'unknown'));
    return;
  }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {session_id: sid, lane: 'general',
    backend: rec.backend || backend, status: rec.status || 'running',
    label: rec.label || 'general',
    idx: (_laneCounters['general'] = (_laneCounters['general'] || 0) + 1)};
  renderSessionBar();
  // Refresh the board so the new general session appears as a tile in the General
  // zone immediately (general is now a board column). lane 'general' suppresses
  // the dock's stage track + Advance.
  refreshBoard();
  setTimeout(function () {
    var tile = document.querySelector(
      '.tile[data-session="' + _cssEsc(sid) + '"]');
    openEffortDock(sid, tile);
  }, 400);
}
// --- Wave 2: File Upload (multi-file + folder + drag-drop) ---
function _anchorReadB64(file) {
  return new Promise(function(resolve, reject) {
    var r = new FileReader();
    r.onload = function() { resolve(r.result.split(',')[1]); };
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

function _anchorUploadDest(projectId) {
  if (projectId === '__dashboard__') return "the dev inbox (C:\\dev\\Anchor\\dev)";
  if (typeof window._anchorUploadName === 'string' && window._anchorUploadName) return window._anchorUploadName;
  return "project " + projectId;
}

// Unified upload core. `items` is an array of { file, path } where path is the
// destination-relative path (leading slashes stripped). All three controls
// (multi-file picker, folder picker, drag-drop) funnel through here.
async function _anchorDoUpload(items, projectId) {
  if (!items || !items.length) return;

  var folders = new Set();
  var fileCount = 0;
  for (var i = 0; i < items.length; i++) {
    var p = items[i].path || "";
    if (p.indexOf('/') !== -1) {
      var parts = p.split('/');
      parts.pop();
      folders.add(parts.join('/'));
    }
    fileCount++;
  }
  var folderCount = folders.size;
  var stagingMsg = fileCount + " file(s)" + (folderCount ? " across " + folderCount + " folder(s)" : "") + " ready";

  var dz = document.querySelector('.upload-dropzone');
  if (dz) {
    dz.innerHTML = "&#9203; Staging: " + stagingMsg + "...";
  }

  var filesPayload = [];
  for (var i = 0; i < items.length; i++) {
    var rel = String(items[i].path || items[i].file.name).replace(/^\/+/, '');
    try {
      var base64 = await _anchorReadB64(items[i].file);
      filesPayload.push({ path: rel, content_b64: base64 });
    } catch (e) {
      alert("Failed to read file: " + rel);
      if (dz) dz.innerHTML = "&#8681; Drop files &amp; folders here to upload (any mix)";
      return;
    }
  }
  var res = await fetch("/api/rnd/upload_batch", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Anchor-Token": _anchorToken()
    },
    body: JSON.stringify({ project_id: projectId, files: filesPayload })
  });
  if (res.ok) {
    alert("Uploaded " + filesPayload.length + " file(s) to " + _anchorUploadDest(projectId) + ".");
    if (typeof loadProjectFiles === 'function') {
      loadProjectFiles(projectId, (typeof currentFilesPath !== 'undefined' ? currentFilesPath : ''));
    }
  } else {
    var data = await res.json();
    alert("Upload failed: " + (data.error || "Unknown error"));
  }
  if (dz) {
    dz.innerHTML = "&#8681; Drop files &amp; folders here to upload (any mix)";
  }
}

async function handleGlobalUpload(inputId, projectId) {
  var input = document.getElementById(inputId);
  if (!input || !input.files || input.files.length === 0) return;
  var items = [];
  for (var i = 0; i < input.files.length; i++) {
    var file = input.files[i];
    items.push({ file: file, path: file.webkitRelativePath || file.name });
  }
  await _anchorDoUpload(items, projectId);
  input.value = "";
}

// Recurse a dropped FileSystemEntry, collecting every File with its full
// relative path. readEntries() returns results in batches, so it must be
// called repeatedly until it yields an empty array.
function _anchorWalkEntry(entry, prefix, out) {
  return new Promise(function(resolve) {
    if (entry.isFile) {
      entry.file(function(file) {
        out.push({ file: file, path: prefix ? (prefix + "/" + entry.name) : entry.name });
        resolve();
      }, function() { resolve(); });
    } else if (entry.isDirectory) {
      var reader = entry.createReader();
      var dirPrefix = prefix ? (prefix + "/" + entry.name) : entry.name;
      var all = [];
      var readBatch = function() {
        reader.readEntries(function(results) {
          if (!results || !results.length) {
            var chain = Promise.resolve();
            all.forEach(function(child) {
              chain = chain.then(function() { return _anchorWalkEntry(child, dirPrefix, out); });
            });
            chain.then(resolve);
          } else {
            for (var m = 0; m < results.length; m++) all.push(results[m]);
            readBatch();
          }
        }, function() { resolve(); });
      };
      readBatch();
    } else {
      resolve();
    }
  });
}

function handleUploadDragOver(ev) {
  ev.preventDefault();
  if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy';
  var dz = ev.currentTarget;
  if (dz) dz.classList.add('dragover');
}

function handleUploadDragLeave(ev) {
  var dz = ev.currentTarget;
  if (dz) dz.classList.remove('dragover');
}

async function handleUploadDrop(ev, projectId) {
  ev.preventDefault();
  var dz = ev.currentTarget;
  if (dz) dz.classList.remove('dragover');
  var dt = ev.dataTransfer;
  if (!dt) return;
  // Collect entries synchronously BEFORE any await (the DataTransfer is cleared
  // once the event handler yields).
  var entries = [];
  if (dt.items && dt.items.length && dt.items[0].webkitGetAsEntry) {
    for (var i = 0; i < dt.items.length; i++) {
      var en = dt.items[i].webkitGetAsEntry();
      if (en) entries.push(en);
    }
  }
  var items = [];
  if (entries.length) {
    for (var j = 0; j < entries.length; j++) {
      await _anchorWalkEntry(entries[j], "", items);
    }
  } else if (dt.files && dt.files.length) {
    for (var k = 0; k < dt.files.length; k++) {
      items.push({ file: dt.files[k], path: dt.files[k].name });
    }
  }
  await _anchorDoUpload(items, projectId);
}

// (v3 floating-window drag/resize helpers removed in v4 Wave 4: inline panels
// stack in the document flow — Wave 5 adds the terminal-pane vertical resize.)

// --- Wave 3: Project Files Viewer ---
var currentFilesPath = "";

async function loadProjectFiles(projectId, path) {
  currentFilesPath = path || "";
  var listEl = document.getElementById("projectFilesList");
  var pathEl = document.getElementById("projectFilesPath");
  if (!listEl) return;
  
  listEl.innerHTML = "<div class='idea-empty'>Loading files...</div>";
  if (pathEl) {
    pathEl.textContent = currentFilesPath ? "/" + currentFilesPath : "/";
  }
  
  try {
    var token = (typeof _anchorToken === 'function') ? _anchorToken() : '';
    var url = "/api/rnd/project_files?project_id=" + encodeURIComponent(projectId) + "&path=" + encodeURIComponent(currentFilesPath);
    if (token) {
      url += "&token=" + encodeURIComponent(token);
    }
    var res = await fetch(url);
    var data = await res.json();
    if (!data.ok) {
      listEl.innerHTML = "<div class='idea-empty' style='color:var(--danger)'>Error: " + _esc(data.error) + "</div>";
      return;
    }
    
    var html = "";
    // Back folder if we are in a subdirectory
    if (currentFilesPath) {
      var parts = currentFilesPath.split("/");
      parts.pop();
      var parentPath = parts.join("/");
      html += "<div class='file-item dir-item' onclick=\"loadProjectFiles('" + escapeJs(projectId) + "', '" + escapeJs(parentPath) + "')\">" +
        "<span class='icon'>&#128194;</span> <span class='mono'>..</span>" +
      "</div>";
    }
    
    // Render directories
    data.dirs.forEach(function(d) {
      var name = d.split("/").pop();
      html += "<div class='file-item dir-item' onclick=\"loadProjectFiles('" + escapeJs(projectId) + "', '" + escapeJs(d) + "')\">" +
        "<span class='icon'>&#128193;</span> <span class='mono'>" + _esc(name) + "/</span>" +
      "</div>";
    });
    
    // Render files
    data.files.forEach(function(f) {
      var sizeStr = formatBytes(f.size);
      html += "<div class='file-item file-item-clickable' onclick=\"previewProjectFile('" + escapeJs(projectId) + "', '" + escapeJs(f.path) + "')\">" +
        "<span class='icon'>&#128196;</span> <span class='mono'>" + _esc(f.name) + "</span>" +
        "<span class='file-size'>" + sizeStr + "</span>" +
      "</div>";
    });
    
    if (data.dirs.length === 0 && data.files.length === 0 && !currentFilesPath) {
      listEl.innerHTML = "<div class='idea-empty'>No files found.</div>";
    } else {
      listEl.innerHTML = html;
    }
  } catch (err) {
    listEl.innerHTML = "<div class='idea-empty' style='color:var(--danger)'>Failed to fetch files: " + _esc(err.message) + "</div>";
  }
}

async function previewProjectFile(projectId, path) {
  var previewContainer = document.getElementById("projectFilesPreviewContainer");
  var previewTitle = document.getElementById("projectFilesPreviewTitle");
  var previewCode = document.getElementById("projectFilesPreviewCode");
  if (!previewContainer || !previewTitle || !previewCode) return;
  
  var name = path.split("/").pop();
  previewTitle.textContent = "Loading " + name + "...";
  previewCode.textContent = "Loading file content...";
  previewContainer.style.display = "block";
  
  try {
    var token = (typeof _anchorToken === 'function') ? _anchorToken() : '';
    var url = "/api/rnd/project_file_content?project_id=" + encodeURIComponent(projectId) + "&path=" + encodeURIComponent(path);
    if (token) {
      url += "&token=" + encodeURIComponent(token);
    }
    var res = await fetch(url);
    var data = await res.json();
    if (!data.ok) {
      previewTitle.textContent = "Error";
      previewCode.textContent = "Error: " + data.error;
      return;
    }
    
    previewTitle.textContent = name + " (" + formatBytes(data.size) + ")";
    previewCode.textContent = data.content;
  } catch (err) {
    previewTitle.textContent = "Error";
    previewCode.textContent = "Failed to load content: " + err.message;
  }
}

function closeProjectFilesPreview() {
  var previewContainer = document.getElementById("projectFilesPreviewContainer");
  if (previewContainer) {
    previewContainer.style.display = "none";
  }
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  var k = 1024;
  var sizes = ['B', 'KB', 'MB', 'GB'];
  var i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function escapeJs(s) {
  return s.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// ── Gandalf output modal + panel toggle helpers ──
function enlargeGandalfRun(ev, el) {
  if (ev) { ev.stopPropagation(); if (ev.preventDefault) ev.preventDefault(); }
  var grun = el.closest('.grun');
  if (!grun) return;
  var gexec = grun.querySelector('.gexec');
  if (!gexec) return;
  var contentHtml = gexec.innerHTML || '';
  
  var overlay = document.getElementById('gandalfEnlargeOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'gandalfEnlargeOverlay';
    overlay.className = 'gandalf-overlay';
    overlay.onclick = function(e) {
      if (e.target === overlay) {
        overlay.classList.remove('open');
      }
    };
    document.body.appendChild(overlay);
  }
  
  overlay.innerHTML = '<div class="gandalf-modal">' +
    '<span class="gandalf-modal-close" onclick="closeGandalfEnlarge()">&times;</span>' +
    '<div class="gandalf-modal-body">' + contentHtml + '</div>' +
    '</div>';
  overlay.classList.add('open');
}

function closeGandalfEnlarge() {
  var overlay = document.getElementById('gandalfEnlargeOverlay');
  if (overlay) {
    overlay.classList.remove('open');
  }
}

function toggleGandalfPanel(el) {
  var body = document.getElementById('gandalfPanelBody');
  if (!body) return;
  var collapsed = body.classList.toggle('collapsed');
  if (el) {
    if (collapsed) {
      el.classList.add('collapsed-caret');
    } else {
      el.classList.remove('collapsed-caret');
    }
  }
  try { localStorage.setItem('gandalfPanelCollapsed', collapsed ? 'true' : 'false'); } catch(e){}
}

function initGandalfPanelCollapse() {
  try {
    var isCollapsed = localStorage.getItem('gandalfPanelCollapsed') === 'true';
    if (isCollapsed) {
      var body = document.getElementById('gandalfPanelBody');
      var tog = document.getElementById('gandalfPanelTog');
      if (body) body.classList.add('collapsed');
      if (tog) tog.classList.add('collapsed-caret');
    }
  } catch (e) {}
  
  // Restart polling if the panel indicates a run is already in-flight
  var panel = document.getElementById('gandalfPanel');
  if (panel && panel.getAttribute('data-gandalf-inflight') === '1') {
      var btns = document.querySelectorAll('#gandalfPanel .gandalf-run');
      var before = _gandalfRunCount();
      _gandalfPollForNew(PROJECT_ID, before, btns, 0);
  }
}

// ── Files panel toggle + browse helpers ──
function onProjectFilesToggle(el) {
  if (el && el.open) {
    loadProjectFiles(PROJECT_ID, currentFilesPath);
  }
}

function toggleBrowseMenu(ev, suffix) {
  if (ev) ev.stopPropagation();
  var menu = document.getElementById('browseMenu_' + suffix);
  if (!menu) return;
  var show = menu.style.display === 'none';
  var all = document.querySelectorAll('.browse-menu');
  for (var i = 0; i < all.length; i++) all[i].style.display = 'none';
  if (show) {
    menu.style.display = 'block';
  }
}
document.addEventListener('click', function() {
  var all = document.querySelectorAll('.browse-menu');
  for (var i = 0; i < all.length; i++) all[i].style.display = 'none';
});
