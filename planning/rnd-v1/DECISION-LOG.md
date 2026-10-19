# Anchor R&D Control Surface — Decision Log

Decisions and the adversarial findings that drove them (Crucible, 2026-06-07/08).

## Locked user decisions
1. **Brownfield** extend of Anchor (`C:\dev\Anchor`); objective = new capability.
2. Session model → **streaming console, stdlib-only** (not a full TUI; no PTY/deps).
3. Registry → **new parallel R&D registry** (distinct from life-domain projects).
4. Artifacts → **inside each project's `.anchor/`** (pointer-records; engine outputs stay native).
5. v1 scope → **all three trio lanes, Claude Code CLI only** (Gemini deferred).
6. Auth → **run the Anchor service as `john`** (resolves LocalSystem credential wall).
7. Remote → **bind Tailscale interface + shared-secret token** on mutating `/api/*`.
8. Architecture → **launcher + checkpoint/gate broker over the trio's own engines/skills**, not a from-scratch durable terminal.
9. Gate model → **in-session**: parse `AskUserQuestion` from the stream, answer as a text turn (after Spike-0 proved the external checkpoint-broker model fictional for these engines).
10. UX → **Tile A (Rich)** + **Dashboard A (Kanban)**; **collapsible console drawer** with session-tabs + per-lane attention badges; **report viewer PDF-default / Reader(md+KaTeX) fallback**, used for research/plan/build; **cost/time/tokens** rolled up on tiles + per-effort in the dashboard.
11. Folder model → **1 folder : N projects** (registry keyed by `id`, `folder_path` non-unique). "+ New Project" = create-new-folder or select-existing (server-side dir browser); selecting a folder with existing projects offers "add another," not a block. Each project namespaces artifacts under `.anchor/projects/<id>/` and Anchor passes per-project output paths into the engines so same-folder projects don't collide. **Build jobs serialize at the folder level** (shared working tree); research/plan run concurrently. Projects view groups by folder with a folder-build-lock badge. → Waves 3 (new-project flow + id-keyed registry + per-project scaffold + folder grouping) and 6 (per-project engine output paths + folder-level build lock).

## Shark-Tank findings → resolutions (condensed)
- **Stage 1, R1:** trio is human-gated by design; engines already own durability; service=LocalSystem can't auth; "durable/resumable" overscoped. → reshape to launcher+broker; run as john; honest C9.
- **Stage 1, R2:** invented HALT-sentinel/answer channel doesn't exist; LocalSystem→john handoff unsolved; "local+Tailscale" still needs bind+auth. → service-as-john; Tailscale+token; checkpoint-poller (later superseded).
- **Stage 1, R3:** the three lanes are NOT peers — researchPrime is a skill (no engine), Crucible has no generic CLI (only `self-run.mjs` fixture; in-process HALT), Foreman's `--clear-halt` re-runs the wave (no `--approved`; user-gate HALT exits 0). → collapse to **one uniform `claude -p`+skill primitive**; gate = in-session (validated by Spike-0).
- **Stage 2 (waves):** no deterministic **mock runner** (all 3 sharks) → `ANCHOR_RUNNER_CMD` + `fake_claude.py`; **no pytest gate** → Wave 1 establishes it; **infra handed to a code agent** → split `[HUMAN-SETUP]` vs `[AGENT]` (SETUP.md); **W3 too big** → split into Waves 4/5/6; **W0 spike is not a Foreman wave** → pre-Foreman; orphaned **C9 backup** + `.anchor/` git policy + **data migration** → owned by Waves 7/3/2.

## Spike-0 (empirical, 2026-06-07)
Proven on the live host: headless auth as john; multi-turn stdin; `AskUserQuestion`
auto-dismiss-but-surfaces + text-answer continuation; `taskkill /T /F` full-tree reap;
cost/usage/duration in every result envelope. Residual (real Crucible flow) → SETUP go/no-go.
