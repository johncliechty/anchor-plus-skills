// bin/lineage-enum.mjs — Wave 7 closed attested-lineage enum gate (crit-5, HALT-for-human).
//
// G8 cross-lineage origin fusion (Enhanced) recovers a correlated blind spot ONLY by counting a
// genuinely DISTINCT attested lineage as a new independent origin (I3). Which lineages are
// "attested distinct" is a RESERVED HUMAN DECISION (MASTER-PLAN crit-5 / DESCRIPTION "Reserved /
// halt-worthy"): the closed enum must be committed by a human BEFORE any cross-lineage origin can
// be claimed, exactly like the pre-registered thresholds (Wave 1, bin/preregistration.mjs).
//
// Until a human commits a real enum in lineage-enum.json, this gate is PENDING — the
// `test/lineage-enum.test.mjs` gate signals a HALT-for-human (a SKIP carrying the HALT reason,
// the same mechanism Wave 1 used so `node --test` stays exit 0 while still surfacing the HALT),
// and G8 stays INERT behind its flag (bin/round.mjs `g8FuseOrigins({ enabled:false })`) so the
// rest of Wave 7 (the dry/empty/suspicious predicates, G9 debate, the Synthesizer/Judge seams)
// reaches GREEN meanwhile. Once committed, `committedLineages()` returns the closed set the shared
// independence-accounting module consumes as its `attestedLineages` (which can only TIGHTEN the
// origin count — off-enum lineages collapse into one capped bucket; it never invents an origin).
//
// This module NEVER invents or defaults the enum; choosing the attested lineages is the human's
// decision and the placeholder sentinel makes an un-set value impossible to miss.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// The exact sentinel that marks an un-committed field in lineage-enum.json. Any field equal to
// this, equal to null, or absent is treated as NOT committed.
export const PLACEHOLDER = '__PREREGISTER_LINEAGE_ENUM__';

// Default location of the committed enum, relative to this file (project root).
export const LINEAGE_ENUM_FILE = new URL('../lineage-enum.json', import.meta.url);

// The North Star wants HETEROGENEOUS ≥2-agree reviewers, so a meaningful closed enum names at
// least two distinct attested lineages — one lineage can never furnish the ≥2 independent origins
// the static quorum floor requires. A committed enum smaller than this is gate corruption.
export const MIN_LINEAGES = 2;

/**
 * The required fields of a committed enum, each with a validator. `validate(v)` returns null when
 * acceptable, or a string reason when not. `lineages` is the closed attested set; committed_by /
 * committed_date are the I6-style human attestation (WHO + WHEN), mirroring preregistration.
 */
export const REQUIRED_FIELDS = [
  { key: 'lineages', serves: 'crit-5 closed attested-lineage enum (≥2 distinct non-empty strings)', validate: lineageList },
  { key: 'committed_by', serves: 'crit-5 human attestation — WHO committed the enum', validate: nonEmptyString },
  { key: 'committed_date', serves: 'crit-5 human attestation — WHEN (before any cross-lineage claim)', validate: isoDate },
];

function isPlaceholder(v) {
  return v === undefined || v === null || v === PLACEHOLDER;
}

/** A closed attested-lineage list: ≥MIN_LINEAGES distinct, non-empty, non-placeholder strings. */
function lineageList(v) {
  if (!Array.isArray(v)) return 'must be an array of attested-lineage strings';
  const cleaned = v.map((s) => (typeof s === 'string' ? s.trim() : s));
  if (cleaned.some((s) => typeof s !== 'string' || s.length === 0)) {
    return 'every lineage must be a non-empty string';
  }
  if (cleaned.some((s) => s === PLACEHOLDER)) return 'a lineage is still the placeholder sentinel';
  if (new Set(cleaned).size !== cleaned.length) return 'lineages must be distinct (no duplicates)';
  if (cleaned.length < MIN_LINEAGES) return `must name at least ${MIN_LINEAGES} distinct lineages`;
  return null;
}

function nonEmptyString(v) {
  return typeof v === 'string' && v.trim().length > 0 ? null : 'must be a non-empty string';
}

function isoDate(v) {
  // Attestation integrity: the WHEN must be a real calendar date, not just a well-formed string
  // (same rule as preregistration — reject impossible dates like 2026-13-45).
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) {
    return 'must be an ISO date string (YYYY-MM-DD)';
  }
  const [y, m, d] = v.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) {
    return 'must be a real calendar date (YYYY-MM-DD), not just a well-formed string';
  }
  return null;
}

/**
 * Load the committed enum. Returns the parsed object, or {} ONLY if the file is absent (an absent
 * file means nothing committed yet → every field reads as a placeholder). A file that is PRESENT
 * but unreadable or malformed is corruption, NOT "nothing committed" — surfaced, never swallowed
 * (the same contract as loadPreregistration).
 */
export function loadLineageEnum(file = LINEAGE_ENUM_FILE) {
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (err) {
    if (err && err.code === 'ENOENT') return {};
    throw err; // present-but-unreadable (perms, I/O, a directory) — corruption, do not mask.
  }
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw new Error(
      `lineage-enum file is present but is not valid JSON (${file}): ${err.message}. ` +
        `Fix the file — a malformed enum must not silently read as un-committed.`,
    );
  }
}

/**
 * Validate the committed enum against REQUIRED_FIELDS.
 * @returns {{ committed: boolean, pending: string[], invalid: Array<{key:string,reason:string}> }}
 * `committed` is true only when every required field is present, non-placeholder, and passes its
 * validator. `pending` lists fields still at placeholder; `invalid` lists committed-but-bad fields.
 */
export function validateLineageEnum(enumObj = loadLineageEnum()) {
  const pending = [];
  const invalid = [];
  for (const { key, validate } of REQUIRED_FIELDS) {
    const v = enumObj[key];
    if (isPlaceholder(v)) {
      pending.push(key);
      continue;
    }
    const reason = validate(v);
    if (reason) invalid.push({ key, reason });
  }
  return { committed: pending.length === 0 && invalid.length === 0, pending, invalid };
}

/**
 * The committed closed attested-lineage set, or [] when the enum is still PENDING / invalid. This
 * is the single accessor the round orchestrator passes to the shared module as `attestedLineages`;
 * returning [] until committed is what keeps G8 inert (no enum ⇒ no cross-lineage origin claim).
 * @returns {string[]}
 */
export function committedLineages(enumObj = loadLineageEnum()) {
  const { committed } = validateLineageEnum(enumObj);
  return committed ? enumObj.lineages.map((s) => s.trim()) : [];
}

// Convenience for human inspection / CLI: `node bin/lineage-enum.mjs`.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = validateLineageEnum();
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.committed ? 0 : 1);
}
