# Anchor R&D Surface v12 — "Efforts" (continuity-first single-session trio) — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, 2026-06-21 — **revised after Shark-Tank Round 2** (3 fresh-context sharks:
> Sequencing BLOCK / Testability BLOCK / Completeness SHIP-WITH-FIXES; all findings folded in: complete
> retirement map gated on `effort_managed`, exact git mechanics, split over-bundled waves, UI shipped
> early as a static skeleton, falsifiable GWTs). Frozen design: `MASTER-PLAN.md`. Build cwd = repo root
> `C:\dev\Anchor`, branch `foreman/rnd-surface-v12` (off master `f2e0e40`, v11.1 merged + deployed).

test-command: python -m pytest -q

## Conventions (read before any wave)

- **Continuity-first model (locked).** An effort is ONE session by default; "Advance" = relabel +
  persist + summarize the completed stage (NO new session, NO PTY injection by default); a
  warn+one-click fresh-session handoff is the context-relief valve only; legacy chains render AS
  efforts via a non-destructive view layer.
- **The `effort_managed` discriminator (critical — Shark C3).** A v12 effort carries
  `effort_managed=True`, set ONLY by the v12 entrypoints (the "+ New effort" start, `handoff_to_fresh`,
  and `advance_stage`/`finish_stage`). Legacy records (incl. the synthetic projects in the v6/v8/v10/v11
  healthcheck walks) normalize to `effort_managed=False`. **Every retirement gate keys on
  `effort_managed`, never on `kind`/`current_stage`** (which legacy records also carry), so the legacy
  walks keep passing unchanged.
- **No live claude/gemini/real PTY:** stub via `tests/fake_claude.py` / `tests/stub_streamjson.py`;
  PTY via `ANCHOR_PTY_BACKEND=stub`; git via the `worktrees._git` seam; temp git/data dirs throughout.
  Never bind `:8777`, never touch real data/network; `ANCHOR_PROACTIVE_SUMMARY` off in tests.
- **THE v11 LESSON (non-negotiable).** Every advance/handoff/stage test is **worktree-only** (write
  produced docs into the session worktree, never `eh.record_effort` pre-persist) and, for
  conversation-only stages, **seed the stub PTY read buffer** via `pty_manager.write` (no file written).
  A pre-persisted test masks coverage. Each advance test asserts session-id **SET equality** (snapshot
  the id-set pre/post, assert equal — not just `len`) to survive reconcile churn.
- **pywinpty** lazy-only (`pty_manager.py`); **Playwright DEV-ONLY** (`pytest.importorskip`), never in
  product; `distro.py` scan green (new modules stdlib-only + in `dist_manifest.txt`).
- **Render discipline:** `render_project_window_html` is an f-string (double-brace `{{ }}`);
  `_PROJECT_WINDOW_JS` is a RAW single-brace string. A **render-smoke test** (import + non-empty
  balanced-brace HTML) precedes every Playwright wave.
- **UI verification (the v4 lesson)** on Waves 2, 10, 11: rendered-DOM (positive + negative) + a real
  Playwright/Chromium interaction test with **machine-checkable pass conditions** (not "element exists")
  + an orchestrator screenshot vs the named mockup **+ named deltas** (the warn banner + "+ New effort"
  are intentional additions beyond the mockup) + John's sign-off. A string-grep-only gate is an automatic
  HALT.
- **Baseline:** GREEN 1266, 1 skipped at branch cut. Each wave holds or grows. Best-effort keystones
  (persist/snapshot/summary/boneyard/view) NEVER break the operation they hook.
- **No merge to master / no `nssm restart` until John signs off.**

---

## Wave 1 — Effort record: stage fields + `effort_managed` + `effort_id` passthrough + back-compat normalize (backend)

**Goal.** The session record can carry an effort's stage + the v12 discriminator without breaking any
existing record, and `start_session` can inherit an `effort_id`.

**Changes.**
- `session_registry._normalize`: add `kind` (`"trio"|"general"|"grass-dev"`, derived from `lane` when
  absent), `current_stage` (`""|research|plan|build`, from `lane` when absent), `stage_history` (list of
  `{stage, store_lane, started_at, ended_at|null, baseline_ref, seeded, summary_ref|null, doc_count,
  state}` where `state ∈ {active,done,interrupted}`; default `[]`), `seeded_stages` (list, default `[]`),
  `effort_id` (default = own `session_id`), `effort_managed` (bool, default **False**). All back-compat;
  an old record normalizes with no crash and `effort_managed==False`.
- `session_registry`: helpers `effort_root(sid)`, `set_current_stage(sid, stage, store_lane,
  baseline_ref)` (close prior entry → append new), `stage_entry(record, stage)`.
- `terminal_session.start_session(..., effort_id=None, effort_managed=False)`: when `effort_id` is given
  the new record inherits it (else = own sid); `effort_managed` stored as passed. (No behavior change for
  existing callers — both default to today's behavior.)
- `anchor_gui`: a board-routing accessor `_effort_zone(record)` → Research vs Plan/Build vs none (by
  `current_stage`/`kind`). **Render unchanged this wave** (the 5-col board still renders; the accessor is
  unit-tested only; its render consumer arrives in W10 — noted so a reviewer doesn't expect live routing).
- Audit `chain_members`/`_CHAIN_LANE_ORDER`/`_REGISTRY_LANE_TO_COLUMN` consumers; document that `lane`
  reads keep working when it later flips.

**Done-when.** A pre-v12 record loads → derived `kind`+`current_stage`, `stage_history==[]`,
`effort_id==sid`, `effort_managed==False`, round-trips unchanged in meaning; `start_session(effort_id=X,
effort_managed=True)` produces a record with `effort_id==X` and `effort_managed==True`.

**Given/When/Then.**
- *Given* an old record `{lane:'research'}` (no new fields), *When* loaded, *Then* `kind=='trio'`,
  `current_stage=='research'`, `stage_history==[]`, `effort_id==sid`, `effort_managed==False`; no exception.
- *Given* `start_session(pid,'research', effort_id='E1', effort_managed=True)` (stub PTY), *Then* the new
  record has `effort_id=='E1'`, `effort_managed==True`; *Given* a legacy `start_session(pid,'research')`,
  *Then* `effort_managed==False`, `effort_id==own sid`.
- *Given* `set_current_stage(sid,'plan','planning','abc')`, *Then* prior entry closed (`ended_at` set,
  `state=='done'`), new `plan` entry appended (`store_lane=='planning'`, `baseline_ref=='abc'`,
  `state=='active'`), `current_stage=='plan'`, `lane=='planning'`.
- *Given* `_effort_zone` on `current_stage=='research'` → Research; `'plan'`/`'build'` → Plan/Build;
  `kind in {general,grass-dev}` → none.

**Tests.** `tests/test_effort_record_v12.py`. No UI.

---

## Wave 2 — Layout-D static skeleton render (UI-gated) — "ship the look early"

**Goal.** John SEES + signs off the approved Layout-D structure early, driven by EXISTING data, with
live interactions deferred — honoring "ship UI early" without forward-referencing the backbone.

**Changes.**
- `render_project_window_html` + `_PROJECT_WINDOW_JS`: render the Layout-D shell per
  `_mockups/dashboard_D_headline_shelf.html` — **Latest Research** headline + collapsible older-research
  shelf; **Latest Plan/Build** headline + collapsible shelf (each foldable "▾ Hide N / ▸ Show all N"); a
  persistent right column (Grass mini-panel + Deliverables panel); a **+ New effort** control; the bottom
  **dock chrome** (title bar + summary-on-top region + draggable splitter + terminal host) present but
  **inert** (no transport, buttons disabled/labeled "(wired in W10)"). Driven by the EXISTING
  `_gather_project_sessions` (already on master), mapped into the headline/shelf shape by a thin adapter.
  Keep masthead + lifecycle + GitHub controls. Preserve the f-string/RAW boundary.

**Done-when.** The window renders Layout D matching the mockup (two headline cards, two collapsible
shelves, right column, + New effort, inert dock chrome); render-smoke + DOM pos/neg pass; Playwright
confirms shelf collapse/expand; screenshot matches the mockup (+ named deltas: warn banner + New-effort);
John signs off the LOOK.

**Given/When/Then.**
- *Given* a project with sessions, *When* rendered, *Then* DOM has one `.headline` (Latest Research) + one
  (Latest Plan/Build), each with a collapsible shelf of little tiles; a right column with Grass +
  Deliverables panels; a `+ New effort` control; an inert dock region (positive DOM). *Given* a project
  with zero sessions, *Then* honest empty states, no shelf, no crash (negative DOM).
- *Given* the page in Chromium, *When* a shelf "Hide/Show all" is clicked, *Then* it collapses/expands
  (the collapse state toggles a class — machine-checkable).
- **Render-smoke:** `render_project_window_html` imports + returns non-empty, brace-balanced HTML.

**Tests.** `tests/test_layoutd_skeleton_v12.py` (DOM pos+neg + render-smoke) +
`tests/test_layoutd_skeleton_playwright_v12.py` (`pytest.importorskip`). Screenshot vs
`_mockups/dashboard_D_headline_shelf.html` + **John sign-off**.

---

## Wave 3 — Keystone A: per-stage baseline commit + stage-scoped persist + stage deliverable (backend)

**Goal.** Each stage's produced docs (and the build deliverable) attribute to THAT stage only, even when
stages share one worktree. Fixes the doc-attribution BLOCKER (R1; SK-2/F2/B1/B2).

**Changes.**
- `effort_history.record_stage_baseline(worktree_path)` → commit (or capture a tree-ish) via
  `worktrees._git`; return `baseline_ref`. Best-effort.
- `effort_history.persist_session_stage_docs(folder, pid, sid, stage, store_lane, worktree_path,
  baseline_ref)` — produced set computed with **EXACT git commands** (no vague "porcelain since baseline"):
  `committed = git diff --name-only <baseline_ref>..HEAD`; `working = git diff --name-only <baseline_ref> --`
  (working-tree vs the baseline); `untracked = git status --porcelain -uall` filtered to additions; the
  produced set = `(committed ∪ working ∪ untracked)` **minus paths already attributed to a closed prior
  stage** (look up via `efforts_for_session_stage` for earlier stages). Persist+commit only those; tag
  each effort `(sid, stage)`. Add `efforts_for_session_stage(folder, pid, sid, stage)`. Keep legacy
  `persist_session_docs` for non-effort callers.
- `deliverables.resolve_build_deliverable`: when the subject is an effort, feed ONLY the build-stage doc
  set (`efforts_for_session_stage(..., 'build')`); honest unresolved when `current_stage != build` or no
  build-stage signal. `deliverables.backfill_build_deliverables`: same stage-filter (so rescan never pins
  a plan-stage MASTER-PLAN.md — Shark C6).

**Done-when.** In ONE shared worktree where research committed `r.md` (baseline B0), then a plan baseline
B1, then `plan/MASTER-PLAN.md`, then a build baseline B2 and an UNCOMMITTED `app.py`: persisting the plan
stage yields `[planning/MASTER-PLAN.md]` only; persisting build yields `[app.py]` only; a build deliverable
resolves `app.py`, never `MASTER-PLAN.md`; and the legacy whole-tree diff is proven to return a superset.

**Given/When/Then (ONE shared worktree, worktree-only).**
- *Given* one worktree W: commit `research/r.md`; B0=HEAD; B1=HEAD; commit `planning/MASTER-PLAN.md`,
  *When* `persist_session_stage_docs(...,'plan','planning',baseline=B1)`, *Then* persisted ==
  `[planning/MASTER-PLAN.md]` exactly; `efforts_for_session_stage(sid,'research')` == `[research/r.md]`;
  the two sets are disjoint. **Falsification (must be in the test body):** compute the legacy
  `_produced_doc_rels(W)` (whole-tree `diff HEAD` ∪ porcelain) in the SAME state and assert it returns a
  SUPERSET containing BOTH `r.md` and `MASTER-PLAN.md` — proving the stage-scoped result is a strict subset.
- *Given* the same W: B2=HEAD; write `build/app.py` **uncommitted**, *When*
  `persist_session_stage_docs(...,'build','build',baseline=B2)`, *Then* persisted == `[build/app.py]`;
  `MASTER-PLAN.md` excluded (predates B2, clean).
- *Given* an effort whose build stage produced `app.py` and plan stage `MASTER-PLAN.md` (one sid), *When*
  `resolve_build_deliverable`, *Then* `app.py` (honest unresolved if no build signal), never
  `MASTER-PLAN.md`; *When* `backfill_build_deliverables`, *Then* it pins `app.py` only. *Given*
  `current_stage=='plan'` → resolved=False.

**Tests.** `tests/test_stage_baseline_persist_v12.py`, `tests/test_stage_deliverable_v12.py`. No UI.

---

## Wave 4 — Keystone B: stage-keyed summaries + schema heal + closed-stage read via `store_lane` (backend)

**Goal.** Each stage gets its own cached summary that resolves correctly even after `lane` flips. Fixes
the summary-key BLOCKER (R2; SK-3/A1/B5).

**Changes.**
- `summarizer.py`: thread an optional `stage` through `summarize_session`, `load_cached`, `summary_dir`,
  `_summary_json_path`/`_summary_md_path`, `session_blurb`, `session_doc_roles`; when `stage` given, cache
  dir = `<store_lane>/summaries/<sid>/<stage>/` (unchanged when absent). Bump `SUMMARY_SCHEMA_VERSION`
  2 → **3** (concrete int so the heal test is falsifiable); an older/missing version is a MISS.
- The CLOSED-stage read path resolves via the stage's recorded `store_lane` (from `stage_history`), NOT
  the record's current `lane` (which has flipped).

**Done-when.** Two stages of one session cache under distinct `<store_lane>/summaries/<sid>/<stage>/`
dirs; after the session's `lane` has flipped to a later stage, `load_cached(..., stage='research')` still
resolves the research summary via `store_lane`; an old single-key cache is a MISS.

**Given/When/Then.**
- *Given* an effort whose research stage cached a summary, *When* the lane has since FLIPPED to `build`
  (`current_stage=='build'`), *When* `load_cached(..., stage='research')`, *Then* it resolves via
  `stage_history[research].store_lane`, NOT the current `lane`; AND `load_cached(stage='research') !=
  load_cached(stage='plan')` (no collision).
- *Given* a pre-bump (`SCHEMA_VERSION<3`) single-key cache at the OLD path, *Then* `load_cached` returns
  MISS (heals on next gen).

**Tests.** `tests/test_stage_summary_key_v12.py`. No UI.

---

## Wave 5 — `finish_stage`: non-reaping durability refactor (backend, regression-only)

**Goal.** Factor the persist+summarize keystone out of `kill` so a stage boundary persists+summarizes
WITHOUT reaping the worktree or marking the record terminal — with `kill` behavior provably unchanged.
Fixes SK-7; isolates the delicate `kill` surgery (SEQ-4).

**Changes.**
- `terminal_session.finish_stage(sid, stage, store_lane, project_id=None)` — `persist_session_stage_docs`
  (W3) + schedule the stage summary (W4), against the live worktree, **no reap, record stays RUNNING**.
- `terminal_session.kill` refactored to call `finish_stage` (current stage) then reap — its observable
  behavior (persist + boneyard + worktree removal + terminal status) **identical to today**.

**Done-when.** `finish_stage` persists+summarizes a live effort's current stage with the worktree intact
and the record non-terminal; `kill` still persists, records the boneyard entry, removes the worktree, and
marks the record terminal exactly as before (regression GREEN).

**Given/When/Then.**
- *Given* a live effort, *When* `finish_stage`, *Then* docs persist (W3) + summary scheduled, worktree
  still on disk, record still RUNNING, no boneyard entry.
- *Given* a live session, *When* `kill`, *Then* identical to pre-refactor: docs persisted, boneyard
  `killed` entry recorded (when material), worktree removed, record terminal (regression assertions over
  the existing v8/v10 kill tests — they stay GREEN).

**Tests.** `tests/test_finish_stage_noreap_v12.py` + the existing kill/boneyard suites stay GREEN. No UI.

---

## Wave 6 — `advance_stage`: in-session relabel+save + lock + idempotency (backend)

**Goal.** Advancing a stage keeps the SAME session, injects nothing into the PTY, and is concurrency-safe.
Fixes SC1 core; A7 concurrency; SEQ-9 (grass-dev acceptance).

**Changes.**
- `terminal_session.advance_stage(sid, to_stage=None, mode="manual"|"auto", project_id=None)` — take
  `paths.WRITE_LOCK`; validate a live effort of `kind in {'trio','grass-dev'}`; `to_stage` is the next
  stage; **idempotent** (no-op if `current_stage >= to_stage`); set `effort_managed=True`; `finish_stage`
  the current stage (W5); `record_stage_baseline` for the new stage; `set_current_stage`. **Inject NOTHING
  into the PTY** by default. (mode='manual' MAY accept `load_skill=True` to write one skill-load turn —
  explicit opt-in, default False; mode='auto' never writes.) Returns the updated record.
- `POST /api/rnd/advance_stage` (token-authed) → `advance_stage(mode='manual')`.

**Done-when.** Advancing a research effort to plan keeps the same `session_id`+`worktree_path`, persists+
summarizes research, flips `current_stage`, sets `effort_managed=True`, with the session-id SET unchanged
and ZERO PTY bytes written; a concurrent manual+auto race yields exactly one advance.

**Given/When/Then (worktree-only AND conversation-only).**
- *(worktree-only)* *Given* a live research effort with docs in its worktree only, *When*
  `advance_stage(sid,'plan','manual')`, *Then* same `session_id`+`worktree_path`; `set(list_sessions ids)`
  unchanged; `current_stage=='plan'`; research stage entry `state=='done'` with a `summary_ref`; plan
  entry `state=='active'`; `effort_managed==True`; **PTY buffer delta == 0**.
- *(conversation-only — the load-bearing case)* *Given* a live research effort whose ONLY output is
  transcript content seeded into its stub PTY read buffer via `pty_manager.write` (NO file, NO
  `record_effort`), *When* `advance_stage(sid,'plan','manual')`, *Then* research persists via the v11.1
  transcript-snapshot path (`research/<short-sid>-transcript.md` committed + tagged `(sid,'research')`),
  `current_stage=='plan'`, session-id set unchanged, **PTY buffer delta beyond the seeded transcript == 0**.
- *Given* `advance_stage` called twice (manual+auto race under the lock), *Then* exactly one persist + one
  summary + one flip; the second is a no-op.
- *Given* a `grass-dev` effort, *When* `advance_stage`, *Then* accepted (covers W11's reuse).

**Tests.** `tests/test_advance_stage_v12.py`, `tests/test_advance_stage_conversation_v12.py`. No UI.

---

## Wave 7 — `detect_stage_progress` + the COMPLETE retirement map + term_sessions rewire (backend)

**Goal.** Auto-advance fires only on a high-precision on-disk signal (never PTY scrape), and EVERY legacy
session-minting path is gated off for `effort_managed` efforts so two advance models can never coexist.
Fixes SC1; SK-1/A3/A5/B4/B7; **C1/C2/C3/C4** (complete map + correct discriminator).

**Changes.**
- `terminal_session.detect_stage_progress(sid)` — on-disk only: research→plan iff a COMMITTED
  `MASTER-PLAN.md`+`IMPLEMENTATION-PLAN.md` pair with commit-time **newer than the stage start** exists;
  plan→build iff a committed EXECUTION-LOG / build product exists. **Reads ZERO PTY bytes.** Idempotent;
  conversation-only stages do NOT auto-advance (manual Advance →'s job — stated honestly).
- **Complete retirement map — gate on `effort_managed` at EVERY minting site:**
  `auto_advance_planning_to_build` AND its call sites: the `term_kill` handler branch
  (`anchor_gui.py:~11925`, **C1**), the `finish_to_build` handler (`:~12686`), and `reconcile_and_advance`
  (`:~11020`); the `/api/rnd/advance_session` + `/api/rnd/finish_to_build` handlers; and BOTH
  `_PROJECT_WINDOW_JS` buttons — the research **"Advance to Planning →"** bar AND the planning **"Finish →
  Build →"** bar (**C2**). Each early-returns (no mint) when the subject `effort_managed==True`. They stay
  fully live for legacy (`effort_managed==False`) records, so the v6/v8/v10/v11 healthcheck walks pass
  unchanged (**C3**).
- `anchor_gui`: rewire the `term_sessions` refresh to call `detect_stage_progress` for `effort_managed`
  efforts (instead of `reconcile_and_advance`).

**Done-when.** A committed plan-set auto-advances an effort once (zero PTY reads); none of the six legacy
minting paths spawns a session for an `effort_managed` effort (session-id set unchanged at each); all
legacy walks still mint as before for `effort_managed==False` records.

**Given/When/Then.**
- *(pos)* *Given* an effort whose worktree gains a COMMITTED MASTER-PLAN.md+IMPLEMENTATION-PLAN.md pair
  newer than the stage start, *When* `detect_stage_progress`, *Then* it advances to plan ONCE (idempotent
  on re-poll), `set(list_sessions ids)` unchanged, ZERO PTY bytes read.
- *(neg, isolation)* *Given* a PTY buffer echoing "Crucible loaded" + a WORKING-TREE (uncommitted)
  MASTER-PLAN.md (no committed pair), *When* `detect_stage_progress`, *Then* NO advance (requires a
  committed pair newer than stage start) — proving it neither scrapes the PTY nor fires on uncommitted files.
- *(retirement, parametrized over ALL six paths)* *Given* an `effort_managed` effort at plan/DONE, *For
  each of* {`auto_advance_planning_to_build`, the `term_kill` branch, the `finish_to_build` handler,
  `reconcile_and_advance`, `POST /api/rnd/advance_session`, `POST /api/rnd/finish_to_build`}, *When*
  invoked, *Then* it early-returns and `set(list_sessions ids)` is identical (set-equality, not count).
- *(legacy intact)* *Given* a synthetic legacy planning record (`effort_managed==False`, as the v10/v11
  walks build), *When* the kill/auto-advance path runs, *Then* a build session IS minted (legacy behavior
  preserved).

**Tests.** `tests/test_detect_stage_progress_v12.py`, `tests/test_retire_auto_advance_v12.py` (all six
paths + legacy-intact). No UI.

---

## Wave 8 — Context-relief handoff (warn + one-click) + restart recovery (backend)

**Goal.** When context fills (or on click), the effort continues in a fresh session that JOINS the same
effort; a restart mid-effort recovers without loss. Fixes SC2; F6/B6/B8/C7.

**Changes.**
- `terminal_session.context_fullness(sid)` → stdlib turn/byte-budget heuristic → `{ratio, over_threshold}`.
- `terminal_session.handoff_to_fresh(effort_id_or_sid, project_id=None)` — `finish_stage` current stage →
  `prepare_stage_handoff` (v11.1) builds the real doc-referencing prompt → `start_session(effort_id=<same>,
  effort_managed=True)` with the prompt as a **pending paste** (nothing auto-submitted). Old session's
  current stage entry → `state=='done'`, worktree NOT reaped.
- `terminal_session.recover_interrupted_efforts()` — on boot/reconcile, an `effort_managed` record RUNNING
  but whose PTY is gone: persist the active stage (W5), mark that stage entry `state=='interrupted'` (a
  literal distinct from `done`/`failed`), keep reopenable to continue the SAME stage (a fresh session
  inheriting `effort_id`). NOT auto-advanced; NOT auto-spawned.
- Endpoints: `GET /api/rnd/context_status?session=` (read-only) + `POST /api/rnd/handoff_to_fresh`
  (token-authed). `anchor_gui` calls `recover_interrupted_efforts` on the reconcile path.

**Done-when.** A one-click handoff yields a NEW session (distinct id) with the SAME `effort_id`, the prior
stage persisted, the next prompt held UNSENT; a simulated restart marks the active stage `interrupted`
(not DONE), no doc loss, reopenable, no auto-spawn.

**Given/When/Then (worktree-only / conversation-only).**
- *Given* a running effort at `current_stage=='plan'` with plan docs in its worktree, *When*
  `handoff_to_fresh(effort_id)`, *Then* `new.session_id != old.session_id` AND `new.effort_id ==
  old.effort_id`; plan docs persisted+committed; `new.pending_paste==<prompt>` and `paste_flushed==False`;
  `pty_manager.read_since(new_sid,0)` contains the greet marker but NOT the prompt body (held unsent per
  the v11.1 base-count guard); `old.worktree_path` still exists (not reaped); old plan stage `state=='done'`.
- *Given* `context_fullness` over threshold, *When* `GET /api/rnd/context_status`, *Then*
  `over_threshold==true`.
- *(restart)* *Given* an `effort_managed` effort RUNNING at build with UNCOMMITTED build docs, simulate
  PTY-gone via `pty_manager.kill(sid)` WITHOUT `terminal_session.kill` (the reconcile-dead state), *When*
  `recover_interrupted_efforts`, *Then* build docs persist (worktree-only), the build stage entry
  `state=='interrupted'` (≠ done, ≠ failed), the effort is reopenable to continue build (fresh session
  inherits `effort_id`), `set(list_sessions ids)` shows no auto-spawned build, and the v9 anchor-repo/
  live-member guard is not tripped.

**Tests.** `tests/test_context_handoff_v12.py`, `tests/test_restart_recovery_v12.py`. No UI (the banner
is W10).

---

## Wave 9 — Effort view-layer: group chains into efforts (NEW `effort_view.py`) + dedup/drift (backend)

**Goal.** Legacy chains and new single-session efforts render uniformly as efforts, from a derived,
drift-safe, deduped view. Fixes SC7; F4/SK-6/A4/B9.

**Changes.**
- NEW `effort_view.py` (stdlib only; added to `dist_manifest.txt`): `build_effort_view(folder, pid)` —
  group registry records by `chain_id`; emit ONE effort per chain `{effort_id (chain root), current_stage
  (most-advanced member), stage_history (synth from members → each member's persisted docs + cached
  summary), status (newest member), live_worktree?}`. A new v12 single-session effort (already carrying
  `stage_history`) passes through as itself. **Rebuilt from the registry on every call** (a cache, not a
  source); a deleted member drops (no ghost stage); **deduped** so a chain member that is ALSO a live
  session carrying `stage_history` renders the effort exactly once (live status wins). Guarded like
  `project_move` (never the Anchor repo; reads, never reaps, live members). `effort_for_session(folder,
  pid, sid)`.
- `anchor_gui._gather_efforts(pid)` returns the view for the render layer (W10/W11); legacy
  `_gather_project_sessions` retained for fallback.

**Done-when.** A project with a legacy 3-member chain AND one new single-session effort renders exactly
two efforts (no double tiles, no ghost stages); deleting a chain member drops only that stage; building
twice is idempotent; the migration-overlap case (a chain member also live with `stage_history`) renders
exactly once.

**Given/When/Then.**
- *Given* a research→plan→build chain (3 records) + one new effort record with `stage_history`, *When*
  `build_effort_view`, *Then* exactly 2 efforts; the chain effort `current_stage=='build'` with 3 stages.
- *Given* the chain's plan member deleted, *When* rebuilt, *Then* research+build only (no ghost), no crash.
- *(dedup, SK-6)* *Given* a chain whose build member is ALSO present as a live registry session carrying
  `stage_history`, *When* `build_effort_view`, *Then* exactly ONE effort for that `chain_id` (len==1; live
  status wins).
- *Given* two builds, *Then* idempotent (equal); *Given* the Anchor repo, *Then* the guard holds.

**Tests.** `tests/test_effort_view_v12.py`, `tests/test_effort_view_drift_v12.py`. No UI.

---

## Wave 10 — Wire Layout-D live: effort-view board + bottom dock (terminal + summary-on-top + Advance + warn) (UI-gated)

**Goal.** The W2 skeleton goes live: headline/shelves driven by the effort view; the dock attaches a
real terminal with summary-on-top + a draggable height splitter + Advance + the context-full warn banner;
the home dashboard rows reflect efforts. Fixes SC1/SC2/SC3 render; SEQ-1/2/7; A9/B10.

**Changes.**
- `_PROJECT_WINDOW_JS` + render: bind the headline cards + collapsible shelves to `_gather_efforts` (W9);
  selecting an effort/tile opens the SINGLE bottom dock (replaces any floating stack): title bar (stage
  track + min/max/close + distinct **Kill → Boneyard**), **summary on top (full width)** via reused
  `_renderSplitSummary`/`_loadPanelSummary`, a **draggable vertical splitter**, a **full-width terminal**
  whose height the user drags (reuse WS→SSE transport + xterm mount/fit/ResizeObserver with a **debounced**
  splitter-drag fit). Wire **Advance →** (→ `/api/rnd/advance_stage`) and the **context-full warn banner**
  (polls `/api/rnd/context_status` → one-click `/api/rnd/handoff_to_fresh`). The stage track relabels +
  the tile migrates zones on refresh.
- `anchor_gui`: home dashboard project rows reflect efforts (running-effort presence, latest objective,
  current stage) via the effort view; `GET /api/rnd/projects_html` covers the in-place refresh.

**Done-when.** Clicking an effort opens the dock with summary-ABOVE-terminal, a live attached terminal
that stays attached + fits while the splitter is dragged; Advance relabels in place with no new session;
the warn banner appears on `over_threshold` and one click hands off; home rows show effort state; matches
the mockup (+ named deltas); John signs off.

**Given/When/Then.**
- *Given* a live effort, *When* its tile is clicked, *Then* the dock shows the summary panel ABOVE a
  full-width terminal (DOM order asserted), the terminal attaches, the stage track reflects `current_stage`.
- *(Playwright, machine-checkable)* *When* the splitter is dragged, *Then* (a) the xterm element is still
  in the DOM AND its transport `readyState===OPEN` (evaluate in-page), (b) a typed char round-trips into
  the terminal buffer after the drag, (c) `terminal.cols/rows` changed (fit ran). *When* **Advance →**
  clicked, *Then* `/api/rnd/advance_stage` is called and the stage track/zone updates with the session-id
  set unchanged. *Given* `context_status.over_threshold`, *Then* the warn banner renders; *When* clicked,
  *Then* `/api/rnd/handoff_to_fresh` is called once.
- *(neg)* *Given* no effort selected, *Then* no dock body bound (negative DOM).

**Tests.** `tests/test_layoutd_live_v12.py` (DOM pos+neg + render-smoke) +
`tests/test_layoutd_live_playwright_v12.py` (click→dock-bound-to-effort_id, drag-splitter-WS-open+echo,
Advance-no-new-session, warn-banner). Screenshot vs `_mockups/dashboard_D_headline_shelf.html` (dock open)
+ **John sign-off**.

---

## Wave 11 — Grass two-pane workbench (one session/idea) + General + Boneyard (UI-gated)

**Goal.** Grass becomes the approved one-session-per-idea workbench (retiring the grass second-advance);
General + Boneyard surface in Layout-D. Fixes SC5/SC6; A10/C4.

**Changes.**
- `effort_history`: collapse the per-(idea,lane) `dev_sessions` map to a single stage-carrying dev session
  per idea (reuse W6 `advance_stage` within grass; the dev session is `kind=='grass-dev'`,
  `effort_managed=True`). **Retire the grass second-advance:** gate `advance_grass_research_to_plan` +
  `/api/rnd/grass_advance` + its JS button OFF for `effort_managed` ideas (route to in-session
  `advance_stage`), leaving them live for the legacy v10/v11.1 walks (same `effort_managed` discriminator —
  C4). **Back-compat:** an existing idea with two `dev_sessions` renders the most-advanced as the single
  workbench session with a stage history; no orphan. `grass_workbench_data` returns the single-session shape.
- `anchor_gui` + `_PROJECT_WINDOW_JS`: render `_mockups/grass_2_workbench.html` — left idea list (capture,
  search, filter chips, ✕→Boneyard); right workbench (header w/ auto-saved indicator + **Migrate to
  project ↑** + Archive snapshot; idea text; auto-gathered History + deliverable links; ONE session
  terminal + engine toggle; NO Research/Plan buttons). Migrate = `export_grass_to_project`; ✕ =
  `delete_grass_idea` → Boneyard. General opens in the dock like any effort. Boneyard per-project tab
  (reuse `GET /api/rnd/boneyard` + search).

**Done-when.** The grass workbench matches the mockup (two panes, one session, no R/P split, Migrate↑,
✕→Boneyard); the grass second-advance is gated off for v12 ideas; an old two-session idea still renders +
works; General opens in the dock; the Boneyard tab lists + searches discarded entries; John signs off.

**Given/When/Then.**
- *Given* a grass idea, *When* the workbench renders, *Then* DOM has a left list + a right workbench with
  ONE session area and NO research/plan buttons (positive); *Given* a pre-v12 idea with
  `dev_sessions={research,plan}`, *Then* one session surfaces with a stage history, no orphan (back-compat).
- *Given* an `effort_managed` grass idea, *When* `advance_grass_research_to_plan` is invoked, *Then* it
  early-returns (no second grass session minted); the in-session `advance_stage` is used instead. *Given* a
  legacy idea (`effort_managed==False`), *Then* the old grass-advance still works (legacy walks pass).
- *(Playwright)* *When* **Migrate to project ↑** clicked, *Then* `export_grass_to_project` called (idea
  stays, `grass_origin` stamped); *When* ✕, *Then* `delete_grass_idea` → the idea appears in the Boneyard
  tab (assert `GET /api/rnd/boneyard` contains it, not just that a toast fired).
- *Given* a project with discarded material, *When* the Boneyard tab + search, *Then*
  `GET /api/rnd/boneyard?q=` filters (positive); empty → honest empty state (negative).

**Tests.** `tests/test_grass_workbench_v12.py` (DOM pos+neg + back-compat + grass-advance retirement) +
`tests/test_grass_playwright_v12.py`. Screenshot vs `_mockups/grass_2_workbench.html` + **John sign-off**.

---

## Wave 12 — CLI mirror + `check_rnd_v12_surface` + distro + docs (PROJECT DONE)

**Goal.** Read seams mirrored; the whole surface walked fully stubbed; invariants + docs closed out.

**Changes.**
- `anchor.py` CLI (read-only): `rnd efforts <pid>` → the effort view (id · current_stage · status · stage
  count); `rnd effort <pid> --session <id>` → ordered `stage_history` (SAFE projection — never worktree/
  branch); `rnd effort-deliverable <pid> --session <id>` → the build-stage resolved deliverable (honest
  unresolved). No CLI for the interactive advance/handoff/dock.
- `anchor_healthcheck.check_rnd_v12_surface` — fully stubbed (stub PTY + stub stream-json + temp git
  project + temp worktree base + temp data dir). Walk: (1) effort-record back-compat normalize +
  `effort_managed==False` for a legacy record; (2) start a trio effort (`effort_managed=True`) →
  `S0=set(list_sessions ids)`; advance research→plan via a COMMITTED plan-set (worktree-only); advance
  plan→build **conversation-only** (seed the stub PTY buffer, no file → transcript-snapshot persist);
  after EACH advance assert `set(list_sessions ids)==S0` (zero mint) + `current_stage` flipped + per-stage
  summary dirs disjoint + per-stage doc attribution disjoint; (3) build-stage deliverable resolves the
  build product WITH a plan-stage `MASTER-PLAN.md` **decoy** asserted NOT resolved; (4) exercise ALL six
  retired paths on the effort → assert set unchanged; AND a legacy (`effort_managed==False`) record still
  mints a build; (5) `handoff_to_fresh` → new session, SAME `effort_id`, pending paste UNSENT; (6)
  `recover_interrupted_efforts` → active stage `interrupted` (≠ done), reopened continuation inherits the
  SAME `effort_id`, no auto-spawn; (7) `build_effort_view` groups a legacy chain + a new effort with no
  double tiles / no ghost stage; (8) grass one-session back-compat + grass-advance retirement +
  ✕→Boneyard capture. Restore all forced env + temp dirs; never bind `:8777`.
- `distro.py`: `effort_view.py` stdlib-only + in `dist_manifest.txt`; scan green; Playwright never in
  product.
- Docs: `CLAUDE.md` (v12 section + endpoints + CLI), memory `anchor-rnd-surface-v12.md` + `MEMORY.md`
  pointer, `SESSION-HANDOFF.md`.

**Done-when.** `python -m pytest -q` GREEN (≥ baseline + v12 tests); `check_rnd_v12_surface` passes fully
stubbed (all 8 steps); `distro.py` scan green; CLI mirrors return honest SAFE data; docs updated. PROJECT
DONE (pending John's per-UI-wave sign-offs + the final merge/deploy sign-off).

**Given/When/Then.**
- *Given* the stubbed v12 surface, *When* `check_rnd_v12_surface`, *Then* all 8 steps pass + tear down; no
  `:8777`; env restored.
- *Given* a project with efforts, *When* `rnd efforts`/`rnd effort --session`, *Then* SAFE projections (no
  worktree/branch); honest empty when none.
- *Given* `distro.py` scan, *Then* green (new module stdlib-only + in manifest; no Playwright in product).

**Tests.** `tests/test_cli_efforts_v12.py`, `tests/test_healthcheck_v12.py`, distro scan test. PROJECT DONE.

---

## Out of scope (Grasscatch)

Calendar / Anchor-as-app; changing the trio skills; git/gh seam changes; multi-user/cloud; a literal
forced single Claude context across skills; destructive rewrite of stored session/chain records;
boneyard restore/global search; new handoff *features* beyond the context-relief valve.

---

## Appendix — Shark-Tank Round 2 (Stage 2, 2026-06-21)

3 fresh-context Sharks on the wave plan: **Sequencing = BLOCK**, **Testability = BLOCK**, **Completeness =
SHIP-WITH-FIXES**. ≥2-agree / high-value findings folded in: complete retirement map across all SIX
session-minting paths + the grass second-advance, gated on a positive **`effort_managed`** discriminator
(C1/C2/C3/C4) so legacy healthcheck walks pass unchanged; exact git mechanic for stage-scoped persist with
a legacy-superset falsification assertion (B1/B2); the conversation-only advance GWT + set-equality
assertions (B3/B4); closed-stage summary read via `store_lane` + concrete schema bump to 3 (B5); concrete
restart-recovery sim + `interrupted` literal (B6); handoff same-`effort_id`/unsent-paste asserts (B8);
Playwright machine-checkable pass conditions (B10); split over-bundled W2→W3/W4 and W3→W5/W6/W7 (SEQ-4/5);
UI shipped early as a static skeleton (W2) then wired live (W10) resolving the false "UI ships early"
sequencing (SEQ-1/2); home-row render pulled out of the closer (SEQ-7); mockup "no handoff" caption
reconciled with SC2 (C5). Result: 12 atomic, independently-gateable waves; `locate-plan.mjs` re-run clean.
Convergence authority: John.
