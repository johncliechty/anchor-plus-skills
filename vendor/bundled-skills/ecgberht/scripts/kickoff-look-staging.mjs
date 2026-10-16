/**
 * Gate 5 / Wave 9 - Phase 4.3: stage the FIVE synthetic efforts for John's look,
 * and be the Node-writes side of the integrated Ecgberht-to-Anchor canary.
 *
 * ONE mechanism, two consumers. The Anchor pytest (tests/test_kickoff_canary_w9.py,
 * declared in scripts/wave-manifests.mjs) spawns this CLI into a temp root and then
 * paints the staged states through the real pass-through reader and cockpit route -
 * the hermetic restart canary. John's actual look uses the SAME command against a
 * real folder; the HALT record quotes it. Two copies of staging logic would drift
 * exactly where the proof must not.
 *
 * WHAT GETS STAGED (KICKOFF_LOOK_EFFORT_PLAN, the halt record's data): document,
 * software, research, simple confirmed through the real engine seams (open ->
 * hash-bound confirm -> Wave 4 projection writer); research CORRECTED ONCE - a
 * spoken component rename re-proposed as the whole v2 bundle and confirmed again;
 * ambiguous left OPEN at its thin proposal, persisted through the Wave 9 open-state
 * read-model seam so a restarted Anchor paints "draft, not applied" from disk.
 * Nothing is hand-written into any store; every byte flows through the engine.
 *
 * THE RECORDED HANDOFF STATE. Kickoff ends at ready-for-first-slice and starts
 * nothing: staging runs under the Wave 2 execution-leak sentinel and records its
 * distilled report - zero execution calls, zero files outside the staged paths -
 * in <target>/kickoff-look.json beside the staged rows, the two visual claims, and
 * the human steps. The summary is canonical sorted-key UTF-8/no-float bytes,
 * written atomically; re-running the CLI on a staged root verifies and answers
 * `already` without moving a byte (every engine verb underneath is idempotent, so
 * even a re-run over a half-staged root converges to the same bytes).
 *
 * Deterministic on purpose: every `at` and client_event_id is pinned; two stagings
 * into two fresh roots produce byte-identical summaries and stores. Bounded: a
 * target already holding more than KICKOFF_LOOK_MAX_FILES files is refused by
 * name. `unknown` and `empty` summary states are SEPARATE rows. No host paths in
 * anything staged. Source is ASCII on purpose (the repo's mojibake sweep).
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  KICKOFF_STATE,
  confirmKickoffProposal,
  kickoffEventsPath,
  openKickoffProposal,
  readKickoffLineage,
} from '../engine/kickoff-lifecycle.mjs';
import {
  kickoffProjectionPath,
  writeKickoffProjection,
} from '../engine/kickoff-projection.mjs';
import { persistKickoffReadModel } from '../engine/kickoff-open-projection.mjs';
import {
  KICKOFF_HALT_RECORD_REL,
  KICKOFF_LOOK_EFFORT_PLAN,
  KICKOFF_VISUAL_CLAIMS,
} from '../engine/kickoff-halt-record.mjs';
import { KICKOFF_HUMAN_STEPS } from '../engine/kickoff-completion-journal.mjs';
import { kickoffEffortFixture } from '../engine/kickoff-effort-fixtures.mjs';
import { canonicalKickoffBytes } from '../engine/kickoff-record.mjs';
import {
  armExecutionLeakSentinel,
  captureTree,
} from '../engine/execution-leak-sentinel.mjs';
import { writeFileAtomicSync } from '../engine/durable-write.mjs';

/** The staged summary file at the target root - what `already` verifies against. */
export const KICKOFF_LOOK_FILE = 'kickoff-look.json';
export const KICKOFF_LOOK_SCHEMA = 'ecgberht-kickoff-look-v0';

/** The named bound: a target already holding more files than this is refused. */
export const KICKOFF_LOOK_MAX_FILES = 500;

const SEAT = Object.freeze({ seat_family: 'chatgpt', driver: 'chatgpt-cli' });
const AT_OPEN = '2026-09-01T10:00:00Z';
const AT_CONFIRM = '2026-09-01T10:05:00Z';
const AT_CORRECT = '2026-09-01T10:10:00Z';
const AT_RECONFIRM = '2026-09-01T10:15:00Z';

export const KICKOFF_LOOK_CODE = Object.freeze({
  STAGED: 'KICKOFF_LOOK_STAGED',
  ALREADY: 'KICKOFF_LOOK_ALREADY_STAGED',
  NOT_STAGED: 'KICKOFF_LOOK_NOT_STAGED',
  UNKNOWN: 'KICKOFF_LOOK_STATE_UNKNOWN',
  EMPTY: 'KICKOFF_LOOK_SUMMARY_EMPTY',
  GARBAGE: 'KICKOFF_LOOK_SUMMARY_GARBAGE',
  CONFLICT: 'KICKOFF_LOOK_TARGET_CONFLICT',
  TREE_BOUND: 'KICKOFF_LOOK_TREE_BOUND_EXCEEDED',
});

export const KICKOFF_LOOK_TEXT = Object.freeze({
  [KICKOFF_LOOK_CODE.STAGED]:
    'The five efforts are staged for John\'s look - kickoff ends at ready-for-first-slice; nothing started.',
  [KICKOFF_LOOK_CODE.ALREADY]:
    'This target is already staged and verifies - nothing rewritten.',
  [KICKOFF_LOOK_CODE.NOT_STAGED]:
    'No staged look at this target - nothing to verify.',
  [KICKOFF_LOOK_CODE.UNKNOWN]:
    'The staged summary is not readable here (<error>) - reported as unknown, not guessed.',
  [KICKOFF_LOOK_CODE.EMPTY]:
    'The staged summary file is empty - the target is half-staged; refused rather than trusted.',
  [KICKOFF_LOOK_CODE.GARBAGE]:
    'The staged summary does not parse as a staging record (<error>) - refused rather than guessed.',
  [KICKOFF_LOOK_CODE.CONFLICT]:
    'The staged efforts do not match their summary (<error>) - refused rather than overwritten blind; point the staging at a fresh folder.',
  [KICKOFF_LOOK_CODE.TREE_BOUND]:
    'The target already holds more files than the staging bound (<error>) - refused rather than staged into an unbounded tree.',
});

function lookFailure(code, extra = {}) {
  const error = extra.error ?? String(code).toLowerCase();
  const text = KICKOFF_LOOK_TEXT[code].replace(/<error>/g, String(error));
  return { ok: false, code, status_code: code, error, text, user_text: text, ...extra };
}

/**
 * Machine-readable failure-state table for the staging surface. `unknown` and
 * `empty` are SEPARATE rows; store-side rows (backing store unreadable, lock
 * contended, lineage corrupt) ride through from the engine verbs by name.
 */
export function kickoffLookFailureTable() {
  const row = (state, code) => Object.freeze({
    state,
    surface: 'kickoff_look_staging',
    status_code: code,
    user_text: KICKOFF_LOOK_TEXT[code],
  });
  return Object.freeze([
    row('staged', KICKOFF_LOOK_CODE.STAGED),
    row('already-staged', KICKOFF_LOOK_CODE.ALREADY),
    row('not-staged', KICKOFF_LOOK_CODE.NOT_STAGED),
    row('unknown', KICKOFF_LOOK_CODE.UNKNOWN),
    row('empty-but-valid', KICKOFF_LOOK_CODE.EMPTY),
    row('dependency-returns-garbage', KICKOFF_LOOK_CODE.GARBAGE),
    row('target-conflict', KICKOFF_LOOK_CODE.CONFLICT),
    row('bound-exceeded', KICKOFF_LOOK_CODE.TREE_BOUND),
  ]);
}

/** Deep plain clone - fixture bundles are deep-frozen shared truth. */
function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

/** The model-authored bundle a fixture ends on (its final planning-tier reply). */
function fixtureBundle(key) {
  const fixture = kickoffEffortFixture(key);
  return clone(fixture.plan[fixture.plan.length - 1].proposal);
}

/**
 * The ONE spoken correction, as data: "call the evidence log the source ledger."
 * A whole-bundle re-proposal (never a field edit): the v1 bundle with that single
 * component renamed, re-opened as v2 and confirmed once more.
 */
export function correctedResearchBundle() {
  const bundle = fixtureBundle('research');
  const log = bundle.work_product.components.find((component) => component.id === 'evidence-log');
  log.name = 'The source ledger';
  return bundle;
}

/** The deterministic discovery Face staged beside each effort (display data only). */
function effortFaceText(label) {
  return [
    '# Ecgberht - Face (campaign memory)',
    '',
    '## North star',
    '',
    `${label} - staged for John's look (Gate 5 Wave 9).`,
    '',
  ].join('\n');
}

/** POSIX rel path of a file under root. */
function relPosix(root, absPath) {
  return path.relative(root, absPath).split(path.sep).join('/');
}

/**
 * Stage ONE effort through the real engine seams; answer the summary row.
 *
 * STATE-AWARE ON PURPOSE (the documented serialization): staging is a single
 * writer, and every store write underneath takes the store's own cross-process
 * lock - but a re-run over a HALF-staged effort (a crash before the summary
 * landed) must converge, never append a phantom draft. So each verb runs only
 * when the lineage has not reached that stage yet; with the pinned ids every
 * replayed step re-derives the same bytes, and a completed effort is pure
 * re-projection. Racing two FIRST-TIME stagings is not a supported mode; the
 * summary-existence check keeps completed roots re-run-safe.
 */
function stageEffort(root, planRow) {
  const fixture = kickoffEffortFixture(planRow.key);
  const effortDir = path.join(root, planRow.dir);
  fs.mkdirSync(effortDir, { recursive: true });
  writeFileAtomicSync(path.join(effortDir, 'ECGBERHT.md'), effortFaceText(fixture.label));

  let lineage = readKickoffLineage(effortDir);
  if (!lineage.ok) return { ...lineage, look_step: `read ${planRow.key}` };

  if (lineage.state === KICKOFF_STATE.EMPTY) {
    const opened = openKickoffProposal(effortDir, {
      proposal: fixtureBundle(planRow.key),
      ...SEAT,
      client_event_id: `look-${planRow.key}-t1`,
      at: AT_OPEN,
    });
    if (!opened.ok) return { ...opened, look_step: `open ${planRow.key}` };
    lineage = readKickoffLineage(effortDir);
    if (!lineage.ok) return { ...lineage, look_step: `reread ${planRow.key}` };
  }

  if (planRow.staged === 'open') {
    const persisted = persistKickoffReadModel(effortDir);
    if (!persisted.ok) return { ...persisted, look_step: `persist-open ${planRow.key}` };
    return {
      ok: true,
      key: planRow.key,
      dir: planRow.dir,
      label: fixture.label,
      state: 'open',
      version: persisted.open_draft.version,
      proposal_hash: persisted.open_draft.proposal_hash,
      receipt_hash: null,
      prior_confirmed_hash: null,
      first_slice_id: null,
      corrected: false,
      ready_for_first_slice: false,
      handoff_state: 'open-draft-not-applied',
      goal: persisted.open_draft.goal,
    };
  }

  if (!lineage.confirmed) {
    if (!lineage.open) {
      return lookFailure(KICKOFF_LOOK_CODE.CONFLICT, {
        error: `${planRow.key}: no open proposal to confirm`,
      });
    }
    const confirmed = confirmKickoffProposal(effortDir, {
      who: 'john',
      proposal_hash: lineage.open.proposal_hash,
      rendered_prose_hash: lineage.open.rendered_prose_hash,
      client_event_id: `look-${planRow.key}-c1`,
      at: AT_CONFIRM,
    });
    if (!confirmed.ok) return { ...confirmed, look_step: `confirm ${planRow.key}` };
    lineage = readKickoffLineage(effortDir);
    if (!lineage.ok) return { ...lineage, look_step: `reread ${planRow.key}` };
  }

  if (planRow.corrected && lineage.confirmed.version < 2) {
    if (!lineage.open || lineage.open.version < 2) {
      const reopened = openKickoffProposal(effortDir, {
        proposal: correctedResearchBundle(),
        ...SEAT,
        client_event_id: `look-${planRow.key}-t2`,
        at: AT_CORRECT,
      });
      if (!reopened.ok) return { ...reopened, look_step: `correct ${planRow.key}` };
      lineage = readKickoffLineage(effortDir);
      if (!lineage.ok) return { ...lineage, look_step: `reread ${planRow.key}` };
    }
    const reconfirmed = confirmKickoffProposal(effortDir, {
      who: 'john',
      proposal_hash: lineage.open.proposal_hash,
      rendered_prose_hash: lineage.open.rendered_prose_hash,
      client_event_id: `look-${planRow.key}-c2`,
      at: AT_RECONFIRM,
    });
    if (!reconfirmed.ok) return { ...reconfirmed, look_step: `reconfirm ${planRow.key}` };
  }

  const written = writeKickoffProjection(effortDir);
  if (!written.ok) return { ...written, look_step: `project ${planRow.key}` };
  return {
    ok: true,
    key: planRow.key,
    dir: planRow.dir,
    label: fixture.label,
    state: 'confirmed',
    version: written.version,
    proposal_hash: written.proposal_hash,
    receipt_hash: written.receipt_hash,
    prior_confirmed_hash: written.projection.confirmed.prior_confirmed_hash,
    first_slice_id: written.projection.execution.first_slice_id,
    corrected: planRow.corrected === true,
    ready_for_first_slice: true,
    handoff_state: 'ready-for-first-slice',
    goal: written.projection.intent.goal,
  };
}

/**
 * Verify an existing staged target against its own summary: every staged row's
 * projection.json must still carry the state, version, and hash the summary
 * recorded. `unknown` (unreadable) and `empty` are separate answers.
 *
 * @param {string} targetRoot
 */
export function verifyStagedKickoffLook(targetRoot) {
  const root = path.resolve(targetRoot);
  const lookPath = path.join(root, KICKOFF_LOOK_FILE);
  if (!fs.existsSync(lookPath)) return lookFailure(KICKOFF_LOOK_CODE.NOT_STAGED);
  let raw;
  try {
    raw = fs.readFileSync(lookPath, 'utf8');
  } catch (error) {
    return lookFailure(KICKOFF_LOOK_CODE.UNKNOWN, { error: error?.code ?? 'summary_unreadable' });
  }
  if (!raw.trim()) return lookFailure(KICKOFF_LOOK_CODE.EMPTY);
  let summary;
  try {
    summary = JSON.parse(raw);
  } catch {
    return lookFailure(KICKOFF_LOOK_CODE.GARBAGE, { error: 'summary_json_unparseable' });
  }
  if (summary?.schema !== KICKOFF_LOOK_SCHEMA || !Array.isArray(summary.staged)) {
    return lookFailure(KICKOFF_LOOK_CODE.GARBAGE, { error: 'summary_schema_unknown' });
  }
  for (const row of summary.staged) {
    const projectionPath = kickoffProjectionPath(path.join(root, row.dir));
    let doc;
    try {
      doc = JSON.parse(fs.readFileSync(projectionPath, 'utf8'));
    } catch {
      return lookFailure(KICKOFF_LOOK_CODE.CONFLICT, { error: `${row.key}: projection missing or unreadable` });
    }
    const hash = doc.state === 'confirmed'
      ? doc.confirmed?.proposal_hash
      : doc.open_draft?.proposal_hash;
    const version = doc.state === 'confirmed' ? doc.confirmed?.version : doc.open_draft?.version;
    if (doc.state !== row.state || hash !== row.proposal_hash || version !== row.version) {
      return lookFailure(KICKOFF_LOOK_CODE.CONFLICT, { error: `${row.key}: staged state drifted from its summary` });
    }
  }
  return { ok: true, verified: true, look_path: lookPath, summary };
}

/**
 * Stage the five efforts (idempotent, bounded, sentinel-armed). See the header.
 *
 * @param {string} targetRoot
 * @returns {object} the staged (or `already`) row, or a named refusal
 */
export function stageKickoffLook(targetRoot) {
  const root = path.resolve(targetRoot);
  const lookPath = path.join(root, KICKOFF_LOOK_FILE);

  if (fs.existsSync(lookPath)) {
    const verified = verifyStagedKickoffLook(root);
    if (!verified.ok) return verified;
    return {
      ok: true,
      code: KICKOFF_LOOK_CODE.ALREADY,
      status_code: KICKOFF_LOOK_CODE.ALREADY,
      user_text: KICKOFF_LOOK_TEXT[KICKOFF_LOOK_CODE.ALREADY],
      already: true,
      written: false,
      target: root,
      look_path: lookPath,
      summary: verified.summary,
      staged_count: verified.summary.staged.length,
    };
  }

  // The named bound on what this CLI will stage INTO: a huge pre-existing tree
  // is refused by name, never walked and never written over.
  if (fs.existsSync(root)) {
    const walk = captureTree(root, { max_files: KICKOFF_LOOK_MAX_FILES });
    if (!walk.ok) {
      return lookFailure(KICKOFF_LOOK_CODE.TREE_BOUND, {
        error: `${walk.count}+ files > ${KICKOFF_LOOK_MAX_FILES}`,
        bound: KICKOFF_LOOK_MAX_FILES,
      });
    }
  }
  fs.mkdirSync(root, { recursive: true });

  // The Wave 2 sentinel, armed over the whole staging: the recorded handoff
  // state carries ITS word, not this script's, that nothing executed.
  const allow = [...KICKOFF_LOOK_EFFORT_PLAN.map((row) => `${row.dir}/`), KICKOFF_LOOK_FILE];
  const sentinel = armExecutionLeakSentinel(root, { allow });
  if (!sentinel.ok) return sentinel;

  let report;
  const staged = [];
  try {
    for (const planRow of KICKOFF_LOOK_EFFORT_PLAN) {
      const row = stageEffort(root, planRow);
      if (!row.ok) return row;
      staged.push(row);
    }
    report = sentinel.report();
  } finally {
    sentinel.disarm();
  }
  if (!report.ok) return report;

  const summary = {
    schema: KICKOFF_LOOK_SCHEMA,
    command: 'node scripts/kickoff-look-staging.mjs',
    handoff_state: 'ready-for-first-slice',
    execution_started: false,
    staged,
    visual_claims: clone(KICKOFF_VISUAL_CLAIMS),
    human_steps: clone(KICKOFF_HUMAN_STEPS),
    halt_record_rel: KICKOFF_HALT_RECORD_REL,
    leak_sentinel: {
      code: report.code,
      status_code: report.status_code,
      user_text: report.user_text,
      execution_calls: report.execution_calls.length,
      calls_by_seam: clone(report.calls_by_seam),
      outside_allowed: report.outside_allowed.length,
    },
  };
  const canonical = canonicalKickoffBytes(summary);
  if (!canonical.ok) return canonical;
  writeFileAtomicSync(lookPath, `${canonical.text}\n`);

  return {
    ok: true,
    code: KICKOFF_LOOK_CODE.STAGED,
    status_code: KICKOFF_LOOK_CODE.STAGED,
    user_text: KICKOFF_LOOK_TEXT[KICKOFF_LOOK_CODE.STAGED],
    already: false,
    written: true,
    target: root,
    look_path: lookPath,
    look_rel: KICKOFF_LOOK_FILE,
    events_rel: staged.map((row) => relPosix(root, kickoffEventsPath(path.join(root, row.dir)))),
    summary,
    staged_count: staged.length,
  };
}

const isMain =
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  const target = process.argv[2];
  if (!target) {
    console.error('usage: node scripts/kickoff-look-staging.mjs <target-dir>');
    process.exit(2);
  }
  const result = stageKickoffLook(target);
  console.log(JSON.stringify(result));
  process.exit(result.ok ? 0 : 1);
}
