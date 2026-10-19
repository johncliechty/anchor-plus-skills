#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { reportDirFor } from '../engine/report-dir.mjs';
import { resolveAgent } from '../engine/agent-seam.mjs';
import { resolveTidyIdyKnobs } from '../engine/triage-knobs.mjs';

// B5 P1/P2: sole ceremony knobs path — debatePasses consumed live below.
export { resolveTidyIdyKnobs };

/**
 * Resolve adversarial pass count from live knobs (Track B5 P2).
 * Explicit options.debatePasses wins; else resolveTidyIdyKnobs → mapping;
 * no depth → 1 (legacy single attacker pass). Always ≥ 1; never skips Judge.
 *
 * LITE thins ceremony passes only (1 vs FULL 2). Judge + protect filtering
 * always still run — RETAIN/PROTECTED classes are never thinned by depth.
 *
 * @param {{ debatePasses?: unknown, triageDepth?: unknown, depth?: unknown, env?: object }} [options]
 * @returns {number}
 */
export function resolveDebatePasses(options = {}) {
  if (options.debatePasses != null && Number.isFinite(Number(options.debatePasses))) {
    return Math.max(1, Math.floor(Number(options.debatePasses)));
  }
  const knobs = resolveTidyIdyKnobs(options);
  if (!knobs) return 1;
  const n = /** @type {{ debatePasses?: unknown }} */ (knobs).debatePasses;
  if (n == null || !Number.isFinite(Number(n))) return 1;
  return Math.max(1, Math.floor(Number(n)));
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
 * Runs the debate engine (Attacker × debatePasses, then Judge) on suspect files.
 *
 * Adversarial pass count comes from resolveDebatePasses → resolveTidyIdyKnobs
 * (FULL=2, LITE/SPIKE-FIRST=1). Judge always runs after all attacker passes;
 * pre-LLM isAllowed / protect filtering is never skipped on LITE.
 *
 * @param {string} projectPath Absolute path to target project
 * @param {Array<{filepath: string, reason: string}>} suspects All suspect files
 * @param {object} options Override configurations (e.g. agent, model, log, chunkSize,
 *   triageDepth, debatePasses, env)
 * @returns {Promise<Array<{filepath: string, decision: "RETAIN" | "REMOVE", rationale: string,
 *   attacker: {case_for_removal: string|null, strength: string|null}|null}>>}
 */
export async function runDebate(projectPath, suspects, options = {}) {
  const log = options.log || (() => {});
  // Wave-1: the staged pipeline injects ctx.fs (the write-audit facade) so this
  // library's reads are audited like the stage wrapper's; the default keeps the
  // legacy CLI path unchanged.
  const io = options.fs || fs;
  // B5 P2: live debatePasses from mapping (or explicit options.debatePasses).
  const debatePasses = resolveDebatePasses(options);
  log(`debatePasses=${debatePasses} (live knobs / explicit; Judge always runs)`);

  // Wave-2: the debate has TWO scopes. 'alignment' is the original — does this
  // file serve the project's stated North Star? 'evidence-sufficiency' is what
  // heuristic mode needs: there IS no stated objective, so the only honest
  // question is whether age/duplicate/orphan/untracked evidence is strong enough
  // to justify removing a file nobody argued about. Re-scoping rather than
  // reusing the alignment prompt matters because the alignment prompt would
  // otherwise invite a model to invent an objective and judge against it.
  const scope = options.scope === 'evidence-sufficiency' ? 'evidence-sufficiency' : 'alignment';

  // Resolve North Star file. In evidence-sufficiency scope there is deliberately
  // none — a missing North Star is the DEFINING condition of heuristic mode, so
  // it must not be an exception there.
  const northStarFile = options.northStarFile || await findNorthStarFile(projectPath, io);
  if (!northStarFile && scope !== 'evidence-sufficiency') {
    throw new Error(`No North Star file found in project: ${projectPath}`);
  }
  const northStarContent = northStarFile ? await io.readFile(northStarFile, 'utf8') : null;
  const northStarFileName = northStarFile ? path.basename(northStarFile) : null;

  // Wave-2 pre-LLM gate: a secret-flagged path never reaches the debate at all,
  // so no excerpt of it can enter the attacker or judge prompt. The default
  // admits everything, keeping the legacy CLI path unchanged.
  const isAllowed = options.isAllowed || (() => true);

  // Filter suspects belonging to this project path
  const projectSuspects = suspects.filter(s => {
    const resolvedPath = path.resolve(s.filepath);
    const resolvedProject = path.resolve(projectPath);
    const relative = path.relative(resolvedProject, resolvedPath);
    if (relative.startsWith('..') || path.isAbsolute(relative)) return false;
    return isAllowed(resolvedPath);
  });

  if (projectSuspects.length === 0) {
    return [];
  }

  // C9 (2026-07-11): the DEFAULT model comes from the trio driver's catalogue — the
  // old hardcoded 'gemini-1.5-pro' was an id agy does not recognize (silent no-op runs).
  //
  // Wave-1 refactor-in-place (Wave-0 seam: hardcoded-path): the driver module is
  // resolved from the injected agent / config / env, never from an absolute
  // machine-local path baked into this file.
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

  // Chunking suspects (clamped between 5 and 10 to satisfy "max 5-10 files per batch")
  let chunkSize = options.chunkSize || 10;
  if (chunkSize < 5) chunkSize = 5;
  if (chunkSize > 10) chunkSize = 10;

  const chunks = [];
  for (let i = 0; i < projectSuspects.length; i += chunkSize) {
    chunks.push(projectSuspects.slice(i, i + chunkSize));
  }

  // C9 + B5 P2: Attacker × debatePasses (from live knobs) then ONE Judge per
  // chunk. Defender seat remains retired. Chunks run CONCURRENTLY under a
  // bounded pool (cap 3 — the agy host cap). Judge always runs; LITE thins
  // attacker pass count only (mapping: LITE=1, FULL=2).
  const judgments = [];
  const processChunk = async (chunk) => {
    // 1. Gather file contents for this batch
    const filesData = [];
    for (const suspect of chunk) {
      let content = '';
      try {
        content = await io.readFile(suspect.filepath, 'utf8');
        if (content.includes('\u0000')) {
          content = '(binary file)';
        } else if (content.length > 100 * 1024) {
          content = content.slice(0, 100 * 1024) + '\n... [TRUNCATED] ...';
        }
      } catch (err) {
        content = `(error reading file: ${err.message})`;
      }
      
      const relativePath = path.relative(projectPath, suspect.filepath).replace(/\\/g, '/');
      filesData.push({
        filepath: suspect.filepath,
        relativePath,
        reason: suspect.reason || 'Failed North Star alignment.',
        content
      });
    }

    const fileDetails = filesData.map(f => `
File: ${f.relativePath}
Reason for suspicion: ${f.reason}
Content:
"""
${f.content}
"""
`).join('\n=========================================\n');

    // 2. Adversarial Attacker passes × debatePasses (B5 P2 live knobs).
    // FULL=2, LITE/SPIKE-FIRST=1. Content redesign deferred — pass-count wiring only.
    // Label stays 'attacker-case' so hermetic counters equate pass count to calls.
    const attackerSchema = {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          filepath: { type: 'string' },
          case_for_removal: { type: 'string' },
          strength: { type: 'string', enum: ['strong', 'weak', 'none'] }
        },
        required: ['filepath', 'case_for_removal', 'strength']
      }
    };
    // The frame each persona argues inside. In alignment scope it is the North
    // Star; in evidence-sufficiency scope it is the explicit absence of one.
    const frame = scope === 'evidence-sufficiency'
      ? `This project has NO North Star document. Do not invent an objective for it and do not judge these files against one you imagine.
The ONLY question in scope is whether the RAW EVIDENCE attached to each file (its age, a byte-identical duplicate, zero references anywhere in the tree, git not holding it) is SUFFICIENT on its own to justify removing it.
Evidence that merely makes a file unusual is NOT sufficient. Absence of evidence is never evidence.`
      : `North Star File: ${northStarFileName}
North Star Content:
"""
${northStarContent}
"""`;

    let attackerCase = [];
    for (let pass = 1; pass <= debatePasses; pass++) {
      const priorBlock = pass > 1 && attackerCase.length
        ? `\nPrior adversarial pass (${pass - 1}/${debatePasses}) case — strengthen or revise honestly; do not invent evidence:\n${JSON.stringify(attackerCase, null, 2)}\n`
        : '';
      const attackerPrompt = `You are the Attacker persona, a ruthless repository hygiene enforcer.
Adversarial pass ${pass} of ${debatePasses}.
For EACH suspect file below, build the strongest honest case for removal (${scope === 'evidence-sufficiency'
        ? 'the attached evidence is strong enough to act on'
        : 'obsolete, duplicate, distracts from the North Star, unnecessary bloat'}) — or say the case is weak/none when it is.

${frame}
${priorBlock}
Below are the suspect files in the batch, including their reasons for suspicion and their file contents:
${fileDetails}

For each file emit: filepath (exactly as listed), case_for_removal, strength (strong | weak | none).`;

      try {
        const out = await agentFn(attackerPrompt, { schema: attackerSchema, label: 'attacker-case' });
        if (Array.isArray(out)) attackerCase = out;
        else log(`Attacker pass ${pass}/${debatePasses} output was not an array — keeping prior case / empty.`);
      } catch (err) {
        log(`Attacker pass ${pass}/${debatePasses} failed: ${err.message} — keeping prior case; Judge still runs.`);
      }
    }

    // 3. ALWAYS one structured Judge pass (never skipped on LITE). The Judge
    // reads FILE CONTENTS + the attacker's case; RETAIN is the fail-safe default.
    const judgePrompt = `You are the Judge persona, a neutral and objective arbitrator of repository hygiene.
Examine the actual file contents, the reasons for suspicion, and the Attacker's case, and decide whether each file should be RETAINED or REMOVED ${scope === 'evidence-sufficiency'
      ? 'based SOLELY on whether the attached raw evidence is sufficient to justify removal'
      : "based on its direct utility to the project's North Star"}. When in doubt, RETAIN.

${frame}

Below are the suspect files in the batch, including their reasons for suspicion and their file contents:
${fileDetails}

The Attacker's case per file:
${JSON.stringify(attackerCase, null, 2)}

For each suspect file, output filepath (EXACTLY as listed above), a decision of RETAIN or REMOVE, and a detailed rationale.`;

    const judgeSchema = {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          filepath: { type: 'string' },
          decision: { type: 'string', enum: ['RETAIN', 'REMOVE'] },
          rationale: { type: 'string' }
        },
        required: ['filepath', 'decision', 'rationale']
      }
    };

    let chunkJudgments = null;
    try {
      chunkJudgments = await agentFn(judgePrompt, { schema: judgeSchema, label: 'judge-decision' });
    } catch (err) {
      log('Judge agent call failed:', err.message);
    }

    // Schema Validation & Safe Defaulting
    let isValid = Array.isArray(chunkJudgments);
    if (isValid) {
      for (const item of chunkJudgments) {
        if (!item || typeof item.filepath !== 'string' || !['RETAIN', 'REMOVE'].includes(item.decision)) {
          isValid = false;
          break;
        }
      }
    }

    // The attacker's case, indexed by the exact relative path it named. The
    // Wave-6 panel renders it VERBATIM next to the judge's verdict, so it has to
    // survive this function rather than existing only inside the judge prompt —
    // a tile that showed a verdict without the case it answered would be asking
    // a human to ratify half an argument.
    const attackerByPath = new Map();
    for (const a of attackerCase) {
      if (a && typeof a.filepath === 'string') {
        attackerByPath.set(String(a.filepath).replace(/\\/g, '/'), {
          case_for_removal: a.case_for_removal ?? null,
          strength: a.strength ?? null,
        });
      }
    }
    const attackerFor = (suspect) =>
      attackerByPath.get(path.relative(projectPath, suspect.filepath).replace(/\\/g, '/')) || null;

    const chunkResults = [];
    if (!isValid) {
      log('Judge output violates schema or is unparseable. Hard-failing safely to RETAIN.');
      // Edge Case: Hard-fails safely to "RETAIN" if the API output violates the schema
      for (const suspect of chunk) {
        chunkResults.push({
          filepath: suspect.filepath,
          decision: 'RETAIN',
          rationale: 'Schema violation or Judge API call failed, defaulted to RETAIN.',
          attacker: attackerFor(suspect)
        });
      }
    } else {
      // Map decisions back to absolute filepaths — EXACT relative-path match ONLY
      // (C9: the old basename fallback could attach a REMOVE verdict on
      // old/util.mjs to src/util.mjs — wrong-file deletion territory).
      for (const suspect of chunk) {
        const suspectRel = path.relative(projectPath, suspect.filepath).replace(/\\/g, '/');
        const decisionObj = chunkJudgments.find(j =>
          String(j.filepath).replace(/\\/g, '/') === suspectRel);

        if (decisionObj) {
          chunkResults.push({
            filepath: suspect.filepath,
            decision: decisionObj.decision,
            rationale: decisionObj.rationale || 'Judge decision.',
            attacker: attackerFor(suspect)
          });
        } else {
          // If the judge missed this file (or named it inexactly), default to RETAIN.
          chunkResults.push({
            filepath: suspect.filepath,
            decision: 'RETAIN',
            rationale: 'Judge did not return an exact-path decision for this file, defaulted to RETAIN.',
            attacker: attackerFor(suspect)
          });
        }
      }
    }
    return chunkResults;
  };

  // Bounded concurrent chunk processing (cap 3 — the agy host cap); output order
  // stays chunk order regardless of completion order.
  const cap = Math.max(1, Math.min(3, options.chunkConcurrency || 3));
  const queue = chunks.map((chunk, i) => ({ chunk, i }));
  const byIndex = new Map();
  await Promise.all(Array.from({ length: Math.min(cap, queue.length) }, async () => {
    while (queue.length) {
      const { chunk, i } = queue.shift();
      byIndex.set(i, await processChunk(chunk));
    }
  }));
  for (let i = 0; i < chunks.length; i++) judgments.push(...(byIndex.get(i) || []));

  return judgments;
}

async function main() {
  try {
    let target = process.argv[2];
    let projects = [];

    // Locate target projects similar to analyze.mjs
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
      // Wave-1 refactor-in-place (Wave-0 seam: shared-mutable-state) — state is
      // derived from the target root (the CWD when no target is given), never
      // from a CWD-relative location shared with unrelated runs.
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

    // Read suspects_batch.json from the TARGET's state directory
    const stateDir = reportDirFor(target ? path.resolve(target) : process.cwd());
    const suspectsJsonPath = path.join(stateDir, 'suspects_batch.json');
    let suspects = [];
    try {
      const content = await fs.readFile(suspectsJsonPath, 'utf8');
      suspects = JSON.parse(content);
    } catch {
      // If it doesn't exist, we assume no suspects and output empty judgments
    }

    const allJudgments = [];
    for (const project of projects) {
      const projectJudgments = await runDebate(project.path, suspects, {
        northStarFile: project.north_star_file,
      });
      allJudgments.push(...projectJudgments);
    }

    await fs.mkdir(stateDir, { recursive: true });
    const outputPath = path.join(stateDir, 'judgments.json');
    await fs.writeFile(outputPath, JSON.stringify(allJudgments, null, 2), 'utf8');

    console.log(JSON.stringify(allJudgments, null, 2));
  } catch (error) {
    console.error('Debate Engine execution failed:', error.message);
    process.exit(1);
  }
}

const isDirectRun = process.argv[1] && (
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))
);

if (isDirectRun || process.argv[1]?.endsWith('debate.mjs')) {
  main();
}
