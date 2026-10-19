# Anchor R&D Surface v11 — "Reliable Trio Handoff" — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, locked 2026-06-20. Frozen design: `MASTER-PLAN.md`. Build
> cwd = repo root `C:\dev\Anchor`, branch `foreman/rnd-surface-v11` (off master
> `465fda9`, v10 + v10.1 merged, GREEN 1202).

test-command: python -m pytest -q

## Conventions (read before any wave)

- **Active Anchor project id:** read from `rnd_registry.json` at build time. Synthetic
  ids only in tests/healthcheck.
- **No live claude/gemini/real PTY:** stub via `tests/fake_claude.py` /
  `tests/stub_streamjson.py`; PTY via `ANCHOR_PTY_BACKEND=stub`; git via the
  `worktrees._git` seam; temp dirs throughout.
- **THE v11 LESSON (non-negotiable):** every advance/handoff test must exercise the
  **WORKTREE-ONLY live flow** — start a live session, write produced docs into the
  session's WORKTREE ONLY (NO `eh.record_effort`, NO kill), then advance, then assert
  the docs were PERSISTED into the project AND referenced in the prompt. A test that
  pre-persists the effort (the masking pattern in `test_advance_artifacts_v10.py:130-133`
  / `test_advance_paste_ui_v10.py:102-106`) is prompt-building coverage, NOT live-flow
  coverage, and can never be the sole test of an advance path.
- **pywinpty** lazy-only; **Playwright DEV-ONLY** (`pytest.importorskip`); `distro.py`
  scan green. f-string/RAW-string discipline (`_PROJECT_WINDOW_JS` RAW single-brace).
- **Persist is best-effort + idempotent** (content-addressed, byte-identical skip) and
  must NEVER break an advance if it fails (degrade to the honest minimal prompt).
- **Baseline:** GREEN 1202, 1 skipped. Each wave holds or grows.
- **UI verification** (the v4 lesson) for UI-changing waves: rendered-DOM (pos+neg) +
  real Playwright + screenshot vs mockup + John's sign-off.

---

## Wave 1 — The shared handoff keystone + the live-flow truth test (backend only)

**Goal.** One helper that persists the source stage's docs and builds the real handoff,
proven by the test that the bug evaded.

**Changes.**
- Add `terminal_session.prepare_stage_handoff(project_id, source_session_id, to_lane)`
  (placed in `terminal_session.py`, which already orchestrates sessions + lazily imports
  `handoff`/`effort_history`/`summarizer` — no new import cycle). It:
  1. **Persists** the source session's produced docs via `capture_session_docs`
     (copies + commits into the main project, records session-tagged DISCOVERED efforts)
     — best-effort, idempotent. Works whether the source is live or done; does NOT reap
     the worktree.
  2. **Builds** the next-stage prompt via `handoff.build_next_stage_prompt` (which now
     finds the just-persisted, session-tagged docs → the REAL prompt with paths +
     "read these first"; honest minimal only when truly no docs exist).
  3. **Resolves** the handoff materials: the real persisted `doc_rels`, the correct
     skill (planning→Crucible, build→Foreman), and the source session's cached summary
     if present (`summarizer.load_cached`).
  4. **Triggers a background source-stage summary** (non-blocking; reuse the existing
     `_trigger_session_summary_on_finish` hook) so the digest is available, without
     blocking the advance.
  5. **Returns** `{prompt, doc_rels, skill, summary_text, persisted: [...], ok}`.
- Add `handoff.write_handoff_md(worktree_path, doc_rels, skill, summary_text)` — writes a
  `HANDOFF.md` that lists the real persisted paths + "read these first, then <plan/build>"
  + the skill + (if present) the cached summary. (Generalizes the plan-set-only
  `prime_worktree`; that stays for the plan→build plan-set case.)

**Done-when.** Calling `prepare_stage_handoff` for a live source session whose docs live
only in its worktree (a) persists + commits those docs into the project, (b) returns a
prompt that NAMES the real persisted paths (not the bare fallback), (c) resolves the
correct skill + the doc_rels for a HANDOFF.md.

**Given/When/Then (THE test that would have caught the bug).**
- *Given* a live research session (stub PTY) that wrote `research/run-1/REPORT.md` into
  its WORKTREE ONLY (no `record_effort`, no kill), *When* `prepare_stage_handoff(pid,
  rsid, 'planning')` runs, *Then* (i) `research/run-1/REPORT.md` is now a file in the
  MAIN project AND committed AND recorded as a research effort tagged with `rsid`; (ii)
  the returned prompt contains `research/run-1/REPORT.md` + a "read these" instruction +
  names Crucible; (iii) `doc_rels` contains the real path. **This MUST FAIL against the
  current code** (which never persists → bare prompt).
- *Given* a source session with genuinely NO produced docs, *Then* the prompt is the
  honest minimal one (no fabricated paths) and `persisted == []` — no crash.
- *Given* `prepare_stage_handoff` called twice, *Then* persistence is idempotent (no dup
  efforts, byte-identical skip) and the second call returns the same real prompt.

**Tests.** `tests/test_stage_handoff_keystone_v11.py` (stub PTY + temp git; the
worktree-only live-flow test above + honest-empty + idempotency). No UI.

---

## Wave 2 — Wire research→plan advance through the keystone (THE user-facing fix, UI)

**Goal.** Clicking **Advance to Planning** on a live research session persists its
reports + opens the planning session with the real, doc-referencing prompt + a HANDOFF.md.

**Changes.**
- `anchor_gui.py` `/api/rnd/advance_session`: call `prepare_stage_handoff(pid, source,
  'planning')` BEFORE `start_session` (mirroring `finish_to_build`'s capture-before-
  advance). Start the planning session with `paste_prompt=<keystone prompt>`; after its
  worktree exists, `handoff.write_handoff_md(plan_wt, doc_rels, 'Crucible', summary)`;
  keep `write_next_prompt` + `record_stage_link`. The research docs are now persisted, so
  the planning worktree (off main HEAD) CONTAINS them.
- Build the mockup `_mockups/research_to_plan_handoff.html` (planning panel: Crucible
  greet + the pasted prompt naming the real `research/run-1/REPORT.md` + "read these
  first" + a note that HANDOFF.md is present).

**Done-when.** Advancing a live research session (docs in worktree only) persists the
docs into the project AND opens the planning session whose pasted prompt names the real
report path + has a HANDOFF.md referencing it.

**Given/When/Then.**
- *Given* a live research session with `research/run-1/REPORT.md` in its worktree only,
  *When* `/api/rnd/advance_session` (research→plan) is called, *Then* the report is
  persisted+committed into the project, the new planning session's `pending_paste`
  contains the real path + "read these", and `HANDOFF.md` exists in the planning worktree
  referencing it.
- *Negative:* a research session with no docs → honest minimal prompt, no fabricated
  path, no crash; the UI shows an honest note.

**Tests.** `tests/test_advance_research_to_plan_live_v11.py` (backend: the worktree-only
live flow over the HTTP endpoint — NOT pre-persisted) + a Playwright
`tests/test_advance_research_to_plan_ui_v11.py` that **produces the report in the
worktree live (not via record_effort)**, clicks Advance, and asserts the planning
terminal's pasted prompt shows the real `research/run-1/REPORT.md` (a token absent from
the bare fallback) + no console error + screenshot vs the mockup. **UI wave — full
verification + John's sign-off.** This is THE wave that fixes John's reported failure.

---

## Wave 3 — Unify the other advance paths through the keystone (backend + plan→build check)

**Goal.** One handoff path. Route plan→build (button + auto-on-kill) and the grass
variant through `prepare_stage_handoff` so all are consistent and equally verified.

**Changes.**
- `finish_to_build`, `auto_advance_planning_to_build` (kill/reconcile), and
  `advance_grass_research_to_plan` call `prepare_stage_handoff` instead of their bespoke
  persist + prompt logic. Remove the now-duplicated capture/prompt code (keep the
  plan-set discovery that build needs). Each writes HANDOFF.md via the shared
  `write_handoff_md` (plan→build keeps `prime_worktree` for the plan-set specifics if
  needed, layered on the shared persist).
- Confirm the chain linkage + idempotency invariants are unchanged for every path.

**Done-when.** plan→build (button + auto-on-kill) and grass research→plan all persist the
source docs + open the next stage with the real doc-referencing prompt, through the
SAME keystone; no regression to the v10/v10.1 behavior.

**Given/When/Then.**
- *Given* a live planning session whose plan docs are in its worktree only, *When*
  Finish→Build runs, *Then* (as today) the docs persist + the build prompt names them —
  now via the shared keystone; the existing `test_finish_to_build_persists_…` still
  passes.
- *Given* the auto-advance-on-kill path, *Then* it still produces the linked build with
  persisted docs (no double-persist, idempotent).
- *Given* the grass research→plan advance, *Then* it still persists the dev docs + opens
  the contained plan dev session with the real prompt (no regression to v10 W5).

**Tests.** `tests/test_handoff_unified_v11.py` (worktree-only live-flow tests for
plan→build button + auto-advance + grass, all through the keystone) + confirm the v10
advance/handoff/grass suites still pass. Light UI check only if the plan→build panel
render changes (likely none).

---

## Wave 4 — Verification hardening + healthcheck v11 + docs (PROJECT DONE)

**Goal.** Make "tests green but live broken" structurally impossible to recur, and close
out.

**Changes.**
- `anchor_healthcheck.py`: `check_rnd_v11_surface(report, server_proc, rnd_env)` — fully
  stubbed (stub PTY + stream-json stub runner + temp worktree base + temp git project +
  temp data dir). It walks the REAL live flow: start a research session, write a doc into
  its WORKTREE ONLY, `prepare_stage_handoff`/advance, assert the doc is persisted +
  committed + the prompt names it + HANDOFF.md references it; then the same for
  plan→build. Registered in `main()`. Reaps stub PTYs + synthetic rows, restores env,
  never binds `:8777`.
- Annotate the masking tests (`test_advance_artifacts_v10.py`, `test_advance_paste_ui_v10.py`)
  with a comment that they are prompt-building-given-persisted-docs coverage and that the
  live-flow truth lives in the v11 tests — keep them (still valid), do not weaken.
- `anchor.py`: if a new read seam is warranted, `rnd handoff <pid> --session <id>
  --to <lane>` → a read-only preview of the prepared handoff (prompt + doc_rels + skill;
  does NOT persist/mutate — a pure preview that resolves from already-persisted docs).
  Optional; include only if cleanly read-only.
- Update `CLAUDE.md`: a v11 section (the keystone unification + the bug it fixed + the
  worktree-only-test lesson) + the new `prepare_stage_handoff` / `write_handoff_md` seams
  + any endpoint/CLI note. Update the auto-memory pointer.

**Done-when.** `python -m pytest -q` ≥ baseline (1202) + the new v11 tests, all green;
`check_rnd_v11_surface` passes fully stubbed walking the real flow; distro green; docs
updated.

**Given/When/Then.**
- *Given* the healthcheck, *When* `check_rnd_v11_surface` runs, *Then* it persists +
  references docs via the real worktree-only flow for research→plan and plan→build, with
  no real PTY/claude/`:8777`/network and full teardown.
- *Given* the full suite, *Then* it is green and the masking tests are annotated (not
  weakened); distro scan green.

**Tests.** Extend the healthcheck self-test; `tests/test_cli_v11.py` if the CLI seam is
added; distro scan stays green. No UI.

---

## Wave dependency / ordering

```
W1 (keystone + live-flow truth test, backend)
  └─> W2 (wire research→plan advance — THE user fix, UI)   ← John's failure fixed here
        └─> W3 (unify finish_to_build / auto-advance / grass through the keystone)
              └─> W4 (healthcheck v11 real-flow walk + docs)   ← PROJECT DONE
```

W1→W2 is the critical chain that fixes the reported bug. W3 unifies the rest (eliminating
the asymmetry class). W4 makes the live-flow coverage permanent.

## 🚦 Stage 2 gate

On John's approval this freezes and hands to Foreman:
`node foreman/bin/locate-plan.mjs --json planning/rnd-v11` must exit 0 before any wave
runs. No branch is cut and no `nssm restart anchor` until John signs off.
