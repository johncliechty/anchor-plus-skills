// calc.js — the canonical fixture's source under test.
//
// add() and multiply() are correct (Wave 1, known-good baseline).
// subtract() carries the deliberately planted bug (Wave 2).

export function add(a, b) {
  return a + b;
}

export function multiply(a, b) {
  return a * b;
}

export function subtract(a, b) {
  // BUG (planted, Phase 0.5): should be `a - b`. Returning `a + b` makes the
  // subtract test fail. The one-line fix is to change `+` to `-`.
  return a + b;
}
