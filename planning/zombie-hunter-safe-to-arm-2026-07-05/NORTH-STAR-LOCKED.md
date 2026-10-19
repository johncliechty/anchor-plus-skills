# Locked North Star — zombie-hunter update (2026-07-05)

Turn Anchor's process-lifecycle subsystem from a permanently-disarmed liability into a trustworthy autonomous reaper that is provably SAFE TO ARM — one that reliably kills only truly orphaned sub-agent swarms (never a legitimate work-doing run) and whose safety is earned by evidence, not asserted — so John can finally flip it on.

## Success criteria
1. ABSTAIN-not-kill invariant: when liveness inputs are missing, stale, partial, or the owner-set computation throws, every one of the 5 call sites (orphan_check banner, Swarm & Owner View freeze, zombie_terminal_start brief, armed kill-daemon live_ids provider, boot reconcile) treats the session as OWNED/alive — a unit test injects each failure mode and asserts zero freeze/kill actions (fixes fail-deadly fallback #1).

2. Single shared liveness source: all 5 call sites consume one canonical live_owner_ids computation (attached ∪ job-owned ∪ transitive-parent-owned) built from one snapshot per sweep; a test proves no call site can classify with a different/narrower input set (fixes inconsistent inputs #3).

3. Bounded blast radius + boot grace: a sweep can freeze/kill at most a configured cap per cycle, and no session younger than a configured boot/startup grace window is ever frozen or killed; tests assert the cap halts a runaway sweep and that a fresh session inside the grace window survives (fixes unbounded blast radius / no boot-grace #2).

4. No swarm-job leak: term_kill and term_delete tear down BOTH the PTY AND every job_runner job the session owns, and never hide the registry record while jobs are still live; a test starts a session with in-flight jobs, kills it, and asserts all owned jobs are cancelled/reaped and the record state is honest (fixes job leak #4).

5. Status-model correctness: STATUS_CANCELLED is terminal (never re-adopted, never keeps a worktree), and the reaped-orphan vs parked-warm meanings of STATUS_IDLE are disambiguated into distinct states so a parked-warm session keeps its worktree while a reaped-orphan does not; tests assert a cancelled session is never resurrected and that worktree retention follows the correct state (fixes #5).

6. kill() persist-before-terminal ordering: produced docs are captured/persisted to main BEFORE the record is marked DONE/terminal, and _is_parked_idle / _is_parked classification fails SAFE (unknown → treat as parked/keep, never as reapable); tests assert no doc loss on kill and that an ambiguous record is never reaped (fixes #6).

7. Win32 correctness: process-liveness probing uses a full-width ctypes handle path (_kernel32 with argtypes/restype set, not windll implicit-int truncation), distinguishes a real running process from exit code 259/STILL_ACTIVE via a proper wait-with-timeout, and _save_sessions never deadlocks on WRITE_LOCK reentrancy; targeted tests cover handle width, the 259 ambiguity, and the reentrant-save path (fixes #7).

8. Restart-durable containment: process containment (Job Object association or an equivalent stdlib mechanism) and a crash-safe PERSISTED frozen-set are written to disk BEFORE any arming, and are re-read and re-honored after an NSSM `anchor` restart — a hermetic simulated-restart test proves a frozen session stays frozen and containment survives across the process boundary (fixes #8).

9. Arming safety gate: the daemon remains dry-run/unarmed by DEFAULT and can only be armed once the plan's enumerated safety gates are met; a dry-run telemetry/audit path records what WOULD have been frozen/killed (with the owner-evidence for each decision) so precision can be measured on the live service before the arm flag is ever set.

10. stdlib-only + green suite: all changes are Python-3.8+ stdlib only (sole exception: lazy pywinpty in pty_manager.py, unchanged), pass distro.py's import scan, and land with the full test suite green plus a new/updated test module gating each of the 9 findings (C7 never-broken-green discipline).

11. Spec truth: C:\dev\Skill Foundry\skills\zombie-hunter\SKILL.md is rewritten to match the shipped mechanism — ownership-based (live-owner), NOT identity-based; psutil/WMI references removed; the abstain-default, boot-grace, blast-cap, and arming-gate model documented as the contract.

---
_Decision: SALVAGE/harden the existing seams. The broader Anchor rearch C-gates (C1/C4/C6/C7 sign-offs, amendment) are OUT OF SCOPE for this effort. Build on a clean branch._
