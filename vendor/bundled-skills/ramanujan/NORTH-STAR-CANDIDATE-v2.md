# Ramanujan — CANDIDATE North Star v2 (Stage 0; awaiting USER lock)

> Supersedes NORTH-STAR-CANDIDATE.md (the narrow understand+firewall version). Reflects: the broad math-reasoning-partner
> re-frame + Path A + dive-1 (UNDERSTAND, converged) + dive-2 (SOLVE+VERIFY, converged) + the D-PROMOTE (c) decision
> (both independence sources, always-on). Band: FULL. STATUS: NOT LOCKED — the user is the convergence authority.

## OBJECTIVE
**Ramanujan is a mathematical reasoning PARTNER.** This cycle's locked, buildable scope is THREE composed pillars on one
shared spine (typed-claim decompose + per-claim honest stamp + the verification router):

- **UNDERSTAND** *(dive-1, converged)* — given a paper's METHOD (method/algorithm section + cited equations, EXCLUDING
  released code), produce a rigorous laddered COMPREHENSION (what it computes / why / where it breaks) AND, when the
  method is computable, the understand→build FIREWALL (a pure/offline/deterministic reference fn trusted by checks
  INDEPENDENT of the agent's reading).
- **SOLVE** *(dive-2, converged)* — given a NEW problem, GENERATE a candidate solution via a stateless one-shot
  generation pass (Polya heuristics) wrapped by a stateful metacognitive CONTROL loop (Schoenfeld: progress-monitor →
  continue / switch / ABANDON on a budget). Generation is cheap and treated as UNVERIFIED until the stack verifies it.
- **VERIFY** *(dive-2 + decision c)* — a VERIFICATION ROUTER decomposes any solution into typed CLAIMS and routes each to
  an **ALWAYS-ON independent verification LADDER**: attempt the strongest APPLICABLE generator-INDEPENDENT verifier —
  **Lean** (formalizable proof/logical claims, via autoformalization gated by the faithfulness discipline; kernel-grade
  = OBSERVED) → else **cross-family** model (informal proof/conceptual claims; statistical independence = CORROBORATED)
  → **firewall** (computational claims; `computational-LOCAL`) — degrading honestly and ABSTAINING/FLAGGING only when NO
  independent verifier applies. **Same-family LLM critique (Gandalf, in-process adversarial) is ADVISORY ONLY — it never
  earns a trust rung.** Every claim carries an honest **rung + verifier-family** stamp.

## NORTH-STAR CRITERIA (testable — drive the inclusion test + drift detector)
- **NS1 — Verified comprehension** (UNDERSTAND): laddered; OBSERVED requires an executed-ref-fn / external-anchor match.
- **NS2 — Generative SOLVE with CONTROL**: the stateless generation pass + the executable CONTROL state machine
  (continue/switch/abandon), graded over a defined progress signal.
- **NS3 — Always-on independent verification ladder**: every claim is routed; trust is earned ONLY by a
  generator-INDEPENDENT verifier (Lean / cross-family / firewall); the strongest applicable is always attempted;
  same-family critique is advisory-only; honest ABSTAIN/FLAG when none applies. No self/same-family grading is a rung.
- **NS4 — Autoformalization faithfulness**: every Lean check is gated by the faithfulness discipline (back-translation /
  N-way consensus / human gate) — a green proof of the WRONG formalization is never trusted.
- **NS5 — Honest per-claim stamp**: rung (OBSERVED / CORROBORATED / CLAIMED / UNVERIFIED) + verifier-family; cross-family
  corroboration LIFTS the rung to CORROBORATED (the single-family CLAIMED ceiling is gone); kernel-checked = OBSERVED.
- **NS6 — Machine-checkable composition + gradeable oracle**: EMIT/commission Gandalf-advisory + the verifiers WITHOUT
  reimplementing them (structural canary); a gradeable oracle that REJECTS a planted-wrong and ACCEPTS a correct
  solution PER CLAIM TYPE (computational, cross-family-checkable, Lean-formalizable), each by its independent verifier.

## SCOPE
- **IN (buildable this cycle, given (c)):** the three pillars + the always-on verification ladder (firewall + cross-family
  + Lean + the autoformalization-faithfulness discipline) + the router + the fail-safe claim-type dispatch + honest
  rung+family stamps + the CONTROL loop + commission/emit composition + the gradeable oracle + an explicit author-SKILL.md wave.
- **DEPENDENCIES (the honest cost of (c) — integration, not subscription fees):** a **Lean toolchain integration**
  (free/open-source: elan/lake + a mathlib build + agent wiring) and **cross-family model access** (a second model
  family as verifier). ⇒ Ramanujan is NOT a pure-subscription autonomous build; it is a Lean+cross-family integration.
- **DEFERRED to future cycles (each its own research dive, NOT locked now):** DIALOGUE as its own pillar (beyond the SOLVE
  loop); CONTEXTUALIZE (situate ideas in human mathematical knowledge via researchPrime/Gandalf); FORMALIZE as an
  interactive GOAL (helping build/refine formalizations of ideas) beyond formalization-for-verification.
- **OUT / reversed:** the dive-1 Oranges drop of formal proof methods is **REVERSED** — Lean is now IN-scope (decision c).

## TO BE DESIGNED IN THE CRUCIBLE PLANNING STAGES (Shark-Tanked; no new dive needed)
The always-on ladder ORDERING + the formalization-failure FALLBACK (what happens when a proof won't faithfully formalize
for Lean → cross-family → abstain) — a recombination of dive-2-researched components. Plus the residuals S1–S4 from dive-2
(CONTROL thresholds; Lean form installed-vs-service; faithfulness human-gate; the must-catch roster + per-claim-type
margins + the firewall-ref-fn-generator-independence invariant, REQUIRED-before-build).

## INHERITS (compose, don't rebuild)
Phase-0 infra (handoff / journal / sleep) · Gandalf v1 (advisory diagnose engine + the seam/schema commission pattern) ·
the dive-1 firewall + UNDERSTAND pillar (the shared claim-decompose + stamp spine).
