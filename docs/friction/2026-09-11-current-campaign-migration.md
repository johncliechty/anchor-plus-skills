# Current campaign migration: delivery and follow-up

Canonical intake: `2026-09-11-03-mba-summary-retries-collide-with-refinem`.

The MBA, Math 541 and Econ 588 campaigns were adopted into the installed refinement ledger while preserving 500 original events and 88 original steps. Live current/history opening exposed automatic summary attempts producing failure handoffs during view recording, causing HTTP409 sequence-conflict. Actual job timestamps and prompts corrected an initial historical-backfill diagnosis.

Root cause fixed through a formal Foundry cycle: parent serialization converts absent expected artifacts to an empty list; the read-only ChatGPT adapter rejected that list although it accepted None. Empty normalization now agrees, while workspace-write without named artifacts still refuses before preflight or a paid seat. Grok READY, 112 tests passed, two host symlink skips. Guarded installation preserved pre-existing owner edits. Six normal summary jobs then succeeded; actual current/history links and current status render acknowledgements passed.

Further improvement remains open: automatic project/session metadata summaries should have an explicit producer purpose so they do not enter the teaching-work-product handoff queue. Calls should carry the correct project attribution, and summary extraction should respect canonical AGENTS/Face project identity rather than treating a thin CLAUDE pointer as the project title. Do not silently suppress real work-product handoffs or infer billing totals. Acceptance: opening a root-registered and a nested campaign creates no false deliverable-review obligations, preserves legitimate completion handoffs, and shows attributed usage with honest coverage.

Run evidence and the formal improvement plan: `C:/dev/Skill Foundry/planning/steward-refinement-2026-09-10/campaign-migration-20260911/`. No Crucible or Foreman engine ran; comparative speed remains unmeasured.
