# Anchor R&D Surface v7 — "Integrated Board" — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, locked 2026-06-15. Frozen design: `MASTER-PLAN.md` (this
> folder) + the approved mockup `_mockups/rnd-v7/board_integration.html`. Build cwd =
> repo root `C:\dev\Anchor`, branch `foreman/rnd-surface-v7` (off master, which has v6
> merged). Each wave ends GREEN on the ground-truth gate and adds/extends tests.

test-command: python -m pytest -v

## Conventions (read before any wave)

- **Active Anchor project id:** read from `rnd_registry.json` at build time; never
  hard-code.
- **No live `claude`/`gemini`/real-PTY in the gate.** Model calls via
  `tests/fake_claude.py` / `tests/stub_streamjson.py` through `ANCHOR_RUNNER_CMD`; PTY
  via the stub backend (`ANCHOR_PTY_BACKEND=stub`). Never `:8777` or real data.
- **pywinpty** is the only native dep (lazy, `pty_manager.py` only). **Playwright is
  DEV-ONLY** (`pytest.importorskip("playwright.sync_api")`), never in product code;
  `distro.py` scan stays green (Wave 5 asserts it).
- **f-string discipline** in `anchor_gui.py`: `_PROJECT_WINDOW_JS` is a RAW single-brace
  string; double literal braces in f-string HTML/CSS.
- **Security:** every new mutating / terminal endpoint behind the `do_POST` token gate;
  GET read-only (token via `?token=`).
- **Reuse, don't fork:** `summarizer.py`, `effort_history.py`, `session_registry.py`,
  `terminal_session.py`, `sessions.py`, `handoff.py`, the v6 board/tile/blurb seams.
- **Scoped commits only** — never the runtime-data churn (`dashboard.html`,
  `PROJECTS.md`, `DASHBOARD.md`, `domains/*`, `INBOX.md`, `.anchor/`, `rnd_jobs/`,
  `rnd_registry.json`, `logs/`). Commit only the code/test files each wave touched.
- **Baseline before Wave 1:** the v6 merge baseline was **816 passed, 1 skipped**.
  Re-establish at Wave 1 start; each wave must hold or grow it.
- **UI VERIFICATION IS MANDATORY (the v4 lesson)** for every wave that changes rendered
  UI (Waves 3, 4). "GREEN" = (a) rendered-DOM assertions (parse served HTML with
  `html.parser`; new structure present AND old/replaced absent — positive + negative);
  (b) a real Playwright + Chromium interaction test (boot `gui.make_server('127.0.0.1',0)`,
  click the actual control, assert DOM + no JS console errors); (c) the orchestrator
  captures a screenshot (PNG under `_devtest/`), Reads it, checks vs the rnd-v7 mockup;
  (d) user sign-off before merge. A string-grep-only test is an automatic HALT.

---

## Wave 1 — Short, clean summaries (#1) — plain-text normalizer + length caps (backend)

Add `summarizer.short_summary_text(structured, max_chars=…)` (or extend `_summary_text`)
that produces the **displayed short form**: it strips markdown control sequences (`**`,
`__`, `##`/heading marks, backticks, leading list markers, link syntax) AND a defined
decorative-glyph set (`✓ ✗ → ↞ ☢ • —`→"-"/space, box-drawing, emoji), collapses
whitespace, and **caps length** (objective ≈ 1 sentence / ~140 chars; a separate
`tile_blurb(...)` ≈ 8–12 words / ~64 chars, cut on a word boundary with an ellipsis).
Apply it at the SHORT display sites: the project objective line (`render_project_tile_html`
+ the project-window header) and (Wave 3) the tile blurb. The **full markdown** on the
`/summary` page is unchanged. Generate-twice + grounding filter unchanged.

- **Done-when:** `pytest` GREEN; a structured summary whose claims contain `**`, `—`,
  `##`, backticks, `✓` renders a SHORT line with none of those glyphs, within the cap,
  word-boundary-truncated; a normal clean sentence is returned unchanged (not
  over-stripped); the full `/summary` markdown still contains its formatting.
- **G/W/T:** **Given** a cached project summary whose objective claim is
  `**Goal:** ship X — handle ## edge \`cases\` ✓`, **When** the dashboard objective
  renders, **Then** it shows a clean capped sentence (`Ship X - handle edge cases`-ish)
  with no markdown/decorative glyphs; **Given** an already-clean sentence, **Then** it is
  returned unchanged; **Given** the `/summary` page, **Then** full markdown is intact.
- **Tests:** `tests/test_summary_shorten_v7.py` — normalizer unit cases (each glyph
  class stripped; clean text unchanged; cap + word-boundary truncation; whitespace
  collapse) + the objective render site uses it + the `/summary` markdown is untouched.
  Backend only.

## Wave 2 — Summarize each session on finish (#3) — proactive cache + blurb source (backend)

Trigger a **background** session-summary generation when a session reaches a terminal
state. Wire `_trigger_session_summary(...)` (the existing Wave-6 background daemon path)
into the session-finish transitions: the `POST /api/rnd/term_kill` path, the
`finish_to_build` path, and `reconcile_and_advance` (best-effort, never block the
response; idempotent — skip if already cached; a failed gen never poisons the cache).
Add `summarizer.session_blurb(folder, pid, lane, session_id)` → the short, clean
(`short_summary_text` from Wave 1) one-line blurb from the cached session summary, or an
honest `""`/placeholder when uncached. This is the data source for the Wave-3 tile blurb
and already feeds the v6 restart seed (`_build_continue_seed`).

- **Done-when:** `pytest` GREEN; finishing a session (kill/finish/reconcile-dead)
  schedules exactly one background summary (not blocking the response), idempotent on a
  cached one; `session_blurb` returns a short clean line when cached and an honest
  placeholder when not; no synchronous model call on any render path.
- **G/W/T:** **Given** a running stub session with member docs, **When** it is killed,
  **Then** a background `summarize_session` is scheduled (the kill response returns
  immediately) and, once cached, `session_blurb` returns a short clean blurb; **Given**
  an uncached session, **Then** `session_blurb` returns the honest placeholder, not a
  blank/garbage, and the render path makes no model call.
- **Tests:** `tests/test_summary_on_finish_v7.py` — finish transitions schedule one
  background gen (spy/poll the daemon) + non-blocking + idempotent + failed-gen-no-cache
  + `session_blurb` short/clean/honest-absent (through the stream-json stub). Backend.

## Wave 3 — Live sessions integrated into the lane columns (#2) — board bridge + blurb (UI)

Bridge live `session_registry` sessions into the board lane render so a started session
appears as a tile in its lane column immediately and persists when done. In
`_gather_project_sessions` (or a new merge step feeding `_render_kanban_html`), MERGE the
registry's managed sessions for research/plan/build/deliverables with the
effort-history sessions, **deduped by session_id** (a session that is both a live record
and an effort record appears once), ordered newest-first → the most-recent is the
prominent tile, older ones under the existing openable "previous sessions" expander.
Each tile shows a **short blurb** from `summarizer.session_blurb` (Wave 2) — running
sessions may show their intent/`what_was_asked` until a summary exists; honest when
absent. The top live strip (`renderSessionBar`) is unchanged (stays for active). Board
render stays cache/registry-only (no model call).

- **Done-when:** the UI-verification set passes — starting a research/plan/build session
  makes a tile appear in that lane column immediately (running light) without losing the
  top-strip chip; the tile carries a short clean blurb; when done it stays as a grey
  tile, newest prominent + older under the expander; no duplicate tiles (dedupe by
  session_id); render makes no model call.
- **G/W/T:** **Given** a project window, **When** the user starts a planning session,
  **Then** a tile appears in the Planning column (running) with a short blurb AND the
  session also shows in the top active strip — exactly one tile per session per lane;
  **When** the session finishes, **Then** the tile stays (grey), newest prominent and
  older planning sessions collapse under "previous sessions".
- **Tests:** `tests/test_board_live_integration_v7.py` — DOM (a live registry session
  renders as a lane-column tile with a blurb; dedupe — one tile per session_id;
  positive+negative vs the v6 board which excluded live sessions) + render-path no-model
  call + Playwright (start a session → tile appears in its lane column + strip; finish →
  stays + grouped) + screenshot vs the mockup board.

## Wave 4 — "Open terminal" general session button (#4) — bare general lane (UI + backend)

Add a top-of-dashboard **"Open terminal"** affordance on the project window that starts a
**bare general session**: a `general` lane value that is intentionally NOT in `LANE_SKILL`
(so `seed_for_lane` returns None → a bare PTY), with the Claude/Gemini engine toggle,
opened in a session window and shown in the top active strip. It is NOT a board lane
column (John's choice B). Wire `general` into the lane enumerations it must pass
(`terminal_session._valid_lanes`) but EXCLUDE it from the trio board columns and from the
auto-advance chain (a general session never advances). Reuse `start_session` (bare seed),
the window/strip machinery, and the Wave-2 summary-on-finish (general sessions get a
summary too, so they're restartable).

- **Done-when:** the UI-verification set passes — clicking "Open terminal" starts a bare
  general session (no skill seed) with an engine toggle, opens its window, and shows it in
  the top strip; it does NOT create a board lane column and never auto-advances; it can be
  summarized/continued like other sessions.
- **G/W/T:** **Given** the project window, **When** the user clicks "Open terminal",
  **Then** a bare `general` session starts (no trio skill seeded), opens a window, and
  appears in the active strip; **and** no Research/Planning/Build column tile is created
  for it and finishing it never opens a build.
- **Tests:** `tests/test_general_terminal_v7.py` — backend (`start_session(lane='general')`
  is bare/no-seed through the stub PTY; `general` validates; excluded from trio board +
  chain/auto-advance) + DOM (the "Open terminal" button present; general is NOT a board
  lane column — negative) + Playwright (click → bare session + window + strip; no console
  errors) + screenshot.

## Wave 5 — CLI mirror + healthcheck v7 + distro scan + docs (PROJECT DONE)

Mirror any new read seam into `anchor.py` (e.g. `rnd blurb <pid> --lane --session` →
`summarizer.session_blurb`, if useful; read-only, honest-absent). Extend
`anchor_healthcheck.py` with `check_rnd_v7_surface` (fully stubbed: stub PTY +
stream-json stub runner + temp worktree base + temp git project): walk (a) the short/clean
normalizer (glyphs stripped, capped, clean text unchanged); (b) summarize-on-finish (a
killed session schedules + caches a summary; `session_blurb` short/clean); (c) the board
bridge — a live registry session is included in the lane-session merge and deduped; (d) a
bare `general` session starts/validates and is excluded from the trio board + chain; tear
everything down, restore env, never `:8777`. Confirm `python -m distro` scan clean
(Playwright not in product code). Update `CLAUDE.md` (a v7 "Integrated Board" section +
the new endpoints/CLI + the `general` lane note + the normalizer/summarize-on-finish
notes).

- **Done-when:** the **full** suite GREEN; the new CLI subcommand works; `check_rnd_v7_surface`
  passes fully stubbed + tears down (no `:8777`, no orphan PTY/worktree); `python -m distro`
  scan clean; `CLAUDE.md` documents v7.
- **G/W/T:** **Given** the stubbed env, **When** `check_rnd_v7_surface` runs, **Then** it
  walks the normalizer + summarize-on-finish + board bridge + general lane and tears down
  with no orphan and never binds `:8777`; **and** the distro scan reports only the declared
  `pywinpty` exception (no Playwright in product code).
- **Tests:** `tests/test_cli_v7.py`, `tests/test_healthcheck_v7.py`, `tests/test_distro_scan_v7.py`
  — and the whole suite GREEN.

## Project DONE

DONE = Wave 5 GREEN on `python -m pytest -v` AND the Master Plan "Definition of done" met
— including the UI waves' (3–4) Playwright + screenshot + **John's sign-off**. Terminal
wave = Wave 5. **No merge to master / no `nssm restart anchor` until John signs off**
(then: merge → `nssm restart anchor` elevated → rescan to heal summaries).
