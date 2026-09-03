#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { reportDirFor } from '../engine/report-dir.mjs';
import { resolveAgent } from '../engine/agent-seam.mjs';

/**
 * Recursively locates all file paths inside a target directory,
 * ignoring hidden directories and files, and node_modules.
 *
 * `io` exists so the Wave-1 stage can hand in ctx.fs — the write-audit
 * facade. Every filesystem call this library makes on the staged path then goes
 * through Tier 1 of the tripwire, so "every stage performs fs access through the
 * facade" is true of the whole call tree, not just the stage wrapper. The
 * default keeps the legacy CLI path byte-for-byte unchanged.
 */
async function getProjectFiles(dir, io = fs) {
  const filesList = [];
  async function walk(currentDir) {
    const name = path.basename(currentDir);
    if (name.startsWith('.') || name === 'node_modules') {
      return;
    }
    let stats;
    try {
      stats = await io.stat(currentDir);
    } catch {
      return;
    }
    if (stats.isDirectory()) {
      let files;
      try {
        files = await io.readdir(currentDir);
      } catch {
        return;
      }
      for (const file of files) {
        await walk(path.join(currentDir, file));
      }
    } else if (stats.isFile()) {
      if (name === 'projects.json' || name === 'suspects_batch.json' || name === 'judgments.json') {
        return;
      }
      filesList.push(currentDir);
    }
  }
  await walk(dir);
  return filesList;
}

/**
 * Helper to prioritize and locate a project's North Star file.
 */
async function findNorthStarFile(projectPath, io = fs) {
  try {
    const files = await io.readdir(projectPath);
    if (files.includes('NORTH-STAR.md')) {
      return path.join(projectPath, 'NORTH-STAR.md');
    } else if (files.includes('INTENT.md')) {
      return path.join(projectPath, 'INTENT.md');
    } else if (files.includes('SKILL.md')) {
      return path.join(projectPath, 'SKILL.md');
    }
  } catch {}
  return null;
}

/**
 * Analyzes a single project against its North Star file using the Gandalf persona.
 * 
 * @param {string} projectPath Absolute path to target project
 * @param {object} options Override configurations
 * @returns {Promise<Array<{filepath: string, reason: string}>>}
 */
export async function runAnalysis(projectPath, options = {}) {
  const log = options.log || (() => {});
  // Wave-1: the staged pipeline injects ctx.fs (the write-audit facade) here, so
  // this library's reads are audited exactly like the stage wrapper's. Absent an
  // injection this is the plain fs module — the legacy CLI path is unchanged.
  const io = options.fs || fs;
  try {
    const northStarFile = options.northStarFile || await findNorthStarFile(projectPath, io);
    if (!northStarFile) {
      throw new Error(`No North Star file found in project: ${projectPath}`);
    }

    const northStarContent = await io.readFile(northStarFile, 'utf8');
    const northStarFileName = path.basename(northStarFile);

    const filePaths = await getProjectFiles(projectPath, io);
    const filesData = [];

    // Wave-2: the UNIVERSAL PRE-LLM GATE's hard filter. The staged pipeline
    // passes the triage stage's verdict in here, so a secret-flagged file is
    // excluded from the prompt at the point the prompt is BUILT — the only place
    // the exclusion can actually prevent a leak. Absent an injection this admits
    // everything, so the legacy CLI path is unchanged.
    const isAllowed = options.isAllowed || (() => true);
    let gateBlocked = 0;

    for (const filePath of filePaths) {
      if (!isAllowed(filePath)) { gateBlocked++; continue; }
      try {
        const stat = await io.stat(filePath);
        if (stat.size > 500 * 1024) continue; // Skip files > 500KB
        const content = await io.readFile(filePath, 'utf8');
        if (content.includes('\u0000')) continue; // Skip binary files
        
        const relativePath = path.relative(projectPath, filePath).replace(/\\/g, '/');
        filesData.push({
          path: relativePath,
          absolutePath: filePath,
          content
        });
      } catch {
        // Skip unreadable files
      }
    }

    if (gateBlocked) {
      log(`pre-LLM gate withheld ${gateBlocked} file(s) from the analysis prompt — their content never enters an LLM context.`);
    }

    if (filesData.length === 0) {
      return [];
    }

    const schema = {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          filepath: { type: 'string' },
          reason: { type: 'string' }
        },
        required: ['filepath', 'reason']
      }
    };

    // C9 (2026-07-11): the DEFAULT model comes from the trio driver's catalogue —
    // the old hardcoded 'gemini-1.5-pro' was an API-style id agy does not recognize,
    // so EVERY real run silently degraded/failed and returned a clean-looking empty
    // report. The tool failed quiet, forever. Never hardcode a model id here again.
    //
    // Wave-1 refactor-in-place (Wave-0 seam: hardcoded-path). The driver is no
    // longer a hardcoded absolute machine path — it is resolved from the
    // injected agent, config, or an env var, and an unresolvable driver fails
    // LOUDLY at the call site instead of at an import of <path>
    const agentFn = resolveAgent({
      agent: options.agent,
      runAgent: options.runAgent,
      driverPath: options.driverPath,
      model: options.model,
      log,
      env: options.env || process.env,
      target: projectPath,
      onReceipt: options.onSeatReceipt,
    });

    // C9: analysis is BATCHED by total bytes (the debate stage always was; the
    // analysis that fed it concatenated the ENTIRE project into one prompt, which
    // blew up on any project with a real engine). ~200KB of file content per call.
    const BATCH_BYTES = 200 * 1024;
    const batches = [];
    let current = [], currentBytes = 0;
    for (const f of filesData) {
      const size = Buffer.byteLength(f.content, 'utf8');
      if (current.length && currentBytes + size > BATCH_BYTES) {
        batches.push(current);
        current = []; currentBytes = 0;
      }
      current.push(f); currentBytes += size;
    }
    if (current.length) batches.push(current);

    const suspects = [];
    for (let b = 0; b < batches.length; b++) {
      const batch = batches[b];
      const prompt = `You are a rigorous, deep-think repository hygiene advisor.
Your objective is to evaluate the files below strictly against the project's North Star file to identify suspect files that fail North Star alignment or distract from the North Star.

North Star File: ${northStarFileName}
North Star Content:
"""
${northStarContent}
"""

Files (batch ${b + 1}/${batches.length} of the project):
${batch.map(f => `\n=========================================\nFILE: ${f.path}\n=========================================\n${f.content}`).join('\n')}

Identify files that distract from the North Star (e.g. obsolete, unused, duplicate, or dead materials). Do not just perform standard garbage collection of unused variables/imports, but look at entire files that do not serve the core objective.
For each suspect file, provide its filepath (as listed above, e.g. "bin/scanner.mjs") and a detailed reason explaining why it fails alignment or distracts from the North Star.`;

      const out = await agentFn(prompt, { schema, label: `hygiene-analysis-b${b + 1}` });
      // C9: a non-array reply is a FAILED analysis batch — LOUD, never a clean-looking
      // empty result (the silent-no-op failure mode this file shipped with).
      if (!Array.isArray(out)) {
        throw new Error(`analysis batch ${b + 1}/${batches.length} returned no parseable suspect list — the analysis did NOT run; refusing to report a clean project`);
      }
      suspects.push(...out);
    }

    const validatedSuspects = [];
    const resolvedProjectPath = path.resolve(projectPath);

    for (const suspect of suspects) {
      if (!suspect || typeof suspect.filepath !== 'string') continue;
      const resolvedPath = path.resolve(projectPath, suspect.filepath);
      try {
        const stat = await io.stat(resolvedPath);
        const relative = path.relative(resolvedProjectPath, resolvedPath);
        const isInside = !relative.startsWith('..') && !path.isAbsolute(relative);
        if (stat.isFile() && isInside) {
          validatedSuspects.push({
            filepath: resolvedPath,
            reason: suspect.reason || 'Failed North Star alignment.'
          });
        }
      } catch {
        // Filter out nonexistent or invalid files
      }
    }

    return validatedSuspects;
  } catch (error) {
    log(`Analysis failed for ${projectPath}:`, error.message);
    if (options.throwOnError) {
      throw error;
    }
    return [];
  }
}

async function main() {
  try {
    let target = process.argv[2];
    let projects = [];

    if (target) {
      const resolvedTarget = path.resolve(target);
      const northStarFile = await findNorthStarFile(resolvedTarget);
      if (northStarFile) {
        projects.push({ path: resolvedTarget, north_star_file: northStarFile });
      } else {
        console.error(`No North Star file found in project path: ${resolvedTarget}`);
        process.exit(1);
      }
    } else {
      // Wave-1 refactor-in-place (Wave-0 seam: shared-mutable-state): with no
      // target argument the target IS the current directory, and state is read
      // from THAT root's report dir — never from a CWD-relative location that
      // could belong to another run.
      const projectsJsonPath = path.join(reportDirFor(process.cwd()), 'projects.json');
      let exists = false;
      try {
        await fs.access(projectsJsonPath);
        exists = true;
      } catch {}

      if (exists) {
        const content = await fs.readFile(projectsJsonPath, 'utf8');
        projects = JSON.parse(content);
      } else {
        const resolvedCwd = process.cwd();
        const northStarFile = await findNorthStarFile(resolvedCwd);
        if (northStarFile) {
          projects.push({ path: resolvedCwd, north_star_file: northStarFile });
        }
      }
    }

    if (projects.length === 0) {
      console.log(JSON.stringify([], null, 2));
      return;
    }

    const allSuspects = [];
    for (const project of projects) {
      const suspects = await runAnalysis(project.path, {
        northStarFile: project.north_star_file,
      });
      allSuspects.push(...suspects);
    }

    const stateDir = reportDirFor(target ? path.resolve(target) : process.cwd());
    await fs.mkdir(stateDir, { recursive: true });
    const outputPath = path.join(stateDir, 'suspects_batch.json');
    await fs.writeFile(outputPath, JSON.stringify(allSuspects, null, 2), 'utf8');

    console.log(JSON.stringify(allSuspects, null, 2));
  } catch (error) {
    console.error('Gandalf Batch Analysis execution failed:', error.message);
    process.exit(1);
  }
}

const isDirectRun = process.argv[1] && (
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))
);

if (isDirectRun || process.argv[1]?.endsWith('analyze.mjs')) {
  main();
}
