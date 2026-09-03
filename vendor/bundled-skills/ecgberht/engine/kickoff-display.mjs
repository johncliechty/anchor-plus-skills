/**
 * Gate 5 / Wave 5 - Phase 2.2: projection PRECEDENCE for the kickoff display, and the
 * anatomy.json guard.
 *
 * THE PRECEDENCE LAW. The display uses confirmed intent FIRST: when the receipt lineage
 * carries a confirmed kickoff, the intent shown is the Wave 4 intent projection derived
 * from that lineage through the ONE pure derivation seam (deriveKickoffProjection), and
 * the tag-derived map is not consulted - not read, not folded in, NEVER merged. Only when
 * confirmed intent is ABSENT does the display fall back to the tag-derived map: the
 * legacy view folded from roadmap steps tagged with the execution-phase part tags
 * (research / slice / rigor / integrate / harden - journal 0095 named this conflation).
 * The fallback is served VISIBLY marked as fallback (KICKOFF_FALLBACK_MARKER rides the
 * result and the user text says so), carries authoritative: false, and is never combined
 * with confirmed intent under any state. Because the confirmed branch derives from the
 * receipt lineage alone, deleting display data (roadmap.json, the campaign Face, the
 * Strip, the projection caches) cannot change what a confirmed effort displays.
 *
 * THE WRITTEN RETIREMENT TRIGGER. The fallback is temporary by declaration, not by hope:
 * TAG_MAP_FALLBACK_RETIREMENT states, machine-readably, that the tag-derived map retires
 * at the legacy-effort migration - a LATER effort, outside Gate 5 - which moves legacy
 * efforts onto confirmed kickoff lineage. Until then it is fallback only, never merged.
 *
 * THE ANATOMY GUARD. New kickoff paths never write or modify anatomy.json - the optional
 * legacy cockpit plate file journal 0095 flagged as drift-prone. guardKickoffWriteTarget
 * is the named refusal at the kickoff write seam: the Wave 4 projection writer passes
 * every target through it before writeFileAtomicSync, so a kickoff write aimed at any
 * anatomy.json (any directory, any letter case - Windows is case-insensitive) refuses
 * with a named row and writes nothing. KICKOFF_ANATOMY_GUARD is the rule as data.
 *
 * Failure states carry a status code AND user-visible text; confirmed-intent, fallback,
 * missing, empty and unknown are SEPARATE display states (kickoffDisplayFailureTable).
 * An unreadable source answers unknown - the display never guesses, and never quietly
 * falls back when the store that might hold confirmed intent cannot be read. Stdlib
 * only. Source is ASCII on purpose (the repo's mojibake sweep).
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  KICKOFF_STATE,
  kickoffEventsPath,
  readKickoffLineage,
} from './kickoff-lifecycle.mjs';
import { deriveKickoffProjection } from './kickoff-projection.mjs';
import { kickoffFailure } from './kickoff-record.mjs';
import {
  ROADMAP_PART_TAGS,
  buildRoadmapProjection,
  loadProjectRoadmap,
} from './roadmap.mjs';

// -- the display states --------------------------------------------------------------

export const KICKOFF_DISPLAY_SOURCE = Object.freeze({
  CONFIRMED_INTENT: 'confirmed_intent',
  TAG_MAP: 'tag_derived_map',
});

export const KICKOFF_DISPLAY_CODE = Object.freeze({
  CONFIRMED_INTENT: 'KICKOFF_DISPLAY_CONFIRMED_INTENT',
  FALLBACK: 'KICKOFF_DISPLAY_TAG_MAP_FALLBACK',
  MISSING: 'KICKOFF_DISPLAY_MISSING',
  EMPTY: 'KICKOFF_DISPLAY_EMPTY',
  UNKNOWN: 'KICKOFF_DISPLAY_UNKNOWN',
  ANATOMY_REFUSED: 'KICKOFF_ANATOMY_WRITE_REFUSED',
});

/** The visible marking every fallback answer carries - a label, not a schema word. */
export const KICKOFF_FALLBACK_MARKER = 'FALLBACK - tag-derived map (not confirmed intent)';

export const KICKOFF_DISPLAY_TEXT = Object.freeze({
  [KICKOFF_DISPLAY_CODE.CONFIRMED_INTENT]:
    'Confirmed kickoff intent - displayed from the confirmed receipt lineage; the tag-derived map is not consulted and never merged.',
  [KICKOFF_DISPLAY_CODE.FALLBACK]:
    'FALLBACK VIEW - no confirmed kickoff intent yet; this map is derived from execution-phase tags, is not confirmed intent, and is never merged with it. It retires at the legacy-effort migration, a later effort.',
  [KICKOFF_DISPLAY_CODE.MISSING]:
    'No kickoff display source exists - neither a kickoff store nor a roadmap; nothing to display.',
  [KICKOFF_DISPLAY_CODE.EMPTY]:
    'The kickoff display sources exist but hold nothing displayable - no confirmed intent and no tagged steps.',
  [KICKOFF_DISPLAY_CODE.UNKNOWN]:
    'The kickoff display state is unknown (<error>) - reported as unknown, never guessed.',
  [KICKOFF_DISPLAY_CODE.ANATOMY_REFUSED]:
    'Refused: a kickoff path tried to write anatomy.json (<error>) - a new kickoff never writes or modifies anatomy.json.',
});

/**
 * THE WRITTEN RETIREMENT TRIGGER for the fallback, as data. The tag-derived map is
 * display fallback ONLY until the legacy-effort migration - a later effort, outside
 * Gate 5 - moves legacy efforts onto confirmed kickoff lineage; then it retires.
 */
export const TAG_MAP_FALLBACK_RETIREMENT = Object.freeze({
  fallback: 'tag_derived_map',
  never_merged: true,
  retirement_trigger: 'legacy_effort_migration',
  scheduled_as: 'a_later_effort',
  written:
    'The tag-derived map retires when the legacy-effort migration (a later effort, outside Gate 5) moves legacy efforts onto confirmed kickoff lineage. Until then it is display fallback only and is never merged with confirmed intent.',
});

/** @param {string} code @param {object} [extra] a failure row in this surface's voice */
export function kickoffDisplayFailure(code, extra = {}) {
  if (!Object.hasOwn(KICKOFF_DISPLAY_TEXT, code)) return kickoffFailure(code, extra);
  const error = extra.error ?? String(code).toLowerCase();
  const text = KICKOFF_DISPLAY_TEXT[code].replace(/<error>/g, String(error));
  return {
    ok: false,
    code,
    status_code: code,
    error,
    text,
    user_text: text,
    authoritative: false,
    ...extra,
  };
}

/**
 * Machine-readable failure-state table for the display surface. The wave's five named
 * display states - confirmed intent, fallback, missing, empty, unknown - are SEPARATE
 * rows with five distinct codes; the anatomy guard's refusal is its own row beside them.
 *
 * @returns {ReadonlyArray<{state: string, surface: string, status_code: string, user_text: string}>}
 */
export function kickoffDisplayFailureTable() {
  const row = (state, code) => Object.freeze({
    state,
    surface: 'kickoff-display',
    status_code: code,
    user_text: KICKOFF_DISPLAY_TEXT[code],
  });
  return Object.freeze([
    row('confirmed-intent', KICKOFF_DISPLAY_CODE.CONFIRMED_INTENT),
    row('fallback', KICKOFF_DISPLAY_CODE.FALLBACK),
    row('missing', KICKOFF_DISPLAY_CODE.MISSING),
    row('empty-but-valid', KICKOFF_DISPLAY_CODE.EMPTY),
    row('unknown', KICKOFF_DISPLAY_CODE.UNKNOWN),
    row('anatomy-write-refused', KICKOFF_DISPLAY_CODE.ANATOMY_REFUSED),
  ]);
}

// -- the anatomy guard ---------------------------------------------------------------

/** The legacy cockpit plate file no new kickoff path may touch. */
export const KICKOFF_ANATOMY_FILE = 'anatomy.json';

/** The guard as data - what is forbidden, where it is enforced, and by which function. */
export const KICKOFF_ANATOMY_GUARD = Object.freeze({
  forbidden_file: KICKOFF_ANATOMY_FILE,
  applies_to: 'new_kickoff_paths',
  rule: 'a new kickoff never writes or modifies anatomy.json',
  enforced_at: 'guardKickoffWriteTarget',
  wired_into: Object.freeze(['engine/kickoff-projection.mjs#writeKickoffProjection']),
});

/**
 * The named refusal at the kickoff write seam. Every kickoff-owned file write passes its
 * target through here first; a target whose file name is anatomy.json - in any directory,
 * any letter case (Windows file systems are case-insensitive) - refuses with the guard's
 * own row and nothing is written. Pure: no disk, no clock.
 *
 * @param {string} filePath the write target (absolute or relative, either separator)
 * @returns {{ok: true, target: string} | object} the pass, or the ANATOMY_REFUSED row
 */
export function guardKickoffWriteTarget(filePath) {
  const target = String(filePath ?? '');
  const base = target.split(/[\\/]/).pop().trim().toLowerCase();
  if (base === KICKOFF_ANATOMY_FILE) {
    return kickoffDisplayFailure(KICKOFF_DISPLAY_CODE.ANATOMY_REFUSED, {
      error: 'kickoff_write_target_anatomy_json',
      target,
      written: false,
      guard: KICKOFF_ANATOMY_GUARD,
    });
  }
  return { ok: true, target };
}

// -- the tag-derived map (fallback only) ---------------------------------------------

const firstLine = (value) => String(value ?? '').split('\n', 1)[0].trim();

/**
 * Fold the legacy tag-derived map from a roadmap container - the display view journal
 * 0095 called the conflation of deliverable anatomy with execution order. Pure. Reads the
 * stored projection when one is present (legacy files carry it), else folds the events.
 * The result is BORN marked: fallback true, authoritative false, the visible marker on it.
 *
 * @param {object|null} roadmap a parsed roadmap container
 * @returns {{source: string, fallback: true, authoritative: false, marker: string,
 *   part_tags: string[], parts: Array<{part: string, steps: object[]}>, step_count: number}}
 */
export function deriveKickoffTagMap(roadmap) {
  const stored = Array.isArray(roadmap?.roadmap_projection) ? roadmap.roadmap_projection : [];
  const steps = stored.length
    ? stored
    : buildRoadmapProjection(roadmap?.roadmap_events).projection;
  const tagged = steps.filter((step) => step && ROADMAP_PART_TAGS.includes(step.part));
  const parts = ROADMAP_PART_TAGS
    .map((part) => ({
      part,
      steps: tagged
        .filter((step) => step.part === part)
        .map((step) => ({ id: step.id, name: step.name, status: step.status ?? null })),
    }))
    .filter((group) => group.steps.length > 0);
  return {
    source: 'roadmap_part_tags',
    fallback: true,
    authoritative: false,
    marker: KICKOFF_FALLBACK_MARKER,
    part_tags: [...ROADMAP_PART_TAGS],
    parts,
    step_count: tagged.length,
  };
}

// -- the selector --------------------------------------------------------------------

/** The open draft as the display carries it: a summary, marked draft-not-applied. */
function openDraftSummary(open) {
  if (!open) return null;
  return {
    version: open.version,
    proposal_hash: open.proposal_hash,
    goal: firstLine(open.goal),
    applied: false,
  };
}

/** The unknown row, carrying the source's own code - reported, never guessed over. */
function unknownDisplay(cause, extra = {}) {
  return kickoffDisplayFailure(KICKOFF_DISPLAY_CODE.UNKNOWN, {
    error: cause?.error ?? String(cause?.code ?? 'display_source_unreadable').toLowerCase(),
    cause_code: cause?.code ?? null,
    fallback: false,
    merged: false,
    tag_map_consulted: false,
    ...extra,
  });
}

/**
 * Select the display projection for an effort - THE precedence seam.
 *
 * Confirmed intent first: a confirmed receipt lineage answers with the Wave 4 intent
 * projection derived from that lineage alone; the roadmap is never read on this branch,
 * so the tag map cannot leak in and deleting display data cannot change the answer.
 * Only when nothing is confirmed is the tag-derived map consulted, and it is served
 * marked as fallback, never merged. Neither source readable enough to answer -> unknown.
 * Neither source exists -> missing. Sources exist but hold nothing -> empty. An OPEN
 * draft rides every unconfirmed answer as a summary, applied: false, never as intent.
 *
 * @param {string} projectPath
 * @param {{max_bytes?: number}} [opts]
 */
export function selectKickoffDisplay(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const lineage = readKickoffLineage(root, opts);
  if (!lineage.ok) return unknownDisplay(lineage);

  if (lineage.confirmed && lineage.receipt) {
    const derived = deriveKickoffProjection(lineage);
    if (!derived.ok) return unknownDisplay(derived);
    return {
      ok: true,
      code: KICKOFF_DISPLAY_CODE.CONFIRMED_INTENT,
      status_code: KICKOFF_DISPLAY_CODE.CONFIRMED_INTENT,
      user_text: KICKOFF_DISPLAY_TEXT[KICKOFF_DISPLAY_CODE.CONFIRMED_INTENT],
      source: KICKOFF_DISPLAY_SOURCE.CONFIRMED_INTENT,
      authoritative: true,
      fallback: false,
      merged: false,
      tag_map_consulted: false,
      version: derived.version,
      proposal_hash: derived.proposal_hash,
      receipt_hash: derived.receipt_hash,
      intent: derived.projection.intent,
      rendered_prose: derived.projection.confirmed.rendered_prose,
      open_draft: derived.open_draft,
    };
  }

  // Nothing confirmed. Only NOW may the tag-derived map answer - fallback, never merged.
  const loaded = loadProjectRoadmap(root);
  if (!loaded.ok) return unknownDisplay({ code: null, error: 'roadmap_unreadable' });
  const openDraft = openDraftSummary(lineage.open);

  if (loaded.exists && loaded.roadmap) {
    const map = deriveKickoffTagMap(loaded.roadmap);
    if (map.step_count > 0) {
      return {
        ok: true,
        code: KICKOFF_DISPLAY_CODE.FALLBACK,
        status_code: KICKOFF_DISPLAY_CODE.FALLBACK,
        user_text: KICKOFF_DISPLAY_TEXT[KICKOFF_DISPLAY_CODE.FALLBACK],
        source: KICKOFF_DISPLAY_SOURCE.TAG_MAP,
        authoritative: false,
        fallback: true,
        fallback_marker: KICKOFF_FALLBACK_MARKER,
        merged: false,
        confirmed_intent: null,
        tag_map: map,
        retirement: TAG_MAP_FALLBACK_RETIREMENT,
        open_draft: openDraft,
      };
    }
  }

  if (!loaded.exists && !fs.existsSync(kickoffEventsPath(root))) {
    return kickoffDisplayFailure(KICKOFF_DISPLAY_CODE.MISSING, {
      error: 'no_display_source',
      fallback: false,
      merged: false,
      open_draft: null,
    });
  }
  return kickoffDisplayFailure(KICKOFF_DISPLAY_CODE.EMPTY, {
    error: 'nothing_displayable',
    state: lineage.state ?? KICKOFF_STATE.EMPTY,
    fallback: false,
    merged: false,
    open_draft: openDraft,
  });
}
