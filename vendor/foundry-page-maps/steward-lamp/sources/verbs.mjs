/**
 * Closed verb bodies (W3 + W4 depth table).
 * Dispatcher is closed-list only — no plugin/open dispatch.
 * Write authority: Face narrative rewrite; Strip append-only instruments/receipts.
 * depth-suggest: Strip signals + dispatch table only (LITE bias; no free-form).
 */

import fs from 'node:fs';
import { verbRefinementUpdate } from './refinement.mjs';
import { writeFileAtomicSync } from './durable-write.mjs';
import { appendRoadmapEventThroughSpine } from './ledger-spine.mjs';
import path from 'node:path';

import { SPELLING, resolvePrimaryVerb } from './verbs.mjs';
import {
  FACE_FILE_NAME,
  STRIP_FILE_NAME,
  loadProjectSurfaces,
  parseFaceDocument,
  parseStrip,
  resolveProjectPath,
  toStripProjection,
} from './face-strip.mjs';
import {
  rewriteFaceNarrative,
  mutateStripInPlace,
  appendStripInstrument,
  appendStripReceipt,
} from './write-authority.mjs';
import { overCap, missingSpine } from './write-authority.mjs';
import { discoverStrips } from './discovery.mjs';
import {
  rankPortfolioStripFirst,
  rankRequiredFullFace,
  scoreStripProjection,
} from './rank.mjs';
import {
  validateReceipt,
  buildGrasscatchReceipt,
  buildDepthReceipt,
  buildOverrideReceipt,
  isMonologueOnly,
  RECEIPT_SCHEMA_ID,
} from './receipt-validate.mjs';
import {
  suggestDepthFromStrip,
  applyDepthOverride,
  loadDispatchTable,
  DEFAULT_BIAS,
} from './dispatch-table.mjs';
import {
  loadProjectRoadmap,
  validateRoadmap,
  verbRoadmapShow,
  verbRoadmapPropose,
  verbRoadmapSet,
} from './roadmap.mjs';
import { verbBrief, precomputeBriefCache } from './brief.mjs';
import {
  verbCommissionPropose,
  verbCommissionConfirm,
} from './job-lifecycle.mjs';
import { verbSeatHop } from './seat-hop.mjs';

/** ISO date (YYYY-MM-DD) for instrument tips. */
function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Parse remaining argv into structured verb options.
 * @param {string[]} args
 */
import { deriveHorizon } from './horizon.mjs';
import { composeRepairProposal, openRepairProposals, planRepairApply, sameRepairSet } from './repair.mjs';
import { foldRefinements } from './refinement-state.mjs';

// W0 (2026-09-28): a wait's subject — a typed reference, never prose. `none` clears it.
const WAIT_REF_RE = /^(step:[^\s@]+|deliverable:[^\s@]+@[^\s@]+|decision:[^\s@]+|none)$/;
export function isWaitRef(value) {
  return typeof value === 'string' && WAIT_REF_RE.test(value.trim());
}

export function parseVerbArgs(args = []) {
  const tokens = Array.isArray(args) ? [...args] : [];
  const face_patch = {};
  const out = {
    roots: [],
    project: null,
    reason: null,
    deferred: null,
    handback_shape: null,
    suggested_later_owner: null,
    receipt: null,
    receipt_raw: null,
    top_k: 3,
    persist: true,
    dry_run: false,
    face_patch,
    step: null,
    name: null,
    status: null,
    from: null,
    done_when: null,
    waiting_on: null,
    due: null,
    ref: null,
    tier: null,
    area: null,
    commissioned_as: null,
    skill: null,
    depth_cell: null,
    proposal: null,
    job_id: null,
    seat: null,
    who: null,
    when: null,
    goal_reread: null,
    current_step_id: null,
    altitude: null,
    anchor_root: null,
    mark_seen: false,
    phase_b: false,
    cached: false,
    refresh: false,
    precompute: false,
    precompute_brief: false,
    rest: [],
  };

  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (t === '--roots' || t === '-R') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.roots.push(...splitList(next));
        i++;
      }
      continue;
    }
    if (t.startsWith('--roots=')) {
      out.roots.push(...splitList(t.slice('--roots='.length)));
      continue;
    }
    if (t === '--project' || t === '-p') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.project = next;
        i++;
      }
      continue;
    }
    if (t.startsWith('--project=')) {
      out.project = t.slice('--project='.length);
      continue;
    }
    if (t === '--reason' || t === '--why') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.reason = next;
        i++;
      }
      continue;
    }
    if (t.startsWith('--reason=') || t.startsWith('--why=')) {
      out.reason = t.includes('=') ? t.slice(t.indexOf('=') + 1) : null;
      continue;
    }
    if (t === '--deferred' || t === '--what') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.deferred = next;
        i++;
      }
      continue;
    }
    if (t.startsWith('--deferred=') || t.startsWith('--what=')) {
      out.deferred = t.slice(t.indexOf('=') + 1);
      continue;
    }
    if (t === '--handback-shape') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.handback_shape = tryParseJson(next) ?? next;
        i++;
      }
      continue;
    }
    if (t === '--owner' || t === '--suggested-later-owner') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.suggested_later_owner = next;
        i++;
      }
      continue;
    }
    if (t === '--receipt' || t === '--json') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.receipt_raw = next;
        out.receipt = tryParseJson(next);
        i++;
      }
      continue;
    }
    if (t.startsWith('--receipt=') || t.startsWith('--json=')) {
      const raw = t.slice(t.indexOf('=') + 1);
      out.receipt_raw = raw;
      out.receipt = tryParseJson(raw);
      continue;
    }
    if (t === '--receipt-file') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        try {
          const raw = fs.readFileSync(next, 'utf8');
          out.receipt_raw = raw;
          out.receipt = tryParseJson(raw);
        } catch (e) {
          out.receipt_error = String(e?.message ?? e);
        }
        i++;
      }
      continue;
    }
    if (t === '--top-k') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        const n = Number(next);
        if (Number.isFinite(n) && n > 0) out.top_k = n;
        i++;
      }
      continue;
    }
    if (t === '--dry-run') {
      out.dry_run = true;
      out.persist = false;
      continue;
    }
    if (t === '--no-persist') {
      out.persist = false;
      continue;
    }
    // Brief flags (TW2 — Decision Packet)
    if (t === '--mark-seen') {
      out.mark_seen = true;
      continue;
    }
    if (t === '--phase-b') {
      out.phase_b = true;
      continue;
    }
    if (t === '--cached') {
      out.cached = true;
      continue;
    }
    if (t === '--refresh') {
      out.refresh = true;
      continue;
    }
    if (t === '--precompute') {
      out.precompute = true;
      continue;
    }
    if (t === '--precompute-brief') {
      out.precompute_brief = true;
      continue;
    }
    const briefValueFlags = {
      '--altitude': 'altitude',
      '--anchor-root': 'anchor_root',
    };
    if (briefValueFlags[t]) {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out[briefValueFlags[t]] = next;
        i++;
      }
      continue;
    }
    {
      let matchedBriefEq = false;
      for (const [flag, key] of Object.entries(briefValueFlags)) {
        if (t.startsWith(`${flag}=`)) {
          out[key] = t.slice(flag.length + 1);
          matchedBriefEq = true;
          break;
        }
      }
      if (matchedBriefEq) continue;
    }
    // Roadmap flags (TW1 — roadmap-show / roadmap-propose / roadmap-set)
    const roadmapFlags = {
      '--step': 'step',
      '--id': 'step',
      '--name': 'name',
      '--status': 'status',
      '--to': 'status',
      '--from': 'from',
      '--done-when': 'done_when',
      '--waiting-on': 'waiting_on',
      '--due': 'due',
      '--ref': 'ref',
      '--tier': 'tier',
      '--area': 'area',
      '--commissioned-as': 'commissioned_as',
      '--who': 'who',
      '--when': 'when',
      '--goal-reread': 'goal_reread',
      '--current-step': 'current_step_id',
      // the active set (2026-09-29)
      '--active': 'active',
      '--active-order': 'active_order',
      '--seat-in': 'seat_in',
      '--seat-order': 'seat_order',
      '--pace': 'pace',
    };
    if (roadmapFlags[t]) {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out[roadmapFlags[t]] = next;
        i++;
      }
      continue;
    }
    {
      let matchedRoadmapEq = false;
      for (const [flag, key] of Object.entries(roadmapFlags)) {
        if (t.startsWith(`${flag}=`)) {
          out[key] = t.slice(flag.length + 1);
          matchedRoadmapEq = true;
          break;
        }
      }
      if (matchedRoadmapEq) continue;
    }
    // Commission flags (TW3 — commission-propose / commission-confirm)
    const commissionFlags = {
      '--skill': 'skill',
      '--depth-cell': 'depth_cell',
      '--depth': 'depth_cell',
      '--job-id': 'job_id',
    };
    if (commissionFlags[t]) {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out[commissionFlags[t]] = next;
        i++;
      }
      continue;
    }
    {
      let matchedCommissionEq = false;
      for (const [flag, key] of Object.entries(commissionFlags)) {
        if (t.startsWith(`${flag}=`)) {
          out[key] = t.slice(flag.length + 1);
          matchedCommissionEq = true;
          break;
        }
      }
      if (matchedCommissionEq) continue;
    }
    // Seat-hop flag (TW4 — titlebar seat switcher / CLI parity)
    if (t === '--seat') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.seat = next;
        i++;
      }
      continue;
    }
    if (t.startsWith('--seat=')) {
      out.seat = t.slice('--seat='.length);
      continue;
    }
    if (t === '--proposal') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.proposal = tryParseJson(next) ?? next;
        i++;
      }
      continue;
    }
    if (t.startsWith('--proposal=')) {
      const raw = t.slice('--proposal='.length);
      out.proposal = tryParseJson(raw) ?? raw;
      continue;
    }

    // Face narrative patch flags
    const faceFlags = {
      '--north-star': 'north_star',
      '--active-effort': 'active_effort',
      '--why-next': 'why_next',
      '--human-wait': 'human_wait',
      '--why-stakes': 'why_stakes',
    };
    if (faceFlags[t]) {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        face_patch[faceFlags[t]] = next;
        i++;
      }
      continue;
    }
    for (const [flag, key] of Object.entries(faceFlags)) {
      if (t.startsWith(`${flag}=`)) {
        face_patch[key] = t.slice(flag.length + 1);
        break;
      }
    }
    if (Object.keys(faceFlags).some((f) => t.startsWith(`${f}=`))) continue;

    // Strip projection tip fields via instrument (append path only)
    if (t === '--next-recommended') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.strip_tip = { ...(out.strip_tip || {}), next_recommended: next };
        i++;
      }
      continue;
    }
    if (t === '--strip-why-next') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.strip_tip = { ...(out.strip_tip || {}), why_next: next };
        i++;
      }
      continue;
    }
    if (t === '--phase') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.strip_tip = { ...(out.strip_tip || {}), phase: next };
        i++;
      }
      continue;
    }
    if (t === '--capacity') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.strip_tip = { ...(out.strip_tip || {}), capacity: next };
        i++;
      }
      continue;
    }
    // W0 (2026-09-28): a wait names its subject — `--wait-ref step:<sid>` · `deliverable:<row>@<version>` ·
    // `decision:<id>` · `none` (append path only, like the other tip fields)
    if (t === '--wait-ref') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.strip_tip = { ...(out.strip_tip || {}), wait_ref: next.trim() };   // stored trimmed (Grok W0): an exact join, never a padded token
        i++;
      }
      continue;
    }
    // W0: `--leave` appends a leave receipt (where he left this project: the step in hand, the last event and
    // its time, the effort) — his own act, recorded; never a step, never a status
    if (t === '--leave') {
      out.leave = true;
      continue;
    }
    if (t === '--leave-at') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.leave_at = next;
        i++;
      }
      continue;
    }
    // W3 (2026-09-28): `--horizon [--horizon-reason <word>]` derives the line from the plan and writes it, stamped
    if (t === '--horizon') {
      out.horizon = true;
      continue;
    }
    if (t === '--horizon-reason') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out.horizon_reason = next;
        i++;
      }
      continue;
    }

    // W4 (2026-09-28): repair as a proposal — `--repair-propose --after-step <id> [--after-presentation <id>]`
    // composes and appends the correction set after an acceptance (nothing changes); `--repair-resolve <proposal>
    // --disposition accepted|dismissed --who <name> [--why <text>]` is his word on it.
    if (t === '--repair-propose') {
      out.repair_propose = true;
      continue;
    }
    if (t === '--after-step' || t === '--after-presentation' || t === '--repair-resolve' || t === '--disposition') {
      const key = { '--after-step': 'after_step', '--after-presentation': 'after_presentation', '--repair-resolve': 'repair_resolve', '--disposition': 'disposition' }[t];
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        out[key] = next.trim();
        i++;
      }
      continue;
    }

    out.rest.push(t);
  }

  return out;
}

function splitList(token) {
  const delim = path.delimiter;
  let parts = token.split(delim).map((s) => s.trim()).filter(Boolean);
  if (parts.length === 1 && delim !== ',' && token.includes(',')) {
    parts = token.split(',').map((s) => s.trim()).filter(Boolean);
  }
  return parts;
}

function tryParseJson(s) {
  if (typeof s !== 'string') return s;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

/**
 * status — Strip-first pointer; Face only if needed for top-k display.
 * @param {object} opts
 */
export function verbStatus(opts = {}) {
  const roots = opts.roots ?? [];
  const top_k = opts.top_k ?? 3;

  // Portfolio status when roots provided
  if (roots.length > 0) {
    const discovered = discoverStrips({ roots, envValue: opts.envValue ?? null, env: opts.env });
    const ranked = rankPortfolioStripFirst(discovered.strips, { top_k });
    return {
      ok: true,
      spelling: SPELLING,
      verb: 'status',
      primary: 'status',
      mode: 'portfolio',
      strip_first: true,
      face_loads_for_status: 0,
      face_required_for_rank: false,
      active_effort: ranked.ranked[0]?.active_effort ?? null,
      human_wait: ranked.ranked[0]?.human_wait ?? null,
      next_recommended: ranked.ranked[0]?.next_recommended ?? null,
      why_next: ranked.ranked[0]?.why_next ?? null,
      portfolio: ranked,
      discovery: {
        empty: discovered.empty,
        count: discovered.strips.length,
        face_full_reads: discovered.face_full_reads,
      },
      message: 'Portfolio status from Strip projections only',
    };
  }

  const project_path = resolveProjectPath({
    project: opts.project,
    cwd: opts.cwd,
  });
  const surfaces = opts.surfaces ?? loadProjectSurfaces(project_path);
  if (!surfaces.strip && !surfaces.face) {
    return {
      ok: false,
      error: 'no_face_or_strip',
      spelling: SPELLING,
      verb: 'status',
      project_path,
      message: 'No Face or Strip found for status',
    };
  }

  const strip = surfaces.strip;
  const proj = strip ? toStripProjection(strip, { project_path, strip_source: surfaces.strip_source }) : null;

  // Face only when top-k display needs narrative color (optional single load)
  let face_display = null;
  let face_loaded = false;
  if (opts.include_face || opts.drill_face) {
    if (surfaces.face?.narrative) {
      face_display = surfaces.face.narrative;
      face_loaded = true;
    }
  }

  // TW1: Roadmap projection is engine truth. Face prose alone is an honest
  // gap (empty projection) — status never invents steps from narrative.
  let roadmap;
  const roadmapLoaded =
    opts.roadmap !== undefined
      ? { ok: true, exists: opts.roadmap != null, roadmap: opts.roadmap }
      : loadProjectRoadmap(project_path);
  if (roadmapLoaded.ok && roadmapLoaded.exists) {
    const validated = validateRoadmap(roadmapLoaded.roadmap, {
      allow_unevented_steps: true,
    });
    roadmap = validated.ok
      ? {
          present: true,
          valid: true,
          projection: validated.projection,
          steps_count: validated.steps_count,
          gap: null,
          invented_steps: false,
        }
      : {
          present: true,
          valid: false,
          projection: [],
          error: validated.error,
          drift: validated.drift,
          gap: 'roadmap_silent_rewrite',
          invented_steps: false,
        };
  } else {
    roadmap = {
      present: false,
      valid: null,
      projection: [],
      gap: surfaces.face ? 'face_prose_only' : 'no_roadmap',
      invented_steps: false,
    };
  }

  return {
    ok: true,
    spelling: SPELLING,
    verb: 'status',
    primary: 'status',
    mode: 'project',
    strip_first: true,
    project_path,
    strip_source: surfaces.strip_source,
    face_loaded,
    active_effort: proj?.active_effort ?? strip?.active_effort ?? null,
    human_wait: proj?.human_wait ?? strip?.human_wait ?? 'none',
    next_recommended: proj?.next_recommended ?? strip?.next_recommended ?? null,
    why_next: proj?.why_next ?? strip?.why_next ?? null,
    capacity: proj?.capacity ?? strip?.capacity ?? 'unknown',
    phase: proj?.phase ?? strip?.phase ?? null,
    negative_heartbeat: proj?.negative_heartbeat ?? strip?.negative_heartbeat ?? null,
    tool_depth_cell: strip?.tool_depth_cell ?? null,
    face_display,
    roadmap,
    pointer: {
      active_effort: proj?.active_effort ?? strip?.active_effort ?? null,
      human_wait: proj?.human_wait ?? strip?.human_wait ?? 'none',
      next_recommended: proj?.next_recommended ?? strip?.next_recommended ?? null,
      why_next: proj?.why_next ?? strip?.why_next ?? null,
    },
    message: 'Status from Strip-first pointer',
  };
}

/**
 * next — N=1 project path or portfolio strip-first rank + why.
 * Never full Face for portfolio rank.
 * @param {object} opts
 */
export function verbNext(opts = {}) {
  const roots = opts.roots ?? [];
  const top_k = opts.top_k ?? 3;

  if (roots.length > 0 || opts.portfolio === true) {
    const discovered = discoverStrips({
      roots: roots.length ? roots : undefined,
      envValue: opts.envValue,
      env: opts.env,
    });
    const ranked = rankPortfolioStripFirst(discovered.strips, { top_k });
    const face_used = rankRequiredFullFace(ranked);

    return {
      ok: true,
      spelling: SPELLING,
      verb: 'next',
      primary: 'next',
      mode: 'portfolio',
      strip_first: true,
      face_loads_for_rank: ranked.face_loads_for_rank,
      face_required_for_rank: face_used,
      next: ranked.ranked.slice(0, top_k).map((r) => ({
        project_id: r.project_id,
        project_path: r.project_path,
        next_recommended: r.next_recommended,
        why_next: r.why_next,
        active_effort: r.active_effort,
        human_wait: r.human_wait,
        score: r.score,
        reasons: r.reasons,
        capacity: r.capacity,
        face_loaded: false,
      })),
      ranked,
      discovery: {
        empty: discovered.empty,
        count: discovered.strips.length,
        face_full_reads: discovered.face_full_reads,
      },
      message: face_used
        ? 'ERROR: portfolio next consulted Face (should never)'
        : 'Portfolio next ranked strip-first without full Face load',
    };
  }

  // N=1 project path
  const project_path = resolveProjectPath({
    project: opts.project,
    cwd: opts.cwd,
  });
  const surfaces = opts.surfaces ?? loadProjectSurfaces(project_path);
  if (!surfaces.strip) {
    return {
      ok: false,
      error: 'no_strip',
      spelling: SPELLING,
      verb: 'next',
      project_path,
      message: 'N=1 next requires a Strip projection',
    };
  }

  const proj = toStripProjection(surfaces.strip, {
    project_path,
    strip_source: surfaces.strip_source,
  });

  return {
    ok: true,
    spelling: SPELLING,
    verb: 'next',
    primary: 'next',
    mode: 'project',
    strip_first: true,
    project_path,
    face_loaded: false,
    face_loads_for_rank: 0,
    next: [
      {
        project_id: proj.project_id,
        project_path,
        next_recommended: proj.next_recommended,
        why_next: proj.why_next,
        active_effort: proj.active_effort,
        human_wait: proj.human_wait,
        capacity: proj.capacity,
        face_loaded: false,
      },
    ],
    next_recommended: proj.next_recommended,
    why_next: proj.why_next,
    active_effort: proj.active_effort,
    human_wait: proj.human_wait,
    message: 'N=1 next from Strip projection',
  };
}

/**
 * update / heartbeat — Face narrative rewrite + Strip append; never rewrite Strip history.
 * @param {object} opts
 * @param {string} [opts.verb_name='update']
 */
/**
 * W4 of the steward revision (2026-09-28): repair as a proposal (his Q2, "propose the tidying too").
 *
 * `--repair-propose --after-step <id> [--after-presentation <id>]` — composes the correction set that follows an
 * acceptance from the records alone (`composeRepairProposal`: the waits that named the accepted step; the slices
 * whose pin on it went stale) and appends it as ONE `repair_proposal` event anchored at the roadmap's last seq.
 * Nothing on any step changes. The SAME set already open for that step (the same presentation and rows) is
 * answered, not duplicated; a different one — a later acceptance — supersedes the open set (`repair_resolve`
 * disposition `superseded`, no step written) and the new composition follows, even when it is empty; an empty
 * set appends no proposal (there is nothing for him to accept). A refinement fold that throws fails the propose:
 * never a partial set (Grok W4).
 *
 * `--repair-resolve <proposal_id> --disposition accepted|dismissed --who <name> [--why <text>]` — his word. On
 * `accepted` each correction still true of the roadmap (`planRepairApply`) is applied FIRST as a receipted
 * `step_set` naming the proposal, then the `repair_resolve` is appended with the ids that landed; a failed
 * `step_set` leaves the proposal open (the landed ones are skipped as moved on a retry). A dismiss is refused once
 * any correction of that proposal has landed. Second-look rows are noted, never written. No model; no strip write.
 */
function repairAct(opts, project_path, lifecycle, verb_name) {
  const base = { spelling: SPELLING, verb: verb_name, primary: 'update', project_path };
  const otherFields = Object.keys(opts.face_patch ?? {}).length
    || Object.keys(opts.strip_tip && typeof opts.strip_tip === 'object' ? opts.strip_tip : {}).length
    || !!opts.current_step_id || !!opts.leave || !!opts.horizon || (opts.repair_propose && opts.repair_resolve);
  if (otherFields) {
    return { ok: false, error: 'repair_exclusive', ...base, message: 'A repair act travels alone: no other field on the same update.' };
  }
  if (!lifecycle.ok || !Array.isArray(lifecycle.roadmap?.roadmap_events)) {
    return { ok: false, error: 'no_roadmap', ...base, message: 'A repair needs the roadmap.' };
  }
  const events = lifecycle.roadmap.roadmap_events;
  const projection = Array.isArray(lifecycle.roadmap.roadmap_projection) ? lifecycle.roadmap.roadmap_projection : [];
  const dry = Boolean(opts.dry_run) || opts.persist === false;

  if (opts.repair_propose) {
    const step = String(opts.after_step ?? '').trim();
    if (!step) return { ok: false, error: 'repair_needs_step', ...base, message: '--repair-propose needs --after-step <id>.' };
    const last = events.length ? events[events.length - 1] : null;
    const lastSeq = last && typeof last.seq === 'number' ? last.seq : 0;
    let state = null;
    try { state = foldRefinements(events); } catch (e) {
      // a fold that throws is not "no pins": the set would be partial (Grok W4)
      return { ok: false, error: 'refinement_fold_failed', step_id: step, ...base, message: `The refinement state could not be folded: ${e?.message ?? e}` };
    }
    const composed = composeRepairProposal({ projection, accepted_step_id: step,
      accepted_presentation_id: typeof opts.after_presentation === 'string' && opts.after_presentation.trim() ? opts.after_presentation.trim() : null,
      refinement_state: state, after_seq: lastSeq });
    if (!composed.ok) return { ok: false, error: 'unknown_step', step_id: step, ...base, message: composed.reason };
    const open = openRepairProposals(events);
    const prior = open.find((e) => e.after && typeof e.after === 'object' && String(e.after.step_id) === step);
    // the same set already open (a retried route): answered, never a twin
    if (prior && sameRepairSet(prior, composed.proposal)) {
      return { ok: true, existing: true, appended: false, proposal_id: String(prior.proposal_id), count: Number(prior.count) || 0, ...base,
               message: `That set is already proposed (${prior.proposal_id}); his word is still awaited.` };
    }
    if (dry) return { ok: true, dry_run: true, appended: false, proposal: composed.proposal, corrections: composed.corrections, supersedes: prior ? String(prior.proposal_id) : null, ...base };
    let superseded = null;
    if (prior) {
      // a later acceptance on the same step: the old set is closed as superseded (nothing written to any step) and
      // the new composition follows — even an empty one supersedes (Grok W4)
      const sup = appendRoadmapEventThroughSpine(project_path, { kind: 'repair_resolve', proposal_id: String(prior.proposal_id), disposition: 'superseded',
        receipt: { who: 'steward', why: `a later acceptance on ${step}` }, applied: [], skipped: [], superseded_by: composed.empty ? null : composed.proposal.proposal_id }, { skip_index: true });
      if (!sup.ok) return { ...sup, ...base, appended: false };
      superseded = String(prior.proposal_id);
    }
    if (composed.empty) {
      return { ok: true, empty: true, appended: false, superseded, proposal: composed.proposal, ...base,
               message: `Nothing to correct after ${step}; no proposal appended${superseded ? ` (${superseded} superseded)` : ''}.` };
    }
    const res = appendRoadmapEventThroughSpine(project_path, { ...composed.proposal }, { skip_index: true });
    if (!res.ok) return { ...res, ...base, appended: false, superseded };
    return { ok: true, appended: true, superseded, proposal_id: composed.proposal.proposal_id, count: composed.proposal.count, corrections: composed.corrections, ...base,
             message: `Proposed ${composed.proposal.count} correction${composed.proposal.count === 1 ? '' : 's'} after ${step}; nothing changes until his word.` };
  }

  const proposal_id = String(opts.repair_resolve ?? '').trim();
  const disposition = String(opts.disposition ?? '').trim();
  if (!['accepted', 'dismissed'].includes(disposition)) {
    return { ok: false, error: 'bad_disposition', proposal_id, ...base, message: '--disposition is accepted or dismissed.' };
  }
  const who = String(opts.who ?? '').trim();
  if (!who) return { ok: false, error: 'repair_needs_who', proposal_id, ...base, message: 'His word carries a name: --who <name>.' };
  const prop = events.find((e) => e && e.kind === 'repair_proposal' && String(e.proposal_id) === proposal_id);
  if (!prop) return { ok: false, error: 'unknown_proposal', proposal_id, ...base, message: `No proposal ${proposal_id} in the roadmap.` };
  if (!openRepairProposals(events).some((e) => String(e.proposal_id) === proposal_id)) {
    return { ok: false, error: 'proposal_resolved', proposal_id, ...base, message: `Proposal ${proposal_id} already has his word.` };
  }
  const landedBefore = events.filter((e) => e && e.kind === 'step_set' && String(e.repair_of ?? '') === proposal_id).map((e) => String(e.step_id));
  if (disposition === 'dismissed' && landedBefore.length) {
    return { ok: false, error: 'repair_partly_applied', proposal_id, applied: landedBefore, ...base,
             message: `${landedBefore.length} correction${landedBefore.length === 1 ? '' : 's'} of ${proposal_id} already landed; accept finishes the set.` };
  }
  const plan = disposition === 'accepted' ? planRepairApply({ projection, proposal: prop }) : { apply: [], skipped: [], noted: [] };
  const afterStep = prop.after && typeof prop.after === 'object' ? String(prop.after.step_id ?? '') : '';
  const why = typeof opts.reason === 'string' && opts.reason.trim() ? opts.reason.trim()
    : `${disposition} the correction set after ${afterStep || 'the acceptance'}`;
  if (dry) return { ok: true, dry_run: true, disposition, proposal_id, apply: plan.apply, skipped: plan.skipped, noted: plan.noted, ...base };
  // the corrections land FIRST; his word is appended only over what landed (Grok W4: the record tells the truth)
  const applied = [...landedBefore];
  for (const c of plan.apply) {
    const sres = appendRoadmapEventThroughSpine(project_path,
      { kind: 'step_set', step_id: c.step_id, fields: c.fields, receipt: { who, why: `repair ${proposal_id}: ${c.why}` }, repair_of: proposal_id },
      { skip_index: true });
    if (!sres.ok) {
      return { ...sres, ...base, resolved: false, disposition, proposal_id, applied, skipped: plan.skipped, noted: plan.noted,
               message: `The correction on ${c.step_id} failed after ${applied.length} landed; the set stays open — accept again finishes it.` };
    }
    applied.push(c.step_id);
  }
  const rres = appendRoadmapEventThroughSpine(project_path, { kind: 'repair_resolve', proposal_id, disposition, receipt: { who, why },
    applied, skipped: plan.skipped, noted: plan.noted }, { skip_index: true });
  if (!rres.ok) return { ...rres, ...base, resolved: false, disposition, proposal_id, applied, skipped: plan.skipped, noted: plan.noted };
  return { ok: true, resolved: true, disposition, proposal_id, applied, skipped: plan.skipped, noted: plan.noted, ...base,
           message: disposition === 'accepted'
             ? `Accepted: ${applied.length} correction${applied.length === 1 ? '' : 's'} applied${plan.skipped.length ? `, ${plan.skipped.length} skipped (moved since)` : ''}${plan.noted.length ? `, ${plan.noted.length} noted for a second look` : ''}.`
             : 'Dismissed: nothing changed.' };
}

export function verbUpdate(opts = {}) {
  const verb_name = opts.verb_name ?? 'update';
  const project_path = resolveProjectPath({
    project: opts.project,
    cwd: opts.cwd,
  });
  const surfaces = opts.surfaces ?? loadProjectSurfaces(project_path);
  const lifecycle = loadProjectRoadmap(project_path);
  const managed = lifecycle.ok && lifecycle.roadmap?.roadmap_events?.some(e=>e.kind==='refinement_update');
  if(managed && [opts.face_patch,opts.strip_tip,opts.strip_in_place_patch].some(p=>p &&
      (Object.hasOwn(p,'human_wait') || Object.hasOwn(p,'pending_request') || Object.hasOwn(p,'wait_ref')))) {
    return {ok:false,error:'managed-wait-event-owned',message:'Use refinement-update; a stamp cannot change managed human wait.'};
  }
  // W0 (2026-09-28): a wait's subject is a typed reference or 'none' — never free prose
  const wait_ref_in = opts.strip_tip && typeof opts.strip_tip === 'object' ? opts.strip_tip.wait_ref : undefined;
  if (wait_ref_in !== undefined && !isWaitRef(wait_ref_in)) {
    return { ok: false, error: 'bad_wait_ref', wait_ref: wait_ref_in, spelling: SPELLING, verb: verb_name, primary: 'update', project_path,
             message: '--wait-ref must be step:<id>, deliverable:<row>@<version>, decision:<id>, or none.' };
  }
  // W4 (2026-09-28): a repair act is a roadmap act and travels alone
  if (opts.repair_propose || opts.repair_resolve) {
    return repairAct(opts, project_path, lifecycle, verb_name);
  }

  if (!surfaces.strip && !surfaces.face) {
    return {
      ok: false,
      error: 'no_face_or_strip',
      spelling: SPELLING,
      verb: verb_name,
      primary: 'update',
      project_path,
      message: 'update/heartbeat needs Face or Strip',
    };
  }

  // W3 (2026-09-28): --horizon derives the line from the plan — the focus, then what follows it — and writes it as a
  // stamped instrument (the roadmap's last seq and the focus it derived from). A record whose stamp already covers
  // the last event with the same focus is unchanged: no write. The focus read is the strip's CURRENT one, so a focus
  // change he made is honoured, never overridden. Deterministic; no model.
  let horizon = null;
  if (opts.horizon) {
    const proj = lifecycle.ok && Array.isArray(lifecycle.roadmap?.roadmap_projection) ? lifecycle.roadmap.roadmap_projection : [];
    const evs = lifecycle.ok && Array.isArray(lifecycle.roadmap?.roadmap_events) ? lifecycle.roadmap.roadmap_events : [];
    const lastEv = evs.length ? evs[evs.length - 1] : null;
    const focusId = opts.current_step_id ?? surfaces.strip?.current_step_id ?? null;
    horizon = deriveHorizon({ projection: proj, current_step_id: focusId, n: 3, last_event: lastEv, reason: opts.horizon_reason });
    if (!horizon.ok) {
      return { ok: false, error: 'no_horizon', reason: horizon.reason, spelling: SPELLING, verb: verb_name, primary: 'update', project_path,
               message: `No horizon can be derived: ${horizon.reason}.` };
    }
    const lastSeq = lastEv && typeof lastEv.seq === 'number' ? lastEv.seq : 0;
    const stampedSeq = surfaces.strip?.horizon_source_seq;
    const whyOut = horizon.why ?? (surfaces.strip?.why_next ?? '');
    const otherFields = Object.keys(opts.strip_tip && typeof opts.strip_tip === 'object' ? opts.strip_tip : {}).length
      || Object.keys(opts.face_patch ?? {}).length || !!opts.current_step_id || !!opts.leave;
    // unchanged (no write) only when the stamp covers the last event with the same focus AND the line and why on
    // the strip already equal the derivation AND the call changes nothing else — a later edit of the line by
    // another update clears the stamp (below), so it can never freeze an old line (Grok W3)
    if (!opts.force && !otherFields && typeof stampedSeq === 'number' && stampedSeq >= lastSeq
        && surfaces.strip?.horizon_focus === horizon.focus
        && surfaces.strip?.next_recommended === horizon.line && String(surfaces.strip?.why_next ?? '') === String(whyOut)) {
      return { ok: true, unchanged: true, horizon, spelling: SPELLING, verb: verb_name, primary: 'update', project_path };
    }
    opts = { ...opts, strip_tip: { ...(opts.strip_tip && typeof opts.strip_tip === 'object' ? opts.strip_tip : {}),
      next_recommended: horizon.line, why_next: whyOut, horizon_source_seq: lastSeq, horizon_focus: horizon.focus, horizon_steps: horizon.steps } };
  } else if (opts.strip_tip && typeof opts.strip_tip === 'object'
             && (opts.strip_tip.next_recommended != null || opts.strip_tip.why_next != null || (opts.face_patch && opts.face_patch.why_next != null))) {
    // a line written by hand (the turn's, his) is not the derived one: the stamp clears so the next --horizon
    // re-derives rather than reporting "unchanged" over it
    opts = { ...opts, strip_tip: { ...opts.strip_tip, horizon_source_seq: null, horizon_focus: null } };
  }
  // the strip's next / why / wait are capped by words (the lead line must fit)
  const face_patch0 = opts.face_patch ?? {};
  const tip0 = opts.strip_tip && typeof opts.strip_tip === 'object' ? opts.strip_tip : {};
  for (const [field, value] of [['next_recommended', tip0.next_recommended], ['why_next', tip0.why_next ?? face_patch0.why_next],
                                ['human_wait', tip0.human_wait ?? face_patch0.human_wait]]) {
    const over = overCap(field, value);
    if (over) {
      return { ok: false, error: 'over_cap', ...over, spelling: SPELLING, verb: verb_name, primary: 'update', project_path,
               message: `${field} is ${over.words} words; the cap is ${over.cap}. Say it shorter.` };
    }
  }
  // --current-step pins the step that follows; a pin needs a next and a why
  const pin_id = typeof opts.current_step_id === 'string' && opts.current_step_id.trim() ? opts.current_step_id.trim() : null;
  let pin_steps = null;
  if (pin_id) {
    pin_steps = lifecycle.ok && Array.isArray(lifecycle.roadmap?.roadmap_projection) ? lifecycle.roadmap.roadmap_projection : [];
    if (!pin_steps.some((st) => st && st.id === pin_id)) {
      return { ok: false, error: 'unknown_step', step_id: pin_id, spelling: SPELLING, verb: verb_name, primary: 'update', project_path,
               message: `--current-step ${pin_id}: no such step in the roadmap.` };
    }
    const missing = missingSpine(surfaces.strip, { next_recommended: tip0.next_recommended, why_next: tip0.why_next ?? face_patch0.why_next });
    if (missing.length) {
      return { ok: false, error: 'spine_required', missing, spelling: SPELLING, verb: verb_name, primary: 'update', project_path,
               message: 'A pin needs a next and a why: pass --next-recommended and --strip-why-next (or have them on the strip).' };
    }
  }

  const prior_as_of = surfaces.strip?.as_of ?? null;
  const prior_instruments = Array.isArray(surfaces.strip?.instruments)
    ? surfaces.strip.instruments.map((e) => ({ ...e }))
    : [];
  const prior_receipts = Array.isArray(surfaces.strip?.receipts)
    ? surfaces.strip.receipts.map((e) => ({ ...e }))
    : [];
  const prior_instruments_len = prior_instruments.length;
  const prior_receipts_len = prior_receipts.length;

  // Reject any attempt to silently rewrite Strip clocks in place
  if (opts.strip_in_place_patch && Object.keys(opts.strip_in_place_patch).length) {
    const rejected = mutateStripInPlace(surfaces.strip, opts.strip_in_place_patch);
    return {
      ...rejected,
      spelling: SPELLING,
      verb: verb_name,
      primary: 'update',
      project_path,
    };
  }

  const face_patch = opts.face_patch ?? {};
  const face_result =
    Object.keys(face_patch).length > 0
      ? rewriteFaceNarrative(surfaces.face?.narrative ?? {}, face_patch)
      : {
          ok: true,
          authority: 'face_human_narrative',
          narrative: surfaces.face?.narrative ?? {},
          rewritten: [],
        };

  let strip = surfaces.strip ? { ...surfaces.strip } : null;
  let strip_append = null;
  let receipt_append = null;

  // W0: a bare `--leave` records where he left and moves no clock — no instrument, one receipt
  const leave_only = !!opts.leave && !Object.keys(face_patch).length && !pin_id
    && !(opts.strip_tip && typeof opts.strip_tip === 'object' && Object.keys(opts.strip_tip).length);
  if (strip && opts.leave) {
    const events = lifecycle.ok && Array.isArray(lifecycle.roadmap?.roadmap_events) ? lifecycle.roadmap.roadmap_events : [];
    const last = events.length ? events[events.length - 1] : null;
    // the deliverable version he was on: copied ONLY when the last event already carries one (a refinement
    // event's presentation), never invented (Grok W0)
    const op = last && last.kind === 'refinement_update' && last.operation && typeof last.operation === 'object' ? last.operation : null;
    const presentation = op ? (op.presentation_id ?? op.base_presentation_id ?? null) : null;
    const receipt = {
      schema: RECEIPT_SCHEMA_ID,
      kind: 'leave',
      as_of: opts.as_of ?? todayIso(),
      at: typeof opts.leave_at === 'string' && opts.leave_at.trim() ? opts.leave_at.trim() : new Date().toISOString(),
      current_step_id: strip.current_step_id ?? null,
      last_event_seq: last?.seq ?? null,
      last_event_at: last?.at ?? null,
      last_event_kind: last?.kind ?? null,
      last_event_step_id: last?.step_id ?? op?.step_id ?? null,
      presentation_id: presentation,
      active_effort: strip.active_effort ?? null,
      wait_ref: strip.wait_ref ?? null,
      human_wait: strip.human_wait ?? 'none',
    };
    const rec = appendStripReceipt(strip, receipt, { apply_to_projection: false });
    if (!rec.ok) {
      return { ok: false, error: rec.error, spelling: SPELLING, verb: verb_name, primary: 'update', message: 'Leave receipt append failed' };
    }
    strip = rec.strip;
    receipt_append = receipt;
  }

  if (strip && !leave_only) {
    const instrument = {
      _kind: 'instrument',
      kind: verb_name === 'heartbeat' ? 'heartbeat' : (horizon ? 'horizon' : 'update'),
      as_of: opts.as_of ?? todayIso(),
      source: horizon ? 'verb_update:horizon' : 'verb_update',
      ...(horizon ? { derived: true } : {}),
      ...(opts.strip_tip && typeof opts.strip_tip === 'object' ? opts.strip_tip : {}),
    };
    // Map face active_effort / human_wait into strip tip when provided
    if (face_patch.active_effort != null) instrument.active_effort = face_patch.active_effort;
    if (face_patch.human_wait != null) instrument.human_wait = face_patch.human_wait;
    if (face_patch.why_next != null && instrument.why_next == null) {
      instrument.why_next = face_patch.why_next;
    }
    if (pin_id) instrument.current_step_id = pin_id;

    const appended = appendStripInstrument(strip, instrument, { apply_to_projection: true });
    if (!appended.ok) {
      return {
        ok: false,
        error: appended.error,
        spelling: SPELLING,
        verb: verb_name,
        primary: 'update',
        message: 'Strip instrument append failed',
      };
    }
    strip = appended.strip;
    strip_append = instrument;

    // Heartbeat also leaves a structured receipt
    if (verb_name === 'heartbeat' || opts.append_receipt) {
      const receipt = {
        schema: RECEIPT_SCHEMA_ID,
        kind: 'heartbeat',
        as_of: instrument.as_of,
        active_effort: strip.active_effort ?? null,
        why_next: strip.why_next ?? null,
        human_wait: strip.human_wait ?? 'none',
        uncertainty_flags: Array.isArray(strip.uncertainty_flags)
          ? [...strip.uncertainty_flags]
          : [],
      };
      const rec = appendStripReceipt(strip, receipt, { apply_to_projection: false });
      if (rec.ok) {
        strip = rec.strip;
        receipt_append = receipt;
      }
    }
  }

  // Prove prior history clocks were not rewritten: prior entries deep-equal prefix
  const history_intact =
    !strip ||
    (Array.isArray(strip.instruments) &&
      prior_instruments.every((e, i) => stableEqual(strip.instruments[i], e)) &&
      prior_receipts.every((e, i) => stableEqual(strip.receipts[i], e)));

  const persist = opts.persist !== false && !opts.dry_run;
  const written = { face: false, strip: false };
  if (persist && !opts.surfaces) {
    if (face_result.rewritten.length && surfaces.face_path) {
      writeFaceNarrative(surfaces.face_path, face_result.narrative, surfaces.face?.raw);
      written.face = true;
    } else if (face_result.rewritten.length) {
      const facePath = path.join(project_path, FACE_FILE_NAME);
      writeFaceNarrative(facePath, face_result.narrative, surfaces.face?.raw);
      written.face = true;
    }
    if (strip && surfaces.strip_source === 'strip.json') {
      const stripPath = surfaces.strip_path ?? path.join(project_path, STRIP_FILE_NAME);
      // Atomic: this is the append-only receipt ledger, and the bridge caller
      // can be KILLED on timeout — a truncated write here loses receipts.
      writeFileAtomicSync(stripPath, `${JSON.stringify(strip, null, 2)}\n`);
      written.strip = true;
    }
    // the same call pins the roadmap: navigation.current on the step that follows, off the rest
    if (pin_id) {
      written.pinned = pin_id;
      written.unpinned = [];
      // a step without a course navigation is pinned by the strip alone (the reader's current_step_id comes first)
      for (const st of pin_steps) {
        const nav = st.navigation && typeof st.navigation === 'object' ? st.navigation : null;
        const isTarget = st.id === pin_id;
        if (!nav) continue;
        if (!isTarget && nav.current !== true) continue;
        if (isTarget && nav.current === true) continue;
        const res = appendRoadmapEventThroughSpine(project_path,
          { kind: 'step_set', step_id: st.id, fields: { navigation: { ...nav, current: isTarget } } }, { skip_index: true });
        if (!res.ok) return { ...res, verb: verb_name, primary: 'update', project_path, pinned: false };
        if (!isTarget) written.unpinned.push(st.id);
      }
    }
    // TW2 precompute hook: brief cache is a declared projection (zero write
    // authority) refreshed at update/heartbeat time so the packet opens with
    // zero further gathering. Opt-in via --precompute-brief.
    if (opts.precompute_brief) {
      precomputeBriefCache(project_path);
      written.brief_cache = true;
    }
  }

  return {
    ok: true,
    spelling: SPELLING,
    verb: verb_name,
    primary: 'update',
    project_path,
    authority: {
      face: 'human_narrative_rewrite',
      strip: 'append_only',
    },
    face: face_result,
    strip,
    strip_append,
    receipt_append,
    prior_as_of,
    prior_instruments_length: prior_instruments_len,
    prior_receipts_length: prior_receipts_len,
    instruments_length: strip?.instruments?.length ?? 0,
    receipts_length: strip?.receipts?.length ?? 0,
    history_intact,
    strip_history_rewritten: !history_intact,
    persisted: written,
    dry_run: Boolean(opts.dry_run) || opts.persist === false,
    message: 'Face narrative updated where patched; Strip history append-only',
  };
}

/**
 * soft-vet / grasscatch — park idea with reason; grasscatch entry + receipt fields.
 * @param {object} opts
 * @param {string} [opts.verb_name='soft-vet']
 */
export function verbSoftVet(opts = {}) {
  const verb_name = opts.verb_name ?? 'soft-vet';
  const kind = verb_name === 'grasscatch' ? 'grasscatch' : 'soft-vet';
  const deferred = opts.deferred ?? opts.what ?? opts.rest?.[0] ?? null;
  const why = opts.reason ?? opts.why ?? opts.rest?.[1] ?? null;

  if (!deferred || !why) {
    return {
      ok: false,
      error: 'soft_vet_requires_reason',
      spelling: SPELLING,
      verb: verb_name,
      primary: 'soft-vet',
      message:
        'soft-vet/grasscatch requires deferred item and reason (what deferred + why). Use --deferred and --reason.',
      required: ['deferred', 'reason'],
    };
  }

  const project_path = resolveProjectPath({
    project: opts.project,
    cwd: opts.cwd,
  });
  const surfaces = opts.surfaces ?? loadProjectSurfaces(project_path);

  if (!surfaces.strip) {
    return {
      ok: false,
      error: 'no_strip',
      spelling: SPELLING,
      verb: verb_name,
      primary: 'soft-vet',
      project_path,
      message: 'soft-vet/grasscatch requires a Strip to append grasscatch + receipt',
    };
  }

  const prior_as_of = surfaces.strip.as_of;
  const prior_instruments = Array.isArray(surfaces.strip.instruments)
    ? surfaces.strip.instruments.map((e) => ({ ...e }))
    : [];
  const prior_receipts = Array.isArray(surfaces.strip.receipts)
    ? surfaces.strip.receipts.map((e) => ({ ...e }))
    : [];
  const prior_grasscatch = Array.isArray(surfaces.strip.grasscatch)
    ? [...surfaces.strip.grasscatch]
    : [];

  // Soft-vet fills receipt cells only — never launches specialists (W4)
  const uncertainty_flags = Array.isArray(surfaces.strip.uncertainty_flags)
    ? [...surfaces.strip.uncertainty_flags]
    : [];
  const receipt = buildGrasscatchReceipt({
    kind,
    deferred,
    why,
    handback_shape: opts.handback_shape ?? {
      when: 'later',
      return_via: 'strip_receipt',
      needs: [
        'active_effort',
        'why_next',
        'grasscatch_why',
        'tool_depth_why',
        'human_wait',
        'uncertainty_flags',
      ],
      what_deferred: deferred,
      why,
      suggested_later_owner: opts.suggested_later_owner ?? null,
    },
    suggested_later_owner: opts.suggested_later_owner ?? null,
    as_of: opts.as_of ?? todayIso(),
    active_effort: surfaces.strip.active_effort ?? null,
    uncertainty_flags,
    tool_depth_why: opts.tool_depth_why ?? null,
  });

  // Append instrument that unions grasscatch list (append-union, never drop prior)
  const instrument = {
    _kind: 'instrument',
    kind,
    as_of: receipt.as_of,
    grasscatch: [deferred],
    deferred,
    why,
    grasscatch_why: why,
    suggested_later_owner: receipt.suggested_later_owner,
    uncertainty_flags: receipt.uncertainty_flags,
    handback_shape: receipt.handback_shape,
  };

  const inst = appendStripInstrument(surfaces.strip, instrument, { apply_to_projection: true });
  if (!inst.ok) {
    return { ok: false, error: inst.error, spelling: SPELLING, verb: verb_name, primary: 'soft-vet' };
  }

  const rec = appendStripReceipt(inst.strip, receipt, { apply_to_projection: false });
  if (!rec.ok) {
    return { ok: false, error: rec.error, spelling: SPELLING, verb: verb_name, primary: 'soft-vet' };
  }

  const strip = rec.strip;
  const history_intact =
    prior_instruments.every((e, i) => stableEqual(strip.instruments[i], e)) &&
    prior_receipts.every((e, i) => stableEqual(strip.receipts[i], e));

  // Prior grasscatch labels must still be present (append-union)
  const grasscatch_prior_intact = prior_grasscatch.every((g) =>
    (strip.grasscatch || []).includes(g),
  );

  const persist = opts.persist !== false && !opts.dry_run;
  const written = { strip: false };
  if (persist && !opts.surfaces && surfaces.strip_source === 'strip.json') {
    const stripPath = surfaces.strip_path ?? path.join(project_path, STRIP_FILE_NAME);
    // Atomic: same receipt ledger, second writer. (Found by the W16 gate —
    // the first pass fixed only one of the two strip writers in this file.)
    writeFileAtomicSync(stripPath, `${JSON.stringify(strip, null, 2)}\n`);
    written.strip = true;
  }

  return {
    ok: true,
    spelling: SPELLING,
    verb: verb_name,
    primary: 'soft-vet',
    project_path,
    parked: {
      deferred,
      why,
      suggested_later_owner: receipt.suggested_later_owner,
      uncertainty_flags: receipt.uncertainty_flags,
      handback_shape: receipt.handback_shape,
    },
    receipt,
    strip,
    prior_as_of,
    prior_grasscatch,
    grasscatch: strip.grasscatch,
    history_intact,
    grasscatch_prior_intact,
    strip_history_rewritten: !history_intact,
    // soft-vet fills cells only — never commissions or launches specialists
    launches_specialists: false,
    commission: null,
    specialists_launched: [],
    persisted: written,
    dry_run: Boolean(opts.dry_run) || opts.persist === false,
    message: `Parked via ${kind}: grasscatch entry + receipt appended (Strip history intact; no specialist launch)`,
  };
}

/**
 * receipt-validate — structured schema only; monologue-only invalid.
 * @param {object} opts
 */
export function verbReceiptValidate(opts = {}) {
  let input = opts.receipt;
  if (input == null && opts.receipt_raw != null) input = opts.receipt_raw;
  if (input == null && opts.rest?.length) {
    // First free arg may be JSON or monologue
    input = opts.rest.join(' ');
  }
  if (opts.receipt_error) {
    return {
      ok: false,
      error: 'receipt_read_failed',
      spelling: SPELLING,
      verb: 'receipt-validate',
      primary: 'receipt-validate',
      message: opts.receipt_error,
    };
  }
  if (input == null || input === '') {
    return {
      ok: false,
      error: 'receipt_missing',
      spelling: SPELLING,
      verb: 'receipt-validate',
      primary: 'receipt-validate',
      message: 'receipt-validate requires --receipt JSON or --receipt-file',
    };
  }

  // Explicit monologue path
  if (typeof input === 'string' && isMonologueOnly(input)) {
    return {
      ok: false,
      error: 'monologue_only_invalid',
      spelling: SPELLING,
      verb: 'receipt-validate',
      primary: 'receipt-validate',
      valid: false,
      message:
        'Monologue-only receipt is invalid; provide structured schema/kind/as_of fields.',
    };
  }

  const result = validateReceipt(input);
  if (!result.ok) {
    return {
      ok: false,
      error: result.error,
      spelling: SPELLING,
      verb: 'receipt-validate',
      primary: 'receipt-validate',
      valid: false,
      issues: result.issues,
      message: result.message,
    };
  }

  return {
    ok: true,
    spelling: SPELLING,
    verb: 'receipt-validate',
    primary: 'receipt-validate',
    valid: true,
    receipt: result.receipt,
    schema_id: result.schema_id,
    monologue: false,
    message: 'Receipt passed structured schema validation',
  };
}

/**
 * depth-suggest — fully table-driven (W4).
 * Reads Strip signals + dispatch table only. Defaults LITE bias.
 * Free-form depth inflation refused. Human override requires structured receipt.
 * @param {object} opts
 */
export function verbDepthSuggest(opts = {}) {
  // Free-form depth inflation refused (argv/opts LITE|FULL|SPIKE without table path)
  const freeForm =
    opts.depth ??
    opts.inflate ??
    opts.rest?.find((t) => /^(LITE|FULL|SPIKE|commission|refuse)$/i.test(t));

  if (freeForm && opts.allow_free_form !== true) {
    return {
      ok: false,
      error: 'free_form_depth_refused',
      spelling: SPELLING,
      verb: 'depth-suggest',
      primary: 'depth-suggest',
      message:
        'Free-form depth inflation refused. depth-suggest is table-driven; no ad-hoc LITE|FULL|SPIKE from argv. Use Strip signals + table, or a structured override receipt (who/when/why/from→to).',
      refused_value: freeForm,
      table_ready: true,
    };
  }

  const table = opts.table ?? loadDispatchTable();
  let strip = null;
  let project_path = null;
  if (opts.signals && typeof opts.signals === 'object') {
    strip = opts.signals;
  } else if (opts.project || opts.surfaces || opts.cwd) {
    project_path = resolveProjectPath({
      project: opts.project,
      cwd: opts.cwd,
    });
    const surfaces = opts.surfaces ?? loadProjectSurfaces(project_path);
    strip = surfaces.strip ?? null;
  }

  const suggested = suggestDepthFromStrip(strip, { table });
  // Rank-adjacent flags when capacity unknown (never silent green)
  let rank_flags = null;
  if (strip) {
    const proj = toStripProjection(strip, { project_path });
    if (proj) {
      const scored = scoreStripProjection(proj);
      rank_flags = scored.flags;
    }
  }

  let outcome = suggested.outcome;
  let override_applied = null;
  let tool_depth_why = suggested.tool_depth_why;

  // Human override of table outcome requires structured receipt reason
  if (opts.override != null || opts.override_receipt != null) {
    const ovRaw = opts.override_receipt ?? opts.override;
    let ovReceipt = ovRaw;
    if (typeof ovRaw === 'string') {
      try {
        ovReceipt = JSON.parse(ovRaw);
      } catch {
        return {
          ok: false,
          error: 'override_receipt_invalid',
          spelling: SPELLING,
          verb: 'depth-suggest',
          primary: 'depth-suggest',
          table_ready: true,
          table_outcome: suggested.outcome,
          message:
            'Override without structured receipt fails. Provide override receipt with who/when/why/from→to.',
        };
      }
    }

    // Accept either full receipt or bare override object
    const reason =
      ovReceipt && typeof ovReceipt === 'object'
        ? ovReceipt.override && typeof ovReceipt.override === 'object'
          ? ovReceipt.override
          : ovReceipt
        : null;

    if (!reason || typeof reason !== 'object') {
      return {
        ok: false,
        error: 'override_receipt_required',
        spelling: SPELLING,
        verb: 'depth-suggest',
        primary: 'depth-suggest',
        table_ready: true,
        table_outcome: suggested.outcome,
        message:
          'Human override of table outcome requires structured receipt reason (who/when/why/from→to).',
      };
    }

    // Validate as receipt when schema/kind present; otherwise field-check via applyDepthOverride
    if (ovReceipt.kind === 'override' || ovReceipt.schema) {
      const validated = validateReceipt(
        ovReceipt.kind
          ? ovReceipt
          : buildOverrideReceipt({
              ...reason,
              from: reason.from ?? suggested.outcome,
              to: reason.to,
            }),
      );
      if (!validated.ok) {
        return {
          ok: false,
          error: 'override_receipt_invalid',
          spelling: SPELLING,
          verb: 'depth-suggest',
          primary: 'depth-suggest',
          table_ready: true,
          table_outcome: suggested.outcome,
          issues: validated.issues,
          message: validated.message,
        };
      }
    }

    const applied = applyDepthOverride(
      reason.from ?? suggested.outcome,
      reason.to,
      {
        who: reason.who,
        when: reason.when,
        why: reason.why,
      },
    );
    if (!applied.ok) {
      return {
        ok: false,
        error: applied.error,
        spelling: SPELLING,
        verb: 'depth-suggest',
        primary: 'depth-suggest',
        table_ready: true,
        table_outcome: suggested.outcome,
        issues: applied.issues,
        message: applied.message,
      };
    }
    outcome = applied.outcome;
    override_applied = applied.override;
    tool_depth_why = applied.tool_depth_why;
  }

  const uncertainty_flags = suggested.uncertainty_flags ?? [];
  const receipt = buildDepthReceipt({
    outcome,
    tool_depth_why,
    as_of: opts.as_of ?? todayIso(),
    uncertainty_flags,
    capacity: suggested.capacity,
    active_effort: suggested.signals?.active_effort ?? null,
    dimensions: suggested.dimensions,
    flags: {
      ...suggested.flags,
      ...(rank_flags || {}),
      override: Boolean(override_applied),
    },
  });

  return {
    ok: true,
    spelling: SPELLING,
    verb: 'depth-suggest',
    primary: 'depth-suggest',
    table_ready: true,
    project_path,
    outcome,
    table_outcome: suggested.outcome,
    bias: DEFAULT_BIAS,
    lite_bias: Boolean(suggested.flags?.lite_bias),
    flags: {
      ...suggested.flags,
      rank: rank_flags,
      silent_full_green: false,
      never_silent_full_green: true,
    },
    cell: {
      status: 'table_ready',
      outcome,
      table_outcome: suggested.outcome,
      reason: tool_depth_why,
      tool_depth_why,
      signals: suggested.signals,
      dimensions: suggested.dimensions,
      matched_cell: suggested.cell,
      lite_bias_default: true,
      override: override_applied,
    },
    receipt,
    uncertainty_flags,
    capacity: suggested.capacity,
    rank_flags,
    free_form: false,
    message: override_applied
      ? `depth-suggest table ${suggested.outcome} overridden → ${outcome} (structured receipt)`
      : `depth-suggest table outcome ${outcome} (LITE bias; free-form refused)`,
    // Never silent FULL green (capacity=unknown demotes FULL in the table layer)
    silent_full_green: false,
  };
}

/**
 * Dispatch a closed primary verb to its body.
 * @param {string} primary
 * @param {object} opts
 */
export function runClosedVerbBody(primary, opts = {}) {
  switch (primary) {
    case 'status':
      return verbStatus(opts);
    case 'next':
      return verbNext(opts);
    case 'update':
      return verbUpdate({ ...opts, verb_name: opts.verb_name ?? 'update' });
    case 'depth-suggest':
      return verbDepthSuggest(opts);
    case 'soft-vet':
      return verbSoftVet({ ...opts, verb_name: opts.verb_name ?? 'soft-vet' });
    case 'receipt-validate':
      return verbReceiptValidate(opts);
    case 'roadmap-show':
      return verbRoadmapShow(opts);
    case 'roadmap-propose':
      return verbRoadmapPropose(opts);
    case 'roadmap-set':
      return verbRoadmapSet(opts);
    case 'refinement-update':
      return verbRefinementUpdate(opts);
    case 'brief':
      return verbBrief(opts);
    case 'commission-propose':
      return verbCommissionPropose(opts);
    case 'commission-confirm':
      return verbCommissionConfirm(opts);
    case 'seat-hop':
      return verbSeatHop(opts);
    default:
      return {
        ok: false,
        error: 'unknown_primary',
        spelling: SPELLING,
        primary,
        message: `No body for primary '${primary}' (closed dispatcher only)`,
      };
  }
}

/**
 * Canary: scan engine entrypoint sources for harness markers.
 * Flags dependency-like paths (import/require/from) and real listen/createServer
 * call sites — not prose that names the ban.
 * @param {string} engineDir absolute or relative path to engine/
 * @returns {{ ok: boolean, openclaw_hits: object[], daemon_hits: object[], scanned: string[] }}
 */
export function runHarnessCanaries(engineDir) {
  const dir = path.resolve(engineDir);
  const files = listJsFiles(dir);
  const openclaw_hits = [];
  const daemon_hits = [];
  const scanned = [];

  // Dependency path only: import/require/from "…openclaw…"
  const forbiddenDep =
    /(?:from\s+|require\s*\(\s*|import\s*\(\s*)['"`][^'"`]*openclaw[^'"`]*['"`]/i;
  // Real server listen loop call sites (not the word "listen" in help text)
  const forbiddenListen = /(?:net|http|https|dgram)?\s*\.?\s*createServer\s*\(|\b\.listen\s*\(\s*\d+/;

  for (const file of files) {
    scanned.push(path.relative(dir, file).split(path.sep).join('/'));
    let text;
    try {
      text = fs.readFileSync(file, 'utf8');
    } catch {
      continue;
    }
    const lines = text.split(/\r?\n/);
    lines.forEach((line, idx) => {
      const trimmed = line.trim();
      // Strip line comments for call-site scan
      const code = trimmed.replace(/\/\/.*$/, '').trim();
      if (!code || code.startsWith('*') || code.startsWith('/*') || code.startsWith('#')) {
        return;
      }
      if (forbiddenDep.test(code)) {
        openclaw_hits.push({
          file: path.basename(file),
          line: idx + 1,
          text: trimmed.slice(0, 120),
        });
      }
      if (forbiddenListen.test(code)) {
        daemon_hits.push({
          file: path.basename(file),
          line: idx + 1,
          text: trimmed.slice(0, 120),
        });
      }
    });
  }

  return {
    ok: openclaw_hits.length === 0 && daemon_hits.length === 0,
    openclaw_hits,
    daemon_hits,
    scanned,
    message:
      openclaw_hits.length || daemon_hits.length
        ? 'Harness canary failed'
        : 'No forbidden dependency paths or daemon listen loops in engine entrypoints',
  };
}

function listJsFiles(dir) {
  const out = [];
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const ent of entries) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (ent.name === 'node_modules' || ent.name === '.git') continue;
      out.push(...listJsFiles(p));
    } else if (ent.isFile() && (ent.name.endsWith('.mjs') || ent.name.endsWith('.js'))) {
      out.push(p);
    }
  }
  return out;
}

/**
 * Rewrite Face markdown narrative sections; preserve Strip fence if present.
 * @param {string} facePath
 * @param {object} narrative
 * @param {string} [priorRaw]
 */
export function writeFaceNarrative(facePath, narrative, priorRaw = '') {
  const prior = typeof priorRaw === 'string' ? priorRaw : '';
  const fence = extractFenceBlock(prior);
  const body = [
    '# Ecgberht — Face',
    '',
    '## North star',
    '',
    narrative.north_star ?? '',
    '',
    '## Active effort',
    '',
    narrative.active_effort ?? '',
    '',
    '## Why next',
    '',
    narrative.why_next ?? '',
    '',
    '## Human wait',
    '',
    narrative.human_wait ?? 'none',
    '',
  ];
  if (narrative.why_stakes) {
    body.push('## Why stakes', '', narrative.why_stakes, '');
  }
  if (fence) {
    body.push('## Strip (instrument)', '', '```json', fence, '```', '');
  }
  fs.mkdirSync(path.dirname(facePath), { recursive: true });
  // Face is the human narrative surface — rewritable, but a truncated Face is
  // still lost work, so it gets the same atomic replacement as Strip.
  writeFileAtomicSync(facePath, `${body.join('\n')}\n`);
}

function extractFenceBlock(markdown) {
  if (!markdown) return null;
  const m = markdown.match(/```(?:json)?\s*\r?\n([\s\S]*?)```/i);
  if (!m) return null;
  const inner = m[1].trim();
  if (!inner.includes('ecgberht-strip') && !inner.includes('"schema"')) return null;
  return inner;
}

function stableEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

// re-export helpers used by tests
export { resolvePrimaryVerb, parseFaceDocument, parseStrip };
