# Anchor R&D Surface v9 — "Tidy" — Execution Log

> Per-wave EXECUTE / REVIEW / FIX / GATE history for the Foreman build of v9. Frozen
> plan: `MASTER-PLAN.md` + `IMPLEMENTATION-PLAN.md` (this folder). Branch:
> `foreman/rnd-surface-v9` (off `foreman/rnd-surface-v8` HEAD `d09ec8d`, which has v8 +
> the dashboard perf fix).

## Baseline

- **2026-06-16** — Branch `foreman/rnd-surface-v9` created off the v8 branch (v8 deployed
  + the perf fix). Baseline = **982 passed, 1 skipped**. GREEN floor; each wave holds/grows.

## Wave records

### Wave 1 — True session delete (keep documents) — GREEN (2026-06-16)

**Built (backend + UI):** `effort_history.delete_session_efforts` (clears the session's lane
effort pointer-records + index entries via the v8 `efforts_for_session_id` join, reusing
`_delete_effort_record`, + the cached summary dir `summaries/<sid>/`; NEVER the produced
documents — Option A). `terminal_session.delete_session` (kills a live session first, then
`session_registry.remove_session` [the existing-but-unused primitive], then the effort/summary
cleanup; best-effort, idempotent, never raises) + `cleanup_ghost_sessions` (sweeps empty
terminal/idle records with no efforts; spares RUNNING + with-work). Endpoints
`POST /api/rnd/term_delete` + `cleanup_ghost_sessions` (token + explicit `confirm`). UI: a red
**✕ delete** control in the panel header top-right — distinct class/glyph/handler/endpoint/CSS
from the v8 🗑 kill (kill ends a running session; ✕ removes the record entirely), confirm-gated;
+ a `_DELETED` suppression set (belt-and-suspenders vs an in-flight repopulate). Survives
refresh because the registry record is genuinely REMOVED (term_sessions/_gather_project_sessions
read the registry) — the v6 page-load-only `_KILLED` bug is moot.

**Orchestrator verification:** `tests/test_session_delete_v9.py` (12) — clears record+efforts/
index+summary while produced docs remain; drops from list_sessions/board + survives reconcile;
idempotent; unknown-id no-raise; live-delete reaps worktree first; ghost cleanup spares
RUNNING/with-work; endpoint auth + confirm-required; DOM (red ✕ present + distinct from kill;
positive+negative); Playwright (delete → tile gone → **reload → still gone** → docs unaffected).
**Screenshot reviewed** — `_devtest/wave1_delete.png`: the solid-red ✕ delete button in the
panel header, distinct from the 🗑 kill.

**Gate:** **994 passed, 1 skipped** (+12). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 1 done -->
### Wave 2 — Grass idea delete — GREEN (2026-06-16)

**Built (backend + UI):** `effort_history.delete_grass_idea(folder, pid, idea_id)` — removes the
idea pointer-record + grass index.json entry (W1 `_delete_effort_record` pattern) + the
refinements dir (`shutil.rmtree`) + cleans the `dev_sessions` map (best-effort
`terminal_session.delete_session` per contained develop session, fallback `remove_session`);
idempotent, never raises, project-scoped. `POST /api/rnd/grass_delete` (token + explicit
`confirm`). UI: a red **✕** (`.gli-del`) on each idea row (`_render_grass_idea_li`) →
`deleteGrassIdea` (confirm-gated, `stopPropagation` so it doesn't select the row) → removes the
row + clears the workbench pane if it was selected; `grass_workbench_data` no longer lists it.

**Orchestrator verification:** `tests/test_grass_delete_v9.py` (12) — clears pointer+index+
refinements+dev_sessions; gone from `grass_workbench_data`; **siblings + other projects
untouched**; idempotent + unknown-id no-raise; endpoint auth + confirm-required; DOM (one
`.gli-del` wired to deleteGrassIdea, ✕ glyph not 🗑; positive+negative); Playwright (delete victim
→ gone, sibling stays). **Screenshot reviewed** — `_devtest/wave2_grass_delete.png`: both idea
rows show a red ✕.

**Gate:** **1004 passed, 1 skipped** (+10). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 2 done -->
### Wave 3 — Project folders: group field + collapsible UI + drag-to-group — GREEN (2026-06-16)

**Built (backend + UI):** `rnd_registry` gains a `group` field (default `""`, `_normalize` +
`update_project` allow-list; back-compat: no-field → Ungrouped) + `set_group(pid, group)`
(persists; never touches disk — `folder_path` unchanged) + `group_by_group()` (named groups
alpha, Ungrouped always last). `POST /api/rnd/set_group` (token-gated). UI: the home R&D view
renders `group_by_group` → collapsible folders (▸/▾ + name + count + uniform path; collapse
state in localStorage), a **"+ New folder"** toolbar (empty groups persist client-side until a
project lands), and **draggable** project rows (⋮⋮ grip) that drop on a folder header → set_group
(NO disk move). Ungrouped catch-all always present. `rndFolderInit` re-wires after the 15s
in-place refresh.

**Orchestrator verification:** `tests/test_project_folders_v9.py` (18) — set_group/group_by_group/
back-compat/Ungrouped-last; **folder_path unchanged on set_group** (no disk move); endpoint auth;
DOM (collapsible scaffold + New-folder + draggable rows; positive+negative vs the v8 flat list);
Playwright (create Research → drop a project → under Research, **persists across reload**,
**folder_path UNCHANGED**, collapse toggles). Updated the v8 flat-list assertions in
`test_dashboard_rows`/`test_new_project` to the new folder structure (legitimate change).
**Screenshot reviewed** — `_devtest/wave3_folders.png`: "+ New folder", an empty "Research (0)",
and "Ungrouped (2)" with two draggable rows — matches the mockup.

**Gate:** **1021 passed, 1 skipped** + 1 PRE-EXISTING FLAKY (`test_lanes_concurrency::test_ac5_
reattach…` — unrelated to Wave 3; passes 3/3 on re-run). ⚠️ **Pending John's UI sign-off.**
Commit: scoped.

<!-- WAVE 3 done -->
### Wave 4 — Project folders: guarded on-disk move — GREEN (2026-06-16)

**Built (backend + UI; the high-risk wave):** new `project_move.move_to_group(pid, group,
projects_root=None)` — guarded atomic move: REFUSE (no fs change) if the project is the running
Anchor repo (`is_anchor_repo` compares folder_path normalized vs `paths.CODE_DIR`) or has a LIVE
session (`session_registry.list_sessions(status=RUNNING)`); else dest = `<root or src.parent>/
<slug(group)>/<dir>`; `shutil.move` → `update_project(folder_path=)` + `set_group` → `git worktree
prune` → regenerate `discovery.json` (via `discover_and_adopt`); **ROLLBACK** (move back + restore
folder_path/group) on ANY step 2–5 failure; never raises. `POST /api/rnd/move_project` (token +
explicit `confirm`; refusals→400, unknown→404). UI: the **Option-C dialog** on a drop into a named
folder — "Move on disk + group" (→ move_project) vs "Just group" (→ W3 set_group) vs Cancel,
showing source→dest + the guard copy; refusal toast for Anchor/live-session; Ungrouped drop stays a
direct set_group.

**Orchestrator verification (ALL on TEMP dirs + temp registry + temp worktree base — never the
real Anchor/registry/:8777):** `tests/test_project_move_v9.py` (18) — move re-points registry+
worktrees+discovery + post-move `create_worktree` succeeds; **Anchor-repo refusal** (CODE_DIR
monkeypatched, real repo never moved); **live-session refusal**; **rollback** on injected forward
failure (dir back + folder_path restored); "Just group" no-fs-change; endpoint auth+confirm+refusal
reasons; DOM + Playwright (drop → Option-C dialog → "Just group" groups without moving). **Screenshot
reviewed** — `_devtest/wave4_move.png`: the dialog (Move-on-disk / Just-group / Cancel + source→dest
+ safety copy) matches the mockup.

**Gate:** **1040 passed, 1 skipped** (+19; the prior flaky concurrency test passed this run).
⚠️ **Pending John's UI sign-off before merge.** Commit: scoped.

<!-- WAVE 4 done -->
### Wave 5 — CLI mirror + healthcheck v9 + distro scan + docs — GREEN (2026-06-16) — PROJECT DONE

**Built:** `anchor.py` `rnd folders` (groups + members via `group_by_group`) + `rnd ghost-sessions
<pid>` (empty/ghost sessions, read-only, SAFE). `anchor_healthcheck.check_rnd_v9_surface` (fully
stubbed: stub PTY + stream-json stub runner + temp git projects + TEMP projects_root + TEMP
registry): walks session delete (record+efforts+summary cleared, survives reload, docs kept) +
ghost cleanup + grass idea delete + set_group/group_by_group + the guarded move (re-point +
post-move worktree works, Anchor-repo refusal via a TEMP CODE_DIR then restored, live-session
refusal, rollback). NEVER moves the real repo/registry/binds :8777. `dist_manifest.txt` ships
`project_move.py`; distro scan clean. `CLAUDE.md` gains the v9 "Tidy" section + the dashboard
perf-fix note.

**Orchestrator verification:** distro re-run → **clean (159 files; sole pywinpty exception; no
Playwright in product)**; `rnd folders`/`rnd ghost-sessions` in the CLI; CLAUDE.md v9 + perf-fix
present. 28 new tests (cli 18 + healthcheck 6 + distro 7... +28 net).

**FINAL GATE:** `ANCHOR_PTY_BACKEND=stub python -m pytest -q` → **1068 passed, 1 skipped** (+86
over the 982 v8+perf-fix baseline). Commit: scoped.

---

## PROJECT DONE (2026-06-16) — pending John's UI sign-off + deploy

All 5 waves GREEN. Branch `foreman/rnd-surface-v9` (off `d09ec8d` = v8 + the dashboard perf fix).
Full suite **1068 passed, 1 skipped**. **NOT merged, service NOT restarted** — UI waves (1–4)
await John's sign-off (screenshots `_devtest/wave{1..4}_*.png`), then: restart to deploy → the
red banner clears on the next clean health-check run.

**Wave tally:** W1 session delete (994) · W2 grass delete (1004) · W3 folders grouping (1021) ·
W4 guarded on-disk move (1040) · W5 CLI/healthcheck/distro/docs (1068).

**Open items flagged for John:** the on-disk move is opt-in per drag (Option C); it hard-refuses
the Anchor repo + live-session projects + rolls back — verified on temp dirs only. A pre-existing
flaky concurrency test (`test_lanes_concurrency::test_ac5_reattach…`) intermittently fails and
passes on re-run (unrelated to v9). Stacked-but-unmerged branches v8→v9 should be merged down to
master when convenient (master is behind what's deployed).
