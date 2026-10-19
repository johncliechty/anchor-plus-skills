# Shareable Anchor Distro + `/onboard` — Implementation Plan (Foreman-ready, Stage-2 Shark-converged)

> test-command: `python -m pytest -q` · branch `share-distro` off master (baseline GREEN 1483 + 1 skip).
> Design: the Shark-converged `MASTER-PLAN.md`. Re-cut to 12 single-concern waves after the Stage-2 Shark
> Tank (split over-bundled W1/W6; defined the build→push interface; replaced vacuous/prose done-whens with
> faked-platform + real-artifact + Given/When/Then assertions).

## Conventions (read before EVERY wave)
- **Python stdlib only** (lone lazy `pywinpty` in `pty_manager.py`; the POSIX backend uses the stdlib `pty`).
- **The gate host is Windows** → a cross-platform done-when MUST run on Windows via a **faked-platform /
  dependency-injected seam** (monkeypatch `sys.platform` / inject fake `pty`/`termios`/`os`/`select` / inject
  an `OSError(EADDRINUSE)`). **`pytest.skip` is NOT acceptable as the sole coverage of a POSIX path** (a
  skipped test is not a satisfied done-when — the rnd-v12 vacuous-GREEN lesson).
- **Hermetic**: temp `HOME`/`ANCHOR_SKILLS_HOME`/data-dir; stubbed seams `ANCHOR_SERVICE_CMD` /
  `ANCHOR_FOREGROUND_CMD` / `ANCHOR_GH_CMD` (`tests/stub_gh.py` + a LOCAL BARE `file://` remote) /
  `ANCHOR_TRIO_DIR` / `ANCHOR_GANDALF_DIR` (temp git repos, **mandatory** in tests). **NEVER** bind `:8777`,
  spawn a real server, register a real service, or hit real GitHub/network.
- Every wave **adds a `tests/test_*` collection item** (hold/grow vs 1483); a markdown/doc-only change still
  ships its own test. Each Done-when is an explicit **Given/When/Then** naming the asserted value.
- NO real GitHub push / NO real service registration until John signs off. Order is load-bearing.

## Wave 1 — POSIX PTY backend (`pty_manager.PosixPtyBackend`)
**Goal:** terminals run on macOS/Linux via the stdlib `pty`, behind the existing backend seam.
**Changes:** `PosixPtyBackend` (stdlib `pty`/`os`/`select`/`fcntl`/`termios`) with the same
start/write/read_since/resize/kill contract as the stub/pywinpty backends; `_select_backend` auto-picks it
on non-Windows when `ANCHOR_PTY_BACKEND` is unset (`stub` still forced in tests).
**Done-when (runs on the Windows gate via injected fakes):** Given a fake `pty.openpty`/`os.read`/`os.write`
seam injected into `PosixPtyBackend`, When a session is started + written to + `read_since`, Then the echoed
bytes round-trip and `kill` reaps it — asserted with NO `pytest.skip`; AND `_select_backend` returns
`PosixPtyBackend` when `sys.platform` is monkeypatched to `linux` and `ANCHOR_PTY_BACKEND` is unset.

## Wave 2 — POSIX single-instance guard
**Goal:** a second instance on `:8777` can't squat on macOS/Linux (parity with Windows `SO_EXCLUSIVEADDRUSE`).
**Changes:** ONE locked mechanism — `SO_REUSEADDR=0` + `classify_bind_error` on `EADDRINUSE` → clean exit(0)
for non-Windows (reuse the existing `classify_bind_error`/`use_exclusive_bind` seam; no pidfile).
**Done-when (Windows-gate-safe):** Given `sys.platform` monkeypatched to `linux` and the server-bind helper
fed an injected `OSError(errno=EADDRINUSE)`, When the guard runs, Then it returns the clean-exit decision
(asserted via `classify_bind_error`), NOT a raised traceback — no real dual bind.

## Wave 3 — `vendor_skills.py`: clean vendoring (git archive + denylist)
**Goal:** vendor the 4 skills with NO `.git`, no gitignored junk, and **no tracked personal logs**.
**Changes:** `vendor_skills.vendor_all(dest)` — `git archive <HEAD>` each source (`ANCHOR_TRIO_DIR`/
`ANCHOR_GANDALF_DIR`) into `vendor/bundled-skills/<name>/` (drops `.git/` + untracked-gitignored), THEN an
explicit **DENYLIST filter** removes tracked-but-personal files (`EXECUTION-LOG.md`, `DECISION-LOG.md`,
`CLAUDE_hist.md`, `journal/`, `*-checkpoint.json`, `.env*`) — because **`git archive` keeps tracked files
even if `.gitignore`-pattern-matched**. Write `SOURCES.md` (archived commit). A residual host-path/PII scrub
genericizes `C:\dev\…`/`/Users/<u>`/`/home/<u>` → `<path>`.
**Done-when:** Given a temp git source repo with (a) a committed normal file, (b) a gitignored+untracked
`runs/x.log`, (c) a **committed** `EXECUTION-LOG.md`, (d) a dirty uncommitted file, (e) a committed file
containing `C:\dev\foreman-targets\x` and `jane@uni.edu`, When `vendor_all`, Then the dest contains (a) only,
NO `.git/`, NO `runs/x.log`, NO `EXECUTION-LOG.md` (denylist), NO dirty file, and (e)'s host-path/email are
scrubbed; `SOURCES.md` records the archived commit.

## Wave 4 — `distro.py` host-path detector + manifest + clean-scan over the REAL vendor output
**Goal:** `build_distro` over the actually-vendored tree is CLEAN, and leaking host paths now FAIL.
**Changes:** add a **build-host-path** PII detector to `distro.py` (`C:\…\dev\…`, `/Users/<u>/`, `/home/<u>/`
— today's `_USERPATH_RE` only catches `X:\Users\<acct>\`, verified); `dist_manifest.txt` allow-lists
`vendor/bundled-skills/**`, `onboard.py`, `vendor_skills.py`, the `/onboard` skill, the starter templates.
(NOTE: `_is_vendored` already matches the `vendor/` prefix — `vendor/bundled-skills/` is ALREADY treated as
vendored; do NOT re-add that.)
**Done-when (real artifact, not a fixture):** Given `vendor_skills.vendor_all` run into a temp tree (Wave 3),
When `build_distro` stages + scans it, Then it returns CLEAN (no `PersonalDataError`, no `third-party-import`,
no high-entropy false-fail on a vendored git SHA); AND a seeded `C:\dev\secret\x` in a NON-vendored staged
file raises `PersonalDataError` (the new detector fires).

## Wave 5 — starter Anchor templates (no data)
**Goal:** headers-only Anchor markdown to start fresh from.
**Changes:** `starter/` templates for the 7 markdown files + `domains/*` (headers only, zero entries);
manifest-allow-listed. + `tests/test_starter_templates.py`.
**Done-when:** Given each starter file, When parsed by the existing markdown parsers, Then it parses AND
yields ZERO task/project/inbox entries; AND a no-PII scan over `starter/` is clean.

## Wave 6 — `onboard.py` core: skills-install + scaffold + token (hermetic; no service)
**Goal:** the safe, idempotent, rollback-able installer core.
**Changes:** `onboard.py` (stdlib): detect OS+prereqs (report, never hard-fail optional); install the 4
vendored skills to `ANCHOR_SKILLS_HOME` (default `~/.claude/skills`) by COPY (symlink opt-in),
refuse-don't-clobber a differently-sourced target; scaffold starter Anchor into the data dir only-if-absent;
generate a random `ANCHOR_TOKEN` to an out-of-tree/`.gitignore`'d file. Resumable.
**Done-when (temp `ANCHOR_SKILLS_HOME` + temp data dir; never real home):** Given a fresh run, Then 4 skills
installed + starter scaffolded + a token file written OUTSIDE the repo; Given a re-run, Then no-op
(idempotent); Given an existing differently-sourced `<skills_home>/foreman`, Then it is refused-not-clobbered;
Given an injected mid-install failure (skill 3 of 4), Then no partial skill remains AND a resume completes all
4; AND `build_distro` over the repo stays CLEAN after onboard (the token never lands in a staged file).

## Wave 7 — service seam + foreground fallback + rollback (stubbed)
**Goal:** the tractable, fully-stubbable core of service bring-up (the fallback alone satisfies the North Star).
**Changes:** an `ANCHOR_SERVICE_CMD` seam; a foreground/background launcher behind an `ANCHOR_FOREGROUND_CMD`
seam; rollback on a half-failed registration; `onboard.py` calls register→(fallback)→record.
**Done-when (both seams stubbed; NO real server/service):** Given the service stub, When onboard registers,
Then the stub records the intended argv + token-env; Given a forced registrar failure, Then onboard
constructs the correct foreground launch argv + env via `ANCHOR_FOREGROUND_CMD` with a port chosen by
`pick_free_port` asserted `≠ 8777` (NO real bind); Given an injected mid-registration failure, Then rollback
leaves no partial service record.

## Wave 8 — per-OS service registrars (unit-file generators)
**Goal:** correct NSSM / launchd / systemd-user unit generation, platform-honest.
**Changes:** the three registrars producing their unit text/argv; restrictive mode (POSIX `chmod 600`;
Windows → request a restrictive ACL recorded via the seam).
**Done-when:** Given each OS forced via the platform seam, When the registrar builds its unit, Then the unit
TEXT/argv matches the expected per-OS shape (string assertion) and carries the token env; Given POSIX, Then
the written unit file's `stat().st_mode & 0o077 == 0`; Given Windows, Then the stub recorded the intended
restrictive ACL (the chmod assertion is POSIX-only — documented).

## Wave 9 — `publish_distro`: build→gate→push pipeline
**Goal:** the clean repo ships to a private GitHub repo, gated on a clean scan (interface owned HERE, not split).
**Changes:** NEW `publish_distro(dest, remote_cmd=ANCHOR_GH_CMD)` SEPARATE from `build_distro`: build →
**clean-scan GATE** (abort before any git/push on a non-clean scan) → `git init` + initial commit →
`gh repo create --private` (via the seam) → push; the documented no-`gh` manual path.
**Done-when (`ANCHOR_GH_CMD` → `tests/stub_gh.py` + a LOCAL BARE `file://` remote; NO network):** Given a
staged tree with an injected PII hit, When `publish_distro`, Then it aborts AND the gh/push stub records ZERO
calls (gate proven); Given a clean staged tree, Then it `git init`s + pushes to the LOCAL BARE remote AND the
stub recorded the `repo create --private`; Given `gh` absent, Then the manual-path message + no crash.

## Wave 10 — `/onboard` repo-local skill + export assertion (+ discovery spike)
**Goal:** `/onboard` is the entry on a fresh clone (with `python onboard.py` as the guaranteed fallback).
**Changes:** a repo-local `/onboard` `SKILL.md` at the Claude-Code skill-discovery path (e.g.
`.claude/skills/onboard/`) that runs `python onboard.py`; manifest-allow-listed.
**Done-when:** Given `build_distro`/`publish_distro`'s export, Then the `/onboard` `SKILL.md` is present at the
repo-local discovery path AND in the exported tree AND names `python onboard.py`. **MANUAL spike (not a pytest
gate, like the live-smoke):** a fresh clone + open in Claude Code shows `/onboard` discoverable; if NOT,
`python onboard.py` is documented as THE entry (the README already guarantees it).

## Wave 11 — cross-platform finalize: Windows-ism audit (LATE) + scheduler scoping
**Goal:** after all shipped surface exists, nothing leaks Windows/host strings; the healthcheck scheduler is
honestly scoped per-OS.
**Changes:** genericize `nssm`/`gwl-server`/`C:\dev`/`C:\Users\john` in ALL shipped UI/comments/README/skill
(run over the FINAL surface, incl. W7/W8's service strings); the daily-healthcheck scheduling is cross-platform
(cron/launchd-timer) OR explicitly documented Windows-Task-Scheduler-only.
**Done-when:** Given a grep over the EXPORTED tree, Then ZERO `nssm`/`gwl-server`/`C:\\dev`/`C:\\Users\\john`
in shipped strings; AND a content assertion that the README/onboard states the healthcheck-scheduler scope
honestly (cross-platform or documented-Windows-only).

## Wave 12 — `check_onboard_surface` healthcheck + CLI mirror + docs (PROJECT DONE)
**Goal:** a hermetic regression walk + falsifiable docs.
**Changes:** `anchor_healthcheck.check_onboard_surface` (fully stubbed; **snapshots+restores HOME +
`ANCHOR_SKILLS_HOME`/`ANCHOR_SERVICE_CMD`/`ANCHOR_FOREGROUND_CMD`/`ANCHOR_GH_CMD`/`ANCHOR_TRIO_DIR`/
`ANCHOR_GANDALF_DIR` in `finally`**; never `:8777`) walking vendor→build_distro-clean→onboard→service-stub/
fallback→publish-to-bare→export-clean; invoked by a `tests/test_*` collection item (on-demand; NOT added to
the daily 5 AM `main()` run — a one-shot installer doesn't need daily). `anchor.py` read-only mirror
(`distro vendor-status` / `distro check`). README (clone → `/onboard` or `python onboard.py`) + CLAUDE.md
"Shareable distro" section; `distro.py` import scan stays clean.
**Done-when:** `pytest -q` green ≥ baseline incl. the `check_onboard_surface` test; a test PARSES the README
and asserts each referenced command (`python onboard.py`, `/onboard`) maps to a real file/entrypoint in the
export AND the 4 skill names are listed; the env-equality post-walk check passes (no leaked HOME/seams).
