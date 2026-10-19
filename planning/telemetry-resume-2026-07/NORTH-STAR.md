# NORTH STAR — Honest Telemetry + Warm Resume (LOCKED 2026-07-11)

> **Every Anchor session — interactive ConPTY or one-shot job — leaves an honest,
> machine-verified trail of what it cost and what it accomplished, so the project
> rollup's numbers mean "measured truth, not zero-by-omission," and clicking ANY
> session tile reliably opens a warm terminal that narrates what was done, what
> was produced, and what comes next.**

Locked by John ("lock", 2026-07-11) after FULL-depth confirmation, the
salvage-vs-rewrite gate (**salvage/extend**), and closure of both Stage-0 blocking
Gaps (see `intake/gap-closures.md`, `intake/gap-closures-b2.md`). Drift detection
active from this point.

## Success criteria (7)

1. **Real PTY usage capture.** A usage-capture seam on the terminal_session path
   (the engine's session JSONL sidecar; `--session-id` pins correlation) produces a
   RUN-provenance effort with a real cost block (tokens/time/$), finalized on every
   end path (finish, kill, close/park, reconcile-dead) — verified by a STUB-GATE
   suite with a pinned sidecar fixture, and one live smoke run whose rollup delta
   matches the sidecar's reported usage.
2. **Honesty contract holds, test-pinned.** discovered/imported still contribute
   exactly 0; uncapturable usage surfaces an explicit **"unmeasured"** state
   distinct from $0.00; no cost is ever estimated, interpolated, or fabricated —
   existing v4 rollup + v8 persist suites stay green unmodified.
3. **No double-counting.** A session's persisted docs (source=discovered) and its
   RUN cost record coexist without inflating the rollup — dedup keyed on
   session_id, proven by a test that does both for one session and asserts the
   cost counts exactly once.
4. **Repro-first tile fixes.** The B2 inconsistencies (blank large-tile window,
   context-free blue restart, manual orientation) are REPRODUCED under Playwright
   against captured registry-state fixtures, THEN fixed; afterward every tile
   class (running, parked-idle, done, failed, discovered) click-opens a non-blank
   session window — Playwright + screenshot sign-off.
5. **Resume narrates and orients.** Clicking a parked/done/discovered tile starts
   a session whose READ-ONLY orientation prompt AUTO-EXECUTES (loads docs/summary;
   prints what was done / accomplished / produced / next steps), while any
   mutating/ACTION prompt remains v10 **paste-NOT-submit**. THE FORK IS RESOLVED
   HERE AND LOCKED; a test pins that no ACTION prompt is ever auto-submitted.
6. **Constraints preserved.** Python stdlib-only (pywinpty exception) passes
   distro.py's scan; tests never touch live :8777 (stub PTY + ANCHOR_RUNNER_CMD +
   fake sidecar fixtures); resume/advance tests follow the v11/v11.1 lessons; the
   daily healthcheck gains a stubbed walk of capture+finalize.
7. **The undercount is measured once.** A before/after comparison on ≥1 real
   project quantifies the missed spend, recorded in the execution log.

## Locked decisions
- Depth: **FULL** (high-stakes forced; confirmed by John).
- **Salvage/extend** — never a lifecycle rewrite.
- Fork: **read-only orientation auto-executes; ACTION prompts stay paste-not-submit.**
- $ semantics: tokens+time are MEASURED; $ is DERIVED from a price table or shown
  "unmeasured" — display semantics finalized in Stage 1 under the never-fabricate rule.

## Non-goals (from framing, held)
No billing/analytics platform · no historical backfill · no honesty-contract
weakening · no Gemini usage parity (honest unmeasured) · no v12 merge (but cost
records keyed session_id + chain_id to survive it) · no board-layout redesign.
