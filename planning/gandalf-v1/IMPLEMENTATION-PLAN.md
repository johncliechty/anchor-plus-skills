# Anchor Gandalf Integration v1 — Implementation Plan (Foreman-ready)

> test-command: `python -m pytest -q`  ·  branch `gandalf-integration` off master `7c2f51f`.
> Baseline GREEN 1426 + 1 skip. Every wave holds or grows the test count. Hermetic: stub BOTH seams
> (`ANCHOR_RUNNER_CMD` → canned RAW draft; `ANCHOR_GANDALF_HOST_CMD` → canned GRADED advisor-output.json);
> temp git/data dirs; `ANCHOR_PROACTIVE_SUMMARY` off; NEVER bind :8777 / real claude / real node-skill /
> network. Playwright DEV-ONLY (`pytest.importorskip`). The design is the converged `MASTER-PLAN.md`.

## Wave 1 — `gandalf.py`: the two-stage engine + store + index (backend)
**Goal:** `gandalf.py` (stdlib only) turns a project into a stored, graded Gandalf run.
**Changes:**
- `run_gandalf(folder_path, project_id, *, force=False, env=None) -> dict`:
  - **Stage A** — build the embedded-protocol prompt (read `SKILL.md` from `ANCHOR_GANDALF_SKILL_DIR`; ask
    for ONLY the RAW draft per `runtime/RAW-DRAFT-CONTRACT.md`), `job_runner.launch` with `cwd=folder`,
    `--add-dir folder`, the `ANCHOR_GANDALF_TIMEOUT` (default 600s), forwarded `env` →
    `extract_assistant_text` → last-balanced-JSON parse → the raw draft.
  - **Stage B** — run `ANCHOR_GANDALF_HOST_CMD` (default `node "<skilldir>/runtime/gandalf-run.mjs"`) feeding
    the raw draft on stdin, capture the graded `advisor-output.json` on stdout (or a tmp `--output`); a
    non-zero exit / absent node → an honest **error run** (`ok:false, reason`), never fabricated.
  - Render `report.md` (full) + `exec-summary.md` (verdict + top findings-by-severity + top elevations);
    one-line verdict = cleaned top-level `verdict` (`summarizer.short_summary_text`). Write
    `report.md`/`exec-summary.md`/`advisor-output.json` to `<folder>/gandalf/run-<ts>/`; append a SAFE record
    to `.anchor/projects/<id>/gandalf/index.json` (newest-first, `GANDALF_INDEX_SCHEMA_VERSION`) under
    `paths.WRITE_LOCK`. Add `gandalf/` to the project `.gitignore` (best-effort).
- `run_gandalf_if_absent(...)` (first-scan no-op-if-prior-run); `list_runs(...)` (newest-first SAFE
  projections: ts·run_id·verdict·cross_model·degraded·ok·report_rel·exec_rel·reason?); `get_run(...)`.
- `tests/stub_gandalf_draft.py` (canned RAW draft) + `tests/stub_gandalf_host.py` (canned GRADED output) +
  `tests/test_gandalf_engine.py`.
**Done-when (`pytest -q tests/test_gandalf_engine.py` green; full suite ≥ baseline):**
- Given the stubbed runner (raw draft) + stubbed host (graded output), When `run_gandalf`, Then a `run-<ts>/`
  with `report.md`+`exec-summary.md`+`advisor-output.json` exists AND `index.json` has one newest-first SAFE
  record (no absolute paths); `list_runs` returns it.
- A second `run_gandalf` appends a 2nd newest-first entry; `run_gandalf_if_absent` no-ops when a run exists.
- A stage-A unparseable draft OR a stage-B host failure (non-zero / absent `ANCHOR_GANDALF_HOST_CMD`) →
  an `ok:false` error run with a reason; no fabricated verdict; never raises to the caller.
- The one-line verdict is the cleaned top-level `verdict`; degraded/cross_model carried from the graded JSON.

## Wave 2 — endpoints + first-scan hook (backend)
**Goal:** manual re-run + read endpoints + the first-scan auto-run, never blocking render.
**Changes:**
- `POST /api/rnd/gandalf_run {project_id}` (token-authed) → schedule `run_gandalf` in a daemon thread
  (`{ok,scheduled:true}` immediately; per-project in-flight guard; NOT module-flag-gated — manual is explicit).
- `GET /api/rnd/gandalf?project_id=<id>` (`?token=`) → `gandalf.list_runs` SAFE projection.
- `_trigger_gandalf(...)` mirroring `_trigger_project_summary` (module flag `_PROACTIVE_SUMMARY_ENABLED` +
  runner-env snapshot forwarded to `launch`), hooked into the register/open/rescan block; first-run-ONLY via
  `run_gandalf_if_absent` behind a per-project `threading.Lock` (check-and-set BEFORE scheduling — no TOCTOU).
- `tests/test_gandalf_endpoints.py` (loopback server, token-authed; the trigger gating + the TOCTOU
  single-fire under two concurrent calls).
**Done-when (`pytest -q` green ≥ baseline):** the manual endpoint schedules exactly one run (in-flight guard);
the read endpoint returns the SAFE projection + 401 unauthed; the first-scan trigger fires once when absent
and is suppressed when `ANCHOR_PROACTIVE_SUMMARY` is off; two concurrent first-scan calls schedule ≤1 run.

## Wave 3 — the white-wizard Gandalf tab (UI — JOHN SIGN-OFF GATE)
**Goal:** a right-column "Gandalf" tab ABOVE Grass with run history + grade chips + report links.
**Changes:**
- `vendor/brand/gandalf-white-icon.svg` (Gandalf the WHITE — white robes/staff; served by `/vendor/brand/`).
- `_render_layoutd_gandalf_panel(folder_path, project_id)` inserted in `_render_layoutd_html` BEFORE
  `{grass_panel}` in `<div class='rightcol'>`: header (icon + "Gandalf" + a "Re-run" button); newest-first
  rows (one-line verdict + ts + a `SPECULATIVE`/`PROMISING` + `cross_model`/`degraded` chip); clicking a row
  **inline-expands** the exec-summary, with `[Full report]` + `[raw JSON]` `/artifact` links; an honest
  **degraded/error** row (reason, no dead links); honest empty state ("No Gandalf read yet" + Run). HTML
  f-string (double braces); panel JS in the RAW `_PROJECT_WINDOW_JS`. Render reads `index.json` only (no model
  call). Add a mockup `planning/gandalf-v1/_mockups/gandalf_tab.html`.
**Done-when:** rendered-DOM assertions (positive: tab present above grass with rows/chips/links; negative:
honest empty state, no dead links on an error run) + a real Playwright+Chromium test (click a row → exec
summary expands; click Re-run → POST fires) with machine-checkable pass conditions + an orchestrator
screenshot vs `_mockups/gandalf_tab.html` + **John's explicit sign-off**. Render-smoke before Playwright.

## Wave 4 — CLI mirror + healthcheck + distro + docs (PROJECT DONE)
**Goal:** the read seam mirrored, a fully-stubbed surface walk, distro green, docs updated.
**Changes:**
- `anchor.py`: `rnd gandalf <pid>` → `gandalf.list_runs` (read-only, newest-first, honest "No Gandalf read yet").
- `anchor_healthcheck.check_gandalf_surface` — fully stubbed (both seams + temp data/git dirs +
  `ANCHOR_PROACTIVE_SUMMARY` off): run → 3 artifacts + index → `list_runs` shape → re-run appends → an error
  run recorded honestly. Snapshots/restores `ANCHOR_RUNNER_CMD`/`ANCHOR_GANDALF_HOST_CMD`/
  `ANCHOR_GANDALF_SKILL_DIR`/`ANCHOR_PROACTIVE_SUMMARY`, temp dirs in `rnd_env["v3_temp_dirs"]`, registered in
  `main()` after `check_rnd_v12_surface`; never binds :8777.
- `distro.py`/`dist_manifest.txt`: add `gandalf.py` + `vendor/brand/gandalf-white-icon.svg`; import scan green
  (assert the SVG manifest entry in the distro test).
- `CLAUDE.md` + `SESSION-HANDOFF.md` updated (the Gandalf surface + the two-stage host engine + the
  ANCHOR_GANDALF_* env seams + the deploy note: first-scan auto-runs one Gandalf per registered project).
**Done-when:** `pytest -q` green ≥ baseline incl. `check_gandalf_surface`; `rnd gandalf` mirrors honestly;
distro scan green with the new module + SVG; docs updated.
