# Implementation Plan — Crucible-Improve Follow-up (2026-07-01)

test-command: python -m pytest -q

Three contiguous waves. Each is EXECUTE → orchestrator GATE (full pytest) →
adversarial REVIEW → FIX → re-gate → commit-on-GREEN. Wave 2 additionally halts
for a screenshot sign-off.

## Wave 1 — Claude-first session launch

**Goal.** Every dashboard session-launch control opens on Claude by default, so
research sessions run on Claude and researchPrime auto-loads. Gemini remains
reachable only via the explicit per-session engine toggle and the skill-layer 5:1
swarm — never as a launch default.

**Changes (anchor_gui.py):**
- `newTermSession(lane, backend, opts)` default `backend = backend || 'gemini'`
  → `'claude'`.
- `newEffort(stage)` payload `backend: 'gemini'` → `'claude'`.
- Research Kanban launcher (`render_project_board`, the `trio_lane == "research"`
  branch): replace the two `newTermSession('research','gemini')` spans + their
  "(Gemini)" / "Gemini" labels with a single `+ New research run` control that
  launches on Claude (mirror the generic `else` launcher shape).

**Acceptance.**
- No session-launch call site hardcodes `'gemini'`; grep of the launch JS/HTML
  shows Claude (or an omitted backend that defaults to Claude).
- The research lane launcher renders a single Claude launcher (no "Gemini" label).
- The lane→skill seed mapping is unchanged (research → researchPrime); backend
  default is Claude (`terminal_session.DEFAULT_ENGINE`, `lanes.select_engine_plan`
  on a Claude host — already true, asserted for regression).
- New test file `tests/test_claude_first_launch_w1.py` gates all of the above.

## Wave 2 — Unified dock controls (× + 🪦) [UI — screenshot sign-off]

**Goal.** The v12 bottom dock header carries exactly the same two lifecycle
controls as the W6 inline panel: `×` graceful close (keeps the effort) + `🪦`
Kill → Boneyard (the ONE destructive control). No second `✕`.

**Changes (anchor_gui.py `_render_layoutd_dock_html`):**
- Keep `dockMin` (▁), `dockMax` (▢), `dockAdvance`.
- Keep `dockClose` as the `×` graceful close.
- Convert `dockKill` to the `🪦` headstone control (match the panel's
  `.panelbtn killbone`), keeping its `dockKill()` → `term_kill` wiring.
- **Remove** the `dockDelete` element (the redundant second red `✕` v9
  true-delete). Leave no dangling JS/CSS reference that errors (the `dockDelete()`
  JS function may remain unused, but nothing may call a now-absent element).

**Acceptance.**
- Dock header HTML renders one `×` (dockClose) + one `🪦` (dockKill) and NO
  `dockDelete` element / no second delete `✕`.
- No JS references an element that no longer exists (no console error on open).
- New test `tests/test_dock_controls_unified_w2.py` gates the control set.
- **Screenshot sign-off:** John confirms the dock shows only `× + 🪦`.

## Wave 3 — Bridge job cost onto the effort record

**Goal.** A completed one-shot `launch_lane` job stamps its captured
cost/tokens/duration onto the effort pointer-record, so
`project_effort_rollup` / `effort_view.effort_rollup` report real numbers instead
of 0.

**Changes (job_runner.py):**
- In `_finalize` (after `rec["cost"]` is stamped), when the job record carries a
  project effort identity (`project_id` + `folder_path` + `lane` + `job_id`),
  bridge the cost onto the effort record via
  `effort_history.finalize_effort(folder_path, project_id, lane, job_id, rec,
  auto_commit=False)`.
- Use a **lazy import** of `effort_history` inside `_finalize` to avoid an import
  cycle; wrap in best-effort try/except so a bridge failure never breaks job
  finalization; idempotent (safe if called twice).
- `auto_commit=False`: only attach cost to the on-disk pointer-record; do not
  trigger a git commit from job finalization.

**Acceptance.**
- Given a finished job record with a `cost` envelope
  (`total_cost_usd`/tokens/`duration_ms`) and a project effort identity, after
  `_finalize` the effort pointer-record carries the same cost block and
  `project_effort_rollup` sums non-zero.
- A job with no effort identity (no project_id) finalizes exactly as before (no
  bridge, no error).
- New test `tests/test_cost_bridge_w3.py` gates both paths.
- The by-design 0 for discovered/interactive efforts is unchanged and documented.

## Wave 4 — Triage & fix the pre-existing baseline reds

**Goal.** The prior crucible-improve build gated on a subset; the full pytest
suite has ~59 pre-existing failures on this branch. Bring the full suite to GREEN
(or GREEN except an explicitly-listed, John-agreed environmental set). This wave
runs LAST so the end-state reflects waves 1–3 plus the baseline.

**Categories to resolve (each touched test documented, with citation):**
- **Stale W6/W9 control-scheme tests** — tests asserting removed controls
  (`panelbtn hardkill`, the old 🗑 kill glyph, `panelbtn delete` on the panel).
  **Realign** them to the intended, user-approved unified scheme (`×` + `🪦`
  everywhere, including the dock after Wave 2). This is alignment to deliberate
  behavior, NOT test-weakening: net assertion coverage of the control set must not
  drop — a realigned test asserts the NEW correct controls.
- **Environmental / browser tests** — Playwright / live-server / JS-console tests
  that require a real browser+server and can't run in this harness. Where a test
  is genuinely environment-bound, gate it behind the same `pytest.importorskip` /
  skip-with-explicit-reason contract the rest of the UI suite uses — never a bare
  `skip` to hide a real failure. Any that CAN be made to pass deterministically,
  fix.
- **Real regressions** — anything that is a true product defect (e.g. an endpoint
  returning the wrong status, a missing wired handler) is FIXED, not masked.

**Acceptance.**
- `python -m pytest -q` is GREEN, OR GREEN except a **written, enumerated** set of
  environment-bound tests (listed in the execution log with the reason each is
  skipped) that John has agreed to treat as non-gating in this harness.
- No test count / assertion reduction for real behavior without an in-log citation
  to the deliberate behavior change that justifies it (anti-test-weakening).
- The execution log records, per touched test: category (stale / env / real),
  action taken, and the citation.
