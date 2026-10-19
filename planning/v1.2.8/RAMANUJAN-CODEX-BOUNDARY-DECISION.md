# Ramanujan Codex boundary decision

Decision date: 2026-08-31

## Decision

Do not replace Ramanujan's Phase-F Gemini/Ollama certifier with a generic Trio
adapter in this bounded run.

Ramanujan has three distinct surfaces:

1. The normal skill is a prompt contract executed by the active host. When the
   active host is ChatGPT/Codex, Codex already performs the understand, solve,
   dialogue, formalize, and contextualize work; Ramanujan does not own another
   model spawn for those roles.
2. `bin/ramanujan-run.mjs` is an exact, deterministic verifier. Its only child
   process is the hermetic Node arithmetic firewall. Adding a model adapter would
   weaken this surface rather than make it more capable.
3. Phase F is an optional, separately gated corroboration appliance. Its pinned
   Gemini-primary/Ollama-fallback identities, independent rerun, and derived
   evidence rungs are part of the certificate contract. It is not a general
   reviewer seat. Substituting Trio here would require a new manifest, canary,
   family-relative independence proof, and rung policy; that is a separate
   formal Foundry improvement, not a safe adapter patch.

This means Codex is usable as Ramanujan's operating/generating host now. Codex is
not claimed as a Phase-F certifier. If that role is desired, implement it as a
versioned Phase-F vNext slice with explicit served-model attestation and keep the
current certifier available until the new canary proves equivalent or stronger.

## Evidence

- The canonical CLI imports the deterministic orchestrator and arithmetic
  firewall; it does not call `runCrossFamilyPanel`, `driveCrossFamily`, or a model
  transport.
- The canonical cross-family route abstains unless a certificate, rerun
  capability, and trusted probe result are explicitly supplied.
- The Phase-F contract derives the evidence rung from the reproduced backend
  identity and rejects same-family verification relative to the generator.
- Focused boundary gate: 64 assertions passed across the CLI/invocation and
  cross-family driver/verifier tests. The two real-tool-lane suites remained
  disabled; no subscription model or network endpoint was called.
- Wave 4 rerun: the same bounded four-file gate again passed 64/64 with both
  real-tool lanes explicitly disabled.
- The real Anchor preference mirror remained unchanged at SHA-256
  `CDC47E7267BB939F86C559CE705CE96ED210FB6228CF80A022E20DD134707A49`.

## Wave-1 disposition

Ramanujan is classified as **host-routed + deterministic, with a specialized
external certifier**. It has no missing general agent adapter. No Ramanujan
production file was changed in this wave.
