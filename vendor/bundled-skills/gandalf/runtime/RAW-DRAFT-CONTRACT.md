# Gandalf runtime — the RAW-DRAFT contract (Tier-1)

> What the model emits in runtime mode, and what the host does with it. The model emits **only** the
> raw draft below as its final message — it does **NOT** self-assign tiers or refutation stamps. The
> host (`runtime/gandalf-run.mjs` → `runtime/seam-pass.applySeamPass`) applies the shipped seams and
> produces the canary-conformant, honestly-graded `schema/advisor-output.schema.json` output.

## Why a contract (journal/0001 + LESSONS.md)

The first real Gandalf runs showed the model produces excellent DIAGNOSE / SITUATE / ANTICIPATE
**content** but, asked to also stamp the honest tiers itself, keeps hand-approximating them and failing
the B-honesty canary. The honest tiers + stamps are the **seam's** job, applied deterministically. So
the model's job is reduced to emitting the raw findings; the host stamps them. **Do not narrate a tier
or a "no independent refutation ran" stamp in `reasoning` — emit the raw fields and let the host apply
the seam.**

## Emit ONLY this JSON object (the raw draft)

```jsonc
{
  "reasoning": "<the deep-think reasoning — emitted BEFORE the verdict>",
  "verdict":   "<the overall verdict; may be 'this is sound'>",

  "findings":  [ /* diagnose / situate / anticipate findings — see per-kind shape below */ ],
  "nitpicks":  [ /* minor, low-stakes findings: { id, rung, reasoning, verdict } */ ],
  "elevations":[ /* forward, value-adding suggestions — see shape below; NO tier, NO stamp */ ]
}
```

`reasoning`, `verdict` are required non-empty strings; `findings`, `nitpicks`, `elevations` are
required arrays (may be empty). A malformed draft (missing a required key, a non-object item, an
anticipate finding missing its future-state) is **rejected** by the host with a non-zero exit and an
honest stderr message — **no partial / forged output is written.**

### `findings[]` — per `kind` (the fields each seam consumes)

**`kind: "diagnose"`** — a vetted-core diagnosis. Do NOT add `gandalf_core`; the host stamps it
(`stampDiagnoseCoreProvenance`). Do NOT carry any external commission id (diagnosis is the core's).
```jsonc
{ "id": "d-1", "kind": "diagnose", "rung": "<REFUTED|UNVERIFIED|CLAIMED|CORROBORATED|OBSERVED>",
  "reasoning": "...", "verdict": "...", "severity": "<minor|major|critical>"? }
```

**`kind: "anticipate"`** — a bounded, forward-looking premortem on the SINGLE effort. Emit the two
future-state fields; the host composes the finding (`composeAnticipation` sets `subject_cardinality: 1`
and refuses any regret / counterfactual-cost field).
```jsonc
{ "id": "a-1", "kind": "anticipate", "rung": "UNVERIFIED",
  "reasoning": "...", "verdict": "...",
  "future_state_condition": "<a not-yet-present condition>",
  "enabling_assumption":    "<what must hold for it to arrive>",
  "severity": "<minor|major|critical>"? }
```

**`kind: "situate"`** — a best-in-class framing. Emit the SITUATE pipeline stages; the host composes +
honesty-caps the finding (`composeSituate`). **Tier-1 has no live researchPrime commission**, so
`facts_verified` is `false` by construction and the host attaches the `needs_verification` handoff.
```jsonc
{ "id": "s-1", "kind": "situate", "reasoning": "...", "verdict": "...",
  "abstraction":  { "stage": "S0-abstract", "skeleton": "<domain-neutral pattern>" },
  "commission":   { "skill": "researchPrime", "question": "...", "cross_model": false,
                    "origin_family": "fable-5", "independent_origin": false,
                    "researchprime_commission_id": null },
  "structure_map": { "answer": "<answer-first conclusion>",
                     "correspondences": [
                       { "source_relation": "...", "target_relation": "..." },
                       { "source_relation": "...", "target_relation": "..." }  /* >= 2, RELATIONAL */
                     ] },
  "outside_view_base_rate": "<the outside-view base rate>" }
```

A finding of any other `kind` (or none) passes through untouched. A finding with `rung: "REFUTED"`
**drops** (the only drop condition).

### `elevations[]` — forward suggestions (NO tier, NO stamp)

Emit the suggestion + the **named concrete defeater** (`what_would_refute_it`), never a tier or a
stamp. In Tier-1 no independent refuter runs, so the host downgrades **every** elevation to
`SPECULATIVE` and stamps it `"no independent refutation ran"` (`vetElevationRefutation` + `labelTier`).
```jsonc
{ "id": "e-1", "value_if_true": "<low|medium|high>", "rung": "<...>",
  "reasoning": "...", "verdict": "...",
  "what_would_refute_it": "<a NAMED concrete defeater — never a confidence word>",
  "severity": "<minor|major|critical>"? }
```
A `rung: "REFUTED"` elevation **drops**.

## What the host applies (deterministically, never the model)

| Stage | Seam | Effect |
|-------|------|--------|
| diagnose | `seam/diagnose-core.stampDiagnoseCoreProvenance` | appends `gandalf_core: { protocol: "PROTOCOL v2" }` |
| anticipate | `seam/anticipate.composeAnticipation` | `subject_cardinality: 1`; B3 + B9 enforced |
| situate | `seam/situate.composeSituate` | rung cap (no self-CORROBORATED) + `needs_verification` handoff |
| elevation | `seam/refute.vetElevationRefutation` → `seam/score-label.labelTier` | SPECULATIVE floor + stamp; single-family PROMISING ceiling |
| drop | `seam/score-label.dropsFromOutput` | only `rung: "REFUTED"` drops |
| synthesis | `seam/score-label.composeRiskLabels` | one `risk_labels` entry per present leg, envelope rung, PROMISING ceiling |
| degradation | (host roll-up) | any per-item `degraded: true` ⇒ top-level `degraded: true` (B6) |

The result is validated by the shipped `test/harness.assertIncrement1Conformant` before it is written;
if it would not pass, the host exits non-zero and writes nothing.

## Scope note (Tier-1)

This host runs the **deterministic** seam pass on ONE model run. It does **not** dispatch the live
independent named-defeater refuters or the researchPrime SITUATE commission (those need the `agent()`
seam the repo flags as the integration point the gate never runs). The **live-refuter PROMISING tier**
is the sequenced follow-on — see `LESSONS.md` and `journal/`.
