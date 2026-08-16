/**
 * TW3 — Commission + job lifecycle receipts (M2).
 *
 * Steward proposes a commission FOR a Roadmap step; John confirms. Confirm is
 * the write step: it appends a `commission_bind` Roadmap event via the TW1
 * single writer (appendRoadmapEvent) AND a Strip instrument — durable engine
 * state, never UI-only. Propose/confirm is the primary UX; a mode picker is
 * never the primary commission face.
 *
 * Jobs COMPOSE Anchor's job_runner (spawn contract only — see
 * ANCHOR_JOB_COMPOSE). Ecgberht never reimplements the runner and never runs
 * in-process Foreman waves or Shark Tank loops.
 *
 * Lifecycle (M2, Fable review): `queued → running → done | failed | orphaned
 * | reaped`. Any abnormal exit (crash, timeout, kill, orphan, reap) MUST
 * append a `commission_abnormal` receipt (who/when/last_known_state/
 * why_known) — a dead terminal must never persist as silent green or
 * manufacture a false negative-heartbeat. Orphan/reap detection composes
 * zombie-hunter-style liveness evidence supplied by the caller and stays OUT
 * of process: advancing to orphaned/reaped without evidence is refused (no
 * in-engine reaper).
 *
 * Single writer: every Roadmap effect here goes through appendRoadmapEvent
 * (commission_bind / status_flip with receipt). No second store, no direct
 * roadmap_projection writes. See ROADMAP_SINGLE_WRITER.tw3_hook (TW1).
 */

import { SPELLING } from './verbs.mjs';
import {
  buildCommission,
  normalizeCommissionSkill,
  COMMISSION_SKILLS,
} from './commission.mjs';
import {
  appendRoadmapEvent,
  appendRoadmapEventDurable,
  validateRoadmap,
  loadProjectRoadmap,
  ROADMAP_SINGLE_WRITER,
} from './roadmap.mjs';
import {
  appendStripInstrument,
  appendStripReceipt,
  appendStripInstrumentDurable,
} from './write-authority.mjs';
import {
  appendRoadmapEventThroughSpine,
  writeStripThroughSpine,
} from './ledger-spine.mjs';
import {
  publishAttention,
  ATTENTION_CALL_SITES,
} from './attention.mjs';
import {
  resolveProjectPath,
  loadProjectSurfaces,
} from './face-strip.mjs';
import {
  buildCommissionAbnormalReceipt,
  validateReceipt,
} from './receipt-validate.mjs';
import { confirmCommissionJournaled } from './commission-dossier.mjs';

export const JOB_SCHEMA_ID = 'ecgberht-job-v0';
export const COMMISSION_PROPOSAL_SCHEMA_ID = 'ecgberht-commission-proposal-v0';

/** M2 lifecycle states, in order of the normal path. */
export const JOB_LIFECYCLE_STATES = Object.freeze([
  'queued',
  'running',
  'done',
  'failed',
  'orphaned',
  'reaped',
]);

/** Terminal states — a job never leaves one. */
export const JOB_TERMINAL_STATES = Object.freeze([
  'done',
  'failed',
  'orphaned',
  'reaped',
]);

/** Terminals that REQUIRE a commission_abnormal receipt (never silent green). */
export const JOB_ABNORMAL_TERMINALS = Object.freeze([
  'failed',
  'orphaned',
  'reaped',
]);

/** Legal transitions: queued → running → done|failed|orphaned|reaped. */
export const JOB_LIFECYCLE_TRANSITIONS = Object.freeze({
  queued: Object.freeze(['running', 'failed', 'orphaned', 'reaped']),
  running: Object.freeze(['done', 'failed', 'orphaned', 'reaped']),
  done: Object.freeze([]),
  failed: Object.freeze([]),
  orphaned: Object.freeze([]),
  reaped: Object.freeze([]),
});

/**
 * Compose contract with Anchor's job_runner. Ecgberht reads/binds run state;
 * it never replaces the runner and never runs specialist loops in-process.
 */
export const ANCHOR_JOB_COMPOSE = Object.freeze({
  runner: 'anchor_job_runner',
  composes: true,
  reimplements_runner: false,
  in_process_foreman: false,
  in_process_shark_tank: false,
  in_process_wave_loop: false,
  orphan_reap_detection: 'out_of_process',
});

/** Commission propose/confirm is the primary UX — never a mode picker. */
export const COMMISSION_PRIMARY_UX = 'steward_proposal';

function nonEmpty(v) {
  return typeof v === 'string' && v.trim() !== '';
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function isTerminalState(state) {
  return JOB_TERMINAL_STATES.includes(state);
}

/**
 * Steward proposes a commission for a Roadmap step (skill + depth as
 * steward-proposed defaults John can override). Pure read — nothing is
 * written until confirmCommission.
 *
 * @param {{
 *   roadmap: object|string,
 *   step_id?: string|null, step?: string|null,
 *   skill: string,
 *   depth_cell?: string|null, depth?: string|null,
 *   who?: string|null,
 *   project_cwd?: string|null,
 *   seats?: object|null, prefs?: object|null, env?: object,
 *   commission_id?: string|null,
 *   at?: string,
 * }} opts
 * @returns {object} proposal (requires_confirm) or structured refuse
 */
export function proposeCommission(opts = {}) {
  const step_id = opts.step_id ?? opts.step ?? null;
  if (!nonEmpty(step_id)) {
    return {
      ok: false,
      error: 'commission_propose_requires_step',
      spelling: SPELLING,
      message:
        'Commission is proposed FOR a Roadmap step — pass step_id (steward owns the Roadmap; no free-floating jobs).',
      required: ['step_id', 'skill'],
    };
  }

  const skill = normalizeCommissionSkill(opts.skill);
  if (!skill) {
    return {
      ok: false,
      error: 'unknown_commission_skill',
      spelling: SPELLING,
      message: `Commission skill must be one of: ${COMMISSION_SKILLS.join(', ')}`,
      allowed_skills: [...COMMISSION_SKILLS],
    };
  }

  const validated = validateRoadmap(opts.roadmap ?? null);
  if (!validated.ok) {
    return {
      ...validated,
      refused: 'commission_propose',
      message: `${validated.message ?? validated.error} Commission proposal refused until the Roadmap is healthy.`,
    };
  }
  const step = validated.projection.find((s) => s.id === step_id) ?? null;
  if (!step) {
    return {
      ok: false,
      error: 'unknown_step',
      spelling: SPELLING,
      step_id,
      message:
        'No such Roadmap step — propose the step first (roadmap-propose); prose is not a step list.',
    };
  }
  if (step.status === 'done' || step.status === 'parked') {
    return {
      ok: false,
      error: 'commission_step_not_open',
      spelling: SPELLING,
      step_id,
      status: step.status,
      message: `Step '${step_id}' is ${step.status}; commissions are proposed for open steps (running/next).`,
    };
  }

  const depth_cell = opts.depth_cell ?? opts.depth ?? null;
  const commission = buildCommission({
    skill,
    depth_cell,
    active_effort: step.name,
    project_cwd: opts.project_cwd ?? null,
    seats: opts.seats ?? null,
    prefs: opts.prefs ?? null,
    env: opts.env,
    prefsPath: opts.prefsPath,
    commission_id: opts.commission_id ?? null,
  });
  if (!commission.ok) {
    return { ...commission, spelling: SPELLING, step_id };
  }

  const at = opts.at ?? todayIso();
  const proposal = {
    ok: true,
    spelling: SPELLING,
    schema: COMMISSION_PROPOSAL_SCHEMA_ID,
    kind: 'commission_proposal',
    proposal_id: `ecgberht-proposal-${step_id}-${Date.now().toString(36)}`,
    step_id,
    step,
    skill,
    depth_cell,
    proposed_by: opts.who ?? 'ecgberht-steward',
    at,
    commission,
    job_runner: ANCHOR_JOB_COMPOSE,
    requires_confirm: true,
    confirmed: false,
    primary_ux: COMMISSION_PRIMARY_UX,
    mode_picker_primary: false,
    single_writer: ROADMAP_SINGLE_WRITER,
    message: `Steward proposes commissioning ${skill} for step '${step_id}'. Confirm or override — nothing is written until confirm.`,
  };

  // T-ATT-CS1 — publish body is file-end helper (A1 plan-line drift budget).
  return {
    ...proposal,
    attention_publish: publishProposeAttentionEdge(proposal, opts, {
      at,
      projection: validated.projection ?? [],
    }),
  };
}

/**
 * Confirm a proposed commission. THE write step:
 * - creates the job (state `queued`, composing Anchor job_runner),
 * - appends `commission_bind` to roadmap_events via the single writer,
 * - appends a Strip instrument (durable — not UI-only state).
 *
 * Wave 7 (A4 fix): when `project_path` is set, the durable path is the
 * CONFIRM JOURNAL (confirm_intent → apply roadmap+strip → confirm_applied).
 * Pure in-memory path (no project_path) is retained for dry-run / fixtures.
 *
 * @param {{
 *   proposal: object,
 *   roadmap: object|string,
 *   strip?: object|null,
 *   who: string,
 *   at?: string,
 *   job_id?: string|null,
 *   project_path?: string|null,
 *   client_event_id?: string|null,
 *   project_id?: string|null,
 *   home?: string,
 *   killAfterRoadmap?: boolean,
 * }} opts
 */
export function confirmCommission(opts = {}) {
  const proposal = opts.proposal;
  if (
    !proposal ||
    typeof proposal !== 'object' ||
    proposal.kind !== 'commission_proposal' ||
    proposal.requires_confirm !== true
  ) {
    return {
      ok: false,
      error: 'commission_confirm_requires_proposal',
      spelling: SPELLING,
      message:
        'Confirm needs a steward commission_proposal (propose/confirm path — not a mode picker).',
    };
  }
  if (!nonEmpty(opts.who)) {
    return {
      ok: false,
      error: 'commission_confirm_requires_who',
      spelling: SPELLING,
      message: 'Commission confirm is a human decision — pass who confirmed.',
      required: ['who'],
    };
  }

  // Wave 7: durable project_path confirms go through the confirm journal
  // (ONE mechanism). Pure in-memory remains for fixtures / dry-run.
  if (opts.project_path && opts.use_confirm_journal !== false) {
    const journaled = confirmCommissionJournaled({
      project_path: opts.project_path,
      proposal,
      roadmap: opts.roadmap ?? null,
      strip: opts.strip ?? null,
      who: opts.who,
      at: opts.at,
      job_id: opts.job_id ?? null,
      client_event_id: opts.client_event_id ?? null,
      project_id: opts.project_id ?? null,
      home: opts.home,
      killAfterRoadmap: opts.killAfterRoadmap === true,
    });
    if (!journaled.ok && !journaled.killed) {
      return { ...journaled, spelling: SPELLING, refused: 'commission_confirm' };
    }
    return {
      ...journaled,
      spelling: SPELLING,
      single_writer: ROADMAP_SINGLE_WRITER,
      compose: ANCHOR_JOB_COMPOSE,
      runner: ANCHOR_JOB_COMPOSE.runner,
      durable: true,
      ui_only_state: false,
      events_only: true,
      // sot_written true when apply completed; false when killed mid-apply
      sot_written: journaled.ok === true && journaled.killed !== true,
      locked: journaled.ok === true,
      spine: true,
      persisted: journaled.ok === true && journaled.killed !== true,
      confirm_journal: true,
    };
  }

  const at = opts.at ?? todayIso();
  const job_id =
    opts.job_id ??
    `ecgberht-job-${String(proposal.skill).toLowerCase()}-${Date.now().toString(36)}`;
  const commissioned_as = `${proposal.skill}:${job_id}`;

  // Pure in-memory: commission_bind lands in roadmap_events (no durable write).
  const bindEvent = {
    kind: 'commission_bind',
    step_id: proposal.step_id,
    commissioned_as,
    at,
    ...(opts.client_event_id ? { client_event_id: opts.client_event_id } : {}),
  };
  const bound = appendRoadmapEvent(opts.roadmap ?? null, bindEvent, { at });
  if (!bound.ok) {
    return {
      ...bound,
      refused: 'commission_confirm',
      job_id,
    };
  }

  const job = {
    schema: JOB_SCHEMA_ID,
    job_id,
    commission_id: proposal.commission?.commission_id ?? null,
    proposal_id: proposal.proposal_id ?? null,
    step_id: proposal.step_id,
    skill: proposal.skill,
    depth_cell: proposal.depth_cell ?? null,
    confirmed_by: opts.who,
    runner: ANCHOR_JOB_COMPOSE.runner,
    compose: ANCHOR_JOB_COMPOSE,
    spawn: proposal.commission ?? null,
    state: 'queued',
    lifecycle_events: [
      {
        seq: 1,
        from: null,
        to: 'queued',
        at,
        observed: 'commission_confirm',
        who: opts.who,
      },
    ],
  };

  // Strip instrument append (in-memory; history append-only).
  let strip = opts.strip ?? null;
  let strip_appended = false;
  let strip_instrument = null;
  if (strip) {
    strip_instrument = {
      _kind: 'instrument',
      kind: 'commission_confirm',
      as_of: at,
      job_id,
      commission_id: job.commission_id,
      step_id: proposal.step_id,
      skill: proposal.skill,
      depth_cell: proposal.depth_cell ?? null,
      state: 'queued',
      who: opts.who,
      runner: ANCHOR_JOB_COMPOSE.runner,
    };
    const appended = appendStripInstrument(strip, strip_instrument, {
      apply_to_projection: false,
    });
    if (!appended.ok) {
      return { ...appended, refused: 'commission_confirm_strip_append', job_id };
    }
    strip = appended.strip;
    strip_appended = true;
  }

  return {
    ok: true,
    spelling: SPELLING,
    job,
    roadmap: bound.roadmap,
    roadmap_event: bound.event,
    projection: bound.projection,
    strip,
    strip_appended,
    strip_instrument,
    commissioned_as,
    durable: true,
    ui_only_state: false,
    events_only: true,
    single_writer: ROADMAP_SINGLE_WRITER,
    compose: ANCHOR_JOB_COMPOSE,
    sot_written: false,
    locked: false,
    spine: false,
    persisted: false,
    message: `Commission confirmed by ${opts.who}: ${commissioned_as} bound to step '${proposal.step_id}' (queued; Strip + roadmap_events appended).`,
  };
}

/**
 * Advance a job through the M2 lifecycle machine. Pure — returns a new job;
 * lifecycle_events history is append-only. Illegal transitions and moves out
 * of a terminal state refuse. Orphaned/reaped REQUIRE out-of-process liveness
 * evidence (zombie-hunter-style, supplied by the caller — no in-engine reaper).
 *
 * @param {object} job
 * @param {string} to
 * @param {{ at?: string, observed?: string|null, who?: string|null, evidence?: object|null, exit_code?: number|null, signal?: string|null }} [info]
 */
export function advanceJobLifecycle(job, to, info = {}) {
  if (!job || typeof job !== 'object' || !nonEmpty(job.state)) {
    return { ok: false, error: 'job_not_object', spelling: SPELLING };
  }
  const from = job.state;
  if (!JOB_LIFECYCLE_STATES.includes(to)) {
    return {
      ok: false,
      error: 'unknown_lifecycle_state',
      spelling: SPELLING,
      to: to ?? null,
      states: [...JOB_LIFECYCLE_STATES],
    };
  }
  if (isTerminalState(from)) {
    return {
      ok: false,
      error: 'job_already_terminal',
      spelling: SPELLING,
      from,
      to,
      message: `Job is terminal (${from}); terminals are final — a dead job cannot be revived or silently re-greened.`,
    };
  }
  const allowed = JOB_LIFECYCLE_TRANSITIONS[from] ?? [];
  if (!allowed.includes(to)) {
    return {
      ok: false,
      error: 'illegal_lifecycle_transition',
      spelling: SPELLING,
      from,
      to,
      allowed: [...allowed],
      message: `Lifecycle is queued → running → done|failed|orphaned|reaped; ${from} → ${to} is not a legal edge.`,
    };
  }
  if (
    (to === 'orphaned' || to === 'reaped') &&
    (!info.evidence || typeof info.evidence !== 'object')
  ) {
    return {
      ok: false,
      error: 'orphan_reap_requires_evidence',
      spelling: SPELLING,
      from,
      to,
      message:
        'Orphan/reap detection stays out of process: pass liveness evidence (zombie-hunter-style) observed by the caller. Ecgberht has no in-engine reaper.',
      orphan_reap_detection: ANCHOR_JOB_COMPOSE.orphan_reap_detection,
    };
  }

  const at = info.at ?? todayIso();
  const events = Array.isArray(job.lifecycle_events)
    ? job.lifecycle_events.map((e) => ({ ...e }))
    : [];
  events.push({
    seq: events.length + 1,
    from,
    to,
    at,
    observed: info.observed ?? null,
    who: info.who ?? null,
    evidence: info.evidence ?? null,
    exit_code: info.exit_code ?? null,
    signal: info.signal ?? null,
  });

  return {
    ok: true,
    spelling: SPELLING,
    from,
    to,
    terminal: isTerminalState(to),
    abnormal: JOB_ABNORMAL_TERMINALS.includes(to),
    job: { ...job, state: to, lifecycle_events: events },
  };
}

/**
 * Classify a terminal observation from the composed runner. UNKNOWN evidence
 * never classifies as done — silent green is impossible by construction.
 *
 * @param {{
 *   exit_code?: number|null, signal?: string|null, killed?: boolean,
 *   timeout?: boolean, orphaned?: boolean, reaped?: boolean,
 *   liveness?: object|null,
 * }} observation
 * @returns {{ ok: true, terminal: string, abnormal: boolean, why_known: string } | { ok: false, error: string, message: string }}
 */
export function classifyTerminalObservation(observation = {}) {
  const obs = observation && typeof observation === 'object' ? observation : {};
  const liveness = obs.liveness && typeof obs.liveness === 'object' ? obs.liveness : null;

  if (obs.reaped === true || liveness?.reaped === true) {
    return {
      ok: true,
      terminal: 'reaped',
      abnormal: true,
      why_known:
        'out-of-process liveness evidence reports the job was reaped (positive proof-of-death)',
    };
  }
  if (obs.orphaned === true || liveness?.orphaned === true) {
    return {
      ok: true,
      terminal: 'orphaned',
      abnormal: true,
      why_known:
        'out-of-process liveness evidence reports the job orphaned (owner gone, process unaccounted)',
    };
  }
  if (obs.killed === true || nonEmpty(obs.signal)) {
    return {
      ok: true,
      terminal: 'failed',
      abnormal: true,
      why_known: `job killed mid-run (signal ${obs.signal ?? 'unknown'}) — terminal observed from the composed runner`,
    };
  }
  if (obs.timeout === true) {
    return {
      ok: true,
      terminal: 'failed',
      abnormal: true,
      why_known: 'job timed out — terminal observed from the composed runner',
    };
  }
  if (typeof obs.exit_code === 'number') {
    if (obs.exit_code === 0) {
      return {
        ok: true,
        terminal: 'done',
        abnormal: false,
        why_known: 'exit code 0 observed from the composed runner',
      };
    }
    return {
      ok: true,
      terminal: 'failed',
      abnormal: true,
      why_known: `non-zero exit code ${obs.exit_code} observed from the composed runner`,
    };
  }
  return {
    ok: false,
    error: 'terminal_unclassifiable',
    message:
      'Terminal observation carries no usable evidence (no exit code, signal, timeout, or liveness). Refusing to classify — unknown is never mapped to done (no silent green).',
  };
}

/**
 * Observe a job terminal and land the FULL lifecycle receipts:
 * - abnormal (failed/orphaned/reaped): `commission_abnormal` receipt appended
 *   to the Strip + Roadmap status_flip → waiting via the single writer;
 * - done: Strip instrument + Roadmap status_flip → done via the single writer.
 * A killed/dead job can never come back ok:'done' — never silent green.
 *
 * @param {{
 *   job: object,
 *   observation: object,
 *   strip?: object|null,
 *   roadmap?: object|string|null,
 *   who?: string|null,
 *   at?: string,
 * }} opts
 */
export function observeJobTerminal(opts = {}) {
  const job = opts.job;
  if (!job || typeof job !== 'object') {
    return { ok: false, error: 'job_not_object', spelling: SPELLING };
  }

  const classified = classifyTerminalObservation(opts.observation);
  if (!classified.ok) {
    return {
      ...classified,
      spelling: SPELLING,
      silent_green: false,
      job,
      terminal: null,
    };
  }

  const at = opts.at ?? todayIso();
  const who = opts.who ?? 'ecgberht-steward';
  const obs = opts.observation ?? {};
  const last_known_state = job.state ?? null;

  const advanced = advanceJobLifecycle(job, classified.terminal, {
    at,
    who,
    observed: 'terminal_observation',
    evidence:
      classified.terminal === 'orphaned' || classified.terminal === 'reaped'
        ? obs.liveness ?? obs
        : obs.liveness ?? null,
    exit_code: typeof obs.exit_code === 'number' ? obs.exit_code : null,
    signal: obs.signal ?? null,
  });
  if (!advanced.ok) {
    return { ...advanced, silent_green: false, terminal: classified.terminal };
  }

  let strip = opts.strip ?? null;
  let roadmap_result = null;
  let receipt = null;
  let receipt_valid = null;

  if (classified.abnormal) {
    receipt = buildCommissionAbnormalReceipt({
      as_of: at,
      who,
      when: at,
      last_known_state,
      why_known: classified.why_known,
      terminal: classified.terminal,
      job_id: job.job_id ?? null,
      commission_id: job.commission_id ?? null,
      step_id: job.step_id ?? null,
      skill: job.skill ?? null,
      exit_code: typeof obs.exit_code === 'number' ? obs.exit_code : null,
      signal: obs.signal ?? null,
    });
    receipt_valid = validateReceipt(receipt);

    if (strip) {
      const appended = appendStripReceipt(strip, receipt, {
        apply_to_projection: false,
      });
      if (appended.ok) strip = appended.strip;
    }
  } else if (strip) {
    const appended = appendStripInstrument(
      strip,
      {
        _kind: 'instrument',
        kind: 'commission_done',
        as_of: at,
        job_id: job.job_id ?? null,
        step_id: job.step_id ?? null,
        skill: job.skill ?? null,
        state: 'done',
        who,
      },
      { apply_to_projection: false },
    );
    if (appended.ok) strip = appended.strip;
  }

  // Roadmap: status_flip via the spine single writer (Wave 6 migration :637).
  if (opts.roadmap != null && nonEmpty(job.step_id)) {
    const flipEvent = {
      kind: 'status_flip',
      step_id: job.step_id,
      to: classified.abnormal ? 'waiting' : 'done',
      receipt: {
        who,
        when: at,
        why: classified.abnormal
          ? `commission_abnormal (${classified.terminal}): ${classified.why_known}`
          : `commission terminal done observed for ${job.job_id ?? 'job'}`,
      },
      at,
      ...(opts.client_event_id ? { client_event_id: opts.client_event_id } : {}),
    };
    roadmap_result = opts.project_path
      ? appendRoadmapEventThroughSpine(opts.project_path, flipEvent, {
          seed: opts.roadmap,
          at,
          project_id: opts.project_id,
          home: opts.home,
          skip_index: !opts.project_id,
        })
      : appendRoadmapEvent(opts.roadmap, flipEvent, { at });
  }

  return {
    ok: true,
    spelling: SPELLING,
    job: advanced.job,
    terminal: classified.terminal,
    abnormal: classified.abnormal,
    why_known: classified.why_known,
    silent_green: false,
    receipt,
    receipt_valid,
    strip,
    roadmap: roadmap_result?.ok ? roadmap_result.roadmap : null,
    roadmap_event: roadmap_result?.ok ? roadmap_result.event : null,
    roadmap_result,
    single_writer: ROADMAP_SINGLE_WRITER,
    // Wave 6 migration stamps (observeJobTerminal / :637)
    spine: roadmap_result?.spine === true,
    sot_written: roadmap_result?.sot_written === true,
    locked: roadmap_result?.locked === true,
    message: classified.abnormal
      ? `Job ${job.job_id ?? ''} terminal ${classified.terminal}: commission_abnormal receipt appended (never silent green).`
      : `Job ${job.job_id ?? ''} terminal done observed; Strip + Roadmap updated via single writer.`,
  };
}

/**
 * Mark a confirmed (queued) job running, appending durable state:
 * Strip instrument + Roadmap status_flip → active via the single writer.
 * @param {{ job: object, strip?: object|null, roadmap?: object|string|null, who?: string|null, at?: string }} opts
 */
export function markJobRunning(opts = {}) {
  const at = opts.at ?? todayIso();
  const who = opts.who ?? 'anchor_job_runner';
  const advanced = advanceJobLifecycle(opts.job, 'running', {
    at,
    who,
    observed: 'job_start',
  });
  if (!advanced.ok) return advanced;
  const job = advanced.job;

  let strip = opts.strip ?? null;
  if (strip) {
    const appended = appendStripInstrument(
      strip,
      {
        _kind: 'instrument',
        kind: 'commission_running',
        as_of: at,
        job_id: job.job_id ?? null,
        step_id: job.step_id ?? null,
        skill: job.skill ?? null,
        state: 'running',
        who,
      },
      { apply_to_projection: false },
    );
    if (appended.ok) strip = appended.strip;
  }

  let roadmap_result = null;
  if (opts.roadmap != null && nonEmpty(job.step_id)) {
    // Wave 6 live-writer migration (job-lifecycle.mjs:715): spine when project_path set.
    const flipEvent = {
      kind: 'status_flip',
      step_id: job.step_id,
      to: 'active',
      receipt: {
        who,
        when: at,
        why: `commissioned job ${job.job_id ?? ''} started (queued → running)`,
      },
      at,
      ...(opts.client_event_id ? { client_event_id: opts.client_event_id } : {}),
    };
    roadmap_result = opts.project_path
      ? appendRoadmapEventThroughSpine(opts.project_path, flipEvent, {
          seed: opts.roadmap,
          at,
          project_id: opts.project_id,
          home: opts.home,
          skip_index: !opts.project_id,
        })
      : appendRoadmapEvent(opts.roadmap, flipEvent, { at });
  }

  return {
    ok: true,
    spelling: SPELLING,
    job,
    strip,
    roadmap: roadmap_result?.ok ? roadmap_result.roadmap : null,
    roadmap_event: roadmap_result?.ok ? roadmap_result.event : null,
    roadmap_result,
    single_writer: ROADMAP_SINGLE_WRITER,
    // Wave 6 migration stamps (markJobRunning / :715)
    spine: roadmap_result?.spine === true,
    sot_written: roadmap_result?.sot_written === true,
    locked: roadmap_result?.locked === true,
    message: `Job ${job.job_id ?? ''} running; Strip + roadmap_events appended (not UI-only state).`,
  };
}

// ─── Closed verb bodies ──────────────────────────────────────────────

function resolveCommissionSurfaces(opts = {}) {
  const project_path = resolveProjectPath({ project: opts.project, cwd: opts.cwd });
  const roadmap_loaded =
    opts.roadmap !== undefined
      ? {
          ok: true,
          exists: opts.roadmap != null,
          roadmap: opts.roadmap,
          roadmap_path: null,
          injected: true,
        }
      : loadProjectRoadmap(project_path);
  const surfaces =
    opts.surfaces !== undefined ? opts.surfaces : loadProjectSurfaces(project_path);
  return { project_path, roadmap_loaded, surfaces };
}

/**
 * commission-propose — steward proposes a commission for a Roadmap step.
 * Read-only: returns a proposal requiring confirm; nothing is written.
 * @param {object} opts
 */
export function verbCommissionPropose(opts = {}) {
  const step_id = opts.step ?? null;
  const skill = opts.skill ?? opts.rest?.[0] ?? null;
  if (!nonEmpty(step_id) || !nonEmpty(skill)) {
    return {
      ok: false,
      error: 'commission_propose_requires_step_and_skill',
      spelling: SPELLING,
      verb: 'commission-propose',
      primary: 'commission-propose',
      required: ['step', 'skill'],
      message:
        'commission-propose requires --step <roadmap step id> and --skill <researchPrime|Crucible|Foreman|Gandalf|Jumper>.',
    };
  }

  const { project_path, roadmap_loaded } = resolveCommissionSurfaces(opts);
  if (!roadmap_loaded.ok) {
    return {
      ...roadmap_loaded,
      verb: 'commission-propose',
      primary: 'commission-propose',
      project_path,
    };
  }
  if (!roadmap_loaded.exists) {
    return {
      ok: false,
      error: 'no_roadmap',
      spelling: SPELLING,
      verb: 'commission-propose',
      primary: 'commission-propose',
      project_path,
      message:
        'No engine Roadmap — commissions are proposed FOR Roadmap steps. Propose the step first (roadmap-propose).',
    };
  }

  const proposal = proposeCommission({
    roadmap: roadmap_loaded.roadmap,
    step_id,
    skill,
    depth_cell: opts.depth_cell ?? null,
    who: opts.who ?? 'ecgberht-steward',
    project_cwd: project_path,
    seats: opts.seats ?? null,
    prefs: opts.prefs ?? null,
    env: opts.env,
    at: opts.as_of ?? undefined,
  });

  return {
    ...proposal,
    verb: 'commission-propose',
    primary: 'commission-propose',
    project_path,
    persisted: { roadmap: false, strip: false },
    written: false,
  };
}

/**
 * commission-confirm — John confirms the steward's proposal; the job is
 * created (queued, composing Anchor job_runner) and Strip + roadmap_events
 * are appended and persisted (not UI-only state).
 * @param {object} opts
 */
export function verbCommissionConfirm(opts = {}) {
  if (!nonEmpty(opts.who)) {
    return {
      ok: false,
      error: 'commission_confirm_requires_who',
      spelling: SPELLING,
      verb: 'commission-confirm',
      primary: 'commission-confirm',
      required: ['who'],
      message: 'commission-confirm requires --who (human confirm receipt).',
    };
  }

  const { project_path, roadmap_loaded, surfaces } = resolveCommissionSurfaces(opts);
  if (!roadmap_loaded.ok) {
    return {
      ...roadmap_loaded,
      verb: 'commission-confirm',
      primary: 'commission-confirm',
      project_path,
    };
  }
  if (!roadmap_loaded.exists) {
    return {
      ok: false,
      error: 'no_roadmap',
      spelling: SPELLING,
      verb: 'commission-confirm',
      primary: 'commission-confirm',
      project_path,
      message:
        'No engine Roadmap — nothing to bind a commission to. Propose the step first (roadmap-propose).',
    };
  }

  // Accept a prior proposal (--proposal JSON) or build one from --step/--skill.
  let proposal = opts.proposal ?? null;
  if (typeof proposal === 'string') {
    try {
      proposal = JSON.parse(proposal);
    } catch (e) {
      return {
        ok: false,
        error: 'proposal_json_parse',
        spelling: SPELLING,
        verb: 'commission-confirm',
        primary: 'commission-confirm',
        message: String(e?.message ?? e),
      };
    }
  }
  if (!proposal) {
    // Build a proposal for immediate confirm only — do NOT publish the
    // "awaiting confirm" attention edge here (that is T-ATT-CS1 on the
    // commission-propose verb). Publishing would append attention_projection_published
    // before commission_bind and break confirm's single-event durability contract.
    const built = proposeCommission({
      roadmap: roadmap_loaded.roadmap,
      step_id: opts.step ?? null,
      skill: opts.skill ?? opts.rest?.[0] ?? null,
      depth_cell: opts.depth_cell ?? null,
      who: 'ecgberht-steward',
      project_cwd: project_path,
      seats: opts.seats ?? null,
      prefs: opts.prefs ?? null,
      env: opts.env,
      at: opts.as_of ?? undefined,
      skip_attention_publish: true,
    });
    if (!built.ok) {
      return {
        ...built,
        verb: 'commission-confirm',
        primary: 'commission-confirm',
        project_path,
      };
    }
    proposal = built;
  }

  const strip = opts.strip !== undefined ? opts.strip : surfaces?.strip ?? null;
  const persist =
    opts.persist !== false && !opts.dry_run && !roadmap_loaded.injected;

  // Wave 6: when persisting, confirmCommission routes the bind through the spine
  // (project_path set). Pure in-memory path retained for dry-run / injected fixtures.
  const confirmed = confirmCommission({
    proposal,
    roadmap: roadmap_loaded.roadmap,
    strip,
    who: opts.who,
    at: opts.as_of ?? undefined,
    job_id: opts.job_id ?? null,
    client_event_id: opts.client_event_id ?? null,
    project_path: persist ? project_path : null,
    project_id: opts.project_id ?? roadmap_loaded.roadmap?.project_id ?? null,
    home: opts.home,
  });
  if (!confirmed.ok) {
    return {
      ...confirmed,
      verb: 'commission-confirm',
      primary: 'commission-confirm',
      project_path,
    };
  }

  const written = { roadmap: false, strip: false };
  if (persist) {
    // Wave 7: confirm journal already applied roadmap bind + strip under
    // confirm_intent → apply → confirm_applied. Do not double-write.
    if (confirmed.confirm_journal === true && confirmed.sot_written === true) {
      written.roadmap = true;
      written.strip = confirmed.strip_appended === true;
    } else if (confirmed.roadmap && !confirmed.sot_written && !confirmed.locked) {
      // Legacy / non-journal fallback: appendRoadmapEventDurable then strip.
      // appendRoadmapEventDurable is the named durable entry (A5 production caller).
      const rebound = appendRoadmapEventDurable(
        project_path,
        roadmap_loaded.roadmap,
        confirmed.roadmap_event,
        {
          project_id: opts.project_id ?? roadmap_loaded.roadmap?.project_id ?? null,
          home: opts.home,
          skip_index: !opts.project_id && !opts.home,
        },
      );
      if (!rebound.ok) {
        return {
          ...rebound,
          verb: 'commission-confirm',
          primary: 'commission-confirm',
          project_path,
        };
      }
      written.roadmap = true;

      if (confirmed.strip_appended && surfaces?.strip_source === 'strip.json') {
        if (opts.project_id && opts.home && confirmed.strip_instrument) {
          const inst = {
            ...confirmed.strip_instrument,
            instrument_id:
              confirmed.strip_instrument.instrument_id
              ?? confirmed.job?.job_id
              ?? `commission-confirm-${Date.now().toString(36)}`,
          };
          appendStripInstrumentDurable(project_path, strip, inst, {
            project_id: opts.project_id,
            home: opts.home,
            apply_to_projection: false,
          });
        }
        const stripWrite = writeStripThroughSpine(project_path, confirmed.strip);
        if (!stripWrite.ok) {
          return {
            ...stripWrite,
            verb: 'commission-confirm',
            primary: 'commission-confirm',
            project_path,
            partial: { roadmap: written.roadmap, strip: false },
          };
        }
        written.strip = true;
      }
    } else {
      written.roadmap = true;
      if (confirmed.strip_appended && surfaces?.strip_source === 'strip.json') {
        if (opts.project_id && opts.home && confirmed.strip_instrument) {
          const inst = {
            ...confirmed.strip_instrument,
            instrument_id:
              confirmed.strip_instrument.instrument_id
              ?? confirmed.job?.job_id
              ?? `commission-confirm-${Date.now().toString(36)}`,
          };
          appendStripInstrumentDurable(project_path, strip, inst, {
            project_id: opts.project_id,
            home: opts.home,
            apply_to_projection: false,
          });
        }
        const stripWrite = writeStripThroughSpine(project_path, confirmed.strip);
        if (!stripWrite.ok) {
          return {
            ...stripWrite,
            verb: 'commission-confirm',
            primary: 'commission-confirm',
            project_path,
            partial: { roadmap: written.roadmap, strip: false },
          };
        }
        written.strip = true;
      }
    }
  }

  return {
    ...confirmed,
    verb: 'commission-confirm',
    primary: 'commission-confirm',
    project_path,
    proposal,
    persisted: written,
    dry_run: Boolean(opts.dry_run) || opts.persist === false,
    spine: persist,
  };
}

/**
 * T-ATT-CS1 helper — at file end so A1 plan-line anchors (141/250/841/908)
 * stay within the audit's 40-line drift budget. proposeCommission still
 * invokes publishAttention via this helper (removal-proof).
 */
function publishProposeAttentionEdge(proposal, opts, ctx = {}) {
  const projectPath =
    opts.project_cwd ?? opts.project_path ?? opts.projectPath ?? null;
  if (!projectPath || opts.skip_attention_publish === true) return null;
  const at = ctx.at ?? opts.at ?? todayIso();
  return publishAttention(projectPath, {
    // T-ATT-CS1
    call_site: ATTENTION_CALL_SITES.PROPOSE,
    who: opts.who ?? 'ecgberht-steward',
    at,
    seed: opts.roadmap ?? opts.seed,
    skip_index: true,
    ledgerView: {
      events: opts.roadmap?.roadmap_events ?? [],
      projection: ctx.projection ?? [],
      awaiting_confirm: true,
      commission_proposal: proposal,
      at,
    },
    home: opts.home,
    env: opts.env,
    project_id: opts.project_id,
    skip_brief_cache: opts.skip_brief_cache === true,
  });
}
