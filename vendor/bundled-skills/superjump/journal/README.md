# journal/ — append-only real-use record

This directory holds the skill's raw, **append-only** experience: one entry per genuine
real-use or canary execution, in the 7-field schema (`references/journal-schema.md`).

Rules:
- **Append-only.** Never edit or delete an existing entry; a correction is a NEW entry.
- **Genuine provenance only.** Entries come from real dogfood/canary runs, tagged with
  their provenance (R5) — not hand-written prose.
- The sleep loop (P0.D) reads these to distill curated lessons into `LESSONS.md`/`SKILL.md`;
  this raw half is never the curated half.

(This README documents the directory and keeps the empty skeleton's `journal/` present.)
