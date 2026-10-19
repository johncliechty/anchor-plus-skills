# Traceability Matrix

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W21 — Phase 4: Unnamed-control sweep + dead-control audit + traceability matrix

Status may only be **CANDIDATE-MET** (structural, rendered-string level) or **OPEN**. A **MET** stamp before S1 (W22) fails the validator. S1 is the only gate that converts CANDIDATE-MET → MET.

| criterion | name | wave(s) | test file | commit SHA | trace artifact | status |
|-----------|------|---------|-----------|------------|-----------------|--------|
| 1 | open/run (+ Retry/Diagnose/restart dead-control clause) | W10 | `tests/test_open_run_2026_07_29.py` | `bbef96ec1a4fd2ecac83ecbaa15d982ffaf419cb` | `artifacts/traces/open-e2e.json; artifacts/traces/run-e2e.json` | CANDIDATE-MET |
| 2 | session attach honesty (timeout / Retry) | W11 | `tests/test_session_attach_2026_07_29.py` | `bbef96ec1a4fd2ecac83ecbaa15d982ffaf419cb` | `artifacts/traces/attach-e2e.json` | CANDIDATE-MET |
| 3 | usage/time + cost surfacing | W12, W13 | `tests/test_usage_time_surfacing_2026_07_29.py; tests/test_cost_surfacing_2026_07_29.py` | `bbef96ec1a4fd2ecac83ecbaa15d982ffaf419cb` | `artifacts/traces/usage-e2e.json; artifacts/traces/cost-e2e.json` | CANDIDATE-MET |
| 4 | Doctor diagnose + per-engine depth labels | W14, W15 | `tests/test_doctor_diagnose_2026_07_29.py; tests/test_doctor_engines_2026_07_29.py` | `bbef96ec1a4fd2ecac83ecbaa15d982ffaf419cb` | `artifacts/traces/doctor-diagnose-e2e.json; artifacts/traces/doctor-engines-e2e.json` | CANDIDATE-MET |
| 5 | stop summary + per-context restart | W16, W17 | `tests/test_stop_summary_2026_07_29.py; tests/test_restart_contract_2026_07_29.py` | `bbef96ec1a4fd2ecac83ecbaa15d982ffaf419cb` | `artifacts/traces/stop-summary-e2e.json; artifacts/traces/restart-e2e.json` | CANDIDATE-MET |
| 6 | file preview (no raw binary) | W18 | `tests/test_file_preview_2026_07_29.py` | `bbef96ec1a4fd2ecac83ecbaa15d982ffaf419cb` | `artifacts/traces/preview-e2e.json` | CANDIDATE-MET |
| 7 | projects collapsed by default + dual-profile | W19 | `tests/test_projects_collapse_2026_07_29.py` | `bbef96ec1a4fd2ecac83ecbaa15d982ffaf419cb` | `(none required)` | CANDIDATE-MET |
| 8 | status cadence from live telemetry | W20 | `tests/test_status_cadence_2026_07_29.py` | `bbef96ec1a4fd2ecac83ecbaa15d982ffaf419cb` | `artifacts/traces/cadence-e2e.json` | CANDIDATE-MET |
| 9 | instrumentation + cost honesty + conformance harness | W6, W7, W8, W9 | `tests/test_named_state_2026_07_29.py; tests/test_cost_state_2026_07_29.py; tests/test_conformance_harness_2026_07_29.py; tests/test_trace_and_faults_2026_07_29.py` | `205e7811a5c31b55cf65e2b237e56b81f2486e4b` | `(none required)` | CANDIDATE-MET |
| 10 | containment + handoff + early-slice honesty floor | W1, W2, W3, W4, W5, W10 | `tests/test_containment_smoke_2026_07_29.py; tests/test_exit_register_2026_07_29.py; tests/test_capability_inventory_2026_07_29.py; tests/test_rollup_evidence_2026_07_29.py; tests/test_freeze_gate_2026_07_29.py` | `5def4c5,205e7811a5c31b55cf65e2b237e56b81f2486e4b,bbef96ec1a4fd2ecac83ecbaa15d982ffaf419cb` | `artifacts/EARLY-SLICE-PARTIAL.md` | CANDIDATE-MET |

## Binding rules (machine-enforced in tools/dead_control_audit.py)

- Status ∈ {CANDIDATE-MET, OPEN} only; MET before S1 → validator fail
- CANDIDATE-MET requires test file + commit SHA + trace artifact field
- Surface-wave join gate: W10–W20 GREEN + commit SHA before W21 GO
- Incomplete row fails naming the criterion (never silent met)
