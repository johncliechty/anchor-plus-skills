---
name: Anvil
icon: assets/icon.jpg
description: Programmatic codebase comprehension, Parable-of-the-Oranges proactive one-trip complete staff work (understanding the real goal, thinking 2-3 steps ahead, and solving the whole problem with a clear recommendation), Essential Core vs. Scaffolding decomposition, interactive block-by-block empirical validation, lossless LibCST/parso best-in-class code remapping (with explicit Null Space, Get-Data/Do-Analysis/Create-Output purity, and Hypothesis differential equivalence), and paper-to-code verification with native MathML and persistent Anvil Agent dialogue.
---

<!-- ELEGANCE-LAW v2 -->
## The Elegance Law (locked by John — binding on this skill)

Canonical text: `Skill Foundry/ELEGANCE.md`. Applies to ANY agent running this
skill on ANY host. If this block and a longer procedure below disagree, this
block wins.

1. **Approvals are ≤200 words** — what changes in his world, the recommendation,
   the one thing that gets worse. The artifact stays on disk and is named, not
   pasted. An approval obtained with a longer block is VOID.
2. **Summaries are ≤150 words** — goal in one line, done / not done, ≤3 findings
   ranked by consequence, the single next decision. Never rounds, waves, seats,
   stamps, gate counts, or file inventories.
3. **Default to the lightest band, without asking.** A heavier tier requires the
   first status line to NAME its trigger: irreversible or externally visible,
   inputs unconverged, a prior failure in this exact area, or he asked for it.
4. **Needed-because line.** Any element he did not request carries one line:
   "Needed because ___; dropping it costs ___." No line, no element.
5. **Show a cut.** ONE dry round ends a review loop — never a streak. Every plan
   names something it removed; "nothing cut" is said aloud.

**THE VERIFICATION LAW** (added 2026-08-15):
6. **Verify the claim you actually made, on the surface he actually uses.**
7. **A symptom reported twice retires the first explanation.**
8. **Prefer a mechanism to an instruction.**
9. **A correction that lives only in a journal or a memory has not been made.**
<!-- /ELEGANCE-LAW -->

> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol.
> **Locked Objective:** see `NORTH-STAR.md` (Rev 3, `ANV-01` through `ANV-11`) and `references/RESEARCHPRIME-CODE-REWRITING-TOOLS.md`. Do not drift from it.

# Anvil — Programmatic Orchestrator for Code Comprehension, Parable-of-the-Oranges Proactive Foresight, Empirical Validation & Best-in-Class CST Remapping

**Anvil is a programmatic orchestrator skill** — never a prose checklist handed to an LLM. Its deterministic Python engine (`scripts/anvil_engine.py`) governs stage transitions, enforces hard machine verification gates (`LibCST`/`parso`, `ruff`, `Hypothesis`, `pytest`), and persists a signed `RUN-STATE.json`.

## How to run (operator manual)

Run `scripts/anvil_engine.py` (or the Foundry Tool `python <path> cst-rewrite`):

1. **Programmatic 5-Stage Orchestrator (`orchestrate`):**
   ```bash
   python "<path> Foundry/skills/anvil/scripts/anvil_engine.py" orchestrate --old-repo <old_path> [--new-repo <new_path>] [--sign-off <fn_name>]... [--test-cmd "<cmd>"] --output <out.json>
   ```
   Executes the 5-stage state machine (`STAGE_0_ORANGE_SPLIT` -> `STAGE_1_CONCEPTUAL_MAP` -> `STAGE_2_EMPIRICAL_BLOCK_PROBES` -> `STAGE_3_CST_REMAP_AND_NULL_SPACE` -> `STAGE_4_DIFFERENTIAL_EQUIVALENCE_GATE`) and writes `.anvil/RUN-STATE.json`.

2. **Stage 0 — The Parable of the Oranges: Proactive Complete Staff Work & Essential Core Decomposition (`orange-split`):**
   ```bash
   python "<path> Foundry/skills/anvil/scripts/anvil_engine.py" orange-split --repo <path> --output <out.json>
   ```
   Modeled on the classic LDS General Conference story of the employee sent to buy oranges for the boss's wife's party: instead of returning empty-handed saying *"the market is out of oranges"* (or stopping at the first obstacle), the proactive employee asks *why* the oranges are needed, tracks down where fine oranges can be sourced, negotiates the terms, verifies quality, arranges delivery in time for the party, and returns having **solved the entire problem in one trip**. In Anvil, Stage 0 proactively probes the true downstream goal, anticipates blockers 2–3 steps ahead, separates Essential Domain Logic (`Do-Analysis` / `juice`), Surface Contracts (`Get-Data` & `Create-Output` / `peel`), and Legacy Scaffolding (`Null Space` candidates / `pith_and_seeds`), and delivers a complete, actionable recommendation in one pass.

3. **Mode 1 — Conceptual Groupings + Process Map + AI Agent Seams (`map`):**
   ```bash
   python "<path> Foundry/skills/anvil/scripts/anvil_engine.py" map --repo <path> --output <out.json>
   ```
   Partitions the codebase into human-meaningful **Conceptual Buckets** (with concise function summaries) and builds the **Block-to-Block Process Map** with explicit **AI Agent Interaction Badges** (`prompt_assembly`, `cli_dispatch`, `schema_gate`).

4. **Mode 2 — Single-Block Drill-Down + Empirical Claim Test (`inspect`):**
   ```bash
   python "<path> Foundry/skills/anvil/scripts/anvil_engine.py" inspect --repo <path> --block <block_id> [--test-cmd "<cmd>"] [--lock-description "<text>"] --output <out.json>
   ```
   Isolates a single code block, builds its **Inner Process Map** (`entry -> helpers -> exit`), pairs its plain-English **Claimed Intent** against **Empirical Execution** (`PASS` / `MISMATCH`), and records the user-approved **`✓ Validated` Description** into `ANVIL-REPORT.md`.

5. **Mode 3 — Best-in-Class Code Remapping, `∅ Null Space` & 3-Stage Pipeline Validation (`remap`, `cst-rewrite`, `verify-equivalence`):**
   ```bash
   python "<path> Foundry/skills/anvil/scripts/anvil_engine.py" remap --old-repo <old_path> --new-repo <new_path> --output <out.json>
   python "<path> Foundry/skills/anvil/scripts/anvil_engine.py" cst-rewrite --source <file.py> [--rename old:new] [--drop pith_fn]
   python "<path> Foundry/skills/anvil/scripts/anvil_engine.py" verify-equivalence --old-repo <old_path> --new-repo <new_path>
   ```
   Applies lossless `LibCST`/`parso` structural transformations, enforces the **`∅ Null Space`** ledger (`100%` accounted, zero silent drops), validates the 3-stage pipeline (**1. Getting the Data [`INGEST`]**, **2. Doing the Analysis [`COMPUTE`]**, **3. Creating the Output [`EMIT`]**), and proves differential behavioral equivalence via `Hypothesis` property-based vectors.

6. **Mode 4 — Paper-to-Code Mapping, Native MathML & Empirical Verification (`paper-map`):**
   ```bash
   python "<path> Foundry/skills/anvil/scripts/anvil_engine.py" paper-map --repo <path> --paper <paper_spec_or_md> --output <out.json>
   ```
   Maps paper equations (rendered in native HTML5 `<math>` MathML — never raw LaTeX strings), algorithms, and figures to implementing code functions, runs empirical verification harnesses, and prepares a production remap plan.

7. **Persistent Anvil Agent Dialogue (`chat`):**
   ```bash
   python "<path> Foundry/skills/anvil/scripts/anvil_engine.py" chat --repo <path> --mode <map|inspect|remap|paper-map> --target <id> --question "<text>"
   ```
   Answers context-grounded questions on any of the 4 Anvil pages and updates the validated comprehension ledger.

## Core Architecture & Invariants

### Stage 0: The Parable of the Oranges (Proactive One-Trip Problem Solving) & Programmatic Orchestration
- **The Parable of the Oranges:** In the classic LDS General Conference story, two employees are sent to get oranges for the boss's wife's party. The first returns empty-handed saying "there are no oranges in the market." The second asks *why* the oranges are needed (for the boss's wife's party), locates where quality oranges can be sourced, negotiates price and delivery, verifies quality, and returns with the **entire problem solved in one trip**. Anvil's Orchestrator and Agent follow this exact law: never stop at a surface symptom or dump raw AST errors back on the user — understand the true scientific/engineering purpose, think 2–3 steps ahead, separate Essential Core (`Do-Analysis`) and Surface I/O Contracts (`Get-Data` / `Create-Output`) from Legacy Scaffolding (`Null Space`), and present a complete, verified recommendation.
- `orchestrate_anvil` governs all 5 stages deterministically and writes `.anvil/RUN-STATE.json`.

### Mode 1: Conceptual Groupings & Block-to-Block Process Map (`ANV-01`, `ANV-02`)
- Every analyzed codebase is grouped into 4–9 human-digestible **Conceptual Buckets** (never raw alphabetical file lists).
- Every function inside a bucket carries a concise 1–2 sentence human summary of its role and inputs/outputs.
- Every block where an AI agent participates carries an explicit **AI Agent Interaction Badge** naming the agent/family, the interaction type, and the verification gate.

### Mode 2: Single-Block Drill-Down & Empirical Claim Testing (`ANV-03`, `ANV-04`, `ANV-05`)
- Clicking any block opens **only that block** with its **Inner Process Map**, plain-English **Claimed Intent**, and **Empirical Execution Harness**.
- Claims are never trusted from docstrings alone: the engine executes the block or its targeted test command and compares actual runtime behavior against the summary.
- Once refined with the user in the **Anvil Agent Dialogue**, locking the block stamps it **`✓ Validated`** and updates `ANVIL-REPORT.md`.

### Mode 3: Best-in-Class Code Remapping & Explicit `∅ Null Space` (`ANV-06`, `ANV-07`, `ANV-08`)
- Structural rewrites use lossless Concrete Syntax Trees (`LibCST` / `parso`) + `ruff` static gates (`cst_rewrite_module`) so comments and docstrings on untouched nodes are never destroyed.
- Any legacy block/function with no target in the new code lands in the **`∅ Null Space`** right beside the new code map. Accidental omissions fail closed (`BLOCKER`); intentional drops require explicit user sign-off.
- End-to-end validation verifies all three stages (**1. Getting the Data [`INGEST`]**, **2. Doing the Analysis [`COMPUTE`]**, **3. Creating the Output [`EMIT`]**) and runs `verify_behavioral_equivalence` (`Hypothesis` property-based vectors, `rtol=1e-7`).

### Mode 4: Paper-to-Code Mapping & Native Typeset Math (`ANV-09`, `ANV-10`, `ANV-11`)
- Maps paper equations, algorithms, and figures to exact code functions and line ranges.
- All mathematical equations render as native typeset MathML (`<math display="block">`), never raw LaTeX strings (`\sum`, `\frac`, `$$`).
- Includes a 1-click bridge from Paper-to-Code Audit into Mode 3 (`remap`) to transform research prototype scripts into production-grade best-in-class code.
