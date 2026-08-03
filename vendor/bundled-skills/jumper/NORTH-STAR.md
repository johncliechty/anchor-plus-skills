# NORTH-STAR — jumper

> This file is the skill's LOCKED purpose + its anti-drift contract. A sleep cycle
> (P0.D) may NEVER ship a revision that violates it (NS3 no-drift).

## Purpose (LOCKED)
Jumper is the dedicated, high-order Ideation and Brainstorming Engine of the portfolio. It strictly composes the Gandalf deep-think skill—using Gandalf's rigorous diagnosis as a foundation—to generate novel, out-of-the-box solutions, architecture extensions, and creative pivots. It leverages structured human ideation frameworks (e.g., TRIZ, SCAMPER, Analogical Transfer) to force divergent thinking. Crucially, it employs a 'generative-and-vetted' methodology: all generated ideas are subjected to a ruthless kill-filter so only structurally sound, highly promising concepts are presented — the filter suppresses hallucinated and shallow output (a mitigation, not a guarantee of elimination; the gate logs stay honest about what was checked and on what substrate). As of 2026-07 it produces a PORTFOLIO of sphere-diverse candidates run as a tournament (ranked survivors + a kill log), not a single take-it-or-leave-it idea.

## Logical tier (the brain seam — NS4)
This skill's persona is **method + a LOGICAL tier**, never a hard-coded model. Its
tier is one of `top | opus | sonnet | haiku` and is resolved to a concrete model
ONLY through the swappable tier→model table (`config/tier-model.json`) or the
per-role driver env ladder (`CLAUDE_MODEL_<ROLE>`; roles: synthesizer, analogy,
triz, deconstruct, gandalf, gate, ground). Record the tier here as data; do NOT
name a model in any prose file.

- logical tier: `top` (the analogy/TRIZ/synthesizer seats — cross-domain
  structural mapping is where the top tier separates)
- gate 3 (adversarial) is cross-FAMILY by preference (`JUMPER_GATE3_DRIVER`),
  not a stronger same-family model — independence, not intelligence, is its point.

## Non-goals — machine-checkable negative tests (R4 / NS3 anti-drift)
Each non-goal is a NEGATIVE canary: an input the skill must REFUSE or FAIL on.

| id   | non-goal (the skill must NOT do this) | negative canary (an input that MUST FAIL the skill) |
|------|----------------------------------------|------------------------------------------------------|
| NG-1 | Present an idea that bypassed the Kill-Filter (no "just brainstorm, skip the gates" mode) | An options/request combination asking for raw un-gated ideas (e.g. `skipKillFilter: true`) must be refused/ignored — every returned concept must carry `gateLogs` with all three gates recorded |
| NG-2 | Self-assign Gandalf honesty tiers/stamps (grading belongs to the deterministic seam pass) | A Gandalf draft that arrives pre-stamped (`tier: "GROUNDED"` in the raw draft) must be re-graded by `applySeamPass`, never passed through |
| NG-3 | Become an execution/build engine (Jumper ideates and grounds a TEST PLAN; it never writes production code or applies changes) | A request "implement the winning idea in the repo" must be refused with a handoff pointer (Crucible/Foreman), not fulfilled |
| NG-4 | Fabricate portfolio diversity (survivors from a single sphere silently presented as diverse) | A fan-out run whose candidates all name the same foreign domain must surface that in the result (distinct `foreignDomain`s or an honest note), never relabel one domain as several |

## Invariants (always true of a correct revision)
- Every returned concept (single or portfolio) carries the full 3-gate `gateLogs`,
  including the gate-3 `substrate` stamp (cross-family vs same-family).
- The default (no `fanOut`) pipeline shape stays backward-compatible: callers get
  `{passed, concept, gateLogs, groundingExecutionProtocol}` on success.
- A kill is honest: `failedAtGate` + `rejectionReason` (portfolio: `killLog[]`) are
  always populated; a retry happens at most ONCE and is stamped `retried: true`.
- Jumper composes Gandalf by embedding its real SKILL.md protocol — never a
  paraphrase of it.

## Provenance
Forged by the `researchPrime → skill-Crucible → Foreman` cycle for `jumper`.
Seeded from the Phase-0 per-skill repo skeleton (`skills/templates/skill-repo/`).
Portfolio/tournament mode + cross-family gate 3 + real Gandalf commission added
2026-07-02 (John-approved review implementation; gates 23/23).
