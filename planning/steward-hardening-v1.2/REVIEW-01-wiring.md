# Steward (Ecgberht) hardening — Review 01: wiring + surface audit

**Branch:** `v1.2` in `C:\dev\Anchor` (private mirror `E:\anchor.git` only — never
the public repo). Base: `ef85b55` = hardened v1.1 + the steward commit `b9252a9`.

**Scope of this pass:** is the steward *wired* — routes, handlers, frontend,
assets, containment? Not yet: behaviour under failure, or whether the engine
says true things.

## Canonical source settled first

Two copies of the steward existed. They are not the same:

| Tree | ecgberht functions | Verdict |
|---|---|---|
| `C:\dev\Anchor` @ `b9252a9` | **13** (project seal-chamber **+** High Seat/portfolio) | **CANONICAL** |
| `C:\dev\Anchor-dev` (uncommitted) | 5 (project chamber only) | stale, older, ignore |

No porting was needed for v1.2: the release bundle was produced by *reverting*
`b9252a9`, so master already equals hardened-v1.1 + steward. `v1.2` is a branch
at that point.

## What is CLEAN (verified, not assumed)

- **Route/handler/UI wiring is complete.** 8 routes declared, 8 handlers defined,
  8 endpoints called by the UI. Zero orphan handlers, zero UI calls to a
  non-existent route, zero routes the UI never calls.
- **All 8 routes are `AUTH_TOKEN`, `migrated=True`.** No unauthed steward surface.
- **`handle_ecgberht_artifact` containment is correct** — `resolve()` +
  `relative_to(root)`, the same idiom as `static_asset`. Because it compares the
  *resolved* path, a symlink escaping the project is caught too.
- **Frontend entry points exist.** `openEcgberhtHighSeat` and `openEcgberhtSeal`
  are both defined in shipped JS. (`createNewProject` flagged by the first audit
  pass was a regex false positive — it is a pre-existing dashboard function.)
- **Static + brand assets all present:** `static/high-seat.css`,
  `static/high-seat.js`, `vendor/brand/ecgberht-portfolio-high-seat.jpg`,
  `vendor/brand/ecgberht-project-seal.jpg`.
- **Both Node bridges exist:** `Ecgberht/scripts/seal-chamber-bridge.mjs` and
  `Ecgberht/scripts/high-seat-bridge.mjs`.
- **The bridge fails honestly, not open.** Missing engine →
  `ecgberht_engine_missing` with a fix hint; spawn failure →
  `bridge_spawn_failed`; empty stdout → `bridge_no_output`; unparseable →
  `bridge_bad_json`. Each returns `ok:false` and the handler maps it to 502.
- **`creationflags=_paths.NO_WINDOW`** is set on the spawn — respects the
  standing no-popup-PowerShell rule.
- **No host-absolute literal** in call sites; `ECGBERHT_ROOT` env override with a
  sibling-checkout fallback.

## FINDINGS

### F1 — Zero test coverage on the entire steward surface (P0)

8 routes, 13 functions, ~372 lines of JS, ~300 lines of Python: **no test file
mentions ecgberht at all.** Every other subsystem in this repo has a stub gate.

This is the finding that matters. The wiring is clean *today*, and nothing keeps
it that way — the two defects already found in this codebase (`foundry_map`
schema never shipped; the status cadence documented but never armed) were both
"correct once, silently rotted". Nothing here would catch a route losing its
handler, an endpoint losing its UI call, or the containment check being relaxed.

**Fix:** a `tests/test_ecgberht_steward_*.py` stub gate that pins, at minimum:
route↔handler↔UI wiring completeness, `AUTH_TOKEN` on every steward route,
artifact traversal refusal (`../`, absolute path, symlink escape), and every
bridge failure mode returning `ok:false` + 502 rather than 200.

### F2 — Bridge timeout does not bound total request time (P1)

`_ecgberht_bridge(timeout=20)` and `_ecgberht_hs_bridge(timeout=30)` bound ONE
spawn. `handle_ecgberht_high_seat` iterates portfolio roots; if it bridges per
root, N slow roots serialise into N×30s while holding a server thread. Anchor is
a threaded stdlib server — a handful of these can starve the dashboard. Needs a
whole-request budget, not just a per-spawn one. *(To confirm in review 02.)*

### F3 — `handle_ecgberht_artifact` reads whole files into memory (P2)

`target.read_bytes()` with no size cap, then sends. A large artifact in a project
folder is an unbounded allocation on a shared server thread. Other Anchor file
routes should be compared for the same idiom.

### F4 — `--project ""` is reachable (P2)

`_ecgberht_project_folder` returns `proj.get("folder_path", "")` and the chamber
handler passes it straight to the bridge without checking it is non-empty. A
registry row with a blank `folder_path` sends `--project ""` to Node. Should be
an honest 4xx before spawning anything.

### F5 — Engine test suite not yet run (deferred, deliberate)

`Ecgberht/scripts/run-all-tests.mjs` exists but was NOT executed. Standing rule
on this machine: never blind-run a suite that might spawn live billable engine
sessions (8,816 leaked sessions, 2026-06-20 → 2026-07-14). Audit it for live
spawns first, then run.

## Next (review 02)

1. Read all 8 handlers end to end for failure behaviour + confirm/kill F2.
2. Audit `high-seat.js` + the project-window steward JS for real defects
   (error paths, 401 handling, double-mount — the same class that caused the
   terminal double-print).
3. Audit `run-all-tests.mjs` for live spawns, then run it.
4. Land the F1 stub gate, then fix F2–F4 with tests.
