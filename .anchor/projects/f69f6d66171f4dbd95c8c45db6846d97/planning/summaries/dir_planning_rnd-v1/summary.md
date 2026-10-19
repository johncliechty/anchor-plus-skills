# Anchor R&D Control Surface — Master Plan (frozen design)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-08

**What was asked:** Anchor R&D Control Surface — Master Plan (frozen design)

**North Star:** Turn Anchor from a task/project tracker into a **per-project R&D control surface**: each code project is a folder (e.g. `C:\dev\Agentic-Home`, `C:\dev\Anchor`); a single-instance dashboard window drives the **researchPrime → Crucible → Foreman** trio as durable, server-owned Claude Code jobs on gwl-server, with versioned effort history, task↔project integration, project lifecycle states, deliverable execution, and a data-free public distribution.

## Actions & files produced

- Anchor R&D Control Surface — Execution Log
- Anchor R&D Control Surface — Master Plan (frozen design)
- Anchor R&D Control Surface — Implementation Plan (Foreman-ready)
- Anchor R&D Control Surface — Decision Log

**Effort:** imported — no run metrics

## Goal & key decisions

- ## Anchor R&D Control Surface â€” Master Plan (planning session summary)
- **Goal / North Star (locked)**
- Transform Anchor from a task/project tracker into a **per-project R&D control surface**, where each code project is a folder (e.g. `C:\dev\Agentic-Home`, `C:\dev\Anchor`).
- A single-instance dashboard window drives the **researchPrime â†’ Crucible â†’ Foreman** trio as durable, server-owned Claude Code jobs on gwl-server.
- Scope includes versioned effort history, taskâ†”project integration, project lifecycle states, deliverable execution, and a data-free public distribution.
- **Key locked decisions (Master Plan)**
- **D1 â€” One uniform job primitive:** a job is `claude -p --input-format stream-json --output-format stream-json` running the relevant skill (researchPrime / crucible / foreman) in the project cwd, **owned by the Anchor server**. A lane = which skill + prompt template; no per-lane orchestration code, no PTY, stdlib only.
- **D2 â€” Gate handling is in-session:** a skill's `AskUserQuestion` gate surfaces in the stream (auto-dismisses headless, but the structured question stays visible); Anchor renders it in a prompt box and sends the user's choice back as a plain text turn to continue the session.
- **Locked user decisions (Decision Log, Crucible 2026-06-07/08)**
- **Brownfield extend of Anchor** (`C:\dev\Anchor`); objective = new capability.
- Session model = **streaming console, stdlib-only** â€” not a full TUI, no PTY/deps.
- Registry = a **new parallel R&D registry**, distinct from life-domain projects.
- Artifacts stored **inside each project's `.anchor/`** as pointer-records; engine outputs stay native.
- v1 scope = **all three trio lanes, Claude Code CLI only** (Gemini deferred).
- Auth = **run the Anchor service as `john`** (resolves the LocalSystem credential wall).
- Remote access = **bind the Tailscale interface + a shared-secret token** on mutating `/api/*`.
- The decisions above are documented as adversarial findings driven by the Crucible planning process.
- Member documents backing this summary: Master Plan (frozen design), Implementation Plan (Foreman-ready), Decision Log, and Execution Log.
- **Objective (North Star, locked):** Transform Anchor from a task/project tracker into a **per-project R&D control surface** â€” each code project is a folder (e.g. `C:\dev\Agentic-Home`, `C:\dev\Anchor`), and a single-instance dashboard drives the **researchPrime â†’ Crucible â†’ Foreman** trio as durable, server-owned Claude Code jobs on gwl-server.
- **Scope of the surface:** versioned effort history, taskâ†”project integration, project lifecycle states, deliverable execution, and a data-free public distribution.
- **D1 â€” One uniform job primitive:** a job is `claude -p --input-format stream-json --output-format stream-json` running the relevant skill (researchPrime / crucible / foreman) in the project cwd, **owned by the Anchor server**. The lane only selects which skill + prompt template â€” no per-lane orchestration code, no PTY, stdlib only.
- **D2 â€” In-session gate handling:** a skill's `AskUserQuestion` gate surfaces in the stream (auto-dismisses headless, but the structured question stays visible); Anchor renders it in a prompt box and sends the user's choice back as a plain-text turn to drive continuation.
- **Brownfield extension:** the work is a brownfield extension of Anchor (`C:\dev\Anchor`); the objective is a new capability, not a rewrite.
- **Session model:** a **streaming console, stdlib-only** approach â€” explicitly not a full TUI, no PTY, no dependencies.
- **Registry:** a **new parallel R&D registry**, kept distinct from the existing life-domain projects.
- **Artifacts:** stored **inside each project's `.anchor/`** as pointer-records; the engine's native outputs stay in place (not copied/transformed).
- **v1 lane scope:** all three trio lanes, **Claude Code CLI only** â€” Gemini deferred.
- **Auth decision:** run the Anchor service as **`john`** to resolve the LocalSystem credential wall.
- **Remote access:** bind the **Tailscale interface + a shared-secret token** on mutating `/api/*` endpoints.
- **Provenance:** decisions and their driving adversarial findings were recorded in a Crucible Decision Log dated 2026-06-07/08; the member set is the four frozen planning docs (Master Plan, Implementation Plan, Decision Log, Execution Log).

## Files

- [Anchor R&D Control Surface — Execution Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v1%2FEXECUTION-LOG.md)
- [Anchor R&D Control Surface — Master Plan (frozen design)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v1%2FMASTER-PLAN.md)
- [Anchor R&D Control Surface — Implementation Plan (Foreman-ready)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v1%2FIMPLEMENTATION-PLAN.md)
- [Anchor R&D Control Surface — Decision Log](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Frnd-v1%2FDECISION-LOG.md)
