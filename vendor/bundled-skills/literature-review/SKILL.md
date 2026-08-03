---
name: literature-review
description: An interactive literature-review skill — deterministic snowball search + PRISMA discipline, ONE-call-per-paper claim extraction with deterministic quote grounding, weighted consensus synthesis, and a final adversarial pass through researchPrime's real governed round. Outputs a source-grounded Assumptions Ledger + comparison matrix.
---

> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol.

# literature-review

You rigorously ingest, corroborate, and synthesize the literature around a seed paper, weighting
evidence by academic quality and adhering to the OBSERVED > CORROBORATED > CLAIMED ladder. The
deliverable is a source-grounded **Assumptions Ledger** + **parameterized comparison matrix** that
downstream phases can build on.

> **Tier definition (Heavy vs regular · stakes-gated cross-model · seat mapping) + invocation
> discipline:** canonical in `<path> Foundry\AGENTS.md` → "Skill tiers" / "Invocation
> discipline" / "Run capture". Heavy = `TRIO_TIER=heavy` on the composed seats. Do not re-define
> or deliberate any of it.

## How to run (operator manual — REWIRED REAL 2026-07-11; the CLI never fabricates)

```
LITREVIEW_LIVE=1 node bin/cli.mjs --seed <pdf-or-s2-url> \
  [--depth 1] [--max-papers 6] [--columns method,evidence,result] \
  [--stakes low|medium|high] [--out litreview-out] [--mock-user "q: ...|approve"]
```

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
training record; long runs emit the LOCKED global status table every ~10 min.

> **⏱ STATUS UPDATES TO CHAT:** When running long phases in the background, you MUST arm a 10-minute cadence (`ScheduleWakeup` ~600s) and provide scheduled updates to the user in the LOCKED Status-table format — canonical definition in ONE place: user-global `AGENTS.md` → "Long-run progress updates" (`[HH:MM]` header · Effort/Doing/Status/Tests/Blocker/Procs/**Journal** rows · ETA + To do footer). The **Journal** row (mandatory, `none` when empty) recaps everything journaled since the last tick — the SESSION composes it from this skill's `journal/`.

## Usage journal (lessons — append after every REAL run)

Append one `NNNN-<slug>.md` to `journal/` (7 canonical fields — id/skill/situation/context/
observation/outcome/provenance; ≤15 lines; append-only). The machine record is auto-captured;
the NNNN entry is for what the run TAUGHT you.
