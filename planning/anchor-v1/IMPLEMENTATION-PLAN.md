# Anchor v1 — Implementation Plan (Foreman-ready)

> **Goal:** Finish Anchor v1 on `feat/zombie-hunter-v2` — close the gandalf
> reaper gaps, give the zombie-hunter swarm coverage, isolate the regressions,
> and reach deploy-readiness — WITHOUT arming the hunter or touching the live
> service. The frozen bar lives in `DESIGN.md`; the run ledger in
> `EXECUTION-LOG.md`.
> **Baseline requirement:** no test weakening; new behavior is covered by new
> tests; the full suite stays green by the terminal wave.

<!-- Foreman ground-truth gate (the single orchestrator-run test command, run
     EVERY wave/iteration). Resolution: discoverTestCommand() reads the FIRST
     matching line below.
     IMPORTANT: this is a FOCUSED, deterministic, claude-free selection — NOT the
     full suite. The full Anchor suite (a) is currently red from ~3 pre-existing
     failures OUTSIDE these modules and (b) spawns real `claude -p` integration
     subagents; running it as a per-iteration loop gate would spawn claude swarms
     and burn Claude tokens. The full-suite regression check is a ONE-SHOT,
     reaped, operator-supervised step (Wave 3), never the loop gate. -->
test-command: python -m pytest -v tests/test_zombie_hunter.py tests/test_session_registry.py tests/test_gandalf_endpoints.py tests/test_gandalf_engine.py tests/test_cancel_liveness.py tests/test_worktrees.py

Per-wave **Gate:** lines name the focused pytest selection for that wave. New
Wave-1 reaper tests go into the EXISTING `test_gandalf_endpoints.py` /
`test_session_registry.py` (covered by the orchestrator gate above) — do NOT
introduce a new gate file that wouldn't exist at first gate-run.

---

## Wave 1 — Gandalf reaper gaps

**Objective:** Make the gandalf lifecycle self-healing and bounded:
- Wire `gandalf.delete_run()` (currently dead code) to a real HTTP route — a
  `do_DELETE` handler (or a `do_POST` prune/delete route) in `anchor_gui.py` —
  so a run can actually be removed from the index from the UI/API.
- Add an **active cancel (tree-kill)** for an in-flight gandalf run: a function
  that, given a run id, terminates the in-flight Stage-A/Stage-B child process
  tree (Job-Object close / `taskkill /T` on Windows) and records the cancelled
  outcome.
- Reset the registry record in a **`finally`** so a crashed/interrupted
  `run_gandalf` never strands a session in `STATUS_RUNNING` (it must land
  DONE/FAILED/cancelled even on an exception).
- **Cap / auto-prune `_append_index()`** so the per-project run index cannot grow
  unbounded (keep the newest N, drop the tail under the write lock).

**Done when / Gate:** new tests prove (a) the delete route removes a run via
`gandalf.delete_run`; (b) an exception inside `run_gandalf` still leaves the
registry record non-`RUNNING` (finally-reset); (c) `_append_index` enforces the
cap; and the active-cancel terminates the in-flight tree. All gandalf + registry
tests pass.

  Gate: `python -m pytest -q tests/test_gandalf_endpoints.py tests/test_gandalf_engine.py tests/test_session_registry.py`

> PROMPT: Implement Wave 1 in `C:/dev/Anchor-zombie` (branch
> `feat/zombie-hunter-v2`; never touch `C:/dev/Anchor`). In `anchor_gui.py` add a
> route that reaches `gandalf.delete_run(folder, project_id, run_id)` (add
> `do_DELETE`, or a POST prune/delete endpoint — match the existing routing
> style). In `gandalf.py`: (1) move the terminal `session_registry.update_session`
> into a `finally` around the Stage-A/Stage-B body so any exception still resets
> the record off `STATUS_RUNNING`; (2) add an active cancel that tree-kills the
> in-flight run's child process (reuse `proc_probe`/Job-Object close or
> `taskkill /T`) and records a cancelled status; (3) cap `_append_index` to the
> newest N records (auto-prune the tail under `_paths.WRITE_LOCK`). Add hermetic
> tests for the delete route, the finally-reset (inject a failure), the cap, and
> the cancel. Stdlib + existing deps only; no live process, no `:8777`.

## Wave 2 — Zombie-hunter swarm coverage

**Objective:** Close the gap where swarm jobs spawned by `job_runner.py` are
invisible to `zombie_hunter.sweep()` (which reads
`session_registry.load_sessions()`). Choose ONE, and make it explicit + tested:
- **Option A (preferred):** have `job_runner` persist the swarm identity it
  already computes — `crypt_token`, `pid`, `proc_create_time` — into
  `session_registry` (via `register_session` / `update_session`) at spawn time,
  so the swarm job appears in `load_sessions()` and is classifiable by the hunter.
- **Option B (fallback):** if persisting into the session registry is rejected,
  **document explicitly** (in `DESIGN.md` + code comment) that swarm jobs are
  covered ONLY by the Job-Object kill-on-close guarantee + the reconcile path,
  and add a test that asserts that contract (Job-Object attach happens + reconcile
  classifies the job), not registry sweepability.

**Done when / Gate:** a test proves a swarm job spawned through `job_runner`
appears in `session_registry.load_sessions()` carrying its `crypt_token` and is
classifiable by `zombie_hunter.classify()` (Option A); OR a test pins the
Job-Object + reconcile-only coverage contract (Option B). Hunter + registry +
job-runner tests pass.

  Gate: `python -m pytest -q tests/test_zombie_hunter.py tests/test_session_registry.py`

> PROMPT: Implement Wave 2. In `job_runner.py`, at the point where the job record
> (already carrying `crypt_token`, `pid`, `proc_create_time`) is written, ALSO
> persist that identity into `session_registry` so `load_sessions()` exposes it
> and `zombie_hunter.classify(record, live_ids, probe)` can classify it (Option
> A). If Option A is infeasible, implement Option B: assert + document the
> Job-Object+reconcile-only coverage. Add a hermetic test (temp `ANCHOR_DATA_DIR`,
> a fake/stub process — no real long-lived child) that demonstrates the chosen
> coverage. Do not arm the hunter.

## Wave 3 — Regression isolation

**Objective:** Identify and fix the ~3 full-suite test failures present on
`feat/zombie-hunter-v2` relative to master. First triage (run the full suite,
capture the failing module list), then fix the root cause in each failing module
without weakening any test. Record the identified modules in `EXECUTION-LOG.md`.

**Done when / Gate:** the previously-failing modules pass (the focused
orchestrator gate stays green). The full-suite confirmation is a ONE-SHOT,
reaped step — NOT the loop gate.

  Gate: `python -m pytest -q tests/test_zombie_hunter.py tests/test_session_registry.py tests/test_gandalf_endpoints.py tests/test_gandalf_engine.py tests/test_cancel_liveness.py tests/test_worktrees.py` (the focused orchestrator gate; the specific previously-failing modules, once identified, are added to this line)

> PROMPT: Implement Wave 3. ⚠️ The full Anchor suite spawns real `claude -p`
> integration subagents — run it AT MOST ONCE for triage, never in a loop, and
> AFTER it finishes IMMEDIATELY reap any spawned `claude`/`agy` process tree
> (`taskkill /T /F`) so no swarm is left. Run `python -m pytest -q` ONCE from the
> repo root, capture the exact failing node ids (~3 expected), record them in
> `EXECUTION-LOG.md`, then reap. Fix the root cause in each — production code, not
> the test — unless a test is provably wrong (cite the reason). Do NOT reduce test
> count or add skip/xfail without an explicit citation (Foreman §5 = automatic
> HALT). Add the now-fixed modules to the focused Gate line above and confirm them
> green (a focused, claude-free re-run — do NOT loop the full suite).

## Wave 4 — Deploy readiness (NO live arming)

**Objective:** Bring the branch to a defensible, merge-clean state WITHOUT
deploying or arming anything. Confirm the full suite (including
`test_zombie_hunter.py` and the reaper/registry tests) is green and the tree is
clean. The actual deploy, arming the hunter (`ANCHOR_ZOMBIE_HUNTER=1`), and the
zero-orphan acceptance demo are **gated on John and stay OUT of this Foreman
run** — they are explicitly NOT part of any wave's work.

**Done when / Gate:** the full suite is green, `test_zombie_hunter.py` +
reaper/registry tests pass, no test was weakened, and no live-service deploy or
hunter arming was performed (the branch is conceptually merge-clean to master).

  Gate: `python -m pytest -v tests/test_zombie_hunter.py tests/test_session_registry.py tests/test_gandalf_endpoints.py tests/test_gandalf_engine.py` (and the full-suite `test-command:` green)

> PROMPT: Implement Wave 4 as a READINESS wave only. Run the full suite and the
> focused zombie/reaper/registry selection; confirm green and a clean tree. Do NOT
> deploy, do NOT set `ANCHOR_ZOMBIE_HUNTER=1`, do NOT run any live zero-orphan
> demo, and do NOT merge to master — those are John-gated and out of scope. If the
> branch cannot reach merge-clean green from plan content alone, HALT with a
> PLAN-AMENDMENT-PROPOSAL rather than deploying or weakening tests.

---

**Definition of Done:** Waves 1–4 GREEN under the orchestrator gate; gandalf
reaper gaps closed (delete route + finally-reset + index cap + active cancel);
swarm coverage proven or explicitly documented; regressions fixed; full suite
green with no weakened tests; branch conceptually merge-clean. Deploy + hunter
arming + zero-orphan acceptance demo remain John-gated and OUTSIDE this run.
