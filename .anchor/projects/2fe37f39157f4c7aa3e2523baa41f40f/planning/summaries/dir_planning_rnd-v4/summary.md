# Anchor R&D Surface v4 — "Project Cockpit" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-13

**What was asked:** Anchor R&D Surface v4 — "Project Cockpit" — Master Plan (frozen design)

**North Star:** Make each project's window a **calm, single-screen cockpit** for its trio work. Every lane (Research · Planning · Build) shows its most-recent session as a **tile with one honest status light** (green=working · amber=needs-you · red=crashed · grey=idle/done). Clicking a tile **expands an inline panel in place** — never a new page — that **stacks a balanced summary on top of a real, resizable terminal below**. Opening a new session **feels exactly like a normal Claude Code / Gemini session**: the lane's skill auto-loads **once**, greets **once**, then behaves normally — no repeating-prompt loop

## Actions & files produced

- Anchor R&D Surface v4 — "Project Cockpit" — Master Plan (frozen design)
- Anchor R&D Surface v4 — "Project Cockpit" — Implementation Plan (Foreman-ready)
- Anchor R&D Surface v4 — "Project Cockpit" — Execution Log

**Effort:** imported — no run metrics

## Goal & key decisions

- The session is the **frozen planning trio for "Anchor R&D Surface v4 â€” Project Cockpit"**, comprising three member documents: the Master Plan (frozen design), the Foreman-ready Implementation Plan, and the Execution Log.
- **North Star (locked):** make each project's window a calm, single-screen cockpit for its trio work, where every lane (Research Â· Planning Â· Build) shows its most-recent session as a tile with one honest status light.
- The status light encodes exactly four states: **green = working Â· amber = needs-you Â· red = crashed Â· grey = idle/done**.
- Clicking a lane tile **expands an inline panel in place â€” never a new page** â€” that stacks a balanced summary on top of a real, resizable terminal below.
- Opening a new session is meant to **feel like a normal Claude Code / Gemini session**: the lane's skill auto-loads once, greets once, then behaves normally â€” with no repeating-prompt loop.
- **Locked decision #1 â€” one terminal substrate:** the project window uses ONLY the v3 ConPTY path (`terminal_session.py` â†’ `pty_manager.py` â†’ xterm.js via `term_ws` / `term_stream2`); the v2 stream-json REPL (`rnd_terminal.py`) is unwired from the project window (the module stays but is unused by the cockpit), and **raw xterm is the default** for interactive Claude/Gemini.
- **Locked decision #2 â€” skill auto-loads once, greets once:** on a NEW session the lane's skill (Research â†’ researchPrime Â· Planning â†’ Crucible Â· Build â†’ Foreman) is loaded by a single opening stdin turn, and the model greets a single time, then waits.
- These locked decisions were established through **Stage 0 / Stage 1 user gates** in the planning process.
- I'll ground this summary in the actual member documents rather than just the anchors. Let me read them.

## Files

- [Anchor R&D Surface v4 — "Project Cockpit" — Master Plan (frozen design)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v4%2FMASTER-PLAN.md)
- [Anchor R&D Surface v4 — "Project Cockpit" — Implementation Plan (Foreman-ready)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v4%2FIMPLEMENTATION-PLAN.md)
- [Anchor R&D Surface v4 — "Project Cockpit" — Execution Log](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v4%2FEXECUTION-LOG.md)
