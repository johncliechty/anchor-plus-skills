---
name: zombie-hunter
description: The automated background sweeper and process lifecycle enforcer for the Anchor service. It ensures zero orphaned sub-agents (zombies) via OS-level guarantees and cryptographically secure user-space polling.
---
# Zombie Hunter — The Lifecyle Sentinel

> Persona tier: AUTOMATED SWEEPER. Substrate: Python background thread inside the Anchor service.
> This skill defines the strict architectural protocol for hunting and destroying orphaned sub-agents (zombies) without ever risking a false positive on a legitimate user process.

## The Icon
**The Event Horizon Prism:** A perfectly symmetrical, dark-mode isometric prism with a matte black singularity at its center. Faint, glowing crimson data-threads spiral down into the void, symbolizing the silent, inescapable cleanup of rogue processes.

## The Core Philosophy (Gandalf's Law)
Relying on a Process ID (PID) alone to kill a background task is an architectural anti-pattern and a loaded gun. The Windows OS aggressively recycles PIDs. A naive polling loop will eventually commit a "Doppelgänger Kill" (nuking a user's manual, unrelated server because it inherited a dead agent's PID). 

**The Zombie Hunter never guesses.** It relies on OS-kernel guarantees first, and Cryptographic Genesis Tokens second.

## Phase 1: The OS Kernel Guarantee (Primary Defense)
The Zombie Hunter's best weapon is not polling—it is prevention.
1. Every time Anchor spawns a long-running PTY or sub-agent (e.g., `claude.exe`, `python.exe`), it must wrap the process in a **Windows Job Object** configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
2. This ensures that if the Anchor service crashes, is restarted by NSSM, or is forcefully killed, the Windows OS kernel instantly and atomically terminates the entire process tree (preventing "Grandchild Zombies").

## Phase 2: Cryptographic Zero-False-Positive Polling (Logical Reaping)
For tasks that must be reaped while Anchor is still alive (e.g., a logical session timeout, or a manual cancellation via the dashboard), the Zombie Hunter wakes up every 10 minutes to synchronize the state.

1. **The Genesis Token:** When Anchor spawns a session, it injects a cryptographically random UUID into the child's environment variables (e.g., `ANCHOR_SESSION_ID=550e8400-e29b-41d4-a716-446655440000`) or its command line arguments.
2. **The Composite Key:** Anchor's `session_registry.py` stores the `[PID, Creation Time, UUID]`.
3. **The WMI/psutil Sweep:** Every 10 minutes, the hunter thread queries running processes.
4. **The Assertion Gate:** Before issuing a kill, the hunter strictly asserts:
   - Does the PID match?
   - Does the Process Creation Time match exactly? (Defeats PID recycling).
   - Does the environment block or command line contain the exact `ANCHOR_SESSION_ID`? (The ultimate failsafe).
5. **The Sniper Kill:** If the token matches but the session is marked "dead" or "cancelled" in Anchor's registry, the hunter executes `taskkill /PID <orphan-pid> /T /F` to destroy the entire tree. If the token is missing, the hunter ABSTAINS and touches nothing.

## Usage journal (sleep-loop feed — append after every REAL run)

At the end of any real (non-test) run of this skill, append ONE entry to
`journal/` in this skill folder as `NNNN-<slug>.md` (next number; APPEND-ONLY —
a correction is a new entry, never an edit). Keep it under ~15 lines, honest over
polished, with the 7 canonical fields (see
`planning/portfolio-program/src/journal.mjs`):

- `id`: NNNN-<slug>
- `skill`: <this skill>@<version or date>
- `situation`: the recurring situation class (the sleep loop's cluster key)
- `context`: the distinct project/session it ran in (cross-context corroboration key)
- `observation`: what was learned — the candidate-lesson signal
- `outcome`: the genuine result (worked | friction | failed | refused)
- `provenance`: genuine-execution | seeded (only genuine-execution corroborates)

No journal entries → the sleep loop has nothing to learn from. This block is the
capture end of the Foundry's improvement loop.
