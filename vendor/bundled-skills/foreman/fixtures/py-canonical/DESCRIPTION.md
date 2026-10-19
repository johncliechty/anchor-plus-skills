# Pocket Calculator (Python) — Description

A throwaway target project used as Foreman's **Python canonical fixture**
(Phase 3d). It mirrors the JS `canonical-project` fixture one-for-one, but the
ground-truth gate is `python -m pytest -v` instead of `node --test`. It is
intentionally tiny: just enough real structure for the engine to run a full
execute -> review -> fix -> re-review loop against a concrete pytest target.

## What it is

A pure-Python arithmetic module (`calc.py`) exposing `add`, `subtract`, and
`multiply`, with a matching pytest suite (`test_calc.py`) run via the standard
`python -m pytest -v` command (the `-v` is required so real per-test events are
emitted for the gate-integrity guards).

## Why it exists

Foreman needs a Python target that exercises the same section-4 contracts the JS
fixture does:

- three locatable frozen docs (this file, the plan, the execution log),
- a parseable `## Wave N` plan,
- a discoverable ground-truth test command (`test-command: python -m pytest -v`),
- a real import edge (`test_calc.py` imports `calc`) so the vacuous-GREEN
  coverage proxy has something to reach, and
- **a planted bug** that makes a real pytest test fail, so the engine has
  something to catch and close.

## The planted bug

`subtract(a, b)` currently returns `a + b` (see the `BUG` marker in `calc.py`).
The test `test_subtract` (`subtract(7, 3) == 4`) therefore fails. The one-line
fix is to change `a + b` to `a - b`. This is the deliberately
failing-then-passing test the plan calls for: RED with the bug present, GREEN
once the engine applies the fix.
