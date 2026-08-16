/**
 * Injected authorizer hook (North Star criterion 9 groundwork — Wave 1).
 *
 * The engine never reads ANCHOR_TOKEN itself. Hosts inject an authorizer via
 * setAuthorizer(); spend/write seams call authorize(seam, ctx). Default is
 * allow-all (host-less skill lane). Anchor's token authorizer is injected in
 * the AUTH-ON lane. Waves 8/11 wire this hook into debit/confirm/launch seams;
 * Wave 1 ships the hook + negative-test harness so auth-ON cannot be vacuous.
 *
 * Stdlib only.
 */

/** @typedef {'confirm'|'launch'|'debit'|'read'|string} AuthSeam */

/**
 * @typedef {object} AuthContext
 * @property {string} [token]
 * @property {string} [principal]
 * @property {string} [credential_class]
 * @property {boolean} [revoked]
 * @property {string|number|null} [expires_at]
 * @property {Record<string, unknown>} [extra]
 */

/**
 * @typedef {object} AuthDecision
 * @property {boolean} ok
 * @property {string} [code]
 * @property {string} [message]
 * @property {AuthSeam} [seam]
 */

/** @type {((seam: AuthSeam, ctx: AuthContext) => AuthDecision)|null} */
let _authorizer = null;

/**
 * Install the process-wide authorizer. Pass null to restore host-less allow-all.
 * @param {((seam: AuthSeam, ctx: AuthContext) => AuthDecision)|null} fn
 */
export function setAuthorizer(fn) {
  _authorizer = typeof fn === 'function' ? fn : null;
}

/** @returns {((seam: AuthSeam, ctx: AuthContext) => AuthDecision)|null} */
export function getAuthorizer() {
  return _authorizer;
}

/**
 * Default host-less authorizer: always allow. Skill lane never requires a token.
 * @param {AuthSeam} seam
 * @param {AuthContext} [_ctx]
 * @returns {AuthDecision}
 */
export function allowAllAuthorizer(seam, _ctx = {}) {
  return { ok: true, seam, code: 'auth-allow-all', message: 'host-less allow-all' };
}

/**
 * Anchor-style shared-secret token authorizer for the AUTH-ON lane and tests.
 * Negative cases: absent / expired / wrong-principal / revoked.
 *
 * @param {{ expectedToken: string, expectedPrincipal?: string|null, now?: () => number }} opts
 * @returns {(seam: AuthSeam, ctx: AuthContext) => AuthDecision}
 */
export function makeTokenAuthorizer(opts) {
  const expectedToken = String(opts.expectedToken ?? '');
  const expectedPrincipal =
    opts.expectedPrincipal === undefined || opts.expectedPrincipal === null
      ? null
      : String(opts.expectedPrincipal);
  const now = typeof opts.now === 'function' ? opts.now : () => Date.now();

  return function tokenAuthorizer(seam, ctx = {}) {
    if (ctx.revoked === true) {
      return {
        ok: false,
        seam,
        code: 'auth-revoked',
        message: 'Credential revoked at the seam; refusal is final.',
      };
    }

    const token = ctx.token == null ? '' : String(ctx.token);
    if (!token) {
      return {
        ok: false,
        seam,
        code: 'auth-absent',
        message: 'No credential presented at the seam.',
      };
    }

    // Constant-time-ish compare for short secrets (Node has no hmac in all paths
    // without import; length mismatch short-circuits but wrong-token still fails).
    if (token.length !== expectedToken.length || token !== expectedToken) {
      return {
        ok: false,
        seam,
        code: 'auth-wrong-token',
        message: 'Credential does not match the expected token.',
      };
    }

    if (ctx.expires_at != null && ctx.expires_at !== '') {
      const exp =
        typeof ctx.expires_at === 'number'
          ? ctx.expires_at
          : Date.parse(String(ctx.expires_at));
      if (Number.isFinite(exp) && exp <= now()) {
        return {
          ok: false,
          seam,
          code: 'auth-expired',
          message: 'Credential expired at the seam.',
        };
      }
    }

    if (expectedPrincipal != null) {
      const principal = ctx.principal == null ? '' : String(ctx.principal);
      if (principal !== expectedPrincipal) {
        return {
          ok: false,
          seam,
          code: 'auth-wrong-principal',
          message: 'Principal does not match the bound identity.',
        };
      }
    }

    return { ok: true, seam, code: 'auth-ok', message: 'authorized' };
  };
}

/**
 * Explicit local-trust authorizer for bare hosts (no Anchor token).
 * Provenance is stamped on spend receipts so the trust model is honest.
 *
 * @param {{ principal?: string|null }} [opts]
 * @returns {(seam: AuthSeam, ctx: AuthContext) => AuthDecision & { provenance: string }}
 */
export function makeLocalTrustAuthorizer(opts = {}) {
  const expectedPrincipal =
    opts.principal === undefined || opts.principal === null
      ? null
      : String(opts.principal);

  return function localTrustAuthorizer(seam, ctx = {}) {
    if (ctx.revoked === true) {
      return {
        ok: false,
        seam,
        code: 'auth-revoked',
        message: 'Credential revoked at the seam; refusal is final.',
        provenance: 'local_trust',
      };
    }
    if (expectedPrincipal != null) {
      const principal = ctx.principal == null ? '' : String(ctx.principal);
      if (principal !== expectedPrincipal) {
        return {
          ok: false,
          seam,
          code: 'auth-wrong-principal',
          message: 'Principal does not match the local-trust bound identity.',
          provenance: 'local_trust',
        };
      }
    }
    return {
      ok: true,
      seam,
      code: 'auth-local-trust',
      message: 'local-trust authorizer (bare host; no token substrate)',
      provenance: 'local_trust',
    };
  };
}

/**
 * Call the injected authorizer (or allow-all when none is set).
 * @param {AuthSeam} seam
 * @param {AuthContext} [ctx]
 * @returns {AuthDecision}
 */
export function authorize(seam, ctx = {}) {
  const fn = _authorizer ?? allowAllAuthorizer;
  try {
    const decision = fn(seam, ctx ?? {});
    if (!decision || typeof decision.ok !== 'boolean') {
      return {
        ok: false,
        seam,
        code: 'auth-malformed-decision',
        message: 'Authorizer returned a non-decision; refusing closed.',
      };
    }
    return { ...decision, seam: decision.seam ?? seam };
  } catch (err) {
    return {
      ok: false,
      seam,
      code: 'auth-authorizer-threw',
      message: String(err?.message ?? err),
    };
  }
}

/**
 * Reset to host-less allow-all. Used by tests between cases.
 */
export function resetAuthorizer() {
  _authorizer = null;
}
