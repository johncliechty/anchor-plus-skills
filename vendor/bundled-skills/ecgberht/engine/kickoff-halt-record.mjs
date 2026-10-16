/**
 * Gate 5 / Wave 9 - Phase 4.3: THE HALT RECORD - the wave's exit is a HALT for
 * John, and this module is that halt as data plus one deterministic renderer.
 *
 * WHAT A HALT RECORD IS HERE. All machine gates run green and then the wave
 * STOPS: no scope widens, nothing executes, and the two claims that remain are
 * VISUAL - only John's screen can prove them. The record therefore names, in
 * machine-readable form and in one rendered document: the five staged fixtures
 * (document, software, research, simple, ambiguous; research corrected once;
 * ambiguous left OPEN so the restart claim has an open state to paint), the two
 * visual claims, the three human steps (recorded in the completion journal,
 * never counted by a test), and the failure routing - a defect returns to its
 * owning phase; a non-North-Star discovery parks in the grasscatcher, never
 * built.
 *
 * Rendering is deterministic (no clock, no randomness, no host paths), so the
 * record re-derives byte-identically on every run - a repeated write is a
 * no-op that says `already`. Stdlib + the repo's atomic write primitive; no
 * child_process (the engine law). Source is ASCII on purpose (mojibake sweep).
 */

import fs from 'node:fs';
import path from 'node:path';

import { writeFileAtomicSync } from './durable-write.mjs';
import { KICKOFF_HUMAN_STEPS } from './kickoff-completion-journal.mjs';
import { KICKOFF_EFFORT_FIXTURES } from './kickoff-effort-fixtures.mjs';

/** Where the rendered HALT record lives, repo-relative (never a host path). */
export const KICKOFF_HALT_RECORD_REL =
  'planning/gate5-kickoff-synthesis-2026-08-31/HALT-WAVE9-JOHNS-LOOK.md';

/** The staging command the record quotes - one CLI, repo-relative. */
export const KICKOFF_LOOK_STAGING_COMMAND =
  'node scripts/kickoff-look-staging.mjs <target-dir>';

/**
 * The staging plan for John's look: the plan's five efforts in the plan's
 * order, ONE corrected once (research: a spoken component rename confirmed as
 * v2) and ONE left OPEN (ambiguous: the thin proposal, unconfirmed) so the
 * restart claim has both persisted states to paint. Effort directory names are
 * relative and carry a space on purpose (the suite's real-world path shape).
 */
export const KICKOFF_LOOK_EFFORT_PLAN = Object.freeze([
  Object.freeze({ key: 'document', dir: 'document effort', staged: 'confirmed', corrected: false }),
  Object.freeze({ key: 'software', dir: 'software effort', staged: 'confirmed', corrected: false }),
  Object.freeze({ key: 'research', dir: 'research effort', staged: 'confirmed', corrected: true }),
  Object.freeze({ key: 'simple', dir: 'simple effort', staged: 'confirmed', corrected: false }),
  Object.freeze({ key: 'ambiguous', dir: 'ambiguous effort', staged: 'open', corrected: false }),
]);

/** The TWO visual claims - everything the machine gates could not prove. */
export const KICKOFF_VISUAL_CLAIMS = Object.freeze([
  Object.freeze({
    id: 'thirty-second-test',
    claim:
      'Across the five staged efforts John identifies goal, finished state, parts, '
      + 'integration, and first move within 30 seconds each, and judges the opening '
      + 'no more burdensome than today\'s.',
  }),
  Object.freeze({
    id: 'restart-paints-open-and-confirmed',
    claim:
      'After one elevated restart, Anchor paints the open proposal (ambiguous effort, '
      + 'draft not applied) and the separately confirmed kickoffs from disk, with no '
      + 'session-memory dependency.',
  }),
]);

/**
 * Failure routing, as the plan writes it: a DEFECT returns to the phase that
 * owns the broken surface; a DISCOVERY that does not block a North-Star
 * criterion parks in the grasscatcher and is never built from this halt.
 */
export const KICKOFF_FAILURE_ROUTING = Object.freeze({
  defect: 'returns to the owning phase below',
  discovery: 'parks in the grasscatcher, never built',
  owning_phases: Object.freeze([
    Object.freeze({ phase: '1.1', owns: 'proposal record, canonical renderer, no-generation invariant' }),
    Object.freeze({ phase: '1.2', owns: 'append-only lifecycle, hash-bound receipt, execution-leak sentinel' }),
    Object.freeze({ phase: '1.3', owns: 'conversational synthesis, question cap, silent bootstrap' }),
    Object.freeze({ phase: '2.1', owns: 'confirmed-lineage projection writer, Face derivation' }),
    Object.freeze({ phase: '2.2', owns: 'display precedence, tag-map fallback, anatomy guard' }),
    Object.freeze({ phase: '3.1', owns: 'effort fixtures, live-seat tape, completion journal' }),
    Object.freeze({ phase: '4.1', owns: 'Anchor pass-through reader, cross-language golden contract' }),
    Object.freeze({ phase: '4.2', owns: 'cockpit GET exposure, routes-inventory truth, dist manifest' }),
    Object.freeze({ phase: '4.3', owns: 'integrated canary, look staging, open-state read model, this halt' }),
  ]),
});

export const KICKOFF_HALT_CODE = Object.freeze({
  DIR_MISSING: 'KICKOFF_HALT_DIR_MISSING',
  RECORD_UNREADABLE: 'KICKOFF_HALT_RECORD_UNREADABLE',
  WRITE_FAILED: 'KICKOFF_HALT_WRITE_FAILED',
});

export const KICKOFF_HALT_TEXT = Object.freeze({
  [KICKOFF_HALT_CODE.DIR_MISSING]:
    'The halt record folder does not exist (<error>) - nothing written; a halt record is never dropped somewhere else.',
  [KICKOFF_HALT_CODE.RECORD_UNREADABLE]:
    'An existing halt record is present but unreadable (<error>) - refused rather than overwritten blind.',
  [KICKOFF_HALT_CODE.WRITE_FAILED]:
    'The halt record write did not land (<error>) - nothing partial kept.',
});

function haltFailure(code, extra = {}) {
  const error = extra.error ?? String(code).toLowerCase();
  const text = KICKOFF_HALT_TEXT[code].replace(/<error>/g, String(error));
  return { ok: false, code, status_code: code, error, text, user_text: text, ...extra };
}

/**
 * Failure-state table for this small surface: `unknown` (an existing record
 * that cannot be read) and `empty-but-valid` (an existing record of zero bytes,
 * rewritten deterministically) are SEPARATE rows, never one guessed one.
 */
export function kickoffHaltRecordFailureTable() {
  const row = (state, code, text) => Object.freeze({
    state,
    surface: 'kickoff_halt_record',
    status_code: code,
    user_text: text ?? KICKOFF_HALT_TEXT[code],
  });
  return Object.freeze([
    row('written', 'KICKOFF_HALT_WRITTEN', 'The halt record is written - the wave ends in a HALT for John.'),
    row('already', 'KICKOFF_HALT_ALREADY', 'The halt record already carries these exact bytes - nothing rewritten.'),
    row('empty-but-valid', 'KICKOFF_HALT_EMPTY_REWRITTEN', 'An empty halt record was rewritten from the deterministic renderer.'),
    row('unknown', KICKOFF_HALT_CODE.RECORD_UNREADABLE),
    row('dependency-missing', KICKOFF_HALT_CODE.DIR_MISSING),
    row('write-failed', KICKOFF_HALT_CODE.WRITE_FAILED),
  ]);
}

/**
 * Deterministic render of the HALT record - same data, same bytes, always.
 * @returns {string}
 */
export function renderKickoffHaltRecord() {
  const fixtureLabel = (key) =>
    KICKOFF_EFFORT_FIXTURES.find((fixture) => fixture.key === key)?.label ?? key;
  const lines = [
    '# HALT - Gate 5 Wave 9 (Phase 4.3): the integrated canary exit and John\'s bounded screen look',
    '',
    'status: HALT. All machine gates are green (code, manifest, inventory, reader-golden,',
    'all under the one orchestrator gate `node scripts/run-all-tests.mjs`). Execution has',
    'NOT started: the leak sentinel\'s recorded word rides with the staged fixtures - zero',
    'execution calls, no file outside the staged paths. Kickoff ends at',
    'ready-for-first-slice and starts nothing. What remains is human, and it is John\'s.',
    '',
    '## The five staged fixtures',
    '',
    `Stage them with: \`${KICKOFF_LOOK_STAGING_COMMAND}\` (idempotent; the staged bytes reproduce).`,
    '',
    '| effort | fixture | staged dir | staged state | corrected |',
    '| --- | --- | --- | --- | --- |',
  ];
  for (const row of KICKOFF_LOOK_EFFORT_PLAN) {
    const state = row.staged === 'open' ? 'OPEN (draft, not applied)' : 'confirmed';
    const corrected = row.corrected ? 'corrected once (v2)' : '-';
    lines.push(`| ${row.key} | ${fixtureLabel(row.key)} | ${row.dir} | ${state} | ${corrected} |`);
  }
  lines.push(
    '',
    '## The two visual claims for John',
    '',
  );
  KICKOFF_VISUAL_CLAIMS.forEach((claim, index) => {
    lines.push(`${index + 1}. [${claim.id}] ${claim.claim}`);
  });
  lines.push(
    '',
    '## Human steps (recorded in the completion journal, never counted by a test)',
    '',
    '| step | what John does | proves |',
    '| --- | --- | --- |',
  );
  for (const step of KICKOFF_HUMAN_STEPS) {
    lines.push(`| ${step.id} | ${step.step} | ${step.proves} |`);
  }
  lines.push(
    '',
    '## Failure routing',
    '',
    `A defect John sees ${KICKOFF_FAILURE_ROUTING.defect}. A discovery that does not block`,
    `a North-Star criterion ${KICKOFF_FAILURE_ROUTING.discovery}.`,
    '',
    '| owning phase | owns |',
    '| --- | --- |',
  );
  for (const row of KICKOFF_FAILURE_ROUTING.owning_phases) {
    lines.push(`| ${row.phase} | ${row.owns} |`);
  }
  lines.push('');
  return lines.join('\n');
}

/**
 * Write (or re-derive) the HALT record under a repo root. Idempotent: identical
 * bytes answer `already` and move nothing; changed data rewrites in place
 * atomically; a missing planning folder refuses rather than inventing one.
 *
 * @param {string} repoRoot
 * @returns {{ok: true, halt_record_rel: string, halt_record_path: string,
 *   written: boolean, already: boolean} | object}
 */
export function writeKickoffHaltRecord(repoRoot) {
  const recordPath = path.join(path.resolve(repoRoot), ...KICKOFF_HALT_RECORD_REL.split('/'));
  const dir = path.dirname(recordPath);
  if (!fs.existsSync(dir)) {
    return haltFailure(KICKOFF_HALT_CODE.DIR_MISSING, { error: path.basename(dir) });
  }
  const content = renderKickoffHaltRecord();
  if (fs.existsSync(recordPath)) {
    let current;
    try {
      current = fs.readFileSync(recordPath, 'utf8');
    } catch (error) {
      return haltFailure(KICKOFF_HALT_CODE.RECORD_UNREADABLE, {
        error: error?.code ?? 'halt_record_unreadable',
      });
    }
    if (current === content) {
      return {
        ok: true,
        halt_record_rel: KICKOFF_HALT_RECORD_REL,
        halt_record_path: recordPath,
        written: false,
        already: true,
      };
    }
  }
  try {
    writeFileAtomicSync(recordPath, content);
  } catch (error) {
    return haltFailure(KICKOFF_HALT_CODE.WRITE_FAILED, {
      error: error?.code ?? 'halt_record_write_failed',
    });
  }
  return {
    ok: true,
    halt_record_rel: KICKOFF_HALT_RECORD_REL,
    halt_record_path: recordPath,
    written: true,
    already: false,
  };
}
