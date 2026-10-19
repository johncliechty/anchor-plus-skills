# Skill Foundry - Master Plan (Crucible Stage 1)

## 1. Assumption Map
- **CSS Grid Supremacy:** A strict `grid-template-columns: 320px 1fr` layout is sufficient for all primary navigation and content needs without requiring a heavy component framework.
- **Knowledge Representation:** The knowledge graph MUST be visualized as a Poincaré Map (Hyperbolic Tree Graph) mimicking a starry constellation. It must implement d3.zoom camera manipulation that zooms dynamically into larger concept nodes, revealing text labels, and eventually "breaking open" into a Deep Expander modal.
- **Native Popover API Suitability:** The 2026 Native Popover API can cleanly take over the viewport for the "Create New Skill" terminal without destabilizing the underlying grid's dimensions or stacking contexts.
- **Dual-State Consistency:** Ephemeral `sqlite-vec` can be robustly hydrated from the filesystem (Markdown/YAML) on startup and kept in sync via file watchers, ensuring Markdown remains the sole git-versioned source of truth.
- **Pipeline Orchestration:** The platform can reliably sequence long-running sub-agent invocations (Gandalf → researchPrime → Crucible) without dropping state.

## 2. Premortem (What Could Go Wrong)
- **The Popover Trap:** The Native Popover API overlay loses focus or fails to scroll properly when the terminal output grows massively during a skill creation pipeline.
- **Sleep Engine Blocking:** The background journaling and continuous learning loop of the Sleep Engine blocks the main UI thread during heavy telemetry processing or graph querying.
- **State Drift:** If a skill is manually edited via external editor, the SQLite vector database becomes stale, leading to incorrect semantic routing.
- **Pipeline Failure Recovery:** A failure in step 3 (researchPrime) of the 5-step pipeline leaves a corrupted or half-finished skill in the Anchor Registry.

## 3. Ideation & Mitigation (Shark-Tank Consensus)
- **Skeptic (State Drift & Sleep Engine):** *If SQLite is ephemeral, when does it load? Does the Sleep Engine block the UI?*
  - **Resolution:** Hydrate SQLite purely from Markdown on boot. Use a background Web Worker (or Node child process, depending on the environment) for the Sleep Engine to perform journaling, vector generation, and telemetry analysis so the main thread remains untouched. A file watcher must immediately invalidate and re-embed any externally edited Markdown files.
- **Contrarian (Popover API):** *Native Popovers are great, but can they handle a complex interactive terminal overlay?*
  - **Resolution:** Yes, provided we explicitly manage `overscroll-behavior: contain` and trap focus within the popover. The popover will overlay the entire grid (`width: 100vw; height: 100vh`) but visually scale to maintain the pitch-black "Anchor" aesthetic.
- **Analyst (Pipeline Resilience):** *The 5-step pipeline is brittle if one step fails.*
  - **Resolution:** Implement atomic writes. The skill is held in memory/temp-file during Intent → Gandalf → researchPrime → Crucible. It is only written to the Markdown/YAML filesystem (and thus registered in Anchor) upon a successful Crucible exit code.

## 4. Phased Plan
- **Phase 1: Foundation & Data Architecture**
  - Implement the dual-state system (Markdown/YAML source of truth + ephemeral `sqlite-vec` in-memory routing).
  - Scaffold the CSS Grid (320px / 1fr) with the pitch-black Anchor aesthetic and the 4 core expandable tiles on the right panel.
- **Phase 2: The Command Overlay & Sleep Engine**
  - Integrate the 2026 Native Popover API for the authoritative terminal overlay.
  - Implement the background Sleep Engine loop (Web Worker / background thread) for journaling and telemetry.
- **Phase 3: The Flagship Meta-Skill Pipeline**
  - Build the orchestration logic for the 5-step pipeline (Intent → Gandalf → researchPrime → Crucible → Anchor Registry) with atomic commit semantics.
