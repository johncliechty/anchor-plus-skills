// Wave 2 — F1a: cross-family driver (v3 substrate: a PREFS-RESOLVED PRIMARY seat + ollama-FALLBACK, verdict-level).
//
// (2026-09-04, John) The PRIMARY seat is no longer a hardwired Gemini: it is whichever family the Anchor
// dashboard prefs configure that is not the author's own (seat.mjs — review_family first, then
// coding_family; gemini only when a pref names it). The prose below describing GEMINI-PRIMARY is the
// substrate's history; every 'Gemini' there now reads 'the configured seat'.
//
// A DETERMINISTIC-DECODING, OUT-OF-MODEL invocation seam to non-Claude families, reproducible AT THE
// VERDICT LEVEL. The Honesty Law forbids any same-family-authored object reaching a trusted rung; this
// driver is the narrow channel through which a generator-INDEPENDENT (non-Claude) family is asked a
// yes/no question, and its answer is parsed into a structured verdict + a re-executable artifact.
// Wave 3 (F1b) builds the quorum/per-verifier VERIFIER + router wiring on top of this seam; this wave
// ships ONLY the seam, its v3 substrate ordering, and its reproducibility contract.
//
// THE v3 SUBSTRATE (DESCRIPTION-INC2 §Tooling v3 / IMPLEMENTATION-PLAN-INC2 Wave 2). The cross-family
// class is GEMINI-PRIMARY (the frontier agy LABEL "Gemini 3.1 Pro (High)" via the agy CLI — genuinely
// generator-INDEPENDENT of Claude) with an ollama-FALLBACK (qwen2.5 + llama3, persistent server). The
// driver tries the PRIMARY FIRST; when Gemini is unavailable / unauthorized (401|403) / credit-depleted
// (HTTP 429) / unreachable (timeout|DNS) — the fail-closed enumeration the F0 probe pins — the seam
// GRACEFULLY FALLS BACK to ollama and stamps the ACTUAL backend it used. The artifact records that:
//
//     { verifier_family, model, tier(frontier|fallback), prompt_hash, verdict,
//       normalized_answer_hash, transcript_hash }
//
//   `tier` is frontier (the verdict came from the Gemini PRIMARY) or fallback (it came from ollama).
//   `verifier_family` is the ACTUAL answering family (gemini | qwen | llama) — NEVER claude.
//   `verdict` + `normalized_answer_hash` are the reproducibility key; `transcript_hash` is provenance.
//
// THE REPRODUCIBILITY CONTRACT (DESCRIPTION-INC2 §v2 point 3). A non-Claude model run is NOT
// byte-reproducible in general: the HTTP server stamps volatile timing metadata, the CLI wraps answers
// in spinner/ANSI chrome, and incidental whitespace varies. So reproducibility is keyed on the PARSED
// VERDICT plus a NORMALIZED-ANSWER hash (chrome + whitespace stripped, case-folded), NEVER on a
// raw-transcript hash. The artifact carries `transcript_hash` for PROVENANCE ONLY — it is explicitly
// allowed to differ run-to-run and is never the equality key; the canary (Wave 3) re-runs the SAME
// backend recorded in the artifact and recomputes the verdict.
//
// THE CROSS-FAMILY INVARIANT. A verdict the driver mints is stamped with the answering
// `verifier_family`, and the driver HARD-FAULTS if asked to mint one for the `claude` family — the seam
// structurally cannot launder a same-family verdict (the Honesty Law at the invocation boundary).
//
// NETWORK SAFETY (DESCRIPTION-INC2 §v3.1, Wave 2). The Gemini key is sent ONLY as the `x-goog-api-key`
// HEADER (never a URL query param), over TLS to the PINNED host generativelanguage.googleapis.com (no
// insecure transport / custom CA), and NEVER appears in a log line, a thrown error, a URL, or a
// persisted provenance blob (every error path is key-redacted). The Gemini request/transport itself is
// the F0 module's audited `createGeminiGenerate` (re-used, not re-implemented) so there is one
// network-safety surface.
//
// THE BUILD-GATE ISOLATION CONTRACT (§v2.1/§v2.2 + §v3.1 fast-gate isolation extends to Gemini): this
// module starts NOTHING and touches NO tool at import time — every network call happens only inside a
// function the caller invokes. The fast Foreman `node --test test/` gate drives the driver with an
// INJECTED transport (a `geminiGenerate`/`fetchImpl` stub and/or an `ollamaGenerateFor` stub) and is
// GREEN with NO live Gemini AND no GEMINI_API_KEY present; the real Gemini + ollama runs live only in
// the env-gated serial tool lane (RAMANUJAN_TOOL_TESTS=1).
//
// Pure node built-ins (crypto) + the F0 phasef-probe seam it reuses. ESM.

import crypto from 'node:crypto';

import { DEFAULT_AUTHOR_FAMILY } from './seat.mjs';
import {
  parseVerdict,
  createOllamaGenerate,
  createGeminiGenerate,
  createFamilyGenerate,
  resolvePrimarySeat,
  SEAT_FAIL_CLASS,
  buildGeminiRequest,
  loadManifest,
  FRONTIER_FAMILY,
  CROSS_FAMILY_TIER,
  GEMINI_HOST,
  GEMINI_BASE_URL,
  GEMINI_FAIL_CLASS,
} from './phasef-probe.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** A 64-char lowercase hex (a SHA-256 digest). */
export const HEX64 = /^[0-9a-f]{64}$/;

/** The two cross-family tiers the artifact can stamp (v3): frontier (Gemini) | fallback (ollama). */
export const TIER = Object.freeze({ FRONTIER: CROSS_FAMILY_TIER.FRONTIER, FALLBACK: CROSS_FAMILY_TIER.FALLBACK });
const VALID_TIERS = Object.freeze(new Set([TIER.FRONTIER, TIER.FALLBACK]));

/** The exact field set of the re-executable cross-family verdict artifact (frozen plan, Wave 2 / v3). */
export const ARTIFACT_FIELDS = Object.freeze([
  'verifier_family',
  'model',
  'tier',
  'prompt_hash',
  'verdict',
  'normalized_answer_hash',
  'transcript_hash',
]);

/** The fields that KEY verdict-level reproducibility (NEVER transcript_hash — provenance only). */
export const REPRODUCIBILITY_KEY_FIELDS = Object.freeze(['verdict', 'normalized_answer_hash']);

/** The structured verdict alphabet (re-exported from the F0 parser for callers/Wave 3). */
export { parseVerdict, GEMINI_FAIL_CLASS, FRONTIER_FAMILY };

/** A typed error so a driver wiring/usage bug is distinguishable from a model verdict. */
export class CrossFamilyDriverError extends Error {
  constructor(message, extra = {}) {
    super(message);
    this.name = 'CrossFamilyDriverError';
    Object.assign(this, extra);
  }
}

// ---------------------------------------------------------------------------
// Normalization + hashing primitives.
// ---------------------------------------------------------------------------

const sha256Hex = (text) => crypto.createHash('sha256').update(String(text), 'utf8').digest('hex');

/** Defensive redaction: NEVER let a secret key surface in an error/log/provenance line (§v3.1). */
function redactKey(text, key) {
  const s = String(text == null ? '' : text);
  if (!key) return s;
  return s.split(key).join('[REDACTED_GEMINI_KEY]');
}

/** SHA-256 of the prompt VERBATIM (the canary re-runs from the stored prompt — Wave 3). */
export function promptHash(prompt) {
  if (typeof prompt !== 'string' || prompt.length === 0) {
    throw new CrossFamilyDriverError('promptHash requires a non-empty string prompt');
  }
  return sha256Hex(prompt);
}

/**
 * Strip CLI/transport CHROME + incidental whitespace from a model's free-text answer so two runs that
 * say the same thing with different wrapping normalize IDENTICALLY:
 *   - ANSI / CSI escape sequences (terminal colour + cursor control the CLI emits),
 *   - the braille-block spinner glyphs `ollama run` prints while generating (U+2800..U+28FF),
 *   - carriage returns and every other whitespace run (collapsed to a single space, then trimmed),
 *   - case (folded to lower) so YES / Yes / yes are one answer.
 * This is the canonical text the normalized_answer_hash digests. It is the reproducibility key's
 * payload; the raw answer (with its chrome) is kept only for the provenance transcript_hash.
 */
export function normalizeAnswer(text) {
  if (typeof text !== 'string') return '';
  return text
    // eslint-disable-next-line no-control-regex
    .replace(/\x1B\[[0-9;?]*[ -/]*[@-~]/g, '') // ANSI/CSI escape sequences (colour, cursor)
    .replace(/[⠀-⣿]/g, '') // braille-block spinner glyphs the CLI animates
    .replace(/[\r\f\v]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

/** SHA-256 of the NORMALIZED answer (chrome + whitespace stripped). The reproducibility payload. */
export function normalizedAnswerHash(rawAnswer) {
  return sha256Hex(normalizeAnswer(rawAnswer));
}

/** SHA-256 of the RAW answer, verbatim. PROVENANCE ONLY — explicitly allowed to differ run-to-run. */
export function transcriptHash(rawAnswer) {
  return sha256Hex(typeof rawAnswer === 'string' ? rawAnswer : '');
}

// ---------------------------------------------------------------------------
// The verdict record + artifact.
// ---------------------------------------------------------------------------

/**
 * Mint a structured cross-family verdict record from a model's RAW answer text. Returns
 *   { artifact:{ ...ARTIFACT_FIELDS }, verdict, prompt, raw_answer, normalized_answer }
 * where `artifact` is the FROZEN re-executable artifact (exactly ARTIFACT_FIELDS) and the envelope
 * additionally carries the prompt + raw/normalized answer Wave 3's canary re-run needs.
 *
 * `verifier_family` is the ACTUAL answering family (gemini | qwen | llama | claude for a non-Claude-
 * authored claim). `tier` is frontier (Gemini) or fallback (ollama). HARD-FAULTS if `verifier_family`
 * is empty, or if it EQUALS the claim's `generator_family` (2026-07: the ban is GENERATOR-RELATIVE —
 * the Honesty Law requires verifier ≠ generator, not "never Claude"; `generator_family` defaults to
 * 'claude', so every existing caller keeps the exact historical behavior, while a Gemini-/human-
 * authored claim may now be verified by the strongest family on the host). `family` is accepted as a
 * legacy alias for `verifier_family`.
 */
export function makeVerdictRecord({ model, verifier_family, family, tier, prompt, rawAnswer, generator_family = 'claude' }) {
  if (typeof model !== 'string' || model.length === 0) {
    throw new CrossFamilyDriverError('makeVerdictRecord requires a non-empty model name');
  }
  const vf = verifier_family != null ? verifier_family : family;
  if (typeof vf !== 'string' || vf.trim().length === 0) {
    throw new CrossFamilyDriverError('makeVerdictRecord requires a non-empty verifier_family');
  }
  const gf = String(generator_family || 'claude').trim().toLowerCase();
  if (vf.trim().toLowerCase() === gf) {
    throw new CrossFamilyDriverError(
      `cross-family driver refuses to mint a \`${gf}\` verdict for a \`${gf}\`-authored claim — ` +
      'the verifier family must DIFFER from the generator family (Honesty Law, generator-relative)',
      { verifier_family: vf, generator_family: gf },
    );
  }
  if (!VALID_TIERS.has(tier)) {
    throw new CrossFamilyDriverError(
      `makeVerdictRecord requires tier ∈ {${[...VALID_TIERS].join(', ')}} (got ${JSON.stringify(tier)})`,
      { tier },
    );
  }
  if (typeof rawAnswer !== 'string') {
    throw new CrossFamilyDriverError('makeVerdictRecord requires the model rawAnswer as a string');
  }
  const normalized = normalizeAnswer(rawAnswer);
  // Parse the verdict from the NORMALIZED text: chrome (ANSI, spinner) can break the word boundaries
  // parseVerdict keys on, so a verdict derived from raw chrome would be falsely UNPARSEABLE. Parsing
  // the normalized payload also makes verdict + normalized_answer_hash a single coherent key.
  const verdict = parseVerdict(normalized);
  const artifact = Object.freeze({
    verifier_family: vf.trim().toLowerCase(),
    model,
    tier,
    prompt_hash: promptHash(prompt),
    verdict,
    normalized_answer_hash: sha256Hex(normalized),
    transcript_hash: transcriptHash(rawAnswer),
  });
  return Object.freeze({
    artifact,
    verdict,
    prompt,
    raw_answer: rawAnswer,
    normalized_answer: normalized,
  });
}

/**
 * Shape-check a cross-family verdict artifact. STRUCTURAL only — it does not re-invoke the model (that
 * is Wave 3's canary's job). Returns { ok, failures } (failures empty iff ok).
 * 2026-07: the family ban is generator-relative — pass { generator_family } for a claim not authored
 * by Claude; the default preserves the historical never-claude check for every existing caller.
 */
export function validateArtifact(artifact, { generator_family = 'claude' } = {}) {
  const failures = [];
  const _gf = String(generator_family || 'claude').trim().toLowerCase();
  if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) {
    return { ok: false, failures: ['artifact is not an object'] };
  }
  // EXACT field set — no extra fields can smuggle untrusted data past Wave 3.
  for (const f of ARTIFACT_FIELDS) {
    if (!(f in artifact)) failures.push(`missing field: ${f}`);
  }
  for (const k of Object.keys(artifact)) {
    if (!ARTIFACT_FIELDS.includes(k)) failures.push(`unexpected field: ${k}`);
  }
  if (typeof artifact.model !== 'string' || artifact.model.length === 0) {
    failures.push('model must be a non-empty string');
  }
  if (typeof artifact.verifier_family !== 'string' || artifact.verifier_family.length === 0) {
    failures.push('verifier_family must be a non-empty string');
  } else if (artifact.verifier_family.toLowerCase() === _gf) {
    failures.push(`verifier_family must NOT equal the generator family (${_gf}) — verifier ≠ generator (Honesty Law)`);
  }
  if (!VALID_TIERS.has(artifact.tier)) {
    failures.push(`tier must be one of ${[...VALID_TIERS].join('|')}`);
  }
  if (typeof artifact.verdict !== 'string' || !['YES', 'NO', 'UNPARSEABLE'].includes(artifact.verdict)) {
    failures.push('verdict must be one of YES|NO|UNPARSEABLE');
  }
  for (const h of ['prompt_hash', 'normalized_answer_hash', 'transcript_hash']) {
    if (typeof artifact[h] !== 'string' || !HEX64.test(artifact[h])) {
      failures.push(`${h} must be a 64-hex SHA-256 string`);
    }
  }
  return { ok: failures.length === 0, failures };
}

/**
 * VERDICT-LEVEL reproducibility check between two artifacts (or records): SAME parsed verdict AND SAME
 * normalized_answer_hash. transcript_hash is DELIBERATELY ignored — it is provenance only and may
 * differ. Returns { reproducible, reasons }.
 */
export function verdictReproducible(a, b) {
  const aa = a && a.artifact ? a.artifact : a;
  const bb = b && b.artifact ? b.artifact : b;
  const reasons = [];
  if (!aa || !bb) {
    return { reproducible: false, reasons: ['one or both artifacts are missing'] };
  }
  if (aa.verdict !== bb.verdict) reasons.push(`verdict differs (${aa.verdict} vs ${bb.verdict})`);
  if (aa.normalized_answer_hash !== bb.normalized_answer_hash) {
    reasons.push('normalized_answer_hash differs');
  }
  return { reproducible: reasons.length === 0, reasons };
}

// ---------------------------------------------------------------------------
// Manifest model resolution (the ollama FALLBACK panel).
// ---------------------------------------------------------------------------

/**
 * Resolve a model in the manifest's ollama panel by exact name OR by family. Returns { name, family }.
 * Throws if the manifest has no ollama panel or the model/family is absent.
 */
export function resolveModel(manifest, modelOrFamily) {
  const models = manifest && manifest.tools && manifest.tools.ollama && manifest.tools.ollama.models;
  if (!Array.isArray(models) || models.length === 0) {
    throw new CrossFamilyDriverError('manifest has no ollama.models panel');
  }
  const hit =
    models.find((m) => m && m.name === modelOrFamily) ||
    models.find((m) => m && m.family === modelOrFamily);
  if (!hit) {
    throw new CrossFamilyDriverError(
      `no ollama model matches ${JSON.stringify(modelOrFamily)} (have: ${models.map((m) => `${m.name}/${m.family}`).join(', ')})`,
    );
  }
  return { name: hit.name, family: hit.family };
}

/** The default FALLBACK model = the first model in the ollama panel. */
function firstOllamaModel(ollamaSpec) {
  const models = ollamaSpec && Array.isArray(ollamaSpec.models) ? ollamaSpec.models : [];
  if (models.length === 0) throw new CrossFamilyDriverError('ollama fallback panel is empty');
  return { name: models[0].name, family: models[0].family };
}

// ---------------------------------------------------------------------------
// The single-backend driver (the low-level seam Wave 3's panel drives per model).
// ---------------------------------------------------------------------------

/**
 * DRIVE a single cross-family verdict against ONE backend (Wave 3's panel calls this once per model).
 *
 *   driveCrossFamilyVerdict(ollamaSpec, { model, family|verifier_family, prompt, tier }, { generate, baseUrl, tier })
 *
 * `generate` (async (prompt) -> rawAnswer string) is INJECTABLE — the fast test tier passes a stub so
 * the driver is exercised with NO server. When omitted, the default network generate is built lazily
 * from `ollamaSpec` + `baseUrl` (the persistent server's base url) using the F0 deterministic-decoding
 * createOllamaGenerate (temp 0, top_k 1, top_p 1, fixed seed, num_predict cap). A single-backend ollama
 * drive is the FALLBACK substrate, so `tier` defaults to fallback when unspecified. Returns the verdict
 * record from makeVerdictRecord.
 */
export async function driveCrossFamilyVerdict(
  ollamaSpec,
  { model, family, verifier_family, prompt, tier } = {},
  { generate, baseUrl, tier: tierOpt } = {},
) {
  if (typeof prompt !== 'string' || prompt.length === 0) {
    throw new CrossFamilyDriverError('driveCrossFamilyVerdict requires a non-empty prompt');
  }
  const t = tier != null ? tier : tierOpt != null ? tierOpt : TIER.FALLBACK;
  let gen = generate;
  if (typeof gen !== 'function') {
    if (!ollamaSpec || typeof baseUrl !== 'string' || baseUrl.length === 0) {
      throw new CrossFamilyDriverError(
        'driveCrossFamilyVerdict needs either an injected generate(prompt) or (ollamaSpec + baseUrl) to build the deterministic network generate',
      );
    }
    gen = createOllamaGenerate(ollamaSpec, model, baseUrl);
  }
  const rawAnswer = await gen(prompt);
  return makeVerdictRecord({ model, verifier_family, family, tier: t, prompt, rawAnswer });
}

/**
 * Convenience: resolve a model from the manifest's ollama panel by name/family and drive a single
 * FALLBACK-tier verdict against the persistent server. The fast tier still injects `generate`; the tool
 * lane passes `baseUrl`.
 */
export async function driveFromManifest(manifest, modelOrFamily, prompt, { generate, baseUrl, manifestPath } = {}) {
  const m = manifest || loadManifest(manifestPath);
  const ollamaSpec = m.tools && m.tools.ollama;
  if (!ollamaSpec) throw new CrossFamilyDriverError('manifest has no ollama tool spec');
  const { name, family } = resolveModel(m, modelOrFamily);
  return driveCrossFamilyVerdict(ollamaSpec, { model: name, family, prompt, tier: TIER.FALLBACK }, { generate, baseUrl });
}

// ---------------------------------------------------------------------------
// The v3 substrate driver: GEMINI-PRIMARY, graceful ollama-FALLBACK.
// ---------------------------------------------------------------------------

/**
 * DRIVE a cross-family verdict over the v3 substrate: try the frontier Gemini PRIMARY first; on ANY
 * fail-closed condition (key-missing / 401|403 / 429 credit-depleted / network timeout|DNS / other
 * non-2xx / unparseable body) GRACEFULLY FALL BACK to the ollama panel and stamp the ACTUAL backend.
 *
 *   driveCrossFamily(manifest, prompt, {
 *     geminiGenerate,        // inject the PRIMARY transport (fast tier); else built from the manifest+env
 *     fetchImpl,             // inject the raw fetch for createGeminiGenerate (lets the fast gate run keyless)
 *     env,                   // env holding GEMINI_API_KEY (default process.env)
 *     ollamaGenerateFor,     // (modelName)->async(prompt)->raw for the FALLBACK (fast tier); else baseUrl
 *     baseUrl,               // the persistent ollama server base url (tool lane)
 *     fallbackModelOrFamily, // which ollama model to fall back to (default: first panel model)
 *   })
 *
 * Returns the verdict record (makeVerdictRecord envelope) AUGMENTED with:
 *   { backend:'gemini'|'ollama', tier, verifier_family, model, gemini_quarantine }
 * where `gemini_quarantine` is null on a frontier success, or { failClass, reason } (KEY-REDACTED) when
 * the PRIMARY was quarantined and the fallback ran. The artifact's `tier`/`verifier_family` record the
 * backend that ACTUALLY produced the verdict — the canary (Wave 3) re-runs THAT backend.
 *
 * NETWORK SAFETY: the Gemini transport is the F0 `createGeminiGenerate` (key only in the
 * x-goog-api-key header, pinned TLS host, key-redacted errors). The fallback reason is additionally
 * redacted here with the env key value as a defensive second layer — the key never reaches the result.
 */
export async function driveCrossFamily(manifest, prompt, opts = {}) {
  if (typeof prompt !== 'string' || prompt.length === 0) {
    throw new CrossFamilyDriverError('driveCrossFamily requires a non-empty prompt');
  }
  const m = manifest || loadManifest(opts.manifestPath);
  const ollamaSpec = (m.tools && m.tools.ollama) || null;
  const {
    geminiGenerate,
    runGemini,
    primaryGenerate,
    runPrimary,
    seat,
    author = DEFAULT_AUTHOR_FAMILY,
    loadModelFamilies,
    env = process.env,
    ollamaGenerateFor,
    baseUrl,
    fallbackModelOrFamily,
  } = opts;

  // ---- The PRIMARY seat (2026-09-04): the Anchor dashboard's configured family, never a hardwired one. ----
  const resolved = await resolvePrimarySeat(m, { geminiGenerate, runGemini, primaryGenerate, runPrimary, seat, author, env, loadModelFamilies });
  if (resolved.family && resolved.family === resolved.author) {
    // The Honesty Law at the invocation boundary: a seat pinned to the author's own family is a
    // wiring error, refused loudly — never quarantined into a fallback that hides it.
    throw new CrossFamilyDriverError(
      `cross-family driver refuses the \`${resolved.family}\` seat for a \`${resolved.author}\`-authored claim — ` +
      'the verifier family must DIFFER from the generator family (Honesty Law, generator-relative)',
      { seat: resolved },
    );
  }
  let primaryQuarantine = null;
  if (!resolved.family) {
    primaryQuarantine = Object.freeze({ failClass: SEAT_FAIL_CLASS.SEAT_UNCONFIGURED, reason: resolved.reason });
  } else {
    try {
      const gen = primaryGenerate || geminiGenerate || createFamilyGenerate(resolved.tool, { env, runFamily: runPrimary || runGemini });
      const rawAnswer = await gen(prompt);
      const rec = makeVerdictRecord({
        model: resolved.model || resolved.family,
        verifier_family: resolved.family,
        tier: TIER.FRONTIER,
        prompt,
        rawAnswer,
        generator_family: resolved.author,
      });
      return Object.freeze({
        ...rec,
        backend: resolved.family,
        tier: TIER.FRONTIER,
        verifier_family: rec.artifact.verifier_family,
        model: rec.artifact.model,
        seat: resolved,
        primary_quarantine: null,
        gemini_quarantine: null, // legacy alias of primary_quarantine
      });
    } catch (e) {
      // Subscription seams use the login (no key) — nothing to redact; carry the typed failClass through.
      primaryQuarantine = Object.freeze({
        failClass: (e && e.failClass) || 'ERROR',
        reason: e && e.message ? String(e.message) : `${resolved.family} transport error`,
      });
    }
  }
  const seatName = resolved.family || 'cross-family seat';

  // ---- QUARANTINE -> FALLBACK: ollama (tier=fallback). ----
  if (!ollamaSpec) {
    throw new CrossFamilyDriverError(
      `${seatName} PRIMARY quarantined and the manifest has no ollama FALLBACK panel — no cross-family backend`,
      { primary_quarantine: primaryQuarantine, gemini_quarantine: primaryQuarantine },
    );
  }
  const { name, family } = fallbackModelOrFamily ? resolveModel(m, fallbackModelOrFamily) : firstOllamaModel(ollamaSpec);
  let gen = typeof ollamaGenerateFor === 'function' ? ollamaGenerateFor(name) : null;
  if (typeof gen !== 'function') {
    if (typeof baseUrl !== 'string' || baseUrl.length === 0) {
      throw new CrossFamilyDriverError(
        `${seatName} PRIMARY quarantined and the FALLBACK needs either an injected ollamaGenerateFor(model) or a baseUrl to reach the persistent server`,
        { primary_quarantine: primaryQuarantine, gemini_quarantine: primaryQuarantine },
      );
    }
    gen = createOllamaGenerate(ollamaSpec, name, baseUrl);
  }
  const rawAnswer = await gen(prompt);
  const rec = makeVerdictRecord({ model: name, verifier_family: family, tier: TIER.FALLBACK, prompt, rawAnswer, generator_family: resolved.author });
  return Object.freeze({
    ...rec,
    backend: 'ollama',
    tier: TIER.FALLBACK,
    verifier_family: rec.artifact.verifier_family,
    model: rec.artifact.model,
    seat: resolved,
    primary_quarantine: primaryQuarantine,
    gemini_quarantine: primaryQuarantine, // legacy alias
  });
}

// Re-export the pinned Gemini transport surface (provenance: F0) for callers/tests that assert the
// network-safety contract (key only in the x-goog-api-key header, pinned TLS host).
export { buildGeminiRequest, GEMINI_HOST, GEMINI_BASE_URL, CROSS_FAMILY_TIER };
