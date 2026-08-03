# Shark-Tank Round 1 — BLOCKED

- Verdict: **BLOCKED** (1 new BLOCKER)
- Angles: Skeptic=skeptical-researcher, Contrarian=competitor, Analyst=bored-investor
- Findings: 14 · Blockers: 1 · Demoted (inclusion test): 3

## Blocking (≥2 Sharks agree, traces to a criterion)
- **BLOCKER** `topic:daemon-dependency-missing` — agree 2 (Skeptic, Contrarian) — Wave 3 explicitly lists 'Depends on: —' (no dependencies), yet its `done-when` scenario requires querying the background daemon via IPC. It must depend on Wave 2, which is the wave responsible for building and running the background daemon.

## Demoted (failed the inclusion test — cannot hold the loop open)
- ~~`topic:cryptography-encryption-unrequested`~~ traces_to_north_star: no — The plan introduces a 'Cryptographic Allowlist for Microsoft signed binaries' (Wave 1) and 'at-rest database encryption' (Wave 2). The North Star requires system-wide detection and historical forensics, but never mandates cryptographic signature verification or encrypted local storage. These introduce massive, unrequested implementation overhead.
- ~~`topic:features-out-scope-security`~~ traces_to_north_star: no — Wave 1 and 2 introduce a 'Cryptographic Allowlist' and 'at-rest database encryption'. These features are not mandated by the North Star and represent over-engineering that inflates scope and delays time-to-market compared to competitors.
- ~~`topic:bloat-crypto-encryption`~~ traces_to_north_star: no — Wave 1 adds a cryptographic allowlist and Wave 2 adds an encrypted SQLite database. Neither is requested in the North Star. This is unbudgeted enterprise-grade over-engineering that wastes resources without delivering business value.
