# Crucible

**One sentence:** The planning brain — turns a goal (or a messy project) into a locked North Star and a Foreman-ready build plan you approve at every major stage.

## Use this when
- You’re starting something non-trivial and need a real plan, not a sketch
- An existing project is messy and needs a clean, vetted path forward
- You want adversarial stress-testing of the plan before anyone writes code

## Do not use this when
- You already have a frozen plan and just need it built (use Foreman)
- You need research evidence first (use researchPrime, then come back)
- The ask is a one-line task or a tiny fix that doesn’t need a multi-stage plan

## What you get
- Stage 0: automatic right-sized depth triage (`LITE` for localized 1–3 file brownfield/greenfield work, `MATRIX-FAST-TRACK` for medium multi-file/architectural work, `SPIKE-FIRST` when genuinely novel/uncertain, `FULL` reserved for explicit `--depth FULL` or high-stakes irreversible changes), zero-LLM **Anvil** brownfield AST facts intake when a repo exists, and a North Star always shown in full on screen before lock.
- Stage 1:
  - **Enforced `LITE` Fast Path (`<= 4` model calls via `bin/slim.mjs` / `runLiteFastPath`):** compact unified draft + 1 cross-family review + `<= 1` delta patch + `locate-plan.mjs`.
  - **Lean 2-Stage `--matrix-fast-track` (`6–9` bounded model calls via `bin/matrix-fast-track.mjs` / `bin/crucible.mjs`):** conditional **Superjump** architectural option pass, unified Plan+Waves draft, 1 cross-family heterogeneous **`L0–L5` 6-Layer Adversarial Matrix** (`L0` North Star & plain-English scope cuts, `L1` Anvil Pure-Core / Deep-Module, `L2` Aegis CWE boundaries, `L3` Chrome UI mockup / `Figure-Designer`, `L4` testability + Wave-1 pilot slice + `O(N)` call budget, `L5` Gandalf simplicity cut), stopping immediately on `0` blockers (`ELEGANCE.md` Rule 5) or running `1` `120s` delta-only verify pass on patched blockers.
- Stage 2: deterministic wave serialization (`## Wave 1 .. ## Wave N` plus disjoint-write-set `### Wave W.k` sub-waves), mechanical **Chekhov Plan-Quality Guards** (Wave-1 usable end-to-end pilot slice, `O(N)` serial LLM call estimator, `<= 200`-word approval block naming deferred/cut scope in plain English, automatic Interactive Chrome Mockup / `Figure-Designer` + `Ramanujan` / `Financial-Analyst` / `Legal-Beagle` / `Literature-Review` certifier gates), validated by `locate-plan.mjs` without a redundant second Stage-2 Shark-Tank loop.

## What it is not
- Not a code builder (that’s Foreman)
- Not a lightweight daily task list
- Not a free-for-all that invents scope after you locked the goal

## How to start (human)
1. Open Crucible with your intent or project folder.
2. Confirm the recommended depth (light / full / probe-first) when asked.
3. Read the full North Star on screen, then lock it.
4. Approve the Master Plan and the implementation plan the same way — only what you see on screen.

## Limits (honest)
- You are the approval authority; stages pause until you decide
- Full runs are heavyweight (time and attention); lighter depth exists for smaller work
- It plans; it does not ship product by itself

## For agents / engines
Full protocol and wiring live in `SKILL.md` next to this file (trio monorepo: `<path> Load that only when running the skill — this card is for people.
