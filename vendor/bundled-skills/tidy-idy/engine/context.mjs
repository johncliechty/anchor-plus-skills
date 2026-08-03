// engine/context.mjs — Wave 1: the run context every stage receives.
//
//   ctx = { rootPath, git: handle-or-null, mode: north-star|heuristic|advisory,
//           ruleset, reportDir, ... }
//
// This object replaces the Wave-0 inventory's SHARED MUTABLE STATE seam: five
// CLI main()s used to transport cross-stage state through a CWD-relative
// `.tidy-idy/` directory, so running the tool from a different directory made
// it read another run's state — or write outside the target root entirely.
// State location is now an EXPLICIT ctx member derived from the target root,
// and stages hand data to each other through the envelope, not through files.

import path from 'node:path';
import crypto from 'node:crypto';
import fsp from 'node:fs/promises';

import { reportDirFor } from './report-dir.mjs';
import { openGit } from './git.mjs';
import { loadConfig } from './config.mjs';
import { makeProtection } from './protection.mjs';
import { computeRulesetVersion, PROMPT_VERSION } from './ruleset.mjs';
import { createWriteAudit } from './write-audit.mjs';
import { resolveAgent } from './agent-seam.mjs';

export const MODES = Object.freeze({ NORTH_STAR: 'north-star', HEURISTIC: 'heuristic', ADVISORY: 'advisory' });

export const NORTH_STAR_FILES = Object.freeze(['NORTH-STAR.md', 'INTENT.md', 'SKILL.md']);

export { reportDirFor };

/** Locate a root's North-Star file, or null. Marker presence selects the MODE. */
export async function findNorthStar(rootPath, { fs = fsp } = {}) {
  for (const name of NORTH_STAR_FILES) {
    const p = path.join(rootPath, name);
    try {
      const st = await fs.stat(p);
      if (st.isFile()) return p;
    } catch { /* next candidate */ }
  }
  return null;
}

/**
 * Build the run context.
 *
 * Mode selection (the Wave-0 foundry-marker seam's fix): a missing North-Star
 * marker selects HEURISTIC mode — it does NOT make the folder invisible and it
 * does NOT throw. `advisory` is chosen explicitly by the caller (Wave 2 wires
 * the non-git preflight's declined-Bootstrap path to it).
 *
 * @param {{rootPath: string, mode?: string, agent?: Function, git?: object|null,
 *   reportDir?: string, hermetic?: boolean, runId?: string, log?: Function,
 *   execFile?: Function, env?: object, now?: Function}} opts
 */
export async function createContext(opts = {}) {
  const rootPath = path.resolve(opts.rootPath);
  const log = opts.log || (() => {});
  const now = opts.now || (() => new Date());
  const reportDir = opts.reportDir ? path.resolve(opts.reportDir) : reportDirFor(rootPath);

  // git: an explicit `null` from the caller means "run gitless" (the git:null
  // contract); `undefined` means "discover".
  const git = opts.git !== undefined ? opts.git : await openGit(rootPath, opts.execFile ? { execFile: opts.execFile } : {});

  // Config parse errors propagate — the pipeline turns them into a FAILED
  // stage. They are never swallowed into a silent default.
  const loaded = await loadConfig(rootPath, opts.readFile ? { readFile: opts.readFile } : {});
  const configPresent = loaded.present;
  const configPath = loaded.path;

  // Wave 5: the cost gate degrades a run by ADDING exclusions, and it decides
  // that before the pipeline starts. The overlay is how that decision reaches
  // the protection predicate WITHOUT the launcher rewriting the user's config
  // file or bypassing the parse-error contract above — it is applied after the
  // real config is parsed, and it is additive-only (see mergeConfigOverlay).
  const config = mergeConfigOverlay(loaded.config, opts.configOverlay);

  const protection = makeProtection(config);
  const northStarFile = await findNorthStar(rootPath);
  const mode = opts.mode || (northStarFile ? MODES.NORTH_STAR : MODES.HEURISTIC);
  if (!Object.values(MODES).includes(mode)) {
    throw new Error(`unknown run mode '${mode}' — expected one of ${Object.values(MODES).join('|')}`);
  }

  const ruleset = {
    version: computeRulesetVersion({
      protectedPatterns: protection.patterns,
      exclusionPatterns: protection.exclusions,
      promptVersion: PROMPT_VERSION,
    }),
    promptVersion: PROMPT_VERSION,
    protectedPatterns: protection.patterns,
    exclusionPatterns: protection.exclusions,
    configPresent,
    configPath,
  };

  const audit = createWriteAudit({
    rootPath,
    reportDir,
    ...(opts.baseFs ? { baseFs: opts.baseFs } : {}),
    ...(opts.execFile ? { baseExecFile: opts.execFile } : {}),
  });

  return {
    runId: opts.runId || `run-${now().toISOString().replace(/[:.]/g, '-')}-${crypto.randomBytes(4).toString('hex')}`,
    rootPath,
    git: git || null,
    mode,
    ruleset,
    reportDir,
    config,
    protection,
    northStarFile,
    /** Hermetic CI fixture: ANY sweep delta fails the build (see snapshot.mjs). */
    hermetic: Boolean(opts.hermetic),
    /** All stage fs access goes through this facade — Tier 1 of the tripwire. */
    audit,
    fs: audit.fs,
    execFile: audit.execFile,
    agent: resolveAgent({
      agent: opts.agent,
      driverPath: opts.driverPath || (config.run && config.run.driver) || null,
      model: opts.model || null,
      log,
      env: opts.env || process.env,
    }),
    log,
    now,
    /** Wave 5: the pre-scan cost-gate record, or null. Read-only for stages. */
    costGate: opts.costGate || null,
    /** Wave 5: the content-hash verdict cache, or null (LLM stages consult it). */
    verdictCache: opts.verdictCache || null,
    /** Wave 5: how this run was launched. Annotation; no stage branches on it. */
    launch: opts.launch || null,
    /** Scratch space for cross-stage handoff WITHIN one run (never a file). */
    state: {},
  };
}

/**
 * Merge a launcher-supplied overlay onto the parsed config. STRICTLY ADDITIVE by
 * construction: the only keys it can touch are the two LIST-valued ones, and it
 * can only concatenate onto them. There is no overlay that can remove a
 * protected pattern, which keeps the Wave-1 monotonicity property intact even
 * though the launcher can now influence the ruleset.
 */
export function mergeConfigOverlay(config = {}, overlay = null) {
  if (!overlay) return config;
  const merged = { ...config };
  for (const table of ['protect', 'exclude']) {
    const extra = overlay[table] && Array.isArray(overlay[table].patterns) ? overlay[table].patterns.map(String) : [];
    if (!extra.length) continue;
    const existing = (config[table] && config[table].patterns) || [];
    merged[table] = { ...(config[table] || {}), patterns: [...existing, ...extra] };
  }
  return merged;
}
