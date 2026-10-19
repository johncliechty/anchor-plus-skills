# Foreman Wave 8 Execution Summary

## Completed Work

1. **CLI Control Channel (`control_channel.py`)**
   - Implemented a dedicated background control channel thread inside `anchor_gui.py`.
   - **Windows:** Leverages `ctypes` to expose a named pipe `\\.\pipe\anchor-<per-install-id>` with an owner-only DACL (`SDDL: D:(A;;GA;;;OW)`).
   - **POSIX:** Creates a unix socket in a mode `0700` directory under the config root, using `SO_PEERCRED` to refuse connections from any non-matching user (`uid != os.getuid()`).
   - Purely OS-authenticated local channel; no HTTP credential fallback.

2. **Headless Pairing Code & Exchange (`anchor pair`)**
   - Added `anchor pair` to `anchor.py`, which communicates over the control channel pipe/socket to request a pairing code.
   - The server dynamically generates a ~50-bit Crockford base32 code, keeping only its SHA-256 hash in a thread-safe singleton state with a 10-minute expiry and 5-attempt cap.
   - The generated code is returned directly via the pipe to the CLI, which prints it exactly once to `stdout`.

3. **Web Pairing Route (`/api/auth/pair`)**
   - Exposed `POST /api/auth/pair` as a registered open route (added to `OPEN_ROUTES.json`).
   - Expects the pairing code from the browser, performing a constant-time HMAC comparison on the hash.
   - On success, directly consumes the pairing nonce and returns an `anchor_session` cookie for the new headless pairing session.

4. **Token Hygiene CI Test (`test_token_hygiene.py`)**
   - Created `tests/test_token_hygiene.py`.
   - Simulates the entire onboard -> claim -> agent spawn -> CLI pair sequence using internal Python APIs.
   - Asserts strict token hygiene by reading the on-disk logs and journal to guarantee the `ANCHOR_TOKEN` is entirely absent from any observability, satisfying the Wave 8 zero-leak guarantee.

The design strictly follows the single-use pairing plan and avoids transmitting the master token via IPC entirely.
