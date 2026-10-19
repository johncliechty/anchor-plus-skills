# Crucible-planned project — Implementation Plan (Foreman-ready)

test-command: node scripts/run-all-tests.mjs

**North Star:** NORTH STAR v4 LOCKED 2026-07-31 by John (full file: C:/dev/Anchor/planning/steward-lifecycle-2026-07-31/NORTH-STAR.md).

# NORTH STAR v4 — Anchor steward: campaign orchestration by conversation

> **LOCKED 2026-07-31 by John** (supersedes v1, `NORTH-STAR-v1-superseded.md`).
> Depth FULL · Heavy · cross-family. Anti-drift authority: every element of the
> Master Plan must serve a criterion below.

## Statement

A project in Anchor is stood up, planned across MANY stages, and driven OVER TIME
by talking to its steward. The steward AUTHORS a coarse scaffolding — a campaign
roadmap annotated with Parable-of-the-Oranges prompts — proposed and
batch-confirmed. As the campaign runs it ORCHESTRATES: at each stage boundary it
emits a reflection, proposes how the next stage should be implemented, and asks
for the detail it needs. Stage work is COMMISSIONED from researchPrime / Gandalf /
Crucible / Foreman — never authored by the steward. Reflections and proposals are
TYPED LEDGER ARTIFACTS rendered into conversation, never chat that must survive as
chat. Every project PUBLISHES a typed attention projection, and the High Seat —
reading the ALREADY-BUILT portfolio index — shows LIVE STATUS ACROSS ALL PROJECTS
at a glance, coming forward only when a decision or a deliverable needs John.
Nothing is spent, written or started without a human confirmation, and the
campaign ledger remains the single source of truth.

## Success criteria

1. A spoken description produces a PROPOSED multi-stage scaffolding (coarse steps
   + Oranges annotations), batch-confirmed; zero chat turns persisted.
2. Scaffolding authoring is LIGHTWEIGHT: one confirmed session ENVELOPE covers
   compiles AND orchestrator-loop reflections (each shown; exhaustion hard-stops).
   No per-sentence confirmation dialog.
3. A commission is proposed FOR a named stage showing skill + seat + depth before
   spend; nothing runs until John confirms; the confirmation records `who`.
4. On a validated handback the steward emits a REFLECTION RECEIPT with Oranges
   prompts and PROPOSES the next stage through propose → confirm.
5. PROGRESSIVE ELABORATION: starting a stage triggers targeted questions or an
   offered researchPrime commission — never demanded at scaffold time.
6. One campaign exercises AT LEAST TWO different commissioned skills.
7. Stage artifacts render reviewably; a spoken correction produces a new version
   through propose → confirm.
8. Roadmap status reflects the ACTUAL session state across park, restart, kill.
9. All of it passes with AUTH ON, asserted on outcomes rather than plumbing.
10. `roadmap_events` has exactly ONE writer, proven by a concurrency test.
11. CONTINUITY — from a full restart with every context window gone, opening the
    project produces a steward whose first message states where the campaign is
    (stage, live/dead/waiting runs, everything waiting on John) derived ENTIRELY
    from the ledger, proposes the next step with its why, and asks NO question
    whose answer is already recorded. Proven by a kill-everything-then-resume
    test, including one run that died mid-flight and one handback that never
    arrived — both NAMED, never silently absorbed.
12. ALTITUDE CONTRACT — every project publishes a typed attention projection
    (`working | needs_you | deliverable_ready | blocked | idle`) derived READ-ONLY
    by one engine function. The High Seat folds N projections into the raise queue
    and the ⚑ badge WITHOUT writing to any project store; `needs_you` and
    `deliverable_ready` reach the badge within one poll; a campaign needing
    nothing produces ZERO ambient signals beyond the badge count.
13. PORTFOLIO AT A GLANCE — opening the High Seat shows EVERY ACTIVE PROJECT with
    where it is and what progress has been made (current stage, live/waiting/
    blocked runs, last movement), answered from the EXISTING portfolio index
    WITHOUT walking project roots, so John never digs into a project to learn its
    state. A project that cannot be read reports `unknown`, NEVER a silently
    shorter list. Ambient signalling stays exactly one thing: the ⚑ badge.

## Non-goals

- **Do not re-plan or rebuild the portfolio tracking index.** It is BUILT
  (`planning/steward-tracking-2026-07`, 19 waves GREEN, 671 tests, `engine/portfolio/`
  32 modules incl. the no-walk `query.mjs`). This effort CONSUMES it; a Wave-1
  audit confirms it is live and wired; a defect there is a fix item, not a re-plan.
- Cross-project pause, resource-conflict arbitration, capacity balancing beyond
  what exists, portfolio-level commissioning, any High Seat WRITE path.
- Changes to Crucible / Foreman / researchPrime internals.
- Steward persona/livery, mobile/iPad.
- ~~Anything that makes the steward do the planning itself~~ — REPLACED: the
  steward AUTHORS the scaffolding (coarse, visibly labelled steward-authored) and
  COMMISSIONS stage-level work. The scaffolding is NEVER routed through
  adversarial review — John is its reviewer.
- Adversarial review anywhere in the product loop.

## Risk taxonomy

Second ledger writer · chat-log persistence · auth-off green · unconfirmed spend ·
status drift · seat family/driver collision · scaffolding mistaken for a
commissioned plan · attention FLAPPING near lease TTL (edge-triggered
`state_since` + hysteresis) · ambient badge POLL COST (must use the no-walk index) ·
STALE PACKET served as fresh (`briefCacheStale` keys on Strip only — fix before
wiring raises) · `deliverable_ready` PROVENANCE hole (bundle-hash gated) ·
CONFIRMATION FATIGUE at stage boundaries (the envelope must cover reflections).

## Wave-0 kill gate

> A spoken description → proposed multi-stage scaffolding → batch confirm → stage
> commissioned, executed by Anchor, validated handback → REFLECTION + NEXT-STAGE
> PROPOSAL — on a fresh project, auth ON. And: kill everything, reopen, and the
> steward names the true state without re-asking.

## Prior art this effort MUST build on (verified 2026-07-31)

| Artifact | Status |
|---|---|
| `Ecgberht/planning/steward-tracking-2026-07` | Crucible FULL/Heavy, NS locked 2026-07-27, Stage 2 approved, Foreman **19 waves GREEN**, 671 tests |
| `engine/portfolio/*` (32 modules) | BUILT — incl. `query.mjs` no-walk queries, `registry`, `inventory`, `root-status`, `doctor`, `anchor-contract` |
| `Ecgberht/NEXT-UX-AND-ANCHOR-ORCHESTRATION.md` | John's LOCKED intent 2026-07-24 — §A project steward, §B portfolio/High Seat |
| `engine/brief.mjs assembleBriefPacket` | BUILT — Q1–Q12 cold-start reconstruction, zero model calls, honest-unknown |
| `engine/high-seat.mjs` / `rank.mjs` | BUILT — raise tiers, MAX_RAISED_BLOCKS=1, tile pills, `write_authority:'none'` |


## Success criteria
- 1. Spoken description → PROPOSED multi-stage scaffolding (coarse steps + Oranges annotations), batch-confirmed; zero chat turns persisted.
- 2. Scaffolding authoring LIGHTWEIGHT: one confirmed session ENVELOPE covers compiles AND orchestrator-loop reflections (each shown; exhaustion hard-stops). No per-sentence confirmation dialog.
- 3. Commission proposed FOR a named stage showing skill + seat + depth before spend; nothing runs until John confirms; confirmation records who.
- 4. On validated handback: REFLECTION RECEIPT with Oranges prompts + PROPOSE next stage through propose→confirm. **QUEUED-vs-EMITTED (contradiction resolved, Stage-1 Decision 1 restated):** the typed reflection RECEIPT is ALWAYS EMITTED at handback — it is a deterministic, zero-model, zero-spend ledger artifact derived from the dossier, so criterion 4's "emits a reflection receipt" is never deferred. What is QUEUED when no live envelope exists is only the two model-spending steps: the NL reflection COMPILE and the next-stage PROPOSAL. Both fire at next session open inside a confirmed envelope. Emitted-always / compiled-when-funded — the receipt is never withheld and no unattended spend ever occurs.
- 5. PROGRESSIVE ELABORATION: starting a stage triggers targeted questions or offered researchPrime commission — never demanded at scaffold time.
- 6. One campaign exercises AT LEAST TWO different commissioned skills.
- 7. Stage artifacts render reviewably; spoken correction → new version through propose→confirm.
- 8. Roadmap status reflects ACTUAL session state across park, restart, kill.
- 9. All of it passes with AUTH ON, asserted on outcomes rather than plumbing.
- 10. roadmap_events has exactly ONE writer, proven by a concurrency test.
- 11. CONTINUITY: full restart with every context gone → first message states campaign state from ledger only; no re-ask; dead run + missing handback NAMED.
- 12. ALTITUDE CONTRACT: typed attention projection (working|needs_you|deliverable_ready|blocked|idle) from one pure read-only function; High Seat fold write_authority none; badge within one poll; zero ambient beyond badge.
- 13. PORTFOLIO AT A GLANCE from EXISTING portfolio index (no root walk); unreadable → unknown row, never silently shorter list. Consume index — do NOT re-plan/rebuild (A5 Wave-1 audit; Stage-1 Decision 2).
- GATE DECISIONS: (1) unattended reflection COMPILE + PROPOSAL queue (the receipt itself always emits — see criterion 4); (2) A5 audit not re-plan, upgraded to a field-by-field coverage matrix with a CAPPED fix-item budget and DEGRADED naming beyond the cap (Wave 3 / Wave 16); (3) briefCacheStale FIXED in Wave 1 under the named-fix diff fence; (4) **G4 FAIL is an explicit HALT** — a machine-readable verdict file mechanically blocks Waves 10–18 unless the verdict is PASS or an ANCHOR-OWNED fallback executor carrying identical auth-ON / confirmed-only / observed-pid / dossier-write obligations is recorded (Wave 4); (5) **the attention projection publish seam is named** — pure derivation (one function, zero writes) is separated from delivery (the project's own single writer publishing into the already-built index), which is how criteria 12 and 13 are simultaneously true (see the seam table below); (6) **commissionable skills are selected from a machine-readable intersection table** (executor-proven ∧ no excluded HALT class), test-bound at Waves 13 and 18 — fewer than two commissionable rows HALTs rather than silently picking; (7) **an early vertical slice proves criteria 1–4 before the spine exists**, under a hard FIXTURE-ONLY rule with zero durable `roadmap_events` writes; (8) audits and spikes run OFF the critical path in declared parallel lanes.
- NON-GOALS: no portfolio-index rebuild; no High Seat WRITE; no Crucible/Foreman/researchPrime internals; no adversarial review in product loop; no unattended spend; refuted e-1/e-4 stay dead.
- BUILD-vs-WIRE: Ecgberht propose/confirm/bind, packet-view, receipt-validate, brief.assembleBriefPacket, high-seat, rank, engine/portfolio/* are BUILT — wire/audit/fix. MISSING: Anchor commission executor (.py), dialogue→step_create, attention emitters, deliverable_ready state, chamber UI steps/proposal/confirm/artifact.
- HARDENING: every asserted property emits a mechanical gate; every surface wave has a failure-state table with unknown≠empty; durability = named atomic write + lock + concurrency test that fails if either is removed. Every property-gate checkbox is mapped to an owning wave, a named deliverable and a done-when clause in the obligation map below — an unmapped checkbox is a BLOCKER.

## Schedule, critical path and the PRE-SPINE FIXTURE-ONLY rule

`Depends on:` encodes the machine-checkable DAG. The lanes below declare what a multi-lane run may execute concurrently; a single-lane run simply follows wave order and violates nothing.

| Lane | Waves | Gate into the next lane |
|---|---|---|
| **A — substrate (critical path)** | 1 Ground truth I → 3 Ground truth II → 6 Ledger spine → 7 Dossier / 8 Scaffolding → 9 Envelope → 10 Commission proposal → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18 | each wave's done-when |
| **B — proving slice (off path)** | 2 Vertical slice (fixture-only) | informs Waves 8–13 shape; ships nothing durable |
| **C — executor + substrate verdict (off path, joins at 10)** | 4 BUILD-E / G4 | `g4-verdict.json` verdict=PASS (or Anchor-owned fallback) — **mechanically blocks Waves 10–18** |
| **D — decision records and spikes (off path, joins at 5→9/10/17)** | 5 Spikes: G2 / G3 / G5 / G6, step-type map, envelope calibration | decision records + `commissionable-skills.json` HALT-class column |

**PRE-SPINE FIXTURE-ONLY RULE (normative).** Any wave that exercises campaign behaviour BEFORE the ledger spine (Wave 6) — today that is Wave 2 only — runs against a temp-directory fixture ledger and MUST NOT write a durable `roadmap_events` record, mint a real `job_id`, or spend. Enforced mechanically, not by convention: (a) the slice suite imports the store only through an injected fixture handle and a module guard throws if the real durable path is resolved; (b) a CI test snapshots the real `roadmap_events` file hash before and after the slice suite and FAILS on any difference; (c) the slice's executor seam is a stub — the real executor is Wave 4 and refuses unconfirmed commissions. When the spine lands, the slice's assertions are re-pointed at the real spine in Waves 8–13; the fixture suite is retained as the fast regression harness, never as the proof of criteria 1–4.

## Attention projection publish seam (criteria 12 AND 13 simultaneously)

Criterion 12 demands the projection be *derived READ-ONLY by one engine function*. Criterion 13 demands the High Seat answer *from the EXISTING index WITHOUT walking project roots* — which requires the projection to have been DELIVERED into that index, i.e. written. Both are true only if derivation and delivery are different acts with different owners. That is this table; it is the contract Waves 15 and 16 are built against.

| Seam element | Exact mechanism | Owning wave |
|---|---|---|
| **Derivation** | `deriveAttention(ledgerView) -> { state, state_since, reason, provenance }` — ONE engine function, PURE: zero writes, zero model calls, zero I/O beyond the passed-in view. Asserted by a write-trap test. | 15 |
| **Publish writer** | `publishAttention()` — the ONLY code allowed to persist a projection, and it persists exclusively through the Wave-6 single-writer spine. It is not a second writer; the Wave-6 CI invariant check covers it. | 15 |
| **Event** | `attention_projection_published { state, state_since, derived_from_event_seq, bundle_hash? }` appended to `roadmap_events`, emitted ONLY on an EDGE (state or `state_since` change). A republish with no change appends nothing — the idempotence gate. | 15 |
| **Published cell** | the project's typed `attention` cell, written in the SAME journaled transaction as the event (never a separate second write). | 15 |
| **Index delivery** | DERIVED ingest into the already-built portfolio index via the existing `engine/portfolio/anchor-contract.mjs` seam (A5 proves it fires on a live write). The project PUSHES; the index never walks and is never rebuilt. | 3 (audit) → 15 (wire) |
| **Read API** | `engine/portfolio/query.mjs` no-walk read returning `{ project, stage, runs{live,waiting,blocked}, last_movement, attention }` per project — the single read surface for the High Seat. | 16 |
| **High Seat** | folds N rows from that API into the raise queue and the ⚑ badge with `write_authority:'none'`; tests assert zero writes to any project store and zero project-root traversals. | 16 |

**Scope correction:** Wave 15's purity claim applies to `deriveAttention` ONLY — derivation, not delivery. Any plan text implying the whole projection path is write-free is superseded by this table.

## Commissionable-skill intersection (machine-readable, test-bound)

`artifacts/commissionable-skills.json` — one row per candidate skill:

`{ skill, executor_proven: bool, executor_evidence: {pid, handback_id}|null, halt_class: "EXTERNALLY-OBSERVABLE"|"REQUIRES-TRIO-CHANGE"|"INVISIBLE", excluded_reason: string|null, commissionable: bool }`

`commissionable === (executor_proven === true && halt_class === "EXTERNALLY-OBSERVABLE")`. The `executor_proven` column is written by Wave 4 from observed evidence; the `halt_class` column by Wave 5's G5 HALT inventory. No prose may set either. Consumers are TEST-BOUND, never hand-picked: Wave 13's multi-skill proof and Wave 18's two-skill campaign both read this file and select only rows with `commissionable: true`. If `count(commissionable) < 2` at either point, the wave HALTs for a human scope decision — it never substitutes a skill, never downgrades the criterion, and never proceeds on one skill.

## Property-gate obligation map (checkbox → owning wave → deliverable → done-when)

| Property | Gate checkbox | Owning wave | Deliverable it lives in | Bound by done-when |
|---|---|---|---|---|
| durability | atomic write (temp + fsync + rename) | 1, 6 | named atomic-write helper; spine append path | W1 removal-proof test; W6 one-writer test |
| durability | lock / documented serialization | 1, 6 | named lock helper; spine lock | W1 removal-proof test; W6 one-writer test |
| durability | a concurrency test | 1, 6 | target-box hammer (N×M); spine N writers × M events | both must FAIL if lock or atomic write is removed |
| honesty | a failure-state table | 2,4,6,7,8,9,10,11,12,13,15,16,17 | per-wave failure-state table | each wave's done-when |
| honesty | unknown and empty as SEPARATE rows | 16, 17 | full FIVE-state surface tables (High Seat, chamber) | W16/W17 done-when |
| idempotence | a repeat-invocation test | 8, 9, 10, 13, 15 | double-submit tests: batch-confirm (W8), envelope-confirm (W9), commission-confirm (W10), handback re-delivery (W13), projection republish (W15) | each wave's done-when |
| boundedness | the numeric bound named | 6, 9, 16 | `ROADMAP_EVENTS_MAX = 50000` (W6); `ENVELOPE_MAX_SPEND_USD = 5.00`, `ENVELOPE_MAX_COMPILES = 25`, `ENVELOPE_TTL_MINUTES = 240` (W9); `PORTFOLIO_MAX_ROWS = 500` (W16) | each wave's done-when |
| boundedness | a refusal path when exceeded | 6, 9, 16 | `events-bound-exceeded`; `envelope-exhausted`; `portfolio-bound-exceeded` (named, never truncated silently) | each wave's done-when |
| containment | escape-attempt test (`..`, absolute, symlink) | 7, 17 | dossier/artifact path resolver confined to the project root; chamber artifact read | W7/W17 done-when |

> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).

## Wave 1 — Ground truth I — durability law, auth ON, trio/index fence, briefCacheStale fix

**Intent:** Establish the non-negotiable substrate before any feature code: a proven storage primitive on the target box, an auth-ON-only suite, a CI fence that keeps this effort out of the trio and the already-built portfolio index, and the A3 defect fixed in Wave 1 as John's gate decision requires.

**Deliverables:** Storage-primitive hammer test on the TARGET box (Windows, scanner + sync running): N concurrent appenders x M records asserting zero torn/lost/duplicated records; FAIL branch escalates to SQLite WAL, never a hardened file; Durability stated in hardening-law form: named atomic write helper + named lock helper + a concurrency test that FAILS if either is removed (removal-proof test); Auth flipped ON: one suite, no auth-off variant; negative auth tests (absent / expired / wrong-principal / revoked) as first-class cases; CI guard that fails the build on any bypass flag; CI diff guard: build fails if the effort modifies any file under the Crucible, Foreman or researchPrime trees, or under Ecgberht/planning/steward-tracking-2026-07 and engine/portfolio/ beyond an explicit named-fix allow-list; A3 FIX in engine/brief.mjs: briefCacheStale staleness key extended from Strip-only (as_of + instruments.length + receipts.length) to include roadmap event count + Face version, entered as a named fix item on the diff-fence allow-list; Regression test: mutate ONLY the roadmap (and separately ONLY the Face) and assert the cached packet reports stale rather than serving further_gathering:false

**Depends on:** —

**done-when:** The concurrency hammer, the removal-proof durability test, the auth-ON negative tests and the A3 staleness regression tests are all green in one auth-ON suite, and the CI diff guard fails a deliberate out-of-fence edit while passing the named A3 fix.

- **Given** A roadmap-only change lands on a project whose brief packet is already cached, **when** assembleBriefPacket is called again, **then** briefCacheStale reports stale and a fresh packet is assembled instead of serving the cached packet stamped further_gathering:false
- **Given** A branch that edits a file under the Foreman tree (or under engine/portfolio/ outside the named-fix allow-list), **when** CI runs the diff guard, **then** the build FAILS naming the offending path, while the same run passes for the allow-listed A3 fix in engine/brief.mjs
- **Given** The atomic-write helper or the lock helper is deleted from the durability path, **when** the concurrency suite runs on the target box with scanner and sync active, **then** the test fails loudly (no prose-only durability claim can pass this gate)

## Wave 2 — Vertical slice (FIXTURE-ONLY) — describe → propose → batch-confirm → commission → handback → reflection

**Intent:** Prove the SHAPE of criteria 1–4 end to end in one narrow slice before the spine, the executor or any UI exists, so the loop's real integration risk surfaces at Wave 2 instead of Wave 13 — while writing nothing durable and spending nothing unconfirmed.

**Deliverables:** Fixture ledger harness: a temp-directory typed-event store with the same event shapes the spine will own, injected (never resolved from the real project root); FIXTURE-ONLY enforcement — a module guard that throws if the durable roadmap_events path is resolved from slice code, plus a CI test that hashes the real roadmap_events file before and after the slice suite and FAILS on any difference; End-to-end slice over the fixture: typed NL description -> compiled coarse scaffolding with Oranges annotations (criterion 1) -> ONE batch confirmation with who (criterion 2 shape) -> a commission PROPOSAL rendering skill + seat + depth for a named step (criterion 3) -> a STUB executor returning a canned validated handback -> a deterministically EMITTED reflection receipt plus a queued next-stage proposal (criterion 4, emitted-vs-queued split); Zero-chat-persistence assertion inside the slice: only typed events exist after the run; Stub-executor honesty: the stub is NAMED as a stub in every artifact it produces and refuses to run on an unconfirmed commission, so the slice can never be mistaken for the G4 proof; Slice findings recorded as a checked-in shape report feeding Waves 8-13, with any surprise entered on the fix-item ledger; Failure-state table for the slice: compile-failed / confirm-refused / stub-handback-invalid / reflection-blocked, unknown distinct from empty

**Depends on:** Ground truth I — durability law, auth ON, trio/index fence, briefCacheStale fix

**done-when:** The whole describe → propose → batch-confirm → commission → handback → reflection loop runs green over the fixture ledger under auth ON, with zero durable roadmap_events writes proven by the before/after hash test and zero spend outside a stub.

- **Given** A typed NL description on a fixture project, **when** the slice runs the full loop to a canned validated handback, **then** a proposed scaffolding, a batch confirmation recording who, a commission proposal showing skill + seat + depth, an emitted reflection receipt and a queued next-stage proposal all exist as typed fixture events, and no chat turn is persisted
- **Given** The real project store, **when** the slice suite runs to completion, **then** the roadmap_events file is byte-identical before and after, and a deliberate attempt to resolve the durable path from slice code throws at import time
- **Given** The slice's stub executor, **when** it is handed a commission that is proposed but not confirmed, **then** it refuses, and every artifact it does produce is labelled STUB so no slice output can be read as the G4 verdict

## Wave 3 — Ground truth II — A1/A2/A4/A5 audit harnesses and the fix-item ledger

**Intent:** Prove empirically what the INTAKE ledger asserts about the BUILT Ecgberht/portfolio halves by driving them from executable audit harnesses against real fixtures, producing checked-in seam tables and a fix-item list — audits, never re-plans (NS non-goal 1).

**Deliverables:** A1 commission-half wiring audit harness: executable probe driving proposeCommission (:141) / confirmCommission (:250) and verbCommissionPropose (:769) / verbCommissionConfirm (:836), emitting a checked-in table of actual parameters, returns and the wiring seams Anchor must call; A2 assembleBriefPacket coverage harness: a REAL campaign fixture (Face + Strip + roadmap + commission dossier + one dead run) driven through Q1-Q12, emitting a coverage table of which continuity facts are answered today vs which need the dossier join; A4 non-atomic confirm-pair defect harness: a kill-between-writes probe over job-lifecycle.mjs:929-944 demonstrating a roadmap-bound commission with no Strip receipt; recorded as a defect row, fix scheduled for the ledger-spine wave; A5 portfolio-index liveness audit: assertions that the index home resolves, the snapshot exists and rebuilds, steward query answers over the REAL portfolio without walking roots, engine/portfolio/anchor-contract.mjs is reachable, and DERIVED ingest fires on a live write; A5 FIELD-BY-FIELD COVERAGE MATRIX (the upgrade — liveness alone is not enough): for EVERY project in the real portfolio the harness emits one row per criterion-13 field — `stage`, `runs.live`, `runs.waiting`, `runs.blocked`, `last_movement` — each marked ANSWERED | PARTIAL | ABSENT with the index key that answered it, plus a per-field `no_walk: true|false` observation; the matrix is the checked-in input Wave 16 is built against, so no criterion-13 field can be discovered missing at the High Seat; A5 attention-delivery probe: whether the existing anchor-contract ingest seam can carry the new `attention` cell, marked ANSWERED or NEEDS-WIRE (wired in Wave 15, never re-planned); CAPPED FIX-ITEM BUDGET: at most 6 A5 fix items totalling at most 2 waves of scheduled effort, each with defect id, evidence file:line and owning wave; if the matrix produces more than the cap, the effort does NOT silently absorb them and does NOT re-plan the index — Wave 16 ships DEGRADED with the uncovered fields rendered as named `unknown` and the overflow raised as a HALT for John's scope decision; Single checked-in FIX-ITEM LEDGER holding the A1/A2/A4/A5 rows, every A5 gap scheduled before the portfolio-at-a-glance wave needs the index, and the DEGRADED list named explicitly if the cap is hit

**Depends on:** Ground truth I — durability law, auth ON, trio/index fence, briefCacheStale fix

**done-when:** All four audit harnesses run green under auth ON against real fixtures, their seam/coverage tables — including the A5 field-by-field matrix covering stage / live / waiting / blocked / last_movement for every real project — are checked in, and every discovered gap either appears in the fix-item ledger within the 6-item / 2-wave cap with an owning wave, or is named on the DEGRADED list with a HALT raised — with no rebuild of the portfolio index.

- **Given** A real campaign fixture containing one run that died mid-flight, **when** the A2 harness drives assembleBriefPacket across Q1-Q12 with zero model calls, **then** the emitted coverage table marks each continuity fact as ANSWERED or NEEDS-DOSSIER-JOIN and no fact is silently reported as answered when the packet returns honest-unknown
- **Given** The live portfolio index built by steward-tracking-2026-07, **when** the A5 audit runs steward query and then performs a live write, **then** the query answers from the no-walk index (no project-root traversal observed) and DERIVED ingest is observed firing on the write; any gap is emitted as a fix-item row, never a re-plan
- **Given** A confirmed commission interrupted between writeProjectRoadmap and the Strip writeFileAtomicSync, **when** the A4 probe restarts and reads both stores, **then** the harness demonstrates the orphaned bind and records the defect row with file:line evidence
- **Given** The real portfolio, **when** the A5 field-by-field matrix is emitted, **then** every project has a row for each of stage / runs.live / runs.waiting / runs.blocked / last_movement marked ANSWERED, PARTIAL or ABSENT with its answering index key, and if more than 6 fix items result the overflow is named on the DEGRADED list with a HALT rather than being absorbed into this effort's scope

## Wave 4 — BUILD-E — the Anchor commission executor and the G4 substrate verdict

**Intent:** Build the verified-ABSENT Anchor half: a minimal executor that takes a CONFIRMED commission and drives a real trio run headlessly through job_runner.py / terminal_session.py / lanes.py, and settle G4 (can the substrate host a commissioned trio run under the steward) on observed evidence.

**Deliverables:** Minimal Anchor commission executor (.py): CONFIRMED commission -> real trio run launched through job_runner.py, using terminal_session.py and lanes.py, with one-run-at-a-time as the declared DEGRADED mode; Integration test asserting an OBSERVED pid and a RETURNED handback for one confirmed commission end to end; MACHINE-READABLE G4 GATE — `artifacts/g4-verdict.json { verdict: "PASS"|"FAIL", path: "substrate"|"anchor-fallback", pid, handback_id, evidence_paths[], recorded_at }`, written from observed evidence only (PASS requires BOTH an observed pid and a returned handback; no prose may set it); G4 FAIL IS AN EXPLICIT HALT, MECHANICALLY ENFORCED: a precondition test shipped in this wave and imported by Wave 10 reads g4-verdict.json and FAILS the build unless `verdict === "PASS"`, which blocks Waves 10-18 — the entire commissioning half — from running on an unproven substrate; the only non-HALT alternative is an ANCHOR-OWNED fallback executor recorded as `path: "anchor-fallback"`, which is in scope ONLY if it discharges IDENTICAL obligations proven by the SAME test suite (auth ON, refuses anything not confirmed, observed pid recorded, handback returned and written into the commission dossier, full failure-state table); a fallback that cannot meet all five obligations is not a fallback — it HALTs for John's scope decision, and no wave may proceed by declaring the substrate question deferred; Executor-proven column emitted into `artifacts/commissionable-skills.json` (one row per skill actually driven to an observed pid + returned handback, with its evidence) — the executor writes only this column, never `commissionable`; Executor refuses to start on anything that is not a confirmed commission (no spend without confirmation), with a negative test; Failure-state table for the executor path: launch-refused / launched-then-died / no-handback, each a NAMED state distinct from empty

**Depends on:** Ground truth II — A1/A2/A4/A5 audit harnesses and the fix-item ledger

**done-when:** A confirmed commission drives a real trio run through job_runner.py to an observed PID and a returned handback under auth ON, `g4-verdict.json` records PASS from that evidence, and the precondition test that Waves 10-18 import passes only because of it.

- **Given** A commission record that has been confirmed with a recorded who, **when** the Anchor executor is invoked for it, **then** a real trio run starts through job_runner.py, its PID is observed and recorded, and the returned handback is captured
- **Given** A commission record that is proposed but NOT confirmed, **when** the executor is invoked for it, **then** the executor refuses to launch, nothing is spent, and the refusal is a named state in the failure-state table
- **Given** A launched run that dies before producing a handback, **when** the executor polls its lane, **then** the state reports launched-then-died by name rather than an empty or absent result
- **Given** A g4-verdict.json recording verdict FAIL with no Anchor-owned fallback meeting all five obligations, **when** any wave from 10 onward runs its precondition test, **then** the build FAILS with the G4 HALT named, no commissioning wave proceeds, and the only ways forward are a PASS verdict or an explicit scope decision from John — never a deferred substrate question

## Wave 5 — Decision records and spikes — G2 render, G3 handback, G5 HALT, G6 identity, step-type map, envelope calibration

**Intent:** Settle the remaining honest hypotheses and lock the decision records the later waves bind to, each backed by executable spikes rather than prose, and gather the compile-cost data that calibrates the session envelope.

**Deliverables:** G2 artifact-rendering spike: a REAL converged Crucible doc-trio fed through packet-view.mjs classifyArtifact / buildArtifactCard, verbatim verdict recorded; FAIL routes a plan-shaped renderer into the chamber-UI wave; G3 handback-validation spike: receipt-validate.mjs observed passing a real trio handback (6 campaign-memory fields) and REFUSING a corrupted one, both as tests; G5 HALT inventory + classification: every human gate on the real Crucible/Foreman/researchPrime/Gandalf commission path listed at file:line and classed EXTERNALLY-OBSERVABLE / REQUIRES-TRIO-CHANGE / INVISIBLE, with the gate budget locked against that table and any INVISIBLE-HALT profile named as excluded from v1 in the Face; this classification is written as the `halt_class` + `excluded_reason` columns of `artifacts/commissionable-skills.json`, and the file's derived `commissionable` flag (executor_proven ∧ halt_class = EXTERNALLY-OBSERVABLE) is computed by a checked-in function with a unit test — never hand-edited; G6 identity resolution: does ANCHOR_TOKEN carry a recoverable subject; FAIL -> who = unattributed(shared_secret) rendered honestly; spend-confirmation events record the credential CLASS; no IdP built; Decision record — step-type -> skill -> confirmation map: RESEARCH -> researchPrime, PLAN -> Crucible, BUILD -> Foreman, REVIEW -> Gandalf (dispatch-table entry only); CONFIRM-TO-PLAN binds a step ULID, CONFIRM-TO-BUILD binds an approved plan artifact VERSION; a plan handback NEVER auto-flows into a build, enforced by a test; Compile-cost measurement over >=20 real compiles (median + p90 $, wall clock, confirmations-per-useful-Face-version) emitted as a machine-readable calibration record; it gates nothing, but Wave 9 MUST import it and the named envelope defaults (ENVELOPE_MAX_SPEND_USD, ENVELOPE_MAX_COMPILES) must be justified against p90 in a checked-in note; Face glossary line: 'talking' = typed NL chat in the Anchor UI, ASR out of scope; amendment-vs-recommission decision recorded in the Face

**Depends on:** Ground truth I — durability law, auth ON, trio/index fence, briefCacheStale fix

**done-when:** Every spike has a checked-in verdict backed by a passing test, the step-type/confirmation map and identity decision are recorded as machine-readable records the later waves import, the G5 HALT-class column of `commissionable-skills.json` is written, and the >=20-compile calibration dataset exists with the named envelope defaults derived from it.

- **Given** An approved plan artifact returned as a PLAN handback, **when** the lifecycle attempts to flow it onward, **then** no BUILD is started automatically; a CONFIRM-TO-BUILD bound to that artifact VERSION is required, proven by a test that fails if auto-flow is reintroduced
- **Given** A real converged Crucible doc-trio, **when** it is passed through classifyArtifact and buildArtifactCard, **then** the verbatim classification and card output are recorded as the G2 verdict, and a FAIL verdict adds the plan-shaped renderer to the chamber-UI wave scope
- **Given** An ANCHOR_TOKEN with no recoverable subject, **when** a spend confirmation is recorded, **then** who is written as unattributed(shared_secret) with the credential CLASS, and it renders that way rather than fabricating an identity

## Wave 6 — Ledger spine — one writer for roadmap_events, typed-store allow-list, invariants in CI

**Intent:** Give the campaign ledger exactly one writer and prove it, so every later wave writes through a single journaled spine and the second-ledger-writer risk is structurally dead.

**Deliverables:** Single-writer spine module owning all roadmap_events appends; every other module writes through it (direct-write attempts fail a static/CI check), including Wave 15's publishAttention — the projection publisher is a CALLER of this writer, never a second one; Typed-store ALLOW-LIST: only declared typed stores are writable; an undeclared store write is refused with a named error; Concurrency test proving ONE writer: N concurrent writers x M events, asserting total ordering, zero interleaved corruption, zero lost events — and that the test FAILS if the lock or the atomic write is removed; APPEND IDEMPOTENCE PRIMITIVE: every append carries a caller-supplied `client_event_id`; a re-append of the same id is a no-op returning the original sequence number, with a repeat-invocation test — this is the primitive the Wave 8/9/10/13/15 double-submit tests are built on; NAMED BOUND: `ROADMAP_EVENTS_MAX = 50000` events per project ledger, with a refusal path `events-bound-exceeded` (named, surfaced, never a silent truncation or an unbounded read) and a bounded-read API that refuses rather than loading past the bound; CI invariant check wired into the auth-ON suite: no second writer, no untyped store, no chat-turn persistence; Named failure states for the spine (lock-contended / store-not-declared / write-refused / events-bound-exceeded) with unknown distinguished from empty

**Depends on:** Ground truth II — A1/A2/A4/A5 audit harnesses and the fix-item ledger

**done-when:** roadmap_events has exactly one writer proven by a passing concurrency test, a repeat append of the same client_event_id is a proven no-op, the 50000-event bound refuses by name, and CI fails any branch that introduces a second writer or an undeclared store.

- **Given** N concurrent processes each appending M roadmap events, **when** the concurrency test runs on the target box, **then** every event appears exactly once in a total order with no torn or lost records, and removing the lock or the atomic write makes the test fail
- **Given** A module that appends to roadmap_events without going through the spine, **when** CI runs the invariant check, **then** the build fails naming the offending call site
- **Given** A write aimed at a store that is not on the typed allow-list, **when** the spine receives it, **then** it is refused with a named error and nothing is persisted
- **Given** An append that has already been committed, **when** the identical client_event_id is submitted again, **then** no second event is written, the original sequence number is returned, and a ledger at ROADMAP_EVENTS_MAX refuses further appends with the named events-bound-exceeded state

## Wave 7 — Commission dossier — one key across the lifecycle, atomic confirm pair (A4 fix)

**Intent:** Join propose -> confirm -> run -> handback under a single dossier key on the single-writer spine, and make the confirm pair crash-safe so a bound commission can never exist without its receipt.

**Deliverables:** Commission dossier store keyed by job_id/commissioned_as, joining proposal, confirmation (with who), launch record (pid), and handback under one key; A4 FIX: writeProjectRoadmap + Strip receipt become one journaled transaction (or a crash-repairable pair with a named repair path) through the spine; Kill-between-writes test: process killed between the roadmap write and the Strip write; on restart the state is either fully committed or fully repaired, never a bind with no receipt; Dossier read API used by later waves (rehydration, attention projection) returning honest-unknown for absent facts; CONTAINMENT: the dossier + handback + artifact path resolver confines every read and write to the owning project root, with ESCAPE-ATTEMPT TESTS for `..` traversal, an absolute path outside the root, and a symlink/junction pointing outside — each refused with the named `path-escape-refused` state (a handback is untrusted input; this is the wave that treats it that way); Failure-state table: dossier-missing / dossier-partial / repair-applied / path-escape-refused, each named

**Depends on:** Ledger spine — one writer for roadmap_events, typed-store allow-list, invariants in CI

**done-when:** The whole commission lifecycle is readable under one dossier key, a kill-between-writes test proves the confirm pair is atomic or crash-repairable with no orphaned bind, and the three escape-attempt tests (`..`, absolute, symlink/junction) are refused by name.

- **Given** A commission being confirmed, **when** the process is killed between the roadmap write and the Strip receipt write, **then** on restart the dossier reads as either fully confirmed with receipt or cleanly repaired, and the A4 defect row closes against this test
- **Given** A commission that was proposed, confirmed, launched and handed back, **when** the dossier is read by its key, **then** all four lifecycle facts return under that one key, with who and pid present
- **Given** A handback naming an artifact path that escapes the project root via `..`, an absolute path, or a symlink/junction, **when** the dossier resolver reads it, **then** each attempt is refused with the named path-escape-refused state and nothing outside the root is read or written

## Wave 8 — Scaffolding authoring — dialogue to step_create, coarse roadmap proposed and batch-confirmed

**Intent:** Turn a spoken description into a PROPOSED multi-stage scaffolding with Oranges annotations that John batch-confirms in one action, authored by the steward, visibly labelled steward-authored, with zero chat turns persisted.

**Deliverables:** dialogue -> step_create path: NL description compiled into coarse roadmap steps with Oranges annotation fields, emitted as a typed PROPOSAL event through the spine; Batch-confirm verb: one confirmation binds the whole proposed scaffolding, recording who; nothing is written to the roadmap before confirmation; Steward-authored provenance flag on every scaffolded step so it can never be mistaken for a commissioned plan (NS risk taxonomy); Zero-chat-persistence test: after a full describe-and-confirm session, no chat turn exists in any store; only typed events; Scaffolding is NEVER routed through adversarial review — asserted by a test that no review path is reachable from the scaffolding compile; Failure-state table: compile-failed / proposal-rejected / partially-confirmed(refused), unknown distinct from empty

**Depends on:** Ledger spine — one writer for roadmap_events, typed-store allow-list, invariants in CI

**done-when:** A spoken description produces a proposed multi-stage scaffolding with Oranges annotations that a single batch confirmation commits to the roadmap, with zero chat turns persisted, and a double-submitted batch confirmation commits exactly once.

- **Given** A fresh project and a typed NL description of a multi-stage effort, **when** the steward compiles it, **then** a PROPOSED scaffolding of coarse steps with Oranges annotations is emitted as a typed event, marked steward-authored, and nothing is yet written to the roadmap
- **Given** A proposed scaffolding awaiting review, **when** John issues ONE batch confirmation, **then** all steps are committed through the single-writer spine with who recorded, and no per-sentence confirmation dialog was required
- **Given** A completed describe-and-confirm session, **when** every store is scanned, **then** zero chat turns are persisted and the campaign state is reconstructable from typed events alone
- **Given** A batch confirmation that has already committed a proposed scaffolding, **when** the identical confirmation is submitted a second time (double-click, retry, replayed request), **then** no duplicate steps and no second commit event are written, the response reports already-confirmed by name, and the ledger is byte-identical to the single-submit case

## Wave 9 — Session envelope — one confirmed budget covering compiles and orchestrator reflections

**Intent:** Implement the confirmed compile ENVELOPE that makes authoring lightweight: John confirms one bounded session budget at session start; every compile and every orchestrator-loop reflection is SHOWN but not re-authorized; exhaustion is a hard stop.

**Deliverables:** Session envelope object with NAMED NUMERIC BOUNDS (the boundedness gate — an unnamed bound cannot be tested): `ENVELOPE_MAX_SPEND_USD = 5.00`, `ENVELOPE_MAX_COMPILES = 25`, `ENVELOPE_TTL_MINUTES = 240`, whichever is reached first; the defaults are justified against the Wave-5 p90 calibration in a checked-in note and are confirmed once at session open as a typed event with who; Envelope enforcement in the spend path: spend permitted only inside a live envelope; every compile AND every orchestrator-loop reflection debits it and is individually SHOWN (observability, not authorization); REFUSAL PATH for each bound: `envelope-exhausted` ($ or compile count) and `envelope-expired` (TTL) are named, rendered, and hard-stop all further spend until a fresh envelope confirmation — never a silent degrade and never a partial compile; Envelope-confirm IDEMPOTENCE: a double-submitted envelope confirmation mints exactly one envelope (repeat-invocation test on the Wave-6 client_event_id primitive), so a retry can never double John's budget; Commissions are explicitly NOT covered by the envelope — a test asserts a commission still requires its own confirmation even inside a live envelope; No-live-envelope path: the reflection COMPILE and next-stage PROPOSAL are QUEUED as typed events and never spend (gate Decision 1), while the deterministic reflection receipt still emits (criterion 4, Wave 13); Failure-state table: envelope-absent / envelope-exhausted / envelope-expired, each named and rendered

**Depends on:** Scaffolding authoring — dialogue to step_create, coarse roadmap proposed and batch-confirmed

**done-when:** One confirmed envelope covers a full authoring session's compiles and reflections with each shown, each of the three named bounds ($5.00 / 25 compiles / 240 minutes) hard-stops by name when reached, a double-submitted envelope confirmation mints exactly one envelope, and no spend of any kind occurs outside a live envelope.

- **Given** A session opened with one confirmed envelope, **when** the steward performs several compiles and an orchestrator-loop reflection, **then** each is shown to John and debits the envelope, and no additional confirmation dialog is raised
- **Given** An envelope whose budget is exhausted, **when** another compile or reflection is attempted, **then** it hard-stops with the named envelope-exhausted state and spends nothing until a fresh envelope is confirmed
- **Given** A live session envelope, **when** a commission is proposed, **then** the commission still requires its own individual confirmation recording who, and the envelope does not authorize it
- **Given** An envelope confirmation submitted twice, and separately an envelope past ENVELOPE_TTL_MINUTES, **when** each is exercised, **then** exactly one envelope exists in the first case and the second refuses with the named envelope-expired state, spending nothing

## Wave 10 — Commission proposal in Anchor — skill, seat and depth shown before spend

**Intent:** Wire the audited Ecgberht propose/confirm/bind verbs into the Anchor steward loop so a commission is always proposed FOR a named roadmap step, showing skill + seat + depth before any spend, and only runs after John confirms with who recorded.

**Deliverables:** G4 PRECONDITION GATE at the head of this wave: the Wave-4 precondition test is imported and run first; unless `g4-verdict.json` reads verdict PASS (substrate or Anchor-owned fallback meeting all five obligations) this wave and every wave after it FAIL to build — the mechanical block on Waves 10-18; Commission proposal path bound to a named step ULID (free-floating steps refused, per the A1 audit), rendering skill + seat + depth + estimated spend BEFORE confirmation; SKILL SELECTION IS TABLE-BOUND: a proposal may only name a skill whose row in `artifacts/commissionable-skills.json` has `commissionable: true`; any other skill is refused with the named `skill-not-commissionable` state carrying its excluded_reason; Confirmation verb recording who and minting job_id / commissioned_as, appending commission_bind through the spine; COMMISSION-CONFIRM IDEMPOTENCE: a double-submitted confirmation mints exactly ONE job_id and launches exactly ONE run — a repeat-invocation test asserts the second submit returns the original job_id, appends no second commission_bind, and starts no second process (double spend is the failure this test exists to prevent); Dispatch by the locked step-type map: RESEARCH -> researchPrime, PLAN -> Crucible, BUILD -> Foreman, REVIEW -> Gandalf (dispatch entry only); Confirmed commission handed to the Anchor executor from the BUILD-E wave; observed pid recorded into the dossier; Seat family/driver collision guard: a proposal naming a colliding seat is refused with a named error (NS risk taxonomy); Failure-state table: step-not-found / free-floating-refused / seat-collision / unconfirmed-refused / skill-not-commissionable / g4-halt

**Depends on:** Session envelope — one confirmed budget covering compiles and orchestrator reflections

**done-when:** With g4-verdict.json at PASS, a commission is proposed for a named stage showing skill, seat and depth, nothing runs until John confirms, the confirmation records who and drives a real run whose pid lands in the dossier, and a double-submitted confirmation produces exactly one job_id and one launch.

- **Given** A confirmed roadmap with a named BUILD step, **when** the steward proposes a commission for it, **then** the proposal renders skill=Foreman, the seat and the depth with an estimated spend, and no run has started
- **Given** A rendered commission proposal, **when** John confirms it, **then** who is recorded, job_id / commissioned_as are minted, commission_bind is appended through the single writer, and the executor launches a real run whose observed pid is stored in the dossier
- **Given** A commission proposal that names no step, or names a seat already driven by a live run, **when** it is submitted, **then** it is refused with the named free-floating or seat-collision state and nothing is spent
- **Given** A confirmation that has already minted a job_id and launched a run, **when** the identical confirmation is submitted again, **then** the original job_id is returned, no second commission_bind is appended, no second process starts, and nothing further is spent
- **Given** A g4-verdict.json that does not read PASS, **when** this wave's suite runs, **then** the precondition test fails the build with the G4 HALT named and no commission path is exercised at all

## Wave 11 — Progressive elaboration — targeted questions or an offered researchPrime commission at stage START

**Intent:** Make detail arrive when a stage starts rather than at scaffold time: starting a stage triggers the steward's targeted questions or an OFFERED researchPrime commission, never a demand at authoring time.

**Deliverables:** Stage-start hook: entering a scaffolded step emits a typed elaboration event carrying targeted questions derived from the step's Oranges annotations; Offered-commission branch: where the gap is research-shaped the steward OFFERS a researchPrime commission through the standard propose -> confirm path (never auto-runs); Assertion that scaffold time demands NO stage detail: a test walks the authoring flow and fails if any stage-detail question is raised before the stage starts; Answers recorded as typed elaboration events joined to the step, feeding the next commission proposal; Failure-state table: no-questions-derivable (named, not empty) / elaboration-declined / offered-commission-refused

**Depends on:** Commission proposal in Anchor — skill, seat and depth shown before spend

**done-when:** Starting a stage produces targeted questions or an offered researchPrime commission, and no stage detail is ever demanded at scaffold time.

- **Given** A batch-confirmed coarse scaffolding with Oranges annotations, **when** the authoring session completes, **then** no stage-level detail question was asked during authoring
- **Given** A scaffolded RESEARCH-shaped stage, **when** John starts that stage, **then** the steward either asks its targeted questions or offers a researchPrime commission via propose -> confirm, and nothing runs until confirmed

## Wave 12 — Session-state truth — roadmap status across park, restart and kill

**Intent:** Make roadmap status reflect the ACTUAL session and run state rather than last-written intent, so park, restart and kill all produce honest status instead of drift.

**Deliverables:** Status derivation that reads live session and run state (lease/pid/lane) and reconciles it against the ledger, with drift resolved toward observed reality; Park path: an explicitly parked session reports parked with its envelope state preserved; Kill/restart path: a killed run is reported dead by name; a session whose context is gone reports its true stage; Lease TTL handling with edge-triggered state_since + hysteresis so status cannot FLAP near expiry (NS risk taxonomy); Tests across all three transitions (park, restart, kill) asserting status equals observed reality; Failure-state table: status-unknown (named) never rendered as idle or empty

**Depends on:** Progressive elaboration — targeted questions or an offered researchPrime commission at stage START

**done-when:** After park, after restart and after kill, roadmap status matches the actual session and run state, and an unreadable state reports unknown rather than idle.

- **Given** A campaign with one live commissioned run, **when** the run's process is killed and the roadmap is read, **then** the run is reported dead by name and the stage status reflects that, not still-working
- **Given** A session parked with a live envelope, **when** the project is reopened, **then** status reports parked with the envelope state preserved and no spend occurred while parked
- **Given** A lease approaching TTL expiry, **when** status is sampled repeatedly across the boundary, **then** state_since is edge-triggered with hysteresis and the reported state does not flap

## Wave 13 — Handback validation, reflection receipt and next-stage proposal (with unattended queue), plus the MULTI-SKILL executor proof

**Intent:** Close the orchestration loop: a validated handback produces a typed REFLECTION RECEIPT with Oranges prompts and a next-stage PROPOSAL through propose -> confirm — and an unattended handback queues instead of spending.

**Deliverables:** Handback ingestion through receipt-validate.mjs: the 6 campaign-memory fields validated; a corrupted handback is REFUSED with a named state and never reflected on; REFLECTION RECEIPT as a typed ledger artifact (never chat), EMITTED ON EVERY VALIDATED HANDBACK regardless of envelope state — it is a deterministic, zero-model, zero-spend render over the dossier (what the stage produced, its Oranges prompts for the next step), so criterion 4's receipt obligation is never deferred; MODEL-SPEND SPLIT (the queued-vs-emitted resolution): only the NL reflection COMPILE and the next-stage PROPOSAL debit the envelope; with a live envelope both fire immediately through propose -> confirm; with NO live envelope both are QUEUED as typed events and fire at next session open, with zero unattended spend proven by a test that asserts the receipt EXISTS while the compile does NOT; MULTI-SKILL EXECUTOR PROOF (intermediate, before the High Seat waves): two DIFFERENT skills selected test-bound from `commissionable-skills.json` are each driven propose -> confirm -> execute -> validated handback -> emitted receipt in one campaign, so criterion 6 is proven here rather than first attempted at the kill gate; fewer than two commissionable rows HALTs this wave; HANDBACK IDEMPOTENCE: the same handback delivered twice (retry, duplicate lane event) produces exactly ONE receipt and ONE queued-or-emitted proposal — a repeat-invocation test on the client_event_id primitive; Missing handback is NAMED (never silently absorbed) and surfaces as its own state; Failure-state table: handback-invalid / handback-missing / reflection-queued / proposal-declined / duplicate-handback-ignored

**Depends on:** Session-state truth — roadmap status across park, restart and kill

**done-when:** A validated handback ALWAYS emits its typed reflection receipt, the compile plus next-stage proposal fire immediately under a live envelope and queue with zero spend without one, two different commissionable skills are each proven end to end in one campaign, and a duplicate handback produces no second receipt.

- **Given** A commissioned stage returning a valid trio handback while a session envelope is live, **when** the handback is ingested, **then** a typed REFLECTION RECEIPT with Oranges prompts is emitted and rendered, and a next-stage proposal awaits John's confirmation
- **Given** A validated handback arriving overnight with no live session envelope, **when** it is ingested, **then** the deterministic reflection RECEIPT is emitted immediately with zero spend, the NL compile and the next-stage proposal are QUEUED as typed events, and both fire at the next session open inside a fresh envelope
- **Given** A corrupted handback missing campaign-memory fields, **when** it is ingested, **then** receipt-validate refuses it with a named state and no reflection or proposal is produced
- **Given** A validated handback that has already produced a receipt, **when** the identical handback is delivered again, **then** exactly one receipt and one proposal exist and the duplicate is recorded as duplicate-handback-ignored
- **Given** `commissionable-skills.json` read at this wave, **when** the multi-skill proof selects its skills, **then** it takes two rows with commissionable:true and drives each to a validated handback — and if fewer than two such rows exist the wave HALTs rather than proving criterion 6 with one skill or an unproven one

## Wave 14 — Rehydration — the cold-start wake-up brief with nothing re-asked

**Intent:** Deliver continuity: from a full restart with every context window gone, opening the project produces a first message stating the true campaign state derived ENTIRELY from the ledger, proposing the next step with its why and asking nothing already recorded.

**Deliverables:** Rehydration path joining assembleBriefPacket (Q1-Q12, zero model calls) with the commission dossier, closing the gaps the A2 coverage table identified; First-message composer as a ZERO-MODEL DETERMINISTIC RENDER: a pure template over the brief packet + dossier producing current stage, live/dead/waiting runs, everything waiting on John, and the next step with its why — no model call, no envelope debit, no invented fact; GOLDEN DETERMINISM TEST: the composer run twice over the same ledger state produces BYTE-IDENTICAL output, and a checked-in golden file pins it; a model call reintroduced anywhere on this path fails the test (the criterion-11 claim is a determinism claim, not a prompt-quality claim); Any optional NL polish is a SEPARATE, envelope-debited, clearly-labelled layer that the criterion-11 assertions never depend on and that is absent by default at cold start; NO-RE-ASK guard: a test that fails if the wake-up message asks any question whose answer exists in the ledger; Dead run and never-arrived handback both NAMED in the wake-up message, never silently absorbed; Kill-everything-then-resume integration test: every process killed, all context gone, project reopened; Honest-unknown rendering for any fact the ledger cannot answer

**Depends on:** Handback validation, reflection receipt and next-stage proposal (with unattended queue)

**done-when:** After killing everything and reopening the project, the steward's first message — a zero-model deterministic render, byte-identical on repeat and pinned to a golden file — states stage, run liveness and everything waiting on John from the ledger alone, names the dead run and the missing handback, and asks no already-answered question.

- **Given** A campaign mid-flight with one run that died and one handback that never arrived, **when** every process is killed, all context windows are gone, and the project is reopened, **then** the first message states the current stage, names the dead run and the missing handback explicitly, and proposes the next step with its why
- **Given** A ledger that already records the campaign objective, the confirmed scaffolding and the last confirmation's who, **when** the wake-up brief is composed, **then** no question is asked about any of those facts, proven by the no-re-ask guard test
- **Given** A fact the ledger genuinely cannot answer, **when** the brief is composed, **then** it renders as honest-unknown rather than being guessed or omitted
- **Given** The same ledger state, **when** the first-message composer runs twice, **then** the two outputs are byte-identical and match the golden file, zero model calls are observed and zero envelope spend is recorded — cold start costs nothing and cannot vary

## Wave 15 — Attention contract — pure derivation, the PUBLISH seam, emitters, and deliverable_ready provenance

**Intent:** Publish the altitude contract along the named seam: DERIVATION is one pure read-only engine function; DELIVERY is the project's own single writer publishing into the already-built index — which is how criterion 12 (read-only derivation) and criterion 13 (answered from the existing index, no root walk) are simultaneously true. Edge-triggered stability, bundle-hash-gated deliverable_ready.

**Deliverables:** DERIVATION — `deriveAttention(ledgerView)` : ONE engine function returning working | needs_you | deliverable_ready | blocked | idle with state_since, reason and provenance; PURE (zero writes, zero model calls, zero I/O beyond the passed view), proven by a write-trap test that fails on any store access; this purity claim is scoped to derivation ONLY and makes no claim about delivery; PUBLISH — `publishAttention()` : the single named publisher, and the ONLY code permitted to persist a projection; it writes through the Wave-6 single-writer spine (so it is a caller, not a second writer, and the Wave-6 invariant check covers it), persisting the project's typed `attention` cell and the `attention_projection_published { state, state_since, derived_from_event_seq, bundle_hash? }` event in ONE journaled transaction; EDGE-ONLY PUBLISH + IDEMPOTENCE: republishing an unchanged projection appends NOTHING and rewrites nothing — a repeat-invocation test asserts the ledger is byte-identical after a no-change republish, which is also what keeps an idle campaign at zero ambient signals; INDEX DELIVERY: publishAttention drives DERIVED ingest through the existing `engine/portfolio/anchor-contract.mjs` seam so the projection lands in the already-built index — the project PUSHES, the High Seat never walks and the index is never rebuilt (NS non-goal 1); if the Wave-3 A5 probe marked this seam NEEDS-WIRE, that wiring is this wave's fix item; READ API: the per-project row returned by `engine/portfolio/query.mjs` (project, stage, runs{live,waiting,blocked}, last_movement, attention) is frozen here as the contract Wave 16 consumes; Attention emitters at the state transitions: commission awaiting confirmation, and a QUEUED reflection compile or proposal -> needs_you; validated handback with artifact -> deliverable_ready; dead/blocked run -> blocked; deliverable_ready PROVENANCE gate: the state is only emitted when the artifact bundle hash matches the validated handback, closing the provenance hole in the risk taxonomy; Anti-FLAP: edge-triggered state_since + hysteresis around lease TTL, with a test sampling across the boundary; Projection returns unknown (a named state) when the project store cannot be read — never idle; Failure-state table for the projection covering unreadable / stale / provenance-unproven / publish-refused

**Depends on:** Rehydration — the cold-start wake-up brief with nothing re-asked

**done-when:** Each project publishes a typed attention projection whose DERIVATION is one proven-pure read-only function and whose DELIVERY is the single spine writer landing it in the existing index for no-walk reads, an unchanged republish writes nothing, deliverable_ready is bundle-hash gated, and the state does not flap across lease TTL.

- **Given** A campaign with a commission proposal awaiting John, **when** the projection function runs, **then** it returns needs_you, writes nothing to any store (asserted), and stamps state_since at the transition edge
- **Given** A handback whose artifact bundle hash does not match the validated receipt, **when** the projection is derived, **then** deliverable_ready is NOT emitted and the provenance-unproven state is recorded instead
- **Given** A project store that cannot be read, **when** the projection is derived, **then** it returns the named unknown state rather than idle
- **Given** A projection already published, **when** publishAttention runs again with no state or state_since change, **then** no event is appended, the attention cell is unchanged byte-for-byte, and no ambient signal is produced
- **Given** A newly published projection, **when** `engine/portfolio/query.mjs` is queried for that project, **then** the attention state is returned from the index with no project-root walk observed, proving derivation-pure and delivery-published are both satisfied on one path

## Wave 16 — High Seat fold — read-only raise queue, badge within one poll, portfolio at a glance

**Intent:** Fold N project projections into the High Seat with write_authority none, answering portfolio-at-a-glance from the EXISTING no-walk index so John sees every active project's state without digging, with the badge as the only ambient signal.

**Deliverables:** High Seat fold consuming N typed projections into the raise queue and the flag badge, with write_authority:'none' enforced by a test that fails on any write to a project store; Portfolio-at-a-glance view answered from engine/portfolio/query.mjs (the existing no-walk index) through the read API frozen in Wave 15: current stage, live/waiting/blocked runs, last movement, attention, per active project; FIELD-BY-FIELD COVERAGE BINDING: a test asserts every criterion-13 field named in the Wave-3 A5 matrix (stage / runs.live / runs.waiting / runs.blocked / last_movement) is either ANSWERED from the index or rendered as a named per-field `unknown` — a field may never be quietly omitted from the row; DEGRADED PATH (gate Decision 2): if the A5 fix-item cap (6 items / 2 waves) was exceeded, this wave ships DEGRADED with the uncovered fields listed BY NAME in the gate report and rendered as unknown, and the shortfall is raised to John as a scope decision — never absorbed, never answered by re-planning or rebuilding the index; Unreadable project renders an explicit unknown ROW — a test asserts the list length never silently shrinks; NAMED BOUND: `PORTFOLIO_MAX_ROWS = 500` active projects with the named `portfolio-bound-exceeded` refusal path (an over-bound portfolio is reported by name, never silently truncated into a shorter list); Badge latency test: needs_you and deliverable_ready reach the ⚑ badge within ONE poll; Ambient-signal containment test: a campaign needing nothing produces ZERO ambient signals beyond the badge count; FIVE-STATE SURFACE TABLE for the High Seat (index read, query, fold, badge), each with a status code AND user-visible text, unknown and empty as SEPARATE rows: dependency-missing / dependency-slow-or-killed / dependency-returns-garbage / backing-store-unreadable / empty-but-valid; All A5 fix items within the cap closed before this wave consumes the index (no re-plan, no rebuild)

**Depends on:** Attention contract — typed projection, emitters, and deliverable_ready provenance

**done-when:** Opening the High Seat shows every active project's stage, run state and last movement from the existing index with no root walk, every criterion-13 field is answered or named unknown, unreadable projects appear as unknown rows, the five-state surface table is exercised, and needs_you / deliverable_ready reach the badge within one poll with no other ambient signal — with any DEGRADED field named in the gate report.

- **Given** A portfolio of several active projects, one of whose stores is unreadable, **when** the High Seat is opened, **then** every project appears with its stage, runs and last movement, the unreadable one shows an unknown row, and the row count is never silently shorter
- **Given** A project transitioning to needs_you, **when** one poll interval elapses, **then** the ⚑ badge count reflects it, and no other ambient signal is produced
- **Given** The High Seat fold running over N projections, **when** project stores are inspected afterwards, **then** no write occurred to any project store (write_authority:'none' proven, not asserted in prose), and no project root was walked
- **Given** Each of the five dependency/store failure modes injected against the index read and the query, **when** the High Seat renders, **then** each produces its own status code and user-visible text, with empty-but-valid rendered distinctly from backing-store-unreadable and from unknown
- **Given** An A5 matrix field that remained ABSENT beyond the fix-item cap, **when** this wave ships, **then** that field renders as a named unknown, the gate report lists it under DEGRADED, and no index re-plan or rebuild was performed to close it

## Wave 17 — Chamber UI — steps, proposals, confirmations, artifacts and spoken corrections

**Intent:** Give the campaign a reviewable surface: scaffolded steps, proposals with their confirm affordance, and stage artifacts rendered readably, with a spoken correction producing a NEW VERSION through propose -> confirm.

**Deliverables:** Chamber UI steps view rendering the confirmed roadmap with per-step status derived from the session-state truth wave; Proposal + confirm surface for scaffolding batch-confirm, commission confirmation (skill/seat/depth/spend) and next-stage proposals, each showing what will be spent before it is spent, and each wired to the Wave 8/9/10 idempotent confirm verbs so a double-click cannot double-commit or double-spend; Artifact view rendering stage artifacts via packet-view.mjs classifyArtifact / buildArtifactCard; if the G2 spike FAILED, the plan-shaped renderer built here; Artifact reads go through the Wave-7 contained resolver, with the chamber's own escape-attempt test (`..`, absolute path, symlink/junction) asserting path-escape-refused is surfaced rather than rendered; Correction path: a typed spoken correction on an artifact or scaffolding emits a NEW VERSION proposal through propose -> confirm; the prior version remains addressable; Reflection receipts rendered into conversation as typed artifacts, never as persisted chat; FIVE-STATE SURFACE TABLE for every chamber surface (steps view, proposal/confirm surface, artifact view, receipt render), each with a status code AND user-visible text, unknown and empty as SEPARATE rows: dependency-missing / dependency-slow-or-killed / dependency-returns-garbage / backing-store-unreadable / empty-but-valid — plus the transient loading state, which is never used to stand in for any of the five

**Depends on:** High Seat fold — read-only raise queue, badge within one poll, portfolio at a glance

**done-when:** Stage artifacts, steps, proposals and reflection receipts render reviewably in the chamber, every chamber surface answers all five failure states with a status code and user-visible text (unknown separate from empty), a contained-path escape attempt is surfaced as refused, and a spoken correction produces a new version through propose -> confirm with the prior version still addressable.

- **Given** A converged Crucible doc-trio returned as a stage artifact, **when** John opens the artifact view, **then** it renders reviewably as a classified artifact card rather than raw text or an empty panel
- **Given** A rendered artifact John disagrees with, **when** he types a correction, **then** a NEW VERSION is proposed and only written after his confirmation, with the previous version still addressable
- **Given** A project whose artifact cannot be read, **when** the chamber renders it, **then** the unknown state is shown distinctly from empty
- **Given** Each of the five failure states injected behind each chamber surface, **when** the surface renders, **then** it shows that state's own status code and user-visible text — empty-but-valid never borrows the unreadable text, and loading never masks a garbage or missing dependency

## Wave 18 — Wave-0 kill gate — end-to-end campaign proof, two skills, auth ON

**Intent:** Prove the whole North Star in one campaign on a fresh project under auth ON: describe -> propose -> batch confirm -> commission -> execute -> validated handback -> reflection + next-stage proposal, exercising at least two commissioned skills, then kill everything and resume without re-asking.

**Deliverables:** End-to-end campaign test on a FRESH project with auth ON, asserted on OUTCOMES (ledger state, rendered surfaces, projections) rather than plumbing; TEST-BOUND TWO-SKILL SELECTION: the campaign reads `artifacts/commissionable-skills.json` and selects two rows with `commissionable: true` (executor-proven ∧ EXTERNALLY-OBSERVABLE HALTs) — the skills are never hand-named in the test, and if fewer than two qualify the gate HALTs with the shortfall named rather than substituting a skill, stubbing an executor or weakening criterion 6; each skill runs through propose -> confirm with who recorded; G4 precondition re-asserted at the gate: a non-PASS verdict fails here too, so no green kill gate can ever coexist with an unproven substrate; Kill-everything-then-resume leg inside the same campaign: all processes killed, contexts gone, project reopened, true state named including one dead run and one missing handback, via the zero-model deterministic composer; Whole-campaign invariant sweep: zero chat turns persisted, zero spend outside a live envelope, exactly one roadmap_events writer (publishAttention included), no High Seat write, no project-root walk, no trio-tree modification, no pre-spine durable write; Criteria traceability report mapping each of NS criteria 1-13 to the passing test(s) that prove it, and each property-gate checkbox to its owning wave's test; Gate report listing anything DEGRADED (one-run-at-a-time executor, any A5 field beyond the fix-item cap, any Anchor-owned G4 fallback) BY NAME rather than omitted

**Depends on:** Chamber UI — steps, proposals, confirmations, artifacts and spoken corrections

**done-when:** One fresh-project campaign under auth ON runs description -> proposed scaffolding -> batch confirm -> commissioned stage -> validated handback -> reflection + next-stage proposal across two skills selected test-bound from the commissionable intersection table, survives kill-and-resume with the true state named by the deterministic composer, and every NS criterion 1-13 and every property-gate checkbox maps to a passing test — with every DEGRADED item named in the gate report.

- **Given** A fresh project with auth ON, **when** John describes an effort, batch-confirms the proposed scaffolding, confirms a commission, and the stage hands back validated, **then** a reflection receipt with Oranges prompts and a next-stage proposal are produced, and the whole path is asserted on ledger and rendered outcomes rather than plumbing
- **Given** That campaign mid-flight with one run dead and one handback never arrived, **when** everything is killed and the project is reopened, **then** the steward's first message names the true state including both anomalies and asks nothing already recorded
- **Given** The completed campaign, **when** the invariant sweep runs, **then** zero chat turns are persisted, no spend occurred outside a live envelope, roadmap_events shows exactly one writer, the High Seat wrote nothing and walked no project root, and no file under the Crucible / Foreman / researchPrime trees was modified
- **Given** `commissionable-skills.json` at gate time, **when** the campaign selects its two skills, **then** both come from rows with commissionable:true and neither is hand-named in the test — and if fewer than two qualify the gate HALTs with the shortfall named instead of reporting a green kill gate

## Property gates (hardening law — crucible journal 0080)

### durability — asserted by this plan
_a durability claim is a STORAGE claim; validating a rule is not providing it_

- [ ] atomic write (temp + fsync + rename)
- [ ] lock or documented serialization
- [ ] a concurrency test

### honesty — asserted by this plan
_the recurring defect is a confident wrong answer, not a crash_

- [ ] a failure-state table
- [ ] unknown and empty as SEPARATE rows

### idempotence — asserted by this plan
_idempotence is only real if something re-invokes and asserts no change_

- [ ] a repeat-invocation test

### boundedness — asserted by this plan
_an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard_

- [ ] the numeric bound named in the plan
- [ ] a refusal path when the bound is exceeded

### containment — asserted by this plan
_containment is asserted far more often than it is exercised_

- [ ] an escape-attempt test (.., absolute path, symlink)

A property named in the plan and absent from this list is a BLOCKER:
the plan is claiming a guarantee nothing enforces.

## Hardening-gate obligations (mechanical — journal 0080)

This section is the **emitted** property-gate checklist. A claim in the plan without a matching obligation below is a BLOCKER.

### Property `durability`
_a durability claim is a STORAGE claim; validating a rule is not providing it_

- **Gate:** atomic write (temp + fsync + rename)
- **Gate:** lock or documented serialization
- **Gate:** a concurrency test

### Property `honesty`
_the recurring defect is a confident wrong answer, not a crash_

- **Gate:** a failure-state table
- **Gate:** unknown and empty as SEPARATE rows

### Property `idempotence`
_idempotence is only real if something re-invokes and asserts no change_

- **Gate:** a repeat-invocation test

### Property `boundedness`
_an unnamed bound cannot be tested and an unbounded read is a shared-thread hazard_

- **Gate:** the numeric bound named in the plan
- **Gate:** a refusal path when the bound is exceeded

### Property `containment`
_containment is asserted far more often than it is exercised_

- **Gate:** an escape-attempt test (.., absolute path, symlink)

### Storage mechanism vocabulary (required when durability is claimed)

- **atomic write** via **temp** + **fsync** + **rename** for snapshot (and durable JSON) paths
- cross-process **lock** or documented **serialization** around multi-writer index paths
- a **concurrency test** (two real processes; assert no event/receipt dropped)
- where "exactly once" / identity is claimed: a **repeat-invocation test**
- where containment is claimed: an **escape-attempt** test (`..`, absolute path, symlink/junction)
- where bounds are claimed: the **numeric bound** named (e.g. 10000 rows / 50000 events) and a **refusal** path when exceeded

### Failure-state table vocabulary (required when addsSurface)

Every surface-bearing wave answers these **five** states with named status code AND user-visible text.
**unknown** and **empty** are SEPARATE rows (never collapsed).

- **dependency-missing** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **dependency-slow-or-killed** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **dependency-returns-garbage** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **backing-store-unreadable** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)
- **empty-but-valid** — status code + user-visible text per surface (index read/write, rebuild, reconcile, verify, query, CLI verbs)

See also wave-local failure tables (hardening-gate 0080 format) and generated red stubs.

