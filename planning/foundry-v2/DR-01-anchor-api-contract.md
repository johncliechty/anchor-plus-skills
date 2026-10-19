# DR-01 — Anchor API contract: native READ/EXECUTE vs. control-plane MUTATIVE verbs

> Phase-0 §1 decision record (foundry-v2 Wave 1). Machine-readable form:
> `foundry_decisions.ANCHOR_API_CONTRACT` (+ `MUTATIVE_VERBS`, `OP_KINDS`).
> Traces to North Star: **NS#5 (GUI drives the real machinery)** and **NS#1 (manifest-driven runner)**.

## Decision

The Foundry GUI is a **stateless client** over Anchor's existing surface, split two-column:

**Column A — native READ/EXECUTE (Anchor already serves these; the GUI reuses, never mirrors):**

| Capability | Anchor surface |
|---|---|
| Run a skill job | `POST /api/rnd/launch_lane` · `POST /api/rnd/run_deliverable` · `POST /api/rnd/cancel_job` |
| Monitor a job | `GET /api/rnd/tail` (cursor-stable incremental log) |
| Live sessions | `POST term_start / term_input2 / term_resize / term_kill / term_close` · `GET term_ws` (WS) · `GET term_stream2` (SSE) · `GET term_sessions` (SAFE projection) |
| Read artifacts | `GET /artifact/<pid>?path=<rel>` · `GET /report/…` · `GET /summary/…` · `GET /api/rnd/session_summary` |
| Interactive gates | `POST /api/rnd/answer_gate` |
| Auth | `ANCHOR_TOKEN` — token-authed POSTs; GET transports gate via `?token=` |

**Column B — the MUTATIVE verbs Anchor's execution API lacks.** This list IS the Phase-6 op
inventory (Waves 9–10, plus the Wave-6 sleep apply). Each ships as a manifest-registered
`mutate` op on the Wave-3 generic runner, dispatched through `job_runner` — therefore
confirm-token-gated, write-scoped, and auto-journaled. **Mutations are runs, not endpoints.**

| Verb | Wave | Write scope |
|---|---|---|
| `foundry.scaffold_skill` | 9 | `Skill Foundry/skills/<new-skill>/` + `map.json` |
| `foundry.gen_manifest` | 9 | `Skill Foundry/skills/<skill>/manifest` |
| `foundry.edit_north_star` | 10 | `Skill Foundry/skills/<skill>/NORTH-STAR.md` |
| `foundry.register_autoload` | 10 | Anchor skill-registration state |
| `foundry.apply_sleep_improvement` | 6 | target skill dir, on a branch behind the test gate |

No new server, DB, or store: ops read/write the existing on-disk truth (skill dirs, map.json,
git) and emit standard artifacts the GUI renders.

## Why

- The archived Sleep-Engine GUI failed as a **hollow second platform** (own server/DB/watcher,
  string-template calls). The reconciliation in the locked North Star says a Foundry GUI is
  legitimate IFF it drives the real machinery — so every displayed value must resolve to an
  engine-written artifact and every mutation must be a real, journaled run.
- The Stage-1 Shark BLOCKER was exactly this gap: the GUI needs write verbs Anchor's execution
  API lacks. Supplying them as `mutate` ops on the generic runner (not bespoke endpoints) keeps
  ONE engine, many surfaces — the second-surface honesty test (Wave 12) then costs zero
  engine-logic change.
- Enumerating Column B **now** means Waves 9–12 build against a frozen inventory instead of
  discovering verbs mid-build.

## Consumed by

Waves 3 (the `run`/`mutate` op-kind hook), 9–10 (op implementations), 11–12 (GUI read/write surfaces).
