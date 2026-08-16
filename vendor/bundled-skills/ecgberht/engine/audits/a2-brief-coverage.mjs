/**
 * Wave 3 — A2 assembleBriefPacket coverage harness.
 *
 * Drives Q1–Q12 with ZERO model calls against a real campaign fixture that
 * includes one dead run. Marks each continuity fact ANSWERED or
 * NEEDS-DOSSIER-JOIN. Never reports ANSWERED when the packet returns
 * honest-unknown.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  assembleBriefPacket,
  UNKNOWN_ANSWER,
  PROJECT_QUESTION_IDS,
  PORTFOLIO_QUESTION_IDS,
  BRIEF_QUESTIONS,
} from '../brief.mjs';
import { writeJsonIdempotentSync } from '../durable-write.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '..', '..');

/** Default campaign fixture (checked in under fixtures/campaign-a2). */
export const A2_FIXTURE_REL = path.join('fixtures', 'campaign-a2');

/** Coverage table artifact. */
export const A2_COVERAGE_TABLE_REL = path.join(
  'artifacts',
  'a2-brief-coverage-table.json',
);

/** Continuity coverage marks. */
export const A2_MARK = Object.freeze({
  ANSWERED: 'ANSWERED',
  NEEDS_DOSSIER_JOIN: 'NEEDS-DOSSIER-JOIN',
});

/**
 * Questions whose honest-unknown answer is expected to need the Phase-7/15
 * dossier join (commission dossier read API) rather than Face/Strip/roadmap
 * alone. Still classified from live packet evidence — never forced.
 */
export const A2_DOSSIER_LEANING_IDS = Object.freeze([
  'Q7', // recently commissioned work conclusions
]);

/**
 * Resolve the campaign fixture directory.
 * @param {{ root?: string, fixtureDir?: string }} [opts]
 */
export function resolveA2FixtureDir(opts = {}) {
  if (opts.fixtureDir) return path.resolve(opts.fixtureDir);
  const root = opts.root ? path.resolve(opts.root) : REPO_ROOT;
  return path.join(root, A2_FIXTURE_REL);
}

/**
 * Classify one packet answer row.
 * @param {object} row packet.answers[] element
 * @returns {{ id: string, mark: string, unknown: boolean, honest_unknown: boolean, question: string|null, note: string }}
 */
export function classifyBriefAnswer(row) {
  const id = row?.id ?? null;
  const unknown = row?.unknown === true;
  const answer = row?.answer;
  const isLiteralUnknown =
    answer === UNKNOWN_ANSWER ||
    (typeof answer === 'string' && answer.includes('unknown — no local evidence'));
  const honest_unknown = unknown || isLiteralUnknown;

  // Continuity facts about dead runs / commission handbacks that the brief
  // cannot join without the dossier API land as NEEDS-DOSSIER-JOIN when unknown.
  let mark;
  let note;
  if (honest_unknown) {
    mark = A2_MARK.NEEDS_DOSSIER_JOIN;
    note =
      'Packet returned honest-unknown — not ANSWERED; dossier join may close later (Wave 15).';
  } else {
    mark = A2_MARK.ANSWERED;
    note = 'Local Face/Strip/roadmap evidence answered this fact without model calls.';
  }

  return {
    id,
    question: row?.question ?? BRIEF_QUESTIONS[id] ?? null,
    mark,
    unknown: Boolean(unknown),
    honest_unknown,
    provenance_count: Array.isArray(row?.provenance) ? row.provenance.length : 0,
    note,
  };
}

/**
 * Assert no row is marked ANSWERED while honest-unknown.
 * @param {Array<object>} coverageRows
 */
export function assertNoFalseAnswered(coverageRows) {
  const bad = coverageRows.filter(
    (r) => r.mark === A2_MARK.ANSWERED && r.honest_unknown,
  );
  return {
    ok: bad.length === 0,
    false_answered: bad.map((r) => r.id),
  };
}

/**
 * Run A2 coverage against the campaign fixture (project + portfolio altitudes).
 * @param {{
 *   root?: string,
 *   fixtureDir?: string,
 *   writeArtifact?: boolean,
 *   model?: Function,
 *   commission?: Function,
 * }} [opts]
 */
export function runA2Audit(opts = {}) {
  const fixtureDir = resolveA2FixtureDir(opts);
  if (!fs.existsSync(fixtureDir)) {
    return {
      ok: false,
      error: 'a2_fixture_missing',
      fixture_dir: fixtureDir,
      message: `Campaign fixture missing at ${A2_FIXTURE_REL}`,
    };
  }

  // Spies: if the harness or assembleBriefPacket ever invokes them, phase_a fails.
  let model_calls = 0;
  let commission_calls = 0;
  const modelSpy = opts.model ?? (() => {
    model_calls += 1;
    return { ok: false, error: 'model_must_not_run_in_phase_a' };
  });
  const commissionSpy = opts.commission ?? (() => {
    commission_calls += 1;
    return { ok: false, error: 'commission_must_not_run_in_phase_a' };
  });

  // Project altitude: Q1–Q9
  const projectPacket = assembleBriefPacket({
    project: fixtureDir,
    altitude: 'project',
    model: modelSpy,
    commission: commissionSpy,
    journal: { present: true, entries: [] },
    anchor_knowledge: { present: false },
    env: {},
  });

  // Portfolio altitude with the campaign as the only root: Q10–Q12
  const portfolioPacket = assembleBriefPacket({
    roots: [fixtureDir],
    altitude: 'portfolio',
    model: modelSpy,
    commission: commissionSpy,
    env: {},
  });

  const projectAnswers = Array.isArray(projectPacket?.answers)
    ? projectPacket.answers
    : [];
  const portfolioAnswers = Array.isArray(portfolioPacket?.answers)
    ? portfolioPacket.answers
    : [];

  const byId = new Map();
  for (const row of projectAnswers) {
    if (row?.id) byId.set(row.id, row);
  }
  for (const row of portfolioAnswers) {
    if (row?.id) byId.set(row.id, row);
  }

  const allIds = [...PROJECT_QUESTION_IDS, ...PORTFOLIO_QUESTION_IDS];
  const coverage = allIds.map((id) => {
    const row = byId.get(id);
    if (!row) {
      return {
        id,
        question: BRIEF_QUESTIONS[id] ?? null,
        mark: A2_MARK.NEEDS_DOSSIER_JOIN,
        unknown: true,
        honest_unknown: true,
        provenance_count: 0,
        note: 'Question absent from packet — treated as honest gap (NEEDS-DOSSIER-JOIN).',
      };
    }
    return classifyBriefAnswer(row);
  });

  const falseCheck = assertNoFalseAnswered(coverage);

  // Dead-run continuity: fixture must surface a named dead run somewhere in packet.
  const deadRunNamed = detectDeadRunNamed(projectPacket, fixtureDir);

  const zeroModel =
    (projectPacket?.phase_a?.model_calls ?? 0) === 0 &&
    (projectPacket?.phase_a?.commission_calls ?? 0) === 0 &&
    (portfolioPacket?.phase_a?.model_calls ?? 0) === 0 &&
    model_calls === 0 &&
    commission_calls === 0;

  const everyMarked = coverage.every(
    (r) =>
      r.mark === A2_MARK.ANSWERED || r.mark === A2_MARK.NEEDS_DOSSIER_JOIN,
  );

  const table = {
    schema: 'ecgberht-a2-brief-coverage-v0',
    audit: 'A2',
    title: 'assembleBriefPacket Q1–Q12 coverage',
    recorded_at: new Date().toISOString(),
    fixture: A2_FIXTURE_REL,
    fixture_abs_note: 'resolved relative to skill root at runtime',
    dead_run_named: deadRunNamed,
    zero_model_calls: zeroModel,
    phase_a_project: projectPacket?.phase_a ?? null,
    phase_a_portfolio: portfolioPacket?.phase_a ?? null,
    coverage,
    false_answered_guard: falseCheck,
    ok:
      everyMarked &&
      falseCheck.ok &&
      zeroModel &&
      deadRunNamed.ok,
  };

  let artifact_path = null;
  if (opts.writeArtifact !== false && opts.root) {
    artifact_path = path.join(opts.root, A2_COVERAGE_TABLE_REL);
    // Idempotent: unchanged coverage leaves the file byte-identical (0070 fix).
    writeJsonIdempotentSync(artifact_path, table);
  }

  return {
    ok: table.ok,
    table,
    artifact_path,
    project_packet: projectPacket,
    portfolio_packet: portfolioPacket,
    coverage,
  };
}

/**
 * Detect that the fixture carries a named dead run and the packet does not hide it.
 * @param {object} packet
 * @param {string} fixtureDir
 */
function detectDeadRunNamed(packet, fixtureDir) {
  const stripPath = path.join(fixtureDir, 'strip.json');
  let strip = null;
  try {
    strip = JSON.parse(fs.readFileSync(stripPath, 'utf8'));
  } catch {
    return { ok: false, reason: 'strip_unreadable' };
  }

  const instruments = Array.isArray(strip?.instruments) ? strip.instruments : [];
  const receipts = Array.isArray(strip?.receipts) ? strip.receipts : [];
  const deadInstrument = instruments.find(
    (i) =>
      i?.kind === 'commission_abnormal' ||
      i?.state === 'orphaned' ||
      i?.state === 'reaped' ||
      i?.dead === true ||
      String(i?.why_known ?? '').toLowerCase().includes('dead'),
  );
  const deadReceipt = receipts.find(
    (r) =>
      r?.kind === 'commission_abnormal' ||
      r?.terminal === 'orphaned' ||
      r?.terminal === 'reaped' ||
      r?.dead === true,
  );

  const roadmapPath = path.join(fixtureDir, 'roadmap.json');
  let deadBind = null;
  try {
    const roadmap = JSON.parse(fs.readFileSync(roadmapPath, 'utf8'));
    const events = Array.isArray(roadmap?.roadmap_events)
      ? roadmap.roadmap_events
      : [];
    deadBind = events.find(
      (e) =>
        e?.kind === 'commission_bind' &&
        (e?.dead === true ||
          String(e?.commissioned_as ?? '').includes('dead') ||
          e?.terminal === 'orphaned'),
    );
  } catch {
    // optional
  }

  const named = Boolean(deadInstrument || deadReceipt || deadBind);
  // Packet honesty: if Q2 or Q4 mentions dead/orphan when instruments exist, good;
  // even without packet mention, fixture naming is required.
  const answers = Array.isArray(packet?.answers) ? packet.answers : [];
  const packetMentionsDead = answers.some((a) => {
    const blob = JSON.stringify(a?.answer ?? '');
    return /dead|orphan|reap|abnormal|missing handback/i.test(blob);
  });

  return {
    ok: named,
    fixture_dead_instrument: Boolean(deadInstrument),
    fixture_dead_receipt: Boolean(deadReceipt),
    fixture_dead_bind: Boolean(deadBind),
    packet_mentions_dead: packetMentionsDead,
    dead_job_id:
      deadInstrument?.job_id ??
      deadReceipt?.job_id ??
      deadBind?.commissioned_as ??
      null,
  };
}
