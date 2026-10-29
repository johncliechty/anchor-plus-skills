# researchPrime Synthesis: Best-in-Class Programmatic Code-Rewriting Tools & The Parable of the Oranges (`Anvil` Mode 3 & Orchestrator)

**Evidence Stamp:** `OBSERVED` + `CORROBORATED` (Empirical tool benchmarking & CST/AST literature synthesis, archived 2026-10-14 for `Anvil` in Skill Foundry).

---

## 1. Why Naive Agent Line-Editing Fails on Legacy & Vibe-Coded Codebases

When an AI agent rewrites or refactors an existing module using raw text replacement or ad-hoc regex scripts, three failure modes dominate:
1. **The 50%-Compromise Frankenstein (Violating the Parable of the Oranges):** The agent preserves half of the legacy scaffolding while bolting on a new abstraction, duplicating state and leaving dead fallback paths ("Null Space") intact.
2. **Formatting, Comment, and Docstring Destruction:** Standard Abstract Syntax Trees (`ast.parse` -> `ast.unparse`) discard comments, docstrings, blank lines, and parentheses, producing massive noisy diffs that fail adversarial review.
3. **Silent Behavioral Drift:** Without deterministic pre/post input-output pinning and property-based differential equivalence tests (`Hypothesis` + `pytest`), subtle edge cases (rounding, NaN handling, ordering, error returns) change silently during refactoring.

---

## 2. The Parable of the Oranges ("Peel vs. Juice vs. Pith/Seeds" Decomposition)

In classic integrative negotiation (Fisher, Ury & Patton; Mary Parker Follett), two sisters quarrel over a single orange and split it 50/50—only to discover one sister wanted **only the peel/zest** to bake a cake (throwing away her half of the pulp), while the other wanted **only the juice/pulp** to drink (throwing away her half of the peel). By failing to separate *underlying functional purpose* from *surface form*, both got half of what they needed.

In **Anvil**, every module, class, and function is deterministically decomposed into three disjoint sets before a single line of replacement code is written:

| Orange Layer | Software Meaning | Anvil Orchestrator Action |
|---|---|---|
| **1. The Juice (Essential Domain / Mathematical Logic)** | Pure state transitions, mathematical equations, invariants, and business rules (`Do-Analysis`). | **Preserve & Verify 100%:** Pin with differential property-based equivalence tests (`Hypothesis` + `pytest`) so old Juice and new Juice agree to machine precision (`rtol=1e-7`) across boundary inputs. |
| **2. The Peel / Zest (Essential Surface Contract & I/O Boundary)** | Public API signatures, CLI flags, schema contracts, file formats, and rendering interfaces (`Get-Data` & `Create-Output`). | **Keep Thin & Explicit:** Separate cleanly from internal calculation; enforce strict schema/type validation at the boundary (`pyright` / `ruff`). |
| **3. The Pith & Seeds (Incidental Legacy Scaffolding / Null Space)** | Dead branches, copy-pasted boilerplate, abandoned experiment flags, defensive workarounds for bugs that no longer exist, and vibe-coded spaghetti glue. | **Classify to Null Space Ledger & Excise:** Every line of Pith/Seeds must be explicitly cataloged in the **Null Space Ledger** (`INTENTIONALLY_DROPPED_OBSOLETE` or `CONSOLIDATED_INTO_BLOCK`) so nothing is silently forgotten and zero dead scaffolding survives into the new build. |

---

## 3. Best-in-Class Programmatic Code-Rewriting & Verification Stack

Based on `researchPrime` evaluation across Python, TypeScript/JavaScript, and polyglot AST/CST ecosystems, `Anvil` standardizes on a 4-layer programmatic toolchain:

### Layer A — Lossless Concrete Syntax Tree (CST) & Structural Rewriting
| Tool | Role in `Anvil` | Why Best-in-Class (`OBSERVED`) |
|---|---|---|
| **`LibCST`** (`libcst`) | Primary Python lossless CST transformer & codemod engine (`CSTTransformer`, `MatcherDecoratableTransformer`, `MetadataWrapper` with `ScopeProvider` & `QualifiedNameProvider`). | Parses Python into a lossless Concrete Syntax Tree that preserves **100% of comments, whitespace, parentheses, and formatting** on untouched nodes while allowing type-safe, scope-aware structural transformations. |
| **`parso`** | Fault-tolerant Python CST parser & round-trip tokenizer. | Recovers gracefully even on partially broken or syntax-error legacy files and guarantees exact byte-for-byte round-tripping (`module.get_code() == source`). |
| **`ast` (Python stdlib)** | Fast semantic call-graph, cyclomatic complexity, import-graph, and `Get-Data` / `Do-Analysis` / `Create-Output` purity classification. | Zero-dependency, microsecond-speed semantic inspection for `Anvil` Mode 1 (`map`), Mode 2 (`inspect`), and `orange_split`. |
| **`ast-grep` (`sg`) / Tree-sitter** | Polyglot structural search & rewrite rules (Python, JS/TS, Rust, Go, C++) via YAML rule manifests. | Matches AST patterns (`pattern: $OBJ.old_api($ARG)`) across languages without brittle regexes. |

### Layer B — Static Analysis, Linting, and Type-Boundary Gates
| Tool | Role in `Anvil` | Why Best-in-Class (`OBSERVED`) |
|---|---|---|
| **`Ruff`** (`python -m ruff`) | Sub-second linter, dead-code detector (`F401`, `F841`, `ERA001`), import sorter, and autofixer (`ruff check --fix`). | 100x faster than Flake8/Black; catches unused imports, shadowed variables, and unreachable code immediately after a CST transform. |
| **`Pyright` / `mypy`** | Static type-contract verification on the **Peel** (public signatures & return types). | Guarantees that refactored modules honor their declared type contracts before runtime tests even start. |

### Layer C — Differential Behavioral Equivalence & Property-Based Pinning
| Tool | Role in `Anvil` | Why Best-in-Class (`OBSERVED`) |
|---|---|---|
| **`Hypothesis`** (`hypothesis`) | Property-based input generator (`st.floats`, `st.lists`, `st.dictionaries`, `st.text`) for differential equivalence harnesses. | Automatically searches for edge cases (`0.0`, `-0.0`, `NaN`, empty collections, boundary ints) where `legacy_fn(x) != new_fn(x)` and shrinks counterexamples to minimal reproducers. |
| **`pytest`** | Deterministic test runner executing `Anvil`'s generated `test_anvil_equivalence_<module>.py` suite. | Enforces hard exit-code `0` gate in the `Anvil` orchestrator before any stage can advance. |

---

## 4. Integration into Foundry Tools (`ft.py cst-rewrite`) and `anvil_engine.py`

To ensure agents never write ad-hoc regex refactoring scripts by hand:
1. **`python <path> cst-rewrite`** provides a fast, logged Foundry Tool for:
   - `--orange-split <file_or_dir>`: Runs the Parable of the Oranges AST/CST decomposition (**Peel**, **Juice**, **Pith/Seeds**), outputting exact symbol classifications and a ready-to-audit Null Space Ledger.
   - `--rename <old:new>` / `--transform <rule.json>`: Runs a lossless `LibCST` / `parso` structural codemod while preserving comments and docstrings, followed by `ruff check`.
   - `--verify-equivalence <old_mod:fn> <new_mod:fn>`: Runs a deterministic `Hypothesis` + `pytest` differential equivalence harness comparing outputs, exceptions, and numerical tolerance (`rtol=1e-7`) across generated and seed inputs.
2. **`anvil_engine.py orchestrate`** runs the 5-stage programmatic state machine (`STAGE_0_ORANGE_SPLIT` -> `STAGE_1_CONCEPTUAL_MAP` -> `STAGE_2_EMPIRICAL_PROBES` -> `STAGE_3_CST_REMAP` -> `STAGE_4_EQUIVALENCE_AND_SHARK_GATE`), persisting `RUN-STATE.json` and refusing to advance unless every machine gate passes.
