# Figure Designer

**One sentence:** Designs scientific and technical figures that communicate a clear message in five seconds — not decorative “looks scientific” fluff.

## Use this when
- You’re making figures for papers, whitepapers, or technical reports
- Architecture, neuroscience, ML, signal, or multi-panel diagrams need real meaning
- A figure looks pretty but readers can’t recover the point

## Do not use this when
- You need pure data plots with no design narrative (use analysis tools first)
- You’re asking for clip-art decoration without a takeaway
- The document doesn’t need figures at all

## What you get
- A locked one-paragraph narrative per figure before any drawing
- Conventions for hierarchy, color-as-meaning, labels, and panel layout
- A verification pass (self-contained, contrast, acronyms, caption length)
- Preferable workflow: narrative → sketch → build → verify → iterate

## What it is not
- Not “generate a fancy diagram first, invent the story later”
- Not rainbow charts, 3D junk, or texture for texture’s sake
- Not a substitute for correct science — design serves the claim

## How to start (human)
1. Write the 5-second reader takeaway for each figure (batch-lock multi-figure docs).
2. Approve those narratives before any SVG/PNG work starts.
3. Sketch layout and color meaning, then build.
4. Check: can a cold reader recover the takeaway from the figure alone?

## Limits (honest)
- Bad narrative in → decorative figure out; the skill won’t fix a vague message
- Tooling choices (SVG vs matplotlib vs Mermaid) still matter for the job
- Publication venues may add house rules beyond this baseline

## For agents / engines
Full protocol and wiring live in `SKILL.md` next to this file. Load that only when running the skill — this card is for people.
