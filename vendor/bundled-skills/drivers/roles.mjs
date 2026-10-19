// One role taxonomy for every Trio routing, posture, and receipt decision.

const VERIFICATION_ROLE_SET = new Set([
  'review', 'shark', 'reviewer', 'debate', 'refuter', 'gate3', 'verify',
  'judge', 'attacker', 'analysis',
]);

// Expose an immutable iterable snapshot; Set.prototype.add/delete remain mutating
// even when a Set object is frozen.
export const VERIFICATION_ROLES = Object.freeze([...VERIFICATION_ROLE_SET]);

const LEGACY_GATE3_LABELS = new Set([
  'killfiltergate3',
  'gate3livenessping',
]);

const ROLE_DELIMITER = /[:#.\x20\t\r\n\f\v]/;

/**
 * Normalize the only supported classifier input. An explicit nonempty role wins
 * over the label. The two historical Jumper labels are the sole compatibility
 * shim and can only promote a missing role or an explicit `gate` role to gate3.
 */
export function normalizeRole({ role, label } = {}) {
  const explicit = typeof role === 'string' && role.trim().length > 0;
  const source = explicit ? role : label;
  const text = typeof source === 'string' ? source.trim() : '';
  let normalized = text ? text.split(ROLE_DELIMITER, 1)[0].trim().toLowerCase() : null;
  if (!normalized) normalized = null;

  const legacyLabel = typeof label === 'string'
    && LEGACY_GATE3_LABELS.has(label.trim().toLowerCase());
  if (legacyLabel && (!explicit || normalized === 'gate')) return 'gate3';
  return normalized;
}

export function isVerificationRole(input = {}) {
  return VERIFICATION_ROLE_SET.has(normalizeRole(input));
}
