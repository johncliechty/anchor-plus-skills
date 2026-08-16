# Verb: roadmap-set

**Closed list:** yes · **Primary:** roadmap-set

Change a Roadmap step via append-only events ONLY (never direct projection writes):

- `--status <to>` → `status_flip` event. **Receipt required** (`--who`, `--reason`); a flip without receipt is refused (`status_flip_requires_receipt`).
- `--commissioned-as <job>` → `commission_bind` event (TW3 job-lifecycle single-writer hook).
- `--name` / `--done-when` / `--waiting-on` → `step_set` event (status and commissioned_as are forbidden here — they have their own event kinds).

Usage: `node bin/ecgberht.mjs roadmap-set --step <id> --status active --who john --reason "kickoff" [--project <path>] [--dry-run]`

Statuses: `proposed | planned | active | waiting | done | parked`.

TW1. Module: `engine/roadmap.mjs`.
