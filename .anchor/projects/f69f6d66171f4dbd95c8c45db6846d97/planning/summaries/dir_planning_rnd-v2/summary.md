# Anchor R&D Surface v2 — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-11

**What was asked:** Anchor R&D Surface v2 — Master Plan (frozen design)

**North Star:** Make Anchor's R&D surface a **truthful, useful memory** of each project's trio work. Concretely: 1. **Imported history is first-class history.** A brownfield-discovered trio run counts as real project history, not a second-class `import` placeholder. A small honest "imported" provenance chip is fine; the lane status must reflect the *activity*, not masquerade it as empty. 2. **One trio run = one session.** A research / plan / build run is shown as a single *session* the user reads as a clean summary — not as N separate

## Actions & files produced

- Anchor R&D Surface v2 — Execution Log
- Anchor R&D Surface v2 — Master Plan (frozen design)
- Anchor R&D Surface v2 — Implementation Plan (Foreman-ready)

**Effort:** imported — no run metrics

## Goal & key decisions

- **North Star (locked):** Make Anchor's R&D surface a **truthful, useful memory** of each project's trio work â€” imported/brownfield-discovered history is first-class history (not a second-class `import` placeholder), and the lane status reflects real activity rather than masquerading it as empty.
- **One trio run = one session:** A research / plan / build run is presented as a single *session* the user reads as a clean summary, not as N separate per-file cards. A small honest "imported" provenance chip is acceptable.
- **Interactive terminal â€” substrate decision (stream-json REPL):** A true ConPTY terminal needs a native dependency, which violates Anchor's stdlib-only / no-compiled-assets rule. v2 keeps the terminal *feel* via vendored **xterm.js** (as KaTeX is already vendored) over a **persistent `stream-json` REPL** â€” one long-lived `claude`/`gemini` process per session, user turns POSTed to stdin, assistant output streamed back via **SSE** (replacing the 1.5s poll). It generalizes the existing gate-stdin mechanism, auto-seeds the right skill per lane, and on exit auto-discovers produced files to confirm adoption as a session.
- **Follow-up â€” real xterm.js swap (user decision, GO 2026-06-11):** User chose real xterm.js over the lightweight anchor-term console. Vendored real `@xterm/xterm 6.0.0` (offline copy, MIT LICENSE + PROVENANCE) into `vendor/xterm/`; rewrote `vendor/anchor-term/anchor-term.js` as an **adapter** over `new window.Terminal(...)` preserving the same `window.AnchorTerm.mount` API, gates, discoverâ†’adopt panel, and beforeunload reap; added a traversal-safe `/vendor/xterm/` static route + includes (xterm before anchor-term). Backend `rnd_terminal.py` + SSE/term endpoints were **byte-unchanged** (verified via empty git diff).
- **Verification:** The xterm.js swap passed the orchestrator-run gate at **394 passed**.
- **Document set:** This planning session comprises the frozen Master Plan, the Foreman-ready Implementation Plan, and the Execution Log for Anchor R&D Surface v2.
- **North Star (locked):** Make Anchor's R&D surface a **truthful, useful memory** of each project's trio work â€” imported/brownfield-discovered history is treated as first-class project history (an honest "imported" provenance chip is allowed, but lane status must reflect real activity, never masquerade as empty).
- **One trio run = one session:** a research/plan/build run is presented as a single session the user reads as a clean summary, not as N separate per-file cards.
- **Interactive terminal substrate decision (stream-json REPL):** a true ConPTY terminal would require a native dependency, violating Anchor's stdlib-only / no-compiled-assets rule, so v2 keeps the terminal *feel* over a persistent `stream-json` REPL â€” one long-lived `claude`/`gemini` process per session, user turns POSTed to stdin, assistant output streamed back via **SSE** (stdlib-friendly, replacing the 1.5s poll).
- **REPL substrate behavior:** it generalizes the existing gate-stdin mechanism, auto-seeds the correct trio skill per lane, and on process exit auto-discovers produced files and asks the user to confirm adoption as a session.
- **xterm.js vendored for the console UI:** the terminal feel uses vendored **xterm.js** (the same way KaTeX is already vendored) rather than a native console.
- **Follow-up â€” real xterm.js swap (user decision, GO 2026-06-11):** the user chose real xterm.js over the lightweight anchor-term console; the team vendored an offline copy of `@xterm/xterm 6.0.0` (MIT LICENSE + PROVENANCE) into `vendor/xterm/` and rewrote `vendor/anchor-term/anchor-term.js` as an **adapter** over `new window.Terminal(...)`, preserving the same `window.AnchorTerm.mount` API, gates, discoverâ†’adopt panel, and beforeunload reap.
- **xterm swap was UI-only:** a traversal-safe `/vendor/xterm/` static route was added (xterm included before anchor-term), and the backend `rnd_terminal.py` + SSE/terminal endpoints were left **byte-unchanged** (verified by an empty git diff).
- **Verification gate:** the orchestrator-run gate passed (**394 passed**) for the xterm.js swap follow-up.
- **Member documents:** the session comprises the v2 Master Plan (frozen design), the v2 Implementation Plan (Foreman-ready), and the v2 Execution Log.

## Files

- [Anchor R&D Surface v2 — Execution Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v2%2FEXECUTION-LOG.md)
- [Anchor R&D Surface v2 — Master Plan (frozen design)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v2%2FMASTER-PLAN.md)
- [Anchor R&D Surface v2 — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v2%2FIMPLEMENTATION-PLAN.md)
