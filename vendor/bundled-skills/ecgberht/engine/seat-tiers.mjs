/**
 * SEAT TIERS — which model plays which ROLE, without ever naming a version.
 *
 * THE LAW (John, 2026-08-05):
 *
 *   frontier        the top-tier model of the selected family — used for REASONING and
 *                   PLANNING: framing a scaffolding, reworking one, the turns worth
 *                   waiting for.
 *   conversational  ALWAYS ONE TIER BELOW FRONTIER — used for TALKING: ordinary
 *                   back-and-forth, refinement, answering. Fast is the point.
 *
 * WHY THIS FILE EXISTS RATHER THAN TWO CONSTANTS. New model versions ship constantly.
 * A pinned `claude-fable-5` would silently become last year's frontier the moment a
 * successor lands, and nothing here would notice. So:
 *
 *   1. ROLES, NOT NAMES. Callers ask for `frontier` or `conversational`. No module
 *      outside this one may name a model.
 *   2. ALIASES, NOT VERSIONED IDS. The CLIs resolve an alias to the LATEST model in
 *      that line (`claude --model fable` -> newest Fable). A new version inside a tier
 *      is picked up with zero code change.
 *   3. ONE TABLE, ENV-OVERRIDABLE. When a genuinely NEW TIER appears — not just a new
 *      version — this map is the only thing to change, and it can be overridden by env
 *      without a release.
 *
 * The seat law still applies: `seating.findProductModelIds` forbids vendor product IDs
 * on seat STAMPS. Aliases are not product IDs (`fable` is not `claude-fable-5`), which
 * is a second reason to route by alias — the stamp stays clean by construction.
 */

/** The two roles. A caller asks for one of these and nothing else. */
export const SEAT_ROLE = Object.freeze({
  /** Top tier — reasoning and planning. */
  FRONTIER: 'frontier',
  /** One tier below frontier — conversation. */
  CONVERSATIONAL: 'conversational',
});

export const SEAT_ROLES = Object.freeze([SEAT_ROLE.FRONTIER, SEAT_ROLE.CONVERSATIONAL]);

/**
 * Role -> CLI ALIAS, per family. Aliases only — never a versioned model ID.
 *
 * UPDATE THIS TABLE ONLY WHEN THE TIER STRUCTURE CHANGES (a new top tier appears, or a
 * family renames its lines). A new *version* of an existing tier needs no change here:
 * the alias already resolves to the latest.
 */
export const FAMILY_TIERS = Object.freeze({
  claude: Object.freeze({
    frontier: 'fable',
    conversational: 'opus',
  }),
  gemini: Object.freeze({
    frontier: 'Gemini 3.1 Pro (High)',
    conversational: 'Gemini 3.1 Pro',
  }),
  grok: Object.freeze({
    frontier: 'grok-4-heavy',
    conversational: 'grok-4',
  }),
});

/**
 * Env overrides, so a tier change needs no release.
 * ECGBERHT_TIER_<FAMILY>_<ROLE>, e.g. ECGBERHT_TIER_CLAUDE_FRONTIER=mythos
 * @param {string} family
 * @param {string} role
 * @param {NodeJS.ProcessEnv} env
 * @returns {string|null}
 */
function envOverride(family, role, env) {
  const key = `ECGBERHT_TIER_${String(family).toUpperCase()}_${String(role).toUpperCase()}`;
  const v = env?.[key];
  return v && String(v).trim() ? String(v).trim() : null;
}

/**
 * Resolve the model alias for a role within a family.
 *
 * Returns an HONEST failure rather than a guess when the family is unknown — inventing
 * a model name is exactly the class of silent wrongness this file exists to prevent.
 *
 * @param {string} family claude | gemini | grok
 * @param {string} role SEAT_ROLE.*
 * @param {{ env?: NodeJS.ProcessEnv }} [opts]
 * @returns {{ ok: true, family: string, role: string, alias: string, source: string }
 *          | { ok: false, error: string, message: string }}
 */
export function resolveTierAlias(family, role, opts = {}) {
  const env = opts.env ?? process.env;
  const fam = String(family ?? '').trim().toLowerCase();
  const rol = String(role ?? '').trim().toLowerCase();

  if (!SEAT_ROLES.includes(rol)) {
    return {
      ok: false,
      error: 'unknown_seat_role',
      message: `"${role}" is not a seat role. Roles: ${SEAT_ROLES.join(', ')}.`,
    };
  }
  const override = envOverride(fam, rol, env);
  if (override) {
    return { ok: true, family: fam, role: rol, alias: override, source: 'env' };
  }
  const tiers = FAMILY_TIERS[fam];
  if (!tiers) {
    return {
      ok: false,
      error: 'unknown_seat_family',
      message:
        `No tier map for family "${family}". Add it to FAMILY_TIERS, or set `
        + `ECGBERHT_TIER_${String(fam).toUpperCase()}_${rol.toUpperCase()}.`,
    };
  }
  return { ok: true, family: fam, role: rol, alias: tiers[rol], source: 'table' };
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
 * Talking is the common case and must be fast; only turns that FRAME OR REWORK a
 * scaffolding earn the frontier model's depth (and its minutes-long turns).
 *
 * @param {{ planning?: boolean }} turn
 * @returns {string} SEAT_ROLE.*
 */
export function roleForTurn(turn = {}) {
  return turn.planning === true ? SEAT_ROLE.FRONTIER : SEAT_ROLE.CONVERSATIONAL;
}
