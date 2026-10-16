/**
 * Heartbeat push transition — W1 SKELETON.
 * The real push to Ecgberht's closed heartbeat verb (non-ranked fields only)
 * lands in W10. W1 ships the seam and the ORDER guarantee: the engine calls
 * this only AFTER the manifest check and the status rebuild, and never when a
 * reconciliation HALT is open (a stale status is never published ahead of a
 * detected edit). Budget: ≤ 5 s (start-budget gate).
 * Only lib/engine.mjs may call this module (machine-only-caller test).
 */
export function pushHeartbeat(root, { project }) {
  return {
    transition: 'heartbeat',
    ok: true,
    pushed: false,
    reason: 'the Ecgberht push lands in W10; W1 is the seam and the order',
    project,
  };
}
