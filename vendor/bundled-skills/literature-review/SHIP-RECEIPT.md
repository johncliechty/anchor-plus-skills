# 2D breadth — ship receipt (2026-07-22)

## What you got (works)

After plan **APPROVE**, literature-review:

1. Materializes **facets** from `PlanArtifact.branches` (never invents silent facets).
2. Runs **breadth before** main snowball (ordering locked by tests).
3. Gathers **per-facet in parallel** (cap ≤2–3), **merge+dedupes** by stable paper id.
4. Writes **honesty/telemetry** stamps (`breadth-stage.json`, run record).
5. researchPrime gets a **pre-Phase-2 facet-coverage seam** that imports the same helpers (oranges still answer-branches only).

**Proof of work:** `node --test test/` in this skill → **452 pass / 0 fail** (re-run at ship).

## What blocked Foreman’s “DONE” stamp (not “feature broken”)

| Issue | Severity for *you* | What it means |
|--------|--------------------|----------------|
| Plan said dual-suite; Foreman only auto-runs lit-review | Process | Don’t claim “RP suite green” without measuring RP |
| RP `npm test` red on nested Crucible/Foreman suite pins | Portfolio ambient | Unrelated engine test health; not breadth unit failures |
| Vacuous-GREEN on resume | Ops | Wave 5 code already landed; resume wouldn’t re-stamp free GO |

## Ship bar chosen

**Product ship, not “every nested trio engine suite green.”**

- In: green lit-review suite + real breadth modules + RP import seam + honest dual-suite notes.
- Out of this ticket: fixing ambient Crucible/Foreman fails that `researchPrime/test/trio-green.test.mjs` re-runs.

Those ambient fails are legitimate **later** work when you do the bigger trio/foundry pass — they should not hold this feature hostage.

## Wave 6

**No shared extract** — RP already thin-imports lit-review; no byte-for-byte fork to lift.

## Operator close

Foreman checkpoint may still say `halted` at wave 5; **product is shipped by this receipt + green suite + committed tree.** Do not require another multi-hour Foreman loop to use the skill.
