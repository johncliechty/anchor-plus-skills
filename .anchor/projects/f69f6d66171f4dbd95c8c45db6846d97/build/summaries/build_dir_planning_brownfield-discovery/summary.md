# brownfield-discovery

*Lane: build · validated, cached summary*

**When run:** 2026-06-10

**What was asked:** brownfield-discovery

## Actions & files produced

- Brownfield Discovery — Execution Log
- foreman.config

**Effort:** imported — no run metrics

## What was built & errors overcome

- ## Brownfield Discovery â€” Build Session Summary
- **Objective:** Add brownfield discovery to Anchor â€” scan a project folder for existing trio artifacts and surface them as honest, non-fabricated "imported" efforts. Built by Foreman across 7 waves, all PASS.
- **Scanner (`brownfield_scan.py`, Wave 1):** Bounded walk (depth â‰¤6, â‰¤5000 files) skipping `.git`/`node_modules`/`_archive`/`.anchor`, classifying files by trio provenance â€” foreman checkpoint/config â†’ build; named planning docs â†’ planning; `report.md/pdf` under `research/` â†’ research; `deliverables/**` â†’ deliverables; generic `*.pdf` + root `*PLAN*.md` â†’ docs (NOT adopted). Robust to missing/mistyped/UNC paths (empty result, never raises). 18 tests green.
- **Discovery data model (`effort_history`, Wave 2):** Added `source="discovered"` records with a stable path-hash `discovered_job_id`, idempotent `adopt_discovered` (upsert + prune-on-rescan) and `reconcile_discovered` (prune on deleted artifact). Discovered records carry real metadata only (rel path, mtimeâ†’created_at, title, kind) â€” **no cost/tokens/session_id fabricated**. Rollups exclude discovered from `effort_count`/cost and add parallel `discovered_count`. Locked `test_cost_rollup.py` 3/2/1 asserts stayed green.
- **Render honesty (Wave 3):** Discovered cards get an `imported` marker, a `.dotdisc` dot, `data-discovered="1"`, no version number, cost 0, never live/done, and link to `/artifact/<pid>?path=<rel>` instead of `/report`. Tiles/rollups render `N efforts Â· M imported Â· $X`.
- **Safe artifact route (Wave 4):** New `GET /artifact/<pid>?path=<rel>` using `report_viewer.resolve_project_artifact` with the KaTeX `resolve()`+`relative_to()` containment pattern â€” rejects absolute/`../`/`.git`/`.anchor`/symlink-escape with 400/404 and zero bytes read. `status_line()` made dynamic (has-runs/imported/none-yet); home R&D panel + `discover_and_adopt(pid)` pipeline + `POST /api/rnd/rescan` wired.
- **Anchor.md marker writer (Wave 5):** `anchor_marker.write_anchor_md` renders a **structure-only** `Anchor.md` (sections, per-lane counts, relative paths, titles, last-scanned) under `paths.WRITE_LOCK`, hash-compared for no-churn; full ScanResult goes to the `.anchor/projects/<id>/discovery.json` sidecar. 7 tests green incl. 24-thread concurrency â†’ one consistent file, no content/secret leak.
- **Wiring (Wave 6):** `discover_and_adopt` hooked into register, open (`GET /project/<id>`), and rescan, with Rescan buttons on project window/tile/home panel. Idempotent via stable path-hash job_ids; prunes deletions; unknown-project rescan â†’ clean 404.
- **End-to-end gate (Wave 7):** Full suite **284 passed, 1 skipped** (symlink test skips â€” needs admin; containment covers that path). Baseline 236 unchanged + 48 new, none weakened. Live HTTP smoke (throwaway server, never port 8777, no live claude) confirmed: imported tiles/cards render correctly, incidental PDF is *not* adopted, `/artifact` serves real files while traversal attempts 404 with zero leak, rescan prunes a deleted artifact's card, and `Anchor.md` stays structure-only. Distro build clean (ships `brownfield_scan.py` + `anchor_marker.py`, no personal-data hits).
- **Config:** project `anchor-brownfield-discovery`, test command `python -m pytest -q`; product code is Python-stdlib-only, pytest dev-only.
- **Session: brownfield-discovery (build)**

## Files

- [Brownfield Discovery — Execution Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fbrownfield-discovery%2FEXECUTION-LOG.md)
- [foreman.config](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fbrownfield-discovery%2Fforeman.config.json)
