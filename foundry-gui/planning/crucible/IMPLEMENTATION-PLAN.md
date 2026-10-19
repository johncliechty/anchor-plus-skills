# Skill Foundry - Implementation Plan (Crucible Stage 2)

gate-command: node --test test/index.mjs

## Foreman-Ready Wave Decomposition

**CRITICAL MANDATE FOR ALL WAVES:** To pass Foreman's strict "vacuous-GREEN" guard, you MUST write a corresponding test file in the `test/` directory (e.g., `test/ui.test.mjs`) that actively imports and exercises the specific code you wrote for your wave. If you change code but do not write a test that reaches it, Foreman will reject the wave.

## Wave 1: UX/UI Grid & Anchor Aesthetic
- **Description:** Implement the strict mathematical CSS Grid layout and the pitch-black "Anchor" aesthetic, including the 4 vertical expandable tiles and the D3.js Poincaré Knowledge Graph.
- **Acceptance Criteria (Done-When):** The UI renders a `320px` left panel and a `1fr` right panel. The right panel contains four expandable tiles (North Star, Capabilities, Evolution History, Knowledge Graph). The color palette adheres strictly to the pitch-black Anchor design system. The Knowledge Graph tile MUST house a D3.js Poincaré Map (Hyperbolic Tree Graph) styled as a starry constellation. It must support d3.zoom camera manipulation that zooms into nodes, dynamically revealing node labels based on scale, and breaking open into a Deep Expander modal upon node click. You must write a frontend test that verifies the DOM nodes.

> PROMPT: Implement the strict mathematical CSS Grid layout and the pitch-black "Anchor" aesthetic, including the 4 vertical expandable tiles and the D3.js Poincaré Knowledge Graph. The code should already be present, just ensure it passes tests.

## Wave 2: Dual-State Data Architecture
- **Description:** Build the system that reads Markdown + YAML files from the filesystem and hydrates an ephemeral `sqlite-vec` database for semantic querying.
- **Acceptance Criteria (Done-When):** On application start, all `.md` files in the skills directory are parsed and loaded into SQLite. A file watcher detects changes to these files and updates the database in real-time. You must write a test verifying the watcher and DB hydration.

> PROMPT: Build the system that reads Markdown + YAML files from the filesystem and hydrates an ephemeral `sqlite-vec` database for semantic querying. Ensure real-time updates via a file watcher.

## Wave 3: The Command Overlay & Conversational Orchestrator
- **Description:** Implement the terminal drawer utilizing the 2026 Native Popover API, and build the backend platform-agnostic Conversational Orchestrator.
- **Acceptance Criteria (Done-When):** Triggering the "Create New Skill" action opens a Native Popover that takes over the primary viewing area. The popover traps focus, contains its own scrolling, and successfully overlays the CSS Grid. On the backend, the Conversational Orchestrator must be implemented with its chat state machine, intake, custom icon selection, and opt-in/opt-out adversarial interview grill mode. A Canary Validation Runner with automated state rollback on verification failure must also be included. Tests must verify the popover attribute and the core conversational/canary logic.

> PROMPT: Implement the terminal drawer utilizing the 2026 Native Popover API (overlay, focus trapping). Additionally, build the backend platform-agnostic Conversational Orchestrator (chat state machine, intake, icon selection, adversarial interview mode) and the Canary Validation Runner (with automated state rollback). Ensure tests cover both UI and backend systems.

## Wave 4: The Sleep Engine Background Loop
- **Description:** Scaffold the persistent background loop that handles journaling, continuous learning, and telemetry tracking.
- **Acceptance Criteria (Done-When):** A background worker continuously polls and logs system telemetry and skill invocations into the local store. Write a test verifying the loop intervals.

> PROMPT: Scaffold the persistent background loop that handles journaling, continuous learning, and telemetry tracking. A background worker must continuously poll and log telemetry into the local store.

## Wave 5: The 5-Step Meta-Skill Creation Pipeline
- **Description:** Orchestrate the flagship "Skill Foundry" skill pipeline.
- **Acceptance Criteria (Done-When):** A user intent (passed via a `--intent "quoted string"` argument) submitted via the terminal successfully triggers a sequential flow: Intent → Gandalf (interrogation) → researchPrime (web/literature scour) → Crucible (plan forging) → Anchor Registry (Markdown write). Write a test mocking the sub-agent pipeline and verifying the atomic Markdown write.

> PROMPT: Orchestrate the 5-step Meta-Skill Creation Pipeline. Wire up the sequential flow from Intent (extracted from --intent "string") to Gandalf, researchPrime, Crucible, and finally the Anchor Registry Markdown write.
