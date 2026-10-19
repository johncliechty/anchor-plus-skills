# Anchor v1 — Finish-Line Design (FROZEN)

> **Role:** This is the frozen *design / description* doc for Foreman. It states
> the bar, the components in play, and the non-negotiables. The wave-by-wave work
> + machine gates live in `IMPLEMENTATION-PLAN.md`; the run ledger lives in
> `EXECUTION-LOG.md`. This doc is the source of truth for *what done means*;
> Foreman never invents requirements beyond it (a discovery that this design is
> wrong is a `PLAN-AMENDMENT-PROPOSAL` HALT, not a silent re-plan).

## 0. Context

Worktree: `C:/dev/Anchor-zombie` on branch `feat/zombie-hunter-v2`.
**The live service `C:/dev/Anchor` is OUT OF SCOPE and must not be touched.**
Most of the process-lifecycle machinery already exists on this branch (the
zombie-hunter v2 core, `proc_probe` Job-Object attach, the gandalf engine, the
job runner). This effort closes the *remaining* gaps that stand between the
branch and a defensible "Anchor v1 is finished" claim.

## 1. The D1 bar (what "finished" means)

Anchor v1 is DONE when all of the following hold on `feat/zombie-hunter-v2`:

1. **Zero orphaned processes.** Every sub-agent / swarm child Anchor spawns is
   either reaped by an OS-level guarantee (Windows Job Object
   `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) or is sweepable by the zombie-hunter
   (its crypt-token identity is discoverable in the session registry and the
   hunter can classify + reap it). No spawn path leaks an unreapable child.
2. **No manual `nssm` restart to clear state.** A crashed or interrupted run can
   never wedge a registry record in `RUNNING` forever; state self-heals so the
   operator never has to bounce the service to unstick the dashboard.
3. **Clean master (conceptually).** The branch merges to master without
   regressions: the full pytest suite is green; no test is weakened, skipped, or
   `xfail`-ed without an explicit plan citation.
4. **Dashboard shows true state.** What the dashboard reports (running / done /
   failed, live vs. zombie) matches the real OS + registry truth, because the
   records the dashboard reads are kept honest (no permanent stale `RUNNING`,
   bounded index growth).

## 2. Components in play

- **Gandalf reaper / lifecycle (`gandalf.py`).** `run_gandalf` registers a
  `RUNNING` session, runs Stage A/B, then updates to DONE/FAILED. Gaps: the
  status update is *not* in a `finally` (a crash mid-run strands `RUNNING`);
  `delete_run()` exists but is **dead code** (no HTTP route reaches it);
  `_append_index()` grows the per-project run index **unbounded** (no cap /
  auto-prune).
- **Zombie-hunter (`zombie_hunter.py`).** `classify()` + `sweep()` +
  `start_hunter()` form the user-space cryptographic sweeper. `sweep()` reads
  identities from `session_registry.load_sessions()`. Gap: **swarm jobs** spawned
  by `job_runner.py` persist their `crypt_token` / `pid` / `proc_create_time`
  into the *job* store, not into `session_registry`, so the hunter does not see
  them as sweepable (they are currently covered only by the Job-Object
  kill-on-close guarantee + reconcile, which must be made explicit).
- **Job runner (`job_runner.py`).** Spawns swarm children with an injected
  `ANCHOR_SESSION_ID_CRYPT_TOKEN`, attaches them to a Job Object, and writes a
  job record carrying `crypt_token` / `pid` / `proc_create_time`. The identity it
  already computes is the bridge Wave 2 needs.
- **Session registry (`session_registry.py`).** `register_session` /
  `update_session` / `load_sessions` — the canonical, hunter-visible session
  store.
- **Reapers / spawn cap.** Existing reaper paths + the spawn cap that bounds
  concurrent children. In-scope only to the extent their tests must stay green
  (no regressions) and the gandalf active-cancel (tree-kill) is wired.

## 3. Non-negotiables (hard constraints)

- **No live arming, no deploy inside the Foreman run.** Arming the hunter
  (`ANCHOR_ZOMBIE_HUNTER=1`), the actual deploy, and the zero-orphan acceptance
  demo are **gated on John** and stay OUT of the autonomous run (see Wave 4).
- **Do not touch `C:/dev/Anchor`** (the live service). All work is in this
  worktree.
- **Hermetic tests only.** Tests use temp `ANCHOR_DATA_DIR` / temp stores and
  never touch the live `.anchor`, port `:8777`, the network, or real long-lived
  processes (the existing `tests/conftest.py` + stub conventions).
- **No test weakening.** Per Foreman §5: reducing test count/coverage or adding
  `skip`/`xfail` without an explicit citation is an automatic HALT.
- **Stdlib-first.** Match the existing codebase (stdlib + `psutil`/`ctypes` where
  already used); no new heavy deps.

## 4. The gate (ground truth)

The orchestrator-run gate command for this project is the full pytest suite
(declared in `IMPLEMENTATION-PLAN.md` as `test-command:`). The project is DONE
only when the terminal wave's gate is GREEN under that command. Each wave below
also names a **focused pytest selection** that is the concrete acceptance for
that wave; reviewers verify the focused selection, and the orchestrator's
full-suite gate enforces no-regression.

> **Known ordering caveat (PLAN-AMENDMENT candidate).** Wave 3 fixes
> *pre-existing* full-suite failures observed on this branch. Because the
> orchestrator gate is the full suite, Waves 1–2 may not show full-suite GREEN
> until Wave 3 lands. The per-wave focused selections (which exclude the
> pre-existing-broken modules) are the real per-wave acceptance; if the operator
> wants strict autonomous GREEN per wave, Wave 3 may be promoted ahead of Waves
> 1–2 via a one-line plan amendment. The wave *content* is unchanged either way.
