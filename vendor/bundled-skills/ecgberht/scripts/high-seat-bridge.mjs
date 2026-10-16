/**
 * TW6 / Wave 17 — High Seat bridge: the ONE entry the live-Anchor MAIN-dashboard
 * docked overlay calls (spawned as `node scripts/high-seat-bridge.mjs …` by
 * the /api/ecgberht/high_seat* handlers). It only composes the engine's
 * closed read surfaces. Wave 17: --badge and the portfolio fold answer from
 * the portfolio INDEX (query / attention cells / badge cache) behind an
 * index-only trap — discoverStrips / verbStatus root-walk is unreachable
 * from the badge route.
 *
 * Modes (all print a single JSON object to stdout — STDOUT PURITY):
 *   --roots <a;b;…>                     → Screen 2 High Seat view model
 *   --badge                             → ⚑ badge count from index cache only
 *   --roots <…> --bring-up <path>       → in-overlay hop + Screen 3 packet view
 *   --packet <path>                     → Screen 3 packet view for one project
 *   --override <json>                   → balancing override → receipt (A1/A3)
 *   --decide <json>                     → packet answer → receipt moving the
 *                                         Roadmap (single writer, persisted)
 *   --roots <…> --speak <text>          → compile saybox talk (closed acts)
 *   --request-full <json>               → TW7 capacity hard-stop
 *   --skipped <json-array>              → semicolon-skipped roots as unknown rows
 *
 * Roots are ';'-separated (Windows-safe). Roots containing ';' must NOT ride
 * the joined argv — pass them via --skipped JSON so they render as unknown
 * rows (row count never shrinks). No host-absolute path is baked in here.
 */

import {
  assembleHighSeat,
  applyBalancingOverride,
  bringItUp,
  highSeatSpeak,
  closeHighSeat,
} from '../engine/high-seat.mjs';
import { requestFullRun, applyCapacityChoice } from '../engine/stand-up.mjs';
import { assemblePacketView, answerPacketQuestion } from '../engine/packet-view.mjs';
import { assembleBriefPacket } from '../engine/brief.mjs';
import { loadProjectRoadmap } from '../engine/roadmap.mjs';
import {
  assemblePortfolioGlance,
  buildBadgeFromIndex,
  mapBridgeGarbage,
  partitionRootsByDelimiter,
  ROOT_DELIM,
  GLANCE_CODE,
  GLANCE_TEXT,
} from '../engine/high-seat-glance.mjs';

/** Parse the tiny closed flag set (no free-form option surface). */
export function parseHighSeatArgs(argv = []) {
  const out = {
    roots: [],
    skipped: [],
    badge: false,
    bringUp: null,
    packet: null,
    override: null,
    decide: null,
    speak: null,
    close: false,
    markSeen: false,
    requestFull: null,
    home: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === '--roots' && argv[i + 1] != null) {
      // Transportable roots only — delimiter-containing paths are corrupted
      // by a join/split; they arrive via --skipped instead.
      out.roots = argv[++i]
        .split(ROOT_DELIM)
        .map((r) => r.trim())
        .filter(Boolean);
    } else if (t === '--skipped' && argv[i + 1] != null) {
      try {
        const parsed = JSON.parse(argv[++i]);
        out.skipped = Array.isArray(parsed) ? parsed : [];
      } catch {
        out.skipped = [];
      }
    } else if (t === '--home' && argv[i + 1] != null) {
      out.home = argv[++i];
    } else if (t === '--badge') out.badge = true;
    else if (t === '--bring-up' && argv[i + 1] != null) out.bringUp = argv[++i];
    else if (t === '--packet' && argv[i + 1] != null) out.packet = argv[++i];
    else if (t === '--override' && argv[i + 1] != null) out.override = argv[++i];
    else if (t === '--decide' && argv[i + 1] != null) out.decide = argv[++i];
    else if (t === '--speak' && argv[i + 1] != null) out.speak = argv[++i];
    else if (t === '--close') out.close = true;
    else if (t === '--mark-seen') out.markSeen = true;
    else if (t === '--request-full' && argv[i + 1] != null)
      out.requestFull = argv[++i];
  }
  return out;
}

/**
 * TW7 capacity hard-stop payload. Fields arrive as JSON:
 * { capacity?, choice?, who?, why?, from?, to?, project_id? }.
 * With a choice → one of the three honest options (override builds and
 * validates its receipt); without → the raw FULL request, which under
 * unknown capacity refuses with the spoken Screen 4 chamber.
 * @param {{ json: string }} opts
 */
export function buildRequestFullPayload(opts = {}) {
  let fields;
  try {
    fields = JSON.parse(opts.json);
  } catch {
    return {
      ok: false,
      error: 'request_full_bad_json',
      message: 'request-full fields must be JSON { capacity?, choice?, who?, why? }',
    };
  }
  const result = fields.choice != null
    ? applyCapacityChoice(fields.choice, fields)
    : requestFullRun(fields);
  return { ...result, mode: 'request-full' };
}

/**
 * High Seat payload: the Screen 2 view model.
 * Wave 17: folds N projections from the portfolio index (no root walk).
 * Semicolon-skipped roots render as named unknown rows (row count preserved).
 * @param {{ roots?: string[], skipped?: string[], home?: string, inject?: object }} opts
 */
export function buildHighSeatPayload(opts = {}) {
  const inject = opts.inject ?? {};
  // Explicit inject.items / status keep unit-test parity (w12).
  if (Array.isArray(inject.items) || inject.status != null) {
    const high_seat = assembleHighSeat({
      roots: opts.roots ?? [],
      ...inject,
    });
    return { ok: true, mode: 'high-seat', high_seat };
  }

  const part = partitionRootsByDelimiter(opts.roots ?? []);
  const skipped = [
    ...(opts.skipped ?? []),
    ...part.skipped,
    ...(inject.skipped_roots ?? []),
  ];

  const glance = assemblePortfolioGlance({
    home: opts.home ?? inject.home,
    env: inject.env,
    paths: inject.paths,
    skipped_roots: skipped,
    unreadable_projects: inject.unreadable_projects,
    inject,
  });

  if (!glance.ok) {
    return {
      ok: false,
      mode: 'high-seat',
      error: glance.code ?? glance.error ?? GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE,
      code: glance.code ?? glance.error,
      message: glance.message ?? GLANCE_TEXT[GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE],
      glance,
      // Map garbage / missing into the surface failure table — never a blank panel.
      surface: glance.code === GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE
        ? mapBridgeGarbage('bridge_bad_json')
        : {
            code: glance.code,
            text: glance.message,
          },
    };
  }

  const high_seat = assembleHighSeat({
    items: glance.items ?? [],
    ...inject,
    glance,
  });
  return {
    ok: true,
    mode: 'high-seat',
    high_seat,
    glance: {
      row_count: glance.row_count,
      code: glance.code ?? null,
      degraded: glance.degraded ?? [],
      no_walk: glance.no_walk ?? null,
      field_coverage: glance.field_coverage ?? null,
      discoverStrips_reached: false,
    },
    skipped_roots: skipped,
  };
}

/**
 * Badge payload: queue length ONLY — the single ambient signal the main
 * dashboard is allowed to poll (S0-E2).
 *
 * Wave 17 — BADGE PATH RETIRED BY NAME: answers from the portfolio-index
 * badge cache / attention cells behind the index-only trap. Never calls
 * verbStatus or discoverStrips (the legacy root-walk path is unreachable).
 *
 * @param {{ roots?: string[], home?: string, inject?: object }} opts
 */
export function buildBadgePayload(opts = {}) {
  // Index-only — discoverStrips is never reached from this function.
  return buildBadgeFromIndex({
    home: opts.home ?? opts.inject?.home,
    env: opts.inject?.env,
    paths: opts.inject?.paths,
    inject: opts.inject ?? {},
    roots: opts.roots ?? [],
  });
}

/**
 * Bring-it-up payload: in-overlay hop + Screen 3 packet view with zero
 * further gathering (Option P path passport).
 * @param {{ project: string, inject?: object }} opts
 */
export function buildBringUpPayload(opts = {}) {
  const result = bringItUp({ project_path: opts.project, ...(opts.inject ?? {}) });
  if (!result.ok) return result;
  return {
    ok: true,
    mode: 'bring-up',
    hop: result.hop,
    packet_view: result.packet_view,
    further_gathering: result.further_gathering,
    from_cache: result.from_cache,
  };
}

/**
 * Standalone packet payload (Screen 3 for one project; deterministic Phase A).
 * @param {{ project: string, inject?: object }} opts
 */
export function buildPacketPayload(opts = {}) {
  const inject = opts.inject ?? {};
  const packet =
    inject.packet ??
    assembleBriefPacket({
      project: opts.project,
      roots: [],
      altitude: 'project',
      ...inject,
    });
  return {
    ok: true,
    mode: 'packet',
    packet_view: assemblePacketView(packet, inject),
  };
}

/**
 * Override payload: parse the caller's JSON fields and land the balancing
 * override as a validated receipt (A1/A3) — or refuse structurally.
 * @param {{ json: string }} opts
 */
export function buildOverridePayload(opts = {}) {
  let fields;
  try {
    fields = JSON.parse(opts.json);
  } catch {
    return {
      ok: false,
      error: 'override_bad_json',
      message: 'override fields must be JSON { who, why, from, to }',
    };
  }
  const applied = applyBalancingOverride(fields);
  return { ...applied, mode: 'override' };
}

/**
 * Decide payload: the S3-E5 answer lands as a receipt that moves the Roadmap
 * through the single writer (answerPacketQuestion → appendRoadmapEvent) and
 * persists the appended event log. 'not_yet' holds and writes nothing.
 * @param {{ json: string, inject?: object }} opts
 */
export function buildDecidePayload(opts = {}) {
  let fields;
  try {
    fields = JSON.parse(opts.json);
  } catch {
    return {
      ok: false,
      error: 'decide_bad_json',
      message:
        'decide fields must be JSON { project_path, step_id, decision, who, why?, to? }',
    };
  }
  const inject = opts.inject ?? {};
  const projectPath = fields.project_path ?? null;
  let roadmap = inject.roadmap ?? null;
  if (!roadmap) {
    if (!projectPath) {
      return { ok: false, error: 'decide_missing_project_path' };
    }
    const loaded = loadProjectRoadmap(projectPath);
    if (!loaded.ok || !loaded.exists) {
      return {
        ok: false,
        error: 'decide_no_roadmap',
        message: 'no roadmap.json for this project — nothing to move',
      };
    }
    roadmap = loaded.roadmap;
  }
  // Wave 6: high-seat-bridge --decide persists ONLY through the ledger spine
  // (answerPacketQuestion + appendRoadmapEventThroughSpine). Zero direct
  // bare roadmap-container writers outside the spine.
  const result = answerPacketQuestion({
    ...fields,
    roadmap,
    project_path: projectPath && inject.persist !== false ? projectPath : null,
    project_id: fields.project_id ?? roadmap?.project_id ?? null,
    home: inject.home,
    client_event_id: fields.client_event_id,
  });
  if (!result.ok || !result.moved) {
    return { ...result, mode: 'decide', persisted: false };
  }
  const persisted =
    result.persisted === true || result.sot_written === true;
  return { ...result, mode: 'decide', persisted, spine: true };
}

/**
 * Speak payload — compile-only against the closed act table.
 * @param {{ text: string, session?: object }} opts
 */
export function buildHighSeatSpeakPayload(opts = {}) {
  const spoken = highSeatSpeak(opts.text, { session: opts.session });
  return {
    ok: true,
    mode: 'speak',
    compiled: spoken.compiled,
    dialogue_persisted: false,
    store_policy: spoken.store_policy,
  };
}

/**
 * Close payload — the overlay closing law: ledger gains at most `seen`.
 * @param {{ markSeen?: boolean, inject?: object }} opts
 */
export function buildClosePayload(opts = {}) {
  const closed = closeHighSeat({
    mark_seen: opts.markSeen === true,
    ...(opts.inject ?? {}),
  });
  return { ...closed, mode: 'close' };
}

/** Dispatch one bridge invocation (pure — used by tests and by main). */
export function runHighSeatBridge(argv = []) {
  const args = parseHighSeatArgs(argv);
  if (args.requestFull != null)
    return buildRequestFullPayload({ json: args.requestFull });
  if (args.override != null) return buildOverridePayload({ json: args.override });
  if (args.decide != null) return buildDecidePayload({ json: args.decide });
  if (args.speak != null) return buildHighSeatSpeakPayload({ text: args.speak });
  if (args.close) return buildClosePayload({ markSeen: args.markSeen });
  if (args.packet != null) return buildPacketPayload({ project: args.packet });
  if (args.bringUp != null) return buildBringUpPayload({ project: args.bringUp });
  // Wave 17: --badge is index-only (no roots required; cache / attention cells).
  if (args.badge) {
    return buildBadgePayload({
      roots: args.roots,
      home: args.home,
    });
  }
  if (args.roots.length || args.skipped.length || args.home) {
    return buildHighSeatPayload({
      roots: args.roots,
      skipped: args.skipped,
      home: args.home,
    });
  }
  return {
    ok: false,
    error: 'missing_mode',
    message:
      'usage: --roots <a;b;…> [--skipped <json>] [--home <path>] [--badge | --bring-up <path> | --speak <text>] | --badge | --packet <path> | --override <json> | --decide <json> | --request-full <json> | --close [--mark-seen]',
  };
}

const invokedDirectly =
  process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, '/').split('/').pop());

if (invokedDirectly) {
  let result;
  try {
    result = runHighSeatBridge(process.argv.slice(2));
  } catch (err) {
    result = { ok: false, error: 'bridge_failed', message: String(err?.message ?? err) };
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = result.ok ? 0 : 1;
}
