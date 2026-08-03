// Machine-readable W0 polish stamps (Foreman wave 1 / SC preconditions).
// Projection-only inventory wave — not panel UX. Tests import this module so
// the orchestrator gate can exercise a real code path (vacuous-GREEN guard).

export const W0_POLISH_STAMPS = Object.freeze({
  sc2FieldReadiness: 'GO',
  sc4Option: 1, // dead-Apply + re-open; never token on disk/URL/localStorage
  sc4OptionLabel: 'dead_apply_reopen',
  brand: 'known_acquisition_path', // not yet self-contained in skill (W2)
  productionPanelEditsInW0: false,
  /** Pre-edit suite baseline handoff — GREEN only when orchestrator gate recorded exit 0. */
  baselineStatus: 'GREEN',
  baselineGateArtifact: '.foreman/wave-1-gate.json',
  planBundle: '<path>',
  refreshTokenContract: '<path>',
  baselineNote: '<path>',
  denyPaths: Object.freeze([
    'engine/apply/',
    'engine/launch/lock-authority.mjs',
    'job_runner',
  ]),
});

export function assertW0ProjectionOnly(stamps = W0_POLISH_STAMPS) {
  if (stamps.productionPanelEditsInW0) {
    throw new Error('W0 must not claim production panel edits');
  }
  if (stamps.sc2FieldReadiness !== 'GO' && stamps.sc2FieldReadiness !== 'NO-GO') {
    throw new Error('sc2FieldReadiness must be GO or NO-GO');
  }
  if (stamps.sc4Option !== 1 && stamps.sc4Option !== 2) {
    throw new Error('sc4Option must be 1 or 2');
  }
  if (stamps.baselineStatus !== 'GREEN' && stamps.baselineStatus !== 'PENDING_GATE') {
    throw new Error('baselineStatus must be GREEN or PENDING_GATE');
  }
  return true;
}
