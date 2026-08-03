# Crucible Master Plan: Ramanujan Dual-Track Expansion

## Oranges Brainstorm

### Assumption Map
1. **Isolation Guarantee:** The empirical track can be perfectly sandboxed and isolated from the formal ledger. (If this is false, empirical tests might leak as "verified" claims, violating the Honesty Law).
2. **Pillar Independence:** A 7th pillar (Solve/Execute Empirical) is sufficient to handle heuristic execution without entangling the other mathematical reasoning pillars.
3. **Advisory Boundaries:** The Synthesizer can act effectively as a non-autocratic advisor that steers without deciding, while the user retains full manual override capability.

### Premortem
1. **Honesty Law Breach:** Users confuse the new `EMPIRICALLY-TESTED` rung with `VERIFIED`, trusting unverified algorithms as mathematically sound.
2. **Ledger Pollution:** The sandbox isn't rigorous enough, so heuristic side-effects pollute the shared ledger and trigger false failures in the formal `VERIFY` router.
3. **Autocratic Takeover:** The Synthesizer ignores the mixed-initiative constraints and forces the session down paths the user didn't choose, overriding the "user retains absolute control" rule.

### Ideate
* **Strict Claim Typing:** Introduce strict typing for the ledger claims: `Claim<Mathematical>` vs `Claim<Empirical>`. The `VERIFY` pillar explicitly routes `Claim<Empirical>` safely away from the formal out-of-model certifiers, ensuring it never hits Lean/z3 and fails closed.
* **Control Precedence:** The orchestrator's Mixed-Initiative control engine must be built *before* the Synthesizer, ensuring the Synthesizer is hard-bound to an advisory role and cannot dispatch without user (or explicit auto-pilot) approval.

## Shark-Tank Convergence Log

* **Round 1 (Control Precedence):** The initial draft placed the Synthesizer build (Phase 3) before the Mixed-Initiative control (Phase 4). The Skeptic and Contrarian flagged this as a blocker: building the AI advisor before the user-control constraints risks an autocratic takeover during the build, violating the North Star. The Judge ruled to swap them.
* **Round 2 (Router Integration):** The updated draft built the 7th pillar but missed the `VERIFY` router. The Contrarian and Analyst flagged that since `VERIFY` is an always-on router for all ledger claims, it must be updated to handle the new `EMPIRICALLY-TESTED` rung; otherwise, empirical claims will hit the formal certifiers and falsely fail-closed. The Judge ruled to explicitly include router updates in Phase 2.
* **Round 3:** Sharks 1, 2, and 3 reviewed the revised plan and found no North Star violations. 0 Sharks object. Convergence achieved.

## Converged Phased Plan

* **Phase 1: Architecture & Structural Definitions**
  * Update `SKILL.md` to establish the 7-pillar architecture.
  * Define the `EMPIRICALLY-TESTED` rung and strictly delineate it from `OBSERVED`/`VERIFIED` in the Honesty Law.
* **Phase 2: The Empirical Sandbox & Router Integration (Pillar 7)**
  * Implement the 7th pillar (`Execute Empirical`).
  * Establish the rigorous empirical execution sandbox.
  * Update the always-on `VERIFY` router to explicitly recognize and route `Claim<Empirical>`, bypassing the formal out-of-model certifiers (Lean/z3).
* **Phase 3: Mixed-Initiative Control Engine**
  * Refactor the orchestrator to explicitly enforce manual jumps, user overrides, and arbitrary iteration.
  * Establish the strict boundary where the user retains absolute control over dispatch.
* **Phase 4: The Persistent Deep-Think Synthesizer**
  * Implement the Synthesizer module (frontier models + Oranges-lens foresight).
  * Wire the Synthesizer to operate strictly as an advisor within the Phase 3 control engine, completing the mixed-initiative workflow.
