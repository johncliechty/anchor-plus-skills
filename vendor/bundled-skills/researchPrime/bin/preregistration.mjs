// bin/preregistration.mjs — Wave 1 pre-registration gate (I6 "no gamed gates").
//
// The thresholds that decide every later acceptance criterion MUST be committed by a
// human BEFORE any measurement is taken (MASTER-PLAN I6; DESCRIPTION "Reserved /
// halt-worthy"). This module is the REAL source the RED-gate test exercises: it loads
// preregistration.json and reports, per required threshold, whether a human has committed
// a non-placeholder value. Until they have, validation FAILS — the test is RED — and
// Foreman HALTs for the human (IMPLEMENTATION-PLAN Wave 1 HALT-for-human). Resume is
// automatic once real values are committed and the suite goes GREEN.
//
// This module NEVER invents or defaults a threshold; choosing the numbers is a reserved
// human decision and the placeholder sentinel makes an un-set value impossible to miss.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// The exact sentinel that marks an un-committed value in preregistration.json. Any field
// equal to this, equal to null, or absent is treated as NOT committed.
export const PLACEHOLDER = '__PREREGISTER__';

// Default location of the committed thresholds, relative to this file (project root).
export const PREREGISTRATION_FILE = new URL('../preregistration.json', import.meta.url);

/**
 * The pre-registered thresholds, each tagged with the criterion/invariant it gates and a
 * validator. `validate(v)` returns null if acceptable, or a string reason if not.
 * G/X%/C_min/N/K/M come from MASTER-PLAN crit 1–7; T and N_min are the Wave-9 ρ̂ gates
 * pulled in by the v6 amendment (IMPLEMENTATION-PLAN Wave 1 done-when (d)).
 */
export const REQUIRED_THRESHOLDS = [
  { key: 'G', serves: 'crit-1 gap-closure target (% of single-pass miss rate closed)', validate: pct },
  { key: 'X_pct', serves: 'crit-2 bounded low-stakes overhead cap (%)', validate: pct },
  { key: 'C_min', serves: 'I2 correlated-blind-spot recall floor (0..1)', validate: unit },
  { key: 'N', serves: 'I7 dry-round convergence threshold (rounds)', validate: posInt },
  { key: 'K', serves: 'I7 suspiciously-dry round bound (high-stakes)', validate: posInt },
  { key: 'M', serves: 'I7 unresolved high-severity finding bound', validate: nonNegInt },
  { key: 'T', serves: 'Wave-9 ρ̂ estimator round-trip tolerance (0..1)', validate: unit },
  { key: 'N_min', serves: 'Wave-9 ρ̂ calibration minimum sample count (cold-start floor)', validate: posInt },
  { key: 'committed_by', serves: 'I6 human attestation — WHO pre-registered these', validate: nonEmptyString },
  { key: 'committed_date', serves: 'I6 human attestation — WHEN these were pre-registered (before any measurement)', validate: isoDate },
];

function isPlaceholder(v) {
  return v === undefined || v === null || v === PLACEHOLDER;
}
function pct(v) {
  return typeof v === 'number' && Number.isFinite(v) && v > 0 && v <= 100 ? null : 'must be a number in (0, 100]';
}
function unit(v) {
  return typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1 ? null : 'must be a number in [0, 1]';
}
function posInt(v) {
  return Number.isInteger(v) && v >= 1 ? null : 'must be an integer >= 1';
}
function nonNegInt(v) {
  return Number.isInteger(v) && v >= 0 ? null : 'must be an integer >= 0';
}
function nonEmptyString(v) {
  return typeof v === 'string' && v.trim().length > 0 ? null : 'must be a non-empty string';
}
function isoDate(v) {
  // I6 attestation integrity: the WHEN of pre-registration must be a trustworthy date,
  // so regex shape (necessary) is not sufficient — it would accept impossible calendar
  // dates like 2026-13-45 or 2026-02-30. Require the components to round-trip through a
  // UTC Date so only real calendar dates pass.
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
 * Load the committed thresholds. Returns the parsed object, or {} ONLY if the file is absent
 * (an absent file means nothing is committed yet → every threshold reads as a placeholder).
 *
 * A file that is PRESENT but unreadable or malformed is data corruption, NOT "nothing
 * committed" — swallowing it would mask the corruption as a clean HALT-for-human and let a
 * broken pre-registration read as an honest blank. So we only tolerate ENOENT; any other read
 * error, and any JSON parse error, is surfaced.
 */
export function loadPreregistration(file = PREREGISTRATION_FILE) {
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
      `preregistration file is present but is not valid JSON (${file}): ${err.message}. ` +
        `Fix the file — a malformed pre-registration must not silently read as un-committed.`,
    );
  }
}

/**
 * Validate the committed thresholds against REQUIRED_THRESHOLDS.
 * @returns {{ committed: boolean, pending: string[], invalid: Array<{key:string,reason:string}> }}
 * `committed` is true only when EVERY required threshold is present, non-placeholder, and
 * passes its validator. `pending` lists keys still at placeholder; `invalid` lists keys
 * whose committed value fails its validator.
 */
export function validatePreregistration(prereg = loadPreregistration()) {
  const pending = [];
  const invalid = [];
  for (const { key, validate } of REQUIRED_THRESHOLDS) {
    const v = prereg[key];
    if (isPlaceholder(v)) {
      pending.push(key);
      continue;
    }
    const reason = validate(v);
    if (reason) invalid.push({ key, reason });
  }
  return { committed: pending.length === 0 && invalid.length === 0, pending, invalid };
}

// Convenience for human inspection / CLI: `node bin/preregistration.mjs`.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = validatePreregistration();
  console.log(JSON.stringify(result, null, 2));
  process.exit(result.committed ? 0 : 1);
}
