/**
 * Gate 5 / Wave 6 - ONE completion journal, its id resolved at write time.
 *
 * WHY THE ID IS RESOLVED AND NEVER HARDCODED. The journal folder is append-only and
 * shared by every effort in this campaign; a planned-ahead number collides the day any
 * other run journals first. So the writer scans the folder AT WRITE TIME, takes the
 * next free id, and keeps that id forever after: a re-run finds the existing completion
 * journal by its slug and either leaves it byte-identical (the repeat-invocation law)
 * or rewrites it in place under the SAME id - one completion journal, never two.
 *
 * WHAT THE JOURNAL SAYS. The plan's A4 acceptance: every North-Star criterion carries
 * exactly one evidence tag - hermetic (a deterministic gate proves it), live-seat (the
 * ONE authorized production recording proves it), or John's screen (only a human look
 * can prove it - TAGGED so, never claimed). The tag table is data here, not prose in a
 * document, so a test can assert coverage and honesty rather than trust the wording.
 *
 * Rendering is deterministic: same inputs, same bytes. Nothing volatile (no wall clock,
 * no durations, no absolute paths) enters the render, so the journal re-derives
 * byte-identically from the committed tape on every later run.
 *
 * Stdlib + the repo's atomic write primitive. ASCII on purpose (the mojibake sweep).
 */

import fs from 'node:fs';
import path from 'node:path';

import { writeFileAtomicSync } from './durable-write.mjs';

/** The one slug this effort's completion journal lives under. */
export const KICKOFF_COMPLETION_SLUG = 'gate5-kickoff-synthesis-completion';

/** The three evidence classes. "John's screen" is a tag, never a claim. */
export const KICKOFF_EVIDENCE_TAG = Object.freeze({
  HERMETIC: 'hermetic',
  LIVE_SEAT: 'live-seat',
  JOHNS_SCREEN: "John's screen",
});

/**
 * Every North-Star criterion (locked 2026-08-31), each with exactly ONE tag and the
 * named gates behind it. Criteria only John's screen can prove say so out loud.
 */
export const KICKOFF_NORTH_STAR_EVIDENCE = Object.freeze([
  Object.freeze({
    criterion: 1,
    claim: 'Rich brainstorming yields a compact proposal with ZERO added questions; sparse input asks at most ONE natural question per turn.',
    tag: KICKOFF_EVIDENCE_TAG.LIVE_SEAT,
    proof: 'W6-T08 question-count row on the recorded production interaction; hermetic W3-T01/W3-T02 and W6-T01..W6-T05 cover the rich and sparse shapes.',
  }),
  Object.freeze({
    criterion: 2,
    claim: 'John reviews and confirms ONE compact bundle - never separate goal/map/plan approvals.',
    tag: KICKOFF_EVIDENCE_TAG.HERMETIC,
    proof: 'W2-T01 hash-bound receipt; W3-T08 spoken confirmation; each W6 fixture presents one bundle.',
  }),
  Object.freeze({
    criterion: 3,
    claim: 'A one-sitting effort stays one compact unit: zero fabricated stages, tautological done-conditions, or annotation boilerplate.',
    tag: KICKOFF_EVIDENCE_TAG.HERMETIC,
    proof: 'W3-T04 and W6-T04 honest collapse; the no-padding row of W6-T08 corroborates on the live tape.',
  }),
  Object.freeze({
    criterion: 4,
    claim: 'A human can tell outcome, components, coarse plan, end-to-end slice, and meaningful integration apart without schema vocabulary.',
    tag: KICKOFF_EVIDENCE_TAG.HERMETIC,
    proof: 'W6-T06 readable-distinction law over the rendered prose of all five efforts.',
  }),
  Object.freeze({
    criterion: 5,
    claim: 'Spoken corrections produce a complete new proposal version and hash - no field editing.',
    tag: KICKOFF_EVIDENCE_TAG.HERMETIC,
    proof: 'W2-T09 and W3-T05 whole-bundle v(n+1) re-proposal.',
  }),
  Object.freeze({
    criterion: 6,
    claim: 'Nothing authoritative changes before confirmation; the committed result equals the reviewed proposal byte-for-hash; double-confirm is harmless; stale confirm refuses safely.',
    tag: KICKOFF_EVIDENCE_TAG.HERMETIC,
    proof: 'W2-T02, W2-T03, W2-T04; W3-T08.',
  }),
  Object.freeze({
    criterion: 7,
    claim: 'Both projections derive from the confirmed lineage; a new kickoff writes no anatomy.json; deleting display data cannot change the projections; confirmed intent has display precedence.',
    tag: KICKOFF_EVIDENCE_TAG.HERMETIC,
    proof: 'W4-T01, W4-T05; W5-T01, W5-T03, W5-T04.',
  }),
  Object.freeze({
    criterion: 8,
    claim: 'Restart with an open proposal paints it; restart after confirmation paints the same confirmed kickoff; the Anchor cockpit canary READS both.',
    tag: KICKOFF_EVIDENCE_TAG.JOHNS_SCREEN,
    proof: 'Store-side restart is hermetic (W2-T07, W4-T02); the cockpit canary and the elevated restart are the final wave\'s human step - tagged, not claimed.',
  }),
  Object.freeze({
    criterion: 9,
    claim: 'A new effort with no Face or envelope reaches its first proposal with no budget/Face/precondition prompt; the Face is created ON confirmation.',
    tag: KICKOFF_EVIDENCE_TAG.HERMETIC,
    proof: 'W3-T02 silent bootstrap; W4-T03 Face-on-confirm.',
  }),
  Object.freeze({
    criterion: 10,
    claim: 'A post-confirmation component change produces v(n+1) conversationally with one confirmation and an updated intent projection.',
    tag: KICKOFF_EVIDENCE_TAG.HERMETIC,
    proof: 'W3-T05; W4-T04 byte-identical re-derivation on the new receipt.',
  }),
  Object.freeze({
    criterion: 11,
    claim: 'Kickoff causes no execution leakage (no draft, model run, specialist, commission, build, or external action).',
    tag: KICKOFF_EVIDENCE_TAG.HERMETIC,
    proof: 'W2-T06 the ONE sentinel; W3-T11; W6-T01 armed across the fixture flow.',
  }),
  Object.freeze({
    criterion: 12,
    claim: 'THE 30-SECOND TEST on John\'s screen across the five synthetic efforts, judged no more burdensome than today\'s opening.',
    tag: KICKOFF_EVIDENCE_TAG.JOHNS_SCREEN,
    proof: 'Only John\'s screen can prove it - the five W6 fixtures stage it for the final wave; tagged, not claimed.',
  }),
]);

/**
 * Gate 5 / Wave 9 - the three HUMAN steps the final wave HALTs for, recorded in
 * THIS journal and never counted by a test. A machine gate that scored a human
 * look would be the confident wrong answer this effort exists to refuse, so the
 * steps are data here: the journal RECORDS them, John performs them, and no
 * assertion anywhere claims their outcome.
 */
export const KICKOFF_HUMAN_STEPS = Object.freeze([
  Object.freeze({
    id: 'single-elevated-restart',
    step: 'John restarts Anchor once, elevated, and looks at what it paints: the open proposal and the separately confirmed kickoff, each read from disk.',
    proves: 'criterion 8 - restart paints open and confirmed with no session-memory dependency',
  }),
  Object.freeze({
    id: 'thirty-second-test',
    step: 'John takes the 30-second test across the five staged efforts (document, software, research, simple, ambiguous; research corrected once): goal, finished state, parts, integration, and first move, each identified within 30 seconds.',
    proves: 'criterion 12 - the 30-second test on John\'s screen',
  }),
  Object.freeze({
    id: 'burden-word',
    step: 'John says in his own words whether this opening is no more burdensome than today\'s - his word is recorded, never scored.',
    proves: 'criterion 12 - the no-more-burdensome-than-today judgement',
  }),
]);

export const KICKOFF_JOURNAL_CODE = Object.freeze({
  DIR_MISSING: 'KICKOFF_JOURNAL_DIR_MISSING',
  TAPE_FACTS_REQUIRED: 'KICKOFF_JOURNAL_TAPE_FACTS_REQUIRED',
});

export const KICKOFF_JOURNAL_TEXT = Object.freeze({
  [KICKOFF_JOURNAL_CODE.DIR_MISSING]:
    'The journal folder does not exist (<error>) - nothing written; a completion journal is never dropped somewhere else.',
  [KICKOFF_JOURNAL_CODE.TAPE_FACTS_REQUIRED]:
    'The completion journal cites the live-seat tape by its verified facts, and none were supplied (<error>) - refused rather than claimed.',
});

function journalFailure(code, extra = {}) {
  let text = KICKOFF_JOURNAL_TEXT[code];
  const error = extra.error ?? String(code).toLowerCase();
  if (text.includes('<error>')) text = text.replace(/<error>/g, String(error));
  return { ok: false, code, status_code: code, error, text, user_text: text, ...extra };
}

const ID_FILE = /^(\d{4})-.+\.md$/;

/**
 * The next free NNNN id in a journal folder, AT THIS MOMENT. Scans one directory level
 * (journal entries are flat; runs/ and README.md are ignored by the pattern).
 *
 * @param {string} journalDir
 * @returns {{ok: true, id: string, max_seen: number} | object}
 */
export function resolveNextJournalId(journalDir) {
  let names;
  try {
    names = fs.readdirSync(journalDir);
  } catch (e) {
    return journalFailure(KICKOFF_JOURNAL_CODE.DIR_MISSING, { error: String(e?.message ?? e) });
  }
  let max = 0;
  for (const name of names) {
    const m = ID_FILE.exec(name);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return { ok: true, id: String(max + 1).padStart(4, '0'), max_seen: max };
}

/**
 * The existing completion journal for this effort, if any - found by SLUG, so the id
 * it was born under is kept forever.
 *
 * @param {string} journalDir
 * @returns {{ok: true, file: string|null, id: string|null} | object}
 */
export function findKickoffCompletionJournal(journalDir) {
  let names;
  try {
    names = fs.readdirSync(journalDir);
  } catch (e) {
    return journalFailure(KICKOFF_JOURNAL_CODE.DIR_MISSING, { error: String(e?.message ?? e) });
  }
  const hit = names.find((name) => ID_FILE.test(name) && name.endsWith(`-${KICKOFF_COMPLETION_SLUG}.md`));
  if (!hit) return { ok: true, file: null, id: null };
  return { ok: true, file: hit, id: hit.slice(0, 4) };
}

/**
 * Deterministic render: same id + same tape facts -> same bytes, always.
 *
 * @param {{id: string, tape: {rel: string, sha256: string, entry_count: number, families: string[]}}} input
 * @returns {string}
 */
export function renderKickoffCompletionJournal(input) {
  const { id, tape } = input;
  const families = [...(tape.families ?? [])].join(', ');
  const lines = [
    `id: ${id}-${KICKOFF_COMPLETION_SLUG}`,
    'skill: ecgberht/steward@2026-09-01',
    'situation: Gate 5 Wave 6 completion evidence for Conversational Kickoff Synthesis v0 - the fixture proof across five representative efforts plus the ONE authorized production-seat recording.',
    'context: North Star locked by John 2026-08-31; frozen plan at planning/gate5-kickoff-synthesis-2026-08-31/crucible/handoff/IMPLEMENTATION-PLAN.md; waves 1-5 GREEN under node scripts/run-all-tests.mjs.',
    `observation: The five effort fixtures (document, software, research, simple, ambiguous) pass hermetically with readable-distinction prose; the authorized live Codex-seat recording at ${tape.rel} (${tape.entry_count} seat calls, families ${families}, tape sha256 ${tape.sha256}) replays deterministically under the prompt-hash drift guard.`,
    'outcome: worked. Every North-Star criterion below carries exactly one evidence tag; criteria only John\'s screen can prove are tagged so, not claimed - they remain the final wave\'s human steps.',
    'provenance: hermetic gates plus the ONE production Codex-seat recording authorized by John 2026-09-01 (no further HALT-for-go was owed and none was raised); the tape is real model output, never authored by hand.',
    '',
    '## North-Star evidence tags',
    '',
    '| criterion | tag | proof |',
    '| --- | --- | --- |',
  ];
  for (const row of KICKOFF_NORTH_STAR_EVIDENCE) {
    lines.push(`| ${row.criterion}. ${row.claim} | ${row.tag} | ${row.proof} |`);
  }
  lines.push(
    '',
    '## Human steps (recorded, never counted by a test)',
    '',
    'The final wave (Phase 4.3) HALTs for these three human steps. They are recorded',
    'here as steps for John - no machine gate asserts their outcome, because a test',
    'that counted a human look would be a confident wrong answer.',
    '',
    '| step | what John does | proves |',
    '| --- | --- | --- |',
  );
  for (const step of KICKOFF_HUMAN_STEPS) {
    lines.push(`| ${step.id} | ${step.step} | ${step.proves} |`);
  }
  lines.push('');
  return lines.join('\n');
}

/**
 * Write (or re-derive) THE completion journal. Id resolved at write time; the slug
 * keeps it singular; a repeat with the same facts writes nothing and says so.
 *
 * @param {string} journalDir
 * @param {{tape: {rel: string, sha256: string, entry_count: number, families: string[]}}} opts
 * @returns {{ok: true, id: string, file: string, journal_path: string, written: boolean,
 *   already: boolean, updated: boolean} | object}
 */
export function writeKickoffCompletionJournal(journalDir, opts = {}) {
  const tape = opts.tape;
  if (!tape || typeof tape !== 'object' || !tape.rel || !tape.sha256
      || !Number.isInteger(tape.entry_count) || tape.entry_count < 1) {
    return journalFailure(KICKOFF_JOURNAL_CODE.TAPE_FACTS_REQUIRED, {
      error: 'tape_facts_missing_or_empty',
    });
  }
  const existing = findKickoffCompletionJournal(journalDir);
  if (!existing.ok) return existing;

  let id = existing.id;
  if (!id) {
    const next = resolveNextJournalId(journalDir);
    if (!next.ok) return next;
    id = next.id;
  }
  const file = `${id}-${KICKOFF_COMPLETION_SLUG}.md`;
  const journalPath = path.join(journalDir, file);
  const content = renderKickoffCompletionJournal({ id, tape });

  if (existing.file) {
    let current = null;
    try {
      current = fs.readFileSync(journalPath, 'utf8');
    } catch { /* unreadable existing file falls through to the rewrite below */ }
    if (current === content) {
      return { ok: true, id, file, journal_path: journalPath, written: false, already: true, updated: false };
    }
    writeFileAtomicSync(journalPath, content);
    return { ok: true, id, file, journal_path: journalPath, written: true, already: false, updated: true };
  }
  writeFileAtomicSync(journalPath, content);
  return { ok: true, id, file, journal_path: journalPath, written: true, already: false, updated: false };
}
