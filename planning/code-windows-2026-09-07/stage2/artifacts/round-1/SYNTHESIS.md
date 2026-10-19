# Shark-Tank Round 1 — BLOCKED

- Verdict: **BLOCKED** (1 new BLOCKER)
- Angles: Skeptic=operator, Contrarian=skeptical-researcher
- Findings: 21 · Blockers: 1 · Demoted (inclusion test): 0

## Blocking (≥2 Sharks agree, traces to a criterion)
- **MAJOR** `topic:cell-mixed-path-url-vs-where` — agree 2 (Skeptic, Contrarian) — The parser says a cell with both a path and a URL "keeps the path as the open target." `delivRow` takes `if (it.url)` first and never rewrites that row to `/notebook`. If `url` is still set, John clicks a `.py` and lands on the live URL. If `url` is cleared because a path exists, a register row that still has the 0110 launch-page path plus the real lab/Shiny address keeps opening the launch page — the gap this criterion exists to close. One cell cannot obey both sentences. The click is unspecified.

## Demoted (failed the inclusion test — cannot hold the loop open)
_none_
