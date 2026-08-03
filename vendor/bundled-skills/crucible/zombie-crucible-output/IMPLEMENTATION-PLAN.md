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
- Human-in-the-loop kill workflow is active with a Show Context toggle

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — System-Wide Process Discovery and Cryptographic Allowlist

**Intent:** Implement the OS-level discovery mechanism using strict AI heuristics and protect critical OS components.

**Deliverables:** OS process discovery module; AI heuristic rules (agy, trio, claude, LLM API detection); Cryptographic Allowlist for Microsoft signed binaries.

**Depends on:** —

**done-when:** A test script can successfully enumerate running AI processes system-wide and categorically filter out Microsoft-signed processes.

- **Given** A system running an AI process (e.g., node.js running trio) and a Microsoft-signed process, **when** The discovery module scans the system, **then** It flags the trio process based on strict signatures and ignores the Microsoft process via the cryptographic allowlist

## Wave 2 — Local Telemetry Daemon and Encrypted SQLite

**Intent:** Build the background daemon to track AI processes and persist telemetry securely while preventing DB bloat.

**Deliverables:** Local SQLite database setup; at-rest database encryption; suspicious tier logging logic (partial AI-like behavior); sanitization and retention policies.

**Depends on:** System-Wide Process Discovery and Cryptographic Allowlist

**done-when:** The daemon runs continuously, receives discovered process data, logs suspicious activities, and stores them securely in the encrypted database.

- **Given** The daemon is active and a Node process exhibits suspicious network activity, **when** The discovery module reports the process to the daemon, **then** The daemon logs it to the encrypted SQLite database as a "suspicious tier" entry without bloating standard telemetry

## Wave 3 — Secure IPC and Soft Freeze State Machine

**Intent:** Establish a secure boundary and implement the suspension mechanism to safely neutralize rogue swarms without crashing parent applications.

**Deliverables:** Windows Named Pipes with strict user ACLs; Soft Freeze module (network blocking, new child process blocking); timeout/fail-safe suspension state

**Depends on:** —

**done-when:** Clicking the Relaunch Sweep button queries the daemon via IPC and returns fresh process data without blocking the user interface.

- **Given** The user opens the GUI and clicks "Relaunch Sweep", **when** The background daemon is queried via IPC for fresh process data, **then** An async spinner displays until the updated process list is returned and rendered, keeping the UI fully responsive

## Wave 4 — Bulk Swarm Approvals and Context Display

**Intent:** Implement the human-facing approval workflow with hierarchical swarm grouping and context explanations.

**Deliverables:** Collapsible Tree View for grouping Swarms; single parent "Kill" button; "Show Context" inline accordion (auto-closing others); human-readable violation explanation template generator.

**Depends on:** Human-in-the-Loop GUI Foundation and Relaunch Sweep

**done-when:** The user can expand a swarm, view the generated context explanation, and approve termination for the entire swarm via a single click.

- **Given** A detected rogue AI swarm is displayed in the GUI, **when** The user clicks the "Show Context" toggle and then the "Kill" button on the parent row, **then** The inline accordion explains the explicit heuristic rule violated, and the Soft Freeze/Kill command is dispatched for the entire unified swarm

## Wave 5 — Historical Forensics Analysis and UI

**Intent:** Introduce retrospective analysis to find past undetected zombies using bounded offline queries.

**Deliverables:** Offline analysis background thread (capped at 5% CPU, 250MB RAM, 1-hour chunk windows); forensics correlation logic; retrospective analysis GUI view.

**Depends on:** Bulk Swarm Approvals and Context Display

**done-when:** The system can analyze historical telemetry within strict resource bounds and display identified past zombies in the GUI view.

- **Given** Historical telemetry data exists in the encrypted database, **when** The forensic analysis thread runs its chunked retrospective query, **then** It identifies past resource-consuming swarms and displays them in the GUI without exceeding 5% CPU or 250MB RAM limits
