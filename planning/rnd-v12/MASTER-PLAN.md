# Anchor R&D Surface v12 — "Efforts" (continuity-first single-session trio) · MASTER PLAN

> **Status:** Stage 1 (Master Plan) — REVISED after Shark-Tank Round 1 (all 3 Sharks BLOCKed the
> first "literally one shared session/worktree/context" draft; John's lived-workflow evidence
> reframed the model to **continuity-first with a context-relief handoff**). Approved by John for
> the model + sequencing 2026-06-21. Frozen design lives here; the wave-by-wave build plan lives in
> `IMPLEMENTATION-PLAN.md`. Approved mockups: `_mockups/dashboard_D_headline_shelf.html` (dashboard)
> + `_mockups/grass_2_workbench.html` (grass catcher).

---

## 1. North Star (LOCKED 2026-06-21)

> **Anchor's per-project dashboard lets John run a unit of work as a single continuous "effort"
> that flows Research → Plan → Build in ONE session by default — the stage transition is a
> lightweight relabel, not a managed handoff — with a fresh-session handoff only as a
> context-relief valve, and with every effort's docs, deliverable, and summary durably saved and
> reopenable, surfaced on the simple Layout-D dashboard.**

### Success criteria (each testable)

- **SC1 — Continuity-first in-session stages.** An effort is ONE session by default; you work
  R→P→B in the same conversation, each skill loading as the work naturally progresses. "Advance"
  is a **relabel + persist + summarize** of the completed stage — it spawns **no new session** and
  injects **nothing** into your conversation. Advance is auto-detected (high-precision on-disk
  signal) with a manual **Advance →** override. The dashboard tile relabels and migrates from the
  Research zone to the Plan/Build zone.
- **SC2 — Context-relief handoff.** When the context window gets too full (or you choose), Anchor
  **warns and offers a one-click handoff** to a fresh session that JOINS the same effort (same
  tile/lineage), carrying the docs + summary forward via the proven v11.1 machinery. The handoff
  is the exception, never the default; nothing is auto-submitted on your behalf.
- **SC3 — Layout D dashboard.** Renders the approved Layout D: latest-research headline +
  collapsible older-research shelf; latest-plan/build headline + collapsible shelf; a persistent
  right column (Grass + Deliverables); a bottom docked window with **summary on top** and a
  **full-width, height-resizable terminal**.
- **SC4 — Always durable, no Save button.** Every effort auto-persists per-stage docs + a generated
  per-stage summary + (for builds) an auto-resolved-or-pinned deliverable. No Save button. A summary
  is written **before** a session closes. Efforts are reopenable and can seed new efforts.
- **SC5 — Grass workbench.** Grass = the approved two-pane workbench: ONE session per idea (no
  Research/Plan split), auto-loaded history + deliverable links, no Save button, **Migrate to
  project ↑**, ✕ → Boneyard.
- **SC6 — General + Boneyard retained.** General session kept (bare; deliverables linked; summary
  before close). Per-project Boneyard captures eliminated content.
- **SC7 — Legacy grouped, not rewritten.** Existing research→plan→build chains render AS efforts via
  a **view-layer grouping** (no stored-record rewrite; self-heals from the registry; rollback =
  ignore the view). No destructive migration.
- **SC8 — Invariants preserved.** Python stdlib-only (lone `pywinpty` exception); hermetic tests
  (stub PTY + stub stream-json + temp dirs; never bind `:8777`; never touch real data/network;
  `ANCHOR_PROACTIVE_SUMMARY` off in tests); Playwright dev-only; `distro.py` scan green (new module
  added to `dist_manifest.txt`); every UI wave gated by rendered-DOM (pos+neg) + real
  Playwright/Chromium + screenshot-vs-mockup + John's sign-off; `check_rnd_v12_surface` walks the
  new surface fully stubbed.

### Non-goals (Grasscatch — explicitly OUT)

- No calendar / "Anchor-as-app" work (separate efforts).
- No changes to the trio **skills** themselves (researchPrime / Crucible / Foreman).
- No change to the git/gh seams (`worktrees._git` / `ANCHOR_GH_CMD`).
- No multi-user / cloud / auth-model change.
- No literal "one Claude context forced through all three skills" — continuity is default but the
  context-relief handoff exists precisely so context never has to be force-shared.
- No destructive rewrite of existing session/chain records.

---

## 2. The problem v12 fixes, and the model

The v6–v11.1 model runs the trio as **separate sessions linked by a chain**, with a managed
handoff between each. Six versions went into making that handoff reliable — and it is still the
single most bug-prone seam and awkward in daily use. **But the fix is not to delete the session
boundary; it is to stop *managing a handoff* at every boundary.**

**Lived-workflow evidence (John, 2026-06-21):** working R→P→B in one Claude session is natural —
after research, Claude itself offers to plan; after planning, to build — and it does **not** need a
silent handoff to do so. The continuity *is* the value, and it already works conversationally.

**The continuity-first model:**

- **Default = one session.** You progress R→P→B in the same conversation; each skill loads as you
  go (you or Claude drive it). Anchor does not interrupt.
- **Advance = relabel + save.** Anchor *observes* the progression (a plan/build doc appears, or you
  click Advance), **persists + summarizes** the stage just completed, and **migrates the tile** to
  the next zone. It spawns no session and writes nothing to your PTY.
- **Handoff = context-relief valve.** Only when the context window fills (or you choose) does Anchor
  **warn + offer a one-click handoff** to a fresh session that continues the *same effort* — reusing
  the v11.1 `prepare_stage_handoff` machinery (persist docs → real doc-referencing prompt →
  HANDOFF.md/NEXT-PROMPT.md → pending paste, nothing auto-submitted).

This keeps clean context available *when needed* without throwing away continuity by default, and it
turns the Shark Tank's BLOCKERs from premise errors into small, named engineering items.

---

## 3. Current architecture (brownfield ground truth — Confirmed; file:line verified in Stage-0 ingest)

- **Session record** (`session_registry._normalize`): `session_id, project_id, lane, backend,
  worktree_path, branch, status, created_at, label, seeded, seed_text, parent_session_id, chain_id,
  pending_paste, paste_flushed, grass_origin`. Lane effectively immutable after register.
- **Lanes** (`terminal_session._valid_lanes` / `LANE_SKILL`): trio = research / plan(planning) /
  build; bare = general, grass. Status→color: running=green, needs-attention/done=amber, failed=red,
  idle=grey.
- **Chains** (`session_registry.chain_for` / `chain_members`, `_CHAIN_LANE_ORDER`): research→plan→
  build via `parent_session_id` + shared `chain_id`.
- **Effort storage** (`effort_history.py`): per-lane `<lane>/efforts/<job_id>.pointer.json` +
  `<lane>/index.json`; **each persisted-doc effort is already tagged with the originating
  `session_id`** (v8 keystone). `efforts_for_session_id`, `persist_session_docs` (copy+commit a
  session's produced docs into the main project **before reap**; `_produced_doc_rels` =
  `git status --porcelain` ∪ `git diff --name-only HEAD` — **a whole-worktree diff against the
  branch base**, ⚠ the doc-attribution crux), `delete_session_efforts` (drop pointers/summary, keep
  docs), `FOLD_LANES`.
- **Lifecycle** (`terminal_session.py`): `start_session` → worktree → bare PTY → register RUNNING →
  seed once. `kill` persists docs → reaps PTY+worktree → Boneyard `killed`. `delete_session`
  kills-if-live → drops record+efforts (keeps docs) → Boneyard `deleted`. ⚠ `kill` is the ONLY
  durable-summary+persist path and it ALSO reaps the worktree.
- **Auto-advance (the legacy handoff path — to be retired for efforts)**:
  `auto_advance_planning_to_build` (fires for any planning-lane session reaching DONE with no child
  build → mints a new build session); `reconcile_and_advance` (wired into the `term_sessions`
  refresh poll); `prepare_stage_handoff` (v11/v11.1); endpoints `/api/rnd/advance_session`,
  `/api/rnd/finish_to_build`; the `_PROJECT_WINDOW_JS` "Advance to Planning →" buttons.
- **Deliverables** (`deliverables.py`): `resolve_build_deliverable` is **session-scoped**, explicit
  signals only (session product member → pin/marker member → single-build fallback), honest
  unresolved. `backfill_*`, `launch_deliverable`, `pin_deliverable` (content-addressed, idempotent).
- **Summaries** (`summarizer.py`): cache keyed by **`(folder, project_id, lane, session_id)`**
  (`summary_dir`/`load_cached` take `lane`, NOT stage); generate-twice + grounding filter;
  `SUMMARY_SCHEMA_VERSION=2` heal; `summarize_project`, `session_blurb`, `short_summary_text`,
  `tile_blurb`, `session_doc_roles`. Render reads cache only.
- **Boneyard** (`boneyard.py`): per-project content-addressed index; killed/deleted/grass-deleted;
  capture wired best-effort.
- **Grass** (`effort_history.py`): idea record `{job_id, status raw/refined/promoted, title, notes,
  refinements (dev-N), dev_sessions {lane→sid}, exported_to, archives, grass_origin}`;
  `grass_workbench_data`, `develop_grass_idea`, `export_grass_to_project`, `archive_grass_session`,
  `advance_grass_research_to_plan`.
- **Render** (`anchor_gui.py`): `render_project_window_html` (f-string, double-brace) +
  `_PROJECT_WINDOW_JS` (RAW single-brace) — opposite brace rules ⚠. 5-col `.p2lanes` Kanban;
  `_gather_project_sessions` merges registry + effort sessions; panel manager
  (`openPanel`/`minimize`/`maximize`/`closePanel`=close-to-tile vs `killPanel` vs `deletePanel`);
  xterm mount+fit+ResizeObserver; transport WS `term_ws` → SSE `term_stream2` + POST `term_input2`,
  token-authed.

**Reuse-over-rewrite insight:** persistence + deliverable + summary + boneyard + the v11.1 handoff
are already session-tagged and largely fit. v12 adds: (a) stage fields on the record, (b) a
**per-stage baseline commit** so the existing whole-worktree diff attributes per stage, (c) an
in-session **relabel-style advance** that retires the legacy auto-advance for efforts, (d) a
**context-relief handoff** reusing v11.1, (e) an **effort view-layer** grouping chains, and (f) the
Layout-D render. Only the effort view/migrate helper is a new module.

---

## 4. The v12 design

### 4.1 Effort = a session that carries a stage (extends `session_registry`)

Add to the normalized record (back-compat defaults in parens; old records normalize with no crash):

- `kind`: `"trio" | "general" | "grass-dev"` (derived from lane on normalize when absent).
- `current_stage`: `"" | "research" | "plan" | "build"` (init from the starting lane; "" for non-trio).
- `stage_history`: append-only `[{stage, store_lane, started_at, ended_at|null, baseline_ref,
  seeded:bool, summary_ref|null, doc_count}]`. The active stage's entry has `ended_at=null`.
  **`store_lane` is recorded per stage** so the closed stage's docs/summary resolve under the lane
  they were written in (fixes the Analyst A1 read-path issue).
- `seeded_stages`: list (audit).
- `effort_id`: the effort's stable id = the root session_id (a fresh effort: its own id; a
  context-relief continuation: the original effort_id, inherited via `start_session(effort_id=…)`).
- `effort_managed` (bool, default **False**): the v12 discriminator. Set **True** ONLY by the v12
  entrypoints (the "+ New effort" start, `handoff_to_fresh`, `advance_stage`/`finish_stage`). Legacy
  records — including the synthetic projects in the v6/v8/v10/v11 healthcheck walks — stay False. **Every
  retirement gate keys on `effort_managed`, never on `kind`/`current_stage`** (which legacy records also
  carry), so the legacy walks keep passing unchanged (Shark C3).
- `lane` is retained as the **current store-lane** (research/planning/build) and flips with
  `current_stage`. **The board routes by `current_stage`/`kind` only** — every `chain_members`/lane
  sort consumer is audited before lane is made mutable (Skeptic SK-8).

**Board routing (SC1):** a trio effort with `current_stage=="research"` → Research headline+shelf;
`current_stage ∈ {plan,build}` → Plan/Build headline+shelf (the tile migrates). `general`/`grass-dev`
never appear in the trio zones.

### 4.2 Per-stage baseline commit + stage-scoped persist & summary (fixes F2/SK-2/SK-3/A1/A6)

The keystone change that makes in-session stages attribute cleanly:

- At each stage **start** (effort start, and each advance), record a **baseline marker** — a commit
  (or tree-ish) in the effort's worktree — stored as `baseline_ref` on the stage_history entry.
- `persist_session_docs` gains a stage-scoped variant. The produced-doc set for a stage is computed
  with **exact git commands** (Shark B2 — "porcelain since baseline" is not a real construct):
  `git diff --name-only <baseline>..HEAD` (committed-since) ∪ `git diff --name-only <baseline> --`
  (working-tree vs baseline) ∪ `git status --porcelain -uall` additions — **minus** paths already
  attributed to a closed prior stage. Only what THIS stage produced, not everything since the worktree
  was cut.
- Persisted efforts are tagged `(session_id, stage)`; add `efforts_for_session_stage`.
- **Summaries keyed by `(session_id, stage)`**: thread a `stage` arg through
  `summarize_session`/`load_cached`/`summary_dir`/`session_blurb`/`session_doc_roles`; cache under
  `<store_lane>/summaries/<session_id>/<stage>/`. Bump `SUMMARY_SCHEMA_VERSION` (stale single-key
  caches → MISS → heal). The read path resolves a closed stage via its `stage_history.store_lane`.
- **Deliverable**: `resolve_build_deliverable` **and** `backfill_build_deliverables` (the rescan path —
  Shark C6) are fed ONLY the **build-stage** doc set (filter by the build stage_history entry), so a
  plan-stage MASTER-PLAN.md can never be mis-resolved/auto-pinned as the build product. Honest
  unresolved when `current_stage != build` or no signal.

### 4.3 In-session advance = relabel + save (extends `terminal_session`; retires legacy auto-advance)

`advance_stage(session_id, to_stage=None, mode="manual"|"auto", project_id=None)`:

1. Take `paths.WRITE_LOCK` (or a per-session lock). Validate live trio effort; `to_stage` is the
   **next** stage; **idempotent** — if `current_stage >= to_stage`, no-op (fixes concurrency A7 /
   double-advance from a manual+auto race).
2. **Persist** the current stage's docs (stage-scoped, §4.2).
3. **Schedule** the current stage's summary (background; `summary_ref` on the closing entry).
4. Close the current stage_history entry (`ended_at`); record the new stage's `baseline_ref`; append
   the new entry; flip `current_stage` + `lane`.
5. **No session spawn. No PTY injection.** (Manual mode MAY optionally offer "load <next skill> for
   me" — an explicit, opt-in convenience that writes one skill-load turn; it is NOT the default and
   NOT how the common path works. The default is: you/Claude already moved on; Anchor just relabels.)
6. The tile migrates zones on next render.

`detect_stage_progress(session_id)` (called from the `term_sessions` refresh): **on-disk
high-precision signal only** — research→plan auto-advances only when a committed MASTER-PLAN.md +
IMPLEMENTATION-PLAN.md pair newer than the stage start appears; plan→build only on a committed
EXECUTION-LOG / build product. **Never** scrapes the PTY for a skill name (avoids the v11.1
seed-echo false-fire). Conversation-only stages do not auto-advance — that's the manual Advance →'s
job (stated plainly so SC1's auto claim is testable and honest — Analyst A5).

**Retirement map (fixes SK-1/A3 + Shark C1/C2/C3/C4 — no two advance models):** gated on
`effort_managed==True` (NOT `kind`), EVERY session-minting path early-returns for an effort:
`auto_advance_planning_to_build` **and all its call sites** — the `term_kill` handler branch (C1), the
`finish_to_build` handler, and `reconcile_and_advance`; the `/api/rnd/advance_session` +
`/api/rnd/finish_to_build` handlers; **both** `_PROJECT_WINDOW_JS` advance bars — research
"Advance to Planning →" AND planning "Finish → Build →" (C2); and the grass second-advance
`advance_grass_research_to_plan` + `/api/rnd/grass_advance` + its button (C4). For legacy
(`effort_managed==False`) records they stay fully live, so the v6/v8/v10/v11.1 healthcheck walks pass
unchanged (C3). The healthcheck asserts an advanced effort spawns **zero** new sessions (session-id
set-equality) AND that a legacy record still mints.

`finish_stage` / non-reaping durability (fixes SK-7): factor the persist+summarize keystone out of
`kill` into a primitive that runs against the live worktree **without reaping** it, so a stage
boundary (and a "summary before close") never tears down the shared worktree. `kill` keeps calling
it, then reaps.

### 4.4 Context-relief handoff (warn + one-click) + restart recovery (SC2; fixes F6)

- A **context-fullness signal** (token/turn budget heuristic on the live session) raises a UI
  **warn banner**: "context getting full — hand off to a fresh session?" One click →
  `handoff_to_fresh(effort_id)`: persist current stage (§4.2) → `prepare_stage_handoff` builds the
  real doc-referencing prompt → start a fresh session that **inherits `effort_id`** (joins the same
  effort/tile/lineage) with the prompt as a **pending paste** (v11.1; nothing auto-submitted). The
  old session is marked done-stage; the effort continues. Auto and manual-only are NOT chosen
  (decision: warn + one-click).
- **Restart recovery:** on boot, an effort whose registry record is RUNNING but whose PTY is gone →
  persist whatever the active stage's worktree holds, mark the stage **interrupted** (not DONE),
  keep it reopenable to **continue the same stage** (a fresh session inheriting `effort_id`). A crash
  is not a "close"; SC4's summary-before-close fires on the orderly close + on this recovery persist.

### 4.5 Effort view-layer — group chains into efforts (NEW `effort_view.py`; fixes F4/SK-6/A4, SC7)

`build_effort_view(folder, project_id)` groups the project's registry records by `chain_id` and
returns ONE effort per chain **at render time** (a derived VIEW, not a stored rewrite):

- `effort_id` = chain root session_id; `stage_history` synthesized from the chain members (each
  member = one stage, referencing its already-persisted docs + cached summary); `current_stage` =
  most-advanced member; `status` from the newest member; live worktree if a member is running.
- New v12 efforts (single session carrying stages) are already efforts; legacy chains are *grouped*
  into the same shape — uniform render.
- **Self-healing & drift-safe:** the view is **rebuilt from the registry on every render/rescan**
  (a cache, never a source of truth). A member deleted from the registry simply drops from the view
  (no ghost stage). No `efforts.json` source-of-truth; rollback = stop calling the view. Idempotent.
  Guarded like v9 `project_move` (never the Anchor repo; reads, never reaps, live members).
- Deduped so a migrated chain + a new live session render the effort **exactly once** (no double
  tiles — Skeptic SK-6).

### 4.6 Layout D dashboard (rebuild `render_project_window_html` + `_PROJECT_WINDOW_JS`)

Per `_mockups/dashboard_D_headline_shelf.html`: Latest-Research headline + collapsible shelf;
Latest-Plan/Build headline + collapsible shelf; persistent right column (Grass + Deliverables); a
**single bottom docked window** (replaces the floating panel stack): title bar (stage track +
min/max/close + distinct **Kill → Boneyard** + the context-full warn banner + **Advance →**),
**summary on top (full width)**, a **draggable vertical splitter**, then a **full-width terminal
whose height the user drags**. Selecting any headline/little-tile opens it here. A **+ New effort**
affordance starts an effort at research (or plan) — stated explicitly (fixes F7).

**Reuse:** transport (`term_ws`/`term_stream2`/`term_input2`), xterm mount/fit/observer (with a
**debounced** splitter-drag fit — SK-9), `_renderSplitSummary`/`_loadPanelSummary`, status-light
classes, token auth, masthead + lifecycle + GitHub controls. **Rewrite:** 5-col grid → headline+
shelf; floating stack → single dock; split → summary-top / terminal-bottom. A **render-smoke test**
(import + non-empty balanced-brace HTML) runs BEFORE the Playwright wave so the f-string/RAW-string
boundary fails fast (A9).

**Engine note (F7):** Gemini is research-only. An effort started on Gemini that advances past
research either blocks the advance with an honest message, or (if the user opts in) the
context-relief/skill-load path relaunches on Claude — a documented, explicit exception, never
silent.

### 4.7 Grass two-pane workbench (extend `effort_history` grass + render; SC5)

Per `_mockups/grass_2_workbench.html`: left = idea list (capture, search, filter, ✕→Boneyard);
right = the selected idea's workbench (header with auto-saved indicator + **Migrate to project ↑** +
Archive snapshot; idea text; auto-gathered History; **ONE session** with engine toggle + one
terminal — no Research/Plan buttons). Collapse the per-(idea,lane) `dev_sessions` map into a single
stage-carrying dev session (reuse §4.3 advance within grass). **Back-compat:** an existing idea with
two dev_sessions renders the most-advanced as the single workbench session with a stage history; no
orphan; ✕/Migrate still work (fixes A10). Migrate = `export_grass_to_project` (copy up, idea stays,
`grass_origin`). ✕ = `delete_grass_idea` → Boneyard.

### 4.8 General + Boneyard (SC6)

General session unchanged (bare lane, summary-before-close, deliverables linked). Boneyard unchanged
(per-project; killing/deleting an effort or idea files its content). Both surfaced in the Layout-D
chrome.

---

## 5. Phasing (waves detailed in IMPLEMENTATION-PLAN.md)

- **Phase A — Effort backbone:** record stage fields + back-compat normalize; board routing by stage.
- **Phase B — Keystone fix:** per-stage baseline commit + stage-scoped persist/summary/deliverable.
- **Phase C — In-session advance:** `advance_stage` (relabel+save) + `detect_stage_progress` +
  retirement map + `finish_stage` non-reaping durability + concurrency lock.
- **Phase D — Context-relief handoff + restart recovery.**
- **Phase E — Effort view-layer** (group chains; drift-safe) + deliverable resolve/pin.
- **Phase F — Layout D UI** (headline+shelves+right column; then the bottom dock). [UI-gated]
- **Phase G — Grass workbench + General + Boneyard UI.** [UI-gated]
- **Phase H — Wire-to-live + hardening:** dashboard rows; CLI mirror; `check_rnd_v12_surface`
  (fully stubbed); distro scan; docs/CLAUDE.md/memory/SESSION-HANDOFF.

UI (the approved Layout D + grass) ships **early** on the chosen backbone (John's sequencing pick),
not gated behind the riskier core.

---

## 6. Risks & mitigations (post-Shark)

- **R1 — Doc mis-attribution across stages (BLOCKER, confirmed SK-2/F2).** *Mitigation:* per-stage
  baseline commit + stage-scoped diff (§4.2); `efforts_for_session_stage`; healthcheck asserts each
  stage's persisted set = only that stage's files.
- **R2 — Summary cache mis-key across stages (BLOCKER, SK-3/A1).** *Mitigation:* `(session, stage)`
  key + per-stage dir + `store_lane` read-resolution; bump schema version; heal stale caches.
- **R3 — Legacy auto-advance spawns sessions for an effort (BLOCKER, SK-1/A3).** *Mitigation:* the
  §4.3 retirement map gates off every legacy advance path for efforts; healthcheck asserts zero new
  sessions on advance + negative-DOM asserts the old buttons are gone.
- **R4 — Migration split-brain / stale index (MAJOR ×3, F4/SK-6/A4).** *Mitigation:* the §4.5 view
  is rebuilt-from-registry each render (a cache, not a source); drift-safe; deduped; rollback = stop
  calling it.
- **R5 — Context pollution degrades a skill (Contrarian F1).** *Status:* downgraded by John's
  lived-workflow evidence; *mitigation:* the context-relief handoff (§4.4) gives clean context
  whenever it's actually wanted, so context is never force-shared.
- **R6 — Re-seeding a live PTY is unproven (SK-4/A2).** *Mitigation:* the default advance injects
  NOTHING into the PTY (relabel+save only); the only PTY-writing path is the v11.1 handoff into a
  FRESH session (already proven) + the opt-in "load skill for me" convenience, both flush-after-greet
  with the v11.1 base-count guard captured from a re-seed cursor.
- **R7 — Foreman builds in a dirty shared worktree (F3).** *Mitigation:* per-stage baseline commits
  leave the tree in a clean committed state at build start; if a build needs a pristine checkout the
  context-relief handoff gives it one. Validated in the healthcheck build walk.
- **R8 — Restart mid-effort loses work (F6).** *Mitigation:* §4.4 restart recovery — persist active
  stage, mark interrupted (not DONE), reopenable to continue.
- **R9 — Concurrency: manual+auto advance race / advance-during-input (A7).** *Mitigation:* WRITE_LOCK
  + idempotency guard in `advance_stage`; both manual and auto go through it.
- **R10 — "UI looks done but isn't" + the f-string/RAW brace hazard (A9, the v4 lesson).**
  *Mitigation:* render-smoke (balanced-brace import) before Playwright; every UI wave gated by DOM
  pos+neg + Playwright/Chromium + screenshot-vs-mockup + John's sign-off. String-grep-only = HALT.
- **R11 — Grass two-session ideas break under the one-session model (A10).** *Mitigation:* §4.7
  back-compat render + test.
- **R12 — Scope (F5).** *Mitigation:* inclusion test (every wave → an SC); UI ships early decoupled
  from the core; reuse-over-rewrite is a hard rule.

---

## 7. Done-when (Master-Plan level)

On a real project: start an effort, work in research, **Advance →** (or auto on a committed plan
set) keeps the SAME session and migrates the tile to Plan/Build while persisting+summarizing the
research stage; each stage's docs attribute only to that stage; a build resolves (or you pin) a
deliverable from build-stage docs only; when context fills, a one-click handoff continues the same
effort in a fresh session; a service restart mid-effort recovers without loss; existing chains render
as efforts with no double tiles and no destructive rewrite; the Layout-D dashboard + bottom dock +
grass workbench match the approved mockups; and `check_rnd_v12_surface` is GREEN fully stubbed — all
invariants intact, merged only after your per-UI-wave sign-off.

---

## Appendix — Shark-Tank Round 1 (2026-06-21)

3 fresh-context Sharks (Skeptic / Contrarian / Analyst), each prompted to refute. **All 3 verdicts:
BLOCK.** ≥2-agree BLOCKERs: doc-attribution in a shared worktree (SK-2+F2); summary cache key across
stages (SK-3+A1); legacy auto-advance / orphaned advance endpoints spawn sessions (SK-1+A3). 3-way
MAJOR: migration split-brain (F4+SK-6+A4). Premise challenge (F1, context pollution) **resolved by
John's lived-workflow evidence** → the continuity-first model with a context-relief handoff, which
converts every BLOCKER into a named, testable engineering item folded into §4/§6 above. Convergence
authority: John (locked the revised model + sequencing 2026-06-21).
