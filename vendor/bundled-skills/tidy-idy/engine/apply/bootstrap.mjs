// engine/apply/bootstrap.mjs — Wave 4: Bootstrap, secret-triage FIRST (Amendment B).
//
// Bootstrap is the canonical table's own row: `git init` → starter .gitignore →
// `git add -A` → one baseline commit B. A fixed op-set, never mixed with
// findings, so every OTHER Apply in this tool can assume a repository already
// exists. Amendment A demoted it from a gate to an OPTIONAL upgrade — removals
// on a plain folder already work through the reversible Trash — so nothing here
// is on the critical path of anything. It buys SAVE findings and `git revert`.
//
// AMENDMENT B IS THE WHOLE POINT OF THIS FILE. A blind `git add -A` over a
// stranger's folder is how an `.env` with a live AWS key gets its own commit,
// permanently, in a repository the user may later push. The plain version of
// this feature is therefore not merely imperfect, it is actively dangerous. So:
//
//   TRIAGE RUNS BEFORE ANY `git add`. Not after, not alongside — before, over
//     every in-scope path, content AND filename, through the same universal
//     pre-LLM gate the rest of the engine uses (engine/secret-triage.mjs).
//   EVERY FLAGGED PATH IS WRITTEN INTO THE STARTER .gitignore, which means git
//     itself — not a filter of ours that could have a hole in it — is what keeps
//     the secret out of the index.
//   AND THE RESULT IS THEN VERIFIED against the commit that was actually
//     written. If any flagged path is reachable from B, Bootstrap UNDOES ITSELF
//     and refuses. "We intended to exclude it" is not a claim worth making about
//     a credential.
//
// CONSENT SCOPE. Bootstrap is the single operation in the entire tool whose tile
// discloses an ignore-rule write; `buildBootstrapTile()` renders exactly what
// will be written, including each secret line, so approving it is approving
// that text. No other Apply may touch .gitignore except through its own
// explicitly-approved add-to-.gitignore finding.
//
// UNDO. Bootstrap journals the PRIOR CONTENT — or the prior ABSENCE — of every
// file it creates or touches, .gitignore above all. Undo (offered only while
// HEAD==B) removes .git and puts every journaled file back byte-for-byte: a
// pre-existing .gitignore is restored, never deleted; a file Bootstrap created
// from nothing is removed. Once HEAD has moved past B the undo is REFUSED
// entirely, because removing .git would then discard work git holds.

import fsp from 'node:fs/promises';
import path from 'node:path';

import { triageAll } from '../secret-triage.mjs';
import { hashFile } from '../snapshot.mjs';
import { reportDirFor } from '../report-dir.mjs';
import { toPosixRel } from '../glob.mjs';

import { makeGitRunner } from './git-plumbing.mjs';
import { acquireLock } from './lock.mjs';
import { openJournal, readJournal } from './journal.mjs';
import { checkPathAgainstExpectation } from './no-clobber.mjs';
import { ensureReportDirIgnored } from './trash.mjs';

export const BOOTSTRAP_KIND = 'bootstrap';

export const BOOTSTRAP_STATUS = Object.freeze({
  BOOTSTRAPPED: 'bootstrapped',
  UNDONE: 'undone',
  PARTIAL: 'partial',
  REFUSED: 'refused',
});

export const BOOTSTRAP_REFUSAL = Object.freeze({
  ALREADY_A_REPO: 'ALREADY_A_REPO',
  NOT_APPROVED: 'BOOTSTRAP_NOT_APPROVED',
  LOCK_HELD: 'LOCK_HELD',
  SECRET_IN_BASELINE: 'SECRET_REACHABLE_FROM_BASELINE',
  NOTHING_TO_COMMIT: 'NOTHING_TO_COMMIT',
  GIT_FAILED: 'GIT_COMMAND_FAILED',
  NO_JOURNAL: 'NO_BOOTSTRAP_JOURNAL',
  HEAD_MOVED: 'HEAD_MOVED_PAST_BASELINE',
  NOT_BOOTSTRAPPED: 'NOT_BOOTSTRAPPED',
});

/**
 * The starter ignore set, deliberately TINY.
 *
 * A generous starter .gitignore (node_modules, dist, *.log, …) looks helpful and
 * is a quiet act of judgement about which of the user's files deserve version
 * control — made at the exact moment git holds nothing, so anything wrongly
 * ignored is simply absent from the baseline with no record anywhere. The two
 * lines below are the ones the TOOL itself makes necessary, plus whatever secret
 * triage flags. Everything else goes into B, where git holds it forever and can
 * be un-tracked later by an explicit, approvable operation.
 */
export const STARTER_HEADER = [
  '# Created by tidy-idy Bootstrap.',
  '# Deliberately minimal: only this tool\'s own state and paths that secret',
  '# triage flagged BEFORE the first `git add`, so no credential can land in the',
  '# baseline commit. Everything else is committed, where git can hold it.',
];

/** Walk the tree, skipping .git and the tool's own state directory. */
async function walk(root, reportDirRel, fs, rel = '') {
  const out = [];
  let entries;
  try {
    entries = await fs.readdir(path.join(root, rel), { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    const child = rel ? `${rel}/${e.name}` : e.name;
    if (e.name === '.git') continue;
    if (reportDirRel && (child === reportDirRel || child.startsWith(`${reportDirRel}/`))) continue;
    if (e.isSymbolicLink()) continue; // Amendment C.ii: links are never followed
    if (e.isDirectory()) out.push(...await walk(root, reportDirRel, fs, child));
    else if (e.isFile()) out.push(child);
  }
  return out;
}

async function readOrNull(fs, abs) {
  try { return await fs.readFile(abs); } catch { return null; }
}

async function hashOrNull(fs, abs) {
  try { return await hashFile(abs, { fs }); } catch { return null; }
}

/**
 * Everything Bootstrap would do, computed by LOOKING ONLY. Safe to call from a
 * read-only scan; this is what the approval tile renders.
 *
 * @param {{rootPath: string, reportDir?: string, paths?: string[]|null, allow?: string[], fs?: object}} opts
 */
export async function planBootstrap({ rootPath, reportDir = null, paths = null, allow = [], fs = fsp } = {}) {
  const root = path.resolve(rootPath);
  const reportDirAbs = reportDir ? path.resolve(reportDir) : reportDirFor(root);
  const reportDirRel = reportDirAbs.startsWith(root + path.sep)
    ? toPosixRel(path.relative(root, reportDirAbs))
    : null;

  const inScope = (paths || await walk(root, reportDirRel, fs)).map(toPosixRel);

  // ---- THE AMENDMENT-B GATE, before anything is staged or written ---------
  const verdicts = await triageAll({ rootPath: root, paths: inScope, fs, allow });
  const secrets = [];
  for (const rel of inScope) {
    const v = verdicts.get(rel);
    if (!v || !v.blockedFromSave) continue;
    secrets.push({
      path: rel,
      triggers: v.triggers,
      triggerSummary: v.maskedTriggerText,
      note: 'auto-added to the starter .gitignore and EXCLUDED from the baseline commit — the file itself is untouched on disk',
    });
  }

  const ignoreLines = [];
  if (reportDirRel) ignoreLines.push(`${reportDirRel}/`);
  for (const s of secrets) ignoreLines.push(s.path);

  const gitignoreAbs = path.join(root, '.gitignore');
  const priorBytes = await readOrNull(fs, gitignoreAbs);
  const priorContent = priorBytes === null ? null : priorBytes.toString('utf8');

  const content = renderGitignore(priorContent, ignoreLines);

  return {
    rootPath: root,
    inScope,
    scanned: inScope.length,
    secrets,
    secretPaths: secrets.map((s) => s.path),
    baselineIncludes: inScope.filter((p) => !secrets.some((s) => s.path === p) && !(reportDirRel && (p === reportDirRel || p.startsWith(`${reportDirRel}/`)))),
    gitignore: {
      path: '.gitignore',
      existed: priorContent !== null,
      priorContent,
      priorHash: priorBytes === null ? null : await hashOrNull(fs, gitignoreAbs),
      linesAdded: ignoreLines,
      content,
      unchanged: priorContent !== null && content === priorContent,
    },
    triageRanFirst: true,
  };
}

/** Append the starter lines to whatever is already there, preserving it exactly. */
function renderGitignore(priorContent, lines) {
  const missing = lines.filter((line) => {
    if (priorContent === null) return true;
    return !priorContent.split(/\r?\n/).some((l) => l.trim() === line);
  });
  if (!missing.length) return priorContent === null ? '' : priorContent;

  const block = [...STARTER_HEADER, ...missing, ''].join('\n');
  if (priorContent === null) return block;
  // The prior bytes are preserved VERBATIM; the block is appended after them.
  const separator = priorContent === '' || priorContent.endsWith('\n') ? '' : '\n';
  return `${priorContent}${separator}\n${block}`;
}

/**
 * The approval tile. Bootstrap is the ONE operation whose tile discloses an
 * ignore-rule write, so the exact text is on it, not a summary of it.
 */
export function buildBootstrapTile(plan) {
  return {
    kind: 'bootstrap',
    action: 'bootstrap',
    approvable: true,
    defaultChecked: false,
    summary: `initialise a git repository here and make ONE baseline commit of ${plan.baselineIncludes.length} file(s)`,
    ops: [
      { kind: 'git-init', summary: '`git init` at the run root' },
      {
        kind: 'starter-gitignore',
        summary: plan.gitignore.existed
          ? 'APPEND to your existing .gitignore (its current content is preserved byte-for-byte and journaled for undo)'
          : 'create a starter .gitignore',
        disclosesIgnoreRuleWrite: true,
        linesAdded: plan.gitignore.linesAdded,
        exactContent: plan.gitignore.content,
      },
      { kind: 'secret-triage-first', summary: `secret triage ran over all ${plan.scanned} in-scope path(s) BEFORE any \`git add\`; ${plan.secrets.length} flagged path(s) are ignored and excluded from the baseline` },
      { kind: 'baseline-commit', summary: 'one baseline commit B — a fixed op-set, never mixed with findings' },
    ],
    secretsExcluded: plan.secrets.map((s) => ({ path: s.path, why: s.triggerSummary })),
    undo: 'while HEAD==B: remove .git and restore every journaled file to its prior state byte-for-byte (a pre-existing .gitignore is restored, never deleted). REFUSED once HEAD has moved past B.',
    consentScope: 'this is the only tile in tidy-idy that declares an ignore-rule write; the exact .gitignore text it will write is shown above',
  };
}

/**
 * Run Bootstrap. One repository, one baseline commit, no secrets in it.
 *
 * @param {{rootPath: string, reportDir?: string, runId: string, approved?: boolean,
 *   paths?: string[]|null, allow?: string[], branch?: string, fs?: object,
 *   env?: object, now?: Function, run?: Function, jobId?: string|null}} opts
 */
export async function applyBootstrap(opts = {}) {
  const {
    runId,
    approved = false,
    paths = null,
    allow = [],
    branch = 'main',
    fs = fsp,
    env = process.env,
    now = () => new Date(),
    jobId = null,
  } = opts;

  const root = path.resolve(opts.rootPath);
  const reportDir = opts.reportDir ? path.resolve(opts.reportDir) : reportDirFor(root);

  if (!approved) {
    return refused(BOOTSTRAP_REFUSAL.NOT_APPROVED,
      'Bootstrap refuses: it creates a repository and a commit, and nothing in this tool happens without an explicit approval of the tile that described it');
  }

  try {
    await fs.stat(path.join(root, '.git'));
    return refused(BOOTSTRAP_REFUSAL.ALREADY_A_REPO,
      `Bootstrap refuses: '${root}' already contains a .git — Bootstrap exists only for folders that have no repository, and running it inside one would create a nested repo whose contents the outer repo sees as an opaque gitlink`);
  } catch { /* no repo: the only state Bootstrap runs in */ }

  const lock = await acquireLock({ reportDir, jobId, purpose: 'bootstrap', fs, now });
  if (!lock.ok) return refused(BOOTSTRAP_REFUSAL.LOCK_HELD, lock.message, { holder: lock.holder });

  const run = opts.run || makeGitRunner({ root, env });
  let journal = null;

  try {
    journal = await openJournal({ reportDir, runId, kind: BOOTSTRAP_KIND, fs, now });
    await journal.append('bootstrap-start', { rootPath: root, branch });

    // ---- STEP 1: TRIAGE. Before init, before the ignore write, before add ---
    const plan = await planBootstrap({ rootPath: root, reportDir, paths, allow, fs });
    await journal.append('secret-triage', {
      scanned: plan.scanned,
      flagged: plan.secrets.map((s) => ({ path: s.path, triggerSummary: s.triggerSummary })),
      beforeAnyGitAdd: true,
      note: 'Amendment B: the gate runs FIRST, so every flagged path is in .gitignore before git is ever asked to stage anything',
    });

    // ---- STEP 2: journal the prior state of everything we will touch -------
    const gitignoreAbs = path.join(root, '.gitignore');
    const touched = [{
      path: '.gitignore',
      existedBefore: plan.gitignore.existed,
      priorHash: plan.gitignore.priorHash,
      priorContentBase64: plan.gitignore.priorContent === null
        ? null
        : Buffer.from(plan.gitignore.priorContent, 'utf8').toString('base64'),
    }];
    await journal.append('prior-state', {
      files: touched,
      gitAbsentBefore: true,
      note: 'undo restores each of these byte-for-byte (or deletes it, when it did not exist before) — this record IS the undo',
    });

    // ---- STEP 3: git init ---------------------------------------------------
    const init = await run(['init'], { allowFailure: true });
    if (init.code !== 0) {
      return refused(BOOTSTRAP_REFUSAL.GIT_FAILED, `Bootstrap refuses: \`git init\` failed (${init.stderr.trim()}). Nothing was created.`);
    }
    // `git init -b` needs git ≥ 2.28; setting HEAD directly works everywhere and
    // is a no-op on an unborn branch.
    await run(['symbolic-ref', 'HEAD', `refs/heads/${branch}`], { allowFailure: true });
    await journal.append('git-init', { branch, gitDir: path.join(root, '.git') });

    // ---- STEP 4: the starter .gitignore (the disclosed ignore-rule write) ---
    await fs.writeFile(gitignoreAbs, plan.gitignore.content, 'utf8');
    await ensureReportDirIgnored({ reportDir, fs });
    const gitignoreHash = await hashOrNull(fs, gitignoreAbs);
    await journal.append('gitignore-write', {
      path: '.gitignore',
      mode: plan.gitignore.existed ? 'appended' : 'created',
      linesAdded: plan.gitignore.linesAdded,
      priorHash: plan.gitignore.priorHash,
      hash: gitignoreHash,
      secretLines: plan.secretPaths,
    });

    // ---- STEP 5: `git add -A`, which now cannot reach a flagged path -------
    const add = await run(['add', '-A'], { allowFailure: true });
    if (add.code !== 0) {
      await journal.append('git-add', { state: 'failed', stderr: add.stderr });
      await rollback({ root, fs, touched, journal });
      return refused(BOOTSTRAP_REFUSAL.GIT_FAILED, `Bootstrap refuses: \`git add -A\` failed (${add.stderr.trim()}). The repository and the .gitignore write were rolled back.`);
    }
    const staged = (await run(['diff', '--cached', '--name-only'], { allowFailure: true })).text
      .split('\n').map((s) => s.trim()).filter(Boolean);
    await journal.append('git-add', { state: 'done', staged: staged.length, afterTriage: true });

    // ---- STEP 6: verify the gate held, BEFORE writing the commit ----------
    const leaked = staged.filter((p) => plan.secretPaths.includes(toPosixRel(p)));
    if (leaked.length) {
      await rollback({ root, fs, touched, journal });
      return refused(BOOTSTRAP_REFUSAL.SECRET_IN_BASELINE,
        `Bootstrap refuses: ${leaked.length} secret-flagged path(s) reached the index despite the ignore rules (${leaked.join(', ')}). Nothing was committed and the repository was removed — a credential in a baseline commit is not a defect to be reported afterwards.`,
        { leaked });
    }

    if (!staged.length) {
      await rollback({ root, fs, touched, journal });
      return refused(BOOTSTRAP_REFUSAL.NOTHING_TO_COMMIT,
        'Bootstrap refuses: after ignore rules there is nothing to commit, so a baseline commit would be empty. The repository was removed and the folder is exactly as it was.');
    }

    // ---- STEP 7: ONE baseline commit B -------------------------------------
    const tree = (await run(['write-tree'])).text.trim();
    const commitEnv = await identityEnv(run, env);
    const message = buildBootstrapMessage({ runId, plan, staged });
    const commit = (await run(['commit-tree', tree, '-m', message], { env: commitEnv })).text.trim();
    await run(['update-ref', `refs/heads/${branch}`, commit], {});
    await journal.append('baseline', {
      commit, tree, branch, ref: `refs/heads/${branch}`,
      files: staged.length,
      excluded: plan.secretPaths,
    });

    // ---- STEP 8: verify the commit itself ----------------------------------
    const reachable = [];
    for (const rel of plan.secretPaths) {
      const probe = await run(['cat-file', '-e', `${commit}:${rel}`], { allowFailure: true });
      if (probe.code === 0) reachable.push(rel);
    }
    if (reachable.length) {
      await journal.append('verification', { state: 'failed', reachable });
      await rollback({ root, fs, touched, journal });
      return refused(BOOTSTRAP_REFUSAL.SECRET_IN_BASELINE,
        `Bootstrap refuses: ${reachable.length} secret-flagged path(s) are reachable from the baseline commit (${reachable.join(', ')}). The commit and the repository were removed. Amendment B is verified against the commit that was actually written, never assumed.`,
        { reachable });
    }
    await journal.append('verification', {
      state: 'ok',
      checked: plan.secretPaths,
      note: 'each flagged path was probed with `git cat-file -e <B>:<path>` and is NOT reachable from the baseline commit',
    });

    const result = {
      status: BOOTSTRAP_STATUS.BOOTSTRAPPED,
      code: null,
      runId,
      rootPath: root,
      commit,
      branch,
      ref: `refs/heads/${branch}`,
      files: staged.length,
      gitignore: {
        path: '.gitignore',
        mode: plan.gitignore.existed ? 'appended' : 'created',
        existedBefore: plan.gitignore.existed,
        linesAdded: plan.gitignore.linesAdded,
        hash: gitignoreHash,
      },
      secretsExcluded: plan.secrets.map((s) => ({ path: s.path, why: s.triggerSummary, inBaseline: false })),
      journal: { dir: journal.dir, file: journal.file },
      undo: {
        available: true,
        while: 'HEAD == B',
        how: 'remove .git and restore every journaled file to its prior state byte-for-byte; refused once HEAD has moved past B',
      },
      message: `bootstrapped: baseline commit ${commit.slice(0, 7)} on ${branch} holds ${staged.length} file(s)${plan.secrets.length ? `, with ${plan.secrets.length} secret-flagged path(s) ignored and verifiably absent from it` : ''}`,
    };
    await journal.writeSummary({ ...result, at: now().toISOString() });
    return result;
  } finally {
    await lock.release().catch(() => {});
  }

  function refused(code, message, extra = {}) {
    return { status: BOOTSTRAP_STATUS.REFUSED, code, message, commit: null, ...extra };
  }
}

/**
 * Take the folder back to exactly the state Bootstrap found it in. Used when a
 * step after `git init` fails — including, above all, the secret verification.
 */
async function rollback({ root, fs, touched, journal }) {
  for (const t of touched) {
    const abs = path.join(root, t.path);
    if (t.existedBefore) await fs.writeFile(abs, Buffer.from(t.priorContentBase64 || '', 'base64'));
    else await fs.rm(abs, { force: true });
  }
  await fs.rm(path.join(root, '.git'), { recursive: true, force: true, maxRetries: 5 });
  if (journal) await journal.append('rolled-back', { files: touched.map((t) => t.path), removedGit: true });
}

function buildBootstrapMessage({ runId, plan, staged }) {
  const lines = [
    `tidy-idy Bootstrap: baseline commit [run ${runId}]`,
    '',
    `${staged.length} file(s) — the folder as it stood when the repository was created.`,
  ];
  if (plan.secrets.length) {
    lines.push('', `EXCLUDED by secret triage, which ran BEFORE \`git add\` (Amendment B):`);
    for (const s of plan.secrets) lines.push(`  - ${s.path}: ${s.triggerSummary}`);
    lines.push('', 'Those paths are in .gitignore and are NOT in this commit. They are untouched on disk.');
  }
  lines.push('', 'Undo: while HEAD is this commit, tidy-idy can remove .git and restore every file it touched byte-for-byte.');
  return lines.join('\n');
}

/** Author/committer identity, so a background commit never fails on config. */
async function identityEnv(run, env) {
  const out = { ...env };
  const name = (await run(['config', '--get', 'user.name'], { allowFailure: true })).text.trim();
  const email = (await run(['config', '--get', 'user.email'], { allowFailure: true })).text.trim();
  if (!name) { out.GIT_AUTHOR_NAME = 'tidy-idy'; out.GIT_COMMITTER_NAME = 'tidy-idy'; }
  if (!email) { out.GIT_AUTHOR_EMAIL = 'tidy-idy@localhost'; out.GIT_COMMITTER_EMAIL = 'tidy-idy@localhost'; }
  return out;
}

/**
 * Is Bootstrap's undo still on the table? The panel asks this to decide whether
 * to render the control at all, so the answer is a record, not a boolean.
 *
 * @param {{rootPath: string, reportDir?: string, runId: string, fs?: object, env?: object, run?: Function}} opts
 */
export async function canUndoBootstrap(opts = {}) {
  const root = path.resolve(opts.rootPath);
  const reportDir = opts.reportDir ? path.resolve(opts.reportDir) : reportDirFor(root);
  const fs = opts.fs || fsp;

  const journal = await readJournal({ reportDir, runId: opts.runId, kind: BOOTSTRAP_KIND, fs });
  const baseline = journal ? [...journal.records].reverse().find((r) => r.type === 'baseline') : null;
  if (!baseline) {
    return { ok: false, code: BOOTSTRAP_REFUSAL.NO_JOURNAL, message: `no Bootstrap journal for run ${opts.runId} at ${reportDir} — there is nothing recorded to undo` };
  }

  const run = opts.run || makeGitRunner({ root, env: opts.env || process.env });
  const headRes = await run(['rev-parse', 'HEAD'], { allowFailure: true });
  if (headRes.code !== 0) {
    return { ok: false, code: BOOTSTRAP_REFUSAL.NOT_BOOTSTRAPPED, baseline, message: 'this folder has no repository (or no HEAD) — nothing for Bootstrap-undo to remove' };
  }
  const head = headRes.text.trim();
  const count = Number((await run(['rev-list', '--count', 'HEAD'], { allowFailure: true })).text.trim() || '0');

  if (head !== baseline.commit || count !== 1) {
    return {
      ok: false,
      code: BOOTSTRAP_REFUSAL.HEAD_MOVED,
      baseline,
      head,
      commits: count,
      message: `Bootstrap-undo REFUSED: HEAD has moved past the baseline commit (B=${String(baseline.commit).slice(0, 7)}, HEAD=${head.slice(0, 7)}, ${count} commit(s) on this branch). Removing .git now would discard work that git — and only git — is holding. Undo the later commits yourself first if this is really what you want.`,
    };
  }

  return { ok: true, baseline, head, journal };
}

/**
 * Undo a Bootstrap. Offered only while HEAD == B.
 *
 * @param {{rootPath: string, reportDir?: string, runId: string, fs?: object,
 *   env?: object, now?: Function, run?: Function, jobId?: string|null}} opts
 */
export async function undoBootstrap(opts = {}) {
  const fs = opts.fs || fsp;
  const now = opts.now || (() => new Date());
  const root = path.resolve(opts.rootPath);
  const reportDir = opts.reportDir ? path.resolve(opts.reportDir) : reportDirFor(root);
  const runId = opts.runId;

  const gate = await canUndoBootstrap({ ...opts, rootPath: root, reportDir, fs });
  if (!gate.ok) {
    return { status: BOOTSTRAP_STATUS.REFUSED, code: gate.code, message: gate.message, baseline: gate.baseline || null, restored: [], refused: [] };
  }

  const lock = await acquireLock({ reportDir, jobId: opts.jobId || null, purpose: 'bootstrap-undo', fs, now });
  if (!lock.ok) {
    return { status: BOOTSTRAP_STATUS.REFUSED, code: BOOTSTRAP_REFUSAL.LOCK_HELD, message: lock.message, holder: lock.holder, restored: [], refused: [] };
  }

  const journal = await openJournal({ reportDir, runId, kind: `${BOOTSTRAP_KIND}-undo`, fs, now });

  try {
    const priorRecord = [...gate.journal.records].reverse().find((r) => r.type === 'prior-state');
    const writeRecords = gate.journal.records.filter((r) => r.type === 'gitignore-write');
    const files = (priorRecord && priorRecord.files) || [];
    await journal.append('undo-start', { baseline: gate.baseline.commit, files: files.map((f) => f.path) });

    const restored = [];
    const refusedPaths = [];

    for (const f of files) {
      // What Bootstrap LEFT at this path — the no-clobber expectation.
      const written = writeRecords.find((w) => w.path === f.path) || null;
      const expected = { exists: true, hash: written ? written.hash : null };
      const guard = await checkPathAgainstExpectation({ rootPath: root, path: f.path, expected, fs });

      if (!guard.ok) {
        refusedPaths.push({
          path: f.path,
          reason: guard.reason,
          message: `${guard.message} — its prior content is still recorded verbatim in the Bootstrap journal (${gate.journal.file}) and can be restored by hand`,
          expected: guard.expected,
          actual: guard.actual,
        });
        await journal.append('restore', { path: f.path, state: 'refused', reason: guard.reason });
        continue;
      }

      await journal.append('restore', { path: f.path, state: 'started', existedBefore: f.existedBefore });
      const abs = path.join(root, f.path);
      if (f.existedBefore) {
        // Byte-for-byte. A pre-existing .gitignore is RESTORED, never deleted —
        // Bootstrap only ever appended to it.
        const bytes = Buffer.from(f.priorContentBase64 || '', 'base64');
        await fs.writeFile(abs, bytes);
        const after = await hashOrNull(fs, abs);
        await journal.append('restore', { path: f.path, state: 'done', mode: 'restored-prior-content', hash: after, bitIdentical: f.priorHash ? after === f.priorHash : null });
        restored.push({ path: f.path, mode: 'restored-prior-content', bytes: bytes.length, bitIdentical: f.priorHash ? after === f.priorHash : null });
      } else {
        // Bootstrap created it from nothing, so undo removes it.
        await fs.rm(abs, { force: true });
        await journal.append('restore', { path: f.path, state: 'done', mode: 'removed-file-bootstrap-created' });
        restored.push({ path: f.path, mode: 'removed-file-bootstrap-created' });
      }
    }

    await journal.append('remove-git', { state: 'started', dir: path.join(root, '.git') });
    await fs.rm(path.join(root, '.git'), { recursive: true, force: true, maxRetries: 5 });
    await journal.append('remove-git', { state: 'done' });

    const result = {
      status: refusedPaths.length ? BOOTSTRAP_STATUS.PARTIAL : BOOTSTRAP_STATUS.UNDONE,
      code: null,
      runId,
      baseline: gate.baseline.commit,
      removedGit: true,
      restored,
      refused: refusedPaths,
      journal: { dir: journal.dir, file: journal.file },
      message: refusedPaths.length
        ? `Bootstrap undone: .git removed and ${restored.length} file(s) put back, but ${refusedPaths.length} path(s) were REFUSED because they changed after the Bootstrap (${refusedPaths.map((r) => r.path).join(', ')}) — their current content was left exactly as it is`
        : `Bootstrap undone: .git removed and ${restored.length} file(s) restored to their exact prior state — the folder is byte-for-byte as it was before Bootstrap ran`,
    };
    await journal.writeSummary({ ...result, at: now().toISOString() });
    return result;
  } finally {
    await lock.release().catch(() => {});
  }
}

export default {
  planBootstrap, buildBootstrapTile, applyBootstrap, undoBootstrap, canUndoBootstrap,
  BOOTSTRAP_STATUS, BOOTSTRAP_REFUSAL, BOOTSTRAP_KIND,
};
