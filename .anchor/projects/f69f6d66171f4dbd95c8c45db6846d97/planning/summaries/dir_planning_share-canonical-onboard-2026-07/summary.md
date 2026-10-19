# Master Plan (draft)

*Lane: planning · validated, cached summary*

**When run:** 2026-07-28

**What was asked:** Master Plan (draft)

**North Star:** - Auto-install every CLI (Claude/agy/Grok) beyond detect + fix links (Python is the hard dependency). - Merging Foundry + trio monorepos in this effort. - Auto-merge of recipient friction into skill sources. - Shipping author journals or personal data. - Open-source license / public GitHub as a gate for this build. - Moving Gandalf: already at Foundry `skills/gandalf` (Claude path is junction only).

## Actions & files produced

- Master Plan (draft)
- Implementation Plan â€” Canonical SKILLS_ROOT + full A/B onboard
- IMPLEMENTATION-PLAN-APPROVAL

**Effort:** imported — no run metrics

## Goal & key decisions

- This planning session forged and locked the plan for the "Canonical SKILLS_ROOT + full A/B onboard" effort — the work of making Anchor's skills genuinely agent-independent and giving strangers a real guided install. Starting from the North Star John locked on 2026-07-24, the session produced a Master Plan establishing that all product skills should live once under a single `SKILLS_ROOT` on a recipient's machine, with Claude, Grok, Gemini, and Anchor acting only as thin adapters (junctions or pointers, never second copies), so every host lists the identical skill portfolio. The plan also defines the two onboarding packages: Package A installs just the skills with governance and multi-host registration, while Package B adds a full Anchor install that ends with the service actually running and a desktop icon pointing at the local dashboard. It records firm guardrails — journals always land under each skill's own folder for Foundry sleep, friction share-back stays opt-in and fail-closed, existing GREEN share modules get extended rather than duplicated, and no open-source license ships. The session then produced the Implementation Plan, decomposing the work into eight Foreman waves (beginning with a skills-root registry plus a portfolio-equality oracle designed to fail on false greens, then the SKILLS_ROOT install and journal-path law); notably, the planning engine stalled mid-Shark-challenge after a dry round, so the final plan was synthesized for explicit human lock rather than auto-approved. John approved it on 2026-07-24, closing the session with a signed approval record handing the build off to a Foreman multi-wave run on `C:\dev\Anchor`.

## Files

- [Master Plan (draft)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FMASTER-PLAN.md)
- [Implementation Plan â€” Canonical SKILLS_ROOT + full A/B onboard](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FIMPLEMENTATION-PLAN.md)
- [IMPLEMENTATION-PLAN-APPROVAL](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FIMPLEMENTATION-PLAN-APPROVAL.md)
