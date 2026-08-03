# Ramanujan — Stage-0 SCOPE EXPANSION (user, 2026-06-21) — NOT yet locked

The user expanded Ramanujan from a paper-method comprehension+firewall tool to a broader **mathematical reasoning
partner**. Verbatim intent: Ramanujan should "engage in a dialogue about mathematical ideas and help build up and
refine formalizations of the ideas, put them in context with general human knowledge as well as solve new math
problems posed to it. It is not just a describer of math and converter into algorithm and code (although that is
important as well)." And: questions whether relying on **Gandalf** for critical analysis is sufficient — "I can see
that in part, but I think we may want/need more."

## The five pillars implied
1. **UNDERSTAND** — comprehend a paper's method → laddered comprehension + the understand→build FIREWALL. **[RESEARCHED + engine-converged in the dive]**
2. **DIALOGUE** — interactive back-and-forth about mathematical ideas (a stateful mode, not a one-shot artifact). **[UN-RESEARCHED]**
3. **FORMALIZE** — take informal ideas → build/refine formalizations (definitions, theorem statements, possibly machine-checkable). **[UN-RESEARCHED; partly REVERSES the dive's Oranges-drop of formal methods]**
4. **CONTEXTUALIZE** — place ideas in the landscape of human mathematical knowledge (overlaps researchPrime/situate + Gandalf's situate). **[UN-RESEARCHED]**
5. **SOLVE** — tackle NEW math problems posed to it (GENERATIVE problem-solving — Polya's full method, not just the comprehension subset). **[UN-RESEARCHED; the current North Star explicitly excludes generation]**

## Open architecture question (user-raised): is Gandalf enough for critical analysis?
Short answer carried into the dive: necessary, NOT sufficient for the generative pillars (see analysis in the chat).
The shared-origin-pair insight from the dive applies: critiquing math Ramanujan ITSELF generated needs INDEPENDENT /
executable verification, not advisory diagnosis of its own output.

## Status
The comprehension+firewall pillar (1) is researched + converged. Pillars 2–5 + the verification-architecture question
are UN-RESEARCHED. Per the Gandalf-cycle lesson (a mid-Crucible scope expansion locked without research drifts and the
Shark Tank bounces it), the North-Star lock is PAUSED pending the user's chosen path.

## DIVE #3 DONE + ENGINE-VERIFIED CONVERGED (2026-06-21): the INTERACTIVE PARTNER LAYER (Dialogue+Formalize+Contextualize)
At `planning\research-partner-layer\` (FINDINGS.md, DELIVERABLE.md, run\ trail incl. DRAFT-FINDINGS-v6.md + DELIVERABLE-
ENGINE.json). The DEEPEST dive: 7 rounds (BLOCKED×2→DRY→BLOCKED×2→DRY→DRY, dryStreak 2/2, verified:true, cross_model:false,
tier=high, unresolvedHigh=0, guard NOT fired, context-free Judge=CONVERGED). The VERIFIED-stamp independence recursion
bottomed out (predicate-reduction→claim_domain→formalization-faithfulness→TERMINUS: autonomous VERIFIED = literal-execution
only, NO same-family object in the path; everything else routes to the out-of-model cross-family/Lean/SMT certifier or caps
CONJECTURAL). Lakatos 'Proofs and Refutations' = the connective tissue (dialogue method = definition-forging method). Six
pillars compose on ONE typed claim ledger + verify router + state model (Understand/Contextualize = claim-emitters;
Solve/Verify/Dialogue/Formalize = stateful). ALL THREE pillar dives now DONE -> the full 6-pillar North Star is lockable.

## DIVE #2 DONE + ENGINE-VERIFIED CONVERGED (2026-06-21): SOLVE + VERIFICATION STACK
At `planning\research-solve-verify\` (FINDINGS.md, DELIVERABLE.md = 3 levels + Crucible intake, run\ trail incl.
DRAFT-FINDINGS-v4.md + DELIVERABLE-ENGINE.json). 4 rounds (BLOCKED→BLOCKED→DRY→DRY, dryStreak 2/2, verified:true,
cross_model:false, tier=high, unresolvedHigh=0, guard NOT fired, context-free Judge=CONVERGED). 6 ≥2-agree blockers +
2 single-raise MAJORs + 1 MINOR found+fixed across v1→v4.
**HONEST HEADLINE RESULT:** autonomous SOLVE-with-INDEPENDENT-verification of PROOF-BEARING math is NOT buildable this
cycle (single-family, bare subscription). Buildable = a VERIFICATION ROUTER (generate→decompose→route→firewall-verify-
arithmetic→ABSTAIN-on-proofs + a metacognitive CONTROL loop). **Gandalf is NOT enough AND not independent** — same-family
critique (Gandalf, in-process adversarial) is ADVISORY, structurally barred from the trust stamp; the ONLY autonomous
independent verifier is the dive-1 firewall (computational-LOCAL only). Independent PROOF verification needs Lean
(heavyweight external) or cross-family — both HALT-gated. ⇒ **D-PROMOTE decision is now LIVE for the user** (Option A ship
the computational-only router now vs Option B promote Lean/cross-family in-scope first). North-Star lock still PAUSED on D-PROMOTE.

## D-PROMOTE DECISION (user, 2026-06-21): Option B, refined to (c) — BOTH sources, ALWAYS-ON (max assurance).
The verification stack is PROMOTED from HALT-gated to IN-SCOPE: firewall (computational) + cross-family (informal proofs)
+ Lean (formalizable proofs, via autoformalization with the faithfulness discipline), independent verification ALWAYS-ON
(not opt-in). Consequences (honest): (1) NOT a pure-subscription autonomous build — requires a Lean toolchain integration
(free/open-source: elan/lake + mathlib build + agent wiring) + cross-family MODEL ACCESS (a 2nd model family); these are
build/integration costs, NOT subscription fees. (2) "Always-on" = a verification LADDER, because most informal/research
math won't faithfully formalize for Lean (~minority formalize cleanly): attempt the STRONGEST APPLICABLE independent
verifier (Lean if it faithfully formalizes → else cross-family → firewall for computation) and degrade honestly; Lean
covers the formalizable subset, cross-family does most of the informal-proof work. (3) UPSIDE: adding a cross-family
verifier LIFTS the dive-1/2 single-family cross_model:false ceiling — claims a cross-family verifier corroborates EARN
cross-family independence ⇒ the CORROBORATED rung becomes reachable (no longer capped at CLAIMED). (4) FORMALIZE/
autoformalization is now LOAD-BEARING in the always-on stack (feeds Lean), so the Formalize pillar is partly pulled in.
The always-on ladder + formalization-failure fallback are a recombination of dive-2-researched components — to be DESIGNED
in the Crucible planning stages (Shark-Tanked), no new research dive required.

## DECISION (user, 2026-06-21): PATH A — re-frame broad, research the new pillars FIRST, then lock & plan.
**Lead with SOLVE (generative problem-solving) + the VERIFICATION STACK** (is Gandalf enough? the layered
firewall / formal-proof-checker / adversarial stack routed by claim type; the formal-methods-drop reversal). The
Crucible Stage-0 lock is PAUSED while a second engine-mode researchPrime dive grounds these. Pillars Dialogue /
Formalize / Contextualize follow (Formalize is adjacent — the verification stack must already handle proof/formalization
claims). Dive workspace: `skills\ramanujan\planning\research-solve-verify\`. The understand+firewall dive
(`planning\research\`) becomes the first researched pillar, independently shippable.
