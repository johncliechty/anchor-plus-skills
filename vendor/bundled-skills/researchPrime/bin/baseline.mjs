// bin/baseline.mjs — Wave 3 single-pass baseline: capture the "current researchPrime Phase-3"
// recall on the power-calc-sized fixture as a NAMED, HASHED artifact (IMPLEMENTATION-PLAN Wave 3
// done-when: "recall committed as a named, hashed artifact; test/baseline.test.mjs asserts
// existence + hash match (later waves LOAD it by hash; regeneration ⇒ RED)").
//
// The baseline is the gap-closure DENOMINATOR — the single-pass miss rate that the pre-registered
// G is a fraction of (MASTER-PLAN crit 1) — and the per-class breakout later waves measure the
// loop against (IMPLEMENTATION-PLAN Wave 6: "recall measured by LOADING the Wave-3 baseline by
// hash, broken out by source gate AND CBS class"). It must therefore be FROZEN: the artifact is
// content-addressed by the sha256 of its canonical payload, and `loadBaselineByHash` refuses any
// artifact whose payload no longer hashes to the expected name. Regenerating from a drifted
// fixture changes the payload ⇒ changes the hash ⇒ the load (and the Wave-3 gate) goes RED.
//
// This module is PURE except for the file read/write helpers (loadFixture / write*): the recall
// computation and the hash are deterministic functions of the manifest, with no clock/random.

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

import { generateFixture, singlePassCatches, RECALL_CLASSES } from './fixture.mjs';
import { powerCalc } from './power-calc.mjs';

// ── On-disk locations of the frozen fixture + the named baseline artifact ────────────────────
export const FIXTURE_DIR = new URL('../fixtures/', import.meta.url);
export const CORPUS_FILE = new URL('corpus.jsonl', FIXTURE_DIR);
export const DEFECTS_FILE = new URL('defects.jsonl', FIXTURE_DIR);
export const BASELINE_FILE = new URL('../baseline/single-pass-baseline.json', import.meta.url);

// The artifact's stable name + schema version. The CONTENT name is the payload hash (below).
export const ARTIFACT_NAME = 'single-pass-baseline';
export const SCHEMA_VERSION = 1;

// ── Canonical serialization + content hash ───────────────────────────────────────────────────
/**
 * Deterministic JSON with recursively SORTED object keys, so the hash is invariant to key order
 * and to pretty-printing of the on-disk file. Arrays keep their order (it is meaningful).
 */
export function canonicalize(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(',')}]`;
  if (value && typeof value === 'object') {
    const keys = Object.keys(value).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalize(value[k])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

/** sha256 hex of an already-canonical string. */
export function sha256Hex(str) {
  return crypto.createHash('sha256').update(str, 'utf8').digest('hex');
}

/** The content hash of a baseline payload (the artifact's NAME for load-by-hash). */
export function hashPayload(payload) {
  return sha256Hex(canonicalize(payload));
}

// ── Read the frozen fixture from disk (JSONL, one record per line) ────────────────────────────
function readJsonl(file) {
  return fs
    .readFileSync(file, 'utf8')
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0)
    .map((l) => JSON.parse(l));
}

/** Load the on-disk fixture. @returns {{ corpus: object[], defects: object[] }} */
export function loadFixture() {
  return { corpus: readJsonl(CORPUS_FILE), defects: readJsonl(DEFECTS_FILE) };
}

// ── Compute the single-pass baseline payload from a fixture (pure) ────────────────────────────
function emptyTally() {
  return { planted: 0, caught: 0, missed: 0 };
}
function finishTally(t) {
  return {
    planted: t.planted,
    caught: t.caught,
    missed: t.missed,
    recall: t.planted === 0 ? 0 : t.caught / t.planted,
  };
}

/**
 * Run the single-pass model over the manifest and compute the baseline recall payload.
 *
 * Recall is measured over the VERIFICATION-RECALL classes only (ordinary, correlated-blind-spot);
 * the probe classes (path-defect, declared-low-but-irreversible) are inventoried separately
 * because they are scored by crit-3 / I6, not by recall. Recall is broken out BY CLASS and BY
 * GATE (FIXTURE-SPEC; IMPLEMENTATION-PLAN Wave 6). I5 (G2 precision-only) is an attribution rule
 * the LOOP must honour later; the baseline simply records the per-gate single-pass numbers.
 *
 * @param {{ corpus: object[], defects: object[] }} fixture
 * @returns {object} the baseline payload (the thing that gets hashed)
 */
export function computeBaseline(fixture) {
  const defects = fixture.defects;
  const overall = emptyTally();
  const byClass = {};
  const byGate = {};
  const byClassCount = {}; // ALL classes, incl. probes (inventory)
  let singlePassMisses = 0;

  for (const d of defects) {
    byClassCount[d.class] = (byClassCount[d.class] || 0) + 1;
    if (!RECALL_CLASSES.includes(d.class)) continue; // probes: not in the recall denominator

    const caught = singlePassCatches(d);
    overall.planted += 1;
    overall[caught ? 'caught' : 'missed'] += 1;
    if (!caught) singlePassMisses += 1;

    byClass[d.class] ??= emptyTally();
    byClass[d.class].planted += 1;
    byClass[d.class][caught ? 'caught' : 'missed'] += 1;

    for (const gate of d.detectable_by ?? []) {
      byGate[gate] ??= emptyTally();
      byGate[gate].planted += 1;
      byGate[gate][caught ? 'caught' : 'missed'] += 1;
    }
  }

  const byClassOut = {};
  for (const c of Object.keys(byClass).sort()) byClassOut[c] = finishTally(byClass[c]);
  const byGateOut = {};
  for (const g of Object.keys(byGate).sort()) byGateOut[g] = finishTally(byGate[g]);

  return {
    artifact: ARTIFACT_NAME,
    schema_version: SCHEMA_VERSION,
    mode: 'single-pass',
    fixture: {
      total_defects: defects.length,
      by_class_count: byClassCount,
      corpus_size: fixture.corpus.length,
    },
    single_pass: {
      ...finishTally(overall),
      by_class: byClassOut,
      by_gate: byGateOut,
    },
    // The gap-closure DENOMINATOR: G is a fraction of THIS miss count (crit-1).
    gap_closure_denominator: { single_pass_misses: singlePassMisses },
  };
}

/**
 * Build the on-disk artifact object: the payload plus its content hash (the artifact's name).
 * @param {{ corpus: object[], defects: object[] }} fixture
 * @returns {{ payload: object, hash: string }}
 */
export function buildBaseline(fixture) {
  const payload = computeBaseline(fixture);
  return { payload, hash: hashPayload(payload) };
}

// ── Load the committed artifact + the load-by-hash API later waves use ─────────────────────────
/** Read & parse the committed baseline artifact. */
export function loadBaselineArtifact() {
  return JSON.parse(fs.readFileSync(BASELINE_FILE, 'utf8'));
}

/**
 * Load the baseline BY HASH (Wave 6+ entry point). Verifies the committed payload still hashes
 * to its self-declared `hash` AND to the `expectedHash` the caller pins. Any mismatch — a drifted
 * fixture regenerated into the artifact, a hand-edit, a truncation — throws, so a later wave can
 * never silently measure against a baseline that is not the one it pinned.
 * @param {string} expectedHash the sha256 content hash the caller expects
 * @returns {object} the verified payload
 */
export function loadBaselineByHash(expectedHash) {
  const artifact = loadBaselineArtifact();
  const actual = hashPayload(artifact.payload);
  if (actual !== artifact.hash) {
    throw new Error(
      `baseline artifact is corrupt: payload hashes to ${actual} but the file claims ${artifact.hash}`,
    );
  }
  if (actual !== expectedHash) {
    throw new Error(
      `baseline hash mismatch: expected ${expectedHash} but the committed baseline is ${actual} ` +
        `(the single-pass baseline was regenerated/changed — later waves load it by hash, so this is RED)`,
    );
  }
  return artifact.payload;
}

// ── Regeneration (CLI / human use): write the fixture + the named, hashed artifact ─────────────
function writeJsonl(file, records) {
  fs.writeFileSync(file, records.map((r) => JSON.stringify(r)).join('\n') + '\n');
}

/**
 * Regenerate everything deterministically: the fixture corpus + manifest (with `single_pass_caught`
 * filled by the model) and the named, hashed baseline artifact. Idempotent — same code ⇒ identical
 * bytes. Used by `node bin/baseline.mjs --write`.
 * @returns {{ hash: string }}
 */
export function regenerate() {
  fs.mkdirSync(fileURLToPath(FIXTURE_DIR), { recursive: true });
  fs.mkdirSync(path.dirname(fileURLToPath(BASELINE_FILE)), { recursive: true });

  const { corpus, defects } = generateFixture();
  // Fill the answer key field the spec reserves for the Wave-3 run.
  const stamped = defects.map((d) => ({ ...d, single_pass_caught: singlePassCatches(d) }));

  writeJsonl(CORPUS_FILE, corpus);
  writeJsonl(DEFECTS_FILE, stamped);

  const { payload, hash } = buildBaseline({ corpus, defects: stamped });
  const artifact = {
    artifact: ARTIFACT_NAME,
    schema_version: SCHEMA_VERSION,
    description:
      'Frozen single-pass ("current researchPrime Phase-3") recall baseline. Content-addressed by ' +
      '`hash` = sha256 of the canonical `payload`. Later waves load it by hash; regeneration ⇒ RED.',
    power_calc: powerCalc(),
    payload,
    hash,
  };
  fs.writeFileSync(BASELINE_FILE, JSON.stringify(artifact, null, 2) + '\n');
  return { hash };
}

// CLI: `node bin/baseline.mjs --write` regenerates; `node bin/baseline.mjs` prints the live hash.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes('--write')) {
    const { hash } = regenerate();
    console.log(`wrote fixture + baseline; hash=${hash}`);
  } else {
    console.log(JSON.stringify(buildBaseline(loadFixture()), null, 2));
  }
}
