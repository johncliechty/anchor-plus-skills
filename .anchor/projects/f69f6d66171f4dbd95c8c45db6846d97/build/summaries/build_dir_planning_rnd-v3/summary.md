# rnd-v3

*Lane: build · validated, cached summary*

**When run:** 2026-06-12

**What was asked:** rnd-v3

**North Star:** > Foreman appends per-wave EXECUTE / GATE / REVIEW / FIX / JUDGE entries here. > Seeded by the Crucible→Foreman handoff on 2026-06-11. Frozen design: > `MASTER-PLAN.md`. Plan: `IMPLEMENTATION-PLAN.md`. Gate: `python -m pytest -v`.

## Actions & files produced

- Anchor R&D Surface v3 — "Mission Control" — Execution Log

**Effort:** imported — no run metrics

## What was built & errors overcome

- This is a **build trio session** for the project titled **rnd-v3** ("Anchor R&D Surface v3 â€” Mission Control").
- The session's member document is the **Execution Log** for "Anchor R&D Surface v3 â€” Mission Control" â€” the per-wave build record produced during the build (Foreman) stage.
- Summary of the **rnd-v3** build trio session, grounded in the Execution Log:
- ## Anchor R&D Surface v3 â€” "Mission Control" (build trio session)
- Crucible handed off on 2026-06-11 (Stage 0 North Star locked, Stage 1 Master Plan approved, Stage 2 10-wave plan converged); waves executed 2026-06-11 â†’ 2026-06-12.
- **Per-wave claims**
- **Wave 1 (HARD GATE) â€” ConPTY substrate.** `pty_manager.py` with a backend seam (real `pywinpty` + deterministic in-memory `stub`, env-selected by `ANCHOR_PTY_BACKEND`); `winpty` lazy-imported and isolated to that one module. The empirical spike proved a real `pywinpty` `claude` TUI runs under a simulated non-interactive `anchor`-service context (computed product round-tripped, proving execution not just echo) â€” the HALT condition was never triggered. Gate: 409 passed, 1 skipped.
- **Wave 2 â€” durable session registry + git-worktree isolation.** `session_registry.py` (atomic `.anchor/sessions.json`, statusâ†’color map) + `worktrees.py` (per-session worktrees under a git-ignored managed base). A reviewer caught a MAJOR branch-naming collision bug (12-char truncation) â€” fixed to full-id slug + 16-hex SHA-1 with always-fresh branches. Gate: 429 passed.
- **Wave 3 â€” terminal service + transport + auth.** `terminal_session.py` ties PTY + registry + worktrees; transport is a stdlib hand-rolled WebSocket (`term_ws`, verified against the RFC-6455 reference key) plus SSE-out/POST-in fallback. Auth enforced before any side effect on all six endpoints. Gate: 449 passed.
- **Wave 4 â€” stacking window-manager UI.** Status-colored session button bar + draggable/resizable/minimizable terminal windows mounting xterm.js; X=kill-with-confirm, minimize keeps the session running. Added an XSS-regression test + `nosniff` header. Gate: 455 passed.
- **Wave 5 â€” thin project rows + proactive project summary.** `summarizer.summarize_project` (generate-twice through the runner seam, grounding-filtered, cached); render path reads cache only, generation is background-on-rescan. Gate: 467 passed. Recorded residual risk: the grounding filter is deterministic term-overlap, not semantic.
- **Process claims**
- Every wave passed an **orchestrator-run** ground-truth gate (never a sub-agent's pasted output) plus **two independent adversarial reviewers**.

## Files

- [Anchor R&D Surface v3 — "Mission Control" — Execution Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v3%2FEXECUTION-LOG.md)
