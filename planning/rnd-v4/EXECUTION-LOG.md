# Anchor R&D Surface v4 — "Project Cockpit" — Execution Log

> Foreman appends per-wave EXECUTE / REVIEW / FIX / JUDGE history here. Seeded by
> Crucible at handoff 2026-06-12. Frozen design: `MASTER-PLAN.md` +
> `IMPLEMENTATION-PLAN.md` (this folder).

## Handoff (Crucible → Foreman) — 2026-06-12

- Design locked by the user across three review rounds; canonical spec =
  `_mockups/project_window_proposals.html` (Paradigm 2) +
  `_mockups/branding_proposals.html` (Option B).
- Terminal substrate proven by `_prototypes/term_harness/` (real ConPTY × WebSocket
  × xterm.js; `pty_smoke.py`, `ws_client_test.py`, `claude_interactive_capture.py`
  all pass).
- 9 waves, terminal wave = Wave 9. test-command: `python -m pytest -v`.

<!-- Foreman: append wave records below this line -->

## Wave 1 — One terminal substrate: skill auto-load-once + greet-once — ✅ GREEN

- **EXECUTE:** added per-lane skill-seed map (research→researchPrime · plan/planning→Crucible · build→Foreman) + `seed_for_lane()` (env-overridable) in `terminal_session.py`; `start_session` writes the seed as exactly ONE stdin turn after PTY launch and records `seeded`/`seed_text` (new fields in `session_registry.py`, normalized + atomic). New `tests/test_terminal_seed.py` (11 tests).
- **REVIEW (refute):** items 1–4 VERIFIED (seed-once integrity, no test-weakening, lane→skill map, persistence). **MAJOR-CONCERN:** Done-when "no rnd_terminal in cockpit wiring" unmet — `anchor_gui.py` lane "+ New run" still wired the unseeded v2 REPL (`openTerminal`/`start_terminal`).
- **FIX iter 1:** repointed the cockpit lane-launch affordance to the seeded path (`newTermSession`→`/api/rnd/term_start`); added `tests/test_cockpit_substrate.py` (asserts seeded wiring, no `start_terminal` in lane launch); updated 3 existing tests that encoded the old buggy wiring (legitimate — same structure/guards, repointed to `newTermSession`).
- **GATE (orchestrator-run):** `python -m pytest -q` → **542 passed, 1 skipped** (baseline 529 + 13 new; the skip is a pre-existing host symlink/git skip). No test weakened. Converged in 1 fix iter.

## Wave 2 — Engine persistence + toggle — ✅ GREEN

- **EXECUTE:** `terminal_session.py` — `last_engine_for_project`/`set_last_engine_for_project` (persist to `.anchor/projects/<id>/engine.json`, atomic under WRITE_LOCK, default `claude`); `start_session` defaults backend to the project's last engine (`_UNSET` sentinel) + records it on success; `switch_engine(session_id, engine)` reaps the PTY and rebinds a new one under the SAME session_id+worktree (policy-checked via existing `lanes.check_engine_allowed` BEFORE reaping; rollback to a consistent record on failure). `POST /api/rnd/term_set_engine` in `do_POST` behind token auth (400 invalid-engine / 404 unknown-session). New `tests/test_engine_persist.py` (12 tests).
- **REVIEW (refute):** **GO** — all 5 items VERIFIED via live repros (orphan-safety: exactly one PTY, worktree reused; rollback leaves status=idle + prior backend; policy refusal uses canonical `lanes` source, no scope creep, leaves running session intact; persistence defaults on missing/corrupt; endpoint auth + validation). `git diff --stat tests/` empty — no existing test modified/weakened.
- **GATE (orchestrator-run):** **554 passed, 1 skipped** (+12 new). Converged in 0 fix iters.

## Wave 3 — Per-lane doc roles + cost/tokens/time rollup (data layer) — ✅ GREEN

- **EXECUTE:** `summarizer.session_doc_roles(pid, lane, session_id)` — per-lane role→doc map (research: exec/report/agent/provenance · planning: master/impl/northstar · build: northstar/deliverable/execlog/plan), hrefs via existing `/report` + `/artifact` routes (same URL-quoting as `_member_links`), absent roles omitted. `effort_history.project_effort_rollup(pid, window, now)` — sums `attach_cost` records for RUN-provenance sessions only (imported/discovered → 0), 30d via injected `now` (finished_at else created_at, boundary-inclusive). Lazy `import sessions` to avoid the sessions↔effort_history cycle. New `tests/test_doc_roles.py` (8) + `tests/test_effort_rollup.py` (7).
- **REVIEW (refute):** **GO** — all 5 VERIFIED via repros: rollup field-extraction matches the real `attach_cost` shape (no phantom fields), run-only + discovered-skip double guard, 30d cutoff correct, doc-role hrefs use real routes + omission, lazy import dodges a real cycle, no fork. `git diff tests/` clean (2 new files only); no `anchor_gui.py` change (data-layer honored).
- **GATE (orchestrator-run):** **569 passed, 1 skipped** (+15 new). Converged in 0 fix iters.

## Wave 4 — Paradigm 2 project window: lane tiles + lights + inline expanding panels — ✅ GREEN

- **EXECUTE:** `anchor_gui.py` — removed the v3 floating window manager (`.termwin`/`.winlayer` CSS+DOM; JS `openSessionWindow`/`_toggleMinimize`/`_closeWindow`/`killSession`/`_wireDrag`/`_wireResize`/`WINDOWS`/`_winZ`); added the Paradigm-2 inline accordion: `.lane-tile` with status lights (`.lt green/amber/red/grey`), a `.panel-stack` host, and JS `openPanel`/`minimizePanel`(keeps session running)/`killPanel`(confirm-gated `term_kill`)/`repopulate`(reads `/api/rnd/term_sessions`)/`laneTileClick`. New Python `_session_light_class`. Seeded launch (`newTermSession`→`term_start`) + all transports preserved. New `tests/test_cockpit_render.py` (9); adapted `test_window_manager_markup_present` to the inline DOM.
- **REVIEW (refute):** **GO** — critical dangling-reference sweep clean (no removed symbol survives in a real 60 KB render; all new symbols defined; `loadSessions`→`repopulate` deferred-handler ordering safe); brace hygiene verified on a live render (no leaked `{{`/`}}`); test adaptation preserved + ADDED negative assertions, no drops/skips; `_session_light_class`/JS `_statusColor` share the locked session_registry buckets. Nits only (stale comment; two green hexes for two elements).
- **GATE (orchestrator-run):** **578 passed, 1 skipped** (+9 new). Converged in 0 fix iters.

## Wave 5 — Panel internals: stacked summary (equal-height split) + resizable terminal — ✅ GREEN

- **EXECUTE:** `anchor_gui.py` — `openPanel` now builds a stacked body: split summary on top (`.smat` materials left from `/api/rnd/session_summary` · `.slinks` role links right from Wave-3 `session_doc_roles`, both columns equal-height via `margin-top:auto` + grid `align-items:stretch`) and a full-width `.tpane` terminal below (`_mountTerminal` reused; `resize:vertical` + `_wirePanelResize`→`_fitPanelTerminal`→`term_resize`). New token-gated read-only GETs `/api/rnd/session_doc_roles` + `/api/rnd/project_rollup`. Header shows `Σ tokens · $ · time · N sessions` (`render_header_rollup_html`, real `project_effort_rollup` lifetime) + a lifetime/30d toggle. New `tests/test_panel_render.py` (12).
- **REVIEW (refute):** **GO** — live repros: 73 KB render with zero `{{`/`}}` leaks; both endpoints 401-on-no-token + 400-on-traversal, call the real Wave-3 fns; resize functional (POSTs `term_resize`); equal-height CSS matches the mockup; rollup run-only/honest; `git diff` source = anchor_gui.py only, test file new, nothing weakened. Cosmetic dead `p.fit` branch noted (working path unaffected).
- **GATE (orchestrator-run):** **590 passed, 1 skipped** (+12 new). Converged in 0 fix iters.

## Wave 6 — Grass Catcher idea board + promote-to-lane — ✅ GREEN

- **EXECUTE:** `terminal_session.py` — `seed_for_lane(lane, seed_context=None)` + `start_session(..., seed_context=None)` fold the idea onto the Wave-1 lane seed as ONE opening turn (None = byte-identical to Wave 1). `effort_history.promote_grass_to_lane(pid, idea_id, lane)` + `get_grass_idea` delegate to `start_session(seed_context=idea)` (copy, never destroys). `anchor_gui.py` — `_render_grass_board` (idea cards + source chips + →Research/→Plan), `promoteGrass` JS (POST→register→`openPanel`), `POST /api/rnd/promote_grass`. New `tests/test_grass_board.py` (11).
- **REVIEW (refute):** **GO** — seed-once regression check passed (idea-in-buffer count stays 1 through attach/input/re-read; seed_context=None identical to Wave 1); copy-not-move verified by repro; endpoint 401-before-logic + lane allow-list {research,plan} (400 on build/grass); render has 0 brace leaks + grass board present; no existing test modified/weakened.
- **GATE (orchestrator-run):** **600 passed, 1 skipped** (+10 new). Converged in 0 fix iters.

## Wave 7 — Deliverable launch-by-type — ✅ GREEN

- **EXECUTE:** `deliverables.py` — `TYPE_TOOL`/`TYPE_SERVICE`, `verify_skill_or_tool` (pure filesystem existence → available/loaded/missing, NO spawn), `get_pinned_deliverable`, `launch_deliverable(...)` dispatching skill/tool→verify · service→`preview_server.start_preview` (free port ≠ 8777, isolated temp data dir, loopback, health-check; pull-up-if-running via `list_previews`+reap) · program→`run_deliverable` · doc→`/artifact` rendered href. `POST /api/rnd/launch_deliverable` + per-type `launchDeliverable` JS. New `tests/test_deliverable_launch.py` (11).
- **REVIEW (refute):** **GO** — safety-critical never-8777 verified (pick_free_port guard; tests use `_StubPreview`, the one real server is OS-assigned ephemeral asserted ≠ 8777 + torn down in `finally`, no leak); skill/tool no-spawn (pure `.is_dir()`/`.exists()`, repro crucible→available/bogus→missing); pull-up reaps-then-matches (no dead URL); endpoint 401-before-dispatch + 404 + 400-not-500; 0 brace leaks; existing deliverable tests untouched.
- **GATE (orchestrator-run):** **611 passed, 1 skipped** (+11 new). Converged in 0 fix iters.

## Wave 8 — Main-dashboard rows (drop directory) + masthead rollup + Option B branding — ✅ GREEN

- **EXECUTE:** `anchor_gui.py` — `_render_folder_groups` flattened to a one-line row list (no `rnd-folder-head` path header; path lives on the project-window header from Wave 5); `render_project_tile_html` rows gained the `Σ tokens·$·time` rollup (real `project_effort_rollup` lifetime, shared `_fmt_rollup_line`, try/except); global lifetime/30d toggle (`_render_rows_rollup_toggle` + `rndRowsRollupWindow` → token-gated `/api/rnd/project_rollup`); Option B `.masthead` lockup (Anchor · divider · GWL mark+wordmark · "Powered by NextGen Nuclear ☢" pill). New `tests/test_dashboard_rows.py` (10); adapted `test_two_projects_one_folder_render_grouped` (intent tightened: both projects still render, no path header).
- **REVIEW (refute):** **GO** — directory line gone with NO project dropped (5 rows; 3-in-1-folder → 3 rows); rollup honest (run-only) + zero-session renders `Σ 0` not a crash; 231 KB full-page render with 0 brace leaks; masthead complete + all 3 brand `<img>` resolve to the single vendored svg; favicon wired; adapted test preserves+tightens intent, no skip.
- **GATE (orchestrator-run):** **621 passed, 1 skipped** (+10 new). Converged in 0 fix iters.

## Wave 9 — CLI mirror + healthcheck v4 surface + distro scan + docs — ✅ GREEN (PROJECT DONE)

- **EXECUTE:** `anchor.py` — 4 read-only `rnd` subcommands (`rollup`/`doc-roles`/`deliverable-type`/`engine`) delegating to the shared modules (no fork). `anchor_healthcheck.py` — `check_rnd_v4_surface` (fully stubbed: ANCHOR_PTY_BACKEND=stub + fake_claude + temp worktree/skills/seed + temp git project; walks seed-once · engine-switch · doc-roles · rollup · grass-promote · skill-verify-no-spawn + stub service launch on a free port ≠ 8777; kills sessions, restores env, tears down) wired into `main()`. `CLAUDE.md` — v4 "Project Cockpit" section + 5 API rows + 4 CLI subcommands. New `tests/test_cli_v4.py` (7) + `test_healthcheck_v4.py` (4) + `test_distro_scan_v4.py` (5).
- **REVIEW (refute):** **GO** — CLI delegates to real fns (ran all 4 live); healthcheck safe by empirical before/after (registry 23→23, sessions 3→3, previews unchanged; never :8777; no PTY/worktree/preview leak); distro scan non-vacuous (proven to flag numpy/misplaced winpty; allowlist locked to `{winpty: pty_manager.py}`); CLAUDE.md claims all verified against code; no existing test weakened.
- **GATE (orchestrator-run):** **637 passed, 1 skipped** (+16 new) · `python -m distro` → **scan clean (110 files)** · v4 healthcheck GREEN stubbed. Converged in 0 fix iters.

---

## PROJECT DONE — 2026-06-12

All 9 waves GREEN on `python -m pytest -v` (terminal wave = 9). Tests 529 → **637 passed, 1 skipped** (+108 new across the build; the skip is a pre-existing host symlink/git skip). Distro import-scan clean (only the declared lazy `pywinpty` exception). Branch `foreman/rnd-surface-v4`, 9 wave commits. Plan-level acceptance gate (Master Plan "Definition of done") met: Paradigm-2 cockpit with inline panels + resizable terminals; one seeded terminal substrate; engine persist+toggle; grass idea board; deliverable launch-by-type (never :8777); flat rows; lifetime/30d rollup; Option B branding; CLI mirror; v4 healthcheck; docs.

---

## REVISION rnd-v4.1 — "Cockpit render (for real)" — 2026-06-13

**Defect found in production (post-merge):** the dashboard updated but the per-project window still rendered the OLD v3 effort-card kanban — for ALL projects, in incognito, and for brand-new ones (so not a cache issue). Root cause (Crucible "shark" review, confirmed at source + by live render): Wave 4 only **wrapped** the old `_render_effort_card` kanban in a `lane-tile` div and the inline panel was **unreachable** — `laneTileClick` swallowed clicks on the effort/`<a>` body, and `openPanel` early-returned for any session not in `MANAGED` (live terminals only), i.e. every historical/discovered session. **Why the v4 gate missed it:** the UI "tests" were string-greps (asserted `lane-tile`/`panel-stack`/`openPanel` existed in CSS/JS; `termwin` absent) — they never asserted the RENDERED BODY became Paradigm 2, that the old kanban was REMOVED, or that a click OPENS a panel. No incognito/visual check.

**Fix (branch `foreman/rnd-v4.1-cockpit`):** rewrote `_render_kanban_html` (→ `.p2lanes`/5×`.p2col`, old `.kan`/`.col-cards` removed), `_render_lane_sessions`/`_render_lane_tile` (genuine Paradigm-2 `.tile` schema; no report links/summary accordions/files expanders on the tile; previous sessions as tiles), added `_render_deliverable_lane_tiles` (launch-by-type); fixed `laneTileClick` (reaches `openPanel`) and `openPanel` (accepts historical/discovered/imported ids — synthesizes a panel record, renders the split summary from `session_summary` + `session_doc_roles`, read-only body for done sessions / live xterm for running); CSS → mockup tile rules. `_render_effort_card` retired from the lane (kept for other routes).

**HARDENED, un-gameable gate (`tests/test_cockpit_paradigm2.py`, authored by the orchestrator):** DOM-parsed (style/script stripped) structural assertions — positive (lane board IS `.p2lanes`/5 `.p2col` with `.tile` schema) + negative (`_assert_no_old_lane_markers`: no `kan`/`col-cards`/`effort`/`session-summary-link`/`openReport`/`termwin` in the body) on multi-lane, **zero-session**, and **imported-only** projects; plus a **real Playwright + Chromium** test that clicks a HISTORICAL tile and asserts the inline panel opens AND populates (≥1 real `.slinks` doc link) with **no JS console errors**. Playwright is a dev-only test dep (`pytest.importorskip`), not shipped — distro scan unaffected.

**GATE (orchestrator-run):** `tests/test_cockpit_paradigm2.py` 5/5 (incl. Playwright click→panel); full suite **643 passed, 1 skipped**. Independent adversarial review: **GO** (live Chromium: historical tile → non-empty summary + 2 doc links; live tile → xterm mounts; no console errors; `/report` route intact). **Pending: user incognito visual sign-off → merge to master.** Lesson recorded: UI "done" = rendered-structure assertions + a real click test + human visual sign-off — never a string grep.
