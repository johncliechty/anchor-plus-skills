# v1.1.3 share-fix — handoff (2026-08-01)

Recovery release for the broken 1.1.x collaborator distribution
(`friction-intake-2026-07-30.md`). Built on branch `sharefix/v1.1.3`.
All work reviewed against the Fable adversarial review of the recovery plan;
six decisions locked by John (builder=distro.py · token enforced · skills
junction→copy · honest launcher (no service) · summaries opt-in on shared ·
automated sandbox + John's VM check).

## What changed (by commit)

1. **Packaging + gates + version** — `dist_manifest.txt` gains the 13 missing
   runtime modules (the 11 from the friction intake + `orientation.py` +
   `parity.py`, found by the new gate itself), the whole `share_*`/onboard
   cold-start surface, `VERSION`/`CHANGELOG.md`/`anchor.ico`. `distro.py` is
   the ONE blessed builder with a new fail-closed **import-closure gate**
   (static, sees lazy imports; optional list: `update_transaction`, `tools`)
   and emits a thin consumer `CLAUDE.md`. `_build_clean_ship.py` is now a
   thin wrapper that raises on any gate hit (it used to print-and-ship).
   Vendored skill bundles drop dev-only `test/` dirs (planted fixtures).
   The stale 61MB `planning/**/package-v1` trees are removed from git
   (history keeps them; last build archived locally under `_archive/`).
   `VERSION` = `pyproject.toml` = `1.1.3`.

2. **Onboard truth** — `onboard.register_service`'s dead `anchor.registrar`
   path and fake "foreground fallback port N" are gone.
   `share_onboard.spawn_anchor_server` GENUINELY starts the server (detached,
   token wired into env, `ANCHOR_PROACTIVE_SUMMARY=0` default on shared
   installs); `launch_anchor_dashboard.py` uses it and hands the token to the
   browser ONCE via the loopback URL (page stores it, mints the HttpOnly
   cookie via `/api/auth/login`, strips the URL). Onboard installs
   `pywinpty` on Windows Package B (probe-first; honest failure). Claude
   skill registration: symlink → REAL directory junction (stock Windows, no
   admin/DevMode) → marked full copy — never a pointer-marker dir; legacy
   pointer dirs heal on re-onboard. `anchor_gui.main()` honors an explicit
   `ANCHOR_PROACTIVE_SUMMARY=0`. `doctor.py` gains deterministic probes
   (missing modules / pywinpty / git / CLIs / token / server).
   `USER-ONBOARD.md`'s three false claims fixed.

3. **Acceptance tooling** — `tools/share_sandbox.py` (10-gate automated
   stranger sandbox; ALL GREEN 2026-08-01) + `tools/vm_check.ps1` (John's
   clean-box one-shot) + `tests/test_sharefix_v113.py` (22 unit gates).

## Sandbox result (2026-08-01, this machine)

10/10: build fail-closed (990 files) · completeness · version · cold boot
GET / 200 · tokenless POST 401 / tokened 200 · **New General session starts
(stub PTY)** · errors.log ZERO ModuleNotFoundError · onboard installs 13
skills all Claude-readable via junctions (junction mode forced — and note:
symlink creation FAILS in-process on this very machine, so the junction path
is what real collaborators will exercise) · doctor quiet-on-complete /
loud-on-hole.

## Status 2026-08-02 — effort FINISHED locally (merge + tag done)

- Branch merged to master (`--no-ff`), tagged **v1.1.3** locally. NOT pushed.
- **Artifact built** (fail-closed, all gates): `C:\dev\Anchor-ship\clean-ship\`
  — `B-anchor-plus-skills` (989 staged files) + `A-skills-only` (601 files).
  Built trees now land OUTSIDE the repo (default `<repo-parent>/Anchor-ship`,
  override `ANCHOR_SHIP_OUT`) so stale product copies never pollute
  `planning/` again.
- **Pull dry run 7/7 GREEN** (`tools/pull_dry_run.py`, 2026-08-02): the built
  B package was copied to a fresh scratch dir (simulated collaborator unzip)
  and the REAL journey ran against that copy — doctor quiet · hermetic B
  onboard installs 13 skills all Claude-readable (junction-forced) with
  readiness **ready** · the REAL `launch_anchor_dashboard.py` genuinely
  spawned the server on an isolated port with the token wired (exit 0,
  GET / 200) · tokenless POST 401 / tokened 200 · **New General session
  started** under the stub PTY · errors.log ZERO ModuleNotFoundError.
- Sandbox re-run 10/10; targeted test net 200 passed.

## Status 2026-08-02 (later) — pushed; clean-profile run 8/8; VM gate open

- **Pushed**: `master` + tag `v1.1.3` → origin (`E:\anchor.git`).
- **Clean-profile VM-approximation run 8/8 PASS** — see
  `CLEAN-PROFILE-RUN.md` (fresh profile + fresh venv + PATH without
  git/node/claude): real pywinpty pip-install exercised; 13 skills
  Claude-readable via junction-only; bare-box AND with-git journeys green;
  zero ModuleNotFoundError.
- **Problems journaled** (friction journal): `2026-08-02-02` journal-CLI
  --help papercut (open) · `-03` wrapper sys.path (resolved 70c50a0) ·
  `-04` Package-A closure on lazy foundry_integrity (resolved 70c50a0) ·
  `-05` TRUE-VM verification pending (open — the collaborator-invite gate).

## Status 2026-08-02 (later still) — token keystone fixed; sandbox staged, reboot pending

- **Decision-2 keystone gap found + fixed (6a276f4)**: the documented
  `.\onboard.cmd → python -m share_onboard` cold start never minted the
  access token (only legacy `python onboard.py` did) — the launcher had
  nothing to wire and collaborators would have run auth-OPEN.
  `run_share_onboard` (B) now mints through the launcher's own seam;
  hermetic-guarded; artifact REBUILT with the fix; tag v1.1.3 re-pointed
  (dd9c843) + pushed (safe — nothing distributed yet). Journaled
  `2026-08-02-06`, resolved.
- **Windows Sandbox**: feature ENABLED (UAC approved) — `RestartNeeded=True`;
  the binary does not exist until a reboot.
- **Fully-automated true-VM check STAGED** at `C:\dev\Anchor-ship\vm-sandbox\`
  (package copy w/ token fix · Python 3.12.10 installer · in-sandbox driver
  covering: python-less bootstrap honesty → REAL onboard (token mint +
  pywinpty pip install + junction skills into the fresh profile) → REAL
  launcher on default :8777 with the token read from the MINTED file →
  401/200 → engine-less term_start honesty + stub session → clean errors.log
  · host driver that launches, polls, prints the verdict, closes).

## Status 2026-08-02 (final) — PRE-VM COLLABORATOR DROP READY (John's call, traveling)

John cannot reboot for ~2 days and explicitly chose to let a few
collaborators try v1.1.3 BEFORE the Windows-Sandbox VM check. Final
hardening pass done (the "parable of the orange" review — instructions
rewritten around what a user actually needs):

- **Docs fixed via the user-needs walk**: zip-first install (with the
  Mark-of-the-Web "Unblock" step), up-front "what you need" split
  (dashboard-only vs AI features), "first ten minutes", the FRICTION-JOURNAL
  feedback loop (`anchor.py journal` → `friction-report` → send to John),
  data-lives-in-the-package-folder upgrade warning, and the errors.log
  location corrected in BOTH USER-ONBOARD.md and the shipped CLAUDE.md
  (default data dir = the package folder, NOT ~/.anchor).
- **Final artifact rebuilt** (B 989 / A 601, all gates), element audit
  14/14, and ALL THREE suites re-run against it: pull dry run 7/7 ·
  clean-profile 8/8 · build sandbox 10/10.
- **Ready to send, at `C:\dev\Anchor-ship\`**:
  `Anchor-plus-skills-v1.1.3.zip` (9.7 MB) · `Skills-only-v1.1.3.zip`
  (3.6 MB) · `SHA256SUMS.txt` · `SHARE-NOTE.md` (paste-ready message).
- **Accepted residual for the early drop** (documented in SHARE-NOTE): the
  genuinely-untested residue is a foreign Windows image + the winget/
  python.org bootstrap on a python-less box; both degrade with honest
  printed instructions. vm-sandbox pkg refreshed to the FINAL build.

## Status 2026-08-02 (clone distribution) — GITHUB REPO LIVE

John chose clone distribution over zips. Done:

- **Private repo published**: `https://github.com/johncliechty/anchor-plus-skills`
  — the built, gated Package B tree (991 files, tag v1.1.3), NOT the author
  monorepo. Publisher: `tools/publish_share_repo.py` (mirror → force-add →
  **count invariant**: refuses to push if any built file failed to track).
- **Publish bug found + fixed on first contact**: the shipped .gitignore's
  unanchored author rules (`gandalf/`, my new `domains/` `logs/` set)
  silently dropped the WHOLE gandalf skill + the starter scaffold from the
  first publish. Fixed: rules root-anchored, publisher force-adds + count
  invariant; verified by a REAL clone from github.com — 991 files, 13
  skills, starter present, **pull dry run 7/7 against the clone**, and user
  data files created in a clone are invisible to git (`git pull` upgrade is
  data-safe, proven).
- Docs rewritten clone-first (USER-ONBOARD + SHARE-NOTE): accept invite →
  clone → onboard.cmd → launcher; upgrades = `git pull`; zips remain at
  `C:\dev\Anchor-ship\` as the no-github fallback.

## Status 2026-08-03 — repo PUBLIC; republished from clean HEAD

- **Repo flipped PUBLIC** (John's call — low-touch sharing, no invites).
  All-rights-reserved, no LICENSE = default copyright. Docs de-invited
  (USER-ONBOARD / SHARE-NOTE / TEST-EMAIL) and republished.
- **Gate save + process rule**: rebuilding from the working tree FAILED the
  import-closure gate — uncommitted v1.2 steward WIP (`anchor_gui.py` +
  `commission_executor.py`) had appeared in the tree. Correct refusal.
  **RULE: share builds run from a clean worktree of committed HEAD**
  (`git worktree add <tmp> master` → `ANCHOR_SHIP_OUT="C:\dev\Anchor-ship"
  python <tmp>/planning/share-anchor-skills-2026-07/_build_clean_ship.py`),
  journaled `2026-08-03-01` (open: make the builder enforce this itself).
  NOTE for John: that steward WIP sits UNCOMMITTED in C:\dev\Anchor — a
  service restart would run it; it was NOT shipped (verified: the public
  clone has zero commission_executor references).
- **Verified on the PUBLIC repo**: anonymous-style fresh clone = 991 files,
  13 skills, public-docs present, no WIP leak, **pull dry run 7/7 against
  the clone**. Zips + vm-sandbox pkg refreshed to the same build.

## Remaining steps

1. **John, from the road**: just send `TEST-EMAIL.md` (no invites needed
   now) to whoever should try it. Clone URL:
   `https://github.com/johncliechty/anchor-plus-skills`
2. **After returning (~2 days)**: reboot PUTER (park live sessions warm
   first if needed: `python tools/pre_restart_drain.py`; reboot also
   cold-deploys v1.1.3 into the NSSM service — no-ops for your config).
3. **Run the sandbox check** (or ask Claude to):
   `python C:\dev\Anchor-ship\vm-sandbox\host_run.py`
4. If green: resolve journal `2026-08-02-05`; widen the invite list.
2. **Tell collaborators**: wipe the old install (delete the old package
   folder + `%USERPROFILE%\.claude\skills\*` entries that are marker-only
   dirs — or just re-run onboard, which heals them), unzip v1.1.3, run
   `.\onboard.cmd`, then `python launch_anchor_dashboard.py`.
3. **Your own machine is untouched**: the NSSM service env has no
   `ANCHOR_PROACTIVE_SUMMARY`, so summaries stay proactive; the launcher
   short-circuits when :8777 is already up. NOTE: next `nssm restart anchor`
   picks up the anchor_gui.py changes (token-bootstrap JS + summarizer flag
   honor) — both are no-ops for your config.

## Accepted residuals (documented, deliberate)

- `ANCHOR_AUTH_MODE` stays `open` on shared installs for THIS release: the
  minted token gates every mutating `/api/*` route + the terminal/WS/RCE
  surface, but read-only data-plane GETs stay open on loopback. Full
  enforcement (`enforce` + static frontend + cookie navigation) is the v1.2
  hardening track — flipping it now risks 401-ing the very installs this
  release fixes, and the DAG ties `enforce` to the static frontend pillar.
- No auto-start on login (launcher re-run after reboot). A schtasks logon
  task was scoped out (Decision 4).
- `zombie-hunter`/`tidy-idy` Python bridges ship; their Node skill servers
  resolve via `~/.claude/skills` or `ANCHOR_FOUNDRY_DIR` and degrade
  honestly when absent.
- The reaper daemon ships UNARMED by default (arming ladder + the
  `.anchor/reaper.disarmed` brake).

## Test evidence

- `tests/test_sharefix_v113.py` — 22 passed
- skills-root w0/w1 — 35 passed (junction-aware)
- share package A/B + onboard w5 — 49 passed
- distro/vendor/onboard/doctor/parity/launcher net (22 files) — 335 passed
  total after the two legit test updates (CLAUDE.md emission; junction-aware
  dual-copy cleanup). Pre-existing failure `test_no_module_imports_gemini_sdk`
  FIXED by the package-v1 removal (verified pre-existing via stash probe).
- Full suite NOT run wholesale (known flaky-under-load; regen traps) —
  targeted nets only, per repo convention.
