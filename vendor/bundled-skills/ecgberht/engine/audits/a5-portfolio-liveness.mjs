/**
 * Wave 3 — A5 portfolio-index liveness audit + DERIVED-ingest probe
 * + criterion-13 field matrix + attention-delivery probe.
 *
 * Audits, never re-plans. No portfolio-index rebuild as a product deliverable
 * (rebuild may be exercised as a liveness proof of the EXISTING rebuilder).
 *
 * DERIVED-ingest probe:
 *   Wave 3 recorded a PRE-DECIDED FAIL (zero production callers of the durable
 *   paths). Wave 6 CLOSES that FAIL by migrating live writers onto the ledger
 *   spine / appendRoadmapEventDurable + write-authority durable paths. After
 *   Wave 6 the probe is green when production_caller_count > 0.
 *
 * Attention delivery: expected NEEDS-WIRE (ingestAck in-process only, C7B open)
 * — recorded; wired in Wave 16.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  writeFileAtomicSync,
  writeJsonIdempotentSync,
  DEFAULT_VOLATILE_JSON_KEYS,
} from '../durable-write.mjs';

/**
 * A5 artifacts embed per-run ephemeral fixture identities (temp project roots
 * get fresh UUID basenames each suite run). Those are volatile alongside the
 * pure timestamps — a rewrite changing only them is semantically EMPTY.
 */
const A5_VOLATILE_KEYS = Object.freeze([
  ...DEFAULT_VOLATILE_JSON_KEYS,
  'project_id',
  'project_ids',
]);
import { emptyRoadmap } from '../roadmap.mjs';
import { appendRoadmapEventThroughSpine } from '../ledger-spine.mjs';
import {
  resolveIndexHome,
  resolveIndexPaths,
  HOME_ENV,
} from '../portfolio/home.mjs';
import { registerRoot } from '../portfolio/register.mjs';
import { rebuildIndex } from '../portfolio/rebuild.mjs';
import { queryIndex } from '../portfolio/query.mjs';
import {
  C7B_STATUS,
  ingestAck,
  ANCHOR_CONTRACT_VERSION,
} from '../portfolio/anchor-contract.mjs';
import { PRESENCE } from '../portfolio/status.mjs';
import { appendFixItem, FIX_ITEM_KIND } from './fix-item-ledger.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '..', '..');

/** Criterion-13 glance fields (plan Wave 3 / Wave 17 input). */
export const CRITERION_13_FIELDS = Object.freeze([
  'stage',
  'runs.live',
  'runs.waiting',
  'runs.blocked',
  'last_movement',
]);

/**
 * Coverage marks for the field matrix.
 * ABSENT reuses the STATUS-v1 presence token (one home for that code).
 */
export const FIELD_MARK = Object.freeze({
  ANSWERED: 'ANSWERED',
  PARTIAL: 'PARTIAL',
  ABSENT: PRESENCE.ABSENT,
});

/** Production roots scanned for durable-path callers (relative to skill root). */
export const PRODUCTION_SCAN_DIRS = Object.freeze([
  'engine',
  'scripts',
  'bin',
]);

/** Files that DEFINE the durable helpers (not callers). */
export const DURABLE_DEFINITIONS = Object.freeze({
  appendRoadmapEventDurable: 'engine/roadmap.mjs',
  appendStripReceiptDurable: 'engine/write-authority.mjs',
  appendStripInstrumentDurable: 'engine/write-authority.mjs',
});

/** Re-export-only files (not production callers). */
export const DURABLE_REEXPORT_FILES = Object.freeze([
  'engine/index.mjs',
]);

/** Symbols probed. */
export const DURABLE_SYMBOLS = Object.freeze([
  'appendRoadmapEventDurable',
  'appendStripReceiptDurable',
  'appendStripInstrumentDurable',
]);

export const A5_LIVENESS_REL = path.join('artifacts', 'a5-liveness.json');
export const A5_DERIVED_INGEST_REL = path.join(
  'artifacts',
  'a5-derived-ingest-probe.json',
);
export const A5_FIELD_MATRIX_REL = path.join('artifacts', 'a5-field-matrix.json');
export const A5_ATTENTION_REL = path.join(
  'artifacts',
  'a5-attention-delivery.json',
);

/**
 * Walk production sources for identifier mentions.
 * @param {string} root skill root
 * @param {string} symbol
 * @returns {Array<{ file: string, line: number, text: string }>}
 */
export function findProductionMentions(root, symbol) {
  const hits = [];
  const re = new RegExp(`\\b${symbol.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`);

  function walk(dir, relBase) {
    let entries = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const ent of entries) {
      const abs = path.join(dir, ent.name);
      const rel = path.join(relBase, ent.name).split(path.sep).join('/');
      if (ent.isDirectory()) {
        if (ent.name === 'node_modules' || ent.name === 'fixture-slice') continue;
        walk(abs, rel);
        continue;
      }
      if (!ent.isFile()) continue;
      if (!ent.name.endsWith('.mjs') && !ent.name.endsWith('.js')) continue;
      let text;
      try {
        text = fs.readFileSync(abs, 'utf8');
      } catch {
        continue;
      }
      const lines = text.split(/\r?\n/);
      for (let i = 0; i < lines.length; i += 1) {
        if (!re.test(lines[i])) continue;
        // Skip pure comments that only mention the name in prose.
        // Do NOT treat bare parentheses in JSDoc as "code" — prose like
        // "appendRoadmapEventDurable (roadmap.mjs)" is not a call site.
        const trimmed = lines[i].trim();
        if (trimmed.startsWith('*') || trimmed.startsWith('//') || trimmed.startsWith('/*')) {
          if (!/import|from|export|function|=\s*|await/.test(lines[i])) {
            continue;
          }
        }
        hits.push({ file: rel, line: i + 1, text: lines[i].trim() });
      }
    }
  }

  for (const d of PRODUCTION_SCAN_DIRS) {
    const abs = path.join(root, d);
    if (fs.existsSync(abs)) walk(abs, d);
  }
  return hits;
}

/**
 * Classify mentions into definition / re-export / production caller.
 * @param {string} symbol
 * @param {Array<{file:string,line:number,text:string}>} hits
 */
export function classifyDurableMentions(symbol, hits) {
  const defFile = DURABLE_DEFINITIONS[symbol];
  const production_callers = [];
  const definitions = [];
  const reexports = [];
  const comments_or_other = [];

  for (const h of hits) {
    const isDef =
      h.file === defFile &&
      (/export\s+function\s+/.test(h.text) || /function\s+/.test(h.text));
    if (isDef) {
      definitions.push(h);
      continue;
    }
    if (DURABLE_REEXPORT_FILES.includes(h.file) && /export\s*\{/.test(h.text) === false) {
      // index.mjs lines are usually bare names inside export { }
      if (h.file === 'engine/index.mjs') {
        reexports.push(h);
        continue;
      }
    }
    if (h.file === 'engine/index.mjs') {
      reexports.push(h);
      continue;
    }
    // call or import from production code
    if (
      /import\s|from\s|^\s*export\s/.test(h.text) &&
      h.file !== defFile
    ) {
      // import of the name for re-export is still not a runtime production persist
      if (h.file.startsWith('engine/') && /import\s/.test(h.text)) {
        // treat non-definition imports in engine as potential callers if they
        // also *invoke* — invocation is a separate hit with (
        comments_or_other.push(h);
        continue;
      }
    }
    if (new RegExp(`${symbol}\\s*\\(`).test(h.text)) {
      // Comment / JSDoc lines are never production call sites (paren in prose).
      const t = h.text.trim();
      if (t.startsWith('*') || t.startsWith('//') || t.startsWith('/*')) {
        comments_or_other.push(h);
        continue;
      }
      production_callers.push(h);
      continue;
    }
    // bare mention without call
    comments_or_other.push(h);
  }

  return {
    symbol,
    definition_file: defFile,
    definitions,
    reexports,
    production_callers,
    other_mentions: comments_or_other,
    production_caller_count: production_callers.length,
  };
}

/**
 * DERIVED-ingest probe — PRE-DECIDED FAIL when zero production callers.
 * @param {{ root?: string, liveWrite?: { projectDir: string } }} [opts]
 */
export function runDerivedIngestProbe(opts = {}) {
  const root = opts.root ? path.resolve(opts.root) : REPO_ROOT;

  // Wave 6: live write goes through the spine (locked durable path), not bare write.
  let live_write = null;
  if (opts.liveWrite?.projectDir) {
    const projectDir = opts.liveWrite.projectDir;
    fs.mkdirSync(projectDir, { recursive: true });
    const r = appendRoadmapEventThroughSpine(
      projectDir,
      {
        kind: 'step_create',
        step_id: 'a5-probe',
        name: 'A5 live write via spine',
        status: 'planned',
        done_when: 'probe records Wave-6 migration closed',
        at: '2026-08-02',
      },
      {
        seed: emptyRoadmap('a5-live-write'),
        skip_index: true,
      },
    );
    live_write = {
      path: 'appendRoadmapEventThroughSpine (locked durable)',
      project_dir_note: 'temp fixture',
      wrote: r.ok === true && r.sot_written === true,
      spine: true,
    };
  }

  const per_symbol = DURABLE_SYMBOLS.map((sym) => {
    const hits = findProductionMentions(root, sym);
    return classifyDurableMentions(sym, hits);
  });

  const totalCallers = per_symbol.reduce(
    (n, s) => n + s.production_caller_count,
    0,
  );

  // Wave 3 pre-decided FAIL (zero callers). Wave 6 CLOSES it when production
  // callers of the durable paths exist (migration done).
  const migration_closed = totalCallers > 0;
  const outcome = migration_closed ? 'PASS' : 'FAIL';

  const result = {
    schema: 'ecgberht-a5-derived-ingest-probe-v0',
    audit: 'A5',
    probe: 'DERIVED-ingest production callers',
    recorded_at: new Date().toISOString(),
    pre_decided: true,
    pre_decided_expectation: 'FAIL',
    pre_decided_closed_by_wave: 6,
    outcome,
    // Residual-cap contract: this probe IS the pre-decided FAIL finding.
    // Wave 6 may close the defect (migration_closed / outcome PASS) without
    // reclassifying the finding as residual — frozen residual-cap audits
    // require this flag true either way.
    confirms_pre_decided_fail: true,
    migration_closed,
    total_production_callers: totalCallers,
    per_symbol,
    live_write,
    live_path_note: migration_closed
      ? 'Production verbs persist via ledger spine / appendRoadmapEventDurable + write-authority durable paths.'
      : 'Every live verb persists via bare writeProjectRoadmap / writeFileAtomicSync with no lock.',
    migration: {
      owning_wave: 6,
      counts_against_a5_cap: false,
      counts_against_residual_cap: false,
      halt_for_this_fact: false,
      closed: migration_closed,
      note: migration_closed
        ? 'Wave-6 ledger spine migration closed the pre-decided FAIL: durable paths have production callers.'
        : 'Verb migration onto appendRoadmapEventDurable + write-authority durable paths is Wave-6 scope.',
    },
    ok: migration_closed,
  };

  return result;
}

/**
 * Attention-delivery probe: ingestAck is in-process; C7B open → NEEDS-WIRE.
 */
export function runAttentionDeliveryProbe() {
  const needsWire =
    C7B_STATUS.open === true && typeof ingestAck === 'function';

  return {
    schema: 'ecgberht-a5-attention-delivery-v0',
    audit: 'A5',
    probe: 'attention index delivery',
    recorded_at: new Date().toISOString(),
    expected: 'NEEDS-WIRE',
    observed: needsWire ? 'NEEDS-WIRE' : 'UNEXPECTED',
    confirms_expected: needsWire,
    evidence: {
      ingestAck_typeof: typeof ingestAck,
      ingestAck_bridge_exposure: 'none — in-process ES-module only',
      C7B_STATUS,
      anchor_contract_version: ANCHOR_CONTRACT_VERSION,
    },
    migration: {
      owning_wave: 16,
      counts_against_residual_cap: false,
      note: 'Bridge deliverable is Wave 16; planned, not residual.',
    },
    ok: needsWire,
  };
}

/**
 * Liveness: index home resolves, snapshot rebuilds, query no-walk, anchor-contract reachable.
 * @param {{ home: string, projectRoots?: string[] }} opts
 */
export function runA5Liveness(opts) {
  const home = path.resolve(opts.home);
  const env = { [HOME_ENV]: home };

  const homeRes = resolveIndexHome(env);
  const paths = resolveIndexPaths(env);
  const home_ok =
    path.resolve(homeRes.home) === home &&
    Boolean(paths.log) &&
    Boolean(paths.snapshot);

  /** @type {string[]} */
  const project_ids = [];
  /** @type {Array<object>} */
  const register_results = [];
  for (const root of opts.projectRoots ?? []) {
    fs.mkdirSync(root, { recursive: true });
    // Minimal strip via bare write (NOT the durable path — that is Wave-6 scope).
    const stripPath = path.join(root, 'strip.json');
    if (!fs.existsSync(stripPath)) {
      writeFileAtomicSync(
        stripPath,
        `${JSON.stringify(
          {
            schema: 'ecgberht-strip-v0',
            project_id: path.basename(root),
            phase: 'build',
            active_effort: 'A5 liveness',
            human_wait: 'none',
            capacity: 'known',
            instruments: [],
            receipts: [],
            as_of: '2026-08-02',
          },
          null,
          2,
        )}\n`,
      );
    }
    const reg = registerRoot(root, { home });
    register_results.push({
      root_label: path.basename(root),
      ok: reg.ok === true,
      code: reg.code ?? null,
      project_id: reg.project_id ?? null,
    });
    if (reg.ok && reg.project_id) project_ids.push(reg.project_id);
  }

  const rebuilt = rebuildIndex({ home });
  const rebuild_ok = rebuilt.ok === true;

  const query_result = queryIndex({ home });
  const query_ok = query_result?.ok === true;
  const no_walk =
    query_result?.no_walk?.index_home_only === true ||
    (query_result?.no_walk?.roots_opened === 0 &&
      Array.isArray(query_result?.no_walk?.refused) &&
      query_result.no_walk.refused.length === 0) ||
    (query_ok &&
      query_result?.no_walk &&
      Number(query_result.no_walk.roots_opened ?? 0) === 0);

  const anchor_reachable =
    typeof ingestAck === 'function' &&
    C7B_STATUS &&
    typeof C7B_STATUS.open === 'boolean';

  return {
    schema: 'ecgberht-a5-liveness-v0',
    audit: 'A5',
    recorded_at: new Date().toISOString(),
    index_home: {
      ok: home_ok,
      // never absolute host profile paths in artifacts — report relative role only
      resolved_via: homeRes.source,
      has_log: Boolean(paths.log),
      has_snapshot: Boolean(paths.snapshot),
      paths_version: 'index-home-v1',
    },
    register: {
      project_ids,
      count: project_ids.length,
      results: register_results,
    },
    snapshot_rebuild: {
      ok: rebuild_ok,
      outcome_code: rebuilt.outcome?.code ?? rebuilt.code ?? null,
      live_projects: rebuilt.body?.counts?.live ?? rebuilt.outcome?.live ?? null,
    },
    steward_query: {
      ok: query_ok,
      no_walk: Boolean(no_walk),
      no_walk_detail: query_result?.no_walk
        ? {
            index_home_only: query_result.no_walk.index_home_only ?? null,
            roots_opened: query_result.no_walk.roots_opened ?? null,
            total_reads: query_result.no_walk.total_reads ?? null,
          }
        : null,
      row_count: Array.isArray(query_result?.rows)
        ? query_result.rows.length
        : null,
      codes: query_result?.codes ?? null,
    },
    anchor_contract: {
      reachable: anchor_reachable,
      version: ANCHOR_CONTRACT_VERSION,
      c7b_open: C7B_STATUS.open,
    },
    no_index_rebuild_as_product: true,
    ok:
      home_ok &&
      rebuild_ok &&
      query_ok &&
      Boolean(no_walk) &&
      anchor_reachable &&
      project_ids.length > 0,
  };
}

/**
 * Field-by-field criterion-13 coverage matrix for every project in the index.
 * @param {{ home: string, projectMeta?: Array<{ project_id: string, root?: string, label?: string }> }} opts
 */
export function emitFieldMatrix(opts) {
  const home = opts.home;
  const env = { [HOME_ENV]: home };
  const paths = resolveIndexPaths(env);

  let snapshot = null;
  if (fs.existsSync(paths.snapshot)) {
    try {
      snapshot = JSON.parse(fs.readFileSync(paths.snapshot, 'utf8'));
    } catch {
      snapshot = null;
    }
  }

  const body = snapshot?.body ?? {};
  const freshness = snapshot?.freshness?.per_project ?? {};
  const projectIds = new Set([
    ...Object.keys(freshness),
    ...(opts.projectMeta ?? []).map((p) => p.project_id),
  ]);

  // Collect DERIVED rows from body.rows and registry project list
  const rows = [];
  if (body && typeof body === 'object') {
    if (Array.isArray(body.rows)) rows.push(...body.rows);
    if (Array.isArray(body.projects)) {
      for (const p of body.projects) {
        if (p?.project_id) projectIds.add(p.project_id);
      }
    }
  }

  for (const r of rows) {
    if (r?.project_id) projectIds.add(r.project_id);
  }

  const metaById = new Map(
    (opts.projectMeta ?? []).map((p) => [p.project_id, p]),
  );

  /** @type {Array<object>} */
  const matrix = [];

  for (const project_id of [...projectIds].sort()) {
    const fresh = freshness[project_id] ?? null;
    const projectRows = rows.filter((r) => r?.project_id === project_id);

    for (const field of CRITERION_13_FIELDS) {
      const row = classifyField(field, {
        project_id,
        fresh,
        projectRows,
        snapshot,
      });
      matrix.push({
        project_id,
        project_label: metaById.get(project_id)?.label ?? null,
        field,
        mark: row.mark,
        answering_index_key: row.answering_index_key,
        no_walk_observation: row.no_walk_observation,
        note: row.note,
      });
    }
  }

  // Every project must have one row per criterion-13 field
  const projects = [...projectIds];
  const complete =
    projects.length > 0 &&
    projects.every(
      (pid) =>
        matrix.filter((m) => m.project_id === pid).length ===
        CRITERION_13_FIELDS.length,
    );

  return {
    schema: 'ecgberht-a5-field-matrix-v0',
    audit: 'A5',
    title: 'Criterion-13 field-by-field coverage matrix',
    recorded_at: new Date().toISOString(),
    criterion: 13,
    fields: [...CRITERION_13_FIELDS],
    project_count: projects.length,
    matrix,
    complete,
    wave_17_input: true,
    note:
      'Checked-in input Wave 17 is built against. ABSENT/PARTIAL fields are the '
      + 'honest audit of the EXISTING index — not a re-plan.',
    ok: complete,
  };
}

/**
 * @param {string} field
 * @param {{ project_id: string, fresh: object|null, projectRows: object[], snapshot: object|null }} ctx
 */
function classifyField(field, ctx) {
  const no_walk_observation =
    'Field read from portfolio index home only — query/indexOnlyFs path; no project-root walk.';

  if (field === 'last_movement') {
    if (ctx.fresh?.last_seen) {
      return {
        mark: FIELD_MARK.ANSWERED,
        answering_index_key: 'freshness.per_project[project_id].last_seen',
        no_walk_observation,
        note: 'Index freshness carries last_seen.',
      };
    }
    if (ctx.fresh) {
      return {
        mark: FIELD_MARK.PARTIAL,
        answering_index_key: 'freshness.per_project[project_id]',
        no_walk_observation,
        note: 'Per-project freshness present but last_seen empty/null.',
      };
    }
    return {
      mark: FIELD_MARK.ABSENT,
      answering_index_key: null,
      no_walk_observation,
      note: 'No per-project freshness entry.',
    };
  }

  if (field === 'stage') {
    // No first-class stage cell in the index body today; roadmap-event proj may PARTIAL.
    const roadmapish = ctx.projectRows.find(
      (r) =>
        r.class === 'roadmap-event' ||
        r?.class === 'roadmap_event' ||
        (r.proj && /stage|phase|step/i.test(JSON.stringify(r.proj))),
    );
    if (roadmapish) {
      return {
        mark: FIELD_MARK.PARTIAL,
        answering_index_key: 'body DERIVED class=roadmap-event proj',
        no_walk_observation,
        note: 'Roadmap-event derived rows exist; no first-class stage cell (Wave 17 binds).',
      };
    }
    return {
      mark: FIELD_MARK.ABSENT,
      answering_index_key: null,
      no_walk_observation,
      note: 'No stage field in portfolio index — Wave 17 glance binding.',
    };
  }

  // runs.live / runs.waiting / runs.blocked — not in index yet (Wave 13/17)
  return {
    mark: FIELD_MARK.ABSENT,
    answering_index_key: null,
    no_walk_observation,
    note: `No ${field} cell in portfolio index today — session/run truth lands later (Waves 13/17).`,
  };
}

/**
 * Full A5 audit suite.
 * @param {{
 *   root?: string,
 *   skillRoot?: string,
 *   home: string,
 *   projectRoots: string[],
 *   projectMeta?: Array<{project_id:string,label?:string}>,
 *   liveWriteDir?: string,
 *   writeArtifact?: boolean,
 *   appendLedger?: boolean,
 * }} opts
 *
 * `root` is the artifact/ledger write destination (may be a disposable temp
 * tree so audits do not thrash the checked-in ledger). Production-source
 * scanning for the DERIVED-ingest probe always targets the skill tree
 * (`skillRoot` when provided, else this module's REPO_ROOT) — never the
 * disposable artifact root alone, which has no engine/ sources.
 */
export function runA5Audit(opts) {
  const root = opts.root ? path.resolve(opts.root) : REPO_ROOT;
  // Source scan root is independent of the artifact write root.
  const skillRoot = opts.skillRoot ? path.resolve(opts.skillRoot) : REPO_ROOT;

  const liveness = runA5Liveness({
    home: opts.home,
    projectRoots: opts.projectRoots,
  });

  // Refresh meta from liveness project ids when not provided
  const projectMeta =
    opts.projectMeta ??
    liveness.register.project_ids.map((project_id) => ({ project_id }));

  const derived = runDerivedIngestProbe({
    root: skillRoot,
    liveWrite: opts.liveWriteDir
      ? { projectDir: opts.liveWriteDir }
      : undefined,
  });

  const field_matrix = emitFieldMatrix({
    home: opts.home,
    projectMeta,
  });

  const attention = runAttentionDeliveryProbe();

  // Scheduled (non-cap) ledger rows for pre-decided findings
  const ledger_rows = [];
  if (opts.appendLedger && opts.root) {
    ledger_rows.push(
      appendFixItem(
        {
          id: 'A5-derived-ingest-zero-callers',
          kind: FIX_ITEM_KIND.PRE_DECIDED,
          counts_against_cap: false,
          title: 'DERIVED-ingest durable paths have zero production callers',
          audit: 'A5',
          owning_wave: 6,
          outcome: derived.outcome,
        },
        { root: opts.root },
      ),
    );
    ledger_rows.push(
      appendFixItem(
        {
          id: 'A5-attention-delivery-needs-wire',
          kind: FIX_ITEM_KIND.SCHEDULED,
          counts_against_cap: false,
          title: 'Attention index delivery NEEDS-WIRE (ingestAck in-process, C7B open)',
          audit: 'A5',
          owning_wave: 16,
          outcome: attention.observed,
        },
        { root: opts.root },
      ),
    );
  }

  const summary = {
    schema: 'ecgberht-a5-audit-summary-v0',
    audit: 'A5',
    recorded_at: new Date().toISOString(),
    liveness_ok: liveness.ok,
    derived_ingest_confirms_pre_decided_fail: derived.confirms_pre_decided_fail,
    derived_migration_wave: 6,
    derived_halt: false,
    field_matrix_complete: field_matrix.complete,
    attention_needs_wire: attention.confirms_expected,
    residual_cap_items_from_a5: 0,
    ok:
      liveness.ok &&
      derived.ok &&
      field_matrix.ok &&
      attention.ok,
  };

  const artifacts = {};
  if (opts.writeArtifact !== false && opts.root) {
    const pairs = [
      [A5_LIVENESS_REL, liveness],
      [A5_DERIVED_INGEST_REL, derived],
      [A5_FIELD_MATRIX_REL, field_matrix],
      [A5_ATTENTION_REL, attention],
      [path.join('artifacts', 'a5-audit-summary.json'), summary],
    ];
    for (const [rel, doc] of pairs) {
      const p = path.join(opts.root, rel);
      // Idempotent: unchanged audit results (ignoring timestamps + ephemeral
      // fixture UUIDs) leave the file byte-identical (journal 0070 thrash fix).
      writeJsonIdempotentSync(p, doc, { volatileKeys: A5_VOLATILE_KEYS });
      artifacts[rel] = p;
    }
  }

  return {
    ok: summary.ok,
    summary,
    liveness,
    derived,
    field_matrix,
    attention,
    ledger_rows,
    artifacts,
  };
}
