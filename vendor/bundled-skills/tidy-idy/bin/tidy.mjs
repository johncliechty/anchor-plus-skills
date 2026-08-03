#!/usr/bin/env node
// tidy.mjs — the orchestrator (C9 simplify-first completion, 2026-07-11).
//
// The pipeline per project: hygiene pre-flight (git required — git IS the archive)
// → batched analysis → single-pass adversarial debate → REMOVE + commit
// (remove.mjs; recovery = git revert) → context compression → commit the
// compression edits. Per-project isolation: one refused/failed project SKIPS with
// a loud note; it never aborts the batch (the old loop aborted every remaining
// project at the first dirty tree — a scheduled hygiene tool that failed its own
// hygiene gate). Every run writes a training record (AGENTS.md "Run capture").

import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { exec } from 'node:child_process';
import { promisify } from 'node:util';

import { scan } from './scanner.mjs';
import { runHygieneCheck } from './hygiene.mjs';
import { runAnalysis } from './analyze.mjs';
import { runDebate } from './debate.mjs';
import { runRemoval } from './remove.mjs';
import { runCompression } from './compress.mjs';

const execAsync = promisify(exec);

/**
 * Finds default target directory if none is provided.
 */
async function getDefaultTargetDir() {
  const parentDir = path.resolve('..');
  try {
    const parentFiles = await fs.readdir(parentDir);
    let hasSkillsInParent = false;
    for (const file of parentFiles) {
      if (file === 'tidy-idy') continue;
      const fullPath = path.join(parentDir, file);
      const stat = await fs.stat(fullPath);
      if (stat.isDirectory()) {
        const subFiles = await fs.readdir(fullPath);
        if (subFiles.includes('SKILL.md') || subFiles.includes('NORTH-STAR.md') || subFiles.includes('INTENT.md')) {
          hasSkillsInParent = true;
          break;
        }
      }
    }
    return hasSkillsInParent ? parentDir : '.';
  } catch {
    return '.';
  }
}

/** Run capture for training (canonical: Skill Foundry AGENTS.md → "Run capture"). Best-effort. */
export function writeRunRecord(record) {
  try {
    const skillDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    const dir = path.join(skillDir, 'journal', 'runs');
    return fs.mkdir(dir, { recursive: true }).then(() => {
      const started = record.started || new Date().toISOString();
      const file = path.join(dir, `${started.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`);
      return fs.writeFile(file, JSON.stringify({ skill: 'tidy-idy', ...record }, null, 2) + '\n', 'utf8').then(() => file);
    }).catch(() => null);
  } catch { return Promise.resolve(null); }
}

/**
 * Orchestrates the pipeline per project and emits a final Hygiene Report.
 *
 * @param {string} targetDir Target directory to scan.
 * @param {object} options Overrides for testing and LLM execution.
 */
export async function runOrchestration(targetDir, options = {}) {
  const log = options.log || (() => {});
  const outputStream = options.stdout || process.stdout;
  const started = new Date().toISOString();
  const t0 = Date.now();

  // C9: state lives INSIDE the target dir (the old CWD-relative .tidy-idy wrote
  // state wherever the tool happened to be launched from) and is gitignored.
  const stateDir = path.join(path.resolve(targetDir), '.tidy-idy');
  await fs.mkdir(stateDir, { recursive: true });

  // 1. Scan for projects
  const projects = await scan(targetDir);
  await fs.writeFile(path.join(stateDir, 'projects.json'), JSON.stringify(projects, null, 2), 'utf8');

  if (projects.length === 0) {
    outputStream.write(`# tidy-idy Hygiene Report\n\nNo active Foundry projects found in target directory: ${targetDir}\n`);
    return { projects: [], removed: [], protectedSkips: [], skipped: [], failed: [], compression: [] };
  }

  const totals = { removed: [], protectedSkips: [], skipped: [], failed: [], compression: [] };
  const execFn = options.exec || execAsync;

  // Per-project pipeline — ISOLATED: a refusal/failure skips THIS project only.
  for (const project of projects) {
    const projectPath = project.path;
    const northStarFile = project.north_star_file;
    try {
      // A. Git hygiene pre-flight (non-git = hard refusal inside; dirty = prompt/refuse)
      await runHygieneCheck(projectPath, { ...options, throwOnError: true });

      // B. Batched analysis (LOUD on failure — never a clean-looking empty result)
      const suspects = await runAnalysis(projectPath, { ...options, northStarFile, throwOnError: true });
      await fs.writeFile(path.join(stateDir, 'suspects_batch.json'), JSON.stringify(suspects, null, 2), 'utf8');

      // C. Single-pass adversarial debate (attacker + judge, structured)
      const judgments = await runDebate(projectPath, suspects, { ...options, northStarFile, throwOnError: true });
      await fs.writeFile(path.join(stateDir, 'judgments.json'), JSON.stringify(judgments, null, 2), 'utf8');

      // D. REMOVE + commit (git is the archive)
      const removal = await runRemoval(projectPath, judgments, options);
      totals.removed.push(...removal.removed.map((r) => ({ project: projectPath, ...r, commit: removal.commit })));
      totals.protectedSkips.push(...removal.protectedSkips.map((r) => ({ project: projectPath, ...r })));
      totals.skipped.push(...removal.skipped.map((r) => ({ project: projectPath, ...r })));

      // E. Context compression, then COMMIT its edits (the run leaves the tree clean —
      //    the old flow dirtied the repo and blocked the next scheduled run).
      const compression = await runCompression(projectPath, { ...options, throwOnError: true });
      totals.compression.push(compression);
      try {
        const { stdout: dirty } = await execFn('git status --porcelain', { cwd: path.resolve(projectPath) });
        if (String(dirty).trim()) {
          await execFn('git add -A', { cwd: path.resolve(projectPath) });
          await execFn('git commit -m "tidy-idy: context compression (agent.md/agent_hist.md refresh)"', { cwd: path.resolve(projectPath) });
        }
      } catch (err) {
        throw new Error(`compression commit failed in ${projectPath}: ${err.message}`);
      }
    } catch (err) {
      totals.failed.push({ project: projectPath, error: err.message });
      outputStream.write(`\n!! SKIPPED ${projectPath}: ${err.message}\n`);
      continue; // isolation — the batch survives one bad project
    }
  }

  // The report
  let report = `# tidy-idy Hygiene Report

## Project Summary
Processed ${projects.length} project(s):
${projects.map(p => `- \`${p.path}\``).join('\n')}

## Operations Summary
- **Removed (git-committed, revertable)**: ${totals.removed.length}
- **Protected skips (never removable)**: ${totals.protectedSkips.length}
- **Other skips**: ${totals.skipped.length}
- **Projects skipped on error/refusal**: ${totals.failed.length}

## Details

### Removed (recovery: git revert the named commit)
`;
  report += totals.removed.length
    ? totals.removed.map((r) => `- \`${r.filepath}\` (${r.project} @ ${r.commit})\n`).join('')
    : 'None\n';
  report += '\n### Protected skips\n';
  report += totals.protectedSkips.length
    ? totals.protectedSkips.map((r) => `- \`${r.rel || r.filepath}\` — ${r.why}\n`).join('')
    : 'None\n';
  report += '\n### Other skips\n';
  report += totals.skipped.length
    ? totals.skipped.map((r) => `- \`${r.filepath || '(unknown)'}\` — ${r.why}\n`).join('')
    : 'None\n';
  report += '\n### Projects skipped (error/refusal)\n';
  report += totals.failed.length
    ? totals.failed.map((f) => `- \`${f.project}\` — ${f.error}\n`).join('')
    : 'None\n';

  outputStream.write(report);

  // Run capture is for REAL runs — tests/harnesses pass captureRuns:false so the
  // training feed never carries mock-run records (provenance discipline).
  if (options.captureRuns !== false) await writeRunRecord({
    tier: 'standard', started, ended: new Date().toISOString(),
    input: path.resolve(targetDir),
    params: { projects: projects.length },
    output: '(report to stdout; state in <target>/.tidy-idy)',
    result: `removed ${totals.removed.length} · protected ${totals.protectedSkips.length} · skippedProjects ${totals.failed.length}`,
    cross_model: true, models: null,
    duration_s: Math.round((Date.now() - t0) / 1000), journal_ref: null,
  });

  return { projects, ...totals };
}

async function main() {
  try {
    let target = process.argv[2];
    if (!target) {
      target = await getDefaultTargetDir();
    }
    const resolvedTarget = path.resolve(target);
    await runOrchestration(resolvedTarget);
    process.exit(0);
  } catch (error) {
    console.error('Orchestration failed:', error.message);
    process.exit(1);
  }
}

const isDirectRun = process.argv[1] && (
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))
);

if (isDirectRun || process.argv[1]?.endsWith('tidy.mjs')) {
  main();
}
