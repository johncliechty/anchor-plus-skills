# researchPrime Verification+Foresight Upgrade — Description (Foreman doc-trio)

## What is being built
An **engine-backed verification + foresight upgrade** to the researchPrime skill. researchPrime gains a Node
engine at `researchPrime/bin/` (ESM) that, **importing — never forking** — the trio's machinery
(`crucible/bin/{shark-tank,synthesizer,judge,enhanced}.mjs` and `foreman/bin/foreman-lib.mjs`), replaces
researchPrime's single-reviewer / single-round Phase-3 with a **stakes-scaled, multi-round adversarial
verification loop** and adds **Parable-of-the-Oranges foresight** to Phase-1.

researchPrime continues to OWN: the evidence ledger, the verification ladder (OBSERVED>CORROBORATED>CLAIMED>
UNVERIFIED>REFUTED), GATE-1 independent-origins, and a new stakes governor.

## Why (the locked North Star)
Conclusions measurably more **trustworthy** and the research path better-**aimed**, using the evidence-backed
levers (independence/CoVe, multiplicity/self-consistency, a separate Judge, heterogeneous ≥2-agree reviewers,
convergence-until-dry), with an active Deep-Think Synthesizer and conditional debate — **scaled by AXIS stakes**
and **ρ-honest in both modes** (default reports correlated-blind-spot recall + caps same-family agreement;
Enhanced fuses genuinely cross-lineage review into GATE-1). No element survives that doesn't serve the AXIS.

## Source of truth
The full design + the 7 locked invariants (I1–I7) live in `MASTER-PLAN.md` (v5, converged through 3 Shark-Tank
rounds). The vetted idea harvest is `HARVEST-SYNTHESIS.md`. This description + `IMPLEMENTATION-PLAN.md` +
`EXECUTION-LOG.md` are the Foreman doc-trio.

## Reserved / halt-worthy (Foreman must NOT decide these autonomously)
- Any change to the locked North Star or invariants I1–I7.
- Choosing the attested-lineage enum membership (crit-5) — a human/policy call.
- Setting the pre-registered thresholds G / X% / C_min / N — these are pre-registered by a human in Wave 1.
- Retiring the prose/degraded mode, or merging researchPrime into Project-Manager (out of scope).

## Ground truth
Build + test gate: `node --test test/` (the trio convention), run by the orchestrator, never a sub-agent.
