**Skill Foundry (Phase 1)**
Skill Foundry is a premium, local-first agentic ideation and skill-creation platform, serving as the evolution of the original Sleep Engine. 

**1. UX/UI Architecture:** Built on a mathematically rigid CSS Grid (320px left panel, `1fr` right panel) featuring the pitch-black "Anchor" aesthetic. The right panel maintains a strict vertical hierarchy of expandable tiles: 1. North Star / Description, 2. Core Capabilities, 3. Evolution History, and 4. The Knowledge Graph.

**2. The Command Overlay:** The "Create New Skill" terminal utilizes the 2026 Native Popover API to launch a properly scaled, authoritative overlay that takes over the primary viewing area without breaking the underlying grid constraints.

**3. The Skill Foundry Skill (The Meta-Skill):** The platform includes the flagship "Skill Foundry" skill, which orchestrates the creation pipeline:
   1) Intakes user intent. 
   2) Invokes Gandalf to interrogate the local knowledge base via a Similarity Matrix to modify an existing skill or build from scratch. 
   3) **Invokes researchPrime to scour the web/literature for best-in-class workflows and ideas related to the skill intent, proposing them for inclusion.**
   4) Invokes Crucible to forge the plan, strictly enforcing the Skill Foundry data structure and Markdown/YAML formatting. 
   5) Automatically registers the completed skill into the Anchor framework.

**4. Data Architecture & The Sleep Engine:** A dual-state system. Plaintext Markdown with YAML frontmatter acts as the git-versioned source of truth. An ephemeral SQLite (`sqlite-vec`) database provides the semantic routing and graph querying engine. Crucially, the platform runs a persistent **Sleep Engine** that manages background journaling, continuous learning, and telemetry, actively wiring every newly created skill into this intelligence loop.
