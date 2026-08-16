---
name: zombie-hunter
description: The armed-by-evidence background reaper for the Anchor service — it freezes or kills only a truly-orphaned sub-agent swarm and never a legitimate run, via ownership-based liveness, positive proof-of-death, an abstain-by-default safety gate, and a token-authenticated control plane.
---

<!-- ELEGANCE-LAW v2 -->
## The Elegance Law (locked by John — binding on this skill)

Canonical text: `Skill Foundry/ELEGANCE.md`. Applies to ANY agent running this
skill on ANY host. If this block and a longer procedure below disagree, this
block wins.

1. **Approvals are ≤200 words** — what changes in his world, the recommendation,
   the one thing that gets worse. The artifact stays on disk and is named, not
   pasted. An approval obtained with a longer block is VOID.
2. **Summaries are ≤150 words** — goal in one line, done / not done, ≤3 findings
   ranked by consequence, the single next decision. Never rounds, waves, seats,
   stamps, gate counts, or file inventories.
3. **Default to the lightest band, without asking.** A heavier tier requires the
   first status line to NAME its trigger: irreversible or externally visible,
   inputs unconverged, a prior failure in this exact area, or he asked for it.
4. **Needed-because line.** Any element he did not request carries one line:
   "Needed because ___; dropping it costs ___." No line, no element.
5. **Show a cut.** ONE dry round ends a review loop — never a streak. Every plan
   names something it removed; "nothing cut" is said aloud.

**THE VERIFICATION LAW** (added 2026-08-15 after its FOURTH recurrence — each of
the first three was written into a journal and recurred anyway):

6. **Verify the claim you actually made, on the surface he actually uses.**
   "It's live / fixed / renders" is a claim about HIS screen. That the server
   emits new bytes, that a build exited zero, or that assertions passed are
   claims about something else. Render it and look at it.
7. **A symptom reported twice retires the first explanation.** Test the
   hypothesis; never repeat it. An explanation that makes his report false
   ("it's your cache", "it's a data issue") needs MORE evidence, not less.
8. **Prefer a mechanism to an instruction.** If the same instruction is given
   every session, the instruction is the defect — build what removes it.
9. **A correction that lives only in a journal or a memory has not been made.**
   Promote it to where it is loaded BEFORE the work starts.

**Two laws these serve.** A gate that cannot see what the user sees is not a gate
— structure diffs are lints, and must be labelled as lints. And a guardrail is
never the whole product of a turn — if enforcement withholds output he already
paid for, show it anyway.
<!-- ELEGANCE-V2.1 addendum -->
**What elegance IS (researchPrime-vetted, 2026-08-15):** the largest result
carried by the least machinery its user can actually hold — every element
forced by an INDEPENDENT citable need, nothing present the objective does not
pay for. Earned by iteration, never by skipping work: as simple as the task
allows, no simpler than a single datum permits.

**The Rabbit-Catcher (canonical battery: `ELEGANCE.md` Part II, ships with
the bundle):** the steering seat runs the full RC battery at PLAN APPROVAL
and on any NEW mid-run element; round boundaries ask only RC-6 ("still on the
critical path?"). Uncertain ⇒ PARK the element (zero further spend) + one
batched line in the next block the user already reads — never silent pursuit,
never ad-hoc interruption. Needs and hazards must be independent of their
proposer (no self-authored justification records); malleability work is
never cut as "unused capability"; guards are judged by RC-G, never by
retirement. Verdicts: KEEP / HOLD (with written trigger or budget) / CUT
(logged).
<!-- /ELEGANCE-V2.1 -->
<!-- /ELEGANCE-LAW -->


> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol.

# Zombie Hunter — The Lifecycle Sentinel (safe-to-arm reaper)

> Persona tier: AUTOMATED SWEEPER. Substrate: Python background thread inside the Anchor service (stdlib only).
> This file is the SHIPPED CONTRACT for Anchor's process-lifecycle reaper. It describes the mechanism that is actually in the code (`reaper.py`, `proc_probe.py`, `freeze_state.py`, `reaper_arming.py`, `session_registry.py`, `terminal_session.py`), not an aspiration. The reaper is **unarmed by default** and is only ever armed once its safety is *earned by evidence*, never asserted.

## The Icon
**The Event Horizon Prism:** A perfectly symmetrical, dark-mode isometric prism with a matte black singularity at its center. Faint, glowing crimson data-threads spiral down into the void — the silent, evidence-gated cleanup of genuinely rogue processes.

## The Core Philosophy — ownership, not identity-matching
The reaper's job is to destroy an **orphaned sub-agent swarm** — a `claude.exe`/`python.exe` process tree Anchor spawned whose owning work is gone — while *never* touching a session that is still doing legitimate work (including a run that is merely blocked on an `AskUserQuestion` gate, quiet, or has no open browser stream).

The mechanism is **ownership-based**, not identity-matching. A registered-RUNNING session is a candidate for freeze/kill ONLY when it is identity-alive AND has **no live owner** — and a destructive action fires only on **positive proof of death** of that owner. Absence of a signal is never treated as death. Every uncertainty resolves to KEEP. The reaper **abstains** rather than guess.

This is the inversion of the old, retired model: there is **no** cryptographic token whose match authorizes a kill, and there is **no** dependency on a native process-inspection library — process enumeration and liveness are stdlib `ctypes` only.

## Node classifier contract seed (W3–W4 — dual-write shadow + spend atlas)

The Node token-spend sentinel (`classify.js` / `server.js`) uses the same fail-SAFE spirit. **SC1 is not claimed** by this seed; Freeze/Kill remain forbidden until later waves.

### Joint-quad zombie predicate

```
would-be actionable RED  ⇔  engine-positive
                          ∧  paid-spend positive
                          ∧  unsupervised (host-walk)
                          ∧  not Anchor-owned
```

| Leg | POSITIVE means | UNCERTAIN ⇒ |
|-----|----------------|-------------|
| engine | closed E1/E2 allowlist hit | **ABSTAIN** (never RED) |
| paid-spend | process-owned socket **and** remote host/SNI ∈ closed atlas (`api.anthropic.com`, `api.claude.ai`, `generativelanguage.googleapis.com`, `aiplatform.googleapis.com`, `api.x.ai`) | **ABSTAIN** (`SPEND_ATLAS_STALE`) |
| unsupervised | host-walk status `UNSUPERVISED` (no **active** interactive host on ancestry) | **ABSTAIN** (`SUPERVISED` ⇒ KEEP) |

**Active session (supervision leg, 2026-07-23):** SUPERVISED only when an allowlisted host ancestor is an *active* work session — **active VS Code/Cursor**, **active Anchor**, **active terminal/shell** (and other H hosts with interactive SessionId). Stale/orphaned shells (Windows session 0, job-only parents like taskeng/svchost) do **not** count as a session and must not KEEP a token spender.
| not Anchor-owned | ownership lookup `owned=false` | fail-closed ⇒ **KEEP** |

**Spend fail-closed (W4 / G2):** port-443 alone, generic Google CDN / `www.google.com`, marketing near-miss hosts, IP-only remotes, empty attribution, or empty/stale atlas ⇒ **not** `SPEND_POSITIVE` (`SPEND_NEGATIVE` or `SPEND_UNCERTAIN` / `SPEND_ATLAS_STALE`). Never invent spend.

Any uncertain leg ⇒ verdict **ABSTAIN** with structured reason codes; no actionable RED on any dual-write surface under shadow. Anchor-registered or ownership IPC error/timeout ⇒ **KEEP** (`OWNERSHIP_REGISTERED_KEEP` / `OWNERSHIP_IPC_FAIL_CLOSED`). Atlas/allowlist version bumps force re-shadow hooks (`spendAtlasHash` in `mode.js`).

### Ownership badge fields (per candidate)

- `owned` / `keep` / `failClosed` / `label` / `reasonCodes` / `stub` / `stubMaxWave`
- IPC path is a **stub** (`OWNERSHIP_IPC_STUB`) until ownership graduation; max stub lifetime is documented in `ownershipStubContract()`.

### Closed reason + Doctor issue catalogs

Versioned payloads from `reason-catalog.js` are exposed on `/api/state`, `/api/mode`, and `/api/catalogs`:

- `reasonCatalogVersion` + closed `reasonCodes[]`
- `doctorIssueCatalogVersion` + `doctorIssues[]` (`id`, `component`, `message`, `suggestedChecks`)

Clients must not invent reason codes outside the catalog.

### Reason-code field map (CI contract — W10 / P7)

Machine-checked by `test_skill_server_reason_code_contract` (`src/skill-contract.js`). Drift between this map and `reason-catalog.js` / server catalog payloads is **HALT-worthy**.

<!-- ZH_REASON_FIELD_MAP_BEGIN -->
```json
{
  "contractVersion": "w10-skill-server-v1",
  "reasonCatalogVersion": "w10-reason-catalog-v1",
  "doctorIssueCatalogVersion": "w9-doctor-issue-catalog-v1",
  "ownershipBadgeFields": [
    "owned",
    "keep",
    "failClosed",
    "label",
    "reasonCodes",
    "stub",
    "stubMaxWave"
  ],
  "serverCatalogFields": [
    "reasonCatalogVersion",
    "doctorIssueCatalogVersion",
    "reasonCodes",
    "doctorIssues"
  ],
  "reasonCodes": [
    "SHADOW_OBSERVE_ONLY",
    "WOULD_BE_ACTIONABLE_RED",
    "LEGACY_SPEND_UNSUPERVISED_SHAPE",
    "NEW_CLASSIFIER_WOULD_BE_RED",
    "NO_WOULD_BE_RED",
    "MODE_SHADOW",
    "MODE_ARMED",
    "REFUSE_ARMED_WITHOUT_RECEIPT",
    "CANARY_RECEIPT_MISSING",
    "CANARY_RECEIPT_MISMATCH",
    "E1_CLOSED_ALLOWLIST",
    "E2_SUPPORT_ANCESTRY",
    "E2_NO_E1_WITHIN_K",
    "ENGINE_NEGATIVE",
    "ENGINE_NEGATIVE_BASENAME",
    "ENGINE_UNCERTAIN",
    "ENGINE_INVALID_PROC",
    "INVALID_PROC",
    "NOT_ENGINE",
    "SUPERVISED",
    "UNSUPERVISED",
    "SUPERVISION_UNCERTAIN",
    "INVALID_CANDIDATE",
    "MISSING_PARENT",
    "MISSING_ANCESTOR",
    "PPID_CYCLE",
    "CREATETIME_INVERSION",
    "CREATE_TIME_INVERSION",
    "HOST_ALLOWLIST_ANCESTOR",
    "WALK_COMPLETE_SYSTEM_ROOT",
    "DEPTH_TRUNCATION",
    "WALK_DEPTH_TRUNCATION",
    "ORPHAN_DETACHED_SPENDER",
    "SPEND_POSITIVE",
    "SPEND_NEGATIVE",
    "SPEND_UNCERTAIN",
    "SPEND_ATLAS_STALE",
    "SPEND_PORT_443_ALONE",
    "SPEND_ATTRIBUTION_UNREADABLE",
    "SPEND_ATLAS_EMPTY",
    "SPEND_ATLAS_VERSION_MISMATCH",
    "OWNERSHIP_IPC_STUB",
    "OWNERSHIP_IPC_FAIL_CLOSED",
    "OWNERSHIP_REGISTERED_KEEP",
    "OWNERSHIP_NOT_REGISTERED",
    "OWNERSHIP_TRANSPORT_ERROR",
    "OWNERSHIP_TIMEOUT",
    "OWNERSHIP_UNAUTHENTICATED",
    "OWNERSHIP_INVALID_IDENTITY",
    "OWNERSHIP_REGISTRY_READ_ERROR",
    "QUAD_JOINT_POSITIVE",
    "QUAD_ABSTAIN_UNCERTAIN_LEG",
    "QUAD_KEEP",
    "VERDICT_ABSTAIN",
    "VERDICT_KEEP",
    "VERDICT_WOULD_BE_RED",
    "FREEZE_UNAVAILABLE",
    "FREEZE_CAPABILITY_FALSE",
    "FREEZE_IDENTITY_MISMATCH",
    "FREEZE_IDENTITY_REQUIRED",
    "FREEZE_SUSPEND_FAILED",
    "FREEZE_OWNERSHIP_RACE_ABORT",
    "KILL_DISABLED",
    "KILL_WITHOUT_FREEZE_DISABLED",
    "KILL_CONFIRM_REQUIRED",
    "KILL_CONFIRM_INVALID",
    "KILL_AUTHZ_DENIED",
    "KILL_TREE_FAILED",
    "KILL_DEATH_UNVERIFIED",
    "KILL_OWNERSHIP_RACE_ABORT",
    "ANCHOR_OWNED_NO_NODE_KILL",
    "FREEZE_KILL_FORBIDDEN",
    "SPEND_POSTCONDITION_STOPPED",
    "SPEND_POSTCONDITION_CONTINUES",
    "SPEND_POSTCONDITION_UNCERTAIN",
    "SWEEP_ERROR",
    "CACHE_STALE",
    "CACHE_ONLY_IDENTITY_REFUSED",
    "CACHED_NON_ACTIONABLE",
    "WHY_FROM_CACHE",
    "UNCERTAIN_NOT_RED",
    "FREEZE_BEFORE_KILL"
  ],
  "doctorIssueIds": [
    "ZH_MODE_SHADOW_FORCED",
    "ZH_CANARY_RECEIPT_MISSING",
    "ZH_OWNERSHIP_IPC_FAIL",
    "ZH_SUPERVISION_UNCERTAIN",
    "ZH_SPEND_ATLAS_STALE",
    "ZH_SWEEP_ERROR",
    "ZH_QUAD_ABSTAIN",
    "ZH_FREEZE_UNAVAILABLE",
    "ZH_ANCHOR_OWNED_KEEP",
    "ZH_HEALTH_CHECK_ISSUES",
    "ZH_REAPER_ABSTAIN_STREAK",
    "ZH_REAPER_CHAIN_TAMPERED"
  ]
}
```
<!-- ZH_REASON_FIELD_MAP_END -->

### Ownership badge UI (W10)

Radar tiles always show the ownership badge. **Freeze and Kill are hidden when owned** (`owned` / `keep` / `failClosed`). Health surfaces include `abstainRate` and `unsupervisedSpendTruePositiveCount`. Operator runbook: `OPERATOR-RUNBOOK.md`.

## The single liveness source — `reaper.py`
All five historical discriminators (the `/api/rnd/orphan_check` banner, the Swarm & Owner View freeze, the `zombie_terminal_start` brief, the armed kill-daemon's `live_ids` provider, and the boot reconcile) consume ONE import surface fed by ONE immutable per-sweep snapshot (`LivenessSnapshot`, a frozen dataclass built exactly once per sweep). No call site may classify against a narrower input set.

**Owner-enumeration contract (the load-bearing definition):**

```
live_owner_ids(snapshot) = attached_pty_ids
                         ∪ job_owned_ids
                         ∪ transitive-parent-owned_ids
```

- `attached_pty_ids` — sessions with a live PTY / browser stream.
- `job_owned_ids` — sessions backed by an actively-running owning job (`job_runner._holder_is_active`; a gate-blocked / API-waiting job stays owned via a `blocked_but_owned` state).
- transitive-parent-owned — a session whose `parent_session_id` lineage reaches a live owner is itself owned, walked to a fixpoint over the immutable snapshot with a visited-set and a hard depth cap.

Ownership is enumerated from the **launch-time identity the registry recorded**, never from live OS parentage — so a backend PID re-parented to PID 1 after its launcher exits stays owned as long as its owning job or a live parent still claims it. `live_owner_ids` is a pure function of the snapshot, rebuilt fresh each sweep (no drift carries across sweeps).

## Positive proof-of-death kill predicate + detectable-lock corroboration
`classify` only *flags* a candidate (identity-alive, no live owner). A destructive action is separately gated by `kill_authorized`, which authorizes ONLY on the conjunction of:

1. a **confirmed-dead owner** (positive proof of death — see Win32 correctness), AND
2. **no corroborated positive signal** of life, AND
3. a fresh **in-process, in-lock re-validation** of the specific target immediately before the action, which aborts if anything now indicates life.

Positive-liveness signals are concrete, stdlib-detectable artifacts — a git `index.lock` in the worktree, a session `heartbeat` file, an owned `socket` probe, a fresh worktree write mtime, a CPU sample — and **each is gated on owning-PID-alive corroboration**. A stale `index.lock` or a forged/stale `heartbeat` whose owner is already dead grants NO keep: the masquerade hole is closed by corroboration.

## Abstain by default (fail SAFE, never fail deadly)
A defensive boundary wraps the owner + positive-liveness computation. Any exception, `None`, missing input, stale timestamp, partial set, empty owner-set, or degraded snapshot returns a sentinel that every one of the five call sites interprets as **OWNED / alive** — zero freeze, zero kill. When liveness cannot be observed, the reaper abstains.

## Win32 correctness — `proc_probe.py`, `ctypes` only
Liveness probing is stdlib `ctypes` (Toolhelp32Snapshot / OpenProcess / GetExitCodeProcess / WaitForSingleObject / GetProcessTimes), with `argtypes`/`restype` pinned and `HANDLE` as `c_void_p` (no implicit-int handle truncation). There is no native process-inspection dependency of any kind.

- **STILL_ACTIVE / 259 disambiguation:** a `GetExitCodeProcess` value of 259 is never read as death; death is decided by `WaitForSingleObject(handle, 0)` returning `WAIT_OBJECT_0`. An access-denied / open failure yields UNKNOWN → abstain.
- **Identity tuple anti-recycle:** every liveness read or kill is gated on a stable `identity tuple` of `(pid, creation_time, image_path)`. `Confirmed dead` = `WAIT_OBJECT_0` AND a matching creation time; a creation-time mismatch means the PID was recycled by a different process → abstain, never act. Any enumeration gap likewise resolves to UNKNOWN → abstain.

## Bounded blast radius + boot-grace + conservative age
- **Blast-radius cap** (`ANCHOR_REAPER_MAX_ACTIONS_PER_SWEEP`): a sweep stops after the cap and logs the remainder as deferred — no runaway cascade.
- **Boot-grace window** (`ANCHOR_REAPER_BOOT_GRACE_SECS`): a session younger than the window is never frozen or killed.
- **Conservative age:** age is derived from the oldest defensible signal (process-tree start time via GetProcessTimes on a live PID), and a session of **unknown age** (no registered `created_at`, no probeable PID start) is treated as PROTECTED. A registered `created_at` is required for kill-eligibility. A lineage cycle is flagged by the registry-integrity check and the involved sessions are abstained.

## Status-model correctness + no-loss teardown
- `STATUS_CANCELLED` is strictly terminal (a state-transition table rejects any transition out of it): never re-adopted, never reconciled to running, retains no worktree.
- The overloaded idle state is split into `STATUS_PARKED_WARM` (keeps its worktree, reopenable) and `STATUS_REAPED_ORPHAN` (no worktree); worktree retention keys on the explicit state, and an ambiguous/unknown parked-vs-reapable classification fails SAFE (keep, never reap).
- `terminal_session.kill()` captures and persists produced docs to main **before** the record is marked DONE/terminal (no doc loss on kill).
- **No swarm-job leak:** `term_kill` / `term_delete` tear down the PTY AND every `job_runner` job the session owns via targeted per-`job_id` cancel/reap (never a full scan), keep the registry record honest until owned jobs are confirmed reaped, and — reference-counted — spare a job still claimed by a live successor in the chain, recording the ownership transfer.

## Restart-durable PROTECT-ONLY freeze — `freeze_state.py`
The first destructive tier is a **reversible freeze** (per-PID suspend), never a kill.

- The frozen-set persists to `.anchor/reaper_frozen.json`, written atomically (tmp + `os.replace`, under `WRITE_LOCK`) before any arming.
- The persisted state is **protect-only**: an entry may only keep a session frozen or thaw it. It can NEVER, by itself, authorize a kill. A `would-kill` telemetry marker is honestly recorded but is inert on restart — any post-restart destructive action is **re-derived in-process** from a fresh live probe (`reaper.kill_authorized`), never read out of the file.
- On restart, `reconcile_after_restart` treats the persisted set as advisory-to-revalidate: it re-probes each owning PID's `identity tuple` and re-establishes the freeze from scratch via per-PID suspend/resume, the verified FLOOR mechanism.
- OS-level process containment (Job Objects) is a **non-load-bearing** enhancement, deliberately off the critical path — so an absent-containment host cannot suffer a mass-kill-on-handle-close, and freeze still works.

## The arming ladder + control-plane integrity — `reaper_arming.py`
The reaper's destructive capability is an incremental **log → freeze → kill arming ladder**, unarmed by default, advancing only on a numeric bar recomputed in-process behind an authenticated, tamper-evident control plane.

- **Rungs:** `TIER_LOG` (unarmed / dry-run — the DEFAULT; classifies and records evidence but touches no process) → `TIER_FREEZE` (freeze-only, fully reversible, never a kill; abstains on any corroborated positive signal; every freeze bounded by an auto-thaw watchdog) → `TIER_KILL` (may kill, but only through the in-process `kill_authorized` re-derived from a fresh probe each sweep).
- **Unarmed default + kill-switch brake:** with no persisted arm state the effective tier is `TIER_LOG`. A `.anchor/reaper.disarmed` **kill-switch** file forces dry-run regardless of the persisted tier — a restart-durable brake because it is a file on disk.
- **Token-authenticated control plane:** `arm` / `advance` / `disarm` require the same shared-secret token as every other mutating Anchor endpoint (`paths.auth_ok`); an unauthenticated request is refused with no state change.
- **Tamper-evident, in-process-recomputed arm gate:** every classify outcome is written as an append-only, **hash-chained owner-evidence receipt** under `.anchor/` (predicates fired, identity tuples, positive-liveness + corroboration result, confirmed-death result, age source, decision). The arm gate chain-verifies the receipt log, recomputes the arm statistics from the verified chain (never trusting a stored aggregate), and evaluates a fresh in-process live snapshot. A forged/edited log or an inflated aggregate FAILS the gate; an under-bar advance is refused.
- **Observability:** a consecutive-abstain health banner trips after more than K blind sweeps, and a read-only `reaper explain` CLI dumps the snapshot, `live_owner_ids`, each session's classification + evidence receipt, and the current arm tier + distance-to-bar. The numeric arm bar is measured against a synthetic + real-process orphan corpus so precision/recall are real numbers before the arm flag is ever set.

## Environment knobs (`paths.py`)
| Env | Meaning |
|-----|---------|
| `ANCHOR_REAPER_MAX_ACTIONS_PER_SWEEP` | Per-cycle blast-radius cap (small default). |
| `ANCHOR_REAPER_BOOT_GRACE_SECS` | Never freeze/kill a session younger than this. |
| `ANCHOR_REAPER_WORK_MTIME_SECS` | Worktree-write freshness window (positive-liveness). |
| `ANCHOR_REAPER_CPU_WINDOW_SECS` | CPU-sample window (positive-liveness). |
| `ANCHOR_REAPER_HEARTBEAT_STALE_SECS` | Heartbeat staleness ceiling (positive-liveness). |

The kill-switch `.anchor/reaper.disarmed` and the persisted `.anchor/reaper_frozen.json` / receipt log are files under the per-instance `.anchor/` store, not env.

## Process depth bands (Track B6) — `REAPER_PASSES_MIN=1`

Depth-variable knobs come **only** from `@foundry/triage` (`resolveZombieHunterDepthKnobs` / live `BAND_MAPPINGS['zombie-hunter']`). Depth may thin **reaperPasses** and **ceremonyLevel**; it never thins safety.

| Floor / rule | Contract |
|--------------|----------|
| `REAPER_PASSES_MIN` | **1** — LITE may run **1** ownership-confirmation pass; it may **never** be 0 |
| FULL multi-pass | Mapping-driven (`BAND_MAPPINGS` FULL row); not a prose literal in callers |
| `requireProofOfDeath` | Always **true** from frozen `ZOMBIE_HUNTER_SAFETY_FLOOR` at every depth (LITE / FULL / SPIKE) |
| Abstain-by-default | Always **true** from the same floor; missing/uncertain proof always ABSTAIN; live-run always KEEP |

Env depth pins: `FOUNDRY_TRIAGE_DEPTH` (portfolio) outranks `ZOMBIE_DEPTH` (skill alias). Unknown depth refuses. Missing depth defaults to FULL mapped knobs.

> **⏱ STATUS UPDATES TO CHAT:** When running long phases in the background, you MUST arm a 10-minute cadence (`ScheduleWakeup` ~600s) and provide scheduled updates to the user in the LOCKED Status-table format — canonical definition in ONE place: the canonical `AGENTS.md` → "Long-run progress updates" (`[HH:MM]` header · Effort/Doing/Status/Tests/Blocker/Procs/**Journal** rows · ETA + To do footer). The **Journal** row (mandatory, `none` when empty) recaps everything journaled since the last tick — the SESSION composes it from this skill's `journal/`.

## Usage journal (sleep-loop feed — append after every REAL run)

At the end of any real (non-test) run of this skill, append ONE entry to
`journal/` in this skill folder as `NNNN-<slug>.md` (next number; APPEND-ONLY —
a correction is a new entry, never an edit). Keep it under ~15 lines, honest over
polished, with the 7 canonical fields (see
`planning/portfolio-program/src/journal.mjs`):

- `id`: NNNN-<slug>
- `skill`: <this skill>@<version or date>
- `situation`: the recurring situation class (the sleep loop's cluster key)
- `context`: the distinct project/session it ran in (cross-context corroboration key)
- `observation`: what was learned — the candidate-lesson signal
- `outcome`: the genuine result (worked | friction | failed | refused)
- `provenance`: genuine-execution | seeded (only genuine-execution corroborates)

No journal entries → the sleep loop has nothing to learn from. This block is the
capture end of the Foundry's improvement loop.
