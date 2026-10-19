# Verb: roadmap-propose

**Closed list:** yes · **Primary:** roadmap-propose

Propose a Roadmap step. Emits a `step_create` event ONLY (status `proposed`); the projection is derived from the event fold — never written directly.

Usage: `node bin/ecgberht.mjs roadmap-propose --name "<step name>" [--step <id>] [--done-when "<criterion>"] [--waiting-on "<who/what>"] [--project <path>] [--dry-run]`

- `--step` defaults to a slug of the name.
- Single writer path: all Roadmap writes flow through `appendRoadmapEvent` (see `ROADMAP_SINGLE_WRITER`); TW3 job lifecycle binds via the same writer.

TW1. Module: `engine/roadmap.mjs`.
