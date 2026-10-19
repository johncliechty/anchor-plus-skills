# Anchor R&D Surface v9 — "Tidy" — Implementation Plan (Foreman-ready)

> Crucible Stage 2 output, locked 2026-06-16. Frozen design: `MASTER-PLAN.md` (this
> folder) + the approved mockup `_mockups/rnd-v9/project_folders.html`. Build cwd = repo
> root `C:\dev\Anchor`, branch `foreman/rnd-surface-v9` (off `foreman/rnd-surface-v8`
> HEAD `d09ec8d`). Each wave ends GREEN on the ground-truth gate and adds/extends tests.

test-command: python -m pytest -v

## Conventions (read before any wave)

- **Active Anchor project id:** read from `rnd_registry.json` at build time; never hard-code.
- **No live `claude`/`gemini`/real-PTY in the gate; never real network / `git push` / `gh`.**
  Model via `tests/fake_claude.py`/`tests/stub_streamjson.py`; PTY via `ANCHOR_PTY_BACKEND=stub`;
  git/gh via the existing stubbed seams. The folder-MOVE tests run on TEMP project dirs + a
  TEMP registry only — **never the live registry, never the real Anchor repo, never `:8777`/
  real data.**
- **pywinpty** stays the only native dep (lazy, `pty_manager.py`). **Playwright DEV-ONLY**
  (`pytest.importorskip`), never in product code; `distro.py` scan green (W5 asserts it).
- **f-string discipline** in `anchor_gui.py`: `_PROJECT_WINDOW_JS` RAW single-brace; double
  literal braces in f-string HTML/CSS.
- **Security:** every new mutating endpoint (delete-session, delete-idea, set-group,
  move-project) behind the `do_POST` token gate; GET read-only (`?token=`). Delete + move
  require an explicit `confirm`/intent flag in the body.
- **Reuse, don't fork:** `session_registry.remove_session`, `effort_history`, `rnd_registry`,
  `worktrees`, `terminal_session`, `sessions.py`, the v7/v8 board/grass seams.
- **Scoped commits only** — never the runtime-data churn (`dashboard.html`, `PROJECTS.md`,
  `DASHBOARD.md`, `domains/*`, `INBOX.md`, `.anchor/`, `rnd_jobs/`, `rnd_registry.json`,
  `logs/`). Commit only the code/test files each wave touched.
- **Baseline before Wave 1:** the v8 + perf-fix baseline was **982 passed, 1 skipped**.
  Re-establish at Wave 1 start; each wave holds or grows it.
- **UI VERIFICATION IS MANDATORY (the v4 lesson)** for every wave that changes rendered UI
  (Waves 1, 2, 3, 4): (a) rendered-DOM (positive+negative, `html.parser`); (b) a real
  Playwright+Chromium interaction test; (c) an orchestrator screenshot (PNG under `_devtest/`)
  Read + checked vs the rnd-v9 mockup; (d) user sign-off before merge. A string-grep-only
  test is an automatic HALT.

---

## Wave 1 — True session delete (backend + UI; keep documents)

Make a session permanently deletable. Add `effort_history.delete_session(folder, pid, lane,
session_id)` (or a focused helper) that, for that session_id, removes the **lane effort
pointer-records + their index entries** and the **cached summary dir**
(`.anchor/projects/<id>/<lane>/summaries/<sid>/`) — **but never the produced documents**
(Option A; they stay in the project folder/git). Add `terminal_session.delete_session(...)`
that calls `session_registry.remove_session(session_id)` (the existing-but-unused primitive)
AND the effort/summary cleanup; if the session is still live, kill it first. Endpoint
`POST /api/rnd/term_delete` (token-gated, explicit `confirm`). UI: a red **✕** control in the
**top-right of a session tile/panel** (distinct from the v8 "kill" — kill ends a *running*
session; delete *removes the record entirely*), behind an "are you sure?" confirm; on success
the tile is removed from the board AND it does not return on refresh (the registry record is
gone, so `term_sessions`/`_gather_project_sessions` no longer surface it). Add a
`cleanup_ghost_sessions(pid)` helper + a small "clear empty sessions" action that deletes
empty DONE records with no efforts.

- **Done-when:** the UI-verification set passes — deleting a session removes its registry
  record + effort pointer-records/index + cached summary; the tile is gone and STAYS gone
  across a fresh reload; produced documents remain on disk; deleting an empty ghost session
  works; kill (running) and delete (remove) are distinct controls.
- **G/W/T:** **Given** a DONE session with produced docs, **When** the user clicks its red ✕
  and confirms, **Then** its registry record + effort pointer-records/index + cached summary
  are removed, `term_sessions` + the board no longer return it after a reload, and the
  produced documents still exist; **Given** an empty ghost session, **Then** delete removes it.
- **Tests:** `tests/test_session_delete_v9.py` — delete clears all three stores (record/efforts/
  summary), docs kept (Option A), survives a reconcile/reload, ghost cleanup, endpoint auth +
  confirm-required + DOM (red ✕ present, distinct from kill; positive+negative) + Playwright
  (delete → tile gone + reload → still gone) + screenshot.

## Wave 2 — Grass idea delete (backend + UI)

Add `effort_history.delete_grass_idea(folder, pid, idea_id)`: remove the idea **pointer-record**
+ its **index.json entry** + its **refinements dir** (`grass-<id>/dev-N`) + clean its
**dev_sessions** map (best-effort kill/forget the contained develop sessions). Endpoint
`POST /api/rnd/grass_delete` (token-gated, explicit `confirm`). UI: a red **✕** on each grass
idea row (`_render_grass_idea_li`) → "are you sure?" → the idea is removed from the workbench
(`grass_workbench_data` no longer returns it). Project-scoped; never touches another project.

- **Done-when:** the UI-verification set passes — deleting a grass idea removes its pointer +
  index entry + refinements dir + dev-session map; the workbench re-renders without it; other
  ideas/projects are untouched.
- **G/W/T:** **Given** a grass idea with saved refinements, **When** the user clicks its red ✕
  and confirms, **Then** its pointer-record, index entry, and refinements dir are removed and
  `grass_workbench_data` no longer lists it; **and** sibling ideas remain.
- **Tests:** `tests/test_grass_delete_v9.py` — delete clears pointer+index+refinements+dev_sessions;
  endpoint auth + confirm; sibling ideas untouched; DOM (red ✕ on the idea row; positive+negative)
  + Playwright (delete idea → gone from the list) + screenshot.

## Wave 3 — Project folders: group field + collapsible UI + drag-to-group (backend + UI)

Add organization WITHOUT touching disk. Add a `group` field to the project record
(`rnd_registry._normalize` default `""` + `update_project` allow-list + a `set_group(pid,
group)`); list folders via a `group_by_group()` (default `""` = "Ungrouped"). The main
dashboard renders **collapsible folders** (▸/▾, name + count + on-disk path, collapse state
persisted client-side), a **"+ New folder"** control (names a group), and **drag-and-drop** a
project row into a folder header → `POST /api/rnd/set_group` (token-gated) reassigns the
project's `group` (dashboard-only; NO disk move this wave). Ungrouped projects still render.
The board/project windows are unaffected.

- **Done-when:** the UI-verification set passes — the dashboard shows collapsible folders with
  counts; "+ New folder" creates a named group; dragging a project into a folder reassigns its
  group (persisted) with NO disk move; ungrouped projects still render; collapse/expand works.
- **G/W/T:** **Given** several projects, **When** the user creates a "Research" folder and drags
  a project into it, **Then** the project's `group` is set to "Research" (persisted), it renders
  under the collapsible "Research" folder, and its directory on disk is unchanged.
- **Tests:** `tests/test_project_folders_v9.py` — `set_group`/`group_by_group` (default Ungrouped;
  back-compat for records without the field); set_group endpoint auth; DOM (collapsible folder
  structure + "+ New folder" + drag affordance; positive+negative vs the v8 flat rows) +
  Playwright (create folder → drag project → grouped, persisted) + screenshot.

## Wave 4 — Project folders: guarded on-disk move (backend + UI; the high-risk wave)

Make the dev tree mirror the folders, safely. Add `project_move.move_to_group(pid, group,
projects_root=None)` that performs the **guarded atomic move**:
(1) **REFUSE** if the project is the running **Anchor repo** (its `folder_path` == the live
CODE_DIR) or has any **live session** (registry status running) — return a clear refusal, no
move; (2) compute the destination `<projects_root>/<group-slug>/<dir-name>` (projects_root
defaults to the project's current parent dir; a folder is created if absent); (3) `shutil.move`
the directory; (4) update the registry `folder_path`; (5) `git worktree prune` + reconcile any
managed worktrees; (6) regenerate `discovery.json` (`root`) via the existing rescan; (7) on ANY
step failure, **roll back** (move the dir back, restore `folder_path`). All git/fs via the
injectable seam; tests use TEMP dirs only. UI: the **Option-C dialog** on a drag-into-folder —
"Move on disk + group" (calls `move_to_group` via `POST /api/rnd/move_project`, token-gated +
confirm) vs "Just group" (Wave 3 path) — surfacing the source→dest paths + the guard notes
(matching the mockup), and a clear refusal toast for Anchor/live-session.

- **Done-when:** the UI-verification set passes (TEMP dirs) — "Move on disk + group" moves a
  project's directory into the group folder, re-points registry+worktrees+discovery, and a new
  session/worktree on the moved project works; moving the Anchor repo or a live-session project
  is REFUSED with a clear message; an injected mid-move failure rolls back (dir + folder_path
  restored); "Just group" leaves the dir in place.
- **G/W/T:** **Given** a temp project with no live sessions, **When** the user picks "Move on
  disk + group" into "research", **Then** its directory moves to `<root>/research/<dir>`, the
  registry `folder_path` + worktrees + `discovery.json` are re-pointed, and a subsequent
  `create_worktree` succeeds; **Given** the Anchor repo or a live-session project, **Then** the
  move is refused (no fs change); **Given** an injected failure after the dir move, **Then** the
  move rolls back fully.
- **Tests:** `tests/test_project_move_v9.py` — move re-points registry+worktrees+discovery (temp
  dirs) + post-move worktree works; Anchor-repo refusal; live-session refusal; rollback on
  injected failure; "just group" no-fs-change; move endpoint auth + confirm + DOM/Playwright (the
  Option-C dialog: Move-on-disk vs Just-group, refusal toast) + screenshot.

## Wave 5 — CLI mirror + healthcheck v9 + distro scan + docs (PROJECT DONE)

Mirror the new seams into `anchor.py` (read-only/data where sensible: `rnd folders <…>` [list
groups + members], `rnd ghost-sessions <pid>` [empty sessions]; delete/move are interactive/
mutating — no one-shot CLI form, consistent with prior versions, OR a guarded `rnd delete-session`
/ `rnd delete-idea` if low-risk). Extend `anchor_healthcheck.py` with `check_rnd_v9_surface`
(fully stubbed: stub PTY + stub runner + temp git project + TEMP projects_root + TEMP registry):
walk (a) session delete clears record+efforts+summary and survives reload, docs kept; (b) ghost
cleanup; (c) grass idea delete clears pointer+index+refinements; (d) set_group/group_by_group;
(e) the guarded on-disk move on a TEMP project (+ Anchor-repo + live-session refusal + rollback)
— **never the real Anchor repo / real registry / `:8777`**. Tear down + restore env. Confirm
`python -m distro` scan clean. Update `CLAUDE.md` (a v9 "Tidy" section + the new endpoints/CLI +
the `group` field + the delete/move modules + the on-disk-move safety model).

- **Done-when:** the **full** suite GREEN; the new CLI works; `check_rnd_v9_surface` passes fully
  stubbed + tears down (no `:8777`, no real move/registry, no orphan PTY/worktree); `python -m
  distro` scan clean; `CLAUDE.md` documents v9.
- **G/W/T:** **Given** the stubbed env, **When** `check_rnd_v9_surface` runs, **Then** it walks
  delete (session+grass+ghost) + group + the guarded move (incl. refusals + rollback) on TEMP
  data and tears down with no orphan, never touching the real Anchor repo/registry/`:8777`;
  **and** distro reports only the declared `pywinpty` exception (no Playwright in product code).
- **Tests:** `tests/test_cli_v9.py`, `tests/test_healthcheck_v9.py`, `tests/test_distro_scan_v9.py`
  — and the whole suite GREEN.

## Project DONE

DONE = Wave 5 GREEN on `python -m pytest -v` AND the Master Plan "Definition of done" met —
including the UI waves' (1–4) Playwright + screenshot + **John's sign-off**. Terminal wave =
Wave 5. **No merge to master / no `nssm restart anchor` until John signs off.**
