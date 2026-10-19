// src/posture-resolver.mjs — Wave 5: composed posture resolution with explicit precedence.
//
// The honesty problem this solves: a run is built from components that each carry their own
// posture — the plan-review gate can honestly claim 'governed' (a hash-bound governance
// record exists for the approved plan), while intake ran degraded and no live model seats
// were bound. Without one resolver, those claims get pasted together into a dishonest
// whole-run stamp ("governed" run that never verified anything).
//
// The rules, enforced here in code rather than by convention:
//   1. PRECEDENCE — 'degraded' anywhere downgrades the WHOLE-RUN stamp. The run stamp is
//      only ever 'live' or 'degraded'; it is never 'governed'.
//   2. SCOPING — the gate's 'governed' claim is scoped to plan-review governance ONLY
//      (SCOPE_PLAN_REVIEW). A 'governed' claim on any other scope is a dishonest posture
//      claim and throws; it is never silently accepted or downgraded.
//   3. ONE POSTURE PER SCOPE — every scope in the composed artifact resolves to exactly one
//      posture, so no artifact can present 'governed' and 'degraded' at the SAME scope.
//      When 'degraded' displaces 'governed' at the plan-review scope, the governed claim
//      (and its reasons) is dropped from the artifact, not co-presented.
//   4. LITREVIEW_LIVE — the resolver honors the skill's existing honesty convention
//      (bin/cli.mjs: LIVE = opts.live || process.env.LITREVIEW_LIVE === '1'): a run without
//      live seats is 'degraded' by definition, with a named reason.
//
// The module is PURE and deterministic: no clock, no randomness, no mutation of its inputs;
// the returned artifact is deep-frozen and validated by assertPostureInvariant before it is
// ever returned, so a resolver bug can never emit a dual claim either.

export const POSTURE_GOVERNED = 'governed';
export const POSTURE_LIVE = 'live';
export const POSTURE_DEGRADED = 'degraded';
export const POSTURES = Object.freeze([POSTURE_LIVE, POSTURE_GOVERNED, POSTURE_DEGRADED]);

/** The whole-run scope (its posture IS the run stamp; never 'governed'). */
export const SCOPE_RUN = 'run';
/** The ONLY scope on which a 'governed' claim is honest: plan-review governance. */
export const SCOPE_PLAN_REVIEW = 'plan-review-governance';

/** The degraded reason stamped when no live seats are bound (mirrors bin/cli.mjs). */
export const NO_LIVE_SEATS_REASON = 'no live model seats bound (--live / LITREVIEW_LIVE=1 not set)';

export class PostureError extends Error {
  constructor(message) {
    super(message);
    this.name = 'PostureError';
  }
}

// Composition precedence per scope: degraded beats governed beats live. Only rule 1
// ("degraded wins") is load-bearing; governed-over-live just keeps the stronger honest
// claim when both are made about plan-review governance.
const PRECEDENCE = Object.freeze({
  [POSTURE_LIVE]: 0,
  [POSTURE_GOVERNED]: 1,
  [POSTURE_DEGRADED]: 2,
});

/**
 * The skill's live-run test (the exact bin/cli.mjs convention): an explicit --live flag or
 * LITREVIEW_LIVE=1. Anything else — unset, '0', 'true' — is NOT live.
 * @param {{ live?: boolean, env?: object }} opts
 * @returns {boolean}
 */
export function isLiveRun({ live = false, env = process.env } = {}) {
  return live === true || env?.LITREVIEW_LIVE === '1';
}

/** Convenience constructor for a component posture claim. */
export function claim(scope, posture, reason = '') {
  return { scope, posture, reason };
}

function validateClaim(c, i) {
  if (!c || typeof c !== 'object' || Array.isArray(c)) {
    throw new PostureError(`claim[${i}] must be an object { scope, posture, reason? }`);
  }
  if (typeof c.scope !== 'string' || c.scope.length === 0) {
    throw new PostureError(`claim[${i}] has no scope`);
  }
  if (!POSTURES.includes(c.posture)) {
    throw new PostureError(
      `claim[${i}] (scope "${c.scope}") has unknown posture ${JSON.stringify(c.posture)} — ` +
        `expected one of ${POSTURES.join('|')}`,
    );
  }
  if (c.posture === POSTURE_GOVERNED && c.scope !== SCOPE_PLAN_REVIEW) {
    throw new PostureError(
      `dishonest posture claim: 'governed' is scoped to plan-review governance ONLY ` +
        `("${SCOPE_PLAN_REVIEW}"), never "${c.scope}"`,
    );
  }
  if (c.reason !== undefined && typeof c.reason !== 'string') {
    throw new PostureError(`claim[${i}] (scope "${c.scope}") reason must be a string`);
  }
}

function deepFreeze(value) {
  if (value && typeof value === 'object') {
    for (const v of Object.values(value)) deepFreeze(v);
    Object.freeze(value);
  }
  return value;
}

/**
 * Compose component posture claims into ONE whole-run posture artifact.
 *
 * @param {{
 *   claims?: Array<{scope:string, posture:string, reason?:string}>,
 *   live?: boolean,             // the CLI --live flag (parity with bin/cli.mjs)
 *   env?: object,               // defaults to process.env; LITREVIEW_LIVE honored
 * }} opts
 * @returns {{
 *   runStamp: 'live'|'degraded',                       // the whole-run stamp — never 'governed'
 *   liveSeatsBound: boolean,
 *   scopes: Record<string, {posture:string, reasons:string[]}>, // exactly ONE posture per scope
 *   degradedReasons: string[],                         // why the run (if degraded) is degraded
 * }} deep-frozen and invariant-checked
 */
export function resolveComposedPosture({ claims = [], live = false, env = process.env } = {}) {
  if (!Array.isArray(claims)) throw new PostureError('claims must be an array');
  claims.forEach(validateClaim);

  const liveSeatsBound = isLiveRun({ live, env });

  // Per-scope composition: the highest-precedence posture wins; reasons are kept only for
  // the WINNING posture, so a displaced claim is never co-presented at that scope.
  const scopes = {};
  for (const c of claims) {
    const entry = (scopes[c.scope] ??= { posture: c.posture, reasons: [] });
    if (PRECEDENCE[c.posture] > PRECEDENCE[entry.posture]) {
      entry.posture = c.posture;
      entry.reasons = [];
    }
    if (c.posture === entry.posture && c.reason) entry.reasons.push(c.reason);
  }

  // Whole-run stamp: any degraded component downgrades the run; no live seats degrades the
  // run (LITREVIEW_LIVE honored). A component claim can never RAISE the run above this.
  const degradedReasons = [];
  for (const [scope, entry] of Object.entries(scopes)) {
    if (entry.posture === POSTURE_DEGRADED) {
      degradedReasons.push(`${scope}: ${entry.reasons.join('; ') || 'degraded component'}`);
    }
  }
  if (!liveSeatsBound) degradedReasons.push(`${SCOPE_RUN}: ${NO_LIVE_SEATS_REASON}`);

  const runStamp = degradedReasons.length > 0 ? POSTURE_DEGRADED : POSTURE_LIVE;

  const priorRun = scopes[SCOPE_RUN];
  scopes[SCOPE_RUN] = {
    posture: runStamp,
    reasons: runStamp === POSTURE_DEGRADED ? [...degradedReasons] : priorRun ? [...priorRun.reasons] : [],
  };

  const artifact = { runStamp, liveSeatsBound, scopes, degradedReasons };
  assertPostureInvariant(artifact);
  return deepFreeze(artifact);
}

/**
 * The CI-enforceable invariant: throws PostureError (naming the violation) unless
 *   - the run stamp is 'live' or 'degraded' (never 'governed'),
 *   - every scope resolves to exactly ONE valid posture (no dual claim at the same scope),
 *   - 'governed' appears only at SCOPE_PLAN_REVIEW,
 *   - the run scope's posture equals the run stamp,
 *   - a 'live' run stamp implies live seats bound and NO degraded scope anywhere.
 * @returns {true}
 */
export function assertPostureInvariant(artifact) {
  if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) {
    throw new PostureError('posture artifact must be an object');
  }
  const { runStamp, liveSeatsBound, scopes } = artifact;
  if (runStamp !== POSTURE_LIVE && runStamp !== POSTURE_DEGRADED) {
    throw new PostureError(
      `whole-run stamp must be '${POSTURE_LIVE}' or '${POSTURE_DEGRADED}', never ` +
        `${JSON.stringify(runStamp)} — the gate's 'governed' claim never covers the run`,
    );
  }
  if (!scopes || typeof scopes !== 'object' || Array.isArray(scopes)) {
    throw new PostureError('posture artifact must carry a scopes map');
  }
  for (const [scope, entry] of Object.entries(scopes)) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      throw new PostureError(`scope "${scope}" must resolve to a single { posture, reasons } entry`);
    }
    for (const key of Object.keys(entry)) {
      if (key !== 'posture' && key !== 'reasons') {
        throw new PostureError(
          `scope "${scope}" carries extra field "${key}" — a scope resolves to exactly ONE posture`,
        );
      }
    }
    if (!POSTURES.includes(entry.posture)) {
      throw new PostureError(`scope "${scope}" carries unknown posture ${JSON.stringify(entry.posture)}`);
    }
    if (entry.reasons !== undefined && !Array.isArray(entry.reasons)) {
      throw new PostureError(`scope "${scope}" reasons must be an array`);
    }
    if (entry.posture === POSTURE_GOVERNED && scope !== SCOPE_PLAN_REVIEW) {
      throw new PostureError(
        `scope "${scope}" claims 'governed' — that claim is scoped to "${SCOPE_PLAN_REVIEW}" only`,
      );
    }
  }
  const run = scopes[SCOPE_RUN];
  if (!run) throw new PostureError(`posture artifact must resolve the "${SCOPE_RUN}" scope`);
  if (run.posture !== runStamp) {
    throw new PostureError(
      `run scope posture "${run.posture}" contradicts the whole-run stamp "${runStamp}"`,
    );
  }
  if (runStamp === POSTURE_LIVE) {
    if (liveSeatsBound !== true) {
      throw new PostureError(
        `whole-run stamp 'live' requires live seats bound (LITREVIEW_LIVE) — degraded operation must stamp '${POSTURE_DEGRADED}'`,
      );
    }
    for (const [scope, entry] of Object.entries(scopes)) {
      if (entry.posture === POSTURE_DEGRADED) {
        throw new PostureError(
          `whole-run stamp 'live' but scope "${scope}" is degraded — any degraded component downgrades the whole run`,
        );
      }
    }
  }
  return true;
}

/**
 * Deterministic display stamp for a composed posture artifact. The run stamp leads; every
 * other scope follows in sorted order, each with its single posture (the 'governed' line is
 * explicitly annotated with its scope limit so the claim can never read as run-wide).
 * @returns {string}
 */
export function renderPostureStamp(artifact) {
  assertPostureInvariant(artifact);
  const runReasons = artifact.scopes[SCOPE_RUN].reasons || [];
  const lines = [
    `POSTURE: ${artifact.runStamp} (whole-run)` + (runReasons.length ? ` — ${runReasons.join('; ')}` : ''),
  ];
  for (const scope of Object.keys(artifact.scopes).sort()) {
    if (scope === SCOPE_RUN) continue;
    const entry = artifact.scopes[scope];
    const note = entry.posture === POSTURE_GOVERNED ? ' (scoped to plan-review governance only)' : '';
    const reasons = entry.reasons || [];
    lines.push(`- ${scope}: ${entry.posture}${note}` + (reasons.length ? ` — ${reasons.join('; ')}` : ''));
  }
  return lines.join('\n');
}
