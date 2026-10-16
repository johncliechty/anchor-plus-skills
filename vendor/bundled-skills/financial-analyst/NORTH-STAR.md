# North Star — financial-analyst

> **PROMOTED, not authored** (2026-08-15, elegance-v2 sleep cycle): this skill's
> locked objective lived only as the in-code charter in
> `bin/deal-review.mjs` (`buildCharter`, "North Star for the review round",
> 2026-07-25). The CODE remains authoritative for the review round (it also
> loads the trio `investment-memo` pack rubric at runtime — deliberately not
> frozen here); this file exists so fresh sessions and the sleep loop have the
> drift anchor every other skill carries. Amending the objective is a human
> re-lock, not an edit.

Financial-analyst is a deal-flow and valuation engine: an exact-Decimal
dependency-graph library with ready templates (VC round comp, real-estate
equity waterfall) that compiles synchronized Excel + Python models and
grounded reports. **The math is not in dispute** — tie-out proves
Excel == Python to the penny; the adversarial review exists for everything
the math cannot prove.

## The charter criteria (verbatim ids from `buildCharter`, plus the loaded
## `investment-memo` pack rubric at runtime)

- **[fa1] TEMPLATE OMISSIONS** — the shipped templates are
  textbook-granularity (no option-pool shuffle, SAFEs, share counts, catch-up
  tiers, IRR/MOIC unless extended). Any omission LOAD-BEARING for THIS deal
  that was not extended or explicitly caveated is a BLOCKER.
- **[fa2] ASSUMPTION SANITY** — inputs the model treats as given (valuations,
  rates, waterfalls) must be plausible and sourced for this deal, or caveated.
- **[fa3] GROUNDING** — every number traces to the evaluated graph or declared
  inputs (deterministic gate); reviewers flag semantic abuse the gate cannot
  see — right number, wrong claim.

A finding MUST set `traces_to_north_star` and name the criterion id it blocks.
