# Session Handoff — Anchor R&D Surface (v12 BUILT, awaiting whole-branch sign-off)

> Written 2026-06-22 to transition this work to a fresh Claude Code session.
> Current as of `master` @ `f2e0e40` (v11.1 live) + the unmerged branch
> `foreman/rnd-surface-v12` (v12 "Efforts", all 12 waves GREEN).
> (NOTE: this is a SESSION handoff for the human/assistant — distinct from the product's
> auto-generated `HANDOFF.md` artifact that Anchor writes into trio worktrees.)

## Gandalf integration v1 (branch `gandalf-integration`, in progress 2026-06-22)

- A SEPARATE branch off master `7c2f51f` (v12). Gives each project an honest "what's really
  going on here" read by invoking the **existing** Gandalf skill through Anchor's runner seam
  (Stage A model → RAW draft) then grading it with Gandalf's own Tier-1 host (Stage B, the
  `ANCHOR_GANDALF_HOST_CMD`/`node` seam → GRADED output). New stdlib-only `gandalf.py`; a
  white-wizard **Gandalf tab** in the project right column ABOVE Grass; endpoints
  `GET /api/rnd/gandalf` + `POST /api/rnd/gandalf_run`; CLI `rnd gandalf <pid>`;
  `check_gandalf_surface` in the healthcheck (both seams stubbed). Frozen design +
  4-wave plan in `planning/gandalf-v1/`. **Waves 1+2 (backend) + 3 (UI tab) + 4 (CLI/HC/distro/docs)
  built.** Deploy note: first-scan auto-runs ONE Gandalf per newly-registered project once
  proactive summary is on; a manual real-`claude -p` live-smoke is a deploy checklist item (not a
  pytest gate). NOT merged / NOT deployed — awaiting John's sign-off + a screenshot of the tab.

## TL;DR — what the next session must do

- **v12 "Efforts" is BUILT — NOT merged, NOT deployed.** All 12 waves are GREEN on branch
  `foreman/rnd-surface-v12` (off master `f2e0e40`, v11.1 merged + deployed). It is awaiting
  **John's whole-branch sign-off** → then merge (`--no-ff`) + `nssm restart anchor` (elevated)
  + rescan the 6 active projects (the same deploy procedure as v11.1, retained below).
- The three UI waves (W2 static skeleton, W10 live Layout-D + dock, W11 grass workbench) each
  already have John's per-wave screenshot sign-off (per `planning/rnd-v12/EXECUTION-LOG.md`);
  the remaining gate is John's review of the whole branch before merge.

## Where things stand

- **Repo:** `C:\dev\Anchor` (single folder, local git; origin is a local bare repo at
  `E:\anchor.git`, NOT GitHub). Service runs as the NSSM service `anchor` on
  `http://localhost:8777` (host `PUTER`/`gwl-server`). Restart only via `nssm restart anchor`
  (elevated). Mutating `/api/*` are token-gated: the `ANCHOR_TOKEN` is in the NSSM service env
  (`AppEnvironmentExtra`), sent as the `X-Anchor-Token` header.
- **master HEAD:** `f2e0e40` (v11.1 "Handoff Always Primes") — **LIVE + DEPLOYED** since
  2026-06-20. The live service is still on v11.1; v12 is NOT yet on master.
- **Unmerged branch pending: `foreman/rnd-surface-v12` (v12 "Efforts").** Continuity-first
  single-session trio: an effort is ONE session, "Advance" relabels+persists+summarizes
  IN-SESSION (no new session / no PTY injection), a one-click fresh-session handoff is the
  context-relief valve, and legacy chains render AS efforts via the new `effort_view.py`
  (the lone NEW stdlib-only module). The locked discriminator is `effort_managed` — every
  legacy session-minting path is gated off for v12 efforts, keyed on it (never on
  `kind`/`current_stage`), so the v6/v8/v10/v11 healthcheck walks pass unchanged. New CLI
  mirrors: `rnd efforts` / `rnd effort --session` / `rnd effort-deliverable --session`. New
  healthcheck: `check_rnd_v12_surface` (8 steps, fully stubbed). See `CLAUDE.md` "R&D Control
  Surface v12" + `planning/rnd-v12/` (MASTER-PLAN / IMPLEMENTATION-PLAN / EXECUTION-LOG).
- Baseline test count at the v12 branch cut: **1266 passed, 1 skipped**. v12 adds tests across
  all 12 waves (W12: `tests/test_cli_efforts_v12.py` + `tests/test_healthcheck_v12.py` +
  `tests/test_distro_scan_v12.py`). The orchestrator runs the full `python -m pytest -q` as the
  gate of record.

## What v11.1 fixes (the user's live failure)

John advanced a **grass research session that was a CONVERSATION** (no file written) and got
**"no materials to advance" — it opened nothing.** Root cause (two corroborating traces): the
handoff only treated **written document files** as "material"; a conversation-only research
session writes no file, so the grass advance **hard-refused**, and the conversation was lost.

v11.1 (on top of v11):
- **W1 (`a5063d6`):** `terminal_session.prepare_stage_handoff` now **synchronously snapshots
  the source PTY transcript** when no doc was produced — `_snapshot_transcript_doc` reads
  `pty_manager.read_since(sid,0)`, `_clean_transcript_text` does **real-ConPTY cleaning**
  (\r-redraw frame-collapse, ANSI/OSC strip, wrap-tolerant seed/greet strip, box/spinner
  chrome drop, dup-line collapse, head+tail cap), writes `<wt>/<lane>/<sid>-transcript.md`,
  re-persists. The no-docs prompt is now **honest + actionable** ("create the materials"; no
  false "report is in this worktree"). Background summary refines it
  (`ANCHOR_PROACTIVE_SUMMARY` exported in `anchor_gui.main()`, deduped vs the finish hook —
  skips a TERMINAL source).
- **W2 (`9552049`):** removed the grass **`no-research-material` hard-refusal** so advance
  always opens; `effort_history._materialize_handoff_into_plan_worktree` **copies the
  transcript + writes HANDOFF.md/NEXT-PROMPT.md INTO the plan worktree** (both fresh-mint AND
  develop-plan-first orderings — closing a BLOCKER where the transcript was named but absent
  from the checkout, so Crucible could actually open it). John signed off the screenshot.
- **W3 (`401b892`):** `check_rnd_v11_1_surface` healthcheck walks the real conversation-only
  flow; CLAUDE.md updated. PROJECT DONE.

Net: advancing a research session that was a **conversation** now snapshots the transcript,
makes it **readable on disk in the next stage's worktree**, opens the next session with a
doc-referencing prompt, and **never refuses** — grass or non-grass.

## How this work is done (the rules — follow them)

- **Crucible plans, Foreman builds.** Substantive changes: Crucible (frozen MASTER-PLAN +
  IMPLEMENTATION-PLAN under `planning/rnd-vXX/`) → repoint `foreman.config.json` → `node
  ~/.claude/skills/foreman/bin/locate-plan.mjs --json` must exit 0 → Foreman drives each wave
  EXECUTE → **2 independent adversarial reviewers (read-only, prompted to refute)** → FIX →
  re-gate. **The orchestrator runs `python -m pytest -q` itself** as the gate of record (never
  a sub-agent's claimed output).
- **Adversarial review is non-negotiable and it works** — this round it caught the real bugs
  the green suite missed (stub-clean-but-real-ConPTY-garbage transcript; named-but-not-on-disk
  transcript; a prod double-summary). Always run ≥2 reviewers per wave and act on concrete
  findings.
- **THE v11/v11.1 test lesson:** advance/handoff tests must exercise the **live flow** — write
  produced docs into the session **worktree only** (no `eh.record_effort` pre-persist); for
  conversation-only, **seed the stub PTY read buffer** (`pty_manager.write` echoes into
  `read_since`) instead of writing a file. A pre-persisted/pre-written test is masking coverage,
  never the sole coverage of an advance path.
- **Constraints:** Python **stdlib only** (lone exception: lazy `pywinpty` in `pty_manager.py`).
  Hermetic tests — `ANCHOR_PTY_BACKEND=stub` + `tests/stub_streamjson.py` + temp git/data dirs;
  **never bind `:8777` / touch real data / network**; `ANCHOR_PROACTIVE_SUMMARY` off in tests.
  **Playwright is DEV-ONLY** (`pytest.importorskip`), never in product. UI waves need
  rendered-DOM + Playwright + screenshot + John's sign-off. `distro.py` import scan stays green.
  `anchor_gui.py` HTML is f-string (double braces); `_PROJECT_WINDOW_JS` is a RAW single-brace
  string. **No merge to master / no `nssm restart` until John signs off.**

## Deploy — DONE 2026-06-20 (steps 1-4 complete; step 5 = John's manual test, still open)

1. **Merge** — DONE. `master` `b6719bd` → `f2e0e40` via `--no-ff`; merged tree verified
   byte-identical (`git diff --stat foreman/rnd-surface-v11.1 HEAD` empty). **Pushed to
   `origin/master`** (`E:\anchor.git`).
2. **Restart** — DONE (John ran `! nssm restart anchor`).
3. **Verified up on new code** — `GET /` → 200; seams present (`prepare_stage_handoff` ×7,
   `_materialize_handoff_into_plan_worktree` ×3).
4. **Rescanned the 6 active projects** — all 200.

   --- (original deploy procedure, retained for reference) ---

1. **Merge** (clean — the branch was cut from current master, so the merged tree is identical):
   ```
   git checkout master
   git merge --no-ff foreman/rnd-surface-v11.1 -m "Merge v11.1 'Handoff Always Primes' to master (3 waves GREEN 1266)"
   git diff --stat foreman/rnd-surface-v11.1 HEAD    # must be EMPTY (identical tree)
   ```
   (Optionally `git push origin master` — origin is the local `E:\anchor.git` mirror; only if
   John asks.)
2. **John restarts:** have him run `! nssm restart anchor` (he runs it; you cannot).
3. **Verify up on new code:** `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8777/`
   → 200; the v11.1 seams exist (`grep -c prepare_stage_handoff terminal_session.py`,
   `grep -c _materialize_handoff_into_plan_worktree effort_history.py`).
4. **Rescan the 6 active projects** (regenerates cached summaries). Read the token from the NSSM
   service env, POST `/api/rnd/rescan` with the `X-Anchor-Token` header. Active ids:
   - Anchor `f69f6d66171f4dbd95c8c45db6846d97`
   - Agentic-Home `fe0a3e82a76347a19c91c365fd87787c`
   - MBA Teaching AI `6765ece4b3bc43b0b0b0907b92b17280`
   - aurora `60e01b3cb2f5426ca9d2c03c26e40afa`
   - Transformer Math `bd8f0e938fb24af5b689ba830c902bff`
   - Skill Foundry `30ffba93f3614ce48aeda6252b74cf42`

   PowerShell pattern (used last deploy) to read the token + rescan:
   ```powershell
   $raw = (& nssm get anchor AppEnvironmentExtra 2>&1 | Out-String)
   foreach ($line in ($raw -split "[`r`n`0]")) { if ($line -match '^\s*ANCHOR_TOKEN=(.+?)\s*$') { $tok = $matches[1].Trim() } }
   # then for each id: POST {"project_id":"<id>"} to http://localhost:8777/api/rnd/rescan
   #   with header X-Anchor-Token=$tok  (Invoke-WebRequest -Method POST -ContentType application/json)
   ```
5. **Then John gives it a real run:** a researchPrime/research session as a **conversation**
   (no file), click **Advance to Plan** → it should open the plan session with the prompt
   naming `research/<sid>-transcript.md`, the transcript readable in the plan worktree. If
   anything's off, trace it the v11/v11.1 way (worktree-only / conversation-only).

## History (most recent first)

- **v12** `foreman/rnd-surface-v12` — "Efforts" (continuity-first single-session trio: in-session
  advance/relabel+persist+summarize, context-relief fresh-session handoff, legacy chains rendered
  AS efforts via the new `effort_view.py`, Layout-D headline/shelf board + embedded dock, grass
  one-session workbench). All 12 waves GREEN, done 2026-06-22. **NOT merged / NOT deployed** —
  awaiting John's whole-branch sign-off then merge + `nssm restart anchor` + rescan.
- **v11.1** `f2e0e40` — Handoff Always Primes (conversation capture). MERGED (`--no-ff`, off v11)
  + DEPLOYED + pushed to origin 2026-06-20. GREEN 1266.
- **v11** `b6719bd` — Reliable Trio Handoff (the `prepare_stage_handoff` keystone; persist source
  docs before advancing). MERGED + DEPLOYED.
- **v10.1** `465fda9` — 4 live-use fixes (restart-window reuse, grass-delete persistence,
  dashboard running-dot, grass terminal reflow). MERGED + DEPLOYED.
- **v10** `39fc853` — Live Handoff & Boneyard (paste-not-submit handoff, grass two-terminals +
  archive + grass_origin lineage, per-project Boneyard `boneyard.py`). MERGED + DEPLOYED.
- Per-wave EXECUTE/REVIEW/FIX/JUDGE history for each is in `planning/rnd-vXX/EXECUTION-LOG.md`.

## Memory pointers (auto-loaded each session)

`C:\Users\john\.claude\projects\C--dev-Anchor\memory\` — see `anchor-rnd-surface-v11-1.md`
(this work), `anchor-rnd-surface-v11.md`, `anchor-rnd-surface-v10.md`, `anchor-runtime-facts.md`
(host/service/token facts), `MEMORY.md` (the index).
