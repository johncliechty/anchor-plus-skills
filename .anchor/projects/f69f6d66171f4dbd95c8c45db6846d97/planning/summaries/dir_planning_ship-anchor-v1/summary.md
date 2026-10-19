# Ship Anchor v1 (full foundry suite + cross-platform onboard + Tailscale) — MASTER PLAN (FROZEN)

*Lane: planning · validated, cached summary*

**When run:** 2026-07-01

**What was asked:** Ship Anchor v1 (full foundry suite + cross-platform onboard + Tailscale) — MASTER PLAN (FROZEN)

**North Star:** A collaborator receives the Anchor repo as a **zip/tarball**, runs **one onboard** to get Anchor plus the **full foundry skill suite** running locally on their machine (Windows / macOS / Linux), and optionally runs a **second onboard (onboard2)** to reach that service from another computer over **Tailscale** (as John reaches gwl-server). The shipped distro carries the **10-minute-summary discipline + locked "Status table" format** and lets the collaborator opt into **auto-run (with-permission)** and **low-verbosity** at onboard time. It ships **zero** of the author's personal data, secrets, or

## Actions & files produced

- Ship Anchor v1 (full foundry suite + cross-platform onboard + Tailscale) — MASTER PLAN (FROZEN)
- Ship Anchor v1 — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- **Objective (North Star, locked by John 2026-07-01):** a collaborator receives Anchor as a zip/tarball, runs one onboard to get Anchor plus the full foundry skill suite locally (Windows/macOS/Linux), and optionally runs a second onboard (onboard2) for Tailscale remote access — with zero of the author's personal data, secrets, or host paths shipped.
- **Delta, not a rewrite:** the plan extends the already-GREEN `share-distro-v1` machinery (distro.py's deny-by-default build + 4 scans, dist_manifest.txt, vendor_skills.py, onboard.py, the `/onboard` skill, enable_remote.ps1) — reuse is an explicit locked decision.
- **Skill roster locked at 12 vendored skills** (researchPrime, crucible, foreman, gandalf, jumper, expert-coder, agent-builder, figure-designer, zombie-hunter, legal-beagle, literature-review, ramanujan) plus the repo-local `/onboard`; financial-analyst and helping-hand are deferred to a fast-follow; tidy-idy is excluded.
- **Canonical gandalf identified** at `C:\dev\Skill Foundry\skills\gandalf\` — a self-contained, dependency-free Node engine that is bundleable; jumper needs no code surgery since its only gandalf dependency is a sibling relative import that resolves once both install side-by-side.
- **Vendoring becomes data-driven:** vendor_skills.py grows a roster map (skill → source dir → git-archive vs. clean-copy), covering whole-repo, subdir-of-repo, and non-git sources, with every source path an injectable test seam; node_modules are never shipped (onboard runs `npm install --omit=dev` best-effort for dep-bearing skills).
- **Collaborator preferences are opt-in only:** onboard prompts for auto-run (with-permission) and low-verbosity, writing Claude Code config only on opt-in; decline is a byte-for-byte no-op, idempotent and reversible.
- **The operating discipline ships as a distro-root `AGENTS.md`** carrying the 10-minute-summary rule, the exact locked "Status table" format, and the low-verbosity rule, with CLAUDE.md/GEMINI.md as thin pointers.
- **onboard2 formalizes Tailscale exposure cross-platform** (existing PowerShell service path on Windows + a new `tailscale serve` POSIX path) with a hard guard refusing exposure without a non-empty `ANCHOR_TOKEN` — closing the known same-box-proxy auth gap.
- **Delivery is zip/tarball only** for v1 (no GitHub push; `publish_distro` stays unused), ending in a clean-room onboard verification from the unpacked archive.
- **Implementation plan is Foreman-ready with 8 ordered waves** (vendor roster → jumper/gandalf sibling resolution → manifest/clean-scan → onboard install+prereqs → preference prompts → AGENTS.md → onboard2 → package+clean-room verify), gated by `python -m pytest -q` hold-or-grow, all waves hermetic and Windows-safe via faked-platform/injected seams (never `pytest.skip` as sole coverage, never binding :8777 or hitting the network).
- Planning session for **"Ship Anchor v1"** — a frozen Master Plan plus a Foreman-ready Implementation Plan (both member documents present), targeting shipping Anchor to collaborators.
- North Star (LOCKED by John, 2026-07-01): a collaborator receives the Anchor repo as a zip/tarball, runs **one onboard** to get Anchor plus the **full foundry skill suite** running locally on Windows/macOS/Linux, and optionally runs a **second onboard (onboard2)** for remote access over **Tailscale** (mirroring how John reaches gwl-server).
- The shipped distro carries the **10-minute-summary discipline and the locked "Status table" format**, and lets the collaborator opt into **auto-run (with-permission)** and **low-verbosity** at onboard time.
- Hard constraint: the distro ships **zero** of the author's personal data or secrets.
- Locked decision: **reuse the GREEN share-distro-v1 machinery** — `distro.py` (deny-by-default plus its 4 scans: personal-email, build-host-path, auth-token, stdlib-only-import), `dist_manifest.txt`, `vendor_skills.py`, `onboard.py`, the repo-local `/onboard` skill, and `enable_remote.ps1`. The plan **extends** these; it does not rewrite them.
- Locked decision: canonical Gandalf is `C:\dev\Skill Foundry\skills\gandalf\` — a self-contained Node engine (SKILL.md + `runtime/` including `runtime/seam-pass.mjs` + `seam/*.mjs`) with **no external npm deps**, actively developed (judgment-first tiering), and confirmed **bundleable**.
- Session outcome: Stage 1 Master Plan is **FROZEN** and a Stage 2 Implementation Plan exists, i.e. the plan is handoff-ready for a Foreman build.

## Files

- [Ship Anchor v1 (full foundry suite + cross-platform onboard + Tailscale) — MASTER PLAN (FROZEN)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fship-anchor-v1%2FMASTER-PLAN.md)
- [Ship Anchor v1 — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fship-anchor-v1%2FIMPLEMENTATION-PLAN.md)
