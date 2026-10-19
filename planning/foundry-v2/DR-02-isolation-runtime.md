# DR-02 — Isolation runtime: explicit `PERMISSIONS_ADVISORY_V2` downgrade

> Phase-0 §2 decision record (foundry-v2 Wave 1). Machine-readable form:
> `foundry_decisions.ISOLATION_RUNTIME` (+ `ISOLATION_COST_ENVELOPE`,
> `ISOLATION_COMPENSATING_CONTROLS`).
> Traces to North Star: **NS#1 (manifest-driven runner)** and **NS#5 (reaper safety envelope)**.

## Decision

**v2 takes the Master Plan's explicitly sanctioned honest downgrade: skill permissions stay
ADVISORY (`PERMISSIONS_ADVISORY_V2`).** No OS-level isolation runtime is adopted in v2.
Enforcement moves to the ONE seam every run already passes through — the Wave-3 generic
runner — via the compensating-controls list below, all of which are host-enforced in code
and covered by tests/drift gates.

## Why the named runtimes were rejected (host facts, not taste)

The research (C3, demoted to CLAIMED) is right that language-level sandboxing is leaky and
real enforcement needs an OS-level primitive. But the workload decides eligibility: a foundry
skill run is an **agentic CLI subprocess** (`claude.exe` / `agy.exe`) that must read/write the
real project tree, spawn tools, and run `git` — under Anchor's frozen invariants (stdlib-only,
"any machine with Python 3.8+", single canonical skill dir consumed in place).

| Candidate | Est. startup latency* | Verdict |
|---|---|---|
| WASM / Wasmtime | ~10 ms | **Ineligible** — cannot host `claude.exe`/`agy.exe`; skills are not WASM modules |
| Container (Docker Desktop / WSL2) | ~3,000 ms cold | **Ineligible** — heavy non-stdlib host dependency; breaks portability rule and in-place single-source skill consumption |
| microVM (Firecracker) | ~125 ms | **Ineligible** — Linux/KVM only; host is Windows 11 |
| Deno permissions | ~50 ms | **Ineligible** — governs only Deno-runtime code; skills are not Deno programs |

\* Literature-tier figures (evidence tier **CLAIMED** — unmeasured on this host; measurement is
moot because every candidate fails on an OBSERVED host fact, not on cost). The chosen advisory
posture costs **0 ms** startup/per-run overhead, so there is **no tension with lazy/budgeted
activation** (the C2 reconciliation the Master Plan asked for).

## The downgrade is honest, not naked — compensating controls

1. Declared capabilities per manifest + a runtime pre-flight probe (Wave 3).
2. `mutate` ops require an explicit confirm token (Wave 3).
3. `mutate` ops declare a write-scope; out-of-scope writes are refused (Wave 3).
4. Mutations apply on a git branch/worktree, never straight to main.
5. Host-enforced journaling of every op, mutative ops included (Wave 2).
6. Grep/drift gates catch out-of-band write paths (Waves 2, 8, 10).
7. Reaper armed to ≥FREEZE + a per-host concurrency budget before default-on fan-out (Wave 13).

## Revisit trigger

If a future v3 targets multi-tenant or untrusted third-party skills, this decision must be
reopened — advisory permissions are acceptable only while every consumed skill is first-party
(the single-source `Skill Foundry/skills/<skill>` set) and the human remains in the promotion loop.

## Consumed by

Wave 3 (runner enforcement seam), Wave 13 (safety-before-scale envelope).
