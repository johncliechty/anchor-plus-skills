# Crucible/Foreman → Gemini adapter — scoping notes (for a future trio run)

> Saved 2026-06-09. Purpose: capture everything needed to make the **Plan (Crucible)**
> and **Build (Foreman)** lanes runnable on the **Gemini CLI**, not just Claude. Research
> (researchPrime) is portable and already wired for Gemini. This doc is itself a good
> candidate to feed through the trio: researchPrime (study the gemini-cli agent API) →
> Crucible (forge the adapter plan) → Foreman (build it).

## Current state (what already exists in Anchor)
- The runner layer is **CLI-agnostic**: `job_runner.resolve_runner_cmd(backend)` resolves
  `claude` vs `gemini` commands; `ANCHOR_RUNNER_CMD` overrides for tests (mock).
- A per-effort **engine selector** is built: `lanes.launch_lane(..., backend=...)`, the
  `/api/rnd/launch_lane` endpoint accepts `backend`, the project window UI offers
  "Run Research (Claude)" / "Run Research (Gemini)".
- The Gemini-only-for-Research policy is a single set: **`lanes.GEMINI_LANES = {"research"}`**.
  Enabling Gemini for plan/build later = add `"plan"`/`"build"` to that set (after the
  adapter below is built + validated).
- Default gemini command (job_runner.DEFAULT_GEMINI_CMD), validated by the spike:
  `gemini --skip-trust -p --output-format stream-json --approval-mode plan`
  (override via `ANCHOR_GEMINI_CMD`).

## Gemini headless spike — findings (2026-06-09, live on gwl-server/PUTER)
- `gemini -p "<prompt>"` runs **non-interactive/headless**; authenticates as the service
  user (`john`) with **no login prompt** (subscription/credentials already present).
- **MUST pass `--skip-trust`** (or `GEMINI_CLI_TRUST_WORKSPACE=true`): without it Gemini
  treats a project folder as untrusted, forces read-only, and overrides the approval mode.
- `--output-format` supports **`stream-json`** (and `json`/`text`) — parallel to Claude's
  stream. JSON result carries `session_id`, `response`, and a `stats.models.<model>` block
  with `api.totalLatencyMs` and `tokens {input, prompt, candidates, total, cached}` →
  **cost/usage capture is feasible** (map to Anchor's cost fields like Claude's envelope).
- Default model observed: `gemini-3.1-flash-lite` (set with `-m/--model`).
- Has `--approval-mode {default, auto_edit, yolo, plan}`, `-y/--yolo`, a **skills** system
  (`gemini skills`), **MCP**, **extensions**, **hooks**. Minor: warns "Ripgrep is not
  available. Falling back to GrepTool" (cosmetic).

## What the adapter needs (the actual work)
Crucible and Foreman are **Node engines** that orchestrate sub-agents through an injected
`agent()` seam + a gate adapter, both currently bound to **Claude's** stream-json +
`AskUserQuestion` model. They are CLI-orchestration-bound, not Claude-*model*-bound. To run
them on Gemini:
1. **Gemini `agent()` binding** — a driver that spawns `gemini --skip-trust -p
   --output-format stream-json` (+ `-m`), feeds the prompt, and parses Gemini's stream
   frames into the {execute, review, fix} step results the engines expect (structured
   text/tool-use). Mirror Foreman's existing `makeAgentDriver({agent})` seam.
2. **Gemini gate adapter** — parse Gemini's tool-call / approval frames into the prompt-box
   record Anchor uses for Claude's `AskUserQuestion` (question/options/id), so in-session
   gates (`gate_adapter`) work for plan/build on Gemini. Confirm how Gemini surfaces an
   interactive choice in headless `--approval-mode` and how a "text answer" continues it
   (the Claude analog is Spike-0's text-turn-after-auto-dismiss).
3. **Cost capture** — read Gemini's `stats.models.*.tokens` + latency from the result and
   store on the effort (mirror the Claude `result` envelope capture in job_runner).
4. **Trust + sandbox** — always pass `--skip-trust`; decide on sandbox (`-s`) and approval
   mode (`yolo`/`auto_edit`) for the **build** lane (which mutates the tree) vs `plan`
   (read-only) for the **plan** lane.
5. **Engine portability of the skills** — research/plan/build skills are Claude Code skills.
   Gemini has its own `skills` system; either install equivalents via `gemini skills` or
   feed the skill methodology via the `-p` prompt (researchPrime is already portable).
6. **Validate** — a Crucible + Foreman **dogfood run on Gemini** against a throwaway project,
   verifying the engine contracts (structured outputs, the orchestrator-run ground-truth
   gate, finding identity) hold. Only then relax `lanes.GEMINI_LANES`.

## Risks / open questions
- Does Gemini's headless `--approval-mode` actually surface an answerable interactive gate,
  or does it just auto-decide? (Determines whether the in-session gate model transfers or
  needs a different UX for Gemini plan/build.) ← do a focused gate spike first.
- stream-json frame schema differences (tool_use shape, result envelope keys) vs Claude.
- Sub-agent spawning model: the engines spawn fresh-context sub-agents; confirm the Gemini
  driver can spawn isolated child sessions equivalently.

## Definition of done
`lanes.GEMINI_LANES = {"research","plan","build"}` with a validated Gemini `agent()` driver
+ gate adapter + cost capture, proven by a green Crucible+Foreman dogfood run on Gemini, and
the UI offering the Gemini engine on all three lanes.
