# PLAN v3 CHANGES — what moved from IMPLEMENTATION-PLAN-v2 and why

**Date:** 2026-08-02 · **Authority:** `stage2-artifacts/IMPLEMENTATION-PLAN-v3.md` (supersedes v2) under **North Star v5, LOCKED 2026-08-02** (15 criteria).
**Sources of the amendment:** `REVIEW-SKILL-BOUNDARY.md` §E–§G (the boundary audit's five seam fixes + T-HOST-0) and **John's two locked 2026-08-02 decisions**: (1) ONE SKILL, TWO ENTRY SURFACES — do not split; (2) BUILD THE IN-SESSION EXECUTOR NOW (the §G.6 grasscatch option was NOT taken), with the divergence-mitigation condition that became NS criterion 15: one skill-owned handback contract, two executor implementations, one shared conformance suite.
**Generated pair:** `stage2-artifacts/wave-decomposition-v3.json`, `source_sha256 = 2a2a21804154891bf96498a548db730a6bb7c9c51cab00d83215cd7dd541d5f5`.

## This is a REVISION, not a re-plan

Preserved intact: the wave DAG for waves 1–18 (every existing edge unchanged; v3 only ADDS waves 20–22 and the Wave-19 edges to 21/22); the S1–S13 per-instance durability obligations (extended with S14, never rewritten); every failure-state table (`unknown` and `empty` still separate rows with status code + user-visible text); gate decisions 1–5 (STAGE1-APPROVAL.md) including the deterministic-emitter interpretation of criterion 4 and the `who` claimed-unauthenticated policy; the SIGNED Descope D-1 (no-credential handback-file design — the in-session executor obeys the same no-token-in-child law); the PRE-SPINE FIXTURE-ONLY rule; the refuted ideas stay dead (no handback artifact channel — the contract OWNERSHIP moved, the channel did not; no bind-and-derive rebuild). Wave numbering 1–19 is stable; **numeric order is no longer execution order** — waves 20–22 precede Wave 19 in the DAG.

## Per-wave delta

| Wave | v3 status | What changed | Why |
|---|---|---|---|
| 1 | **AMENDED** | Suite split into a **SKILL LANE** (runs HOST-LESS: no Anchor service, no `ANCHOR_TOKEN`, no auth preflight; CI runs it once in a scrubbed env every build) and an **AUTH-ON LANE** (Anchor integration; token minted, pillar `enforce`, vacuous-green preflight unchanged). CI diff guard additionally fences the new non-goal: no steward logic in Anchor Python. Equivalence check now parses the v3 doc/JSON pair. | §G.2-W1: v2 made the whole auth-ON preflight a precondition of every Ecgberht test — the skill's own suite was unrunnable without Anchor. Criterion 14 groundwork. |
| 2 | unchanged | — | — |
| 3 | unchanged | — | — |
| 4 | **AMENDED** | The durable handback-file **CONTRACT is now SKILL-OWNED**: `schema/handback-contract.schema.json` + `docs/handback-contract.md` + contract unit tests in the Ecgberht repo (validated by the existing `receipt-validate.mjs`); Anchor's executor wrapper is IMPLEMENTATION #1, the Wave-20 executor IMPLEMENTATION #2. Primary repo now **both** (contract = Ecgberht; reference executor = Anchor). G4 HALT now blocks Waves 11–22. New GWT: the contract is testable host-less. | §G.2-W4: as specified in v2, no other host could ever hand back. Ownership moves; the channel does not (e-1 stays refuted). Serves criterion 15. |
| 5 | unchanged | — | — |
| 6 | unchanged | — | — |
| 7 | unchanged | — | — |
| 8 | **AMENDED** | `ANCHOR_TOKEN` revalidation at the debit seam replaced by the **INJECTED `authorize('debit', ctx)` hook**; Anchor supplies the token authorizer; a bare host supplies its own or the stamped local-trust authorizer; the SAME negative tests run through the hook (auth-ON lane); companion assertion that no engine module reads `ANCHOR_TOKEN`. | §G.2-W8 / NS criterion 9: Anchor's auth must not be welded into the skill engine. |
| 9 | unchanged | — | — |
| 10 | unchanged | — | — |
| 11 | **AMENDED + retitled** | Retitled "Commission proposal — **wired into** Anchor" (§G.2's retitle). Same authorizer-hook fix at the confirm seam. NEW: the **EXECUTOR SEAM** `executeCommission(dossier, ctx)` — the only route from a confirmed commission to any executor; Anchor injects the Wave-4 executor; the Wave-20 in-session executor is the in-session default; nothing available → the named terminal refusal **`no-executor-host`** (new failure row `COMMISSION_NO_EXECUTOR_HOST`), never a silent forever-queue. | §G.2-W11 + §A.2's "one real functional gap" (compose-only job-lifecycle queues forever with no Anchor). Serves criteria 9 and 14. |
| 12 | unchanged | — | — |
| 13 | **AMENDED** | The status-truth channel is now the named **HOST-AGNOSTIC ingestion seam** `ingestStatusEvents(producer)` (skill-owned contract, unit-tested host-less with a fixture producer). Anchor's fsync'd outbox + Node mediator is **producer #1** — no longer "the" answer; the Wave-20 in-session supervisor is producer #2 through the SAME seam. Single-writer law untouched. | §G.2-W13: as written, criterion 8 was structurally Anchor-only forever. |
| 14 | AMENDED (light) | One clause: handback ingestion is **executor-agnostic by contract** — a contract-conformant handback ingests identically whichever executor produced it. | Follows from W4's contract ownership; supports criterion 15. |
| 15 | unchanged | (Wave 20 wires its next-invocation reconcile into `openProjectPipeline` stage 1 — declared in Wave 20's scope, no change to Wave 15's text.) | — |
| 16 | unchanged | — | — |
| 17 | unchanged | — | — |
| 18 | unchanged | — | — |
| 19 | **AMENDED** | Serves **all 15** criteria. Done-when now REQUIRES `t-host-0-verdict.json` PASS (Wave 22) and `conformance-verdict.json` BOTH-PASS on one contract_version (Wave 21) — either missing/drifting FAILS the gate by name. Depends on 18, **21, 22**. Auth outcome sweep runs through the injected authorizer hook with the criterion-9 no-token-in-engine grep re-asserted. Traceability report maps criteria 1–15. | §G.2-W19 (T-HOST-0 as a done-when clause) + criterion 15 as a kill-gate fact. |

## New waves

| Wave | What it is | Depends on | Teeth (no stub can green it) |
|---|---|---|---|
| **20 — In-session executor** | The skill EXECUTES a confirmed commission in the calling session with no Anchor: real trio-CLI child spawn behind the Wave-11 seam, durable launch intent + leases (new store **S14**), `(pid, proc_create_time)` identity, positive-confirmation tree-kill, **orphan reconcile at next invocation** (the Wave-4 boot-reconcile obligations without a service — no daemon, per the SKILL.md canary law), handbacks written through the Wave-4 **skill-owned contract** (same S6 clauses), status through the Wave-13 seam as producer #2, `INSESSION_MAX_CONCURRENT_RUNS=1` with `insession-busy`, no token in child env (D-1). **Honest difficulty**: Windows process supervision is the hard part `job_runner.py` already solves — it is now owned twice (a named NS v5 risk), so this implementation is deliberately smaller and reconcile-based. | 4, 7, 11, 13, 15 | Anti-stub **`exec2-verdict.json`** earned exactly like G4 (trio cmdline + receipt-validate + live-then-terminal identity); mechanical gates **T-EXEC2-KILL** (kill-mid-run) and **T-EXEC2-ORPHAN** (calling-session death → next-invocation reconcile); host-less real-run gate `gate/w20-real-run.mjs`; full failure-state table (11 rows, unknown ≠ empty). |
| **21 — Shared conformance suite** | Criterion 15 as a machine fact: `conformance/handback-contract/` in the skill repo — named contract clauses (path convention, schema via `receipt-validate.mjs`, marker semantics, S6 write discipline by write-interception, kill-mid-write, duplicate idempotence, no-token child env, single writer per run dir) run through an executor-adapter interface against BOTH executors' REAL wrapper code with REAL OS child processes (canned-file adapters fail the interception clause). In CI every build: skill lane runs the in-session adapter, auth-ON lane runs the Anchor adapter; either failing fails the build **naming the executor and the clause**; version-skew fails both. Emits `conformance-verdict.json`. | 4, 20 | A deliberately injected single-executor drift must fail the build by name (GWT-tested); regenerate-twice byte-identical verdict (S8). |
| **22 — T-HOST-0 gate** | §F's script implemented in the SKILL repo (`gate/t-host-0.mjs`), **amended per John's decision**: step 5 now ACTUALLY EXECUTES a confirmed commission via the in-session executor (real cheap-profile run → contract-valid handback → golden-matched deterministic reflection + next-stage proposal); `no-executor-host` is asserted as a SEPARATE case (executor disabled + nothing injected). Scrubbed env (no service/token/prefs/stores), zero-Anchor-read and zero-network traps, honest seat source `defaults`. Emits `t-host-0-verdict.json`. | 9, 11, 14, 15, 17, 20 | It is a real-run gate in a scrubbed environment with read/network traps — a refusal or a canned handback cannot pass step 5, and the verdict is a Wave-19 done-when input. |

## Cross-cutting changes

- **Framing:** title and prose reframed skill-first ("Ecgberht, the host-independent steward SKILL … Anchor as reference host"); NS v5 (15 criteria) replaces v4 everywhere; criterion 9 restated as the injected-authorizer criterion; criteria 14 and 15 added to the restatement and to the criteria map.
- **New non-goals:** no steward logic in Anchor Python (Anchor implements host contracts only — executor, outbox producer, authorizer, UI; CI-fenced in Wave 1, re-swept in Wave 19); no splitting the steward into two skills (ONE SKILL, TWO ENTRY SURFACES).
- **Lanes:** new Lane E (20 → 21 → 22, starts after 11/13/15, joins at 19). Topological order: 1…18, 20 → 21 → 22, then 19.
- **Durable stores:** S6 re-scoped as the skill-owned contract implemented by both executors (waves 4, 20, 21); S8 extended with the three v3 verdict artifacts; **S14 added** (in-session run ledger) with T-DUR-S14.
- **Property maps:** boundedness gains `INSESSION_MAX_CONCURRENT_RUNS=1` / `insession-busy` (T-BND-20); honesty gains Wave 20's table; new rows for host-independence (T-HOST-0) and contract conformance (T-CONF-15).
- **BUILD CONTRACT:** two-lane runner (`--lane skill` scrubbed); token provisioning is auth-ON-lane-only; real-run gate list adds Waves 20 and 22; per-wave repo manifest updated (20–22 = Ecgberht; 4 = both).
- **G4 gate:** FAIL now blocks Waves 11–22 (transitive; unchanged semantics — an Anchor-substrate HALT remains John's decision point even though the in-session executor exists, because the kill-gate campaign runs on the reference host).

## Still needs John

1. **Wave-20/22 real-run budgets** — Stage-2 approval of v3 must cover the two new cheap-profile real runs (`gate/w20-real-run.mjs`, `gate/t-host-0.mjs`), same LITE researchPrime profile as the existing gates.
2. **SKILL.md pass** (§G.3, small, can ride Wave 4 or 11): retitle "Seating (Anchor prefs only)" → host prefs with Anchor as reference source; document the two entry surfaces; add the T-HOST-0 promise to Install. Not wave-gated in v3 — say the word and it lands with Wave 4.
3. **Foundry governance pointer-map entry** for Ecgberht (§G.5 bookkeeping, non-blocking).
