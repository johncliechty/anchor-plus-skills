# North Star — Tidy-Idy GUI + full-vision engine  (LOCKED 2026-07-20)

## Statement
A project's **Tidy-Idy button in Anchor launches a background hygiene pass and opens a
project-tied Triage Panel** that presents everything the pass found — **files to remove,
files to save/commit, and folder reorganizations** — as clear, human-approvable decisions,
and applies **only what the human approves, as one git commit per Apply (undo = `git revert`)**,
never losing work git holds and never acting without approval. The tidy-idy engine is
**extended, not forked** to add save-detection and reorg proposals and to run on ordinary
(non-Foundry, possibly non-git) folders, while preserving its removal pipeline and every safety invariant.

## Success criteria (each gate-able)
1. **One-click background run, project-scoped.** Clicking Tidy-Idy on project P starts a headless
   run over P's folder (like Gandalf), shows a live "running" state, and on completion opens a
   Triage Panel whose header unmistakably identifies P (name + path + git status + run #). A run
   over P never reads/writes another project.
2. **Three finding classes, from real analysis.** The panel shows (a) **removals**, each carrying
   the engine's real **Attacker + Judge** verdict; (b) **save/commit** candidates (untracked +
   uncommitted-modified files that should be preserved); (c) **reorg** proposals rendered as
   **before→after trees**. A failed analysis is shown LOUDLY ("the analysis did not run") — never
   an empty, clean-looking panel.
3. **Nothing applied without approval.** No file is deleted, committed, or moved until the human
   approves it (per-item or per-set) and presses **Apply**. Apply lands all approved changes as
   **one git commit** with a clear message; undo = `git revert <commit>`. Protected classes
   (SKILL/README/tests/`bin/`/`journal/`/North-Star…) are never offered for removal.
4. **Runs on ordinary folders, honestly.** On a non-Foundry folder (no North-Star file) the run
   still yields useful removal/save/reorg findings (age / duplicate / orphan / untracked heuristics
   stand in for North-Star alignment, clearly labelled as such). On a **non-git** folder it does
   NOT silently act — it either offers `git init` (so the undo guarantee holds) or marks the run
   **advisory / read-only** with actions disabled and says why. A **dirty** tree is handled, not
   refused outright.
5. **Extend-don't-fork + green.** Reuses tidy-idy's `scanner/hygiene/analyze/debate/remove/compress`
   modules and adds new ones (save-detect, reorg, a report emitter) + Anchor's `job_runner`/Gandalf
   run path + a Zombie-Sentinel-style GUI serving; the tidy-idy suite and new tests are green;
   stdlib / existing substrate first.

6. **Investigator terminal tile (like Zombie Hunter).** The Triage Panel includes an
   "Investigate with an agent" tile that opens a seeded terminal (Claude / Gemini / Grok),
   loaded with the **tidy-idy skill AND a briefing of the CURRENT report** (its findings), so the
   human can interrogate/act on the results conversationally — tied to the same launching project.
7. **Report archive / history.** Every run's report is persisted per project, newest-first (the
   Gandalf run-index pattern); previous tidy-idy reports are KEPT as browsable **references** from
   the panel and never overwritten, so a project accrues a hygiene history.

## Non-goals (explicitly out)
- No hard-delete / archive-TTL subsystem — **git is the only archive** (unchanged).
- No auto-apply and no scheduled unattended mutation from the GUI — human-in-the-loop only.
- No AI rewriting of file CONTENTS; tidy-idy organizes/removes, it does not edit documents
  (the existing `agent.md` compression is the one preserved exception).
- Not a general file manager — only the three finding classes + Apply.
- No cross-project / whole-computer scan (that is Zombie Hunter's lane) — Tidy-Idy is per-project.

## Risk taxonomy (safety-critical — this tool touches real files)
- **R1 Data loss on removal/move.** Every mutation is git-committed; removal only on Attacker+Judge
  REMOVE with exact-path match; moves are `git mv` (history-preserving); non-git ⇒ no mutation. Undo = revert.
- **R2 Wrong-file action (path/basename bug).** Exact-path matching end-to-end (the prior basename bug
  is a known failure mode); GUI shows full path per item; Apply re-validates paths before acting.
- **R3 Silent no-op / fake-clean report.** Loud failure surfaced in the GUI; the report distinguishes
  "ran, found nothing" from "did not run."
- **R4 Approval bypass.** The report is inert; the Apply endpoint refuses any item not explicitly
  approved; token-gated like other Anchor mutating routes.
- **R5 Reorg breakage.** Moves preserve git history (`git mv`); the before→after preview is exact;
  a reorg set is all-or-nothing and reversible.
- **R6 Cross-project bleed / wrong-project GUI.** Project id threaded through run → report → GUI; the
  panel is stamped with the launching project; a run is scoped to one folder.
- **R7 Non-git / dirty ambiguity.** Explicit states — git-clean (full actions) / dirty (save-detection
  foregrounded, removal gated) / non-git (advisory or offer `git init`).

## Foresight brief (2–3 steps ahead)
- **F1 Serving the GUI.** Two proven Anchor patterns: node-server-proxied (Zombie Sentinel) vs an
  Anchor-native panel reading a persisted per-run JSON (Gandalf's report-viewer pattern). The report is
  per-run + project-scoped, so the native panel is likely cleaner than a standing node process — Stage 1
  decides, but the standing-process cost is flagged.
- **F2 The report contract is the spine.** Engine ↔ GUI couple ONLY through a versioned JSON report
  (removals+verdicts · save-candidates · reorg move-set · kept/protected · run+project identity · status).
  Design it once, well.
- **F3 Reorg needs a human-legible rationale** per move (by-year-from-filename-date / by-type / dedupe),
  or approvals stall and the before→after tree isn't trustworthy.
- **F4 Non-Foundry heuristics vs North-Star analysis diverge.** Keep age/duplicate/orphan/untracked
  signals clearly labelled vs North-Star misalignment so the human knows the basis for each call.
- **F5 Usage cost.** Analysis/debate calls (Gemini via trio driver) scale with file count; batch + cap as
  tidy-idy already does, and surface a large-folder run's cost/scope BEFORE it runs.

---
*Design prototypes reviewed & chosen by John (2026-07-20): Triage Panel (Mockup A) + reorg Option 1
(before→after trees). Canonical CURRENT mockups:
`<path> (A + A2 Option 1 only; B/C and Option 2 REJECTED).*


## AMENDMENT (2026-07-20, approved by John)
Undo clause: `undo = git revert` → **undo = `git revert` for git-held content; restore-from-Trash (`.tidy-idy/trash/<run>/`, gitignored) for content git does not hold (untracked / non-git) — always fully reversible, never a destructive delete.**

## AMENDMENT 2 — Standalone tool + thin Anchor caller (2026-07-21, approved by John)
**Ownership inversion.** Tidy-Idy is a **standalone hygiene tool that owns its own Triage Panel GUI and its own launch**. Its **single canonical run-and-open-panel entry point** — `tidy-idy <folder>`, invocable from a **CLI or cowork** — runs the background hygiene pass on **any folder** (an Anchor project root OR a plain folder outside Anchor) and opens the project-tied Triage Panel. **Anchor's Tidy-Idy button is ONE thin caller** of that same entry point: it dispatches the run (via `job_runner`, for headless-in-Anchor + live state) and opens the tool's panel — it adds **no second launch / panel / archive code path**. Everything else in the Statement and all seven criteria are unchanged; this amendment only re-homes *who owns the launch*.

- **Statement clause** "A project's Tidy-Idy button in Anchor launches …" is superseded by: "The tidy-idy tool's launch entry point (CLI/cowork, on any folder) — or Anchor's Tidy-Idy button as a thin caller of it — launches a background hygiene pass and opens a project-tied Triage Panel …".
- **Criterion 1** ("One-click background run, project-scoped") now requires the run+panel to be reachable **two ways from one code path**: (a) the tool's own CLI/cowork launch on any folder inside or outside Anchor, and (b) Anchor's button as a thin caller — identical envelope, archive, project-scoping, and live "running" state either way.
- **Criterion 5** ("Extend-don't-fork + green"): the **panel server, launch, run-archive, cost-gate, and lock are owned by the tool**; Anchor's `job_runner` is used by the button caller only (for headless dispatch + resource-claim queuing) and a standalone run's correctness never depends on it.
- **F1 (serving the GUI)** is resolved toward the **tool-owned standing panel server** (the Zombie-Sentinel pattern), because the same server must serve a run launched with no Anchor process present.

**Amendment-2 refinements (cross-family Shark pass, 2026-07-21 — folded into Wave 5/6/7):**
- **"Zero Anchor dependency" is scoped to CORRECTNESS, not isolation.** A standalone run on a non-Anchor folder needs nothing from Anchor. But **cross-agent mutual exclusion is preserved, not dropped**: the tool's per-project lockfile is the single cross-agent source of truth, and Anchor's `job_runner` + the **Foreman/Gandalf launchers consult it** before mutating a root (closing the R1 concurrency-blindness hole where a CLI tidy run could be invisible to a concurrent build). A CLI run inside an Anchor workspace also registers the resource claim best-effort.
- **No zombie server / no permanent lock (ties to Zombie Hunter's concern):** the standalone panel server self-terminates + releases its **stale-PID-aware** lock on explicit close, idle timeout, or a heartbeat gap — closing the browser tab never strands a process or a locked folder.
- **CLI token bootstrap is specified, not assumed:** the single-use **nonce** may transit a loopback URL / 0600 temp file (redeemed + invalidated on first GET); the capability **token** still never touches disk/URL/log — invariant 5 holds identically on both launch paths.
- **"Identical panel" = identical envelope + rendering + Apply semantics;** the investigator terminal + browser-open are one launch-spec with an environment-appropriate opener (Criterion 6 preserved on both paths).
