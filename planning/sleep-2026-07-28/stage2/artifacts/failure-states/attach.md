# Session attach failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W11 — Phase 3: Session attach honesty
Surface: `attach`
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (attach / retry). Doctor-tile hygiene vocabulary is
honesty theater on this tile and must not appear.

**unknown** and **empty** are SEPARATE rows. Combining those two states into one
row is a build failure (hardening gates 0080/0081). Timeout is classified as **timeout**,
never as unknown session.

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | cannot_retry | cannot_retry | attach or retry capability absent — cannot attach/retry |
| dependency-slow-or-killed | timeout | timeout | attach request exceeded attach timeout (not unknown session) |
| dependency-returns-garbage | measurement_failed | measurement_failed | attach dependency returned garbage payload |
| backing-store-unreadable | unknown | unknown | attach session store unreadable or session list could not be queried (never empty) |
| empty-but-valid | empty | empty | attach session list legitimately empty — nothing in scope |
| empty-but-valid | zero_measured | zero_measured | attach aggregation ran over existing scope; total is 0 |

## Enumerated attach reasons (handler)

| reason | named_state | user_visible | trigger |
|--------|-------------|--------------|---------|
| timeout | timeout | timeout | attach exceeded the attach timeout — classified as timeout, not unknown session |
| unknown_session | unknown | unknown | attach session id absent or not found (unknown ≠ empty) |
| empty_session_list | empty | empty | attach session list read succeeded with zero sessions |
| process_gone | cannot_retry | cannot_retry | underlying session process is gone — retry not viable |
| capability_absent | cannot_retry | cannot_retry | attach/retry inventory row is not live PRESENT (ABSENT / STUB / STALE) |
| session_store_unreadable | unknown | unknown | attach could not read the session store (unknown ≠ empty) |

## Retry contract

* ``retry_contract`` returns a viable re-issue action (re-issue attach after
  timeout) **or** ``CannotRetry(reason)``.
* When retry is not viable (process gone, unknown session, empty list,
  capability absent), the surface renders the named **cannot_retry** state
  through ``render_state`` and emits **no** Retry clickable element.
* A dead Retry button is a **build failure**, not a finding to file later.
* Timeout failures that leave the process alive expose a viable Retry that
  re-issues attach.

## Single error emission

* One component owns attach error display (``attach-error-once``).
* The NamedState label appears **exactly once** in rendered HTML (count == 1).
* Fixing double-print by hiding a second copy with CSS is disallowed.

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty, never timeout).
* `dependency-slow-or-killed` → **timeout** for the attach timeout path.
* `empty-but-valid` requires **empty** and **zero_measured** as separate rows.
* Empty session list and unreadable / unqueried session list are two distinct
  visible labels (empty vs unknown).
