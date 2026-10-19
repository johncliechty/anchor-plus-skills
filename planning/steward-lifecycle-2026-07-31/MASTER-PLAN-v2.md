# MASTER PLAN v2 — Anchor steward: campaign orchestration by conversation

> **STAGE-1 APPROVED by John 2026-07-31** — see `STAGE1-APPROVAL.md`.
> **Serves NORTH STAR v4 (LOCKED 2026-07-31)** — `NORTH-STAR.md` in this folder is the
> anti-drift authority. Every phase below cites the numbered criteria it serves.
> Supersedes `stage1-artifacts/BEST-DRAFT.md` (the 9-phase draft), revised per John's
> locked edits: G1 shrunk to a wiring audit, the executor re-aimed at the verified-ABSENT
> Anchor half, the confirmed compile ENVELOPE adopted (NS criterion 2), scaffolding
> authored-then-batch-confirmed (criteria 1, 5), and two new phases — Rehydration
> (criterion 11) and the Attention contract / High Seat fold / portfolio at a glance
> (criteria 12, 13) — consuming the ALREADY-BUILT portfolio index by name.
>
> **Stage-1 gate decisions (John 2026-07-31, locked at approval):**
> 1. Unattended reflections never spend — queue; compile at next session open.
> 2. Portfolio index: A5 Wave-1 live-wiring audit; fix items only; no re-plan.
> 3. `briefCacheStale` (A3) FIXED in Wave 1 / Phase 1 (not deferred to Phase 7);
>    CI diff guard still fences the rest of the 19-wave GREEN tree.

**Fact base:** `INTAKE.md` (verified build-vs-wire ledger). The two REFUTED ideas —
adding an artifact channel to the handback, and bind-and-derive as new work — are NOT
in this plan; both already exist. **No phase modifies Crucible / Foreman / researchPrime
internals** (CI diff guard, Phase 1). **The portfolio tracking index is never re-planned
or rebuilt** (NS non-goal 1) — it is audited live in Phase 1 and consumed in Phase 9.

## Criteria map (every phase must appear here)

| NS criterion | Served by |
|---|---|
| 1 — spoken description → proposed scaffolding, batch-confirmed, zero chat persisted | P2, P3, P4, P5, P11 |
| 2 — lightweight authoring: ONE confirmed session envelope covers compiles AND orchestrator-loop reflections | P1 (calibration), P4, P11 |
| 3 — commission proposed FOR a named stage; skill+seat+depth before spend; confirm records `who` | P1, P2, P3, P5, P6, P11 |
| 4 — validated handback → REFLECTION RECEIPT + next-stage proposal | P7, P8, P11 |
| 5 — progressive elaboration fires at stage START, never demanded at scaffold time | P5, P11 |
| 6 — one campaign exercises ≥ two commissioned skills | P11 (asserts researchPrime + Crucible + Foreman) |
| 7 — stage artifacts render reviewably; spoken correction → new version via propose→confirm | P3, P10, P11 |
| 8 — roadmap status reflects ACTUAL session state across park/restart/kill | P3, P6, P11 |
| 9 — everything passes AUTH ON, asserted on outcomes | P1, P9, P11 |
| 10 — `roadmap_events` has exactly ONE writer, proven by concurrency test | P2, P11 |
| 11 — CONTINUITY: kill-everything-then-resume wake-up brief, no re-ask, dead run + missing handback NAMED | P7 (Rehydration), P11 |
| 12 — ALTITUDE CONTRACT: typed attention projection, read-only High Seat fold, badge within one poll, zero ambient beyond badge | P9, P11 |
| 13 — PORTFOLIO AT A GLANCE from the EXISTING index, no root walk, `unknown` never a shorter list | P1 (live-wiring audit), P9, P11 |

## The spend invariant, as v4 states it

**Nothing is spent, written, or started without a human confirmation** — and NS
criterion 2 now defines what that confirmation IS for steward authoring: a **confirmed
compile envelope**. John confirms ONE bounded session budget at session start; the
steward may spend only inside it; **every compile and every orchestrator-loop reflection
is still individually shown** (observability, not authorization); envelope exhaustion is
a HARD STOP requiring a fresh confirmation. The envelope explicitly covers
**orchestrator-loop reflections at stage boundaries**, not only describe-session
compiles — otherwise a nine-stage campaign becomes a per-boundary rubber-stamp mill
(the CONFIRMATION-FATIGUE risk named in the NS risk taxonomy). A designed consequence,
stated rather than hidden: a reflection that would fire when **no session envelope is
live** (e.g. an unattended handback landing overnight) is **queued as a typed ledger
event and compiled/proposed at next session open** — no spend ever occurs outside a
live envelope. Commissions remain individually confirmed (criterion 3) — the envelope
never covers a commission.

Phase 1's ≥20-compile measurement survives as **envelope CALIBRATION** (how big should
a default session envelope be), not as a usability gate on the mechanism.

## Wave-1 ground-truth gates — audits of the verified, hypotheses only where honest

INTAKE.md verified the Ecgberht halves EXIST. They are therefore audited for wiring
fitness, not gated as existence hypotheses whose FAIL branch rebuilds them. Genuine
hypotheses remain gated. Any defect found in an audit is a **fix item, never a
re-plan** (NS non-goal 1).

- **A1 — commission-half WIRING AUDIT** (was G1). `Ecgberht/engine/job-lifecycle.mjs`
  `proposeCommission` (:141) / `confirmCommission` (:250) and their verb wrappers
  `verbCommissionPropose` (:769) / `verbCommissionConfirm` (:836) are VERIFIED BUILT
  (refuse free-floating steps, validate roadmap health, record `who`, mint
  `job_id`/`commissioned_as`, append `commission_bind`). The audit produces a checked-in
  table of actual parameters/returns and the wiring seams Anchor must call. There is no
  FAIL-rebuild branch.
- **A2 — `assembleBriefPacket` coverage audit.** Drive `engine/brief.mjs
  assembleBriefPacket` (Q1–Q12, zero model calls, honest-unknown) against a REAL
  campaign fixture (Face + Strip + roadmap + commission dossier + one dead run) and
  table which continuity facts it already answers vs which need the Phase-7 dossier
  join. Fix items only.
- **A3 — `briefCacheStale` DEFECT confirmation + Wave-1 FIX (John Stage-1 gate,
  Decision 3 = option 2, 2026-07-31).** `brief.mjs:931` keys staleness on Strip only
  (`as_of` + `instruments.length` + `receipts.length`): a roadmap-only or Face-only
  change serves a STALE cached packet stamped `further_gathering:false`. Recorded as a
  defect row AND fixed in Wave 1 / Phase 1 (staleness key gains roadmap event count +
  Face version) — not deferred to Phase 7. Named in the NS risk taxonomy; CI diff guard
  still fences the rest of the 19-wave GREEN tree (named fix item only).
- **A4 — non-atomic confirm pair.** `verbCommissionConfirm` persists
  `writeProjectRoadmap(...)` then `writeFileAtomicSync(strip...)` as two separate
  durable writes (`job-lifecycle.mjs:929–944`); a crash between them leaves a
  commission bound in the roadmap with no Strip receipt. Recorded as a defect row;
  fixed in Phase 2 (single-writer spine makes the pair one journaled transaction or
  crash-repairable, proven by a kill-between-writes test).
- **A5 — is the built portfolio index LIVE and WIRED?** The steward-tracking build is
  19 waves GREEN / 671 tests — but its own
  `planning/steward-tracking-2026-07/stage2/EXECUTION-LOG.md` contradicts itself
  (the hand-appended correction attests 19 GO; the Waves section still reads "no waves
  built yet"), and `last_commit` stayed `null` across all 19 GOs (journal
  `foreman/journal/0093`). The audit proves empirically: the index home resolves, the
  snapshot exists and rebuilds, `steward query` answers over the REAL portfolio,
  Anchor-side consumption points (`engine/portfolio/anchor-contract.mjs`) are reachable,
  and DERIVED ingest is actually firing on live writes. Every gap is a **fix item
  scheduled before Phase 9 needs the index** — never a re-plan.
- **BUILD-E — the Anchor commission executor** (re-aim of the old executability gate).
  `grep -rni commission` over every Anchor `.py` returns NOTHING (INTAKE, verified
  ABSENT). This is not a gate on existing code — it is Wave-1 NEW WORK: a minimal
  executor path that takes a CONFIRMED commission and drives a real trio run through
  `job_runner.py` / `terminal_session.py` / `lanes.py`, asserting an observed PID and a
  returned handback. G4 below remains the honest hypothesis underneath it.
- **G2 — artifact rendering spike** (unchanged). Feed a REAL converged Crucible
  doc-trio through `packet-view.mjs` `classifyArtifact`/`buildArtifactCard`; verbatim
  verdict recorded. FAIL → plan-shaped renderer enters Phase 10 scope.
- **G3 — handback validation** (audit-leaning). `receipt-validate.mjs` is VERIFIED to
  validate the 6 campaign-memory fields; the wave observes a real trio handback pass
  and a corrupted one refused. Provenance upgrade stays Phase 8 work.
- **G4 — the real substrate** (genuine hypothesis, per INTAKE's open GAP). Whether
  `job_runner` can host a commissioned trio run headlessly under the steward. PASS =
  observed pid + returned handback via BUILD-E. FAIL = the slice launches the trio
  directly and substrate integration becomes its own phase. DEGRADED: one run at a
  time.
- **G5 — HALT traversability** (unchanged). Classification table of every human gate on
  the real Crucible/Foreman commission path: EXTERNALLY-OBSERVABLE /
  REQUIRES-TRIO-CHANGE / INVISIBLE. Gate budget stated in the same decision record.
- **G6 — identity** (unchanged). Does ANCHOR_TOKEN carry a recoverable subject; FAIL →
  `who` = `unattributed(shared_secret)`, honestly rendered; no IdP built.

---

## Phase 1 — Ground truth: audit the built, build the absent, flip auth, fence the trio

**Done-when:** every A-row audit table and G-gate verdict is checked in, the Anchor
executor (BUILD-E) drives one confirmed commission to an observed PID + returned
handback, the suite runs auth-ON only, and the trio diff guard is live.
**Serves NS criteria:** 2 (calibration), 3, 9, 13 (A5); precondition for all.

Deliverables:
- Storage-primitive hammer on the TARGET box (Windows, scanner + sync running): N
  concurrent appenders × M records, zero torn/lost/duplicated; FAIL → SQLite WAL, not a
  hardened file. Durability stated in hardening-law form: named atomic write + named
  lock + a concurrency test that fails if either is removed. No prose-only durability
  claim is accepted at any later gate.
- **A1 wiring audit** (table of `proposeCommission`/`confirmCommission` actual shapes +
  seams). **A2** brief-packet coverage table against a real campaign fixture. **A3**
  `briefCacheStale` defect row confirmed **and FIXED in this phase** (staleness key =
  Strip + roadmap event count + Face version; regression test: mutate only the roadmap
  → cache reports stale). Named fix item under the portfolio/index diff fence. **A4**
  non-atomic confirm-pair defect row confirmed. **A5** portfolio-index liveness audit
  with fix-item list.
- **BUILD-E:** the minimal Anchor commission executor (confirmed commission → real trio
  run through `job_runner.py`), integration-tested to observed PID + handback. This is
  the verified-ABSENT half; it is built, not gated.
- HALT inventory AND classification (file:line, three classes) + the gate budget locked
  against that table; any profile containing an INVISIBLE HALT is not commissionable in
  v1 and is named as excluded in the Face.
- **Decision record — the step-type → skill → confirmation map:** RESEARCH →
  researchPrime; PLAN → Crucible; BUILD → Foreman; **REVIEW → Gandalf (dispatch-table
  entry only — no new lifecycle machinery this effort)**. CONFIRM-TO-PLAN binds to a
  step ULID; CONFIRM-TO-BUILD binds to an approved plan artifact VERSION. A plan
  handback never auto-flows into a build.
- Identity resolution (G6) as a decision record; spend-confirmation events record the
  credential CLASS; IdP cut to the Grasscatcher.
- Auth flipped ON now: ONE suite, no auth-off variant, CI guard fails any bypass flag;
  negative auth tests (absent/expired/wrong-principal/revoked) first-class.
- CI diff guard: build fails if this effort modifies any file under the Crucible,
  Foreman, or researchPrime trees — or under
  `Ecgberht/planning/steward-tracking-2026-07` and `engine/portfolio/` beyond named
  fix items (the index is consumed, not re-planned).
- Compile-cost measurement, ≥20 real compiles (median + p90 $, wall clock,
  confirmations-per-useful-Face-version) — **feeds envelope calibration in Phase 4**,
  gates nothing.
- Face glossary line: 'talking' = typed NL chat in the Anchor UI; ASR out of scope.
- Amendment-vs-recommission decision recorded in the Face.

Deferred (explicitly): IdP of any kind; storage performance tuning; the sweeping
reconciler/outbox/capability minting (Phase 6); polished renderer (Phase 10, only if
G2 fails).

## Phase 2 — The ledger spine: one writer, one dossier key, invariants in CI

**Done-when:** the single-writer concurrency proof is green, the allow-list admits only
typed stores, the commission dossier joins the whole lifecycle under one key, and the
invariant checker (including the three new clauses) runs in CI.
**Serves NS criteria:** 10 directly; precondition for 1, 3, 4, 11.

Deliverables (kept from draft, plus the locked additions):
- Append-only stores under the Phase-1 primitive: `roadmap_events`, `face_events`,
  `source_text` blob store, commission dossier. Per-project partitioning at the storage
  layer; the two-live-session test proves partition isolation only.
- Second writer physically impossible: events store writable only by the holder of a
  named lock/socket `job_runner.py` cannot acquire, or via an IPC endpoint with no file
  path exposed to Python; CI grep of the Python tree for the events path. Single-writer
  concurrency test that fails if the atomic write or the lock is removed (criterion 10).
- **A4 fix lands here:** the roadmap-then-strip confirm pair becomes one
  journaled/recoverable transaction; kill-between-writes test proves no
  bound-without-receipt state survives restart.
- Typed foreign key: commission → step validated on write; unresolvable step ID
  REJECTED. Bidirectional integrity sweep in CI.
- THE COMMISSION DOSSIER: one key joining step ULID → proposal → confirmation
  (`who` + human|synthesized provenance) → minted capability → process/lease →
  quarantined handback → validated receipt → artifact version → spend.
- Confirmations typed at the storage layer; synthesized human approval a schema-level
  impossibility.
- **Event allow-list (zero-chat-turn conformance), versioned:** durable stores may
  contain ONLY Strip receipts, roadmap events, `face_events`, and `source_text`
  artifacts. Roadmap event kinds extend `ROADMAP_EVENT_KINDS`
  (`step_create`, `step_set`, `status_flip`, `commission_bind`) **plus
  `scaffold_proposal`** (the batch-proposal event Phase 5 emits). Later phases admit
  `reflection_receipt` (P7) and attention-state events (P9) ONLY via an explicit
  allow-list version bump + test — a "temporary" transcript sink fails the build.
- **Ledger invariant checker** — CI + periodic production — referential integrity both
  directions, single-writer attestation, no live RUNNING without a live lease, no
  synthesized approval in a confirmed chain, no receipt field without a source pointer,
  **plus three new clauses:**
  1. **Dangling commission:** confirmed, no terminal receipt, and no live lease past
     TTL → flagged by name.
  2. **Done-without-handback:** a step terminal `done` while its dossier's quarantine
     is empty → flagged (nothing reaches `done` without a validated handback).
  3. **Stale-step:** every `step_create` records the **Face version current at
     creation**; a step predating the current north star is FLAGGED for
     re-confirmation, never silently executed.

Deferred: cross-project write paths (non-goal), retention/compaction, multi-user
authorization.

## Phase 3 — The ugly vertical slice: describe, propose, confirm, real process, on screen

**Done-when:** one hard-coded path runs describe → proposal → confirm → real Crucible
process (via BUILD-E) → real handback → plan on screen, with lease-derived status and
zero fake elements. **Serves NS criteria:** 1, 3, 7, 8 (first real proof of each).

Kept as written in the draft: ugly by contract, never fake. One compiled Face field +
one roadmap step (extraction labelled PROVISIONAL), proposal card, confirmation
recording `who`, real run on the real substrate, real handback, artifact from the run's
output bundle (hash-checked — a steward stand-in fails the slice). Both confirmation
beats exist from here (CONFIRM-TO-BUILD may be an explicit refusal naming the plan
version it WOULD build). Status truth ships HERE: lease renewal, RUNNING only while
live, kill -9 → STALE never a lying RUNNING. Commission profile drawn from the
EXTERNALLY-OBSERVABLE HALT class; wave report records wall clock, dollars,
confirmations, readability verdict, and every break — the empirical input that re-plans
Phases 4–11 before they are built. Spends on this path run inside a confirmed envelope
(minimal form) with every spend shown.

Failure-state table (slice surface — statuses render in the chamber UI):

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (trio CLI absent) | `SLICE_SUBSTRATE_MISSING` | "The build substrate is not available on this box — commission cannot launch." |
| dependency-slow-or-killed (run dies) | `SLICE_RUN_DEAD` | "The commissioned run died — lease expired at <t>. Nothing is running." |
| dependency-returns-garbage (unparseable handback) | `SLICE_HANDBACK_GARBAGE` | "The run returned an unreadable handback; it is quarantined, not absorbed." |
| backing-store-unreadable | `SLICE_LEDGER_UNREADABLE` | "The campaign ledger cannot be read — no status shown rather than a guess." |
| empty-but-valid (no steps yet) | `SLICE_ROADMAP_EMPTY` | "No roadmap steps yet — describe the project to propose a scaffolding." |
| unknown (liveness undeterminable) | `SLICE_STATUS_UNKNOWN` | "Run liveness unknown (lease unreadable) — shown as UNKNOWN, not RUNNING." |

## Phase 4 — The Face as a compiled projection, under the confirmed compile envelope

**Done-when:** the Face is a projection over `face_events` with verbatim `source_text`,
provenance spans, visible `dropped_or_generalized`, first-class retraction — and every
compile runs inside a confirmed session ENVELOPE that also covers orchestrator-loop
reflections, with exhaustion a hard stop. **Serves NS criteria:** 1, 2.

Kept from the draft: immutable content-hashed `source_text` per description; provenance
spans (source_hash + offsets) on every compiled field; property test — any Face version
reproduces its exact source text byte-identically; typed assert/retract/refine events;
`dropped_or_generalized` rendered as part of the proposal and seen before acceptance;
retraction preserves content + `why` and is a hard exclusion set on recompile;
park/restart equivalence (byte-identical projection); bounded compile (max passes,
fixed-point check, circuit breaker that HALTs to John); incremental diff-based
rewrites; **cost ledger** — every compile logged with tokens + dollar estimate.

**REPLACED — CONFIRM-BEFORE-COMPILE → THE CONFIRMED COMPILE ENVELOPE** (the draft's own
recorded amendment, now canonical per NS criterion 2):
- ONE confirmed budget per session, proposed at session open with the calibrated
  default from Phase 1's measurement; John confirms once.
- **Scope: the envelope covers describe-session compiles AND orchestrator-loop
  reflections** (the stage-boundary reflection compiles Phase 7 renders and Phase 11
  demos). Without this a nine-stage campaign rubber-stamps at every boundary —
  criterion 2's exact wording. Commissions are NEVER inside the envelope.
- Every compile/reflection is still SHOWN individually (what it compiled, what it
  cost, envelope remaining) — observability, not authorization.
- Exhaustion is a HARD STOP: no compile runs past the envelope; the steward asks for a
  fresh confirmation. No soft thresholds, no unconfirmed spend below any line.
- A reflection firing with no live envelope (unattended handback) is queued as a typed
  event and compiled at next session open — no unattended spend, ever.
- The ≥20-compile measurement is envelope **calibration** (default size, warning at
  80%), not a usability gate.
- Mechanical gates: a ledger query proving every compile event references a live
  confirmed envelope with remaining budget; an exhaustion test proving the hard stop;
  a no-envelope-queue test proving zero spend between sessions.

Failure-state table (compile surface):

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (no live envelope) | `COMPILE_NO_ENVELOPE` | "No confirmed session envelope — compile queued; confirm a budget to run it." |
| dependency-slow-or-killed (compiler non-convergent) | `COMPILE_CIRCUIT_BREAK` | "The compiler could not converge in <N> passes — halted; your call." |
| dependency-returns-garbage | `COMPILE_OUTPUT_INVALID` | "Compile output failed validation and was discarded; the Face is unchanged." |
| backing-store-unreadable | `FACE_EVENTS_UNREADABLE` | "Face history cannot be read — compile refused rather than compiled blind." |
| empty-but-valid (nothing to compile) | `COMPILE_SOURCE_EMPTY` | "Nothing new to compile — the Face already reflects everything recorded." |
| unknown (envelope state undeterminable) | `ENVELOPE_STATE_UNKNOWN` | "Envelope balance unknown (ledger gap) — compile refused until it is repaired." |

Deferred: provenance VIEWER UI (Phase 10); time-travel audit (Grasscatcher); compile
quality tuning.

## Phase 5 — The scaffolding the steward AUTHORS, and elaboration that waits for the stage

**Done-when:** a spoken description yields ONE proposed multi-stage scaffolding (coarse
steps + Parable-of-the-Oranges annotations) batch-confirmed as ONE `scaffold_proposal`
→ batch `step_create` write, and starting a stage — not scaffolding it — triggers
targeted elaboration. **Serves NS criteria:** 1, 3, 5.

**REFRAMED, machinery kept.** v4 replaced the old non-goal: the steward AUTHORS the
coarse scaffolding (visibly labelled steward-authored, John is its reviewer — never
adversarial review); stage WORK stays commissioned.

- **The missing dialogue → `step_create` path is built here.** Today `step_create` is
  minted in exactly one place (`pe-gate.mjs:444`, parked future steps) and
  `verbRoadmapPropose` mints one step at a time; `stand-up.mjs confirmStandUp` creates
  Face+Strip but no steps (INTAKE). The steward may now propose a WHOLE scaffolding:
  one `scaffold_proposal` event carrying the ordered coarse steps + Oranges
  annotations; John's ONE batch confirmation emits the batch of `step_create` events
  through the single writer (criterion 1: batch-confirmed, zero chat persisted).
- Every step keeps an opaque immutable ULID minted at creation; the compiler may only
  ADD / RETIRE / AMEND by ID — never regenerate the list. Write-locks on steps carrying
  a live commission, enforced in the LEDGER WRITER. Explicit confirmation naming
  affected runs when a correction requires touching a locked step.
- **The commissionability predicate SURVIVES but moves in time:** it is no longer a
  scaffold-time requirement (a coarse scaffold step is ALLOWED to be vague — that is
  what coarse means). It becomes the **PROGRESSIVE-ELABORATION trigger**: when a stage
  is STARTED, the unit-tested pure predicate (named deliverable + acceptance sentence +
  ≥1 Face-anchored constraint with a provenance pointer) runs; failing it fires "tell
  me more" — targeted questions asking ONLY for the missing element — or an OFFERED
  researchPrime commission (itself individually confirmed, never silent). Criterion 5
  verbatim.
- Dry-run / estimate mode stays: computing skill + seat + depth + estimate spends
  nothing; propose is genuinely free; confirm is the first spend. Proposal card shows
  skill + seat + depth + estimate + bound step title and ULID. Typed FK enforces
  FOR-a-step. Concurrency test: `refine_goal` during an in-flight commission — handback
  lands on the ORIGINALLY bound step. `who` recorded per the Phase-1 identity decision.
- Mechanical gates: batch-confirm atomicity test (all steps or none); a
  scaffold-labelling test (every scaffold step renders `steward-authored`); a
  predicate-timing test (an un-elaborated step scaffolds fine, refuses commission
  until elaborated or the elaboration offer is taken).

Failure-state table (scaffolding proposal surface):

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (no Face to anchor to) | `SCAFFOLD_NO_FACE` | "No project Face yet — describe the project first; the scaffolding anchors to it." |
| dependency-slow-or-killed (proposal compile dies) | `SCAFFOLD_PROPOSAL_LOST` | "The scaffolding proposal did not complete; nothing was written. Ask again." |
| dependency-returns-garbage | `SCAFFOLD_PROPOSAL_INVALID` | "Proposed scaffolding failed validation — shown for reference, not confirmable." |
| backing-store-unreadable | `ROADMAP_STORE_UNREADABLE` | "Roadmap store unreadable — batch confirm refused rather than partially written." |
| empty-but-valid (description yields no steps) | `SCAFFOLD_EMPTY` | "I couldn't derive any stages from that description — tell me more." |
| unknown (existing roadmap state unclear) | `ROADMAP_STATE_UNKNOWN` | "Existing roadmap health unknown (validate failed) — heal before scaffolding." |

Deferred: dependency graphs / critical path; auto-elaboration without confirmation;
estimate calibration beyond order-of-magnitude.

## Phase 6 — Confirm to launch to live truth, hardened

**Done-when:** intent records, run-scoped capabilities, the sweeping lease reconciler,
the fsync'd outbox, the distinct build beat, and gate-surfacing all pass their kill
tests on the real substrate. **Serves NS criteria:** 3, 8.

**Kept as written in the draft**, in full: intent record + durable launcher reconciling
intents at boot (never a silent confirmed-but-unlaunched commission); distinct
run-scoped capability (single-purpose, revocable, TTL > budget ceiling; never argv/env;
redaction filter + no-capability-in-artifacts test); hardened lease truth (sweeping
reconciler, `status_flip(-> DEAD, cause=lease_expired)`, STALE-vs-DEAD distinct in the
UI); THE BUILD BEAT as its own confirmation bound to an immutable plan artifact version
(amending the plan invalidates an outstanding build proposal); per-beat status truth
(PLANNING / BUILDING named); Python-side durable fsync'd OUTBOX with monotonic
sequence + acknowledged idempotent drain by the Node mediator, kill-the-mediator
convergence test; the three kill -9 self-healing tests (job / Anchor / steward); the
park/restart/kill parity matrix as ONE checked-in table; gate-surfacing as a
first-class path proven on a deliberately gate-heavy REAL Crucible commission from the
EXTERNALLY-OBSERVABLE class, measured against the Phase-1 gate budget; real execution
via `job_runner.py` / `terminal_session.py` / `lanes.py`; status as a projection over
`status_flip` + lease liveness. INTAKE's `status_flip` gap (nothing emits today) is
closed here by the mediator as the single writer's client — Anchor never writes the
ledger directly.

Failure-state table (status/gate surface):

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (launcher down) | `LAUNCH_INTENT_STRANDED` | "Confirmed but not launched — the launcher is down; intent preserved, will reconcile at boot." |
| dependency-slow-or-killed (lease expired) | `RUN_DEAD_LEASE_EXPIRED` | "The run died (lease expired <t>) — marked DEAD, not RUNNING." |
| dependency-returns-garbage (outbox gap) | `STATUS_SEQUENCE_GAP` | "Status sequence gap detected — status shown as of seq <n>, gap flagged." |
| backing-store-unreadable | `OUTBOX_UNREADABLE` | "Status outbox unreadable — last durable status shown with its timestamp." |
| empty-but-valid (no runs) | `NO_LIVE_RUNS` | "Nothing is running." |
| unknown (reconciler cannot decide) | `RUN_LIVENESS_UNKNOWN` | "Run liveness UNKNOWN — neither RUNNING nor DEAD is claimed." |

## Phase 7 — Rehydration: the wake-up brief *(NEW — after Phase 6)*

**Done-when:** from a full kill of Anchor, the steward, and every run, reopening the
project days later produces a first message that states where the campaign is — stage,
live/dead/waiting runs, everything waiting on John, the dead run and the missing
handback NAMED — derived entirely from the ledger, proposing the next step with its
why, and re-asking NO question whose answer is recorded. **Serves NS criterion:** 11
(and 4's reflection rendering).

This is a WIRING phase over verified-built parts, not new machinery:

- **The deterministic session-open path is `assembleBriefPacket`**
  (`engine/brief.mjs:642` — Q1–Q12 cold-start reconstruction, zero model calls,
  honest-unknown), NOT new code. Wired at project open as the sole source of the
  orientation message.
- **Joined with:** `validateRoadmap` / `healRoadmap` (`engine/roadmap.mjs:322/:414`) so
  a torn roadmap heals before it briefs; the Phase-2 **commission dossier join** (which
  commissions are open, at what lifecycle state, per `advanceJobLifecycle` /
  `observeJobTerminal`); and the Phase-6 **lease check** so every claimed-live run is
  verified live — a dead one is reported "died mid-flight at <t>", a confirmed
  commission with no handback past TTL is reported "handback never arrived" — both
  NAMED, never silently absorbed (criterion 11 verbatim).
- **`seen` receipt appended on view** (`appendSeenReceipt` / `buildSeenReceipt`,
  `brief.mjs:183/:138`) AFTER assembling, so `deltaSinceSeen` (:241) stays anchored to
  the PREVIOUS seen and the "since you last looked" delta is count-anchored, not
  clock-anchored (survives clock skew).
- **THE NO-RE-ASK TEST** (criterion 11's proof): kill everything; reopen days later
  with the clock deliberately skewed; assert the first proposal cites recorded facts
  (Face version, stage, dossier state) and repeats NO question whose answer exists in
  `source_text` — asserted mechanically by diffing the proposal's questions against
  the recorded Q/A set.
- **Stage-boundary reflections are typed events rendered from ledger:**
  `reflection_receipt` (with Oranges prompts) admitted to the Phase-2 allow-list via a
  version bump; the wake-up brief renders pending reflections from the ledger — chat
  never persists (criteria 1, 4). Reflection COMPILES draw on the live envelope
  (Phase 4); queued when none is live.
- **`briefCacheStale` already fixed in Phase 1 / Wave 1** (A3, John Stage-1 Decision 3
  option 2) — Phase 7 only re-asserts the regression (mutate only the roadmap → cache
  reports stale) as part of the wake-up path; no second rewrite of the key.
- Mechanical gates: kill-everything-then-resume integration test (one dead run + one
  never-arrived handback seeded); byte-determinism of the brief packet given a frozen
  ledger; the no-re-ask diff assertion; A3 staleness-key regression re-assert.

Failure-state table (wake-up brief surface):

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (no ledger yet) | `BRIEF_NO_CAMPAIGN` | "No campaign recorded for this project yet — describe it to begin." |
| dependency-slow-or-killed (assembly interrupted) | `BRIEF_ASSEMBLY_FAILED` | "Could not assemble the wake-up brief — nothing partial is shown; retry." |
| dependency-returns-garbage (torn roadmap) | `BRIEF_ROADMAP_HEALED` | "Roadmap had <n> invalid events — healed and noted; brief reflects the healed state." |
| backing-store-unreadable | `BRIEF_LEDGER_UNREADABLE` | "Campaign ledger unreadable — brief refused rather than invented." |
| empty-but-valid (campaign done/idle) | `BRIEF_ALL_QUIET` | "Campaign at stage <s>; nothing running, nothing waiting on you." |
| unknown (run liveness unresolvable) | `BRIEF_RUN_UNKNOWN` | "Run <id>: liveness UNKNOWN — reported as unknown, not as running." |

## Phase 8 — Handback: quarantine first, derive honestly, validate provenance, refuse repairably

**Done-when:** every handback quarantines before validation, fields cite artifact
hashes present in the bundle, `unavailable(reason)` is preferred over invention, and
the refuse → repair → accept round-trip test is green. **Serves NS criterion:** 4 (the
validated handback that triggers the reflection receipt), 3.

**Kept as written in the draft**, in full: quarantine-before-validate (refusal always
repairable); the declarative derivation map (receipt field → trio artifact →
extraction rule, unit-tested on real converged output); typed `unavailable(reason)`
preferred, source pointer required; `receipt-validate.mjs` upgraded from shape to
PROVENANCE validation (artifact hash must exist in the run's output bundle; sampled
re-derivation spot-check published); the 6-field required set enforced with
`unavailable(reason)` acceptable; synthesized-approval refusal via Phase-2 typed
provenance; honest-coverage ratio published per handback in the Strip; explicit
repair-and-resubmit + step-reset with prior spend visible. On acceptance, the
validated handback emits the Phase-7 `reflection_receipt` and the next-stage proposal
through propose → confirm (criterion 4). The refuted e-1 (new artifact channel) stays
dead — the existing bundle channel is the only channel.

Failure-state table (handback surface):

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (bundle absent) | `HANDBACK_NO_BUNDLE` | "Handback arrived without its artifact bundle — quarantined; nothing accepted." |
| dependency-slow-or-killed (never arrived) | `HANDBACK_NEVER_ARRIVED` | "Commission <id> confirmed <t> ago; no handback. Named as overdue, not absorbed." |
| dependency-returns-garbage | `HANDBACK_REFUSED_REPAIRABLE` | "Handback failed validation on <fields> — quarantined for repair; work preserved." |
| backing-store-unreadable | `QUARANTINE_UNREADABLE` | "Quarantine store unreadable — validation refused; raw handback untouched." |
| empty-but-valid (all fields unavailable) | `HANDBACK_HONEST_EMPTY` | "Handback valid but <n>/<m> fields honestly unavailable — coverage ratio shown." |
| unknown (derivation source missing) | `FIELD_SOURCE_UNKNOWN` | "Field <f> cites no source artifact — rejected; shown as unknown, not filled." |

## Phase 9 — The attention contract, the High Seat fold, and portfolio at a glance *(NEW — after Phase 8, before the demo)*

**Done-when:** every project publishes the typed attention projection from ONE pure
read-only function; the High Seat folds N projections and answers "where is every
project" from the BUILT index without walking a single root; `needs_you` /
`deliverable_ready` reach the ⚑ badge within one poll; and a byte-identity test proves
the whole surface writes nothing. **Serves NS criteria:** 12, 13, 9.

- **Attention projection v1, frozen:** `working | needs_you | deliverable_ready |
  blocked | idle`, derived by **ONE pure engine function** (read-only over Strip +
  roadmap projection + lease state), with a documented precedence order
  (`needs_you` > `deliverable_ready` > `blocked` > `working` > `idle`),
  **edge-triggered `state_since`** (changes only on transition) and **hysteresis** near
  lease TTL so a lease-renewal jitter never flaps the badge (NS risk: attention
  FLAPPING).
- **Emitters at the natural sites, through the single writer:** Phase-6 gate-surfacing
  → `needs_you`; Phase-8 validated handback → `deliverable_ready` **gated on
  bundle-hash provenance** (the NS `deliverable_ready` provenance hole: no bundle
  hash, no ready); lease death → `blocked`. Attention events enter the Phase-2
  allow-list via a version bump.
- **`waiting_steps` derived from the roadmap projection** (`buildRoadmapProjection`
  step statuses) and fed to `enrichForRaise` — this **revives the currently-dead raise
  tier 2** (`raiseSeverity` → `waiting_on_john_step`, `engine/high-seat.mjs:112–129`,
  which today never fires because nothing supplies `waiting_steps`).
- **`precomputeBriefCache` (`brief.mjs:954`) fired on every attention-state change** —
  this **makes raise tier 1 (`human_wait_packet_ready`) real**: when a project comes
  forward, "bring it up" (`bringItUp`, `high-seat.mjs:539`) serves a FRESH packet with
  zero further gathering (and the Phase-7 staleness fix guarantees fresh means fresh).
- **Portfolio at a glance (criterion 13) — served from the BUILT index's no-walk query
  surface, never by walking roots:** the High Seat reads
  `engine/portfolio/query.mjs queryIndex` (:810) / `query` (:1315) (snapshot body +
  bounded tail merge, `indexOnlyFs` guard proving no root is opened),
  `engine/portfolio/registry.mjs readRegistry` / `materializeRegistry` for membership,
  and `engine/portfolio/root-status.mjs classifyRootStatus` /
  `unknownRowFromNative` / `renderRootStatus` for presence — so every active project
  shows current stage, live/waiting/blocked runs, and last movement without John
  digging. **An unreadable project renders `unknown` (its row present, freshness
  UNKNOWN), NEVER a silently shorter list** — the index's own loud-unknown contract,
  asserted again at this surface. Badge poll cost is index-read-only (NS risk: ambient
  POLL COST).
- **Read-only proof:** a full High Seat assembly (`assembleHighSeat`,
  `high-seat.mjs:674`) + badge poll + tile render leaves **every project tree
  byte-identical** (hash before/after), honoring `write_authority:'none'` and NS
  non-goal "any High Seat WRITE path".
- **Auth-ON badge round trip (criteria 9, 12):** stage a `needs_you` → badge shows 1
  within one poll → `bring_up` serves the FRESH precomputed packet → John decides →
  badge returns to 0. A campaign needing nothing produces ZERO ambient signals beyond
  the badge count (negative assertion over every other surface,
  `HIGH_SEAT_NEGATIVE_SURFACES`).
- Mechanical gates: pure-function determinism test (same ledger → same projection);
  flap test (jittered lease renewals near TTL → zero extra transitions); provenance
  gate test (handback without bundle hash never yields `deliverable_ready`);
  byte-identity test; one-poll latency test; unknown-row count-preservation test.

Failure-state table (High Seat / badge surface):

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (index absent) | `GLANCE_INDEX_MISSING` | "Portfolio index not found — no project list is shown; run the index audit fix." |
| dependency-slow-or-killed (query over cap) | `GLANCE_QUERY_REFUSED` | "Portfolio query exceeded its bound — refused, not truncated-as-complete." |
| dependency-returns-garbage (snapshot invalid) | `GLANCE_INDEX_UNPARSEABLE` | "Index snapshot unreadable — rebuild required; nothing is guessed." |
| backing-store-unreadable (one project root) | `GLANCE_PROJECT_UNKNOWN` | "<project>: state unknown (root unreadable) — row kept, marked unknown." |
| empty-but-valid (no active projects) | `GLANCE_PORTFOLIO_EMPTY` | "No active projects registered." |
| unknown (attention underivable) | `ATTENTION_UNKNOWN` | "<project>: attention state unknown — never rendered as idle." |

## Phase 10 — The plan John can read, and the correction he can speak

**Done-when:** commissioned stage artifacts render readably (testable property), a
spoken correction lands as a typed, lineage-tracked amendment through propose →
confirm, and the trio-bundle origin guardrail covers every artifact version — with the
scaffolding explicitly, visibly exempt. **Serves NS criterion:** 7.

Kept from the draft: G2-conditional renderer work; 'readable' as a TESTABLE property
(all content reachable in-UI, sections addressable, deep-link to a wave); spoken
correction = typed amendment shown as a diff before landing, full recommission only
when it cannot be a layer; immutable versioned artifacts with lineage v_n → v_n+1;
both amendment and recommission through the SAME propose → confirm with `who`;
provenance viewer for Face fields.

**I52 RE-SCOPED (the locked edit):**
- **Commissioned stage artifacts** — unchanged: every plan/report/build artifact
  VERSION and every typed amendment must originate from a trio run's output bundle
  (hash present); a steward-authored plan-shaped document is refused at v_1 and v_n
  alike.
- **The SCAFFOLDING is exempt** — it is steward-authored BY DESIGN (NS revised
  non-goal) and is **visibly labelled `steward-authored`** wherever it renders.
- **New test:** a scaffolding is NEVER presented as a commissioned plan — the renderer
  refuses to draw a scaffold step or `scaffold_proposal` in the commissioned-artifact
  card chrome, and an artifact card never renders without a bundle hash (NS risk:
  scaffolding mistaken for a commissioned plan).

Failure-state table (artifact render surface):

| State | Status code | User-visible text |
|---|---|---|
| dependency-missing (bundle gone) | `ARTIFACT_BUNDLE_MISSING` | "Artifact's source bundle is missing — shown as unavailable, not re-created." |
| dependency-slow-or-killed (render fails) | `ARTIFACT_RENDER_FAILED` | "Could not render this artifact — raw bundle is downloadable; nothing invented." |
| dependency-returns-garbage (unclassifiable) | `ARTIFACT_UNCLASSIFIED` | "Artifact type unrecognized — listed by name, not force-rendered." |
| backing-store-unreadable | `ARTIFACT_STORE_UNREADABLE` | "Artifact store unreadable — version list withheld rather than partial." |
| empty-but-valid (no artifacts yet) | `ARTIFACT_NONE_YET` | "This stage has produced no artifacts yet." |
| unknown (provenance unverifiable) | `ARTIFACT_PROVENANCE_UNKNOWN` | "Cannot verify this artifact's origin — refused from the commissioned card." |

## Phase 11 — The demo IS the acceptance test: one CAMPAIGN, end to end

**Done-when:** one executable, auth-ON, outcome-asserted script runs a full multi-stage
CAMPAIGN — including a mid-demo kill-everything and a quiet badge — and every ledger
invariant is green at the end. **Serves NS criteria:** binds ALL 13 (Wave-0 kill gate
realized).

**The script (rewritten as a CAMPAIGN):**
1. Fresh project, auth ON → typed **description**.
2. **Scaffolding proposed** — coarse multi-stage roadmap **with Oranges annotations
   visible**, labelled steward-authored → **batch confirm** (one confirmation, batch
   `step_create`, zero chat persisted — criteria 1, 2).
3. **Stage 1 RESEARCH commission** (researchPrime) proposed FOR the named stage with
   skill + seat + depth shown → confirm records `who` → real run → **validated
   handback** → **reflection receipt** with Oranges prompts → **next-step proposal**
   (criteria 3, 4).
4. **Progressive elaboration:** starting stage 2 fires the predicate → targeted
   questions elaborate it (criterion 5).
5. **CONFIRM-TO-PLAN** (Crucible) → plan artifact renders → **spoken amendment** →
   new version through propose → confirm (criterion 7).
6. **CONFIRM-TO-BUILD** — distinct confirmation bound to the approved plan VERSION →
   Foreman runs → **reflection** → **the Roadmap shows campaign truth** (stage,
   PLANNING/BUILDING beat, live status — criterion 8). Three commissioned skills
   exercised: researchPrime, Crucible, Foreman (criterion 6 exceeded).
7. **MID-DEMO KILL:** kill -9 Anchor + the steward + the live run. **On reopen the
   wake-up brief names the true state** — the stage, the dead run BY NAME, everything
   waiting on John — and re-asks nothing recorded (criterion 11).
8. **Badge round trip:** the `needs_you` moment reaches the ⚑ badge within one poll;
   after the decision the badge returns to quiet (criterion 12).
9. **NEGATIVE ASSERTION:** during BUILDING, the main dashboard receives **no Ecgberht
   signal other than the badge count** — asserted over every non-badge surface
   (criteria 12, 13).
10. **Portfolio at a glance:** with a second registered project present, opening the
    High Seat shows both projects' stage/progress from the index, with a deliberately
    unreadable third root rendering `unknown` and the row count preserved
    (criterion 13).

**Every retained assertion from the draft, unchanged in force:**
- BOTH BEATS asserted: an approved plan alone launches nothing; confirm-to-build names
  its exact plan version; PLANNING vs BUILDING distinguished.
- **SPEND-INVARIANT assertion, envelope form:** every spend event in the demo ledger
  traces to a direct human confirmation (commissions) or to a live confirmed envelope
  with remaining budget (compiles + reflections), with the exhaustion hard-stop
  exercised once mid-demo; the assertion is a ledger query, not a code review.
- Every assertion is an OUTCOME assertion on the user-visible path.
- The demo re-states the Wave-1 audit findings and gate verdicts (A1–A5, G2–G6) and,
  for any FAIL, asserts the degraded shape actually shipped.
- Entire script under ANCHOR_TOKEN, single auth-on suite, no bypass (criterion 9).
- Zero-chat-turn conformance via the Phase-2 versioned allow-list (criterion 1).
- **Ledger invariant checker green at demo end** — including the three new clauses:
  no dangling commission, no done-without-handback, no stale-step silently executed.
- Honest-coverage ratio + provenance spot-check pass rate reported, not hidden.
- Final durability attestation in hardening-law form (named atomic write + named lock +
  concurrency test) as the gate for calling this done (criterion 10).
- A kill -9 during a run converging the Roadmap to truth (criterion 8) — now
  subsumed by, and additionally asserted within, the mid-demo kill-everything.

Deferred: latency targets; multi-box demo; load/soak beyond the required concurrency
tests.

---

## Standing rules (carried from the draft, unweakened)

1. **Hardening law:** any asserted property emits a mechanical gate (test, CI check, or
   ledger query). A property named in a phase and absent from that phase's gates is a
   BLOCKER.
2. **Failure-state discipline:** every surface-bearing phase ships its table with
   `unknown` and `empty` as SEPARATE rows, each naming status code AND user-visible
   text.
3. **Defects in prior-art are fix items, never re-plans** (NS non-goal 1) — this binds
   A3, A4, A5 and anything else the audits surface.
4. **The trio trees and the portfolio-index build are fenced** by the Phase-1 CI diff
   guard; the index is consumed through its public surfaces
   (`query.mjs` / `registry.mjs` / `root-status.mjs` / `anchor-contract.mjs` /
   `brief.mjs`) by name.
5. **Refuted ideas stay dead:** no new handback artifact channel; no bind-and-derive
   rebuild — both exist and are wired, not rewritten.
6. **Adversarial review appears nowhere in the product loop** (NS non-goal) — John is
   the scaffolding's reviewer; commissioned skills carry their own internal rigor.
