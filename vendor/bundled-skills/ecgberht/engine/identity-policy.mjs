/**
 * Wave 5 — G6 identity policy (GATE DECISION 5, John 2026-08-01).
 *
 * Substrate fact (Anchor paths.py:384-446): ANCHOR_TOKEN is a bare shared
 * secret, constant-time compared, with no subject / expiry / claims. The
 * engine does NOT read ANCHOR_TOKEN (criterion 9) — this module only stamps
 * the CLAIMED identity shape later waves import.
 *
 * Every confirmation receipt records:
 *   who: { claimed: "<supplied name>", provenance: "claimed_unauthenticated" }
 *
 * A claimed who is NEVER rendered as proven. `unattributed` is NEVER silently
 * substituted (unknown-never-rendered-as-empty honesty law). Building real
 * subject identity (accounts/sessions/subjects) is OUT of this North Star.
 */

export const IDENTITY_POLICY_SCHEMA = 'ecgberht-identity-policy-v0';

export const WHO_PROVENANCE = 'claimed_unauthenticated';

/** Credential class of the bare shared-secret substrate (no subject). */
export const CREDENTIAL_CLASS_SHARED_SECRET = 'shared_secret';

/** Host-less / no credential presented. */
export const CREDENTIAL_CLASS_NONE = 'none';

/**
 * Frozen decision record later waves import.
 * @returns {object}
 */
export function identityPolicyRecord() {
  return {
    schema: IDENTITY_POLICY_SCHEMA,
    gate_decision: 5,
    decided: '2026-08-01',
    authority: 'STAGE1-APPROVAL.md',
    substrate: {
      kind: 'bare_shared_secret',
      name: 'ANCHOR_TOKEN',
      constant_time_compare: true,
      subject: false,
      expiry: false,
      claims: false,
      cited_from: 'paths.py:384-446',
      engine_reads_token: false,
      note:
        'Engine contains no ANCHOR_TOKEN logic; hosts inject authorize(seam, ctx).',
    },
    who_shape: {
      claimed: '<supplied name>',
      provenance: WHO_PROVENANCE,
    },
    rules: [
      'record the CLAIMED identity stamped unauthenticated',
      'never render claimed who as proven subject identity',
      'never silently substitute unattributed for a missing or claimed who',
      'credential CLASS recorded on spend confirmations',
      'no IdP; real subject identity is a future effort, not a TODO here',
    ],
    out_of_scope: [
      'accounts',
      'sessions',
      'subjects',
      'IdP',
      'recoverable_subject_from_token',
    ],
  };
}

/**
 * Stamp a claimed who (gate decision 5). Never invents unattributed.
 *
 * @param {string|null|undefined} claimed
 * @returns {{ claimed: string, provenance: 'claimed_unauthenticated' } | null}
 */
export function stampClaimedWho(claimed) {
  if (claimed == null) return null;
  const name = String(claimed).trim();
  if (!name) return null;
  // Refuse silent unattributed substitution
  if (name.toLowerCase() === 'unattributed') return null;
  return {
    claimed: name,
    provenance: WHO_PROVENANCE,
  };
}

/**
 * Normalize who input for receipts. Strings → claimed stamp; objects must
 * carry claimed. Never substitutes unattributed.
 *
 * @param {*} who
 * @returns {{ claimed: string, provenance: string } | null}
 */
export function normalizeClaimedWho(who) {
  if (who == null) return null;
  if (typeof who === 'string') return stampClaimedWho(who);
  if (typeof who === 'object' && who.claimed != null) {
    const stamped = stampClaimedWho(who.claimed);
    if (!stamped) return null;
    return {
      claimed: stamped.claimed,
      provenance: WHO_PROVENANCE, // always force the locked provenance
    };
  }
  return null;
}

/**
 * Record who + credential CLASS on a spend confirmation.
 *
 * Credential CLASS is REQUIRED — never silently defaulted to shared_secret.
 * Callers must state the class (shared_secret | none | host-supplied name).
 *
 * @param {{
 *   claimed?: string,
 *   who?: string|object,
 *   credential_class: string,
 *   at?: string,
 *   kind?: string,
 * }} opts
 * @returns {{ ok: true, confirmation: object } | { ok: false, code: string, message: string }}
 */
export function recordSpendConfirmationWho(opts = {}) {
  const who = normalizeClaimedWho(opts.claimed ?? opts.who);
  if (!who) {
    return {
      ok: false,
      code: 'who-required',
      message:
        'Spend confirmation requires a claimed identity — unattributed is never silently substituted.',
    };
  }
  if (opts.credential_class == null || opts.credential_class === '') {
    return {
      ok: false,
      code: 'credential-class-required',
      message:
        'Spend confirmation requires an explicit credential CLASS — never silently defaulted (shared_secret | none | host-named).',
    };
  }
  const credential_class = String(opts.credential_class);

  return {
    ok: true,
    confirmation: {
      kind: opts.kind ?? 'spend_confirmation',
      who,
      credential_class,
      at: opts.at ?? new Date().toISOString(),
      identity_policy: IDENTITY_POLICY_SCHEMA,
      substrate_has_subject: false,
    },
  };
}

/**
 * Render a who stamp for UI / Face. Claimed is NEVER shown as proven.
 * Missing who → honest unknown, never empty, never unattributed.
 *
 * @param {{ claimed?: string, provenance?: string }|null|undefined} who
 * @returns {{
 *   display: string,
 *   proven: false,
 *   claimed: string|null,
 *   provenance: string|null,
 *   unknown: boolean,
 *   class: 'claimed-not-authenticated'|'unknown',
 * }}
 */
export function renderWhoClaimedNotAuthenticated(who) {
  const normalized = normalizeClaimedWho(who);
  if (!normalized) {
    return {
      display: 'unknown — no claimed identity on this confirmation',
      proven: false,
      claimed: null,
      provenance: null,
      unknown: true,
      class: 'unknown',
    };
  }
  return {
    display: `${normalized.claimed} (claimed, not authenticated)`,
    proven: false,
    claimed: normalized.claimed,
    provenance: normalized.provenance,
    unknown: false,
    class: 'claimed-not-authenticated',
  };
}

/**
 * Assert a who object obeys the honesty law (for tests / CI).
 * @param {*} who
 * @returns {{ ok: boolean, issues: string[] }}
 */
export function assertWhoHonesty(who) {
  const issues = [];
  if (who == null) {
    issues.push('who_missing');
    return { ok: false, issues };
  }
  if (who === 'unattributed' || who?.claimed === 'unattributed') {
    issues.push('unattributed_forbidden');
  }
  if (typeof who === 'object') {
    if (!who.claimed || !String(who.claimed).trim()) {
      issues.push('claimed_empty');
    }
    if (who.provenance !== WHO_PROVENANCE) {
      issues.push(`provenance_must_be_${WHO_PROVENANCE}`);
    }
    if (who.proven === true || who.authenticated === true || who.subject) {
      issues.push('must_not_assert_proven_subject');
    }
  }
  return { ok: issues.length === 0, issues };
}
