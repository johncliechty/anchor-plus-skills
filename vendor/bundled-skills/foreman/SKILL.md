---
name: foreman
description: >-
  Autonomous multi-wave build orchestrator. Invoke inside a project folder that
  has frozen design + implementation-plan docs to drive each wave/sprint/section
  to done via fresh-context sub-agents in an EXECUTE -> ADVERSARIAL-REVIEW -> FIX
  -> RE-REVIEW loop, auto-advancing across waves and halting only on a defined
  blocker set. STATUS (2026-08-24): PRODUCTION — ~15 real builds shipped; the
  ground-truth test gate is run by the orchestrator (a Node process), never by a
  sub-agent. One consolidated status block lives in the body below; verified
  currency lives in the foundry PLAN.md, never in this line.
---

## North Star (LOCKED — John, 2026-08-25)

Given a frozen plan, Foreman drives every wave to verified done — fresh-context executors, adversarial review, ground-truth gates run by the orchestrator, never a sub-agent — halting only on defined blockers and never burning the user's attention between gates.


<!-- ELEGANCE-LAW v2 -->
## The Elegance Law (locked by John — binding on this skill)

Canonical text: `Skill Foundry/ELEGANCE.md`. Applies to ANY agent running this
skill on ANY host. If this block and a longer procedure below disagree, this
block wins.

1. **Approvals are ≤200 words** — what changes in his world, the recommendation,
   the one thing that gets worse. The artifact stays on disk and is named, not
   pasted. An approval obtained with a longer block is VOID.
2. **Summaries are ≤150 words** — goal in one line, done / not done, ≤3 findings
   ranked by consequence, the single next decision. Never rounds, waves, seats,
   stamps, gate counts, or file inventories.
3. **Default to the lightest band, without asking.** A heavier tier requires the
   first status line to NAME its trigger: irreversible or externally visible,
   inputs unconverged, a prior failure in this exact area, or he asked for it.
4. **Needed-because line.** Any element he did not request carries one line:
   "Needed because ___; dropping it costs ___." No line, no element.
5. **Show a cut.** ONE dry round ends a review loop — never a streak. Every plan
   names something it removed; "nothing cut" is said aloud.

**THE VERIFICATION LAW** (added 2026-08-15 after its FOURTH recurrence — each of
the first three was written into a journal and recurred anyway):

6. **Verify the claim you actually made, on the surface he actually uses.**
   "It's live / fixed / renders" is a claim about HIS screen. That the server
   emits new bytes, that a build exited zero, or that assertions passed are
   claims about something else. Render it and look at it.
7. **A symptom reported twice retires the first explanation.** Test the
   hypothesis; never repeat it. An explanation that makes his report false
   ("it's your cache", "it's a data issue") needs MORE evidence, not less.
8. **Prefer a mechanism to an instruction.** If the same instruction is given
   every session, the instruction is the defect — build what removes it.
9. **A correction that lives only in a journal or a memory has not been made.**
   Promote it to where it is loaded BEFORE the work starts.

**Two laws these serve.** A gate that cannot see what the user sees is not a gate
— structure diffs are lints, and must be labelled as lints. And a guardrail is
never the whole product of a turn — if enforcement withholds output he already
paid for, show it anyway.
<!-- ELEGANCE-V2.1 addendum -->
**What elegance IS (researchPrime-vetted, 2026-08-15):** the largest result
carried by the least machinery its user can actually hold — every element
forced by an INDEPENDENT citable need, nothing present the objective does not
pay for. Earned by iteration, never by skipping work: as simple as the task
allows, no simpler than a single datum permits.

**The Rabbit-Catcher (canonical battery: `ELEGANCE.md` Part II, ships with
the bundle):** the steering seat runs the full RC battery at PLAN APPROVAL
and on any NEW mid-run element; round boundaries ask only RC-6 ("still on the
critical path?"). Uncertain ⇒ PARK the element (zero further spend) + one
batched line in the next block the user already reads — never silent pursuit,
never ad-hoc interruption. Needs and hazards must be independent of their
proposer (no self-authored justification records); malleability work is
never cut as "unused capability"; guards are judged by RC-G, never by
retirement. Verdicts: KEEP / HOLD (with written trigger or budget) / CUT
(logged).

**THE SPEAKING LAW (John, 2026-08-16 — ELEGANCE.md Part III):** every ask,
HALT, or summary this skill puts to the user describes the DECISION, never
the machinery (a gate ask took FOUR attempts because it kept narrating waves
and gates); a few plain sentences carrying the two-three details that matter
+ where the full detail lives; genuinely complicated content goes in NUMBERED
BATCHES, one at a time, each ending "OK so far?"; no seat/stamp/gate
vocabulary in the sentence the user must read; every ask ends with a question
answerable in one word AND carries a recommendation (what you would choose +
one line of why + alternatives when the choice has them + "or tell me
something else" — options are a convenience, never a cage).
<!-- /ELEGANCE-V2.1 -->
<!-- /ELEGANCE-LAW -->


> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol.

# Foreman

Autonomous multi-wave build orchestrator (working title "code-execution-organizer").
Foreman is a Claude Code **skill** invoked in a project folder. Given that
project's *frozen* design + implementation-plan docs, it drives each
wave/sprint/section to done through fresh-context sub-agents, auto-advances to
the next wave, keeps the tree clean, prints running commentary, and **halts only
on a defined blocker set**.

> **Tier definition (Heavy vs regular · stakes-gated cross-model · seat mapping) + invocation
> discipline (zero deliberation · the LOCKED global status table · run capture):** canonical in
> `AGENTS.md` (Foundry root on the author host; your install root in a distributed bundle) → "Skill tiers" / "Invocation discipline" / "Run capture".
> Trio build tier: `TRIO_TIER=heavy|standard` (standard is the build default). Do not re-define
> or deliberate any of it.

> **Status (2026-08-24, consolidated — the ONE status block; verified currency lives in
> `Skill Foundry/PLAN.md`): PRODUCTION — ~15 real builds shipped** (aurora,
> researchPrime-upgrade, ramanujan, the Anchor rearchitecture 20/20 waves, most Foundry
> skills). Suite: `node --test "test/*.test.mjs"` (the bare directory form false-fails on
> fixture subdirs). The ground-truth gate is orchestrator-run (unforgeable); the JUDGE is a
> pure function, not an agent. Operationally hardened through 2026-07: async gate with
> per-minute heartbeat + on-disk plan rebind each iteration; classified gate timeouts
> (`[taxonomy:gate-timeout]`, child-tree kill, never a fake RED); per-wave scoped gates
> (0086); halt taxonomy prefixes on every reason; `review:degraded` honest seat-dropping
> (gate stays ground truth §5); EXECUTION-LOG.md orchestrator-appended on every GO.
> **Halt recovery:** `--clear-halt` on a vacuous halt is REFUSED unless code landed;
> `--clear-halt --force` re-enters EXECUTE with eyes open; a PLAN-AMENDMENT clear
> re-enters EXECUTE at iteration 0; resume re-proves GREEN.
> **NEVER run `git clean -fd` in a Foreman workspace** — two total-project-loss
> events (journals 0013/0042). Non-convergence uses `git stash` (recoverable);
> untracked deliverables are exactly what `git clean` destroys.

## What Foreman is / is NOT

- **Is:** a loop that takes a frozen plan and drives it to done wave by wave —
  EXECUTE -> ADVERSARIAL-REVIEW -> FIX -> RE-REVIEW until convergence, then
  auto-advance, with logging, hygiene, commits, and running commentary. **(built — see `bin/`)**
- **Is NOT:** a planner. It never invents requirements, refactors for taste
  outside the plan, or makes reserved architectural calls — those are **halts**.
  This anti-scope-creep contract is its most important property.

## Topology (the load-bearing rule)

Do **not** parallelize code-writing — coding is the least-parallelizable task and
parallel coders make conflicting implicit decisions (Anthropic + Cognition both
agree; see `research1-out/.../01-report.md` F1/F2).

| Phase | Topology |
|---|---|
| EXECUTE | single-threaded linear agent per wave; compress when long |
| REVIEW | `REVIEWER_COUNT` (default 2) independent reviewers, **CONCURRENT** (default on), read-only, prompted to refute; **stakes-gated** — ordinary clean mid-run waves run 1, the full panel runs on the terminal wave / after fix iterations / `FOREMAN_FULL_REVIEW=1`; skipped entirely on RED intermediate iterations (the gate artifact IS the fix guidance) |
| FIX | single-threaded linear agent |
| JUDGE | a PURE FUNCTION (0 model calls); the **orchestrator-run ground-truth gate dominates** (§5) |

`REVIEWER_COUNT` is one config var (default 2) — never hard-coded.
Independence comes from separate sub-agent calls, never multi-persona-in-one-generation.

---

## §4 — Invocation / contract (the confirmation flow)

On invocation, Foreman resolves the contract and **states it back for the user
to confirm before building**. The deterministic, no-guess part is implemented in
`bin/locate-plan.mjs` (which uses `bin/foreman-lib.mjs`):

```
node foreman/bin/locate-plan.mjs [projectDir]      # human-readable contract
node foreman/bin/locate-plan.mjs --json [projectDir]
```

Exit codes: `0` contract resolved · `3` HALT-for-human · `2` internal error.

1. **Project folder** (cwd) is the project proxy.
2. **Frozen docs** — locate + state back the *description*, *implementation
   plan*, and *execution log*. Resolution is no-guess:
   - an explicit `foreman.config.json` `{ "docs": {...} }` wins; else
   - a case-insensitive heuristic glob over top-level `*.md`.
   - **0 candidates for a role -> HALT (missing).** **>1 candidate -> HALT
     (ambiguous; ask, never pick).** Foreman never guesses which file is the plan.
3. **Wave parsing** — waves are read from an explicit `## Wave N` heading
   (`## Sprint N` / `## Section N` accepted as aliases) in the plan doc. Headings
   inside code fences are ignored. Wave numbers must be **contiguous 1..N**.
   - **No parseable wave structure -> HALT.** Foreman never infers wave boundaries.
4. **Test discovery** — the build+test (gate) command, from the plan first
   (`test-command:` / `build-and-test:` / `gate-command:` line), else the project
   manifest (`package.json` `scripts.test` -> `npm test`; `pyproject.toml` with
   pytest -> `pytest`).
   - **No ground-truth test command found -> HALT** ("no ground truth -> cannot gate").
5. **Project-DONE definition** — DONE = the last parsed wave GREEN (via the
   orchestrator-run gate) **and** any plan-level acceptance gate met. Foreman
   emits a final-state verdict and stops; it does **not** loop past the last wave.
6. **Budget** — `{max waves this run, max fix-iters/wave (default 4), max
   wall-clock}`; the Workflow `budget` token target is a secondary guard. **(enforced as a hard pre-flight gate)**
7. **Ambiguity gate (the linchpin).** Before acting, each execute/review agent
   must emit `answerable-from-frozen-docs: yes/no + cited plan line`. A `no` is a
   **HALT** (§6.4), never an autonomous decision. This is what makes "no
   babysitting" possible without scope creep. **(implemented: the execute/review
   agent prompts emit the gate; the engine cannot weaken it.)**

---

## §5 — Judge arbitration + the trusted ground-truth gate (reward-hacking fix)

**Evidence precedence:** OBSERVED test/command output -> reproduced execution
data -> directly-read authoritative source -> theory/argument.

- **The gate is run by the orchestrator, not by a sub-agent.** The deterministic
  Workflow step executes the build+test command, captures exit code + stdout/stderr
  to a **gate-artifact file that sub-agents cannot write**; the judge reads only
  that artifact. Sub-agent-pasted "command output" in a wave log is **never** the
  gate of record. (Closes the forge-the-output hole.) **(implemented in `bin/wave-engine.mjs` `runGate`)**
- **Anti-test-weakening:** snapshot the test inventory + assertion/skip count at
  wave start. A wave that reduces test count/coverage or adds `skip`/`xfail`
  without an explicit plan citation is an **automatic HALT**, not a downgradeable
  finding.
- **Vacuous-GREEN guard:** if the GREEN gate does not execute any artifact this
  wave changed (coverage-of-changed-files check), it is **not** a GO — HALT as
  "gate proves nothing about this wave."
- **Judge rules:** a GREEN gate outranks reviewer prose; to block GREEN a
  reviewer must produce a **failing repro command + output**. The judge may HALT
  on missing required tests; it may not override passing real output with argument.
- **Anti-sycophancy:** reviewers run read-only, are prompted to **refute**, cite
  `file:line` or `command+output`; a **BLOCKER requires >=2 independent reviewers
  to agree**.
- **Finding identity:** every finding carries a stable id (`file:line + rule`);
  convergence = zero open BLOCKER/MAJOR with verified closure; a fix that closes
  A but opens B is tracked to prevent false convergence / oscillation.

---

## §5b — The DELTA-COVERAGE gate (`bin/delta-coverage-gate.mjs`, journal 0091)

**A wave that adds a SURFACE and ships zero tests is a BLOCKER, not a nit.**

Why this is its own gate: a green suite is not evidence that a wave is covered.
Foreman built a subsystem GREEN that delivered **8 HTTP routes, 13 functions and
~670 lines with not one test file mentioning it** — and the existing suite stayed
green *precisely because* the new code was untested. So "0 tests for 670 new lines"
and "full coverage" produced the same verdict. Six real defects were found later,
by reading.

**Enforced in engine (journal 0092):** after vacuous-GREEN passes and before
`finishGo`, `wave-engine.mjs` runs `checkDeltaCoverage` on the wave's changed
files + test-file text; writes `.foreman/wave-N-delta-coverage.json`; **HALTs**
when a surface is uncovered. Soft-skip only on unexpected throw (never silent
suppress of a real fail). Sibling of Crucible's property-gate emit (0080/0081).

Run `checkDeltaCoverage({changedFiles, testMentions})` per wave:

1. **Delta, not percentage.** The unit is *what this wave added*. A global coverage
   % is gameable and stays comfortably green while an entire subsystem is bare —
   which is exactly how this happened. An unrelated test in the same wave does not
   satisfy the gate.
2. **Surfaces are:** HTTP routes, handlers, CLI verbs, persistence paths, frontend
   entry points. Adding one obliges a test that *names* it.
3. **Honor the repo's own convention.** Where a repo has stub gates
   (`tests/test_<subsystem>_<wave>.py`), a new subsystem without one is an
   INCOMPLETE wave — check for the convention rather than assuming a global suite.
4. **Emit the wire-up assertions by default** for any wave adding routes (static
   text checks, no server boot — roughly five tests): every route reaches a handler
   that exists; every handler is reachable; every endpoint the frontend calls is
   declared; every route carries its expected auth policy; each failure path returns
   its documented status code and text.
5. **Failure-path tests assert the USER-VISIBLE TEXT,** not just a non-crash. The
   recurring defect in this family of work is a *confident wrong answer* — "no
   projects", "queue 0" — which a happy-path test cannot see.
6. **No fixed-rate poller against an endpoint that spawns a process** — it ships with
   visibility gating and failure backoff, or it does not ship.

## §6 — Halt-for-human conditions (the only things that wake you)

1. Budget / iter / wall-clock cap.
2. Verdict **NO-GO**.
3. **Non-convergence** (`MAX_ITERS`, default 4, no GO) — `git stash`/branch the
   failed attempt and record the ref so the tree is left clean and recoverable.
4. **Ambiguity / new-requirement / plan-deviation** — any
   `answerable-from-docs: no` (§4.7), or a wave diff with no traceable plan basis.
   - **`PLAN-AMENDMENT-PROPOSAL` (sub-type).** When a build-time discovery shows
     the *frozen plan itself* is wrong/incomplete for the current wave (an
     assumption falsified, an API not behaving as the plan assumed) — distinct
     from mere ambiguity above — a review/execute agent may attach a concrete
     proposed resolution: a **proposed diff** to the plan doc **plus a rationale**.
     This is **still a HALT** — no silent re-planning. Foreman records the proposal
     in the checkpoint `pending_action` for one-click human approval; on approval +
     resume the bounded amendment is applied (or recorded as applied) and the wave
     continues. The human stays in the loop and must approve before any plan change
     takes effect; the §4.7 ambiguity gate and every §5 guard are unchanged. F3
     only attaches a resolution to a halt that would otherwise be bare.
5. **Unrecoverable error** — can't verify a load-bearing claim; repo in bad
   state; an irreversible action's gates didn't both verify; invalid/torn
   checkpoint on resume (§8).
6. **Test-integrity / vacuous-GREEN** halts (§5).

On every halt: write the checkpoint (§8) with the **exact recommended next
action** in `pending_action`. In Phase 0, the `bin` CLIs signal a HALT with
**exit code 3** and a `HALT: <reason>` line on stderr.

---

## §8 — State, durability, resume (zero context bloat)

- Sub-agents communicate via **file paths**, never by dumping transcripts into
  the orchestrator. **(implemented)**
- **Per-wave logs + gate artifact:** the orchestrator-written gate artifact is
  `.foreman/wave-<n>-gate.json` (`written_by:"orchestrator"`); the judge reads
  only that. **(implemented)**
- **Canonical checkpoint `foreman-checkpoint.json`** (project root). Schema
  (implemented in `bin/foreman-lib.mjs`, exercised by `bin/checkpoint.mjs`):

  | field | type | notes |
  |---|---|---|
  | `plan_path` | string | absolute path to the plan doc |
  | `current_wave` | number | 1..N |
  | `total_waves` | number | parsed count |
  | `intra_wave_step` | string | `execute`\|`review`\|`fix`\|`judge`\|`gate`\|`done` |
  | `iteration` | number | fix<->review iteration within the wave |
  | `reviewer_count` | number | default 2 |
  | `budget_remaining` | object | `{waves, fix_iters, wall_clock_min}` |
  | `last_verdict` | string\|null | `GO`\|`NO-GO`\|`HALT`\|null |
  | `last_commit` | string\|null | HEAD at last checkpoint |
  | `open_findings` | array | `[{id, severity, file, line, rule, status}]` |
  | `pending_action` | string\|null | exact recommended next action on halt |
  | `stash_ref` | string\|null | non-convergence stash/branch ref |
  | `status` | string | `running`\|`halted`\|`done` |

- **Atomic writes:** serialize -> write `<file>.tmp` -> `fsync` -> atomic
  `rename` over the destination. A torn write can never replace a valid file.
- **On resume, if the JSON is invalid (torn) or breaches the schema -> HALT.**
  Never best-effort-parse a torn file.
- **Resume reconciliation (Phase 2):** compare `git rev-parse HEAD` to
  checkpoint `last_commit`; if HEAD is ahead, adopt HEAD and skip the re-commit
  (prevents double-apply). Intra-wave resume uses `intra_wave_step`.

CLI (Phase 0):

```
node foreman/bin/checkpoint.mjs new <file> --plan <path> --waves <N> [--reviewers K]
node foreman/bin/checkpoint.mjs read <file>          # HALT (exit 3) on torn/invalid
node foreman/bin/checkpoint.mjs roundtrip <file> --plan <path> --waves <N>
node foreman/bin/checkpoint.mjs dashboard <file>     # render §10 block
```

---

## §10 — Running commentary (best-effort telemetry)

Suppress sub-agent transcripts; narrate via `log()` / status line. Token %,
context fill, and rate-window status are **best-effort with graceful fallback**
(the harness exposes no live quota API; window status is derived reactively from
observed 429s, e.g. `window: OK` / `throttled @ HH:MM`). Rendered by
`renderDashboard()` in `bin/foreman-lib.mjs`:

(Sample dashboard rendering moved to `HUMAN.md` — 2026-08-24 elegance sweep.)

---

## Files in this skill

**Engine (Node — the orchestrator + gate live here, never in a sub-agent):**
- `bin/foreman-lib.mjs` — parsers + state primitives: `locateDocs`, `parseWaves`,
  `discoverTestCommand`, `projectDoneDefinition`, checkpoint schema + atomic
  `writeCheckpointAtomic`/`readCheckpoint`, `makeBudget`, `renderDashboard`.
  Recoverable refusals throw `HaltError`.
- `bin/wave-engine.mjs` — the one-wave engine (`runWave`): EXECUTE -> orchestrator
  GATE -> sequential REVIEWERS -> JUDGE -> bounded FIX -> re-gate, with all §5
  guards (real-tests-ran GREEN predicate, anti-weakening, vacuous-GREEN, finding
  identity). Language-aware gate for Node `--test` and `python -m pytest -v`.
- `bin/project-engine.mjs` — multi-wave auto-advance (`runProject`): ascending
  truth-gated advance, project-DONE, budget pre-flight, wave/intra-wave/git resume.
- `bin/delta-coverage-gate.mjs` — §5b: classifies a wave's changed files, flags any
  SURFACE (route / handler / CLI verb / persistence path / frontend entry) that no
  test names, and returns a **BLOCKER**. Pure predicates over a file list — no git
  spawn. `renderDeltaCoverageRequirement()` emits the wave text. **Wired into the
  live GO path** in `wave-engine.mjs` (journal **0092**).
- `bin/git-hygiene.mjs` — §9 git hygiene: dedicated work branch, commit-only-on-GO,
  dirty-tree HALT, repo-boundary containment, crash reconciliation. Never pushes.
- `bin/wave-workflow.js` — the production driver seam: `makeAgentDriver({agent})`
  turns an injected `agent()` (Workflow `agent()`, the Agent tool, or a headless
  `claude -p` child) into the engine's {execute, review, fix} steps.
- `bin/drivers/scripted-driver.mjs` — deterministic no-LLM driver used by the tests.
- `bin/locate-plan.mjs`, `bin/checkpoint.mjs`, `bin/run-wave.mjs`,
  `bin/run-project.mjs` — CLIs (contract resolver, checkpoint IO, single-wave and
  whole-project runners).

**Why a Node process, not a Workflow script (design finding L):** a Workflow-tool
script has no filesystem/process access, but §5 requires the orchestrator to spawn
the test command and write a gate artifact sub-agents cannot forge. So the
orchestrator + gate + state live in this Node engine; the Workflow tool / sub-agents
drive only the model steps via the `agent()` seam.

**Tests & fixtures:** `test/*.test.mjs` (106 passing), `fixtures/canonical-project/`
(Node, ships red), `fixtures/py-canonical/` (pytest, ships red), and the
`test/neg-*` HALT cases.

## How to invoke

> **⏱ STATUS UPDATES TO CHAT — the launch pattern that makes the 10-min rule actually fire
> (2026-07-11 fix).** A Foreman build runs for hours. If a driving session launches the engine as a
> BLOCKING foreground call, the session is frozen for the whole run and CANNOT post updates — that is
> why status cadence silently goes dark. So whenever a Claude session drives a build:
> 1. **Launch the engine in the BACKGROUND** (Bash `run_in_background: true` — or `go.ps1` spawned
>    detached), NEVER a foreground call. The launch returns immediately and the session stays free.
> 2. **Arm the cadence at launch** — `ScheduleWakeup` (~600s) or `/loop 10m`, the moment the run starts.
> 3. **Each tick, relay — shell-free:** the engine writes the LOCKED Status table to
>    `<projectDir>/_foreman-status.log` at t=0, every ~10 min, and on halt/done. READ its tail with the
>    Read tool (never spawn a shell) and POST the latest status to chat in the LOCKED Status-table format —
>    canonical definition in ONE place: the canonical `AGENTS.md` → "Long-run progress updates"
>    (`[HH:MM]` header · Effort/Doing/Status/Tests/Blocker/Procs/**Journal** rows · ETA + To do footer).
>    The **Journal** row (mandatory, `none` when empty) recaps everything journaled since the last tick —
>    the engine log is the data source; the SESSION composes the Journal row from `journal/`.
>    The chat window is the PRIMARY channel (global AGENTS.md); the log is the data source.
> 4. **Stop the cadence** when the checkpoint `status` flips to `halted`/`done`, or the background task
>    notifies completion. The engine's own timer is the fallback if the session misses a tick — but only
>    the session can reach chat, so the background+relay pattern is mandatory, not optional.

1. **Resolve the contract first.** From the project folder, run
   `node <skill>/bin/locate-plan.mjs .`. If it prints `HALT:` (exit 3), fix the
   named problem (add the missing doc, add `## Wave N` headings, declare a
   `test-command:`) and re-invoke — Foreman never proceeds on a guessed contract.
2. **Dry-run the engine deterministically** (no LLM, reproducible) with the
   scripted driver: `node <skill>/bin/run-project.mjs <projectDir>` (add `--git`
   for commit-on-GO, `--max-waves`/`--max-wallclock-sec` for a budget cap,
   `--resume` to continue from a checkpoint).
3. **Drive it with live sub-agents** using the robust wrapper script:
   `powershell -File <skill>/bin/go.ps1 -Project <projectDir> [-Resume]`
   The script automatically handles stale locks and executes through the backend registry (every subscription driver: `claude`, `chatgpt-cli`, `grok-cli`, `gemini-cli`). Seats come from the **Anchor dashboard** (`coding_family` → execute/fix, `review_family` → review; Anchor data-dir `settings.json` → `~/.anchor/model_prefs.json`) — a `TRIO_DRIVER` env is a per-run override, never the source. The wrapper also requires `$env:CRUCIBLE_AGENT_LIVE="1"` to allow live billable agents.
4. **Per-role model routing (the coding family codes, the review family reviews — whatever the dashboard selects; 2026-09-04).**
   The dashboard prefs seat every role by default. To pin MODELS per role for one project, add a `"models"` block to the project's `foreman.config.json` (the example shows a gemini review seat; use the driver of the family the dashboard selects):
   ```json
   { "models": { "execute": "claude:claude-fable-5", "fix": "claude:claude-fable-5", "review": "gemini-cli:gemini-3.1-pro" } }
   ```
   `run-live.mjs` exports each entry as per-role env (`CLAUDE_MODEL_<ROLE>` for claude;
   `TRIO_DRIVER_<ROLE>` + `TRIO_MODEL_<ROLE>` for another backend) and both driver
   ladders resolve them (`resolveClaudeModel` / `resolveGeminiModel`; explicit env
   always wins over config). The run header logs the resolved routing
   (`model routing: execute=… · review=… · fix=…`) and every call's served model is
   attested per SR-5 — check both when verifying a routing change.

## Standing rules (sleep-cycle promotion 2026-08-15 — journals 0093/0099/0100/0101)

- **A GO with `last_commit: null` HALTs.** The EXECUTION-LOG append is part of
  the GO transaction, not a courtesy; a checkpoint from a foreign project is
  refused, never adopted; the gate refutes the reviewer — a reviewer verdict
  that contradicts the orchestrator gate loses. (0093)
- **A test that enters through a different door than the human proves the
  wrong thing.** §5b proves a new surface HAS a test; it does not prove the
  surface is REACHABLE from the user's entry point — check reachability when
  the wave's deliverable is user-facing. (0099, open engine work)
- **`--clear-halt` clears a STATE, not a defect.** Its refusal check is a
  regex on halt text, not proof the remedy landed — clearing without landing
  the named remedy re-buys the same halt. (0100)
- **The gate command must be a TEST RUNNER that emits counts.** A declared
  gate that cannot count tests gates nothing; name the remedy in the halt
  text. (0088 crucible / 0101)

## Usage journal (sleep-loop feed — append after every REAL run)

At the end of any real (non-test) run of this skill, append ONE entry to
`journal/` in this skill folder as `NNNN-<slug>.md` (next number = **max(existing NNNN)+1 over the WHOLE directory** — gandalf accumulated 32 colliding ids because sessions read the low numbers as the frontier; APPEND-ONLY —
a correction is a new entry, never an edit). Keep it under ~15 lines, honest over
polished, with the 7 canonical fields (see the Skill Foundry's
`planning/portfolio-program/src/journal.mjs`): id, skill, situation, context,
observation, outcome (worked | friction | failed | refused), provenance
(genuine-execution | seeded — only genuine-execution corroborates).
No journal entries → the sleep loop has nothing to learn from.

**Auto-capture (2026-07-11):** `bin/run-live.mjs` now writes the machine-readable training
record to `journal/runs/<ts>.json` AUTOMATICALLY at the end of every run (project, params,
per-wave outcomes, halt reason, tier, duration — the AGENTS.md "Run capture" standard) and
emits the LOCKED global Status table to the status log at t=0, every ~10 min, and at
completion. The human NNNN entry above is for LESSONS — write one when a run taught you
something; the mechanical record is already handled.
