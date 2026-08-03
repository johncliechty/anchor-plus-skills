// Wave 26 — Journal integration (E2).
//
// The gradeable oracle (Waves 24/25) is only useful if its results FEED BACK: a real-use / canary
// RUN must leave a durable, append-only RECORD, and the inherited sleep loop must be able to read
// that record and LEARN from where the oracle FAILED (a missed catch or a false positive). This
// module is that seam. It is pure plumbing over INHERITED machinery — per NS8 it COMPOSES, never
// reimplements:
//
//   • the 7-field journal SCHEMA + validator come from the inherited `phase0-journal` seam
//     (JOURNAL_FIELDS / PROVENANCE_VALUES / validateEntry) resolved through inherits.manifest.json;
//   • the cross-context-corroborated DISTILL / no-drift / no-regression sleep loop comes from the
//     inherited `phase0-sleep` seam (clusterEntries / distill / runSleepCycle);
//   • durability is the SAME inherited Phase-0 substrate the adjudication store persists through
//     (atomic write-tmp+fsync+rename / validating read) — reused via adjudication.loadDurabilitySubstrate,
//     NO new persistence layer (P9 "reuse, no new store").
//
// THE INTEGRATION (the Wave-26 done-when): a completed oracle RUN is turned into one well-formed
// 7-field journal entry PER FIXTURE (the full append-only audit), each entry is durably appended,
// and the entries whose outcome is a FIXTURE-FAILURE (`canary-fail` — a missed defect catch or a
// false positive on a sound fixture) are the SLEEP-LOOP INPUT feeding the oracle's fixture-failure
// learning: they are fed to the inherited `distill`, which clusters them by defect class across
// DISTINCT fixture instances (cross-context corroboration, R5) into candidate lessons.
//
// A healthy battery-on run produces NO fixture-failure entries, so the sleep loop distills nothing
// (the oracle is sound); the ablation arm (battery off) misses every defect, so its failures cluster
// per class into lessons — proving the learning seam is load-bearing, not decorative.
//
// Pure node built-ins + the project's own modules + the inherited seams. Runs under `node --test test/`.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { loadManifest, resolveEntryPath, DEFAULT_MANIFEST_PATH } from './inherits-gate.mjs';
import { loadDurabilitySubstrate } from './adjudication.mjs';
import { SCORER, realBatteryFlags, scoredSubset, soundSubset } from './oracle-scorer.mjs';
import { loadCorpus, SUBSET } from './oracle-corpus.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** The skill@version stamp written into every journal entry (field 2). Read once from package.json. */
export const RAMANUJAN_SKILL = (() => {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
    return `${pkg.name}@${pkg.version}`;
  } catch {
    return 'ramanujan@unknown';
  }
})();

/** Genuine-execution provenance — the ONLY provenance the sleep loop lets corroborate a lesson (R5). */
export const GENUINE = 'genuine-execution';

/** The two run outcomes a journalled fixture can carry (field 6). */
export const OUTCOME = Object.freeze({ PASS: 'canary-pass', FAIL: 'canary-fail' });

/** The situation (cluster key) prefix: the sleep loop clusters fixture-failures by defect class. */
export const SITUATION_PREFIX = 'oracle-fixture';

// ---------------------------------------------------------------------------
// Inherited-seam resolution (compose, never reimplement — NS8).
// ---------------------------------------------------------------------------

/** Resolve an inherited MODULE seam to its live namespace, by logical_name, through the manifest. */
export async function resolveModuleSeam(logical_name, manifestPath = DEFAULT_MANIFEST_PATH) {
  const manifest = loadManifest(manifestPath);
  const entry = manifest.entries.find((e) => e.logical_name === logical_name);
  if (!entry) throw new Error(`inherits manifest has no entry logical_name="${logical_name}"`);
  if (entry.kind !== 'module') throw new Error(`inherited seam "${logical_name}" is not a module (kind=${entry.kind})`);
  const resolved = resolveEntryPath(manifestPath, entry);
  if (!fs.existsSync(resolved)) throw new Error(`inherited seam "${logical_name}" path does not exist: ${resolved}`);
  return import(pathToFileURL(resolved).href);
}

/** The inherited journal seam (JOURNAL_FIELDS / PROVENANCE_VALUES / validateEntry / journalValidator). */
export const resolveJournalSeam = (manifestPath) => resolveModuleSeam('phase0-journal', manifestPath);

/** The inherited sleep seam (clusterEntries / distill / runSleepCycle / northStarGate / evalGate). */
export const resolveSleepSeam = (manifestPath) => resolveModuleSeam('phase0-sleep', manifestPath);

// ---------------------------------------------------------------------------
// Run → 7-field journal entries.
// ---------------------------------------------------------------------------

/** name → the `flagged(fixture)` battery predicate (the ONE knob the oracle scorer varies). */
const BATTERY_PREDICATE = Object.freeze({
  [SCORER.BATTERY_ON]: realBatteryFlags, // the REAL spine (Wave-24 in-process probes)
  [SCORER.ABLATION]: () => false, // battery OFF — nothing withheld (the load-bearing ablation arm)
  [SCORER.STUB_ALWAYS_ABSTAIN]: () => true, // canned baseline: withhold everything
  [SCORER.STUB_ALWAYS_FLAG]: () => true, // canned baseline: flag everything
});

/**
 * Is a fixture's run CORRECT? A SCORED-subset DEFECT fixture is correct iff the battery FLAGS it
 * (the oracle withholds the defect — a catch); a SOUND-subset fixture is correct iff the battery
 * does NOT flag it (it settles — flagging a sound fixture is a false positive). Mirrors the exact
 * grading the Wave-25 scorer uses, so a journalled outcome can never disagree with Metric G.
 */
export function fixtureRunIsCorrect(fixture, flagged) {
  const isSound = fixture.subset === SUBSET.SOUND;
  return isSound ? !flagged : flagged;
}

/**
 * Turn ONE completed oracle run (a named scorer over the corpus) into 7-field journal entries —
 * one per SCORED-defect and SOUND fixture, in the scorer's stable order. Each entry is validated
 * with the INHERITED validateEntry; an entry that does not conform is a hard error (we never append
 * a malformed record). `runId` makes the entry ids deterministic + unique (no clock / no RNG).
 *
 * @param {{ scorerName?: string, corpus?: object, runId: string, journalSeam: object }} cfg
 * @returns {Array<object>} validated 7-field entries (full append-only audit of the run)
 */
export function runToJournalEntries({ scorerName = SCORER.BATTERY_ON, corpus = loadCorpus(), runId, journalSeam } = {}) {
  if (typeof runId !== 'string' || runId.length === 0) throw new Error('runToJournalEntries requires a non-empty runId');
  if (!journalSeam || typeof journalSeam.validateEntry !== 'function') {
    throw new Error('runToJournalEntries requires the inherited journal seam (validateEntry)');
  }
  const flagged = BATTERY_PREDICATE[scorerName];
  if (typeof flagged !== 'function') {
    throw new Error(`runToJournalEntries: unknown scorer ${JSON.stringify(scorerName)}`);
  }

  // SCORED defects first, then the FIXED SOUND subset — the same fixtures Metric G grades.
  const fixtures = [...scoredSubset(corpus), ...soundSubset(corpus)];
  const entries = fixtures.map((fixture) => {
    const isFlagged = Boolean(flagged(fixture));
    const correct = fixtureRunIsCorrect(fixture, isFlagged);
    const isSound = fixture.subset === SUBSET.SOUND;
    const outcome = correct ? OUTCOME.PASS : OUTCOME.FAIL;
    const detail = isSound
      ? correct ? 'sound fixture settled (no false positive)' : 'FALSE POSITIVE: sound fixture wrongly withheld'
      : correct ? 'defect caught (withheld)' : 'MISSED: defect was greened, not caught';
    const entry = {
      id: `${runId}::${fixture.id}`, // 1. unique, deterministic, append-only
      skill: RAMANUJAN_SKILL, // 2. the skill@version that produced the entry
      situation: `${SITUATION_PREFIX}:${fixture.class}`, // 3. CLUSTER key — the defect class
      context: fixture.id, // 4. cross-context corroboration key — the distinct fixture instance
      observation: `${scorerName} → ${detail}`, // 5. the candidate-lesson signal
      outcome, // 6. canary-pass | canary-fail
      provenance: GENUINE, // 7. a genuine execution (the sleep loop trusts it for corroboration)
    };
    const v = journalSeam.validateEntry(entry);
    if (!v.ok) throw new Error(`runToJournalEntries built a malformed entry ${entry.id}: ${v.detail}`);
    return entry;
  });
  return entries;
}

/**
 * The SLEEP-LOOP INPUT feeding the oracle's fixture-FAILURE learning: the subset of run entries whose
 * outcome is a failure (a missed catch or a false positive). These are what the inherited distill
 * clusters into lessons — a healthy run yields an empty input (nothing to learn).
 */
export function fixtureFailureInput(entries = []) {
  return entries.filter((e) => e && e.outcome === OUTCOME.FAIL);
}

// ---------------------------------------------------------------------------
// The durable, append-only journal store (on the inherited Phase-0 substrate — reuse, no new store).
// ---------------------------------------------------------------------------

export class JournalStore {
  #substrate;
  #file;
  #entries;
  #validate;

  /**
   * @param {object} substrate     inherited durability module ({ newCheckpoint, writeCheckpointAtomic, readCheckpoint }).
   * @param {string} file          the checkpoint file the journal array is parked on.
   * @param {{ entries?: Array<object>, validateEntry: Function }} cfg
   *        validateEntry is the INHERITED journal validator (never a local reimplementation).
   */
  constructor(substrate, file, { entries = [], validateEntry } = {}) {
    for (const fn of ['newCheckpoint', 'writeCheckpointAtomic', 'readCheckpoint']) {
      if (!substrate || typeof substrate[fn] !== 'function') {
        throw new Error(`JournalStore requires a durability substrate with ${fn}()`);
      }
    }
    if (typeof file !== 'string' || file.length === 0) throw new Error('JournalStore requires a file path');
    if (typeof validateEntry !== 'function') throw new Error('JournalStore requires the inherited validateEntry');
    this.#substrate = substrate;
    this.#file = file;
    this.#validate = validateEntry;
    this.#entries = Array.isArray(entries) ? entries.slice() : [];
  }

  /**
   * Open the store for `file`, RELOADING any persisted journal from disk (an across-restart load
   * reads ONLY from disk — it holds no in-memory state from a prior process). Absent file ⇒ empty.
   */
  static load(substrate, file, { validateEntry } = {}) {
    let entries = [];
    if (fs.existsSync(file)) {
      const cp = substrate.readCheckpoint(file); // validating read — HALTs on a torn file
      if (cp && Array.isArray(cp.journal)) entries = cp.journal;
    }
    return new JournalStore(substrate, file, { entries, validateEntry });
  }

  /** The journal entries, in append order (a copy — the store is append-only, never mutated in place). */
  get entries() {
    return this.#entries.slice();
  }

  /** Persist a candidate journal array DURABLY via the inherited atomic writer (the flush boundary). */
  #flush(candidate) {
    const cp = this.#substrate.newCheckpoint({ plan_path: this.#file, total_waves: 1 });
    cp.journal = candidate;
    this.#substrate.writeCheckpointAtomic(this.#file, cp); // write-tmp + fsync + atomic rename
  }

  /**
   * APPEND one entry (append-only — corrections are new entries, never edits). The entry is validated
   * with the inherited validator FIRST (a malformed record is refused), then the new journal is
   * FLUSHED to disk BEFORE it is published in memory — so a crash mid-append never leaves an entry
   * visible-but-unpersisted.
   */
  append(entry) {
    const v = this.#validate(entry);
    if (!v.ok) throw new Error(`JournalStore.append refused entry ${entry && entry.id}: ${v.detail}`);
    const next = [...this.#entries, entry];
    this.#flush(next); // durable BEFORE in-memory publish
    this.#entries = next;
    return entry;
  }

  /** Append many entries, in order. Returns the full entry list after the appends. */
  appendAll(entries = []) {
    for (const e of entries) this.append(e);
    return this.entries;
  }
}

// ---------------------------------------------------------------------------
// The end-to-end integration: run → durable append → sleep-loop consumption.
// ---------------------------------------------------------------------------

/**
 * Open a durable journal wired to the inherited substrate + inherited validator. Returns
 * { store, journalSeam, sleepSeam, substrate } so callers reuse the resolved seams.
 */
export async function openJournal({ manifestPath = DEFAULT_MANIFEST_PATH, file } = {}) {
  if (typeof file !== 'string' || file.length === 0) throw new Error('openJournal requires a file path');
  const [journalSeam, sleepSeam, substrate] = await Promise.all([
    resolveJournalSeam(manifestPath),
    resolveSleepSeam(manifestPath),
    loadDurabilitySubstrate(manifestPath),
  ]);
  const store = JournalStore.load(substrate, file, { validateEntry: journalSeam.validateEntry });
  return { store, journalSeam, sleepSeam, substrate };
}

/**
 * THE WAVE-26 done-when, executed end-to-end. Take a completed oracle RUN (a named scorer over the
 * corpus), append a well-formed 7-field journal entry per fixture to the DURABLE append-only store,
 * RELOAD the journal from disk (proving it persisted), then feed the fixture-FAILURE entries to the
 * inherited sleep-loop `distill` (the sleep loop CONSUMING the journal) to learn per-class lessons.
 *
 * @param {{
 *   scorerName?: string,
 *   corpus?: object,
 *   runId: string,
 *   file: string,
 *   manifestPath?: string,
 * }} cfg
 * @returns {Promise<{
 *   appended: number,
 *   entries: Array<object>,        // the entries appended this run
 *   journal: Array<object>,        // the FULL journal reloaded from disk (the durable audit)
 *   failureInput: Array<object>,   // the sleep-loop input (the fixture-failures)
 *   distill: { candidates: Array<object>, rejected: Array<object> }, // the sleep loop's consumption
 * }>}
 */
export async function integrateRun({
  scorerName = SCORER.BATTERY_ON,
  corpus = loadCorpus(),
  runId,
  file,
  manifestPath = DEFAULT_MANIFEST_PATH,
} = {}) {
  const { store, journalSeam, sleepSeam, substrate } = await openJournal({ manifestPath, file });

  // 1. A completed run → 7-field entries; 2. durably APPEND each (append-only).
  const entries = runToJournalEntries({ scorerName, corpus, runId, journalSeam });
  store.appendAll(entries);

  // 3. RELOAD the journal from disk via a FRESH store — the durable audit (proves the append
  //    persisted, not merely that it is sitting in this process's memory).
  const reloaded = JournalStore.load(substrate, file, { validateEntry: journalSeam.validateEntry });
  const journal = reloaded.entries;

  // 4. The sleep loop CONSUMES the journal: feed the fixture-FAILURE entries to the inherited distill,
  //    which clusters them per defect class across DISTINCT fixture instances (R5 cross-context).
  const failureInput = fixtureFailureInput(journal);
  const distill = sleepSeam.distill(failureInput);

  return { appended: entries.length, entries, journal, failureInput, distill };
}
