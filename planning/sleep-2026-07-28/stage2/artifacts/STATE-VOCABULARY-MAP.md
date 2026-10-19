# STATE-VOCABULARY-MAP

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W8 — Phase 2: Tri-state conformance harness + failure-state table validator

Machine-read bijection between the **hardening-gate dependency vocabulary**
and the **surface-native NamedState** members. Every term on both sides appears
**exactly once**. A term that appears on neither side is a build failure
(`table_validator.py` / `load_vocabulary_map`).

Schema: `state-vocabulary-map/v1`

## Hardening dependency vocabulary (exactly once each)

These five terms are the required failure-state rows every surface-bearing
table must answer (hardening-gate vocabulary):

1. `dependency-missing`
2. `dependency-slow-or-killed`
3. `dependency-returns-garbage`
4. `backing-store-unreadable`
5. `empty-but-valid`

## Surface-native NamedState vocabulary (exactly once each)

The thirteen `NamedState` members from W6 (`anchor/ui/named_state.py`):

1. `ok`
2. `unknown`
3. `empty`
4. `zero_measured`
5. `pending`
6. `unmeasured`
7. `measurement_failed`
8. `timeout`
9. `stale`
10. `cannot_retry`
11. `cannot_open`
12. `cannot_run`
13. `cannot_restart`

## MAP (machine block — do not hand-edit the fences)

Each hardening term appears once on the left. Each NamedState token appears
once across the right-hand lists. `empty-but-valid` expands to the empty /
zero_measured / pending / ok family per the binding definitions.
`backing-store-unreadable` maps **only** to `unknown` (never empty, never a zero).

```vocab-map
schema: state-vocabulary-map/v1
dependency-missing: cannot_open, cannot_run, cannot_retry, cannot_restart
dependency-slow-or-killed: timeout, stale
dependency-returns-garbage: measurement_failed, unmeasured
backing-store-unreadable: unknown
empty-but-valid: empty, zero_measured, pending, ok
```

## Required surface-table rows

A surface failure-state table is **conformant only when complete**:

| required_row (hardening) | must map to NamedState | notes |
|--------------------------|------------------------|-------|
| dependency-missing | cannot_* (open/run/retry/restart per surface) | capability or engine absent |
| dependency-slow-or-killed | timeout (or stale when freshness bound) | slow kill / timeout path |
| dependency-returns-garbage | measurement_failed (or unmeasured) | garbage / unusable payload |
| backing-store-unreadable | unknown | **never** empty, **never** zero |
| empty-but-valid | empty **and** zero_measured as SEPARATE surface rows; pending when no aggregator | empty ≠ zero_measured |

Additionally (W6 hardening 0080/0081, enforced again here):

- **unknown** and **empty** are SEPARATE rows (never `unknown/empty`)
- every row names a **user-visible string** and a **trigger**
- rows are written in the surface's own actions (`open`, `run`, `attach`,
  `diagnose`, `preview`, `restart`, `tile render`) — **index / rebuild /
  reconcile** language on a user-facing tile is honesty theater and fails
  `table_validator.py`

## Surface-native action vocabulary (allowed on user-facing tiles)

`open`, `run`, `attach`, `diagnose`, `preview`, `restart`, `tile render`,
`retry`, `stop`, `render`

## Honesty-theater verbs (forbidden on user-facing tiles)

`index`, `rebuild`, `reconcile` — allowed only on surfaces that are themselves
index-bearing; on Doctor / cost / usage / open-run tiles they fail validation
by name, not as a style note.
