# Intent — Tidy-Idy GUI + full-vision engine (Anchor-integrated)

**Date locked:** 2026-07-20 · **Requested by:** John · **Planning skill:** Crucible → Foreman

## One-line intent (North-Star candidate)
Make a project's **Tidy-Idy** button (in the Anchor project window) run a **background hygiene pass** (like Gandalf runs) and open a **project-tied Triage Panel GUI** that shows what was found and the decisions needing human input — **files to remove, files to save/commit, and folder reorganization** — with **git as the safety net** (every applied change is one git commit; undo = `git revert`), and nothing applied without explicit human approval.

## What Tidy-Idy does TODAY (per its SKILL.md — the baseline to extend, not replace)
- **Git pre-flight** — refuses non-git dirs (git is its only undo); prompts on a dirty tree.
- **North-Star alignment analysis** — judges each file against the project's North-Star file (batched, Gemini via trio driver). A failed analysis is LOUD ("analysis did NOT run"), never a clean-looking empty report.
- **Adversarial review** — per ≤10-file chunk: one Attacker (case for removal) + one Judge (RETAIN | REMOVE, exact-path only). RETAIN is the fail-safe.
- **Removal = delete + git commit** (git IS the archive). Protected classes never removed: SKILL/NORTH-STAR/INTENT/LESSONS/CHANGELOG/README, `journal/`, tests, `bin/`. >10 removals needs interactive human OK.
- **Context compression** of `agent.md`. State in `<targetDir>/.tidy-idy/` (gitignored); each run writes a `journal/runs/` record.

## FULL-VISION scope (what this effort ADDS) — the three gaps
1. **Save / commit detection (NEW):** find **untracked** and **uncommitted-modified** files that should be preserved, and propose "Add & commit" / "Add to .gitignore" / "Leave". Today tidy-idy refuses dirty trees rather than helping save.
2. **Reorganization proposals (NEW):** propose folder moves (e.g. group loose files into `documents/<year>/`), applied as **git-committed renames**. GUI graphic = **Option 1: before→after trees** (flat cluttered root visibly becomes an organized tree; moved files highlighted). Human approves the whole set.
3. **Non-Foundry / non-git / dirty projects (NEW):** handle a plain docs folder (e.g. "Family Trusts") with **no North-Star file**, and a non-git or dirty tree, **gracefully** — degrade honestly or offer `git init` for the GUI use case, rather than a hard refusal. (Removals still require git as the undo; be explicit about what's safe.)

## GUI — the Triage Panel (chosen; CURRENT mockups under polish design/)
- **Zombie-Hunter–style panel** (Anchor dark tokens). Header **clearly ties the panel to the launching project** (name chip + path + git status + run #), so a popped-up GUI is unmistakably *this project's* run.
- **Verdict pills:** Proposed removals · Not-saved/not-in-git · Reorg proposals · Kept/protected.
- **Findings grouped by ACTION:**
  - 🗑 Removals — each shows file + why + tidy-idy's **Attacker + Judge** verdict; Approve / Keep.
  - 💾 Not saved / not in git — Add & commit / .gitignore / Leave.
  - 📁 Reorg — **before→after tree** graphic (Option 1); Approve set / Edit / Skip.
  - 🛡 Kept & protected (collapsed).
- **Sticky Apply** → all approved changes land as **ONE git commit** (undo = `git revert`). Nothing happens until Apply.
- Reference mockups (CURRENT only): `<path> `…\tidy-idy-mockup-A2-reorg.html` (Option 1 only; B/C and A2 Option 2 REJECTED).

## Run model + Anchor integration
- **Background run like Gandalf** (the project-window header Tidy-Idy button → `tidyIdyRun`) — headless job via Anchor's `job_runner` / the Gandalf map-reduce pattern; writes a persisted report the GUI reads.
- **GUI panel opens tied to the launching project** (project id/name/path threaded through). Serve it in the Anchor style — either an Anchor-native panel or the proxied-node pattern used by the Zombie-Hunter Sentinel; Crucible to choose the cleaner fit.
- Reuse: tidy-idy `bin/tidy.mjs` engine, the trio driver, Anchor `job_runner`/gandalf wiring, Anchor `/vendor/brand/tidy-idy-icon.jpg`.

## Hard constraints / invariants
- **git is the archive** — nothing hard-deletes; every applied change is a git commit; undo = `git revert`.
- **Observe-first / human-in-the-loop** — no removal, save, or move is applied without explicit per-item (or per-set) approval in the GUI, then a single Apply.
- **Honesty** — a failed analysis is loud; never a clean-looking empty report; protected classes never touched.
- **Anchor style** — dark tokens; the GUI reads as part of Anchor.
- Stdlib/existing-substrate first; reuse tidy-idy + Anchor patterns rather than new frameworks.

## Deliverables the plan must cover
1. tidy-idy engine extensions (save-detection, reorg-proposals, non-Foundry/non-git handling) with the loud-failure + protected-class + git-commit invariants preserved.
2. A structured **report contract** (JSON) the GUI renders — removals (+ adversarial verdicts), save candidates, reorg proposals (before→after move set), kept/protected.
3. The **Triage Panel GUI** (Anchor-styled, project-tied) reading that report + the Apply flow (one git commit).
4. Anchor **wiring**: the header Tidy-Idy button → background run → GUI panel, tied to the project.
5. Tests + the honesty/safety gates.
