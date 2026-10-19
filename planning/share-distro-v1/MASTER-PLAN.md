# Shareable Anchor Distro + `/onboard` — MASTER PLAN (FROZEN, Shark-converged)

> Crucible, 2026-06-23. Branch `share-distro` off Anchor master. Shark-Tank R1 (3 sharks, 4 verified
> BLOCKERs + many MAJORs) converged into this plan. Scope: **FULL v1** (John) — cross-platform core +
> cross-platform live terminals + per-OS auto-service + vendored skills + `/onboard` + private GitHub. Every
> Shark fix is folded in as a concrete wave (see IMPLEMENTATION-PLAN.md).

## North Star (LOCKED — John, 2026-06-23)
Produce a clean, shareable Anchor git repo — **zero personal data** — with the **trio (researchPrime,
Crucible, Foreman) + Gandalf** skills vendored in, that a collaborator clones and brings up on their own
machine (**Windows / macOS / Linux**) with one **`/onboard`** command: installs the skills, scaffolds a fresh
empty Anchor, sets their **own** token, registers the background service, and starts the dashboard. Reuse
`distro.py`'s deny-by-default builder; **never ship the author's data, history, or host paths.**

## Locked decisions (post-Shark)
1. **Clean repo via `distro.py`** (deny-by-default + no-PII/secrets scan + stdlib-import scan), EXTENDED to
   (a) treat `vendor/bundled-skills/**` as **vendored** (skip the import + high-entropy scans like `vendor/`),
   and (b) add a **build-host-path** detector (`C:\dev\…`, `/Users/<u>/`, `/home/<u>/`) to the PII scan
   (fixes the 157 leaking host paths the scan misses today). [BLOCKERs S1-1/2/3, S3-1/3]
2. **Skills vendored under `vendor/bundled-skills/{researchPrime,crucible,foreman,gandalf}/` via
   `git archive <commit>`** — NOT a working-tree copy. `git archive` auto-excludes `.git/`, gitignored files
   (node_modules, `*-out/`, `runs/`, `.env`, `.foreman/`, `*-checkpoint.json`, the named personal logs
   `EXECUTION-LOG.md`/`DECISION-LOG.md`/`CLAUDE_hist.md`), and dirty working state. `SOURCES.md` stamps the
   **archived commit** (honest provenance). A residual-scrub pass genericizes any remaining host paths / test
   PII before staging. [BLOCKERs S3-2/S1-4, S3-10]
3. **`/onboard` = a REPO-LOCAL Claude Code skill** (shipped in the repo so it's discoverable on clone+open,
   no prior install) that invokes the installer `onboard.py`. The README documents `python onboard.py` as the
   guaranteed-works bring-up (installs the skills, after which `/onboard` + the trio/Gandalf are available).
   [fixes the S2-4 chicken-and-egg while honoring "`/onboard` is the entry"]
4. **Cross-platform terminals via the existing `pty_manager` backend seam**: keep `pywinpty` on Windows; add
   a **stdlib `pty`-module POSIX backend** for macOS/Linux (the stdlib `pty`/`os` modules — NO new dependency).
   `ANCHOR_PTY_BACKEND` already selects the backend; auto-select by OS. [resolves OPEN#1 stdlib-only]
5. **`/onboard` registers the background service per-OS** — NSSM (Windows) · launchd user-agent (macOS) ·
   systemd-user (Linux) — through a NEW injectable **`ANCHOR_SERVICE_CMD` seam** (stubbed in tests, like
   `ANCHOR_GH_CMD`), with a **foreground/`nohup` fallback** when registration isn't possible (no elevation /
   no service manager). Service env captures PATH (`claude`/`node`) + the token. [BLOCKER S1-6 made tractable]
6. **POSIX single-instance guard**: add a pidfile/`EADDRINUSE`-exit guard for non-Windows (the Windows
   `SO_EXCLUSIVEADDRUSE` guard has no POSIX equivalent today → the duplicate-server bug recurs). [S1-5]
7. **Token**: `onboard.py` GENERATES a random `ANCHOR_TOKEN` per machine, written to a file **outside the
   repo tree** (or repo `.gitignore`'d AND manifest-excluded by construction); service unit files written
   `chmod 600`. Never printed to a shared log, never committed; `build_distro` stays clean after onboard runs.
   [S3-4]
8. **Skill install = COPY by default** (deterministic, no privilege), **symlink opt-in**; refuse-don't-clobber
   when a target `~/.claude/skills/<name>` already points elsewhere (protects the AUTHOR's own live dev
   symlinks). [S1-7, S3-5]
9. **Ship to a NEW PRIVATE GitHub repo** via `ANCHOR_GH_CMD` → `gh repo create --private`; gate the push on a
   **clean `build_distro` scan**; spell out the no-`gh` manual path (`git init`/`remote add`/push). [S1-8, S3-8]
10. **Windows-ism audit**: the shipped UI/comments must not hardcode `nssm`/`gwl-server`/the author's host
    (generic strings); the daily healthcheck + scheduling are honestly scoped per-OS (cron/launchd-timer or
    documented-Windows-only). [S3-7, S1-9]

## Architecture
- **`distro.py` / `dist_manifest.txt`** — extend: classify `vendor/bundled-skills/**` as vendored; add the
  build-host-path PII detector; allow-list the vendored skills + `onboard.py` + the repo-local `/onboard`
  skill + starter templates; `build_distro` ends with a clean-scan gate before any push.
- **`vendor_skills.py` (NEW, stdlib)** — `git archive <commit>` each source skill → `vendor/bundled-skills/`,
  honoring `.gitignore`, stripping `.git/`, writing `SOURCES.md`, running the residual host-path/PII scrub.
- **Starter templates** — empty `DASHBOARD.md`/`INBOX.md`/`PROJECTS.md`/`domains/*`/`SAVED_FOR_LATER.md`/
  `CANCELLED.md`/`WEEKLY_REVIEW.md` (headers only). Onboard scaffolds only-if-absent (never clobbers).
- **`onboard.py` (NEW, stdlib, cross-platform, idempotent, resumable, never-destructive)** — detect OS +
  prereqs (Python≥3.8, node, `claude` CLI; optional `pywinpty` Windows) → install the 4 skills (copy default)
  → scaffold starter Anchor → generate+store the token → register the service via `ANCHOR_SERVICE_CMD`
  (foreground fallback) → health-check `:8777` + print the URL. Honest per-OS skip messaging; rollback on a
  half-failed service step.
- **`pty_manager.py`** — add the stdlib POSIX `pty` backend; OS-auto-select.
- **`/onboard` repo-local skill** — `SKILL.md` that runs `python onboard.py`.
- **Service seam** — `ANCHOR_SERVICE_CMD` (stub in tests) + per-OS registrars + the foreground fallback.
- **Tests / healthcheck** — `check_onboard_surface` (FULLY hermetic): temp `HOME`/skills-dir, stubbed
  `ANCHOR_SERVICE_CMD`, stubbed `gh` (`tests/stub_gh.py` + local bare remote), `port=0`, never `:8777` / real
  home / real service / network; restores all env.

## Risks (post-Shark, with mitigations)
- **R1 PII/host-path leak in vendored skills** → `git archive` + the new host-path detector + residual scrub +
  a clean-scan GATE on the build (Wave done-when: `build_distro` clean over the staged tree).
- **R2 per-OS service correctness/elevation** → the `ANCHOR_SERVICE_CMD` seam + foreground fallback +
  stubbed-hermetic tests; the fallback alone satisfies "bring it up," so a failed registrar never blocks.
- **R3 onboard destroys the author's/collaborator's setup** → copy-default + refuse-don't-clobber + resumable
  + rollback; never overwrite existing data/skills.
- **R4 POSIX duplicate-server** → the pidfile/EADDRINUSE guard (Wave 1).
- **R5 token leak** → out-of-tree/`.gitignore`'d token + `chmod 600` units + a test that build stays clean
  after onboard.
- **R6 cross-platform terminals** → stdlib `pty` POSIX backend (no new dep); Windows unchanged.
- **R7 vendoring drift** → `SOURCES.md` archived-commit stamp; re-vendor is a clean `git archive`.

## Out of scope (v1)
Auto-syncing vendored skills with upstream; a GUI installer; multi-user/hosted Anchor; migrating an existing
user's data (the share repo is for FRESH installs); alternate-engine (Gemini/OpenAI) keys (`.env.example`
excluded or documented-optional).
