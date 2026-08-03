# tidy-idy Implementation Plan (Converged)

test-command: node --test

## Global Systemic Invariants
1. **Human Decision-Making Rule**: *Any* time `tidy-idy` halts for user input (e.g., Git hygiene halts, debate tie-breakers, critical file deletions), it MUST strictly adhere to the 5-point format: present exactly one question at a time, provide clear context/explanations, list multiple clear options, and provide a specific recommendation.
2. **Strict Structured Outputs**: All LLM interactions (Gandalf, Defender, Attacker, Judge) MUST use API-level Structured Outputs (JSON Schema adherence) to prevent parsing crashes and infinite LLM retry loops.

## Architecture & Data Contracts
- **Data Transport**: Handoffs between waves occur via intermediate JSON files written to a temporary `.tidy-idy/` state directory.
- **Fail-Safe**: If any parsing fails or deadlocks occur, the system defaults to **Retain** to prevent accidental data loss.

---

## Wave Decomposition

## Wave 1: Foundation & Project Discovery
- **Done-When**: `bin/scanner.mjs` locates active Foundry projects, extracts the project's North Star, and outputs `projects.json`.
- **Given/When/Then**:
  - *Given* a workspace containing multiple skill directories.
  - *When* the scanner is executed.
  - *Then* it outputs a valid JSON array of `[{ "path": string, "north_star_file": string }]`.

## Wave 2: Git Hygiene Pre-flight & Compliant Nagging
- **Done-When**: `bin/hygiene.mjs` checks repository status. If dirty, it halts and issues a compliant nag prompt.
- **Given/When/Then**:
  - *Given* a target project with uncommitted changes or an unpushed branch.
  - *When* the hygiene pre-flight runs.
  - *Then* it halts execution, and presents a single question with context, options, and a specific recommendation.

## Wave 3: Gandalf Batch Analysis (True Ruthlessness)
- **Done-When**: `bin/analyze.mjs` invokes the `gandalf` persona to evaluate the codebase strictly against `INTENT.md` (targeting code that distracts from the North Star, not just unused GC) and outputs `suspects_batch.json`.
- **Data Contract**: Outputs `[{ "filepath": string, "reason": string }]`.
- **Given/When/Then**:
  - *Given* a clean project and its `INTENT.md`.
  - *When* `analyze.mjs` runs.
  - *Then* it uses Structured Outputs to emit a valid JSON array of suspect assets explicitly failing North Star alignment.

## Wave 4: Batched Adversarial Debate Engine
- **Done-When**: `bin/debate.mjs` implements the Defender, Attacker, and Judge. It reads `suspects_batch.json` in strict chunks (max 5-10 files per batch to prevent context dilution), runs max 2 rounds of debate, and outputs `judgments.json`.
- **Given/When/Then**:
  - *Given* a batch (≤ 10) of suspect files and the project's North Star.
  - *When* the debate engine runs.
  - *Then* it executes the debate and the Judge strictly emits a JSON array: `[{ "filepath": string, "decision": "RETAIN" | "REMOVE", "rationale": string }]` using API-level Structured Outputs.
  - *Edge Case*: Hard-fails safely to "RETAIN" if the API output violates the schema.

## Wave 5: True Ruthlessness (Archive & Safelocked 30-Day TTL)
- **Done-When**: `bin/archive.mjs` moves "REMOVE" assets to `.archive/`, logs metadata to `archive_manifest.json`, and an inline TTL enforcer hard-deletes (`rm -rf`) files older than 30 days.
- **Safety Interlock**: Before any `rm -rf`, it mathematically validates the timestamp (must be > project creation date and < current time, explicitly rejecting UNIX epoch 1970). If > 10 files are up for deletion, it triggers a Human Decision-Making nag to confirm.
- **Given/When/Then**:
  - *Given* a populated `.archive/` directory and valid `archive_manifest.json`.
  - *When* Wave 5 runs.
  - *Then* it safely hard-deletes files explicitly validated to be exactly > 30 days old, and moves newly judged files into `.archive/` updating the manifest.

## Wave 6: Context Compression Engine
- **Done-When**: `bin/compress.mjs` parses `agent.md`, extracts an executive summary, appends history to `agent_hist.md`, and applies lossy summarization to `agent_hist.md` when it exceeds 500 lines.
- **Given/When/Then**:
  - *Given* a bloated `agent.md` and/or an `agent_hist.md` > 500 lines.
  - *When* `compress.mjs` runs.
  - *Then* it rewrites `agent.md` to under 50 lines and summarizes older entries in `agent_hist.md` without losing critical milestone data.

## Wave 7: Orchestration & Reporting
- **Done-When**: `bin/tidy.mjs` orchestrates Waves 1-6 into a single run sequence per project and emits a final "Hygiene Report" markdown summary to the terminal.
- **Given/When/Then**:
  - *Given* a successful pass through Waves 1-6.
  - *When* orchestration completes.
  - *Then* it outputs a structured Markdown report of all TTL hard-deletes, new archives, and skips, exiting with code 0.
