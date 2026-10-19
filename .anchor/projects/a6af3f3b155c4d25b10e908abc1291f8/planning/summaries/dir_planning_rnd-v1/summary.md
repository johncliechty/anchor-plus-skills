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

- This planning session ran Crucible over the Anchor codebase on 2026-06-07 and 06-08 and produced a frozen, Foreman-ready design for turning Anchor from a task and project tracker into a per-project R&D control surface. The locked North Star treats each code project as a folder, with a single dashboard window that drives the researchPrime → Crucible → Foreman trio as durable, server-owned Claude Code jobs on gwl-server, complete with versioned effort history, task-to-project linking, project lifecycle states, deliverable execution, and a data-free public distribution. The session settled the core architecture around one uniform job primitive: every lane is the same `claude -p` stream-json invocation running the relevant skill in the project's working directory, owned by the Anchor server, with no per-lane orchestration, no PTY, and stdlib only. Skill gates such as AskUserQuestion are handled in-session by surfacing the structured question in the stream and sending the user's choice back as a plain text turn. Alongside those design decisions, the user locked several scope and infrastructure choices: a brownfield extension of the existing Anchor repo, a streaming console rather than a full TUI, a new parallel R&D registry distinct from life-domain projects, artifacts stored as pointer-records inside each project's `.anchor/` folder, all three trio lanes on Claude Code CLI only with Gemini deferred, the Anchor service running as the `john` user to clear the LocalSystem credential wall, and remote access via the Tailscale interface with a shared-secret token on mutating API calls. The session delivered four documents: the Master Plan capturing the frozen design, the Implementation Plan ready for Foreman to build, a Decision Log recording each decision and the adversarial Shark-Tank findings that drove it, and an Execution Log tracking the run itself.

## Files

- [Anchor R&D Control Surface — Execution Log](/artifact/a6af3f3b155c4d25b10e908abc1291f8?path=planning%2Frnd-v1%2FEXECUTION-LOG.md)
- [Anchor R&D Control Surface — Master Plan (frozen design)](/artifact/a6af3f3b155c4d25b10e908abc1291f8?path=planning%2Frnd-v1%2FMASTER-PLAN.md)
- [Anchor R&D Control Surface — Implementation Plan (Foreman-ready)](/artifact/a6af3f3b155c4d25b10e908abc1291f8?path=planning%2Frnd-v1%2FIMPLEMENTATION-PLAN.md)
- [Anchor R&D Control Surface — Decision Log](/artifact/a6af3f3b155c4d25b10e908abc1291f8?path=planning%2Frnd-v1%2FDECISION-LOG.md)
