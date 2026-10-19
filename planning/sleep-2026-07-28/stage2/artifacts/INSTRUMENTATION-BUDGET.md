# INSTRUMENTATION-BUDGET

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W5 — Phase 1: Wave-list freeze + doc-trio amendment procedure

Recorded **before** surface waves need it so E4 reduced-instrument choices are
not invented under pressure.

## Load-bearing (must ship; not optional under E4)

These items are structural honesty for the North Star. They may not be dropped
by a reduced-instrument trigger:

| item | why load-bearing | owning wave(s) |
|------|------------------|----------------|
| NamedState + `render_state` | unknown ≠ empty ≠ zero_measured ≠ pending | W6 |
| Failure-state tables with unknown and empty as **separate** rows | hardening gates; no merged labels | W8 + every surface |
| `cost_state` + `render_cost` (never `$0.00` as fact) | "cost never fabricates dollars" | W7, W13 |
| Capability inventory PRESENT/STUB/ABSENT + source hash | live control authorization | W3, W5 |
| Rollup evidence PROVEN / NO_AGGREGATOR / READ_FAILED | usage/time honesty | W4, W12 |
| Dead-control contract | no clickable no-ops | W10 (+ importers) |
| End-to-end trace with `proof_level: rendered-string` | structural e2e, not human-path claim | W9, W10–W20 |
| Freeze stamp + evidence hash | surface waves cannot start on a stale plan | W5 |
| Exit register E1–E6 rules | unsigned / illegal exits HALT | W2 |
| S1 live session | only converter of CANDIDATE-MET → MET | W22 |

## Discretionary (may reduce under E4)

| item | default | reduced form under E4 |
|------|---------|------------------------|
| Delta-coverage gate | require every new route/handler in a dated test | enumerated per-handler test list (W1 probe recorded tooling absent) |
| Fault injection breadth | one fault per named failure reason per surface | one-per-reason still required; extra combinatorial faults optional |
| Multi-profile UI verify | dual-profile preference verify (W19) | single-profile + documented second-profile deferral only with signed exit |
| Spot-check sample above minimum | >20 sessions / >3 per engine | floor remains 20 (or all) and ≥3 per engine — not reducible below floor |
| Trace payload pretty-printing | human-readable JSON | minified schema-valid JSON acceptable |

## E4 reduced-instrument trigger

**Trigger (must already be true, not assumed):**

1. `artifacts/coverage-toolchain-probe.json` records
   `delta_coverage.available == false` and the fact string
   `delta-coverage unavailable` (W1 ground truth), **or**
2. A later re-probe proves the same absence, **and**
3. The wave gate records a **signed E4** in the exit register with the
   enumerated per-handler test list as the substitute evidence.

**Rules:**

- E4 never authorizes dropping a load-bearing row in the table above.
- E4 never authorizes emitting `$0.00` as fact, merging unknown/empty, or
  shipping a dead control.
- E4 is **illegal for dollars** when misread as E2 — cost surfaces still
  render `measurement_failed` / `unmeasured` via `cost_state`.
- When the trigger is **not** met (tooling present), waves must use the full
  delta-coverage path; inventing E4 while tooling exists is a gate failure.

## Snapshot at freeze (2026-07-29)

- Coverage engine: not found on this box (W1 probe).
- Delta-coverage: **unavailable** → `e4_enumerated_list_required: true`.
- Therefore surface waves W10–W20 must either install tooling and re-probe, or
  ship the enumerated per-handler list under a signed E4 — they may not claim
  delta-coverage silently.
