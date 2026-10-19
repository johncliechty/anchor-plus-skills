# Invariants

## Durability, Honesty, and Reaper Invariants

1. **CLI+secondary atomic writes**: All writes must use atomic sequences (same-dir temp + fsync + rename + fsync).
2. **Cross-process lock**: O_EXCL lockfile with start-time+PID liveness pair ensures exclusive execution.
3. **Torn-index rebuild-from-pointers**: Torn indices are gracefully rebuilt from effort pointers.
4. **Boot-reaper owner-set**: Only the owning user can trigger the boot reaper, preventing unprivileged clearing.
5. **Telemetry/narration invariants**: Telemetry must log truthfully without fabricating states or histories.
