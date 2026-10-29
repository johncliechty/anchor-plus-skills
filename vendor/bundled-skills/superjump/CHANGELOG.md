# Changelog — Superjump

## 1.0.1 — 2026-09-18 — inherit Jumper ping repair (no seating fork)

- Uses Jumper's retried, longer Gate-3 ping. A dead ping no longer empty-halts:
  leaps still run; candidates are UNJUDGED, never survivors. Dedupe (review-family)
  is skipped when the channel is dead. North Star unchanged: no clock-kill of a
  generating seat; no skip-review survivors.

## 1.0.0 — 2026-09-15

- First shipped engine: Read → parallel Leap → independent Judge as each lands → one dedupe pass.
- Fit Contract from the brief, reweightable ratings, progressive result writes.
- Progress monitor recommends a kill; it never aborts on a clock. Safety timeout 60 minutes, recorded.
- Icon: tiger-in-the-ball with a brighter central light (John's pick of the light variant).
