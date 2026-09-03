---
name: jumper
description: Jumper is the high-order Ideation and Brainstorming Engine of the portfolio. It composes the Gandalf deep-think skill to generate novel, out-of-the-box solutions, architecture extensions, and creative pivots using SCAMPER, Analogical Transfer, and TRIZ, with a 3-gate kill-filter and Grounding Execution Protocol.
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

# Jumper — the ideation and brainstorming engine

Jumper is the dedicated, high-order Ideation and Brainstorming Engine of the portfolio. It strictly composes the Gandalf deep-think skill to force divergent, structured, and vetted lateral thinking.

> **Tier definition (Heavy vs regular · stakes-gated cross-model · seat mapping) + invocation discipline
> (zero deliberation · the LOCKED global status table · run capture):** canonical in
> `AGENTS.md` (Foundry root on the author host; your install root in a distributed bundle) → "Skill tiers" / "Invocation discipline" / "Run capture".
> Jumper-Heavy runs the composed Gandalf at the MATCHING tier. Do not re-define or deliberate any of it.

## How to run (operator manual — a real invocation runs THE ENGINE, never an improvised pipeline)

```
node bin/jumper-run.mjs --problem "<the problem statement>" [--output out.json]
node bin/jumper-run.mjs --input problem.txt --fan-out 5 --retry-on-kill
node bin/jumper-run.mjs --problem "<statement>" --depth LITE
node bin/jumper-run.mjs --problem "<statement>" --depth FULL --fan-out <ideaRounds>
```

- **Default = PORTFOLIO mode (`fanOut 3`)**: 3 sphere-diversified candidates built in parallel
  (natural sciences / arts-humanities / rule systems …), each through Hesse→Dirac, judged by the
  kill-filter as a tournament → `survivors[]` ranked + GEP on the winner, `killLog[]` for the dead.
  `--fan-out 1` selects the legacy single-candidate pipeline; max 5.
- **`--depth` lock (LITE|SPIKE|FULL):** knobs from `@foundry/triage` only (`resolveJumperDepthKnobs`).
  When `--depth` is set and **`--fan-out` is omitted**, `fanOut` inherits live `ideaRounds` (one derivation).
- **P-CONFLICT (dual flags):** if both `--depth` and `--fan-out` are set, allow only when
  `--fan-out ===` live `ideaRounds`; mismatch → exit≠0 naming both values (`JumperDepthFanOutConflictHalt`),
  engine never starts. Recovery: omit `--fan-out` or pass the equal value.
- **killGates floor:** every depth keeps `killGates ≥ 3` (never thinned). Pre-run refuse below floor
  (`JumperKillGatesFloorHalt`); engine does not start.
- **Model seats are pre-decided** (invocation discipline): Anchor's coding family owns
  drafting/ideation and its review family owns Gate 3. `JUMPER_GATE3_DRIVER` may
  retarget the review driver, but never the independence rule.
- **HALTs are honest outcomes, not bugs — and a HALT never destroys paid work (2026-08-19,
  journal 0031)**: `JumperSelfReviewHalt` = Gate 3 resolved to the drafter family (fixed at
  PRE-FLIGHT since 2026-07-25 — the CLI refuses in under a second, before any paid seat;
  select an independent review family or explicitly retarget `JUMPER_GATE3_DRIVER`);
  `JumperCrossFamilyDegradeHalt` = agy down (Jumper NEVER silently self-reviews — rerun when agy
  is back; if candidates were already built, the CLI emits them to `--output` stamped
  **NOT FULLY VETTED** instead of nothing). `RefuterBudgetHalt` no longer kills a composed run
  (it killed THREE tournaments: journals 0003/0012/0030): the compose seam CAPS refuter demand
  at the budget (prereg R=3, or `--budget N`) — the first R firing elevations are refuted for
  real, the excess floor to SPECULATIVE with the "no independent refutation ran" stamp, and the
  output carries `refutation_capped` naming the numbers. Standalone gandalf keeps its HALT.
  `--no-live-refuter` floors Gandalf elevations to SPECULATIVE honestly; it does
  **not** disable Jumper's Gate-3 kill-filter, its liveness ping, or its seating check.
- **Watch the heartbeats** (2026-07-25): the CLI streams `jumper: gandalf:start|done`,
  `sphere:i/n`, `killfilter:candidate i/n …` to stderr — a healthy long run is visibly moving;
  silence for many minutes is the anomaly (journal 0014's false-DONE came from this blindness).
- **Startup can no longer stall silently (2026-08-19, journal 0031)**: the CLI writes an
  IN-FLIGHT run record (start time, pid, input) the moment the engine starts — record present
  = engine started; absent = the launch wrapper never reached node (the BA-815 0.14s-CPU/25-min
  stall left zero trace). A STARTUP WATCHDOG then fails the run LOUDLY, writing WHY into that
  same record, if the first model round-trip hasn't landed within `JUMPER_STARTUP_WATCHDOG_S`
  (default 900). The record is rewritten in place at HALT/success — one record per run.
- **NG canaries are executable** (`test/ng-canaries.test.mjs` + `canaries/canary-set.v2.json`):
  no gate-bypass option exists, pre-stamped tiers get re-graded, same-sphere survivors are
  never relabeled as diverse.
- Do NOT run the tripartite pipeline "by hand" in prose — an improvised run bypasses the
  commission ledger, the cross-family gate, and every honesty stamp. The engine or nothing.
- Every CLI run auto-writes a training record to `journal/runs/` (AGENTS.md "Run capture");
  long runs emit the LOCKED global status table every ~10 min unprompted.

## When to use
Trigger Jumper when the user wants to brainstorm, ideate, find out-of-the-box solutions, run creative pivots, map structural analogies, or resolve core system contradictions. Triggers: "brainstorm," "ideate," "help me pivot," "analogical transfer," "/jumper."

## North Star (LOCKED — verbatim)
Jumper is the dedicated, high-order Ideation and Brainstorming Engine of the portfolio. It strictly composes the Gandalf deep-think skill—using Gandalf's rigorous diagnosis as a foundation—to generate novel, out-of-the-box solutions, architecture extensions, and creative pivots. It leverages structured human ideation frameworks (e.g., TRIZ, SCAMPER, Analogical Transfer) to force divergent thinking. Crucially, it employs a 'generative-and-vetted' methodology: all generated ideas are immediately subjected to a ruthless kill-filter to ensure only structurally sound, highly promising concepts are presented to the user, completely eliminating LLM hallucination and shallow brainstorming.

## Core Architecture: The Tripartite Ideation Engine
Jumper operates as a high-order brainstorming engine that deeply composes Gandalf. To force divergent thinking without hallucination, it runs on a strictly phased Tripartite Engine:

*   **Phase 1: Peterson Query (Deconstruction & Probe)**
    *   **Mechanism:** Uses the **SCAMPER** framework to aggressively question the current state of the problem. It maps anomalous data, breaks the problem down into its fundamental assumptions, and identifies core contradictions.
    *   **Goal:** Explore the unknown and define the exact parameters of the chaos/problem space.
*   **Phase 2: Hesse Glass Bead Translation (Abstraction & Analogy)**
    *   **Mechanism:** Uses **Analogical Transfer** to lift the deconstructed problem out of its native domain. It maps the structural properties of the problem against a completely foreign domain (e.g., mapping a software architecture problem to Renaissance painting techniques or biological cell structures).
    *   **Goal:** Create a "universal symbolic language" connecting disparate disciplines across all human knowledge, art, and philosophy.
*   **Phase 3: Dirac Transfer (Symmetry & Resolution)**
    *   **Mechanism:** Uses **TRIZ** principles of invention to resolve the contradictions identified in Phase 1, using the analogical insights generated in Phase 2.
    *   **Goal:** Apply mathematical/structural elegance to map the abstract solution back to the concrete problem domain, ensuring the solution is beautiful, symmetrical, and highly effective.

## The Synthesizer Subagent (Intuition & Oversight)
To ensure the rigid frameworks (SCAMPER/TRIZ) don't miss obvious cross-domain connections or lateral leaps, a **Persistent Synthesizer Subagent** oversees all three phases.
*   **Role:** It leverages frontier-model intuition to catch blind spots, synthesize connections across the phases, and inject "steering flags" into the Tripartite Engine.
*   **The Oranges-Lens (Proactive Foresight):** The Synthesizer is explicitly guided by the *Parable of the Oranges*. It must exercise deeply contextual foresight—anticipating the true underlying needs, seeing 2-3 steps ahead, and finding high-value connections across domains rather than passively watching the frameworks execute.
*   **Constraint (The Trio Archetype):** It steers, but never decides. It cannot bypass the Tripartite Engine or the Kill-Filter. It strictly provides intuitive oversight to guarantee that a frontier model's native capacity for connection-making is fully utilized alongside the rigid frameworks.

## The 3-Gate Kill-Filter (Anti-Hallucination Guardrails)
Every generated idea—including any intuitive leaps suggested by the Synthesizer—must survive a ruthless three-gate kill-filter before being presented to the user. (Implementation: Gates 1+2 are judged in ONE model call with two independent verdicts — same-family cheap pre-filters, short-circuiting BEFORE the spend on Gate 3; Gate 3 is a separate CROSS-FAMILY adversarial call.)

*   **Gate 1: Existence Proof**
    *   *Test:* Is the concept theoretically possible? Does it violate the fundamental axioms or laws of its target domain?
*   **Gate 2: Glass Bead Syntax Test**
    *   *Test:* Does the analogical mapping hold logical/structural integrity, or is it merely a forced, shallow metaphor? (e.g., Does the biological analogy *actually* map to the software problem's constraints?)
*   **Gate 3: Dirac Structural Symmetry Test (Adversarial Gate)**
    *   *Test:* An independent adversarial subagent reviews the surviving concepts. It explicitly hunts for LLM hallucination, logical gaps, and asymmetry. Only ideas that the subagent verifies as structurally sound and practically applicable pass this gate.

## The Output: Grounding Execution Protocol
To avoid the "Ivory Tower" trap, Jumper will never output purely theoretical concepts. The final output must include a **Grounding Execution Protocol**: a concrete, step-by-step test plan to validate the idea in reality.
*   **For Empirical/Scientific Domains:** A formal experiment design, defined variables, and success metrics.
*   **For Software/Engineering:** A proof-of-concept architecture, unit test definitions, or a minimal viable implementation plan.
*   **For Art/Philosophy:** A concrete phenomenological demonstration, a rigorous logical proof, or a specific creative output.

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
