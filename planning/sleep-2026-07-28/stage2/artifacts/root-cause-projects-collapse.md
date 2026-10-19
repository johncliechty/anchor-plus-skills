# Root cause — projects not collapsed by default

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W19 — Phase 3: Projects collapsed by default + remembered preference
Surface: `projects_collapse`
Control id (CAPABILITY-INVENTORY): `projects_collapse`

## Verdict at Phase-1 inventory

| field | value |
|-------|-------|
| control_id | `projects_collapse` |
| inventory verdict | **ABSENT** |
| handler_bound | false |
| source | `artifacts/inventory-sources/projects_collapse.probe` |
| transcript | `artifacts/transcripts/projects_collapse.json` |

There was **no** projects-collapse handler bound in the stage2 tree at Phase-1
inventory. The surface did not own a real JS/CSS path for default collapse or
for per-user preference persistence.

## Actual defect mechanism

The failure was **not** a missing cosmetic class on a working tree. It was the
absence of the owner path itself:

1. **No server-rendered collapsed default.** Project folder nodes were emitted
   (or left to the browser) without a definitive first-paint collapsed stamp
   (`class="collapsed"` / `data-collapsed="true"`). Browser defaults and any
   open-by-default list styling therefore showed folders expanded on first
   load.

2. **No real JS path.** There was no `static/js/projects_tree.js` (or equivalent)
   that:
   - applied collapsed-by-default as the authoritative client default,
   - toggled expand/collapse on user action,
   - wrote and re-read a per-profile preference under a version-stamped key.

3. **No preference store.** Expand/collapse choices were not stored per user
   profile. A reload always reset to whatever the (broken) first-paint default
   was. Dual-profile isolation was impossible because no profile key existed.

4. **Cosmetic-only "fixes" would not close the criterion.** Adding a CSS rule
   such as `.project-folder { display: … }` without fixing the server first
   paint **and** the JS owner path leaves:
   - first paint still wrong if the DOM never receives `collapsed`,
   - preference non-persistent,
   - unreadable-store honesty undefined (silent expanded/collapsed as if it
     were the user's choice).

## Fix applied at the real path (W19)

| layer | path | role |
|-------|------|------|
| Server first paint | `anchor/ui/projects_tree.py` | Every folder rendered with `class="project-folder collapsed"` and `data-collapsed="true"` unless a **readable** per-profile preference expands that folder id. |
| Real JS path | `static/js/projects_tree.js` | Collapse default, toggle, collect expanded ids, read/write preference under `projects.collapse.v1`. |
| Preference store | injectable dict or path (`InMemoryPreferenceStore` / `PathPreferenceStore`) | Per-profile expand set; dual-profile helpers `profile_A` / `profile_B`. |
| Unreadable store | preference panel via `render_state(NamedState.unknown)` | Fallback **all collapsed**; preference shows **unknown** — never a silent user choice. |
| Empty project list | `NamedState.empty` | Distinct from list-unreadable **unknown**. |
| Preference key stamp | `projects.collapse.v1` | Stale keys ignored; default collapsed re-applied (plan: ship key with the fix). |

## What "matches the code that was changed" means

The written root cause names the **ABSENT handler + missing first-paint stamp +
missing preference path**. The code that was changed is exactly those three
seams (`projects_tree.py` render, `static/js/projects_tree.js`, injectable
preference store). A later CSS-only tweak that does not touch those seams is
**not** a valid W19 fix and must not be claimed as one.

## Dual-profile contract (criterion 7)

* Profile A expands two folders → save → reload → those two expanded, others collapsed.
* Profile B expands none → reload → all collapsed.
* No cross-profile bleed (store keys are per `profile_id`).
* Preference store unreadable → collapsed + named unknown preference state.

## Related artifacts

* Failure-state table: `artifacts/failure-states/projects-collapse.md`
* Tests: `tests/test_projects_collapse_2026_07_29.py`
* Inventory row: CAPABILITY-INVENTORY control `projects_collapse`
