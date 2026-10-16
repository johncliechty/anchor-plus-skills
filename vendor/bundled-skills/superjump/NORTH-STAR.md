# NORTH-STAR — superjump (Stage 0, 2026-09-14; consolidated after the ChatGPT read and John's decision on time; locks on John's word)

> This file is the skill's LOCKED purpose + its anti-drift contract once John approves it.
> It is deliberately close to Jumper's original North Star: Superjump exists to keep the
> original structure John liked and make it deliver — watched for real progress, never cut
> off by a clock — with a visible fit to the problem.

## Purpose (to be LOCKED)

Superjump is the portfolio's structured ideation engine for genuinely new ideas. It runs the
original Jumper structure end to end — a bounded Gandalf-lite read of the problem, a SCAMPER
scan that reports only its productive moves, foreign-domain analogical transfer with an
inspectable transfer trace, TRIZ contradiction resolution, a three-gate kill-filter with an
independent cross-family adversary, and a proportionate, unperformed fair test — and it
**never stops a run on a clock**. It states the expected duration from measured calibration,
watches each seat for observable progress, writes its results progressively so that anything
that has landed can be read at any moment, and only *recommends* a kill — to a human or the
steward — when observable progress has stopped well beyond the range in which runs have been
seen to finish; the only automatic stop is the driver's safety timeout, set generously and
recorded. Every idea is generated against, and judged against, a Fit Contract drawn from the
brief with each item's source quoted — the deliverable, the must-haves, the fixed facts, the
forbids, and the judging axes John may set himself. Eligibility, soft fit and portfolio
diversity are reported separately; explicit violations kill, inferred objections flag; ratings
are anchored and reweightable after the run. The filter suppresses hallucinated and shallow
output as a mitigation, not a guarantee, and the record stays honest about what was checked, on
what substrate, how long each seat took against its expectation, and what a kill would forfeit.

## Logical tier (the brain seam — NS4)
- logical tier: `top` for the read and the leap seats; the independent review is cross-FAMILY
  by preference (Anchor review family), independence over intelligence. No model is named in
  prose; seats resolve from Anchor prefs. The effort each seat runs at is recorded in every run
  and chosen against measured expectations, never silently lowered.

## Non-goals — machine-checkable negative tests (NS3 anti-drift)

| id | non-goal (must NOT happen) | negative canary (an input that MUST FAIL) |
|---|---|---|
| NG-1 | Present an idea that bypassed the independent review | `skipReview:true` is ignored; every returned candidate carries its three gate verdicts, its fit table and the review substrate |
| NG-2 | Kill on a clock | a seat that is slow but still showing progress (streaming events, or inside the calibrated range) must never be aborted by the engine; a `--deadline` option does not exist; the only automatic stop is the recorded driver safety timeout |
| NG-3 | Become a build engine | "implement the winner" is refused with a Crucible/Foreman pointer |
| NG-4 | Fabricate diversity | two candidates sharing a principal mechanism are reported as one idea with two routes, never as two ideas; a duplicate never lowers the original's rating |
| NG-5 | Rank by anything but the brief | survivors are ordered by the weighted anchored ratings on the contract's axes; sorting by mapping length, output length, sphere or self-score is a drift failure |
| NG-6 | Let a self-assessment stand as a verdict | a candidate with no independent review is `unjudged`, never a survivor; the reviewer never sees a numeric self-score |
| NG-7 | Kill on an inferred requirement | a Gate-3 objection not tied to an explicit contract item with a source quote is an `uncertain` flag, never a kill |
| NG-8 | Hide a stall | when observable progress has stopped beyond the window, the run must say so in its status line and result (`progress.recommend_kill` with the evidence and what has landed); silence is a defect |

## Invariants (always true of a correct revision)
- The brief reaches every prompt verbatim; the Fit Contract reaches every generation and review prompt with each item's source; the reviewer re-checks the extraction before scoring; deterministic phrase/number checks are labelled lints.
- Three hops in sequence: Read → Leap (parallel) → Judge (per candidate, as it lands); one bounded duplication pass when the portfolio is complete. No prompt-injected heartbeat; no engine-side abort on elapsed time; progress is observed from what the seat's process actually emits, and from calibrated expectations when it emits nothing.
- The result file is written after every landed stage, so a read at any moment shows what exists; a kill, by whoever decides it, forfeits only what has not landed.
- Outputs are bounded; a nonconforming reply is retried once and then recorded `unjudged`; paid work is never lost (partials at every hop, salvage when nothing survives).
- Seating from Anchor prefs; attested cross-family review; receipts per dispatch; `cross_model` derived; pre-flight ping; in-flight record; run capture with per-hop durations against their expectations.
- Superjump imports Jumper's seating ledger, receipt validators, seating resolver and halts; it never forks them.
- The report leads with the Fit Contract (sources shown) and the findings; process, seats and timings come last.

## Provenance
Commissioned by John 2026-09-14 after the Jumper review (skills/jumper/planning/review-2026-09-13) and the six-run comparison. Analysis: `ANALYSIS.md` (§10 carries the adopted ChatGPT revisions; §11 carries John's decision on time); adversarial read: `chatgpt-review/REVIEW-CHATGPT.md`.
