# HANDOFF — Ecgberht steward campaign orchestration

**STATUS 2026-08-02: READY FOR THE FOREMAN (HEAVY) BUILD.** North Star v5 LOCKED,
Stage-2 APPROVED, plan v3 emitted to `handoff/` and integrity-verified.

---

## The build input — `handoff/` (this is what Foreman consumes)

| File | Role |
|---|---|
| `handoff/IMPLEMENTATION-PLAN.md` | **22 waves, AUTHORITATIVE** — byte-identical to `stage2-artifacts/IMPLEMENTATION-PLAN-v3.md` |
| `handoff/wave-decomposition.json` | generated from the plan; embeds `source_sha256` = `2a2a21804154891b…` |
| `handoff/foreman.config.json` | Heavy tier, seating, build root, test lanes, per-wave commit repos, authorized real-run waves, HALT set |
| `handoff/DESCRIPTION.md` | what is being built and why |
| `handoff/EXECUTION-LOG.md` | Foreman appends GREEN/HALT per wave |

**Integrity rule:** `sha256(handoff/IMPLEMENTATION-PLAN.md)` MUST equal `source_sha256`
in `handoff/wave-decomposition.json`. Mismatch ⇒ **STOP, do not build.**

**NEVER read** (they contradict v3 on gate semantics — one wrong file-pick silently
reverts the hardening layer with all gates green):
`stage2-artifacts/wave-decomposition.STALE-DO-NOT-USE.json` ·
`stage2-artifacts/*.SUPERSEDED.*` · `stage2-artifacts/BEST-DRAFT.md`

## Governing documents

| File | Role |
|---|---|
| `NORTH-STAR.md` | **v5, LOCKED 2026-08-02** — 15 criteria, anti-drift authority |
| `STAGE2-APPROVAL.md` | the build approval + authorized real-run budgets |
| `STAGE1-APPROVAL.md` | gate decisions 1–7 + signed Descope D-1 |
| `PLAN-V3-CHANGES.md` | what changed from v2 and why |
| `REVIEW-CONSISTENCY.md` / `REVIEW-HARDENING.md` / `REVIEW-SKILL-BOUNDARY.md` | the three Fable reviews this plan answers |
| `INTAKE.md` | verified build-vs-wire fact base |
| `C:\dev\Ecgberht\SKILL.md` | the skill contract (corrected 2026-08-02, commit `4889c3c`) |
| `C:\dev\Ecgberht\NEXT-UX-AND-ANCHOR-ORCHESTRATION.md` | John's locked UX intent |

## The shape of the thing

**The deliverable IS the skill** (`C:\dev\Ecgberht`) — ONE skill, TWO entry surfaces
(seal = project, high seat = portfolio). **Anchor is the REFERENCE HOST**, implementing
host contracts only (executor, outbox producer, authorizer, routes/UI). **No steward
logic in Anchor Python** — NS v5 non-goal, CI-fenced in Wave 1.

**Execution order is the DAG, not the numbers: 1…18 → 20 → 21 → 22 → 19.**
- W20 in-session executor (skill spawns/supervises runs with no Anchor)
- W21 shared conformance suite — BOTH executors, ONE contract, drift fails loudly
- W22 T-HOST-0 — the whole steward working with no Anchor at all
- W19 final campaign proof; requires T-HOST-0 PASS + both-executor conformance PASS

## Invariants (a violation is a HALT, not a judgement call)

E5 single ledger (chat turns NEVER persisted; dialogue COMPILES into the Face) · single
writer on `roadmap_events` · commissions FOR roadmap steps carrying `who` as CLAIMED
identity stamped unauthenticated · subscription-CLI seats only (family→driver via
`resolveSeats`) · the ENGINE contains no `ANCHOR_TOKEN` logic (auth via injected
`authorize()` hook) · unattended reflections ZERO-MODEL + ZERO-NETWORK, trap-asserted ·
nothing spends without human confirmation · no adversarial review in the product loop.

**Vacuous-auth trap:** `paths.auth_ok()` returns True when `ANCHOR_TOKEN` is unset — an
auth-ON assertion MUST first assert a token is configured and the mode is enforce.

## Environment hazards

Long runs MUST launch detached via **schtasks breakaway** (background shells and
Start-Process died SILENTLY 9+ times — job-object SIGKILL) · Anchor is the NSSM service
`anchor` on :8777, restart ONLY via elevated `restart_anchor.ps1`, never blanket-kill
python · `job_runner.py` KILL_ON_JOB_CLOSE orphans commissioned runs (W4 fixes it) ·
cross-repo: build root `C:\dev\Ecgberht`, some waves are pytest in `C:\dev\Anchor` ·
Windows process supervision is now owned TWICE — W21 is what stops the two executors
drifting.

## Outstanding, NOT on the build path

- **Anchor service restart pending** for the 31 July UI fixes to go live: elevated
  `powershell -ExecutionPolicy Bypass -File .\restart_anchor.ps1`, then Ctrl+Shift+R.
- **`test_session_continue`** — 3 pre-existing failures; a product call (stale tests vs
  contract drift), deliberately kept off this path.

## History (why the plan looks the way it does)

Stage 1 HALTed human-lockable → two Fable reviews found the Stage-2 draft NOT safe (the
machine decomposition contradicted the human plan on G4 semantics while the hardening
gate said PASS) → 13 must-fixes applied → John challenged the framing ("I want a skill,
not an Anchor feature") → the boundary review found the skill already existed with both
altitudes built and the plan already 12-of-19 skill-rooted → NS v5 reframed skill-first,
the in-session executor was added, plan v3 landed at 22 waves.
