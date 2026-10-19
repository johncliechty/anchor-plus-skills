# Anchor R&D Surface v5 — "Durable Work" — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, locked 2026-06-14. Frozen design: `MASTER-PLAN.md`
> (this folder) + the approved mockup `_mockups/grass_catcher_refined.html` (Grass
> B+C hybrid). Build cwd = repo root `C:\dev\Anchor`. Each wave ends GREEN on the
> ground-truth gate and adds/extends tests under `tests/`.

test-command: python -m pytest -v

## Conventions (read before any wave)

- **Active Anchor project id:** read from `rnd_registry.json` at build time; never
  hard-code. Note `2fe37f39…` is retired; the live Anchor is the active one.
- **No live `claude`/`gemini`/real-PTY in the gate.** Model calls via
  `tests/fake_claude.py` through `ANCHOR_RUNNER_CMD`; PTY via the stub backend
  (`ANCHOR_PTY_BACKEND=stub`). Never `:8777` or real data; any spawned
  preview/service uses an OS-assigned port HARD-guarded `!= 8777` + isolated temp
  `ANCHOR_DATA_DIR`.
- **pywinpty** is the only native dep (lazy, `pty_manager.py` only). **Playwright is
  a DEV-ONLY test dep** — import it via `pytest.importorskip("playwright.sync_api")`
  so the suite skips cleanly where it's absent; NEVER import it in product code.
  `distro.py`'s import scan must stay green (Wave 6 asserts it).
- **f-string discipline** in `anchor_gui.py`: `_PROJECT_WINDOW_JS` is a RAW
  single-brace string; double literal braces in f-string HTML/CSS.
- **Security:** every new mutating / terminal / launch endpoint behind the existing
  `do_POST` token gate; GET read-only (token via `?token=`).
- **Reuse, don't fork:** build on `terminal_session.py`, `pty_manager.py`,
  `session_registry.py`, `summarizer.py`, `deliverables.py`, `effort_history.py`,
  `handoff.py`, `job_runner.py`, `report_viewer.py`, `vendor/xterm`.
- **UI VERIFICATION IS MANDATORY (the v4 lesson — non-negotiable).** For ANY wave
  that changes the rendered UI, "GREEN" requires ALL of: (a) **rendered-DOM
  assertions** — parse the served HTML (style/script stripped) with `html.parser`,
  assert the new structure is present AND the replaced/old structure is absent
  (positive + negative); (b) a **real Playwright + Chromium interaction test**
  (boot a throwaway `make_server('127.0.0.1',0)`, click the actual control, assert
  the resulting DOM + no JS console errors) — model it on
  `tests/test_cockpit_paradigm2.py`; (c) the **orchestrator captures a screenshot**
  and visually checks it against the relevant mockup; (d) **user sign-off before
  merge**. A string-grep-only test is NOT acceptable and is an automatic wave HALT.

## Wave 1 — Run lifecycle: close-to-tile vs. deliberate hard-kill

Stop losing work. In the project-window JS (`_PROJECT_WINDOW_JS`): the panel header
**X = CLOSE the panel only** — the session record stays in the registry and its
**tile remains in the lane** (a running session keeps running; a done one stays
done). Add a **separate, visually distinct hard-KILL control** (e.g. a 🗑/"Kill"
button distinct from X) that, behind an "Are you sure?", terminates the session
(`/api/rnd/term_kill` → reap PTY + remove worktree) AND removes its tile. Ensure a
session closed-to-tile can be **reopened** (clicking its tile re-opens the panel and
re-attaches a live terminal or shows the summary). Reconcile already re-statuses dead
sessions; closing must not reap.

- **Done-when:** the full UI-verification set passes — closing a panel keeps the
  session as a reopenable tile (record + tile persist; live PTY not reaped); the
  separate kill control reaps + removes the tile (no orphan PTY/worktree); reopening
  a closed tile restores its panel.
- **G/W/T:** **Given** a live (stub-PTY) session with an open panel, **When** the
  user clicks **X**, **Then** the panel closes, the tile remains, the registry record
  + live PTY persist, and clicking the tile reopens the panel; **When** the user
  clicks **Kill** and confirms, **Then** the PTY+worktree are reaped, the record is
  marked terminal/removed, and the tile is gone.
- **Tests:** `tests/test_run_lifecycle.py` — DOM assertions (X vs Kill are distinct
  controls; kill is confirm-gated) + a Playwright test (open panel → X → tile
  remains + reopen works; Kill → tile gone) + registry/PTY assertions (close keeps,
  kill reaps).

## Wave 2 — Past-session view: real summary + "Continue in a live session"

When a DONE/historical session's panel opens, replace the "session complete" note
with a **summary**: the **skill invoked**, the **prompts/turns asked**, and the
**actions/files produced**, built from the session's transcript/log + member docs
through the validated `summarizer` seam (extend `summarize_session` to capture
skill + prompt turns + actions; generate-twice + grounding filter; cached
generate-once). Add a **"Continue in a live session"** button that calls a new
`POST /api/rnd/continue_session` (token-authed) → `terminal_session.start_session`
in the same lane with `seed_context` = the prior session's summary/transcript, so the
new live session resumes the work. The original session is never mutated.

- **Done-when:** UI-verification set passes — a historical panel shows the summary
  (skill + prompts + actions, non-empty when data exists; honest when absent); the
  continue button starts a NEW live session seeded with the prior context, in the
  same lane, leaving the original intact.
- **G/W/T:** **Given** a done research session with a transcript, **When** its panel
  opens, **Then** the panel shows its skill + prompts + produced files (not just
  "complete"); **When** "Continue in a live session" is clicked, **Then** a new
  RUNNING session starts in the same lane whose seed contains the prior summary, and
  the original record is unchanged.
- **Tests:** `tests/test_session_continue.py` — summarizer extension (skill/prompts/
  actions captured, stubbed runner) + endpoint auth + seeded-continue (new session,
  original intact) + DOM/Playwright (panel shows summary + the continue button works).

## Wave 3 — Better project summaries (objective/purpose)

Improve `summarizer.summarize_project`: a stronger seed (CLAUDE.md / README /
Anchor.md + newest plan docs + pinned deliverables + per-lane activity) and a prompt
that yields a 1–2 sentence **objective/task/purpose** summary, grounding-filtered;
cache `.anchor/projects/<id>/project-summary.*` (generate-once on rescan; `force`
regenerates; a failed run never poisons the cache). The dashboard row
(`render_project_tile_html`) and project header READ the cache only (no synchronous
model run on render). Generation runs in the background on `rescan`.

- **Done-when:** `pytest` GREEN; `summarize_project` (through the stub runner)
  produces a non-empty objective-focused summary; the row + header render it from
  cache; an unsummarized project shows a graceful placeholder, never a synchronous
  model call on render.
- **G/W/T:** **Given** a project with CLAUDE.md + plan docs, **When**
  `summarize_project` runs through the stub runner, **Then** it returns a 1–2
  sentence objective summary that the row + header display; **and** the render path
  performs no model call (cache only).
- **Tests:** `tests/test_project_summary_v5.py` — seed includes the right sources;
  objective summary cached + grounded; render reads cache only; placeholder when
  uncached. (Render assertions; no Playwright needed unless markup changes — if the
  row/header markup changes, add the DOM + screenshot check.)

## Wave 4 — Deliverable per Foreman build (resolve · backfill · list)

Every Build (Foreman) session resolves a **deliverable**. Add
`deliverables.resolve_build_deliverable(folder, pid, build_session)` that resolves
the artifact a build produced from explicit signals (pinned path / `foreman.config`
`docs` / declared `Anchor.md` marker / known build output); **backfill** by scanning
existing build sessions per project. List resolved deliverables in the **Deliverables
lane** AND render the deliverable **inside each Build session's panel**. When a build
has no resolvable deliverable, show an honest "no deliverable pinned yet — pin one"
(never fabricate). Auto-pin on build completion where the signal is unambiguous.

- **Done-when:** UI-verification set passes — a project with a build session shows
  that build's deliverable in BOTH the Deliverables lane and the build's panel; a
  build with no resolvable deliverable shows the honest placeholder; backfill finds
  deliverables for existing builds; nothing fabricated.
- **G/W/T:** **Given** a project with a completed build that produced an artifact,
  **When** the project window renders and the build panel opens, **Then** the
  deliverable appears in the Deliverables lane AND in the build panel; **Given** a
  build with no resolvable artifact, **Then** both show the honest "none yet"
  placeholder.
- **Tests:** `tests/test_build_deliverable.py` — `resolve_build_deliverable` (each
  signal; ambiguous → unresolved, not fabricated) + backfill + DOM/Playwright (lane
  lists it; build panel shows it; honest placeholder when absent).

## Wave 5 — Grass Catcher: B+C hybrid idea workbench

Rebuild the Grass lane to the approved mockup (`_mockups/grass_catcher_refined.html`):
a **filter-tab row** (All / raw / refined / promoted + a **search** box) over a
**two-pane workbench** — idea list left (filtered), the selected idea's workbench
right (idea text + **Develop: Research / Plan** in the workbench terminal + engine
toggle + **Promote to a lane**). Extend `effort_history` grass: stable idea ids
(`grass-<hash>`), a **status** (raw→refined→promoted), **versioned refinements**
(`grass-<id>/dev-N`) logged + **pullable into other efforts**, and a **promote link**
(a promoted idea links to the run it became). Developing opens a **seeded live
session in the workbench terminal** (reuses `start_session` with `seed_context` = the
idea + its refinements); the refined output is saved back as a new version.
Endpoints (token-authed) for develop / save-refinement / set-status / promote / pull.
Project-scoped.

- **Done-when:** UI-verification set passes — the Grass view renders the filter tabs
  + two-pane workbench per the mockup; filtering by status works; selecting an idea
  loads its workbench; "Develop with Research/Plan" starts a seeded session in the
  workbench terminal; a refinement is saved with a version id and is pullable; a
  promoted idea links to its run; search filters the list.
- **G/W/T:** **Given** several ideas of mixed status, **When** the Grass view
  renders, **Then** the filter tabs scope the left list and selecting an idea loads
  its right workbench; **When** "Develop with Research" is clicked, **Then** a seeded
  live session starts in the workbench terminal and a saved refinement appears in the
  history with a `grass-<id>/dev-N` id pullable into a lane.
- **Tests:** `tests/test_grass_workbench.py` — DOM assertions (filter tabs + 2-pane +
  workbench terminal + history, old single-column grass markup absent) + Playwright
  (filter → select → develop → refinement-saved → pull) + backend (status
  transitions, versioned refinements, promote-link, develop seeds a session).

## Wave 6 — CLI mirror + healthcheck v5 + distro scan + docs (PROJECT DONE)

Mirror the new read/data seams into `anchor.py` (`rnd session-summary <pid> --lane
--session`, `rnd grass <pid>` [list ideas + status], `rnd build-deliverable <pid>
--session`). Extend `anchor_healthcheck.py` with `check_rnd_v5_surface` (fully
stubbed): walk close-to-tile vs kill (registry), session summary + continue (seeded),
project summary, build-deliverable resolve/backfill, and grass develop/refine/promote
— tear everything down, never `:8777`. Confirm `distro` import scan stays clean
(Playwright must NOT appear in product code). Update `CLAUDE.md` (a v5 "Durable Work"
section + API table rows + CLI subcommands; note Playwright is a dev-only test dep
and that UI waves are gated by Playwright + screenshot + sign-off).

- **Done-when:** the **full** suite GREEN; the new CLI subcommands work against the
  live registry; `check_rnd_v5_surface` passes fully stubbed + tears down (no
  `:8777`, no orphan PTY/worktree/preview); `python -m distro` scan clean; CLAUDE.md
  documents v5.
- **G/W/T:** **Given** the stubbed env, **When** `check_rnd_v5_surface` runs, **Then**
  it walks the full v5 surface and tears down with no orphan and never binds `:8777`;
  **and** the distro scan reports only the declared `pywinpty` exception (no
  Playwright in product code).
- **Tests:** `tests/test_cli_v5.py`, `tests/test_healthcheck_v5.py`,
  `tests/test_distro_scan_v5.py` (CLI subcommands; stubbed surface walk + teardown;
  import scan clean) — and the whole suite GREEN.

## Project DONE

DONE = Wave 6 GREEN on `python -m pytest -v` AND the plan-level acceptance gate
(Master Plan "Definition of done") met — including the UI waves' Playwright +
screenshot + user sign-off. Terminal wave = Wave 6.
