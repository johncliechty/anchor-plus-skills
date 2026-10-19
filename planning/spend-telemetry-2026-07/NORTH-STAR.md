# NORTH STAR — Honest Spend Telemetry v2 (LOCKED 2026-07-20)

**Effort folder:** `planning/spend-telemetry-2026-07/` · **Depth:** FULL (user-confirmed) · **Seats:** Heavy, all `claude-fable-5` (user-directed all-Claude; cross-family seat down for agy full-model auth) · **Locked by:** John, 2026-07-20 (shown-in-full via preview pane at the lock ask).

## Statement

Every Anchor surface that shows spend (project rollups, effort metrics, session details) shows REAL, honestly-provenanced numbers — tokens, wall-clock time, and a clearly-labeled subscription-equivalent dollar estimate — for EVERY class of run session (trio lanes, general/interactive, swarm), with historical worktree sessions recovered by a NO-GUESS backfill, and with the capture substrate hardened so that a hermetic context can never again permanently poison a real session's record. Discovered/brownfield efforts continue to contribute exactly 0 — nothing is ever fabricated.

## Success criteria

1. **Swarm spend visible going forward.** Swarm launches pin `--session-id`; finalize fires from both the owning orchestrator (where wired) and the reconcile-dead transition, arbitrated by the finalize-once CAS. A new fleet run produces measured records for its sub-agent sessions.
2. **Interactive spend surfaces.** The rollup reports trio lanes and general/interactive as SEPARATE figures; both render on the dashboard and project window. `__doctor__` is excluded from every surface.
3. **The latch cannot be burned hermetically.** A finalize attempted in a hermetic context (pytest / healthcheck / redirected data dir) SKIPS without consuming the finalize-once CAS; a later live finalize can still measure. Regression-tested.
4. **History recovered, honestly labeled.** A one-shot backfill tool correlates historical sessions to sidecars ONLY via the deterministic worktree-dirname embedding (`…anchor-worktrees-<session_id>`), mints records with `usage_state: "measured-backfill"`, never overwrites a live-measured record, and reports an honest per-session outcome list (recovered / no-sidecar / ambiguous-skipped).
5. **Dollars are estimates, labeled.** Token-measured sessions show a subscription-equivalent `$` computed from a maintained pricing table, always rendered with an explicit "est." marker; real envelope dollars (one-shot jobs) remain distinct.
6. **Counting is honest.** Cost-less members (e.g. deliverable-doc pointers with `cost: None`) no longer inflate the rollup's "sessions" count; a session counts only if it contributed a measured record.

## Non-goals

- No live per-message spend streaming or graphs (capture + rollup + display of totals only).
- No retroactive recovery for sessions with neither an engine UUID nor a worktree-dirname correlation — honestly unmeasured forever.
- No change to the discovered-efforts-contribute-0 honesty contract.
- No API-key metering or provider billing integration; the pricing table is a maintained constant, not a live feed.
- No WAL/journal rearchitecture (queued separately).

## Risk taxonomy

- **Concurrency (highest):** the CAS-latch change touches the primitive arbitrating racing end-paths; regression could double-write or deadlock capture. Mitigation: dedicated STUB-GATE tests (hermetic-skip, live-win, race).
- **False attribution:** backfill correlation must be provably deterministic; heuristic matching (mtime, transcript similarity) is FORBIDDEN — ambiguity ⇒ skip + report.
- **Safety adjacency:** swarm lifecycle wiring must not disturb the zombie-hunter live-owner discrimination or the orphan reaper.
- **Estimate drift:** the pricing table will age; the "est." label plus a single maintained constant bounds the harm.
- **Suite-contamination recurrence:** tests/healthcheck touching the real registry was the poison vector; the hermetic-skip fix plus the billing-safety-net conventions get pinned by tests.

## Foresight brief

- Design the record shape so per-effort fleet attribution needs no migration later.
- Pricing table + sidecar-root resolution stay injectable seams (`ANCHOR_SIDECAR_DIR` remains the only hermetic escape); the shareable-distro effort inherits both.
- Run-cost records stay append-only (no in-place mutation beyond the CAS stamp) — WAL-inversion compatible.

## Stage-0 locked decisions (John, 2026-07-20, one-at-a-time with recommendations)

1. **Rollup lanes:** general/interactive spend = SEPARATE line from trio lanes; `__doctor__` excluded everywhere.
2. **Backfill labeling:** distinct provenance `measured-backfill` — counted identically, auditable forever.
3. **$ policy:** labeled subscription-equivalent estimate from a maintained pricing table; real envelope $ distinct.
4. **Swarm finalize ownership:** BOTH eager owner finalize + reconcile-dead catch-all, CAS-arbitrated; swarm launches pin `--session-id`.

## Confirmed intake evidence (investigation 2026-07-18, all OBSERVED)

- 111 registry sessions: 106 swarm (69 no usage state, 37 uncorrelated), 0 ever `measured` in a rollup lane.
- The one measured record (2.76M tok / 445s) sits in `general` — excluded from `ROLLUP_LANES`.
- 3 sessions stamped `sidecar-root-unavailable` by a hermetic-context finalize that consumed the CAS latch (live service env verified clean: no `ANCHOR_DATA_DIR`/`ANCHOR_HEALTHCHECK` in NSSM config).
- 55+ sidecar dirs on disk embed the anchor session id in the munged cwd dirname — the deterministic backfill asset.
- Measured interactive records carry `total_cost_usd: 0.0` (sidecar has no costUSD — the locked honesty rule this effort's decision 3 now refines).
