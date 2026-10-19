# W1 — Mockup hygiene (SC1 pointer)

Foreman Wave 2 (W1) locks one CURRENT mockup set. Production panel code is **not** edited in this wave.

**Canonical CURRENT home:**

`<path>

| CURRENT | Path |
|---------|------|
| Mockup A triage | `design/tidy-idy-mockup-A-triage.html` |
| A2 Option 1 only | `design/tidy-idy-mockup-A2-reorg.html` |

| REJECTED / POINTER | Location |
|--------------------|----------|
| B / C / A2 Option 2 | `design/archive/*-REJECTED.html` |
| Root `<path> | POINTER (A/A2) or REJECTED (B/C) stubs |
| Parent `plans/2026-07-tidy-idy-gui/design/` | POINTER stubs |

**Assert home:** `test/sc1-mockup-hygiene.test.mjs` (skill root `node --test` reads absolute plan/root paths).
