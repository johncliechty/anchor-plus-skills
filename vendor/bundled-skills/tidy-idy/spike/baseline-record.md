# Wave 0 — Recorded green baseline of the tidy-idy suite (before / after the spike)

**Test command (frozen plan, line 3):** `node --test` (run from the skill root; Node's default
discovery picks up both the legacy `test/*.test.mjs` files and the new `spike/*.test.mjs` files).

## The legacy suite (the baseline every later wave must preserve)

| # | File |
|---|------|
| 1 | `test/analyze.test.mjs` |
| 2 | `test/compress.test.mjs` |
| 3 | `test/debate.test.mjs` |
| 4 | `test/hygiene.test.mjs` |
| 5 | `test/remove.test.mjs` |
| 6 | `test/scanner.test.mjs` |
| 7 | `test/tidy.test.mjs` |

## Before-spike baseline

The pre-wave tree is branch `foreman/tidy-idy-gui` at commit `628b913` (the Foreman
checkpoint's `last_commit` at wave start). This spike wave adds ONLY new files under `spike/`
plus one `.gitignore` line for a gitignored runtime debug dump; it modifies **zero** existing
source or test files. The legacy suite is therefore textually identical before and after the
spike — the "before" and "after" baselines are the same seven files, byte for byte.

## After-spike record (mechanical, re-proven every run)

`spike/seam-harness.test.mjs` contains the test
`recorded green baseline: legacy tidy-idy suite passes in a subprocess`, which re-runs the seven
legacy files above as an explicit-file `node --test` subprocess (explicit files, not a directory
argument — Node 26 rejects directory args) on **every** gate run and fails if they are not green.
A green wave gate therefore *is* the recorded green baseline — before-state by the byte-identity
argument above, after-state by direct measurement in the same run.

## Division-of-labor honesty

The EXECUTE agent runs no tests (the Foreman orchestrator owns the `node --test` gate and all
git operations). This artifact defines exactly what the orchestrator's gate run certifies; the
green/red stamp itself is the gate run's output, recorded in the Foreman log (`LOG.md`) and the
wave commit.
