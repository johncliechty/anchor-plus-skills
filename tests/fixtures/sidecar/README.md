# Pinned Claude sidecar fixtures (telemetry-resume W1 — B1 spike)

These are the **canonical, frozen** fixtures for the Honest-Telemetry usage-capture
pipeline. Every later wave (W3 narration enrichment, **W4** the sum-over-message
parser + ledger, W7 the healthcheck walk + drift tripwire) asserts against the
shape and totals pinned here — no wave re-derives the sidecar contract.

## Provenance (honest)

The observed shape is grounded in the **on-host probe recorded in
`planning/telemetry-resume-2026-07/intake/gap-closures.md` → derived-G1
("verified on host, 2026-07-11")**, which inspected the live
`C:\Users\john\.claude\projects\C--dev-Anchor\*.jsonl` store, plus the
structural facts of the Claude Code transcript format. These files are
**hand-authored to that observed shape and fully anonymized** (no real cwd,
branch, prompt/response text, session UUIDs, or request ids) — see the anonymizer
`tools/capture_registry_fixture.py` for the registry-side equivalent. They are
deterministic and stdlib-parseable (`json.loads` per line); they are NOT a raw
dump of a private session. The full spike write-up lives in
`planning/telemetry-resume-2026-07/W1-GROUND-TRUTH.md` §1.

## Observed shape (derived-G1)

- Claude Code writes **one JSONL transcript per session** at
  `~/.claude/projects/<project-dir-slug>/<session-uuid>.jsonl`. The slug is derived
  from the session cwd (e.g. `C--dev-Anchor`); **the filename IS the engine session
  UUID**, and every record repeats it in `sessionId`. Deterministic correlation:
  `claude --session-id <uuid>` pins the filename **at launch** (no mtime/cwd-window
  guessing for new sessions — this is the W4 UUID-at-launch capture seam).
- Each **assistant** record carries a real `message.usage` block:
  `{"input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
  "output_tokens", "service_tier"}`.
- Records are ISO-8601 `timestamp`-ed → wall-clock duration is directly measurable
  (first record → last record).
- **Per-message records carry NO `total_cost_usd` / `duration_ms`** — those exist
  only in one-shot `-p` RESULT envelopes (the `job_runner` path). On the interactive
  PTY path, **tokens + time are the measured facts; `$` is unmeasured** unless the
  engine self-reports `costUSD` (locked: no own pricing table — see the North Star
  amendment, "no-own-pricing-table").

## Load-bearing finding — DEDUP BY `message.id`

A single assistant turn that contains multiple content blocks (e.g. text **and** a
`tool_use`) is written across **more than one JSONL line that share the same
`message.id`, each repeating the identical `usage` block**. `canonical_3turn.jsonl`
encodes this: `msg_01B00000000000000000BB` appears on **two** lines with the same
usage. **The parser MUST dedup usage by `message.id`** (the ledger key is
`(engine_session_uuid, message_uuid/line-hash)`); a naive sum-over-all-lines
double-counts (`EXPECTED.json → naive_undeduped_would_be` pins exactly how much).

## Files

| file | role | expected state |
|------|------|----------------|
| `canonical_3turn.jsonl` | real 3-turn interactive shape: summary line, user/assistant records, per-message usage, a duplicated `message.id` (tool-use turn) | `measured` — deduped totals in `EXPECTED.json` |
| `resumed_segment.jsonl` | a **resume** of the canonical session (new `sessionId`, `summary.leafUuid` → the prior session's last message) — the engine-switch/continue "segment B" | `measured` — summed with A once, keyed by message uuid |
| `corrupted_zero_usage.jsonl` | message lines PRESENT but usage missing / all-zero (CLI schema drift) | `capture-failed` (`zero-usage-despite-message-lines`) — RED, never $0 |
| `corrupted_malformed.jsonl` | a truncated/malformed JSON line that raises on parse | `capture-failed` (`parse-error`) — RED, never $0 |
| `EXPECTED.json` | the exact per-fixture parse results (deduped token sums, duration, states, reasons) the parser/classifier assert against | — |

## Contract these pin (per the locked tripwire severity)

- **PRESENT + parseable + nonzero usage → `measured`** with the deduped totals.
- **ABSENT/pruned** (no file at all) is an expected environmental state →
  `unmeasured (sidecar-pruned)`, healthcheck `report.warn` (NOT reproduced here —
  it is the *absence* of a file).
- **PRESENT but unparseable or zero-usage-despite-message-lines → `capture-failed`**
  (a first-class enum state, visually distinct from measured AND from unmeasured),
  healthcheck `report.check(False)` **RED** — capture never halts the session
  lifecycle and never silently degrades to `$0`/`unmeasured`. The two `corrupted_*`
  fixtures pin this leg.
