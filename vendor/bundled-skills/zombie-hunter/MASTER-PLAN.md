# NORTH STAR (LOCKED)

> To build a robust, zero-false-positive background sweeper that guarantees the complete termination of orphaned sub-agents, seamlessly integrated with a sleek, uncomplicated "Prism Matrix" reporting GUI on the Anchor dashboard. It will employ a dual-layer defense: first, relying on Windows OS Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) to atomically destroy process trees upon parent death, and second, utilizing a cryptographically secure 10-minute polling loop that positively identifies tasks via injected UUID environment variables. The reporting GUI will surface this data in a minimalist modal overlay, visualizing the status of session IDs, cryptographic matches, running projects, and active background swarms (including autonomous Foreman runs).

# STAGE 1: MASTER PLAN

## Architecture Overview
The Zombie Hunter is divided into two primary domains that coordinate closely with the existing `<path> core:
1. **The Kernel Sentinel (Process Spawning / Job Objects):** Integration with `job_runner.py` and `pty_manager.py` to ensure all spawned agent processes are attached to a Windows Job Object configured to terminate children upon parent exit.
2. **The Cryptographic Sweeper & Prism GUI (Event Loop & Dashboard):** A background thread injected into `anchor.py` that periodically polls running PIDs, matches them via `WMI` against UUIDs in `session_registry.py`, reaps orphans, and surfaces the live data to the Option 2 "Glass Prism Modal" on the Anchor dashboard.

## Technical Strategy & Shark-Tank Resolution
*   **Analyst Review:** Polling via WMI can be expensive on Windows.
*   **Contrarian Review:** If WMI is too slow, relying on it every 10 minutes might stutter the main Anchor event loop.
*   **Skeptic Review:** UUID injection might leak into sub-process environments where it's not expected.
*   **Synthesizer / Judge Resolution:** The polling loop MUST run in a fully detached daemon thread, sleeping for 10 minutes between sweeps to guarantee zero blocking of the Anchor UI. WMI will only be queried for `python.exe` and `claude.exe` to minimize the search space. UUID injection will use a highly specific key (`ANCHOR_SESSION_ID_CRYPT_TOKEN`) to prevent accidental collision.

## Phased Approach
*   **Phase 1: Foundation (The Kernel Guard & UUID Injection)** - Modify `pty_manager.py` to inject UUIDs and attach Job Objects.
*   **Phase 2: The Sweeper Thread** - Build the `zombie_hunter.py` daemon thread that queries WMI and coordinates with `session_registry.py`.
*   **Phase 3: The Prism Matrix GUI** - Modify `dashboard_api.html` (and relevant dashboard files) to include the Glass Prism Modal reporting interface.
