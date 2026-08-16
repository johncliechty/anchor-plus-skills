# Ecgberht — product vision (John, 2026-07-23)

## One-sentence

Ecgberht is the continuous steward of work: at **project** level it keeps each kingdom’s campaign order; at **portfolio** level it keeps the map of all kingdoms, time, and AI capacity — so opening Anchor always answers *where am I, what matters next, and why*.

## Interaction model (JARVIS, not a build bot)

Inspired by Iron Man’s JARVIS:

- **Always oriented** — greets with state, not empty chat.
- **Anticipatory, not pushy** — “meeting in 90 minutes; prep for X from project Y.”
- **Honest uncertainty** — estimates and suggestions labeled; never fake certainty.
- **Delegate to specialists** — plans via Crucible, builds via Foreman, deep critique via Gandalf, research via researchPrime; Ecgberht chooses *whether* and *how deep*, not *how to code the module*.
- **Memory that survives sessions** — MD/files (v0) → structured project state (v1) → portfolio heartbeat (v2).
- **Quiet competence** — short, high-signal; status tables for long runs; no ceremony theater.

## Project-level Ecgberht (per project)

Each project can own:

| Surface | Intent |
|---------|--------|
| **North star** | Whole-project concluding goal (one paragraph) |
| **Effort roadmap** | Ordered E0…En with status, tool depth, done-when |
| **Active pointer** | Doing / next / waiting / last updated |
| **Grasscatcher** | Parked ideas with provenance (“we put this here so we don’t forget”) |
| **Oranges / foresight** | Light 1–2 steps ahead (not full Crucible Oranges engine) |
| **Idea intake** | Soft-vet: keep / grasscatch / drop-with-reason — **not** Shark Tank |
| **Status addendum** | After global 10‑min table: Project / Effort / Done / Next / Waiting / Backlog |
| **Tool-depth judgment** | LITE / FULL / SPIKE-FIRST / ops-only / advisory skill |

**Anchor UX:** Work dashboard → open project → **project dashboard** with Ecgberht panel (state + next actions + grasscatcher + launch Crucible/Foreman when locked).

## Portfolio-level Ecgberht (Anchor top)

| Capability | Intent |
|------------|--------|
| **Project map** | All projects: phase, health, next recommended action |
| **Next-attention ranking** | Across projects: what to think about *now* and why |
| **Calendar (later)** | Google + Outlook (+ others): prep for meetings/classes |
| **Email streams (later)** | Gmail + Outlook: surface actionable signals into action lists / projects |
| **AI capacity** | Token usage, subscription headroom, “buy more / switch plan” warnings |
| **Teaching / classes** | Class cadence and workflow improvements when calendar says so |
| **Action lists** | Tie projects + calendar + grasscatcher into one attention model |
| **Morning brief** | High-fidelity start-of-day (status, blockers, prep, capacity) |

**Anchor UX:** Main work dashboard hosts portfolio Ecgberht; project open dives into project Ecgberht.

## Explicit non-goals (this generation)

- Not a second Crucible, Foreman, or Gandalf.
- Not multi-agent swarm cost explosion (see prior-art critique of early OpenClaw Ecgberht plans).
- Not in the **48-hour shareable Anchor** cut — next-gen after that archive.
- Not automated bank login scraping, tax engine, or full Quicken replacement (those remain project-domain).

## Success criteria (design phase)

1. **Pilot as example:** Family-Finances Ecgberht MD remains a **read-only behavioral seed** (very early version) — shape to learn from, not a build target for this design effort.
2. **Skill shape:** Foundry-ready skill sketch with clear compose boundaries (commissions trio/foundry; does not reimplement).
3. **Two-altitude state model:** project file set + portfolio heartbeat that scales without N× full-memory reads.
4. **Anchor surfaces:** wireframe-level project panel + portfolio panel (no launch-cut code required).
5. **Best-in-class pressure:** researchPrime + Jumper + Gandalf artifacts land in this folder with honesty stamps.

## Naming law

- **Always:** Ecgberht  
- **Never for this role:** Expert, Jarvis-as-product-name (JARVIS is the metaphor only), Jervis  
- Historical variants in prose OK only once: Egbert / Ecgbert
