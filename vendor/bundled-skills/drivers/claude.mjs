// drivers/claude.mjs — the DEFAULT trio model backend: headless `claude -p` on the
// subscription (NO ANTHROPIC_API_KEY => subscription usage). This is the canonical
// home of the existing `claude -p` behavior that previously lived inline in
// `crucible/bin/agent.mjs` and Foreman's `run-live.mjs`; both now route through this
// module so the Claude path stays byte-for-byte equivalent (Wave 4 non-regression).
//
// The seam is:
//   - ENV-GATED: the live process is only spawned when CRUCIBLE_AGENT_LIVE=1, so an
//     accidental import/test never launches a real (billable) agent.
//   - STUBBABLE: `makeAgentSeam({ runClaude })` accepts an injected transport, so
//     tests drive the full schema/retry/failure logic with zero subprocesses.
// The returned `agent(prompt, opts)` honors Workflow's contract: it returns text by
// default, and the validated object when `opts.schema` is supplied (retry-once then
// fail on nonconforming schema replies, exactly like run-live's C1 hardening).
//
// `claudeDriver` is the registry entry consumed by `drivers/index.mjs`; its
// `runAgent({ prompt, schema, freshContext })` is the pluggable interface. claude -p
// spawns a fresh sub-agent process, so `freshContext` is satisfied natively
// (subAgentCapable: true) and the flag is accepted as a no-op for this backend.

import { spawnSync } from 'node:child_process';
import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { attestStamp } from './attest.mjs';
import { isVerificationRole, normalizeRole } from './roles.mjs';
import { runCliSchemaAttempts } from './cli-schema.mjs';
import { runCloseBoundProcess } from './subscription-process.mjs';
import {
  resolveModelPolicy,
  policyEnvironment,
  modelLaunchArgs,
  isClaudeVerificationSeat,
  normalizeClaudeFableModel,
  normalizeStrength,
  isVariableStrengthActive,
  loadPolicyPrefs,
  effectiveVariableStrengthConfig,
  resolveSkillStrength,
  selectStrength,
  CLAUDE_CATALOG_MODELS,
} from './model-policy.mjs';
import { classifySubscriptionOutcome } from './subscription-outcome.mjs';

const BASE_ARGS = [
  '-p', ' ', '--output-format', 'stream-json', '--verbose',
  '--permission-mode', 'acceptEdits',
];
const DEFAULT_ALLOWED_TOOLS = 'Bash,Edit,Write,Read,Glob,Grep';

/** Pull the first JSON object out of a model reply (bare, fenced, or embedded). */
export function extractJson(text) {
  if (typeof text !== 'string') return null;
  let t = text.trim();
  // Strip a leading ```json / ``` fence if the model wrapped its reply.
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) t = fence[1].trim();
  // Try, in order: the text as-is; the outermost {object} or [array] embedded in prose.
  // Each attempt is also retried with trailing commas stripped (a common model malformation
  // that breaks JSON.parse). Hardened 2026-07-17 to cut transient reviewer abstains.
  const stripTrailingCommas = (s) => s.replace(/,(\s*[}\]])/g, '$1');
  // Grok CLI plain output (2026-08-20 gate-3 probe): the model can emit JSON whose
  // string values contain LITERAL newlines/control chars — invalid JSON that broke
  // Jumper Gate-3 as a phantom "transport failure". Last-resort candidate: control
  // chars → spaces (legal between tokens, content-neutral inside prose strings).
  const stripControlChars = (s) => s.replace(/[\u0000-\u001F]/g, ' ');
  const candidates = [
    t,
    (t.match(/\{[\s\S]*\}/) || [])[0],
    (t.match(/\[[\s\S]*\]/) || [])[0],
  ];
  for (const c of candidates) {
    if (typeof c !== 'string' || !c) continue;
    try { return JSON.parse(c); } catch { /* try comma-stripped */ }
    try { return JSON.parse(stripTrailingCommas(c)); } catch { /* try control-char-sanitized */ }
    try { return JSON.parse(stripControlChars(stripTrailingCommas(c))); } catch { /* next candidate */ }
  }
  return null;
}

/**
 * Parse the full `claude -p --output-format stream-json --verbose` stdout into
 * `{ text, rec }`. PURE + testable (symmetric to gemini-cli's `parseGeminiCliFrames`),
 * so the SR-5 attestation logic is unit-tested with no subprocess.
 *
 * Served-model discovery (Phase 1.3): the Claude stream exposes the served model on
 * (in order of authority) the `result` envelope's `model`, then each `assistant`
 * message's `message.model`, then the `system`/init envelope's `model`. Whichever is
 * present POSITIVELY attests (`model_attested:true`); if NONE exposes a served-model id
 * the stamp DEGRADES (SR-5 — never fabricate). Today `claude -p` emits the model on the
 * assistant/init frames, so the positive branch is exercised live; the degrade branch
 * is the documented fallback if a future CLI build drops the field.
 * @param {string} stdout            raw newline-delimited JSON frames
 * @param {object} [meta]
 * @param {string} [meta.label]
 * @param {?number}[meta.cli_status] process exit code
 * @returns {{ text:string, rec:object }}
 */
export const CANONICAL_FABLE_MODEL = 'claude-fable-5-2';
export const CANONICAL_STANDARD_CLAUDE_MODEL = 'claude-opus-5-5';
const CLAUDE_MOVING_ALIASES = new Set(['best', 'opus', 'sonnet', 'haiku']);

const CLAUDE_ENTITLEMENT_FALLBACK_LADDER = Object.freeze({
  best: Object.freeze(['opus', 'sonnet']),
  'claude-fable-5-2': Object.freeze(['claude-opus-5-5', 'opus', 'sonnet']),
  opus: Object.freeze(['sonnet']),
});

const CLAUDE_QUOTA_WALL_RE = /\b(?:hit\s+your\s+limit|weekly\s+limit|usage\s+limit\s+reached|rate_limit_error|quota\s+exceeded)\b/i;

export function isClaudeQuotaWall(rec, finalEnv = null, result = null) {
  if (!rec || rec.ok) return false;
  if (Number(rec.tools) > 0) return false;
  if (rec.status === 'rate_limit') return true;
  const combined = [
    rec.error,
    typeof finalEnv?.result === 'string' ? finalEnv.result : '',
    typeof result?.stderr === 'string' ? result.stderr : '',
  ].filter(Boolean).join(' ');
  return CLAUDE_QUOTA_WALL_RE.test(combined);
}

/**
 * Positive served-model attestation gate for `claude-fable-5-2` (and `claude-opus-5-5`
 * on Standard/Light verification seats under Variable Strength).
 * Refuses silent substitution or unattested replies fail-closed unless a legitimate
 * non-verification credit-gate fallback recorded `fallback_from_model` or an explicit
 * quota-wall Heavy->Light step-down recorded `quota_stepdown_from`.
 */
export function attestClaudeFableReceipt(rec, {
  requestedModel = rec?.requested_model ?? null,
  label = rec?.label ?? '(unlabeled)',
  role = rec?.role ?? null,
} = {}) {
  if (!rec || typeof rec !== 'object' || rec.ok !== true) return rec;
  const verification = isClaudeVerificationSeat({ role, label });
  const normalizedReq = normalizeClaudeFableModel(requestedModel);
  const normalizedServed = typeof rec.model_served === 'string'
    ? normalizeClaudeFableModel(rec.model_served)
    : null;
  if (normalizedReq === 'sonnet' && verification) {
    const isSonnet = normalizedServed === 'sonnet' || /^claude-sonnet-\d/i.test(String(normalizedServed || ''));
    if (rec.model_attested === true && isSonnet) {
      return rec;
    }
    const servedDesc = rec.model_attested === true && rec.model_served ? rec.model_served : 'unattested';
    rec.ok = false;
    rec.status = 'attestation_mismatch';
    rec.replay_safe = false;
    rec.error = `Claude positive attestation failed (${label}): requested sonnet but served ${servedDesc}`;
    return rec;
  }
  if (normalizedReq === CANONICAL_STANDARD_CLAUDE_MODEL && verification) {
    if (rec.model_attested === true && normalizedServed === CANONICAL_STANDARD_CLAUDE_MODEL) {
      rec.model_served = CANONICAL_STANDARD_CLAUDE_MODEL;
      return rec;
    }
    const servedDesc = rec.model_attested === true && rec.model_served ? rec.model_served : 'unattested';
    rec.ok = false;
    rec.status = 'attestation_mismatch';
    rec.replay_safe = false;
    rec.error = `Claude positive attestation failed (${label}): requested ${CANONICAL_STANDARD_CLAUDE_MODEL} but served ${servedDesc}`;
    return rec;
  }
  if (normalizedReq !== CANONICAL_FABLE_MODEL) return rec;
  if (!verification && rec.fallback_from_model === CANONICAL_FABLE_MODEL) return rec;
  if (rec.allow_quota_stepdown === true
      && rec.quota_stepdown_from === CANONICAL_FABLE_MODEL
      && rec.model_attested === true
      && normalizedServed === CANONICAL_STANDARD_CLAUDE_MODEL) {
    rec.model_served = CANONICAL_STANDARD_CLAUDE_MODEL;
    return rec;
  }
  if (rec.model_attested === true && normalizedServed === CANONICAL_FABLE_MODEL) {
    rec.model_served = CANONICAL_FABLE_MODEL;
    return rec;
  }
  const servedDesc = rec.model_attested === true && rec.model_served
    ? rec.model_served
    : 'unattested';
  rec.ok = false;
  rec.status = 'attestation_mismatch';
  rec.replay_safe = false;
  rec.error = `Claude positive attestation failed (${label}): requested ${CANONICAL_FABLE_MODEL} but served ${servedDesc}`;
  return rec;
}

const CLAUDE_CREDIT_GATE_RE = /\b(?:requires?\s+(?:extra\s+)?usage\s+credits|credits_required|model_requires_usage_credits|switch\s+to\s+another\s+model|not\s+entitled\s+to\s+model|model\s+is\s+not\s+available\s+on\s+your\s+plan)\b/i;

export function isClaudeModelCreditGate(rec, finalEnv = null, result = null) {
  if (!rec || rec.ok) return false;
  if (Number(rec.tools) > 0) return false;
  const code = String(rec.api_error_code || finalEnv?.api_error_code || '').trim().toLowerCase();
  if (code === 'credits_required' || code === 'model_requires_usage_credits') return true;
  const combined = [
    rec.error,
    typeof finalEnv?.result === 'string' ? finalEnv.result : '',
    typeof result?.stderr === 'string' ? result.stderr : '',
  ].filter(Boolean).join(' ');
  return CLAUDE_CREDIT_GATE_RE.test(combined);
}

export function parseClaudeFrames(stdout, {
  label = '(unlabeled)', cli_status = null, requested_model = null,
} = {}) {
  let finalEnv = null, lastText = '', tools = 0, servedModel = null;
  let apiErrorCode = null, apiErrorStatus = null;
  for (const raw of String(stdout).split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    let o; try { o = JSON.parse(line); } catch { continue; }
    if (typeof o.api_error_code === 'string' && o.api_error_code.trim()) {
      apiErrorCode = o.api_error_code.trim();
    }
    if (typeof o.api_error_status === 'number' && Number.isFinite(o.api_error_status)) {
      apiErrorStatus = o.api_error_status;
    }
    if (o.type === 'assistant' && o.message?.content) {
      if (typeof o.message.model === 'string' && o.message.model && !o.message.model.startsWith('<')) {
        servedModel = o.message.model;
      }
      for (const x of o.message.content) {
        if (x.type === 'tool_use') { tools++; }
        else if (x.type === 'text' && x.text?.trim()) { lastText = x.text.trim(); }
      }
    } else if (o.type === 'result') {
      finalEnv = o;
      if (typeof o.model === 'string' && o.model && !o.model.startsWith('<')) {
        servedModel = o.model; // most authoritative
      }
    }
  }
  const ok = cli_status === 0 && !!finalEnv && finalEnv.is_error === false;
  const envError = !ok
    ? ((typeof finalEnv?.result === 'string' && finalEnv.result.trim())
      || (typeof finalEnv?.error === 'string' && finalEnv.error.trim())
      || (typeof finalEnv?.error?.message === 'string' && finalEnv.error.message.trim())
      || (Array.isArray(finalEnv?.errors)
        ? finalEnv.errors.map(e => (typeof e === 'string' ? e : e?.message || '')).filter(Boolean).join('; ')
        : '')
      || (finalEnv?.is_error ? lastText : ''))
    : '';
  const rec = {
    label, cli_status,
    ok,
    status: ok
      ? 'success'
      : 'cli_error',
    requested_model,
    duration_ms: finalEnv?.duration_ms ?? null, tools,
    output_tokens: finalEnv?.usage?.output_tokens ?? null,
    cost_usd: finalEnv?.total_cost_usd ?? null,
    // Attribution (Anchor S3): the seat's own session and its measured usage ride
    // the internal physical receipt so the dispatcher's sink can record them.
    session_id: typeof finalEnv?.session_id === 'string' ? finalEnv.session_id : null,
    usage: finalEnv?.usage && typeof finalEnv.usage === 'object' ? finalEnv.usage : null,
    ...(envError ? { error: String(envError).trim().slice(0, 500) } : {}),
    ...(apiErrorCode ? { api_error_code: apiErrorCode } : {}),
    ...(apiErrorStatus !== null ? { api_error_status: apiErrorStatus } : {}),
    ...attestStamp(servedModel ? normalizeClaudeFableModel(servedModel) : null), // SR-5 served-model stamp
  };
  rec.model_family = rec.ok ? 'claude' : null;
  rec.family_attested = rec.ok;
  return { text: finalEnv?.result ?? lastText ?? '', rec, _finalEnv: finalEnv };
}

/**
 * Resolve the designated Claude model for this call — the per-role ladder, mirroring
 * `resolveGeminiModel` (gemini-cli.mjs): explicit `model` wins, then a per-role env
 * (`CLAUDE_MODEL_<ROLE>`, role taken from `role` else the label's prefix before
 * ':' / '#' / '.'), then the global `CLAUDE_MODEL`, else null (the CLI session
 * default — the pre-existing behavior, so unset env changes nothing).
 * This is what makes `CLAUDE_MODEL_EXECUTE=claude-fable-5` (etc.) reachable on every
 * path that flows through this driver.
 */
/**
 * TRIO_TIER (John 2026-07-04): one switch that flips every Claude seat of a run.
 *  - heavy    => the latest frontier Claude ("Fable builds") — for work that
 *                genuinely needs the top tier.
 *  - standard => one notch below frontier — the affordable default for builds
 *                whose rigor lives in the machinery (gates/reviewers/guards),
 *                not the builder's model tier.
 * Both tiers keep the 5:1 pattern (Gemini holds the checking seats regardless).
 * Precedence: an explicit opts.model (e.g. a project's foreman.config.json
 * models block) still wins over everything; TRIO_TIER, when set, deliberately
 * BEATS the setx-pinned CLAUDE_MODEL/CLAUDE_MODEL_<ROLE> user env — those encode
 * the old always-heavy default, and the point of the switch is to flip a run
 * without unpinning machine-wide env. Update ids when a new frontier ships.
 */
const TIER_CLAUDE_MODELS = {
  heavy: 'claude-fable-5-2',
  // one notch below frontier (2026-11-19): Opus 5.5 — below Fable 5.2
  standard: 'claude-opus-5-5',
  light: 'claude-opus-5-5',
};

/** The Claude model ONE NOTCH BELOW frontier (the `standard` tier) — the failover target when a
 * non-Claude verification seat can't serve its attested requested model. Symbolic so it TRACKS
 * the ladder as frontier ships forward; never hard-coded at the call site (John 2026-07-17). */
export function belowFrontierClaudeModel() { return TIER_CLAUDE_MODELS.standard; }

export function resolveClaudeModel({ model, role, label, tier = null, env = process.env, variableStrength = false } = {}) {
  const verificationSeat = isClaudeVerificationSeat({ role, label });
  if (model && !verificationSeat) return model;
  if (model && verificationSeat && model !== 'best' && model !== 'latest_supported') return model;
  const rawTier = String(tier || env.ANCHOR_STRENGTH || env.TRIO_TIER || '').trim().toLowerCase();
  const effTier = rawTier === 'regular' ? 'standard' : rawTier;
  if (effTier && TIER_CLAUDE_MODELS[effTier]) {
    if (effTier === 'light' || (variableStrength && effTier === 'standard')) {
      return TIER_CLAUDE_MODELS[effTier];
    }
    return verificationSeat ? TIER_CLAUDE_MODELS.heavy : TIER_CLAUDE_MODELS[effTier];
  }
  const key = normalizeRole({ role, label }) || '';
  const roleKey = key ? `CLAUDE_MODEL_${key.toUpperCase().replace(/[^A-Z0-9]+/g, '_')}` : null;
  return (roleKey && env[roleKey]) || env.CLAUDE_MODEL || null;
}

const CLAUDE_PREFLIGHT_CACHE = new Map();
const CLAUDE_PREFLIGHT_TTL_MS = 5 * 60 * 1000;

/**
 * Deterministic `claude auth status --json` preflight (`loggedIn === true`).
 * Surfaces an immediate typed `auth_expired` / `login_required` status before
 * Wave 1 or a live turn spawns, authorizing clean failover (`replay_safe: true`).
 */
export function preflightClaudeSubscription({
  cmd = process.platform === 'win32' ? 'claude.exe' : 'claude',
  env = process.env,
  spawnSyncImpl = spawnSync,
  cache = CLAUDE_PREFLIGHT_CACHE,
  now = Date.now,
} = {}) {
  const key = `${cmd}\0${env.CLAUDE_CONFIG_DIR || env.USERPROFILE || env.HOME || ''}`;
  const nowMs = Number(now());
  const cached = cache?.get(key);
  if (cached && Number.isFinite(nowMs) && nowMs - cached.checked_at_ms < CLAUDE_PREFLIGHT_TTL_MS) {
    return cached.result;
  }
  if (cached) cache.delete(key);
  const childEnv = policyEnvironment(env);
  const probe = spawnSyncImpl(cmd, ['auth', 'status', '--json'], {
    env: childEnv, shell: false, windowsHide: true, encoding: 'utf8', timeout: 15_000,
  });
  const detail = `${probe?.error?.message || ''}\n${probe?.stdout || ''}\n${probe?.stderr || ''}`.trim();
  if (probe?.error?.code === 'ETIMEDOUT' || /timed out|timeout/i.test(String(probe?.error?.message || ''))) {
    return {
      ok: false, status: 'preflight_timeout', subscription_auth: null, replay_safe: true,
      error: `Claude auth status probe timed out${detail ? `: ${detail}` : ''}`.slice(0, 500),
    };
  }
  if (probe?.error || probe?.status == null) {
    return {
      ok: false, status: 'spawn_error', subscription_auth: null, replay_safe: true,
      error: `Claude auth status probe could not start${detail ? `: ${detail}` : ''}`.slice(0, 500),
    };
  }
  let parsed = null;
  try { parsed = JSON.parse(String(probe.stdout || '').trim()); } catch { parsed = null; }
  if (parsed && typeof parsed === 'object') {
    if (parsed.loggedIn === true) {
      const result = {
        ok: true, status: 'ready', subscription_auth: true,
        auth_method: parsed.authMethod ?? null,
      };
      cache?.set(key, { checked_at_ms: nowMs, result });
      return result;
    }
    return {
      ok: false, status: 'auth_expired', login_required: true,
      subscription_auth: false, replay_safe: true,
      error: (parsed.error || detail || 'Claude CLI is not logged in (loggedIn:false)').slice(0, 300),
    };
  }
  if (probe.status === 0 && /\blogged\s*in\b/i.test(detail) && !/\bnot\s+logged\s+in\b/i.test(detail)) {
    const result = { ok: true, status: 'ready', subscription_auth: true };
    cache?.set(key, { checked_at_ms: nowMs, result });
    return result;
  }
  return {
    ok: false, status: 'auth_expired', login_required: true,
    subscription_auth: false, replay_safe: true,
    error: detail.slice(0, 300) || 'Claude CLI authentication required (run `claude auth login`)',
  };
}

/**
 * Live transport: spawn `claude -p` and resolve `{ text, rec }` once the stream's
 * result envelope arrives. ENV-GATED — throws unless CRUCIBLE_AGENT_LIVE=1 so it
 * can never fire by accident (tests inject a stub instead).
 */
export function defaultRunClaude(fullPrompt, label, {
  env = process.env,
  target = process.cwd(),
  allowedTools = DEFAULT_ALLOWED_TOOLS,
  model = null,
  role = null,
  tier = null,
  sandbox = null,
  repairOnly = false,
  timeoutMs = (Number(env.CLAUDE_CALL_TIMEOUT_MS) || 20 * 60000),
  signal = null,
  log = () => {},
  processRunner = runCloseBoundProcess,
  preflightImpl = undefined,
  policyResolver = undefined,
  spawnImpl,
  spawnSyncImpl,
  platform = process.platform,
  killImpl,
} = {}) {
  if (env.CRUCIBLE_AGENT_LIVE !== '1') {
    throw new HaltError(
      'live agent seam is disabled',
      'set CRUCIBLE_AGENT_LIVE=1 to spawn a real `claude -p` sub-agent, or inject a stub `runClaude` (tests/orchestrator)',
    );
  }
  const baseArgs = [...BASE_ARGS, '--allowedTools', allowedTools];
  const verificationSeat = isClaudeVerificationSeat({ role, label });
  if (repairOnly || allowedTools === '') {
    const modeIndex = baseArgs.indexOf('--permission-mode');
    if (modeIndex !== -1) baseArgs[modeIndex + 1] = 'plan';
    const toolsIndex = baseArgs.indexOf('--allowedTools');
    if (toolsIndex !== -1) baseArgs[toolsIndex + 1] = '';
    if (!baseArgs.includes('--tools=') && !baseArgs.includes('--tools')) {
      baseArgs.push('--tools=');
    }
  } else if (sandbox === 'read-only' || verificationSeat) {
    const modeIndex = baseArgs.indexOf('--permission-mode');
    if (modeIndex !== -1) baseArgs[modeIndex + 1] = 'plan';
    const toolsIndex = baseArgs.indexOf('--allowedTools');
    if (toolsIndex !== -1) baseArgs[toolsIndex + 1] = 'Read,Glob,Grep';
  }
  const explicitCallModel = typeof model === 'string' && model.trim() ? model.trim() : null;
  const effectiveTier = tier ?? env.ANCHOR_STRENGTH ?? env.TRIO_TIER ?? null;
  const normTier = normalizeStrength(effectiveTier, null);
  const heavyTier = normTier === 'heavy';
  let loadedPrefs = null;
  try { loadedPrefs = loadPolicyPrefs(env); } catch { loadedPrefs = null; }
  const vsActive = isVariableStrengthActive({ settings: loadedPrefs, env, tier: effectiveTier });
  const explicitResolved = resolveClaudeModel({
    model: verificationSeat ? explicitCallModel : explicitCallModel,
    role,
    label,
    env,
    variableStrength: vsActive,
  });
  const vsCfg = vsActive ? effectiveVariableStrengthConfig(loadedPrefs?.model_policy) : null;
  let selection;
  if (typeof policyResolver === 'function') {
    selection = policyResolver('claude', {
      env,
      role,
      label,
      model: verificationSeat ? null : explicitCallModel,
      tier: effectiveTier,
      skill: env.ANCHOR_SKILL || null,
    });
  } else if (processRunner === runCloseBoundProcess) {
    selection = resolveModelPolicy('claude', {
      env,
      role,
      label,
      model: verificationSeat ? null : (vsActive ? explicitCallModel : explicitResolved),
      tier: effectiveTier,
      skill: env.ANCHOR_SKILL || null,
    });
    if (!verificationSeat && !vsActive && !(heavyTier && !explicitCallModel)
        && explicitResolved && explicitResolved !== 'best' && selection.model !== explicitResolved) {
      selection = {
        ...selection,
        model: explicitResolved,
        selection_evidence: 'explicit_role_model',
      };
    }
  } else if (vsActive) {
    const resolvedTier = normTier || resolveSkillStrength({
      skill: env.ANCHOR_SKILL,
      explicitStrength: effectiveTier,
      inheritedStrength: env.ANCHOR_INHERITED_STRENGTH,
      cockpitStrength: env.ANCHOR_COCKPIT_STRENGTH,
      defaultStrength: vsCfg?.default_strength || 'standard',
      settings: loadedPrefs,
      env,
    });
    const fallbackRows = CLAUDE_CATALOG_MODELS.map((m, idx) => ({
      model: m,
      efforts: ['low', 'medium', 'high', 'max'],
      rank: idx,
    }));
    const vsPick = selectStrength('claude', fallbackRows, resolvedTier, loadedPrefs?.model_policy);
    selection = {
      family: 'claude',
      model: (!verificationSeat && explicitCallModel && explicitCallModel !== 'best') ? explicitCallModel : vsPick.model,
      effort: vsPick.effort,
      requested_strength: resolvedTier,
      selection_evidence: resolvedTier === 'heavy' && vsCfg?.heavy?.model_steps_below === 0
        ? 'heavy_review_fable_pin'
        : vsPick.selection_evidence,
    };
  } else {
    const pinnedHeavyOrReview = verificationSeat || (heavyTier && !explicitCallModel);
    selection = {
      family: 'claude',
      model: pinnedHeavyOrReview
        ? TIER_CLAUDE_MODELS.heavy
        : (explicitResolved || null),
      effort: pinnedHeavyOrReview ? 'max' : null,
      ...(pinnedHeavyOrReview ? { selection_evidence: 'heavy_review_fable_pin' } : {}),
    };
  }
  const mdl = selection.model;
  const cmdName = platform === 'win32' ? 'claude.exe' : 'claude';
  const childEnv = policyEnvironment(env);

  if (signal?.aborted) {
    return Promise.resolve({
      text: '',
      rec: {
        label, cli_status: null, ok: false, status: 'aborted', aborted: true,
        requested_model: mdl, model_served: null, model_family: null,
        family_attested: false, model_attested: false, degraded: true,
      },
    });
  }

  if (typeof preflightImpl === 'function' || processRunner === runCloseBoundProcess) {
    const preflightFn = typeof preflightImpl === 'function' ? preflightImpl : preflightClaudeSubscription;
    const preflight = preflightFn({
      cmd: cmdName, env, ...(spawnSyncImpl ? { spawnSyncImpl } : {}),
    });
    if (!preflight.ok) {
      return Promise.resolve({
        text: '',
        rec: {
          label, cli_status: null, ok: false,
          status: preflight.status || 'auth_expired',
          login_required: preflight.login_required === true,
          error: preflight.error || 'Claude subscription authentication required',
          requested_model: mdl, requested_effort: selection.effort ?? null,
          model_served: null, model_family: null,
          family_attested: false, model_attested: false, degraded: true,
          subscription_cli: true, subscription_auth: preflight.subscription_auth ?? false,
          timed_out: false, replay_safe: true,
          replay_evidence: 'subscription_preflight_rejected_before_prompt_spawn',
        },
      });
    }
  }

  const invokeModel = (activeSelection) => {
    const modelArgs = activeSelection.effort
      ? modelLaunchArgs(activeSelection)
      : (activeSelection.model ? ['--model', activeSelection.model] : []);
    const pinArgs = activeSelection.model && !CLAUDE_MOVING_ALIASES.has(activeSelection.model)
      ? ['--settings', '{"switchModelsOnFlag":false}']
      : [];
    const launchArgs = [...baseArgs, ...modelArgs, ...pinArgs];
    return processRunner({
      command: cmdName,
      args: launchArgs,
      options: { cwd: target, env: childEnv, shell: false, windowsHide: true },
      input: fullPrompt,
      signal,
      timeoutMs,
      label,
      log,
      ...(spawnImpl ? { spawnImpl } : {}),
      ...(spawnSyncImpl ? { spawnSyncImpl } : {}),
      platform,
      ...(killImpl ? { killImpl } : {}),
    });
  };

  const evaluateResult = (result, activeSelection) => {
    const activeModel = activeSelection.model;
    const { text, rec, _finalEnv } = parseClaudeFrames(result.stdout, {
      label,
      cli_status: result.code,
      requested_model: activeModel,
    });
    const outcome = classifySubscriptionOutcome({ family: 'claude', ...result });
    rec.replay_safe = !rec.ok && outcome.replay_safe;
    rec.replay_evidence = outcome.replay_evidence;
    if (!rec.ok && outcome.failure_status) rec.status = outcome.failure_status;
    if (result.terminal !== 'closed') {
      rec.ok = false;
      rec.status = result.terminal;
      rec.error = result.error || result.stderr.slice(0, 500);
    }
    if (rec.ok && (
      normalizeClaudeFableModel(activeModel) === CANONICAL_FABLE_MODEL
      || (verificationSeat && normalizeClaudeFableModel(activeModel) === CANONICAL_STANDARD_CLAUDE_MODEL)
    )) {
      attestClaudeFableReceipt(rec, { requestedModel: activeModel, label, role });
    }
    rec.timed_out = result.terminal === 'timeout';
    rec.requested_effort = activeSelection.effort;
    rec.model_policy = activeSelection;
    rec.highest_effort_verified = activeSelection.effort === 'max' || !activeSelection.requested_strength || activeSelection.requested_strength === 'heavy';
    rec.aborted = result.terminal === 'aborted';
    rec.kill_status = result.kill_status;
    if (!_finalEnv) {
      log(`!! ${label}: no result envelope. stderr=${result.stderr.slice(0, 300)}`);
    }
    return { text, rec, _finalEnv, result };
  };

  return invokeModel(selection).then(async (initialResult) => {
    const initial = evaluateResult(initialResult, selection);
    if (
      !initial.rec.ok
      && initialResult.terminal === 'closed'
      && !signal?.aborted
      && env.ANCHOR_ALLOW_HEAVY_QUOTA_STEPDOWN === '1'
      && normalizeClaudeFableModel(mdl) === CANONICAL_FABLE_MODEL
      && isClaudeQuotaWall(initial.rec, initial._finalEnv, initialResult)
    ) {
      log(`   !! ${label}: Claude frontier model '${mdl}' hit subscription quota wall — stepping down once to '${CANONICAL_STANDARD_CLAUDE_MODEL}' @ medium (degraded:true)`);
      const quotaStepdownSelection = {
        ...selection,
        model: CANONICAL_STANDARD_CLAUDE_MODEL,
        effort: 'medium',
        requested_strength: 'light',
        quota_stepdown_from: CANONICAL_FABLE_MODEL,
        selection_evidence: `${selection.selection_evidence || 'heavy_review_fable_pin'}+quota_wall_stepdown`,
      };
      const stepRaw = await invokeModel(quotaStepdownSelection);
      const stepEval = evaluateResult(stepRaw, quotaStepdownSelection);
      if (stepEval.rec.ok) {
        stepEval.rec.degraded = true;
        stepEval.rec.allow_quota_stepdown = true;
        stepEval.rec.quota_stepdown_from = CANONICAL_FABLE_MODEL;
        stepEval.rec.effective_strength = 'light';
        stepEval.rec.initial_requested_model = mdl;
        return { text: stepEval.text, rec: stepEval.rec };
      }
    }
    const blockSameFamilyStepdown = (verificationSeat || heavyTier) && mdl === CANONICAL_FABLE_MODEL;
    if (
      initial.rec.ok
      || blockSameFamilyStepdown
      || initialResult.terminal !== 'closed'
      || signal?.aborted
      || !isClaudeModelCreditGate(initial.rec, initial._finalEnv, initialResult)
    ) {
      return { text: initial.text, rec: initial.rec };
    }

    const fallbackModels = CLAUDE_ENTITLEMENT_FALLBACK_LADDER[String(mdl || '').toLowerCase()] || [];
    if (fallbackModels.length === 0) {
      return { text: initial.text, rec: initial.rec };
    }

    const primaryError = initial.rec.error;
    const attemptedModels = [mdl];
    let lastAttempt = initial;

    for (const nextModel of fallbackModels) {
      if (signal?.aborted) break;
      const prevModel = attemptedModels.at(-1);
      attemptedModels.push(nextModel);
      log(`   !! ${label}: Claude model '${prevModel}' requires usage credits — retrying with subscription model '${nextModel}'`);
      const fallbackSelection = {
        ...selection,
        model: nextModel,
        fallback_from_model: mdl,
        selection_evidence: `${selection.selection_evidence || 'provider_moving_alias'}+entitlement_fallback`,
      };
      const retryRaw = await invokeModel(fallbackSelection);
      const retryEval = evaluateResult(retryRaw, fallbackSelection);
      lastAttempt = retryEval;
      if (retryEval.rec.ok) {
        retryEval.rec.fallback_from_model = mdl;
        retryEval.rec.initial_requested_model = mdl;
        retryEval.rec.attempted_models = attemptedModels;
        return { text: retryEval.text, rec: retryEval.rec };
      }
      if (
        retryRaw.terminal !== 'closed'
        || !isClaudeModelCreditGate(retryEval.rec, retryEval._finalEnv, retryRaw)
      ) {
        break;
      }
    }

    if (primaryError && !lastAttempt.rec.error) {
      lastAttempt.rec.error = primaryError;
    } else if (primaryError) {
      lastAttempt.rec.error = primaryError;
    }
    lastAttempt.rec.requested_model = mdl;
    lastAttempt.rec.initial_requested_model = mdl;
    lastAttempt.rec.attempted_models = attemptedModels;
    return { text: lastAttempt.text, rec: lastAttempt.rec };
  });
}

/**
 * Build the `agent()` seam.
 * @param {object} [o]
 * @param {?Function} [o.runClaude]  injected transport `(prompt,label)=>Promise<{text}>`
 *                                   (omit to use the env-gated live `claude -p`).
 * @param {object}    [o.env=process.env]
 * @param {string}    [o.target=process.cwd()]  cwd for the live sub-agent
 * @param {string}    [o.allowedTools]
 * @param {Function}  [o.log=()=>{}]
 * @returns {{ agent: (prompt:string, opts?:object)=>Promise<any> }}
 */
export function makeAgentSeam(options = {}) {
  const {
    runClaude = null,
    env = process.env,
    target = process.cwd(),
    allowedTools = DEFAULT_ALLOWED_TOOLS,
    log = () => {},
  } = options;
  // Per-call opts (model/role) thread through as a third arg so the per-role model
  // ladder is reachable; injected `runClaude` stubs keep their 2-arg shape unharmed.
  const run = runClaude || ((prompt, label, callOpts = {}) =>
    defaultRunClaude(prompt, label, { ...options, env, target, allowedTools, log, ...callOpts }));

  async function agent(prompt, opts = {}) {
    const label = opts.label || '(unlabeled)';
    const callOpts = {
      model: opts.model,
      role: normalizeRole({ role: opts.role, label }),
      timeoutMs: opts.timeoutMs,
      signal: opts.signal,
    };
    return runCliSchemaAttempts({
      run,
      prompt,
      schema: opts.schema,
      label,
      callOpts,
      driverOpts: opts,
      familyName: 'Claude',
      log,
      parse: extractJson,
    });
  }

  return { agent };
}

/**
 * The Claude registry entry (the trio's default backend).
 *
 * `runAgent` is the pluggable interface (`drivers/index.mjs` dispatches to it):
 * it builds the env-gated/stubbable `agent()` seam and invokes it once. A test or
 * orchestrator may inject `runClaude` (a stub transport) to drive the full
 * schema/retry/failure logic with no subprocess. `freshContext` is accepted for
 * interface parity — claude -p spawns a fresh sub-agent process, so a fresh context
 * is the native behavior and the flag is a no-op for this backend.
 *
 * @type {{ name: string, subAgentCapable: boolean, structuredOutput: string,
 *          runAgent: (opts?: object) => Promise<any> }}
 */
export const claudeDriver = {
  name: 'claude',
  subAgentCapable: true,
  // Structured output comes from the CLI sub-agent: the schema is appended to the
  // prompt and the reply is parsed (retry-once-then-failure). Contrast the raw-API
  // backends, which use native JSON-mode / function-calling.
  structuredOutput: 'cli-subagent (prompt-suffix)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, model, role, timeoutMs, signal } = opts;
    // makeAgentSeam reads runClaude/env/target/allowedTools/log from the same opts
    // bag; an absent runClaude falls back to the env-gated live transport.
    // model/role thread through to the per-role ladder (resolveClaudeModel).
    const { agent } = makeAgentSeam(opts);
    return agent(prompt, { ...opts, schema, label, model, role, timeoutMs, signal });
  },
};

export default claudeDriver;

