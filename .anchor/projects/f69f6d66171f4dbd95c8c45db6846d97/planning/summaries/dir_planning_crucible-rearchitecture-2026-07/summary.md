# Master Plan (draft)

*Lane: planning · validated, cached summary*

**When run:** 2026-07-03

**What was asked:** Master Plan (draft)

**North Star:** Re-architect Anchor from an 18,441-line monolith into a maintainable, observable, restart-resilient substrate — the architectural foundation for the Butler (an always-on agent that manages John's projects and workflow) — by (1) extracting the embedded frontend to static files, (2) replacing the if-elif dispatch with a declarative route table whose auth is default-deny by construction, (3) laying an append-only per-project event-log spine (dual-write; legacy stores stay authoritative), and (4) splitting spawned work into a supervisor process so the dashboard can restart without killing in-fligh

## Actions & files produced

- Master Plan (draft)
- Anchor Re-architecture — the Butler substrate — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- **Anchor Re-architecture — the Butler substrate — Master Plan (draft)**
- **Objective:** Re-architect Anchor from an 18,441-line monolith into a maintainable, observable, restart-resilient substrate — the architectural foundation for the *Butler* (an always-on agent that manages John's projects and workflow).
- **Four structural moves:** (1) extract the embedded frontend to static files; (2) replace the if-elif request dispatch with a declarative route table whose auth is default-deny by construction; (3) lay an append-only per-project event-log spine (dual-write, legacy stores stay authoritative); (4) split spawned work into a supervisor process so the dashboard can restart without killing in-flight work.
- **Locked architectural decisions (Stage-0, John-approved):**
- **D1 — Event log:** per-project append-only JSONL journal, DUAL-WRITE only (legacy stores remain authoritative for reads); a parity gate and a recovery tool are mandatory consumers.
- **D2 — Supervisor:** a separate stdlib supervisor as its own NSSM service, with loopback token-authed IPC and an inline seam for tests; JOBS are migrated first, PTYs held behind a mandated ConPTY spike.
- **D3 — Routing/auth:** default-deny declarative route auth; `open` (unauthed) is an explicit, reviewed allowlist; cookie-based browser navigation; strangler-style incremental migration.
- **Explicit non-goals (scope fences):**
- NOT building the Butler itself — no autonomous scheduling/decision agent, no proactive actions; this effort ships only the substrate.
- NOT promoting the event log to source of truth — no read-path cutover, no removal of index/pointer/registry stores (a later, separate effort).
- NOT a UI redesign — extraction is verbatim/behavior-parity; no visual or interaction changes beyond what parity requires.
- NOT replacing markdown as the task source of truth, and no new storage engines (no SQLite, no third-party deps).
- **Build convention:**
- Every wave ships real source that its own new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line-style criterion per item).
- **Member documents:** *Master Plan (draft)* and *Anchor Re-architecture — the Butler substrate — Implementation Plan (Foreman-ready).*
- **Master Plan (draft) — Anchor Re-architecture ("the Butler substrate")**
- **Objective:** Re-architect Anchor from an 18,441-line monolith into a maintainable, observable, restart-resilient substrate — the architectural foundation for the Butler (a future always-on agent that manages John's projects and workflow).
- **Four substrate deliverables:** (1) extract the embedded frontend to static files; (2) replace the if-elif dispatch with a declarative route table whose auth is default-deny by construction; (3) lay an append-only per-project event-log spine via dual-write (legacy stores stay authoritative for reads); (4) split spawned work into a supervisor process so the dashboard can restart without killing in-flight work.
- **Locked decision D1 (event log):** per-project append-only JSONL journal, DUAL-WRITE with legacy stores authoritative for reads; a parity gate and a recovery tool are mandatory consumers. Stage-0, John-approved and locked.
- **Locked decision D2 (supervisor):** a separate stdlib supervisor running as its own NSSM service, with loopback token-authed IPC and an inline seam for tests; JOBS handled first, PTYs gated behind a mandated ConPTY spike.
- **Locked decision D3 (routing/auth):** default-deny declarative route auth; `open` routes are an explicit reviewed allowlist; cookie-based browser navigation; strangler-style incremental migration.
- **Non-goal — not the Butler:** this effort delivers only the substrate; no autonomous scheduling/decision agent and no proactive actions are built.
- **Non-goal — no source-of-truth cutover:** the event log is not promoted to source of truth; no read-path cutover and no removal of index/pointer/registry stores (deferred to a separate later effort).
- **Non-goal — no UI redesign:** frontend extraction is verbatim/behavior-parity; no visual or interaction changes beyond what parity requires.
- **Non-goal — no storage-engine change:** markdown remains the task source of truth; no SQLite and no third-party dependencies introduced.
- **Build convention:** every wave ships real source that its new tests import and exercise; acceptance criteria follow the D16 hybrid convention.
- **Member documents:** "Master Plan (draft)" and "Anchor Re-architecture — the Butler substrate — Implementation Plan (Foreman-ready)."

## Files

- [Master Plan (draft)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fcrucible-rearchitecture-2026-07%2FMASTER-PLAN-DRAFT.md)
- [Anchor Re-architecture — the Butler substrate — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fcrucible-rearchitecture-2026-07%2FIMPLEMENTATION-PLAN-DRAFT.md)
