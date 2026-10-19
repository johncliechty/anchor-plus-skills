# Doctor diagnose failure-state table

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W14 — Phase 3: Doctor really diagnoses + banner→Doctor issue payload
Surface: `doctor-diagnose` / `diagnose`
Schema: failure-state-table/v1 (mapped through `artifacts/STATE-VOCABULARY-MAP.md`)

Surface-native language only (diagnose / render). Index / rebuild / reconcile
vocabulary is honesty theater on this tile and must not appear.

**unknown** and **empty** are SEPARATE rows. Combining those two states into one
row is a build failure (hardening gates 0080/0081).

## Rows (machine-readable)

| hardening | state | user_visible | trigger |
|-----------|-------|--------------|---------|
| dependency-missing | cannot_run | cannot_run | diagnose capability absent / unavailable — named unavailable state, no Diagnose control |
| dependency-slow-or-killed | timeout | timeout | diagnose probe elapsed exceeds the timeout bound (live elapsed reading still quoted) |
| dependency-returns-garbage | measurement_failed | measurement_failed | diagnose dependency returned garbage / unusable payload |
| backing-store-unreadable | unknown | unknown | health store unreadable at diagnose time — never empty, never a fabricated finding |
| empty-but-valid | empty | empty | diagnose finding scope legitimately empty (named no-finding state) |
| empty-but-valid | zero_measured | zero_measured | diagnose aggregation over existing scope yielded measured 0 findings-of-interest |

## Enumerated diagnose outcomes (handler)

| outcome | named_state | user_visible | trigger |
|---------|-------------|--------------|---------|
| health_store_unreadable | unknown | unknown | health store could not be read (unknown ≠ empty) |
| empty_finding_scope | empty | empty | finding scope legitimately empty — named no-finding (empty ≠ unknown) |
| probe_timeout | timeout | timeout | probe_elapsed_ms above bound; finding still quotes the live elapsed reading |
| capability_absent | cannot_run | cannot_run | diagnose inventory not live PRESENT — named unavailable, no clickable Diagnose |
| findings_present | (none / findings) | findings | one or more findings each quoting a live reading taken at diagnose time |
| healthy | ok | ok | all live readings match the healthy baseline |

## Dead-control contract

* Diagnose control is emitted **only** when the diagnose capability is PRESENT
  on a non-STALE live inventory row.
* Otherwise the surface renders the named unavailable state (`cannot_run`)
  through `render_state` and emits **no** clickable Diagnose element.
* A dead Diagnose button is a **build failure**, not a finding to file later.

## Banner payload handoff

* Banner passes issue id, source, observed symptom into Doctor.
* Payload id and hash of `(issue_id, source, observed_symptom)` computed at the
  banner are byte-identical to those Doctor records in the trace.
* Doctor re-running its own detection to reconstruct the issue is a test failure.

## Mapping notes

* `backing-store-unreadable` → **unknown** only (never empty).
* `empty-but-valid` requires **empty** and **zero_measured** as separate rows.
* Empty finding scope and unreadable health store are two distinct visible
  labels (empty vs unknown).
