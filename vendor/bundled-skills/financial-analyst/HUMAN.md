# Financial Analyst

**One sentence:** Builds deal and valuation models with exact decimal math, then can emit matching Excel and Python so the numbers tie out to the penny.

## Use this when
- You need a real deal model (VC round, equity waterfall, ownership math)
- Someone will rely on the spreadsheet or the numbers must be defensible
- You want Excel and Python generated from the same underlying model

## Do not use this when
- You only need a back-of-envelope rule of thumb (just ask in chat)
- You need tax, legal, or investment advice from a licensed professional
- You’re looking for market “attractiveness” opinions without your own benchmarks

## What you get
- Templates to start from (e.g. VC round comparison, real-estate waterfall)
- Exact-decimal dependency graph so inputs recompute cleanly
- Reports grounded in model nodes (not vibes)
- Optional synchronized Excel + Python with a machine-checked tie-out

## What it is not
- Not tax, legal, or personalized investment advice
- Not a complete suite of every deal structure out of the box (templates are starting points)
- Not a free pass for qualitative valuation claims without sources you provide

## How to start (human)
1. Say which deal type and the key inputs (valuations, cash flows, ownership splits).
2. Confirm whether you need full deliverables (Excel/Python/report) or a quick model check.
3. Review outputs; ask for template extensions when real structure differs from the starter.
4. For dual Excel/Python, require the tie-out line (max delta zero) before sharing.

## Limits (honest)
- Shipped templates are textbook-granularity starters; real deals often need extension
- Requires the skill’s Python environment (`openpyxl` etc.)
- Grounded numbers only — no invented “market standard” terms

## For agents / engines
Full protocol and wiring live in `SKILL.md` next to this file. Load that only when running the skill — this card is for people.
