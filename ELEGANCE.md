<!-- SHIP COPY. Canonical source: the Skill Foundry's ELEGANCE.md on the
     author host. Re-copy at release prep when the canonical changes;
     every vendored SKILL.md carries the binding block inline either way. -->

# The Elegance Law

**Canonical. Model-agnostic. Applies to every skill in this portfolio and to any agent
running one — Claude, Gemini, Grok, or a human following the same procedure.**

Locked by John, 2026-08-15, after a ten-day steward rebuild produced ~140 process
artifacts (~15,000 lines of plans, ratifications, audits, and gates) and roughly four
usable affordances, none of which he had confirmed on his own screen.

His words: *"There's a lack of elegance in all these skills. They do too much, add things
that aren't essential. There's no reflective element — is this really needed? We get rabbit
holes, wasting resources and not delivering what I want. And when you give me a summary or
a plan it's more than I have time or inclination to read — so sometimes I say yes, but I
didn't check it carefully."*

That last clause is the reason this file exists. **Long plans manufacture false consent.**
A skill's thoroughness must not be funded by approvals its user did not truly give.

---

## The five rules

**1. The approval block is ≤200 words.**
Anything put to the user for approval is ONE block: what changes in their world, the
recommendation, and the one thing that gets worse. The full artifact stays on disk and its
path is named; it is printed only if they ask. An approval obtained with a longer block is
void — treat that work as unapproved.

**2. A summary is ≤150 words.**
The goal in one line, what is done and not done, at most three findings ranked by
consequence, and the single next decision. Never rounds, waves, seats, stamps, gate counts,
or file inventories. Never restate what the user just said. Everything else goes to disk.

**3. Default to the lightest band, without asking.**
Every run opens at its lightest tier. Escalating to a heavy tier requires the run's first
status line to NAME its trigger: the action is irreversible or externally visible; the
inputs have not converged; this exact area has failed before; or the user typed the heavy
form. A heavy run with no named trigger is a defect. Right-sizing downward never costs the
user a question.

**4. Every unrequested element carries a needed-because line.**
Any wave, gate, artifact, document, or amendment the user did not ask for carries one line
in the plan: *"Needed because ___; dropping it costs ___."* No line, no element.

**5. Show a cut, and stop on the first dry round.**
One genuinely empty review round ends the loop — never a streak, which pays reviewers to
keep finding filler. And every plan presented for approval names at least one thing it
removed or declined to do, with the cost saved. If nothing was cut, say so out loud.

---

## The verification law (added 2026-08-15 — the fourth recurrence)

**Verify the claim you actually made, on the surface the user actually uses.**

This has now failed four times in three weeks, each time with the lesson written down
afterwards and each time recurring anyway:

- 2026-07-26 — 63/63 tests green, run against the wrong directory.
- 2026-08-12 — 53 model gates and 27 deck checks passed while four charts rendered clipped,
  a headline overflowed its subtitle, and a footnote lay across the footer. No text- or
  number-level assertion can see any of that.
- 2026-08-13 — "a lot of work was done but it isn't showing up." A data explanation was
  offered instead of a look. He was right; the chamber was deleting itself on every open.
- 2026-08-15 — "I restarted and nothing changed", four times. Each time the SERVER was
  checked and found correct, and the browser was blamed without test. The real cause: the
  redeploy signal was keyed on the last commit, so uncommitted work never moved it.

Three rules, and they are not satisfied by a passing test:

1. **Check the noun in the claim.** "It's live", "it's fixed", "it renders" are claims about
   what the user will see. Verifying that the server emits new bytes, that a build exited
   zero, or that assertions passed is a claim about something else. Render it and look.
2. **A symptom reported twice retires the first explanation.** The second report means the
   hypothesis was wrong or untested. Test it; never repeat it. Cheap explanations that make
   the user's report false ("it's your cache", "it's a data issue") require *more* evidence
   than expensive ones, not less — they are the ones you want to be true.
3. **Prefer a mechanism to an instruction.** If the same instruction is being given every
   session ("hard-refresh", "check the exit code"), the instruction is the defect. Build the
   thing that makes it unnecessary.

**And the meta-rule this file exists to enforce: a correction that lives only in a journal or
a memory has not been made.** Journals are read after the fact. Promote the correction to
where it is loaded before the work starts — here, and therefore into every skill.

## The two laws these rules serve

**A gate that cannot see what the user sees is not a gate.** Any claim about a user-facing
surface is proved against the real thing — real pixels, real service — or it is unproved.
Structure diffs, markup hashes, and slot inventories are lints. Label them as lints. The
steward chamber ran twelve waves logging an identical `1135/1135` while the surface it was
building deleted itself on every open.

**A guardrail is never the whole product of a turn.** If enforcement withholds output the
user already paid for, the withheld output is still shown. A refusal that replaces an
answer is a worse failure than the thing it was guarding against.

---

## What this costs

Adopting these rules loses the predictive value of full adversarial rounds on medium-sized
tasks — real defects that a heavy pre-build pass would have named in advance will instead
surface mid-build as red gates. That trade is accepted deliberately. The record's worst
failure happened *under* full ceremony and was caught only by the user's own eyes.


---
---

# Part II — What elegance IS, and the Rabbit-Catcher
## (added 2026-08-15 — researchPrime-vetted; commissioned by John)

> Provenance: commissioned by John 2026-08-15 ("go out and do a researchPrime
> on elegance and come back with a really nice elegance definition... a rabbit
> catcher alongside the orchestrator"). Built from three parallel evidence
> sweeps (38 ledger items, evidence-rung marked) and hardened through FOUR
> live cross-family adversarial rounds (3 independent Gemini reviewer seats
> per round; live Judge + Synthesizer; engine tally trajectory 3→1→1→0 new
> blockers; stopped on the first genuinely-dry round per rule 5 above).
> Full run record retained on the author host (the governed-round inputs,
p-run\.
>
> Part I above is the LAW (how much ceremony, what gets shown, what gets
> verified). Part II is the CRITERION (what elegance is, and the per-element
> test). Part I was locked by John and is unchanged; Part II extends it.

## The definition  [D1]

**Elegance is the largest result carried by the least machinery its user can
actually hold — every element forced by a need you can point at, nothing
present the objective does not pay for, and the whole legible to the person
who must live with it. It is earned by iteration and subtraction, never by
skipping work: as simple as the task allows, and no simpler than a single
datum of experience permits.**

"Can actually hold" is bounded by evidence, not aspiration: the Book-proof
editors cap a perfect proof at ten pages; working memory holds ~4 chunks;
Rams pairs "as little design as possible" with "thorough down to the last
detail." Small enough to grasp — complete enough to work.

Three independent fields converge on the same two-sided law:  [TBL]

| Field | Cut this | Never cut this |
|---|---|---|
| Software (Fowler/Ousterhout/Gabriel) | presumptive FEATURES (capability nobody asked for — cost-of-carry) | **malleability work** (refactors, tests, seams — YAGNI's own author exempts it); interface-protecting implementation depth |
| Cognition (Sweller/Nielsen) | extraneous load (imposed by presentation) | intrinsic load (the task's own complexity) — STAGE it, don't delete it |
| Math/physics (Ockham-as-written/Einstein-1933) | anything posited without necessity | anything whose removal surrenders a datum of experience |

Two structural signatures distinguish real elegance from its counterfeit:  [SIG]
- **Leverage** (Hardy's economy; deep modules): disproportion between machinery
  and consequence — "the weapons seem childishly simple compared with the
  far-reaching results, but there is no escape from the conclusions."
- **Provenance** (Gall; sprezzatura; motor learning): working complexity is
  GROWN from a working simple core; effortlessness is the trained END state.
  Novice-stage scaffolding is load-bearing while the internal model forms —
  give it a written retirement trigger; do not ban it.

---

## The Rabbit-Catcher — the per-element test battery

> **Where it runs (bounded — the battery must not become its own rabbit
> hole):** the FULL battery runs at exactly two moments — (1) plan approval,
> over the plan's enumerated elements, and (2) any NEW element introduced
> mid-run (an amendment, an unplanned dependency, an added gate). Round
> boundaries get ONE question only — RC-6 on the current work item ("still on
> the critical path?"). Each question is answered from evidence already on
> the table. When one requires NEW investigation, that investigation cannot
> cite precedent (it is new by definition) — its need IS the battery question
> that spawned it, which is on the record the moment the battery runs. It
> enters HOLD with a stated budget (time or calls) and is never itself
> batteried: one level, no recursion. A **rabbit hole** is work that is
> absorbing and effortful but off the critical path to the locked North Star
> (the 750-GeV class: 500 papers on a statistical fluctuation).

**RC-1 · Needed-because, with an INDEPENDENT citable need.** What forces this
element — named as a record that is **independent of the element's proposer**:
it predates this effort, or carries the user's authorship or ratification, or
is an incident/journal record of something that actually happened. A clause of
the locked North Star, a recorded failure, an explicit user request, a datum.
*(Ockham as written: posit nothing without necessity — and the same
independent-origins law the evidence ladder already applies to sources.)*
**You may not justify an element by a record created in order to justify
it** — by you, by a sub-agent you tasked, in this effort or planted in an
earlier one. The reviewing seat assesses the record's provenance chain —
authorship, timing, and above all BENEFICIARY: **a record whose only
beneficiary is the element it justifies is suspect regardless of its author
or age — and the test runs PER ELEMENT, never per bundle: packaging an
element beside a legitimately-needed sibling transfers nothing.** This is a reviewer's judgment call by design; the battery is a
checklist wielded by a frontier seat, not a cryptosystem, and its bar is
"would this citation survive the reviewer asking one follow-up question,"
not unforgeability. No independent citable need ⇒ presumptive ⇒ cut or park
(see Disposition).

**RC-2 · Delete-and-check, with the objective named.** State what breaks if
this is removed, for WHOM, against WHICH on-record objective. *(Tufte's erase
test — bounded by Bateman/Inbar: an element may serve a second legitimate
objective; name the objectives BEFORE deleting.)* The only loss being an
unexercised presumptive FEATURE ⇒ rabbit hole. **Carve-out (Fowler's own):
malleability work — refactoring, tests, seams, design investment that changes
the cost of the NEXT change — is never "unexercised capability." The
discriminator has TWO legs, both required: malleability work (1) ships no
user-facing behavior nobody asked for, AND (2) names the next concrete change
it cheapens, where that change passes RC-1's independence-and-beneficiary
test itself (a North-Star clause, a user-stated direction, a recurring
incident class — never a "direction" whose only beneficiary is the
abstraction it shelters).
Over-engineered internal abstraction ships no behavior either — but it cannot
cite an independent next change, and leg 2 is where it dies.**

**RC-3 · Leverage.** What disproportionately large consequence does this buy —
and what does it let us DROP? *(Hardy's economy; Ousterhout's deep modules.)*
A **plan or process element** that adds machinery while retiring none is
presumed extraneous. Guards and preventative machinery are exempt here — they
are scored by RC-G below, not by retirement.

**RC-4 · Whose simplicity?** Does this "simplification" move complexity from
the implementation onto the user or maintainer? *(Gabriel; Ousterhout;
Sweller.)* Cutting intrinsic complexity or interface-protecting depth is
forbidden; extraneous load is the only legitimate target, and intrinsic
complexity is STAGED (progressive disclosure by frequency of use), never
deleted.

**RC-5 · Earned or premature — by written trigger, not vibes.** Scaffolding is
EARNED when it carries a **written retirement trigger** ("delete when X passes
its first live run"); it is squatting when no trigger exists. *(Gall's
provenance; co-contraction decays as the internal model forms.)* Symmetrically,
a simplification is premature when it precedes the understanding it claims —
if no working core exists yet, simplify the PLAN, not the safety margin.

**RC-6 · Critical path — flagged in-channel, never as interruption spam.**
Does the locked North Star fail without this — or merely feel less complete?
When genuinely uncertain, DO NOT PURSUE SILENTLY and DO NOT fire ad-hoc
questions: **PARK the element (zero further spend on it) and carry the flag
into the next block the user already reads** (the ≤200-word approval block or
the next status tick) as one line — *"possible rabbit hole: ___ because ___ —
pursue or drop?"* Load-bearing SIBLINGS continue; the flagged element itself
waits for the answer, so nothing uncertain is half-built before the user
speaks. If the parked element blocks the critical path, that is a HALT-worthy
dependency and is surfaced as one. One channel, batched, per the v1 law.

**RC-7 · Tie-breaker only.** Elegance ranks candidates of EQUAL demonstrated
capability. It never overrides a requirement, a datum, or a failing test.
*(Promoted from tie-breaker to truth criterion, beauty failed at industrial
scale: naturalness/SUSY; Domingos — simpler-is-more-accurate is "demonstrably
false"; simplicity's real payoff is human comprehensibility.)*

**RC-G · The guard clause (scores tests, gates, error handling, journals,
run-records).** Preventative machinery is forced by a **named hazard**, not a
recorded failure — demanding a recorded failure of a guard is demanding the
accident before the guardrail. But the hazard obeys the SAME independence law
as RC-1: it predates the proposal, or the user named it, or its class has
actually occurred somewhere on the record. "Plausible" is not a rung — a
hazard invented in the same breath as the guard it justifies fails, and
labeling machinery a "guard" confers no shelter without an independent
hazard. A guard passes when (a) its hazard meets the independence law, (b) it
can actually SEE the failure it guards (a gate that cannot see what the user
sees is not a gate), and (c) its false-alarm cost is stated. A guard failing
(b) is theater — fix or cut it; never count it as protection.

**Disposition — three verdicts, one rule.**  [DISP]

Every element receives exactly one verdict:

- **KEEP** — it has an independent need (RC-1; RC-G for guards) and no
  battery question is failing against it.
- **HOLD** — something is unresolved, and the hold is NAMED: a failing
  RC-2/3/4/5 with a written cure and retirement trigger (probation); an
  RC-6 uncertainty awaiting the user's batched one-line answer (parked, zero
  further spend); a guard failing any RC-G leg awaiting its fix (never
  counted as protection meanwhile); or a battery-spawned investigation
  running on its stated budget. **A HOLD without a written trigger, budget,
  or pending question is not a HOLD — it is a CUT that hasn't been logged
  yet.**
- **CUT** — no independent need (RC-1/RC-G fail), or a HOLD whose trigger
  fired without the element re-justifying itself. Logged, per v1 rule 5.

The rule: **need decides existence, unresolved questions decide HOLD, and
every HOLD carries its own expiry.** RC-7 never appears here — it is not a
per-element verdict; it breaks ties between whole candidates of equal
demonstrated capability.

---

## Known failure modes of elegance-as-criterion (the gate's own guards)

1. **Beauty-as-truth.** Naturalness predicted SUSY at LHC energies; nothing
   came; the criterion got re-tuned instead of retired. Tie-breaker, search
   heuristic — never a verdict. (CORROBORATED)
2. **Premature simplification.** Einstein's authentic 1933 clause is two-sided:
   "...as simple and as few as possible WITHOUT having to surrender the
   adequate representation of a single datum of experience." The popular "but
   no simpler" is a 1950 Sessions paraphrase that drops the protection.
   (CORROBORATED)
3. **Minimalism damaging a second objective.** Tufte-minimal charts lost
   legibility (Inbar 2007) and memorability (Bateman 2010). The erase test is
   valid only after every objective the element serves is named. (CORROBORATED)
4. **Unfamiliar ≠ inelegant.** Hickey: simple means unentangled — objective;
   easy means familiar — relative to a person. Reviewers reliably misgrade
   unfamiliar-but-unentangled as complex. (OBSERVED)
5. **Option-cutting on weak evidence.** Hick's cost is logarithmic and trains
   toward zero; choice-overload meta-analyzed to a mean effect near zero.
   "Fewer options" is not a law. (OBSERVED)
6. **Leprechaun statistics.** The "64% of features rarely used" figure traces
   to four internal apps at a 2002 keynote — the PROVENANCE CRITIQUE is
   corroborated; the figure itself never rose above CLAIMED. The gate's
   economics rest on corroborated technical-debt waste (~23% of dev time,
   Besker et al.), never on folklore.
7. **The gate eating its own guards.** The first draft of THIS battery would
   have cut preventative tests and safety gates (no recorded failure, no
   retired machinery). RC-G exists because two independent adversarial
   reviewers caught it. A battery without a guard clause is a hazard, not a
   standard. (OBSERVED — this run)

## Misattribution ledger (do not ship these)  [ML]
- "Entities must not be multiplied beyond necessity" — John Punch 1639, NOT Ockham.
- "As simple as possible, but no simpler" — Sessions 1950 paraphrase, NOT Einstein.
- KISS/Kelly Johnson — anecdotal; keep the operational form (simplicity defined
  by the maintainer's tools), drop the attribution.
- Standish 64% — leprechaun; cite Besker ~23% instead.
- "What does it let us drop?" is Hardy's economy and deep-module thinking —
  NOT Gall. Gall's law backs provenance (RC-5), not leverage (RC-3).
