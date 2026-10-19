# Shareable Anchor Distro + `/onboard` — MASTER PLAN (FROZEN, Shark-converged)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-23

**What was asked:** Shareable Anchor Distro + `/onboard` — MASTER PLAN (FROZEN, Shark-converged)

**North Star:** Produce a clean, shareable Anchor git repo — **zero personal data** — with the **trio (researchPrime, Crucible, Foreman) + Gandalf** skills vendored in, that a collaborator clones and brings up on their own machine (**Windows / macOS / Linux**) with one **`/onboard`** command: installs the skills, scaffolds a fresh empty Anchor, sets their **own** token, registers the background service, and starts the dashboard. Reuse `distro.py`'s deny-by-default builder; **never ship the author's data, history, or host paths.**

## Actions & files produced

- Shareable Anchor Distro + `/onboard` — MASTER PLAN (FROZEN, Shark-converged)

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star (LOCKED — John, 2026-06-23)**
- Goal is a clean, shareable Anchor git repo containing **zero personal data**, with the trio (researchPrime, Crucible, Foreman) **plus Gandalf** skills vendored in.
- A collaborator clones the repo and brings it up on their own machine — **Windows, macOS, or Linux** — via a single **`/onboard`** command.
- `/onboard` must: install the skills, scaffold a fresh empty Anchor, set the collaborator's **own** token, register the background service, and start the dashboard.
- Hard constraint: reuse `distro.py`'s deny-by-default builder and **never ship the author's data, history, or host paths.**
- **Locked decision 1 — Clean repo via `distro.py`** (resolves Shark BLOCKERs S1-1/2/3, S3-1/3)
- Keep `distro.py`'s three guards: deny-by-default file selection, the no-PII/secrets scan, and the stdlib-only import scan.
- Extend it to treat `vendor/bundled-skills/**` as **vendored** — i.e. skip the import scan and high-entropy scan there, consistent with the existing `vendor/` exemption.
- Add a **build-host-path detector** to the PII scan for patterns like `C:\dev\…`, `/Users/<u>/`, `/home/<u>/`.
- **Locked decision 2 — Skills vendored via `git archive`**
- Skills land under `vendor/bundled-skills/{researchPrime,crucible,foreman,gandalf}/`.
- They are produced with **`git archive <commit>`**, **not** a working-tree copy.
- Summary of the planning session — **Shareable Anchor Distro + `/onboard`** (Crucible MASTER PLAN, frozen 2026-06-23, branch `share-distro`):
- ## Objective (North Star, LOCKED by John 2026-06-23)
- Produce a clean, shareable Anchor git repo with **zero personal data**, vendoring the **trio (researchPrime, Crucible, Foreman) + Gandalf** skills, that a collaborator clones and brings up on **Windows / macOS / Linux** with one **`/onboard`** command.
- `/onboard` installs the skills, scaffolds a fresh empty Anchor, sets the collaborator's **own** token, registers the background service, and starts the dashboard.
- Reuse `distro.py`'s deny-by-default builder; never ship the author's data, history, or host paths.
- Scope is **FULL v1**: cross-platform core + cross-platform live terminals + per-OS auto-service + vendored skills + `/onboard` + private GitHub.
- Converged through a **Shark-Tank R1** (3 sharks) that surfaced **4 verified BLOCKERs + many MAJORs**, all folded into the plan as concrete waves.
- ## Locked decisions (10)
- **Clean repo via `distro.py`**, extended to (a) treat `vendor/bundled-skills/**` as vendored (skip import + high-entropy scans), and (b) add a **build-host-path detector** (`C:\dev\…`, `/Users/<u>/`, `/home/<u>/`) — fixing **157 leaking host paths** the current scan misses.
- **Skills vendored via `git archive <commit>`** (not a working-tree copy) under `vendor/bundled-skills/{researchPrime,crucible,foreman,gandalf}/`; auto-excludes `.git/`, gitignored files, and dirty state. `SOURCES.md` stamps the archived commit; a residual-scrub pass genericizes remaining host paths / test PII.
- **`/onboard` = a repo-local Claude Code skill** (discoverable on clone, no prior install) that invokes installer `onboard.py`; README documents `python onboard.py` as the guaranteed bring-up (fixes the chicken-and-egg).
- **Cross-platform terminals via the existing `pty_manager` backend seam**: keep `pywinpty` on Windows, add a **stdlib `pty`-module POSIX backend** (no new dependency); `ANCHOR_PTY_BACKEND` auto-selects by OS.
- **Per-OS service registration** via a NEW injectable **`ANCHOR_SERVICE_CMD` seam**: NSSM (Windows) · launchd user-agent (macOS) · systemd-user (Linux), with a **foreground/`nohup` fallback** when registration isn't possible.
- **POSIX single-instance guard** (pidfile/`EADDRINUSE`-exit) since Windows' `SO_EXCLUSIVEADDRUSE` has no POSIX equivalent.
- **Token**: `onboard.py` generates a random `ANCHOR_TOKEN` per machine, stored **outside the repo tree** (or gitignored + manifest-excluded); service units `chmod 600`; never printed/committed.
- **Skill install = COPY by default** (symlink opt-in); **refuse-don't-clobber** when a target skill already points elsewhere (protects the author's live dev symlinks).
- **Ship to a NEW PRIVATE GitHub repo** via `ANCHOR_GH_CMD` → `gh repo create --private`; push gated on a **clean `build_distro` scan**; manual no-`gh` path documented.
- **Windows-ism audit**: shipped UI/comments must not hardcode `nssm`/`gwl-server`/author host; healthcheck + scheduling honestly scoped per-OS.
- ## Architecture (new/extended components)
- **`vendor_skills.py` (NEW, stdlib)** — `git archive` each source skill → `vendor/bundled-skills/`, strips `.git/`, writes `SOURCES.md`, runs the residual scrub.
- **`onboard.py` (NEW, stdlib, cross-platform, idempotent, resumable, never-destructive)** — detect OS + prereqs → install 4 skills (copy) → scaffold starter Anchor → generate/store token → register service (foreground fallback) → health-check `:8777` + print URL; rollback on half-failed service step.
- **Starter templates** — empty headers-only `DASHBOARD.md`/`INBOX.md`/`PROJECTS.md`/`domains/*`/etc.; scaffolded only-if-absent.
- **`distro.py` / `dist_manifest.txt`** extended with the vendored-skill classification, host-path detector, allow-list, and a clean-scan gate before any push.
- **Tests** — `check_onboard_surface`, fully hermetic (temp HOME/skills-dir, stubbed `ANCHOR_SERVICE_CMD` + `gh`, `port=0`, never `:8777`/real home/network).
- ## Risks → mitigations (7)
- **R1** PII/host-path leak → `git archive` + host-path detector + residual scrub + clean-scan build GATE.
- **R2** per-OS service/elevation → seam + foreground fallback (fallback alone satisfies bring-up).
- **R3** onboard destroys existing setup → copy-default + refuse-don't-clobber + resumable + rollback.
- **R4** POSIX duplicate-server → pidfile/EADDRINUSE guard (Wave 1).
- **R5** token leak → out-of-tree/gitignored token + chmod 600 + post-onboard clean-scan test.
- **R6** cross-platform terminals → stdlib `pty` backend, Windows unchanged.
- **R7** vendoring drift → `SOURCES.md` archived-commit stamp; re-vendor = clean `git archive`.
- Upstream skill auto-sync, GUI installer, multi-user/hosted Anchor, migrating an existing user's data (share repo is for FRESH installs), alternate-engine keys.

## Files

- [Shareable Anchor Distro + `/onboard` — MASTER PLAN (FROZEN, Shark-converged)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-distro-v1%2FMASTER-PLAN.md)
