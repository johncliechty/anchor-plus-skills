# Anchor R&D Surface v3 — "Mission Control" — Master Plan (frozen design)

> Crucible Stage 1 output, approved 2026-06-11. Supersedes nothing in v2 (which
> shipped to master) — it BUILDS ON v2 (sessions.py, summarizer.py,
> rnd_terminal.py, deliverables.py, job_runner.py, vendor/xterm). v3 reshapes the
> UX (thin rows, in-place expandable accurate summaries), turns the terminal into
> a persistent, isolated, real (ConPTY) multi-session window manager, adds clean
> stage handoffs + concurrency isolation, and makes the Anchor deliverable
> runnable.

## North Star (locked)

Turn the Anchor dashboard into a **durable mission-control for trio-driven R&D**.
Every project is a thin, full-width row with an accurate, auto-generated summary.
Clicking any session expands a concise, **cached, in-place** summary (when ·
what-was-asked · North-Star · clickable doc links · effort in tokens+time) —
never a separate "no summary" page. Trio work runs as **persistent, isolated,
server-side terminal sessions** managed like stacking windows — open / attach /
minimize / kill-with-confirm, status-colored, surviving disconnect — where
launching a session **feels exactly like a real Claude/Gemini terminal**, hands
off cleanly stage→stage, and never lets a planning session collide with a
running build.

## Locked decisions (Stage 0/1 user gates)

1. **Terminal substrate = real ConPTY** (via `pywinpty`). This consciously WAIVES
   Anchor's "stdlib-only / no native assets" rule **for the terminal subsystem
   only**. Everything else stays stdlib. The subsystem degrades gracefully (and
   the dashboard still works) if `pywinpty` is absent.
2. **Summaries = proactive background generation, cached.** Generated once
   (at discovery/rescan and right after a run completes); clicking shows a ready,
   cached summary in-place. Lazy "generating…" only as a fallback.
3. **Concurrency isolation = git worktrees per session.** Each plan/research/build
   session runs in its own worktree+branch; trees never collide.
4. **Scope = one comprehensive plan** (all of v3 in a single Foreman build).
5. **ConPTY-under-service is gated by a Wave-1 spike that HALTS to the user if it
   fails** — no silent downgrade.
6. **Status colors:** green = actively working (ignore) · amber = needs you / done
   (come look) · red = failed · grey = idle.

## Real intent (Parable of the Oranges)

Anchor is John's single pane of glass for managing every project across every
trio stage, replacing the cognitive load of juggling many VS Code windows +
terminals. The deeper needs it must serve: (a) at-a-glance TRUTH of what exists /
what's running / what needs attention; (b) frictionless DRIVE — start, attach,
minimize, kill durable server-side sessions like a window manager; (c) clean
CONCURRENCY — plan the next wave while a build runs, isolated; (d) faithful
HANDOFFS stage→stage; (e) RUNNABLE deliverables. Bloat that doesn't serve this is
cut or Grasscatched.

## Current-state ground truth (verified 2026-06-11)

- The `anchor` NSSM service runs as **`.\john`** with working Claude **subscription**
  creds (`C:\Users\john\.claude\.credentials.json`) + `claude.exe`/`gemini`/`node`
  on the service PATH. Live trio off the subscription from the server is viable
  (v2 terminals already spawn `claude`). So "no summary" is a UX/architecture
  issue, NOT creds.
- v2 summaries are generated **lazily on click into a separate `/summary` page**
  that renders an empty/failed state when generation hasn't run or yields no
  grounded claims — this is exactly the "hit summary → no summary" symptom.
- v2 terminal = a structured **stream-json REPL** that auto-seeds the lane skill
  (hence the "unintelligible researchPrime internals" dump) and whose interactive
  gate-answer path is empirically fragile (AskUserQuestion can't be answered
  cleanly). It is NOT a faithful terminal.
- v2 tiles are small squares wasting the right half of each row.
- Anchor's own deliverable (the `anchor_gui.py` server) is not represented.

## Architecture (frozen)

### A. Thin full-width project rows
Replace the square `rnd-tile` (in `anchor_gui.render_projects_view_html`) with a
one-line, full-width row: name · accurate summary · per-lane mini-counts · a
status dot. Click → opens the project window. Lifecycle controls (P1/P2, archive,
notes, rescan) move into a hover/kebab menu so the row stays thin.

### B. Accurate, proactive, cached summaries (project + session)
Evolve `summarizer.py` so a background job generates each summary ONCE (on
discovery/rescan and right after a run completes) and caches it. Content fixed to
be real and concise: **when-run (date) · what-was-asked (the seed/intent) ·
North-Star (extracted from the session's MASTER-PLAN) · documents produced
(master plan / implementation plan / report …) as clickable links that open
nicely-rendered markdown in a new tab · effort = tokens + wall-clock** from the
`job_runner` cost records. Imported sessions honestly show "imported — no run
metrics." The PROJECT summary is generated the same way from CLAUDE.md + recent
plan docs + deliverables (replaces the weak first-paragraph blurb).

### C. In-place expandable session summaries (kills the "no summary" page)
Clicking a session tile in any lane EXPANDS an accordion **inline** in the Kanban
showing the cached summary + doc links + a "Launch new session" button; collapse
to minimize. No navigation to `/summary`. The only new-tab is the rendered
markdown document itself (reuse `report_viewer`).

### D. Persistent server-side session manager + real ConPTY terminals
A durable **session registry** (persisted under `.anchor/`, survives restart) +
a **ConPTY terminal manager** (`pty_manager.py`, pywinpty backend with a stub
backend seam for tests via an env override). Each session is a genuine PTY
running interactive `claude`/`gemini` (real TUI, user-driven; NO auto-seeded
skill, NO gate-answer hack). Processes run under the `anchor` service (as john)
and SURVIVE client disconnect; reattach replays the live screen buffer.
**Transport:** a minimal **stdlib hand-rolled WebSocket** endpoint carrying PTY
bytes both directions into the vendored **xterm.js**; **SSE-out + POST-in is the
fallback** if the WS proves troublesome. Terminal endpoints are **token-authed**
(they are an RCE surface; must not sit on the unauthenticated GET surface).

### E. Stacking window-manager UI
A top bar of terse **status-colored buttons** ("plan 1", "research 2",
"foreman 1"); click to open/attach. Terminal windows **stack like bricks (2–3)**,
are draggable / resizable / minimizable; minimize keeps the process running; an
**X kills with an "Are you sure?" confirm**. Status colors per the locked mapping
(green/amber/red/grey). Reopening Anchor repopulates the running sessions and
their windows from the registry.

### F. Git-worktree concurrency isolation
Each session runs in its own **git worktree + branch** under a managed,
git-ignored location (outside the tracked tree), so a planning session can't
dirty a running Foreman build's tree. Worktree created on launch; removed on kill
(with confirm). Results are merged back deliberately (a session can be
merged/inspected when done). A reaper cleans orphaned worktrees.

### G. Stage handoffs
Launching a build/execution session finds the **most-recent plan set** (from the
`.anchor` store / sessions) and asks "execute on this plan set?", pre-staging its
worktree and printing the plan paths in the terminal for the user to confirm/run.
General principle: each lane's "Launch new session" can seed context from the
prior stage's outputs, all discoverable from the dashboard + the Anchor.md/.anchor
reference.

### H. Runnable Anchor deliverable
Pin `anchor_gui.py` as the Anchor project's deliverable. Its **Run** action spins
up a **preview instance on an OS-assigned ephemeral port** (in a worktree/copy,
never touching the live :8777 service or its single-instance guard) and opens the
browser to it; the preview is bounded and reaped.

### I. Robustness / persistence
All sessions, PTYs, worktrees, and preview servers run under the `anchor` service
on gwl-server → they survive RDP disconnect / client crash. The session registry
is persisted; on reconnect the dashboard reflects true live state. A reaper
handles dead/hung sessions, orphan worktrees, and stale preview servers.

## Constraints (binding)

- **Stdlib-only EXCEPT the terminal subsystem**, which may use `pywinpty`
  (ConPTY). The native dep is isolated; if absent, the terminal subsystem
  degrades and the rest of the dashboard is unaffected. The distribution scan +
  healthcheck are updated to know about this single, declared exception.
- **No live `claude`/`gemini` in the test gate.** Model/PTY interactions are
  exercised via `tests/fake_claude.py` through `ANCHOR_RUNNER_CMD` and a **stub
  PTY backend** (a fake pty-able child) — never live. The ConPTY-under-service
  empirical proof (Wave 1) is a documented manual/orchestrator check, separate
  from the pytest gate.
- **`anchor_gui.py` HTML is f-string-generated** (double literal braces);
  `_PROJECT_WINDOW_JS` is a RAW single-brace string.
- **Security:** terminal + preview-run + worktree endpoints are token-authed;
  GET endpoints stay read-only/unauthenticated; a real interactive terminal
  reachable over Tailscale is an RCE surface and must be behind the token.
- **Mirror** new backend data functions into `anchor.py` where natural.
- Runtime unchanged otherwise: NSSM service `anchor`, binds localhost:8777,
  single-instance guard on 8777.

## Out of scope (Grass Catchers for later)

- A general multi-user / multi-tenant terminal server.
- Cross-machine sync of `.anchor` / worktrees.
- Auto-merging session worktree results without user review.
