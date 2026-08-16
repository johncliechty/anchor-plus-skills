---
name: financial-analyst
description: Deal-flow and valuation engine — an exact-Decimal dependency-graph library (Python, in this skill folder) with ready templates (VC round comp, real-estate equity waterfall) that compiles synchronized Excel + Python models and grounded reports. Use for deal modeling, waterfalls, cap-table/round math, or when penny-exact Excel/Python tie-out matters.
icon: icon.jpg
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

# financial-analyst

You have a WORKING engine in this skill's folder — use it; never re-derive the math
ad hoc. Everything below runs on Python stdlib + `openpyxl` (see `requirements.txt`).

> **Tier definition (Heavy vs regular · always-cross-model · seat mapping):** canonical in `AGENTS.md` (Foundry root on the author host; your install root in a distributed bundle) → "Skill tiers". A `-Heavy` run uses top-frontier models on EVERY seat regardless of the base session (delegate the frontier seat to a frontier-pinned sub-agent if the base session isn't frontier); foundry skills are ALWAYS true cross-model. Do not re-define tiers locally.

## Scope gate (read first)

- **Simple finance question** (rule of thumb, one formula, "is this rental roughly a
  good deal?") → just answer it in prose with the formula shown. Do NOT build models.
- **Deal model requested** (waterfall, round comp, "build me the model", anything
  where numbers must be defensible or handed to someone) → use the engine below.
- The full tri-format output (Excel + standalone Python + agent-facing module) is
  produced only when the user wants deliverables, not for every calculation.

## The machinery (all in this folder)

| File | What it is |
|---|---|
| `graph_engine.py` | Exact-`Decimal` dependency graph: `InputNode`/`FormulaNode`, memoized evaluation, cycle detection, cache invalidation on `set_input` |
| `agent_interface.py` | `FinancialAnalystAgent` facade — `load_template / set_input / get_value / evaluate / generate_report / compile_excel / compile_python` |
| `templates/vc_comp.py` | VC round comp: `pre_money_valuation`, `investment_amount` → post-money, dilution, ownership splits |
| `templates/re_waterfall.py` | RE equity waterfall: `initial_equity`, LP/GP shares, two hurdles + 3-tier promote splits over per-period cash flows |
| `compiler_excel.py` / `compiler_python.py` | Compile the SAME graph to a live-formula Excel workbook / a standalone Python model |
| `report_generator.py` | Grounded markdown/PDF report + an LLM-facing prompt digest, all read off the evaluated graph |
| `tests/` | pytest suite (`python -m pytest tests/ -q` from this folder) — run it after any engine/template change |

## Quickstart

```python
# cwd = this skill folder (imports are folder-relative)
from agent_interface import FinancialAnalystAgent
a = FinancialAnalystAgent()
a.load_template("vc_comp", pre_money_valuation=8_000_000, investment_amount=2_000_000)
a.set_input("investment_amount", 2_500_000)   # graph invalidates + recomputes
values = a.evaluate()                          # every node, exact Decimal
report = a.generate_report("report.md")
a.compile_excel("model.xlsx")                  # live-formula workbook
a.compile_python("model.py")                   # standalone matching model
```

Templates: `"vc_comp"` and `"re_waterfall"` (see each template file's signature for
its inputs; `re_waterfall` takes `cash_flows=[...]` per period). **Honesty note
(2026-07-11): the shipped templates are STARTING POINTS at textbook granularity** —
`vc_comp` has no option-pool shuffle / SAFEs / share counts, `re_waterfall` is one
fixed 3-tier simple-pref structure with no catch-up or IRR/MOIC nodes. A real deal
usually means extending a template per "Extending" below — plan for that, don't
discover it mid-session.

## The tie-out rule (non-negotiable when deliverables are produced)

When you emit both Excel and Python outputs, they must agree **to the penny** — and
this is now MACHINE-CHECKED: call **`a.tie_out()`** (compiles the standalone Python,
executes it, compares EVERY leaf node against the live graph's exact Decimals) and
put its `line` ("tie-out: N nodes compared, max delta 0") in the deliverable. Never
hand-roll the comparison, and never ship deliverables when `ok` is false — a
divergence is a bug to fix.

## Grounding rule

Every quantitative claim in a report/answer must be a node value read off the
evaluated graph (or a directly-cited user input). No unverified qualitative
valuation claims ("attractive multiple", "market-standard terms") unless the user
supplied the benchmark.

**This is now MACHINE-ENFORCED** (2026-07-25, prose-lock=C): `bin/deal-review.mjs`'s
deterministic grounding gate extracts every significant number from the report and
refuses delivery unless each traces to the `evaluate()` node dict or the declared
inputs — an ungrounded number is a named violation with context, never a vibe.

## The adversarial review engine (`bin/deal-review.mjs`, 2026-07-25)

The review layer this skill previously only CLAIMED. Runs strictly DOWNSTREAM of
`evaluate()`/`tie_out()` (the calc engine is never touched, never re-derived):

    node bin/deal-review.mjs --report report.md --values nodes.json [--inputs inputs.json] \
         [--rounds 3] [--live] [--out outdir]

- **Grounding gate first** (deterministic, pre-seat, see above).
- **3 fresh-context Sharks** with the ≥2-agree BLOCKER tally — imported from
  `crucible/bin/shark-tank.mjs`, charter = crucible's `investment-memo` pack criteria
  (c2 is this skill's grounding rule as a rubric line) + FA extensions (fa1 template
  omissions load-bearing for THIS deal, fa2 assumption sanity, fa3 semantic grounding).
- **Context-free Judge** (`crucible/bin/judge.mjs`) + convergence-until-dry (cap
  `--rounds`).
- **Unforgeable stamps**: `--live` binds prefs-aware cross-family seats via
  `researchPrime/bin/live-round-agent.mjs`; `cross_model` is DERIVED from the reached-
  family tracker. No seats ⇒ **honest stop** ("the adversarial review did NOT run") —
  never a fabricated review. Single-family runs carry the shared-blind-spot note.
- Verdict: `GO` only when grounded AND shark-dry AND judge-lockable. Output:
  `DEAL-REVIEW.json` + a `journal/runs/` capture.
- Gate: `node --test test/` (deal-review suite is hermetic — stub seats, no .py).

## Extending

A new deal type = a new `templates/<name>.py` exposing `create_<name>_graph(**inputs)`
that returns a `Graph`, plus a branch in `agent_interface.load_template` and a pytest
file mirroring `tests/test_vc_comp.py`. Keep every formula a `FormulaNode` (never
compute outside the graph — that is what guarantees the Excel/Python tie-out).

> **â± STATUS UPDATES TO CHAT:** When running long phases in the background, you MUST arm a 10-minute cadence (`ScheduleWakeup` ~600s) and provide scheduled updates to the user in the LOCKED Status-table format — canonical definition in ONE place: the canonical `AGENTS.md` → "Long-run progress updates" (`[HH:MM]` header · Effort/Doing/Status/Tests/Blocker/Procs/**Journal** rows · ETA + To do footer). The **Journal** row (mandatory, `none` when empty) recaps everything journaled since the last tick — the SESSION composes it from this skill's `journal/`.

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

