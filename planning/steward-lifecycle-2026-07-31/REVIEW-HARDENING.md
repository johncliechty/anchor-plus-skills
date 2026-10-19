# REVIEW-HARDENING — adversarial hardening review of the Stage-2 plan set

**Date:** 2026-08-01 · **Target:** `stage2-artifacts/BEST-DRAFT.md` (18 waves) + `wave-decomposition.json` + `hardening-gate-result.json`, against NORTH-STAR v4 (LOCKED), MASTER-PLAN-v2 (Stage-1 approved), INTAKE.md, and the LOCKED UX intent.
**Method:** every load-bearing claim was checked against real code in `C:\dev\Ecgberht\engine\`, `C:\dev\Ecgberht\scripts\`, and `C:\dev\Anchor\*.py` (file:line citations throughout). This review does NOT re-litigate consistency (separate reviewer) and does not resurrect the two REFUTED ideas.
**Note:** the Stage-2 run HALTed human-lockable with the shark tank dry at agreement:1 — `stage2-artifacts/OPEN-FINDINGS.json` holds 8 single-shark BLOCKERs and ~15 MAJORs that are **open, not absorbed**. Where this review confirms one independently it says so briefly and moves on; everything else here is new.

---

## 0. THE TOP FINDING — the two build inputs diverge, and the gate stamped the wrong one

`wave-decomposition.json` (ts `2026-08-01T06:00:10.654Z`) and `BEST-DRAFT.md` (obligations injected at ts `…10.660Z`, same run) are **different plans**:

| In BEST-DRAFT.md (18 waves) | In wave-decomposition.json (17 waves) |
|---|---|
| Wave 2 vertical slice + PRE-SPINE FIXTURE-ONLY rule (module guard, before/after hash) | **absent entirely** |
| Machine-readable `g4-verdict.json`; G4 FAIL = mechanical HALT blocking Waves 10–18 | prose-only G4 "FAIL branch documented as direct-launch fallback" |
| `client_event_id` append-idempotence primitive + double-submit gates (W6/8/9/10/13/15) | **no idempotence anywhere** |
| Named bounds (`ROADMAP_EVENTS_MAX=50000`, `ENVELOPE_MAX_*`, `PORTFOLIO_MAX_ROWS=500`) + refusal paths | **no bounds anywhere** |
| Containment escape tests (`..`/absolute/symlink) in W7/W17 | **absent** |
| A5 field-by-field matrix + capped fix budget; multi-skill proof in W13; commissionable-skills intersection table | absent |
| Attention publish seam table; golden byte-determinism composer (W14); five-state tables W16/17 | old un-hardened wave texts |

Foreman (or any fresh-context builder) handed this folder cannot tell which is authoritative — and if it parses the structured JSON (the natural machine artifact), **every hardening upgrade the Stage-2 rounds produced silently vanishes** while `hardening-gate-result.json` stamps PASS over the prose it will not build. This one defect can undo the entire hardening layer without any wave failing.

**Fix (MUST, trivial):** regenerate the decomposition from BEST-DRAFT (18 waves, all obligations), or delete it and declare BEST-DRAFT the sole input in the handoff; add a mechanical check that wave count + titles match across the two.

---

## A. PROPERTY ASSERTED, NO GATE EMITTED — wave by wave

The plan is unusually gate-rich; the findings below are where an assertion still outruns its gate. Code citations show why each gap is live, not theoretical.

**Wave 1**
- *"hammer on the TARGET box (Windows, scanner + sync running)"* — nothing gates that the scanner/sync were actually active during the run. An idle-box green satisfies the done-when. Gate: the hammer records machine + concurrent-load evidence in its artifact, or drops the environmental claim.
- *"FAIL → SQLite WAL, not a hardened file"* — an architecture swap authorized inside a ground-truth wave with no decision record, no schema, no second-path test matrix (confirms open finding `backend-fail-fork-hammer-storage`). Also collides with the ecosystem's stdlib-only / no-native-deps posture. Gate: FAIL = HALT for a storage decision.
- *A3 fix keys staleness on "roadmap event **count** + Face version"* — count is a weak key: `healRoadmap`, any repair path, or a same-count replace serves STALE as fresh. This repeats the exact defect being fixed — the live key already uses lengths, not content (`brief.mjs:936-939` compares `instruments_length`/`receipts_length`), so a receipt *mutated in place* is invisible today and a roadmap *healed in place* will be invisible tomorrow. Gate: key on last event **seq/hash**, and the regression test must include a count-preserving mutation.
- The brief cache write itself is non-atomic (`writeBriefCache` uses bare `fs.writeFileSync`, `brief.mjs:902`, despite importing `writeFileAtomicSync`) — harmless-ish (corrupt cache reads as absent, `brief.mjs:910-924`) but Wave 1's durability law never lists which stores it covers. See the store inventory gap under the gate-verdict below.

**Wave 3 (audits)** — *"DERIVED ingest is actually firing on live writes"* will be found FALSE: the durable/indexed write path is **dead code in production**. `appendRoadmapEventDurable` (`roadmap.mjs:791`), `appendStripReceiptDurable` / `appendStripInstrumentDurable` (`write-authority.mjs:327/:348`) have zero non-test callers; every live steward verb persists via bare `writeProjectRoadmap`/`writeFileAtomicSync` with no lock (`job-lifecycle.mjs:929-944`, `roadmap.mjs:1000/:1139`). Rewiring every verb onto the durable ingest path is Wave-6-scale work, not a "fix item" — the 6-item/2-wave A5 cap will blow on day one and HALT. The plan asserts the audit outcome is open; the code says it is already decided. Gate: pre-decide this known outcome now (fold verb-migration into Wave 6 scope) instead of a scripted HALT surprise.

**Wave 4 (BUILD-E / G4)** — the classic stub-passes-the-gate defect, twice:
- *PASS = "observed pid + returned handback"* — nothing requires the pid to belong to a **trio CLI** process or the handback to pass `receipt-validate`. A 10-line launcher spawning `node -e "setTimeout(…)"` and writing a canned JSON satisfies every stated criterion. Gate: PASS additionally requires (a) captured child argv/cmdline naming the trio entry, (b) the returned handback passing `receipt-validate.mjs`, (c) run identity as `(pid, proc_create_time)` — the record already carries it (`job_runner.py:683-687`) but `_pid_alive` checks pid only (`job_runner.py:1249-1259`), a real PID-reuse hazard on Windows.
- *"the executor polls its lane"* — there is **no lease/heartbeat anywhere in job_runner** (verified); liveness is a per-probe `tasklist` spawn. "Launched-then-died" as a named state has no substrate until some wave BUILDS lease emission — no wave owns it (Wave 12 *reads* "lease/pid/lane" as if leases exist).
- The executor failure table is missing the refusals the substrate actually throws: `LaneBusyError`, spawn-cap-reached, folder-build-lock (`job_runner.py:1672-1697`).
- The gated-lane continuation path is self-described in code as **"inherently FRAGILE … best-effort continuation, not guaranteed"** (`job_runner.py:574-578`). Crucible and Foreman are the gated lanes. G5's HALT classification must absorb this documented fragility, or G4-PASS-on-Foreman overstates the substrate.

**Wave 5** — *"median + p90 $"* over ≥20 real compiles: production seats are **subscription CLIs** (INTAKE invariant 4) with no per-token billing; dollars are synthetic unless a named deterministic cost model (tokens × rate table) is a deliverable. Without it the calibration record and every later envelope debit is unfalsifiable. G6 is also pre-decided by code: `ANCHOR_TOKEN` is a bare shared secret, constant-time-compared, no subject/expiry/claims (`paths.py:384-446`) — record `who = unattributed(shared_secret)` now; the "investigation" has one possible outcome.

**Wave 6 (spine)** — the biggest gap between claim and gate:
- *Storage reality:* `roadmap_events` is an **array inside `roadmap.json`, rewritten whole** (`writeProjectRoadmap` → `writeFileAtomicSync` of the full container, `roadmap.mjs:689-693`). "Append-only" is enforced only by validation (`mutateRoadmapProjectionInPlace` refuses, `:628-634`) — the exact pattern the hardening law forbids, and `durable-write.mjs:19` says so itself: *"A module that VALIDATES append-only does not PROVIDE it."*
- *Process topology:* every Anchor call spawns a fresh Node bridge (`anchor_gui.py:10381-10388/:10494-10501`) with `subprocess.run(timeout=20/30)` — the platform **kills writers mid-flight by design** on timeout. Concurrent bridge invocations doing unlocked read-modify-write are lost-update, today. The Wave-6 concurrency test therefore must use separate OS **processes** (not workers in one process) and must include a **kill-the-writer-mid-append** crash test; neither is stated.
- *Lock:* a cross-process lock exists (`withFileLock`, O_EXCL, `durable-write.mjs:191`, with `updateJsonSync`) but is used **only** by the portfolio/index layer — no steward write takes any lock. Wave 6 never names the lock mechanism (open finding `check-ci-second-theater-writer` concurs on the static check; this adds: the lock itself is unnamed).
- *Existing second writers must be enumerated and retired by name*, or the shipped code remains a second writer the day the spine lands: `job-lifecycle.mjs:283/:637/:715`, `packet-view.mjs:304` (reached from the live `high-seat-bridge.mjs --decide` path, which imports `writeProjectRoadmap` directly, `scripts/high-seat-bridge.mjs:41,237`, and is spawned by `anchor_gui.py:10495`), `roadmap.mjs:979/:1126`, `pe-gate.mjs:443`. The CI grep must span **both repos including Python and the bridge scripts**.
- *"no chat-turn persistence" CI check* — detector unspecified; without the Master Plan's versioned event-kind allow-list (dropped from Stage 2) there is nothing mechanical to distinguish a chat turn from a typed event.

**Wave 9** — envelope debits in $ (needs the Wave-5 cost model); `ENVELOPE_TTL_MINUTES` under wall-clock skew ungated (W14 handles skew, W9/W12 don't); the envelope ledger is a new durable store with no named atomic-write/lock/concurrency obligation (see gate-verdict).

**Waves 11/14 — trivially satisfiable gates:** W11's "targeted questions derived from Oranges annotations" is passed by echoing annotation text; W14's no-re-ask guard is passed by a composer that asks nothing. Gate: W11 questions must name the missing predicate element; W14 must also assert the brief *proposes a next step* (it does, in the done-when — bind the two in one test).

**Wave 13 — the unowned overnight ingest.** "A validated handback arriving overnight" assumes something is alive to ingest it. Completion detection in Anchor is **exclusively a live stdout reader thread + exit code** (`_reader_loop`/`_finalize`, `job_runner.py:734/:982`) — there is no durable completion-marker protocol. Worse: children are attached to a Job Object with **KILL_ON_JOB_CLOSE** (`job_runner.py:659-666`), so an `nssm restart anchor` mid-commission kills the run unless opted out — and if opted out, the orphan's handback is never captured because the reader died with the service. No wave owns "Anchor restarts mid-commission." This is the failure Wave 18's kill-everything leg will hit *last*; it must be designed *first* (executor contract, Wave 4) — see B.2.

**Wave 15** — publish trigger unowned (confirms open findings); additionally, the index-delivery seam is an **in-process ES-module function** (`ingestAck`, `anchor-contract.mjs:395`) with no CLI/bridge exposure, and the contract file itself records `C7B_STATUS.open: true` — the acknowledging side "ships from another repo." That other repo is this effort; A5's ANSWERED/NEEDS-WIRE probe should expect NEEDS-WIRE plus a bridge deliverable, not a wiring afterthought.

**Wave 16** — see §E. Also: `write_authority:'none'` is today a **declared string field, not enforcement** (`high-seat.mjs:752`; contrast `indexOnlyFs`, which actually throws, `query.mjs:392-422`). The byte-identity test is the real gate — keep it, and reuse the `indexOnlyFs` facade pattern as the fold's read trap.

**Wave 17** — hardening law #4 (poller visibility gating + failure backoff) is met **nowhere** for the new chamber surfaces. Verified: the only visibility-gated, backoff-equipped poll in Anchor is `static/high-seat.js:485-528` (90s min, ×2^fails to 15 min, `document.hidden` skip); **none** of the inline `anchor_gui.py` `setInterval` loops are gated. New chamber pollers must be required to adopt that pattern by name.

**Cross-cutting, no gate anywhere — hardening law #3 (delimiter guards):** project roots cross the process boundary as a `';'`-joined argv string (`_ECGBERHT_ROOT_DELIM`, `anchor_gui.py:10542`; `high-seat-bridge.mjs:24`). The Python side *drops* semicolon-containing folders (reported as `skipped_roots`) — which is a **silently-shorter-portfolio** shape, criterion 13's forbidden failure, unless skipped roots render as `unknown` rows. Also the bridge protocol is "last stdout line is JSON" — one stray `console.log` in the engine corrupts every caller; no stdout-purity test exists.

### Verdict on `hardening-gate-result.json`

**PASS on form, not substance — and stamped on the wrong artifact.** The gate is a regex detector: each of the five property classes was matched by a keyword (`/crash[- ]safe/i`, `/honest(ly)?[- ]unknown/i`, `/exactly once/i`, `/bounded/i`, `/traversal/i`) and the injected obligations checklist satisfied "a gate is emitted." Three reasons the PASS is not earned as a verdict:
1. It graded the **prose** while the machine decomposition Foreman may consume carries **none** of the obligations (§0).
2. It counts **per property class, not per claim instance**. Durability obligations exist for `roadmap_events` — but the plan mints at least seven more durable stores (`commissionable-skills.json` with its two writers, `g4-verdict.json`, the envelope ledger, the queued-reflection store, the quarantine store, the fix-item ledger, the attention cell) and **none** carries a named atomic-write/lock/concurrency obligation. 5/5 properties "gated" while most new stores are ungated.
3. The checkboxes are unchecked and unmapped to test IDs (the open `command-missing-ownership-test` finding), so nothing later forces them true.

Credit where due: the obligation-map table (checkbox → owning wave → deliverable → done-when) in BEST-DRAFT is real and better than most plans ever emit. The gate's PASS records that the document contains it — not that the assertions above are covered. The gaps in this section stand under the PASS.

---

## B. WHAT BREAKS IN THE BUILD — concrete failure modes

1. **Foreman builds the un-hardened plan** (§0). Guard: regenerate/remove the stale decomposition; assert equivalence mechanically.

2. **Anchor restart kills or orphans commissioned runs; handbacks are stdout-tethered** (Waves 4/12/13/18). KILL_ON_JOB_CLOSE murders the run on `nssm restart`; opting out orphans it with no reader to capture completion (`job_runner.py:659-666, :734, :982`). Cheapest guard: the executor contract (Wave 4) mandates a **durable handback file protocol** (run writes handback + terminal marker to a known path; boot-time reconcile finalizes from disk) and explicitly decides `kill_on_job_close` for commissions; Wave 14's kill-everything test then seeds this case deliberately.

3. **Cross-repo build with a single test-command.** The plan lives in the Anchor repo; `test-command: node scripts/run-all-tests.mjs` resolves only at `C:\dev\Ecgberht` (verified: `C:\dev\Ecgberht\scripts\run-all-tests.mjs` exists; Anchor has no `scripts/`); Wave 4 is Python/pytest in Anchor; the CI diff guard fences trees in both repos. Foreman's worktree/branch/commit hygiene covers one root. Guard: a build-contract preamble naming the build root, how the runner reaches pytest cross-repo, and which repo each wave commits to.

4. **Lost updates on `roadmap.json` under the real process topology.** Whole-file rewrite + no lock + per-call Node spawns + `subprocess.run` timeout kills (§A Wave 6). Guard: route steward writes through the existing `withFileLock`/`updateJsonSync` (or the dead-code durable path), and prove with a two-OS-process hammer plus a kill-mid-write test.

5. **Windows rename sharing-violations.** Only `session_registry.py:539-559` and `freeze_state.py:219-238` carry the bounded `PermissionError` retry; `job_runner`, `gate_adapter`, `effort_history`, `deliverables` use bare `os.replace`. A new executor writing dossiers under concurrent GUI reads + AV scan is a fresh instance of the exact observed race. Guard: reuse the `_atomic_replace` retry pattern in all new Python writers (and note the Node side already retries, `durable-write.mjs:71` — though it never fsyncs the **directory**, `:87`, so rename durability across power loss is unproven).

6. **Process-spawn multiplication.** `_pid_alive` shells `tasklist` per probe (`job_runner.py:1249-1259`); every Ecgberht endpoint spawns Node synchronously on the HTTP handler thread for up to 20–30 s (`anchor_gui.py:10381/:10494`). A steward loop that polls commission status via these paths multiplies both — the zombie-hunter-storm shape. Guard: batch liveness probes; cache bridge results with a TTL ≥ the poll interval; never poll `_holder_is_active` per render.

7. **Second-writer collision with shipped code.** Eight `/api/ecgberht/*` routes, both bridges, the badge element, and the gated poll loop are **already live** (`route_table.py:239-261`, `anchor_gui.py:10360-10701`, `static/high-seat.js`). Waves 15–17 that "build" these surfaces greenfield will collide with existing routes, the route-audit test, and `tests/test_rearch_2026_07.py`. Guard: scope those waves as modify/extend of named existing files; new endpoints must ship `route_table.py` rows (default-deny gate: the `open` set must equal `OPEN_ROUTES.json` or the build fails).

8. **Auth-off green by fallback.** With `ANCHOR_TOKEN` unset and the pillar flag not in `enforce`, `auth_ok()` returns **True** (`paths.py:408-416`) — a suite can run "auth-ON" with auth silently disabled. Guard (Wave 1): the suite asserts `expected_token()` is non-None and FLAG_AUTH=enforce before any test counts.

9. **PID reuse** (Windows recycles PIDs aggressively): liveness by pid alone can mark a stranger's process as our run. Guard: `(pid, proc_create_time)` everywhere liveness is decided.

10. **Clock skew / TTLs:** envelope TTL and lease expiry are wall-clock; only Wave 14 tests skew. Guard: monotonic-or-seq-anchored TTL checks, skew test in W9/W12.

11. **Path length:** worktree + `.anchor/projects/<id>/planning/` + bundle artifact names can cross MAX_PATH; git and stdlib behave differently with/without longpaths. Guard: one long-path test in Wave 7's containment suite.

---

## C. FOREMAN-READINESS

- **Input ambiguity is disqualifying until §0 is fixed.**
- **DAG:** `Depends on:` is declared machine-checkable but under-specified (concur with open finding `dag-depends-incomplete` — W9→W5 calibration, W10→W4/W5/W7 artifacts, W13→W4/W5, lane joins). Foreman will either serialize everything (safe, slow) or parallelize into missing substrate.
- **Real-run tests poison the standing suite.** Waves 4, 13, 18 require REAL trio runs (minutes–hours, real spend). If they land in `run-all-tests.mjs`, every subsequent wave's gate re-runs them — Foreman's EXECUTE→REVIEW→FIX loop re-runs gates repeatedly. Guard: real-run tests are wave-local gate scripts, excluded from the standing suite, with a named cheap commission profile (e.g. a LITE research run) for repeatability.
- **Wave size:** Wave 6 is already large; once the §A Wave-3 finding lands (verb migration onto the durable path is Wave-6 work), it is plausibly >1 fresh context. Wave 16 similarly (fold + glance view + coverage binding + degraded path + bounds + latency + containment + rewiring the existing endpoint). Pre-split or flag both as multi-sub-agent waves.
- **Stub-satisfiable gates** (the "refusal string proves the beat" class): G4 pid/handback (§A W4 — worst offender), W11 question derivation, W14 no-re-ask, W6 chat-turn detector. Each needs its named anti-stub assertion.
- **Done-when machine-checkability** is otherwise good — most waves bind to tests. Exceptions: W5's "justified against p90 in a checked-in note" (prose judgement; make it a numeric relation the test checks) and W18's DEGRADED-yet-green tension (open finding; John should pre-decide whether DEGRADED can pass the kill gate).
- **Token provisioning in CI** is unstated: who mints `ANCHOR_TOKEN` for the auth-ON suite on a fresh box/worktree?

## D. SEQUENCING RISK

- The kill gate is genuinely last (Wave 18) — but the plan's early de-risk instinct (W2 slice, W4 G4) is right and real. The remaining hole: **SC6 feasibility (≥2 commissionable skills) is knowable at W4+W5 and not asserted until W13/W18** (concur with the Contrarian BLOCKER). Cheapest fix: a one-line feasibility checkpoint after W5 — `count(commissionable) ≥ 2` or HALT — before Waves 6–12 spend the bulk of the build.
- **Real-money spends before the spend law exists:** W4's real trio run and W5's ≥20 compiles occur before the envelope (W9). State explicitly in the plan that Stage-2 approval itself authorizes these named budgets, or the builder violates the invariant it is building.
- W1's SQLite branch and W5's G2-FAIL scope injection into W17 both mutate later waves from inside early ones (open findings; concur — both should HALT instead).
- Predicted early FAILs that invalidate the schedule as written: A5's DERIVED-ingest probe (§A W3, predetermined FAIL beyond the cap) — pre-deciding it converts a scripted Wave-3 HALT into planned Wave-6 scope.

## E. THE AMBIENT-COST TRAP — bounded on paper, not in the waves

Verified current shape: the badge poll is `GET /api/ecgberht/high_seat_badge` → **spawn `node scripts/high-seat-bridge.mjs --roots <all roots> --badge`** (`anchor_gui.py:10599-10617, :10483`) → `verbStatus({roots})` → `discoverStrips` **filesystem walk of every root + one subdir level** plus a per-project `loadBriefCache` read (`high-seat.mjs:681-686, :654`; `verb-bodies.mjs:451`). Fully O(portfolio) per poll, one fresh Node process per poll, synchronous on a handler thread — exactly the `GET /` O(everything)-per-render shape that broke Anchor in June.

Two things the plan must absorb:
1. **The client side is already hardened and must not be regressed:** `static/high-seat.js:485-528` ships the min-90s interval, `document.hidden` skip, geometric backoff to 15 min, `pagehide` cleanup — its own comment names the node-spawn-storm hazard. A Wave-16 rebuild that loses this is a regression; and "badge within one poll" is unfalsifiable until the test imports **that** constant (and defines whether "one poll" means 90 s or the backed-off 15 min — under backoff, `needs_you` can legally take 15 minutes to surface, which John should sign off on or the backoff ceiling must shrink).
2. **The server side is the unbounded half and Wave 16 owns it without saying so.** Wave 16 asserts index-only cost but emits no gate binding the **badge path specifically**: required deliverables — (a) the badge answered from the portfolio-index read (`query.mjs`) behind an `indexOnlyFs`-style trap that throws on any project-root read, with a files-opened bound asserted; (b) the existing `--badge` bridge path and `assembleHighSeat`'s `discoverStrips` walk **retired or rewired by name** (otherwise both paths coexist and the walk keeps running); (c) semicolon-skipped roots rendered as `unknown` rows, never dropped (criterion 13); (d) per-poll process spawn either eliminated (badge served from a cached cell the ingest path updates) or explicitly bounded to one short-lived process per interval.

**Wave 16 is the wave that must bound this. As drafted it asserts the bound and gates the fold, not the badge.**

## F. HARDENING OPTIONS — ranked

### MUST-FIX-BEFORE-BUILD
1. **Single authoritative build input** — regenerate `wave-decomposition.json` from BEST-DRAFT (or delete + declare); add a wave-count/title equivalence check. *Cost: small. Buys: the entire hardening layer actually gets built.*
2. **Wave 4 anti-stub G4 + restart-safe handback contract** — PASS requires trio-CLI cmdline evidence + `receipt-validate` pass + `(pid, create_time)` identity; executor contract adds the durable handback/terminal-marker file protocol, decides `kill_on_job_close`, and adds LaneBusy/spawn-cap/build-lock refusal states. *Cost: medium. Buys: G4 means what it claims; overnight/restart handbacks become possible at all.*
3. **Wave 6 scope truth** — name the cross-process lock (`withFileLock` exists), enumerate + migrate/retire the seven live writer call sites incl. `high-seat-bridge --decide`, CI grep both repos + Python + scripts, concurrency test with separate OS processes + kill-writer-mid-append, and state the whole-file-rewrite reality (move to a true append log or gate lost-update explicitly). *Cost: medium (it is the honest size of the wave). Buys: criterion 10 is true in the shipped topology, not in a lab.*
4. **Wave 16 ambient gates** (§E a–d) + poll-constant-bound latency test + preserve `high-seat.js` gating. *Cost: small-medium. Buys: criterion 12/13 without re-importing the June regression.*
5. **Wave 1 auth substrate gate** — assert `expected_token()` non-None + FLAG_AUTH=enforce inside the suite (closes the `paths.py:408-416` silent-auth-off fallback); pre-record G6's only possible outcome. *Cost: small. Buys: "auth-ON green" cannot be vacuous.*
6. **Cross-repo build contract** — build root, cross-repo test runner (Node + pytest), per-wave commit repo, `route_table.py` rows + `OPEN_ROUTES.json` as named deliverables for every new endpoint. *Cost: small. Buys: Foreman can execute at all without inventing it.*
7. **Boot-ingest ordering** — one named open-project pipeline (reconcile → ingest pending handbacks → publishAttention → compose brief), owned by a wave, kill-between-stages tested (also resolves the open reconcile-before-compose and publish-trigger BLOCKERs). *Cost: small to specify. Buys: criteria 8/11/12 coherent after kills.*
8. **Pre-decide the A5 DERIVED-ingest outcome** — fold verb migration into Wave 6; don't script a HALT for a fact the code already states. *Cost: zero (a plan edit). Buys: no dead-stop at Wave 3.*

### WORTH-DOING
9. Staleness key = last event seq/hash, not counts (A3 and the existing Strip-length key). *Small.*
10. Named cost model for $ debits/calibration on subscription seats. *Small.*
11. SC6 feasibility checkpoint after W5 (`count(commissionable) ≥ 2` or HALT). *Small.*
12. `commissionable-skills.json` regenerated from two pure inputs by one function (kills its dual-writer shape; concurs with open finding). *Small.*
13. Content-hash-bound confirms (TOCTOU; concurs with the Analyst BLOCKER — confirm payload carries the proposal hash). *Medium.*
14. Real-run tests marked gate-only, cheap commission profile named. *Small.*
15. `(pid, proc_create_time)` liveness everywhere; batch `tasklist` probes. *Small.*
16. Stdout-purity test on both bridges (one JSON line, nothing else) + `bridge_bad_json` mapped into each surface's dependency-returns-garbage row. *Small.*
17. Add every new durable store (envelope ledger, queue, quarantine, verdicts, skills table) to the typed allow-list with the durability triple. *Small-medium.*
18. W17 pollers required to adopt the `high-seat.js` gating pattern by name. *Small.*

### NICE-TO-HAVE
19. Single append-only `artifacts/degraded.json` ledger (concurs with NIT).
20. Directory fsync after rename in `durable-write.mjs` (crash-across-power-loss durability of the rename itself).
21. Long-path (MAX_PATH) test in Wave 7; clock-skew tests for envelope/lease TTLs; delimiter round-trip test for `';'` roots.
22. Atomic `writeBriefCache` (use the helper the module already imports).

---
*Review by the adversarial-hardening pass, 2026-08-01. Code evidence: `C:\dev\Ecgberht\engine\{brief,roadmap,job-lifecycle,durable-write,high-seat,stand-up,pe-gate,write-authority}.mjs`, `engine/portfolio/{query,anchor-contract,caps,ingest}.mjs`, `C:\dev\Ecgberht\scripts\high-seat-bridge.mjs`, `C:\dev\Anchor\{anchor_gui,job_runner,terminal_session,lanes,route_table,paths,gate_adapter,session_registry,freeze_state}.py`, `C:\dev\Anchor\static\high-seat.js`.*
