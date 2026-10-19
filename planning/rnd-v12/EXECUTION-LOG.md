# Anchor R&D Surface v12 — "Efforts" — Execution Log

> Foreman appends per-wave EXECUTE / ADVERSARIAL-REVIEW / FIX / GATE history here.
> Frozen design: `MASTER-PLAN.md`. Build plan: `IMPLEMENTATION-PLAN.md`.
> Branch: `foreman/rnd-surface-v12` (off master `f2e0e40`, v11.1 merged + deployed). Baseline GREEN 1266.

## Wave 1 — Effort record: stage fields + `effort_managed` + `effort_id` passthrough + back-compat normalize — GREEN ✅

- **EXECUTE:** `session_registry._normalize` gains `kind`/`current_stage`/`stage_history`/`seeded_stages`/
  `effort_id`/`effort_managed` (back-compat defaults; `effort_managed` default False); `register_session`
  + `update_session` thread the new fields; new helpers `effort_root`/`stage_entry`/`set_current_stage`
  (closes prior active entry → appends new, under the re-entrant `WRITE_LOCK`). `terminal_session.start_session`
  gains `effort_id=`/`effort_managed=` passthrough (no behavior change for existing callers).
  `anchor_gui._effort_zone(record)` accessor (render unchanged this wave). New `tests/test_effort_record_v12.py`.
- **GATE (orchestrator-run):** `python -m pytest -q` → 1273 passed, 1 skipped (baseline 1266 + 7).
- **REVIEW (2 independent, adversarial):** both GO-WITH-NITS, zero BLOCKERs. Nits applied at source:
  R1-01 re-derive `current_stage` on `""` not just `None`; R2-1 deep-copy `stage_history` entries in
  `_normalize` (kill the W4/W5 aliasing hazard). +2 regression tests.
- **RE-GATE:** 1275 passed, 1 skipped. **Converged.**
- **Forward note (R2-2):** a freshly-started effort has `current_stage` but an empty `stage_history`;
  W3/W6 MUST establish the first stage entry (or consumers guard `stage_entry()==None`). R2-3: the only
  sanctioned stage flip is `set_current_stage` (keeps `current_stage`+`lane` in sync).

## Wave 2 — Layout-D static skeleton render (UI-gated) — GREEN ✅ (John signed off)

- **EXECUTE:** `render_project_window_html` swapped to `_render_layoutd_html` (Latest-Research headline +
  collapsible older-research shelf; Latest-Plan/Build headline + shelf; persistent right column with Grass +
  Deliverables; inert bottom-dock chrome; "+ New effort" disabled/labeled "(wired in W10)"). New renderers
  `_layoutd_zones`/`_render_layoutd_*`; `toggleShelf` JS (flips `.collapsed`); `/api/rnd/board_html`
  repointed. Driven by the EXISTING `_gather_project_sessions` (no effort_view/advance dependency).
  ~17 prior UI tests migrated from the retired 5-col `.p2lanes` board to Layout-D landmarks (intent
  preserved; refreshBoard/one-tile-per-session/status-dedup/seeded term_start/panel-open all kept). New
  `tests/test_layoutd_skeleton_v12.py` (render-smoke brace-balance + DOM pos/neg) +
  `tests/test_layoutd_skeleton_playwright_v12.py` (Chromium shelf-toggle `.collapsed` flip).
- **GATE (orchestrator-run, authoritative):** 1280 passed, 1 skipped.
- **REVIEW (2 independent, adversarial):** both GO-WITH-NITS, zero BLOCKERs. Acted on:
  **F1 (MAJOR, R2):** Plan/Build headline picked the OLDEST plan (effort views had no epoch → merge
  sort degenerate) → fixed by stamping `_eff_created_at` on the effort view + using it in `_sv_created_at`;
  + regression test (newer build beats older plan for the headline). **W2-R1 (MINOR, R1):** the
  engine-selector migration left a dead-token positive assertion (`assert 'engtog' in html`) → made honest
  (kept real negatives; the rendered engine affordance is re-asserted in W10). Dead `.p2lanes`/kanban
  helpers left in place (W10 reuses the tile helpers).
- **RE-GATE:** 1281 passed, 1 skipped. **Converged + UI sign-off (screenshot `_mockups/w2_layoutd_screenshot.png`).**

## Wave 3 — Keystone A: per-stage baseline commit + stage-scoped persist + stage deliverable — GREEN ✅

- **EXECUTE:** `effort_history.record_stage_baseline` (HEAD sha as baseline) + `persist_session_stage_docs`
  (EXACT git: `diff <base>..HEAD` ∪ `diff <base> --` ∪ `status --porcelain -uall` additions, MINUS
  prior closed-stage paths via `efforts_for_session_stage`; tags efforts by `(session_id, stage)`;
  best-effort, idempotent) + `efforts_for_session_stage`. `deliverables.resolve_build_deliverable`/`backfill`
  stage-scoped for efforts (build-stage docs only; honest unresolved off-build; legacy path byte-unchanged).
  Build stage also persists products (not just docs). New `tests/test_stage_baseline_persist_v12.py` +
  `tests/test_stage_deliverable_v12.py` incl. the Shark-B1 legacy-superset falsification + B2 uncommitted
  build product + deliverable decoy. Legacy `persist_session_docs`/`_produced_doc_rels` untouched.
- **GATE:** 1291 passed, 1 skipped.
- **REVIEW (2 independent):** both GO-WITH-NITS. Two MAJORs = two sides of the build-accept heuristic:
  **W3-R1** over-capture (swept `.pyc`/`.dll`/`.coverage`/bundle trees) + **W3-R2** under-capture (dropped
  a ROOT product like `anchor_gui.py`, the canonical Anchor deliverable). Fixed: build-accept switched from
  a dir-allowlist to a **junk denylist** (`_BUILD_JUNK_EXT` + dotfiles excluded) accepting root + any-depth
  products, PLUS a bundle-sweep cap (`_MAX_BUILD_PRODUCTS=25` non-doc → docs-only, rely on explicit pin).
  +3 tests (root captured / junk excluded / bundle capped). W3-N1 (prior-stage lane coupling) = documented
  forward-note for the W6 wiring (callers must pass the canonical store_lane). Verified good: git mechanic,
  falsification genuineness, legacy byte-unchanged, idempotency, backfill C6 protection, distro clean.
- **RE-GATE:** 1294 passed, 1 skipped. **Converged.** (Keystone unwired until W6 — by design.)

## Wave 4 — Keystone B: stage-keyed summaries + schema heal + closed-stage read via store_lane — GREEN ✅

- **EXECUTE:** `summarizer.py` threads optional `stage=None` through `summary_dir`/`_summary_json_path`/
  `_summary_md_path`/`load_cached`/`summarize_session`/`_write_cache`/`session_blurb`/`session_doc_roles`;
  stage cache = `<store_lane>/summaries/<sid>/<stage>/` (stage=None = legacy path, byte-identical). New
  `stage_store_lane(record, stage)` resolves a CLOSED stage's lane from `stage_history` (not the flipped
  current lane). `SUMMARY_SCHEMA_VERSION` 2→3 (old/missing = MISS, session AND project caches).
  Per-stage lock key preserves the run-once-under-concurrency guarantee. New `tests/test_stage_summary_key_v12.py`
  (distinct dirs + no-collision + lane-flip resolution + schema heal + stage=None legacy), stub-runner driven.
- **GATE:** 1298 passed, 1 skipped.
- **REVIEW (2 independent):** both GO-WITH-NITS, zero BLOCKERs. ≥2-agree MINOR: `session_doc_roles(stage=…)`
  is an unused/inert param (by design — resolution is lane-driven) → tightened the docstring to say so.
  Non-blocking nits noted: `stage=''` collapses to legacy (no caller passes it); the schema bump needs a
  post-deploy rescan to repopulate caches (consistent with prior bumps). Verified: legacy byte-identical,
  clean MISS (no crash) on old caches, correct store_lane resolution, lock-key safe, scope = summarizer.py only.
- **DOCSTRING-ONLY FIX** (no re-gate needed for a comment). **Converged.**

## Wave 5 — finish_stage non-reaping durability refactor (regression-only) — GREEN ✅

- **EXECUTE:** new `terminal_session.finish_stage(sid, stage, store_lane, project_id)` (persist+summarize the
  current stage against the LIVE worktree; NO reap, NO terminal, NO boneyard; best-effort) + shared primitive
  `_persist_current_stage` (splits on the open `stage_history` entry: v12 effort → W3 stage-scoped persist +
  W4 stage summary; legacy/no-open-stage → exact pre-v12 `capture_session_docs`). `kill` changed by ONE line
  (`capture_session_docs` → `_persist_current_stage`) — observable behavior byte-identical (persist set,
  boneyard 'killed', worktree reap, terminal status, return dict). `_trigger_background_stage_summary` reads
  the `ANCHOR_PROACTIVE_SUMMARY` gate directly (never imports anchor_gui). New `tests/test_finish_stage_noreap_v12.py`.
- **GATE:** 1304 passed, 1 skipped (the only run-of-record).
- **REVIEW (2 independent):** both GO-WITH-NITS, zero BLOCKERs. Kill verified byte-identical; finish_stage
  non-destructive; idempotent (content-addressed persist + doc_count SET not increment); summary seam threads
  stage + never poisons cache; honest no-op on unknown/legacy. Nits all optional (plan said "kill calls
  finish_stage" but impl calls the shared primitive per MASTER-PLAN §4.3 — better; `_active_stage_entry`
  returns last-open if >1 open, but the one-open invariant holds). No code fix needed.
- **Forward note (W6):** `advance_stage` must OPEN the first stage entry (a fresh effort's `stage_history` is
  still [] → finish_stage falls to legacy whole-tree until the first entry exists). **Converged.**

## Wave 6 — advance_stage: in-session relabel+save + lock + idempotency + endpoint — GREEN ✅

- **EXECUTE:** `terminal_session.advance_stage(sid, to_stage, mode, project_id, load_skill)` — under
  `paths.WRITE_LOCK`; validates a live `trio`/`grass-dev` effort; idempotent (rank-based no-op on a
  manual+auto race); `finish_stage` current (W5, no reap) → `record_stage_baseline` + `set_current_stage`
  flips stage+lane; **ZERO PTY bytes by default** (only `mode='manual' + load_skill=True` writes one turn;
  `auto` never). `start_session(effort_managed=True)` now OPENS the first stage entry + baseline (the W5/R2-2
  fix). Conversation-only capture: `_snapshot_transcript_doc` wired into the stage-scoped persist branch.
  `POST /api/rnd/advance_stage` (token-authed, SAFE projection). New `tests/test_advance_stage_v12.py` +
  `tests/test_advance_stage_conversation_v12.py`.
- **GATE:** 1315 passed, 1 skipped.
- **REVIEW (2 independent):** R1 **GO** (SC1 zero-PTY-injection verified, no deadlock, idempotent, legacy
  start unchanged, no W7 creep). R2 **BLOCK** with 2 findings — NOT formally ≥2-agree (R1 rated the first a
  MINOR), but both real + cheap, so FIXED: **W6-R2-02** invalid/garbage `to_stage` was reported `ok:True
  'already-advanced'` → now an honest `ok:False 'invalid-stage'` (HTTP 400) + reject non-adjacent
  `'invalid-stage-skip'`; **W6-R2-01** the closing stage entry now gets a `summary_ref` locator
  (`_stamp_stage_summary_ref`); **W6-R2-05** endpoint projects `stage_history` to SAFE fields (drops
  `baseline_ref`/`store_lane`). +3 tests. R2 confirmed the core (zero-mint set-equality, zero-PTY-byte,
  conversation capture) genuinely sound.
- **RE-GATE:** 1318 passed, 1 skipped. **Converged.**

## Wave 7 — detect_stage_progress + the COMPLETE retirement map + term_sessions rewire — GREEN ✅

- **EXECUTE:** `terminal_session.detect_stage_progress` (ON-DISK only — `git diff <baseline>..HEAD`, ZERO
  PTY; research→plan on a committed MASTER+IMPL pair, plan→build on a committed EXECUTION-LOG/build product;
  idempotent; conversation-only never auto-advances). **COMPLETE retirement map gated on `effort_managed`
  ONLY** (Shark C3) across all six minting sites + grass: `auto_advance_planning_to_build` (function-level
  → covers `reconcile_and_advance`), the `term_kill` planning-kill branch, the `finish_to_build` + 
  `advance_session` HTTP handlers, `effort_history.advance_grass_research_to_plan` (→ `/api/rnd/grass_advance`),
  + the two `_PROJECT_WINDOW_JS` advance bars. `term_sessions` refresh rewired to call detect for effort_managed
  efforts (legacy stays on reconcile_and_advance). New `tests/test_detect_stage_progress_v12.py` +
  `tests/test_retire_auto_advance_v12.py`.
- **GATE:** 1337 passed, 1 skipped.
- **REVIEW (2 independent):** both GO-WITH-NITS. **≥2-AGREE MAJOR (W7-R2-01/R1-W7-01):** the JS guard on the
  two advance bars was INERT — `effort_managed` never reached the JS session record, so the bars still rendered
  for an effort (SC1 mint still blocked server-side by the tested 409, so a UX-not-safety defect). FIXED:
  propagate `effort_managed` into the JS MANAGED + FINISHED records, `_registry_session_view`, the
  minitile/headline `data-effort-managed` attr, and `_synthSessionRecord` — guard now live on both live +
  historical paths. Also R1-W7-03: detect no longer diffs the empty-tree for a plan/build stage with an empty
  baseline (no false-fire). R1-W7-02 perf already mitigated (no-next-stage early-return precedes the git diff).
  +2 tests. (The rendered-bar Playwright assertion belongs to W10's UI gate, which rebuilds the advance UI.)
- **RE-GATE:** 1339 passed, 1 skipped. **Converged.** All six server paths gated + legacy walks intact.

## Wave 8 — context-relief handoff (warn + one-click) + restart recovery — GREEN ✅

- **EXECUTE:** `terminal_session.context_fullness` (byte-budget heuristic, env-overridable, honest 0.0),
  `handoff_to_fresh` (finish_stage current [no reap] → prepare_stage_handoff prompt → start_session with the
  SAME effort_id + pending paste UNSENT [v11.1 contract] → continues the SAME stage, not an advance; old
  worktree kept), `recover_interrupted_efforts` (RUNNING-but-PTY-gone effort → persist active stage [no reap]
  + mark stage `state='interrupted'` [≠done/failed] + re-status IDLE; no auto-spawn/advance; idempotent;
  legacy-skipped). `GET /api/rnd/context_status` + `POST /api/rnd/handoff_to_fresh` + reconcile wiring. New
  `tests/test_context_handoff_v12.py` + `tests/test_restart_recovery_v12.py`.
- **GATE:** 1351 passed, 1 skipped.
- **REVIEW (2 independent):** R1 GO-WITH-NITS (verified same-stage/effort_id/unsent-paste/recovery in
  ISOLATION). R2 **BLOCK — W8-R2-01 (real doc-loss, read-only repro):** the GUI poll ran
  `reconcile_and_advance` BEFORE `recover_interrupted_efforts`; reconcile blanket-marked a PTY-gone effort
  DONE so recover skipped it → stage never 'interrupted', uncommitted docs LOST. The gate + tests missed it
  (recover tested only in isolation). FIXED: **reordered** the poll — recover runs FIRST (claims the effort
  interrupted+IDLE), then reconcile leaves it alone + a GUI-ORDER regression test asserting no doc loss.
  R1-F1: added the explicit `new_rec['current_stage']=='plan'` (continue-not-advance) assertion. W8-R2-02
  (handoff not idempotent on double-click) documented as accepted (spec-scoped, one-click endpoint).
- **RE-GATE:** 1352 passed, 1 skipped. **Converged.** (Lesson: an integration-order bug hid behind
  isolation-only tests + a gate that didn't exercise the wired poll order — the adversarial integration repro caught it.)

## Wave 9 — Effort view-layer: group chains into efforts (NEW effort_view.py) — GREEN ✅ (backend complete)

- **EXECUTE:** NEW `effort_view.py` (stdlib-only, in `dist_manifest.txt`) — `build_effort_view(folder, pid)`
  groups registry records by `chain_id` → ONE effort per chain (effort_id=root, current_stage=most-advanced,
  synth stage_history research→plan→build referencing each member's docs+cached summary, SAFE member
  projections — no worktree/branch); a single-session v12 effort passes through; **rebuilt from the registry
  each call (derived cache, NOT a stored source); deduped (migration-overlap → one effort, live wins); a
  deleted member drops (no ghost); read-only (never mutates/reaps)**. `effort_for_session`. `anchor_gui._gather_efforts`
  delegates; legacy `_gather_project_sessions` retained as fallback. New `tests/test_effort_view_v12.py` +
  `tests/test_effort_view_drift_v12.py`.
- **GATE:** 1362 passed, 1 skipped.
- **REVIEW (2 independent):** both GO-WITH-NITS, zero BLOCKERs. Verified read-only/non-destructive (SC7),
  dedup (len==1, live wins), drift no-ghost, SAFE projection, stdlib-only + distro green, idempotent.
  ≥2-agree NIT (EV-1/F1): the Anchor-repo guard was a tautological no-op → REMOVED (read-only purity is the
  real, tested guarantee; dropped the now-unused `paths` import). F3: added an `effort_id` sort tiebreaker
  (defined total order). **Accepted NITs:** F2 (per-member docs+summary read twice — bounded O(members), NOT
  the global-scan perf hazard) left as-is. **EV-2 → W10 REQUIREMENT:** two same-stage members emit duplicate
  stage_history entries (matches the W9 spec "one entry per member"); **W10's stage-track renderer MUST light
  nodes from `current_stage` (presence-based) and tolerate duplicate stage labels** (do not iterate
  stage_history 1:1 for the 3-node track).
- **RE-GATE:** 1362 passed, 1 skipped. **Converged. Backend (Waves 1–9) COMPLETE** — next are the UI-gated
  waves W10 (live Layout-D + dock) + W11 (grass/general/boneyard), then W12 (CLI + healthcheck + docs).

## Wave 10 — Wire Layout-D live: effort-view board + bottom dock (UI-gated) — GREEN ✅ (John sign-off pending)

- **EXECUTE:** the board binds to the effort view (`_build_effort_index`/`_effort_data_attrs`; tiles stamp
  `data-effort-id`+`data-current-stage`); the SINGLE bottom dock goes live — `openEffortDock` (summary-on-top
  via `_renderSplitSummary`, draggable splitter with rAF-debounced fit, full-width live terminal reusing
  WS→SSE + xterm), `_renderDockTrack` (EV-2: lights nodes by `current_stage` presence, not stage_history),
  `dockAdvance`→`/api/rnd/advance_stage` (same session, refreshBoard migrates the tile), context-full warn
  banner polling `/api/rnd/context_status`→one-click `/api/rnd/handoff_to_fresh`, `dockKill`→Boneyard,
  `dockDelete` (v9 true-delete), live `+ New effort`. Home rows reflect effort current_stage (cache-only).
  New `tests/test_layoutd_live_v12.py` (DOM pos/neg + render-smoke) + `tests/test_layoutd_live_playwright_v12.py`
  (machine-checkable: bind+attach / drag-keeps-attached+echo / Advance-no-mint / warn→handoff).
- **GATE:** 1370 passed, 1 skipped.
- **REVIEW (2 independent):** both GO-WITH-NITS, zero formal BLOCKERs; migrated tests verified NOT weakened.
  R1 **MAJOR F1:** a live session reachable from BOTH the effort tile (→dock) and its session-bar chip
  (→openPanel) could double-mount (openPanel guarded PANELS, not DOCK). FIXED: `openPanel` routes an
  already-docked session to `openEffortDock` (one live surface per session) + a Playwright guard test.
  R2 NITs FIXED: `live` gated on `status==='running'` (never mount a reaped PTY); deterministic warn-banner
  precondition; build-at-build Advance-hidden test added. **F2 → W11 REQUIREMENT:** the dock "replaces the
  floating stack" only for EFFORT tiles in W10; `#panelStack`/openPanel stays for grass/boneyard/chain-nav/
  chips. **W11 must either retire `#panelStack` or the EXECUTION-LOG records the coexistence as final.**
- **RE-GATE:** 1372 passed after F1 + the 3 NIT fixes.
- **JOHN UI SIGN-OFF (with 3 refinements, applied):** (1) **EMBED the dock** — it was `position:fixed`
  floating; now `position:relative` in-flow (reads as part of the page; maximize still expands to full-viewport).
  (2) **Two new-session controls** — `+ New research` (`#newResearchBtn`) + `+ New plan/build`
  (`#newPlanBuildBtn`) replacing the single `+ New effort` (an effort can start at research OR plan). (3)
  **Per-effort metrics** — `effort_view.effort_rollup` + `GET /api/rnd/effort_rollup` render the selected
  effort's `Σ tok · time · $` in the dock summary. Clarified for John WHERE cost shows: the **masthead**
  project rollup (`Σ tok · $ · time · sessions`, lifetime/30d) + the **per-effort dock** line; and the
  **previous-versions** link = the per-zone collapsible **"Hide/Show all N older … sessions"** shelf line.
  The button rename broke 4 tests asserting `#newEffortBtn` (the full gate caught them, the agent's targeted
  run did not) — all 4 migrated honestly to the two new buttons. Re-screenshot `_mockups/w10_layoutd_live_screenshot.png`.
- **FINAL GATE:** 1377 passed, 1 skipped. **Converged + John signed off.**

## Wave 11 — Grass two-pane one-session workbench + General-in-dock + Boneyard tab — GREEN ✅ (John sign-off pending)

- **EXECUTE:** grass = ONE `effort_managed` `grass-dev` session per idea (`develop_grass_workbench`,
  advances research→plan IN-SESSION via advance_stage; back-compat fallback resolves a pre-v12 two-
  `dev_sessions` idea to its most-advanced session); `grass_workbench_data` single-session shape; the W7
  grass second-advance retirement now also covers the `workbench` key. Two-pane workbench UI to
  `grass_2_workbench.html` (left list + capture/search/filter/✕; right: auto-saved + Migrate↑
  [export_grass_to_project] + Archive [archive_grass_session] + idea text + auto-History + ONE session +
  engine toggle, NO research/plan). General opens in the W10 **dock** (`newGeneral`; no stage track/Advance
  for lane=='general'). Boneyard per-project tab. F2: `#panelStack` retained ONLY for the grass workbench +
  Boneyard tool panels (documented); the dock owns all live sessions. New `tests/test_grass_workbench_v12.py`
  + `tests/test_grass_workbench_playwright_v12.py`.
- **GATE:** caught **8 regressions the agent's targeted run missed** (the "Open terminal"→newGeneral rename
  broke 7 tests asserting the old `newTermSession('general','claude')` wiring; the one-session grass broke
  the v10.1 two-terminal reflow test). All 8 migrated honestly to the new affordances/selectors (no weakening).
- **REVIEW:** R2 GO-WITH-NITS (one-session collapse correct, landmarks present, Migrate/✕→Boneyard verified).
  Fixed: **W11-R2-02** `develop_grass_workbench` check-then-mint now under WRITE_LOCK (TOCTOU double-mint
  guard, parity with advance_stage); **W11-R2-01** grass Playwright now asserts transport readyState OPEN.
  **R1 STALLED (21m, 0 bytes) — orchestrator covered its scope:** audited the grass test reductions
  (`test_grass_two_terminals_v10` −28 asserts, etc.) → LEGITIMATE plan-cited retirement of the retired
  two-terminal grass (MASTER-PLAN §4.7 one-session collapse + John's approved mockup), NOT §5 weakening;
  one-session intent re-asserted by the v12 grass suite; legacy grass-advance walks GREEN (18); back-compat
  covered. **Documented debt:** 8 legacy grass JS fns (`developGrass`/`toggleGrassTerminal`/
  `advanceGrassToPlan`/`saveGrassRefinement`/`archiveGrassSession`/`_setGrassToggle`/`_grassTermBox`/
  `_renderGrassArchives`) are now dead/unreferenced — left for a follow-up cleanup (removing from the RAW JS
  string isn't worth the brace risk for a NIT). Screenshot `_mockups/w11_grass_workbench_screenshot.png`.
- **RE-GATE:** 1390 passed, 1 skipped (net +13). **John signed off the grass-workbench screenshot.**
- **REVIEW 1 (finished at 38m — slow, not stalled; HTTP-server-truth audit):** GO-WITH-NITS, **confirms the
  orchestrator audit** — §5 NOT violated (removed asserts coupled to the retired two-terminal UI or replaced
  by equal-or-stronger HTTP server-truth assertions; +85 new asserts), back-compat SOLID (reproduced the
  reaped-plan→research fallback), legacy retirement CORRECT, Migrate/✕→Boneyard verified via
  `GET /api/rnd/boneyard`, General-in-dock coherent. Its F1 (8 fails) = the PRE-fix tree (already migrated →
  1390 GREEN). Fixed R1's one real find: a no-op `assert ... in js or True` in `test_grass_advance_v10.py`
  → a real `inspect.getsource` route-registered assertion. Dead-JS (F2) = the documented debt.
- **Converged + John signed off.** (8 dead legacy grass JS fns left as documented W-next cleanup debt.)

## Wave 12 — CLI mirror + check_rnd_v12_surface + distro + docs — GREEN ✅ (PROJECT DONE)

- **EXECUTE:** `anchor.py` read-only CLI mirrors — `rnd efforts <pid>` (effort view: id·current_stage·status·
  stage_count), `rnd effort <pid> --session <id>` (ordered stage_history, SAFE: drops baseline_ref/store_lane/
  worktree/branch), `rnd effort-deliverable <pid> --session <id>` (build-stage deliverable, honest unresolved;
  MASTER-PLAN decoy never resolves). `anchor_healthcheck.check_rnd_v12_surface` — the 8-step fully-stubbed walk
  (back-compat normalize · advance R→P→B in ONE session [committed-worktree-only + conversation-only PTY-buffer-
  seeded] with session-id SET-equality/zero-mint + disjoint per-stage docs + distinct summary dirs · build
  deliverable + decoy · retirement [effort gated, legacy mints] · handoff same effort_id + unsent paste ·
  recover interrupted≠done no-spawn · effort_view no double/ghost · grass one-session + ✕→Boneyard), registered
  in main() after v11.1; hermetic (env restored in finally, never :8777, PTYs reaped, no row leak). distro:
  effort_view.py stdlib-only + in dist_manifest.txt, scan green. Docs: CLAUDE.md v12 section + SESSION-HANDOFF.md
  (BUILT, awaiting sign-off). New `tests/test_cli_efforts_v12.py` + `test_healthcheck_v12.py` + `test_distro_scan_v12.py`.
- **GATE:** 1424 passed, 1 skipped (full suite, clean — purely additive).
- **REVIEW (2 independent):** R1 GO-WITH-NITS (healthcheck hermetic + non-vacuous verified empirically;
  ENV_LEAK {}, LEAKED_ROWS 0), R2 **GO** (CLI SAFE, distro green, docs accurate — every listed endpoint exists).
  Fixed: **V12R1-01** `_rmtree_force` (chmod-on-error rmtree so a temp git repo's read-only `.git/objects` is
  actually removed, not leaked into %TEMP% — shared helper, benefits all surfaces) + the teardown test now
  asserts REMOVAL; **V12R1-02** the per-stage summary-dir assertion now holds the lane constant + varies ONLY
  `stage` (isolates the stage-key — the prior form also varied lane). NIT-01 (CLI unknown-session asymmetry) left
  (cosmetic, both print cleanly). V12R1-03 (5 AM walk touches real .anchor/sessions.json transiently, self-healing)
  = pre-existing multi-surface pattern, out of scope.
- **RE-GATE:** 1424 passed, 1 skipped. **Converged.**

---

## 🏁 v12 "Efforts" — PROJECT DONE (2026-06-22)

All **12 waves GREEN** on `foreman/rnd-surface-v12` (off master `f2e0e40`, v11.1). Final gate **1424 passed,
1 skipped** (baseline 1266 → +158). Every wave: EXECUTE → orchestrator full-suite gate → 2 independent
adversarial reviewers → fix → re-gate. The 3 UI waves (W2 skeleton, W10 live dock, W11 grass) each have
John's screenshot sign-off. **Adversarial review caught real bugs the green suite hid** every round (doc
mis-attribution, summary mis-keying, the incomplete retirement map, the W8 reconcile-before-recover doc-loss,
the W10 double-mount, rename-stale tests). **NOT merged / NOT deployed — awaiting John's whole-branch sign-off
→ `git merge --no-ff` + `nssm restart anchor` (elevated) + rescan the 6 active projects.**

### Post-build tweak (John, 2026-06-22, during review)
- **Grass Catcher right-column panel: collapsible idea list.** Added a caret toggle (`#grassMiniTog` →
  `toggleGrassMini`) that folds the idea items IN THE TILE (`#grassMiniList.collapsed`), keeping +capture /
  Open-workbench reachable; default expanded. +2 tests (DOM presence + Playwright collapse-click). Gate:
  1426 passed, 1 skipped. (John reviewed v12 via an isolated preview on :8799; this was his one tweak.)

### Deploy (2026-06-22) — DONE
- John ran `nssm restart anchor` (the branch working tree = v12, so the restart loaded v12). Service GET / → 200,
  v12 + grass toggle live. **Rescanned the 6 real projects** (Anchor/Agentic-Home/MBA Teaching AI/aurora/
  Transformer Math/Skill Foundry) → all 200. (The live registry also carries ~22 leftover TEST-cruft projects +
  duplicate Anchor/aurora registrations — a registry-tidy item for later, not rescanned.) Merged v12 → master.










