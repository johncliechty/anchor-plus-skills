# Fault → Finding Contracts

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W14 — Phase 3: Doctor really diagnoses + banner→Doctor issue payload

One row per injectable fault. Columns record:

* **fault** — the injectable fault id
* **reading** — the live reading the fault must change at diagnose time
* **shape** — the expected finding *shape* (structural token — **never** wording)
* **notes** — how the reading is interpreted

"The outputs differ" is **not** accepted as proof of diagnosis. Each contract
requires the finding to quote the live reading the fault changed, with the
named shape.

A multi-branch template mapping injector tags to polished prose fails this
wave by construction: the anti-template test drives a fault **absent** from
this table and still requires a live-reading quote (or the named no-finding
state).

Schema: `fault-finding-contracts/v1`

## Contract rows (machine-readable)

| fault | reading | shape | notes |
|-------|---------|-------|-------|
| `service_status_down` | `service_status` | `status_value` | fault forces service_status away from healthy baseline; finding quotes the live status value |
| `process_count_zero` | `process_count` | `count_value` | fault forces process_count to 0; finding quotes the live count |
| `config_path_missing` | `config_path` | `path_value` | fault forces config_path to a missing path; finding quotes the live path |
| `version_mismatch` | `version` | `version_value` | fault forces version away from expected; finding quotes the live version |
| `probe_timeout` | `probe_elapsed_ms` | `elapsed_ms_value` | fault forces probe elapsed above timeout bound; finding quotes the live elapsed ms (surface may also name timeout) |
| `health_store_unreadable` | `health_store_readable` | `named_unknown` | fault makes the health store unreadable; diagnose emits named unknown — no fabricated findings |
| `empty_finding_scope` | `finding_scope_empty` | `no_finding` | fault marks the finding scope legitimately empty; diagnose emits the named no-finding state (empty) |

## Anti-template fault (NOT a contract row)

| fault | reading | expected |
|-------|---------|----------|
| `orphan_socket_flood` | `orphan_socket_count` | finding still quotes the live reading via baseline-diff, or named no-finding; falling through to generic prose without a live reading fails the wave |

## Shape vocabulary (structural only — never user-facing prose)

* `status_value` — finding carries a status reading value
* `count_value` — finding carries a numeric count reading
* `path_value` — finding carries a path reading
* `version_value` — finding carries a version reading
* `elapsed_ms_value` — finding carries an elapsed-ms reading
* `named_unknown` — named state unknown (store unreadable); no finding list
* `no_finding` — named no-finding / empty scope state

## Bans

* Fixed seed strings in rendered findings (literal-scan gate)
* Injector-tag → polished-prose branch maps
* Accepting "outputs differ" without quoting the changed reading
