# Execution Log — Crucible-Improve Follow-up (Foreman)

Status: IN PROGRESS — driven by Foreman (Claude/Opus orchestrating).
Gate: `python -m pytest -q` (orchestrator-run, full suite).

| Wave | Title | State |
|------|-------|-------|
| 1 | Claude-first session launch | GREEN |
| 2 | Unified dock controls (× + 🪦) [UI sign-off] | GREEN (signed off) |
| 3 | Bridge job cost onto the effort record | GREEN |
| 4 | Triage & fix pre-existing baseline reds (~59) | GREEN (−2 enumerated order-flakes) |

## Wave 1 — Claude-first session launch — GREEN (2026-07-01)

**EXECUTE.** Made Claude the launch default at every real site in `anchor_gui.py`
(the earlier investigation found more than the two originally reported):
`newTermSession` default, `newEffort` payload, the grass workbench `_grassEngine`,
the `_buildEngineToggle` highlight default, four `rec.backend || 'gemini'` MANAGED
display-fallbacks, and the legacy kanban research launcher. Confirmed the
server-side default is already Claude and the `backend="gemini"` at :16741 is a
correct claude-first fallback (only when the `claude` CLI is absent). New gate:
`tests/test_claude_first_launch_w1.py`.

**REVIEW (2 independent, refute-prompted).** Reviewer B: no regression (the server
is the source of truth for `backend`; the `repopulate()` re-sync uses an
empty-string, not claude, fallback; the engine toggle is live-only). Reviewer A:
found a REAL gap — `promoteGrass` / `continueSession` sent no backend, so the
server resolved to the project's **sticky `last_engine_for_project`**; after any
per-session Gemini toggle, an unrelated promote/continue would silently open on
Gemini (violating the policy). Reviewer A also flagged the first test cut as
string-only (blind to that path).

**FIX.** Threaded an explicit Claude default through both paths: client payloads
now send `backend:'claude'`, and the `promote_grass`/`continue_session` handlers
default to `DEFAULT_ENGINE` (never the sticky last_engine); `advance_session` is
intentionally left inheriting its own effort's engine (legitimate continuity —
its source was explicitly toggled). Added 3 behavioral (stub-PTY) tests that set
`last_engine=gemini` and prove promote/continue still open Claude, plus a
"witness" test documenting the sticky leak at the source. `test_engine_persist` /
`test_cli_v4` (the intentional sticky-engine semantics) stay green — no global
behavior change.

**GATE (orchestrator-run full suite).** 60 failed / 1616 passed. Delta vs the
59-red baseline: my 11 new tests all pass; exactly ONE pre-existing test flipped
red — `test_project_window.py::test_summary_panel_no_leaked_braces`. Verified it
is a **full-suite ORDER/isolation flake, NOT a Wave-1 regression**: it passes in
isolation AND passes when run immediately after the new test file; my edits are
brace-free raw-string value swaps to a panel I never touched. Per the gate rule (a
red that does not reproduce in isolation cannot block GREEN) Wave 1 is GREEN.
→ **Added to Wave 4 triage: `test_summary_panel_no_leaked_braces` (test-pollution
/ order-flake category).**

**Also noted for Wave 4:** `_render_kanban_html` is dead code (no live caller;
`/api/rnd/board_html` renders `_render_layoutd_html`) — candidate for removal.

## Wave 2 — Unified dock controls (× + 🪦) — GREEN (signed off, 2026-07-01)

**EXECUTE.** `_render_layoutd_dock_html`: the dock's destructive controls now
mirror the W6 inline panel — `×` graceful close (dockClose) + a single
`🪦` Kill → Boneyard (dockKill, entity `&#129702;`, class `ctl panelbtn
killbone`, still `onclick=dockKill()` → term_kill). Removed the redundant
second-`✕` v9 true-delete (`dockDelete`). New gate:
`tests/test_dock_controls_unified_w2.py` (4 tests).

**REVIEW (2 independent, refute-prompted) — both converged.** (1) The red
headstone was a CSS-specificity mirage: `.dock .dbar .ctl` (0,3,0) out-specified
`.panelbtn.killbone` (0,2,0), so the destructive control rendered neutral grey.
(2) FEATURE LOSS (HIGH): removing `dockDelete` left `/api/rnd/term_delete`
(true-delete = drop record, KEEP docs) with NO UI trigger anywhere. (3) The
Playwright `test_session_delete_v9::test_playwright_delete_tile_gone_and_stays_gone`
still asserts `#dockDelete` (already baseline-red; now also feature-removed).

**FIX.** Added dock-specificity danger rules
`.dock .dbar .ctl.killbone{color:var(--danger)}` + `:hover` (computed color
verified rgb(248,113,113) red on dockKill vs grey on dockClose). 

**SIGN-OFF (screenshot + user decision).** Rendered the real dock (Playwright,
3× crop → `scratchpad/wave2_dock_ctrls.png`): `Advance → | ▁ | ▢ | × | 🪦` — one
close, one headstone, no second ×. John reviewed and chose **"Drop true-delete —
× + 🪦 only"** (Kill → Boneyard preserves docs in the searchable Boneyard, so no
doc loss). Decision recorded.

**GATE.** Full suite 59 failed / 1621 passed — **zero new reds** vs the 59
baseline (order-flake did not resurface). 1606 + 11 (W1) + 4 (W2) = 1621. The
CSS danger-rule was added after the gate launched but is test-inert (additive,
balanced braces, no color assertion); re-verified the 3 dock test files (24 pass)
against the final code.

**Wave 4 follow-ups queued (true-delete now dropped by decision):** retire
`test_session_delete_v9::test_playwright_delete_tile_gone_and_stays_gone`
(tests a removed feature); remove the now-dead `dockDelete()` + `deletePanel()`
JS and the vestigial `.panelbtn.delete` CSS + its false "retained for the dock"
comment (and update `test_terminal_controls_w6`'s `.panelbtn.delete{` assertion
accordingly).

## Wave 3 — Bridge job cost onto the effort record — GREEN (2026-07-01)

**EXECUTE.** `job_runner._finalize`: after the terminal-status write (outside the
`WRITE_LOCK`, after `_mirror_session_status`), bridge the captured cost onto the
project EFFORT record via `effort_history.finalize_effort(folder_path,
project_id, lane, job_id, rec, auto_commit=False)` — guarded on the record
carrying `project_id` + `folder_path` + `cost`, lazy import, best-effort
try/except. The rollups read the effort `cost` block, whose only writer
(finalize_effort→attach_cost) previously had NO production caller. New gate:
`tests/test_cost_bridge_w3.py` (4 tests: bridge writes cost · no-identity skip ·
no-envelope no-fabrication · end-to-end `project_effort_rollup` non-zero).

**REVIEW (2 independent, refute-prompted) — both CLEAN, no FIX needed.**
Reviewer A (safety): WRITE_LOCK is an RLock and the bridge runs outside it (no
deadlock); overwrite-not-accumulate idempotency; `auto_commit=False` runs no git;
no import cycle; the guard fires ONLY for real `launch_guarded` jobs (lane launch
+ v2 REPL) — gandalf shards (bare `launch`) and swarm children (project_id="")
correctly skip; no file collision with `_write_launch_record`. Reviewer B
(honesty): traced end-to-end — a bridged effort record is RUN-provenance (no
`source=discovered`), so `project_effort_rollup` counts it; no double-count.
Cosmetic-only notes folded in (test 4 simplified to prove the bridge ALONE lights
the rollup, faithful to production).

**HONEST SCOPE (surfaced to John).** This fixes the zeros for **one-shot
`launch_lane` jobs** only. **Interactive ConPTY terminal sessions — the
day-to-day UX — still read 0**: they never reach `job_runner._finalize` with a
stream-json result envelope and persist as `SOURCE_DISCOVERED` (excluded from the
rollup by the honesty contract). The bridge does NOT fabricate zero-cost for them.
Lighting up interactive-session cost needs a separate capture mechanism — a
documented follow-up, out of this effort's scope.

**GATE.** Full suite 60 failed / 1624 passed. Delta vs baseline: my 4 new tests
pass; exactly ONE pre-existing test flipped —
`test_advance_artifacts_v10::test_finish_to_build_persists_planning_docs_so_build_can_read_them`.
Verified a full-suite ORDER/isolation flake (passes in isolation, as a whole
file, AND directly after the cost test file); NOT a Wave-3 regression. Per the
gate rule Wave 3 is GREEN. → **Wave 4 triage now tracks TWO order-flakes**
(this + `test_summary_panel_no_leaked_braces`) as a test-isolation category.

## Baseline (pre-Wave-1)

Full suite `python -m pytest -q`: **59 failed / 1606 passed** (15m15s). The prior
crucible-improve build gated on a subset, so these were not caught. Probed sample
confirms the majority are stale W6 control-scheme tests (assert removed
`hardkill`/🗑/`panelbtn delete`) + environmental browser tests. Full categorized
list captured for Wave 4. My waves 1–3 gate on "no NEW reds beyond this baseline";
Wave 4 clears the baseline itself.

---

(Per-wave EXECUTE → GATE → REVIEW → FIX records are appended below as each wave runs.)

## Wave 4 — Triage & fix pre-existing baseline reds — GREEN (2026-07-01)

Baseline 59 full-suite reds → **2 order-flakes** (both pass in isolation).
1682 passed. The prior "gate 274/274" was a SUBSET gate; the full suite hid one
real product bug plus a pile of test-hygiene rot.

**1 REAL PRODUCT BUG FIXED (anchor_gui.py) — cleared 39 tests at once.**
`GET /api/version` 500'd on EVERY page load: a function-local `import json`
(and `import sys`) inside the zombie-hunter branch of `do_GET` made `json`
method-local for the whole method, so the earlier `/api/version` branch hit
`UnboundLocalError`. The client polls `/api/version` every 30s, so this spammed
500s in production too. Removed the redundant local imports (both are
module-global). 39 Playwright tests (all asserting "no JS console 500") went
green.

**20 TEST-HYGIENE REALIGNMENTS (4 parallel triage agents, zero product change,
zero assertions weakened):**
- *Stale W6/W9 control-scheme tests (7)* — realigned `panelbtn hardkill`/🗑 →
  `panelbtn killbone`/🪦 and the dock/panel × + 🪦 scheme; retired the
  `#dockDelete` Playwright test (true-delete dropped by user decision) →
  replaced with a render guard that `#dockDelete` stays gone. Files:
  test_run_lifecycle, test_window_controls_v6, test_session_delete_v9.
- *Playwright selector renames (4)* — `.panelbtn.hardkill` → `.panelbtn.killbone`
  in kill-flow tests + one xterm scrollback-vs-visible-viewport read fix
  (advance seed now carries the upstream summary, scrolling the opener out of
  view). Chromium confirmed working here — these were NOT env failures. Files:
  test_no_loss_lifecycle_v8, test_auto_advance_plan_to_build, test_handoff_docs_v8,
  test_advance_paste_ui_v10.
- *Host-token / non-hermetic fixtures (6)* — this dev host has a real
  `ANCHOR_TOKEN` set; fixtures that didn't `delenv` it leaked it in, 401-ing
  back-compat read tests. Added the suite-standard `delenv`/token-in-body
  (test_panel_render ×4, test_anchor_features) + hardened the throwaway-git
  fixture (`commit.gpgsign false` + `--no-verify`) in test_stage_baseline_persist.
- *Stale literal-string assertions (3)* — realigned to the current render:
  `npNameEdited()` now co-emits `npUpdatePreview()`; the brand-img "single svg"
  invariant now allows the documented zombie-hunter photo icon; the older-runs
  shelf gained a stable `prev-efforts` class between `shelf-wrap` and `collapsed`.
  Files: test_rnd_ui_wiring, test_dashboard_rows, test_project_window.

**Dead-code decision (deviating from the initial cleanup note, on new info):**
Agent 2 showed `deletePanel()` is still the tested confirm-gated client for the
live `/api/rnd/term_delete` backend. Rather than rip it out (and re-edit a
coherent passing test state) for a removed UI affordance, KEPT the
`deletePanel()`/`dockDelete()` client + `.panelbtn.delete` CSS as a tested,
one-line re-add path and FIXED the now-false "the dock still uses it" comments
(anchor_gui.py + test_terminal_controls_w6).

**GATE.** `python -m pytest` → 2 failed / 1682 passed (13m44s). Both residual
fails PASS IN ISOLATION and are pre-existing test-ISOLATION (order) flakes, NOT
product regressions:
- `test_project_window::test_session_summary_endpoint_unknown_session_is_terminal`
  (was NOT in the original baseline — newly surfaced by ordering).
- `test_stage_baseline_persist_v12::test_baseline_best_effort` (green standalone
  after the git-config hardening; order-coupled in the full suite).
Each prior gate surfaced a DIFFERENT such flake (W1: no_leaked_braces; W3:
advance_artifacts finish_to_build), confirming a broad suite-wide isolation
weakness that predates this effort. **FOLLOW-UP (out of scope): harden
cross-test isolation** (a global git-config/env/cwd leak between tests). Per the
plan's "GREEN except an enumerated set," Wave 4 is GREEN.
