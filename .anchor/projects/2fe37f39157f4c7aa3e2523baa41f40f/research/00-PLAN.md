# Phase 1 — PLAN (researchPrime) — Anchor brownfield orientation

**Run mode:** DEGRADED prose mode for Phase-3 adversarial loop. Reason: `node` is present (v26.1.0) but arbitrary `node <script>` / `node -e` execution is **gated behind a tool-approval that cannot be granted in this non-interactive lane**. The engine import-probe (`contract.runImportSpike`) therefore could not be executed. Per protocol the deliverables carry the honesty stamp: *"schema conforms; adversarial verification did NOT run (Node engine)."* In its place, Phase-3 uses **real context-isolated sub-agents** (Explore / general-purpose) for reviewer → independent-reviewer → judge passes — genuine forget on a sub-agent host, stamped ISOLATION: real for those sub-tasks.

**ISOLATION (main thread):** approximated (single-context synthesis), with execution fanned out to real sub-agents.

## AXIS (load-bearing win-condition)
A brand-new owner, after reading the report, can (a) state correctly what Anchor *is*, (b) stand the system up and not break the running service, (c) name precisely what is DONE vs OUTSTANDING, and (d) know the top risks/unknowns to resolve before further work — **without** having to re-read the whole codebase.

**What FALSIFIES a candidate report:**
- It parrots CLAUDE.md / memory claims without checking them against the on-disk tree (brownfield = verify, don't trust the docs).
- It misstates current state (e.g. says rnd-v2 is "in progress" when commits say PROJECT DONE, or vice-versa) — i.e. fails the done-vs-outstanding axis.
- It would lead the new owner to a destructive action (e.g. blanket-killing pythonw, deleting retained R&D ids, mutating markdown source-of-truth) → blast-radius failure.
- It invents structure/modules not present, or misses load-bearing ones.

## Stakes VECTOR
- **Impact:** medium — orientation doc; wrong content wastes a new owner's time and could mislead.
- **Reversibility:** the *report* is fully reversible (it's a doc). But the **subject system runs as a live Windows service writing to markdown source-of-truth with no DB/undo**; advice that triggers a destructive op is hard to reverse. → irreversibility of the *subject* forces tier **>= medium**.
- **Blast radius:** the report is read-only output under the research dir; constraint is "do not mutate the working tree." Blast radius of the *deliverable* itself is contained.
- **Projected tier: MEDIUM.** Phase-3 includes independent reviewer + separate judge passes.

## Candidate branches
- **B1 (chosen):** Verify-against-tree brownfield inventory → fan-out sub-agents over (architecture, tests/build/run, docs+prior-work, working-tree state) → cross-check doc claims vs disk → synthesize orientation report + risk register. Adversarial review by independent agents.
- **B2 (dropped):** Trust CLAUDE.md + memory as ground truth and just reformat them into a report. *Counterfactual cost of dropping:* none lost — this is exactly the falsification mode; CLAUDE.md is detailed but is a claim, not an observation, and the git working tree shows uncommitted drift (modified dashboards, untracked .anchor/, rnd_jobs/) that a doc-only pass would miss.
- **B3 (dropped/deferred):** Deep per-module code audit (read every .py end-to-end). *Counterfactual cost:* lower risk of a subtle behavioral miss, but far over-scoped for an *orientation* report and would blow the budget; deferred to the "outstanding work" the new owner can do. Recorded as a known coverage limit.

## Best-in-class baseline to beat
A competent engineer handed the repo who runs `git log`, reads CLAUDE.md, and skims the top of each module. The report must beat that by: (1) reconciling doc-claims with on-disk reality, (2) explicitly separating DONE vs OUTSTANDING with evidence, and (3) a prioritized risk/unknown register — not just a file tour.

## Oranges foresight receipt
Dropped branch B2 (doc-only) — counterfactual cost: **zero** (it is the falsification trap). Dropped branch B3 (full code audit) — counterfactual cost: **real but out-of-scope** (a subtle behavioral bug could go unseen); recorded as an explicit coverage limit and handed to the new owner as outstanding work. Foresight value: added (named both drops + their costs).

## Note on prior work discovered pre-freeze
A sibling research run exists at `.anchor/projects/227eb089706140388b829776d87e57c8/research/` (01-report.md, 02-executive.md, 03-agent-impl.*, evidence-ledger.jsonl, plan-anchor-brownfield-orientation.md). It is the SAME brownfield-orientation task on the SAME folder under a different project id. It will be treated as prior research to inventory and cross-check — NOT copied. Our output is independent and lands under project 2fe37f39….

PLAN FROZEN.
