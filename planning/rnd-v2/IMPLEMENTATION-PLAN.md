# Anchor R&D Surface v2 — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, approved 2026-06-11. Frozen design: `MASTER-PLAN.md`
> (this folder). Build cwd = repo root `C:\dev\Anchor`. Each wave ends GREEN on
> the ground-truth gate and adds/extends tests under `tests/`.

test-command: python -m pytest -v

## Conventions (read before any wave)

- **Active project id:** `2fe37f39157f4c7aa3e2523baa41f40f` (the live "Anchor").
- **Retired test ids to fold+delete (Wave 2):** `bfe0e75451b94d55a706e8cb120fc5ea`,
  `227eb089706140388b829776d87e57c8` (holds the real researchPrime report),
  `5935f7dc7e664d2883e60bca6d8db1ff` ("BF Test", a temp folder — fold nothing,
  just delete). Confirm against `rnd_registry.json` at build time; do not assume.
- **No live `claude`/`gemini` in tests.** The runner-driven waves (6, 7) must be
  exercised through `tests/fake_claude.py` via `ANCHOR_RUNNER_CMD`, mirroring the
  existing `test_gated_stdin_wiring.py` / `test_lanes_concurrency.py` patterns.
- **Stdlib only at runtime.** xterm.js is vendored as a static asset like KaTeX;
  no native/compiled deps; no new pip runtime requirement.
- **f-string discipline** in `anchor_gui.py`: double literal braces in
  f-string-generated CSS/JS; `_PROJECT_WINDOW_JS` stays a RAW single-brace string.
- **Mirror** every new backend data function into `anchor.py` (Wave 8 sweeps any
  it misses, but mirror as you go where natural).

## Wave 1 — Session model + grouping

New `sessions.py` that wraps `effort_history`. Implement a session record and
`list_sessions(folder_path, project_id, lane)` that groups efforts into sessions
(run efforts by `job_id`/`output_dir`; discovered efforts by common parent dir;
fallback key = `skill` + timestamp cluster). Return newest-first. Add
`merge_sessions(...)` / `split_session(...)` helpers (escape hatch). Do **not**
touch the UI in this wave.

- **Done-when:** for the active project's discovered planning efforts,
  `list_sessions` returns exactly **2** sessions (`brownfield-discovery`,
  `rnd-v1`), each carrying its full `member_files`, ordered newest-first.
- **G/W/T:** **Given** 7 discovered planning files across 2 parent dirs, **When**
  `list_sessions(folder, active_id, "plan")`, **Then** 2 session records are
  returned newest-first and every source file appears in exactly one session's
  `member_files`.
- **Tests:** `tests/test_sessions.py` (grouping by dir, by job_id, fallback
  cluster, merge/split, empty-lane → `[]`).

## Wave 2 — Folder-history unification + reconcile + deliverable pinning

In `brownfield_scan.py` / `rnd_registry.py`: rescan also adopts sessions found in
**sibling project-ids' stores for the same folder**. Add an explicit, reviewable
`reconcile_folder(active_id)` that (a) reports what it will fold, (b) folds retired
siblings' real sessions into the active id, (c) hard-deletes the listed test ids.
Add deliverable **declare** (parse an `Anchor.md` marker block) and **pin**
(`POST /api/rnd/pin_deliverable`) paths so `anchor_gui.py` can be a deliverable.

- **Done-when:** after reconcile + rescan, the active Anchor project shows the
  researchPrime report as a **research** session, `anchor_gui.py` appears as a
  **pinned deliverable**, and `rnd_registry.json` contains exactly **one** Anchor id.
- **G/W/T:** **Given** 3 retired + 1 active same-folder ids, **When**
  `reconcile_folder(active_id)` runs, **Then** the retired ids' real sessions are
  present under the active id and the retired ids are absent from the registry.
- **Tests:** `tests/test_reconcile.py`, extend `tests/test_brownfield_adopt.py`,
  `tests/test_deliverables.py` (declare + pin).

## Wave 3 — First-class imported history (status-line, tiles, blurb)

Rework `rnd_registry.status_line()` to return per-lane **counts + provenance**
(e.g. `{planning: {count: 2, imported: 2, running: 0}}`) instead of the `import`
masquerade. In `anchor_gui.py` tile rendering: render a real per-lane summary line
and a small per-card "imported" chip (not a lane-wide state). Add a **project
blurb** field (stored on the registry entry or a sidecar), user-editable via a new
`POST /api/rnd/set_blurb`, seeded once from `CLAUDE.md`/`README`/`Anchor.md`.

- **Done-when:** the main-dashboard Anchor tile shows a blurb plus a line like
  `Research: 1 · Planning: 2 (1 imported) · Build: 1 · Deliverables: 1` — no lane
  reads "import" or "none-yet" when sessions exist.
- **Tests:** `tests/test_registry.py` (new status_line shape), a render assertion
  in `tests/test_project_window.py` or a new `tests/test_tile_render.py`.

## Wave 4 — Project window restructure (most-recent + expander, grass column, tasks)

In `render_project_window_html` / `build_kanban` (`anchor_gui.py`): render the
**most-recent session per lane** as the visible card with a **"previous sessions"**
expander holding the rest. Add the **Grass Catchers** column to `_KANBAN_COLUMNS`.
Surface task-linking: a linked-tasks strip + a **Link task** affordance using the
existing `link_task` endpoint, plus the reverse (project → its tasks).

- **Done-when:** the window shows 1 most-recent planning card + an expander
  revealing the other planning session(s); a Grass Catchers column is present; a
  linked-tasks strip with a working Link button renders.
- **G/W/T:** **Given** a lane with ≥2 sessions, **When** the window renders,
  **Then** exactly 1 session card is visible and the remainder sit behind a
  "previous sessions" toggle.
- **Tests:** extend `tests/test_project_window.py` (column set incl. grass,
  most-recent+expander markup, linked-tasks strip).

## Wave 5 — Grass Catchers content sources

Add the `grass` lane dir to `rnd_registry.LANE_DIRS`. Implement three feeds:
manual add (`POST /api/rnd/add_idea`), **promote from INBOX**
(`POST /api/rnd/promote_inbox` reading `INBOX.md`), and discovery classification of
idea-docs in `brownfield_scan.py` (`SAVED_FOR_LATER`, un-run root `*PLAN.md` stubs
not matching named trio docs, scoping notes) into the grass lane.

- **Done-when:** a manual idea can be added, an `INBOX.md` item promoted into a
  project's Grass Catchers, and discovery surfaces `planning/gemini-adapter/PLAN.md`
  as a grass candidate.
- **Tests:** `tests/test_grass_catchers.py` (three sources), extend
  `tests/test_brownfield_scan.py` (idea-doc classification).

## Wave 6 — Validated, cached summaries

New `summarizer.py`: for a session, extraction-seed from member docs → generate
**twice** → **validation pass** drops claims not grounded in the member docs →
cache `summary.json` + `summary.md` under the session. Wire a session click to a
**summary page** (reuse `report_viewer.markdown_to_html`) that renders the cached
summary with working links to each member doc, plus a **Regenerate** action
(`POST /api/rnd/regenerate_summary`). All model calls go through the runner so
they are exercised via `fake_claude.py`.

- **Done-when:** clicking the `brownfield-discovery` planning session opens a
  **cached** markdown summary (goal · key decisions · files-with-links); reopening
  serves the identical cached summary without re-running; Regenerate re-runs and
  re-caches.
- **G/W/T:** **Given** a session with member docs and a stubbed runner, **When**
  the summary is requested twice, **Then** the model runs once (first request) and
  the second request serves the cache; ungrounded claims from the stub are absent
  from `summary.json`.
- **Tests:** `tests/test_summarizer.py` (extraction seed, cache hit/miss, grounded-
  claim filtering, regenerate) using `ANCHOR_RUNNER_CMD=fake_claude`.

## Wave 7 — Interactive terminal (xterm.js + SSE + stream-json REPL)

New `rnd_terminal.py` + vendored `static/xterm.js` / `static/xterm.css`. A
persistent `claude`/`gemini` `stream-json` session per lane (build via
`job_runner`), auto-seeded with the lane's skill. Add an **SSE** stream endpoint
(`GET /api/rnd/term_stream?session=…`, stdlib chunked response) for server→client
output and a **POST** input endpoint (`POST /api/rnd/term_input`) writing user
turns to stdin. Front-end: an xterm.js terminal in the project window replacing
the raw-log console. On process exit, **auto-discover** files produced under the
session output dir and prompt the user to **confirm adoption** as a session
(reusing Wave 1 grouping + Wave 2 adopt).

- **Done-when:** "New plan run" opens a terminal that starts the plan-lane skill
  interactively; typed turns stream back; on exit the UI asks to adopt the produced
  docs as a planning session and, on confirm, the session appears in the lane.
- **G/W/T:** **Given** a stubbed interactive runner, **When** the user opens a
  plan terminal and sends a turn, **Then** the SSE stream delivers the stubbed
  assistant output and the input is written to the job stdin; **and** on stub exit
  the produced fixture files are offered for adoption.
- **Tests:** `tests/test_terminal_repl.py` (SSE framing, input→stdin wiring,
  exit→discover→adopt) via `fake_claude.py`; keep `test_gated_stdin_wiring.py`
  green.

## Wave 8 — CLI mirror + healthcheck + docs

Mirror any new backend data functions (sessions, status_line shape, reconcile,
grass, blurb, deliverable pin) into `anchor.py`. Extend `anchor_healthcheck.py` to
exercise the new endpoints and walk a synthetic session through summarize +
terminal-adopt (stubbed). Update `CLAUDE.md` to document the v2 model (session
model, summaries, Grass Catchers, terminal substrate, reconcile).

- **Done-when:** `python anchor_healthcheck.py` completes clean (or its test-mode
  equivalent passes in the suite), the full `pytest` suite is GREEN, and
  `CLAUDE.md` documents the v2 surface.
- **Tests:** extend `tests/test_healthcheck_auth.py` / add coverage for the new
  endpoint walk; `python -m pytest -v` green overall.

## Project DONE

All eight waves GREEN on `python -m pytest -v`, the active Anchor project tile and
window faithfully reflect its real research/plan/build/deliverable/grass history
with most-recent + expander and cached session summaries, and "New plan/research/
build" opens an interactive terminal that runs the right trio skill and adopts what
it produced. Terminal wave (Wave 8) is the terminal/closing wave.
