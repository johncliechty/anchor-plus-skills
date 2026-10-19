/**
 * Wave 21 — conformance-verdict.json writer (S8 discipline).
 *
 * Shape: {
 *   contract_version,
 *   executors: { insession: PASS|FAIL, anchor: PASS|FAIL },
 *   failed_clauses: string[],  // "executor:<name> clause:<clause>"
 *   recorded_at, written_by
 * }
 *
 * Only the suite runner writes this artifact. Regenerate-twice is
 * byte-identical via writeJsonIdempotentSync (volatile recorded_at stripped).
 *
 * Stdlib only. No host-absolute paths.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  writeJsonIdempotentSync,
  withFileLock,
  writeFileAtomicSync,
} from '../../engine/durable-write.mjs';
import { CONTRACT_VERSION } from '../../engine/handback-contract.mjs';
import { EXECUTOR_SLOTS } from './adapter-interface.mjs';
import { clauseFailureName } from './clauses.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(HERE, '..', '..');

export const CONFORMANCE_VERDICT_REL = path.join(
  'artifacts',
  'conformance-verdict.json',
);

export const CONFORMANCE_WRITTEN_BY = 'conformance/handback-contract';

/**
 * @param {string} [root]
 */
export function conformanceVerdictPath(root = DEFAULT_ROOT) {
  return path.join(root, CONFORMANCE_VERDICT_REL);
}

/**
 * Empty / unknown baseline (both FAIL until proven this run).
 * @param {{ contract_version?: string }} [opts]
 */
export function emptyConformanceVerdict(opts = {}) {
  return {
    contract_version: opts.contract_version ?? CONTRACT_VERSION,
    executors: {
      insession: 'FAIL',
      anchor: 'FAIL',
    },
    failed_clauses: [],
    recorded_at: null,
    written_by: CONFORMANCE_WRITTEN_BY,
    schema: 'ecgberht-conformance-verdict-v0',
  };
}

/**
 * @param {string} [root]
 * @returns {object|null}
 */
export function readConformanceVerdict(root = DEFAULT_ROOT) {
  const p = conformanceVerdictPath(root);
  try {
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * Merge one executor's clause results into the verdict payload (pure).
 *
 * @param {object|null} existing
 * @param {{
 *   executor: string,
 *   contract_version: string,
 *   clause_results: Array<{ clause: string, ok: boolean, reason?: string }>,
 *   peer_versions?: Record<string, string|null|undefined>,
 * }} update
 */
export function mergeExecutorResult(existing, update) {
  const base = existing && typeof existing === 'object'
    ? {
        ...emptyConformanceVerdict(),
        ...existing,
        executors: {
          ...emptyConformanceVerdict().executors,
          ...(existing.executors || {}),
        },
      }
    : emptyConformanceVerdict({ contract_version: update.contract_version });

  const executor = String(update.executor);
  if (!EXECUTOR_SLOTS.includes(executor)) {
    throw new Error(`unknown executor slot: ${executor}`);
  }

  const failedThis = (update.clause_results || [])
    .filter((r) => r && r.ok === false)
    .map((r) => clauseFailureName(executor, r.clause));

  // Drop prior failures for this executor; keep the other executor's.
  const prefix = `executor:${executor} clause:`;
  const kept = (Array.isArray(base.failed_clauses) ? base.failed_clauses : [])
    .filter((f) => !String(f).startsWith(prefix));

  const allFailed = [...kept, ...failedThis].sort();
  const executorPass = failedThis.length === 0 ? 'PASS' : 'FAIL';

  const contract_version = update.contract_version || base.contract_version || CONTRACT_VERSION;

  // Version-skew: if peer versions disagree, both FAIL until they agree.
  const peers = update.peer_versions || {};
  const versions = {
    insession:
      executor === 'insession'
        ? contract_version
        : peers.insession ?? base.executor_versions?.insession ?? null,
    anchor:
      executor === 'anchor'
        ? contract_version
        : peers.anchor ?? base.executor_versions?.anchor ?? null,
  };
  // Prefer skill contract pin for the verdict top-level when both agree
  let topVersion = contract_version;
  if (
    versions.insession &&
    versions.anchor &&
    String(versions.insession) === String(versions.anchor)
  ) {
    topVersion = String(versions.insession);
  }

  let failed_clauses = allFailed;
  const skew =
    versions.insession &&
    versions.anchor &&
    String(versions.insession) !== String(versions.anchor);

  const executors = {
    ...base.executors,
    [executor]: executorPass,
  };

  if (skew) {
    // Fail BOTH until they agree (plan GWT).
    executors.insession = 'FAIL';
    executors.anchor = 'FAIL';
    for (const slot of EXECUTOR_SLOTS) {
      const token = clauseFailureName(slot, 'version-skew');
      if (!failed_clauses.includes(token)) failed_clauses.push(token);
    }
    failed_clauses = [...failed_clauses].sort();
  }

  return {
    contract_version: topVersion,
    executors,
    executor_versions: versions,
    failed_clauses,
    clause_detail: {
      ...(base.clause_detail || {}),
      [executor]: (update.clause_results || []).map((r) => ({
        clause: r.clause,
        ok: r.ok === true,
        reason: r.reason ?? null,
      })),
    },
    recorded_at: new Date().toISOString(),
    written_by: CONFORMANCE_WRITTEN_BY,
    schema: 'ecgberht-conformance-verdict-v0',
  };
}

/**
 * Write (merge) one executor result into artifacts/conformance-verdict.json.
 *
 * @param {{
 *   root?: string,
 *   executor: string,
 *   contract_version?: string,
 *   clause_results: Array<{ clause: string, ok: boolean, reason?: string }>,
 *   peer_versions?: Record<string, string|null|undefined>,
 * }} opts
 */
export function writeConformanceVerdictForExecutor(opts) {
  const root = opts.root ?? DEFAULT_ROOT;
  const outPath = conformanceVerdictPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });

  // Outer withFileLock covers the full RMW. writeJsonIdempotentSync defaults to
  // taking the same path's lock; that lock is not reentrant, so nested acquire
  // deadlocks the holding process until LOCK_TIMEOUT_MS (gate RED on every
  // suite write). Disable the inner lock — we already hold exclusive access.
  return withFileLock(outPath, () => {
    const existing = readConformanceVerdict(root);
    const payload = mergeExecutorResult(existing, {
      executor: opts.executor,
      contract_version: opts.contract_version ?? CONTRACT_VERSION,
      clause_results: opts.clause_results || [],
      peer_versions: opts.peer_versions,
    });
    const result = writeJsonIdempotentSync(outPath, payload, { lock: false });
    return { path: outPath, payload, ...result };
  });
}

/**
 * Replace the whole verdict (tests / full both-executor run).
 *
 * @param {object} payload
 * @param {{ root?: string }} [opts]
 */
export function writeConformanceVerdict(payload, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const outPath = conformanceVerdictPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const body = {
    ...emptyConformanceVerdict(),
    ...payload,
    written_by: CONFORMANCE_WRITTEN_BY,
    recorded_at: payload.recorded_at ?? new Date().toISOString(),
  };
  const result = writeJsonIdempotentSync(outPath, body);
  return { path: outPath, payload: body, ...result };
}

/**
 * S8: regenerate twice must leave file byte-identical when semantic content
 * is unchanged (volatile recorded_at ignored by writeJsonIdempotentSync).
 *
 * @param {{ root?: string, executor?: string, clause_results?: object[] }} [opts]
 */
export function proveRegenerateTwiceByteIdentical(opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const executor = opts.executor ?? 'insession';
  const clause_results =
    opts.clause_results ??
    [
      { clause: 'path-convention', ok: true },
      { clause: 'schema-validity', ok: true },
    ];

  writeConformanceVerdictForExecutor({
    root,
    executor,
    clause_results,
    contract_version: CONTRACT_VERSION,
  });
  const first = fs.readFileSync(conformanceVerdictPath(root));
  writeConformanceVerdictForExecutor({
    root,
    executor,
    clause_results,
    contract_version: CONTRACT_VERSION,
  });
  const second = fs.readFileSync(conformanceVerdictPath(root));
  return {
    ok: Buffer.compare(first, second) === 0,
    path: conformanceVerdictPath(root),
    bytes: first.length,
  };
}

/**
 * Force a raw write (bypasses idempotence) — only for tests that need a
 * known torn/prior state. Production suite uses writeConformanceVerdict*.
 *
 * @param {string} root
 * @param {object} payload
 */
export function forceWriteConformanceVerdict(root, payload) {
  const outPath = conformanceVerdictPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  writeFileAtomicSync(outPath, `${JSON.stringify(payload, null, 2)}\n`);
  return outPath;
}
