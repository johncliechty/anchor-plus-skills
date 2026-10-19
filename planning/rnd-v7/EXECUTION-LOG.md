# Anchor R&D Surface v7 — "Integrated Board" — Execution Log

> Per-wave EXECUTE / REVIEW / FIX / GATE history for the Foreman build of v7. Frozen
> plan: `MASTER-PLAN.md` + `IMPLEMENTATION-PLAN.md` (this folder). Branch:
> `foreman/rnd-surface-v7` (off master `5ae3c2e`, which has v6 merged).

## Baseline

- **2026-06-15** — Branch `foreman/rnd-surface-v7` created off master (v6 merged).
  v6 baseline = **816 passed, 1 skipped**. This is the GREEN floor; every wave holds or
  grows it.

## Wave records

### Wave 1 — Short, clean summaries (normalizer + caps) — GREEN (2026-06-15)

**Built (backend):** `summarizer.short_summary_text(in, max_chars=140)` + `tile_blurb(in,
max_chars=64)` (+ private `_strip_markdown_controls`/`_strip_decorative`/`_normalize_plain`/
`_coerce_summary_input`). Strips markdown (`** __ ~~ `` ` `` `, headings, list markers,
`[t](u)`→`t`, blockquotes; standalone inline `#…` but preserves `C#`) and a decorative
glyph set (`✓ → ☢ • ● ▼ ⋮ …` + generic Unicode symbol/control/format categories → emoji +
box-drawing), normalizes dash family → `-`, collapses whitespace, word-boundary cap with
`…`. A clean in-cap sentence is returned UNCHANGED (apostrophes/quotes/parens/digits/`?`
preserved). Applied at the two SHORT objective sites (home row `_project_summary_text` +
project-window header); the `/summary` full markdown is untouched. `tile_blurb` added +
unit-tested for Wave 3.

**Orchestrator verification:** `tests/test_summary_shorten_v7.py` (16) — each glyph/markdown
class stripped while words survive; clean sentence unchanged; word-boundary truncation;
render sites use it (glyph-laden cache → clean); `/summary` markdown still intact. v6
guards (`test_summary_content_v6`, `test_dashboard_reflection_v6`) stay GREEN.

**Gate:** **831 passed, 1 skipped** (+15). Backend-only (no UI structure change). Commit:
scoped.

<!-- WAVE 1 done -->
### Wave 2 — Summarize each session on finish — GREEN (2026-06-15)

**Built (backend):** `_trigger_session_summary_on_finish` (non-blocking, idempotent,
best-effort wrapper over the Wave-6 background daemon) wired into the three finish
transitions: `term_kill` (killed session), `finish_to_build` (finished planning session,
only when a plan set exists), and the `term_sessions` reconcile-dead path (iterates
`reconcile_and_advance` → `report.reconcile.marked`, schedules each). Each hook is its own
try/except, runs before the response, never blocks it; idempotent (skips if cached); a
failed runner leaves no cache (summarizer FIX 2). Added `summarizer.session_blurb(...)` —
pure cached read → `tile_blurb`(first grounded claim → what_was_asked → title), honest
`""` when uncached, never a model call. Gated by `_PROACTIVE_SUMMARY_ENABLED` (off in
tests unless opted-in; on in the live server).

**Orchestrator verification:** `tests/test_summary_on_finish_v7.py` (+ `tests/stub_fail_runner.py`)
— kill schedules exactly one background summary + non-blocking + idempotent; injected raise
still 200s; failed runner → no cache; `session_blurb` clean/capped/honest-absent + no model
call; finish_to_build + reconcile-dead end-to-end + wiring guards. v6 guards
(`test_v6_polish`, `test_auto_advance_plan_to_build`, `test_summary_content_v6`) GREEN.

**Honest note:** a killed live-PTY session with no effort members is grounding-empty (cached
but `session_blurb`="" until real members exist) — intended; Wave 3 shows running intent
until a summary lands.

**Gate:** **840 passed, 1 skipped** (+9). Backend-only. Commit: scoped.

<!-- WAVE 2 done -->
### Wave 3 — Live sessions integrated into the lane columns — GREEN (2026-06-15)

**Built (UI):** Bridged live `session_registry` sessions into the board lane columns in
`_gather_project_sessions` — `_registry_session_view` (SAFE: session_id/lane/status/label/
created_at only) + `_merge_registry_sessions` (dedupe by session_id via `_strip_session_prefix`
collapsing `run::<sid>`→`sid`; newest-first; on a hit keep the richer effort view but adopt
the live status; on a miss append a synthetic view). Lane map: research/plan(planning alias)/
build/deliverables; **general + grass excluded** from trio columns. Added a `.blurb` line to
`_render_lane_tile` — `summarizer.session_blurb` (cache read) for finished sessions, else a
short `tile_blurb` of the intent for running ones; honest empty. Top strip unchanged. Board
render stays cache/registry-only (no model call).

**Orchestrator verification:** `tests/test_board_live_integration_v7.py` — DOM (live session
→ one green tile in its column; planning alias; general excluded [negative vs v6]; dedupe one
tile per id; newest prominent + older under `prev-sessions`; clean short blurb) + no-model-call
spy + Playwright (start plan session → tile in `#cards_plan` + chip in `#sessionBar`; finish +
newer + reload → stays grey under expander). **Screenshot reviewed** — `_devtest/wave3_board.png`:
"PLAN / session / running · now" tile in the Planning column + "● plan 1" strip chip. Matches
mockup #2.

**Honest nuance (flagged for John):** the board is server-rendered, so a started session's
lane-column tile appears on the next render (reload/rescan); the **top strip is the instant
view**. A small follow-up (a board-fragment refresh endpoint called from `newTermSession`)
could make the lane-column tile appear instantly without a reload — offered, not built.

**Gate:** **848 passed, 1 skipped** (+8). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 3 done -->
### Wave 4 — "Open terminal" general session button — GREEN (2026-06-15)

**Built (UI + backend):** `terminal_session._valid_lanes` now accepts `general` (one line);
`general` has NO `LANE_SKILL` → `seed_for_lane` returns None → BARE PTY (like grass). An
"⊞ Open terminal" button in the project-window header `.right` div launches `newTermSession('general','claude')`
→ bare session, inline panel, top-strip chip, per-panel Claude/Gemini toggle. `general` is
NOT in `_REGISTRY_LANE_TO_COLUMN` (excluded from trio board columns — no `cards_general`) and
not in `_PLANNING_LANES` (never auto-advances). grass unchanged.

**Orchestrator verification:** `tests/test_general_terminal_v7.py` (10) — backend (general
valid + bare/no-seed vs research seeded; excluded from board columns + chain; killing a
general session with a plan set → no build) + DOM (button present; NO general board column —
negative) + Playwright (click → general chip + panel + no trio tile; no console errors).
**Screenshot reviewed** — `_devtest/wave4_general.png`: the "Open terminal" header button, the
5-column board (no general column), and an opened "general 1 · claude" bare panel + strip chip.
Matches choice B.

**Flagged for John:** Gemini is research-only by current engine policy, so toggling a general
session to Gemini surfaces a clean refusal (not a crash). If you want the general terminal to
allow Gemini, that's a one-line policy tweak — say the word.

**Gate:** **858 passed, 1 skipped** (+10). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 4 done -->
### Wave 5 — CLI mirror + healthcheck v7 + distro + docs — GREEN (2026-06-15) — PROJECT DONE

**Built:** `anchor.py` `rnd blurb <pid> --lane --session` → `summarizer.session_blurb`
(read-only, cache-only, honest "(no summary yet)"). `anchor_healthcheck.check_rnd_v7_surface`
(fully stubbed: stub PTY + stream-json stub runner + temp worktree base + temp git project):
walks (a) the normalizer (glyph/markdown stripped + clean-unchanged); (b) summarize-on-finish
(kill → cached summary + clean `session_blurb`); (c) the board bridge (live registry session
deduped into its lane column; `general` excluded from trio columns); (d) the bare `general`
lane (no seed, never advances) — reaps PTYs + temp dirs, restores all env, never `:8777`.
`distro.py` unchanged (scan already clean). `CLAUDE.md` gains a full v7 "Integrated Board"
section (module block + API rows + `rnd blurb` CLI + general-lane note). Avoided the
secrets-scanner trip (benign test token).

**Orchestrator verification:** distro re-run → **clean (138 files; sole pywinpty exception;
no Playwright in product code)**; `rnd blurb` in the CLI usage; CLAUDE.md v7 section present.
21 new tests (cli 8 + healthcheck 7 + distro 6).

**FINAL GATE:** `ANCHOR_PTY_BACKEND=stub python -m pytest -q` → **879 passed, 1 skipped**
(+21; +63 over the 816 v6 baseline). Commit: scoped.

---

### Wave 6 — polish (instant-in-column board refresh + Gemini on general) — GREEN (2026-06-15)

**Built (the two flagged follow-ups):** (1) **instant-in-column** — `GET /api/rnd/board_html`
(token via `?token=`, SAFE) returns `_render_kanban_html`; the board is wrapped in
`#kanbanBoard`; a new `refreshBoard()` (in `_PROJECT_WINDOW_JS`) GETs it and swaps the
container in place, wired into all 7 board-changing lifecycle calls (`newTermSession`,
`promoteGrass`, `developGrass`, `advanceSession`, `finishToBuild`, `killPanel`, `repopulate`).
Server stays the single source of truth (JS re-fetches, never injects) → exactly one tile, no
dup. So a started session's lane-column tile now appears WITHOUT a reload. (2) **Gemini on
general** — `lanes.GEMINI_LANES = {research, general}` (was research-only); `check_engine_allowed`
now permits Gemini on a general session; plan/build still refuse.

**Orchestrator verification:** `tests/test_v7_polish.py` (9) — board_html token-gated + SAFE +
404; `#kanbanBoard` wraps the grid; `refreshBoard` wired in all 7 fns; Playwright — click "+ New
plan run" → tile in `#cards_plan` WITHOUT reload, exactly one, no console errors; engine policy
(gemini on general+research, refused plan/build). **Screenshot reviewed** —
`_devtest/wave6_instant.png`: planning-column tile appears live after the click. 

**Gate:** **888 passed, 1 skipped** (+9). Commit: scoped.

---

## PROJECT DONE (2026-06-15) — John signed off ("keep going") → MERGED + PUSHED

All 5 waves GREEN. Branch `foreman/rnd-surface-v7` (off master `5ae3c2e`). Full suite **879
passed, 1 skipped**. **NOT merged, service NOT restarted** — UI waves (3–4) await John's
sign-off (screenshots under `_devtest/`), then: merge → `nssm restart anchor` (elevated) →
rescan to heal summaries.

**Wave tally:** W1 short-clean summaries (831) · W2 summarize-on-finish (840) · W3 live
sessions in lane columns (848) · W4 "Open terminal" general session (858) · W5 CLI/healthcheck/
distro/docs (879).

**Open items flagged for John:** (1) Wave 3 — the lane-column tile appears on next render
(reload/rescan); the top strip is the instant view; a board-fragment refresh from
`newTermSession` would make it instant-in-column (offered, not built). (2) Wave 4 — Gemini is
research-only by policy, so toggling a general session to Gemini surfaces a clean refusal; a
one-line policy tweak would allow it. (3) #1 summaries only fully heal after a rescan post-deploy.
