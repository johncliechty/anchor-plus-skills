# Anvil

**One sentence:** Programmatic codebase comprehension, **Parable-of-the-Oranges** proactive one-trip complete staff work (understanding the real goal, thinking 2–3 steps ahead, negotiating trade-offs, and returning with the entire problem solved), Essential Core vs. Scaffolding decomposition, single-block empirical claim testing, lossless `LibCST`/`parso` best-in-class code remapping (with an explicit `∅ Null Space`, Get-Data / Do-Analysis / Create-Output validation, and `Hypothesis` differential equivalence), and paper-to-code verification with a persistent Anvil Agent dialogue across every page.

## Use this when
- You want a **programmatic orchestrator** (not a loose LLM checklist) to govern code comprehension and refactoring through 5 deterministic machine-gated stages (`RUN-STATE.json`)
- You want an orchestrator and agent governed by the **Parable of the Oranges** (from the classic LDS General Conference talk where an employee sent to buy oranges for the boss's wife's party doesn't come back empty-handed saying *"the market is out of oranges,"* but proactively finds out *why* they are needed, locates quality oranges, negotiates price and delivery, and solves the entire problem in one trip)
- You want to click into a single block of code, see its inner process map and plain-English intent, and **run the code empirically** to verify whether what the summary says it does matches what it actually does
- You are refactoring or replacing legacy code with best-in-class code using lossless Concrete Syntax Trees (`LibCST` / `parso`), an explicit **`∅ Null Space`** audit of omitted legacy functionality, and `Hypothesis` property-based differential equivalence tests
- You have a research paper and a repository claiming to implement it, and you want to verify equation-by-equation (in native typeset MathML) and empirically whether the code actually matches the paper

## Do not use this when
- You only want a high-level strategic opinion on a prose document without code execution or structural mapping (use Gandalf)
- You are doing open-ended literature discovery across dozens of papers (use literature-review or researchPrime)
- You are running a multi-wave autonomous build from an already-frozen implementation plan (use Foreman)

## What you get
- **Programmatic Orchestrator (`anvil orchestrate`):** 5-stage state machine (`STAGE_0_ORANGE_SPLIT` -> `STAGE_1_CONCEPTUAL_MAP` -> `STAGE_2_EMPIRICAL_BLOCK_PROBES` -> `STAGE_3_CST_REMAP_AND_NULL_SPACE` -> `STAGE_4_DIFFERENTIAL_EQUIVALENCE_GATE`) writing `.anvil/RUN-STATE.json`
- **Parable of the Oranges & Essential Core Decomposition (`anvil orange-split`):** Proactively identifies the real downstream goal, anticipates obstacles 2–3 steps ahead, separates Essential Domain Logic (`Do-Analysis`), Surface I/O Contracts (`Get-Data` / `Create-Output`), and Legacy Scaffolding (`Null Space` candidates), and prepares a complete one-trip recommendation
- **Mode 1 (`anvil map`):** Synchronized **Conceptual Groupings** (with function-level summaries) + **Block-to-Block Process Map** with explicit **AI Agent Interaction Badges** (prompt assembly, CLI/API dispatch, schema/verdict gate)
- **Mode 2 (`anvil inspect`):** Single-block isolation with its **Inner Process Map**, plain-English intent, **live empirical claim runner** (`PASS ✓` / `MISMATCH ✗`), and a lockable **`✓ Validated` description** that rolls up into `ANVIL-REPORT.md`
- **Mode 3 (`anvil remap` / `cst-rewrite` / `verify-equivalence`):** Lossless `LibCST`/`parso` structural codemods + `ruff` hygiene check, **Old-to-New Mapping Matrix**, explicit **`∅ Null Space`** panel for unmapped legacy code, **3-Stage Pipeline Validation (`INGEST` -> `COMPUTE` -> `EMIT`)**, and `Hypothesis` differential equivalence verification
- **Mode 4 (`anvil paper-map`):** Paper-to-code mapping with **native typeset MathML equations** (never raw LaTeX strings), empirical + adversarial verification of paper claims, and a 1-click bridge to remap research prototype code into production best-in-class code
- **Persistent Anvil Agent Dialogue:** Available on all 4 pages so you can ask questions, refine block descriptions, challenge mappings, and lock validated comprehension at any point

## What it is not
- Not a passive employee that stops at the first missing dependency and says "there are no oranges in the market"
- Not a prose checklist handed to an agent without programmatic state or machine gates
- Not a raw Doxygen/Sphinx AST dump or a regex search-and-replace script that strips comments and docstrings

## How to start (human)
1. Launch Anvil from your AI Cockpit header (`Anvil` button with the official Blueprint-Crystal-Sword icon) or run `python scripts/anvil_engine.py orchestrate --old-repo <dir>`.
2. Review the **Parable of the Oranges** proactive brief and Essential Core decomposition, and browse the **Conceptual Groupings** and **Process Map** (Page 1).
3. Click any block to open **Single-Block Drill-Down** (Page 2), run the empirical claim check, and lock (`✓ Validated`) the block's description.
4. Use **Page 3 (Best-in-Class Remapping & Null Space)** when modernizing code with `LibCST` + `Hypothesis`, or **Page 4 (Paper-to-Code Mapping)** when auditing a research implementation.

## How it works
Anvil is driven by a deterministic Python orchestrator (`scripts/anvil_engine.py`) and backed by the `cst-rewrite` Foundry Tool (`python <path> cst-rewrite`). Stage 0 runs the Parable of the Oranges proactive assessment and AST/CST decomposition. Stage 1 partitions the codebase into human-sized conceptual buckets and traces inter-block control flow plus AI agent seams (`anvil-map.json`). Stage 2 traces intra-block call chains and executes empirical harnesses (`anvil-inspect.json`). Stage 3 applies lossless `LibCST`/`parso` transformations, enforces the `∅ Null Space` gate, and checks the 3-stage pipeline (`1. Get Data`, `2. Do Analysis`, `3. Create Output`). Stage 4 runs `Hypothesis` property-based differential equivalence tests to prove old and new implementations agree within tolerance (`rtol=1e-7`).

## Limits (honest)
- Empirical claim testing and differential equivalence execute code in a contained subprocess; blocks requiring external hardware or live production credentials need fixtures or mocks
- Cross-family adversarial review requires an active secondary model family in Anchor's seating preferences; when unavailable, stamps honestly record `cross_model: false`

## For agents / engines
Full protocol, schemas, and CLI commands live in `SKILL.md`, `references/RESEARCHPRIME-CODE-REWRITING-TOOLS.md`, and `scripts/anvil_engine.py` next to this file. Load `SKILL.md` when running the skill — this card is for people.
