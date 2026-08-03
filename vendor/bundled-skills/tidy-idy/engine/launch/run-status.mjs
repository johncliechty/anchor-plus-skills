// engine/launch/run-status.mjs — the single status record for a tidy run.
//
// Written under reportDir (tripwire-exempt). Both the tool-owned status server
// and Anchor's thin caller read it so a second click can re-open the live panel
// without starting a second hygiene pass.

import fsp from 'node:fs/promises';
import path from 'node:path';

export const STATUS_FILE = 'status.json';

export const PHASE = Object.freeze({
  STARTING: 'starting',
  SCANNING: 'scanning',
  ANALYZING: 'analyzing',
  ARCHIVING: 'archiving',
  PANEL_READY: 'panel-ready',
  FAILED: 'failed',
  REFUSED: 'refused',
  DONE: 'done',
});

/**
 * Coarse progress (%) by named step. Honest about long LLM stages (analyze /
 * debate hold mid-range for a while) so the bar moves on every stage boundary
 * and the user can see the run is not stalled.
 */
export const STEP_PROGRESS = Object.freeze({
  start: 2,
  'cost-gate': 8,
  topology: 12,
  snapshot: 16,
  scan: 22,
  hygiene: 28,
  preflight: 32,
  triage: 38,
  save: 42,
  analyze: 55,
  heuristic: 62,
  debate: 78,
  compress: 85,
  reorg: 90,
  sweep: 93,
  archive: 96,
  panel: 100,
  failed: 100,
  refused: 100,
  done: 100,
});

/** Fallback when only a phase name is known (no step yet). */
export const PHASE_PROGRESS = Object.freeze({
  [PHASE.STARTING]: 2,
  [PHASE.SCANNING]: 8,
  [PHASE.ANALYZING]: 20,
  [PHASE.ARCHIVING]: 96,
  [PHASE.PANEL_READY]: 100,
  [PHASE.FAILED]: 100,
  [PHASE.REFUSED]: 100,
  [PHASE.DONE]: 100,
});

export function progressFor({ step = null, phase = null, progress = null } = {}) {
  if (Number.isFinite(progress)) {
    return Math.max(0, Math.min(100, Math.round(progress)));
  }
  if (step != null && STEP_PROGRESS[step] != null) return STEP_PROGRESS[step];
  if (phase != null && PHASE_PROGRESS[phase] != null) return PHASE_PROGRESS[phase];
  return 0;
}

export function statusPathFor(reportDir) {
  return path.join(reportDir, STATUS_FILE);
}

/**
 * @param {string} reportDir
 * @param {object} patch
 */
export async function writeStatus(reportDir, patch = {}, { fs = fsp, now = () => new Date() } = {}) {
  const file = statusPathFor(reportDir);
  await fs.mkdir(reportDir, { recursive: true });
  let prev = {};
  try {
    prev = JSON.parse(String(await fs.readFile(file, 'utf8')));
  } catch { /* first write */ }
  const stamp = now().toISOString();
  const next = {
    version: 1,
    ...prev,
    ...patch,
    updatedAt: stamp,
  };
  // New run: phase=starting with forceNewRun (or explicit startedAt) resets the
  // clock so the status tab does not show elapsed time from a prior session.
  if (patch.forceNewRun || (patch.phase === PHASE.STARTING && patch.startedAt)) {
    next.startedAt = patch.startedAt || stamp;
    delete next.forceNewRun;
    delete next.stale;
    delete next.staleReason;
  } else if (!next.startedAt) {
    next.startedAt = stamp;
  }
  // Always stamp a progress % so clients can draw a bar without re-deriving.
  // Prefer an EXPLICIT patch.progress; else re-derive from the current step/phase.
  // Never carry a sticky prior % forward (a previous 100 from panel/failed would
  // otherwise lock the bar at 100% during later mid-run steps like debate —
  // observed live 2026-07-22: phase=analyzing step=debate with progress:100).
  next.progress = progressFor({
    step: next.step,
    phase: next.phase,
    progress: patch.progress != null ? patch.progress : null,
  });
  await fs.writeFile(file, `${JSON.stringify(next, null, 2)}\n`, 'utf8');
  return next;
}

export async function readStatus(reportDir, { fs = fsp } = {}) {
  try {
    return JSON.parse(String(await fs.readFile(statusPathFor(reportDir), 'utf8')));
  } catch {
    return null;
  }
}

/** Inline SVG favicon (works on loopback without Anchor assets). */
export const FAVICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="7" fill="#1a2332"/>
  <path d="M8 22c2-6 5-10 9-12 1.2 2.5 2 5.2 2.2 8.2 2.8-.4 5 .6 6.8 2.4-3.2 1.2-6.5 1.6-9.5.6C13.2 23 10.5 23 8 22z" fill="#8ab4f8"/>
  <path d="M11 9l2.2 1.1L14.5 8l.8 2.3L17.5 11l-2.3.7L14.5 14l-1.1-2.2L11 11.2l2.2-.6z" fill="#fdd663"/>
</svg>`;

export function faviconDataUri() {
  return `data:image/svg+xml,${encodeURIComponent(FAVICON_SVG.replace(/\s+/g, ' ').trim())}`;
}

/** Human page shown while the hygiene pass runs (and until panel handoff). */
export function renderStatusPage({
  title = 'Tidy-Idy',
  pollUrl = '/api/status',
  dark = true,
  faviconUrl = null,
} = {}) {
  const bg = dark ? '#0f1115' : '#f6f7f9';
  const fg = dark ? '#e8eaed' : '#111';
  const muted = dark ? '#9aa0a6' : '#555';
  const accent = '#8ab4f8';
  const track = dark ? '#2a2f3a' : '#e0e3e8';
  const iconHref = faviconUrl || faviconDataUri();
  return `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>${escapeHtml(title)}</title>
<link rel="icon" href="${escapeHtml(iconHref)}" type="${faviconUrl ? 'image/jpeg' : 'image/svg+xml'}"/>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:${bg};color:${fg};
    margin:0;padding:2rem;line-height:1.5}
  h1{font-size:1.35rem;margin:0 0 .35rem;font-weight:600}
  .sub{color:${muted};margin:0 0 1.25rem;font-size:.95rem}
  .card{max-width:36rem;border:1px solid ${dark ? '#2a2f3a' : '#ddd'};border-radius:12px;
    padding:1.25rem 1.4rem;background:${dark ? '#161a22' : '#fff'}}
  .phase{display:inline-block;font-size:.75rem;letter-spacing:.04em;text-transform:uppercase;
    color:${accent};border:1px solid ${accent}55;border-radius:999px;padding:.15rem .6rem;margin-bottom:.75rem}
  #msg{font-size:1.05rem;margin:0 0 .75rem}
  #detail{color:${muted};font-size:.9rem;margin:0;white-space:pre-wrap}
  .bar-wrap{margin:1rem 0 .5rem}
  .bar-meta{display:flex;justify-content:space-between;align-items:baseline;font-size:.85rem;
    color:${muted};margin-bottom:.35rem}
  #pct{color:${accent};font-weight:600;font-variant-numeric:tabular-nums}
  .bar{height:.55rem;background:${track};border-radius:999px;overflow:hidden}
  .bar > i{display:block;height:100%;width:0%;background:linear-gradient(90deg,${accent},${accent}cc);
    border-radius:999px;transition:width .4s ease}
  .bar.indeterminate > i{width:35% !important;animation:ind 1.2s ease-in-out infinite}
  @keyframes ind{0%{transform:translateX(-100%)}100%{transform:translateX(320%)}}
  .spin{display:inline-block;width:.85rem;height:.85rem;border:2px solid ${accent}44;
    border-top-color:${accent};border-radius:50%;animation:s .7s linear infinite;margin-right:.45rem;vertical-align:-2px}
  @keyframes s{to{transform:rotate(360deg)}}
  a{color:${accent}}
  #alive{font-size:.8rem;color:${muted};margin-top:.65rem}
</style></head><body>
  <div class="card">
    <div class="phase" id="phase">starting</div>
    <h1>Tidy-Idy</h1>
    <p class="sub" id="project">Hygiene pass in progress</p>
    <p id="msg"><span class="spin" id="spin"></span>Starting…</p>
    <div class="bar-wrap">
      <div class="bar-meta"><span id="stepLabel">Starting</span><span id="pct">0%</span></div>
      <div class="bar" id="bar"><i id="barFill"></i></div>
    </div>
    <p id="detail"></p>
    <p id="alive">Waiting for first status…</p>
  </div>
<script>
(function () {
  var pollUrl = ${JSON.stringify(pollUrl)};
  var redirected = false;
  var baseTitle = ${JSON.stringify(title)};
  var lastUpdatedAt = null;
  var startedAt = null;
  function set(id, text) { var el = document.getElementById(id); if (el) el.textContent = text; }
  function fmtElapsed(ms) {
    if (!Number.isFinite(ms) || ms < 0) return '0s';
    var s = Math.floor(ms / 1000);
    if (s < 60) return s + 's';
    var m = Math.floor(s / 60); s = s % 60;
    if (m < 60) return m + 'm ' + s + 's';
    var h = Math.floor(m / 60); m = m % 60;
    return h + 'h ' + m + 'm';
  }
  function setProgress(pct, stepLabel) {
    var p = Math.max(0, Math.min(100, Number(pct) || 0));
    var fill = document.getElementById('barFill');
    var bar = document.getElementById('bar');
    if (fill) fill.style.width = p + '%';
    set('pct', Math.round(p) + '%');
    if (stepLabel) set('stepLabel', stepLabel);
    if (bar) {
      if (p > 0 && p < 100) bar.classList.remove('indeterminate');
      else if (p === 0) bar.classList.add('indeterminate');
      else bar.classList.remove('indeterminate');
    }
    try { document.title = Math.round(p) + '% · ' + baseTitle; } catch (e) {}
  }
  function tickAlive() {
    var now = Date.now();
    var parts = [];
    if (startedAt) parts.push('elapsed ' + fmtElapsed(now - startedAt));
    if (lastUpdatedAt) {
      var age = now - lastUpdatedAt;
      parts.push(age < 2500 ? 'status fresh' : ('last update ' + fmtElapsed(age) + ' ago'));
    }
    set('alive', parts.length ? parts.join(' · ') : 'Waiting for first status…');
  }
  function tick() {
    fetch(pollUrl, { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (s) {
      if (!s) return;
      set('phase', s.phase || 'running');
      if (s.projectName || s.rootPath) set('project', (s.projectName || '') + (s.rootPath ? ' — ' + s.rootPath : ''));
      var msg = s.message || 'Working…';
      set('msg', msg);
      var spin = document.getElementById('spin');
      if (s.startedAt) {
        var t0 = Date.parse(s.startedAt);
        if (Number.isFinite(t0)) startedAt = t0;
      }
      if (s.updatedAt) {
        var t1 = Date.parse(s.updatedAt);
        if (Number.isFinite(t1)) lastUpdatedAt = t1;
      }
      var stepLabel = s.stepLabel || s.step || s.phase || 'Working';
      setProgress(s.progress != null ? s.progress : 0, stepLabel);
      var d = [];
      if (s.step && s.stepTotal) d.push('step ' + s.stepIndex + ' / ' + s.stepTotal + ' (' + s.step + ')');
      else if (s.step) d.push('step: ' + s.step);
      if (s.findings != null) d.push(s.findings + ' finding(s) so far');
      if (s.runId) d.push('run ' + s.runId);
      if (s.error) d.push('error: ' + s.error);
      set('detail', d.join('\\n'));
      tickAlive();
      if (s.phase === 'panel-ready' && s.openUrl && !redirected) {
        redirected = true;
        if (spin) spin.style.display = 'none';
        setProgress(100, 'Panel ready');
        set('msg', 'Panel ready — opening Triage Panel…');
        window.location.replace(s.openUrl);
        return;
      }
      if (s.phase === 'panel-ready' && s.panelBaseUrl && !redirected) {
        redirected = true;
        if (spin) spin.style.display = 'none';
        setProgress(100, 'Panel ready');
        set('msg', 'Panel is live — opening…');
        window.location.replace(s.panelBaseUrl);
        return;
      }
      if (s.phase === 'failed' || s.phase === 'refused' || s.phase === 'done') {
        if (spin) spin.style.display = 'none';
        setProgress(100, s.phase);
      }
    }).catch(function () { tickAlive(); });
  }
  setProgress(0, 'Starting');
  tick();
  setInterval(tick, 1000);
  setInterval(tickAlive, 1000);
})();
</script>
</body></html>`;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
