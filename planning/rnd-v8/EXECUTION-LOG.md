# Anchor R&D Surface v8 — "Durable Artifacts" — Execution Log

> Per-wave EXECUTE / REVIEW / FIX / GATE history for the Foreman build of v8. Frozen
> plan: `MASTER-PLAN.md` + `IMPLEMENTATION-PLAN.md` (this folder). Branch:
> `foreman/rnd-surface-v8` (off master `80ead40`, which has v7 merged).

## Baseline

- **2026-06-16** — Branch `foreman/rnd-surface-v8` created off master (v7 merged).
  v7 baseline = **888 passed, 1 skipped**. GREEN floor; every wave holds or grows it.

## Wave records

### Wave 1 — Project bootstrap (auto git-init + starter CLAUDE.md) — GREEN (2026-06-16)

**Built (backend):** new `project_bootstrap.py` (reuses `worktrees._git`, no forked git):
`ensure_git_repo(folder)` — idempotent best-effort `git init` + initial commit honoring
`.gitignore` (no-op on an existing repo; clean `{"ok":False,"reason":"git-unavailable"}`
without raising when git absent); `ensure_claude_md(folder, name)` — writes a minimal
starter only when absent (NEVER overwrites); `bootstrap_project` (CLAUDE.md then git).
Wired (best-effort) into `select_existing_project` (was missing git init — the gap),
`create_new_folder_project`, and `discover_and_adopt` (covers both rescan + the open/
`GET /project/<id>` path). After bootstrap, `create_worktree`/research-start no longer
returns `not-a-git-repo` — the user's error is fixed.

**Orchestrator verification:** `tests/test_project_bootstrap_v8.py` (11) — init+idempotent+
honors-gitignore+git-absent-clean; CLAUDE.md created-when-absent + never-overwrites; register/
rescan paths bootstrap; **error-fixed** (pre-bootstrap create_worktree `not-a-git-repo` →
post-bootstrap ok). **Behavior change** (intended): updated `test_new_project.py` —
`test_create_new_folder_git_init_optional` → `test_create_new_folder_always_git_repo`
(every project is now a git repo + has a CLAUDE.md regardless of the legacy git_init flag).

**Gate:** **897 passed, 1 skipped** (+9). Backend-only. Commit: scoped.

<!-- WAVE 1 done -->
### Wave 2 — Trio document persistence (THE KEYSTONE) — GREEN (2026-06-16)

**Built (backend):** `effort_history.persist_session_docs(folder, pid, lane, session, worktree)`
— detects produced docs via `git status --porcelain -uall` ∪ `git diff --name-only HEAD` in
the worktree, filtered to `.md`/`.pdf` under planning/research/build/deliverables + bare trio
doc names (excludes `.anchor`/`.git`/node_modules/etc.); COPIES them into the main folder
(skips byte-identical); records DISCOVERED efforts with main-folder `artifact_path`s (so
`list_efforts`/`discover_recent_plan_set` resolve them); COMMITS scoped (`git add --` only the
produced docs + pointer/index, never `-A`; refuses the Anchor repo; message `anchor: <lane>
session <id8> docs`). Idempotent (re-persist → no commit), scoped (user's unrelated files
untouched), never raises. `terminal_session.capture_session_docs` (generalizes v6
`capture_plan_set`) wired into `kill` BEFORE `remove_worktree` (reap PTY → mark DONE →
persist → remove).

**Orchestrator verification:** `tests/test_doc_persistence_v8.py` (7) — copied+scoped-commit;
user's unrelated file never staged; **survive-reap** (kill → worktree gone, docs remain);
**build-worktree-contains** the plan docs; **discover-finds** them from main; idempotent;
no-docs honest no-op. v6 auto-advance/chain stay green (stub session → no worktree docs →
`no-docs` no-op).

**Handoff note (for Wave 4):** the gui `term_kill` captures the plan_set BEFORE kill, but
persistence now runs inside kill — Wave 4 must reorder so persistence precedes the plan-set
capture (or capture after kill) for the auto-advance to see freshly-produced docs.

**Gate:** **904 passed, 1 skipped** (+7). Backend-only. Commit: scoped.

<!-- WAVE 2 done -->
### Wave 3 — Link GitHub + Option-A auto-push — GREEN (2026-06-16)

**Built (UI + backend):** new `project_remote.py` (reuses `worktrees._git`): `link_github`
(mode=create → `gh repo create --private` THROUGH the `ANCHOR_GH_CMD` seam; mode=existing →
`git remote add`; degrades to paste-URL when gh absent), `set_auto_push`/`get_auto_push`
(per-project opt-in on the rnd_registry record), `push_project`, `auto_push_if_opted`,
`remote_status`. Endpoints (token-gated): POST `link_github`/`set_auto_push`/`push_now`,
GET `remote_status`. Header UI: "Link GitHub" → inline Create-new-private / paste-existing /
not-now prompt; once linked → `owner/repo` label + auto-push opt-in checkbox + "Push now".
`_auto_push_on_finish` wired into the kill/finish path — pushes ONLY when linked + opted.

**Build note:** the first execute agent hit a transient classifier/500 mid-wave (backend
landed, UI/tests cut off). Verified the partial tree was SAFE (this repo's remote unchanged,
no stray commits, gh/push all behind the `ANCHOR_GH_CMD` seam) and a continuation agent
finished the UI + tests + screenshot. The continuation **found+fixed a real bug**: the prior
agent referenced `_auto_push_on_finish` without defining it (NameError swallowed by try/except
→ auto-push silently never fired); now defined.

**Orchestrator verification:** `tests/test_github_link_v8.py` (+ `tests/stub_gh.py`) — link
create (seam stub → private, persisted) / existing (LOCAL BARE remote, no network) / opt-in /
auto-push-on-finish ONLY when linked+opted (push lands in the local bare remote; non-opted
never pushes) / manual push / gh-absent paste-only / all endpoints token-gated. NEVER real
network/gh/github.com. **Screenshot reviewed** — `_devtest/wave3_github.png`: header shows
`🔗 johncliechty/repo · ☑ auto-push · ↑ Push now`.

**Gate:** **921 passed, 1 skipped** (+17). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 3 done -->
### Wave 4 — Handoff that carries the documents — GREEN (2026-06-16)

**Built (backend + UI):** (1) **Generated handoff seed with real doc paths.**
`terminal_session._build_seed_for_plan` rewritten (+ new `_doc_paths_for_seed`
helper) to name `LANE_SKILL['build']` (**Foreman**), list the ACTUAL persisted
`planning/.../IMPLEMENTATION-PLAN.md` + `MASTER-PLAN.md` (+ supporting) paths, and
a "Read these documents first, then proceed" instruction; new
`_build_seed_for_research` (research→plan analog → **Crucible** + the real research
report path) with `research_set_for_session` + `build_research_to_plan_seed`
(resolves the report from the persisted research efforts tagged with the originating
`session_id`). Wired as `seed_context` into `auto_advance_planning_to_build` (plan→build)
and the `advance_session` endpoint (research→plan: prepends the generated Crucible
doc-seed before the continue summary). `prime_worktree`'s HANDOFF.md already lists the
same paths — they now EXIST in the build checkout (Wave-2 commit-to-main).

(2) **term_kill ordering fix.** The handler captured the plan set BEFORE `kill()`, but
Wave-2's persist runs INSIDE `kill()` — so the pre-capture saw no freshly-produced
docs and the auto-build got a stale/empty plan. Reordered: `kill()` (persists docs +
DONE + reaps) → `capture_plan_set` (now reads the persisted main folder) → auto-advance.

(3) **Skill clarity.** Verified `LANE_SKILL` (build→Foreman, plan/planning→Crucible,
research→researchPrime) — **build never loads Crucible anywhere** (no bug found). Added
a JS `_skillForLane` map mirroring it + a `.skl` panel-header chip ("planning · Crucible"
/ "build · Foreman") so the loaded skill is unambiguous (the user's confusion).

**Orchestrator verification:** `tests/test_handoff_docs_v8.py` (6) — plan→build seed
CONTAINS the real IMPL+MASTER paths + read-first + Foreman (never Crucible) and HANDOFF.md
references files that EXIST in the build checkout; research→plan seed contains the real
report path + Crucible; **term_kill persist-then-advance** (docs not discoverable BEFORE
the kill → auto_build appears AFTER, referencing the now-persisted docs); LANE_SKILL
mapping asserted; the header skill chip wired (DOM positive+negative); Playwright kill
planning→build asserts header "planning · Crucible" then "build · Foreman" + backend
seed/HANDOFF reference real docs, no JS console errors. Screenshot `_devtest/wave4_handoff.png`
(reviewed — build panel shows the green **BUILD · FOREMAN** chip).

**Gate (scoped run):** `test_handoff_docs_v8` + `test_auto_advance_plan_to_build` +
`test_doc_persistence_v8` + `test_advance_research_to_plan` = **31 passed**. Touched
`terminal_session.py`, `anchor_gui.py`, the new test + `_devtest/`. ⚠️ **Pending John's
UI sign-off before merge.** Commit: scoped.

<!-- WAVE 4 done -->
<!-- WAVE 4 — Handoff that carries the documents -->
### Wave 5 — No-loss lifecycle (summary+docs on kill, promote to big tiles, detail view) — GREEN (2026-06-16)

**Built (backend + UI):** `effort_history.efforts_for_session_id` (joins a managed session id
to the docs Wave-2 persisted under it). `anchor_gui._resolve_finished_session` synthesizes a
session dict whose `member_files` are the efforts tagged with the killed session's managed id
— closing the gap where persisted docs grouped under `dir::` (not the bare id) left the
summary empty. Rewired `_trigger_session_summary_on_finish` + the `session_summary` GET
fallback through it, so the kill schedules a summary keyed to the stable id carrying the real
docs. `_fillPastSessionDetail` polls on `generating`. Net: kill → top chip removed (v6
`_KILLED`) + a big done lane tile (registry record stays DONE → v7 board bridge) + a detail
panel showing the produced docs/deliverable + summary + **"Continue in a live session"** (v6
continue_session seeded from the durable summary/docs; original record untouched).

**Orchestrator verification:** `tests/test_no_loss_lifecycle_v8.py` (6) — kill persists docs +
a durable summary (stable id + refs) before reap, nothing lost after reap; promotion (big tile
present + chip removed); detail view lists produced docs + summary + Continue seeds the durable
context; Playwright (kill → chip gone + big tile + detail + Continue opens a new live panel).
**Screenshot reviewed** — `_devtest/wave5_noloss.png`: promoted BUILD tile w/ summary, detail
"Files produced" + "Continue in a live session", and a new live build from Continue.

**Honest notes (flagged for John):** a hard-killed PTY session has no recorded skill/prompts,
so the detail honestly shows "not recorded" while Files-produced lists the real docs (v6
contract). Minor pre-existing UX wart: a killed session can show both its registry tile and a
`dir::` discovered-docs tile in the same column (no dedup change made — would risk forking the
v7 board bridge); candidate cleanup.

**Gate:** **933 passed, 1 skipped** (+6). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 5 done -->
### Wave 6 — Grass: self-contained, cumulative, exportable — GREEN (2026-06-16)

**Built (backend + UI):** (1) **dedup/focus** — `develop_grass_idea` persists a `dev_sessions`
`{lane: session_id}` map on the idea record; re-click resolves the mapped LIVE session and
FOCUSES it (only starts new when none live; dead → fresh). (2) **contained, both layers** —
JS `developGrass` no longer writes `MANAGED`/calls `renderSessionBar`/`refreshBoard` (mounts
only in the workbench `[data-grass-term]` pane); backend stamps the develop session's registry
label `[grass-dev] ` and the v7 board bridge (`_gather_project_sessions`) skips it → no
top-strip chip, no board tile. (3) **cumulative** — `grass_workbench_data` surfaces
`dev_sessions`+`exported_to`; develop seed carries idea+refinements (resume). (4) **no build**
(research/plan only; build raises). (5) **Export (Option B)** — `export_grass_to_project` +
token-gated `POST /api/rnd/grass_export` + a workbench "⇪ Export to project" button: persists
each develop session's docs (Wave-2 keystone), records REAL linked lane efforts carrying the
docs, marks the idea **promoted** (+ `exported_to` link) and LEAVES it in grass; content-
addressed → idempotent; honest no-work.

**Orchestrator verification:** `tests/test_grass_contained_v8.py` (14) — dedupe→one session;
board+JS containment; cumulative+resume; no-build; export carries docs + idea stays promoted+
linked; endpoint auth; Playwright (develop twice → one contained session, no chip/board tile →
export → promoted research tile + idea promoted). **Behavior change** (intended): updated
`test_tile_lifecycle_v6` — dropped `developGrass` from the mints-a-tile loop + added
`test_grass_develop_is_contained_no_top_strip_chip`. **Screenshot reviewed** —
`_devtest/wave6_grass.png`: contained workbench terminal (empty top strip), promoted idea
chip, "Export to project", and the exported Research lane tile.

**Honest notes (for John):** the "promoted N" filter-tab counter lags the "1 promoted" idea
summary (cosmetic). A KILLED develop session's docs would surface as board efforts (Wave-2
persistence behavior; live develop sessions stay contained — the locked requirement holds).

**Gate:** **948 passed, 1 skipped** (+15). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 6 done -->
### Wave 7 — Full chain navigation — GREEN (2026-06-16)

**Built (UI):** enhanced the v6 breadcrumb (no fork) — `openPanel` already calls
`_loadChainBreadcrumb` UNCONDITIONALLY (live + done/historical, via `_synthSessionRecord`),
so a finished tile gets the same chain row. Each node now shows a **status light**
(`_statusColor(m.status)`) next to lane+label. Clicking a node → `openPanel(sibling)`: LIVE →
focus/attach; DONE → the W5 detail (summary + produced docs + Continue). Honest partial
chains via the `members.length < 2` guard (singleton renders no breadcrumb; nodes built only
from the server's `members` — no client synthesis). No backend change needed (durable W2/W5
records make the chain point at real artifacts).

**Orchestrator verification:** `tests/test_chain_nav_v8.py` (7) — `chain_members` ordered
research→plan→build; chain GET carries lane+label+status, SAFE (no worktree/branch),
token-gated; partial chains return only existing nodes; DOM (breadcrumb wired + unconditional
load + no-fabrication guard); Playwright (build panel → 3 nodes w/ lights → click research
[back-nav] → click build [forward-nav], no console errors). **Screenshot reviewed** —
`_devtest/wave7_chain.png`: `● R research → ● P planning → ● B build` with green lights, build
current.

**Gate:** **955 passed, 1 skipped** (+7). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 7 done -->
### Wave 8 — CLI mirror + healthcheck v8 + distro scan + docs — GREEN (2026-06-16) — PROJECT DONE

**Built:** `anchor.py` `rnd remote <pid>` (link/opt-in status via `project_remote.remote_status`)
+ `rnd docs <pid> --session` (persisted-doc list via `efforts_for_session_id`). `anchor_healthcheck.check_rnd_v8_surface`
(fully stubbed: stub PTY + stream-json stub runner + temp worktree base + temp git project +
`ANCHOR_GH_CMD`→`tests/stub_gh.py` + LOCAL BARE remote — NO network): walks bootstrap +
keystone doc-persistence + handoff seed + no-loss + grass contained/export + remote link/opt-in/
push; reaps PTYs + temp dirs, restores env, never `:8777`/real network. `dist_manifest.txt`
ships the two new stdlib-only modules; `distro` scan clean. `CLAUDE.md` gains the full v8
"Durable Artifacts" section.

**Orchestrator verification:** distro re-run → **clean (151 files; sole pywinpty exception; no
Playwright in product)**; `rnd remote`/`rnd docs` in the CLI; CLAUDE.md v8 section present. 27
new tests (cli 16 + healthcheck 6 + distro 7... net +27 incl. fixtures).

**FINAL GATE:** `ANCHOR_PTY_BACKEND=stub python -m pytest -q` → **982 passed, 1 skipped** (+94
over the 888 v7 baseline). Commit: scoped.

---

## PROJECT DONE (2026-06-16) — pending John's UI sign-off + deploy

All 8 waves GREEN. Branch `foreman/rnd-surface-v8` (off master `80ead40`). Full suite **982
passed, 1 skipped**. **NOT merged, service NOT restarted** — UI waves (3–7) await John's sign-off
(screenshots under `_devtest/`), then: merge → `nssm restart anchor` (elevated) → rescan (which
now also bootstraps git + CLAUDE.md per project).

**Wave tally:** W1 bootstrap (897) · W2 KEYSTONE doc persistence (904) · W3 GitHub link+push
(921) · W4 handoff carries docs (927) · W5 no-loss kill (933) · W6 grass contained+export (948)
· W7 chain nav (955) · W8 CLI/healthcheck/distro/docs (982).

**Open items flagged for John:** (1) the "promoted N" grass filter-tab counter lags the idea
summary (cosmetic). (2) A killed session can show both its registry tile and a `dir::`
discovered-docs tile in the same lane column (dedup candidate; live sessions stay contained).
(3) A killed grass-develop session's docs surface as board efforts (Wave-2 persistence;
contained only while live). None block merge.
