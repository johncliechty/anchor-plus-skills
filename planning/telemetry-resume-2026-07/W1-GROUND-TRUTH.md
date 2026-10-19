# W1 — Ground Truth (sidecar spike · plan-mode verification · narration-floor arithmetic)

> Frozen design inputs for the Honest-Telemetry + Warm-Resume build. Every later
> wave cites THIS doc (and the North Star amendment) rather than re-deriving these
> facts. Serves criteria (1), (4), (5), (6).

Provenance note (honest): the sidecar shape below is grounded in the **on-host
probe recorded in `intake/gap-closures.md` → derived-G1 ("verified on host,
2026-07-11")**, which inspected the live
`C:\Users\john\.claude\projects\C--dev-Anchor\*.jsonl` store, plus the structural
facts of the Claude Code transcript format. The pinned fixtures under
`tests/fixtures/sidecar/` are hand-authored to that observed shape and **fully
anonymized** — they are a faithful, deterministic model of the real contract, not
a raw dump of a private session.

---

## §1 — Sidecar shape (the frozen capture contract)

**Location & naming.** Claude Code writes **one JSONL transcript per session** at
`~/.claude/projects/<project-dir-slug>/<session-uuid>.jsonl`. The slug is derived
from the session cwd (e.g. `C--dev-Anchor`); **the filename IS the engine session
UUID**, and every record repeats it in `sessionId`.

**Deterministic correlation (the W4 UUID-at-launch seam).**
`claude --session-id <uuid>` pins the sidecar filename **at launch** — no
mtime/cwd-window guessing for NEW sessions. Engine-switch / legacy fallback:
cwd-slug + a tight launch window, refuse-on-ambiguity → honest `uncorrelated`.

**Record types (per line, `json.loads`-able):**
- a leading `{"type":"summary", "summary":…, "leafUuid":…}` (present on resumes,
  where `leafUuid` points back at the parent session's last message);
- `{"type":"user", "message":{"role":"user","content":…}, "uuid", "sessionId",
  "timestamp", "cwd", "version", "gitBranch", "parentUuid"}`;
- `{"type":"assistant", "message":{"id":"msg_…","role":"assistant","model":…,
  "content":[…], "usage":{…}}, "uuid", "requestId", "timestamp", "sessionId",
  "parentUuid"}`.

**Usage block (assistant records only):**
`{"input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
"output_tokens", "service_tier"}`. Timestamps are ISO-8601 → wall-clock duration
is directly measurable (first record → last record).

**`$` semantics (locked by this shape).** Per-message records carry **NO
`total_cost_usd` / `duration_ms`** — those exist only in one-shot `-p` RESULT
envelopes (the `job_runner` path). On the interactive PTY path, **tokens + time
are the measured facts; `$` is unmeasured** unless the engine self-reports
`costUSD`. There is **no own pricing table** (North Star amendment: "no-own-pricing-
table"); a session renders `N tok · Xm (subscription)` on the Max host.

**LOAD-BEARING FINDING — dedup by `message.id`.** A single assistant turn that
contains multiple content blocks (e.g. text **and** a `tool_use`) is written
across **more than one JSONL line sharing the same `message.id`, each repeating the
identical `usage` block**. The parser MUST **dedup usage by `message.id`** (the
ledger key is `(engine_session_uuid, message_uuid/line-hash)`); a naive
sum-over-all-lines double-counts. `tests/fixtures/sidecar/canonical_3turn.jsonl`
encodes this (`msg_01B…` appears twice with identical usage), and
`EXPECTED.json → naive_undeduped_would_be` pins exactly how much a non-deduping
parser would over-count.

**Pinned fixtures (`tests/fixtures/sidecar/`, see its README):**
- `canonical_3turn.jsonl` → `measured`; deduped totals in `EXPECTED.json`
  (input 30 · cache_creation 1500 · cache_read 3400 · output 555 · duration 150000ms).
- `resumed_segment.jsonl` → `measured`; a resume of the canonical session (new
  `sessionId`, `summary.leafUuid` → the parent's last message) — the
  engine-switch/continue "segment B". `EXPECTED.json` also pins the combined
  A+B total counted **once** (the W4 switch-engine invariant).
- `corrupted_zero_usage.jsonl` → `capture-failed` (`zero-usage-despite-message-lines`).
- `corrupted_malformed.jsonl` → `capture-failed` (`parse-error`).

The two `corrupted_*` fixtures pin the locked tripwire severity: **PRESENT but
unparseable / zero-usage-despite-message-lines is a CORRECTNESS failure → an atomic
`capture-failed` record (never measured-$0, never silent `unmeasured`), healthcheck
`report.check(False)` RED**. Absent/pruned (no file at all) is the *only*
`unmeasured (sidecar-pruned)` / `report.warn` leg.

---

## §2 — Orientation execution: `permission_mode='plan'` IS enforceable

**Result: ENFORCEABLE on the one-shot job path — the PRIMARY fork branch holds.**
The Layer-2 orientation narration can run as a **read-only plan-mode one-shot job
through `job_runner`** (the same substrate as Gandalf's read-only advisor shards),
never a seeded turn on a live interactive PTY. Verified in code:

- `job_runner._build_claude_argv(..., permission_mode="plan")` emits
  `--permission-mode plan`, the same posture the Gandalf read-only advisor already
  uses so "claude can NEVER edit the analyzed project" (`job_runner.py:352-358`).
- `job_runner._build_gemini_argv(..., permission_mode="plan")` emits `--readonly`
  (`job_runner.py:389-390`), so the Gemini/agy path is likewise sandboxed read-only.
- `build_backend_argv` / `launch(..., permission_mode=…)` thread the mode through
  end-to-end (`job_runner.py:394-437, 521-586`).

**Consequence:** the fork lock's PRIMARY branch — *read-only orientation
auto-executes as a plan-mode one-shot job; ACTION prompts stay v10 paste-NOT-submit*
— is realizable as specified. The lock's fallback (a RICHER Layer-1 render:
transcript-tail + summary, never an unsandboxed auto-executed turn) is **NOT
needed** and is retained only as the documented contingency if a future engine
drops plan-mode.

---

## §3 — Narration-floor cost arithmetic (feeds the locked CHOSEN/CUT ruling)

The narration-floor lock CHOSE lazy on-first-click enrichment through the EXISTING
background summary path, with the deterministic template as the FLOOR, and CUT the
eager batch backfill. The arithmetic that makes the CUT quantitative, not taste:

| path | model spend |
|------|-------------|
| **Eager batch backfill (CUT)** | `(summary-less session count) × (per-summary generation cost)` — paid up front on the ENTIRE summary-less tail, including tiles nobody ever opens. |
| **Lazy enrichment (CHOSEN)** | the SAME per-summary unit cost, paid at most ONCE per session lifetime, and ONLY for tiles actually clicked. A repeat click is a `$0` cache read. The never-opened tail costs `$0` (the deterministic template covers it). |

**Registry measurement (honest, method + caveat).** The exact summary-less count is
an environment fact of John's live `.anchor/` store, which this build agent does
not read live (tests/build are hermetic — the fail-closed seam in W2 is the point).
The number is produced by the W3 **two-number coverage report** run against the real
registry (template coverage — must be 100% — and enrichment coverage %). The
standing arithmetic conclusion does not depend on the exact count: because the
per-summary unit cost is identical between the two paths and lazy pays it only for
the **clicked subset ⊆ the summary-less set**, `lazy_cost ≤ batch_cost` for every
possible registry, with equality only in the degenerate case where every
summary-less tile is eventually clicked exactly once — and even then lazy defers the
spend to the moment of first view instead of paying it eagerly. The prior planning
observation that essentially all managed sessions are summary-less (enrichment
coverage ≈ 0% on the historical tail, since summarize-on-finish predates this
feature for most old sessions) makes the CUT's savings **larger**, not smaller: a
batch backfill would pay the per-summary cost across nearly the whole managed
history, the overwhelming majority of which is never clicked.

**Failure mode (both bars):** a failed/timed-out generation clears the
`summary generating…` badge and leaves the deterministic floor standing — never a
blank pane, never a poisoned cache, never a blocked click (the click path has ZERO
synchronous dependency on the model). This arithmetic + the three-way evaluation in
the North Star amendment ("narration floor") is the standing answer to any future
"why not backfill?" / "why not template-only?" relitigation.
