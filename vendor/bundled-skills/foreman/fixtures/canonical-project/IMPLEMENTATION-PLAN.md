# Pocket Calculator — Implementation Plan

This is the canonical fixture's plan. It has a real, parseable `## Wave N`
structure (ascending, contiguous) and declares the ground-truth gate command so
`discoverTestCommand` finds it without falling through to the manifest.

test-command: `node --test`

## Wave 1 — Core arithmetic

Implement `add` and `multiply` in `src/calc.js` with passing tests. These are
already correct in the fixture and act as the "known-good" baseline so a
vacuous-GREEN (all-tests-deleted) attempt is distinguishable from a real pass.

## Wave 2 — Subtraction (carries the planted bug)

Implement `subtract(a, b)`. The fixture ships this wave with a deliberate bug
(`a + b` instead of `a - b`) so a real test fails. Phase 1's engine must catch
this in review and close it with a fix; this wave is what makes the fixture
useful as an end-to-end target.
