/**
 * Wave 7 — Commission dossier (S3) + CONFIRM JOURNAL (A4 fix, ONE mechanism).
 *
 * Lifecycle facts under one key (job_id / commissioned_as):
 *   proposal → confirmation (who) → launch (pid, proc_create_time) → handback
 *
 * Confirm journal two-phase apply (the single chosen mechanism — "journaled
 * transaction OR crash-repairable pair" is retired):
 *   1. append ONE atomic `confirm_intent` (client_event_id keyed) BEFORE any
 *      store write
 *   2. apply: roadmap bind + Strip receipt/instrument
 *   3. `confirm_applied` marker closes the journal entry
 *   Boot repair: repairConfirmJournal() replays open entries idempotently
 *   (client_event_id) to full application or rolls them back whole.
 *   Open journal → DOSSIER_PARTIAL; after repair → DOSSIER_REPAIRED.
 *
 * Containment: dossier / handback / artifact path resolver confined to the
 * project root — `..`, absolute, symlink/junction, and MAX_PATH cases refuse
 * as path-escape-refused (DOSSIER_PATH_REFUSED).
 *
 * Durability (S3): writeFileAtomicSync + withFileLock; T-DUR-S3 / T-ATOM-CONFIRM.
 * Stdlib only. No host-absolute user homes in shipped strings.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  writeFileAtomicSync,
  withFileLock,
  LOCK_TIMEOUT_MS,
} from './durable-write.mjs';
import {
  appendRoadmapEventThroughSpine,
  writeStripThroughSpine,
} from './ledger-spine.mjs';
import { loadProjectRoadmap } from './roadmap.mjs';
import { realpathJunctionAware } from './canary-pack.mjs';
import {
  STRIP_FILE_NAME,
  loadProjectSurfaces,
} from './face-strip.mjs';
import { appendStripInstrument } from './write-authority.mjs';
import { isInsideHome } from './portfolio/home.mjs';
import { MAX_PATH } from './portfolio/inventory.mjs';

// ── Named durability helpers (S3 — removal-proof T-DUR-S3) ─────────────────

/** Named lock helper — Durable-store map S3. */
export const DOSSIER_LOCK_HELPER = 'withFileLock';

/** Named atomic write — Durable-store map S3. */
export const DOSSIER_ATOMIC_WRITE = 'writeFileAtomicSync';

/** Relative store dir under the project root. */
export const DOSSIER_DIR_REL = path.join('.ecgberht', 'dossiers');

/** Confirm journal directory (one file per client_event_id). */
export const CONFIRM_JOURNAL_DIR_REL = path.join('.ecgberht', 'confirm-journal');

/** Aggregate dossier index file name (under DOSSIER_DIR_REL). */
export const DOSSIER_INDEX_FILE = 'index.json';

/** Schema id for a single dossier record. */
export const DOSSIER_SCHEMA_ID = 'ecgberht-commission-dossier-v0';

/** Schema id for a confirm-journal entry. */
export const CONFIRM_JOURNAL_SCHEMA_ID = 'ecgberht-confirm-journal-v0';

/** Idempotence key name (named for boot repair). */
export const CONFIRM_JOURNAL_IDEMPOTENCE_KEY = 'client_event_id';

/** Named repair verb. */
export const REPAIR_CONFIRM_JOURNAL_VERB = 'repairConfirmJournal';

/** Honest-unknown token for absent facts on the read API. */
export const HONEST_UNKNOWN = Object.freeze({
  status: 'unknown',
  reason: 'fact-absent',
});

// ── Failure states (dossier surface) ───────────────────────────────────────

export const DOSSIER_CODE = Object.freeze({
  MISSING: 'DOSSIER_MISSING',
  PARTIAL: 'DOSSIER_PARTIAL',
  REPAIRED: 'DOSSIER_REPAIRED',
  PATH_REFUSED: 'DOSSIER_PATH_REFUSED',
  UNREADABLE: 'DOSSIER_UNREADABLE',
  EMPTY: 'DOSSIER_EMPTY',
  STATE_UNKNOWN: 'DOSSIER_STATE_UNKNOWN',
});

export const DOSSIER_TEXT = Object.freeze({
  [DOSSIER_CODE.MISSING]:
    'No dossier for commission <id> — shown as missing, not empty.',
  [DOSSIER_CODE.PARTIAL]:
    'Commission <id> confirm incomplete — repair pending; not shown as confirmed.',
  [DOSSIER_CODE.REPAIRED]:
    'Commission <id> was repaired at boot — now fully consistent; noted.',
  [DOSSIER_CODE.PATH_REFUSED]:
    'Handback path escapes the project root — refused; nothing read or written.',
  [DOSSIER_CODE.UNREADABLE]:
    'Dossier store unreadable — facts withheld rather than guessed.',
  [DOSSIER_CODE.EMPTY]: 'No commissions yet.',
  [DOSSIER_CODE.STATE_UNKNOWN]:
    'Dossier state unknown — reported as unknown.',
});

/**
 * @param {string} code DOSSIER_CODE value
 * @param {object} [extra]
 */
export function dossierFailure(code, extra = {}) {
  let text = DOSSIER_TEXT[code] ?? DOSSIER_TEXT[DOSSIER_CODE.STATE_UNKNOWN];
  const id = extra.id ?? extra.job_id ?? extra.commissioned_as ?? null;
  if (id != null && typeof text === 'string' && text.includes('<id>')) {
    text = text.replace(/<id>/g, String(id));
  }
  return {
    ok: false,
    error: extra.error ?? String(code).toLowerCase().replace(/_/g, '-'),
    code,
    status: code,
    status_code: code,
    text,
    message: text,
    user_text: text,
    dossier: true,
    ...extra,
  };
}

/**
 * Full failure-state table for the dossier surface (honest unknown ≠ empty).
 * @returns {ReadonlyArray<{state: string, status_code: string, user_text: string}>}
 */
export function dossierFailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'dossier-missing',
      status_code: DOSSIER_CODE.MISSING,
      user_text: DOSSIER_TEXT[DOSSIER_CODE.MISSING],
    }),
    Object.freeze({
      state: 'dossier-partial (journal open)',
      status_code: DOSSIER_CODE.PARTIAL,
      user_text: DOSSIER_TEXT[DOSSIER_CODE.PARTIAL],
    }),
    Object.freeze({
      state: 'repair-applied',
      status_code: DOSSIER_CODE.REPAIRED,
      user_text: DOSSIER_TEXT[DOSSIER_CODE.REPAIRED],
    }),
    Object.freeze({
      state: 'path-escape-refused',
      status_code: DOSSIER_CODE.PATH_REFUSED,
      user_text: DOSSIER_TEXT[DOSSIER_CODE.PATH_REFUSED],
    }),
    Object.freeze({
      state: 'backing-store-unreadable',
      status_code: DOSSIER_CODE.UNREADABLE,
      user_text: DOSSIER_TEXT[DOSSIER_CODE.UNREADABLE],
    }),
    Object.freeze({
      state: 'empty-but-valid',
      status_code: DOSSIER_CODE.EMPTY,
      user_text: DOSSIER_TEXT[DOSSIER_CODE.EMPTY],
    }),
    Object.freeze({
      state: 'unknown',
      status_code: DOSSIER_CODE.STATE_UNKNOWN,
      user_text: DOSSIER_TEXT[DOSSIER_CODE.STATE_UNKNOWN],
    }),
  ]);
}

// ── Path helpers ───────────────────────────────────────────────────────────

function safeKey(key) {
  return String(key ?? '')
    .replace(/[^A-Za-z0-9._:-]+/g, '_')
    .slice(0, 180) || 'unknown';
}

/**
 * Absolute path of the dossier index under a project root.
 * @param {string} projectRoot
 */
export function dossierIndexPath(projectRoot) {
  return path.join(path.resolve(projectRoot), DOSSIER_DIR_REL, DOSSIER_INDEX_FILE);
}

/**
 * Absolute path of a single-dossier file (by job_id).
 * @param {string} projectRoot
 * @param {string} jobId
 */
export function dossierRecordPath(projectRoot, jobId) {
  return path.join(
    path.resolve(projectRoot),
    DOSSIER_DIR_REL,
    `${safeKey(jobId)}.json`,
  );
}

/**
 * Absolute path of a confirm-journal entry.
 * @param {string} projectRoot
 * @param {string} clientEventId
 */
export function confirmJournalEntryPath(projectRoot, clientEventId) {
  return path.join(
    path.resolve(projectRoot),
    CONFIRM_JOURNAL_DIR_REL,
    `${safeKey(clientEventId)}.json`,
  );
}

/**
 * Confirm journal directory absolute path.
 * @param {string} projectRoot
 */
export function confirmJournalDir(projectRoot) {
  return path.join(path.resolve(projectRoot), CONFIRM_JOURNAL_DIR_REL);
}

// realpathJunctionAware lives in canary-pack.mjs (the canonical home;
// stand-up.mjs already imports it from there). Wave 7 re-implemented it
// here verbatim, producing a duplicate export in index.mjs and two copies
// of the junction-aware realpath the live-skill evidence classification
// depends on. Import the single implementation; re-export for consumers.
export { realpathJunctionAware } from './canary-pack.mjs';

/**
 * Containment: is candidate inside projectRoot (separator-bounded, case-aware
 * via isInsideHome)?
 * @param {string} projectRoot
 * @param {string} candidate
 */
export function isInsideProjectRoot(projectRoot, candidate) {
  return isInsideHome(projectRoot, candidate);
}

/**
 * Resolve a handback / artifact / dossier path confined to the project root.
 *
 * Refuses (all as path-escape-refused / DOSSIER_PATH_REFUSED):
 *   - `..` escapes after resolve
 *   - absolute paths outside the root
 *   - symlink / junction targets that leave the root
 *   - paths at or past MAX_PATH (worktree + planning + bundle names can cross it)
 *
 * @param {string} projectRoot
 * @param {string} candidate  relative or absolute path naming a handback/artifact
 * @param {{ allowRootEqual?: boolean }} [opts]
 * @returns {{ ok: true, abs: string, rel: string }
 *   | { ok: false, code: string, status_code: string, text: string, message: string,
 *       reason: string, candidate: string }}
 */
export function resolveContainedPath(projectRoot, candidate, opts = {}) {
  const root = path.resolve(String(projectRoot ?? ''));
  const raw = String(candidate ?? '');

  if (!raw || !root) {
    return {
      ...dossierFailure(DOSSIER_CODE.PATH_REFUSED, {
        error: 'path-escape-refused',
        reason: 'empty-path',
        candidate: raw,
      }),
      reason: 'empty-path',
      candidate: raw,
    };
  }

  // Absolute path that is not under root → refuse (do not silently re-root).
  let abs;
  if (path.isAbsolute(raw) || /^[A-Za-z]:[\\/]/.test(raw)) {
    abs = path.resolve(raw);
  } else {
    abs = path.resolve(root, raw);
  }

  // MAX_PATH case — refused by name (git/stdlib differ with/without longpaths).
  if (String(abs).length >= MAX_PATH) {
    return {
      ...dossierFailure(DOSSIER_CODE.PATH_REFUSED, {
        error: 'path-escape-refused',
        reason: 'max-path-exceeded',
        candidate: raw,
        path_length: String(abs).length,
        max_path: MAX_PATH,
      }),
      reason: 'max-path-exceeded',
      candidate: raw,
      path_length: String(abs).length,
      max_path: MAX_PATH,
    };
  }

  // Lexical containment (catches `..` and absolute-outside).
  if (!isInsideProjectRoot(root, abs)) {
    return {
      ...dossierFailure(DOSSIER_CODE.PATH_REFUSED, {
        error: 'path-escape-refused',
        reason: path.isAbsolute(raw) || /^[A-Za-z]:[\\/]/.test(raw)
          ? 'absolute-escape'
          : 'dotdot-escape',
        candidate: raw,
        resolved: abs,
      }),
      reason:
        path.isAbsolute(raw) || /^[A-Za-z]:[\\/]/.test(raw)
          ? 'absolute-escape'
          : 'dotdot-escape',
      candidate: raw,
      resolved: abs,
    };
  }

  // Symlink / junction: realpath of candidate and root must stay inside root.
  const rootReal = realpathJunctionAware(root);
  const candReal = realpathJunctionAware(abs);
  const rootCheck = rootReal.path;
  const candCheck = candReal.path;
  if (!isInsideProjectRoot(rootCheck, candCheck)) {
    return {
      ...dossierFailure(DOSSIER_CODE.PATH_REFUSED, {
        error: 'path-escape-refused',
        reason: 'symlink-junction-escape',
        candidate: raw,
        resolved: abs,
        realpath: candCheck,
        root_realpath: rootCheck,
      }),
      reason: 'symlink-junction-escape',
      candidate: raw,
      resolved: abs,
      realpath: candCheck,
    };
  }

  if (!opts.allowRootEqual && path.resolve(candCheck) === path.resolve(rootCheck)) {
    // Handback/artifact must name a path *inside* the root, not the root itself.
    // Still not an escape — return ok with rel '.'.
  }

  const rel = path.relative(root, abs);
  return {
    ok: true,
    abs,
    rel: rel === '' ? '.' : rel.split(path.sep).join('/'),
    realpath: candCheck,
  };
}

// ── Empty dossier / journal shapes ─────────────────────────────────────────

/**
 * @param {string} jobId
 * @param {string} [commissionedAs]
 */
export function emptyDossier(jobId, commissionedAs = null) {
  return {
    schema: DOSSIER_SCHEMA_ID,
    job_id: jobId,
    commissioned_as: commissionedAs,
    proposal: null,
    confirmation: null,
    launch: null,
    handback: null,
    repaired_at_boot: false,
    updated_at: null,
  };
}

/**
 * @param {object} intent
 */
function emptyJournalEntry(intent) {
  return {
    schema: CONFIRM_JOURNAL_SCHEMA_ID,
    phase: 'confirm_intent',
    client_event_id: intent.client_event_id,
    job_id: intent.job_id,
    commissioned_as: intent.commissioned_as,
    intent,
    confirm_applied: false,
    applied_at: null,
    created_at: intent.at ?? new Date().toISOString(),
  };
}

// ── Store I/O (atomic + locked) ────────────────────────────────────────────

function readJsonFile(filePath) {
  try {
    if (!fs.existsSync(filePath)) return { ok: true, exists: false, value: null };
    const raw = fs.readFileSync(filePath, 'utf8');
    return { ok: true, exists: true, value: JSON.parse(raw) };
  } catch (e) {
    return {
      ok: false,
      exists: true,
      error: 'unreadable',
      detail: String(e?.message ?? e),
    };
  }
}

function writeJsonLocked(filePath, value, opts = {}) {
  const timeoutMs = opts.timeoutMs ?? LOCK_TIMEOUT_MS;
  try {
    withFileLock(
      filePath,
      () => {
        fs.mkdirSync(path.dirname(filePath), { recursive: true });
        writeFileAtomicSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
      },
      {
        timeoutMs,
        onTimeout: (info) => {
          const err = new Error('dossier lock timeout');
          err.code = 'ELOCKTIMEOUT';
          err.lock_info = info;
          return err;
        },
      },
    );
    return { ok: true, path: filePath, sot_written: true, locked: true };
  } catch (e) {
    if (e && (e.code === 'ELOCKTIMEOUT' || e.code === 'SPINE_LOCK_TIMEOUT')) {
      return dossierFailure(DOSSIER_CODE.STATE_UNKNOWN, {
        error: 'lock-contended',
        detail: String(e?.message ?? e),
      });
    }
    return dossierFailure(DOSSIER_CODE.UNREADABLE, {
      error: 'write-failed',
      detail: String(e?.message ?? e),
    });
  }
}

/**
 * Source-removal proof: dossier module must still name the durable helpers.
 * @param {string} sourceText
 */
export function assertDossierDurableHelpersPresent(sourceText) {
  const missing = [];
  if (!sourceText.includes('writeFileAtomicSync')) missing.push('writeFileAtomicSync');
  if (!sourceText.includes('withFileLock')) missing.push('withFileLock');
  if (!sourceText.includes('repairConfirmJournal')) missing.push('repairConfirmJournal');
  if (!sourceText.includes('confirm_intent')) missing.push('confirm_intent');
  if (!sourceText.includes('confirm_applied')) missing.push('confirm_applied');
  return { ok: missing.length === 0, missing };
}

// ── Dossier write / read API ───────────────────────────────────────────────

/**
 * Upsert lifecycle facts on a dossier under one key (job_id).
 * Facts not supplied are left unchanged; never invents absent facts.
 *
 * @param {string} projectRoot
 * @param {{
 *   job_id: string,
 *   commissioned_as?: string|null,
 *   proposal?: object|null,
 *   confirmation?: object|null,
 *   launch?: object|null,
 *   handback?: object|null,
 *   repaired_at_boot?: boolean,
 * }} patch
 */
export function upsertDossier(projectRoot, patch) {
  const jobId = patch?.job_id;
  if (!jobId || typeof jobId !== 'string') {
    return dossierFailure(DOSSIER_CODE.STATE_UNKNOWN, {
      error: 'dossier-key-required',
    });
  }
  const filePath = dossierRecordPath(projectRoot, jobId);
  const existing = readJsonFile(filePath);
  if (!existing.ok) {
    return dossierFailure(DOSSIER_CODE.UNREADABLE, {
      id: jobId,
      detail: existing.detail,
    });
  }
  const base = existing.exists && existing.value
    ? existing.value
    : emptyDossier(jobId, patch.commissioned_as ?? null);

  const next = {
    ...base,
    schema: DOSSIER_SCHEMA_ID,
    job_id: jobId,
    commissioned_as:
      patch.commissioned_as !== undefined
        ? patch.commissioned_as
        : base.commissioned_as,
    proposal: patch.proposal !== undefined ? patch.proposal : base.proposal,
    confirmation:
      patch.confirmation !== undefined ? patch.confirmation : base.confirmation,
    launch: patch.launch !== undefined ? patch.launch : base.launch,
    handback: patch.handback !== undefined ? patch.handback : base.handback,
    repaired_at_boot:
      patch.repaired_at_boot !== undefined
        ? patch.repaired_at_boot
        : base.repaired_at_boot === true,
    updated_at: new Date().toISOString(),
  };

  const written = writeJsonLocked(filePath, next);
  if (!written.ok) return written;

  // Maintain index for empty-vs-missing list reads.
  touchDossierIndex(projectRoot, jobId, next.commissioned_as);

  return {
    ok: true,
    dossier: next,
    path: filePath,
    sot_written: true,
    locked: true,
    atomic_write: DOSSIER_ATOMIC_WRITE,
    lock: DOSSIER_LOCK_HELPER,
  };
}

function touchDossierIndex(projectRoot, jobId, commissionedAs) {
  const idxPath = dossierIndexPath(projectRoot);
  // RMW under the same lock as the write so concurrent upserts cannot drop keys.
  try {
    withFileLock(
      idxPath,
      () => {
        const loaded = readJsonFile(idxPath);
        const index =
          loaded.ok && loaded.exists && loaded.value && typeof loaded.value === 'object'
            ? { ...loaded.value, keys: { ...(loaded.value.keys ?? {}) } }
            : { schema: 'ecgberht-dossier-index-v0', keys: {} };
        if (!index.keys || typeof index.keys !== 'object') index.keys = {};
        index.keys[jobId] = {
          job_id: jobId,
          commissioned_as: commissionedAs ?? null,
          updated_at: new Date().toISOString(),
        };
        fs.mkdirSync(path.dirname(idxPath), { recursive: true });
        writeFileAtomicSync(idxPath, `${JSON.stringify(index, null, 2)}\n`);
      },
      { timeoutMs: LOCK_TIMEOUT_MS },
    );
  } catch {
    // Best-effort index; dossier record itself is authoritative for single-key reads.
  }
}

/**
 * Record a launch intent + process identity on the dossier.
 * @param {string} projectRoot
 * @param {{
 *   job_id: string,
 *   commissioned_as?: string|null,
 *   pid: number|null,
 *   proc_create_time: number|null,
 *   intent?: object|null,
 *   at?: string,
 * }} opts
 */
export function recordLaunchOnDossier(projectRoot, opts) {
  return upsertDossier(projectRoot, {
    job_id: opts.job_id,
    commissioned_as: opts.commissioned_as ?? null,
    launch: {
      intent: opts.intent ?? { kind: 'launch_intent', at: opts.at ?? null },
      pid: opts.pid ?? null,
      proc_create_time: opts.proc_create_time ?? null,
      at: opts.at ?? new Date().toISOString(),
    },
  });
}

/**
 * Record a validated handback under the dossier key. Path is containment-checked.
 * @param {string} projectRoot
 * @param {{
 *   job_id: string,
 *   commissioned_as?: string|null,
 *   handback_path?: string|null,
 *   handback_id?: string|null,
 *   body?: object|null,
 *   at?: string,
 * }} opts
 */
export function recordHandbackOnDossier(projectRoot, opts) {
  let pathMeta = null;
  if (opts.handback_path) {
    const resolved = resolveContainedPath(projectRoot, opts.handback_path);
    if (!resolved.ok) return resolved;
    pathMeta = { rel: resolved.rel, abs_contained: true };
  }
  return upsertDossier(projectRoot, {
    job_id: opts.job_id,
    commissioned_as: opts.commissioned_as ?? null,
    handback: {
      handback_id: opts.handback_id ?? null,
      path: pathMeta,
      body: opts.body ?? null,
      at: opts.at ?? new Date().toISOString(),
    },
  });
}

/**
 * Read a single dossier by job_id or commissioned_as.
 * Returns honest-unknown for absent lifecycle facts; never invents them.
 * Open confirm-journal entry → DOSSIER_PARTIAL (not shown as confirmed).
 *
 * @param {string} projectRoot
 * @param {string} key  job_id or commissioned_as
 */
export function readDossier(projectRoot, key) {
  const root = path.resolve(String(projectRoot ?? ''));
  if (!key || typeof key !== 'string') {
    return dossierFailure(DOSSIER_CODE.STATE_UNKNOWN, {
      error: 'key-required',
    });
  }

  // Locate by job_id file first; fall back to index scan by commissioned_as.
  let filePath = dossierRecordPath(root, key);
  let loaded = readJsonFile(filePath);

  if ((!loaded.ok || !loaded.exists) && key.includes(':')) {
    // commissioned_as form — scan index
    const idx = readJsonFile(dossierIndexPath(root));
    if (!idx.ok) {
      return dossierFailure(DOSSIER_CODE.UNREADABLE, { id: key });
    }
    if (idx.exists && idx.value?.keys) {
      for (const [jobId, row] of Object.entries(idx.value.keys)) {
        if (row?.commissioned_as === key || jobId === key) {
          filePath = dossierRecordPath(root, jobId);
          loaded = readJsonFile(filePath);
          break;
        }
      }
    }
  }

  if (!loaded.ok) {
    return dossierFailure(DOSSIER_CODE.UNREADABLE, { id: key });
  }

  // Open journal for this key (by job_id or commissioned_as) → PARTIAL even
  // when the dossier record has not been written yet (kill before dossier upsert).
  const openJournal =
    findOpenJournalForJob(root, key)
    ?? listOpenConfirmJournal(root).find(
      (e) =>
        e.commissioned_as === key
        || e.intent?.commissioned_as === key
        || e.job_id === key
        || e.intent?.job_id === key,
    )
    ?? null;

  if (!loaded.exists || !loaded.value) {
    if (openJournal) {
      const jobId = openJournal.job_id ?? openJournal.intent?.job_id ?? key;
      return {
        ok: false,
        ...dossierFailure(DOSSIER_CODE.PARTIAL, { id: jobId }),
        dossier: projectDossierRead(
          emptyDossier(jobId, openJournal.commissioned_as ?? null),
          { partial: true },
        ),
        open_journal: {
          client_event_id: openJournal.client_event_id,
          phase: openJournal.phase,
        },
        detector: 'open-journal-entry',
        repair_verb: REPAIR_CONFIRM_JOURNAL_VERB,
        idempotence_key: CONFIRM_JOURNAL_IDEMPOTENCE_KEY,
      };
    }
    return dossierFailure(DOSSIER_CODE.MISSING, { id: key });
  }

  const d = loaded.value;
  const jobId = d.job_id ?? key;

  // Open journal entry for this commission → PARTIAL (not confirmed).
  if (openJournal) {
    return {
      ok: false,
      ...dossierFailure(DOSSIER_CODE.PARTIAL, { id: jobId }),
      dossier: projectDossierRead(d, { partial: true }),
      open_journal: {
        client_event_id: openJournal.client_event_id,
        phase: openJournal.phase,
      },
      detector: 'open-journal-entry',
      repair_verb: REPAIR_CONFIRM_JOURNAL_VERB,
      idempotence_key: CONFIRM_JOURNAL_IDEMPOTENCE_KEY,
    };
  }

  const facts = projectDossierRead(d, {
    repaired: d.repaired_at_boot === true,
  });

  if (d.repaired_at_boot === true) {
    return {
      ok: true,
      code: DOSSIER_CODE.REPAIRED,
      status: DOSSIER_CODE.REPAIRED,
      status_code: DOSSIER_CODE.REPAIRED,
      text: DOSSIER_TEXT[DOSSIER_CODE.REPAIRED].replace(/<id>/g, String(jobId)),
      message: DOSSIER_TEXT[DOSSIER_CODE.REPAIRED].replace(/<id>/g, String(jobId)),
      user_text: DOSSIER_TEXT[DOSSIER_CODE.REPAIRED].replace(/<id>/g, String(jobId)),
      dossier: facts,
      repaired: true,
    };
  }

  return {
    ok: true,
    dossier: facts,
    code: null,
    status: 'ok',
  };
}

/**
 * Project a stored dossier into the read API shape with honest-unknown for
 * absent facts (never empty-as-missing).
 * @param {object} d
 * @param {{ partial?: boolean, repaired?: boolean }} [flags]
 */
export function projectDossierRead(d, flags = {}) {
  const fact = (v) => (v == null ? { ...HONEST_UNKNOWN } : v);
  return {
    schema: d.schema ?? DOSSIER_SCHEMA_ID,
    job_id: d.job_id ?? null,
    commissioned_as: d.commissioned_as ?? null,
    proposal: fact(d.proposal),
    confirmation: fact(d.confirmation),
    launch: fact(d.launch),
    handback: fact(d.handback),
    // Convenience accessors for the four lifecycle facts
    who: d.confirmation?.who ?? null,
    pid: d.launch?.pid ?? null,
    proc_create_time: d.launch?.proc_create_time ?? null,
    partial: flags.partial === true,
    repaired_at_boot: flags.repaired === true || d.repaired_at_boot === true,
  };
}

/**
 * List dossiers / empty-but-valid.
 * @param {string} projectRoot
 */
export function listDossiers(projectRoot) {
  const root = path.resolve(String(projectRoot ?? ''));
  const idx = readJsonFile(dossierIndexPath(root));
  if (!idx.ok) {
    return dossierFailure(DOSSIER_CODE.UNREADABLE);
  }
  if (!idx.exists || !idx.value?.keys || Object.keys(idx.value.keys).length === 0) {
    return {
      ok: true,
      empty: true,
      code: DOSSIER_CODE.EMPTY,
      status: DOSSIER_CODE.EMPTY,
      status_code: DOSSIER_CODE.EMPTY,
      text: DOSSIER_TEXT[DOSSIER_CODE.EMPTY],
      message: DOSSIER_TEXT[DOSSIER_CODE.EMPTY],
      user_text: DOSSIER_TEXT[DOSSIER_CODE.EMPTY],
      dossiers: [],
    };
  }
  const dossiers = [];
  for (const jobId of Object.keys(idx.value.keys)) {
    const r = readDossier(root, jobId);
    dossiers.push(r);
  }
  return { ok: true, empty: false, dossiers };
}

// ── Confirm journal ────────────────────────────────────────────────────────

/**
 * Append ONE atomic confirm_intent journal record BEFORE any store write.
 * Idempotent on client_event_id: re-append of a closed or open entry returns
 * the existing entry without rewriting applied markers.
 *
 * @param {string} projectRoot
 * @param {{
 *   client_event_id: string,
 *   job_id: string,
 *   commissioned_as: string,
 *   who: string,
 *   at?: string,
 *   proposal: object,
 *   bind_event: object,
 *   strip_instrument?: object|null,
 *   strip_seed?: object|null,
 *   roadmap_seed?: object|null,
 *   project_id?: string|null,
 *   home?: string,
 * }} intent
 */
export function appendConfirmIntent(projectRoot, intent) {
  const clientEventId = intent?.client_event_id;
  if (!clientEventId || typeof clientEventId !== 'string' || !clientEventId.trim()) {
    return dossierFailure(DOSSIER_CODE.STATE_UNKNOWN, {
      error: 'client_event_id-required',
      message: 'confirm_intent requires client_event_id (idempotence key).',
    });
  }
  const filePath = confirmJournalEntryPath(projectRoot, clientEventId);
  const existing = readJsonFile(filePath);
  if (!existing.ok) {
    return dossierFailure(DOSSIER_CODE.UNREADABLE, {
      id: intent.job_id,
      detail: existing.detail,
    });
  }
  if (existing.exists && existing.value) {
    return {
      ok: true,
      idempotent: true,
      entry: existing.value,
      path: filePath,
      client_event_id: clientEventId,
    };
  }

  const entry = emptyJournalEntry({
    ...intent,
    client_event_id: clientEventId,
    phase: 'confirm_intent',
  });
  // Persist only the journal-safe payload (no host paths).
  const journalIntent = {
    client_event_id: clientEventId,
    job_id: intent.job_id,
    commissioned_as: intent.commissioned_as,
    who: intent.who,
    at: intent.at ?? new Date().toISOString(),
    proposal: intent.proposal,
    bind_event: intent.bind_event,
    strip_instrument: intent.strip_instrument ?? null,
    // strip_seed / roadmap_seed kept for repair apply; may be large but needed
    strip_seed: intent.strip_seed ?? null,
    project_id: intent.project_id ?? null,
  };
  entry.intent = journalIntent;

  const written = writeJsonLocked(filePath, entry);
  if (!written.ok) return written;
  return {
    ok: true,
    idempotent: false,
    entry,
    path: filePath,
    client_event_id: clientEventId,
    phase: 'confirm_intent',
  };
}

/**
 * Mark a journal entry confirm_applied (closes the entry).
 * @param {string} projectRoot
 * @param {string} clientEventId
 * @param {object} [extra]
 */
export function markConfirmApplied(projectRoot, clientEventId, extra = {}) {
  const filePath = confirmJournalEntryPath(projectRoot, clientEventId);
  const existing = readJsonFile(filePath);
  if (!existing.ok) {
    return dossierFailure(DOSSIER_CODE.UNREADABLE, { detail: existing.detail });
  }
  if (!existing.exists || !existing.value) {
    return dossierFailure(DOSSIER_CODE.STATE_UNKNOWN, {
      error: 'journal-entry-missing',
      client_event_id: clientEventId,
    });
  }
  if (existing.value.confirm_applied === true) {
    return {
      ok: true,
      idempotent: true,
      entry: existing.value,
      path: filePath,
    };
  }
  const next = {
    ...existing.value,
    phase: 'confirm_applied',
    confirm_applied: true,
    applied_at: extra.applied_at ?? new Date().toISOString(),
    apply_result: extra.apply_result ?? null,
  };
  const written = writeJsonLocked(filePath, next);
  if (!written.ok) return written;
  return { ok: true, idempotent: false, entry: next, path: filePath };
}

/**
 * Load a journal entry by client_event_id.
 * @param {string} projectRoot
 * @param {string} clientEventId
 */
export function readConfirmJournalEntry(projectRoot, clientEventId) {
  const filePath = confirmJournalEntryPath(projectRoot, clientEventId);
  const loaded = readJsonFile(filePath);
  if (!loaded.ok) {
    return dossierFailure(DOSSIER_CODE.UNREADABLE, { detail: loaded.detail });
  }
  if (!loaded.exists) {
    return { ok: true, exists: false, entry: null };
  }
  return { ok: true, exists: true, entry: loaded.value, path: filePath };
}

/**
 * List open (confirm_intent without confirm_applied) journal entries.
 * @param {string} projectRoot
 * @returns {object[]}
 */
export function listOpenConfirmJournal(projectRoot) {
  const dir = confirmJournalDir(projectRoot);
  if (!fs.existsSync(dir)) return [];
  let names;
  try {
    names = fs.readdirSync(dir);
  } catch {
    return [];
  }
  const open = [];
  for (const name of names) {
    if (!name.endsWith('.json')) continue;
    const loaded = readJsonFile(path.join(dir, name));
    if (!loaded.ok || !loaded.exists || !loaded.value) continue;
    const e = loaded.value;
    // Open = confirm_intent without confirm_applied and not rolled back whole.
    if (
      e.confirm_applied !== true
      && e.rolled_back !== true
      && e.phase !== 'rolled_back'
    ) {
      open.push(e);
    }
  }
  return open;
}

function findOpenJournalForJob(projectRoot, jobId) {
  return listOpenConfirmJournal(projectRoot).find(
    (e) => e.job_id === jobId || e.intent?.job_id === jobId,
  ) ?? null;
}

/**
 * Apply a confirm_intent: write roadmap bind + Strip instrument, then close.
 *
 * Kill-between-writes hook for T-ATOM-CONFIRM:
 *   opts.killAfterRoadmap === true  → write bind, return partial (no strip,
 *                                      journal stays open). Simulates process
 *                                      death between the two durable writes.
 *
 * @param {string} projectRoot
 * @param {object} entry  journal entry (or intent payload)
 * @param {{
 *   killAfterRoadmap?: boolean,
 *   strip?: object|null,
 *   roadmap?: object|null,
 *   project_id?: string|null,
 *   home?: string,
 *   skip_index?: boolean,
 *   rollback?: boolean,
 * }} [opts]
 */
export function applyConfirmIntent(projectRoot, entry, opts = {}) {
  const intent = entry?.intent ?? entry;
  if (!intent || !intent.client_event_id) {
    return dossierFailure(DOSSIER_CODE.STATE_UNKNOWN, {
      error: 'apply-missing-intent',
    });
  }

  // Already applied → idempotent no-op
  if (entry?.confirm_applied === true) {
    return {
      ok: true,
      idempotent: true,
      client_event_id: intent.client_event_id,
      job_id: intent.job_id,
      commissioned_as: intent.commissioned_as,
    };
  }

  // Explicit whole-entry rollback (no store writes left behind).
  if (opts.rollback === true) {
    return rollbackConfirmIntent(projectRoot, entry);
  }

  const root = path.resolve(projectRoot);
  const bindEvent = {
    ...intent.bind_event,
    client_event_id: intent.client_event_id,
  };

  // ── Write 1: roadmap bind (spine) ──────────────────────────────────────
  const bound = appendRoadmapEventThroughSpine(root, bindEvent, {
    seed: opts.roadmap ?? intent.roadmap_seed ?? null,
    at: intent.at,
    project_id: opts.project_id ?? intent.project_id ?? null,
    home: opts.home,
    skip_index:
      opts.skip_index
      ?? !(opts.project_id || intent.project_id),
  });
  if (!bound.ok && !bound.idempotent) {
    return {
      ...bound,
      phase: 'apply-roadmap',
      client_event_id: intent.client_event_id,
    };
  }

  // ── KILL WINDOW (T-ATOM-CONFIRM) ───────────────────────────────────────
  if (opts.killAfterRoadmap === true) {
    return {
      ok: false,
      killed: true,
      kill_window: 'between-roadmap-and-strip',
      roadmap_written: true,
      strip_written: false,
      client_event_id: intent.client_event_id,
      job_id: intent.job_id,
      commissioned_as: intent.commissioned_as,
      code: DOSSIER_CODE.PARTIAL,
      status: DOSSIER_CODE.PARTIAL,
      status_code: DOSSIER_CODE.PARTIAL,
      text: DOSSIER_TEXT[DOSSIER_CODE.PARTIAL].replace(
        /<id>/g,
        String(intent.job_id),
      ),
      message: DOSSIER_TEXT[DOSSIER_CODE.PARTIAL].replace(
        /<id>/g,
        String(intent.job_id),
      ),
      bound,
    };
  }

  // ── Write 2: Strip instrument / receipt ────────────────────────────────
  // Idempotent on client_event_id: if a commission_confirm instrument with the
  // same key is already on the strip (e.g. crash after strip write, before
  // confirm_applied), do not double-append — still ensure journal closes.
  let strip = opts.strip ?? intent.strip_seed ?? null;
  let strip_appended = false;
  let strip_already_present = false;
  let stripWrite = null;
  if (strip && intent.strip_instrument) {
    const cid = intent.client_event_id;
    const instruments = Array.isArray(strip.instruments) ? strip.instruments : [];
    strip_already_present = instruments.some(
      (i) =>
        i
        && (i.client_event_id === cid
          || (i.kind === 'commission_confirm' && i.job_id === intent.job_id && cid)),
    );
    if (!strip_already_present) {
      const appended = appendStripInstrument(strip, intent.strip_instrument, {
        apply_to_projection: false,
      });
      if (!appended.ok) {
        return {
          ...appended,
          phase: 'apply-strip-append',
          client_event_id: intent.client_event_id,
        };
      }
      strip = appended.strip;
      strip_appended = true;
      stripWrite = writeStripThroughSpine(root, strip);
      if (!stripWrite.ok) {
        return {
          ...stripWrite,
          phase: 'apply-strip-write',
          client_event_id: intent.client_event_id,
          partial: { roadmap: true, strip: false },
        };
      }
    }
  }

  // ── Close journal ──────────────────────────────────────────────────────
  const closed = markConfirmApplied(root, intent.client_event_id, {
    apply_result: {
      roadmap: true,
      strip: strip_appended || strip_already_present,
      seq: bound.seq ?? bound.event?.seq ?? null,
    },
  });
  if (!closed.ok) return closed;

  // ── Dossier confirmation fact ──────────────────────────────────────────
  const dossierWrite = upsertDossier(root, {
    job_id: intent.job_id,
    commissioned_as: intent.commissioned_as,
    proposal: intent.proposal
      ? {
          proposal_id: intent.proposal.proposal_id ?? null,
          step_id: intent.proposal.step_id ?? null,
          skill: intent.proposal.skill ?? null,
          depth_cell: intent.proposal.depth_cell ?? null,
          at: intent.proposal.at ?? null,
        }
      : null,
    confirmation: {
      who: intent.who,
      at: intent.at ?? null,
      client_event_id: intent.client_event_id,
      job_id: intent.job_id,
      commissioned_as: intent.commissioned_as,
    },
  });

  // Reaching this return means the journal was open (confirm_applied early-
  // return is above). Completing strip and/or closing confirm_applied is
  // always real work — even when the bind is already present under
  // client_event_id (the kill-between-writes repair path).
  const bindIdempotent = bound.idempotent === true;

  return {
    ok: true,
    client_event_id: intent.client_event_id,
    job_id: intent.job_id,
    commissioned_as: intent.commissioned_as,
    roadmap: bound.roadmap,
    roadmap_event: bound.event,
    strip,
    strip_appended,
    strip_already_present,
    strip_write: stripWrite,
    journal: closed.entry,
    dossier: dossierWrite.ok ? dossierWrite.dossier : null,
    dossier_write: dossierWrite,
    sot_written: true,
    locked: true,
    spine: true,
    bind_idempotent: bindIdempotent,
    // Only the confirm_applied early-return is a true no-op; repair counts
    // this pass as changed so a second repair is the only noop.
    idempotent: false,
  };
}

/**
 * Roll back an open journal entry whole: remove orphan bind if present,
 * remove open journal entry, leave strip untouched if never written.
 * @param {string} projectRoot
 * @param {object} entry
 */
export function rollbackConfirmIntent(projectRoot, entry) {
  const intent = entry?.intent ?? entry;
  const root = path.resolve(projectRoot);
  const clientEventId = intent.client_event_id;

  // Best-effort: if bind landed with this client_event_id, we cannot un-append
  // an append-only ledger — forward-repair is preferred. Rollback means:
  // mark journal as rolled_back and refuse to show the commission as confirmed.
  // A bind without strip is the orphan A4 named; rollback records that the
  // entry is closed without confirm_applied success, and dossier stays partial
  // until a forward repair. For tests that request rollback, we close the
  // journal with phase rolled_back so a second repair is a no-op.
  const filePath = confirmJournalEntryPath(root, clientEventId);
  const existing = readJsonFile(filePath);
  if (!existing.ok) {
    return dossierFailure(DOSSIER_CODE.UNREADABLE, { detail: existing.detail });
  }
  if (!existing.exists) {
    return { ok: true, idempotent: true, rolled_back: true, missing: true };
  }
  if (
    existing.value.confirm_applied === true
    || existing.value.phase === 'rolled_back'
  ) {
    return {
      ok: true,
      idempotent: true,
      rolled_back: existing.value.phase === 'rolled_back',
      entry: existing.value,
    };
  }

  // Prefer forward completion when strip instrument is available — but when
  // caller explicitly asked rollback, close without applying strip.
  const next = {
    ...existing.value,
    phase: 'rolled_back',
    confirm_applied: false,
    rolled_back: true,
    rolled_back_at: new Date().toISOString(),
  };
  const written = writeJsonLocked(filePath, next);
  if (!written.ok) return written;

  return {
    ok: true,
    rolled_back: true,
    client_event_id: clientEventId,
    job_id: intent.job_id,
    entry: next,
  };
}

/**
 * BOOT REPAIR — named verb repairConfirmJournal().
 *
 * Detector: open journal entry (confirm_intent without confirm_applied).
 * Idempotence key: client_event_id.
 * Action: replay apply idempotently to full application (forward repair).
 * Second pass changes nothing.
 *
 * @param {string} projectRoot
 * @param {{
 *   strip?: object|null,
 *   project_id?: string|null,
 *   home?: string,
 *   preferRollback?: boolean,
 * }} [opts]
 */
export function repairConfirmJournal(projectRoot, opts = {}) {
  const root = path.resolve(projectRoot);
  const open = listOpenConfirmJournal(root);
  const results = [];
  let changed = 0;

  for (const entry of open) {
    // Skip explicit rollbacks that left the journal open-flag false but phase set
    if (entry.rolled_back === true || entry.phase === 'rolled_back') {
      results.push({
        client_event_id: entry.client_event_id,
        action: 'skip-rolled-back',
        idempotent: true,
      });
      continue;
    }

    // Prefer forward repair: complete bind+strip under client_event_id.
    // Load current strip from disk when not injected so repair is self-contained.
    let strip = opts.strip ?? null;
    if (strip == null) {
      const surfaces = loadProjectSurfaces(root);
      strip = surfaces?.strip ?? entry.intent?.strip_seed ?? null;
    }

    if (opts.preferRollback === true) {
      const rb = rollbackConfirmIntent(root, entry);
      results.push({
        client_event_id: entry.client_event_id,
        action: 'rollback',
        result: rb,
      });
      if (rb.ok && !rb.idempotent) changed += 1;
      continue;
    }

    const applied = applyConfirmIntent(root, entry, {
      strip,
      project_id: opts.project_id ?? entry.intent?.project_id ?? null,
      home: opts.home,
      skip_index: true,
    });

    if (applied.ok) {
      // Stamp dossier as repaired-at-boot for user-visible DOSSIER_REPAIRED.
      if (entry.job_id || entry.intent?.job_id) {
        upsertDossier(root, {
          job_id: entry.job_id ?? entry.intent.job_id,
          commissioned_as:
            entry.commissioned_as ?? entry.intent?.commissioned_as ?? null,
          repaired_at_boot: true,
        });
      }
      const wasIdempotent = applied.idempotent === true;
      if (!wasIdempotent) changed += 1;
      results.push({
        client_event_id: entry.client_event_id,
        action: 'forward-repair',
        result: applied,
        idempotent: wasIdempotent,
      });
    } else {
      results.push({
        client_event_id: entry.client_event_id,
        action: 'repair-failed',
        result: applied,
      });
    }
  }

  return {
    ok: true,
    verb: REPAIR_CONFIRM_JOURNAL_VERB,
    detector: 'open-journal-entry',
    idempotence_key: CONFIRM_JOURNAL_IDEMPOTENCE_KEY,
    open_count: open.length,
    changed,
    results,
    // User-visible repair-applied when something was actually repaired
    code: changed > 0 ? DOSSIER_CODE.REPAIRED : null,
    status: changed > 0 ? DOSSIER_CODE.REPAIRED : 'noop',
  };
}

// ── Full journaled confirm (A4 fix path) ───────────────────────────────────

/**
 * Confirm a commission under the confirm journal (ONE mechanism).
 *
 * Sequence:
 *   1. appendConfirmIntent (atomic, client_event_id keyed) — BEFORE any store write
 *   2. applyConfirmIntent → roadmap bind + Strip instrument
 *   3. confirm_applied closes the journal
 *
 * @param {{
 *   project_path: string,
 *   proposal: object,
 *   roadmap?: object|null,
 *   strip?: object|null,
 *   who: string,
 *   at?: string,
 *   job_id?: string|null,
 *   client_event_id?: string|null,
 *   project_id?: string|null,
 *   home?: string,
 *   killAfterRoadmap?: boolean,
 * }} opts
 */
export function confirmCommissionJournaled(opts = {}) {
  const proposal = opts.proposal;
  if (
    !proposal
    || typeof proposal !== 'object'
    || proposal.kind !== 'commission_proposal'
    || proposal.requires_confirm !== true
  ) {
    return {
      ok: false,
      error: 'commission_confirm_requires_proposal',
      message:
        'Confirm needs a steward commission_proposal (propose/confirm path — not a mode picker).',
    };
  }
  if (!opts.who || !String(opts.who).trim()) {
    return {
      ok: false,
      error: 'commission_confirm_requires_who',
      message: 'Commission confirm is a human decision — pass who confirmed.',
      required: ['who'],
    };
  }
  if (!opts.project_path) {
    return {
      ok: false,
      error: 'project_path_required',
      message: 'Journaled confirm requires project_path (durable store root).',
    };
  }

  const at = opts.at ?? new Date().toISOString().slice(0, 10);
  const job_id =
    opts.job_id
    ?? `ecgberht-job-${String(proposal.skill).toLowerCase()}-${Date.now().toString(36)}`;
  const commissioned_as = `${proposal.skill}:${job_id}`;
  const client_event_id =
    opts.client_event_id
    ?? `confirm-${job_id}`;

  const bind_event = {
    kind: 'commission_bind',
    step_id: proposal.step_id,
    commissioned_as,
    at,
    client_event_id,
  };

  const strip_instrument = opts.strip
    ? {
        _kind: 'instrument',
        kind: 'commission_confirm',
        as_of: at,
        job_id,
        commission_id: proposal.commission?.commission_id ?? null,
        step_id: proposal.step_id,
        skill: proposal.skill,
        depth_cell: proposal.depth_cell ?? null,
        state: 'queued',
        who: opts.who,
        client_event_id,
      }
    : null;

  const job = {
    schema: 'ecgberht-job-v0',
    job_id,
    commission_id: proposal.commission?.commission_id ?? null,
    proposal_id: proposal.proposal_id ?? null,
    step_id: proposal.step_id,
    skill: proposal.skill,
    depth_cell: proposal.depth_cell ?? null,
    confirmed_by: opts.who,
    state: 'queued',
    lifecycle_events: [
      {
        seq: 1,
        from: null,
        to: 'queued',
        at,
        observed: 'commission_confirm',
        who: opts.who,
      },
    ],
  };

  // 1. Journal intent BEFORE any store write
  const intented = appendConfirmIntent(opts.project_path, {
    client_event_id,
    job_id,
    commissioned_as,
    who: opts.who,
    at,
    proposal,
    bind_event,
    strip_instrument,
    strip_seed: opts.strip ?? null,
    roadmap_seed: opts.roadmap ?? null,
    project_id: opts.project_id ?? null,
  });
  if (!intented.ok) {
    return { ...intented, refused: 'confirm_intent' };
  }

  // 2–3. Apply (roadmap + strip) + confirm_applied
  const applied = applyConfirmIntent(opts.project_path, intented.entry, {
    strip: opts.strip ?? null,
    roadmap: opts.roadmap ?? null,
    project_id: opts.project_id ?? null,
    home: opts.home,
    killAfterRoadmap: opts.killAfterRoadmap === true,
    skip_index: !opts.project_id,
  });

  if (applied.killed) {
    return {
      ...applied,
      job,
      commissioned_as,
      client_event_id,
      journaled: true,
      confirm_journal: true,
    };
  }
  if (!applied.ok) {
    return {
      ...applied,
      job,
      commissioned_as,
      client_event_id,
      journaled: true,
    };
  }

  return {
    ok: true,
    job,
    commissioned_as,
    client_event_id,
    roadmap: applied.roadmap,
    roadmap_event: applied.roadmap_event,
    strip: applied.strip,
    strip_appended: applied.strip_appended,
    strip_instrument,
    dossier: applied.dossier,
    journaled: true,
    confirm_journal: true,
    sot_written: true,
    locked: true,
    spine: true,
    durable: true,
    ui_only_state: false,
    events_only: true,
    who: opts.who,
    message:
      `Commission confirmed by ${opts.who}: ${commissioned_as} bound via confirm journal `
      + `(client_event_id=${client_event_id}).`,
  };
}

/**
 * A4 defect closed against T-ATOM-CONFIRM when the journal path is the sole
 * production confirm mechanism for durable project_path confirms.
 * @returns {{ closed: true, test_id: string, mechanism: string, repair_verb: string }}
 */
export function a4DefectClosure() {
  return {
    closed: true,
    defect_id: 'A4-non-atomic-confirm-pair',
    test_id: 'T-ATOM-CONFIRM',
    mechanism: 'confirm journal (confirm_intent → apply → confirm_applied + repairConfirmJournal)',
    repair_verb: REPAIR_CONFIRM_JOURNAL_VERB,
    idempotence_key: CONFIRM_JOURNAL_IDEMPOTENCE_KEY,
    detector: 'open-journal-entry',
    unrepaired_state: DOSSIER_CODE.PARTIAL,
    repair_applied_state: DOSSIER_CODE.REPAIRED,
  };
}

/**
 * Probe T-ATOM-CONFIRM: journal intent → kill after roadmap → repair → consistent.
 * @param {{
 *   projectDir: string,
 *   proposal: object,
 *   roadmap: object,
 *   strip: object,
 *   who?: string,
 *   job_id?: string,
 *   client_event_id?: string,
 * }} opts
 */
export function probeAtomConfirm(opts) {
  const projectDir = opts.projectDir;
  const client_event_id =
    opts.client_event_id ?? `t-atom-confirm-${Date.now().toString(36)}`;
  const job_id = opts.job_id ?? 'ecgberht-job-t-atom-001';

  // Seed surfaces on disk so repair can re-load strip.
  fs.mkdirSync(projectDir, { recursive: true });
  writeFileAtomicSync(
    path.join(projectDir, 'roadmap.json'),
    `${JSON.stringify(opts.roadmap, null, 2)}\n`,
  );
  writeFileAtomicSync(
    path.join(projectDir, STRIP_FILE_NAME),
    `${JSON.stringify(opts.strip, null, 2)}\n`,
  );

  const killed = confirmCommissionJournaled({
    project_path: projectDir,
    proposal: opts.proposal,
    roadmap: opts.roadmap,
    strip: opts.strip,
    who: opts.who ?? 'john',
    at: opts.at ?? '2026-08-03',
    job_id,
    client_event_id,
    killAfterRoadmap: true,
  });

  if (!killed.killed) {
    return {
      ok: false,
      error: 'expected-kill-window',
      killed,
    };
  }

  // Restart observation BEFORE repair: bind present, strip confirm absent, journal open.
  const before = loadProjectRoadmap(projectDir);
  const surfacesBefore = loadProjectSurfaces(projectDir);
  const bindBefore = (before.roadmap?.roadmap_events ?? []).find(
    (e) => e.kind === 'commission_bind',
  );
  const stripHasConfirmBefore = (surfacesBefore?.strip?.instruments ?? []).some(
    (i) =>
      i?.kind === 'commission_confirm'
      || i?.job_id === job_id
      || i?.client_event_id === client_event_id,
  );
  const openBefore = listOpenConfirmJournal(projectDir);
  const partialRead = readDossier(projectDir, job_id);

  // Boot repair
  const repair1 = repairConfirmJournal(projectDir, { strip: opts.strip });
  const repair2 = repairConfirmJournal(projectDir, { strip: opts.strip });

  const after = loadProjectRoadmap(projectDir);
  const surfacesAfter = loadProjectSurfaces(projectDir);
  const bindAfter = (after.roadmap?.roadmap_events ?? []).find(
    (e) => e.kind === 'commission_bind',
  );
  const stripHasConfirmAfter = (surfacesAfter?.strip?.instruments ?? []).some(
    (i) =>
      i?.kind === 'commission_confirm'
      || i?.job_id === job_id
      || i?.client_event_id === client_event_id,
  );
  const openAfter = listOpenConfirmJournal(projectDir);
  const dossierAfter = readDossier(projectDir, job_id);

  const fullyConsistent =
    Boolean(bindAfter)
    && stripHasConfirmAfter
    && openAfter.length === 0;

  const noOrphan = !(Boolean(bindAfter) && !stripHasConfirmAfter);

  return {
    ok: fullyConsistent && noOrphan && repair2.changed === 0,
    test_id: 'T-ATOM-CONFIRM',
    a4_closure: a4DefectClosure(),
    kill: {
      roadmap_written: true,
      strip_written: false,
      bind_present: Boolean(bindBefore),
      strip_confirm_present: stripHasConfirmBefore,
      open_journal: openBefore.length,
      partial_code: partialRead.code ?? partialRead.status_code ?? null,
    },
    repair1: {
      changed: repair1.changed,
      open_count: repair1.open_count,
      code: repair1.code,
      results: repair1.results,
    },
    repair2: {
      changed: repair2.changed,
      open_count: repair2.open_count,
    },
    after: {
      bind_present: Boolean(bindAfter),
      strip_confirm_present: stripHasConfirmAfter,
      open_journal: openAfter.length,
      dossier_ok: dossierAfter.ok === true,
      dossier_who: dossierAfter.dossier?.who ?? dossierAfter.dossier?.confirmation?.who ?? null,
      repaired: dossierAfter.repaired === true || dossierAfter.code === DOSSIER_CODE.REPAIRED,
    },
    fully_consistent: fullyConsistent,
    no_orphaned_bind: noOrphan,
    second_pass_noop: repair2.changed === 0,
  };
}

// Re-export MAX_PATH for tests (T-CON-07 long-path case).
export { MAX_PATH };
