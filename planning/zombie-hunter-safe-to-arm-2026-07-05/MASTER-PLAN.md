# Master Plan (draft — rev. Stage-1/R3)

**North Star:** Turn Anchor's process-lifecycle subsystem from a permanently-disarmed liability into a trustworthy autonomous reaper that is provably SAFE TO ARM — one that reliably kills only truly orphaned sub-agent swarms (never a legitimate work-doing run) and whose safety is earned by evidence, not asserted — so John can finally flip it on.

## Stage-0 assent questions — DECIDE BEFORE THIS PLAN CAN LOCK

This plan resolves the North Star against a specific buildable end state, and that resolution is a DECISION John must make, not a scope choice the plan may silently make for him. The plan **cannot lock** until Q1 is answered; Q2/Q3 are surfaced so their load-bearing consequences are chosen, not defaulted.

- **Q1 (PREMISE — the contracted-deliverable decision, blocking).** The literal North Star says the reaper "kills only truly orphaned sub-agent swarms." This plan proposes to REACH that objective as the TOP RUNG of an evidence ladder, and to CONTRACT as the build's shipped, armable deliverable a **SAFE-TO-ARM FREEZE-ONLY reaper plus the harness+evidence that earns the kill rung** — with the KILL rung armed by John post-merge on lived zero-false-freeze evidence. This is a deliberate divergence between the literal North-Star verb ("kills") and the build's day-one armable capability ("freezes; kill is earned"). **John must pick one:**
  - **(1a) Freeze-first ladder (plan's recommendation):** ship an armable freeze-only reaper; kill is a second, separate flip John performs post-merge once criterion 12's kill bar is met on lived evidence. Freeze is fully reversible (suspend, never destroy), so it is the honest first thing worth arming.
  - **(1b) Kill-in-gate:** the build's arm gate must itself clear criterion 12's KILL bar before merge — i.e. the kill rung is a build EXIT gate, not a post-merge flip. This is a one-line scope promotion (criterion 12's kill bar moves from post-merge to build exit) and materially lengthens the build.
  The plan is written to 1a; if John chooses 1b, the ONLY change is that criterion (12)'s kill bar becomes a build exit gate. Either way this is now an explicit assent gate at the TOP of the plan, not a decision resolved in prose downstream.
- **Q2 (INTEGRITY POSTURE).** The plan treats the reaper as a fail-deadly control-plane primitive: arming/rung-advance/disarm are mutating operations that require the SAME token-auth as every other mutating Anchor endpoint, evidence receipts are append-only/tamper-evident, the arm gate is computed IN-PROCESS from the live harness (never trusted from a persisted number), and persisted state may only ever PROTECT (thaw/keep), never AUTHORIZE a kill (criterion 14). John assents that this integrity/authz model is in-scope for the build (without it, "provably safe to arm" is false regardless of decision-logic quality).
- **Q3 (STDLIB HARD GATE + ESCAPE HATCH).** Product code stays Python-3.8+ stdlib-only (sole exception: the existing lazy pywinpty), enforced by distro.py's import scan; psutil is a TEST-ONLY ground-truth dependency. The escape hatch — a SECOND declared distro exception — is opened ONLY if ctypes enumerator parity empirically fails AND the arm bar's recall floor cannot otherwise be met, and it then requires John's explicit assent (criterion 11, Phase 9). John assents to this bounded, assent-gated posture.

## North-Star endpoint reconciliation (what "flip it on" concretely delivers)

Given Q1's freeze-first resolution (1a), this is the buildable, in-scope end state that satisfies "John can finally flip it on." The plan commits to a **two-flip ladder with a numeric arm gate**, and the FIRST flip is the plan's contracted deliverable:

- **The contracted deliverable is a SAFE-TO-ARM FREEZE-ONLY reaper plus a proven ladder to kill.** Freeze is fully reversible (suspend, never destroy), so it is the honest first thing worth arming. "Flip it on" = John sets the freeze-only arm flag, and that flip is **gated by a concrete, numeric arm gate whose passing IS the flip event** (success criterion 12), and whose arming action is token-authed and receipt-backed (criterion 14). Nothing is armed by assertion; the gate's receipts, recomputed in-process, are the evidence.
- **The KILL rung is a SECOND, separate flip** that John performs only after a lived zero-false-freeze observation window on the armed freeze-only tier. It has its own numeric bar (criterion 12). The North Star's "kills only truly orphaned swarms" remains the objective, but the plan reaches it as the *top rung of an evidence ladder*, not as a day-one capability — and John assents to kill separately, on evidence, not on trust. (If John picks Q1 option 1b, this rung becomes a build exit gate instead.)

## Success criteria

- **(1) ABSTAIN-not-kill invariant:** when liveness inputs are missing, stale, partial, or the owner-set computation throws, every one of the 5 call sites (orphan_check banner, Swarm & Owner View freeze, zombie_terminal_start brief, armed kill-daemon live_ids provider, boot reconcile) treats the session as OWNED/alive — a unit test injects each failure mode and asserts zero freeze/kill actions (fixes fail-deadly fallback #1).
- **(2) Single shared liveness source:** all 5 call sites consume one canonical `live_owner_ids` computation (attached ∪ job-owned ∪ transitive-parent-owned) built from one snapshot per sweep; a test proves no call site can classify with a different/narrower input set (fixes inconsistent inputs #3).
- **(3) Bounded blast radius + boot grace:** a sweep can freeze/kill at most a configured cap per cycle, and no session younger than a configured boot/startup grace window is ever frozen or killed; tests assert the cap halts a runaway sweep and that a fresh session inside the grace window survives (fixes unbounded blast radius / no boot-grace #2).
- **(4) No swarm-job leak:** term_kill and term_delete tear down BOTH the PTY AND every job_runner job the session owns, and never hide the registry record while jobs are still live; a test starts a session with in-flight jobs, kills it, and asserts all owned jobs are cancelled/reaped and the record state is honest (fixes job leak #4).
- **(5) Status-model correctness:** STATUS_CANCELLED is terminal (never re-adopted, never keeps a worktree), and the reaped-orphan vs parked-warm meanings of STATUS_IDLE are disambiguated into distinct states so a parked-warm session keeps its worktree while a reaped-orphan does not; tests assert a cancelled session is never resurrected and that worktree retention follows the correct state (fixes #5).
- **(6) kill() persist-before-terminal ordering:** produced docs are captured/persisted to main BEFORE the record is marked DONE/terminal, and `_is_parked_idle`/`_is_parked` classification fails SAFE (unknown → treat as parked/keep, never as reapable); tests assert no doc loss on kill and that an ambiguous record is never reaped (fixes #6).
- **(7) Win32 correctness:** process-liveness probing uses a full-width ctypes handle path (`_kernel32` with argtypes/restype set, not windll implicit-int truncation), distinguishes a real running process from exit code 259/STILL_ACTIVE via a proper wait-with-timeout, and `_save_sessions` never deadlocks on WRITE_LOCK reentrancy; targeted tests cover handle width, the 259 ambiguity, and the reentrant-save path (fixes #7).
- **(8) POSITIVE-liveness kill predicate (no fail-deadly absence):** freeze/kill is authorized only by POSITIVE evidence, never by absence. KEEP holds if a session has a live owner OR any positive liveness signal that is itself LIVENESS-CORROBORATED (criterion 15). KILL requires ALL of: no live owner, **positive proof the owning process(es) are DEAD** via the identity-tuple probe (confirmed exit, not merely "not found"), no corroborated positive liveness signal, and fresh in-lock re-validation. A test proves that a session which is merely *quiet* (no writes, no CPU, no handles) but whose owning process is still ALIVE is NEVER frozen/killed (fixes fail-deadly work-evidence; resolves the gate-blocked/API-waiting hazard — see Phase 2).
- **(9) Restart-durable freeze state (containment not load-bearing; protect-only):** a crash-safe PERSISTED frozen-set is written atomically to disk BEFORE any arming and is re-read, re-probed, and re-honored after an NSSM `anchor` restart — a hermetic simulated-restart test proves a frozen session stays frozen across the process boundary via re-probe-and-reconcile. The persisted frozen-set may only PROTECT (keep-frozen / thaw), NEVER AUTHORIZE a kill: on restart, any destructive action is re-derived in-process from a fresh live probe, never from the persisted record (criterion 14). Correctness NEVER depends on OS containment surviving a restart; verified per-PID control is always the floor (see Phase 7 cost/benefit resolution).
- **(10) Arming safety gate — numeric, not asserted:** the daemon ships dry-run/UNARMED by DEFAULT and can only be armed when the plan's **numeric arm bar (below) is met with receipts recomputed in-process**; a dry-run telemetry/audit path records what WOULD have been frozen/killed (with owner-evidence per decision) so precision/recall are MEASURED on synthetic + shadow data before any arm flag is set.
- **(11) stdlib-only (psutil is TEST-ONLY, hard gate):** all PRODUCT changes are Python-3.8+ stdlib only (sole exception: lazy pywinpty in pty_manager.py, unchanged) and PASS distro.py's import scan — which mechanically FAILS the build if psutil/WMI is imported by any product module. psutil is permitted ONLY as a dev/test ground-truth dependency (Phase 9). This contradiction is resolved as a HARD GATE, with the fallback cost stated explicitly in Phase 9.
- **(12) THE ARM GATE (the flip event, numeric):** the freeze-only arm flag can be set ONLY when the evidence harness (Phase 9) + shadow telemetry (Phase 8) produce receipts clearing this bar, AND the gate value is recomputed IN-PROCESS from the live harness at arm time (never read from a persisted number — criterion 14). Numbers are the plan's proposed floor, tunable at Stage-2 but PRESENT as a criterion:
  - **Synthetic recall ≥ 0.95** on an injected-orphan corpus of **N_syn ≥ 200** abandoned trees spread across the required fixture classes (breakaway grandchild, reused PID, held git index.lock, access-denied probe, STALE index.lock, FORGED/stale heartbeat).
  - **Precision = 1.000 (ZERO false-freeze)** across ALL synthetic decisions AND across a shadow observation window of **≥ 500 real-session sweeps** on the live service, where a false-freeze = any session a deterministic post-hoc oracle shows was still legitimately owned/working.
  - **Min-N of real would-freeze decisions ≥ 50** confirmed against real orphans in shadow mode, with 0 false positives.
  - **Zero-false-freeze observation window:** the freeze-only tier runs in SHADOW (would-have-frozen logged, nothing actually suspended) until all of the above hold; the sweep at which they hold, WITH the append-only receipt log proving it, IS the arm event.
  - **Kill rung (John's second flip, or a build exit gate under Q1/1b):** after ≥ 14 days / ≥ 1000 sweeps of ARMED freeze-only operation with zero false freezes and zero reported legitimate-work disruption, AND every REAL-process fixture green. A test asserts the arm-tier state machine refuses to advance a rung whose bar is unmet.
- **(13) Spec truth:** `C:\dev\Skill Foundry\skills\zombie-hunter\SKILL.md` is rewritten to match the shipped mechanism — ownership-based (live-owner) + positive-liveness kill predicate, NOT identity-based; psutil/WMI removed from the product contract; the abstain-default, boot-grace, blast-cap, numeric arm bar, control-plane integrity/authz model, and log→freeze→kill ladder documented as the contract.
- **(14) Control-plane integrity + authorization (arming is a mutating, fail-deadly operation):** "provably safe to arm" requires that the arm control-plane cannot be subverted, not merely that the decision logic is sound. Concretely: (a) **authz** — arming, rung-advance, and disarm are mutating endpoints that require the SAME token-auth as every other mutating Anchor endpoint (a request without a valid token cannot arm, advance, or disarm); (b) **protect-only persistence** — persisted state (frozen-set, arm-tier record, cached gate numbers) may only ever PROTECT (thaw/keep) or downgrade the tier; it can NEVER by itself authorize a freeze or kill — every destructive action is re-derived in-process from a fresh live probe; (c) **tamper-evident receipts** — the evidence receipt log is append-only and tamper-evident (each record chained to the prior via a running hash), and the arm gate is computed IN-PROCESS from the live harness at arm time, never trusted from a stored aggregate; a test proves that a FORGED or edited receipt log FAILS the gate (the in-process recompute + chain-verify rejects it) rather than passing on the forged numbers. Tests: `tests/test_reaper_control_plane.py` asserts unauthed arm/advance/disarm are refused, a persisted "armed" record cannot itself trigger a kill without a live in-process re-derivation, and a tampered/forged receipt log fails the arm gate.
- **(15) Owner-enumeration contract + liveness-corroborated positive signals (the double-edged contract):** the positive-liveness basis is only sound if (a) the OWNER SET is a well-defined, refreshed, escape-resistant set and (b) every positive signal is corroborated by an ALIVE owner, so a stale artifact can never masquerade as life. Concretely:
  - **Owner-enumeration contract:** `live_owner_ids` = attached-PTY session ids ∪ job-owned ids ∪ transitive-parent-owned ids, where an id is job-owned iff it has a `RUNNING`/in-flight job whose holder is active (`_holder_is_active`) whose owning PID (and its descendants) is process-alive. The owning process set for a session is the recorded launch PID plus its live descendants, enumerated each sweep. **Detached/re-parented grandchildren** (a breakaway process the OS re-parents to PID 1/services) enter the owner set via BOTH mechanisms the design provides: (i) if the optional Job Object enhancement is present, Job-Object membership (`IsProcessInJob`) captures them regardless of re-parenting; (ii) always, the identity-tuple registry of launch-time PIDs+create-times recorded at spawn, re-probed each sweep, keeps a known-launched PID owned even after re-parenting — so a grandchild is never orphaned merely because its parent exited. The set is REBUILT from one immutable snapshot each sweep (never incrementally mutated), so drift cannot accumulate.
  - **Liveness-corroborated positive signals:** a positive signal (git index.lock present, session heartbeat, owned-socket, worktree write mtime, CPU sample) grants KEEP ONLY when it is BOTH fresh (mtime/age within the configured window) AND accompanied by an ALIVE owning process (identity-tuple probe). A STALE index.lock left by a crashed process, or a FORGED/stale heartbeat file whose owning PID is confirmed dead, is NOT positive liveness and does NOT protect. Required RECALL fixtures (an orphan that MUST be recalled, i.e. correctly frozen/killed): a **stale-index.lock orphan** (lock file present, owner dead) and a **forged-heartbeat orphan** (recent-looking heartbeat, owner dead) — both must be caught by the harness, proving corroboration closes the masquerade hole.
  - **Fallback-not-masked assertion:** the gate-blocked/API-waiting KEEP fixture must assert WHICH protection held. It runs TWICE: once with ownership intact (asserts KEEP held via the live-owner basis), and once with ownership FORCIBLY STRIPPED from the snapshot (asserts KEEP STILL held via the process-alive positive-liveness probe) — so the process-alive fallback is proven to work on its own and is never silently masked by the owner set.
  - Tests: `tests/test_reaper_single_source.py` (enumeration contract + one-snapshot rebuild), `tests/test_reaper_work_evidence.py` (corroboration: stale-lock/forged-heartbeat not protective; gate-blocked KEEP asserted twice with ownership stripped), and the stale-lock/forged-heartbeat recall fixtures wired into `tests/test_reaper_evidence_harness.py`.

## Traceability matrix (finding → criterion → phase → test module)

The falsifiability spine the reviewers asked for: every finding lands on a criterion, a phase, and a NAMED gating test module. Nothing is acknowledged without a gate.

| # | Finding | Success criterion | Phase | Gating test module |
|---|---|---|---|---|
| 1 | Fail-deadly abstain fallback (5 sites) | (1) | 1, 2 | `test_reaper_abstain.py` |
| 2 | Unbounded blast radius / no boot-grace | (3) | 4 | `test_reaper_bounds.py` |
| 3 | Inconsistent per-site liveness inputs | (2) | 1 | `test_reaper_single_source.py` |
| 4 | Swarm-job leak on kill/delete | (4) | 6 | `test_reaper_job_leak.py` |
| 5 | STATUS_CANCELLED / overloaded STATUS_IDLE | (5) | 5 | `test_reaper_status_model.py` |
| 6 | kill() persist-after-terminal doc loss | (6) | 5 | `test_reaper_status_model.py` |
| 7 | Win32 handle truncation / 259 / lock reentrancy | (7) | 3 | `test_reaper_win32.py` |
| 8 | Fail-deadly work-evidence (absence-gated) | (8) | 2 | `test_reaper_work_evidence.py` |
| 9 | Restart durability / containment assumed | (9) | 7 | `test_reaper_restart.py` |
| — | Arming by assertion, no numeric bar | (10),(12) | 8, 9 | `test_reaper_arming.py`, `test_reaper_evidence_harness.py` |
| — | stdlib-vs-psutil contradiction | (11) | 9 | `test_reaper_distro_scan.py` (distro import scan) |
| — | Held-handle undetectable in stdlib | (8),(15) | 2, 8 | `test_reaper_work_evidence.py` |
| — | Control-plane integrity/authz gap (r2 security lens) | (14) | 8 | `test_reaper_control_plane.py` |
| — | Owner-enumeration undefined / positive signal uncorroborated | (15) | 1, 2, 9 | `test_reaper_single_source.py`, `test_reaper_work_evidence.py`, `test_reaper_evidence_harness.py` |
| — | Spec contradicts shipped mechanism | (13) | 10 | `tests/test_skill_spec_truth.py` (grep contract) |

(The 9 numbered findings each get an independent module per C7 discipline; the cross-cutting rows share the arming/harness/distro/control-plane/spec modules. The r2 security lens is treated as a genuine new axis — control-plane integrity — not as convergence.)

---

A ten-phase plan that turns Anchor's disarmed process-lifecycle subsystem into an arming-worthy reaper by building safety bottom-up: first consolidate the five drifted call sites onto ONE canonical liveness source with a WRITTEN owner-enumeration contract and make abstain the structural default, then put the kill authorization on a POSITIVE, liveness-CORROBORATED basis (never absence, never a stale artifact), make the underlying Win32 liveness/age probing provably correct, add bounded blast-radius + boot-grace, fix the status-model and kill-ordering, close the job-leak, add restart-durable FREEZE STATE (protect-only, with OS containment demoted to a non-load-bearing enhancement), and only THEN expose an incremental log→freeze→kill arming ladder gated by a synthetic/real-process evidence harness that produces the NUMERIC arm bar behind a token-authed, tamper-evident, in-process-recomputed control plane — closing with the SKILL.md spec rewrite. Near-term phases (1–6) are specified concretely enough to seed a Stage-2 implementation plan against the real modules (zombie_hunter.py, session_registry.py, terminal_session.py, worktrees.py, job_runner.py, paths.py, pty_manager.py); the containment, arming-ladder, control-plane, and evidence-harness details of phases 7–9 are scoped explicitly with their numeric targets and integrity criteria named. Every phase maps to at least one North-Star success criterion; nothing is silently dropped.

## Phase 1 — Unify onto one reaper module + one canonical liveness snapshot + WRITTEN owner-enumeration contract

Serves criteria (2) and (15). The historical drift risk is five independent discriminators; the only durable fix is a single import surface fed by one immutable per-sweep snapshot built to a WRITTEN owner-enumeration contract. This is the structural foundation every later safety property leans on, so it goes first.

**Near-term specifics:**
- Create a new `reaper.py` module that absorbs the scattered discriminator logic currently in `zombie_hunter.classify` / `live_owner_ids` and the five call sites (idea 39).
- Define a frozen `@dataclass(frozen=True) LivenessSnapshot` capturing: `attached_pty_ids: frozenset`, `job_owned_ids: frozenset`, `parent_owned_ids: frozenset`, `pid_identity: Mapping[int, tuple[pid, create_time, image_path]]`, and `positive_liveness: Mapping[session_id, PositiveSignals]` (worktree-write mtime, index.lock presence, heartbeat age, owned-socket liveness, CPU sample); build it EXACTLY ONCE per sweep (idea 1).
- **Write the owner-enumeration contract (criterion 15) into the module docstring AND enforce it in code:** `live_owner_ids(snapshot)` = attached ∪ job-owned ∪ transitive-parent-owned, where job-owned requires a RUNNING in-flight job whose `_holder_is_active` is true AND whose owning PID (recorded at launch) + live descendants are process-alive; the owning process set is the recorded launch PID plus its live descendants enumerated THIS sweep; detached/re-parented grandchildren stay owned via the launch-time identity-tuple registry (re-probed each sweep) and, when present, Job-Object membership. The set is REBUILT from the immutable snapshot each sweep, never incrementally mutated.
- Make `live_owner_ids(snapshot)` a pure function of the snapshot with no self-sourcing.
- Refactor `classify()` to take the live-owner set AND the positive-liveness map as its ONLY inputs (no default self-sourcing) so a 6th consumer is compile-forced to supply them (idea 2, mitigation 7).
- Re-point all 5 call sites — `/api/rnd/orphan_check` banner, Swarm & Owner View freeze, `zombie_terminal_start` brief, the armed kill-daemon `live_ids` provider, and the boot reconcile (`anchor_gui.py:~18198`) — to consume the identical snapshot/provider; route the boot-reconcile site through the SAME shared owner-set rather than its own liveness-only path (idea 36).
- Add `tests/test_reaper_single_source.py` with a STUB-GATE test that greps every classify/kill call site and FAILS if any bypasses the single `live_owner_ids`/snapshot provider (idea 2), PLUS a test that asserts the owner-enumeration contract: a re-parented grandchild PID recorded at launch stays in the owner set after its parent exits, and the set is rebuilt (not mutated) each sweep.

**Deferred (explicitly):**
- Transitive-parent-owned set via full chain_id lineage walk with visited-set + hard depth cap + cycle→PROTECTED — deferred to Phase 4 where age/graph conservatism lives (idea 30).
- Targeted-lookup performance discipline (per-session job_id load, chains indexed by chain_id, sweep cost flat vs rnd_jobs/ size) — deferred to Phase 9's perf gate (idea 32, mitigation 16).

## Phase 2 — Positive, liveness-CORROBORATED kill predicate + gate-blocked/API-waiting proof + abstain invariant + pre-execution re-validation

Serves criteria (1), (8), and (15); builds premortem mitigations (1),(9). Once there is one source, the two most important properties are: (a) ANY uncertainty resolves to KEEP, and (b) KILL is authorized by POSITIVE proof of death, NEVER by absence of activity AND never blocked by a stale artifact masquerading as life. This phase also PROVES the single most dangerous assumption in the whole plan — that a legitimately-working session that happens to be quiet (gate-blocked, API-waiting) is protected — and proves WHICH protection holds.

**The absence-is-fail-deadly resolution (the crux):**
- A gate-blocked or API-waiting sub-agent writes no files, burns no CPU, and holds no obvious handles. Under any absence-based "work_evidence", it looks dead. The fix is structural: **the kill authorization is POSITIVE, not absence.** KEEP is granted by a live owner OR any CORROBORATED positive liveness signal; KILL requires the identity-tuple probe to CONFIRM the owning process(es) have EXITED. A quiet-but-alive process fails the kill predicate at "positive proof of death," so absence can never kill it.
- **PROVE the ownership assumption, do not assert it.** Add an explicit investigation task: instrument `job_runner` and confirm — with a test — whether a job that is blocked on an AskUserQuestion gate or awaiting an API response REMAINS in `job_owned_ids` (i.e., the job record stays `RUNNING`/in-flight, `_holder_is_active` stays true). Two outcomes, both handled:
  - If PROVEN true (expected): the gate-blocked session is KEPT by the live-owner basis, giving it double protection (owner + alive-process probe).
  - If NOT true (the job drops out of ownership while blocked): that is a fail-deadly defect that MUST be fixed in this phase — extend `job_runner` to keep a gate-blocked/API-waiting job in the active-owner set (a `blocked_but_owned` state) — because otherwise `work_evidence`/ownership cannot gate ANY action. This is a build task, not a deferral.
- **Fallback-not-masked (criterion 15):** `tests/test_reaper_work_evidence.py` runs the gate-blocked KEEP fixture TWICE and asserts WHICH protection held — once with ownership intact (KEEP via live-owner) and once with ownership FORCIBLY STRIPPED from the snapshot (KEEP STILL held via the process-alive positive-liveness probe) — so the process-alive fallback is proven independently and never silently masked.

**Held-handle detectability replacement + corroboration (item 5 / criterion 15):** stdlib cannot reliably enumerate another process's held file handles on Windows. Replace "held write handles" everywhere with CONCRETELY DETECTABLE stdlib signals, EACH corroborated by an alive owner:
- **git `index.lock` presence** — a plain `os.path.exists` on the worktree's `.git/index.lock` (and `.git/*.lock`): a live commit/checkout in progress — BUT protective ONLY when the owning PID is confirmed alive; a stale lock left by a dead process is NOT liveness.
- **Session heartbeat** — the live PTY/job writes a monotonic heartbeat timestamp to `.anchor/.../heartbeat` on a fixed cadence; a fresh heartbeat is positive liveness ONLY when the owning PID is confirmed alive (defeats a forged/stale heartbeat); a stale one is merely corroborating-idle (never a kill authorizer).
- **Owned socket liveness** — for a session with a known listening/connected port (e.g. a preview), a stdlib socket probe, corroborated by owner-alive.
- **Worktree write mtime + CPU sample** — corroborating idle signals only.
None of these individually authorizes a kill; presence of ANY CORROBORATED signal grants KEEP. Required recall fixtures (stale-index.lock orphan, forged-heartbeat orphan) prove an UNcorroborated signal never protects — wired here and into the Phase 9 harness.

**Near-term specifics:**
- Wrap the owner + positive-liveness computation in a defensive boundary: any exception, `None`/missing input, stale timestamp, partial set, or empty owner-set returns a sentinel EVERY call site interprets as OWNED/alive (idea 4).
- Implement `positive_liveness(session)` from the detectable signals above, each gated on owner-PID-alive corroboration; implement the KILL predicate as: no live owner AND identity-probe-confirmed-dead AND no CORROBORATED positive signal AND fresh re-validation (criteria 8,15).
- Add pre-execution re-validation: within the SAME lock, immediately before the destructive action, recompute owner + positive-liveness + confirmed-death for the SPECIFIC target and ABORT if anything now indicates life; the per-sweep snapshot is for candidate SELECTION only, EXECUTION requires fresh confirmation (idea 28, mitigation 9).
- Add `tests/test_reaper_work_evidence.py` (positive-basis) and extend `tests/test_reaper_abstain.py`: inject each failure mode (throw, None, stale timestamp, partial set) at each of the 5 call sites and assert ZERO freeze/kill; add the gate-blocked-session KEEP fixture (run twice, ownership-stripped variant), the quiet-but-alive KEEP fixture, and the stale-lock/forged-heartbeat NOT-protective fixtures.
- Introduce env knobs with safe defaults read via `paths.py`: `ANCHOR_REAPER_WORK_MTIME_SECS`, `ANCHOR_REAPER_CPU_WINDOW_SECS`, `ANCHOR_REAPER_HEARTBEAT_STALE_SECS`.

**Deferred (explicitly):**
- Fuzz/property-testing of classify over random present/absent/stale/throwing combinations asserting the invariant holds universally — deferred to Phase 9 (idea 38).
- Persistent-abstain detection + dashboard health-banner on >K consecutive abstains — deferred to Phase 8's telemetry surface (idea 31, mitigation 14).

## Phase 3 — Win32 correctness: full-width ctypes, STILL_ACTIVE/259 disambiguation, identity tuples, WRITE_LOCK reentrancy

Serves criterion (7) and mitigations (6 partial),(8),(12). Every safety decision above — especially the positive-proof-of-death kill predicate and the owner-enumeration identity-tuple registry — trusts the liveness probe; if the probe truncates handles, misreads exit 259, or deadlocks the save, the whole edifice is unsound. This must be correct before any age or containment logic relies on it.

**Near-term specifics:**
- Replace `windll` implicit-int probing with an explicit `_kernel32` ctypes surface — OpenProcess/GetExitCodeProcess/WaitForSingleObject/GetProcessTimes — with `argtypes`/`restype` fully set and HANDLE as `c_void_p`, so 64-bit handles are never truncated (idea 13).
- Disambiguate exit 259: never treat `GetExitCodeProcess==259` as dead; confirm via `WaitForSingleObject(handle, 0)` — `WAIT_TIMEOUT`=running vs `WAIT_OBJECT_0`=exited — and treat ACCESS_DENIED/open-failure as UNKNOWN→abstain (idea 14, mitigation 8). NOTE: "confirmed dead" for the criterion-8 kill predicate means `WAIT_OBJECT_0` with a matching identity tuple — never an inference from absence.
- Bind every tracked PID to a stable identity tuple (PID + GetProcessTimes creation time + image path where available); a liveness read or kill fires ONLY when both PID and creation-time match the snapshot; a mismatch = recycled PID → abstain (idea 16, mitigation 8). This identity registry is the escape-resistant backbone of the owner-enumeration contract (criterion 15).
- Restructure `_save_sessions` in `session_registry.py` to NOT re-acquire `WRITE_LOCK` when called under a held lock (pass the held lock down / split the critical section) rather than making the lock reentrant; add a parallel-sweep + user-write concurrency stress test to the gate (idea 15, mitigation 12).
- Add `tests/test_reaper_win32.py` covering: handle width on a synthetic high-value handle, the 259 ambiguity, the denied-open→abstain path, PID-reuse-within-a-sweep, and the reentrant-save path.

**Deferred (explicitly):**
- Validating the pure-ctypes Toolhelp32Snapshot/OpenProcess ENUMERATOR against psutil ground truth (psutil dev/test-only) — deferred to Phase 9; the stdlib-vs-psutil resolution and its fallback cost live there (idea 27, mitigation 18).
- Real detached-child-tree integration coverage of the probe under real-world shapes — deferred to Phase 9 (idea 26, mitigation 17).

## Phase 4 — Bounded blast radius + boot grace + conservative age + safe lineage walk

Serves criterion (3) and mitigations (6),(13). Even a correct reaper must be prevented from a runaway cascade or from touching young/unknown-age sessions. This caps the worst case before any arming is contemplated.

**Near-term specifics:**
- Add a per-cycle blast-radius cap `ANCHOR_REAPER_MAX_ACTIONS_PER_SWEEP` (small default) — a sweep STOPS after the cap and logs the remainder as deferred (idea 5).
- Add a boot/startup grace window `ANCHOR_REAPER_BOOT_GRACE_SECS` — never freeze/kill a session younger than the window (idea 5).
- Derive session age conservatively from the OLDEST defensible signal — process-tree start time via GetProcessTimes on the live PIDs, not file mtime; treat unknown-age (no registered `created_at`, no probeable PID start) as PROTECTED, and require a registered `created_at` for a session to EVER be kill-eligible (idea 6, mitigation 6).
- Walk the chain_id lineage for the transitive-parent-owned set with a visited-set and a hard depth cap; on cycle-or-cap, log and treat involved sessions as PROTECTED (abstain), never loop; add a registry-integrity check that flags lineage cycles (idea 30, mitigation 13).
- Add `tests/test_reaper_bounds.py`: cap halts a runaway sweep, a fresh session inside the grace window survives, unknown-age is never reaped, and a lineage cycle is flagged + abstained.

**Deferred (explicitly):**
- Tuning exact default cap/grace/age thresholds against live-service observation — deferred to Phase 8's dry-run window (relates to idea 23).
- Perf-flatness of the lineage/owner computation as the registry grows — deferred to Phase 9 (idea 32).

## Phase 5 — Status-model correctness + kill() persist-before-terminal ordering

Serves criteria (5) and (6), mitigation (10). The overloaded STATUS_IDLE and the current kill ordering are latent data-loss and false-reap hazards; disambiguating them and reordering persistence is prerequisite to trusting worktree-retention decisions.

**Near-term specifics:**
- Make STATUS_CANCELLED strictly terminal via a state-transition table that REJECTS any transition OUT of CANCELLED — never re-adopted, never reconciled back to running, never retains a worktree (idea 9).
- Split the overloaded STATUS_IDLE into `STATUS_PARKED_WARM` (keeps worktree, reopenable) and `STATUS_REAPED_ORPHAN` (no worktree); key `worktrees.reap_orphans`/`_is_parked_idle` retention on the explicit state field, not the overloaded one (idea 10).
- Migrate every legacy STATUS_IDLE record CONSERVATIVELY to PARKED_WARM (protected), never to reaped-orphan, so migration can only over-protect; gate the first post-migration boot with reap DISABLED (dry-run log only) (idea 11, mitigation 10).
- Reorder `terminal_session.kill()` so produced docs are captured/persisted to main (`capture_session_docs`) and the persist is CONFIRMED before the record is marked DONE/terminal; make `_is_parked_idle`/`_is_parked` fail SAFE — unknown/ambiguous → parked/keep, never reapable (idea 12).
- Add `tests/test_reaper_status_model.py`: a cancelled session is never resurrected by reconcile/adopt, worktree retention follows the correct state, no doc loss on kill, and an ambiguous record is never reaped.

**Deferred (explicitly):**
- UI surfacing of the two new IDLE-descendant states (tile color/label distinction) — deferred; backend-correct first, render polish later.
- Backfilling historical reaped-orphan records that predate the split — deferred; conservative migration treats all legacy as parked.

## Phase 6 — Close the swarm-job leak: teardown owns PTY AND jobs, reference-counted

Serves criterion (4) and mitigation (11). A session that dies while its job_runner jobs live on is exactly the orphan-swarm the reaper exists to prevent; kill/delete must reap both and never lie about record state.

**Near-term specifics:**
- Make `term_kill`/`term_delete` tear down the PTY AND every job_runner job the session owns via targeted per-`job_id` cancel/reap (never a full `list_records` scan) (idea 7).
- Forbid hiding the registry record while any owned job is still live — the record state stays honest until jobs are confirmed reaped (idea 7).
- Reference-count job ownership: before reaping a session's jobs, check whether any live successor in the chain (plan→build handoff, shared preview) still claims the job; kill only jobs with no other live claimant and record explicit hand-off ownership transfer (idea 8, mitigation 11).
- Add `tests/test_reaper_job_leak.py`: start a session with in-flight jobs, kill it, assert all owned jobs cancelled/reaped and record honest; assert a handed-off/shared job survives when a live successor claims it.

**Deferred (explicitly):**
- Retroactive sweeping of already-orphaned jobs from prior instances beyond boot reconcile — deferred to the armed sweep behavior in Phase 8.
- Cross-project shared-job semantics beyond the chain_id lineage — deferred; scope is intra-chain ownership for now.

## Phase 7 — Restart-durable FREEZE STATE (protect-only); OS containment demoted to non-load-bearing enhancement

Serves criteria (9) and (14) and mitigations (3),(4). **Cost/benefit resolution (item 6):** because the design ALWAYS degrades to verified per-PID kill and NEVER relies on cross-restart OS containment, a Windows Job Object is NOT load-bearing and is NOT on the arm-gate critical path. This phase therefore builds ONLY the load-bearing piece — a crash-safe persisted frozen-set plus restart re-probe/reconcile — and demotes Job Object containment to an explicit, optional, spawn-time enhancement that the arm gate does not depend on.

**Load-bearing (in scope, required for the arm gate):**
- Persist a crash-safe frozen-set + minimal metadata under `.anchor/` written atomically (tmp+rename) BEFORE any arming (idea 19).
- On restart, RECONCILE from the persisted registry by re-probing PID liveness (with the identity-tuple reuse guard) and re-establishing freeze control from scratch; never rely on cross-restart OS containment; treat the frozen-set as advisory-to-revalidate (ideas 19,20, mitigation 4).
- **Protect-only persistence (criterion 14):** the persisted frozen-set may only keep-frozen or thaw on restart; it can NEVER by itself authorize a kill — any destructive action after restart is re-derived in-process from a fresh live probe, never from the persisted record. `tests/test_reaper_restart.py` asserts a persisted "would-kill" marker does NOT cause a kill on restart without a live in-process re-derivation.
- Verified per-PID suspend/resume is the FLOOR mechanism for freeze; it works with zero OS-containment support.
- Add `tests/test_reaper_restart.py`: a hermetic simulated-restart test proving a frozen session stays frozen across the process boundary via re-probe-and-reconcile, that NO mass-kill-on-handle-close occurs when containment is absent, and the protect-only assertion above.

**Optional enhancement (explicitly NOT on the critical path; buildable only if cheap):**
- IF (and only if) it proves low-cost, prefer process containment AT SPAWN — assign a Windows Job Object to a swarm launch before its children fork — as an enhancement (it also strengthens grandchild ownership per criterion 15's enumeration contract), documented best-effort-only; never `KILL_ON_JOB_CLOSE` on a service-owned job (idea 17, mitigation 3).
- IF the enhancement is built, prove coverage empirically (`IsProcessInJob==true` for every PID) and on ANY escapee ABSTAIN from the job-object path and fall back to verified per-PID kill (idea 18, mitigation 3).
- If the enhancement's cost is not clearly justified at Stage-2, it is DROPPED — the arm gate stands on per-PID control + the identity-tuple owner registry + persisted frozen-set alone. This is the explicit cost/benefit call the reviewers demanded.

**Deferred (explicitly):**
- Exact Job Object ctypes flag surface (JOBOBJECT_EXTENDED_LIMIT_INFORMATION, AssignProcessToJobObject argtypes) — specified at Stage-2 ONLY IF the optional enhancement is kept.
- Real-process containment coverage assertions on the live host (breakaway grandchild fixture) — the real-process fixtures land in Phase 9.

## Phase 8 — Arming safety gate + CONTROL-PLANE INTEGRITY: token-authed arm/advance/disarm, tamper-evident receipts, in-process gate, dry-run default, freeze-only tier, reaper-explain CLI, health-banner

Serves criteria (10), (12), and (14), mitigations (5),(14),(15). Trust is earned incrementally by lived evidence measured against the numeric arm bar — AND the control plane that arms must itself be unsubvertable, or "provably safe to arm" is false. The daemon ships unarmed and climbs a log→freeze→kill ladder with reversible brakes, full auditability, and an authenticated, tamper-evident arm surface at every rung.

**Control-plane integrity (criterion 14 — the r2 security lens):**
- **Authz:** arming, rung-advance, and disarm are exposed only through mutating endpoints that require the SAME token-auth as every other mutating Anchor endpoint (reuse `paths.py` auth helpers). An unauthenticated arm/advance/disarm request is refused with no state change.
- **Protect-only persistence:** no persisted record (arm-tier, frozen-set, cached gate aggregate) can by itself authorize a freeze or kill; every destructive action is re-derived in-process from a fresh live probe. A persisted "armed" flag only ENABLES the in-process gate to run; it never substitutes for it.
- **Tamper-evident receipts + in-process gate:** the evidence receipt log is append-only and chained (each record carries a running hash of the prior), and the arm gate is COMPUTED IN-PROCESS from the live harness at arm time — never trusted from a stored aggregate. A forged or edited receipt log FAILS the gate (chain-verify + in-process recompute reject it).

**Near-term specifics:**
- Ship the daemon dry-run/UNARMED by DEFAULT; arming requires an explicit token-authed flag AND the numeric arm bar (criterion 12) met with receipts recomputed in-process (idea 21).
- Emit a structured per-decision owner-evidence receipt JSON for every classify outcome (KEEP/ABSTAIN/would-freeze/would-kill) — predicates fired, identity tuples, positive-liveness readings + corroboration result, confirmed-death result, age source, decision — to a rotating, append-only, hash-chained audit log under `.anchor/` (idea 33). These receipts ARE the arm-bar evidence.
- Add a kill-switch: a `.anchor/reaper.disarmed` file that, if present, forces dry-run regardless of the arm flag — a physical, restart-durable brake (idea 37).
- Implement the FREEZE-ONLY armed tier (fully reversible, never kill) as the first arm rung: freeze only what would otherwise be killed and only after the positive-liveness predicate says confirmed-dead-owner + no corroborated signal; before any suspend, snapshot the detectable locks (git index.lock, fresh heartbeat, owned socket) and ABSTAIN if any CORROBORATED positive signal is present; bound every freeze with an auto-thaw watchdog (idea 29, mitigations 5,15).
- Implement the arm-tier STATE MACHINE that refuses to advance a rung whose numeric bar (criterion 12) is unmet — computed in-process — and records the passing-sweep as the arm event.
- Add a `reaper explain` read-only CLI/inspection mirror (like the other `rnd` seams) that dumps the current snapshot, live_owner_ids, each session's classification + evidence receipt, and the current arm tier + distance-to-bar (idea 35).
- Track consecutive-abstain streaks and RAISE a dashboard health-banner (like the red GET-/ banner) when abstained > K sweeps, so a silently-disarmed reaper is loud (idea 31, mitigation 14).
- Add `tests/test_reaper_arming.py`: unarmed-by-default, disarm-file forces dry-run, freeze-only never kills, abstain-on-corroborated-positive-signal, evidence-receipt shape, arm-tier state machine refuses under-bar advance, and the health-banner trip.
- Add `tests/test_reaper_control_plane.py`: unauthed arm/advance/disarm refused; a persisted "armed" record cannot trigger a kill without a live in-process re-derivation; a forged/edited receipt log fails the arm gate (chain-verify + in-process recompute).

**Deferred (explicitly):**
- The EXACT tuned values of the arm bar (N_syn, window length, min-N) beyond the proposed floors in criterion 12 — finalized once the Phase 9 harness produces measured precision/recall; the floors stand as the contract until then (idea 23).
- Exposing the KILL arm rung to John after the zero-false-freeze observation window — a lived-evidence step gated on criterion 12's kill bar (idea 34). (Promoted to a build exit gate only if John picks Q1 option 1b.)

## Phase 9 — Evidence harness: synthetic orphan injection, real-process integration, enumerator parity (psutil hard-gate), fuzz, perf gate

Serves criterion (12) (and (10),(11),(15)), mitigations (2),(17),(18). Arming is 'earned by evidence, not asserted'; this phase manufactures the ground truth (synthetic + real orphans) and MEASURES recall/precision so the arm bar in criterion 12 has real numbers to clear.

**Near-term specifics:**
- Replace precision-on-rare-real-events with SYNTHETIC orphan injection: a test-host harness deliberately abandons known process trees at N_syn ≥ 200 and measures recall/precision against ground truth (idea 22, mitigation 2). Required fixture classes: breakaway grandchild, reused PID, held index.lock, denied probe, **STALE index.lock orphan**, **FORGED/stale heartbeat orphan** (the last two prove criterion 15's corroboration closes the masquerade hole).
- Add a shadow-mode would-have-killed/would-have-frozen counter cross-checked against a deterministic post-hoc oracle (did the tree exit on its own within T?) — this feeds the criterion-12 shadow precision number (idea 22).
- Add at least one REAL-process integration test: spawn an actual detached child tree on the test host, abandon it, and assert enumeration/liveness/freeze/kill behaves — with breakaway grandchild, reused PID, denied probe, held index.lock, stale-lock, and forged-heartbeat as REQUIRED fixtures that MUST exist and pass before the arm gate can pass (idea 26, mitigation 17). The breakaway-grandchild fixture also validates criterion 15's re-parented-grandchild ownership.
- **stdlib-vs-psutil HARD GATE (item 4) with stated cost:** validate the pure-ctypes Toolhelp32Snapshot/OpenProcess enumerator against a psutil-produced ground truth in TESTS ONLY (psutil = dev/test dependency, enforced absent from product by `test_reaper_distro_scan.py`). Any enumeration gap/denied-open = UNKNOWN→abstain. **Stated fallback cost:** if ctypes parity cannot be achieved, the plan does NOT silently add psutil to product; it keeps the abstain-on-gap posture (accepting reduced recall, which the arm bar's recall floor will then expose) — and ONLY if that recall floor cannot be met does a second declared distro exception (like pywinpty) become a Stage-2 decision requiring John's assent. The contradiction is thus resolved as: product stdlib-only by hard gate, with an explicit, bounded, assent-gated escape hatch — never an open-ended "maybe psutil" (idea 27, mitigation 18).
- Fuzz/property-test classify: random combinations of present/absent/stale/throwing inputs across all predicates, asserting 'no FREEZE/KILL without positive-death-of-owner AND no corroborated positive signal AND fresh re-validation' for every case (idea 38).
- Add a perf gate asserting sweep time stays flat as rnd_jobs/ grows (targeted per-session job_id load, chains indexed by chain_id, one snapshot per sweep), mirroring the GET-/ regression test (idea 32, mitigation 16).
- Enforce stdlib-only + green suite: all product changes Python-3.8+ stdlib (sole exception lazy pywinpty), pass distro.py's import scan, full suite green, each finding gated by its named test module per the traceability matrix (idea 24, C7 discipline).

**Deferred (explicitly):**
- Long-horizon live-service shadow measurement (the actual observation window John watches for the criterion-12 numbers) — an operational step post-merge; the harness + telemetry that FEED it are in scope, the multi-week watch itself is not a build task.
- The decision to declare the second (psutil-parity) distro exception — made only if ctypes enumerator parity empirically fails AND the recall floor cannot be met, with John's assent.

## Phase 10 — Spec truth: rewrite zombie-hunter SKILL.md to the shipped mechanism

Serves criterion (13). The spec currently describes an identity-based, psutil/WMI model that contradicts the shipped ownership-based + positive-liveness reaper; the documented contract must match reality or the safety story is unverifiable.

**Near-term specifics:**
- Rewrite `C:\dev\Skill Foundry\skills\zombie-hunter\SKILL.md` to describe the ownership-based (live-owner) + POSITIVE, liveness-CORROBORATED kill predicate model, NOT identity-based (idea 25).
- Strip ALL psutil/WMI references from the product contract (psutil appears only as a test-only ground-truth per Phase 9) (idea 25).
- Document as the contract: the abstain-default, the owner-enumeration contract (criterion 15), the positive-liveness kill predicate (confirmed-death-of-owner, never absence; signals corroborated by owner-alive), the detectable-lock signals (index.lock/heartbeat/socket), boot-grace, blast-cap, the persisted PROTECT-ONLY frozen-set + restart reconcile (containment non-load-bearing), the control-plane integrity/authz model (token-authed arm/advance/disarm, tamper-evident receipts, in-process gate — criterion 14), and the log→freeze→kill arming ladder with the NUMERIC arm bar and the kill-switch brake (idea 25).
- Add `tests/test_skill_spec_truth.py`: a grep gate that FAILS if the SKILL.md still asserts identity-based/psutil/WMI language or omits the arm-bar / abstain-default / control-plane-integrity contract.

**Deferred (explicitly):**
- Broader operator runbook / dashboard-help copy for reaper-explain + health-banner — a docs follow-up once UI surfaces stabilize.
- Cross-linking the rewritten SKILL.md contract into Anchor's CLAUDE.md architecture section — a housekeeping step after merge.