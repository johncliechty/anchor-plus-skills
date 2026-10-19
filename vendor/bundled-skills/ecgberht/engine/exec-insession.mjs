/**
 * Wave 20 — In-session executor (IMPLEMENTATION #2; NS criteria 14, 15).
 *
 * A confirmed commission executes IN THE CALLING SESSION with no Anchor
 * present, through the SAME skill-owned handback contract (Wave 4) and the
 * Wave-13 host-agnostic status-ingestion seam as PRODUCER #2.
 *
 * Deliberately SMALLER than job_runner: no daemon (canary law — no
 * createServer/listen loop), supervision lives while the calling session
 * lives, and truth is recovered at NEXT INVOCATION by reconcile (Wave-4
 * boot-reconcile relocated from service boot to verb time / openProjectPipeline).
 *
 * ENGINE LAW: nothing under engine/ may import child_process or call spawn*().
 * Process creation + tree-kill arrive via injected host hooks (gate / CLI /
 * tests). Identity uses (pid, proc_create_time) never pid alone; process.kill
 * signal-0 is allowed (same as g4-verdict / process-liveness).
 *
 * Reached ONLY through the Wave-11 executor seam `executeCommission` when
 * registered via `installInSessionExecutor` / `setInSessionExecutor`.
 *
 * Stdlib only. No host-absolute user-home paths in shipped strings.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import crypto from 'node:crypto';

import {
  writeFileAtomicSync,
  withFileLock,
  writeJsonIdempotentSync,
  LOCK_TIMEOUT_MS,
} from './durable-write.mjs';
import {
  writeHandbackPair,
  isIngestable,
  readIngestableHandback,
  handbackJsonPath,
  CONTRACT_VERSION,
  EXEC_FAILURE_STATES,
} from './handback-contract.mjs';
import {
  evaluateG4Evidence,
  collectEvidenceFromWorktree,
  cmdlineNamesTrioEntry,
  observeProcessIdentity,
  sanitizeEvidenceForShip,
} from './g4-verdict.mjs';
import {
  LEASE_TTL_MS,
  LEASE_RENEW_INTERVAL_MS,
  RUN_LIVENESS,
  evaluateLeaseState,
  defaultLeaseMonoMs,
} from './lease-law.mjs';
import {
  ingestStatusEvents,
  makeFixtureProducer,
  STATUS_PRODUCERS,
  STATUS_INGESTION_SEAM,
} from './status-ingestion.mjs';
import { processIdentityKey } from './process-liveness.mjs';
import { authorize } from './authorize.mjs';
import { setInSessionExecutor } from './commission-proposal.mjs';
import { ingestHandback } from './handback-ingest.mjs';
import { validateReceipt } from './receipt-validate.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(ENGINE_DIR, '..');

// ── Bounds / store ─────────────────────────────────────────────────────────

/** DEGRADED-mode parity with Anchor's one-run-at-a-time (T-BND-20). */
export const INSESSION_MAX_CONCURRENT_RUNS = 1;

/** Durable-store map S14. */
export const INSESSION_STORE = 'S14';
export const INSESSION_ATOMIC_WRITE = 'writeFileAtomicSync';
export const INSESSION_LOCK_HELPER = 'withFileLock';

export const INSESSION_LEDGER_SCHEMA = 'ecgberht-insession-ledger-v0';
export const INSESSION_LEDGER_REL = path.join(
  '.ecgberht',
  'insession-runs',
  'ledger.json',
);

/** S8 verdict / evidence (gate + unit writers only). */
export const EXEC2_VERDICT_REL = path.join('artifacts', 'exec2-verdict.json');
export const EXEC2_EVIDENCE_REL = path.join('artifacts', 'exec2-evidence.json');

/** Producer #2 id on the Wave-13 status-ingestion seam. */
export const INSESSION_PRODUCER_ID = STATUS_PRODUCERS.INSESSION;

/** Forbidden credential keys in child env/argv (D-1 / no-token law). */
export const FORBIDDEN_CHILD_ENV = Object.freeze([
  'ANCHOR_TOKEN',
  'ANCHOR_CAPABILITY',
  'ANCHOR_CAPABILITY_TOKEN',
  'ECGBERHT_CAPABILITY',
  'ECGBERHT_TOKEN',
]);

// ── Failure-state table (plan Wave 20) ─────────────────────────────────────

export const EXEC2_CODE = Object.freeze({
  EXEC2_SUBSTRATE_MISSING: 'EXEC2_SUBSTRATE_MISSING',
  EXEC_REFUSED_UNCONFIRMED: 'EXEC_REFUSED_UNCONFIRMED',
  EXEC2_BUSY: 'EXEC2_BUSY',
  EXEC_RUN_DIED: 'EXEC_RUN_DIED',
  EXEC_HANDBACK_MISSING: 'EXEC_HANDBACK_MISSING',
  EXEC2_KILL_UNCONFIRMED: 'EXEC2_KILL_UNCONFIRMED',
  EXEC2_RUN_ADOPTED: 'EXEC2_RUN_ADOPTED',
  EXEC_AUTH_REFUSED: 'EXEC_AUTH_REFUSED',
  EXEC2_LEDGER_UNREADABLE: 'EXEC2_LEDGER_UNREADABLE',
  EXEC_NO_RUNS: 'EXEC_NO_RUNS',
  EXEC_LIVENESS_UNKNOWN: 'EXEC_LIVENESS_UNKNOWN',
});

export const EXEC2_TEXT = Object.freeze({
  [EXEC2_CODE.EXEC2_SUBSTRATE_MISSING]:
    "The commissioned skill's CLI is not on this box — commission cannot launch here.",
  [EXEC2_CODE.EXEC_REFUSED_UNCONFIRMED]:
    'Commission not confirmed — nothing launched, nothing spent.',
  [EXEC2_CODE.EXEC2_BUSY]:
    'One in-session run at a time — commission intact; retry when the current run ends.',
  [EXEC2_CODE.EXEC_RUN_DIED]:
    'Run <id> died (process identity no longer live) — named dead, not absorbed.',
  [EXEC2_CODE.EXEC_HANDBACK_MISSING]:
    'Run <id> ended with no handback file — named missing, not absorbed.',
  [EXEC2_CODE.EXEC2_KILL_UNCONFIRMED]:
    'Kill issued but death not confirmed — run shown as unknown, not as killed.',
  [EXEC2_CODE.EXEC2_RUN_ADOPTED]:
    'Run <id> outlived its session — handback adopted from its durable file.',
  [EXEC2_CODE.EXEC_AUTH_REFUSED]:
    'Launch refused — the injected authorizer said no; nothing started.',
  [EXEC2_CODE.EXEC2_LEDGER_UNREADABLE]:
    'In-session run ledger unreadable — launch refused rather than launched blind.',
  [EXEC2_CODE.EXEC_NO_RUNS]: 'No commissioned runs.',
  [EXEC2_CODE.EXEC_LIVENESS_UNKNOWN]:
    'Run liveness UNKNOWN — shown as unknown, not running.',
});

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function exec2Failure(code, extra = {}) {
  let text = EXEC2_TEXT[code] ?? EXEC2_TEXT[EXEC2_CODE.EXEC_LIVENESS_UNKNOWN];
  if (extra.id != null && text.includes('<id>')) {
    text = text.replace(/<id>/g, String(extra.id));
  }
  if (extra.run_id != null && text.includes('<id>')) {
    text = text.replace(/<id>/g, String(extra.run_id));
  }
  return {
    ok: false,
    code,
    status_code: code,
    text,
    message: text,
    user_text: text,
    executor: 'insession',
    store: INSESSION_STORE,
    ...extra,
  };
}

/**
 * Full failure-state table (honest unknown ≠ empty).
 * @returns {ReadonlyArray<{state: string, status_code: string, user_text: string}>}
 */
export function exec2FailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'dependency-missing (commissioned CLI absent)',
      status_code: EXEC2_CODE.EXEC2_SUBSTRATE_MISSING,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC2_SUBSTRATE_MISSING],
    }),
    Object.freeze({
      state: 'launch-refused (unconfirmed)',
      status_code: EXEC2_CODE.EXEC_REFUSED_UNCONFIRMED,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC_REFUSED_UNCONFIRMED],
    }),
    Object.freeze({
      state: 'insession-busy (bound reached)',
      status_code: EXEC2_CODE.EXEC2_BUSY,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC2_BUSY],
    }),
    Object.freeze({
      state: 'launched-then-died',
      status_code: EXEC2_CODE.EXEC_RUN_DIED,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC_RUN_DIED],
    }),
    Object.freeze({
      state: 'no-handback (marker absent past TTL)',
      status_code: EXEC2_CODE.EXEC_HANDBACK_MISSING,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC_HANDBACK_MISSING],
    }),
    Object.freeze({
      state: 'kill-unconfirmed',
      status_code: EXEC2_CODE.EXEC2_KILL_UNCONFIRMED,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC2_KILL_UNCONFIRMED],
    }),
    Object.freeze({
      state: 'orphan-adopted at next invocation',
      status_code: EXEC2_CODE.EXEC2_RUN_ADOPTED,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC2_RUN_ADOPTED],
    }),
    Object.freeze({
      state: 'auth-refused at launch',
      status_code: EXEC2_CODE.EXEC_AUTH_REFUSED,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC_AUTH_REFUSED],
    }),
    Object.freeze({
      state: 'backing-store-unreadable',
      status_code: EXEC2_CODE.EXEC2_LEDGER_UNREADABLE,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC2_LEDGER_UNREADABLE],
    }),
    Object.freeze({
      state: 'empty-but-valid',
      status_code: EXEC2_CODE.EXEC_NO_RUNS,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC_NO_RUNS],
    }),
    Object.freeze({
      state: 'unknown (liveness undeterminable)',
      status_code: EXEC2_CODE.EXEC_LIVENESS_UNKNOWN,
      user_text: EXEC2_TEXT[EXEC2_CODE.EXEC_LIVENESS_UNKNOWN],
    }),
  ]);
}

// Wave-4 EXEC_FAILURE_STATES subset still names the shared codes.
export { EXEC_FAILURE_STATES };

// ── Process hooks (host injects spawn capability — engine stays process-free) ─

/**
 * @typedef {object} InSessionProcessHooks
 * @property {(args: {
 *   cmdline: string[],
 *   cwd: string,
 *   env: NodeJS.ProcessEnv,
 *   worktree: string,
 *   run_id: string,
 * }) => {
 *   pid: number,
 *   proc_create_time: number,
 *   wait?: () => Promise<{ code: number|null }>| { code: number|null },
 *   child?: object|null,
 * }} launch
 * @property {(args: {
 *   pid: number,
 *   proc_create_time?: number|null,
 *   run_id?: string,
 * }) => { ok: boolean, method?: string, detail?: string }} [treeKill]
 * @property {(pid: number) => number|null} [observeCreateTime]
 */

/** @type {InSessionProcessHooks|null} */
let _processHooks = null;

/**
 * Install host process hooks (launch + optional treeKill / observeCreateTime).
 * Pass null to clear.
 * @param {InSessionProcessHooks|null} hooks
 */
export function setInSessionProcessHooks(hooks) {
  _processHooks =
    hooks && typeof hooks === 'object' && typeof hooks.launch === 'function'
      ? hooks
      : null;
}

/** @returns {InSessionProcessHooks|null} */
export function getInSessionProcessHooks() {
  return _processHooks;
}

export function resetInSessionProcessHooks() {
  _processHooks = null;
}

// ── Session-live run table (same calling session; complements durable S14) ──

/** @type {Map<string, { run_id: string, pid: number, proc_create_time: number|null, state: string }>} */
const _sessionLive = new Map();

export function resetInSessionLiveTable() {
  _sessionLive.clear();
}

/** @returns {number} */
export function sessionLiveRunCount() {
  let n = 0;
  for (const r of _sessionLive.values()) {
    if (r && (r.state === 'running' || r.state === 'intent')) n += 1;
  }
  return n;
}

// ── Child env (no-token law) ───────────────────────────────────────────────

/**
 * Build child env with forbidden tokens stripped.
 * @param {NodeJS.ProcessEnv} [base]
 * @returns {{ env: NodeJS.ProcessEnv, stripped_keys: string[], no_token_in_child: boolean }}
 */
export function buildChildEnv(base = process.env) {
  const env = { ...base };
  const stripped_keys = [];
  for (const k of FORBIDDEN_CHILD_ENV) {
    if (k in env && env[k] != null && env[k] !== '') {
      stripped_keys.push(k);
    }
    delete env[k];
  }
  // Forbidden keys (including the Anchor capability name) are stripped above
  // via the closed FORBIDDEN_CHILD_ENV list — never via a direct env.<name>
  // property access (criterion 9: engine must not read that token from env).
  return {
    env,
    stripped_keys,
    no_token_in_child: true,
  };
}

/**
 * Observe whether any forbidden key remains in an env object.
 * @param {NodeJS.ProcessEnv|object} env
 */
export function observeChildEnv(env) {
  const forbidden_present = FORBIDDEN_CHILD_ENV.filter(
    (k) => env && env[k] != null && env[k] !== '',
  );
  return {
    no_token_in_child: forbidden_present.length === 0,
    forbidden_present,
  };
}

/**
 * True when argv strings carry no token-like secrets (best-effort).
 * @param {string[]} cmdline
 */
export function argvCarriesNoToken(cmdline) {
  const parts = Array.isArray(cmdline) ? cmdline.map(String) : [];
  for (const p of parts) {
    if (/ANCHOR_TOKEN|CAPABILITY_TOKEN|ECGBERHT_TOKEN/i.test(p)) return false;
    if (/^--token=/i.test(p) || /^--capability=/i.test(p)) return false;
  }
  return true;
}

// ── S14 ledger ─────────────────────────────────────────────────────────────

/**
 * @param {string} projectPath
 * @returns {string}
 */
export function insessionLedgerPath(projectPath) {
  return path.join(path.resolve(projectPath), INSESSION_LEDGER_REL);
}

/**
 * Empty-but-valid ledger.
 * @returns {object}
 */
export function emptyInsessionLedger() {
  return {
    schema: INSESSION_LEDGER_SCHEMA,
    store: INSESSION_STORE,
    runs: [],
    status_events: [],
    next_status_seq: 1,
    adopted_client_event_ids: [],
  };
}

/**
 * @param {string} projectPath
 * @returns {{ ok: true, ledger: object, exists: boolean } | { ok: false, code: string, message: string, exists: boolean }}
 */
export function readInsessionLedger(projectPath) {
  const p = insessionLedgerPath(projectPath);
  try {
    if (!fs.existsSync(p)) {
      return { ok: true, exists: false, ledger: emptyInsessionLedger() };
    }
    const raw = fs.readFileSync(p, 'utf8');
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object' || !Array.isArray(data.runs)) {
      return {
        ok: false,
        exists: true,
        code: EXEC2_CODE.EXEC2_LEDGER_UNREADABLE,
        message: EXEC2_TEXT[EXEC2_CODE.EXEC2_LEDGER_UNREADABLE],
        ledger: null,
      };
    }
    return {
      ok: true,
      exists: true,
      ledger: {
        ...emptyInsessionLedger(),
        ...data,
        runs: Array.isArray(data.runs) ? data.runs : [],
        status_events: Array.isArray(data.status_events)
          ? data.status_events
          : [],
        next_status_seq: Number(data.next_status_seq) || 1,
        adopted_client_event_ids: Array.isArray(data.adopted_client_event_ids)
          ? data.adopted_client_event_ids
          : [],
      },
    };
  } catch (e) {
    return {
      ok: false,
      exists: true,
      code: EXEC2_CODE.EXEC2_LEDGER_UNREADABLE,
      message: String(e?.message ?? e),
      ledger: null,
    };
  }
}

/**
 * Durable write of the S14 ledger (atomic + locked).
 * Prefer `updateInsessionLedger` for read-modify-write races.
 *
 * @param {string} projectPath
 * @param {object} ledger
 * @param {{ timeoutMs?: number }} [opts]
 */
export function writeInsessionLedger(projectPath, ledger, opts = {}) {
  const p = insessionLedgerPath(projectPath);
  const dir = path.dirname(p);
  fs.mkdirSync(dir, { recursive: true });
  return withFileLock(
    p,
    () => {
      const body = {
        ...emptyInsessionLedger(),
        ...ledger,
        schema: INSESSION_LEDGER_SCHEMA,
        store: INSESSION_STORE,
        written_at: new Date().toISOString(),
      };
      writeFileAtomicSync(p, `${JSON.stringify(body, null, 2)}\n`);
      return { ok: true, path: p, store: INSESSION_STORE };
    },
    { timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS },
  );
}

/**
 * Locked read-modify-write of the S14 ledger (T-DUR-S14 concurrency).
 * `mutate(ledger)` returns the next ledger object (or mutates in place).
 *
 * @param {string} projectPath
 * @param {(ledger: object) => object} mutate
 * @param {{ timeoutMs?: number }} [opts]
 */
export function updateInsessionLedger(projectPath, mutate, opts = {}) {
  const p = insessionLedgerPath(projectPath);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  return withFileLock(
    p,
    () => {
      let ledger = emptyInsessionLedger();
      try {
        if (fs.existsSync(p)) {
          const raw = fs.readFileSync(p, 'utf8');
          const data = JSON.parse(raw);
          if (!data || typeof data !== 'object' || !Array.isArray(data.runs)) {
            return {
              ok: false,
              code: EXEC2_CODE.EXEC2_LEDGER_UNREADABLE,
              message: EXEC2_TEXT[EXEC2_CODE.EXEC2_LEDGER_UNREADABLE],
            };
          }
          ledger = {
            ...emptyInsessionLedger(),
            ...data,
            runs: Array.isArray(data.runs) ? data.runs : [],
            status_events: Array.isArray(data.status_events)
              ? data.status_events
              : [],
            next_status_seq: Number(data.next_status_seq) || 1,
            adopted_client_event_ids: Array.isArray(data.adopted_client_event_ids)
              ? data.adopted_client_event_ids
              : [],
          };
        }
      } catch (e) {
        return {
          ok: false,
          code: EXEC2_CODE.EXEC2_LEDGER_UNREADABLE,
          message: String(e?.message ?? e),
        };
      }
      const next = mutate(ledger) || ledger;
      const body = {
        ...emptyInsessionLedger(),
        ...next,
        schema: INSESSION_LEDGER_SCHEMA,
        store: INSESSION_STORE,
        written_at: new Date().toISOString(),
      };
      writeFileAtomicSync(p, `${JSON.stringify(body, null, 2)}\n`);
      return { ok: true, path: p, store: INSESSION_STORE, ledger: body };
    },
    { timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS },
  );
}

/**
 * Count non-terminal live runs in a ledger (+ session table).
 * @param {object} ledger
 * @returns {number}
 */
export function countLiveRuns(ledger) {
  let n = sessionLiveRunCount();
  const runs = Array.isArray(ledger?.runs) ? ledger.runs : [];
  for (const r of runs) {
    if (!r) continue;
    if (r.terminal === true) continue;
    if (r.state === 'running' || r.state === 'intent') {
      // Avoid double-count when already in session table
      if (!_sessionLive.has(String(r.run_id))) n += 1;
    }
  }
  return n;
}

/**
 * @param {string} src
 * @returns {{ ok: boolean, missing: string[] }}
 */
export function assertInsessionDurableHelpersPresent(src) {
  const text = String(src ?? '');
  const missing = [];
  if (!text.includes('writeFileAtomicSync')) missing.push('writeFileAtomicSync');
  if (!text.includes('withFileLock')) missing.push('withFileLock');
  if (!text.includes("INSESSION_STORE = 'S14'") && !text.includes('S14')) {
    missing.push('S14');
  }
  return { ok: missing.length === 0, missing };
}

// ── Status producer #2 (through Wave-13 seam only) ─────────────────────────

/**
 * Append a durable status event to the S14 ledger (monotonic seq) and
 * immediately route it through ingestStatusEvents when projectPath + step_id
 * allow. Never a parallel ledger writer.
 *
 * @param {string} projectPath
 * @param {object} event  shape: kind + fields (seq assigned here)
 * @param {{ who?: string, at?: string, seed?: object|null, skip_index?: boolean }} [opts]
 */
export function emitInsessionStatusEvent(projectPath, event, opts = {}) {
  let stamped = null;
  let seq = 0;
  const written = updateInsessionLedger(projectPath, (ledger) => {
    seq = Number(ledger.next_status_seq) || 1;
    stamped = {
      ...event,
      seq,
      producer: INSESSION_PRODUCER_ID,
      client_event_id:
        event.client_event_id ||
        `insession:${event.kind || 'ev'}:${seq}:${event.run_id || 'na'}`,
    };
    ledger.status_events = [...(ledger.status_events || []), stamped];
    ledger.next_status_seq = seq + 1;
    return ledger;
  });
  if (!written.ok) {
    return exec2Failure(EXEC2_CODE.EXEC2_LEDGER_UNREADABLE, {
      detail: written.message,
    });
  }

  let seam = null;
  if (projectPath && (stamped.step_id || stamped.kind === 'launch_intent')) {
    const producer = makeFixtureProducer([stamped], {
      id: INSESSION_PRODUCER_ID,
    });
    seam = ingestStatusEvents(producer, {
      projectPath,
      who: opts.who || 'insession-executor',
      at: opts.at || stamped.wall_at || new Date().toISOString(),
      seed: opts.seed,
      skip_index: opts.skip_index !== false,
      afterSeq: seq - 1,
    });
  }

  return {
    ok: true,
    seq,
    event: stamped,
    seam,
    producer: INSESSION_PRODUCER_ID,
    status_ingestion_seam: STATUS_INGESTION_SEAM,
  };
}

/**
 * Build a pull producer over durable S14 status_events (tests / re-drain).
 * @param {string} projectPath
 */
export function makeInsessionStatusProducer(projectPath) {
  return {
    id: INSESSION_PRODUCER_ID,
    pull(afterSeq) {
      const read = readInsessionLedger(projectPath);
      if (!read.ok) {
        return { events: [], gap: false, unreadable: true };
      }
      const from = Number(afterSeq) || 0;
      const events = (read.ledger.status_events || []).filter(
        (e) => Number(e.seq) > from,
      );
      return { events, gap: false };
    },
    ack() {
      return { ok: true };
    },
  };
}

// ── Lease renew (S14; law identical to Wave 13) ────────────────────────────

/**
 * Renew the durable lease for a run (S14). Status truth via seam producer #2.
 *
 * @param {string} projectPath
 * @param {string} runId
 * @param {{ nowMono?: number, step_id?: string, who?: string, at?: string, seed?: object|null }} [opts]
 */
export function renewInsessionLease(projectPath, runId, opts = {}) {
  const nowMono =
    opts.nowMono != null ? Number(opts.nowMono) : defaultLeaseMonoMs();
  let run = null;
  const written = updateInsessionLedger(projectPath, (ledger) => {
    const idx = ledger.runs.findIndex((r) => r && r.run_id === runId);
    if (idx < 0) {
      run = null;
      return ledger;
    }
    run = { ...ledger.runs[idx] };
    const prevSeq = Number(run.lease?.seq) || 0;
    run.lease = {
      ...(run.lease || {}),
      last_renew_mono_ms: nowMono,
      seq: prevSeq + 1,
      seq_anchor_mono_ms: run.lease?.seq_anchor_mono_ms ?? nowMono,
      ttl_ms: LEASE_TTL_MS,
      renew_interval_ms: LEASE_RENEW_INTERVAL_MS,
    };
    run.state = run.state === 'intent' ? 'running' : run.state;
    ledger.runs[idx] = run;
    return ledger;
  });
  if (!written.ok) {
    return exec2Failure(EXEC2_CODE.EXEC2_LEDGER_UNREADABLE, {
      detail: written.message,
    });
  }
  if (!run) {
    return exec2Failure(EXEC2_CODE.EXEC_NO_RUNS, { run_id: runId });
  }

  // Emit stamps producer on the durable event + Wave-13 path; the renew
  // return exposes only the ingestion-seam result (not the emit wrapper).
  const emitResult = emitInsessionStatusEvent(
    projectPath,
    {
      kind: 'lease_renew',
      run_id: runId,
      step_id: opts.step_id || run.step_id,
      last_renew_mono_ms: nowMono,
      pid: run.pid,
      proc_create_time: run.proc_create_time,
      run_state: RUN_LIVENESS.RUNNING,
    },
    opts,
  );

  return {
    ok: true,
    run_id: runId,
    lease: run.lease,
    lease_law: {
      ttl_ms: LEASE_TTL_MS,
      renew_interval_ms: LEASE_RENEW_INTERVAL_MS,
      evaluate: 'evaluateLeaseState',
    },
    seam: emitResult && emitResult.ok !== false ? emitResult.seam ?? null : null,
  };
}

// ── Cmdline resolution ─────────────────────────────────────────────────────

/**
 * Resolve the commissioned skill CLI cmdline.
 * Host may inject ctx.cmdline / ctx.resolveCmdline; otherwise skill entry from dossier.
 *
 * @param {object} dossier
 * @param {object} [ctx]
 * @returns {{ ok: true, cmdline: string[] } | { ok: false, code: string, message: string }}
 */
export function resolveCommissionCmdline(dossier, ctx = {}) {
  if (Array.isArray(ctx.cmdline) && ctx.cmdline.length > 0) {
    return { ok: true, cmdline: ctx.cmdline.map(String) };
  }
  if (typeof ctx.resolveCmdline === 'function') {
    try {
      const r = ctx.resolveCmdline(dossier, ctx);
      if (Array.isArray(r) && r.length > 0) {
        return { ok: true, cmdline: r.map(String) };
      }
      if (r && r.ok && Array.isArray(r.cmdline)) {
        return { ok: true, cmdline: r.cmdline.map(String) };
      }
    } catch (e) {
      return {
        ok: false,
        code: EXEC2_CODE.EXEC2_SUBSTRATE_MISSING,
        message: String(e?.message ?? e),
      };
    }
  }
  if (Array.isArray(dossier?.cmdline) && dossier.cmdline.length > 0) {
    return { ok: true, cmdline: dossier.cmdline.map(String) };
  }
  if (Array.isArray(dossier?.launch?.cmdline) && dossier.launch.cmdline.length) {
    return { ok: true, cmdline: dossier.launch.cmdline.map(String) };
  }
  // No hardcoded host skill roots — absence is named substrate-missing.
  return {
    ok: false,
    code: EXEC2_CODE.EXEC2_SUBSTRATE_MISSING,
    message: EXEC2_TEXT[EXEC2_CODE.EXEC2_SUBSTRATE_MISSING],
  };
}

// ── Launch intent (BEFORE spawn) ───────────────────────────────────────────

/**
 * Record durable launch intent before any process start (S14).
 *
 * @param {string} projectPath
 * @param {object} intent
 */
export function writeLaunchIntent(projectPath, intent) {
  const run_id =
    intent.run_id ||
    intent.job_id ||
    `insession-${crypto.randomBytes(6).toString('hex')}`;
  const record = {
    run_id,
    job_id: intent.job_id ?? null,
    commission_id: intent.commission_id ?? run_id,
    step_id: intent.step_id ?? null,
    worktree: intent.worktree ?? null,
    state: 'intent',
    terminal: false,
    launch_intent: {
      confirmed: true,
      launched: false,
      at: intent.at || new Date().toISOString(),
      cmdline: intent.cmdline || [],
      client_event_id: intent.client_event_id || `launch-intent:${run_id}`,
    },
    pid: null,
    proc_create_time: null,
    lease: null,
    auth_stamp: intent.auth_stamp ?? null,
    no_token_in_child: intent.no_token_in_child !== false,
    cmdline: intent.cmdline || [],
    commissioned_as: intent.commissioned_as ?? null,
    skill: intent.skill ?? null,
  };

  const written = updateInsessionLedger(projectPath, (ledger) => {
    const existing = ledger.runs.findIndex((r) => r && r.run_id === run_id);
    if (existing >= 0) ledger.runs[existing] = record;
    else ledger.runs.push(record);
    return ledger;
  });
  if (!written.ok) {
    return exec2Failure(EXEC2_CODE.EXEC2_LEDGER_UNREADABLE, {
      detail: written.message,
    });
  }

  _sessionLive.set(run_id, {
    run_id,
    pid: 0,
    proc_create_time: null,
    state: 'intent',
  });

  return { ok: true, run_id, record, store: INSESSION_STORE };
}

/**
 * Patch a run record in the S14 ledger.
 * @param {string} projectPath
 * @param {string} runId
 * @param {object} patch
 */
export function updateRunRecord(projectPath, runId, patch) {
  let updated = null;
  const written = updateInsessionLedger(projectPath, (ledger) => {
    const idx = ledger.runs.findIndex((r) => r && r.run_id === runId);
    if (idx < 0) {
      updated = null;
      return ledger;
    }
    ledger.runs[idx] = { ...ledger.runs[idx], ...patch };
    updated = ledger.runs[idx];
    return ledger;
  });
  if (!written.ok) {
    return exec2Failure(EXEC2_CODE.EXEC2_LEDGER_UNREADABLE, {
      detail: written.message,
    });
  }
  if (!updated) {
    return exec2Failure(EXEC2_CODE.EXEC_NO_RUNS, { run_id: runId });
  }
  const live = _sessionLive.get(runId);
  if (live) {
    _sessionLive.set(runId, {
      ...live,
      pid: patch.pid ?? live.pid,
      proc_create_time:
        patch.proc_create_time !== undefined
          ? patch.proc_create_time
          : live.proc_create_time,
      state: patch.state ?? live.state,
    });
    if (patch.terminal === true) _sessionLive.delete(runId);
  }
  return { ok: true, run: updated };
}

// ── Auth at launch ─────────────────────────────────────────────────────────

/**
 * Authorize launch; bare hosts may stamp local-trust honestly.
 * @param {object} [ctx]
 */
export function authorizeLaunch(ctx = {}) {
  const authCtx =
    ctx.authCtx ??
    ctx.auth ??
    (ctx.token != null || ctx.revoked != null || ctx.principal != null
      ? {
          token: ctx.token,
          principal: ctx.principal,
          revoked: ctx.revoked,
          expires_at: ctx.expires_at,
        }
      : ctx.use_local_trust === false
        ? null
        : {
            principal: ctx.principal ?? 'local-session',
            credential_class: 'local_trust',
          });

  // When no authorizer is injected, allow-all; stamp local-trust provenance
  // for bare-host honesty when credential_class is local_trust.
  let decision;
  if (authCtx == null) {
    decision = authorize('launch', {});
  } else {
    decision = authorize('launch', authCtx);
  }

  const stamp = {
    ok: decision.ok === true,
    code: decision.code ?? null,
    seam: 'launch',
    provenance:
      decision.provenance ||
      (authCtx?.credential_class === 'local_trust'
        ? 'local_trust'
        : decision.code === 'auth-allow-all'
          ? 'allow-all'
          : decision.code === 'auth-local-trust'
            ? 'local_trust'
            : decision.ok
              ? 'injected'
              : 'refused'),
  };
  return { decision, stamp };
}

// ── Execute (main) ─────────────────────────────────────────────────────────

/**
 * In-session executor entry — registered on the Wave-11 seam.
 *
 * @param {object} dossier  confirmed commission dossier
 * @param {object} [ctx]
 * @returns {object}
 */
export function executeInSession(dossier, ctx = {}) {
  if (!dossier || typeof dossier !== 'object') {
    return exec2Failure(EXEC2_CODE.EXEC_REFUSED_UNCONFIRMED, {
      error: 'dossier-required',
      launched: false,
    });
  }

  const confirmed =
    dossier.confirmed === true ||
    dossier.confirmation != null ||
    dossier.state === 'queued' ||
    dossier.state === 'confirmed' ||
    ctx.confirmed === true;

  if (!confirmed) {
    return exec2Failure(EXEC2_CODE.EXEC_REFUSED_UNCONFIRMED, {
      error: 'unconfirmed-refused',
      launched: false,
      processes_launched: 0,
      pid: null,
      proc_create_time: null,
    });
  }

  const projectPath =
    ctx.project_path ||
    ctx.projectPath ||
    dossier.project_path ||
    dossier.projectPath ||
    null;
  if (!projectPath || typeof projectPath !== 'string') {
    return exec2Failure(EXEC2_CODE.EXEC2_LEDGER_UNREADABLE, {
      error: 'project_path_required',
      message:
        'In-session executor requires project_path for the S14 run ledger.',
      launched: false,
    });
  }

  // Auth before process launch (local-trust stamped on bare hosts)
  const { decision: authDecision, stamp: auth_stamp } = authorizeLaunch(ctx);
  if (!authDecision.ok) {
    return exec2Failure(EXEC2_CODE.EXEC_AUTH_REFUSED, {
      error: authDecision.code ?? 'auth-refused',
      message: authDecision.message ?? EXEC2_TEXT[EXEC2_CODE.EXEC_AUTH_REFUSED],
      auth: authDecision,
      auth_stamp,
      launched: false,
      processes_launched: 0,
      pid: null,
      proc_create_time: null,
    });
  }

  const ledgerRead = readInsessionLedger(projectPath);
  if (!ledgerRead.ok) {
    return exec2Failure(EXEC2_CODE.EXEC2_LEDGER_UNREADABLE, {
      detail: ledgerRead.message,
      launched: false,
    });
  }

  const live = countLiveRuns(ledgerRead.ledger);
  if (live >= INSESSION_MAX_CONCURRENT_RUNS) {
    return {
      ...exec2Failure(EXEC2_CODE.EXEC2_BUSY, {
        error: 'insession-busy',
        state: 'insession-busy',
        bound: INSESSION_MAX_CONCURRENT_RUNS,
        live_runs: live,
      }),
      // Refusal name for T-BND-20
      refusal: 'insession-busy',
      launched: false,
      commission_preserved: true,
      job_id: dossier.job_id ?? null,
      commissioned_as: dossier.commissioned_as ?? null,
      processes_launched: 0,
      pid: null,
      proc_create_time: null,
    };
  }

  const cmd = resolveCommissionCmdline(dossier, ctx);
  if (!cmd.ok) {
    return exec2Failure(EXEC2_CODE.EXEC2_SUBSTRATE_MISSING, {
      error: 'substrate-missing',
      message: cmd.message,
      launched: false,
      processes_launched: 0,
    });
  }
  const cmdline = cmd.cmdline;
  if (!argvCarriesNoToken(cmdline)) {
    return exec2Failure(EXEC2_CODE.EXEC_AUTH_REFUSED, {
      error: 'token-in-argv',
      message: 'Child argv must not carry a token or capability.',
      launched: false,
    });
  }

  const hooks = ctx.hooks || _processHooks;
  if (!hooks || typeof hooks.launch !== 'function') {
    return exec2Failure(EXEC2_CODE.EXEC2_SUBSTRATE_MISSING, {
      error: 'process-hooks-missing',
      message:
        'In-session process hooks not installed — host must inject launch (engine is process-free).',
      launched: false,
    });
  }

  const worktree =
    ctx.worktree ||
    dossier.worktree ||
    path.join(path.resolve(projectPath), '.ecgberht', 'runs', `run-${Date.now()}`);
  try {
    fs.mkdirSync(worktree, { recursive: true });
  } catch (e) {
    return exec2Failure(EXEC2_CODE.EXEC2_SUBSTRATE_MISSING, {
      error: 'worktree-unwritable',
      message: String(e?.message ?? e),
      launched: false,
    });
  }

  const at = ctx.at || new Date().toISOString();
  const run_id =
    ctx.run_id ||
    dossier.run_id ||
    dossier.job_id ||
    `insession-${crypto.randomBytes(6).toString('hex')}`;
  const step_id = ctx.step_id || dossier.step_id || dossier.bound_step_id || null;
  const client_event_id =
    ctx.client_event_id ||
    dossier.client_event_id ||
    `launch-intent:${run_id}`;

  const childEnvBuilt = buildChildEnv(ctx.env || process.env);
  childEnvBuilt.env.ECGBERHT_HANDBACK_WORKTREE = worktree;
  if (dossier.commission_id || dossier.job_id) {
    childEnvBuilt.env.ECGBERHT_COMMISSION_ID = String(
      dossier.commission_id || dossier.job_id,
    );
  }
  const envObs = observeChildEnv(childEnvBuilt.env);
  if (!envObs.no_token_in_child) {
    return exec2Failure(EXEC2_CODE.EXEC_AUTH_REFUSED, {
      error: 'token_leaked_to_child_env',
      forbidden_present: envObs.forbidden_present,
      launched: false,
    });
  }

  // ── Durable launch intent BEFORE process launch (S14) ───────────────────
  const intentWrite = writeLaunchIntent(projectPath, {
    run_id,
    job_id: dossier.job_id ?? null,
    commission_id: dossier.commission_id || dossier.job_id || run_id,
    step_id,
    worktree,
    cmdline,
    at,
    client_event_id,
    auth_stamp,
    no_token_in_child: true,
    commissioned_as: dossier.commissioned_as ?? null,
    skill: dossier.skill ?? dossier.commissioned_skill ?? null,
  });
  if (!intentWrite.ok) return intentWrite;

  emitInsessionStatusEvent(
    projectPath,
    {
      kind: 'launch_intent',
      run_id,
      step_id,
      client_event_id,
      confirmed: true,
      launched: false,
      cmdline: sanitizeCmdlineForRecord(cmdline),
    },
    { who: ctx.who || 'insession-executor', at, seed: ctx.seed },
  );

  // ── Spawn via injected host hooks ───────────────────────────────────────
  let launched;
  try {
    launched = hooks.launch({
      cmdline,
      cwd: ctx.cwd || worktree,
      env: childEnvBuilt.env,
      worktree,
      run_id,
    });
  } catch (e) {
    updateRunRecord(projectPath, run_id, {
      state: 'dead',
      terminal: true,
      death_cause: 'launch_threw',
      error: String(e?.message ?? e),
    });
    _sessionLive.delete(run_id);
    return exec2Failure(EXEC2_CODE.EXEC2_SUBSTRATE_MISSING, {
      error: 'launch-threw',
      message: String(e?.message ?? e),
      run_id,
      launched: false,
    });
  }

  const pid = Number(launched?.pid);
  if (!Number.isFinite(pid) || pid <= 0) {
    updateRunRecord(projectPath, run_id, {
      state: 'dead',
      terminal: true,
      death_cause: 'no_pid',
    });
    _sessionLive.delete(run_id);
    return exec2Failure(EXEC2_CODE.EXEC2_SUBSTRATE_MISSING, {
      error: 'no-pid',
      run_id,
      launched: false,
    });
  }

  let proc_create_time =
    launched.proc_create_time != null
      ? Number(launched.proc_create_time)
      : null;
  if (
    (proc_create_time == null || !Number.isFinite(proc_create_time)) &&
    typeof hooks.observeCreateTime === 'function'
  ) {
    try {
      proc_create_time = hooks.observeCreateTime(pid);
    } catch {
      proc_create_time = null;
    }
  }
  if (proc_create_time == null || !Number.isFinite(proc_create_time)) {
    // Fall back to wall clock seconds — host should supply real create-time
    // for anti-stub PASS; tests inject observed create-time.
    proc_create_time = Date.now() / 1000;
  }

  const liveAt = new Date().toISOString();
  const nowMono = defaultLeaseMonoMs();

  updateRunRecord(projectPath, run_id, {
    state: 'running',
    terminal: false,
    pid,
    proc_create_time,
    identity_key: processIdentityKey(pid, proc_create_time),
    launch_intent: {
      confirmed: true,
      launched: true,
      at,
      cmdline: sanitizeCmdlineForRecord(cmdline),
      client_event_id,
    },
    lease: {
      last_renew_mono_ms: nowMono,
      seq: 1,
      seq_anchor_mono_ms: nowMono,
      ttl_ms: LEASE_TTL_MS,
      renew_interval_ms: LEASE_RENEW_INTERVAL_MS,
    },
    live_observed_at: liveAt,
    auth_stamp,
    no_token_in_child: true,
    stripped_env_keys: childEnvBuilt.stripped_keys,
  });

  _sessionLive.set(run_id, {
    run_id,
    pid,
    proc_create_time,
    state: 'running',
  });

  emitInsessionStatusEvent(
    projectPath,
    {
      kind: 'run_status',
      run_id,
      step_id,
      run_state: RUN_LIVENESS.RUNNING,
      cause: 'launched',
      pid,
      proc_create_time,
      client_event_id: `run-status:running:${run_id}`,
    },
    { who: ctx.who || 'insession-executor', at: liveAt, seed: ctx.seed },
  );

  const result = {
    ok: true,
    launched: true,
    path: 'insession',
    executor: 'insession',
    run_id,
    job_id: dossier.job_id ?? null,
    commission_id: dossier.commission_id || dossier.job_id || run_id,
    step_id,
    pid,
    proc_create_time,
    identity_key: processIdentityKey(pid, proc_create_time),
    worktree,
    cmdline: sanitizeCmdlineForRecord(cmdline),
    cmdline_names_trio_entry: cmdlineNamesTrioEntry(cmdline),
    no_token_in_child: true,
    stripped_env_keys: childEnvBuilt.stripped_keys,
    auth_stamp,
    intent: {
      kind: 'launch_intent',
      at,
      client_event_id,
      durable: true,
      store: INSESSION_STORE,
    },
    lease: {
      last_renew_mono_ms: nowMono,
      ttl_ms: LEASE_TTL_MS,
    },
    producer: INSESSION_PRODUCER_ID,
    live_observed_at: liveAt,
    processes_launched: 1,
    wait: null,
    supervise: null,
  };

  // Optional: wait for completion in this call (tests / gate)
  const shouldWait = ctx.wait === true || ctx.supervise === true;
  if (shouldWait && typeof launched.wait === 'function') {
    const waitResult = launched.wait();
    const finish = (exit) =>
      completeInsessionRun(projectPath, run_id, {
        exit_code: exit?.code ?? null,
        who: ctx.who,
        at: new Date().toISOString(),
        seed: ctx.seed,
        step_id,
        write_handback: ctx.write_handback,
        handback_body: ctx.handback_body,
      });
    if (waitResult && typeof waitResult.then === 'function') {
      result.async = true;
      result.promise = waitResult.then(finish);
      result.wait = result.promise;
    } else {
      const completed = finish(waitResult || {});
      Object.assign(result, { completed, terminal_observed_at: completed.terminal_observed_at });
    }
  } else if (typeof launched.wait === 'function') {
    // Expose wait without blocking
    result.wait = () => {
      const w = launched.wait();
      const finish = (exit) =>
        completeInsessionRun(projectPath, run_id, {
          exit_code: exit?.code ?? null,
          who: ctx.who,
          at: new Date().toISOString(),
          seed: ctx.seed,
          step_id,
          write_handback: ctx.write_handback,
          handback_body: ctx.handback_body,
        });
      if (w && typeof w.then === 'function') return w.then(finish);
      return finish(w || {});
    };
    result.supervise = result.wait;
  }

  return result;
}

/**
 * Mark run terminal after supervised exit; optional wrapper handback write.
 * @param {string} projectPath
 * @param {string} runId
 * @param {object} [opts]
 */
export function completeInsessionRun(projectPath, runId, opts = {}) {
  const terminal_observed_at = opts.at || new Date().toISOString();
  const read = readInsessionLedger(projectPath);
  if (!read.ok) {
    return exec2Failure(EXEC2_CODE.EXEC2_LEDGER_UNREADABLE, {
      detail: read.message,
    });
  }
  const run = (read.ledger.runs || []).find((r) => r && r.run_id === runId);
  if (!run) {
    return exec2Failure(EXEC2_CODE.EXEC_NO_RUNS, { run_id: runId });
  }

  // Optional: wrapper writes handback pair (same S6 contract as Anchor)
  let handback_write = null;
  if (opts.write_handback === true && opts.handback_body && run.worktree) {
    handback_write = writeHandbackPair(run.worktree, opts.handback_body, {
      client_event_id: opts.handback_body.client_event_id || `hb:${runId}`,
    });
  }

  const handback_present = run.worktree ? isIngestable(run.worktree) : false;
  const exitOk = opts.exit_code === 0 || opts.exit_code == null;
  const state =
    handback_present || exitOk
      ? handback_present
        ? 'done'
        : 'dead'
      : 'dead';

  updateRunRecord(projectPath, runId, {
    state,
    terminal: true,
    exit_code: opts.exit_code ?? null,
    terminal_observed_at,
    handback_present,
  });
  _sessionLive.delete(runId);

  const cause = handback_present
    ? 'completed'
    : opts.exit_code != null && opts.exit_code !== 0
      ? 'exit_nonzero'
      : 'handback_missing_on_complete';

  emitInsessionStatusEvent(
    projectPath,
    {
      kind: 'run_status',
      run_id: runId,
      step_id: opts.step_id || run.step_id,
      run_state: RUN_LIVENESS.DEAD,
      cause,
      pid: run.pid,
      proc_create_time: run.proc_create_time,
      client_event_id: `run-status:terminal:${runId}`,
    },
    {
      who: opts.who || 'insession-executor',
      at: terminal_observed_at,
      seed: opts.seed,
    },
  );

  return {
    ok: true,
    run_id: runId,
    state,
    terminal: true,
    terminal_observed_at,
    handback_present,
    handback_write,
    exit_code: opts.exit_code ?? null,
  };
}

/** @param {string[]} cmdline */
function sanitizeCmdlineForRecord(cmdline) {
  // Prefer basename for absolute host segments; keep trio-naming segments
  return (Array.isArray(cmdline) ? cmdline : []).map((part) => {
    const s = String(part);
    if (!path.isAbsolute(s) && !/^[A-Za-z]:[\\/]/.test(s)) return s;
    // Keep relative-from-trio-token form without shipping user homes
    if (/([/\\])Users\1/i.test(s) || /([/\\])home\1/i.test(s)) {
      return path.basename(s);
    }
    return s;
  });
}

// ── commission-kill ────────────────────────────────────────────────────────

/**
 * Tree-kill by process identity; confirm death POSITIVELY; emit DEAD cause=killed.
 * Unconfirmable kill → EXEC2_KILL_UNCONFIRMED (never silent success).
 *
 * @param {{
 *   project_path: string,
 *   run_id?: string,
 *   job_id?: string,
 *   who?: string,
 *   at?: string,
 *   seed?: object|null,
 *   hooks?: InSessionProcessHooks,
 *   confirm_timeout_ms?: number,
 * }} opts
 */
export function commissionKill(opts = {}) {
  const projectPath = opts.project_path || opts.projectPath;
  if (!projectPath) {
    return exec2Failure(EXEC2_CODE.EXEC2_LEDGER_UNREADABLE, {
      error: 'project_path_required',
    });
  }
  const read = readInsessionLedger(projectPath);
  if (!read.ok) {
    return exec2Failure(EXEC2_CODE.EXEC2_LEDGER_UNREADABLE, {
      detail: read.message,
    });
  }

  const runId = opts.run_id || opts.job_id;
  const run = (read.ledger.runs || []).find(
    (r) =>
      r &&
      (r.run_id === runId ||
        r.job_id === runId ||
        r.commission_id === runId),
  );
  if (!run) {
    return exec2Failure(EXEC2_CODE.EXEC_NO_RUNS, {
      run_id: runId,
      message: EXEC2_TEXT[EXEC2_CODE.EXEC_NO_RUNS],
    });
  }

  const pid = Number(run.pid);
  const pct =
    run.proc_create_time == null ? null : Number(run.proc_create_time);
  if (!Number.isFinite(pid) || pid <= 0) {
    return exec2Failure(EXEC2_CODE.EXEC2_KILL_UNCONFIRMED, {
      run_id: run.run_id,
      error: 'no-pid-to-kill',
    });
  }

  const hooks = opts.hooks || _processHooks;
  let killIssued = false;
  let killDetail = null;
  if (hooks && typeof hooks.treeKill === 'function') {
    try {
      const kr = hooks.treeKill({
        pid,
        proc_create_time: pct,
        run_id: run.run_id,
      });
      killIssued = kr?.ok !== false;
      killDetail = kr;
    } catch (e) {
      killIssued = false;
      killDetail = { ok: false, detail: String(e?.message ?? e) };
    }
  } else {
    // Best-effort single-process signal (not full tree) when no host hook.
    // Never claims tree-kill success without positive identity confirmation.
    try {
      process.kill(pid, 'SIGTERM');
      killIssued = true;
      killDetail = { ok: true, method: 'process.kill-SIGTERM' };
    } catch (e) {
      const code = e && (e.code || e.errno);
      // Already gone
      if (code === 'ESRCH') {
        killIssued = true;
        killDetail = { ok: true, method: 'already-dead', code };
      } else {
        killIssued = false;
        killDetail = { ok: false, detail: String(e?.message ?? e) };
      }
    }
    try {
      process.kill(pid, 'SIGKILL');
    } catch {
      /* ignore */
    }
  }

  // Positive death confirmation by identity (never pid alone)
  const obs = observeProcessIdentity(pid, pct);
  const confirmedDead = obs.status === 'dead';

  if (!confirmedDead) {
    // Do NOT mark killed; report by name
    updateRunRecord(projectPath, run.run_id, {
      kill_issued: killIssued,
      kill_detail: killDetail,
      kill_confirmed: false,
      liveness: obs.status,
    });
    return {
      ...exec2Failure(EXEC2_CODE.EXEC2_KILL_UNCONFIRMED, {
        run_id: run.run_id,
        pid,
        proc_create_time: pct,
        identity_observation: obs,
        kill_issued: killIssued,
        kill_detail: killDetail,
      }),
      killed: false,
      death_confirmed: false,
    };
  }

  const at = opts.at || new Date().toISOString();
  updateRunRecord(projectPath, run.run_id, {
    state: 'killed',
    terminal: true,
    kill_issued: true,
    kill_confirmed: true,
    death_cause: 'killed',
    terminal_observed_at: at,
    kill_detail: killDetail,
  });
  _sessionLive.delete(run.run_id);

  const seam = emitInsessionStatusEvent(
    projectPath,
    {
      kind: 'run_status',
      run_id: run.run_id,
      step_id: run.step_id,
      run_state: RUN_LIVENESS.DEAD,
      cause: 'killed',
      pid,
      proc_create_time: pct,
      client_event_id: `run-status:killed:${run.run_id}`,
    },
    { who: opts.who || 'commission-kill', at, seed: opts.seed },
  );

  // Also emit explicit status_flip shape for spine binding
  if (run.step_id) {
    emitInsessionStatusEvent(
      projectPath,
      {
        kind: 'status_flip',
        step_id: run.step_id,
        to: 'waiting',
        run_id: run.run_id,
        run_state: RUN_LIVENESS.DEAD,
        cause: 'killed',
        client_event_id: `status-flip:killed:${run.run_id}`,
        receipt: {
          who: opts.who || 'commission-kill',
          when: at,
          why: `status_flip->DEAD cause=killed run_id=${run.run_id} producer=${INSESSION_PRODUCER_ID}`,
          run_state: RUN_LIVENESS.DEAD,
          cause: 'killed',
          producer: INSESSION_PRODUCER_ID,
        },
        at,
      },
      { who: opts.who || 'commission-kill', at, seed: opts.seed },
    );
  }

  return {
    ok: true,
    killed: true,
    death_confirmed: true,
    run_id: run.run_id,
    pid,
    proc_create_time: pct,
    cause: 'killed',
    status_flip: { to: RUN_LIVENESS.DEAD, cause: 'killed' },
    seam,
    identity_observation: obs,
    store_torn: false,
  };
}

// ── Orphan reconcile (next invocation / openProjectPipeline stage 1) ───────

/**
 * Reconcile in-session runs left by a dead calling session.
 * Adopts a complete handback pair exactly once (idempotent via client_event_id);
 * names EXEC_RUN_DIED / EXEC_HANDBACK_MISSING — never silent absorb.
 *
 * @param {string} projectPath
 * @param {{
 *   who?: string,
 *   at?: string,
 *   seed?: object|null,
 *   nowMono?: number,
 *   handback_ttl_ms?: number,
 *   probe?: { probeOne?: function },
 * }} [opts]
 */
export function reconcileInSessionOrphans(projectPath, opts = {}) {
  const who = opts.who || 'insession-reconcile';
  const at = opts.at || new Date().toISOString();
  const nowMono =
    opts.nowMono != null ? Number(opts.nowMono) : defaultLeaseMonoMs();
  const handbackTtlMs = Number(opts.handback_ttl_ms ?? LEASE_TTL_MS * 3);

  const read = readInsessionLedger(projectPath);
  if (!read.ok) {
    return {
      ok: false,
      ...exec2Failure(EXEC2_CODE.EXEC2_LEDGER_UNREADABLE, {
        detail: read.message,
      }),
      outcomes: [],
    };
  }
  if (!read.exists || !(read.ledger.runs || []).length) {
    return {
      ok: true,
      outcomes: [],
      ...exec2Failure(EXEC2_CODE.EXEC_NO_RUNS),
      empty: true,
    };
  }

  const outcomes = [];
  const adopted_ids = new Set(read.ledger.adopted_client_event_ids || []);
  const pendingIds = (read.ledger.runs || [])
    .filter(
      (r) =>
        r &&
        r.terminal !== true &&
        r.state !== 'done' &&
        r.state !== 'killed' &&
        r.state !== 'adopted',
    )
    .map((r) => r.run_id);

  const loadRun = (runId) => {
    const r = readInsessionLedger(projectPath);
    if (!r.ok) return { ok: false, ledger: null, run: null, idx: -1 };
    const idx = (r.ledger.runs || []).findIndex((x) => x && x.run_id === runId);
    return {
      ok: true,
      ledger: r.ledger,
      run: idx >= 0 ? r.ledger.runs[idx] : null,
      idx,
    };
  };

  const patchRun = (runId, patch) => {
    const cur = loadRun(runId);
    if (!cur.ok || cur.idx < 0) return cur;
    cur.ledger.runs[cur.idx] = { ...cur.ledger.runs[cur.idx], ...patch };
    cur.ledger.adopted_client_event_ids = [...adopted_ids];
    writeInsessionLedger(projectPath, cur.ledger);
    return { ok: true, run: cur.ledger.runs[cur.idx] };
  };

  for (const runId of pendingIds) {
    const cur = loadRun(runId);
    if (!cur.ok || !cur.run) continue;
    const run = cur.run;
    if (run.terminal === true) continue;

    const worktree = run.worktree;
    const pairOk = worktree ? isIngestable(worktree) : false;

    if (pairOk) {
      const hb = readIngestableHandback(worktree);
      const ce = hb.ok
        ? hb.client_event_id || hb.handback?.client_event_id
        : null;
      const idemKey = ce || `adopt:${run.run_id}`;

      if (adopted_ids.has(String(idemKey))) {
        patchRun(runId, {
          terminal: true,
          state: 'adopted',
          adopt_duplicate: true,
        });
        outcomes.push({
          run_id: run.run_id,
          kind: 'duplicate_skipped',
          client_event_id: idemKey,
          adopted: false,
          duplicate: true,
        });
        continue;
      }

      let ingest = null;
      if (hb.ok) {
        ingest = ingestHandback(projectPath, worktree, {
          skip_index: true,
          at,
        });
      }

      adopted_ids.add(String(idemKey));
      patchRun(runId, {
        terminal: true,
        state: 'adopted',
        adopted_at: at,
        adopt_client_event_id: idemKey,
      });

      emitInsessionStatusEvent(
        projectPath,
        {
          kind: 'run_status',
          run_id: run.run_id,
          step_id: run.step_id,
          run_state: RUN_LIVENESS.DEAD,
          cause: 'adopted',
          client_event_id: `run-status:adopted:${run.run_id}`,
        },
        { who, at, seed: opts.seed },
      );

      outcomes.push({
        run_id: run.run_id,
        kind: 'adopted',
        status_code: EXEC2_CODE.EXEC2_RUN_ADOPTED,
        client_event_id: idemKey,
        adopted: true,
        duplicate: false,
        ingest,
        user_text: EXEC2_TEXT[EXEC2_CODE.EXEC2_RUN_ADOPTED].replace(
          '<id>',
          String(run.run_id),
        ),
      });
      continue;
    }

    const pid = run.pid != null ? Number(run.pid) : null;
    const pct =
      run.proc_create_time == null ? null : Number(run.proc_create_time);
    let liveness = 'unknown';
    if (pid && Number.isFinite(pid)) {
      if (opts.probe && typeof opts.probe.probeOne === 'function') {
        const p = opts.probe.probeOne(pid, pct);
        liveness = p?.status || 'unknown';
      } else {
        const obs = observeProcessIdentity(pid, pct);
        liveness = obs.status;
      }
    }

    if (liveness === 'alive') {
      const leaseEval = evaluateLeaseState(run.lease || {}, {
        nowMono,
        ttlMs: LEASE_TTL_MS,
        hysteresisMs: 0,
      });
      if (leaseEval.state === RUN_LIVENESS.DEAD) {
        patchRun(runId, {
          terminal: true,
          state: 'dead',
          death_cause: 'lease_expired_orphan',
        });
        emitInsessionStatusEvent(
          projectPath,
          {
            kind: 'run_status',
            run_id: run.run_id,
            step_id: run.step_id,
            run_state: RUN_LIVENESS.DEAD,
            cause: 'lease_expired',
            client_event_id: `run-status:died-lease:${run.run_id}`,
          },
          { who, at, seed: opts.seed },
        );
        outcomes.push({
          run_id: run.run_id,
          kind: 'named_dead',
          status_code: EXEC2_CODE.EXEC_RUN_DIED,
          cause: 'lease_expired',
          user_text: EXEC2_TEXT[EXEC2_CODE.EXEC_RUN_DIED].replace(
            '<id>',
            String(run.run_id),
          ),
          silently_absorbed: false,
        });
      } else {
        outcomes.push({
          run_id: run.run_id,
          kind: 'still_live',
          liveness: 'alive',
          lease_state: leaseEval.state,
        });
      }
      continue;
    }

    if (liveness === 'dead') {
      patchRun(runId, {
        terminal: true,
        state: 'dead',
        death_cause: 'process_identity_gone',
      });
      emitInsessionStatusEvent(
        projectPath,
        {
          kind: 'run_status',
          run_id: run.run_id,
          step_id: run.step_id,
          run_state: RUN_LIVENESS.DEAD,
          cause: 'process_died',
          client_event_id: `run-status:died:${run.run_id}`,
        },
        { who, at, seed: opts.seed },
      );
      outcomes.push({
        run_id: run.run_id,
        kind: 'named_dead',
        status_code: EXEC2_CODE.EXEC_RUN_DIED,
        user_text: EXEC2_TEXT[EXEC2_CODE.EXEC_RUN_DIED].replace(
          '<id>',
          String(run.run_id),
        ),
        silently_absorbed: false,
      });
      continue;
    }

    const launchedAt = run.launch_intent?.at || run.live_observed_at;
    let ageMs = null;
    if (launchedAt) {
      const t = Date.parse(String(launchedAt));
      if (Number.isFinite(t)) ageMs = Date.now() - t;
    }
    const leaseEval = evaluateLeaseState(run.lease || {}, {
      nowMono,
      ttlMs: handbackTtlMs,
      hysteresisMs: 0,
    });
    const overdue =
      leaseEval.state === RUN_LIVENESS.DEAD ||
      (ageMs != null && ageMs > handbackTtlMs) ||
      opts.force_missing === true ||
      run.handback_never_arrived === true ||
      run.missing_handback === true;

    if (overdue) {
      patchRun(runId, {
        terminal: true,
        state: 'handback_missing',
        death_cause: 'handback_missing',
      });
      emitInsessionStatusEvent(
        projectPath,
        {
          kind: 'run_status',
          run_id: run.run_id,
          step_id: run.step_id,
          run_state: RUN_LIVENESS.DEAD,
          cause: 'handback_missing',
          client_event_id: `run-status:hb-missing:${run.run_id}`,
        },
        { who, at, seed: opts.seed },
      );
      outcomes.push({
        run_id: run.run_id,
        kind: 'named_missing_handback',
        status_code: EXEC2_CODE.EXEC_HANDBACK_MISSING,
        user_text: EXEC2_TEXT[EXEC2_CODE.EXEC_HANDBACK_MISSING].replace(
          '<id>',
          String(run.run_id),
        ),
        silently_absorbed: false,
      });
    } else {
      outcomes.push({
        run_id: run.run_id,
        kind: 'liveness_unknown',
        status_code: EXEC2_CODE.EXEC_LIVENESS_UNKNOWN,
        user_text: EXEC2_TEXT[EXEC2_CODE.EXEC_LIVENESS_UNKNOWN],
        silently_absorbed: false,
      });
    }
  }

  const finalRead = readInsessionLedger(projectPath);
  if (finalRead.ok) {
    finalRead.ledger.adopted_client_event_ids = [
      ...new Set([
        ...(finalRead.ledger.adopted_client_event_ids || []),
        ...adopted_ids,
      ]),
    ];
    writeInsessionLedger(projectPath, finalRead.ledger);
  }

  return {
    ok: true,
    outcomes,
    adopted: outcomes.filter((o) => o.kind === 'adopted').length,
    named_dead: outcomes.filter((o) => o.kind === 'named_dead').length,
    named_missing: outcomes.filter((o) => o.kind === 'named_missing_handback')
      .length,
    silently_absorbed: false,
    producer: INSESSION_PRODUCER_ID,
  };
}

/**
 * Build run descriptors from the S14 ledger for openProjectPipeline stage 1.
 * @param {string} projectPath
 * @returns {object[]}
 */
export function listInsessionRunsForPipeline(projectPath) {
  const read = readInsessionLedger(projectPath);
  if (!read.ok || !read.ledger) return [];
  // Only non-terminal runs need Wave-13 lease sweep; terminal outcomes are
  // already durable from reconcileInSessionOrphans / kill / complete.
  return (read.ledger.runs || [])
    .filter((r) => r && r.terminal !== true)
    .map((r) => ({
      run_id: r.run_id,
      step_id: r.step_id,
      worktree: r.worktree,
      lease: r.lease,
      pid: r.pid,
      proc_create_time: r.proc_create_time,
      launch_intent: r.launch_intent,
      commission_id: r.commission_id,
      handback_expected: true,
      missing_handback:
        r.state === 'handback_missing' || r.missing_handback === true,
      parked: r.parked === true,
      source: 'insession',
    }));
}

// ── Install on Wave-11 seam ────────────────────────────────────────────────

/**
 * Register the in-session executor on executeCommission's resolution path.
 * @param {{ hooks?: InSessionProcessHooks, available?: boolean } & object} [opts]
 */
export function installInSessionExecutor(opts = {}) {
  if (opts.hooks) setInSessionProcessHooks(opts.hooks);
  setInSessionExecutor(
    (dossier, ctx) =>
      executeInSession(dossier, {
        ...opts,
        ...ctx,
        hooks: ctx.hooks || opts.hooks || _processHooks,
      }),
    { available: opts.available !== false },
  );
  return { ok: true, available: opts.available !== false, path: 'insession' };
}

/**
 * Unregister in-session executor + clear hooks + live table (tests).
 */
export function resetInSessionExecutor() {
  setInSessionExecutor(null, { available: false });
  resetInSessionProcessHooks();
  resetInSessionLiveTable();
}

// ── Anti-stub exec2 verdict (exactly like G4) ──────────────────────────────

/**
 * Evaluate observed evidence into exec2 verdict (pure).
 * Same three anti-stub clauses as G4:
 *   (a) cmdline names trio CLI entry
 *   (b) handback passes receipt-validate
 *   (c) (pid, proc_create_time) live then terminal with observation record
 *
 * @param {object} evidence
 */
export function evaluateExec2Evidence(evidence = {}) {
  const g4 = evaluateG4Evidence(evidence);
  // Explicit refuse of node -e canned JSON (same as G4)
  const fail_reasons = [...(g4.fail_reasons || [])];
  if (
    evidence.stub_launcher === true ||
    (Array.isArray(evidence.cmdline) &&
      evidence.cmdline.some((p) => String(p) === '-e'))
  ) {
    if (!fail_reasons.includes('cmdline_missing_trio_entry')) {
      // node -e already fails trio check; keep both for clarity when forced stub flag
    }
    if (evidence.stub_launcher === true && g4.verdict === 'PASS') {
      fail_reasons.push('stub_launcher_refused');
    }
  }
  const verdict =
    fail_reasons.length === 0 && g4.verdict === 'PASS' ? 'PASS' : 'FAIL';
  return {
    ...g4,
    verdict,
    fail_reasons: verdict === 'PASS' ? [] : fail_reasons.length ? fail_reasons : g4.fail_reasons,
    executor: 'insession',
    verdict_kind: 'exec2',
    anti_stub_clauses: {
      cmdline_names_trio_entry: g4.checks?.cmdline_names_trio_entry === true,
      receipt_validate_ok: g4.checks?.receipt_validate_ok === true,
      pid_create_time_live_then_terminal:
        g4.checks?.pid_and_create_time_live_then_terminal === true,
    },
  };
}

/**
 * @param {string} [root]
 */
export function exec2VerdictPath(root = DEFAULT_ROOT) {
  return path.join(root, EXEC2_VERDICT_REL);
}

/**
 * @param {string} [root]
 */
export function exec2EvidencePath(root = DEFAULT_ROOT) {
  return path.join(root, EXEC2_EVIDENCE_REL);
}

/**
 * @param {object} evidence
 * @param {{ root?: string }} [opts]
 */
export function writeExec2Evidence(evidence, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const outPath = exec2EvidencePath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const clean = { ...evidence };
  delete clean.commissionable;
  const payload = sanitizeEvidenceForShip(
    {
      ...clean,
      written_by: 'exec-insession.mjs',
      executor: 'insession',
      recorded_at: clean.recorded_at ?? new Date().toISOString(),
      contract_version: CONTRACT_VERSION,
    },
    root,
  );
  writeJsonIdempotentSync(outPath, payload);
  return outPath;
}

/**
 * @param {object} verdict
 * @param {{ root?: string }} [opts]
 */
export function writeExec2Verdict(verdict, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const outPath = exec2VerdictPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const payload = sanitizeEvidenceForShip(
    {
      verdict: verdict.verdict,
      path: verdict.path,
      pid: verdict.pid,
      proc_create_time: verdict.proc_create_time,
      handback_id: verdict.handback_id,
      evidence_paths: verdict.evidence_paths ?? [],
      recorded_at: verdict.recorded_at ?? new Date().toISOString(),
      fail_reasons: verdict.fail_reasons ?? [],
      checks: verdict.checks ?? {},
      anti_stub_clauses: verdict.anti_stub_clauses ?? null,
      contract_version: CONTRACT_VERSION,
      executor: 'insession',
      verdict_kind: 'exec2',
      written_by: 'exec-insession.mjs',
    },
    root,
  );
  writeJsonIdempotentSync(outPath, payload);
  return outPath;
}

/**
 * Evaluate + write both S8 artifacts.
 * @param {object} evidence
 * @param {{ root?: string }} [opts]
 */
export function recordExec2FromEvidence(evidence, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const evidencePath = writeExec2Evidence(evidence, { root });
  const verdict = evaluateExec2Evidence({
    ...evidence,
    evidence_paths: [
      ...(Array.isArray(evidence.evidence_paths) ? evidence.evidence_paths : []),
      evidencePath,
    ],
  });
  const verdictPath = writeExec2Verdict(
    {
      ...verdict,
      evidence_paths: [
        ...verdict.evidence_paths,
        evidencePath,
        exec2VerdictPath(root),
      ],
    },
    { root },
  );
  return { verdict, evidencePath, verdictPath };
}

/**
 * Collect evidence from a supervised in-session run worktree (like G4).
 * @param {object} args
 */
export function collectExec2EvidenceFromWorktree(args) {
  return {
    ...collectEvidenceFromWorktree(args),
    executor: 'insession',
  };
}

/**
 * Validate handback at contract path via receipt-validate (shared).
 * @param {string} worktree
 */
export function validateHandbackAtContractPath(worktree) {
  if (!isIngestable(worktree)) {
    return {
      ok: false,
      receipt_validate_ok: false,
      error: 'pair_not_ingestable',
    };
  }
  const read = readIngestableHandback(worktree);
  if (!read.ok) {
    return { ok: false, receipt_validate_ok: false, error: read.error };
  }
  const v = validateReceipt(read.handback);
  return {
    ok: v.ok === true,
    receipt_validate_ok: v.ok === true,
    handback_id: read.handback_id,
    client_event_id: read.client_event_id,
    handback_path: handbackJsonPath(worktree),
  };
}
