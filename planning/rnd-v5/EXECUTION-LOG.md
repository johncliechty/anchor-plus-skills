# Anchor R&D Surface v5 — "Durable Work" — Execution Log

> Foreman appends per-wave EXECUTE / REVIEW / FIX / GATE history here. Seeded by
> Crucible at handoff 2026-06-14. Frozen design: `MASTER-PLAN.md` +
> `IMPLEMENTATION-PLAN.md` (this folder).

## Handoff (Crucible → Foreman) — 2026-06-14

- Builds on the merged v4.1 "Project Cockpit" + the terminal fixes (full-width fit,
  Ctrl+V paste, no-freeze pump).
- 6 waves, terminal wave = 6. test-command: `python -m pytest -v`.
- Grass design = the approved B+C hybrid (`_mockups/grass_catcher_refined.html`).
- **Verification is mandatory per UI wave:** rendered-DOM (positive+negative) +
  a real Playwright/Chromium interaction test + an orchestrator screenshot vs the
  mockup + user sign-off before merge. A string-grep gate is an automatic HALT.
  (Playwright is installed as a dev-only test dep; `pytest.importorskip`.)

<!-- Foreman: append wave records below this line -->

## Wave 1 — Run lifecycle: close-to-tile vs. deliberate hard-kill — GREEN (2026-06-14)

- **EXECUTE** (fresh sub-agent): panel header rebuilt to THREE distinct controls
  (`–` minimize · `×` CLOSE close-to-tile · `🗑` KILL, confirm-gated → term_kill).
  Re-added `#sessionBar` as the reopen vector for LIVE managed sessions (not
  server-rendered board tiles); `closePanel` (non-killing) vs `killPanel`
  (confirm + term_kill + `_removeSessionTile`); `renderSessionBar` rebuilds
  reopenable chips from MANAGED. New `tests/test_run_lifecycle.py` (DOM +
  Playwright + backend registry/PTY + token gate). Flipped the stale v4.1
  `sessionBar`-absent negative in `test_project_window.py` (FWM negatives intact).
- **GATE (orchestrator-run, stub PTY):** 651 passed, 1 skipped (baseline 643+1, +8).
- **REVIEW (adversarial, prompted to refute): 1 BLOCKER** — a hard-killed session
  is marked `done` (terminal) but its record is kept; `repopulate()` (term_sessions
  returns every status) re-synced it into the live bar ~400ms after kill, so the
  killed chip REAPPEARED. The Playwright test raced past it (closed the browser
  before `setTimeout(repopulate,400)` fired) → GREEN on broken behavior (the v4
  timing-blind-gate trap). All other 6 scrutiny points CONFIRMED-OK (close never
  reaps; kill reaps no orphan; reopen re-attaches live PTY; stdlib-only; no
  Playwright in product; never :8777).
- **FIX (orchestrator):** `repopulate()` excludes terminal-status sessions
  (`_isTerminalStatus` mirrors `session_registry.TERMINAL_STATUSES` = {done,
  failed}) from the live bar; a session that just went terminal is evicted from
  MANAGED. Strengthened the Playwright kill assertion to wait 900ms (past the
  repopulate) and re-assert the chip + panel stay gone.
- **RE-GATE (orchestrator-run, stub PTY):** 651 passed, 1 skipped. UI verified:
  rendered-DOM (positive `#sessionBar`/`#panelStack` + negative old `× == kill`),
  real Playwright open→close→reopen→kill, and an orchestrator screenshot of the
  panel header showing the grey `×` and a distinct red `🗑` (visually confirmed).
- **COMMIT (scoped):** `dd08c6b` — anchor_gui.py + test_run_lifecycle.py +
  test_project_window.py only (no runtime churn).

## Wave 2 — Past-session view: real summary + "Continue in a live session" — GREEN (2026-06-14)

- **EXECUTE** (fresh sub-agent): (A) `summarizer.summarize_session` extended with
  three DETERMINISTIC source-grounded fields — `skill` / `prompts` / `actions`
  (read straight off session+member records, NEVER through the model → zero
  fabrication; honest empty/placeholder when absent). Model `claims` still go
  through generate-twice + grounding filter; failed-runner branch still skips the
  cache (no poison). (B) Historical panel JS (`_mountReadOnlyBody` rewritten →
  `_renderPastSession`/`_fillPastSessionDetail`) replaces the "session complete"
  dead-end with skill+prompts+files+doc-role links. (C) New token-gated
  `POST /api/rnd/continue_session` (+ `_build_continue_seed`) → `start_session` in
  the SAME lane seeded with the prior summary; original never mutated (R2).
- **GATE (orchestrator-run, stub PTY):** 660 passed, 1 skipped (baseline 651+1, +9).
- **REVIEW (adversarial, prompted to refute): SHIP — 0 BLOCKER, 2 MINOR.** All 7
  scrutiny points CONFIRMED-OK: R3 grounding intact (skill/prompts/actions are real
  reads; `frobnicate`/`zzyzx` ungrounded claims still dropped); cache generate-once
  + force + no-poison-on-failure; R2 original byte-identical after continue + fresh
  worktree; endpoint token-gated; UI gate is a REAL Playwright click→panel→summary→
  continue test (NOT grep-only); stdlib-only; never :8777. MINOR: produced-file
  labels not hyperlinked (doc links live in the summary block above — honest, not
  dangling); handler covered via Playwright rather than a dedicated HTTP unit test.
  Neither blocks. No FIX required.
- **UI VERIFY (orchestrator):** screenshot of a discovered planning session's panel
  — confirmed it shows the summary header + PLAN DOCUMENTS role links + "Skill
  invoked: not recorded" + "Prompts asked: none recorded" + "Files produced:
  Master Plan / Impl Plan" + the blue "▶ Continue in a live session" button
  (honest placeholders for the imported case; `ro-sec`=3).
- **COMMIT (scoped):** `6b781aa` — summarizer.py + anchor_gui.py +
  test_session_continue.py only (no runtime churn).

## Wave 3 — Better project summaries (objective/purpose) + folded dashboard reflection — GREEN (2026-06-14)

> Scope note: this wave ALSO delivers a user request raised mid-build — "project-
> window changes should reflect on the main dashboard timely" — folded in here
> because it touches the same dashboard-row/summary render path.

- **EXECUTE** (fresh sub-agent): PART 1 — `summarizer.project_extraction_seed` adds
  per-lane activity; `_project_seed_prompt` rewritten to ask for a grounded 1-2
  sentence OBJECTIVE; `render_project_markdown` → prose `## Objective`; project
  header renders the cached `Objective:` line; render path is cache-only (proven by
  stub-counter). PART 2 (folded) — read-only `GET /api/rnd/projects_html` (reuses
  `render_projects_view_html`), `#rndProjectsRows` container, `rndRowsRefresh()`
  poll(~15s)+visibilitychange+showView('rnd') in-place swap (diff-before-swap,
  hidden-view guard, failure-tolerant, no page reload).
- **GATE (orchestrator-run, stub PTY):** 670 passed, 1 skipped (baseline 660+1, +10).
- **REVIEW (adversarial, prompted to refute): SHIP — 0 BLOCKER, 1 MINOR (F1).** All
  7 points CONFIRMED-OK: cache-only render with a NON-VACUOUS counter proof (counter
  increments on a real run, stays put across renders); R3 grounding intact (per-lane
  activity is deterministic, ungrounded claims still dropped, honest "No summary yet",
  failed run no-poison); generate-once/force; the dashboard refresh swaps in place
  with real guards; UI gate is a REAL Playwright in-place-refresh test (NOT grep);
  stdlib-only + distro scan clean; never :8777. **F1 (MINOR):** the 15s poll
  re-rendered the default fragment, reverting a user's 30d rollup toggle + closing an
  open kebab.
- **FIX (orchestrator):** `rndRowsRefresh` now skips the swap while a kebab is open
  and preserves the active rollup window across the swap (capture before, re-apply
  after). New regression test `test_refresh_preserves_rollup_toggle_and_open_kebab`
  (scoped to `#rndProjectsRows` — the toggle markup also appears in a hidden view).
- **RE-GATE (orchestrator-run, stub PTY):** 671 passed, 1 skipped. UI verified:
  rendered-DOM (`#rndProjectsRows` + JS present), real Playwright in-place refresh +
  toggle/kebab preservation, and an orchestrator screenshot of the project header
  showing the grounded objective line ("…energy-aware HVAC scheduler that pre-cools
  before peak prices").
- **COMMIT (scoped):** `3bcac71` — summarizer.py + anchor_gui.py +
  test_project_summary_v5.py only (no runtime churn).

## Wave 4 — Deliverable per Foreman build (resolve · backfill · list) — GREEN (2026-06-14)

- **EXECUTE** (fresh sub-agent): `deliverables.resolve_build_deliverable` +
  `backfill_build_deliverables` (idempotent auto-pin) + read-only
  `GET /api/rnd/build_deliverable`; build panel renders its deliverable (`.bdeliv`)
  or the honest "no deliverable pinned yet — pin one"; Deliverables lane lists
  backfilled deliverables (auto-pin runs before the kanban render).
- **GATE (orchestrator-run, stub PTY):** 683 passed, 1 skipped (baseline 671+1, +12).
- **REVIEW (adversarial, prompted to refute): HALT — 2 BLOCKER, 1 MINOR.**
  **B1 (R4 fabrication):** the top signal used `summarizer.session_doc_roles`'s
  `deliverable` role, which is PROJECT-scoped (newest pin) — so EVERY build panel
  claimed the same artifact (e.g. anchor_gui.py) regardless of what it produced
  (proven with two probes). **B2 (false-green gate):** `test_resolve_from_doc_role`
  ENCODED the bug and there was ZERO multi-build-per-project coverage, so all 12
  tests + the real Playwright test passed on broken behavior. MINOR: `_is_plan_doc`
  startswith over-exclusion (readme*/handoff* → false unresolved, never a
  fabrication). Other 5 points CONFIRMED-OK (no fabrication elsewhere; backfill
  idempotent; endpoint read-only/traversal-safe; UI test real not grep; stdlib-only;
  distro clean; never :8777).
- **FIX (orchestrator):** rewrote resolution SESSION-SCOPED — (1) the build's own
  product member (>1 → ambiguous unless a pin disambiguates to one); (2) a pin whose
  path is a MEMBER of THIS session; (3) project-level pin/marker/[opt-in]config ONLY
  when the project has a SINGLE build (unambiguous). Multiple builds + no
  session-scoped signal → honest unresolved. Dropped the project-scoped doc-role
  signal. Replaced the bug-encoding test with a MULTI-BUILD regression lock + a
  single-build project-pin positive test. (MINOR left as a noted benign follow-up.)
- **RE-GATE (orchestrator-run, stub PTY):** 684 passed, 1 skipped. UI verified:
  rendered-DOM (lane lists it / panel `.bdeliv.resolved` / negative `.bdeliv.none`
  placeholder), real Playwright lane+panel+placeholder, and orchestrator screenshots
  of a build panel showing "Deliverable: myapp.py [program]" (resolved) AND
  "no deliverable pinned yet — pin one" (honest, no fabrication).
- **COMMIT (scoped):** `550c580` — deliverables.py + anchor_gui.py +
  test_build_deliverable.py only (no runtime churn).

## Wave 5 — Grass Catcher B+C hybrid idea workbench — GREEN (2026-06-14)

- **EXECUTE** (fresh sub-agent): Grass column tile opens a FULL-WIDTH workbench panel
  matching the mockup — filter tabs (All/raw/refined/promoted + counts + search +
  add/from-inbox), two-pane (idea list + selected-idea workbench: text, Develop
  Research/Plan, engine toggle, Promote, workbench terminal, refinement history with
  pull). effort_history extended: stable grass-<hash> ids, status raw→refined→
  promoted, versioned refinements grass-<id>/dev-N (append-only, race-safe), pull,
  develop (seeded session), promote-link. Endpoints token-gated; read-only GET grass.
- **GATE (orchestrator-run, stub PTY):** 698 passed, 1 skipped (baseline 684+1, +14).
- **REVIEW (adversarial, prompted to refute): HALT — 1 BLOCKER, 1 MINOR.**
  **BLOCKER:** `grass_save_refinement` existed + was backend-tested but had NO JS
  caller — the develop → "refined output saved back as a new version" loop
  (IMPL-PLAN line 150 / Wave-5 G/W/T line 162) was UNREACHABLE in the product, and
  the Playwright test masked it by PRE-FABRICATING the refinement (calling
  `eh.save_grass_refinement` directly before asserting it rendered). MINOR:
  discovered-idea promote-link vulnerable to reconcile pruning if its source doc is
  later deleted (pre-existing edge). The other 6 points CONFIRMED-OK: COPY-never-
  destroy proven at every path (append-only, race-safe dev-N, promote annotates in
  place); status lifecycle coherent; pull seeds real content; UI gate is a REAL
  Playwright test (not grep) for filter/search/select/develop; mockup structure
  present; endpoints token-gated + reuse the seed path; stdlib-only; never :8777.
- **FIX (orchestrator):** wired a "Save refinement" control into the workbench
  terminal bar (enabled once a Develop session is live) → POSTs the session output to
  `grass_save_refinement` → re-fetches + re-renders the history so the new
  grass-<id>/dev-N row appears with pull controls and the idea flips to refined.
  Extended the Playwright test to click Save and assert `dev-2` appears AS A RESULT
  (not pre-seeded). (MINOR left as a noted pre-existing edge.)
- **RE-GATE (orchestrator-run, stub PTY):** 698 passed, 1 skipped. UI verified:
  rendered-DOM (filter tabs + two-pane + history; old idea-board markup gone), real
  Playwright filter→search→select→develop→SAVE→dev-N-appears, and an orchestrator
  screenshot vs the mockup (filter tabs · two-pane list+workbench · id/status/source
  chips · Develop/engine/Promote · terminal + Save · refinement history with pull —
  strong fidelity).
- **COMMIT (scoped):** `bf8b438` — effort_history.py + anchor_gui.py +
  test_grass_workbench.py + test_grass_board.py only (no runtime churn).

## Wave 6 — CLI mirror + healthcheck v5 + distro scan + docs (PROJECT DONE) — GREEN (2026-06-14)

- **EXECUTE** (fresh sub-agent): anchor.py rnd CLI mirror (`session-summary` →
  summarizer.load_cached cache-only · `grass` → effort_history.grass_workbench_data ·
  `build-deliverable` → deliverables.resolve_build_deliverable), each delegating to the
  shared module; `check_rnd_v5_surface` (fully stubbed) registered in the healthcheck
  sequence walking all 5 wave surfaces + teardown/env-restore + never :8777; CLAUDE.md
  v5 section + API rows + CLI list + healthcheck note.
- **GATE (orchestrator-run, stub PTY):** 715 passed, 1 skipped (baseline 698+1, +17).
  `python -m distro` → scan clean (119 files; only the pywinpty exception).
- **REVIEW (adversarial, prompted to refute): SHIP — 0 BLOCKER, 2 MINOR.** All 7 points
  CONFIRMED-OK + **PROJECT-DONE: YES**: CLI delegates (read-only, cache-only summary);
  healthcheck fully stubbed + tears down + env-restored + never :8777 (independently
  asserted); distro clean + no Playwright in any product module (AST grep);
  CLAUDE.md accurate (every documented endpoint/function exists); no v2/v3/v4
  regression. MINOR: (a) `rnd grass` crashed with UnicodeEncodeError on a cp1252
  console when printing a "→"/em-dash idea title (pre-existing CLI-wide; surfaced by
  the new subcommand); (b) process: commit Wave 6 + add untracked tests.
- **FIX (orchestrator):** anchor.py main() reconfigures stdout/stderr to UTF-8
  (errors=replace) — verified live (`rnd grass` on the real registry now prints the
  "→" title, exit 0). Guard test added (test_cli_grass_handles_non_ascii_idea_title).
- **RE-GATE (orchestrator-run, stub PTY):** 716 passed, 1 skipped; distro scan clean.
- **COMMIT (scoped):** `862e249` — anchor.py + anchor_healthcheck.py + CLAUDE.md +
  test_cli_v5.py + test_healthcheck_v5.py + test_distro_scan_v5.py only (no runtime churn).

## PROJECT DONE — all 6 waves GREEN (716 passed, 1 skipped) — 2026-06-14

Every Definition-of-done item satisfied by committed code: close-to-tile vs deliberate
hard-kill (W1); past-session real summary skill/prompts/actions + continue-in-live (W2);
objective project summaries on row+header (cache-only render) + timely dashboard
reflection (W3, folded user request); deliverable-per-build session-scoped resolve +
backfill + honest-when-none (W4); Grass B+C hybrid workbench filter-tabs+two-pane+
develop+versioned/pullable refinements+promote-links+search (W5); CLI mirrors the new
seams + check_rnd_v5_surface fully stubbed + distro clean + CLAUDE.md updated (W6).
Every UI wave verified by rendered-DOM (positive+negative) + a real Playwright/Chromium
interaction test + an orchestrator screenshot. REMAINING (human/orchestrator gate):
preview-from-branch screenshots + USER SIGN-OFF before the --no-ff merge to master.
