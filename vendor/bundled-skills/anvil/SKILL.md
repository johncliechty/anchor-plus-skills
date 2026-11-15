---
name: Anvil
description: Programmatic codebase comprehension, Parable-of-the-Oranges proactive one-trip complete staff work, 3-Level Progressive Abstraction Map (Level 1 Role & I/O -> Level 2 Sub-flow, Native MathML Formulas, Explicit Assumptions & Old-to-New Diff -> Level 3 Full Numbered Source), Isolated Subprocess Polyglot Code Walkthrough (Claimed vs. Actual Runtime Verification), 5-Seat Software Beta-Reader Panel (grounded in Cal Newport cognitive-load reduction, John Ousterhout Deep Modules, Gary Bernhardt Functional Core / Imperative Shell, and Aegis CWE security scanning), scope-safe LibCST remapping with explicit Null Space, and Paper Section/Algorithm/MathML-to-Software verification.
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

**THE VERIFICATION LAW** (added 2026-08-15 after its FOURTH recurrence — each of
the first three was written into a journal and recurred anyway):

6. **Verify the claim you actually made, on the surface he actually uses.**
   "It's live / fixed / renders" is a claim about HIS screen. That the server
   emits new bytes, that a build exited zero, or that assertions passed are
   claims about something else. Render it and look at it.
7. **A symptom reported twice retires the first explanation.** Test the
   hypothesis; never repeat it. An explanation that makes his report false
   ("it's your cache", "it's a data issue") needs MORE evidence, not less.
8. **Prefer a mechanism to an instruction.** If the same instruction is given
   every session, the instruction is the defect — build what removes it.
9. **A correction that lives only in a journal or a memory has not been made.**
   Promote it to where it is loaded BEFORE the work starts.

**Two laws these serve.** A gate that cannot see what the user sees is not a gate
— structure diffs are lints, and must be labelled as lints. And a guardrail is
never the whole product of a turn — if enforcement withholds output he already
paid for, show it anyway.
<!-- ELEGANCE-V2.1 addendum -->
**What elegance IS (researchPrime-vetted, 2026-08-15):** the largest result
carried by the least machinery its user can actually hold — every element
forced by an INDEPENDENT citable need, nothing present the objective does not
pay for. Earned by iteration, never by skipping work: as simple as the task
allows, no simpler than a single datum permits.

**The Rabbit-Catcher (canonical battery: `ELEGANCE.md` Part II, ships with
the bundle):** the steering seat runs the full RC battery at PLAN APPROVAL
and on any NEW mid-run element; round boundaries ask only RC-6 ("still on the
critical path?"). Uncertain ⇒ PARK the element (zero further spend) + one
batched line in the next block the user already reads — never silent pursuit,
never ad-hoc interruption. Needs and hazards must be independent of their
proposer (no self-authored justification records); malleability work is
never cut as "unused capability"; guards are judged by RC-G, never by
retirement. Verdicts: KEEP / HOLD (with written trigger or budget) / CUT
(logged).

**THE SPEAKING LAW (John, 2026-08-16 — ELEGANCE.md Part III):** every ask,
HALT, or summary this skill puts to the user describes the DECISION, never
the machinery (a gate ask took FOUR attempts because it kept narrating waves
and gates); a few plain sentences carrying the two-three details that matter
+ where the full detail lives; genuinely complicated content goes in NUMBERED
BATCHES, one at a time, each ending "OK so far?"; no seat/stamp/gate
vocabulary in the sentence the user must read; every ask ends with a question
answerable in one word AND carries a recommendation (what you would choose +
one line of why + alternatives when the choice has them + "or tell me
something else" — options are a convenience, never a cage).
<!-- /ELEGANCE-V2.1 -->
<!-- /ELEGANCE-LAW -->

> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol; the locked objective lives in `NORTH-STAR.md`.

# Anvil — Honest Polyglot Code Comprehension, Progressive Abstraction, Subprocess Walkthrough, Beta-Reader & Paper-to-Software Engine

## North Star

`Anvil` is the human-centered polyglot code comprehension, isolated empirical verification, scope-safe refactoring, and paper-to-software mapping engine. Every claim Anvil makes is earned in deterministic AST/CST code or an isolated child subprocess (`shell=False`), never fabricated:
- **Polyglot Import-Graph Clustering & Full-Repo Reference Indexing:** Clusters Python, JavaScript/TypeScript (`.js`/`.mjs`/`.cjs`/`.ts`/`.tsx`), R, and C/C++ repositories into 4–9 coherent Deep Modules, indexing 100% of cross-repo + `tests/` symbol references so `∅ Null Space` flags only genuinely unreferenced non-entrypoint helpers.
- **Honest Runtime Verdicts (`EXECUTED_PASS` | `STATIC_ONLY` | `DIVERGENCE`):** Runs runtime probes and test commands strictly in isolated child subprocesses (`shell=False`, zero in-process module execution), stamping `EXECUTED_PASS` (`validated: true`) only when a child process exits `0`.
- **Rich Paper Sections, Step-by-Step Algorithms & Native MathML Equations ⇄ Companion Software (`paper-map`):** Recursively parses `.tex` trees (`\input`/`\include`), arXiv `/e-print/` source bundles, `.md`, and `.pdf` manuscripts into `sections[]`, `algorithms[]` (with step-by-step code ties), and `equations[]` (compiled into native `<math>` MathML with zero raw `$...$` LaTeX), scoring every paper artifact against companion software modules, functions, AST variables, and math operators.
- **Fast Sub-2s Agent Primitives (`facts`, `slice`, `verify-diff`):** Gives Crucible, Foreman, and code-job workers compact `<50 KB` architectural JSON, `<15 KB` file AST slices, and deterministic post-edit syntax/duplicate-def/dead-helper/Aegis CWE verification.

---

## 1. Mission & Core Architecture

1. **3-Level Progressive Abstraction on Every Process-Map Module**:
   - **Level 1 (`level1_summary` — High-Level Role & I/O):** Plain-English purpose, typed inputs/outputs, pipeline stage (`INGEST` / `COMPUTE` / `EMIT`), Functional-Core purity percentage, AI/LLM touchpoint count, and Orange role (`CORE` Juice vs. `CONTRACT` Peel vs. `SCAFFOLDING` Null Space).
   - **Level 2 (`level2_mechanics` — Member Files, Sub-Flow, State Contracts & Native MathML):** Complete list of member files, intra-module call edges, typed class/function state contracts, explicit engineering invariants, and native `<math>` formulas (emitted only when actual mathematical AST operations or mapped paper equations exist).
   - **Level 3 (`level3_code` — Full On-Demand Per-File Numbered Source):** Complete per-file index (`files_index`) plus untruncated line-numbered source, AST symbol table, callers, and callees via `get_file_level3_source`.
2. **Isolated Subprocess Polyglot Code Walkthrough (`walkthrough` / `--walkthrough`):**
   - Steps through modules in execution order (`Ingest` → `Compute` → `Emit`) inside isolated child subprocesses (`python -c`, `pytest`, `node --test`, `Rscript`) with `shell=False` and `CREATE_NO_WINDOW`, stamping `EXECUTED_PASS`, `STATIC_ONLY`, or `DIVERGENCE`.
3. **5-Seat Software Beta-Reader Panel (`beta-readers`):**
   - `cal_newport_cognitive_load` — Cal Newport & John Ousterhout Cognitive Load & Deep Modules Auditor
   - `functional_core_architect` — Gary Bernhardt Functional Core / Imperative Shell Architect
   - `numerical_verification_auditor` — Empirical & Reference Hygiene Auditor
   - `systems_performance_specialist` — Systems Performance & Idiom Specialist
   - `security_boundary_auditor` — Deterministic Aegis CWE/OWASP (`AEG-01..AEG-06`) Security Boundary Auditor (`../aegis/scripts/aegis_engine.py`)
4. **Parable of the Oranges One-Trip Staff Work, Scope-Safe `LibCST` & Explicit Null Space (`orange-split` / `remap` / `cst-rewrite`):**
   - Separates **Juice** (Pure Domain Compute), **Peel** (Surface I/O Contracts), and **Pith & Seeds** (`truly_unreferenced` non-entrypoint Null Space), and rewrites Python modules via `libcst` + `MetadataWrapper` + `ScopeProvider` (preserving comments, strings, `obj.attr`, `fn(kw=1)`, and shadowed locals; refusing cleanly without regex fallback if `libcst` is absent).

---

## 2. Programmatic CLI Usage (`scripts/anvil_engine.py`)

Run from the `anvil` skill root (or pass the path to `scripts/anvil_engine.py`):

```powershell
# Fast Trio / Code-Job Primitives (<2s)
python scripts/anvil_engine.py facts --repo "<repo>" --json
python scripts/anvil_engine.py slice --repo "<repo>" --files "<rel1>" "<rel2>" --json
python scripts/anvil_engine.py verify-diff --repo "<repo>" --files "<rel1>" --json

# Mode 4: Paper Sections, Step-by-Step Algorithms & Native MathML <-> Software
python scripts/anvil_engine.py paper-map --repo "<code_dir>" --paper "<main.tex_or_dir>" --json

# Mode 1–3: Progressive Map, Subprocess Walkthrough, Beta-Readers, CST Rewrite & Orchestrator
python scripts/anvil_engine.py map --repo "<repo>" --json
python scripts/anvil_engine.py walkthrough --repo "<repo>" --block "<block_id>" --json
python scripts/anvil_engine.py beta-readers --repo "<repo>" --json
python scripts/anvil_engine.py inspect --repo "<repo>" --block "<block_id>" --test-cmd "pytest -q" --json
python scripts/anvil_engine.py orange-split --repo "<repo>" --json
python scripts/anvil_engine.py cst-rewrite --source "<file.py>" --rename "old_fn:new_fn" --drop "dead_helper"
python scripts/anvil_engine.py orchestrate --old-repo "<old_dir>" --new-repo "<new_dir>"
python scripts/anvil_engine.py render-report --repo "<repo>" --output "<out>/ANVIL-REPORT.md"
```

---

## 3. Paper Sections, Step-by-Step Algorithms & Native MathML Equations ⇄ Companion Software

`paper-map` (`paper_to_code_map`) extracts three first-class hierarchies from single `.tex` files, multi-file `.tex` trees (`\input`/`\include`), extracted arXiv `/e-print/` tarballs, `.md`, or `.pdf` manuscripts and aligns them deterministically against companion code without round-robin/modulo assignment:
1. **`sections[]`:** Manuscript section hierarchy (`\section`, `\subsection`, `\subsubsection`), prose summary, child `equation_ids` and `algorithm_ids`, matched software modules/functions, and verification status.
2. **`algorithms[]`:** Formal `\begin{algorithm}` / `\begin{algorithmic}` blocks and procedural numbered derivations (`procedural_section`), decomposed into ordered `steps[]` with inline `<math>` fragments, matched functions, file/line spans, matched variables, and step confidence.
3. **`equations[]`:** Display equations (`equation`, `align`, `gather`, `\[...\]`, `$$...$$`) compiled via recursive-descent LaTeX-to-MathML into valid `<math xmlns="http://www.w3.org/1998/Math/MathML" display="block">`, symbol-to-variable tables, ranked `matched_functions` (scored by symbol overlap, math operator AST signatures, docstring citations, and domain terminology), and honest alignment verdicts (`EXECUTED_PASS`, `STATIC_ALIGNED`, `PARTIAL_OR_DRIFT`, `UNMAPPED_PAPER_CLAIM`), plus `code_only_modules[]` for software infrastructure not described in the manuscript.

---

## 4. Mandatory Pedagogical & Visual Report Standard

Every human-facing `ANVIL-REPORT.md` (and companion paper-to-software audit report) MUST include:
1. **Up-Front Plain-English Glossary & Visual Concept Primer:** Define central domain, mathematical, and architectural terms in plain English with a concrete miniature example before diving into internals.
2. **Genuine Graphical Diagrams (`figure-designer` Compliance — Never Text-Wall SVG Cards):** Render clean, high-contrast vector flowcharts, coordinate plots, and proportional module diagrams (`<= 6` words per label, `>= 10px` sans-serif typography).
3. **End-to-End Execution & Complexity Trace:** Trace both forward data transformations and reverse/feedback or error-propagation paths across modules with explicit time/space complexity notes.
4. **Dual Canonical Maps for Scientific Software:**
   - **Map 1 — Paper-to-Software Map (`sections[]` & `equations[]` ⇄ Files & Symbols)** with explicit side-by-side comparison of paper notation vs. code implementation.
   - **Map 2 — Step-by-Step Algorithm Math ⇄ Verbatim Code Execution Map (`algorithms[].steps[]`)** tracing Step 1 → Step $K$ against exact files and line spans.
5. **Einstein 4-Block Pedagogical Progression:** Structure sections as *(a) Plain-English Intuition → (b) Small Worked Example → (c) Visual Diagram → (d) Verified Codebase Evidence & One-Line Takeaway*.
