# Pocket Calculator — Description

A throwaway target project used as Foreman's **canonical fixture** (Phase 0.5).
It is intentionally tiny: just enough real structure for the future Phase 1
engine to run a full execute -> review -> fix -> re-review loop against something
concrete.

## What it is

A pure-JS arithmetic module (`src/calc.js`) exposing `add`, `subtract`, and
`multiply`, with a matching test suite (`test/calc.test.mjs`) run via the Node
built-in test runner.

## Why it exists

Foreman needs a target that exercises the real section-4 contracts:

- three locatable frozen docs (this file, the plan, the execution log),
- a parseable `## Wave N` plan,
- a discoverable ground-truth test command, and
- **a planted bug** that makes a real test fail, so the engine has something to
  catch and close.

## The planted bug

`subtract(a, b)` currently returns `a + b` (see the `BUG` marker in
`src/calc.js`). The test `subtract: 7 - 3 === 4` therefore fails. The one-line
fix is to change `a + b` to `a - b`. This is the "deliberately
failing-then-passing test" the plan calls for: red with the bug, green once the
engine applies the fix.
