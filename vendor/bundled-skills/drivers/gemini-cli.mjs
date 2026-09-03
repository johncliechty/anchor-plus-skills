// drivers/gemini-cli.mjs — the Gemini HOST backend: headless `agy -p` on the user's
// Antigravity CLI (agy) login. This is the Gemini analog of `claude.mjs`: a real
// sub-agent-spawning CLI driver (contrast the raw-HTTP `gemini.mjs` WORKER driver,
// which needs GEMINI_API_KEY and is NOT sub-agent-capable). Selected via
// `TRIO_DRIVER=gemini-cli`.
//
// W0 (2026-07-05) — LIVE agy contract rewrite. This driver now mirrors the PROVEN
// transport in Skill Foundry tools/agy-dispatch.mjs (validated against agy
// v1.0.13 on this host):
//   * Invocation: `agy -p "<STEER + prompt>" --log-file <tmp> --model "<LABEL>"
//     [--sandbox --add-dir <target>]`. The old `--skip-trust` / `--output-format
//     stream-json` / `--dangerously-skip-permissions` flags are DEAD (hard-error on
//     this agy), and the prompt goes via ARGV `-p` (NOT stdin — stdin truncates ~4KB).
//   * Print mode emits NOTHING on a pipe: the model reply is read from the conversation
//     `transcript.jsonl` (resolved via the `--log-file` "Print mode: conversation=<id>"
//     line → the last `source==='MODEL'` transcript line), never from stdout.
//   * Model ids are agy LABELS ("Gemini 3.1 Pro (High)" / "Gemini 3.5 Flash (Medium)"),
//     NEVER API-style ids. An API-style id like `gemini-3.1-pro` is UNRECOGNIZED and agy
//     SILENTLY serves Flash instead — the phantom-id degrade the served==requested guard
//     below exists to catch (proven in W0-DISCOVERY.md).
//
// SERVED-MODEL ATTESTATION (criterion 3 / SR-5) — W0-fix (2026-07-05), LIVE-VERIFIED:
// the transcript carries NO model field, so the served model is read from agy's `cli.log`
// (`~/.gemini/antigravity-cli/cli.log`). CRITICAL live fact: agy ONLY writes model lines
// when it SUBSTITUTES. A clean call with a RECOGNIZED label (e.g. "Gemini 3.1 Pro (High)")
// writes NO model line at all — not even after 2s — so there is NO positive "served model"
// line to read on the happy path. An UNRECOGNIZED id (e.g. `gemini-3.1-pro`) reliably logs,
// slightly async:
//   `Resolving model gemini-3.1-pro`
//   `Failed to resolve model flag gemini-3.1-pro: … is not recognized …`
//   `Propagating selected model override to backend: label="Gemini 3.5 Flash (Medium)"`
// So attestation is an ALLOWLIST + SUBSTITUTION-DETECTION (`servedModelFromCliLog`):
//   * a `Failed to resolve model flag <requested>` line ⇒ substituted; the following
//     `Propagating … override … label="<X>"` names what actually served → { served:X,
//     substituted:true };
//   * else a `requested` in KNOWN_AGY_LABELS ⇒ clean serve attested by ABSENCE of any
//     substitution line → { served:requested, substituted:false };
//   * else (uncatalogued id, no override) ⇒ cannot attest → { served:null, substituted:false }.
// We POLL the tail appended by THIS call (sliced from the pre-spawn cli.log size) up to ~3s
// so the slightly-async substitution line is not missed (the old code read too early and got
// null even for a real substitution — a timing bug); a concurrent call's line is not
// mis-attributed because we only read our own appended region.
//
// THREE HONEST OUTCOMES (parseGeminiCliFrames): substituted → `ok:false`,
// `status:'model_substituted'`, `model_served:<override>`, `model_attested:true` (we DID
// attest what served — that is how we know it was substituted — but it is NEVER a success,
// the silent cross-family degrade tripwire); clean known label → `ok:true`,
// `status:'success'`, `model_served:requested`, `model_attested:true`; uncatalogued id →
// `ok:false`, `status:'unattested_model'`, `model_served:null`, `model_attested:false`
// (conservative HALT — never assume a clean serve for an id we can't verify).
//
// Auth posture: the agy LOGIN is the default — this driver passes NO API key. The seam is
// ENV-GATED (CRUCIBLE_AGENT_LIVE=1 — the same trio-wide gate the Claude driver uses) so an
// accidental import/test never spawns a real (billable) agent, and STUBBABLE
// (`makeGeminiCliSeam({ runGemini })`) so tests drive the full schema/retry/failure logic
// with zero subprocesses.

import { existsSync, readFileSync, statSync, readdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { extractJson } from './claude.mjs';
import { isVerificationRole, normalizeRole } from './roles.mjs';
import { runCliSchemaAttempts } from './cli-schema.mjs';
import { runCloseBoundProcess } from './subscription-process.mjs';

// agy on-disk layout (validated on this host). The conversation transcript lives under
// the brain dir keyed by conversation id; the served-model attestation lives in cli.log.
const AGY_HOME = path.join(homedir(), '.gemini', 'antigravity-cli');
const AGY_BRAIN_DIR = path.join(AGY_HOME, 'brain');
const AGY_CLI_LOG = path.join(AGY_HOME, 'cli.log');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// W0: agy args are BUILT PER-CALL (prompt + log-file + model are dynamic), so there is no
// static base-arg list any more. Kept as an exported empty tuple only so downstream
// imports of this name do not break; the dead `--skip-trust`/`--output-format` flags are
// gone (they hard-error on live agy).
export const GEMINI_CLI_BASE_ARGS = [];

// W0: agy LABEL model ids (NEVER API-style ids). Heavy/top = "Gemini 3.1 Pro (High)"
// (also agy's settings.json default); standard/one-below = "Gemini 3.5 Flash (Medium)".
// The old phantom default `gemini-3.1-pro` was an UNRECOGNIZED id that agy silently
// degraded to Flash — replaced here with the real heavy LABEL.
export const GEMINI_HEAVY_MODEL = 'Gemini 3.1 Pro (High)';
export const GEMINI_STANDARD_MODEL = 'Gemini 3.5 Flash (Medium)';
export const DEFAULT_GEMINI_CLI_MODEL = GEMINI_HEAVY_MODEL;

// `auto_edit` auto-approves file edits (the Claude `acceptEdits` analog) — the right
// default for execute/fix roles. Read-only roles (reviewers/judges) get `plan`. Retained
// for back-compat with `approvalModeFor` consumers; the live agy posture is derived from
// the role via READONLY_ROLES → `--readonly` (no `--sandbox`) below.
export const DEFAULT_GEMINI_APPROVAL_MODE = 'auto_edit';

// Read-only roles get agy's `--readonly` posture (no edit flags); edit roles get
// `--sandbox --add-dir <target>` (auto-approve edits, scoped). Roles are matched by name
// or by the label prefix Foreman uses (`execute:`, `review:`, `fix:`).
export const READONLY_ROLES = new Set([
  'review', 'reviewer', 'shark', 'judge', 'synthesizer', 'synth', 'research', 'researcher', 'plan', 'planner',
]);
const EDIT_ROLES = new Set(['execute', 'exec', 'fix', 'build', 'builder']);

// W0 NO-SHELL STEER (the permanent window-focus fix, verbatim from agy-dispatch.mjs):
// agy spawns a fresh VISIBLE PowerShell window for every shell tool call, and no parent
// spawn flag can suppress it. Keeping Gemini ENTIRELY on its in-process file tools (it
// never invokes the shell) is the reliable fix — the STEER prefix is prepended to every
// prompt. It forbids the shell only; write/edit-file tools still work, so edit roles are
// unaffected.
const STEER = `TOOL POLICY (MANDATORY): Use ONLY your in-process file tools — read_file, ` +
  `list_directory, glob, search/grep, and (for edit tasks) write/edit file. Do NOT use the ` +
  `shell / terminal / run_shell_command tool for ANY reason — no git, python, node, grep, ` +
  `pytest, ls, cat, etc. On Windows agy opens a VISIBLE PowerShell window for every shell ` +
  `call, which steals the user's keyboard focus, so shell use is forbidden here. If a step ` +
  `seems to need a shell, do it with the file tools instead, or state plainly that it needs ` +
  `a shell — the human operator runs all shell / test / git / build commands. Stay file-tools-only.\n\n---\n\n`;

const norm = (s) => String(s ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
const modelsEqual = (a, b) => norm(a) === norm(b);

// W0-fix (2026-07-05): the agy LABEL allowlist. LIVE-VERIFIED behavior — agy logs a model
// line to cli.log ONLY when it SUBSTITUTES (an unrecognized id it can't resolve); a clean
// serve of a KNOWN label writes NO model line at all (not even after 2s). So there is no
// positive "served model" line to read on the happy path — a clean known-label serve is
// attested by the ABSENCE of a substitution line, checked against this catalog.
export const KNOWN_AGY_LABELS = new Set(['Gemini 3.1 Pro (High)', 'Gemini 3.5 Flash (Medium)']);
const KNOWN_AGY_LABELS_NORM = new Set([...KNOWN_AGY_LABELS].map(norm));
function familyFromModel(m) {
  const s = String(m ?? '');
  if (!s) return null;
  // W0-fix: STRICT prefix match — a label like "claude-...-gemini-fallback" must NOT
  // stamp gemini. Family is the leading token, not a substring anywhere in the label.
  const t = s.trim().toLowerCase();
  if (t.startsWith('gemini')) return 'gemini';
  if (t.startsWith('claude')) return 'claude';
  return s.split(/[\s\-]/)[0].toLowerCase() || null;
}

/**
 * Resolve the approval mode for a worker (retained for back-compat). An explicit
 * `approvalMode` always wins. Otherwise a read-only role => 'plan'; an edit role =>
 * 'auto_edit'; unknown => the safe-ish default. Role is taken from `role`, else the
 * label's prefix before ':' / '#' / '.'.
 */
export function approvalModeFor({ approvalMode, role, label } = {}) {
  if (approvalMode) return approvalMode;
  const key = normalizeRole({ role, label });
  if (READONLY_ROLES.has(key)) return 'plan';
  if (EDIT_ROLES.has(key)) return 'auto_edit';
  return DEFAULT_GEMINI_APPROVAL_MODE;
}

/** True iff this role/label is a read-only (verification) seat — agy `--readonly`. */
export function isReadonlyRole({ role, label } = {}) {
  const key = normalizeRole({ role, label });
  return isVerificationRole({ role: key, label }) || READONLY_ROLES.has(key);
}

/**
 * TRIO_TIER (John 2026-07-04) — the SAME one-switch tier ladder as the Claude
 * resolver (`resolveClaudeModel` in claude.mjs), expressed in agy LABELs:
 *  - heavy    => GEMINI_HEAVY_MODEL   ("Gemini 3.1 Pro (High)")
 *  - standard => GEMINI_STANDARD_MODEL ("Gemini 3.5 Flash (Medium)")
 * Both are agy LABELs (never API-style ids — an API id silently degrades to Flash).
 */
const TIER_GEMINI_MODELS = {
  heavy: GEMINI_HEAVY_MODEL,
  standard: GEMINI_STANDARD_MODEL,
};

/**
 * Resolve the designated model for this call. Precedence mirrors `resolveClaudeModel`
 * EXACTLY: an explicit `opts.model` wins → then `TRIO_TIER` (heavy/standard) → then the
 * per-role env `TRIO_MODEL_<ROLE>` → then `TRIO_MODEL` → then `GEMINI_MODEL` → then the
 * default. CRITICAL: `TRIO_TIER` is ordered ABOVE the `TRIO_MODEL`/`GEMINI_MODEL` env so
 * it BEATS the setx-pinned user env (which encodes the old always-heavy default) — the
 * whole point of the switch is to flip a run without unpinning machine-wide env, exactly
 * as the Claude resolver orders TRIO_TIER above CLAUDE_MODEL_<ROLE>.
 * NB (W0): the resolved value is an agy LABEL, never an API-style id.
 */
export function resolveGeminiModel({ model, role, env = process.env } = {}) {
  if (model) return model;
  const tier = String(env.TRIO_TIER || '').trim().toLowerCase();
  if (tier && TIER_GEMINI_MODELS[tier]) return TIER_GEMINI_MODELS[tier];
  const roleKey = role ? `TRIO_MODEL_${String(role).toUpperCase()}` : null;
  return (
    (roleKey && env[roleKey]) ||
    env.TRIO_MODEL ||
    env.GEMINI_MODEL ||
    DEFAULT_GEMINI_CLI_MODEL
  );
}

// Default per-call wall-clock ceiling — kills a child that hangs so the orchestrator
// never blocks forever. Override via opts.timeoutMs (0 disables).
export const DEFAULT_GEMINI_TIMEOUT_MS = 60 * 60 * 1000;

// Argv-safe prompt ceiling: Windows caps a command line ~32KB; past ~28KB (leaving room
// for the other args) the prompt is delivered via a per-call file instead (2026-07-16).
export const OVERSIZE_PROMPT_ARGV_BYTES = 28000;

/**
 * W0: build the live agy argv — `-p <STEER+prompt> --log-file <tmp> --model "<LABEL>"
 * --print-timeout <t>s [--sandbox --add-dir <target>]`. Prompt is delivered via ARGV
 * (stdin truncates ~4KB on agy). An OVERSIZED prompt (2026-07-16, John-authorized fix:
 * live Item-F Sharks died >32KB argv, journal crucible/0004) is delivered via
 * `promptFile` instead: the file carries the FULL prompt and `-p` carries only a short
 * pointer instructing Gemini to read it with its in-process file tool.
 * @param {object} o
 * @param {string} o.prompt      the FULL prompt to send (STEER already prepended)
 * @param {string} [o.promptFile] when set, `prompt` was written to this path — argv gets the short pointer
 * @param {string} o.logPath     the `--log-file` temp path (source of the conversation id)
 * @param {string} [o.model]     agy LABEL
 * @param {string} [o.target]    cwd / edit scope for `--add-dir`
 * @param {boolean}[o.readonly]  read-only posture (no `--sandbox --add-dir`)
 * @param {number} [o.timeoutMs] used to align agy's own `--print-timeout` under our kill
 * @returns {string[]}
 */
export function buildGeminiCliArgs({
  prompt = '',
  promptFile = null,
  logPath,
  model,
  target = process.cwd(),
  readonly = false,
  timeoutMs = DEFAULT_GEMINI_TIMEOUT_MS,
} = {}) {
  const argvPrompt = promptFile
    ? STEER +
      `Your ENTIRE task prompt is in the UTF-8 file ${promptFile} — read that file NOW with your ` +
      `in-process file-read tool and follow its contents EXACTLY as if it were this message. ` +
      `Do not summarize it back; execute it and reply as it instructs.`
    : prompt;
  const args = ['-p', argvPrompt, '--log-file', logPath, '--model', model ?? DEFAULT_GEMINI_CLI_MODEL];
  // Align agy's own print-mode wait just under our kill ceiling so OUR kill is the backstop.
  const secs = timeoutMs > 0 ? Math.max(60, Math.floor((timeoutMs * 0.95) / 1000)) : 60;
  args.push('--print-timeout', `${secs}s`);
  if (!readonly) {
    args.push('--sandbox', '--add-dir', target);
    // The sandbox must be able to READ the prompt file (it lives in the per-call tmp dir).
    if (promptFile) args.push('--add-dir', path.dirname(promptFile));
  }
  return args;
}

// ---- W0 transcript reply reader (mirrors agy-dispatch.mjs) --------------------------
// The reply is NOT on stdout in print mode — it is read from the conversation
// transcript.jsonl, resolved via the --log-file "Print mode: conversation=<id>" line.

export function conversationIdFromLog(logPath) {
  if (!logPath || !existsSync(logPath)) return null;
  let txt = '';
  try { txt = readFileSync(logPath, 'utf8'); } catch { return null; }
  const m = txt.match(/Print mode:\s*conversation=([0-9a-fA-F-]{8,})/);
  return m ? m[1] : null;
}
function transcriptPathForId(id) {
  return path.join(AGY_BRAIN_DIR, id, '.system_generated', 'logs', 'transcript.jsonl');
}
function newestTranscriptSince(since) {
  if (!existsSync(AGY_BRAIN_DIR)) return null;
  let best = null, bestMtime = since, ids = [];
  try { ids = readdirSync(AGY_BRAIN_DIR); } catch { return null; }
  for (const id of ids) {
    const p = transcriptPathForId(id);
    try { const st = statSync(p); if (st.mtimeMs >= bestMtime) { best = p; bestMtime = st.mtimeMs; } }
    catch { /* no transcript */ }
  }
  return best;
}
/** Last `source==='MODEL'` line's text in a transcript.jsonl (the final model reply). */
export function finalTextFromTranscript(pathOrText, { isText = false } = {}) {
  let raw = '';
  if (isText) raw = String(pathOrText ?? '');
  else {
    if (!pathOrText || !existsSync(pathOrText)) return '';
    try { raw = readFileSync(pathOrText, 'utf8'); } catch { return ''; }
  }
  let last = '';
  for (const line of raw.split('\n')) {
    const s = line.trim();
    if (!s) continue;
    let o; try { o = JSON.parse(s); } catch { continue; }
    if (o && o.source === 'MODEL' && typeof o.content === 'string' && o.content.trim()) last = o.content.trim();
  }
  return last;
}
async function readAgyReply(logPath, startMs) {
  let id = null;
  for (let i = 0; i < 20 && !id; i++) { id = conversationIdFromLog(logPath); if (!id) await sleep(100); }
  if (id) {
    const p = transcriptPathForId(id);
    for (let i = 0; i < 20; i++) { const t = finalTextFromTranscript(p); if (t) return { text: t, id }; await sleep(250); }
    return { text: '', id };
  }
  for (let i = 0; i < 20; i++) {
    const p = newestTranscriptSince(startMs - 2000);
    const t = finalTextFromTranscript(p);
    if (t) return { text: t, id: null };
    await sleep(250);
  }
  return { text: '', id: null };
}

// ---- W0 served-model attestation (parsed from agy's cli.log) ------------------------

/** Current byte-length of cli.log (0 if absent) — captured pre-spawn to slice OUR tail. */
function cliLogSize(logPath = AGY_CLI_LOG) {
  try { return statSync(logPath).size; } catch { return 0; }
}
/**
 * Read the cli.log region appended after `sinceBytes` (this call's own lines).
 * W0-fix: returns `null` on ANY read error so an unreadable cli.log fails CLOSED
 * (treated as UNATTESTED downstream) rather than looking like a clean empty window.
 */
function cliLogTailSince(sinceBytes, logPath = AGY_CLI_LOG) {
  try {
    const buf = readFileSync(logPath);
    return buf.slice(Math.max(0, sinceBytes)).toString('utf8');
  } catch { return null; }
}

const reEscape = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * W0-fix (2026-07-05): recover the SERVED model from an agy `cli.log` window, using the
 * LIVE-VERIFIED fact that agy ONLY logs when it SUBSTITUTES. There is NO positive
 * "served model" line on a clean serve — so attestation is an allowlist + substitution
 * detection, NOT a line to parse on the happy path.
 *   (1) SUBSTITUTION — the window contains `Failed to resolve model flag <requested>`
 *       (the requested id was NOT recognized). agy then propagates the model it actually
 *       serves: `Propagating selected model override to backend: label="<X>"`. Return
 *       `{ served: X, substituted: true }` — X is the served truth (X may be null only if
 *       the override line hasn't been flushed yet).
 *   (2) CLEAN KNOWN LABEL — no substitution line AND `requested` is in KNOWN_AGY_LABELS →
 *       `{ served: requested, substituted: false }`. Attested by the ABSENCE of a
 *       substitution line on a catalogued label (agy would have logged had it substituted).
 *   (3) UNCATALOGUED — an unknown id with no override captured → `{ served: null,
 *       substituted: false }`. We cannot attest; the caller must HALT rather than assume.
 * @param {string} cliLogWindow    a cli.log region (this call's appended tail)
 * @param {object} [o]
 * @param {?string}[o.requested]   the requested agy LABEL / id
 * @returns {{ served: ?string, substituted: boolean }}
 */
/**
 * B2 (2026-07-11): when should the post-exit cli.log attestation poll STOP?
 * Pure/testable. Three answers:
 *   'substitution-evidence' — a resolve-failure / override line landed: stop NOW,
 *       `servedModelFromCliLog` will stamp the substitution (tripwire fully intact).
 *   'known-label-clean'     — the requested label is CATALOGUED, the window is
 *       readable, and a straggler grace (default 2s — agy writes substitution lines
 *       slightly async) has elapsed with no evidence: attest-by-absence is already
 *       decided, waiting the full ~10s adds nothing. This was the review's largest
 *       standing tax: EVERY successful Gemini call paid the whole 40x250ms poll,
 *       because a clean serve never writes the line the loop waited for.
 *   null                    — keep polling (unknown label, unreadable window, or
 *       still inside the grace). Unknown labels always poll the full window — they
 *       are the substitution-risk case the tripwire exists for.
 */
export function shouldStopAttestationPoll({ cliWindow, requested, elapsedMs, graceMs = 2000 } = {}) {
  if (typeof cliWindow === 'string' &&
      (/Failed to resolve model flag/i.test(cliWindow) ||
       /Propagating selected model override to backend:/i.test(cliWindow))) {
    return 'substitution-evidence';
  }
  if (requested && KNOWN_AGY_LABELS_NORM.has(norm(requested)) &&
      typeof cliWindow === 'string' && elapsedMs >= graceMs) {
    return 'known-label-clean';
  }
  return null;
}

export function servedModelFromCliLog(cliLogWindow, { requested = null } = {}) {
  // W0-fix: a null / non-string window (unreadable cli.log) fails CLOSED — Branch 3
  // UNATTESTED, NEVER the Branch 2 clean-stamp. We cannot attest what we could not read.
  if (typeof cliLogWindow !== 'string') return { served: null, substituted: false };
  const win = cliLogWindow;
  // (1) Substitution: the requested id was NOT recognized (`Failed to resolve model flag <requested>`).
  if (requested) {
    const failedRe = new RegExp(`Failed to resolve model flag\\s+${reEscape(requested)}`, 'i');
    if (failedRe.test(win)) {
      const overrides = [...win.matchAll(/Propagating selected model override to backend:\s*label="([^"]+)"/g)];
      const served = overrides.length ? overrides[overrides.length - 1][1].trim() : null;
      return { served, substituted: true };
    }
  }
  // NOTE (2026-07-17): the resolver.go "Model ID <X> not in local config, defaulting to CCPA"
  // line is BENIGN — VERIFIED LIVE by asking the served model its identity (it answered
  // "Gemini 3.1 Pro"): agy serves the real requested model via model_resolver.go + the
  // "Propagating selected model override" path DESPITE that line. It is NOT a substitution
  // signal. An earlier fix that treated it as one was a FALSE POSITIVE that would fail EVERY
  // real Gemini serve over to Claude — do not re-add it. Genuine substitution is the
  // "Failed to resolve model flag" branch (1) above.
  // (2) Clean serve of a KNOWN label — attested by absence-of-substitution on a catalogued label.
  if (requested && KNOWN_AGY_LABELS_NORM.has(norm(requested))) {
    return { served: requested, substituted: false };
  }
  // (3) Uncatalogued id, no override evidence — cannot attest.
  return { served: null, substituted: false };
}

/**
 * W0-fix (2026-07-05): assemble the `{ text, rec }` result from the transcript reply plus
 * the cli.log attestation (`{ served, substituted }` from `servedModelFromCliLog`). Pure/
 * testable — no subprocess. Because agy ONLY logs on substitution, there are THREE honest
 * outcomes (not two):
 *
 *   (a) SUBSTITUTED (`substituted:true`) — agy could not resolve the requested id and
 *       served something else (the captured override label). We DID attest what served —
 *       that is exactly how we know it was substituted — so `model_attested:true`,
 *       `model_served:<override>`, `degraded:false`; but it is NEVER a success:
 *       `ok:false`, `status:'model_substituted'` (the silent cross-family degrade tripwire).
 *   (b) CLEAN KNOWN LABEL (`served === requested`, not substituted) — attested by the
 *       ABSENCE of a substitution line on a catalogued label: `ok:true`, `status:'success'`,
 *       `model_served:requested`, `model_attested:true`, `degraded:false`.
 *   (c) UNATTESTED (`served === null`, not substituted) — an uncatalogued id with no
 *       evidence either way. We refuse to assume a clean serve for an id we can't verify:
 *       `ok:false`, `status:'unattested_model'`, `model_served:null`, `model_attested:false`
 *       (conservative HALT).
 *
 * The attestation triple (model_served/model_attested/degraded) is ALWAYS kept internally
 * consistent (drivers/attest.mjs `hasAttestation` invariant); a guard failure is expressed
 * via `ok`/`status`, never by corrupting the triple.
 *
 * @param {string} replyText                the model's final transcript reply
 * @param {object} [meta]
 * @param {string} [meta.label]
 * @param {?number}[meta.cli_status]        agy process exit code
 * @param {?string}[meta.requested_model]   the requested agy LABEL
 * @param {?string}[meta.served_model]      the served LABEL from servedModelFromCliLog (or null)
 * @param {boolean}[meta.substituted]       true iff cli.log showed a resolve-failure/override
 * @returns {{ text:string, rec:object }}
 */
export function parseGeminiCliFrames(replyText, {
  label = '(unlabeled)',
  cli_status = null,
  requested_model = null,
  served_model = null,
  substituted = false,
} = {}) {
  const text = String(replyText ?? '').trim();
  const transportOk = cli_status === 0;

  const rec = {
    label,
    cli_status,
    ok: transportOk && text.length > 0,
    status: transportOk ? (text.length > 0 ? 'success' : 'no_reply') : 'cli_error',
    duration_ms: null,
    tools: 0,
    output_tokens: null,
    input_tokens: null,
    total_tokens: null,
    cost_usd: null,
    requested_model,
    // SR-5 attestation triple — honest fallback (unattested) until proven otherwise below.
    model_served: null,
    model_family: transportOk ? 'gemini' : null,
    model_attested: false,
    degraded: true,
    multi_model: false,
    family_attested: transportOk,
  };

  if (substituted) {
    // (a) SUBSTITUTED: cli.log named the override agy actually served. We attested what
    // served (that's how we know it substituted), but it is NEVER a success.
    const attested = typeof served_model === 'string' && served_model.trim().length > 0;
    const servedFamily = attested ? familyFromModel(served_model) : null;
    rec.model_served = attested ? served_model : null;
    rec.model_family = ['claude', 'gemini', 'grok', 'chatgpt'].includes(servedFamily)
      ? servedFamily
      : null;
    rec.family_attested = rec.model_family !== null;
    rec.model_attested = attested;
    rec.degraded = !attested;
    rec.ok = false;
    rec.status = 'model_substituted';
  } else if (typeof served_model === 'string' && served_model.length > 0
             && requested_model && modelsEqual(served_model, requested_model)) {
    // (b) CLEAN KNOWN LABEL: served === requested, attested by absence-of-substitution on a
    // catalogued label. ok/status already 'success' from the transport check above.
    rec.model_served = served_model;
    rec.model_family = familyFromModel(served_model);
    rec.model_attested = true;
    rec.degraded = false;
  } else {
    // (c) UNATTESTED: served === null for an uncatalogued id, no evidence either way. We
    // refuse to assume a clean serve for an id we cannot verify → conservative HALT.
    rec.model_served = null;
    rec.model_family = null;
    rec.model_attested = false;
    // degraded stays true (honest fallback: model_attested:false ∧ degraded:true).
    rec.ok = false;
    rec.status = 'unattested_model';
  }

  return { text, rec };
}

/**
 * W0 live transport: spawn `agy -p`, read the reply from transcript.jsonl, and attest the
 * served model from cli.log. ENV-GATED — throws unless CRUCIBLE_AGENT_LIVE=1.
 * @param {string} fullPrompt
 * @param {string} label
 * @param {object} [o]
 * @param {object} [o.env=process.env]
 * @param {string} [o.target=process.cwd()]  cwd + edit scope for the live sub-agent
 * @param {string} [o.model]                 agy LABEL (resolved if omitted)
 * @param {string} [o.role]                  role name for per-role model + readonly posture
 * @param {string} [o.approvalMode]          retained (back-compat); posture is role-derived
 * @param {number} [o.timeoutMs]             wall-clock kill ceiling (0 disables)
 * @param {Function}[o.log=()=>{}]
 * @returns {Promise<{ text:string, rec:object }>}
 */
export function defaultRunGeminiCli(fullPrompt, label, {
  env = process.env,
  target = process.cwd(),
  model,
  role,
  approvalMode,
  timeoutMs = DEFAULT_GEMINI_TIMEOUT_MS,
  signal = null,
  log = () => {},
  processRunner = runCloseBoundProcess,
  spawnImpl,
  spawnSyncImpl,
  platform = process.platform,
  killImpl,
} = {}) {
  if (env.CRUCIBLE_AGENT_LIVE !== '1') {
    throw new HaltError(
      'live agent seam is disabled',
      'set CRUCIBLE_AGENT_LIVE=1 to spawn a real `agy -p` sub-agent, or inject a stub `runGemini` (tests/orchestrator)',
    );
  }

  const mdl = resolveGeminiModel({ model, role, env });
  const readonly = isReadonlyRole({ role, label });
  // W0: prompt via ARGV `-p` with the STEER prefix (mirrors agy-dispatch.mjs); the reply
  // is read from transcript.jsonl below, not stdout.
  const prompt = STEER + String(fullPrompt ?? '');
  const childEnv = Object.assign({}, env, { NO_COLOR: '1', FORCE_COLOR: '0', CI: '1' });
  if (signal?.aborted) {
    return Promise.resolve({ text: '', rec: {
      label, cli_status: null, ok: false, status: 'aborted', aborted: true,
      requested_model: mdl, model_served: null, model_family: null,
      family_attested: false, model_attested: false, degraded: true, cost_usd: null,
    } });
  }
  const logDir = mkdtempSync(path.join(tmpdir(), 'agy-gemini-cli-'));
  const logPath = path.join(logDir, 'agy.log');
  const startMs = Date.now();
  const cliLogBefore = cliLogSize();
  let promptFile = null;
  if (Buffer.byteLength(prompt) > OVERSIZE_PROMPT_ARGV_BYTES) {
    promptFile = path.join(logDir, 'prompt.md');
    writeFileSync(promptFile, prompt, 'utf8');
    log(`${label}: prompt delivered via file (${Buffer.byteLength(prompt)} bytes)`);
  }
  const args = buildGeminiCliArgs({
    prompt, promptFile, logPath, model: mdl, target, readonly, timeoutMs,
  });
  const cmdName = platform === 'win32' ? 'agy.exe' : 'agy';
  return processRunner({
    command: cmdName,
    args,
    options: {
      cwd: target, env: childEnv, shell: false, windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    },
    signal,
    timeoutMs,
    label,
    log,
    ...(spawnImpl ? { spawnImpl } : {}),
    ...(spawnSyncImpl ? { spawnSyncImpl } : {}),
    platform,
    ...(killImpl ? { killImpl } : {}),
  }).then(async (result) => {
    if (result.terminal !== 'closed' || result.code !== 0) {
      const status = result.terminal === 'closed' ? 'cli_error' : result.terminal;
      if (result.stderr) log(`!! ${label}: agy ${status}. stderr=${result.stderr.slice(0, 300)}`);
      return { text: '', rec: {
        label, cli_status: result.code, ok: false, status,
        error: result.error || result.stderr.slice(0, 500),
        requested_model: mdl, model_served: null, model_family: null,
        family_attested: false, model_attested: false, degraded: true,
        cost_usd: null, timed_out: status === 'timeout', aborted: status === 'aborted',
        kill_status: result.kill_status,
      } };
    }
    const reply = await readAgyReply(logPath, startMs);
    const graceMs = Number(env.AGY_ATTEST_GRACE_MS) > 0
      ? Number(env.AGY_ATTEST_GRACE_MS)
      : 2000;
    let cliWindow = null;
    for (let i = 0; i < 40; i++) {
      cliWindow = cliLogTailSince(cliLogBefore);
      if (shouldStopAttestationPoll({
        cliWindow, requested: mdl, elapsedMs: i * 250, graceMs,
      })) break;
      await sleep(250);
    }
    const attestation = servedModelFromCliLog(cliWindow, { requested: mdl });
    const { text, rec } = parseGeminiCliFrames(reply.text, {
      label,
      cli_status: result.code,
      requested_model: mdl,
      served_model: attestation.served,
      substituted: attestation.substituted,
    });
    rec.conversation_id = reply.id;
    rec.kill_status = result.kill_status;
    if (!rec.ok) {
      log(`!! ${label}: status=${rec.status} (requested="${mdl}" served="${attestation.served ?? 'unattested'}").`);
    }
    return { text, rec };
  });
}

/**
 * Build the `agent()` seam for the Gemini CLI backend. Mirrors claude.mjs's
 * `makeAgentSeam`: structured output is prompt-suffix (the schema is appended, the reply
 * parsed with retry-once-then-failure) so behavior matches every other backend.
 * @param {object} [o]
 * @param {?Function}[o.runGemini]  injected transport `(prompt,label)=>Promise<{text,rec}>`
 *                                  (omit to use the env-gated live `agy -p`).
 * @param {object}  [o.env=process.env]
 * @param {string}  [o.target=process.cwd()]
 * @param {string}  [o.model]
 * @param {string}  [o.role]
 * @param {string}  [o.approvalMode]
 * @param {Function}[o.log=()=>{}]
 * @returns {{ agent: (prompt:string, opts?:object)=>Promise<any> }}
 */
export function makeGeminiCliSeam(options = {}) {
  const {
    runGemini = null,
    env = process.env,
    target = process.cwd(),
    model,
    role,
    approvalMode,
    timeoutMs,
    log = () => {},
  } = options;
  const run = runGemini
    || ((prompt, label, callOpts = {}) => defaultRunGeminiCli(prompt, label, {
      ...options, env, target, model: callOpts.model ?? model,
      role: callOpts.role ?? role, approvalMode,
      timeoutMs: callOpts.timeoutMs ?? timeoutMs, signal: callOpts.signal, log,
    }));

  async function agent(prompt, opts = {}) {
    const label = opts.label || '(unlabeled)';
    return runCliSchemaAttempts({
      run,
      prompt,
      schema: opts.schema,
      label,
      callOpts: {
        model: opts.model ?? model,
        role: normalizeRole({ role: opts.role ?? role, label }),
        timeoutMs: opts.timeoutMs ?? timeoutMs,
        signal: opts.signal,
      },
      driverOpts: opts,
      familyName: 'Gemini',
      log,
      parse: extractJson,
    });
  }

  return { agent };
}

/**
 * The Gemini CLI registry entry — a real sub-agent-capable HOST backend (spawns a fresh
 * `agy -p` process per call, so `freshContext` is native). Structured output is
 * prompt-suffix, identical contract to the Claude backend.
 * @type {{ name:string, subAgentCapable:boolean, structuredOutput:string,
 *          runAgent:(opts?:object)=>Promise<any> }}
 */
export const geminiCliDriver = {
  name: 'gemini-cli',
  subAgentCapable: true,
  structuredOutput: 'cli-subagent (prompt-suffix)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, timeoutMs } = opts;
    const { agent } = makeGeminiCliSeam(opts);
    return agent(prompt, { ...opts, schema, label, timeoutMs });
  },
};

export default geminiCliDriver;
