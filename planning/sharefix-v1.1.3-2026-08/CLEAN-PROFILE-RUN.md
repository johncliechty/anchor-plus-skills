# Clean-profile VM-approximation run — 2026-08-02, 8/8 PASS

The strongest clean-box simulation possible on PUTER without a real VM
(Windows Sandbox feature not enabled; Hyper-V needs elevation). Run against
the BUILT v1.1.3 artifact (`C:\dev\Anchor-ship\clean-ship\B-anchor-plus-skills`),
driver kept in the session scratchpad (one-off; `tools/pull_dry_run.py` and
`tools/vm_check.ps1` are the durable acceptance tools).

## Isolation used

- fresh scratch **user profile** (USERPROFILE/HOME/APPDATA/LOCALAPPDATA all
  redirected — nothing read from or written to the real profile)
- fresh **venv** = a python with NO pywinpty installed
- minimal **PATH** = venv + System32 only → `git`, `node`, `claude`, `agy`
  all absent (the bare collaborator box); second variant re-adds git only
- isolated ports + `ANCHOR_DATA_DIR`; stub PTY backend (no engine spawn,
  no billing); live `:8777` never touched

## Results

| # | Check | Result |
|---|---|---|
| C1 | Bare-box doctor | exit 1 with exactly the right prescriptions (pywinpty, Node, git, no CLI) and **zero** "MISSING from this install" modules |
| C2 | `install_terminal_extra` on a clean python | **really pip-installed pywinpty** from PyPI into the venv (the exact fix for the collaborator's manual-install friction) |
| C2b | Doctor after install | pywinpty prescription cleared |
| C3 | Fresh-profile Package-B onboard (auto chain) | 13 skills installed, ALL Claude-readable, readiness **ready** — mechanisms: **junction only** (symlink creation fails from a normal process on this box, same as a stock collaborator box) |
| C4 | Launcher on the bare box | exit 0, spawned server, GET / 200 |
| C5 | New General with NO git | session starts **in-place** (`worktrees.create_worktree`'s documented degrade: `isolation: "none"`, never pretends isolation); server stays up |
| C6 | New General WITH git | full worktree flow, session starts, killed clean |
| C7 | errors.log (both variants) | **zero** ModuleNotFoundError |

Initial C5 expectation was wrong in the DRIVER (expected a refusal); the
product's in-place degrade is designed and documented — check corrected,
noted here for honesty.

## Journal entries from this phase (friction journal)

- `2026-08-02-02` (concern, OPEN) — `anchor.py journal` has no `--help`
  guard; any first arg becomes an entry.
- `2026-08-02-03` (friction, RESOLVED 70c50a0) — clean-ship wrapper couldn't
  run as a plain script (sys.path).
- `2026-08-02-04` (friction, RESOLVED 70c50a0) — Package A tripped its own
  import-closure gate on distro's lazy `foundry_integrity` (gate working as
  designed; declared optional for A).
- `2026-08-02-05` (problem, OPEN — **the collaborator-invite gate**) — true
  clean-VM verification still pending; no VM reachable non-elevated.

## What the true VM run still adds (and how to unblock it)

Covered here: everything except a genuinely different Windows image and the
python-absent → winget bootstrap path of `onboard.ps1`.

To unblock, either:
1. Elevated PowerShell:
   `Enable-WindowsOptionalFeature -Online -FeatureName "Containers-DisposableClientVM" -All`
   then reboot → Windows Sandbox becomes available and the run can be
   automated end-to-end (mapped folder + LogonCommand), or
2. any existing VM / spare machine: copy
   `C:\dev\Anchor-ship\clean-ship\B-anchor-plus-skills` over and run
   `powershell -ExecutionPolicy Bypass -File .\tools\vm_check.ps1`, then walk
   `.\onboard.cmd` once interactively.
