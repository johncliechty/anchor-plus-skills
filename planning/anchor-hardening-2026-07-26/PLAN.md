# Anchor world-class hardening — 2026-07-26 (pre-collaborator-share gate)

**THE EFFORT**: John wants a comprehensive review/revamp/hardening of ANCHOR (the
product) before sharing v1.1 with collaborators — same method as the 2026-07-25
skills journal-hardening pass (which he rated highly): verify every claim against
code, trust journals/logs over docs, check failures are pre-existing at HEAD before
blaming a change, run smoke tests under COLLABORATOR conditions, fix directly with
regression tests, journal every fix. Bar: **world class**.

## John's specific complaints (his words, expanded)

1. **Zombie-hunter must REALLY hunt**: track real zombies = token-spending sessions
   NOT tied to a live session somewhere (VS Code, PowerShell, Anchor terminal).
   Verify the ownership/liveness model end-to-end against the RUNNING system — does
   it actually catch orphaned spenders? False negatives are the concern (it's been
   shadow-mode CLEAN — is that true, or is it blind?).
2. **Project-dashboard / workbench big tiles**: needs a smooth-looking transition
   and RESTART capability for all large tiles. Today: "the summaries are not great
   and the restart docs are not great — I often have to have the session do a search
   for what is going on." So: tile summaries (what a returning user sees) + restart/
   carry-on docs (what a fresh session loads) both need real quality work.
3. **Terminal misbehavior on his laptop**: double printing, not tracking well.
4. **iPad dictation problem** into an Anchor session — he says "I have a few Anchor
   logs to look at" → hunt `C:\dev\Anchor\logs\` (+ health_reports/) for evidence of
   both the terminal and dictation issues.
5. General: catch what the skills pass caught — dark modules, prose-only claims,
   stale docs, silent failures, false-green tests.
6. **USAGE TRACKING (added by John 2026-07-26, mid-review)**: "the tracking of usage
   (tokens, time and estimated $) seems sporadic to non-existent, even though there is
   supposed to be wiring there for that." → AGENT F. Note the evidence already in hand:
   a zombie summary tile recorded **194,422 tokens / 66.6s** (so SOME capture works) while
   most session summaries render **"Effort: 0 tokens · 0.0s wall-clock · 0 run(s)"**
   (FINDINGS-BCD §B2) — i.e. the meter is wired but usually reads zero. Also relevant:
   zombie-hunter's spend.js has a REAL measured Claude token ledger (spend.js:782-838,
   evidenceClass measured|activity) that currently feeds only the burn UI. Suspect: the
   PTY/terminal path (John's daily "general" lane) never reports usage at all, while the
   job_runner one-shot path does.

## Hard constraints

- **EXCLUDE Ecgberht entirely** from review/changes — but stay AWARE of it so this
  work integrates cleanly into Anchor v1.2 (note integration points, don't touch).
- v1.1.0 is tagged/pushed but NOT yet announced — this hardening supersedes it
  (v1.1.1 or re-cut) BEFORE the collaborator email goes out.
- Repo map: `C:\dev\Anchor` = LIVE service repo (NSSM service; origin E:\anchor.git;
  my foundry_journal fix is committed here @626340a). `C:\dev\Anchor-dev` = github
  dev/share repo (origin johncliechty/Anchor-dev; I repaired its corrupted
  vendor_skills.py @6c2afc3). `C:\dev\Anchor-release-v1.0` = release repo (github
  johncliechty/Anchor; master=v1.1=tag v1.1.0=80b6409). Determine per-fix which repo
  is canonical for Anchor product code (likely C:\dev\Anchor, then propagate).
- Anchor's test suite: ~2104 pytest tests (python -m pytest tests/ from C:\dev\Anchor).
  KNOWN LEAK CLASS: some pytest GUI tests spawned REAL claude sessions (memory
  usage-leak-2026-07-14; "mock-the-tests" was pending) — do NOT blindly run the full
  suite; run targeted files; check for live-spawn tests first.
- Sub-agent rule: review agents are Read/Grep/Glob ONLY (no shells — spawned
  PowerShells disrupt John's machine).
- Decisions one at a time, with recommendation; render content fully in chat.
- Status updates lead with a one-line "what this effort is FOR".
- Journal fixes in the affected component; Anchor itself journals under... check
  (Anchor has no skill journal; use planning/anchor-hardening-2026-07-26/JOURNAL.md).

## Context from the just-finished skills pass (relevant leads)

- zombie-hunter skill review (2026-07-25): Node sentinel + Ward GUI verified real;
  abstain-by-default verified at spec+test+runtime; still `classifierMode: shadow`,
  `zombieActionable: 0`. The 2026-07-05 Gandalf verdict "NOT safe to ARM" was
  honored. John now wants proof it CATCHES real zombies — i.e., test the DETECTION
  side (quad predicate: SUPERVISED/QUAD_KEEP/VERDICT_KEEP legs) with a REAL orphan,
  not just the safety side. Files: skills/zombie-hunter/src/{server,mode,daemon,
  forensics,ownership,host-walk,spend}.js; Anchor-side reaper: C:\dev\Anchor
  (reaper/ownership modules, tests/test_reaper_abstain.py); `.zh-last-known.json`
  is live state. "Slim seed arrived with pid/class unknown and no reason codes"
  (journal 0004) = known lossy seed emitter — likely part of why hunting feels weak.
- Anchor GUI: anchor_gui.py, foundry_gui.py, panel/tile code in C:\dev\Anchor root
  (boneyard.py, anchor_healthcheck.py etc. seen). The .anchor/projects/__dashboard__
  tree at C:\dev\.anchor holds dashboard state (summaries/, planning/, research/
  efforts, project-summary.md) — the "summaries not great" complaint likely maps to
  whatever writes project-summary.md / tile summaries there.
- Memory note: "C1 Stage 2 (home-dashboard blob) PARKED by John — keep parked" (from
  the earlier Anchor re-architecture). His new tile-restart ask may overlap — ASK
  or treat as a fresh requirement, don't silently unpark.
- Terminal: Anchor terminal tile (the ZH-style terminal tile pattern exists in
  tidy-idy render.mjs; Anchor's own terminal impl is in the Anchor repo — find it;
  "double printing" smells like duplicated event listeners / SSE double-subscribe
  on reconnect, or PTY echo).
- iPad dictation: Anchor is served over network? (reverse-proxy mention "apiUrl for
  reverse-proxy clients" in zombie-hunter v1.0 notes). Dictation → likely textarea/
  input event handling in the web GUI (composition events / speech input produce
  `insertReplacementText` / composition events that naive keydown handlers mangle).
  Find the input handling + the logs.

## Plan (phases)

- **P0 (done first, this doc)**: durable state so compaction cannot lose the effort.
- **P1 EVIDENCE**: fan out read-only agents (no shells):
  A. zombie-hunter DETECTION reality check (both substrates + seed emitter + live
     state + what a real orphan looks like on this machine).
  B. dashboard tiles: summaries + restart/carry-on docs pipeline (writers, readers,
     quality gaps; the __dashboard__ state tree; transition smoothness).
  C. terminal implementation review (double-print/tracking) + logs evidence.
  D. iPad/dictation + remote-client input path + logs evidence.
  E. Anchor logs + health_reports sweep (last ~2 weeks) for error clusters incl.
     the two John mentioned; also test-suite live-spawn audit (which pytest files
     spawn real sessions — the mock-the-tests debt).
- **P2 SYNTHESIS**: consolidated review doc at
  planning/anchor-hardening-2026-07-26/REVIEW.md, P0/P1/P2 fix program, present to
  John (decisions one at a time; recommend fix order).
- **P3 FIX + VERIFY**: direct fixes w/ tests; live verification against the running
  service where safe (GUI smoke via existing test harnesses; careful with the NSSM
  service — coordinate restarts with John); journal entries; commit per repo.
- **P4 SHIP GATE**: re-vendor, in-bundle smoke (the memo commands), re-cut release
  (v1.1.1 or move the announce), update collaborator memo x3 if anything changes.

## STATUS CADENCE (John, 2026-07-26 — MANDATORY for this effort)
Post a status update **every ~10 minutes of working time** in the LOCKED format
(user-global AGENTS.md "Long-run progress updates"): a `[HH:MM]` header, then
Effort / Doing / Status / Tests / Blocker / Procs / **Journal** rows, then an
ETA + To do footer — and **lead with the one-line "what this effort is FOR"**
goal line (memory: feedback-status-about-line). Append each update to
`STATUS.md` in this folder (tracked, so John can read it any time) AND post it
in chat. The Journal row now has a real source: `anchor.py friction-report`.

## Status ledger (update as work proceeds)

- [x] P0 durable state written (this doc + memory)
- [x] P1 agents LAUNCHED 2026-07-26 (all five, read-only): A zombie-detection /
      B tiles+summaries+restart / C terminal / D dictation / E logs+test-spawn-audit.
      Reports arrive as task notifications; if a report seems missing after
      compaction, the transcripts live under the session tasks dir — but prefer
      re-launching a fresh agent over reading raw transcripts.
- [x] 4 of 5 reports IN + written durably: FINDINGS-A-zombie-detection.md,
      FINDINGS-BCD.md (tiles/summaries/restart · terminal · dictation). Agent E
      (logs sweep + pytest live-spawn audit) still running as of the compaction point —
      if its report never arrived, RELAUNCH it (prompt sketch in this file's P1-E line).
- [ ] P2 REVIEW.md + program presented — HEADLINES ALREADY ESTABLISHED (do not re-derive):
      (1) zombie detection is structurally blind to the real Windows orphan (dead
      parent ⇒ abstain); (2) terminal double-print = every reconnect replays 200KB
      from cursor 0 (client never sends `since`) + SSE fallback fires on a working WS
      + no teardown in _mountTerminal; (3) iPad dictation = xterm 6.0.0 never clears
      its hidden textarea and its only guard needs keyCode 229 which iOS never sends,
      Anchor forwards uncapped; (4) summaries: ~60%+ render "no grounded claims"
      (corpus is titles-only), and "generate twice" UNIONS both runs = duplication;
      (5) RESTART.md has no goal/status/decisions/next-action and _build_continue_seed
      never reads it. **All defects also ship in Anchor-release-v1.0 (v1.1.0).**
- [x] ALL 6 evidence reports in + durable: FINDINGS-A (zombie), FINDINGS-BCD
      (tiles/terminal/dictation), FINDINGS-E (logs+tests), FINDINGS-F (usage).
      REVIEW.md holds the full P0/P1/P1b/P2 program.
- [x] **JOHN'S DECISION 2026-07-26: "P0 + usage + summaries, then re-cut v1.1.1."**
      SCOPE FOR THIS FIX WAVE (do exactly this, in this order):
      1. P0.5 test guard fail-CLOSED FIRST (conftest `setdefault`→`=`, +ANCHOR_GH_CMD,
         +ANCHOR_ENGINE_CMD seam in terminal_session.py:436-457, fail-closed assert in
         start_session, pyproject --timeout=120) — do this BEFORE running any test.
         Use the verified safe smoke subset in FINDINGS-E until it lands.
      2. P1b.3 `terminal_session.py:4082` + `:1920` "efforts"→"member_files" (one key;
         fixes BOTH the zero-usage Effort line AND the blank-summary epidemic).
      3. P1b.1 COST_LANES incl. general/zombie/gandalf (effort_history.py:2189).
      4. P1b.2 list_efforts union index+glob (:217-230) + cross-process lock (paths.py:34).
      5. P1b.4 Effort line reads run-cost + recompute-at-render (kills cached zeros).
      6. P0.1 terminal cursor resume (client `since=` on SSE+WS; anchor_gui.py:16608).
      7. P0.2 one-mount-per-session teardown + gotData flag (project-window.js:4248/:4429/:2739).
      8. P0.3 dictation: compose box + composition-gated onData + clear textarea + server cap.
      9. P0.4 redact `?token=` from the access log writer.
     10. P0.6 ensure_zh_node backoff/circuit-breaker.
     11. P1.3/P1.4 summarizer: no model call on title-only corpus; run2 = judge not author.
      THEN: propagate to C:\dev\Anchor-release-v1.0, re-vendor, in-bundle smoke, tag
      v1.1.1, update the collaborator memo x3, push.
      DEFERRED to v1.1.2/v1.2 (tell John, don't silently drop): P1.5 zombie detection
      real, P1.1/P1.2 restart briefs, P1.6 keyed board diff, P2 hygiene, and the
      $-pricing-table DECISION (locked no-own-pricing policy — ask, don't build).
- [x] **WAVE 1 LANDED + COMMITTED (Anchor 121b479, 2026-07-26)**: test guard
      fail-closed (conftest hard-assign + ANCHOR_ENGINE_CMD seam + fail-closed
      assert at all 3 spawn sites + ANCHOR_GH_CMD stub + live marker);
      usage visibility (ROLLUP_LANES +general/zombie/gandalf; list_efforts
      index∪glob; member_files key at both call sites).
      **PROVEN: general lane now rolls up 3,178,583 tokens / 530,558 ms
      (was invisible); 17 efforts visible (was 13).** +5 regression tests green.
      Smoke subset 40 pass / 1 pre-existing fail (test_token_hygiene, at HEAD).
      NOTE: the member_files fix should ALSO fix the blank-summary epidemic —
      verify by regenerating a summary before claiming it.
- [x] **JOURNALING BUILT + COMMITTED (Anchor 638b0cb)**: friction_journal.py
      (store + capture + auto-context + lifecycle + friction_report intake
      brief) + anchor.py CLI (`journal`, `friction-report`, `friction-resolve`)
      + 10 tests. Verified end-to-end incl. closing a record with a real commit.
      VERSION -> 1.1.1. STILL TO DO for the feature: the HTTP endpoints
      (POST /api/rnd/journal_friction, GET /api/rnd/friction) + a UI capture
      control, so it is reachable from the dashboard, not only the CLI.
- [x] (superseded — see above) NEW REQUIREMENT (John 2026-07-26): FRICTION
      JOURNALING + sleep-cycle intake.** Full design:
      `JOURNALING-FEATURE.md` in this folder. Verified gap: share_feedback.py
      covers SKILL journals only; docs/friction/*.md were HAND-WRITTEN; Anchor
      has NO user-facing capture for its own friction. Build: .anchor/friction
      store + POST /api/rnd/journal_friction + GET /api/rnd/friction + CLI
      `journal` / `friction-report` (the sleep-cycle intake brief) + UI control
      + tests. Zero model calls on the capture path (it must work when engines
      are down). Must appear in the collaborator memo as the "tell us what hurt"
      mechanism.
- [ ] NEXT (wave 2, in order): P0.1 terminal cursor resume · P0.2 one-mount
      teardown + gotData · P0.3 dictation compose box + composition gate + cap ·
      P0.4 token redaction in access log · P0.6 ensure_zh_node backoff ·
      P1.3/P1.4 summarizer (no model call on title-only corpus; run2 = judge).
      THEN propagate to Anchor-release-v1.0, re-vendor, in-bundle smoke, v1.1.1,
      memo x3.
- [ ] P3 fixes landed
- [ ] P4 ship gate re-run
