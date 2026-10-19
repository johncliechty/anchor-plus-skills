# Anchor hardening REVIEW + FIX PROGRAM — 2026-07-26

Evidence: FINDINGS-A (zombie), FINDINGS-BCD (tiles/summaries/restart · terminal ·
dictation), FINDINGS-E (logs + test audit) in this folder. Every claim file:line-verified
read-only. **The v1.1.0 release mirror carries every client-side defect** (byte-identical
`static/project-window.js`) — do NOT announce v1.1.0 until P0 lands.

## The one-paragraph verdict
Anchor's *architecture* is sound and its safety instincts are real (abstain-by-default,
gates, honest stamps). What's broken is a consistent pattern: **subsystems that report
success while doing nothing** — a zombie hunter that cannot see the orphan it exists for,
a summarizer that burns 194k tokens to render "no grounded claims", a reaper that has
never reaped, a restart doc with no goal or next action, and a health banner that stays
green over a 3.4× perf breach. Plus three concrete user-facing bugs (terminal replay,
dictation blow-up, 15s board flash) with root causes now pinned to exact lines.

## P0 — SHIP BLOCKERS (before the collaborator email)
| # | Fix | Where | Why now |
|---|---|---|---|
| P0.1 | **Terminal cursor resume**: client tracks `cursor`, sends `&since=` on BOTH SSE and WS; WS must read `since` (hardcodes 0 today); surface `dropped` | `static/project-window.js:4390/:4395/:4403-4406`; `anchor_gui.py:16608` vs `:16434-16436`, `:16493/:16639` | The double-print John sees; evidence at nssm-stdout.log:82259-82260 |
| P0.2 | **One mount per session + no false SSE fallback**: teardown in `_mountTerminal`, `gotData` flag before falling back, close old transport in `openPanel` | `project-window.js:4248-4262`, `:4429-4433`, `:2739` | Same bug family; also kills the dictation dual-input amplifier |
| P0.3 | **Dictation**: compose-box for ConPTY (port `vendor/anchor-term/anchor-term.js:72-82`) + composition-gated `onData` + clear textarea after commit + server-side input cap | `project-window.js:4300-4311`, `anchor_gui.py:13014` (use `MAX_TURN_CHARS` as at `:11029`) | iPad unusable today; cumulative blow-up polluted real transcripts |
| P0.4 | **Token out of the access log** — redact `?token=` in the request-line writer | `anchor_gui.py` log_message/BaseHTTPRequestHandler override | A collaborator reading logs sees the live capability token |
| P0.5 | **Test guard fail-CLOSED** (`setdefault`→`=`, add ANCHOR_GH_CMD/ANCHOR_CLAUDE_CMD), `ANCHOR_ENGINE_CMD` seam in `_resolve_engine_cmd`, fail-closed assertion in `start_session`, `--timeout=120` | `tests/conftest.py:50-55`; `terminal_session.py:436-457`, `~:638-668`; `pyproject.toml:16-21` | 8,816 leaked sessions once; guard is still fail-open; `gh repo create` reachable |
| P0.6 | **`ensure_zh_node` backoff + circuit breaker** (74 recycles at 6-8s, no give-up) | the ensure_zh_node supervisor in `anchor_gui.py` | Loudest error in the log, in the subsystem we want to demo |

## P1 — THE QUALITY COMPLAINTS (summaries / restart / transitions / zombie truth)
- **P1.1 RESTART.md becomes a real brief** generated AT HALT from live state, bounded
  model pass with the `pre_restart_drain.py:84` 20s-timeout pattern; transcripts demoted
  to an audit section. BAR: Goal(≤25w) · Status(+because) · Done(≤7) · Open decisions ·
  ONE Next action · Deliverables(non-transcript) · Do-not-re-litigate. Empty Goal/Next =
  gate failure. (`terminal_session.py:3105-3163`)
- **P1.2 Wire the brief into the readers**: RESTART.md = precedence rank 0 in
  `_build_continue_seed` (it never reads it today); orientation inlines Goal/Status/Next
  instead of `_floor_done`. BAR: resumed session's first turn cites Goal+Next with ZERO
  exploratory Read/Grep. (`anchor_gui.py:1864-1967`, `orientation.py:66-118`, `narration.py:294`)
- **P1.3 Summaries stop being blank**: don't call the model when the corpus is
  title-only (emit an honest deterministic tile); add a real `general` signal set +
  transcript-aware seed (lift USER TURNS); prefer non-transcript members. BAR:
  no_grounded_claims ~60% → <10%; zero model calls on a title-only corpus.
  (`summarizer.py:190/:167/:286/:209/:619`)
- **P1.4 Run 2 becomes a JUDGE not a second author** (union → ≥2-run agreement + near-dup
  collapse; cap project objective 3 sentences). BAR: no two sentences ≥60% token overlap;
  ≤90 words. Fixture: `f69f6d66…/project-summary.md` 700w → 1 para. (`summarizer.py:649-670`)
- **P1.5 Zombie detection becomes REAL** (all shadow-safe): parent-confirmed-dead ⇒
  `UNSUPERVISED/ORPHAN_DETACHED_SPENDER` (the catalogued code the classifier never emits);
  real session-activity test (window/console, or Anchor's own `live_owner_ids` from
  `reaper.py:512-523` via the ownership registry seam); demote `explorer`/`conhost` to
  weak-host (bump HOST_ALLOWLIST_VERSION ⇒ auto re-shadow); spend memory + admit the
  MEASURED ledger; fix the Investigate seed + persist `burnUncertain`.
  **Proof: plant a real orphan (spawn from a throwaway pwsh, kill the pwsh) and require
  it to appear in observe with actionableRed:false.** (zombie-hunter/src/*)
- **P1.6 Keyed board diff** replacing the 15s `innerHTML` swap (state-hash → no-op when
  unchanged; patch reused nodes so CSS transitions fire; delete the openStates block).
  BAR: zero innerHTML writes when unchanged; same node identity across running→done; no
  lost details/scroll/selection over 5 polls. (`project-window.js:3922-4015`, `:2212-2217`)

## P1b — USAGE TRACKING (FINDINGS-F) — cheapest high-value win in the whole program
**The numbers are already on disk** (2,757,886 tokens / 444,813 ms in one general-lane
record whose summary says "0 tokens · 0.0s · 0 run(s)"). Writers work; readers are blind.
- **P1b.1** add `general`/`zombie`/`gandalf` to the cost rollups (`effort_history.py:2189`
  ROLLUP_LANES) — one tuple; verify `project_effort_rollup("f69f6d66…")` = 3,178,583 tok.
- **P1b.2** `list_efforts:217-230` union index.json with a directory glob (index is lossy:
  17 pointers, 13 indexed) + cross-process lock replacing `paths.WRITE_LOCK` (`paths.py:34`).
- **P1b.3** `terminal_session.py:4082`/`:1920` `"efforts"` → `"member_files"` — **this one
  key ALSO fixes the blank-summary epidemic (same RC as FINDINGS-B)**.
- **P1b.4** Effort line reads the run-cost record + recompute-at-render (kill cached zeros).
- **P1b.5** ledger reader + backfill (43 populated docs, 1 internal consumer).
- **DECISION FOR JOHN (not a repair)**: `$0.00 (subscription)` is a LOCKED
  no-own-pricing-table policy (`usage_capture.py:24-27`). Tokens+time become real without
  it; real $ needs either a per-model price table (new) or wider use of zombie-hunter's
  measured ledger. **Ask before building.**

## P2 — HYGIENE / TRUTH-IN-REPORTING
Perf: home page 321-329KB / 8.5-16.1s and journal overhead 26-51% vs 15% budget must
either redden the banner or be re-baselined honestly · `errors.log` cp1252 mixed encoding
(grep silently skips lines — false-clean) + `→` UnicodeEncodeError losing boot lines ·
access log has no dates · orphan-worktree reaper 160× dry-run "held", list 24→40, never
reaps (arm it or say plainly it's disabled) · reaper blast-cap defers the SAME 2 ids
forever · healthcheck R&D v12 RED (unborn HEAD in the temp project) + the masked
`view_ok=False` · `: boom` placeholder in production logs · ~20 SyntaxWarnings per boot ·
`RuntimeError: can't start new thread` (thread-per-request + leaked SSE pumps) ·
"test port 8778 busy" auto-fix in 24/24 reports · 18 service restarts in 4 days.

## Constraints honored
- **C1 Stage 2 stays PARKED** — the project-window half already shipped; every fix above
  is backend or in the already-extracted `static/project-window.js`. Only brush: two
  `window.location.reload()` calls inside the home-dashboard f-string
  (`anchor_gui.py:7831`, `:8754`) — one-line substitutions, flag to John, not an extraction.
- **Ecgberht: zero footprint in Anchor** (logs, tests, state tree all clean) — no
  exclusion work needed; v1.2 integration unobstructed.
- Fixes must land in `C:\dev\Anchor` (canonical) AND propagate to
  `C:\dev\Anchor-release-v1.0` (byte-identical client defects) before any re-cut.
