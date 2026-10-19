# Shark-Tank — Round 1 Synthesis (Crucible Stage 1)

> 3 cross-model Sharks (Gemini) refuted the Master Plan against real code.
> BLOCKER = ≥2 Sharks agree. Synthesizer = Claude. User = convergence authority.
> Round 1 was NOT dry — 2 BLOCKERs, 1 verified-broken fact, 5 adopted improvements.

## CONFIRMED BLOCKER A — the #1 swarm-warning fix would neuter the zombie hunter
**Agreement: Shark 1 (Skeptic) + Shark 3 (Analyst) — ≥2, strongest of the round.**
- Both: broadening "attached" to *effort-bound + live-PID* sessions means **true
  orphans never get killed** — they also have live PIDs and registry records
  (`zombie_hunter.py:151-170`).
- Shark 3 ALSO falsified my root cause: `pty_manager._LIVE` is a **persistent**
  in-memory dict; a WebSocket disconnect does NOT remove a session from `live_ids`.
  Sessions fall out of `live_ids` **only on server restart** — and John restarts
  gwl-server regularly. So the real trigger is restart-survival, not stream-disconnect.
- **Resolution:** #1 is NOT ready to fix. It moves to **reproduce-first** (trigger the
  banner live, capture the real registry/`_LIVE`/PID state), and the fix must use a
  **genuine liveness signal** (e.g. a session heartbeat token, or RE-ADOPT surviving
  PTYs into `_LIVE` on restart) — never "effort-bound ⇒ don't warn."

## ELEVATED BLOCKER B — in-product 5:1 orchestrator violates the uniform-job model
**Raised BLOCKER by Shark 2 (Contrarian); fallback-incompleteness corroborated by
Shark 1 #7.** (1 BLOCKER vote, but it touches the North-Star clause "without changing
what Anchor is for" → elevated to a user decision, not auto-blocked.)
- `lanes.py:13-20`: "ONE uniform job primitive… no per-lane orchestration code — the
  runner is uniform." Baking a multi-agent orchestrator into Anchor's `job_runner`
  shifts it from a control surface into an orchestration framework.
- **Resolution (recommended):** the 5:1 swarm logic lives at the **session/skill
  layer** — the skill running in the terminal (researchPrime/Crucible/Foreman) fans out
  to Gemini via `agy-dispatch` (PROVEN by THIS very session). Anchor's job stays small:
  default new sessions to Claude, ensure agy-dispatch is available, surface the split,
  fall back cleanly. This is smaller, safer, and honors the North Star.

## VERIFIED FACT C — the zombie-page terminal (#12b) is structurally dead
**Shark 1 #1 (verifiable, not judgment).** `/api/rnd/zombie_terminal_start`
(`anchor_gui.py:16535-16542`) calls `start_session` with `lane="zombie"` (not a valid
lane, `terminal_session._valid_lanes`) and `project_id="__dashboard__"` (unregistered)
→ guaranteed `TerminalSessionError`/400. **Resolves the reproduce question: it's
broken.** Fix = permit a dashboard-scoped zombie lane/session (or repoint to a valid
lane+project), not "reproduce."

## ADOPTED IMPROVEMENTS
- **D — non-destructive control must truly preserve (Shark 1, top pick).** Today `×`
  keeps the PTY *running* (leaks slots); `Kill→Boneyard` *destroys the worktree*. No
  "halt but keep resumable." Refine #5/#13: `×` close = **suspend PTY + keep
  worktree/record (resumable)**; one `Kill→Boneyard` = permanent archive+reap; drop the
  redundant `🗑`/`✕`. (Satisfies John's "too many Xs" AND Shark's no-leak/no-forced-
  destroy.)
- **E — #7 simpler fix (Shark 3 #4).** "Bytes since seed" is fragile: the PTY buffer
  caps at `MAX_BUFFER_CHARS` and truncates the front, so the greet marker is lost in
  long sessions. Just **raise the budget (~1 MB)** and/or discount a fixed seed
  allowance.
- **F — #9 must not block on a summary (Shark 1 #6).** If the engine is wedged/crashed,
  summarizing through it hangs. Handoff summary = **best-effort, timeout-bounded**; the
  switch proceeds regardless. Also gitignore the handoff doc (Shark 1 #8) and fix the
  hardcoded "promoted from Grass Catchers" seed label (Shark 3 #5).
- **G — Gandalf (#2) has no real Phase-5 dependency (Shark 2 #2).** With the 5:1 logic
  at the skill layer (B), Gandalf map-reduce fans out via the existing
  `job_runner`/agy-dispatch directly → can move earlier.
- **H — single-sub fallback honesty (Shark 1 #7).** Gemini-only users can't run
  plan/build (Crucible/Foreman are Claude-only, `lanes.py:56-59`). Fallback must
  **honestly degrade** (research + Gemini-runnable work), not silently fail.

## VERIFIED ROOT CAUSES (Shark 3 confirmed): #6, #7, #5/13, #9 all correct.
## FALSIFIED: #1 (mechanism corrected above).
