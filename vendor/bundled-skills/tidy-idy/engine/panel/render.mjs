// engine/panel/render.mjs — Triage Panel page (Mockup A aligned).
//
// Decision-first UI: header + verdict pills + action sections. Full evidence
// (attacker/judge/diffs/JSON) lives behind <details>, never open by default.
// The model remains the source of truth; this file is a projection only.
//
// Safety rules unchanged:
//   1. Token in browser memory only (module const, never storage/URL).
//   2. Mutating POSTs carry token in header + full finding identity.
//   3. Celebratory-clean only from envelope.isClean.
//   4. Verbatim evidence is never paraphrased — only hidden until expanded.

import { faviconDataUri } from '../launch/run-status.mjs';
import { headerBrandDataUri } from './assets/brand.mjs';

export const TOKEN_HEADER = 'x-tidy-idy-token';
// Re-export size budget pin so same-wave brand asserts share one constant.
export { HEADER_BRAND_DATA_URI_MAX_BYTES } from './assets/brand.mjs';

// ---- SC4 / Option 1 (W6): dead-Apply after F5 — never remount token ----------
// Capability token is browser-memory only. A reload drops it; Apply must not
// silently re-enable. Operator re-opens from CLI or Anchor (fresh nonce + mint).
export const DEAD_APPLY_BANNER_TITLE = 'Apply session ended — reload dropped the capability';
export const DEAD_APPLY_REOPEN_COPY =
  'This tab no longer holds the one-time Apply capability (F5 / reload clears the browser-memory token). '
  + 'Re-open the panel from the CLI (`tidy-idy <folder>`) or the Anchor Tidy-Idy button to mint a fresh single-use session. '
  + 'Apply will not silently re-enable.';
export const LIVE_APPLY_F5_FOOTPRINT =
  'Reload (F5) ends this Apply session — re-open from tidy-idy CLI or Anchor; the token is never restored to a reloaded tab.';
export const DEAD_APPLY_CHIP_LABEL = 'Apply disabled — re-open required';

/** True when the page embeds a usable capability token (Option 1 live session). */
export function isTokenLive(token) {
  return typeof token === 'string' && token.length > 0;
}


export function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/** Safe to embed in a <script> block: `</script>` inside a string cannot escape. */
export function embedJson(value) {
  const LS = String.fromCharCode(0x2028);
  const PS = String.fromCharCode(0x2029);
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .split(LS).join('\\u2028')
    .split(PS).join('\\u2029');
}

/**
 * The redeemed panel page.
 *
 * @param {{token: string|null|undefined, model: object, baseUrl: string}} opts
 *   `token` live on first bootstrap redeem only. Absent/empty → Option 1 dead-Apply
 *   chrome (banner + disabled Apply + re-open copy). Never put token on disk/URL/storage.
 */
export function renderPanelPage({ token, model, baseUrl }) {
  const h = model.header;
  const v = model.verdicts || {};
  const icon = faviconDataUri();
  // SC2 brand: self-contained data-URI from engine/panel/assets/ (not broom, not file://).
  const brand = headerBrandDataUri();
  // SC4 Option 1: no usable token ⇒ honest dead-Apply (no silent re-enable).
  const tokenLive = isTokenLive(token);
  const applyEnabled = tokenLive && Boolean(model.apply && model.apply.bulkEnabled);
  const deadBanner = tokenLive ? '' : renderDeadApplyBanner();
  const disabledChip = !tokenLive
    ? `<span class="chip amber" id="apply-disabled" data-testid="dead-apply-chip">${escapeHtml(DEAD_APPLY_CHIP_LABEL)}</span>`
    : (model.apply.disabledReason
      ? `<span class="chip amber" id="apply-disabled">${escapeHtml(model.apply.disabledReason)}</span>`
      : '');
  const tokenFootprint = tokenLive
    ? `${escapeHtml(model.apply.tokenTransport)}. One Apply per run · nothing mutates until you click Apply. ${escapeHtml(LIVE_APPLY_F5_FOOTPRINT)}`
    : `${escapeHtml(DEAD_APPLY_REOPEN_COPY)}`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Tidy-Idy — ${escapeHtml(h.project)} · run ${escapeHtml(h.run.number)}</title>
<link rel="icon" href="${icon}" type="image/svg+xml"/>
<link rel="shortcut icon" href="${icon}" type="image/svg+xml"/>
<style>${STYLE}</style>
</head>
<body class="${tokenLive ? 'token-live' : 'dead-apply'}" data-token-live="${tokenLive ? '1' : '0'}" data-sc4-option="1">
<div class="dash" data-testid="triage-dash">
  <header class="dhead" data-testid="triage-header">
    <img class="brand" src="${brand}" alt="Tidy-Idy" width="52" height="52" data-testid="header-brand">
    <div class="dhead-main">
      <h1>Tidy-Idy — cleanup review</h1>
      <div class="proj">
        <span>run launched from</span>
        <span class="projchip">▶ ${escapeHtml(h.project)}</span>
        <code class="path">${escapeHtml(h.absolutePath)}</code>
        <span class="git ${h.git && h.git.present ? 'ok' : 'none'}">● ${escapeHtml(h.git.summary)}</span>
        ${v.scanned != null ? `<span>${escapeHtml(String(v.scanned))} files scanned</span>` : ''}
      </div>
    </div>
    <div class="meta">
      run #${escapeHtml(h.run.number)} · ${escapeHtml(h.run.endedAt || h.run.ageLabel || '')}<br>
      <span class="fineprint">${escapeHtml(h.run.id || '')}</span>
      <div class="meta-badges">
        <span class="chip status-${escapeHtml(h.status)}">${escapeHtml(String(h.status).toUpperCase())}</span>
        ${(h.badges || []).map((b) => `<span class="chip badge ${escapeHtml(b.tone)}" title="${escapeHtml(b.note)}">${escapeHtml(b.label)}</span>`).join('')}
      </div>
    </div>
  </header>

  <div class="verdicts" id="verdicts" data-testid="verdicts">
    <div class="vpill rm" data-testid="verdict-pill-removals"><div class="n">${escapeHtml(String(v.removals ?? 0))}</div><div class="l">Proposed removals</div></div>
    <div class="vpill save" data-testid="verdict-pill-save"><div class="n">${escapeHtml(String(v.save ?? 0))}</div><div class="l">Unsaved / not in git</div></div>
    <div class="vpill org" data-testid="verdict-pill-reorg"><div class="n">${escapeHtml(String(v.reorg ?? 0))}</div><div class="l">Reorg proposals</div></div>
    <div class="vpill keep" data-testid="verdict-pill-keep"><div class="n">${escapeHtml(String(v.keep ?? 0))}</div><div class="l">Kept / no finding</div></div>
  </div>

  ${renderExecutiveSummary(model.executiveSummary)}

  ${renderTermTile(model.slots && model.slots.investigator)}

  <section id="banners" class="banners">
${deadBanner}
${(model.banners || []).map(renderBanner).join('\n')}
  </section>

${model.clean && !model.clean.celebrate ? `<details class="not-clean sect-collapse" id="not-clean">
  <summary><h2>Not clean — exactly why</h2> <span class="badge">${(model.clean.blockers || []).length} blocker(s) · click to expand</span></summary>
  <ul>${(model.clean.blockers || []).map((b) => `<li>${escapeHtml(b)}</li>`).join('')}</ul>
  <p class="fineprint">source: ${escapeHtml(model.clean.source)}</p>
</details>` : ''}

  <p class="body-hint fineprint" data-testid="collapse-hint">All sections start closed. Expand only what you need. Terminal tile is under the summary (like Zombie Hunter). Apply stays at the bottom.</p>
  <div class="body">
${renderDecisionSections(model)}

${(model.notices || []).length ? `<details class="sect-block sect-collapse" id="notices">
  <summary class="sect">Quarantined notices <span class="badge">${(model.notices || []).length} · not actionable · click to expand</span></summary>
  <div class="sect-body">
  ${(model.notices || []).map((n) => `<article class="card notice"><code>${escapeHtml(n.path)}</code> — ${escapeHtml(n.quarantine)} <span class="fineprint">${escapeHtml(n.note)}</span></article>`).join('\n')}
  </div>
</details>` : ''}

    <details class="sect-block sect-collapse" id="kept">
      <summary class="sect">🛡 Kept &amp; protected <span class="badge">${escapeHtml(String((model.kept && model.kept.count) || 0))} path(s)${(model.kept && model.kept.protected) ? ` · ${escapeHtml(String(model.kept.protected))} withheld` : ''} · click to expand</span></summary>
      <div class="sect-body">
        <p class="fineprint">${escapeHtml((model.kept && model.kept.note) || '')}</p>
        ${((model.kept && model.kept.withheld) || []).length
    ? `<ul class="kept-list">${model.kept.withheld.map((w) => `<li><code>${escapeHtml(w.path)}</code>${w.reason ? ` — ${escapeHtml(w.reason)}` : ''}</li>`).join('')}</ul>`
    : ''}
      </div>
    </details>

    <details class="sect-block sect-collapse" id="trash-view">
      <summary class="sect">Trash — removed items, restorable <span class="badge">click to expand</span></summary>
      <div class="sect-body" id="trash-body">${renderTrash(model.trash)}</div>
    </details>

    <details class="sect-block sect-collapse" id="previous-runs">
      <summary class="sect">Previous runs (${(model.previousRuns || []).length}) — newest first <span class="badge">click to expand</span></summary>
      <div class="sect-body">
      <ol class="prev-runs">${(model.previousRuns || []).map((r) => `<li${r.current ? ' class="current"' : ''}>run ${escapeHtml(r.runNumber)} · ${escapeHtml(r.status)} · ${escapeHtml(r.findings)} finding(s)${r.costGated ? ' · cost-gated' : ''} · ${escapeHtml(r.endedAt)}${r.current ? ' <strong>(this run)</strong>' : ''}</li>`).join('')}</ol>
      </div>
    </details>
  </div>

  <div class="footbar apply-bar" data-testid="apply-bar">
    <button id="bulk-apply" class="apply" data-testid="bulk-apply" ${applyEnabled ? '' : 'disabled'}>Apply approved (${model.counts.bulkApprovable} bulk-approvable) →</button>
    <button id="rescan" class="btn">Re-scan</button>
    <button id="close-release" class="btn">Close &amp; release lock</button>
    <span id="apply-state" class="undo">Apply state: ${escapeHtml(model.apply.state)}</span>
    ${disabledChip}
    <p class="undo fineprint" data-testid="token-footprint">${tokenFootprint}</p>
  </div>
</div>

<footer class="foot">Header, summary, and pills stay open. Every tile section starts closed — expand only what you need. Nothing happens until you Apply.</footer>

<script type="module">
// ---- capability token: BROWSER MEMORY ONLY (SC4 Option 1) ------------------
// Never write TOKEN to durable browser sinks, the URL, or history.
// F5 / reload drops this binding; Apply must not silently re-enable without a fresh open.
const TOKEN = ${embedJson(tokenLive ? token : '')};
const TOKEN_USABLE = ${embedJson(tokenLive)};
const BASE = ${embedJson(baseUrl)};
const MODEL = ${embedJson(model)};
const RUN_ID = ${embedJson(model.apply.runId)};
const DEAD_REOPEN = ${embedJson(DEAD_APPLY_REOPEN_COPY)};
// Built at runtime so live HTML never contains the dead-banner testid attribute form.
const DEAD_BANNER_TID = 'dead-apply' + '-banner';
const DEAD_CHIP_TID = 'dead-apply' + '-chip';

const post = (path, body) => {
  if (!TOKEN_USABLE) {
    return Promise.resolve({
      status: 401,
      body: { error: 'no usable capability token — re-open the panel from the tool', detail: DEAD_REOPEN },
    });
  }
  // Capability token stays browser-memory only (never storage/URL).
  // When this page is opened through Anchor's reverse proxy (Tailscale), the
  // dashboard shared-secret rides on the page URL as ?token= (Anchor convention
  // for GET navigations). Forward it as X-Anchor-Token so POSTs re-enter the
  // proxy; direct loopback opens have no such query and need no Anchor header.
  const headers = {
    'content-type': 'application/json',
    ${embedJson(TOKEN_HEADER)}: TOKEN,
  };
  try {
    const at = new URLSearchParams(location.search).get('token');
    if (at) headers['X-Anchor-Token'] = at;
  } catch (_e) { /* non-browser / opaque origin */ }
  return fetch(BASE + path, {
    method: 'POST',
    headers,
    body: JSON.stringify(body || {}),
  }).then((r) => r.json().then((j) => ({ status: r.status, body: j })));
};

const say = (msg) => {
  const el = document.getElementById('apply-state');
  if (el) el.textContent = msg;
};

/** Option 1 dead-Apply: disable Apply chrome and surface re-open instruction. */
function enterDeadApply(reason) {
  document.body.classList.remove('token-live');
  document.body.classList.add('dead-apply');
  document.body.setAttribute('data-token-live', '0');
  const bulk = document.getElementById('bulk-apply');
  if (bulk) bulk.disabled = true;
  document.querySelectorAll('button.confirm-one, button.approve-set, input.approve').forEach((el) => {
    el.disabled = true;
  });
  let chip = document.getElementById('apply-disabled');
  if (!chip) {
    chip = document.createElement('span');
    chip.id = 'apply-disabled';
    chip.className = 'chip amber';
    chip.setAttribute('data-testid', DEAD_CHIP_TID);
    const bar = document.querySelector('.apply-bar');
    if (bar) bar.appendChild(chip);
  }
  chip.textContent = ${embedJson(DEAD_APPLY_CHIP_LABEL)};
  const foot = document.querySelector('[data-testid="token-footprint"]');
  if (foot) foot.textContent = DEAD_REOPEN;
  let banner = document.querySelector('[data-testid=' + DEAD_BANNER_TID + ']');
  if (!banner) {
    banner = document.createElement('div');
    banner.className = 'banner amber';
    banner.setAttribute('data-kind', 'dead-apply');
    banner.setAttribute('data-testid', DEAD_BANNER_TID);
    banner.innerHTML = '<strong></strong><p></p>';
    const host = document.getElementById('banners');
    if (host) host.prepend(banner);
  }
  const title = banner.querySelector('strong');
  const msg = banner.querySelector('p');
  if (title) title.textContent = ${embedJson(DEAD_APPLY_BANNER_TITLE)};
  if (msg) msg.textContent = reason || DEAD_REOPEN;
  say('Apply disabled — re-open the panel from tidy-idy CLI or Anchor');
}

if (!TOKEN_USABLE) enterDeadApply(DEAD_REOPEN);

const beat = () => { if (TOKEN_USABLE) post('/api/heartbeat', {}).catch(() => {}); };
beat();
setInterval(beat, 15000);

function approvalsFor(scope) {
  const checked = new Set(Array.from(document.querySelectorAll('input.approve:checked')).map((el) => el.value));
  return MODEL.tiles
    .filter((t) => t.approval && checked.has(t.id))
    .filter((t) => scope !== 'bulk' || t.bulkApprovable)
    .map((t) => t.approval);
}

document.getElementById('bulk-apply').addEventListener('click', async (e) => {
  if (!TOKEN_USABLE) { enterDeadApply(DEAD_REOPEN); return; }
  const approvals = approvalsFor('bulk');
  if (!approvals.length) { say('nothing approved'); return; }
  e.target.disabled = true;
  say('applying…');
  const r = await post('/api/apply', { runId: RUN_ID, approvals });
  say(r.body && r.body.replay
    ? 'already applied — showing the recorded result of that Apply (no second commit)'
    : 'Apply ' + ((r.body && r.body.result && r.body.result.status) || r.status));
});

document.querySelectorAll('button.confirm-one').forEach((btn) => {
  if (!TOKEN_USABLE) btn.disabled = true;
  btn.addEventListener('click', async () => {
    if (!TOKEN_USABLE) { enterDeadApply(DEAD_REOPEN); return; }
    const tile = MODEL.tiles.find((t) => t.id === btn.dataset.id);
    if (!tile || !tile.approval) return;
    btn.disabled = true;
    const r = await post('/api/apply', { runId: RUN_ID, approvals: [tile.approval] });
    say('Apply ' + ((r.body && r.body.result && r.body.result.status) || r.status));
  });
});

document.querySelectorAll('button.approve-set').forEach((btn) => {
  if (!TOKEN_USABLE) btn.disabled = true;
  btn.addEventListener('click', () => {
    if (!TOKEN_USABLE) { enterDeadApply(DEAD_REOPEN); return; }
    const setId = btn.dataset.set;
    document.querySelectorAll('input.approve[data-set="' + setId + '"]').forEach((el) => {
      if (!el.disabled) el.checked = true;
    });
    say('selected all bulk-approvable items in that folder set');
  });
});

document.getElementById('rescan').addEventListener('click', async (e) => {
  if (!TOKEN_USABLE) { enterDeadApply(DEAD_REOPEN); return; }
  e.target.disabled = true;
  const r = await post('/api/rescan', { runId: RUN_ID });
  say('re-scan: ' + ((r.body && r.body.message) || r.status));
});

document.querySelectorAll('button.confirm-full-run').forEach((btn) => {
  btn.addEventListener('click', async () => {
    if (!TOKEN_USABLE) { enterDeadApply(DEAD_REOPEN); return; }
    btn.disabled = true;
    const r = await post('/api/confirm-full-run', { runId: RUN_ID });
    say('full-scope re-run: ' + ((r.body && r.body.message) || r.status));
  });
});

document.querySelectorAll('button.restore').forEach((btn) => {
  btn.addEventListener('click', async () => {
    if (!TOKEN_USABLE) { enterDeadApply(DEAD_REOPEN); return; }
    btn.disabled = true;
    const r = await post('/api/restore', { runId: RUN_ID, trashRunId: btn.dataset.run, paths: btn.dataset.path ? [btn.dataset.path] : null });
    btn.textContent = (r.body && r.body.result && r.body.result.status === 'ok') ? 'restored' : 'restore: ' + r.status;
  });
});

// ZH-style terminal tile: expand head, then start engines.
const termTile = document.getElementById('termTile');
const termHead = document.getElementById('termHead');
const termBody = document.getElementById('termBody');
if (termHead && termBody && termTile) {
  termHead.addEventListener('click', () => {
    const open = termTile.classList.toggle('open');
    termBody.style.display = open ? 'block' : 'none';
  });
}

async function startInvestigate(btn, deep) {
  if (!TOKEN_USABLE) { enterDeadApply(DEAD_REOPEN); return; }
  const picked = document.querySelector('input[name="investigator-engine"]:checked');
  const engine = picked ? picked.value : null;
  const st = document.getElementById('investigate-state');
  const hint = document.getElementById('termHint');
  if (btn) { btn.disabled = true; }
  if (st) st.textContent = 'opening…';
  if (hint) hint.textContent = deep ? 'deep brief…' : 'starting…';
  const r = await post('/api/investigate', { runId: RUN_ID, engine, deepBrief: !!deep });
  const msg = (r.body && r.body.message) || ('investigate: ' + r.status);
  if (st) st.textContent = msg;
  if (hint) hint.textContent = msg;
  say(msg);
  if (btn) { btn.disabled = false; }
}

const investigateBtn = document.getElementById('investigate');
if (investigateBtn) investigateBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  startInvestigate(investigateBtn, false);
});
const investigateDeep = document.getElementById('investigate-deep');
if (investigateDeep) investigateDeep.addEventListener('click', (e) => {
  e.stopPropagation();
  startInvestigate(investigateDeep, true);
});
// Engine toggles must not collapse the tile.
document.querySelectorAll('.engtoggle .eng, .engtoggle').forEach((el) => {
  el.addEventListener('click', (e) => e.stopPropagation());
});
document.querySelectorAll('.engtoggle .eng').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.engtoggle .eng').forEach((b) => b.classList.remove('on'));
    btn.classList.add('on');
    const radio = document.querySelector('input[name="investigator-engine"][value="' + btn.dataset.eng + '"]');
    if (radio) radio.checked = true;
  });
});

// Clicks on checkboxes / buttons inside collapsed sections must not re-toggle <details>.
document.querySelectorAll('.sect-body, .folder-set').forEach((root) => {
  root.addEventListener('click', (e) => {
    const t = e.target;
    if (!t) return;
    if (t.closest && (t.closest('input') || t.closest('button') || t.closest('label') || t.closest('a'))) {
      e.stopPropagation();
    }
  });
});

document.getElementById('close-release').addEventListener('click', async () => {
  // P1 2026-07-25 (MAJOR dead-token-close-must-not-claim-lock-released): only claim a
  // release that actually happened. A dead token never called /api/close, and a failed
  // call proves nothing — saying "released" either way was a false safety claim.
  if (TOKEN_USABLE) {
    const r = await post('/api/close', {}).catch(() => null);
    document.body.classList.add('closed');
    say(r && r.status >= 200 && r.status < 300
      ? 'panel closed — the project lock has been released'
      : 'panel closed — lock release NOT confirmed (server unreachable); the lock may still be held until the server exits');
  } else {
    document.body.classList.add('closed');
    say('panel closed — this token is expired, so the lock was NOT released from here; re-open the panel (fresh link) to release it, or stop the panel server');
  }
});

window.addEventListener('pagehide', () => { /* beats stop; the server reclaims */ });
</script>
</body>
</html>
`;
}

/** SC4 Option 1 — honest dead-Apply banner (no token remount). */
function renderDeadApplyBanner() {
  return `<div class="banner amber" data-kind="dead-apply" data-testid="dead-apply-banner">
  <strong>${escapeHtml(DEAD_APPLY_BANNER_TITLE)}</strong>
  <p>${escapeHtml(DEAD_APPLY_REOPEN_COPY)}</p>
</div>`;
}

/**
 * One-page executive summary — always open, plain-English bullets.
 * Built in model.mjs; this is a dumb projection.
 */
function renderExecutiveSummary(exec) {
  if (!exec || !(exec.bullets || []).length) return '';
  const found = (exec.found || []).map((b) => `<li>${escapeHtml(b)}</li>`).join('\n');
  const recs = (exec.recommendations || []).map((b) => `<li>${escapeHtml(b)}</li>`).join('\n');
  // Fallback: flat bullets list when structured halves are absent.
  const flat = !found && !recs
    ? `<ul class="exec-list">${(exec.bullets || []).map((b) => `<li>${escapeHtml(b)}</li>`).join('\n')}</ul>`
    : '';
  return `<section class="exec-summary" id="exec-summary" data-testid="executive-summary">
  <h2>${escapeHtml(exec.title || 'At a glance')}</h2>
  ${exec.lede ? `<p class="exec-lede">${escapeHtml(exec.lede)}</p>` : ''}
  ${found ? `<h3 class="exec-h">What Tidy-Idy found</h3><ul class="exec-list" data-testid="exec-found">${found}</ul>` : ''}
  ${recs ? `<h3 class="exec-h">What it recommends</h3><ul class="exec-list" data-testid="exec-recs">${recs}</ul>` : ''}
  ${flat}
  ${exec.footer ? `<p class="fineprint exec-foot">${escapeHtml(exec.footer)}</p>` : ''}
</section>`;
}

function fallbackGroups(model) {
  // Older models without actionSections still render via class groups.
  return (model.groups || []).map((g) => renderActionSection({
    id: g.class,
    title: g.title,
    badge: g.subtitle,
    tone: g.class === 'removal' || g.class === 'heuristic-removal' ? 'rm'
      : g.class === 'save' || g.class === 'quarantine' ? 'save'
        : g.class === 'reorg' ? 'org' : 'other',
    sets: [{ kind: 'flat', tiles: g.tiles }],
  })).join('\n');
}

/** All decision sections start collapsed — operator expands only what they need. */
function renderDecisionSections(model) {
  const sections = model.actionSections || [];
  if (!sections.length) return fallbackGroups(model);
  return sections.map((s) => renderActionSection(s, { open: false })).join('\n');
}

/**
 * ZH-style terminal tile (under pills): expand → pick engine → open seeded terminal.
 * Same product idea as Zombie Hunter's "Investigate with an agent" tile.
 */
function renderTermTile(inv) {
  const active = inv && inv.active;
  const engines = (inv && inv.engines) || [
    { id: 'claude', label: 'Claude', default: true },
    { id: 'gemini', label: 'Gemini', default: false },
    { id: 'grok', label: 'Grok', default: false },
  ];
  const note = active
    ? (inv.note || 'Seeded agent terminal in this project with the current-run briefing.')
    : (inv && inv.note) || 'Investigator hook not wired for this launch — expand for details.';
  const briefing = inv && inv.briefing && inv.briefing.path
    ? `<p class="fineprint">briefing: <code>${escapeHtml(inv.briefing.path)}</code></p>`
    : '';
  const disabled = active ? '' : 'disabled';
  return `<div class="term-tile" id="termTile" data-testid="term-tile">
  <div class="term-head" id="termHead" role="button" tabindex="0" aria-expanded="false">
    <span class="caret">▶</span>
    <span class="tt">🔎 Investigate with an agent</span>
    <span class="tsub">like Zombie Hunter · slim seed · Claude / Gemini / Grok</span>
    <span class="engtoggle" onclick="event.stopPropagation()">
      ${engines.map((e) => `<button type="button" class="eng${e.default ? ' on' : ''}" data-eng="${escapeHtml(e.id)}" title="${escapeHtml(e.label)}">${escapeHtml(e.label)}</button>`).join('')}
    </span>
  </div>
  <div class="term-body" id="termBody" style="display:none">
    <p class="note">${escapeHtml(note)}</p>
    <div class="control" style="display:none">
      ${engines.map((e) => `<label class="radio"><input type="radio" name="investigator-engine" value="${escapeHtml(e.id)}"${e.default ? ' checked' : ''}> ${escapeHtml(e.label)}</label>`).join(' ')}
    </div>
    <p class="acts">
      <button type="button" id="investigate" class="btn-start" ${disabled}>Start terminal (slim seed)</button>
      <button type="button" id="investigate-deep" class="btn" ${disabled}>Deep brief</button>
      <span id="termHint" class="hint"></span>
      <span id="investigate-state" class="fineprint"></span>
    </p>
    ${briefing}
  </div>
</div>`;
}

function renderActionSection(s, opts = {}) {
  const total = (s.sets || []).reduce((n, set) => n + (set.tiles || []).length, 0);
  // Always start closed at report open (opts.open reserved for future explicit open).
  const openAttr = opts.open ? ' open' : '';
  // Whole middle section is a <details> — title + count visible; body collapsed.
  if (!total) {
    if (!s.alwaysShow && !s.emptyNote) return '';
    return `<details class="sect-block sect-collapse" data-section="${escapeHtml(s.id)}" data-testid="decision-section-${escapeHtml(s.id)}" data-empty="1"${openAttr}>
  <summary class="sect">${escapeHtml(s.title)} <span class="badge">0${s.badge ? ' · ' + escapeHtml(s.badge) : ''} · click to expand</span></summary>
  <div class="sect-body">
    <div class="empty-sect" data-testid="section-empty-${escapeHtml(s.id)}">${escapeHtml(s.emptyNote || 'Nothing in this section.')}</div>
  </div>
</details>`;
  }
  const bulkN = (s.sets || []).reduce(
    (n, set) => n + (set.bulkApprovableCount || (set.tiles || []).filter((t) => t.bulkApprovable).length),
    0,
  );
  const previewNames = [];
  for (const set of s.sets || []) {
    for (const t of set.tiles || []) {
      if (previewNames.length >= 5) break;
      const nm = t.basename || t.path;
      if (nm) previewNames.push(nm);
    }
    if (previewNames.length >= 5) break;
  }
  const peek = previewNames.length
    ? `<span class="sect-peek fineprint">${previewNames.map(escapeHtml).join(' · ')}${total > previewNames.length ? ` · +${total - previewNames.length} more` : ''}</span>`
    : '';
  // Groups inside also start closed — no auto-open first group.
  return `<details class="sect-block sect-collapse" data-section="${escapeHtml(s.id)}" data-testid="decision-section-${escapeHtml(s.id)}"${openAttr}>
  <summary class="sect">${escapeHtml(s.title)} <span class="badge">${escapeHtml(String(total))}${bulkN ? ` · ${bulkN} bulk-ok` : ''}${s.badge ? ' · ' + escapeHtml(s.badge) : ''} · click to expand</span>${peek}</summary>
  <div class="sect-body">
  ${(s.sets || []).map((set, i) => renderSet(set, s, i, { open: false })).join('\n')}
  </div>
</details>`;
}

function renderSet(set, section, idx, opts = {}) {
  const setId = `${section.id}-${idx}`;
  const tiles = set.tiles || [];
  if (!tiles.length) return '';

  const isGroup = set.kind === 'folder' || set.kind === 'pattern' || set.kind === 'toplevel';
  // Always collapse groups AND flat multi-item lists — closed at report start.
  if (isGroup || tiles.length > 1) {
    const bulkN = set.bulkApprovableCount || tiles.filter((t) => t.bulkApprovable).length;
    const label = set.label
      || (set.folder ? `${tiles.length} under ${set.folder}/` : null)
      || `${tiles.length} items`;
    const preview = tiles.slice(0, 5).map((t) => t.basename || t.path).filter(Boolean);
    const more = tiles.length > preview.length ? ` · +${tiles.length - preview.length} more` : '';
    const previewLine = preview.length
      ? `<p class="set-preview fineprint">${preview.map(escapeHtml).join(' · ')}${escapeHtml(more)}</p>`
      : '';
    // Prefer compact rows for any multi-item set (ZH-style).
    const body = tiles.length >= 2
      ? renderCompactTileList(tiles, setId, set.previewMax || 12)
      : tiles.map((t) => renderTile(t, setId)).join('\n');
    const openAttr = opts.open ? ' open' : '';
    return `<details class="folder-set" data-kind="${escapeHtml(set.kind || 'flat')}" data-folder="${escapeHtml(set.folder || '')}" data-pattern="${escapeHtml(set.pattern || '')}"${openAttr}>
  <summary class="folder-sum">
    <span class="fname">${escapeHtml(label)}</span>
    <span class="fmeta">${tiles.length} item(s)${bulkN ? ` · ${bulkN} bulk-approvable` : ''} · click to expand</span>
  </summary>
  ${previewLine}
  ${bulkN ? `<p class="set-acts"><button type="button" class="btn approve-set" data-set="${escapeHtml(setId)}">Select all bulk-approvable in this group</button></p>` : ''}
  ${body}
</details>`;
  }

  // Single item: still one compact card (not a wall of chrome).
  return renderTile(tiles[0], setId, { compact: tiles[0].class !== 'reorg' });
}

/** Dense rows — name + approve; why/evidence one click away. */
function renderCompactTileList(tiles, setId, previewMax = 12) {
  // All compact; if very long, nest further collapse after previewMax.
  if (tiles.length <= previewMax) {
    return tiles.map((t) => renderTile(t, setId, { compact: t.class !== 'reorg' })).join('\n');
  }
  const head = tiles.slice(0, previewMax);
  const tail = tiles.slice(previewMax);
  return `${head.map((t) => renderTile(t, setId, { compact: t.class !== 'reorg' })).join('\n')}
<details class="folder-set flat-more">
  <summary class="folder-sum"><span class="fname">Show remaining ${tail.length}</span></summary>
  ${tail.map((t) => renderTile(t, setId, { compact: t.class !== 'reorg' })).join('\n')}
</details>`;
}

/** @deprecated body slot — terminal lives in ZH-style term-tile under pills. */
function renderInvestigator(inv) {
  return renderTermTile(inv);
}

function renderBanner(b) {
  return `<div class="banner ${escapeHtml(b.level)}" data-kind="${escapeHtml(b.kind)}">
  <strong>${escapeHtml(b.title)}</strong>
  <p>${escapeHtml(b.message)}</p>
  ${(b.blockers || []).length ? `<ul>${b.blockers.map((x) => `<li>${escapeHtml(x)}</li>`).join('')}</ul>` : ''}
  ${(b.missing || []).length ? `<p class="missing">missing: ${b.missing.map(escapeHtml).join('; ')}</p>` : ''}
  ${(b.errors || []).length ? `<pre class="verbatim">${b.errors.map((e) => escapeHtml(`${e.name}: ${e.message}`)).join('\n')}</pre>` : ''}
  ${b.action ? `<button type="button" class="${escapeHtml(b.action.id)} btn">${escapeHtml(b.action.label)}</button>` : ''}
</div>`;
}

function renderTile(t, setId = '', opts = {}) {
  const compact = Boolean(opts.compact);
  const tone = t.class === 'removal' || t.class === 'heuristic-removal' ? 'rm'
    : t.class === 'save' || t.class === 'quarantine' ? 'save'
      : t.class === 'reorg' ? 'org'
        : t.class === 'secret-blocked' ? 'secret' : '';
  const isReorg = t.class === 'reorg';
  const name = t.basename || t.path || '(unknown)';
  const why = t.summaryWhy || t.why || '';
  // Compact: decision row only — full path + evidence under details (Mockup A density).
  if (compact && !isReorg) {
    return `<article class="card compact ${tone} ${escapeHtml(t.class)}" id="tile-${escapeHtml(t.id || t.path)}" data-testid="finding-tile" data-tile-class="${escapeHtml(t.class || '')}" data-compact="1">
  <div class="crow">
    ${renderControls(t, setId)}
    <span class="fname" title="${escapeHtml(t.path)}">${escapeHtml(name)}</span>
    <span class="fmeta" data-testid="path-secondary" title="${escapeHtml(t.absolutePath || '')}">${escapeHtml(t.path || '')}</span>
  </div>
  <details class="evidence" data-testid="evidence-details">
    <summary>Show evidence (verbatim)</summary>
    ${why ? `<p class="why">${escapeHtml(why)}</p>` : ''}
    ${(t.badges || []).length ? `<p class="badges" data-testid="tile-badges">${t.badges.map((b) => `<span class="chip">${escapeHtml(b)}</span>`).join(' ')}</p>` : ''}
    ${renderEvidence(t)}
  </details>
</article>`;
  }
  // W3 / SC2: reorg decision chrome order is crow → badges → primary tree →
  // always-visible safety chips → why → controls → secondary evidence.
  // Primary trees must NOT live under details.evidence (hollow-tree ban target).
  // Path hierarchy: basename primary; project-relative secondary (fmeta);
  // absolute paths only as secondary disclosure (title / evidence) — never sole primary label.
  return `<article class="card ${tone} ${escapeHtml(t.class)}" id="tile-${escapeHtml(t.id || t.path)}" data-testid="${isReorg ? 'reorg-tile' : 'finding-tile'}" data-tile-class="${escapeHtml(t.class || '')}">
  <div class="crow">
    <span class="fname" title="${escapeHtml(t.path)}">${escapeHtml(name)}</span>
    <span class="fmeta" data-testid="path-secondary" title="${escapeHtml(t.absolutePath || '')}">${escapeHtml(t.path || '')}</span>
  </div>
  ${(t.badges || []).length ? `<p class="badges" data-testid="tile-badges">${t.badges.map((b) => `<span class="chip">${escapeHtml(b)}</span>`).join(' ')}</p>` : ''}
  ${isReorg ? renderPrimaryTreeDiff(t) : ''}
  ${isReorg ? renderReorgSafetyChrome(t) : ''}
  ${why ? `<p class="why">${escapeHtml(why)}</p>` : ''}
  ${renderControls(t, setId)}
  <details class="evidence" data-testid="evidence-details">
    <summary>Show evidence (verbatim)</summary>
    ${renderEvidence(t)}
  </details>
  ${t.undo ? `<p class="fineprint">undo: ${escapeHtml(t.undo)}</p>` : ''}
</article>`;
}

/**
 * Short relative label under a move root (Mockup A2 hierarchy: primary scannable
 * names; full project-relative paths stay secondary via title/evidence).
 */
export function shortRelLabel(entry, root) {
  const e = String(entry == null ? '' : entry).replace(/\\/g, '/');
  const r = String(root == null ? '' : root).replace(/\\/g, '/').replace(/\/+$/, '');
  if (!e) return '';
  if (r && (e === r || e.startsWith(`${r}/`))) {
    const rel = e === r ? r.split('/').pop() || r : e.slice(r.length + 1);
    return rel || e;
  }
  const i = e.lastIndexOf('/');
  return i < 0 ? e : e.slice(i + 1);
}

/**
 * W3/W4: before→after tree-diff as PRIMARY card chrome (not under details.evidence).
 * Hollow-tree ban: missing or empty before/after must NOT paint empty columns as if
 * a real tree-diff existed — honest missing chrome only (fail closed for SC2).
 */
function renderPrimaryTreeDiff(t) {
  const e = t.evidence || {};
  const before = e.before;
  const after = e.after;
  const beforeEntries = before && Array.isArray(before.entries) ? before.entries : null;
  const afterEntries = after && Array.isArray(after.entries) ? after.entries : null;
  const hollow = !beforeEntries || beforeEntries.length === 0
    || !afterEntries || afterEntries.length === 0
    || !(before && before.root)
    || !(after && after.root);
  if (hollow) {
    return `<div class="tree-diff primary-tree-diff hollow" data-testid="primary-tree-diff" data-hollow="true">
  <p class="warn" data-testid="hollow-tree-ban">before→after tree missing or empty — cannot project a non-empty tree-diff from finding fields</p>
</div>`;
  }
  const treeCol = (label, tree, side) => {
    const root = tree.root || '';
    const entries = tree.entries;
    return `<div class="tree bacol${side === 'after' ? ' after' : ''}" data-side="${escapeHtml(side)}">
      <div class="bah${side === 'after' ? ' a' : ''}">${escapeHtml(label)}: <code class="tree-root">${escapeHtml(root)}/</code></div>
      <ul class="tree-entries" data-testid="tree-entries-${escapeHtml(side)}">${entries.map((p) => {
    const full = String(p);
    const short = shortRelLabel(full, root);
    // Short relative label is the visible primary text; full project-relative path is title only.
    return `<li class="tnode${side === 'after' ? ' moved' : ''}" title="${escapeHtml(full)}"><code>${escapeHtml(short)}</code></li>`;
  }).join('')}</ul>
    </div>`;
  };
  return `<div class="tree-diff primary-tree-diff" data-testid="primary-tree-diff" data-hollow="false">
  ${treeCol('before', before, 'before')}
  <span class="arrow" aria-hidden="true">→</span>
  ${treeCol('after', after, 'after')}
</div>`;
}

/**
 * Always-visible hit-count / referenceUnsafe / override-only chrome.
 * Must remain scannable without expanding details.evidence (zero-hit vs non-zero-hit differential).
 * Fail closed: missing / non-numeric hitCount must NOT claim zero-hit bulk-approvable (W4).
 */
function renderReorgSafetyChrome(t) {
  const e = t.evidence || {};
  const scan = e.referenceScan;
  const rawHit = scan && scan.hitCount;
  const hasScan = scan != null && rawHit != null && Number.isFinite(Number(rawHit));
  if (!hasScan) {
    // Missing scan is not "0 hits" — never fail open to bulk-approvable.
    return `<div class="reorg-safety" data-testid="reorg-safety">
  <p class="hit-count unsafe" data-testid="reference-scan-chip">
    <span class="chip amber" data-testid="scan-missing-chip">reference scan missing — not bulk-approvable</span>
    <span class="chip amber" data-testid="override-only-chip">override only — not bulk</span>
  </p>
</div>`;
  }
  const n = Number(rawHit);
  const tone = n === 0 ? 'safe' : 'unsafe';
  const override = Boolean(
    n > 0
    || (t.confirmIndividually && t.confirmIndividually.override)
    || e.referenceUnsafe
    || t.bulkApprovable === false,
  );
  const unsafe = e.referenceUnsafe;
  return `<div class="reorg-safety" data-testid="reorg-safety">
  <p class="hit-count ${tone}" data-testid="reference-scan-chip">
    <span class="chip">${escapeHtml(String(n))} reference hit(s)</span>
    ${scan.scannedFiles != null ? `<span class="fineprint"> · ${escapeHtml(String(scan.scannedFiles))} scanned file(s)</span>` : ''}
    ${override
    ? `<span class="chip amber" data-testid="override-only-chip">override only — not bulk</span>`
    : `<span class="chip safe-chip" data-testid="bulk-approvable-chip">bulk-approvable</span>`}
  </p>
  ${unsafe && unsafe.reason
    ? `<p class="warn" data-testid="reference-unsafe-reason">${escapeHtml(unsafe.reason)}</p>`
    : ''}
</div>`;
}

function renderControls(t, setId = '') {
  if (!t.approvable) {
    return `<p class="no-control">${escapeHtml(t.class === 'secret-blocked'
      ? 'no approval control — blocked by construction'
      : 'informational — nothing to approve')}</p>`;
  }
  if (!t.bulkApprovable) {
    const label = (t.confirmIndividually && t.confirmIndividually.label)
      || (t.confirmIndividually && t.confirmIndividually.override
        ? "Apply anyway — I'll fix the references"
        : 'Confirm this one individually');
    return `<div class="acts">
      <button type="button" class="btn approve confirm-one" data-id="${escapeHtml(t.id)}">${escapeHtml(label)}</button>
      <span class="fineprint">excluded from bulk${t.confirmIndividually && t.confirmIndividually.why ? ` — ${escapeHtml(t.confirmIndividually.why)}` : ''}</span>
    </div>`;
  }
  return `<div class="acts">
    <label class="chk"><input type="checkbox" class="approve" value="${escapeHtml(t.id)}" data-set="${escapeHtml(setId)}"${t.defaultChecked ? ' checked' : ''}> approve</label>
  </div>`;
}

function renderEvidence(t) {
  const parts = [];
  const e = t.evidence || {};

  if (t.class === 'removal') {
    parts.push(`<div class="ev"><h4>Attacker's case ${e.attacker && e.attacker.verbatim ? '(verbatim)' : ''}</h4>${
      e.attacker && e.attacker.claim
        ? `<pre class="verbatim">${escapeHtml(e.attacker.claim)}</pre><p class="fineprint">strength (verbatim): ${escapeHtml(e.attacker.strength)}</p>`
        : `<p class="fineprint">${escapeHtml((e.attacker && e.attacker.note) || 'not recorded')}</p>`
    }</div>`);
    parts.push(`<div class="ev"><h4>Judge verdict (verbatim)</h4><p class="verdict">${escapeHtml(e.judge && e.judge.decision)}</p><pre class="verbatim">${escapeHtml((e.judge && e.judge.rationale) || '(no rationale recorded)')}</pre></div>`);
    parts.push(`<div class="ev"><h4>Confidence</h4><p>${escapeHtml(e.confidence && e.confidence.value ? `${e.confidence.value} — ${e.confidence.source}` : (e.confidence && e.confidence.note) || 'not recorded')}</p></div>`);
    if (e.porcelain) parts.push(`<div class="ev"><h4>git porcelain (verbatim)</h4><pre class="verbatim">${escapeHtml(e.porcelain)}</pre></div>`);
  }

  if (t.class === 'heuristic-removal') {
    const hs = e.heuristics || [];
    parts.push(`<div class="ev"><h4>Heuristic signals</h4><p>${escapeHtml(hs.join(', ') || 'none listed')}</p>
      ${e.note ? `<p class="fineprint">${escapeHtml(e.note)}</p>` : ''}
      <details><summary>Raw evidence JSON</summary><pre class="verbatim">${escapeHtml(JSON.stringify(e.raw, null, 2))}</pre></details>
    </div>`);
  }

  if (t.class === 'save' || t.class === 'quarantine') {
    if (e.porcelain) parts.push(`<div class="ev"><h4>git porcelain (verbatim)</h4><pre class="verbatim">${escapeHtml(e.porcelain)}</pre></div>`);
    if (e.stagedWarning) parts.push(`<p class="warn">${escapeHtml(e.stagedWarning)}</p>`);
    const d = e.dirtyOverlap;
    if (d && d.available) {
      parts.push(`<div class="ev"><h4>What a commit would contain — ${escapeHtml(d.source)}</h4>
        <details><summary>Diff (${escapeHtml(String((d.diff || '').length))} chars) — expand only if needed</summary>
        <pre class="verbatim diff">${escapeHtml(d.diff)}</pre></details>
        ${d.changedWarning ? `<p class="warn">${escapeHtml(d.changedWarning)}</p>` : ''}</div>`);
    } else if (d) {
      parts.push(`<div class="ev"><h4>No diff rendered</h4><p class="fineprint">${escapeHtml(d.reason)}</p></div>`);
    }
  }

  if (t.class === 'secret-blocked') {
    parts.push(`<div class="ev"><h4>Why it is blocked</h4><ul>${(e.triggers || []).map((x) => `<li>rule <code>${escapeHtml(x.rule)}</code>${x.where ? ` at ${escapeHtml(x.where)}` : ''}${x.line != null ? ` line ${escapeHtml(x.line)}` : ''}</li>`).join('')}</ul>
      ${e.maskedTriggerText ? `<pre class="verbatim masked">${escapeHtml(e.maskedTriggerText)}</pre>` : ''}</div>`);
    parts.push(`<div class="ev"><h4>Remediation</h4><ol>${(e.remediation || []).map((r) => `<li><strong>${escapeHtml(r.kind || r.id || 'option')}</strong> — ${escapeHtml(r.summary || r.note || r.description || '')}${r.command ? `<pre class="verbatim">${escapeHtml(r.command)}</pre>` : ''}</li>`).join('')}</ol></div>`);
  }

  if (t.class === 'bootstrap') {
    parts.push(`<div class="ev"><h4>Bootstrap steps</h4><ol>${(e.steps || []).map((s) => `<li><strong>${escapeHtml(s.kind)}</strong> — ${escapeHtml(s.summary)}</li>`).join('')}</ol></div>`);
  }

  if (t.class === 'reorg') {
    // W3: primary trees + hit chip live OUTSIDE this disclosure. Evidence holds
    // secondary full paths, raw hit lines, and verbatim move metadata only.
    const scan = e.referenceScan || {};
    const before = e.before || { root: '', entries: [] };
    const after = e.after || { root: '', entries: [] };
    const move = e.move || {};
    if (move.from || move.to) {
      parts.push(`<div class="ev" data-testid="reorg-move-secondary"><h4>Move paths (full relative)</h4>
        <p><code>${escapeHtml(move.from || '')}</code> → <code>${escapeHtml(move.to || '')}</code></p></div>`);
    }
    parts.push(`<div class="ev" data-testid="reorg-full-path-trees"><h4>Full path listing (secondary)</h4>
      <p class="fineprint">Primary card shows short labels under each move root; full project-relative paths are here for audit.</p>
      <pre class="verbatim">before ${escapeHtml(before.root || '')}/
${escapeHtml((before.entries || []).join('\n'))}

after ${escapeHtml(after.root || '')}/
${escapeHtml((after.entries || []).join('\n'))}</pre></div>`);
    const hitKnown = scan.hitCount != null && Number.isFinite(Number(scan.hitCount));
    const hitLabel = hitKnown ? String(Number(scan.hitCount)) : 'unknown';
    const safeOnlyWhenZero = hitKnown && Number(scan.hitCount) === 0 && !(scan.hits || []).length;
    parts.push(`<div class="ev" data-testid="reorg-reference-hits-secondary"><h4>Whole-tree reference scan (detail)</h4>
      <p class="fineprint">${escapeHtml(hitLabel)} hit(s) · ${escapeHtml(String(scan.scannedFiles ?? '—'))} scanned · ${escapeHtml(scan.scope || '')}</p>${
  (scan.hits || []).length
    ? `<pre class="verbatim">${escapeHtml((scan.hits || []).map((h) => `${h.path}:${h.line}: ${h.text}`).join('\n'))}</pre>`
    : safeOnlyWhenZero
      ? '<p class="fineprint">no references found — move is reference-safe</p>'
      : '<p class="fineprint">reference scan detail unavailable or incomplete — not treated as zero-hit</p>'
}</div>`);
    if (e.referenceUnsafe) {
      parts.push(`<p class="warn">${escapeHtml(e.referenceUnsafe.reason)}</p>`);
    }
    if ((e.members || []).length) {
      parts.push(`<div class="ev"><h4>Members</h4><pre class="verbatim">${escapeHtml((e.members || []).join('\n'))}</pre></div>`);
    }
  }

  return parts.join('\n') || '<p class="fineprint">no structured evidence on this tile</p>';
}

function renderTrash(trash) {
  if (!trash || !(trash.runs || []).length) {
    return '<p class="fineprint">nothing in the Trash for this project.</p>';
  }
  return (trash.runs || []).map((r) => `<article class="card trash-run">
  <h3>run <code>${escapeHtml(r.runId)}</code> — ${escapeHtml(r.held)} held, ${escapeHtml(r.restored)} restored${r.expired ? ' — past TTL' : ''}</h3>
  <ul>${(r.items || []).map((i) => `<li><code>${escapeHtml(i.path)}</code>${i.restored ? ' — restored' : ` <button type="button" class="restore btn" data-run="${escapeHtml(r.runId)}" data-path="${escapeHtml(i.path)}">Restore</button>`}</li>`).join('')}</ul>
  ${r.held ? `<button type="button" class="restore btn" data-run="${escapeHtml(r.runId)}">Restore all ${escapeHtml(r.held)}</button>` : ''}
</article>`).join('\n');
}

const STYLE = `
:root {
  --bg:#0f1117; --surface:#1a1d27; --surface2:#232733; --border:#2e3340;
  --text:#e2e4e9; --text-dim:#8b8f9a; --accent:#6c9cfc;
  --danger:#f87171; --warning:#fbbf24; --success:#4ade80;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  font-family: system-ui, Segoe UI, sans-serif;
  background: var(--bg); color: var(--text);
  margin: 0; padding: 22px; line-height: 1.5; font-size: 14px;
}
.dash {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; max-width: 1000px; margin: 0 auto; overflow: hidden;
}
.dhead {
  display: flex; align-items: center; gap: 14px;
  padding: 15px 20px; border-bottom: 1px solid var(--border); background: var(--surface2);
}
/* Header brand mark (W2): self-contained data-URI img — not broom emoji. */
.dhead .brand, img.brand {
  width: 52px; height: 52px; border-radius: 10px; border: 1px solid var(--border);
  display: block; flex-shrink: 0; background: #12151c; object-fit: cover;
}
.dhead h1 { margin: 0; font-size: 18px; font-weight: 700; }
.proj {
  margin-top: 4px; font-size: 12px; color: var(--text-dim);
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.projchip {
  background: rgba(108,156,252,.15); color: var(--accent);
  border: 1px solid rgba(108,156,252,.4); border-radius: 20px;
  padding: 2px 10px; font-weight: 700; font-size: 11.5px;
}
.path { font-size: 11.5px; opacity: .9; word-break: break-all; }
.git.ok { color: var(--success); }
.git.none { color: var(--warning); }
.meta { margin-left: auto; text-align: right; font-size: 11px; color: var(--text-dim); min-width: 9rem; }
.meta-badges { display: flex; flex-wrap: wrap; gap: 4px; justify-content: flex-end; margin-top: 6px; }
.verdicts {
  display: flex; gap: 10px; padding: 14px 20px;
  border-bottom: 1px solid var(--border); flex-wrap: wrap;
}
.vpill {
  flex: 1; min-width: 120px; border: 1px solid var(--border);
  border-radius: 10px; padding: 10px 13px; background: var(--surface2);
}
.vpill .n { font-size: 22px; font-weight: 800; line-height: 1; }
.vpill .l { font-size: 10.5px; color: var(--text-dim); margin-top: 3px; text-transform: uppercase; letter-spacing: .5px; }
.vpill.rm { border-color: rgba(248,113,113,.5); } .vpill.rm .n { color: var(--danger); }
.vpill.save { border-color: rgba(251,191,36,.45); } .vpill.save .n { color: var(--warning); }
.vpill.org { border-color: rgba(108,156,252,.45); } .vpill.org .n { color: var(--accent); }
.vpill.keep { border-color: rgba(74,222,128,.4); } .vpill.keep .n { color: var(--success); }
/* Executive summary — always open, one-page bullets under the pills */
.exec-summary {
  margin: 0 20px 8px; padding: 14px 16px 12px;
  border: 1px solid var(--border); border-radius: 10px;
  background: linear-gradient(180deg, #1c2030 0%, var(--surface2) 100%);
  border-left: 3px solid var(--accent);
}
.exec-summary h2 {
  margin: 0 0 6px; font-size: 14px; font-weight: 700; letter-spacing: .2px;
}
.exec-lede { margin: 0 0 10px; font-size: 13px; color: var(--text); line-height: 1.45; }
.exec-h {
  margin: 10px 0 4px; font-size: 11px; text-transform: uppercase;
  letter-spacing: .6px; color: var(--text-dim); font-weight: 700;
}
.exec-list {
  margin: 0 0 4px; padding-left: 1.15rem; font-size: 13px; line-height: 1.45;
}
.exec-list li { margin: 3px 0; }
.exec-foot { margin: 8px 0 0; }
.banners { padding: 0 20px; }
.banner { border-left: 4px solid; padding: .5rem .8rem; margin: .6rem 0; border-radius: 0 8px 8px 0; background: var(--surface2); }
.banner.red { border-color: var(--danger); }
.banner.amber { border-color: var(--warning); }
.banner.info { border-color: var(--accent); }
.banner.green { border-color: var(--success); }
.banner p { margin: .3rem 0; color: var(--text-dim); }
.not-clean { padding: 8px 20px 0; }
.not-clean h2 { font-size: 13px; margin: 0 0 6px; color: var(--warning); }
.body { padding: 8px 20px 24px; }
.sect {
  font-size: 12px; text-transform: uppercase; letter-spacing: .7px;
  color: var(--text-dim); font-weight: 700; margin: 20px 0 10px;
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.sect-block { margin-bottom: 4px; }
.body-hint { max-width: 1000px; margin: 0 auto 8px; padding: 0 4px; }
.sect-collapse {
  border: 1px solid var(--border); border-radius: 10px;
  margin-bottom: 10px; background: var(--surface2); padding: 0 12px 4px;
}
.sect-collapse > summary.sect {
  cursor: pointer; list-style: none; user-select: none;
  margin: 0; padding: 12px 4px; flex-wrap: wrap;
}
.sect-collapse > summary.sect::-webkit-details-marker { display: none; }
.sect-collapse > summary.sect::before {
  content: '▶'; display: inline-block; width: 1rem; color: var(--text-dim);
  font-size: 10px; transition: transform .12s ease;
}
.sect-collapse[open] > summary.sect::before { transform: rotate(90deg); }
.sect-collapse .sect-body { padding: 0 2px 12px; }
.sect-peek { display: block; width: 100%; margin: 4px 0 0 1rem; font-weight: 400; }
.not-clean.sect-collapse { margin: 8px 20px 0; padding: 0 12px 8px; }
.not-clean.sect-collapse summary { cursor: pointer; list-style: none; display: flex; align-items: center; gap: 8px; padding: 10px 0; }
.not-clean.sect-collapse summary h2 { margin: 0; font-size: 13px; color: var(--warning); }
.not-clean.sect-collapse summary::-webkit-details-marker { display: none; }
/* ZH-style terminal tile under verdict pills */
.term-tile {
  margin: 12px 20px 4px; border: 1px solid var(--accent); border-radius: 10px;
  background: var(--surface2); overflow: hidden;
}
.term-head {
  display: flex; align-items: center; gap: 10px; padding: 10px 13px;
  cursor: pointer; user-select: none;
}
.term-head:hover { background: #20242f; }
.term-tile.open .caret { transform: rotate(90deg); }
.term-head .caret { color: var(--text-dim); font-size: 11px; transition: transform .15s; width: 12px; }
.term-head .tt { font-weight: 600; font-size: 13px; }
.term-head .tsub { font-size: 11px; color: var(--text-dim); }
.engtoggle { margin-left: auto; display: flex; border: 1px solid var(--border); border-radius: 7px; overflow: hidden; }
.eng {
  font-size: 11px; font-weight: 600; padding: 4px 12px; border: none;
  background: var(--surface); color: var(--text-dim); cursor: pointer;
}
.eng.on { background: var(--accent); color: #0c0f15; }
.term-body { padding: 4px 13px 13px; }
.term-body .note { font-size: 12px; color: var(--text-dim); margin: 0 0 10px; }
.btn-start {
  font-size: 12px; font-weight: 600; padding: 7px 16px; border-radius: 7px;
  border: 1px solid var(--accent); background: var(--surface); color: var(--text); cursor: pointer;
}
.btn-start:hover { background: #20242f; }
.btn-start:disabled, .btn:disabled { opacity: .55; cursor: default; }
.term-body .hint { font-size: 11px; color: var(--text-dim); margin-left: 8px; }
.sect-collapse > summary.sect { display: flex; align-items: center; gap: 8px; }
.folder-sum { pointer-events: auto; }
.folder-set .acts, .card.compact .acts { margin-top: 0; }
.card.compact .acts { display: inline-flex; margin-right: 4px; }
.badge {
  font-size: 10px; padding: 2px 7px; border-radius: 10px;
  background: var(--surface2); color: var(--text-dim);
  text-transform: none; letter-spacing: 0; font-weight: 600;
}
.card {
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px; margin-bottom: 8px;
}
.card.rm { border-left: 3px solid var(--danger); }
.card.save { border-left: 3px solid var(--warning); }
.card.org { border-left: 3px solid var(--accent); }
.card.secret { border-left: 3px solid var(--danger); border-width: 1px 1px 1px 3px; }
.card.reserved { opacity: .75; border-style: dashed; }
.crow { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.fname { font-family: ui-monospace, Consolas, monospace; font-size: 13px; font-weight: 600; }
.fmeta { margin-left: auto; font-size: 11px; color: var(--text-dim); font-family: ui-monospace, Consolas, monospace; max-width: 55%; text-align: right; word-break: break-all; }
.why { font-size: 12.5px; color: var(--text-dim); margin: 7px 0 0; }
.acts { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; align-items: center; }
.btn, button {
  font-size: 11.5px; padding: 5px 12px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit;
}
.btn.approve, button.confirm-one { border-color: rgba(248,113,113,.5); color: var(--danger); }
.btn.move { border-color: rgba(108,156,252,.5); color: var(--accent); }
button[disabled] { opacity: .45; cursor: not-allowed; }
.chk { font-size: 12.5px; cursor: pointer; }
.chip {
  border: 1px solid var(--border); border-radius: 999px;
  padding: .1rem .55rem; font-size: .75rem; color: var(--text-dim);
}
.chip.amber { border-color: var(--warning); color: var(--warning); }
.chip.status-failed { border-color: var(--danger); color: var(--danger); font-weight: 700; }
.chip.status-partial { border-color: var(--warning); color: var(--warning); font-weight: 700; }
.chip.status-ok { border-color: var(--success); color: var(--success); }
.badges { margin: .25rem 0 0; display: flex; flex-wrap: wrap; gap: .3rem; }
.evidence { margin-top: 8px; font-size: 12px; }
.evidence > summary {
  cursor: pointer; color: var(--accent); font-size: 12px; user-select: none;
}
.evidence[open] > summary { margin-bottom: 6px; }
.verbatim {
  white-space: pre-wrap; word-break: break-word;
  background: #0c0f15; border: 1px solid var(--border);
  padding: .5rem; border-radius: .35rem; font-size: .8rem;
  max-height: 14rem; overflow: auto;
}
.diff { max-height: 16rem; }
.fineprint { font-size: .8rem; color: var(--text-dim); }
.no-control { font-size: .85rem; font-weight: 600; color: var(--text-dim); margin-top: 8px; }
.warn { color: var(--warning); font-weight: 700; }
.verdict { font-weight: 700; }
.folder-set {
  border: 1px solid var(--border); border-radius: 10px;
  margin-bottom: 10px; background: #161922; padding: 0 10px 8px;
}
.folder-sum {
  cursor: pointer; padding: 10px 4px; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap;
  font-weight: 600; list-style: none;
}
.folder-sum::-webkit-details-marker { display: none; }
.set-acts { margin: 0 0 8px; }
.set-preview { margin: 0 0 8px; line-height: 1.45; }
.empty-sect {
  background: var(--surface2); border: 1px dashed var(--border);
  border-radius: 9px; padding: 12px 14px; font-size: 12.5px; color: var(--text-dim);
  margin-bottom: 8px;
}
.card.compact { padding: 8px 10px; margin-bottom: 4px; }
.card.compact .crow { align-items: center; gap: 8px; }
.card.compact .fname { font-size: 12.5px; }
.card.compact .fmeta { font-size: 10.5px; max-width: 40%; }
.card.compact .evidence { margin-top: 4px; }
.flat-more { margin-top: 6px; }
.kept {
  background: var(--surface2); border: 1px dashed var(--border);
  border-radius: 9px; padding: 10px 13px; font-size: 12px; color: var(--text-dim);
}
.kept-list { margin: 8px 0 0; padding-left: 1.2rem; }
/* W3 / A2 Opt1: primary before→after tree-diff (decision chrome, not buried). */
.tree-diff, .tree-diff.primary-tree-diff {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 0;
  margin-top: 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface2);
  align-items: stretch;
}
.tree, .tree.bacol {
  flex: 1; min-width: 0;
  background: #0c0f15;
  padding: 12px 14px;
}
.tree.bacol.after { background: rgba(74, 222, 128, 0.04); }
.tree h5, .tree .bah {
  margin: 0 0 8px; font-size: 11px; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: .5px; font-weight: 700;
}
.tree .bah.a { color: var(--success); }
.tree ul, .tree-entries { margin: 0; padding-left: 0; list-style: none; font-size: 12px; }
.tnode {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12.5px; padding: 2px 0; color: var(--text-dim);
}
.tnode.moved, .tnode.moved code { color: var(--success); }
.tnode code { font-size: inherit; }
.arrow {
  color: var(--accent); font-weight: 800; align-self: center;
  display: flex; align-items: center; justify-content: center;
  padding: 0 8px; background: var(--surface); font-size: 18px;
}
.reorg-safety { margin-top: 8px; }
.hit-count { margin: 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.hit-count.safe .chip, .chip.safe-chip { border-color: var(--success); color: var(--success); }
.hit-count.unsafe .chip { border-color: var(--warning); color: var(--warning); }
/* Decision-first cards: slightly tighter meta so trees/pills stay the focus. */
.card.org .fname { color: var(--accent); }
.card.org .why { margin-top: 6px; }
.footbar {
  position: sticky; bottom: 0;
  background: linear-gradient(180deg, rgba(26,29,39,0), var(--surface2) 28%);
  padding: 16px 20px; border-top: 1px solid var(--border);
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.footbar .apply {
  background: var(--accent); color: #0c0f15; border: none;
  border-radius: 8px; padding: 9px 18px; font-weight: 700; font-size: 13px; cursor: pointer;
}
.undo { font-size: 11.5px; color: var(--text-dim); }
.foot {
  max-width: 1000px; margin: 12px auto 0; color: var(--text-dim);
  font-size: 11.5px; text-align: center;
}
.prev-runs { font-size: 12px; color: var(--text-dim); }
.prev-runs .current { color: var(--text); }
body.closed { opacity: .55; }
/* SC4 Option 1: dead-Apply after F5 — chrome disabled, re-open instruction shown */
body.dead-apply button.confirm-one,
body.dead-apply button.approve-set,
body.dead-apply #bulk-apply,
body.dead-apply input.approve {
  opacity: .45; cursor: not-allowed; pointer-events: none;
}
body.dead-apply [data-testid=dead-apply-banner] {
  border-color: var(--warning);
}
code, pre { font-family: ui-monospace, Consolas, monospace; }
.radio { margin-right: 10px; font-size: 12.5px; }
`;

export default {
  renderPanelPage, escapeHtml, embedJson, shortRelLabel, TOKEN_HEADER, isTokenLive,
  DEAD_APPLY_BANNER_TITLE, DEAD_APPLY_REOPEN_COPY, LIVE_APPLY_F5_FOOTPRINT, DEAD_APPLY_CHIP_LABEL,
};
