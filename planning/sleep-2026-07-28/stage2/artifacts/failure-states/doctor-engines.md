# Doctor engines failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W15 — Phase 3: Per-engine independent diagnose for Claude, Gemini, Grok with depth labels
Surface: `doctor-engines` / `diagnose` (per engine: Claude, Gemini, Grok)
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (diagnose / render / tile render). Index / rebuild /
reconcile vocabulary is honesty theater on this tile and must not appear.

**unknown** and **empty** are SEPARATE rows. Combining those two states into one
row is a build failure (hardening gates 0080/0081).

**Per engine:** every row applies independently to Claude, Gemini, and Grok.
One engine's fault does not blank or fake the other two; there is no shared
verdict across engines. Every report carries a depth label (`deep` / `shallow`
/ `unavailable`).

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | cannot_run | cannot_run | per-engine diagnose capability absent — that engine row shows named cannot_run with depth unavailable; other engines still render their own probe results |
| dependency-slow-or-killed | timeout | timeout | per-engine probe elapsed exceeds the timeout bound — that engine row shows timeout with depth shallow; sibling engines unaffected |
| dependency-returns-garbage | measurement_failed | measurement_failed | per-engine probe returned garbage / unusable payload — that engine row shows measurement_failed with depth shallow |
| backing-store-unreadable | unknown | unknown | per-engine engine store unreadable at diagnose time — that engine row shows unknown with depth unavailable; never empty, never a fabricated finding |
| empty-but-valid | empty | empty | per-engine finding scope legitimately empty — that engine row shows empty with depth shallow (empty ≠ unknown) |
| empty-but-valid | zero_measured | zero_measured | per-engine probe measured 0 findings over an existing scope — that engine row shows zero_measured with depth deep |

## Per-engine outcomes (handler)

| engine | outcome | named_state | depth | trigger |
|--------|---------|-------------|-------|---------|
| claude | healthy | ok | deep | Claude probe completed; independent of Gemini/Grok |
| gemini | healthy | ok | deep | Gemini probe completed; independent of Claude/Grok |
| grok | healthy | ok | deep | Grok probe completed; independent of Claude/Gemini |
| claude | timeout | timeout | shallow | Claude probe timed out; Gemini and Grok still show their own results |
| gemini | timeout | timeout | shallow | Gemini probe timed out; Claude and Grok still show their own results |
| grok | timeout | timeout | shallow | Grok probe timed out; Claude and Gemini still show their own results |
| any | store_unreadable | unknown | unavailable | that engine's store could not be read (unknown ≠ empty) |
| any | empty_scope | empty | shallow | that engine's finding scope legitimately empty (empty ≠ unknown) |
| any | missing | cannot_run | unavailable | that engine's diagnose capability absent |
| any | garbage | measurement_failed | shallow | that engine's probe returned unusable payload |
| any | unlabelled | (rejected) | (none) | engine report without a depth label — wave gate fails naming the engine and the unlabelled report |

## Isolation contract

* Claude, Gemini, and Grok each produce a depth-labelled report from their own probe.
* Inducing a fault in one engine leaves the other two reports intact and correctly labelled.
* No shared verdict is rendered across the three rows.
* Blanked or faked sibling rows are a build failure.

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty).
* `empty-but-valid` requires **empty** and **zero_measured** as separate rows.
* Empty finding scope and unreadable engine store are two distinct visible
  labels (empty vs unknown), stated per engine.
