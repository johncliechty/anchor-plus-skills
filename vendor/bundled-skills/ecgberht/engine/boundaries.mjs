// The speaking boundaries — the named moments at which the steward may speak unprompted on the High Seat.
//
// W0 of the steward revision (2026-09-28; PLAN v1.0 §5). The review's Superjump passes killed every "prepare and
// speak" mechanism on an undefined "another boundary"; this list is the definition. Nothing reads it yet except
// the tests and Anchor's mirror (`steward_cockpit/boundaries.py`, kept identical by a test on both sides); W2 and
// W3 read it. A moment that is not on this list is not a boundary: the steward prepares and waits.
export const SPEAKING_BOUNDARIES = Object.freeze([
  'page_open',      // he opens the High Seat
  'card_open',      // he opens a project's card on the High Seat
  'turn_submitted', // he submits a turn to the steward (the cockpit or the High Seat composer)
  'step_closed',    // a step closes on the record (an acceptance, a done)
  'run_finished',   // a commissioned run he launched has finished
]);

export const SPEAKING_BOUNDARIES_VERSION = 1;

/** True when `moment` is one of the named boundaries (a string compare; never a fuzzy match). */
export function isSpeakingBoundary(moment) {
  return typeof moment === 'string' && SPEAKING_BOUNDARIES.includes(moment);
}
