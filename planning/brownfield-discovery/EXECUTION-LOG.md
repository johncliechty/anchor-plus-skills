# Brownfield Discovery — Execution Log

> Foreman appends per-wave EXECUTE/GATE/REVIEW/JUDGE/FIX verdicts here during the build.

## Wave 1 — brownfield_scan.py — PASS
- Implemented `brownfield_scan.py`: bounded walk (depth<=6, files<=5000), skips
  `.git/node_modules/_archive/.anchor`, classifies by trio provenance signals
  (foreman checkpoint/config -> build; named planning docs -> planning;
  report.md/pdf under research/ -> research; deliverables/** -> deliverables;
  generic *.pdf + root *PLAN*.md -> docs, NOT adopted). Robust to
  missing/mistyped/UNC path (empty ScanResult, no raise).
- `tests/test_brownfield_scan.py` (18 tests) green: full ScanResult + exact
  numeric counts for the planted fixture, parametrized single-file
  classification, robustness cases, own-`.anchor`-store-not-imported,
  JSON-serializable `to_dict`.

## Wave 2 — effort_history discovery model + reconciliation — PASS
- Added `source="discovered"`, stable path-hash `discovered_job_id`,
  `adopt_discovered` (idempotent upsert + prune-on-rescan), `reconcile_discovered`
  (prune-on-deleted-artifact). Discovered records carry real metadata only
  (rel path, mtime->created_at, title, kind), NO cost/tokens/session_id.
- `lane_rollup`/`project_rollup` EXCLUDE discovered from effort_count + cost,
  add parallel `discovered_count` (+ `discovered_cost`=0). `list_efforts` still
  returns discovered records.
- `tests/test_brownfield_adopt.py` (6 tests) green: 2 real + 3 discovered ->
  effort_count==2/discovered_count==3/cost unchanged; idempotent double-adopt;
  rescan prunes deleted artifact; reconcile never prunes real efforts.
- LOCKED `tests/test_cost_rollup.py` 3/2/1 effort_count asserts STILL green
  (seeds no discovered efforts).

## Wave 3 — render honesty — PASS
- `_gather_project_efforts` threads `discovered`/`artifact_path`/`title`/`kind`;
  vN computed over REAL efforts only; discovered cards get an `imported` marker
  + a small `.dotdisc` dot + `data-discovered="1"`, NO vN, cost 0, never
  live/done, and link to `/artifact/<pid>?path=<rel>` (not `/report`).
- Tile + cost rollup render `N efforts · M imported · $X`.
- `tests/test_brownfield_render.py` (3 tests) green.
- LOCKED `tests/test_rnd_project_window_kanban.py` `>v2<`/`>v1<` STILL green
  WITH a discovered card also present in the served HTML.

## Wave 4 — /artifact route + status_line + home panel — PASS
- New `GET /artifact/<pid>?path=<rel>` using `report_viewer.resolve_project_artifact`
  (the katex_asset containment pattern: target=(folder/rel).resolve();
  target.relative_to(folder) or reject). Rejects absolute rel, ../.. escape,
  .git/.anchor, symlink-escape -> 400/404, ZERO bytes read.
- `rnd_registry.status_line()` now reflects adopted+real per lane
  (has-runs / imported / none-yet) — no longer hardcoded.
- Home dashboard R&D panel/tiles populate (tile reads project_rollup +
  status_line; shows `N efforts · M imported`).
- Added `discover_and_adopt(pid)` pipeline + `POST /api/rnd/rescan` + Rescan
  buttons on the project window, tile, and home panel.
- `tests/test_artifact_route_safety.py` (14 pass, 1 skip — symlink needs admin
  on this host; containment via resolve() covers it). LOCKED
  `tests/test_report_route_safety.py` (single-segment `_unsafe_path_seg`) STILL
  green — the new route uses a SEPARATE containment guard, not `_unsafe_path_seg`.

## Wave 5 — Anchor.md marker writer (lock-safe, no-churn) — PASS
- `anchor_marker.write_anchor_md(folder)`: renders `Anchor.md` at folder root,
  STRUCTURE ONLY (project sections, per-lane real+imported counts, relative
  paths, titles, last-scanned), under `paths.WRITE_LOCK`, hash-compared
  (no-churn — unchanged folder is NOT rewritten on 2nd open). Machine sidecar
  `.anchor/projects/<id>/discovery.json` = full ScanResult.
- `tests/test_anchor_marker.py` (7 tests) green: no secret/file-content leak,
  no-churn, structural-change rewrite, sidecar, N-projects sections, 24-thread
  concurrency yields one consistent file, missing-folder noop.

## Wave 6 — wiring (register + open + Rescan) — PASS
- `discover_and_adopt(pid)` wired into register (`select_existing_project` /
  `create_new_folder_project`), open (`GET /project/<id>`), and
  `POST /api/rnd/rescan`. Rescan buttons added to project window + tile + home
  panel. Idempotent (stable path-hash job_ids -> no dupes), prunes deletions.
- `tests/test_brownfield_wiring.py` (3 tests, live throwaway server) green:
  register populates tile (imported) + Kanban (3 discovered cards) + writes
  Anchor.md; open re-syncs; rescan idempotent + prunes a deleted artifact;
  unknown-project rescan -> clean 404.

## Wave 7 — end-to-end live verify + full-suite gate — PASS
- `python -m pytest -q`: **284 passed, 1 skipped** (symlink-escape test skips —
  symlink creation needs admin on this host; `resolve_project_artifact`
  containment via `resolve()`+`relative_to()` covers that path and the direct
  rejection test exercises it). Baseline 236 unchanged + 48 new; NO existing
  test weakened/deleted.
- LIVE HTTP smoke (throwaway server port=0, never 8777, no live claude) ALL
  PASS on a tmp folder seeded with planning/MASTER-PLAN.md +
  foreman-checkpoint.json + an incidental vendored paper.pdf:
  * home R&D panel shows `2 imported` + the tile; project window shows 2
    discovered cards (data-discovered, no vN, /artifact links, imported marker);
  * the incidental pdf is NOT adopted as an effort (listed in sidecar docs only);
  * /artifact opens the real MASTER-PLAN.md (200 + bytes);
  * ../../, absolute, .git/config, planning/../.. all -> 404, ZERO leak;
  * rescan after deleting an artifact prunes its card (2 -> 1 discovered);
  * Anchor.md is structure-only (names project + relative paths; NO secret, NO
    prose body).
- distro build clean: ships brownfield_scan.py + anchor_marker.py; staged scan
  has no personal-data hits; all new shipped test files are scan-clean (planted
  secrets built at runtime / non-secret-named).
