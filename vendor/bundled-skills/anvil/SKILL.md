---
name: Anvil
description: Programmatic codebase comprehension, Parable-of-the-Oranges proactive one-trip complete staff work, 3-Level Progressive Abstraction Map (Level 1 Role & I/O -> Level 2 Sub-flow, Native MathML Formulas, Explicit Assumptions & Old-to-New Diff -> Level 3 Full Numbered Source), Live Polyglot Code Walkthrough (Claimed vs. Actual Runtime Verification), 5-Seat Software Beta-Reader Panel (grounded in Cal Newport cognitive-load reduction, John Ousterhout Deep Modules, and Gary Bernhardt Functional Core / Imperative Shell), lossless LibCST/parso remapping with explicit Null Space, and paper-to-code verification.
---

# Anvil v2 — Programmatic Code Comprehension, Progressive Abstraction, Live Walkthrough & Software Beta-Reader Engine

## 1. Mission & Core Architecture

**Anvil (`v2`)** is the programmatic code comprehension, mathematical verification, and architectural refactoring engine of the Skill Foundry portfolio. It eliminates the need to open multiple tabs or jump between pages by organizing every codebase and scientific paper into a **Single-Surface Progressive Process Map**:

1. **3-Level Progressive Abstraction on Every Process-Map Node**:
   - **Level 1 (`level1_summary` — High-Level Role & I/O):** Plain-English purpose, inputs, outputs, pipeline stage (`INGEST` / `COMPUTE` / `EMIT`), and Orange role (`CORE` Juice vs. `CONTRACT` Peel vs. `SCAFFOLDING` Pith/Seeds).
   - **Level 2 (`level2_mechanics` — Internal Sub-Flow, Native MathML Equations, Assumptions & Old→New Diff):** Step-by-step inner function flow, native `<math>` equations, explicit mathematical/engineering assumptions, and Old-to-New Best-in-Class diff summary with cognitive-load reduction percentage.
   - **Level 3 (`level3_code` — Full Source Code):** Numbered line-by-line original source code alongside the clean Functional Core / Imperative Shell refactored source preview.
2. **Live Polyglot Code Walkthrough & Claim-vs-Reality Validator (`walkthrough` / `--walkthrough`):**
   - Steps through each block on the Process Map in execution order (`Ingest` $\to$ `Compute` $\to$ `Emit`), running or tracing concrete inputs against `Python`, `R`, `JS/Node`, and `C/C++` modules and comparing **Claimed Behavior** (docstring / paper equation) against **Actual Runtime Calculation & Output** (`ACCURATE` | `DRIFT` | `MISMATCH`).
3. **5-Seat Software Beta-Reader Panel (`beta-readers`):**
   - Inspired by **Chekhov's** beta-reader panel and grounded in **Cal Newport** (*Slow Productivity* / *A World Without Email* cognitive-load & context-switch reduction), **John Ousterhout** (*A Philosophy of Software Design* Deep Modules), and **Gary Bernhardt** (*Functional Core, Imperative Shell*):
     - `cal_newport_cognitive_load` — Cognitive Load & Context-Switch Auditor
     - `functional_core_architect` — Functional Core / Imperative Shell Architect
     - `numerical_verification_auditor` — Runtime & Numerical Verification Debugger
     - `systems_performance_specialist` — Systems Performance & Idiom Specialist
     - `security_boundary_auditor` — Defensive Security & Input Boundary Auditor
4. **Parable of the Oranges One-Trip Staff Work & Explicit Null Space (`orange-split` / `remap`):**
   - Grounded in **The Parable of the Oranges** (when the boss's wife asks to buy oranges at the market, a proactive staff member gathers price, variety, stock, and delivery details in **one trip** instead of making repeated follow-up trips), Anvil separates **Juice** (Essential Domain Logic), **Peel** (Surface I/O Contracts), and **Pith & Seeds** (`∅ Null Space` dead/legacy code requiring explicit human sign-off).

---

## 2. Programmatic CLI Usage (`scripts/anvil_engine.py`)

```powershell
# 1. Full 5-Stage Orchestrator State Machine (writes .anvil/RUN-STATE.json & .anvil/manifest.json)
python "<path> Foundry\skills\anvil\scripts\anvil_engine.py" orchestrate --old-repo "<path>" --new-repo "<path>"

# 2. Mode 1 + Anvil v2 3-Level Progressive Map, Beta-Reader Panel & Walkthrough Trace
python "<path> Foundry\skills\anvil\scripts\anvil_engine.py" map --repo "<path>"

# 3. Live Polyglot Code Walkthrough (Claimed vs. Actual Runtime)
python "<path> Foundry\skills\anvil\scripts\anvil_engine.py" walkthrough --repo "<path>"
python "<path> Foundry\skills\anvil\scripts\anvil_engine.py" --walkthrough --repo "<path>"

# 4. 5-Seat Software Beta-Reader Panel
python "<path> Foundry\skills\anvil\scripts\anvil_engine.py" beta-readers --repo "<path>"

# 5. Standalone Illustrated Markdown Report (with Inline SVGs, Beta-Readers & Walkthrough Table)
python "skills/anvil/scripts/anvil_engine.py" render-report --repo "." --output "ANVIL-REPORT.md"
```

---

## 3. Mandatory Pedagogical & Visual Report Standard (`Einstein` + `Gandalf` + `Figure-Designer` + `Ramanujan`)

Every human-facing `ANVIL-REPORT.md` / `ANVIL-REPORT.pdf` (and companion paper-to-code evaluation report) MUST include the following five structural pillars:

1. **Up-Front Plain-English Glossary & Visual Concept Primer**:
   - Right after the plain-English executive summary and 60-second roadmap table, include a dedicated **Key Terms & Visual Definitions Primer** that defines every central mathematical, statistical, and architectural term in simple, concrete language, paired with a miniature numerical example and a visual diagram (`Figure 0`).
2. **Genuine Graphical Plots & Diagrams (`figure-designer` Compliance — Never Text-Wall SVG Cards)**:
   - Every SVG figure must be a real visual graph or diagram: plotted 2D contours/curves (e.g., Gaussian vs. Neal's funnel contours), block-sparse matrix heatmaps/grids, directed forward + backward computation flowcharts, schedule trajectories, and proportional bar/line charts with coordinate axes. Keep in-figure text labels short (`<= 6` words per label, `>= 10px` sans-serif typography) and put detailed prose explanations in the surrounding text and caption.
3. **Explicit Forward Pass + Backward Pass (Backpropagation) Block Complexity Trace**:
   - When auditing variational inference, normalizing flows, or block-structured optimization algorithms, explicitly explain and diagram how **both** the **Forward Pass** (parallel base-noise draw, root-to-leaf block conditioning, triangular $\log|\det J|$, and objective evaluation) and the **Backward Pass** (parallel reverse-mode gradient backpropagation $\nabla_\phi \mathcal{L}$ across decoupled local blocks plus parent gradient sum-reduction) execute in parallel across blocks to achieve true $\mathcal{O}(p)$ time and memory scaling.
4. **The Two Canonical Maps (Visual Diagrams + Complete Reference Tables)**:
   - **Map 1 — Paper-to-Software Map (Sections, Equations & Tables $\leftrightarrow$ Files & Symbols)**: Visually and tabularly connects every manuscript section, equation, and benchmark table to its exact production file, class/function symbol, and line span. Always audit `.anvil/session.json`'s automated token-overlap equation matches and explicitly display the **Automated Heuristic Match vs. Domain-Verified Production Symbol** correction table alongside any differences between how the paper describes the algorithm and how the software implements it.
   - **Map 2 — Step-by-Step Formal Algorithm Math $\leftrightarrow$ Verbatim Code Execution Map**: Traces the complete algorithm in execution order (Step 1 $\to$ Step $K$), showing side-by-side: (i) the **Execution Step & Purpose**, (ii) the **Formal Mathematical Formula**, (iii) the **Exact Verbatim Code Expression & File/Line Citation**, and (iv) the **Per-Step Complexity ($\mathcal{O}(p)$ verification)**.
5. **Einstein 4-Block Pedagogical Progression Inside Every Section**:
   - Structure each section as: *(a) Plain-English Intuition $\to$ (b) Small Worked Toy Example (tied out to deterministic ground-truth checks where applicable) $\to$ (c) Graphical Vector Figure $\to$ (d) Verified Codebase Evidence, 5-Seat Beta-Reader / Walkthrough Tie-Out & One-Line Takeaway*.

