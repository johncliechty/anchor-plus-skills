# Anchor R&D Surface v7 — "Integrated Board" — Master Plan (frozen design)

> Crucible Stage 1 output, locked 2026-06-15. Follows the merged v6 "Linked Pipeline".
> Comes from J.C. Liechty reviewing v6 and giving four points. Build cwd = repo root
> `C:\dev\Anchor`. Approved interaction mockup: `_mockups/rnd-v7/board_integration.html`
> (board lane-tile integration + the short/clean summary before/after). Each wave ends
> GREEN on `python -m pytest -v` and extends v6 seams (no new modules).

## North Star (locked — John's Stage-0 answers)

Make the project board an **honest, integrated, well-summarized view of all work**:

1. **Short, clean summaries.** Every *displayed short* summary (the project objective
   line, the per-tile blurb) is length-capped and **scrubbed of markdown/decorative
   glyphs** (`**`, `—`, `##`, backticks, the `✓` greeting, etc.). Full markdown stays
   only on the dedicated summary page.
2. **Live sessions live in their lane column.** A session started in research / plan /
   build / deliverables appears **as a tile in its lane column on the board the moment
   it starts** (green = running) and **stays there when done** (grey) — newest
   prominent, older ones behind an openable "previous sessions" expander, each with a
   **very short blurb**. The top "active now" strip stays (John likes it) for live
   sessions.
3. **Every session is summarized on finish.** When a session reaches done/closed, a
   validated session summary is **generated and cached then** (not only lazily on
   view), so the session is restartable *with* a summary and the lane tile has a real
   blurb. Honest when absent; never a synchronous model call on render.
4. **A general terminal, one click away.** A top-of-dashboard **"Open terminal"**
   button launches a **bare general session** (no trio skill seeded; Claude/Gemini
   engine toggle) in a window; it rides the top active strip. It is **not** a board
   lane (John's choice B).

## Why v7 (what John flagged in v6 review)

1. **Summaries are long and full of "strange symbols."** The one-line objective just
   joins grounded claims with spaces (`summarizer._summary_text`), and nothing strips
   markdown/decorative chars, so `**Goal:** … — … ## ✓` leaks into the short display.
2. **New sessions don't appear on the board.** The board lanes render only from
   `effort_history`; live managed sessions (`session_registry`) render only in the
   separate top strip. A started session never shows in its lane column — the user
   loses the at-a-glance "what's in each lane" view. (Brownfield-discovered artifacts
   *do* appear, because `adopt_discovered` writes effort records — the bridge to reuse.)
3. **Sessions aren't summarized until viewed.** Session summaries are lazy/on-view
   (proactive only on `rescan`), so a freshly-finished session has no summary to restart
   from and no blurb for its tile.
4. **No general terminal.** Every terminal is tied to a trio skill (research→
   researchPrime, plan→Crucible, build→Foreman) or grass; there's no plain "talk to the
   project" terminal.

## Locked decisions (Stage 0 user gates)

1. **#1 short + clean (decided).** Add a plain-text normalizer that strips markdown +
   decorative glyphs from any *short displayed* summary, and cap length (objective ≈ 1
   sentence; per-tile blurb ~8–12 words). Keep generate-twice + grounding. Full markdown
   only on the `/summary` page.
2. **#2 = Option B (approved):** session tiles in BOTH places. The top active strip
   stays for *currently-running* sessions; AND every session appears as a tile in its
   **lane column** on start and persists when done — newest prominent, older under an
   openable "previous sessions" expander (the v6 pattern), each with a short blurb. A
   live session may appear in both the strip (while running) and its lane column; that's
   accepted.
3. **#3 summarize-on-finish (decided).** Proactively generate + cache a session summary
   when the session reaches a terminal state (the existing kill/close/reconcile-dead
   transitions), reusing the validated summarizer seam. The lane-tile blurb is derived
   from this cached summary (short + clean per #1). Honest placeholder when none yet.
4. **#4 = Option B (approved):** a top-of-dashboard **"Open terminal"** button (NOT a
   6th board lane) that starts a **bare general session** (no skill seed) with the
   Claude/Gemini engine toggle, opens a window, and rides the top active strip. General
   sessions are reachable/restartable via the registry + strip; they do not get a
   dedicated board lane column.
5. **Verification standard (non-negotiable, the v4 lesson).** Every UI wave's "GREEN" =
   rendered-DOM assertions (positive + negative) + a real Playwright/Chromium interaction
   test + an orchestrator screenshot checked against `_mockups/rnd-v7/board_integration.html`
   + the user's sign-off before merge. String-grep gate = automatic HALT.
6. **Scope = one build** on `C:\dev\Anchor`, every wave GREEN on `python -m pytest -v`.
   Branch `foreman/rnd-surface-v7`. No merge to master / no service restart without
   John's sign-off.

## Out of scope (inclusion test — bloat / later)

- Calendar integration, the app-builder version, floating windows (carry the v6
  fences).
- A dedicated **board lane** for the general terminal (John chose the button, B).
- Re-architecting the summarizer or the board render — v7 **extends** them.
- Cross-project board/strip views; multi-user.

## Hard constraints (from CLAUDE.md — non-negotiable)

- **Python stdlib only** (+ lazy `pywinpty` in `pty_manager.py`). **Playwright is
  DEV-ONLY** (`pytest.importorskip`), never in product code; `distro.py` scan stays green.
- **Never bind/touch `:8777` or real data in tests/healthcheck.** Model calls via
  `tests/fake_claude.py` / `tests/stub_streamjson.py` (`ANCHOR_RUNNER_CMD`); PTY via the
  stub backend (`ANCHOR_PTY_BACKEND=stub`); previews on an OS-assigned port `!= 8777` +
  isolated temp `ANCHOR_DATA_DIR`.
- **All mutating / terminal endpoints** behind the `do_POST` token gate; GET read-only
  (token via `?token=`).
- **f-string brace discipline** in `anchor_gui.py` (`_PROJECT_WINDOW_JS` is a RAW
  single-brace string; doubled braces in f-string HTML/CSS).
- **Reuse, don't fork:** `summarizer.py`, `effort_history.py`, `session_registry.py`,
  `terminal_session.py`, `handoff.py`, `sessions.py`, the v6 board/tile/blurb seams.
  **Mirror** new read seams into `anchor.py`; **extend** `anchor_healthcheck.py`
  (`check_rnd_v7_surface`, fully stubbed); **update** `CLAUDE.md`.
- **Scoped commits only** — never sweep runtime-data churn.

## Risks & mitigations

- **R1 — double-rendering / dedupe.** A live session could appear twice in the lane
  column (registry-sourced + an effort record) or fight the top strip. Mitigation:
  bridge live sessions into the board with a **stable id** keyed on session_id and
  **dedupe** against effort-sourced sessions; the strip is a separate, intentional
  view. Test: a started session shows exactly once per lane column + (while running) in
  the strip; no duplicate tiles.
- **R2 — board now needs live registry data → render slowdown / model calls.** The
  board must stay a **cache/registry-only read** (no model call on render); the blurb
  comes from the cached session summary (#3) or an honest placeholder. Test: render
  makes no model call; missing summary → placeholder, not a blank/garbage.
- **R3 — summary normalizer over-strips** (mangles legitimate text). Mitigation: strip
  only markdown control chars + a defined decorative-glyph set; collapse whitespace;
  preserve words/numbers/normal punctuation. Test: a claim with `**`, `—`, `##`,
  backticks, `✓` → clean readable text; a normal sentence is unchanged.
- **R4 — summarize-on-finish storms / blocks the kill path.** Generation must be
  **background + best-effort** (never block close/kill; never poison cache on failure);
  idempotent (don't regenerate a cached one). Test: finishing a session schedules one
  background summary; the kill response is not blocked; a failed gen leaves no cache.
- **R5 — general (bare) session breaks lane-keyed code.** A general session has no trio
  lane; it must not be misfiled into research/plan/build or break chain/summary code.
  Mitigation: a dedicated lane value (e.g. `general`) that is bare (no `LANE_SKILL`),
  excluded from the trio board columns and the auto-advance chain. Test: a general
  session starts bare, appears in the strip, is summarizable, and never auto-advances.
- **R6 — another vacuous UI gate.** Decision 5 (DOM + Playwright + screenshot + sign-off)
  mandatory per UI wave.

## Definition of done (project)

All waves GREEN on `python -m pytest -v` AND: short displayed summaries are capped +
glyph-clean (full markdown only on the summary page); every session appears as a tile in
its lane column on start and persists when done (newest prominent + openable "previous"
expander + short blurb) while the top active strip still shows live ones; each session is
summarized on finish (background, honest when absent, no render-time model call) and that
summary feeds the tile blurb + restart seed; a top "Open terminal" button launches a bare
general session (engine toggle, window, strip) that never misfiles into a trio lane or
auto-advances; the CLI/healthcheck/distro/docs mirror the new seams; and every UI wave is
verified by Playwright + a screenshot + John's sign-off before merge.
