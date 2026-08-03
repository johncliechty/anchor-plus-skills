// Wave 1 — F0: tools manifest + persistent-server infra + per-class integrity probe gate.
//
// MAKE EVERY EXTERNAL TOOL REACHABLE, FAST-ENOUGH, AND CORRECT BEFORE ANY CERTIFIER IS TRUSTED.
// Increment-2 (Phase F) wires OUT-OF-MODEL certifiers into the verify-router — Lean (F2), z3 (F3),
// and the cross-family class (F1). Substrate (2026-07): the cross-family class is
// GEMINI-PRIMARY via the agy CLI (the frontier "Gemini 3.1 Pro (High)" LABEL through the agy login —
// generator-INDEPENDENT of Claude) with an ollama-FALLBACK panel (Qwen/Llama). The F0 probe runs the PRIMARY FIRST (a
// frontier-canary self-test then the sentinel battery); a Gemini that is key-missing / unauthorized /
// credit-depleted (HTTP 429) / unreachable is QUARANTINED and the probe FALLS BACK to ollama, stamping
// the active cross-family tier (frontier => CORROBORATED | fallback => PLAUSIBILITY-CORROBORATED); if
// the fallback ALSO fails, the lift HARD-FAULTS to CONJECTURAL. The Honesty Law forbids trusting any of them on a
// recorded field alone: a tool earns trust ONLY by answering its per-class integrity SENTINELS
// correctly, and a tool that MIS-answers a sentinel — including a wrong-answering DETERMINISTIC stub
// (a `lean` that exits 0 on a false theorem) — is QUARANTINED (its lift structurally disabled), not
// merely flagged. This module is that gate plus the persistent-ollama-server infra the cross-family
// probe needs.
//
//   1. THE MANIFEST (tools.manifest.json).  Each tool is pinned by ABSOLUTE path + class
//      (deterministic | probabilistic) + (for ollama) deterministic-decoding options and the
//      persistent-server config. loadManifest/validateManifest read + structurally check it. Tools
//      are spawned by absolute path via execFile (NO shell) so there is no quoting/injection surface.
//
//   2. THE PER-CLASS SENTINELS.
//      - DETERMINISTIC (lean, z3): a SINGLE-SHOT battery. lean: true theorem -> exit 0, false
//        theorem -> non-zero. z3: the negation of a TRUE sentence -> `unsat`, a satisfiable sentence
//        -> `sat`. Any miss (incl. exit-0 on the false theorem) => QUARANTINED.
//      - PROBABILISTIC (cross-family ollama): N=5 trials at deterministic decoding on a known-true +
//        known-false battery (5/5 each) PLUS a proof-JUDGING sentinel — a planted plausible-but-wrong
//        proof the panel MUST reject. A model that accepts the wrong proof is QUARANTINED from the
//        PLAUSIBILITY-CORROBORATED path.
//
//   3. THE PERSISTENT-SERVER INFRA.  A single cold ollama generation measured >200s on this host, so
//      startOllamaServer + warmUp pay the model cold-load ONCE; createOllamaGenerate then talks to the
//      keep_alive'd server with the manifest's deterministic decoding. stopOllamaServer kills the
//      server process TREE (taskkill /T on win32) so an orphan can't mask a cold-start regression, and
//      warmUp asserts a FRESH-LOAD signal (a real model load_duration), not just a 200-OK.
//
// THE BUILD-GATE ISOLATION CONTRACT (v2.1/v2.2): this module starts NOTHING and touches NO tool at
// import time — every spawn/HTTP call happens only inside a function the caller invokes. The
// honesty-bearing tool tests live in the env-gated serial lane (RAMANUJAN_TOOL_TESTS=1); the fast
// Foreman `node --test test/` gate exercises the probe LOGIC against stubs and never starts a server.
//
// Pure node built-ins (child_process, crypto, fs, os, path, url) + global fetch (Node 18+). ESM.

import { execFileSync, spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** The pinned tool manifest (repo root). */
export const DEFAULT_MANIFEST_PATH = fileURLToPath(new URL('../tools.manifest.json', import.meta.url));

/** The CANONICAL tool-lane gate env var (pinned identically in tools.manifest.json + test helper). */
export const TOOL_LANE_ENV = 'RAMANUJAN_TOOL_TESTS';

/** The two integrity classes. */
export const TOOL_CLASS = Object.freeze({ DETERMINISTIC: 'deterministic', PROBABILISTIC: 'probabilistic' });

/** A tool is either TRUSTED (sentinels passed) or QUARANTINED (a sentinel missed => lift disabled). */
export const PROBE_STATUS = Object.freeze({ TRUSTED: 'trusted', QUARANTINED: 'quarantined' });

/** N=5 trials for the probabilistic cross-family battery (quorum 5/5). */
export const CROSS_FAMILY_TRIALS = 5;

/** The lift a quarantined cross-family panel disables (consumed by Wave 3). */
export const PLAUSIBILITY_CORROBORATED = 'PLAUSIBILITY-CORROBORATED';

/** The frontier (Gemini) cross-family rung — the locked NS5 cross-family rung, above the fallback tier. */
export const CORROBORATED = 'CORROBORATED';

/** The hard-fault rung when NO cross-family backend can be probed (Gemini quarantined AND ollama failed). */
export const CONJECTURAL = 'CONJECTURAL';

/** The cross-family substrate tier the F0 probe STAMPS (v3): frontier (Gemini) | fallback (ollama) | none. */
export const CROSS_FAMILY_TIER = Object.freeze({ FRONTIER: 'frontier', FALLBACK: 'fallback', NONE: 'none' });

/** The PRIMARY cross-family family (frontier, generator-independent of Claude). */
export const FRONTIER_FAMILY = 'gemini';

/** The Gemini API base URL + PINNED host — retained ONLY for the back-compat buildGeminiRequest/parseGeminiResponse
 * shaping helpers + their unit tests. The LIVE cross-family transport is now the agy CLI (see below), NOT HTTP. */
export const GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta';
export const GEMINI_HOST = 'generativelanguage.googleapis.com';

/**
 * The pinned agy model LABELs (2026-07: the cross-family PRIMARY is the Antigravity CLI `agy`, NOT the
 * dead Gemini HTTP API). agy is addressed by human LABEL, NEVER an API-style id — an API-style id is
 * UNRECOGNIZED and agy SILENTLY serves Flash instead (the phantom-id degrade the served==requested
 * attestation catches). Mirrors KNOWN_AGY_LABELS in <path>
 */
export const KNOWN_AGY_LABELS = Object.freeze(new Set(['Gemini 3.1 Pro (High)', 'Gemini 3.5 Flash (Medium)']));

/** The default frontier agy LABEL — the verifier whose attested verdict earns the CORROBORATED rung. */
export const DEFAULT_FRONTIER_LABEL = 'Gemini 3.1 Pro (High)';

/** Default agy driver path (overridden by manifest tools.gemini.driver_ref); dynamic-imported LIVE only. */
export const DEFAULT_AGY_DRIVER_REF = '<path>';

/**
 * The fail-closed enumeration for the Gemini PRIMARY (DESCRIPTION-INC2 §v3.1). EVERY class
 * quarantines Gemini and falls the probe back to ollama (tier=fallback); none is a silent pass.
 */
export const GEMINI_FAIL_CLASS = Object.freeze({
  KEY_MISSING: 'KEY_MISSING',         // GEMINI_API_KEY unset / empty
  UNAUTHORIZED: 'UNAUTHORIZED',       // HTTP 401 / 403 (invalid key)
  CREDIT_DEPLETED: 'CREDIT_DEPLETED', // HTTP 429 (AI-Studio $0 credits) — today's state
  NETWORK: 'NETWORK',                 // timeout / DNS / connection / agy transport failure
  HTTP_ERROR: 'HTTP_ERROR',           // any other non-2xx / unclassified agy status
  BAD_RESPONSE: 'BAD_RESPONSE',       // 2xx but unparseable body / agy returned no reply
  ATTESTATION: 'ATTESTATION',         // agy served a DIFFERENT model than requested, or could not attest the served model (served!=requested)
});

/** A typed error so a probe wiring/usage bug is distinguishable from a tool verdict. */
export class PhaseFProbeError extends Error {
  constructor(message, extra = {}) {
    super(message);
    this.name = 'PhaseFProbeError';
    Object.assign(this, extra);
  }
}

// ---------------------------------------------------------------------------
// Manifest load + structural validation.
// ---------------------------------------------------------------------------

/** Read + parse the pinned tools manifest. */
export function loadManifest(manifestPath = DEFAULT_MANIFEST_PATH) {
  let text;
  try {
    text = fs.readFileSync(manifestPath, 'utf8');
  } catch (e) {
    throw new PhaseFProbeError(`tools manifest not found at ${manifestPath}: ${e && e.message}`);
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new PhaseFProbeError(`tools manifest is not valid JSON (${manifestPath}): ${e && e.message}`);
  }
}

/**
 * Structurally validate a manifest object WITHOUT touching the filesystem-resident tools (so it
 * passes on a fresh checkout / a host where the tools are absent — path existence is a tool-lane
 * concern). Returns { ok, errors:[...] }.
 */
export function validateManifest(manifest) {
  const errors = [];
  if (!manifest || typeof manifest !== 'object') {
    return { ok: false, errors: ['manifest is not an object'] };
  }
  if (manifest.tool_lane_env !== TOOL_LANE_ENV) {
    errors.push(`tool_lane_env must be ${JSON.stringify(TOOL_LANE_ENV)} (got ${JSON.stringify(manifest.tool_lane_env)})`);
  }
  const tools = manifest.tools;
  if (!tools || typeof tools !== 'object') {
    errors.push('manifest.tools is missing');
    return { ok: errors.length === 0, errors };
  }
  for (const name of ['lean', 'z3', 'ollama']) {
    const t = tools[name];
    if (!t) {
      errors.push(`required tool ${name} is absent from the manifest`);
      continue;
    }
    if (typeof t.path !== 'string' || !path.isAbsolute(t.path)) {
      errors.push(`${name}.path must be an ABSOLUTE path (got ${JSON.stringify(t.path)})`);
    }
    if (t.class !== TOOL_CLASS.DETERMINISTIC && t.class !== TOOL_CLASS.PROBABILISTIC) {
      errors.push(`${name}.class must be one of ${Object.values(TOOL_CLASS).join('|')} (got ${JSON.stringify(t.class)})`);
    }
  }
  if (tools.lean && tools.lean.class !== TOOL_CLASS.DETERMINISTIC) errors.push('lean must be class deterministic');
  if (tools.z3 && tools.z3.class !== TOOL_CLASS.DETERMINISTIC) errors.push('z3 must be class deterministic');
  if (tools.ollama) {
    if (tools.ollama.class !== TOOL_CLASS.PROBABILISTIC) errors.push('ollama must be class probabilistic');
    const dd = tools.ollama.deterministic_decoding;
    if (!dd || typeof dd !== 'object') {
      errors.push('ollama.deterministic_decoding is required (the bare `ollama run` default is NOT temp 0)');
    } else {
      if (dd.temperature !== 0) errors.push('ollama.deterministic_decoding.temperature must be 0');
      if (dd.top_k !== 1) errors.push('ollama.deterministic_decoding.top_k must be 1');
      if (dd.top_p !== 1) errors.push('ollama.deterministic_decoding.top_p must be 1');
      if (!Number.isInteger(dd.seed)) errors.push('ollama.deterministic_decoding.seed must be a fixed integer');
      if (!Number.isInteger(dd.num_predict) || dd.num_predict <= 0) errors.push('ollama.deterministic_decoding.num_predict must be a positive integer cap');
    }
    const models = tools.ollama.models;
    if (!Array.isArray(models) || models.length < 2) {
      errors.push('ollama.models must list >=2 distinct families (quorum >=2 for PLAUSIBILITY-CORROBORATED)');
    } else {
      const families = new Set(models.map((m) => m && m.family));
      if (families.size < 2) errors.push('ollama.models must span >=2 DISTINCT families');
    }
    const srv = tools.ollama.server;
    if (!srv || typeof srv.base_url !== 'string') errors.push('ollama.server.base_url is required (persistent server)');
  }

  // --- v3 substrate: the cross-family PRIMARY is Gemini via the agy CLI (a cli-agy class — NO HTTP
  // endpoint, NO API key; agy is addressed by a pinned LABEL and reached through the login). ---
  const gem = tools.gemini;
  if (!gem) {
    errors.push('required cross-family PRIMARY tool gemini is absent from the manifest (v3 substrate)');
  } else {
    if (gem.class !== TOOL_CLASS.PROBABILISTIC) errors.push('gemini must be class probabilistic');
    if (gem.kind !== 'cli-agy') errors.push('gemini.kind must be "cli-agy" (the agy CLI transport — the bare Gemini HTTP API is dead)');
    if (typeof gem.driver_ref !== 'string' || !path.isAbsolute(gem.driver_ref)) {
      errors.push('gemini.driver_ref must be the ABSOLUTE path to the agy driver (gemini-cli.mjs)');
    }
    if (typeof gem.model !== 'string' || !KNOWN_AGY_LABELS.has(gem.model)) {
      errors.push(`gemini.model must be a known agy LABEL, one of {${[...KNOWN_AGY_LABELS].join(' | ')}} (an API-style id silently degrades to Flash)`);
    }
    if (gem.temperature !== 0) errors.push('gemini.temperature must be 0 (deterministic decoding)');
    if (gem.family !== FRONTIER_FAMILY) errors.push(`gemini.family must be ${FRONTIER_FAMILY}`);
    if (Object.prototype.hasOwnProperty.call(gem, 'path')) errors.push('gemini is a cli-agy class and must NOT carry a local tool path');
  }

  // --- v3 substrate block: PRIMARY/FALLBACK + the per-tier rungs + the hard-fault rung. ---
  const cf = manifest.cross_family;
  if (!cf || typeof cf !== 'object') {
    errors.push('manifest.cross_family substrate block is required (v3): {primary, fallback, frontier_rung, fallback_rung, hard_fault_rung}');
  } else {
    if (cf.primary !== 'gemini') errors.push('cross_family.primary must be gemini (v3 GEMINI-PRIMARY substrate)');
    if (cf.fallback !== 'ollama') errors.push('cross_family.fallback must be ollama');
    if (cf.frontier_rung !== CORROBORATED) errors.push(`cross_family.frontier_rung must be ${CORROBORATED}`);
    if (cf.fallback_rung !== PLAUSIBILITY_CORROBORATED) errors.push(`cross_family.fallback_rung must be ${PLAUSIBILITY_CORROBORATED}`);
    if (cf.hard_fault_rung !== CONJECTURAL) errors.push(`cross_family.hard_fault_rung must be ${CONJECTURAL}`);
  }

  return { ok: errors.length === 0, errors };
}

// ---------------------------------------------------------------------------
// No-shell subprocess primitive.
// ---------------------------------------------------------------------------

/**
 * Spawn an executable by absolute path with execFileSync — NO shell, so the argv is passed verbatim
 * (no Windows quoting/injection surface). Returns { exitCode, stdout, stderr, timedOut } and NEVER
 * throws on a non-zero exit (a non-zero exit is a legitimate sentinel observation, e.g. lean on a
 * false theorem). Throws PhaseFProbeError only on a spawn failure (ENOENT — the tool is unreachable).
 */
export function runExecutable(absPath, args = [], { input, timeoutMs = 60000, cwd } = {}) {
  try {
    const stdout = execFileSync(absPath, args, {
      input,
      cwd,
      timeout: timeoutMs,
      encoding: 'utf8',
      windowsHide: true,
      maxBuffer: 16 * 1024 * 1024,
    });
    return { exitCode: 0, stdout: stdout == null ? '' : String(stdout), stderr: '', timedOut: false };
  } catch (e) {
    if (e && (e.code === 'ENOENT' || e.errno === -4058)) {
      throw new PhaseFProbeError(`tool unreachable (spawn failed) at ${absPath}: ${e.message}`, { unreachable: true });
    }
    const timedOut = Boolean(e && (e.killed || e.signal === 'SIGTERM') && e.code === 'ETIMEDOUT') || (e && e.code === 'ETIMEDOUT');
    return {
      exitCode: typeof e.status === 'number' ? e.status : 1,
      stdout: e && e.stdout != null ? String(e.stdout) : '',
      stderr: e && e.stderr != null ? String(e.stderr) : '',
      timedOut: Boolean(timedOut),
    };
  }
}

/**
 * SMOKE / reachability: spawn the tool by its manifest absolute path and confirm it runs (a version
 * probe). Proves the done-when's "every tool is spawned via its manifest absolute path from a clean
 * shell". Returns { reachable, exitCode, output }.
 */
export function smokeReachable(toolSpec, { exec = runExecutable, timeoutMs = 30000 } = {}) {
  const args = Array.isArray(toolSpec.version_args) ? toolSpec.version_args : ['--version'];
  try {
    const r = exec(toolSpec.path, args, { timeoutMs });
    return { reachable: true, exitCode: r.exitCode, output: `${r.stdout}${r.stderr}`.trim() };
  } catch (e) {
    if (e instanceof PhaseFProbeError && e.unreachable) return { reachable: false, exitCode: null, output: e.message };
    throw e;
  }
}

// ---------------------------------------------------------------------------
// DETERMINISTIC sentinels (lean, z3).
//
// A sentinel battery is a list of { label, writeInput(dir)->filename, args(file)->argv, accept(obs),
// describe }. The probe writes each input into a hermetic temp dir, spawns the tool, and checks the
// observation. ANY miss => QUARANTINED, naming the failed sentinel. The "command" abstraction
// ({ path, baseArgs }) lets the SAME probe drive the real tool (path=lean.exe, baseArgs=[]) or a stub
// (path=node.exe, baseArgs=[stubScript]) — the stub is still spawned by absolute path, no shell.
// ---------------------------------------------------------------------------

/** Lean sentinels: a true theorem must typecheck (exit 0); a FALSE one must be rejected (non-zero). */
export const LEAN_SENTINELS = Object.freeze([
  Object.freeze({
    label: 'lean:true-theorem-must-accept',
    file: 'true.lean',
    source: 'example : (1 : Nat) + 1 = 2 := rfl\n',
    accept: (o) => o.exitCode === 0,
    describe: 'lean must exit 0 on `1+1=2 := rfl`',
  }),
  Object.freeze({
    label: 'lean:false-theorem-must-reject',
    file: 'false.lean',
    source: 'example : (1 : Nat) + 1 = 3 := rfl\n',
    accept: (o) => o.exitCode !== 0,
    describe: 'lean must exit NON-ZERO on `1+1=3 := rfl` (a stub that exits 0 here is QUARANTINED)',
  }),
]);

/** z3 sentinels: the negation of a true sentence is `unsat`; a satisfiable sentence is `sat`. */
export const Z3_SENTINELS = Object.freeze([
  Object.freeze({
    label: 'z3:negation-of-true-must-be-unsat',
    file: 'neg-true.smt2',
    source: '(assert (not (= (+ 1 1) 2)))\n(check-sat)\n',
    accept: (o) => /\bunsat\b/.test(o.stdout),
    describe: 'z3 must answer `unsat` on (not (1+1=2))',
  }),
  Object.freeze({
    label: 'z3:satisfiable-must-be-sat',
    file: 'sat.smt2',
    source: '(assert (= (+ 1 1) 2))\n(check-sat)\n',
    accept: (o) => /\bsat\b/.test(o.stdout) && !/\bunsat\b/.test(o.stdout),
    describe: 'z3 must answer `sat` on (1+1=2)',
  }),
]);

/**
 * Run a deterministic sentinel battery against a command. `command` = { path, baseArgs } (the tool
 * spawned by absolute path; baseArgs lets a stub be driven via node). Returns a per-tool probe result:
 *   { name, class:'deterministic', status, reason, results:[{ label, accepted, observation }] }
 * status is QUARANTINED on the FIRST miss (its label named in `reason`).
 */
export function probeDeterministic(name, command, sentinels, { exec = runExecutable, timeoutMs = 60000 } = {}) {
  const token = crypto.randomBytes(8).toString('hex');
  const dir = path.join(os.tmpdir(), `ramanujan-f0-${name}-${token}`);
  fs.mkdirSync(dir, { recursive: true });
  const results = [];
  try {
    for (const s of sentinels) {
      const inputPath = path.join(dir, s.file);
      fs.writeFileSync(inputPath, s.source, 'utf8');
      let obs;
      try {
        obs = exec(command.path, [...(command.baseArgs || []), inputPath], { timeoutMs, cwd: dir });
      } catch (e) {
        if (e instanceof PhaseFProbeError && e.unreachable) {
          return quarantine(name, TOOL_CLASS.DETERMINISTIC, results, `${name} is UNREACHABLE at ${command.path}: ${e.message}`);
        }
        throw e;
      }
      const accepted = Boolean(s.accept(obs)) && !obs.timedOut;
      results.push({ label: s.label, accepted, observation: { exitCode: obs.exitCode, timedOut: obs.timedOut, stdout: obs.stdout.slice(0, 400) } });
      if (!accepted) {
        return quarantine(name, TOOL_CLASS.DETERMINISTIC, results, `${name} FAILED sentinel ${s.label} (${s.describe})`);
      }
    }
    return Object.freeze({ name, class: TOOL_CLASS.DETERMINISTIC, status: PROBE_STATUS.TRUSTED, trusted: true, disables: [], reason: null, results: Object.freeze(results) });
  } finally {
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* best-effort */ }
  }
}

function quarantine(name, klass, results, reason, extra = {}) {
  const disables = klass === TOOL_CLASS.PROBABILISTIC ? [PLAUSIBILITY_CORROBORATED] : [];
  return Object.freeze({
    name,
    class: klass,
    status: PROBE_STATUS.QUARANTINED,
    trusted: false,
    disables: Object.freeze(disables),
    reason,
    results: Object.freeze(results),
    ...extra,
  });
}

// ---------------------------------------------------------------------------
// PROBABILISTIC sentinels (cross-family ollama).
// ---------------------------------------------------------------------------

/** Normalize a model's free-text answer to a YES / NO / UNPARSEABLE verdict. */
export function parseVerdict(text) {
  if (typeof text !== 'string') return 'UNPARSEABLE';
  const t = text.toUpperCase();
  const yesRe = /\b(YES|TRUE|VALID|CORRECT|SOUND|HOLDS)\b/g;
  const noRe = /\b(NO|FALSE|INVALID|INCORRECT|WRONG|UNSOUND|FLAWED|FAILS)\b/g;
  let lastYes = -1;
  let lastNo = -1;
  let m;
  while ((m = yesRe.exec(t))) lastYes = m.index;
  while ((m = noRe.exec(t))) lastNo = m.index;
  if (lastYes < 0 && lastNo < 0) return 'UNPARSEABLE';
  if (lastYes >= 0 && lastNo < 0) return 'YES';
  if (lastNo >= 0 && lastYes < 0) return 'NO';
  return lastYes > lastNo ? 'YES' : 'NO'; // the decisive (last-stated) token wins
}

/**
 * The cross-family integrity battery. `expect` is the CORRECT verdict the panel must return.
 *  - knownTrue  -> YES  (a true sentence the model must affirm)
 *  - knownFalse -> NO   (a false sentence the model must reject)
 *  - proofJudging -> NO (a planted plausible-but-wrong proof the panel MUST reject)
 */
export const CROSS_FAMILY_BATTERY = Object.freeze({
  knownTrue: Object.freeze({
    id: 'known-true',
    expect: 'YES',
    prompt: 'Answer with exactly one word, YES or NO. Is the following statement true? "7 is a prime number."',
  }),
  knownFalse: Object.freeze({
    id: 'known-false',
    expect: 'NO',
    prompt: 'Answer with exactly one word, YES or NO. Is the following statement true? "9 is a prime number."',
  }),
  proofJudging: Object.freeze({
    id: 'proof-judging',
    expect: 'NO',
    prompt:
      'You are a strict proof referee. A "proof" claims to show that ALL positive integers are equal. ' +
      '"Proof: Let max(a,b) denote the larger of a and b. We show by induction on n that if max(a,b)=n then a=b. ' +
      'Base n=1: if max(a,b)=1 then a=b=1. Step: assume true for n; if max(a,b)=n+1 then max(a-1,b-1)=n so by the ' +
      'hypothesis a-1=b-1, hence a=b. Therefore all positive integers are equal." ' +
      'This proof is FLAWED (the base case and the a-1,b-1 step are invalid). ' +
      'Answer with exactly one word: is this a VALID proof? Reply VALID or INVALID.',
  }),
});

/**
 * Probe a single cross-family model. `generate` is async (prompt) -> string (the model's answer
 * text). Runs N=CROSS_FAMILY_TRIALS deterministic-decoding trials on known-true + known-false (each
 * must be 5/5 correct) PLUS one proof-judging trial (must reject). ANY shortfall => QUARANTINED from
 * the PLAUSIBILITY-CORROBORATED path. Returns the per-model probe result.
 */
export async function probeCrossFamilyModel(modelName, generate, { trials = CROSS_FAMILY_TRIALS } = {}) {
  if (typeof generate !== 'function') throw new PhaseFProbeError('probeCrossFamilyModel requires an async generate(prompt) function');
  const results = [];

  for (const battery of [CROSS_FAMILY_BATTERY.knownTrue, CROSS_FAMILY_BATTERY.knownFalse]) {
    let correct = 0;
    const verdicts = [];
    for (let i = 0; i < trials; i += 1) {
      const verdict = parseVerdict(await generate(battery.prompt));
      verdicts.push(verdict);
      if (verdict === battery.expect) correct += 1;
    }
    const accepted = correct === trials;
    results.push({ label: `${modelName}:${battery.id}`, accepted, observation: { correct, trials, verdicts } });
    if (!accepted) {
      return quarantine(modelName, TOOL_CLASS.PROBABILISTIC, results, `${modelName} FAILED the ${battery.id} battery (${correct}/${trials}; need ${trials}/${trials})`);
    }
  }

  // The proof-JUDGING sentinel: the panel MUST reject the plausible-but-wrong proof.
  const pj = CROSS_FAMILY_BATTERY.proofJudging;
  const pjVerdict = parseVerdict(await generate(pj.prompt));
  const pjAccepted = pjVerdict === pj.expect; // expect NO (i.e. INVALID)
  results.push({ label: `${modelName}:${pj.id}`, accepted: pjAccepted, observation: { verdict: pjVerdict, expect: pj.expect } });
  if (!pjAccepted) {
    return quarantine(modelName, TOOL_CLASS.PROBABILISTIC, results, `${modelName} ACCEPTED a plausible-but-wrong proof (proof-judging sentinel) => QUARANTINED from ${PLAUSIBILITY_CORROBORATED}`);
  }

  return Object.freeze({ name: modelName, class: TOOL_CLASS.PROBABILISTIC, status: PROBE_STATUS.TRUSTED, trusted: true, disables: [], reason: null, results: Object.freeze(results) });
}

// ---------------------------------------------------------------------------
// Cross-family PRIMARY: Gemini via the agy CLI (frontier, generator-INDEPENDENT of Claude).
//
// 2026-07 substrate move: the bare Gemini HTTP API (generativelanguage.googleapis.com) is DEAD on this
// host ($0/429) and its API-style model id is a PHANTOM. The cross-family PRIMARY is now the
// Antigravity CLI `agy`, reached through the PROVEN transport in <path>
// (pinned as tools.gemini.driver_ref): `agy -p` under the agy LOGIN (no API key), addressed by a real
// LABEL ("Gemini 3.1 Pro (High)"), with SERVED-MODEL ATTESTATION (served==requested) so a silent Flash
// substitution is caught, and a NO-SHELL steer so no PowerShell window pops.
//
// createGeminiGenerate now returns an agy-backed `async (prompt)->string`. Its CONTRACT is unchanged so
// the rest of the substrate (probeCrossFamily, driveCrossFamily, frontierCanarySelfTest) is untouched:
// input a prompt string, resolve the model's answer text, and on ANY failure throw a typed
// PhaseFProbeError carrying a `failClass` (so the quarantine->ollama-fallback path still fires). The
// FAST `node --test` gate stays hermetic + spawns NO agy: it injects `runGemini` (a
// (prompt,label)=>{text,rec} stub); only the LIVE tool lane dynamic-imports the driver_ref and spawns
// the env-gated (`CRUCIBLE_AGENT_LIVE=1`) `agy -p`. buildGeminiRequest/parseGeminiResponse below are
// RETAINED as pure back-compat shaping helpers (+ their unit tests) but are no longer on the live path.
// ---------------------------------------------------------------------------

/** Build the `{url, init}` for a Gemini generateContent request (key ONLY in the x-goog-api-key header). BACK-COMPAT ONLY. */
export function buildGeminiRequest({ prompt, model, apiKey, baseUrl = GEMINI_BASE_URL, temperature = 0 }) {
  const body = {
    contents: [{ role: 'user', parts: [{ text: prompt }] }],
    generationConfig: { temperature },
  };
  return {
    url: `${baseUrl}/models/${model}:generateContent`,
    init: {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-goog-api-key': apiKey ?? '' },
      body: JSON.stringify(body),
    },
  };
}

/** Concatenate the text parts of a Gemini response (empty string on miss). */
export function parseGeminiResponse(data) {
  const parts = data && data.candidates && data.candidates[0] && data.candidates[0].content && data.candidates[0].content.parts;
  if (!Array.isArray(parts)) return '';
  return parts.map((p) => (p && p.text) || '').join('').trim();
}

/** Defensive: NEVER let a secret key surface in an error/log line (key-redaction, §v3.1 network safety). */
function redactKey(text, key) {
  const s = String(text == null ? '' : text);
  if (!key) return s;
  return s.split(key).join('[REDACTED_GEMINI_KEY]');
}

/**
 * Map an agy driver `rec.status` (from gemini-cli.mjs parseGeminiCliFrames) to a fail-closed
 * GEMINI_FAIL_CLASS. EVERY non-success status quarantines Gemini and falls the probe back to ollama —
 * the class is for honest reporting, not control flow. The load-bearing new one is ATTESTATION: agy
 * served a DIFFERENT model than requested (`model_substituted`) or could not attest what it served
 * (`unattested_model`) — the silent-Flash-degrade tripwire that must NEVER pass as a frontier verdict.
 */
export function agyStatusToFailClass(status) {
  switch (status) {
    case 'model_substituted':
    case 'unattested_model':
      return GEMINI_FAIL_CLASS.ATTESTATION;
    case 'timeout':
    case 'cli_error':
    case 'transport-error':
      return GEMINI_FAIL_CLASS.NETWORK;
    case 'no_reply':
      return GEMINI_FAIL_CLASS.BAD_RESPONSE;
    default:
      return GEMINI_FAIL_CLASS.HTTP_ERROR;
  }
}

/**
 * Build the agy-backed cross-family `generate(prompt) -> string` for the F0 probe / driver. The agy
 * transport (<path> pinned as geminiSpec.driver_ref) is reached ONLY when
 * the returned function is invoked; the FAST gate injects `runGemini` so NO agy process spawns and NO
 * cross-repo import happens. Fail-closed enumeration is preserved as typed PhaseFProbeError(failClass):
 * ATTESTATION (served!=requested — the silent-Flash tripwire), NETWORK (transport/timeout/cli error),
 * BAD_RESPONSE (no reply), HTTP_ERROR (unclassified). Served-model attestation lives in the agy driver
 * (served==requested) — a returned string here is a verdict from the ATTESTED requested LABEL.
 *
 * @param {object} geminiSpec  manifest tools.gemini (model LABEL + driver_ref)
 * @param {object} [o]
 * @param {object} [o.env=process.env]
 * @param {Function}[o.runGemini]  injected transport `(prompt,label)=>Promise<{text,rec}>` (fast tier);
 *                                 omit to dynamic-import driver_ref's env-gated live `agy -p` runner.
 * @param {number} [o.timeoutMs]
 * @returns {(prompt:string)=>Promise<string>}
 */
export function createGeminiGenerate(geminiSpec = {}, { env = process.env, runGemini, timeoutMs } = {}) {
  const model = geminiSpec.model || DEFAULT_FRONTIER_LABEL;
  const reqTimeout = timeoutMs || geminiSpec.request_timeout_ms || 60000;
  const driverRef = geminiSpec.driver_ref || DEFAULT_AGY_DRIVER_REF;

  // Resolve the agy transport lazily + once. `runGemini` (injected) short-circuits the dynamic import
  // so the fast gate never touches the driver or spawns agy; the LIVE lane imports the pinned driver
  // and builds the env-gated (CRUCIBLE_AGENT_LIVE=1) `agy -p` runner in a read-only (refuter) posture.
  let runnerPromise = null;
  function resolveRunner() {
    if (typeof runGemini === 'function') return Promise.resolve(runGemini);
    if (!runnerPromise) {
      runnerPromise = import(pathToFileURL(driverRef).href).then((mod) => {
        if (typeof mod.defaultRunGeminiCli !== 'function') {
          throw new PhaseFProbeError(`agy driver ${driverRef} does not export defaultRunGeminiCli`);
        }
        return (prompt, label) => mod.defaultRunGeminiCli(prompt, label, { env, model, role: 'refuter', timeoutMs: reqTimeout });
      });
    }
    return runnerPromise;
  }

  return async function geminiGenerate(prompt) {
    const runner = await resolveRunner();
    let out;
    try {
      out = await runner(prompt, 'ramanujan-cross-family');
    } catch (e) {
      // A thrown error from the live seam (e.g. the seam disabled without CRUCIBLE_AGENT_LIVE) is an
      // unreachable-transport condition — fail closed as NETWORK so the probe quarantines->falls back.
      throw new PhaseFProbeError(`gemini (agy) transport error: ${e && e.message}`, { failClass: GEMINI_FAIL_CLASS.NETWORK });
    }
    const rec = out && out.rec;
    if (!rec || rec.ok === false) {
      const failClass = agyStatusToFailClass(rec && rec.status);
      throw new PhaseFProbeError(
        `gemini (agy) unavailable [${rec ? rec.status : 'no-rec'}] (requested="${model}" served="${(rec && rec.model_served) ?? 'unattested'}")`,
        { failClass, served: (rec && rec.model_served) ?? null, requested: model },
      );
    }
    return typeof out.text === 'string' ? out.text : '';
  };
}

/**
 * The FRONTIER-CANARY SELF-TEST (§v3.1, load-bearing). The frontier CORROBORATED rung is enabled ONLY
 * after a real Gemini round-trip whose INDEPENDENT RE-RUN reproduces the normalized VERDICT (verdict
 * level — NEVER an exact answer/transcript hash), on a known-answer prompt. Until this passes (e.g.
 * while Gemini is 429), the cross-family lift stays on the FALLBACK tier. Returns
 *   { passed, verdictA, verdictB, reproducible, correct, expect }.
 * A network/credit error PROPAGATES (its typed failClass) so the caller quarantines→falls back.
 */
export async function frontierCanarySelfTest(generate, { prompt = CROSS_FAMILY_BATTERY.knownTrue.prompt, expect = CROSS_FAMILY_BATTERY.knownTrue.expect } = {}) {
  const verdictA = parseVerdict(await generate(prompt));
  const verdictB = parseVerdict(await generate(prompt)); // an INDEPENDENT re-run of the SAME prompt
  const reproducible = verdictA === verdictB && verdictA !== 'UNPARSEABLE';
  const correct = verdictA === expect;
  return { passed: reproducible && correct, verdictA, verdictB, reproducible, correct, expect };
}

/**
 * Run the per-class integrity probe over the CROSS-FAMILY class with the v3 substrate ordering:
 * the PRIMARY (frontier Gemini) is probed FIRST — a frontier-canary self-test (verdict-reproducible)
 * THEN the full 5/5 + proof-judging battery. If Gemini passes => the lift is enabled at tier=frontier
 * (rung CORROBORATED). If Gemini is QUARANTINED for ANY fail-closed reason (key-missing / 401|403 /
 * 429 / network / a missed sentinel / accepting the planted wrong proof), the probe FALLS BACK to the
 * ollama panel; if every fallback model passes its sentinels => tier=fallback (rung
 * PLAUSIBILITY-CORROBORATED). If the fallback ALSO fails => the cross-family lift HARD-FAULTS to
 * CONJECTURAL (tier=none) — the system NEVER runs with an un-probed cross-family backend.
 *
 * Backends are injected so the FAST gate never touches the network:
 *   - `geminiGenerate`   : async (prompt)->string for the PRIMARY (default: createGeminiGenerate(spec,{env})).
 *   - `ollamaGenerateFor`: (modelName)->async (prompt)->string for each FALLBACK model.
 * Returns a frozen report: { crossFamilyTrusted, tier, activeBackend, activeFamily, rung, gemini, fallback }.
 */
export async function probeCrossFamily(manifest, { geminiGenerate, ollamaGenerateFor, env = process.env, trials = CROSS_FAMILY_TRIALS } = {}) {
  const geminiSpec = (manifest.tools && manifest.tools.gemini) || {};
  const ollamaSpec = (manifest.tools && manifest.tools.ollama) || {};

  // ---- PRIMARY: frontier Gemini (self-test FIRST, then the full sentinel battery). ----
  let gemini;
  try {
    const gen = geminiGenerate || createGeminiGenerate(geminiSpec, { env });
    const selfTest = await frontierCanarySelfTest(gen);
    if (!selfTest.passed) {
      gemini = quarantine(
        'gemini',
        TOOL_CLASS.PROBABILISTIC,
        [{ label: 'gemini:frontier-canary-self-test', accepted: false, observation: selfTest }],
        `gemini frontier-canary self-test FAILED (verdict not reproduced/correct: ${JSON.stringify(selfTest)}) — frontier rung NOT enabled`,
        { failClass: 'SELFTEST_FAILED', selfTest },
      );
    } else {
      const battery = await probeCrossFamilyModel(geminiSpec.model || 'gemini', gen, { trials });
      gemini = battery.trusted
        ? Object.freeze({ ...battery, selfTest, family: FRONTIER_FAMILY })
        : Object.freeze({ ...battery, selfTest });
    }
  } catch (e) {
    const failClass = (e && e.failClass) || 'ERROR';
    gemini = quarantine(
      'gemini',
      TOOL_CLASS.PROBABILISTIC,
      [],
      `gemini PRIMARY fail-closed [${failClass}]: ${e && e.message}`,
      { failClass },
    );
  }

  if (gemini.trusted) {
    return Object.freeze({
      crossFamilyTrusted: true,
      tier: CROSS_FAMILY_TIER.FRONTIER,
      activeBackend: 'gemini',
      activeFamily: FRONTIER_FAMILY,
      rung: CORROBORATED,
      gemini,
      fallback: null,
    });
  }

  // ---- QUARANTINE -> FALLBACK: the ollama panel must itself pass its sentinels. ----
  const models = Array.isArray(ollamaSpec.models) ? ollamaSpec.models : [];
  const fallback = {};
  let allFallbackTrusted = models.length > 0;
  for (const m of models) {
    const gen = ollamaGenerateFor ? ollamaGenerateFor(m.name) : null;
    if (typeof gen !== 'function') {
      fallback[m.name] = quarantine(m.name, TOOL_CLASS.PROBABILISTIC, [], `no fallback generate available for ${m.name}`);
      allFallbackTrusted = false;
      continue;
    }
    const r = await probeCrossFamilyModel(m.name, gen, { trials });
    fallback[m.name] = r;
    if (!r.trusted) allFallbackTrusted = false;
  }

  if (allFallbackTrusted) {
    return Object.freeze({
      crossFamilyTrusted: true,
      tier: CROSS_FAMILY_TIER.FALLBACK,
      activeBackend: 'ollama',
      activeFamily: null, // a >=2-family panel, not a single family
      rung: PLAUSIBILITY_CORROBORATED,
      gemini,
      fallback,
    });
  }

  // ---- BOTH failed: HARD-FAULT to CONJECTURAL (no probed cross-family backend). ----
  return Object.freeze({
    crossFamilyTrusted: false,
    tier: CROSS_FAMILY_TIER.NONE,
    activeBackend: null,
    activeFamily: null,
    rung: CONJECTURAL,
    hardFault: true,
    reason: 'cross-family HARD-FAULT: Gemini PRIMARY quarantined AND the ollama FALLBACK failed its sentinel — no probed cross-family backend (CONJECTURAL, never a silent same-family/no-op pass)',
    gemini,
    fallback,
  });
}

// ---------------------------------------------------------------------------
// Persistent ollama server infra (tool-lane only — never invoked at import time).
// ---------------------------------------------------------------------------

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** HTTP GET base_url/api/version — used to poll the server for readiness. */
async function serverReachable(baseUrl, versionPath = '/api/version') {
  try {
    const res = await fetch(`${baseUrl}${versionPath}`, { method: 'GET' });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Start a PERSISTENT ollama server (`ollama serve`) and wait until it answers /api/version. If a
 * server is already listening, reuse it (preExisting=true) — warmUp's fresh-load assertion still
 * guards against an orphan masking a cold-start. Registers process exit/signal handlers so the child
 * is killed even on a crash. Returns { child|null, baseUrl, preExisting }.
 */
export async function startOllamaServer(ollamaSpec, { readyTimeoutMs } = {}) {
  const srv = ollamaSpec.server || {};
  const baseUrl = srv.base_url || 'http://127.0.0.1:11434';
  const timeout = readyTimeoutMs || srv.ready_timeout_ms || 60000;

  if (await serverReachable(baseUrl, srv.version_path)) {
    return { child: null, baseUrl, preExisting: true };
  }

  const child = spawn(ollamaSpec.path, srv.serve_args || ['serve'], {
    stdio: 'ignore',
    windowsHide: true,
    detached: false,
  });
  child.on('error', () => { /* surfaced via the readiness poll below */ });

  const handle = { child };
  registerTeardown(handle);

  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await serverReachable(baseUrl, srv.version_path)) {
      return { child, baseUrl, preExisting: false, _teardown: handle };
    }
    await sleep(500);
  }
  await stopOllamaServer({ child });
  throw new PhaseFProbeError(`ollama server did not become ready within ${timeout}ms at ${baseUrl}`);
}

const _teardownHandles = new Set();
let _teardownHooked = false;
function registerTeardown(handle) {
  _teardownHandles.add(handle);
  if (_teardownHooked) return;
  _teardownHooked = true;
  const killAll = () => {
    for (const h of _teardownHandles) {
      try { killTree(h.child); } catch { /* best-effort */ }
    }
  };
  process.once('exit', killAll);
  process.once('SIGINT', () => { killAll(); process.exit(130); });
  process.once('SIGTERM', () => { killAll(); process.exit(143); });
}

/** Kill a child process TREE. On win32 use `taskkill /T /F` so the whole ollama tree dies. */
function killTree(child) {
  if (!child || child.killed || typeof child.pid !== 'number') return;
  if (process.platform === 'win32') {
    try {
      execFileSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true, timeout: 15000 });
    } catch {
      try { child.kill('SIGKILL'); } catch { /* best-effort */ }
    }
  } else {
    try { process.kill(-child.pid, 'SIGKILL'); } catch { try { child.kill('SIGKILL'); } catch { /* best-effort */ } }
  }
}

/** Stop the persistent server, killing the whole process tree (idempotent). */
export async function stopOllamaServer(handle) {
  if (!handle) return;
  const child = handle.child || handle;
  killTree(child);
  for (const h of _teardownHandles) if (h.child === child) _teardownHandles.delete(h);
}

/**
 * WARM UP a model and ASSERT a FRESH-LOAD signal (a real model load_duration), not merely a 200-OK,
 * so an orphaned already-warm server cannot mask a cold-start regression. To force a fresh load it
 * first unloads the model (a generate with keep_alive:0), then loads it and checks load_duration.
 * Returns { model, loaded:true, load_duration_ns }.
 */
export async function warmUp(ollamaSpec, modelName, baseUrl) {
  const srv = ollamaSpec.server || {};
  const url = `${baseUrl}${srv.generate_path || '/api/generate'}`;
  const freshLoadMinNs = Number(srv.fresh_load_min_ns || 50000000);

  // Force an unload so the warm-up is genuinely a cold load.
  try {
    await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model: modelName, prompt: '', keep_alive: 0 }),
    });
  } catch { /* best-effort unload */ }
  await sleep(500);

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      model: modelName,
      prompt: 'ready',
      stream: false,
      keep_alive: srv.keep_alive || '30m',
      options: ollamaSpec.deterministic_decoding,
    }),
  });
  if (!res.ok) throw new PhaseFProbeError(`warm-up generate failed for ${modelName}: HTTP ${res.status}`);
  const json = await res.json();
  const loadNs = Number(json.load_duration || 0);
  if (!(loadNs >= freshLoadMinNs)) {
    throw new PhaseFProbeError(
      `warm-up did NOT observe a fresh model load for ${modelName} (load_duration=${loadNs}ns < ${freshLoadMinNs}ns) — an orphaned server may be masking a cold-start regression`,
      { load_duration_ns: loadNs },
    );
  }
  return { model: modelName, loaded: true, load_duration_ns: loadNs };
}

/**
 * Build the deterministic-decoding generate(prompt) the cross-family probe uses, bound to the
 * keep_alive'd persistent server (so each call reuses the warm model — NO per-call reload).
 */
export function createOllamaGenerate(ollamaSpec, modelName, baseUrl) {
  const srv = ollamaSpec.server || {};
  const url = `${baseUrl}${srv.generate_path || '/api/generate'}`;
  return async function generate(prompt) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        model: modelName,
        prompt,
        stream: false,
        keep_alive: srv.keep_alive || '30m',
        options: ollamaSpec.deterministic_decoding,
      }),
    });
    if (!res.ok) throw new PhaseFProbeError(`ollama generate failed for ${modelName}: HTTP ${res.status}`);
    const json = await res.json();
    return typeof json.response === 'string' ? json.response : '';
  };
}

// ---------------------------------------------------------------------------
// Top-level orchestration (the gate's report).
// ---------------------------------------------------------------------------

/**
 * Run the per-class integrity probe over the manifest's DETERMINISTIC tools against the REAL
 * executables (lean, z3) by absolute path. (The probabilistic cross-family probe is driven separately
 * because it needs the persistent server + warm-up — see probeCrossFamilyModel + the server infra.)
 * Returns { allTrusted, tools:{ name -> result } }.
 */
export function runDeterministicProbe(manifest, { exec = runExecutable } = {}) {
  const tools = manifest.tools || {};
  const out = {};
  out.lean = probeDeterministic('lean', { path: tools.lean.path, baseArgs: [] }, LEAN_SENTINELS, { exec });
  out.z3 = probeDeterministic('z3', { path: tools.z3.path, baseArgs: [] }, Z3_SENTINELS, { exec });
  return { allTrusted: Object.values(out).every((r) => r.trusted), tools: out };
}
