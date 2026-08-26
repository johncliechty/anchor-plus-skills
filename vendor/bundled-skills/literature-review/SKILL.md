---
name: literature-review
description: An interactive literature-review skill — deterministic snowball search + PRISMA discipline, ONE-call-per-paper claim extraction with deterministic quote grounding, weighted consensus synthesis, and a final adversarial pass through researchPrime's real governed round. Outputs a source-grounded Assumptions Ledger + comparison matrix.
---

## North Star (LOCKED — John, 2026-08-25)

Given a research question, literature-review delivers a PRISMA-disciplined, quote-grounded synthesis with weighted consensus and an honest assumptions ledger — every claim traceable to a source, at a depth right-sized to the stakes.


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

# literature-review

You rigorously ingest, corroborate, and synthesize the literature around a seed paper, weighting
evidence by academic quality and adhering to the OBSERVED > CORROBORATED > CLAIMED ladder. The
deliverable is a source-grounded **Assumptions Ledger** + **parameterized comparison matrix** that
downstream phases can build on.

> **Tier definition (Heavy vs regular · stakes-gated cross-model · seat mapping) + invocation
> discipline:** canonical in `AGENTS.md` (Foundry root on the author host; your install root in a distributed bundle) → "Skill tiers" / "Invocation
> discipline" / "Run capture". Heavy = `TRIO_TIER=heavy` on the composed seats. Do not re-define
> or deliberate any of it.

## How to run (operator manual — REWIRED REAL 2026-07-11; the CLI never fabricates)

```
LITREVIEW_LIVE=1 node bin/cli.mjs --seed <pdf-or-s2-url> \
  [--depth 1] [--max-papers 6] [--columns method,evidence,result] \
  [--stakes low|medium|high] [--out litreview-out] [--mock-user "q: ...|approve"]
```

**Env:** `S2_API_KEY` (optional but strongly recommended) raises the Semantic Scholar rate
limit — without it, sustained 429s killed 8 of 9 real invocations (journal 0004). Seeds now
PRE-FLIGHT before any paid seat binds, with a recorded OpenAlex fallback by catalog
identifier; both-provider failure halts by name with zero capacity spent (fix 2026-08-25).

**Reverse-arrow rule (journal 0004, verified):** for any directional question "does X cause
Y", ALSO seed/search the reverse direction "does Y cause X" — it recovered the one on-point
paper in the skill's only real high-stakes use.

The pipeline, in order — each stage honest about what ran:
1. **Ingest** (deterministic): seed PDF → text chunks + Semantic Scholar id.
2. **Snowball + PRISMA** (deterministic): depth-bounded citation walk with backoff; the venue
   whitelist RANKS candidates (Tier-1 first) and **excludes nothing by default** (arXiv survives;
   `excludeByVenue`/`--min-tier` are opt-in); every exclusion logged PRISMA-style; Mermaid graph out.
3. **Mixed-initiative gate**: review the ranked candidates, interrogate the ingested text via the
   copilot, `approve`/`reject`. TTY-aware — non-interactive runs auto-approve WITH a stamp
   (`--mock-user` drives it in tests).
4. **LEAN extraction** (live seats required): ONE model call per paper; every extracted claim must
   carry a VERBATIM supporting quote, and the quote is string-matched against the paper's text —
   a fabricated quote is rejected deterministically, never kept. Claims enter as CLAIMED with a
   `claim_id` (the trio's ≥2-agree identity key).
5. **Weighted consensus synthesis** (deterministic math): citation-weight × rung ladder, conflict
   grouping, CORROBORATED upgrades → `assumptions-ledger.{json,md}` + `parameterized-matrix.json`.
6. **Adversarial governed pass(es)** over the synthesized ledger through researchPrime's REAL
   surface (`composeLiteratureReviewAdversarialPass` → `runGovernedRound`: trio tally, claim_id
   agreement, inclusion test, Judge) — reviewers route cross-family (Gemini via agy). Invocation
   count `N = knobs.adversarialRounds` from `@foundry/triage` (never `runEngine`). Stamped
   honestly as N governed rounds, never passed off as a converged multi-round researchPrime product
   run (commission researchPrime itself when you need that).

### Process depth (Track B7 — operator note)

Depth locks come **only** from `@foundry/triage` (`literatureReviewKnobs` / live
`BAND_MAPPINGS['literature-review']` via `FOUNDRY_TRIAGE_DEPTH` / `--triage-depth`).

- **LITE thins only** `snowballDepth`, `adversarialRounds`, and ceremony/seats labels.
- **PRISMA discipline, quote-grounding, and one-call-per-paper claim extraction remain
  full-strength at every band** — they live on the depth-invariant `LIT_REVIEW_SAFETY_FLOOR`
  consumed at extract entry, never as overridable depth knobs. LITE and `adversarialRounds=0`
  must not dilute those floors.

**Honesty posture:** without `--live`/`LITREVIEW_LIVE=1` the run STOPS after stage 3 with an
explicit "extraction/verification did NOT run" stamp — deterministic outputs only, nothing
invented. With live seats, the model split is the 5:1 (extraction/copilot → Claude;
reviewers/judge → Gemini; agy down ⇒ honest HALT). Every run auto-writes a `journal/runs/`
training record; status cadence per the block below.

> **⏱ STATUS UPDATES TO CHAT:** When running long phases in the background, you MUST arm a 10-minute cadence (`ScheduleWakeup` ~600s) and provide scheduled updates to the user in the LOCKED Status-table format — canonical definition in ONE place: the canonical `AGENTS.md` → "Long-run progress updates" (`[HH:MM]` header · Effort/Doing/Status/Tests/Blocker/Procs/**Journal** rows · ETA + To do footer). The **Journal** row (mandatory, `none` when empty) recaps everything journaled since the last tick — the SESSION composes it from this skill's `journal/`.

## Usage journal (lessons — append after every REAL run)

Append one `NNNN-<slug>.md` to `journal/` (7 canonical fields — id/skill/situation/context/
observation/outcome/provenance; ≤15 lines; append-only). The machine record is auto-captured;
the NNNN entry is for what the run TAUGHT you.
