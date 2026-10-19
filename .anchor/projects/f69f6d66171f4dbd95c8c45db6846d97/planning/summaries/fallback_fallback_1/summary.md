# Implementation plan — Anchor durability (2026-07 review, Plan 1 Wave C)

*Lane: planning · validated, cached summary*

**When run:** 2026-07-02

**What was asked:** Implementation plan — Anchor durability (2026-07 review, Plan 1 Wave C)

## Actions & files produced

- Implementation plan — Anchor durability (2026-07 review, Plan 1 Wave C)

**Effort:** imported — no run metrics

## Goal & key decisions

- **Scope:** The plan hardens Anchor's job durability across three waves — re-launchable job specs, durable gate answers, and Gandalf boot reconcile — targeting `job_runner.py`, `gate_adapter.py`, and `gandalf.py` (plus boot wiring in `anchor_gui.py`).
- **Wave 1 — Re-launchable job specs:** every launched job persists a `relaunch_spec` (lane, cwd, prompt, output dir, gated flag, permission mode, backend, seed-only env keys, project metadata) so an `interrupted` job can be relaunched in one call. `relaunch(job_id)` refuses honestly (string reasons, never exceptions) on any non-interrupted status, unknown id, or legacy record without a spec, and links old↔new records via `relaunch_of`/`relaunched_as`.
- **Approved amendment (2026-07-02):** a relaunch goes through `launch_guarded()` so the concurrency policy (same-lane serialize, folder-build lock, spawn cap) and project-metadata propagation apply exactly as on a first launch.
- **Security/safety constraints:** only runner-seam env keys (`ANCHOR_RUNNER_CMD`, `STUB_*`, `FAKE_*`, `ANCHOR_GANDALF_*`) are persisted — never the full environment; `reconcile_on_startup()` never auto-relaunches (no restart storm launching stale jobs unattended).
- **Wave 2 — Durable gate answers:** an awaiting-input gate also writes an atomic `<job_id>.gate.json` under `paths.WRITE_LOCK`, so answering no longer requires the original process's live stdin. Answering a dead job returns `{ok, deferred: true}` and persists the answer; a later relaunch delivers it exactly once (appended to the seed prompt, `delivered_at` stamped). The live stdin path for running jobs is unchanged, and `load_pending_prompt` reads the gate file post-restart so the dashboard can still show the pending question.
- **Wave 3 — Gandalf boot reconcile:** `reconcile_dangling_runs` upserts any `in_progress` index row with no live run (not in `_ACTIVE_RUNS`, no RUNNING-alive registry record) to an honest `failed / interrupted-by-restart` terminal record — never raises — and is wired into server boot right after `job_runner.reconcile_on_startup()` for every registered project, so no perpetual "running" Gandalf row survives a restart.
- **Testing discipline:** all behavior lands with hermetic tests in `tests/test_durability_2026_07.py` (temp `ANCHOR_DATA_DIR`, stub runner via `fake_claude.py`, never real claude/node/port 8777); the gate runs pytest with `-v` because Foreman's vacuous-GREEN guard requires per-test events; stdlib-only and no-visible-window rules apply throughout.
- **Status (per git history):** all three waves were built and gated GREEN — Wave 1 (gate 40/40), Wave 2 (47/47), Wave 3 (54/54).
- **Gate:** The test command is `python -m pytest tests/test_durability_2026_07.py tests/test_review_fixes_2026_07.py tests/test_gate_adapter.py tests/test_gated_stdin_wiring.py tests/test_runner.py -v`; `-v` is mandatory because Foreman's vacuous-GREEN guard requires per-test events.
- **Conventions:** Python stdlib only; all new behavior tested hermetically in `tests/test_durability_2026_07.py` (temp `ANCHOR_DATA_DIR`, `ANCHOR_RUNNER_CMD` → `tests/fake_claude.py`, never real claude/node/port 8777); every new subprocess passes `creationflags=_paths.NO_WINDOW`; `anchor_gui.py` routes untouched except where named; the orchestrator owns git and the gate.
- **Wave 1 — Re-launchable job specs (`job_runner.py`):** persist a `relaunch_spec` on every job record at launch (lane, cwd, prompt, output_dir, gated, permission_mode, backend, seed-only env keys, project_id, folder_path — never the full environment); add `relaunch(job_id)` that refuses unless `status == interrupted` (honest `{ok:False, reason}` strings, never exceptions) and otherwise relaunches via `launch_guarded()` with full concurrency policy + project-metadata propagation (approved amendment 2026-07-02), linking records via `relaunched_as`/`relaunch_of`; `reconcile_on_startup()` unchanged — no auto-relaunch (no restart storms).
- **Wave 2 — Durable gate answers (`gate_adapter.py` + `job_runner.py` hook):** an awaiting gate also writes a durable `<jobs_dir>/<job_id>.gate.json` (atomic tmp+replace under `paths.WRITE_LOCK`); `answer_gate` on a dead job persists the answer and returns `{ok: True, deferred: True}` instead of failing; relaunch carries an unanswered gate file forward and appends an answered-but-undelivered answer to the new seed prompt with delivered-once semantics (`delivered_at`); `load_pending_prompt` prefers the durable file post-restart; the live stdin-pipe path is unchanged.
- **Wave 3 — Gandalf boot reconcile (`gandalf.py`):** add `reconcile_dangling_runs(folder_path, project_id)` that flips stale `in_progress: true` index rows (run not in `_ACTIVE_RUNS`, session not RUNNING-alive) to an honest `failed / interrupted-by-restart` terminal record, never raising; wired into the `anchor_gui.py` boot path right after `job_runner.reconcile_on_startup()` for every registered project, best-effort and logged.

## Files

- [Implementation plan — Anchor durability (2026-07 review, Plan 1 Wave C)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=IMPLEMENTATION-PLAN.md)
