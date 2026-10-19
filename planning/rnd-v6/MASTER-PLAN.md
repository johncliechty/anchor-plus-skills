# Anchor R&D Surface v6 — "Linked Pipeline" — Master Plan (frozen design)

> Crucible Stage 1 output, locked 2026-06-14. Builds on the merged v5 "Durable
> Work" cockpit (close-to-tile vs kill, past-session summary + continue-live, grass
> B+C workbench, per-build deliverable). v6 comes straight from J.C. Liechty
> **dogfooding the cockpit** — running real researchPrime + Crucible sessions inside
> the Anchor project window — and hitting three concrete walls: sessions don't chain
> into one another, the session windows aren't real windows, and the summaries +
> main dashboard are uninformative/broken. v6 makes the trio a **linked, first-class,
> honestly-summarized pipeline**.
>
> Approved interaction mockup: `_mockups/rnd-v6/session_pipeline.html` (the
> plain-English walkthrough John signed off the decisions against). Build cwd = repo
> root `C:\dev\Anchor`. Each wave ends GREEN on `python -m pytest -v`.

## North Star (locked)

Make the researchPrime → Crucible → Foreman trio a **single linked pipeline of
first-class session windows, backed by summaries that are actually true and a main
dashboard that reflects live project work.** Concretely:

1. **Every session is a first-class window.** A research, planning, or build session
   opens as a window the user can **minimize, freely resize, and maximize** (plus the
   v5 close-to-tile and hard-kill). Windows **stack in a column** (not floating).
2. **Every new session mints a new tile.** Starting a session ALWAYS adds a new tile
   to the tiles row — it never silently reuses or replaces an existing one.
3. **The trio auto-chains, with the right human-in-the-loop.** A **research** session
   advances to a **planning** session **on the user's explicit click** (not every
   research needs planning). A **planning** session advances to a **build** session
   **automatically — but only when that planning session actually produced a
   Foreman-ready plan** (a Master + Implementation plan set exists); a planning
   session with no plan simply doesn't advance.
4. **Same-problem sessions are linked into one traversable chain.** research → planning
   → build are tied together (durable parent/chain link) and the chain is **visible
   and clickable** from any of its tiles/windows.
5. **Finished tiles stay, newest-first.** A finished session keeps its tile; the
   **newest** session is the prominent tile, older ones collapse into a **"previously
   done"** group — nothing vanishes, everything is reopenable.
6. **Summaries are true and informative.** Session and project summaries actually
   render real, grounded content (the prod stream-json parse bug is fixed) and convey
   what the session/project is *for* — never blank, never boilerplate, never
   fabricated.
7. **The main dashboard reflects project work.** The home dashboard shows, per R&D
   project, **what's happening now** — running sessions, latest progress, the latest
   grounded summary — not just a status dot.

## Why v6 (what's wrong today, from live use)

1. **Sessions are islands.** Running research then planning then build means manually
   starting three disconnected sessions; nothing carries context forward and nothing
   records that they're the same effort. The user explicitly wants research→plan→build
   to flow and stay linked.
2. **"Windows" aren't windows.** The v4.1/v5 inline panels only minimize + close +
   kill; there is **no maximize and no free resize** (only the terminal sub-pane
   resizes vertically). The user asked for real minimize/resize/maximize on the
   session windows.
3. **Tile behavior is unreliable & lossy in the row.** Starting a new session doesn't
   always feel like it mints a new tile, and **finished sessions drop out of the
   top tiles row** (`repopulate()` excludes terminal-status sessions), so the chain
   you just ran disappears until a reload.
4. **Summaries are broken in production.** Every real project shows *"No grounded
   objective could be extracted"* and session `summary.md` files are **empty** — the
   summarizer discards 100% of `claude -p --output-format stream-json` output (it
   skips the very envelope lines that carry the text). Tests passed because the stub
   emits bare lines: a tested-but-broken-in-prod gap. (Root-cause fix already exists
   as commit `1bd8b85`; v6 lands it and builds the real-envelope regression guard +
   content quality on top.)
5. **The main dashboard ignores R&D activity.** `render` maps a project to a single
   status dot ("green if any lane has a running session"); it does not surface what is
   running, recent progress, or the latest summary — v5's "timely dashboard
   reflection" under-delivered to a dot.

## Locked decisions (Stage 0/1 user gates — from John's answers on the mockup)

1. **Window controls = minimize · resize · maximize · close · kill, STACKED.** Each
   session window (research/plan/build) gains **maximize** (fill the cockpit viewport,
   toggle to restore) and **free resize** (drag any edge/corner) on top of the
   existing minimize, close-to-tile (keeps the session), and hard-kill. Layout stays
   the v5 **stacked panel column** — NOT floating/draggable windows. (John: "Stacked
   is fine for tiles.")
2. **New session ⇒ new tile, always.** Every session-start path (`term_start`,
   continue, advance, promote-grass, grass-develop) mints a distinct tile that appears
   in the tiles row. No path reuses/replaces a tile. (John: "when I start a new
   session/tile then it should show up in the list of tiles.")
3. **Research → Planning: MANUAL advance.** A research session's window carries an
   **"Advance to Planning →"** control. Clicking it starts a NEW planning session in
   the same chain, **seeded** from the research (its grounded summary / report), and
   **linked** to it. Nothing auto-advances research. (John: "Advance research to
   planning only on my click — some don't advance.")
4. **Planning → Build: AUTOMATIC, gated on a real plan.** When a planning session
   reaches a terminal/**DONE** state — the deliberate **hard-kill** ("I'm done with
   planning") or **reconcile-dead** — AND a **Foreman-ready plan set** tied to it is
   discoverable (`handoff.discover_recent_plan_set` finds a MASTER+IMPL pair), the
   cockpit **automatically** opens a new linked **build** tile, primed via
   `handoff.prime_worktree` (HANDOFF.md referencing the plan docs) and seeded for
   Foreman. The build is primed from the discovered plan set **before** the planning
   worktree is reaped, so the plan docs are never lost. A **keep-alive close does NOT
   advance** (the session is still live — you're not done), and a planning session
   that produced **no** plan set does **not** advance. This holds even when the
   planning session had **no upstream research**. (John: "Advance planning to
   implementation automatically." — OPEN UX nuance flagged for John: whether the
   natural "I'm done planning" gesture should be the hard-kill, a dedicated "Finish →
   Build" button, or a keep-alive close; v6 ships kill/reconcile-dead as the trigger
   and a "Finish → Build" affordance can be added if John prefers.)
5. **Linked chain = durable + traversable.** Each session record gains
   `parent_session_id` and `chain_id`; a chain is research → planning → build (→ …).
   The window/tile shows a **chain breadcrumb** (e.g. `R-1 → P-2 → B-1`) you can click
   to jump between linked sessions. The link is created at advance/continue/promote
   time and survives restart + rescan (persisted in the registry + `handoff`/
   `discovery.json`).
6. **Finished tiles kept, newest-prominent + "previously done."** Terminal-status
   sessions remain in the tiles row. Per lane/chain the **most-recent** session is the
   prominent tile; older finished ones collapse under a **"previously done"** group
   (matching the existing project-window "most-recent visible + previous-sessions
   expander" idiom). Closing never loses a tile; only hard-kill removes one.
   (John: "Keep finished tiles … most recent tile up top … others moved to previously
   done.")
7. **Summaries fixed + informative + regression-proof.** Land the stream-json parse
   fix (commit `1bd8b85`: `job_runner.extract_assistant_text` + shared
   `summarizer._claims_from_job` + `SUMMARY_SCHEMA_VERSION` cache auto-heal +
   `tests/stub_streamjson.py`/`test_summary_streamjson.py`). On top: strengthen the
   session + project summary **content** (skill · prompts · actions for sessions;
   objective/purpose for projects), keep the generate-twice + grounding filter
   (honest when absent, never fabricated), and ensure pre-fix empty caches **auto-heal
   on rescan**. Any test that drives a model through the runner seam MUST use a
   **stream-json-shaped stub**, not bare lines.
8. **Main dashboard reflects project activity.** The home dashboard's R&D project
   rows surface, per project: running-session presence/count, the **latest grounded
   project summary** (objective), and a **timely "what's happening"** line (most-recent
   lane activity / newest session title). It **reads caches only** on render (no
   synchronous model call); a background refresh + the existing `projects_html`
   in-place re-render keep it current.
9. **Verification standard (non-negotiable, the v4 lesson).** Every UI wave's "GREEN"
   = **rendered-DOM assertions** (positive AND negative) **+ a real Playwright/Chromium
   interaction test** (click the control, assert the DOM, no JS console errors) **+ an
   orchestrator screenshot checked against `_mockups/rnd-v6/session_pipeline.html`**
   **+ the user's sign-off before merge.** A string-grep gate is an automatic HALT.
10. **Scope = one build** on `C:\dev\Anchor`, every wave GREEN on `python -m
    pytest -v`. Branch `foreman/rnd-surface-v6`; **no merge to master and no service
    restart without John's sign-off.**

## Out of scope (inclusion test — bloat / later)

- **Calendar integration** and the **app-building version of Anchor** — explicitly
  deferred by John for this round.
- **Floating/draggable windows** — rejected in favor of stacked (Decision 1).
- A full transcript replay/scrubber (the grounded summary suffices), multi-user, and
  cross-project chain views. Re-architecting the summarizer or terminal substrate —
  v6 **extends** them, never forks.
- Auto-advancing **research→plan** (kept manual per Decision 3) and auto-advancing a
  **plan-less** planning session (Decision 4).

## Hard constraints (from CLAUDE.md — non-negotiable)

- **Python stdlib only**, except the declared lazy `pywinpty` (`pty_manager.py` only).
  **Playwright is a DEV-ONLY test dep** (`pytest.importorskip`), never imported by
  product code; `distro.py`'s import scan must stay green.
- **Never bind/touch the live `:8777` service or real data in tests/healthcheck.**
  Model calls via `tests/fake_claude.py` / stream-json stub through
  `ANCHOR_RUNNER_CMD`; PTY via the stub backend (`ANCHOR_PTY_BACKEND=stub`); any
  spawned preview/service on an OS-assigned port **HARD-guarded `!= 8777`** + isolated
  temp `ANCHOR_DATA_DIR`.
- **All mutating / terminal / advance endpoints** behind the `do_POST` token gate;
  GET read-only (token via `?token=`).
- **f-string brace discipline** in `anchor_gui.py` (`_PROJECT_WINDOW_JS` is a RAW
  single-brace string; doubled braces in f-string HTML/CSS).
- **Reuse, don't fork:** `terminal_session.py`, `session_registry.py`, `worktrees.py`,
  `handoff.py`, `summarizer.py`, `effort_history.py`, `job_runner.py`, `pty_manager.py`,
  `vendor/xterm`. **Mirror** new data seams into `anchor.py`; **extend**
  `anchor_healthcheck.py` (`check_rnd_v6_surface`, fully stubbed); **update** `CLAUDE.md`.
- **Scoped commits only** — never sweep runtime-data churn (`dashboard.html`,
  `PROJECTS.md`, `DASHBOARD.md`, `domains/*`, `INBOX.md`, `.anchor/`, `rnd_jobs/`,
  `rnd_registry.json`, `logs/`). Commit only the code/test files each wave touches.

## Risks & mitigations

- **R1 — auto plan→build fires wrongly / spawns junk builds.** Gate strictly on
  `discover_recent_plan_set` returning a real MASTER+IMPL pair tied to that planning
  session; no plan set ⇒ no advance. Make the trigger **idempotent** (one build per
  planning session — keyed by `parent_session_id`) so reconcile/restart can't spawn
  duplicates. Surface it as a clearly-attributed new tile, never silently. Test: a
  planning session with a plan set auto-opens exactly one linked primed build; a
  plan-less one opens none; re-running reconcile doesn't duplicate.
- **R2 — "automatic" never fires because interactive sessions don't exit.** Define the
  trigger on the planning session reaching a terminal/**DONE** state via the deliberate
  **hard-kill** ("done with planning") or **reconcile-dead** — NOT on a keep-alive
  close (which leaves it running, v5) and NOT on process self-exit. **Prime the build
  from the discovered plan set BEFORE the planning worktree is reaped** so the plan
  docs survive. Test the kill/reconcile-dead transition drives exactly one advance and
  the build's HANDOFF.md references the real plan docs.
- **R3 — chain links break on restart/rescan.** Persist `parent_session_id`/`chain_id`
  in the registry record (survives restart) AND mirror the cross-lane edge into
  `handoff`/`discovery.json` (rescan-durable, like v3 handoffs). Test: a chain survives
  a registry reload + a rescan.
- **R4 — keeping finished tiles re-clutters / re-introduces the v3 stale-session
  problem.** Newest-prominent + "previously done" collapse bounds the visible set;
  reconcile still re-statuses dead sessions; closing keeps the record, only kill
  reaps. Test: N finished sessions render one prominent + a collapsed group; kill
  removes; reopen works.
- **R5 — summary still blank / fabricated in prod.** The parse fix + a **stream-json
  shaped** regression stub (not bare lines) + the generate-twice + grounding filter +
  `SUMMARY_SCHEMA_VERSION` auto-heal. Honest placeholder when truly absent. Test:
  realistic stream-json yields a grounded non-empty summary; an ungrounded claim is
  dropped; a pre-fix empty cache heals on rescan.
- **R6 — another vacuous UI gate ships a broken UI.** Decision 9 (DOM + Playwright +
  screenshot + sign-off) mandatory per UI wave; a string-grep gate HALTs the wave.
- **R7 — window resize/maximize fights the xterm fit + terminal pump.** Reuse the v4.1
  proven fit/resize-observer; maximize/restore must re-fit the terminal; assert no
  freeze + correct cols/rows after resize. Test in the Playwright wave.

## Definition of done (project)

All waves GREEN on `python -m pytest -v` AND: each session window minimizes / freely
resizes / maximizes / closes-to-tile / hard-kills, stacked; every new session mints a
new tile; a research window's "Advance to Planning →" starts a linked, seeded planning
session; a planning session that produced a plan set **auto-opens** a linked, primed
build tile (and a plan-less one does not), even with no upstream research; sessions of
one problem form a durable, traversable research→plan→build chain with a breadcrumb;
finished tiles persist newest-prominent with a "previously done" group; session +
project summaries render real grounded content via the stream-json fix (regression-
guarded, honest when absent); the main dashboard reflects per-project running/progress/
summary from cache; the CLI mirrors the new read seams; `check_rnd_v6_surface` passes
fully stubbed (no `:8777`, no orphans); `distro` scan clean (no Playwright in product
code); `CLAUDE.md` updated; and **every UI wave is verified by Playwright + a
screenshot + John's sign-off before merge.**
