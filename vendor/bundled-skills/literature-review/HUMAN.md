# Literature Review

**One sentence:** A disciplined literature review from a seed paper — snowball search, PRISMA-style exclusions, quote-grounded claims, and an adversarial pass so the synthesis doesn’t float free of sources.

## Use this when
- You’re mapping a research area around a known seed paper or DOI/PDF
- You need an assumptions ledger and comparison matrix for later work
- You care that every extracted claim is tied to a real quote in the paper

## Do not use this when
- You only want a casual “what’s hot in this field” chat
- You don’t have a seed and won’t approve a candidate set
- You need primary experimental research rather than secondary literature synthesis

## What you get
- Deterministic ingest and citation snowball with logged exclusions
- Human (or stamped auto) approval of which papers enter the review
- Claims extracted one paper at a time, each grounded in a verbatim quote
- Weighted consensus synthesis plus an adversarial review pass when live seats run

## What it is not
- Not a full systematic review certification body (PRISMA-ish discipline, not a formal registry)
- Not free to invent quotes — fabricated quotes are rejected
- Not a substitute for reading the papers that matter most to you

## Variable Strength (`Literature-Review` Standard Default vs. `Literature-Review Heavy`) — What to Call When
- **Call `Literature-Review` (default = `Standard` · one generalist model below frontier @ `medium` effort on extraction, synthesis, and review)** when mapping a new topic around a seed paper, building a working comparison matrix, or screening candidate citations quickly.
- **Call `Literature-Review Heavy` (`⚡ Heavy` · frontier model @ full effort across synthesis and the governed `researchPrime` adversarial round)** when producing a publication-bound related-work section, grant narrative, or contested clinical/scientific synthesis where subtle methodological distinctions matter.

## How to start (human)
1. Provide a seed PDF or Semantic Scholar link and what columns you care about.
2. Review the ranked candidate list; approve or reject before extraction.
3. Read the assumptions ledger and matrix with source links in mind.
4. For high stakes, keep live verification on; without it, only the early deterministic stages run and the run says so.

## Limits (honest)
- API rate limits and paywalls can shrink the reachable set
- Live extraction and adversarial seats require a live configuration; offline mode is honest but partial
- Depth knobs may thin search/adversarial rounds, never quote-grounding discipline

## For agents / engines
Full protocol and wiring live in `SKILL.md` next to this file. Load that only when running the skill — this card is for people.
