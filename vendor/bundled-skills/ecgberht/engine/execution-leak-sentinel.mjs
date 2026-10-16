/**
 * Gate 5 / Wave 2 - THE execution-leak sentinel: the ONE mechanism behind every
 * "no execution" assertion (amendment B2), introduced here and reused by every later wave.
 *
 * WHAT A LEAK IS. Kickoff ends at "ready for first slice" and starts nothing: no commission,
 * no draft, no model run, no specialist, no build, no external action (North Star criterion
 * 11). "Asserted three times with no mechanism" was the Stage 2 finding; this module is the
 * mechanism. It watches the four execution seams AND the disk, because a leak is either a
 * call that reached an executor or a byte that reached a file it had no business reaching.
 *
 * THE FOUR SEAMS, and where each one is actually spied. The engine law is that nothing under
 * engine/ may touch child_process: every execution path is an INJECTED hook, so the sentinel
 * spies on the engine's own injection points rather than on the operating system.
 *
 *   commission  - the confirmed-commission executor seam. engine/commission-proposal.mjs
 *                 resolves executeCommission() through two injected registries (the host
 *                 executor and the in-session executor); arming replaces both with a spy
 *                 that records the dossier and REFUSES, so a leaking path is seen and stopped.
 *   specialist  - a process launch. A specialist skill is spawned through the in-session
 *                 process hooks (engine/exec-insession.mjs `launch`); arming installs a spy
 *                 launch hook that records and throws, so no pid can ever come back.
 *   model_run   - a seat call. The seat transport is injected per call (`seatCall`) and has
 *                 no global registry, so the sentinel supplies a seatCall-shaped spy
 *                 (`spies.model_run`) for a caller to inject wherever a real transport would go.
 *   draft       - a model-authored compile pass (face-compile `passFn`, NL-polish). Also
 *                 injected per call; `spies.draft` is the passFn-shaped spy.
 *
 * THE TREE DIFF. arm() captures every file under the project root (path, size, sha256);
 * report() captures again and lists every created / modified / deleted path, and names the
 * ones OUTSIDE the allow-list (default: `.ecgberht/kickoff/` only). A Face, a Strip, an
 * envelope ledger, a roadmap, an anatomy.json written during kickoff is a leak, by name.
 *
 * Bounded: a root with more than SENTINEL_MAX_FILES files refuses to arm rather than walk
 * unbounded. Stdlib only. Source is ASCII on purpose (the repo's mojibake sweep).
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import {
  getCommissionExecutor,
  getInSessionExecutor,
  setCommissionExecutor,
  setInSessionExecutor,
} from './commission-proposal.mjs';
import {
  getInSessionProcessHooks,
  setInSessionProcessHooks,
} from './exec-insession.mjs';

/** The four execution seams, in the order the plan names them. */
export const EXECUTION_SEAMS = Object.freeze(['commission', 'draft', 'model_run', 'specialist']);

/** Paths kickoff may write. Everything else written while armed is a leak. */
export const SENTINEL_DEFAULT_ALLOW = Object.freeze(['.ecgberht/kickoff/']);

/** The named bound on the tree walk; past it the sentinel refuses to arm. */
export const SENTINEL_MAX_FILES = 20000;

export const SENTINEL_CODE = Object.freeze({
  CLEAN: 'EXECUTION_LEAK_NONE',
  LEAK: 'EXECUTION_LEAK_DETECTED',
  TREE_BOUND: 'EXECUTION_SENTINEL_TREE_BOUND_EXCEEDED',
});

export const SENTINEL_TEXT = Object.freeze({
  [SENTINEL_CODE.CLEAN]:
    'No execution leaked: zero execution calls and no file outside the allowed paths.',
  [SENTINEL_CODE.LEAK]:
    'Execution leaked during kickoff (<detail>) - this path must start nothing.',
  [SENTINEL_CODE.TREE_BOUND]:
    'The project tree exceeds the sentinel file bound (<detail>) - refused rather than walked unbounded.',
});

/** @param {string} code @param {string} [detail] @returns {string} */
export function sentinelText(code, detail = '') {
  const text = SENTINEL_TEXT[code] ?? SENTINEL_TEXT[SENTINEL_CODE.LEAK];
  return text.replace(/<detail>/g, String(detail));
}

// -- the tree --------------------------------------------------------------------

/**
 * Every regular file under `root`: repo-relative POSIX path -> {size, sha256}. Symlinks and
 * junctions are not followed. Returns `ok: false` past the file bound instead of walking on.
 *
 * @param {string} root
 * @param {{max_files?: number}} [opts]
 * @returns {{ok: boolean, files: Map<string, {size: number, sha256: string}>, count: number, bound: number}}
 */
export function captureTree(root, opts = {}) {
  const bound = Number.isInteger(opts.max_files) ? opts.max_files : SENTINEL_MAX_FILES;
  const base = path.resolve(root);
  const files = new Map();
  const stack = [''];
  while (stack.length) {
    const rel = stack.pop();
    const abs = rel ? path.join(base, rel) : base;
    let entries;
    try {
      entries = fs.readdirSync(abs, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const childRel = rel ? `${rel}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        stack.push(childRel);
        continue;
      }
      if (!entry.isFile()) continue;
      if (files.size >= bound) return { ok: false, files, count: files.size, bound };
      let bytes;
      try {
        // encoding-lint: raw-bytes - the diff is over the BYTES on disk, never decoded text
        bytes = fs.readFileSync(path.join(base, ...childRel.split('/')));
      } catch {
        continue;
      }
      files.set(childRel, {
        size: bytes.length,
        sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
      });
    }
  }
  return { ok: true, files, count: files.size, bound };
}

/**
 * @param {Map<string, object>} before @param {Map<string, object>} after
 * @returns {Array<{path: string, change: 'created'|'modified'|'deleted'}>} sorted by path
 */
export function diffTrees(before, after) {
  const changes = [];
  const paths = new Set([...before.keys(), ...after.keys()]);
  for (const rel of [...paths].sort()) {
    const was = before.get(rel);
    const is = after.get(rel);
    if (!was) changes.push({ path: rel, change: 'created' });
    else if (!is) changes.push({ path: rel, change: 'deleted' });
    else if (was.sha256 !== is.sha256 || was.size !== is.size) {
      changes.push({ path: rel, change: 'modified' });
    }
  }
  return changes;
}

/** @param {string} rel POSIX relative path @param {ReadonlyArray<string>} [allow] */
export function isAllowedPath(rel, allow = SENTINEL_DEFAULT_ALLOW) {
  const norm = String(rel).split('\\').join('/');
  return allow.some((prefix) => norm === prefix || norm.startsWith(prefix));
}

// -- arming ----------------------------------------------------------------------

/**
 * Arm the sentinel over a project root.
 *
 * Installs the seam spies into the engine's injection registries, captures the tree, and
 * returns a handle whose `report()` says whether anything executed or escaped, whose
 * `assertNoExecutionLeak()` throws a named error when it did, and whose `disarm()` restores
 * whatever executors and hooks were installed before (only if they are still ours).
 *
 * @param {string} root
 * @param {{allow?: ReadonlyArray<string>, max_files?: number}} [opts]
 * @returns {object} the armed sentinel, or `{ok: false, code: TREE_BOUND, ...}`
 */
export function armExecutionLeakSentinel(root, opts = {}) {
  const projectRoot = path.resolve(root);
  const allow = Object.freeze([...(opts.allow ?? SENTINEL_DEFAULT_ALLOW)]);
  const before = captureTree(projectRoot, opts);
  if (!before.ok) {
    return {
      ok: false,
      armed: false,
      code: SENTINEL_CODE.TREE_BOUND,
      status_code: SENTINEL_CODE.TREE_BOUND,
      user_text: sentinelText(SENTINEL_CODE.TREE_BOUND, `${before.count}+ files > ${before.bound}`),
      root: projectRoot,
      bound: before.bound,
    };
  }

  const calls = [];
  let armed = true;
  const record = (seam, detail) => {
    const entry = Object.freeze({ seq: calls.length + 1, seam, detail: Object.freeze({ ...detail }) });
    calls.push(entry);
    return entry;
  };
  const refusal = (entry) => ({
    ok: false,
    code: SENTINEL_CODE.LEAK,
    status_code: SENTINEL_CODE.LEAK,
    user_text: sentinelText(SENTINEL_CODE.LEAK, `${entry.seam} call #${entry.seq}`),
    seam: entry.seam,
    leak: true,
    executed: false,
    launched: false,
    pid: null,
  });

  const spies = Object.freeze({
    commission: (dossier) => refusal(record('commission', {
      skill: dossier?.skill ?? null,
      commission_id: dossier?.commission_id ?? null,
    })),
    specialist: (args) => {
      const entry = record('specialist', {
        run_id: args?.run_id ?? null,
        cmdline: Array.isArray(args?.cmdline) ? args.cmdline.join(' ') : null,
      });
      const err = new Error(sentinelText(SENTINEL_CODE.LEAK, `specialist launch #${entry.seq}`));
      err.code = SENTINEL_CODE.LEAK;
      err.seam = 'specialist';
      throw err;
    },
    model_run: (prompt, ctx) => refusal(record('model_run', {
      role: ctx?.role ?? null,
      prompt_chars: typeof prompt === 'string' ? prompt.length : null,
    })),
    draft: (input, ctx) => refusal(record('draft', { kind: ctx?.kind ?? 'compile_pass' })),
  });

  const previous = {
    commission: getCommissionExecutor(),
    insession: getInSessionExecutor(),
    hooks: getInSessionProcessHooks(),
  };
  setCommissionExecutor(spies.commission);
  setInSessionExecutor(spies.commission, { available: true });
  setInSessionProcessHooks({ launch: spies.specialist });

  const report = () => {
    const after = captureTree(projectRoot, opts);
    const changes = after.ok ? diffTrees(before.files, after.files) : [];
    const outside = changes.filter((change) => !isAllowedPath(change.path, allow));
    const executionCalls = calls.slice();
    const bySeam = Object.fromEntries(
      EXECUTION_SEAMS.map((seam) => [seam, executionCalls.filter((c) => c.seam === seam).length]),
    );
    const clean = after.ok && executionCalls.length === 0 && outside.length === 0;
    const code = !after.ok
      ? SENTINEL_CODE.TREE_BOUND
      : clean ? SENTINEL_CODE.CLEAN : SENTINEL_CODE.LEAK;
    const detail = [
      ...executionCalls.map((c) => `${c.seam}#${c.seq}`),
      ...outside.map((c) => `${c.change}:${c.path}`),
    ].join(', ');
    return Object.freeze({
      ok: clean,
      code,
      status_code: code,
      user_text: sentinelText(code, detail || `${after.count} files`),
      armed,
      root: projectRoot,
      allowed: allow,
      seams: EXECUTION_SEAMS,
      execution_calls: Object.freeze(executionCalls),
      calls_by_seam: Object.freeze(bySeam),
      files_changed: Object.freeze(changes),
      outside_allowed: Object.freeze(outside),
      files_before: before.count,
      files_after: after.count,
    });
  };

  const disarm = () => {
    if (!armed) return false;
    armed = false;
    if (getCommissionExecutor() === spies.commission) setCommissionExecutor(previous.commission);
    if (getInSessionExecutor().fn === spies.commission) {
      setInSessionExecutor(previous.insession.fn, { available: previous.insession.available });
    }
    if (getInSessionProcessHooks()?.launch === spies.specialist) {
      setInSessionProcessHooks(previous.hooks);
    }
    return true;
  };

  return {
    ok: true,
    armed: true,
    root: projectRoot,
    allowed: allow,
    seams: EXECUTION_SEAMS,
    spies,
    report,
    assertNoExecutionLeak: () => {
      const outcome = report();
      if (!outcome.ok) {
        const err = new Error(outcome.user_text);
        err.code = outcome.code;
        err.report = outcome;
        throw err;
      }
      return outcome;
    },
    disarm,
    isArmed: () => armed,
  };
}

/**
 * Run `fn` under an armed sentinel and always disarm afterwards. `fn` may be sync or async
 * and receives the sentinel (so it can inject `spies.model_run` / `spies.draft`).
 *
 * @param {string} root @param {(sentinel: object) => *} fn @param {object} [opts]
 * @returns {Promise<{ok: boolean, result: *, report: object}>}
 */
export async function withExecutionLeakSentinel(root, fn, opts = {}) {
  const sentinel = armExecutionLeakSentinel(root, opts);
  if (!sentinel.ok) return { ok: false, result: undefined, report: sentinel };
  try {
    const result = await fn(sentinel);
    const report = sentinel.report();
    return { ok: report.ok, result, report };
  } finally {
    sentinel.disarm();
  }
}
