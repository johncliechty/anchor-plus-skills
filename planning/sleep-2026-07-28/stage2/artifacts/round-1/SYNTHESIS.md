# Shark-Tank Round 1 — DRY

- Verdict: **DRY** (dry round — no new BLOCKER)
- Angles: Skeptic=skeptical-researcher, Contrarian=competitor, Analyst=bored-investor
- Findings: 44 · Blockers: 0 · Demoted (inclusion test): 2

## Blocking (≥2 Sharks agree, traces to a criterion)
_none_

## Demoted (failed the inclusion test — cannot hold the loop open)
- ~~`topic:command-gates-level-pytest-test-top-vs`~~ traces_to_north_star: no — Document header says `node scripts/run-all-tests.mjs` while every wave gate is scoped pytest. Inconsistent operator entrypoint; does not by itself create a dead control or fabricated dollar. Demoted under inclusion test.
- ~~`topic:command-gates-pytest-test-vs`~~ traces_to_north_star: no — Top-level test-command is node scripts/run-all-tests.mjs while every wave gate is scoped pytest. Out of inclusion for North Star severity; still a Foreman foot-gun if the aggregator does not invoke the same suites. Align or document the aggregator’s inclusion list—demoted under inclusion test.
