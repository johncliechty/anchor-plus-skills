# Skill Foundry - Master Plan (Crucible Stage 1)

*Lane: planning · validated, cached summary*

**When run:** 2026-07-10

**What was asked:** Skill Foundry - Master Plan (Crucible Stage 1)

## Actions & files produced

- Skill Foundry - Master Plan (Crucible Stage 1)
- Skill Foundry - Implementation Plan (Crucible Stage 2)

**Effort:** imported — no run metrics

## Goal & key decisions

- ## Skill Foundry — Master Plan (Crucible Stage 1) — Grounded Summary
- UI is a strict CSS Grid (`320px 1fr`) — deemed sufficient without a heavy component framework.
- The knowledge graph is rendered as a **Poincaré Map (hyperbolic tree graph)** styled as a starry constellation, with `d3.zoom` that reveals labels on zoom and "breaks open" into a Deep Expander modal.
- The "Create New Skill" terminal uses the **2026 Native Popover API** to take over the viewport.
- **Markdown/YAML on the filesystem is the sole git-versioned source of truth**; an ephemeral `sqlite-vec` DB is hydrated from it on boot and kept in sync via file watchers.
- The platform sequences long-running sub-agent invocations (Gandalf → researchPrime → Crucible) without dropping state.
- **Popover focus/scroll loss** during large terminal output → trap focus + `overscroll-behavior: contain`, overlay full viewport (`100vw/100vh`).
- **Sleep Engine blocking the UI thread** → run journaling/telemetry/vector generation in a background Web Worker or Node child process; file watcher invalidates and re-embeds externally edited Markdown.
- **Pipeline corruption if a mid-pipeline step (e.g. researchPrime) fails** → **atomic writes**: the skill stays in memory/temp-file through Intent → Gandalf → researchPrime → Crucible and is only written to disk/registered in Anchor on a successful Crucible exit.
- **Phased plan (§4):** Phase 1 — dual-state data architecture + CSS Grid scaffold with 4 right-panel tiles; Phase 2 — Popover command overlay + Sleep Engine loop; Phase 3 — the 5-step meta-skill pipeline with atomic commit.
- **Gate command:** `node --test test/index.mjs`.
- **Foreman anti-vacuous-GREEN mandate:** every wave must add a `test/` file that actively imports and exercises the wave's code, or Foreman rejects the wave.
- **Wave 1 — UX/UI Grid & Anchor Aesthetic:** 320px/1fr grid, pitch-black palette, 4 expandable tiles (North Star, Capabilities, Evolution History, Knowledge Graph), D3.js Poincaré constellation graph with zoom-to-label + Deep Expander modal; DOM-node test required.
- **Wave 2 — Dual-State Data Architecture:** parse all `.md` skills into SQLite on start, real-time file watcher updates; test verifies watcher + hydration.
- **Wave 3 — Command Overlay & Conversational Orchestrator:** Native Popover terminal (focus-trapped, self-scrolling) + backend platform-agnostic orchestrator (chat state machine, intake, custom icon selection, opt-in adversarial "interview grill" mode) + a **Canary Validation Runner with automated state rollback** on verification failure.
- **Wave 4 — Sleep Engine Background Loop:** background worker polling/logging telemetry and skill invocations into the local store; test verifies loop intervals.
- **Wave 5 — 5-Step Meta-Skill Pipeline:** an `--intent "quoted string"` argument drives Intent → Gandalf (interrogation) → researchPrime (web/literature scour) → Crucible (plan forging) → Anchor Registry (atomic Markdown write); test mocks the sub-agent pipeline and verifies the atomic write.
- **"Skill Foundry - Master Plan (Crucible Stage 1)"** — the Stage 1 Master Plan artifact.
- **"Skill Foundry - Implementation Plan (Crucible Stage 2)"** — the Stage 2 Implementation Plan artifact.

## Files

- [Skill Foundry - Master Plan (Crucible Stage 1)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=foundry-gui%2Fplanning%2Fcrucible%2FMASTER-PLAN.md)
- [Skill Foundry - Implementation Plan (Crucible Stage 2)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=foundry-gui%2Fplanning%2Fcrucible%2FIMPLEMENTATION-PLAN.md)
