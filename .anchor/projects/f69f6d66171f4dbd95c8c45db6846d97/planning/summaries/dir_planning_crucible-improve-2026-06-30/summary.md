# Master Plan — Anchor Improvement Effort (Crucible Stage 1)

*Lane: planning · validated, cached summary*

**When run:** 2026-06-30

**What was asked:** Master Plan — Anchor Improvement Effort (Crucible Stage 1)

**North Star:** - **(A) Resumable sessions** — leave any effort, click to carry on (phase + docs + skills + summary). Includes brownfield/discovered efforts + model-switch handoff. - **(B) Honest UI & warnings** — latest-per-tab + "previous" link; collapsed deliverables; correct terminal controls + width; warnings only on real problems; Gandalf produces real findings; zombie page is live. - **(C) Model-flexible execution** — Claude default; Claude orchestrates Gemini swarm sub-agents at 5:1; clean single-subscription fallback, never cross-calling.

## Actions & files produced

- Master Plan — Anchor Improvement Effort (Crucible Stage 1)
- Implementation Plan — Anchor Improvement Effort (Crucible Stage 2)

**Effort:** imported — no run metrics

## Goal & key decisions

- ## Master Plan — Anchor Improvement Effort (Crucible Stage 1)
- A brownfield Crucible planning effort (locked 2026‑06‑30, depth FULL) to make Anchor a **durable, resumable, model‑flexible** control surface. Root causes were verified against live code by 5 Gemini swarms; the Stage‑2 plan is 9 Foreman‑ready waves, gate‑passed and awaiting build.
- **North Star — three pillars**
- **(A) Resumable sessions** — leave any effort and click to carry on warm (phase + docs + skills + summary), including brownfield/discovered efforts and model‑switch handoff.
- **(B) Honest UI & warnings** — latest‑per‑tab + "previous" link, collapsed deliverables, correct terminal controls/width, warnings only on real problems, real Gandalf findings, a live zombie page.
- **(C) Model‑flexible execution** — Claude default; Claude orchestrates a Gemini swarm at 5:1; clean single‑subscription fallback, never cross‑calling.
- **13 verified fixes → 9 reordered waves** (deps precede dependents)
- **W1 — Honest warnings:** raise context budget to ~1 MB minus a fixed seed allowance (#7); zombie‑page auto‑refresh (#12a) + revive the dead embedded terminal (#12b).
- **W2 — Swarm‑warning correctness (safety‑critical):** an **owner‑liveness discriminator** — flag a registered‑running session as orphan only if identity‑alive AND no live owner (not in `_LIVE`, no running owning job, no live parent); reconcile dead records on boot. Explicitly *not* "effort‑bound ⇒ never warn" — that would neuter the hunter (#1).
- **W3 — Resume backend keystone ⭐ (Pillar A):** when no registry record/summary exists, `_build_continue_seed` synthesizes a warm seed from on‑disk docs (lane/phase + doc list + skill + summary); fold discovered efforts into the effort‑view grouping (#6/#3).
- **W4 — Resume UI:** real "resume as session" affordance on discovered cards + latest‑per‑lane inline with a "previous efforts" expander (#6/#3).
- **W5 — UI quick‑fixes:** collapse deliverables in `<details>` (#4); terminal `width:100%` + `fit()` on open (#8).
- **W6 — Terminal controls (depends W3/W4):** `×` close = stop PTY + preserve worktree/record (resumable, *not* OS suspend); one `Kill→Boneyard`; drop redundant `🗑`/`✕` (#5/#13).
- **W7 — Model‑switch handoff:** best‑effort, 5‑second‑timeout‑bounded summary → git‑ignored `SWITCH-HANDOFF.md` seeded into the new engine; never blocks the switch; fix the wrong "promoted from Grass Catchers" seed label (#9).
- **W8 — Model‑flex at the skill layer:** the 5:1 split lives in skills/sessions via `agy-dispatch`, **not** in `job_runner` (preserves the uniform‑job invariant); honest fallback — Claude‑only never spawns Gemini, Gemini‑only marks plan/build "requires Claude" (#10).
- **W9 — Gandalf map‑reduce (depends W8):** shard the tree, fan out reads through the W8 substrate, reduce to graded grouped findings + an in‑progress indicator, replacing the thin single Stage‑A pass (#2).
- Diagnosis + both Shark‑Tank rounds ran on Gemini swarms (the 5:1 split, proven live this session); Claude orchestrated.
- Gate is a deterministic ~82 s wave‑covering pytest subset, not the full suite (which times out and includes headless‑failing Playwright tests, two of which are deselected); each wave adds stubbed STUB‑GATE tests, with visual/live behavior pushed to a Playwright + screenshot SIGN‑OFF lane (the v4 rule).
- Deploy is a one‑time elevated `nssm restart anchor` after merge — not part of any wave.
- **Meta / dogfood:** every Crucible and Foreman run writes its own summary into the planning folder so this effort itself is a resumable Anchor session (the live test of Pillar A).
- `locate-plan.mjs --json` → exit 0; the doc‑trio is Foreman‑ready and **awaiting John's approval to invoke Foreman**.
- These claims are grounded in `planning/crucible-improve-2026-06-30/MASTER-PLAN.md` and `IMPLEMENTATION-PLAN.md`. Note: the unrelated `planning/anchor-v1/` docs (zombie‑hunter v2) share the "Anchor" name but are a different effort.
- ## Master Plan — Anchor Improvement Effort (Crucible Stage 1) — grounded summary
- Stage-1 Master Plan **LOCKED 2026-06-30** by J.C. Liechty after Shark-Tank Round 1; depth FULL, measured against a LOCKED `NORTH-STAR.md`. Stage-2 Implementation Plan REVISED after a second Shark-Tank and is **pending user approval → Foreman handoff**.
- Root causes were verified against real code by 5 Gemini swarms (`DIAGNOSIS.md` → CORRECTIONS); every fix carries a live `file:line` reference.
- **The three pillars (North Star)**
- **(A) Resumable sessions** — leave any effort, click to carry on (phase + docs + skills + summary); includes brownfield/discovered efforts and model-switch handoff.
- **(B) Honest UI & warnings** — latest-per-tab + "previous" link, collapsed deliverables, correct terminal controls/width, warnings only on real problems, Gandalf producing real findings, live zombie page.
- **(C) Model-flexible execution** — Claude default; Claude orchestrates a Gemini swarm at 5:1; clean single-subscription fallback, never cross-calling.
- **Key locked Stage-1 resolutions (authoritative, supersede draft)**
- **#10 (Phase 5):** the 5:1 Claude-orchestrates-Gemini swarm lives at the **skill/session layer via `agy-dispatch`**, NOT in `job_runner`. Anchor only defaults to Claude, ensures agy-dispatch is available, surfaces the split, and degrades honestly (Gemini-only → research-only; plan/build show "requires Claude").
- **#1:** reproduce-first; the naive "don't warn on effort-bound sessions" is REJECTED (neuters the hunter). Real cause = restart-survival + empty `_LIVE`; fix uses a genuine liveness signal (heartbeat / re-adopt surviving PTYs). The discriminating line is **live owner**, not effort-binding.
- **#5/#13:** `×` close = suspend PTY + preserve worktree/record (resumable); one `Kill→Boneyard`; drop the redundant `🗑`/`✕`.
- **#7:** raise the byte budget (~1 MB) + discount a fixed seed allowance (bytes-since-seed breaks on buffer truncation).
- **#9:** best-effort, timeout-bounded switch summary that never blocks the switch; gitignore the handoff doc; fix the "promoted from Grass Catchers" seed label.
- **#2 (Gandalf):** no real dependency on Phase 5; fans out via existing `job_runner`/agy-dispatch.
- **11 verified root causes mapped to fixes** — swarm false-warning (#1), fresh-session context warning (#7), restart-not-warm (#6), missing "previous efforts" link (#3), redundant panel controls (#5/#13), no model-switch handoff (#9), always-open deliverables (#4), narrow terminal (#8), stale zombie page (#12), thin Gandalf (#2), no in-product 5:1 (#10).
- **Phasing (Stage 1):** P1 Honest warnings → P2 UI correctness → P3 ⭐ Resumable sessions (keystone, dogfood: this effort's docs resume warm) → P4 Gandalf map-reduce → P5 🔨 Model-flexible execution (biggest build). P5's substrate precedes P4 so Gandalf reuses the swarm engine rather than a second bespoke fan-out.
- ## Implementation Plan (Stage 2) — grounded summary
- **9 Foreman-ready waves**, reordered so every dependency precedes its dependent: W1/W2 independent; **W3 (resume backend keystone)** precedes W4/W5/W6; W7 independent; **W8 (model-flex) precedes W9 (Gandalf)**, which fans out through W8's substrate. Each wave ships independently on merge — no big-bang; deploy = user-run `nssm restart anchor`.
- **Wave list:** W1 context-budget + zombie-page · W2 swarm-warning correctness (safety-critical) · W3 ⭐ resume-seed backend · W4 resume UI + efforts list · W5 deliverables-collapse + terminal-width · W6 terminal-controls unification · W7 model-switch handoff · W8 model-flexible execution at skill layer · W9 Gandalf map-reduce.
- **Gate model (per Anchor's v4 rule):** each wave has a deterministic **STUB GATE** (`ANCHOR_PTY_BACKEND=stub`, `ANCHOR_RUNNER_CMD`→`fake_claude.py`, temp dirs, never live `:8777`) that Foreman advances on, plus a **SIGN-OFF** (Playwright + screenshot + user) for visual/live behavior. The named `test-command` is a fast (~82 s) wave-covering subset; two Playwright tests are deselected (full suite times out >10 min headless).
- **Build constraints:** one app (`anchor_gui.py`, Python stdlib + siblings), no new third-party deps (lone `pywinpty` exception, enforced by `distro.py`); the Foreman build itself runs Claude-driver + Gemini swarm via agy-dispatch.
- **Meta-requirement (dogfood Pillar A):** every Crucible and Foreman run writes its own summary into the planning folder so the effort is itself a resumable Anchor session.
- **Handoff:** `MASTER-PLAN.md` + `IMPLEMENTATION-PLAN.md` + `EXECUTION-LOG.md` form the doc-trio in `foreman.config.json`; the handoff is gated on `locate-plan.mjs --json <dir>` exiting 0.

## Files

- [Master Plan — Anchor Improvement Effort (Crucible Stage 1)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fcrucible-improve-2026-06-30%2FMASTER-PLAN.md)
- [Implementation Plan — Anchor Improvement Effort (Crucible Stage 2)](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fcrucible-improve-2026-06-30%2FIMPLEMENTATION-PLAN.md)
