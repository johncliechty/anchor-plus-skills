# Anchor — Agent-Implementation Mirror

*Human mirror of `03-agent-impl.json`, rendered from the same evidence ledger (parallel projection, not derived from the JSON).*

**ISOLATION:** approximated (single-context orchestrator + fresh read-only sub-agents). **r2_mode:** mixed — local greps OBSERVED (E9,E10); test-suite GREEN is corroboration-only (pytest harness-gated, E12). **best_in_class:** N/A — brownfield single-project inventory, `experiment_run = none - claim-only`. **bandwagon_check:** no popularity claims; the one doc-consensus risk ("tests pass / done") is downgraded to single-build-origin.

## What Anchor is
Single-user plain-markdown productivity system for J.C. Liechty (`anchor_gui.py` live server on :8777 + `anchor.py` CLI), plus a newer per-project **R&D control surface** that launches the researchPrime/Crucible/Foreman trio as durable server-owned `claude -p` jobs and serves their reports.

## Findings (with level + evidence)
1. **[CORROBORATED | E2,E13,E15]** Core product is a stdlib-only markdown task system; `anchor_gui.py` (~205 KB) is the live NSSM-service app on :8777, `anchor.py` the mirrored CLI.
2. **[OBSERVED | E9,E3]** The "Python stdlib only" contract is **true** — flask/Pillow are imported only by the dead `anchor_server.py` + the optional `create_shortcut.py` icon helper, neither ships. `requirements.txt` is stale.
3. **[CORROBORATED | E11]** *(dissent: single build-origin; pytest not re-run, E12)* The R&D feature was Crucible-planned, Foreman-built across 9 waves; gate reports 158→168 tests GREEN, status done/GO.
4. **[OBSERVED | E5,E10]** The `claude` launch→stream→tail→report spine is live-proven: a real `rnd_jobs/` job invoked researchPrime and wrote artifacts into the project namespace.
5. **[OBSERVED | E10]** **effort_history is built + unit-tested but NOT wired into production** — no production caller of `record_effort/finalize_effort/attach_cost`; no `index.json`/`efforts/` on disk. Kanban effort cards, cost rollup, and C9 per-effort git auto-commit are inert in prod. *(Highest-value gap.)*
6. **[CORROBORATED | E14]** The keystone gate (answer an `AskUserQuestion` via a stdin text turn) is self-described "inherently FRAGILE/best-effort" and tested only against a **synthetic** fixture; the real-Crucible live go/no-go was never run; human SETUP gate PENDING.
7. **[CORROBORATED | E14]** Gemini support is deferred to the research lane only; the plan/build adapter is unbuilt.
8. **[CORROBORATED | E15,E6]** *(dissent: recent, not soak-tested)* Single-instance/exclusive-bind guard shipped, resolving the duplicate-supervisor/stale-server saga (commits `bb660a5`, `31a3832`).
9. **[OBSERVED | E9,E13]** `anchor_server.py` is dead legacy (Flask, :5000, old "Anchor PSU" layout) — superseded by `anchor_gui.py`.
10. **[OBSERVED | E4]** Working tree is dirty: 7 modified + 4 untracked paths uncommitted.
11. **[CLAIMED | E8]** `deliverables.py` is a real product module with tests but is **missing from `dist_manifest.txt`** → would not ship under deny-by-default.
12. **[CORROBORATED | E7]** ~29 test files cover job durability/cancel, registry, token-auth, gate adapter, project window/Kanban, lanes concurrency, report viewer, deliverables, distro PII scan (10 planted-secret fixtures), engine selector, migration; state isolated via `ANCHOR_DATA_DIR` + a stdlib `fake_claude` mock (no live billing).

## Action items (priority order)
1. **Re-run `python -m pytest -v`** to independently confirm GREEN — the 158/168 figure is the build's self-report; pytest was harness-gated here. `[E11,E12]`
2. **Wire effort_history into the live path** — call `record_effort` at launch and `finalize_effort` on terminal job status (add a completion hook in `job_runner`). Highest-value fix. `[E10]`
3. **Run the human SETUP gate**, especially the real-Crucible live go/no-go (capture a real `crucible_gate.jsonl`; confirm a plan/build gate is answerable headless). "The one residual risk." `[E14]`
4. **Exercise real-host job liveness** — launch a real `claude` job, confirm the recorded PID stays valid (no false `interrupted` dropping the folder build-lock). `[E14]`
5. **Hygiene pass** — delete/annotate stale `requirements.txt`; quarantine dead `anchor_server.py` + `dashboard_api/live.html`; add `deliverables.py` to the manifest; commit the dirty tree; update `EXECUTION-LOG` past 06-08. `[E4,E9]`

## Verify before use
- Exact current pytest pass count — harness-gated this session `[E12]`.
- `deliverables.py` missing-from-manifest — CLAIMED, single sub-agent `[E8]`.
- Production service invocation (`--no-browser`/8777) rests on docs, not a committed installer — CLAIMED `[E2]`.
- `report_viewer`/`gate_adapter`/`dir_browser` specific line behaviors — CLAIMED, single primary read `[E8]`.
