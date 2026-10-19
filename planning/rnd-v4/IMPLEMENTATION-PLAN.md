# Anchor R&D Surface v4 — "Project Cockpit" — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, locked 2026-06-12. Frozen design: `MASTER-PLAN.md`
> (this folder) + the mockups `_mockups/project_window_proposals.html` (Paradigm 2)
> and `_mockups/branding_proposals.html` (Option B). Build cwd = repo root
> `C:\dev\Anchor`. Each wave ends GREEN on the ground-truth gate and adds/extends
> tests under `tests/`.

test-command: python -m pytest -v

## Conventions (read before any wave)

- **Active Anchor project id:** read it from `rnd_registry.json` at build time
  (the live "Anchor" project); do not hard-code.
- **No live `claude`/`gemini`/real-PTY in the gate.** Model interactions go
  through `tests/fake_claude.py` via `ANCHOR_RUNNER_CMD`; PTY interactions go
  through the **stub PTY backend** (`ANCHOR_PTY_BACKEND=stub`). Real `pywinpty` is
  runtime-only, never in pytest.
- **pywinpty is the ONLY permitted native dependency**, lazily imported in
  `pty_manager.py` only. No wave may add another native/third-party import;
  `distro.py`'s import scan stays green (Wave 9 asserts it).
- **f-string discipline** in `anchor_gui.py`: double literal braces in generated
  CSS/JS; `_PROJECT_WINDOW_JS` stays a RAW single-brace string.
- **Security:** every new mutating / terminal / launch / preview endpoint sits
  behind the existing `do_POST` token-auth gate; GET stays read-only (token via
  `?token=`). Any spawned server/preview uses an OS-assigned port HARD-guarded
  `!= 8777`, isolated temp `ANCHOR_DATA_DIR`, loopback bind.
- **Reuse, don't fork:** build on v3's `terminal_session.py`, `pty_manager.py`,
  `session_registry.py`, `worktrees.py`, `summarizer.py`, `deliverables.py`,
  `preview_server.py`, `handoff.py`, `report_viewer.py`, `job_runner.py`,
  `effort_history.py`, `vendor/xterm`, `vendor/brand`.
- **Mirror** new backend data functions into `anchor.py` where natural (Wave 9
  sweeps any remainder). **Each wave that changes HTML adds string-level render
  assertions** (the existing `tests/test_project_window.py` /
  `tests/test_tile_render.py` style), since there is no browser in the gate.

## Wave 1 — One terminal substrate: skill auto-load-once + greet-once (GATES THE UX)

Kill the repeating-prompt bug at the root. Make `terminal_session.start_session`
seed **exactly one** opening stdin turn that loads the lane's skill
(Research→researchPrime · Planning→Crucible · Build→Foreman) and asks the model to
greet once and wait. Record `seeded=True` + `seed_text` on the session so the seed
is **never re-sent**. Unwire the v2 stream-json REPL (`rnd_terminal.py`) from the
project window's terminal path (the module remains on disk, simply unused by the
cockpit). Add a per-lane seed-prompt map (overridable via env for tests).

- **Done-when:** `pytest` GREEN; the stub backend shows the lane skill-seed written
  once on session start and absent on every subsequent `read_since`; the project
  window terminal path resolves to `terminal_session`/`pty_manager` only (no
  `rnd_terminal` call in the cockpit wiring).
- **G/W/T:** **Given** the stub PTY backend and a new Planning session, **When**
  `start_session` runs and the client reads output repeatedly, **Then** the Crucible
  seed turn appears exactly once, `record.seeded` is `True`, and no further seed is
  emitted; **and** killing the session reaps the PTY + worktree with no orphan.
- **Tests:** `tests/test_terminal_seed.py` (seed-once per lane; no re-seed across N
  reads; seeded flag persisted; lane→skill map correct; cockpit uses only the
  ConPTY substrate).

## Wave 2 — Engine persistence + toggle (relaunch on the other engine)

Store the chosen engine (`claude`|`gemini`) on the session record (already a
`backend` field in `session_registry`). New sessions **default to the project's
last-used engine** (helper `last_engine_for_project(pid)`). Add
`terminal_session.switch_engine(session_id, engine)` that reaps the current PTY and
re-`start_session`s on the other engine, preserving lane + worktree + label,
updating the registry (rollback on failure). Expose `POST /api/rnd/term_set_engine`
(token-authed). Persist a per-project `last_engine` (in `.anchor/projects/<id>/`).

- **Done-when:** `pytest` GREEN; a new session inherits the project's last-used
  engine; `switch_engine` swaps backend with no orphan PTY/worktree and the registry
  reflects the new backend.
- **G/W/T:** **Given** a running session on `claude`, **When** `switch_engine(...,
  'gemini')` runs, **Then** the old PTY is reaped, a new stub PTY starts in the same
  worktree, `record.backend == 'gemini'`, and `last_engine_for_project` returns
  `gemini`; **and** a failed relaunch rolls back to the prior record.
- **Tests:** `tests/test_engine_persist.py` (default-from-last; switch swaps +
  re-registers; no orphan; rollback on failure; endpoint token-gated).

## Wave 3 — Per-lane doc roles + cost/tokens/time rollup (data layer)

Add the data the cockpit renders. (a) `summarizer`/`effort_history`: a
`session_doc_roles(pid, lane, session_id) -> {role: {label, href}}` resolving the
locked role sets (research: exec/report/agent/provenance; planning:
master/impl/northstar; build: northstar/deliverable/exec-log/plan), each link via
the existing `/report` / `/artifact` routes; missing roles omitted (never faked).
(b) `effort_history.project_effort_rollup(pid, window='lifetime'|'30d') -> {tokens,
cost_usd, wall_clock_ms, sessions}` summing `job_runner` cost records for
**RUN-provenance** sessions only (imported/discovered contribute 0).

- **Done-when:** `pytest` GREEN; doc-roles resolve the right links per lane and omit
  absent ones; the rollup sums only run sessions and supports lifetime + 30-day
  windows; imported/discovered add nothing.
- **G/W/T:** **Given** a project with run + imported sessions and cost records,
  **When** `project_effort_rollup(pid,'lifetime')` runs, **Then** it returns summed
  tokens/cost/time + run-session count, excluding imported/discovered; **and**
  `'30d'` excludes records older than 30 days (clock injected for determinism).
- **Tests:** `tests/test_doc_roles.py`, `tests/test_effort_rollup.py`
  (lifetime vs 30d; run-only; zero when no run metrics; per-lane role resolution).

## Wave 4 — Paradigm 2 project window: lane tiles + lights + inline expanding panels

Re-lay-out `render_project_window_html` to the locked Paradigm 2. Each lane
(Research/Planning/Build/Deliverables/Grass) shows its most-recent session as a
**tile with a status light** (green/amber/red/grey from `session_registry` status
→ color map). Clicking a content tile **expands a full-width inline panel** appended
to a panel stack below the board (no page navigation); a second click / minimize
collapses it back to the tile (session keeps running); an **X kills behind an
"Are you sure?" confirm**. Rewrite the project-window JS (replacing the v3 floating
window-manager block) into an **accordion panel manager** (`openPanel`,
`minimizePanel`, `killPanel`, `repopulate` from `/api/rnd/term_sessions`). Keep all
terminal endpoints unchanged.

- **Done-when:** `pytest` GREEN; the rendered window contains lane tiles each with a
  status-light element and a panel-stack container; the JS exposes the accordion
  panel-manager contract; no floating-window markup remains in the cockpit.
- **G/W/T:** **Given** a project with sessions in three lanes, **When**
  `render_project_window_html` runs, **Then** each lane tile carries the correct
  light class for its session status and a click-to-expand hook targeting the inline
  panel stack; **and** the kill control is gated by a confirm.
- **Tests:** `tests/test_cockpit_render.py` (tile + light per status; panel-stack
  present; accordion JS symbols present; kill-confirm present; no `.termwin`
  floating-window class).

## Wave 5 — Panel internals: stacked summary (equal-height split) + resizable terminal

Fill an expanded panel: **summary on top, full-width terminal below**. The summary
is a two-column split — **materials left** (goal · North-Star · what-was-asked ·
effort), **role-tagged links right** (Wave 3) — with CSS that makes **both columns
fill equal vertical height** (left effort line sinks to bottom; right's second
link-group pins to bottom). Mount xterm.js in the panel's terminal host reusing the
v3 transport (`term_ws` → `term_stream2` fallback, `term_input2`/`term_resize`).
The terminal pane is **vertically resizable** (drag bottom edge; persists size in
the panel). Wire the per-project rollup + path into the project-window header.

- **Done-when:** `pytest` GREEN; an expanded panel renders the split summary (both
  columns present, equal-height CSS classes), the role-tagged links from Wave 3, a
  resizable terminal host bound to the existing transport, and the header shows path
  + rollup.
- **G/W/T:** **Given** an expanded Planning panel, **When** it renders, **Then** the
  summary materials sit above a full-width terminal host, the right column shows
  MASTER/IMPL/North-Star links, the terminal host carries the resize affordance, and
  the panel header shows `Σ tokens · $ · time`.
- **Tests:** `tests/test_panel_render.py` (split + equal-height classes; role links
  present; resizable terminal host; header rollup + path).

## Wave 6 — Grass Catcher idea board + promote-to-lane

Render the Grass lane as an **idea board**: idea cards (from
`effort_history` grass + INBOX promotions + discovered idea-docs), each with **→
Research** and **→ Plan** actions. Add `effort_history.promote_grass_to_lane(pid,
idea_id, lane)` that creates a new session launch in that lane **seeded with the
idea text** (reusing the Wave 1 seed path). Expose `POST
/api/rnd/promote_grass` (token-authed). Clicking an action opens the new session in
an inline panel.

- **Done-when:** `pytest` GREEN; the grass lane renders idea cards with →Research /
  →Plan actions; `promote_grass_to_lane` starts a seeded session in the target lane;
  the endpoint is token-gated.
- **G/W/T:** **Given** a grass idea, **When** `promote_grass_to_lane(pid, idea,
  'research')` runs (stub backend), **Then** a new Research session starts seeded
  with the idea text and is registered RUNNING; **and** the idea remains in grass
  (promotion copies, never destroys).
- **Tests:** `tests/test_grass_board.py` (idea-card render; promote→seeded session;
  copy-not-move; endpoint auth).

## Wave 7 — Deliverable launch-by-type

Extend `deliverables.py` with type-aware launch. Detect/declare type ∈
{`skill`,`tool`,`service`,`program`,`doc`} and implement `launch_deliverable(pid,
deliverable_id)`: **skill/tool → verify status** (available/loaded, no spawn);
**service → launch into a window or pull up the running one** (persistent variant of
`preview_server`: free port ≠ 8777, isolated temp data dir, loopback, health-check,
reconcile via `previews.json`); **program → run in a window** (run-to-result on a
free port / captured output); **doc → open rendered** (existing `report_viewer`).
Expose `POST /api/rnd/launch_deliverable` (token-authed) + the UI on the deliverable
tile. service/program **health-check before returning the window URL**.

- **Done-when:** `pytest` GREEN; each type launches per its contract; skill/tool
  return availability without spawning; service/program bind a free port `!= 8777`
  with an isolated data dir and health-check; doc resolves a rendered view; nothing
  touches `:8777` or real data.
- **G/W/T:** **Given** a pinned `service` deliverable, **When**
  `launch_deliverable(...)` runs, **Then** it starts on an OS-assigned port asserted
  `!= 8777` in an isolated temp data dir, health-checks, returns the URL, and a
  second launch **pulls up the running one** instead of double-spawning; **Given** a
  `skill` deliverable, **Then** launch returns `{available|loaded}` with no process.
- **Tests:** `tests/test_deliverable_launch.py` (per-type contract; never-8777 guard
  with injected port; pull-up-if-running; skill/tool no-spawn; endpoint auth).

## Wave 8 — Main-dashboard rows (drop directory) + masthead rollup + Option B branding

`render_projects_view_html` / `_render_folder_groups`: render a **flat one-line row
list** (no per-folder path header); the path moves to the project-window header
(Wave 5). Each row gains the **cost/tokens/time rollup** (Wave 3) with a
**lifetime/30-day toggle**. Add **Option B branding** to the main dashboard masthead
in `generate_html()`: "Anchor" title · vertical divider · GWL mark + wordmark off to
the side · "Powered by NextGen Nuclear ☢" pill far right (reuse
`/vendor/brand/gwl-m-icon.svg`; keep the existing favicon route).

- **Done-when:** `pytest` GREEN; project rows render one line with **no directory
  text** and a rollup + window toggle; the masthead renders the Option B lockup with
  the brand mark; the page still has exactly one GWL mark source (the vendored svg).
- **G/W/T:** **Given** three projects each in their own folder, **When** the R&D view
  renders, **Then** there is no folder-path header line and each row shows
  `Σ tokens · $ · time`; **and** the dashboard masthead shows the Anchor title beside
  the GWL lockup + NextGen Nuclear ☢ pill.
- **Tests:** `tests/test_dashboard_rows.py` (no path line; per-row rollup + toggle;
  Option B masthead markup; single brand-mark source).

## Wave 9 — CLI mirror + healthcheck v4 surface + distro scan + docs (PROJECT DONE)

Mirror the new read/data seams into `anchor.py` (`rnd rollup <pid> [--window
lifetime|30d]`, `rnd doc-roles <pid> --lane <lane> --session <id>`, `rnd
deliverable-type <pid> <id>`, `rnd engine <pid>` showing last-used). Extend
`anchor_healthcheck.py` with `check_rnd_v4_surface`: fully stubbed
(`ANCHOR_PTY_BACKEND=stub`, `ANCHOR_RUNNER_CMD`→`fake_claude.py`, temp
`ANCHOR_DATA_DIR`/`ANCHOR_WORKTREE_BASE`, never `:8777`) — walk seed-once, engine
switch, doc-roles, rollup, grass promote, and a type-aware deliverable launch on a
guaranteed-free port; tear everything down. Confirm `distro.py`'s import scan still
passes (no new native/third-party import). Update `CLAUDE.md` (module list, API
table, a v4 "Project Cockpit" section; note the v2 REPL is unwired from the
cockpit).

- **Done-when:** the **full** `pytest` suite is GREEN; the new CLI subcommands work
  against the live registry; `check_rnd_v4_surface` passes fully stubbed and tears
  down (no `:8777`, no real data); `python -m distro` (import scan) passes;
  `CLAUDE.md` documents v4.
- **G/W/T:** **Given** the stubbed env, **When** `check_rnd_v4_surface` runs, **Then**
  it walks the full v4 surface and tears down with no orphan PTY/worktree/preview and
  never binds `:8777`; **and** `distro.py`'s scan reports only the declared pywinpty
  exception.
- **Tests:** `tests/test_cli_v4.py`, `tests/test_healthcheck_v4.py`,
  `tests/test_distro_scan_v4.py` (CLI subcommands; stubbed surface walk + teardown;
  import scan still clean) — and the whole suite GREEN.

## Project DONE

DONE = Wave 9 GREEN on `python -m pytest -v` AND the plan-level acceptance gate
(Master Plan "Definition of done") met. Terminal wave = Wave 9.
