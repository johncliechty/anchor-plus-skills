# bin/ wave numbering — TWO programs, one directory (read before trusting a header)

Two build programs shared this directory and both numbered their waves from 1, so a
module header saying "Wave N" is ambiguous without this map (2026-07-25 review,
researchPrime §3 — this collision is how the T9 governor orphan survived review:
`governor.mjs` says "Wave 8 GOVERNOR WIRING … the WIRING the prior waves were built to
drop into", which read as DONE while `test/wave8-*.test.mjs` was green about a
different program's wave 8 entirely).

| Wave # | VERIFICATION program (MASTER-PLAN) | GOVERNANCE program |
|---|---|---|
| 1 | preregistration.mjs | formal-governor.mjs |
| 2 | trio-core/independence-accounting.mjs | wave2 lint suite |
| 3 | — | (governance-record.mjs — archived 2026-07-25) |
| 4 | stakes.mjs | intake / triage extension |
| 5 | — | matrix-planner.mjs |
| 6 | verify-core.mjs | gate-loader.mjs |
| 7 | round.mjs | approval-provider.mjs |
| 8 | governor.mjs | replay fixtures |
| 9 | rho-ledger.mjs | (calibrate-shadow.mjs — archived) |

Rule going forward: a new module's header names its PROGRAM, not just a wave number.
`test/bin-reachability.test.mjs` asserts every bin/*.mjs is reachable from a canonical
entry (run-rounds.mjs / plan-gate.mjs) or explicitly allowlisted as a tool.
