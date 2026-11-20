# Anvil Lessons

Research repositories accumulate dozens of abandoned prototypes alongside the few active workflows that actually produce a paper's tables, policy counterfactuals, and simulation figures, so Anvil must first isolate each paper-matched pipeline one at a time rather than scanning every historical trial together. Once focused on an active pipeline, Anvil must extract the actual tensor algebra computed in the software into readable mathematical formulas instead of falling back on generic placeholders or shallow word matching. Because subtle coding mistakes such as normalizing covariates across the full sample before cross-validation or adding redundant intercept layers silently distort empirical findings, Anvil must audit the code for real statistical and numerical hazards. Finally, instead of emitting generic architectural boilerplate, Anvil must propose a concrete refactoring that separates a shared mathematical core and split-safe data preparation from thin command-line entry scripts.

---

## Technical Engineering Lessons & Mechanisms

1. **Paper-Anchored Replication Scoping & Multi-Pipeline Partitioning (`discover_paper_matched_scopes`, `--pipeline`):**
   - Inspect manuscript `.tex` trees (`\input{Tables/...}`, `\includegraphics{...}`, `\label{tab:...}`), `.md`, and `.pdf` files alongside `workflow.sh`, `Makefile`, `REPLICATION.md`, and `README*.md` to locate true replication entrypoints.
   - Compute transitive intra-repository import-reachability closures per entrypoint and partition distinct workflows into coherent named `pipelines[]` (`predictive_tables`, `policy_targeting`, `simulations`, `verification_checks`), quarantining unreachable scripts into `unreferenced_historical_files[]`.
   - Cluster active replication modules by scientific role (`Data Prep & Covariates`, `Core Choice & Panel Estimation`, `Table / Metric Builders`, `Policy / Counterfactual Evaluation`, `Verification Checks`), capping bucket size (`<= 35` modules) so unrelated files are never collapsed into one mega-bucket.

2. **PyTorch / NumPy Tensor AST -> Native MathML Extraction (`_extract_real_code_mathml`):**
   - Tensor operations in PyTorch and NumPy are AST `Call` expressions rather than scalar binary operators; AST formula extraction must inspect `einsum` bilinear contractions, `log_softmax` / `softmax` multinomial logit probabilities, `logsumexp` panel mixture likelihoods, `tanh` / `ReLU` covariate adapters, z-score standardization `(Z - Z.mean(...)) / (Z.std(...) + eps)`, doubly-robust AIPW contrasts, and quadratic `(dev ** 2).mean()` shrinkage penalties, compiling each into native `<math xmlns="http://www.w3.org/1998/Math/MathML" display="block">` with exact `file:lineno` and plain-English meaning.

3. **Operator-Grounded & Scope-Filtered Paper <-> Code Alignment (`paper_to_code_map`):**
   - Filter candidate functions to paper-matched replication files first (penalizing prototype/archive scripts), reward structural operator agreement (`\prod_t` + `\sum_s` panel likelihoods <-> `logsumexp` + `.sum(`, `\tanh` adapters <-> `tanh` + `Linear`, `\frac{\exp}{\sum \exp}` <-> `log_softmax`/`softmax`), and penalize pure data-loader (`load_*`, `read_csv`) functions from matching model utility equations.

4. **Static Scientific Bug/Leakage Detection & Concrete Functional-Core Proposals (`run_scientific_validation`):**
   - Deterministically flag pre-split full-sample normalization leaks before `KFold` / train-test splits (`SCI-01`), collinear `nn.Linear(..., bias=True)` heads added directly onto unfrozen `nn.Parameter` base coefficients (`SCI-02`), and cross-script `logsumexp` + `log_softmax` choice-loss duplication (`SCI-03`), emitting a concrete Functional-Core / Imperative-Shell refactoring plan naming the shared pure kernel module, split-safe fold preprocessor, and thin CLI shells in both JSON and `ANVIL-REPORT.md`.

5. **Shell-Variable Manifest Expansion, Subprocess Closure & Cross-Platform Float Assertions (`SCI-04`):**
   - Expand shell variables (`C="$OUT/Code"`, `$PY`) and step wrappers (`step <label> "$PY" ...`) in `workflow.sh`, resolve `subprocess` `.py`/`.R` scripts and `-c` inline imports in `_build_repo_import_graph`, honor `PAPER_DATASETS` exclusions in shared loaders, and flag `assert np.isclose(..., <8+ decimal float>)` without cross-CPU `atol` (`SCI-04`).
