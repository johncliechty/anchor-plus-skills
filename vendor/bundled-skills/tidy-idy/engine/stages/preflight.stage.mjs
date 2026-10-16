// engine/stages/preflight.stage.mjs — Wave 2: the non-git preflight, as PURE ANALYSIS.
//
// When a run's root has no repository, this stage answers three questions that
// a human needs answered BEFORE deciding whether to bootstrap one — and answers
// them by looking, never by acting:
//
//   1. IS THERE AN ENCLOSING REPOSITORY? Running `git init` inside a directory
//      that is already inside someone's work tree creates a nested repo whose
//      contents the outer repo then sees as an opaque gitlink. The honest
//      recommendation there is "use the enclosing repo", not "initialise here".
//
//   2. IS THIS FOLDER INSIDE A CLOUD-SYNC TREE? Dropbox/OneDrive/Drive rewrite
//      files under you, including .git internals, at times you do not choose.
//      A repository living there is a real hazard and the user should know.
//
//   3. HOW BIG IS IT? `git add -A` over a tree with a build output directory in
//      it commits gigabytes. Above a threshold the proposal asks for explicit
//      confirmation instead of assuming.
//
// The stage PROPOSES Bootstrap and stops. Bootstrap is its own Apply
// (engine/apply/bootstrap.mjs, secret-triage-first per Amendment B), and
// Amendment A already demoted it from
// a gate to an optional upgrade: removals work on a plain folder through the
// reversible Trash whether or not anyone ever bootstraps.

import path from 'node:path';
import { makeStageResult, STATUS } from '../envelope.mjs';

/** Above this many in-scope files, Bootstrap asks for explicit confirmation. */
export const SIZE_CONFIRM_FILES = 5000;
/** Above this many bytes, likewise. */
export const SIZE_CONFIRM_BYTES = 250 * 1024 * 1024;

/** Path segments that mean "a sync client owns this directory". */
const CLOUD_SEGMENTS = Object.freeze([
  'dropbox', 'onedrive', 'google drive', 'googledrive', 'my drive',
  'icloud drive', 'com~apple~clouddocs', 'box sync', 'pcloudrive', 'mega',
  'creative cloud files', 'nextcloud', 'syncthing', 'yandexdisk',
]);

/** Marker files a sync client leaves in a directory it manages. */
const CLOUD_SENTINEL_FILES = Object.freeze([
  '.dropbox', '.dropbox.cache', '.dropbox.attr', '.icloud',
  'desktop.ini', '.nextcloudsync.log', '.sync.ffs_db', '.stfolder',
]);

export const preflightStage = {
  name: 'preflight',
  requiresGit: false,
  gitNull: {
    status: STATUS.OK,
    // Exactly one proposal finding when there is no repo, and it is a PROPOSAL
    // (action='propose-bootstrap' is not actionable) — nothing is applied here.
    findings: 1,
    note: 'no repo — the preflight runs and PROPOSES Bootstrap; it writes nothing and Bootstrap remains optional (Amendment A)',
  },

  async run(ctx) {
    if (ctx.git) {
      return makeStageResult({
        stage: preflightStage.name,
        status: STATUS.OK,
        coverage: { scanned: 0, skipped: 0, errored: 0, note: 'a repository already exists at the run root — the Bootstrap preflight does not apply' },
        findings: [],
        notes: [`repository present (${ctx.git.toplevel}) — nothing to bootstrap`],
      });
    }

    const enclosing = await findEnclosingRepo(ctx);
    const cloud = await detectCloudSync(ctx);
    const size = estimateSize(ctx);

    const blockers = [];
    if (enclosing) {
      blockers.push({
        kind: 'enclosing-repo',
        severity: 'high',
        detail: `this folder already sits inside the work tree of the repository at '${enclosing}'`,
        recommendation: 'use the enclosing repository rather than initialising a nested one — a nested repo appears to the outer repo as an opaque gitlink and its contents stop being versioned there',
      });
    }
    if (cloud.detected) {
      blockers.push({
        kind: 'cloud-sync',
        severity: 'high',
        detail: `cloud-sync markers detected: ${cloud.evidence.join('; ')}`,
        recommendation: 'a git repository inside a cloud-sync tree can be corrupted by the sync client rewriting .git internals mid-operation — prefer a location the sync client does not manage',
      });
    }
    if (size.needsConfirmation) {
      blockers.push({
        kind: 'size',
        severity: 'medium',
        detail: `${size.files} in-scope file(s), ${size.bytes} byte(s) — above the confirmation threshold (${SIZE_CONFIRM_FILES} files / ${SIZE_CONFIRM_BYTES} bytes)`,
        recommendation: 'confirm explicitly before a baseline commit captures a tree this size, and consider adding exclusions to .tidy-idy.toml first',
      });
    }

    const finding = {
      stage: preflightStage.name,
      kind: 'bootstrap-proposal',
      // NOT actionable: this stage proposes, it never applies. Bootstrap is its
      // own Apply with its own approval (engine/apply/bootstrap.mjs).
      action: 'propose-bootstrap',
      approvable: true,
      defaultChecked: false,
      path: null,
      rootPath: ctx.rootPath,
      optional: true,
      why: 'this folder has no git repository. Bootstrap (`git init` + a starter .gitignore + a baseline commit) is OPTIONAL — removals already work here through the reversible Trash (Amendment A). Bootstrap buys you SAVE findings and git-revert undo.',
      evidence: {
        enclosingRepo: enclosing,
        cloudSync: cloud,
        size,
      },
      blockers,
      plannedOps: [
        { kind: 'git-init', summary: '`git init` at the run root' },
        { kind: 'starter-gitignore', summary: 'write a starter .gitignore — the ONE operation whose tile discloses an ignore-rule write (consent scope)', includesSecretPaths: true },
        { kind: 'secret-triage-first', summary: 'run secret triage BEFORE any `git add`, so every secret-flagged path lands in .gitignore and is EXCLUDED from the baseline commit (Amendment B)' },
        { kind: 'baseline-commit', summary: 'one baseline commit B — a fixed op-set, never mixed with findings' },
      ],
      undo: 'while HEAD==B: remove .git and restore every journaled file to its prior state byte-for-byte; refused once HEAD has moved past B (engine/apply/bootstrap.mjs)',
      note: 'the scan itself writes NOTHING — this is a proposal record, and Bootstrap runs only as its own separately approved Apply',
    };

    return makeStageResult({
      stage: preflightStage.name,
      status: STATUS.OK,
      coverage: {
        scanned: size.files,
        skipped: 0,
        errored: 0,
        note: 'pure analysis: enclosing-repo detection, cloud-sync sentinels and size estimation — no filesystem mutation of any kind',
      },
      findings: [finding],
      notes: [
        'no repository at the run root — the preflight PROPOSES Bootstrap and does nothing else',
        `Bootstrap is optional, not a gate: approved removals here move into the reversible Trash and restore from it (Amendment A)${blockers.length ? `; ${blockers.length} caution(s) recorded on the proposal` : ''}`,
      ],
      data: { enclosingRepo: enclosing, cloudSync: cloud, size, blockers },
    });
  },
};

/** Walk upward looking for a .git — filesystem only, no process spawn. */
async function findEnclosingRepo(ctx) {
  let dir = path.dirname(path.resolve(ctx.rootPath));
  let previous = null;
  while (dir && dir !== previous) {
    try {
      await ctx.fs.stat(path.join(dir, '.git'));
      return dir;
    } catch { /* keep walking */ }
    previous = dir;
    dir = path.dirname(dir);
  }
  return null;
}

async function detectCloudSync(ctx) {
  const evidence = [];
  const root = path.resolve(ctx.rootPath);
  const lowered = root.toLowerCase().replace(/\\/g, '/');
  for (const seg of CLOUD_SEGMENTS) {
    if (lowered.includes(`/${seg}/`) || lowered.endsWith(`/${seg}`)) {
      evidence.push(`the absolute path contains a '${seg}' directory`);
    }
  }
  for (const sentinel of CLOUD_SENTINEL_FILES) {
    try {
      await ctx.fs.stat(path.join(root, sentinel));
      evidence.push(`sentinel file '${sentinel}' present at the run root`);
    } catch { /* absent */ }
  }
  return { detected: evidence.length > 0, evidence };
}

function estimateSize(ctx) {
  const snapshot = ctx.state.snapshot;
  const paths = snapshot && snapshot.paths ? snapshot.paths : {};
  const files = Object.keys(paths).length || (ctx.state.inScope || []).length;
  let bytes = 0;
  for (const meta of Object.values(paths)) bytes += Number(meta.size || 0);
  return {
    files,
    bytes,
    needsConfirmation: files > SIZE_CONFIRM_FILES || bytes > SIZE_CONFIRM_BYTES,
    thresholds: { files: SIZE_CONFIRM_FILES, bytes: SIZE_CONFIRM_BYTES },
  };
}

export default preflightStage;
