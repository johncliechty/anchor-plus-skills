# Anchor R&D Control Surface — Implementation Plan (Foreman-ready)

Frozen design: see `MASTER-PLAN.md`. Human prerequisites: see `SETUP.md`. This plan is
decomposed into independently-shippable waves; every wave is `[AGENT]` (Foreman-buildable
and verified by the gate below). All elevation/service/Tailscale/host items are **not**
waves — they live in `SETUP.md` as a one-time human gate completed **before** invoking
Foreman.

## Gate (ground truth)

test-command: python -m pytest -v

- The gate is the orchestrator-run pytest suite. **Wave 1 establishes it** (a project with
  no pytest config cannot be gated). pytest is a dev/test dependency; the shipped Anchor
  product remains stdlib-only.
- Every wave must leave the full suite GREEN. Each wave adds `tests/test_*.py`.
- All runner/job waves are verified against a **deterministic mock runner** (`tests/fake_claude.py`
  + fixtures) via the `ANCHOR_RUNNER_CMD` indirection — **never** a live `claude` call and
  never real billing inside the Foreman loop. The single live validation is the `SETUP.md`
  go/no-go that also produces the gate-adapter fixture.
- The existing `anchor_healthcheck.py` (5 AM cron) is the human/integration check and is
  **out** of the Foreman gate; each wave extends it with a mock-runner round-trip.

## Wave 1 — Establish the pytest gate + test harness

**Done-when:** `python -m pytest -v` runs and is GREEN with at least one real test that
exercises a source module; `pyproject.toml` declares `[tool.pytest.ini_options]`.
- Given a fresh checkout, when `python -m pytest -v` runs, then it discovers `tests/` and reports ≥1 passing test in pytest format.
- Given the shipped product, when imports are checked, then no new third-party runtime import is added (pytest is dev-only).

Files: `pyproject.toml`, `tests/`, `tests/test_smoke.py`.

## Wave 2 — Foundations (code only)

**Done-when:** data/code decoupled via `ANCHOR_DATA_DIR`; server is `ThreadingHTTPServer`
with write-locks; token-auth middleware on mutating `/api/*`; `/api/shutdown` removed;
existing dashboard + healthcheck behavior preserved; existing projects/tasks migrated under
`ANCHOR_DATA_DIR` with zero loss.
- Given `ANCHOR_DATA_DIR` set to a tmp dir, when GUI/CLI/healthcheck resolve paths, then all read/write under it via the shared `paths` helper.
- Given two concurrent mutating requests on one markdown/JSON file, when they run under threading, then write-locks serialize them with no lost update (race test).
- Given a mutating `/api/*` call, when the token is absent/invalid, then it is rejected 401; with a valid token, it succeeds.
- Given `socket.bind` is monkeypatched to fail once, when the server starts, then the bind-retry loop recovers (Tailscale-slow-start simulation).
- Given the legacy `PROJECTS.md`/tasks, when the idempotent migration runs, then a before/after diff shows zero project/task loss and the dashboard renders unchanged.

Files: `paths.py`, `anchor_gui.py`, `anchor.py`, `anchor_healthcheck.py`, `tests/test_paths.py`, `tests/test_threading_locks.py`, `tests/test_auth.py`, `tests/test_migration.py`.

## Wave 3 — Thin registry + New Project flow + per-project store + folder-grouped window

**Done-when:** a "+ New Project" flow (create-new-folder or select-existing via a
server-side directory browser); an **id-keyed** registry where `folder_path` is **non-unique**
(N projects per folder); per-project `.anchor/projects/<id>/` scaffold with a documented
tracking policy; folder-grouped projects view + 4-state status line (none-yet); `/project/<id>`
route; single-instance behavior; task `Project:` field parsed as no-op; legacy projects
assigned stable ids.
- Given "create new folder" with a name + parent path, when run, then the folder is created (optional `git init`), a registry entry `{id,name,folder_path,priority,state}` with a fresh id is added, and `<folder>/.anchor/projects/<id>/{research,planning,build,deliverables,jobs}/` is scaffolded.
- Given "select existing" via the directory browser, when a path is chosen, then it registers as a project; a missing/moved path yields a `path-missing` state, not a crash.
- Given a folder that already hosts project(s), when selected, then the existing projects are listed and "add another project in this folder" is offered (not blocked); the new project gets its own id and isolated `.anchor/projects/<id>/`.
- Given two projects sharing one `folder_path` with different ids, when the projects view renders, then both appear grouped under that folder and their stores do not collide.
- Given a project, when priority/archive/future ops run, then the registry reflects them and archived/future entries are retained (not deleted).
- Given an open project window, when the project is opened again, then the existing instance id is returned (no duplicate window).
- Given a task line with a `Project:` field, when parsed, then it round-trips unchanged (no-op until Wave 9).

Files: `rnd_registry.py`, `dir_browser.py`, `anchor_gui.py` (new-project flow + routes + folder-grouped tiles + status-line render), `tests/test_registry.py`, `tests/test_new_project.py`, `tests/test_project_window.py`.

## Wave 4 — Mock runner + launch/tail primitive

**Done-when:** `ANCHOR_RUNNER_CMD` indirection + `tests/fake_claude.py` exist; a server-owned
job launches, streams to a durable log, is tailable via long-poll, reports liveness, and is
cleanly cancelled via tree-kill.
- Given the mock runner emitting N lines then exiting, when a job is launched, then the durable log captures N lines and the job record holds `{job_id,lane,pid,status,log_path}`.
- Given a running job, when a client long-polls `?since=K`, then it receives lines after K within the 25s ceiling, and a client disconnect does not crash the handler thread.
- Given a running job tree, when cancelled, then `taskkill /T /F` reaps it with no orphan and status → `cancelled`.
- Given a job whose process dies, when the liveness poll / startup reconciliation runs, then its status → `interrupted`.

Files: `job_runner.py`, `tests/fake_claude.py`, `tests/fixtures/`, `tests/test_runner.py`, `tests/test_cancel_liveness.py`.

## Wave 5 — Gate adapter (in-session answers)

**Done-when:** an `AskUserQuestion` tool_use parsed from the stream surfaces as a prompt
record; answering sends a single text turn that continues the session; awaiting-input is
persisted so a reattaching client can answer; answers are single-consumer.
- Given the captured-transcript fixture with an `AskUserQuestion` frame, when parsed, then a prompt-box record `{question, options, tool_use_id}` is produced and the job state → `awaiting-input`.
- Given an awaiting-input job with no attached client, when a fresh client reattaches, then it loads the pending question and submits the answer, and the job advances.
- Given two concurrent answer POSTs for one `tool_use_id`, when processed, then exactly one stdin text turn is written and the second is no-oped.

Files: `gate_adapter.py`, `tests/fixtures/gate_stream.jsonl`, `tests/test_gate_adapter.py`.

## Wave 6 — Lane wiring + concurrency

**Done-when:** research/plan/build lanes map to their skills + prompt seeds with
**per-project output paths passed into the engines**; research runs to completion (no gate);
plan/build gate in-session; within a project same-lane serialized + cross-lane concurrent;
**across projects sharing a folder, build jobs serialized at the folder level**; reattach works.
- Given a lane launch, when started, then the correct skill + prompt seed is used and the engine is given the project-scoped output path so the effort is recorded under `.anchor/projects/<id>/<lane>/` (never the folder root).
- Given a build running for a project, when a second build is requested for the **same project**, then it is serialized/refused while a research job for that project may run concurrently (mock runner).
- Given a build running in a folder, when **another project in the same folder** requests a build, then it is queued/refused with a folder-build-lock indicator, while research/plan jobs in that folder may still run concurrently.
- Given two projects in **different** folders, when both launch builds, then they run concurrently.
- Given a job and a closed browser, when reopened, then the log re-tails history → live.

Files: `lanes.py`, `job_runner.py` (folder-build-lock), `tests/test_lanes_concurrency.py`, `tests/test_folder_build_lock.py`.

## Wave 7 — Versioned history, reports + viewer, cost rollup, C9 backup

**Done-when:** efforts are job-id-scoped pointer-records (current-on-top); the report viewer
serves md (Reader + KaTeX) and PDF (default when present) for research/plan/build; cost/time/
tokens roll up per-effort → per-lane → per-project (tile + dashboard); `.anchor/` pointer-
records auto-commit per effort.
- Given multiple efforts, when history is read, then records are sorted newest-first (index 0 = most recent) and nothing is deleted on re-run (D5).
- Given an effort with `report.pdf`, when opened, then the viewer shows the PDF by default; given only `report.md`, then the Reader renders it with KaTeX math.
- Given a completed job's result envelope, when recorded, then `total_cost_usd`/tokens/`duration_ms` are stored and aggregated to the lane and the project tile.
- Given a completed effort, when finalized, then its `.anchor/` pointer-record is auto-committed (one commit per effort), reconciled with `.gitignore`.

Files: `effort_history.py`, `report_viewer.py`, `vendor/katex/` (vendored), `anchor_gui.py` (viewer + cost render), `tests/test_history.py`, `tests/test_report_viewer.py`, `tests/test_cost_rollup.py`.

## Wave 8 — Shareable, data-free distribution

**Done-when:** a deny-by-default shippable-file manifest + a no-personal-data scan produce a
clean export; a planted secret fails the build.
- Given the manifest, when the distro is built, then only manifest-allowed code files are included (data/registry/`.anchor/` excluded).
- Given a planted `C:\Users` path / `john.liechty@gmail.com` / a token / a registry artifact in the staged set, when the scan runs, then the build fails with the offending file named.
- Given a clean tree, when the distro is built, then a README is emitted and the export is publishable.

Files: `distro.py`, `dist_manifest.txt`, `tests/test_distro_scan.py`, `tests/fixtures/planted_secret/`.

## Wave 9 — Deliverables + task↔project activation

**Done-when:** deliverables run via the launch+watch primitive with per-type success
contracts; tasks link to projects and show in the project view.
- Given a deliverable of each type, when run, then: doc = read/rendered (exists+nonempty); script/skill = exit 0 / result-no-error; program = exit 0 within the timeout; status reports to the dashboard. A long-running/interactive deliverable times out cleanly (stdin-closed, non-interactive).
- Given a task with `Project: <id>`, when the project view renders, then the task appears under that project and the link round-trips through parse/serialize + healthcheck.

Files: `deliverables.py`, `anchor_gui.py` (project-tasks view), `anchor.py` (link op), `tests/test_deliverables.py`, `tests/test_task_project_link.py`.

## Project DONE
DONE = Wave 9 GREEN (orchestrator-run pytest gate) AND every prior wave GREEN. Foreman emits
a final-state verdict and stops; it does not loop past Wave 9.
