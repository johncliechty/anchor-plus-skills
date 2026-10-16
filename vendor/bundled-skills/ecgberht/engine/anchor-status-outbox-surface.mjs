/**
 * Anchor S12 status-outbox surface pin (Wave 13 — host contract only).
 *
 * Mirrors Wave-4's anchor-executor-surface pattern: skill lane measures and
 * pins the Anchor Python half without requiring Anchor for host-less green.
 *
 * No steward logic. No roadmap/status law in Python.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  OUTBOX_SCHEMA_ID,
  OUTBOX_EVENT_KINDS,
  OUTBOX_STORE,
} from './status-outbox.mjs';
import { STATUS_FAILURE_CODE } from './status-ingestion.mjs';
import { LEASE_TTL_MS, LEASE_RENEW_INTERVAL_MS } from './lease-law.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_ROOT = path.resolve(ENGINE_DIR, '..');

/** Relative path of the Anchor Python module (from Anchor repo root). */
export const ANCHOR_STATUS_OUTBOX_MODULE_REL = 'status_outbox.py';

/** Relative path of the Anchor pytest module. */
export const ANCHOR_STATUS_OUTBOX_TEST_REL = 'tests/test_status_outbox_w13.py';

/** Symbols the Anchor implementation MUST define. */
export const ANCHOR_STATUS_OUTBOX_REQUIRED_SYMBOLS = Object.freeze([
  'OUTBOX_SCHEMA',
  'OUTBOX_REL_PARTS',
  'append_outbox_record',
  'renew_lease',
  'read_outbox',
  'atomic_write_json',
  'LEASE_TTL_MS',
  'LEASE_RENEW_INTERVAL_MS',
  'process_identity_tuple',
  'RUN_DEAD_LEASE_EXPIRED',
  'STATUS_SEQUENCE_GAP',
  'OUTBOX_UNREADABLE',
  'NO_LIVE_RUNS',
  'RUN_LIVENESS_UNKNOWN',
  'LAUNCH_INTENT_STRANDED',
]);

/**
 * Normative surface descriptor for S12 producer #1 (Python half).
 */
export function anchorStatusOutboxSurface() {
  return {
    store: OUTBOX_STORE,
    owner: 'anchor',
    role: 'outbox-producer-1',
    module_rel: ANCHOR_STATUS_OUTBOX_MODULE_REL,
    test_rel: ANCHOR_STATUS_OUTBOX_TEST_REL,
    schema: OUTBOX_SCHEMA_ID,
    event_kinds: [...OUTBOX_EVENT_KINDS],
    lease_ttl_ms: LEASE_TTL_MS,
    lease_renew_interval_ms: LEASE_RENEW_INTERVAL_MS,
    liveness: '(pid, proc_create_time)',
    writes_roadmap_ledger: false,
    host_contract_only: true,
    failure_status_codes: Object.keys(STATUS_FAILURE_CODE),
    required_symbols: [...ANCHOR_STATUS_OUTBOX_REQUIRED_SYMBOLS],
    steward_logic_forbidden: [
      'propose',
      'confirm decisions',
      'reflection',
      'attention derivation',
      'roadmap/status law',
    ],
    mediator_client: 'engine/status-mediator.mjs',
    seam: 'ingestStatusEvents',
  };
}

/**
 * @param {string} [skillRoot]
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {string|null}
 */
export function resolveAnchorRootForOutbox(skillRoot = SKILL_ROOT, env = process.env) {
  const fromEnv =
    env.ANCHOR_REPO || env.ECGBERHT_ANCHOR_ROOT || env.ANCHOR_ROOT;
  if (fromEnv && String(fromEnv).trim()) {
    const p = path.resolve(String(fromEnv).trim());
    return fs.existsSync(p) ? p : null;
  }
  const sibling = path.resolve(skillRoot, '..', 'Anchor');
  return fs.existsSync(sibling) ? sibling : null;
}

/**
 * @param {{ skillRoot?: string, env?: NodeJS.ProcessEnv }} [opts]
 */
export function probeAnchorStatusOutboxSource(opts = {}) {
  const skillRoot = opts.skillRoot ?? SKILL_ROOT;
  const env = opts.env ?? process.env;
  const anchorRoot = resolveAnchorRootForOutbox(skillRoot, env);
  if (!anchorRoot) {
    return { available: false, anchor_root: null };
  }
  const modulePath = path.join(anchorRoot, ANCHOR_STATUS_OUTBOX_MODULE_REL);
  if (!fs.existsSync(modulePath)) {
    return {
      available: true,
      anchor_root: anchorRoot,
      module_path: modulePath,
      ok: false,
      missing: [ANCHOR_STATUS_OUTBOX_MODULE_REL],
      present: [],
    };
  }
  let text;
  try {
    text = fs.readFileSync(modulePath, 'utf8');
  } catch (e) {
    return {
      available: true,
      anchor_root: anchorRoot,
      module_path: modulePath,
      ok: false,
      missing: [`unreadable: ${e?.message ?? e}`],
      present: [],
    };
  }

  const present = [];
  const missing = [];
  for (const sym of ANCHOR_STATUS_OUTBOX_REQUIRED_SYMBOLS) {
    const defRe = new RegExp(
      `(?:^|\\n)\\s*(?:def\\s+${sym}\\s*\\(|${sym}\\s*=)`,
      'm',
    );
    const ok =
      defRe.test(text) ||
      new RegExp(`${sym}\\s*=\\s*["']${sym}["']`).test(text) ||
      text.includes(sym);
    if (ok) present.push(sym);
    else missing.push(sym);
  }

  const noLedgerWrite =
    !/roadmap\.json/.test(text) ||
    /NEVER writes the ledger|never writes roadmap|writes_roadmap_ledger\s*=\s*False/i.test(
      text,
    );

  return {
    available: true,
    anchor_root: anchorRoot,
    module_path: modulePath,
    ok: missing.length === 0 && noLedgerWrite,
    missing,
    present,
    writes_roadmap_ledger: !noLedgerWrite,
  };
}
