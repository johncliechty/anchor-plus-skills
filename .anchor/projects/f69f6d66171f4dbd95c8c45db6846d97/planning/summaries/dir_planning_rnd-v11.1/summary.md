# Anchor R&D Surface v11.1 — "Handoff Always Primes" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-20

**What was asked:** Anchor R&D Surface v11.1 — "Handoff Always Primes" — Master Plan (frozen design)

**North Star:** **Advancing any trio stage (research→plan, plan→build), grass or non-grass, ALWAYS opens the next stage with a useful, honest transition prompt — even when the source produced no written doc — and the source session's CONTENT is captured and made available to the next stage so nothing is lost. When there are no written materials, the next session opens, loads the transition prompt, and is set up to CREATE the materials (informed by the captured research conversation).** One handoff path (the v11 `prepare_stage_handoff` keystone) — the snapshot + honest-prompt logic lives in ONE place, applied

## Actions & files produced

- Anchor R&D Surface v11.1 — "Handoff Always Primes" — Master Plan (frozen design)
- Anchor R&D Surface v11.1 — "Handoff Always Primes" — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- ## Anchor R&D Surface v11.1 â€” "Handoff Always Primes" â€” Planning Session Summary
- **Goal / North Star (locked, John's intent)**
- Advancing any trio stage (researchâ†’plan, planâ†’build), grass or non-grass, must **always** open the next stage with a useful, honest transition prompt â€” even when the source produced no written document.
- The source session's **content is captured and made available** to the next stage so nothing is lost.
- When there are no written materials, the next session opens, loads the transition prompt, and is **set up to CREATE the materials**, informed by the captured research conversation.
- One handoff path: the snapshot + honest-prompt logic lives in **ONE place** â€” the v11 `prepare_stage_handoff` keystone â€” applied uniformly.
- **Key decisions (John-approved)**
- **D1 â€” Remove the grass hard-refusal.** Delete the `no-research-material` block (`effort_history.py:817-822`) so the grass advance **always proceeds and opens the next session**, exactly like the non-grass path â€” unifying the two behaviors.
- **D2 â€” Honest + actionable no-docs prompt.** Rewrite the no-docs fallback (`handoff.py:609-616` plus the build fallback) so it makes **no false claim** that a research report exists in the worktree; instead it instructs the next skill to **review the captured research (transcript/summary) and CREATE** the planning materials (Master Plan + Implementation Plan).
- The frozen design is captured across two member documents: the **Master Plan** (frozen design) and the **Implementation Plan** (Foreman-ready).
- The driving gap: a research session whose work existed only as a terminal conversation (no written file) previously caused the grass advance to refuse and the non-grass advance to open with a misleading prompt â€” the conversation (the actual research) was lost.

## Files

- [Anchor R&D Surface v11.1 — "Handoff Always Primes" — Master Plan (frozen design)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v11.1%2FMASTER-PLAN.md)
- [Anchor R&D Surface v11.1 — "Handoff Always Primes" — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v11.1%2FIMPLEMENTATION-PLAN.md)
