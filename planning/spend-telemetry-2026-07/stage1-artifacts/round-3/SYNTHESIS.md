# Shark-Tank Round 3 — BLOCKED

- Verdict: **BLOCKED** (1 new BLOCKER)
- Angles: Skeptic=frustrated-UX, Contrarian=operator, Analyst=skeptical-researcher
- Findings: 24 · Blockers: 1 · Demoted (inclusion test): 0

## Blocking (≥2 Sharks agree, traces to a criterion)
- **BLOCKER** `topic:corruption-document` — agree 3 (Skeptic, Contrarian, Analyst) — The re-emission claims the corruption is fixed; it is not — it has gotten worse. Concretely: (a) Phase 3's launch-surface item 2 still reads "envelope-measured today (real `" followed by an ENTIRE embedded copy of the round-2 draft — which itself contains, at its own item 2, a second-level embedding of the round-3 document, i.e. the corruption is now RECURSIVE. (b) The North Star appears at least three times (outer copy, embedded-draft copy, embedded-round-3 copy), directly contradicting "Exactly ONE North Star copy remains." (c) The embedded copies retain the double numbering ("Phase 1 — Phase 0", "Phase 2 — Phase 1"…) the changelog claims was collapsed. (d) The changelog's own item 1 is truncated by the same bug mid-sentence ("restored intact (`job_runner`: real envelope `" → another full document). (e) Raw patch syntax (`>>>>`, `<<<<`, `====`) sits verbatim in the phase-overview section — the reviser emitted unapplied search/replace blocks into the artifact instead of applying them. Diagnose the mechanism, not just the symptom: every corruption site is the literal `$` character inside backticks ("real envelope `$`") — some substitution step is expanding `$`-in-backticks into the whole document. Until the reviser re-emits from scratch (not by patching the corrupted text) and the `$` glyph survives, this plan cannot lock.

## Demoted (failed the inclusion test — cannot hold the loop open)
_none_
