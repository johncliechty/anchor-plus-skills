// engine/launch/panel-server.mjs — the TOOL-OWNED panel server.
//
// The launch surface belongs to tidy-idy, not to Anchor. This server is what
// "the tool owns its panel" means concretely: it binds loopback, it mints the
// Apply capability token, it decides when it dies, and it releases the project
// lock on the way out. Anchor's button opens the URL this server prints; it does
// not host, mint, or serve anything.
//
// WAVE 5 put the launch-time invariants here. WAVE 6 puts the Triage Panel and
// the hardened Apply control plane on top of them, on this same server.
//
// ─── Wave 5: the three Amendment-D refinements ───────────────────────────────
//
// 1. THE BOOTSTRAP NONCE (the token-bootstrap finding). A bare CLI has no
//    trusted channel to hand a browser a secret. So the opener is SPECIFIED, not
//    just its guarantee: the launcher opens
//        http://127.0.0.1:<port>/bootstrap/<nonce>
//    where <nonce> is single-use. The FIRST GET redeems it — the nonce is
//    invalidated, any 0600 temp file carrying it is unlinked, and the response
//    body (Cache-Control: no-store) carries the capability token. Every later GET
//    of that URL is refused with 410. The TOKEN itself is minted in server memory
//    and never appears on disk, in a URL, in a query string, in a Referer, or in
//    a log line — only the NONCE ever transits those, exactly as the amendment
//    permits, and it is worthless once redeemed.
//
// 2. SERVER LIFECYCLE (the zombie-process + permanent-lock finding). Three ways
//    this server ends, all of which release the lock:
//      (a) explicit "Close & release" from the panel;
//      (b) an idle timeout with no panel heartbeat at all;
//      (c) a heartbeat GAP — the browser tab was closed, so the beats stopped.
//    And because a SIGKILL gets none of the three, the lock itself is stale-PID
//    aware (engine/apply/lock.mjs steals a lock whose owning process is gone), so
//    a killed server leaves a reclaimable lock rather than a wedged folder.
//
// 3. GET AUDIT. Every GET here is side-effect-free and token-free, the single
//    exception being the one-time bootstrap redemption. The worst a hostile local
//    process gets by crawling this server after the panel opens is report content
//    it could have read off disk anyway — never write capability. The route table
//    is EXPORTED (`GET_ENDPOINTS`) so the audit test enumerates the real thing
//    rather than a hand-maintained copy of it.
//
// ─── Wave 6: the Apply control plane, end to end ─────────────────────────────
//
//   MINT       — a 256-bit CSPRNG token, created in memory at run completion,
//                never written to disk, to a server log, or to the archived
//                envelope.
//   TRANSPORT  — the single-use bootstrap redemption, and nothing else.
//   STORAGE    — browser memory (see engine/panel/render.mjs: no storage API is
//                referenced in the page at all).
//   REPLAY     — a PERSISTED pending→applying→done machine (engine/panel/
//                apply-state.mjs). The STATE persists for crash recovery and
//                replay-idempotence; the TOKEN never does. One Apply per run; a
//                replay returns the recorded original result and cannot
//                re-execute; a stale tab's run-ID mismatch is rejected.
//   INVALIDATION — restart-invalidation is STRUCTURAL (nothing to reload), and a
//                newer completed run for the same project supersedes and voids
//                this run's token; a fresh panel open re-mints.
//   ORIGIN     — every POST passes an Origin/Referer check (Amendment C.iii) and
//                carries the token in a HEADER, never a URL.

import http from 'node:http';
import crypto from 'node:crypto';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { applyApproved } from '../apply/executor.mjs';
import { applyReorgMove, REORG_STATUS } from '../apply/reorg.mjs';
import { restoreFromTrash, listTrash, readTrashLedger } from '../apply/trash.mjs';
import { stampFindingIds } from '../apply/identity.mjs';
import { loadPorcelain } from '../porcelain.mjs';
import { readLock } from '../apply/lock.mjs';
import { buildPanelModel } from '../panel/model.mjs';
import { renderPanelPage } from '../panel/render.mjs';
import { readApplyState, beginApply, settleApply, failApply, APPLY_STATE, APPLY_STATE_REFUSAL } from '../panel/apply-state.mjs';
import { readRunIndex } from './archive.mjs';

export const TOKEN_HEADER = 'x-tidy-idy-token';
export const BOOTSTRAP_PREFIX = '/bootstrap/';
export const LOOPBACK = '127.0.0.1';

/** No heartbeat at all within this long after open → the panel was never used. */
export const DEFAULT_IDLE_TIMEOUT_MS = 30 * 60 * 1000;
/** Beats stopped for this long → the tab is gone. */
export const DEFAULT_HEARTBEAT_GAP_MS = 90 * 1000;
/** A POST body larger than this is not a panel action. */
export const MAX_BODY_BYTES = 1024 * 1024;

export const CLOSE_REASON = Object.freeze({
  EXPLICIT: 'panel-close-and-release',
  IDLE: 'idle-timeout-no-heartbeat',
  HEARTBEAT_GAP: 'heartbeat-gap-tab-closed',
  CALLER: 'caller-close',
});

/**
 * Every GET this server answers, with the two facts the audit test asserts.
 * `token: true` would be a contract violation and there is no such row — the
 * bootstrap redemption is not a route in this table precisely because it IS the
 * exception, and it is enumerated separately.
 */
export const GET_ENDPOINTS = Object.freeze([
  { route: '/', auth: 'none', mutates: false, returns: 'a pointer to the bootstrap URL; never a credential' },
  { route: '/api/health', auth: 'none', mutates: false, returns: 'liveness + run id + apply state name' },
  { route: '/api/identity', auth: 'none', mutates: false, returns: 'folder-derived project identity' },
  { route: '/api/lock', auth: 'none', mutates: false, returns: "the lock holder's pid/purpose — the ownership token is REDACTED" },
  { route: '/api/cost-gate', auth: 'none', mutates: false, returns: 'the pre-scan cost gate record' },
  { route: '/api/archive', auth: 'none', mutates: false, returns: "this run's archive paths" },
  { route: '/api/runs', auth: 'none', mutates: false, returns: 'the newest-first run index, re-read from disk' },
  { route: '/api/envelope', auth: 'token', mutates: false, returns: 'the Wave-1 machine envelope, verbatim' },
  { route: '/api/panel', auth: 'token', mutates: false, returns: 'the token-free panel model the page renders from' },
  { route: '/api/trash', auth: 'token', mutates: false, returns: 'every run\'s Trash with per-item restore state' },
  { route: '/api/staleness', auth: 'token', mutates: false, returns: 'run age + whether HEAD moved since the snapshot' },
  { route: '/api/apply-state', auth: 'token', mutates: false, returns: 'the persisted apply state machine (never the token)' },
]);

export const POST_ENDPOINTS = Object.freeze([
  '/api/heartbeat', '/api/close', '/api/apply', '/api/restore', '/api/rescan', '/api/confirm-full-run', '/api/investigate',
]);

/**
 * Serve one run's panel.
 *
 * @param {{envelope: object, identity: object, runNumber?: number|null,
 *   archive?: object|null, runIndex?: Array|null, costGate?: object|null,
 *   rootPath?: string|null, reportDir?: string|null, git?: object|null,
 *   lock?: object|null, applyFn?: Function|null, onRescan?: Function|null,
 *   onInvestigate?: Function|null, investigator?: object|null,
 *   probeHead?: Function|null, onClose?: Function, log?: Function, port?: number,
 *   host?: string, idleTimeoutMs?: number, heartbeatGapMs?: number,
 *   nonceFile?: string|null, fs?: object, now?: Function}} opts
 */
export async function servePanel({
  envelope,
  identity,
  runNumber = null,
  archive = null,
  runIndex = null,
  costGate = null,
  rootPath = null,
  reportDir = null,
  git = null,
  lock = null,
  applyFn = null,
  onRescan = null,
  onInvestigate = null,
  investigator = null,
  probeHead = null,
  onClose = null,
  log = () => {},
  port = 0,
  host = LOOPBACK,
  idleTimeoutMs = DEFAULT_IDLE_TIMEOUT_MS,
  heartbeatGapMs = DEFAULT_HEARTBEAT_GAP_MS,
  nonceFile = null,
  fs = fsp,
  now = () => new Date(),
} = {}) {
  // ---- secrets, both in memory ------------------------------------------
  // The TOKEN never leaves this closure except inside a redeemed panel body.
  const token = crypto.randomBytes(32).toString('hex');
  // The NONCE may transit a loopback URL and a 0600 temp file. It buys exactly
  // one page load and nothing else.
  let nonce = crypto.randomBytes(24).toString('hex');
  let nonceRedeemed = false;

  const root = rootPath ? path.resolve(rootPath) : (envelope.rootPath || null);
  const store = reportDir ? path.resolve(reportDir) : (envelope.reportDir || null);

  // Wave-3 finding identity, stamped before anything renders: a tile without an
  // ID has no approval control, and an approval that does not round-trip the
  // full identity is refused by Apply. Stamping here (not in the archive) also
  // keeps run-derived IDs out of the on-disk envelope.
  stampFindingIds(envelope.findings || [], envelope.runId);

  const openedAt = now().getTime();
  let lastBeat = null;
  let closed = false;
  let closeReason = null;
  let supersededBy = null;

  const state = {
    runId: envelope.runId,
    /** Mirrors the PERSISTED machine; the persisted file is the authority. */
    apply: APPLY_STATE.PENDING,
  };
  if (store) {
    const persisted = await readApplyState({ reportDir: store, runId: envelope.runId, fs });
    state.apply = persisted.state;
  }

  const server = http.createServer(handle);

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    // Loopback ONLY. Never 0.0.0.0, never a hostname that could resolve off-box.
    server.listen(port, host, () => { server.removeListener('error', reject); resolve(); });
  });

  const boundPort = server.address().port;
  const baseUrl = `http://${host}:${boundPort}`;
  const bootstrapUrl = `${baseUrl}${BOOTSTRAP_PREFIX}${nonce}`;

  // The 0600 temp file is the alternative channel for a caller that cannot be
  // handed a URL directly (Anchor's dispatcher reads it from the job's cwd-free
  // environment). It holds the NONCE — never the token — and is unlinked the
  // moment the nonce is redeemed.
  let nonceFilePath = null;
  if (nonceFile) {
    nonceFilePath = nonceFile === true
      ? path.join(os.tmpdir(), `tidy-idy-bootstrap-${crypto.randomBytes(8).toString('hex')}.json`)
      : nonceFile;
    await fs.writeFile(nonceFilePath, `${JSON.stringify({ url: bootstrapUrl, expiresWith: 'first GET' })}\n`, { encoding: 'utf8', mode: 0o600 });
  }

  const timer = setInterval(() => {
    if (closed) return;
    const t = now().getTime();
    if (lastBeat === null) {
      if (t - openedAt >= idleTimeoutMs) void close(CLOSE_REASON.IDLE);
    } else if (t - lastBeat >= heartbeatGapMs) {
      void close(CLOSE_REASON.HEARTBEAT_GAP);
    }
  }, Math.max(50, Math.min(idleTimeoutMs, heartbeatGapMs) / 4));
  if (typeof timer.unref === 'function') timer.unref();

  async function close(reason = CLOSE_REASON.CALLER) {
    if (closed) return { closed: true, reason: closeReason };
    closed = true;
    closeReason = reason;
    clearInterval(timer);
    // Invalidate the nonce on the way out too, so a shutdown race cannot leave a
    // redeemable URL pointing at a dying server.
    nonce = null;
    await unlinkNonceFile();
    await new Promise((resolve) => server.close(resolve));
    // The lock release lives with the CALLER (it owns the lock handle), so this
    // server never has to know how locking works — it only has to guarantee that
    // every exit path runs it exactly once.
    if (onClose) await onClose({ reason });
    log(`panel server closed (${reason})`);
    return { closed: true, reason };
  }

  async function unlinkNonceFile() {
    if (!nonceFilePath) return;
    try { await fs.rm(nonceFilePath, { force: true }); } catch { /* already gone */ }
    nonceFilePath = null;
  }

  function handle(req, res) {
    const url = new URL(req.url, baseUrl);
    const route = url.pathname;

    if (req.method === 'GET' && route.startsWith(BOOTSTRAP_PREFIX)) {
      return redeemBootstrap(route.slice(BOOTSTRAP_PREFIX.length), req, res);
    }
    // A route that throws must still answer, and must answer with an error that
    // carries no capability material — never with a hung socket.
    const fail = (err) => {
      try { send(res, 500, { error: `the panel server failed to answer ${route}: ${err && err.message}` }); } catch { /* already answered */ }
    };
    if (req.method === 'GET') return void getRoute(route, req, res).catch(fail);
    if (req.method === 'POST') return void postRoute(route, req, res).catch(fail);
    return send(res, 405, { error: 'method not allowed' });
  }

  function redeemBootstrap(candidate, req, res) {
    if (nonceRedeemed || !nonce) {
      // 410 GONE, not 404: the difference between "never existed" and "already
      // used" is exactly what a second tab needs to be told.
      // SC4 Option 1: F5 / re-GET never remounts the capability token.
      // Prefer HTML for browser navigations (raw JSON looks like "{" to operators).
      const accept = String((req && req.headers && req.headers.accept) || '').toLowerCase();
      const wantHtml = !accept || accept.includes('text/html') || accept.includes('*/*');
      if (wantHtml) {
        const html = `<!doctype html><html><head><meta charset=utf-8><title>Tidy-Idy — session already opened</title>
<style>body{font-family:system-ui,sans-serif;background:#0f1115;color:#e8eaed;padding:2rem;line-height:1.5}
.card{max-width:36rem;border:1px solid #2a2f3a;border-radius:12px;padding:1.25rem 1.4rem;background:#161a22}
h1{font-size:1.2rem;margin:0 0 .5rem}p{color:#9aa0a6;margin:0 0 .75rem}code{color:#8ab4f8}</style></head>
<body><div class=card><h1>This panel link was already used</h1>
<p>The bootstrap URL is single-use (so a refresh cannot re-enable Apply). Close this tab and re-open the panel <b>from where you launched it</b> — the <b>Tidy-Idy</b> button on the project in Anchor, or a fresh <code>tidy-idy</code> CLI run — either mints a fresh single-use open link for the live panel.</p>
<p><code>bootstrap nonce already redeemed</code></p></div></body></html>`;
        res.writeHead(410, {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'no-store',
        });
        res.end(html);
        return undefined;
      }
      return send(res, 410, {
        error: 'bootstrap nonce already redeemed',
        detail: 'the panel bootstrap URL is single-use — this reload cannot re-enable Apply. '
          + 'Re-open the panel from the tidy-idy CLI (`tidy-idy <folder>`) or the Anchor Tidy-Idy button to mint a fresh session',
        sc4Option: 1,
        apply: 'disabled',
      }, { 'Cache-Control': 'no-store' });
    }
    if (!timingSafeEqual(candidate, nonce)) {
      return send(res, 404, { error: 'unknown bootstrap nonce' }, { 'Cache-Control': 'no-store' });
    }
    nonceRedeemed = true;
    nonce = null;
    void unlinkNonceFile();
    lastBeat = now().getTime(); // the panel is open as of this moment

    // Build the model BEFORE writing the head, so a modelling failure is a 500
    // rather than a half-written page carrying a token.
    let page;
    try {
      page = buildModel()
        .then((model) => renderPanelPage({ token, model, baseUrl }));
    } catch (err) {
      return send(res, 500, { error: `the panel could not be rendered: ${err.message}` });
    }
    return void page.then((html) => {
      res.writeHead(200, {
        'Content-Type': 'text/html; charset=utf-8',
        // The one response in this server that carries the token. It must never
        // be stored by anything.
        'Cache-Control': 'no-store, no-cache, must-revalidate, private',
        Pragma: 'no-cache',
        'Referrer-Policy': 'no-referrer',
      });
      res.end(html);
      // NOTE the absence of any log() call carrying the token. Deliberate.
      log('bootstrap nonce redeemed — panel opened');
    }).catch((err) => send(res, 500, { error: `the panel could not be rendered: ${err.message}` }));
  }

  // ---- reads, all of them side-effect-free ------------------------------

  async function readLockState() {
    if (!store) return { held: false, note: 'no report directory — lock state unknown' };
    const holder = await readLock(store, { fs });
    if (!holder) return { held: false };
    // The lock record's OWNERSHIP token is redacted: it is not the capability
    // token, but handing it out would let any local process release our lock.
    return { held: true, pid: holder.pid ?? null, purpose: holder.purpose || null, jobId: holder.jobId || null, acquiredAt: holder.acquiredAt || null };
  }

  async function readStaleness() {
    const snapshotHead = (envelope.snapshot && envelope.snapshot.head)
      || (envelope.git && envelope.git.head)
      || null;
    if (!snapshotHead) {
      return { checked: false, headMoved: false, snapshotHead: null, currentHead: null, note: 'no repository (or no HEAD at scan time) — there is no HEAD for this run to be stale against' };
    }
    const probe = probeHead || defaultProbeHead;
    let currentHead = null;
    try {
      currentHead = await probe();
    } catch {
      currentHead = null;
    }
    if (!currentHead) {
      return { checked: false, headMoved: false, snapshotHead, currentHead: null, note: 'the current HEAD could not be read — staleness is UNKNOWN, not false' };
    }
    return {
      checked: true,
      snapshotHead,
      currentHead,
      headMoved: currentHead !== snapshotHead,
    };
  }

  async function defaultProbeHead() {
    if (!git || typeof git.run !== 'function') return null;
    const r = await git.run(['rev-parse', 'HEAD']);
    return String(r.stdout || '').trim() || null;
  }

  async function readTrashView() {
    if (!store) return { runs: [], totalHeld: 0 };
    const { runs, base, ttlMs } = await listTrash({ reportDir: store, fs, now });
    const detailed = [];
    for (const r of runs) {
      const { entries } = await readTrashLedger({ reportDir: store, runId: r.runId, fs });
      detailed.push({
        ...r,
        items: [...entries.values()]
          .filter((e) => e.moveState === 'done')
          .map((e) => ({ path: e.path, hash: e.hash || null, size: e.size ?? null, restored: e.restoreState === 'done' }))
          .sort((a, b) => a.path.localeCompare(b.path)),
      });
    }
    return {
      base,
      ttlMs,
      runs: detailed,
      totalHeld: detailed.reduce((n, r) => n + r.held, 0),
      note: 'these files were MOVED here, never deleted; restore is the Wave-4 journaled, no-clobber, idempotent move-back',
    };
  }

  /**
   * Has a NEWER completed run for this project superseded this one? A newer run
   * voids this run's token, because approving last run's verdicts against a tree
   * that has since been re-scanned is exactly the stale-tab failure the identity
   * contract exists to prevent.
   */
  async function checkSuperseded() {
    if (supersededBy) return supersededBy;
    if (!store || !Number.isInteger(runNumber)) return null;
    const index = await readRunIndex(store, { fs });
    const newer = index.find((r) => Number(r.runNumber) > Number(runNumber) && samePath(r, identity));
    if (newer) supersededBy = { runNumber: newer.runNumber, runId: newer.runId, endedAt: newer.endedAt || null };
    return supersededBy;
  }

  async function buildModel() {
    const [applyState, staleness, trash, lockState, superseded, index] = await Promise.all([
      store ? readApplyState({ reportDir: store, runId: envelope.runId, fs }) : Promise.resolve(null),
      readStaleness(),
      readTrashView(),
      readLockState(),
      checkSuperseded(),
      store ? readRunIndex(store, { fs }) : Promise.resolve(runIndex || []),
    ]);
    if (applyState) state.apply = applyState.state;
    return buildPanelModel({
      envelope,
      identity,
      runNumber,
      archive,
      runIndex: (index && index.length ? index : runIndex) || [],
      costGate,
      trash,
      applyState,
      staleness,
      lock: lockState,
      supersededBy: superseded,
      investigator,
      // The model is a SNAPSHOT of this run as of when the panel opened, so two
      // reads of it are byte-identical: `generatedAt` and the run's age are
      // pinned to the open instant rather than the wall clock, which keeps the
      // GET-audit invariant ("a read never mutates state") honest — a live clock
      // would make an untouched model appear to change between two crawls.
      now: () => new Date(openedAt),
    });
  }

  async function getRoute(route, req, res) {
    // Every branch below is a pure read. Nothing here mutates state, and nothing
    // here can emit token bytes — asserted by the GET-audit test.
    switch (route) {
      case '/':
        return send(res, 200, {
          tool: 'tidy-idy',
          project: { name: identity.name, path: identity.path },
          runId: envelope.runId,
          note: 'open the panel through the single-use bootstrap URL the launcher printed; this endpoint never returns a credential',
        });
      case '/api/health':
        return send(res, 200, { ok: true, runId: envelope.runId, closed, applyState: state.apply });
      case '/api/identity':
        return send(res, 200, identity);
      case '/api/lock':
        return send(res, 200, await readLockState());
      case '/api/cost-gate':
        return send(res, 200, costGate || envelope.costGate || null);
      case '/api/archive':
        return send(res, 200, archive || null);
      case '/api/runs':
        return send(res, 200, { runs: store ? await readRunIndex(store, { fs }) : (runIndex || []) });
      case '/api/envelope':
        return requireToken(req, res, () => send(res, 200, envelope));
      case '/api/panel':
        return requireToken(req, res, async () => send(res, 200, await buildModel()));
      case '/api/trash':
        return requireToken(req, res, async () => send(res, 200, await readTrashView()));
      case '/api/staleness':
        return requireToken(req, res, async () => send(res, 200, await readStaleness()));
      case '/api/apply-state':
        return requireToken(req, res, async () => send(res, 200, store
          ? await readApplyState({ reportDir: store, runId: envelope.runId, fs })
          : { state: state.apply, note: 'no report directory — this run has no persisted apply state' }));
      default:
        return send(res, 404, { error: 'no such endpoint' });
    }
  }

  async function postRoute(route, req, res) {
    const originError = checkOrigin(req, baseUrl);
    if (originError) return send(res, 403, { error: originError });
    return requireToken(req, res, async () => {
      let body = {};
      if (route !== '/api/heartbeat' && route !== '/api/close') {
        try {
          body = await readBody(req);
        } catch (err) {
          return send(res, 413, { error: err.message });
        }
      }
      switch (route) {
        case '/api/heartbeat':
          lastBeat = now().getTime();
          return send(res, 200, { ok: true, at: new Date(lastBeat).toISOString() });
        case '/api/close': {
          send(res, 200, { ok: true, closing: CLOSE_REASON.EXPLICIT });
          await close(CLOSE_REASON.EXPLICIT);
          return undefined;
        }
        case '/api/apply':
          return handleApply(body, res);
        case '/api/restore':
          return handleRestore(body, res);
        case '/api/rescan':
          return handleRescan(body, res, { costGateEnabled: true });
        case '/api/confirm-full-run':
          return handleRescan(body, res, { costGateEnabled: false });
        case '/api/investigate':
          return handleInvestigate(body, res);
        case '/api/reissue-bootstrap':
          // Host-only (Anchor reverse-proxy is loopback): mint a NEW single-use
          // bootstrap URL so a second click / Tailscale re-open works after the
          // first nonce was redeemed. Does NOT re-enable a reloaded tab's token
          // (SC4 Option 1) — it is a fresh open of the same live panel process.
          return handleReissueBootstrap(req, res);
        default:
          return send(res, 404, { error: 'no such endpoint' });
      }
    });
  }

  function isLoopbackRequest(req) {
    const ra = String(req.socket && (req.socket.remoteAddress || '') || '');
    return ra === '127.0.0.1' || ra === '::1' || ra === '::ffff:127.0.0.1' || ra.endsWith('127.0.0.1');
  }

  function handleReissueBootstrap(req, res) {
    if (!isLoopbackRequest(req)) {
      return send(res, 403, {
        error: 'reissue-bootstrap is host-local only',
        detail: 'only Anchor on this machine may mint a new bootstrap URL',
      });
    }
    if (closed) {
      return send(res, 410, {
        error: 'panel closed',
        detail: 'start a new tidy-idy run for a fresh panel',
      });
    }
    // Mint a fresh single-use nonce (previous one is already spent or replaced).
    nonce = crypto.randomBytes(24).toString('hex');
    nonceRedeemed = false;
    lastBeat = now().getTime();
    const bootstrapUrl = `${baseUrl}${BOOTSTRAP_PREFIX}${nonce}`;
    // Refresh the 0600 nonce file if the launcher uses one.
    if (nonceFilePath) {
      void fs.writeFile(
        nonceFilePath,
        `${JSON.stringify({ url: bootstrapUrl, expiresWith: 'first GET' })}\n`,
        { encoding: 'utf8', mode: 0o600 },
      ).catch(() => {});
    }
    log('bootstrap nonce reissued for host re-open');
    return send(res, 200, {
      ok: true,
      bootstrapUrl,
      openUrl: bootstrapUrl,
      panelBaseUrl: baseUrl,
      runId: envelope.runId,
    }, { 'Cache-Control': 'no-store' });
  }

  /** A stale tab is a tab describing a DIFFERENT run. It is rejected, not fixed. */
  function checkRunId(body) {
    if (!body || typeof body.runId !== 'string') {
      return `every mutating POST must name the run it believes it is acting on — this one did not`;
    }
    if (body.runId !== envelope.runId) {
      return `this panel serves run ${envelope.runId}, but the request names run ${body.runId} — a stale tab cannot apply one run's verdicts to another run's tree`;
    }
    return null;
  }

  async function handleApply(body, res) {
    const idError = checkRunId(body);
    if (idError) return send(res, 409, { error: idError, code: APPLY_STATE_REFUSAL.STALE_RUN });

    const superseded = await checkSuperseded();
    if (superseded) {
      return send(res, 409, {
        code: APPLY_STATE_REFUSAL.SUPERSEDED,
        supersededBy: superseded,
        error: `run ${runNumber} has been superseded by a newer completed run (run ${superseded.runNumber}) for this project — this run's token is void; open the newest run's panel, which re-mints`,
      });
    }

    if (!store) return send(res, 500, { error: 'this panel was served without a report directory, so it has no place to persist the Apply state machine and refuses to apply' });

    const begin = await beginApply({ reportDir: store, runId: envelope.runId, fs, now });
    if (begin.replay) {
      // THE ONLY thing a replay can produce is the recorded result. There is no
      // path from here into the executor.
      state.apply = begin.state.state;
      return send(res, 200, { ok: true, replay: true, runId: envelope.runId, state: begin.state.state, result: begin.result, message: begin.message });
    }
    if (!begin.ok) {
      state.apply = begin.state.state;
      return send(res, 409, { code: begin.code, error: begin.message, state: begin.state.state });
    }

    state.apply = APPLY_STATE.APPLYING;
    const approvals = Array.isArray(body.approvals) ? body.approvals : [];
    try {
      const fn = applyFn || defaultApplyFn;
      const result = await fn({ approvals, runId: envelope.runId });
      const settled = await settleApply({ reportDir: store, runId: envelope.runId, result, fs, now });
      state.apply = settled.state;
      // A fresh Apply carries `replay: false` so a caller can tell it apart from
      // the recorded-result replay above. The resumption of an interrupted
      // PARTIAL is neither: it re-executes, so it omits `replay` entirely rather
      // than claim to be a first-and-only Apply.
      const payload = { ok: true, runId: envelope.runId, state: settled.state, result };
      if (!begin.retryOfPartial) payload.replay = false;
      return send(res, 200, payload);
    } catch (err) {
      const failed = await failApply({ reportDir: store, runId: envelope.runId, error: err, fs, now });
      state.apply = failed.state;
      return send(res, 500, { ok: false, error: `Apply threw: ${err.message}`, state: failed.state });
    }
  }

  async function defaultApplyFn({ approvals }) {
    const findings = envelope.findings || [];
    stampFindingIds(findings, envelope.runId);
    const byId = new Map(findings.map((f) => [f.id, f]));

    // Reorg moves are executed by their OWN class-partitioned two-phase executor
    // (engine/apply/reorg.mjs), never folded into the removals/saves single
    // commit: a mixed-directory move has a tracked half (a git commit) AND an fs
    // half (a journaled move-set), which is a different transaction than one
    // all-or-nothing commit. Split the approvals so the non-reorg path stays
    // byte-identical to the frozen Wave-6 behaviour when there are no reorg
    // approvals at all.
    const reorgApprovals = approvals.filter((a) => {
      const f = a && a.id ? byId.get(a.id) : null;
      return (f && f.action === 'reorg') || (a && a.action === 'reorg');
    });
    const otherApprovals = approvals.filter((a) => !reorgApprovals.includes(a));

    if (!reorgApprovals.length) {
      return applyApproved({
        rootPath: root,
        git,
        runId: envelope.runId,
        snapshot: envelope.snapshot,
        findings,
        approvals: otherApprovals,
        reportDir: store,
        ruleset: envelope.ruleset || null,
        jobId: envelope.runId,
        // The panel's Apply runs INSIDE the run lock the launcher already holds
        // for the panel's lifetime. Without this the executor would contend with
        // its own launcher and refuse every Apply with LOCK_HELD.
        lock,
        fs,
        now,
      });
    }

    // Mixed request: run the non-reorg half through the single-commit executor,
    // then each reorg move through its class-partitioned executor. Both share the
    // borrowed run lock and the one Apply the control plane permits per run.
    let base = null;
    if (otherApprovals.length) {
      base = await applyApproved({
        rootPath: root, git, runId: envelope.runId, snapshot: envelope.snapshot,
        findings, approvals: otherApprovals, reportDir: store,
        ruleset: envelope.ruleset || null, jobId: envelope.runId, lock, fs, now,
      });
    }

    const porcelain = git ? await loadPorcelain({ git, state: {} }) : null;
    const reorgResults = [];
    for (const a of reorgApprovals) {
      const finding = a && a.id ? byId.get(a.id) : null;
      if (!finding) {
        reorgResults.push({ status: REORG_STATUS.REFUSED, code: 'UNMATCHED_FINDING_ID', approval: a });
        continue;
      }
      const r = await applyReorgMove({
        rootPath: root, git, runId: envelope.runId, reportDir: store,
        finding, snapshot: envelope.snapshot, porcelain,
        override: a && a.override === true, lock, fs, now,
      });
      reorgResults.push(r);
    }

    // Merge into one Apply result the control plane can settle. The run counts as
    // applied only if the non-reorg half (if any) applied and every reorg move
    // reached a terminal applied state; any refusal/rollback makes it partial.
    const reorgApplied = reorgResults.every((r) => r.status === REORG_STATUS.APPLIED || r.status === REORG_STATUS.NO_OP);
    const baseOk = !base || base.status === 'applied' || base.status === 'no-op';
    const status = baseOk && reorgApplied ? 'applied' : 'partial';
    return {
      status,
      runId: envelope.runId,
      base,
      reorg: reorgResults,
      commit: base ? base.commit : (reorgResults.find((r) => r.commit) || {}).commit || null,
      message: `reorg apply: ${reorgResults.map((r) => r.message || r.status).join(' | ')}${base ? ` || removals/saves: ${base.message || base.status}` : ''}`,
    };
  }

  async function handleRestore(body, res) {
    const idError = checkRunId(body);
    if (idError) return send(res, 409, { error: idError, code: APPLY_STATE_REFUSAL.STALE_RUN });
    if (!store) return send(res, 500, { error: 'this panel was served without a report directory and cannot reach the Trash' });

    // The Trash run id is NOT this run's id: the panel restores items that an
    // EARLIER run moved. It defaults to this run only when nothing else is named.
    const trashRunId = typeof body.trashRunId === 'string' && body.trashRunId ? body.trashRunId : envelope.runId;
    const paths = Array.isArray(body.paths) && body.paths.length ? body.paths.map(String) : null;
    const result = await restoreFromTrash({ rootPath: root, reportDir: store, runId: trashRunId, paths, fs, now });
    return send(res, result.status === 'refused' ? 409 : 200, { ok: result.status !== 'refused', trashRunId, result });
  }

  async function handleRescan(body, res, { costGateEnabled }) {
    const idError = checkRunId(body);
    if (idError) return send(res, 409, { error: idError, code: APPLY_STATE_REFUSAL.STALE_RUN });
    if (!onRescan) {
      return send(res, 501, {
        ok: false,
        performed: false,
        costGateEnabled,
        message: `this panel's launcher supplied no re-scan hook — run \`tidy-idy ${root}\`${costGateEnabled ? '' : ' --no-cost-gate'} yourself to produce a fresh run`,
      });
    }
    const outcome = await onRescan({ costGateEnabled, runId: envelope.runId, rootPath: root });
    return send(res, 202, { ok: true, performed: true, costGateEnabled, ...outcome });
  }

  /**
   * Open the seeded investigator terminal for THIS run. Read-only with respect to
   * the repository: it opens a terminal in the project cwd and (re)writes the
   * regenerable briefing — it never mutates the working tree, the index, or git,
   * so it carries no Apply-state or staleness gate, only the run-ID check that
   * keeps a stale tab from launching against a different run.
   */
  async function handleInvestigate(body, res) {
    const idError = checkRunId(body);
    if (idError) return send(res, 409, { error: idError, code: APPLY_STATE_REFUSAL.STALE_RUN });
    if (!onInvestigate) {
      return send(res, 501, {
        ok: false,
        performed: false,
        message: `this panel's launcher supplied no investigator hook — open a terminal in ${root} yourself and read this run's reports/tidy briefing`,
      });
    }
    const engine = typeof body.engine === 'string' && body.engine ? body.engine : null;
    const outcome = await onInvestigate({ engine, runId: envelope.runId, rootPath: root });
    return send(res, 202, { ok: true, performed: true, ...outcome });
  }

  function requireToken(req, res, fn) {
    const presented = req.headers[TOKEN_HEADER];
    if (!presented || !timingSafeEqual(String(presented), token)) {
      return send(res, 401, {
        error: 'missing or invalid capability token',
        detail: `present the per-run token in the ${TOKEN_HEADER} header — it is never accepted in a URL or query string`,
      });
    }
    return fn();
  }

  async function readBody(req) {
    const chunks = [];
    let size = 0;
    for await (const chunk of req) {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) throw new Error(`request body exceeds ${MAX_BODY_BYTES} bytes — a panel action is never this large`);
      chunks.push(chunk);
    }
    if (!chunks.length) return {};
    try {
      return JSON.parse(Buffer.concat(chunks).toString('utf8')) || {};
    } catch {
      return {};
    }
  }

  return {
    url: baseUrl,
    port: boundPort,
    host,
    bootstrapUrl,
    /** The 0600 file carrying the NONCE (never the token), or null. */
    nonceFile: nonceFilePath,
    runId: envelope.runId,
    runNumber,
    close,
    get closed() { return closed; },
    get closeReason() { return closeReason; },
    /** In-memory only, for tests and for the launcher's own POSTs. Never persisted. */
    get token() { return token; },
    get nonceRedeemed() { return nonceRedeemed; },
    get lastHeartbeatAt() { return lastBeat; },
    /** Void this run's token because a newer run for the project completed. */
    supersede(by) { supersededBy = by || { runNumber: null, runId: null }; return supersededBy; },
    get supersededBy() { return supersededBy; },
    /** Test/host handle onto the panel model. Token-free by construction. */
    model: buildModel,
    state,
  };
}

function samePath(record, identity) {
  const a = record && record.project && record.project.path;
  if (!a || !identity) return true; // an index row without a project path is this project's
  return path.resolve(a) === path.resolve(identity.path);
}

/** Reject a cross-origin POST (Amendment C.iii). Same-origin or no Origin (curl). */
export function checkOrigin(req, baseUrl) {
  const origin = req.headers.origin;
  const referer = req.headers.referer;
  const expected = new URL(baseUrl).origin;
  if (origin && origin !== expected) return `cross-origin POST refused (origin ${origin} != ${expected})`;
  if (referer) {
    try {
      if (new URL(referer).origin !== expected) return `cross-origin POST refused (referer origin != ${expected})`;
    } catch {
      return 'malformed Referer on a POST';
    }
  }
  return null;
}

function timingSafeEqual(a, b) {
  const ba = Buffer.from(String(a || ''), 'utf8');
  const bb = Buffer.from(String(b || ''), 'utf8');
  if (ba.length !== bb.length) return false;
  return crypto.timingSafeEqual(ba, bb);
}

function send(res, code, body, headers = {}) {
  const text = `${JSON.stringify(body, null, 2)}\n`;
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...headers });
  res.end(text);
}

/**
 * The redeemed panel page, as a pure function — kept exported under its Wave-5
 * name because that is the name the launch surface and its tests know it by.
 * WHERE the token lives has not changed: embedded in this page, held in browser
 * memory, and never written to localStorage, sessionStorage, or a cookie.
 */
export function renderBootstrapPage({ token, model, identity, envelope, runNumber, baseUrl }) {
  const m = model || buildPanelModel({ envelope, identity, runNumber });
  return renderPanelPage({ token, model: m, baseUrl });
}

export default {
  servePanel, checkOrigin, renderBootstrapPage,
  TOKEN_HEADER, CLOSE_REASON, BOOTSTRAP_PREFIX, LOOPBACK, GET_ENDPOINTS, POST_ENDPOINTS,
};
