// engine/launch/archive.mjs — Wave 5: the per-project run archive.
//
// Every run is kept. Nothing is ever overwritten. That is the whole contract,
// and it is enforced structurally rather than promised: a run directory is
// created with `mkdir` WITHOUT `recursive` (which fails EEXIST rather than
// silently reusing an existing directory), and the run number is re-derived and
// retried on collision. There is no code path in this file that opens an
// existing run's file for writing.
//
// LAYOUT (identical on every launch path — CLI, cowork, Anchor button):
//
//   <root>/reports/tidy/run-007/
//     envelope.json               the Wave-1 machine envelope, verbatim
//     report.md                   the human report
//     protection-withheld.json    what was never offered, and why
//     excluded-subtrees.json      what the run did NOT look at
//     cost-and-coverage.json      the gate record + per-stage coverage + cache stats
//     .gitignore                  `*` — see below
//   <root>/.tidy-idy/runs-tidy/index.json
//     append-only, newest-first, one row per run
//
// TWO LOCATIONS, ON PURPOSE:
//
//   The ARTIFACTS live at the project root under `reports/tidy/` because they
//   are for the human: browsable, diffable, and reachable without knowing where
//   the tool hides its state (Gandalf's project-root `gandalf/run-<ts>/` for the
//   same reason).
//
//   The INDEX lives in the tool's OWN store (`reportDir/runs-tidy/index.json`).
//   It is namespaced away from Gandalf's index — a tidy run never writes a row
//   into `gandalf/index.json` — and, being tool-owned, it exists identically on
//   a plain folder that Anchor has never heard of. A standalone run needs no
//   Anchor project store to have a history.
//
// WRITING UNDER THE ROOT: the zero-write tripwire covers the ANALYSIS (stages
// write nothing outside reportDir). The archive is written by the LAUNCHER,
// after the run has completed and its snapshot sweep has already been taken, and
// it is the one disclosed exception the plan asks for. It self-ignores from the
// inside (`reports/tidy/.gitignore` containing `*`) exactly as the Trash does,
// so the tool still never edits the user's `.gitignore` — the consent-scope
// invariant is untouched.

import fsp from 'node:fs/promises';
import path from 'node:path';

import { writeBriefing, BRIEFING_FILENAME } from './briefing.mjs';

/** `<root>/reports/tidy` — the human-facing archive. */
export const ARCHIVE_REL = 'reports/tidy';
/** `<reportDir>/runs-tidy/index.json` — the tool-owned, Gandalf-free run index. */
export const RUNS_INDEX_DIRNAME = 'runs-tidy';
export const RUNS_INDEX_FILENAME = 'index.json';
export const RUNS_INDEX_SCHEMA_VERSION = 1;

export const ARCHIVE_FILES = Object.freeze({
  ENVELOPE: 'envelope.json',
  REPORT: 'report.md',
  WITHHELD: 'protection-withheld.json',
  EXCLUDED: 'excluded-subtrees.json',
  COST: 'cost-and-coverage.json',
  /**
   * Wave 7: the per-run investigator briefing — engine-agnostic markdown a
   * seeded agent terminal reads, distinct from the panel JSON. Written with a
   * plain (non-wx) write because it is regenerable and is REFRESHED at launch to
   * match the environment the terminal actually opens in (see briefing.mjs).
   */
  BRIEFING: BRIEFING_FILENAME,
});

export function archiveDirFor(rootPath) {
  return path.join(path.resolve(rootPath), ...ARCHIVE_REL.split('/'));
}

export function runDirName(n) {
  return `run-${String(n).padStart(3, '0')}`;
}

export function runDirFor(rootPath, n) {
  return path.join(archiveDirFor(rootPath), runDirName(n));
}

export function runsIndexPathFor(reportDir) {
  return path.join(reportDir, RUNS_INDEX_DIRNAME, RUNS_INDEX_FILENAME);
}

/** The highest existing run number in the archive, or 0. */
export async function highestRunNumber(rootPath, { fs = fsp } = {}) {
  let names;
  try {
    names = await fs.readdir(archiveDirFor(rootPath));
  } catch {
    return 0;
  }
  let max = 0;
  for (const name of names) {
    const m = /^run-(\d+)$/.exec(name);
    if (m) max = Math.max(max, Number.parseInt(m[1], 10));
  }
  return max;
}

/**
 * Self-ignore the archive from the inside, so the tool never edits the project's
 * own .gitignore to keep its regenerable output out of `git status`.
 */
export async function ensureArchiveIgnored(rootPath, { fs = fsp } = {}) {
  const dir = archiveDirFor(rootPath);
  const file = path.join(dir, '.gitignore');
  try {
    await fs.stat(file);
    return { written: false, path: file };
  } catch { /* absent */ }
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(file,
    "# tidy-idy's own per-run report archive.\n"
    + '# Self-ignoring so the tool never has to edit YOUR .gitignore (consent scope).\n'
    + '*\n', 'utf8');
  return { written: true, path: file };
}

/**
 * Archive one completed run.
 *
 * @param {{rootPath: string, reportDir: string, envelope: object, identity: object,
 *          costGate?: object|null, verdictCache?: object|null, launchedBy?: string,
 *          panel?: object|null, fs?: object, now?: Function}} opts
 * @returns {Promise<{runNumber: number, dir: string, files: object, indexPath: string, record: object}>}
 */
export async function archiveRun({
  rootPath,
  reportDir,
  envelope,
  identity,
  costGate = null,
  verdictCache = null,
  launchedBy = 'cli',
  panel = null,
  fs = fsp,
  now = () => new Date(),
} = {}) {
  await ensureArchiveIgnored(rootPath, { fs });

  // Create the run directory NON-recursively so an existing run is an EEXIST,
  // not a silent overwrite. Re-derive and retry — two concurrent launches would
  // in any case have contended on the lock long before reaching here.
  let n = (await highestRunNumber(rootPath, { fs })) + 1;
  let dir = runDirFor(rootPath, n);
  for (let attempt = 0; attempt < 50; attempt++) {
    try {
      await fs.mkdir(dir);
      break;
    } catch (err) {
      if (!err || err.code !== 'EEXIST') throw err;
      n += 1;
      dir = runDirFor(rootPath, n);
      if (attempt === 49) throw new Error(`could not allocate a fresh run directory under ${archiveDirFor(rootPath)} — 50 consecutive numbers were taken`);
    }
  }

  const written = {};
  const put = async (name, text) => {
    // 'wx': fail rather than overwrite. Belt and braces with the mkdir above.
    await fs.writeFile(path.join(dir, name), text, { encoding: 'utf8', flag: 'wx' });
    written[name] = path.join(dir, name);
  };

  await put(ARCHIVE_FILES.ENVELOPE, `${JSON.stringify(envelope, null, 2)}\n`);
  await put(ARCHIVE_FILES.WITHHELD, `${JSON.stringify({
    note: 'paths the protection predicate withheld before emission — the tool considered them and refused to offer them',
    withheld: envelope.protectionWithheld || [],
  }, null, 2)}\n`);
  await put(ARCHIVE_FILES.EXCLUDED, `${JSON.stringify({
    note: 'what this run did NOT look at, and why — a partial tree is never reported as the whole thing',
    excludedSubtrees: (envelope.topology && envelope.topology.excludedSubtrees) || [],
    links: (envelope.topology && envelope.topology.links) || [],
  }, null, 2)}\n`);
  await put(ARCHIVE_FILES.COST, `${JSON.stringify({
    costGate: costGate || envelope.costGate || null,
    verdictCache: verdictCache || envelope.verdictCache || null,
    coverage: (envelope.stages || []).map((s) => ({ stage: s.stage, status: s.status, coverage: s.coverage })),
  }, null, 2)}\n`);
  await put(ARCHIVE_FILES.REPORT, renderReportMarkdown({ envelope, identity, runNumber: n, costGate, verdictCache, launchedBy }));

  // The investigator briefing. NOT put() (not wx-guarded): it is regenerable and
  // is refreshed at launch to inline the skill when it is unresolvable in the
  // opening environment. Written last so a briefing failure never aborts the
  // canonical artifacts above.
  const briefing = await writeBriefing({ runDir: dir, envelope, identity, runNumber: n, fs });
  written[ARCHIVE_FILES.BRIEFING] = briefing.path;

  const record = {
    schemaVersion: RUNS_INDEX_SCHEMA_VERSION,
    runNumber: n,
    runId: envelope.runId,
    runDir: dir,
    project: { name: identity.name, path: identity.path },
    git: identity.git,
    mode: envelope.mode,
    status: envelope.status,
    isClean: envelope.isClean,
    findings: (envelope.findings || []).length,
    costGated: Boolean((costGate || envelope.costGate || {}).gated),
    launchedBy,
    startedAt: envelope.startedAt,
    endedAt: envelope.endedAt,
    archivedAt: now().toISOString(),
    ...(panel ? { panel: { url: panel.url || null } } : {}),
  };

  const indexPath = await appendRunIndex({ reportDir, record, fs });

  return { runNumber: n, dir, files: written, indexPath, record };
}

/**
 * Prepend a record to the newest-first run index.
 *
 * APPEND-ONLY: existing rows are re-serialised byte-for-byte from what was read
 * and never edited, and no row is ever dropped. (Gandalf's index caps at 20 and
 * upserts in place; the tidy index deliberately does neither — 'previous reports
 * kept as browsable references, never overwritten' is a criterion here.)
 */
export async function appendRunIndex({ reportDir, record, fs = fsp } = {}) {
  const file = runsIndexPathFor(reportDir);
  await fs.mkdir(path.dirname(file), { recursive: true });
  const existing = await readRunIndex(reportDir, { fs });
  const runs = [record, ...existing];
  const tmp = `${file}.tmp`;
  await fs.writeFile(tmp, `${JSON.stringify({ schemaVersion: RUNS_INDEX_SCHEMA_VERSION, runs }, null, 2)}\n`, 'utf8');
  await fs.rename(tmp, file);
  return file;
}

/** Read the index newest-first. Honest empty on absence or corruption. */
export async function readRunIndex(reportDir, { fs = fsp } = {}) {
  try {
    const parsed = JSON.parse(String(await fs.readFile(runsIndexPathFor(reportDir), 'utf8')));
    if (Array.isArray(parsed)) return parsed;
    if (parsed && Array.isArray(parsed.runs)) return parsed.runs;
    return [];
  } catch {
    return [];
  }
}

/**
 * The human report. Envelope-driven end to end: every claim below is read off
 * the envelope, so a run that failed a stage cannot render as a clean report.
 */
export function renderReportMarkdown({ envelope, identity, runNumber, costGate = null, verdictCache = null, launchedBy = 'cli' }) {
  const L = [];
  const gate = costGate || envelope.costGate || null;
  const cache = verdictCache || envelope.verdictCache || null;

  L.push(`# tidy-idy — ${identity.name} — run ${runNumber}`);
  L.push('');
  L.push(`- **Project**: \`${identity.path}\``);
  L.push(`- **Git**: ${identity.git.present
    ? `${identity.git.branch || 'detached'} @ ${identity.git.shortSha || '(no commits)'}${Number.isInteger(identity.git.dirtyCount) ? ` — ${identity.git.dirtyCount} dirty path(s)` : ''}`
    : 'no repository (removals apply through the reversible Trash)'}`);
  L.push(`- **Mode**: ${envelope.mode}`);
  L.push(`- **Run id**: \`${envelope.runId}\``);
  L.push(`- **Launched by**: ${launchedBy}`);
  L.push(`- **Started / ended**: ${envelope.startedAt} → ${envelope.endedAt}`);
  L.push(`- **Terminal status**: **${String(envelope.status).toUpperCase()}** (worst stage status)`);
  L.push('');

  if (envelope.isClean) {
    L.push('## Clean');
    L.push('');
    L.push('Every stage completed with complete coverage, no tripwire violation, and zero findings.');
  } else {
    L.push('## Not clean');
    L.push('');
    L.push('This run is **not** a clean verdict. Exactly why:');
    L.push('');
    for (const b of envelope.cleanBlockers || []) L.push(`- ${b}`);
  }
  L.push('');

  if (gate && gate.gated) {
    L.push('## ⚠ Cost-gated — full run needs confirmation');
    L.push('');
    L.push(gate.banner ? gate.banner.message : 'the run completed in auto-degraded scope');
    L.push('');
    for (const step of (gate.degradation && gate.degradation.steps) || []) {
      L.push(`- **rung ${step.rung} — ${step.step}**: ${step.why} (${step.before.files} → ${step.after.files} file(s))`);
    }
    L.push('');
    L.push('The run never blocked awaiting input. Confirm a full-scope re-run from the panel.');
    L.push('');
  }

  L.push('## Stages');
  L.push('');
  L.push('| stage | status | scanned | skipped | errored | note |');
  L.push('| --- | --- | --- | --- | --- | --- |');
  for (const s of envelope.stages || []) {
    const c = s.coverage || {};
    L.push(`| ${s.stage} | ${s.status} | ${c.scanned || 0} | ${c.skipped || 0} | ${c.errored || 0} | ${(c.note || '').replace(/\|/g, '\\|')} |`);
  }
  L.push('');

  if ((envelope.errors || []).length) {
    L.push('## Errors (verbatim)');
    L.push('');
    for (const e of envelope.errors) L.push(`- **${e.stage}**: ${e.message}`);
    L.push('');
  }

  const byAction = new Map();
  for (const f of envelope.findings || []) {
    const key = f.action || f.kind || 'finding';
    if (!byAction.has(key)) byAction.set(key, []);
    byAction.get(key).push(f);
  }
  L.push('## Findings');
  L.push('');
  if (!byAction.size) {
    L.push('_None._');
    L.push('');
  }
  for (const [action, list] of byAction) {
    L.push(`### ${action} (${list.length})`);
    L.push('');
    for (const f of list) {
      const flags = [
        f.stale ? 'STALE' : null,
        f.label || null,
        f.defaultChecked === false ? 'default-unchecked' : null,
        f.removalClass ? `class=${f.removalClass}` : null,
      ].filter(Boolean);
      L.push(`- \`${f.path}\`${flags.length ? ` — _${flags.join(', ')}_` : ''}`);
      if (f.evidence && f.evidence.rationale) L.push(`  - judge (verbatim): ${f.evidence.rationale}`);
      if (f.undo) L.push(`  - undo: ${f.undo}`);
    }
    L.push('');
  }

  if ((envelope.protectionWithheld || []).length) {
    L.push('## Withheld by protection');
    L.push('');
    for (const w of envelope.protectionWithheld) L.push(`- \`${w.path}\` — ${w.why}`);
    L.push('');
  }

  if (cache) {
    L.push('## Verdict cache');
    L.push('');
    L.push(`- hits ${cache.hits || 0}, misses ${cache.misses || 0}, stored ${cache.stores || 0} (${cache.keyedBy || ''})`);
    L.push('');
  }

  L.push('---');
  L.push('');
  L.push('Nothing in this report has been applied. Approval happens in the Triage Panel, one Apply per run.');
  L.push('');
  return L.join('\n');
}

export default {
  archiveRun, appendRunIndex, readRunIndex, renderReportMarkdown, ensureArchiveIgnored,
  archiveDirFor, runDirFor, runDirName, runsIndexPathFor, highestRunNumber,
  ARCHIVE_REL, ARCHIVE_FILES, RUNS_INDEX_DIRNAME, RUNS_INDEX_FILENAME,
};
