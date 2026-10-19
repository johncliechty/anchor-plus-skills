# FOCUS: Zombie-Hunter subsystem evaluation

## The evaluation question (verbatim)

> Does the Zombie-Hunter subsystem reliably TRACK, MONITOR, and REAP orphaned
> sub-agent processes (zombies) while NEVER stopping a legitimate, work-doing
> run? Does it need updating, and is it fit for the CURRENT ("updated") Anchor
> structure (per-session git worktrees, managed ConPTY sessions in
> session_registry, the durable job_runner, and the `live_owner_ids` live-owner
> discriminator)?

## Key thing to check — spec vs. implementation divergence

`ZOMBIE_HUNTER_SKILL_SPEC.md` specifies a **psutil/WMI + Windows Job Object +
cryptographic genesis-token (`ANCHOR_SESSION_ID`) + process-creation-time
composite-key** design. Its "Assertion Gate" claims a THREE-part kill test:
PID match **AND** creation-time match **AND** the exact `ANCHOR_SESSION_ID`
token present in the live process's environment block / command line.

The **ACTUAL implementation** (`zombie_hunter.py` + `proc_probe.py` +
`session_registry.py`) is **stdlib-only** (no psutil, no WMI — `ctypes`
`OpenProcess`/`GetProcessTimes`) and its kill gate is a TWO-part identity proof
plus an ownership check:

1. `classify(record, live_owner_ids)` kills only when: the record is RUNNING,
   has an identity (`crypt_token` + `pid` + `proc_create_time` all present), the
   live PID's creation time matches the recorded one (within `tol=2.0s`), AND the
   session is NOT in the live-owner set. Missing identity ⇒ **ABSTAIN** (never
   kill); dead PID ⇒ `reap_dead` (registry-only, no kill); creation-time mismatch
   ⇒ `reap_recycled` (never kills the new PID owner).
2. `live_owner_ids(attached, records=, job_active=)` is the safety-critical
   discriminator: **live owner = PTY-attached ∪ job-owned ∪ transitive
   parent-owned**. `job_active` defaults to `job_runner._holder_is_active`
   (session_id == job_id for a swarm/lane job).

Divergences a reviewer should weigh:

- **The genesis-token is stored but NOT verified against the live process.** The
  `crypt_token` is a per-spawn UUID recorded on the session record and set as the
  `ANCHOR_SESSION_ID_CRYPT_TOKEN` env var on the child (`job_runner.launch`), but
  `classify` only checks that the token is *non-empty on the record* — it never
  reads the live process's env block / command line to confirm the token, so the
  spec's "ultimate failsafe" (Assertion Gate step 3) is NOT implemented. Identity
  rests on `[pid, creation_time]` only.
- **The Job Object is created but its handle is not durably retained.** The
  KILL_ON_JOB_CLOSE guarantee (`proc_probe.attach_to_job_object`) is created at
  spawn and stashed on the in-memory `_LiveJob._h_job`; consider whether it
  survives across the server's own restart (NSSM) as the spec's Phase-1 promise
  requires, or whether it only protects against the child outliving a *clean*
  server exit.
- **The armed auto-kill daemon is OFF by default** (`ANCHOR_ZOMBIE_HUNTER=1`
  arms it; otherwise `start_hunter` runs sweeps in `apply=False` dry-run). The
  banner/freeze paths run regardless.
- **`pause_orphan` FREEZES (NtSuspendProcess) flagged orphans** in the Swarm &
  Owner View even in the default (unarmed) config — evaluate whether a false
  positive there could freeze a legitimate run (note the `PYTEST_CURRENT_TEST`
  guard is the only hard block on freezing).

Ask specifically: **does the implementation actually deliver the SKILL.md's
zero-false-positive guarantee**, given it dropped the token-in-live-process
assertion and relies on `[pid, creation_time]` + the `live_owner_ids` ownership
set — and **have the spec and the code diverged** enough that one should be
updated to match the other?

## Files in this scope

Verbatim copies (exact snapshots of the live source):

- `zombie_hunter.py` — the sweeper: `classify` (pure verdict), `live_owner_ids`
  (the live-owner discriminator), `sweep`, `pause_orphan`/`resume_pid`, the
  `start_hunter` daemon. The heart of the subsystem.
- `proc_probe.py` — stdlib `ctypes` Win32 probe: `creation_time` (identity
  proof), `is_alive`, `tree_kill` (taskkill /T /F), `suspend`/`resume`
  (NtSuspendProcess), and `attach_to_job_object` (KILL_ON_JOB_CLOSE Job Object).
- `session_registry.py` — durable session store; the `_normalize` schema that
  carries `pid`/`proc_create_time`/`crypt_token` + lineage, and `reconcile`
  (re-status a dead "running" record on boot).
- `worktrees.py` — per-session git worktree lifecycle; `reap_orphans` (keeps a
  `STATUS_IDLE` parked worktree, dry-run safety marker).
- `test_swarm_zombie_coverage.py` — the STUB GATE locking the swarm-session
  coverage + the live-owner discriminator invariants (never-kill-a-live-owner).
- `ZOMBIE_HUNTER_SKILL_SPEC.md` — the skill's SPECIFICATION (the psutil/WMI +
  Job Object + genesis-token design the implementation is measured against).

Excerpts (relevant functions only — headers name source file + line ranges):

- `anchor_gui_zombie_integration.py` — the server call sites: `/api/rnd/orphan_check`
  banner poll, the Swarm & Owner View render + `pause_orphan` freeze,
  `/api/rnd/zombie_terminal_start` briefing, and the boot-time reconcile +
  `reap_orphans` + armed kill-daemon `live_ids` provider.
- `job_runner_launch_excerpt.py` — `launch` (spawn + Job Object wrap + mint the
  sweepable session record with identity), `_holder_is_active` (the default
  `job_active` probe), `launch_guarded` (concurrency + spawn cap).
- `terminal_session_kill_excerpt.py` — `kill` / `close_session` (park) /
  `delete_session` / `reconcile_and_advance` — the competing teardown/park paths
  the hunter must never race into a false reap.
