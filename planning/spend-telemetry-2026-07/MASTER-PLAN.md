# Master Plan — Honest Spend Telemetry v2 (Round-3 re-emission, reconstructed)

> **Round-3 mechanical note:** clean re-emission — ONE North Star copy, ONE copy of each phase, single phase numbering 0–7, launch-surface item 2 restored intact, substantive changelog at the end.
> **Reconstruction note (driving session, 2026-07-20):** the engine's re-emission was corrupted by a `$`-splice in launch-table item 2 that embedded an older draft copy mid-sentence. This file is the mechanical de-interleave: every line comes verbatim from stage1-artifacts/BEST-DRAFT.md; item 2's sentence is restored from the draft's own round-3 changelog wording. No planning content was added or altered.

## North Star (embedded verbatim) — Honest Spend Telemetry v2 (LOCKED 2026-07-20)

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


## Phase overview

Eight phases, numbered 0–7 — Phase 0 is a plan-time pre-task, Phases 1–7 are the build waves — ordered per the wave-ordering foresight (idea 27): the plan-time sidecar snapshot fires immediately (Phase 0), then the finalize-once CAS + hermetic-beacon substrate lands first because every other path consumes it (criterion 3), then the sidecar parser/record-schema/end-time evidence layer, then forward swarm capture through one choke-point launcher (criterion 1), then the pricing engine and two-tier dollar rendering (criterion 5), then the surfaces/honest-counting wave (criteria 2 and 6), and finally the backfill runs LAST against the frozen snapshot with the substrate fully soaked (criterion 4), closing with a live deploy-verification receipt. All 29 integrated ideas and all 16 premortem mitigations are placed in a phase; deferrals are named explicitly, never silently dropped. Discovered/brownfield efforts continue to contribute exactly 0 throughout — no phase touches that contract.

## Phase 0 — Plan-time sidecar snapshot (pre-Stage-2 task, execute NOW)

Serves criterion 4 (history recovered): engine retention pruning between planning and execution would silently destroy the 55+ historical sidecar dirs — the only deterministic backfill asset. Snapshotting at PLAN time (idea 12, mitigation 7) makes later pruning cost zero history. This is a Stage-2 pre-task, not a build wave.

**Near-term specifics:**
- Copy the ENTIRE engine sidecar root — every sidecar project dir, unfiltered — into a new read-only `.anchor/sidecar-archive/` directory, preserving dirnames byte-for-byte (the dirname IS the correlation key). Deliberately OVER-inclusive: the worktree-dirname munging rule is not isolated + regression-tested until Phase 2, and filtering at the only unrepeatable moment with an untested rule risks destroying exactly the history this phase exists to save. Sidecars are JSONL text; the disk cost is bounded and recorded in the manifest.
- Record a manifest (`.anchor/sidecar-archive/MANIFEST.json`): source path, dirname, file count, total bytes, copy timestamp — the audit trail proving the snapshot's provenance.
- Mark the archive read-only with BOTH mechanisms, concretely: `attrib +R` on every file AND an inheritance-stripped `icacls` ACL (`icacls .anchor\sidecar-archive /inheritance:r /grant:r "PUTER\john:(OI)(CI)RX" "SYSTEM:(OI)(CI)RX"`) so the user and the service account can read but nothing writes without an explicit, logged ACL change. Add it to `.gitignore` if not already excluded — it is data, not code.
- Measure the archive at copy time: the manifest records per-dir byte totals + the grand total, and the Phase-0 completion note in the effort folder states the measured grand total — the size becomes an OBSERVED number at execution (intake baseline: 55+ dirs of JSONL text), never an assumption.
- Verify (a read-only grep count, NOT a copy filter) that ≥ the 55 dirs observed at intake (2026-07-18) embedding the `…anchor-worktrees-<session_id>` marker are present in the archive, and log any present-then vs present-now delta honestly in the manifest.
- The Phase 6 backfill tool points at this snapshot exclusively, never the live engine sidecar root — so NO later event (engine retention pruning, interim deploy checkpoints, new sessions) can change what backfill sees. The frozen-snapshot assumption is anchored HERE, at plan time, before any deploy checkpoint exists; interim deploys are structurally incapable of colliding with it.

**Deferred (explicitly):**
- ALL filtering + correlation of the snapshotted sidecars — that is Phase 6, using the Phase-2-tested munging function; this phase only preserves bytes.
- Pruning/retention policy for the archive itself (keep indefinitely for now; revisit post-backfill).

## Phase 1 — Finalize-once CAS + hermetic beacon substrate

Serves criterion 3 (the latch cannot be burned hermetically) and is the primitive every later phase consumes (idea 27) — highest-risk concurrency change gets maximum soak time under the suite. Fixes the observed poison vector: 3 sessions stamped terminal by a hermetic finalize that consumed the CAS.

**Near-term specifics:**
- Reimplement the finalize-once CAS as an exclusive-create (O_CREAT|O_EXCL) claim file named by session_id under `.anchor/run-costs/` (idea 4, mitigation 5): file EXISTENCE is the CAS; NTFS guarantees exactly one winner across threads AND processes; record content is idempotent (same session → same payload) so a double-fire converges, never double-counts.
- Invert the hermetic predicate from blocklist to positive identity (idea 5, mitigation 3): the beacon is BIND-DERIVED, not supervisor-derived — whichever process wins the EXCLUSIVE bind on the real service port (8777, `SO_EXCLUSIVEADDRUSE`) while resolving the REAL un-redirected data dir mints the boot beacon (PID + boot token) at startup. Only a finalize presenting the matching beacon may consume the CAS; any non-beacon context records retryable NON-TERMINAL `usage_state: finalize-deferred` — a later live finalize always may proceed. Because the anchor is the exclusive bind + real data dir, it covers the NSSM service, the documented manual-debug path (`python anchor_gui.py` run by hand on 8777 with the service stopped), AND a non-NSSM distro supervisor identically — no supervisor enumeration to get wrong. The beacon is re-verified at CONSUME time, never trusted from boot: to consume the CAS a finalizer must (a) BE the beacon-minting process this boot (PID + boot-token match against its own in-memory token, not just the file) and (b) still HOLD the live exclusive bind at the moment of claim (re-probed on the listener handle) — so a beacon file orphaned by a crash is inert (the token died with the process), and a process that lost the port between mint and consume defers instead of writing. The redirect-seam list is CLOSED and written down: `ANCHOR_DATA_DIR`, `ANCHOR_SIDECAR_DIR`, `ANCHOR_WORKTREE_BASE`, `ANCHOR_SKILLS_DIR`, `ANCHOR_HEALTHCHECK`, `ANCHOR_PTY_BACKEND=stub`, `ANCHOR_RUNNER_CMD` (stub runner), pytest-detection — ANY active seam forces the deferred path even when the bind test would pass; adding a seam requires updating this list + its parametrized test. Named STUB-GATEs: `test_beacon_stale_file_inert` (crash-orphaned beacon admits nobody), `test_beacon_consume_reverify` (bind lost between mint and consume → deferred, CAS untouched), `test_redirect_seam_forces_deferred` (parametrized over EVERY listed seam).
- **CAS trust model — the single authoritative writer table: every writer, its admission predicate, and the attack on that predicate:**
  1. *Live finalize (any beaconed server: NSSM, manual-debug on 8777, distro supervisor).* Admission: holds the current boot beacon (exclusive real-port bind + real data dir). Attack: a hermetic context cannot mint the beacon — pytest/healthcheck servers bind other ports and/or redirected data dirs, and the exclusive bind guarantees at most one beacon holder at a time. Residual, stated honestly: the predicate is anti-ACCIDENT, not anti-adversary — a malicious local process could copy the beacon file; single-user machine, out of threat model.
  2. *Backfill tool (Phase 6).* Admission: explicit operator invocation with a confirm flag + service-unreachable probe (8777) + refusal under ANY hermetic marker (`ANCHOR_DATA_DIR` redirect, `ANCHOR_HEALTHCHECK`, pytest-detect) + terminal-status sessions only + reads the frozen snapshot only. Attack (the service-down spoof): a hermetic context on a service-down machine passes the probe, so the markers alone would be a blocklist again. Defense in depth beyond markers: (a) the entry point is a standalone operator CLI never imported or invoked by suite/healthcheck code — a conformance test greps for it; (b) the blast radius is structurally bounded — it can ONLY mint `measured-backfill` provenance from snapshot bytes and can NEVER displace an existing record (exclusive-create), so the worst spoofed outcome is an honest-provenance record, not a burned latch or a fabricated number. Override, enumerated: `--force` bypasses ONLY the service-reachable probe — never the hermetic-marker refusal, the terminal-status-only constraint, or the snapshot-only read — and every record minted under it carries `forced: true` + the operator-supplied reason, echoed in the run's outcome list (admission / override / logging all named).
  3. *Warm drain (`pre_restart_drain.py`).* NOT a CAS writer — it parks sessions and persists docs only; finalize for parked/terminal sessions belongs to the next beaconed boot sweep. Declared and tested: a drain run consumes zero claims.
  4. *Manual debug off-port or on a redirected data dir.* No beacon → deferred-capture by construction: records `finalize-deferred`, swept by the next beaconed sweep. Honestly deferred-capture, never silently measured.
  5. *Distro on a host that cannot provide an exclusive bind.* Honestly DEFERRED-capture (same `finalize-deferred` path) until that host's beacon story exists; the shareable-distro effort inherits the seam. No measurement without a beacon, ever.
  6. *Poisoned-record repair script (this phase, one-shot).* Admission: hardcoded allowlist of exactly the 3 intake session ids + a current-state check (`sidecar-root-unavailable`, else loud refusal) + a single-run latch (a second run refuses) + the same hermetic-marker refusal as the backfill CLI. It is the ONLY writer permitted to DELETE a claim file — the single audited append-only exception — with before/after content logged to the effort folder. Attack: an out-of-allowlist id or a re-run — both refused by construction, STUB-GATE-tested.
  **Closure invariant (literal, testable):** rows 1, 2, and 6 are the ONLY claim-file writers (create for 1–2, the audited delete for 6); rows 3–5 are enumerated NON-writers, each pinned by a test (the drain consumes zero claims; off-beacon contexts write only the registry's `finalize-deferred` field, which is not a claim file). A conformance test greps product code for claim-file create/delete call sites under `.anchor/run-costs/` and fails on any site outside the three named entry points (live-finalize module + its sweep, the backfill CLI, the repair CLI). Adding a writer requires a plan amendment + updating that test — the table is CLOSED, and the invariant is literally true OF the table because the test forces the table and the code to coincide.
- Stamp the triggering predicate reason on every deferred/skipped record; surface a `finalize-deferred` count on the rollup; add a healthcheck WARN (yellow per the locked severity rule, never red) when live-registry sessions accumulate deferrals (idea 7, mitigation 4).
- STUB-GATE trio, named tests (idea 6, mitigation 3): (a) hermetic-context finalize skips and the CAS survives, (b) live finalize after a hermetic skip still measures, (c) two racing writers as real separate processes — exactly one claim-create succeeds.
- Append-only invariant test (mitigation 16): a finalized cost file is never rewritten — byte-identical content + stable mtime across a second finalize attempt; the registry record gains only a pointer/state field.
- Hermetic-test conformance (idea 28): the entire telemetry suite runs against temp `ANCHOR_SIDECAR_DIR` + temp data dir; a conformance test asserts no telemetry test ever resolves the REAL sidecar root — pinning the billing-safety-net convention.
- Repair path for the 3 poisoned `sidecar-root-unavailable` records — mechanism NAMED: an audited one-shot repair script gated on a hardcoded allowlist of exactly those 3 session ids (from the 2026-07-18 intake evidence). For each: verify the current state is still `sidecar-root-unavailable` (else refuse loudly), DELETE the burned claim file — the single, audited exception to append-only, with the old record content preserved in the effort folder and a before/after log — then re-stamp `usage_state: finalize-deferred`. Guard + STUB-GATE test: the script refuses any id outside the allowlist and refuses a second run; after repair, the Phase 6 backfill measures them through the normal claim path like any other deferred session.

**Deferred (explicitly):**
- Wiring the beacon check into the actual NSSM deploy verification — named as a Phase 7 checklist item.
- Backfill's use of the identical claim path — Phase 6 (it reuses this primitive verbatim, no new code path).
- WAL/journal rearchitecture — explicitly out of scope (North Star non-goal, queued separately); records stay append-only files, WAL-inversion compatible by design.

## Phase 2 — Evidence layer: sidecar parser fence, munging isolation, end-time derivation, frozen record schema

Serves criteria 1 and 4 indirectly and the foresight brief directly: every measured number flows through the parser and the record shape, so hardening them before any capture path consumes them prevents fabricated zeros, burned latches, and a later migration.

**Near-term specifics:**
- Version-fence the sidecar parser (idea 15, mitigation 2): probe a known field fingerprint (token key shapes, JSONL envelope names) before parsing; mismatch → `usage_state: sidecar-format-unrecognized` — loud, retryable, never a fabricated 0, never a consumed CAS. Pin a CAPTURED REAL sidecar as a test fixture so a `claude` CLI shape change turns a test red.
- Isolate the worktree-dirname munging rule (`…anchor-worktrees-<session_id>` ↔ munged cwd) in ONE function with its own regression test against real observed dirnames from the 55+ population (idea 16, mitigation 2).
- Quiesce check before any sidecar read (idea 17, mitigation 7): mtime stable for N seconds else defer to the next sweep; truncated tail → `usage_state: measured-partial`, never a clean-looking number.
- End-time evidence ladder (idea 19, mitigation 13): last sidecar entry timestamp → last PTY-activity timestamp → reconcile time; reconcile-only → `duration_state: upper-bound` rendered '≤ Nh'. Test the unattended-death path asserting the sidecar timestamp beats a days-late reconcile time.
- Freeze the run-cost record schema NOW (idea 24): `session_id`, `effort_id`/`chain_id` (nullable), `parent_session_id`, `lane`, `model`, per-category token counts (input/output/cache-read/cache-write), provenance/usage state, duration + duration_state — documented in the plan so per-effort fleet rollups later need a query, not a migration.
- CLOSED provenance vocabulary, frozen here: `usage_state` ∈ { `measured`, `measured-backfill`, `measured-partial`, `finalize-deferred`, `id-unverified`, `sidecar-format-unrecognized`, `unmeasured` } and `duration_state` ∈ { `measured`, `upper-bound` }. A conformance test asserts no writer ever emits a value outside these sets; adding a value requires a plan amendment + updating that test, so the vocabulary cannot drift by accretion.

**Deferred (explicitly):**
- Per-effort fleet-attribution ROLLUP/QUERY itself — schema-ready now, query surface deferred to a future effort (named, not silent).
- Multi-engine (Gemini) sidecar formats — the fence will refuse them honestly (`sidecar-format-unrecognized`); Gemini parsing deferred until the cross-family seat returns.

## Phase 3 — Forward swarm + interactive capture (choke-point launch, observed-id readback, decoupled reconcile-finalize)

Serves criterion 1 (swarm spend visible going forward) and the safety-adjacency risk: capture must attach to every future launch without disturbing the zombie-hunter live-owner discrimination the 2026-06-30 fix installed.

**Near-term specifics:**
- ONE choke-point launch helper for every swarm/sub-agent spawn (idea 2, mitigation 6a): mints a fresh UUID, registers the session BEFORE exec, pins `--session-id`, refuses resume-with-pin. Conformance test greps product code for raw spawn calls outside the helper and fails on any hit.
- **Concrete launch-surface table (tabled NOW — nothing left for Stage 2 to enumerate): every known spawner, its pinning mechanism, and its scope:**
  1. `terminal_session.start_session` (trio lanes, general, grass workbench, continue/advance/resume paths) — WIRED this effort: already registers-before-exec; adopts the helper for id-mint + pin.
  2. `job_runner` one-shot lane jobs (`launch_lane`, gate-driven runs) — WIRED: envelope-measured today (real envelope `$` stays distinct per Stage-0 decision 3, plus the pin); gains the pin so its sidecar correlates too.
  3. Gandalf runs, BOTH forms — WIRED: the canonical hidden background skill job (the 2026-07-07 tile path) and the legacy map-reduce shard fan-out (`_map_shards` → job_runner) route through the helper.
  4. `summarizer` runner calls (session/project summaries via `ANCHOR_RUNNER_CMD`) — WIRED via the helper's pin; cheap but numerous, and invisible spend here would quietly understate totals.
  5. **The 5:1 skill-layer swarm dispatch (`agy-dispatch` / foundry-skill sub-agent spawns) — explicitly IN SCOPE for capture; this is the population criterion 1 exists for (106 of the 111 registry sessions are swarm).** Two-tier mechanism: (a) the helper is exposed as a spawn-wrapper contract (an env-provided pin the dispatcher consumes at spawn), and adopting it inside the agy-dispatch skill is a NAMED concrete task of this wave; (b) any skill-layer spawn that bypasses the wrapper (a skill invoking raw `claude`) is caught by the orphan-sidecar sweep below — late-measured `measured-backfill`, never invisible. In-scope means: measured eagerly where wrapped, by sweep otherwise — never silently absent.
- Pin-as-hypothesis (idea 1, mitigation 1): immediately read back the OBSERVED session id from the engine's first stream-json init envelope (or created sidecar path), store `observed_session_id` on the registry record, correlate ALL capture on the observed id; mismatch → `usage_state: id-unverified`, never a silently lost session.
- Launch-time canary STUB-GATE (idea 3): pin an id through the real launch path (stub engine), assert the sidecar lands under it, assert the mismatch path stamps id-unverified.
- Structurally decouple finalize from the zombie-hunter path (idea 18, mitigation 12): reconcile classifies FIRST and completely — STUB GATE asserts classification output is bit-identical with and without finalize wired — then schedules finalize async on the already-terminal set; finalize writes ONLY usage fields, never status/liveness. `tests/test_swarm_zombie_coverage.py` reruns as a REQUIRED gate for this wave.
- Reconcile-dead finalize inherits the Phase 2 quiesce check. The sweep's scope is WIDENED and its owner NAMED: the beaconed service runs the reconcile+finalize sweep at boot AND on a periodic cadence (~30 min), covering (a) reconcile-dead sessions, (b) RETRY of every `finalize-deferred` record — this sweep is the single named owner of deferred retries — and (c) the orphan-sidecar scan. Outage/deploy cadence: every deploy restarts the service, so each deploy checkpoint triggers a boot sweep; after a long outage the first boot sweep catches up before engine pruning windows matter (idea 17). Unattended-remeasure STUB GATE: a record deferred in a hermetic context is measured by the next live sweep with NO human action. Race hygiene: the widened sweep and an eager owner finalize CAN meet on the same session — both go through the identical exclusive-create claim with idempotent content, so exactly one wins and the numbers converge; a STUB-GATE race test pins this specific sweep-vs-eager pairing. **Single-owner matrix + terminality:** each record class has exactly ONE owner — pre-snapshot terminal sessions → the Phase-6 backfill CLI (one-shot); post-snapshot deferred / orphan-sidecar / reconcile-dead → THIS sweep; live session endings → the eager owner finalize (with the sweep as the CAS-arbitrated catch-all). A `finalize-deferred` record is retried ONLY by the sweep, and it terminates honestly rather than deferring forever: when its sidecar is absent from both the live root and the Phase-0 archive after `DEFER_RETRY_MAX` sweeps (default 20 — roughly 10h of cadence plus boot sweeps), the sweep transitions it ONCE to `usage_state: unmeasured` with the exhaustion reason stamped — terminal, never retried again, never a silent zero; only the audited repair path may ever revisit it. STUB-GATE: `test_deferred_terminality` (exhaustion → exactly one terminal `unmeasured` transition with reason; a later sidecar appearance does not silently resurrect it).
- Forward orphan-sidecar sweep (idea 23, mitigation 6b): periodic + on-demand — sidecars whose dirname embeds a valid session marker but has no registry row get honest `measured-backfill` records going forward via the Phase-2 munging function and the Phase-1 claim path verbatim; an unregistered launch degrades to late-measured, never invisible.
- **Concrete walk-through — one UNWRAPPED shared-cwd sub-agent, end to end:** an orchestrator session S (worktree cwd `…anchor-worktrees-S`) spawns raw `claude` with the SAME cwd, bypassing the choke-point helper. The engine writes the sub-agent's sidecar as a NEW `<engine-uuid>.jsonl` FILE inside S's EXISTING munged sidecar dir — the dirname correlates to S, but the file's uuid matches neither S's `observed_session_id` nor any registry row. Mechanism: the sweep correlates per-FILE, not per-DIR — for each session file in a correlated dir, a uuid in the known observed-id set is that session's own record; an unknown uuid mints a SEPARATE child record (`session_id: sidecar:<engine-uuid>`, `parent_session_id: S`, S's lane + project, `usage_state: measured-backfill`). So the unwrapped spawn's tokens land as a child row attributed to S's effort — NEVER folded into S's own counts (S's numbers remain exactly S's own sidecar file: no inflation, no loss) and never invisible; rollups sum child rows into the effort/fleet totals with the backfill provenance visible. STUB-GATE: `test_unwrapped_shared_cwd_subagent` — two session files in one dir → two records, correct parentage, parent's counts unchanged.
- **Interim deploy checkpoint + EARLY general-lane receipt:** at the end of this phase, merge + warm-restart deploy the substrate (CAS/beacon + capture) and produce the first live receipt — run one real general/interactive session to completion and verify a `measured` record with real token counts lands via the beaconed path (a record-level check; the `rnd spend` surface arrives in Phase 5). This pulls the general-lane proof forward instead of letting everything ride to the final ship wave. NO collision with backfill's frozen-snapshot assumption: backfill reads ONLY the Phase-0 archive (snapshotted at plan time, before this checkpoint existed), touches only terminal-status sessions, and its exclusive-create claim can never displace what this checkpoint measures — the checkpoint and the backfill are disjoint by construction.

**Deferred (explicitly):**
- Nothing about WHICH surfaces are wired is deferred — the launch-surface table above is exhaustive over known spawners. Deferred is only: eager IN-PROCESS finalize inside the agy-dispatch skill itself beyond wrapper adoption; until that lands, its sessions are measured by the sweep catch-all per the table's tier (b) — the North Star's 'where wired' clause, made concrete.
- Live per-message spend streaming — North Star non-goal, named here because the capture hooks would be its natural seam; explicitly not built.

## Phase 4 — Pricing engine + two-tier dollar rendering

Serves criterion 5 (dollars are estimates, labeled). Built before the surfaces phase so every surface consumes one shared render helper from day one — a future surface structurally cannot present an estimate as a bill.

**Near-term specifics:**
- Pricing table = one maintained constant module (idea 21, mitigation 15): per-model per-category rates (input/output/cache-read/cache-write) + an `as_of` date rendered beside every 'est.' marker. Unknown model id → 'est. unavailable (unknown model)', NEVER $0. Healthcheck WARN (yellow) when any measured session references a model absent from the table.
- Price ONLY the token categories actually present per model (idea 20, mitigation 9); missing breakdown → degrade the DISPLAY tier to 'est. (coarse)' or tokens-only, never a precise-looking dollar. Fixture-test a cache-read-dominated session and a mixed-model session; assert each estimate stays within a declared error band.
- One shared render helper with two distinct CSS classes / formats (idea 22): `$X.XX est. (as of 2026-07)` for token-derived subscription-equivalents vs the bare real envelope `$` for one-shot jobs — no per-surface string formatting anywhere.
- This resolves the intake contradiction honestly: measured interactive records carrying `total_cost_usd: 0.0` (sidecar has no costUSD) now render a labeled estimate instead of a false $0.

**Deferred (explicitly):**
- Live pricing feed / API-key metering / provider billing integration — North Star non-goal; the table is a maintained constant with a staleness nudge, nothing more.
- Automated table refresh tooling — the healthcheck WARN is the maintenance trigger; a refresh script is named-deferred.

## Phase 5 — Surfaces: additive rollup schema, synthetic predicate, honest counting, CLI mirror, coverage report

Serves criteria 2 (interactive spend as a separate line, __doctor__ excluded everywhere) and 6 (honest counting). Runs after capture + pricing exist so surfaces render real substrate output, not placeholders.

**Near-term specifics:**
- Additive rollup evolution (idea 8, mitigation 10): existing keys keep their old meaning; add `measured_sessions`, `general_tokens`, `general_seconds`, `general_est_usd` alongside. BEFORE the wave starts, grep-enumerate every consumer — effort_view, narration, healthcheck assertions, project-window JS, dashboard rows — and list them as explicit Stage-2 touch-points; healthcheck count assertions become shape assertions.
- General/interactive spend renders as a SEPARATE line from trio lanes on both the dashboard and project window (Stage-0 decision 1); the one known measured record (2.76M tok / 445s in `general`) becomes the first visible receipt.
- One synthetic-session predicate, one module (idea 9, mitigation 14): `is_synthetic_session(record)` driven by an explicit `synthetic=True` registration flag (marker convention, never name-sniffing), consulted by EVERY spend surface; `__doctor__` migrates onto the flag; convention test asserts all surfaces route through the predicate and that registering synthetic without the flag fails loudly.
- Honest counting (idea 10): a session counts iff it contributed a measured record (measured / measured-backfill / measured-partial); cost-less members (deliverable-doc pointers with `cost: None`) are enumerable but never counted; render 'N measured of M total' so the denominator stays visible.
- CLI inspection mirror per the v3–v12 convention (idea 25): `anchor.py rnd spend <pid> [--window]` — measured/total split, per-lane + general lines, usage_state distribution, est.-$ with label; data seam only, no mutation.
- Usage-state coverage report (idea 26), the narration.coverage_report pattern: module function + CLI + healthcheck consumer reporting the fraction of registry sessions measured vs deferred vs unrecognized vs honestly-unmeasurable — premortem #4's 'quietly returns to zeros' becomes a visible ratio.

**Deferred (explicitly):**
- Spend graphs / historical trend charts — display of totals only (North Star non-goal).
- A dedicated 'General' session tile surface (the known general-session-surface gap) — the rollup line lands here; a full tile render surface remains a separate queued effort.

## Phase 6 — Historical backfill (LAST, against the Phase-0 snapshot)

Serves criterion 4 (history recovered, honestly labeled). Deliberately last (idea 27): the CAS, parser fence, munging function, and claim path have soaked under the suite for several waves before history is touched. False attribution is the named risk — heuristic matching is FORBIDDEN.

**Near-term specifics:**
- One-shot backfill tool reading the read-only `.anchor/sidecar-archive/` snapshot exclusively; correlation REQUIRES the FULL session id intact in the sidecar dirname (idea 11, mitigation 8) — containment of the complete id, cross-checked against the complete known-session-id set demanding exactly one full-id containment; truncated/partial embedding → ambiguous-skip BY DEFINITION. Regression test with deliberately long, Windows-truncation-colliding paths.
- Run discipline encoded in the tool (idea 13, mitigation 11), per its row in the Phase-1 CAS trust model: explicit operator invocation with a confirm flag; on start it probes 8777 and REFUSES to run while the service is reachable unless `--force`; refuses under ANY hermetic marker (`ANCHOR_DATA_DIR` redirect, `ANCHOR_HEALTHCHECK`, pytest-detect); its entry point is a standalone CLI never imported or invoked by suite/healthcheck code (conformance-tested); even forced it uses the IDENTICAL exclusive-create claim files as the live path and touches only terminal-status sessions (never RUNNING/IDLE). The service-down spoof is bounded by construction: a hermetic run that slipped every marker could still only mint honest `measured-backfill` records from snapshot bytes — never burn a latch, never displace a live record.
- Records minted with `usage_state: measured-backfill` (Stage-0 decision 2 — counted identically, auditable forever); never overwrites: the exclusive-create claim means an existing live-measured cost file wins BY CONSTRUCTION — no compare-and-decide code path exists to get wrong (idea 14). Test: a second finalize/backfill attempt leaves the original byte-identical, mtime stable.
- Honest per-session outcome list printed every run (recovered / no-sidecar / ambiguous-skipped) so a partial run is auditable and resumable; the intake population (69 no-usage-state + 37 uncorrelated + 3 repaired-deferred) is the target set, reconciled against the coverage report after the run.
- Backfilled records flow through the Phase-2 parser fence and end-time ladder unchanged — a format-unrecognized historical sidecar is reported, never guessed.

**Deferred (explicitly):**
- Sessions with neither an engine UUID nor a worktree-dirname correlation — honestly unmeasured FOREVER (North Star non-goal, restated so it is a decision, not an omission).
- Re-running backfill against the LIVE sidecar root for dirs created after the snapshot — covered going-forward by the Phase-3 orphan sweep, so no second backfill mode is built.

## Phase 7 — Ship: deploy, live receipt, conventions pinned

Serves every criterion's 'actually true in production' clause: the telemetry-resume deploy convention showed merged-not-deployed and vacuous-GREEN are real failure modes here; the live receipt is the counter.

**Near-term specifics:**
- Merge + `restart_anchor.ps1` (warm drain) deploy; then the deploy-verification receipt (idea 29, mitigation 4): (a) the bind-derived beacon predicate passes in the REAL NSSM env — verified once, explicitly, per the checklist — and a spot-check confirms the manual-debug path (service stopped, hand-run server on 8777, real data dir) also mints a beacon, (b) a freshly-finished real session lands `measured` end-to-end, (c) `__doctor__` is absent from every surface, (d) `rnd spend` and the dashboard rollup agree.
- Run the full suite + the swarm-zombie coverage gate + the healthcheck (expect at most yellow WARNs, no red) post-deploy.
- Trigger one small real fleet/swarm run and confirm sub-agent sessions produce measured records (criterion 1's live proof).
- Confirm the backfill outcome list is archived in the effort folder and the coverage-report ratio moved (the before/after receipt for criterion 4).

**Deferred (explicitly):**
- Optional Playwright visual sign-off of the new rollup lines — offered to John post-deploy per the established sign-off pattern, not a merge blocker.
- The WAL-inversion follow-on and shareable-distro inheritance of the pricing/sidecar seams — both named in the foresight brief, both queued efforts, neither touched here.

## Round-3 changelog (substantive, per-finding)

Round 2 returned no numbered substantive findings; its outcome was the Synthesizer's not-lockable lean on DOCUMENT CORRUPTION plus five press directions. Each is answered explicitly — nothing dropped silently:

1. **Corruption (the not-lockable cause) — FIXED.** The full second copy of the document embedded mid-item-2 of the launch-surface table is excised; the double phase numbering ("Phase N — Phase N−1") is collapsed to the single 0–7 scheme every in-text reference already used, so all `Phase-N` references now resolve against the headers; the duplicated bulleted "Success criteria" section is deleted (the North Star's numbered criteria are the single authority); launch-table item 2 is restored intact (`job_runner`: real envelope `$` distinct per Stage-0 decision 3, plus the pin). Exactly ONE North Star copy remains.
2. **CAS writer table as a closed system — STRENGTHENED.** The repair script is now writer row 6 (the only DELETE-capable writer; allowlist + single-run + hermetic-marker gated, before/after logged); the backfill row enumerates `--force` (probe-only bypass, `forced:true` + reason logged); a literal closure invariant distinguishes writers (rows 1, 2, 6) from tested non-writers (rows 3–5) and is pinned by a grep conformance test over claim create/delete sites.
3. **Beacon self-identity — STRENGTHENED.** Consume-time re-verification (in-memory PID + boot-token match AND live-bind re-probe; a crash-orphaned beacon file is inert), plus the written-down CLOSED redirect-seam list, each with named STUB-GATEs (`test_beacon_stale_file_inert`, `test_beacon_consume_reverify`, `test_redirect_seam_forces_deferred`).
4. **Unwrapped shared-cwd sub-agent — ANSWERED CONCRETELY.** A full walk-through shows per-FILE correlation inside a correlated dir: an unknown-uuid session file mints a child record (`sidecar:<uuid>`, `parent_session_id`, `measured-backfill`) — its tokens land on the effort as a child row, never folded into or lost from the parent; STUB-GATE `test_unwrapped_shared_cwd_subagent`.
5. **Single-owner + terminality — ADDED.** An explicit owner matrix (backfill CLI = pre-snapshot terminal; sweep = deferred/orphan/reconcile-dead; eager finalize = live endings) and the deferred→`unmeasured` terminality rule (`DEFER_RETRY_MAX`, one terminal transition, reason stamped, repair-path-only resurrection); STUB-GATE `test_deferred_terminality`.
6. **Snapshot location / ACL / size — SPECIFIED.** `.anchor/sidecar-archive/` with concrete `attrib +R` + inheritance-stripped `icacls` read-only ACL, and the measured byte totals recorded in the manifest + the effort-folder completion note (observed at execution, never assumed).
