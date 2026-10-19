# Anchor R&D Surface v9 — "Tidy" — Master Plan (frozen design)

> Crucible Stage 1 output, locked 2026-06-16. Follows v8 "Durable Artifacts" (deployed;
> branched off `foreman/rnd-surface-v8` HEAD `d09ec8d`, which includes the dashboard
> perf fix). From J.C. Liechty's live-use feedback: he needs to **remove clutter**
> (delete sessions + ideas) and **organize** (project folders that mirror disk).
> Approved mockup: `_mockups/rnd-v9/project_folders.html`. Build cwd = repo root
> `C:\dev\Anchor`. Each wave ends GREEN on `python -m pytest -v`; extends v6/v7/v8 seams.

## North Star (locked — John's Stage-0 answers)

Make the R&D surface **tidy and organizable** — the user can permanently remove what
they don't want and arrange what they keep:

1. **True session delete.** A red **✕** (top-right of a session tile) → "are you sure?"
   → the session is **completely gone and stays gone across a refresh**: the registry
   record (`remove_session`), the lane effort pointer-records + index entries, and the
   cached summary are removed. **Produced documents are KEPT** (Option A — a delete
   removes the Anchor session, never the real committed work). Ghost/empty sessions
   (empty DONE records with no efforts) delete cleanly; a sweep can clear them in bulk.
2. **Grass idea delete.** A red **✕** on a grass idea → confirm → the idea is fully
   removed: its pointer-record, its index entry, its versioned refinements dir
   (`grass-<id>/dev-N`), and its develop-session mapping (all Anchor scratch). So the
   grass list never becomes burdensome.
3. **Project folders that mirror disk.** Collapsible **folders** on the main dashboard
   group projects (▸/▾, "+ New folder"); **dragging** a project into a folder **groups
   it instantly** in the dashboard, and a dialog then offers **"Move on disk + group"**
   vs **"Just group"** (Option C). The on-disk move is a **guarded, atomic** operation:
   it **hard-refuses the live Anchor repo** and any project with a **live session**
   (stop them first), creates the real folder under the projects root, moves the
   directory, re-points the registry `folder_path` + git worktrees + `discovery.json`,
   and **rolls back** on any failure.

## Why v9 (what John hit in live use)

1. **Killed sessions won't die.** `kill` only marks a session DONE; `remove_session()`
   exists but is never called; the client "killed" suppression is per-page-load only —
   so killed tiles **reappear as greyed tiles on refresh**, and empty "ghost" sessions
   accumulate.
2. **Ideas pile up.** You can add a grass idea but there's **no way to remove one**.
3. **No organization.** Projects render as one flat list (26 of them, much of it junk);
   there's no way to group them, and no relationship between the dashboard and the dev
   filesystem.
4. (Related: the clutter is what made the dashboard slow — the perf fix landed
   alongside this; delete + folders address the human side of the same problem.)

## Locked decisions (Stage 0 user gates)

1. **Session delete = remove-from-Anchor, KEEP documents (Option A).** Delete clears the
   registry record + lane effort pointer-records/index + cached summary so the tile is
   gone permanently (survives refresh); produced/committed documents are never deleted.
2. **Grass delete = full** (the idea's pointer + index + refinements + dev-session map —
   all Anchor scratch, nothing committed).
3. **Folders = drag-groups-instantly + ask-to-move-on-disk (Option C).** A drag always
   groups in the dashboard (safe, reversible); a dialog offers "Move on disk + group"
   (the guarded atomic move) vs "Just group". The on-disk move **always** refuses the
   Anchor repo and live-session projects, is atomic, and rolls back on failure.
4. **Verification standard (non-negotiable, the v4 lesson).** Every UI wave's "GREEN" =
   rendered-DOM (positive+negative) + a real Playwright/Chromium interaction test + an
   orchestrator screenshot vs the rnd-v9 mockup + the user's sign-off before merge. A
   string-grep gate is an automatic HALT.
5. **Scope = one build** on `C:\dev\Anchor`, every wave GREEN on `python -m pytest -v`.
   Branch `foreman/rnd-surface-v9`. No merge / no service restart without John's sign-off.

## Out of scope (inclusion test)

- Calendar, app-builder, floating windows (carry the fences).
- Deleting produced/committed documents on session delete (Option A keeps them).
- Moving the Anchor repo itself, or any project with a live session, on disk (hard-refused).
- Nested folders beyond one level (a flat set of named folders; revisit if needed).
- Auto-moving a directory on every drag (Option C requires explicit confirm).

## Hard constraints (from CLAUDE.md — non-negotiable)

- **Python stdlib only** (+ lazy `pywinpty`). git/gh as external CLIs via the existing
  stubbed seams; the folder-move uses `shutil.move` + `git` (worktree prune) through an
  injectable seam stubbed in tests — **NEVER move real data / the real Anchor repo / hit
  real network in tests**. **Playwright DEV-ONLY** (`pytest.importorskip`), never in
  product code; `distro.py` scan stays green.
- **Never bind/touch `:8777` or real data in tests/healthcheck**; model/PTY via the
  stubs; temp dirs/registries only. The folder-move tests operate on TEMP project dirs +
  a TEMP registry, never the live one.
- **All mutating endpoints** (delete-session, delete-idea, set-group, move-project)
  behind the `do_POST` token gate; GET read-only (`?token=`). Delete + move endpoints
  require an explicit confirm flag.
- **f-string brace discipline** (`_PROJECT_WINDOW_JS` RAW single-brace; doubled braces
  in f-string HTML/CSS).
- **Reuse, don't fork:** `session_registry.remove_session`, `effort_history`,
  `rnd_registry`, `worktrees`, `terminal_session`, `sessions.py`, the v7/v8 board/grass
  seams. **Mirror** new read seams into `anchor.py`; **extend** `anchor_healthcheck.py`
  (`check_rnd_v9_surface`, fully stubbed); **update** `CLAUDE.md`.
- **Scoped commits only** — never sweep runtime-data churn.

## Risks & mitigations

- **R1 — session delete leaves orphan stores → the tile reappears.** Delete must clear
  ALL of: registry record, lane effort pointer-records + index entries, cached summary
  — for exactly that session_id — so a refresh can't resurrect it. Test: after delete,
  `term_sessions` + the board + `list_sessions` no longer return it across a fresh reload.
- **R2 — delete destroys real work.** Option A: never delete produced/committed docs;
  only Anchor's session records/summary. Test: a session with produced docs → after
  delete the docs still exist on disk + in git; only the Anchor session is gone.
- **R3 — the on-disk MOVE corrupts a project / the running server.** Hard-refuse the
  Anchor repo (match the running CODE_DIR) and any project with a live session; require
  an explicit confirm; perform atomically (move dir → update folder_path → `git worktree
  prune` → regenerate `discovery.json`) with **rollback** (move back) on any step
  failure; operate only within a configured projects root. Test (TEMP dirs): a move
  re-points registry+worktrees+discovery and a subsequent worktree/session works;
  Anchor-repo + live-session moves are refused; an injected mid-move failure rolls back.
- **R4 — grass delete leaves refinement scratch / breaks the workbench.** Delete the
  pointer + index + refinements dir + dev-session map; the workbench re-renders without
  it. Test: deleted idea gone from `grass_workbench_data` + the disk stores cleared.
- **R5 — folders confuse the board / break the flat-row render.** The `group` field is
  additive (default ungrouped); ungrouped projects still render; the board/project
  windows are unaffected. Test: grouping renders collapsible folders, ungrouped still
  shows, no regression to the flat rows / project windows.
- **R6 — another vacuous UI gate.** Decision 4 (DOM + Playwright + screenshot + sign-off)
  mandatory per UI wave.

## Definition of done (project)

All waves GREEN on `python -m pytest -v` AND: a session's red ✕ deletes it permanently
(record + efforts + summary cleared; survives refresh) while keeping produced documents;
ghost/empty sessions delete (and a sweep clears them); a grass idea's red ✕ fully removes
it (pointer + index + refinements + dev-session map); the dashboard shows collapsible
folders with "+ New folder" and drag-to-group, and a drag offers "Move on disk + group"
(guarded atomic move, Anchor-repo + live-session refused, rollback) vs "Just group"; the
CLI/healthcheck/distro/docs mirror the new seams; and every UI wave is verified by
Playwright + a screenshot + John's sign-off before merge.
