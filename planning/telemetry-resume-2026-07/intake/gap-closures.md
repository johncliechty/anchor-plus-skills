# Stage-0 blocking-Gap closures

## derived-G1 — PTY usage capture design question → CLOSED (verified on host, 2026-07-11)

**Probe:** live inspection of `C:\Users\john\.claude\projects\C--dev-Anchor\*.jsonl`.

**Findings (OBSERVED):**
- Claude Code writes ONE JSONL transcript per session at
  `~/.claude/projects/<project-dir-slug>/<session-uuid>.jsonl` — the slug is derived
  from the session cwd (e.g. `C--dev-Anchor`), the filename IS the engine session UUID.
- Each assistant message record carries a real `usage` block:
  `{"input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
    "output_tokens", "server_tool_use": {...}}`.
- Records are timestamped → wall-clock duration is directly measurable.
- Per-message records carry NO `total_cost_usd` / `duration_ms` (those exist only in
  one-shot `-p` result envelopes). $ must be DERIVED from token classes × a price
  table, or surfaced as tokens+time with $ marked "derived"/"unmeasured" — a Stage-1
  design decision under the never-fabricate rule (token counts + timestamps are
  measured facts; a price-table product is a computation, not an estimate — but the
  display semantics must say which it is).
- **Deterministic correlation is available:** `claude --session-id <uuid>` pins the
  sidecar filename at launch — no mtime/cwd-window heuristics needed for NEW sessions.
  (Fallback for engine-switch/legacy: cwd-slug + launch-window, refuse-on-ambiguity.)

**Consequence for planning:** the capture seam = "pin session UUID at launch →
parse the sidecar's usage records (version-tolerant, unknown → honest unmeasured) →
sum token classes + duration → RUN-provenance effort cost block, finalized on every
end path." Gemini parity: unknown (out of scope per nonGoals; honest unmeasured).

## diag-B2 — tile/resume inconsistencies unreproduced → investigation IN FLIGHT

Code-path root-cause investigation (blank large-tile window, context-free blue
restart button, manual orientation) delegated 2026-07-11; results land in
`gap-closures-b2.md`. The lock waits on it per the gate.
