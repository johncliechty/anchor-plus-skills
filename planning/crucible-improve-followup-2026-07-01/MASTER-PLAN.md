# Master Plan — Crucible-Improve Follow-up (live-use fixes, 2026-07-01)

## North Star
Close the three real gaps John found while dogfooding the just-built
crucible-improve (W1–W9) branch, WITHOUT regressing anything that already works.
Three fixes, three waves, each truth-gated by the full pytest suite.

## Scope (exactly these three, nothing else)
1. **Claude-first session launch.** All dashboard session-launch controls must
   open on **Claude** by default (honoring the locked model policy: Claude is the
   default engine; the 5:1 Claude-orchestrates-Gemini split lives at the
   skill/session layer; Foreman/build code-writing is pinned to Claude). Today the
   JS launch controls hardcode `backend:'gemini'`, which (a) opens research in
   Gemini and (b) causes the researchPrime seed to land on a Gemini PTY that can't
   load a Claude Code skill — so researchPrime never auto-loads. Fixing the launch
   engine fixes both symptoms together.
2. **Unified dock controls.** The v12 bottom dock still carries the pre-W6 control
   shape — a `✕` close PLUS a separate red `✕` true-delete PLUS a text
   "Kill → Boneyard". Collapse it to match the W6-unified inline panel: exactly
   `×` (graceful close, keeps the effort) + `🪦` (the ONE destructive
   Kill → Boneyard). Remove the redundant second `✕` true-delete.
3. **Bridge job cost onto the effort record.** Time/tokens/spend read all-zero
   because the only writer of the effort `cost` block (`finalize_effort` →
   `attach_cost`) has no production caller; the runner captures real cost onto the
   *job* record but never bridges it to the *effort* pointer-record the rollups
   read. Wire that bridge for one-shot `launch_lane` jobs.

## Constraints
- Python **stdlib only** at runtime (pytest is dev-only). No new deps.
- The three real fixes only — no adjacent refactors, no taste changes.
- Every wave GREEN via the **orchestrator-run** full pytest gate before commit.
- The UI wave (Wave 2) additionally requires a **screenshot sign-off** from John
  before it is considered done (the standing UI-wave rule).

## Honest limitation (documented, out of scope)
Wave 3 makes one-shot `launch_lane` jobs report real cost. **Interactive ConPTY
terminal sessions** (the day-to-day sessions) transport raw PTY bytes with no
stream-json `result` envelope, so there is no machine-readable token/cost to
capture for them — they will continue to contribute 0 to the rollup. Giving those
sessions real metrics needs a separate mechanism and is NOT in this effort.
