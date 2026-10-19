# Baseline context (brownfield, Anchor @ v1.2.12, 2026-09-05)

## The register and its two renderings (one source today)
- `steward_cockpit/steward_campaign.py` `read_deliverables(campaign_dir)` (~1045): parses `DELIVERABLES.md`
  table rows `| What | Where | Date | Step? |`; `path` = the first backticked span (or first file-like token),
  resolved against the campaign dir; **`openable` only when the real path stays INSIDE the campaign dir**;
  `step` = the optional 4th cell (a roadmap step number or name fragment). `_plan_doc_rows` (2026-09-04) adds
  auto rows for PLAN / MASTER-PLAN / IMPLEMENTATION-PLAN / NORTH-STAR docs found under the effort.
- `steward_cockpit/static/shared.js`: `renderDeliverablesTile` (the tile, pinned first in the status pane),
  `stepDeliverables(stepName, idx1)` (~275) + `stepDelivLine(it)` (~285) — the PLAN OUTLINE's per-step rows,
  matched by the register's `step` cell; `delivRow(it)` (~439) builds the open link
  `/api/steward/deliverable-file?pid=…&dir=…&path=…` ONLY when `it.openable && it.path`; else text.
- `steward_routes.py`: verb `deliverables` (~420) → `read_deliverables`; the `deliverable-file` verb serves
  in-effort files (Office/PDF/MD rendering, 2026-09-04).

## Where skill outputs actually live (outside the effort dir)
- **Gandalf:** `gandalf.py` `list_runs`/`run_gandalf` (~228, ~359-362, ~1507): `report_rel`, `exec_rel`,
  `advisor_rel` — RELATIVE to the project folder (`.anchor/gandalf/<run>/…`); the classic window links them via
  `/artifact/<pid>?path=<rel>` (anchor_gui.py ~3281, ~3760, ~4665).
- **Lane jobs (researchPrime / Crucible / Foreman via job_runner):** session docs under
  `.anchor/projects/<pid>/<lane>/…`; `summarizer.session_doc_roles` (~1091) maps roles
  (research → exec · report · agent · provenance; planning → master · impl · northstar; build → northstar ·
  deliverable · execlog · plan) to `/report/<pid>/<lane>/<job_id>` (anchor_gui.py ~3314) and `/artifact`.
- **Foreman waves:** EXECUTION-LOG.md in the project (or the handoff dir); `finishGo` appends the GREEN line.
- **Finish hooks that exist today:** `anchor_gui._trigger_session_summary_on_finish(pid, lane, session_id)`
  (v7: hard-kill / finish→build / reconcile-dead), `gandalf.run_gandalf` finalize (index record UPSERT by
  run_id), `job_runner` completion (records under `rnd_jobs/`).
- **The effort of a run:** the steward commissions from an effort (writes `.ecgberht/attention.json` there);
  a classic-window lane job has no effort → the project root (which the cockpit treats as the root effort,
  `rel == ""`, `read_efforts` ~1255).

## The runnable link (not built)
- `planning/deliverable-runner-2026-09-04/NOTE.md`: terminal runner (a cockpit terminal + staged command),
  app slot (iframe proxy), remote display. Only the terminal runner is in scope.
- Existing pieces: `POST /api/rnd/term_start {project_id, lane:"general", backend, paste_prompt}` — v10
  PENDING PASTE: phase-1 seed submits, the `paste_prompt` sits in the input UNSENT until Enter
  (`terminal_session.pending_paste` / `_flush_pending_paste`); the project window opens `#session=<id>`.
  A `general` lane is a bare shell of the engine CLI — the staged command is typed into the ENGINE's
  composer, not a shell (an engine CLI runs shell commands on request: `!` prefix in Claude, plain ask in
  Codex) — the plan must say which it stages: the command as an instruction the engine executes, or a
  true shell PTY (does `pty_manager` support a bare shell backend? `VALID_BACKENDS` = engines only today).

## Tests that pin today's truth
- `tests/test_steward_deliverables.py` (12), `tests/test_status_lookthrough_2026_09_04.py` (plan rows),
  `tests/test_cockpit_status_window_2026_09_03.py` (one-line deliverable rows, two-stage open),
  Playwright cockpit tests (`test_cockpit_*`), Gandalf tests (`tests/test_gandalf_*`), job_runner tests.
- Gate for the build: `python -m pytest tests/test_steward_deliverables.py tests/test_status_lookthrough_2026_09_04.py tests/test_cockpit_status_window_2026_09_03.py tests/test_reports_links_2026_09_05.py -q -p no:cacheprovider` — wave 1 creates the last file.

## Constraints
- Python stdlib only; no new registry; `DELIVERABLES.md` stays the one source; containment for file rows stands.
- No auto-run: the Run link stages, the user submits.
- Anchor serves the working tree; restart only when the build is done; then the v1.2.13 ship pipeline.
