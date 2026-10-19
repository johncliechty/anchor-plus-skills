# crucible

*Lane: planning · validated, cached summary*

**When run:** 2026-06-28

**What was asked:** crucible

**North Star:** > To build a robust, zero-false-positive background sweeper that guarantees the complete termination of orphaned sub-agents, seamlessly integrated with a sleek, uncomplicated "Prism Matrix" reporting GUI on the Anchor dashboard. It will employ a dual-layer defense: first, relying on Windows OS Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) to atomically destroy process trees upon parent death, and second, utilizing a cryptographically secure 10-minute polling loop that positively identifies tasks via injected UUID environment variables. The reporting GUI will surface this data in a minimal

## Actions & files produced

- NORTH STAR (LOCKED)
- STAGE 2: IMPLEMENTATION PLAN

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star (locked)**
- Goal: a zero-false-positive background sweeper that guarantees complete termination of orphaned sub-agents, paired with a minimal "Prism Matrix" reporting modal on the Anchor dashboard.
- Dual-layer defense by design: (1) Windows OS Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) to atomically destroy process trees on parent death; (2) a 10-minute polling loop that identifies tasks via an injected UUID env var.
- The GUI surfaces session IDs, cryptographic matches, running projects, and active background swarms (including autonomous Foreman runs) in a minimalist modal overlay.
- **Architecture (Master Plan)**
- Two domains coordinating with the existing `C:\dev\Anchor` core: a **Kernel Sentinel** (process-spawning + Job Objects via `job_runner.py` / `pty_manager.py`) and a **Cryptographic Sweeper + Prism GUI** (a background thread in `anchor.py` polling PIDs, matching UUIDs against `session_registry.py`, reaping orphans).
- Raised concerns: WMI polling is expensive on Windows; a 10-min WMI query could stutter the main loop; UUID injection could leak into unexpected sub-process envs.
- Resolutions locked: the polling loop runs in a **fully detached daemon thread** (10-min sleep, zero UI blocking); WMI is queried **only for `python.exe` and `claude.exe`** to shrink the search space; the injection key is the specific `ANCHOR_SESSION_ID_CRYPT_TOKEN` to avoid collisions.
- **Wave 1 — Job Object Foundation:** intercept `subprocess.Popen` in `pty_manager.py`, inject a UUID4 as `ANCHOR_SESSION_ID_CRYPT_TOKEN`, wrap the child in a `ctypes` Job Object with kill-on-close. *Done when:* a spawned test child gets the UUID and dies instantly when the Anchor parent is killed.
- **Wave 2 — Session Registry Logging:** persist the `crypt_token` to `sessions.json` (extend `_normalize`). *Done when:* registering a session writes `crypt_token` alongside `session_id`.
- **Wave 3 — Sweeper Daemon:** build `zombie_hunter.py` — a 10-min daemon loop using `psutil` to scan `python.exe`/`claude.exe`, read env, kill any process whose token is no longer active in the registry; expose `start_hunter()` for `anchor.py`. *Done when:* a dead-token orphan is killed while a valid process survives.
- **Wave 4 — Prism Matrix GUI:** add the "Glass Prism" modal in `dashboard_api.html` + backend routes serving live metrics (Live Projects, Swarms, Reaped Zombies). *Done when:* the dashboard opens the modal populated with live match data.
- The objective is a zero-false-positive background sweeper that guarantees complete termination of orphaned sub-agents, paired with a "Prism Matrix" reporting GUI on the Anchor dashboard.
- Defense is dual-layer: (1) Windows OS Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) that atomically destroy process trees on parent death, and (2) a 10-minute polling loop that positively identifies tasks via injected UUID environment variables.
- **Master Plan — architecture & risk resolution**
- Two domains coordinate with the Anchor core: a **Kernel Sentinel** (Job Object attachment via `job_runner.py`/`pty_manager.py`) and a **Cryptographic Sweeper + Prism GUI** (a background thread in `anchor.py` polling PIDs and matching UUIDs against `session_registry.py`).
- Shark-Tank flagged three risks: WMI polling is expensive on Windows, it could stutter the main event loop, and UUID injection could leak into unexpected sub-processes.
- Resolution: the polling loop runs in a **fully detached daemon thread** sleeping 10 minutes between sweeps (zero UI blocking); WMI is queried **only for `python.exe` and `claude.exe`** to shrink the search space; and a highly specific key (`ANCHOR_SESSION_ID_CRYPT_TOKEN`) prevents collisions.
- **Wave 1 — Job Object Foundation:** intercept `subprocess.Popen` in `pty_manager.py`, inject a UUID4 as `ANCHOR_SESSION_ID_CRYPT_TOKEN`, and wrap the child in a `ctypes` Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. *Done when:* a spawned child receives the UUID and killing the Anchor parent instantly kills the child.
- **Wave 2 — Session Registry Logging:** persist the `crypt_token` into `sessions.json` via `session_registry.py` (update `_normalize`). *Done when:* registering a session durably writes `crypt_token` alongside `session_id`.
- **Wave 3 — Sweeper Daemon:** build `zombie_hunter.py` as a daemon thread polling every 10 min via `psutil`, reading process env, and killing any process whose token is no longer active in the registry; expose `start_hunter()` for `anchor.py`. *Done when:* an orphan with a dead token is killed while a valid process is untouched.
- **Wave 4 — Prism Matrix GUI:** add a "Glass Prism Modal" in `dashboard_api.html` opened from a Zombie Hunter icon, displaying Live Projects, Swarms, and Reaped Zombies from backend routes. *Done when:* the dashboard renders the modal populated with live cryptographic match data.

## Files

- [NORTH STAR (LOCKED)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fcrucible%2FMASTER-PLAN.md)
- [STAGE 2: IMPLEMENTATION PLAN](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fcrucible%2FIMPLEMENTATION-PLAN.md)
