# Anchor R&D Surface v3 — "Mission Control" — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, approved 2026-06-11. Frozen design: `MASTER-PLAN.md`
> (this folder). Build cwd = repo root `C:\dev\Anchor`. Each wave ends GREEN on
> the ground-truth gate and adds/extends tests under `tests/`.

test-command: python -m pytest -v

## Conventions (read before any wave)

- **Active Anchor project id:** read it from `rnd_registry.json` at build time
  (the live "Anchor" project; do not hard-code — it may differ).
- **No live `claude`/`gemini`/real-PTY in the gate.** Model interactions go
  through `tests/fake_claude.py` via `ANCHOR_RUNNER_CMD`; PTY interactions go
  through a **stub PTY backend** selected by an env override (e.g.
  `ANCHOR_PTY_BACKEND=stub`) that runs a fake pty-able child. Real `pywinpty` is
  used only at runtime, never in pytest.
- **pywinpty is the ONLY permitted native dependency, isolated to the terminal
  subsystem.** Import it lazily; if the import fails, the terminal subsystem
  reports "real terminal unavailable" and the rest of Anchor is unaffected. Add
  it to the dev/runtime extras, NOT to the stdlib-only core import path.
- **f-string discipline** in `anchor_gui.py`: double literal braces in generated
  CSS/JS; `_PROJECT_WINDOW_JS` stays a RAW single-brace string.
- **Security:** every new mutating / terminal / preview-run / worktree endpoint
  sits behind the existing `do_POST` token-auth gate. GET stays read-only.
- **Mirror** new backend data functions into `anchor.py` where natural (Wave 9
  sweeps the rest).
- Reuse, don't fork: build on v2's `sessions.py`, `summarizer.py`,
  `rnd_terminal.py`, `deliverables.py`, `job_runner.py`, `report_viewer.py`,
  `vendor/xterm`.

## Wave 1 — ConPTY-under-service spike (GATES THE WHOLE BUILD)

Prove a real ConPTY terminal can run under the non-interactive `anchor` service
(session 0) before building the session manager on top of it. Create
`pty_manager.py` with a **backend seam**: a `pywinpty` backend and a `stub`
backend (env-selected). Implement the minimal manager core: `start(cmd, cwd, env)
-> session_id`, `write(session_id, bytes)`, `read_since(session_id, cursor)`,
`resize(session_id, cols, rows)`, `kill(session_id)`. Unit-test the manager logic
against the **stub** backend. SEPARATELY, provide a runnable spike
(`spike_conpty_service.py` or a documented orchestrator step) that launches a real
interactive child (e.g. `cmd`/`claude`) via pywinpty under a faithfully simulated
service context (no loaded profile; `USERPROFILE`/`HOME`=`C:\Users\john`; full
system env minus profile vars — per the runtime memory pitfall) and confirms
bidirectional bytes.

- **Done-when:** (a) `pytest` is GREEN with the stub-backend manager tests; AND
  (b) the empirical spike demonstrates a real pywinpty child running + echoing
  bytes under the simulated service context, recorded in EXECUTION-LOG.
- **HALT condition (per user gate):** if the empirical ConPTY-under-service spike
  FAILS, Foreman HALTS and surfaces the fallback options (john-owned session
  broker; or REPL revert) to the user — it does NOT silently proceed or downgrade.
- **G/W/T:** **Given** the stub PTY backend, **When** the manager starts a child,
  writes input, and reads output, **Then** the echoed bytes round-trip and
  `kill` reaps the child; **and** the empirical spike log shows a real pywinpty
  child streaming under the simulated service env.
- **Tests:** `tests/test_pty_manager.py` (stub backend: start/write/read/resize/
  kill, unknown-session errors, reap-on-kill).

## Wave 2 — Durable session registry + git-worktree isolation

New `session_registry.py` (persisted under `.anchor/`, survives restart) modeling
a managed session: `{session_id, project_id, lane, backend(claude|gemini),
worktree_path, branch, status, created_at, label}`. New `worktrees.py`:
`create_worktree(project_id, session_id) -> (path, branch)` (git worktree+branch
under a managed, git-ignored location OUTSIDE the tracked tree),
`remove_worktree(session_id)` (with safety checks), and a `reap_orphans()` sweep.
Wire registry persistence + recovery (reconcile registry vs live processes/worktrees
on load). No UI yet.

- **Done-when:** a session can be registered with its own worktree+branch; two
  concurrent sessions get independent worktrees that don't share a working tree;
  removing a session removes its worktree; `reap_orphans` cleans a worktree whose
  session is gone; the registry round-trips across a simulated restart.
- **G/W/T:** **Given** an active Anchor git repo, **When** two sessions are
  created, **Then** each has a distinct worktree path + branch and a dirty file in
  one is invisible to the other; **When** one is killed, **Then** its worktree is
  removed and the other is untouched.
- **Tests:** `tests/test_session_registry.py`, `tests/test_worktrees.py`
  (hermetic: a temp git repo; create/isolate/remove/reap/recover).

## Wave 3 — ConPTY terminal manager + transport + auth

Tie Wave-1 `pty_manager` + Wave-2 registry/worktrees into the live session
service: `start_session(project_id, lane, backend)` creates a worktree, launches a
**bare interactive** `claude`/`gemini` PTY in it (NO auto-seeded skill), registers
it; `attach`/`detach`/`input`/`resize`/`kill`. Add the browser transport: a
minimal **stdlib hand-rolled WebSocket** endpoint (`/api/rnd/term_ws`) carrying
PTY bytes both ways, with an **SSE-out + POST-in fallback** (`/api/rnd/term_stream2`
+ `/api/rnd/term_input2`). All terminal endpoints are **token-authed**. Reattach
replays the live screen buffer.

- **Done-when:** start→attach→type→see-output→detach (process keeps running)→
  reattach (buffer replays)→kill works against the stub backend over the chosen
  transport; endpoints reject unauthenticated requests.
- **G/W/T:** **Given** a started stub session, **When** the client detaches and
  reattaches, **Then** the session is still running and prior output replays;
  **When** an unauthenticated request hits a terminal endpoint, **Then** it is 401.
- **Tests:** `tests/test_terminal_session.py` (start/attach/detach/reattach/kill,
  buffer replay, auth, WS-frame or SSE framing well-formed without hanging).

## Wave 4 — Stacking window-manager UI

Front-end in `anchor_gui` (dashboard + `_PROJECT_WINDOW_JS`): a top bar of terse
**status-colored session buttons** ("plan 1", "research 2", "foreman 1");
clicking opens/attaches an xterm.js terminal **window**; windows **stack like
bricks**, are draggable/resizable/minimizable; minimize keeps the session
running; **X = kill with an "Are you sure?" confirm**. Status colors per the
locked mapping (green=working, amber=needs-you/done, red=failed, grey=idle),
driven by session status. On dashboard load, repopulate buttons/windows from the
registry.

- **Done-when:** the served HTML/JS includes the session-button bar, the
  stacking/minimizable window container wired to the Wave-3 endpoints, the
  kill-confirm dialog, and the status-color classes; reopening reflects live
  sessions. (Behavioral terminal feel verified in-browser, out of gate scope.)
- **G/W/T:** **Given** ≥2 live sessions, **When** the dashboard renders, **Then**
  two status-colored buttons appear and the window manager can open/stack/minimize
  them; **When** X is clicked, **Then** a confirm dialog gates the kill.
- **Tests:** extend `tests/test_project_window.py` / `tests/test_rnd_ui_wiring.py`
  (button bar markup, status-color classes, kill-confirm wiring, brace hygiene,
  repopulate-from-registry hook).

## Wave 5 — Thin project rows + accurate proactive project summary

Replace the square tile with a thin full-width row (name · summary · per-lane
mini-counts · status dot; click→window; lifecycle controls in a kebab/hover
menu). Add a background **project-summary** generator (extend `summarizer.py`):
generate ONCE from CLAUDE.md + recent plan docs + deliverables, cached,
regenerable; replaces the weak blurb. Generation runs proactively (on rescan)
through the runner seam.

- **Done-when:** the main dashboard renders thin full-width rows; the Anchor row
  shows an accurate cached project summary (not the old first-paragraph blurb);
  lifecycle controls still reachable from the kebab; row click opens the window.
- **G/W/T:** **Given** the Anchor project, **When** the dashboard renders, **Then**
  it is a one-line full-width row with a cached accurate summary and a working
  click-to-open; **Then** no wasted right-half square remains.
- **Tests:** extend `tests/test_tile_render.py` (thin-row markup, cached project
  summary present, kebab controls), `tests/test_summarizer.py` (project-summary
  generate-once + cache).

## Wave 6 — In-place expandable session summaries (content fix + links + effort)

Make clicking a session tile EXPAND an accordion inline (no `/summary` page).
Improve summary CONTENT to the locked shape: when-run, what-was-asked, North-Star,
document links (open rendered markdown in a new tab via `report_viewer`), and
effort (tokens + wall-clock from `job_runner` cost records; imported → "no run
metrics"). Generate proactively (Wave-5 mechanism) + cache; lazy "generating…"
only as fallback. Add a "Launch new session" button inside the expanded panel
that calls Wave-3 `start_session` seeded from this session.

- **Done-when:** clicking the brownfield-discovery planning session expands an
  inline panel with the accurate cached summary + working doc links + effort +
  a "Launch new session" button; collapses back; no navigation to a separate
  page; reopening serves the cache.
- **G/W/T:** **Given** a session with cached summary, **When** its tile is
  clicked, **Then** an inline accordion shows when/what/North-Star/doc-links/
  effort and a Launch-new-session control — with zero separate-page navigation.
- **Tests:** extend `tests/test_project_window.py` (inline-expand markup, doc
  links, effort rendering, launch-from-panel wiring), `tests/test_summarizer.py`
  (the richer content fields).

## Wave 7 — Stage handoffs

When launching a build/execution session, discover the most-recent plan set (from
the `.anchor` store / sessions) and present "execute on this plan set?" —
pre-staging the worktree and surfacing the plan doc paths. Record handoff context
in the per-project Anchor reference (`Anchor.md`/`discovery.json`). General lane
"Launch new session" seeds prior-stage outputs.

- **Done-when:** launching a build session for Anchor proposes the most-recent
  rnd-v* plan set and, on confirm, stages a worktree primed with those plan paths.
- **G/W/T:** **Given** existing planning sessions, **When** a build session is
  launched, **Then** the most-recent plan set is offered and confirming primes the
  session worktree with those docs referenced.
- **Tests:** `tests/test_handoff.py` (most-recent-plan discovery, confirm→prime,
  Anchor.md handoff record).

## Wave 8 — Runnable Anchor deliverable (ephemeral preview)

Pin `anchor_gui.py` as the Anchor deliverable (extend `deliverables.py`). Add a
**Run** action: spin up a preview `anchor_gui.py` on an **OS-assigned ephemeral
port** in a worktree/copy (NEVER binding 8777 / never touching the live service),
register it as a preview session, open it, and reap it on stop. Auth-gated.

- **Done-when:** the Anchor project shows `anchor_gui.py` as a deliverable; the
  Run action launches a preview instance on a free port (≠8777), returns its URL,
  and the preview can be stopped/reaped; the live service is untouched.
- **G/W/T:** **Given** the pinned deliverable, **When** Run is clicked, **Then** a
  preview server starts on an ephemeral port and is reachable, and Stop reaps it;
  **Then** 8777 / the live service is never bound or disturbed.
- **Tests:** `tests/test_deliverable_run.py` (ephemeral-port preview start/stop/
  reap, never-8777 assertion, auth).

## Wave 9 — Ghost World Labs branding on the Home page

Brand the Anchor home page as a **Ghost World Labs** tool, **powered by NextGen
Nuclear**, in a stylish way that fits the existing dark theme. Vendor the brand
mark from `C:\dev\Agentic-Home\GWL-M-Icon.svg` (a ghost on dark slate `#0f172a`
with a green glow `#22c55e` and a ☢ radioactive symbol — note: ☢ already encodes
the NextGen Nuclear tie-in; palette matches Anchor's theme) into Anchor's static
assets (e.g. `vendor/brand/gwl-m-icon.svg`) served via a traversal-safe static
route, and also set it as the dashboard `favicon`. Add a tasteful home-page
header/footer treatment: the ghost mark + a **"Ghost World Labs"** wordmark + a
small **"Powered by NextGen Nuclear ☢"** badge, using the brand palette
(`#0f172a` / `#22c55e` / `#f8fafc`). Keep it elegant and unobtrusive (a header
lockup and/or a footer credit), not garish. f-string brace discipline applies.

- **Done-when:** the served home-page HTML includes the GWL mark asset, the
  "Ghost World Labs" wordmark, and a "Powered by NextGen Nuclear" badge, styled to
  match the theme; the favicon is the GWL mark; the brand asset is served by a
  path-traversal-safe static route.
- **G/W/T:** **Given** the dashboard, **When** the home page renders, **Then** it
  shows the Ghost World Labs lockup + the NextGen Nuclear credit + the GWL favicon,
  and the `/vendor/brand/` route serves the SVG and blocks `../` traversal.
- **Tests:** extend `tests/test_tile_render.py` or add `tests/test_branding.py`
  (home-page lockup markup, favicon wired, brand static route serves + traversal-
  safe).

## Wave 10 — CLI mirror + healthcheck + distro-scan/docs

Mirror new backend data functions into `anchor.py` (sessions/registry/handoff/
deliverable-run inspection where sensible). Extend `anchor_healthcheck.py` to walk
the v3 surface (session registry, stub-PTY session lifecycle, proactive summary,
deliverable-run preview) — fully stubbed. Update the **distribution scan** to
allow the declared `pywinpty` terminal-subsystem exception (and confirm it still
refuses other native/secret leakage). Update `CLAUDE.md`.

- **Done-when:** `python anchor_healthcheck.py` (or its suite equivalent) walks
  the v3 surface clean and stubbed; the distro scan passes with the declared
  pywinpty exception; full `python -m pytest -v` is GREEN; `CLAUDE.md` documents v3.
- **Tests:** extend `tests/test_distro_scan.py` (pywinpty exception declared, no
  other leakage), `tests/test_healthcheck_*`; suite green overall.

## Project DONE

All ten waves GREEN on `python -m pytest -v`; the dashboard shows thin
full-width project rows with accurate cached summaries; session tiles expand
in-place with accurate summaries + doc links + effort; trio work runs as
persistent, worktree-isolated, status-colored ConPTY terminal sessions managed as
stacking windows that survive disconnect; stage handoffs work; the home page is
branded as a Ghost World Labs tool powered by NextGen Nuclear; and the Anchor
deliverable runs as an ephemeral preview. Wave 10 is the terminal/closing wave.
**Note:** Wave 1's ConPTY-under-service empirical proof is a HARD GATE — a failure
there HALTS to the user before any further wave proceeds.
