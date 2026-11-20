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
const WAVE_RE = /^##\s+(Wave|Sprint|Section)\s+(\d+)(?!\.\d)\b[ \t]*[—:\-.]?[ \t]*(.*)$/i;
const SUBWAVE_RE = /^#{2,3}\s+(Wave|Sprint|Section)\s+(\d+)\.(\d+)\b[ \t]*[—:\-.]?[ \t]*(.*)$/i;

function normalizePlanRelPath(raw) {
  return String(raw || '')
    .trim()
    .replace(/\\/g, '/')
    .replace(/^\.\//, '')
    .replace(/^\/+/, '')
    .replace(/\/+$/, '');
}

/** True when two repo-relative paths (or directory/glob prefixes) can touch the same file. */
export function pathsOverlap(aRaw, bRaw) {
  const a = normalizePlanRelPath(aRaw).replace(/\/?\*\*.*$/, '').replace(/\/?\*.*$/, '');
  const b = normalizePlanRelPath(bRaw).replace(/\/?\*\*.*$/, '').replace(/\/?\*.*$/, '');
  if (!a || !b) return false;
  const al = a.toLowerCase();
  const bl = b.toLowerCase();
  return al === bl || al.startsWith(`${bl}/`) || bl.startsWith(`${al}/`);
}

function parseListField(rawVal) {
  const cleaned = String(rawVal || '').trim();
  if (!cleaned || /^(?:none|n\/a|nil|\[\]|[-—])$/i.test(cleaned)) return [];
  return [...cleaned.matchAll(/`([^`]+)`|"([^"]+)"|'([^']+)'|([^\s,;`"']+)/g)]
    .map((x) => (x[1] ?? x[2] ?? x[3] ?? x[4] ?? '').trim())
    .filter((tok) => tok && !/^(?:none|n\/a|nil|\[\]|[-—]|and)$/i.test(tok));
}

function normalizeDepRef(rawDep, parentN) {
  const s = String(rawDep || '').trim().replace(/^(?:wave|sprint|section)\s+/i, '');
  if (/^\d+\.\d+$/.test(s)) return s;
  if (/^\d+$/.test(s)) return `${parentN}.${s}`;
  return s;
}

/**
 * Validate a parent wave's sub-waves (`W.1..W.k`), enforce DAG acyclicity + pairwise
 * disjoint write-sets across concurrent siblings, and return topological execution batches.
 */
export function computeSubwaveBatches(subwaves = [], parentWaveNum = 1) {
  if (!Array.isArray(subwaves) || subwaves.length === 0) return [];

  // Contiguous 1..k ascending sub-wave numbering within parent wave W
  const subs = subwaves.map((sw) => sw.sub);
  for (let i = 0; i < subs.length; i++) {
    if (subs[i] !== i + 1) {
      throw new HaltError(
        `sub-wave numbers under Wave ${parentWaveNum} are not contiguous ${parentWaveNum}.1..${parentWaveNum}.${subs.length}`,
        `found sub-waves [${subwaves.map((s) => s.id).join(', ')}] — number sub-waves contiguously in ascending order`,
      );
    }
  }

  const byId = new Map(subwaves.map((sw) => [sw.id, sw]));
  for (const sw of subwaves) {
    for (const dep of sw.dependsOn || []) {
      if (dep === sw.id) {
        throw new HaltError(
          `[taxonomy:subwave-cycle] sub-wave ${sw.id} depends on itself`,
          `remove self-dependency on Wave ${sw.id}`,
        );
      }
      if (!byId.has(dep)) {
        throw new HaltError(
          `[taxonomy:invalid-subwave-dep] sub-wave ${sw.id} depends on unknown sibling "${dep}"`,
          `Depends-On under Wave ${parentWaveNum} must reference sibling sub-waves in [${subwaves.map((s) => s.id).join(', ')}]`,
        );
      }
    }
  }

  // Kahn topological batches
  const inDegree = new Map(subwaves.map((sw) => [sw.id, (sw.dependsOn || []).length]));
  const dependents = new Map(subwaves.map((sw) => [sw.id, []]));
  for (const sw of subwaves) {
    for (const dep of sw.dependsOn || []) {
      dependents.get(dep).push(sw.id);
    }
  }

  const batches = [];
  let visited = 0;
  let ready = subwaves.filter((sw) => inDegree.get(sw.id) === 0).map((sw) => sw.id);
  while (ready.length > 0) {
    batches.push(ready);
    visited += ready.length;
    const nextReady = [];
    for (const id of ready) {
      for (const childId of dependents.get(id) || []) {
        const deg = inDegree.get(childId) - 1;
        inDegree.set(childId, deg);
        if (deg === 0) nextReady.push(childId);
      }
    }
    ready = nextReady;
  }

  if (visited !== subwaves.length) {
    throw new HaltError(
      `[taxonomy:subwave-cycle] cyclic Depends-On graph in Wave ${parentWaveNum}`,
      `sub-waves [${subwaves.map((s) => s.id).join(', ')}] contain a dependency cycle`,
    );
  }

  // Transitive reachability: reaches.get(a).has(b) === true iff a ->+ b (b runs strictly after a)
  const reaches = new Map(subwaves.map((sw) => [sw.id, new Set()]));
  for (const sw of subwaves) {
    const seen = new Set();
    const stack = [...(dependents.get(sw.id) || [])];
    while (stack.length > 0) {
      const cur = stack.pop();
      if (seen.has(cur)) continue;
      seen.add(cur);
      for (const nxt of dependents.get(cur) || []) stack.push(nxt);
    }
    reaches.set(sw.id, seen);
  }

  // Pairwise disjoint write-set enforcement across any two concurrent (unordered) sibling sub-waves
  for (let i = 0; i < subwaves.length; i++) {
    for (let j = i + 1; j < subwaves.length; j++) {
      const a = subwaves[i];
      const b = subwaves[j];
      const ordered = reaches.get(a.id).has(b.id) || reaches.get(b.id).has(a.id);
      if (ordered) continue;
      if (!a.writes?.length || !b.writes?.length) {
        throw new HaltError(
          `[taxonomy:missing-subwave-writes] concurrent sub-waves ${a.id} and ${b.id} must declare explicit Writes:/Files:`,
          `parallel sibling sub-waves require explicit disjoint file write-sets (or add Depends-On: ${a.id} on Wave ${b.id} to serialize them)`,
        );
      }
      for (const pa of a.writes) {
        for (const pb of b.writes) {
          if (pathsOverlap(pa, pb)) {
            throw new HaltError(
              `[taxonomy:overlapping-subwave-writes] concurrent sub-waves ${a.id} and ${b.id} have overlapping write-sets ("${pa}" vs "${pb}")`,
              `writes(${a.id}) ∩ writes(${b.id}) must be empty — split "${pa}"/"${pb}" cleanly or add Depends-On: ${a.id} on Wave ${b.id}`,
            );
          }
        }
      }
    }
  }

  return batches;
}

function parseSectionMetadata(lines, startLine1Based, endLine1Based, { stopAtSubwaves = false, parentN = null } = {}) {
  const section = [];
  let fenced = false;
  let gateCommand;
  let waveKind;
  const outputs = [];
  const writes = [];
  const dependsOn = [];

  for (let li = startLine1Based; li < endLine1Based - 1 && li < lines.length; li++) {
    const body = lines[li];
    if (!fenced && stopAtSubwaves && SUBWAVE_RE.test(body)) break;
    const gm = body.match(/^\s*(?:wave[-_ ]?)?gate[-_ ]?command\s*[:=]\s*(.+)$/i);
    if (gm) {
      const cmd = gm[1].replace(/^`+|`+$/g, '').trim();
      if (cmd) gateCommand = cmd;
    }
    if (/^\s*(```|~~~)/.test(body)) { fenced = !fenced; continue; }
    if (fenced) continue;
    section.push(body);
    const km = body.match(/^\s*\*{0,2}(?:wave[-_ ]?)?kind\*{0,2}\s*[:=]\s*`?([a-z][a-z-]*)`?\s*$/i);
    if (km) waveKind = km[1].toLowerCase();
    const om = body.match(/^\s*[-*+]?\s*\*{0,2}(?:(?:declared|wave)[-_ ]?outputs?|outputs)\*{0,2}\s*[:=]\s*(.+)$/i);
    if (om) {
      outputs.push(...parseListField(om[1]));
    }
    const wm = body.match(/^\s*[-*+]?\s*\*{0,2}(?:writes?|files?|write[-_ ]?set|target[-_ ]?files?)\*{0,2}\s*[:=]\s*(.+)$/i);
    if (wm) {
      for (const p of parseListField(wm[1])) {
        const norm = normalizePlanRelPath(p);
        if (norm && !writes.includes(norm)) writes.push(norm);
      }
    }
    const dm = body.match(/^\s*[-*+]?\s*\*{0,2}(?:depends[-_ ]?on|after|needs)\*{0,2}\s*[:=]\s*(.+)$/i);
    if (dm && parentN !== null) {
      for (const d of parseListField(dm[1])) {
        const normDep = normalizeDepRef(d, parentN);
        if (normDep && !dependsOn.includes(normDep)) dependsOn.push(normDep);
      }
    }
  }

  return {
    acceptance: section.join('\n').trim(),
    gateCommand,
    waveKind,
    outputs,
    writes,
    dependsOn,
  };
}

/**
 * Parse waves (and optional `W.1..W.k` sub-waves) from plan markdown text.
 * @returns {Array<{n:number, title:string, kind:string, line:number, gateCommand?:string, waveKind?:string,
 *   outputs?:string[], writes?:string[], subwaves?:object[], subwaveBatches?:string[][],
 *   acceptance:string, oracles:{item:string, oracle:string}[]}>}
 * @throws HaltError if zero waves found, wave numbers are not 1..N contiguous/ascending,
 *   or concurrent sibling sub-waves have overlapping/missing write-sets.
 */
export function parseWaves(planText) {
  const lines = planText.split(/\r?\n/);
  const waves = [];
  let inFence = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*(```|~~~)/.test(line)) { inFence = !inFence; continue; }
    if (inFence) continue; // ignore headings inside code fences
    const sm = SUBWAVE_RE.exec(line);
    if (sm) {
      const kind = sm[1].toLowerCase();
      const parent = Number(sm[2]);
      const sub = Number(sm[3]);
      const subObj = {
        id: `${parent}.${sub}`,
        parent,
        sub,
        kind,
        title: (sm[4] || '').trim(),
        line: i + 1,
      };
      const lastWave = waves[waves.length - 1];
      if (lastWave && lastWave.n === parent) {
        lastWave.subwaves.push(subObj);
      } else {
        waves.push({
          kind,
          n: parent,
          title: `Wave ${parent} (parallel sub-waves)`,
          line: i + 1,
          implicitParent: true,
          subwaves: [subObj],
        });
      }
      continue;
    }
    const m = WAVE_RE.exec(line);
    if (m) {
      waves.push({
        kind: m[1].toLowerCase(),
        n: Number(m[2]),
        title: (m[3] || '').trim(),
        line: i + 1,
        subwaves: [],
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

  const ascending = nums.every((v, idx) => idx === 0 || v > nums[idx - 1]);
  if (!ascending) {
    throw new HaltError(
      'waves are not declared in ascending order',
      `wave numbers appear as [${nums.join(', ')}] in the plan — reorder the headings so they read 1..N top-to-bottom; Foreman will not reorder them for you (§4.3)`,
    );
  }

  for (let wi = 0; wi < waves.length; wi++) {
    const w = waves[wi];
    const start = w.line; // 1-based
    const end = wi + 1 < waves.length ? waves[wi + 1].line : lines.length + 1;

    // Whole-wave metadata (acceptance spans entire parent wave including sub-waves so
    // required-test oracles & review prompts see the complete parent wave contract).
    const fullMeta = parseSectionMetadata(lines, w.implicitParent ? start - 1 : start, end, {
      stopAtSubwaves: false,
      parentN: null,
    });
    const headerMeta = w.subwaves.length > 0 && !w.implicitParent
      ? parseSectionMetadata(lines, start, w.subwaves[0].line, { stopAtSubwaves: true, parentN: null })
      : fullMeta;

    if (headerMeta.gateCommand || fullMeta.gateCommand) {
      w.gateCommand = headerMeta.gateCommand || fullMeta.gateCommand;
    }
    if (headerMeta.waveKind) w.waveKind = headerMeta.waveKind;
    else if (!w.subwaves.length && fullMeta.waveKind) w.waveKind = fullMeta.waveKind;
    if (fullMeta.outputs.length) w.outputs = fullMeta.outputs;
    if (fullMeta.writes.length) w.writes = fullMeta.writes;
    w.acceptance = fullMeta.acceptance;
    w.oracles = parseWaveOracles(w.acceptance);

    if (w.subwaves.length > 0) {
      for (let si = 0; si < w.subwaves.length; si++) {
        const sw = w.subwaves[si];
        const swEnd = si + 1 < w.subwaves.length ? w.subwaves[si + 1].line : end;
        const swMeta = parseSectionMetadata(lines, sw.line, swEnd, {
          stopAtSubwaves: false,
          parentN: w.n,
        });
        if (swMeta.gateCommand) sw.gateCommand = swMeta.gateCommand;
        if (swMeta.waveKind) sw.waveKind = swMeta.waveKind;
        if (swMeta.outputs.length) sw.outputs = swMeta.outputs;
        sw.writes = swMeta.writes;
        sw.dependsOn = swMeta.dependsOn;
        sw.acceptance = swMeta.acceptance;
        sw.oracles = parseWaveOracles(sw.acceptance);
      }
      w.subwaveBatches = computeSubwaveBatches(w.subwaves, w.n);
      const unionWrites = [...new Set([
        ...(w.writes || []),
        ...w.subwaves.flatMap((sw) => sw.writes || []),
      ])];
      if (unionWrites.length) w.writes = unionWrites;
    } else {
      delete w.subwaves;
    }
    delete w.implicitParent;
  }
  return waves;
}

/**
 * S5/S6 (2026-10-10): the `(oracle: ...)` of each acceptance item - the one grammar the slim plan writes, the
 * hardening lint reads (through `acceptance`) and wave-engine's required-test guard enforces. An oracle that names
 * a test file makes that file a REQUIRED test of the wave (wave-engine requiredWaveTestPaths); any other oracle (a
 * command, an observable fact) is kept as text so a review and the wave's record can trace each test to the item
 * it proves. One level of parentheses inside the oracle is allowed.
 * @param {string} sectionText  a wave's acceptance/section text (fenced examples already removed)
 * @returns {{item:string, oracle:string}[]}
 */
export function parseWaveOracles(sectionText) {
  const out = [];
  const re = /\(\s*oracle\s*:\s*([^()]*(?:\([^()]*\)[^()]*)*)\)/gi;
  for (const raw of String(sectionText || '').split(/\r?\n/)) {
    const line = raw.replace(/\*\*/g, '').trim();
    let m;
    while ((m = re.exec(line)) !== null) {
      const oracle = m[1].trim();
      if (!oracle) continue;
      const item = line.slice(0, m.index).replace(/^(?:[-*+]|\d+[.)])\s*/, '').trim();
      out.push({ item, oracle });
    }
    re.lastIndex = 0;
  }
  return out;
}

/** S3: the wave kinds whose gate is their declared outputs rather than a test suite. */
export const NONCODE_WAVE_KINDS = Object.freeze(['docs', 'landing', 'verification', 'render', 'data']);

/** S3: a wave is non-code only when it DECLARES a non-code kind AND names its outputs - a kind with nothing declared
 *  proves nothing, and outputs without the kind are a code wave's deliverables. The label alone never selects the
 *  gate: wave-engine still inspects the measured changes (final review 10-10, finding 1). */
export function isNonCodeWave(wave) {
  return !!(wave && NONCODE_WAVE_KINDS.includes(String(wave.waveKind || '').toLowerCase())
    && Array.isArray(wave.outputs) && wave.outputs.length > 0);
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
//   - -q/--quiet        -> enough -v inserted to outweigh them (pytest nets -v
//                          against -q), so `pytest -q` runs as `pytest -vv -q`: the
//                          author's check, with the per-test events GREEN needs
//                          (John 2026-10-11: an ordinary `python -m pytest -q`
//                          check must never be refused).
//   - already verbose   -> untouched. Non-pytest commands -> untouched.
const PYTEST_TOKEN_RE = /(^|[\s/\\])(python(?:\d(?:\.\d+)?)?\s+-m\s+pytest|pytest|py\.test)(?=\s|$)/;

// pytest's no-value short flags combine (`-qqv`, `-xvs`): each v/q in such a group counts
const SHORT_GROUP_RE = /(^|\s)-([vqxsl]+)(?=\s|$)/g;

function flagCount(cmd, letter, long) {
  let short = 0;
  for (const m of cmd.matchAll(SHORT_GROUP_RE)) short += m[2].split(letter).length - 1;
  return short + (cmd.match(new RegExp(`(^|\\s)--${long}(?=\\s|$)`, 'g')) || []).length;
}

export function normalizePytestGate(command, source) {
  const cmd = String(command).trim();
  const m = cmd.match(PYTEST_TOKEN_RE);
  if (!m) return { command: cmd, source };
  const need = 1 - (flagCount(cmd, 'v', 'verbose') - flagCount(cmd, 'q', 'quiet'));
  if (need <= 0) return { command: cmd, source };
  const insertAt = m.index + m[0].length;
  const flag = '-' + 'v'.repeat(need);
  return {
    command: cmd.slice(0, insertAt) + ' ' + flag + cmd.slice(insertAt),
    source: `${source} (normalized: ${flag} inserted — GREEN requires per-test events)`,
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

/**
 * S3 (2026-10-10, final review 10-10 finding 6): the project's gate command through PRODUCTION startup - or NO
 * command when EVERY parsed wave is a non-code wave (each is proven by its declared outputs; a fictitious
 * `test-command:` would be the lie the W0 runs told). A plan with any code wave (no `kind:`, or a kind without
 * outputs) still needs its command: §4.4 "no ground truth → cannot gate" is unchanged for it. The one caller-facing
 * shape is discoverTestCommand's, with `command: null` for the artifact-only case.
 * @param {string} planText
 * @param {string} projectDir
 * @param {ReturnType<typeof parseWaves>} waves
 * @returns {{command:?string, source:string, artifactOnly?:true}}
 */
export function discoverGateCommand(planText, projectDir, waves) {
  try {
    return discoverTestCommand(planText, projectDir);
  } catch (e) {
    const artifactOnly = Array.isArray(waves) && waves.length > 0 && waves.every((w) => isNonCodeWave(w));
    if (e instanceof HaltError && /no ground-truth test command/.test(String(e.reason)) && artifactOnly) {
      return {
        command: null,
        artifactOnly: true,
        source: `none — every wave is a non-code wave (${waves.map((w) => `${w.n}:${w.waveKind}`).join(', ')}) proven by its declared outputs`,
      };
    }
    throw e;
  }
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
