# Feedback intake channel (not code contribution)

**Hard line (R12):** sanitized friction feedback is **not** a code contribution.

- Opt-in only (default off). Full local journals stay on the recipient machine.
- Export records are allowlist-only, fail-closed sanitized, and de-identified
  (opaque install key — never name/email/machine/path).
- Transport delivers to a **John-owned private intake** (repo subtree or
  dedicated inbox), hard-partitioned by `skill_id` under `by_skill/<skill_id>/`.
- Credentials on recipient machines are **intake-scoped only** — never
  product-main write, skill-source write, or repo-admin tokens.
- Intake is **pull/review only**. There is **no auto-merge** into skill sources
  or product `main`. Collaborators who want to change code use the normal
  branch/PR collaborator path, not this channel.
- Cross-skill default blob rollup is forbidden (R14). Metrics may be counted
  per skill; raw records stay in their skill partitions.

## Separate from product write access (topology)

This intake is **not** the public mirror write path and **not** a code push to
main. Dual-audience write policy lives in [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
and topology ops in [`share-topology.md`](share-topology.md). Three paths:

1. **Download & use** — consumers pin release artifacts; local edits stay local.
2. **Sanitized feedback** — this channel (opt-in friction only).
3. **Collaborate** — invited private `*-dev` branch/PR only.

## Dogfood

Invited collaborators use the thinnest viable path first. Measure **export
yield** before any public marketing claim. If yield is zero, kill the channel
cost honestly rather than building heavy UI.
