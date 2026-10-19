# Anchor R&D Surface v3 — "Mission Control" — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-12

**What was asked:** Anchor R&D Surface v3 — "Mission Control" — Master Plan (frozen design)

**North Star:** > Crucible Stage 1 output, approved 2026-06-11. Supersedes nothing in v2 (which > shipped to master) — it BUILDS ON v2 (sessions.py, summarizer.py, > rnd_terminal.py, deliverables.py, job_runner.py, vendor/xterm). v3 reshapes the > UX (thin rows, in-place expandable accurate summaries), turns the terminal into > a persistent, isolated, real (ConPTY) multi-session window manager, adds clean > stage handoffs + concurrency isolation, and makes the Anchor deliverable > runnable.

## Actions & files produced

- Anchor R&D Surface v3 — "Mission Control" — Master Plan (frozen design)
- Anchor R&D Surface v3 — "Mission Control" — Implementation Plan (Foreman-ready)
- Anchor R&D Surface v3 — "Mission Control" — Execution Log

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star (locked):** Turn the Anchor dashboard into a durable mission-control for trio-driven R&D â€” every project is a thin, full-width row with an accurate auto-generated summary, and clicking any session expands a concise, cached, in-place summary (when Â· what-was-asked Â· North-Star Â· clickable doc links Â· effort in tokens+time) rather than a separate "no summary" page.
- **Trio work runs as persistent, isolated, server-side terminal sessions** managed like stacking windows â€” open / attach / minimize / kill-with-confirm â€” status-colored and surviving disconnect, so launching a session feels like a real terminal.
- **Locked decision #1 â€” Terminal substrate = real ConPTY (via `pywinpty`).** This consciously waives Anchor's "stdlib-only / no native assets" rule for the terminal subsystem only; everything else stays stdlib, and the subsystem (and dashboard) degrades gracefully if `pywinpty` is absent.
- **Locked decision #2 â€” Summaries = proactive background generation, cached.** Generated once at discovery/rescan and right after a run completes; clicking shows a ready cached summary in-place, with lazy "generatingâ€¦" only as a fallback.
- **Locked decision #3 â€” Concurrency isolation = git worktrees per session.** Each plan/research/build session gets its own isolated worktree so concurrent sessions can't dirty each other's trees.
- **Member documents in this planning set:** the frozen Master Plan (design), the Foreman-ready Implementation Plan, and the Execution Log.
- **North Star (locked):** Turn the Anchor dashboard into a durable mission-control for trio-driven R&D, where every project is a thin, full-width row carrying an accurate, auto-generated summary.
- **In-place session summaries:** Clicking any session expands a concise, cached, in-place summary â€” covering *when*, *what-was-asked*, *North-Star*, clickable doc links, and effort in tokens + time â€” never a separate "no summary" page.
- **Persistent server-side terminals:** Trio work runs as persistent, isolated server-side terminal sessions managed like stacking windows (open / attach / minimize / kill-with-confirm), status-colored, and surviving disconnect â€” so launching a session feels like a real terminal.
- **Locked decision #1 â€” Terminal substrate = real ConPTY (via `pywinpty`):** This consciously waives Anchor's "stdlib-only / no native assets" rule for the terminal subsystem only; everything else stays stdlib, and the subsystem (and dashboard) degrades gracefully if `pywinpty` is absent.
- **Locked decision #2 â€” Summaries are proactive, background-generated, and cached:** Generated once (at discovery/rescan and right after a run completes) so clicking shows a ready cached summary in-place; lazy "generatingâ€¦" appears only as a fallback.
- **Locked decision #3 â€” Concurrency isolation = git worktrees per session:** Each plan/research/build session gets its own git worktree so concurrent sessions cannot interfere.
- **Document set:** The session comprises a frozen Master Plan, a Foreman-ready Implementation Plan, and an Execution Log â€” the standard planning-trio trio of design, build plan, and execution record.

## Files

- [Anchor R&D Surface v3 — "Mission Control" — Master Plan (frozen design)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v3%2FMASTER-PLAN.md)
- [Anchor R&D Surface v3 — "Mission Control" — Implementation Plan (Foreman-ready)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v3%2FIMPLEMENTATION-PLAN.md)
- [Anchor R&D Surface v3 — "Mission Control" — Execution Log](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v3%2FEXECUTION-LOG.md)
