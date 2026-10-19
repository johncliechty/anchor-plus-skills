# Shared artifact ledger — Anchor sleep cycle 2026-07-28 (v1.2)

**Wave:** W1 — Phase 0 · **Owner of this file:** W1 · **Validator:** `tools/artifact_ledger.py`
· **Containment proof:** `tools/containment_smoke.py`

Every artifact this build reads or writes, with its owner and its path. Three rules bind it:

1. **Paths are relative to the containment root** `planning/sleep-2026-07-28/stage2/`.
   Every `write` / `append` / `read-write` row is checked by `containment_smoke.check_write_target`
   and must resolve inside that root. No host absolute path appears in this file.
2. **`${REPO_ROOT}/` rows are `must-not-touch`** — repository-root documents belonging to *other*
   efforts. Each one must also appear in `containment_smoke.ROOT_FOREIGN_ARTIFACTS`, whose SHA-256
   is snapshotted before and after every smoke run. A ledger row promising protection the smoke
   does not enforce fails validation. The reverse drift is caught too:
   `containment_smoke.unprotected_foreign_candidates` reports any repository-root file shaped like
   another effort's Foreman document that the protected set — and therefore this table — does not
   yet cover, so the list cannot silently fall behind the repository.
3. **Rows for unbuilt waves are declarations, not claims.** A path owned by W7 does not exist yet;
   the row says who will write it and where, so containment is checked before the write, not after.

**Sign-off is a live-John item.** While the sign-off block below reads `UNSIGNED`, `artifact_ledger.gate()`
returns HALT with `live-John item — shared-artifact ledger is unsigned`. No exit substitutes for it.

## Artifacts

| id | path | owner | mode | consumed_by | notes |
| --- | --- | --- | --- | --- | --- |
| plan | IMPLEMENTATION-PLAN.md | Crucible (frozen) | read | every wave | the frozen plan; waves read it, W5's amendment procedure is the only sanctioned edit path |
| description | DESCRIPTION.md | Crucible (frozen) | read | every wave | North Star + success criteria |
| execution-log | EXECUTION-LOG.md | orchestrator | append | W9, W21, W22 | one appended row per wave with commit SHA; sub-agents never write it |
| foreman-config | foreman.config.json | orchestrator | read | orchestrator | doc-trio wiring |
| tools-pkg | tools/__init__.py | W1 | write | all tool modules | package marker for the build tooling |
| containment-smoke | tools/containment_smoke.py | W1 | write | W1, every wave's write path | write-target containment, root foreign artifact byte-identity, escape suite |
| coverage-probe-src | tools/coverage_toolchain_probe.py | W1 | write | W8 (delta-coverage / E4) | records the real coverage toolchain on this box |
| triple-src | tools/verification_task_triple.py | W1 | write | W1 gate, W22/S1 | task-triple schema, live-John HALT, Phase-0 GO decision |
| ledger-src | tools/artifact_ledger.py | W1 | write | W1 gate | parser + validator for this file |
| tests-conftest | tests/conftest.py | W1 | write | every dated test | puts the containment root on sys.path for the scoped gate |
| test-containment | tests/test_containment_smoke_2026_07_29.py | W1 | write | W1 gate | containment + escape suite + coverage-probe tests |
| test-triple | tests/test_verification_task_triple_2026_07_29.py | W1 | write | W1 gate | task-triple + ledger tests |
| task-triple | artifacts/verification-task-triple.json | W1 | write | W22 (S1) | the three reproducible tasks; John's dated confirmation required |
| this-ledger | artifacts/shared-artifact-ledger.md | W1 | write | W1 gate, every wave | this file |
| coverage-probe-record | artifacts/coverage-toolchain-probe.json | W1 | write | W8 (E4 decision) | written by the probe at gate time; idempotent when the toolchain is unchanged |
| exit-register-src | anchor/build/exit_register.py | W2 | write | W4, W13, W21, W22 | ExitId enum, signature validator, conjunction scorer, terminal status |
| exit-register-doc | artifacts/EXIT-REGISTER.md | W2 | write | W21, W22 | starts with zero signed exits |
| capability-inventory-src | tools/capability_inventory.py | W3 | write | W5, W10-W20 | PRESENT / STUB / ABSENT probes with transcripts and source hashes |
| capability-inventory-doc | artifacts/CAPABILITY-INVENTORY.md | W3 | write | W5, W10-W20 | one row per control named by criteria 1-8 plus open and run |
| transcripts | artifacts/transcripts/ | W3 | write | W3, W5 | captured-once, replayed-many probe transcripts |
| rollup-gate-src | tools/rollup_evidence_gate.py | W4 | write | W12, W13 | PROVEN / NO_AGGREGATOR / READ_FAILED with sub-verdicts |
| rollup-evidence-doc | artifacts/ROLLUP-EVIDENCE.md | W4 | write | W12, W13 | one block per rollup with query, row count, sample row, receipt |
| rollup-spot-check | artifacts/rollup-spot-check.md | W4 | write | W13, W21 | the cost spot-check record: population, sample, independence, 0-cent tolerance |
| rollup-registry-src | anchor/build/rollup_registry.py | W4 | write | W12, W13 | machine list of PROVEN rollups the surface waves import |
| wave-list-freeze | artifacts/WAVE-LIST-FREEZE.md | W5 | write | W10-W21 | frozen wave list plus the North-Star control decision table |
| doc-trio-amendment | artifacts/DOC-TRIO-AMENDMENT.md | W5 | write | any inserted wave | how a 'build it' wave is inserted without touching the repository root |
| freeze-gate-src | tools/freeze_gate.py | W5 | write | W10-W20 | blocks every surface wave until the freeze verifies |
| instrumentation-budget | artifacts/INSTRUMENTATION-BUDGET.md | W5 | write | W9, W21 | load-bearing vs discretionary instrumentation and the E4 trigger |
| named-state-src | anchor/ui/named_state.py | W6 | write | every surface wave | the NamedState enum and the single render primitive |
| zero-inference-lint | tools/zero_inference_lint.py | W6 | write | W13 gate | flags any label derived from a value being zero |
| cost-src | anchor/cost/ | W7 | write | W13 | cost_state enum, fail-closed reader, the only sanctioned cost renderer |
| migrations | migrations/ | W7 | write | W7, W13 | dated cost_state schema migration and backfill |
| conformance | tests/conformance/ | W8 | write | W10-W20 | tri-state harness, table validator, HTML and node --check asserters |
| state-vocabulary-map | artifacts/STATE-VOCABULARY-MAP.md | W8 | write | every failure-state table | the machine-read bijection between the two vocabularies |
| delta-coverage-src | tools/delta_coverage.py | W8 | write | W10-W20 gates | degrades to the enumerated per-handler list when W1's probe recorded the tooling absent |
| trace-artifact-src | anchor/build/trace_artifact.py | W9 | write | W10-W20 | the end-to-end trace schema, proof_level stamped |
| fault-inject-src | tools/fault_inject.py | W9 | write | W10-W20 | one induced fault per named failure reason |
| execution-log-src | anchor/build/execution_log.py | W9 | write | orchestrator | the append schema for EXECUTION-LOG.md |
| attestation-src | tools/attestation.py | W9 | write | W21, W22 | host-computed attestation; a sub-agent-authored one counts zero |
| traces | artifacts/traces/ | W9 | write | W10-W21 | one end-to-end trace artifact per surface wave |
| failure-states | artifacts/failure-states/ | W10 | write | W10-W21 | one surface-native failure-state table per surface |
| dead-control-src | anchor/ui/dead_control.py | W10 | write | W11, W17 | the shared dead-control contract |
| session-src | anchor/session/ | W10 | write | W11, W16, W17 | open, run, attach, stop summary, restart entry points |
| ui-src | anchor/ui/ | W10 | write | W10-W20 | every view renders through render_state |
| early-slice-partial | artifacts/EARLY-SLICE-PARTIAL.md | W10 | write | W21, W22 | the labelled partial-slice declaration |
| usage-src | anchor/usage/ | W12 | write | W12 | reads only rollups marked PROVEN |
| doctor-src | anchor/doctor/ | W14 | write | W14, W15 | real diagnosis, banner handoff, per-engine probes and depth labels |
| fault-finding-contracts | artifacts/FAULT-FINDING-CONTRACTS.md | W14 | write | W14 gate | one row per injectable fault: the reading it must change and the finding shape |
| restart-contexts | artifacts/RESTART-CONTEXTS.md | W17 | write | W17, W21 | every restart context with its single control and preserved/lost contract |
| restart-audit-src | tools/restart_control_audit.py | W17 | write | W17 gate | asserts exactly one restart control per context |
| files-src | anchor/files/ | W18 | write | W18 | the shared human-friendly preview path and the binary guard |
| projects-tree-js | static/js/projects_tree.js | W19 | write | W19 | collapsed-by-default at the real JS path |
| projects-collapse-root-cause | artifacts/root-cause-projects-collapse.md | W19 | write | W19, W21 | the actual defect mechanism, written down |
| status-src | anchor/status/ | W20 | write | W20 | timer-owned cadence and named staleness states |
| dead-control-audit-src | tools/dead_control_audit.py | W21 | write | W21 gate | enumerates every rendered control |
| ambiguous-zero-audit-src | tools/ambiguous_zero_audit.py | W21 | write | W21 gate | sweeps rendered HTML for numerals not produced by render_state / render_cost |
| traceability-matrix | artifacts/TRACEABILITY-MATRIX.md | W21 | write | W22 | criterion to wave to test to SHA to trace; CANDIDATE-MET or OPEN only |
| out-of-criteria-surfaces | artifacts/OUT-OF-CRITERIA-SURFACES.md | W21 | write | W22 | each closed as fixed, disabled, or a signed E3 |
| s1-validation | artifacts/S1-VALIDATION.md | W22 | write | John | the live session script over this triple, with John's dated result per step |
| s1-findings-src | anchor/build/s1_findings.py | W22 | write | W22 | the four violation classes are BUILD_BLOCKING, never E6 |
| release-guard-src | tools/release_guard.py | W22 | write | W22 gate | nothing from this effort is publishable to v1.1.x collaborators |
| tests-tree | tests/ | every wave | write | orchestrator gate | one dated test file per wave, matched by the scoped gate keyword |
| root-description | ${REPO_ROOT}/DESCRIPTION.md | another effort | must-not-touch | nobody | repository-root doc-trio; SHA-256 compared before and after every smoke run |
| root-implementation-plan | ${REPO_ROOT}/IMPLEMENTATION-PLAN.md | another effort | must-not-touch | nobody | repository-root doc-trio |
| root-execution-log | ${REPO_ROOT}/EXECUTION-LOG.md | another effort | must-not-touch | nobody | repository-root doc-trio |
| root-decision-log | ${REPO_ROOT}/DECISION-LOG.md | another effort | must-not-touch | nobody | repository-root planning doc |
| root-handoff | ${REPO_ROOT}/HANDOFF.md | another effort | must-not-touch | nobody | repository-root handoff doc |
| root-session-handoff | ${REPO_ROOT}/SESSION-HANDOFF.md | another effort | must-not-touch | nobody | repository-root handoff doc |
| root-foreman-log-2026-07 | ${REPO_ROOT}/FOREMAN-EXECUTION-LOG-2026-07.md | another effort | must-not-touch | nobody | a different Foreman run's log |
| root-foreman-log-rearch | ${REPO_ROOT}/FOREMAN-EXECUTION-LOG-REARCH.md | another effort | must-not-touch | nobody | a different Foreman run's log |
| root-foundry-description | ${REPO_ROOT}/FOUNDRY-V2-DESCRIPTION.md | another effort | must-not-touch | nobody | the Foundry v2 doc-trio |
| root-foundry-plan | ${REPO_ROOT}/FOUNDRY-V2-IMPLEMENTATION-PLAN.md | another effort | must-not-touch | nobody | the Foundry v2 doc-trio |
| root-foundry-log | ${REPO_ROOT}/FOUNDRY-V2-EXECUTION-LOG.md | another effort | must-not-touch | nobody | the Foundry v2 doc-trio |
| root-anchor-state | ${REPO_ROOT}/ANCHOR-STATE.md | another effort | must-not-touch | nobody | repository-root state summary |
| root-phase3-foreman-tuning | ${REPO_ROOT}/PHASE3-FOREMAN-TUNING.md | another effort | must-not-touch | nobody | a different Foreman effort's tuning report |
| root-overhaul-report | ${REPO_ROOT}/ANCHOR-OVERHAUL-REPORT-2026-07.md | another effort | must-not-touch | nobody | a different effort's overhaul report |
| root-wave4-summary | ${REPO_ROOT}/WAVE4-EXECUTE-SUMMARY.md | another effort | must-not-touch | nobody | a different Foreman run's per-wave execute summary |
| root-wave7-summary | ${REPO_ROOT}/WAVE7-EXECUTE-SUMMARY.md | another effort | must-not-touch | nobody | a different Foreman run's per-wave execute summary |
| root-wave8-summary | ${REPO_ROOT}/WAVE8-EXECUTE-SUMMARY.md | another effort | must-not-touch | nobody | a different Foreman run's per-wave execute summary |

## Sign-off

- **status:** SIGNED
- **signed_by:** John
- **date:** 2026-07-29
- **line:** Phase-0 ledger reviewed via steward: containment root is stage2 only; root foreign Foreman artifacts listed must-not-touch; product fixes for empty-HEAD worktree + honest usage row recorded this day; John directed steward to complete Phase-0 and drive Foreman without further re-asks.

Fill the four fields above to sign. status must read SIGNED, date must be an ISO
YYYY-MM-DD, and signed_by and line must be non-empty; anything less stays UNSIGNED and the
Phase-0 gate stays HALT.
