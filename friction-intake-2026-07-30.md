# Anchor friction — sleep-cycle intake (2026-07-30 12:08)

**3 record(s)** · status `open` · Anchor 1.1.2

## What hurt, by area

### terminal — 2 record(s) (problem)

- **Static import audit: 8 more local Python modules missing beyond the reaper/freeze_state/zombie_hunter/foundry_acceptance already logged** `2026-07-30-02-static-import-audit-8-more-local-python` · 2026-07-30T12:06:45 · problem
  > Cross-referenced every top-level local import in Anchor/*.py against files that actually exist. Confirmed missing (none found anywhere under C:\dev, none on PyPI): proc_probe -- referenced in anchor_gui.py, anchor_healthcheck.py, gandalf.py, job_runner.py (x3), pty_manager.py (x3), skill_runner.py, supervisor.py (x2) -- 7 distinct files, the widest blast radius of any of them, looks like a core process-liveness probe used by session/PTY/supervisor code. foundry_integrity -- distro.py, foundry_north_star.py, foundry_ops.py (x2). foundry_safety -- anchor_gui.py:15965. foundry_skills -- foundry_ops.py:135. reaper_arming -- anchor.py (x2), anchor_gui.py (x4). tidy_idy_runner -- anchor_gui.py (x3), likely meant to bridge to the tidy-idy skill the same way zombie_hunter should bridge to skills/zombie-hunter -- but skills/tidy-idy has no matching Python entry point either, same gap pattern. verify_freeze_manifest -- share_ci_ship_gate.py:47, and this one is a MODULE-LEVEL import (not lazy/deferred like the others), so simply importing share_ci_ship_gate.py fails immediately. update_transaction -- anchor.py (x2), doctor.py. All of these except verify_freeze_manifest are lazily imported inside functions, which is why they have not shown up in logs/errors.log yet -- their code paths just have not been exercised this session. Combined with the already-open record (reaper, freeze_state, zombie_hunter, foundry_acceptance), that is 12 total missing local modules. Pattern: several names (zombie_hunter, tidy_idy_runner, reaper_arming) look like they were meant to bridge to Node-based skill packages under skills/zombie-hunter and skills/tidy-idy, which exist but have no Python-side entry point wired up. Others (proc_probe, foundry_integrity, foundry_safety, foundry_skills, verify_freeze_manifest, update_transaction, freeze_state, foundry_acceptance) look like pure Python modules that are simply absent from this copy of the Anchor distribution -- possibly dropped during packaging/distro.py, or never committed. Recommend the creator check distro.py / dist_manifest.txt against what actually shipped.
  - log: `import foundry_acceptance as _facc`
  - log: `ModuleNotFoundError: No module named 'foundry_acceptance'`
- **New General session broken: 3 Python modules missing (reaper, freeze_state, zombie_hunter)** `2026-07-30-01-new-general-session-broken-3-python-modu` · 2026-07-30T12:01:29 · problem
  > Boot log (logs/errors.log) shows session_registry boot reconcile failed: No module named 'reaper'; freeze_state boot reconcile failed: No module named 'freeze_state'; zombie_hunter.start_hunter failed: No module named 'zombie_hunter'. These three imports fail on every server start and also spam every ~30-60s from the /api/rnd/orphan_check background poll. Verified none of the three modules exist anywhere under C:\dev as .py files -- grep and glob both come back empty. The only real implementation is skills/zombie-hunter/src/*.js -- a Node.js implementation, never bridged to Python. Because session_registry never finishes its boot reconcile, session bookkeeping runs in a degraded state. Reproduction: clicked + New General in the dashboard for the Feynman way project -- terminal window opened with no prompt (empty), closed it, clicked + New General again -- got a fetch failed error. Separately (already fixed): the ConPTY terminal backend also failed with pywinpty (ConPTY) is unavailable -- No module named winpty -- because the optional [terminal] extra (pywinpty) was never installed in the Python environment Anchor runs under; installed it manually with pip install pywinpty>=2.0, which resolved that half of the problem. The reaper/freeze_state/zombie_hunter gap is separate and still open.
  - log: `import reaper`
  - log: `ModuleNotFoundError: No module named 'reaper'`

### zombie/sessions — 1 record(s) (problem)

- **Root cause found for the missing-modules pattern: dist_manifest.txt (distro.py's deny-by-default allowlist) never lists any of them** `2026-07-30-03-root-cause-found-for-the-missing-modules` · 2026-07-30T12:08:13 · problem
  > Read dist_manifest.txt in full. It is explicitly the single source of truth for
  > what distro.py stages into a distributed copy -- deny-by-default, unlisted files
  > simply do not ship. It documents ONE deliberate exclusion carefully:
  > update_transaction.py is intentionally not shipped, wrapped in try/except
  > everywhere it is touched (anchor.py, doctor.py), confirmed safe / degrading
  > gracefully -- that one is NOT a bug, retracting it from the list of concerns.
  - log: `import foundry_acceptance as _facc`
  - log: `ModuleNotFoundError: No module named 'foundry_acceptance'`

## How to work this brief

1. Each record is the USER'S WORDS, verbatim — treat them as ground truth.
2. Verify against the code before believing any diagnosis (including this
   file's clustering, which is keyword-only and never a model judgement).
3. Close a record explicitly when fixed:
   `python anchor.py friction-resolve <id> --commit <sha> --note "…"`
   Records stay OPEN until someone says otherwise — nothing self-resolves.
