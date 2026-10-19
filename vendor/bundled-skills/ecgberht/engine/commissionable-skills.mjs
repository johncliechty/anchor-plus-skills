/**
 * Wave 5 — commissionable-skills table (S8) + early SC6 feasibility verdict.
 *
 * ONE pure generator: deriveCommissionableSkills(g4Evidence, haltInventory)
 *   commissionable === (executor_proven && halt_class === "EXTERNALLY-OBSERVABLE")
 *
 * Never hand-edit artifacts/commissionable-skills.json — regenerate via this
 * module. Hand-edits are detected by regeneration byte-identity in CI.
 *
 * EARLY SC6: commissionable_count >= 2 → FEASIBLE; else HALT for John's
 * scope decision BEFORE Wave 6+ builds.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  writeFileAtomicSync,
  withFileLock,
  writeJsonIdempotentSync,
} from './durable-write.mjs';
import { COMMISSION_SKILLS } from './commission.mjs';
import {
  buildHaltInventory,
  skillHaltClass,
  HALT_INVENTORY_SCHEMA,
} from './halt-inventory.mjs';
import { evaluateG4Evidence, EVIDENCE_CLASS } from './g4-verdict.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(ENGINE_DIR, '..');

export const COMMISSIONABLE_SKILLS_SCHEMA = 'ecgberht-commissionable-skills-v0';
export const SC6_FEASIBILITY_SCHEMA = 'ecgberht-sc6-feasibility-v0';
export const SC6_MIN_COMMISSIONABLE = 2;

export const COMMISSIONABLE_SKILLS_REL = path.join(
  'artifacts',
  'commissionable-skills.json',
);
export const SC6_FEASIBILITY_REL = path.join(
  'artifacts',
  'sc6-feasibility.json',
);
export const HALT_INVENTORY_REL = path.join('artifacts', 'halt-inventory.json');

/**
 * Normalize g4 evidence into a list of per-skill evidence objects.
 * Accepts a single evidence object, { skills: [...] }, or an array.
 *
 * @param {object|object[]|null} g4Evidence
 * @returns {object[]}
 */
export function normalizeG4EvidenceList(g4Evidence) {
  if (g4Evidence == null) return [];
  if (Array.isArray(g4Evidence)) return g4Evidence.filter(Boolean);
  if (Array.isArray(g4Evidence.skills)) return g4Evidence.skills.filter(Boolean);
  if (Array.isArray(g4Evidence.evidence)) {
    return g4Evidence.evidence.filter(Boolean);
  }
  // Single evidence object (Wave-4 standing shape)
  if (g4Evidence.skill || g4Evidence.cmdline || g4Evidence.pid != null) {
    return [g4Evidence];
  }
  return [];
}

/**
 * Whether observed evidence proves the executor for that skill (anti-stub).
 * Uses evaluateG4Evidence — never free-booleans alone.
 *
 * @param {object} evidence
 * @returns {boolean}
 */
export function isExecutorProven(evidence) {
  if (!evidence || typeof evidence !== 'object') return false;
  const v = evaluateG4Evidence(evidence);
  return v.verdict === 'PASS';
}

/**
 * The evidence class of an entry (SC6 corrective, journal 0074).
 * Recorded at observation time by the G4 recorder; for legacy entries with no
 * stamp, a `gate/…` entry path is honestly classed `harness`, everything else
 * `unknown`. NEVER infers `live-skill` — that class is only ever earned by a
 * realpath resolution at record time.
 *
 * @param {object|null|undefined} evidence
 * @returns {'harness'|'live-skill'|'unknown'}
 */
export function evidenceClassOf(evidence) {
  const cls = evidence?.evidence_class;
  if (
    cls === EVIDENCE_CLASS.HARNESS ||
    cls === EVIDENCE_CLASS.LIVE_SKILL ||
    cls === EVIDENCE_CLASS.UNKNOWN
  ) {
    return cls;
  }
  const rel = Array.isArray(evidence?.evidence_paths)
    ? evidence.evidence_paths[0]
    : null;
  if (typeof rel === 'string' && rel.replace(/\\/g, '/').startsWith('gate/')) {
    return EVIDENCE_CLASS.HARNESS;
  }
  return EVIDENCE_CLASS.UNKNOWN;
}

/**
 * THE ONE pure generator. Never hand-sets commissionable.
 *
 * @param {object|object[]|null} g4Evidence
 * @param {object|null} haltInventory
 * @param {{ candidateSkills?: string[] }} [opts]
 * @returns {{
 *   schema: string,
 *   generated_by: 'deriveCommissionableSkills',
 *   rows: object[],
 *   commissionable_count: number,
 * }}
 */
export function deriveCommissionableSkills(
  g4Evidence,
  haltInventory,
  opts = {},
) {
  const candidates = opts.candidateSkills ?? [...COMMISSION_SKILLS];
  const evidenceList = normalizeG4EvidenceList(g4Evidence);
  const bySkill = new Map();
  // Preference order: live-skill PASS > harness/unknown PASS > anything else.
  const rank = (ev) =>
    (isExecutorProven(ev) ? 2 : 0) * 2 +
    (evidenceClassOf(ev) === EVIDENCE_CLASS.LIVE_SKILL ? 1 : 0);
  for (const ev of evidenceList) {
    const skill = ev.skill || null;
    if (!skill) continue;
    const prev = bySkill.get(skill);
    if (!prev || rank(ev) > rank(prev)) {
      bySkill.set(skill, ev);
    }
  }

  const inv =
    haltInventory && typeof haltInventory === 'object'
      ? haltInventory
      : buildHaltInventory();
  const skillClasses = inv.skill_classes || {};
  const gates = inv.gates || [];

  const rows = [];
  for (const skill of candidates) {
    const ev = bySkill.get(skill) ?? null;
    const executor_proven = ev ? isExecutorProven(ev) : false;
    const evidence_class = ev ? evidenceClassOf(ev) : null;
    const halt_class =
      skillClasses[skill] ??
      skillHaltClass(skill, gates) ??
      'INVISIBLE';
    const executor_evidence =
      executor_proven && ev
        ? {
            pid: ev.pid ?? null,
            proc_create_time: ev.proc_create_time ?? null,
            handback_id: ev.handback_id ?? null,
          }
        : null;

    // commissionable is COMPUTED — never taken from input. SC6 corrective
    // (journal 0074): only LIVE-SKILL evidence counts. A harness stand-in
    // still proves the HANDBACK CONTRACT (Wave 4 stays green) but never makes
    // a skill commissionable — SC6 means what it says.
    const commissionable =
      executor_proven === true &&
      halt_class === 'EXTERNALLY-OBSERVABLE' &&
      evidence_class === EVIDENCE_CLASS.LIVE_SKILL;

    let excluded_reason = null;
    if (!executor_proven) {
      excluded_reason = 'executor_not_proven';
    } else if (halt_class !== 'EXTERNALLY-OBSERVABLE') {
      excluded_reason = `halt_class_${halt_class}`;
    } else if (evidence_class === EVIDENCE_CLASS.HARNESS) {
      excluded_reason = 'harness_evidence_only';
    } else if (evidence_class !== EVIDENCE_CLASS.LIVE_SKILL) {
      excluded_reason = 'evidence_class_unknown';
    }

    rows.push({
      skill,
      executor_proven,
      executor_evidence,
      evidence_class,
      halt_class,
      excluded_reason,
      commissionable,
    });
  }

  // Stable order by candidate list
  const commissionable_count = rows.filter((r) => r.commissionable).length;

  return {
    schema: COMMISSIONABLE_SKILLS_SCHEMA,
    generated_by: 'deriveCommissionableSkills',
    rows,
    commissionable_count,
  };
}

/**
 * Early SC6 feasibility verdict from a derived table (or count).
 *
 * @param {object|number} derivedOrCount
 * @returns {{
 *   schema: string,
 *   commissionable_count: number,
 *   min_required: number,
 *   verdict: 'FEASIBLE'|'HALT',
 *   reason: string,
 * }}
 */
export function evaluateSc6Feasibility(derivedOrCount) {
  const count =
    typeof derivedOrCount === 'number'
      ? derivedOrCount
      : Number(derivedOrCount?.commissionable_count ?? 0);
  const ok = count >= SC6_MIN_COMMISSIONABLE;
  return {
    schema: SC6_FEASIBILITY_SCHEMA,
    commissionable_count: count,
    min_required: SC6_MIN_COMMISSIONABLE,
    verdict: ok ? 'FEASIBLE' : 'HALT',
    reason: ok
      ? `commissionable_count ${count} >= ${SC6_MIN_COMMISSIONABLE}`
      : `commissionable_count ${count} < ${SC6_MIN_COMMISSIONABLE} — HALT for John's North-Star/non-goal decision BEFORE Wave 6+ spend`,
  };
}

/**
 * Canonical JSON serialization for byte-identity checks (stable key order
 * via recursive key sort; trailing newline).
 * @param {*} obj
 * @returns {string}
 */
export function stableStringify(obj) {
  return `${JSON.stringify(sortKeysDeep(obj), null, 2)}\n`;
}

/** @param {*} value @returns {*} */
function sortKeysDeep(value) {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value && typeof value === 'object') {
    const out = {};
    for (const k of Object.keys(value).sort()) {
      out[k] = sortKeysDeep(value[k]);
    }
    return out;
  }
  return value;
}

/**
 * @param {string} [root]
 */
export function haltInventoryPath(root = DEFAULT_ROOT) {
  return path.join(root, HALT_INVENTORY_REL);
}

/**
 * @param {string} [root]
 */
export function commissionableSkillsPath(root = DEFAULT_ROOT) {
  return path.join(root, COMMISSIONABLE_SKILLS_REL);
}

/**
 * @param {string} [root]
 */
export function sc6FeasibilityPath(root = DEFAULT_ROOT) {
  return path.join(root, SC6_FEASIBILITY_REL);
}

/**
 * Load g4-evidence.json from artifacts (observed only).
 * @param {string} [root]
 */
export function loadG4Evidence(root = DEFAULT_ROOT) {
  const p = path.join(root, 'artifacts', 'g4-evidence.json');
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

/**
 * Load or build halt inventory.
 * @param {string} [root]
 */
export function loadHaltInventory(root = DEFAULT_ROOT) {
  const p = haltInventoryPath(root);
  if (fs.existsSync(p)) {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  }
  return buildHaltInventory();
}

/**
 * Write halt-inventory.json (S8 writer for this artifact).
 * @param {object} [inventory]
 * @param {{ root?: string }} [opts]
 */
export function writeHaltInventory(inventory, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const outPath = haltInventoryPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const body = inventory ?? buildHaltInventory();
  if (body.schema !== HALT_INVENTORY_SCHEMA) {
    body.schema = HALT_INVENTORY_SCHEMA;
  }
  const payload = {
    ...body,
    written_by: 'halt-inventory.mjs',
  };
  // Idempotent: unchanged inventory leaves the file byte-identical (0070 fix).
  writeJsonIdempotentSync(outPath, payload);
  return outPath;
}

/**
 * Build the on-disk commissionable-skills payload (single shape for write + detect).
 * @param {object|object[]|null} g4Evidence
 * @param {object|null} haltInventory
 * @returns {object}
 */
export function buildCommissionableSkillsPayload(g4Evidence, haltInventory) {
  const derived = deriveCommissionableSkills(g4Evidence, haltInventory);
  return {
    ...derived,
    written_by: 'deriveCommissionableSkills',
    source_inputs: {
      g4_evidence: 'artifacts/g4-evidence.json',
      halt_inventory: 'artifacts/halt-inventory.json',
    },
  };
}

/**
 * Derive + write commissionable-skills.json (never hand-edit).
 * @param {{ root?: string, g4Evidence?: object, haltInventory?: object }} [opts]
 */
export function writeCommissionableSkills(opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const g4 = opts.g4Evidence ?? loadG4Evidence(root);
  const inv = opts.haltInventory ?? loadHaltInventory(root);
  const payload = buildCommissionableSkillsPayload(g4, inv);
  const outPath = commissionableSkillsPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  // Strip any hand-stamped commissionable on rows by re-deriving only.
  // Idempotent: unchanged derivation leaves the file byte-identical (0070 fix).
  writeJsonIdempotentSync(outPath, payload);
  return { path: outPath, derived: payload };
}

/**
 * Write sc6-feasibility.json from derived table.
 * @param {{ root?: string, derived?: object }} [opts]
 */
export function writeSc6Feasibility(opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  let derived = opts.derived;
  if (!derived) {
    const g4 = loadG4Evidence(root);
    const inv = loadHaltInventory(root);
    derived = deriveCommissionableSkills(g4, inv);
  }
  const verdict = evaluateSc6Feasibility(derived);
  const outPath = sc6FeasibilityPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  const payload = {
    ...verdict,
    written_by: 'commissionable-skills.mjs',
    source: 'deriveCommissionableSkills',
  };
  // Idempotent: unchanged verdict leaves the file byte-identical (0070 fix).
  writeJsonIdempotentSync(outPath, payload);
  return { path: outPath, verdict: payload };
}

/**
 * Detect hand-edit: re-derive and compare to on-disk commissionable-skills.json.
 * Uses the same payload builder as writeCommissionableSkills. Comparison is on
 * canonical JSON (parse → stableStringify) so CRLF/checkout noise is not a
 * false hand-edit — content divergence still fails.
 * @param {string} [root]
 * @returns {{ ok: boolean, hand_edit_detected: boolean, message: string }}
 */
export function detectCommissionableHandEdit(root = DEFAULT_ROOT) {
  const onDiskPath = commissionableSkillsPath(root);
  if (!fs.existsSync(onDiskPath)) {
    return {
      ok: false,
      hand_edit_detected: false,
      message: 'commissionable-skills.json missing',
    };
  }
  const onDiskRaw = fs.readFileSync(onDiskPath, 'utf8');
  let onDiskCanonical;
  try {
    onDiskCanonical = stableStringify(JSON.parse(onDiskRaw));
  } catch {
    return {
      ok: false,
      hand_edit_detected: true,
      message: 'hand-edit detected — on-disk commissionable-skills.json is not valid JSON',
    };
  }
  const g4 = loadG4Evidence(root);
  const inv = loadHaltInventory(root);
  const expected = stableStringify(buildCommissionableSkillsPayload(g4, inv));
  const hand_edit_detected = onDiskCanonical !== expected;
  return {
    ok: !hand_edit_detected,
    hand_edit_detected,
    message: hand_edit_detected
      ? 'hand-edit detected — regenerate via deriveCommissionableSkills'
      : 'byte-identical to pure generator',
  };
}

/**
 * Regenerate all Wave-5 skill-table artifacts (halt inventory → skills → sc6).
 * @param {{ root?: string }} [opts]
 */
export function regenerateSkillsArtifacts(opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  writeHaltInventory(buildHaltInventory(), { root });
  const { derived } = writeCommissionableSkills({ root });
  const { verdict } = writeSc6Feasibility({ root, derived });
  return { derived, verdict };
}
