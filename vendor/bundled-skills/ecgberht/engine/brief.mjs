/**
 * TW2 — Decision Packet / brief engine (W7 reframed).
 *
 * The valued-servant mechanic: a FIXED question set (Q1–Q12) answered by
 * DETERMINISTIC retrieval from local stores, with per-answer provenance and
 * honest `unknown — no local evidence` where a store is silent.
 *
 * Two-phase law:
 * - Phase A assembles the whole packet with ZERO model / commission calls
 *   (this module deliberately imports neither the commission nor the seating
 *   module; tests canary the import list). Phase A is complete offline.
 * - Phase B (optional recommend) may consult a model; it is never required
 *   for green. Model unavailable → Phase A complete + recommendation unknown.
 *
 * `seen` receipt {kind, who, when, altitude} is the delta anchor for Q2 —
 * append-only via appendStripReceipt; prior history never rewritten.
 *
 * Precompute cache is a DECLARED PROJECTION (annex A6 discipline): zero write
 * authority, regenerable at any time, never read back as truth.
 */

import fs from 'node:fs';
import crypto from 'node:crypto';
import { writeFileAtomicSync } from './durable-write.mjs';
import path from 'node:path';

import { SPELLING } from './verbs.mjs';
import {
  FACE_FILE_NAME,
  STRIP_FILE_NAME,
  loadProjectSurfaces,
  resolveProjectPath,
  toStripProjection,
} from './face-strip.mjs';
import { appendStripReceipt } from './write-authority.mjs';
import { RECEIPT_SCHEMA_ID } from './receipt-validate.mjs';
import { loadProjectRoadmap, validateRoadmap } from './roadmap.mjs';
import { suggestDepthFromStrip, loadDispatchTable } from './dispatch-table.mjs';
import { discoverStrips } from './discovery.mjs';
import { rankPortfolioStripFirst } from './rank.mjs';
import {
  readAnchorProjectKnowledge,
  anchorConclusions,
} from './anchor-knowledge.mjs';

/**
 * Content-hash helper for brief cache anchors (A3). Counts are a weak key —
 * a healed/replaced-in-place roadmap can preserve length while changing meaning.
 * @param {unknown} value
 * @returns {string}
 */
export function hashBriefContent(value) {
  const bytes =
    typeof value === 'string'
      ? value
      : JSON.stringify(value ?? null, (_k, v) => v);
  return crypto.createHash('sha256').update(bytes, 'utf8').digest('hex');
}

/**
 * Face VERSION for the A3 staleness key — explicit version field if present,
 * else a content hash of the Face document (raw markdown preferred).
 * @param {object|null|undefined} face
 * @returns {string|null}
 */
export function faceVersionOf(face) {
  if (!face || typeof face !== 'object') return null;
  if (face.version != null && String(face.version).length > 0) {
    return String(face.version);
  }
  if (typeof face.raw === 'string' && face.raw.length > 0) {
    return hashBriefContent(face.raw);
  }
  if (face.narrative && typeof face.narrative === 'object') {
    return hashBriefContent(face.narrative);
  }
  return null;
}

/**
 * Last roadmap event seq + content hash (A3 content-anchored key).
 * @param {object|null|undefined} roadmap
 * @returns {{ seq: number|null, hash: string|null, count: number }}
 */
export function lastRoadmapEventAnchor(roadmap) {
  const events = Array.isArray(roadmap?.roadmap_events)
    ? roadmap.roadmap_events
    : [];
  if (events.length === 0) {
    return { seq: null, hash: null, count: 0 };
  }
  const last = events[events.length - 1];
  const seq =
    typeof last?.seq === 'number' && Number.isFinite(last.seq)
      ? last.seq
      : events.length;
  return {
    seq,
    hash: hashBriefContent(last),
    count: events.length,
  };
}

export const BRIEF_SCHEMA_ID = 'ecgberht-brief-v0';
export const BRIEF_CACHE_SCHEMA_ID = 'ecgberht-brief-cache-v0';
export const BRIEF_CACHE_FILE_NAME = 'brief-cache.json';

/** The literal honest-unknown line — never filler. */
export const UNKNOWN_ANSWER = 'unknown — no local evidence';

/** Brief altitudes. */
export const BRIEF_ALTITUDES = Object.freeze(['project', 'portfolio']);

/** Locked seen-receipt shape (delta anchor for Q2). */
export const SEEN_RECEIPT_FIELDS = Object.freeze([
  'kind',
  'who',
  'when',
  'altitude',
]);

/** Project-altitude question ids (W7-BRIEF-SPEC §2). */
export const PROJECT_QUESTION_IDS = Object.freeze([
  'Q1',
  'Q2',
  'Q3',
  'Q4',
  'Q5',
  'Q6',
  'Q7',
  'Q8',
  'Q9',
]);

/** Portfolio-altitude adds. */
export const PORTFOLIO_QUESTION_IDS = Object.freeze(['Q10', 'Q11', 'Q12']);

/** The standing question set — fixed, known in advance. */
export const BRIEF_QUESTIONS = Object.freeze({
  Q1: 'Where is this campaign, toward what?',
  Q2: 'What happened since I last looked?',
  Q3: 'What is waiting on me?',
  Q4: 'What is blocked / uncertain, and why?',
  Q5: 'What will the next move cost; can we afford it?',
  Q6: "What's the next best move and why?",
  Q7: 'What did recently commissioned work conclude?',
  Q8: "What's parked that's now relevant?",
  Q9: "What's likely to bite next?",
  Q10: 'Decision Queue — everything waiting on the human, ranked',
  Q11: 'What blocker is shared across projects?',
  Q12: 'What is starving?',
});

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function nowIso() {
  return new Date().toISOString();
}

function nonEmpty(v) {
  return typeof v === 'string' && v.trim() !== '';
}

function answered(id, answer, provenance, extra = {}) {
  return {
    id,
    question: BRIEF_QUESTIONS[id],
    unknown: false,
    answer,
    provenance: Array.isArray(provenance) ? provenance : [provenance].filter(Boolean),
    ...extra,
  };
}

function unknownAnswer(id, extra = {}) {
  return {
    id,
    question: BRIEF_QUESTIONS[id],
    unknown: true,
    answer: UNKNOWN_ANSWER,
    provenance: [],
    ...extra,
  };
}

// ---------------------------------------------------------------------------
// seen receipt — the delta anchor
// ---------------------------------------------------------------------------

/**
 * Build a `seen` receipt {kind, who, when, altitude} + snapshot counters that
 * make the Q2 delta exact (counters are extra fields; the locked four stand).
 * @param {{ who: string, when?: string, altitude?: string, strip?: object|null, journal_seen?: number }} fields
 */
export function buildSeenReceipt(fields = {}) {
  const when = nonEmpty(fields.when) ? fields.when : nowIso();
  const altitude = BRIEF_ALTITUDES.includes(fields.altitude)
    ? fields.altitude
    : 'project';
  const strip = fields.strip ?? null;
  return {
    schema: RECEIPT_SCHEMA_ID,
    kind: 'seen',
    as_of: when.slice(0, 10),
    who: fields.who ?? null,
    when,
    altitude,
    instruments_seen: Array.isArray(strip?.instruments)
      ? strip.instruments.length
      : 0,
    receipts_seen: Array.isArray(strip?.receipts) ? strip.receipts.length : 0,
    journal_seen:
      typeof fields.journal_seen === 'number' ? fields.journal_seen : null,
  };
}

/**
 * Find the last `seen` receipt on a Strip (optionally altitude-scoped).
 * @param {object|null} strip
 * @param {{ altitude?: string }} [opts]
 * @returns {{ receipt: object|null, index: number }}
 */
export function findLastSeen(strip, opts = {}) {
  const receipts = Array.isArray(strip?.receipts) ? strip.receipts : [];
  for (let i = receipts.length - 1; i >= 0; i--) {
    const r = receipts[i];
    if (!r || r.kind !== 'seen') continue;
    if (opts.altitude && r.altitude !== opts.altitude) continue;
    return { receipt: r, index: i };
  }
  return { receipt: null, index: -1 };
}

/**
 * Append a `seen` receipt (append-only; prior history untouched).
 * Refuses without a non-empty `who`.
 * @param {object} strip
 * @param {{ who: string, when?: string, altitude?: string, journal_seen?: number }} fields
 */
export function appendSeenReceipt(strip, fields = {}) {
  if (!nonEmpty(fields.who)) {
    return {
      ok: false,
      error: 'seen_requires_who',
      spelling: SPELLING,
      required: [...SEEN_RECEIPT_FIELDS],
      message:
        'seen receipt requires who (kind/when/altitude are stamped; append-only law applies).',
    };
  }
  const receipt = buildSeenReceipt({ ...fields, strip });
  const appended = appendStripReceipt(strip, receipt, {
    apply_to_projection: false,
  });
  if (!appended.ok) return appended;
  return {
    ok: true,
    authority: 'strip_append_only',
    strip: appended.strip,
    receipt,
  };
}

// ---------------------------------------------------------------------------
// journal (local evidence for Q2/Q9)
// ---------------------------------------------------------------------------

/**
 * List a project's journal entries (journal/*.md), name-sorted.
 * Numbered-journal convention makes name order append-only.
 * @param {string} projectPath
 * @returns {{ present: boolean, entries: { file: string, name: string }[] }}
 */
export function listJournalEntries(projectPath) {
  const dir = path.join(path.resolve(projectPath), 'journal');
  let names = [];
  try {
    names = fs
      .readdirSync(dir)
      .filter((n) => n.endsWith('.md') && n.toLowerCase() !== 'readme.md')
      .sort();
  } catch {
    return { present: false, entries: [] };
  }
  return {
    present: true,
    entries: names.map((name) => ({ file: `journal/${name}`, name })),
  };
}

/**
 * Q2 delta: instruments/receipts appended AFTER the last seen receipt
 * + journal entries beyond the seen journal counter. Exact, count-anchored.
 * @param {object|null} strip
 * @param {{ receipt: object|null, index: number }} seen result of findLastSeen
 * @param {{ journal?: { present: boolean, entries: object[] } }} [opts]
 */
export function deltaSinceSeen(strip, seen, opts = {}) {
  const instruments = Array.isArray(strip?.instruments) ? strip.instruments : [];
  const receipts = Array.isArray(strip?.receipts) ? strip.receipts : [];
  const journal = opts.journal ?? { present: false, entries: [] };

  if (!seen?.receipt) {
    return {
      anchored: false,
      seen: null,
      instruments: [...instruments],
      receipts: [...receipts],
      journal: journal.entries,
      note: 'no seen receipt on file — full local history shown',
    };
  }

  const instFrom =
    typeof seen.receipt.instruments_seen === 'number'
      ? seen.receipt.instruments_seen
      : instruments.length;
  const journalFrom =
    typeof seen.receipt.journal_seen === 'number'
      ? seen.receipt.journal_seen
      : journal.entries.length;

  return {
    anchored: true,
    seen: {
      who: seen.receipt.who ?? null,
      when: seen.receipt.when ?? null,
      altitude: seen.receipt.altitude ?? null,
    },
    instruments: instruments.slice(instFrom),
    receipts: receipts.slice(seen.index + 1).filter((r) => r?.kind !== 'seen'),
    journal: journal.entries.slice(journalFrom),
  };
}

// ---------------------------------------------------------------------------
// Phase A — deterministic packet assembly (zero model / commission calls)
// ---------------------------------------------------------------------------

/**
 * Roadmap-aware position: where are we in the major steps.
 * Face-only prose → honest gap; steps never invented.
 * @param {object|null} roadmapResult validated roadmap projection or null
 */
function roadmapPosition(roadmapResult) {
  if (!roadmapResult || !roadmapResult.present || !roadmapResult.valid) {
    return {
      present: false,
      gap: roadmapResult?.gap ?? 'no_roadmap',
      current_step: null,
      steps_done: 0,
      steps_total: 0,
      invented_steps: false,
    };
  }
  const steps = roadmapResult.projection;
  const current =
    steps.find((s) => s.status === 'active') ??
    steps.find((s) => s.status === 'waiting') ??
    steps.find((s) => s.status !== 'done' && s.status !== 'parked') ??
    null;
  return {
    present: true,
    gap: null,
    current_step: current
      ? {
          id: current.id,
          name: current.name,
          status: current.status,
          done_when: current.done_when,
          waiting_on: current.waiting_on,
        }
      : null,
    steps_done: steps.filter((s) => s.status === 'done').length,
    steps_total: steps.length,
    invented_steps: false,
  };
}

function projectQuestionAnswers(ctx) {
  const { strip, face, position, anchor, journal, seenHit, dispatchTable } = ctx;
  const answers = [];

  // Q1 — position: Face north star + Strip phase/active_effort + Roadmap step
  const northStar = face?.narrative?.north_star ?? null;
  if (nonEmpty(northStar) || nonEmpty(strip?.phase) || nonEmpty(strip?.active_effort) || position.present) {
    const prov = [];
    if (nonEmpty(northStar)) prov.push({ source: FACE_FILE_NAME, field: 'north_star' });
    if (nonEmpty(strip?.phase)) prov.push({ source: STRIP_FILE_NAME, field: 'phase' });
    if (nonEmpty(strip?.active_effort)) prov.push({ source: STRIP_FILE_NAME, field: 'active_effort' });
    if (position.present) prov.push({ source: 'roadmap.json', field: 'roadmap_projection' });
    answers.push(
      answered(
        'Q1',
        {
          toward: nonEmpty(northStar) ? northStar.trim() : UNKNOWN_ANSWER,
          phase: strip?.phase ?? null,
          active_effort: strip?.active_effort ?? null,
          position,
        },
        prov,
        { roadmap_aware: true },
      ),
    );
  } else {
    answers.push(unknownAnswer('Q1', { roadmap_aware: true, position }));
  }

  // Q2 — delta since last seen (anchored by the seen receipt)
  if (strip) {
    const delta = deltaSinceSeen(strip, seenHit, { journal });
    const prov = [
      { source: STRIP_FILE_NAME, field: 'instruments' },
      { source: STRIP_FILE_NAME, field: 'receipts' },
      ...delta.journal.map((j) => ({ source: j.file })),
    ];
    answers.push(answered('Q2', delta, prov, { delta_anchor: 'seen_receipt' }));
  } else {
    answers.push(unknownAnswer('Q2', { delta_anchor: 'seen_receipt' }));
  }

  // Q3 — waiting on the human
  const humanWait = strip?.human_wait ?? face?.narrative?.human_wait ?? null;
  if (nonEmpty(humanWait)) {
    const fromStrip = nonEmpty(strip?.human_wait);
    answers.push(
      answered('Q3', { human_wait: humanWait.trim() }, [
        fromStrip
          ? { source: STRIP_FILE_NAME, field: 'human_wait' }
          : { source: FACE_FILE_NAME, field: 'human_wait' },
      ]),
    );
  } else {
    answers.push(unknownAnswer('Q3'));
  }

  // Q4 — blocked / uncertain and why
  if (strip) {
    const flags = Array.isArray(strip.uncertainty_flags) ? strip.uncertainty_flags : [];
    answers.push(
      answered(
        'Q4',
        {
          uncertainty_flags: [...flags],
          negative_heartbeat: strip.negative_heartbeat ?? null,
          capacity: strip.capacity === 'known' ? 'known' : 'unknown',
        },
        [
          { source: STRIP_FILE_NAME, field: 'uncertainty_flags' },
          { source: STRIP_FILE_NAME, field: 'negative_heartbeat' },
          { source: STRIP_FILE_NAME, field: 'capacity' },
        ],
      ),
    );
  } else {
    answers.push(unknownAnswer('Q4'));
  }

  // Q5 — next-move cost: tool_depth_cell + capacity + dispatch table (table only, no model)
  if (strip) {
    const suggested = suggestDepthFromStrip(strip, { table: dispatchTable });
    const capacity = strip.capacity === 'known' ? 'known' : 'unknown';
    answers.push(
      answered(
        'Q5',
        {
          tool_depth_cell: strip.tool_depth_cell ?? null,
          table_outcome: suggested.outcome,
          tool_depth_why: suggested.tool_depth_why,
          capacity,
          // Capacity honesty law: no fake % meters, no silent affordability
          affordable: capacity === 'known' ? suggested.outcome !== 'refuse' : 'unknown',
        },
        [
          { source: STRIP_FILE_NAME, field: 'tool_depth_cell' },
          { source: STRIP_FILE_NAME, field: 'capacity' },
          { source: 'fixtures/dispatch-table-seed.json', field: 'cells' },
        ],
      ),
    );
  } else {
    answers.push(unknownAnswer('Q5'));
  }

  // Q6 — next best move and why
  if (nonEmpty(strip?.next_recommended)) {
    answers.push(
      answered(
        'Q6',
        {
          next_recommended: strip.next_recommended,
          why_next: strip.why_next ?? null,
        },
        [
          { source: STRIP_FILE_NAME, field: 'next_recommended' },
          { source: STRIP_FILE_NAME, field: 'why_next' },
        ],
      ),
    );
  } else {
    answers.push(unknownAnswer('Q6'));
  }

  // Q7 — commissioned-work conclusions from the read-only Anchor store
  const concluded = anchorConclusions(anchor);
  if (concluded.grounded) {
    answers.push(
      answered(
        'Q7',
        { conclusions: concluded.conclusions },
        concluded.conclusions.map((c) => c.provenance),
        { store: 'anchor_read_only' },
      ),
    );
  } else {
    answers.push(
      unknownAnswer('Q7', {
        store: 'anchor_read_only',
        store_present: anchor?.present === true,
        reason:
          anchor?.present === true
            ? 'no_grounded_claims_in_store'
            : (anchor?.reason ?? 'store_missing'),
      }),
    );
  }

  // Q8 — parked-and-now-relevant: grasscatch receipts whose park reason
  // references current phase/effort (string-match MVP → heuristic_match stamp)
  if (strip) {
    const receipts = Array.isArray(strip.receipts) ? strip.receipts : [];
    const needles = [strip.phase, strip.active_effort]
      .filter(nonEmpty)
      .map((s) => s.trim().toLowerCase());
    const matches = [];
    receipts.forEach((r, i) => {
      if (!r || (r.kind !== 'grasscatch' && r.kind !== 'soft-vet')) return;
      const hay = `${r.grasscatch_why ?? ''} ${r.why ?? ''} ${r.deferred ?? ''}`.toLowerCase();
      if (needles.some((n) => n && hay.includes(n))) {
        matches.push({
          deferred: r.deferred ?? r.what_deferred ?? null,
          why: r.grasscatch_why ?? r.why ?? null,
          heuristic_match: true,
          provenance: { source: STRIP_FILE_NAME, field: `receipts[${i}]` },
        });
      }
    });
    if (matches.length) {
      answers.push(
        answered('Q8', { parked_relevant: matches }, matches.map((m) => m.provenance), {
          heuristic_match: true,
        }),
      );
    } else {
      answers.push(unknownAnswer('Q8', { heuristic_match: true }));
    }
  } else {
    answers.push(unknownAnswer('Q8'));
  }

  // Q9 — likely to bite next: RECORDED foresight only, never fresh speculation
  {
    const recorded = [];
    const prov = [];
    const flags = Array.isArray(strip?.uncertainty_flags) ? strip.uncertainty_flags : [];
    if (flags.length) {
      recorded.push({ kind: 'uncertainty_flags', items: [...flags] });
      prov.push({ source: STRIP_FILE_NAME, field: 'uncertainty_flags' });
    }
    if (nonEmpty(strip?.negative_heartbeat?.why)) {
      recorded.push({
        kind: 'negative_heartbeat',
        items: [strip.negative_heartbeat.why],
      });
      prov.push({ source: STRIP_FILE_NAME, field: 'negative_heartbeat.why' });
    }
    const frictionJournal = (journal?.entries ?? []).filter((j) =>
      j.name.toLowerCase().includes('friction'),
    );
    if (frictionJournal.length) {
      recorded.push({
        kind: 'journal_friction_patterns',
        items: frictionJournal.map((j) => j.file),
      });
      prov.push(...frictionJournal.map((j) => ({ source: j.file })));
    }
    if (recorded.length) {
      answers.push(
        answered('Q9', { recorded_foresight: recorded }, prov, {
          recorded_only: true,
          fresh_speculation: false,
        }),
      );
    } else {
      answers.push(
        unknownAnswer('Q9', { recorded_only: true, fresh_speculation: false }),
      );
    }
  }

  return answers;
}

function portfolioQuestionAnswers(ctx) {
  const { discovered, ranked } = ctx;
  const answers = [];
  const projections = (discovered?.strips ?? [])
    .map((hit) => hit.projection ?? toStripProjection(hit.strip, { project_path: hit.project_path }))
    .filter(Boolean);

  if (!projections.length) {
    answers.push(unknownAnswer('Q10'));
    answers.push(unknownAnswer('Q11', { heuristic_match: true }));
    answers.push(unknownAnswer('Q12'));
    return answers;
  }

  // Q10 — Decision Queue: one ranked list of everything waiting on the human
  const rankedList = ranked?.ranked ?? [];
  const queue = rankedList
    .filter((r) => nonEmpty(r.human_wait) && r.human_wait !== 'none')
    .map((r) => ({
      project_id: r.project_id ?? null,
      project_path: r.project_path ?? null,
      human_wait: r.human_wait,
      score: r.score,
    }));
  answers.push(
    answered('Q10', { decision_queue: queue, queue_length: queue.length }, [
      { source: STRIP_FILE_NAME, field: 'human_wait', scope: 'all_strips' },
    ]),
  );

  // Q11 — shared blockers across projects (string-match MVP → heuristic_match)
  const tokenProjects = new Map();
  for (const p of projections) {
    const tokens = new Set();
    if (nonEmpty(p.human_wait) && p.human_wait !== 'none') {
      tokens.add(p.human_wait.trim().toLowerCase());
    }
    for (const f of p.uncertainty_flags ?? []) {
      if (nonEmpty(f)) tokens.add(f.trim().toLowerCase());
    }
    for (const t of tokens) {
      if (!tokenProjects.has(t)) tokenProjects.set(t, []);
      tokenProjects.get(t).push(p.project_id ?? p.project_path ?? null);
    }
  }
  const shared = [...tokenProjects.entries()]
    .filter(([, projs]) => projs.length >= 2)
    .map(([value, projs]) => ({
      blocker: value,
      projects: projs,
      heuristic_match: true,
    }));
  answers.push(
    answered(
      'Q11',
      { shared_blockers: shared, heuristic_match: true },
      [
        { source: STRIP_FILE_NAME, field: 'human_wait', scope: 'all_strips' },
        { source: STRIP_FILE_NAME, field: 'uncertainty_flags', scope: 'all_strips' },
      ],
      { heuristic_match: true },
    ),
  );

  // Q12 — starving: anti_starvation_age_days
  const starving = projections
    .filter((p) => (p.anti_starvation_age_days ?? 0) > 0)
    .sort((a, b) => (b.anti_starvation_age_days ?? 0) - (a.anti_starvation_age_days ?? 0))
    .map((p) => ({
      project_id: p.project_id ?? null,
      project_path: p.project_path ?? null,
      anti_starvation_age_days: p.anti_starvation_age_days,
    }));
  answers.push(
    answered('Q12', { starving }, [
      { source: STRIP_FILE_NAME, field: 'anti_starvation_age_days', scope: 'all_strips' },
    ]),
  );

  return answers;
}

/**
 * Assemble the Decision Packet — Phase A, fully deterministic.
 * ZERO model / commission calls on this path: any spy passed via
 * opts.model / opts.commission is returned untouched (never invoked).
 * @param {{
 *   project?: string|null, cwd?: string|null, surfaces?: object,
 *   roadmap?: object|null, roots?: string[], altitude?: string,
 *   anchor_root?: string|null, anchor_knowledge?: object,
 *   journal?: object, env?: object, envValue?: string|null,
 *   as_of?: string, table?: object,
 * }} [opts]
 * @returns {object} packet
 */
export function assembleBriefPacket(opts = {}) {
  const roots = Array.isArray(opts.roots) ? opts.roots : [];
  const altitude = BRIEF_ALTITUDES.includes(opts.altitude)
    ? opts.altitude
    : roots.length > 0
      ? 'portfolio'
      : 'project';
  const as_of = opts.as_of ?? todayIso();

  // Phase A guard — nothing in this function may increment these.
  const phase_a = {
    complete: true,
    deterministic: true,
    model_calls: 0,
    commission_calls: 0,
    zero_model_calls: true,
  };

  let answers = [];
  let goal_card;
  let position = null;
  let project_path = null;
  let sources = null;

  if (altitude === 'portfolio') {
    const discovered = discoverStrips({
      roots: roots.length ? roots : undefined,
      envValue: opts.envValue ?? null,
      env: opts.env,
    });
    const ranked = rankPortfolioStripFirst(discovered.strips, {
      top_k: opts.top_k ?? 3,
    });
    answers = portfolioQuestionAnswers({ discovered, ranked });

    const top = ranked.ranked[0] ?? null;
    goal_card = top
      ? {
          altitude: 'portfolio',
          unknown: false,
          project_id: top.project_id ?? null,
          active_effort: top.active_effort ?? null,
          north_star: top.active_effort ?? UNKNOWN_ANSWER,
          provenance: [{ source: STRIP_FILE_NAME, field: 'active_effort' }],
        }
      : {
          altitude: 'portfolio',
          unknown: true,
          north_star: UNKNOWN_ANSWER,
          provenance: [],
        };
    sources = {
      discovery_count: discovered.strips.length,
      discovery_empty: discovered.empty,
    };
  } else {
    project_path = resolveProjectPath({ project: opts.project, cwd: opts.cwd });
    const surfaces = opts.surfaces ?? loadProjectSurfaces(project_path);
    const strip = surfaces?.strip ?? null;
    const face = surfaces?.face ?? null;

    // Roadmap-aware position (engine truth; prose never invents steps)
    let roadmapResult;
    const roadmapLoaded =
      opts.roadmap !== undefined
        ? { ok: true, exists: opts.roadmap != null, roadmap: opts.roadmap }
        : loadProjectRoadmap(project_path);
    if (roadmapLoaded.ok && roadmapLoaded.exists) {
      const validated = validateRoadmap(roadmapLoaded.roadmap, {
        allow_unevented_steps: true,
      });
      roadmapResult = validated.ok
        ? { present: true, valid: true, projection: validated.projection, gap: null }
        : {
            present: true,
            valid: false,
            projection: [],
            gap: 'roadmap_silent_rewrite',
          };
    } else {
      roadmapResult = {
        present: false,
        valid: null,
        projection: [],
        gap: face ? 'face_prose_only' : 'no_roadmap',
      };
    }
    position = roadmapPosition(roadmapResult);

    const anchor =
      opts.anchor_knowledge !== undefined
        ? opts.anchor_knowledge
        : readAnchorProjectKnowledge({
            project_path,
            project_key: opts.project_key ?? null,
            anchor_root: opts.anchor_root ?? null,
            env: opts.env,
          });

    const journal = opts.journal ?? listJournalEntries(project_path);
    const seenHit = findLastSeen(strip);
    const dispatchTable = opts.table ?? loadDispatchTable();

    answers = projectQuestionAnswers({
      strip,
      face,
      position,
      anchor,
      journal,
      seenHit,
      dispatchTable,
    });

    // Goal card — MANDATORY in every packet ("remember the goal")
    const northStar = face?.narrative?.north_star ?? null;
    goal_card = nonEmpty(northStar)
      ? {
          altitude: 'project',
          unknown: false,
          north_star: northStar.trim(),
          provenance: [{ source: FACE_FILE_NAME, field: 'north_star' }],
        }
      : {
          altitude: 'project',
          unknown: true,
          north_star: UNKNOWN_ANSWER,
          provenance: [],
        };

    const roadmapForAnchor =
      roadmapLoaded.ok && roadmapLoaded.exists ? roadmapLoaded.roadmap : null;
    const roadmapAnchor = lastRoadmapEventAnchor(roadmapForAnchor);
    sources = {
      strip_present: Boolean(strip),
      strip_as_of: strip?.as_of ?? null,
      instruments_length: Array.isArray(strip?.instruments)
        ? strip.instruments.length
        : 0,
      receipts_length: Array.isArray(strip?.receipts) ? strip.receipts.length : 0,
      face_present: Boolean(face),
      roadmap_present: roadmapResult.present,
      // Count retained for display; A3 staleness uses seq/hash + face version.
      roadmap_events: roadmapAnchor.count,
      last_roadmap_event_seq: roadmapAnchor.seq,
      last_roadmap_event_hash: roadmapAnchor.hash,
      face_version: faceVersionOf(face),
      journal_present: journal.present,
      journal_count: journal.entries.length,
      anchor_store_present: anchor?.present === true,
    };
  }

  const answerable = answers.filter((a) => !a.unknown).length;
  const total = answers.length;

  return {
    schema: BRIEF_SCHEMA_ID,
    spelling: SPELLING,
    altitude,
    as_of,
    project_path,
    goal_card,
    position,
    answers,
    coverage: {
      answerable,
      total,
      stamp: `answerable ${answerable}/${total} from local evidence`,
    },
    phase_a,
    phase_b: { requested: false, ran: false },
    recommendation: null,
    sources,
    honest_unknowns: answers.filter((a) => a.unknown).map((a) => a.id),
    invented: false,
  };
}

// ---------------------------------------------------------------------------
// Phase B — optional recommend (never required for green)
// ---------------------------------------------------------------------------

/**
 * Phase B: optional model-backed recommendation on top of a complete Phase A
 * packet. Model unavailable (or no recommend fn, or it throws) → Phase A
 * stands complete and recommendation is the honest 'unknown'.
 * @param {object} packet Phase A packet
 * @param {{ model_available?: boolean, recommend?: (packet: object) => any }} [opts]
 */
export function briefPhaseB(packet, opts = {}) {
  const base = { ...packet };
  const available = opts.model_available === true && typeof opts.recommend === 'function';
  if (!available) {
    return {
      ...base,
      phase_b: {
        requested: true,
        ran: false,
        model_used: false,
        reason: 'model_unavailable',
      },
      recommendation: 'unknown',
    };
  }
  try {
    const recommendation = opts.recommend(packet);
    return {
      ...base,
      phase_b: { requested: true, ran: true, model_used: true, reason: null },
      recommendation: recommendation ?? 'unknown',
    };
  } catch (e) {
    return {
      ...base,
      phase_b: {
        requested: true,
        ran: false,
        model_used: false,
        reason: 'model_failed',
        message: String(e?.message ?? e),
      },
      recommendation: 'unknown',
    };
  }
}

// ---------------------------------------------------------------------------
// Precompute cache — declared projection, zero write authority
// ---------------------------------------------------------------------------

/**
 * Wrap a packet as the declared cache projection (annex A6 discipline).
 * @param {object} packet
 * @param {{ as_of?: string }} [opts]
 */
export function buildBriefCacheProjection(packet, opts = {}) {
  return {
    schema: BRIEF_CACHE_SCHEMA_ID,
    projection: true,
    write_authority: 'none',
    regenerable: true,
    read_back_as_truth: false,
    as_of: opts.as_of ?? packet?.as_of ?? todayIso(),
    precomputed_at: opts.precomputed_at ?? nowIso(),
    snapshot: {
      strip_as_of: packet?.sources?.strip_as_of ?? null,
      instruments_length: packet?.sources?.instruments_length ?? 0,
      receipts_length: packet?.sources?.receipts_length ?? 0,
      // A3 — content-anchored keys (counts alone miss healed-in-place mutations).
      last_roadmap_event_seq: packet?.sources?.last_roadmap_event_seq ?? null,
      last_roadmap_event_hash: packet?.sources?.last_roadmap_event_hash ?? null,
      face_version: packet?.sources?.face_version ?? null,
    },
    packet,
  };
}

/**
 * Persist the cache projection next to the project surfaces.
 * S11: uses writeFileAtomicSync (temp + fsync + rename) — never bare writeFileSync.
 * Corrupt/torn reads stay "absent" via loadBriefCache (T-DUR-S11).
 * @param {string} projectPath
 * @param {object} packet
 * @param {{ as_of?: string }} [opts]
 */
export function writeBriefCache(projectPath, packet, opts = {}) {
  const root = path.resolve(projectPath);
  const cachePath = path.join(root, BRIEF_CACHE_FILE_NAME);
  const cache = buildBriefCacheProjection(packet, opts);
  fs.mkdirSync(root, { recursive: true });
  writeFileAtomicSync(cachePath, `${JSON.stringify(cache, null, 2)}\n`);
  return { ok: true, cache_path: cachePath, cache };
}

/**
 * Load the cache projection; absent/corrupt → { exists: false } (regenerable).
 * @param {string} projectPath
 */
export function loadBriefCache(projectPath) {
  const cachePath = path.join(path.resolve(projectPath), BRIEF_CACHE_FILE_NAME);
  if (!fs.existsSync(cachePath)) {
    return { exists: false, cache: null, cache_path: cachePath };
  }
  try {
    const cache = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
    if (!cache || cache.schema !== BRIEF_CACHE_SCHEMA_ID) {
      return { exists: false, cache: null, cache_path: cachePath };
    }
    return { exists: true, cache, cache_path: cachePath };
  } catch {
    return { exists: false, cache: null, cache_path: cachePath };
  }
}

/**
 * Staleness: cache snapshot vs live Strip clocks/lengths PLUS A3 content anchors
 * (last roadmap event seq/hash + Face version). Counts alone are weak: a healed
 * or replaced-in-place roadmap can preserve event count while changing content.
 *
 * @param {object} cache
 * @param {object|null} live bare Strip (legacy) OR
 *   `{ strip?, face?, roadmap?, surfaces? }` with content anchors
 */
export function briefCacheStale(cache, live = null) {
  let strip = null;
  let face = null;
  let roadmap = null;
  /** When false, roadmap seq/hash are not part of the stale predicate. */
  let compareRoadmap = false;

  if (live && typeof live === 'object') {
    const wrapped =
      Object.prototype.hasOwnProperty.call(live, 'strip') ||
      Object.prototype.hasOwnProperty.call(live, 'face') ||
      Object.prototype.hasOwnProperty.call(live, 'roadmap') ||
      Object.prototype.hasOwnProperty.call(live, 'surfaces');
    if (wrapped) {
      strip = live.strip ?? live.surfaces?.strip ?? null;
      face = live.face ?? live.surfaces?.face ?? null;
      // Only compare roadmap anchors when the caller supplied the key.
      // Omission ≠ "empty roadmap": inject/surfaces-only call sites (and
      // projects with no roadmap file) must not false-stale a content-anchored
      // cache. Explicit `roadmap: null` still compares (null anchors).
      if (Object.prototype.hasOwnProperty.call(live, 'roadmap')) {
        roadmap = live.roadmap ?? null;
        compareRoadmap = true;
      }
    } else {
      // Legacy call sites pass the bare Strip object.
      strip = live;
    }
  }

  const snap = cache?.snapshot ?? {};
  const liveAsOf = strip?.as_of ?? null;
  const liveInst = Array.isArray(strip?.instruments) ? strip.instruments.length : 0;
  const liveRec = Array.isArray(strip?.receipts) ? strip.receipts.length : 0;
  const liveRoadmap = lastRoadmapEventAnchor(roadmap);
  const liveFaceVer = faceVersionOf(face);

  const stale =
    (snap.strip_as_of ?? null) !== liveAsOf ||
    (snap.instruments_length ?? 0) !== liveInst ||
    (snap.receipts_length ?? 0) !== liveRec ||
    (compareRoadmap &&
      (snap.last_roadmap_event_seq ?? null) !== liveRoadmap.seq) ||
    (compareRoadmap &&
      (snap.last_roadmap_event_hash ?? null) !== liveRoadmap.hash) ||
    (snap.face_version ?? null) !== liveFaceVer;

  return {
    stale,
    cache_as_of: cache?.as_of ?? null,
    cache_strip_as_of: snap.strip_as_of ?? null,
    live_strip_as_of: liveAsOf,
    cache_last_roadmap_event_seq: snap.last_roadmap_event_seq ?? null,
    live_last_roadmap_event_seq: liveRoadmap.seq,
    cache_last_roadmap_event_hash: snap.last_roadmap_event_hash ?? null,
    live_last_roadmap_event_hash: liveRoadmap.hash,
    cache_face_version: snap.face_version ?? null,
    live_face_version: liveFaceVer,
    roadmap_compared: compareRoadmap,
  };
}

/**
 * Precompute hook (update/heartbeat time): assemble Phase A and cache it so
 * "Bring it up" opens with zero further gathering.
 * @param {string} projectPath
 * @param {object} [opts] assembleBriefPacket opts
 */
export function precomputeBriefCache(projectPath, opts = {}) {
  const packet = assembleBriefPacket({ ...opts, project: projectPath });
  const written = writeBriefCache(projectPath, packet, { as_of: packet.as_of });
  return {
    ok: true,
    projection: true,
    write_authority: 'none',
    cache_path: written.cache_path,
    cache: written.cache,
    packet,
  };
}

// ---------------------------------------------------------------------------
// verb body
// ---------------------------------------------------------------------------

/**
 * brief — closed verb. Deterministic Phase A packet (offline, zero model
 * calls); optional Phase B recommend; optional cached serve; optional
 * mark-seen (appends the seen receipt AFTER assembling, so Q2 stays anchored
 * to the PREVIOUS seen).
 * @param {object} opts parsed verb options + test injectors
 */
export function verbBrief(opts = {}) {
  const roots = Array.isArray(opts.roots) ? opts.roots : [];
  const altitude = BRIEF_ALTITUDES.includes(opts.altitude)
    ? opts.altitude
    : roots.length > 0
      ? 'portfolio'
      : 'project';

  const project_path =
    altitude === 'project'
      ? resolveProjectPath({ project: opts.project, cwd: opts.cwd })
      : null;

  // Cached serve: Seal panel opens instantly on the cached packet + staleness
  // stamp + refresh affordance. The cache is a projection, never truth.
  if (altitude === 'project' && opts.cached && !opts.refresh) {
    const loaded = loadBriefCache(project_path);
    if (loaded.exists) {
      const surfaces = opts.surfaces ?? loadProjectSurfaces(project_path);
      const roadmapLoaded =
        opts.roadmap !== undefined
          ? { ok: true, exists: opts.roadmap != null, roadmap: opts.roadmap }
          : loadProjectRoadmap(project_path);
      const roadmap =
        roadmapLoaded.ok && roadmapLoaded.exists ? roadmapLoaded.roadmap : null;
      const staleness = briefCacheStale(loaded.cache, {
        strip: surfaces?.strip ?? null,
        face: surfaces?.face ?? null,
        roadmap,
      });
      return {
        ok: true,
        spelling: SPELLING,
        verb: 'brief',
        primary: 'brief',
        altitude,
        project_path,
        served_from: 'cache',
        cache_projection: true,
        cache_write_authority: 'none',
        as_of: loaded.cache.as_of,
        ...staleness,
        refresh_affordance: 'brief --refresh',
        further_gathering: false,
        packet: loaded.cache.packet,
        goal_card: loaded.cache.packet?.goal_card ?? null,
        coverage: loaded.cache.packet?.coverage ?? null,
        message: staleness.stale
          ? `Cached Decision Packet (STALE as_of ${loaded.cache.as_of}) — refresh to recompute.`
          : `Cached Decision Packet (as_of ${loaded.cache.as_of}).`,
      };
    }
    // No cache → fall through to live assembly (still zero further gathering
    // for the caller: one deterministic pass).
  }

  // Phase A — deterministic assembly (zero model / commission calls).
  let packet = assembleBriefPacket({
    ...opts,
    roots,
    altitude,
    project: opts.project,
    cwd: opts.cwd,
  });

  // Phase B — only when explicitly requested; never required for green.
  if (opts.phase_b) {
    packet = briefPhaseB(packet, {
      model_available: opts.model_available === true,
      recommend: opts.recommend,
    });
  }

  // mark-seen: append the seen receipt after viewing (append-only law).
  let seen_receipt = null;
  let strip_after_seen = null;
  const written = { strip: false, cache: false };
  if (opts.mark_seen) {
    // Portfolio-altitude seen stamps the named project's Strip (--project).
    const seenProjectPath =
      project_path ??
      (opts.project ? resolveProjectPath({ project: opts.project, cwd: opts.cwd }) : null);
    const surfaces =
      opts.surfaces ?? (seenProjectPath ? loadProjectSurfaces(seenProjectPath) : null);
    const targetStrip = surfaces?.strip ?? null;
    if (!targetStrip) {
      return {
        ok: false,
        error: 'seen_requires_strip',
        spelling: SPELLING,
        verb: 'brief',
        primary: 'brief',
        altitude,
        project_path,
        message:
          'mark-seen appends a seen receipt to the project Strip; no Strip found. For portfolio altitude pass --project for the Strip to stamp.',
      };
    }
    const journal =
      opts.journal ??
      (seenProjectPath ? listJournalEntries(seenProjectPath) : { entries: [] });
    const appended = appendSeenReceipt(targetStrip, {
      who: opts.who,
      when: opts.when ?? undefined,
      altitude,
      journal_seen: journal.entries.length,
    });
    if (!appended.ok) {
      return {
        ...appended,
        verb: 'brief',
        primary: 'brief',
        altitude,
        project_path,
      };
    }
    seen_receipt = appended.receipt;
    strip_after_seen = appended.strip;
    const persist = opts.persist !== false && !opts.dry_run && !opts.surfaces;
    if (persist && surfaces?.strip_source === 'strip.json') {
      const stripPath =
        surfaces.strip_path ?? path.join(seenProjectPath, STRIP_FILE_NAME);
      writeFileAtomicSync(
        stripPath,
        `${JSON.stringify(strip_after_seen, null, 2)}\n`,
      );
      written.strip = true;
    }
  }

  // Optional precompute: write the cache projection for instant next open.
  if (altitude === 'project' && opts.precompute && opts.persist !== false && !opts.dry_run) {
    const cached = writeBriefCache(project_path, packet, { as_of: packet.as_of });
    written.cache = Boolean(cached.ok);
  }

  return {
    ok: true,
    spelling: SPELLING,
    verb: 'brief',
    primary: 'brief',
    altitude,
    project_path,
    served_from: 'live',
    stale: false,
    packet,
    goal_card: packet.goal_card,
    coverage: packet.coverage,
    phase_a: packet.phase_a,
    phase_b: packet.phase_b,
    recommendation: packet.recommendation,
    seen_receipt,
    strip: strip_after_seen,
    persisted: written,
    dry_run: Boolean(opts.dry_run) || opts.persist === false,
    message: `Decision Packet assembled (Phase A deterministic; ${packet.coverage.stamp}).`,
  };
}
