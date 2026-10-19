# Zombie-Hunter — Gandalf Evaluation (2026-07-05)

## Provenance
- Gandalf read of the **zombie-hunter subsystem**: `zombie_hunter.py`, `proc_probe.py`,
  `session_registry.py`, `worktrees.py`, integration excerpts from `anchor_gui.py` /
  `job_runner.py` / `terminal_session.py`, the `ZOMBIE_HUNTER_SKILL_SPEC.md`, and
  `tests/test_swarm_zombie_coverage.py` (assembled scope: `_gandalf-zombie-scope/`).
- **Primary read — single-family Fable 5, non-degraded:** run `run-1783259639683` →
  `gandalf/run-1783259639683/report.md` (28 findings across 6 areas). `cross_model:false`
  (honest — Gemini did not run in this read).
- **Cross-model corroboration — Gemini gemini-3.1-pro** (via the newly-wired agy transport):
  the shard drafts independently corroborated the core findings. The polished
  `cross_model:true` rendered artifact was blocked by a Gandalf-host conformance bug
  (see Follow-ups) — the corroboration below is taken from the raw shard drafts.

## Verdict
Well-built in the normal path (correct abstain-on-missing-identity discipline, good
single-spawn-site identity minting, OS Job-Object `KILL_ON_JOB_CLOSE` backstop, boot
reconcile-by-liveness) but **NOT yet safe to ARM** — a single transient liveness-probe error
flips the whole system **fail-deadly**. It is dry-run/unarmed by default today (no live kills),
so the danger is latent. Its `SKILL.md` spec is stale to the point of being un-implementable.

## The three questions
1. **Reap zombies without stopping legit runs?** Not reliably at the seams. Two CRITICALs:
   (a) **fail-deadly fallback** — every call site catches a `live_owner_ids` error and reverts to
   `live_ids = attached` (the pre-2026-06-30 "no PTY ⇒ orphan" rule) → false alert / freeze / kill;
   must ABSTAIN instead. (b) **unbounded blast radius** — one armed sweep + one degraded probe
   mass-kills every running session. Plus the armed daemon reads a different liveness set
   (`_LIVE.keys()`, no `records=`) than the advisory surfaces. It also under-reaps
   (kill-failures retire as "killed"; unidentifiable RUNNING records abstain forever;
   `STATUS_CANCELLED` excluded from terminal; PTY-only teardown hides live swarm jobs).
2. **Needs updating? Yes.**
   - **SPEC (urgent):** rewrite `SKILL.md` — it mandates **psutil/WMI** (violates the locked
     stdlib-only rule; not implementable), promises a genesis-token-in-live-process check the code
     dropped, and aims its "zero false positive" guarantee at *identity* when the real incident
     class is *ownership* misclassification; also own the "every restart kills live sessions"
     Job-Object semantic. Time-sensitive because the build is agent-driven (agents read the spec).
   - **CODE (before arming):** fallback→abstain; unify all 5 call sites on one accessor + signature;
     bound blast radius / add a boot-grace window before freeze+kill; `STATUS_CANCELLED`→terminal;
     stop overloading `STATUS_IDLE` (reap vs park); route swarm-lane teardown through
     `job_runner` cancel; fix `kill()`'s DONE-before-persist ordering; `_is_parked_idle` fail-safe.
3. **Fit for the current ("updated") Anchor? Bones yes, seams no.** Good & fitting: identity
   minting, Job-Object backstop, `launch_guarded` atomic under WRITE_LOCK, boot reconcile,
   abstain-by-default, dry-run-first. Clashes with the new architecture: IDLE-overload (a reaped
   orphan is indistinguishable from a parked warm-resumable session → worktree kept forever);
   Job-Object `KILL_ON_JOB_CLOSE` vs restart-durable parked sessions (every NSSM restart kills all
   live sessions); `_is_parked_idle` fails unsafe (read error → reap a parked worktree).
   Gandalf's steer: move from inference-side liveness (reaper enumerates owners) to
   **lease/heartbeat** (worker proves liveness) or kernel-group (Job Object) as primary boundary.

## Cross-model corroboration (Gemini gemini-3.1-pro vs Fable 5)
- ✅ **Swarm-job leak on delete/kill** — Gemini rated **CRITICAL** (`kill` only does `_pty.kill`,
  a no-op for swarm jobs; the deleted record → the hunter never sees it). Fable 5 had it MAJOR.
  Both families, independently; Gemini weights it higher.
- ✅ **Genesis-token / identity-assertion gap** — Gemini: spec claims a live-process token check,
  impl only checks the token is non-empty on the record. Corroborates Fable 5.
- ✅ **Dry-run suspension safety** (NtSuspendProcess) and **PID-reuse / creation-time tolerance** —
  both surfaced by Gemini, consistent with Fable 5.
- ⚠️ Fable 5's two headline CRITICALs (**fail-deadly fallback**, **blast radius**) live in the
  `anchor_gui` integration shard; not confirmable as independently flagged from the captured
  Gemini shard excerpts. The core (swarm-leak + token-gap + dry-run-safety) IS corroborated.

## Cross-model read (COMPLETED — `cross_model:true`, run-1783262815794)
A genuine two-family Gandalf-Heavy read (agy Gemini gemini-3.1-pro shards + Fable 5 fusion) graded
`cross_model:true, degraded:false`, risk tier **GROUNDED** (cross-model lifts the single-family
PROMISING ceiling). Report: `gandalf/run-1783262815794/report.md`.
**Cross-model verdict:** "the zero-false-positive guarantee is NOT actually established: identity,
liveness, ownership-ordering, and locking each carry an independently found defect that compound
into freeze/kill-the-innocent and hunter-self-wedge scenarios — treat the sweep as unsafe to arm."
- **CORROBORATES Fable 5:** not-safe-to-arm; false-kill of legit runs; hunter self-wedge/under-reap;
  swarm/teardown ownership leak; Job-Object containment lost across restarts; genesis-token/identity gap.
- **ADDS (Gemini went deeper on low-level Win32/concurrency correctness):** CRITICAL ctypes handle
  truncation (use `_kernel32` not `windll` on 64-bit); MAJOR liveness bug (use `WaitForSingleObject`
  to avoid the exit-code-259 STILL_ACTIVE false positive); CRITICAL nested-lock reentrancy in
  `_save_sessions`; and a cross-shard SYNTHESIS — "identity + liveness + ctypes must be hardened as
  ONE chain; point-fixing a single leg is insufficient," plus "crash-safe resume before arming."
- **Complementary split:** Fable 5 = architecture/integration seams (fail-deadly fallback, blast
  radius, IDLE-overload); Gemini = low-level Win32/ctypes/locking correctness. Together > either.

## Follow-ups / infrastructure (this session)
- ✅ **agy wired into Anchor `job_runner`** (`agy_job_adapter.mjs` behind `_build_gemini_argv`) —
  the host's Gemini CLI is `agy`, not bare `gemini`; verified end-to-end (PONG smoke, 0 popups).
- ✅ **Gandalf-host grader hardened** — `runHost` now DEGRADES a canary-tripping draft to its largest
  conformant subset (honestly stamped) instead of crashing the whole read (47/47 tests green). The
  original run-heavy4 crash was a transient host-process failure; the reconstructed Stage-B input
  grades cleanly, which produced the stored `cross_model:true` report.

Full findings: single-family `gandalf/run-1783259639683/report.md` (28); cross-model
`gandalf/run-1783262815794/report.md` (11 + 4 cross-shard).
