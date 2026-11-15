# researchPrime Synthesis: Best-in-Class Programmatic Code-Rewriting Tools & The Parable of the Oranges (`Anvil` Mode 3 & Orchestrator)

**Evidence Stamp:** `OBSERVED` + `CORROBORATED` (Empirical tool benchmarking & CST/AST literature synthesis for `skills/anvil`).

---

## 1. Why Naive Agent Line-Editing Fails on Legacy & Vibe-Coded Codebases

When an AI agent rewrites or refactors an existing module using raw text replacement or ad-hoc regex scripts, three failure modes dominate:
1. **The 50%-Compromise Frankenstein (Violating the Parable of the Oranges):** The agent preserves half of the legacy scaffolding while bolting on a new abstraction, duplicating state and leaving dead fallback paths ("Null Space") intact.
2. **Formatting, Comment, String, Attribute & Keyword Corruption:** Regex replacements (`\bsym\b`) corrupt string literals, comments, object attributes (`obj.sym`), keyword arguments (`fn(sym=1)`), and shadowed local parameters (`def f(sym): return sym`). Standard `ast.unparse` discards comments and formatting.
3. **Silent Behavioral Drift:** Without isolated child-subprocess input-output pinning and differential equivalence checks, subtle edge cases change silently during refactoring.

---

## 2. The Parable of the Oranges ("Peel vs. Juice vs. Pith/Seeds" Decomposition)

In classic integrative negotiation (Fisher, Ury & Patton; Mary Parker Follett), two sisters quarrel over a single orange and split it 50/50—only to discover one sister wanted **only the peel/zest** to bake a cake while the other wanted **only the juice/pulp** to drink. By failing to separate *underlying functional purpose* from *surface form*, both got half of what they needed.

In **Anvil**, every module, class, and function is deterministically decomposed into three disjoint sets using a full-repository AST + `tests/` reference index:

| Orange Layer | Software Meaning | Anvil Orchestrator Action |
|---|---|---|
| **1. The Juice (Essential Domain / Mathematical Logic)** | Pure state transitions, mathematical equations, invariants, and business rules (`Do-Analysis`). | **Preserve & Verify 100%:** Pin with isolated child-subprocess differential equivalence probes (`verify-equivalence`, `rtol=1e-7`). |
| **2. The Peel / Zest (Essential Surface Contract & I/O Boundary)** | Public API signatures, CLI flags, route handlers, schema contracts, file formats, and rendering interfaces (`Get-Data` & `Create-Output`). | **Keep Thin & Explicit:** Separate cleanly from internal calculation; enforce strict schema/type and Aegis CWE boundary checks. |
| **3. The Pith & Seeds (Truly Unreferenced Non-Entrypoints / Null Space)** | Functions with zero references across production ASTs (including top-level dispatch tables, decorators, default args, `__all__`) AND zero references in `tests/`. | **Classify to Null Space Ledger & Sign Off:** Cataloged in `pith_and_seeds` (`TRULY_UNREFERENCED_NON_ENTRYPOINT` or `INTENTIONALLY_DROPPED_OBSOLETE`); `referenced_by_tests_only` helpers are separated cleanly and never misclassified as dead code. |

---

## 3. Best-in-Class Programmatic Code-Rewriting & Verification Stack

### Layer A — Scope-Safe Concrete Syntax Tree (`LibCST`) & Polyglot AST Inspection
| Tool | Role in `Anvil` | Why Best-in-Class (`OBSERVED`) |
|---|---|---|
| **`LibCST`** (`libcst` + `MetadataWrapper` + `ScopeProvider` + `ParentNodeProvider`) | Primary Python lossless CST transformer (`cst_rewrite_module`). | Preserves **100% of comments, string literals, whitespace, and parentheses** while refusing to touch `obj.attr`, `fn(kw=1)`, or shadowed local variables. Fails closed cleanly when `libcst` is absent (zero regex fallback). |
| **`ast` (Python stdlib) + Polyglot JS/TS/R/C Scanners** | Fast semantic call-graph, import-graph community clustering, and purity classification. | Zero-dependency sub-second inspection across Python, `.js`/`.mjs`/`.cjs`/`.ts`/`.tsx`, `.R`, and `.c`/`.cpp`. |

### Layer B — Static Hygiene & Defensive Security Gates
| Tool | Role in `Anvil` | Why Best-in-Class (`OBSERVED`) |
|---|---|---|
| **`Ruff`** (`python -m ruff check --select E9,F63,F7,F82`) | Post-transform syntax and undefined-name gate inside `cst_rewrite_module`. | Sub-second verification that every refactored module parses and resolves symbols cleanly. |
| **`Aegis`** (`../aegis/scripts/aegis_engine.py`) | Deterministic CWE taint/sink scanner (`AEG-01..AEG-06`) wired into Seat 5 and `verify-diff`. | Catches shell injection (`CWE-78`), code execution (`CWE-94/502`), path traversal (`CWE-22`), SSRF (`CWE-918`), weak crypto (`CWE-208/328`), and hardcoded secrets (`CWE-798`). |

### Layer C — Isolated Subprocess Differential Equivalence
| Tool | Role in `Anvil` | Why Best-in-Class (`OBSERVED`) |
|---|---|---|
| **Child Subprocess Runner + `Hypothesis` / `pytest`** | Isolated differential probe (`verify_behavioral_equivalence` & `run_code_walkthrough`, `shell=False`). | Runs untrusted or experimental target modules in a separate child Python/Node/R process so target imports never mutate the host process or `sys.path`. |

---

## 4. Direct CLI Entrypoints in `scripts/anvil_engine.py`

All refactoring, slicing, and equivalence tools ship directly in `scripts/anvil_engine.py`:
1. `python scripts/anvil_engine.py orange-split --repo <dir> --json` — Full-AST + `tests/` Orange Split (`Juice`, `Peel`, `Pith & Seeds`).
2. `python scripts/anvil_engine.py cst-rewrite --source <file.py> --rename <old:new> --drop <dead_fn>` — Scope-safe `LibCST` codemod + `ruff` syntax/undefined-symbol gate.
3. `python scripts/anvil_engine.py verify-equivalence --old-repo <old_dir> --new-repo <new_dir> --rtol 1e-7` — Child-subprocess differential equivalence gate.
4. `python scripts/anvil_engine.py verify-diff --repo <dir> --files <changed_files> --json` — Sub-2s post-edit syntax, duplicate-definition, accidental new dead-helper, and Aegis CWE gate.
