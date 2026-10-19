# Anchor R&D Surface v2 — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-11

**What was asked:** Anchor R&D Surface v2 — Master Plan (frozen design)

**North Star:** Make Anchor's R&D surface a **truthful, useful memory** of each project's trio work. Concretely: 1. **Imported history is first-class history.** A brownfield-discovered trio run counts as real project history, not a second-class `import` placeholder. A small honest "imported" provenance chip is fine; the lane status must reflect the *activity*, not masquerade it as empty. 2. **One trio run = one session.** A research / plan / build run is shown as a single *session* the user reads as a clean summary — not as N separate

## Actions & files produced

- Anchor R&D Surface v2 — Master Plan (frozen design)
- Anchor R&D Surface v2 — Implementation Plan (Foreman-ready)
- Anchor R&D Surface v2 — Execution Log

**Effort:** imported — no run metrics

## Goal & key decisions

- Here's a grounded summary of the planning trio session, drawn from the provided anchors and member documents:
- ## Anchor R&D Surface v2 â€” Master Plan (frozen design)
- **North Star (locked)**
- The goal is to make Anchor's R&D surface a **truthful, useful memory** of each project's trio work â€” surfacing real activity, not placeholders.
- **Imported history is first-class history.** A brownfield-discovered trio run counts as real project history, not a second-class `import` placeholder. An honest "imported" provenance chip is acceptable, but a lane's status must reflect actual *activity* rather than masquerade real work as empty.
- **One trio run = one session.** A research/plan/build run is presented as a single *session* the user reads as a clean summary, not as N separate per-file cards.
- **Interactive terminal â€” substrate decision (stream-json REPL)**
- A true ConPTY terminal was rejected because it requires a native dependency, violating Anchor's stdlib-only / no-compiled-assets rule.
- v2 instead preserves the terminal **feel** via vendored **xterm.js** (the same vendoring approach already used for KaTeX) layered over a **persistent `stream-json` REPL**: one long-lived `claude`/`gemini` process per session, user turns POSTed to stdin, assistant output streamed back over **SSE** (replacing the prior 1.5s poll).
- The REPL **generalizes the existing gate-stdin mechanism**, auto-seeds the correct skill per lane, and on process exit auto-discovers produced files and asks the user to confirm adoption as a session.
- **Follow-up â€” real xterm.js swap (user decision, GO 2026-06-11)**
- The user chose **real xterm.js** over the lightweight `anchor-term` console.
- Execution: vendored real `@xterm/xterm 6.0.0` (offline copy, MIT LICENSE + PROVENANCE) into `vendor/xterm/`; rewrote `vendor/anchor-term/anchor-term.js` as an **adapter** over `new window.Terminal(...)` that preserves the same `window.AnchorTerm.mount` API, gates, discoverâ†’adopt panel, and beforeunload reap.
- Added a traversal-safe `/vendor/xterm/` static route with includes ordered xterm-before-anchor-term.
- Backend `rnd_terminal.py` and the SSE/terminal endpoints were left **byte-unchanged** (verified via an empty git diff).
- **Member documents**
- Anchor R&D Surface v2 â€” Master Plan (frozen design)
- Anchor R&D Surface v2 â€” Implementation Plan (Foreman-ready)
- Anchor R&D Surface v2 â€” Execution Log
- One honest gap: the final gate result line is cut off in the source anchor, so I've reported only the verified "394 passed" portion rather than inferring the rest.
- **North Star (locked):** Make Anchor's R&D surface a *truthful, useful memory* of each project's trio work â€” not a placeholder. Two locked principles: imported (brownfield-discovered) trio history is first-class history (an honest "imported" provenance chip is fine, but lane status must reflect actual activity rather than masquerade as empty), and one trio run = one session shown as a single clean summary rather than N separate per-file cards.
- **Interactive terminal substrate decision (stream-json REPL):** Because a true ConPTY terminal needs a native dependency that violates Anchor's stdlib-only / no-compiled-assets rule, v2 keeps the terminal *feel* via vendored xterm.js (the same way KaTeX is vendored) running over a persistent `stream-json` REPL â€” one long-lived `claude`/`gemini` process per session, user turns POSTed to stdin, assistant output streamed back via SSE (replacing the 1.5s poll). It generalizes the existing gate-stdin mechanism, auto-seeds the correct skill per lane, and on exit auto-discovers produced files to confirm adoption as a session.
- **Follow-up â€” real xterm.js swap (user decision, GO 2026-06-11):** The user chose real xterm.js over the lightweight anchor-term console. Execution vendored an offline copy of `@xterm/xterm 6.0.0` (with MIT LICENSE + PROVENANCE) into `vendor/xterm/`, and rewrote `vendor/anchor-term/anchor-term.js` as an adapter over `new window.Terminal(...)` that preserves the same `window.AnchorTerm.mount` API, gates, discoverâ†’adopt panel, and beforeunload reap. A traversal-safe `/vendor/xterm/` static route plus includes were added (xterm loaded before anchor-term).
- **Backend left untouched by the swap:** `rnd_terminal.py` and the SSE/terminal endpoints were byte-unchanged, verified via an empty git diff â€” the xterm.js change was purely a frontend console substitution.
- **Member documents:** This planning trio comprises three frozen docs â€” the Master Plan (frozen design), the Implementation Plan (Foreman-ready), and the Execution Log.
- *Note: the available anchors cover the North Star and the terminal-substrate decision in detail but only sample the broader Master Plan â€” other v2 surface areas (sessions model, summaries, grass catchers, deliverables) are referenced by the document set but not quoted here, so I haven't asserted claims about them.*

## Files

- [Anchor R&D Surface v2 — Master Plan (frozen design)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v2%2FMASTER-PLAN.md)
- [Anchor R&D Surface v2 — Implementation Plan (Foreman-ready)](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v2%2FIMPLEMENTATION-PLAN.md)
- [Anchor R&D Surface v2 — Execution Log](/artifact/2fe37f39157f4c7aa3e2523baa41f40f?path=planning%2Frnd-v2%2FEXECUTION-LOG.md)
