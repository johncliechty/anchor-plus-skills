# FINDING F — usage tracking: THE NUMBERS ARE ON DISK; THE READERS ARE BLIND

**Headline: the writers work. `usage_capture` has been faithfully recording real
tokens + real wall-clock all along.** Proof on disk:
`.anchor/projects/f69f6d66…/general/efforts/run-cost-a0a0772e….pointer.json` =
`usage_state:"measured"`, **2,757,886 tokens, 444,813 ms**. Its own summary — generated
5 HOURS LATER — says `**Effort:** 0 tokens · 0.0s wall-clock · 0 run(s)`. Same for
`c888d494…` (420,697 tok / 85.7s). Nothing was lost; nothing is being read.

## Paths (writer → store → reader → surface)
- **W1 WORKS**: `usage_capture.finalize_session_usage:386` (via
  `terminal_session._finalize_usage_safe:75` from kill `:2812`, close/park `:3362`,
  drain `:1566`, finish→build `:96`, reconcile-dead `:3857`) → `run-cost-<sid>.pointer.json`.
- **W1b ABSENT READER**: 120s autosave snapshots → `.anchor/usage_ledger/<uuid>.json`;
  **43 populated docs, ZERO UI consumers** (only `combined_totals:319` inside finalize).
- **W2 WORKS RECENTLY**: job_runner stream-json cost → `attach_cost:2073`; the comment at
  `job_runner.py:1044` admits `attach_cost` "had no production caller" before the bridge
  ⇒ older one-shot efforts have no cost block.
- **W2b ABSENT**: jobs with no project_id (summarizer runs, Gandalf shards) burn REAL
  metered $ (`usage_ledger/0a9fc38c….json` = `total_cost_usd: 0.2085`) that reaches nothing.
- **W4 WORKS + HONEST**: `_stamp:627` → registry usage_state → `rollup_honesty.
  project_capture_rate:177` → "measured N/T · K capture-failed" (`anchor_gui.py:2263-2273`).
- **R-f WORKS**: zombie-hunter spend.js → `handle_zombie_spenders:9938/:9981` $/min banner
  — **the only live $ figure in the whole GUI**.
- **BROKEN readers**: summarizer `_aggregate_effort:470` (R-a) · project rollups
  `effort_history:2262/:2192` (R-b/R-d) · dock metrics `effort_view.effort_rollup:541`
  (R-c) · boneyard `:438-452` (R-e).

## Root causes (all proven, not inferred)
- **RC-1 THE DAILY LANE IS EXCLUDED BY DEFINITION.**
  `ROLLUP_LANES = ("research","planning","build","deliverables")` —
  `effort_history.py:2189`, driving `:2293`, `:2204`, `anchor_gui.py:5501`. John's lane is
  **`general`** (also `zombie`, `gandalf`). Every general run-cost record is structurally
  unreachable by every project rollup, forever.
- **RC-2 THE LANE INDEX IS LOSSY AND `list_efforts` IS INDEX-ONLY** (`:217-230`, never
  globs the dir). `general/efforts/` has **17** pointers; `general/index.json` lists
  **13** — missing both `run-cost-*`. `record_effort:198-202` is a read-modify-write
  guarded only by an in-process `threading.RLock` (`paths.py:34`) — **no cross-process
  lock**, so CLI/healthcheck/rebuild_summaries clobber it. (Dashboard's zombie index DOES
  list all three ⇒ write path fine, index lossy.)
- **RC-3 WRONG DICT KEY.** `terminal_session.py:4081-4082` and `:1919-1920` build
  `{"session_id","lane","efforts": …}` but `summarizer.extraction_seed:291` and
  `_aggregate_effort:484` read `session["member_files"]` ⇒ empty members ⇒
  `title ""`, `claims []`, `effort {0,0,0.0,0}`, `no_grounded_claims:true` —
  **byte-for-byte the shape of every zero summary on disk** (this is ALSO the blank-summary
  root cause from FINDINGS-B).
- **RC-4 ID-NAMESPACE MISMATCH.** `summarizer._find_session:985` compares against
  `sessions.list_sessions` ids minted as `run::<job_id>` / `dir::<parent>`
  (`sessions.py:198-215, 285-298`) — never a bare managed session id ⇒ always None for a
  PTY session (kills `terminal_session.py:1571` drain digest).
- **RC-5** run-cost `job_id` = `run-cost-<sid>` ⇒ `_compute_group_key:198` puts it in its
  OWN session, never a member of the doc session.
- **RC-6 ZEROS ARE PERMANENT**: `summarize_session:1177-1181` serves cache; finish hook
  skips when cached (`anchor_gui.py:1736`) ⇒ never self-heals.
- **RC-7 $ IS 0.00 BY LOCKED POLICY, NOT A BUG**: `_cost_block:352` hard-codes
  `total_cost_usd: 0.0`; "No-own-pricing-table" is a LOCKED contract
  (`usage_capture.py:24-27`, `rollup_honesty.py:27-29`). **No per-model pricing table
  exists anywhere in Anchor** — absent, not stale. `(subscription)` is rendered at
  `_fmt_rollup_line:4847`. Real $ only from metered stream-json envelopes and
  zombie-hunter's spend.js.

## Time vs $ — DIFFERENT causes
Wall-clock has the SAME cause as tokens (captured at `_duration_ms:132` /
`_session_wall_clock_ms:528`; 66,629ms / 444,813ms / 15,665,363ms are on disk) — it reads
0 purely from RC-1/2/3. **$ is deliberate policy (RC-7): fixing the readers makes tokens
and seconds real but leaves `$0.00 (subscription)` on PTY sessions.** A per-model pricing
table is a NEW decision for John, not a repair.

## Honesty note
`_fmt_rollup_line:4847-4851` and `rollup_honesty.capture_rate_line:240` are genuinely
honest ("(subscription)", "measured N/T · K capture-failed"). **The one DISHONEST zero is
the summary tile**: `0 tokens · 0.0s · 0 run(s)` asserts the session never ran — false.

## Top 5 fixes (each verifiable with ZERO live spend — the data is already on disk)
1. **Include `general` (+zombie/gandalf) in the cost rollups** — `effort_history.py:2189`
   `ROLLUP_LANES` → add a `COST_LANES`. VERIFY: `project_effort_rollup("f69f6d66…")`
   must return **3,178,583 tokens / 530,558 ms** from the two existing records.
2. **Stop trusting index.json as sole truth** — `list_efforts:217-230` union index with
   `glob("*.pointer.json")`; add an index-repair pass in `record_effort:198-202` + a
   cross-process lock file replacing `paths.WRITE_LOCK:34`. VERIFY: `len(...) == 17`,
   both run-cost records present.
3. **Fix the wrong key** — `terminal_session.py:4082` and `:1920`: `"efforts"` →
   `"member_files"`. (Also repairs blank summaries.) VERIFY: hermetic assert on
   `extraction_seed` output — `effort.runs > 0`, `title != ""`, no model call.
4. **Effort line reads the run-cost record + self-heals** — `_aggregate_effort:470` +
   call site `:1200`: union members with `efforts_for_session_id(kind=="run-cost")`; fix
   `_find_session:985` to match the bare managed id, or recompute at render time instead
   of trusting a cached zero. VERIFY: re-render `summaries/a0a0772e…` → expect
   `2757886 tokens · 444.8s wall-clock · 1 run(s)`.
5. **Give the ledger a reader + backfill** — `.anchor/usage_ledger/` (43 docs, one
   internal consumer): non-finalizing read keyed off `_engine_uuids_of:369`, plus a
   backfill re-running `finalize_session_usage` over historical registry records. NOTE:
   Anchor ALREADY reads `~/.claude/projects/<slug>/<uuid>.jsonl` correctly
   (`locate_sidecar:267`, dedup `parse_sidecar_text:219`) — the untapped part is
   re-reading it for sessions whose finalize never ran. VERIFY: pinned
   `tests/fixtures/sidecar/` + `ANCHOR_SIDECAR_DIR`, zero live spend.

## Two warnings
- **The healthcheck CANNOT catch any of this**: `anchor_healthcheck.py:4863-4910` verifies
  run-cost only on a synthetic build/research lane against a fixture sidecar — never
  `general`, never index-under-contention, never the summarizer session-dict contract.
- **Divergent stale forks**: `C:\dev\Anchor\bundle_staging\*.py` and
  `planning\share-anchor-skills-2026-07\package-v1\**` (e.g. bundle_staging
  usage_capture.py lacks `_write_run_cost_wall_only`). **Land fixes in repo-root files only.**
