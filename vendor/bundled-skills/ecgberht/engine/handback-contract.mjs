/**
 * Skill-owned durable handback-file contract (Wave 4 / NS criterion 15).
 *
 * Path convention, S6 write discipline (temp + fsync + rename), terminal
 * marker semantics, kill-mid-write non-ingestability, and duplicate-delivery
 * idempotence. Handback BODY validation is delegated to the EXISTING
 * receipt-validate.mjs — no second validator.
 *
 * Stdlib only. Host-absolute paths never appear in this module.
 */

import fs from 'node:fs';
import path from 'node:path';
import { writeFileAtomicSync } from './durable-write.mjs';
import { validateReceipt } from './receipt-validate.mjs';
import { loadJsonRelative } from './load.mjs';

/** Pinned contract version — Wave-21 fails if executors disagree. */
export const CONTRACT_VERSION = '1.0.0';

/** Relative directory inside the run worktree. */
export const HANDBACK_REL_DIR = '.ecgberht/handback';

export const HANDBACK_JSON_NAME = 'handback.json';
export const TERMINAL_MARKER_NAME = 'TERMINAL.marker';

/** Normative write discipline token (schema const). */
export const WRITE_DISCIPLINE = 'temp-fsync-rename';

/** Idempotence key name for ingest/adopt. */
export const IDEMPOTENCE_KEY = 'client_event_id';

/**
 * Failure-state table for the executor surface (Wave 4).
 * Status codes are the machine names; user_text is the honest user-facing line.
 */
export const EXEC_FAILURE_STATES = Object.freeze({
  EXEC_SUBSTRATE_MISSING: {
    state: 'dependency-missing (trio CLI absent)',
    status_code: 'EXEC_SUBSTRATE_MISSING',
    user_text:
      'The build substrate is not available on this box — commission cannot launch.',
  },
  EXEC_REFUSED_UNCONFIRMED: {
    state: 'launch-refused (unconfirmed)',
    status_code: 'EXEC_REFUSED_UNCONFIRMED',
    user_text: 'Commission not confirmed — nothing launched, nothing spent.',
  },
  EXEC_SUBSTRATE_BUSY: {
    state: 'substrate-busy (LaneBusy / spawn cap / build lock)',
    status_code: 'EXEC_SUBSTRATE_BUSY',
    user_text:
      'Substrate refused the launch (<reason>) — commission intact; retry when clear.',
  },
  EXEC_RUN_DIED: {
    state: 'launched-then-died',
    status_code: 'EXEC_RUN_DIED',
    user_text:
      'Run <id> died (process identity no longer live) — named dead, not absorbed.',
  },
  EXEC_HANDBACK_MISSING: {
    state: 'no-handback (marker absent past TTL)',
    status_code: 'EXEC_HANDBACK_MISSING',
    user_text:
      'Run <id> ended with no handback file — named missing, not absorbed.',
  },
  EXEC_RUN_ADOPTED: {
    state: 'adopted-after-restart',
    status_code: 'EXEC_RUN_ADOPTED',
    user_text:
      'Run <id> survived a service restart — handback adopted from its durable file.',
  },
  EXEC_AUTH_REFUSED: {
    state: 'auth-refused at launch',
    status_code: 'EXEC_AUTH_REFUSED',
    user_text:
      'Launch refused — credential invalid at the launch seam; nothing started.',
  },
  EXEC_DOSSIER_UNREADABLE: {
    state: 'backing-store-unreadable',
    status_code: 'EXEC_DOSSIER_UNREADABLE',
    user_text:
      'Commission dossier unreadable — launch refused rather than launched blind.',
  },
  EXEC_NO_RUNS: {
    state: 'empty-but-valid',
    status_code: 'EXEC_NO_RUNS',
    user_text: 'No commissioned runs.',
  },
  EXEC_LIVENESS_UNKNOWN: {
    state: 'unknown (liveness undeterminable)',
    status_code: 'EXEC_LIVENESS_UNKNOWN',
    user_text: 'Run liveness UNKNOWN — shown as unknown, not running.',
  },
  LAUNCH_INTENT_STRANDED: {
    state: 'confirmed-but-unlaunched',
    status_code: 'LAUNCH_INTENT_STRANDED',
    user_text:
      'Commission was confirmed but never launched — named stranded, not silent.',
  },
});

/**
 * Load the frozen contract schema from the skill pack.
 * @returns {object}
 */
export function loadHandbackContractSchema() {
  return loadJsonRelative('schema', 'handback-contract.schema.json');
}

/**
 * Canonical contract descriptor object (matches schema consts).
 * @returns {object}
 */
export function contractDescriptor() {
  return {
    contract_version: CONTRACT_VERSION,
    handback_rel_dir: HANDBACK_REL_DIR,
    handback_json_name: HANDBACK_JSON_NAME,
    terminal_marker_name: TERMINAL_MARKER_NAME,
    write_discipline: WRITE_DISCIPLINE,
    single_writer: true,
    kill_mid_write: {
      marker_absent_means: 'not_ingestable',
      ingestable: 'handback_json_and_terminal_marker_both_present',
    },
    duplicate_delivery: {
      idempotence_key: IDEMPOTENCE_KEY,
      semantics: 'ingest_exactly_once',
    },
    receipt_validator: 'engine/receipt-validate.mjs',
    write_order: [HANDBACK_JSON_NAME, TERMINAL_MARKER_NAME],
    no_credential_in_child: true,
  };
}

/**
 * @param {string} worktreeRoot absolute or relative run worktree root
 * @returns {string}
 */
export function handbackDir(worktreeRoot) {
  return path.join(String(worktreeRoot), ...HANDBACK_REL_DIR.split('/'));
}

/**
 * @param {string} worktreeRoot
 * @returns {string}
 */
export function handbackJsonPath(worktreeRoot) {
  return path.join(handbackDir(worktreeRoot), HANDBACK_JSON_NAME);
}

/**
 * @param {string} worktreeRoot
 * @returns {string}
 */
export function terminalMarkerPath(worktreeRoot) {
  return path.join(handbackDir(worktreeRoot), TERMINAL_MARKER_NAME);
}

/**
 * Validate that a handback body is a receipt-validate handback.
 * @param {*} body
 * @returns {{ ok: true, receipt: object } | { ok: false, error: string, message: string, issues?: string[] }}
 */
export function validateHandbackBody(body) {
  const result = validateReceipt(body);
  if (!result.ok) return result;
  if (result.receipt?.kind !== 'handback') {
    return {
      ok: false,
      error: 'handback_kind_required',
      message: 'Handback contract body must have kind "handback".',
      issues: ['kind'],
    };
  }
  return { ok: true, receipt: result.receipt, schema_id: result.schema_id };
}

/**
 * Write the durable handback pair under S6 (handback first, marker second).
 * Single writer per run dir by construction.
 *
 * @param {string} worktreeRoot
 * @param {object} handbackBody receipt-shaped object (kind=handback)
 * @param {{ client_event_id?: string, handback_id?: string, skip_body_validate?: boolean }} [opts]
 * @returns {{ ok: true, handback_path: string, marker_path: string, client_event_id: string|null, handback_id: string|null, contract_version: string }
 *   | { ok: false, error: string, message: string, issues?: string[] }}
 */
export function writeHandbackPair(worktreeRoot, handbackBody, opts = {}) {
  if (!worktreeRoot || typeof worktreeRoot !== 'string') {
    return {
      ok: false,
      error: 'worktree_required',
      message: 'writeHandbackPair requires a worktree root path.',
    };
  }

  let body = handbackBody && typeof handbackBody === 'object' ? { ...handbackBody } : null;
  if (!body) {
    return {
      ok: false,
      error: 'handback_body_required',
      message: 'writeHandbackPair requires a handback body object.',
    };
  }

  if (opts.client_event_id && !body.client_event_id) {
    body.client_event_id = opts.client_event_id;
  }
  if (opts.handback_id && !body.handback_id) {
    body.handback_id = opts.handback_id;
  }
  if (!body.contract_version) {
    body.contract_version = CONTRACT_VERSION;
  }

  if (opts.skip_body_validate !== true) {
    const v = validateHandbackBody(body);
    if (!v.ok) return v;
    body = v.receipt;
  }

  const dir = handbackDir(worktreeRoot);
  fs.mkdirSync(dir, { recursive: true });

  const hbPath = handbackJsonPath(worktreeRoot);
  const mkPath = terminalMarkerPath(worktreeRoot);

  // S6: handback first (temp + fsync + rename), then marker.
  writeFileAtomicSync(hbPath, `${JSON.stringify(body, null, 2)}\n`);

  const markerPayload = {
    contract_version: CONTRACT_VERSION,
    terminal: true,
    written_at: new Date().toISOString(),
    client_event_id: body.client_event_id ?? opts.client_event_id ?? null,
    handback_id: body.handback_id ?? opts.handback_id ?? null,
  };
  writeFileAtomicSync(mkPath, `${JSON.stringify(markerPayload)}\n`);

  return {
    ok: true,
    handback_path: hbPath,
    marker_path: mkPath,
    client_event_id: body.client_event_id ?? null,
    handback_id: body.handback_id ?? null,
    contract_version: CONTRACT_VERSION,
  };
}

/**
 * True only when both handback.json and TERMINAL.marker exist.
 * Marker-less or torn pairs are NOT ingestable (kill-mid-write law).
 *
 * @param {string} worktreeRoot
 * @returns {boolean}
 */
export function isIngestable(worktreeRoot) {
  try {
    return (
      fs.existsSync(handbackJsonPath(worktreeRoot)) &&
      fs.existsSync(terminalMarkerPath(worktreeRoot))
    );
  } catch {
    return false;
  }
}

/**
 * Read and validate an ingestable pair. Returns named refusal when not complete.
 *
 * @param {string} worktreeRoot
 * @returns {{ ok: true, handback: object, client_event_id: string|null, handback_id: string|null }
 *   | { ok: false, error: string, status_code: string, message: string }}
 */
export function readIngestableHandback(worktreeRoot) {
  const hbPath = handbackJsonPath(worktreeRoot);
  const mkPath = terminalMarkerPath(worktreeRoot);
  const hbExists = fs.existsSync(hbPath);
  const mkExists = fs.existsSync(mkPath);

  if (!hbExists && !mkExists) {
    return {
      ok: false,
      error: 'handback_pair_absent',
      status_code: 'EXEC_HANDBACK_MISSING',
      message: EXEC_FAILURE_STATES.EXEC_HANDBACK_MISSING.user_text.replace(
        '<id>',
        path.basename(String(worktreeRoot)),
      ),
    };
  }
  if (!mkExists) {
    return {
      ok: false,
      error: 'terminal_marker_absent',
      status_code: 'EXEC_HANDBACK_MISSING',
      message:
        'Handback JSON present but TERMINAL.marker absent — kill-mid-write; not ingestable.',
    };
  }
  if (!hbExists) {
    return {
      ok: false,
      error: 'handback_json_absent',
      status_code: 'EXEC_HANDBACK_MISSING',
      message: 'TERMINAL.marker present without handback.json — not ingestable.',
    };
  }

  let raw;
  try {
    raw = fs.readFileSync(hbPath, 'utf8');
  } catch (e) {
    return {
      ok: false,
      error: 'handback_unreadable',
      status_code: 'EXEC_DOSSIER_UNREADABLE',
      message: String(e?.message ?? e),
    };
  }

  let body;
  try {
    body = JSON.parse(raw);
  } catch (e) {
    return {
      ok: false,
      error: 'handback_torn_json',
      status_code: 'EXEC_HANDBACK_MISSING',
      message: `Handback JSON parse failed (torn?): ${e?.message ?? e}`,
    };
  }

  const v = validateHandbackBody(body);
  if (!v.ok) {
    return {
      ok: false,
      error: v.error ?? 'handback_invalid',
      status_code: 'EXEC_HANDBACK_MISSING',
      message: v.message ?? 'Handback failed receipt-validate.',
      issues: v.issues,
    };
  }

  return {
    ok: true,
    handback: v.receipt,
    client_event_id: v.receipt.client_event_id ?? null,
    handback_id: v.receipt.handback_id ?? null,
    handback_path: hbPath,
    marker_path: mkPath,
  };
}

/**
 * Idempotent adopt registry: track client_event_ids already ingested.
 * Pure helper over a Set/Map supplied by the caller (or a JSON file path).
 */
export class IngestIdempotenceRegistry {
  /**
   * @param {Iterable<string>} [seed]
   */
  constructor(seed = []) {
    /** @type {Set<string>} */
    this._seen = new Set(seed);
  }

  /**
   * @param {string|null|undefined} clientEventId
   * @returns {boolean} true if this id was already adopted
   */
  has(clientEventId) {
    if (clientEventId == null || clientEventId === '') return false;
    return this._seen.has(String(clientEventId));
  }

  /**
   * Attempt adopt. Returns { adopted: true } on first time, { adopted: false, duplicate: true } on re-delivery.
   * Ids that are null/empty always adopt (no key → cannot dedupe; caller should supply keys).
   *
   * @param {string|null|undefined} clientEventId
   * @returns {{ adopted: boolean, duplicate: boolean, client_event_id: string|null }}
   */
  tryAdopt(clientEventId) {
    if (clientEventId == null || clientEventId === '') {
      return { adopted: true, duplicate: false, client_event_id: null };
    }
    const id = String(clientEventId);
    if (this._seen.has(id)) {
      return { adopted: false, duplicate: true, client_event_id: id };
    }
    this._seen.add(id);
    return { adopted: true, duplicate: false, client_event_id: id };
  }

  /** @returns {string[]} */
  toArray() {
    return [...this._seen];
  }

  /**
   * Load registry from a JSON file (array of ids). Missing file → empty.
   * @param {string} filePath
   * @returns {IngestIdempotenceRegistry}
   */
  static loadFromFile(filePath) {
    try {
      const raw = fs.readFileSync(filePath, 'utf8');
      const data = JSON.parse(raw);
      const ids = Array.isArray(data)
        ? data
        : Array.isArray(data?.ids)
          ? data.ids
          : [];
      return new IngestIdempotenceRegistry(ids.map(String));
    } catch {
      return new IngestIdempotenceRegistry();
    }
  }

  /**
   * Persist registry (atomic).
   * @param {string} filePath
   */
  saveToFile(filePath) {
    const dir = path.dirname(filePath);
    fs.mkdirSync(dir, { recursive: true });
    writeFileAtomicSync(
      filePath,
      `${JSON.stringify({ ids: this.toArray(), contract_version: CONTRACT_VERSION }, null, 2)}\n`,
    );
  }
}

/**
 * Simulate a kill mid-write for T-DUR-S6 tests: write only handback.json
 * without the terminal marker (the torn / interrupted state).
 *
 * @param {string} worktreeRoot
 * @param {object} handbackBody
 * @returns {{ ok: boolean, handback_path?: string, error?: string }}
 */
export function writeHandbackWithoutMarker(worktreeRoot, handbackBody) {
  const v = validateHandbackBody(handbackBody);
  if (!v.ok) return v;
  const dir = handbackDir(worktreeRoot);
  fs.mkdirSync(dir, { recursive: true });
  const hbPath = handbackJsonPath(worktreeRoot);
  writeFileAtomicSync(hbPath, `${JSON.stringify(v.receipt, null, 2)}\n`);
  return { ok: true, handback_path: hbPath, marker_present: false };
}

/**
 * Assert the live descriptor matches the frozen schema consts.
 * @returns {{ ok: true, descriptor: object } | { ok: false, issues: string[] }}
 */
export function assertContractMatchesSchema() {
  const schema = loadHandbackContractSchema();
  const desc = contractDescriptor();
  const issues = [];
  const props = schema.properties || {};

  for (const key of schema.required || []) {
    if (!(key in desc)) issues.push(`descriptor missing required ${key}`);
  }
  for (const [key, def] of Object.entries(props)) {
    if (def && def.const !== undefined && desc[key] !== undefined) {
      if (typeof def.const === 'object') continue; // nested checked loosely
      if (desc[key] !== def.const) {
        issues.push(`${key}: descriptor ${JSON.stringify(desc[key])} !== schema const ${JSON.stringify(def.const)}`);
      }
    }
  }
  if (desc.contract_version !== props.contract_version?.const) {
    issues.push('contract_version mismatch');
  }
  if (issues.length) return { ok: false, issues };
  return { ok: true, descriptor: desc, schema_id: schema.$id };
}
