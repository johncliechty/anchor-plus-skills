# Verb: roadmap-show

**Closed list:** yes · **Primary:** roadmap-show

Show the Campaign Roadmap projection derived from the append-only `roadmap_events[]` (engine truth).

- Projection fields per step: `id, name, status, done_when, waiting_on, commissioned_as`.
- A stored projection that disagrees with the event fold is a silent rewrite → structured reject (`roadmap_silent_rewrite`); heal rebuilds from events.
- Face-only prose roadmap → empty projection + honest gap (`face_prose_only`) — steps are never invented from prose.

Usage: `node bin/ecgberht.mjs roadmap-show [--project <path>]`

TW1. Module: `engine/roadmap.mjs` · schema: `schema/roadmap.schema.json`.
