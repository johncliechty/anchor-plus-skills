# Shark-Tank Round 1 — DRY

- Verdict: **DRY** (dry round — no new BLOCKER)
- Angles: Skeptic=skeptical-researcher, Contrarian=competitor, Analyst=bored-investor
- Findings: 12 · Blockers: 0 · Demoted (inclusion test): 2

## Blocking (≥2 Sharks agree, traces to a criterion)
_none_

## Demoted (failed the inclusion test — cannot hold the loop open)
- ~~`topic:gemini-omission-segment`~~ traces_to_north_star: no — The plan explicitly defers Gemini usage capture to a fast-follow. While multi-model support is desirable for future-proofing, the North Star does not mandate specific backend engines, only that the sessions that do run leave an honest trail. This is a known, documented deferral.
- ~~`topic:eviction-parked-worktree`~~ traces_to_north_star: no — Implementing a bounded parked-worktree budget and oldest-first eviction logic is entirely unrelated to cost capture or reliable session resume. This is a disk-space management feature smuggled into the plan. Remove it to keep the project strictly focused on the North Star.
