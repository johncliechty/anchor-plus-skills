/**
 * Anchor reference commission-executor surface (Wave 4 — IMPLEMENTATION #1).
 *
 * HOST CONTRACT ONLY. This module lives in the skill repo so the standing suite
 * can measure and pin the Anchor half (which physically lives as
 * `commission_executor.py` next to the skill) without the Anchor tree escaping
 * vacuous-GREEN / delta-coverage measurement.
 *
 * No steward logic. No ANCHOR_TOKEN handling in this module (the Python host
 * owns the launch-seam authorizer). Constants mirror the skill-owned handback
 * contract and the Wave-4 failure-state table.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  CONTRACT_VERSION,
  HANDBACK_REL_DIR,
  HANDBACK_JSON_NAME,
  TERMINAL_MARKER_NAME,
  EXEC_FAILURE_STATES,
  WRITE_DISCIPLINE,
} from './handback-contract.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_ROOT = path.resolve(ENGINE_DIR, '..');

/** Relative path of the Anchor Python module (from Anchor repo root). */
export const ANCHOR_EXECUTOR_MODULE_REL = 'commission_executor.py';

/** Relative path of the Anchor pytest module (from Anchor repo root). */
export const ANCHOR_EXECUTOR_TEST_REL = 'tests/test_commission_executor_w4.py';

/**
 * Symbols the Anchor implementation MUST export / define (string presence
 * checked when the sibling Anchor tree is available).
 */
export const ANCHOR_EXECUTOR_REQUIRED_SYMBOLS = Object.freeze([
  'CONTRACT_VERSION',
  'COMMISSION_KILL_ON_JOB_CLOSE',
  'execute_confirmed_commission',
  'write_launch_intent',
  'boot_reconcile',
  'authorize_at_launch',
  'child_env',
  'process_identity_alive',
  'write_handback_pair',
  'is_ingestable',
  'renew_commission_lease',
  'EXEC_REFUSED_UNCONFIRMED',
  'EXEC_AUTH_REFUSED',
  'EXEC_RUN_DIED',
  'EXEC_HANDBACK_MISSING',
  'EXEC_RUN_ADOPTED',
  'LAUNCH_INTENT_STRANDED',
  'EXEC_SUBSTRATE_BUSY',
]);

/**
 * Normative surface descriptor for IMPLEMENTATION #1.
 * @returns {object}
 */
export function anchorExecutorSurface() {
  return {
    implementation: 1,
    owner: 'anchor',
    role: 'reference-host-executor',
    module_rel: ANCHOR_EXECUTOR_MODULE_REL,
    test_rel: ANCHOR_EXECUTOR_TEST_REL,
    contract_version: CONTRACT_VERSION,
    handback_rel_dir: HANDBACK_REL_DIR,
    handback_json_name: HANDBACK_JSON_NAME,
    terminal_marker_name: TERMINAL_MARKER_NAME,
    write_discipline: WRITE_DISCIPLINE,
    kill_on_job_close_for_commissions: false,
    kill_on_job_close_reason:
      'commissions outlive the service — kill_on_job_close=False so nssm restart does not murder an in-flight commissioned run (Wave 4)',
    liveness: '(pid, proc_create_time)',
    degraded_one_run_at_a_time: true,
    no_token_in_child: true,
    auth_revalidation_at_launch: true,
    refuses_unconfirmed: true,
    failure_status_codes: Object.keys(EXEC_FAILURE_STATES),
    required_symbols: [...ANCHOR_EXECUTOR_REQUIRED_SYMBOLS],
    host_contract_only: true,
    // NS v5 non-goal: no steward logic in Anchor Python
    steward_logic_forbidden: [
      'propose',
      'confirm decisions',
      'reflection',
      'attention derivation',
      'roadmap/status law',
    ],
  };
}

/**
 * Resolve Anchor root the same way the pytest bridge does (env or sibling).
 * Host-absolute paths are never hardcoded.
 *
 * @param {string} [skillRoot]
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {string|null}
 */
export function resolveAnchorRootForSurface(skillRoot = SKILL_ROOT, env = process.env) {
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
 * When Anchor is present, read commission_executor.py and verify required symbols.
 * When absent (host-less skill box), return { available: false } — not a fail.
 *
 * @param {{ skillRoot?: string, env?: NodeJS.ProcessEnv }} [opts]
 * @returns {{
 *   available: boolean,
 *   anchor_root?: string|null,
 *   module_path?: string,
 *   ok?: boolean,
 *   missing?: string[],
 *   present?: string[],
 *   kill_on_job_close_false?: boolean,
 *   contract_version_match?: boolean,
 * }}
 */
export function probeAnchorExecutorSource(opts = {}) {
  const skillRoot = opts.skillRoot ?? SKILL_ROOT;
  const env = opts.env ?? process.env;
  const anchorRoot = resolveAnchorRootForSurface(skillRoot, env);
  if (!anchorRoot) {
    return { available: false, anchor_root: null };
  }
  const modulePath = path.join(anchorRoot, ANCHOR_EXECUTOR_MODULE_REL);
  if (!fs.existsSync(modulePath)) {
    return {
      available: true,
      anchor_root: anchorRoot,
      module_path: modulePath,
      ok: false,
      missing: [ANCHOR_EXECUTOR_MODULE_REL],
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
  for (const sym of ANCHOR_EXECUTOR_REQUIRED_SYMBOLS) {
    // Prefer definition-shaped matches over free substring (anti pin-gaming).
    // Constants: NAME = … ; functions: def NAME(
    const defRe = new RegExp(
      `(?:^|\\n)\\s*(?:def\\s+${sym}\\s*\\(|${sym}\\s*=)`,
      'm',
    );
    const ok =
      defRe.test(text) ||
      // status-code string constants often appear as NAME = "NAME"
      new RegExp(`${sym}\\s*=\\s*["']${sym}["']`).test(text) ||
      // FAILURE_STATES keys still count as export surface for status codes
      (sym.startsWith('EXEC_') || sym === 'LAUNCH_INTENT_STRANDED'
        ? text.includes(sym)
        : false);
    if (ok) present.push(sym);
    else missing.push(sym);
  }

  const killOnJobCloseFalse =
    /COMMISSION_KILL_ON_JOB_CLOSE\s*=\s*False/.test(text) ||
    /kill_on_job_close\s*=\s*False/.test(text);

  const contractVersionMatch = text.includes(`"${CONTRACT_VERSION}"`) ||
    text.includes(`'${CONTRACT_VERSION}'`);

  return {
    available: true,
    anchor_root: anchorRoot,
    module_path: modulePath,
    ok: missing.length === 0 && killOnJobCloseFalse && contractVersionMatch,
    missing,
    present,
    kill_on_job_close_false: killOnJobCloseFalse,
    contract_version_match: contractVersionMatch,
    // Never embed the absolute path in shipped docs — callers may log relative
    module_rel: ANCHOR_EXECUTOR_MODULE_REL,
  };
}
