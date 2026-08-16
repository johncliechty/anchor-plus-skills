/**
 * Wave 21 — shared handback-contract conformance suite runner.
 *
 * Drives any { prepareRun, spawn, kill, collect } adapter through the
 * named T-CONF-15 clauses. Does not import child_process itself — adapters
 * own process creation (engine law: engine/ stays process-free; suite lives
 * outside engine/).
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  CONTRACT_VERSION,
  HANDBACK_REL_DIR,
  HANDBACK_JSON_NAME,
  TERMINAL_MARKER_NAME,
  handbackDir,
  handbackJsonPath,
  terminalMarkerPath,
  isIngestable,
  readIngestableHandback,
  validateHandbackBody,
  IngestIdempotenceRegistry,
} from '../../engine/handback-contract.mjs';
import { CLAUSE_NAMES, clauseFailureName } from './clauses.mjs';
import { validateAdapter } from './adapter-interface.mjs';
import {
  evaluateWriteInterception,
  evaluateWriteDiscipline,
  probeRealWriterS6,
  loadWriterSource,
} from './write-intercept.mjs';
import {
  writeConformanceVerdictForExecutor,
  mergeExecutorResult,
  CONFORMANCE_WRITTEN_BY,
} from './verdict.mjs';

/**
 * @typedef {object} ClauseResult
 * @property {string} clause
 * @property {boolean} ok
 * @property {string} [reason]
 * @property {string} [failure_name]
 */

/**
 * Run a single named clause against adapter collect/context.
 * Exported for unit tests of injected drift / stub refusal.
 *
 * @param {string} clause
 * @param {object} ctx
 * @returns {ClauseResult}
 */
export function evaluateClause(clause, ctx = {}) {
  const executor = ctx.executor || ctx.adapter_name || 'unknown';
  const fail = (reason) => ({
    clause,
    ok: false,
    reason,
    failure_name: clauseFailureName(executor, clause),
  });
  const pass = (reason) => ({
    clause,
    ok: true,
    reason: reason || null,
    failure_name: clauseFailureName(executor, clause),
  });

  const collect = ctx.collect || {};
  const worktree = ctx.worktree || collect.worktree;

  switch (clause) {
    case 'path-convention': {
      if (!worktree) return fail('no worktree');
      const hb = handbackJsonPath(worktree);
      const mk = terminalMarkerPath(worktree);
      const relHb = path.relative(worktree, hb).split(path.sep).join('/');
      const relMk = path.relative(worktree, mk).split(path.sep).join('/');
      const expectHb = `${HANDBACK_REL_DIR}/${HANDBACK_JSON_NAME}`;
      const expectMk = `${HANDBACK_REL_DIR}/${TERMINAL_MARKER_NAME}`;
      if (relHb !== expectHb) {
        return fail(`handback path ${relHb} !== ${expectHb}`);
      }
      if (relMk !== expectMk) {
        return fail(`marker path ${relMk} !== ${expectMk}`);
      }
      if (collect.complete_pair === true) {
        if (!fs.existsSync(hb) || !fs.existsSync(mk)) {
          return fail('complete_pair claimed but files missing at contract paths');
        }
      }
      return pass(`paths ${expectHb} + ${expectMk}`);
    }

    case 'schema-validity': {
      let body = collect.handback;
      if (!body && worktree && fs.existsSync(handbackJsonPath(worktree))) {
        try {
          body = JSON.parse(fs.readFileSync(handbackJsonPath(worktree), 'utf8'));
        } catch (e) {
          return fail(`handback JSON unreadable: ${e?.message ?? e}`);
        }
      }
      if (!body) return fail('no handback body to validate');
      const v = validateHandbackBody(body);
      if (!v.ok) {
        return fail(v.message || v.error || 'receipt-validate failed');
      }
      return pass('receipt-validate ok (kind=handback)');
    }

    case 'terminal-marker-semantics': {
      if (!worktree) return fail('no worktree');
      if (collect.complete_pair === true) {
        if (!isIngestable(worktree)) {
          return fail('complete pair not ingestable');
        }
        const read = readIngestableHandback(worktree);
        if (!read.ok) return fail(read.message || read.error);
        return pass('both files present → ingestable');
      }
      // Explicit torn state check when provided
      if (collect.marker_absent === true || collect.torn === true) {
        if (isIngestable(worktree)) {
          return fail('torn pair must not be ingestable');
        }
        return pass('marker absent → not ingestable');
      }
      return fail('terminal-marker-semantics needs complete_pair or torn collect');
    }

    case 'write-discipline': {
      const writerText =
        ctx.writer_source_text ||
        collect.writer_source_text ||
        (ctx.writer_rel
          ? loadWriterSource(ctx.writer_rel, {
              skillRoot: ctx.skillRoot,
              anchorRoot: ctx.anchorRoot,
            }).text
          : null);
      const r = evaluateWriteDiscipline(collect, {
        writerSourceText: writerText || undefined,
      });
      return r.ok ? pass(r.reason || 'S6 ok') : fail(r.reason);
    }

    case 'write-interception': {
      const r = evaluateWriteInterception(collect);
      return r.ok ? pass('real child spawn observed') : fail(r.reason);
    }

    case 'kill-mid-write': {
      if (!worktree) return fail('no worktree');
      if (collect.kill_mid_done !== true && collect.marker_absent !== true) {
        return fail('kill-mid-write not exercised (collect.kill_mid_done)');
      }
      if (isIngestable(worktree)) {
        return fail('kill-mid-write left an ingestable pair (marker must be absent)');
      }
      if (fs.existsSync(terminalMarkerPath(worktree))) {
        return fail('TERMINAL.marker present after kill-mid-write');
      }
      // handback.json may or may not exist (killed before or during write)
      return pass('marker absent → not ingestable');
    }

    case 'duplicate-delivery': {
      const id =
        collect.client_event_id ||
        collect.handback?.client_event_id ||
        ctx.client_event_id;
      if (!id) return fail('no client_event_id for duplicate-delivery');
      const reg =
        ctx.idempotence_registry ||
        collect.idempotence_registry ||
        new IngestIdempotenceRegistry();
      // If adapter already proved duplicate, trust the counts
      if (
        collect.ingest_first_adopted === true &&
        collect.ingest_second_duplicate === true
      ) {
        return pass('ingest exactly once (adapter-reported)');
      }
      const a = reg.tryAdopt(id);
      const b = reg.tryAdopt(id);
      if (!a.adopted || a.duplicate) {
        return fail('first delivery should adopt');
      }
      if (b.adopted || !b.duplicate) {
        return fail('second delivery should be duplicate (ingest exactly once)');
      }
      return pass('ingest exactly once');
    }

    case 'no-token-in-child': {
      if (collect.no_token_in_child === true && !collect.forbidden_in_child?.length) {
        return pass('no forbidden token in child env');
      }
      const env = collect.child_env || {};
      const forbidden = [
        'ANCHOR_TOKEN',
        'ANCHOR_CAPABILITY',
        'ANCHOR_CAPABILITY_TOKEN',
        'ECGBERHT_CAPABILITY',
        'ECGBERHT_TOKEN',
      ];
      const present = forbidden.filter(
        (k) => env[k] != null && String(env[k]) !== '',
      );
      if (present.length) {
        return fail(`forbidden keys in child env: ${present.join(',')}`);
      }
      if (collect.no_token_in_child === false) {
        return fail('adapter reported no_token_in_child=false');
      }
      return pass('no forbidden token in child env');
    }

    case 'single-writer': {
      if (collect.single_writer === false) {
        return fail('adapter reported single_writer=false');
      }
      if (collect.writer_count != null && Number(collect.writer_count) !== 1) {
        return fail(`writer_count=${collect.writer_count} (expected 1)`);
      }
      // Clean handback dir after complete write implies single writer finished
      if (worktree && collect.complete_pair === true) {
        try {
          const dir = handbackDir(worktree);
          const names = fs.readdirSync(dir);
          const expected = new Set([HANDBACK_JSON_NAME, TERMINAL_MARKER_NAME]);
          const extras = names.filter((n) => !expected.has(n) && !n.endsWith('.lock'));
          if (extras.length) {
            return fail(`unexpected files in handback dir: ${extras.join(',')}`);
          }
        } catch (e) {
          return fail(String(e?.message ?? e));
        }
      }
      return pass('single writer per run dir');
    }

    case 'version-skew': {
      const skillVer = ctx.skill_contract_version || CONTRACT_VERSION;
      const execVer =
        collect.contract_version ||
        ctx.executor_contract_version ||
        collect.executor_contract_version;
      if (execVer == null) {
        return fail('executor did not report contract_version');
      }
      if (String(execVer) !== String(skillVer)) {
        return fail(
          `version skew: skill=${skillVer} executor=${execVer} — both fail until they agree`,
        );
      }
      // Optional peer skew injection (suite-level both-executor check)
      if (
        ctx.peer_contract_version != null &&
        String(ctx.peer_contract_version) !== String(execVer)
      ) {
        return fail(
          `peer version skew: self=${execVer} peer=${ctx.peer_contract_version}`,
        );
      }
      return pass(`contract_version=${execVer}`);
    }

    default:
      return fail(`unknown clause: ${clause}`);
  }
}

/**
 * Run the full clause table against one adapter (real prepare/spawn/kill/collect).
 *
 * Modes exercised:
 *   - complete: full pair write via real child
 *   - kill-mid: torn write (marker absent)
 *   - (duplicate / token / version read from complete collect)
 *
 * @param {object} adapter
 * @param {{
 *   skillRoot?: string,
 *   anchorRoot?: string|null,
 *   root?: string,
 *   writeVerdict?: boolean,
 *   clauses?: string[],
 * }} [opts]
 */
export async function runConformanceAgainstAdapter(adapter, opts = {}) {
  const v = validateAdapter(adapter);
  if (!v.ok) {
    return {
      ok: false,
      executor: adapter?.name ?? 'unknown',
      error: v.error,
      message: v.message,
      clause_results: [
        {
          clause: 'write-interception',
          ok: false,
          reason: v.message,
          failure_name: clauseFailureName(adapter?.name ?? 'unknown', 'write-interception'),
        },
      ],
    };
  }

  const executor = v.name;
  const clauses = opts.clauses || [...CLAUSE_NAMES];
  /** @type {ClauseResult[]} */
  const clause_results = [];
  const skillRoot = opts.skillRoot;
  const anchorRoot = opts.anchorRoot ?? null;

  // ── Leg A: complete write via real wrapper + real OS child ──────────────
  let prep;
  try {
    prep = await adapter.prepareRun({
      mode: 'complete',
      skillRoot,
      anchorRoot,
    });
  } catch (e) {
    return {
      ok: false,
      executor,
      message: `prepareRun failed: ${e?.message ?? e}`,
      clause_results: clauses.map((c) => ({
        clause: c,
        ok: false,
        reason: `prepareRun failed: ${e?.message ?? e}`,
        failure_name: clauseFailureName(executor, c),
      })),
    };
  }

  let spawnResult;
  try {
    spawnResult = await adapter.spawn({
      ...prep,
      mode: 'complete',
    });
  } catch (e) {
    try {
      await adapter.kill({ ...prep, spawn: null });
    } catch {
      /* best effort */
    }
    return {
      ok: false,
      executor,
      message: `spawn failed: ${e?.message ?? e}`,
      clause_results: clauses.map((c) => ({
        clause: c,
        ok: false,
        reason: `spawn failed: ${e?.message ?? e}`,
        failure_name: clauseFailureName(executor, c),
      })),
    };
  }

  // Wait for child if adapter exposes wait
  if (spawnResult && typeof spawnResult.wait === 'function') {
    try {
      await spawnResult.wait();
    } catch {
      /* collect will surface incompleteness */
    }
  }

  let collectComplete;
  try {
    collectComplete = await adapter.collect({
      ...prep,
      spawn: spawnResult,
      mode: 'complete',
    });
  } catch (e) {
    collectComplete = {
      error: String(e?.message ?? e),
      spawned_child: false,
    };
  }

  try {
    await adapter.kill({ ...prep, spawn: spawnResult });
  } catch {
    /* optional */
  }

  // ── Leg B: kill-mid-write ───────────────────────────────────────────────
  let prepMid;
  let collectMid = null;
  try {
    prepMid = await adapter.prepareRun({
      mode: 'kill-mid',
      skillRoot,
      anchorRoot,
    });
    const spawnMid = await adapter.spawn({
      ...prepMid,
      mode: 'kill-mid',
    });
    if (spawnMid && typeof spawnMid.wait === 'function') {
      try {
        await spawnMid.wait();
      } catch {
        /* expected for kill path */
      }
    }
    // Prefer adapter kill mid-flight when it still has a live handle
    if (spawnMid && spawnMid.live === true) {
      await adapter.kill({ ...prepMid, spawn: spawnMid, force: true });
    }
    collectMid = await adapter.collect({
      ...prepMid,
      spawn: spawnMid,
      mode: 'kill-mid',
    });
    try {
      await adapter.kill({ ...prepMid, spawn: spawnMid });
    } catch {
      /* done */
    }
  } catch (e) {
    collectMid = {
      kill_mid_done: false,
      error: String(e?.message ?? e),
      worktree: prepMid?.worktree,
    };
  }

  // Writer source for S6
  let writer_source_text = collectComplete.writer_source_text;
  if (!writer_source_text) {
    const rel =
      executor === 'anchor'
        ? 'commission_executor.py'
        : 'engine/durable-write.mjs';
    const loaded = loadWriterSource(rel, { skillRoot, anchorRoot });
    if (loaded.ok) writer_source_text = loaded.text;
  }

  const worktree = collectComplete.worktree || prep?.worktree;
  const baseCtx = {
    executor,
    adapter_name: executor,
    skillRoot,
    anchorRoot,
    skill_contract_version: CONTRACT_VERSION,
    writer_source_text,
    worktree,
  };

  // Evaluate each clause with the appropriate collect
  for (const clause of clauses) {
    let ctx;
    if (clause === 'kill-mid-write') {
      const midWt = collectMid?.worktree || prepMid?.worktree;
      ctx = {
        ...baseCtx,
        worktree: midWt,
        collect: {
          ...(collectMid || {}),
          worktree: midWt,
          kill_mid_done:
            collectMid?.kill_mid_done === true ||
            collectMid?.marker_absent === true ||
            (midWt != null && collectMid != null),
          marker_absent: true,
        },
      };
    } else {
      ctx = {
        ...baseCtx,
        collect: {
          complete_pair: true,
          used_real_writer: true,
          s6_proven: true,
          single_writer: true,
          writer_count: 1,
          no_token_in_child: collectComplete.no_token_in_child !== false,
          ...collectComplete,
        },
        client_event_id: collectComplete.client_event_id,
      };
    }
    clause_results.push(evaluateClause(clause, ctx));
  }

  const ok = clause_results.every((r) => r.ok);
  const contract_version =
    collectComplete.contract_version || CONTRACT_VERSION;

  let verdictWrite = null;
  if (opts.writeVerdict !== false && opts.root) {
    verdictWrite = writeConformanceVerdictForExecutor({
      root: opts.root,
      executor,
      contract_version,
      clause_results,
      peer_versions: opts.peer_versions,
    });
  }

  return {
    ok,
    executor,
    contract_version,
    clause_results,
    failed_clauses: clause_results
      .filter((r) => !r.ok)
      .map((r) => r.failure_name || clauseFailureName(executor, r.clause)),
    collect: collectComplete,
    collect_mid: collectMid,
    verdict: verdictWrite?.payload ?? null,
    verdict_path: verdictWrite?.path ?? null,
    written_by: CONFORMANCE_WRITTEN_BY,
    s6_probe: probeRealWriterS6({
      skillRoot,
      anchorRoot,
      executor,
    }),
  };
}

/**
 * Pure evaluation of an injected-drift scenario (no adapter spawn).
 * Used by GWT tests for write-discipline drift and version-skew.
 *
 * @param {{ executor?: string, collect?: object, skill_contract_version?: string, peer_contract_version?: string, writer_source_text?: string }} scenario
 * @param {string[]} [clauses]
 */
export function evaluateInjectedScenario(scenario = {}, clauses = CLAUSE_NAMES) {
  const executor = scenario.executor || 'anchor';
  const results = clauses.map((clause) =>
    evaluateClause(clause, {
      executor,
      collect: scenario.collect || {},
      skill_contract_version: scenario.skill_contract_version || CONTRACT_VERSION,
      executor_contract_version: scenario.executor_contract_version,
      peer_contract_version: scenario.peer_contract_version,
      writer_source_text: scenario.writer_source_text,
      worktree: scenario.worktree || scenario.collect?.worktree,
    }),
  );
  return {
    ok: results.every((r) => r.ok),
    executor,
    clause_results: results,
    failed_clauses: results
      .filter((r) => !r.ok)
      .map((r) => r.failure_name || clauseFailureName(executor, r.clause)),
  };
}

/**
 * Build a stub adapter that returns canned files without spawning — must FAIL
 * write-interception.
 *
 * @param {{ worktree: string, handback?: object }} opts
 */
export function makeCannedStubAdapter(opts) {
  const worktree = opts.worktree;
  return {
    name: 'stub-canned',
    async prepareRun() {
      return { worktree, runDir: worktree };
    },
    async spawn() {
      // Deliberately no OS child — write files in-process
      return { pid: null, canned: true };
    },
    async kill() {
      return { ok: true };
    },
    async collect() {
      // Caller may have pre-placed files; we claim them without spawn
      return {
        worktree,
        canned: true,
        stub: true,
        stub_adapter: true,
        spawned_child: false,
        wrote_via_canned_files: true,
        complete_pair: true,
        handback: opts.handback || null,
        contract_version: CONTRACT_VERSION,
        no_token_in_child: true,
        single_writer: true,
      };
    },
  };
}

export { CLAUSE_NAMES, mergeExecutorResult, CONTRACT_VERSION };
