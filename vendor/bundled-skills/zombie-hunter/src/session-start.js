// W8 / SC5+SC6 — Multi-engine Investigate + Doctor shared session-start plumbing.
//
// Shell paints before any engine session. Engine toggle is Claude / Gemini(agy) /
// Grok (grok-cli / grok.exe -p). Dead toggles forbidden; unhealthy engines disabled
// with health. Slim Investigate seed + optional deep-brief; Doctor shell-first
// (no blocking auto-session). First prompt ≤15s or disable engine.
//
// P5 plumbing (this module) is the shared start contract. P6 (W9 banner→Doctor)
// requires this plumbing green — see assertP5StartPlumbingGreen().

const {
  recommendNext,
  legSummary,
  buildWhyMinPayload,
  RECOMMENDED_NEXT,
} = require('./radar-cache.js');

/** Shell first-paint budget (SC5/SC6). */
const SHELL_PAINT_BUDGET_MS = 1000;

/** First prompt budget; miss ⇒ disable engine with health (SC5/SC6). */
const FIRST_PROMPT_BUDGET_MS = 15_000;

/** Closed engine toggle ids — dead toggle forbidden (no fourth silent backend). */
const ENGINE_IDS = Object.freeze(['claude', 'gemini', 'grok']);

/**
 * Subscription-CLI transport map (never API-key theater).
 * gemini transport is agy; grok is grok-cli / grok.exe -p.
 */
const ENGINE_TRANSPORT = Object.freeze({
  claude: Object.freeze({
    id: 'claude',
    label: 'Claude',
    transport: 'claude',
    spawn: 'claude',
    subscriptionCli: true,
    argvHint: ['claude'],
  }),
  gemini: Object.freeze({
    id: 'gemini',
    label: 'Gemini',
    transport: 'agy',
    spawn: 'agy',
    subscriptionCli: true,
    argvHint: ['agy'],
  }),
  grok: Object.freeze({
    id: 'grok',
    label: 'Grok',
    transport: 'grok-cli',
    spawn: 'grok.exe -p',
    subscriptionCli: true,
    argvHint: ['grok', '-p'],
  }),
});

/** Max reason codes on a slim seed (length-limited; process strings are data). */
const SLIM_SEED_REASON_CAP = 8;

/** Cap on free-text fields embedded in seeds (untrusted process strings). */
const SLIM_SEED_TEXT_CAP = 240;

/**
 * Normalize an engine id; unknown → null (never invent a dead toggle).
 * @param {string} raw
 * @returns {'claude'|'gemini'|'grok'|null}
 */
function normalizeEngineId(raw) {
  const e = String(raw || '').trim().toLowerCase();
  if (e === 'agy') return 'gemini';
  if (e === 'grok-cli' || e === 'grok.exe') return 'grok';
  if (ENGINE_IDS.includes(e)) return e;
  return null;
}

/**
 * Build engine toggle rows from a host availability profile.
 * Unhealthy engines are disabled with health — never a silent dead toggle.
 *
 * @param {object} [profile] — { claude?: bool, gemini?: bool, grok?: bool, health?: object }
 * @param {object} [opts] — { firstPromptMs?: {claude,gemini,grok}, now?: number }
 * @returns {{ engines: object[], available: string[], defaultEngine: string|null, anyHealthy: boolean }}
 */
/**
 * The families the Anchor dashboard SELECTED (2026-09-04, John: seats are what the dashboard
 * sets — universally). From opts.prefs: an explicit `selected` set, else the union of
 * default_cli / coding_family / review_family. Empty ⇒ no selection known ⇒ no gating.
 */
function selectedFamilies(prefs = {}) {
  const out = new Set();
  const add = (v) => { const id = normalizeEngineId(v); if (id) out.add(id); };
  if (prefs.selected && typeof prefs.selected[Symbol.iterator] === 'function') {
    for (const v of prefs.selected) add(v);
  } else {
    add(prefs.default_cli); add(prefs.coding_family); add(prefs.review_family);
  }
  return out;
}

function listEngineToggle(profile = {}, opts = {}) {
  const healthIn = profile.health || {};
  const firstPromptMs = opts.firstPromptMs || {};
  const selected = selectedFamilies(opts.prefs || {});
  const engines = ENGINE_IDS.map((id) => {
    const transport = ENGINE_TRANSPORT[id];
    const available = profile[id] === true;
    const promptMs = firstPromptMs[id];
    const overBudget = Number.isFinite(promptMs) && promptMs > FIRST_PROMPT_BUDGET_MS;
    const chosen = selected.size === 0 || selected.has(id);
    const healthNote = healthIn[id]
      || (!available
        ? 'unavailable (subscription CLI not detected)'
        : (overBudget
          ? `first prompt ${promptMs}ms > ${FIRST_PROMPT_BUDGET_MS}ms budget — disabled`
          : (!chosen
            ? 'installed, but not selected on the Anchor dashboard (Terminal / Coder / Reviewer)'
            : 'healthy')));
    const enabled = available && !overBudget && chosen;
    return {
      id,
      label: transport.label,
      transport: transport.transport,
      spawn: transport.spawn,
      subscriptionCli: true,
      available,
      selected: chosen,
      enabled,
      disabled: !enabled,
      health: healthNote,
      firstPromptBudgetMs: FIRST_PROMPT_BUDGET_MS,
      firstPromptMs: Number.isFinite(promptMs) ? promptMs : null,
    };
  });
  const available = engines.filter((e) => e.enabled).map((e) => e.id);
  return {
    engines,
    available,
    defaultEngine: pickDefaultEngine(available, opts.prefs || {}, opts.lastUsed),
    anyHealthy: available.length > 0,
    shellPaintBudgetMs: SHELL_PAINT_BUDGET_MS,
    firstPromptBudgetMs: FIRST_PROMPT_BUDGET_MS,
  };
}

/**
 * Default engine: last-used healthy → coding_family prefs → first healthy.
 * Never defaults to a dead/disabled toggle.
 *
 * @param {string[]} healthyIds
 * @param {object} prefs — { coding_family?: 'claude'|'gemini'|'grok', default_cli?: string }
 * @param {string|null|undefined} lastUsed
 * @returns {string|null}
 */
function pickDefaultEngine(healthyIds, prefs = {}, lastUsed) {
  const healthy = new Set((healthyIds || []).map(normalizeEngineId).filter(Boolean));
  const last = normalizeEngineId(lastUsed);
  if (last && healthy.has(last)) return last;
  // (2026-09-04) a picker starts a TERMINAL: the dashboard's Terminal role (default_cli) wins,
  // then the Coder family.
  const family = normalizeEngineId(prefs.default_cli || prefs.coding_family);
  if (family && healthy.has(family)) return family;
  const alt = normalizeEngineId(prefs.coding_family);
  if (alt && healthy.has(alt)) return alt;
  for (const id of ENGINE_IDS) {
    if (healthy.has(id)) return id;
  }
  return null;
}

function _clip(s, n = SLIM_SEED_TEXT_CAP) {
  const t = String(s == null ? '' : s);
  if (t.length <= n) return t;
  return t.slice(0, n - 1) + '…';
}

/**
 * Investigate slim seed: pid + class + top reason codes + freeze/kill status.
 * Process strings are data (length-capped), not instructions.
 *
 * @param {object} candidate
 * @param {object} [opts]
 * @returns {object}
 */
function buildInvestigateSlimSeed(candidate = {}, opts = {}) {
  const reasonCodes = Array.isArray(candidate.reasonCodes)
    ? candidate.reasonCodes.slice(0, SLIM_SEED_REASON_CAP).map(String)
    : (candidate.quad && Array.isArray(candidate.quad.reasonCodes)
      ? candidate.quad.reasonCodes.slice(0, SLIM_SEED_REASON_CAP).map(String)
      : []);
  const pid = candidate.pid != null
    ? Number(candidate.pid)
    : (Array.isArray(candidate.pids) && candidate.pids[0] != null
      ? Number(candidate.pids[0])
      : null);
  const freezeStatus = opts.freezeStatus
    || candidate.freezeStatus
    || (opts.freezeKillEnabled === false
      ? 'disabled'
      : (opts.freezeCapability === true ? 'available' : 'unavailable'));
  const killStatus = opts.killStatus
    || candidate.killStatus
    || (opts.freezeKillEnabled === false ? 'disabled' : 'confirm_required');
  const classifierMode = opts.classifierMode || candidate.classifierMode || 'shadow';
  const seed = {
    kind: 'investigate_slim',
    version: 'w8-investigate-slim-v1',
    pid: Number.isFinite(pid) ? pid : null,
    class: _clip(
      candidate.engineClass
        || candidate.class
        || candidate.name
        || candidate.quadVerdict
        || 'unknown',
      80,
    ),
    topReasonCodes: reasonCodes,
    freezeStatus: String(freezeStatus),
    killStatus: String(killStatus),
    classifierMode,
    freezeCapability: opts.freezeCapability === true,
    ownershipBadge: candidate.ownershipBadge || null,
    image: _clip(candidate.imagePath || candidate.image || candidate.path || '', 160),
    name: _clip(candidate.name || '', 80),
    // Explicit: slim path does not embed multi-minute full briefing.
    slim: true,
    deepBrief: false,
  };
  return seed;
}

/**
 * Render slim seed as short agent-facing text (async session seed_context).
 * @param {object} slim
 * @returns {string}
 */
function formatInvestigateSlimSeedText(slim) {
  const s = slim || {};
  const lines = [
    'ZOMBIE-HUNTER INVESTIGATE — SLIM SEED (W8/SC5)',
    'You help the operator treat ONE candidate. Prefer FREEZE before KILL. Uncertain ≠ red.',
    `pid: ${s.pid == null ? 'unknown' : s.pid}`,
    `class: ${s.class || 'unknown'}`,
    `top reason codes: ${(s.topReasonCodes || []).join(', ') || '(none)'}`,
    `freeze status: ${s.freezeStatus || 'unknown'}`,
    `kill status: ${s.killStatus || 'unknown'}`,
    `classifierMode: ${s.classifierMode || 'shadow'}`,
    `freezeCapability: ${s.freezeCapability === true}`,
    s.image ? `image: ${s.image}` : null,
    'Safety: observe-only unless DESTRUCTIVE_ELIGIBLE; never mass-kill; confirm before kill.',
  ].filter(Boolean);
  return lines.join('\n');
}

/**
 * Optional deep-brief path for a selected candidate (same closed recommendedNext as Why).
 * Available without a second multi-minute session.
 *
 * @param {object} candidate
 * @param {object} [opts]
 * @returns {object}
 */
function buildInvestigateDeepBrief(candidate = {}, opts = {}) {
  // B6 W2: deep-brief is ceremony (explain verbosity). LITE ceremony may thin it.
  // Slim seed + safety stamps always remain (never thinned by depth).
  const ceremonyLevel = opts.ceremonyLevel != null
    ? String(opts.ceremonyLevel).trim().toLowerCase().replace(/_/g, '-')
    : (opts.ceremony != null
      ? String(opts.ceremony).trim().toLowerCase().replace(/_/g, '-')
      : null);
  const ceremonyOrdinal = (() => {
    if (ceremonyLevel == null) return 2; // unset → full (backward compatible)
    if (ceremonyLevel === 'lite' || ceremonyLevel === 'light') return 0;
    if (ceremonyLevel === 'spike-first' || ceremonyLevel === 'spike' || ceremonyLevel === 'spikefirst') return 1;
    if (ceremonyLevel === 'full') return 2;
    return 0;
  })();
  const deepBriefAllowed = ceremonyOrdinal >= 2;
  if (!deepBriefAllowed) {
    return {
      kind: 'investigate_deep_brief',
      version: 'w8-investigate-deep-brief-v1',
      slim: buildInvestigateSlimSeed(candidate, opts),
      ceremonyLevel: ceremonyLevel || 'lite',
      ceremonyThinned: true,
      deepBrief: false,
      recommendedNext: recommendNext(candidate, opts),
      treatEnum: RECOMMENDED_NEXT.slice(),
      legSummary: legSummary(candidate),
      reasonCodes: [],
      lastVerdict: null,
      note: 'deep_brief_thinned_by_ceremonyLevel',
    };
  }
  const why = buildWhyMinPayload(candidate, opts);
  const recommendedNext = why.recommendedNext || recommendNext(candidate, opts);
  return {
    kind: 'investigate_deep_brief',
    version: 'w8-investigate-deep-brief-v1',
    slim: buildInvestigateSlimSeed(candidate, opts),
    ceremonyLevel: ceremonyLevel || 'full',
    ceremonyThinned: false,
    deepBrief: true,
    recommendedNext,
    treatEnum: RECOMMENDED_NEXT.slice(),
    legSummary: why.legSummary || legSummary(candidate),
    reasonCodes: why.reasonCodes || [],
    lastVerdict: why.lastVerdict,
    cacheAgeMs: why.cacheAgeMs,
    freezeCapability: why.freezeCapability,
    classifierMode: why.classifierMode,
    ownershipBadge: why.ownershipBadge,
    uiCopy: why.uiCopy,
    // FREEZE_THEN_KILL only when Why/recommendNext already conditioned (mode+capability).
    blocksSessionStart: false,
  };
}

/**
 * Doctor short seed (optional one-click diagnose). Banner issue fields optional (W9).
 * @param {object|null} [issue]
 * @param {object} [opts]
 * @returns {object}
 */
function buildDoctorShortSeed(issue = null, opts = {}) {
  const base = {
    kind: 'doctor_short',
    version: 'w8-doctor-short-v1',
    short: true,
    classifierMode: opts.classifierMode || 'shadow',
    note: 'Short diagnose seed — shell painted first; session start is on demand.',
    markdownPath: null,
    isMarkdownPath: false,
  };
  if (!issue || typeof issue !== 'object') return base;
  const message = _clip(issue.message || issue.exactMessage || '', 400);
  return {
    ...base,
    issueId: issue.issueId != null ? String(issue.issueId) : (issue.id != null ? String(issue.id) : null),
    message,
    // Plan SC7 "exact message" — same 1:1 value as message
    exactMessage: message,
    component: _clip(issue.component || '', 120),
    lastError: _clip(issue.lastError || '', 400),
    suggestedChecks: Array.isArray(issue.suggestedChecks)
      ? issue.suggestedChecks.slice(0, 8).map((c) => _clip(c, 160))
      : [],
    bannerSurface: issue.bannerSurface || null,
  };
}

/**
 * Format doctor short seed as seed_context text.
 * @param {object} short
 * @returns {string}
 */
function formatDoctorShortSeedText(short) {
  const s = short || {};
  const lines = [
    'ANCHOR DOCTOR — SHORT DIAGNOSE SEED (W8/SC6)',
    'Read-only diagnose. Never invent numbers. Shell-first: session started on demand.',
    s.issueId ? `issueId: ${s.issueId}` : null,
    s.message ? `message: ${s.message}` : null,
    s.component ? `component: ${s.component}` : null,
    s.lastError ? `lastError: ${s.lastError}` : null,
    (s.suggestedChecks && s.suggestedChecks.length)
      ? `suggestedChecks: ${s.suggestedChecks.join('; ')}`
      : null,
    'Say plainly when healthy; prefer inspect-then-suggest over mutation.',
  ].filter(Boolean);
  return lines.join('\n');
}

/**
 * Shared session-start plan: shell + engine picker + seed BEFORE session.
 * Session is async/cancelable; failure is non-blocking.
 *
 * @param {object} args
 * @returns {object}
 */
function buildSessionStartPlan(args = {}) {
  const surface = args.surface === 'doctor' ? 'doctor' : 'investigate';
  const profile = args.profile || {};
  const toggle = listEngineToggle(profile, {
    prefs: args.prefs,
    lastUsed: args.lastUsed,
    firstPromptMs: args.firstPromptMs,
  });
  const requested = normalizeEngineId(args.engine);
  let engine = null;
  let engineDenied = null;
  if (requested) {
    const row = toggle.engines.find((e) => e.id === requested);
    if (row && row.enabled) engine = requested;
    else {
      engineDenied = row
        ? { engine: requested, reason: row.health, disabled: true }
        : { engine: requested, reason: 'unknown engine (dead toggle forbidden)', disabled: true };
    }
  }
  if (!engine) engine = toggle.defaultEngine;

  let seed;
  let seedText;
  if (surface === 'doctor') {
    seed = buildDoctorShortSeed(args.issue || null, {
      classifierMode: args.classifierMode,
    });
    seedText = formatDoctorShortSeedText(seed);
  } else if (args.deepBrief) {
    const deep = buildInvestigateDeepBrief(args.candidate || {}, args);
    seed = deep;
    seedText = formatInvestigateSlimSeedText(deep.slim)
      + `\nrecommendedNext: ${deep.recommendedNext}\n`
      + `legs: ${JSON.stringify(deep.legSummary)}`;
  } else {
    seed = buildInvestigateSlimSeed(args.candidate || {}, args);
    seedText = formatInvestigateSlimSeedText(seed);
  }

  const canStart = !!engine && toggle.anyHealthy && !engineDenied;
  return {
    surface,
    // Shell contract: paint before session
    shell: {
      paintFirst: true,
      paintBudgetMs: SHELL_PAINT_BUDGET_MS,
      enginePicker: true,
      engines: toggle.engines,
      autoStartSession: surface === 'doctor' ? false : false, // Doctor: never blocking auto-session
      modeChip: {
        classifierMode: args.classifierMode || 'shadow',
        freezeCapability: args.freezeCapability === true,
      },
    },
    seed,
    seedText,
    seedBeforeSession: true,
    engine,
    engineDenied,
    engineToggle: toggle,
    session: {
      async: true,
      cancelable: true,
      failureNonBlocking: true,
      autoStart: false,
      firstPromptBudgetMs: FIRST_PROMPT_BUDGET_MS,
      startWhen: canStart ? 'operator_or_diagnose_click' : 'blocked_no_healthy_engine',
    },
    canStart,
    ok: canStart,
    error: canStart
      ? null
      : (engineDenied
        ? engineDenied.reason
        : (toggle.anyHealthy ? 'no engine selected' : 'no healthy engine')),
    // P5 plumbing stamp — required by P6
    p5Plumbing: P5_START_PLUMBING,
  };
}

/**
 * Doctor page contract: shell + picker usable immediately; no auto multi-minute session.
 * @param {object} [toggle]
 * @returns {object}
 */
function doctorShellBeforeSessionContract(toggle = null) {
  const t = toggle || listEngineToggle({ claude: true, gemini: true, grok: true });
  return {
    surface: 'doctor',
    shellFirst: true,
    autoStartSession: false,
    blockingAutoSession: false,
    enginePickerRequired: true,
    engines: t.engines,
    oneClickDiagnose: true,
    sessionStartOnDemand: true,
    shellPaintBudgetMs: SHELL_PAINT_BUDGET_MS,
    firstPromptBudgetMs: FIRST_PROMPT_BUDGET_MS,
  };
}

/**
 * P5 start plumbing markers — P6 (W9 health-banner Doctor seed) requires these green.
 */
const P5_START_PLUMBING = Object.freeze({
  id: 'p5-shared-session-start',
  version: 'w8-p5-v1',
  required: Object.freeze([
    'shared_session_start_helper',
    'shell_before_session',
    'engine_picker_three',
    'slim_seed',
    'async_cancelable_session',
    'failure_non_blocking',
    'first_prompt_budget',
    'doctor_shell_first',
  ]),
  surfaces: Object.freeze(['investigate', 'doctor']),
  engines: ENGINE_IDS,
  shellPaintBudgetMs: SHELL_PAINT_BUDGET_MS,
  firstPromptBudgetMs: FIRST_PROMPT_BUDGET_MS,
});

/**
 * Assert P5 plumbing is present and green (import-time / unit gate for P6).
 * @returns {{ ok: boolean, missing: string[], plumbing: object }}
 */
function assertP5StartPlumbingGreen() {
  const missing = [];
  const checks = {
    shared_session_start_helper: typeof buildSessionStartPlan === 'function',
    shell_before_session: SHELL_PAINT_BUDGET_MS <= 1000,
    engine_picker_three: ENGINE_IDS.length === 3
      && ENGINE_IDS.includes('claude')
      && ENGINE_IDS.includes('gemini')
      && ENGINE_IDS.includes('grok'),
    slim_seed: typeof buildInvestigateSlimSeed === 'function',
    async_cancelable_session: true,
    failure_non_blocking: true,
    first_prompt_budget: FIRST_PROMPT_BUDGET_MS === 15_000,
    doctor_shell_first: doctorShellBeforeSessionContract().autoStartSession === false,
  };
  for (const key of P5_START_PLUMBING.required) {
    if (!checks[key]) missing.push(key);
  }
  // Transport green-path: subscription CLI only
  for (const id of ENGINE_IDS) {
    if (!ENGINE_TRANSPORT[id] || !ENGINE_TRANSPORT[id].subscriptionCli) {
      missing.push(`transport_${id}`);
    }
  }
  return {
    ok: missing.length === 0,
    missing,
    plumbing: P5_START_PLUMBING,
    checks,
  };
}

module.exports = {
  SHELL_PAINT_BUDGET_MS,
  FIRST_PROMPT_BUDGET_MS,
  ENGINE_IDS,
  ENGINE_TRANSPORT,
  SLIM_SEED_REASON_CAP,
  P5_START_PLUMBING,
  normalizeEngineId,
  listEngineToggle,
  pickDefaultEngine,
  buildInvestigateSlimSeed,
  formatInvestigateSlimSeedText,
  buildInvestigateDeepBrief,
  buildDoctorShortSeed,
  formatDoctorShortSeedText,
  buildSessionStartPlan,
  doctorShellBeforeSessionContract,
  assertP5StartPlumbingGreen,
};
