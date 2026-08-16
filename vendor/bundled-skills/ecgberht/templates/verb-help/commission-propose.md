# Verb: commission-propose

**Closed list:** yes · **Primary:** commission-propose

Steward proposes a commission FOR a Roadmap step (the propose/confirm path is the primary UX — never a mode-picker instrument face). Skill + depth are steward-proposed defaults John can override at confirm.

- `--step <id>` (required) — the Roadmap step the commission is for.
- `--skill <name>` (required) — one of `researchPrime | Crucible | Foreman | Gandalf | Jumper` (compose-only spawn contract; no in-process Shark Tank/Foreman loops).
- `--depth <cell>` — steward-proposed depth cell default.

Read-only: returns a `commission_proposal` with `requires_confirm: true`; **nothing is written until `commission-confirm`**. Steps that are `done`/`parked` refuse (`commission_step_not_open`); no Roadmap refuses (`no_roadmap`).

Usage: `node bin/ecgberht.mjs commission-propose --step <id> --skill Foreman [--depth FULL] [--project <path>]`

TW3 (M2). Module: `engine/job-lifecycle.mjs`.
