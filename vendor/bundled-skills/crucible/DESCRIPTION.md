# Crucible — Description / Design Doc (for the Foreman build)

**What we are building:** **Crucible**, a standalone production *planning* skill — the planning brain of the trio **ResearchOne → Crucible → Foreman**. It turns an intent (or a messy existing project) into a vetted, **gold-standard, Foreman-ready implementation plan**, without drifting from the project's locked objective.

**Full design (source of truth):** `MASTER-PLAN.md` (v4.1, converged through 3 Shark-Tank rounds; decisions D1–D16 in `DECISION-LOG.md`). This file is the Foreman *description* role; the **waves** live in `IMPLEMENTATION-PLAN.md`.

## Architecture (summary — see MASTER-PLAN for detail)
- A **Node engine** (a Foreman *sibling*) that **imports** Foreman's modules — `foreman-lib.mjs` (atomic checkpoint writes, budget), `git-hygiene.mjs`, `makeAgentDriver({agent})` from `wave-workflow.js` — and **spawns** `foreman/bin/locate-plan.mjs` as the well-formedness gate. **Never fork** Foreman code.
- **Three stages**, each ending at a user-approval HALT gate: Stage 0 Intake & Framing → Stage 1 Master Plan → Stage 2 Implementation Plan.
- **Shark Tank** = the adversarial review round: 3 fresh-context Sharks (Skeptic/Contrarian/Analyst), BLOCKER needs ≥2 to agree.
- **The Synthesizer** = a persistent Deep-Think Director (steers, does not decide). The **Judge** decides (cross-model when reachable, else a same-model judge persona in a fresh, context-free sub-agent). The **user** is the final convergence authority.
- **Anti-drift** North-Star pillar with the **Grasscatcher** backlog and the **inclusion test** (every element must serve a North-Star criterion).

## Tech & conventions
- Language: **Node.js (ESM `.mjs`)**, matching Foreman. Native test runner (`node --test`).
- Sub-agents communicate via **file paths only**; the orchestrator writes forge-proof gate artifacts.
- Authored BOM-free; CRLF tolerated (git `eol=lf` normalization).

## Scope / Non-goals
- **In:** the planning engine, the Shark-Tank + Synthesizer + Judge loop, Stage-0 intake (greenfield + tiered brownfield), the two-gate convergence, anti-drift/Grasscatcher, docs/VC layer, capability-bound cross-model Enhanced mode, tests + a dogfood self-run.
- **Out (Non-goals):** pedagogy/education; building product code (that's Foreman); being the everyday lightweight planner (that's Project-Manager); requiring cross-model for v1; full machine-verifiable YAML conformance contracts and a full cross-model debate roster (both v2 — see `GRASSCATCHER.md`).
