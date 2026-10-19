# Usage + time failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W12 — Phase 3: Usage + time surfacing gated on the Rollup Evidence Gate
Surface: `usage-time`
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (tile render / usage / time). Doctor-tile hygiene
vocabulary and index / rebuild / reconcile language are honesty theater on this
tile and must not appear.

**unknown** and **empty** are SEPARATE rows. Combining those two states into one
row is a build failure (hardening gates 0080/0081). A measured zero is
**zero_measured**, never pending and never empty.

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | pending | pending | usage/time aggregator absent (NO_AGGREGATOR) — tile render shows pending naming the aggregation wave it awaits; no numeral |
| dependency-slow-or-killed | timeout | timeout | usage/time rollup dependency slow or killed during tile render |
| dependency-returns-garbage | measurement_failed | measurement_failed | usage/time dependency returned garbage payload on tile render |
| backing-store-unreadable | unknown | unknown | usage/time query failed or store unreadable (READ_FAILED) — tile render shows unknown; never empty, never a numeral, never pending wording |
| empty-but-valid | empty | empty | usage/time scope legitimately empty — tile render: nothing was ever in scope (no sessions) |
| empty-but-valid | zero_measured | zero_measured | usage/time aggregation ran over existing sessions; total is 0 — measured zero is a fact |

## Surface × verdict matrix (handler)

| surface | registry verdict | named_state | numeral | notes |
|---------|------------------|-------------|---------|-------|
| dashboard | NO_AGGREGATOR | pending | none | pending labels the aggregation wave; no numeral in the tile |
| workbench | PROVEN / zero_measured | zero_measured | 0 (measured) | visibly distinct from empty, pending, unknown |
| session_chrome | READ_FAILED | unknown | none | no numeral and no pending wording |
| any | PROVEN / empty | empty | none | empty scope ≠ measured zero |
| any | PROVEN / nonzero | ok | measured total | under signed E2: as_of stamp + reconciliation entry |

## E2 provisional data (usage/time only)

* A usage or time count may ship under signed **E2** `provisional data` with a
  visible **as_of** stamp beside the number.
* A post-hoc **reconciliation** entry is recorded in `EXECUTION-LOG.md`
  (marker `usage-time-e2-reconciliation`).
* E2 is **illegal for dollars** — cost surfaces use measurement_failed (W2/W7/W13).

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty, never a zero, never pending).
* `dependency-missing` → **pending** on this surface (aggregator not built yet).
* `empty-but-valid` requires **empty** and **zero_measured** as separate rows.
* A bare `0` for a value that was never aggregated is a build failure.
* Tile render is the surface action vocabulary (dashboard / workbench / session chrome).
