# 0139 - Sleep-Cycle Improvement: Parallel Orthogonal Sub-Wave Execution & Deterministic Fast-Gate
id: 0139-parallel-subwave-execution-and-deterministic-fast-gate
skill: foreman
situation: Multi-Anchor Collaboration (Wave 22) planning and execution architecture review prompted John's directive on Crucible and Foreman: "If it is not good for this task, then it is probably not good for any type of task. Same for foreman?"
context: Formal Skill Foundry sleep-cycle improvement (2026-10-22) across <path> evaluating why sequential per-wave cold-start EXECUTE -> MULTI-REVIEWER-SWARM -> FIX -> RE-REVIEW loops bottleneck multi-subsystem builds that decompose cleanly into orthogonal sub-waves (W.1..W.k).
observation: When a wave decomposes into independent sub-waves (W.1..W.k) with disjoint file write-sets and each sub-wave has an orchestrator-run deterministic test gate (pytest / node --test) plus deterministic AST security/structure checks (Aegis + Anvil), running sub-waves strictly serially and spawning multi-round LLM reviewer swarms on already-green deterministic gates burns 60-75% of wall-clock time on redundant subprocess cold starts.
outcome: worked - codified Parallel Sub-Wave & Deterministic Fast-Gate Mode in Foreman SKILL.md and HUMAN.md, establishing DAG/parallel disjoint-write-set sub-wave dispatch, orchestrator-first deterministic fast-gate (tests + Aegis AST + Anvil structural check), and single-pass cross-family diff review with immediate auto-advance when BLOCKER == 0.
provenance: genuine-execution - Multi-Anchor Collaboration Wave 22 architectural review and John's 2026-10-22 Skill Foundry directive.

## 1. Diagnosis: Why Strict Serial Waves + Multi-Round Reviewer Swarms Bottleneck Multi-Subsystem Builds

In traditional Foreman runs across large multi-subsystem plans:
1. **False Serialization of Orthogonal Sub-Waves (`W.1`..`W.k`):**
   While two coders editing the *same* file concurrently creates merge conflicts, a well-factored Stage-2 plan (especially from Crucible's `--matrix-fast-track`) decomposes waves into orthogonal sub-waves (`W.1`, `W.2`, ..., `W.k`) with **strictly disjoint file write-sets** (e.g., `W.1` Transport Engine in `anchor_net/`, `W.2` Git Bundle Sync in `anchor_git/`, `W.3` Yjs CRDT Room in `anchor_crdt/`, `W.4` RBAC Policy in `anchor_rbac/`). Running `W.1` through `W.k` strictly serially multiplies wall-clock build time by $k\times$ with zero safety benefit.
2. **Multi-Round LLM Reviewer Swarms After Deterministic Oracles Are Already Green:**
   Spawning a multi-round 2–3 reviewer subprocess swarm (`REVIEW -> FIX -> RE-REVIEW`) on every sub-wave *after* the orchestrator's deterministic ground-truth test suite (`pytest` / `node --test`), `delta-coverage-gate.mjs`, `Aegis` AST security scanner (6 CWE families), and `Anvil` structural/syntax verification have all passed with `0` issues introduces massive CLI spawn latency and reviewer timeout thrash (journals `0082`, `0109`, `0112`, `0135`).

## 2. Sleep-Cycle Architectural Upgrade: Parallel Orthogonal Sub-Waves + Deterministic Fast-Gate + Single-Pass Cross-Family Diff Review

Foreman now codifies **Parallel Sub-Wave & Deterministic Fast-Gate Mode** as a first-class execution topology:

1. **DAG / Parallel Sub-Wave Dispatch (Disjoint File Write-Sets):**
   - When a wave declares independent sub-waves (`W.1`, `W.2`, ..., `W.k`) whose declared file write-sets are mutually disjoint ($\text{writes}(W.i) \cap \text{writes}(W.j) = \emptyset$ for $i \ne j$), Foreman dispatches the orthogonal sub-wave executors in parallel across the DAG level rather than strictly serially.
   - Any sub-wave with an upstream dependency or overlapping write-set waits for its prerequisite DAG edge to complete and pass its gate.
2. **Orchestrator-Owned Deterministic Fast-Gate First (`Tests + Aegis + Anvil`):**
   - Immediately after `EXECUTE`, the orchestrator (never a sub-agent) runs the three-part **Deterministic Fast-Gate**:
     1. **Ground-Truth Test Suite + Delta Coverage:** `pytest` / `node --test` + `checkDeltaCoverage` (`bin/delta-coverage-gate.mjs`) + vacuous-GREEN / anti-test-weakening guards.
     2. **`Aegis` Deterministic AST Security Gate:** Zero-LLM static taint/sink scan across all 6 CWE families (`CWE-78`, `CWE-94/502`, `CWE-22`, `CWE-918`, `CWE-208/328`, `CWE-798`) on changed files.
     3. **`Anvil` Deterministic Structural & Contract Gate:** AST/CST parse integrity, interface export verification, and Null-Space / dead-scaffolding lint.
   - If the Deterministic Fast-Gate is RED, Foreman routes the exact deterministic failure artifact directly to `FIX` (0 reviewer model calls wasted on broken code).
3. **Single-Pass Cross-Family Diff Review on Green Fast-Gate (`BLOCKER == 0` Auto-Advance):**
   - When the Deterministic Fast-Gate (ground-truth tests + `Aegis` AST scan + `Anvil` structural check) passes with **`0` issues**, Foreman runs **1 bounded cross-family diff review** (`120s` timeout ceiling, scoped strictly to the `git diff` + plan acceptance criteria) instead of a multi-round reviewer swarm.
   - When `BLOCKER == 0` (any `BLOCKER` still requires a concrete failing repro command + output per §5), Foreman commits the wave/sub-wave, appends `EXECUTION-LOG.md`, and **auto-advances immediately**.
