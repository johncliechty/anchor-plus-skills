# Codex skill-seam inventory

Bounded inventory for `steward-codex-anchor-2026-08-31`. This classifies production
agent entry points; tests, one-off planning scripts, archived artifacts, and external
model transports are not counted as skills.

## Foundry runtime map

| Skill surface | Current production seam | Codex-ready state | Bounded action |
|---|---|---|---|
| researchPrime | Trio role routing / `runAgent` | Ready | Freeze; retain injected tests. |
| Crucible | Trio role routing / `runAgent` | Ready | Freeze; retain verification attestation. |
| Foreman | Trio role routing / `runAgent` | Ready | Freeze. |
| Figure Designer | Prompt contract; no owned model spawn | External | Record as host-routed; do not invent an engine. |
| Gandalf | Trio role routing, with the proven `agy` seam for Gemini | Ready | Freeze production path; classify old generator scripts as tooling. |
| Ramanujan | Gemini-primary Phase-F probe plus Ollama fallback | Missing shared adapter | Separate high-risk slice; preserve certifier and attestation contracts. |
| Financial Analyst | Deterministic/prompt workflow; no owned model spawn | External | Record as host-routed; do not invent an engine. |
| Jumper | Trio `runAgent` with receipt ledger | Ready | Frozen by Wave 0 (42/42). |
| Legal Beagle | Prompt contract; no owned model spawn | External | Replace Gemini-specific prose only when that delegated review contract is revised. |
| Literature Review | researchPrime live-round agent / Trio routing | Route-ready, telemetry gap | Make family lineage and `cross_model` truth derive from reached receipts. |
| Tidy-Idy | Injected agent or Gemini-specific module factory | Missing shared adapter | Add injected Trio `runAgent` adapter without a live call. |
| Zombie Hunter | Deterministic runtime; separate development verifiers | External | Keep runtime deterministic; do not treat verifier wrappers as production roles. |

Counts: 12 canonical runtime surfaces; 5 clean shared-Trio routes, 1 shared route
with a truth-reporting gap, 4 prompt-only/deterministic surfaces, and 2 missing
shared adapters.

## Priority surfaces outside the Foundry map

| Surface | Finding | Bounded action |
|---|---|---|
| Ecgberht / Steward | Seat selection accepts only Claude, Gemini, and Grok; dirty in-progress Codex code manually launches model CLIs instead of Trio. | First adapter slice: admit `chatgpt`, make production seat calls use injected/shared Trio `runAgent`, retain replay, and test Ultra as reasoning effort without a live invocation. |
| Anchor Doctor | Host-side terminal/provider controls, not a Foundry skill runtime. | Cover with the Anchor selector slice in Wave 2. |

## Deliberate exclusions

- No live subscription CLI or Fable call.
- No OAuth, real account data, deployment, commit, push, or merge.
- No rewrite of Ramanujan inside the Ecgberht slice.
- No conversion of prompt-only skills into new orchestration engines.
- No promotion of `_mockups/dashboard-v2` sample data.

The next acceptance gate is deliberately narrow: Ecgberht resolves ChatGPT from
the Anchor preference mirror, routes one injected synthetic Steward seat through
the shared Trio contract, records an honest receipt, and leaves the preference
file unchanged.

## Post-inventory disposition

The focused Ramanujan boundary gate corrected its initial `Missing shared
adapter` label. Its normal skill is host-routed, its thin CLI is deterministic,
and Phase F is a specialized certificate appliance rather than a general agent
seat. The bounded decision and evidence are in
`planning/v1.2.8/RAMANUJAN-CODEX-BOUNDARY-DECISION.md`; no Phase-F production code
was changed. After the Ecgberht, Tidy-Idy, Literature Review, and Ramanujan gates,
there are no unclassified or missing general model seams in the 12-surface map.
