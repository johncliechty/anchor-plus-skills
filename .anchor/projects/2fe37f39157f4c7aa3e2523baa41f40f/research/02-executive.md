# Anchor — Executive Summary (Brownfield Orientation)

**`C:\dev\Anchor` · 2026-06-11 · researchPrime**
**Honesty stamp:** DEGRADED prose mode — *schema conforms; adversarial verification did NOT run (Node engine approval-gated).* Adversarial value came from 5 context-isolated sub-agents instead. `cross_model: false`. Full report: `01-report.md`; evidence: `evidence-ledger.jsonl`.

## What it is
**Two products in one folder.** (1) A mature, stdlib-only **markdown productivity system** — task/project/inbox files served by `anchor_gui.py` (~5,400 lines) running as a persistent **Windows NSSM service `anchor` on localhost:8777**, writing markdown directly (no DB). (2) A newer **R&D control surface** that registers code projects and runs the **researchPrime → Crucible → Foreman** trio as durable `claude` jobs, tracking each run as a session with cached summaries, an interactive (xterm.js) terminal, and a Kanban window. Nearly all recent effort is on (2).

## Current state — DONE
The **R&D-surface v2** build is **finished and merged to `master`**: 8 Foreman waves GREEN, "PROJECT DONE" 2026-06-11, ~394 tests passing (per the build log), real xterm.js swapped in. Daily healthcheck is OK and has been clean ~8 days. Two artifacts falsely *look* unfinished — `foreman-checkpoint.json` (says "wave 1 / running") and an EXECUTION-LOG line ("not merged to master") — **both are verified STALE; the work is done and on master.** `master` is 20 commits ahead of origin (unpushed).

## Done vs. outstanding (top items)
**Done:** core app + healthcheck; R&D v1 (9 waves); brownfield discovery (7 waves); R&D v2 (8 waves, merged); effort_history now wired into the live GUI (closing the prior research's #1 gap); shipped product genuinely stdlib-only.
**Outstanding, by priority:** (1) confirm the live service was *restarted* onto the new code, then `git push`; (2) run folder **reconcile** (3 Anchor ids on one folder; sessions stranded on retired ids); (3) decide durability for untracked-and-unignored R&D state (`rnd_registry.json`, `.anchor/` pointer-records, `Anchor.md`) before a checkout loses it; (4) clean 16 retired temp test-projects + stale/orphaned job records; (5) **Gemini plan/build adapter** (deferred; scoping doc ready); (6) Phase-F deferrals + hygiene (`domains/test.md`, stale `requirements.txt`, regenerated HTML churn).

## Top 3 risks/unknowns
1. **Is the live process actually on the new code? — UNVERIFIED.** Disk is merged; whether the NSSM service was restarted to load it is not derivable from files and could not be checked (PowerShell approval-gated). Verify first; `nssm restart anchor` (elevated) if unsure.
2. **No live trio run ever proven — integration risk.** Every Crucible/Foreman/researchPrime gate/liveness path is tested only against a stubbed runner (`tests/fake_claude.py`); real-engine go/no-go under load/timeout is unobserved. Consistent across this and the prior research run.
3. **R&D-memory durability gap.** Registry + `.anchor/` pointer-records are untracked **and not gitignored**, plus 20 unpushed commits — a loss/checkout event drops all R&D history.

## Don't-break-it note
Persistent service, markdown is source-of-truth, no undo. Never blanket-kill `pythonw`; restart via `nssm restart anchor` only. Cross-check the docs against the tree — several doc statements are stale relative to the merged code.
