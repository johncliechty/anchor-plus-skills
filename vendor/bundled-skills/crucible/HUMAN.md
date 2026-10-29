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
- Stage 0: a North Star you lock (success criteria, non-goals, risks — always shown in full on screen)
- Stage 1: a Master Plan you approve — including **Multi-Level Adversarial Matrix Mode (`--matrix-fast-track`)**, which decomposes complex systems into parallel dimension studies (`researchPrime` + `Gandalf`) and an explicit **6-Layer Adversarial Review Matrix (`L0–L5`: Failure Mode, Severity, Concrete Mitigation)** that converges in 1 bounded pass instead of stalling in 20–30 sequential CLI subprocess spawns
- Stage 2: a wave-by-wave (and orthogonal sub-wave `W.1`..`W.k`) implementation plan validated deterministically by `locate-plan.mjs` and ready for Foreman
- Adversarial “Shark Tank” or `L0–L5` Matrix review so weak ideas die before build time (with delta-only `120s` re-review if $\ge 2$ reviewers prove an unmitigated `BLOCKER`)

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
