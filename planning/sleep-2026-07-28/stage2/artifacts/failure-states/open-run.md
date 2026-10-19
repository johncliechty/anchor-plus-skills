# Open + Run failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W10 — Phase 3: Open + Run control honesty
Surface: `open-run`
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (open / run). Doctor-tile hygiene vocabulary is
honesty theater on this tile and must not appear.

**unknown** and **empty** are SEPARATE rows. A combined `unknown/empty` row is a
build failure (hardening gates 0080/0081).

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | cannot_open | cannot_open | open capability absent — cannot open |
| dependency-missing | cannot_run | cannot_run | run capability absent — cannot run |
| dependency-slow-or-killed | timeout | timeout | open or run dependency slow or killed |
| dependency-returns-garbage | measurement_failed | measurement_failed | open or run dependency returned garbage payload |
| backing-store-unreadable | unknown | unknown | open project store unreadable — did not successfully read (never empty) |
| empty-but-valid | empty | empty | open project list legitimately empty — nothing in scope |
| empty-but-valid | zero_measured | zero_measured | open/run aggregation ran over existing scope; total is 0 |

## Enumerated cannot-open reasons (handler)

| reason | named_state | user_visible | trigger |
|--------|-------------|--------------|---------|
| no_such_project | cannot_open | cannot_open | open requested a project id that is not in the store |
| project_store_unreadable | unknown | unknown | open could not read the project store (unknown ≠ empty) |
| workspace_locked | cannot_open | cannot_open | open refused because the workspace is locked |
| capability_absent | cannot_open | cannot_open | open inventory row is not live PRESENT (ABSENT / STUB / STALE) |

## Enumerated cannot-run reasons (handler)

| reason | named_state | user_visible | trigger |
|--------|-------------|--------------|---------|
| no_runnable_target | cannot_run | cannot_run | run has no runnable target |
| engine_unavailable | cannot_run | cannot_run | run engine is unavailable |
| prior_run_in_flight | cannot_run | cannot_run | a prior run is still in flight for the target |
| capability_absent | cannot_run | cannot_run | run inventory row is not live PRESENT (ABSENT / STUB / STALE) |

## Dead-control contract

* A control is emitted only when its capability verdict is **PRESENT** on a
  non-STALE inventory row.
* Otherwise the surface renders the named cannot-* state through `render_state`
  and emits **no clickable element at all**.
* A dead Open or Run button is a **build failure**, not a finding to file later.

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty, never a zero).
* `empty-but-valid` requires **empty** and **zero_measured** as separate rows.
* `dependency-missing` covers both cannot_open and cannot_run on this surface.
