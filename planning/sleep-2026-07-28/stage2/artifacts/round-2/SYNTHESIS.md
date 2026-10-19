# Shark-Tank Round 2 — DRY

- Verdict: **DRY** (dry round — no new BLOCKER)
- Angles: Skeptic=future-maintainer, Contrarian=steel-man-the-premise, Analyst=security
- Findings: 40 · Blockers: 0 · Demoted (inclusion test): 5

## Blocking (≥2 Sharks agree, traces to a criterion)
_none_

## Demoted (failed the inclusion test — cannot hold the loop open)
- ~~`topic:binding-docstring-lock-text-verbatim`~~ traces_to_north_star: no — Coupling enum docstrings to the plan’s binding prose “verbatim” makes any clarity edit to the plan a red W6 gate. That is future-maintainer friction, not a North-Star honesty failure. Prefer a single imported constants module or hash of the binding fragment over full-prose equality—demote unless it causes label drift on screen.
- ~~`topic:changelog-empty-reviser`~~ traces_to_north_star: no — Fifty-one identical “Applied a search/replace patch” lines give a future shark or maintainer zero diff intent. Process defect for the planning loop, not a product North-Star violation—do not hold the wave list open on this alone, but stop accepting content-free changelogs.
- ~~`topic:four-named-states-trichotomy`~~ traces_to_north_star: no — The section is titled “trichotomy” and then defines four words (empty, zero_measured, unknown, pending) and forbids a fifth. Naming is inconsistent; fix the label to “state tetrad” / “four-way state vocabulary” so implementers do not assume three buckets and merge pending into unknown. Out of scope for North Star severity; do not promote.
- ~~`topic:changelog-opaque-reviser`~~ traces_to_north_star: no — The reviser’s changelog is fifty identical “Applied a search/replace patch” lines—no semantic delta. That prevents sharks from targeting what changed. Process hygiene only; demote. Future revisions should list wave/section-level intent.
- ~~`topic:asserts-controls-gates-integrity-omit-property-security-while`~~ traces_to_north_star: no — The plan asserts signature validation, host-computed attestation, release isolation, and path refusal in places, but the emitted property-gate checklist only lists honesty, idempotence, boundedness, containment. There is no security/integrity gate (authz of confirmations, secret redaction, package quarantine). Under the plan’s own rule this is not a property-named-but-unenforced BLOCKER unless security is named as a property. Recorded for synthesis only; do not keep the loop open on this alone.
