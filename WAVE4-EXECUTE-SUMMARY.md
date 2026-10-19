Wave 4 — Per-OS Durability Layer under the Pinned Contract has been fully implemented in `lib/invariants.mjs` and tested in `test/pinning/wave4.test.mjs` using the mock `fs_shim.mjs`.

- Implemented `atomicWrite` with the POSIX 4-step sequence and Windows contention-bound rename substitute.
- Implemented `renameWithContentionBound` (15s total bound, exponential backoff, loud path/history failure, configurable upward only).
- Implemented `recursiveDelete` and `directoryRename` with contention bound and trash-rename-aside escape hatch.
- Implemented `acquireLock` with O_EXCL and PID+start-time staleness check/takeover.
- Updated `fs_shim.mjs` to add `rm` capability and `mockError` injection for `fsync`, `rename`, and `rm`.
- Created `test/pinning/wave4.test.mjs` with assertions for contention bounds, timeouts, fallback paths, POSIX structural differences, and a crash-between-steps never-torn test.

All file modifications comply with the rule to not use the shell/terminal. The orchestrator can now take over to run the tests and verify the wave completion.
