# 2026-07-28 — Projects tab opens with all folders expanded

- **id**: `2026-07-28-06-projects-tab-opens-with-all-project-fold` (friction store)
- **surface**: Main Anchor dashboard — **Projects** tile (`#tile-projects`) · R&D folder groups
- **situation**: Opening Projects shows **every** project folder expanded (all rows visible). John does not want that.
- **severity**: friction (UX noise; not a crash)
- **status**: Journaled for sleep — small default-flip; do not ad-hoc unless pulled into sleep polish
- **provenance**: genuine-user-report + code inspection

---

## What John said (verbatim intent)

> Also a small thing, but I do not want to have all of the project folders open when we open the projects tab on the main anchor page. That should not be the case.

---

## What happens today

1. Projects tile body renders R&D groups via `_render_group_folders` / `render_projects_view_html`.
2. Each folder is emitted **expanded**: caret `▾`, **no** `rnd-collapsed` class, body with all project rows.
3. Client `rndFolderInit` restores collapse only for group names listed in  
   `localStorage['anchor_rnd_folder_collapsed']` (array of **collapsed** names).
4. So default (fresh browser / never toggled / new folder) = **everything open**.

Persistence model is **opt-in collapse**. John wants **opt-in expand** (default closed).

---

## Desired product behavior

| Moment | Behavior |
|--------|----------|
| Open Projects tab (first time / no prefs) | All folders **collapsed** — headers + counts only |
| User expands a folder | That folder opens; others stay as they were |
| Optional persistence | Remember per-folder expand/collapse; still **default collapsed** when unknown |
| No flash | Prefer server HTML default collapsed so no expand-then-JS-collapse flash |

---

## Sleep fix sketch (not implemented here)

1. **Server:** emit `class="rnd-folder rnd-collapsed"` + caret `▸` by default in `_render_group_folders`.
2. **Client model flip (cleanest):** store **expanded** set (or invert semantics of existing key with a version bump) so “unknown → collapsed”.
3. **Init:** only *remove* `rnd-collapsed` for groups the user previously expanded.
4. **Toggle:** update caret + storage accordingly.
5. **Smoke:** empty LS → all closed; expand A → reload → only A open; new folder → closed.

Seams: `anchor_gui.py` folder HTML + `rndToggleFolder` / `rndFolderInit` / `RND_FOLDER_LS`.

---

## Success criteria

1. Fresh load: **no** project folder bodies visible until user expands.
2. Expand is per-folder; no “open all on tab open.”
3. Persistence (if kept) does not reintroduce default-open-all.
4. No jarring flash of full tree on paint.

---

## Cross-links

| Item | Link |
|------|------|
| Sleep intake 2026-07-28 | Add as small polish item / Defect 6 |
| Related | General session attach Defect 5 is separate; this is dashboard chrome only |
