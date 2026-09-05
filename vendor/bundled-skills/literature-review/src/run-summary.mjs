// src/run-summary.mjs — Wave 4 (2026-09-04, journal 0010): corpus-relevance stamp + honesty gate.
//
// The 0010 run counted papers on every surface but never said whether the corpus was
// about the question — it reported "18 grounded claims" over Fiji, PointNet++ and a
// shape GAN and called that a synthesis. This module derives ONE authoritative
// run-summary object from the EXTRACTED corpus only, and every output surface —
// console summary, ledger header, machine-readable run record — consumes that same
// object; none re-derives its own numbers:
//
//   - `corpus_relevance` = the fraction of EXTRACTED papers at or above the Wave-3
//     relevance floor (seeds are at/above by construction: they DEFINE the topic and
//     their score is similarity to the OTHER seeds, never to themselves);
//   - deterministic edges: zero extracted papers → corpus_relevance null (an empty
//     corpus has no measurable relevance; the run already reports its emptiness
//     honestly), and a no-seed run (floor inactive — no relevance signal exists)
//     → corpus_relevance null with governed verdict behavior fully preserved;
//   - verdict derivation is CENTRALIZED here: corpus_relevance below the configurable
//     `corpus_relevance_min` yields verdict `corpus:off-topic` and ledger status
//     `partial` — the governed adversarial verdict never overrides it; at/above the
//     minimum (or when relevance is not measurable) the governed verdict passes
//     through UNCHANGED;
//   - the ledger for a corpus:off-topic run is STILL WRITTEN, stamped partial, and
//     success phrasing derived from extracted/grounded/synthesized counts alone is
//     suppressed (formatRunResult): counts do not make a success.
//
// An invalid floor or minimum is refused outright: an unnamed bound cannot be tested.

import { validateSchema } from './validateSchema.mjs';

export const RUN_SUMMARY_VERSION = 'litreview-run-summary/1';

/** The configurable honesty minimum: below this fraction the run verdict is corpus:off-topic. */
export const DEFAULT_CORPUS_RELEVANCE_MIN = 0.5;

/** The centralized below-minimum verdict — never phrased as a synthesis success. */
export const VERDICT_CORPUS_OFF_TOPIC = 'corpus:off-topic';

/** Ledger statuses the summary can carry (none = no ledger is written at all). */
export const LEDGER_STATUS = Object.freeze({ PARTIAL: 'partial', COMPLETE: 'complete', NONE: 'none' });

/** Round to 6 decimals at the stamping boundary — what is recorded is what is compared. */
const round6 = (x) => Math.round(x * 1e6) / 1e6;

function assertUnitInterval(name, value) {
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new TypeError(`${name} must be a number in [0,1], got ${JSON.stringify(value)}`);
  }
}

/**
 * Build THE run-summary object — the one authority every output surface consumes.
 *
 * `extractedCandidates` are the papers that actually made it through extraction
 * (text sourced AND grounded claims produced), each carrying the Wave-3 relevance
 * stamps (`relevance_score`, `relevance_exempt`/`is_seed`). Papers skipped for
 * missing text or at the per-paper grounded-claims floor are NOT extracted and
 * never enter the fraction.
 *
 * @param {object} input
 * @param {object[]} input.extractedCandidates Wave-3-stamped records of extracted papers only.
 * @param {number} input.relevanceFloor The Wave-3 relevance floor in [0,1].
 * @param {boolean} input.floorActive Whether scoreable seeds existed (Wave-3 floor_active).
 * @param {number} [input.corpusRelevanceMin] Configurable honesty minimum in [0,1].
 * @param {string|null} [input.governedVerdict] The governed verdict, when already known.
 * @returns {object} A frozen, schema-valid RunSummary.
 */
export function buildRunSummary({
  extractedCandidates,
  relevanceFloor,
  floorActive,
  corpusRelevanceMin = DEFAULT_CORPUS_RELEVANCE_MIN,
  governedVerdict = null,
} = {}) {
  if (!Array.isArray(extractedCandidates)) {
    throw new TypeError('buildRunSummary: extractedCandidates must be an array');
  }
  assertUnitInterval('buildRunSummary: relevanceFloor', relevanceFloor);
  assertUnitInterval('buildRunSummary: corpusRelevanceMin', corpusRelevanceMin);
  if (governedVerdict !== null && typeof governedVerdict !== 'string') {
    throw new TypeError('buildRunSummary: governedVerdict must be a string or null');
  }

  const extracted = extractedCandidates.length;
  let atOrAbove = 0;
  for (const c of extractedCandidates) {
    if (c === null || typeof c !== 'object') {
      throw new TypeError('buildRunSummary: every extracted candidate must be an object');
    }
    const exempt = c.relevance_exempt === true || c.is_seed === true;
    const score = typeof c.relevance_score === 'number' ? c.relevance_score : null;
    if (exempt || (score !== null && score >= relevanceFloor)) atOrAbove += 1;
  }

  // Deterministic edges: an empty extracted corpus has no measurable relevance, and a
  // run without scoreable seeds carries no relevance signal at all (no-seed
  // compatibility — the pre-Wave-4 governed behavior is preserved bit-for-bit).
  const measurable = floorActive === true && extracted > 0;
  const corpusRelevance = measurable ? round6(atOrAbove / extracted) : null;
  const offTopic = corpusRelevance !== null && corpusRelevance < corpusRelevanceMin;

  const summary = Object.freeze({
    version: RUN_SUMMARY_VERSION,
    relevance_floor: relevanceFloor,
    corpus_relevance_min: corpusRelevanceMin,
    extracted,
    extracted_at_or_above_floor: atOrAbove,
    corpus_relevance: corpusRelevance,
    floor_active: floorActive === true,
    verdict: offTopic ? VERDICT_CORPUS_OFF_TOPIC : governedVerdict,
    // extracted > 0 implies at least one grounded claim, so a ledger IS written:
    // partial under corpus:off-topic, complete otherwise. Zero extracted → none.
    ledger_status: offTopic ? LEDGER_STATUS.PARTIAL : (extracted > 0 ? LEDGER_STATUS.COMPLETE : LEDGER_STATUS.NONE),
  });
  validateSchema(summary, 'RunSummary');
  return summary;
}

/**
 * Fill in the governed verdict once the adversarial stage has spoken. The corpus
 * verdict is authoritative: a corpus:off-topic summary is returned UNCHANGED — no
 * governed outcome can promote an off-topic corpus back to success. Everything
 * else (fraction, floor, minimum, counts, ledger status) is already final.
 *
 * @param {object} summary A RunSummary from buildRunSummary.
 * @param {object} [options]
 * @param {string|null} [options.governedVerdict]
 * @returns {object} The same summary, or a new frozen one with the verdict filled.
 */
export function finalizeRunSummary(summary, { governedVerdict = null } = {}) {
  validateSchema(summary, 'RunSummary');
  if (summary.verdict === VERDICT_CORPUS_OFF_TOPIC) return summary;
  if (governedVerdict !== null && typeof governedVerdict !== 'string') {
    throw new TypeError('finalizeRunSummary: governedVerdict must be a string or null');
  }
  if (governedVerdict === null || governedVerdict === summary.verdict) return summary;
  const next = Object.freeze({ ...summary, verdict: governedVerdict });
  validateSchema(next, 'RunSummary');
  return next;
}

/**
 * The ONE shared stamp line: every surface prints this exact string, so the console,
 * the ledger header and the run record can never disagree on the fraction, the floor,
 * the minimum, the counts or the ledger status. The verdict is rendered per-surface
 * (the governed verdict may not exist yet when the ledger is written); the ledger
 * status and the off-topic verdict, which are final at build time, never differ.
 *
 * @param {object} summary A RunSummary.
 * @returns {string}
 */
export function summaryStampLine(summary) {
  validateSchema(summary, 'RunSummary');
  const rel = summary.corpus_relevance === null ? 'n/a' : String(summary.corpus_relevance);
  return `corpus_relevance=${rel} (${summary.extracted_at_or_above_floor}/${summary.extracted} extracted at/above relevance_floor=${summary.relevance_floor}; corpus_relevance_min=${summary.corpus_relevance_min}; ledger=${summary.ledger_status})`;
}

/**
 * Console rendering of the summary object — the honest closing lines of a run.
 *
 * @param {object} summary A RunSummary.
 * @returns {string[]}
 */
export function formatConsoleSummary(summary) {
  const lines = [`Corpus relevance: ${summaryStampLine(summary)}`];
  if (summary.verdict === VERDICT_CORPUS_OFF_TOPIC) {
    lines.push(
      `VERDICT ${VERDICT_CORPUS_OFF_TOPIC} — the extracted corpus is below corpus_relevance_min; the ledger is written as PARTIAL. Not a synthesis success.`,
    );
  } else if (typeof summary.verdict === 'string') {
    lines.push(`Verdict: ${summary.verdict} (governed — corpus relevance at/above minimum or not measurable; verdict logic unchanged)`);
  } else {
    lines.push('Verdict: none recorded (no governed verdict reached this run; nothing is claimed).');
  }
  return lines;
}

/**
 * Ledger-header rendering of the SAME summary object, emitted at the top of the
 * synthesized assumptions ledger (markdown). For a corpus:off-topic run the header
 * carries the verdict and the partial stamp; for an on-topic run written before the
 * governed stage concludes, the header defers the verdict to the run record.
 *
 * @param {object} summary A RunSummary.
 * @returns {string} A markdown block ending in a blank line.
 */
export function formatLedgerHeader(summary) {
  const lines = [
    '## Corpus relevance (run honesty stamp)',
    '',
    `- ${summaryStampLine(summary)}`,
  ];
  if (summary.verdict === VERDICT_CORPUS_OFF_TOPIC) {
    lines.push(`- **Verdict:** ${VERDICT_CORPUS_OFF_TOPIC} — below corpus_relevance_min; this ledger is PARTIAL, not a synthesis success.`);
  } else if (typeof summary.verdict === 'string') {
    lines.push(`- **Verdict:** ${summary.verdict} (governed; corpus relevance at/above minimum or not measurable)`);
  } else {
    lines.push('- **Verdict:** governed verdict pending at ledger write — see the run record.');
  }
  lines.push(`- **Ledger status:** ${summary.ledger_status}`);
  return lines.join('\n') + '\n\n';
}

/**
 * The run record's `result` line, derived from the summary: below the minimum the
 * result IS the corpus verdict — the count-based success phrasing the caller would
 * otherwise have written is suppressed. At/above the minimum (or not measurable)
 * the caller's governed result passes through unchanged.
 *
 * @param {object} summary A RunSummary.
 * @param {string} governedResult The result line the run would otherwise record.
 * @returns {string}
 */
export function formatRunResult(summary, governedResult) {
  validateSchema(summary, 'RunSummary');
  if (summary.verdict === VERDICT_CORPUS_OFF_TOPIC) {
    return `${VERDICT_CORPUS_OFF_TOPIC} — ${summaryStampLine(summary)}; partial ledger written; success phrasing suppressed`;
  }
  return governedResult;
}
