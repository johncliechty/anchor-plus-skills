# Master Plan (APPROVED) — Shareable Anchor + Skills

*Lane: planning · validated, cached summary*

**When run:** 2026-07-28

**What was asked:** Master Plan (APPROVED) — Shareable Anchor + Skills

## Actions & files produced

- Master Plan (APPROVED) — Shareable Anchor + Skills
- Success criteria

**Effort:** imported — no run metrics

## Goal & key decisions

- This planning session produced the approved Master Plan for making Anchor and its skill suite shareable with other people. The session locked in a plan (approved by John on 2026-07-23) to ship two distribution packages — a Skills-only bundle and a combined Anchor+Skills bundle, with a standalone Anchor package explicitly ruled out — aimed at two audiences: public consumers who download and use the tools read-only, and invited collaborators who work through branches and pull requests. The plan is organized into seven phases that build on the already-proven share-distro machinery rather than creating a second packaging stack: first mapping what existing GREEN modules can be reused and hard-coupling the package contracts, then extending the no-leak scrubbed-distro pipeline with freeze-at-tag provenance for vendored skills, installing a governance pack and journal hooks so recipients inherit the operating culture, building a plain-English terminal onboarding flow (home directory choice, subscription seat probes, a desktop icon that opens the local dashboard, and honest readiness stamps), designing an opt-in and fail-closed friction-feedback channel using de-identified install keys, establishing the dual-audience git topology with one-way public mirrors, and finally proving everything through CI matrices and a stranger-install end-to-end test on a clean Windows VM. The session also drew clear boundaries: actual shipping stays gated behind the concurrent skill-update run merging, declared freeze tags, and John's explicit go-ahead, while Tailscale remote access, Foundry sleep automation, an OpenAI seat, and any SaaS hosting are deferred by name out of v1 scope.
- This was a Crucible planning session (run at full depth) that produced the approved master plan for making Anchor and its skill suite shareable with other people — the plan John signed off on 2026-07-23, now living in `planning/share-anchor-skills-2026-07/`. The session locked the product shape and its success criteria: ship exactly two packages — a Skills-only bundle and an Anchor+Skills bundle, never Anchor by itself — serving two audiences (public consumers who download and use, and invited collaborators who branch and PR), with a no-leak scrubbed distribution built by reusing the already-proven share-distro machinery rather than a second packaging stack. It then laid out a seven-phase roadmap to get there: first mapping what already exists and freezing the package and capability contracts, then hardening the leak-scrubbed freeze-at-tag packaging, installing a governance pack and journal hooks so recipients inherit the operating culture, building a plain-English terminal onboarding flow (home directory choice, subscription seat probes, a desktop icon that opens the local dashboard, honest "degraded" readiness stamps), designing an opt-in, fail-closed friction-feedback channel keyed by a de-identified install ID, setting up the dual-audience git topology with one-way public mirrors, and finally proving it all with stranger-install end-to-end tests on a clean machine. Crucially, the plan separates plan-complete from ship-allowed: nothing gets vendored or published until the concurrent skill-update run merges, freeze tags are declared, and John gives an explicit go-ahead — and it names its own exclusions up front (Foundry sleep automation, Tailscale remote access, API-key-first seats, SaaS hosting, and any rebuilding of skill internals are all out of scope for v1).

## Files

- [Master Plan (APPROVED) — Shareable Anchor + Skills](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-anchor-skills-2026-07%2FMASTER-PLAN.md)
- [Success criteria](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-anchor-skills-2026-07%2FIMPLEMENTATION-PLAN.md)
