# foreman.config

*Lane: build · validated, cached summary*

**When run:** 2026-06-13

**What was asked:** foreman.config

## Actions & files produced

- foreman.config

**Effort:** imported — no run metrics

## What was built & errors overcome

- ## Session Summary â€” `foreman.config`
- **Project under build:** `anchor-rnd-surface-v6` â€” the "Linked Pipeline" R&D control surface, building on the merged v5 "Durable Work" surface; originated from John dogfooding the cockpit.
- **Build configuration / docs:** Design = `planning/rnd-v6/MASTER-PLAN.md`; plan = `planning/rnd-v6/IMPLEMENTATION-PLAN.md`; execution log = `planning/rnd-v6/EXECUTION-LOG.md`. Test command = `python -m pytest -v`.
- **Build environment:** cwd = repo root `C:\dev\Anchor`, on branch `foreman/rnd-surface-v6` (off master; base commit = the cherry-picked summarizer stream-json parse fix `1bd8b85`).
- **Scope â€” 8 waves:** (1) summaries that work (land the stream-json parse fix + informative content + regression stub + schema-version cache heal); (2) session linkage backbone (`parent_session_id` + `chain_id`, `chain_for`/`chain_members`, generic handoff stage edge); (3) maximize + free-resize stacked panels with xterm re-fit; (4) tile lifecycle (new-sessionâ†’new-tile, persistent finished tiles, `term_sessions` projection includes terminal sessions); (5) manual researchâ†’planning advance via `POST /api/rnd/advance_session` + chain breadcrumb; (6) automatic planningâ†’build advance gated on a real MASTER+IMPL plan set, idempotent one-build-per-planning; (7) main dashboard reflects project activity (cache-only render); (8) CLI mirror (`rnd chain`) + `check_rnd_v6_surface` healthcheck + distro scan + docs (project done).
- **Locked user decisions:** windows STACKED (not floating); new-session always mints a new tile; researchâ†’plan is MANUAL on click; planâ†’build is AUTOMATIC only when a real plan exists; finished tiles are KEPT (newest-prominent + "previously done" group); chain is durable, traversable, with a breadcrumb.
- **Out of scope:** calendar integration, app-builder version, floating windows.
- **Mandatory UI verification (the v4 lesson, Waves 3â€“7):** rendered-DOM (positive + negative) + a real Playwright/Chromium interaction test + an orchestrator screenshot-vs-mockup (`_mockups/rnd-v6/session_pipeline.html`) + user sign-off before merge; a string-grep-only gate is an automatic HALT.
- **Test/safety discipline:** Playwright is DEV-ONLY (`pytest.importorskip`), never in product code; all model/PTY calls go through `tests/fake_claude.py` + `tests/stub_streamjson.py` + stub PTY (`ANCHOR_PTY_BACKEND=stub`) via `ANCHOR_RUNNER_CMD` â€” never live `claude`/`gemini`/real-PTY/`:8777`/real data; spawned previews bind an OS-assigned port HARD-guarded `!= 8777` with an isolated temp `ANCHOR_DATA_DIR`; `pywinpty` is the only native-dep waiver (lazy, `pty_manager.py` only).
- **Code-shape constraints:** `anchor_gui.py` HTML is f-string-generated (double braces); `_PROJECT_WINDOW_JS` is a RAW single-brace string.
- **Deploy gate:** NO merge to master and NO `nssm restart` until John signs off; then merge + `nssm restart anchor` (elevated) + rescan each project to heal summaries.

## Files

- [foreman.config](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=foreman.config.json)
