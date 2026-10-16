// Versioned closed classifier reason codes + Doctor issue ID seed (W3 / P1).
//
// Closed catalogs: only codes listed here are legal on dual-write / Why / Doctor
// seed surfaces. Unknown codes must not be invented by clients. W10 CI will
// lock SKILL.md ↔ this catalog; W3 seeds the contract.

/** Catalog version pin (bump when adding/removing codes). */
const REASON_CATALOG_VERSION = 'w10-reason-catalog-v1';

/** Doctor issue catalog version pin. */
const DOCTOR_ISSUE_CATALOG_VERSION = 'w9-doctor-issue-catalog-v1';

/**
 * Closed classifier / dual-write reason codes (strings).
 * Grouped for readability; Set is the closed membership test.
 */
const CLASSIFIER_REASON_CODES = Object.freeze([
  // Dual-write / shadow observe (G0)
  'SHADOW_OBSERVE_ONLY',
  'WOULD_BE_ACTIONABLE_RED',
  'LEGACY_SPEND_UNSUPERVISED_SHAPE',
  'NEW_CLASSIFIER_WOULD_BE_RED',
  'NO_WOULD_BE_RED',
  // Mode / arm
  'MODE_SHADOW',
  'MODE_ARMED',
  'REFUSE_ARMED_WITHOUT_RECEIPT',
  'CANARY_RECEIPT_MISSING',
  'CANARY_RECEIPT_MISMATCH',
  // Engine leg (C3)
  'E1_CLOSED_ALLOWLIST',
  'E2_SUPPORT_ANCESTRY',
  'E2_NO_E1_WITHIN_K',
  'ENGINE_NEGATIVE',
  'ENGINE_NEGATIVE_BASENAME',
  'ENGINE_UNCERTAIN',
  'ENGINE_INVALID_PROC',
  'INVALID_PROC',
  'NOT_ENGINE',
  // Supervision leg (C1)
  'SUPERVISED',
  'UNSUPERVISED',
  'SUPERVISION_UNCERTAIN',
  'INVALID_CANDIDATE',
  'MISSING_PARENT',
  'MISSING_ANCESTOR',
  'PPID_CYCLE',
  'CREATETIME_INVERSION',
  'CREATE_TIME_INVERSION',
  'HOST_ALLOWLIST_ANCESTOR',
  'WALK_COMPLETE_SYSTEM_ROOT',
  'DEPTH_TRUNCATION',
  'WALK_DEPTH_TRUNCATION',
  'ORPHAN_DETACHED_SPENDER',
  // Spend leg (W4 atlas)
  'SPEND_POSITIVE',
  'SPEND_NEGATIVE',
  'SPEND_UNCERTAIN',
  'SPEND_ATLAS_STALE',
  'SPEND_PORT_443_ALONE',
  'SPEND_ATTRIBUTION_UNREADABLE',
  'SPEND_ATLAS_EMPTY',
  'SPEND_ATLAS_VERSION_MISMATCH',
  // Ownership leg (W3)
  'OWNERSHIP_IPC_STUB',
  'OWNERSHIP_IPC_FAIL_CLOSED',
  'OWNERSHIP_REGISTERED_KEEP',
  'OWNERSHIP_NOT_REGISTERED',
  'OWNERSHIP_TRANSPORT_ERROR',
  'OWNERSHIP_TIMEOUT',
  'OWNERSHIP_UNAUTHENTICATED',
  'OWNERSHIP_INVALID_IDENTITY',
  'OWNERSHIP_REGISTRY_READ_ERROR',
  // Quad verdicts (W3 skeleton)
  'QUAD_JOINT_POSITIVE',
  'QUAD_ABSTAIN_UNCERTAIN_LEG',
  'QUAD_KEEP',
  'VERDICT_ABSTAIN',
  'VERDICT_KEEP',
  'VERDICT_WOULD_BE_RED',
  // Surface / freeze scaffold (W6 sole boundary)
  'FREEZE_UNAVAILABLE',
  'FREEZE_CAPABILITY_FALSE',
  'FREEZE_IDENTITY_MISMATCH',
  'FREEZE_IDENTITY_REQUIRED',
  'FREEZE_SUSPEND_FAILED',
  'FREEZE_OWNERSHIP_RACE_ABORT',
  'KILL_DISABLED',
  'KILL_WITHOUT_FREEZE_DISABLED',
  'KILL_CONFIRM_REQUIRED',
  'KILL_CONFIRM_INVALID',
  'KILL_AUTHZ_DENIED',
  'KILL_TREE_FAILED',
  'KILL_DEATH_UNVERIFIED',
  'KILL_OWNERSHIP_RACE_ABORT',
  'ANCHOR_OWNED_NO_NODE_KILL',
  'FREEZE_KILL_FORBIDDEN',
  'SPEND_POSTCONDITION_STOPPED',
  'SPEND_POSTCONDITION_CONTINUES',
  'SPEND_POSTCONDITION_UNCERTAIN',
  // W7 / SC4 cache-first radar + JSON-safe sweep
  'SWEEP_ERROR',
  'CACHE_STALE',
  'CACHE_ONLY_IDENTITY_REFUSED',
  'CACHED_NON_ACTIONABLE',
  'WHY_FROM_CACHE',
  'UNCERTAIN_NOT_RED',
  'FREEZE_BEFORE_KILL',
]);

const CLASSIFIER_REASON_SET = new Set(CLASSIFIER_REASON_CODES);

/**
 * Doctor issue ID seed catalog — 1:1 fields for health-banner → Doctor seed.
 * id is stable; component/suggestedChecks are seed defaults.
 */
const DOCTOR_ISSUE_IDS = Object.freeze([
  Object.freeze({
    id: 'ZH_MODE_SHADOW_FORCED',
    component: 'classifier-mode',
    message: 'classifierMode forced to shadow (missing or mismatched canaryReceipt)',
    suggestedChecks: Object.freeze([
      'Check ZH_CLASSIFIER_MODE and canaryReceipt hashes',
      'Confirm SC1 canary gate before arm',
    ]),
  }),
  Object.freeze({
    id: 'ZH_CANARY_RECEIPT_MISSING',
    component: 'canary-receipt',
    message: 'No version-matched canaryReceipt; armed RED impossible',
    suggestedChecks: Object.freeze([
      'Run SC1 canary pack',
      'Write canaryReceipt with matching classifier/atlas hashes',
    ]),
  }),
  Object.freeze({
    id: 'ZH_OWNERSHIP_IPC_FAIL',
    component: 'ownership',
    message: 'Ownership IPC fail-closed (error/timeout) — process treated as KEEP',
    suggestedChecks: Object.freeze([
      'Verify Anchor registry reachable',
      'Inspect OWNERSHIP_IPC_FAIL_CLOSED reason codes on candidate',
    ]),
  }),
  Object.freeze({
    id: 'ZH_SUPERVISION_UNCERTAIN',
    component: 'host-walk',
    message: 'Host-walk returned UNCERTAIN — abstain (never unsupervised RED)',
    suggestedChecks: Object.freeze([
      'Inspect parent chain / createTime / depth',
      'Confirm process tree enumeration complete',
    ]),
  }),
  Object.freeze({
    id: 'ZH_SPEND_ATLAS_STALE',
    component: 'spend-atlas',
    message: 'Spend atlas stale or empty — no invented spend',
    suggestedChecks: Object.freeze([
      'Refresh spend atlas version',
      'Confirm process-owned sockets + SNI allowlist path',
    ]),
  }),
  Object.freeze({
    id: 'ZH_SWEEP_ERROR',
    component: 'sweep',
    message: 'Sweep parse or worker error — abstain, never invent RED',
    suggestedChecks: Object.freeze([
      'Read sweepError field',
      'Re-run scan; check control-char safety of process JSON',
    ]),
  }),
  Object.freeze({
    id: 'ZH_QUAD_ABSTAIN',
    component: 'classifier-quad',
    message: 'Quad predicate abstained (uncertain leg or incomplete joint positive)',
    suggestedChecks: Object.freeze([
      'Inspect per-leg statuses on Why payload',
      'Confirm engine/spend/supervision/ownership legs',
    ]),
  }),
  Object.freeze({
    id: 'ZH_FREEZE_UNAVAILABLE',
    component: 'freeze',
    message: 'Freeze/Kill disabled (shadow, no freezeCapability, or authz denied on sole boundary)',
    suggestedChecks: Object.freeze([
      'Check freezeKillEnabled and freezeCapability (non-elevated operator envelope)',
      'Confirm sole boundary is freeze.js (NtSuspendProcess) — SoftFreeze/Thread.Suspend is gone',
      'Kill requires server-validated confirm token from /api/kill-confirm',
    ]),
  }),
  Object.freeze({
    id: 'ZH_ANCHOR_OWNED_KEEP',
    component: 'ownership',
    message: 'Process is Anchor-registered — KEEP, no Node reap',
    suggestedChecks: Object.freeze([
      'Confirm ownership badge owned=true',
      'Use Anchor reaper path for registered sessions, not Node kill',
    ]),
  }),
  // W9 / SC7 — dashboard health + reaper-health banners → Doctor seed
  Object.freeze({
    id: 'ZH_HEALTH_CHECK_ISSUES',
    component: 'health-check',
    message: 'Dashboard health check found issues — diagnose in Doctor (not a markdown path)',
    suggestedChecks: Object.freeze([
      'Open Doctor from the health banner (seeded issue context)',
      'Inspect latest health_reports entry via Doctor, not a static file link alone',
      'Re-run diagnostics if status is stale',
    ]),
  }),
  Object.freeze({
    id: 'ZH_REAPER_ABSTAIN_STREAK',
    component: 'reaper-health',
    message: 'Reaper consecutive-abstain streak — liveness inputs may be broken; reaper flying blind',
    suggestedChecks: Object.freeze([
      'Run reaper explain (read-only) and inspect live_owner_ids',
      'Check liveness snapshot degraded flag and owner enumeration inputs',
      'Confirm reaper is unarmed/disarmed until inputs recover',
    ]),
  }),
  Object.freeze({
    id: 'ZH_REAPER_CHAIN_TAMPERED',
    component: 'reaper-health',
    message: 'Reaper owner-evidence receipt chain failed verification — audit log may be tampered',
    suggestedChecks: Object.freeze([
      'Verify receipt chain hashes under .anchor/',
      'Do not arm or advance reaper tier until chain verifies',
      'Inspect last owner-evidence receipt entries',
    ]),
  }),
]);

const DOCTOR_ISSUE_BY_ID = new Map(DOCTOR_ISSUE_IDS.map((x) => [x.id, x]));

/**
 * @param {string} code
 * @returns {boolean}
 */
function isKnownReasonCode(code) {
  return CLASSIFIER_REASON_SET.has(String(code || ''));
}

/**
 * Filter to known codes only (closed catalog enforcement).
 * @param {string[]} codes
 * @returns {string[]}
 */
function filterKnownReasonCodes(codes) {
  if (!Array.isArray(codes)) return [];
  const out = [];
  for (const c of codes) {
    const s = String(c || '');
    if (CLASSIFIER_REASON_SET.has(s) && !out.includes(s)) out.push(s);
  }
  return out;
}

/**
 * @param {string} issueId
 * @returns {object|null}
 */
function getDoctorIssue(issueId) {
  return DOCTOR_ISSUE_BY_ID.get(String(issueId || '')) || null;
}

/**
 * Public payload for server /api/state (versioned closed catalogs).
 */
function getCatalogsPublicPayload() {
  return {
    reasonCatalogVersion: REASON_CATALOG_VERSION,
    doctorIssueCatalogVersion: DOCTOR_ISSUE_CATALOG_VERSION,
    reasonCodes: CLASSIFIER_REASON_CODES.slice(),
    doctorIssues: DOCTOR_ISSUE_IDS.map((x) => ({
      id: x.id,
      component: x.component,
      message: x.message,
      suggestedChecks: x.suggestedChecks.slice(),
    })),
  };
}

/**
 * Assert all codes are in the closed catalog (test helper).
 * @param {string[]} codes
 * @returns {{ ok: boolean, unknown: string[] }}
 */
function assertCodesClosed(codes) {
  const unknown = [];
  for (const c of codes || []) {
    if (!isKnownReasonCode(c)) unknown.push(String(c));
  }
  return { ok: unknown.length === 0, unknown };
}

module.exports = {
  REASON_CATALOG_VERSION,
  DOCTOR_ISSUE_CATALOG_VERSION,
  CLASSIFIER_REASON_CODES,
  DOCTOR_ISSUE_IDS,
  isKnownReasonCode,
  filterKnownReasonCodes,
  getDoctorIssue,
  getCatalogsPublicPayload,
  assertCodesClosed,
};
