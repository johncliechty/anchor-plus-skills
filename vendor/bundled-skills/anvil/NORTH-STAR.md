# ANVIL — Locked North Star & Idea Log

**Skill Path:** `skills/anvil/`  
**Date Locked:** 2026-10-14 (Rev 4 — Ratified 2026-11-14 with Polyglot Engine & Paper Section/Algorithm/MathML Mapper)  
**Author & Convergence Authority:** John  
**Visual Brand Asset:** `/vendor/brand/workbench-anvil.jpg` + Standard Anchor Mark (`/vendor/brand/anchor-tab-48.png`)

---

## 1. The Locked North Star (Exact Text)

> **ANVIL NORTH STAR (Rev 4 — Locked by John)**
>
> **Mission:** `Anvil` is the human-centered polyglot code comprehension, isolated empirical validation, best-in-class re-architecture, and paper-to-software verification skill. Instead of overwhelming the human with raw AST dumps, noisy call graphs, or fabricated badges, `Anvil` organizes code and scientific manuscripts around **human understanding**, **persistent repo-grounded dialogue**, **isolated subprocess execution proof (`shell=False`)**, and **honest old-to-new and paper-to-software equivalence**.
>
> **Five Core Pillars:**
>
> 1. **Polyglot Top-Level Mapping (`anvil map` / `facts` / `slice` — Import-Graph Deep Modules + AI Agent Touchpoints):**
>    - Scans Python, JavaScript/TypeScript (`.js`/`.mjs`/`.cjs`/`.ts`/`.tsx`), R, and C/C++ repositories cleanly and clusters files via package + import-graph community structure into 4–9 coherent architectural modules.
>    - Provides 3-Level Progressive Abstraction (`Level 1 Role & I/O` → `Level 2 All Member Files, Intra-Module Edges & Typed State Contracts` → `Level 3 Full On-Demand Per-File Numbered Source`) and highlights **AI Agent Seams** (CLI dispatch, prompt assembly, schema/verdict gates).
>
> 2. **Focused Block Drill-Down & Isolated Subprocess Claim Testing (`anvil inspect` / `walkthrough`):**
>    - Runs probes and test commands strictly inside isolated child subprocesses (`shell=False`, zero in-process module execution), stamping **`EXECUTED_PASS`** (`✓ Validated`) ONLY when a child run exits `0`, **`STATIC_ONLY`** when traced statically without live execution, and **`DIVERGENCE`** on non-zero exit or uncaught exception.
>
> 3. **Best-in-Class Code Remapping, Scope-Safe `LibCST` & Explicit `∅ Null Space` (`anvil remap` / `orange-split` / `cst-rewrite` / `verify-diff`):**
>    - Indexes 100% of symbol calls and references across production code AND `tests/`, classifying every function into `referenced_by_prod`, `referenced_by_tests_only`, or `truly_unreferenced` so `∅ Null Space` flags only genuinely unreferenced non-entrypoint helpers.
>    - Rewrites Python code via `LibCST` + `ScopeProvider` (preserving comments, strings, `obj.attr`, `fn(kw=1)`, and shadowed locals, with zero regex fallback), paired with **Aegis (`AEG-01..AEG-06`)** security scanning in Seat 5 of the 5-Seat Beta-Reader Panel.
>
> 4. **Paper Sections, Step-by-Step Algorithms & Native MathML Equations ⇄ Companion Software (`anvil paper-map`):**
>    - Parses `.tex` files, multi-file `.tex` trees (`\input`/`\include`), arXiv `/e-print/` source bundles, `.md`, and `.pdf` manuscripts into three first-class hierarchies: **`sections[]`**, **`algorithms[]`** (with step-by-step code ties, file/line spans, and matched variables), and **`equations[]`** (compiled into native `<math>` MathML with zero raw `$...$` LaTeX strings).
>    - Aligns every section, algorithm step, and equation against companion software modules, functions, AST variables, and mathematical operators (`EXECUTED_PASS`, `STATIC_ALIGNED`, `PARTIAL_OR_DRIFT`, `UNMAPPED_PAPER_CLAIM`), while surfacing `code_only_modules[]` for software infrastructure not described in the manuscript.
>
> 5. **Persistent Grounded Anvil Agent Dialogue Across All Modes:**
>    - Every page of the `Anvil` workbench features a persistent right-side Anvil Agent Dialogue Dock grounded directly in the live AST symbol table, Null Space ledger, Aegis findings, and Paper-to-Software alignment map (with zero canned Mad-Libs or fabricated test counts).

---

## 2. John's Requirement Ledger

| ID | Requirement / Idea | Where It Lives in `Anvil` |
| :--- | :--- | :--- |
| **ANV-01** | Orient for **human understanding** with import-graph-clustered Conceptual Modules and a System Process Map. | Mode 1 (`scripts/anvil_engine.py map` & `facts`) |
| **ANV-02** | Show **where AI agents interact and in what way** across the blocks of code. | Mode 1 (`ai_agent_touchpoints` badges & seam summaries) |
| **ANV-03** | Drill into any module/file with full Level 3 numbered source across **all** member files, never silently truncating multi-file clusters. | Mode 1/2 (`get_file_level3_source` & `/api/steward/anvil/source`) |
| **ANV-04** | Run code in an **isolated child subprocess (`shell=False`)** and stamp `EXECUTED_PASS` (`validated=True`) ONLY on exit code `0`. | Mode 2 (`inspect` & `walkthrough`) |
| **ANV-05** | **Repo-grounded Anvil dialogue** across all tabs + lockable validated descriptions rolling up into `ANVIL-REPORT.md`. | All 4 Modes (`anvil_chat` & `steward_cockpit/anvil_session.py`) |
| **ANV-06** | 5-Seat Beta-Reader Panel with **Seat 5 wired deterministically to Aegis (`AEG-01..AEG-06`)**. | `run_beta_reader_panel` (`../aegis/scripts/aegis_engine.py`) |
| **ANV-07** | Full-AST + `tests/` reference index preventing false dead-code flags, plus scope-safe `LibCST` rewriting. | Mode 3 (`extract_orange_split`, `remap`, `cst-rewrite`, `verify-diff`) |
| **ANV-08** | Validate 3-stage pipeline (`1. Get Data` → `2. Do Analysis` → `3. Create Output`) and child-subprocess differential equivalence. | Mode 3 (`remap` & `verify-equivalence`) |
| **ANV-09** | **Rich Paper Sections, Step-by-Step Algorithms & Native MathML Equations ⇄ Software** across `.tex` trees and arXiv `/e-print/` bundles. | Mode 4 (`paper-map` — `sections[]`, `algorithms[]`, `equations[]`, `code_only_modules[]`) |
