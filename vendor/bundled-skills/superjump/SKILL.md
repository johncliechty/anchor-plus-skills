---
name: superjump
description: >
  Superjump is the structured ideation engine for genuinely new ideas: a bounded
  read of the problem, analogical leaps with an inspectable transfer trace, and
  an independent cross-family judge against a Fit Contract drawn from the brief.
  Use when Jumper's lean mode is not enough, when the user wants Super Jump /
  Superjump / /superjump, or when ideas must be judged in the brief's own terms
  and watched for real progress rather than cut off by a clock.
icon: assets/superjump-icon.jpg
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

**THE SPEAKING LAW (John, 2026-08-16 — ELEGANCE.md Part III):** every ask,
HALT, or summary this skill puts to the user describes the DECISION, never
the machinery (a gate ask took FOUR attempts because it kept narrating waves
and gates); a few plain sentences carrying the two-three details that matter
+ where the full detail lives; genuinely complicated content goes in NUMBERED
BATCHES, one at a time, each ending "OK so far?"; no seat/stamp/gate
vocabulary in the sentence the user must read; every ask ends with a question
answerable in one word AND carries a recommendation (what you would choose +
one line of why + alternatives when the choice has them + "or tell me
something else" — options are a convenience, never a cage).
<!-- /ELEGANCE-V2.1 -->
<!-- /ELEGANCE-LAW -->

> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol.

# Superjump — structured ideation against a Fit Contract

Superjump keeps Jumper's original structure and makes it deliver: a bounded
Gandalf-lite read, productive SCAMPER only, foreign-domain transfer with an
inspectable trace, TRIZ resolution, a three-gate independent judge, and a
proportionate unperformed fair test. It never stops a run on a clock.

> **Tier definition + invocation discipline + run capture:** canonical in
> Foundry `AGENTS.md`. Superjump-Heavy is the frontier of the coding family on
> the read and leap seats; the independent review is the review family. Do not
> re-define or deliberate any of it.

## How to run — the engine, never an improvised pipeline

```
node bin/superjump-run.mjs --input brief.txt --output out.json
node bin/superjump-run.mjs --problem "<brief>" --candidates 3
node bin/superjump-run.mjs --reweight "human benefit 3; simplicity 1" --from out.json
node bin/superjump-run.cmd --input brief.txt
```

- `--candidates` 1–5, default 3.
- `--effort auto|highest` (auto uses the calibration table's recorded choice).
- `--control <file>`: write `kill` or `kill <dispatch>` to abort through AbortSignal
  and emit the partial. The engine never kills on elapsed time.
- `--reweight` reorders a finished result with no model call.
- There is **no `--deadline`**. The only automatic stop is `SUPERJUMP_CALL_TIMEOUT_MS`
  (default 60 minutes), recorded in the run.
- Seats from Anchor prefs. Pre-flight ping. In-flight run record. Progressive
  writes after every landed stage. Partials on every thrown error.
- Do not improvise the hops in prose. The engine or nothing.

## Hops

1. **Read** (coding family) — ask, assumptions, contradictions, wrong-if, productive
   SCAMPER, Fit Contract. A `DELIVERABLE`/`MUST`/`FIXED`/`FORBID`/`JUDGE` block in
   the brief overrides derivation.
2. **Leap × N** in parallel — ordered transfer trace, then the instantiated
   deliverable. No numeric self-score. Sphere hints only.
3. **Judge** per candidate as it lands (review family) — contract re-check, three
   gates, eligibility table with passages, anchored ratings. Explicit must/fixed/forbid
   violations kill; inferred objections flag as `uncertain`.
4. **Dedupe** — one call over one-line mechanisms. Duplicates are one idea with two
   routes; they never lower the original's rating.

## When to use

Triggers: "super jump", "superjump", "/superjump", "original jumper structure",
"ideas judged against my brief", "fit contract". Prefer Jumper `--mode lean` when
the user wants vetted options in a few minutes.

## Do not use

Diagnosis (Gandalf). Build plans (Crucible). Builds (Foreman). "Implement the
winner" is refused with a Crucible/Foreman pointer.

## Output order

Fit Contract with sources; survivors by anchored rating (deliverable, mechanism,
domain, trace, eligibility, ratings with passages, uncertain flags, unperformed
test); kills with term and passage; unjudged; duplication groups; progress log
and seats last.

> **⏱ STATUS UPDATES TO CHAT:** long runs use the LOCKED Status-table in the
> canonical `AGENTS.md`. Arm the cadence at launch.

## Usage journal

After every real run, append `journal/NNNN-<slug>.md` and `journal/runs/<utc>-<id>.json`
per Foundry `AGENTS.md` "Run capture".
