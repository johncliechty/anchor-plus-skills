# Appendix A — traceability ledger: integrated ideas 1–52 + mitigations 1–20 (W3)

Every integrated idea and mitigation from the Stage-1 Master Plan, resolved
to the wave(s) of the frozen `IMPLEMENTATION-PLAN.md` that cite it. The W3
gate (`tests/test_rearch_2026_07.py::TestW3AppendixALedger`) re-derives the
citation map mechanically from the frozen plan text and fails if this ledger
drifts from it — traceability is demonstrated, not narrated. W18's closure
re-runs the reconciliation against the final delivered state.

## Integrated ideas 1–52 → citing wave(s)

| idea | wave(s) |
|---|---|
| I-1 | W1, W6 |
| I-2 | W4, W5 |
| I-3 | W4, W5 |
| I-4 | W1 |
| I-5 | W2 |
| I-6 | W4 |
| I-7 | W4 |
| I-8 | W2 |
| I-9 | W6 |
| I-10 | W7 |
| I-11 | W8 |
| I-12 | W8 |
| I-13 | W2 |
| I-14 | W3, W9 |
| I-15 | W9, W18 |
| I-16 | W7 |
| I-17 | W8 |
| I-18 | W7 |
| I-19 | W12 |
| I-20 | W1, W13 |
| I-21 | W12 |
| I-22 | W14 |
| I-23 | W3, W12 |
| I-24 | W12 |
| I-25 | W14 |
| I-26 | W13 |
| I-27 | W15 |
| I-28 | W15 |
| I-29 | W15 |
| I-30 | W15 |
| I-31 | W16 |
| I-32 | W16 |
| I-33 | W3, W17 |
| I-34 | W3, W17 |
| I-35 | W15 |
| I-36 | W17, W18 |
| I-37 | W10 |
| I-38 | W10 |
| I-39 | W11 |
| I-40 | W11 |
| I-41 | W11, W18 |
| I-42 | W3 |
| I-43 | W3, W18 |
| I-44 | W3, W18 |
| I-45 | W3, W8 |
| I-46 | W7 |
| I-47 | W13 |
| I-48 | W14 |
| I-49 | W15, W16 |
| I-50 | W4, W5, W6 |
| I-51 | W8 |
| I-52 | W3, W18 |

**Coverage: 52/52 ideas are cited by at least one wave — zero silently
dropped.**

## Mitigations 1–20 → citing wave(s)

| mitigation | wave(s) |
|---|---|
| M-1 | W1 |
| M-2 | W4 |
| M-3 | W9 |
| M-4 | W2, W8 |
| M-5 | W1 |
| M-6 | W12, W14 |
| M-7 | W15 |
| M-8 | W15 |
| M-9 | — (explicit reconciliation below) |
| M-10 | W3, W17 |
| M-11 | W11 |
| M-12 | W2 |
| M-13 | W3, W12 |
| M-14 | W1 |
| M-15 | W3 |
| M-16 | W7 |
| M-17 | W10 |
| M-18 | W17 |
| M-19 | W13 |
| M-20 | W3 |

## Mitigation 9 — the explicit reconciliation

**M-9 is the ONLY mitigation cited by zero waves of the frozen
Implementation Plan**, and the plan's W3 deliverable mandates that this be
reconciled explicitly rather than left to be noticed. Recorded here so it can
never be a silent drop:

- Status: **no landing wave** in the frozen plan (every other mitigation
  1–20 resolves to at least one wave).
- The Stage-1 Master Plan — the source document carrying M-9's text — is not
  checked into this repository (the frozen doc trio here is the North Star
  in `DESCRIPTION.md` + the wave plan in `IMPLEMENTATION-PLAN.md`); this
  ledger therefore records the omission mechanically, without paraphrasing
  the mitigation's content.
- Binding follow-through: **W18's Appendix-A reconciliation must resolve
  M-9 against the Stage-1 Master Plan to either a landed item or a
  documented amendment** (its done-when names Mitigation 9 for exactly this
  reason). Until then, M-9 is an OPEN reconciliation item, visibly carried —
  not resolved by this entry.

## Provenance

- Source of the citation map: the `(Master Plan Phase N; Integrated …;
  Mitigations …)` intent lines of the 18 waves in the frozen
  `IMPLEMENTATION-PLAN.md` (root).
- Kept mechanically honest by the W3 gate test, which re-parses those lines
  and diffs them against the two tables above.
