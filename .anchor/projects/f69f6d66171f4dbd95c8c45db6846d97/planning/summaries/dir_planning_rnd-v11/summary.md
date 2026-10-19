# Anchor R&D Surface v11 — "Reliable Trio Handoff" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-20

**What was asked:** Anchor R&D Surface v11 — "Reliable Trio Handoff" — Master Plan (frozen design)

**North Star:** **Advancing any trio stage (research→plan, plan→build) in the LIVE flow reliably PRIMES the next stage: the source stage's produced docs are persisted into the project, the next session opens with a REAL prompt that names the actual persisted doc paths + "read these first," a HANDOFF.md / handoff summary is written so the next stage starts informed, the sessions are linked — and this is VERIFIED against the real worktree-only flow so "tests green but live broken" cannot recur.** The deeper objective (the inclusion test): there is **ONE** handoff path, not four half-wired ones. Every advance —

## Actions & files produced

- Anchor R&D Surface v11 — "Reliable Trio Handoff" — Master Plan (frozen design)
- Anchor R&D Surface v11 — "Reliable Trio Handoff" — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star (locked):** Advancing any trio stage (researchâ†’plan, planâ†’build) in the LIVE flow reliably PRIMES the next stage â€” the source stage's produced docs are persisted into the project, the next session opens with a REAL prompt naming the actual persisted doc paths + "read these first," a HANDOFF.md / handoff summary is written, and the sessions are linked.
- **Verification mandate:** The handoff is VERIFIED against the real worktree-only flow so that "tests green but live broken" cannot recur.
- **Deeper objective (inclusion test):** There is ONE handoff path, not four half-wired ones â€” every advance routes through the same shared mechanism.
- **D1 â€” Patch vs unify â†’ Unify:** One shared `prepare_stage_handoff` keystone that ALL advance paths call. Rationale: the bug was an un-mirrored one-line patch; a single keystone permanently kills the asymmetry class â€” the "get it right" fix, not another patch.
- **D2 â€” Handoff richness â†’ Persist docs + write HANDOFF.md:** The handoff persists the source docs and writes HANDOFF.md (real persisted paths + "read these first" + the correct skill + the source session's cached summary if present); `NEXT-PROMPT.md` references them; and an advance triggers a BACKGROUND (non-blocking) source-stage summary.
- **Member documents:** The session comprises a frozen Master Plan (design) and a Foreman-ready Implementation Plan.
- **Framing:** Decisions are presented as Crucible-locked choices for John's approval/adjustment, consistent with the planning-stage (Crucible) role of the trio.
- ## Anchor R&D Surface v11 â€” "Reliable Trio Handoff" â€” Master Plan summary
- **Objective / North Star**
- The locked North Star is that advancing any trio stage in the LIVE flow (researchâ†’plan, planâ†’build) reliably **primes the next stage**: the source stage's produced docs are persisted into the project, the next session opens with a REAL prompt naming the actual persisted doc paths plus a "read these first" instruction, a HANDOFF.md / handoff summary is written, and the sessions are linked.
- The deeper objective (the inclusion test) is that there is **ONE handoff path, not four half-wired ones** â€” every advance routes through the same mechanism.
- A standing constraint is that the fix is **VERIFIED against the real worktree-only flow**, so a "tests green but live broken" regression cannot recur.
- **Locked decisions (Crucible â€” for John's approval/adjustment)**
- **D1 â€” Patch vs unify â†’ Unify:** all advance paths call ONE shared `prepare_stage_handoff` keystone. Rationale: the bug was an un-mirrored one-line patch; a single keystone permanently kills the asymmetry class and is the "get it right" fix rather than another patch.
- **D2 â€” Handoff richness â†’ Persist docs + write HANDOFF.md:** the handoff persists the source docs and writes a HANDOFF.md carrying the real persisted paths, a "read these first" instruction, the correct skill, and the source session's cached summary if present; `NEXT-PROMPT.md` references those docs; and a **background source-stage summary is triggered on advance** (non-blocking).
- **Document set**
- The session comprises two member documents: the Master Plan (frozen design) and the Implementation Plan (Foreman-ready).
- *Note: the anchor text for both the North Star and decision D2 is truncated mid-sentence in the source material, so the closing rationale of D2 and the full enumeration after "Every advance â€”" are not fully captured here.*

## Files

- [Anchor R&D Surface v11 — "Reliable Trio Handoff" — Master Plan (frozen design)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v11%2FMASTER-PLAN.md)
- [Anchor R&D Surface v11 — "Reliable Trio Handoff" — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v11%2FIMPLEMENTATION-PLAN.md)
