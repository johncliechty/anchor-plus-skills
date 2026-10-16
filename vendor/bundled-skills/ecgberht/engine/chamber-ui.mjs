/**
 * Wave 18 — Chamber UI: steps, proposals, confirmations, artifacts, corrections
 * (+ I52 scaffold-exemption renderer refusal — Master-Plan P10).
 *
 * Reviewable campaign surface composed from existing engine law:
 *   - steps view ← confirmed roadmap + Wave-13 per-step status
 *   - proposal/confirm ← hash-bound verbs (scaffold batch, commission, next-stage)
 *   - artifact view ← packet-view classifyArtifact / buildArtifactCard
 *     with I52: scaffold NEVER wears commissioned-artifact chrome; card
 *     NEVER renders without a bundle hash
 *   - artifact path reads ← Wave-7 resolveContainedPath (T-CON-18)
 *   - correction ← typed spoken correction → NEW VERSION propose → confirm
 *   - reflection receipts + deterministic next-stage proposals as typed
 *     conversation artifacts (never persisted chat)
 *   - every new chamber poller adopts the high-seat.js:485-528 pattern BY NAME
 *
 * G2 spike PASS (artifacts/g2-artifact-spike-verdict.json): no plan-shaped
 * renderer scope addition. Stdlib only. No host-absolute paths.
 */

import {
  classifyArtifact,
  buildArtifactCard,
} from './packet-view.mjs';
import {
  resolveContainedPath,
  DOSSIER_CODE,
} from './commission-dossier.mjs';
import {
  loadProjectRoadmap,
  buildRoadmapProjection,
  ROADMAP_STEP_STATUSES,
} from './roadmap.mjs';
import {
  hashScaffoldPayload,
  recomputeProposalHash as recomputeScaffoldHash,
  SCAFFOLD_PROPOSAL_SCHEMA,
} from './scaffolding.mjs';
import {
  recomputeProposalHash as recomputeCommissionHash,
  COMMISSION_PROPOSAL_SCHEMA,
} from './commission-proposal.mjs';
import {
  emitReflectionReceipt,
  proposeNextStageDeterministic,
  REFLECTION_RECEIPT_SCHEMA,
  NEXT_STAGE_PROPOSAL_SCHEMA,
} from './handback-ingest.mjs';
import { normalizeClaimedWho, WHO_PROVENANCE } from './identity-policy.mjs';

// ── Schemas / surfaces ─────────────────────────────────────────────────────

export const CHAMBER_UI_SCHEMA = 'ecgberht-chamber-ui-v0';
export const ARTIFACT_CORRECTION_SCHEMA = 'ecgberht-artifact-correction-v0';
export const COMMISSIONED_ARTIFACT_CHROME = 'commissioned-artifact-card';

/** Chamber surfaces named by the frozen failure table. */
export const CHAMBER_SURFACES = Object.freeze([
  'steps_view',
  'proposal_confirm',
  'artifact_view',
  'receipt_render',
]);

/** Human labels for surface placeholders in failure text. */
export const CHAMBER_SURFACE_LABEL = Object.freeze({
  steps_view: 'Steps view',
  proposal_confirm: 'Proposal/confirm',
  artifact_view: 'Artifact view',
  receipt_render: 'Receipt render',
});

// ── Failure-state table (chamber surfaces — Master-Plan P10 / Wave 18) ─────

export const CHAMBER_CODE = Object.freeze({
  DEP_MISSING: 'CHAMBER_DEP_MISSING',
  DEP_DEAD: 'CHAMBER_DEP_DEAD',
  DEP_GARBAGE: 'CHAMBER_DEP_GARBAGE',
  STORE_UNREADABLE: 'CHAMBER_STORE_UNREADABLE',
  PATH_REFUSED: 'CHAMBER_PATH_REFUSED',
  EMPTY: 'CHAMBER_EMPTY',
  STATE_UNKNOWN: 'CHAMBER_STATE_UNKNOWN',
  /** I52 renderer refusal (not in the 7-row table; named refusal). */
  SCAFFOLD_EXEMPT: 'CHAMBER_SCAFFOLD_EXEMPT',
  /** Artifact card refused — no bundle hash. */
  BUNDLE_HASH_REQUIRED: 'CHAMBER_BUNDLE_HASH_REQUIRED',
  /** Post-render mutation on hash-bound confirm. */
  CONFIRM_HASH_MISMATCH: 'confirm-hash-mismatch',
});

/**
 * Plan-verbatim failure text templates. `<surface>` is filled by surface label.
 * path-escape-refused is surface-invariant (plan table).
 */
export const CHAMBER_TEXT = Object.freeze({
  [CHAMBER_CODE.DEP_MISSING]:
    '<surface>: its data source is not available — shown as unavailable, not blank.',
  [CHAMBER_CODE.DEP_DEAD]:
    '<surface>: the data source stopped responding — last good state shown with its age.',
  [CHAMBER_CODE.DEP_GARBAGE]:
    '<surface>: the data source returned something unreadable — shown as an error, nothing invented.',
  [CHAMBER_CODE.STORE_UNREADABLE]:
    '<surface>: backing store unreadable — content withheld rather than guessed.',
  [CHAMBER_CODE.PATH_REFUSED]:
    'Artifact path escapes the project root — refused, not rendered.',
  [CHAMBER_CODE.EMPTY]:
    '<surface>: nothing here yet.',
  [CHAMBER_CODE.STATE_UNKNOWN]:
    '<surface>: state unknown — reported as unknown, distinct from empty.',
  [CHAMBER_CODE.SCAFFOLD_EXEMPT]:
    'Scaffold steps and scaffold_proposal cannot wear commissioned-artifact card chrome.',
  [CHAMBER_CODE.BUNDLE_HASH_REQUIRED]:
    'Artifact card refused — a commissioned artifact must carry a bundle hash.',
  [CHAMBER_CODE.CONFIRM_HASH_MISMATCH]:
    'Proposal content changed after render — confirm refused (confirm-hash-mismatch).',
});

/** State name → code map for the plan failure table. */
export const CHAMBER_STATE_TO_CODE = Object.freeze({
  'dependency-missing': CHAMBER_CODE.DEP_MISSING,
  'dependency-slow-or-killed': CHAMBER_CODE.DEP_DEAD,
  'dependency-returns-garbage': CHAMBER_CODE.DEP_GARBAGE,
  'backing-store-unreadable': CHAMBER_CODE.STORE_UNREADABLE,
  'path-escape-refused': CHAMBER_CODE.PATH_REFUSED,
  'empty-but-valid': CHAMBER_CODE.EMPTY,
  unknown: CHAMBER_CODE.STATE_UNKNOWN,
});

/**
 * Fill the `<surface>` placeholder in failure text.
 * @param {string} code
 * @param {string} surface one of CHAMBER_SURFACES
 * @returns {string}
 */
export function chamberUserText(code, surface) {
  const template = CHAMBER_TEXT[code] ?? CHAMBER_TEXT[CHAMBER_CODE.STATE_UNKNOWN];
  if (code === CHAMBER_CODE.PATH_REFUSED) return template;
  const label =
    CHAMBER_SURFACE_LABEL[surface] ??
    (typeof surface === 'string' && surface.trim() ? surface : 'Chamber surface');
  return template.replace(/<surface>/g, label);
}

/**
 * Full failure table — every surface × every plan failure state with distinct
 * codes and text. empty never borrows unreadable's text; unknown ≠ empty.
 * @returns {ReadonlyArray<object>}
 */
export function chamberFailureTable() {
  const states = Object.keys(CHAMBER_STATE_TO_CODE);
  const rows = [];
  for (const surface of CHAMBER_SURFACES) {
    for (const state of states) {
      const status_code = CHAMBER_STATE_TO_CODE[state];
      rows.push(
        Object.freeze({
          surface,
          state,
          status_code,
          user_text: chamberUserText(status_code, surface),
        }),
      );
    }
  }
  return Object.freeze(rows);
}

/**
 * Build a structured failure for a chamber surface.
 * @param {string} surface
 * @param {string} state plan state name or CHAMBER_CODE value
 * @param {object} [extra]
 */
export function chamberFailure(surface, state, extra = {}) {
  const code =
    CHAMBER_STATE_TO_CODE[state] ??
    (Object.values(CHAMBER_CODE).includes(state) ? state : CHAMBER_CODE.STATE_UNKNOWN);
  const text = chamberUserText(code, surface);
  return Object.freeze({
    ok: false,
    surface,
    state:
      Object.entries(CHAMBER_STATE_TO_CODE).find(([, c]) => c === code)?.[0] ??
      state,
    code,
    status_code: code,
    text,
    user_text: text,
    message: text,
    ...extra,
  });
}

// ── Poller discipline (high-seat.js:485-528 pattern BY NAME) ───────────────

/**
 * Chamber poll constants — same shape as ECG_HS_MIN_MS / ECG_HS_MAX_MS.
 * Named for import by latency / poller-audit tests. Do not rename.
 */
export const ECG_CHAMBER_MIN_MS = 90000;
export const ECG_CHAMBER_MAX_MS = 15 * 60 * 1000;

/** Pattern markers required on every new chamber poller (by name). */
export const CHAMBER_POLLER_PATTERN = Object.freeze({
  source_lines: 'static/high-seat.js:485-528',
  visibility_gating: 'document.hidden',
  visibility_event: 'visibilitychange',
  pagehide_cleanup: 'pagehide',
  min_interval_name: 'ECG_CHAMBER_MIN_MS',
  max_interval_name: 'ECG_CHAMBER_MAX_MS',
  geometric_backoff: 'Math.pow(2',
  min_ms: ECG_CHAMBER_MIN_MS,
  max_ms: ECG_CHAMBER_MAX_MS,
});

/**
 * Parse a millisecond assignment from client JS source (product forms ok).
 * @param {string} src
 * @param {string} name
 * @returns {number}
 */
function parseClientMsAssignment(src, name) {
  const re = new RegExp(
    String.raw`\b${name}\s*=\s*([0-9]+(?:\s*\*\s*[0-9]+)*)`,
  );
  const m = src.match(re);
  if (!m) return NaN;
  const factors = m[1].split(/\s*\*\s*/).map((p) => Number(p));
  if (factors.length === 0 || factors.some((n) => !Number.isFinite(n))) return NaN;
  return factors.reduce((acc, n) => acc * n, 1);
}

/**
 * Import chamber poll constants from static client source.
 * @param {string} sourceText
 * @returns {Readonly<{ MIN_MS: number, MAX_MS: number, ok: boolean }>}
 */
export function importChamberPollConstants(sourceText) {
  const src = String(sourceText ?? '');
  const MIN_MS = (() => {
    const named = parseClientMsAssignment(src, 'ECG_CHAMBER_MIN_MS');
    if (Number.isFinite(named)) return named;
    return parseClientMsAssignment(src, 'MIN_MS');
  })();
  const MAX_MS = (() => {
    const named = parseClientMsAssignment(src, 'ECG_CHAMBER_MAX_MS');
    if (Number.isFinite(named)) return named;
    return parseClientMsAssignment(src, 'MAX_MS');
  })();
  return Object.freeze({
    MIN_MS,
    MAX_MS,
    ok: Number.isFinite(MIN_MS) && Number.isFinite(MAX_MS) && MIN_MS > 0,
    one_poll_definition: 'one healthy visible-tab interval (MIN_MS)',
    failure_backoff_may_reach_MAX_MS: true,
    hidden_tab_polls_skip: true,
  });
}

/**
 * Audit a chamber client source for the named high-seat poller pattern.
 * Verifies visibility gating, minimum interval, geometric backoff, pagehide cleanup.
 * Every new setInterval / setTimeout poller must pass.
 *
 * @param {string} sourceText
 * @returns {Readonly<object>}
 */
export function auditChamberPoller(sourceText) {
  const src = String(sourceText ?? '');
  const constants = importChamberPollConstants(src);
  const hasVisibility =
    /document\.hidden/.test(src) && /visibilitychange/.test(src);
  const hasPagehide = /pagehide/.test(src);
  const hasBackoff = /Math\.pow\s*\(\s*2/.test(src);
  const hasMinName =
    /ECG_CHAMBER_MIN_MS/.test(src) ||
    (/\bMIN_MS\b/.test(src) && constants.ok);
  const hasMaxName =
    /ECG_CHAMBER_MAX_MS/.test(src) ||
    (/\bMAX_MS\b/.test(src) && constants.ok);
  // setInterval is allowed only if the named pattern wraps it; pure fixed-rate
  // setInterval without hidden/backoff is a failure. Prefer setTimeout schedule.
  const bareSetInterval = /setInterval\s*\(/.test(src);
  const usesNamedSchedule =
    /setTimeout\s*\(/.test(src) ||
    (bareSetInterval && hasVisibility && hasBackoff);
  const ok =
    constants.ok &&
    hasVisibility &&
    hasPagehide &&
    hasBackoff &&
    hasMinName &&
    hasMaxName &&
    usesNamedSchedule &&
    constants.MIN_MS === ECG_CHAMBER_MIN_MS;

  return Object.freeze({
    ok,
    pattern: CHAMBER_POLLER_PATTERN.source_lines,
    visibility_gating: hasVisibility,
    min_interval: constants.MIN_MS,
    max_interval: constants.MAX_MS,
    geometric_backoff: hasBackoff,
    pagehide_cleanup: hasPagehide,
    named_constants: hasMinName && hasMaxName,
    constants,
    bare_setInterval_without_gating: bareSetInterval && !(hasVisibility && hasBackoff),
    failures: [
      !constants.ok && 'poll-constants-unparseable',
      !hasVisibility && 'missing-visibility-gating',
      !hasPagehide && 'missing-pagehide-cleanup',
      !hasBackoff && 'missing-geometric-backoff',
      !hasMinName && 'missing-min-interval-name',
      bareSetInterval && !(hasVisibility && hasBackoff) && 'bare-setInterval',
      constants.ok &&
        constants.MIN_MS !== ECG_CHAMBER_MIN_MS &&
        'min-interval-mismatch',
    ].filter(Boolean),
  });
}

// ── Steps view ─────────────────────────────────────────────────────────────

/**
 * Map a roadmap projection step into a chamber steps-view row.
 * Status comes from Wave-13 status-ingestion / roadmap projection (never invented).
 * @param {object} step
 * @param {number} index
 */
export function mapStepRow(step, index = 0) {
  const id = step?.id ?? step?.step_id ?? null;
  const name = step?.name ?? null;
  const status = step?.status ?? null;
  const knownStatus =
    status != null && ROADMAP_STEP_STATUSES.includes(String(status));
  return Object.freeze({
    index,
    id,
    name,
    status: knownStatus ? String(status) : status == null ? null : String(status),
    status_known: knownStatus,
    done_when: step?.done_when ?? null,
    waiting_on: step?.waiting_on ?? null,
    commissioned_as: step?.commissioned_as ?? null,
    is_scaffold:
      step?.steward_authored === true ||
      step?.kind === 'scaffold' ||
      step?.step_kind === 'scaffold' ||
      String(step?.status ?? '') === 'proposed',
  });
}

/**
 * Chamber steps view: confirmed roadmap with per-step status.
 *
 * @param {{
 *   project_path?: string,
 *   roadmap?: object|null,
 *   projection?: object|null,
 *   status_by_step?: Record<string, string>|null,
 *   inject?: object,
 *   failure?: string|null,
 * }} [opts]
 */
export function buildStepsView(opts = {}) {
  const surface = 'steps_view';

  if (opts.failure) {
    return chamberFailure(surface, opts.failure, {
      view: 'steps',
      steps: [],
    });
  }

  // Dependency missing — no project and no inject.
  if (
    !opts.project_path &&
    !opts.roadmap &&
    !opts.projection &&
    !opts.inject?.steps
  ) {
    return chamberFailure(surface, 'dependency-missing', {
      view: 'steps',
      steps: [],
    });
  }

  let roadmap = opts.roadmap ?? null;
  let projection = opts.projection ?? null;

  if (opts.inject?.steps) {
    const statusMap =
      opts.status_by_step ?? opts.inject?.status_by_step ?? null;
    const steps = opts.inject.steps.map((s, i) => {
      const row = mapStepRow(s, i);
      if (statusMap && row.id != null && statusMap[row.id] != null) {
        const st = String(statusMap[row.id]);
        return Object.freeze({
          ...row,
          status: st,
          status_known: ROADMAP_STEP_STATUSES.includes(st),
          status_source: 'wave13-status-ingestion',
        });
      }
      return row;
    });
    if (steps.length === 0) {
      return Object.freeze({
        ok: true,
        surface,
        view: 'steps',
        empty: true,
        status_code: CHAMBER_CODE.EMPTY,
        user_text: chamberUserText(CHAMBER_CODE.EMPTY, surface),
        steps: Object.freeze([]),
        step_count: 0,
      });
    }
    return Object.freeze({
      ok: true,
      surface,
      view: 'steps',
      empty: false,
      steps: Object.freeze(steps),
      step_count: steps.length,
      source: statusMap ? 'inject+wave13' : 'inject',
    });
  }

  if (opts.project_path && !roadmap && !projection) {
    try {
      const loaded = loadProjectRoadmap(opts.project_path);
      if (!loaded.ok && loaded.exists) {
        return chamberFailure(surface, 'backing-store-unreadable', {
          view: 'steps',
          steps: [],
          detail: loaded.message ?? loaded.error,
        });
      }
      if (!loaded.exists) {
        return Object.freeze({
          ok: true,
          surface,
          view: 'steps',
          empty: true,
          status_code: CHAMBER_CODE.EMPTY,
          user_text: chamberUserText(CHAMBER_CODE.EMPTY, surface),
          steps: Object.freeze([]),
          step_count: 0,
          source: 'roadmap-missing',
        });
      }
      roadmap = loaded.roadmap;
    } catch (e) {
      return chamberFailure(surface, 'backing-store-unreadable', {
        view: 'steps',
        steps: [],
        detail: String(e?.message ?? e),
      });
    }
  }

  if (roadmap && !projection) {
    try {
      projection = buildRoadmapProjection(roadmap.events ?? roadmap.roadmap_events ?? []);
    } catch (e) {
      return chamberFailure(surface, 'dependency-returns-garbage', {
        view: 'steps',
        steps: [],
        detail: String(e?.message ?? e),
      });
    }
  }

  if (projection && typeof projection !== 'object') {
    return chamberFailure(surface, 'dependency-returns-garbage', {
      view: 'steps',
      steps: [],
    });
  }

  const rawSteps = Array.isArray(projection?.steps)
    ? projection.steps
    : Array.isArray(roadmap?.projection?.steps)
      ? roadmap.projection.steps
      : [];

  // Wave-13 status overlay when provided (status_by_step[id] wins).
  const statusMap = opts.status_by_step ?? opts.inject?.status_by_step ?? null;
  const steps = rawSteps.map((s, i) => {
    const row = mapStepRow(s, i);
    if (statusMap && row.id != null && statusMap[row.id] != null) {
      const st = String(statusMap[row.id]);
      return Object.freeze({
        ...row,
        status: st,
        status_known: ROADMAP_STEP_STATUSES.includes(st),
        status_source: 'wave13-status-ingestion',
      });
    }
    return row;
  });

  if (steps.length === 0) {
    return Object.freeze({
      ok: true,
      surface,
      view: 'steps',
      empty: true,
      status_code: CHAMBER_CODE.EMPTY,
      user_text: chamberUserText(CHAMBER_CODE.EMPTY, surface),
      steps: Object.freeze([]),
      step_count: 0,
      source: 'projection',
    });
  }

  return Object.freeze({
    ok: true,
    surface,
    view: 'steps',
    empty: false,
    steps: Object.freeze(steps),
    step_count: steps.length,
    source: statusMap ? 'roadmap+wave13' : 'roadmap',
  });
}

// ── Proposal + confirm surface ─────────────────────────────────────────────

/**
 * Estimate / spend block shown BEFORE confirm (never spent until confirm).
 * @param {object} proposal
 */
export function extractSpendPreview(proposal) {
  const estimate = proposal?.estimate ?? proposal?.rendering?.estimate ?? null;
  const cost_usd =
    estimate?.cost_usd ??
    proposal?.rendering?.estimate_usd ??
    proposal?.cost_usd ??
    null;
  const tokens =
    estimate?.tokens ??
    proposal?.rendering?.estimate_tokens ??
    proposal?.tokens ??
    null;
  const depth =
    proposal?.depth_cell ??
    proposal?.rendering?.depth ??
    proposal?.depth ??
    null;
  const skill = proposal?.skill ?? proposal?.rendering?.skill ?? null;
  const seat =
    proposal?.seat ??
    proposal?.seats ??
    proposal?.rendering?.seat ??
    null;
  return Object.freeze({
    will_spend_before_confirm: true,
    cost_usd,
    tokens,
    depth,
    skill,
    seat,
    summary:
      proposal?.rendering?.summary ??
      (skill
        ? `Will spend on ${skill}${depth ? ` @ ${depth}` : ''}${cost_usd != null ? ` (~$${cost_usd})` : ''} only after confirm.`
        : proposal?.kind === 'scaffold_proposal'
          ? 'Scaffolding batch-confirm: compiles already debited under the live envelope; confirm commits steps, not new model spend.'
          : 'Spend shown before confirm; nothing runs until hash-bound confirm.'),
  });
}

/**
 * Detect proposal kind for confirm wiring.
 * @param {object} proposal
 */
export function classifyProposalKind(proposal) {
  if (!proposal || typeof proposal !== 'object') return 'unknown';
  const kind = String(proposal.kind ?? '');
  if (
    kind === 'scaffold_proposal' ||
    proposal.schema === SCAFFOLD_PROPOSAL_SCHEMA
  ) {
    return 'scaffold_batch_confirm';
  }
  if (
    kind === 'commission_proposal' ||
    proposal.schema === COMMISSION_PROPOSAL_SCHEMA
  ) {
    return 'commission_confirm';
  }
  if (
    kind === 'next_stage_proposal' ||
    proposal.schema === NEXT_STAGE_PROPOSAL_SCHEMA
  ) {
    return 'next_stage_confirm';
  }
  if (
    kind === 'artifact_correction_proposal' ||
    proposal.schema === ARTIFACT_CORRECTION_SCHEMA
  ) {
    return 'correction_confirm';
  }
  return kind || 'unknown';
}

/**
 * Recompute content hash for a rendered proposal (TOCTOU / double-click guard).
 * @param {object} proposal
 * @returns {string|null}
 */
export function recomputeAnyProposalHash(proposal) {
  if (!proposal || typeof proposal !== 'object') return null;
  const kind = classifyProposalKind(proposal);
  try {
    if (kind === 'scaffold_batch_confirm') {
      return recomputeScaffoldHash(proposal);
    }
    if (kind === 'commission_confirm') {
      return recomputeCommissionHash(proposal);
    }
    if (kind === 'correction_confirm') {
      // Must match correctionHashBody used at propose time.
      return hashScaffoldPayload(
        correctionHashBody({
          lineage_id: proposal.lineage_id,
          prior_version: proposal.prior_version,
          prior_bundle_hash: proposal.prior_bundle_hash,
          correction_text: proposal.correction_text,
          new_version: proposal.new_version,
          artifact_path: proposal.artifact_path ?? null,
        }),
      );
    }
    if (kind === 'next_stage_confirm') {
      // Prefer stamped content_hash; else hash the stable emitter fields.
      if (proposal.content_hash) return String(proposal.content_hash);
      return hashScaffoldPayload({
        schema: proposal.schema,
        kind: proposal.kind,
        step_id: proposal.step_id ?? null,
        next_step_id: proposal.next_step_id ?? null,
        why: proposal.why ?? null,
        requires_confirm: true,
        confirmed: false,
      });
    }
    if (proposal.content_hash) {
      return String(proposal.content_hash);
    }
    const {
      proposal_hash: _ph,
      confirmed: _cf,
      proposal_id: _pid,
      who_proposed: _who,
      prior_addressable: _prior,
      at: _at,
      ok: _ok,
      ...rest
    } = proposal;
    return hashScaffoldPayload(rest);
  } catch {
    return null;
  }
}

/**
 * Proposal + confirm surface for scaffolding batch-confirm, commission
 * confirmation, and next-stage proposals. Shows spend before confirm;
 * wires to hash-bound confirm (double-click cannot double-commit;
 * post-render mutation → confirm-hash-mismatch).
 *
 * @param {{
 *   proposal?: object|null,
 *   failure?: string|null,
 *   last_good?: object|null,
 *   last_good_age_ms?: number|null,
 * }} [opts]
 */
export function buildProposalConfirmSurface(opts = {}) {
  const surface = 'proposal_confirm';

  if (opts.failure === 'dependency-slow-or-killed' || opts.failure === CHAMBER_CODE.DEP_DEAD) {
    return chamberFailure(surface, 'dependency-slow-or-killed', {
      view: 'proposal_confirm',
      last_good: opts.last_good ?? null,
      last_good_age_ms: opts.last_good_age_ms ?? null,
    });
  }
  if (opts.failure) {
    return chamberFailure(surface, opts.failure, { view: 'proposal_confirm' });
  }

  const proposal = opts.proposal;
  if (proposal === undefined || proposal === null) {
    return Object.freeze({
      ok: true,
      surface,
      view: 'proposal_confirm',
      empty: true,
      status_code: CHAMBER_CODE.EMPTY,
      user_text: chamberUserText(CHAMBER_CODE.EMPTY, surface),
      proposal: null,
      confirm: null,
    });
  }

  if (typeof proposal !== 'object' || Array.isArray(proposal)) {
    return chamberFailure(surface, 'dependency-returns-garbage', {
      view: 'proposal_confirm',
    });
  }

  const kind = classifyProposalKind(proposal);
  const spend = extractSpendPreview(proposal);
  const expected_hash =
    proposal.proposal_hash ??
    proposal.content_hash ??
    recomputeAnyProposalHash(proposal);

  return Object.freeze({
    ok: true,
    surface,
    view: 'proposal_confirm',
    empty: false,
    proposal_kind: kind,
    proposal,
    spend,
    confirm: Object.freeze({
      hash_bound: true,
      expected_hash,
      proposal_hash: expected_hash,
      idempotent: true,
      double_click_safe: true,
      post_render_mutation_surfaces: CHAMBER_CODE.CONFIRM_HASH_MISMATCH,
      requires_confirm: proposal.requires_confirm !== false && proposal.confirmed !== true,
      confirmed: proposal.confirmed === true,
      who_policy: WHO_PROVENANCE,
    }),
  });
}

/**
 * Apply a hash-bound confirm against a rendered proposal.
 * Double-submit with the same client_event_id is idempotent (caller tracks).
 * Post-render mutation of proposal content → confirm-hash-mismatch.
 *
 * @param {{
 *   proposal: object,
 *   proposal_hash?: string,
 *   client_event_id?: string,
 *   who?: object|string,
 *   prior_confirms?: Set<string>|string[],
 * }} opts
 */
export function confirmProposalHashBound(opts = {}) {
  const proposal = opts.proposal;
  if (!proposal || typeof proposal !== 'object') {
    return chamberFailure('proposal_confirm', 'dependency-missing', {
      error: 'proposal-required',
    });
  }

  const expected = recomputeAnyProposalHash(proposal);
  const provided =
    opts.proposal_hash ?? proposal.proposal_hash ?? proposal.content_hash ?? '';

  if (!expected || !provided || expected !== provided) {
    return Object.freeze({
      ok: false,
      surface: 'proposal_confirm',
      state: 'confirm-hash-mismatch',
      code: CHAMBER_CODE.CONFIRM_HASH_MISMATCH,
      status_code: CHAMBER_CODE.CONFIRM_HASH_MISMATCH,
      error: 'confirm-hash-mismatch',
      text: CHAMBER_TEXT[CHAMBER_CODE.CONFIRM_HASH_MISMATCH],
      user_text: CHAMBER_TEXT[CHAMBER_CODE.CONFIRM_HASH_MISMATCH],
      message: CHAMBER_TEXT[CHAMBER_CODE.CONFIRM_HASH_MISMATCH],
      expected_hash: expected,
      provided_hash: provided || null,
      committed: false,
    });
  }

  const client_event_id =
    opts.client_event_id ??
    `confirm-${proposal.proposal_id ?? expected.slice(0, 16)}`;

  const prior = opts.prior_confirms;
  const priorSet =
    prior instanceof Set
      ? prior
      : new Set(Array.isArray(prior) ? prior : []);

  if (priorSet.has(client_event_id)) {
    return Object.freeze({
      ok: true,
      surface: 'proposal_confirm',
      idempotent_replay: true,
      committed: false,
      already_committed: true,
      client_event_id,
      proposal_hash: expected,
      message: 'Double-click / re-submit: already committed once; no second commit.',
    });
  }

  const who = normalizeClaimedWho(opts.who ?? 'john');

  return Object.freeze({
    ok: true,
    surface: 'proposal_confirm',
    idempotent_replay: false,
    committed: true,
    already_committed: false,
    client_event_id,
    proposal_hash: expected,
    proposal_kind: classifyProposalKind(proposal),
    who,
    who_provenance: WHO_PROVENANCE,
    message: 'Hash-bound confirm accepted — single commit.',
  });
}

// ── Artifact view + I52 scaffold exemption ─────────────────────────────────

/**
 * Kinds that must NEVER wear commissioned-artifact card chrome (I52 / P10).
 * @param {object|string|null} artifact
 * @returns {boolean}
 */
export function isScaffoldExempt(artifact) {
  if (artifact == null) return false;
  if (typeof artifact === 'string') {
    const s = artifact.toLowerCase();
    return (
      s === 'scaffold_proposal' ||
      s === 'scaffold' ||
      s.includes('scaffold_proposal')
    );
  }
  const kind = String(artifact.kind ?? artifact.card_kind ?? artifact.type ?? '');
  if (
    kind === 'scaffold_proposal' ||
    kind === 'scaffold' ||
    kind === 'scaffold_step' ||
    artifact.schema === SCAFFOLD_PROPOSAL_SCHEMA
  ) {
    return true;
  }
  // Explicit scaffold markers always exempt (I52).
  if (artifact.is_scaffold === true) return true;
  if (artifact.step_kind === 'scaffold') return true;
  if (artifact.scaffold_proposal === true) return true;
  if (artifact.steward_authored === true && String(artifact.status ?? '') === 'proposed') {
    return true;
  }
  if (Array.isArray(artifact.steps) && artifact.requires_batch_confirm === true) {
    // scaffold_proposal shape
    return kind === 'scaffold_proposal' || artifact.schema === SCAFFOLD_PROPOSAL_SCHEMA;
  }
  return false;
}

/**
 * Extract bundle hash from an artifact reference.
 * @param {object|null} artifact
 * @returns {string|null}
 */
export function extractBundleHash(artifact) {
  if (!artifact || typeof artifact !== 'object') return null;
  const h =
    artifact.bundle_hash ??
    artifact.bundleHash ??
    artifact.content_hash ??
    artifact.handback?.bundle_hash ??
    null;
  if (h == null || String(h).trim() === '') return null;
  return String(h);
}

/**
 * I52 + bundle-hash gate: render a commissioned artifact card via
 * packet-view classifyArtifact / buildArtifactCard.
 *
 * REFUSES:
 *   - scaffold step / scaffold_proposal in commissioned-artifact chrome
 *   - any artifact card without a bundle hash
 *
 * @param {object|null} artifact
 * @param {{ project_path?: string, force_chrome?: string }} [opts]
 */
export function renderCommissionedArtifactCard(artifact, opts = {}) {
  const surface = 'artifact_view';

  if (artifact == null) {
    return Object.freeze({
      ok: true,
      surface,
      empty: true,
      status_code: CHAMBER_CODE.EMPTY,
      user_text: chamberUserText(CHAMBER_CODE.EMPTY, surface),
      chrome: null,
      card: null,
      refused: false,
    });
  }

  // I52: scaffold can NEVER wear commissioned-artifact card chrome.
  if (isScaffoldExempt(artifact)) {
    return Object.freeze({
      ok: false,
      surface,
      refused: true,
      refusal: 'scaffold-exempt',
      code: CHAMBER_CODE.SCAFFOLD_EXEMPT,
      status_code: CHAMBER_CODE.SCAFFOLD_EXEMPT,
      text: CHAMBER_TEXT[CHAMBER_CODE.SCAFFOLD_EXEMPT],
      user_text: CHAMBER_TEXT[CHAMBER_CODE.SCAFFOLD_EXEMPT],
      message: CHAMBER_TEXT[CHAMBER_CODE.SCAFFOLD_EXEMPT],
      chrome: null,
      chrome_refused: COMMISSIONED_ARTIFACT_CHROME,
      card: null,
      kind: artifact.kind ?? 'scaffold_proposal',
    });
  }

  const bundle_hash = extractBundleHash(artifact);
  if (!bundle_hash) {
    return Object.freeze({
      ok: false,
      surface,
      refused: true,
      refusal: 'bundle-hash-required',
      code: CHAMBER_CODE.BUNDLE_HASH_REQUIRED,
      status_code: CHAMBER_CODE.BUNDLE_HASH_REQUIRED,
      text: CHAMBER_TEXT[CHAMBER_CODE.BUNDLE_HASH_REQUIRED],
      user_text: CHAMBER_TEXT[CHAMBER_CODE.BUNDLE_HASH_REQUIRED],
      message: CHAMBER_TEXT[CHAMBER_CODE.BUNDLE_HASH_REQUIRED],
      chrome: null,
      card: null,
    });
  }

  const refPath = artifact.path ?? artifact.ref ?? artifact.rel ?? null;
  const classified = classifyArtifact(refPath);
  const baseCard = buildArtifactCard({
    path: refPath,
    title: artifact.title ?? artifact.name ?? refPath,
    note: artifact.note ?? null,
    provenance: artifact.provenance ?? [],
  });

  // Commissioned chrome wraps the packet-view card with the required hash.
  const card = Object.freeze({
    ...baseCard,
    chrome: COMMISSIONED_ARTIFACT_CHROME,
    bundle_hash,
    classified,
    artifact_id: artifact.artifact_id ?? artifact.id ?? null,
    version: artifact.version ?? artifact.version_id ?? 1,
    lineage_id: artifact.lineage_id ?? artifact.artifact_id ?? artifact.id ?? null,
  });

  return Object.freeze({
    ok: true,
    surface,
    refused: false,
    empty: false,
    chrome: COMMISSIONED_ARTIFACT_CHROME,
    card,
    bundle_hash,
    classified,
  });
}

/**
 * Artifact view assembly — path containment (T-CON-18) + I52 card render.
 *
 * @param {{
 *   project_path?: string,
 *   artifact?: object|null,
 *   rel?: string|null,
 *   failure?: string|null,
 * }} [opts]
 */
export function buildArtifactView(opts = {}) {
  const surface = 'artifact_view';

  if (opts.failure === 'path-escape-refused' || opts.failure === CHAMBER_CODE.PATH_REFUSED) {
    return chamberFailure(surface, 'path-escape-refused', {
      view: 'artifact',
      card: null,
    });
  }
  if (opts.failure) {
    return chamberFailure(surface, opts.failure, { view: 'artifact', card: null });
  }

  const project_path = opts.project_path ?? null;
  const rel = opts.rel ?? opts.artifact?.path ?? opts.artifact?.rel ?? null;

  // Contained-path resolve when both root and candidate are present.
  if (project_path && rel) {
    const resolved = resolveChamberArtifactPath(project_path, rel);
    if (!resolved.ok) {
      return resolved; // already CHAMBER_PATH_REFUSED shaped
    }
  }

  if (!opts.artifact && !rel) {
    return Object.freeze({
      ok: true,
      surface,
      view: 'artifact',
      empty: true,
      status_code: CHAMBER_CODE.EMPTY,
      user_text: chamberUserText(CHAMBER_CODE.EMPTY, surface),
      card: null,
    });
  }

  const artifact = opts.artifact ?? { path: rel };
  return renderCommissionedArtifactCard(artifact, { project_path });
}

/**
 * T-CON-18: chamber artifact path through Wave-7 contained resolver.
 * Escape → CHAMBER_PATH_REFUSED with plan-verbatim text.
 *
 * @param {string} projectRoot
 * @param {string} candidate
 * @param {object} [opts]
 */
export function resolveChamberArtifactPath(projectRoot, candidate, opts = {}) {
  const r = resolveContainedPath(projectRoot, candidate, opts);
  if (r.ok) {
    return Object.freeze({
      ok: true,
      abs: r.abs,
      rel: r.rel,
      contained: true,
    });
  }
  return Object.freeze({
    ok: false,
    surface: 'artifact_view',
    state: 'path-escape-refused',
    code: CHAMBER_CODE.PATH_REFUSED,
    status_code: CHAMBER_CODE.PATH_REFUSED,
    text: CHAMBER_TEXT[CHAMBER_CODE.PATH_REFUSED],
    user_text: CHAMBER_TEXT[CHAMBER_CODE.PATH_REFUSED],
    message: CHAMBER_TEXT[CHAMBER_CODE.PATH_REFUSED],
    error: 'path-escape-refused',
    dossier_code: r.code ?? DOSSIER_CODE.PATH_REFUSED,
    reason: r.reason ?? null,
    candidate: r.candidate ?? candidate,
  });
}

// ── Correction path (new version via propose → confirm) ────────────────────

/**
 * Canonical hash body for an artifact-correction proposal (excludes hash field).
 * @param {object} body
 */
export function correctionHashBody(body) {
  return {
    schema: ARTIFACT_CORRECTION_SCHEMA,
    kind: 'artifact_correction_proposal',
    lineage_id: body.lineage_id,
    prior_version: body.prior_version,
    prior_bundle_hash: body.prior_bundle_hash,
    correction_text: body.correction_text,
    new_version: body.new_version,
    artifact_path: body.artifact_path ?? null,
    requires_confirm: true,
    confirmed: false,
  };
}

/**
 * Typed spoken correction → NEW VERSION proposal (hash-bound).
 * Prior version remains addressable via lineage_id + prior_version + prior_bundle_hash.
 *
 * @param {{
 *   artifact: object,
 *   correction_text: string,
 *   who?: object|string,
 *   at?: string,
 * }} opts
 */
export function proposeArtifactCorrection(opts = {}) {
  const surface = 'proposal_confirm';
  const artifact = opts.artifact;
  const text = opts.correction_text;

  if (!artifact || typeof artifact !== 'object') {
    return chamberFailure(surface, 'dependency-missing', {
      error: 'artifact-required-for-correction',
    });
  }
  if (text == null || String(text).trim() === '') {
    return chamberFailure(surface, 'empty-but-valid', {
      error: 'correction-text-empty',
      message: 'Correction text is empty — nothing proposed.',
    });
  }

  // Scaffold cannot be "corrected" into commissioned chrome via this path.
  if (isScaffoldExempt(artifact)) {
    return Object.freeze({
      ok: false,
      surface,
      code: CHAMBER_CODE.SCAFFOLD_EXEMPT,
      status_code: CHAMBER_CODE.SCAFFOLD_EXEMPT,
      text: CHAMBER_TEXT[CHAMBER_CODE.SCAFFOLD_EXEMPT],
      user_text: CHAMBER_TEXT[CHAMBER_CODE.SCAFFOLD_EXEMPT],
      message: 'Cannot open a correction version path on a scaffold proposal.',
      refused: true,
    });
  }

  const prior_bundle_hash = extractBundleHash(artifact);
  if (!prior_bundle_hash) {
    return Object.freeze({
      ok: false,
      surface,
      code: CHAMBER_CODE.BUNDLE_HASH_REQUIRED,
      status_code: CHAMBER_CODE.BUNDLE_HASH_REQUIRED,
      text: CHAMBER_TEXT[CHAMBER_CODE.BUNDLE_HASH_REQUIRED],
      user_text: CHAMBER_TEXT[CHAMBER_CODE.BUNDLE_HASH_REQUIRED],
      message: 'Prior artifact has no bundle hash — correction refused.',
      refused: true,
    });
  }

  const lineage_id =
    artifact.lineage_id ?? artifact.artifact_id ?? artifact.id ?? `lineage-${prior_bundle_hash.slice(0, 12)}`;
  const prior_version = Number(artifact.version ?? artifact.version_id ?? 1);
  const new_version = prior_version + 1;
  const correction_text = String(text).trim();
  const at = opts.at ?? new Date().toISOString();

  const body = correctionHashBody({
    lineage_id,
    prior_version,
    prior_bundle_hash,
    correction_text,
    new_version,
    artifact_path: artifact.path ?? artifact.ref ?? null,
  });
  const proposal_hash = hashScaffoldPayload(body);

  const proposal = Object.freeze({
    ...body,
    proposal_id: `ecgberht-correction-${lineage_id}-v${new_version}-${proposal_hash.slice(0, 10)}`,
    proposal_hash,
    prior_addressable: Object.freeze({
      lineage_id,
      version: prior_version,
      bundle_hash: prior_bundle_hash,
      address: `${lineage_id}@v${prior_version}:${prior_bundle_hash.slice(0, 16)}`,
    }),
    who_proposed: normalizeClaimedWho(opts.who ?? 'john'),
    at,
  });

  return Object.freeze({
    ok: true,
    surface,
    proposal,
    proposal_hash,
    prior_addressable: proposal.prior_addressable,
    message:
      'NEW VERSION correction proposed — confirm with matching proposal_hash to commit.',
  });
}

/**
 * Confirm a correction proposal (hash-bound). Prior version stays addressable.
 *
 * @param {{
 *   proposal: object,
 *   proposal_hash?: string,
 *   client_event_id?: string,
 *   who?: object|string,
 *   prior_confirms?: Set<string>|string[],
 * }} opts
 */
export function confirmArtifactCorrection(opts = {}) {
  const bound = confirmProposalHashBound({
    ...opts,
    proposal: opts.proposal,
  });
  if (!bound.ok || bound.already_committed) {
    return bound;
  }

  const p = opts.proposal;
  const new_bundle_seed = hashScaffoldPayload({
    lineage_id: p.lineage_id,
    version: p.new_version,
    correction_text: p.correction_text,
    prior_bundle_hash: p.prior_bundle_hash,
  });

  const versioned = Object.freeze({
    lineage_id: p.lineage_id,
    version: p.new_version,
    bundle_hash: new_bundle_seed,
    correction_text: p.correction_text,
    prior: p.prior_addressable,
    path: p.artifact_path,
    kind: 'stage_artifact',
    schema: ARTIFACT_CORRECTION_SCHEMA,
  });

  return Object.freeze({
    ...bound,
    new_version: versioned,
    prior_still_addressable: true,
    prior: p.prior_addressable,
    message:
      'NEW VERSION landed hash-bound; prior version remains addressable by lineage@version:hash.',
  });
}

// ── Reflection receipts + next-stage as typed conversation artifacts ───────

/**
 * Render a reflection receipt or deterministic next-stage proposal into the
 * conversation as a TYPED ARTIFACT — never as persisted chat.
 *
 * @param {object} item receipt or proposal
 * @param {{ project_path?: string }} [opts]
 */
export function renderTypedConversationArtifact(item, opts = {}) {
  const surface = 'receipt_render';

  if (item == null) {
    return Object.freeze({
      ok: true,
      surface,
      empty: true,
      status_code: CHAMBER_CODE.EMPTY,
      user_text: chamberUserText(CHAMBER_CODE.EMPTY, surface),
      artifact: null,
      persisted_chat: false,
    });
  }

  if (typeof item !== 'object' || Array.isArray(item)) {
    return chamberFailure(surface, 'dependency-returns-garbage', {
      view: 'receipt_render',
      persisted_chat: false,
    });
  }

  const kind = String(item.kind ?? '');
  const isReceipt =
    kind === 'reflection_receipt' || item.schema === REFLECTION_RECEIPT_SCHEMA;
  const isNextStage =
    kind === 'next_stage_proposal' || item.schema === NEXT_STAGE_PROPOSAL_SCHEMA;

  if (!isReceipt && !isNextStage) {
    return chamberFailure(surface, 'unknown', {
      view: 'receipt_render',
      detail: `unrecognized kind: ${kind || '(none)'}`,
      persisted_chat: false,
    });
  }

  const content_hash =
    item.content_hash ??
    item.bundle_hash ??
    hashScaffoldPayload({
      kind: item.kind,
      schema: item.schema,
      step_id: item.step_id,
      at: item.at,
      message: item.message,
    });

  return Object.freeze({
    ok: true,
    surface,
    empty: false,
    persisted_chat: false,
    chat_turn_written: false,
    typed_artifact: true,
    artifact: Object.freeze({
      card: isReceipt ? 'reflection_receipt' : 'next_stage_proposal',
      kind: isReceipt ? 'reflection_receipt' : 'next_stage_proposal',
      schema: item.schema,
      chrome: 'typed-conversation-artifact',
      content_hash,
      bundle_hash: content_hash,
      zero_model: item.zero_model !== false,
      zero_spend: item.zero_spend !== false,
      gate_decision: item.gate_decision ?? 4,
      step_id: item.step_id ?? null,
      body: item,
      requires_confirm: isNextStage ? item.requires_confirm !== false : false,
      never_persisted_as_chat: true,
    }),
  });
}

/**
 * Build receipt-render surface from dossier/handback facts (deterministic emitters).
 * @param {{ dossier?: object, ledgerView?: object, failure?: string }} [opts]
 */
export function buildReceiptRenderSurface(opts = {}) {
  const surface = 'receipt_render';
  if (opts.failure) {
    return chamberFailure(surface, opts.failure, {
      view: 'receipt_render',
      persisted_chat: false,
    });
  }
  if (!opts.dossier && !opts.receipt && !opts.proposal) {
    return Object.freeze({
      ok: true,
      surface,
      empty: true,
      status_code: CHAMBER_CODE.EMPTY,
      user_text: chamberUserText(CHAMBER_CODE.EMPTY, surface),
      receipts: Object.freeze([]),
      persisted_chat: false,
    });
  }

  const out = [];
  if (opts.receipt) {
    out.push(renderTypedConversationArtifact(opts.receipt));
  }
  if (opts.proposal) {
    out.push(renderTypedConversationArtifact(opts.proposal));
  }
  if (opts.dossier) {
    const r = emitReflectionReceipt(opts.dossier, opts.ledgerView ?? {});
    if (r.ok) out.push(renderTypedConversationArtifact(r.receipt));
    const p = proposeNextStageDeterministic(opts.dossier, opts.ledgerView ?? {});
    if (p.ok) out.push(renderTypedConversationArtifact(p.proposal));
  }

  return Object.freeze({
    ok: true,
    surface,
    empty: out.length === 0,
    status_code: out.length === 0 ? CHAMBER_CODE.EMPTY : undefined,
    user_text:
      out.length === 0
        ? chamberUserText(CHAMBER_CODE.EMPTY, surface)
        : undefined,
    receipts: Object.freeze(out),
    persisted_chat: false,
    chat_turns: 0,
  });
}

// ── Full chamber UI assembly ───────────────────────────────────────────────

/**
 * Assemble the Wave-18 chamber UI surfaces for a project.
 *
 * @param {{
 *   project_path?: string,
 *   roadmap?: object,
 *   projection?: object,
 *   status_by_step?: object,
 *   proposal?: object,
 *   artifact?: object,
 *   dossier?: object,
 *   ledgerView?: object,
 *   inject?: object,
 * }} [opts]
 */
export function assembleChamberUi(opts = {}) {
  const steps = buildStepsView({
    project_path: opts.project_path,
    roadmap: opts.roadmap,
    projection: opts.projection,
    status_by_step: opts.status_by_step,
    inject: opts.inject,
    failure: opts.inject?.steps_failure,
  });

  const proposal_confirm = buildProposalConfirmSurface({
    proposal: opts.proposal ?? opts.inject?.proposal ?? null,
    failure: opts.inject?.proposal_failure,
    last_good: opts.inject?.proposal_last_good,
    last_good_age_ms: opts.inject?.proposal_last_good_age_ms,
  });

  const artifact_view = buildArtifactView({
    project_path: opts.project_path,
    artifact: opts.artifact ?? opts.inject?.artifact ?? null,
    rel: opts.inject?.artifact_rel,
    failure: opts.inject?.artifact_failure,
  });

  const receipt_render = buildReceiptRenderSurface({
    dossier: opts.dossier ?? opts.inject?.dossier,
    ledgerView: opts.ledgerView ?? opts.inject?.ledgerView,
    receipt: opts.inject?.receipt,
    proposal: opts.inject?.next_stage_proposal,
    failure: opts.inject?.receipt_failure,
  });

  return Object.freeze({
    ok: true,
    schema: CHAMBER_UI_SCHEMA,
    surfaces: Object.freeze({
      steps_view: steps,
      proposal_confirm,
      artifact_view,
      receipt_render,
    }),
    poller: Object.freeze({ ...CHAMBER_POLLER_PATTERN }),
    footer:
      'stage artifacts · steps · proposals · receipts render reviewably · scaffold never wears commissioned chrome · chat is not the store',
  });
}

/**
 * Inject a named failure behind a chamber surface (test helper / fault injection).
 * @param {string} surface
 * @param {string} state
 */
export function injectChamberFailure(surface, state) {
  return chamberFailure(surface, state);
}

/**
 * Distinctness proof: empty text ≠ unreadable text ≠ unknown text per surface.
 * @returns {{ ok: boolean, collisions: string[] }}
 */
export function assertFailureTextsDistinct() {
  const collisions = [];
  for (const surface of CHAMBER_SURFACES) {
    const empty = chamberUserText(CHAMBER_CODE.EMPTY, surface);
    const unreadable = chamberUserText(CHAMBER_CODE.STORE_UNREADABLE, surface);
    const unknown = chamberUserText(CHAMBER_CODE.STATE_UNKNOWN, surface);
    const garbage = chamberUserText(CHAMBER_CODE.DEP_GARBAGE, surface);
    const missing = chamberUserText(CHAMBER_CODE.DEP_MISSING, surface);
    const dead = chamberUserText(CHAMBER_CODE.DEP_DEAD, surface);
    const texts = [empty, unreadable, unknown, garbage, missing, dead];
    const set = new Set(texts);
    if (set.size !== texts.length) {
      collisions.push(surface);
    }
    if (empty === unreadable || empty === unknown || unreadable === unknown) {
      collisions.push(`${surface}:empty-unreadable-unknown-collision`);
    }
  }
  // path-escape is invariant and distinct from empty
  const pathText = CHAMBER_TEXT[CHAMBER_CODE.PATH_REFUSED];
  for (const surface of CHAMBER_SURFACES) {
    if (pathText === chamberUserText(CHAMBER_CODE.EMPTY, surface)) {
      collisions.push(`${surface}:path-empty-collision`);
    }
  }
  return { ok: collisions.length === 0, collisions };
}
