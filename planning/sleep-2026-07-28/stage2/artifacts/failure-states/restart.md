# Restart failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W17 — Phase 3: Per-context restart contract
Surface: `restart`
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (restart). Doctor-tile hygiene vocabulary is
honesty theater on this surface and must not appear.

**unknown** and **empty** are SEPARATE rows. A combined `unknown/empty` row is a
build failure (hardening gates 0080/0081).

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | cannot_restart | cannot_restart | restart capability absent for this context — named cannot_restart; no dead Restart button |
| dependency-slow-or-killed | timeout | timeout | restart dependency slow or killed during restart control render |
| dependency-returns-garbage | measurement_failed | measurement_failed | restart dependency returned garbage payload during restart |
| backing-store-unreadable | unknown | unknown | restart store unreadable — did not successfully read (never empty) |
| empty-but-valid | empty | empty | restart scope legitimately empty — nothing in scope to restart |
| empty-but-valid | zero_measured | zero_measured | restart aggregation over existing scope measured total 0 |

## Enumerated cannot-restart reasons (handler)

| reason | named_state | user_visible | trigger |
|--------|-------------|--------------|---------|
| capability_absent | cannot_restart | cannot_restart | restart inventory row is not live PRESENT (ABSENT / STUB / STALE) |
| no_target | cannot_restart | cannot_restart | restart has no target id in this context |
| target_gone | cannot_restart | cannot_restart | restart target process or record is gone |
| store_unreadable | unknown | unknown | restart store could not be read (unknown ≠ empty) |
| empty_scope | empty | empty | restart scope list is legitimately empty |
| already_restarting | cannot_restart | cannot_restart | a restart is already in flight for this target |
| engine_unavailable | cannot_restart | cannot_restart | engine restart refused because the engine is unavailable |

## Per-context control contract

Exactly one restart control per context (`run` / `session` / `engine` /
`workbench`). Each control names its scope and preserved/lost contract. Dual
competing controls in one context (e.g. bare `Restart` + `Restart session`) are
a **build failure** detected by `tools/restart_control_audit.py`.

## Dead-control contract

* A restart control is emitted only when its capability verdict is **PRESENT**
  on a non-STALE inventory row.
* Otherwise the surface renders the named cannot_restart state through
  `render_state` and emits **no clickable element at all**.
* A dead Restart button is a **build failure**, not a finding to file later.

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty, never a zero).
* `empty-but-valid` requires **empty** and **zero_measured** as separate rows.
* `dependency-missing` covers cannot_restart for every restart context.
* Surface actions: restart.
