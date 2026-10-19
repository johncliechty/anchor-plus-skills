# STAGE 2: IMPLEMENTATION PLAN

## Wave 1: Job Object Foundation (Kernel Sentinel)
**Objective:** Intercept the process spawning mechanism in `C:\dev\Anchor\pty_manager.py` (and `job_runner.py` if applicable) to inject the `ANCHOR_SESSION_ID_CRYPT_TOKEN` UUID into the environment, and attach the process to a Windows Job Object with the `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` flag set.
**Done When:** A test script spawned by Anchor receives the UUID in its environment, and forcibly killing the Anchor parent process instantly kills the test child process.

> PROMPT: You are implementing Wave 1 of the Zombie Hunter. Modify `pty_manager.py` (and any related spawning utilities in Anchor) to intercept the `subprocess.Popen` call. Generate a unique `UUID4`, inject it into the child's `env` dict as `ANCHOR_SESSION_ID_CRYPT_TOKEN`, and wrap the child process in a Windows Job Object using `ctypes`. Ensure the job object sets `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.

## Wave 2: Session Registry Logging
**Objective:** Update `C:\dev\Anchor\session_registry.py` to ensure the exact Cryptographic UUID token injected during Wave 1 is durably stored in the `sessions.json` registry.
**Done When:** Registering a new session correctly writes the `crypt_token` to the JSON on disk alongside the standard `session_id`.

> PROMPT: You are implementing Wave 2 of the Zombie Hunter. Modify `session_registry.py` to accept the new `crypt_token` during session registration and ensure it is durably persisted and loaded from the `sessions.json` file. Update the `_normalize` function to support this new field.

## Wave 3: The Sweeper Daemon (Cryptographic Polling)
**Objective:** Build `zombie_hunter.py`—a background daemon thread that wakes up every 10 minutes. It will poll Windows `WMI` or `psutil` specifically for `python.exe` and `claude.exe` processes, extract their environment block, and verify the `ANCHOR_SESSION_ID_CRYPT_TOKEN` against the live `session_registry.py`. If a process has a token that is NO LONGER active in the registry, it is killed.
**Done When:** An orphaned test process with a dead token is successfully killed by the sweeper, while a valid process remains untouched.

> PROMPT: You are implementing Wave 3 of the Zombie Hunter. Create `zombie_hunter.py`. Implement a background daemon thread with a 10-minute polling loop. Use `psutil` to find all `python.exe` and `claude.exe` processes. Read their environment variables. If `ANCHOR_SESSION_ID_CRYPT_TOKEN` is found but the token does NOT exist as an active session in the data provided by `session_registry.py`, forcibly terminate the process. Expose a `start_hunter()` function that `anchor.py` can call.

## Wave 4: The Prism Matrix GUI
**Objective:** Build the "Glass Prism Modal" in `dashboard_api.html` (and any associated frontend/backend routes) to surface the sweeper data. It should list active projects, swarms, and zombie metrics, appearing when the user clicks the Zombie Hunter icon on the main dashboard.
**Done When:** The Anchor dashboard correctly displays the modal overlay, populated with live cryptographic match data from the backend.

> PROMPT: You are implementing Wave 4 of the Zombie Hunter. Modify `dashboard_api.html` and Anchor's frontend to include a button that opens the "Prism Matrix Modal" in a new window. Render the UI matching the "Glass Prism" aesthetic. It must fetch and display high-level metrics (Live Projects, Swarms, Reaped Zombies) from the backend. Update the backend server routes to serve this data from the `zombie_hunter.py` metrics.
