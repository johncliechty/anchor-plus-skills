# Anchor Brownfield Discovery + `Anchor.md` Marker — Implementation Plan

> Crucible Stage 2 (converged after a Stage-1 and a Stage-2 Shark-Tank round, all
> findings code-verified). Foreman-ready: 7 waves, each with an orchestrator-gateable
> `done-when` + Given/When/Then. Product code is Python-stdlib-only. The full 236-test
> suite must stay green.

test-command: python -m pytest -q

## North Star (locked)
When an R&D project is registered or opened on an existing folder, Anchor INSTANTLY
(local, no tokens, no agent) discovers genuine pre-existing trio artifacts and ADOPTS
them so the dashboard POPULATES (home R&D panel + tile rollup + project Kanban fill in)
— but HONESTLY: discovered items are excluded from the real `effort_count` (shown
separately as "M imported"), get NO `vN` label, are clickable to their REAL on-disk
file, and carry a SUBTLE `imported` marker (a small dot). Anchor also writes/maintains
`Anchor.md` (human, structure-only, no-churn) + a machine sidecar.

## Honesty contract (the spine — every wave serves it)
- Discovered records carry `source="discovered"`; real available metadata only
  (path, `mtime`→`created_at`, title, kind); **never** fabricated cost/tokens/session_id.
- `list_efforts` still RETURNS discovered records (render needs them); only the
  ROLLUP counters exclude them. Tile reads `N efforts · M imported · $X`.
- Discovered cards: subtle dot, no `vN`, clickable to the real file. Not masqueraded
  as Anchor-run sessions.

---

## Wave 1 — `brownfield_scan.py` (pure scanner/classifier, stdlib)
Bounded walk (skip `.git`, `node_modules`, `_archive`, the project's own `.anchor`;
depth cap ~6, file cap ~5000; ignore large binaries). Classify by **trio provenance
signals**, not broad globs: `build`=`foreman-checkpoint.json`/`foreman.config.json`;
`planning`=`planning/**` trio docs (`*MASTER-PLAN*`,`*IMPLEMENTATION-PLAN*`,
`*EXECUTION-LOG*`,`*DECISION-LOG*`); `research`=`report.md`/`report.pdf` under a
research store / researchPrime markers; `deliverables`=declared outputs. Generic
`*.pdf`/`*PLAN*.md` → low-confidence `docs` (listed, NOT adopted). Robust to a
missing/huge/UNC/mistyped path (returns an empty `ScanResult`, never hangs/raises).
Returns `ScanResult{by_lane, docs, counts, generated_at}`.
- **done-when:** `tests/test_brownfield_scan.py` (planted-fixture + `@pytest.mark.parametrize`,
  house style of `test_distro_scan.py`) is green and asserts the FULL `ScanResult` with
  numeric `counts` for ALL these cases.
- **GWT:** GIVEN a fixtures folder containing `foreman-checkpoint.json`,
  `planning/MASTER-PLAN.md`, a root `FUNDING-PLAN.md`, a vendored `paper.pdf` under a
  dir named `research/`, and `.git/`+`.anchor/`+`node_modules/` subtrees, WHEN `scan()`
  runs, THEN checkpoint→`by_lane.build`, `MASTER-PLAN.md`→`by_lane.planning`,
  `FUNDING-PLAN.md`→`docs` (NOT adopted), `paper.pdf`→`docs` (NOT an effort), and the
  `.git`/`.anchor`/`node_modules` trees are skipped; `counts` match exactly.

## Wave 2 — `effort_history` honest-discovery model + reconciliation
Add `source="discovered"` to pointer-records. `adopt_discovered(folder, pid, scan)`
creates/updates records with a STABLE path-hash `job_id` (idempotent rescans),
`mtime`→`created_at`, title, real artifact rel-path; NO cost/tokens/session_id.
`list_efforts` STILL returns discovered records. `lane_rollup`/`project_rollup`
EXCLUDE `source="discovered"` from `effort_count` and cost, and ADD a parallel
`discovered_count` (+`discovered_cost`=0). **Reconcile on rescan:** discovered records
whose artifact no longer exists on disk are PRUNED (they are derived, so safe to
remove — unlike real efforts, which are never touched).
- **done-when:** new tests green AND the existing `test_cost_rollup.py` 3/2/1
  `effort_count` assertions pass unchanged (they seed no discovered efforts).
- **GWT:** GIVEN 2 real + 3 discovered efforts, WHEN `project_rollup` runs, THEN
  `effort_count==2`, `discovered_count==3`, cost unchanged; AND adopting twice yields
  no duplicates; AND after a discovered artifact is deleted + rescan, its record is gone.

## Wave 3 — render honesty (no security surface yet)
Thread `is_discovered` + `artifact_path` through `_gather_project_efforts` into the
effort view. Compute `vN` over NON-discovered efforts only; discovered cards get an
`imported` marker (`data-discovered="1"` + a small dot class), never a `vN`. Tile +
cost rollup render `N efforts · M imported · $X`.
- **done-when:** render tests green, machine-asserted (no human "subtle" judgement).
- **GWT:** GIVEN a project with 2 real research efforts AND 1 discovered planning doc,
  WHEN the window/tile render, THEN the real research cards still read `>v2<`/`>v1<`
  (existing test stays green), the discovered card contains `data-discovered="1"` and
  NO `>v<` token, and the tile text contains `1 imported`.

## Wave 4 — `/artifact` file route (security) + `status_line()` + home panel
New `GET /artifact/<pid>?path=<rel>` serving a discovered artifact from the project
folder, using the proven `report_viewer.katex_asset` containment pattern:
`target=(folder/rel).resolve()` then `target.relative_to(folder.resolve())` or 404;
reject absolute `rel`, reject resolved paths under `.git`/`.anchor`, reject
symlink-escape. Wire `rnd_registry.status_line()` to reflect adopted+real efforts per
lane. Ensure the HOME-dashboard R&D panel + tiles (not only the project window) reflect
adopted efforts.
- **done-when:** a REQUIRED negative test (mirroring `test_report_route_safety.py`)
  green AND a status-line test green AND the home view renders imported counts.
- **GWT:** GIVEN a discovered artifact at `planning/MASTER-PLAN.md`, WHEN
  `GET /artifact/<pid>?path=planning/MASTER-PLAN.md`, THEN 200 + the file bytes; WHEN
  `?path=../../secret`, `/etc/passwd`, `.git/config`, or a symlink-escape, THEN 400/404
  and zero bytes read; AND `status_line()['planning'] != 'none-yet'`; AND the home R&D
  panel tile shows `1 imported`.

## Wave 5 — marker writer (`Anchor.md` + sidecar), lock-safe + no-churn
`write_anchor_md(folder)` renders `Anchor.md` at the folder root under
`paths.WRITE_LOCK`: project name(s) (one section per project sharing the folder),
per-lane counts (real + imported), deliverables, key RELATIVE paths, last-scanned —
**STRUCTURE ONLY, never file contents**. Hash-compare: rewrite only if changed.
Machine sidecar `.anchor/projects/<id>/discovery.json` = full `ScanResult`.
- **done-when:** commit-safety test (asserts no file-content/secret leakage in
  `Anchor.md`) green; no-churn test green; concurrency test (house style of
  `test_threading_locks.py`) green.
- **GWT:** GIVEN an unchanged folder, WHEN `/project/<id>` opened twice, THEN
  `Anchor.md` is not rewritten on the 2nd open (mtime stable); WHEN N threads open the
  same project concurrently, THEN exactly one consistent `Anchor.md` (no corruption).

## Wave 6 — wiring (register + open + Rescan)
One pipeline `discover_and_adopt(pid)`: scan → adopt → reconcile → write marker;
idempotent, bounded, folder-path-robust. Call from `rnd_registry.add_project`
(register), the `/project/<id>` GET handler (open), and `POST /api/rnd/rescan {id}`
(+ a **Rescan** button on the project window, the project tile, and the home R&D panel).
- **done-when:** registering or opening a brownfield project populates the Kanban +
  tile + home panel from disk; Rescan re-syncs with no dupes and prunes deletions.
- **GWT:** GIVEN a folder with prior trio docs, WHEN a project is registered on it,
  THEN its tile immediately shows imported counts and its Kanban is non-empty.

## Wave 7 — end-to-end live verify + full-suite gate
Live HTTP (throwaway server, mock runner): a project on a folder containing
`planning/*.md` + `foreman-checkpoint.json` renders a non-empty, honestly-labeled
dashboard on BOTH the home R&D panel and the project window; the `/artifact` link
opens the real file; rescan is idempotent and prunes a deleted artifact; `Anchor.md`
is commit-safe.
- **done-when:** `python -m pytest -q` green (≥236 + new) with no weakened tests AND
  the live smoke passes.
- **GWT:** GIVEN the seeded brownfield folder, WHEN the dashboard + project window are
  served, THEN both show the imported counts, the discovered card opens its real file,
  and the full suite is green.

## Sequencing / safety notes
- Wave 4 lands the `/artifact` route TOGETHER with its negative test (no insecure
  intermediate state).
- Discovered records are reconcilable (derived); real efforts are never mutated/pruned.
- Everything bounded + lock-guarded; commit-safe marker; stdlib-only.
