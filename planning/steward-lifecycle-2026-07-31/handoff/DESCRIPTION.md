# Ecgberht — steward campaign orchestration (Foreman build)

## What is being built

**The deliverable IS a foundry skill**, not an Anchor feature. `C:\dev\Ecgberht` is a
host-independent steward with TWO ENTRY SURFACES — the **seal** (project altitude) and
the **high seat** (portfolio altitude). It is ONE skill; it is never forked into a
second brain.

**Anchor is the REFERENCE HOST.** It supplies execution, auth and browser surfaces,
consuming the skill exactly as it consumes Gandalf. Anchor implements HOST CONTRACTS
ONLY — executor, outbox producer, authorizer, routes/UI. **No steward logic in Anchor
Python** (North Star v5 non-goal, CI-fenced in Wave 1).

## The capability

A project is stood up, planned across MANY stages, and driven OVER TIME by talking to
its steward. The steward AUTHORS a coarse scaffolding (campaign roadmap + Parable-of-
the-Oranges prompts), proposed and batch-confirmed; ORCHESTRATES stage by stage
(reflection → next-stage proposal → progressive elaboration); and COMMISSIONS
researchPrime / Gandalf / Crucible / Foreman for stage work, never authoring it.
Reflections and proposals are typed ledger artifacts rendered into conversation, never
chat that must survive as chat. Every project publishes a typed attention projection so
the portfolio altitude shows live status across ALL projects and comes forward only when
a decision or a deliverable needs John.

## What already exists (CONSUME — do not rebuild)

- Project altitude (E5): Face/Strip, roadmap events, brief, dispatch, commission verbs,
  bare CLI — 56 tests.
- Portfolio altitude: high-seat/rank + `engine/portfolio/` index — **671 tests**, home
  `~/.steward/portfolio`, zero Anchor dependence. Wave 1 audits it is live and wired;
  a defect there is a FIX ITEM, never a re-plan.

## What is genuinely new

The Anchor commission executor (host contract), a dialogue→`step_create` path, the
attention-projection emitters, `deliverable_ready` as a state, the chamber UI, **the
skill's own in-session executor** (Waves 20–22), and the **shared conformance suite**
proving both executors implement ONE skill-owned handback contract.

## Invariants (violating one is a HALT)

E5 single ledger (chat turns NEVER persisted; the dialogue COMPILES into the Face) ·
single writer on `roadmap_events` · commissions are FOR roadmap steps carrying `who` as
CLAIMED identity stamped unauthenticated · subscription-CLI seats only · the ENGINE
contains no `ANCHOR_TOKEN` logic (auth enters via an injected `authorize()` hook) ·
unattended reflections are ZERO-MODEL and ZERO-NETWORK · nothing spends without human
confirmation · no adversarial review in the product loop.

## Authority

`../NORTH-STAR.md` (v5, LOCKED 2026-08-02, 15 criteria) · `../STAGE2-APPROVAL.md` ·
`../STAGE1-APPROVAL.md` (gate decisions 1–7, signed Descope D-1).
