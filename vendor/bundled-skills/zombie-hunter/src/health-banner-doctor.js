// W9 / SC7 — Clickable dashboard health + reaper-health banners → Doctor seed.
//
// Banner click opens Doctor with 1:1 issue fields (issueId, exact message,
// component, lastError, suggestedChecks) — NEVER a static markdown file path.
// Async diagnose session start is attempted with that payload when an engine is
// enabled; start failure surfaces health and leaves the UI usable.
//
// Closed versioned Doctor issue catalog is reused where applicable (reason-catalog).
// Cross-surface fail-SAFE: dual-write scare surfaces stay non-actionable under shadow
// even when a health/reaper banner seeds Doctor.

const {
  getDoctorIssue,
  DOCTOR_ISSUE_CATALOG_VERSION,
} = require('./reason-catalog.js');
const {
  buildDoctorShortSeed,
  formatDoctorShortSeedText,
  buildSessionStartPlan,
  assertP5StartPlumbingGreen,
} = require('./session-start.js');
const {
  evaluateDualWriteSurfaces,
  assertNoActionableRedUnderShadow,
  SURFACES,
} = require('./dual-write.js');

/** Canonical 1:1 seed fields (plan SC7 / W9). */
const BANNER_SEED_FIELDS = Object.freeze([
  'issueId',
  'message',
  'component',
  'lastError',
  'suggestedChecks',
]);

/** Banner surface kinds that open Doctor (not Zombie Hunter radar). */
const BANNER_SURFACES = Object.freeze([
  'dashboard_health',
  'reaper_health',
]);

const BANNER_DOCTOR_SEED_VERSION = 'w9-banner-doctor-seed-v1';

const TEXT_CAP = 400;
const CHECK_CAP = 160;
const CHECK_MAX = 8;

function _clip(s, n = TEXT_CAP) {
  const t = String(s == null ? '' : s);
  if (t.length <= n) return t;
  return t.slice(0, n - 1) + '…';
}

/**
 * Normalize any raw banner/issue object into the closed 1:1 seed shape.
 * Prefer closed catalog defaults when issueId is known; overrides win for
 * exact message / lastError from the live banner.
 *
 * @param {object|null} raw
 * @param {object} [opts]
 * @returns {object|null}
 */
function normalizeBannerIssue(raw, opts = {}) {
  if (!raw || typeof raw !== 'object') return null;
  const idRaw = raw.issueId != null ? raw.issueId : (raw.id != null ? raw.id : null);
  const issueId = idRaw != null && String(idRaw).trim() !== '' ? String(idRaw) : null;
  const catalog = issueId ? getDoctorIssue(issueId) : null;

  const exactMessage = _clip(
    raw.message
      || raw.exactMessage
      || (catalog && catalog.message)
      || opts.defaultMessage
      || '',
    400,
  );
  const component = _clip(
    raw.component || (catalog && catalog.component) || opts.defaultComponent || '',
    120,
  );
  const lastError = _clip(raw.lastError || raw.error || opts.defaultLastError || '', 400);
  let checks = Array.isArray(raw.suggestedChecks)
    ? raw.suggestedChecks
    : (catalog && Array.isArray(catalog.suggestedChecks) ? catalog.suggestedChecks.slice() : []);
  if (!Array.isArray(checks)) checks = [];
  checks = checks.slice(0, CHECK_MAX).map((c) => _clip(c, CHECK_CAP)).filter(Boolean);

  return {
    issueId,
    // Plan wording: "exact message" — both keys hold the same 1:1 value.
    message: exactMessage,
    exactMessage,
    component,
    lastError,
    suggestedChecks: checks,
    // Metadata (not part of 1:1 seed fields)
    bannerSurface: BANNER_SURFACES.includes(raw.bannerSurface)
      ? raw.bannerSurface
      : (opts.bannerSurface || null),
    catalogAligned: !!(issueId && catalog),
    doctorIssueCatalogVersion: DOCTOR_ISSUE_CATALOG_VERSION,
    version: BANNER_DOCTOR_SEED_VERSION,
    // Explicit: seed is structured issue fields, not a markdown path.
    markdownPath: null,
    isMarkdownPath: false,
  };
}

/**
 * Dashboard health-check banner issue payload (Anchor top banner).
 * Replaces static health_reports/{date}.md path with Doctor-seeded diagnose.
 *
 * @param {object} [args]
 * @returns {object}
 */
function buildDashboardHealthBannerIssue(args = {}) {
  const reportDate = args.reportDate != null ? String(args.reportDate) : '';
  const status = args.status != null ? String(args.status) : 'ISSUES FOUND';
  const msg = args.message
    || `Health check found issues${reportDate ? ` on ${reportDate}` : ''} (${status})`;
  return normalizeBannerIssue({
    issueId: args.issueId || 'ZH_HEALTH_CHECK_ISSUES',
    message: msg,
    component: args.component || 'health-check',
    lastError: args.lastError || status,
    suggestedChecks: args.suggestedChecks,
    bannerSurface: 'dashboard_health',
  }, { bannerSurface: 'dashboard_health' });
}

/**
 * Reaper consecutive-abstain / chain-tampered health banner issue payload.
 *
 * @param {object} [args] — reaper_arming.health_banner() shape + optional overrides
 * @returns {object}
 */
function buildReaperHealthBannerIssue(args = {}) {
  const kind = String(args.kind || 'abstain-streak');
  const issueId = args.issueId
    || (kind === 'chain-tampered'
      ? 'ZH_REAPER_CHAIN_TAMPERED'
      : 'ZH_REAPER_ABSTAIN_STREAK');
  const msg = args.message
    || (kind === 'chain-tampered'
      ? 'Reaper receipt chain failed verification — owner-evidence log may be tampered.'
      : `Reaper has ABSTAINED for ${args.streak || '?'} consecutive sweeps — flying blind.`);
  return normalizeBannerIssue({
    issueId,
    message: msg,
    component: args.component || 'reaper-health',
    lastError: args.lastError
      || (kind === 'chain-tampered'
        ? 'chain_verification_failed'
        : `abstain_streak=${args.streak != null ? args.streak : '?'};threshold=${args.threshold != null ? args.threshold : '?'}`),
    suggestedChecks: args.suggestedChecks,
    bannerSurface: 'reaper_health',
  }, { bannerSurface: 'reaper_health' });
}

/**
 * Extract only the 1:1 seed fields from a banner issue.
 * @param {object} issue
 * @returns {{ issueId: string|null, message: string, component: string, lastError: string, suggestedChecks: string[] }}
 */
function extractBannerSeedFields(issue) {
  const n = normalizeBannerIssue(issue) || {
    issueId: null,
    message: '',
    component: '',
    lastError: '',
    suggestedChecks: [],
  };
  return {
    issueId: n.issueId,
    message: n.message,
    component: n.component,
    lastError: n.lastError,
    suggestedChecks: Array.isArray(n.suggestedChecks) ? n.suggestedChecks.slice() : [],
  };
}

/**
 * Assert Doctor short seed matches banner issue 1:1 on the closed field set.
 * @param {object} bannerIssue
 * @param {object} doctorSeed — buildDoctorShortSeed result
 * @returns {{ ok: boolean, mismatches: string[] }}
 */
function assertBannerSeedOneToOne(bannerIssue, doctorSeed) {
  const b = extractBannerSeedFields(bannerIssue);
  const seed = doctorSeed || {};
  const mismatches = [];
  if (String(seed.issueId || '') !== String(b.issueId || '')) {
    mismatches.push(`issueId: banner=${b.issueId} seed=${seed.issueId}`);
  }
  if (String(seed.message || '') !== String(b.message || '')) {
    mismatches.push('message');
  }
  if (String(seed.component || '') !== String(b.component || '')) {
    mismatches.push('component');
  }
  if (String(seed.lastError || '') !== String(b.lastError || '')) {
    mismatches.push('lastError');
  }
  const seedChecks = Array.isArray(seed.suggestedChecks) ? seed.suggestedChecks.map(String) : [];
  const bChecks = b.suggestedChecks.map(String);
  if (seedChecks.length !== bChecks.length
    || seedChecks.some((c, i) => c !== bChecks[i])) {
    mismatches.push('suggestedChecks');
  }
  // Must not be a markdown path masquerading as seed
  if (seed.markdownPath || seed.isMarkdownPath === true) {
    mismatches.push('markdownPath_present');
  }
  if (typeof seed.message === 'string' && /health_reports[/\\].*\.md/i.test(seed.message)
    && seed.message.trim() === seed.message && !seed.issueId) {
    mismatches.push('markdown_path_only_seed');
  }
  return { ok: mismatches.length === 0, mismatches, fields: BANNER_SEED_FIELDS.slice() };
}

/**
 * Build Doctor navigation from a banner issue — path is /doctor with query seed,
 * never health_reports/*.md.
 *
 * @param {object} issue
 * @param {object} [opts] — { token?, autoDiagnose?: boolean }
 * @returns {object}
 */
function buildDoctorNavigationFromBanner(issue, opts = {}) {
  const n = normalizeBannerIssue(issue);
  if (!n) {
    return {
      ok: false,
      href: '/doctor',
      path: '/doctor',
      isMarkdownPath: false,
      markdownPath: null,
      autoDiagnose: false,
      query: {},
      issue: null,
      error: 'no_issue',
    };
  }
  const autoDiagnose = opts.autoDiagnose !== false;
  const q = {
    issueId: n.issueId || '',
    message: n.message || '',
    component: n.component || '',
    lastError: n.lastError || '',
    suggestedChecks: (n.suggestedChecks || []).join('|'),
  };
  if (autoDiagnose) q.diagnose = '1';
  if (opts.token) q.token = String(opts.token);

  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (v != null && v !== '') params.set(k, v);
  }
  const href = `/doctor?${params.toString()}`;
  return {
    ok: true,
    href,
    path: '/doctor',
    isMarkdownPath: false,
    markdownPath: null,
    autoDiagnose,
    query: q,
    issue: extractBannerSeedFields(n),
    bannerSurface: n.bannerSurface,
    version: BANNER_DOCTOR_SEED_VERSION,
    // Guard: never emit a health_reports markdown path as the navigation target
    forbiddenMarkdownPath: false,
  };
}

/**
 * Build the full Doctor short seed + session-start plan for a banner click.
 * Session is async; start is attempted only when an engine is enabled.
 *
 * @param {object} issue
 * @param {object} [opts] — session-start args (profile, engine, classifierMode, …)
 * @returns {object}
 */
function buildBannerDiagnosePlan(issue, opts = {}) {
  const n = normalizeBannerIssue(issue);
  const seed = buildDoctorShortSeed(n, {
    classifierMode: opts.classifierMode || 'shadow',
  });
  // Ensure exactMessage alias on seed for plan "exact message" wording
  if (n) {
    seed.exactMessage = n.exactMessage || seed.message;
    seed.markdownPath = null;
    seed.isMarkdownPath = false;
    seed.bannerSurface = n.bannerSurface;
    seed.version = seed.version || 'w8-doctor-short-v1';
    seed.bannerDoctorVersion = BANNER_DOCTOR_SEED_VERSION;
  }
  const oneToOne = assertBannerSeedOneToOne(n, seed);
  const plan = buildSessionStartPlan({
    surface: 'doctor',
    engine: opts.engine,
    issue: n,
    profile: opts.profile || { claude: true, gemini: true, grok: true },
    classifierMode: opts.classifierMode || 'shadow',
    prefs: opts.prefs,
    lastUsed: opts.lastUsed,
    firstPromptMs: opts.firstPromptMs,
  });
  // Force seed from banner 1:1 (session plan already embeds issue when present)
  plan.seed = seed;
  plan.seedText = formatDoctorShortSeedText(seed);
  plan.bannerIssue = extractBannerSeedFields(n);
  plan.bannerOneToOne = oneToOne;
  plan.navigation = buildDoctorNavigationFromBanner(n, {
    token: opts.token,
    autoDiagnose: opts.autoDiagnose !== false,
  });
  plan.p6BannerDoctor = {
    id: 'p6-health-banner-doctor-seed',
    version: BANNER_DOCTOR_SEED_VERSION,
    notMarkdownPath: true,
    fields: BANNER_SEED_FIELDS.slice(),
  };
  // Diagnose startWhen: operator banner click may attempt async start immediately
  // when engine enabled — still non-blocking / shell-first.
  if (plan.canStart && opts.autoDiagnose !== false) {
    plan.session = {
      ...plan.session,
      async: true,
      cancelable: true,
      failureNonBlocking: true,
      autoStart: false, // shell still paints first; attempt is explicit diagnose path
      startWhen: 'banner_click_diagnose',
      attemptAsyncDiagnose: true,
    };
  } else {
    plan.session = {
      ...plan.session,
      async: true,
      cancelable: true,
      failureNonBlocking: true,
      attemptAsyncDiagnose: false,
      startWhen: plan.canStart ? 'operator_or_diagnose_click' : 'blocked_no_healthy_engine',
    };
  }
  return plan;
}

/**
 * Attempt async diagnose session start for a banner payload (contract object).
 * Does not spawn real engines — models the start attempt + failure surface for
 * tests and GUI consumers. When start fails, UI remains usable and health is set.
 *
 * @param {object} issue
 * @param {object} [opts]
 * @returns {object}
 */
function attemptAsyncBannerDiagnoseStart(issue, opts = {}) {
  const p5 = assertP5StartPlumbingGreen();
  const plan = buildBannerDiagnosePlan(issue, opts);
  const forceFail = opts.forceFail === true;
  const engineEnabled = !!plan.canStart && !forceFail;

  if (!p5.ok) {
    return {
      ok: false,
      attempted: false,
      async: true,
      failureNonBlocking: true,
      uiUsable: true,
      health: {
        status: 'p5_plumbing_missing',
        message: `P5 start plumbing incomplete: ${(p5.missing || []).join(',')}`,
        missing: p5.missing || [],
      },
      plan,
      session: null,
      error: 'p5_plumbing_not_green',
    };
  }

  if (!engineEnabled) {
    const reason = forceFail
      ? (opts.failReason || 'engine_start_failed')
      : (plan.error || plan.engineDenied?.reason || 'no healthy engine');
    return {
      ok: false,
      attempted: forceFail ? true : false,
      async: true,
      failureNonBlocking: true,
      uiUsable: true,
      // Failure surfaces health; page does not freeze
      health: {
        status: forceFail ? 'start_failed' : 'engine_disabled',
        message: String(reason),
        engine: plan.engine || opts.engine || null,
        engineDenied: plan.engineDenied || null,
      },
      plan,
      session: null,
      seed: plan.seed,
      seedOneToOne: plan.bannerOneToOne,
      error: reason,
    };
  }

  // Successful attempt contract (orchestrator/GUI performs real spawn)
  return {
    ok: true,
    attempted: true,
    async: true,
    failureNonBlocking: true,
    uiUsable: true,
    health: {
      status: 'healthy',
      message: 'async diagnose start attempted with banner seed',
      engine: plan.engine,
    },
    plan,
    session: {
      status: 'starting',
      async: true,
      cancelable: true,
      engine: plan.engine,
      seedKind: plan.seed && plan.seed.kind,
      issueId: plan.bannerIssue && plan.bannerIssue.issueId,
    },
    seed: plan.seed,
    seedOneToOne: plan.bannerOneToOne,
    error: null,
  };
}

/**
 * Cross-surface fail-SAFE: health-banner Doctor seed must not light dual-write
 * scare RED under shadow.
 *
 * @param {object} [opts]
 * @returns {{ ok: boolean, dualWrite: object, surfaces: string[] }}
 */
function assertBannerDoctorFailSafeWithDualWrite(opts = {}) {
  const mode = opts.classifierMode || 'shadow';
  const dual = evaluateDualWriteSurfaces({
    classifierMode: mode,
    legacyWouldBeZombies: opts.legacyWouldBeZombies || [],
    newWouldBeZombies: opts.newWouldBeZombies,
    freezeCapability: opts.freezeCapability === true,
  });
  const shadowOk = mode === 'shadow'
    ? assertNoActionableRedUnderShadow(dual)
    : true;
  // Banner doctor navigation is independent of scare surfaces
  const bannerPlan = buildBannerDiagnosePlan(
    opts.issue || buildDashboardHealthBannerIssue({ reportDate: '2099-01-01', status: 'ISSUES FOUND' }),
    { classifierMode: mode, profile: opts.profile },
  );
  const noMarkdown = bannerPlan.navigation
    && bannerPlan.navigation.isMarkdownPath === false
    && !/health_reports[/\\].*\.md/i.test(bannerPlan.navigation.href || '');
  return {
    ok: shadowOk && noMarkdown && bannerPlan.bannerOneToOne.ok,
    dualWrite: dual,
    surfaces: SURFACES.slice(),
    anySurfaceActionableRed: dual.anySurfaceActionableRed,
    bannerOneToOne: bannerPlan.bannerOneToOne,
    notMarkdownPath: noMarkdown,
  };
}

/**
 * Render clickable banner contract (data attrs + click opens Doctor).
 * Consumers (Anchor HTML) use this shape; Node holds the seed source of truth.
 *
 * @param {object} issue
 * @param {object} [opts]
 * @returns {object}
 */
function buildClickableBannerContract(issue, opts = {}) {
  const n = normalizeBannerIssue(issue);
  const nav = buildDoctorNavigationFromBanner(n, opts);
  const fields = extractBannerSeedFields(n);
  return {
    clickable: true,
    role: 'button',
    opens: 'doctor',
    notMarkdownPath: true,
    markdownPath: null,
    href: nav.href,
    dataAttrs: {
      'data-issue-id': fields.issueId || '',
      'data-message': fields.message || '',
      'data-component': fields.component || '',
      'data-last-error': fields.lastError || '',
      'data-suggested-checks': (fields.suggestedChecks || []).join('|'),
      'data-banner-surface': (n && n.bannerSurface) || '',
      'data-diagnose': opts.autoDiagnose === false ? '0' : '1',
    },
    issue: fields,
    navigation: nav,
    version: BANNER_DOCTOR_SEED_VERSION,
  };
}

module.exports = {
  BANNER_SEED_FIELDS,
  BANNER_SURFACES,
  BANNER_DOCTOR_SEED_VERSION,
  normalizeBannerIssue,
  buildDashboardHealthBannerIssue,
  buildReaperHealthBannerIssue,
  extractBannerSeedFields,
  assertBannerSeedOneToOne,
  buildDoctorNavigationFromBanner,
  buildBannerDiagnosePlan,
  attemptAsyncBannerDiagnoseStart,
  assertBannerDoctorFailSafeWithDualWrite,
  buildClickableBannerContract,
};
