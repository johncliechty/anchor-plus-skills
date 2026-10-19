# Verb: roadmap-set

**Closed list:** yes · **Primary:** roadmap-set

Change a Roadmap step via append-only events ONLY (never direct projection writes):

- `--status <to>` → `status_flip` event. **Receipt required** (`--who`, `--reason`); a flip without receipt is refused (`status_flip_requires_receipt`).
- `--commissioned-as <job>` → `commission_bind` event (TW3 job-lifecycle single-writer hook).
- `--name` / `--done-when` / `--waiting-on` → `step_set` event (status and commissioned_as are forbidden here — they have their own event kinds).

Usage: `node bin/ecgberht.mjs roadmap-set --step <id> --status active --who john --reason "kickoff" [--project <path>] [--dry-run]`

Statuses: `proposed | planned | active | waiting | done | parked`.

TW1. Module: `engine/roadmap.mjs`.

- `--active on|off` · `--active-order N|none` · `--pace YYYY-MM-DD|none` → `step_set` on an initiative's heading step (the active set, 2026-09-29): what he works on now, its place in the set, the date he drives it toward. Off drops the order. Only by his act; the High Seat's head and tile read them.
- `--seat-in active|deck|none` · `--seat-order N|none` (`--seat` alone is the model seat) → `step_set` on a goal's component (the seats, 2026-09-30, John's three levels): a project's cockpit, one cockpit within a project (`effort:<pid>/<dir>`), or a desk task sits in its goal (none), ON DECK, or ACTIVE, in his order. None drops the order. Only by his act or his word; the High Seat's head and shelves read them.
