/**
 * Closed verb bodies (W3 + W4 depth table).
 * Dispatcher is closed-list only — no plugin/open dispatch.
 * Write authority: Face narrative rewrite; Strip append-only instruments/receipts.
 * depth-suggest: Strip signals + dispatch table only (LITE bias; no free-form).
 */

import fs from 'node:fs';
import { writeFileAtomicSync } from './durable-write.mjs';
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
    commissioned_as: null,
    skill: null,
    depth_cell: null,
    proposal: null,
    job_id: null,
    seat: null,
    who: null,
    when: null,
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
      '--commissioned-as': 'commissioned_as',
      '--who': 'who',
      '--when': 'when',
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
export function verbUpdate(opts = {}) {
  const verb_name = opts.verb_name ?? 'update';
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
      verb: verb_name,
      primary: 'update',
      project_path,
      message: 'update/heartbeat needs Face or Strip',
    };
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

  if (strip) {
    const instrument = {
      _kind: 'instrument',
      kind: verb_name === 'heartbeat' ? 'heartbeat' : 'update',
      as_of: opts.as_of ?? todayIso(),
      source: 'verb_update',
      ...(opts.strip_tip && typeof opts.strip_tip === 'object' ? opts.strip_tip : {}),
    };
    // Map face active_effort / human_wait into strip tip when provided
    if (face_patch.active_effort != null) instrument.active_effort = face_patch.active_effort;
    if (face_patch.human_wait != null) instrument.human_wait = face_patch.human_wait;
    if (face_patch.why_next != null && instrument.why_next == null) {
      instrument.why_next = face_patch.why_next;
    }

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
