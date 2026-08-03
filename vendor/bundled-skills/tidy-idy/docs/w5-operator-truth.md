# W5 — Operator docs truth alignment (SC5 pointer)

Foreman Wave 6 (plan id **W5**) rewrites the operator story so **SKILL.md** matches
shipped code: `bin/tidy-idy.mjs` + Anchor thin caller + panel + Trash + reorg.

**Production safety code is not redesigned by this wave.** Docs restate existing
invariants only (no auto-apply, one Apply per run, token never on disk/URL/localStorage).

## Canonical sources

| Surface | Path |
|---------|------|
| Operator manual | `SKILL.md` → “How to run” |
| CLI `--help` | `bin/tidy-idy.mjs` `USAGE` |
| Thin caller | `engine/launch/anchor-caller.mjs` (+ `docs/anchor-job-runner-integration-contract.md`) |
| W0 mismatch list (M1–M8) | `<path> |
| Truth gate | `test/sc5-operator-truth.test.mjs` |

## Design note (canonical mockup + A2 Opt1 stage lock)

**CURRENT home:** `<path>

| CURRENT | Lock |
|---------|------|
| `tidy-idy-mockup-A-triage.html` | Mockup A triage |
| `tidy-idy-mockup-A2-reorg.html` | A2 **Option 1 only** (before→after trees) |

Option 2 / Mockups B & C = **REJECTED** (see `docs/w1-mockup-hygiene.md`).

## SC5 checklist (asserted by test)

- [x] SKILL “How to run” uses `bin/tidy-idy.mjs <folder>` (not `tidy.mjs` as default)
- [x] SKILL names panel + Trash + reorg + thin caller
- [x] SKILL options align with `USAGE` / `--help`
- [x] Thin-caller dry path dispatches the same entry with `--json` + `--environment=anchor`
- [x] No claim of auto-apply, multi-Apply, or token on disk/URL
- [x] M1–M8 closed (fixed in docs or explicit legacy/limitation matching code)
