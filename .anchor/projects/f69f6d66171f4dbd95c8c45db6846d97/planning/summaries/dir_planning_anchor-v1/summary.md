# anchor-v1

*Lane: planning · validated, cached summary*

**When run:** 2026-06-29

**What was asked:** anchor-v1

## Actions & files produced

- Anchor v1 — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- Goal: finish Anchor v1 on branch `feat/zombie-hunter-v2` — close gandalf reaper gaps, give the zombie-hunter swarm coverage, isolate regressions, and reach deploy-readiness — **without arming the hunter or touching the live service**.
- Work happens in `C:/dev/Anchor-zombie`; `C:/dev/Anchor` is never touched. Frozen scope in `DESIGN.md`, run ledger in `EXECUTION-LOG.md`.
- Baseline: no test weakening; new behavior gets new tests; full suite green by the terminal wave.
- Ground-truth gate is a **focused, claude-free** pytest selection (zombie_hunter, session_registry, gandalf_endpoints, gandalf_engine, cancel_liveness, worktrees) — deliberately NOT the full suite, because the full suite is currently red (~3 pre-existing failures outside these modules) and spawns real `claude -p` subagents that would burn tokens if looped.
- **Wave 1 — Gandalf reaper gaps**
- Wire dead-code `gandalf.delete_run()` to a real HTTP route (`do_DELETE` or a POST prune/delete endpoint) so a run can be removed from the index.
- Add an active tree-kill cancel for an in-flight gandalf run (Job-Object close / `taskkill /T`), recording a cancelled outcome.
- Move the terminal registry update into a `finally` so a crashed `run_gandalf` never strands a session in `STATUS_RUNNING`.
- Cap/auto-prune `_append_index()` (keep newest N under the write lock) so the per-project index can't grow unbounded.
- **Wave 2 — Zombie-hunter swarm coverage**
- Closes the gap where `job_runner` swarm jobs are invisible to `zombie_hunter.sweep()` (which reads `session_registry.load_sessions()`).
- **Option A (preferred):** persist the swarm identity job_runner already computes (`crypt_token`, `pid`, `proc_create_time`) into `session_registry` at spawn so the hunter can classify it.
- **Option B (fallback):** document (DESIGN.md + code) that swarm jobs are covered only by Job-Object kill-on-close + reconcile, and test that contract.
- **Wave 3 — Regression isolation**
- Triage the ~3 full-suite failures on the branch vs master (run full suite once, capture failing node ids), fix root cause in production code without weakening tests, record modules in `EXECUTION-LOG.md`.
- The full-suite run is a **one-shot, reaped** step (immediately `taskkill /T /F` any spawned claude/agy tree) — never the loop gate. Fixed modules get added to the focused gate line.
- **Wave 4 — Deploy readiness (NO live arming)**
- Bring the branch to a defensible, conceptually merge-clean state: full suite green, reaper/registry/zombie tests pass, clean tree.
- **Explicitly out of scope / John-gated:** the actual deploy, arming the hunter (`ANCHOR_ZOMBIE_HUNTER=1`), the zero-orphan acceptance demo, and merging to master. HALT with a PLAN-AMENDMENT-PROPOSAL rather than deploy or weaken tests if green can't be reached.
- **Definition of Done:** Waves 1–4 green under the orchestrator gate; reaper gaps closed (delete route + finally-reset + index cap + active cancel); swarm coverage proven or documented; regressions fixed; full suite green with no weakened tests; branch conceptually merge-clean — with deploy, hunter arming, and the zero-orphan demo remaining John-gated and outside this run.

## Files

- [Anchor v1 — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fanchor-v1%2FIMPLEMENTATION-PLAN.md)
