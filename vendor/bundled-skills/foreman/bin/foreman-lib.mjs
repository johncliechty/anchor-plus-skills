// foreman-lib.mjs — Phase 0 parsers + state primitives for Foreman.
//
// Scope (Phase 0 only, per Foreman-Implementation-Plan-FINAL.md §11):
//   - document location (§4.2)            -> locateDocs()
//   - wave parsing  `## Wave N`  (§4.3)   -> parseWaves()
//   - test-command discovery     (§4.4)   -> discoverTestCommand()
//   - project-DONE definition    (§4.5)   -> projectDoneDefinition()
//   - checkpoint schema + atomic IO (§8)  -> writeCheckpointAtomic() / readCheckpoint()
//   - running-commentary line    (§10)    -> renderDashboard()
//
// This file contains NO orchestration engine (no execute/review/fix loop, no
// Workflow agent() calls). That is Phase 1+. Everything here is a pure parser
// or a deterministic file primitive so its behavior is verifiable from a
// single command's real output.
//
// Convention used by the CLIs that import this lib:
//   - A recoverable refusal/HALT is signaled by throwing `new HaltError(reason)`.
//   - "Never guess" (§4) is enforced by treating BOTH missing and ambiguous
//     inputs as HALTs — Foreman refuses rather than picking one.

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

/** A recoverable HALT-for-human (§6). CLIs map this to exit code 3. */
export class HaltError extends Error {
  constructor(reason, detail) {
    super(reason);
    this.name = 'HaltError';
    this.reason = reason;
    this.detail = detail ?? null;
  }
}

// ---------------------------------------------------------------------------
// §4.2  Document location — find description / plan / execution-log; refuse
//        (HALT) on missing OR ambiguous. Never guess.
// ---------------------------------------------------------------------------

// Filename heuristics (case-insensitive, matched against the basename).
const DOC_PATTERNS = {
  description: [/description/i, /\bdesign\b/i, /\bspec\b/i, /\bprd\b/i],
  plan:        [/implementation[-_ ]?plan/i, /\bplan\b/i],
  execution_log: [/execution[-_ ]?log/i, /exec[-_ ]?log/i],
};

const DOC_LABELS = {
  description: 'description / design doc',
  plan: 'implementation plan',
  execution_log: 'execution log',
};

/**
 * Locate the three frozen docs in `projectDir`.
 *
 * Resolution order (no guessing):
 *   1. If `foreman.config.json` exists and names a doc, that explicit path wins.
 *   2. Otherwise glob *.md basenames against DOC_PATTERNS.
 *      - 0 candidates for a required role  -> HALT (missing).
 *      - >1 candidate for a role           -> HALT (ambiguous; ask, don't pick).
 *
 * @returns {{description:string, plan:string, execution_log:string, source:'config'|'heuristic'}}
 */
export function locateDocs(projectDir) {
  const dir = path.resolve(projectDir);
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) {
    throw new HaltError('project folder not found', dir);
  }

  // 1. explicit config
  const cfgPath = path.join(dir, 'foreman.config.json');
  let cfgDocs = null;
  if (fs.existsSync(cfgPath)) {
    let cfg;
    try {
      cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    } catch (e) {
      throw new HaltError('foreman.config.json is not valid JSON', e.message);
    }
    cfgDocs = cfg.docs ?? null;
  }

  const result = { description: null, plan: null, execution_log: null, source: 'heuristic' };

  if (cfgDocs) {
    result.source = 'config';
    for (const role of Object.keys(DOC_LABELS)) {
      const rel = cfgDocs[role];
      if (!rel) {
        throw new HaltError(`config does not name the ${DOC_LABELS[role]}`, cfgPath);
      }
      const abs = path.resolve(dir, rel);
      if (!fs.existsSync(abs)) {
        throw new HaltError(`config-named ${DOC_LABELS[role]} does not exist`, abs);
      }
      result[role] = abs;
    }
    return result;
  }

  // 2. heuristic glob over top-level *.md
  const mdFiles = fs.readdirSync(dir)
    .filter((f) => f.toLowerCase().endsWith('.md'))
    .map((f) => ({ name: f, abs: path.join(dir, f) }));

  for (const role of Object.keys(DOC_PATTERNS)) {
    const pats = DOC_PATTERNS[role];
    const hits = mdFiles.filter((f) => pats.some((p) => p.test(f.name)));
    if (hits.length === 0) {
      throw new HaltError(
        `cannot locate the ${DOC_LABELS[role]} in this project`,
        `searched ${mdFiles.length} *.md file(s) in ${dir}; add it or name it in foreman.config.json`,
      );
    }
    if (hits.length > 1) {
      throw new HaltError(
        `ambiguous ${DOC_LABELS[role]}: ${hits.length} candidates`,
        `candidates: ${hits.map((h) => h.name).join(', ')} — name the right one in foreman.config.json (Foreman never guesses)`,
      );
    }
    result[role] = hits[0].abs;
  }

  // Finding J (Phase 1): the role patterns overlap (e.g. `design-plan.md` matches
  // BOTH description via /design/ AND plan via /\bplan\b/). If a single file is
  // resolved into two roles, Foreman cannot tell which role the author meant —
  // binding it to both is a silent guess. Per §4 "never guess", HALT and ask.
  const byPath = {};
  for (const role of Object.keys(DOC_PATTERNS)) {
    const abs = result[role];
    (byPath[abs] = byPath[abs] || []).push(role);
  }
  for (const [abs, roles] of Object.entries(byPath)) {
    if (roles.length > 1) {
      throw new HaltError(
        `document binds to two roles (${roles.map((r) => DOC_LABELS[r]).join(' and ')})`,
        `${path.basename(abs)} matches the ${roles.map((r) => DOC_LABELS[r]).join(' and ')} patterns — ` +
          `Foreman cannot tell which it is; name each doc explicitly in foreman.config.json (Foreman never guesses)`,
      );
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// §4.3  Wave parsing — `## Wave N` (sprint/section accepted as aliases).
//        HALT if the plan has no parseable wave structure.
// ---------------------------------------------------------------------------

// One line, level-2 heading, "Wave"/"Sprint"/"Section" + integer, optional
// title after a separator. Examples that match:
//   ## Wave 1 — Bootstrap
//   ## Wave 2: MoE judge wiring
//   ## Sprint 3 Foo
const WAVE_RE = /^##\s+(Wave|Sprint|Section)\s+(\d+)\b[ \t]*[—:\-.]?[ \t]*(.*)$/i;

/**
 * Parse waves from plan markdown text.
 * @returns {Array<{n:number, title:string, kind:string, line:number}>}
 * @throws HaltError if zero waves found, or wave numbers are not 1..N contiguous.
 */
export function parseWaves(planText) {
  const lines = planText.split(/\r?\n/);
  const waves = [];
  let inFence = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) { inFence = !inFence; continue; }
    if (inFence) continue; // ignore headings inside code fences
    const m = WAVE_RE.exec(line);
    if (m) {
      waves.push({
        kind: m[1].toLowerCase(),
        n: Number(m[2]),
        title: (m[3] || '').trim(),
        line: i + 1,
      });
    }
  }

  if (waves.length === 0) {
    throw new HaltError(
      'plan has no parseable wave structure',
      'expected at least one `## Wave N` (or `## Sprint N` / `## Section N`) heading — add one; Foreman never infers wave boundaries (§4.3)',
    );
  }

  // Numbers must be unique and contiguous 1..N so iteration order is unambiguous.
  const nums = waves.map((w) => w.n);
  const sorted = [...nums].sort((a, b) => a - b);
  const expected = sorted.map((_, idx) => idx + 1);
  const contiguous = sorted.length === expected.length &&
    sorted.every((v, idx) => v === expected[idx]);
  if (!contiguous) {
    throw new HaltError(
      'wave numbers are not contiguous 1..N',
      `found wave numbers [${nums.join(', ')}] — fix the plan numbering; Foreman will not reorder or fill gaps`,
    );
  }

  // Finding I (Phase 0.5): the *set* is now known to be exactly {1..N}, but the
  // engine iterates the array in its *declared* order. A non-ascending
  // declaration (e.g. `## Wave 2` above `## Wave 1`) would otherwise be returned
  // as [2,1] and silently run out of intended order. Foreman must not guess the
  // author's intent: §4.3 already states it "will not reorder or fill gaps" and
  // §4 says "never guess". So HALT on a non-ascending declaration rather than
  // silently sorting (which would invent an order the author may not have meant).
  const ascending = nums.every((v, idx) => idx === 0 || v > nums[idx - 1]);
  if (!ascending) {
    throw new HaltError(
      'waves are not declared in ascending order',
      `wave numbers appear as [${nums.join(', ')}] in the plan — reorder the headings so they read 1..N top-to-bottom; Foreman will not reorder them for you (§4.3)`,
    );
  }

  // Declared order is validated as a strictly-ascending, contiguous 1..N run.
  // Per-wave optional gate-command (0082 P1.6): scan body until next wave heading.
  for (let wi = 0; wi < waves.length; wi++) {
    const start = waves[wi].line; // 1-based
    const end = wi + 1 < waves.length ? waves[wi + 1].line : lines.length + 1;
    for (let li = start; li < end - 1 && li < lines.length; li++) {
      const body = lines[li];
      const gm = body.match(/^\s*(?:wave[-_ ]?)?gate[-_ ]?command\s*[:=]\s*(.+)$/i);
      if (gm) {
        const cmd = gm[1].replace(/^`+|`+$/g, '').trim();
        if (cmd) waves[wi].gateCommand = cmd;
      }
    }
  }
  return waves;
}

/**
 * Doctor: prove the gate command collects/runs >0 tests before wave 1 (0082 P2.13).
 * Best-effort; returns { ok, tests, note, command }.
 */
export function doctorTestCommand(command, projectDir = process.cwd()) {
  const cmd = String(command || '').trim();
  if (!cmd) return { ok: false, tests: 0, note: 'empty test command', command: cmd };
  let probe = cmd;
  // pytest: --collect-only is cheap and counts without running bodies.
  if (/(^|[\s/\\])(python(?:\d(?:\.\d+)?)?\s+-m\s+pytest|pytest|py\.test)(?=\s|$)/i.test(cmd)) {
    if (!/--collect-only\b/.test(cmd)) probe = `${cmd} --collect-only -q`;
  }
  try {
    // Strip NODE_TEST_CONTEXT so a doctor run nested under `node --test` does
    // not inherit "skip files" (same false-green class as runGate).
    const env = { ...process.env };
    delete env.NODE_TEST_CONTEXT;
    const r = spawnSync(probe, {
      cwd: projectDir, shell: true, windowsHide: true, encoding: 'utf8',
      timeout: 120_000, maxBuffer: 16 * 1024 * 1024,
      env,
    });
    const out = `${r.stdout || ''}\n${r.stderr || ''}`;
    // pytest: "N tests collected" or node --test pass counts
    let n = 0;
    const m1 = out.match(/(\d+)\s+tests?\s+collected/i);
    const m2 = out.match(/#\s*tests\s+(\d+)/i);
    const m3 = out.match(/(\d+)\s+passed/i);
    const m4 = out.match(/#\s*pass\s+(\d+)/i);
    // node --test summary: "ℹ tests 1" or plain "tests 1" (unicode info glyph varies)
    const m5 = out.match(/(?:^|\n)\s*(?:ℹ|i)?\s*tests\s+(\d+)/im);
    const m6 = out.match(/(?:^|\n)\s*(?:ℹ|i)?\s*pass\s+(\d+)/im);
    if (m1) n = Number(m1[1]);
    else if (m2) n = Number(m2[1]);
    else if (m4) n = Number(m4[1]);
    else if (m5) n = Number(m5[1]);
    else if (m6 && Number(m6[1]) > 0) n = Number(m6[1]);
    else if (m3) n = Number(m3[1]);
    if (n > 0) return { ok: true, tests: n, note: 'collected/ran tests', command: cmd };
    if (r.status === 0) {
      // node --test TAP: lines like "ok 1 - name" or "# pass 1"
      const okLines = (out.match(/^\s*ok\s+\d+/gim) || []).length;
      if (okLines > 0) return { ok: true, tests: okLines, note: 'TAP ok events observed', command: cmd };
      if (/#\s*pass\s+[1-9]/i.test(out)) {
        return { ok: true, tests: 1, note: 'pass summary observed', command: cmd };
      }
      // Spec reporter checkmarks
      const checks = (out.match(/✔/g) || []).length;
      if (checks > 0) return { ok: true, tests: checks, note: 'spec pass marks observed', command: cmd };
    }
    return {
      ok: false,
      tests: n,
      note: `gate collected 0 tests (exit ${r.status}). Fix test-command before wave 1.`,
      command: cmd,
    };
  } catch (e) {
    return { ok: false, tests: 0, note: `doctor spawn failed: ${e.message}`, command: cmd };
  }
}

// ---------------------------------------------------------------------------
// §4.4  Test-command discovery — from the plan first, else the manifest.
//        HALT if no ground-truth test command can be found.
// ---------------------------------------------------------------------------

// T3 (2026-07-11): a pytest gate only earns GREEN through real per-test events
// (wave-engine countTestEvents), which pytest emits ONLY under -v/--verbose. A
// bare `pytest` or `pytest -q` gate is therefore a command the engine can NEVER
// pass — every such run ends in a vacuous refusal AFTER paying the execute call
// (observed live: manifest-discovered `pytest`, and a plan-declared `-q` that
// dead-stopped a genuine RED). Normalize at CONTRACT time instead:
//   - bare pytest       -> `-v` inserted after the pytest token (verbosity only,
//                          semantics unchanged; safe in chained commands).
//   - -q/--quiet        -> HALT with the exact edit to make (stripping a flag the
//                          plan explicitly declares would be guessing — §4 "never
//                          guess"; the author confirms by editing the plan).
//   - already -v        -> untouched. Non-pytest commands -> untouched.
const PYTEST_TOKEN_RE = /(^|[\s/\\])(python(?:\d(?:\.\d+)?)?\s+-m\s+pytest|pytest|py\.test)(?=\s|$)/;

export function normalizePytestGate(command, source) {
  const cmd = String(command).trim();
  const m = cmd.match(PYTEST_TOKEN_RE);
  if (!m) return { command: cmd, source };
  if (/(^|\s)(-q|--quiet)\b/.test(cmd)) {
    throw new HaltError(
      'pytest gate uses -q/--quiet — a gate the engine can NEVER pass as written',
      `test command "${cmd}" (${source}) suppresses per-test events, but GREEN requires them ` +
        `(§5 anti-forgery: a summary line alone is refusable). Change the declaration to use ` +
        `\`-v\` (e.g. \`pytest -v\`) and re-run. Halting NOW, before any execute call is spent.`,
    );
  }
  if (/(^|\s)(-v+|--verbose)\b/.test(cmd)) return { command: cmd, source };
  const insertAt = m.index + m[0].length;
  return {
    command: cmd.slice(0, insertAt) + ' -v' + cmd.slice(insertAt),
    source: `${source} (normalized: -v inserted — GREEN requires per-test events)`,
  };
}

/**
 * Discover the build+test command.
 * @param {string} planText  contents of the plan doc
 * @param {string} projectDir
 * @returns {{command:string, source:string}}
 * @throws HaltError when nothing authoritative is found.
 */
export function discoverTestCommand(planText, projectDir) {
  // 1. explicit declaration in the plan, e.g. a line:
  //      test-command: pytest -q
  //      Test command: `npm test`
  const planLine = planText.split(/\r?\n/).find((l) =>
    /^\s*(test[-_ ]?command|build[-_ ]?and[-_ ]?test|gate[-_ ]?command)\s*[:=]/i.test(l));
  if (planLine) {
    const raw = planLine.replace(/^\s*[^:=]+[:=]\s*/, '').trim();
    const cmd = raw.replace(/^`+|`+$/g, '').trim();
    if (cmd) return normalizePytestGate(cmd, 'plan declaration');
  }

  // 2. project manifest
  const dir = path.resolve(projectDir);
  const pkgPath = path.join(dir, 'package.json');
  if (fs.existsSync(pkgPath)) {
    let pkg;
    try {
      pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
    } catch (e) {
      throw new HaltError('package.json is not valid JSON', e.message);
    }
    if (pkg.scripts && typeof pkg.scripts.test === 'string' && pkg.scripts.test.trim()) {
      return { command: 'npm test', source: 'package.json scripts.test' };
    }
  }

  const pyproject = path.join(dir, 'pyproject.toml');
  if (fs.existsSync(pyproject)) {
    const txt = fs.readFileSync(pyproject, 'utf8');
    if (/\[tool\.pytest/.test(txt) || /pytest/.test(txt)) {
      // -v is REQUIRED (not cosmetic): GREEN needs per-test events (see
      // normalizePytestGate). A bare `pytest` gate self-sabotages every run.
      return { command: 'pytest -v', source: 'pyproject.toml (pytest configured)' };
    }
  }

  throw new HaltError(
    'no ground-truth test command found',
    'no `test-command:` in the plan and no recognizable test script in the manifest — cannot gate (§4.4: "no ground truth → cannot gate"). Declare one in the plan or add a test script.',
  );
}

// ---------------------------------------------------------------------------
// Gate honesty preflight (cf-slick 2026-07-22 — journals 0038/0039/0047/0049)
// ---------------------------------------------------------------------------

/**
 * True when the gate string is the known-bad Win Node v26 form that treats
 * `test/` as a single module path instead of a recursive suite.
 * @param {string} command
 */
export function isBadNodeTestDirectoryCommand(command) {
  const c = String(command || '').trim();
  // node --test test/  OR  node --test test  OR  node --test "./test/"
  return /^node\s+--test\s+["']?\.?\/?test\/?["']?\s*$/i.test(c);
}

/**
 * Preflight the discovered gate command. Does not invent a command — only
 * refuses known-broken forms so FIX does not invent illegal test harnesses.
 *
 * @param {{command:string, source?:string}} discovered  from discoverTestCommand
 * @param {string} [projectDir]
 * @returns {{command:string, source:string, warnings:string[]}}
 * @throws HaltError on hard-refuse cases
 */
export function preflightTestCommand(discovered, projectDir = '') {
  const command = discovered?.command || '';
  const source = discovered?.source || 'unknown';
  const warnings = [];

  if (isBadNodeTestDirectoryCommand(command)) {
    throw new HaltError(
      'gate command is known-broken on this host',
      `\`node --test test/\` fails on Windows Node v26 (MODULE_NOT_FOUND / non-recursive). ` +
        `Prefer test-command: node scripts/run-all-tests.mjs (lists test/*.test.mjs) ` +
        `or explicit files, e.g. node --test test/foo.test.mjs test/bar.test.mjs ` +
        `(journals foreman 0038, 0039, 0047, 0076). Source was: ${source}`,
    );
  }

  // Under-gating check (journal 0049): package suite larger than plan gate → HALT.
  // Do not swallow HaltError in the catch (Shark: empty catch was hiding the guard).
  try {
    const dir = path.resolve(projectDir || '.');
    const pkgPath = path.join(dir, 'package.json');
    if (fs.existsSync(pkgPath) && source === 'plan declaration') {
      const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
      const scr = pkg?.scripts?.test || '';
      if (typeof scr === 'string' && scr.includes('--test') && command.includes('--test')) {
        const planFiles = (command.match(/[\w./\\-]+\.test\.\w+/g) || []).length;
        const pkgFiles = (scr.match(/[\w./\\-]+\.test\.\w+/g) || []).length;
        if (pkgFiles > planFiles && planFiles > 0) {
          throw new HaltError(
            'plan gate under-gates the package test suite',
            `package.json scripts.test names ${pkgFiles} test file(s) but plan test-command names ${planFiles} ` +
              `(journal 0049). Expand plan test-command to the full suite or shrink package scripts.test — ` +
              `refusing to risk PROJECT DONE on a narrow frozen gate.`,
          );
        }
      }
    }
  } catch (e) {
    if (e instanceof HaltError) throw e;
    // best-effort only for I/O/parse noise
  }

  // Dual-root / outside-tree test imports (journal 0048): if project tests import
  // source outside projectDir, vacuous-GREEN will never see deliverables.
  try {
    const dual = preflightDualRootImports(projectDir, command);
    if (dual.outside.length) {
      throw new HaltError(
        'tests import sources outside the Foreman project root',
        `projectDir=${path.resolve(projectDir || '.')} · outside imports: ${dual.outside.slice(0, 8).join('; ')}` +
          (dual.outside.length > 8 ? ` (+${dual.outside.length - 8} more)` : '') +
          `. Point projectDir at the package that owns the code (journal 0048), or keep tests inside the root.`,
      );
    }
  } catch (e) {
    if (e instanceof HaltError) throw e;
  }

  return { command, source, warnings };
}

/**
 * Scan project test files for relative imports that resolve outside projectDir.
 * @returns {{checked:number, outside:string[]}}
 */
export function preflightDualRootImports(projectDir, testCommand = '') {
  const root = path.resolve(projectDir || '.');
  const outside = [];
  let checked = 0;
  const candidates = [];

  // Prefer explicit files named in the gate command
  const named = String(testCommand || '').match(/[\w./\\-]+\.test\.\w+/g) || [];
  for (const n of named) {
    const abs = path.resolve(root, n);
    if (fs.existsSync(abs)) candidates.push(abs);
  }
  // Also walk test/ for *.test.mjs|js
  const walk = (dir, depth = 0) => {
    if (depth > 4 || !fs.existsSync(dir)) return;
    let ents;
    try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of ents) {
      const abs = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (e.name === 'node_modules' || e.name === '.git') continue;
        walk(abs, depth + 1);
      } else if (/\.test\.(mjs|js|cjs|ts)$/i.test(e.name)) {
        candidates.push(abs);
      }
    }
  };
  walk(path.join(root, 'test'));

  const seen = new Set();
  for (const file of candidates) {
    const key = path.resolve(file);
    if (seen.has(key)) continue;
    seen.add(key);
    let txt;
    try { txt = fs.readFileSync(file, 'utf8'); } catch { continue; }
    checked += 1;
    const re = /\bfrom\s*['"](\.\.?\/[^'"]+)['"]|\bimport\s*\(\s*['"](\.\.?\/[^'"]+)['"]\s*\)/g;
    let m;
    while ((m = re.exec(txt))) {
      const spec = m[1] || m[2];
      if (!spec) continue;
      let resolved = path.resolve(path.dirname(file), spec);
      // try .mjs/.js extensions
      if (!fs.existsSync(resolved)) {
        for (const ext of ['.mjs', '.js', '/index.mjs', '/index.js']) {
          if (fs.existsSync(resolved + ext)) { resolved = resolved + ext; break; }
        }
      }
      const rel = path.relative(root, resolved);
      if (rel.startsWith('..') || path.isAbsolute(rel)) {
        // Ignore node_modules and missing optional paths
        if (/node_modules/i.test(resolved)) continue;
        outside.push(`${path.relative(root, file) || file} → ${spec}`);
      }
    }
  }
  return { checked, outside: [...new Set(outside)] };
}

// ---------------------------------------------------------------------------
// §4.5  Project-DONE definition.
// ---------------------------------------------------------------------------

/**
 * Describe the DONE predicate for this project (§4.5). Phase 0 returns the
 * definition + the terminal wave; the engine (Phase 2) evaluates it.
 */
export function projectDoneDefinition(waves) {
  const last = waves.reduce((a, b) => (b.n > a.n ? b : a), waves[0]);
  return {
    total_waves: waves.length,
    last_wave: last.n,
    last_wave_title: last.title,
    predicate: 'DONE = last parsed wave GREEN (orchestrator-run gate) AND any plan-level acceptance gate met',
    note: 'Foreman emits a final-state verdict and stops; it does not loop past the last wave (§4.5).',
  };
}

// ---------------------------------------------------------------------------
// §8  Checkpoint schema + atomic write / validating read.
// ---------------------------------------------------------------------------

// Canonical schema. `null`-able fields are allowed to be null pre-first-wave.
const CHECKPOINT_FIELDS = {
  plan_path:        { type: 'string',  nullable: false },
  current_wave:     { type: 'number',  nullable: false },
  total_waves:      { type: 'number',  nullable: false },
  intra_wave_step:  { type: 'string',  nullable: false }, // execute|review|fix|judge|gate|done
  iteration:        { type: 'number',  nullable: false },
  reviewer_count:   { type: 'number',  nullable: false },
  budget_remaining: { type: 'object',  nullable: false }, // {waves,fix_iters,wall_clock_min}
  last_verdict:     { type: 'string',  nullable: true },  // GO|NO-GO|HALT|null
  last_commit:      { type: 'string',  nullable: true },
  open_findings:    { type: 'array',   nullable: false }, // [{id,severity,file,line,rule,status}]
  pending_action:   { type: 'string',  nullable: true },
  stash_ref:        { type: 'string',  nullable: true },
  status:           { type: 'string',  nullable: false }, // running|halted|done
};

/** Build a fresh, schema-valid checkpoint for wave 1 / pre-execute. */
export function newCheckpoint({ plan_path, total_waves, reviewer_count = 2, budget = {} }) {
  return {
    plan_path,
    current_wave: 1,
    total_waves,
    intra_wave_step: 'execute',
    iteration: 0,
    reviewer_count,
    budget_remaining: {
      waves: budget.waves ?? total_waves,
      fix_iters: budget.fix_iters ?? 4,
      wall_clock_min: budget.wall_clock_min ?? null,
    },
    last_verdict: null,
    last_commit: null,
    open_findings: [],
    pending_action: null,
    stash_ref: null,
    status: 'running',
  };
}

/** Validate `obj` against the canonical schema. Throws HaltError on any breach. */
export function validateCheckpoint(obj) {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new HaltError('checkpoint is not a JSON object');
  }
  for (const [key, spec] of Object.entries(CHECKPOINT_FIELDS)) {
    if (!(key in obj)) {
      throw new HaltError(`checkpoint missing required field: ${key}`);
    }
    const v = obj[key];
    if (v === null) {
      if (!spec.nullable) throw new HaltError(`checkpoint field ${key} must not be null`);
      continue;
    }
    const actual = Array.isArray(v) ? 'array' : typeof v;
    if (actual !== spec.type) {
      throw new HaltError(`checkpoint field ${key} has wrong type: expected ${spec.type}, got ${actual}`);
    }
  }
  return obj;
}

/**
 * Atomically write a checkpoint: serialize -> write `<file>.tmp` -> fsync ->
 * rename over the destination. A torn write can never replace a valid file
 * because rename is atomic and the partial data only ever lives in the tmp.
 */
export function writeCheckpointAtomic(file, checkpoint) {
  validateCheckpoint(checkpoint);
  const dest = path.resolve(file);
  const tmp = dest + '.tmp';
  const data = JSON.stringify(checkpoint, null, 2) + '\n';
  const fd = fs.openSync(tmp, 'w');
  try {
    fs.writeSync(fd, data);
    fs.fsyncSync(fd); // flush to disk before the rename publishes it
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(tmp, dest); // atomic on NTFS (MoveFileEx REPLACE_EXISTING) and POSIX
  // K (durability): fsync the PARENT DIRECTORY so the rename's directory entry is
  // itself flushed, making the publish crash-durable on POSIX (without this, the
  // file's data is durable but the rename that names it may not survive a crash).
  // Best-effort: on Windows/NTFS opening a directory for fsync is typically
  // unsupported (EISDIR/EPERM/EACCES), so we ATTEMPT it and tolerate failure
  // rather than fail an otherwise-successful write. The atomic contract above is
  // unchanged.
  try {
    const dirFd = fs.openSync(path.dirname(dest), 'r');
    try { fs.fsyncSync(dirFd); } finally { fs.closeSync(dirFd); }
  } catch {
    // directory fsync unsupported on this platform — tolerate and continue.
  }
  return dest;
}

/**
 * Read + validate a checkpoint. On invalid JSON (torn file) or schema breach,
 * throws HaltError — per §8 we HALT, never best-effort parse a torn file.
 */
export function readCheckpoint(file) {
  const dest = path.resolve(file);
  let raw;
  try {
    raw = fs.readFileSync(dest, 'utf8');
  } catch (e) {
    throw new HaltError('checkpoint file unreadable', e.message);
  }
  let obj;
  try {
    obj = JSON.parse(raw);
  } catch (e) {
    throw new HaltError('checkpoint JSON is invalid (possible torn write) — refusing to best-effort parse', e.message);
  }
  return validateCheckpoint(obj);
}

// ---------------------------------------------------------------------------
// §4.6 / §6.1  Budget — a HARD PRE-FLIGHT GATE (Phase 3b).
//
// The plan (§4.6) defines the budget as an explicit TUPLE:
//   { max waves this run, max fix-iters/wave (default 4), max wall-clock }.
// The Workflow token target is a SECONDARY guard only (and is unavailable to a
// Node process anyway — §10: "the harness exposes no live quota API"). §7's real
// binding limit is the Pro USAGE WINDOW, but because §10 says there is no live
// quota API, the engine cannot read the window directly: "Pro-window calibration"
// (§11 Phase 3) is the EMPIRICAL measurement that SETS the wave/wall-clock cap
// defaults (~1–3 waves/window), not a runtime-readable meter. So this budget
// enforces the §4.6 tuple; the wave + wall-clock caps are what bound window burn.
//
// Enforcement is a HARD PRE-FLIGHT GATE, never advisory: before starting each
// affordable unit (a wave, or a fix iteration), the caller asks `canStart*()`; if
// the next unit cannot be afforded the caller does NOT start it — it writes a
// clean, resumable budget-stop checkpoint and HALTs (§6.1). The engine therefore
// never overruns by beginning work it cannot finish within budget. Wall-clock is
// enforced at unit boundaries (refuse to *start* a unit once the deadline has
// passed); per-unit duration is not predictable, so the boundary check is the
// affordability test.
//
// Conservative fallback (§10 best-effort telemetry, but a SAFE stop decision):
// the wall-clock is the only telemetry this budget reads. If a wall-clock budget
// is configured but the clock is unreadable or returns a non-finite value, we
// HALT (HaltError) rather than run unbounded — the stop decision fails safe.
// ---------------------------------------------------------------------------

/**
 * Build a budget enforcer. All caps are OPTIONAL; a null cap means "no limit on
 * that dimension". Budget is per-INVOCATION: `maxWaves` is "max waves THIS run"
 * (§4.6), and a resumed run starts a fresh budget (a new Pro window = new budget,
 * per §7 "wait for the window reset").
 *
 * @param {object}   o
 * @param {?number}  [o.maxWaves]            max waves to START this run (null = unlimited)
 * @param {number}   [o.maxFixItersPerWave]  §6.3 MAX_ITERS (carried for the checkpoint snapshot)
 * @param {?number}  [o.maxWallClockMs]      wall-clock cap in ms (null = unlimited)
 * @param {()=>number} [o.now]               clock source (injectable for tests); default Date.now
 * @returns budget with canStartWave()/startWave()/canStartFixIter()/snapshotForCheckpoint()
 */
export function makeBudget({ maxWaves = null, maxFixItersPerWave = 4, maxWallClockMs = null, now = Date.now } = {}) {
  // Validate configured numeric caps up front — a malformed cap is a contract
  // error, not something to silently treat as "unlimited".
  for (const [k, v] of [['maxWaves', maxWaves], ['maxWallClockMs', maxWallClockMs]]) {
    if (v !== null && !(Number.isFinite(v) && v >= 0)) {
      throw new HaltError(`budget cap ${k} is invalid`, `expected a non-negative finite number or null, got ${JSON.stringify(v)}`);
    }
  }
  // Conservative clock read: any failure to read a real number HALTs rather than
  // letting an unbounded run proceed (the §10 telemetry may be best-effort, but
  // the STOP DECISION must be safe).
  function readClock() {
    let t;
    try { t = now(); }
    catch (e) {
      throw new HaltError(
        'budget telemetry unreadable: wall-clock source threw — refusing to run unbounded',
        e && e.message ? e.message : String(e));
    }
    if (typeof t !== 'number' || !Number.isFinite(t)) {
      throw new HaltError(
        'budget telemetry unreadable: wall-clock returned a non-finite value — refusing to run unbounded',
        `clock yielded ${JSON.stringify(t)}`);
    }
    return t;
  }

  const t0 = readClock();           // anchor the run start (also fails fast on a bad clock)
  let wavesStarted = 0;

  const elapsedMs = () => readClock() - t0;

  function wallClockExhausted(where) {
    if (maxWallClockMs === null) return null;
    const e = elapsedMs();
    if (e >= maxWallClockMs) {
      return `wall-clock budget exhausted (${Math.round(e / 1000)}s elapsed ≥ ${Math.round(maxWallClockMs / 1000)}s cap)` +
        (where ? ` before ${where}` : '');
    }
    return null;
  }

  return {
    maxWaves, maxFixItersPerWave, maxWallClockMs,
    wavesStarted: () => wavesStarted,
    elapsedMs,

    /** Pre-flight: may we AFFORD to START another wave? (waves + wall-clock). */
    canStartWave() {
      if (maxWaves !== null && wavesStarted >= maxWaves) {
        return { ok: false, dimension: 'waves',
          reason: `wave budget exhausted (${wavesStarted}/${maxWaves} wave(s) already started this run)` };
      }
      const wc = wallClockExhausted('starting the next wave');
      if (wc) return { ok: false, dimension: 'wall-clock', reason: wc };
      return { ok: true };
    },

    /** Record that a wave has STARTED (call only after canStartWave() passed). */
    startWave() { wavesStarted += 1; },

    /** Pre-flight before a FIX iteration (wall-clock only; the iter COUNT cap is §6.3). */
    canStartFixIter() {
      const wc = wallClockExhausted('the next fix iteration');
      if (wc) return { ok: false, dimension: 'wall-clock', reason: wc };
      return { ok: true };
    },

    /** A §8 `budget_remaining` snapshot for the checkpoint (audit/telemetry). */
    snapshotForCheckpoint() {
      return {
        waves: maxWaves === null ? null : Math.max(0, maxWaves - wavesStarted),
        fix_iters: maxFixItersPerWave,
        wall_clock_min: maxWallClockMs === null ? null
          : Math.max(0, Math.round(((maxWallClockMs - elapsedMs()) / 60000) * 100) / 100),
      };
    },
  };
}

// ---------------------------------------------------------------------------
// §10  Running commentary — render the dashboard block from state.
// ---------------------------------------------------------------------------

/**
 * Render the §10 dashboard line/block. All live-quota fields are best-effort
 * (the harness exposes no quota API), so callers pass what they observe and
 * unknowns fall back gracefully.
 */
export function renderDashboard({
  project, wave, totalWaves, waveTitle,
  lines = [],            // ['▸ execute… done', ...] already-formatted step lines
  contextPct = null,     // best-effort
  elapsed = null,        // '1h12m'
  budgetWaves = null,    // '3/8 waves'
  window = 'OK',         // 'OK' | 'throttled @ HH:MM'
}) {
  const head = `[Foreman | ${project} | wave ${wave}/${totalWaves} "${waveTitle}"]`;
  const body = lines.map((l) => `  ${l}`).join('\n');
  const ctx = contextPct == null ? '~?% (best-effort)' : `~${contextPct}% (best-effort)`;
  const el = elapsed == null ? 'elapsed ?' : `elapsed ${elapsed}`;
  const bw = budgetWaves == null ? 'budget ?' : `budget ${budgetWaves}`;
  const footer = `context: ${ctx} · ${el} · ${bw} · window ${window}`;
  return [head, body, footer].filter(Boolean).join('\n');
}
