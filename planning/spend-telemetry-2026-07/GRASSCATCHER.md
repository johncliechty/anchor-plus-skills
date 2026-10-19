
## Stage-1 triage — parked (out-of-scope; revisit if the North Star is amended)

- Live per-message spend streaming ticker in the terminal chrome (tokens counting up as the session runs). — Explicit non-goal (capture + totals only); genuinely useful someday, parked honestly.
- Budget alerts / hard spend limits per project (halt a swarm when its est. $ crosses a threshold). — Valuable follow-on once measurement exists, but the North Star scopes display of totals, not enforcement.
- Auto-refresh the pricing table from Anthropic's published pricing page on a schedule. — Explicit non-goal (maintained constant, not a live feed) and violates the no-network posture; the B21 WARN is the sanctioned maintenance path.
- Historical spend trend chart (spend-over-time graph per project on the dashboard). — Non-goal (no graphs); the append-only record shape (B4/B24) makes it buildable later without rework — that's the foresight receipt, not a scope claim.
- Fold run-cost records into the WAL/journal as authoritative events now, ahead of the queued inversion effort. — Explicit non-goal; B4's append-only-file design is deliberately WAL-compatible so the queued effort inherits it cleanly.
- Recover Gemini/agy-side swarm spend from Gemini CLI telemetry files. — The intake evidence and criteria are Claude-sidecar-shaped; Gemini capture is a distinct parser+seam effort. Park it — but B24's record schema should not hardcode Claude-only token category names (note carried into the schema task).
