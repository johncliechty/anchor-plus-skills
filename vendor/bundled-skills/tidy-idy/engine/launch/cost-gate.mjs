// engine/launch/cost-gate.mjs — Wave 5: the pre-scan cost gate, owned by the TOOL.
//
// THE CONCRETE FAILURE THIS PREVENTS (carried finding, round 1). One click on a
// 300k-file monorepo whose node_modules was never pruned. A gate that asks
// "proceed / narrow / heuristic-only?" INSIDE the run has two outcomes there,
// both bad: the headless run blocks forever on an answer nobody is present to
// give, or — if the block is skipped — the LLM stages burn unbounded spend on a
// tree the user never meant to send.
//
// So the rule is absolute and is stated in the record itself: THE GATE NEVER
// BLOCKS A HEADLESS RUN. `blocked` is a field, and it is always false.
//
// Above threshold the run DEGRADES, in a fixed ladder, and records every rung:
//
//   rung 1  generic exclusions — the default regenerable/large-artifact set is
//           applied on top of the built-ins, and the tree is re-counted.
//   rung 2  heuristic-only narrowing — if the tree is STILL over threshold, the
//           LLM stages are narrowed out of the run (mode=heuristic: the debate
//           re-scopes to evidence sufficiency and no content is batched to a
//           model), so the excess costs walk time, not tokens.
//
// The run then COMPLETES, the degradation lands in the envelope, and the panel
// renders a 'cost-gated — full run needs confirmation' banner with ONE click
// that re-runs at full scope. The interactive proceed/narrow decision exists
// there, where a human is, and nowhere else.
//
// The count is a METADATA walk: readdir + stat, no file content, no hashing. It
// is a second enumeration (the topology check owns the authoritative one) purely
// because its answer DECIDES the exclusion set the topology check will use.

import fsp from 'node:fs/promises';
import path from 'node:path';

import { toPosixRel, firstMatch } from '../glob.mjs';

/** Above either of these, the run degrades. Overridable per project. */
export const DEFAULT_THRESHOLDS = Object.freeze({
  maxFiles: 20000,
  maxBytes: 2 * 1024 * 1024 * 1024,
});

/** Hard ceiling on the counting walk itself, so the GATE can never be the hang. */
export const COUNT_CAP = 400000;

/**
 * The generic exclusion set applied at rung 1. Every entry names content that is
 * REGENERABLE or is not source: no judgement about the user's project is encoded
 * here beyond "a hygiene verdict about a build artifact is not worth an LLM
 * call". `.tidy-idy.toml`'s `[cost] exclude_patterns` extends this list.
 */
export const GENERIC_EXCLUSIONS = Object.freeze([
  'vendor/**', '**/vendor/**',
  'third_party/**', '**/third_party/**',
  '.cache/**', '**/.cache/**',
  '.gradle/**', '**/.gradle/**',
  '.terraform/**', '**/.terraform/**',
  '.mypy_cache/**', '**/.mypy_cache/**',
  '.pytest_cache/**', '**/.pytest_cache/**',
  '.tox/**', '**/.tox/**',
  'coverage/**', '**/coverage/**',
  'Pods/**', '**/Pods/**',
  'out/**', '**/out/**',
  'obj/**', '**/obj/**',
  '*.min.js', '*.map',
  '*.zip', '*.tar', '*.tar.gz', '*.tgz', '*.7z', '*.rar', '*.jar', '*.war',
  '*.png', '*.jpg', '*.jpeg', '*.gif', '*.webp', '*.ico', '*.svg',
  '*.mp4', '*.mov', '*.mp3', '*.wav', '*.avi', '*.mkv',
  '*.pdf', '*.psd', '*.ai', '*.sketch',
  '*.iso', '*.dmg', '*.exe', '*.dll', '*.so', '*.dylib', '*.pdb',
  '*.log',
]);

/** Read the `[cost]` table, with the defaults as the floor. */
export function costConfig(config = {}) {
  const c = (config && config.cost) || {};
  return {
    enabled: c.enabled === undefined ? true : Boolean(c.enabled),
    maxFiles: Number.isInteger(c.max_files) ? c.max_files : DEFAULT_THRESHOLDS.maxFiles,
    maxBytes: Number.isInteger(c.max_bytes) ? c.max_bytes : DEFAULT_THRESHOLDS.maxBytes,
    excludePatterns: Array.isArray(c.exclude_patterns) ? c.exclude_patterns.map(String) : [],
  };
}

/**
 * Count in-scope files and bytes cheaply.
 *
 * @param {{rootPath: string, isExcluded?: Function, fs?: object, cap?: number, reportDir?: string|null}} opts
 * @returns {Promise<{files: number, bytes: number, truncated: boolean, unreadableDirs: number}>}
 */
export async function countTree({ rootPath, isExcluded = () => false, fs = fsp, cap = COUNT_CAP, reportDir = null } = {}) {
  const root = path.resolve(rootPath);
  const reportAbs = reportDir ? path.resolve(reportDir) : null;
  let files = 0;
  let bytes = 0;
  let unreadableDirs = 0;
  let truncated = false;

  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    let entries;
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch {
      unreadableDirs++;
      continue;
    }
    for (const entry of entries) {
      if (files >= cap) { truncated = true; return { files, bytes, truncated, unreadableDirs }; }
      const abs = path.join(dir, entry.name);
      const rel = toPosixRel(path.relative(root, abs));
      if (!rel) continue;
      if (reportAbs && (abs === reportAbs || abs.startsWith(reportAbs + path.sep))) continue;
      // Never follow a link while counting — the topology check is the one place
      // link semantics are decided, and a counting walk that followed one could
      // count (and cost-gate on) a tree outside the root.
      if (entry.isSymbolicLink()) continue;
      if (isExcluded(rel)) continue;
      if (entry.isDirectory()) { stack.push(abs); continue; }
      if (!entry.isFile()) continue;
      files++;
      try {
        const st = await fs.stat(abs);
        bytes += st.size;
      } catch { /* a file that vanished mid-count contributes no bytes */ }
    }
  }
  return { files, bytes, truncated, unreadableDirs };
}

/**
 * Evaluate the gate for a run. NEVER returns a blocking decision.
 *
 * @param {{rootPath: string, config?: object, protection: object, reportDir?: string|null,
 *          fs?: object, mode?: string|null}} opts
 * @returns {Promise<object>} the cost-gate record, persisted verbatim in the envelope
 */
export async function evaluateCostGate({ rootPath, config = {}, protection, reportDir = null, fs = fsp, mode = null } = {}) {
  const cfg = costConfig(config);
  const baseExcluded = (rel) => protection.isExcluded(rel);

  if (!cfg.enabled) {
    return {
      ran: false,
      blocked: false,
      gated: false,
      thresholds: { maxFiles: cfg.maxFiles, maxBytes: cfg.maxBytes },
      note: '[cost] enabled = false in .tidy-idy.toml — the gate did not run and the full scope was used',
      degradation: emptyDegradation(),
      banner: null,
      confirmFullRun: null,
    };
  }

  const initial = await countTree({ rootPath, isExcluded: baseExcluded, fs, reportDir });
  const over = (c) => c.files > cfg.maxFiles || c.bytes > cfg.maxBytes || c.truncated;

  if (!over(initial)) {
    return {
      ran: true,
      blocked: false,
      gated: false,
      thresholds: { maxFiles: cfg.maxFiles, maxBytes: cfg.maxBytes },
      initial,
      final: initial,
      degradation: emptyDegradation(),
      banner: null,
      confirmFullRun: null,
      note: `${initial.files} file(s) / ${initial.bytes} byte(s) in scope — under threshold, full scope used`,
    };
  }

  // ---- rung 1: generic exclusions ----------------------------------------
  const applied = [...GENERIC_EXCLUSIONS, ...cfg.excludePatterns];
  const withGeneric = (rel) => baseExcluded(rel) || firstMatch(applied, rel) !== null;
  const afterExclusions = await countTree({ rootPath, isExcluded: withGeneric, fs, reportDir });

  const steps = [{
    rung: 1,
    step: 'generic-exclusions',
    applied,
    before: initial,
    after: afterExclusions,
    why: 'regenerable/large-artifact classes excluded so the excess costs no tokens',
  }];

  // ---- rung 2: heuristic-only narrowing over the excess --------------------
  let heuristicOnly = false;
  if (over(afterExclusions)) {
    heuristicOnly = true;
    steps.push({
      rung: 2,
      step: 'heuristic-only',
      before: afterExclusions,
      after: afterExclusions,
      why: 'still over threshold after the generic exclusions — the LLM stages are narrowed out of this run (mode=heuristic: candidates come from raw file evidence and the debate re-scopes to evidence sufficiency), so no content is batched to a model',
    });
  }

  return {
    ran: true,
    /** STATED, not implied: this gate has no code path that blocks a run. */
    blocked: false,
    gated: true,
    thresholds: { maxFiles: cfg.maxFiles, maxBytes: cfg.maxBytes },
    initial,
    final: afterExclusions,
    degradation: {
      applied: true,
      steps,
      exclusionsApplied: applied,
      heuristicOnly,
      /** The mode the launcher must run with, or null for "unchanged". */
      forcedMode: heuristicOnly ? 'heuristic' : null,
      requestedMode: mode,
    },
    banner: {
      kind: 'cost-gated',
      severity: 'warn',
      title: 'cost-gated — full run needs confirmation',
      message:
        `${initial.files} file(s) / ${initial.bytes} byte(s) exceeded this project's cost threshold `
        + `(${cfg.maxFiles} files / ${cfg.maxBytes} bytes). The run COMPLETED in auto-degraded scope: `
        + `${applied.length} generic exclusion pattern(s) applied`
        + (heuristicOnly ? ', and the LLM stages were narrowed to heuristic-only over the excess' : '')
        + `. ${afterExclusions.files} file(s) were actually analysed.`,
      action: 'confirm-full-run',
    },
    confirmFullRun: {
      action: 'confirm-full-run',
      rootPath: path.resolve(rootPath),
      /** What a confirmed re-run overrides. One click, no free-text decision. */
      overrides: { costGate: { enabled: false } },
      note: 'the interactive proceed/narrow choice lives HERE, in the panel, where a human is — never inside the headless run',
    },
    note:
      'the cost gate degraded this run rather than blocking it; every exclusion and narrowing applied is recorded above',
  };
}

function emptyDegradation() {
  return { applied: false, steps: [], exclusionsApplied: [], heuristicOnly: false, forcedMode: null };
}

export default { evaluateCostGate, countTree, costConfig, GENERIC_EXCLUSIONS, DEFAULT_THRESHOLDS, COUNT_CAP };
