# WAVE-LIST-FREEZE

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W5 — Phase 1: Wave-list freeze + doc-trio amendment procedure

## Freeze metadata

**Owner:** orchestrator
**Gate:** John's Phase-1 verdict review
**Freeze date:** 2026-07-29
**Freeze stamp:** STAMPED
**Stamp status:** STAMPED
**John Phase-1 verdict review:** John Phase-1 review: freeze accepted via steward 2026-07-29.
**Evidence hash:** `461d489e3d53fe0069941756b9130c1799aed08427051c97c4820858ea4197d0`
**Inventory+rollup hash:** `461d489e3d53fe0069941756b9130c1799aed08427051c97c4820858ea4197d0`
**Inserted build-it count:** 0
**Inserted build it count:** 0
**Insertion cap:** 3
**Re-baseline:** not recorded

Evidence hash binds this freeze to the current bytes of `artifacts/CAPABILITY-INVENTORY.md` and `artifacts/ROLLUP-EVIDENCE.md`. Any later edit that changes those bytes makes this freeze **stale**; surface waves must not proceed until re-freeze via `artifacts/DOC-TRIO-AMENDMENT.md`.

## Frozen wave list

- W1 — Phase 0: John task triple, containment smoke, shared-artifact ledger
- W2 — Phase 0: Exit register engine + status-string generator
- W3 — Phase 1: Capability Inventory harness
- W4 — Phase 1: Rollup Evidence Gate
- W5 — Phase 1: Wave-list freeze + doc-trio amendment procedure
- W6 — Phase 2: Named-state vocabulary + render primitive
- W7 — Phase 2: cost_state enum + migration + dollar-fabrication ban
- W8 — Phase 2: Tri-state conformance harness + failure-state table validator
- W9 — Phase 2: End-to-end trace schema, fault injection, EXECUTION-LOG schema
- W10 — Phase 3: Open + Run control honesty
- W11 — Phase 3: Session attach honesty
- W12 — Phase 3: Usage + time surfacing
- W13 — Phase 3: Cost surfacing from cost_state
- W14 — Phase 3: Doctor really diagnoses + banner payload
- W15 — Phase 3: Per-engine independent diagnose (Claude/Gemini/Grok)
- W16 — Phase 3: Stop summary tile backed by real in-flight inventory
- W17 — Phase 3: Per-context restart contract
- W18 — Phase 3: File preview via shared human-friendly path
- W19 — Phase 3: Projects collapsed by default + remembered preference
- W20 — Phase 3: Cadence telemetry with as_of/staleness named states
- W21 — Phase 3: Close-out audits + traceability matrix
- W22 — S1: Live North-Star validation session with John

## Delta vs plan

- Inventory: open/run/retry/restart*/stop_summary/preview/projects_collapse/cadence = ABSENT → already planned surface waves (no plan-wave insert).
- Inventory: diagnose + per-engine diagnose = STUB / build it → owned by planned W14/W15 (counts against STUB disposition, not against the 3-insert cap until an *extra* wave is added).
- Rollups: all criterion-3 rollups = NO_AGGREGATOR → surfaces render pending; aggregation work stays inside planned W12/W13.
- No PRESENT North-Star control at freeze → zero signed-exit rows; every North-Star control is build now.
- Inserted build-it waves at freeze: 0 of 3 (cap unexceeded).

## NORTH-STAR CONTROL DECISION

Each North-Star verb/control is forced into exactly one of two states:

- **build now** — names the wave that builds it; or
- **signed exit** — PRESENT verdict, in-bound transcript, matching
  source hash, and John's dated `no further work` line.

A row left blank, deferred, marked ambient, annotated `S1 will catch it`, or `covered by the verification task triple` fails the freeze.

| control | decision | inventory cites | notes |
|---------|----------|-----------------|-------|
| `open` (open) | build now: W10 | `open` | surface wave owns control |
| `run` (run) | build now: W10 | `run` | surface wave owns control |
| `stop` (stop) | build now: W16 | `stop_summary` | surface wave owns control |
| `restart` (restart) | build now: W17 | `restart_run`, `restart_session`, `restart_engine`, `restart_workbench` | surface wave owns control |
| `doctor_diagnose` (Doctor diagnose) | build now: W14 | `diagnose`, `diagnose_claude`, `diagnose_gemini`, `diagnose_grok` | surface wave owns control |
| `session_attach` (session attach) | build now: W11 | `retry` | surface wave owns control |

## Binding rules (machine-enforced in tools/freeze_gate.py)

- Surface waves: **W10–W21** only (W6–W9 are Phase-2 primitives).
- Unstamped freeze → HALT: `wave-list freeze not stamped — surface waves blocked`
- Hash mismatch → HALT: `wave-list freeze stale — inventory/rollup hash mismatch; re-freeze via DOC-TRIO-AMENDMENT procedure required`
- Fourth inserted build-it wave → `HALT_REBASELINE`
- STALE inventory cites fail closed.
