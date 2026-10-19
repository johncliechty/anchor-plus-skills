# Anchor R&D Surface v4 — "Project Cockpit" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-13

**What was asked:** Anchor R&D Surface v4 — "Project Cockpit" — Master Plan (frozen design)

**North Star:** Make each project's window a **calm, single-screen cockpit** for its trio work. Every lane (Research · Planning · Build) shows its most-recent session as a **tile with one honest status light** (green=working · amber=needs-you · red=crashed · grey=idle/done). Clicking a tile **expands an inline panel in place** — never a new page — that **stacks a balanced summary on top of a real, resizable terminal below**. Opening a new session **feels exactly like a normal Claude Code / Gemini session**: the lane's skill auto-loads **once**, greets **once**, then behaves normally — no repeating-prompt loop

## Actions & files produced

- Anchor R&D Surface v4 — "Project Cockpit" — Execution Log
- Anchor R&D Surface v4 — "Project Cockpit" — Master Plan (frozen design)
- Anchor R&D Surface v4 — "Project Cockpit" — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- # Anchor R&D Surface v4 â€” "Project Cockpit" â€” Planning Session Summary
- **Goal (North Star, locked)**
- Make each project's window a calm, single-screen **cockpit** for its trio work â€” Research Â· Planning Â· Build.
- Each lane shows its most-recent session as a **tile with one honest status light**: green = working Â· amber = needs-you Â· red = crashed Â· grey = idle/done.
- Clicking a tile **expands an inline panel in place** (never a new page) that stacks a **balanced summary on top** over a **real, resizable terminal below**.
- A new session must **feel like a normal Claude Code / Gemini session**: the lane's skill auto-loads **once**, greets **once**, then behaves normally â€” explicitly killing the repeating-prompt loop.
- **Key locked decisions (Stage 0/1 user gates)**
- **One terminal substrate.** The project window uses ONLY the v3 ConPTY path (`terminal_session.py` â†’ `pty_manager.py` â†’ xterm.js via `term_ws` / `term_stream2`).
- The v2 stream-json REPL (`rnd_terminal.py`) is **unwired from the project window** â€” the module stays on disk but the cockpit no longer uses it.
- **Raw xterm is the default** for interactive Claude/Gemini.
- **Skill auto-loads once, greets once.** On a new session, the lane's skill (Research â†’ researchPrime Â· Planning â†’ Crucible Â· Build â†’ Foreman) is loaded by **one opening stdin turn**; the model greets a single time and then waits.
- **Document set (this planning session's members)**
- Master Plan (frozen design) â€” the locked North Star + decisions above.
- Execution Log â€” the per-stage record of the planning/build work.
- *Note on grounding:* These claims are drawn from the Master Plan's North Star and the locked Stage 0/1 decisions surfaced in the anchors, plus the member-document titles. I did not have the full body text of the Implementation Plan or Execution Log in this session, so I've limited claims about them to what their titles and the shared frozen design support â€” I did not fabricate wave counts, status, or build outcomes beyond the anchored decisions.
- ## Anchor R&D Surface v4 â€” "Project Cockpit" â€” Planning Summary
- **Goal / North Star (locked)**
- Make each project's window a **calm, single-screen cockpit** for its trio work â€” Research Â· Planning Â· Build.
- Every lane shows its **most-recent session as a tile with one honest status light**: green = working Â· amber = needs-you Â· red = crashed Â· grey = idle/done.
- Clicking a tile **expands an inline panel in place** â€” never a new page â€” that **stacks a balanced summary on top of a real, resizable terminal below**.
- Opening a new session must **feel exactly like a normal Claude Code / Gemini session**: the lane's skill auto-loads **once**, greets **once**, then behaves normally â€” **no repeating-prompt loop**.
- **Key decisions (Stage 0/1 user-gated, locked)**
- The **v2 stream-json REPL (`rnd_terminal.py`) is unwired** from the project window â€” the module stays on disk but is not used by the cockpit.
- **Skill auto-loads once, greets once.** Per-lane mapping: Research â†’ researchPrime Â· Planning â†’ Crucible Â· Build â†’ Foreman.
- The skill is loaded by **one opening stdin turn**; the model greets **a single time** (e.g. "âœ“ Crucible loadedâ€¦") and then waits â€” never re-sent.
- **Document set (this planning session)**
- Master Plan â€” frozen design (the anchor doc above).
- Implementation Plan â€” Foreman-ready (wave-by-wave build plan).
- Execution Log â€” per-wave EXECUTE/REVIEW/FIX/JUDGE history.
- A note for grounding honesty: the anchors provided cover the **North Star** and the **two locked Stage-0/1 decisions**, plus the three member-doc titles. The full Master Plan almost certainly contains more locked decisions (engine policy, doc-roles, rollup, grass promote, deliverable launch-by-type, flat rows/masthead) â€” those appear in the project's CLAUDE.md but are **not present in the excerpt I was given**, so I have not asserted them here. If you want a complete grounded summary, point me at the full `planning/rnd-v4/MASTER-PLAN.md` text and I'll extend the claims.

## Files

- [Anchor R&D Surface v4 — "Project Cockpit" — Execution Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v4%2FEXECUTION-LOG.md)
- [Anchor R&D Surface v4 — "Project Cockpit" — Master Plan (frozen design)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v4%2FMASTER-PLAN.md)
- [Anchor R&D Surface v4 — "Project Cockpit" — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v4%2FIMPLEMENTATION-PLAN.md)
