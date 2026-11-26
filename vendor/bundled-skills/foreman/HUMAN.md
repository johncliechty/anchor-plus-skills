# Foreman

**One sentence:** A multi-wave build orchestrator that executes a frozen plan wave by wave, runs real tests itself, and stops when the plan is unclear — never invents scope.

## Use this when
- You have an approved, wave-structured implementation plan (often from Crucible)
- You want autonomous build progress with gates, reviews, and a clean tree
- You need “done” defined by real tests, not by a model saying it’s done

## Do not use this when
- There is no frozen plan yet (use Crucible first)
- You’re still exploring what to build
- You need research or deep critique rather than code execution

## What you get
- Wave-by-wave and **parallel disjoint-write-set sub-wave (`W.1..W.k`)** execution: pre-execute `Anvil` AST slice → implement (isolated git worktrees for sibling sub-waves) → ground-truth test gate + deterministic fast-gates (`delta-coverage`, `Tidy-Idy` scratch hygiene, `Aegis` CWE security scan, `Anvil` AST syntax/diff check) → self-contained diff-scoped cross-family review → fast-close elegance pass
- Parallel DAG dispatch (`Writes:` + optional `Depends-On:`, default concurrency `3`) for independent sub-waves with disjoint file write-sets, merging cleanly back into parent `HEAD` before running one combined wave gate
- Pre-Wave-1 subscription CLI auth preflight (`claude`, `codex`, `agy`, `grok`) with 3rd-family verification failover, unified `onReceipt` cost/token telemetry, and SHA-256 `attested_review` manifests in `.foreman/run-record.json`
- Orchestrator-run tests and deterministic fast-gates (agents can’t fake pass/fail, and broken hygiene/security/syntax never burns reviewer tokens)
- Auto-advance immediately when the gate + fast-gates + review pass (`0` post-elegance double-review rounds); halt only on real blockers for you
- Resume from checkpoint after a stop; run the full Foreman suite anytime via `npm test` (`node scripts/run-all-tests.mjs`)

## What it is not
- Not a planner — it will not invent requirements or “improve” architecture for taste
- Not a silent scope-creeper; ambiguity is a stop, not a guess
- Not a green light for empty work (vacuous “pass” when tests prove nothing is refused)

## How to start (human)
1. Put description, implementation plan (with `## Wave N` sections and optional `### Wave N.k` sub-waves declaring disjoint `Writes:` and `Depends-On:`), and test command in the project.
2. Confirm the contract Foreman reads back before build starts.
3. Launch the run and watch status updates; act only when it halts for you.
4. On halt, fix the named issue (or approve a plan amendment) and resume.

## Limits (honest)
- No parseable waves or no test command → it will not start
- Builds take real wall-clock time; budget caps apply
- It builds what’s in the frozen plan — not what you hoped was implied

## For agents / engines
Full protocol and wiring live in `SKILL.md` next to this file (trio monorepo: `<path> Load that only when running the skill — this card is for people.

## What the running dashboard looks like (moved from SKILL.md, 2026-08-24)

```
[Foreman | <path> | wave 3/7 "MoE judge wiring"]
  ▸ execute… done (commit 1a2b3c4, 2 files)            +6m
  ▸ review (2 independent, sequential)… 1 MAJOR        +5m
  ▸ fix iter 1… closed MAJOR; re-review… GO            +4m
  ✓ wave 3 converged (2 iters) · gate 18/18 (orchestrator-run)
  → advancing to wave 4/7
context: ~38% (best-effort) · elapsed 1h12m · budget 3/8 waves · window OK
```
