# Anchor v1 — Execution Log

> Foreman's run ledger for the `anchor-v1` plan (branch `feat/zombie-hunter-v2`,
> worktree `C:/dev/Anchor-zombie`). Foreman appends per-wave commentary, gate
> results, and any HALT/amendment here. Seeded empty (pre-run).

## Status

- **State:** not started (plan authored, awaiting Foreman invocation).
- **Gate of record:** `python -m pytest -q` (full suite), orchestrator-run.
- **Budget:** `max_waves_per_run = 4`, `max_fix_iters_per_wave = 4`.

## Pre-run notes

- Most lifecycle machinery already exists on this branch; these waves close the
  remaining gaps (see `DESIGN.md` §2).
- Wave 3 must record the exact set of previously-failing test node ids here once
  triaged.
- Live deploy + hunter arming (`ANCHOR_ZOMBIE_HUNTER=1`) + zero-orphan acceptance
  demo are John-gated and intentionally OUTSIDE this run.

## Wave log

<!-- Foreman appends: wave N — execute/review/fix/gate outcomes, commits, verdicts. -->
