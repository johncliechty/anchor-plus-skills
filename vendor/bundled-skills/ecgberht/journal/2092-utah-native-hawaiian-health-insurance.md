# 2092 — Steward Campaign Orchestration for Multi-Run researchPrime + Gandalf Health Insurance Plan

- **Date / skill / tier**: 2026-10-14 · `ecgberht` (Steward) · Standard (`ecgberht.mjs` / `engine/index.mjs`, 4 roadmap steps S1..S4, session model Gemini 3.1 Pro)
- **Task**: Set up and drive a 4-step campaign (`S1` researchPrime Run 1 -> `S2` Gandalf Run 1 -> `S3` researchPrime Run 2 + Gandalf Run 2 -> `S4` Final Plan + PDF reading copy) to completion.
- **Outcome**: All 4 steps proposed, transitioned through `active` -> `done` with `--goal-reread reaffirmed` receipts (`goal_flip` events recorded), and closed cleanly on `roadmap.json` and `strip.json`.
- **What worked**: Pinning `current_step_id`, `next_recommended` (<=15 words), and `why_next` (<=20 words) on `strip.json` before each `status_flip` to `done` satisfied `demandClose` / `demandSpineForClose` cleanly.
- **What failed / friction**: Initial `roadmap-propose` passed `--tier Heavy --area researchPrime`, which refused with `invalid_tier` because `tier`/`area` on `roadmap-propose` are reserved for normalized portfolio goal tags rather than skill model tiers.
- **Workaround / fix**: Omitted `--tier` and `--area` on campaign step proposals (`tool_depth_cell: "Heavy / FULL"` belongs on `strip.json`, not `step_create`), which succeeded immediately.
- **Proposed skill change**: Clarify in `SKILL.md` CLI examples that `--tier` on `roadmap-propose` is the portfolio goal tier enum, while skill model/depth cell (`Heavy / FULL`) is recorded on `strip.json` (`tool_depth_cell`).
