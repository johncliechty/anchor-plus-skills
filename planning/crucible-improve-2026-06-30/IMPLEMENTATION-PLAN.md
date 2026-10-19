# Implementation Plan — Anchor Improvement Effort (Crucible Stage 2)

> **Status:** REVISED after Stage-2 Shark-Tank (see `S2-SHARK-TANK.md`). Pending user
> approval → Foreman handoff. Derived from the LOCKED `MASTER-PLAN.md`. Depth **FULL**.
> 9 Foreman-ready waves, reordered so every dependency precedes its dependent.

## Build substrate
- One app: `anchor_gui.py` (Python stdlib) + sibling modules. No new third-party deps
  (the lone `pywinpty` exception stands; `distro.py`'s scan enforces it).
- Deploy = `nssm restart anchor` (elevated) after merge — a one-time step the USER runs
  on gwl-server; not part of any wave.
- The Foreman build runs Claude-driver + Gemini swarm sub-agents via `agy-dispatch`
  (locked #10 decision) and writes each wave's run summary into this planning folder.

test-command: "C:\Program Files\Git\usr\bin\bash.exe" tests-gate.sh

> **Gate runs via a bash wrapper (`tests-gate.sh`) — W3 amendment.** Foreman runs the
> gate through `spawnSync(shell:true)` = **cmd.exe**, which does NOT expand globs. So the
> gate is `tests-gate.sh`, run under git-bash (full path), which `cd`s to the repo root,
> sets `nullglob`, and runs the curated baseline file list PLUS `tests/test_*_w[0-9].py`
> (bash expands it). Each wave's NEW deterministic STUB-GATE tests must live in a file
> named `tests/test_<topic>_w<N>.py` so the wrapper's glob auto-collects them (no
> per-wave static-list HALT). Tests that fit an already-listed file may be appended
> there instead. Verified: 230 passed through Foreman's exact spawnSync path.

> **Gate scope note (Stage-2 build finalization):** the plan's gate is a fast (~82 s),
> deterministic, wave-covering subset, not the full suite — the full `pytest` run times
> out (>10 min) and includes Playwright/browser tests that fail headless. The two
> deselected tests are browser-based (`importorskip("playwright.sync_api")`); their
> visual behavior is verified in the SIGN-OFF lane (Playwright + screenshot), per the v4
> rule. Each wave ALSO adds its own deterministic STUB-GATE tests, which run here.

> **Gate model (per Anchor's v4 rule).** Each wave's done-when has a **STUB GATE** — a
> concrete `pytest` assertion the Foreman gate runs (stubbed: `ANCHOR_PTY_BACKEND=stub`,
> `ANCHOR_RUNNER_CMD`→`fake_claude.py`, temp dirs, never live `:8777`) — and, where the
> behavior is visual or needs a live model, a **SIGN-OFF** (Playwright + screenshot +
> user confirmation) verified after the wave builds. Foreman advances on the STUB GATE;
> the SIGN-OFF items are surfaced for the user.

## Wave order & dependency rationale
`W1, W2` are independent. `W3` (resume backend keystone) precedes `W4` (resume UI),
`W5` (quick UI), and `W6` (controls) — all depend on its effort-view folding / resume
seed so discovered efforts don't usurp tiles and `×`-closed sessions reopen warm.
`W7` is independent. `W8` (model-flex) precedes `W9` (Gandalf), which fans out through
W8's substrate. Each wave ships independently on merge; no big-bang.

---

## Wave 1 — Honest warnings: context budget + zombie page
- **#7** Raise `CONTEXT_FULL_BUDGET_BYTES` to ~1 MB and subtract a fixed seed allowance
  so the warning reflects real growth, not the skill seed (`terminal_session.py:1309-1380`).
- **#12a** Add a bounded auto-refresh (interval/SSE) to the zombie page so it updates
  live without a manual reload (`anchor_gui.py:14650-15036`).
- **#12b** Fix the structurally-dead embedded terminal: permit a dashboard-scoped
  `zombie` lane + registered dashboard project so `/api/rnd/zombie_terminal_start`
  (`anchor_gui.py:16535-16542`) returns 200, not 400.
- **STUB GATE:** a freshly-seeded stub session reports `context_status.over_threshold ==
  False`; `zombie_terminal_start` for the dashboard scope returns a session record (no
  400); the zombie report endpoint emits the refresh hook.
- **SIGN-OFF:** the zombie page visibly updates during a sweep; the terminal opens and
  accepts a line.

## Wave 2 — Swarm-warning correctness (safety-critical)
- **#1** Replace the orphan discriminator: a registered-running session is an orphan
  ONLY if identity-alive AND it has **no live owner** — not in `pty_manager.live_sessions()`
  AND no actively-running owning job AND no live parent session. Apply in `classify`'s
  caller / `orphan_check` (`anchor_gui.py:14613-14648`, `zombie_hunter.py:127-170`). On
  boot, reconcile registry "running" records by process liveness (dead → terminal, no
  banner). NEVER "effort-bound ⇒ never warn" (that neuters the hunter); the line is
  **live owner**, not effort-binding.
- **STUB GATE (injected `probe` + constructed states):** (a) running + alive-PID + has a
  live owner (job running / in `_LIVE`) ⇒ NOT flagged; (b) running + alive-PID + NO live
  owner ⇒ `kill`; (c) dead PID ⇒ `reap_dead`, no banner. A legit lane-job session is
  never listed by `orphan_check`.
- **SIGN-OFF:** on gwl-server, after an elevated restart, a real attached swarm does NOT
  raise the banner while a genuine orphan still does. (User-driven; the design no longer
  depends on it.)

## Wave 3 — Resume backend keystone (Pillar A) ⭐
- **#6 backend** When `_build_continue_seed` (`anchor_gui.py:1330-1408`) finds no registry
  record / cached summary (a discovered/brownfield effort), **synthesize a seed from
  on-disk docs**: detect lane/phase, enumerate the available documents, select the right
  skill, and assemble an orienting summary. **#3 data:** fold discovered efforts into the
  effort-view grouping (`effort_view.build_effort_view` / `_gather_project_sessions`) so
  they become first-class members, not loose singletons.
- **STUB GATE:** given a temp project with discovered docs and NO registry/summary,
  `_build_continue_seed` returns a NON-empty seed containing the doc list + chosen skill
  + detected phase; `build_effort_view` groups the discovered effort as a member (not a
  `loose::` singleton).
- **SIGN-OFF:** none (pure backend).

## Wave 4 — Resume UI + efforts list (Pillar A/B · UI)
- **#6 UI** Give discovered effort cards a real "resume as session" affordance (today
  `:2133` only opens the artifact) that drives `start_session` with the W3 synthesized
  seed. **#3 render** Always show the latest effort per lane inline + a "previous efforts"
  expander when >1 (`_render_lane_sessions:4006-4036`, `_render_layoutd_zone:3231-3269`),
  on the research lane and the main workbench too.
- **STUB GATE:** the project-window render includes a resume control on a discovered card
  and a "previous efforts" expander when a lane has >1 effort (assert on the HTML).
- **SIGN-OFF (Playwright + screenshot):** clicking an OLD/brownfield effort opens a WARM
  session — Crucible loaded, the planning docs read, a summary orienting the turn — NOT a
  cold terminal. (The dogfood: THIS effort's docs resume warm.)

## Wave 5 — UI quick-fixes: deliverables collapse + terminal width (Pillar B · UI)
- **#4** Wrap `render_deliverables_html` (`anchor_gui.py:10095-10182`) output in
  `<details>` so deliverables start collapsed.
- **#8** `width:100%` on `.panel .pin` (`4694-4695`) + call the xterm `fit()` on panel
  open so a terminal fills its column immediately, not only after maximize→restore.
- **STUB GATE:** the deliverables HTML contains a `<details>` wrapper (collapsed by
  default); the panel CSS carries `width:100%` and the open path invokes `fit()` (assert
  on the emitted HTML/JS).
- **SIGN-OFF (screenshot):** deliverables render collapsed; a freshly-opened terminal
  spans the full column width.

## Wave 6 — Terminal controls unification (Pillar A/B · UI) — depends on W3/W4
- **#5/#13** A session panel's controls become: `–` minimize · `×` close = **stop the
  PTY + preserve worktree + keep the registry record (resumable via W3/W4)** · one
  **`Kill→Boneyard`** (archive + reap, better icon). Remove the redundant `🗑` `.hardkill`
  and `✕` `.delete` (`anchor_gui.py:4705-4722`); update JS listeners + CSS selectors in
  lockstep. (No OS process suspension — `×` performs a graceful stop, not `SuspendThread`.)
- **#5/#13 durability (W6 amendment) — close must be WARM-resumable, not just worktree-
  preserving.** Build-time discovery: `_build_continue_seed` reads cache/main-persisted
  docs ONLY (never the worktree), and the boot orphan-reaper deletes a no-live-PTY
  worktree on restart — so a bare "preserve worktree" close reopens COLD and loses the
  work. Therefore `close_session` MUST, before returning: (a) `capture_session_docs(...)`
  to persist produced docs to main (like `kill`) so they survive the boot reaper and the
  resume seed can read them; and (b) schedule the same best-effort/idempotent
  session-summary hook `finish`/`kill` use, so `_build_continue_seed` finds a cached
  summary and the W3 resume opens WARM. Also teach `worktrees.reap_orphans` + its boot
  caller (`anchor_gui.py:~18243`) to KEEP worktrees whose registry record is
  `STATUS_IDLE` (parked/reopenable), not only those with a live PTY.
- **STUB GATE:** after `×`, the session's PTY is reaped BUT the worktree + registry record
  persist (status reopenable), and a subsequent resume reopens it via W3; the panel
  exposes exactly close-`×` + `Kill→Boneyard`; `Kill→Boneyard` reaps + archives to the
  boneyard index. **PLUS (amendment):** the REAL `_build_continue_seed` (not a hand-fed
  `seed_context`) yields a NON-EMPTY warm seed for the closed managed session; close
  persists the session's docs to main (they survive a simulated reaper pass); and a
  `STATUS_IDLE` worktree is NOT removed by `reap_orphans`.
- **SIGN-OFF (Playwright + screenshot):** every panel shows two controls; `×` then reopen
  carries on warm; no second destructive control; no orphaned PTY after `×`.

## Wave 7 — Model-switch handoff (Pillar A/C)
- **#9** `switch_engine` (`terminal_session.py:756-826`): before reaping, generate a
  **best-effort, 5-second-timeout-bounded** session summary; write a git-ignored
  `SWITCH-HANDOFF.md` into the worktree and pass it as `seed_context` to the new engine;
  fix the hardcoded "promoted from Grass Catchers" seed label (`:228-231`,`:840`). A
  wedged source engine must NOT block the switch (timeout → skip summary, proceed).
- **STUB GATE:** a switch with a healthy stub writes `SWITCH-HANDOFF.md` (git-ignored) and
  seeds the new engine with it; a switch whose summary stub hangs past 5 s still completes
  the engine swap (summary skipped); the seed label is not "promoted from Grass Catchers".
- **SIGN-OFF:** switching engines mid-session visibly carries context into the new engine.

## Wave 8 — Model-flexible execution at the skill layer (Pillar C)
- **#10 (locked decision)** Confirm `DEFAULT_ENGINE=claude` on Windows; detect
  `agy-dispatch` availability; surface the 5:1 split in the session UI; implement
  **honest single-subscription fallback** — both subs → Claude driver + skill-driven
  Gemini swarm; Claude-only → Claude everywhere, NEVER spawn agy/Gemini; Gemini-only →
  research + Gemini-runnable lanes, plan/build show an honest "requires Claude" state
  (`lanes.py:56-69`). The 5:1 fan-out lives in the skills, not the `job_runner`.
- **STUB GATE:** the engine-selection function, given a Claude-only host profile, returns
  a plan that spawns NO gemini/agy process; given a Gemini-only profile, plan/build
  resolve to a "requires Claude" status (not a crash); given both, the default driver is
  Claude with Gemini available for swarm.
- **SIGN-OFF:** the UI shows the split + the honest fallback states.

## Wave 9 — Gandalf map-reduce (Pillar B) — depends on W8
- **#2** Replace the single Stage-A pass with a real **map-reduce**: shard the target
  tree, fan out parallel reads via the W8 substrate (agy-dispatch / job_runner), reduce
  into graded, grouped findings; add an in-progress/queued indicator while the index is
  `ok:false` (`gandalf.py`).
- **STUB GATE (stub runner):** a Gandalf run shards the tree into ≥2 shards, dispatches a
  read per shard, and the reduce step emits grouped findings (≥1 per shard); the index
  exposes an in-progress state before completion.
- **SIGN-OFF:** a live run over a large tree (e.g. `C:\dev`) returns non-trivial, grouped
  findings (not a thin single-pass), with visible progress until ready.

---

## Cross-cutting (every wave)
- Extend the stubbed healthcheck surface for the wave; never touch live `:8777` / real
  data. UI/live behaviors go to the SIGN-OFF lane (Playwright + screenshot), per the v4
  rule — Playwright stays a dev-only `pytest.importorskip` dependency, never in product.
- Update `CLAUDE.md` for any new endpoint/behavior (the project's standing rule).
- Each Foreman wave writes its run summary into this planning folder (meta-requirement).

## Foreman handoff
`MASTER-PLAN.md` (description) + this file (plan) + `EXECUTION-LOG.md` (execution log)
form the doc-trio named in `foreman.config.json`. Stage 2 gates the handoff on
`node foreman/bin/locate-plan.mjs --json <dir>` (exit 0).
