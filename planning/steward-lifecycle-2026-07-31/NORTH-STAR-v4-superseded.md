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
