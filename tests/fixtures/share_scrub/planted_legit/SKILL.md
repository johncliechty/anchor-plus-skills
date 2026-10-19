# PLANTED LEGIT FIXTURE — dual-scrub CI (Shareable W2).

Skill prose that names **legitimate relative paths** only. Clean-scan must
PASS with no false-positive block.

## Layout

- Entry: `SKILL.md` (this file)
- Runtime: `./src/cli.mjs`
- Tests: `test/unit/smoke.test.mjs`
- Nested skill docs: `skills/jumper/references/improvement.md`
- Relative data: `../shared/schema.json` from a sibling skill tree

Do not hardcode absolute host paths. Recipient machines resolve skills from
their chosen home (e.g. a relative `skills/` install tree).
