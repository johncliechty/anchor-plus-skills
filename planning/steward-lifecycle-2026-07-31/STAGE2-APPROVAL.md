# STAGE-2 APPROVAL — steward campaign orchestration

**APPROVED by John 2026-08-02** to proceed to the Foreman (Heavy) build.

## What is approved

| Artifact | Value |
|---|---|
| Plan | `stage2-artifacts/IMPLEMENTATION-PLAN-v3.md` — **22 waves**, AUTHORITATIVE |
| Decomposition | `stage2-artifacts/wave-decomposition-v3.json` — generated from the plan |
| Binding | `source_sha256` = `2a2a21804154891b…` — **verified matching** 2026-08-02 |
| DAG | acyclic, no dangling deps; order **1–18 → 20 → 21 → 22 → 19** |
| North Star | v5, LOCKED 2026-08-02 (15 criteria) |

## Provenance of this approval

Stage 2 originally HALTed human-lockable with the judge NOT_CONVERGED. Rather than
stamp it, the plan was subjected to TWO independent Fable reviews (consistency +
hardening), which found it NOT safe to build; all 13 must-fixes were applied; a THIRD
review (skill-vs-host boundary) reframed the effort to skill-first, producing North
Star v5 and plan v3. John is the convergence authority and approves on that basis.

## Authorized real-run budgets (CHEAP COMMISSION PROFILE)

Waves **4, 5, 13, 14, 19, 20, 22** may spawn REAL trio-CLI child processes under the
named cheap profile (a LITE researchPrime run, smallest depth). Gate decision 6
explicitly approved W20 + W22. Real-run gates are wave-local scripts EXCLUDED from the
standing suite. Tests must not spend without explicit opt-in; the spend invariant the
build is implementing applies to the build itself.

## Binding decisions carried in

Gate decisions 1–7 and signed Descope D-1 — see `STAGE1-APPROVAL.md`. Summary:
1. Unattended reflections never spend (queue; compile at next session open).
2. Portfolio index: Wave-1 live-wiring audit (A5); fix items only; never re-plan.
3. `briefCacheStale` fixed in Wave 1 under a named-fix diff fence.
4. Criterion 4 = deterministic zero-model reflection at handback; rich compile later.
5. `who` = CLAIMED identity stamped unauthenticated; never rendered as proven.
6. Real-run budgets for W20 + W22 approved (cheap profile).
7. ONE SKILL, TWO ENTRY SURFACES; in-session executor BUILT NOW; divergence mitigated
   by the Wave-21 shared conformance suite (one contract, two hosts).
D-1. SIGNED — no run-scoped capability minting; no-credential handback-file design.

## What this does NOT approve

Splitting the steward into two skills · steward logic in Anchor Python · rebuilding the
portfolio index · resurrecting the refuted ideas (handback artifact channel;
bind-and-derive as new work) · changes to Crucible/Foreman/researchPrime internals ·
pushing to any remote without John.
