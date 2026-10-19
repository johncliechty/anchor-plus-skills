# Anchor R&D Surface v6 — "Linked Pipeline" — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, locked 2026-06-14. Frozen design: `MASTER-PLAN.md` (this
> folder) + the approved interaction mockup `_mockups/rnd-v6/session_pipeline.html`.
> Build cwd = repo root `C:\dev\Anchor`, branch `foreman/rnd-surface-v6` (off master;
> the summarizer parse fix `1bd8b85` is already cherry-picked as the branch base).
> Each wave ends GREEN on the ground-truth gate and adds/extends tests under `tests/`.

test-command: python -m pytest -v

## Conventions (read before any wave)

- **Active Anchor project id:** read from `rnd_registry.json` at build time; never
  hard-code (`2fe37f39…` is retired; the live Anchor is the active one).
- **No live `claude`/`gemini`/real-PTY in the gate.** Model calls via
  `tests/fake_claude.py` / `tests/stub_streamjson.py` through `ANCHOR_RUNNER_CMD`;
  PTY via the stub backend (`ANCHOR_PTY_BACKEND=stub`). Never `:8777` or real data;
  any spawned preview/service on an OS-assigned port HARD-guarded `!= 8777` + isolated
  temp `ANCHOR_DATA_DIR`.
- **pywinpty** is the only native dep (lazy, `pty_manager.py` only). **Playwright is a
  DEV-ONLY test dep** — `pytest.importorskip("playwright.sync_api")`; NEVER in product
  code; `distro.py`'s scan must stay green (Wave 8 asserts it).
- **f-string discipline** in `anchor_gui.py`: `_PROJECT_WINDOW_JS` is a RAW
  single-brace string; double literal braces in f-string HTML/CSS.
- **Security:** every new mutating / terminal / advance endpoint behind the existing
  `do_POST` token gate; GET read-only (token via `?token=`).
- **Reuse, don't fork:** build on `terminal_session.py`, `session_registry.py`,
  `worktrees.py`, `handoff.py`, `summarizer.py`, `effort_history.py`, `job_runner.py`,
  `pty_manager.py`, `report_viewer.py`, `vendor/xterm`.
- **Scoped commits only** — never the runtime-data churn (`dashboard.html`,
  `PROJECTS.md`, `DASHBOARD.md`, `domains/*`, `INBOX.md`, `.anchor/`, `rnd_jobs/`,
  `rnd_registry.json`, `logs/`). Commit only the code/test files each wave touched.
- **Baseline before Wave 1:** the v5 merge baseline was **643 passed, 1 skipped**;
  the cherry-picked summarizer fix adds `tests/test_summary_streamjson.py`
  (+ stub). Re-establish the live count at Wave 1 start; each wave must hold or grow it.
- **UI VERIFICATION IS MANDATORY (the v4 lesson — non-negotiable)** for every wave
  that changes rendered UI (Waves 3, 4, 5, 6, 7). "GREEN" requires ALL of: (a)
  **rendered-DOM assertions** — parse the served HTML (style/script stripped) with
  `html.parser`, assert the new structure present AND the replaced/old structure
  absent (positive + negative); (b) a **real Playwright + Chromium interaction test**
  (boot a throwaway `gui.make_server('127.0.0.1',0)`, click the actual control, assert
  the resulting DOM + no JS console errors) — model on `tests/test_cockpit_paradigm2.py`
  / `tests/test_run_lifecycle.py`; (c) the **orchestrator captures a screenshot**
  (PNG under `_devtest/`), **Reads it**, and checks it against the rnd-v6 mockup; (d)
  **user sign-off before merge**. A string-grep-only test is an automatic wave HALT.

---

## Wave 1 — Summaries that actually work (backend; lands the prod fix + content + heal)

The parse fix (`1bd8b85`) is already the branch base. This wave makes summaries
genuinely *informative* and *regression-proof*, and heals stale caches. Verify
`summarizer.summarize_session` and `summarize_project` produce grounded, non-empty
content when driven through a **stream-json-shaped** stub (`tests/stub_streamjson.py`),
not bare lines. Strengthen the **session** summary to convey skill · prompts/turns ·
actions/files and the **project** summary to convey objective/purpose (stronger seed:
CLAUDE.md/README/Anchor.md + newest plan docs + pinned deliverables + per-lane
activity). Keep generate-twice + grounding filter (honest "no grounded …" only when
truly absent; never fabricated). Ensure pre-fix caches (`SUMMARY_SCHEMA_VERSION` older/
missing) are treated as a MISS and **regenerate on rescan/force**. Add a small
`rescan`-path helper (or confirm the existing background `summarize_project` on
`rescan`) so existing empty project caches heal without manual force.

- **Done-when:** `pytest` GREEN; through the stream-json stub, a session summary is
  non-empty and carries skill/prompts/actions, and a project summary is a grounded
  1–2 sentence objective; an ungrounded claim is dropped; a `SCHEMA_VERSION`-stale
  empty cache is regenerated on rescan; bare-line stub back-compat still parses.
- **G/W/T:** **Given** a session/project whose runner emits `claude --output-format
  stream-json` envelopes, **When** the summarizer runs through the stub, **Then** it
  extracts the real text and caches a grounded, non-empty, informative summary;
  **Given** a pre-fix empty `project-summary.json` (old/again missing schema version),
  **When** the project is rescanned, **Then** the cache is treated as a miss and
  regenerated (no longer "No grounded objective").
- **Tests:** extend `tests/test_summary_streamjson.py`; add
  `tests/test_summary_content_v6.py` (session skill/prompts/actions shape; project
  objective shape; grounding drops a hallucinated claim; schema-version heal on
  rescan). Backend only — no Playwright unless markup changes.

## Wave 2 — Session linkage backbone (backend; the durable chain)

Give sessions a durable lineage. Add `parent_session_id` (str|"") and `chain_id` (str)
to the `session_registry` record (`_normalize` defaults + `register_session` params +
`update_session` allow-list); a new session with no parent **starts its own chain**
(`chain_id = session_id`), a child **inherits its parent's `chain_id`**. Add
`session_registry.chain_for(session_id)` / `chain_members(chain_id)` (ordered
research→plan→build by lane then created_at) and a `terminal_session.start_session(...,
parent_session_id=None)` passthrough that sets both fields. Extend `handoff.py` to
record a **generic stage edge** (not just plan→build): a `record_stage_link(folder,
pid, from_session, to_session, kind)` appended to `discovery.json` (rescan-durable via
`anchor_marker` merge, like existing handoffs), and have `discover_recent_plan_set`
honor an explicit `source_session_id` already (it does). No UI in this wave.

- **Done-when:** `pytest` GREEN; a child session created with `parent_session_id`
  inherits the parent's `chain_id`; `chain_members` returns the ordered chain; the
  stage edge is persisted and **survives a registry reload + a rescan**; existing
  records (no new fields) normalize with empty parent / self `chain_id` (back-compat).
- **G/W/T:** **Given** a research session R, **When** a planning session P is started
  with `parent_session_id=R`, **Then** P.chain_id == R.chain_id and
  `chain_members(R.chain_id) == [R, P]` ordered; **When** the registry is reloaded and
  the project rescanned, **Then** the R→P edge and chain still resolve.
- **Tests:** `tests/test_session_chain.py` — field defaults/back-compat; chain
  inherit + ordering; `chain_for`/`chain_members`; stage-edge persistence across
  reload + rescan; `start_session(parent_session_id=…)` through the stub PTY.

## Wave 3 — First-class session windows: maximize + free resize (UI)

In `_PROJECT_WINDOW_JS` + the panel CSS: add a **maximize** control (▢) to each panel
header that toggles the panel to fill the cockpit viewport (`.panel.maxd`) and back,
and make the panel **freely resizable** (drag any edge/corner — not just the terminal
sub-pane), persisting size per session (extend `_panelHeights` → `_panelRects`).
Keep the v5 minimize, close-to-tile, and hard-kill exactly as they are; layout stays
the **stacked** column. Maximize/restore and resize MUST re-fit the xterm terminal
(reuse the v4.1 fit + ResizeObserver) with no freeze and correct cols/rows.

- **Done-when:** UI-verification set passes — every session panel has working
  minimize / **maximize (toggle)** / **free resize** / close / kill; maximizing fills
  the viewport and restores; resizing re-fits the terminal (correct cols/rows, no
  freeze); the old "terminal-pane-only vertical resize" is no longer the only resize.
- **G/W/T:** **Given** an open session panel, **When** the user clicks maximize,
  **Then** the panel fills the cockpit and the terminal re-fits; **When** clicked
  again, **Then** it restores to its prior rect; **When** the user drags the panel's
  corner, **Then** the panel resizes and the terminal re-fits with no console error.
- **Tests:** `tests/test_window_controls_v6.py` — DOM (maximize control present on
  panels; resize affordance present; positive+negative vs the v5 header) + Playwright
  (open panel → maximize → assert maxd geometry + terminal fit → restore → resize
  drag → assert new size, no JS console errors) + screenshot vs mockup Step 2.

## Wave 4 — Tile lifecycle: new-session=new-tile + keep finished (newest-prominent) (UI)

Two fixes. (a) **Every start mints a tile:** audit every session-start front-end path
(`newTermSession`, `continueSession`, `promoteGrass`, `developGrass`, and the new
advance paths) so each appends a distinct tile to the tiles row — none reuse/replace.
(b) **Keep finished tiles, newest-prominent:** stop excluding terminal-status sessions
from the tiles row (`repopulate`/`renderSessionBar` + the server `term_sessions`
projection) so done/failed sessions remain as **greyed, reopenable** tiles; per
lane/chain render the **most-recent** session as the prominent tile and collapse older
finished ones under a **"previously done"** group/expander. Reopening a finished tile
shows its summary panel (Wave 1); closing keeps the tile (v5); only hard-kill removes
it.

- **Done-when:** UI-verification set passes — starting any kind of session adds a new
  tile; finishing a session keeps its tile (greyed) in the row without a reload; per
  lane the newest is prominent and older finished ones are under "previously done";
  reopening a finished tile opens its summary; kill removes the tile.
- **G/W/T:** **Given** the tiles row, **When** the user starts a second research
  session, **Then** a second distinct research tile appears (the first is not
  replaced); **When** a session finishes, **Then** its tile remains (greyed) and, if a
  newer one exists in its lane, moves under "previously done"; **When** a finished tile
  is clicked, **Then** its summary panel opens.
- **Tests:** `tests/test_tile_lifecycle_v6.py` — DOM (multiple same-lane tiles;
  finished tile present + "previously done" group; positive+negative) + Playwright
  (start two sessions → two tiles; finish one → still present + grouped; reopen →
  summary) + backend (term_sessions projection now includes terminal sessions, still
  SAFE — no worktree_path/branch).

## Wave 5 — Manual advance research→planning + chain breadcrumb (UI + endpoint)

Add an **"Advance to Planning →"** control to a research session's window (shown when
the session looks done / on demand). It calls a new **`POST /api/rnd/advance_session`**
(token-authed) → `terminal_session.start_session(lane='planning',
parent_session_id=<research>, seed_context=<research summary/report>)`, creating a NEW
linked planning tile seeded from the research; the research record is never mutated
(reuses the v5 continue-seed builder). Render a **chain breadcrumb** (`R-1 → P-2 → …`)
in each session window header (and as a small affordance on the tile) from
`chain_members`; clicking a breadcrumb node opens that session's panel. (This wave
establishes the generic advance endpoint that Wave 6 reuses for the auto path.)

- **Done-when:** UI-verification set passes — a research window shows "Advance to
  Planning →"; clicking it opens a new planning tile in the same chain, seeded from the
  research, original intact; every linked session shows the chain breadcrumb and
  clicking a node navigates the chain.
- **G/W/T:** **Given** a research session with a grounded summary, **When** the user
  clicks "Advance to Planning →", **Then** a new RUNNING planning session starts in the
  same `chain_id` with `parent_session_id` = the research and a seed containing the
  research context, and the research record is unchanged; **When** the user clicks the
  breadcrumb's research node from the planning window, **Then** the research panel opens.
- **Tests:** `tests/test_advance_research_to_plan.py` — endpoint auth + seeded-linked
  start (new session, original intact, chain set) + DOM (advance control on research
  only; breadcrumb present) + Playwright (click advance → new planning tile + seed;
  click breadcrumb → navigates) + screenshot vs mockup Step 3.

## Wave 6 — Auto advance planning→build (gated on a real plan) (backend + UI)

When a **planning** session reaches a terminal/**DONE** state — the deliberate
**hard-kill** ("done with planning") or **reconcile-dead**, NOT a keep-alive close —
the server checks `handoff.discover_recent_plan_set(folder, pid,
source_session_id=<planning session>)`. If a **MASTER+IMPL plan set** is found, it
**automatically** starts a NEW linked **build** session (`start_session(lane='build',
parent_session_id=<planning>, …)`), **primes** its worktree via
`handoff.prime_worktree` (HANDOFF.md → the plan docs) **before the planning worktree
is reaped** (so the plan docs survive), and **records the stage edge** (Wave 2) —
exactly one build per planning session (**idempotent** on `parent_session_id`, so
reconcile/restart never duplicates). If **no** plan set is found, **no** advance. The
new build tile appears in the row (Wave 4), clearly attributed, even when the planning
session had no upstream research. Surface a tiny "→ auto-opened Build B-n from this
plan" note. The trigger is the kill/reconcile-dead transition the cockpit already
owns — never process self-exit, never a keep-alive close.

- **Done-when:** UI-verification set passes — finishing a planning session that
  produced a plan set auto-opens exactly one linked, primed build tile; a planning
  session with no plan set opens none; the build is linked into the chain and survives
  reconcile/restart without duplication; works with no upstream research.
- **G/W/T:** **Given** a planning session whose worktree contains a MASTER+IMPL plan
  set, **When** it is hard-killed / found reconcile-dead (DONE transition), **Then**
  the cockpit opens one build session with `parent_session_id` = the planning session,
  a primed HANDOFF.md (referencing the real plan docs, captured before reap), and a
  recorded stage edge; **Given** a planning session with no plan set, **When** it
  finishes, **Then** no build is opened; **When** reconcile runs again, **Then** no
  duplicate build is created; **When** a planning panel is keep-alive **closed**,
  **Then** no build is opened (still live).
- **Tests:** `tests/test_auto_advance_plan_to_build.py` — terminal-transition trigger
  (stub PTY, temp git project with/without a plan set) → exactly-one primed linked
  build; idempotency across a second reconcile; no-plan ⇒ no-advance; no upstream
  research path + DOM/Playwright (finishing a planning panel surfaces the new build
  tile + note).

## Wave 7 — Main dashboard reflects project activity (UI)

Upgrade the home-dashboard R&D project rows (`render_project_tile_html` / the rows
re-rendered by `GET /api/rnd/projects_html`) from a bare status dot to a **timely
reflection**: per project show running-session presence/count, the **latest grounded
project summary** (objective, from Wave 1's cache), and a **"what's happening" line**
(most-recent lane activity / newest session title / its status). **Read caches only**
on render (no synchronous model call); generation stays the background-on-`rescan`
path, and the existing `projects_html` in-place refresh updates the rows when a new
summary lands. Honest placeholders when a project has no activity/summary yet.

- **Done-when:** UI-verification set passes — each R&D project row shows its running
  count + latest objective summary + a recent-activity line, sourced from cache; a
  project mid-run shows it's active with its newest session; render performs no model
  call; rows refresh in place after a background summarize.
- **G/W/T:** **Given** a project with a running session and a cached objective summary,
  **When** the home dashboard renders, **Then** the row shows the objective + a
  "running: N · latest: <session>" reflection (cache only, no model call); **Given** a
  background `summarize_project` completes, **When** `projects_html` re-renders, **Then**
  the row updates in place.
- **Tests:** `tests/test_dashboard_reflection_v6.py` — DOM (row shows objective +
  activity line; positive+negative vs the v5 dot-only row) + render-path asserts no
  model call (cache only) + Playwright (row reflects a running stub session; in-place
  refresh) + screenshot.

## Wave 8 — CLI mirror + healthcheck v6 + distro scan + docs (PROJECT DONE)

Mirror the new **read** seams into `anchor.py`: `rnd chain <pid> --session <id>`
(ordered chain members via `chain_members`), and ensure `rnd session-summary` /
`rnd build-deliverable` reflect the Wave 1 content. Extend `anchor_healthcheck.py`
with **`check_rnd_v6_surface`** (fully stubbed: stub PTY + stream-json stub runner +
temp `ANCHOR_WORKTREE_BASE` + temp git project): walk (1) a summarizer round-trip
through the stream-json stub yields grounded non-empty session + project summaries +
schema-heal; (2) a chain — start research → advance to planning (linked) → finish
planning-with-plan → exactly-one auto build, asserting `chain_members`; (3) the
tiles/term_sessions projection includes terminal sessions and stays SAFE; tear
everything down (no `:8777`, no orphan PTY/worktree). Confirm `python -m distro` import
scan stays clean (Playwright NOT in product code). Update `CLAUDE.md` (a v6 "Linked
Pipeline" section + new API rows: `advance_session`; CLI `rnd chain`; the new registry
fields + handoff stage edge; note Playwright is dev-only and UI waves are
Playwright+screenshot+sign-off gated).

- **Done-when:** the **full** suite GREEN; the new CLI subcommand works against the
  live registry; `check_rnd_v6_surface` passes fully stubbed + tears down (no `:8777`,
  no orphan PTY/worktree); `python -m distro` scan clean; `CLAUDE.md` documents v6.
- **G/W/T:** **Given** the stubbed env, **When** `check_rnd_v6_surface` runs, **Then**
  it walks summaries + the research→plan→build chain (incl. auto-advance + idempotency)
  and tears down with no orphan and never binds `:8777`; **and** the distro scan
  reports only the declared `pywinpty` exception (no Playwright in product code).
- **Tests:** `tests/test_cli_v6.py`, `tests/test_healthcheck_v6.py`,
  `tests/test_distro_scan_v6.py` — and the whole suite GREEN.

## Project DONE

DONE = Wave 8 GREEN on `python -m pytest -v` AND the Master Plan "Definition of done"
met — including the UI waves' (3–7) Playwright + screenshot + **John's sign-off**.
Terminal wave = Wave 8. **No merge to master and no `nssm restart anchor` until John
signs off** (then: merge, `nssm restart anchor` elevated, rescan each project to heal
summaries).
