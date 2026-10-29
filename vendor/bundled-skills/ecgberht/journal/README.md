# Ecgberht design — project journal

Append-only friction and learning notes for the **next-gen Ecgberht** effort under `<path>

Skill-owned sleep feed lives in the **skill** journals (jumper / gandalf / researchPrime / crucible / foreman).  
This folder is the project-level rollup so a design session does not lose cross-skill friction.

Schema: same 7 fields as Foundry usage journals when possible.

## Standing discipline (locked 2026-07-25 — John)

For **every** real skill run in this campaign (especially E9/E10):

1. **Skill journal** (`Skill Foundry/skills/<skill>/journal/NNNN-….md` or host skill journal) — entry on **start**, on any **stuck / HALT / workaround / seating friction**, and on **complete**.
2. **Training record** when the engine writes `journal/runs/` — leave it; do not suppress.
3. **Project rollup** here when friction crosses skills or is operator-facing.
4. **Cadence Status table `Journal` row** must recap new journal items since last tick (`none` only if truly nothing).

Silent recovery without a journal entry is forbidden. Sparse logs ≠ silent death — still journal “looks stuck / still alive” when investigating.

## Glossary (locked 2026-07-25 — John)

- **Self-run** — use our own product/skill on our own work (e.g. Ecgberht CLI on this campaign). Prefer this word always; do not say “dogfood.”
- **Shark Tank** — adversarial multi-reviewer runs only (Crucible / researchPrime / kill-filter peers).
