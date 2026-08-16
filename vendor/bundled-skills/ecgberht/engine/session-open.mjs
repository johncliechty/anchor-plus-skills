/**
 * Wave 15 — Rehydration + the ONE boot/open-project pipeline (Master-Plan P7).
 *
 * THE ONLY open-project path:
 *   openProjectPipeline() → reconcile → ingest → publish → compose
 *
 * Continuity law: reconcile commits observed reality to the ledger FIRST;
 * the composer then reads ONLY the post-reconcile ledger. That is how
 * "derived ENTIRELY from the ledger" and "dead run NAMED" are simultaneously
 * true (closes residual finding cold-ledger-observed-only-race).
 *
 * Kill-between-stages: each stage is idempotent (client_event_id). A process
 * killed between adjacent stages re-runs cleanly with no duplicate events and
 * the composer never runs against a pre-reconcile ledger.
 *
 * HEAL-BEFORE-BRIEF: validateRoadmap / healRoadmap before compose; healed
 * write goes through writeRoadmapThroughSpine.
 * SEEN-RECEIPT: appendSeenReceipt after assembly so deltaSinceSeen stays
 * count-anchored (skew-proof).
 * First-message composer: ZERO-MODEL deterministic render, golden-pinnable.
 * NL polish is a SEPARATE envelope-debited layer, absent by default at cold start.
 *
 * Stdlib only. No host-absolute paths in shipped strings.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { writeFileAtomicSync } from './durable-write.mjs';
import {
  reconcileSessionStatus,
  reconcileAfterRestart,
} from './status-reconciler.mjs';
import {
  ingestHandback,
  nameMissingHandback,
  buildLedgerView,
} from './handback-ingest.mjs';
import { isIngestable } from './handback-contract.mjs';
import { RUN_LIVENESS } from './lease-law.mjs';
import {
  loadProjectRoadmap,
  validateRoadmap,
  healRoadmap,
  buildRoadmapProjection,
} from './roadmap.mjs';
import {
  appendRoadmapEventThroughSpine,
  writeRoadmapThroughSpine,
} from './ledger-spine.mjs';
import {
  assembleBriefPacket,
  appendSeenReceipt,
  UNKNOWN_ANSWER,
  BRIEF_QUESTIONS,
} from './brief.mjs';
import {
  loadProjectSurfaces,
  STRIP_FILE_NAME,
} from './face-strip.mjs';
import { writeStripThroughSpine } from './ledger-spine.mjs';
import { listDossiers } from './commission-dossier.mjs';
import {
  deriveAttention,
  publishAttention,
  ATTENTION_CALL_SITES,
} from './attention.mjs';
import {
  resolveNoLiveEnvelopePath,
  QUEUE_WITHOUT_ENVELOPE_KIND,
} from './session-envelope.mjs';
import {
  reconcileInSessionOrphans,
  listInsessionRunsForPipeline,
} from './exec-insession.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(ENGINE_DIR, '..');

// ── Pipeline identity ──────────────────────────────────────────────────────

/** Named stages in proven order. */
export const PIPELINE_STAGES = Object.freeze([
  'reconcile',
  'ingest',
  'publish',
  'compose',
]);

/** Module path token (relative) — the ONLY open-project path. */
export const OPEN_PROJECT_PIPELINE_MODULE = 'engine/session-open.mjs';

/** Schema of the pipeline result / checkpoint. */
export const OPEN_PROJECT_PIPELINE_SCHEMA = 'ecgberht-open-project-pipeline-v0';

/** First-message schema (zero-model deterministic render). */
export const FIRST_MESSAGE_SCHEMA = 'ecgberht-first-message-v0';

/** Durable checkpoint relative path (kill-between-stages resume). */
export const PIPELINE_CHECKPOINT_REL = path.join(
  '.ecgberht',
  'open-project-pipeline.json',
);

/** Golden first-message fixture (relative to skill root). */
export const GOLDEN_FIRST_MESSAGE_REL = path.join(
  'fixtures',
  'w15-golden',
  'first-message.golden.txt',
);

// ── Failure-state table (wake-up brief surface — Master-Plan P7) ────────────

export const BRIEF_CODE = Object.freeze({
  BRIEF_NO_CAMPAIGN: 'BRIEF_NO_CAMPAIGN',
  BRIEF_ASSEMBLY_FAILED: 'BRIEF_ASSEMBLY_FAILED',
  BRIEF_ROADMAP_HEALED: 'BRIEF_ROADMAP_HEALED',
  BRIEF_LEDGER_UNREADABLE: 'BRIEF_LEDGER_UNREADABLE',
  BRIEF_ALL_QUIET: 'BRIEF_ALL_QUIET',
  BRIEF_RUN_UNKNOWN: 'BRIEF_RUN_UNKNOWN',
});

export const BRIEF_TEXT = Object.freeze({
  [BRIEF_CODE.BRIEF_NO_CAMPAIGN]:
    'No campaign recorded for this project yet — describe it to begin.',
  [BRIEF_CODE.BRIEF_ASSEMBLY_FAILED]:
    'Could not assemble the wake-up brief — nothing partial is shown; retry.',
  [BRIEF_CODE.BRIEF_ROADMAP_HEALED]:
    'Roadmap had <n> invalid events — healed and noted; brief reflects the healed state.',
  [BRIEF_CODE.BRIEF_LEDGER_UNREADABLE]:
    'Campaign ledger unreadable — brief refused rather than invented.',
  [BRIEF_CODE.BRIEF_ALL_QUIET]:
    'Campaign at stage <s>; nothing running, nothing waiting on you.',
  [BRIEF_CODE.BRIEF_RUN_UNKNOWN]:
    'Run <id>: liveness UNKNOWN — reported as unknown, not as running.',
});

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function briefFailure(code, extra = {}) {
  let text = BRIEF_TEXT[code] ?? BRIEF_TEXT[BRIEF_CODE.BRIEF_ASSEMBLY_FAILED];
  if (code === BRIEF_CODE.BRIEF_ROADMAP_HEALED && extra.n != null) {
    text = text.replace('<n>', String(extra.n));
  }
  if (code === BRIEF_CODE.BRIEF_ALL_QUIET && extra.s != null) {
    text = text.replace('<s>', String(extra.s));
  }
  if (code === BRIEF_CODE.BRIEF_RUN_UNKNOWN && extra.id != null) {
    text = text.replace('<id>', String(extra.id));
  }
  return {
    ok: false,
    code,
    status_code: code,
    text,
    message: text,
    user_text: text,
    brief_surface: true,
    ...extra,
  };
}

/**
 * Full failure-state table (honest unknown ≠ empty).
 * @returns {ReadonlyArray<{state: string, status_code: string, user_text: string}>}
 */
export function briefFailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'dependency-missing (no ledger yet)',
      status_code: BRIEF_CODE.BRIEF_NO_CAMPAIGN,
      user_text: BRIEF_TEXT[BRIEF_CODE.BRIEF_NO_CAMPAIGN],
    }),
    Object.freeze({
      state: 'dependency-slow-or-killed (assembly interrupted)',
      status_code: BRIEF_CODE.BRIEF_ASSEMBLY_FAILED,
      user_text: BRIEF_TEXT[BRIEF_CODE.BRIEF_ASSEMBLY_FAILED],
    }),
    Object.freeze({
      state: 'dependency-returns-garbage (torn roadmap)',
      status_code: BRIEF_CODE.BRIEF_ROADMAP_HEALED,
      user_text: BRIEF_TEXT[BRIEF_CODE.BRIEF_ROADMAP_HEALED],
    }),
    Object.freeze({
      state: 'backing-store-unreadable',
      status_code: BRIEF_CODE.BRIEF_LEDGER_UNREADABLE,
      user_text: BRIEF_TEXT[BRIEF_CODE.BRIEF_LEDGER_UNREADABLE],
    }),
    Object.freeze({
      state: 'empty-but-valid (campaign quiet)',
      status_code: BRIEF_CODE.BRIEF_ALL_QUIET,
      user_text: BRIEF_TEXT[BRIEF_CODE.BRIEF_ALL_QUIET],
    }),
    Object.freeze({
      state: 'unknown (run liveness unresolvable)',
      status_code: BRIEF_CODE.BRIEF_RUN_UNKNOWN,
      user_text: BRIEF_TEXT[BRIEF_CODE.BRIEF_RUN_UNKNOWN],
    }),
  ]);
}

// ── Checkpoint (kill-between-stages) ───────────────────────────────────────

/**
 * @param {string} projectPath
 */
export function pipelineCheckpointPath(projectPath) {
  return path.join(path.resolve(projectPath), PIPELINE_CHECKPOINT_REL);
}

/**
 * @param {string} projectPath
 */
export function readPipelineCheckpoint(projectPath) {
  const p = pipelineCheckpointPath(projectPath);
  try {
    if (!fs.existsSync(p)) return { ok: true, exists: false, checkpoint: null };
    const raw = fs.readFileSync(p, 'utf8');
    return { ok: true, exists: true, checkpoint: JSON.parse(raw) };
  } catch (e) {
    return {
      ok: false,
      exists: true,
      checkpoint: null,
      error: 'checkpoint_unreadable',
      detail: String(e?.message ?? e),
    };
  }
}

/**
 * Persist the kill-between-stages checkpoint (atomic).
 * @param {string} projectPath
 * @param {object} checkpoint
 */
export function writePipelineCheckpoint(projectPath, checkpoint) {
  const p = pipelineCheckpointPath(projectPath);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  writeFileAtomicSync(p, `${JSON.stringify(checkpoint, null, 2)}\n`);
  return { ok: true, path: p };
}

/** @deprecated alias — prefer writePipelineCheckpoint */
export function writePipelineCheckpointAtomic(projectPath, checkpoint) {
  return writePipelineCheckpoint(projectPath, checkpoint);
}

// ── Stage 1: RECONCILE ─────────────────────────────────────────────────────

/**
 * Commit observed run/handback reality to the ledger via the Wave-13 reconciler
 * + named missing-handback events. Idempotent via client_event_id.
 *
 * @param {string} projectPath
 * @param {object} [opts]
 */
export function stageReconcile(projectPath, opts = {}) {
  const who = opts.who || 'open-project-pipeline';
  const at = opts.at || '1970-01-01T00:00:00.000Z';
  const seed = opts.seed ?? null;

  // Wave 20: orphan reconcile at next invocation (boot-reconcile at verb time).
  // Runs BEFORE Wave-13 lease sweep so adopted/named outcomes are durable first.
  let insession_orphan = null;
  if (opts.skip_insession_reconcile !== true) {
    insession_orphan = reconcileInSessionOrphans(projectPath, {
      who,
      at,
      seed,
      nowMono: opts.nowMono,
      probe: opts.probe,
      force_missing: opts.force_missing,
      handback_ttl_ms: opts.handback_ttl_ms,
    });
  }

  // Merge S14 ledger runs with any caller-supplied runs (caller wins on id clash).
  const fromLedger =
    opts.skip_insession_runs === true
      ? []
      : listInsessionRunsForPipeline(projectPath);
  const callerRuns = Array.isArray(opts.runs) ? opts.runs : [];
  const byId = new Map();
  for (const r of fromLedger) {
    if (r?.run_id) byId.set(String(r.run_id), r);
  }
  for (const r of callerRuns) {
    if (r?.run_id) byId.set(String(r.run_id), r);
    else byId.set(`anon:${byId.size}`, r);
  }
  const runs = [...byId.values()];

  const reconcile = reconcileSessionStatus(projectPath, {
    runs,
    who,
    at,
    seed,
    nowMono: opts.nowMono,
    probe: opts.probe,
    drainOutboxes: opts.drainOutboxes !== false,
  });

  const named_dead = [];
  const named_missing_handbacks = [];
  const spine_appends = [];

  for (const fact of reconcile.run_facts || []) {
    if (
      fact.run_state === RUN_LIVENESS.DEAD ||
      fact.cause === 'lease_expired' ||
      fact.cause === 'launch_intent_stranded'
    ) {
      named_dead.push({
        run_id: fact.run_id,
        step_id: fact.step_id,
        run_state: fact.run_state,
        cause: fact.cause,
      });
    }
  }

  // Overdue / never-arrived handbacks: named durable events (idempotent).
  for (const run of runs) {
    const expectHb =
      run.handback_expected === true ||
      run.missing_handback === true ||
      run.handback_never_arrived === true;
    if (!expectHb) continue;

    const worktree = run.worktree || null;
    const present = worktree ? isIngestable(worktree) : false;
    if (present) continue;

    const commission_id =
      run.commission_id || run.run_id || run.job_id || 'unknown';
    const named = nameMissingHandback({
      commission_id,
      confirmed_ago: run.confirmed_ago || run.confirmed_at || 'unknown duration',
    });
    named_missing_handbacks.push(named);

    if (!run.step_id) continue;

    const client_event_id = `missing-handback:${commission_id}`;
    // Prefer status_flip → waiting with receipt naming the missing handback.
    const flip = appendRoadmapEventThroughSpine(
      projectPath,
      {
        kind: 'status_flip',
        step_id: run.step_id,
        to: 'waiting',
        at,
        client_event_id,
        run_id: run.run_id ?? null,
        receipt: {
          who,
          when: at,
          why: `HANDBACK_NEVER_ARRIVED commission=${commission_id} named, not absorbed`,
          status_code: named.status_code,
          cause: 'handback_never_arrived',
        },
      },
      { skip_index: true, seed: seed ?? undefined, at },
    );
    spine_appends.push({
      kind: 'missing_handback',
      client_event_id,
      ok: flip.ok === true,
      idempotent: flip.idempotent === true,
      seq: flip.seq ?? null,
      error: flip.ok ? null : flip.error ?? flip.message,
    });
  }

  // Fold Wave-20 orphan outcomes into named_dead / named_missing
  if (insession_orphan && Array.isArray(insession_orphan.outcomes)) {
    for (const o of insession_orphan.outcomes) {
      if (o.kind === 'named_dead') {
        named_dead.push({
          run_id: o.run_id,
          step_id: null,
          run_state: RUN_LIVENESS.DEAD,
          cause: o.cause || 'process_died',
          status_code: o.status_code,
          source: 'insession',
        });
      }
      if (o.kind === 'named_missing_handback') {
        named_missing_handbacks.push({
          commission_id: o.run_id,
          status_code: o.status_code,
          user_text: o.user_text,
          source: 'insession',
        });
      }
    }
  }

  return {
    ok: true,
    stage: 'reconcile',
    reconcile,
    named_dead,
    named_missing_handbacks,
    spine_appends,
    insession_orphan,
    composer_peeks_live_pids: false,
    ledger_committed: true,
  };
}

// ── Stage 2: INGEST ────────────────────────────────────────────────────────

/**
 * Adopt pending durable handback files via Wave 14 (idempotent).
 *
 * @param {string} projectPath
 * @param {object} [opts]
 */
export function stageIngest(projectPath, opts = {}) {
  const runs = Array.isArray(opts.runs) ? opts.runs : [];
  const pending = Array.isArray(opts.pendingHandbacks)
    ? opts.pendingHandbacks
    : [];

  const worktrees = [];
  for (const r of runs) {
    if (r && r.worktree) worktrees.push(r.worktree);
  }
  for (const p of pending) {
    if (typeof p === 'string') worktrees.push(p);
    else if (p && p.worktree) worktrees.push(p.worktree);
  }

  const results = [];
  for (const wt of worktrees) {
    if (!isIngestable(wt)) {
      results.push({
        worktree: wt,
        ok: false,
        skipped: true,
        reason: 'not_ingestable',
      });
      continue;
    }
    const ingested = ingestHandback(projectPath, wt, {
      skip_index: opts.skip_index !== false,
      dossier: opts.dossier ?? null,
      at: opts.at ?? null,
    });
    results.push({
      worktree: wt,
      ok: ingested.ok === true,
      status: ingested.status ?? null,
      idempotence_key: ingested.idempotence_key ?? null,
      client_event_id: ingested.client_event_id ?? null,
      receipt_append: ingested.receipt_append ?? null,
      proposal_append: ingested.proposal_append ?? null,
      status_code: ingested.status_code ?? null,
      duplicate:
        ingested.status_code === 'HANDBACK_DUPLICATE_IGNORED' ||
        ingested.receipt_append?.idempotent === true,
    });
  }

  return {
    ok: true,
    stage: 'ingest',
    results,
    adopted: results.filter((r) => r.ok).length,
    skipped: results.filter((r) => r.skipped).length,
  };
}

// ── Stage 3: PUBLISH ───────────────────────────────────────────────────────

/**
 * publishAttention on any resulting edges (Wave 15 call site T-ATT-CS6).
 *
 * @param {string} projectPath
 * @param {object} [opts]
 */
export function stagePublish(projectPath, opts = {}) {
  const ledgerView = opts.ledgerView ?? buildPostReconcileLedgerView(projectPath, opts);
  const derived = deriveAttention(ledgerView);
  // T-ATT-CS6: boot/open-project → openProjectPipeline stage 3.
  const published = publishAttention(projectPath, {
    ledgerView,
    derived,
    who: opts.who || 'open-project-pipeline',
    at: opts.at,
    client_event_id: opts.attention_client_event_id,
    // T-ATT-CS6 — removal-proof marker must be the literal call-site id
    call_site: 'openProjectPipeline:publish', // ATTENTION_CALL_SITES.OPEN_PROJECT
    home: opts.home,
    env: opts.env,
    project_id: opts.project_id,
    skip_brief_cache: opts.skip_brief_cache === true,
  });
  return {
    ok: published.ok !== false,
    stage: 'publish',
    derived,
    published,
    call_site: ATTENTION_CALL_SITES.OPEN_PROJECT,
  };
}

// ── Stage 4: COMPOSE (heal-before-brief + seen-receipt + first message) ────

/**
 * HEAL-BEFORE-BRIEF: validate → heal → write through spine when torn.
 *
 * @param {string} projectPath
 * @param {{ seed?: object|null }} [opts]
 */
export function healBeforeBrief(projectPath, opts = {}) {
  const loaded = loadProjectRoadmap(projectPath);
  if (!loaded.ok && loaded.exists) {
    return {
      ok: false,
      healed: false,
      ...briefFailure(BRIEF_CODE.BRIEF_LEDGER_UNREADABLE, {
        detail: loaded.message ?? loaded.error,
      }),
    };
  }
  if (!loaded.exists) {
    if (opts.seed) {
      // Seed only materialises when caller asks (tests); otherwise no campaign.
      return {
        ok: true,
        healed: false,
        exists: false,
        roadmap: opts.seed,
        code: null,
      };
    }
    return {
      ok: true,
      healed: false,
      exists: false,
      roadmap: null,
      ...briefFailure(BRIEF_CODE.BRIEF_NO_CAMPAIGN),
    };
  }

  const roadmap = loaded.roadmap;
  const validated = validateRoadmap(roadmap, { allow_unevented_steps: false });
  if (validated.ok && validated.clean !== false) {
    // Clean or issues-only (no silent rewrite) — no heal required when ok.
    if (validated.ok) {
      const issues = Array.isArray(validated.issues) ? validated.issues : [];
      // If projection already matches events, no write.
      return {
        ok: true,
        healed: false,
        exists: true,
        roadmap,
        issues,
        code: null,
      };
    }
  }

  if (!validated.ok && validated.error === 'roadmap_silent_rewrite') {
    const healed = healRoadmap(roadmap);
    if (!healed.ok) {
      return {
        ok: false,
        healed: false,
        ...briefFailure(BRIEF_CODE.BRIEF_ASSEMBLY_FAILED, {
          detail: healed.message ?? healed.error,
        }),
      };
    }
    const written = writeRoadmapThroughSpine(projectPath, healed.roadmap);
    if (!written.ok) {
      return {
        ok: false,
        healed: false,
        ...briefFailure(BRIEF_CODE.BRIEF_LEDGER_UNREADABLE, {
          detail: written.message ?? written.error,
        }),
      };
    }
    const n =
      (Array.isArray(validated.drift) ? validated.drift.length : 0) ||
      (Array.isArray(healed.issues) ? healed.issues.length : 1);
    const note = briefFailure(BRIEF_CODE.BRIEF_ROADMAP_HEALED, { n });
    return {
      ok: true,
      healed: true,
      exists: true,
      roadmap: healed.roadmap,
      issues: healed.issues,
      spine_write: written,
      code: BRIEF_CODE.BRIEF_ROADMAP_HEALED,
      status_code: BRIEF_CODE.BRIEF_ROADMAP_HEALED,
      user_text: note.user_text,
      n,
    };
  }

  // parse failure etc.
  if (!validated.ok) {
    return {
      ok: false,
      healed: false,
      ...briefFailure(BRIEF_CODE.BRIEF_LEDGER_UNREADABLE, {
        detail: validated.message ?? validated.error,
      }),
    };
  }

  return {
    ok: true,
    healed: false,
    exists: true,
    roadmap,
    issues: validated.issues ?? [],
    code: null,
  };
}

/**
 * Build a pure ledger view from the POST-RECONCILE on-disk ledger only.
 * Composer never peeks at live pids.
 *
 * @param {string} projectPath
 * @param {object} [opts]
 */
export function buildPostReconcileLedgerView(projectPath, opts = {}) {
  const loaded = loadProjectRoadmap(projectPath);
  if (!loaded.ok && loaded.exists) {
    return { unreadable: true, events: [], projection: [], run_facts: [] };
  }
  if (!loaded.exists) {
    return {
      unreadable: false,
      empty: true,
      events: [],
      projection: [],
      run_facts: opts.run_facts ?? [],
      missing_handbacks: opts.missing_handbacks ?? [],
    };
  }
  const roadmap = loaded.roadmap;
  const events = Array.isArray(roadmap.roadmap_events) ? roadmap.roadmap_events : [];
  let projection = Array.isArray(roadmap.roadmap_projection)
    ? roadmap.roadmap_projection
    : [];
  try {
    const built = buildRoadmapProjection(events);
    if (Array.isArray(built?.projection)) projection = built.projection;
  } catch {
    /* keep stored */
  }

  // Derive missing-handback / dead-run facts from durable events (not live pids).
  const missing_handbacks = [];
  const run_facts = Array.isArray(opts.run_facts) ? [...opts.run_facts] : [];
  for (const e of events) {
    if (!e) continue;
    const why = e.receipt?.why || e.note || '';
    if (
      e.client_event_id?.startsWith?.('missing-handback:') ||
      String(why).includes('HANDBACK_NEVER_ARRIVED') ||
      e.receipt?.cause === 'handback_never_arrived'
    ) {
      const id =
        e.client_event_id?.replace?.(/^missing-handback:/, '') ||
        e.run_id ||
        e.step_id ||
        'unknown';
      missing_handbacks.push({
        commission_id: id,
        step_id: e.step_id ?? null,
        named: true,
        status_code: 'HANDBACK_NEVER_ARRIVED',
      });
    }
    if (
      String(why).includes('status_flip->DEAD') ||
      e.receipt?.run_state === RUN_LIVENESS.DEAD ||
      e.dead === true
    ) {
      run_facts.push({
        run_id: e.run_id ?? e.receipt?.run_id ?? e.step_id,
        step_id: e.step_id,
        run_state: RUN_LIVENESS.DEAD,
        cause: e.receipt?.cause ?? 'lease_expired',
      });
    }
  }
  if (Array.isArray(opts.missing_handbacks)) {
    for (const m of opts.missing_handbacks) missing_handbacks.push(m);
  }

  const view = buildLedgerView({
    roadmap,
    events,
    projection,
    at: opts.at ?? null,
    scaffolding: opts.scaffolding ?? null,
    current_step_id: opts.current_step_id ?? null,
    handback: opts.handback ?? null,
  });
  // Extra fields for attention + first message (carried on the view object).
  view.run_facts = run_facts;
  view.missing_handbacks = missing_handbacks;
  view.roadmap = roadmap;
  return view;
}

/**
 * Join dossier read API into a Phase-A packet, closing A2 NEEDS-DOSSIER-JOIN
 * gaps where dossier facts answer Q7 (and related continuity questions).
 *
 * @param {object} packet
 * @param {object[]} dossierReads
 */
export function joinDossierIntoPacket(packet, dossierReads) {
  if (!packet || !Array.isArray(packet.answers)) return packet;
  const reads = Array.isArray(dossierReads) ? dossierReads : [];
  const conclusions = [];
  for (const r of reads) {
    if (!r || r.ok === false) continue;
    const d = r.dossier ?? r;
    const hb = d.handback;
    if (!hb || hb.unknown === true) continue;
    const body = hb.body ?? hb;
    if (body && (body.active_effort || body.kind === 'handback')) {
      conclusions.push({
        job_id: d.job_id ?? null,
        skill: body.skill ?? d.commissioned_as?.split?.(':')?.[0] ?? null,
        active_effort: body.active_effort ?? null,
        why_next: body.why_next ?? null,
        provenance: {
          source: 'commission-dossier',
          job_id: d.job_id ?? null,
        },
      });
    }
  }

  if (!conclusions.length) return { ...packet, dossier_joined: false };

  const answers = packet.answers.map((a) => {
    if (a.id !== 'Q7') return a;
    if (a.unknown !== true && a.answer !== UNKNOWN_ANSWER) return a;
    return {
      id: 'Q7',
      question: BRIEF_QUESTIONS.Q7,
      unknown: false,
      answer: { conclusions },
      provenance: conclusions.map((c) => c.provenance),
      store: 'commission_dossier_join',
      dossier_joined: true,
    };
  });

  const answerable = answers.filter((x) => !x.unknown).length;
  return {
    ...packet,
    answers,
    dossier_joined: true,
    coverage: {
      answerable,
      total: answers.length,
      stamp: `answerable ${answerable}/${answers.length} from local evidence`,
    },
    honest_unknowns: answers.filter((x) => x.unknown).map((x) => x.id),
  };
}

/**
 * Facts already recorded on the ledger that the first message must NOT re-ask.
 *
 * @param {object} ledgerView
 * @param {object|null} strip
 * @param {object|null} face
 */
export function recordedFacts(ledgerView, strip, face) {
  const events = Array.isArray(ledgerView?.events) ? ledgerView.events : [];
  const facts = {
    objective: null,
    scaffolding: null,
    last_confirmation: null,
  };

  const north =
    face?.narrative?.north_star ??
    strip?.active_effort ??
    null;
  if (typeof north === 'string' && north.trim()) {
    facts.objective = north.trim();
  }

  const scaffold = events.find((e) => e && e.kind === 'scaffold_proposal');
  if (scaffold) {
    facts.scaffolding = {
      step_id: scaffold.step_id ?? null,
      at: scaffold.at ?? null,
      name: scaffold.name ?? null,
    };
  } else if (Array.isArray(ledgerView?.scaffolding?.steps)) {
    facts.scaffolding = { steps: ledgerView.scaffolding.steps.length };
  } else if (
    Array.isArray(ledgerView?.projection) &&
    ledgerView.projection.length > 0
  ) {
    facts.scaffolding = { steps: ledgerView.projection.length };
  }

  // Last confirmation: prefer human strip instruments, then human-ish event receipts.
  // System actors (pipeline / reconciler / mediator) are not "confirmations".
  const SYSTEM_WHO = new Set([
    'open-project-pipeline',
    'status-reconciler',
    'status-ingestion-seam',
    'publishAttention',
    'steward-reconcile',
  ]);

  if (Array.isArray(strip?.instruments)) {
    for (let i = strip.instruments.length - 1; i >= 0; i--) {
      const inst = strip.instruments[i];
      if (!inst) continue;
      if (
        inst.kind === 'commission_confirm' ||
        (inst.who && !SYSTEM_WHO.has(String(inst.who)))
      ) {
        facts.last_confirmation = {
          who: inst.who ?? null,
          when: inst.as_of ?? null,
          kind: inst.kind ?? null,
        };
        break;
      }
    }
  }
  if (!facts.last_confirmation) {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (!e) continue;
      if (e.kind === 'commission_bind') {
        const who = e.receipt?.who ?? e.who ?? null;
        if (who && SYSTEM_WHO.has(String(who))) continue;
        facts.last_confirmation = {
          who,
          when: e.at ?? null,
          commissioned_as: e.commissioned_as ?? null,
        };
        break;
      }
      if (e.kind === 'status_flip' && e.receipt?.who) {
        if (SYSTEM_WHO.has(String(e.receipt.who))) continue;
        // Prefer flips that look like human gates (campaign open / confirm).
        facts.last_confirmation = {
          who: e.receipt.who,
          when: e.receipt.when ?? e.at ?? null,
          why: e.receipt.why ?? null,
        };
        break;
      }
    }
  }

  return facts;
}

/**
 * ZERO-MODEL deterministic first-message render.
 * Byte-identical on repeat for the same ledger view + opts.
 * NL polish is NOT applied (absent by default at cold start).
 *
 * @param {{
 *   ledgerView: object,
 *   strip?: object|null,
 *   face?: object|null,
 *   packet?: object|null,
 *   heal?: object|null,
 *   stage_label?: string|null,
 *   as_of?: string,
 * }} input
 * @returns {{ ok: true, text: string, message: object, model_calls: 0, spend: 0 } | object}
 */
export function composeFirstMessage(input = {}) {
  const phase_a = {
    complete: true,
    deterministic: true,
    model_calls: 0,
    commission_calls: 0,
    zero_model_calls: true,
    zero_spend: true,
    nl_polish: false,
  };

  try {
    const ledgerView = input.ledgerView ?? {};
    if (ledgerView.unreadable === true) {
      const fail = briefFailure(BRIEF_CODE.BRIEF_LEDGER_UNREADABLE);
      return {
        ok: false,
        ...fail,
        text: fail.user_text,
        phase_a,
        model_calls: 0,
        spend: 0,
      };
    }

    if (ledgerView.empty === true && !(ledgerView.events || []).length) {
      const fail = briefFailure(BRIEF_CODE.BRIEF_NO_CAMPAIGN);
      return {
        ok: true,
        status_code: BRIEF_CODE.BRIEF_NO_CAMPAIGN,
        text: fail.user_text,
        message: {
          schema: FIRST_MESSAGE_SCHEMA,
          status_code: BRIEF_CODE.BRIEF_NO_CAMPAIGN,
          lines: [fail.user_text],
        },
        phase_a,
        model_calls: 0,
        spend: 0,
        asks: [],
        proposes: null,
      };
    }

    const strip = input.strip ?? null;
    const face = input.face ?? null;
    const facts = recordedFacts(ledgerView, strip, face);
    const projection = Array.isArray(ledgerView.projection)
      ? ledgerView.projection
      : [];
    const events = Array.isArray(ledgerView.events) ? ledgerView.events : [];
    const run_facts = Array.isArray(ledgerView.run_facts)
      ? ledgerView.run_facts
      : [];
    const missing = Array.isArray(ledgerView.missing_handbacks)
      ? ledgerView.missing_handbacks
      : [];

    // Also scan events for named facts when run_facts/missing not pre-filled.
    const deadFromEvents = [];
    const missingFromEvents = [];
    for (const e of events) {
      if (!e) continue;
      const why = String(e.receipt?.why || e.note || '');
      if (
        why.includes('status_flip->DEAD') ||
        e.receipt?.run_state === RUN_LIVENESS.DEAD ||
        e.dead === true
      ) {
        deadFromEvents.push({
          run_id: e.run_id ?? e.step_id ?? 'unknown',
          step_id: e.step_id ?? null,
        });
      }
      if (
        e.client_event_id?.startsWith?.('missing-handback:') ||
        why.includes('HANDBACK_NEVER_ARRIVED') ||
        e.receipt?.cause === 'handback_never_arrived'
      ) {
        missingFromEvents.push({
          commission_id:
            e.client_event_id?.replace?.(/^missing-handback:/, '') ||
            e.run_id ||
            e.step_id ||
            'unknown',
        });
      }
    }

    const deadRuns = [
      ...run_facts.filter((r) => r && r.run_state === RUN_LIVENESS.DEAD),
      ...deadFromEvents,
    ];
    // Dedupe by run_id
    const deadSeen = new Set();
    const deadUnique = [];
    for (const d of deadRuns) {
      const id = d.run_id || d.step_id || JSON.stringify(d);
      if (deadSeen.has(id)) continue;
      deadSeen.add(id);
      deadUnique.push(d);
    }
    const missingAll = [...missing, ...missingFromEvents];
    const missSeen = new Set();
    const missingUnique = [];
    for (const m of missingAll) {
      const id = m.commission_id || m.id || JSON.stringify(m);
      if (missSeen.has(id)) continue;
      missSeen.add(id);
      missingUnique.push(m);
    }

    const current =
      projection.find((s) => s && s.status === 'active') ||
      projection.find((s) => s && s.status === 'waiting') ||
      projection.find(
        (s) => s && s.status !== 'done' && s.status !== 'parked',
      ) ||
      null;
    const stageName =
      input.stage_label ||
      current?.name ||
      current?.id ||
      strip?.active_effort ||
      strip?.phase ||
      'unknown';

    const lines = [];
    lines.push(`Campaign stage: ${stageName}.`);

    if (facts.objective) {
      lines.push(`Objective (recorded): ${facts.objective}.`);
    }
    if (facts.scaffolding) {
      const sc =
        facts.scaffolding.steps != null
          ? `${facts.scaffolding.steps} scaffolded step(s)`
          : facts.scaffolding.name || facts.scaffolding.step_id || 'recorded';
      lines.push(`Scaffolding (recorded): ${sc}.`);
    }
    if (facts.last_confirmation) {
      const who = facts.last_confirmation.who || 'recorded';
      const when = facts.last_confirmation.when
        ? ` at ${facts.last_confirmation.when}`
        : '';
      lines.push(`Last confirmation (recorded): ${who}${when}.`);
    }

    // Run liveness from ledger only.
    if (deadUnique.length === 0 && missingUnique.length === 0 && !current) {
      const quiet = briefFailure(BRIEF_CODE.BRIEF_ALL_QUIET, { s: stageName });
      lines.push(quiet.user_text);
    }

    for (const d of deadUnique) {
      const id = d.run_id || d.step_id || 'unknown';
      lines.push(
        `Dead run NAMED: ${id} — process identity no longer live; marked DEAD, not absorbed.`,
      );
    }
    for (const m of missingUnique) {
      const id = m.commission_id || m.id || 'unknown';
      const named = nameMissingHandback({
        commission_id: id,
        confirmed_ago: m.confirmed_ago || 'unknown duration',
      });
      lines.push(`Missing handback NAMED: ${named.user_text}`);
    }

    // Honest unknown for unresolvable liveness.
    const unknownRuns = run_facts.filter(
      (r) => r && r.run_state === RUN_LIVENESS.UNKNOWN,
    );
    for (const u of unknownRuns) {
      const id = u.run_id || 'unknown';
      const f = briefFailure(BRIEF_CODE.BRIEF_RUN_UNKNOWN, { id });
      lines.push(f.user_text);
    }

    // Waiting on John (from strip / projection).
    const waitingBits = [];
    if (strip?.human_wait && strip.human_wait !== 'none') {
      waitingBits.push(String(strip.human_wait).trim());
    }
    for (const s of projection) {
      if (s && s.waiting_on) waitingBits.push(String(s.waiting_on));
    }
    if (waitingBits.length) {
      lines.push(`Waiting on you: ${waitingBits.join('; ')}.`);
    } else if (deadUnique.length || missingUnique.length) {
      lines.push(
        'Waiting on you: name the dead run / missing handback disposition (recommission or park).',
      );
    }

    // Next step + why (ANTI-STUB: must propose; must not re-ask recorded facts).
    let nextStep =
      strip?.next_recommended ||
      current?.done_when ||
      null;
    let whyNext =
      strip?.why_next ||
      (deadUnique.length || missingUnique.length
        ? 'Continuity criterion 11 — dead run + missing handback NAMED from the post-reconcile ledger; resume from durable facts, do not re-ask.'
        : facts.objective
          ? `Advance the recorded objective (${facts.objective}).`
          : null);

    if (!nextStep) {
      if (deadUnique.length || missingUnique.length) {
        nextStep =
          'Decide recommission vs park for the named dead run / missing handback';
      } else if (current) {
        nextStep = `Continue stage ${current.name || current.id}`;
      } else {
        nextStep = 'Describe the campaign to begin';
      }
    }
    if (!whyNext) {
      whyNext = 'Post-reconcile ledger shows this as the standing next move.';
    }

    lines.push(`Next step: ${nextStep}.`);
    lines.push(`Why: ${whyNext}.`);

    if (input.heal?.healed === true) {
      const note = briefFailure(BRIEF_CODE.BRIEF_ROADMAP_HEALED, {
        n: input.heal.n ?? 1,
      });
      lines.push(note.user_text);
    }

    // ANTI-RE-ASK: never form a question about recorded objective/scaffolding/confirmation.
    const asks = [];
    // Deliberately empty when facts are recorded — the brief proposes, does not re-ask.

    const text = lines.join('\n');
    const message = {
      schema: FIRST_MESSAGE_SCHEMA,
      deterministic: true,
      zero_model: true,
      zero_spend: true,
      nl_polish: false,
      stage: stageName,
      objective_recorded: facts.objective,
      scaffolding_recorded: facts.scaffolding,
      last_confirmation_recorded: facts.last_confirmation,
      dead_runs: deadUnique.map((d) => d.run_id || d.step_id),
      missing_handbacks: missingUnique.map((m) => m.commission_id || m.id),
      next_step: nextStep,
      why_next: whyNext,
      asks,
      lines,
      text,
    };

    return {
      ok: true,
      text,
      message,
      phase_a,
      model_calls: 0,
      spend: 0,
      asks,
      proposes: { next_step: nextStep, why: whyNext },
      recorded: facts,
      status_code:
        deadUnique.length || missingUnique.length
          ? null
          : waitingBits.length
            ? null
            : BRIEF_CODE.BRIEF_ALL_QUIET,
    };
  } catch (e) {
    const fail = briefFailure(BRIEF_CODE.BRIEF_ASSEMBLY_FAILED, {
      detail: String(e?.message ?? e),
    });
    return {
      ok: false,
      ...fail,
      text: fail.user_text,
      phase_a: {
        complete: false,
        deterministic: true,
        model_calls: 0,
        commission_calls: 0,
        zero_model_calls: true,
        zero_spend: true,
        nl_polish: false,
      },
      model_calls: 0,
      spend: 0,
    };
  }
}

/**
 * Compose stage: heal → assembleBriefPacket (post-reconcile) → dossier join →
 * first message → seen receipt. Never runs if reconcile has not completed.
 *
 * @param {string} projectPath
 * @param {object} [opts]
 */
export function stageCompose(projectPath, opts = {}) {
  // Guard: composer never runs against a pre-reconcile ledger.
  if (opts.reconcile_completed !== true && opts.force_compose !== true) {
    return {
      ok: false,
      stage: 'compose',
      error: 'compose_requires_reconcile',
      message:
        'Composer refused — reconcile must complete before compose (post-reconcile ledger only).',
      packet: null,
      first_message: null,
    };
  }

  const heal = healBeforeBrief(projectPath, { seed: opts.seed });
  if (!heal.ok && heal.status_code === BRIEF_CODE.BRIEF_LEDGER_UNREADABLE) {
    return {
      ok: false,
      stage: 'compose',
      heal,
      ...briefFailure(BRIEF_CODE.BRIEF_LEDGER_UNREADABLE),
      packet: null,
      first_message: null,
      model_calls: 0,
      spend: 0,
    };
  }

  if (heal.exists === false && heal.status_code === BRIEF_CODE.BRIEF_NO_CAMPAIGN) {
    const first = composeFirstMessage({
      ledgerView: { empty: true, events: [], projection: [] },
    });
    return {
      ok: true,
      stage: 'compose',
      heal,
      packet: null,
      first_message: first,
      model_calls: 0,
      spend: 0,
      status_code: BRIEF_CODE.BRIEF_NO_CAMPAIGN,
    };
  }

  // Load POST-RECONCILE ledger view only (after heal write).
  const ledgerView = buildPostReconcileLedgerView(projectPath, {
    at: opts.at,
    run_facts: opts.run_facts,
    missing_handbacks: opts.missing_handbacks,
    scaffolding: opts.scaffolding,
    current_step_id: opts.current_step_id,
  });
  // Attach run facts from reconcile for attention/composer.
  if (Array.isArray(opts.run_facts)) {
    ledgerView.run_facts = opts.run_facts;
  }
  if (Array.isArray(opts.missing_handbacks)) {
    ledgerView.missing_handbacks = opts.missing_handbacks;
  }

  const surfaces = opts.surfaces ?? loadProjectSurfaces(projectPath);
  const strip = surfaces?.strip ?? opts.strip ?? null;
  const face = surfaces?.face ?? opts.face ?? null;

  // Dossier read API join (close A2 NEEDS-DOSSIER-JOIN).
  let dossierReads = [];
  if (opts.dossiers) {
    dossierReads = opts.dossiers;
  } else {
    const listed = listDossiers(projectPath);
    if (listed.ok && Array.isArray(listed.dossiers)) {
      // listDossiers already returns readDossier results.
      dossierReads = listed.dossiers;
    }
  }

  let packet;
  try {
    packet = assembleBriefPacket({
      project: projectPath,
      altitude: 'project',
      as_of: opts.as_of ?? '1970-01-01',
      surfaces: { strip, face },
      roadmap: heal.roadmap ?? ledgerView.roadmap ?? undefined,
      // Injectors keep Phase A free of wall-clock when tests pin as_of.
      journal: opts.journal ?? { present: false, entries: [] },
      anchor_knowledge:
        opts.anchor_knowledge !== undefined
          ? opts.anchor_knowledge
          : { present: false, reason: 'not_consulted_at_cold_start' },
    });
    // Ensure zero model.
    if (packet?.phase_a) {
      packet.phase_a.model_calls = 0;
      packet.phase_a.commission_calls = 0;
      packet.phase_a.zero_model_calls = true;
    }
    packet = joinDossierIntoPacket(packet, dossierReads);
  } catch (e) {
    return {
      ok: false,
      stage: 'compose',
      heal,
      ...briefFailure(BRIEF_CODE.BRIEF_ASSEMBLY_FAILED, {
        detail: String(e?.message ?? e),
      }),
      packet: null,
      first_message: null,
      model_calls: 0,
      spend: 0,
    };
  }

  const first_message = composeFirstMessage({
    ledgerView,
    strip,
    face,
    packet,
    heal,
    stage_label: opts.stage_label,
    as_of: opts.as_of,
  });

  // SEEN-RECEIPT after assembly (count-anchored delta).
  let seen = null;
  if (opts.mark_seen !== false && strip && opts.who) {
    const appended = appendSeenReceipt(strip, {
      who: opts.who,
      when: opts.at || opts.as_of || '1970-01-01T00:00:00.000Z',
      altitude: 'project',
      journal_seen: Array.isArray(opts.journal?.entries)
        ? opts.journal.entries.length
        : 0,
    });
    if (appended.ok) {
      seen = appended.receipt;
      if (opts.persist_seen !== false && !opts.dry_run) {
        writeStripThroughSpine(projectPath, appended.strip, {
          fileName: STRIP_FILE_NAME,
        });
      }
    } else {
      seen = { ok: false, error: appended.error };
    }
  }

  // NL polish absent by default at cold start.
  const nl_polish = {
    present: false,
    envelope_debited: false,
    path: resolveNoLiveEnvelopePath(QUEUE_WITHOUT_ENVELOPE_KIND, {
      live: false,
    }),
  };

  return {
    ok: first_message.ok !== false,
    stage: 'compose',
    heal,
    packet,
    first_message,
    seen_receipt: seen,
    nl_polish,
    dossier_joined: packet?.dossier_joined === true,
    model_calls: 0,
    spend: 0,
    ledger_source: 'post-reconcile',
    composer_peeks_live_pids: false,
  };
}

// ── THE PIPELINE ───────────────────────────────────────────────────────────

/**
 * THE ONE open-project path. Ordered stages:
 *   1. reconcile  2. ingest  3. publish  4. compose
 *
 * Kill-between-stages: pass `stopAfter: 'reconcile'|'ingest'|'publish'` to
 * halt after that stage (simulating process kill). Re-run without stopAfter
 * converges; stages are idempotent via client_event_id.
 *
 * @param {string} projectPath
 * @param {{
 *   runs?: object[],
 *   pendingHandbacks?: Array<string|object>,
 *   who?: string,
 *   at?: string,
 *   as_of?: string,
 *   seed?: object|null,
 *   stopAfter?: 'reconcile'|'ingest'|'publish'|null,
 *   nowMono?: number,
 *   probe?: object|null,
 *   mark_seen?: boolean,
 *   dry_run?: boolean,
 *   scaffolding?: object|null,
 *   surfaces?: object|null,
 *   journal?: object,
 *   stage_label?: string,
 * }} [opts]
 */
export function openProjectPipeline(projectPath, opts = {}) {
  if (!projectPath || typeof projectPath !== 'string') {
    return {
      ok: false,
      error: 'project_path_required',
      message: 'openProjectPipeline requires projectPath',
      schema: OPEN_PROJECT_PIPELINE_SCHEMA,
    };
  }

  const root = path.resolve(projectPath);
  const who = opts.who || 'john';
  const at = opts.at || '1970-01-01T00:00:00.000Z';
  const stages_completed = [];
  const stage_results = {};
  const order = [];

  const stopAfter = opts.stopAfter || null;
  if (stopAfter && !PIPELINE_STAGES.includes(stopAfter) && stopAfter !== 'compose') {
    // allow stop after any of the first three
  }

  // ── 1. RECONCILE ─────────────────────────────────────────────────────────
  order.push('reconcile');
  const reconcileResult = stageReconcile(root, {
    runs: opts.runs,
    who,
    at,
    seed: opts.seed,
    nowMono: opts.nowMono,
    probe: opts.probe,
    drainOutboxes: opts.drainOutboxes,
  });
  stage_results.reconcile = reconcileResult;
  stages_completed.push('reconcile');
  writePipelineCheckpointAtomic(root, {
    schema: OPEN_PROJECT_PIPELINE_SCHEMA,
    stages_completed: [...stages_completed],
    at,
    who,
  });

  if (stopAfter === 'reconcile') {
    return finalizePipeline({
      root,
      ok: true,
      stopped_after: 'reconcile',
      stages_completed,
      stage_results,
      order,
      who,
      at,
      compose_ran: false,
    });
  }

  // ── 2. INGEST ────────────────────────────────────────────────────────────
  order.push('ingest');
  const ingestResult = stageIngest(root, {
    runs: opts.runs,
    pendingHandbacks: opts.pendingHandbacks,
    who,
    at,
    skip_index: opts.skip_index !== false,
    dossier: opts.dossier,
  });
  stage_results.ingest = ingestResult;
  stages_completed.push('ingest');
  writePipelineCheckpointAtomic(root, {
    schema: OPEN_PROJECT_PIPELINE_SCHEMA,
    stages_completed: [...stages_completed],
    at,
    who,
  });

  if (stopAfter === 'ingest') {
    return finalizePipeline({
      root,
      ok: true,
      stopped_after: 'ingest',
      stages_completed,
      stage_results,
      order,
      who,
      at,
      compose_ran: false,
    });
  }

  // ── 3. PUBLISH ───────────────────────────────────────────────────────────
  order.push('publish');
  const run_facts = reconcileResult.reconcile?.run_facts ?? [];
  const missing_handbacks = reconcileResult.named_missing_handbacks ?? [];
  const publishResult = stagePublish(root, {
    who,
    at,
    run_facts,
    missing_handbacks,
  });
  // Rebuild ledger view with reconcile facts for publish (stagePublish loads disk;
  // pass explicit facts via a second publish if edges need them).
  const ledgerForPublish = buildPostReconcileLedgerView(root, {
    at,
    run_facts,
    missing_handbacks,
  });
  ledgerForPublish.run_facts = run_facts;
  ledgerForPublish.missing_handbacks = missing_handbacks;
  const publishWithFacts = publishAttention(root, {
    ledgerView: ledgerForPublish,
    who,
    at,
    // T-ATT-CS6 — removal-proof marker must be the literal call-site id
    call_site: 'openProjectPipeline:publish', // ATTENTION_CALL_SITES.OPEN_PROJECT
    home: opts.home,
    env: opts.env,
    project_id: opts.project_id,
    skip_brief_cache: opts.skip_brief_cache === true,
  });
  stage_results.publish = {
    ...publishResult,
    published: publishWithFacts,
    derived: deriveAttention(ledgerForPublish),
  };
  stages_completed.push('publish');
  writePipelineCheckpointAtomic(root, {
    schema: OPEN_PROJECT_PIPELINE_SCHEMA,
    stages_completed: [...stages_completed],
    at,
    who,
  });

  if (stopAfter === 'publish') {
    return finalizePipeline({
      root,
      ok: true,
      stopped_after: 'publish',
      stages_completed,
      stage_results,
      order,
      who,
      at,
      compose_ran: false,
    });
  }

  // ── 4. COMPOSE (post-reconcile ledger ONLY) ──────────────────────────────
  order.push('compose');
  const composeResult = stageCompose(root, {
    who,
    at,
    as_of: opts.as_of || at.slice(0, 10),
    seed: opts.seed,
    reconcile_completed: true,
    run_facts,
    missing_handbacks,
    scaffolding: opts.scaffolding,
    surfaces: opts.surfaces,
    journal: opts.journal,
    stage_label: opts.stage_label,
    mark_seen: opts.mark_seen,
    dry_run: opts.dry_run,
    persist_seen: opts.persist_seen,
    dossiers: opts.dossiers,
    anchor_knowledge: opts.anchor_knowledge,
  });
  stage_results.compose = composeResult;
  stages_completed.push('compose');
  writePipelineCheckpointAtomic(root, {
    schema: OPEN_PROJECT_PIPELINE_SCHEMA,
    stages_completed: [...stages_completed],
    at,
    who,
    complete: true,
  });

  return finalizePipeline({
    root,
    ok: composeResult.ok !== false,
    stopped_after: null,
    stages_completed,
    stage_results,
    order,
    who,
    at,
    compose_ran: true,
  });
}

function finalizePipeline(ctx) {
  const compose = ctx.stage_results.compose ?? null;
  const first = compose?.first_message ?? null;
  return {
    ok: ctx.ok,
    schema: OPEN_PROJECT_PIPELINE_SCHEMA,
    module: OPEN_PROJECT_PIPELINE_MODULE,
    project_path: ctx.root,
    order: ctx.order,
    stages_completed: ctx.stages_completed,
    stopped_after: ctx.stopped_after,
    compose_ran: ctx.compose_ran === true,
    // Proven order for tests.
    pipeline_order: [...PIPELINE_STAGES],
    stages: ctx.stage_results,
    first_message: first,
    text: first?.text ?? null,
    packet: compose?.packet ?? null,
    heal: compose?.heal ?? null,
    seen_receipt: compose?.seen_receipt ?? null,
    model_calls: 0,
    spend: 0,
    zero_model: true,
    zero_spend: true,
    nl_polish_absent: true,
    who: ctx.who,
    at: ctx.at,
    named_dead: ctx.stage_results.reconcile?.named_dead ?? [],
    named_missing_handbacks:
      ctx.stage_results.reconcile?.named_missing_handbacks ?? [],
  };
}

/**
 * Convenience: restart path — reconcileAfterRestart then full pipeline.
 * Deliberately seeded for the Wave-4 restart case.
 *
 * @param {string} projectPath
 * @param {object} [opts]
 */
export function openProjectAfterKillEverything(projectPath, opts = {}) {
  // Restart reconcile first (outbox drain + lease truth), then full pipeline.
  const restart = reconcileAfterRestart(projectPath, {
    runs: opts.runs,
    who: opts.who,
    at: opts.at,
    seed: opts.seed,
    nowMono: opts.nowMono,
    probe: opts.probe,
    drainOutboxes: opts.drainOutboxes !== false,
  });
  const pipeline = openProjectPipeline(projectPath, opts);
  return {
    ...pipeline,
    kill_everything_resume: true,
    restart,
  };
}

/**
 * Load golden first-message text.
 * @param {string} [root]
 */
export function loadGoldenFirstMessage(root = DEFAULT_ROOT) {
  const p = path.join(root, GOLDEN_FIRST_MESSAGE_REL);
  return fs.readFileSync(p, 'utf8');
}

/**
 * Stable inputs for golden first-message (fixed timestamps, no wall-clock).
 */
export function goldenFirstMessageInputs() {
  const ledgerView = {
    events: [
      {
        seq: 1,
        kind: 'step_create',
        step_id: 'stage-research',
        at: '2026-08-01',
        name: 'Research the campaign substrate',
        status: 'planned',
      },
      {
        seq: 2,
        kind: 'scaffold_proposal',
        at: '2026-08-01',
        name: 'Campaign scaffold',
        client_event_id: 'scaffold:golden-w15',
      },
      {
        seq: 3,
        kind: 'status_flip',
        step_id: 'stage-research',
        at: '2026-08-01',
        to: 'active',
        receipt: {
          who: 'john',
          when: '2026-08-01',
          why: 'campaign open',
        },
      },
      {
        seq: 4,
        kind: 'status_flip',
        step_id: 'stage-research',
        at: '2026-08-01T19:30:00.000Z',
        to: 'waiting',
        client_event_id: 'status:fixture:dead-1',
        run_id: 'run-dead-001',
        receipt: {
          who: 'status-reconciler',
          when: '2026-08-01T19:30:00.000Z',
          why: 'status_flip->DEAD cause=lease_expired run_id=run-dead-001',
          run_state: 'dead',
          cause: 'lease_expired',
        },
      },
      {
        seq: 5,
        kind: 'status_flip',
        step_id: 'stage-research',
        at: '2026-08-01T19:31:00.000Z',
        to: 'waiting',
        client_event_id: 'missing-handback:comm-dead-001',
        run_id: 'run-dead-001',
        receipt: {
          who: 'open-project-pipeline',
          when: '2026-08-01T19:31:00.000Z',
          why: 'HANDBACK_NEVER_ARRIVED commission=comm-dead-001 named, not absorbed',
          cause: 'handback_never_arrived',
          status_code: 'HANDBACK_NEVER_ARRIVED',
        },
      },
    ],
    projection: [
      {
        id: 'stage-research',
        name: 'Research the campaign substrate',
        status: 'waiting',
        done_when: 'researchPrime handback validated',
        waiting_on: 'dead run named; missing handback',
      },
    ],
    run_facts: [
      {
        run_id: 'run-dead-001',
        step_id: 'stage-research',
        run_state: 'dead',
        cause: 'lease_expired',
      },
    ],
    missing_handbacks: [
      {
        commission_id: 'comm-dead-001',
        confirmed_ago: '3h',
        named: true,
        status_code: 'HANDBACK_NEVER_ARRIVED',
      },
    ],
    at: '2026-08-01T19:31:00.000Z',
  };

  const strip = {
    schema: 'ecgberht-strip-v0',
    project_id: 'w15-golden',
    phase: 'build',
    active_effort: 'Wave 15 golden campaign — dead run + missing handback',
    human_wait: 'name the dead run and decide recommission vs park',
    capacity: 'known',
    next_recommended: 'Name the dead run; do not re-ask scaffold',
    why_next:
      'Continuity criterion 11 — dead run + missing handback NAMED from the post-reconcile ledger',
    instruments: [
      {
        kind: 'commission_confirm',
        who: 'john',
        as_of: '2026-08-01T18:00:00.000Z',
        job_id: 'comm-dead-001',
      },
    ],
    receipts: [],
  };

  const face = {
    narrative: {
      north_star: 'Deliver continuity through the ONE open-project pipeline',
    },
  };

  return { ledgerView, strip, face };
}

/**
 * Source-removal proof for Wave 15 module.
 * @param {string} sourceText
 */
export function assertSessionOpenSurfacePresent(sourceText) {
  const missing = [];
  for (const token of [
    'openProjectPipeline',
    'stageReconcile',
    'stageIngest',
    'stagePublish',
    'stageCompose',
    'healBeforeBrief',
    'composeFirstMessage',
    'publishAttention',
    'appendSeenReceipt',
    'assembleBriefPacket',
    'PIPELINE_STAGES',
  ]) {
    if (!sourceText.includes(token)) missing.push(token);
  }
  return { ok: missing.length === 0, missing };
}


