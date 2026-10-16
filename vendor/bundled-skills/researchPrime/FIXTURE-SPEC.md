# researchPrime Upgrade — Planted-Defect Fixture Spec (Wave 1)

> **Status:** authored in Wave 1; **frozen + sized + captured in Wave 3** (power calc sets the
> count of planted defects so the pre-registered **G** is statistically reachable — MASTER-PLAN
> crit 2). This spec defines WHAT the fixture must contain and HOW each class is scored. The
> actual fixture corpus and the hashed single-pass baseline are produced in Wave 3.

This fixture is the ground truth for crit-1 (trustworthiness ↑, correlation-gated), crit-3
(research path better-aimed), and crit-7 (learned independence). It is a corpus of research
claims/sources with **planted defects of known type and location**, so loop recall can be
measured against a known answer key rather than asserted.

## Required machine-readable manifest
Each planted defect is one record (later emitted as JSONL alongside the corpus in Wave 3):

```
{
  "id": "<stable defect id, e.g. cbs-003>",
  "class": "ordinary | correlated-blind-spot | path-defect",
  "location": "<file/claim/ledger-row the defect lives in>",
  "ground_truth": "<the correct answer the loop must recover>",
  "detectable_by": ["G1" | "G2" | "G3" | "G4" | "G7" | "..."],
  "single_pass_caught": true | false,
  "severity": "low | medium | high"
}
```

`single_pass_caught` is filled by the Wave-3 single-pass baseline run (hashed). Recall is
`caught_by_loop / planted`, broken out **by source gate AND by class** (IMPLEMENTATION-PLAN
Wave 6). Recall attribution honours I5: G2 (self-consistency) recall counts as **precision-only**
and must not move the crit-1 accuracy number.

## Mandatory defect classes

### 1. Ordinary planted defects (baseline recall)
Standard single-origin factual/citation defects a competent single reviewer can catch with one
fresh fetch (G1). Establish the gap-closure denominator (the single-pass miss rate that **G**
is a fraction of).

### 2. Correlated-blind-spot (CBS) class — **MANDATORY, gating (I2)**
Defects engineered so that reviewers of the **same lineage share the blind spot**: a plausible
but wrong consensus answer that any same-family reviewer will independently reproduce (e.g. a
widely-repeated-but-false "fact", a shared training-data artifact, a unit/sign convention every
same-family model gets wrong the same way). Purpose:

- Make CBS recall a **gating sub-criterion**, not an aside: CBS recall **< `C_min` fails crit-1
  regardless** of the blended number (MASTER-PLAN crit 1 / I2).
- Honesty check (I1): in **default (single-family) mode** the loop must **DETECT and STAMP** the
  CBS class as a *measured ceiling* — it must NOT claim to have closed it. Only **Enhanced mode**
  (a genuinely cross-lineage origin) may recover CBS defects and count the fresh origin.
- Ground truth for ρ̂ (crit 7 / Wave 9): ρ̂ is calibrated against **this class's known co-miss
  events**, never against the live ledger's self-reported catches (A5: ρ̂ is a censored lower bound).

The CBS records carry an extra field `lineage_trap: "<why same-lineage reviewers co-miss>"` so the
correlated structure is explicit and reviewer-checkable.

### 3. Declared-low-but-irreversible case — **MANDATORY (I6 under-call guard)**
At least one item whose author **declares the stakes LOW** while its reversibility is in fact
**irreversible** (e.g. a "minor" recommendation that, if acted on, cannot be undone). Purpose:

- Guard the stakes governor against **under-calling** (MASTER-PLAN I6): the adjudicated stakes
  vector must catch the irreversibility and force **tier ≥ medium** despite the low declaration
  (IMPLEMENTATION-PLAN Wave 4 `Given reversibility="irreversible", Then tier ≥ medium`).
- The record carries `declared_stakes: "low"` and `reversibility: "irreversible"`; the answer key
  is `expected_tier: ">= medium"`. A run that honours the low declaration FAILS the under-call guard.

### 4. Planted-path-defect probe — **for crit-3 (foresight re-aim)**
At least one item with a deliberately wrong/wasteful research branch that good foresight should
**drop or reorder**. The answer key names the exact branch that must be dropped/reordered and its
counterfactual cost. crit-3 passes only if the Oranges foresight receipt names **≥1 dropped/reordered
branch + its counterfactual cost** (equality assertion on the exact branch — IMPLEMENTATION-PLAN
Wave 4); a no-op pass is stamped "no foresight value added" and crit-3 reported NOT satisfied.

## Sizing (deferred to Wave 3)
The count per class is set by a **power calc** so the pre-registered **G** gap-closure is
statistically reachable on this fixture (MASTER-PLAN Phase 0 / crit 2). The CBS class must be large
enough that CBS recall can be compared to `C_min` with a meaningful sample. Sizing is NOT decided in
Wave 1 — it is a Wave-3 step gated on the pre-registration being GREEN.
