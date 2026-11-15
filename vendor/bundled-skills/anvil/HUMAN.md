# Anvil

**One sentence:** Honest polyglot codebase comprehension, **Parable-of-the-Oranges** proactive one-trip complete staff work, 3-Level Progressive Abstraction Map, isolated subprocess runtime walkthroughs, 5-Seat Software Beta-Reader + Aegis CWE security panel, scope-safe `LibCST` remapping with an explicit `∅ Null Space`, and rich **Paper Sections, Step-by-Step Algorithms & Native MathML Equations ⇄ Companion Software** verification.

## Use this when
- You want a **programmatic polyglot engine** (`Python`, `JS/TS/MJS`, `R`, `C/C++`) that clusters a codebase into 4–9 coherent Deep Modules using its real package and import graph rather than keyword buckets
- You want an orchestrator and agent governed by the **Parable of the Oranges**—separating Essential Domain Logic (`Juice`), Surface I/O Contracts (`Peel`), and truly unreferenced helpers (`∅ Null Space`, indexed across both production ASTs and `tests/`)
- You want to drill into any module or file (`Level 1 Role` → `Level 2 Contracts & Sub-Flow` → `Level 3 Full Numbered Source`) and run isolated child-subprocess checks (`EXECUTED_PASS` | `STATIC_ONLY` | `DIVERGENCE`) without in-process code execution or shell injection
- You are refactoring code with scope-safe Concrete Syntax Trees (`LibCST` + `ScopeProvider`) and isolated differential equivalence probes
- You have a scientific paper (`.tex` manuscript tree, arXiv ID / `/e-print/` bundle, `.md`, or `.pdf`) and companion software, and want to see every **Paper Section**, **Step-by-Step Algorithm**, and **Native MathML Equation** mapped directly to exact code files, functions, line spans, and variables

## Do not use this when
- You only want a strategic prose review of a memo or policy document with no software or formal algorithm (use Gandalf)
- You are running broad multi-paper literature discovery across dozens of external citations (use literature-review or researchPrime)
- You are executing an already-planned multi-wave build (use Foreman — which calls `anvil_engine.py slice` and `verify-diff` automatically as helper gates)

## What you get
- **Fast Agent & Trio Primitives (`facts`, `slice`, `verify-diff`):** `<50 KB` repo facts in `<2s`, `<15 KB` file AST slices in `<1s`, and post-edit AST syntax + duplicate-definition + dead-helper + Aegis security verification in `<2s`
- **Mode 1 (`map`):** Import-graph-clustered Deep Modules + 3-Level Progressive Abstraction + AI Agent Seam badges
- **Mode 2 (`inspect` / `walkthrough`):** Isolated child-subprocess claim verification (`shell=False`) stamping `EXECUTED_PASS` only when tests/probes exit `0`, and `STATIC_ONLY` when unexecuted
- **Mode 3 (`orange-split` / `remap` / `cst-rewrite` / `verify-equivalence`):** Full-AST + `tests/` reference indexing (`referenced_by_prod`, `referenced_by_tests_only`, `truly_unreferenced`), scope-safe `LibCST` codemods, 3-stage pipeline check (`INGEST` → `COMPUTE` → `EMIT`), and child-subprocess differential equivalence
- **Mode 4 (`paper-map`):** Recursive `.tex` (`\input`/`\include`) & arXiv `/e-print/` parser extracting `sections[]`, `algorithms[]` (with step-by-step code ties), `equations[]` (native `<math>` MathML, zero raw `$...$` LaTeX), and `code_only_modules[]`
- **5-Seat Beta-Reader Panel (`beta-readers`):** Grounded in Cal Newport, John Ousterhout, Gary Bernhardt, reference hygiene, and **Aegis (`AEG-01..AEG-06`)** security scanning

## What it is not
- Not a regex text-replacer that corrupts comments, string literals, object attributes, or keyword arguments
- Not an optimistic dashboard that stamps unexecuted code `Validated` or fabricates test counts
- Not limited to Python—scans Python, JavaScript/TypeScript (`.js`/`.mjs`/`.cjs`/`.ts`/`.tsx`), R, and C/C++

## How to start (human)
1. Launch **Anvil** from your Anchor AI Cockpit header or run `python scripts/anvil_engine.py map --repo <dir>` from the `anvil` skill directory.
2. Explore the **3-Level Progressive Process Map** (`Level 1 Role` → `Level 2 Contracts & Sub-Flow` → `Level 3 Full Per-File Source`) and **5-Seat Beta-Reader + Aegis Panel**.
3. Attach a companion `.tex` path, PDF, or arXiv ID (e.g. `arXiv:2401.12345`) to inspect **Paper Sections, Algorithms & Native MathML Equations ⇄ Software**.
4. Use **Single-Block Drill-Down** or **Old-to-New Remapping & Null Space** to verify runtime behavior and safely refactor legacy helpers.

## How it works
Anvil runs deterministically through `scripts/anvil_engine.py` (stdlib polyglot AST + import-graph clustering, isolated `shell=False` child-subprocess execution, sibling `../aegis/scripts/aegis_engine.py` CWE taint/sink scanning, recursive-descent LaTeX-to-MathML compilation, and `libcst` scope-aware rewriting). Inside Anchor's AI Cockpit (`steward_cockpit/anvil_session.py`), Anvil caches `.anvil/session.json`, serves fast `<15 KB` summary polls (`?summary=1`), streams full untruncated per-file Level 3 source on demand (`/api/steward/anvil/source`), and safely extracts arXiv `/e-print/` `.tex` bundles with strict path-containment guards.

## Limits (honest)
- Runtime walkthroughs and differential equivalence execute in isolated child subprocesses; modules requiring external GPUs, databases, or credentials remain honestly stamped `STATIC_ONLY` until a test command or fixture is supplied
- Scope-safe Python AST/CST rewriting requires `libcst` installed in the Python environment; when `libcst` is absent, `cst-rewrite` refuses cleanly rather than falling back to unsafe regex edits

## For agents / engines
Full protocol, CLI subcommands, and schemas live in `SKILL.md`, `NORTH-STAR.md`, `references/RESEARCHPRIME-CODE-REWRITING-TOOLS.md`, and `scripts/anvil_engine.py` next to this file.
