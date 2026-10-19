/**
 * Semantic turn roles, not model tiers. Both roles use Anchor's selected family
 * and the shared transport's current supported model / highest supported effort.
 * Roles influence the work requested, never a dated model pin or a lower effort.
 * Exact selections belong in runtime receipts, not durable skill policy.
 */

/** The two roles. A caller asks for one of these and nothing else. */
export const SEAT_ROLE = Object.freeze({
  /** Top tier — reasoning and planning. */
  FRONTIER: 'frontier',
  /** Conversational work; same latest/highest model policy. */
  CONVERSATIONAL: 'conversational',
});

export const SEAT_ROLES = Object.freeze([SEAT_ROLE.FRONTIER, SEAT_ROLE.CONVERSATIONAL]);

/** Provider resolution is delegated to the shared subscription transport. */
export const FAMILY_TIERS = Object.freeze({
  chatgpt: Object.freeze({
    frontier: 'configured',
    conversational: 'configured',
  }),
  claude: Object.freeze({
    frontier: 'configured',
    conversational: 'configured',
  }),
  gemini: Object.freeze({
    frontier: 'configured',
    conversational: 'configured',
  }),
  grok: Object.freeze({
    frontier: 'configured',
    conversational: 'configured',
  }),
});

/**
 * Resolve the model alias for a role within a family.
 *
 * Returns an HONEST failure rather than a guess when the family is unknown — inventing
 * a model name is exactly the class of silent wrongness this file exists to prevent.
 *
 * @param {string} family chatgpt | claude | gemini | grok
 * @param {string} role SEAT_ROLE.*
 * @param {{ env?: NodeJS.ProcessEnv }} [opts]
 * @returns {{ ok: true, family: string, role: string, alias: string, source: string }
 *          | { ok: false, error: string, message: string }}
 */
export function resolveTierAlias(family, role, opts = {}) {
  const fam = String(family ?? '').trim().toLowerCase();
  const rol = String(role ?? '').trim().toLowerCase();

  if (!SEAT_ROLES.includes(rol)) {
    return {
      ok: false,
      error: 'unknown_seat_role',
      message: `"${role}" is not a seat role. Roles: ${SEAT_ROLES.join(', ')}.`,
    };
  }
  const tiers = FAMILY_TIERS[fam];
  if (!tiers) {
    return {
      ok: false,
      error: 'unknown_seat_family',
      message:
        `No policy transport for family "${family}". Configure a supported family in Anchor.`,
    };
  }
  return { ok: true, family: fam, role: rol, alias: tiers[rol], source: 'model_policy' };
}

/**
 * Structural proof that no VERSIONED model id leaked into the tier table.
 *
 * Asserted by the suite. A version number here would defeat the whole point: the table
 * would stop tracking "the latest in this tier" the day a successor ships.
 *
 * @param {object} [table]
 */
export function assertNoVersionedIds(table = FAMILY_TIERS) {
  // A digit attached to a vendor-model word is what a pinned version looks like
  // (claude-fable-5, gemini-3.1-pro, grok-4-0709). Bare tier words are fine.
  const versioned = /(claude|gemini|grok|sonnet|haiku|opus|fable|mythos)[-_ ]?\d/i;
  const offenders = [];
  for (const [family, roles] of Object.entries(table)) {
    for (const [role, alias] of Object.entries(roles)) {
      if (versioned.test(String(alias))) offenders.push(`${family}.${role}=${alias}`);
    }
  }
  return {
    ok: offenders.length === 0,
    offenders,
    law: 'aliases only — a versioned id stops tracking the tier the day a successor ships',
  };
}

/**
 * The role a turn needs.
 *
 * Roles preserve semantic context; both resolve to latest/highest.
 *
 * @param {{ planning?: boolean }} turn
 * @returns {string} SEAT_ROLE.*
 */
export function roleForTurn(turn = {}) {
  return turn.planning === true ? SEAT_ROLE.FRONTIER : SEAT_ROLE.CONVERSATIONAL;
}
