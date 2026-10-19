# Anchor R&D Surface v4 — "Project Cockpit" — Master Plan (frozen design)

> Crucible Stage 1 output, locked 2026-06-12. Builds on v3 "Mission Control"
> (already merged to master: `pty_manager.py`, `session_registry.py`,
> `worktrees.py`, `terminal_session.py`, `summarizer.py`, `deliverables.py`,
> `preview_server.py`, `handoff.py`, `vendor/xterm`, GWL brand mark). v4 does NOT
> re-architect the substrate — it **re-lays-out the project window** (Paradigm 2:
> inline expanding panels), **fixes the terminal to one honest substrate**, and
> **restores/repairs a handful of dashboard data surfaces**. The full UX is locked
> by the user across three review rounds; the canonical pixel spec is the frozen
> mockup `_mockups/project_window_proposals.html` (Paradigm 2) +
> `_mockups/branding_proposals.html` (Option B).

## North Star (locked)

Make each project's window a **calm, single-screen cockpit** for its trio work.
Every lane (Research · Planning · Build) shows its most-recent session as a **tile
with one honest status light** (green=working · amber=needs-you · red=crashed ·
grey=idle/done). Clicking a tile **expands an inline panel in place** — never a
new page — that **stacks a balanced summary on top of a real, resizable terminal
below**. Opening a new session **feels exactly like a normal Claude Code / Gemini
session**: the lane's skill auto-loads **once**, greets **once**, then behaves
normally — no repeating-prompt loop, no second half-wired substrate. The board
stays glanceable and truthful: grass is an **idea board**, every build pins a
**linked, launchable deliverable**, rows are **one clean line**, and **cost ·
tokens · time** are visible again per project.

## Why v4 (the problem with v3 as shipped)

v3 delivered the substrate but three things land wrong for the user:
1. **The terminal feels "weird."** Two substrates are half-wired into the same
   window — the v2 stream-json REPL (`rnd_terminal.py`, console drawer) **re-seeds
   its skill prompt every turn** (the repeated *"this is the beginning of planning
   session…"*), while the v3 bare ConPTY drops you on an **empty `claude` REPL**.
2. **Clicking a session is unsatisfying** — floating stacking windows + a separate
   summary surface; the user wants the summary and terminal **together, inline,
   stacked**, with the materials/links **balanced**.
3. **Dashboard regressions** — a directory line per project eats space, and the
   **cost/tokens/time rollup is gone**. Grass and deliverables still open as flat
   text rather than an idea board / launchable artifact.

The terminal substrate is **proven**: `_prototypes/term_harness/` runs real
interactive `claude.exe` in a ConPTY over a stdlib WebSocket into xterm.js
(`pty_smoke.py`, `ws_client_test.py`, `claude_interactive_capture.py` all pass —
real model turn `● PTYHELLO`). v4 keeps that substrate and removes the second one.

## Locked decisions (Stage 0/1 user gates)

1. **One terminal substrate.** The project window uses ONLY the v3 ConPTY path
   (`terminal_session.py` → `pty_manager.py` → xterm.js via `term_ws` /
   `term_stream2`). The v2 stream-json REPL (`rnd_terminal.py`) is **unwired from
   the project window** (the module stays for now; it is simply not used by the
   cockpit). **Raw xterm is the default** for interactive Claude/Gemini.
2. **Skill auto-loads once, greets once.** On a NEW session, the lane's skill
   (Research→researchPrime · Planning→Crucible · Build→Foreman) is loaded by **one
   opening stdin turn**, the model greets a single time ("✓ Crucible loaded — what
   would you like to plan?"), then it is a normal session. **The seed is never
   re-sent** — this is the literal fix for the repeating-prompt bug.
3. **Engine is per-session and persists.** Claude Code vs Gemini CLI is chosen
   **once** when a session is created and stored on the session record; every
   re-open uses it. A **◆/✦ toggle** on the tile/panel header switches it (relaunch
   on the other engine, same lane/worktree). New sessions **default to the
   project's last-used engine**.
4. **Project window = Paradigm 2 (inline expanding panels).** Lane tiles with
   lights; clicking expands a **full-width inline panel** that pushes the board
   down; multiple panels stack; **minimize → tile** (session keeps running); **X =
   kill behind an "Are you sure?" confirm**. This **replaces** v3's floating
   stacking-window manager in the project window.
5. **Panel internals stack & balance.** Summary **on top**, full-width terminal
   **below** (NOT left/right). The summary is a two-column split — **materials
   left, role-tagged doc/deliverable links right** — sized so **both columns fill
   equal vertical height**. The terminal pane is **vertically resizable** (drag its
   bottom edge taller/shorter).
6. **Per-lane doc roles.** Research → Executive summary (md) · Full report (PDF) ·
   Agent-readable (json) · provenance. Planning → MASTER-PLAN · IMPLEMENTATION-PLAN
   · North-Star. Build → North-Star · the linked deliverable · EXECUTION-LOG · the
   plan it executes. Missing roles degrade gracefully (shown only when present).
7. **Grass Catcher = idea board.** Idea cards, each with **→ Research** / **→ Plan**
   actions that launch a new session in that lane seeded with the idea. Fed by
   manual add, promote-from-INBOX, discovery (all already in `effort_history` /
   `brownfield_scan`).
8. **Deliverable launch is type-aware.** Every Foreman run auto-pins **one** linked
   deliverable. Launching adapts to type: **skill / tool → verify status
   (available / loaded)**; **service → launch into a window, or pull up the
   already-running one**; **program → run in a window**; **doc → open rendered
   (PDF/Reader)**. service/program **health-check before the window shows**; every
   preview/run binds an **OS-assigned port HARD-guarded ≠ 8777**.
9. **Main-dashboard rows drop the directory line.** The folder path was the
   per-folder *group header* (one path line per single-project folder). Rows become
   a **flat one-line list**; the path moves to the **project-window header** only.
10. **Cost · tokens · time restored.** A per-project rollup `Σ tokens · $ · time ·
    N sessions` appears on the **project-window header** AND on **each main
    dashboard row**, summing **RUN sessions only** (imported/discovered contribute
    nothing — never fabricated). **Default = lifetime totals**, with a clickable
    **last-30-days** toggle.
11. **Branding = Option B** on the main dashboard masthead: "Anchor" title · a
    vertical divider · the GWL mark + wordmark off to the side · a "Powered by
    NextGen Nuclear ☢" pill far right (reuse `vendor/brand/gwl-m-icon.svg`).
12. **Scope = one comprehensive Foreman build** (all of v4 in one run), built on
    the repo at `C:\dev\Anchor`, every wave GREEN on `python -m pytest -v`.

## Inclusion test (the size rule)

Every wave serves a North-Star criterion above. Explicitly **out of scope** (would
be bloat or belongs elsewhere): rewriting the summarizer pipeline (reuse it),
multi-user/remote auth changes, replacing xterm/pywinpty, a general window manager
beyond the cockpit panels, Gemini parity for Plan/Build (Gemini stays Research-lane
per `gemini-trio-adapter`), and touching the v2 REPL internals (only unwire it).

## Hard constraints (from CLAUDE.md — non-negotiable)

- **Python stdlib only**, EXCEPT the single declared `pywinpty` optional extra
  (LAZY import, `pty_manager.py` ONLY). `distro.py`'s import scan must still pass
  with no new native/third-party import.
- **Never bind or touch the live `:8777` service or real data in tests.** Model
  calls go through `tests/fake_claude.py` via `ANCHOR_RUNNER_CMD`; PTY through the
  **stub backend** (`ANCHOR_PTY_BACKEND=stub`); previews/services on **OS-assigned
  ports HARD-guarded ≠ 8777**; temp `ANCHOR_DATA_DIR` / `ANCHOR_WORKTREE_BASE`.
- **All mutating / terminal / preview / launch endpoints stay behind the existing
  `do_POST` token-auth gate**; GET stays read-only (GET transports gate via
  `?token=`).
- **f-string discipline** in `anchor_gui.py`: double literal braces in generated
  CSS/JS; `_PROJECT_WINDOW_JS` stays a RAW single-brace string.
- **Markdown/plain-text source of truth**; everything accessible from any CLI.
- **Mirror** new backend data functions into `anchor.py`; **extend**
  `anchor_healthcheck.py` to walk the v4 surface, fully stubbed; **update**
  `CLAUDE.md`.

## Risks & mitigations

- **R1 — Skill auto-load turns into a loop again.** Mitigation: seed is exactly
  ONE stdin turn recorded as `seeded=true` on the session; Wave 1 tests assert the
  seed is emitted once and never re-emitted across many `read_since` calls.
- **R2 — Engine toggle orphans a PTY/worktree.** Mitigation: toggle goes through
  the existing `kill`→`start_session` reap path (rollback on failure); test asserts
  no orphan PTY/worktree after a switch.
- **R3 — Inline-panel rewrite regresses the proven transport.** Mitigation: keep
  `term_ws`/`term_stream2`/`term_input2` endpoints exactly; only the host DOM
  changes (floating window → inline panel). Wave 4 reuses the v3 mount code.
- **R4 — "service" deliverable squats a port / touches real data.** Mitigation:
  reuse `preview_server` discipline — `pick_free_port` (asserts ≠ 8777), isolated
  temp data dir, loopback bind, reap-on-close, `previews.json` reconcile.
- **R5 — Rollup fabricates numbers.** Mitigation: sum only `job_runner` cost
  records for RUN-provenance sessions; imported/discovered → contribute 0 and the
  UI shows "no run metrics", never an invented figure.

## Definition of done (project)

All nine waves GREEN on `python -m pytest -v`; the cockpit renders Paradigm 2 with
working inline panels + resizable terminals; a new session auto-loads its skill
once and behaves like a normal terminal; engine persists + toggles; grass is an
idea board; deliverables launch by type (never on 8777); rows have no directory
line; the cost/tokens/time rollup shows lifetime with a 30-day toggle; Option B
branding is on the masthead; the CLI mirrors the new data seams; the healthcheck
walks the v4 surface fully stubbed; `distro.py` scan passes; `CLAUDE.md` updated.
