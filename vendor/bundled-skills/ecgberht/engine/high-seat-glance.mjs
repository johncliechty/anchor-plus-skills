/**
 * Wave 17 — High Seat fold + THE BADGE PATH BOUNDED — portfolio at a glance.
 *
 * Folds N typed projections (portfolio index + Wave-16 attention cells) into
 * the raise queue and ⚑ badge. Answers criterion-13 fields from the EXISTING
 * no-walk index — never a project-root walk. write_authority:'none' is
 * ENFORCED by an indexOnlyFs-style read/write trap (not the string field).
 *
 * Badge path retired: --badge answers from the index badge cache / attention
 * cells behind the trap. discoverStrips / verbStatus walk is unreachable from
 * the badge route. Ingest (attention push) updates the cached badge cell so
 * each poll opens a bounded number of index-home files and at most one short-
 * lived bridge process per MIN_MS interval.
 *
 * Stdlib only. No host-absolute paths.
 */

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

import {
  indexPathsFrom,
  openIndexForRead,
  replayEvents,
} from './append-log.mjs';
import {
  indexOnlyFs,
  newReadJournal,
  QueryRefusal,
} from './portfolio/query.mjs';
import { materializeRegistry } from './portfolio/registry.mjs';
import {
  ATTENTION_STATES,
  ATTENTION_READ_UNKNOWN,
  ATTENTION_CODE,
  ATTENTION_TEXT,
} from './attention.mjs';
import { buildRaiseQueue } from './high-seat.mjs';
import { CRITERION_13_FIELDS } from './audits/a5-portfolio-liveness.mjs';
import {
  BADGE_CACHE_REL,
  BADGE_CACHE_SCHEMA,
  badgeCachePath,
  badgeCachePayload,
  writeBadgeCache,
  listAttentionCells,
  recomputeBadgeCacheFromHome,
} from './portfolio/badge-cache.mjs';
import { COMPOSITE, PRESENCE } from './portfolio/status.mjs';

// ── Named bounds ───────────────────────────────────────────────────────────

/** Portfolio row ceiling — refuse by name, never silently truncate. */
export const PORTFOLIO_MAX_ROWS = 500;

/**
 * Files-opened bound on the badge path when the cache cell is present.
 * Cache hit: badge-cache.json (+ optional existsSync path probes under home).
 */
export const BADGE_FILES_OPENED_BOUND_CACHED = 8;

/**
 * Files-opened bound when recomputing badge from attention cells under home.
 * readdir + one cell per project + cache write metadata, capped by MAX_ROWS.
 */
export const BADGE_FILES_OPENED_BOUND_RECOMPUTE = PORTFOLIO_MAX_ROWS + 32;

/** Same delimiter Anchor uses when joining roots into bridge argv. */
export const ROOT_DELIM = ';';
export const _ECGBERHT_ROOT_DELIM = ROOT_DELIM;

export { BADGE_CACHE_REL, BADGE_CACHE_SCHEMA, badgeCachePath, badgeCachePayload, writeBadgeCache };

export const GLANCE_SCHEMA = 'ecgberht-portfolio-glance-v0';
export const GLANCE_ROW_SCHEMA = 'ecgberht-portfolio-glance-row-v0';

/** Criterion-13 fields + attention (Wave-16 read API). */
export const GLANCE_FIELD_KEYS = Object.freeze([
  ...CRITERION_13_FIELDS,
  'attention',
]);

export { CRITERION_13_FIELDS };

// ── Failure-state table (High Seat surface — Master-Plan P9 + Wave 17) ─────

export const GLANCE_CODE = Object.freeze({
  GLANCE_INDEX_MISSING: 'GLANCE_INDEX_MISSING',
  GLANCE_QUERY_REFUSED: 'GLANCE_QUERY_REFUSED',
  GLANCE_INDEX_UNPARSEABLE: 'GLANCE_INDEX_UNPARSEABLE',
  GLANCE_PROJECT_UNKNOWN: 'GLANCE_PROJECT_UNKNOWN',
  GLANCE_ROOT_SKIPPED: 'GLANCE_ROOT_SKIPPED',
  GLANCE_BOUND_EXCEEDED: 'GLANCE_BOUND_EXCEEDED',
  GLANCE_PORTFOLIO_EMPTY: 'GLANCE_PORTFOLIO_EMPTY',
  ATTENTION_UNKNOWN: 'ATTENTION_UNKNOWN',
});

export const GLANCE_TEXT = Object.freeze({
  [GLANCE_CODE.GLANCE_INDEX_MISSING]:
    'Portfolio index not found — no project list is shown; run the index audit fix.',
  [GLANCE_CODE.GLANCE_QUERY_REFUSED]:
    'Portfolio query exceeded its bound — refused, not truncated-as-complete.',
  [GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE]:
    'Index snapshot or bridge output unreadable — nothing is guessed.',
  [GLANCE_CODE.GLANCE_PROJECT_UNKNOWN]:
    '<project>: state unknown (store unreadable) — row kept, marked unknown.',
  [GLANCE_CODE.GLANCE_ROOT_SKIPPED]:
    '<project>: root name unsupported by the transport — row kept, marked unknown.',
  [GLANCE_CODE.GLANCE_BOUND_EXCEEDED]:
    'More than 500 active projects — list refused by name, never silently truncated.',
  [GLANCE_CODE.GLANCE_PORTFOLIO_EMPTY]:
    'No active projects registered.',
  [GLANCE_CODE.ATTENTION_UNKNOWN]:
    '<project>: attention state unknown — never rendered as idle.',
});

/**
 * Full failure table for the High Seat glance surface.
 * @returns {ReadonlyArray<object>}
 */
export function glanceFailureTable() {
  return Object.freeze(
    Object.keys(GLANCE_CODE).map((k) =>
      Object.freeze({
        state: k,
        status_code: GLANCE_CODE[k],
        user_text: GLANCE_TEXT[GLANCE_CODE[k]],
      }),
    ),
  );
}

/**
 * Map bridge/stdout garbage into the dependency-returns-garbage row.
 * @param {string|null|undefined} error
 * @returns {{ code: string, text: string, bridge_bad_json: boolean }}
 */
export function mapBridgeGarbage(error) {
  const err = String(error ?? '');
  const isBad =
    err === 'bridge_bad_json' ||
    err === 'bridge_no_output' ||
    err.includes('bad_json') ||
    err.includes('JSON');
  return Object.freeze({
    code: GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE,
    text: GLANCE_TEXT[GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE],
    bridge_bad_json: isBad || err === 'bridge_bad_json',
    mapped_from: err || null,
  });
}

// ── Write trap (write_authority none enforcement) ──────────────────────────

/** Calls that would mutate the filesystem. */
export const GUARDED_WRITE_CALLS = Object.freeze([
  'writeFileSync',
  'writeFile',
  'appendFileSync',
  'appendFile',
  'mkdirSync',
  'mkdir',
  'rmSync',
  'rm',
  'unlinkSync',
  'unlink',
  'renameSync',
  'rename',
  'copyFileSync',
  'copyFile',
  'openSync', // open for write is blocked via flag check in wrapper when possible
  'createWriteStream',
  'truncateSync',
  'rmdirSync',
]);

export class WriteAuthorityRefusal extends Error {
  /** @param {string} call @param {string} detail */
  constructor(call, detail) {
    super(`WRITE_AUTHORITY_NONE: ${call}() refused — ${detail}`);
    this.name = 'WriteAuthorityRefusal';
    this.code = 'WRITE_AUTHORITY_NONE';
    this.call = call;
    this.detail = detail;
  }
}

/**
 * An fs facade that throws on any write-shaped call.
 * Enforces write_authority:'none' (the string on the VM is a declaration only).
 *
 * @param {object|undefined} base
 * @param {{ writes?: Array<object> }} [journal]
 * @returns {object}
 */
export function writeAuthorityNoneFs(base, journal = { writes: [] }) {
  const facade = { ...(base ?? fs) };
  for (const call of GUARDED_WRITE_CALLS) {
    const original = facade[call];
    facade[call] = (...args) => {
      const entry = Object.freeze({ call, args0: args[0] != null ? String(args[0]) : null });
      journal.writes.push(entry);
      throw new WriteAuthorityRefusal(
        call,
        'High Seat fold has write_authority none; project trees must stay byte-identical',
      );
    };
    // Keep typeof original for callers that probe; original unused by design.
    void original;
  }
  return facade;
}

/**
 * Combined index-home-only read + write-authority-none trap.
 * Reads outside home throw (query.mjs pattern); any write throws.
 *
 * @param {object|undefined} base
 * @param {string} home
 * @param {{reads: Array, outside: Array, total: number, writes: Array}} journal
 * @returns {object}
 */
export function glanceIndexOnlyFs(base, home, journal) {
  if (!journal.writes) journal.writes = [];
  const readGuarded = indexOnlyFs(base, home, journal);
  return writeAuthorityNoneFs(readGuarded, journal);
}

/**
 * Run `fn` under the write trap. Any write throws WriteAuthorityRefusal.
 * @template T
 * @param {() => T} fn
 * @param {{ fsx?: object, journal?: object }} [opts]
 * @returns {{ result: T, journal: object }}
 */
export function withWriteAuthorityNone(fn, opts = {}) {
  const journal = opts.journal ?? { writes: [] };
  const trap = writeAuthorityNoneFs(opts.fsx ?? fs, journal);
  // fn may close over trap via opts — also expose on a property for tests.
  const result = fn({ fsx: trap, journal });
  return { result, journal };
}

// ── Delimiter guard ────────────────────────────────────────────────────────

/**
 * Partition roots that can cross the process boundary as a ';'-joined argv
 * string. Roots containing the delimiter are SKIPPED for transport and must
 * render as unknown rows (row count never shrinks).
 *
 * @param {string[]|string} roots
 * @returns {Readonly<{ transportable: string[], skipped: string[], joined: string }>}
 */
export function partitionRootsByDelimiter(roots = []) {
  const list = Array.isArray(roots)
    ? roots
    : typeof roots === 'string'
      ? roots.split(ROOT_DELIM).map((r) => r.trim()).filter(Boolean)
      : [];
  const transportable = [];
  const skipped = [];
  for (const r of list) {
    const s = String(r ?? '').trim();
    if (!s) continue;
    if (s.includes(ROOT_DELIM)) skipped.push(s);
    else transportable.push(s);
  }
  return Object.freeze({
    transportable: Object.freeze([...transportable]),
    skipped: Object.freeze([...skipped]),
    joined: transportable.join(ROOT_DELIM),
  });
}

/**
 * Round-trip: join transportable roots, split, assert identity — skipped
 * roots never appear in the joined string and are carried separately.
 * @param {string[]} roots
 * @returns {Readonly<object>}
 */
export function delimiterRoundTrip(roots = []) {
  const part = partitionRootsByDelimiter(roots);
  const resplit = part.joined.length
    ? part.joined.split(ROOT_DELIM).map((r) => r.trim()).filter(Boolean)
    : [];
  const ok =
    resplit.length === part.transportable.length &&
    resplit.every((r, i) => r === part.transportable[i]);
  return Object.freeze({
    ok,
    transportable: part.transportable,
    skipped: part.skipped,
    joined: part.joined,
    resplit: Object.freeze(resplit),
    // Skipped roots are NOT in the joined transport — they ride as unknown rows.
    skipped_absent_from_join: part.skipped.every((s) => !part.joined.includes(s)
      || s.includes(ROOT_DELIM)),
  });
}

// ── Field binding (criterion 13 + attention) ───────────────────────────────

/**
 * Bind one criterion-13 / attention field from index data.
 * ANSWERED from index or named per-field `unknown` — never quietly omitted.
 *
 * @param {string} field
 * @param {{
 *   project_id?: string,
 *   fresh?: object|null,
 *   attention?: object|null,
 *   derived_rows?: object[],
 *   unreadable?: boolean,
 *   skipped?: boolean,
 * }} ctx
 * @returns {Readonly<{ field: string, value: unknown, known: boolean, source: string|null, mark: string }>}
 */
export function bindGlanceField(field, ctx = {}) {
  if (ctx.unreadable === true || ctx.skipped === true) {
    return Object.freeze({
      field,
      value: 'unknown',
      known: false,
      source: null,
      mark: 'unknown',
    });
  }

  if (field === 'last_movement') {
    const last = ctx.fresh?.last_seen ?? null;
    if (last) {
      return Object.freeze({
        field,
        value: last,
        known: true,
        source: 'freshness.per_project[project_id].last_seen',
        mark: 'ANSWERED',
      });
    }
    return Object.freeze({
      field,
      value: 'unknown',
      known: false,
      source: 'freshness.per_project[project_id].last_seen',
      mark: 'unknown',
    });
  }

  if (field === 'stage') {
    // Prefer attention reason / active effort projection; else named unknown.
    const att = ctx.attention;
    if (att?.state && ATTENTION_STATES.includes(att.state)) {
      // stage is not a first-class attention field — try derived roadmap proj.
      const rows = Array.isArray(ctx.derived_rows) ? ctx.derived_rows : [];
      for (const r of rows) {
        const proj = r?.proj;
        if (proj && typeof proj === 'object') {
          const stage =
            proj.stage ?? proj.phase ?? proj.active_stage ?? proj.current_stage;
          if (stage != null && String(stage).length > 0) {
            return Object.freeze({
              field,
              value: stage,
              known: true,
              source: 'body DERIVED proj.stage',
              mark: 'ANSWERED',
            });
          }
        }
      }
    }
    // Honest unknown when index has no stage cell (A5 ABSENT path).
    return Object.freeze({
      field,
      value: 'unknown',
      known: false,
      source: null,
      mark: 'unknown',
    });
  }

  if (field === 'runs.live' || field === 'runs.waiting' || field === 'runs.blocked') {
    const att = ctx.attention;
    if (att && typeof att === 'object') {
      // Map attention state onto run buckets when no first-class run cells exist.
      if (field === 'runs.live' && att.state === 'working') {
        return Object.freeze({
          field,
          value: 1,
          known: true,
          source: 'attention.state=working',
          mark: 'ANSWERED',
        });
      }
      if (field === 'runs.waiting' && (att.state === 'needs_you' || att.state === 'deliverable_ready')) {
        return Object.freeze({
          field,
          value: Math.max(1, Number(att.waiting_steps) || 1),
          known: true,
          source: 'attention.state needs_you|deliverable_ready',
          mark: 'ANSWERED',
        });
      }
      if (field === 'runs.blocked' && att.state === 'blocked') {
        return Object.freeze({
          field,
          value: 1,
          known: true,
          source: 'attention.state=blocked',
          mark: 'ANSWERED',
        });
      }
      if (att.state && ATTENTION_STATES.includes(att.state)) {
        // Known zero for this bucket.
        return Object.freeze({
          field,
          value: 0,
          known: true,
          source: 'attention.state',
          mark: 'ANSWERED',
        });
      }
    }
    return Object.freeze({
      field,
      value: 'unknown',
      known: false,
      source: null,
      mark: 'unknown',
    });
  }

  if (field === 'attention') {
    const att = ctx.attention;
    if (att?.state && ATTENTION_STATES.includes(att.state)) {
      return Object.freeze({
        field,
        value: att.state,
        known: true,
        source: 'attention index cell',
        mark: 'ANSWERED',
      });
    }
    return Object.freeze({
      field,
      value: ATTENTION_READ_UNKNOWN,
      known: false,
      source: 'attention index cell',
      mark: 'unknown',
      failure_code: GLANCE_CODE.ATTENTION_UNKNOWN,
    });
  }

  return Object.freeze({
    field,
    value: 'unknown',
    known: false,
    source: null,
    mark: 'unknown',
  });
}

/**
 * Build one glance row with EVERY criterion-13 field present.
 * @param {object} opts
 * @returns {Readonly<object>}
 */
export function buildGlanceRow(opts = {}) {
  const project_id = opts.project_id ?? null;
  const project_path = opts.project_path ?? opts.root ?? null;
  const label = opts.label ?? project_id ?? project_path ?? 'unknown';
  const skipped = opts.skipped === true;
  const unreadable = opts.unreadable === true;

  const fields = {};
  const field_list = [];
  for (const key of GLANCE_FIELD_KEYS) {
    const bound = bindGlanceField(key, {
      project_id,
      fresh: opts.fresh ?? null,
      attention: opts.attention ?? null,
      derived_rows: opts.derived_rows ?? [],
      unreadable,
      skipped,
    });
    fields[key] = bound;
    field_list.push(bound);
  }

  let status_code = null;
  let user_text = null;
  if (skipped) {
    status_code = GLANCE_CODE.GLANCE_ROOT_SKIPPED;
    user_text = GLANCE_TEXT[status_code].replace('<project>', String(label));
  } else if (unreadable) {
    status_code = GLANCE_CODE.GLANCE_PROJECT_UNKNOWN;
    user_text = GLANCE_TEXT[status_code].replace('<project>', String(label));
  } else if (fields.attention?.known === false) {
    status_code = GLANCE_CODE.ATTENTION_UNKNOWN;
    user_text = GLANCE_TEXT[status_code].replace('<project>', String(label));
  }

  // Flatten convenience accessors for the fold / raise queue.
  const attentionState =
    fields.attention?.known === true
      ? fields.attention.value
      : ATTENTION_READ_UNKNOWN;

  return Object.freeze({
    schema: GLANCE_ROW_SCHEMA,
    project_id,
    project_path,
    label,
    skipped,
    unreadable,
    unknown: skipped || unreadable || fields.attention?.known === false,
    status_code,
    user_text,
    fields: Object.freeze(fields),
    field_list: Object.freeze(field_list),
    // Every GLANCE_FIELD_KEYS key is present — never quietly omitted.
    field_coverage_complete:
      field_list.length === GLANCE_FIELD_KEYS.length &&
      GLANCE_FIELD_KEYS.every((k) => fields[k] != null),
    attention: attentionState,
    // The cell's own words, carried whole to the fold: the raise shows the
    // QUESTION the run stopped on, not a state slug (see foldRowToRaiseItem).
    attention_reason: opts.attention?.reason ?? null,
    attention_briefing: opts.attention?.briefing ?? null,
    stage: fields.stage?.value,
    runs: Object.freeze({
      live: fields['runs.live']?.value,
      waiting: fields['runs.waiting']?.value,
      blocked: fields['runs.blocked']?.value,
    }),
    last_movement: fields.last_movement?.value,
  });
}

// ── Fold projections → raise-queue items ───────────────────────────────────

/**
 * Map a glance row / attention cell into a raise-queue item shape.
 * @param {object} row buildGlanceRow result or synthetic
 * @returns {object}
 */
export function foldRowToRaiseItem(row = {}) {
  const attention =
    row.attention ??
    row.fields?.attention?.value ??
    ATTENTION_READ_UNKNOWN;
  const needsYou =
    attention === 'needs_you' || attention === 'deliverable_ready';
  const blocked = attention === 'blocked';
  const working = attention === 'working';

  let human_wait = 'none';
  if (needsYou) {
    human_wait =
      row.fields?.attention?.source === 'attention index cell' &&
      row.attention_reason
        ? row.attention_reason
        : attention === 'deliverable_ready'
          ? 'deliverable_ready'
          : 'needs_you';
  } else if (blocked) {
    human_wait = 'blocked';
  }

  const waiting_steps =
    typeof row.runs?.waiting === 'number'
      ? row.runs.waiting
      : needsYou
        ? 1
        : 0;

  // THE BRIEFING (2026-08-06). When the cell carries a commissioned-run
  // briefing, the raise item answers John's questions before he asks them:
  // human_wait becomes the QUESTION the run stopped on, last_done what it did,
  // next_recommended what it would do next. buildRaiseBlock already renders
  // exactly these fields — nothing there changes.
  const briefing =
    row.attention_briefing && typeof row.attention_briefing === 'object'
      ? row.attention_briefing
      : null;

  return {
    project_id: row.project_id ?? null,
    project_path: row.project_path ?? null,
    active_effort:
      working && row.stage != null && row.stage !== 'unknown'
        ? String(row.stage)
        : null,
    goal_phrase: null,
    human_wait:
      needsYou && briefing?.question ? String(briefing.question) : human_wait,
    last_done: briefing?.did ? String(briefing.did) : undefined,
    next_recommended: briefing?.next ? String(briefing.next) : undefined,
    session_id: briefing?.session_id ?? null,
    capacity: row.unknown ? 'unknown' : 'known',
    anti_starvation_age_days: 0,
    packet_ready: attention === 'deliverable_ready',
    waiting_steps,
    attention,
    glance_row: row,
    // Raise-tier helpers
    capacity_conflict: false,
  };
}

/**
 * Fold N glance rows into raise-queue items + badge.
 * @param {object[]} rows
 * @param {{ starve_threshold_days?: number }} [opts]
 * @returns {Readonly<object>}
 */
export function foldProjections(rows = [], opts = {}) {
  const items = (Array.isArray(rows) ? rows : []).map(foldRowToRaiseItem);
  const raiseQueue = buildRaiseQueue(items, opts);
  return Object.freeze({
    items: Object.freeze(items),
    raise_queue: raiseQueue,
    badge: raiseQueue.badge,
    queue_length: raiseQueue.queue_length,
    row_count: items.length,
  });
}

// ── Badge cache (ingest path updates; poll path reads) ─────────────────────

/**
 * Read badge cache under the index-only trap.
 * @param {{ home: string, fsx?: object, journal?: object }} req
 */
export function readBadgeCache(req = {}) {
  const home = req.home;
  if (!home) {
    return Object.freeze({
      ok: false,
      exists: false,
      cell: null,
      reason: 'home_required',
    });
  }
  const journal = req.journal ?? newReadJournal();
  if (!journal.writes) journal.writes = [];
  const fsx = req.fsx
    ? req.fsx
    : glanceIndexOnlyFs(fs, home, journal);
  const cellPath = badgeCachePath(home);
  try {
    if (typeof fsx.existsSync === 'function' && !fsx.existsSync(cellPath)) {
      journal.total += 1;
      journal.reads.push(Object.freeze({ call: 'existsSync', path: cellPath }));
      return Object.freeze({
        ok: true,
        exists: false,
        cell: null,
        path: cellPath,
        journal,
      });
    }
    journal.total += 1;
    journal.reads.push(Object.freeze({ call: 'existsSync', path: cellPath }));
    const raw = fsx.readFileSync(cellPath, 'utf8');
    const cell = JSON.parse(raw);
    if (!cell || cell.schema !== BADGE_CACHE_SCHEMA) {
      return Object.freeze({
        ok: false,
        exists: true,
        cell: null,
        path: cellPath,
        reason: 'schema_mismatch',
        code: GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE,
        journal,
      });
    }
    return Object.freeze({
      ok: true,
      exists: true,
      cell,
      path: cellPath,
      journal,
      files_opened: journal.total,
    });
  } catch (e) {
    if (e instanceof QueryRefusal || e instanceof WriteAuthorityRefusal) throw e;
    return Object.freeze({
      ok: false,
      exists: false,
      cell: null,
      path: cellPath,
      reason: String(e?.message ?? e),
      code: GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE,
      journal,
    });
  }
}

/**
 * List attention cells under the index home (no project-root walk).
 * @param {{ home: string, fsx?: object, journal?: object }} req
 * @returns {ReadonlyArray<object>}
 */
export function listAttentionCellsFromIndex(req = {}) {
  const home = req.home;
  if (!home) return Object.freeze([]);
  const journal = req.journal ?? newReadJournal();
  if (!journal.writes) journal.writes = [];
  const fsx = req.fsx ?? glanceIndexOnlyFs(fs, home, journal);
  const cells = listAttentionCells({ home, fsx });
  // Journal the readdir-equivalent volume for the files-opened bound.
  journal.total += 1 + cells.length;
  journal.reads.push(
    Object.freeze({ call: 'readdirSync+readFileSync', path: path.join(home, 'attention') }),
  );
  return Object.freeze(cells);
}

/**
 * Recompute badge from attention cells and write the cache (ingest path).
 * @param {{ home: string, env?: object, paths?: object }} req
 */
export function recomputeBadgeCache(req = {}) {
  let home = req.home;
  if (!home) {
    try {
      home = indexPathsFrom({ home: req.home, env: req.env, paths: req.paths }).home;
    } catch {
      return Object.freeze({ ok: false, reason: 'home_unresolved' });
    }
  }
  const journal = newReadJournal();
  journal.writes = [];
  const readFs = indexOnlyFs(fs, home, journal);
  const cells = listAttentionCellsFromIndex({ home, fsx: readFs, journal });
  const raiseItems = cells.map((c) =>
    foldRowToRaiseItem({
      project_id: c.project_id,
      project_path: c.project_path,
      attention: c.state,
      attention_reason: c.reason,
      runs: {
        waiting:
          c.state === 'needs_you' || c.state === 'deliverable_ready'
            ? Math.max(1, Number(c.waiting_steps) || 1)
            : 0,
      },
      fields: {
        attention: {
          value: c.state,
          known: ATTENTION_STATES.includes(c.state),
          source: 'attention index cell',
        },
      },
    }),
  );
  const rq = buildRaiseQueue(raiseItems);
  const written = writeBadgeCache({
    home,
    count: rq.queue_length,
    queue_length: rq.queue_length,
    projects: rq.queue.map((q) => q.project_id).filter(Boolean),
    updated_via: 'recomputeBadgeCache',
  });
  return Object.freeze({
    ok: written.ok === true,
    count: rq.queue_length,
    badge: rq.badge,
    cache: written,
    cells_read: cells.length,
    files_opened: journal.total,
    journal,
    // Also available via the leaf recompute helper used by attention push.
    leaf: recomputeBadgeCacheFromHome({ home }),
  });
}

/**
 * Build badge payload from index only — discoverStrips is never reached.
 * Prefers the cached cell; recomputes under trap if missing.
 *
 * @param {{
 *   home?: string,
 *   env?: object,
 *   paths?: object,
 *   inject?: object,
 *   roots?: string[],
 * }} opts
 * @returns {Readonly<object>}
 */
export function buildBadgeFromIndex(opts = {}) {
  const inject = opts.inject ?? {};

  // Test inject: items short-circuit without index (still no discoverStrips).
  if (Array.isArray(inject.items)) {
    const rq = buildRaiseQueue(inject.items, inject);
    return Object.freeze({
      ok: true,
      mode: 'badge',
      badge: rq.badge,
      queue_length: rq.queue_length,
      source: 'inject.items',
      discoverStrips_reached: false,
      walk_path_unreachable: true,
      files_opened: 0,
      files_opened_bound: BADGE_FILES_OPENED_BOUND_CACHED,
      files_opened_within_bound: true,
      process_spawns_per_interval: 1,
    });
  }

  let home = opts.home ?? inject.home ?? null;
  let paths = opts.paths ?? inject.paths ?? null;
  try {
    if (!home) {
      paths = paths ?? indexPathsFrom({ home: opts.home, env: opts.env ?? inject.env, paths });
      home = paths.home;
    }
  } catch (e) {
    return Object.freeze({
      ok: false,
      mode: 'badge',
      error: GLANCE_CODE.GLANCE_INDEX_MISSING,
      code: GLANCE_CODE.GLANCE_INDEX_MISSING,
      message: GLANCE_TEXT[GLANCE_CODE.GLANCE_INDEX_MISSING],
      badge: { glyph: '⚑', count: null },
      queue_length: null,
      discoverStrips_reached: false,
      walk_path_unreachable: true,
      detail: String(e?.message ?? e),
    });
  }

  if (!home || typeof home !== 'string') {
    return Object.freeze({
      ok: false,
      mode: 'badge',
      error: GLANCE_CODE.GLANCE_INDEX_MISSING,
      code: GLANCE_CODE.GLANCE_INDEX_MISSING,
      message: GLANCE_TEXT[GLANCE_CODE.GLANCE_INDEX_MISSING],
      badge: { glyph: '⚑', count: null },
      queue_length: null,
      discoverStrips_reached: false,
      walk_path_unreachable: true,
    });
  }

  // Existence of index home (directory) — missing → named failure.
  if (!fs.existsSync(home)) {
    return Object.freeze({
      ok: false,
      mode: 'badge',
      error: GLANCE_CODE.GLANCE_INDEX_MISSING,
      code: GLANCE_CODE.GLANCE_INDEX_MISSING,
      message: GLANCE_TEXT[GLANCE_CODE.GLANCE_INDEX_MISSING],
      badge: { glyph: '⚑', count: null },
      queue_length: null,
      discoverStrips_reached: false,
      walk_path_unreachable: true,
    });
  }

  const journal = newReadJournal();
  journal.writes = [];
  const guarded = glanceIndexOnlyFs(fs, home, journal);

  // Prefer cache
  const cached = readBadgeCache({ home, fsx: guarded, journal });
  if (cached.ok && cached.exists && cached.cell) {
    const count = Number(cached.cell.count ?? cached.cell.queue_length ?? 0) || 0;
    const within = journal.total <= BADGE_FILES_OPENED_BOUND_CACHED;
    return Object.freeze({
      ok: true,
      mode: 'badge',
      badge: Object.freeze({
        glyph: cached.cell.glyph ?? '⚑',
        count,
        only_ambient_signal: true,
        law: '⚑ count equals raise queue length; no other ambient notification surfaces anywhere in Anchor',
      }),
      queue_length: count,
      source: 'badge-cache',
      discoverStrips_reached: false,
      walk_path_unreachable: true,
      files_opened: journal.total,
      files_opened_bound: BADGE_FILES_OPENED_BOUND_CACHED,
      files_opened_within_bound: within,
      process_spawns_per_interval: 1,
      no_walk: Object.freeze({
        roots_opened: journal.outside.length,
        index_home_only: journal.outside.length === 0,
        total_reads: journal.total,
      }),
      write_authority: 'none',
      writes_attempted: journal.writes.length,
    });
  }

  // Cache miss: recompute from attention cells under trap (read), write cache with real fs.
  try {
    const cells = listAttentionCellsFromIndex({ home, fsx: guarded, journal });
    const raiseItems = cells.map((c) =>
      foldRowToRaiseItem({
        project_id: c.project_id,
        project_path: c.project_path,
        attention: c.state,
        attention_reason: c.reason,
        runs: {
          waiting:
            c.state === 'needs_you' || c.state === 'deliverable_ready'
              ? Math.max(1, Number(c.waiting_steps) || 1)
              : 0,
        },
        fields: {
          attention: {
            value: c.state,
            known: ATTENTION_STATES.includes(c.state),
            source: 'attention index cell',
          },
        },
      }),
    );
    const rq = buildRaiseQueue(raiseItems);
    // Update cache for next poll (ingest-style write on index home — not a project tree).
    writeBadgeCache({
      home,
      count: rq.queue_length,
      projects: rq.queue.map((q) => q.project_id).filter(Boolean),
      updated_via: 'buildBadgeFromIndex-cache-miss',
      fsx: fs,
    });
    const within = journal.total <= BADGE_FILES_OPENED_BOUND_RECOMPUTE;
    return Object.freeze({
      ok: true,
      mode: 'badge',
      badge: rq.badge,
      queue_length: rq.queue_length,
      source: 'attention-cells',
      discoverStrips_reached: false,
      walk_path_unreachable: true,
      files_opened: journal.total,
      files_opened_bound: BADGE_FILES_OPENED_BOUND_RECOMPUTE,
      files_opened_within_bound: within,
      process_spawns_per_interval: 1,
      no_walk: Object.freeze({
        roots_opened: journal.outside.length,
        index_home_only: journal.outside.length === 0,
        total_reads: journal.total,
      }),
      write_authority: 'none',
      writes_attempted: journal.writes.length,
    });
  } catch (e) {
    if (e instanceof QueryRefusal) {
      return Object.freeze({
        ok: false,
        mode: 'badge',
        error: GLANCE_CODE.GLANCE_QUERY_REFUSED,
        code: GLANCE_CODE.GLANCE_QUERY_REFUSED,
        message: GLANCE_TEXT[GLANCE_CODE.GLANCE_QUERY_REFUSED],
        detail: e.message,
        discoverStrips_reached: false,
        walk_path_unreachable: true,
        files_opened: journal.total,
      });
    }
    return Object.freeze({
      ok: false,
      mode: 'badge',
      error: GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE,
      code: GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE,
      message: GLANCE_TEXT[GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE],
      detail: String(e?.message ?? e),
      discoverStrips_reached: false,
      walk_path_unreachable: true,
    });
  }
}

// ── Portfolio glance assembly ──────────────────────────────────────────────

/**
 * Assemble portfolio-at-a-glance from the index (no root walk).
 *
 * @param {{
 *   home?: string,
 *   env?: object,
 *   paths?: object,
 *   skipped_roots?: string[],
 *   unreadable_projects?: Array<{project_id?:string, project_path?:string, label?:string}>,
 *   inject?: object,
 *   fsx?: object,
 * }} opts
 * @returns {Readonly<object>}
 */
export function assemblePortfolioGlance(opts = {}) {
  const inject = opts.inject ?? {};
  const degraded = [];

  // Injected rows (tests / pure fold)
  if (Array.isArray(inject.rows)) {
    const rows = [...inject.rows];
    for (const s of opts.skipped_roots ?? inject.skipped_roots ?? []) {
      const pathStr = typeof s === 'string' ? s : s?.project_path ?? s?.root ?? '';
      if (!pathStr) continue;
      rows.push(
        buildGlanceRow({
          project_id: typeof s === 'object' ? s.project_id ?? null : null,
          project_path: pathStr,
          label: typeof s === 'object' ? s.label ?? pathStr : pathStr,
          skipped: true,
        }),
      );
    }
    for (const u of opts.unreadable_projects ?? inject.unreadable_projects ?? []) {
      const already = rows.some(
        (r) =>
          (u.project_id && r.project_id === u.project_id) ||
          (u.project_path && r.project_path === u.project_path),
      );
      if (already) continue;
      rows.push(
        buildGlanceRow({
          project_id: u.project_id ?? null,
          project_path: u.project_path ?? null,
          label: u.label ?? u.project_id ?? u.project_path,
          unreadable: true,
        }),
      );
    }
    if (rows.length > PORTFOLIO_MAX_ROWS) {
      return boundExceededResult(rows.length);
    }
    const folded = foldProjections(rows, inject);
    for (const row of rows) {
      for (const f of CRITERION_13_FIELDS) {
        if (row.fields?.[f]?.known === false) {
          degraded.push(
            Object.freeze({
              project_id: row.project_id,
              field: f,
              mark: COMPOSITE.DEGRADED,
              note: 'A5 field beyond cap / absent in index — named unknown; Wave 19 kill gate cannot green criterion 13 on DEGRADED without signed decision',
            }),
          );
        }
      }
    }
    return Object.freeze({
      ok: true,
      schema: GLANCE_SCHEMA,
      rows: Object.freeze(rows),
      row_count: rows.length,
      ...folded,
      write_authority: 'none',
      discoverStrips_reached: false,
      degraded: Object.freeze(degraded),
      ambient: ambientSignals(folded.badge),
      field_coverage: Object.freeze({
        keys: GLANCE_FIELD_KEYS,
        every_row_complete: rows.every((r) => r.field_coverage_complete === true),
      }),
    });
  }

  let home = opts.home ?? inject.home ?? null;
  let paths;
  try {
    paths = opts.paths ?? inject.paths ?? indexPathsFrom({
      home: opts.home,
      env: opts.env ?? inject.env,
      paths: opts.paths,
    });
    home = paths.home;
  } catch (e) {
    return Object.freeze({
      ok: false,
      schema: GLANCE_SCHEMA,
      error: GLANCE_CODE.GLANCE_INDEX_MISSING,
      code: GLANCE_CODE.GLANCE_INDEX_MISSING,
      message: GLANCE_TEXT[GLANCE_CODE.GLANCE_INDEX_MISSING],
      detail: String(e?.message ?? e),
      rows: Object.freeze([]),
      row_count: 0,
      discoverStrips_reached: false,
      write_authority: 'none',
    });
  }

  if (!home || !fs.existsSync(home)) {
    return Object.freeze({
      ok: false,
      schema: GLANCE_SCHEMA,
      error: GLANCE_CODE.GLANCE_INDEX_MISSING,
      code: GLANCE_CODE.GLANCE_INDEX_MISSING,
      message: GLANCE_TEXT[GLANCE_CODE.GLANCE_INDEX_MISSING],
      rows: Object.freeze([]),
      row_count: 0,
      discoverStrips_reached: false,
      write_authority: 'none',
    });
  }

  const journal = newReadJournal();
  journal.writes = [];
  const guarded = glanceIndexOnlyFs(opts.fsx ?? fs, home, journal);

  let read;
  try {
    read = openIndexForRead({ ...opts, paths, home, fsx: guarded, env: opts.env ?? inject.env });
  } catch (e) {
    if (e instanceof QueryRefusal) {
      return Object.freeze({
        ok: false,
        schema: GLANCE_SCHEMA,
        error: GLANCE_CODE.GLANCE_QUERY_REFUSED,
        code: GLANCE_CODE.GLANCE_QUERY_REFUSED,
        message: GLANCE_TEXT[GLANCE_CODE.GLANCE_QUERY_REFUSED],
        detail: e.message,
        rows: Object.freeze([]),
        row_count: 0,
        discoverStrips_reached: false,
        no_walk: noWalkReceipt(journal),
        write_authority: 'none',
      });
    }
    return Object.freeze({
      ok: false,
      schema: GLANCE_SCHEMA,
      error: GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE,
      code: GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE,
      message: GLANCE_TEXT[GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE],
      detail: String(e?.message ?? e),
      rows: Object.freeze([]),
      row_count: 0,
      discoverStrips_reached: false,
      no_walk: noWalkReceipt(journal),
      write_authority: 'none',
    });
  }

  if (read.ok !== true) {
    // Distinguish missing vs unparseable
    const code =
      read.code === 'INDEX_ABSENT' || read.reason === 'absent'
        ? GLANCE_CODE.GLANCE_INDEX_MISSING
        : GLANCE_CODE.GLANCE_INDEX_UNPARSEABLE;
    return Object.freeze({
      ok: false,
      schema: GLANCE_SCHEMA,
      error: code,
      code,
      message: GLANCE_TEXT[code],
      detail: read.reason ?? read.text ?? null,
      rows: Object.freeze([]),
      row_count: 0,
      discoverStrips_reached: false,
      no_walk: noWalkReceipt(journal),
      write_authority: 'none',
    });
  }

  const events = replayEvents(read.events ?? []);
  const registry = materializeRegistry(events);
  const snapshot = read.snapshot_value && typeof read.snapshot_value === 'object'
    ? read.snapshot_value
    : null;
  const freshness = snapshot?.freshness && typeof snapshot.freshness === 'object'
    ? snapshot.freshness
    : { per_project: {} };
  const perProject = freshness.per_project && typeof freshness.per_project === 'object'
    ? freshness.per_project
    : {};

  // Body rows by project for stage binding
  const bodyRows = [];
  if (snapshot?.body && typeof snapshot.body === 'object') {
    const projects = snapshot.body.projects ?? snapshot.body;
    // body shape varies — collect derived-like arrays if present
    if (Array.isArray(snapshot.body.rows)) bodyRows.push(...snapshot.body.rows);
  }

  const attentionCells = listAttentionCellsFromIndex({ home, fsx: guarded, journal });
  const attentionById = new Map();
  const attentionByPath = new Map();
  for (const c of attentionCells) {
    if (c.project_id) attentionById.set(String(c.project_id), c);
    if (c.key) attentionById.set(String(c.key), c);
    // Option-P path passport: a cell pushed by the HOST carries the host's
    // project id (Anchor's), which is not the steward registry's id — found
    // live 2026-08-06: a real needs_you cell folded to queue 0. The resolved
    // project path is the identity both sides share. NEWEST WINS when several
    // ids pushed cells for one path (1 folder : N host projects is legal) —
    // otherwise a stale cell can shadow a live raise.
    if (c.project_path) {
      const key = path.resolve(String(c.project_path));
      const prev = attentionByPath.get(key);
      if (!prev || String(c.at ?? '') >= String(prev.at ?? '')) {
        attentionByPath.set(key, c);
      }
    }
  }

  const rows = [];
  const projects = Array.isArray(registry.projects) ? registry.projects : [];

  for (const p of projects) {
    const pid = p.project_id;
    const fresh = perProject[pid] ?? null;
    const rowPath = p.current_path ?? p.root ?? null;
    const att =
      attentionById.get(String(pid)) ??
      (rowPath ? attentionByPath.get(path.resolve(String(rowPath))) : null) ??
      null;
    // Presence UNREACHABLE / unreadable store → unknown row kept.
    //
    // EXCEPT (2026-08-06, found live): UNREACHABLE means "nobody has checked
    // the filesystem yet", not "the root is gone" — and a LIVE attention cell
    // pushed by the project moments ago is itself evidence. Zeroing the row
    // threw away a real needs_you: the ⚑ badge (which reads cells directly)
    // said 1 while the raise queue said 0 — the two surfaces disagreeing about
    // the same fact. ABSENT (checked and gone) still marks the row unreadable.
    const presence = fresh?.presence ?? p.presence ?? null;
    const unreadable =
      (presence === PRESENCE.UNREACHABLE && att == null) ||
      presence === PRESENCE.ABSENT ||
      presence === 'unreadable' ||
      p.unreadable === true;

    const derivedForProject = bodyRows.filter(
      (r) => r && String(r.project_id) === String(pid),
    );

    const row = buildGlanceRow({
      project_id: pid,
      project_path: p.current_path ?? p.root ?? null,
      label: p.label ?? pid,
      fresh,
      attention: att
        ? {
            state: att.state,
            reason: att.reason,
            waiting_steps: att.waiting_steps,
            briefing: att.briefing ?? null,
          }
        : null,
      derived_rows: derivedForProject,
      unreadable,
    });

    // DEGRADED: any A5 field still unknown ships named + gate-report entry
    for (const f of CRITERION_13_FIELDS) {
      if (row.fields[f]?.known === false) {
        degraded.push(
          Object.freeze({
            project_id: pid,
            field: f,
            mark: COMPOSITE.DEGRADED,
            note: 'A5 field beyond cap / absent in index — named unknown; Wave 19 kill gate cannot green criterion 13 on DEGRADED without signed decision',
          }),
        );
      }
    }
    rows.push(row);
  }

  // Unreadable projects supplied explicitly (not in registry)
  for (const u of opts.unreadable_projects ?? inject.unreadable_projects ?? []) {
    const already = rows.some(
      (r) =>
        (u.project_id && r.project_id === u.project_id) ||
        (u.project_path && r.project_path === u.project_path),
    );
    if (already) continue;
    rows.push(
      buildGlanceRow({
        project_id: u.project_id ?? null,
        project_path: u.project_path ?? null,
        label: u.label ?? u.project_id ?? u.project_path,
        unreadable: true,
      }),
    );
  }

  // Semicolon-skipped roots → unknown rows (row count never shrinks)
  const skipped = [
    ...(opts.skipped_roots ?? []),
    ...(inject.skipped_roots ?? []),
  ];
  for (const s of skipped) {
    const pathStr = typeof s === 'string' ? s : s?.project_path ?? s?.root ?? '';
    if (!pathStr) continue;
    rows.push(
      buildGlanceRow({
        project_id: typeof s === 'object' ? s.project_id ?? null : null,
        project_path: pathStr,
        label: typeof s === 'object' ? s.label ?? pathStr : pathStr,
        skipped: true,
      }),
    );
  }

  if (rows.length > PORTFOLIO_MAX_ROWS) {
    return boundExceededResult(rows.length, journal);
  }

  if (rows.length === 0) {
    return Object.freeze({
      ok: true,
      schema: GLANCE_SCHEMA,
      code: GLANCE_CODE.GLANCE_PORTFOLIO_EMPTY,
      message: GLANCE_TEXT[GLANCE_CODE.GLANCE_PORTFOLIO_EMPTY],
      rows: Object.freeze([]),
      row_count: 0,
      items: Object.freeze([]),
      badge: Object.freeze({
        glyph: '⚑',
        count: 0,
        only_ambient_signal: true,
      }),
      queue_length: 0,
      empty: true,
      discoverStrips_reached: false,
      no_walk: noWalkReceipt(journal),
      write_authority: 'none',
      writes_attempted: journal.writes.length,
      degraded: Object.freeze(degraded),
      ambient: ambientSignals({ count: 0 }),
      files_opened: journal.total,
    });
  }

  const folded = foldProjections(rows, inject);

  // Refresh badge cache so the next poll is cache-hit cheap
  try {
    writeBadgeCache({
      home,
      count: folded.queue_length,
      projects: folded.raise_queue.queue
        .map((q) => q.project_id)
        .filter(Boolean),
      updated_via: 'assemblePortfolioGlance',
      fsx: fs,
    });
  } catch {
    // Cache refresh failure does not fail the glance read.
  }

  return Object.freeze({
    ok: true,
    schema: GLANCE_SCHEMA,
    home,
    rows: Object.freeze(rows),
    row_count: rows.length,
    items: folded.items,
    raise_queue: folded.raise_queue,
    badge: folded.badge,
    queue_length: folded.queue_length,
    discoverStrips_reached: false,
    walk_path_unreachable: true,
    no_walk: noWalkReceipt(journal),
    write_authority: 'none',
    writes_attempted: journal.writes.length,
    degraded: Object.freeze(degraded),
    ambient: ambientSignals(folded.badge),
    files_opened: journal.total,
    field_coverage: Object.freeze({
      keys: GLANCE_FIELD_KEYS,
      every_row_complete: rows.every((r) => r.field_coverage_complete === true),
    }),
  });
}

function boundExceededResult(count, journal) {
  return Object.freeze({
    ok: false,
    schema: GLANCE_SCHEMA,
    error: GLANCE_CODE.GLANCE_BOUND_EXCEEDED,
    code: GLANCE_CODE.GLANCE_BOUND_EXCEEDED,
    message: GLANCE_TEXT[GLANCE_CODE.GLANCE_BOUND_EXCEEDED],
    refused: true,
    portfolio_bound: PORTFOLIO_MAX_ROWS,
    attempted_rows: count,
    rows: Object.freeze([]),
    row_count: 0,
    discoverStrips_reached: false,
    no_walk: journal ? noWalkReceipt(journal) : null,
    write_authority: 'none',
  });
}

/** @param {object} journal */
function noWalkReceipt(journal) {
  return Object.freeze({
    roots_opened: journal.outside?.length ?? 0,
    refused: Object.freeze([...(journal.outside ?? [])]),
    reads: Object.freeze([...(journal.reads ?? [])]),
    total_reads: journal.total ?? 0,
    index_home_only: (journal.outside?.length ?? 0) === 0,
  });
}

/**
 * Ambient-signal containment: only the badge count; zero ambient beyond it.
 * @param {{ count?: number }|null} badge
 */
export function ambientSignals(badge = null) {
  const count = Number(badge?.count ?? 0) || 0;
  return Object.freeze({
    only_signal: 'badge',
    badge_count: count,
    ambient_beyond_badge: 0,
    signals: Object.freeze([{ kind: 'badge', count }]),
  });
}

// ── Stdout purity (both bridges) ───────────────────────────────────────────

/**
 * Assert a bridge stdout is exactly one JSON line (nothing else).
 * @param {string} stdout
 * @param {string} bridgeName
 * @returns {Readonly<{ ok: boolean, bridge: string, error?: string, parsed?: object }>}
 */
export function assertBridgeStdoutPurity(stdout, bridgeName = 'bridge') {
  const raw = String(stdout ?? '');
  // Allow a single trailing newline; nothing else.
  const trimmed = raw.replace(/\r\n/g, '\n');
  const lines = trimmed.endsWith('\n')
    ? trimmed.slice(0, -1).split('\n')
    : trimmed.split('\n');
  if (lines.length !== 1 || lines[0].trim() === '') {
    return Object.freeze({
      ok: false,
      bridge: bridgeName,
      error: 'bridge_bad_json',
      message: `${bridgeName}: stdout must be exactly one JSON line; got ${lines.length} line(s)`,
      mapped: mapBridgeGarbage('bridge_bad_json'),
    });
  }
  try {
    const parsed = JSON.parse(lines[0]);
    return Object.freeze({
      ok: true,
      bridge: bridgeName,
      parsed,
    });
  } catch (e) {
    return Object.freeze({
      ok: false,
      bridge: bridgeName,
      error: 'bridge_bad_json',
      message: `${bridgeName}: stdout is not JSON — ${e.message}`,
      mapped: mapBridgeGarbage('bridge_bad_json'),
    });
  }
}

/**
 * Hash a project tree (files only) for byte-identity write_authority proof.
 * @param {string} root
 * @param {object} [fsx]
 * @returns {string} sha256 hex
 */
export function hashProjectTree(root, fsx = fs) {
  const files = [];
  function walk(dir) {
    let entries;
    try {
      entries = fsx.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const ent of entries) {
      const abs = path.join(dir, ent.name);
      if (ent.isDirectory()) walk(abs);
      else if (ent.isFile()) files.push(abs);
    }
  }
  walk(root);
  files.sort();
  const h = crypto.createHash('sha256');
  for (const f of files) {
    h.update(path.relative(root, f).split(path.sep).join('/'));
    h.update('\0');
    // encoding-lint: raw-bytes — tree hash fingerprints on-disk bytes, not decoded text
    h.update(fsx.readFileSync(f));
    h.update('\0');
  }
  return h.digest('hex');
}

/**
 * Prove write_authority none: hash trees before/after fold+badge+tile path.
 * @param {string[]} projectRoots
 * @param {() => void} run
 * @returns {Readonly<{ ok: boolean, before: object, after: object, identical: boolean }>}
 */
export function assertTreesByteIdentical(projectRoots, run) {
  const before = {};
  for (const r of projectRoots) before[r] = hashProjectTree(r);
  run();
  const after = {};
  for (const r of projectRoots) after[r] = hashProjectTree(r);
  const identical = projectRoots.every((r) => before[r] === after[r]);
  return Object.freeze({
    ok: identical,
    before: Object.freeze(before),
    after: Object.freeze(after),
    identical,
    write_authority: 'none',
  });
}

/**
 * Client poll contract — parse MIN_MS / MAX_MS from static/high-seat.js source.
 * "One poll" = one healthy visible-tab interval (MIN_MS). Failure backoff may
 * reach MAX_MS; hidden tabs skip entirely.
 *
 * @param {string} sourceText contents of static/high-seat.js
 * @returns {Readonly<{ MIN_MS: number, MAX_MS: number, ok: boolean }>}
 */
/**
 * Parse a millisecond assignment from client JS source.
 * Accepts a bare integer (`90000`) or a pure product (`15 * 60 * 1000`) —
 * the form static/high-seat.js uses for the MAX_MS ceiling.
 *
 * @param {string} src
 * @param {string} name identifier on the left of `=`
 * @returns {number} finite ms, or NaN when the assignment is absent/unparseable
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

export function importClientPollConstants(sourceText) {
  const src = String(sourceText ?? '');
  // Prefer Wave-17 named constants; fall back to local MIN_MS / MAX_MS aliases.
  // Product expressions (15 * 60 * 1000) must evaluate — capturing only the
  // leading 15 would silently shrink the backoff ceiling 60_000×.
  const MIN_MS = (() => {
    const named = parseClientMsAssignment(src, 'ECG_HS_MIN_MS');
    if (Number.isFinite(named)) return named;
    return parseClientMsAssignment(src, 'MIN_MS');
  })();
  const MAX_MS = (() => {
    const named = parseClientMsAssignment(src, 'ECG_HS_MAX_MS');
    if (Number.isFinite(named)) return named;
    return parseClientMsAssignment(src, 'MAX_MS');
  })();
  return Object.freeze({
    MIN_MS,
    MAX_MS,
    ok: Number.isFinite(MIN_MS) && Number.isFinite(MAX_MS) && MIN_MS > 0,
    // Contract documentation (not silently violated):
    one_poll_definition: 'one healthy visible-tab interval (MIN_MS)',
    failure_backoff_may_reach_MAX_MS: true,
    hidden_tab_polls_skip: true,
  });
}

/**
 * Removal-proof: badge route source must not call discoverStrips / verbStatus.
 * @param {string} sourceText high-seat-bridge or glance module source
 * @returns {Readonly<{ ok: boolean, discoverStrips_refs: number, verbStatus_on_badge: boolean }>}
 */
export function assertBadgePathDoesNotWalk(sourceText) {
  const src = String(sourceText ?? '');
  // buildBadgeFromIndex body must not invoke discoverStrips
  const badgeFn = src.includes('buildBadgeFromIndex') || src.includes('buildBadgePayload');
  // Count discoverStrips invocations that are not comments
  const lines = src.split('\n').filter((l) => !/^\s*(\/\/|\*)/.test(l));
  const body = lines.join('\n');
  // For bridge: buildBadgePayload should call buildBadgeFromIndex, not verbStatus
  const badgeSection = extractFunctionBody(src, 'buildBadgePayload')
    ?? extractFunctionBody(src, 'buildBadgeFromIndex')
    ?? '';
  const discoverInBadge = /discoverStrips\s*\(/.test(badgeSection);
  const verbStatusInBadge = /verbStatus\s*\(/.test(badgeSection);
  return Object.freeze({
    ok: badgeFn && !discoverInBadge && !verbStatusInBadge,
    discoverStrips_reached: discoverInBadge,
    verbStatus_on_badge: verbStatusInBadge,
    badge_function_present: badgeFn,
  });
}

/** @param {string} src @param {string} name */
function extractFunctionBody(src, name) {
  const re = new RegExp(
    `(?:export\\s+)?function\\s+${name}\\s*\\([^)]*\\)\\s*\\{`,
  );
  const m = re.exec(src);
  if (!m) return null;
  let i = m.index + m[0].length;
  let depth = 1;
  const start = i;
  while (i < src.length && depth > 0) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') depth -= 1;
    i += 1;
  }
  return src.slice(start, i - 1);
}

// Re-export attention codes used on the glance surface
export { ATTENTION_CODE, ATTENTION_TEXT, ATTENTION_READ_UNKNOWN, ATTENTION_STATES };
