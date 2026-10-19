# RELAY-HANDOFF — steward-chamber Foreman build (written 2026-08-10 07:2x)

**To the session picking this up:** you now OWN the relay for this run (run-ownership
rule: exactly one session monitors a run; the prior session — 1fe1403d, which launched
the build 2026-08-09 16:46 — has stood down its wakeup chain). Your two jobs:
(1) keep the build moving through wave 12, (2) deliver John's 10-minute status tables
RELIABLY. The prior session failed at (2) for environmental reasons — see
`C:\dev\Ecgberht\journal\0081-*.md` before you start.

## Current state (as of handoff)

- **Build:** `foreman/steward-chamber` branch, 12-wave plan at
  `planning/steward-chamber-2026-08-09/IMPLEMENTATION-PLAN.md`.
- **W1-W4 GREEN** (committed by the orchestrator, EXECUTION-LOG.md has the GO lines).
- **W5 is PROVEN but HELD:** its iter-1 gate was fully green
  (`.foreman/wave-5-gate.json`: exit 0, engine 1135/1135 + full Anchor lane) but the
  run HALTed at 06:46 on a **procedural** test-immutability guard: the fix agent
  edited `tests/fixtures/chamber/refresh_real_ledgers.py`. That edit was REQUIRED —
  wave 5's own law-test (`test_chamber_coldopen_w5.py ::
  test_no_host_home_path_rides_the_committed_fixtures_or_w5_sources`) forbids
  host-home paths in committed fixtures, and the fix scrubbed one. Reverting would
  re-red the gate. The sanctioned recovery is the two commands below.
- **Mockup amendment gate: CLOSED.** John signed ALL TEN states 2026-08-10 ~05:41
  (drawer drawn now). Signed hash `4a7f7953852b5563fd10e073f7cab8c1ac7930390d0743726b54aebc31aeedde`
  recorded in `chamber/MOCKUP-AMENDMENT-GATE.md` + root `DECISION-LOG.md`; the drawn
  states live in `C:\dev\Ecgberht\planning\steward-assessment-2026-08-08\mockups.html`
  `#amendments` (Ecgberht commit 3483e93; artifact republished, same URL). C9 DOM
  diffs pin to that hash.
- **Remaining John gates:** E1-bound ratification (present prose-style, one at a
  time, when it surfaces mid-build) · W12 tile-retirement parity + ease-report audit
  (vs his 5→0 reference baseline) at the end.
- **Uncommitted in the Anchor tree (intentional):** W5's wave work + these relay
  docs — the orchestrator's W5 GO commit sweeps them. Do NOT commit them yourself.

## First actions (in order)

```
cd C:/dev/Anchor && node "C:/Users/john/.claude/skills/foreman/bin/checkpoint.mjs" clear foreman-checkpoint.json --force
```
```
FOREMAN_GATE_TIMEOUT_MS=2400000 powershell -ExecutionPolicy Bypass -File "C:\Users\john\.claude\skills\foreman\bin\go.ps1" -Project "C:\dev\Anchor" -Resume
```

Then confirm `_foreman-status.log` shows wave 5 re-entering, post the first status
table, and ASK JOHN TO CONFIRM HE SEES IT before trusting your delivery path.

## The status-update contract (John's standing rule — non-negotiable)

- Every 10 minutes ON THE CLOCK, from now to run end. Never stretch the interval,
  including overnight and while blocked.
- Timestamp from the system clock (`date +%H:%M`) — never estimated.
- Locked format, PLAIN LINES (no code fence):
  `[HH:MM] Foreman build · Anchor · steward chamber (M1)` · `─────` dividers ·
  `Effort / Doing / Status / Tests / Blocker / Procs / Journal` · `ETA` + `To do` ·
  then the `STEWARD CAMPAIGN` footer: `Where / Now / Remains / Gates / Verdict`.
- Mirror one line per tick to `planning/steward-chamber-2026-08-09/STATUS-FEED.md`.
- PushNotification ONLY on: wave GREEN · HALT · a John gate · run end.
- Decisions to John: prose, ONE at a time, context → recommendation → question LAST.
  Never a clipped dialog. If a gate goes unanswered >1h, restate it in a DIRECT
  REPLY to his next message (timer-turn messages are the unreliable path).

## Halt-recovery playbook (all seen this run)

| Taxonomy | What it means | Recovery |
|---|---|---|
| gate-timeout | suite ran past budget | re-export `FOREMAN_GATE_TIMEOUT_MS=2400000`, go.ps1 -Resume |
| vacuous-GREEN | wave's new source has no test naming/exercising it | WRITE REAL TESTS first (pytest, private `--basetemp`, AUTH-ON tag on `tests/test_chamber_*.py`), prove them green, THEN checkpoint clear `--force` + resume |
| test-immutability | fix agent touched a test file | verify the edit was demanded by a test/law AND the gate is green → clear `--force` + resume; else revert the edit |
| distro import-closure red | new modules not in `dist_manifest.txt` | the fix loop handles it (1 iteration, historically) |
| dirty-tree refusal (fresh start only) | non-wave residue | commit residue separately; resumes don't check |

Iteration cap is 4 per wave; if exhausted, diagnose `.foreman/wave-N-gate.json` +
agent logs yourself. `DECISION-LOG.md` lesson #3-5 (—force ≠ skipping proof) applies:
clear-force ONLY when the demanded evidence genuinely exists.

## Key paths

- `_foreman-status.log` (rolling) · `planning/steward-chamber-2026-08-09/EXECUTION-LOG.md` (GO lines)
- `.foreman/` (gate/proven/delta-coverage artifacts, heartbeat, run.lock)
- `foreman-checkpoint.json` (root) — the resume state
- `chamber/` (provenance-table, wire-homing, routes-inventory, MOCKUP-AMENDMENT-GATE)
- `scripts/run-all-tests.mjs` — the two-suite gate (~22 min; bannered deselects; W1/W12 debt in TEST-DEBT-REGISTER.md)
- Mockups (normative UI spec): `C:\dev\Ecgberht\planning\steward-assessment-2026-08-08\mockups.html`
