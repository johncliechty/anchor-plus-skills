# Journal entry schema (reference)

> The full, authoritative **7-field journal schema** is defined and TAP-gated by P0.D
> (wave 5): the contract lives in `src/journal.mjs` (`JOURNAL_FIELDS`) and is gated by
> `test/journal.test.mjs`. This reference stays in sync with that contract (a wave-5 test
> asserts every field below is named here).

Each entry in `journal/` is an append-only record of ONE genuine real-use / canary
execution of this skill (provenance-tagged per R5 — never hand-fabricated prose). The
7 fields (authoritative, in canonical order):

1. `id` — stable unique entry id (append-only; corrections are NEW entries, never edits).
2. `skill` — the `skill@version` that produced the entry.
3. `situation` — the recurring situation class; the sleep loop's CLUSTER key.
4. `context` — the DISTINCT execution context; the cross-context corroboration key (R5).
5. `observation` — what was learned; the candidate-lesson signal a cluster distills.
6. `outcome` — the genuine execution result (e.g. `canary-pass` / `canary-fail` / `refused`).
7. `provenance` — how the entry was produced: `genuine-execution` | `seeded` (R5 distrust).

Append-only: entries are never edited or deleted in place; corrections are new entries.
The sleep loop (P0.D) reads these, requires CROSS-CONTEXT corroboration before distilling
a lesson, and promotes a curated lesson to `LESSONS.md`/`SKILL.md` only through the
North-Star gate + eval gate.
