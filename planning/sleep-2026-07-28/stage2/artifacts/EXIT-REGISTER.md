# Exit Register

Build: Anchor sleep cycle 2026-07-28 (v1.2)
Wave: W2 — Phase 0: Exit register engine + status-string generator

## Signed exits

**Zero signed exits.** At plan time and at W2 delivery John has signed for none. None are pre-authorized; every exit is signed live in the wave that needs it, via `anchor.build.exit_register`.

| exit id | criterion | forcing evidence | user sees instead | date | John confirmation |
|---------|-----------|------------------|-------------------|------|-------------------|
| _(none)_ | — | — | — | — | — |

## Binding rules (machine-enforced in exit_register.py)

- E1 `not available on this build` — ABSENT + independent absence transcript; STUB never authorizes E1
- E2 `provisional data` — usage/time only; **illegal for dollars / cost-labelling**
- E3 `documented with reason` — surface already honest or removed; not justified by upstream E1
- E4 `reduced-instrument path` — signed narrowing to the named lighter forms
- E5 `not verified — awaiting John` — not available on the W1 task triple
- E6 `S1 finding routed to follow-on` — **closed** for dead control / silent zero / mislabelled empty / raw-binary preview
- Unsigned exit = HALT
- Conjunction: 2 exits on one criterion, or 4 across the build → `HALT_REBASELINE`
- Terminal status: structural CANDIDATE-MET phrase until N==0 **and** S1 PASS; unqualified `ten criteria met` only then
