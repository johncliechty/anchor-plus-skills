# CHANGELOG — <skill-name>

> Every promoted revision (and its versioned canary set) is recorded here by the sleep
> loop. Versions are git-tagged so a regressed promotion can be rolled back to the prior
> version (NS2). Newest first.

## 2026-09-18 — shared Gate-3 ping retry; unjudged ideas if review is still down (John-approved)

- Ping bound 90s → 180s with one retry (ledger max two logical attempts). Closes the
  0063 empty halt where a live Grok seat aborted the 90s hello before any idea existed.
- After both hellos fail: generate anyway and stamp UNJUDGED, never survivors. Same
  seating/halt objects Superjump imports — no fork. Self-review seating still HALTs
  before spend. `JUMPER_GATE3_PING_TIMEOUT_MS` / `JUMPER_GATE3_PING_ATTEMPTS` override.
- Tests: `test/gate3-ping-repair.test.mjs` plus the existing ping abort-join contract
  (explicit `attempts: 1`).

## 2026-09-13 — repair card R1–R5 + lean mode (John-approved formal improvement; journals 0055–0057)

- R1 swarm look-in supervisor unwired from candidate builds; heartbeat/look-in prompt fragment
  removed from Synthesizer, Hesse, Dirac (read-only one-shot seats could never satisfy it; five
  silence-rule halts since 08-28).
- R2 startup watchdog disarms on the Gandalf DRAFT returning (`gandalf:draft:done`) or lean
  generation, never on the refuter lane; heartbeat lines carry `[+NNNs]` elapsed.
- R3 paid work never lost: round-one kills ride a thrown retry's partial; single-candidate path
  emits its built candidate on a Gate-3 halt; missing Gate-1/2 verdict → retry once → UNJUDGED.
- R4 verbatim brief into Peterson, Hesse and the grounding call (which now sees the deliverable
  and must stay proportionate); given facts declared fixed.
- R5 no ranking by analogy-mapping length; `ranking` stamp; build order kept.
- `--mode lean [--count N]`: one generation call + one attested cross-family review of the whole
  portfolio; dispatch ids `coding:lean:generate` / `gate3:lean:verdict`; run-record tier `lean-N`.
- Tests: 13 new (test/repair-card.test.mjs, test/lean-mode.test.mjs), silence-receipt rewritten
  for the unwired supervisor, portfolio ranking expectation updated; suite 55/55 (was 42/42).
- NORTH-STAR.md carries the John-approved revision block (kill-filter invariant, NG-4 by idea,
  ranking, paid work, supervision).

## v0.1.0 — skeleton
- Initialized from the Phase-0 per-skill repo skeleton (`skills/templates/skill-repo/`):
  NORTH-STAR.md, SKILL.md, references/, LESSONS.md, journal/, CHANGELOG.md.
- No lessons promoted yet.

## 2026-09-09 — notebook and model-policy maintenance

Added notebook work-product instructions.

Validation: focused source tests passed. Notebook execution, authenticated opening, and recovery require acceptance on the installation host.
