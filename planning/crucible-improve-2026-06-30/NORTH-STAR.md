# North Star — Anchor Improvement Effort (LOCKED 2026-06-30)

> **Status:** Crucible Stage 0 complete. North Star **LOCKED** by J.C. Liechty.
> Drift detection is active against this statement. Depth: **FULL**.

## The locked objective

> **Anchor is a durable, resumable, model-flexible control surface.** A user can
> leave *any* effort — including older brownfield ones — and later click to **carry
> on exactly where they were**: correct phase (research / plan / build), the
> documents that were available, the right skills loaded, and a session summary that
> orients the new turn. The UI shows the **latest effort per tab** with prior efforts
> **one click away**, **warns only on genuine problems** (orphan swarms, real context
> pressure), and runs **Claude-orchestrates-Gemini (5:1, single-subscription
> fallback)** as the default execution substrate — **without changing what Anchor is
> for.**

## The three pillars

Every in-scope item serves exactly one pillar. Growth that serves a pillar is
welcome; non-serving bloat is cut (the inclusion test).

- **(A) Resumable sessions** — leave and carry on, with phase + docs + skills +
  summary restored. Includes making *discovered / brownfield* efforts first-class
  resumable sessions, and a model-switch handoff doc.
- **(B) Honest UI & warnings** — latest-per-tab + "previous" link; collapsed
  deliverables; correct terminal controls + width; warnings that fire only on real
  problems (orphan swarms, real context pressure); the Gandalf engine producing
  *real* findings.
- **(C) Model-flexible execution** — Claude default on Windows; Claude orchestrates
  Gemini swarm sub-agents at 5:1; graceful fallback to whichever single subscription
  exists, never cross-calling.

## Meta-requirement

Every Crucible and Foreman run on this effort writes its own summary into the
effort — dogfooding Pillar A.
