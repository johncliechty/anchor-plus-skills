// agent.mjs — Crucible's live `agent()` seam.
//
// As of Wave 4 (trio driver abstraction) the canonical implementation lives in the
// pluggable Claude backend at `drivers/claude.mjs` — the trio's default driver and
// the single source of truth for the `claude -p` behavior. This module re-exports
// that backend's seam so Crucible's public API is byte-for-byte unchanged (the
// non-regression guarantee) while routing through the driver registry with `claude`
// as the default. The exported names and behavior are identical to before:
//   - `extractJson`      pull the first JSON object out of a model reply
//   - `defaultRunClaude` the env-gated (CRUCIBLE_AGENT_LIVE=1) live `claude -p` transport
//   - `makeAgentSeam`    build the stubbable `agent(prompt, opts)` seam
// See `drivers/claude.mjs` for the implementation and `drivers/index.mjs` for the
// `runAgent`/`TRIO_DRIVER` registry that selects the backend.

export { extractJson, defaultRunClaude, makeAgentSeam } from '../../drivers/claude.mjs';
