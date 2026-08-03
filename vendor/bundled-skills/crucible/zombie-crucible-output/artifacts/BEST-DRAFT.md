# Crucible-planned project — Implementation Plan (Foreman-ready)

test-command: node --test test/

**North Star:** Transform Zombie Hunter from an Anchor-specific utility into a global, system-wide AI process sentinel. 
Key objectives:
1. System-Wide Detection: Expand scope to monitor and track all AI-related processes across the OS (including Anchor, VS Code AI swarms, raw terminal processes, and cowork).
2. GUI Enhancements: Add a manual "Relaunch Sweep" button to the GUI for on-demand, fresh process updates.
3. Historical Forensics: Introduce a retrospective analysis feature that identifies evidence of past zombie swarms that consumed resources but evaded detection.
4. Human-in-the-Loop Approval: Replace automated kills with a human-facing approval workflow that freezes the rogue swarm. Include a toggleable "Show Context" button in the GUI to reveal (and hide) the detailed, human-readable explanation of what the process is and why it should be neutralized.

## Success criteria
- System-wide detection across Anchor, VS Code, terminals, and cowork is functional
- GUI contains a working Relaunch Sweep button
- Forensics feature successfully identifies past undetected zombies
- Human-in-the-loop freeze workflow is active with a Show Context toggle

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — System-Wide Process Discovery and Fingerprinting Core

**Intent:** Implement OS-level discovery mechanisms using robust data sources, specify the required permission models, and mandate explicit fingerprinting heuristics (signatures, process chains) for identifying AI swarms. Resolve self-sabotage risks by establishing an immutable OS-binary allow-list.

**Deliverables:** OS process discovery module leveraging WMI (Windows Management Instrumentation) and process enumeration APIs; background daemon with automatic crash-recovery (e.g., Windows Service auto-restart
<truncated 3568 bytes>
Approvals, Context Display, and Lifecycle Management

**Intent:** Implement the human-facing approval workflow with hierarchical swarm grouping, detailed context explanations derived from the extraction architecture, and complete post-freeze lifecycle actions in the GUI.

**Deliverables:** Collapsible Tree View for grouping Swarms; single parent "Freeze" button; "Show Context" inline accordion (auto-closing others); human-readable violation explanation engine mapping extracted telemetry (Wave 3) to plain-English context; post-freeze action buttons ("Resume" and "Kill").

**Depends on:** Wave 3, Wave 4

**done-when:** The user can expand a swarm, view the real extracted context explanation, approve freezing, and manage the post-freeze lifecycle.

- **Given** A detected rogue AI swarm is displayed in the GUI, **when** The user clicks the "Show Context" toggle to read the violation, clicks "Freeze", and later clicks "Kill", **then** The inline accordion displays the real extracted telemetry (env vars, files touched) explaining why it should be neutralized, the orchestrator suspends it safely, and finally permanently terminates it via the complete operator lifecycle.

## Wave 6 — Historical Forensics UI and Resource Bounding

**Intent:** Expose the retrospective analysis feature in the GUI while strictly bounding the offline analysis background thread's resource consumption.

**Deliverables:** Offline analysis background thread capped at 5% CPU, 250MB RAM, 1-hour chunk windows; retrospective analysis GUI view for displaying historical zombies identified from ETW telemetry.

**Depends on:** Wave 3, Wave 5

**done-when:** The system can analyze historical ETW telemetry within strict resource bounds and display identified past zombies in the GUI view.

- **Given** Historical telemetry data exists in the database, **when** The forensic analysis thread runs its chunked retrospective query, **then** It identifies past resource-consuming swarms and displays them in the GUI without exceeding 5% CPU or 250MB RAM limits.