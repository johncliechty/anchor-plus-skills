# Skill Foundry v2 — Implementation Plan (Foreman-ready) — ANCHOR-SIDE BUILD (split)

*Lane: planning · validated, cached summary*

**When run:** 2026-07-10

**What was asked:** Skill Foundry v2 — Implementation Plan (Foreman-ready) — ANCHOR-SIDE BUILD (split)

**North Star:** **Deliverables:** an end-to-end acceptance test proving the ANCHOR-SIDE North-Star journey from the GUI on genuine data — create a skill, run/monitor it + see changes, browse library + graph, edit its North Star — plus every foundry skill auto-available/clickable in Anchor, all mutations journaled, safety envelope armed. **SPLIT NOTE — deferred to integration:** the North Star's central sleep-loop clause ("run+review a test-gated sleep improvement that has turned over ≥1× on genuine data") is delivered by the SEPARATE foundry-kernel build (`FOUNDRY-KERNEL-PLAN.md`) + a FINAL integration pass t

## Actions & files produced

- Skill Foundry v2 — Implementation Plan (Foreman-ready) — ANCHOR-SIDE BUILD (split)

**Effort:** imported — no run metrics

## Goal & key decisions

- ## Skill Foundry v2 — Anchor-Side Build (Planning Session Summary)
- This is the **Anchor-side** slice of a split "Skill Foundry v2" implementation plan, made **Foreman-ready** (i.e. structured into waves for the Foreman build orchestrator).
- The build is deliberately **split**: this plan covers the Anchor-side work; a **separate `FOUNDRY-KERNEL-PLAN.md`** owns the foundry-kernel build, with a **final integration pass** joining the two.
- **Wave 1 — Phase 0: de-risking spikes → decisions (as code)**
- Enforces a Foreman constraint (§5): **a wave must change real CODE exercised by a test; a docs-only wave HALTs.** So Phase-0 decisions are encoded as an importable module, not prose.
- Deliverable (A): a new source module **`foundry_decisions.py`** in the Anchor build root, encoding the **four resolved decisions** as machine-readable constants/enums that **later waves import** — putting the decisions on the consumption path.
- Named decisions surfaced in the anchor: (1) **`ANCHOR_API_CONTRACT`** — the native READ/EXECUTE surface vs. the MUTATIVE verbs the control plane must supply (feeds the control-plane wave's op inventory); (2) an isolation decision (`ISOL…`, truncated in the source excerpt).
- **Wave 12 — Anchor-side North-Star acceptance proof (end-to-end)**
- Deliverable: an **end-to-end acceptance test** proving the Anchor-side North-Star journey **from the GUI on genuine data** — create a skill, run/monitor it and see changes, browse the **library + graph**, and edit its **North Star**.
- Also proves every **foundry skill is auto-available/clickable in Anchor**, all **mutations are journaled**, and the **safety envelope is armed**.
- **Split note:** the North Star's central **sleep-loop clause** ("run+review a test-gated sleep improvement that has turned over ≥1× on genuine data") is **deferred to integration** — delivered by the separate foundry-kernel build plus the final integration pass, not by this Anchor-side plan.
- ## Skill Foundry v2 — Implementation Plan (Foreman-ready) — Anchor-Side Build (split)
- This is a **split plan**: it covers the *Anchor-side* build only. A separate `FOUNDRY-KERNEL-PLAN.md` build handles the foundry-kernel, with a final integration pass tying them together.
- The plan is structured as Foreman-ready waves (at least Wave 1 through Wave 12).
- **Wave 1 — Phase 0: de-risking spikes → decisions (encoded as code)**
- Enforces a hard Foreman constraint (§5): **a wave must change real CODE exercised by a test — a docs-only wave HALTs.** The four Phase-0 decisions are therefore encoded as an *importable Python module*, not prose.
- **Deliverable (A):** a new source module **`foundry_decisions.py`** in the Anchor build root, encoding the four resolved decisions as machine-readable constants/enums that later waves import — putting the decisions on the actual consumption path.
- **`ANCHOR_API_CONTRACT`** — the native READ/EXECUTE surface vs. the MUTATIVE verbs the control plane must supply (feeds the control-plane wave's op inventory).
- **Deliverable:** an end-to-end acceptance test proving the Anchor-side North-Star journey from the GUI on genuine data — create a skill, run/monitor it and see changes, browse library + graph, edit its North Star.
- Also proves every foundry skill is auto-available/clickable in Anchor, all mutations are journaled, and the safety envelope is armed.
- **Split note (deferred to integration):** the North Star's central *sleep-loop* clause ("run+review a test-gated sleep improvement that has turned over ≥1× on genuine data") is **not** delivered here — it's delivered by the separate `FOUNDRY-KERNEL-PLAN.md` build plus a final integration pass.

## Files

- [Skill Foundry v2 — Implementation Plan (Foreman-ready) — ANCHOR-SIDE BUILD (split)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=FOUNDRY-V2-IMPLEMENTATION-PLAN.md)
