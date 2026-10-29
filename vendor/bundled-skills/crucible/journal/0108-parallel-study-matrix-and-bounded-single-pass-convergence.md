# 0108 - Sleep-Cycle Improvement: Parallel Dimension Study Matrix (L0-L5) & Bounded Single-Pass Convergence
id: 0108-parallel-study-matrix-and-bounded-single-pass-convergence
skill: crucible
situation: Multi-Anchor Collaboration (Wave 22) architectural planning exposed the latency and timeout bottleneck of sequential multi-round Shark-Tank subprocess swarms on large systems efforts, prompting John's mandate: "we should consider changing crucible to be more like what you are proposing. If it is not good for this task, then it is probably not good for any type of task."
context: Formal Skill Foundry sleep-cycle improvement (2026-10-22) across <path> grounded in Multi-Anchor Collaboration Wave 22 empirical comparison (4 parallel researchPrime dimension studies + 4 Gandalf critiques + 6-Level L0-L5 Adversarial Matrix + 6-Subwave deterministic plan vs. sequential multi-round Shark loops).
observation: Sequential multi-round 5-subprocess Shark swarms (3 Sharks + Synthesizer + Judge x 3-5 rounds across Stages 1 and 2 = 20-30 cold CLI spawns) suffer compounding tail latency, Windows job-object timeout risk, and unstructured prose thrash on complex multi-subsystem architectures, whereas parallel orthogonal dimension decomposition paired with an explicit L0-L5 Adversarial Matrix converges in 1 bounded pass with higher defect recall and zero subprocess stalls.
outcome: worked - codified Multi-Level Adversarial Matrix Mode (--matrix-fast-track) in SKILL.md and HUMAN.md as the canonical high-velocity architecture for complex systems and multi-wave plans.
provenance: genuine-execution - Multi-Anchor Collaboration Wave 22 planning synthesis and John's 2026-10-22 architectural directive.

## 1. Diagnosis: Why Sequential Multi-Round Subprocess Swarms Stall on Complex Architectures

When planning a complex multi-subsystem engineering effort (such as Multi-Anchor Collaboration across transport, Git DAG sync, CRDT workspace state, RBAC governance, and cockpit UI), the legacy `FULL` Shark-Tank loop exhibits three compounding failure modes:

1. **Multiplicative Subprocess Spawn Latency (`20–30` Cold CLI Spawns):**
   Running `3 Sharks + 1 Synthesizer + 1 Judge` sequentially across `3–5` rounds in both Stage 1 and Stage 2 requires `20–30` cold CLI process spawns (`claude.exe` / `agy` / `grok`). Each cold start pays full context ingestion and CLI initialization overhead, turning a 10-minute planning problem into a 45–90 minute wall-clock marathon vulnerable to Windows job-object kills (journals `0020–0027`, `0064–0067`) and quota exhaustion.
2. **Monolithic Context Saturation vs. Orthogonal Dimension Depth:**
   Asking three general-purpose Sharks to critique an entire 8-subsystem architecture in one monolithic prompt dilutes attention across surface prose while missing deep layer-specific invariants (e.g., Tailscale DERP NAT hole-punching vs. Yjs CRDT tombstones vs. Ed25519 capability rotation).
3. **Unstructured Prose Debate vs. Structured Layer Matrix:**
   Multi-round free-text Shark critiques frequently oscillate on framing preferences rather than systematically auditing every failure layer from physical transport (`L0`) up to human UX (`L5`).

## 2. Sleep-Cycle Architectural Upgrade: Parallel Dimension Study + Multi-Level Adversarial Matrix (`L0–L5`) + Bounded Delta-Only Re-Review

To make Crucible fast, rigorous, and stall-proof for any complex engineering task, **Multi-Level Adversarial Matrix Mode (`--matrix-fast-track`)** is promoted as the canonical high-velocity architecture:

1. **Stage 0 (Explicit North Star Lock):**
   - Display the complete candidate North Star verbatim on screen (Per the Show-the-Artifact Rule and Crucible Pre-Launch Rule) and lock immediately upon human approval.
2. **Stage 1 (Parallel Dimension Decomposition + Multi-Level Adversarial Matrix `L0–L5`):**
   - **Parallel Dimension Decomposition ($K$ Orthogonal Studies):** Decompose complex problems into $K$ orthogonal architectural dimensions (e.g., Networking/Transport, State/CRDT Sync, Security/RBAC, UI/Cockpit Ergonomics) investigated in parallel (`researchPrime` + `Gandalf` critique per dimension) rather than serial monolithic rounds.
   - **Explicit Multi-Level Adversarial Review Matrix (`L0–L5`):** Synthesize the dimension studies into a single master plan anchored by an explicit **6-Layer Adversarial Review Table (`L0` through `L5`)**, where every layer enumerates concrete **Failure Modes**, **Severity**, and **Mandatory Engineering Mitigations**:
     - `L0` — Physical / Transport / Process / OS Boundary
     - `L1` — Data / State / Concurrency / Storage Integrity
     - `L2` — Protocol / API / Schema / Backwards-Compatibility Contract
     - `L3` — Security / Auth / Capability / Secret & Taint Isolation (`Aegis`)
     - `L4` — Orchestration / Fault Recovery / Partition & Failover Resilience
     - `L5` — Human Surface / UX Ergonomics / Cognitive Load & Reachability (`Anvil`)
   - **Single-Pass Convergence (`first-dry / matrix-converged`) + Delta-Only Re-Review (`120s` Cap):** Stop in **1 pass** once every `L0–L5` row carries a concrete mechanical mitigation and test oracle, unless $\ge 2$ independent reviewers prove an unmitigated `BLOCKER` — in which case re-review runs **only on the amended delta section** with a hard per-seat timeout (`120s`), never re-tanking the entire document.
3. **Stage 2 (Foreman-Ready Sub-Wave Plan + Deterministic `locate-plan.mjs` Gate):**
   - Compile the converged `L0–L5` matrix directly into orthogonal, test-gated sub-waves (`W.1`..`W.k`) with explicit file write-sets, hardening property gates (`bin/hardening-gate.mjs`), and machine-countable test commands, validated deterministically by `foreman/bin/locate-plan.mjs` (exit `0`).
