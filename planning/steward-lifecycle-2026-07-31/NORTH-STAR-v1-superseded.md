# NORTH STAR — Anchor steward: project lifecycle by conversation

> **LOCKED 2026-07-31 by John.** Anti-drift authority for this effort. Every element of
> Stage 1 and Stage 2 must serve one of the criteria below; drift detection runs from
> this lock. Depth: **FULL** (confirmed at Stage-0 triage).

## Statement

A project in Anchor is stood up, planned, and driven **by talking to its steward**. John
describes the project in his own words; the steward compiles that description into the
project's Face and Campaign Roadmap, proposes a commission for a named roadmap step,
and — only on John's explicit confirmation — Anchor executes it as a real trio run. The
produced plan comes back as an artifact John can read on screen and change by talking;
when he says start, Foreman executes and the Roadmap shows the truth about what is
running. Nothing is spent, written, or started without a human confirmation, and the
campaign ledger remains the single source of truth.

## Success criteria

1. From a **fresh** project with no Face, no Strip and no roadmap, a spoken description
   produces a Face north-star and at least one roadmap step — with **zero** chat turns
   persisted.
2. A commission is **proposed for a named step**, showing the skill, the seat and the
   depth before any spend; nothing runs until John confirms, and the confirmation
   records `who`.
3. Anchor executes the confirmed commission as a real trio run and returns a
   **validated handback**; a malformed handback is refused, never absorbed.
4. The produced plan is rendered as a **reviewable artifact** in the chamber, and a
   spoken correction produces a new version through the same propose → confirm path.
5. The Roadmap's step status reflects the **actual** state of the Anchor session across
   park, restart and kill — it never reports work that is not running.
6. Every one of the above passes with **`ANCHOR_TOKEN` set** (auth ON), asserted on
   outcomes rather than plumbing.
7. `roadmap_events` has exactly **one writer**, proven by a concurrency test, not prose.

## Non-goals (scope boundary)

- **Portfolio altitude** — High Seat cross-project reporting, pause, resource conflicts.
  Deferred deliberately (GROUNDED elevation e-7: prove one round-trip first).
- Any change to Crucible, Foreman or researchPrime themselves.
- New planning intelligence or a bespoke plan template — the Crucible plan shape IS the
  template.
- Steward persona/livery, mobile/iPad, and the two queued Anchor test decisions.
- Anything that makes the steward do the planning itself rather than commission it.

## Risk taxonomy

| Risk | Class | Guard |
|---|---|---|
| Anchor becomes a second ledger writer | Correctness — silent corruption | Single-writer concurrency test (hardening law §1) |
| Scoping dialogue persisted as a chat log | Invariant breach (E5) | Compile-into-Face; a persisted-turns test that must fail |
| Ships green auth-off, broken auth-on | Regression (happened twice this week) | Auth-ON case per mutating endpoint, asserting outcomes |
| Commission spends without confirmation | Irreversible — money/time | `who` required; propose/confirm split; no auto-run |
| Roadmap status drifts from session reality | Honesty | Status derived across full lifecycle, incl. parked |
| Seat crosses family/driver boundary wrong | Fails closed on the default config | Mapping assertion over every `default_cli` value |

## Foresight brief (Oranges)

The literal ask was "make the refine button work". The real intent is that a project
should be steerable by conversation rather than by operating the machinery — which is
why the answer is *commission the vetted planner*, not *ask a model for a plan*. Two to
three steps ahead: once one project's loop works, the portfolio layer becomes a
projection over N of them rather than a new system, and the receipt trail this produces
is what later makes "pause that, what is it costing me, what is blocked" answerable at
all. The trap is building the conversational surface first — it demos well and hides an
unproven round-trip underneath.

## Wave-0 kill gate

> Can a `step_create` event be minted from the scoping dialogue — compiled into the
> Face, not stored as chat — and can a commission then be proposed, confirmed with
> `who`, executed by Anchor, and its result returned as a `status_flip` + a renderable
> artifact, on a **fresh** project, with auth ON?

If that round-trip cannot be made to work, the capability is blocked at the front door.
