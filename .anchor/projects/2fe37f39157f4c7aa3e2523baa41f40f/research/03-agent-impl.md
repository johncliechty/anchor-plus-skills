# Anchor — Agent-Implementation Brief

*Machine-oriented projection of the orientation. Structured form in `03-agent-impl.json`. DEGRADED prose mode — adversarial Node engine did NOT run; `cross_model:false`.*

## TL;DR for an agent picking up this repo
- **Two products, one folder:** (a) stdlib markdown task manager (`anchor_gui.py`, runs as NSSM service `anchor` on `localhost:8777`, writes markdown directly, no DB); (b) an R&D control surface running the **researchPrime→Crucible→Foreman** trio as durable `claude` jobs.
- **Build state = DONE & merged.** rnd-v2 = 8 Foreman waves GREEN, PROJECT DONE 2026-06-11, on `master`, 20 commits ahead of origin (unpushed). Ignore `foreman-checkpoint.json` (says wave1/running — STALE) and `EXECUTION-LOG.md:111` (says not-merged — STALE). The tree is the truth.
- **Closed since prior research:** `effort_history` is now wired into the live GUI (was the prior run's #1 gap).

## Hard constraints (do not violate)
1. Markdown files are source-of-truth; no DB, no undo. Never blanket-kill `pythonw`. Restart only via `nssm restart anchor` (elevated).
2. Shipped product must stay **stdlib-only** (enforced by `dist_manifest.txt` deny-by-default + `distro.py` PII scanner). flask/Pillow/pywin32 exist in the tree but are non-shipped utilities.
3. This research lane must **not mutate the working tree**; all output lives under `.anchor/projects/2fe37f39…/research/`.

## Next actions, ordered
1. **Verify R1 (UNVERIFIED):** is the live service running the merged code? `nssm restart anchor` if unsure; then `git push`.
2. **Reconcile** the 3 Anchor ids on `C:\dev\Anchor` (sessions stranded on retired `227eb089`/`bfe0e754`).
3. **Durability:** commit/track or deliberately ignore `rnd_registry.json` + `.anchor/` pointer-records (README policy C9 says track) + `Anchor.md`.
4. **Cleanup:** 16 retired temp test projects; 1 failed + ≥1 orphaned `running` job record; `domains/test.md`; stale `requirements.txt`; dead `anchor_server.py`.
5. **Feature:** Gemini plan/build adapter (`planning/gemini-adapter/PLAN.md`; `lanes.GEMINI_LANES={'research'}` today).
6. **De-risk R2:** one real, non-stubbed end-to-end trio dogfood run (all gate/liveness paths are stub-only today).

## Verification ladder honesty
- **OBSERVED** (direct file/git read): architecture, module set, xterm swap, merge-to-master, effort_history wiring, stale checkpoint, registry/job state, health OK.
- **CLAIMED** (docs/log, not re-executed): pytest pass counts; Phase-F deferral list; `domains/test.md` debris.
- **UNVERIFIED** (blocked): all live runtime facts — service status, single-listener-on-8777, pid liveness, whether the running process loaded the new code.
